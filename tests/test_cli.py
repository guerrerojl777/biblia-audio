from __future__ import annotations

from typer.testing import CliRunner

from bjaudio.cli import app

runner = CliRunner()


def _invocar(proyecto, *args):
    resultado = runner.invoke(app, ["--config", str(proyecto.raiz / "config.toml"), *args])
    assert resultado.exit_code == 0, resultado.output
    return resultado.output


def test_flujo_completo_por_cli(proyecto):
    salida = _invocar(proyecto, "inspeccionar")
    assert "solo un número" in salida and "sup.v" in salida and "inspeccionar --libro" in salida
    assert (proyecto.dir_trabajo / "inspeccion.txt").exists()

    salida = _invocar(proyecto, "extraer")
    assert (proyecto.dir_texto / "gn" / "001.txt").exists()

    salida = _invocar(proyecto, "plan", "gn", "1")
    assert "trozos" in salida

    salida = _invocar(proyecto, "correr", "gn", "1-2", "--simular")
    assert "≈" in salida and not (proyecto.dir_salida).exists()

    salida = _invocar(proyecto, "correr", "gn", "1-3")
    assert "gn 3: no hay texto" in salida
    assert (proyecto.dir_salida / "simulado" / "01-gn" / "gn-002.mp3").exists()

    salida = _invocar(proyecto, "estado")
    assert "gn · Génesis" in salida


def test_voces_deepgram(proyecto):
    salida = _invocar(proyecto, "voces", "--proveedor", "deepgram")
    assert "aura-2-javier-es" in salida


def test_error_claro_si_falta_la_clave(proyecto, monkeypatch):
    monkeypatch.delenv("DEEPGRAM_API_KEY", raising=False)
    _invocar(proyecto, "extraer")
    resultado = runner.invoke(app, ["--config", str(proyecto.raiz / "config.toml"), "correr", "gn", "1",
                                    "--proveedor", "deepgram"])
    assert resultado.exit_code == 1
    assert "DEEPGRAM_API_KEY" in resultado.output
