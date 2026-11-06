"""Health check del worker: falla si no hay latido reciente en la base de datos.

    python -m api.salud_worker   (código 0 = sano, 1 = sin latido)
"""
import sys
from datetime import timedelta

from api.persistencia import BaseDatos, ahora
from config.ajustes import cargar_ajustes


def main() -> int:
    try:
        estado = BaseDatos(cargar_ajustes().url_base_datos).leer_estado()
    except Exception:  # noqa: BLE001
        return 1
    return 0 if estado and ahora() - estado["latido_en"] < timedelta(seconds=20) else 1


if __name__ == "__main__":
    sys.exit(main())
