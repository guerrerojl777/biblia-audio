"""Errores esperados del pipeline. Llevan un mensaje pensado para leerse en la terminal."""


class BjaError(Exception):
    """Error esperado: la CLI lo muestra sin traceback."""


class ConfigError(BjaError):
    """config.toml o .env con un problema."""


class EpubProtegidoError(BjaError):
    """El EPUB tiene DRM: el pipeline no lo procesa ni intenta desprotegerlo."""


class TextoInvalido(BjaError):
    """Un archivo de texto canónico no respeta el formato."""


class PresupuestoExcedido(BjaError):
    """La operación gastaría más crédito del disponible: se aborta antes de llamar a la API."""


class ErrorProveedor(BjaError):
    """La API de TTS o ASR respondió con un error que no se arregla reintentando."""


class FfmpegNoDisponible(BjaError):
    """No se encontró ffmpeg en el PATH."""
