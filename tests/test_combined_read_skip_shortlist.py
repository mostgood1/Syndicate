"""Lane `web-silent-worker-kills` (2026-11-20): the combined board read leaves the day state's Layer 2
shortlist ENCODED.

MEASURED ON THE FLEET 2026-11-20. Two loop-stall dumps (16:08:10Z, 17:04Z) named the same call: a web
request thread inside ONE `json.loads` at `_decompress_oversized_values`, decoding 11-21's compressed
`layer2_shortlist` (5.2 MB of base64, 39.9 MB of JSON) during a cold `read_combined_intelligence_response`.
It held the GIL 40+ s, so the worker's main loop could not heartbeat; past 60 s gunicorn kills the worker
(the 11-17 silent kills). Nothing on that path reads the shortlist: the combined read uses each date's
`by_sport`, `candidate_count` and stamps, and its Layer 2 fallback reads the standalone artifact.

NO READER IS STUBBED: the state goes through the real writer (aliased + compressed) and the real reader,
as in `test_combined_board_persisted_state_rows.py`. These pin: the precondition (the persisted shortlist
really is compressed), the served board is identical with the skip on and off, the skipped value never
reaches zlib (off != on in the work done), the other readers still decode it, and the codec check still
refuses an unknown codec.
"""

from __future__ import annotations

import json
import zlib
from pathlib import Path
from unittest.mock import patch

import pytest

from pipeline import intelligence_state as S

DATE = "2026-06-15"
STAMP = "2026-06-15T01:54:49Z"


def _row(index: int) -> dict:
    return {"sport": "mlb", "candidate_type": "game", "market": "h2h", "selection": f"Team {index}",
            "game_id": f"g{index}"}


def _shortlist(count: int = 4000) -> dict:
    rows = [{"game_id": f"g{i}", "selection": f"Team {i}", "note": "x" * 120} for i in range(count)]
    return {"selected_date": DATE, "generated_at": STAMP, "rows": rows, "cards": rows[:50]}


def _state(rows: list[dict], shortlist: dict) -> dict:
    return {
        "ok": True,
        "selected_date": DATE,
        "requested_sport": "all",
        "state_last_updated": STAMP,
        "candidate_count": len(rows),
        "recommendations": list(rows),
        "top_opportunities": list(rows),
        "by_sport": {"mlb": list(rows)},
        "analysis": None,
        "portfolio": {},
        "parlays": [],
        "layer2_shortlist": shortlist,
    }


@pytest.fixture
def worker_disk(tmp_path: Path, monkeypatch):
    """Real writer, real reader, one temp reports root (the fixture of
    `test_combined_board_persisted_state_rows.py`)."""
    monkeypatch.delenv(S._COMBINED_READ_SKIP_ENV, raising=False)
    S._COMBINED_INTELLIGENCE_RESPONSE_CACHE.clear()
    S._INTELLIGENCE_STATE_SERVICE._snapshots.clear()
    with patch.object(S, "reports_root", return_value=tmp_path), patch.object(
        S, "central_today_iso", return_value="2026-06-14"
    ), patch.object(S, "STATE_PATH", tmp_path / "query_state_cache.json"), patch.object(
        S, "BOARD_SNAPSHOT_PATH", tmp_path / "board_snapshot.json"
    ), patch.object(
        S, "INTELLIGENCE_STATE_PATH", tmp_path / "intelligence_state.json"
    ), patch.object(
        S, "INTELLIGENCE_HISTORY_PATH", tmp_path / "intelligence" / "intelligence_state_history.jsonl"
    ), patch.object(S, "board_l2a_fallback_enabled", return_value=False), patch.object(
        S, "_refresh_layer2_live_state", return_value=0
    ):
        rows = [_row(i) for i in range(30)]
        assert S.write_latest_intelligence_state(_state(rows, _shortlist())) is not None
        yield tmp_path
    S._COMBINED_INTELLIGENCE_RESPONSE_CACHE.clear()


def _day_state_path() -> Path:
    return S._intelligence_state_daily_paths(DATE)["state"]


