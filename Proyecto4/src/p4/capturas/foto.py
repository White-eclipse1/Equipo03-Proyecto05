"""Fotografia recibida: JPEG real, con tope de tamano y de pixeles, SHA-256 y dimensiones."""

from __future__ import annotations

import hashlib
import io
import warnings
from dataclasses import dataclass

from PIL import Image, UnidentifiedImageError

from p4.capturas.errores import CapturaError

INICIO_JPEG = b"\xff\xd8\xff"
# Una camara de 12 MP da ~12 millones de pixeles; 40 M deja margen y corta los JPEG
# "bomba" (un archivo de pocos bytes que declara 65000x65000) antes de decodificar.
MAX_PIXELES = 40_000_000


@dataclass(frozen=True)
class Foto:
    datos: bytes
    sha256: str
    ancho: int
    alto: int

    @property
    def bytes(self) -> int:
        return len(self.datos)


def _no_soportada(motivo: str) -> CapturaError:
    # 415: un error del envio, no del servidor; el dispositivo no lo reintenta.
    return CapturaError(415, "foto_no_soportada", motivo)


def inspeccionar_foto(datos: bytes, max_bytes: int) -> Foto:
    """Bytes de la parte `foto` -> `Foto`. 413 si pesa demasiado; 415 si no es un JPEG valido."""
    if len(datos) > max_bytes:
        raise CapturaError(
            413,
            "foto_demasiado_grande",
            f"La foto pesa {len(datos)} bytes; el maximo es {max_bytes}",
        )
    if not datos.startswith(INICIO_JPEG):
        raise _no_soportada("La foto debe ser JPEG")
    try:
        with warnings.catch_warnings():
            # Pillow solo AVISA entre 1x y 2x de su limite de pixeles: aqui es un rechazo.
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(datos)) as imagen:
                ancho, alto = imagen.size
                if ancho * alto > MAX_PIXELES:
                    raise _no_soportada(
                        f"La foto declara {ancho}x{alto} px; el maximo es {MAX_PIXELES} pixeles"
                    )
                imagen.verify()
    except (
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
        UnidentifiedImageError,
        OSError,
        SyntaxError,
        ValueError,
    ) as error:
        raise _no_soportada(f"La foto no es un JPEG valido: {error}") from error
    return Foto(datos, hashlib.sha256(datos).hexdigest(), ancho, alto)
