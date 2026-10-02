"""Verificación: compara lo que se pidió decir con lo que el reconocedor oyó.

El detector no mira la tasa de error promedio, sino las RACHAS:
- Un reconocedor se equivoca de forma dispersa: una palabra suelta aquí y allá,
  sobre todo nombres propios. Eso no es un problema del audio.
- Un motor de voz que se salta una frase produce una racha de palabras faltantes
  seguidas; uno que repite o inventa produce una racha de palabras sobrantes.
Por eso el criterio principal es la racha más larga de omisiones o inserciones, y la
tasa de error (WER) es solo una red de seguridad para casos muy malos.

Además, la alineación entrega la marca de tiempo de cada versículo: el índice del
capítulo sale gratis del mismo paso.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from difflib import SequenceMatcher

from .asr import Palabra
from .config import ConfigVerificacion
from .normalizar import tokenizar


@dataclass
class Resultado:
    wer: float
    sustituciones: int
    omisiones: int
    inserciones: int
    racha_omision: int
    racha_insercion: int
    marcado: bool
    motivo: str
    tiempos: dict[str, float] = field(default_factory=dict)  # versículo → segundos dentro del trozo
    faltantes: list[str] = field(default_factory=list)  # fragmentos de referencia no oídos
    sobrantes: list[str] = field(default_factory=list)  # fragmentos oídos que no estaban

    def gravedad(self) -> tuple[int, int, float]:
        """Para elegir el mejor intento: menor es mejor."""
        return (max(self.racha_omision, self.racha_insercion), self.omisiones + self.inserciones, self.wer)

    def a_dict(self) -> dict:
        return asdict(self)


def verificar(referencia: str, versos: list[tuple[str, int]], palabras: list[Palabra],
              cfg: ConfigVerificacion, duracion: float) -> Resultado:
    ref = tokenizar(referencia)
    hip: list[str] = []
    tiempos_hip: list[float] = []
    for p in palabras:
        for token in tokenizar(p.texto):
            hip.append(token)
            tiempos_hip.append(p.inicio)

    matcher = SequenceMatcher(a=ref, b=hip, autojunk=False)
    sust = omis = ins = racha_o = racha_i = 0
    faltantes: list[str] = []
    sobrantes: list[str] = []
    ref_a_hip: dict[int, int] = {}
    for op, i1, i2, j1, j2 in matcher.get_opcodes():
        n_ref, n_hip = i2 - i1, j2 - j1
        if op == "equal":
            for k in range(n_ref):
                ref_a_hip[i1 + k] = j1 + k
        elif op == "delete":
            omis += n_ref
            racha_o = max(racha_o, n_ref)
            faltantes.append(" ".join(ref[i1:i2]))
        elif op == "insert":
            ins += n_hip
            racha_i = max(racha_i, n_hip)
            sobrantes.append(" ".join(hip[j1:j2]))
        else:  # replace
            sust += min(n_ref, n_hip)
            if n_ref > n_hip:
                omis += n_ref - n_hip
                racha_o = max(racha_o, n_ref - n_hip)
                if n_ref - n_hip >= cfg.racha_omision:
                    faltantes.append(" ".join(ref[i1:i2]))
            elif n_hip > n_ref:
                ins += n_hip - n_ref
                racha_i = max(racha_i, n_hip - n_ref)
                if n_hip - n_ref >= cfg.racha_insercion:
                    sobrantes.append(" ".join(hip[j1:j2]))

    total = max(1, len(ref))
    wer = (sust + omis + ins) / total
    motivos = []
    if not hip and ref:
        motivos.append("no se oyó nada")
    if racha_o >= cfg.racha_omision:
        motivos.append(f"faltan {racha_o} palabras seguidas")
    if racha_i >= cfg.racha_insercion:
        motivos.append(f"sobran {racha_i} palabras seguidas")
    if wer > cfg.wer_max:
        motivos.append(f"WER {wer:.0%} > {cfg.wer_max:.0%}")

    tiempos = _tiempos_versos(versos, ref_a_hip, tiempos_hip, len(ref), duracion)
    return Resultado(
        wer=round(wer, 4), sustituciones=sust, omisiones=omis, inserciones=ins,
        racha_omision=racha_o, racha_insercion=racha_i, marcado=bool(motivos),
        motivo="; ".join(motivos), tiempos=tiempos, faltantes=faltantes[:5], sobrantes=sobrantes[:5],
    )


def clave_unica(tiempos: dict[str, float], verso: str) -> str:
    """'24' si es nuevo; '24#2', '24#3'… si la edición numera dos veces el mismo versículo."""
    base = verso.split("#", 1)[0]
    clave, k = base, 2
    while clave in tiempos:
        clave, k = f"{base}#{k}", k + 1
    return clave


def _tiempos_versos(versos: list[tuple[str, int]], ref_a_hip: dict[int, int], tiempos_hip: list[float],
                    n_ref: int, duracion: float) -> dict[str, float]:
    """Tiempo de inicio de cada versículo: el primer token suyo (o siguiente) que se alineó."""
    salida: dict[str, float] = {}
    for verso, indice in versos:
        tiempo = None
        for k in range(indice, n_ref):
            if k in ref_a_hip:
                tiempo = tiempos_hip[ref_a_hip[k]]
                break
        if tiempo is None:  # nada alineado después: proporción de tokens como aproximación
            tiempo = duracion * (indice / max(1, n_ref))
        salida[clave_unica(salida, verso)] = round(tiempo, 3)
    return salida


def estimar_tiempos(versos: list[tuple[str, int]], referencia: str, duracion: float) -> dict[str, float]:
    """Sin verificación: reparto proporcional al número de palabras (aproximado)."""
    n = max(1, len(tokenizar(referencia)))
    salida: dict[str, float] = {}
    for v, i in versos:
        salida[clave_unica(salida, v)] = round(duracion * i / n, 3)
    return salida
