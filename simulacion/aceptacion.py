"""V3 — Motor de aceptación de viajes (capa comercial sobre la asignación académica).

La asignación académica (RF-04 + RF-05) **no cambia**: ``Despachador.solicitar_viaje``
sigue asignando directamente el menor ETA entre los k candidatos. Este motor la
reutiliza para obtener y ordenar los candidatos y añade lo que ocurre en una
aplicación real: el conductor puede aceptar, rechazar o no responder.

Flujo por solicitud:

1. k candidatos disponibles con el Quadtree + Haversine; ETA con un Dijkstra
   inverso propio (``Despachador.buscar_candidatos`` y ``calcular_eta``).
2. Se ordenan por (ETA, distancia recta, id). El primero es el **óptimo
   académico dentro de k**; se guarda para compararlo con el resultado operativo.
3. Se envía una oferta al primer candidato todavía disponible: pasa a
   ``OFERTA_PENDIENTE`` (sale de la búsqueda de disponibles, así nadie más se lo
   puede asignar ni ofrecer).
4. En los turnos siguientes llega su respuesta según su **política**:
   ``automatica`` (acepta), ``probabilistica`` (acepta con probabilidad p),
   ``rechazo`` (rechaza) o ``sin_respuesta`` (la oferta vence a los
   ``plazo_oferta_turnos``).
5. Si acepta: ``ACEPTADO`` → ``EN_CAMINO`` con su ruta recalculada desde donde
   está. Si rechaza o vence: vuelve a ``DISPONIBLE`` y se ofrece al siguiente.
   Si nadie acepta, la solicitud termina como ``sin_aceptacion``.

**Reproducibilidad:** la decisión de cada conductor ante cada solicitud usa un
generador propio sembrado con ``(semilla, solicitud, conductor)``. No consume el
generador de la simulación y no depende del orden en que se procesen las ofertas.
Los benchmarks académicos no usan este motor.
"""
from __future__ import annotations

import math
import random
from dataclasses import asdict, dataclass, field

from simulacion.despachador import Candidato, Despachador
from simulacion.modelos import Conductor, EstadoConductor, Pasajero

POLITICAS = ("automatica", "probabilistica", "rechazo", "sin_respuesta")


def asignar_politicas(flota: list[Conductor], semilla: int, distribucion) -> None:
    """Asigna una política a cada conductor con un generador propio (no altera la flota académica)."""
    generador = random.Random(f"politicas-{semilla}")
    nombres = [p for p, _ in distribucion]
    pesos = [w for _, w in distribucion]
    if any(p not in POLITICAS for p in nombres):
        raise ValueError(f"Política desconocida en {nombres}")
    for conductor in flota:
        conductor.politica = generador.choices(nombres, weights=pesos)[0]


@dataclass
class Oferta:
    solicitud_id: int
    pasajero: dict
    candidatos: list[dict]                 # ordenados por ETA (óptimo académico primero)
    indice: int = -1                       # candidato al que se hizo la oferta vigente
    conductor_id: int | None = None
    turno_envio: int = 0
    turno_respuesta: int = 0
    decision: str = ""                     # acepta | rechaza | sin_respuesta
    intentos: list[dict] = field(default_factory=list)

    @property
    def academico(self) -> dict | None:
        return self.candidatos[0] if self.candidatos else None

    def a_diccionario(self) -> dict:
        return asdict(self)


