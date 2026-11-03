"""`/api/p4/capturas`: recepcion del dispositivo y consulta para Capturas Edge.

`POST` multipart con dos partes, `evento` (JSON del contrato) y `foto` (JPEG), y
`Authorization: Bearer <P4_TOKEN_DISPOSITIVO>`. Respuestas:

- 201 `creado` / 200 `duplicado` (mismo ID, mismos datos: no se escribe nada);
- 409 `conflicto_capture_id` (mismo ID con otros datos: no se sobrescribe);
- 400/413/415/422 el envio esta mal: se corrige, no se reintenta;
- 401 token ausente o incorrecto;
- 503 almacen o receptor no disponibles: se reintenta con el MISMO evento.

Las lecturas (`GET`) no piden token: en el despliegue las protege el acceso al
portal, igual que al resto de sus paginas.
"""

from __future__ import annotations

import hmac
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError
from fastapi import APIRouter, Depends, Path, Query, Request
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile
from starlette.exceptions import HTTPException
from starlette.formparsers import MultiPartException

from p4.capturas import exportar
from p4.capturas.almacen import (
    Almacen,
    AlmacenAusente,
    AlmacenMemoria,
    AlmacenNoDisponibleError,
    AlmacenS3,
    CapturaNoEncontradaError,
    ConflictoCapturaError,
    llave_registro,
)
from p4.capturas.config import ConfigCapturas, obtener_config
from p4.capturas.errores import CapturaError
from p4.capturas.evento import PATRON_ID, leer_evento, validar_evento
from p4.capturas.foto import inspeccionar_foto

router = APIRouter(prefix="/api/p4/capturas", tags=["p4-capturas"])

ConfigDep = Annotated[ConfigCapturas, Depends(obtener_config)]
IdCaptura = Annotated[str, Path(pattern=f"^{PATRON_ID.pattern}$")]

# Reloj del receptor; las pruebas lo sustituyen.
ahora: Callable[[], datetime] = lambda: datetime.now(UTC)  # noqa: E731

_almacenes: dict[tuple[Any, ...], Almacen] = {}
_candado = threading.Lock()


def _crear_almacen(config: ConfigCapturas) -> Almacen:
    if config.almacen == "memoria":
        return AlmacenMemoria(config.prefijo)
    if not config.bucket.strip():
        return AlmacenAusente("El receptor no tiene P4_BUCKET configurado")
    try:
        sesion = boto3.Session(profile_name=config.aws_profile)
        cliente = sesion.client(
            "s3",
            region_name=config.aws_region,
            endpoint_url=config.s3_endpoint,
            aws_access_key_id=config.s3_access_key,
            aws_secret_access_key=(
                config.s3_secret_key.get_secret_value() if config.s3_secret_key else None
            ),
            config=Config(
                retries={"max_attempts": 3, "mode": "standard"},
                # MinIO local solo entiende rutas `endpoint/bucket/llave`.
                s3={"addressing_style": "path" if config.s3_endpoint else "auto"},
            ),
        )
    except BotoCoreError as error:
        return AlmacenAusente(f"No se pudo crear el cliente de S3 ({type(error).__name__})")
    return AlmacenS3(cliente, config.bucket, config.prefijo)


def obtener_almacen(config: ConfigDep) -> Almacen:
    """Un almacen por configuracion. Uno que fallo se vuelve a intentar en la siguiente peticion."""
    llave = (config.almacen, config.bucket, config.prefijo, config.aws_profile, config.s3_endpoint)
    with _candado:
        if llave not in _almacenes:
            almacen = _crear_almacen(config)
            if isinstance(almacen, AlmacenAusente):
                return almacen
            _almacenes[llave] = almacen
        return _almacenes[llave]


AlmacenDep = Annotated[Almacen, Depends(obtener_almacen)]


def revisar_token(cabecera: str | None, config: ConfigCapturas) -> None:
    if config.token_dispositivo is None:
        raise CapturaError(
            503,
            "receptor_no_configurado",
            "El receptor no tiene P4_TOKEN_DISPOSITIVO configurado; no acepta envios",
        )
    esquema, _, token = (cabecera or "").partition(" ")
    esperado = config.token_dispositivo.get_secret_value()
    if esquema.lower() != "bearer" or not hmac.compare_digest(token.encode(), esperado.encode()):
        raise CapturaError(401, "no_autorizado", "Falta el token del dispositivo o no es valido")


def _evento_grande(maximo: int) -> CapturaError:
    return CapturaError(413, "evento_demasiado_grande", f"La parte 'evento' pasa de {maximo} bytes")


