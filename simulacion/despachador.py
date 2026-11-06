"""Despachador: coordina búsqueda de candidatos, cálculo de ETA y asignación.

Flujo de una solicitud (RF-04 + RF-05):

1. Ubicar al pasajero en la intersección más cercana usando un Quadtree de
   intersecciones (no se usa ``osmnx.nearest_nodes``, que depende de un
   índice espacial ya hecho).
2. Obtener los k conductores **disponibles** más cercanos en línea recta con el
   Quadtree de conductores + heap (Haversine propio).
3. Ejecutar **un** Dijkstra sobre el grafo invertido desde el pasajero para
   obtener la distancia por calles de los k candidatos respetando los sentidos.
4. Convertir distancias a ETA y elegir el **menor ETA** (no necesariamente el
   más cercano en línea recta).
5. Marcar al conductor como ocupado en la flota y en el Quadtree dentro de una
   sección crítica para impedir asignaciones duplicadas.
"""
from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass, field

from algoritmos.asignacion_multiple import algoritmo_hungaro, asignacion_codiciosa, costo_total
from algoritmos.congestion import PesosDinamicos
from algoritmos.dijkstra import distancias_hacia_destino, eta_segundos, reconstruir_ruta_hacia
from algoritmos.grafo import GrafoVial
from config.ajustes import Ajustes
from estructuras.geografia import Rectangulo, validar_coordenadas
from estructuras.quadtree import Quadtree
from simulacion.errores import CoordenadasInvalidas, FueraDeCobertura, SinConexionVial
from simulacion.modelos import Conductor, EstadoConductor, Pasajero


@dataclass
class Candidato:
    conductor_id: int
    distancia_recta_m: float
    distancia_calles_m: float = math.inf
    eta_s: float = math.inf
    ruta: list[int] = field(default_factory=list)

    @property
    def alcanzable(self) -> bool:
        return not math.isinf(self.eta_s)

    def a_diccionario(self) -> dict:
        return {
            "conductor_id": self.conductor_id,
            "codigo": f"LG-{self.conductor_id:05d}",
            "distancia_recta_m": round(self.distancia_recta_m, 1),
            "distancia_calles_m": None if math.isinf(self.distancia_calles_m) else round(self.distancia_calles_m, 1),
            "eta_s": None if math.isinf(self.eta_s) else round(self.eta_s, 1),
            "alcanzable": self.alcanzable,
        }


@dataclass
class ResultadoAsignacion:
    estado: str  # asignado | sin_conductores | sin_ruta
    mensaje: str
    pasajero: Pasajero
    candidatos: list[Candidato] = field(default_factory=list)
    seleccionado: Candidato | None = None
    ruta_coordenadas: list[tuple[float, float]] = field(default_factory=list)
    tiempo_ms: float = 0.0
    nodos_explorados: int = 0

    @property
    def exito(self) -> bool:
        return self.estado == "asignado"


