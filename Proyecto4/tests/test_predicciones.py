"""Archivo formal de predicciones por muestra (VAL-03, #13).

`validacion/predicciones_formales.py` lo genera y `validacion/verificar_predicciones.py`
(solo biblioteca estandar) lo verifica contra el manifiesto. Las pruebas usan un
manifiesto sintetico y, al final, la evidencia real versionada.
"""

from __future__ import annotations

import copy
import csv
import hashlib
import importlib.util
import io
import json
import sys
from pathlib import Path

import pytest

VALIDACION = Path(__file__).resolve().parents[1] / "validacion"


def cargar(nombre: str):
    spec = importlib.util.spec_from_file_location(nombre, VALIDACION / f"{nombre}.py")
    modulo = importlib.util.module_from_spec(spec)
    sys.modules[nombre] = modulo
    spec.loader.exec_module(modulo)
    return modulo


ver = cargar("verificar_predicciones")
sys.path.insert(0, str(VALIDACION))
formal = cargar("predicciones_formales")

CLASES = ["cat", "dog", "person"]
MANIFIESTO_ID = "m-prueba"


def linea(cid: str, clase: str, split: str) -> str:
    fila = {
        "category_name": clase,
        "class_index": CLASES.index(clase),
        "crop_id": cid,
        "split": split,
    }
    return json.dumps(fila, separators=(",", ":"))


LINEAS = [
    linea("0.1.3:a1", "cat", "train"),
    linea("0.1.3:a2", "dog", "val"),
    linea("0.1.3:a3", "person", "test"),
    linea("0.1.3:a4", "cat", "val"),
    linea("0.1.3:a5", "person", "val"),
]
MANIFIESTO = ("\n".join(LINEAS) + "\n").encode()
EXTRACTO = ("\n".join(x for x in LINEAS if '"val"' in x) + "\n").encode()
META = {
    "manifest_id": MANIFIESTO_ID,
    "manifest_hash": hashlib.sha256(MANIFIESTO).hexdigest(),
    "classes": [{"class_index": i, "category_name": c} for i, c in enumerate(CLASES)],
    "counts": {"crops": {"val": {"cat": 1, "dog": 1, "person": 1}}},
}


def comparacion(int8: dict[str, str] | None = None) -> list[dict[str, str]]:
    """Filas con el formato de comparar_modelos.py (VAL-02)."""
    int8 = int8 or {}
    filas = []
    for cid, clase in (("0.1.3:a2", "dog"), ("0.1.3:a4", "cat"), ("0.1.3:a5", "person")):
        fila = {"sample_id": cid, "true_class": clase, "original_prediction": clase}
        fila["int8_prediction"] = int8.get(cid, clase)
        for c in CLASES:
            fila[f"prob_original_{c}"] = "0.9" if c == clase else "0.05"
            fila[f"prob_int8_{c}"] = "0.8" if c == fila["int8_prediction"] else "0.1"
        filas.append(fila)
    return filas


def generar(int8: dict[str, str] | None = None) -> tuple[bytes, dict]:
    manifiesto_val = {
        json.loads(x)["crop_id"]: {**json.loads(x), "manifest_id": MANIFIESTO_ID}
        for x in ver.lineas_val(MANIFIESTO)
    }
    filas = formal.construir(comparacion(int8), manifiesto_val, CLASES)
    datos = formal.csv_bytes(filas)
    metadatos = {
        "archivo": {"sha256": hashlib.sha256(datos).hexdigest()},
        "clases": CLASES,
        "manifiesto": {
            "manifest_id": MANIFIESTO_ID,
            "sha256": hashlib.sha256(MANIFIESTO).hexdigest(),
            "extracto_val": {"sha256": hashlib.sha256(EXTRACTO).hexdigest()},
        },
        "exclusiones": [],
        "resumen": ver.resumir(list(csv.DictReader(io.StringIO(datos.decode())))),
    }
    return datos, metadatos


def fallidas(informe: dict) -> set[str]:
    return {c["id"] for c in informe["comprobaciones"] if not c["ok"]}


def re_firmar(datos: bytes, metadatos: dict) -> dict:
    """Metadatos coherentes con un CSV alterado: aisla la comprobacion que interesa."""
    nuevos = copy.deepcopy(metadatos)
    nuevos["archivo"]["sha256"] = hashlib.sha256(datos).hexdigest()
    nuevos["resumen"] = ver.resumir(list(csv.DictReader(io.StringIO(datos.decode()))))
    return nuevos


