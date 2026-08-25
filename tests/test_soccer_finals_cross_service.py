"""A finished soccer match must reach the service that GRADES bets.

THE INERT-FEATURE TRAP THIS EXISTS TO CATCH. A soccer resolver reading only the
per-league `match_box` passes every unit test on a dev box, where all ten league
files are local -- and grades NOTHING in production:

  `live/soccer_live_lens.json`   keyvalue backend, crosses services, IN-PLAY ONLY
  per-league `match_box`         filesystem on live-odds-worker, spans in AND post

`settle_orders` is called from `pipeline/intelligence_state.py`, which runs on
refresh-worker. `board_enrichment._soccer_live_state_games` already states the
asymmetry in its own docstring, and the same reading measured 2026-08-21 17:05Z
that a per-league-only read reported "no published live-state artifact for any
league" while all ten files existed and were seconds old.

`model_engine_standard.md`: "Reachability test before correctness tests
(`off != on`)". This is that test.
"""

from __future__ import annotations

import json

from syndicate.features.shared.board_enrichment import _soccer_live_state_games

DATE = "2026-08-25"


def _write_aggregate(root, payload):
    live = root / "live"
    live.mkdir(parents=True, exist_ok=True)
    (live / "soccer_live_lens.json").write_text(json.dumps(payload), encoding="utf-8")


def _as_refresh_worker(tmp_path, monkeypatch):
    """A data root with the aggregate and NO per-league tree -- which is exactly
    what refresh-worker's disk looks like."""
    monkeypatch.setattr(
        "syndicate.features.shared.refresh_state_store.data_root", lambda: tmp_path
    )
    return tmp_path


def test_a_finished_match_is_visible_with_NO_per_league_tree(tmp_path, monkeypatch):
    root = _as_refresh_worker(tmp_path, monkeypatch)
    _write_aggregate(root, {
        "date": DATE,
        "games": [],
        "finals": [{
            "league": "epl", "event_id": "espn-1",
            "home_team": "Chelsea", "away_team": "Fulham",
            "score_home": "2", "score_away": "1",
            "status_state": "post", "final": True,
        }],
    })

    resolved = _soccer_live_state_games(DATE)
    assert resolved is not None
    games, _age = resolved
    finals = [g for g in games if g["state"] == "final"]
    assert len(finals) == 1
    assert finals[0]["home"]["name"] == "Chelsea"
    # ESPN ships scores as STRINGS; the shared `_add` coerces them, and a string
    # compares wrong downstream without ever raising.
    assert finals[0]["home_score"] == 2
    assert finals[0]["away_score"] == 1


def test_without_the_finals_key_the_same_read_sees_NOTHING_final(tmp_path, monkeypatch):
    """`off != on`. Same artifact, same service, `finals` removed -- and the
    finished match disappears. This is the state production was in, and a test
    that only asserted the `on` case could not tell the two apart.
    """
    root = _as_refresh_worker(tmp_path, monkeypatch)
    _write_aggregate(root, {"date": DATE, "games": []})

    resolved = _soccer_live_state_games(DATE)
    games = [] if resolved is None else resolved[0]
    assert [g for g in games if g["state"] == "final"] == []


def test_a_stale_dated_aggregate_cannot_answer_for_today(tmp_path, monkeypatch):
    """Yesterday's finals must not settle today's bets. The in-play path already
    enforces this date check; the finals path must not be the hole in it."""
    root = _as_refresh_worker(tmp_path, monkeypatch)
    _write_aggregate(root, {
        "date": "2026-08-24",
        "games": [],
        "finals": [{"home_team": "Chelsea", "away_team": "Fulham",
                    "score_home": "2", "score_away": "1", "final": True}],
    })

    resolved = _soccer_live_state_games(DATE)
    games = [] if resolved is None else resolved[0]
    assert [g for g in games if g["state"] == "final"] == []


def test_the_resolver_grades_off_that_same_cross_service_read(tmp_path, monkeypatch):
    """End to end on refresh-worker's disk shape: aggregate in, graded bet out.
    The two halves are wired by `_load_matches`, and this is the only test that
    exercises the seam rather than patching over it."""
    from syndicate.features.shared.bet_status_soccer import soccer_status_resolver

    root = _as_refresh_worker(tmp_path, monkeypatch)
    _write_aggregate(root, {
        "date": DATE,
        "games": [],
        "finals": [{
            "home_team": "Chelsea", "away_team": "Fulham",
            "score_home": "2", "score_away": "1", "final": True,
        }],
    })

    verdict = soccer_status_resolver(DATE)({
        "sport": "soccer", "market": "h2h", "side": "home",
        "home_team": "Chelsea", "away_team": "Fulham",
    })
    assert verdict.get("unavailable_reason") is None
    assert verdict["is_final"] is True
    assert verdict["current_value"] == 1
