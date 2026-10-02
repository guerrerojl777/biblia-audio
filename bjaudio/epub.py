"""Lectura de EPUB sin dependencias exóticas: ZIP + OPF + spine.

Dos responsabilidades:
1. Diagnosticar DRM. Si el contenido está cifrado (Adobe ADEPT, Readium LCP u otro),
   el pipeline se detiene: no procesa archivos protegidos ni intenta desprotegerlos.
   La ofuscación de fuentes (IDPF/Adobe) NO es DRM del texto y se acepta.
2. Entregar los documentos XHTML en el orden de lectura (spine).
"""

from __future__ import annotations

import html.entities
import posixpath
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote

from bs4 import BeautifulSoup
from lxml import etree

from .errores import BjaError, EpubProtegidoError

# Algoritmos de ofuscación de fuentes: no cifran texto.
_ALGORITMOS_FUENTES = {
    "http://www.idpf.org/2008/embedding",
    "http://ns.adobe.com/pdf/enc#RC",
}
_EXT_FUENTES = (".ttf", ".otf", ".woff", ".woff2")
_TIPOS_DOCUMENTO = {"application/xhtml+xml", "text/html", "application/x-dtbook+xml"}
_PARSER_SEGURO = etree.XMLParser(resolve_entities=False, no_network=True, recover=True)


@dataclass(frozen=True)
class DiagnosticoDrm:
    protegido: bool
    motivo: str
    fuentes_ofuscadas: int = 0


@dataclass(frozen=True)
class DocumentoEpub:
    href: str  # ruta dentro del ZIP
    tipo: str
    contenido: bytes


def _xml(datos: bytes) -> etree._Element:
    return etree.fromstring(datos, parser=_PARSER_SEGURO)


def diagnosticar_drm(zf: zipfile.ZipFile) -> DiagnosticoDrm:
    nombres = set(zf.namelist())
    if "META-INF/rights.xml" in nombres:
        return DiagnosticoDrm(True, "contiene META-INF/rights.xml (DRM de Adobe ADEPT)")
    if "META-INF/license.lcpl" in nombres:
        return DiagnosticoDrm(True, "contiene META-INF/license.lcpl (DRM Readium LCP)")
    if "META-INF/encryption.xml" not in nombres:
        return DiagnosticoDrm(False, "sin DRM")
    raiz = _xml(zf.read("META-INF/encryption.xml"))
    fuentes = 0
    for dato in raiz.xpath("//*[local-name()='EncryptedData']"):
        metodo = dato.xpath(".//*[local-name()='EncryptionMethod']/@Algorithm")
        uri = dato.xpath(".//*[local-name()='CipherReference']/@URI")
        algoritmo = metodo[0] if metodo else ""
        recurso = unquote(uri[0]) if uri else ""
        if algoritmo in _ALGORITMOS_FUENTES and recurso.lower().endswith(_EXT_FUENTES):
            fuentes += 1
            continue
        return DiagnosticoDrm(True, f"META-INF/encryption.xml cifra '{recurso or '?'}' con {algoritmo or 'algoritmo desconocido'}")
    return DiagnosticoDrm(False, "sin DRM (solo fuentes ofuscadas)" if fuentes else "sin DRM", fuentes)


