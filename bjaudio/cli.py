"""Interfaz de línea de comandos: python -m bjaudio <comando>."""

from __future__ import annotations

import functools
import hashlib
from dataclasses import replace
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table
from rich.text import Text

from . import __version__, audio
from .asr import crear_asr
from .config import Config, cargar_config
from .errores import BjaError, PresupuestoExcedido
from .gastos import LibroGastos
from .libros import LIBROS, obtener
from .pipeline import Estimacion, Pipeline, capitulos_disponibles, parsear_rango
from .proveedores import Contexto, crear_tts, etiqueta_voz, resolver_voz
from .texto import escribir_atomico

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    rich_markup_mode=None,  # los textos de ayuda llevan [epub] literal: no interpretar como marcado
    help="Biblia en audio: EPUB sin DRM → texto canónico → voz verificada → MP3 por capítulo.",
)
consola = Console()


def _manejar_errores(funcion):
    @functools.wraps(funcion)
    def envoltura(*args, **kwargs):
        try:
            return funcion(*args, **kwargs)
        except BjaError as e:
            consola.print(f"[bold red]✗[/] {e}", markup=True, highlight=False)
            raise typer.Exit(1) from None
        except KeyError as e:  # p. ej. id de libro inexistente
            consola.print(f"[bold red]✗[/] {e.args[0] if e.args else e}", highlight=False)
            raise typer.Exit(1) from None
        except KeyboardInterrupt:
            consola.print("\n[yellow]Interrumpido.[/] Lo ya generado quedó en caché: al repetir no se vuelve a pagar.")
            raise typer.Exit(130) from None

    return envoltura


def _cfg(ctx: typer.Context) -> Config:
    return cargar_config(ctx.obj.get("config") if ctx.obj else None)


def _version(valor: bool) -> None:
    if valor:
        consola.print(f"biblia-audio {__version__}")
        raise typer.Exit()


@app.callback()
def principal(
    ctx: typer.Context,
    config: Optional[Path] = typer.Option(None, "--config", "-c", help="Ruta a config.toml (por defecto, el de la carpeta actual)."),
    version: bool = typer.Option(False, "--version", callback=_version, is_eager=True, help="Muestra la versión."),
) -> None:
    ctx.obj = {"config": config}


# ------------------------------------------------------------------ inspeccionar
_AYUDA_VOZ = "Solo para esta orden: luciano, javier, sirio… (Deepgram) o un voice_id (ElevenLabs)."
_AYUDA_VELOCIDAD = "Solo para esta orden. Deepgram: 0.7–1.5 en pasos de 0.05 (en español, 0.9 o más)."


@app.command()
@_manejar_errores
def inspeccionar(
    ctx: typer.Context,
    libro: Optional[str] = typer.Option(None, "--libro", "-l", help="Analiza un libro (gn, sal, qo…) y sugiere selectores probados."),
    doc: Optional[str] = typer.Option(None, "--doc", help="Analiza un documento concreto (número de la lista o parte de su ruta)."),
    aplicar: bool = typer.Option(False, "--aplicar", help="Guarda la sugerencia en config.toml (deja copia .bak)."),
    epub: Optional[Path] = typer.Option(None, "--epub", help="EPUB a inspeccionar (por defecto, [epub] archivo)."),
) -> None:
    """Informe de estructura del EPUB. Con --libro deduce y prueba los selectores. No gasta crédito."""
    from .config import actualizar_config
    from .inspeccion import inspeccionar as _inspeccionar

    cfg = _cfg(ctx)
    if libro:
        obtener(libro)
    if aplicar and not libro:
        raise BjaError("--aplicar necesita --libro (la sugerencia se prueba sobre un libro).")
    with consola.status("Analizando el EPUB…"):
        informe = _inspeccionar(cfg, epub, libro, doc)
    destino = cfg.dir_trabajo / "inspeccion.txt"
    escribir_atomico(destino, informe.texto)
    consola.print(informe.texto, markup=False, highlight=False, soft_wrap=True)
    consola.print(f"[green]Guardado en[/] {destino.relative_to(cfg.raiz)} — solo trae fragmentos cortos: "
                  "puedes compartirlo para pedir ayuda.")
    if aplicar:
        if not informe.cambios:
            consola.print("[yellow]No hay nada que aplicar:[/] la configuración actual ya es la mejor que encontré.")
            return
        respaldo = actualizar_config(cfg.ruta_config, "epub", informe.cambios)
        consola.print(f"[green]✓ config.toml actualizado[/] ({', '.join(informe.cambios)}). Copia anterior: "
                      f"{respaldo.name}. Siguiente: bja extraer --libro {libro}", highlight=False)