class MotorAceptacion:
    def __init__(self, despachador: Despachador, semilla: int, plazo_turnos: int = 2,
                 probabilidad_aceptacion: float = 0.8) -> None:
        if plazo_turnos < 1:
            raise ValueError("El plazo de la oferta debe ser de al menos un turno")
        self.despachador = despachador
        self.semilla = semilla
        self.plazo_turnos = plazo_turnos
        self.probabilidad_aceptacion = probabilidad_aceptacion
        self.ofertas: dict[int, Oferta] = {}

    # ------------------------------------------------------------ decisión
    def decidir(self, conductor: Conductor, solicitud_id: int) -> tuple[str, int]:
        """(decisión, turnos hasta la respuesta). Determinista para (semilla, solicitud, conductor)."""
        generador = random.Random(f"{self.semilla}-{solicitud_id}-{conductor.id}")
        if conductor.politica == "automatica":
            return "acepta", 1
        if conductor.politica == "rechazo":
            return "rechaza", 1
        if conductor.politica == "sin_respuesta":
            return "sin_respuesta", self.plazo_turnos
        acepta = generador.random() < self.probabilidad_aceptacion
        return ("acepta" if acepta else "rechaza"), generador.randint(1, self.plazo_turnos)

    # ----------------------------------------------------------- solicitud
    def iniciar(self, pasajero: Pasajero, solicitud_id: int, turno: int, k: int | None = None) -> Oferta | None:
        """Busca candidatos y envía la primera oferta. ``None`` si no hay ninguno alcanzable."""
        with self.despachador._candado:
            candidatos = self.despachador.buscar_candidatos(pasajero, k)
            self.despachador.calcular_eta(pasajero, candidatos)
            alcanzables = sorted((c for c in candidatos if c.alcanzable),
                                 key=lambda c: (c.eta_s, c.distancia_recta_m, c.conductor_id))
            if not alcanzables:
                return None
            oferta = Oferta(solicitud_id, _pasajero_a_diccionario(pasajero),
                            [_candidato(c) for c in alcanzables])
            self.ofertas[solicitud_id] = oferta
            self._ofrecer_siguiente(oferta, turno)
            return oferta

    def _ofrecer_siguiente(self, oferta: Oferta, turno: int) -> bool:
        while oferta.indice + 1 < len(oferta.candidatos):
            oferta.indice += 1
            cid = oferta.candidatos[oferta.indice]["conductor_id"]
            conductor = self.despachador.conductores.get(cid)
            if conductor is None or not conductor.esta_disponible:
                oferta.intentos.append({"conductor_id": cid, "resultado": "no_disponible", "turno": turno})
                continue
            self.despachador.cambiar_estado(cid, EstadoConductor.OFERTA_PENDIENTE)
            conductor.ruta = []  # mientras decide, se detiene
            conductor.avance_m = 0.0
            decision, retraso = self.decidir(conductor, oferta.solicitud_id)
            oferta.conductor_id = cid
            oferta.turno_envio = turno
            oferta.turno_respuesta = turno + retraso
            oferta.decision = decision
            return True
        oferta.conductor_id = None
        return False

    # -------------------------------------------------------------- turno
    def procesar_turno(self, turno: int) -> list[dict]:
        """Resuelve las respuestas que vencen en este turno. Devuelve eventos para el worker."""
        eventos = []
        with self.despachador._candado:
            for solicitud_id in sorted(self.ofertas):
                oferta = self.ofertas[solicitud_id]
                if oferta.conductor_id is None or turno < oferta.turno_respuesta:
                    continue
                cid = oferta.conductor_id
                resultado = oferta.decision if oferta.decision == "acepta" else (
                    "vencida" if oferta.decision == "sin_respuesta" else "rechaza")
                oferta.intentos.append({"conductor_id": cid, "resultado": resultado, "turno": turno})
                if resultado == "acepta" and self._confirmar(oferta, cid):
                    eventos.append({"tipo": "oferta_aceptada", "solicitud_id": solicitud_id, "conductor_id": cid,
                                    "oferta": oferta.a_diccionario()})
                    del self.ofertas[solicitud_id]
                    continue
                if self.despachador.conductores[cid].estado is EstadoConductor.OFERTA_PENDIENTE:
                    self.despachador.cambiar_estado(cid, EstadoConductor.DISPONIBLE)
                eventos.append({"tipo": f"oferta_{resultado}", "solicitud_id": solicitud_id, "conductor_id": cid})
                if not self._ofrecer_siguiente(oferta, turno):
                    eventos.append({"tipo": "sin_aceptacion", "solicitud_id": solicitud_id,
                                    "oferta": oferta.a_diccionario()})
                    del self.ofertas[solicitud_id]
        return eventos

    def _confirmar(self, oferta: Oferta, cid: int) -> bool:
        """El conductor aceptó: se recalcula su ETA desde su posición actual y sale hacia el pasajero."""
        despachador = self.despachador
        pasajero = _pasajero_desde_diccionario(oferta.pasajero)
        candidato = Candidato(cid, oferta.candidatos[oferta.indice]["distancia_recta_m"])
        despachador.calcular_eta(pasajero, [candidato])
        if not candidato.alcanzable:
            return False
        despachador.cambiar_estado(cid, EstadoConductor.ACEPTADO)
        conductor = despachador.conductores[cid]
        conductor.ruta = list(candidato.ruta[1:])
        conductor.avance_m = 0.0
        conductor.solicitud_id = oferta.solicitud_id
        conductor.destino_nodo = pasajero.destino_nodo
        despachador.cambiar_estado(cid, EstadoConductor.EN_CAMINO)
        oferta.candidatos[oferta.indice].update(eta_confirmado_s=candidato.eta_s,
                                                distancia_confirmada_m=candidato.distancia_calles_m,
                                                ruta=candidato.ruta)
        return True

    def cancelar(self, solicitud_id: int) -> bool:
        """El pasajero canceló mientras se buscaba conductor: se libera la reserva."""
        with self.despachador._candado:
            oferta = self.ofertas.pop(solicitud_id, None)
            if oferta is None:
                return False
            cid = oferta.conductor_id
            if cid is not None and self.despachador.conductores[cid].estado is EstadoConductor.OFERTA_PENDIENTE:
                self.despachador.cambiar_estado(cid, EstadoConductor.DISPONIBLE)
            return True

    # ------------------------------------------------------- persistencia
    def a_diccionario(self) -> list[dict]:
        return [o.a_diccionario() for o in self.ofertas.values()]

    def restaurar(self, datos: list[dict]) -> None:
        self.ofertas = {d["solicitud_id"]: Oferta(**d) for d in datos}


def _candidato(c: Candidato) -> dict:
    return {"conductor_id": c.conductor_id, "codigo": f"LG-{c.conductor_id:05d}",
            "distancia_recta_m": c.distancia_recta_m, "distancia_calles_m": c.distancia_calles_m,
            "eta_s": c.eta_s}


def _pasajero_a_diccionario(p: Pasajero) -> dict:
    return asdict(p)


def _pasajero_desde_diccionario(d: dict) -> Pasajero:
    return Pasajero(**d)


def resumen_oferta(oferta: dict) -> dict:
    """Comparación académica (óptimo en k) frente a la operativa (quien aceptó)."""
    academico = oferta["candidatos"][0]
    elegido = oferta["candidatos"][oferta["indice"]] if oferta.get("indice", -1) >= 0 else None
    return {
        "conductor_academico": academico["conductor_id"],
        "eta_academico_s": academico["eta_s"],
        "conductor_operativo": elegido["conductor_id"] if elegido else None,
        "eta_operativo_s": elegido.get("eta_confirmado_s", elegido["eta_s"]) if elegido else None,
        "intentos": len(oferta["intentos"]),
        "coincide": bool(elegido) and elegido["conductor_id"] == academico["conductor_id"],
        "diferencia_eta_s": (elegido.get("eta_confirmado_s", elegido["eta_s"]) - academico["eta_s"])
        if elegido and not math.isinf(academico["eta_s"]) else None,
    }
