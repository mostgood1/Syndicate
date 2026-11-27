"""Soccer's live lane-age ceiling, behind its own switch (lane soccer-live-lane-age-ceiling, 2026-11-27).

2026-11-27 20:02-21:47Z the soccer live lens was not rewritten (its memory gate skipped every tick) and the join kept
pricing the six matches already in it, 14-38 rows per build, from a model that ended ~95 minutes old: soccer was not
in `_MAX_LANE_AGE_SECONDS_BY_SPORT`, and its lanes carried no time to judge (`lane_age_max=None` on every soccer
LIVE_GAMELINE_JOIN line that day), because the source read a per-match `generated_at` the lens writes only at the top.

These pin it:
  - the switch: absent / empty / explicit off = off; `shadow`; `on` and any other explicit value = on;
  - OFF IS TODAY: no lane time stamped (the index's `as_of` stays None), no ceiling, a two-hour-old lens priced;
  - reachability, `off != on`: the same lens and row price under off and refuse under on;
  - on: past 600 s refused, at 600 s and fresh priced, an untimed lens refused;
  - shadow: priced exactly as off, the would-refuse counted;
  - the global gate rules over it (global off prices; global shadow caps soccer at shadow);
  - other sports' ceilings do not move with the soccer switch;
  - the stamp keeps a match's own time, and both stores (aggregate, per-league) carry it;
  - the production caller reaches it with the wall clock.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from syndicate.features.shared import board_enrichment
from syndicate.features.shared import soccer_live_gameline_source as src
from syndicate.features.shared.live_gameline_join import (
    LANE_AGE_GATE_ENV,
    MAX_LANE_AGE_ENV,
    REASON_LANE_TIME_ABSENT,
    REASON_STALE_LANE,
    SOCCER_LANE_AGE_ENV,
    SOCCER_MAX_LANE_AGE_SECONDS,
    attach_live_gamelines,
    max_lane_age_seconds,
    soccer_lane_age_mode,
)

DATE = "2026-11-27"
LENS_AT = datetime(2026, 11, 27, 20, 1, 59, tzinfo=timezone.utc)  # the 11-27 frozen lens
LENS_AT_ISO = "2026-11-27T20:01:59.123456+00:00"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for key in (SOCCER_LANE_AGE_ENV, LANE_AGE_GATE_ENV, MAX_LANE_AGE_ENV):
        monkeypatch.delenv(key, raising=False)


@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.setattr("syndicate.features.shared.refresh_state_store.data_root", lambda: tmp_path)
    return tmp_path


def _projection():
    return {"simulations": 400, "home_win_probability": 0.62, "draw_probability": 0.23, "away_win_probability": 0.15,
            "projected_final_home_goals": 1.9, "projected_final_away_goals": 1.1, "projected_final_total": 3.0,
            "over_2_5_probability": 0.58, "home_red_card_applied": False, "away_red_card_applied": False}


def _game(**over):
    g = {"event_id": "401915999", "league": "serie_a", "home_team": "Venezia", "away_team": "Bologna",
         "score_home": 0, "score_away": 0, "status_display_clock": "17'", "projection": _projection()}
    g.update(over)
    return g


def _write_aggregate(root, games, generated_at=LENS_AT_ISO):
    d = root / "live"
    d.mkdir(parents=True, exist_ok=True)
    payload = {"date": DATE, "games": games}
    if generated_at is not None:
        payload["generated_at"] = generated_at
    (d / "soccer_live_lens.json").write_text(json.dumps(payload), encoding="utf-8")


def _write_per_league(root, games_by_id, generated_at=LENS_AT_ISO):
    d = root / "soccer_source" / "serie_a" / "api" / "live_state"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"live_state_{DATE}.json").write_text(json.dumps(
        {"league": "serie_a", "date": DATE, "generated_at": generated_at, "games": games_by_id, "match_box": {}}),
        encoding="utf-8")


def _row():
    """A live full-game h2h board row with a fresh QUOTE: the subject is the lane's age, not the quote's."""
    return {"sport": "soccer", "kind": "game", "market": "h2h", "segment": "full",
            "home_team": "Venezia", "away_team": "Bologna", "game": {"state": "live"},
            "age_seconds": 20.0, "projection": {"market_fair_prob_over": 0.55, "side": "home"}}


def _price(root, seconds_after_lens):
    """Build the index from the lens on disk and run the shared join at LENS_AT + seconds. Returns (row, coverage)."""
    index = src.soccer_live_gameline_index(DATE, data_root=root)
    rows = [_row()]
    coverage = attach_live_gamelines(rows, index, sport="soccer", now=LENS_AT + timedelta(seconds=seconds_after_lens))
    return rows[0], coverage


def _priced(row, coverage):
    """(True, None) for a priced row; (False, reason) for a refused one. A refused row carries no `live_gameline`
    block: its reason is the join's only `withheld_by_reason` entry (one row per call here)."""
    block = row.get("live_gameline")
    if isinstance(block, dict) and block.get("priceable"):
        return True, None
    reasons = coverage.get("withheld_by_reason") or {}
    assert len(reasons) == 1 and sum(reasons.values()) == 1, reasons
    return False, next(iter(reasons))