def test_archivo_formal_valido_con_extracto_y_con_manifiesto_completo():
    datos, metadatos = generar({"0.1.3:a4": "dog"})
    con_extracto = ver.verificar(datos, metadatos, EXTRACTO, META)
    assert con_extracto["ok"], fallidas(con_extracto)
    assert con_extracto["manifiesto_usado"] == "extracto val versionado"

    completo = ver.verificar(datos, metadatos, MANIFIESTO, META, EXTRACTO)
    assert completo["ok"], fallidas(completo)
    assert "manifiesto.extracto" in {c["id"] for c in completo["comprobaciones"]}

    filas = list(csv.DictReader(io.StringIO(datos.decode())))
    assert [f["optimized_prediction"] for f in filas] == ["dog", "dog", "person"]
    assert {f["manifest_id"] for f in filas} == {MANIFIESTO_ID}
    assert metadatos["resumen"]["aciertos_optimizado"] == 2


def test_detecta_id_duplicado():
    datos, metadatos = generar()
    lineas = datos.decode().splitlines()
    datos = ("\n".join([*lineas, lineas[1]]) + "\n").encode()
    assert "ids.duplicados" in fallidas(
        ver.verificar(datos, re_firmar(datos, metadatos), EXTRACTO, META)
    )


def test_faltante_sin_justificar_falla_y_documentado_pasa():
    datos, metadatos = generar()
    lineas = [x for x in datos.decode().splitlines() if not x.startswith("0.1.3:a4,")]
    datos = ("\n".join(lineas) + "\n").encode()
    metadatos = re_firmar(datos, metadatos)
    assert "ids.union_con_manifiesto" in fallidas(ver.verificar(datos, metadatos, EXTRACTO, META))

    con_motivo = {**metadatos, "exclusiones": [{"sample_id": "0.1.3:a4", "motivo": "ilegible"}]}
    meta = copy.deepcopy(META)
    informe = ver.verificar(datos, con_motivo, EXTRACTO, meta)
    assert informe["ok"], fallidas(informe)

    sin_motivo = {**metadatos, "exclusiones": [{"sample_id": "0.1.3:a4", "motivo": ""}]}
    assert "ids.union_con_manifiesto" in fallidas(ver.verificar(datos, sin_motivo, EXTRACTO, META))


def test_detecta_etiqueta_distinta_al_manifiesto():
    datos, metadatos = generar()
    datos = datos.replace(b"0.1.3:a2,dog,", b"0.1.3:a2,cat,")
    informe = ver.verificar(datos, re_firmar(datos, metadatos), EXTRACTO, META)
    assert {"etiquetas", "clases"} <= fallidas(informe)


def test_detecta_prediccion_fuera_de_las_clases():
    datos, metadatos = generar({"0.1.3:a5": "car"})
    assert "clases" in fallidas(ver.verificar(datos, metadatos, EXTRACTO, META))


def test_detecta_resumen_o_csv_que_no_cuadran():
    datos, metadatos = generar()
    inflado = copy.deepcopy(metadatos)
    inflado["resumen"]["aciertos_optimizado"] += 1
    assert "resumen.recalculado" in fallidas(ver.verificar(datos, inflado, EXTRACTO, META))

    otro = datos.replace(b"0.9,", b"0.91,", 1)
    assert "csv.sha256" in fallidas(ver.verificar(otro, metadatos, EXTRACTO, META))


def test_detecta_manifiesto_ajeno_o_extracto_que_no_es_su_val():
    datos, metadatos = generar()
    ajeno = MANIFIESTO + b'{"category_name":"cat","class_index":0,"crop_id":"x","split":"train"}\n'
    assert "manifiesto.vinculo" in fallidas(ver.verificar(datos, metadatos, ajeno, META))

    extracto_malo = EXTRACTO.replace(b"0.1.3:a2", b"0.1.3:a9")
    informe = ver.verificar(datos, metadatos, MANIFIESTO, META, extracto_malo)
    assert "manifiesto.extracto" in fallidas(informe)


def test_formato_sin_columnas_requeridas():
    _, metadatos = generar()
    informe = ver.verificar(b"sample_id,true_class\n0.1.3:a2,dog\n", metadatos, EXTRACTO, META)
    assert not informe["ok"] and fallidas(informe) == {"formato"}


@pytest.mark.skipif(not ver.PREDICCIONES.is_file(), reason="sin evidencia generada")
def test_la_evidencia_versionada_se_verifica_sin_datos_del_p3():
    """Lo mismo que correra el evaluador: CSV, extracto y meta versionados."""
    metadatos = json.loads(ver.PREDICCIONES.with_suffix(".json").read_text("utf-8"))
    informe = ver.verificar(
        ver.PREDICCIONES.read_bytes(),
        metadatos,
        ver.EXTRACTO.read_bytes(),
        json.loads(ver.META.read_text("utf-8")),
    )
    assert informe["ok"], fallidas(informe)
    assert metadatos["resumen"]["muestras"] == 292
    assert metadatos["manifiesto"]["sha256"].startswith("45600f29")
