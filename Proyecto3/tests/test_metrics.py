"""Metricas de la evaluacion final en test (F6 T15-T16, criterios 4.2-4.4).

Todos los valores esperados estan calculados a mano sobre un caso pequeno, para
no depender de una libreria que calcule lo mismo que el codigo que se prueba.

Caso de referencia (9 recortes, clases cat/dog/person):

    real \\ pred   cat  dog  person
    cat            2    1     0        (3)
    dog            0    3     1        (4)
    person         0    0     2        (2)

accuracy = 7/9. cat: P=2/2, R=2/3. dog: P=3/4, R=3/4. person: P=2/3, R=2/2.
"""

from __future__ import annotations

from fractions import Fraction

import pytest

from p3.eval.metrics import (
    accuracy,
    classification_report,
    confusion_matrix,
    majority_baseline,
    most_confused_pair,
)

LABELS = ("cat", "dog", "person")
Y_TRUE = ["cat", "cat", "cat", "dog", "dog", "dog", "dog", "person", "person"]
Y_PRED = ["cat", "cat", "dog", "dog", "dog", "dog", "person", "person", "person"]


def _f1(p: Fraction, r: Fraction) -> float:
    return float(2 * p * r / (p + r))


def test_matriz_con_filas_reales_y_columnas_predichas() -> None:
    assert confusion_matrix(Y_TRUE, Y_PRED, LABELS) == [[2, 1, 0], [0, 3, 1], [0, 0, 2]]


def test_la_matriz_suma_el_total_y_no_es_simetrica_por_accidente() -> None:
    matrix = confusion_matrix(Y_TRUE, Y_PRED, LABELS)
    assert sum(map(sum, matrix)) == len(Y_TRUE)
    # Transpuesta distinta: cambiar filas por columnas es un error detectable.
    assert matrix != [list(col) for col in zip(*matrix, strict=True)]


def test_la_matriz_incluye_clases_sin_ningun_ejemplo() -> None:
    assert confusion_matrix(["cat"], ["cat"], LABELS) == [[1, 0, 0], [0, 0, 0], [0, 0, 0]]


def test_etiqueta_desconocida_es_un_error() -> None:
    with pytest.raises(ValueError, match="bird"):
        confusion_matrix(["cat"], ["bird"], LABELS)


def test_accuracy_exacta_sin_redondear() -> None:
    assert accuracy(Y_TRUE, Y_PRED) == 7 / 9
    # Justo en el umbral: 17/20 = 0.85 exacto no debe redondearse hacia abajo ni arriba.
    assert accuracy(["a"] * 20, ["a"] * 17 + ["b"] * 3) == 0.85


def test_reporte_por_clase_precision_recall_f1_y_support() -> None:
    report = classification_report(Y_TRUE, Y_PRED, LABELS)
    per_class = {row["class"]: row for row in report["per_class"]}
    esperado = {
        "cat": (Fraction(2, 2), Fraction(2, 3), 3),
        "dog": (Fraction(3, 4), Fraction(3, 4), 4),
        "person": (Fraction(2, 3), Fraction(2, 2), 2),
    }
    for clase, (p, r, support) in esperado.items():
        row = per_class[clase]
        assert row["precision"] == pytest.approx(float(p))
        assert row["recall"] == pytest.approx(float(r))
        assert row["f1"] == pytest.approx(_f1(p, r))
        assert row["support"] == support
    assert [row["class"] for row in report["per_class"]] == list(LABELS)


def test_f1_macro_es_el_promedio_simple_de_los_f1() -> None:
    report = classification_report(Y_TRUE, Y_PRED, LABELS)
    f1s = [
        _f1(Fraction(1), Fraction(2, 3)),
        _f1(Fraction(3, 4), Fraction(3, 4)),
        _f1(Fraction(2, 3), Fraction(1)),
    ]
    assert report["f1_macro"] == pytest.approx(sum(f1s) / 3)
    assert report["accuracy"] == 7 / 9
    assert report["total"] == 9


def test_clase_nunca_predicha_tiene_precision_cero_sin_dividir_entre_cero() -> None:
    report = classification_report(["cat", "dog"], ["cat", "cat"], ("cat", "dog"))
    dog = next(row for row in report["per_class"] if row["class"] == "dog")
    assert dog["precision"] == 0.0
    assert dog["recall"] == 0.0
    assert dog["f1"] == 0.0


def test_baseline_de_clase_mayoritaria_sobre_el_mismo_test() -> None:
    baseline = majority_baseline(Y_TRUE)
    assert baseline == {"class": "dog", "accuracy": 4 / 9}


def test_baseline_con_empate_elige_por_orden_alfabetico() -> None:
    assert majority_baseline(["person", "cat", "cat", "person"]) == {
        "class": "cat",
        "accuracy": 0.5,
    }


def test_par_mas_confundido_ignora_la_diagonal() -> None:
    y_true = ["cat"] * 5 + ["dog"] * 3
    y_pred = ["cat"] * 3 + ["dog"] * 2 + ["cat", "dog", "dog"]
    assert most_confused_pair(y_true, y_pred, ("cat", "dog")) == {
        "true": "cat",
        "predicted": "dog",
        "count": 2,
    }


def test_par_mas_confundido_sin_errores_es_none() -> None:
    assert most_confused_pair(["cat", "dog"], ["cat", "dog"], ("cat", "dog")) is None


def test_longitudes_distintas_son_un_error() -> None:
    with pytest.raises(ValueError, match="longitud"):
        accuracy(["cat"], ["cat", "dog"])
