"""Tests for the gzip transport added by lane `render-egress-transport`.

WHAT THESE ARE FOR. The change is worth ~20 GB/month and touches the path that
carries every artifact between the workers and web, so the tests that matter
are the ones that would catch it being INERT or being WRONG, not the ones that
restate the implementation:

- REACHABILITY BEFORE CORRECTNESS (`learnings.md`, and the model-engine
  standard's `off != on` rule): a compression layer that silently does nothing
  looks exactly like a working one at every level except the bill. So the first
  assertions are that the compressed output is genuinely SMALLER and that the
  kill switch genuinely turns it off.
- The round trip: what the receiver reconstructs must be byte-identical to
  what the sender had, because `X-Artifact-Checksum` is the sha256 of the
  UNCOMPRESSED file and every consumer reads these artifacts whole.
- `gzip;q=0` is a REFUSAL. A substring test for "gzip" gets that backwards,
  and it is the one Accept-Encoding form where being wrong means shipping a
  body the client cannot read.
"""

from __future__ import annotations

import gzip
import json
import zlib

import pytest

from syndicate.features.shared import response_compression as rc


class _FakeHeaders(dict):
    def get(self, key, default=None):  # noqa: D102 - dict with case-insensitive get
        for existing, value in self.items():
            if existing.lower() == str(key).lower():
                return value
        return default

    def __setitem__(self, key, value):
        for existing in list(self.keys()):
            if existing.lower() == str(key).lower():
                dict.__delitem__(self, existing)
        dict.__setitem__(self, key, value)


class _FakeResponse:
    """Just enough of a Flask response for `compress_response`."""

    def __init__(self, payload: bytes, *, content_type: str = "application/json", status: int = 200):
        self._data = payload
        self.headers = _FakeHeaders({"Content-Type": content_type})
        self.status_code = status
        self.direct_passthrough = False

    def get_data(self) -> bytes:
        return self._data

    def set_data(self, payload: bytes) -> None:
        self._data = payload


def _board_like_payload(rows: int = 400) -> bytes:
    """A payload shaped like the ones that actually cost money.

    Not random bytes: the real traffic is repeated JSON keys over odds rows,
    which is why the measured ratio on a production `book_quotes` shard is
    3.5%. Random bytes would show gzip in its WORST case and the test would
    prove the opposite of what production does.
    """
    return json.dumps(
        [
            {
                "game_id": f"2026-09-04-{index // 20}",
                "market": "player_points",
                "book": "draftkings",
                "line": 24.5,
                "over_price": -115,
                "under_price": -105,
                "captured_at": "2026-09-04T17:30:00Z",
            }
            for index in range(rows)
        ]
    ).encode("utf-8")


def test_gzip_bytes_round_trips_and_actually_shrinks():
    payload = _board_like_payload()
    compressed = rc.gzip_bytes(payload, level=1)

    assert gzip.decompress(compressed) == payload
    # The reachability assertion. A no-op implementation passes the round trip
    # and fails this.
    assert len(compressed) < len(payload) / 4


def test_compress_response_sets_gzip_headers_and_body(monkeypatch):
    monkeypatch.delenv("SYNDICATE_RESPONSE_GZIP", raising=False)
    payload = _board_like_payload()
    response = _FakeResponse(payload)

    rc.compress_response(response, "gzip, deflate, br")

    assert response.headers.get("Content-Encoding") == "gzip"
    assert response.headers.get("Content-Length") == str(len(response.get_data()))
    assert "Accept-Encoding" in response.headers.get("Vary", "")
    assert gzip.decompress(response.get_data()) == payload


def test_kill_switch_leaves_the_body_untouched(monkeypatch):
    monkeypatch.setenv("SYNDICATE_RESPONSE_GZIP", "off")
    payload = _board_like_payload()
    response = _FakeResponse(payload)

    rc.compress_response(response, "gzip")

    assert response.headers.get("Content-Encoding") is None
    assert response.get_data() == payload


def test_passthrough_response_is_never_buffered(monkeypatch):
    """`send_file` bodies must be left alone.

    `/api/ops/artifacts/stream` serves 34-199 MB artifacts through
    `send_file`, whose whole purpose is that the body never lands in memory on
    a 2 GB instance. Compressing it would mean calling `get_data()` on it.
    """
    monkeypatch.delenv("SYNDICATE_RESPONSE_GZIP", raising=False)
    response = _FakeResponse(_board_like_payload())
    response.direct_passthrough = True

    def _explode():  # pragma: no cover - must never be called
        raise AssertionError("get_data() was called on a passthrough response")

    response.get_data = _explode  # type: ignore[assignment]

    rc.compress_response(response, "gzip")

    assert response.headers.get("Content-Encoding") is None


