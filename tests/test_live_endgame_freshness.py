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


# ---------------------------------------------------------------- the engine expert (`live_resim_expert`)
# Shapes copied from tests/test_engine_experts.py (`_evidence`, `_ledger`): a live NBA total, the evidence row's
# state read at `as_of`, the line at `recorded_at`.

LINE_AT = datetime(2026, 11, 10, 0, 20, 10, tzinfo=timezone.utc)


def _evidence(*, period, clock, state_age, tick_age=None):
    as_of = LINE_AT - timedelta(seconds=state_age)
    t = LINE_AT - timedelta(seconds=state_age if tick_age is None else tick_age)
    return {"t": t.isoformat(), "as_of": as_of.isoformat(), "event_id": "401909953",
            "home_name": "Charlotte Hornets", "away_name": "Cleveland Cavaliers", "home": "CHA", "away": "CLE",
            "refusal": None, "carried": False, "state": {"period": period, "clockSeconds": clock},
            "totalRunsDist": {"210": 30, "214": 20, "218": 30, "222": 20},
            "marginDist": {"-6": 25, "-2": 25, "3": 25, "8": 25}, "segments": {}, "modelHomeWinProb": 0.6,
            "simsRun": 100}


def _ledger(ev):
    return {"v": 5, "sport": "nba", "recorded_at": LINE_AT.isoformat(), "event_id": "1df5ff8fe9c6d2dbff1d0ae176063b37",
            "home_team": "Charlotte Hornets", "away_team": "Cleveland Cavaliers", "segment": "full",
            "market": "totals", "line": 215.5, "market_fair_prob": 0.5, "model_home_win_prob": 0.5,
            "live_state_as_of": ev["as_of"], "quote_age_seconds": 50.0, "sims_run": 100,
            "point_estimator": "agresti_coull", "priceable": False}


def _opine(ev, monkeypatch, *, mode=None, experts_off=None):
    from syndicate.features.shared import engine_experts as ee

    if mode is None:
        monkeypatch.delenv(lef.MODE_ENV, raising=False)
    else:
        monkeypatch.setenv(lef.MODE_ENV, mode)
    off = frozenset({experts_off}) if experts_off else frozenset()
    return ee.live_resim_expert(_ledger(ev), ee.EvidenceIndex([ev]), ee.Reader(), off)


def test_expert_off_differs_from_on_on_the_same_stale_end_game_input(monkeypatch):
    """Reachability: one input, the switch the only difference. Off prices it as before; on refuses it by name."""
    ev = _evidence(period=4, clock=60, state_age=45)
    off = _opine(ev, monkeypatch, mode="off")
    on = _opine(ev, monkeypatch, mode="on")
    assert off.refusal is None and off.p_expert is not None
    assert on.refusal == lef.REASON_STALE and on.p_expert is None and on.delta_logit is None
    assert on.clock_bucket == "95-100" and on.inputs["state_age_s"] == 45.0


def test_expert_absent_switch_is_shadow_it_records_and_refuses_nothing(monkeypatch):
    ev = _evidence(period=4, clock=60, state_age=45)
    shadow = _opine(ev, monkeypatch)
    off = _opine(ev, monkeypatch, mode="off")
    assert shadow.refusal is None and shadow.p_expert == off.p_expert and shadow.delta_logit == off.delta_logit
    assert shadow.inputs["state_age_s"] == 45.0
    assert shadow.inputs["endgame_freshness"] == lef.REASON_STALE


def test_expert_off_and_the_experts_off_list_leave_the_opinion_exactly_as_before(monkeypatch):
    ev = _evidence(period=4, clock=60, state_age=45)
    for op in (_opine(ev, monkeypatch, mode="off"), _opine(ev, monkeypatch, mode="on", experts_off=lef.EXPERTS_FEATURE)):
        assert op.refusal is None
        assert "state_age_s" not in op.inputs and "endgame_freshness" not in op.inputs


def test_expert_on_prices_a_fresh_end_game_state_and_any_state_before_the_end_game(monkeypatch):
    fresh = _opine(_evidence(period=4, clock=60, state_age=20), monkeypatch, mode="on")
    assert fresh.refusal is None and fresh.p_expert is not None and "endgame_freshness" not in fresh.inputs
    early = _opine(_evidence(period=2, clock=360, state_age=600), monkeypatch, mode="on")
    assert early.refusal is None and early.p_expert is not None and early.inputs["state_age_s"] == 600.0