# ------------------------------------------------------------------ extraer
@app.command()
@_manejar_errores
def extraer(
    ctx: typer.Context,
    epub: Optional[Path] = typer.Option(None, "--epub", help="EPUB de origen (por defecto, [epub] archivo)."),
    libro: Optional[str] = typer.Option(None, "--libro", "-l", help="Solo este libro (id: gn, sal, mt…)."),
    forzar: bool = typer.Option(False, "--forzar", help="Sobrescribe .txt existentes aunque los hayas editado."),
) -> None:
    """EPUB → un .txt canónico por capítulo en trabajo/texto/. No gasta crédito."""
    from .extraccion import extraer_a_disco, resumen_por_libro, tiene_prologo

    cfg = _cfg(ctx)
    if libro:
        obtener(libro)
    with consola.status("Extrayendo…"):
        res, (nuevos, iguales, omitidos) = extraer_a_disco(cfg, epub, libro, forzar)
    tabla = Table(title="Extracción", show_lines=False)
    for col in ("libro", "capítulos", "versículos", "caracteres"):
        tabla.add_column(col, justify="right" if col != "libro" else "left")
    incompletos = []
    for libro_id, caps, esperados, versos, chars in resumen_por_libro(res):
        marca = "" if caps == esperados else " ←"
        if caps != esperados:
            incompletos.append(libro_id)
        extra = " + prólogo" if tiene_prologo(res, libro_id) else ""
        tabla.add_row(libro_id, f"{caps}/{esperados}{extra}{marca}", str(versos), f"{chars:,}".replace(",", "."))
    consola.print(tabla)
    consola.print(f"Escritos: {nuevos} · sin cambios: {iguales} · omitidos (ya existían y difieren): {len(omitidos)}")
    if omitidos:
        consola.print(
            "[yellow]No sobrescribí estos archivos: ya existían y son distintos de lo extraído ahora.[/] "
            "Si los editaste a mano, revisa la diferencia; si no (p. ej. venían de una versión anterior), "
            f"regenéralos con: bja extraer{f' --libro {libro}' if libro else ''} --forzar"
        )
        for o in omitidos[:10]:
            consola.print(f"  {o}", highlight=False)
    if res.avisos:
        consola.print(f"[yellow]{len(res.avisos)} avisos para revisar[/]; los primeros:")
        for a in res.avisos[:12]:
            consola.print(f"  - {a}", highlight=False, markup=False)
    consola.print(f"Informe completo: {(cfg.dir_trabajo / 'extraccion.txt').relative_to(cfg.raiz)}")
    if not res.capitulos:
        objetivo = libro or "qo"
        consola.print(f"[red]No salió ningún capítulo.[/] Prueba: bja inspeccionar --libro {objetivo}")
    elif incompletos:
        consola.print(f"Libros incompletos: {', '.join(incompletos[:10])}. Para uno de ellos: "
                      f"bja inspeccionar --libro {incompletos[0]}", highlight=False)
    elif libro:
        consola.print(f"Revisa el texto (p. ej. trabajo/texto/{libro}/001.txt) y después: bja plan {libro} 1",
                      highlight=False)


