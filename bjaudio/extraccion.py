"""EPUB → texto canónico, de forma determinística y configurable.

No hay IA aquí a propósito: extraer texto de un EPUB es un problema de estructura
(etiquetas y clases), y un parser lo resuelve exacto, gratis y repetible. Un modelo de
lenguaje podría parafrasear, "corregir" u omitir un versículo sin avisar.

Funcionamiento:
1. Se limpia cada documento: se eliminan notas, llamadas a nota y lo que indiques en
   [epub] eliminar.
2. Se recorre el árbol en orden de lectura y se emiten eventos: libro, capítulo,
   versículo, sección, línea, párrafo, texto.
3. Una máquina de estados convierte esos eventos en capítulos canónicos.

Reglas que protegen contra el texto que no es Biblia (introducciones, notas, índices):
- Un título que encaja en `ignorar_titulos` (por defecto, "Notas…") cierra el libro.
- Un título que no es de ningún libro también lo cierra (salvo que lo declares sección).
- Un capítulo sin ningún versículo numerado CON TEXTO se descarta: suele ser una
  referencia en negrita dentro de una introducción ("véase 3 1-8"), a veces seguida de una
  llamada de nota numérica.
- Si el mismo número de capítulo sale varias veces, se distinguen dos casos:
  · trozos con versículos DISTINTOS (la BJ traspone versículos: 1 R 4–5, Est 1): se unen
    en el orden del libro, para no perder texto;
  · trozos que REPITEN versículos (un duplicado): se queda el más sólido y se avisa.
- Un trozo sin marca de capítulo antes del capítulo 1, con sus propios versículos (el
  prólogo del Eclesiástico), se guarda como capítulo 0 y se anuncia «Prólogo».
- Texto entre la marca de capítulo y el versículo 1 (la BJ traslada ahí el final del
  versículo anterior: 1 S 11, Ne 8, Ag 2) queda como versículo 0.
- Un bloque que solo contiene un número romano ("I", "IV") es un título editorial.
- Un número de versículo entre corchetes ("[21]") es un versículo que la edición no trae:
  no se lee y no cuenta como faltante.
"""

from __future__ import annotations

import hashlib
import html
import json
import re
import statistics
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass, field, replace
from pathlib import Path

import soupsieve as sv
from bs4 import BeautifulSoup
from bs4.element import Comment, Declaration, Doctype, NavigableString, ProcessingInstruction, Tag

from .config import Config, ConfigEpub
from .epub import Epub, decodificar, parsear_xhtml
from .errores import ConfigError
from .libros import POR_ID, SECCION as TITULO_SECCION, Libro, detectar_libro_detalle, obtener
from .texto import (
    LINEA, NINGUNA, PARRAFO, SECCION, VERSICULO, Capitulo, Omitido, Seccion, Unidad, escribir, escribir_atomico,
    ruta_capitulo,
)

_TIPOS_NOTA = {"footnote", "endnote", "rearnote", "note", "footnotes", "endnotes", "rearnotes", "noteref", "annoref"}
_BLOQUES = frozenset({
    "p", "div", "li", "ul", "ol", "blockquote", "section", "article", "table", "tr", "td", "th",
    "dd", "dt", "dl", "pre", "figure", "header", "footer", "h1", "h2", "h3", "h4", "h5", "h6",
})
_LISTA_BLOQUES = sorted(_BLOQUES)
_INVISIBLES = dict.fromkeys(map(ord, "­​‌‍﻿"), None)
_RE_NO_LATINO = re.compile(r"[Ͱ-Ͽἀ-῿֐-׿]")
# "[21]" o "[7] 8": versículo que la edición numera pero no trae (va en nota o se omite).
_RE_OMITIDO = re.compile(r"^\s*\[\s*(\d{1,3}[a-z]{0,2}(?:\s*[-–]\s*\d{1,3}[a-z]{0,2})?)\s*\]\s*(.*?)\s*$")
_RE_ROMANO = re.compile(r"(?=[IVXLC])[IVXLC]{1,7}\.?")
_NO_TEXTO = (Comment, ProcessingInstruction, Doctype, Declaration)


def _compilar(selector: str, nombre: str) -> sv.SoupSieve | None:
    selector = selector.strip().strip(",").strip()
    if not selector:
        return None
    try:
        return sv.compile(selector)
    except sv.SelectorSyntaxError as e:
        raise ConfigError(f"Selector CSS inválido en [epub] {nombre} = '{selector}': {e}") from e


def _regex(patron: str, nombre: str, flags: int = 0) -> re.Pattern[str]:
    try:
        return re.compile(patron, flags)
    except re.error as e:
        raise ConfigError(f"Expresión regular inválida en [epub] {nombre}: {e}") from e


@dataclass
class Selectores:
    libro: sv.SoupSieve | None
    capitulo: sv.SoupSieve | None
    versiculo: sv.SoupSieve | None
    seccion: sv.SoupSieve | None
    linea: sv.SoupSieve | None
    estrofa: sv.SoupSieve | None
    rotulo: sv.SoupSieve | None
    eliminar: sv.SoupSieve | None
    re_capitulo: re.Pattern[str]
    re_versiculo: re.Pattern[str]
    re_nota: re.Pattern[str]
    ignorar_titulos: list[re.Pattern[str]]
    ignorar_documentos: list[re.Pattern[str]]
    bloque_corto: int

    @classmethod
    def desde(cls, c: ConfigEpub) -> Selectores:
        return cls(
            libro=_compilar(c.titulo_libro, "titulo_libro"),
            capitulo=_compilar(c.capitulo, "capitulo"),
            versiculo=_compilar(c.versiculo, "versiculo"),
            seccion=_compilar(c.titulo_seccion, "titulo_seccion"),
            linea=_compilar(c.linea_poetica, "linea_poetica"),
            estrofa=_compilar(c.estrofa, "estrofa"),
            rotulo=_compilar(c.rotulo, "rotulo"),
            eliminar=_compilar(", ".join(s for s in c.eliminar if s.strip()), "eliminar"),
            re_capitulo=_regex(c.capitulo_regex, "capitulo_regex", re.IGNORECASE),
            re_versiculo=_regex(c.versiculo_regex, "versiculo_regex"),
            re_nota=_regex(c.marcador_nota_regex, "marcador_nota_regex"),
            ignorar_titulos=[_regex(p, "ignorar_titulos", re.IGNORECASE) for p in c.ignorar_titulos],
            ignorar_documentos=[_regex(p, "ignorar_documentos") for p in c.ignorar_documentos],
            bloque_corto=c.bloque_corto_chars,
        )

    def numero_capitulo(self, texto: str) -> int | None:
        m = self.re_capitulo.search(texto)
        if not m:
            return None
        grupo = next((g for g in m.groups() if g), None) if m.groups() else m.group(0)
        return int(grupo) if grupo and grupo.isdigit() else None

    def etiqueta_versiculo(self, texto: str) -> str | None:
        m = self.re_versiculo.match(texto)
        if not m:
            return None
        return normalizar_etiqueta(m.group(1) if m.groups() else m.group(0))

    def titulo_ignorado(self, titulo: str) -> bool:
        return any(p.search(titulo) for p in self.ignorar_titulos)


