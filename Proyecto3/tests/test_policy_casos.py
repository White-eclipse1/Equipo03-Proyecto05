"""Casos C1-C7 de la politica con detecciones sinteticas (B1-02, B1-03; criterio 2.2).

Las expectativas se fijan aqui por geometria ANTES de implementar, con la
configuracion versionada `config/politica.yaml` (cuadro de 640x480, un cuadro
cada 100 ms, 2 cuadros para bloquear, 3 para liberar). Zonas en x normalizado:
izquierda [0, 0.35), centro [0.35, 0.65], derecha (0.65, 1].

Cajas de referencia (xyxy en pixeles, origen arriba a la izquierda):

- CENTRO  x 260-380 -> 0.41-0.59: solo centro; y2 = 460 (0.96) dentro de la banda.
- IZQ     x  20-180 -> 0.03-0.28: solo izquierda.
- DER     x 470-620 -> 0.73-0.97: solo derecha.
- ALTO    centro pero y2 = 120 (0.25): fuera de la banda de riesgo, se ignora.

Estas pruebas aislan reglas de politica; NO acreditan el detector real (eso lo
cubre el recorrido integral de B3 con pesos reales).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from p3.policy.config import ConfigPolitica, cargar_config
from p3.policy.contrato import Cuadro
from p3.policy.politica import Decision, PoliticaDecision

RUTA = Path(__file__).resolve().parents[1] / "config" / "politica.yaml"
CONFIG, SHA = cargar_config(RUTA)

CENTRO = (260, 200, 380, 460)
IZQ = (20, 200, 180, 460)
DER = (470, 200, 620, 460)
ALTO = (260, 10, 380, 120)
PERIODO_MS = 100


def det(caja: tuple[float, float, float, float], conf: float = 0.9, clase: str = "person"):
    return {"class_name": clase, "confidence": conf, "bbox_xyxy": list(caja)}


def cuadro(i: int, *dets: dict, seq: str = "s1", t_ms: int | None = None) -> Cuadro:
    return Cuadro.model_validate(
        {
            "sequence_id": seq,
            "frame_id": f"{seq}-{i:04d}",
            "t_capture_ms": i * PERIODO_MS if t_ms is None else t_ms,
            "image_width": 640,
            "image_height": 480,
            "status": "ok",
            "detections": list(dets),
        }
    )


def error(i: int, seq: str = "s1") -> Cuadro:
    return Cuadro.model_validate(
        {
            "sequence_id": seq,
            "frame_id": f"{seq}-{i:04d}",
            "t_capture_ms": i * PERIODO_MS,
            "image_width": 640,
            "image_height": 480,
            "status": "error",
            "detections": [],
            "error": "excepcion del detector",
        }
    )


def correr(escenas: list[tuple], config: ConfigPolitica = CONFIG) -> list[Decision]:
    """Cada escena es una tupla de detecciones; el cuadro i es la escena i (desde 1)."""
    politica = PoliticaDecision(config, config_sha256=SHA)
    return [politica.decidir(cuadro(i, *dets)) for i, dets in enumerate(escenas, start=1)]


LIBRE: tuple = ()
CALENTAR = [LIBRE] * 3  # 3 cuadros libres confirman las tres zonas


def sin_evasion() -> ConfigPolitica:
    datos = CONFIG.model_dump()
    datos["evasion"]["habilitada"] = False
    return ConfigPolitica.model_validate(datos)


# --- C1 via despejada ------------------------------------------------------------


def test_c1_via_despejada_avanza_tras_confirmar_la_percepcion() -> None:
    decisiones = correr([LIBRE] * 6)
    # Los dos primeros cuadros aun no confirman que la via esta libre: STOP.
    assert [d.accion for d in decisiones[:2]] == ["STOP", "STOP"]
    assert all(d.estado == "UNKNOWN" for d in decisiones[:2])
    assert all(d.reason_code == "PERCEPCION_NO_CONFIRMADA" for d in decisiones[:2])
    # Desde el tercero avanza con velocidad positiva y recto: no es STOP constante.
    for d in decisiones[2:]:
        assert d.accion == "FORWARD"
        assert d.estado == "CLEAR"
        assert d.velocidad == CONFIG.comandos.velocidad_crucero > 0
        assert d.direccion == 0
        assert d.reason_code == "VIA_LIBRE"


def test_c1_un_objeto_fuera_de_la_banda_de_riesgo_no_detiene() -> None:
    decisiones = correr([*CALENTAR, (det(ALTO),), (det(ALTO),), (det(ALTO),)])
    assert [d.accion for d in decisiones[3:]] == ["FORWARD"] * 3
    assert decisiones[3].detecciones[0].nivel == "ignorada"
    assert decisiones[3].detecciones[0].motivo == "fuera_de_banda"


def test_c1_una_clase_que_no_es_obstaculo_no_detiene() -> None:
    decisiones = correr([*CALENTAR, (det(CENTRO, clase="traffic light"),)] * 1)
    assert decisiones[3].accion == "FORWARD"
    assert decisiones[3].detecciones[0].motivo == "clase_no_obstaculo"


def test_c1_una_caja_diminuta_no_detiene() -> None:
    diminuta = (318, 440, 322, 444)  # 16 px2 / 307200 px2 < area_min
    decisiones = correr([*CALENTAR, (det(diminuta),), (det(diminuta),)])
    assert [d.accion for d in decisiones[3:]] == ["FORWARD"] * 2
    assert decisiones[3].detecciones[0].motivo == "area_pequena"


# --- C2 obstaculo central ----------------------------------------------------------


def test_c2_obstaculo_central_detiene_al_confirmarse_sin_evasion() -> None:
    decisiones = correr([*CALENTAR, (det(CENTRO),), (det(CENTRO),), (det(CENTRO),)], sin_evasion())
    # Primer cuadro con el obstaculo: aun no confirmado, pero ya NO avanza a crucero.
    assert decisiones[3].accion == "SLOW"
    assert decisiones[3].estado == "CAUTION"
    assert decisiones[3].reason_code == "CENTRO_POR_CONFIRMAR"
    # Segundo cuadro: bloqueo confirmado -> STOP con velocidad cero.
    for d in decisiones[4:]:
        assert d.accion == "STOP"
        assert d.velocidad == 0
        assert d.estado == "BLOCKED"
        assert d.reason_code == "CENTRO_BLOQUEADO"
    assert decisiones[4].cambio_estado
    assert decisiones[4].estado_anterior == "CAUTION"


def test_c2_con_evasion_gira_solo_hacia_un_lateral_verificado_libre() -> None:
    decisiones = correr([*CALENTAR, (det(CENTRO),), (det(CENTRO),)])
    d = decisiones[4]
    assert d.estado == "BLOCKED"
    assert d.accion == "EVADE_RIGHT"  # ambos libres: desempata `lado_preferido`
    assert d.direccion == CONFIG.comandos.direccion_evasion > 0
    assert d.velocidad == CONFIG.comandos.velocidad_evasion
    assert d.zonas["derecha"].estado == "LIBRE"


def test_c2_nunca_avanza_a_crucero_hacia_el_bloqueo() -> None:
    decisiones = correr([*CALENTAR, *[(det(CENTRO),)] * 5])
    assert all(d.accion != "FORWARD" for d in decisiones[3:])


# --- C3 / C4 laterales -----------------------------------------------------------


@pytest.mark.parametrize(
    ("caja", "lado", "signo_prohibido"),
    [(IZQ, "izquierda", -1), (DER, "derecha", 1)],
)
def test_c3_c4_obstaculo_lateral_avanza_sin_dirigirse_a_la_zona_ocupada(
    caja: tuple, lado: str, signo_prohibido: int
) -> None:
    decisiones = correr([*CALENTAR, *[(det(caja),)] * 5])
    for d in decisiones[3:]:
        assert d.accion == "SLOW"  # avance seguro a velocidad de precaucion
        assert d.velocidad == CONFIG.comandos.velocidad_precaucion > 0
        assert d.direccion * signo_prohibido <= 0  # nunca hacia el lado ocupado
        assert d.reason_code == "LATERAL_OCUPADO"
        assert d.zonas["centro"].estado == "LIBRE"
    assert decisiones[-1].zonas[lado].estado == "OCUPADA"


def test_c3_c4_distinguen_la_geometria_del_obstaculo_central() -> None:
    izquierda = correr([*CALENTAR, (det(IZQ),), (det(IZQ),)], sin_evasion())[-1]
    centro = correr([*CALENTAR, (det(CENTRO),), (det(CENTRO),)], sin_evasion())[-1]
    assert izquierda.accion == "SLOW"
    assert centro.accion == "STOP"


# --- C5 varios obstaculos ------------------------------------------------------------


def test_c5_centro_e_izquierda_bloqueados_evade_solo_a_la_derecha() -> None:
    d = correr([*CALENTAR, (det(CENTRO), det(IZQ)), (det(CENTRO), det(IZQ))])[-1]
    assert d.accion == "EVADE_RIGHT"


def test_c5_centro_y_derecha_bloqueados_evade_a_la_izquierda_aunque_prefiera_derecha() -> None:
    d = correr([*CALENTAR, (det(CENTRO), det(DER)), (det(CENTRO), det(DER))])[-1]
    assert d.accion == "EVADE_LEFT"
    assert d.direccion < 0


def test_c5_todas_las_rutas_bloqueadas_detiene() -> None:
    escena = (det(IZQ), det(CENTRO), det(DER))
    d = correr([*CALENTAR, escena, escena])[-1]
    assert d.accion == "STOP"
    assert d.velocidad == 0
    assert d.reason_code == "SIN_ZONA_LIBRE"


def test_c5_considera_el_conjunto_y_no_solo_la_deteccion_mas_confiable() -> None:
    escena = (det(IZQ, conf=0.99), det(CENTRO, conf=0.6))
    d = correr([*CALENTAR, escena, escena], sin_evasion())[-1]
    assert d.accion == "STOP"
    assert d.zonas["centro"].estado == "OCUPADA"
    assert d.zonas["izquierda"].estado == "OCUPADA"


def test_c5_una_caja_ancha_ocupa_todas_las_zonas_que_cubre() -> None:
    ancha = (300, 200, 600, 460)  # x 0.47-0.94: centro y derecha
    d = correr([*CALENTAR, (det(ancha),), (det(ancha),)])[-1]
    assert d.zonas["centro"].estado == "OCUPADA"
    assert d.zonas["derecha"].estado == "OCUPADA"
    assert d.accion == "EVADE_LEFT"


def test_c5_un_obstaculo_pequeno_en_el_limite_ocupa_las_zonas_que_toca() -> None:
    # x 0.330-0.370: 26 px a caballo entre izquierda y centro. Cubre solo ~6% del
    # ancho de cada zona, pero cada mitad es ~50% de la caja: debe ocupar ambas.
    limite = (211, 200, 237, 460)
    decisiones = correr([*CALENTAR, (det(limite),), (det(limite),)], sin_evasion())
    assert decisiones[-1].detecciones[0].zonas == ("izquierda", "centro")
    assert decisiones[-1].zonas["centro"].estado == "OCUPADA"
    assert decisiones[-1].accion == "STOP"


def test_c5_un_obstaculo_pequeno_mayormente_en_un_lado_tambien_cuenta_en_el_otro() -> None:
    # x 0.336-0.370: 39% de la caja en la izquierda y 61% en el centro.
    d = correr([*CALENTAR, (det((215, 200, 237, 460)),)])[-1]
    assert d.detecciones[0].zonas == ("izquierda", "centro")


def test_c5_una_caja_lateral_grande_que_roza_el_centro_no_lo_ocupa() -> None:
    # x 0.156-0.359: solo 0.009 de solape con el centro (5% de la caja, 3% del centro).
    d = correr([*CALENTAR, (det((100, 200, 230, 460)),)])[-1]
    assert d.detecciones[0].zonas == ("izquierda",)


@pytest.mark.parametrize("ancho", [1, 4, 10, 26, 60, 120, 300, 640])
def test_ninguna_caja_dentro_del_cuadro_queda_sin_zona(ancho: int) -> None:
    politica = PoliticaDecision(CONFIG, config_sha256=SHA)
    for i, x1 in enumerate(range(0, 641 - ancho, 3), start=1):
        d = politica.decidir(cuadro(i, det((x1, 200, x1 + ancho, 460), conf=0.1)))
        assert d.detecciones[0].zonas, f"caja x {x1}-{x1 + ancho} sin zona"


def test_c5_no_evade_hacia_un_lateral_con_deteccion_debil_reciente() -> None:
    escena = (det(CENTRO), det(DER, conf=0.4), det(IZQ, conf=0.4))
    d = correr([*CALENTAR, escena, escena])[-1]
    assert d.accion == "STOP"
    assert d.reason_code == "SIN_ZONA_LIBRE"


# --- C6 baja confianza ---------------------------------------------------------------


def test_c6_deteccion_debil_en_el_centro_reduce_velocidad_sin_detener() -> None:
    decisiones = correr([*CALENTAR, *[(det(CENTRO, conf=0.40),)] * 5])
    for d in decisiones[3:]:
        assert d.accion == "SLOW"
        assert d.estado == "CAUTION"
        assert d.reason_code == "CENTRO_DEBIL"
        assert d.detecciones[0].nivel == "debil"
    assert decisiones[-1].zonas["centro"].estado == "LIBRE"


def test_c6_bajo_el_umbral_bajo_se_ignora() -> None:
    decisiones = correr([*CALENTAR, *[(det(CENTRO, conf=0.20),)] * 3])
    assert [d.accion for d in decisiones[3:]] == ["FORWARD"] * 3
    assert decisiones[3].detecciones[0].motivo == "bajo_umbral"


def test_c6_al_cruzar_el_umbral_alto_se_bloquea() -> None:
    escenas = [*CALENTAR, (det(CENTRO, conf=0.40),), (det(CENTRO, conf=0.55),)]
    escenas += [(det(CENTRO, conf=0.55),)]
    decisiones = correr(escenas, sin_evasion())
    assert decisiones[3].accion == "SLOW"
    assert decisiones[4].reason_code == "CENTRO_POR_CONFIRMAR"
    assert decisiones[5].accion == "STOP"
    assert decisiones[5].estado == "BLOCKED"


def test_c6_una_deteccion_debil_sostiene_un_bloqueo_ya_confirmado() -> None:
    escenas = [*CALENTAR, (det(CENTRO),), (det(CENTRO),)]
    escenas += [(det(CENTRO, conf=0.40),)] * 5
    decisiones = correr(escenas, sin_evasion())
    assert all(d.accion == "STOP" for d in decisiones[4:])
    assert decisiones[-1].reason_code == "CENTRO_HISTERESIS"


# --- C7 aparicion / desaparicion -----------------------------------------------------


def test_c7_libre_obstaculo_persistente_y_desaparicion_con_histeresis() -> None:
    escenas = [*CALENTAR, *[(det(CENTRO),)] * 4, *[LIBRE] * 4]
    decisiones = correr(escenas, sin_evasion())
    acciones = [d.accion for d in decisiones]
    assert acciones == [
        "STOP",  # 1 arranque
        "STOP",  # 2 arranque
        "FORWARD",  # 3 via confirmada libre
        "SLOW",  # 4 obstaculo, 1er cuadro
        "STOP",  # 5 bloqueo confirmado
        "STOP",  # 6
        "STOP",  # 7
        "STOP",  # 8 desaparece: 1 de 3 libres
        "STOP",  # 9 2 de 3 libres
        "FORWARD",  # 10 3 de 3 libres: reanuda
        "FORWARD",  # 11
    ]
    assert [d.reason_code for d in decisiones[7:9]] == ["CENTRO_HISTERESIS"] * 2
    cambios = [(d.estado_anterior, d.estado) for d in decisiones if d.cambio_estado]
    assert cambios == [
        ("UNKNOWN", "CLEAR"),
        ("CLEAR", "CAUTION"),
        ("CAUTION", "BLOCKED"),
        ("BLOCKED", "CLEAR"),
    ]


def test_c7_un_falso_positivo_aislado_no_detiene() -> None:
    decisiones = correr([*CALENTAR, (det(CENTRO),), LIBRE, LIBRE, LIBRE])
    assert all(d.estado != "BLOCKED" for d in decisiones)
    assert [d.accion for d in decisiones[3:]] == ["SLOW", "FORWARD", "FORWARD", "FORWARD"]


def test_c7_un_unico_cuadro_vacio_no_reanuda_un_bloqueo() -> None:
    escenas = [*CALENTAR, (det(CENTRO),), (det(CENTRO),), LIBRE, (det(CENTRO),), LIBRE]
    decisiones = correr(escenas, sin_evasion())
    assert all(d.accion == "STOP" for d in decisiones[4:])


def test_c7_es_determinista() -> None:
    escenas = [*CALENTAR, *[(det(CENTRO),)] * 3, *[LIBRE] * 4]
    assert correr(escenas) == correr(escenas)


# --- Percepcion invalida y orden temporal (apoyo a C8/C9 de B2) ----------------------


def test_un_error_del_detector_detiene_y_no_cuenta_como_via_libre() -> None:
    politica = PoliticaDecision(CONFIG, config_sha256=SHA)
    for i in range(1, 4):
        politica.decidir(cuadro(i))
    d = politica.decidir(error(4))
    assert d.accion == "STOP"
    assert d.velocidad == 0
    assert d.estado == "FAULT"
    assert d.reason_code == "ERROR_PERCEPCION"
    # Tras el error hay que volver a confirmar la via: no reanuda con un cuadro.
    siguientes = [politica.decidir(cuadro(i)) for i in range(5, 8)]
    assert [s.accion for s in siguientes] == ["STOP", "STOP", "FORWARD"]


def test_un_cuadro_fuera_de_orden_se_rechaza_con_stop() -> None:
    politica = PoliticaDecision(CONFIG, config_sha256=SHA)
    for i in range(1, 5):
        politica.decidir(cuadro(i))
    viejo = politica.decidir(cuadro(9, t_ms=200))
    assert viejo.accion == "STOP"
    assert viejo.reason_code == "CUADRO_FUERA_DE_ORDEN"
    # El cuadro viejo no altera la memoria temporal de la politica.
    assert politica.decidir(cuadro(5)).accion == "FORWARD"


def test_una_secuencia_nueva_reinicia_la_confirmacion() -> None:
    politica = PoliticaDecision(CONFIG, config_sha256=SHA)
    for i in range(1, 5):
        politica.decidir(cuadro(i))
    d = politica.decidir(cuadro(1, seq="s2"))
    assert d.accion == "STOP"
    assert d.reason_code == "PERCEPCION_NO_CONFIRMADA"


# --- Trazabilidad de la decision -----------------------------------------------------


def test_la_decision_queda_vinculada_al_cuadro_y_a_la_configuracion() -> None:
    d = correr([LIBRE] * 3)[-1]
    assert d.sequence_id == "s1"
    assert d.frame_id == "s1-0003"
    assert d.t_capture_ms == 300
    assert d.valido_hasta_ms == 300 + CONFIG.temporal.vigencia_comando_ms
    assert d.config_sha256 == SHA
    assert set(d.zonas) == {"izquierda", "centro", "derecha"}
    assert d.razon  # texto legible ademas del codigo


def test_stop_siempre_lleva_velocidad_y_direccion_cero() -> None:
    escenas = [LIBRE, LIBRE, *[(det(IZQ), det(CENTRO), det(DER))] * 3]
    for d in correr(escenas):
        if d.accion == "STOP":
            assert (d.velocidad, d.direccion) == (0, 0)


def test_cada_deteccion_registra_su_nivel_y_zonas() -> None:
    d = correr([*CALENTAR, (det(IZQ), det(CENTRO, conf=0.4), det(DER, conf=0.1))])[-1]
    niveles = [(e.nivel, e.zonas) for e in d.detecciones]
    assert niveles == [
        ("firme", ("izquierda",)),
        ("debil", ("centro",)),
        ("ignorada", ("derecha",)),
    ]
