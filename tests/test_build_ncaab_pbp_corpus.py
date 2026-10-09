"""NCAAB pbp backtest corpus (lane ncaab-native-live-tier)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "build_ncaab_pbp_corpus", Path(__file__).resolve().parents[1] / "scripts" / "build_ncaab_pbp_corpus.py"
)
corpus = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(corpus)


def _team_box(tid, name):
    return {
        "team": {"id": tid, "location": name},
        "statistics": [
            {"name": "fieldGoalsMade-fieldGoalsAttempted", "displayValue": "25-60"},
            {"name": "freeThrowsMade-freeThrowsAttempted", "displayValue": "10-15"},
            {"name": "offensiveRebounds", "displayValue": "9"},
            {"name": "totalTurnovers", "displayValue": "11"},
        ],
    }


def _payload(final=(70, 65), last_play=(70, 65), game_note="", season_type=2):
    plays = [
        {"id": "p1", "sequenceNumber": "1", "type": {"id": "615"}, "period": {"number": 1}, "clock": {"displayValue": "20:00"}, "homeScore": 0, "awayScore": 0, "wallclock": "2026-01-16T03:16:01Z"},
        {"id": "p2", "sequenceNumber": "2", "type": {"id": "558"}, "period": {"number": 1}, "clock": {"displayValue": "19:31"}, "homeScore": 2, "awayScore": 0, "team": {"id": "10"}, "participants": [{"athlete": {"id": "77"}}], "scoreValue": 2, "scoringPlay": True, "shootingPlay": True},
        {"id": "p3", "sequenceNumber": "3", "type": {"id": "584"}, "period": {"number": 2}, "clock": {"displayValue": "45.3"}, "homeScore": 60, "awayScore": 60, "team": {"id": "20"}, "text": "Jo Smith subbing in for Away St"},
        {"id": "p4", "sequenceNumber": "4", "type": {"id": "402"}, "period": {"number": 2}, "clock": {"displayValue": "0:00"}, "homeScore": last_play[0], "awayScore": last_play[1]},
    ]
    return {
        "header": {
            "id": "555",
            "season": {"year": 2026, "type": season_type},
            "gameNote": game_note,
            "competitions": [{
                "neutralSite": False,
                "conferenceCompetition": True,
                "competitors": [
                    {"id": "10", "homeAway": "home", "score": str(final[0]), "team": {"id": "10", "location": "Home U"}, "linescores": [{"displayValue": "35"}, {"displayValue": "35"}]},
                    {"id": "20", "homeAway": "away", "score": str(final[1]), "team": {"id": "20", "location": "Away St"}, "linescores": [{"displayValue": "30"}, {"displayValue": "35"}]},
                ],
            }],
        },
        "boxscore": {
            "teams": [_team_box("10", "Home U"), _team_box("20", "Away St")],
            "players": [{"team": {"id": "10"}, "statistics": [{"names": ["MIN", "PTS", "PF"], "athletes": [{"athlete": {"id": "77"}, "starter": True, "stats": ["31", "18", "4"]}]}]}],
        },
        "pickcenter": [{
            "provider": {"name": "DraftKings"},
            "pointSpread": {"home": {"open": {"line": "-3.5"}, "close": {"line": "-4.5"}}},
            "total": {"over": {"open": {"line": "o141.5"}, "close": {"line": "o140.5"}}},
            "moneyline": {"home": {"open": {"odds": "-170"}, "close": {"odds": "-190"}}, "away": {"open": {"odds": "+145"}, "close": {"odds": "EVEN"}}},
        }],
        "winprobability": [{"playId": "p2", "homeWinPercentage": 0.61}],
        "plays": plays,
    }


def test_record_shape_and_final_check():
    r = corpus.parse_record(_payload(), season=2026, day="2026-01-15")
    assert r["v"] == corpus.RECORD_VERSION and r["game_id"] == "555"
    assert r["home"] == {"id": "10", "name": "Home U", "score": 70, "linescores": [35, 35]}
    assert r["check"]["pbp_final_matches"] is True and r["check"]["n_subs"] == 1 and r["check"]["n_wp"] == 1
    cols = r["plays_cols"]
    second = dict(zip(cols, r["plays"][1]))
    assert second == {"seq": 2, "period": 1, "clock": 1171.0, "home": 2, "away": 0, "type": 558, "team": "h", "athlete": "77", "value": 2, "scoring": True, "shooting": True, "wall": None, "wp_home": 0.61, "sub": None}
    assert dict(zip(cols, r["plays"][2]))["clock"] == pytest.approx(45.3)
    assert dict(zip(cols, r["plays"][2]))["team"] == "a"
    assert dict(zip(cols, r["plays"][2]))["sub"] == 1 and r["check"]["n_subs_undirected"] == 0
    assert r["players"] == [["h", "77", True, 31, 4, 18]]
    assert len(r["box_rows"]) == 2 and {row["site"] for row in r["box_rows"]} == {"home", "away"}


def test_lines_open_and_close():
    lines = corpus.parse_record(_payload(), season=2026, day="2026-01-15")["lines"]
    assert lines["spread_home_open"] == -3.5 and lines["spread_home_close"] == -4.5
    assert lines["total_open"] == 141.5 and lines["total_close"] == 140.5
    assert lines["ml_home_close"] == -190 and lines["ml_away_close"] == 100.0


def test_pbp_final_mismatch_is_recorded_not_hidden():
    r = corpus.parse_record(_payload(final=(70, 65), last_play=(68, 65)), season=2026, day="2026-01-15")
    assert r["check"]["pbp_final_matches"] is False and r["check"]["pbp_final"] == [68, 65]


@pytest.mark.parametrize(
    "season_type,note,day,phase",
    [
        (2, "", "2026-01-15", "regular"),
        (2, "Players Era Festival - Championship", "2025-11-27", "regular"),
        (2, "Big East Tournament - Quarterfinal", "2026-03-12", "conf_tournament"),
        (3, "NCAA Men's Basketball Championship - East Region - 1st Round", "2026-03-19", "ncaa_tournament"),
        (3, "NCAA Men's Basketball Championship - West Region - First Four", "2026-03-17", "ncaa_tournament"),
        (3, "NIT - 1st Round", "2026-03-17", "other_postseason"),
        (3, "College Basketball Crown - Quarterfinals", "2026-04-01", "other_postseason"),
    ],
)
def test_phase(season_type, note, day, phase):
    assert corpus.classify_phase(season_type, note, day) == phase
    assert corpus.parse_record(_payload(game_note=note, season_type=season_type), season=2026, day=day)["phase"] == phase


def test_unusable_payload_is_none():
    payload = _payload()
    payload["plays"] = []
    assert corpus.parse_record(payload, season=2026, day="2026-01-15") is None


def test_append_and_read_roundtrip(tmp_path):
    path = tmp_path / "c.jsonl.gz"
    a = corpus.parse_record(_payload(), season=2026, day="2026-01-15")
    corpus.append_record(path, a)
    corpus.append_record(path, {**a, "game_id": "556"})
    assert [r["game_id"] for r in corpus.read_records(path)] == ["555", "556"]


def test_clock_seconds():
    assert corpus.clock_seconds("12:34") == 754.0
    assert corpus.clock_seconds("0:00") == 0.0
    assert corpus.clock_seconds("") is None and corpus.clock_seconds("x") is None


def test_core_odds_fallback_and_live_last_is_labelled():
    payload = {"items": [
        {"provider": {"id": "58"}, "homeTeamOdds": {"open": {"pointSpread": {"american": "-33.5"}}, "close": {"pointSpread": {"american": "-36.5"}, "moneyLine": {"american": "-5000"}}},
         "awayTeamOdds": {"close": {"moneyLine": {"american": "+1800"}}},
         "open": {"total": {"american": "137.5"}}, "close": {"total": {"alternateDisplayValue": "136.5"}}},
        {"provider": {"id": "59"}, "homeTeamOdds": {"current": {"pointSpread": {"american": "-15.5"}}}, "current": {"total": {"american": "136.5"}}},
    ]}
    lines = corpus.parse_core_odds(payload)
    assert lines["spread_home_open"] == -33.5 and lines["spread_home_close"] == -36.5
    assert lines["total_open"] == 137.5 and lines["total_close"] == 136.5
    assert lines["ml_home_close"] == -5000 and lines["ml_away_close"] == 1800 and lines["ml_home_open"] is None
    assert lines["live_last"]["spread_home"] == -15.5 and "not a live close" in lines["live_last"]["note"]
    assert corpus.parse_core_odds({}) == {}


_BSPEC = importlib.util.spec_from_file_location(
    "ncaab_corpus_baseline", Path(__file__).resolve().parents[1] / "scripts" / "ncaab_corpus_baseline.py"
)
baseline = importlib.util.module_from_spec(_BSPEC)
_BSPEC.loader.exec_module(baseline)


def _record(plays, players, gid="g1"):
    cols = list(corpus.PLAY_COLUMNS)
    rows = [[p.get(c) for c in cols] for p in plays]
    return {"game_id": gid, "plays_cols": cols, "plays": rows, "players": players, "check": {"n_subs_undirected": 0}}


def _play(period, clock, home=None, away=None, **kw):
    return {"period": period, "clock": clock, "home": home, "away": away, **kw}


def test_state_at_checkpoint_takes_the_last_scored_play_at_or_before():
    rec = _record([_play(1, 1200, 0, 0), _play(1, 30, 30, 28), _play(1, 0, 32, 28), _play(2, 1150, 34, 28)], [], gid="s1")
    plays = baseline.plays_of(rec)
    assert baseline.state_at(plays, 1200)["home"] == 32  # halftime = the H1 0:00 play
    assert baseline.state_at(plays, 1199)["home"] == 30
    assert baseline.state_at(plays, 1250)["home"] == 34


def test_starter_share_follows_directed_subs_across_the_half():
    starters = [["h", f"h{i}", True, 30, 1, 10] for i in range(5)] + [["a", f"a{i}", True, 30, 1, 10] for i in range(5)]
    plays = [
        _play(1, 1200, 0, 0),
        # h0 out at 15:00 of H1 (elapsed 300), back in at 10:00 (elapsed 600)
        _play(1, 900, 10, 10, type=584, team="h", athlete="h0", sub=-1),
        _play(1, 600, 20, 20, type=584, team="h", athlete="h0", sub=1),
        # a0 does not start H2: his first H2 event is IN at 12:00 (elapsed 1680)
        _play(2, 720, 50, 50, type=584, team="a", athlete="a0", sub=1),
        _play(2, 0, 70, 70),
    ]
    share = baseline.starter_share_by_minute(_record(plays, starters, gid="s2"), baseline.plays_of(_record(plays, starters, gid="s2")))
    assert share[0] == 1.0  # minute 0: all ten
    assert share[6] == 0.9  # 6:30 elapsed: h0 on the bench
    assert share[12] == 1.0
    assert share[21] == 0.9  # early H2: a0 not on the floor
    assert share[29] == 1.0  # after 28:00 elapsed a0 is back
    assert share[39] == 1.0


def test_starter_share_refuses_undirected_subs():
    rec = _record([_play(1, 1200, 0, 0)], [], gid="s3")
    rec["check"]["n_subs_undirected"] = 2
    assert baseline.starter_share_by_minute(rec, baseline.plays_of(rec)) == {}