def texto_de(tag: Tag) -> str:
    """Texto de un elemento con espacios entre sus partes (para números y marcas)."""
    return re.sub(r"\s+", " ", tag.get_text(" ", strip=True).translate(_INVISIBLES)).strip()


def texto_titulo(tag: Tag) -> str:
    """Texto de un título tal como se lee: las etiquetas en línea no separan palabras
    (versalitas como <span>L</span>A AMADA dan "LA AMADA") y no queda espacio antes de la
    puntuación que seguía a una llamada de nota ya eliminada ("Prólogo." y no "Prólogo .")."""
    partes: list[str] = []
    for d in tag.descendants:
        if isinstance(d, NavigableString) and not isinstance(d, _NO_TEXTO):
            partes.append(str(d))
        elif isinstance(d, Tag) and d.name == "br":
            partes.append(" ")
    return _limpiar("".join(partes).translate(_INVISIBLES))


_SEP_ALTERNATIVA = "\x1f"


def _con_alternativa(titulo: str, alternativo: str) -> str:
    """Un título se lee sin espacios entre etiquetas en línea (versalitas), pero si así no se
    reconoce se prueba con espacios (<span>CARTA A LOS</span><span>ROMANOS</span>)."""
    return titulo if alternativo == titulo else f"{titulo}{_SEP_ALTERNATIVA}{alternativo}"


def _detectar_titulo(valor: str, titulos: dict[str, str]) -> tuple[str, Libro | None, str]:
    variantes = valor.split(_SEP_ALTERNATIVA)
    primero = None
    for texto in variantes:
        libro, modo = detectar_libro_detalle(texto, titulos)
        if primero is None:
            primero = (texto, libro, modo)
        if libro is not None or modo == TITULO_SECCION:
            return texto, libro, modo
    assert primero is not None
    return primero


def normalizar_etiqueta(etiqueta: str) -> str:
    """'24 – 25' → '24-25'; '12a' queda igual."""
    return re.sub(r"\s+", "", etiqueta).replace("–", "-")


def limpiar_documento(cuerpo: Tag, sel: Selectores) -> None:
    for t in cuerpo.find_all(["script", "style"]):
        t.decompose()
    if sel.eliminar:
        for t in [x for x in cuerpo.find_all(True) if sel.eliminar.match(x)]:
            t.decompose()
    for t in cuerpo.find_all(True):
        tipo = t.get("epub:type")
        if tipo and set(str(tipo).split()) & _TIPOS_NOTA:
            t.decompose()
    for t in cuerpo.find_all(["sup", "a"]):
        contenido = t.get_text()
        if sel.re_nota.match(contenido) and not sel.re_versiculo.match(contenido):
            t.decompose()


def es_hoja(tag: Tag) -> bool:
    """Bloque sin bloques dentro (un <p> con texto y elementos en línea)."""
    return tag.find(_LISTA_BLOQUES) is None


@dataclass
class _EstadoBloques:
    previo_corto: bool = False


def eventos(nodo: Tag, sel: Selectores, estado: _EstadoBloques | None = None) -> Iterator[tuple[str, str]]:
    if estado is None:
        estado = _EstadoBloques()
    for hijo in nodo.children:
        if isinstance(hijo, (Comment, ProcessingInstruction, Doctype, Declaration)):
            continue
        if isinstance(hijo, NavigableString):
            yield "texto", str(hijo).translate(_INVISIBLES)
            continue
        if not isinstance(hijo, Tag):
            continue
        nombre = (hijo.name or "").lower()
        if sel.libro and sel.libro.match(hijo):
            estado.previo_corto = False
            yield "libro", _con_alternativa(texto_titulo(hijo), texto_de(hijo))
            continue
        if sel.capitulo and sel.capitulo.match(hijo):
            n = sel.numero_capitulo(texto_de(hijo))
            if n is not None:
                if nombre in _BLOQUES:
                    estado.previo_corto = False
                yield "capitulo", str(n)
                continue
        if sel.versiculo and sel.versiculo.match(hijo):
            contenido = texto_de(hijo)
            etiqueta = sel.etiqueta_versiculo(contenido)
            if etiqueta:
                yield "versiculo", etiqueta
                continue
            m = _RE_OMITIDO.match(contenido)
            if m:
                yield "omitido", normalizar_etiqueta(m.group(1))
                siguiente = sel.etiqueta_versiculo(m.group(2)) if m.group(2) else None
                if siguiente:
                    yield "versiculo", siguiente
                continue
            if nombre == "sup":  # superíndice que no es número: llamada a nota o similar
                continue
        if sel.seccion and sel.seccion.match(hijo):
            estado.previo_corto = False
            titulo = texto_titulo(hijo)
            if titulo:
                yield "seccion", titulo
            continue
        if nombre in _BLOQUES and es_hoja(hijo) and _RE_ROMANO.fullmatch(texto_de(hijo)):
            # "I", "II"… centrados (las cinco imprecaciones de Habacuc): división editorial.
            estado.previo_corto = False
            yield "seccion", texto_de(hijo)
            continue
        if nombre == "br":
            yield "linea", ""
            continue
        if sel.rotulo and sel.rotulo.match(hijo):
            # Rótulo leído («La amada», «Álef»): párrafo propio, nunca línea de un poema.
            estado.previo_corto = False
            yield "parrafo", ""
            yield from eventos(hijo, sel, estado)
            yield "parrafo", ""
            estado.previo_corto = False
            continue
        if sel.estrofa and sel.estrofa.match(hijo):
            estado.previo_corto = False
            yield "parrafo", ""
        if sel.linea and sel.linea.match(hijo):
            yield from eventos(hijo, sel, estado)
            yield "linea", ""
            estado.previo_corto = True
            continue
        if nombre in _BLOQUES:
            corto = sel.bloque_corto > 0 and es_hoja(hijo) and len(texto_de(hijo)) <= sel.bloque_corto
            if not (corto and estado.previo_corto):
                yield "parrafo", ""
            yield from eventos(hijo, sel, estado)
            if corto:
                yield "linea", ""
                estado.previo_corto = True
            else:
                yield "parrafo", ""
                estado.previo_corto = False
            continue
        yield from eventos(hijo, sel, estado)


