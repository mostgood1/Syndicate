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


def _mlb_root(tmp_path, monkeypatch):
    import json as _json

    root = tmp_path / "mlb"
    (root / "processed").mkdir(parents=True)
    (root / "processed" / "mlb_batter_game_log.csv").write_text(
        "date,game_pk,player_id,player_name,team,opponent,ab,h,r,rbi,hr,bb,so,tb\n"
        + "".join(f"2026-09-{d:02d},1,643289,Mauricio Dubon,ATL,X,4,{d % 2},0,{1 if d % 3 == 0 else 0},0,0,1,1\n" for d in range(1, 13)),
        encoding="utf-8",
    )
    (root / "processed" / "mlb_pitcher_game_log.csv").write_text(
        "date,game_pk,player_id,player_name,team,opponent,is_starter,ip,outs,pitches,k,bb,er,h,r,hr\n"
        "2026-09-20,1,607259,Nick Martinez,TB,X,1,6.0,18,90,7,1,2,5,2,1\n"
        "2026-09-26,2,607259,Nick Martinez,TB,X,1,5.0,15,85,4,2,3,6,3,0\n",
        encoding="utf-8",
    )
    snap = root / "daily" / "snapshots" / "2026-10-07"
    snap.mkdir(parents=True)
    (snap / "probables.json").write_text(_json.dumps({"games": [{
        "home": {"abbr": "ATL"}, "away": {"abbr": "LAD"},
        "home_probable_id": 111, "away_probable_id": 677,
        "home_validation": {"selected_name": "Spencer Strider"}, "away_validation": {"selected_name": "Tyler Glasnow"},
    }]}), encoding="utf-8")
    bvp = root / "statcast" / "bvp"
    bvp.mkdir(parents=True)
    (bvp / f"bvp_pairs_{677 % 64:02d}.json").write_text(_json.dumps({
        "fields": ["pa", "hits", "hr", "so", "bb", "hbp", "inplay_pa", "inplay_hits"],
        "pitchers": {"677": {"643289": [11, 4, 2, 3, 1, 0, 7, 4]}},
    }), encoding="utf-8")
    monkeypatch.setenv("SYNDICATE_MLB_DATA_ROOT", str(root))
    return root


def test_mlb_batter_gets_recent_form_and_career_bvp_vs_the_opposing_starter(tmp_path, monkeypatch):
    _mlb_root(tmp_path, monkeypatch)
    row = {"kind": "prop", "sport": "mlb", "market": "batter_rbis", "line": 0.5, "side": "over", "player_name": "Mauricio Dubon",
           "home_team": "Atlanta Braves", "away_team": "Los Angeles Dodgers", "projection": {"player_id": "643289"}}
    text = rm.mlb_prop_recent_matchup_text(row, selected_date="2026-10-07")
    # last 10 logged games are 09-03..09-12; rbi=1 on 09-03,06,09,12 -> 4 of 10
    assert "Recent form: over 0.5 in 4 of the last 10 logged games (avg 0.4; log since 2026-09-03)." in text
    # ATL batter faces the AWAY starter
    assert "Matchup: vs Tyler Glasnow (career) 4 hits in 11 PA, 2 HR, 3 K, 1 BB." in text


def test_mlb_pitcher_gets_recent_form_from_starts(tmp_path, monkeypatch):
    _mlb_root(tmp_path, monkeypatch)
    row = {"kind": "prop", "sport": "mlb", "market": "pitcher_strikeouts", "line": 5.5, "side": "over", "player_name": "Nick Martinez",
           "home_team": "New York Yankees", "away_team": "Tampa Bay Rays", "projection": {"player_id": "607259"}}
    text = rm.mlb_prop_recent_matchup_text(row, selected_date="2026-10-07")
    assert text == "Recent form: over 5.5 in 1 of the last 2 logged games (avg 5.5; log since 2026-09-20)."


def test_mlb_first_meeting_and_missing_id(tmp_path, monkeypatch):
    _mlb_root(tmp_path, monkeypatch)
    row = {"kind": "prop", "sport": "mlb", "market": "batter_hits", "line": 0.5, "side": "over", "player_name": "X",
           "home_team": "Atlanta Braves", "away_team": "Los Angeles Dodgers", "projection": {"player_id": "999"}}
    assert rm.mlb_prop_recent_matchup_text(row, selected_date="2026-10-07") is None  # no log -> no team -> no starter
    assert rm.mlb_prop_recent_matchup_text(dict(row, projection={}), selected_date="2026-10-07") is None
