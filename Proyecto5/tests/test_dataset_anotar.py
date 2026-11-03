import json
import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from dataset_helpers import CENTER_BOX, add_sequence, make_jpeg
from p5.dataset.anotar import create_server
from p5.dataset.paquete import load_annotations


@pytest.fixture
def server(tmp_path):
    add_sequence(tmp_path, "seq01", ["libre", "libre"], first_seed=1)
    (tmp_path / "anotaciones.jsonl").unlink()
    (tmp_path / "secreto.txt").write_text("no servir", encoding="utf-8")
    httpd = create_server(tmp_path, 0)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield httpd, tmp_path, f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    httpd.server_close()


def post(url, body):
    return urlopen(Request(f"{url}/api/annotation", data=json.dumps(body).encode(), method="POST"))


def test_server_only_listens_on_loopback(server):
    httpd, _, _ = server

    assert httpd.server_address[0] == "127.0.0.1"


def test_page_and_frames_are_served(server):
    _, _, url = server

    assert b"Anotador P5" in urlopen(url).read()
    payload = json.load(urlopen(f"{url}/api/frames"))
    assert [frame["frame_id"] for frame in payload["frames"]] == ["seq01-0001", "seq01-0002"]
    assert payload["frames"][0]["annotation"] is None
    assert "person" in payload["classes"]


def test_captured_image_is_served(server):
    _, _, url = server

    assert urlopen(f"{url}/img/seq01/seq01-0001.jpg").read() == make_jpeg(1)


@pytest.mark.parametrize("path", ["/img/../secreto.txt", "/img/seq01/../../secreto.txt"])
def test_files_outside_the_captures_are_not_served(server, path):
    _, _, url = server

    with pytest.raises(HTTPError) as error:
        urlopen(f"{url}{path}")

    assert error.value.code == 404


def test_annotation_is_saved_and_can_be_replaced(server):
    _, dataset, url = server
    objects = [{"class_name": "person", "bbox_xyxy": CENTER_BOX}]

    post(url, {"frame_id": "seq01-0001", "road_state": "centro", "objects": objects})
    assert load_annotations(dataset)["seq01-0001"]["objects"] == objects

    post(url, {"frame_id": "seq01-0001", "road_state": "libre", "objects": []})
    annotation = load_annotations(dataset)["seq01-0001"]
    assert annotation == {"frame_id": "seq01-0001", "road_state": "libre", "objects": []}


def test_invalid_annotation_is_rejected_and_not_saved(server):
    _, dataset, url = server

    with pytest.raises(HTTPError) as error:
        post(url, {"frame_id": "seq01-0001", "road_state": "centro", "objects": []})

    assert error.value.code == 422
    assert "exige al menos" in json.load(error.value)["errors"][0]
    assert load_annotations(dataset) == {}


def test_unknown_frame_is_rejected(server):
    _, _, url = server

    with pytest.raises(HTTPError) as error:
        post(url, {"frame_id": "nope", "road_state": "libre", "objects": []})

    assert error.value.code == 400
