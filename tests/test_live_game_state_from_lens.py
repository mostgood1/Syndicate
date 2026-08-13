"""`#413` -- the board's game state was frozen at whenever the feed was captured.

REPORTED FROM THE BOARD: "we need live state to update, we had the MIL SD game
still showing and its final now."

NOT ARTIFACT LAG, which is what it looks like and what makes it hard to see.
Measured 2026-08-13 against a board artifact **5 minutes old**:

    matchup   BOARD state   BOARD status   LENS abstract
    MIL@SD    live          TOP 9          Final          <- reported
    CLE@DET   live          BOT 1          Live           <- 2h after first pitch

The artifact was fresh. Its input was frozen.

THE MECHANISM is `_mlb_feed_live_payload` (blueprints/home.py:3333):

    payload = load_json_or_gz_file(raw_feed_live_path(selected_date, game_pk))
    if isinstance(payload, dict):
        return payload            # exists -> returned, however old
    if selected_date == central_today_iso():
        return _fetch_mlb_feed_live(game_pk)

The cached file is consulted for PRESENCE and never for freshness, so whichever
moment a game's feed was first captured becomes its state for the rest of the
day. Captured in the 1st inning, it reads `BOT 1` forever; captured in the 9th,
it reads `TOP 9` through the final out. The live lens does a real status fetch
and is right -- two consumers, same box, opposite answers.

VERIFIED AGAINST PRODUCTION, one snapshot against one board:

    rows_corrected: 210   transitions: {"live->final": 210}   snapshot age: 2.6s

MIL @ SD flipped to final; the seven genuinely-live games were left alone.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from syndicate.features.shared import board_enrichment as BE


def _snapshot(*games, age_seconds: float = 30.0):
    generated = datetime.now(timezone.utc) - timedelta(seconds=age_seconds)
    return {"generatedAt": generated.isoformat(), "games": list(games)}


def _lens_game(away, home, abstract, detailed="", away_score=None, home_score=None):
    return {
        "status": {"abstract": abstract, "detailed": detailed},
        "away": {"abbr": away, "name": away},
        "home": {"abbr": home, "name": home},
        "matchup": {"score": {"away": away_score, "home": home_score}},
    }


def _row(away, home, state, status_token=""):
    return {
        "away_team": away,
        "home_team": home,
        "game": {"state": state, "status_token": status_token},
    }


@pytest.fixture
def lens(monkeypatch):
    """Feed a snapshot in, and make the team join exact-match for the test."""

    def _install(snapshot):
        import syndicate.features.shared.refresh_state_store as store
        import syndicate.features.shared.team_aliases as aliases

        monkeypatch.setattr(store, "read_json_file", lambda *_a, **_k: snapshot)
        monkeypatch.setattr(
            aliases, "teams_match", lambda _sport, a, b: str(a).strip().lower() == str(b).strip().lower()
        )

    return _install


def test_the_reported_case_a_finished_game_stops_reading_live(lens):
    lens(_snapshot(_lens_game("MIL", "SD", "Final", away_score=2, home_score=3)))
    grid = [_row("MIL", "SD", "live", "TOP 9")]
    coverage = BE.attach_live_game_state_from_lens(grid, sport="mlb", selected_date="2026-08-12")
    assert coverage["rows_corrected"] == 1
    assert coverage["transitions"] == {"live->final": 1}
    assert grid[0]["game"]["state"] == "final"


def test_the_frozen_status_token_is_corrected_too(lens):
    # Leaving "TOP 9" on a game now marked final swaps one confident wrong
    # reading for another -- the reader sees a settled game mid-inning.
    lens(_snapshot(_lens_game("MIL", "SD", "Final")))
    grid = [_row("MIL", "SD", "live", "TOP 9")]
    BE.attach_live_game_state_from_lens(grid, sport="mlb", selected_date="2026-08-12")
    assert grid[0]["game"]["status_token"] == "FINAL"
    assert grid[0]["game"]["state_source"] == "mlb_live_lens"


def test_a_genuinely_live_game_is_left_alone(lens):
    # Seven of eight live games agreed on production. A correction pass that
    # rewrites agreeing rows would make its own instrumentation useless.
    lens(_snapshot(_lens_game("CLE", "DET", "Live", "In Progress")))
    grid = [_row("CLE", "DET", "live", "BOT 1")]
    coverage = BE.attach_live_game_state_from_lens(grid, sport="mlb", selected_date="2026-08-12")
    assert coverage["rows_corrected"] == 0
    assert grid[0]["game"]["status_token"] == "BOT 1"


def test_final_is_terminal_and_never_reopens(lens):
    """A settled game must not be dragged back to live by a lagging snapshot.

    An un-finaled game re-opens edges against a market with no price left to
    beat, which is precisely what `live_edge_policy` refuses.
    """
    lens(_snapshot(_lens_game("TB", "ATH", "Live", "In Progress")))
    grid = [_row("TB", "ATH", "final", "FINAL")]
    coverage = BE.attach_live_game_state_from_lens(grid, sport="mlb", selected_date="2026-08-12")
    assert coverage["rows_corrected"] == 0
    assert grid[0]["game"]["state"] == "final"


def test_a_stale_snapshot_may_not_override_a_fresh_chip(lens):
    """Otherwise a wedged live lens freezes the board harder than the bug.

    The whole premise is that the lens is the FRESHER source. When it stops
    being fresh the premise is gone, and the correction has to stand down and
    say so rather than keep applying an old answer with authority.
    """
    lens(_snapshot(_lens_game("MIL", "SD", "Final"),
                   age_seconds=BE._LENS_STATE_MAX_AGE_SECONDS + 60))
    grid = [_row("MIL", "SD", "live", "TOP 9")]
    coverage = BE.attach_live_game_state_from_lens(grid, sport="mlb", selected_date="2026-08-12")
    assert coverage["rows_corrected"] == 0
    assert "staler" in coverage["reason"]
    assert grid[0]["game"]["state"] == "live"


def test_an_absent_snapshot_is_named_not_silently_zero(lens):
    # Zero corrections and "there was nothing to correct with" render
    # identically and have opposite fixes.
    lens(None)
    coverage = BE.attach_live_game_state_from_lens(
        [_row("MIL", "SD", "live")], sport="mlb", selected_date="2026-08-12"
    )
    assert coverage["rows_corrected"] == 0
    assert coverage["reason"] == "no published live-lens snapshot"


def test_an_unwired_sport_says_so(lens):
    # The lens status is MLB StatsAPI-derived. Every other sport must get a
    # reason rather than a silent no-op that looks like agreement.
    lens(_snapshot(_lens_game("MIL", "SD", "Final")))
    coverage = BE.attach_live_game_state_from_lens(
        [_row("MIL", "SD", "live")], sport="wnba", selected_date="2026-08-12"
    )
    assert coverage["supported"] is False
    assert "wnba" in coverage["reason"]


def test_the_score_comes_across_with_the_state(lens):
    lens(_snapshot(_lens_game("MIL", "SD", "Final", away_score=2, home_score=3)))
    grid = [_row("MIL", "SD", "live", "TOP 9")]
    BE.attach_live_game_state_from_lens(grid, sport="mlb", selected_date="2026-08-12")
    assert grid[0]["game"]["away_score"] == 2
    assert grid[0]["game"]["home_score"] == 3


def test_it_runs_before_the_projections():
    """`live_edge_policy` reads `game.state` to decide whether an edge is allowed.

    Correcting the state AFTER the projections would leave a settled game's
    edges standing -- the correction has to land while it can still change an
    answer.
    """
    import pathlib

    src = (pathlib.Path(__file__).resolve().parents[1]
           / "syndicate" / "features" / "shared" / "book_grid_artifact.py").read_text(encoding="utf-8")
    assert src.index("attach_live_game_state_from_lens(grid") < src.index("attach_projections(grid")