# ------------------------------------------------------------------ plan
@app.command()
@_manejar_errores
def plan(
    ctx: typer.Context,
    libro: str = typer.Argument(..., help="Id del libro: gn, ex, sal, mt…"),
    capitulo: int = typer.Argument(..., help="Número de capítulo."),
    proveedor: Optional[str] = typer.Option(None, "--proveedor", "-p", help="deepgram, elevenlabs o simulado."),
    voz: Optional[str] = typer.Option(None, "--voz", "-v", help=_AYUDA_VOZ),
    velocidad: Optional[float] = typer.Option(None, "--velocidad", help=_AYUDA_VELOCIDAD),
) -> None:
    """Muestra cómo se partirá un capítulo en trozos y cuánto costaría. No gasta crédito."""
    cfg = _cfg(ctx)
    cfg = cfg_con_voz(cfg, proveedor or cfg.proveedor, voz, velocidad)
    tts = crear_tts(cfg, proveedor)
    # Para estimar costos solo importa el ASR de pago; whisper local no se carga aquí.
    pipe = Pipeline(cfg, tts, crear_asr(cfg) if cfg.asr == "deepgram" else None)
    lib = obtener(libro)
    trozos = pipe.plan(lib, capitulo)
    est = pipe.estimar(trozos)
    tabla = Table(title=f"{lib.nombre} {capitulo} — {len(trozos)} trozos")
    for col, j in (("#", "right"), ("chars", "right"), ("versos", "left"), ("pausa", "right"), ("comienzo", "left")):
        tabla.add_column(col, justify=j)
    for t in trozos:
        versos = "anuncio" if t.anuncio else (t.versos[0][0] + ("–" + t.versos[-1][0] if len(t.versos) > 1 else "") if t.versos else "cont.")
        # Text(): el contenido del libro nunca se interpreta como marcado de rich
        tabla.add_row(str(t.indice), str(t.caracteres), versos, f"{t.pausa_ms} ms", Text(t.texto[:48].replace("\n", " ⏎ ")))
    consola.print(tabla, highlight=False)
    _imprimir_estimacion(est)
    pipe.cerrar()


def _imprimir_estimacion(est: Estimacion) -> None:
    minutos = est.segundos_audio / 60
    consola.print(
        f"Audio estimado: ~{minutos:.1f} min · por sintetizar: {est.pendientes}/{est.trozos} trozos, "
        f"{est.caracteres} caracteres · costo estimado: TTS ${est.usd_tts:.4f} + verificación ${est.usd_asr:.4f}"
    )


# ------------------------------------------------------------------ muestra
@app.command()
@_manejar_errores
def muestra(
    ctx: typer.Context,
    texto: str = typer.Argument(..., help="Texto corto para escuchar la voz (una o dos frases)."),
    proveedor: Optional[str] = typer.Option(None, "--proveedor", "-p"),
    voz: Optional[str] = typer.Option(None, "--voz", "-v", help=_AYUDA_VOZ),
    velocidad: Optional[float] = typer.Option(None, "--velocidad", help=_AYUDA_VELOCIDAD),
) -> None:
    """Sintetiza una frase para comparar voces y velocidades. Cuesta centavos; queda en salida/muestras/."""
    cfg = _cfg(ctx)
    nombre = proveedor or cfg.proveedor
    cfg = cfg_con_voz(cfg, nombre, voz, velocidad)
    if len(texto) > 500:
        raise BjaError("La muestra es para frases cortas (máx. 500 caracteres).")
    tts = crear_tts(cfg, nombre)
    tts.listo()
    audio.requerir_ffmpeg()  # antes de gastar: sin ffmpeg no se puede exportar
    pipe = Pipeline(cfg, tts, None)
    texto_tts = tts.preparar_texto(pipe.lexico.reescribir_comun(texto), pipe.lexico)
    pipe.comprobar_presupuesto(Estimacion(1, 1, len(texto_tts), len(texto_tts) / 14, tts.costo_usd(len(texto_tts)), 0.0))
    wav, de_cache, cobrados, _clave = pipe.sintetizar(texto_tts, 0, Contexto(), "muestra")
    sr = tts.sample_rate
    pcm = audio.a_pcm(wav, sr)
    huella = hashlib.sha1(texto.encode()).hexdigest()[:8]
    destino = cfg.dir_salida / "muestras" / f"{etiqueta_voz(cfg, nombre)}-{huella}.mp3"
    s = cfg.salida
    audio.exportar_mp3(pcm, sr, destino, kbps=s.mp3_kbps, loudnorm=(s.loudnorm_i, s.loudnorm_tp, s.loudnorm_lra),
                       etiquetas={"title": f"Muestra {etiqueta_voz(cfg, nombre)}", "artist": s.artista})
    costo = tts.costo_usd(cobrados)
    consola.print(f"[green]✓[/] {destino.relative_to(cfg.raiz)} · {'(desde caché) ' if de_cache else ''}"
                  f"{cobrados} caracteres · ${costo:.4f}", highlight=False)
    pipe.cerrar()


