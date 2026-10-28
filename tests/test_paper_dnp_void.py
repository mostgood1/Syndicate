"""#744 void re-scope: a paper bet on a player who did not play settles as a void.

User decision 2026-10-28, verbatim "Yes, void them" (to "Should paper settle a
sat-out prop as a void, stake back and out of ROI?"). A void is a push with
`void_reason`, $0, its stake out of the ROI denominator; NBA learns to say "did
not play" from ESPN by athlete ID. Reachability first (`off != on`), then the
rules. No network: every ESPN read is a stub.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from syndicate.features.shared import bet_status_nba as nba
from syndicate.features.shared import bet_status_nfl as nfl
from syndicate.features.shared import paper_settlement as ps

DNP = "nba_player_did_not_play_void"


def _order(**overrides):
    order = {
        "sport": "nba",
        "mode": "paper",
        "venue": "paper",
        "status": "filled",
        "market": "player_rebounds",
        "side": "over",
        "line": 5.5,
        "player_name": "Kawhi Leonard",
        "home_team": "Minnesota Timberwolves",
        "away_team": "Toronto Raptors",
        "commence_time": "2026-10-25T23:10:00Z",
        "selected_date": "2026-10-25",
        "fill_stake_dollars": 10.0,
        "fill_price": -110,
    }
    order.update(overrides)
    return order


def _refusing(reason, **extra):
    return lambda _order: {"unavailable_reason": reason, **extra}


# --------------------------------------------------------------------------
# Reachability: the switch must change the answer, or nothing below matters.
# --------------------------------------------------------------------------


def test_the_switch_REACHES_the_verdict_off_refuses_on_voids(monkeypatch):
    monkeypatch.setenv(ps.DNP_VOID_ENV, "off")
    off = ps._our_verdict(_order(), _refusing(DNP))
    monkeypatch.delenv(ps.DNP_VOID_ENV)
    on = ps._our_verdict(_order(), _refusing(DNP))

    assert off[0] is None and off[2] == DNP
    assert on[0] is not None and on[0]["void_reason"] == DNP
    assert off != on


def test_absent_switch_is_ON_because_the_decision_is_made(monkeypatch):
    monkeypatch.delenv(ps.DNP_VOID_ENV, raising=False)
    assert ps.dnp_void_enabled() is True


def test_the_allowlist_is_each_resolvers_OWN_constant():
    from syndicate.features.shared import bet_status_nhl, bet_status_soccer

    assert ps.DNP_VOID_REASONS == {
        nfl.REASON_DNP_VOID,
        bet_status_nhl.REASON_DNP_VOID,
        bet_status_soccer.REASON_DNP_VOID,
        nba.REASON_DNP_VOID,
    }


# --------------------------------------------------------------------------
# The void verdict.
# --------------------------------------------------------------------------


@pytest.mark.parametrize("reason", sorted(ps.DNP_VOID_REASONS))
def test_every_dnp_reason_settles_as_a_zero_dollar_push_with_its_reason(monkeypatch, reason):
    monkeypatch.delenv(ps.DNP_VOID_ENV, raising=False)
    verdict, _resolved, refusal = ps._our_verdict(_order(), _refusing(reason))

    assert refusal == ""
    assert verdict["outcome"] == ps.OUTCOME_PUSH
    assert verdict["pnl_dollars"] == 0.0 and verdict["pnl_gross_dollars"] == 0.0
    assert verdict["void_reason"] == reason


@pytest.mark.parametrize(
    "reason", ["player_not_in_box", "nba_player_not_on_either_team_roster", "nba_player_played_but_not_in_box", "stat_not_in_box"]
)
def test_a_refusal_that_is_NOT_a_did_not_play_never_voids(monkeypatch, reason):
    monkeypatch.delenv(ps.DNP_VOID_ENV, raising=False)
    verdict, _resolved, refusal = ps._our_verdict(_order(), _refusing(reason))
    assert verdict is None and refusal == reason


def test_an_unfilled_order_is_not_voided_it_was_never_a_bet(monkeypatch):
    monkeypatch.delenv(ps.DNP_VOID_ENV, raising=False)
    verdict, _resolved, refusal = ps._our_verdict(_order(status="submitted"), _refusing(DNP))
    assert verdict is None and refusal == ps.REASON_NOT_FILLED


def test_the_stamped_row_carries_why_and_on_what_evidence(monkeypatch):
    monkeypatch.delenv(ps.DNP_VOID_ENV, raising=False)
    order = _order()
    verdict, resolved, _ = ps._our_verdict(order, _refusing(DNP, dnp_basis="inactive", espn_athlete_id="1966"))
    ps._stamp_grade(order, verdict, resolved)

    assert order["outcome"] == "push" and order["pnl_dollars"] == 0.0
    assert order["void_reason"] == DNP
    assert order["dnp_basis"] == "inactive" and order["espn_athlete_id"] == "1966"
    assert ps._outcome_key(verdict) == "void"


def test_a_void_stays_OUT_of_the_ROI_denominator_and_the_win_rate():
    won = _order(outcome="won", pnl_dollars=9.09)
    lost = _order(outcome="lost", pnl_dollars=-10.0)
    void = _order(outcome="push", pnl_dollars=0.0, void_reason=DNP)

    with_void = ps.settlement_summary(orders=[won, lost, void])["total"]
    without = ps.settlement_summary(orders=[won, lost])["total"]

    assert with_void["void"] == 1 and with_void["push"] == 0
    assert with_void["settled"] == 3
    assert with_void["staked_dollars"] == without["staked_dollars"] == 20.0
    assert with_void["roi_pct"] == without["roi_pct"]
    assert with_void["win_pct"] == without["win_pct"]


# --------------------------------------------------------------------------
# NBA: did he play? ESPN by athlete ID, never by name.
# --------------------------------------------------------------------------

CORE = "https://sports.core.api.espn.com/v2/sports/basketball/leagues/nba/events/401909864/competitions/401909864"
SITE = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/{}/roster"


def _entries(team_ids, extra=()):
    rows = [{"playerId": f"{team}{n}", "didNotPlay": False, "statistics": {"$ref": "x"}} for team in team_ids for n in range(8)]
    return rows + list(extra)


def _espn(game_extra=(), team_athletes=None, *, roster_rows=None):
    """A stubbed ESPN: TOR (28) and MIN (16), Kawhi Leonard = athlete 6450 on TOR."""
    team_athletes = team_athletes if team_athletes is not None else {
        "28": [{"id": "6450", "fullName": "Kawhi Leonard", "firstName": "Kawhi", "lastName": "Leonard"}],
        "16": [{"id": "4431", "fullName": "Anthony Edwards"}],
    }
    entries = roster_rows if roster_rows is not None else _entries(["28", "16"], game_extra)
    pages = {
        f"{CORE}/competitors": {"items": [{"id": "16"}, {"id": "28"}]},
        f"{CORE}/competitors/16/roster": {"entries": [e for e in entries if str(e["playerId"]).startswith("16")]},
        f"{CORE}/competitors/28/roster": {"entries": [e for e in entries if not str(e["playerId"]).startswith("16")]},
    }
    for team, athletes in team_athletes.items():
        pages[SITE.format(team)] = {"athletes": athletes} if athletes is not None else None
    calls = []

    def fetch(url):
        calls.append(url)
        return pages.get(url)

    return fetch, calls


def _check(fetch):
    return nba.did_not_play(nfl.EspnSettlementFeed("nba", fetch_json=fetch), "401909864", "Kawhi Leonard")


def test_dressed_and_sat_out_is_a_void():
    fetch, _ = _espn([{"playerId": "6450", "didNotPlay": True, "reason": "LEFT KNEE SWELLING"}])
    out = _check(fetch)
    assert out == {"unavailable_reason": DNP, "dnp_basis": "did_not_play", "espn_athlete_id": "6450"}


def test_inactive_on_the_team_roster_but_off_both_game_rosters_is_a_void():
    fetch, _ = _espn()
    out = _check(fetch)
    assert out == {"unavailable_reason": DNP, "dnp_basis": "inactive", "espn_athlete_id": "6450"}


def test_he_PLAYED_and_our_box_missed_him_refuses_it_never_voids():
    fetch, _ = _espn([{"playerId": "6450", "didNotPlay": False, "statistics": {"$ref": "x"}}])
    assert _check(fetch) == {"unavailable_reason": nba.REASON_PLAYED_NOT_IN_BOX}


def test_a_name_no_team_roster_carries_refuses_it_never_voids():
    fetch, _ = _espn(team_athletes={"28": [{"id": "1", "fullName": "Somebody Else"}], "16": [{"id": "2", "fullName": "Anthony Edwards"}]})
    assert _check(fetch) == {"unavailable_reason": nba.REASON_NOT_ON_TEAM_ROSTER}


def test_two_athletes_with_his_name_refuse():
    fetch, _ = _espn(team_athletes={"28": [{"id": "6450", "fullName": "Kawhi Leonard"}], "16": [{"id": "9", "fullName": "Kawhi Leonard"}]})
    assert _check(fetch) == {"unavailable_reason": nba.REASON_ROSTER_AMBIGUOUS}


def test_a_partial_game_roster_cannot_say_he_was_absent():
    fetch, _ = _espn(roster_rows=[{"playerId": "281", "didNotPlay": False, "statistics": {}}, {"playerId": "161", "didNotPlay": False, "statistics": {}}])
    assert _check(fetch) == {"unavailable_reason": nba.REASON_ROSTER_UNAVAILABLE}


def test_an_unreadable_team_roster_cannot_say_he_was_absent():
    fetch, _ = _espn(team_athletes={"28": None, "16": [{"id": "4431", "fullName": "Anthony Edwards"}]})
    assert _check(fetch) == {"unavailable_reason": nba.REASON_ROSTER_UNAVAILABLE}


# --------------------------------------------------------------------------
# NBA resolver: the ESPN check is reached only for a FINAL game past the window.
# --------------------------------------------------------------------------


def _box(final=True, state="post"):
    game = {"event_id": "401909864", "state": state, "final": final, "home_tri": "MIN", "away_tri": "TOR",
            "home_score": 110, "away_score": 100, "_players": {}}
    return {"by_event": {"401909864": game}, "by_matchup": {nba._matchup_key("TOR", "MIN"): game}}


def _at(monkeypatch, iso):
    monkeypatch.setattr(nfl, "_utcnow", lambda: datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(timezone.utc))


def test_resolver_final_game_absent_player_reaches_ESPN_and_voids(monkeypatch):
    monkeypatch.setattr(nba, "_load_box", lambda _d: _box())
    _at(monkeypatch, "2026-10-28T12:00:00Z")
    fetch, calls = _espn([{"playerId": "6450", "didNotPlay": True}])
    out = nba.nba_status_resolver("2026-10-25", fetch_json=fetch)(_order(event_id="oddsapi-hash"))
    assert out["unavailable_reason"] == DNP and calls


def test_resolver_game_NOT_final_never_reaches_the_network(monkeypatch):
    monkeypatch.setattr(nba, "_load_box", lambda _d: _box(final=False, state="in"))
    _at(monkeypatch, "2026-10-28T12:00:00Z")
    fetch, calls = _espn()
    out = nba.nba_status_resolver("2026-10-25", fetch_json=fetch)(_order())
    assert out == {"unavailable_reason": nba.REASON_PLAYER_NOT_FOUND} and calls == []


def test_resolver_inside_the_six_hour_window_never_reaches_the_network(monkeypatch):
    monkeypatch.setattr(nba, "_load_box", lambda _d: _box())
    _at(monkeypatch, "2026-10-26T02:00:00Z")  # tip 10-25 23:10Z + 2 h 50 m
    fetch, calls = _espn()
    out = nba.nba_status_resolver("2026-10-25", fetch_json=fetch)(_order())
    assert out == {"unavailable_reason": nba.REASON_PLAYER_NOT_FOUND} and calls == []


def test_end_to_end_the_resolver_and_the_grader_settle_a_sat_out_prop_as_void(monkeypatch):
    monkeypatch.delenv(ps.DNP_VOID_ENV, raising=False)
    monkeypatch.setattr(nba, "_load_box", lambda _d: _box())
    _at(monkeypatch, "2026-10-28T12:00:00Z")
    fetch, _ = _espn()
    order = _order()
    verdict, resolved, refusal = ps._our_verdict(order, nba.nba_status_resolver("2026-10-25", fetch_json=fetch))
    assert refusal == "" and verdict["void_reason"] == DNP and resolved["dnp_basis"] == "inactive"
