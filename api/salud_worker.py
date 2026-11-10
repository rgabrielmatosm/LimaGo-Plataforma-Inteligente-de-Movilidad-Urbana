"""Health check del worker: falla si no hay latido reciente en la base de datos.

    python -m api.salud_worker   (código 0 = sano, 1 = sin latido)
"""
import sys
from datetime import timedelta

from api.persistencia import BaseDatos, ahora
from config.ajustes import cargar_ajustes


def main() -> int:
    try:
        latido = BaseDatos(cargar_ajustes().url_base_datos).latido_estado()  # sin leer la instantánea completa
    except Exception:  # noqa: BLE001
        return 1
    return 0 if latido and ahora() - latido < timedelta(seconds=20) else 1


if __name__ == "__main__":
    sys.exit(main())
