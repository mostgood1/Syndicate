"""NBA live pricing is ON unless SYNDICATE_NBA_LIVE_PRICED turns it off (user override 2026-10-20: "Display + money on
everything"; before it, absent = off), and when admitted the join reads
the native re-sim's own snapshot and indexes its `live_resim` lanes (lane nba-native-live-resim, P3)."""
from __future__ import annotations

from syndicate.features.nba import live_resim as lr
from syndicate.features.shared import board_enrichment as be
from syndicate.features.shared.live_gameline_join import build_live_gameline_index, lens_sources_for_sport


def test_absent_env_prices_nba_and_zero_turns_it_off(monkeypatch):
    monkeypatch.delenv(be.NBA_LIVE_PRICED_ENV, raising=False)
    assert "nba" in be._live_gameline_sports() and "nba" in be._live_prop_sports()
    for off in ("0", "off", "false"):
        monkeypatch.setenv(be.NBA_LIVE_PRICED_ENV, off)
        assert "nba" not in be._live_gameline_sports() and "nba" not in be._live_prop_sports()


def test_env_on_admits_nba_and_leaves_every_other_sport_as_it_was(monkeypatch):
    monkeypatch.setenv(be.NBA_LIVE_PRICED_ENV, "on")
    assert be._live_gameline_sports() == be._LIVE_GAMELINE_SPORTS | {"nba"}
    assert be._live_prop_sports() == be._LIVE_PROP_SPORTS | {"nba"}


def test_the_board_reads_the_resim_file_and_accepts_only_live_resim_lanes():
    assert be._LIVE_GAMELINE_SNAPSHOT_PATHS["nba"] == lr.live_lens_snapshot_path().name == "nba_live_resim.json"
    assert lens_sources_for_sport("nba") == (lr.LIVE_RESIM_LENS_SOURCE,) == ("live_resim",)


def _snapshot(lane):
    return {"date": "2026-01-15", "sport": "nba", "games": [{
        "event_id": "999", "home": "Golden State Warriors", "away": "New York Knicks",
        "home_name": "Golden State Warriors", "away_name": "New York Knicks",
        "home_code": "GSW", "away_code": "NYK", "status": {"detailedState": "In Progress"},
        "gameLens": [lane]}]}


def test_a_live_resim_lane_indexes_by_full_team_names_and_a_refusal_does_not():
    facts = lr.ResumeFacts("999", "GSW", "NYK", 50, 48, 2, 0.0, None, 99, "t")
    res = {"sims_run": 200, "home_win_prob": 0.55, "total_mean": 220.0, "home_margin_mean": 2.0,
           "total_dist": {"219": 100, "221": 100}, "margin_dist": {"1": 100, "3": 100}, "segments": {}}
    ok = lr.build_game_lens(facts, res)[0]
    diag: dict = {}
    idx = build_live_gameline_index(_snapshot(ok), sources=lens_sources_for_sport("nba"), sport="nba",
                                     slate_date="2026-01-15", diagnostics=diag)
    assert ("new york knicks", "golden state warriors") in idx, diag
    refused = lr.build_game_lens(None, lr.NbaResimRefusal("no_pregame_inputs", "x"))[0]
    idx2 = build_live_gameline_index(_snapshot(refused), sources=lens_sources_for_sport("nba"), sport="nba",
                                     slate_date="2026-01-15")
    assert ("new york knicks", "golden state warriors") not in idx2
