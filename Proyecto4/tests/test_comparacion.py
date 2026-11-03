"""Comparacion original vs INT8 por muestra (VAL-02, #2): `validacion/comparar_modelos.py`.

Las pruebas usan un manifiesto y recortes sinteticos y predictores falsos: la logica de
muestras, IDs, etiquetas y calibracion se prueba sin torch, onnxruntime ni pesos.
"""

from __future__ import annotations

import csv
import importlib.util
import io
import json
import math
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "validacion" / "comparar_modelos.py"
_spec = importlib.util.spec_from_file_location("comparar_modelos", SCRIPT)
comp = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = comp
_spec.loader.exec_module(comp)

CLASES = ["cat", "dog", "person"]


def fila(cid: str, clase: str, split: str) -> dict:
    return {
        "crop_id": cid,
        "category_name": clase,
        "class_index": CLASES.index(clase),
        "split": split,
    }


MANIFIESTO = [
    fila("0.1.3:a1", "cat", "train"),
    fila("0.1.3:a2", "dog", "val"),
    fila("0.1.3:a3", "person", "test"),
    fila("0.1.3:a4", "cat", "val"),
    fila("0.1.3:a5", "person", "val"),
    fila("0.1.3:a6", "dog", "train"),
]


@pytest.fixture
def recortes(tmp_path: Path) -> Path:
    lineas = []
    for f in MANIFIESTO:
        ruta = f"{f['category_name']}/{f['crop_id'].replace(':', '_')}.png"
        (tmp_path / ruta).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / ruta).write_bytes(b"png falso")
        lineas.append(json.dumps({"crop_id": f["crop_id"], "crop_path": ruta}))
    (tmp_path / "crops.jsonl").write_text("\n".join(lineas) + "\n", encoding="utf-8")
    return tmp_path


def predictor_fijo(clase: str):
    return lambda _ruta: [0.9 if c == clase else 0.05 for c in CLASES]


def predictor_correcto(muestras):
    clase_de = {m["ruta"]: m["true_class"] for m in muestras}
    return lambda ruta: [0.8 if c == clase_de[ruta] else 0.1 for c in CLASES]


def test_solo_val_en_el_orden_del_manifiesto(recortes):
    muestras, faltantes = comp.muestras_val(MANIFIESTO, recortes, CLASES)
    assert [m["sample_id"] for m in muestras] == ["0.1.3:a2", "0.1.3:a4", "0.1.3:a5"]
    assert [m["true_class"] for m in muestras] == ["dog", "cat", "person"]
    assert faltantes == []


def test_csv_con_los_mismos_ids_y_etiquetas_que_val(recortes):
    muestras, faltantes = comp.muestras_val(MANIFIESTO, recortes, CLASES)
    correcto = predictor_correcto(muestras)
    predictores = {
        "original": correcto,
        "fp32": correcto,
        "int8": predictor_fijo("person"),
        "int8_referencia": correcto,
    }
    filas = comp.comparar(muestras, predictores, CLASES)
    datos = comp.csv_bytes(filas, CLASES)

    verificacion = comp.verificar_csv(datos, muestras, faltantes)
    assert verificacion["ok"]
    assert verificacion["mismo_orden_que_manifiesto"]

    leidas = list(csv.DictReader(io.StringIO(datos.decode("utf-8"))))
    for col in ("sample_id", "true_class", "original_prediction", "optimized_prediction"):
        assert col in leidas[0]
    assert [f["optimized_prediction"] for f in leidas] == ["person"] * 3
    assert [f["original_prediction"] for f in leidas] == ["dog", "cat", "person"]
    # Probabilidades exactas: se recalculan desde el CSV sin perder precision.
    assert float(leidas[0]["prob_int8_person"]) == 0.9

    r = comp.resumen(filas, CLASES)
    assert r["aciertos"] == {"original": 3, "fp32": 3, "int8": 1, "int8_referencia": 3}
    assert r["acuerdo_int8_vs_original"] == 1
    assert r["acuerdo_int8_vs_int8_referencia"] == 1
    assert [f["int8_referencia_prediction"] for f in leidas] == ["dog", "cat", "person"]
    assert r["clases_presentes"]


def test_detecta_id_duplicado(recortes):
    muestras, faltantes = comp.muestras_val(MANIFIESTO, recortes, CLASES)
    p = predictor_fijo("cat")
    filas = comp.comparar(muestras, dict.fromkeys(comp.MODELOS, p), CLASES)
    datos = comp.csv_bytes([*filas, filas[0]], CLASES)
    verificacion = comp.verificar_csv(datos, muestras, faltantes)
    assert verificacion["duplicados"] == ["0.1.3:a2"]
    assert not verificacion["ok"]


