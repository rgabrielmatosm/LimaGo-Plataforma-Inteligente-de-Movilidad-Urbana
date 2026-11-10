"""V3 — Hora local de Lima para el tráfico automático por horario.

Perú no usa horario de verano desde 1994: Lima está en UTC−5 todo el año. Se
usa la base de datos de zonas horarias (``America/Lima``) si está disponible y,
si no, el desfase fijo, con el mismo resultado.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

try:  # pragma: no cover - depende del sistema
    from zoneinfo import ZoneInfo

    ZONA_LIMA = ZoneInfo("America/Lima")
except Exception:  # noqa: BLE001
    ZONA_LIMA = timezone(timedelta(hours=-5), "America/Lima")


def ahora_lima() -> datetime:
    return datetime.now(ZONA_LIMA)


def hora_lima(momento: datetime | None = None) -> float:
    """Hora decimal (0–24) en Lima: 08:30 → 8.5."""
    momento = (momento or ahora_lima()).astimezone(ZONA_LIMA)
    return momento.hour + momento.minute / 60 + momento.second / 3600


def nivel_trafico(hora: float) -> str:
    """Etiqueta para el público del tráfico **simulado** según el perfil horario del Reto B."""
    from algoritmos.congestion import factor_congestion

    factor = factor_congestion("primary", hora % 24)
    if factor >= 2.2:
        return "alto"
    if factor >= 1.4:
        return "moderado"
    return "fluido"