def cfg_con_voz(cfg: Config, proveedor: str, voz: str | None, velocidad: float | None) -> Config:
    """Copia de la configuración con otra voz o velocidad, validada. No toca config.toml."""
    from .config import validar

    if voz:
        voz = resolver_voz(proveedor, voz)
    if proveedor == "deepgram":
        dg = cfg.deepgram
        cfg = replace(cfg, deepgram=replace(dg, voz=voz or dg.voz, velocidad=dg.velocidad if velocidad is None else velocidad))
    elif proveedor == "elevenlabs":
        el = cfg.elevenlabs
        cfg = replace(cfg, elevenlabs=replace(el, voz=voz or el.voz, velocidad=el.velocidad if velocidad is None else velocidad))
    validar(cfg)
    return cfg


# ------------------------------------------------------------------ probar-erre
_NUMEROS = ("uno", "dos", "tres", "cuatro", "cinco")


@app.command("probar-erre")
@_manejar_errores
def probar_erre(
    ctx: typer.Context,
    voz: Optional[str] = typer.Option(None, "--voz", "-v", help=_AYUDA_VOZ),
    velocidad: Optional[float] = typer.Option(None, "--velocidad", help=_AYUDA_VELOCIDAD),
) -> None:
    """La misma frase con cuatro tratamientos de la erre final, en un solo MP3 (Deepgram; ~2 centavos)."""
    from .fonetica import sin_marcas, variantes_erre

    cfg = _cfg(ctx)
    cfg = cfg_con_voz(cfg, "deepgram", voz, velocidad)
    cfg = replace(cfg, deepgram=replace(cfg.deepgram, erre_final=""))  # cada opción trae su propio tratamiento
    tts = crear_tts(cfg, "deepgram")
    tts.listo()
    audio.requerir_ffmpeg()
    pipe = Pipeline(cfg, tts, None)
    opciones = variantes_erre(tts.seseo)
    textos = [f"Opción {_NUMEROS[i]}. {texto}" for i, (_m, _d, texto) in enumerate(opciones)]
    caracteres = sum(len(sin_marcas(t)) for t in textos)
    pipe.comprobar_presupuesto(Estimacion(len(textos), len(textos), caracteres, caracteres / 14,
                                          tts.costo_usd(caracteres), 0.0))
    sr = tts.sample_rate
    piezas: list[bytes] = []
    cobrados = 0
    for texto in textos:
        wav, _de_cache, cobrado, _clave = pipe.sintetizar(texto, 0, Contexto(), "probar-erre")
        cobrados += cobrado
        pcm, _recorte = audio.recortar_silencio(audio.a_pcm(wav, sr), sr, cfg.pausas.umbral_silencio_dbfs,
                                                cfg.pausas.margen_recorte)
        piezas += [pcm, audio.silencio(1300, sr)]
    destino = cfg.dir_salida / "muestras" / f"erre-{etiqueta_voz(cfg, 'deepgram')}.mp3"
    s = cfg.salida
    audio.exportar_mp3(b"".join(piezas), sr, destino, kbps=s.mp3_kbps,
                       loudnorm=(s.loudnorm_i, s.loudnorm_tp, s.loudnorm_lra),
                       etiquetas={"title": f"Prueba de erre · {etiqueta_voz(cfg, 'deepgram')}", "artist": s.artista})
    consola.print(f"[green]✓[/] {destino.relative_to(cfg.raiz)} · {cobrados} caracteres · ${tts.costo_usd(cobrados):.4f}",
                  highlight=False)
    tabla = Table(title="Escucha las cuatro opciones y quédate con la que diga bien «mar»")
    for col in ("opción", "qué cambia", "línea para [deepgram] en config.toml"):
        tabla.add_column(col)
    for i, (modo, descripcion, _t) in enumerate(opciones):
        tabla.add_row(str(i + 1), descripcion, f'erre_final = "{modo}"' if modo else "(nada: es como ahora)")
    consola.print(tabla)
    consola.print("Fíjate también en que «por» no suene raro y en que el resto de cada palabra siga natural. "
                  "Si ninguna mejora, cuéntamelo: hay otras salidas.", highlight=False)
    pipe.cerrar()


