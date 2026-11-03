"""Frente 7 — Settings escribe de verdad en `quality.yaml`.

La rubrica es explicita: un formulario que no escribe en `quality.yaml` vale
cero. Asi que lo que se prueba aqui no es que el endpoint responda 200, sino
las dos cosas que lo hacen util:

  - el cambio PERSISTE en el archivo, con sus comentarios intactos;
  - el cambio se REFLEJA en la siguiente corrida de la compuerta, sin tocar
    una linea de codigo.

La segunda es la que convierte `quality.yaml` en una politica declarativa y no
en decoracion.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from dataset_quality import policy
from dataset_quality.main import create_app
from dataset_quality.models.quality import QualityConfig

# Copia reducida del `quality.yaml` real, con sus comentarios: son justo lo que
# no puede sobrevivir a un `yaml.safe_dump` y lo que esta prueba vigila.
YAML = """\
# ---------------------------------------------------------------------------
# Umbrales de la compuerta de calidad.
# ---------------------------------------------------------------------------

version: 1

# NO es un valor de ejemplo: el requisito real son 300 imagenes distintas.
min_images_per_class:
  enabled: true
  severity: error
  min_images: 300
  min_classes: 2

small_objects:
  enabled: true
  severity: warning
  area_ratio_threshold: 0.02 # area/annotation < 2% del area de la imagen
  max_ratio: 0.10 # tolera hasta 10% de las anotaciones marcadas

class_imbalance:
  enabled: true
  severity: warning
  max_ratio_max_min: 20.0

duplicates:
  enabled: true
  severity: error
  phash_hamming_distance: 5 # <=5 bits de diferencia se considera duplicado
  max_ratio: 0.01

degenerate_boxes:
  enabled: true
  severity: error
  max_ratio: 0.0 # cero tolerancia

spatial_bias:
  enabled: true
  severity: warning
  grid_size: 3
  max_cell_share: 0.60

splits:
  seed: 42
  ratios:
    train: 0.70
    val: 0.15
    test: 0.15
  tolerance: 0.05
  group_near_duplicates: true
