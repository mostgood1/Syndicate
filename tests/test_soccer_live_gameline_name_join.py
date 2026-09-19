# -*- coding: utf-8 -*-
"""The live soccer game-line join on CANONICAL team names plus the pricer-only name table, through the real producer
and the unmodified shared join.

Every pair below is REAL. `REAL_PAIRS_2026_09_18` was read on production: the board's name (OddsAPI, on the served
soccer book grid) against the live state's name (ESPN, on the served `live_state`), for the eight matches in play
at 19:29Z; the exact key joined 3 of them. `WEEKEND_PAIRS_2026_09_19_20` are the 18 fixtures of that weekend whose
production odds name and ESPN scoreboard name still differed after canonicalisation, plus the one match read unjoined
on the live board on 2026-09-19 (1. FC Koln / FC Cologne). `learnings.md` 2026-09-05 forbids a join test whose fixture builds both
sides from one set of names, so the two sides here are never the same list, and pairs that must NOT join are
asserted as well as pairs that must.
"""
from __future__ import annotations

import json

import pytest

from syndicate.features.shared import soccer_live_gameline_source as src
from syndicate.features.shared.live_gameline_join import REASON_NO_LIVE_PROJECTION, attach_live_gamelines

DATE = "2026-09-18"

# (league, board away, board home, live-state away, live-state home, joins on canonical names)
REAL_PAIRS_2026_09_18 = [
    ("championship", "Watford", "Bristol City", "Watford", "Bristol City", True),
    ("epl", "Chelsea", "Brentford", "Chelsea", "Brentford", True),
    ("serie_a", "Sassuolo", "Monza", "Sassuolo", "Monza", True),
    ("bundesliga", "Union Berlin", "Bayern Munich", "1. FC Union Berlin", "Bayern Munich", True),
    ("la_liga", "Elche CF", "Espanyol", "Elche", "Espanyol", True),
    ("ligue_1", "RC Lens", "AS Monaco", "Lens", "AS Monaco", True),
    # A club prefix the canonicaliser keeps; joined by the pricer-only table (user decision 2026-09-18).
    ("belgian_pro_league", "Standard Liege", "Gent", "Standard Liege", "KAA Gent", True),
    ("eredivisie", "FC Zwolle", "Groningen", "PEC Zwolle", "FC Groningen", True),
]

# (league, odds away, odds home, ESPN away, ESPN home): production book_quotes h2h vs the ESPN scoreboard.
WEEKEND_PAIRS_2026_09_19_20 = [
    ("belgian_pro_league", "RAAL La Louvi\u00e8re", "Leuven", "RAAL La Louvi\u00e8re", "OH Leuven"),
    ("belgian_pro_league", "Cercle Brugge KSV", "Charleroi", "Cercle Brugge KSV", "Royal Charleroi SC"),
    ("belgian_pro_league", "Union Saint-Gilloise", "Royal Antwerp", "Union St.-Gilloise", "Antwerp"),
    ("belgian_pro_league", "Westerlo", "Sint Truiden", "KVC Westerlo", "Sint-Truidense"),
    ("belgian_pro_league", "Genk", "Club Brugge", "Racing Genk", "Club Brugge"),
    ("belgian_pro_league", "SK Beveren", "KV Kortrijk", "Waasland-Beveren", "KV Kortrijk"),
    ("bundesliga", "FSV Mainz 05", "Borussia Monchengladbach", "Mainz", "Borussia M\u00f6nchengladbach"),
    ("eredivisie", "Excelsior", "Ajax", "Excelsior", "Ajax Amsterdam"),
    ("eredivisie", "FC Utrecht", "Feyenoord", "FC Utrecht", "Feyenoord Rotterdam"),
    ("eredivisie", "PSV Eindhoven", "FC Twente Enschede", "PSV Eindhoven", "FC Twente"),
    ("la_liga", "Rayo Vallecano", "CA Osasuna", "Rayo Vallecano", "Osasuna"),
    ("la_liga", "Alav\u00e9s", "Athletic Bilbao", "Alav\u00e9s", "Athletic Club"),
    ("la_liga", "Real Racing Club de Santander", "Celta Vigo", "Racing Santander", "Celta Vigo"),
    ("primeira_liga", "Famalic\u00e3o", "Nacional", "FC Famalicao", "C.D. Nacional"),
    ("primeira_liga", "CS Maritimo", "Gil Vicente", "Maritimo", "Gil Vicente"),
    ("primeira_liga", "Arouca", "Sporting Lisbon", "Arouca", "Sporting CP"),
    ("primeira_liga", "Moreirense FC", "Vit\u00f3ria SC", "Moreirense", "Vit\u00f3ria de Guimaraes"),
    ("serie_a", "Atalanta BC", "Juventus", "Atalanta", "Juventus"),
    # Not in the audit (four events shared its kickoff, so it could not be paired); read unjoined on the live
    # board 2026-09-19 14:49Z, the one residual that morning.
    ("bundesliga", "1. FC Köln", "Hamburger SV", "FC Cologne", "Hamburg SV"),
]


