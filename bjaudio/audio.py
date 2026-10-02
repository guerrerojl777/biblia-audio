"""Audio con la biblioteca estándar (wave/array) y ffmpeg como binario externo.

Todo el procesamiento interno es PCM de 16 bits, mono, a una sola frecuencia de muestreo.
Así concatenar es pegar bytes y medir tiempos es dividir: sin sorpresas de formato.
ffmpeg solo entra para (a) convertir lo que llegue en otro formato y (b) normalizar
volumen y codificar el MP3 final.
"""

from __future__ import annotations

import io
import math
import shutil
import struct
import subprocess
import sys
import wave
from array import array
from dataclasses import dataclass
from pathlib import Path

from .errores import BjaError, FfmpegNoDisponible

ANCHO = 2  # bytes por muestra (16 bits)


def requerir_ffmpeg() -> str:
    ruta = shutil.which("ffmpeg")
    if not ruta:
        raise FfmpegNoDisponible(
            "No encuentro ffmpeg. En Ubuntu/WSL: sudo apt install ffmpeg  (luego vuelve a intentar)."
        )
    return ruta


def pcm_a_wav(pcm: bytes, sr: int) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(ANCHO)
        w.setframerate(sr)
        w.writeframes(pcm)
    return buf.getvalue()


@dataclass(frozen=True)
class Wav:
    sr: int
    canales: int
    ancho: int  # bytes por muestra
    formato: int  # 1 = PCM, 0xFFFE = extensible
    pcm: bytes