# ------------------------------------------------------------------------------------------------------ the switch

@pytest.mark.parametrize("raw, mode", [
    (None, "off"), ("", "off"), ("  ", "off"), ("off", "off"), ("OFF", "off"), ("0", "off"), ("false", "off"),
    ("no", "off"), ("shadow", "shadow"), (" Shadow ", "shadow"), ("on", "on"), ("1", "on"), ("true", "on"),
    ("onn", "on"),  # a typo must not leave a stale lane on the price
])
def test_switch_values(raw, mode):
    env = {} if raw is None else {SOCCER_LANE_AGE_ENV: raw}
    assert soccer_lane_age_mode(env) == mode


def test_the_ceiling_exists_only_while_the_switch_is_not_off(monkeypatch):
    assert max_lane_age_seconds("soccer") is None
    for value in ("shadow", "on"):
        monkeypatch.setenv(SOCCER_LANE_AGE_ENV, value)
        assert max_lane_age_seconds("soccer") == SOCCER_MAX_LANE_AGE_SECONDS == 600.0
        assert max_lane_age_seconds(" Soccer ") == 600.0


def test_other_sports_do_not_move_with_the_soccer_switch(monkeypatch):
    before = {s: max_lane_age_seconds(s) for s in ("nba", "ncaab", "wncaab", "ncaaf", "nfl", "nhl", "mlb", "wnba")}
    monkeypatch.setenv(SOCCER_LANE_AGE_ENV, "on")
    assert {s: max_lane_age_seconds(s) for s in before} == before
    assert before["nhl"] is None and before["nba"] == 600.0


def test_the_incident_override_moves_soccer_only_while_gated(monkeypatch):
    monkeypatch.setenv(MAX_LANE_AGE_ENV, "120")
    assert max_lane_age_seconds("soccer") is None
    monkeypatch.setenv(SOCCER_LANE_AGE_ENV, "on")
    assert max_lane_age_seconds("soccer") == 120.0


# -------------------------------------------------------------------------------------------------- the stamp

def test_off_stamps_nothing_and_the_index_carries_no_lane_time(root):
    _write_aggregate(root, [_game()])
    games = src.soccer_live_games(DATE, data_root=root)
    assert "generated_at" not in games[0]
    hit = next(iter(src.soccer_live_gameline_index(DATE, data_root=root).values()))
    assert hit["as_of"] is None


@pytest.mark.parametrize("mode", ["shadow", "on"])
def test_shadow_and_on_stamp_the_lens_time_from_the_aggregate(root, monkeypatch, mode):
    monkeypatch.setenv(SOCCER_LANE_AGE_ENV, mode)
    _write_aggregate(root, [_game()])
    hit = next(iter(src.soccer_live_gameline_index(DATE, data_root=root).values()))
    assert hit["as_of"] == LENS_AT_ISO


def test_the_stamp_reaches_the_per_league_store_too(root, monkeypatch):
    monkeypatch.setenv(SOCCER_LANE_AGE_ENV, "on")
    _write_per_league(root, {"401915999": _game()})
    hit = next(iter(src.soccer_live_gameline_index(DATE, data_root=root).values()))
    assert hit["as_of"] == LENS_AT_ISO


def test_a_matchs_own_time_is_kept(root):
    _write_aggregate(root, [_game(generated_at="2026-11-27T20:05:00+00:00")])
    games = src.soccer_live_games(DATE, data_root=root, stamp_snapshot_time=True)
    assert games[0]["generated_at"] == "2026-11-27T20:05:00+00:00"


def test_the_stamp_copies_and_never_mutates_the_snapshot(root):
    _write_aggregate(root, [_game()])
    plain = src.soccer_live_games(DATE, data_root=root)
    stamped = src.soccer_live_games(DATE, data_root=root, stamp_snapshot_time=True)
    assert "generated_at" not in plain[0] and stamped[0]["generated_at"] == LENS_AT_ISO
    assert {k: v for k, v in stamped[0].items() if k != "generated_at"} == plain[0]


# -------------------------------------------------------------------------------------------- through the join

