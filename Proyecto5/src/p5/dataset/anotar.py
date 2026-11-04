"""Anotador local de cajas para el dataset de P5. Solo escucha en 127.0.0.1."""

import argparse
import json
import os
from functools import partial
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

from p5.dataset.captura import SEQUENCES_DIR
from p5.dataset.paquete import (
    ANNOTATIONS_FILE,
    BASE_ACTIONS,
    OBSTACLE_CLASSES,
    ZONES,
    annotation_errors,
    load_annotations,
    load_captures,
)

_MAX_BODY = 1_000_000

_PAGE = """<!doctype html>
<html lang="es"><head><meta charset="utf-8"><title>Anotador P5</title>
<style>
body{font:15px system-ui,sans-serif;margin:16px;color:#222;background:#fff}
#app{display:flex;gap:16px;flex-wrap:wrap;align-items:flex-start}
canvas{border:1px solid #888;cursor:crosshair;max-width:100%}
#side{width:300px}button,select{font:inherit;padding:4px 8px;margin:2px 2px 2px 0}
li{margin:4px 0}#msg{min-height:1.4em;margin:8px 0}.err{color:#b00020}.ok{color:#1b6e3c}
kbd{border:1px solid #aaa;border-radius:3px;padding:0 4px;font-size:12px}
</style></head><body>
<h3 id="title">Cargando</h3>
<div id="app"><canvas id="c"></canvas><div id="side">
<label>Clase de la siguiente caja<br><select id="cls"></select></label>
<ul id="boxes"></ul>
<label>Estado de la via<br><select id="state"></select></label>
<div id="msg"></div>
<button id="save">Guardar y seguir (Enter)</button><br>
<button id="prev">Anterior (A)</button><button id="next">Siguiente (D)</button>
<button id="copy">Copiar cajas del cuadro anterior (C)</button>
<button id="todo">Primer pendiente</button>
<p><small>Arrastra para dibujar. Etiqueta <b>todos</b> los objetos de estas clases, tambien
los de los lados y los lejanos. Sin objetos: deja la lista vacia y elige <i>libre</i>.
Teclas <kbd>1</kbd>-<kbd>5</kbd>: estado.</small></p>
</div></div>
<script>
const SCALE = 2, $ = id => document.getElementById(id);
const canvas = $("c"), ctx = canvas.getContext("2d"), image = new Image();
let frames = [], meta = {}, at = 0, boxes = [], drag = null;

const fill = (select, values) => values.forEach(value => {
  const option = document.createElement("option");
  option.value = option.textContent = value;
  select.append(option);
});
const message = (text, kind) => { $("msg").textContent = text; $("msg").className = kind || ""; };
const pending = () => frames.findIndex(f => !f.annotation);

function draw() {
  ctx.drawImage(image, 0, 0, canvas.width, canvas.height);
  ctx.setLineDash([6, 6]); ctx.strokeStyle = "#ffd400"; ctx.lineWidth = 1;
  meta.zones.forEach(x => {
    ctx.beginPath(); ctx.moveTo(x * canvas.width, 0);
    ctx.lineTo(x * canvas.width, canvas.height); ctx.stroke();
  });
  ctx.setLineDash([]); ctx.lineWidth = 2; ctx.font = "14px system-ui";
  const all = drag ? boxes.concat([drag]) : boxes;
  all.forEach(b => {
    const [x1, y1, x2, y2] = b.bbox_xyxy.map(v => v * SCALE);
    ctx.strokeStyle = "#00e5ff"; ctx.strokeRect(x1, y1, x2 - x1, y2 - y1);
    ctx.fillStyle = "#00e5ff"; ctx.fillText(b.class_name, x1 + 3, y1 + 15);
  });
}
function listBoxes() {
  $("boxes").replaceChildren(...boxes.map((b, i) => {
    const row = document.createElement("li"), del = document.createElement("button");
    row.textContent = b.class_name + " [" + b.bbox_xyxy.map(Math.round).join(", ") + "] ";
    del.textContent = "Quitar";
    del.onclick = () => { boxes.splice(i, 1); listBoxes(); draw(); };
    row.append(del);
    return row;
  }));
}
function show(index) {
  if (index < 0 || index >= frames.length) return;
  at = index;
  const f = frames[at], done = frames.filter(x => x.annotation).length;
  boxes = f.annotation ? structuredClone(f.annotation.objects) : [];
  $("state").value = f.annotation ? f.annotation.road_state : "libre";
  $("title").textContent = f.frame_id + "  (" + (at + 1) + "/" + frames.length + ", "
    + done + " anotados)  " + (f.annotation ? "anotado" : "pendiente");
  image.onload = () => {
    canvas.width = f.image_width * SCALE; canvas.height = f.image_height * SCALE;
    draw();
  };
  image.src = "/img/" + f.sequence_id + "/" + f.file;
  listBoxes(); message("");
}
async function save() {
  const f = frames[at], body = {frame_id: f.frame_id, road_state: $("state").value, objects: boxes};
  const response = await fetch("/api/annotation", {method: "POST", body: JSON.stringify(body)});
  const result = await response.json();
  if (!response.ok) { message(result.errors.join("; "), "err"); return; }
  f.annotation = {road_state: body.road_state, objects: structuredClone(boxes)};
  const next = pending();
  if (at + 1 < frames.length) show(at + 1);
  else if (next >= 0) show(next);
  else { show(at); message("Todos los cuadros estan anotados.", "ok"); }
}
function point(event) {
  const r = canvas.getBoundingClientRect(), f = frames[at];
  const clamp = (v, max) => Math.min(max, Math.max(0, Math.round(v * 10) / 10));
  return [clamp((event.clientX - r.left) / r.width * f.image_width, f.image_width),
          clamp((event.clientY - r.top) / r.height * f.image_height, f.image_height)];
}
canvas.onmousedown = e => { const p = point(e); drag = {start: p, class_name: $("cls").value,
  bbox_xyxy: [p[0], p[1], p[0], p[1]]}; };
window.onmousemove = e => {
  if (!drag) return;
  const [x, y] = point(e), [a, b] = drag.start;
  drag.bbox_xyxy = [Math.min(a, x), Math.min(b, y), Math.max(a, x), Math.max(b, y)];
  draw();
};
window.onmouseup = () => {
  if (!drag) return;
  const [x1, y1, x2, y2] = drag.bbox_xyxy;
  if (x2 - x1 >= 2 && y2 - y1 >= 2) {
    boxes.push({class_name: drag.class_name, bbox_xyxy: drag.bbox_xyxy}); listBoxes();
  }
  drag = null; draw();
};
function copyPrevious() {
  const previous = frames[at - 1];
  if (!previous || !previous.annotation) {
    message("El cuadro anterior no tiene anotacion.", "err");
    return;
  }
  boxes = structuredClone(previous.annotation.objects);
  $("state").value = previous.annotation.road_state;
  listBoxes(); draw();
  message("Copiadas: ajusta cada caja a este cuadro antes de guardar.");
}
$("save").onclick = save;
$("prev").onclick = () => show(at - 1);
$("next").onclick = () => show(at + 1);
$("copy").onclick = copyPrevious;
$("todo").onclick = () => show(Math.max(0, pending()));
// Con el foco en un menu, el navegador se queda con las teclas de atajo.
$("cls").onchange = $("state").onchange = e => e.target.blur();
window.onkeydown = e => {
  if (e.target.tagName === "SELECT") return;
  if (e.key === "Enter") { e.preventDefault(); save(); }
  else if (e.key === "a") show(at - 1);
  else if (e.key === "d") show(at + 1);
  else if (e.key === "c") copyPrevious();
  else if ("12345".includes(e.key)) $("state").selectedIndex = Number(e.key) - 1;
};
(async () => {
  const data = await (await fetch("/api/frames")).json();
  frames = data.frames; meta = data;
  fill($("cls"), data.classes); fill($("state"), data.states);
  if (!frames.length) { $("title").textContent = "No hay cuadros capturados."; return; }
  show(Math.max(0, pending()));
})();
</script></body></html>
"""


