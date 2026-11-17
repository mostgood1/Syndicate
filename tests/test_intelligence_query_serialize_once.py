"""Serialize-once: the board query hashes the bytes it sends (lane board-query-serialize-once).

The old exit serialised the ~24 MB wire payload twice. `_versioned_query_response`
walked it with `_json_safe_value` and `json.dumps`'d it only to hash it, then `jsonify`
walked and dumped the same tree again to send it
(`.syndicate/findings_2026-11-17_board_query_response_cache.md`, lead a).
`_versioned_query_json_response` does both once.

ORDER, as `learnings.md` asks:
1. reachability first: off != on through the route, read off the same QUERY_STAGE_MS
   field the fleet log carries, and the large payload never reaching the provider when on;
2. equivalence: the same bytes as the old exit, through the route and the helper;
3. the hash: the old hash when nothing needs a JSON `default`, else a hash of the bytes sent;
4. the fallbacks.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from syndicate.blueprints import intelligence as intel

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "intelligence_query_row_refs_sample.json"
SWITCH = "SYNDICATE_QUERY_SERIALIZE_ONCE"
PAGE_BODY = {"question": "top edges today", "mode": "recommendation", "timing": "all", "background": True,
             "force_refresh": False, "slim_aliases": True, "drop_row_diagnostics": True, "row_refs": True}
PINNED_TS = "2026-11-17T21:00:00Z"


def _recorded_board() -> dict:
    return json.loads(FIXTURE.read_text(encoding="ascii"))["response"]


@pytest.fixture(scope="module")
def app():
    from syndicate.app import create_app

    application = create_app()
    application.testing = True
    return application


def _post(app, body: dict) -> tuple[bytes, list[dict]]:
    """The real combined-board exit, fed the recorded board. Returns the body and the
    QUERY_STAGE_MS records the request printed."""
    board = copy.deepcopy(_recorded_board())
    printed: list[str] = []
    real_print = print

    def _capture(*args, **kwargs):
        text = " ".join(str(a) for a in args)
        if "QUERY_STAGE_MS" in text:
            printed.append(text)
        else:
            real_print(*args, **kwargs)

    with patch.object(intel, "combined_board_default_enabled", return_value=True), \
         patch.object(intel, "read_combined_intelligence_response", return_value=board), \
         patch.object(intel, "_server_timestamp", return_value=PINNED_TS), \
         patch("builtins.print", _capture):
        res = app.test_client().post("/api/intelligence/query", json=body)
    assert res.status_code == 200
    assert res.headers.get("Content-Type", "").startswith("application/json")
    assert res.headers.get("Cache-Control") == "no-cache, no-store, must-revalidate"
    stages = [json.loads(line.split("QUERY_STAGE_MS ", 1)[1]) for line in printed]
    return res.get_data(), stages


# --------------------------------------------------------------------------
# 1. Reachability: off != on.
# --------------------------------------------------------------------------


def test_the_switch_is_on_unless_turned_off(monkeypatch):
    monkeypatch.delenv(SWITCH, raising=False)
    assert intel._serialize_once_enabled() is True
    for value in ("off", "OFF", "0", "false", "no"):
        monkeypatch.setenv(SWITCH, value)
        assert intel._serialize_once_enabled() is False, value
    for value in ("on", "1", "true", ""):
        monkeypatch.setenv(SWITCH, value)
        assert intel._serialize_once_enabled() is True, value


def test_the_stage_log_says_which_exit_ran(app, monkeypatch):
    """The fleet reading: QUERY_STAGE_MS carries `serialize_once`, and it follows the switch."""
    monkeypatch.delenv(SWITCH, raising=False)
    _, on = _post(app, PAGE_BODY)
    monkeypatch.setenv(SWITCH, "off")
    _, off = _post(app, PAGE_BODY)
    assert [s["serialize_once"] for s in on] == [True]
    assert [s["serialize_once"] for s in off] == [False]
    assert "version_and_debug" in on[0]["stages"]


def test_the_payload_never_reaches_the_provider_when_on(app, monkeypatch):
    """Assert the branch, not the outcome: when on, the provider only ever dumps the
    small envelope, and the second full walk + dump is gone."""
    provider_cls = type(app.json)
    real_dumps = provider_cls.dumps
    sizes: list[int] = []

    def _counting(self, obj, **kwargs):
        out = real_dumps(self, obj, **kwargs)
        sizes.append(len(out))
        return out

    monkeypatch.delenv(SWITCH, raising=False)
    with patch.object(provider_cls, "dumps", _counting):
        body_on, _ = _post(app, PAGE_BODY)
    on_sizes, sizes[:] = list(sizes), []
    monkeypatch.setenv(SWITCH, "off")
    with patch.object(provider_cls, "dumps", _counting):
        _post(app, PAGE_BODY)
    off_sizes = list(sizes)

    assert len(body_on) > 50_000, "the fixture must be big enough for the size test to mean anything"
    assert on_sizes and max(on_sizes) < 5_000, on_sizes
    assert max(off_sizes) >= len(body_on) - 1, off_sizes


# --------------------------------------------------------------------------
# 2. Equivalence: the old exit's bytes.
# --------------------------------------------------------------------------


@pytest.mark.parametrize("body", [
    PAGE_BODY,
    {"question": "show me the board", "slim_aliases": True, "drop_row_diagnostics": True},
    {"question": "show me the board"},
], ids=["page", "slim+drop", "no-flags"])
def test_the_route_sends_the_old_exits_bytes(app, monkeypatch, body):
    monkeypatch.setenv(SWITCH, "off")
    old, _ = _post(app, body)
    monkeypatch.delenv(SWITCH, raising=False)
    new, _ = _post(app, body)
    assert new == old


def _both(app, payload: dict, fields: dict) -> tuple[bytes, bytes, object]:
    with app.test_request_context(), patch.object(intel, "_server_timestamp", return_value=PINNED_TS):
        with patch.dict("os.environ", {SWITCH: "off"}):
            old = intel._versioned_query_json_response(copy.deepcopy(payload), dict(fields))
        with patch.dict("os.environ", {SWITCH: "on"}):
            new = intel._versioned_query_json_response(copy.deepcopy(payload), dict(fields))
    assert getattr(old, intel._SERIALIZE_ONCE_MARK, False) is False
    assert getattr(new, intel._SERIALIZE_ONCE_MARK, False) is True
    return old.get_data(), new.get_data(), new


def _strict(raw: bytes) -> dict:
    def _refuse(token):
        raise ValueError(f"non-strict JSON token {token}")
    return json.loads(raw, parse_constant=_refuse)


def test_nan_and_infinity_are_cleaned_the_same_way(app):
    payload = {"ok": True, "edge": float("nan"), "rows": [{"p": float("inf"), "q": [1.5, float("-inf")]}],
               "nested": {"z": {"a": float("nan")}}, "text": "café — \"quoted\""}
    fields = {"candidate_count": 3, "selected_date": None, "dates_covered": ["2026-11-17"], "bad": float("nan")}
    old, new, _ = _both(app, payload, fields)
    assert new == old
    doc = _strict(new)
    assert doc["response"]["edge"] is None and doc["response"]["rows"][0]["p"] is None
    assert doc["bad"] is None
    assert doc["response"]["text"] == "café — \"quoted\""


def test_the_placeholder_cannot_collide_with_payload_text(app):
    """The splice replaces the envelope's token only; the same text inside the payload
    or a field survives untouched."""
    lookalike = "__syndicate_serialize_once_" + "0" * 32 + "__"
    payload = {"note": lookalike, "list": [lookalike]}
    old, new, _ = _both(app, payload, {"debug_source": lookalike})
    assert new == old
    assert _strict(new)["response"]["note"] == lookalike


# --------------------------------------------------------------------------
# 3. The hash.
# --------------------------------------------------------------------------


def test_the_version_is_the_old_hash_on_the_recorded_board(app):
    """Nothing in a JSON-native payload needs a `default`, so the bytes hashed are the
    bytes the old hash was taken over: `version` does not move across the change, and
    the page's skip-render-on-same-hash behaviour carries over."""
    board = _recorded_board()
    old, new, _ = _both(app, board, {"debug_source": "combined_board_window"})
    assert new == old
    doc = json.loads(new)
    assert doc["version"] == doc["response_hash"] == intel._versioned_query_response(board)["version"]


