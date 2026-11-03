"""Politica temporal: detecciones por cuadro -> estado de la via y comando (B1-02; E4, 2.1-2.2).

Funcion pura `paso(config, memoria, cuadro)`: misma entrada, misma salida, sin
reloj de pared ni E/S. `PoliticaDecision` solo guarda la memoria entre cuadros;
la usan igual la aplicacion y el recorrido de evaluacion.

Reglas (justificacion completa en `docs/politica.md`):

1. Cada deteccion se clasifica como `firme`, `debil` o `ignorada` (clase que no
   es obstaculo, bajo `umbral_bajo`, fuera de la banda de riesgo o caja menor
   que `area_min`) y se asigna a TODAS las zonas que cubre.
2. Cada zona es DESCONOCIDA, LIBRE u OCUPADA. Pasa a OCUPADA tras
   `cuadros_para_bloquear` cuadros seguidos con una deteccion firme, y a LIBRE
   tras `cuadros_para_liberar` cuadros seguidos sin deteccion firme ni debil.
   Una deteccion debil no ocupa una zona, pero impide liberarla (histeresis de
   confianza). Al arrancar, tras un error y al cambiar de secuencia todas las
   zonas vuelven a DESCONOCIDA: la via libre hay que confirmarla.
3. El centro manda: si no esta LIBRE no se avanza. Con el centro OCUPADO se
   evade hacia un lateral LIBRE y sin detecciones recientes; si no hay, STOP.
4. Con el centro LIBRE se avanza a crucero solo si todo esta despejado; una
   deteccion por confirmar o debil en el centro, o cualquier lateral no libre,
   baja a velocidad de precaucion, siempre recto.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from p3.policy.config import ConfigPolitica
from p3.policy.contrato import Cuadro, Deteccion

NombreZona = Literal["izquierda", "centro", "derecha"]
ZONAS: tuple[NombreZona, ...] = ("izquierda", "centro", "derecha")

EstadoVia = Literal["UNKNOWN", "CLEAR", "CAUTION", "BLOCKED", "FAULT"]
EstadoZona = Literal["DESCONOCIDA", "LIBRE", "OCUPADA"]
Accion = Literal["FORWARD", "SLOW", "EVADE_LEFT", "EVADE_RIGHT", "STOP"]
Nivel = Literal["firme", "debil", "ignorada"]

RAZONES: dict[str, str] = {
    "VIA_LIBRE": "Las tres zonas estan confirmadas libres.",
    "PERCEPCION_NO_CONFIRMADA": "Aun no hay suficientes cuadros validos para confirmar el centro.",
    "CENTRO_POR_CONFIRMAR": "Obstaculo firme en el centro aun no confirmado: se reduce velocidad.",
    "CENTRO_DEBIL": "Deteccion debil en el centro: se reduce velocidad sin detener.",
    "LATERAL_OCUPADO": "Centro libre con un lateral ocupado: avance recto a precaucion.",
    "CENTRO_BLOQUEADO": "Obstaculo confirmado en el centro: STOP.",
    "CENTRO_HISTERESIS": "El centro sigue ocupado hasta completar los cuadros libres exigidos.",
    "SIN_ZONA_LIBRE": "Centro bloqueado y ningun lateral verificado libre: STOP.",
    "EVASION_IZQUIERDA": "Centro bloqueado; la zona izquierda esta verificada libre.",
    "EVASION_DERECHA": "Centro bloqueado; la zona derecha esta verificada libre.",
    "ERROR_PERCEPCION": "El detector reporto un error: STOP y se reinicia la confirmacion.",
    "SALIDA_MALFORMADA": "La salida del detector no cumple el contrato: STOP como fallo.",
    "CUADRO_FUERA_DE_ORDEN": "Cuadro con t_capture_ms no creciente: se rechaza con STOP.",
}


class _Inmutable(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Zona(_Inmutable):
    estado: EstadoZona = "DESCONOCIDA"
    racha_ocupada: int = 0
    racha_libre: int = 0


class Memoria(_Inmutable):
    """Lo unico que la politica recuerda entre cuadros."""

    estado: EstadoVia = "UNKNOWN"
    sequence_id: str | None = None
    ultimo_t_ms: float | None = None
    zonas: dict[NombreZona, Zona] = {z: Zona() for z in ZONAS}


class DeteccionEvaluada(_Inmutable):
    indice: int
    class_name: str
    confidence: float
    nivel: Nivel
    motivo: str | None
    zonas: tuple[NombreZona, ...]


class Decision(_Inmutable):
    """Salida B1 -> B2. velocidad en [0, 1] (fraccion de la maxima); direccion en
    [-1, 1] con negativo = izquierda. STOP siempre es (0, 0). El adaptador debe
    tratar el comando como STOP a partir de `valido_hasta_ms`."""

    sequence_id: str | None
    frame_id: str | None
    t_capture_ms: float | None
    estado_anterior: EstadoVia
    estado: EstadoVia
    cambio_estado: bool
    accion: Accion
    reason_code: str
    razon: str
    velocidad: float
    direccion: float
    valido_hasta_ms: float | None
    zonas: dict[NombreZona, Zona]
    detecciones: tuple[DeteccionEvaluada, ...]
    config_sha256: str | None
    error: str | None = None


def _zonas_de(det: Deteccion, cuadro: Cuadro, config: ConfigPolitica) -> tuple[NombreZona, ...]:
    x1, _, x2, _ = det.bbox_xyxy
    a, b = max(x1, 0) / cuadro.image_width, min(x2, cuadro.image_width) / cuadro.image_width
    cubiertas = []
    for nombre in ZONAS:
        ini, fin = getattr(config.zonas, nombre)
        solape = max(0.0, min(b, fin) - max(a, ini))
        dentro = a >= ini and b <= fin
        if solape > 0 and (dentro or solape >= config.geometria.cobertura_min_zona * (fin - ini)):
            cubiertas.append(nombre)
    return tuple(cubiertas)


def evaluar_deteccion(
    indice: int, det: Deteccion, cuadro: Cuadro, config: ConfigPolitica
) -> DeteccionEvaluada:
    x1, y1, x2, y2 = det.bbox_xyxy
    area = (x2 - x1) * (y2 - y1) / (cuadro.image_width * cuadro.image_height)
    motivo: str | None = None
    if det.class_name not in config.clases_obstaculo:
        motivo = "clase_no_obstaculo"
    elif det.confidence < config.confianza.umbral_bajo:
        motivo = "bajo_umbral"
    elif y2 / cuadro.image_height < config.geometria.banda_riesgo_y_min:
        motivo = "fuera_de_banda"
    elif area < config.geometria.area_min:
        motivo = "area_pequena"
    if motivo is not None:
        nivel: Nivel = "ignorada"
    else:
        nivel = "firme" if det.confidence >= config.confianza.umbral_alto else "debil"
    return DeteccionEvaluada(
        indice=indice,
        class_name=det.class_name,
        confidence=det.confidence,
        nivel=nivel,
        motivo=motivo,
        zonas=_zonas_de(det, cuadro, config),
    )


def _actualizar_zona(zona: Zona, firme: bool, debil: bool, config: ConfigPolitica) -> Zona:
    t = config.temporal
    if firme:
        racha = zona.racha_ocupada + 1
        estado = "OCUPADA" if racha >= t.cuadros_para_bloquear else zona.estado
        return Zona(estado=estado, racha_ocupada=racha, racha_libre=0)
    if debil:
        return Zona(estado=zona.estado, racha_ocupada=0, racha_libre=0)
    racha = zona.racha_libre + 1
    estado = "LIBRE" if racha >= t.cuadros_para_liberar else zona.estado
    return Zona(estado=estado, racha_ocupada=0, racha_libre=racha)


def _stop(
    memoria: Memoria,
    estado: EstadoVia,
    reason_code: str,
    *,
    sequence_id: str | None,
    frame_id: str | None,
    t_ms: float | None,
    config_sha256: str | None,
    zonas: dict[NombreZona, Zona] | None = None,
    detecciones: tuple[DeteccionEvaluada, ...] = (),
    error: str | None = None,
) -> Decision:
    return Decision(
        sequence_id=sequence_id,
        frame_id=frame_id,
        t_capture_ms=t_ms,
        estado_anterior=memoria.estado,
        estado=estado,
        cambio_estado=estado != memoria.estado,
        accion="STOP",
        reason_code=reason_code,
        razon=RAZONES[reason_code],
        velocidad=0.0,
        direccion=0.0,
        # STOP no vence: es el estado seguro aunque no llegue otro cuadro.
        valido_hasta_ms=None,
        zonas=zonas if zonas is not None else memoria.zonas,
        detecciones=detecciones,
        config_sha256=config_sha256,
        error=error,
    )


def paso(
    config: ConfigPolitica,
    memoria: Memoria,
    cuadro: Cuadro,
    config_sha256: str | None = None,
) -> tuple[Memoria, Decision]:
    """Decide un cuadro. Devuelve la memoria nueva y la decision; no muta nada."""
    ids = {
        "sequence_id": cuadro.sequence_id,
        "frame_id": cuadro.frame_id,
        "t_ms": cuadro.t_capture_ms,
        "config_sha256": config_sha256,
    }
    if cuadro.sequence_id != memoria.sequence_id:
        # Secuencia nueva: nada de lo recordado vale para esta camara/recorrido.
        memoria = Memoria(estado=memoria.estado, sequence_id=cuadro.sequence_id)
    elif memoria.ultimo_t_ms is not None and cuadro.t_capture_ms <= memoria.ultimo_t_ms:
        return memoria, _stop(memoria, memoria.estado, "CUADRO_FUERA_DE_ORDEN", **ids)

    if cuadro.status == "error":
        nueva = Memoria(
            estado="FAULT", sequence_id=cuadro.sequence_id, ultimo_t_ms=cuadro.t_capture_ms
        )
        decision = _stop(
            memoria, "FAULT", "ERROR_PERCEPCION", zonas=nueva.zonas, error=cuadro.error, **ids
        )
        return nueva, decision

    evaluadas = tuple(
        evaluar_deteccion(i, d, cuadro, config) for i, d in enumerate(cuadro.detections)
    )
    firmes = {z for e in evaluadas if e.nivel == "firme" for z in e.zonas}
    debiles = {z for e in evaluadas if e.nivel == "debil" for z in e.zonas}
    zonas = {
        z: _actualizar_zona(memoria.zonas[z], z in firmes, z in debiles, config) for z in ZONAS
    }
    centro = zonas["centro"]
    cmd = config.comandos

    accion: Accion
    if centro.estado == "DESCONOCIDA":
        estado, accion, codigo, velocidad, direccion = (
            "UNKNOWN",
            "STOP",
            "PERCEPCION_NO_CONFIRMADA",
            0.0,
            0.0,
        )
    elif centro.estado == "OCUPADA":
        estado = "BLOCKED"
        libres = [
            z
            for z in ("izquierda", "derecha")
            if zonas[z].estado == "LIBRE"
            and zonas[z].racha_libre >= config.temporal.cuadros_para_liberar
        ]
        if config.evasion.habilitada and libres:
            lado = config.evasion.lado_preferido if len(libres) == 2 else libres[0]
            signo = -1.0 if lado == "izquierda" else 1.0
            accion = "EVADE_LEFT" if lado == "izquierda" else "EVADE_RIGHT"
            codigo = "EVASION_IZQUIERDA" if lado == "izquierda" else "EVASION_DERECHA"
            velocidad, direccion = cmd.velocidad_evasion, signo * cmd.direccion_evasion
        else:
            accion, velocidad, direccion = "STOP", 0.0, 0.0
            if "centro" not in firmes:
                codigo = "CENTRO_HISTERESIS"
            elif config.evasion.habilitada:
                codigo = "SIN_ZONA_LIBRE"
            else:
                codigo = "CENTRO_BLOQUEADO"
    else:
        lateral_no_libre = any(
            zonas[z].estado != "LIBRE" or z in firmes or z in debiles
            for z in ("izquierda", "derecha")
        )
        if "centro" in firmes:
            estado, accion, codigo = "CAUTION", "SLOW", "CENTRO_POR_CONFIRMAR"
        elif "centro" in debiles:
            estado, accion, codigo = "CAUTION", "SLOW", "CENTRO_DEBIL"
        elif lateral_no_libre:
            estado, accion, codigo = "CAUTION", "SLOW", "LATERAL_OCUPADO"
        else:
            estado, accion, codigo = "CLEAR", "FORWARD", "VIA_LIBRE"
        velocidad = cmd.velocidad_crucero if accion == "FORWARD" else cmd.velocidad_precaucion
        direccion = 0.0

    nueva = Memoria(
        estado=estado,
        sequence_id=cuadro.sequence_id,
        ultimo_t_ms=cuadro.t_capture_ms,
        zonas=zonas,
    )
    decision = Decision(
        sequence_id=cuadro.sequence_id,
        frame_id=cuadro.frame_id,
        t_capture_ms=cuadro.t_capture_ms,
        estado_anterior=memoria.estado,
        estado=estado,
        cambio_estado=estado != memoria.estado,
        accion=accion,
        reason_code=codigo,
        razon=RAZONES[codigo],
        velocidad=velocidad,
        direccion=direccion,
        valido_hasta_ms=(
            None if accion == "STOP" else cuadro.t_capture_ms + config.temporal.vigencia_comando_ms
        ),
        zonas=zonas,
        detecciones=evaluadas,
        config_sha256=config_sha256,
    )
    return nueva, decision


class PoliticaDecision:
    """Envoltura con estado de `paso`: un objeto por recorrido o por auto."""

    def __init__(self, config: ConfigPolitica, config_sha256: str | None = None) -> None:
        self.config = config
        self.config_sha256 = config_sha256
        self.memoria = Memoria()

    def decidir(self, cuadro: Cuadro) -> Decision:
        self.memoria, decision = paso(self.config, self.memoria, cuadro, self.config_sha256)
        return decision

    def decidir_crudo(self, datos: object) -> Decision:
        """Valida la salida del detector; si no cumple el contrato es un FALLO, no via libre."""
        try:
            cuadro = Cuadro.model_validate(datos)
        except ValidationError as exc:
            campos = datos if isinstance(datos, dict) else {}
            seq = campos.get("sequence_id")
            nueva = Memoria(
                estado="FAULT",
                sequence_id=str(seq) if seq is not None else self.memoria.sequence_id,
                ultimo_t_ms=self.memoria.ultimo_t_ms,
            )
            frame = campos.get("frame_id")
            decision = _stop(
                self.memoria,
                "FAULT",
                "SALIDA_MALFORMADA",
                sequence_id=nueva.sequence_id,
                frame_id=str(frame) if frame is not None else None,
                t_ms=None,
                config_sha256=self.config_sha256,
                zonas=nueva.zonas,
                error=f"{exc.error_count()} error(es) de validacion: {exc.errors()[0]['msg']}",
            )
            self.memoria = nueva
            return decision
        return self.decidir(cuadro)
