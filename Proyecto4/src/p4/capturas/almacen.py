"""Donde viven las capturas: foto + registro por `capture_id`.

El `capture_id` es la clave de idempotencia:
- mismo ID, mismos campos y misma foto -> `duplicado`, sin escribir nada;
- mismo ID con otros datos -> `ConflictoCapturaError`, nunca se sobrescribe.

`AlmacenS3` lo garantiza con escrituras condicionales (`If-None-Match: *`): la
foto primero y despues el registro, asi un registro nunca apunta a una foto que
no existe y un reintento completa una escritura que fallo a la mitad.
`AlmacenMemoria` tiene la misma semantica, para pruebas y desarrollo sin S3.
"""

from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, Protocol

from botocore.exceptions import BotoCoreError, ClientError

from p4.capturas.evento import EventoCaptura
from p4.capturas.foto import Foto

Registro = dict[str, Any]


@dataclass(frozen=True)
class Guardado:
    estado: Literal["creado", "duplicado"]
    registro: Registro


class ConflictoCapturaError(Exception):
    """El `capture_id` ya existe con otros datos u otra foto."""

    def __init__(self, diferencias: list[dict[str, Any]]) -> None:
        super().__init__("el capture_id ya existe con otros datos")
        self.diferencias = diferencias


class CapturaNoEncontradaError(Exception):
    pass


class AlmacenNoDisponibleError(Exception):
    """El almacen no respondio o no esta configurado: el envio se puede reintentar."""


class Almacen(Protocol):
    def guardar(self, evento: EventoCaptura, foto: Foto, recibido: datetime) -> Guardado: ...
    def listar(self) -> tuple[list[Registro], list[dict[str, str]]]: ...
    def obtener(self, capture_id: str) -> Registro: ...
    def foto(self, capture_id: str) -> bytes: ...


class AlmacenAusente:
    """Almacen que no se pudo crear (sin bucket, perfil inexistente): todo responde 503."""

    def __init__(self, motivo: str) -> None:
        self.motivo = motivo

    def guardar(self, evento: EventoCaptura, foto: Foto, recibido: datetime) -> Guardado:
        raise AlmacenNoDisponibleError(self.motivo)

    def listar(self) -> tuple[list[Registro], list[dict[str, str]]]:
        raise AlmacenNoDisponibleError(self.motivo)

    def obtener(self, capture_id: str) -> Registro:
        raise AlmacenNoDisponibleError(self.motivo)

    def foto(self, capture_id: str) -> bytes:
        raise AlmacenNoDisponibleError(self.motivo)


def llave_foto(prefijo: str, capture_id: str) -> str:
    return f"{prefijo}fotos/{capture_id}.jpg"


def llave_registro(prefijo: str, capture_id: str) -> str:
    return f"{prefijo}eventos/{capture_id}.json"


def armar_registro(evento: EventoCaptura, foto: Foto, recibido: datetime, prefijo: str) -> Registro:
    """Campos del dispositivo + los que agrega el receptor."""
    return {
        **evento.campos(),
        "received_at": recibido.isoformat(timespec="milliseconds"),
        "image_key": llave_foto(prefijo, evento.capture_id),
        "image_bytes": foto.bytes,
        "image_width": foto.ancho,
        "image_height": foto.alto,
    }


def diferencias(guardado: Registro, evento: EventoCaptura) -> list[dict[str, Any]]:
    """Campos del dispositivo que no coinciden entre lo guardado y lo recibido."""
    recibido = evento.campos()
    return [
        {"campo": campo, "guardado": guardado.get(campo), "recibido": valor}
        for campo, valor in recibido.items()
        if guardado.get(campo) != valor
    ]


class AlmacenMemoria:
    """Mismo contrato que S3, en un diccionario. Se pierde al reiniciar el proceso."""

    def __init__(self, prefijo: str = "edge-capturas/") -> None:
        self.prefijo = prefijo
        self._registros: dict[str, Registro] = {}
        self._fotos: dict[str, bytes] = {}
        self._candado = threading.Lock()

    def guardar(self, evento: EventoCaptura, foto: Foto, recibido: datetime) -> Guardado:
        with self._candado:
            existente = self._registros.get(evento.capture_id)
            if existente is not None:
                distintos = diferencias(existente, evento)
                if distintos:
                    raise ConflictoCapturaError(distintos)
                return Guardado("duplicado", existente)
            registro = armar_registro(evento, foto, recibido, self.prefijo)
            self._fotos[evento.capture_id] = foto.datos
            self._registros[evento.capture_id] = registro
            return Guardado("creado", registro)

    def listar(self) -> tuple[list[Registro], list[dict[str, str]]]:
        with self._candado:
            return list(self._registros.values()), []

    def obtener(self, capture_id: str) -> Registro:
        try:
            return self._registros[capture_id]
        except KeyError as error:
            raise CapturaNoEncontradaError(capture_id) from error

    def foto(self, capture_id: str) -> bytes:
        try:
            return self._fotos[capture_id]
        except KeyError as error:
            raise CapturaNoEncontradaError(capture_id) from error


def _codigo(error: ClientError) -> str:
    return str(error.response.get("Error", {}).get("Code", ""))