def test_expert_judges_the_state_time_not_the_tick(monkeypatch):
    """NBA stamps its tick AFTER reading every game's state: a tick 5 s before the line can carry a state read 45 s
    before it. `evidence_age_s` says 5; the rule must say 45 and refuse."""
    ev = _evidence(period=4, clock=30, state_age=45, tick_age=5)
    on = _opine(ev, monkeypatch, mode="on")
    assert on.inputs["evidence_age_s"] == 5.0 and on.inputs["state_age_s"] == 45.0
    assert on.refusal == lef.REASON_STALE


def test_expert_overtime_is_end_game(monkeypatch):
    on = _opine(_evidence(period=5, clock=200, state_age=60), monkeypatch, mode="on")
    assert on.clock_bucket == "ot" and on.refusal == lef.REASON_STALE


# ---------------------------------------------------------------- the board join (`attach_live_gamelines`)
# Shapes from tests/test_live_gameline_lane_age_gate.py: one live lane (period / clock on its projection, as the NBA,
# NCAAF and NHL producers publish them), one live moneyline row priced at 0.40 against the lane's 0.90.

JOIN_AT = datetime(2026, 11, 18, 2, 0, 0, tzinfo=timezone.utc)
HOME, AWAY = "Atlanta Hawks", "Washington Wizards"


@pytest.fixture(autouse=False)
def _join_env(monkeypatch):
    from syndicate.features.shared import live_gameline_join as join

    for key in (lef.MODE_ENV, lef.MAX_AGE_ENV, join.LANE_AGE_GATE_ENV, join.MAX_LANE_AGE_ENV):
        monkeypatch.delenv(key, raising=False)
    return join


def _snapshot(*, state_age, period=4, clock=60, as_of="set"):
    projection = {"total": 230.0, "homeMargin": 9.0, "totalRunsDist": {"220": 100, "240": 100},
                  "marginDist": {"4": 100, "14": 100}, "period": period, "clockSeconds": clock}
    lane = {"key": "live", "source": "live_resim", "modelHomeWinProb": 0.9, "simsRun": 200, "projection": projection}
    if as_of == "set":
        lane["liveStateAsOf"] = (JOIN_AT - timedelta(seconds=state_age)).isoformat()
    return {"games": [{"home": HOME, "away": AWAY, "gameLens": [lane]}]}


def _row():
    return {"kind": "game", "market": "h2h", "segment": "full", "line": None, "sides": ["home", "away"],
            "away_team": AWAY, "home_team": HOME, "age_seconds": 20.0,
            "game": {"state": "live", "home_score": 100, "away_score": 92},
            "projection": {"market_fair_prob_over": 0.40}}


def _join(join, snapshot, *, sport="nba"):
    rows = [_row()]
    index = join.build_live_gameline_index(snapshot, sources=("live_resim",), sport=sport)
    cov = join.attach_live_gamelines(rows, index, sport=sport, now=JOIN_AT)
    return rows[0], cov


def _priced(row, cov):
    return (row["projection"].get("live_aware") is True and row.get("live_gameline", {}).get("priceable") is True
            and cov["rows_live_gameline_priceable"] == 1)


def test_join_off_shadow_and_on_differ_on_the_same_stale_end_game_row(_join_env, monkeypatch):
    """Reachability through `attach_live_gamelines`: one row, one lane (Q4 1:00, state read 45 s before the build),
    only the switch moves. Off and shadow price it identically; shadow counts it; on withholds the edge by name."""
    join = _join_env
    out = {}
    for mode in ("off", "shadow", "on"):
        monkeypatch.setenv(lef.MODE_ENV, mode)
        out[mode] = _join(join, _snapshot(state_age=45))
    row, cov = out["off"]
    assert _priced(row, cov) and cov["endgame_judged"] == 0 and cov["endgame_would_refuse"] == {}
    row, cov = out["shadow"]
    assert _priced(row, cov) and row["live_gameline"] == out["off"][0]["live_gameline"]
    assert cov["endgame_freshness"] == "shadow" and cov["endgame_judged"] == 1
    assert cov["endgame_would_refuse"] == {lef.REASON_STALE: 1}
    assert cov["endgame_would_refuse_priced"] == {lef.REASON_STALE: 1}
    assert cov["withheld_by_reason"] == {}
    row, cov = out["on"]
    assert not _priced(row, cov)
    assert "live_aware" not in row["projection"] and row["projection"].get("edge_vs_market_pct") is None
    assert cov["withheld_by_reason"] == {lef.REASON_STALE: 1}
    assert cov["endgame_would_refuse"] == {}