def _limpiar(texto: str) -> str:
    texto = re.sub(r"\s+", " ", texto).strip()
    texto = re.sub(r"\s+([,.;:!?…»”’)\]])", r"\1", texto)
    return re.sub(r"([«“‘(\[¿¡])\s+", r"\1", texto)


@dataclass
class TituloVisto:
    texto: str
    libro: str | None
    modo: str  # exacto, nombre, ordinal, sin ordinal → primer libro, config, seccion, ignorado, no reconocido
    documento: str


@dataclass
class ResultadoExtraccion:
    capitulos: list[Capitulo] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)
    titulos: list[TituloVisto] = field(default_factory=list)
    descartados: list[str] = field(default_factory=list)
    notas: list[str] = field(default_factory=list)  # informativas: no requieren revisión
    caracteres_ignorados: int = 0
    documentos: int = 0

    @property
    def titulos_no_reconocidos(self) -> list[str]:
        return [t.texto for t in self.titulos if t.modo == "no reconocido"]

    def registrar_titulo(self, titulo: TituloVisto) -> None:
        if not any(t.texto == titulo.texto and t.documento == titulo.documento for t in self.titulos):
            self.titulos.append(titulo)


class _Ensamblador:
    def __init__(self, cfg: ConfigEpub, sel: Selectores, res: ResultadoExtraccion):
        self.cfg = cfg
        self.sel = sel
        self.res = res
        self.libro: Libro | None = None
        self.cap: Capitulo | None = None
        self.verso: str | None = None
        self.abierta: Unidad | None = None
        self.pendiente = NINGUNA
        self.explicitos = 0  # números de versículo explícitos en el capítulo abierto
        self.implicito = False  # el texto abierto se asumió como versículo 1 (sin número)
        self.abierta_numerada = False  # la unidad abierta empezó con un número de versículo
        self.documento = ""
        self.titulo_actual = "(antes del primer título)"
        self.ignorando = False
        self.fuera: Counter[str] = Counter()  # marcas de capítulo sin libro, por título
        # Títulos de sección vistos antes de que empiece el capítulo al que pertenecen
        # (en la BJ el título va antes del párrafo que lleva el número de capítulo).
        self.secciones_pendientes: list[str] = []

    # -- utilidades
    def _cerrar_unidad(self) -> None:
        u = self.abierta
        numerada = self.abierta_numerada
        self.abierta = None
        self.abierta_numerada = False
        if u is None or self.cap is None:
            return
        u.texto = _limpiar(u.texto)
        if u.texto:
            self.cap.unidades.append(u)
            self.cap.numerados += numerada
        elif u.inicia_versiculo:
            self.cap.avisos.append(f"{self.cap.libro} {self.cap.numero}:{u.versiculo} — versículo sin texto")

    def _cerrar_capitulo(self) -> None:
        self._cerrar_unidad()
        cap, explicitos = self.cap, self.explicitos
        self.cap = None
        self.verso = None
        self.pendiente = NINGUNA
        self.explicitos = 0
        self.implicito = False
        if cap is None or not cap.unidades:
            return
        if explicitos == 0 or cap.numerados == 0:
            self.res.descartados.append(
                f"{cap.libro} {cap.numero} en {cap.origen}: ningún versículo numerado con texto "
                "(suele ser una referencia en negrita dentro de una introducción)"
            )
            return
        self.res.capitulos.append(cap)

    def _abrir_capitulo(self, numero: int, explicito: bool) -> None:
        assert self.libro is not None
        self.cap = Capitulo(self.libro.id, numero, origen=self.documento, explicito=explicito)
        self.verso = None
        self.pendiente = NINGUNA
        self.explicitos = 0
        self.implicito = False
        if self.secciones_pendientes:
            self.cap.secciones = [Seccion(t, 0) for t in self.secciones_pendientes]
            self.pendiente = SECCION
            self.secciones_pendientes = []

    def _soltar_secciones_finales(self) -> None:
        """Pasa al capítulo siguiente los títulos que quedaron al final del actual."""
        if self.cap is None:
            return
        self._cerrar_unidad()
        n = len(self.cap.unidades)
        finales = [s.titulo for s in self.cap.secciones if s.antes_de >= n]
        if finales:
            self.cap.secciones = [s for s in self.cap.secciones if s.antes_de < n]
            self.secciones_pendientes = finales + self.secciones_pendientes

    # -- eventos
    def texto(self, s: str) -> None:
        if self.cap is None:
            self.res.caracteres_ignorados += len(s.strip())
            return
        if self.abierta is None:
            if not s.strip():
                return
            if self.verso is None:
                if not self.cfg.versiculo_implicito:
                    self.res.caracteres_ignorados += len(s.strip())
                    return
                self.verso = "1"
                self.implicito = True
                self.abierta = Unidad("1", "", max(self.pendiente, VERSICULO), True, implicita=True)
            else:
                self.abierta = Unidad(self.verso, "", self.pendiente, False)
            self.pendiente = NINGUNA
        elif not self.abierta.texto.strip() and s.strip() and self.pendiente:
            self.abierta.ruptura = max(self.abierta.ruptura, self.pendiente)
            self.pendiente = NINGUNA
        self.abierta.texto += s

    def versiculo(self, v: str) -> None:
        if self.cap is None:
            # Capítulo 1 sin marca: muchos EPUB no numeran el primer capítulo (y los libros
            # de un solo capítulo nunca lo hacen). Se asume al ver el versículo 1.
            if self.libro is None or self.ignorando or v != "1":
                return
            self._abrir_capitulo(1, explicito=False)
        self._cerrar_unidad()
        if self.implicito and self.explicitos == 0 and _numero(v) == 1:
            # Había texto antes del versículo 1: no era el 1 (la BJ pone ahí el final del
            # versículo anterior). Se etiqueta 0 para no repetir el 1.
            for u in self.cap.unidades:
                if u.versiculo == "1":
                    u.versiculo = "0"
        self.implicito = False
        self.verso = v
        self.explicitos += 1
        self.abierta = Unidad(v, "", max(self.pendiente, VERSICULO), True)
        self.abierta_numerada = True
        self.pendiente = NINGUNA

    def omitido(self, v: str) -> None:
        if self.cap is None:
            return
        self._cerrar_unidad()
        self.cap.omitidos.append(Omitido(v, len(self.cap.unidades)))

    def linea(self) -> None:
        if self.abierta is not None and self.abierta.texto.strip():
            self._cerrar_unidad()
            self.pendiente = max(self.pendiente, LINEA)

    def parrafo(self) -> None:
        if self.cap is None:
            return
        if self.abierta is not None and self.abierta.texto.strip():
            self._cerrar_unidad()
        if self.cap.unidades or self.abierta is not None:
            self.pendiente = max(self.pendiente, PARRAFO)

    def seccion(self, titulo: str) -> None:
        if self.cap is None:
            if self.libro is not None and not self.ignorando:
                self.secciones_pendientes.append(titulo)
            return
        self._cerrar_unidad()
        self.cap.secciones.append(Seccion(titulo, len(self.cap.unidades)))
        self.pendiente = max(self.pendiente, SECCION)

    def capitulo(self, n: int) -> None:
        self._soltar_secciones_finales()
        self._cerrar_capitulo()
        if self.ignorando:
            return
        if self.libro is None:
            self.fuera[self.titulo_actual] += 1
            self.secciones_pendientes = []
            return
        self._abrir_capitulo(n, explicito=True)

    def libro_titulo(self, valor: str) -> None:
        titulo = valor.split(_SEP_ALTERNATIVA, 1)[0]
        if any(self.sel.titulo_ignorado(t) for t in valor.split(_SEP_ALTERNATIVA)):
            self._cerrar_capitulo()
            self.libro, self.ignorando, self.titulo_actual = None, True, titulo
            self.res.registrar_titulo(TituloVisto(titulo, None, "ignorado", self.documento))
            return
        titulo, libro, modo = _detectar_titulo(valor, self.cfg.titulos)
        if modo == TITULO_SECCION:
            self.res.registrar_titulo(TituloVisto(titulo, self.libro.id if self.libro else None, modo, self.documento))
            self.seccion(titulo)
            return
        self._cerrar_capitulo()
        self.secciones_pendientes = []
        self.res.registrar_titulo(TituloVisto(titulo, libro.id if libro else None, modo, self.documento))
        self.libro, self.ignorando, self.titulo_actual = libro, False, titulo

    def nuevo_documento(self, href: str) -> None:
        self.documento = href

    def fin_documento(self) -> None:
        # Un capítulo puede seguir en el siguiente archivo del EPUB: no se cierra aquí,
        # pero la unidad abierta sí (un archivo nuevo siempre empieza un bloque nuevo).
        self._cerrar_unidad()
        if self.cap is not None and self.cap.unidades:
            self.pendiente = max(self.pendiente, PARRAFO)

    def fin(self) -> None:
        self._cerrar_capitulo()
        for titulo, n in self.fuera.items():
            self.res.avisos.append(
                f"{n} marca(s) de capítulo después del título «{titulo[:60]}», que no es de ningún libro. "
                "Si es un libro, añádelo en [epub.titulos]; si es una parte dentro de un libro, "
                'decláralo como "seccion".'
            )