def _status(error: ClientError) -> int:
    return int(error.response.get("ResponseMetadata", {}).get("HTTPStatusCode", 0))


def _ya_existe(error: ClientError) -> bool:
    return _codigo(error) == "PreconditionFailed" or _status(error) == 412


def _no_existe(error: ClientError) -> bool:
    return _codigo(error) in {"NoSuchKey", "404", "NotFound"} or _status(error) == 404


class AlmacenS3:
    """Capturas en un bucket S3 (AWS o MinIO).

    `{prefijo}fotos/{id}.jpg`   la foto tal como llego, con metadato `sha256`
    `{prefijo}eventos/{id}.json` el registro: evento + campos del receptor
    """

    def __init__(self, cliente: Any, bucket: str, prefijo: str) -> None:
        self.cliente = cliente
        self.bucket = bucket
        self.prefijo = prefijo

    def _falla(self, accion: str, error: Exception) -> AlmacenNoDisponibleError:
        detalle = _codigo(error) if isinstance(error, ClientError) else type(error).__name__
        return AlmacenNoDisponibleError(
            f"S3 fallo al {accion} ({detalle}); reintenta con el mismo ID"
        )

    def guardar(self, evento: EventoCaptura, foto: Foto, recibido: datetime) -> Guardado:
        cid = evento.capture_id
        try:
            self.cliente.put_object(
                Bucket=self.bucket,
                Key=llave_foto(self.prefijo, cid),
                Body=foto.datos,
                ContentType="image/jpeg",
                Metadata={"sha256": foto.sha256, "capture-id": cid},
                IfNoneMatch="*",
            )
        except ClientError as error:
            if not _ya_existe(error):
                raise self._falla("guardar la foto", error) from error
            self._misma_foto(evento, foto)
        except BotoCoreError as error:
            raise self._falla("guardar la foto", error) from error

        registro = armar_registro(evento, foto, recibido, self.prefijo)
        try:
            self.cliente.put_object(
                Bucket=self.bucket,
                Key=llave_registro(self.prefijo, cid),
                Body=json.dumps(registro, ensure_ascii=False).encode("utf-8"),
                ContentType="application/json",
                IfNoneMatch="*",
            )
        except ClientError as error:
            if not _ya_existe(error):
                raise self._falla("guardar el registro", error) from error
            existente = self.obtener(cid)
            distintos = diferencias(existente, evento)
            if distintos:
                raise ConflictoCapturaError(distintos) from error
            return Guardado("duplicado", existente)
        except BotoCoreError as error:
            raise self._falla("guardar el registro", error) from error
        return Guardado("creado", registro)

    def _misma_foto(self, evento: EventoCaptura, foto: Foto) -> None:
        """La foto ya existia (reintento o falla a la mitad): debe ser la misma."""
        try:
            cabecera = self.cliente.head_object(
                Bucket=self.bucket, Key=llave_foto(self.prefijo, evento.capture_id)
            )
        except (ClientError, BotoCoreError) as error:
            raise self._falla("leer la foto existente", error) from error
        guardado = cabecera.get("Metadata", {}).get("sha256")
        if guardado != foto.sha256:
            raise ConflictoCapturaError(
                [{"campo": "image_sha256", "guardado": guardado, "recibido": foto.sha256}]
            )

    def _leer(self, llave: str, capture_id: str) -> bytes:
        try:
            return self.cliente.get_object(Bucket=self.bucket, Key=llave)["Body"].read()
        except ClientError as error:
            if _no_existe(error):
                raise CapturaNoEncontradaError(capture_id) from error
            raise self._falla("leer", error) from error
        except BotoCoreError as error:
            raise self._falla("leer", error) from error

    def obtener(self, capture_id: str) -> Registro:
        return json.loads(self._leer(llave_registro(self.prefijo, capture_id), capture_id))

    def foto(self, capture_id: str) -> bytes:
        return self._leer(llave_foto(self.prefijo, capture_id), capture_id)

    def listar(self) -> tuple[list[Registro], list[dict[str, str]]]:
        """Todos los registros; los ilegibles van en la segunda lista, no se esconden."""
        prefijo = f"{self.prefijo}eventos/"
        try:
            paginas = self.cliente.get_paginator("list_objects_v2").paginate(
                Bucket=self.bucket, Prefix=prefijo
            )
            llaves = [o["Key"] for p in paginas for o in p.get("Contents", [])]
        except (ClientError, BotoCoreError) as error:
            raise self._falla("listar", error) from error

        def leer(llave: str) -> tuple[Registro | None, dict[str, str] | None]:
            try:
                cuerpo = self.cliente.get_object(Bucket=self.bucket, Key=llave)["Body"].read()
                registro = json.loads(cuerpo)
            except (ClientError, BotoCoreError, ValueError) as error:
                return None, {"llave": llave, "problema": f"{type(error).__name__}: {error}"}
            if not isinstance(registro, dict) or "capture_id" not in registro:
                return None, {"llave": llave, "problema": "el registro no tiene capture_id"}
            return registro, None

        with ThreadPoolExecutor(max_workers=8) as hilos:
            leidos = list(hilos.map(leer, llaves))
        registros = [r for r, _ in leidos if r is not None]
        errores = [e for _, e in leidos if e is not None]
        return registros, errores