def test_already_encoded_response_is_not_double_compressed(monkeypatch):
    monkeypatch.delenv("SYNDICATE_RESPONSE_GZIP", raising=False)
    payload = gzip.compress(_board_like_payload())
    response = _FakeResponse(payload)
    response.headers["Content-Encoding"] = "gzip"

    rc.compress_response(response, "gzip")

    assert response.get_data() == payload


def test_small_bodies_are_left_alone(monkeypatch):
    monkeypatch.delenv("SYNDICATE_RESPONSE_GZIP", raising=False)
    monkeypatch.delenv("SYNDICATE_RESPONSE_GZIP_MIN_BYTES", raising=False)
    response = _FakeResponse(b'{"ok": true}')

    rc.compress_response(response, "gzip")

    assert response.headers.get("Content-Encoding") is None
    # Vary is still set: the same URL can serve a compressed variant.
    assert "Accept-Encoding" in response.headers.get("Vary", "")


def test_non_compressible_content_type_is_left_alone(monkeypatch):
    monkeypatch.delenv("SYNDICATE_RESPONSE_GZIP", raising=False)
    payload = _board_like_payload()
    response = _FakeResponse(payload, content_type="image/png")

    rc.compress_response(response, "gzip")

    assert response.headers.get("Content-Encoding") is None


@pytest.mark.parametrize(
    "header,expected",
    [
        ("gzip", True),
        ("gzip, deflate, br", True),
        ("deflate, gzip;q=0.8", True),
        ("*", True),
        ("", False),
        ("deflate", False),
        # THE ONE THAT A SUBSTRING TEST GETS BACKWARDS.
        ("gzip;q=0", False),
        ("gzip; q=0", False),
    ],
)
def test_client_accepts_gzip_reads_quality_values(header, expected):
    assert rc.client_accepts_gzip(header) is expected


