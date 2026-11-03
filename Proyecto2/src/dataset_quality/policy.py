"""Reescritura de `quality.yaml` conservando lo que no se toca.

La pantalla de Settings tiene que poder cambiar un umbral y que el cambio se
note en la siguiente corrida de la compuerta. Lo obvio seria `yaml.safe_dump`
del modelo entero, y es justo lo que no se puede hacer: `quality.yaml` no es
solo datos. Sus comentarios explican por que `min_images` son 300 y no 50, por
que `degenerate_boxes` tolera cero y que significa cada `severity`. Un
`safe_dump` los borra todos en el primer guardado, y el archivo versionado en
Git pasa de documentar una politica a ser una lista de numeros sueltos.

Asi que en vez de reescribir el archivo se editan las lineas que cambian:
mismo orden, mismos comentarios, mismo espaciado, y en el diff de Git se ve
exactamente que umbral se movio y a que valor.

La garantia de que esto es seguro no esta en la edicion de texto sino en el
paso siguiente: lo escrito se vuelve a leer y a validar contra `QualityConfig`,
y si no coincide con la politica pedida, no se guarda nada.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from dataset_quality.models.quality import QualityConfig

# Raiz del repositorio: src/dataset_quality/policy.py -> ../../..
REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = REPO_ROOT / "quality.yaml"

# `clave: valor` con la sangria que la situa en el arbol. Lo que no encaja
# aqui — comentarios, lineas en blanco, elementos de lista — se copia tal cual.
CLAVE = re.compile(r"^(?P<sangria>[ ]*)(?P<clave>[A-Za-z_][\w-]*):(?P<resto>.*)$")

# Un comentario al final de la linea empieza por `#` precedido de espacio.
COMENTARIO = re.compile(r"(?=\s#)")

Ruta = tuple[str, ...]


class PolicyWriteError(RuntimeError):
    """El archivo no se puede editar sin riesgo de dejarlo incoherente."""


def flatten(data: Mapping[str, Any], prefijo: Ruta = ()) -> dict[Ruta, Any]:
    """Aplana un dict anidado a `("splits", "ratios", "train") -> 0.7`."""
    plano: dict[Ruta, Any] = {}
    for clave, valor in data.items():
        ruta = (*prefijo, str(clave))
        if isinstance(valor, Mapping):
            plano.update(flatten(valor, ruta))
        else:
            plano[ruta] = valor
    return plano


def diff(actual: Mapping[str, Any], nueva: Mapping[str, Any]) -> dict[Ruta, Any]:
    """Escalares que cambian de valor. Solo se tocan las lineas que hace falta."""
    antes, despues = flatten(actual), flatten(nueva)
    desconocidas = sorted(".".join(ruta) for ruta in set(despues) - set(antes))
    if desconocidas:
        raise PolicyWriteError(f"La politica nueva trae claves que no existen: {desconocidas}")
    return {ruta: valor for ruta, valor in despues.items() if antes[ruta] != valor}


def render(valor: Any) -> str:
    """Valor escalar tal como se escribe en YAML."""
    if isinstance(valor, bool):
        return "true" if valor else "false"
    if isinstance(valor, int):
        return str(valor)
    if isinstance(valor, float):
        # `repr` da la representacion mas corta que vuelve al mismo float, y
        # fuerza el punto decimal: `20.0` no puede quedar escrito como `20` o
        # dejaria de ser un float al releerlo.
        return repr(valor)
    return str(valor)


def apply_updates(texto: str, updates: Mapping[Ruta, Any]) -> str:
    """Sustituye el valor de cada ruta dejando intacto el resto del archivo.

    Recorre las lineas llevando la pila de claves abiertas por sangria, que es
    lo que permite distinguir `duplicates.max_ratio` de `small_objects.max_ratio`
    sin parsear el YAML entero (parsearlo devolveria un dict sin comentarios,
    que es exactamente lo que hay que conservar).
    """
    if not updates:
        return texto

    lineas = texto.splitlines(keepends=True)
    pendientes = set(updates)
    pila: list[tuple[int, str]] = []

    for indice, linea in enumerate(lineas):
        encaje = CLAVE.match(linea)
        if encaje is None:
            continue

        sangria = len(encaje["sangria"])
        while pila and pila[-1][0] >= sangria:
            pila.pop()
        pila.append((sangria, encaje["clave"]))

        ruta = tuple(clave for _, clave in pila)
        if ruta not in pendientes:
            continue

        resto = encaje["resto"]
        # Una clave sin valor abre una seccion; sustituirla se llevaria por
        # delante todo lo que cuelga de ella.
        if not resto.strip() or resto.lstrip().startswith("#"):
            raise PolicyWriteError(
                f"`{'.'.join(ruta)}` no es un valor escalar en quality.yaml: no se reescribe."
            )

        salto = linea[len(linea.rstrip("\r\n")) :]
        partes = COMENTARIO.split(resto.rstrip("\r\n"), maxsplit=1)
        comentario = partes[1] if len(partes) > 1 else ""
        lineas[indice] = (
            f"{encaje['sangria']}{encaje['clave']}: {render(updates[ruta])}{comentario}{salto}"
        )
        pendientes.discard(ruta)

    if pendientes:
        faltan = sorted(".".join(ruta) for ruta in pendientes)
        raise PolicyWriteError(
            f"quality.yaml no declara estas claves, asi que no se pueden editar desde la app: "
            f"{faltan}. Anadelas al archivo y vuelve a intentarlo."
        )
    return "".join(lineas)


def save(nueva: QualityConfig, path: Path = CONFIG_PATH) -> list[str]:
    """Persiste la politica y devuelve las rutas que cambiaron, en orden.

    El guardado es atomico y solo ocurre si el texto reescrito vuelve a leerse
    como la politica pedida: una edicion de texto que no produce exactamente el
    modelo que pidio quien llamo no se escribe, se rechaza.
    """
    texto = path.read_text(encoding="utf-8")
    actual = QualityConfig.from_yaml(path)

    cambios = diff(actual.model_dump(), nueva.model_dump())
    if not cambios:
        return []

    reescrito = apply_updates(texto, cambios)

    temporal = path.with_suffix(f"{path.suffix}.tmp")
    temporal.write_text(reescrito, encoding="utf-8")
    try:
        releida = QualityConfig.from_yaml(temporal)
        if releida != nueva:
            raise PolicyWriteError(
                "La reescritura de quality.yaml no produjo la politica pedida; no se guardo nada."
            )
        os.replace(temporal, path)
    finally:
        temporal.unlink(missing_ok=True)

    return sorted(".".join(ruta) for ruta in cambios)
