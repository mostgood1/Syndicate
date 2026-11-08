"""An NCAAB live quote is judged against the LAST SCORE CHANGE the re-sim saw, not the state fetch (#762, lane
ncaab-live-resim-capacity on a loan from wncaab-module; user 2026-11-08 "Score-change rule").

Measured (`.syndicate/findings_2026-11-08_college_quote_order_by_score_change.md`): the quote-order check's spurious
edge sits where a score changed between the quote and the state, so a quote taken after the last score change is a fair
comparison however long before the fetch it was. These pin: the producer publishes the time, it reaches the join's hit,
the basis switch changes the board's answer (off != on), unknown keeps the stricter rule, and wncaab is unchanged.
"""

from __future__ import annotations

import pytest

from syndicate.features.ncaab import live_resim as lr
from syndicate.features.shared.live_gameline_join import (
    QUOTE_ORDER_BASIS_ENV,
    REASON_QUOTE_BEHIND_SCORE,
    REASON_QUOTE_OR_SCORE_TIME_ABSENT,
    attach_live_gamelines,
    build_live_gameline_index,
    lens_sources_for_sport,
    quote_behind_score_verdict,
    quote_order_basis,
)
from tests.basketball_pbp_fixtures import Game


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    # The lane-age gate judges lanes against the wall clock; these carry fixed past times. Basis env starts absent.
    monkeypatch.setenv("SYNDICATE_LIVE_GAMELINE_LANE_AGE_GATE", "off")
    monkeypatch.delenv(QUOTE_ORDER_BASIS_ENV, raising=False)


STATE_AT = "2026-11-08T18:00:00+00:00"       # the state fetch
CHANGED_AT = "2026-11-08T17:57:00Z"           # the last score change in that state, 180 s earlier
AWAY, HOME = "Army Black Knights", "Duke Blue Devils"


# ------------------------------------------------------------------------------------------- the switch

@pytest.mark.parametrize("raw,basis", [(None, "score_change"), ("", "score_change"), ("score_change", "score_change"),
                                       (" Score_Change ", "score_change"), ("state", "state"), ("typo", "state"),
                                       ("off", "state")])
def test_basis_absent_is_the_decision_and_anything_unrecognised_is_the_stricter_one(raw, basis):
    env = {} if raw is None else {QUOTE_ORDER_BASIS_ENV: raw}
    assert quote_order_basis(env) == basis


# ------------------------------------------------------------------------------------------- the verdict

@pytest.mark.parametrize("quote_at,refused", [
    ("2026-11-08 17:56:59+00:00", True),    # 1 s before the score change: the book had not seen it, no grace
    ("2026-11-08 17:57:00+00:00", False),   # at the change
    ("2026-11-08 17:58:00+00:00", False),   # after the change, 120 s before the fetch: refused by the state rule
    ("2026-11-08 18:05:00+00:00", False),   # newer than the state
])
def test_ncaab_quote_is_judged_against_the_score_change(quote_at, refused):
    verdict = quote_behind_score_verdict(quote_at, STATE_AT, sport="ncaab", score_changed_at=CHANGED_AT)
    assert (verdict is not None) is refused
    if refused:
        assert verdict["withheld_reason"] == REASON_QUOTE_BEHIND_SCORE


def test_the_state_basis_is_the_old_rule_for_the_same_quote(monkeypatch):
    quote = "2026-11-08 17:58:00+00:00"
    assert quote_behind_score_verdict(quote, STATE_AT, sport="ncaab", score_changed_at=CHANGED_AT) is None
    monkeypatch.setenv(QUOTE_ORDER_BASIS_ENV, "state")
    assert quote_behind_score_verdict(quote, STATE_AT, sport="ncaab", score_changed_at=CHANGED_AT)[
        "withheld_reason"] == REASON_QUOTE_BEHIND_SCORE


