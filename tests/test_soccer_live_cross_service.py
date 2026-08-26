"""The soccer live joins must work from the service that BUILDS THE BOARD.

Measured 2026-08-21 17:05Z: gate 1 reported "no published live-state artifact
for any league" while all ten per-league files existed and were seconds old.
They are a filesystem write on live-odds-worker; the board is built on
refresh-worker, a different box. `Path.iterdir()` cannot cross that.

`live/soccer_live_lens.json` goes through `refresh_state_store` (keyvalue,
shared key space). These tests pin the AGGREGATE path specifically -- the
per-league tests pass whether or not the aggregate works, which is exactly how
the inert version shipped green.

**CORRECTED 2026-08-26: the aggregate is NOT "the only soccer live data the
board build can read", and believing that cost soccer every settlement it ever
had.** `_keyvalue_backed` excludes exactly one marker (`migration_runs/`), so
the per-league files cross services too. What could not cross was DISCOVERY:
the league names came from `Path.iterdir()` on a directory that does not exist
on refresh-worker, so a reader that could have fetched any of them by name had
no names to fetch. See the final test in this file.
"""
from __future__ import annotations

import json

import pytest

from syndicate.features.shared import board_enrichment
from syndicate.features.shared import soccer_live_gameline_source as src

# The loader only accepts a snapshot whose `date` matches the requested one,
# so the fixture must speak about the same day the assertions ask about.
_TODAY = __import__('datetime').datetime.now(__import__('datetime').timezone.utc).date().isoformat()


def _projection():
    return {
        "simulations": 400,
        "home_win_probability": 0.62,
        "draw_probability": 0.23,
        "away_win_probability": 0.15,
        "projected_final_home_goals": 1.9,
        "projected_final_away_goals": 1.1,
        "projected_final_total": 3.0,
        "over_2_5_probability": 0.58,
    }


def _aggregate_game():
    return {
        "league": "epl",
        "event_id": "401879301",
        "home_team": "Arsenal",
        "away_team": "Coventry City",
        "score_home": 2,
        "score_away": 0,
        "status_display_clock": "63'",
        "projection": _projection(),
        "live_player_props": [{
            "player_name": "Kai Havertz",
            "shots_so_far": 2,
            "projected_final_shots": 3.4,
            "shots_over_probabilities": {"0.5": 0.97, "2.5": 0.61},
        }],
    }


def _now_iso(offset_seconds: int = 0) -> str:
    """A RELATIVE timestamp, because gate 1 refuses an artifact older than
    `_LENS_STATE_MAX_AGE_SECONDS`. The first version of this fixture hardcoded
    `2026-08-21T19:20:00+00:00`; it passed when written and failed an hour
    later as wall-clock moved past the staleness bound -- the code was right
    and the test was time-dependent."""
    from datetime import datetime, timedelta, timezone

    return (datetime.now(timezone.utc) - timedelta(seconds=offset_seconds)).isoformat()


def _write_aggregate(root, games, *, date=_TODAY, generated_at=None):
    generated_at = generated_at or _now_iso()
    d = root / "live"
    d.mkdir(parents=True, exist_ok=True)
    (d / "soccer_live_lens.json").write_text(
        json.dumps({
            "date": date,
            "generated_at": generated_at,
            "leagues_checked": ["epl"],
            "leagues_with_games": ["epl"] if games else [],
            "count": len(games),
            "games": games,
            "errors": [],
        }),
        encoding="utf-8",
    )


@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "syndicate.features.shared.refresh_state_store.data_root", lambda: tmp_path
    )
    return tmp_path


def test_aggregate_alone_feeds_the_games_loader(root):
    """NO per-league tree exists here -- exactly the board build's situation."""
    _write_aggregate(root, [_aggregate_game()])
    games = src.soccer_live_games(_TODAY)
    assert len(games) == 1
    assert games[0]["home_team"] == "Arsenal"
    assert games[0]["projection"]["simulations"] == 400


def test_gate3_index_builds_from_the_aggregate_alone(root):
    _write_aggregate(root, [_aggregate_game()])
    idx = src.soccer_live_gameline_index(_TODAY)
    assert list(idx) == [("coventry city", "arsenal")]
    hit = idx[("coventry city", "arsenal")]
    assert hit["home_win_prob"] == 0.62
    assert hit["sims_run"] == 400
    assert hit["analytic_markets"]["totals"]["prob_over"] == 0.58


def test_gate2_index_builds_from_the_aggregate_alone(root):
    _write_aggregate(root, [_aggregate_game()])
    report = src.soccer_live_prop_index(_TODAY)
    assert report["live_games"] == 1
    assert report["rows_indexed"] == 2
    assert ("kai havertz", "player_shots", 2.5) in report["index"]