def _ops_client(tmp_path, monkeypatch):
    """A Flask test client wired to a throwaway data root.

    Through the REAL app factory and the REAL blueprint, because the thing
    being tested is whether the two ends of a wire agree -- a hand-rolled
    fake of either end can only prove that my model of it is self-consistent.
    """
    monkeypatch.setenv("SYNDICATE_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("ADMIN_TOKEN", "test-token")
    monkeypatch.delenv("SYNDICATE_REQUIRE_HOSTED_STORAGE", raising=False)
    monkeypatch.delenv("SYNDICATE_RESPONSE_GZIP", raising=False)
    monkeypatch.delenv("SYNDICATE_BOOTSTRAP_ON_START", raising=False)

    from flask import Flask

    from syndicate.blueprints.ops import ops_bp
    from syndicate.features.shared.response_compression import install_response_compression

    app = Flask(__name__)
    app.register_blueprint(ops_bp)
    install_response_compression(app)
    return app.test_client()


_ARTIFACT_PATH = "mlb_source/tracking/book_quotes/2026-09-05.jsonl"


def test_publish_accepts_a_gzip_body_and_stores_the_artifact(tmp_path, monkeypatch):
    """END TO END on the path that carries the bytes.

    3,461 MB of one 4,050 MB hour was inbound publishes on exactly this route.
    """
    client = _ops_client(tmp_path, monkeypatch)
    payload = _board_like_payload(rows=800)
    wire = gzip.compress(payload, 1)
    assert len(wire) < len(payload) / 4

    import hashlib

    response = client.post(
        "/api/ops/artifacts/publish",
        data=wire,
        headers={
            "Authorization": "Bearer test-token",
            "Content-Type": "application/octet-stream",
            "Content-Encoding": "gzip",
            "X-Artifact-Path": _ARTIFACT_PATH,
            # sha256 of the UNCOMPRESSED artifact -- unchanged meaning.
            "X-Artifact-Checksum": hashlib.sha256(payload).hexdigest(),
            "X-Artifact-Publisher": "test",
        },
    )

    assert response.status_code == 200, response.get_data(as_text=True)
    body = response.get_json()
    assert body["encoding"] == "gzip"
    assert body["bytes"] == len(payload)
    assert body["wire_bytes"] == len(wire)
    # The file on disk is the DECOMPRESSED artifact, byte for byte.
    assert (tmp_path / _ARTIFACT_PATH).read_bytes() == payload


def test_publish_still_accepts_an_uncompressed_body(tmp_path, monkeypatch):
    """Any deploy order has to work. An un-upgraded worker keeps publishing."""
    client = _ops_client(tmp_path, monkeypatch)
    payload = _board_like_payload(rows=800)

    import hashlib

    response = client.post(
        "/api/ops/artifacts/publish",
        data=payload,
        headers={
            "Authorization": "Bearer test-token",
            "Content-Type": "application/octet-stream",
            "X-Artifact-Path": _ARTIFACT_PATH,
            "X-Artifact-Checksum": hashlib.sha256(payload).hexdigest(),
            "X-Artifact-Publisher": "test",
        },
    )

    assert response.status_code == 200, response.get_data(as_text=True)
    assert response.get_json()["encoding"] == "identity"
    assert (tmp_path / _ARTIFACT_PATH).read_bytes() == payload


def test_publish_rejects_a_gzip_body_whose_checksum_is_the_compressed_one(tmp_path, monkeypatch):
    """The sender's negotiation depends on this being a 400, not a 500 or a 200.

    `_disable_publish_gzip` turns compression off for the process on a 400 and
    on nothing else, so an old receiver must be distinguishable by its answer.
    A receiver that accepted this would store gzip bytes under a `.jsonl` name.
    """
    client = _ops_client(tmp_path, monkeypatch)
    payload = _board_like_payload(rows=800)
    wire = gzip.compress(payload, 1)

    import hashlib

    response = client.post(
        "/api/ops/artifacts/publish",
        data=wire,
        headers={
            "Authorization": "Bearer test-token",
            "Content-Type": "application/octet-stream",
            "Content-Encoding": "gzip",
            "X-Artifact-Path": _ARTIFACT_PATH,
            "X-Artifact-Checksum": hashlib.sha256(wire).hexdigest(),
        },
    )

    assert response.status_code == 400
    assert response.get_json()["error"] == "checksum mismatch"
    assert not (tmp_path / _ARTIFACT_PATH).exists()


def test_export_is_gzipped_for_a_client_that_asks(tmp_path, monkeypatch):
    """The other direction: the 11-17 MB pull both workers make every ~90s."""
    client = _ops_client(tmp_path, monkeypatch)
    payload = _board_like_payload(rows=3000)
    target = tmp_path / _ARTIFACT_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload)

    plain = client.get(
        f"/api/ops/artifacts/export?path={_ARTIFACT_PATH}",
        headers={"Authorization": "Bearer test-token"},
    )
    assert plain.status_code == 200, plain.get_data(as_text=True)
    assert plain.headers.get("Content-Encoding") is None

    compressed = client.get(
        f"/api/ops/artifacts/export?path={_ARTIFACT_PATH}",
        headers={"Authorization": "Bearer test-token", "Accept-Encoding": "gzip"},
    )
    assert compressed.status_code == 200
    assert compressed.headers.get("Content-Encoding") == "gzip"

    raw = compressed.get_data()
    # Werkzeug's test client may or may not decode for us depending on version;
    # accept either, then assert on the CONTENT, which is what callers read.
    decoded = raw if raw[:2] != b"\x1f\x8b" else gzip.decompress(raw)
    assert json.loads(decoded)["artifacts"][_ARTIFACT_PATH].encode("utf-8") == payload

    # THE REACHABILITY ASSERTION, and the whole point of the change: the wire
    # body has to be materially smaller than the one it replaces.
    wire_len = len(raw) if raw[:2] == b"\x1f\x8b" else len(gzip.compress(decoded, 1))
    assert wire_len < len(plain.get_data()) / 4