@pytest.mark.parametrize("changed", [None, "", "not a time"])
def test_an_unknown_score_change_time_keeps_the_state_rule(changed):
    assert quote_behind_score_verdict("2026-11-08 17:58:00+00:00", STATE_AT, sport="ncaab",
                                      score_changed_at=changed)["withheld_reason"] == REASON_QUOTE_BEHIND_SCORE
    assert quote_behind_score_verdict("2026-11-08 17:59:45+00:00", STATE_AT, sport="ncaab",
                                      score_changed_at=changed) is None


def test_a_missing_quote_or_state_time_still_refuses_by_name():
    assert quote_behind_score_verdict(None, STATE_AT, sport="ncaab", score_changed_at=CHANGED_AT)[
        "withheld_reason"] == REASON_QUOTE_OR_SCORE_TIME_ABSENT
    assert quote_behind_score_verdict("2026-11-08 17:58:00+00:00", None, sport="ncaab", score_changed_at=CHANGED_AT)[
        "withheld_reason"] == REASON_QUOTE_OR_SCORE_TIME_ABSENT


def test_wncaab_keeps_the_state_rule_and_other_sports_are_ungated():
    quote = "2026-11-08 17:58:00+00:00"
    assert quote_behind_score_verdict(quote, STATE_AT, sport="wncaab", score_changed_at=CHANGED_AT)[
        "withheld_reason"] == REASON_QUOTE_BEHIND_SCORE
    for sport in ("nba", "ncaaf", "mlb", None):
        assert quote_behind_score_verdict(quote, STATE_AT, sport=sport, score_changed_at=CHANGED_AT) is None


# ------------------------------------------------------------------------------------------- the producer

class _Ev:
    def __init__(self, home, away, wallclock=""):
        self.home_score, self.away_score, self.wallclock = home, away, wallclock


def test_last_score_change_is_the_last_play_that_moved_the_score():
    events = [_Ev(0, 0, "T0"), _Ev(2, 0, "T1"), _Ev(2, 0, "T2"), _Ev(2, 3, "T3"), _Ev(2, 3, "T4"), _Ev(None, None, "T5")]
    assert lr.last_score_change_wallclock(events) == "T3"
    assert lr.last_score_change_wallclock([_Ev(0, 0, "T0"), _Ev(0, 0, "T1")]) == ""
    assert lr.last_score_change_wallclock([]) == ""
    # The change itself carries no wall clock: unknown, not the previous change's time.
    assert lr.last_score_change_wallclock([_Ev(2, 0, "T1"), _Ev(4, 0, "")]) == ""


def _live_game():
    g = Game("ncaab", state="in")
    g.shot(1, "15:00", "home", "h1").shot(1, "14:00", "away", "a1", pts=3).shot(1, "13:00", "home", "h2")
    g.foul(1, "12:30", "away", "a2")
    for play, clock in zip(g.plays, ("2026-11-08T17:50:00Z", "2026-11-08T17:54:00Z", "2026-11-08T17:57:00Z",
                                     "2026-11-08T17:58:30Z")):
        play["wallclock"] = clock
    return g


def test_resume_publishes_the_last_scoring_plays_wall_clock():
    _st, _gs, facts = lr.resume_from_summary(_live_game().summary(), date="2026-11-08", as_of=STATE_AT, league="ncaab")
    assert facts.score_source == "official"
    assert facts.score_changed_at == "2026-11-08T17:57:00Z"   # the second home basket, not the later foul


def test_a_header_ahead_of_the_plays_publishes_no_score_change_time():
    g = _live_game()
    summary = g.summary()
    for comp in summary["header"]["competitions"][0]["competitors"]:
        if comp.get("homeAway") == "home":
            comp["score"] = str(int(comp["score"]) + 2)   # a basket ESPN's plays do not carry yet
    out = lr.resume_from_summary(summary, date="2026-11-08", as_of=STATE_AT, league="ncaab")
    assert not isinstance(out, lr.NcaabResimRefusal)
    assert out[2].score_source == "pbp_lagging_header"
    assert out[2].score_changed_at == ""


