from __future__ import annotations

import json
import shutil
import subprocess

import pytest

from bjaudio import audio

SR = 24000
requiere_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg no instalado")


def test_recorte_de_silencio():
    pcm = audio.silencio(500, SR) + audio.tono(240, 1.0, SR) + audio.silencio(700, SR)
    recortado, quitado = audio.recortar_silencio(pcm, SR, -45.0, 40)
    assert abs(audio.duracion(recortado, SR) - 1.08) < 0.03
    assert abs(quitado - 0.46) < 0.02


def test_todo_silencio_queda_vacio():
    recortado, quitado = audio.recortar_silencio(audio.silencio(300, SR), SR, -45.0, 40)
    assert recortado == b"" and quitado == 0.0


def test_wav_ida_y_vuelta():
    pcm = audio.tono(240, 0.5, SR)
    wav = audio.pcm_a_wav(pcm, SR)
    assert audio.info_wav(wav) == (SR, 1, 2, len(pcm) // 2)
    assert audio.a_pcm(wav, SR) == pcm


@pytest.mark.parametrize("tam", [0, 0xFFFFFFFF])
def test_wav_con_cabecera_de_streaming(tam):
    """Algunas APIs envían el tamaño de datos en 0 o 0xFFFFFFFF: no se debe perder audio."""
    pcm = audio.tono(240, 0.5, SR)
    wav = bytearray(audio.pcm_a_wav(pcm, SR))
    i = wav.find(b"data")
    wav[i + 4 : i + 8] = tam.to_bytes(4, "little")
    wav[4:8] = (0xFFFFFFFF).to_bytes(4, "little")
    assert audio.a_pcm(bytes(wav), SR) == pcm
    assert audio.info_wav(bytes(wav))[3] == len(pcm) // 2
    limpio = audio.normalizar_wav(bytes(wav), SR)
    assert audio.info_wav(limpio)[3] == len(pcm) // 2


def test_no_wav_da_error_claro():
    from bjaudio.errores import BjaError

    with pytest.raises(BjaError, match="RIFF"):
        audio.leer_wav(b"ID3\x03 esto es un mp3")


@requiere_ffmpeg
def test_conversion_de_frecuencia():
    wav16 = audio.pcm_a_wav(audio.tono(400, 1.0, 16000), 16000)
    pcm24 = audio.a_pcm(wav16, SR)
    assert abs(audio.duracion(pcm24, SR) - 1.0) < 0.02


@requiere_ffmpeg
def test_exportar_mp3_con_etiquetas(tmp_path):
    destino = tmp_path / "x" / "gn-001.mp3"
    pcm = audio.tono(240, 2.0, SR) + audio.silencio(500, SR)
    audio.exportar_mp3(pcm, SR, destino, kbps=64, loudnorm=(-18.0, -1.5, 11.0),
                       etiquetas={"title": "Génesis 1", "album": "Génesis", "track": "1/50"})
    datos = json.loads(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration:format_tags", "-of", "json", str(destino)],
        capture_output=True, check=True, text=True).stdout)
    assert abs(float(datos["format"]["duration"]) - 2.5) < 0.15
    etiquetas = {k.lower(): v for k, v in datos["format"]["tags"].items()}
    assert etiquetas["title"] == "Génesis 1" and etiquetas["album"] == "Génesis"