# ------------------------------------------------------------------ voces
@app.command()
@_manejar_errores
def voces(
    ctx: typer.Context,
    proveedor: Optional[str] = typer.Option(None, "--proveedor", "-p", help="deepgram o elevenlabs."),
    usar: Optional[str] = typer.Option(None, "--usar", help="Guarda esta voz en config.toml (p. ej. luciano o aura-2-luciano-es)."),
) -> None:
    """Lista voces en español disponibles; con --usar, deja una como predeterminada."""
    from .config import actualizar_config

    cfg = _cfg(ctx)
    nombre = proveedor or cfg.proveedor
    if usar:
        if nombre not in ("deepgram", "elevenlabs"):
            raise BjaError("--usar funciona con --proveedor deepgram o --proveedor elevenlabs.")
        usar = resolver_voz(nombre, usar)
        respaldo = actualizar_config(cfg.ruta_config, nombre, {"voz": usar})
        destino = etiqueta_voz(cfg_con_voz(cfg, nombre, usar, None), nombre)
        consola.print(f"[green]✓[/] Voz de {nombre}: {usar} (copia anterior en {respaldo.name}). Los MP3 nuevos irán a "
                      f"salida/{destino}/; los de otras voces no se tocan.", highlight=False)
        return
    if nombre == "deepgram":
        from .proveedores.deepgram import VOCES_ES

        tabla = Table(title="Deepgram Aura-2 · voces en español")
        for col in ("modelo", "voz", "acento", "rasgos"):
            tabla.add_column(col)
        for modelo, genero, acento, rasgos in VOCES_ES:
            marca = " ◀ configurada" if modelo == cfg.deepgram.voz else ""
            tabla.add_row(modelo + marca, genero, acento, rasgos)
        consola.print(tabla)
        consola.print("Ediciones de España (vosotros) → acento de España; Latinoamericana (ustedes) → México/es-419.")
    elif nombre == "elevenlabs":
        from .proveedores.elevenlabs import ElevenLabsTTS

        el = ElevenLabsTTS(cfg.elevenlabs, cfg.elevenlabs_api_key)
        tabla = Table(title="ElevenLabs · voces de tu cuenta")
        for col in ("voice_id", "nombre", "categoría", "etiquetas"):
            tabla.add_column(col)
        for v in el.listar_voces():
            etiquetas = ", ".join(f"{k}={val}" for k, val in (v.get("labels") or {}).items())
            tabla.add_row(Text(v.get("voice_id", "")), Text(v.get("name", "")), Text(v.get("category", "")), Text(etiquetas))
        consola.print(tabla)
        el.cerrar()
    else:
        raise BjaError("Usa --proveedor deepgram o --proveedor elevenlabs.")


