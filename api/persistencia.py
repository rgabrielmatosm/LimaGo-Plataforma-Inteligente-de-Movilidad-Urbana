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
                        event, func, insert, select, update)
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
    Column("creada_en", DateTime(timezone=True), nullable=False),
    Column("actualizada_en", DateTime(timezone=True), nullable=False),
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

    def listar_solicitudes(self, canal: str | None = "app", limite: int = 50) -> list[dict]:
        consulta = select(solicitudes).order_by(solicitudes.c.id.desc()).limit(limite)
        if canal:
            consulta = consulta.where(solicitudes.c.canal == canal)
        with self.motor.connect() as conexion:
            return [dict(f) for f in conexion.execute(consulta).mappings().all()]

    def max_id_solicitud(self) -> int:
        with self.motor.connect() as conexion:
            return int(conexion.execute(select(func.max(solicitudes.c.id))).scalar() or 0)

    def solicitudes_activas(self) -> list[dict]:
        with self.motor.connect() as conexion:
            filas = conexion.execute(select(solicitudes).where(
                solicitudes.c.estado.in_(["asignada", "en_viaje"]))).mappings().all()
            return [dict(f) for f in filas]
