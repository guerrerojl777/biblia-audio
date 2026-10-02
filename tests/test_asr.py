from __future__ import annotations

import sys
import types
from pathlib import Path

from bjaudio.asr import WhisperLocalASR
from bjaudio.config import Config


class _Palabra:
    def __init__(self, word, start, end):
        self.word, self.start, self.end = word, start, end


class _Segmento:
    def __init__(self, palabras):
        self.words = palabras


def test_whisper_local_usa_la_api_de_faster_whisper(monkeypatch, tmp_path):
    llamadas = {}

    class ModeloFalso:
        def __init__(self, modelo, device, compute_type):
            llamadas["init"] = (modelo, device, compute_type)

        def transcribe(self, audio, **kwargs):
            llamadas["kwargs"] = kwargs
            llamadas["audio_tiene_read"] = hasattr(audio, "read")
            return iter([_Segmento([_Palabra(" Habló", 0.1, 0.4), _Palabra(" Moisés.", 0.5, 0.9)])]), None

    modulo = types.ModuleType("faster_whisper")
    modulo.WhisperModel = ModeloFalso
    monkeypatch.setitem(sys.modules, "faster_whisper", modulo)

    asr = WhisperLocalASR(Config(raiz=Path(tmp_path)))
    palabras = asr.transcribir(b"RIFF...", "Habló Moisés al pueblo de Israel.")
    assert [p.texto for p in palabras] == ["Habló", "Moisés."]
    assert llamadas["init"] == ("small", "cpu", "int8")
    kw = llamadas["kwargs"]
    assert kw["language"] == "es" and kw["word_timestamps"] is True
    # la pista solo lleva nombres propios, nunca el texto completo
    assert kw["initial_prompt"] == "Habló, Israel, Moisés"
    assert llamadas["audio_tiene_read"]
