"""Lane `state-read-expand-choke-point` (2026-09-15): a persisted board state
reaches every reader EXPANDED, without the caller having to remember.

WHY. The writer compacts (`_compact_state_for_persist`: `by_sport` becomes
position aliases into `recommendations`) and compresses (`_write_state_payload`),
so the stored bytes are not a board. Expansion used to be each caller's job and
one caller forgot: `_read_single_date_response_for_combining` read `by_sport` raw,
and the combined board showed 0 of the 374 candidates refresh-worker persisted
for 2026-09-14 (lane `combined-board-state-rows-lost`, web `b6a0e346`).

The fix is structural -- `_read_state_payload` expands -- and these tests pin it:

  * the precondition is ASSERTED, not assumed: the stored `by_sport` really is
    aliased, or every other assertion here would pass for the wrong reason;
  * the REAL writer feeds every public reader, nothing stubbed on the read path;
  * a static scan fails the next time someone adds a raw `read_json_file` on a
    compacted state/snapshot path without expanding it.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from unittest.mock import patch

import pytest

from pipeline import intelligence_state as S

DATE = "2026-06-15"
STAMP = "2026-06-15T01:54:49Z"
ROWS = 40  # recommendations >= 4,096 bytes, so `_compact_state_for_persist` aliases by_sport
REPO = Path(__file__).resolve().parents[1]


def _row(index: int) -> dict:
    return {
        "sport": "mlb",
        "candidate_type": "game",
        "market": "h2h",
        "selection": f"Team {index}",
        "game_id": f"g{index}",
        "note": "x" * 200,
    }


def _state() -> dict:
    rows = [_row(i) for i in range(ROWS)]
    return {
        "ok": True,
        "selected_date": DATE,
        "requested_sport": "all",
        "state_last_updated": STAMP,
        "candidate_count": ROWS,
        "recommendations": list(rows),
        "top_opportunities": list(rows),
        "by_sport": {"mlb": list(rows)},
        "analysis": None,
        "portfolio": {},
        "parlays": [],
    }


def _by_sport_rows(payload) -> int:
    by_sport = (payload or {}).get("by_sport")
    if not isinstance(by_sport, dict):
        return 0
    return sum(len(items) for items in by_sport.values() if isinstance(items, list))


@pytest.fixture
def written(tmp_path: Path):
    """One real write, for TODAY, so both the global and the dated files exist."""
    S._COMBINED_INTELLIGENCE_RESPONSE_CACHE.clear()
    S._INTELLIGENCE_STATE_SERVICE._snapshots.clear()
    with patch.object(S, "reports_root", return_value=tmp_path), patch.object(
        S, "central_today_iso", return_value=DATE
    ), patch.object(S, "STATE_PATH", tmp_path / "query_state_cache.json"), patch.object(
        S, "BOARD_SNAPSHOT_PATH", tmp_path / "intelligence" / "board_snapshot.json"
    ), patch.object(
        S, "INTELLIGENCE_STATE_PATH", tmp_path / "intelligence" / "intelligence_state.json"
    ), patch.object(
        S, "INTELLIGENCE_HISTORY_PATH", tmp_path / "intelligence" / "intelligence_state_history.jsonl"
    ), patch.object(S, "board_l2a_fallback_enabled", return_value=False), patch.object(
        # Downstream of every read under test (a scoreboard re-state); stubbed
        # only to keep the test off the network. It cannot add rows.
        S, "_refresh_layer2_live_state", return_value=0
    ):
        assert S.write_latest_intelligence_state(_state()) is not None
        yield S._intelligence_state_daily_paths(DATE)


def test_the_stored_state_really_is_compacted(written):
    """THE PRECONDITION. If the writer ever stops aliasing, every test below
    passes without exercising expansion -- so say so, loudly, here."""
    raw = S.read_json_file(written["state"])
    assert isinstance(raw, dict)
    assert _by_sport_rows(raw) == 0, "by_sport was stored as plain lists; these tests no longer exercise expansion"
    assert int(raw.get("candidate_count") or 0) == ROWS


@pytest.mark.parametrize("branch", ["keyvalue_copy", "artifact_only"])
def test_read_state_payload_returns_the_expanded_board(written, branch):
    """Both of `_read_state_payload`'s sources, since each returns through it."""
    if branch == "artifact_only":
        # The keyvalue store holds no copy -- the #43 artifact-fallback case.
        with patch.object(S, "read_json_file", return_value=None):
            payload = S._read_state_payload(written["state"])
    else:
        payload = S._read_state_payload(written["state"])
    assert _by_sport_rows(payload) == ROWS