def test_reachability_off_prices_and_on_refuses_the_same_stale_lens(root, monkeypatch):
    """`off != on` FIRST: the same lens and row, two hours on, with only the switch moved."""
    _write_aggregate(root, [_game()])
    off_row, off_cov = _price(root, 2 * 3600)
    monkeypatch.setenv(SOCCER_LANE_AGE_ENV, "on")
    on_row, on_cov = _price(root, 2 * 3600)
    assert _priced(off_row, off_cov) == (True, None)
    assert _priced(on_row, on_cov) == (False, REASON_STALE_LANE)
    assert on_cov["withheld_by_reason"].get(REASON_STALE_LANE) == 1
    assert off_cov["withheld_by_reason"].get(REASON_STALE_LANE, 0) == 0


def test_off_is_today_the_lane_time_is_absent_and_nothing_is_judged(root):
    _write_aggregate(root, [_game()])
    row, coverage = _price(root, 6063)  # the 11-27 R18 age
    assert _priced(row, coverage) == (True, None)
    assert coverage["lane_age_max_s"] is None
    assert coverage["lane_age_would_refuse"] == {}


@pytest.mark.parametrize("seconds, priced", [(60, True), (195, True), (600, True), (601, False), (6063, False)])
def test_on_refuses_past_the_ceiling_and_prices_at_and_under_it(root, monkeypatch, seconds, priced):
    monkeypatch.setenv(SOCCER_LANE_AGE_ENV, "on")
    _write_aggregate(root, [_game()])
    row, coverage = _price(root, seconds)
    assert _priced(row, coverage)[0] is priced, coverage["withheld_by_reason"]
    assert coverage["lane_age_max_s"] == pytest.approx(seconds - 0.123456, abs=0.1)


def test_on_refuses_an_untimed_lens(root, monkeypatch):
    """Unknown must not default permissive: a snapshot with no time is refused, never priced as fresh."""
    monkeypatch.setenv(SOCCER_LANE_AGE_ENV, "on")
    _write_aggregate(root, [_game()], generated_at=None)
    row, coverage = _price(root, 30)
    assert _priced(row, coverage) == (False, REASON_LANE_TIME_ABSENT)


def test_shadow_prices_as_off_and_counts_what_on_would_refuse(root, monkeypatch):
    _write_aggregate(root, [_game()])
    off_row, off_cov = _price(root, 2 * 3600)
    monkeypatch.setenv(SOCCER_LANE_AGE_ENV, "shadow")
    row, coverage = _price(root, 2 * 3600)
    assert _priced(row, coverage) == (True, None)
    assert row["live_gameline"]["model_prob"] == off_row["live_gameline"]["model_prob"]
    assert row["live_gameline"]["edge_pp"] == off_row["live_gameline"]["edge_pp"]
    assert coverage["lane_age_would_refuse"] == {REASON_STALE_LANE: 1}
    assert coverage["lane_age_would_refuse_priced"] == {REASON_STALE_LANE: 1}
    fresh_row, fresh_cov = _price(root, 60)
    assert _priced(fresh_row, fresh_cov) == (True, None) and fresh_cov["lane_age_would_refuse"] == {}


def test_the_global_gate_rules_over_soccers_switch(root, monkeypatch):
    _write_aggregate(root, [_game()])
    monkeypatch.setenv(SOCCER_LANE_AGE_ENV, "on")
    monkeypatch.setenv(LANE_AGE_GATE_ENV, "off")
    row, coverage = _price(root, 2 * 3600)
    assert _priced(row, coverage) == (True, None) and coverage["lane_age_would_refuse"] == {}
    monkeypatch.setenv(LANE_AGE_GATE_ENV, "shadow")
    row, coverage = _price(root, 2 * 3600)
    assert _priced(row, coverage) == (True, None) and coverage["lane_age_would_refuse"] == {REASON_STALE_LANE: 1}


def test_the_production_caller_reaches_it_with_the_wall_clock(root, monkeypatch):
    """`board_enrichment` passes no `now`: the 11-27 lens is hours old (or more) by the wall clock, so on refuses it."""
    _write_aggregate(root, [_game()])
    rows = [_row()]
    cov = board_enrichment.attach_live_gamelines_for_sport(rows, sport="soccer", selected_date=DATE)
    assert _priced(rows[0], cov) == (True, None)
    monkeypatch.setenv(SOCCER_LANE_AGE_ENV, "on")
    rows = [_row()]
    cov = board_enrichment.attach_live_gamelines_for_sport(rows, sport="soccer", selected_date=DATE)
    assert _priced(rows[0], cov) == (False, REASON_STALE_LANE)
    assert "live_gameline" not in rows[0]
