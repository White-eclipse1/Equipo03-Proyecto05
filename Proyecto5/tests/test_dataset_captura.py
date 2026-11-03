import io
import json

import pytest

from dataset_helpers import HEIGHT, WIDTH, make_jpeg, stream_bytes
from p5.dataset import captura
from p5.dataset.captura import CaptureError, capture_sequence, iter_stream_parts, jpeg_size


def ticking_clock(step_s: float = 0.2):
    now = {"t": -step_s}

    def clock() -> float:
        now["t"] += step_s
        return now["t"]

    return clock


def test_jpeg_size_reads_the_frame_dimensions():
    assert jpeg_size(make_jpeg(1)) == (WIDTH, HEIGHT)


@pytest.mark.parametrize(
    "data",
    [b"", b"not a jpeg", make_jpeg(1)[:-2], b"\xff\xd8\xff\xd9"],
    ids=["empty", "text", "truncated", "without-sof"],
)
def test_jpeg_size_rejects_invalid_data(data):
    assert jpeg_size(data) is None


def test_stream_parts_follow_content_length_even_with_blank_lines_in_the_jpeg():
    parts = [make_jpeg(1), make_jpeg(2)]

    assert list(iter_stream_parts(io.BytesIO(stream_bytes(parts)))) == parts


def test_stream_cut_inside_a_frame_raises():
    data = stream_bytes([make_jpeg(1)])

    with pytest.raises(CaptureError, match="inside a frame"):
        list(iter_stream_parts(io.BytesIO(data[:60])))


def test_capture_saves_files_times_and_hashes(tmp_path):
    stream = io.BytesIO(stream_bytes([make_jpeg(i) for i in range(20)]))

    records = capture_sequence(
        stream, "seq01", tmp_path, frames=3, interval_ms=500, clock=ticking_clock()
    )

    # A 200 ms entre partes, un intervalo de 500 ms guarda una de cada tres.
    assert [record.t_capture_ms for record in records] == [0, 600, 1200]
    assert [record.frame_id for record in records] == ["seq01-0001", "seq01-0002", "seq01-0003"]
    directory = tmp_path / "secuencias" / "seq01"
    assert (directory / "seq01-0002.jpg").read_bytes() == make_jpeg(3)
    lines = (directory / "capturas.jsonl").read_text(encoding="utf-8").splitlines()
    assert [json.loads(line)["sha256"] for line in lines] == [r.sha256 for r in records]


def test_capture_skips_duplicates_and_invalid_frames(tmp_path):
    parts = [make_jpeg(1), make_jpeg(1), b"corrupt", make_jpeg(2)]

    records = capture_sequence(
        io.BytesIO(stream_bytes(parts)),
        "seq01",
        tmp_path,
        frames=2,
        interval_ms=0,
        clock=ticking_clock(),
    )

    assert [record.frame_id for record in records] == ["seq01-0001", "seq01-0002"]
    assert (tmp_path / "secuencias" / "seq01" / "seq01-0002.jpg").read_bytes() == make_jpeg(2)


def test_capture_discards_the_warmup_frames(tmp_path):
    parts = [make_jpeg(i) for i in range(5)]

    records = capture_sequence(
        io.BytesIO(stream_bytes(parts)),
        "seq01",
        tmp_path,
        frames=2,
        interval_ms=0,
        warmup_ms=500,
        clock=ticking_clock(),
    )

    # A 200 ms entre partes, las de 0, 200 y 400 ms caen dentro del calentamiento.
    assert [record.t_capture_ms for record in records] == [0, 200]
    assert (tmp_path / "secuencias" / "seq01" / "seq01-0001.jpg").read_bytes() == make_jpeg(3)


def test_capture_never_overwrites_an_existing_sequence(tmp_path):
    (tmp_path / "secuencias" / "seq01").mkdir(parents=True)

    with pytest.raises(CaptureError, match="already exists"):
        capture_sequence(io.BytesIO(b""), "seq01", tmp_path, frames=1)


def test_short_stream_raises_but_keeps_what_was_captured(tmp_path):
    stream = io.BytesIO(stream_bytes([make_jpeg(1)]))

    with pytest.raises(CaptureError, match="1/5"):
        capture_sequence(stream, "seq01", tmp_path, frames=5, interval_ms=0, clock=ticking_clock())

    assert (tmp_path / "secuencias" / "seq01" / "seq01-0001.jpg").exists()


@pytest.mark.parametrize("sequence", ["", "../fuera", "Seq 1", "a/b"])
def test_invalid_sequence_id_is_rejected(tmp_path, sequence):
    with pytest.raises(CaptureError, match="invalid sequence id"):
        capture_sequence(io.BytesIO(b""), sequence, tmp_path, frames=1)


def test_cli_only_requests_the_given_stream_url(tmp_path, monkeypatch, capsys):
    requested = []

    def fake_urlopen(url, timeout):
        requested.append(url)
        return io.BytesIO(stream_bytes([make_jpeg(1), make_jpeg(2)]))

    monkeypatch.setattr(captura, "urlopen", fake_urlopen)

    code = captura.main(
        [
            "--url",
            "http://car:81/stream",
            "--dataset",
            str(tmp_path),
            "--sequence",
            "seq01",
            "--frames",
            "2",
            "--interval-ms",
            "0",
            "--warmup-ms",
            "0",
        ]
    )

    assert code == 0
    assert requested == ["http://car:81/stream"]
    assert json.loads(capsys.readouterr().out) == {"sequence_id": "seq01", "frames": 2}


def test_cli_returns_non_zero_when_the_car_is_unreachable(tmp_path, monkeypatch, capsys):
    def fake_urlopen(url, timeout):
        raise OSError("unreachable")

    monkeypatch.setattr(captura, "urlopen", fake_urlopen)

    code = captura.main(
        [
            "--url",
            "http://car:81/stream",
            "--dataset",
            str(tmp_path),
            "--sequence",
            "seq01",
            "--frames",
            "1",
        ]
    )

    assert code == 1
    assert "unreachable" in capsys.readouterr().err
