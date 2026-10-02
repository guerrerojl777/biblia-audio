"""Fábrica de motores de voz."""

from __future__ import annotations

import re

from ..config import Config
from ..errores import ConfigError
from .base import Audio, Contexto, ProveedorTTS


def crear_tts(cfg: Config, nombre: str | None = None) -> ProveedorTTS:
    nombre = nombre or cfg.proveedor
    if nombre == "deepgram":
        from .deepgram import DeepgramTTS

        return DeepgramTTS(cfg.deepgram, cfg.deepgram_api_key)
    if nombre == "elevenlabs":
        from .elevenlabs import ElevenLabsTTS

        return ElevenLabsTTS(cfg.elevenlabs, cfg.elevenlabs_api_key)
    if nombre == "simulado":
        from .simulado import SimuladoTTS

        return SimuladoTTS()
    raise ConfigError(f"Proveedor de voz desconocido: {nombre}")


def etiqueta_voz(cfg: Config, nombre: str) -> str:
    """Nombre de carpeta de salida: proveedor + voz (+ velocidad si no es 1.0), para que
    comparar voces o ritmos nunca sobrescriba un MP3."""
    if nombre == "deepgram":
        return f"deepgram-{cfg.deepgram.voz}{_ritmo(cfg.deepgram.velocidad)}"
    if nombre == "elevenlabs":
        return f"elevenlabs-{cfg.elevenlabs.voz or 'sin-voz'}{_ritmo(cfg.elevenlabs.velocidad)}"
    return nombre


def _ritmo(velocidad: float) -> str:
    return "" if abs(velocidad - 1.0) < 1e-9 else f"-x{velocidad:g}"


def resolver_voz(nombre: str, voz: str) -> str:
    """Acepta el nombre corto de una voz de Deepgram ("luciano" → "aura-2-luciano-es")."""
    if nombre != "deepgram":
        return voz
    from .deepgram import VOCES_ES

    conocidas = [v[0] for v in VOCES_ES]
    candidata = voz.strip().lower()
    if candidata in conocidas:
        return candidata
    corta = f"aura-2-{candidata}-es"
    if corta in conocidas:
        return corta
    if re.fullmatch(r"aura-2-[a-z]+-[a-z]{2}", candidata):  # voz nueva que aún no está en la lista
        return candidata
    cortas = ", ".join(v.split("-")[2] for v in conocidas)
    raise ConfigError(f"'{voz}' no es una voz de Aura-2 en español. Opciones: {cortas}.")


__all__ = ["Audio", "Contexto", "ProveedorTTS", "crear_tts", "etiqueta_voz", "resolver_voz"]