# ------------------------------------------------------------------ correr
@app.command()
@_manejar_errores
def correr(
    ctx: typer.Context,
    libro: str = typer.Argument(..., help="Id del libro: gn, ex, sal, mt…"),
    capitulos: str = typer.Argument(..., help="Capítulos: 1, 1-3 o 1,4,7-8."),
    proveedor: Optional[str] = typer.Option(None, "--proveedor", "-p", help="deepgram, elevenlabs o simulado."),
    asr: Optional[str] = typer.Option(None, "--asr", help="deepgram, whisper, simulado o ninguno."),
    sin_verificar: bool = typer.Option(False, "--sin-verificar", help="No transcribe para verificar (más barato, menos seguro)."),
    simular: bool = typer.Option(False, "--simular", help="Solo calcula trozos y costo; no llama a ninguna API."),
    voz: Optional[str] = typer.Option(None, "--voz", "-v", help=_AYUDA_VOZ),
    velocidad: Optional[float] = typer.Option(None, "--velocidad", help=_AYUDA_VELOCIDAD),
) -> None:
    """Genera los MP3 de uno o varios capítulos (2-3 por día es el ritmo previsto).

    Con --voz/--velocidad se prueba otra voz o ritmo sin tocar config.toml: cada combinación
    va a su propia carpeta de salida, así se comparan escuchando el mismo capítulo."""
    cfg = _cfg(ctx)
    if sin_verificar:
        cfg = replace(cfg, verificacion=replace(cfg.verificacion, activa=False))
    nombre = proveedor or cfg.proveedor
    cfg = cfg_con_voz(cfg, nombre, voz, velocidad)
    lib = obtener(libro)
    numeros = parsear_rango(capitulos)
    tts = crear_tts(cfg, proveedor)
    if voz or velocidad is not None:
        consola.print(f"Voz para esta orden: {etiqueta_voz(cfg, nombre)} (config.toml no cambia)", highlight=False)
    asr_obj = crear_asr(cfg, asr) if cfg.verificacion.activa else None
    if not simular:
        tts.listo()
        if asr_obj:
            asr_obj.listo()
        audio.requerir_ffmpeg()
    pipe = Pipeline(cfg, tts, asr_obj)
    disponibles = set(capitulos_disponibles(cfg, lib.id))
    if not disponibles & set(numeros):
        pipe.cerrar()
        raise BjaError(
            f"No hay texto de {lib.nombre} en trabajo/texto/{lib.id}/. Primero extráelo:\n"
            f"  bja inspeccionar --libro {lib.id}   (comprueba y, si hace falta, --aplicar)\n"
            f"  bja extraer --libro {lib.id}"
        )
    resumenes = []
    try:
        for n in numeros:
            if n not in disponibles:
                consola.print(f"[yellow]•[/] {lib.id} {n}: no hay texto en trabajo/texto/{lib.id}/{n:03d}.txt — se salta.")
                continue
            with consola.status(f"{lib.nombre} {n}…"):
                try:
                    r = pipe.procesar(lib.id, n, simular=simular)
                except PresupuestoExcedido as e:
                    consola.print(f"[bold red]⛔ {e}[/]", highlight=False)
                    break
            resumenes.append(r)
            minutos = r.duracion / 60
            if simular:
                consola.print(f"[cyan]≈[/] {lib.id} {n}: ~{minutos:.1f} min · {r.trozos} trozos "
                              f"({r.desde_cache} en caché) · {r.caracteres_facturados} caracteres por pagar · ~${r.usd:.4f}")
                continue
            estado = "[green]✓[/]" if not r.marcados else "[yellow]![/]"
            consola.print(
                f"{estado} {lib.id} {n}: {minutos:.1f} min · {r.trozos} trozos ({r.desde_cache} de caché) · "
                f"${r.usd:.4f} · {len(r.marcados)} marcados → {r.mp3.relative_to(cfg.raiz) if r.mp3 else ''}",
                highlight=False,
            )
            for m in r.marcados:
                consola.print(f"     ↳ trozo {m.trozo} (vv. {m.versos}) en {m.minuto}: {m.motivo}", highlight=False)
                for f in m.faltantes[:2]:
                    consola.print(f"        falta: “{f[:90]}”", highlight=False, markup=False)
                for s in m.sobrantes[:2]:
                    consola.print(f"        sobra: “{s[:90]}”", highlight=False, markup=False)
    finally:
        pipe.cerrar()
    if resumenes and not simular:
        total = sum(r.usd for r in resumenes)
        marcados = sum(len(r.marcados) for r in resumenes)
        consola.print(f"Total: {len(resumenes)} capítulo(s) · ${total:.4f} · {marcados} trozo(s) para escuchar.")
        if marcados:
            consola.print("Escucha los minutos indicados. Si el error es del motor, corrige el texto o el léxico y "
                          "vuelve a correr: solo se regeneran los trozos que cambian.")


