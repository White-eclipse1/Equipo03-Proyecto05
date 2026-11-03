"""Paquete de evidencia de calidad y recursos (VAL-08, #24): `evidencias/VAL-08/`.

Comprueba que el paquete versionado se recalcula solo con sus archivos, que detecta
alteraciones y que sigue sincronizado con la evidencia de VAL-01 a VAL-07 de la que sale.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PROYECTO4 = Path(__file__).resolve().parents[1]
PAQUETE = PROYECTO4 / "evidencias" / "VAL-08"
sys.path.insert(0, str(PROYECTO4 / "validacion"))
_spec = importlib.util.spec_from_file_location(
    "paquete_val08", PROYECTO4 / "validacion" / "paquete_val08.py"
)
paq = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = paq
_spec.loader.exec_module(paq)

pytestmark = pytest.mark.skipif(not PAQUETE.is_dir(), reason="sin paquete generado")


def recalcular(carpeta: Path) -> subprocess.CompletedProcess:
    """Como lo correra el evaluador: Python aislado (-I), desde una copia del paquete."""
    return subprocess.run(
        [sys.executable, "-I", "recalcular.py"],
        cwd=carpeta,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


@pytest.fixture
def copia(tmp_path: Path) -> Path:
    destino = tmp_path / "VAL-08"
    shutil.copytree(PAQUETE, destino)
    return destino


def test_el_paquete_se_recalcula_solo_con_sus_archivos(copia):
    resultado = recalcular(copia)
    assert resultado.returncode == 0, resultado.stdout + resultado.stderr
    assert "VERIFICADO" in resultado.stdout and "FALLA" not in resultado.stdout


def test_detecta_una_prediccion_alterada(copia):
    ruta = copia / "validacion" / "predicciones_val.csv"
    lineas = ruta.read_text("utf-8").splitlines()
    campos = lineas[1].split(",")
    campos[3] = "dog" if campos[3] != "dog" else "cat"  # optimized_prediction
    lineas[1] = ",".join(campos)
    ruta.write_text("\n".join(lineas) + "\n", encoding="utf-8")
    resultado = recalcular(copia)
    assert resultado.returncode == 1
    assert "[FALLA] integridad" in resultado.stdout
    assert "[FALLA] validacion.predicciones" in resultado.stdout


def test_detecta_tiempos_alterados_aunque_se_rehaga_el_sha256sums(copia):
    """Sin la integridad, el recalculo desde los datos crudos tambien lo detecta."""
    ruta = copia / "benchmark" / "tiempos.csv"
    ruta.write_text(ruta.read_text("utf-8").replace(",True,", ",False,", 30), encoding="utf-8")
    sumas = (copia / "SHA256SUMS.txt").read_text("utf-8").splitlines()
    nuevas = []
    for linea in sumas:
        digest, nombre = linea.split("  ", 1)
        if nombre == "benchmark/tiempos.csv":
            digest = hashlib.sha256(ruta.read_bytes()).hexdigest()
        nuevas.append(f"{digest}  {nombre}")
    (copia / "SHA256SUMS.txt").write_text("\n".join(nuevas) + "\n", encoding="utf-8")
    resultado = recalcular(copia)
    assert resultado.returncode == 1
    assert "[FALLA] benchmark.crudo" in resultado.stdout


def test_el_paquete_esta_sincronizado_con_la_evidencia_de_origen():
    for nombre, origen in paq.COPIAS.items():
        assert (PAQUETE / nombre).read_bytes() == origen.read_bytes(), nombre
    ficha = json.loads((PAQUETE / "modelo" / "ficha_modelos.json").read_text("utf-8"))
    assert ficha == paq.ficha_modelos()
    readme = paq.readme(
        ficha,
        paq.leer_json(paq.RES / "metricas_val.json"),
        paq.leer_json(paq.RES / "recursos_edge.json"),
        paq.leer_json(paq.RAIZ / "evidencias/VAL-05/benchmark.json"),
        paq.leer_json(paq.RES / "contraste_edge.json"),
    )
    assert (PAQUETE / "README.md").read_text("utf-8") == readme


def test_cubre_los_criterios_de_aceptacion():
    ficha = json.loads((PAQUETE / "modelo" / "ficha_modelos.json").read_text("utf-8"))
    metricas = json.loads((PAQUETE / "validacion" / "metricas_val.json").read_text("utf-8"))
    recursos = json.loads((PAQUETE / "benchmark" / "recursos_edge.json").read_text("utf-8"))
    for modelo in ("original", "optimizado"):
        assert {"version", "archivo", "sha256", "bytes", "s3", "version_id"} <= set(ficha[modelo])
    assert ficha["original"]["run_id"].startswith("9f9b62c2")
    for modelo in ("original", "optimized"):
        m = metricas["modelos"][modelo]
        assert {"accuracy", "f1_macro"} <= set(m)
        assert all({"f1", "support"} <= set(m["por_clase"][c]) for c in ("cat", "dog", "person"))
    assert metricas["caida_accuracy"]["pp_fraccion"] == "25/73"
    for modelo in ("fp32", "int8"):
        assert {"p50", "p95"} <= set(recursos["latencia_edge"][modelo]["ms_total"])
        assert recursos["latencia_edge"][modelo]["calentamientos_excluidos"] >= 10
        assert recursos["latencia_edge"][modelo]["mediciones_validas"] >= 100
    assert "Intercambio entre recursos y calidad" in (PAQUETE / "README.md").read_text("utf-8")
