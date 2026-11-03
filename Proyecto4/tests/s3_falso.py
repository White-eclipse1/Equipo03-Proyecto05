"""S3 en memoria con la semantica que usa `AlmacenS3`: `If-None-Match: *` y metadatos.

No sustituye a `botocore.stub.Stubber` (que valida los parametros contra el modelo
real de S3, ver `test_almacen_s3.py`); sirve para probar secuencias: reintentos,
conflictos y fallas a la mitad.
"""

# ruff: noqa: N803 - los argumentos se llaman como los de boto3 (Bucket, Key, ...)

from __future__ import annotations

import io
from dataclasses import dataclass, field
from typing import Any

from botocore.exceptions import ClientError


def error_s3(codigo: str, status: int, operacion: str) -> ClientError:
    return ClientError(
        {
            "Error": {"Code": codigo, "Message": codigo},
            "ResponseMetadata": {"HTTPStatusCode": status},
        },
        operacion,
    )


@dataclass
class Objeto:
    cuerpo: bytes
    metadatos: dict[str, str]


@dataclass
class S3Falso:
    objetos: dict[str, Objeto] = field(default_factory=dict)
    escrituras: list[str] = field(default_factory=list)
    # Error a lanzar en la siguiente llamada de una operacion: {"put_object": ClientError}.
    fallar: dict[str, Exception] = field(default_factory=dict)
    # Error a lanzar en la siguiente escritura de una llave: simula fallas a la mitad.
    fallar_llave: dict[str, Exception] = field(default_factory=dict)
    por_pagina: int = 1000

    def _quiza_fallar(self, operacion: str) -> None:
        if operacion in self.fallar:
            raise self.fallar.pop(operacion)

    def put_object(self, *, Bucket, Key, Body, ContentType, Metadata=None, IfNoneMatch=None):
        self._quiza_fallar("put_object")
        if Key in self.fallar_llave:
            raise self.fallar_llave.pop(Key)
        if IfNoneMatch == "*" and Key in self.objetos:
            raise error_s3("PreconditionFailed", 412, "PutObject")
        self.objetos[Key] = Objeto(bytes(Body), dict(Metadata or {}))
        self.escrituras.append(Key)
        return {"VersionId": f"v{len(self.escrituras)}"}

    def _objeto(self, Key: str, operacion: str) -> Objeto:
        if Key not in self.objetos:
            raise error_s3("NoSuchKey", 404, operacion)
        return self.objetos[Key]

    def head_object(self, *, Bucket, Key):
        self._quiza_fallar("head_object")
        return {"Metadata": self._objeto(Key, "HeadObject").metadatos}

    def get_object(self, *, Bucket, Key):
        self._quiza_fallar("get_object")
        return {"Body": io.BytesIO(self._objeto(Key, "GetObject").cuerpo)}

    def get_paginator(self, nombre: str) -> Any:
        assert nombre == "list_objects_v2"
        s3 = self

        class Paginador:
            def paginate(self, *, Bucket, Prefix):
                s3._quiza_fallar("list_objects_v2")
                llaves = sorted(k for k in s3.objetos if k.startswith(Prefix))
                for inicio in range(0, max(len(llaves), 1), s3.por_pagina):
                    pagina = llaves[inicio : inicio + s3.por_pagina]
                    yield {"Contents": [{"Key": k} for k in pagina]} if pagina else {}

        return Paginador()
