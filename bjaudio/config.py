"""Carga de config.toml y .env.

Todo valor tiene un default razonable; config.toml solo necesita lo que quieras cambiar.
Las claves desconocidas son un error (así un typo no se ignora en silencio).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
from dataclasses import dataclass, field, fields, replace
from pathlib import Path
from typing import Any

from .errores import ConfigError

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib


CAPITULO_DEFECTO = "h2, h3, h4, .capitulo, .cap, .capital, .salmocapital, .chapter, .chapter-num"
# Rama 1: número solo, "Capítulo N", "Salmo N" o abreviatura de hasta 4 letras + N
# ("Qo 3", "1 Cro 3", "Sal 10"). Rama 2: "Capítulo/Salmo N" seguido de algo ("SALMO 9-10").
CAPITULO_REGEX_DEFECTO = (
    r"^\s*(?:(?:cap[ií]tulo|salmos?)\s+|(?:[1-3]\s*)?[^\W\d_]{1,4}\.?\s+)?(\d{1,3})\s*$"
    r"|^\s*(?:cap[ií]tulo|salmos?)\s+(\d{1,3})\b"
)
VERSICULO_REGEX_DEFECTO = r"^\s*(\d{1,3}[a-z]{0,2}(?:\s*[-–]\s*\d{1,3}[a-z]{0,2})?)\s*$"


@dataclass
class ConfigEpub:
    archivo: str = "libros/biblia.epub"
    # Selectores CSS (sintaxis de BeautifulSoup/soupsieve). Ajústalos tras `inspeccionar`.
    titulo_libro: str = "h1"
    capitulo: str = CAPITULO_DEFECTO
    # Un elemento "capítulo" solo cuenta si su texto encaja aquí (grupo 1 o 2 = número).
    # Acepta "3", "Capítulo 3", "Salmo 23 (22)" y abreviatura + número: "Qo 3", "1 Cro 3".
    capitulo_regex: str = CAPITULO_REGEX_DEFECTO
    versiculo: str = "sup, .v, .vers, .verse, .versiculo, .verse-num"
    # "12", "12a", "40ab" y versículos unidos "24-25".
    versiculo_regex: str = VERSICULO_REGEX_DEFECTO
    titulo_seccion: str = "h2, h3, h4, h5, h6"
    linea_poetica: str = ""
    estrofa: str = ""
    # Rótulos que se leen con pausa larga antes y después: quién habla en el Cantar, las
    # letras hebreas de un acróstico (p. ej. ".flm"). Para que NO se lean, ponlos en
    # titulo_seccion.
    rotulo: str = ""
    eliminar: list[str] = field(
        default_factory=lambda: [
            "a.nota", "a.note", "a.footnote", "a.noteref", "sup.nota", "span.nota",
            "div.notas", "div.notes", "div.footnotes", "aside", "span.ref", "span.paralelo",
        ]
    )
    # <sup> o <a> cuyo texto encaja aquí son llamadas a nota: se eliminan.
    marcador_nota_regex: str = r"^\s*[a-z*†‡]{1,3}\s*$"
    # Si un capítulo empieza con texto antes de cualquier número de versículo, es el 1.
    versiculo_implicito: bool = True
    # Documentos del EPUB a saltar (regex sobre la ruta interna), p. ej. ["notas", "intro"].
    ignorar_documentos: list[str] = field(default_factory=list)
    # Un título de libro que encaje aquí cierra el libro: lo que sigue se ignora hasta el
    # próximo título reconocido. Sirve para las secciones de notas al final del EPUB.
    ignorar_titulos: list[str] = field(default_factory=lambda: [r"^\s*notas\b"])
    # Si cada línea poética es un <p> propio: bloques de hasta N caracteres seguidos se
    # leen como líneas de un mismo párrafo (pausa corta). 0 = desactivado.
    bloque_corto_chars: int = 0
    # Títulos que no se reconocen solos: "TEXTO EXACTO DEL TÍTULO" = "id_libro".
    # El valor especial "seccion" trata ese título como título de sección del libro en curso.
    titulos: dict[str, str] = field(default_factory=dict)


@dataclass
class ConfigPlan:
    objetivo_chars: int = 600
    max_chars: int = 1800
    poesia_coma: bool = True
    quitar_caracteres: str = "*†‡§[]"
    anunciar_capitulo: bool = True


@dataclass
class ConfigPausas:
    anuncio: int = 900
    linea: int = 300
    versiculo: int = 250
    parrafo: int = 650
    seccion: int = 900
    final: int = 1500
    margen_recorte: int = 40
    umbral_silencio_dbfs: float = -45.0


@dataclass
class ConfigDeepgram:
    voz: str = "aura-2-alvaro-es"
    velocidad: float = 1.0
    sample_rate: int = 24000
    asr_modelo: str = "nova-3"
    asr_idioma: str = "es"
    tts_usd_por_1k: float = 0.030
    asr_usd_por_min: float = 0.0043
    credito_usd: float = 200.0
    reserva_usd: float = 10.0
    # Erre final ("mar" que suena "marzo"): "" (sin cambios), "suave" (IPA [ɾ]), "fuerte"
    # (IPA [r]) o "rr" ("marr" en el texto que recibe el motor). Elige con: bja probar-erre
    erre_final: str = ""


@dataclass
class ConfigElevenLabs:
    voz: str = ""
    modelo: str = "eleven_multilingual_v2"
    idioma: str = "es"
    estabilidad: float = 0.5
    similitud: float = 0.75
    estilo: float = 0.0
    velocidad: float = 1.0
    semilla: int = 1234
    formato: str = "pcm_24000"
    creditos_mes: int = 10000
    creditos_por_caracter: float = 1.0


@dataclass
class ConfigWhisper:
    modelo: str = "small"
    dispositivo: str = "cpu"
    computo: str = "int8"


@dataclass
class ConfigVerificacion:
    activa: bool = True
    racha_omision: int = 3
    racha_insercion: int = 4
    wer_max: float = 0.25
    reintentos: int = 1


@dataclass
class ConfigSalida:
    mp3_kbps: int = 64
    loudnorm_i: float = -18.0
    loudnorm_tp: float = -1.5
    loudnorm_lra: float = 11.0
    artista: str = "Biblia de Jerusalén"


@dataclass
class Config:
    raiz: Path
    proveedor: str = "deepgram"
    asr: str = "deepgram"
    edicion: str = ""
    epub: ConfigEpub = field(default_factory=ConfigEpub)
    plan: ConfigPlan = field(default_factory=ConfigPlan)
    pausas: ConfigPausas = field(default_factory=ConfigPausas)
    deepgram: ConfigDeepgram = field(default_factory=ConfigDeepgram)
    elevenlabs: ConfigElevenLabs = field(default_factory=ConfigElevenLabs)
    whisper: ConfigWhisper = field(default_factory=ConfigWhisper)
    verificacion: ConfigVerificacion = field(default_factory=ConfigVerificacion)
    salida: ConfigSalida = field(default_factory=ConfigSalida)
    deepgram_api_key: str | None = None
    elevenlabs_api_key: str | None = None
    ruta: Path | None = None  # config.toml del que se cargó (para poder editarlo)

    @property
    def ruta_config(self) -> Path:
        return self.ruta or self.raiz / "config.toml"

    @property
    def dir_trabajo(self) -> Path:
        return self.raiz / "trabajo"

    @property
    def dir_texto(self) -> Path:
        return self.dir_trabajo / "texto"

    @property
    def dir_cache(self) -> Path:
        return self.raiz / "cache"

    @property
    def dir_salida(self) -> Path:
        return self.raiz / "salida"

    @property
    def archivo_gastos(self) -> Path:
        return self.dir_trabajo / "gastos.jsonl"

    @property
    def archivo_lexico(self) -> Path:
        return self.raiz / "lexico.tsv"

    def ruta_epub(self) -> Path:
        ruta = Path(self.epub.archivo).expanduser()
        return ruta if ruta.is_absolute() else self.raiz / ruta


PROVEEDORES_TTS = ("deepgram", "elevenlabs", "simulado")
PROVEEDORES_ASR = ("deepgram", "whisper", "simulado", "ninguno")

_SECCIONES = {
    "epub": ConfigEpub,
    "plan": ConfigPlan,
    "pausas": ConfigPausas,
    "deepgram": ConfigDeepgram,
    "elevenlabs": ConfigElevenLabs,
    "whisper": ConfigWhisper,
    "verificacion": ConfigVerificacion,
    "salida": ConfigSalida,
}
_RAIZ_CLAVES = {"proveedor", "asr", "edicion"}


def _coercionar(valor: Any, default: Any, nombre: str) -> Any:
    if isinstance(default, bool):
        if not isinstance(valor, bool):
            raise ConfigError(f"'{nombre}' debe ser true o false, no {valor!r}.")
        return valor
    if isinstance(valor, bool):
        raise ConfigError(f"'{nombre}' no admite true/false; usa un {type(default).__name__}.")
    if isinstance(default, float) and isinstance(valor, int):
        return float(valor)
    if isinstance(default, (int, float, str, list, dict)) and not isinstance(valor, type(default)):
        raise ConfigError(f"'{nombre}' debe ser de tipo {type(default).__name__}, no {valor!r}.")
    return valor


def _llenar(cls: type, datos: dict[str, Any], seccion: str) -> Any:
    instancia = cls()
    conocidos = {f.name for f in fields(cls)}
    desconocidas = sorted(set(datos) - conocidos)
    if desconocidas:
        raise ConfigError(
            f"Claves desconocidas en [{seccion}]: {', '.join(desconocidas)}. "
            f"Válidas: {', '.join(sorted(conocidos))}."
        )
    cambios = {k: _coercionar(v, getattr(instancia, k), f"{seccion}.{k}") for k, v in datos.items()}
    return replace(instancia, **cambios)


def _validar(cfg: Config) -> None:
    if cfg.proveedor not in PROVEEDORES_TTS:
        raise ConfigError(f"proveedor = '{cfg.proveedor}' no existe. Opciones: {', '.join(PROVEEDORES_TTS)}.")
    if cfg.asr not in PROVEEDORES_ASR:
        raise ConfigError(f"asr = '{cfg.asr}' no existe. Opciones: {', '.join(PROVEEDORES_ASR)}.")
    v = cfg.deepgram.velocidad
    if not 0.7 <= v <= 1.5:
        raise ConfigError("deepgram.velocidad debe estar entre 0.7 y 1.5 (límite de Aura-2).")
    if round(v * 100) % 5 != 0:
        raise ConfigError("deepgram.velocidad debe ir en pasos de 0.05 (p. ej. 0.95, 1.0, 1.05).")
    if cfg.plan.max_chars > 2000 and cfg.proveedor == "deepgram":
        raise ConfigError("plan.max_chars no puede superar 2000 con Deepgram (límite por petición de Aura-2).")
    if cfg.plan.objetivo_chars > cfg.plan.max_chars:
        raise ConfigError("plan.objetivo_chars no puede ser mayor que plan.max_chars.")
    if cfg.deepgram.sample_rate not in (8000, 16000, 24000, 32000, 48000):
        raise ConfigError("deepgram.sample_rate debe ser 8000, 16000, 24000, 32000 o 48000.")
    el = cfg.elevenlabs
    if not 0.7 <= el.velocidad <= 1.2:
        raise ConfigError("elevenlabs.velocidad debe estar entre 0.7 y 1.2.")
    for nombre in ("estabilidad", "similitud", "estilo"):
        if not 0.0 <= getattr(el, nombre) <= 1.0:
            raise ConfigError(f"elevenlabs.{nombre} debe estar entre 0.0 y 1.0.")
    if not el.formato.startswith(("pcm_", "mp3_")):
        raise ConfigError("elevenlabs.formato debe ser pcm_<frecuencia> o mp3_<frecuencia>_<kbps>.")
    if cfg.verificacion.racha_omision < 1 or cfg.verificacion.racha_insercion < 1:
        raise ConfigError("Las rachas de verificación deben ser al menos 1.")
    if cfg.epub.bloque_corto_chars < 0:
        raise ConfigError("epub.bloque_corto_chars debe ser 0 (desactivado) o un número positivo.")
    from .fonetica import MODOS_ERRE

    if cfg.deepgram.erre_final not in MODOS_ERRE:
        raise ConfigError('deepgram.erre_final debe ser "", "suave", "fuerte" o "rr" (pruébalos con: bja probar-erre).')


def validar(cfg: Config) -> None:
    """Validación pública (p. ej. tras cambiar la voz o la velocidad desde la CLI)."""
    _validar(cfg)


def cargar_config(ruta: Path | None = None) -> Config:
    """Lee config.toml (si existe) y .env desde la carpeta del proyecto."""
    if ruta is None:
        ruta = Path.cwd() / "config.toml"
    ruta = ruta.expanduser().resolve()
    raiz = ruta.parent
    datos: dict[str, Any] = {}
    if ruta.exists():
        try:
            datos = tomllib.loads(ruta.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError as e:
            raise ConfigError(f"config.toml tiene un error de sintaxis: {e}") from e

    desconocidas = sorted(set(datos) - set(_SECCIONES) - _RAIZ_CLAVES)
    if desconocidas:
        raise ConfigError(f"Secciones o claves desconocidas en config.toml: {', '.join(desconocidas)}.")

    cfg = Config(raiz=raiz)
    for clave in _RAIZ_CLAVES & set(datos):
        cfg = replace(cfg, **{clave: _coercionar(datos[clave], getattr(cfg, clave), clave)})
    for seccion, cls in _SECCIONES.items():
        if seccion in datos:
            if not isinstance(datos[seccion], dict):
                raise ConfigError(f"[{seccion}] debe ser una sección de TOML.")
            cfg = replace(cfg, **{seccion: _llenar(cls, datos[seccion], seccion)})

    _cargar_env(raiz / ".env")
    cfg = replace(
        cfg,
        deepgram_api_key=os.environ.get("DEEPGRAM_API_KEY") or None,
        elevenlabs_api_key=os.environ.get("ELEVENLABS_API_KEY") or None,
        ruta=ruta,
    )
    _validar(cfg)
    return cfg


# --------------------------------------------------------------------- edición
_RE_ENCABEZADO = re.compile(r"^\s*\[([^\[\]]+)\]\s*(?:#.*)?$")


def valor_toml(valor: Any) -> str:
    """Valor de Python → literal TOML de una línea (las cadenas JSON son TOML válido)."""
    if isinstance(valor, bool):
        return "true" if valor else "false"
    if isinstance(valor, (int, float)):
        return repr(valor)
    if isinstance(valor, str):
        return json.dumps(valor, ensure_ascii=False)
    if isinstance(valor, list):
        return "[" + ", ".join(valor_toml(v) for v in valor) + "]"
    raise ConfigError(f"No sé escribir {valor!r} en TOML.")


def actualizar_config(ruta: Path, seccion: str, cambios: dict[str, Any]) -> Path:
    """Cambia claves de una sección de config.toml línea a línea, conservando comentarios.

    Deja una copia en config.toml.bak, valida el resultado cargándolo y, si no es válido,
    restaura la copia. Devuelve la ruta de la copia.
    """
    ruta = Path(ruta)
    original = ruta.read_text(encoding="utf-8") if ruta.exists() else ""
    lineas = original.splitlines()

    inicio = fin = None
    for i, linea in enumerate(lineas):
        m = _RE_ENCABEZADO.match(linea)
        if not m:
            continue
        if inicio is None and m.group(1).strip() == seccion:
            inicio = i
        elif inicio is not None:
            fin = i
            break
    if inicio is None:
        if lineas and lineas[-1].strip():
            lineas.append("")
        lineas.append(f"[{seccion}]")
        inicio = len(lineas) - 1
    if fin is None:
        fin = len(lineas)

    for clave, valor in cambios.items():
        nueva = f"{clave} = {valor_toml(valor)}"
        activa = re.compile(rf"^(\s*){re.escape(clave)}\s*=\s*(.*)$")
        comentada = re.compile(rf"^(\s*)#\s*{re.escape(clave)}\s*=")
        hecho = False
        for i in range(inicio + 1, fin):
            m = activa.match(lineas[i])
            if not m:
                continue
            resto = m.group(2).strip()
            if resto.startswith("[") and "]" not in resto:
                raise ConfigError(f"[{seccion}] {clave} ocupa varias líneas en {ruta.name}: cámbialo a mano.")
            # El comentario en línea describía el valor viejo: se descarta para no confundir.
            lineas[i] = m.group(1) + nueva
            hecho = True
            break
        if not hecho:
            # La plantilla trae la clave comentada ("# capitulo = …"): se activa ahí mismo.
            for i in range(inicio + 1, fin):
                m = comentada.match(lineas[i])
                if m:
                    lineas[i] = m.group(1) + nueva
                    hecho = True
                    break
        if not hecho:
            # Clave nueva: tras la última clave activa de la sección, o tras el encabezado.
            pos = inicio + 1
            for j in range(inicio + 1, fin):
                if lineas[j].strip() and not lineas[j].lstrip().startswith("#"):
                    pos = j + 1
            lineas.insert(pos, nueva)
            fin += 1

    texto = "\n".join(lineas) + "\n"
    try:
        tomllib.loads(texto)
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"El cambio dejaría {ruta.name} inválido ({e}); no se tocó nada.") from e
    respaldo = ruta.with_name(ruta.name + ".bak")
    if ruta.exists():
        shutil.copy2(ruta, respaldo)
    ruta.write_text(texto, encoding="utf-8")
    try:
        cargar_config(ruta)
    except ConfigError:
        if respaldo.exists():
            shutil.copy2(respaldo, ruta)
        raise
    return respaldo


def _cargar_env(ruta: Path) -> None:
    if not ruta.exists():
        return
    try:
        from dotenv import load_dotenv
    except ImportError:  # pragma: no cover
        raise ConfigError("Falta python-dotenv. Ejecuta: pip install -r requirements.txt") from None
    # override=False: una variable ya definida en el entorno manda sobre .env
    load_dotenv(ruta, override=False)