def save_annotation(dataset: Path, frame: dict[str, Any], body: dict[str, Any]) -> list[str]:
    """Valida y guarda una anotacion. Reescribe el archivo completo de forma atomica."""
    road_state, objects = body.get("road_state"), body.get("objects")
    errors = annotation_errors(road_state, objects, frame["image_width"], frame["image_height"])
    if errors:
        return errors

    annotations = load_annotations(dataset)
    annotations[frame["frame_id"]] = {
        "frame_id": frame["frame_id"],
        "road_state": road_state,
        "objects": objects,
    }
    path = dataset / ANNOTATIONS_FILE
    temporary = path.with_suffix(".tmp")
    lines = (json.dumps(annotations[key], sort_keys=True) for key in sorted(annotations))
    temporary.write_text("".join(f"{line}\n" for line in lines), encoding="utf-8", newline="\n")
    os.replace(temporary, path)
    return []


class _Handler(BaseHTTPRequestHandler):
    def __init__(self, dataset: Path, *args: Any, **kwargs: Any) -> None:
        self.dataset = dataset
        super().__init__(*args, **kwargs)

    def log_message(self, format: str, *args: Any) -> None:
        pass

    def _send(self, status: HTTPStatus, content: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(content)

    def _json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        self._send(status, json.dumps(payload).encode(), "application/json")

    def do_GET(self) -> None:
        path = unquote(urlsplit(self.path).path)
        if path == "/":
            self._send(HTTPStatus.OK, _PAGE.encode(), "text/html; charset=utf-8")
        elif path == "/api/frames":
            annotations = load_annotations(self.dataset)
            frames = [
                {**frame, "annotation": annotations.get(frame["frame_id"])}
                for frame in load_captures(self.dataset)
            ]
            payload = {
                "frames": frames,
                "classes": OBSTACLE_CLASSES,
                "states": tuple(BASE_ACTIONS),
                "zones": [ZONES["izquierda"][1], ZONES["centro"][1]],
            }
            self._json(HTTPStatus.OK, payload)
        elif path.startswith("/img/"):
            self._image(path.removeprefix("/img/"))
        else:
            self._json(HTTPStatus.NOT_FOUND, {"errors": ["not found"]})

    def _image(self, relative: str) -> None:
        # Solo sirve archivos que aparecen en las capturas, nunca una ruta arbitraria.
        known = {f"{f['sequence_id']}/{f['file']}" for f in load_captures(self.dataset)}
        if relative not in known:
            self._json(HTTPStatus.NOT_FOUND, {"errors": ["unknown image"]})
            return
        data = (self.dataset / SEQUENCES_DIR / relative).read_bytes()
        self._send(HTTPStatus.OK, data, "image/jpeg")

    def do_POST(self) -> None:
        if urlsplit(self.path).path != "/api/annotation":
            self._json(HTTPStatus.NOT_FOUND, {"errors": ["not found"]})
            return
        length = int(self.headers.get("Content-Length", 0))
        if not 0 < length <= _MAX_BODY:
            self._json(HTTPStatus.BAD_REQUEST, {"errors": ["invalid body size"]})
            return
        try:
            body = json.loads(self.rfile.read(length))
        except ValueError:
            self._json(HTTPStatus.BAD_REQUEST, {"errors": ["invalid JSON"]})
            return
        frame_id = body.get("frame_id") if isinstance(body, dict) else None
        frame = next((f for f in load_captures(self.dataset) if f["frame_id"] == frame_id), None)
        if frame is None:
            self._json(HTTPStatus.BAD_REQUEST, {"errors": [f"unknown frame: {frame_id!r}"]})
            return
        errors = save_annotation(self.dataset, frame, body)
        if errors:
            self._json(HTTPStatus.UNPROCESSABLE_ENTITY, {"errors": errors})
        else:
            self._json(HTTPStatus.OK, {"saved": frame_id})


def create_server(dataset: Path, port: int) -> ThreadingHTTPServer:
    return ThreadingHTTPServer(("127.0.0.1", port), partial(_Handler, dataset))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m p5.dataset.anotar",
        description="Abre un anotador local de cajas para el dataset.",
    )
    parser.add_argument("--dataset", required=True, type=Path)
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)

    server = create_server(args.dataset, args.port)
    print(f"Anotador en http://127.0.0.1:{server.server_address[1]}  (Ctrl+C para salir)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
