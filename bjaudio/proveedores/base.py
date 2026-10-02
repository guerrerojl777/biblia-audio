"""Interfaz común de motores de voz y utilidades HTTP con reintentos."""

from __future__ import annotations

import json
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass

import httpx

from ..errores import ErrorProveedor
from ..lexico import Lexico

TIMEOUT = httpx.Timeout(120.0, connect=15.0)
_REINTENTABLES = {429, 500, 502, 503, 504}


@dataclass
class Contexto:
    """Información que algunos motores usan para dar continuidad entre trozos."""

    texto_anterior: str | None = None
    texto_siguiente: str | None = None
    variante: int = 0  # en reintentos, cambia la semilla de los motores estocásticos


@dataclass
class Audio:
    wav: bytes  # WAV PCM16 mono
    caracteres: int  # lo que factura el proveedor (si lo informa) o len(texto)
    id_peticion: str | None = None


class ProveedorTTS(ABC):
    nombre: str = ""
    max_chars: int = 2000
    estocastico: bool = False  # True si repetir la petición puede dar un audio distinto
    sample_rate: int = 24000

    @abstractmethod
    def firma(self) -> dict:
        """Parámetros que cambian el audio. Forman parte de la clave de caché."""

    def listo(self) -> None:
        """Lanza ConfigError si falta algo (clave, voz…) para poder sintetizar."""

    def preparar_texto(self, texto: str, lexico: Lexico) -> str:
        """Por defecto: el motor no entiende IPA, así que usa la reescritura si existe."""
        return lexico.reescribir_sin_ipa(texto)

    @abstractmethod
    def sintetizar(self, texto: str, contexto: Contexto) -> Audio:
        ...

    def costo_usd(self, caracteres: int) -> float:
        return 0.0

    def comprobar_cuota(self, caracteres: int) -> None:
        """Lanza PresupuestoExcedido si el proveedor no tiene cuota para `caracteres`."""

    def cerrar(self) -> None:
        pass


def _detalle_error(r: httpx.Response) -> str:
    try:
        datos = r.json()
    except (json.JSONDecodeError, ValueError):
        return r.text[:300]
    if isinstance(datos, dict):
        for clave in ("err_msg", "message", "detail", "error"):
            if clave in datos:
                valor = datos[clave]
                return json.dumps(valor, ensure_ascii=False)[:300] if not isinstance(valor, str) else valor[:300]
    return json.dumps(datos, ensure_ascii=False)[:300]


def peticion(cliente: httpx.Client, metodo: str, url: str, *, servicio: str, intentos: int = 4,
             espera_inicial: float = 1.5, **kwargs) -> httpx.Response:
    """HTTP con reintentos exponenciales para 429/5xx y fallos de red.

    Los 4xx restantes (clave inválida, texto rechazado…) no se reintentan: reintentar
    no los arregla y gastaría tiempo. Se convierten en ErrorProveedor con el detalle.
    """
    espera = espera_inicial
    ultimo: Exception | None = None
    for intento in range(1, intentos + 1):
        try:
            r = cliente.request(metodo, url, **kwargs)
        except httpx.TransportError as e:
            ultimo = e
        else:
            if r.status_code < 400:
                return r
            if r.status_code not in _REINTENTABLES:
                if r.status_code in (401, 403):
                    raise ErrorProveedor(
                        f"{servicio}: acceso denegado ({r.status_code}). Revisa la clave en .env "
                        f"y sus permisos. Detalle: {_detalle_error(r)}"
                    )
                raise ErrorProveedor(f"{servicio}: error {r.status_code}: {_detalle_error(r)}")
            ultimo = ErrorProveedor(f"{servicio}: error {r.status_code}: {_detalle_error(r)}")
            retry_after = r.headers.get("retry-after")
            if retry_after and retry_after.isdigit():
                espera = max(espera, float(retry_after))
        if intento < intentos:
            time.sleep(espera)
            espera *= 2
    raise ErrorProveedor(f"{servicio}: falló tras {intentos} intentos: {ultimo}")