def _projection():
    return {"simulations": 80, "home_win_probability": 0.5, "draw_probability": 0.27, "away_win_probability": 0.23,
            "projected_final_home_goals": 1.4, "projected_final_away_goals": 1.1, "projected_final_total": 2.5,
            "over_2_5_probability": 0.5}


def _write_live(root, league, games):
    d = root / "soccer_source" / league / "api" / "live_state"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"live_state_{DATE}.json").write_text(json.dumps(
        {"league": league, "date": DATE, "generated_at": "2026-09-18T19:29:00+00:00", "games": games, "match_box": {}}),
        encoding="utf-8")


def _live_game(event_id, away, home, league):
    return {"event_id": event_id, "league": league, "away_team": away, "home_team": home,
            "status_display_clock": "30'", "score_home": 0, "score_away": 0, "projection": _projection()}


def _board_row(away, home):
    """A live full-game h2h board row, shaped the way the shared join reads one."""
    return {"kind": "game", "market": "h2h", "segment": "full", "away_team": away, "home_team": home,
            "game": {"state": "live"}, "age_seconds": 5, "projection": {}}


@pytest.fixture
def real_slate(tmp_path):
    for i, (league, _ba, _bh, la, lh, _joins) in enumerate(REAL_PAIRS_2026_09_18):
        _write_live(tmp_path, league, {str(1000 + i): _live_game(str(1000 + i), la, lh, league)})
    return tmp_path


def _missed(index, away, home):
    coverage = attach_live_gamelines([_board_row(away, home)], index, sport="soccer")
    return coverage["withheld_by_reason"].get(REASON_NO_LIVE_PROJECTION, 0) == 1


# ---------------------------------------------------------------------------- end to end first

def test_the_real_2026_09_18_slate_joins_eight_of_eight_through_the_shared_join(real_slate):
    """3 of 8 on the exact key (the production reading), 6 of 8 on canonical names alone, 8 of 8 with the pricer-only
    table. Fails on the pre-change code."""
    index = src.soccer_live_gameline_index(DATE, data_root=real_slate)
    joined = {(league, ba, bh): not _missed(index, ba, bh) for league, ba, bh, _la, _lh, _j in REAL_PAIRS_2026_09_18}
    assert joined == {(league, ba, bh): j for league, ba, bh, _la, _lh, j in REAL_PAIRS_2026_09_18}
    assert sum(joined.values()) == 8


