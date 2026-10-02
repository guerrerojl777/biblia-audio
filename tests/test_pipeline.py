from __future__ import annotations

import json
from dataclasses import replace

import httpx
import pytest

from bjaudio.asr import SimuladoASR
from bjaudio.errores import PresupuestoExcedido
from bjaudio.extraccion import extraer_a_disco
from bjaudio.gastos import LibroGastos
from bjaudio.pipeline import Pipeline, parsear_rango
from bjaudio.proveedores.deepgram import DeepgramTTS
from bjaudio.proveedores.elevenlabs import ElevenLabsTTS
from bjaudio.proveedores.simulado import SimuladoTTS


def test_de_punta_a_punta_con_simulado(proyecto):
    extraer_a_disco(proyecto)
    pipe = Pipeline(proyecto, SimuladoTTS(), SimuladoASR())
    r = pipe.procesar("gn", 1)
    assert r.mp3 is not None and r.mp3.exists()
    assert r.mp3.parent.name == "01-gn" and r.mp3.name == "gn-001.mp3"
    assert not r.marcados and r.sintetizados == r.trozos and r.desde_cache == 0
    indice = json.loads(r.mp3.with_suffix(".json").read_text(encoding="utf-8"))
    tiempos = [indice["versiculos"][v] for v in ["1", "2", "3", "4", "5"]]
    assert tiempos == sorted(tiempos) and tiempos[0] > 0.5  # tras el anuncio
    assert indice["secciones"][0]["titulo"] == "El comienzo"
    assert indice["tiempos"] == "verificados"
    # Segunda pasada: todo sale de la caché, no se "paga" nada.
    r2 = pipe.procesar("gn", 1)
    assert r2.sintetizados == 0 and r2.desde_cache == r2.trozos


def test_simulacion_no_genera_archivos(proyecto):
    extraer_a_disco(proyecto)
    r = Pipeline(proyecto, SimuladoTTS(), SimuladoASR()).procesar("gn", 2, simular=True)
    assert r.mp3 is None and r.trozos >= 2 and r.caracteres_facturados > 0
    assert not (proyecto.dir_salida).exists()


def test_presupuesto_deepgram_aborta_antes_de_llamar(proyecto):
    extraer_a_disco(proyecto)
    cfg = replace(proyecto, deepgram=replace(proyecto.deepgram, credito_usd=10.0, reserva_usd=10.0))

    def prohibido(req):
        raise AssertionError("no debía llamarse a la API")

    tts = DeepgramTTS(cfg.deepgram, "k", httpx.MockTransport(prohibido))
    with pytest.raises(PresupuestoExcedido, match="No se llamó a la API"):
        Pipeline(cfg, tts, None).procesar("gn", 1)


def test_presupuesto_cuenta_lo_ya_gastado(proyecto):
    extraer_a_disco(proyecto)
    cfg = replace(proyecto, deepgram=replace(proyecto.deepgram, credito_usd=50.0, reserva_usd=5.0))
    LibroGastos(cfg.archivo_gastos).registrar("deepgram", "tts", 1_500_000, 45.0, "pasado")
    tts = DeepgramTTS(cfg.deepgram, "k", httpx.MockTransport(lambda r: (_ for _ in ()).throw(AssertionError())))
    with pytest.raises(PresupuestoExcedido):
        Pipeline(cfg, tts, None).procesar("gn", 1)


def test_tope_mensual_elevenlabs(proyecto):
    extraer_a_disco(proyecto)
    cfg = replace(proyecto, elevenlabs=replace(proyecto.elevenlabs, voz="V", creditos_mes=10000))
    LibroGastos(cfg.archivo_gastos).registrar("elevenlabs", "tts", 9990, 0.0, "pasado")
    tts = ElevenLabsTTS(cfg.elevenlabs, "k", httpx.MockTransport(lambda r: (_ for _ in ()).throw(AssertionError())))
    with pytest.raises(PresupuestoExcedido, match="ElevenLabs"):
        Pipeline(cfg, tts, None).procesar("gn", 1)


def test_parsear_rango():
    assert parsear_rango("1-3") == [1, 2, 3]
    assert parsear_rango("1,4,7-8,4") == [1, 4, 7, 8]


class ASRContador(SimuladoASR):
    """ASR simulado que cobra, para comprobar que la verificación tampoco se paga dos veces."""

    def __init__(self):
        self.llamadas = 0

    def transcribir(self, wav, referencia):
        self.llamadas += 1
        return super().transcribir(wav, referencia)

    def costo_usd(self, segundos):
        return segundos / 60 * 0.0043


def test_la_verificacion_se_guarda_y_no_se_vuelve_a_pagar(proyecto):
    extraer_a_disco(proyecto)
    asr = ASRContador()
    pipe = Pipeline(proyecto, SimuladoTTS(), asr)
    r1 = pipe.procesar("gn", 1)
    assert asr.llamadas == r1.trozos and r1.usd_asr > 0
    assert pipe.estimar(pipe.plan(pipe_libro("gn"), 1)).usd_asr == 0.0
    r2 = pipe.procesar("gn", 1)
    assert asr.llamadas == r1.trozos and r2.usd_asr == 0.0
    gastos = LibroGastos(proyecto.archivo_gastos).filas()
    assert sum(1 for f in gastos if f["tipo"] == "asr") == r1.trozos


def pipe_libro(id_libro):
    from bjaudio.libros import obtener

    return obtener(id_libro)
