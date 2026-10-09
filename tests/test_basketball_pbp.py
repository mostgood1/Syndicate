"""Lane `basketball-native-live-state` (P2): ESPN play-by-play parsing and on-floor reconstruction."""

from __future__ import annotations

import pytest

from syndicate.features.shared import basketball_pbp as pbp
from tests.basketball_pbp_fixtures import AWAY, HOME, Game, full_nba_game


@pytest.mark.parametrize(
    "type_text,text,shooting,kind",
    [
        ("Offensive Charge", "X offensive charge", False, "foul_offensive"),  # no "foul" in the type: was missed
        ("Offensive Foul Turnover", "X offensive foul turnover", False, "turnover"),
        ("Offensive Foul", "X offensive foul", False, "foul_offensive"),
        ("Free Throw - Technical", "X misses technical free throw", True, "free_throw"),
        ("Technical Foul", "X technical foul", False, "foul_technical"),
        ("Defensive 3-Seconds Technical", "X defensive 3-seconds", False, "foul_technical"),
        ("Shooting Foul", "X shooting foul", False, "foul"),
        ("Personal Take Foul", "X take foul", False, "foul"),
        ("PersonalFoul", "Foul on X.", False, "foul"),  # NCAAB CamelCase
        ("MadeFreeThrow", "X misses free throw 1 of 2", False, "free_throw"),
        ("Dead Ball Rebound", "team rebound", False, "rebound_dead"),
        ("Bad Pass\nTurnover", "X bad pass", False, "turnover"),
        ("Official TV Timeout", "", False, "timeout_official"),
        ("OfficialTVTimeOut", "", False, "timeout_official"),
        ("ShortTimeOut", "Texas Tech Timeout", False, "timeout"),
        ("Substitution", "X enters the game for Y", False, "substitution"),
        ("JumpShot", "X makes jumper", True, "shot"),
        ("End Period", "", False, "end_period"),
    ],
)
def test_classify(type_text, text, shooting, kind):
    assert pbp.classify(type_text, text, shooting_play=shooting) == kind


def test_parse_clock_and_elapsed():
    assert pbp.parse_clock("7:49") == 469.0
    assert pbp.parse_clock("45.2") == 45.2
    assert pbp.parse_clock("") is None
    nba, ncaab = pbp.rules_for("nba"), pbp.rules_for("ncaab")
    assert nba.elapsed(2, 720.0) == 720.0
    assert nba.elapsed(5, 0.0) == 2880.0 + 300.0  # first overtime ends
    assert ncaab.elapsed(2, 0.0) == 2400.0
    assert ncaab.foul_bucket(3) == 2  # NCAAB overtime fouls continue the second half


def test_full_game_minutes_score_and_between_period_sub():
    g = full_nba_game()
    rec = pbp.reconstruct(g.summary(), "nba", date="2026-01-15")
    secs = pbp.player_seconds(rec.stints)
    minutes = {p: round(s / 60.0, 2) for p, s in secs.items()}
    # h1 sat 6:00 of Q1 then came back at the (unlogged) quarter break; h6 never appears in Q2
    assert minutes["h1"] == 42.0 and minutes["h6"] == 6.0
    assert minutes["h2"] == 24.0 and minutes["h7"] == 24.0  # swapped at the Q3 tip, nobody swapped back
    assert minutes["h3"] == minutes["h4"] == minutes["h5"] == 48.0
    assert minutes["a5"] == 43.0 and minutes["a6"] == 5.0
    for side, ids in (("home", HOME), ("away", AWAY)):
        assert sum(secs.get(p, 0.0) for p in ids) == pytest.approx(5 * 2880.0)
    assert pbp.reconstructed_score(rec.events) == {"home": 8, "away": 7}
    assert rec.anomalies == 0
    assert all(len(st.lineup) == 5 for st in rec.stints)
    assert len(rec.lineups_at) == len(rec.events)


