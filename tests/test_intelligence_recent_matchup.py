"""Recency + matchup sentences (lane intelligence-evidence-coverage). Facts shapes are the ones
prop_evidence emitted on the fleet 2026-10-08."""

from __future__ import annotations

from syndicate.features import intelligence_recent_matchup as rm

_WNBA_RECENT = {
    "games": 10,
    "hit_rate": {"games": 10, "over": 4, "under": 6, "push": 0, "hits": 4, "side": "over", "line": 12.5, "rate": 0.4},
    "values": [15.0, 15.0, 8.0, 15.0, 16.0, 4.0, 10.0, 5.0, 7.0, 11.0],
    "newest_game": "2026-10-04",
    "stale_days": 3,
}
_WNBA_MATCHUP = {
    "opponent": "ATL",
    "vs_opponent": {"games": 4, "hit_rate": {"games": 4, "over": 4, "under": 0, "push": 0, "hits": 4, "side": "over", "line": 12.5, "rate": 1.0}},
    "opponent_advanced": {"pace": 82.83, "def_rtg": 95.53250897467984},
}


def test_recent_form_sentence():
    assert rm.recent_form_text(_WNBA_RECENT) == "Recent form: over 12.5 in 4 of the last 10 (avg 10.6)."


def test_matchup_sentence_basketball():
    text = rm.matchup_text(_WNBA_MATCHUP)
    assert text == "Matchup: over 12.5 in 4 of 4 vs ATL; ATL defensive rating 95.5, pace 82.8."


def test_matchup_nhl_ncaaf_nfl_soccer_opponent_details():
    nhl = rm.matchup_text({"team": "ANA", "opponent": "EDM", "opponent_profile": {"xg": {"xgf60": 3.37, "xga60": 3.1323}}})
    assert nhl == "Matchup: EDM allows 3.13 xG/60."
    ncaaf = rm.matchup_text({"opponent": "Kennesaw State", "allowed_per_game": 173.5294, "allowed_rank": "112 of 134"})
    assert ncaaf == "Matchup: Kennesaw State allows 173.5 per game, rank 112 of 134."
    nfl = rm.matchup_text({"opponent": "GB", "opponent_points_allowed": [39.0, 17.0, 35.0, 14.0]})
    assert nfl == "Matchup: GB has allowed 26.2 points a game (4 games)."
    soccer = rm.matchup_text({"opponent": "Lyon", "opponent_rating": {"xg_against_per_match": 1.3424}})
    assert soccer == "Matchup: Lyon concedes 1.34 xG a match."


def test_stale_recent_form_says_so():
    stale = dict(_WNBA_RECENT, stale_days=120)
    assert "(newest game 120 days ago)" in rm.recent_form_text(stale)


def test_empty_facts_give_nothing():
    assert rm.recent_form_text({}) is None and rm.matchup_text({}) is None
    assert rm.recent_form_text(None) is None and rm.matchup_text({"opponent": "X"}) is None


def test_row_text_is_memoised_per_bet_and_never_raises(monkeypatch):
    import syndicate.features.shared.prop_evidence as pe

    calls = []

    class Layer:
        RECENT_FORM = "recent"
        MATCHUP = "matchup"

    class Ev:
        def __init__(self):
            self.layers = {
                "recent": type("L", (), {"facts": _WNBA_RECENT})(),
                "matchup": type("L", (), {"facts": _WNBA_MATCHUP})(),
            }

    import syndicate.features.shared.prop_evidence.contract as contract

    monkeypatch.setattr(contract, "Layer", Layer)
    monkeypatch.setattr(pe, "build_prop_evidence", lambda row, selected_date: calls.append(1) or Ev())
    row = {"kind": "prop", "sport": "wnba", "player_name": "Jonquel Jones", "market": "player_rebounds_assists",
           "line": 12.5, "side": "over", "home_team": "Atlanta Dream", "away_team": "New York Liberty"}
    memo: dict = {}
    first = rm.prop_recent_matchup_text(row, selected_date="2026-10-07", memo=memo)
    again = rm.prop_recent_matchup_text(dict(row, bookmaker="dk", odds=110), selected_date="2026-10-07", memo=memo)
    assert first == again and len(calls) == 1
    assert first.startswith("Recent form:") and "Matchup:" in first

    monkeypatch.setattr(pe, "build_prop_evidence", lambda row, selected_date: (_ for _ in ()).throw(RuntimeError("x")))
    assert rm.prop_recent_matchup_text(dict(row, line=13.5), selected_date="2026-10-07", memo=memo) is None
    assert rm.prop_recent_matchup_text({"kind": "game", "sport": "nba"}, selected_date="2026-10-07") is None
