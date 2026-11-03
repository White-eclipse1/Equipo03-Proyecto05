"""Metricas de clasificacion para la evaluacion final (F6 T15-T16, criterios 4.2-4.4).

Implementadas a mano, sin scikit-learn, para que el evaluador pueda seguir cada
cuenta: la matriz tiene filas = clase real y columnas = clase predicha, e
incluye todas las clases aunque alguna no tenga ejemplos; la accuracy es
`aciertos / total` sin redondear (el umbral de 0.85 se compara con el valor
exacto); una clase nunca predicha tiene precision 0 en lugar de dividir entre 0.

Logica pura: listas de etiquetas de entrada, numeros de salida.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from typing import Any


def _check(y_true: Sequence[str], y_pred: Sequence[str]) -> None:
    if len(y_true) != len(y_pred):
        raise ValueError(
            f"y_true y y_pred tienen distinta longitud ({len(y_true)} y {len(y_pred)})."
        )
    if not y_true:
        raise ValueError("No hay predicciones que evaluar.")


def confusion_matrix(
    y_true: Sequence[str], y_pred: Sequence[str], labels: Sequence[str]
) -> list[list[int]]:
    """`matrix[i][j]` = recortes de clase real `labels[i]` predichos como `labels[j]`."""
    _check(y_true, y_pred)
    index = {label: i for i, label in enumerate(labels)}
    unknown = sorted((set(y_true) | set(y_pred)) - set(index))
    if unknown:
        raise ValueError(f"Etiquetas fuera de {list(labels)}: {unknown}")
    matrix = [[0] * len(labels) for _ in labels]
    for true, pred in zip(y_true, y_pred, strict=True):
        matrix[index[true]][index[pred]] += 1
    return matrix


def accuracy(y_true: Sequence[str], y_pred: Sequence[str]) -> float:
    """`aciertos / total`, sin redondear."""
    _check(y_true, y_pred)
    return sum(t == p for t, p in zip(y_true, y_pred, strict=True)) / len(y_true)


def classification_report(
    y_true: Sequence[str], y_pred: Sequence[str], labels: Sequence[str]
) -> dict[str, Any]:
    """Accuracy, F1 macro y precision/recall/F1/support por clase, en el orden de `labels`."""
    matrix = confusion_matrix(y_true, y_pred, labels)
    per_class = []
    for i, label in enumerate(labels):
        true_positive = matrix[i][i]
        predicted = sum(row[i] for row in matrix)
        support = sum(matrix[i])
        precision = true_positive / predicted if predicted else 0.0
        recall = true_positive / support if support else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        per_class.append(
            {
                "class": label,
                "precision": precision,
                "recall": recall,
                "f1": f1,
                "support": support,
            }
        )
    return {
        "total": len(y_true),
        "accuracy": accuracy(y_true, y_pred),
        "f1_macro": sum(row["f1"] for row in per_class) / len(per_class),
        "per_class": per_class,
        "confusion_matrix": {"labels": list(labels), "rows_true_cols_pred": matrix},
    }


def majority_baseline(y_true: Sequence[str]) -> dict[str, Any]:
    """Accuracy de contestar siempre la clase mas frecuente del MISMO conjunto.

    Empate: la primera en orden alfabetico, para que el resultado no dependa
    del orden de las filas.
    """
    if not y_true:
        raise ValueError("No hay etiquetas para calcular el baseline.")
    counts = Counter(y_true)
    label = min(counts, key=lambda name: (-counts[name], name))
    return {"class": label, "accuracy": counts[label] / len(y_true)}


def most_confused_pair(
    y_true: Sequence[str], y_pred: Sequence[str], labels: Sequence[str]
) -> dict[str, Any] | None:
    """El par real -> predicho con mas errores (fuera de la diagonal), o `None`.

    Empate: el primer par en orden alfabetico (real, predicho).
    """
    matrix = confusion_matrix(y_true, y_pred, labels)
    errors = [
        (matrix[i][j], true, pred)
        for i, true in enumerate(labels)
        for j, pred in enumerate(labels)
        if i != j and matrix[i][j] > 0
    ]
    if not errors:
        return None
    count, true, pred = min(errors, key=lambda e: (-e[0], e[1], e[2]))
    return {"true": true, "predicted": pred, "count": count}