def test_free_throws_around_a_substitution_land_on_the_right_five():
    rec = pbp.reconstruct(full_nba_game().summary(), "nba")
    q4_away = [st for st in rec.stints if st.side == "away" and st.period == 4]
    with_a5 = [st for st in q4_away if "a5" in st.lineup]
    with_a6 = [st for st in q4_away if "a6" in st.lineup]
    assert sum(st.pts_for for st in with_a5) == 1  # FT 1 of 2, before the sub
    assert sum(st.pts_for for st in with_a6) == 3  # FT 2 of 2 after it, then a6's jumper


def test_ncaab_single_player_subs_in_either_order_at_one_clock():
    g = Game("ncaab")
    g.shot(1, "19:00", "home", "h1")
    g.sub_in(1, "15:00", "home", "h6").sub_out(1, "15:00", "home", "h1")  # IN logged before OUT
    g.shot(1, "10:00", "home", "h6").end_period(1)
    g.shot(2, "19:00", "home", "h6").end_period(2)
    rec = pbp.reconstruct(g.summary(), "ncaab")
    minutes = {p: s / 60.0 for p, s in pbp.player_seconds(rec.stints).items()}
    assert minutes["h1"] == pytest.approx(5.0) and minutes["h6"] == pytest.approx(35.0)
    assert rec.anomalies == 0 and all(len(st.lineup) == 5 for st in rec.stints)


def test_player_acting_off_floor_is_put_on_and_counted():
    g = Game("ncaab")
    g.shot(1, "19:00", "home", "h1").shot(1, "18:00", "home", "h2").shot(1, "17:00", "home", "h3").shot(1, "16:00", "home", "h4")
    g.shot(1, "10:00", "home", "h6")  # h6 was never subbed in; h5 is the idle one
    g.end_period(1).end_period(2)
    rec = pbp.reconstruct(g.summary(), "ncaab")
    assert rec.anomalies == 1 and any("acting_off_floor_h6" in n for n in rec.notes)
    minutes = {p: s / 60.0 for p, s in pbp.player_seconds(rec.stints).items()}
    assert minutes["h5"] == pytest.approx(10.0)  # out at 10:00 of the first half, never back
    assert minutes["h6"] > 0


def test_sub_logged_after_the_first_play_at_the_same_clock_is_not_a_gap():
    g = Game("nba")
    g.rebound(1, "6:00", "home", "h6")  # ESPN writes h6's play first ...
    g.sub(1, "6:00", "home", "h6", "h1")  # ... then the substitution that put him on
    g.end_period(1).end_period(2).end_period(3).end_period(4)
    rec = pbp.reconstruct(g.summary(), "nba")
    minutes = {p: s / 60.0 for p, s in pbp.player_seconds(rec.stints).items()}
    assert rec.anomalies == 0
    assert minutes["h1"] == pytest.approx(6.0) and minutes["h6"] == pytest.approx(42.0)


def test_personal_fouls_follow_box_rules():
    g = Game("nba")
    g.foul(1, "10:00", "home", "h1").foul(1, "9:00", "home", "h1", "Offensive Charge")
    g.foul(1, "8:00", "home", "h1", "Technical Foul").foul(1, "7:00", "home", "h1", "Offensive Foul")
    events = pbp.normalize_plays(g.summary(), pbp.game_meta(g.summary(), "nba"))
    assert pbp.personal_fouls(events, "nba") == {"h1": 3}  # the technical is not a personal foul


def test_pair_seconds_cover_every_teammate_pair():
    rec = pbp.reconstruct(full_nba_game().summary(), "nba")
    pairs = pbp.pair_seconds(rec.stints)
    assert pairs[("home", "h3", "h4")][0] == pytest.approx(2880.0)
    assert ("home", "h1", "h6") not in pairs  # never on the floor together


def test_live_game_leaves_the_current_stint_open():
    g = Game("nba", state="in")
    g.shot(1, "11:00", "home", "h1").sub(1, "8:00", "home", "h6", "h1").shot(1, "7:30", "away", "a1")
    rec = pbp.reconstruct(g.summary(), "nba")
    open_home = [st for st in rec.stints if st.side == "home" and st.open]
    assert len(open_home) == 1 and "h6" in open_home[0].lineup
    assert open_home[0].end_elapsed == pytest.approx(270.0)  # 4:30 into the game: the last play
    assert rec.on_floor["home"] == sorted(["h2", "h3", "h4", "h5", "h6"])