class Epub:
    """EPUB abierto en modo lectura. Úsalo con `with Epub(ruta) as e:`."""

    def __init__(self, ruta: Path):
        self.ruta = Path(ruta)
        if not self.ruta.exists():
            raise BjaError(f"No encuentro el EPUB: {self.ruta}. Revisa [epub] archivo en config.toml.")
        try:
            self._zip = zipfile.ZipFile(self.ruta)
        except zipfile.BadZipFile:
            raise BjaError(f"{self.ruta.name} no es un EPUB válido (no es un archivo ZIP).") from None
        self.drm = diagnosticar_drm(self._zip)
        self._nombres = {n.lower(): n for n in self._zip.namelist()}
        self.opf, self.manifiesto, self.spine = self._leer_opf()

    def __enter__(self) -> Epub:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.cerrar()

    def cerrar(self) -> None:
        self._zip.close()

    def exigir_sin_drm(self) -> None:
        if self.drm.protegido:
            raise EpubProtegidoError(
                f"Este EPUB tiene DRM: {self.drm.motivo}.\n"
                "El pipeline no procesa archivos protegidos ni intenta desprotegerlos.\n"
                "Opciones: escucharlo con la lectura en voz alta de tu app de lectura, "
                "pedir permiso a la editorial, o usar una edición sin DRM."
            )

    def leer(self, href: str) -> bytes:
        nombre = href if href in self._zip.namelist() else self._nombres.get(href.lower())
        if nombre is None:
            raise BjaError(f"El EPUB declara '{href}' pero el archivo no está dentro del ZIP.")
        return self._zip.read(nombre)

    def _leer_opf(self) -> tuple[str, dict[str, tuple[str, str]], list[str]]:
        try:
            contenedor = _xml(self.leer("META-INF/container.xml"))
        except BjaError:
            raise BjaError("EPUB sin META-INF/container.xml: el archivo está dañado o no es EPUB.") from None
        rutas = contenedor.xpath("//*[local-name()='rootfile']/@full-path")
        if not rutas:
            raise BjaError("container.xml no indica el archivo OPF.")
        opf = rutas[0]
        base = posixpath.dirname(opf)
        paquete = _xml(self.leer(opf))
        manifiesto: dict[str, tuple[str, str]] = {}
        for item in paquete.xpath("//*[local-name()='manifest']/*[local-name()='item']"):
            href = posixpath.normpath(posixpath.join(base, unquote(item.get("href", ""))))
            manifiesto[item.get("id", "")] = (href, item.get("media-type", ""))
        spine = [i for i in paquete.xpath("//*[local-name()='spine']/*[local-name()='itemref']/@idref")]
        return opf, manifiesto, spine

    def hojas_de_estilo(self) -> list[str]:
        """Texto de las hojas CSS del EPUB (para saber qué clases separan párrafos)."""
        hojas = []
        for href, tipo in self.manifiesto.values():
            if tipo == "text/css" or href.lower().endswith(".css"):
                try:
                    hojas.append(decodificar(self.leer(href)))
                except BjaError:
                    continue
        return hojas

    def documentos(self) -> list[DocumentoEpub]:
        """Documentos de contenido en orden de lectura."""
        docs: list[DocumentoEpub] = []
        for idref in self.spine:
            if idref not in self.manifiesto:
                continue
            href, tipo = self.manifiesto[idref]
            if tipo in _TIPOS_DOCUMENTO or href.lower().endswith((".xhtml", ".html", ".htm")):
                docs.append(DocumentoEpub(href, tipo, self.leer(href)))
        return docs


_RE_ENTIDAD = re.compile(r"&([A-Za-z][A-Za-z0-9]*);")
_ENTIDADES_XML = {"amp", "lt", "gt", "quot", "apos"}


def _entidades_html_a_numericas(texto: str) -> str:
    """&nbsp; y compañía no existen en XML puro: se pasan a &#160; para no perder texto."""

    def cambiar(m: re.Match[str]) -> str:
        nombre = m.group(1)
        if nombre in _ENTIDADES_XML:
            return m.group(0)
        codigo = html.entities.name2codepoint.get(nombre)
        return f"&#{codigo};" if codigo else m.group(0)

    return _RE_ENTIDAD.sub(cambiar, texto)


_RE_DECLARACION = re.compile(rb"""encoding\s*=\s*["']([A-Za-z0-9._-]+)["']""")


def decodificar(contenido: bytes) -> str:
    if contenido.startswith(b"\xef\xbb\xbf"):
        return contenido[3:].decode("utf-8", errors="replace")
    if contenido.startswith((b"\xff\xfe", b"\xfe\xff")):
        return contenido.decode("utf-16", errors="replace")
    m = _RE_DECLARACION.search(contenido[:200])
    codec = m.group(1).decode("ascii") if m else "utf-8"
    try:
        return contenido.decode(codec)
    except (LookupError, UnicodeDecodeError):
        return contenido.decode("utf-8", errors="replace")


def parsear_xhtml(contenido: bytes) -> BeautifulSoup:
    """XHTML se parsea como XML a propósito.

    Con un parser HTML, un ancla vacía `<a id="v1"/>` se convierte en una etiqueta
    abierta que se traga el texto siguiente; si luego se eliminan anclas, se pierde texto.
    El parser XML (con recover) respeta las etiquetas autocerradas.
    """
    texto = _entidades_html_a_numericas(decodificar(contenido))
    # Ya es texto Unicode: la declaración <?xml encoding=…?> sobra y puede confundir al parser.
    texto = re.sub(r"^\s*<\?xml[^>]*\?>", "", texto, count=1)
    return BeautifulSoup(texto, "xml")