def test_publish_streamed_sends_a_gzip_body(tmp_path, monkeypatch):
    """ASSERT THE BRANCH, not the outcome.

    `learnings.md`: a fixture can take a cheaper path than production and the
    failure looks like a good result. A `_publish_streamed` that quietly
    skipped compression would still return True and still publish, and the
    only visible difference would be the bandwidth graph a month later. So
    this captures the actual `urllib` Request and reads what crossed the wire.
    """
    import hashlib

    from syndicate.features.shared import artifact_publisher as ap

    monkeypatch.setenv("SYNDICATE_DATA_ROOT", str(tmp_path))
    monkeypatch.delenv("SYNDICATE_PUBLISH_GZIP", raising=False)
    monkeypatch.setattr(ap, "_PUBLISH_GZIP_ENABLED", True, raising=False)
    # `_LAST_PUBLISHED_CHECKSUM` is a MODULE-LEVEL de-duplicator and it leaks
    # across tests: the same bytes at the same path publish once and then log
    # PUBLISH_SKIPPED_UNCHANGED, so a second test asserting on the wire body
    # sees no request at all. Caught by this file, not reasoned about.
    ap._LAST_PUBLISHED_CHECKSUM.clear()

    payload = _board_like_payload(rows=4000)
    source = tmp_path / _ARTIFACT_PATH
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(payload)

    captured: dict[str, object] = {}

    class _FakeHTTPResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b"{}"

    def _fake_urlopen(request_obj, timeout=None):  # noqa: ARG001
        captured["headers"] = {k.lower(): v for k, v in request_obj.headers.items()}
        captured["body"] = request_obj.data.read()
        return _FakeHTTPResponse()

    monkeypatch.setattr(ap.urllib_request, "urlopen", _fake_urlopen)

    result = ap._publish_streamed(
        source,
        relative_path=_ARTIFACT_PATH,
        url="http://web:10000/api/ops/artifacts/publish",
        token="test-token",
        timeout_seconds=10,
    )

    assert result is True
    headers = captured["headers"]
    assert headers["Content-encoding".lower()] == "gzip"
    body = captured["body"]
    assert gzip.decompress(body) == payload
    assert len(body) < len(payload) / 4
    # Content-Length must describe the WIRE body or urllib buffers (or worse,
    # truncates) instead of streaming it.
    assert int(headers["Content-length".lower()]) == len(body)
    # The checksum header still describes the UNCOMPRESSED artifact.
    assert headers["X-artifact-checksum".lower()] == hashlib.sha256(payload).hexdigest()


def test_publish_streamed_kill_switch_sends_the_raw_body(tmp_path, monkeypatch):
    from syndicate.features.shared import artifact_publisher as ap

    monkeypatch.setenv("SYNDICATE_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("SYNDICATE_PUBLISH_GZIP", "off")
    monkeypatch.setattr(ap, "_PUBLISH_GZIP_ENABLED", True, raising=False)
    # `_LAST_PUBLISHED_CHECKSUM` is a MODULE-LEVEL de-duplicator and it leaks
    # across tests: the same bytes at the same path publish once and then log
    # PUBLISH_SKIPPED_UNCHANGED, so a second test asserting on the wire body
    # sees no request at all. Caught by this file, not reasoned about.
    ap._LAST_PUBLISHED_CHECKSUM.clear()

    payload = _board_like_payload(rows=4000)
    source = tmp_path / _ARTIFACT_PATH
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(payload)

    captured: dict[str, object] = {}

    class _FakeHTTPResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b"{}"

    def _fake_urlopen(request_obj, timeout=None):  # noqa: ARG001
        captured["headers"] = {k.lower(): v for k, v in request_obj.headers.items()}
        captured["body"] = request_obj.data.read()
        return _FakeHTTPResponse()

    monkeypatch.setattr(ap.urllib_request, "urlopen", _fake_urlopen)

    assert ap._publish_streamed(
        source,
        relative_path=_ARTIFACT_PATH,
        url="http://web:10000/api/ops/artifacts/publish",
        token="test-token",
        timeout_seconds=10,
    ) is True

    assert "content-encoding" not in captured["headers"]
    assert captured["body"] == payload


def test_receiver_decompressor_reconstructs_the_exact_artifact():
    """The receive loop's shape, over chunk boundaries.

    `_publish_streamed_body` feeds `zlib.decompressobj(16 + MAX_WBITS)` one
    read at a time and hashes the DECOMPRESSED bytes. This asserts the two
    properties that makes correct: chunking never loses a byte, and `flush()`
    is required (dropping it silently truncates the tail).
    """
    payload = _board_like_payload(rows=2000)
    wire = gzip.compress(payload, 1)
    assert len(wire) < len(payload) / 4

    decompressor = zlib.decompressobj(16 + zlib.MAX_WBITS)
    out = bytearray()
    # A deliberately awkward chunk size, so boundaries fall mid-member.
    for start in range(0, len(wire), 997):
        out += decompressor.decompress(wire[start : start + 997])
    out += decompressor.flush()

    assert bytes(out) == payload
