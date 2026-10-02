"""biblia-audio: convierte capítulos de la Biblia (desde un EPUB sin DRM) en MP3 verificados.

Arquitectura en cascada: Python determinístico orquesta todo; los modelos solo hacen
dos subtareas acotadas (sintetizar voz y transcribirla para verificar).
"""

__version__ = "0.3.3"