def _solidez(cap: Capitulo) -> tuple[bool, int, float]:
    distintos = len(set(cap.versiculos))
    densidad = cap.caracteres / max(1, distintos)
    return (cap.explicito, distintos, -densidad)


def _siguiente_etiqueta(v: str) -> str | None:
    m = re.fullmatch(r"(\d+)([a-y]?)", v)
    if not m:
        return None
    n, letra = m.groups()
    return f"{n}{chr(ord(letra) + 1)}" if letra else str(int(n) + 1)


def compactar(etiquetas: list[str], maximo: int = 6) -> str:
    """['7', '8', '2', '3', '4'] → '7–8, 2–4' (en el orden en que aparecen)."""
    tramos: list[list[str]] = []
    for v in etiquetas:
        if tramos and _siguiente_etiqueta(tramos[-1][-1]) == v:
            tramos[-1].append(v)
        else:
            tramos.append([v])
    partes = [t[0] if len(t) == 1 else f"{t[0]}–{t[-1]}" for t in tramos]
    if len(partes) > maximo:
        partes = partes[: maximo - 1] + ["…", partes[-1]]
    return ", ".join(partes)


def _en_orden_numerados(cap: Capitulo) -> list[str]:
    """Versículos con número en el EPUB (no los asumidos al ver texto sin número), en orden."""
    return [u.versiculo for u in cap.unidades if u.inicia_versiculo and not u.implicita]


def _numerados(cap: Capitulo) -> set[str]:
    return set(_en_orden_numerados(cap))