# ------------------------------------------------------------------ estado
@app.command()
@_manejar_errores
def estado(ctx: typer.Context) -> None:
    """Progreso por libro y gasto registrado. No gasta crédito."""
    cfg = _cfg(ctx)
    etiqueta = etiqueta_voz(cfg, cfg.proveedor)
    tabla = Table(title=f"Progreso · voz actual: {etiqueta}")
    for col, j in (("libro", "left"), ("con texto", "right"), ("con MP3", "right"), ("total", "right")):
        tabla.add_column(col, justify=j)
    for lib in LIBROS:
        disponibles = capitulos_disponibles(cfg, lib.id)
        con_texto = len([n for n in disponibles if n >= 1])
        prologo = " + prólogo" if 0 in disponibles else ""
        carpeta = cfg.dir_salida / etiqueta / f"{lib.orden:02d}-{lib.id}"
        mp3 = list(carpeta.glob(f"{lib.id}-*.mp3")) if carpeta.exists() else []
        con_mp3 = sum(1 for p in mp3 if not p.stem.endswith("-000"))
        prologo_mp3 = " + prólogo" if any(p.stem.endswith("-000") for p in mp3) else ""
        if disponibles or mp3:
            tabla.add_row(f"{lib.id} · {lib.nombre}", f"{con_texto}{prologo}", f"{con_mp3}{prologo_mp3}",
                          str(lib.capitulos))
    if tabla.row_count:
        consola.print(tabla)
    else:
        consola.print("Aún no hay capítulos extraídos. Empieza por: bja inspeccionar --libro qo  (o el libro que quieras)")
    gastos = LibroGastos(cfg.archivo_gastos)
    dg = cfg.deepgram
    gastado = gastos.total_usd("deepgram")
    consola.print(f"Deepgram: gastado registrado ${gastado:.4f} · disponible para el pipeline "
                  f"${max(0.0, dg.credito_usd - dg.reserva_usd - gastado):.2f} "
                  f"(crédito ${dg.credito_usd:.2f}, reserva ${dg.reserva_usd:.2f})")
    el_mes = gastos.unidades_mes("elevenlabs", "tts")
    linea_el = f"ElevenLabs: {el_mes:.0f} caracteres este mes (registro local; tope {cfg.elevenlabs.creditos_mes})"
    if cfg.elevenlabs_api_key:
        from .proveedores.elevenlabs import ElevenLabsTTS

        el = ElevenLabsTTS(cfg.elevenlabs, cfg.elevenlabs_api_key)
        cuota = el.cuota()
        el.cerrar()
        if cuota:
            linea_el += f" · la API dice {cuota[0]}/{cuota[1]} créditos usados"
    consola.print(linea_el)


def main() -> None:
    app(prog_name="bja")


if __name__ == "__main__":
    main()