def _combined() -> dict:
    S._COMBINED_INTELLIGENCE_RESPONSE_CACHE.clear()
    return S.read_combined_intelligence_response(dates=[DATE], sport="all")


def _comparable(out: dict) -> str:
    """The served board minus what differs between ANY two reads (wall-clock stamps)."""
    def scrub(value):
        if isinstance(value, dict):
            return {k: scrub(v) for k, v in value.items()
                    if k not in {"served_at", "server_time", "read_at", "age_seconds", "newest_age_seconds", "age_s", "now"}}
        if isinstance(value, list):
            return [scrub(v) for v in value]
        return value
    return json.dumps(scrub(out), sort_keys=True, default=str)


def test_the_persisted_day_state_carries_the_shortlist_compressed(worker_disk):
    """The precondition, so the rest is not vacuous: the writer stored the shortlist as a codec envelope."""
    raw = S.read_json_file(_day_state_path())
    envelope = raw["layer2_shortlist"]
    assert envelope[S._COMPRESSED_VALUE_KEY] == S._COMPRESSED_VALUE_CODEC
    assert envelope[S._COMPRESSED_VALUE_BYTES] > S._COMPRESS_MIN_BYTES


def test_the_served_board_is_the_same_with_the_skip_on_and_off(worker_disk, monkeypatch):
    on = _combined()
    monkeypatch.setenv(S._COMBINED_READ_SKIP_ENV, "0")
    off = _combined()
    assert on["by_date"][DATE]["candidate_count"] == 30
    assert _comparable(on) == _comparable(off)


def test_the_skipped_shortlist_never_reaches_zlib_and_says_so(worker_disk, monkeypatch, capsys):
    real = zlib.decompress
    sizes: list[int] = []

    def spy(data, *a, **k):
        out = real(data, *a, **k)
        sizes.append(len(out))
        return out

    shortlist_bytes = len(json.dumps(_shortlist(), sort_keys=True).encode("utf-8"))
    with patch.object(S.zlib, "decompress", spy):
        _combined()
        skipped = list(sizes)
        sizes.clear()
        monkeypatch.setenv(S._COMBINED_READ_SKIP_ENV, "off")
        _combined()
        decoded = list(sizes)
    assert not any(n >= shortlist_bytes * 0.9 for n in skipped), skipped
    assert any(n >= shortlist_bytes * 0.9 for n in decoded), decoded
    assert "STATE_DECODE_SKIPPED key=layer2_shortlist" in capsys.readouterr().out


def test_the_per_date_read_returns_the_documented_marker(worker_disk):
    response = S._read_single_date_response_for_combining(DATE)
    marker = response["layer2_shortlist"]
    assert marker[S._DECODE_SKIPPED_KEY] is True and marker[S._QUERY_STATE_LAYER2_OMITTED_KEY] is True
    assert marker["read_from"] == "read_layer2_shortlist"
    assert "rows" not in marker and "cards" not in marker, "a consumer reaching for rows must get None, not []"
    assert response["candidate_count"] == 30 and len(response["by_sport"]["mlb"]) == 30


def test_every_other_reader_still_decodes_the_shortlist(worker_disk):
    full = S._read_state_payload(_day_state_path())
    assert len(full["layer2_shortlist"]["rows"]) == 4000


def test_an_unknown_codec_still_refuses_the_payload_even_on_a_skipped_key():
    payload = {"by_sport": {}, "layer2_shortlist": {S._COMPRESSED_VALUE_KEY: "lz4-v9", S._COMPRESSED_VALUE_DATA: "x"}}
    assert S._decompress_oversized_values(payload, ("layer2_shortlist",)) is None


@pytest.mark.parametrize("raw, expected", [
    ("", ("layer2_shortlist",)), ("1", ("layer2_shortlist",)), ("on", ("layer2_shortlist",)),
    ("typo", ("layer2_shortlist",)), ("0", ()), ("false", ()), ("no", ()), ("OFF", ()),
])
def test_the_switch(monkeypatch, raw, expected):
    monkeypatch.setenv(S._COMBINED_READ_SKIP_ENV, raw)
    assert S._combined_read_skip_keys() == expected