def test_muestra_sin_imagen_queda_como_faltante_y_falla(recortes):
    (recortes / "cat" / "0.1.3_a4.png").unlink()
    muestras, faltantes = comp.muestras_val(MANIFIESTO, recortes, CLASES)
    assert faltantes == [{"sample_id": "0.1.3:a4", "motivo": "no existe cat/0.1.3_a4.png"}]
    p = predictor_fijo("cat")
    datos = comp.csv_bytes(comp.comparar(muestras, dict.fromkeys(comp.MODELOS, p), CLASES), CLASES)
    assert not comp.verificar_csv(datos, muestras, faltantes)["ok"]


def test_rechaza_class_index_que_no_coincide(recortes):
    malo = [*MANIFIESTO, {**fila("0.1.3:a7", "dog", "val"), "class_index": 0}]
    with pytest.raises(comp.ComparacionError, match="class_index"):
        comp.muestras_val(malo, recortes, CLASES)


def test_calibracion_solo_train_segun_el_manifiesto():
    buena = [{"crop_id": "0.1.3:a1"}, {"crop_id": "0.1.3:a6"}]
    assert comp.comprobar_calibracion(MANIFIESTO, buena)["solo_train"]

    mala = [*buena, {"crop_id": "0.1.3:a3"}, {"crop_id": "0.1.3:a99"}]
    resultado = comp.comprobar_calibracion(MANIFIESTO, mala)
    assert not resultado["solo_train"]
    assert resultado["fuera_de_train"] == ["0.1.3:a3", "0.1.3:a99"]
    assert resultado["por_split_segun_manifiesto"] == {"ausente": 1, "test": 1, "train": 2}


def test_exige_sha256(tmp_path):
    ruta = tmp_path / "manifest.jsonl"
    ruta.write_text("{}\n", encoding="utf-8")
    with pytest.raises(comp.ComparacionError, match="SHA-256"):
        comp.exigir_sha(ruta, "0" * 64, "manifiesto")
    with pytest.raises(comp.ComparacionError, match="No existe"):
        comp.exigir_sha(tmp_path / "otro.jsonl", "0" * 64, "manifiesto")


def test_configuracion_toma_los_hashes_de_la_conversion_verificada():
    cfg = comp.configuracion()
    assert cfg["variante"] == "1.0.0-int8-e05.1"
    assert cfg["manifiesto"]["sha256"].startswith("45600f29")
    assert cfg["crops_jsonl_sha256"].startswith("d3d61f35")
    assert cfg["modelos"]["original"]["sha256"].startswith("e4acca42")
    assert cfg["modelos"]["int8"]["sha256"].startswith("ba89ee43")
    assert cfg["modelos"]["int8"]["s3"].endswith("1.0.0-int8-e05.1/model_int8.onnx")


def test_detecta_png_con_dimensiones_distintas_a_crops_jsonl(tmp_path):
    from PIL import Image

    bien, mal = tmp_path / "bien.png", tmp_path / "mal.png"
    Image.new("RGB", (30, 20)).save(bien)
    Image.new("RGB", (20, 30)).save(mal)
    muestras = [
        {"sample_id": "0.1.3:a1", "ruta": bien, "tamano": (30, 20)},
        {"sample_id": "0.1.3:a2", "ruta": mal, "tamano": (30, 20)},
    ]
    assert comp.dimensiones_distintas(muestras) == [
        {"sample_id": "0.1.3:a2", "esperado": (30, 20), "png": (20, 30)}
    ]


def test_detecta_png_con_hash_distinto_al_inventario(recortes):
    muestras, _ = comp.muestras_val(MANIFIESTO, recortes, CLASES)
    inventario = {m["sample_id"]: comp.sha256(m["ruta"]) for m in muestras}
    assert comp.hashes_distintos(muestras, inventario) == []

    (recortes / "cat" / "0.1.3_a4.png").write_bytes(b"otra imagen")
    distintos = comp.hashes_distintos(muestras, inventario)
    assert [d["sample_id"] for d in distintos] == ["0.1.3:a4"]


def test_inventario_exige_el_sha256_de_su_resumen(tmp_path):
    ruta = tmp_path / "recortes_0.1.3.jsonl"
    ruta.write_text('{"crop_id": "0.1.3:a1", "sha256": "ab"}\n', encoding="utf-8")
    resumen = {"inventario": {"archivo": ruta.name, "sha256": comp.sha256(ruta)}}
    ruta.with_suffix(".json").write_text(json.dumps(resumen), encoding="utf-8")
    assert comp.cargar_inventario(ruta) == {"0.1.3:a1": "ab"}

    ruta.write_text('{"crop_id": "0.1.3:a1", "sha256": "cd"}\n', encoding="utf-8")
    with pytest.raises(comp.ComparacionError, match="SHA-256"):
        comp.cargar_inventario(ruta)