class Despachador:
    """Coordina la asignación del conductor de menor ETA."""

    def __init__(self, grafo: GrafoVial, conductores: list[Conductor], ajustes: Ajustes,
                 nodos_validos: set[int] | None = None) -> None:
        self.grafo = grafo
        self.ajustes = ajustes
        self.velocidad_kmh = ajustes.velocidad_promedio_kmh
        self.nodos_validos = nodos_validos if nodos_validos is not None else grafo.componente_principal()
        self.limites: Rectangulo = grafo.limites()
        self._candado = threading.RLock()
        self.hora_actual = ajustes.hora_inicio_simulacion
        self.pesos_dinamicos = PesosDinamicos(grafo) if ajustes.congestion_activa else None
        # Índice propio de intersecciones para ubicar pasajeros sobre la red.
        self.indice_intersecciones = Quadtree(self.limites, capacidad=16, profundidad_maxima=22)
        for nodo in sorted(self.nodos_validos):
            lat, lon = grafo.coordenadas(nodo)
            self.indice_intersecciones.insertar(nodo, lat, lon, True)
        self.conductores: dict[int, Conductor] = {}
        self.quadtree = Quadtree(self.limites, ajustes.capacidad_nodo, ajustes.profundidad_maxima)
        for conductor in conductores:
            self.registrar_conductor(conductor)

    # --------------------------------------------------------------- flota
    def registrar_conductor(self, conductor: Conductor) -> None:
        with self._candado:
            if conductor.id in self.conductores:
                raise ValueError(f"Conductor duplicado: {conductor.id}")
            self.conductores[conductor.id] = conductor
            self.quadtree.insertar(conductor.id, conductor.lat, conductor.lon, conductor.esta_disponible)

    def retirar_conductor(self, conductor_id: int) -> None:
        with self._candado:
            self.conductores.pop(conductor_id)
            self.quadtree.eliminar(conductor_id)

    def mover_conductor(self, conductor_id: int, nodo: int) -> None:
        """Ubica al conductor en otra intersección y actualiza el Quadtree en la misma operación."""
        with self._candado:
            conductor = self.conductores[conductor_id]
            lat, lon = self.grafo.coordenadas(nodo)
            conductor.nodo, conductor.lat, conductor.lon = nodo, lat, lon
            self.quadtree.actualizar_posicion(conductor_id, lat, lon)

    def cambiar_estado(self, conductor_id: int, estado: EstadoConductor) -> None:
        with self._candado:
            conductor = self.conductores[conductor_id]
            conductor.estado = estado
            self.quadtree.cambiar_disponibilidad(conductor_id, estado is EstadoConductor.DISPONIBLE)

    def liberar_conductor(self, conductor_id: int) -> None:
        with self._candado:
            conductor = self.conductores[conductor_id]
            conductor.ruta = []
            conductor.solicitud_id = None
            conductor.destino_nodo = None
            conductor.avance_m = 0.0
            self.cambiar_estado(conductor_id, EstadoConductor.DISPONIBLE)

    def conteo_estados(self) -> dict[str, int]:
        conteo = {estado.value: 0 for estado in EstadoConductor}
        for conductor in self.conductores.values():
            conteo[conductor.estado.value] += 1
        return conteo

    # ------------------------------------------------------------ pasajeros
    def ubicar_en_red(self, lat: float, lon: float) -> tuple[int, float]:
        """Intersección conectada más cercana. Lanza errores de ubicación con mensaje claro."""
        try:
            validar_coordenadas(lat, lon)
        except ValueError as error:
            raise CoordenadasInvalidas(str(error)) from error
        if not self.limites.contiene(lat, lon):
            raise FueraDeCobertura("La ubicación está fuera de la zona de cobertura de Miraflores")
        mas_cercano = self.indice_intersecciones.vecino_mas_cercano(lat, lon)
        if mas_cercano is None:
            raise SinConexionVial("No hay calles disponibles en la red")
        distancia, nodo = mas_cercano
        if distancia > self.ajustes.distancia_maxima_conexion_m:
            raise SinConexionVial(
                f"La ubicación está a {distancia:.0f} m de la calle más cercana; elige un punto junto a una vía"
            )
        return nodo, distancia

    def crear_pasajero(self, identificador: int, lat: float, lon: float, direccion: str = "",
                       destino: tuple[float, float] | None = None, destino_direccion: str = "") -> Pasajero:
        nodo, distancia = self.ubicar_en_red(lat, lon)
        pasajero = Pasajero(id=identificador, lat=float(lat), lon=float(lon), nodo=nodo,
                            distancia_a_red_m=distancia, direccion=direccion)
        if destino is not None:
            nodo_destino, _ = self.ubicar_en_red(*destino)
            pasajero.destino_lat, pasajero.destino_lon = float(destino[0]), float(destino[1])
            pasajero.destino_nodo = nodo_destino
            pasajero.destino_direccion = destino_direccion
        return pasajero

    # ------------------------------------------------------------- búsqueda
    def buscar_candidatos(self, pasajero: Pasajero, k: int | None = None) -> list[Candidato]:
        """RF-04: k conductores disponibles más cercanos en línea recta (Quadtree + heap)."""
        k = k or self.ajustes.k_candidatos
        return [Candidato(cid, d) for d, cid in self.quadtree.buscar_k_cercanos(pasajero.lat, pasajero.lon, k)]

    def _adyacencias(self):
        if self.pesos_dinamicos is not None:
            return self.pesos_dinamicos.adyacencias(self.hora_actual)
        return self.grafo.adyacencia, self.grafo.inversa

    def calcular_eta(self, pasajero: Pasajero, candidatos: list[Candidato]) -> int:
        """RF-05: distancia por calles y ETA de cada candidato con un Dijkstra sobre el grafo invertido.

        Devuelve el número de nodos explorados.
        """
        if not candidatos:
            return 0
        _, inversa = self._adyacencias()
        nodos = {c.conductor_id: self.conductores[c.conductor_id].nodo for c in candidatos}
        resultado = distancias_hacia_destino(inversa, pasajero.nodo, nodos.values())
        for candidato in candidatos:
            nodo = nodos[candidato.conductor_id]
            if nodo not in resultado.asentados:
                continue  # inaccesible por calles: ETA infinito
            ruta = reconstruir_ruta_hacia(resultado.predecesores, nodo, pasajero.nodo) or [nodo]
            candidato.ruta = ruta
            candidato.distancia_calles_m = self.grafo.longitud_ruta(ruta)
            if self.pesos_dinamicos is not None:
                candidato.eta_s = resultado.distancias[nodo]  # pesos en segundos
            else:
                candidato.eta_s = eta_segundos(candidato.distancia_calles_m, self.velocidad_kmh)
        return resultado.nodos_explorados

    @staticmethod
    def elegir_mejor(candidatos: list[Candidato]) -> Candidato | None:
        """Menor ETA; empates por menor distancia recta y luego por id."""
        alcanzables = [c for c in candidatos if c.alcanzable]
        if not alcanzables:
            return None
        return min(alcanzables, key=lambda c: (c.eta_s, c.distancia_recta_m, c.conductor_id))

    # ----------------------------------------------------------- asignación
    def solicitar_viaje(self, pasajero: Pasajero, k: int | None = None, solicitud_id: int | None = None,
                        expansiones: int = 3) -> ResultadoAsignacion:
        """Asigna el conductor de menor ETA. Operación atómica respecto a otras solicitudes."""
        inicio = time.perf_counter()
        k = k or self.ajustes.k_candidatos
        with self._candado:
            candidatos: list[Candidato] = []
            explorados = 0
            k_actual = k
            for _ in range(expansiones + 1):
                candidatos = self.buscar_candidatos(pasajero, k_actual)
                if not candidatos:
                    break
                explorados += self.calcular_eta(pasajero, candidatos)
                if any(c.alcanzable for c in candidatos) or len(candidatos) < k_actual:
                    break
                k_actual *= 2  # todos inaccesibles: se amplía la búsqueda
            duracion = (time.perf_counter() - inicio) * 1000
            if not candidatos:
                return ResultadoAsignacion("sin_conductores", "No hay conductores disponibles en este momento",
                                           pasajero, [], None, [], duracion, explorados)
            mejor = self.elegir_mejor(candidatos)
            if mejor is None:
                return ResultadoAsignacion("sin_ruta", "Ningún conductor cercano puede llegar por calles a tu ubicación",
                                           pasajero, candidatos, None, [], duracion, explorados)
            self._ocupar(mejor, pasajero, solicitud_id)
            return ResultadoAsignacion("asignado", f"Conductor LG-{mejor.conductor_id:05d} asignado", pasajero,
                                       candidatos, mejor, self.grafo.geometria_ruta(mejor.ruta),
                                       (time.perf_counter() - inicio) * 1000, explorados)

    def _ocupar(self, candidato: Candidato, pasajero: Pasajero, solicitud_id: int | None) -> None:
        conductor = self.conductores[candidato.conductor_id]
        if not conductor.esta_disponible:  # defensa ante asignaciones duplicadas
            raise RuntimeError(f"El conductor {conductor.id} ya está ocupado")
        conductor.ruta = list(candidato.ruta[1:])
        conductor.avance_m = 0.0
        conductor.solicitud_id = solicitud_id
        conductor.destino_nodo = pasajero.destino_nodo
        self.cambiar_estado(conductor.id, EstadoConductor.EN_CAMINO)

    # ------------------------------------------------- Reto C: varios pasajeros
    def matriz_eta(self, pasajeros: list[Pasajero], k: int | None = None) -> tuple[list[int], list[list[float]]]:
        """Conductores candidatos (unión de los k más cercanos de cada pasajero) y matriz de ETA."""
        k = max(k or self.ajustes.k_candidatos, len(pasajeros))
        ids: set[int] = set()
        for pasajero in pasajeros:
            ids.update(c.conductor_id for c in self.buscar_candidatos(pasajero, k))
        columnas = sorted(ids)
        matriz: list[list[float]] = []
        for pasajero in pasajeros:
            candidatos = [Candidato(cid, 0.0) for cid in columnas]
            self.calcular_eta(pasajero, candidatos)
            matriz.append([c.eta_s for c in candidatos])
        return columnas, matriz

    def asignar_varios(self, pasajeros: list[Pasajero], k: int | None = None, estrategia: str = "optima",
                       solicitud_ids: list[int] | None = None) -> dict:
        """Asigna simultáneamente minimizando la espera total (húngaro) o de forma codiciosa."""
        with self._candado:
            columnas, matriz = self.matriz_eta(pasajeros, k)
            if not columnas:
                return {"estrategia": estrategia, "asignaciones": [], "espera_total_s": 0.0, "sin_asignar": len(pasajeros)}
            if estrategia == "optima":
                filas_extra = len(pasajeros) - len(columnas)
                if filas_extra > 0:  # más pasajeros que conductores: columnas ficticias
                    matriz_ext = [fila + [math.inf] * filas_extra for fila in matriz]
                    asignacion = algoritmo_hungaro(matriz_ext)
                else:
                    asignacion = algoritmo_hungaro(matriz)
            elif estrategia == "codiciosa":
                asignacion = asignacion_codiciosa(matriz)
            else:
                raise ValueError("Estrategia desconocida")
            asignaciones = []
            for i, j in enumerate(asignacion):
                if j < 0 or j >= len(columnas) or math.isinf(matriz[i][j]):
                    asignaciones.append({"pasajero_id": pasajeros[i].id, "conductor_id": None, "eta_s": None})
                    continue
                asignaciones.append({"pasajero_id": pasajeros[i].id, "conductor_id": columnas[j], "eta_s": matriz[i][j]})
            validas = [a for a in asignaciones if a["conductor_id"] is not None]
            total = costo_total(matriz, [j if j < len(columnas) and not math.isinf(matriz[i][j]) else -1
                                         for i, j in enumerate(asignacion)])
            return {
                "estrategia": estrategia,
                "asignaciones": asignaciones,
                "espera_total_s": total,
                "sin_asignar": len(asignaciones) - len(validas),
                "conductores_evaluados": len(columnas),
            }

    def confirmar_asignaciones(self, pasajeros: list[Pasajero], plan: dict,
                               solicitud_ids: list[int] | None = None) -> list[ResultadoAsignacion]:
        """Aplica un plan de ``asignar_varios`` marcando a los conductores como ocupados."""
        resultados = []
        with self._candado:
            for indice, (pasajero, item) in enumerate(zip(pasajeros, plan["asignaciones"])):
                sid = solicitud_ids[indice] if solicitud_ids else None
                if item["conductor_id"] is None:
                    resultados.append(ResultadoAsignacion("sin_conductores", "Sin conductor disponible", pasajero))
                    continue
                candidato = Candidato(item["conductor_id"], 0.0)
                self.calcular_eta(pasajero, [candidato])
                self._ocupar(candidato, pasajero, sid)
                resultados.append(ResultadoAsignacion("asignado", "Asignado", pasajero, [candidato], candidato,
                                                      self.grafo.geometria_ruta(candidato.ruta)))
        return resultados

    # ---------------------------------------------------------- consistencia
    def verificar_consistencia(self) -> None:
        """La flota y el Quadtree deben describir exactamente lo mismo."""
        self.quadtree.verificar_consistencia()
        assert len(self.quadtree) == len(self.conductores)
        for conductor in self.conductores.values():
            assert self.quadtree.obtener_posicion(conductor.id) == (conductor.lat, conductor.lon)
            assert self.quadtree.esta_disponible(conductor.id) == conductor.esta_disponible
            assert self.grafo.coordenadas(conductor.nodo) == (conductor.lat, conductor.lon)
        ocupados_por_solicitud: dict[int, int] = {}
        for conductor in self.conductores.values():
            if conductor.solicitud_id is not None and conductor.estado.ocupado:
                assert conductor.solicitud_id not in ocupados_por_solicitud, "solicitud con dos conductores"
                ocupados_por_solicitud[conductor.solicitud_id] = conductor.id
