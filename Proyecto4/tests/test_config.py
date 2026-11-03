"""Configuracion del receptor y creacion del almacen segun el entorno."""

from __future__ import annotations

from p4.capturas import api
from p4.capturas.almacen import AlmacenAusente, AlmacenMemoria, AlmacenS3
from p4.capturas.config import ConfigCapturas


def test_valores_por_defecto_sin_secretos():
    config = ConfigCapturas()
    assert config.token_dispositivo is None
    assert config.modelos() == {}
    assert config.lista_clases() == ("cat", "dog", "person")  # orden del modelo del P3
    assert config.almacen == "s3"


def test_variables_vacias_son_none_y_prefijo_normalizado():
    config = ConfigCapturas(
        P4_AWS_PROFILE="", P4_TOKEN_DISPOSITIVO="  ", P4_S3_ENDPOINT="", P4_PREFIJO="/capturas"
    )
    assert config.aws_profile is None
    assert config.token_dispositivo is None
    assert config.s3_endpoint is None
    assert config.prefijo == "capturas/"


def test_modelos_aceptados():
    config = ConfigCapturas(P4_MODELOS_ACEPTADOS=f" 1.0.0-int8 = {'A' * 64} , 2.0.0={'b' * 64}")
    assert config.modelos() == {"1.0.0-int8": "a" * 64, "2.0.0": "b" * 64}


def test_el_token_no_aparece_al_imprimir_la_config():
    config = ConfigCapturas(P4_TOKEN_DISPOSITIVO="secreto-de-prueba")
    assert "secreto-de-prueba" not in repr(config)


def test_almacen_en_memoria():
    assert isinstance(api._crear_almacen(ConfigCapturas(P4_ALMACEN="memoria")), AlmacenMemoria)


def test_sin_bucket_el_almacen_responde_que_falta_configurarlo():
    almacen = api._crear_almacen(ConfigCapturas(P4_ALMACEN="s3", P4_BUCKET=""))
    assert isinstance(almacen, AlmacenAusente)
    assert "P4_BUCKET" in almacen.motivo


def test_perfil_inexistente_no_tumba_el_portal():
    config = ConfigCapturas(P4_BUCKET="b", P4_AWS_PROFILE="perfil-que-no-existe-p4")
    almacen = api._crear_almacen(config)
    assert isinstance(almacen, AlmacenAusente)
    assert "ProfileNotFound" in almacen.motivo


def test_minio_local_con_endpoint():
    config = ConfigCapturas(
        P4_BUCKET="dataset-releases",
        P4_S3_ENDPOINT="http://minio:9000",
        P4_S3_ACCESS_KEY="usuario",
        P4_S3_SECRET_KEY="clave",
    )
    almacen = api._crear_almacen(config)
    assert isinstance(almacen, AlmacenS3)
    assert almacen.cliente.meta.endpoint_url == "http://minio:9000"