def _es_fragmento(etiquetas: set[str], vistas: set[str]) -> bool:
    """Un trozo con versículos que aún no se vieron es parte del capítulo, no un duplicado.
    Se tolera alguna coincidencia (un versículo partido entre dos trozos) si trae más
    versículos nuevos que repetidos."""
    comunes = len(etiquetas & vistas)
    nuevos = len(etiquetas - vistas)
    return comunes == 0 or (comunes <= max(1, len(etiquetas) // 10) and nuevos > comunes)


def _unir_en(destino: Capitulo, otro: Capitulo) -> None:
    base = len(destino.unidades)
    previo = destino.unidades[-1].versiculo if destino.unidades else "1"
    iniciales = True
    for k, u in enumerate(otro.unidades):
        if iniciales and u.implicita:
            # Texto sin número al comienzo del trozo: sigue el versículo donde quedó el capítulo.
            u = replace(u, versiculo=previo, inicia_versiculo=False, implicita=False)
        else:
            iniciales = False
        destino.unidades.append(replace(u, ruptura=max(u.ruptura, PARRAFO)) if k == 0 else u)
    destino.secciones += [Seccion(s.titulo, s.antes_de + base) for s in otro.secciones]
    destino.omitidos += [Omitido(o.versiculo, o.antes_de + base) for o in otro.omitidos]
    destino.avisos += otro.avisos


_MIN_NUMERADOS_SIN_MARCA = 3  # un trozo sin marca de capítulo con menos es ruido de una introducción


def _combinar(grupo: list[Capitulo], avisos: list[str], notas: list[str]) -> Capitulo:
    orden = {id(c): i for i, c in enumerate(grupo)}
    hay_marca = any(c.explicito for c in grupo)
    # Sin marca de capítulo y con pocos versículos numerados: una llamada de nota numérica en
    # una introducción. Con varios (un capítulo 1 sin marca), participa como cualquier trozo.
    participan = [c for c in grupo if c.explicito or not hay_marca or c.numerados >= _MIN_NUMERADOS_SIN_MARCA]
    ruido = [c for c in grupo if not any(c is x for x in participan)]
    nucleo = max(participan, key=_solidez)
    vistas = _numerados(nucleo)
    documentos = {nucleo.origen}
    aceptados = [nucleo]
    repetidos: list[Capitulo] = []
    perdidos: list[tuple[Capitulo, set[str]]] = []
    for c in sorted(participan, key=lambda c: orden[id(c)]):
        if c is nucleo:
            continue
        etiquetas = _numerados(c)
        nuevos = etiquetas - vistas
        if not nuevos:
            repetidos.append(c)
            continue
        # Los traspuestos de la BJ están en el mismo archivo que el resto del capítulo; un
        # trozo de otro archivo solo se une si trae al menos dos versículos numerados.
        cercano = c.origen in documentos or c.numerados >= 2
        if cercano and _es_fragmento(etiquetas, vistas):
            aceptados.append(c)
            vistas |= etiquetas
            documentos.add(c.origen)
        else:
            perdidos.append((c, nuevos))
    aceptados.sort(key=lambda c: orden[id(c)])
    ref = f"{grupo[0].libro} {grupo[0].numero}"
    resultado = aceptados[0]
    if len(aceptados) > 1:
        primero = aceptados[0]
        resultado = Capitulo(
            primero.libro, primero.numero, list(primero.unidades), list(primero.secciones),
            list(primero.omitidos), origen=primero.origen, explicito=True, avisos=list(primero.avisos),
        )
        for c in aceptados[1:]:
            _unir_en(resultado, c)
        resultado.fragmentos = [_en_orden_numerados(c) for c in aceptados]
        notas.append(
            f"{ref} — {len(aceptados)} trozos con el mismo número de capítulo y versículos distintos "
            f"({' | '.join(compactar(f) for f in resultado.fragmentos)}): en la BJ hay versículos "
            "traspuestos aquí. Los uní en el orden del libro para que el capítulo quede completo."
        )
    def donde(c: Capitulo) -> str:
        return f"{c.origen.rsplit('/', 1)[-1]} ({len(set(c.versiculos))} vv.)"

    for c in ruido:
        notas.append(f"{ref} — descarto un trozo sin marca de capítulo en {donde(c)}: suele ser una llamada "
                      "de nota numérica en una introducción")
    for c in repetidos:
        notas.append(f"{ref} — descarto un duplicado en {donde(c)}: todos sus versículos ya están en el que se conserva")
    for c, nuevos in perdidos:
        vv = compactar(sorted(nuevos, key=_orden_natural))
        avisos.append(
            f"{ref} — ¡OJO! descarto un trozo en {donde(c)} que trae versículos que NO están en el capítulo "
            f"conservado (vv. {vv}): repite otros o viene de otro archivo. Si es texto bíblico, añádelo a "
            "mano en el .txt."
        )
    return resultado


_MIN_VERSOS_PROLOGO = 10
_RE_TITULO_PROLOGO = re.compile(r"pr[óo]logo|prefacio|proemio", re.IGNORECASE)


def _separar_prologo(grupo: list[Capitulo]) -> tuple[Capitulo | None, list[Capitulo]]:
    """Capítulo 1 sin marca seguido del capítulo 1 con marca: si el primero tiene versículos
    propios (1, 2, 3…), es un prólogo (Eclesiástico) y pasa a ser el capítulo 0."""
    if grupo[0].numero != 1:
        return None, grupo
    primero_explicito = next((i for i, c in enumerate(grupo) if c.explicito), None)
    if not primero_explicito:  # None (ninguno explícito) o 0 (el explícito va primero)
        return None, grupo
    capitulo_1 = grupo[primero_explicito]
    numerados_1 = _numerados(capitulo_1)
    if "1" not in numerados_1:  # el capítulo marcado no empieza: el trozo sin marca es su comienzo
        return None, grupo

    def es_prologo(c: Capitulo) -> bool:
        propios = _numerados(c)
        return (len(propios) >= _MIN_VERSOS_PROLOGO
                and "1" in propios  # numeración propia que empieza en 1, como la del capítulo
                and c.caracteres / max(1, c.numerados) <= 300  # versículos, no párrafos con notas
                # y titulado como tal: una introducción con llamadas de nota numeradas no lo está
                and any(_RE_TITULO_PROLOGO.search(t.titulo) for t in c.secciones))

    previos = [c for c in grupo[:primero_explicito] if es_prologo(c)]
    if not previos:
        return None, grupo
    prologo = replace(previos[0], numero=0, explicito=True, unidades=list(previos[0].unidades),
                      secciones=list(previos[0].secciones), omitidos=list(previos[0].omitidos))
    for c in previos[1:]:
        _unir_en(prologo, c)
    return prologo, [c for c in grupo if not any(c is x for x in previos)]


def _resolver_duplicados(capitulos: list[Capitulo], avisos: list[str],
                         notas: list[str]) -> list[Capitulo]:
    grupos: dict[tuple[str, int], list[Capitulo]] = {}
    for cap in capitulos:
        grupos.setdefault((cap.libro, cap.numero), []).append(cap)
    salida: list[Capitulo] = []
    for cap in capitulos:
        grupo = grupos[(cap.libro, cap.numero)]
        if len(grupo) == 1:
            salida.append(cap)
        elif cap is grupo[0]:
            prologo, resto = _separar_prologo(grupo)
            if prologo is not None:
                salida.append(prologo)
                notas.append(
                    f"{prologo.libro} 0 — texto con versículos propios antes del capítulo 1 "
                    f"({len(set(prologo.versiculos))} vv., en {prologo.origen.rsplit('/', 1)[-1]}): es un prólogo; "
                    "se guarda como capítulo 0 y se anuncia «Prólogo»"
                )
            salida.append(resto[0] if len(resto) == 1 else _combinar(resto, avisos, notas))
    return salida


def extraer(epub: Epub, cfg: ConfigEpub, solo_libro: str | None = None,
            documentos: list[str] | None = None) -> ResultadoExtraccion:
    """Extrae capítulos. `documentos` restringe el recorrido a esas rutas internas."""
    epub.exigir_sin_drm()
    sel = Selectores.desde(cfg)
    for clave, id_libro in cfg.titulos.items():
        if id_libro == TITULO_SECCION:
            continue
        try:
            obtener(id_libro)
        except KeyError as e:
            raise ConfigError(f"[epub.titulos] '{clave}' apunta a un libro inexistente: {e}") from None
    res = ResultadoExtraccion()
    ens = _Ensamblador(cfg, sel, res)
    permitidos = set(documentos) if documentos is not None else None
    for doc in epub.documentos():
        if permitidos is not None and doc.href not in permitidos:
            continue
        if any(p.search(doc.href) for p in sel.ignorar_documentos):
            continue
        res.documentos += 1
        ens.nuevo_documento(doc.href)
        soup: BeautifulSoup = parsear_xhtml(doc.contenido)
        cuerpo = soup.find("body") or soup
        limpiar_documento(cuerpo, sel)
        lista = list(eventos(cuerpo, sel))
        # Un documento sin libro, capítulo ni versículo (notas, apéndices, índices) no
        # aporta texto: si no, su contenido se pegaría al último versículo abierto.
        if not any(tipo in ("libro", "capitulo", "versiculo") for tipo, _ in lista):
            res.caracteres_ignorados += sum(len(v.strip()) for tipo, v in lista if tipo == "texto")
            continue
        for tipo, valor in lista:
            if tipo == "texto":
                ens.texto(valor)
            elif tipo == "versiculo":
                ens.versiculo(valor)
            elif tipo == "omitido":
                ens.omitido(valor)
            elif tipo == "linea":
                ens.linea()
            elif tipo == "parrafo":
                ens.parrafo()
            elif tipo == "seccion":
                ens.seccion(valor)
            elif tipo == "capitulo":
                ens.capitulo(int(valor))
            elif tipo == "libro":
                ens.libro_titulo(valor)
        ens.fin_documento()
    ens.fin()
    res.capitulos = _resolver_duplicados(res.capitulos, res.avisos, res.notas)
    if solo_libro:
        res.capitulos = [c for c in res.capitulos if c.libro == solo_libro]
        res.descartados = [d for d in res.descartados if d.startswith(f"{solo_libro} ")]
    for cap in res.capitulos:
        res.avisos.extend(cap.avisos)
        libro = POR_ID.get(cap.libro)
        if not cap.explicito and libro is not None and libro.capitulos > 1:
            res.avisos.append(f"{cap.libro} 1 — sin marca de capítulo en {cap.origen}: se asumió el capítulo 1")
    res.avisos.extend(diagnosticar(res.capitulos))
    res.notas.extend(observar(res.capitulos))
    res.notas.extend(notas_de(res.capitulos))
    return res


def _numero(v: str) -> int | None:
    m = re.match(r"(\d+)", v)
    return int(m.group(1)) if m else None


def _cubre(v: str) -> list[int]:
    """Números que cubre una etiqueta: '24-25' → [24, 25]; '12a' → [12]."""
    m = re.fullmatch(r"(\d+)[a-z]*(?:-(\d+)[a-z]*)?", v)
    if not m:
        return []
    a = int(m.group(1))
    b = int(m.group(2)) if m.group(2) else a
    return list(range(a, b + 1)) if a <= b <= a + 10 else [a]


def _orden_natural(v: str) -> tuple[int, str]:
    m = re.match(r"(\d+)(.*)", v)
    return (int(m.group(1)), m.group(2)) if m else (0, v)


def diagnosticar(capitulos: list[Capitulo]) -> list[str]:
    """Lo que hay que revisar ANTES de generar audio: algo se leería mal o faltaría
    (un número que se leería en voz alta, una nota colada, letras que la voz no sabe leer,
    capítulos de menos). Lo que no cambia lo que se oye va a observar()."""
    avisos: list[str] = []
    por_libro: dict[str, list[int]] = {}
    for cap in capitulos:
        ref = f"{cap.libro} {cap.numero}"
        por_libro.setdefault(cap.libro, []).append(cap.numero)
        for u in cap.unidades:
            if len(u.texto) > 1500:
                avisos.append(f"{ref}:{u.versiculo} — tramo de {len(u.texto)} caracteres: ¿se coló una nota o faltan números de versículo?")
            if (_RE_NUMERO_SOSPECHOSO.search(u.texto) or _RE_MARCA_SUELTA.fullmatch(u.texto)
                    or _RE_SOLO_NUMERO.fullmatch(u.texto)):
                avisos.append(f"{ref}:{u.versiculo} — número suelto: ¿número de versículo o capítulo sin detectar?")
            if _RE_NO_LATINO.search(u.texto):
                avisos.append(f"{ref}:{u.versiculo} — contiene letras griegas o hebreas: la voz no las leerá bien")
    for libro_id, caps in por_libro.items():
        esperados = POR_ID[libro_id].capitulos if libro_id in POR_ID else max(caps)
        presentes = set(caps)
        faltan = sorted(set(range(1, esperados + 1)) - presentes)
        sobran = sorted(n for n in presentes if n > esperados)
        if faltan:
            muestra = ", ".join(map(str, faltan[:12])) + ("…" if len(faltan) > 12 else "")
            avisos.append(f"{libro_id} — {len(presentes & set(range(1, esperados + 1)))} de {esperados} capítulos; faltan: {muestra}")
        if sobran:
            avisos.append(f"{libro_id} — capítulos fuera de rango (el libro tiene {esperados}): {', '.join(map(str, sobran[:10]))}")
    return avisos


def _largos_por_verso(cap: Capitulo) -> dict[str, int]:
    largos: dict[str, int] = {}
    actual: str | None = None
    for u in cap.unidades:
        if u.inicia_versiculo:
            actual = u.versiculo
        if actual is not None:
            largos[actual] = largos.get(actual, 0) + len(u.texto)
    return largos


def _tramos(numeros: list[int]) -> list[tuple[int, int]]:
    salida: list[tuple[int, int]] = []
    for n in numeros:
        if salida and salida[-1][1] == n - 1:
            salida[-1] = (salida[-1][0], n)
        else:
            salida.append((n, n))
    return salida


def _faltantes(cap: Capitulo, faltan: list[int]) -> list[str]:
    """Explica cada hueco de numeración. Si el EPUB solo perdió el número, el texto quedó
    pegado al versículo anterior, que mide varias veces lo normal: se lee igual. Si los
    vecinos tienen el largo de siempre, la edición no trae esos versículos."""
    ref = f"{cap.libro} {cap.numero}"
    largos = _largos_por_verso(cap)
    tipico = statistics.median(largos.values()) if largos else 0
    salida = []
    for a, b in _tramos(faltan):
        cuales = f"el versículo {a}" if a == b else f"los versículos {a}–{b}"
        previos = [v for v in largos if (_cubre(v) or [0])[-1] == a - 1]
        largo = largos[previos[-1]] if previos else 0
        proporcion = largo / tipico if tipico else 0.0
        k = b - a + 1
        # Si el texto quedó pegado, el anterior mide como él más los que faltan (≈ k + 1 veces).
        if previos and largo >= 150 and proporcion >= k + 1.0:
            numeros = f"falta el número del versículo {a}" if a == b else f"faltan los números de los versículos {a}–{b}"
            salida.append(
                f"{ref} — {numeros}, pero su texto parece estar al final del {previos[-1]} "
                f"(mide {proporcion:.1f} veces lo normal): se lee igual; solo falta en el índice de tiempos"
            )
        elif previos and proporcion >= 1.0 + 0.4 * k:
            salida.append(
                f"{ref} — falta {cuales}: o su texto está al final del {previos[-1]} (mide {proporcion:.1f} veces lo "
                "normal) o esta edición no lo trae. En los dos casos se lee lo que hay"
            )
        else:
            salida.append(f"{ref} — esta edición no trae {cuales} (sus vecinos tienen el largo normal): se lee lo que hay")
    return salida


def observar(capitulos: list[Capitulo]) -> list[str]:
    """Rarezas de numeración que no cambian lo que se oye: huecos, repeticiones y cambios de
    orden (en la BJ, casi siempre decisiones de la edición)."""
    notas: list[str] = []
    for cap in capitulos:
        ref = f"{cap.libro} {cap.numero}"
        cubiertos = {n for v in cap.versiculos for n in _cubre(v)}
        if not cubiertos:
            continue
        omitidos = {n for o in cap.omitidos for n in _cubre(o.versiculo)}
        faltan = sorted(set(range(1, max(cubiertos) + 1)) - cubiertos - omitidos)
        if faltan:
            notas.extend(_faltantes(cap, faltan))
        repetidos = sorted({v for v in cap.versiculos if cap.versiculos.count(v) > 1}, key=_orden_natural)
        if repetidos == ["1"] and _uno_inicial_corto(cap):
            repetidos = []  # aclamación inicial numerada aparte (notas_de lo menciona)
        if repetidos:
            notas.append(
                f"{ref} — versículos repetidos: {', '.join(repetidos[:8])}{'…' if len(repetidos) > 8 else ''} "
                "(la BJ numera dos veces ese pasaje): se lee en el orden del libro"
            )
        primeros = [n for n in (_numero(v) for v in cap.versiculos) if n is not None]
        retrocesos = sum(1 for a, b in zip(primeros, primeros[1:]) if b < a)
        if retrocesos and len(cap.fragmentos) < 2:
            notas.append(f"{ref} — {retrocesos} cambio(s) de orden: la BJ traspone versículos aquí; se lee en el orden del libro")
    return notas


# Un número de versículo sin detectar suele quedar al principio de una oración, delante de
# una mayúscula ("…dijo. 5 Entonces…"); una marca de capítulo sin detectar, sola ("Qo 2").
# Las cantidades del texto ("los hijos de Ará: 775;") no tienen esa forma.
_RE_NUMERO_SOSPECHOSO = re.compile(r"(?:^|[.!?…»”]\s+)\d{1,3}[a-z]?\s+[A-ZÁÉÍÓÚÑ¡¿«“—]")
_RE_MARCA_SUELTA = re.compile(r"(?:[1-3]\s*)?[A-ZÁÉÍÓÚ][a-záéíóú]{0,3}\.?\s+\d{1,3}")
_RE_SOLO_NUMERO = re.compile(r"\d{1,3}[a-z]?[.,;:]?")
_RE_CIFRA = re.compile(r"\d")


def _uno_inicial_corto(cap: Capitulo) -> bool:
    """El capítulo empieza con un «1» de una sola línea corta seguido de otro «1» (en los
    salmos de la BJ, la aclamación inicial lleva número propio)."""
    inicios = [i for i, u in enumerate(cap.unidades) if u.inicia_versiculo]
    if len(inicios) < 2 or cap.unidades[inicios[0]].versiculo != "1" or cap.unidades[inicios[1]].versiculo != "1":
        return False
    primero = cap.unidades[inicios[0]:inicios[1]]
    return sum(len(u.texto) for u in primero) <= 25


def notas_de(capitulos: list[Capitulo]) -> list[str]:
    """Hechos de la edición que conviene conocer pero no requieren revisión."""
    notas = []
    cifras: dict[str, list[str]] = {}
    for cap in capitulos:
        for u in cap.unidades:
            if _RE_CIFRA.search(u.texto):
                cifras.setdefault(cap.libro, []).append(f"{cap.numero}:{u.versiculo}")
    for libro_id, refs in cifras.items():
        notas.append(f"{libro_id} — {len(refs)} tramo(s) con cantidades en cifras (p. ej. {', '.join(refs[:3])}): "
                     "al leer se convierten a palabras")
    for cap in capitulos:
        if _uno_inicial_corto(cap) and cap.versiculos.count("1") == 2:
            notas.append(f"{cap.libro} {cap.numero} — empieza con una línea corta numerada «1» y luego el versículo 1: se leen en orden")
        if cap.omitidos:
            vv = ", ".join(o.versiculo for o in cap.omitidos)
            notas.append(f"{cap.libro} {cap.numero} — v. {vv} entre corchetes y sin texto en el EPUB (la BJ lo omite): no se lee")
    return notas


HUELLAS = ".huellas.json"  # en trabajo/texto/: qué escribió la extracción en cada .txt


def _huella(contenido: str) -> str:
    return hashlib.sha256(contenido.encode("utf-8")).hexdigest()[:16]


def guardar(res: ResultadoExtraccion, cfg: Config, forzar: bool = False) -> tuple[int, int, list[str]]:
    """Escribe los .txt. Reemplaza los que la extracción escribió y nadie tocó; uno editado
    a mano (o de origen desconocido, p. ej. de la 0.2) solo se pisa con forzar."""
    archivo_huellas = cfg.dir_texto / HUELLAS
    try:
        huellas: dict[str, str] = json.loads(archivo_huellas.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        huellas = {}
    nuevos = iguales = 0
    omitidos: list[str] = []
    for cap in res.capitulos:
        ruta = ruta_capitulo(cfg.dir_texto, cap.libro, cap.numero)
        clave = ruta.relative_to(cfg.dir_texto).as_posix()
        contenido = cap.a_texto()
        if ruta.exists():
            actual = ruta.read_text(encoding="utf-8")
            if actual == contenido:
                iguales += 1
                huellas[clave] = _huella(contenido)
                continue
            intacto = huellas.get(clave) == _huella(actual)
            if not (forzar or intacto):
                omitidos.append(str(ruta.relative_to(cfg.raiz)))
                continue
        escribir(cap, ruta)
        huellas[clave] = _huella(contenido)
        nuevos += 1
    if res.capitulos:
        escribir_atomico(archivo_huellas, json.dumps(huellas, indent=0, sort_keys=True) + "\n")
    return nuevos, iguales, omitidos


def resumen_por_libro(res: ResultadoExtraccion) -> list[tuple[str, int, int, int, int]]:
    """(id, capítulos encontrados, capítulos esperados, versículos, caracteres) en orden canónico."""
    por_libro: dict[str, list[Capitulo]] = {}
    for c in res.capitulos:
        por_libro.setdefault(c.libro, []).append(c)
    filas = []
    for libro_id in sorted(por_libro, key=lambda i: POR_ID[i].orden if i in POR_ID else 999):
        caps = por_libro[libro_id]
        esperados = POR_ID[libro_id].capitulos if libro_id in POR_ID else 0
        numerados = len({c.numero for c in caps if c.numero >= 1})
        filas.append((libro_id, numerados, esperados, sum(len(c.versiculos) for c in caps), sum(c.caracteres for c in caps)))
    return filas


def tiene_prologo(res: ResultadoExtraccion, libro_id: str) -> bool:
    return any(c.libro == libro_id and c.numero == 0 for c in res.capitulos)


def informe(res: ResultadoExtraccion, libro: str | None = None) -> str:
    lineas = [f"# Informe de extracción{f' (libro {libro})' if libro else ''}", ""]
    lineas.append(f"Documentos recorridos: {res.documentos}")
    for libro_id, caps, esperados, versos, chars in resumen_por_libro(res):
        marca = "" if caps == esperados else "  ←"
        extra = " + prólogo" if tiene_prologo(res, libro_id) else ""
        lineas.append(f"{libro_id:5} {caps:4}/{esperados:<4} capítulos  {versos:6} versículos  {chars:9} caracteres{extra}{marca}")
    lineas.append("")
    lineas.append(f"Caracteres fuera de capítulos (introducciones, índices, notas): {res.caracteres_ignorados}")
    dudosos = [t for t in res.titulos if t.modo in ("no reconocido", "sin ordinal → primer libro", TITULO_SECCION)]
    if dudosos:
        lineas += ["", "Títulos para revisar (añade o corrige en [epub.titulos] si hace falta):"]
        for t in dudosos[:60]:
            destino = t.libro or "—"
            lineas.append(f"  - «{t.texto[:70]}» → {destino} ({t.modo}) · {t.documento}")
    if res.descartados:
        lineas += ["", f"Capítulos descartados ({len(res.descartados)}):"]
        lineas += [f"  - {d}" for d in res.descartados[:40]]
    if res.avisos:
        lineas += ["", f"Revisar antes de generar el audio ({len(res.avisos)}):"]
        lineas += [f"  - {a}" for a in res.avisos]
    else:
        lineas += ["", "Nada que revisar antes de generar el audio."]
    if res.notas:
        lineas += ["", f"Para tu información, no requieren nada ({len(res.notas)}):"]
        lineas += [f"  - {n}" for n in res.notas]
    reconocidos = [t for t in res.titulos if t.libro and t.modo not in ("ignorado",)]
    if reconocidos:
        lineas += ["", "Mapa de títulos reconocidos:"]
        lineas += [f"  {t.libro:5} ← «{t.texto[:70]}» ({t.modo}) · {t.documento}" for t in reconocidos]
    return "\n".join(lineas) + "\n"


# --------------------------------------------------------------------- mapa del EPUB
@dataclass
class TituloDoc:
    texto: str
    libro: str | None
    modo: str


@dataclass
class InfoDocumento:
    indice: int
    href: str
    kb: int
    titulos: list[TituloDoc]


_RE_TAG_SIMPLE = re.compile(r"^[a-zA-Z][a-zA-Z0-9]*$")


def titulos_de(contenido: bytes, cfg: ConfigEpub, sel: Selectores) -> list[str]:
    """Títulos de libro de un documento (cada uno con su variante con espacios, ver
    _con_alternativa). Atajo con regex si el selector es una etiqueta simple (h1); si no, se
    parsea el documento."""
    selector = cfg.titulo_libro.strip()
    if _RE_TAG_SIMPLE.match(selector):
        texto = decodificar(contenido)
        salida = []
        for m in re.finditer(rf"<{selector}\b[^>]*>(.*?)</{selector}\s*>", texto, re.S | re.I):
            interior = re.sub(r"<br\b[^>]*>", " ", m.group(1), flags=re.I)
            variantes = []
            for sep in ("", " "):
                v = html.unescape(re.sub(r"<[^>]+>", sep, interior)).translate(_INVISIBLES)
                variantes.append(_limpiar(v))
            if variantes[0]:
                salida.append(_con_alternativa(*variantes))
        return salida
    if sel.libro is None:
        return []
    soup = parsear_xhtml(contenido)
    cuerpo = soup.find("body") or soup
    return [_con_alternativa(texto_titulo(x), texto_de(x)) for x in sel.libro.select(cuerpo) if texto_titulo(x)]


def mapa_documentos(epub: Epub, cfg: ConfigEpub) -> list[InfoDocumento]:
    sel = Selectores.desde(cfg)
    mapa = []
    for i, doc in enumerate(epub.documentos()):
        titulos = []
        for valor in titulos_de(doc.contenido, cfg, sel):
            if any(sel.titulo_ignorado(t) for t in valor.split(_SEP_ALTERNATIVA)):
                titulos.append(TituloDoc(valor.split(_SEP_ALTERNATIVA, 1)[0], None, "ignorado"))
                continue
            texto, libro, modo = _detectar_titulo(valor, cfg.titulos)
            titulos.append(TituloDoc(texto, libro.id if libro else None, modo))
        mapa.append(InfoDocumento(i, doc.href, len(doc.contenido) // 1024, titulos))
    return mapa


def documentos_de_libro(mapa: list[InfoDocumento], libro_id: str) -> list[str]:
    """Documentos que pertenecen a un libro: los que llevan su título y los que siguen sin
    título (continuaciones), hasta el próximo título de otra cosa."""
    hrefs: list[str] = []
    activo = False
    for d in mapa:
        propios = [t for t in d.titulos if t.modo != TITULO_SECCION]
        if propios:
            if any(t.libro == libro_id for t in propios):
                hrefs.append(d.href)
            activo = propios[-1].libro == libro_id
        elif activo:
            hrefs.append(d.href)
    return hrefs


def extraer_a_disco(cfg: Config, ruta_epub: Path | None = None, solo_libro: str | None = None,
                    forzar: bool = False) -> tuple[ResultadoExtraccion, tuple[int, int, list[str]]]:
    with Epub(ruta_epub or cfg.ruta_epub()) as epub:
        epub.exigir_sin_drm()
        documentos = None
        if solo_libro:
            documentos = documentos_de_libro(mapa_documentos(epub, cfg.epub), solo_libro) or None
        res = extraer(epub, cfg.epub, solo_libro, documentos)
    resumen = guardar(res, cfg, forzar)
    escribir_atomico(cfg.dir_trabajo / "extraccion.txt", informe(res, solo_libro))
    return res, resumen
