"""Politica de decision del Proyecto 5 (rol B1): detecciones por cuadro -> decision de movimiento.

Logica pura: no lee `os.environ`, no abre camara, GPIO ni motores. La aplicacion y
el recorrido de evaluacion usan el MISMO `PoliticaDecision` (criterio 2.3).
"""
