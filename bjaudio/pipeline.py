"""Orquestación de un capítulo: plan → presupuesto → síntesis (con caché) → verificación → MP3.

Todo el control de flujo es código determinístico. Los modelos solo sintetizan y
transcriben; su salida no se da por buena hasta pasar la verificación.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from collections.abc import Callable

from . import audio
from .asr import ASR, Palabra, segundos_de
from .cache import CacheAudio
from .config import Config
from .errores import BjaError, PresupuestoExcedido
from .gastos import LibroGastos
from .lexico import Lexico, cargar_lexico
from .libros import Libro, obtener
from .plan import Trozo, planificar
from .proveedores import Contexto, ProveedorTTS, etiqueta_voz
from .texto import escribir_atomico, leer, ruta_capitulo
from .verificacion import Resultado, clave_unica, estimar_tiempos, verificar

CHARS_POR_SEGUNDO = 14.0  # ~150 palabras por minuto en español; solo para estimar costos


@dataclass
class Marcado:
    trozo: int
    versos: str
    minuto: str  # posición en el MP3 final, para ir a escuchar
    motivo: str
    faltantes: list[str]
    sobrantes: list[str]


@dataclass
class ResumenCapitulo:
    libro: str
    capitulo: int
    mp3: Path | None
    duracion: float = 0.0
    trozos: int = 0
    sintetizados: int = 0
    desde_cache: int = 0
    caracteres_facturados: int = 0
    usd_tts: float = 0.0
    usd_asr: float = 0.0
    marcados: list[Marcado] = field(default_factory=list)
    simulacion: bool = False

    @property
    def usd(self) -> float:
        return self.usd_tts + self.usd_asr


@dataclass
class Estimacion:
    trozos: int
    pendientes: int
    caracteres: int
    segundos_audio: float
    usd_tts: float
    usd_asr: float


def _mmss(segundos: float) -> str:
    m, s = divmod(int(round(segundos)), 60)
    return f"{m:02d}:{s:02d}"


def _rango(versos: list[tuple[str, int]]) -> str:
    if not versos:
        return "anuncio"
    return versos[0][0] if len(versos) == 1 else f"{versos[0][0]}–{versos[-1][0]}"


class Pipeline:
    def __init__(self, cfg: Config, tts: ProveedorTTS, asr: ASR | None,
                 avisar: Callable[[str], None] = lambda _m: None):
        self.cfg = cfg
        self.tts = tts
        self.asr = asr if cfg.verificacion.activa else None
        self.avisar = avisar
        self.cache = CacheAudio(cfg.dir_cache)
        self.gastos = LibroGastos(cfg.archivo_gastos)
        self.lexico: Lexico = cargar_lexico(cfg.archivo_lexico)

    # ---------------------------------------------------------------- utilidades
    def _texto_tts(self, trozo: Trozo) -> str:
        return self.tts.preparar_texto(trozo.texto, self.lexico)

    def _clave(self, texto_tts: str, variante: int) -> str:
        return self.cache.clave(self.tts.firma(), texto_tts, variante)

    def plan(self, libro: Libro, capitulo: int) -> list[Trozo]:
        ruta = ruta_capitulo(self.cfg.dir_texto, libro.id, capitulo)
        if not ruta.exists():
            raise BjaError(
                f"No existe {ruta.relative_to(self.cfg.raiz)}. Ejecuta primero 'extraer' "
                "o crea el archivo a mano con el formato canónico (ver README)."
            )
        cap = leer(ruta)
        if cap.libro != libro.id or cap.numero != capitulo:
            raise BjaError(f"{ruta.name} dice '# {cap.libro} {cap.numero}' pero se esperaba '# {libro.id} {capitulo}'.")
        unos = cap.versiculos.count("1")
        if unos >= 3:
            # Un capítulo con tres «1» trae varios capítulos dentro: suele ser un .txt de una
            # extracción vieja que no se pisó. Mejor parar que pagar el libro entero dos veces.
            raise BjaError(
                f"{ruta.relative_to(self.cfg.raiz)} parece contener varios capítulos (el versículo 1 aparece "
                f"{unos} veces). Si viene de una extracción anterior, regenéralo: "
                f"bja extraer --libro {libro.id} --forzar"
            )
        return planificar(cap, libro, self.cfg, self.lexico, self.tts.max_chars)

    def estimar(self, trozos: list[Trozo]) -> Estimacion:
        """Qué falta por pagar: síntesis de trozos sin audio en caché y verificación de
        trozos sin transcripción en caché (las dos cosas se guardan y no se repiten)."""
        pendientes: list[Trozo] = []
        segundos_asr = 0.0
        for t in trozos:
            clave = self._clave(self._texto_tts(t), 0)
            tiene_audio = self.cache.existe(self.tts.nombre, clave)
            if not tiene_audio:
                pendientes.append(t)
            if self.asr is not None and (
                not tiene_audio or self.cache.obtener_transcripcion(self.tts.nombre, clave, self.asr.firma()) is None
            ):
                segundos_asr += len(t.texto) / CHARS_POR_SEGUNDO
        chars = sum(len(t.texto) for t in pendientes)
        segundos = sum(len(t.texto) for t in trozos) / CHARS_POR_SEGUNDO
        usd_asr = self.asr.costo_usd(segundos_asr) if self.asr else 0.0
        return Estimacion(len(trozos), len(pendientes), chars, segundos, self.tts.costo_usd(chars), usd_asr)

    def comprobar_presupuesto(self, est: Estimacion) -> None:
        """Aborta ANTES de llamar a cualquier API si el gasto no cabe."""
        tts_dg = self.tts.nombre == "deepgram"
        asr_dg = self.asr is not None and self.asr.nombre == "deepgram"
        if tts_dg or asr_dg:
            gasto = (est.usd_tts if tts_dg else 0.0) + (est.usd_asr if asr_dg else 0.0)
            dg = self.cfg.deepgram
            disponible = dg.credito_usd - dg.reserva_usd - self.gastos.total_usd("deepgram")
            if gasto > disponible:
                raise PresupuestoExcedido(
                    f"Deepgram: esto costaría ~${gasto:.3f} y quedan ${max(0.0, disponible):.2f} "
                    f"(crédito ${dg.credito_usd:.2f} − reserva ${dg.reserva_usd:.2f} − gastado registrado). "
                    "No se llamó a la API. Si tu consola muestra otro saldo, actualiza deepgram.credito_usd."
                )
        if self.tts.nombre == "elevenlabs" and est.caracteres:
            el = self.cfg.elevenlabs
            usados = self.gastos.unidades_mes("elevenlabs", "tts") * el.creditos_por_caracter
            necesarios = est.caracteres * el.creditos_por_caracter
            if usados + necesarios > el.creditos_mes:
                raise PresupuestoExcedido(
                    f"ElevenLabs: harían falta ~{necesarios:.0f} créditos y este mes llevas {usados:.0f} "
                    f"de {el.creditos_mes}. No se llamó a la API."
                )
            self.tts.comprobar_cuota(est.caracteres)

    # ---------------------------------------------------------------- síntesis
    def sintetizar(self, texto_tts: str, variante: int, contexto: Contexto,
                   referencia: str) -> tuple[bytes, bool, int, str]:
        """Devuelve (wav, venía_de_caché, caracteres_facturados, clave_de_caché)."""
        clave = self._clave(texto_tts, variante)
        en_cache = self.cache.obtener(self.tts.nombre, clave)
        if en_cache is not None:
            return en_cache, True, 0, clave
        contexto.variante = variante
        resultado = self.tts.sintetizar(texto_tts, contexto)
        # Primero se anota el gasto: la API ya cobró aunque algo falle después.
        self.gastos.registrar(self.tts.nombre, "tts", resultado.caracteres,
                              self.tts.costo_usd(resultado.caracteres), referencia)
        # Cabecera limpia y formato único antes de guardar: el ASR y el ensamblado
        # reciben siempre PCM16 mono a la frecuencia del motor.
        wav = audio.normalizar_wav(resultado.wav, self.tts.sample_rate)
        self.cache.guardar(self.tts.nombre, clave, wav, {
            "texto": texto_tts, "firma": self.tts.firma(), "variante": variante,
            "caracteres": resultado.caracteres, "id_peticion": resultado.id_peticion,
        })
        return wav, False, resultado.caracteres, clave

    def _verificar(self, trozo: Trozo, wav: bytes, clave: str, referencia: str,
                   resumen: ResumenCapitulo) -> Resultado | None:
        if self.asr is None:
            return None
        segundos = segundos_de(wav)
        guardadas = self.cache.obtener_transcripcion(self.tts.nombre, clave, self.asr.firma())
        if guardadas is not None:
            palabras = [Palabra(t, a, b) for t, a, b in guardadas]
        else:
            palabras = self.asr.transcribir(wav, trozo.texto)
            costo = self.asr.costo_usd(segundos)
            if costo:
                self.gastos.registrar(self.asr.nombre, "asr", round(segundos, 2), costo, referencia)
                resumen.usd_asr += costo
            self.cache.guardar_transcripcion(self.tts.nombre, clave, self.asr.firma(),
                                             [[p.texto, p.inicio, p.fin] for p in palabras])
        return verificar(trozo.texto, trozo.versos, palabras, self.cfg.verificacion, segundos)

    def _cabe_reintento(self, caracteres: int) -> bool:
        try:
            self.comprobar_presupuesto(Estimacion(1, 1, caracteres, caracteres / CHARS_POR_SEGUNDO,
                                                  self.tts.costo_usd(caracteres),
                                                  self.asr.costo_usd(caracteres / CHARS_POR_SEGUNDO) if self.asr else 0.0))
            return True
        except PresupuestoExcedido:
            return False

    # ---------------------------------------------------------------- capítulo
    def procesar(self, libro_id: str, capitulo: int, simular: bool = False) -> ResumenCapitulo:
        libro = obtener(libro_id)
        trozos = self.plan(libro, capitulo)
        est = self.estimar(trozos)
        resumen = ResumenCapitulo(libro.id, capitulo, None, trozos=len(trozos), simulacion=simular)
        if simular:
            resumen.usd_tts, resumen.usd_asr = est.usd_tts, est.usd_asr
            resumen.caracteres_facturados = est.caracteres
            resumen.duracion = est.segundos_audio
            resumen.sintetizados = est.pendientes
            resumen.desde_cache = est.trozos - est.pendientes
            return resumen
        self.comprobar_presupuesto(est)

        sr = self.tts.sample_rate
        p = self.cfg.pausas
        piezas: list[bytes] = []
        cursor = 0.0
        tiempos_versos: dict[str, float] = {}
        tiempos_secciones: list[dict] = []
        verificaciones: list[dict] = []
        for i, trozo in enumerate(trozos):
            ref = f"{libro.id} {capitulo} #{trozo.indice}"
            contexto = Contexto(
                texto_anterior=trozos[i - 1].texto if i > 0 else None,
                texto_siguiente=trozos[i + 1].texto if i + 1 < len(trozos) else None,
            )
            texto_tts = self._texto_tts(trozo)
            wav, de_cache, cobrados, clave = self.sintetizar(texto_tts, 0, contexto, ref)
            resumen.desde_cache += de_cache
            resumen.sintetizados += not de_cache
            resumen.caracteres_facturados += cobrados
            resultado = self._verificar(trozo, wav, clave, ref, resumen)

            # Reintento solo si el motor es estocástico (otra semilla puede dar otro audio)
            # y si el presupuesto lo permite. Se queda el intento menos grave.
            intentos = self.cfg.verificacion.reintentos if self.tts.estocastico else 0
            variante = 0
            while resultado is not None and resultado.marcado and variante < intentos:
                variante += 1
                if not self.cache.existe(self.tts.nombre, self._clave(texto_tts, variante)) and not self._cabe_reintento(len(texto_tts)):
                    break
                wav2, de_cache2, cobrados2, clave2 = self.sintetizar(texto_tts, variante, contexto, ref)
                resumen.sintetizados += not de_cache2
                resumen.caracteres_facturados += cobrados2
                r2 = self._verificar(trozo, wav2, clave2, ref, resumen)
                if r2 is not None and r2.gravedad() < resultado.gravedad():
                    wav, resultado = wav2, r2

            pcm = audio.a_pcm(wav, sr)
            pcm, recorte = audio.recortar_silencio(pcm, sr, p.umbral_silencio_dbfs, p.margen_recorte)
            for titulo in trozo.secciones:
                tiempos_secciones.append({"titulo": titulo, "t": round(cursor, 3)})
            if resultado is not None:
                # Tiempos del ASR: relativos al audio sin recortar.
                locales = {v: max(0.0, t - recorte) for v, t in resultado.tiempos.items()}
                verificaciones.append({"trozo": trozo.indice, "versos": _rango(trozo.versos), **resultado.a_dict()})
                if resultado.marcado:
                    resumen.marcados.append(Marcado(trozo.indice, _rango(trozo.versos), _mmss(cursor),
                                                    resultado.motivo, resultado.faltantes, resultado.sobrantes))
            else:
                locales = estimar_tiempos(trozo.versos, trozo.texto, audio.duracion(pcm, sr))
            for verso, t in locales.items():
                # Una etiqueta solo se registra donde EMPIEZA el versículo; si vuelve a salir
                # es numeración doble de la edición (Dn 3 en la BJ): se guarda como "24#2".
                tiempos_versos[clave_unica(tiempos_versos, verso)] = round(cursor + t, 3)
            piezas.append(pcm)
            piezas.append(audio.silencio(trozo.pausa_ms, sr))
            cursor += audio.duracion(pcm, sr) + trozo.pausa_ms / 1000

        pcm_total = b"".join(piezas)
        resumen.duracion = audio.duracion(pcm_total, sr)
        resumen.usd_tts = self.tts.costo_usd(resumen.caracteres_facturados)

        etiqueta = etiqueta_voz(self.cfg, self.tts.nombre)
        carpeta = self.cfg.dir_salida / etiqueta / f"{libro.orden:02d}-{libro.id}"
        mp3 = carpeta / f"{libro.id}-{capitulo:03d}.mp3"
        s = self.cfg.salida
        audio.exportar_mp3(
            pcm_total, sr, mp3, kbps=s.mp3_kbps, loudnorm=(s.loudnorm_i, s.loudnorm_tp, s.loudnorm_lra),
            etiquetas={
                "title": f"{libro.nombre} {capitulo}" if capitulo else f"{libro.nombre}, prólogo",
                "album": libro.nombre,
                "artist": s.artista,
                "track": f"{capitulo}/{libro.capitulos}" if capitulo else "",
                "genre": "Speech",
                "comment": self.cfg.edicion or "uso personal",
            },
        )
        indice = {
            "libro": libro.id, "capitulo": capitulo, "edicion": self.cfg.edicion,
            "voz": etiqueta, "duracion": round(resumen.duracion, 3),
            "versiculos": tiempos_versos, "secciones": tiempos_secciones,
            "tiempos": "verificados" if self.asr is not None else "aproximados",
            "marcados": [asdict(m) for m in resumen.marcados],
            "generado": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        escribir_atomico(mp3.with_suffix(".json"), json.dumps(indice, ensure_ascii=False, indent=2))
        if verificaciones:
            destino = self.cfg.dir_trabajo / "verificacion" / etiqueta / libro.id / f"{capitulo:03d}.json"
            escribir_atomico(destino, json.dumps(verificaciones, ensure_ascii=False, indent=2))
        resumen.mp3 = mp3
        return resumen

    def cerrar(self) -> None:
        self.tts.cerrar()
        if self.asr:
            self.asr.cerrar()


def parsear_rango(texto: str) -> list[int]:
    """'1-3' → [1, 2, 3]; '1,4,7-8' → [1, 4, 7, 8]."""
    numeros: list[int] = []
    for parte in texto.replace(" ", "").split(","):
        if not parte:
            continue
        if "-" in parte:
            a, b = parte.split("-", 1)
            if not (a.isdigit() and b.isdigit()) or int(a) > int(b):
                raise BjaError(f"Rango inválido: '{parte}'. Usa por ejemplo 1-3 o 1,4,7-8.")
            numeros.extend(range(int(a), int(b) + 1))
        elif parte.isdigit():
            numeros.append(int(parte))
        else:
            raise BjaError(f"Rango inválido: '{parte}'.")
    if not numeros:
        raise BjaError("Indica al menos un capítulo, p. ej. 1 o 1-3.")
    return sorted(dict.fromkeys(numeros))


def capitulos_disponibles(cfg: Config, libro_id: str) -> list[int]:
    carpeta = cfg.dir_texto / libro_id
    if not carpeta.exists():
        return []
    return sorted(int(p.stem) for p in carpeta.glob("*.txt") if p.stem.isdigit())