def test_every_public_state_reader_sees_the_rows(written):
    state = S.read_intelligence_state()
    assert _by_sport_rows(state) == ROWS

    combined = S.read_combined_intelligence_response(dates=[DATE], sport="all")
    assert combined["by_date"][DATE]["candidate_count"] == ROWS, combined["by_date"]

    snapshot = S.read_latest_intelligence_board_snapshot_response({"date": DATE})
    assert isinstance(snapshot, dict)
    assert S._intelligence_state_candidate_count(snapshot) == ROWS


# --- the static half ---------------------------------------------------------

# A raw read of a path the state writer compacts. Matched on the argument's
# SOURCE, because these paths are reached through module constants and helpers.
_COMPACTED_PATH = re.compile(r"INTELLIGENCE_STATE_PATH|BOARD_SNAPSHOT_PATH|\[\s*[\"'](state|board_snapshot)[\"']\s*\]")
_EXPANDERS = {"_expand_persisted_state", "expand_persisted_state", "_expand_persisted_state_public"}
_RAW_READERS = {"read_json_file", "_read_json_file"}

# Raw reads that are CORRECT without expansion, each with its reason. Adding to
# this list is a claim that the reader touches only top-level scalars.
_ALLOWED_RAW = {
    # `_empty_write_would_clobber_good_board`: reads `selected_date`,
    # `candidate_count` and `state_last_updated` only -- never compacted -- and
    # runs on refresh-worker about once a minute while builds are refused, so a
    # decompress there would be a recurring cost for nothing.
    ("pipeline/intelligence_state.py", '_intelligence_state_daily_paths(selected_date)["state"]'),
}


def _raw_compacted_reads() -> list[tuple[str, int, str]]:
    found: list[tuple[str, int, str]] = []
    for root in ("pipeline", "syndicate", "scripts"):
        for path in sorted((REPO / root).rglob("*.py")):
            source = path.read_text(encoding="utf-8-sig")
            if "read_json_file" not in source:
                continue
            tree = ast.parse(source)
            wrapped: set[int] = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and getattr(node.func, "id", getattr(node.func, "attr", None)) in _EXPANDERS:
                    for arg in node.args:
                        wrapped.add(id(arg))
            rel = path.relative_to(REPO).as_posix()
            for node in ast.walk(tree):
                if not (isinstance(node, ast.Call) and getattr(node.func, "id", getattr(node.func, "attr", None)) in _RAW_READERS):
                    continue
                if not node.args or id(node) in wrapped:
                    continue
                arg_source = ast.get_source_segment(source, node.args[0]) or ""
                if _COMPACTED_PATH.search(arg_source) and (rel, arg_source) not in _ALLOWED_RAW:
                    found.append((rel, node.lineno, arg_source))
    return found


def test_no_raw_read_of_a_compacted_state_path():
    """A new raw `read_json_file` on a compacted state/snapshot path fails here.
    Route it through `_read_state_payload`, wrap it in `expand_persisted_state`,
    or -- if it truly reads only top-level scalars -- allowlist it WITH a reason."""
    assert _raw_compacted_reads() == []


def test_the_static_scan_can_fail():
    """Instrument check: the scan must see the one allowlisted raw read, or it
    is scanning nothing and the test above passes vacuously."""
    source = (REPO / "pipeline" / "intelligence_state.py").read_text(encoding="utf-8-sig")
    assert 'read_json_file(_intelligence_state_daily_paths(selected_date)["state"])' in source
    with patch.dict(globals(), {"_ALLOWED_RAW": set()}):
        assert any(rel == "pipeline/intelligence_state.py" for rel, _line, _arg in _raw_compacted_reads())
