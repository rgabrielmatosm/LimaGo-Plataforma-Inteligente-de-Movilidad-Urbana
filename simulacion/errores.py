"""Errores de dominio con mensajes en español aptos para el usuario final."""


class ErrorLimaGo(Exception):
    codigo = "error"


class ErrorUbicacion(ErrorLimaGo, ValueError):
    codigo = "ubicacion_invalida"


class CoordenadasInvalidas(ErrorUbicacion):
    codigo = "coordenadas_invalidas"


class FueraDeCobertura(ErrorUbicacion):
    codigo = "fuera_de_cobertura"


class SinConexionVial(ErrorUbicacion):
    codigo = "sin_conexion_vial"


class DireccionNoEncontrada(ErrorUbicacion):
    codigo = "direccion_no_encontrada"


class DireccionAmbigua(ErrorUbicacion):
    codigo = "direccion_ambigua"

    def __init__(self, mensaje: str, opciones: list[dict]):
        super().__init__(mensaje)
        self.opciones = opciones


class ServicioNoDisponible(ErrorLimaGo):
    codigo = "servicio_no_disponible"
