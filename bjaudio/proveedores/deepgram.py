"""Deepgram Aura-2 (REST /v1/speak).

Datos de la documentación de Deepgram (verificados en octubre de 2026):
- Máximo 2000 caracteres por petición.
- `speed` entre 0.7 y 1.5; para voces en español se recomienda 0.9–1.5
  (por debajo de 0.9 puede introducir disfluencias).
- Sin control de pausas en Aura-2: las pausas las insertamos nosotros al ensamblar.
- Pronunciación por IPA en línea, en inglés y español:
  \\{"word": "palabra", "pronounce": "IPA"\\}  (máx. 500 por petición, IPA ≤ 128 caracteres;
  la marca de acento va justo antes de la vocal). Se factura la palabra, no el IPA.
  Con erre_final, las palabras terminadas en «r» van marcadas (ver fonetica.py); si las
  marcas alargan un trozo más allá de 2000 caracteres, se pide en partes y se unen.
- La respuesta trae `dg-char-count` (caracteres facturados) y `dg-request-id`.
"""

from __future__ import annotations

import re

import httpx

from .. import audio
from ..config import ConfigDeepgram
from ..errores import ConfigError, ErrorProveedor
from ..fonetica import marcar_erre_final, partir_peticion
from ..lexico import Lexico
from .base import TIMEOUT, Audio, Contexto, ProveedorTTS, peticion

URL_SPEAK = "https://api.deepgram.com/v1/speak"

# Voces Aura-2 en español según la documentación (modelo, género, acento, rasgos).
VOCES_ES: tuple[tuple[str, str, str, str], ...] = (
    ("aura-2-sirio-es", "masculina", "México", "calmada, profesional, barítono"),
    ("aura-2-nestor-es", "masculina", "España", "calmada, profesional, clara"),
    ("aura-2-carina-es", "femenina", "España", "profesional, rasposa, enérgica"),
    ("aura-2-celeste-es", "femenina", "Colombia", "clara, enérgica, positiva"),
    ("aura-2-alvaro-es", "masculina", "España", "calmada, profesional, clara"),
    ("aura-2-diana-es", "femenina", "España", "profesional, expresiva; uso: narración"),
    ("aura-2-aquila-es", "masculina", "Latinoamérica (es-419)", "expresiva, segura"),
    ("aura-2-selena-es", "femenina", "Latinoamérica (es-419)", "cercana, calmada"),
    ("aura-2-estrella-es", "femenina", "México", "natural, calmada, expresiva"),
    ("aura-2-javier-es", "masculina", "México", "profesional, calmada; uso: narración"),
    ("aura-2-agustina-es", "femenina", "España", "calmada, clara, expresiva"),
    ("aura-2-antonia-es", "femenina", "Argentina", "cercana, natural"),
    ("aura-2-gloria-es", "femenina", "Colombia", "clara, natural, suave"),
    ("aura-2-luciano-es", "masculina", "México", "carismática, enérgica"),
    ("aura-2-olivia-es", "femenina", "México", "cálida, calmada"),
    ("aura-2-silvia-es", "femenina", "España", "clara, natural, cálida"),
    ("aura-2-valerio-es", "masculina", "México", "profunda, informativa"),
)


class DeepgramTTS(ProveedorTTS):
    nombre = "deepgram"
    max_chars = 2000
    estocastico = False

    def __init__(self, cfg: ConfigDeepgram, api_key: str | None, transporte: httpx.BaseTransport | None = None):
        self.cfg = cfg
        self.sample_rate = cfg.sample_rate
        self._api_key = api_key
        self._cliente = httpx.Client(
            timeout=TIMEOUT,
            transport=transporte,
            headers={"Authorization": f"Token {api_key or ''}", "Content-Type": "application/json"},
        )

    def listo(self) -> None:
        if not self._api_key:
            raise ConfigError("Falta DEEPGRAM_API_KEY en .env (cópialo de .env.example).")

    def firma(self) -> dict:
        return {"proveedor": "deepgram", "voz": self.cfg.voz, "velocidad": self.cfg.velocidad, "sr": self.cfg.sample_rate}

    @property
    def seseo(self) -> bool:
        """Las voces de España distinguen z/c de s; las de América sesean."""
        acento = next((a for m, _g, a, _r in VOCES_ES if m == self.cfg.voz), "")
        return acento != "España"

    def preparar_texto(self, texto: str, lexico: Lexico) -> str:
        ipa = lexico.con_ipa()
        if ipa:
            alternativas = "|".join(re.escape(p) for p in sorted(ipa, key=len, reverse=True))
            patron = re.compile(rf"(?<!\w)({alternativas})(?!\w)")
            # Una sola barra invertida antes de cada llave: json.dumps la escapará al enviar.
            texto = patron.sub(lambda m: '\\{"word": "%s", "pronounce": "%s"\\}' % (m.group(1), ipa[m.group(1)]), texto)
        if self.cfg.erre_final:
            texto = marcar_erre_final(texto, self.cfg.erre_final, seseo=self.seseo, excluir=frozenset(ipa))
        return texto

    def sintetizar(self, texto: str, contexto: Contexto) -> Audio:
        self.listo()
        try:
            partes = partir_peticion(texto, self.max_chars)
        except ValueError as e:
            raise ErrorProveedor(f"Trozo de {len(texto)} caracteres con marcas de IPA: {e}") from None
        if len(partes) == 1:
            return self._peticion(texto)
        # Las marcas de IPA no se facturan pero sí ocupan: se pide por partes y se une el audio.
        resultados = [self._peticion(p) for p in partes]
        pcm = b"".join(audio.a_pcm(r.wav, self.sample_rate) for r in resultados)
        return Audio(
            wav=audio.pcm_a_wav(pcm, self.sample_rate),
            caracteres=sum(r.caracteres for r in resultados),
            id_peticion=",".join(r.id_peticion or "" for r in resultados),
        )

    def _peticion(self, texto: str) -> Audio:
        params: dict[str, str] = {
            "model": self.cfg.voz,
            "encoding": "linear16",
            "container": "wav",
            "sample_rate": str(self.cfg.sample_rate),
        }
        if abs(self.cfg.velocidad - 1.0) > 1e-9:
            params["speed"] = f"{self.cfg.velocidad:.2f}"
        r = peticion(self._cliente, "POST", URL_SPEAK, servicio="Deepgram TTS", params=params, json={"text": texto})
        if not r.content.startswith(b"RIFF"):
            raise ErrorProveedor(f"Deepgram devolvió algo que no es WAV (content-type: {r.headers.get('content-type')}).")
        cargo = r.headers.get("dg-char-count")
        return Audio(
            wav=r.content,
            caracteres=int(cargo) if cargo and cargo.isdigit() else len(texto),
            id_peticion=r.headers.get("dg-request-id"),
        )

    def costo_usd(self, caracteres: int) -> float:
        return caracteres / 1000 * self.cfg.tts_usd_por_1k

    def cerrar(self) -> None:
        self._cliente.close()