def test_gate1_corrects_from_the_aggregate_alone(root):
    """The reading that was false in production: no per-league tree, aggregate
    present, chip must move pregame -> live."""
    _write_aggregate(root, [_aggregate_game()])
    grid = [{
        "home_team": "Arsenal", "away_team": "Coventry City",
        "game": {"state": "pregame", "status_token": "2:00 PM CT"},
    }]
    out = board_enrichment.attach_live_game_state_from_lens(
        grid, sport="soccer", selected_date=_TODAY)
    assert out["supported"] is True
    assert out["rows_corrected"] == 1, out
    assert grid[0]["game"]["state"] == "live"
    assert grid[0]["game"]["home_score"] == 2


def test_a_stale_dated_aggregate_is_refused(root):
    """A snapshot for another date must not price today's board."""
    _write_aggregate(root, [_aggregate_game()], date="1999-01-01")
    assert src.soccer_live_games(_TODAY) == []


def test_empty_aggregate_falls_through_rather_than_masking(root):
    """An aggregate with no games must not shadow a readable per-league tree --
    otherwise live-odds-worker, where the files ARE local, would go blind."""
    _write_aggregate(root, [])
    d = root / "soccer_source" / "epl" / "api" / "live_state"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"live_state_{_TODAY}.json").write_text(
        json.dumps({
            "league": "epl", "date": _TODAY,
            "generated_at": "2026-08-21T19:20:00+00:00",
            "games": {"1": _aggregate_game()}, "match_box": {},
        }),
        encoding="utf-8",
    )
    games = src.soccer_live_games(_TODAY)
    assert len(games) == 1, "per-league fallback was shadowed by an empty aggregate"


def test_the_per_league_box_is_readable_WITHOUT_a_local_directory(tmp_path, monkeypatch):
    """SOCCER SETTLED ZERO ORDERS ALL-TIME BECAUSE OF THIS.

    `read_json_file` can fetch any path it can NAME -- the per-league live_state
    files are keyvalue-backed like everything else. But the loop enumerated
    leagues with `source.iterdir()`, and on refresh-worker (where
    `settle_orders` runs) `soccer_source/` does not exist, so `league_dirs` was
    EMPTY and the whole branch was skipped.

    That branch is the one that matters: `match_box` spans `in` AND `post`,
    while the aggregate's `games` is in-play only. MEASURED 2026-08-26 --
    la_liga logged `BOX_REUSED ... final_cached=1` for 2026-08-25 while
    settlement for that same date reported `no_soccer_live_state_for_date`.

    So: NO `soccer_source/` directory on disk, and the box still has to arrive.
    """
    monkeypatch.setenv("SYNDICATE_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("SYNDICATE_REFRESH_STATE_BACKEND", "file")
    assert not (tmp_path / "soccer_source").exists()

    wanted = f"soccer_source/epl/api/live_state/live_state_{_TODAY}.json"

    def _named_read(path):
        # Serves ONLY the epl live_state, by name. Everything else -- including
        # the aggregate -- is absent, so a pass here cannot be the aggregate.
        if str(path).replace("\\", "/").endswith(wanted):
            return {
                "generated_at": f"{_TODAY}T20:00:00Z",
                "match_box": {
                    "m1": {
                        "home_team": "Chelsea", "away_team": "Fulham",
                        "score_home": "2", "score_away": "1",
                        "status_state": "post", "final": True,
                    }
                },
            }
        return None

    # `read_json_file` is a LAZY import inside the function, so it is not an
    # attribute of `board_enrichment`. Patch it where it is defined.
    from syndicate.features.shared import refresh_state_store as _rss

    monkeypatch.setattr(_rss, "read_json_file", _named_read)

    resolved = board_enrichment._soccer_live_state_games(_TODAY)
    assert resolved is not None, "the per-league box must be reachable by NAME"
    games, _age = resolved
    finals = [g for g in games if g.get("state") == "final"]
    assert len(finals) == 1, games
    assert finals[0]["home"]["name"] == "Chelsea"
    assert finals[0]["home_score"] == 2 and finals[0]["away_score"] == 1


def test_a_league_on_disk_is_still_read_when_the_catalogue_lacks_it(tmp_path, monkeypatch):
    """The catalogue is a UNION with the directory listing, not a replacement.

    On live-odds-worker and on a dev box those directories are real, and a
    league present on disk but missing from `LEAGUE_DISPLAY_NAMES` must not
    stop being read because the fix arrived.
    """
    monkeypatch.setenv("SYNDICATE_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("SYNDICATE_REFRESH_STATE_BACKEND", "file")
    box = tmp_path / "soccer_source" / "not_in_catalogue" / "api" / "live_state"
    box.mkdir(parents=True)
    (box / f"live_state_{_TODAY}.json").write_text(json.dumps({
        "generated_at": f"{_TODAY}T20:00:00Z",
        "match_box": {"m1": {
            "home_team": "Ajax", "away_team": "PSV",
            "score_home": "0", "score_away": "3",
            "status_state": "post", "final": True,
        }},
    }), encoding="utf-8")

    resolved = board_enrichment._soccer_live_state_games(_TODAY)
    assert resolved is not None
    games, _age = resolved
    assert [g["home"]["name"] for g in games if g.get("state") == "final"] == ["Ajax"]
