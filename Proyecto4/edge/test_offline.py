"""Comprueba una única carga previa al corte y misma sesión en las tres capturas."""

import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import offline


class OfflineTests(unittest.TestCase):
    def test_modelo_cargado_antes_del_corte_y_reutilizado(self):
        modelo = Mock()
        modelo.metadatos = {"estado": "modelo_cargado"}
        respuestas = iter(["", "cat", "", "dog", "", "", "person", ""])

        def entrada(mensaje):
            constructor.assert_called_once()
            return next(respuestas)

        with tempfile.TemporaryDirectory() as temporal:
            salida = Path(temporal)
            with patch.object(offline, "Modelo", return_value=modelo) as constructor:
                with patch("builtins.input", side_effect=entrada), patch("sys.stdout", io.StringIO()):
                    with patch.object(offline, "capturar", return_value={"image_ref": "foto.jpg"}) as captura:
                        with patch.object(offline, "procesar", return_value={"estado": "inferencia_local"}) as proceso:
                            self.assertEqual(offline.ejecutar(Path("modelo"), "http://camara/shot.jpg", salida), 0)
            self.assertEqual(captura.call_count, 3)
            self.assertEqual(proceso.call_count, 3)
            for llamada in proceso.call_args_list:
                self.assertIs(llamada.args[0], modelo)
            registros = [json.loads(x) for x in (salida / "offline.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertEqual(registros[0]["estado"], "modelo_cargado")
            self.assertEqual(len({r["session_id"] for r in registros}), 1)
            resultados = [r for r in registros if r["estado"] == "inferencia_local"]
            self.assertEqual([r["fase"] for r in resultados], ["sin_internet", "sin_internet", "reconectado"])