def test_join_absent_switch_is_shadow(_join_env):
    row, cov = _join(_join_env, _snapshot(state_age=45))
    assert _priced(row, cov) and cov["endgame_freshness"] == "shadow"
    assert cov["endgame_would_refuse_priced"] == {lef.REASON_STALE: 1}


def test_join_on_prices_a_fresh_end_game_lane_and_any_lane_before_the_end_game(_join_env, monkeypatch):
    monkeypatch.setenv(lef.MODE_ENV, "on")
    row, cov = _join(_join_env, _snapshot(state_age=20))
    assert _priced(row, cov) and cov["endgame_judged"] == 1
    row, cov = _join(_join_env, _snapshot(state_age=300, period=3, clock=60))
    assert _priced(row, cov) and cov["endgame_judged"] == 0


def test_join_on_refuses_a_stale_nhl_end_game_lane_which_has_no_lane_age_ceiling(_join_env, monkeypatch):
    """NHL lanes have no lane-age ceiling at the join; the end-game rule still applies to them."""
    monkeypatch.setenv(lef.MODE_ENV, "on")
    row, cov = _join(_join_env, _snapshot(state_age=45, period=3, clock=100), sport="nhl")
    assert not _priced(row, cov) and cov["withheld_by_reason"] == {lef.REASON_STALE: 1}
    row, cov = _join(_join_env, _snapshot(state_age=45, period=3, clock=400), sport="nhl")
    assert _priced(row, cov) and cov["endgame_judged"] == 0


def test_join_an_ungated_sport_is_never_judged(_join_env, monkeypatch):
    monkeypatch.setenv(lef.MODE_ENV, "on")
    row, cov = _join(_join_env, _snapshot(state_age=45, period=2, clock=30), sport="ncaab")
    assert cov["endgame_judged"] == 0 and lef.REASON_STALE not in (cov.get("withheld_by_reason") or {})


def test_join_the_reasons_before_it_keep_their_counts(_join_env, monkeypatch):
    """An end-game lane with no state time is the LANE-AGE gate's refusal (it is judged first): the end-game rule must
    not take it, and shadow must not count it as newly refused."""
    monkeypatch.setenv(lef.MODE_ENV, "on")
    row, cov = _join(_join_env, _snapshot(state_age=0, as_of=None))
    assert cov["withheld_by_reason"] == {_join_env.REASON_LANE_TIME_ABSENT: 1}
    monkeypatch.setenv(lef.MODE_ENV, "shadow")
    row, cov = _join(_join_env, _snapshot(state_age=0, as_of=None))
    assert cov["endgame_would_refuse"] == {} and cov["endgame_judged"] == 1


def test_join_prints_one_line_with_its_denominator(_join_env, monkeypatch, capsys):
    monkeypatch.setenv(lef.MODE_ENV, "shadow")
    _join(_join_env, _snapshot(state_age=45))
    line = [l for l in capsys.readouterr().out.splitlines() if "LIVE_ENDGAME_FRESHNESS" in l]
    assert len(line) == 1
    assert "sport=nba mode=shadow judged=1" in line[0] and "live_state_stale_in_endgame" in line[0]
    _join(_join_env, _snapshot(state_age=45, period=2))
    assert "LIVE_ENDGAME_FRESHNESS" not in capsys.readouterr().out


def test_the_board_caller_reaches_the_gate_with_the_wall_clock(_join_env, monkeypatch):
    """`board_enrichment.attach_live_gamelines_for_sport` passes no `now`: the gate must see the build's wall clock on
    the one path that prices. Same row, same producer snapshot; only the switch moves."""
    from syndicate.features.shared import board_enrichment, refresh_state_store

    monkeypatch.setattr(board_enrichment, "_nba_live_priced", lambda: True)
    wall = datetime.now(timezone.utc)
    snap = _snapshot(state_age=0)
    snap["games"][0]["gameLens"][0]["liveStateAsOf"] = (wall - timedelta(seconds=90)).isoformat()
    monkeypatch.setattr(refresh_state_store, "read_json_file", lambda _path: snap)
    out = {}
    for mode in ("off", "on"):
        monkeypatch.setenv(lef.MODE_ENV, mode)
        rows = [_row()]
        cov = board_enrichment.attach_live_gamelines_for_sport(rows, sport="nba", selected_date="2026-11-17")
        out[mode] = (rows[0], cov)
    assert _priced(*out["off"])
    row, cov = out["on"]
    assert not _priced(row, cov) and cov["withheld_by_reason"] == {lef.REASON_STALE: 1}