def test_the_version_hashes_the_response_bytes_sent(app):
    board = _recorded_board()
    _, new, _ = _both(app, board, {})
    start = new.index(b'"response":') + len(b'"response":')
    end = new.index(b',"response_hash":')
    assert hashlib.sha256(new[start:end]).hexdigest() == json.loads(new)["version"]


def test_a_value_needing_a_default_is_hashed_as_sent(app):
    """The old hash used `default=str`, the provider sends `http_date`. The old exit's
    `version` was a hash of bytes nobody received; the new one is the hash of what was sent.
    Everything except the two hash fields stays byte-equal once parsed."""
    payload = {"ok": True, "at": datetime(2026, 11, 17, 21, 0, tzinfo=timezone.utc)}
    old, new, _ = _both(app, payload, {})
    old_doc, new_doc = json.loads(old), json.loads(new)
    assert new_doc["response"] == old_doc["response"] == {"ok": True, "at": "Tue, 17 Nov 2026 21:00:00 GMT"}
    for doc in (old_doc, new_doc):
        doc.pop("version"), doc.pop("response_hash")
    assert new_doc == old_doc
    sent = json.dumps({"at": "Tue, 17 Nov 2026 21:00:00 GMT", "ok": True}, sort_keys=True, separators=(",", ":"))
    assert json.loads(new)["version"] == hashlib.sha256(sent.encode()).hexdigest()


# --------------------------------------------------------------------------
# 4. Fallbacks.
# --------------------------------------------------------------------------


def test_debug_pretty_printing_falls_back_to_the_old_exit(app, monkeypatch):
    monkeypatch.delenv(SWITCH, raising=False)
    monkeypatch.setattr(app.json, "compact", False)
    with app.test_request_context(), patch.object(intel, "_server_timestamp", return_value=PINNED_TS):
        res = intel._versioned_query_json_response({"ok": True, "x": [1, 2]}, {})
    assert getattr(res, intel._SERIALIZE_ONCE_MARK, False) is False
    assert b"\n  " in res.get_data()


def test_a_response_field_in_the_envelope_is_refused(app, monkeypatch):
    monkeypatch.delenv(SWITCH, raising=False)
    with app.test_request_context(), pytest.raises(ValueError):
        intel._versioned_query_json_response({"ok": True}, {"response": {"shadow": True}})


def test_floats_round_trip_unchanged():
    """The splice relies on `json.dumps` writing a nested value the same wherever it sits;
    floats are the one place that could plausibly differ, so pin it."""
    values = [0.1, 1e-7, 123456789.123, -0.0, 2.5e300, math.pi]
    inner = json.dumps(values, separators=(",", ":"))
    outer = json.dumps({"a": 1, "response": values}, sort_keys=True, separators=(",", ":"))
    assert inner in outer
