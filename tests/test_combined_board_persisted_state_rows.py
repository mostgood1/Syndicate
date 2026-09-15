"""Lane `combined-board-state-rows-lost` (2026-09-15): the combined board reads a
per-date state the WORKER wrote, and must see its rows.

MEASURED ON PRODUCTION 2026-09-15. refresh-worker persisted real boards
(`STATE_PERSIST_BEGIN candidate_count=374` at 01:56:23Z, 14 for 09-15 at
03:02:58Z) and web read those exact payloads -- its stamps match the worker's
`CANDIDATE_POOL_READY` lines to the second -- yet logged
`COMBINED_BOARD_VINTAGE_IGNORED ... reason=no_rows` for both, and every
`by_date` candidate_count on the served board was 0.

NO READER IS STUBBED HERE. The earlier tests of this function
(`test_board_vintage_gating.py`) replace `_read_single_date_response_for_combining`
with a dict of hand-built payloads, which is exactly the input production does
not deliver: a persisted state is aliased (`_compact_state_for_persist`) and
compressed (`_write_state_payload`) on the way out.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from pipeline import intelligence_state as S

DATE = "2026-06-15"
STAMP = "2026-06-15T01:54:49Z"


def _row(index: int, pad: int) -> dict:
    return {
        "sport": "mlb",
        "candidate_type": "game",
        "market": "h2h",
        "selection": f"Team {index}",
        "game_id": f"g{index}",
        "note": "x" * pad,
    }


def _state(rows: list[dict]) -> dict:
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
    }


@pytest.fixture
def worker_disk(tmp_path: Path):
    """Real writer, real reader, one temp reports root. Today is NOT `DATE`, so
    the global no-date files are never written."""
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
        # Downstream of the read under test: re-states rows against a live
        # scoreboard. Stubbed only so the test does no network IO; it cannot
        # add or remove rows, and it runs only AFTER rows were found.
        S, "_refresh_layer2_live_state", return_value=0
    ):
        yield tmp_path


@pytest.mark.xfail(
    strict=True,
    reason=(
        "lane combined-board-state-rows-lost: `_read_single_date_response_for_combining` "
        "reads the persisted state without `_expand_persisted_state`, so a member-aliased "
        "`by_sport` contributes 0 rows. Strict: this flips to XPASS, and fails, when the "
        "reader is fixed -- remove the marker then."
    ),
)
@pytest.mark.parametrize(
    "count,pad,shape",
    [
        # Both land MEMBER-ALIASED on disk (measured). Aliasing shrinks even the
        # 1,500-row by_sport below `_COMPRESS_MIN_BYTES`, so neither is compressed
        # -- an earlier label here said the second one was, and it was not.
        (40, 200, "member-aliased by_sport, small board"),
        (1500, 200, "member-aliased by_sport, full-slate board"),
    ],
)
def test_combined_board_sees_the_rows_of_a_persisted_state(worker_disk, count, pad, shape):
    rows = [_row(i, pad) for i in range(count)]
    assert S.write_latest_intelligence_state(_state(rows)) is not None

    out = S.read_combined_intelligence_response(dates=[DATE], sport="all")

    assert out["by_date"][DATE]["candidate_count"] == count, (shape, out["by_date"])
    assert out["state_meta"]["computed_at"] == STAMP, (shape, out["state_meta"])


def test_a_small_state_is_neither_aliased_nor_compressed_and_already_reads(worker_disk):
    """The control. Below both thresholds the stored payload is plain lists, so
    this passes on HEAD -- which is what makes the two cases above a test of the
    PERSISTED SHAPE rather than of the fixture."""
    rows = [_row(i, 0) for i in range(3)]
    assert S.write_latest_intelligence_state(_state(rows)) is not None

    out = S.read_combined_intelligence_response(dates=[DATE], sport="all")

    assert out["by_date"][DATE]["candidate_count"] == 3, out["by_date"]
