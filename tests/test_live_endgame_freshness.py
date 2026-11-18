"""todo #836: the end-game freshness rule (`syndicate/features/shared/live_endgame_freshness.py`)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from syndicate.features.shared import live_endgame_freshness as lef

NOW = datetime(2026, 11, 18, 2, 0, 0, tzinfo=timezone.utc)


def _ago(seconds: float) -> str:
    return (NOW - timedelta(seconds=seconds)).isoformat()


# ---------------------------------------------------------------- the switch


@pytest.mark.parametrize("raw, expected", [
    (None, "shadow"), ("", "shadow"), ("shadow", "shadow"), (" Shadow ", "shadow"),
    ("off", "off"), ("0", "off"), ("false", "off"), ("no", "off"),
    ("on", "on"), ("1", "on"), ("true", "on"), ("onn", "on"),
])
def test_mode_absent_is_shadow_off_is_explicit_and_a_typo_gates(raw, expected):
    env = {} if raw is None else {lef.MODE_ENV: raw}
    assert lef.mode(env) == expected


@pytest.mark.parametrize("raw, expected", [
    (None, 30.0), ("", 30.0), ("45", 45.0), ("0", 30.0), ("-5", 30.0), ("nan", 30.0), ("inf", 30.0), ("x", 30.0),
])
def test_max_state_age_override_only_takes_a_positive_finite_value(raw, expected):
    env = {} if raw is None else {lef.MAX_AGE_ENV: raw}
    assert lef.max_state_age_seconds(env) == expected


# ---------------------------------------------------------------- the clock


def test_the_clock_table_is_the_engine_experts_table():
    """"The last 5%" must mean what the engine read's 95-100 bucket meant: one table, pinned, never two that drift."""
    from syndicate.features.shared.engine_experts import SPORT_CLOCK

    for sport, spec in lef.GATED_SPORTS.items():
        assert SPORT_CLOCK[sport] == spec


@pytest.mark.parametrize("sport", sorted(lef.GATED_SPORTS))
def test_elapsed_share_matches_the_engine_experts_on_every_state(sport):
    from syndicate.features.shared.engine_experts import elapsed_share as expert_share

    periods, length = lef.GATED_SPORTS[sport]
    for period in range(1, periods + 2):
        for clock in (length, length - 1, length / 2, 31, 30, 1, 0, -3, length + 10):
            share, overtime = lef.elapsed_share(sport, period, clock)
            theirs, bucket = expert_share(sport, {"period": period, "clockSeconds": clock})
            if period > periods:
                assert overtime and share is None and bucket == "ot"
            else:
                assert not overtime and share == pytest.approx(theirs, abs=1e-4)
                assert (share >= lef.ENDGAME_SHARE) == (bucket == "95-100")


def test_the_end_game_starts_at_95_percent_of_regulation():
    # NBA: 2,880 s of regulation, 5% is the last 144 s.
    assert not lef.in_endgame("nba", 4, 145)
    assert lef.in_endgame("nba", 4, 144)
    assert lef.in_endgame("nba", 4, 0)
    # NHL: 3,600 s, last 180 s. NCAAF: 3,600 s, last 180 s.
    assert not lef.in_endgame("nhl", 3, 181) and lef.in_endgame("nhl", 3, 180)
    assert not lef.in_endgame("ncaaf", 4, 181) and lef.in_endgame("ncaaf", 4, 180)
    # Earlier periods never are.
    assert not lef.in_endgame("nba", 3, 0)


def test_overtime_is_end_game():
    assert lef.in_endgame("nba", 5, 300)
    assert lef.in_endgame("nhl", 4, 299)
    assert lef.in_endgame("ncaaf", 5, 0)


@pytest.mark.parametrize("sport, period, clock", [
    ("ncaab", 2, 10), ("wnba", 4, 5), ("nfl", 4, 5), ("", 4, 5), (None, 4, 5),
    ("nba", None, 5), ("nba", 4, None), ("nba", 0, 5), ("nba", "x", 5),
])
def test_an_ungated_sport_or_an_unreadable_state_is_never_end_game(sport, period, clock):
    assert not lef.in_endgame(sport, period, clock)
    assert lef.endgame_verdict(sport, period, clock, _ago(600), NOW) is None


# ---------------------------------------------------------------- the verdict


@pytest.mark.parametrize("sport, period, clock", [("nba", 4, 60), ("ncaaf", 4, 100), ("nhl", 3, 90), ("nhl", 4, 200)])
def test_end_game_state_within_30_s_is_used_and_older_is_refused(sport, period, clock):
    assert lef.endgame_verdict(sport, period, clock, _ago(29.9), NOW) is None
    assert lef.endgame_verdict(sport, period, clock, _ago(30.0), NOW) is None
    verdict = lef.endgame_verdict(sport, period, clock, _ago(30.5), NOW)
    assert verdict is not None
    assert verdict["withheld_reason"] == lef.REASON_STALE
    assert verdict["priceable"] is False and verdict["model_prob"] is None and verdict["edge_pp"] is None
    assert verdict["state_age_s"] == 30.5 and verdict["max_state_age_s"] == 30.0


def test_before_the_end_game_any_age_is_left_alone():
    """Before 95% the read found no age effect worth acting on: a 10-minute-old state is not this rule's business."""
    assert lef.endgame_verdict("nba", 4, 145, _ago(600), NOW) is None
    assert lef.endgame_verdict("nhl", 2, 0, _ago(3600), NOW) is None


@pytest.mark.parametrize("as_of", [None, "", "not a time"])
def test_end_game_with_no_state_time_refuses_by_name(as_of):
    verdict = lef.endgame_verdict("nba", 4, 30, as_of, NOW)
    assert verdict is not None and verdict["withheld_reason"] == lef.REASON_TIME_ABSENT
    assert verdict["state_age_s"] is None


def test_a_state_time_ahead_of_now_is_fresh_not_negative():
    verdict = lef.endgame_verdict("nba", 4, 30, (NOW + timedelta(seconds=5)).isoformat(), NOW)
    assert verdict is None
    assert lef.state_age_seconds((NOW + timedelta(seconds=5)).isoformat(), NOW) == 0.0


def test_a_naive_state_time_is_read_as_utc_and_a_datetime_is_accepted():
    naive = (NOW - timedelta(seconds=40)).replace(tzinfo=None).isoformat()
    assert lef.state_age_seconds(naive, NOW) == pytest.approx(40.0)
    assert lef.state_age_seconds(NOW - timedelta(seconds=12), NOW) == pytest.approx(12.0)
    assert lef.state_age_seconds("2026-11-18T01:59:00Z", NOW) == pytest.approx(60.0)


def test_the_age_bound_follows_its_env_override():
    env = {lef.MAX_AGE_ENV: "60"}
    assert lef.endgame_verdict("nba", 4, 30, _ago(45), NOW, env=env) is None
    verdict = lef.endgame_verdict("nba", 4, 30, _ago(61), NOW, env=env)
    assert verdict is not None and verdict["max_state_age_s"] == 60.0


def test_the_verdict_names_what_it_judged():
    verdict = lef.endgame_verdict("nba", 4, 72, _ago(95), NOW)
    assert verdict["elapsed_share"] == pytest.approx((3 * 720 + 648) / 2880, abs=1e-4)
    assert verdict["overtime"] is False
    ot = lef.endgame_verdict("nhl", 4, 100, _ago(95), NOW)
    assert ot["overtime"] is True and ot["elapsed_share"] is None
