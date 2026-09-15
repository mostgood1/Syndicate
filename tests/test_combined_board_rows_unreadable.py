"""Lane `combined-board-rows-unreadable-tripwire` (2026-09-15): the combined
board publishes the WRITER's stored count beside the rows its READER got, and
names the contradiction when they disagree.

WHY. `by_date[date].candidate_count` counts rows read out of `by_sport`. When the
reader could not parse a member-aliased `by_sport`, that number read 0 while
refresh-worker had persisted 374 candidates -- and the served payload carried no
other number, so a session recorded "production has no state rows". The fix for
the reader is `b6a0e346`/`da013b77`; this is the instrument that would have made
the defect visible in the payload and in one log line.

The unreadable case is produced from a REAL write read back raw -- the exact
shape the pre-`b6a0e346` reader received -- not from a hand-built payload.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from pipeline import intelligence_state as S

DATE = "2026-06-15"
OTHER_DATE = "2026-06-16"
STAMP = "2026-06-15T01:54:49Z"
ROWS = 40  # recommendations >= 4,096 bytes, so the writer member-aliases by_sport


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


@pytest.fixture
def written(tmp_path: Path):
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
        # Downstream of the read (a scoreboard re-state); stubbed only to keep
        # the test off the network. It cannot add or remove rows.
        S, "_refresh_layer2_live_state", return_value=0
    ):
        assert S.write_latest_intelligence_state(_state()) is not None
        yield tmp_path


def test_a_readable_state_reports_stored_equal_to_rows_and_stays_silent(written, capsys):
    out = S.read_combined_intelligence_response(dates=[DATE], sport="all")

    entry = out["by_date"][DATE]
    assert entry["candidate_count"] == ROWS
    assert entry["stored_candidate_count"] == ROWS
    assert "COMBINED_BOARD_STATE_ROWS_UNREADABLE" not in capsys.readouterr().out


def test_the_historical_defect_fires_the_tripwire(written, capsys):
    """The pre-`b6a0e346` reader: the persisted payload, NOT expanded."""
    raw_read = S.read_json_file
    precondition = raw_read(S._intelligence_state_daily_paths(DATE)["state"])
    assert not any(isinstance(v, list) for v in (precondition.get("by_sport") or {}).values()), (
        "the writer stored by_sport as plain lists, so this no longer reproduces the defect"
    )

    with patch.object(S, "_read_state_payload", side_effect=lambda path: raw_read(path)):
        out = S.read_combined_intelligence_response(dates=[DATE], sport="all")

    entry = out["by_date"][DATE]
    assert entry["candidate_count"] == 0
    assert entry["stored_candidate_count"] == ROWS
    printed = capsys.readouterr().out
    assert f"COMBINED_BOARD_STATE_ROWS_UNREADABLE date={DATE} stored={ROWS} rows=0" in printed, printed
    assert "by_sport_shape=aliased" in printed, printed


def test_a_date_with_no_payload_reports_none_not_zero(written, capsys):
    """"Nothing was read" and "read, and it held zero" are different facts."""
    out = S.read_combined_intelligence_response(dates=[OTHER_DATE], sport="all")

    entry = out["by_date"][OTHER_DATE]
    assert entry["candidate_count"] == 0
    assert entry["stored_candidate_count"] is None
    assert "COMBINED_BOARD_STATE_ROWS_UNREADABLE" not in capsys.readouterr().out


@pytest.mark.parametrize(
    "value,expected",
    [
        (None, "absent"),
        ({}, "empty"),
        ({"__compressed__": "zlib-b64-v1", "data": "x"}, "compressed"),
        ({"mlb": {"__alias_members_of__": "recommendations"}}, "aliased"),
        ({"mlb": []}, "lists"),
        ("text", "str"),
    ],
)
def test_by_sport_shape_names_what_arrived(value, expected):
    assert S._by_sport_shape(value) == expected