def test_huella_de_validacion_del_p3():
    filas = [
        {"true_class": "cat", "original_prediction": "cat", "prob_original_cat": "0.9"},
        {"true_class": "dog", "original_prediction": "cat", "prob_original_dog": "0.4"},
    ]
    perdida = (-math.log(0.9) - math.log(0.4)) / 2
    seleccion = {"run_id": "r", "val_accuracy": 0.5, "val_loss": perdida + 5e-6}
    assert comp.huella_p3(filas, seleccion)["ok"]

    # Otra imagen en val mueve la perdida aunque el accuracy no cambie.
    assert not comp.huella_p3(filas, {**seleccion, "val_loss": perdida + 1e-3})["ok"]
    assert not comp.huella_p3(filas, {**seleccion, "val_accuracy": 1.0})["ok"]


def test_inventario_detecta_etag_que_no_es_el_md5(recortes):
    sys.path.insert(0, str(SCRIPT.parent))
    import inventario_recortes as inv

    objetos = {}
    for r in comp.leer_jsonl(recortes / "crops.jsonl"):
        _, md5, _ = inv.hashes(recortes / r["crop_path"])
        objetos[r["crop_path"]] = {"version_id": "v1", "etag": md5}
    filas, problemas, etags = inv.inventario(recortes, MANIFIESTO, objetos)
    assert (len(filas), problemas, etags) == (6, [], 6)
    assert {f["split"] for f in filas} == {"train", "val", "test"}

    objetos["cat/0.1.3_a4.png"]["etag"] = "0" * 32
    del objetos["dog/0.1.3_a2.png"]
    _, problemas, _ = inv.inventario(recortes, MANIFIESTO, objetos)
    assert len(problemas) == 2


def evidencia_valida() -> dict:
    return {
        "verificacion": {"ok": True},
        "calibracion": {"solo_train": True, "fuera_de_train": []},
        "resumen": {"clases_presentes": True},
        "huella_p3": {"ok": True},
    }


def test_fallas_enumera_cada_validacion_incumplida():
    assert comp.fallas(evidencia_valida()) == []
    mala = evidencia_valida()
    mala["verificacion"]["ok"] = False
    mala["calibracion"] = {"solo_train": False, "fuera_de_train": ["0.1.3:a3"]}
    mala["resumen"]["clases_presentes"] = False
    mala["huella_p3"]["ok"] = False
    assert len(comp.fallas(mala)) == 4


def test_corrida_invalida_no_toca_la_evidencia_existente(tmp_path):
    csv_bueno, json_bueno = tmp_path / comp.ARCHIVO_CSV, tmp_path / comp.ARCHIVO_JSON
    csv_bueno.write_bytes(b"evidencia buena\n")
    json_bueno.write_bytes(b'{"buena": true}\n')
    mala = evidencia_valida()
    mala["huella_p3"]["ok"] = False

    with pytest.raises(comp.ComparacionError, match="queda intacta"):
        comp.guardar(tmp_path, b"resultado incompleto\n", mala)
    assert csv_bueno.read_bytes() == b"evidencia buena\n"
    assert json_bueno.read_bytes() == b'{"buena": true}\n'


def test_corrida_valida_escribe_csv_y_json_sin_temporales(tmp_path):
    comp.guardar(tmp_path / "resultados", b"sample_id\n", evidencia_valida())
    destino = tmp_path / "resultados"
    assert (destino / comp.ARCHIVO_CSV).read_bytes() == b"sample_id\n"
    assert json.loads((destino / comp.ARCHIVO_JSON).read_text("utf-8"))["huella_p3"]["ok"]
    assert sorted(p.name for p in destino.iterdir()) == [comp.ARCHIVO_CSV, comp.ARCHIVO_JSON]


def test_falla_al_escribir_no_deja_temporales_ni_reemplaza(tmp_path, monkeypatch):
    (tmp_path / comp.ARCHIVO_CSV).write_bytes(b"evidencia buena\n")

    def falla_disco(*_args):
        raise OSError("disco lleno")

    monkeypatch.setattr(comp.os, "replace", falla_disco)
    with pytest.raises(OSError):
        comp.guardar(tmp_path, b"nuevo\n", evidencia_valida())
    assert (tmp_path / comp.ARCHIVO_CSV).read_bytes() == b"evidencia buena\n"
    assert [p.name for p in tmp_path.iterdir()] == [comp.ARCHIVO_CSV]