def leer_wav(datos: bytes) -> Wav:
    """Lector de WAV tolerante.

    Las APIs que transmiten audio a veces escriben la cabecera antes de saber el largo
    y dejan el tamaño del bloque de datos en 0 o en 0xFFFFFFFF. El módulo `wave` creería
    ese número; aquí, si no cuadra con lo recibido, se toma todo hasta el final.
    """
    if len(datos) < 12 or datos[:4] != b"RIFF" or datos[8:12] != b"WAVE":
        raise BjaError("El audio recibido no es un WAV (falta la cabecera RIFF/WAVE).")
    pos = 12
    fmt: tuple[int, int, int, int] | None = None
    while pos + 8 <= len(datos):
        bloque = datos[pos : pos + 4]
        tam = int.from_bytes(datos[pos + 4 : pos + 8], "little")
        pos += 8
        if bloque == b"fmt ":
            if tam < 16:
                raise BjaError("WAV con bloque fmt inválido.")
            formato, canales, sr, _bps, _align, bits = struct.unpack("<HHIIHH", datos[pos : pos + 16])
            fmt = (formato, canales, sr, bits)
        elif bloque == b"data":
            if fmt is None:
                raise BjaError("WAV sin bloque fmt antes de los datos.")
            disponible = len(datos) - pos
            if tam == 0 or tam > disponible:
                tam = disponible
            formato, canales, sr, bits = fmt
            return Wav(sr, canales, bits // 8, formato, datos[pos : pos + tam])
        pos += tam + (tam % 2)
    raise BjaError("WAV sin bloque de datos.")


def info_wav(datos: bytes) -> tuple[int, int, int, int]:
    """(frecuencia, canales, ancho_bytes, n_muestras) calculados sobre los datos reales."""
    w = leer_wav(datos)
    n = len(w.pcm) // max(1, w.ancho * w.canales)
    return w.sr, w.canales, w.ancho, n


def convertir(datos: bytes, sr: int) -> bytes:
    """Cualquier formato que entienda ffmpeg → WAV PCM16 mono a `sr`."""
    ffmpeg = requerir_ffmpeg()
    proc = subprocess.run(
        [ffmpeg, "-hide_banner", "-loglevel", "error", "-i", "pipe:0",
         "-ac", "1", "-ar", str(sr), "-c:a", "pcm_s16le", "-f", "wav", "pipe:1"],
        input=datos, capture_output=True, check=False,
    )
    if proc.returncode != 0:
        raise BjaError(f"ffmpeg no pudo convertir el audio: {proc.stderr.decode(errors='replace')[:300]}")
    return proc.stdout


def a_pcm(datos: bytes, sr: int) -> bytes:
    """Devuelve PCM16 mono crudo a `sr`, convirtiendo con ffmpeg solo si hace falta."""
    try:
        w = leer_wav(datos)
        if w.sr == sr and w.canales == 1 and w.ancho == ANCHO and w.formato in (1, 0xFFFE):
            return w.pcm[: len(w.pcm) - len(w.pcm) % ANCHO]
    except BjaError:
        pass
    return leer_wav(convertir(datos, sr)).pcm


def normalizar_wav(datos: bytes, sr: int) -> bytes:
    """WAV limpio (cabecera correcta, PCM16 mono a `sr`) para guardar en caché."""
    return pcm_a_wav(a_pcm(datos, sr), sr)


def _muestras(pcm: bytes) -> array:
    a = array("h")
    a.frombytes(pcm)
    if sys.byteorder == "big":  # WAV es little-endian
        a.byteswap()
    return a


def duracion(pcm: bytes, sr: int) -> float:
    return len(pcm) / (ANCHO * sr)


def recortar_silencio(pcm: bytes, sr: int, umbral_dbfs: float, margen_ms: int) -> tuple[bytes, float]:
    """Quita silencio al principio y al final. Devuelve (pcm, segundos_quitados_al_inicio).

    Trabaja por ventanas de 10 ms con el pico absoluto, y solo recorre desde los bordes
    hacia dentro: en audio de TTS el silencio está en los extremos, así que es rápido.
    """
    muestras = _muestras(pcm)
    n = len(muestras)
    if n == 0:
        return pcm, 0.0
    umbral = 32768 * (10 ** (umbral_dbfs / 20))
    ventana = max(1, sr // 100)

    def fuerte(i: int) -> bool:
        trozo = muestras[i : i + ventana]
        return bool(trozo) and max(abs(min(trozo)), abs(max(trozo))) > umbral

    inicio = 0
    while inicio < n and not fuerte(inicio):
        inicio += ventana
    if inicio >= n:  # todo silencio
        return b"", 0.0
    fin = n
    while fin > inicio and not fuerte(max(inicio, fin - ventana)):
        fin -= ventana
    margen = int(sr * margen_ms / 1000)
    inicio = max(0, inicio - margen)
    fin = min(n, fin + margen)
    return pcm[inicio * ANCHO : fin * ANCHO], inicio / sr


def silencio(ms: int, sr: int) -> bytes:
    return b"\x00\x00" * int(sr * ms / 1000)


def tono(frecuencia: float, segundos: float, sr: int, nivel_dbfs: float = -12.0) -> bytes:
    """Seno simple (para el proveedor simulado y las pruebas)."""
    amplitud = 32767 * (10 ** (nivel_dbfs / 20))
    n = int(sr * segundos)
    periodo = sr / frecuencia
    if periodo.is_integer():  # camino rápido: un ciclo repetido
        ciclo = array("h", (int(amplitud * math.sin(2 * math.pi * i / periodo)) for i in range(int(periodo))))
        a = ciclo * (n // len(ciclo) + 1)
        del a[n:]
    else:
        a = array("h", (int(amplitud * math.sin(2 * math.pi * frecuencia * i / sr)) for i in range(n)))
    if sys.byteorder == "big":
        a.byteswap()
    return a.tobytes()


def exportar_mp3(pcm: bytes, sr: int, destino: Path, *, kbps: int, loudnorm: tuple[float, float, float],
                 etiquetas: dict[str, str]) -> None:
    """Normaliza volumen (EBU R128) y codifica MP3 mono con etiquetas ID3v2.3."""
    ffmpeg = requerir_ffmpeg()
    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    i, tp, lra = loudnorm
    tmp = destino.with_name(f".{destino.stem}.tmp.mp3")
    comando = [
        ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
        "-f", "s16le", "-ar", str(sr), "-ac", "1", "-i", "pipe:0",
        "-af", f"loudnorm=I={i}:TP={tp}:LRA={lra}",
        "-ar", str(sr), "-ac", "1", "-c:a", "libmp3lame", "-b:a", f"{kbps}k",
        "-id3v2_version", "3",
    ]
    for clave, valor in etiquetas.items():
        if valor:
            comando += ["-metadata", f"{clave}={valor}"]
    comando.append(str(tmp))
    proc = subprocess.run(comando, input=pcm, capture_output=True, check=False)
    if proc.returncode != 0:
        tmp.unlink(missing_ok=True)
        raise BjaError(f"ffmpeg falló al crear el MP3: {proc.stderr.decode(errors='replace')[:400]}")
    tmp.replace(destino)