"""


@pytest.fixture
def config_path(tmp_path: Path, monkeypatch) -> Path:
    """Un `quality.yaml` propio para cada prueba; nunca el del repositorio."""
    destino = tmp_path / "quality.yaml"
    destino.write_text(YAML, encoding="utf-8")
    monkeypatch.setattr(policy, "CONFIG_PATH", destino)
    return destino


@pytest.fixture
def client(env, config_path) -> TestClient:
    del env, config_path
    return TestClient(create_app(), raise_server_exceptions=False)


def editar(client: TestClient, **cambios) -> dict:
    """Lee la politica, cambia lo pedido bajo `min_images_per_class` y la guarda."""
    actual = client.get("/api/policy").json()["data"]
    actual["min_images_per_class"] = {**actual["min_images_per_class"], **cambios}
    return actual


# --------------------------------------------------------------------------
# Lectura
# --------------------------------------------------------------------------
def test_get_devuelve_la_politica_del_archivo(client) -> None:
    cuerpo = client.get("/api/policy").json()

    assert cuerpo["source"] == "quality.yaml"
    assert cuerpo["data"]["min_images_per_class"]["min_images"] == 300
    assert cuerpo["data"]["splits"]["ratios"]["train"] == pytest.approx(0.70)
    assert cuerpo["warnings"] == []


def test_sin_quality_yaml_da_503_y_dice_donde_falta(client, monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(policy, "CONFIG_PATH", tmp_path / "no-existe.yaml")

    response = client.get("/api/policy")

    assert response.status_code == 503
    assert "quality.yaml" in response.json()["detail"]


# --------------------------------------------------------------------------
# Escritura — que persista
# --------------------------------------------------------------------------
def test_el_put_escribe_el_umbral_en_el_archivo(client, config_path: Path) -> None:
    response = client.put("/api/policy", json=editar(client, min_images=450))

    assert response.status_code == 200
    assert response.json()["changed"] == ["min_images_per_class.min_images"]
    # Lo que vale no es la respuesta: es lo que quedo en disco.
    assert "min_images: 450" in config_path.read_text(encoding="utf-8")
    assert QualityConfig.from_yaml(config_path).min_images_per_class.min_images == 450


def test_el_put_conserva_los_comentarios_del_archivo(client, config_path: Path) -> None:
    """Los comentarios explican la politica; un `safe_dump` los borraria todos."""
    client.put("/api/policy", json=editar(client, min_images=450))
    texto = config_path.read_text(encoding="utf-8")

    assert "# NO es un valor de ejemplo" in texto
    assert "# cero tolerancia" in texto
    assert "# ---------------------------------------------------------------------------" in texto


def test_un_comentario_al_final_de_la_linea_editada_sobrevive(client, config_path: Path) -> None:
    actual = client.get("/api/policy").json()["data"]
    actual["duplicates"] = {**actual["duplicates"], "phash_hamming_distance": 8}

    client.put("/api/policy", json=actual)

    linea = next(
        renglon
        for renglon in config_path.read_text(encoding="utf-8").splitlines()
        if "phash_hamming_distance" in renglon
    )
    assert linea.strip().startswith("phash_hamming_distance: 8")
    assert "# <=5 bits" in linea


def test_solo_se_tocan_las_lineas_que_cambian(client, config_path: Path) -> None:
    antes = config_path.read_text(encoding="utf-8").splitlines()
    client.put("/api/policy", json=editar(client, min_images=450))
    despues = config_path.read_text(encoding="utf-8").splitlines()

    distintas = [i for i, (a, b) in enumerate(zip(antes, despues, strict=True)) if a != b]
    assert len(distintas) == 1


def test_una_politica_identica_no_reescribe_nada(client) -> None:
    igual = client.get("/api/policy").json()["data"]

    cuerpo = client.put("/api/policy", json=igual).json()

    assert cuerpo["changed"] == []
    assert cuerpo["stale_reports"] is False


def test_el_put_puede_cambiar_varios_umbrales_a_la_vez(client, config_path: Path) -> None:
    actual = client.get("/api/policy").json()["data"]
    actual["small_objects"]["max_ratio"] = 0.25
    actual["spatial_bias"]["grid_size"] = 4
    actual["splits"]["ratios"] = {"train": 0.6, "val": 0.2, "test": 0.2}

    cuerpo = client.put("/api/policy", json=actual).json()

    assert cuerpo["changed"] == [
        "small_objects.max_ratio",
        "spatial_bias.grid_size",
        "splits.ratios.test",
        "splits.ratios.train",
        "splits.ratios.val",
    ]
    guardada = QualityConfig.from_yaml(config_path)
    assert guardada.small_objects.max_ratio == pytest.approx(0.25)
    assert guardada.spatial_bias.grid_size == 4
    assert guardada.splits.ratios.train == pytest.approx(0.6)


def test_dos_claves_con_el_mismo_nombre_no_se_confunden(client, config_path: Path) -> None:
    """`max_ratio` existe en tres checks: la ruta completa decide cual se edita."""
    actual = client.get("/api/policy").json()["data"]
    actual["duplicates"]["max_ratio"] = 0.33

    client.put("/api/policy", json=actual)

    guardada = QualityConfig.from_yaml(config_path)
    assert guardada.duplicates.max_ratio == pytest.approx(0.33)
    assert guardada.small_objects.max_ratio == pytest.approx(0.10)
    assert guardada.degenerate_boxes.max_ratio == pytest.approx(0.0)


# --------------------------------------------------------------------------
# Escritura — que se valide antes de tocar el disco
# --------------------------------------------------------------------------
def test_un_umbral_fuera_de_rango_se_rechaza_sin_escribir(client, config_path: Path) -> None:
    antes = config_path.read_text(encoding="utf-8")

    response = client.put("/api/policy", json=editar(client, min_images=0))

    assert response.status_code == 422
    assert "min_images" in response.text
    assert config_path.read_text(encoding="utf-8") == antes


def test_una_severidad_inventada_se_rechaza(client, config_path: Path) -> None:
    antes = config_path.read_text(encoding="utf-8")

    response = client.put("/api/policy", json=editar(client, severity="catastrofica"))

    assert response.status_code == 422
    assert config_path.read_text(encoding="utf-8") == antes


def test_una_clave_desconocida_se_rechaza(client) -> None:
    """`QualityConfig` prohibe campos extra: un typo no se guarda en silencio."""
    actual = client.get("/api/policy").json()["data"]
    actual["min_images_per_class"]["min_imagenes"] = 300

    assert client.put("/api/policy", json=actual).status_code == 422


# --------------------------------------------------------------------------
# Avisos: bajar el minimo del curso se permite, pero no en silencio
# --------------------------------------------------------------------------
def test_bajar_el_minimo_del_curso_avisa(client) -> None:
    cuerpo = client.put("/api/policy", json=editar(client, min_images=50)).json()

    assert cuerpo["changed"] == ["min_images_per_class.min_images"]
    assert any("300" in aviso for aviso in cuerpo["warnings"])


def test_desactivar_el_volumen_minimo_avisa(client) -> None:
    cuerpo = client.put("/api/policy", json=editar(client, enabled=False)).json()

    assert any("desactivado" in aviso for aviso in cuerpo["warnings"])


def test_degradar_la_severidad_a_warning_avisa(client) -> None:
    cuerpo = client.put("/api/policy", json=editar(client, severity="warning")).json()

    assert any("bloquearia" in aviso for aviso in cuerpo["warnings"])


# --------------------------------------------------------------------------
# Que el cambio se REFLEJE en la siguiente corrida
# --------------------------------------------------------------------------
def test_el_umbral_guardado_cambia_el_veredicto_de_la_compuerta(client, config_path: Path) -> None:
    """La prueba que la rubrica pide: subir el umbral y que ahora falle.

    Se corre la compuerta contra el archivo, sin tocar una linea de codigo entre
    una corrida y la otra.
    """
    from dataset_quality.analyzers import analyze_min_images_per_class
    from dataset_quality.models.coco import CocoDataset

    dataset = CocoDataset.model_validate(
        {
            "images": [
                {"id": i, "file_name": f"{i}.jpg", "width": 64, "height": 64} for i in (1, 2)
            ],
            "annotations": [
                {
                    "id": i,
                    "image_id": i,
                    "category_id": 1,
                    "bbox": [0, 0, 10, 10],
                    "area": 100,
                    "iscrowd": 0,
                }
                for i in (1, 2)
            ],
            "categories": [{"id": 1, "name": "car"}],
        }
    )

    # Con el umbral en 1 imagen y 1 clase, el dataset pasa.
    client.put("/api/policy", json=editar(client, min_images=1, min_classes=1))
    config = QualityConfig.from_yaml(config_path)
    assert analyze_min_images_per_class(dataset, config.min_images_per_class).status == "pass"

    # Se sube el umbral a un valor imposible DESDE LA APP y ahora bloquea.
    client.put("/api/policy", json=editar(client, min_images=99999, min_classes=1))
    config = QualityConfig.from_yaml(config_path)
    resultado = analyze_min_images_per_class(dataset, config.min_images_per_class)

    assert resultado.status == "fail"
    assert resultado.severity == "error"
    assert resultado.threshold == pytest.approx(99999)
