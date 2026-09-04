"""The live-lens overlay must not correct a grid for a slate it is not about.

REGRESSION FOR A MEASURED LOSS, not a hypothetical. On 2026-09-03 MLB played 9
games and StatsAPI records all 9 as Final; the board's `live_gameline_score`
saw 7. `attach_live_game_state_from_lens` had joined the 09-03 grid against the
**09-04** lens by team pair alone -- `rows_corrected: 187`,
`transitions: {"live->pregame": 187}` -- and 187 was exactly the ATH @ SEA row
count, the single 09-03 matchup that plays again on 09-04. A Final 7-4 was
driven back to `pregame` and never scored.

The FINAL IS TERMINAL guard does not cover this: the row was still reading
`live` off a frozen feed-live chip, so it was never eligible for that guard's
protection. Only the date gate stops it.
"""

from __future__ import annotations

import pytest

from syndicate.features.shared import board_enrichment


def _grid_row(away: str, home: str, state: str, *, away_score=None, home_score=None) -> dict:
    return {
        "away_team": away,
        "home_team": home,
        "game": {
            "matchup": f"{away} @ {home}",
            "state": state,
            "away_score": away_score,
            "home_score": home_score,
        },
    }


def _lens_snapshot(date: str, games: list[dict]) -> dict:
    # `generatedAt` is deliberately absent: `_lens_generated_age_seconds`
    # returns None for it and the staleness guard then declines to fire, so a
    # refusal in these tests can only have come from the date gate.
    return {"page_context": {"date": date, "games": games}}


def _lens_game(away: str, home: str, abstract: str) -> dict:
    return {
        "status": {"abstract": abstract, "detailed": abstract.title()},
        "home": {"name": home},
        "away": {"name": away},
        "matchup": {"score": {"home": None, "away": None}},
    }


@pytest.fixture
def patched_lens(monkeypatch):
    """Swap the keyvalue-backed snapshot read for an in-memory payload.

    The real path is `data_root()/live/mlb_live_lens.json`, which is a Redis
    key rather than a file (learnings.md:3722) -- so this must patch the
    READER, not write a fixture to disk.
    """

    def _install(snapshot):
        import syndicate.features.shared.refresh_state_store as store

        monkeypatch.setattr(store, "read_json_file", lambda *_a, **_k: snapshot)

    return _install


def test_lens_from_the_next_day_corrects_nothing(patched_lens):
    """THE 2026-09-03 CASE. Tomorrow's pregame entry must not touch today's grid."""
    patched_lens(_lens_snapshot("2026-09-04", [_lens_game("Athletics", "Seattle Mariners", "preview")]))
    grid = [_grid_row("Athletics", "Seattle Mariners", "live", away_score=7, home_score=4)]

    result = board_enrichment.attach_live_game_state_from_lens(grid, sport="mlb", selected_date="2026-09-03")

    assert result["rows_corrected"] == 0
    assert result["reason"] == "live-lens snapshot is for a different slate date"
    assert result["lens_date"] == "2026-09-04"
    assert result["requested_date"] == "2026-09-03"
    # The row is untouched -- this is the assertion the outage was about.
    assert grid[0]["game"]["state"] == "live"


def test_same_date_lens_still_corrects(patched_lens):
    """THE OFF != ON CONTROL. A gate that refused everything would also pass
    the test above, so prove the same-date path still does its job."""
    patched_lens(_lens_snapshot("2026-09-03", [_lens_game("Athletics", "Seattle Mariners", "final")]))
    grid = [_grid_row("Athletics", "Seattle Mariners", "live")]

    result = board_enrichment.attach_live_game_state_from_lens(grid, sport="mlb", selected_date="2026-09-03")

    assert result["rows_corrected"] == 1
    assert grid[0]["game"]["state"] == "final"


def test_undated_snapshot_is_refused_with_its_own_reason(patched_lens):
    """ABSENT MUST NOT DEFAULT PERMISSIVE, and must be distinguishable from a
    date mismatch -- an undated snapshot is a shape defect worth chasing,
    a mismatched one is this guard working."""
    patched_lens({"page_context": {"games": [_lens_game("Athletics", "Seattle Mariners", "preview")]}})
    grid = [_grid_row("Athletics", "Seattle Mariners", "live")]

    result = board_enrichment.attach_live_game_state_from_lens(grid, sport="mlb", selected_date="2026-09-03")

    assert result["rows_corrected"] == 0
    assert result["reason"] == "live-lens snapshot carries no slate date to check against"
    assert "lens_date" not in result
    assert grid[0]["game"]["state"] == "live"
