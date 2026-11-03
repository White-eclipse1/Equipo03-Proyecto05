"""`ConfigPolitica`: configuracion externalizada y rechazada antes de mover (B1-01; 2.1)."""

from __future__ import annotations

import copy
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from p3.policy.config import ConfigPolitica, cargar_config

RUTA = Path(__file__).resolve().parents[1] / "config" / "politica.yaml"


def _base() -> dict:
    return yaml.safe_load(RUTA.read_text(encoding="utf-8"))


def test_la_configuracion_versionada_es_valida() -> None:
    config, sha = cargar_config(RUTA)
    assert "person" in config.clases_obstaculo
    assert config.confianza.umbral_bajo < config.confianza.umbral_alto
    assert len(sha) == 64


def test_el_hash_identifica_los_bytes_del_archivo(tmp_path: Path) -> None:
    copia = tmp_path / "politica.yaml"
    copia.write_bytes(RUTA.read_bytes())
    _, sha_original = cargar_config(RUTA)
    _, sha_copia = cargar_config(copia)
    assert sha_original == sha_copia
    copia.write_bytes(RUTA.read_bytes() + b"\n# cambio\n")
    assert cargar_config(copia)[1] != sha_original


def _con(ruta: tuple[str, ...], valor: object) -> dict:
    datos = copy.deepcopy(_base())
    nodo = datos
    for clave in ruta[:-1]:
        nodo = nodo[clave]
    nodo[ruta[-1]] = valor
    return datos


@pytest.mark.parametrize(
    ("ruta", "valor", "campo"),
    [
        (("clases_obstaculo",), [], "clases_obstaculo"),
        (("clases_obstaculo",), ["person", "person"], "clases_obstaculo"),
        (("zonas", "izquierda"), [0.0, 0.30], "zonas"),  # hueco con el centro
        (("zonas", "derecha"), [0.65, 0.9], "zonas"),  # no llega al borde
        (("zonas", "centro"), [0.5, 0.4], "zonas"),
        (("geometria", "banda_riesgo_y_min"), 1.0, "banda_riesgo_y_min"),
        (("geometria", "area_min"), -0.1, "area_min"),
        (("geometria", "cobertura_min_zona"), 0, "cobertura_min_zona"),
        (("confianza", "umbral_alto"), 1.5, "umbral_alto"),
        (("confianza", "umbral_bajo"), 0.6, "confianza"),  # bajo >= alto
        (("temporal", "cuadros_para_bloquear"), 0, "cuadros_para_bloquear"),
        (("temporal", "cuadros_para_liberar"), 0, "cuadros_para_liberar"),
        (("temporal", "vigencia_comando_ms"), 0, "vigencia_comando_ms"),
        (("comandos", "velocidad_crucero"), 1.5, "velocidad_crucero"),
        (("comandos", "velocidad_precaucion"), 0.9, "comandos"),  # > crucero
        (("comandos", "velocidad_evasion"), 0.5, "comandos"),  # > precaucion
        (("comandos", "direccion_evasion"), 0, "direccion_evasion"),
        (("evasion", "lado_preferido"), "centro", "lado_preferido"),
        (("schema_version",), 2, "schema_version"),
        (("campo_desconocido",), 1, "campo_desconocido"),
    ],
)
def test_una_configuracion_invalida_se_rechaza_nombrando_el_campo(
    ruta: tuple[str, ...], valor: object, campo: str
) -> None:
    with pytest.raises(ValidationError) as error:
        ConfigPolitica.model_validate(_con(ruta, valor))
    assert any(campo in map(str, e["loc"]) for e in error.value.errors())


def test_cargar_un_archivo_invalido_falla_antes_de_crear_la_politica(tmp_path: Path) -> None:
    mala = tmp_path / "mala.yaml"
    mala.write_text(yaml.safe_dump(_con(("confianza", "umbral_alto"), 2.0)), encoding="utf-8")
    with pytest.raises(ValidationError):
        cargar_config(mala)