# ------------------------------------------------------------------------------------------- through the join

def _snapshot(score_changed_at, *, carried=False):
    def simulate(rng, gs, i=[0]):
        i[0] += 1
        return {}, {}, [40, 40], [40, 30 if i[0] % 20 else 45]
    result = lr.resim_live_game({}, None, sims=200, simulate=simulate)
    facts = lr.ResumeFacts("401", "10", "20", 70, 58, 2, 120.0, "home", 400, STATE_AT,
                           score_changed_at=score_changed_at)
    game = lr._lane_row("401", {"home": HOME, "away": AWAY, "source": "odds"}, facts, result)
    return {"games": [lr._carry(game) if carried else game]}


def _row(quote_at):
    return {"kind": "game", "market": "h2h", "segment": "full", "away_team": AWAY, "home_team": HOME,
            "age_seconds": 30.0, "updated_at": quote_at, "game": {"state": "live"},
            "projection": {"model_prob_over": 0.62, "market_fair_prob_over": 0.40, "basis": "ncaab_team_model"}}


def _attach(snapshot, quote_at, sport="ncaab"):
    index = build_live_gameline_index(snapshot, sources=lens_sources_for_sport(sport), sport=sport)
    row = _row(quote_at)
    coverage = attach_live_gamelines([row], index, sport=sport)
    return row, coverage


def test_the_lane_field_reaches_the_joins_hit():
    snap = _snapshot(CHANGED_AT)
    assert snap["games"][0]["gameLens"][0]["liveScoreChangedAt"] == CHANGED_AT
    index = build_live_gameline_index(snap, sources=lens_sources_for_sport("ncaab"), sport="ncaab")
    hits = [hit for _key, hit in index.items()]
    assert len(hits) == 1 and hits[0]["score_changed_at"] == CHANGED_AT and hits[0]["as_of"] == STATE_AT


def test_off_is_not_on_a_quote_after_the_score_change_is_priced_and_the_state_basis_refuses_it(monkeypatch):
    """REACHABILITY: the same row through the real producer and join, under each basis."""
    quote = "2026-11-08 17:58:00+00:00"   # after the change, 120 s before the fetch
    on_row, on_cov = _attach(_snapshot(CHANGED_AT), quote)
    assert on_row.get("live_gameline", {}).get("edge_pp") is not None
    assert REASON_QUOTE_BEHIND_SCORE not in (on_cov.get("withheld_by_reason") or {})
    monkeypatch.setenv(QUOTE_ORDER_BASIS_ENV, "state")
    off_row, off_cov = _attach(_snapshot(CHANGED_AT), quote)
    assert "live_gameline" not in off_row
    assert off_cov["withheld_by_reason"] == {REASON_QUOTE_BEHIND_SCORE: 1}


def test_a_quote_before_the_score_change_is_refused_and_a_lane_without_the_time_keeps_the_old_rule():
    _row_before, cov_before = _attach(_snapshot(CHANGED_AT), "2026-11-08 17:56:00+00:00")
    assert cov_before["withheld_by_reason"] == {REASON_QUOTE_BEHIND_SCORE: 1}
    _row_old, cov_old = _attach(_snapshot(""), "2026-11-08 17:58:00+00:00")
    assert cov_old["withheld_by_reason"] == {REASON_QUOTE_BEHIND_SCORE: 1}


def test_a_carried_lane_keeps_its_score_change_time():
    row, _cov = _attach(_snapshot(CHANGED_AT, carried=True), "2026-11-08 17:58:00+00:00")
    assert row["live_gameline"]["carried_forward"] is True
    assert row["live_gameline"].get("edge_pp") is not None


def test_wncaab_lane_with_the_time_is_still_judged_on_the_state():
    _row_w, cov = _attach(_snapshot(CHANGED_AT), "2026-11-08 17:58:00+00:00", sport="wncaab")
    assert cov["withheld_by_reason"] == {REASON_QUOTE_BEHIND_SCORE: 1}