def test_every_measured_weekend_residual_joins_through_the_shared_join(tmp_path):
    by_league = {}
    for i, (league, _oa, _oh, ea, eh) in enumerate(WEEKEND_PAIRS_2026_09_19_20):
        by_league.setdefault(league, {})[str(2000 + i)] = _live_game(str(2000 + i), ea, eh, league)
    for league, games in by_league.items():
        _write_live(tmp_path, league, games)
    index = src.soccer_live_gameline_index(DATE, data_root=tmp_path)
    assert len(index) == len(WEEKEND_PAIRS_2026_09_19_20)
    missed = [(oa, oh) for _lg, oa, oh, _ea, _eh in WEEKEND_PAIRS_2026_09_19_20 if _missed(index, oa, oh)]
    assert missed == []
    # and each odds pair finds ITS OWN fixture, not a neighbour's
    for league, oa, oh, _ea, _eh in WEEKEND_PAIRS_2026_09_19_20:
        assert index.get((oa, oh))["league"] == league


def test_the_pricer_table_is_written_in_canonical_form_and_never_chains():
    from syndicate.features.soccer.features.team_names import canonical_team_name

    table = src._PRICER_NAME_ALIASES
    for variant, target in table.items():
        assert canonical_team_name(variant) == variant and canonical_team_name(target) == target, (variant, target)
    assert not set(table.values()) & set(table), "a target that is also a key would chain"


@pytest.mark.parametrize("board,live", [
    (("Sporting Braga", "Arouca"), ("Sporting CP", "Arouca")),        # a different Sporting
    (("Racing Genk", "Celta Vigo"), ("Racing Santander", "Celta Vigo")),  # two Racings
    (("Vitoria Setubal", "Arouca"), ("Vitoria de Guimaraes", "Arouca")),  # a different Vitoria
])
def test_the_table_does_not_merge_different_clubs(tmp_path, board, live):
    _write_live(tmp_path, "primeira_liga", {"1": _live_game("1", live[0], live[1], "primeira_liga")})
    index = src.soccer_live_gameline_index(DATE, data_root=tmp_path)
    assert _missed(index, *board)


@pytest.mark.parametrize("league,ba,bh,la,lh,joins", REAL_PAIRS_2026_09_18)
def test_each_real_pair_finds_its_own_match_and_no_other(real_slate, league, ba, bh, la, lh, joins):
    index = src.soccer_live_gameline_index(DATE, data_root=real_slate)
    hit = index.get(("  " + ba.upper() + " ", bh.lower()))       # the shared join's own key shape: case and spacing
    if joins:
        assert hit is not None and hit["league"] == league
    else:
        assert hit is None


# ---------------------------------------------------------------------------- what must never join

def test_home_and_away_swapped_do_not_join(real_slate):
    index = src.soccer_live_gameline_index(DATE, data_root=real_slate)
    assert _missed(index, "Bristol City", "Watford")
    assert _missed(index, "Bayern Munich", "Union Berlin")


def test_a_different_club_never_joins(real_slate):
    index = src.soccer_live_gameline_index(DATE, data_root=real_slate)
    assert _missed(index, "Hertha Berlin", "Bayern Munich")         # shares a city token with Union Berlin
    assert _missed(index, "Chelsea", "Brentford FC Women")


def test_two_live_matches_collapsing_to_one_canonical_pair_price_neither(tmp_path, capsys):
    _write_live(tmp_path, "epl", {"1": _live_game("1", "Arsenal", "Chelsea", "epl")})
    _write_live(tmp_path, "championship", {"2": _live_game("2", "Arsenal FC", "Chelsea FC", "championship")})
    index = src.soccer_live_gameline_index(DATE, data_root=tmp_path)
    assert index.get(("arsenal", "chelsea")) is None and ("arsenal", "chelsea") not in index
    with pytest.raises(KeyError):
        index[("arsenal", "chelsea")]
    assert "AMBIGUOUS_CANONICAL_KEY" in capsys.readouterr().out


def test_a_malformed_key_is_a_miss_not_an_error(real_slate):
    index = src.soccer_live_gameline_index(DATE, data_root=real_slate)
    assert index.get("not a pair") is None and index.get(None, "d") == "d"