async def leer_partes(request: Request, config: ConfigCapturas) -> tuple[str, bytes]:
    """Partes `evento` y `foto` del multipart. 400 si falta alguna; 413 si `evento` es enorme."""
    try:
        formulario = await request.form(
            max_files=2, max_fields=2, max_part_size=config.max_evento_bytes
        )
    except (MultiPartException, HTTPException) as error:
        motivo = str(getattr(error, "message", None) or getattr(error, "detail", error))
        if "maximum size" in motivo:
            raise _evento_grande(config.max_evento_bytes) from error
        raise CapturaError(
            400, "solicitud_invalida", f"El cuerpo no es multipart valido: {motivo}"
        ) from error
    evento, foto = formulario.get("evento"), formulario.get("foto")
    if evento is None:
        raise CapturaError(400, "solicitud_invalida", "Falta la parte 'evento'")
    if foto is None:
        raise CapturaError(400, "solicitud_invalida", "Falta la parte 'foto'")
    if not isinstance(foto, UploadFile):
        raise CapturaError(400, "solicitud_invalida", "La parte 'foto' debe ser un archivo")
    # Un byte de mas basta para saber si pasa del tope sin cargar archivos enormes.
    datos = await foto.read(config.max_foto_bytes + 1)
    if isinstance(evento, UploadFile):
        crudo = await evento.read(config.max_evento_bytes + 1)
        if len(crudo) > config.max_evento_bytes:
            raise _evento_grande(config.max_evento_bytes)
        evento = crudo.decode("utf-8", errors="replace")
    return evento, datos


@router.post("", status_code=201)
async def recibir_captura(request: Request, config: ConfigDep, almacen: AlmacenDep) -> JSONResponse:
    try:
        revisar_token(request.headers.get("authorization"), config)
        texto, datos = await leer_partes(request, config)
        foto = inspeccionar_foto(datos, config.max_foto_bytes)
        evento = leer_evento(texto)
        validar_evento(evento, foto, config)
        guardado = await run_in_threadpool(almacen.guardar, evento, foto, ahora())
    except CapturaError as error:
        return error.respuesta()
    except ConflictoCapturaError as error:
        return CapturaError(
            409,
            "conflicto_capture_id",
            "El capture_id ya existe con otros datos; no se sobrescribe",
            error.diferencias,
        ).respuesta()
    except AlmacenNoDisponibleError as error:
        return CapturaError(503, "almacen_no_disponible", str(error)).respuesta()

    registro = guardado.registro
    return JSONResponse(
        status_code=201 if guardado.estado == "creado" else 200,
        content={
            "estado": guardado.estado,
            "capture_id": registro["capture_id"],
            "image_key": registro["image_key"],
            "record_key": llave_registro(config.prefijo, registro["capture_id"]),
            "received_at": registro["received_at"],
        },
    )


async def _leer(funcion: Callable[..., Any], *argumentos: Any) -> Any:
    """Corre una lectura del almacen y traduce sus fallas al formato de error."""
    try:
        return await run_in_threadpool(funcion, *argumentos)
    except CapturaNoEncontradaError as error:
        raise CapturaError(404, "captura_no_encontrada", f"No existe la captura {error}") from error
    except AlmacenNoDisponibleError as error:
        raise CapturaError(503, "almacen_no_disponible", str(error)) from error


@router.get("")
async def listar_capturas(
    almacen: AlmacenDep, limite: Annotated[int, Query(ge=1, le=1000)] = 200
) -> JSONResponse:
    """Capturas de mas reciente a mas antigua (`captured_at` en UTC)."""
    try:
        registros, errores = await _leer(almacen.listar)
    except CapturaError as error:
        return error.respuesta()
    ordenados, sin_orden = exportar.ordenar(registros)
    errores = [*errores, *sin_orden]
    return JSONResponse({"items": ordenados[:limite], "total": len(ordenados), "errores": errores})


# Antes de `/{capture_id}`: "exportar" tambien cumple el patron de un ID.
@router.get("/exportar")
async def exportar_capturas(
    almacen: AlmacenDep, formato: Annotated[Literal["csv", "json"], Query()] = "json"
) -> Response:
    """Todos los eventos con los campos del contrato y los del receptor."""
    try:
        registros, errores = await _leer(almacen.listar)
    except CapturaError as error:
        return error.respuesta()
    momento = ahora()
    ordenados, sin_orden = exportar.ordenar(registros)
    errores = [*errores, *sin_orden]
    cabeceras = {
        "Content-Disposition": (
            f'attachment; filename="{exportar.nombre_archivo(momento, formato)}"'
        ),
        # Registros ilegibles: visibles tambien en CSV, donde no caben en el cuerpo.
        "X-Capturas-Con-Error": str(len(errores)),
    }
    if formato == "csv":
        return Response(exportar.a_csv(ordenados), media_type="text/csv", headers=cabeceras)
    return Response(
        exportar.a_json(ordenados, errores, momento),
        media_type="application/json",
        headers=cabeceras,
    )


@router.get("/{capture_id}")
async def obtener_captura(capture_id: IdCaptura, almacen: AlmacenDep) -> JSONResponse:
    try:
        return JSONResponse(await _leer(almacen.obtener, capture_id))
    except CapturaError as error:
        return error.respuesta()


@router.get("/{capture_id}/foto")
async def obtener_foto(capture_id: IdCaptura, almacen: AlmacenDep) -> Response:
    """La foto, leida del almacen por el servidor: el navegador no recibe URLs de S3."""
    try:
        datos = await _leer(almacen.foto, capture_id)
    except CapturaError as error:
        return error.respuesta()
    return Response(
        datos, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=300"}
    )
