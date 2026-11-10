"""Persistencia y mecanismo explícito de coordinación backend ↔ worker.

Coordinación (una sola versión de la flota):

* El **worker** es el único proceso que tiene la flota y el Quadtree en
  memoria y el único que los modifica.
* El **backend** nunca modifica la flota: inserta filas en ``comandos`` (cola)
  y espera su resultado; para mostrar el mapa lee la última fila de
  ``estado_simulacion`` (instantánea versionada que el worker reescribe tras cada
  turno o comando).
* Los comandos se procesan en orden de llegada por un único consumidor, por lo
  que dos solicitudes simultáneas nunca pueden recibir el mismo conductor.

Funciona igual con PostgreSQL (Docker) y con SQLite (ejecución local y pruebas).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (JSON, Boolean, Column, DateTime, Float, Integer, MetaData, String, Table, Text, create_engine,
                        event, func, insert, inspect, select, text, update)
from sqlalchemy.engine import Engine

metadatos = MetaData()

comandos = Table(
    "comandos", metadatos,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("tipo", String(40), nullable=False),
    Column("carga", JSON, nullable=False, default=dict),
    Column("estado", String(20), nullable=False, default="pendiente", index=True),  # pendiente|hecho|error
    Column("resultado", JSON),
    Column("error_codigo", String(60)),
    Column("error_mensaje", Text),
    Column("creado_en", DateTime(timezone=True), nullable=False),
    Column("procesado_en", DateTime(timezone=True)),
)

solicitudes = Table(
    "solicitudes", metadatos,
    Column("id", Integer, primary_key=True, autoincrement=False),
    Column("canal", String(20), nullable=False, index=True),  # app | simulacion
    Column("estado", String(30), nullable=False, index=True),
    Column("origen_texto", Text, default=""),
    Column("origen_lat", Float),
    Column("origen_lon", Float),
    Column("destino_texto", Text, default=""),
    Column("destino_lat", Float),
    Column("destino_lon", Float),
    Column("conductor_id", Integer),
    Column("eta_s", Float),
    Column("distancia_calles_m", Float),
    Column("distancia_recta_m", Float),
    Column("candidatos", JSON),
    Column("ruta_recogida", JSON),
    Column("ruta_viaje", JSON),
    Column("mensaje", Text, default=""),
    Column("turno_solicitud", Integer),
    Column("turno_recogida", Integer),
    Column("turno_fin", Integer),
    # --- V2 (añadidas con migración ligera, ver BaseDatos._migrar) ---
    Column("distancia_viaje_m", Float),
    Column("duracion_viaje_s", Float),
    Column("tarifa_estimada", Float),
    Column("recogida_en", DateTime(timezone=True)),
    Column("finalizada_en", DateTime(timezone=True)),
    # --- V3 ---
    Column("distrito_origen", String(80)),
    Column("distrito_destino", String(80)),
    Column("tarifa_desglose", JSON),
    Column("cotizacion_id", String(40)),
    Column("intentos", JSON),
    Column("conductor_academico_id", Integer),
    Column("eta_academico_s", Float),
    Column("asignada_en", DateTime(timezone=True)),
    Column("creada_en", DateTime(timezone=True), nullable=False),
    Column("actualizada_en", DateTime(timezone=True), nullable=False),
)

cotizaciones = Table(
    "cotizaciones", metadatos,
    Column("id", String(40), primary_key=True),
    Column("datos", JSON, nullable=False),
    Column("creada_en", DateTime(timezone=True), nullable=False),
    Column("usada", Boolean, nullable=False, default=False),
)

alertas = Table(
    "alertas", metadatos,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("solicitud_id", Integer, nullable=False, index=True),
    Column("estado", String(20), nullable=False, default="abierta"),  # abierta | atendida
    Column("lat", Float),
    Column("lon", Float),
    Column("estado_viaje", String(30)),
    Column("conductor_id", Integer),
    Column("unidad", String(20)),
    Column("distancia_unidad_m", Float),
    Column("nota", Text, default=""),
    Column("creada_en", DateTime(timezone=True), nullable=False),
    Column("atendida_en", DateTime(timezone=True)),
)

estado_simulacion = Table(
    "estado_simulacion", metadatos,
    Column("id", Integer, primary_key=True, autoincrement=False),
    Column("version", Integer, nullable=False, default=0),
    Column("turno", Integer, nullable=False, default=0),
    Column("en_pausa", Boolean, nullable=False, default=False),
    Column("hora_simulada", Float),
    Column("instantanea", JSON, nullable=False),
    Column("actualizado_en", DateTime(timezone=True), nullable=False),
    Column("latido_en", DateTime(timezone=True), nullable=False),
)


#: Estados de una solicitud que todavía no terminó (V3 añade búsqueda y espera en el punto de recojo).
ESTADOS_ACTIVOS = ["buscando", "asignada", "esperando_recogida", "en_viaje"]


def ahora() -> datetime:
    return datetime.now(timezone.utc)


def _como_utc(valor: datetime | None) -> datetime | None:
    if valor is not None and valor.tzinfo is None:  # SQLite devuelve fechas sin zona
        return valor.replace(tzinfo=timezone.utc)
    return valor


class BaseDatos:
    def __init__(self, url: str) -> None:
        argumentos: dict[str, Any] = {"pool_pre_ping": True}
        if url.startswith("sqlite"):
            argumentos["connect_args"] = {"check_same_thread": False, "timeout": 30}
        self.motor: Engine = create_engine(url, **argumentos)
        if url.startswith("sqlite"):
            @event.listens_for(self.motor, "connect")
            def _pragmas(conexion, _registro):  # pragma: no cover - configuración del motor
                cursor = conexion.cursor()
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA synchronous=NORMAL")
                cursor.close()

    def crear_tablas(self) -> None:
        metadatos.create_all(self.motor)
        self._migrar()

    def _migrar(self) -> None:
        """Agrega columnas nuevas a tablas creadas por versiones anteriores (``create_all`` no lo hace)."""
        inspector = inspect(self.motor)
        for tabla in metadatos.sorted_tables:
            existentes = {c["name"] for c in inspector.get_columns(tabla.name)}
            faltantes = [c for c in tabla.columns if c.name not in existentes]
            if not faltantes:
                continue
            with self.motor.begin() as conexion:
                for columna in faltantes:
                    tipo = columna.type.compile(dialect=self.motor.dialect)
                    conexion.execute(text(f'ALTER TABLE {tabla.name} ADD COLUMN {columna.name} {tipo}'))

    def comprobar(self) -> bool:
        with self.motor.connect() as conexion:
            conexion.execute(select(1))
        return True

    # -------------------------------------------------------------- comandos
    def encolar_comando(self, tipo: str, carga: dict | None = None) -> int:
        with self.motor.begin() as conexion:
            resultado = conexion.execute(insert(comandos).values(tipo=tipo, carga=carga or {}, estado="pendiente",
                                                                 creado_en=ahora()))
            return int(resultado.inserted_primary_key[0])

    def obtener_comando(self, comando_id: int) -> dict | None:
        with self.motor.connect() as conexion:
            fila = conexion.execute(select(comandos).where(comandos.c.id == comando_id)).mappings().first()
            return dict(fila) if fila else None

    def comandos_pendientes(self, limite: int = 50) -> list[dict]:
        with self.motor.connect() as conexion:
            filas = conexion.execute(select(comandos).where(comandos.c.estado == "pendiente")
                                     .order_by(comandos.c.id).limit(limite)).mappings().all()
            return [dict(f) for f in filas]

    def cerrar_comando(self, comando_id: int, estado: str, resultado: dict | None = None,
                       error_codigo: str | None = None, error_mensaje: str | None = None) -> None:
        with self.motor.begin() as conexion:
            conexion.execute(update(comandos).where(comandos.c.id == comando_id).values(
                estado=estado, resultado=resultado, error_codigo=error_codigo, error_mensaje=error_mensaje,
                procesado_en=ahora()))

    # ---------------------------------------------------------- instantánea
    def guardar_instantanea(self, instantanea: dict) -> int:
        momento = ahora()
        with self.motor.begin() as conexion:
            actual = conexion.execute(select(estado_simulacion.c.version).where(estado_simulacion.c.id == 1)).first()
            valores = {"turno": instantanea["turno"], "en_pausa": instantanea["en_pausa"],
                       "hora_simulada": instantanea["hora_simulada"], "instantanea": instantanea,
                       "actualizado_en": momento, "latido_en": momento}
            if actual is None:
                conexion.execute(insert(estado_simulacion).values(id=1, version=1, **valores))
                return 1
            version = actual[0] + 1
            conexion.execute(update(estado_simulacion).where(estado_simulacion.c.id == 1).values(version=version,
                                                                                                 **valores))
            return version

    def latido(self) -> None:
        with self.motor.begin() as conexion:
            conexion.execute(update(estado_simulacion).where(estado_simulacion.c.id == 1).values(latido_en=ahora()))

    def leer_estado(self) -> dict | None:
        with self.motor.connect() as conexion:
            fila = conexion.execute(select(estado_simulacion).where(estado_simulacion.c.id == 1)).mappings().first()
            if not fila:
                return None
            datos = dict(fila)
            datos["latido_en"] = _como_utc(datos["latido_en"])
            datos["actualizado_en"] = _como_utc(datos["actualizado_en"])
            return datos

    def latido_estado(self):
        with self.motor.connect() as conexion:
            fila = conexion.execute(select(estado_simulacion.c.latido_en).where(estado_simulacion.c.id == 1)).first()
            return _como_utc(fila[0]) if fila else None

    def version_estado(self) -> int | None:
        with self.motor.connect() as conexion:
            fila = conexion.execute(select(estado_simulacion.c.version, estado_simulacion.c.latido_en)
                                    .where(estado_simulacion.c.id == 1)).first()
            return fila[0] if fila else None

    # ---------------------------------------------------------- solicitudes
    def insertar_solicitud(self, **valores) -> None:
        momento = ahora()
        with self.motor.begin() as conexion:
            conexion.execute(insert(solicitudes).values(creada_en=momento, actualizada_en=momento, **valores))

    def actualizar_solicitud(self, solicitud_id: int, **valores) -> None:
        with self.motor.begin() as conexion:
            conexion.execute(update(solicitudes).where(solicitudes.c.id == solicitud_id).values(
                actualizada_en=ahora(), **valores))

    def obtener_solicitud(self, solicitud_id: int) -> dict | None:
        with self.motor.connect() as conexion:
            fila = conexion.execute(select(solicitudes).where(solicitudes.c.id == solicitud_id)).mappings().first()
            return dict(fila) if fila else None

    def listar_solicitudes(self, canal: str | None = "app", limite: int = 50, estados: list[str] | None = None,
                           desde_id: int | None = None) -> list[dict]:
        consulta = select(solicitudes).order_by(solicitudes.c.id.desc()).limit(limite)
        if canal:
            consulta = consulta.where(solicitudes.c.canal == canal)
        if estados:
            consulta = consulta.where(solicitudes.c.estado.in_(estados))
        if desde_id is not None:
            consulta = consulta.where(solicitudes.c.id < desde_id)
        with self.motor.connect() as conexion:
            return [dict(f) for f in conexion.execute(consulta).mappings().all()]

    def estadisticas(self, canal: str | None = None, ultimas: int = 500) -> dict:
        """Indicadores calculados sobre las solicitudes registradas (datos reales de la persistencia)."""
        filtro = [solicitudes.c.canal == canal] if canal else []
        with self.motor.connect() as conexion:
            por_estado = {fila[0]: fila[1] for fila in conexion.execute(
                select(solicitudes.c.estado, func.count()).where(*filtro).group_by(solicitudes.c.estado))}
            recientes = select(solicitudes.c.eta_s, solicitudes.c.tarifa_estimada, solicitudes.c.estado).where(
                *filtro).order_by(solicitudes.c.id.desc()).limit(ultimas).subquery()
            eta_media, tarifa_media = conexion.execute(
                select(func.avg(recientes.c.eta_s), func.avg(recientes.c.tarifa_estimada))).one()
            con_resultado = conexion.execute(select(func.count()).select_from(recientes).where(
                recientes.c.estado != "rechazada")).scalar() or 0
            sin_conductor = conexion.execute(select(func.count()).select_from(recientes).where(
                recientes.c.estado.in_(["sin_conductores", "sin_ruta"]))).scalar() or 0
        total = sum(por_estado.values())
        return {
            "total": total,
            "por_estado": por_estado,
            "eta_media_s": float(eta_media) if eta_media is not None else None,
            "tarifa_media": float(tarifa_media) if tarifa_media is not None else None,
            "tasa_asignacion": (1 - sin_conductor / con_resultado) if con_resultado else None,
            "muestra": min(total, ultimas),
        }

    # ---------------------------------------------------------- cotizaciones (V3)
    def guardar_cotizacion(self, identificador: str, datos: dict) -> None:
        with self.motor.begin() as conexion:
            conexion.execute(insert(cotizaciones).values(id=identificador, datos=datos, creada_en=ahora(), usada=False))

    def obtener_cotizacion(self, identificador: str) -> dict | None:
        with self.motor.connect() as conexion:
            fila = conexion.execute(select(cotizaciones).where(cotizaciones.c.id == identificador)).mappings().first()
            if not fila:
                return None
            datos = dict(fila)
            datos["creada_en"] = _como_utc(datos["creada_en"])
            return datos

    def marcar_cotizacion_usada(self, identificador: str) -> bool:
        """Marca la cotización como usada; ``False`` si ya lo estaba (evita doble confirmación)."""
        with self.motor.begin() as conexion:
            resultado = conexion.execute(update(cotizaciones).where(cotizaciones.c.id == identificador,
                                                                    cotizaciones.c.usada.is_(False)).values(usada=True))
            return resultado.rowcount == 1

    # --------------------------------------------------------------- alertas (V3)
    def crear_alerta(self, **valores) -> int:
        with self.motor.begin() as conexion:
            r = conexion.execute(insert(alertas).values(creada_en=ahora(), estado="abierta", **valores))
            return int(r.inserted_primary_key[0])

    def alerta_abierta(self, solicitud_id: int) -> dict | None:
        with self.motor.connect() as conexion:
            fila = conexion.execute(select(alertas).where(alertas.c.solicitud_id == solicitud_id,
                                                          alertas.c.estado == "abierta")).mappings().first()
            return dict(fila) if fila else None

    def alerta(self, alerta_id: int) -> dict | None:
        with self.motor.connect() as conexion:
            fila = conexion.execute(select(alertas).where(alertas.c.id == alerta_id)).mappings().first()
            return dict(fila) if fila else None

    def actualizar_alerta(self, alerta_id: int, **valores) -> None:
        with self.motor.begin() as conexion:
            conexion.execute(update(alertas).where(alertas.c.id == alerta_id).values(**valores))

    def listar_alertas(self, limite: int = 50) -> list[dict]:
        with self.motor.connect() as conexion:
            return [dict(f) for f in conexion.execute(select(alertas).order_by(alertas.c.id.desc()).limit(limite)).mappings()]

    def atender_alerta(self, alerta_id: int, nota: str = "") -> dict | None:
        with self.motor.begin() as conexion:
            conexion.execute(update(alertas).where(alertas.c.id == alerta_id, alertas.c.estado == "abierta").values(
                estado="atendida", atendida_en=ahora(), nota=nota))
            fila = conexion.execute(select(alertas).where(alertas.c.id == alerta_id)).mappings().first()
            return dict(fila) if fila else None

    def contar_alertas_abiertas(self) -> int:
        with self.motor.connect() as conexion:
            return int(conexion.execute(select(func.count()).select_from(alertas).where(alertas.c.estado == "abierta")).scalar())

    def estadisticas_aceptacion(self, ultimas: int = 500) -> dict:
        """Asignación operativa (quién aceptó) frente al óptimo académico (menor ETA en k)."""
        with self.motor.connect() as conexion:
            filas = conexion.execute(select(solicitudes.c.conductor_id, solicitudes.c.conductor_academico_id,
                                            solicitudes.c.eta_s, solicitudes.c.eta_academico_s, solicitudes.c.estado,
                                            solicitudes.c.intentos)
                                     .where(solicitudes.c.conductor_academico_id.is_not(None))
                                     .order_by(solicitudes.c.id.desc()).limit(ultimas)).all()
        resueltas = [f for f in filas if f.estado != "buscando"]
        asignadas = [f for f in resueltas if f.conductor_id is not None and f.estado != "sin_aceptacion"]
        coinciden = sum(f.conductor_id == f.conductor_academico_id for f in asignadas)
        difs = [f.eta_s - f.eta_academico_s for f in asignadas if f.eta_s is not None and f.eta_academico_s is not None]
        intentos = [len(f.intentos or []) for f in resueltas]
        return {
            "solicitudes": len(resueltas),
            "aceptadas": len(asignadas),
            "sin_aceptacion": sum(f.estado == "sin_aceptacion" for f in resueltas),
            "coincide_con_academico": coinciden,
            "eta_extra_medio_s": sum(difs) / len(difs) if difs else None,
            "intentos_medios": sum(intentos) / len(intentos) if intentos else None,
        }

    def max_id_solicitud(self) -> int:
        with self.motor.connect() as conexion:
            return int(conexion.execute(select(func.max(solicitudes.c.id))).scalar() or 0)

    def solicitudes_activas(self) -> list[dict]:
        with self.motor.connect() as conexion:
            filas = conexion.execute(select(solicitudes).where(
                solicitudes.c.estado.in_(ESTADOS_ACTIVOS))).mappings().all()
            return [dict(f) for f in filas]
