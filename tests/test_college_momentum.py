"""College basketball's live game shape on the rail (lane wncaab-module, Phase 2).

The run line and bonus come from `college_basketball/momentum_capture.py` on the live-odds-worker; the
chip build (`live_detail`) and the serve-time re-read (`attach_served_linescores`) both read its file.
"""
from __future__ import annotations

import json

import pytest

from syndicate.features.college_basketball import momentum_capture as mc
from syndicate.features.shared import game_chip_linescore as gcl
from syndicate.features.shared.game_chip_detail import college_live_line, live_detail

AWAY, HOME = ("10", "UCSD"), ("20", "WASH")


def _play(team_id, period, clock, *, kind="JumpShot", points=0, attempted=2):
    shooting = kind in ("JumpShot", "LayUpShot", "MadeFreeThrow")
    return {"type": {"text": kind}, "team": {"id": team_id}, "period": {"number": period}, "clock": {"displayValue": clock},
            "shootingPlay": shooting, "pointsAttempted": attempted if shooting else None, "scoreValue": points, "scoringPlay": points > 0}


def _summary(plays, period):
    competitors = [{"homeAway": "away", "team": {"id": AWAY[0], "abbreviation": AWAY[1]},
                    "fouls": {"teamFouls": 0, "foulsToGive": 0, "bonusState": "DOUBLE"}},  # ESPN's college placeholder
                   {"homeAway": "home", "team": {"id": HOME[0], "abbreviation": HOME[1]},
                    "fouls": {"teamFouls": 0, "foulsToGive": 0, "bonusState": "DOUBLE"}}]
    return {"header": {"competitions": [{"competitors": competitors, "status": {"period": period}}]}, "plays": plays}


def _fouls(team_id, period, n):
    return [_play(team_id, period, f"{9 - i}:00", kind="PersonalFoul") for i in range(n)]


def test_womens_bonus_counts_the_current_quarter_and_carries_into_overtime():
    plays = _fouls(AWAY[0], 2, 6) + _fouls(AWAY[0], 3, 4) + _fouls(HOME[0], 3, 5)
    fouls = mc.team_fouls(_summary(plays, 3), "wncaab")
    assert fouls["away"]["fouls"] == 4 and fouls["home"]["fouls"] == 5  # Q2's six are gone
    assert mc.bonus_text(fouls, "wncaab") == "UCSD in bonus"  # WASH's 5th foul puts UCSD on the line
    ot = mc.team_fouls(_summary(_fouls(AWAY[0], 4, 3) + _fouls(AWAY[0], 5, 2) + _fouls(HOME[0], 4, 5), 5), "wncaab")
    assert ot["away"]["fouls"] == 5  # overtime extends the fourth quarter
    assert mc.bonus_text(ot, "wncaab") == "both in bonus"
    # ESPN's placeholder `bonusState` is never read: no fouls, no bonus.
    assert mc.bonus_text(mc.team_fouls(_summary([], 1), "wncaab"), "wncaab") is None


def test_mens_bonus_is_per_half_with_one_and_one_then_double():
    fouls = mc.team_fouls(_summary(_fouls(AWAY[0], 1, 7) + _fouls(HOME[0], 1, 10), 1), "ncaab")
    assert mc.bonus_text(fouls, "ncaab") == "UCSD in double bonus · WASH in bonus"
    second = mc.team_fouls(_summary(_fouls(AWAY[0], 1, 9) + _fouls(AWAY[0], 2, 2), 2), "ncaab")
    assert second["away"]["fouls"] == 2 and mc.bonus_text(second, "ncaab") is None  # reset at the half
    ot = mc.team_fouls(_summary(_fouls(HOME[0], 2, 6) + _fouls(HOME[0], 3, 1), 3), "ncaab")
    assert mc.bonus_text(ot, "ncaab") == "UCSD in bonus"  # overtime extends the second half
    # At halftime the first-half count is about to reset: no bonus is stated (measured UTEP @ NKU 9-9 at HALF).
    half = _summary(_fouls(AWAY[0], 1, 9) + _fouls(HOME[0], 1, 9), 1)
    half["header"]["competitions"][0]["status"]["type"] = {"name": "STATUS_HALFTIME"}
    assert mc.team_fouls(half, "ncaab")["on_break"] and mc.bonus_text(mc.team_fouls(half, "ncaab"), "ncaab") is None


def _run_summary(period=3):
    # WASH 2, then UCSD 9: "UCSD on a 9–2 run" (a run allows the other side up to 4, as NBA chips read it).
    plays = [_play(HOME[0], period, "8:00", points=2)]
    plays += [_play(AWAY[0], period, f"{7 - i}:00", points=3, attempted=3) for i in range(3)]
    return _summary(plays + _fouls(HOME[0], period, 5), period)


def test_capture_writes_the_file_the_chip_reads(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNDICATE_DATA_ROOT", str(tmp_path))
    result = mc.capture_once("wncaab", "2026-11-02", event_ids=["401"], fetch_summary=lambda eid: _run_summary(), out_root=tmp_path)
    assert result["written"] and result["live"] == 1
    path = tmp_path / "wncaab_source" / "source_artifacts" / "data" / "live_lens" / "momentum_events_2026-11-02.json"
    entry = json.loads(path.read_text(encoding="utf-8"))["games"]["401"]
    assert entry["bonus"] == "UCSD in bonus" and entry["fouls"]["home"]["fouls"] == 5 and entry["narrator"]
    assert college_live_line("wncaab", {"event_id": "401"}, "2026-11-02") == "UCSD on a 9–2 run · UCSD in bonus"
    from datetime import datetime, timezone

    start = datetime(2026, 11, 2, 19, 0, tzinfo=timezone.utc)
    assert live_detail("wncaab", {"event_id": "401"}, start) == "UCSD on a 9–2 run · UCSD in bonus"
    assert live_detail("ncaab", {"event_id": "401"}, start) is None  # each league reads its own file


def test_a_missed_shot_is_not_points_and_a_run_never_outruns_the_score(tmp_path, monkeypatch):
    # Measured 2026-11-02 USC @ UNLV, Q1 3-5: college feeds carry `scoreValue` on misses (`scoringPlay: false`),
    # the narrator summed USC 13 / UNLV 8, and the chip read "USC on a 9–2 run".
    from syndicate.features.shared.basketball_momentum import basketball_scoring_events

    miss = {**_play(AWAY[0], 1, "7:30", points=0), "scoreValue": 3, "scoringPlay": False}
    rows = basketball_scoring_events(_summary([_play(HOME[0], 1, "8:00", points=2), miss], 1), league_code="wncaab")
    assert [(r["team"], r["weight"]) for r in rows] == [("WASH", 2.0)]
    # A feed without the flag still counts its points.
    unflagged = {k: v for k, v in _play(AWAY[0], 1, "7:00", points=3, attempted=3).items() if k != "scoringPlay"}
    assert len(basketball_scoring_events(_summary([unflagged], 1), league_code="wncaab")) == 1

    # Read-time guard: rows that add up to more than the card's score never become a run.
    monkeypatch.setenv("SYNDICATE_DATA_ROOT", str(tmp_path))
    mc.capture_once("wncaab", "2026-11-02", event_ids=["401"], fetch_summary=lambda eid: _run_summary(), out_root=tmp_path)
    assert college_live_line("wncaab", {"event_id": "401"}, "2026-11-02", {"UCSD": 3, "WASH": 2}) == "UCSD in bonus"
    assert college_live_line("wncaab", {"event_id": "401"}, "2026-11-02", {"UCSD": 9, "WASH": 2}) == "UCSD on a 9–2 run · UCSD in bonus"


def test_capture_with_no_live_game_writes_nothing(tmp_path):
    assert mc.capture_once("ncaab", "2026-11-02", event_ids=[], out_root=tmp_path) == {"league": "ncaab", "live": 0, "written": False}
    assert not any(tmp_path.rglob("*.json"))


def test_capture_switch_is_reachable(monkeypatch):
    started = []
    monkeypatch.setattr(mc.threading, "Thread", lambda **kw: started.append(kw) or type("T", (), {"start": lambda self: None, "is_alive": lambda self: True})())
    monkeypatch.setattr(mc, "_thread", None)
    monkeypatch.setenv("SYNDICATE_COLLEGE_MOMENTUM_CAPTURE", "0")
    assert mc.ensure_capture_thread() is False and not started
    monkeypatch.setenv("SYNDICATE_COLLEGE_MOMENTUM_CAPTURE", "1")
    assert mc.ensure_capture_thread() is True and started[0]["name"] == "college-momentum-capture"
    assert mc.ensure_capture_thread() is False  # once per process
    monkeypatch.setenv("SYNDICATE_COLLEGE_MOMENTUM_INTERVAL_SECONDS", "5")
    assert mc.capture_interval_seconds() == 60


@pytest.mark.parametrize("sport,period,status,want", [
    ("ncaab", 2, "STATUS_IN_PROGRESS", "H2 4:12"),
    ("ncaab", 3, "STATUS_IN_PROGRESS", "OT 4:12"),
    ("wncaab", 3, "STATUS_IN_PROGRESS", "Q3 4:12"),
    ("wncaab", 2, "STATUS_END_PERIOD", "END Q2"),
    ("wncaab", 2, "STATUS_HALFTIME", "HALF"),
])
def test_serve_time_clock_uses_college_periods(monkeypatch, sport, period, status, want):
    hit = {"id": "401", "period": period, "clock": "4:12", "status_name": status, "away_periods": [15, 14, 12], "home_periods": [17, 10, 13]}
    monkeypatch.setattr(gcl, "_espn_game", lambda *a, **k: hit)
    assert gcl.live_clock_token(sport, {"event_id": "401"}, "2026-11-02") == want


def test_serve_time_linescore_prefers_espn_and_keeps_the_slate_when_espn_fails(monkeypatch):
    hit = {"id": "401", "away_periods": [15, 14, 12], "home_periods": [17, 10, 13]}
    monkeypatch.setattr(gcl, "_espn_game", lambda *a, **k: hit)
    box = gcl.linescore("wncaab", {"event_id": "401"}, "2026-11-02", live=True)
    assert box["labels"] == ["1", "2", "3"] and box["away"] == [15, 14, 12]
    monkeypatch.setattr(gcl, "_espn_game", lambda *a, **k: None)
    slate_game = {"event_id": "401", "live_state": {"away_linescores": [30, 20], "home_linescores": [25, 22]}}
    assert gcl.linescore("ncaab", slate_game, "2026-11-02", live=True)["away"] == [30, 20]
    assert "groups=50" in gcl._ESPN_QUERY["wncaab"] and "womens-college-basketball" in gcl._ESPN_PATHS["wncaab"]


def test_serve_time_periods_follow_the_chips_sides_on_a_neutral_site_game(monkeypatch):
    # Measured 2026-11-02 20:34Z: 401911532 carded NKU @ UTEP (oriented to the odds feed), ESPN UTEP @ NKU 38-42.
    from syndicate.features.shared import game_chip_scoreboard as gcs

    hit = {"id": "401911532", "away": "UTEP", "home": "NKU", "away_periods": [38], "home_periods": [42],
           "period": 2, "clock": "19:40", "status_name": "STATUS_IN_PROGRESS"}
    monkeypatch.setattr(gcl, "_espn_game", lambda *a, **k: hit)
    box = gcl.linescore("ncaab", {"event_id": "401911532"}, "2026-11-02", away_abbr="NKU", home_abbr="UTEP", live=True)
    assert box["away"] == [42] and box["home"] == [38]
    chip = {"sport": "ncaab", "state": "live", "game_key": "401911532", "status_token": "H2 19:40", "start_time_utc": "2026-11-02T19:00:00Z",
            "away": {"abbr": "NKU", "score": "40"}, "home": {"abbr": "UTEP", "score": "38"}}
    gcs.attach_served_linescores([chip], "2026-11-02")
    assert chip["away"]["score"] == "42" and chip["home"]["score"] == "38" and chip["leader"] == "away"
    # Same orientation as ESPN: untouched.
    same = gcl.linescore("ncaab", {"event_id": "401911532"}, "2026-11-02", away_abbr="UTEP", home_abbr="NKU", live=True)
    assert same["away"] == [38] and same["home"] == [42]


def test_served_chip_keeps_worker_periods_and_reads_the_live_line(tmp_path, monkeypatch):
    from syndicate.features.shared import game_chip_scoreboard as gcs

    monkeypatch.setenv("SYNDICATE_DATA_ROOT", str(tmp_path))
    mc.capture_once("wncaab", "2026-11-02", event_ids=["401"], fetch_summary=lambda eid: _run_summary(), out_root=tmp_path)
    monkeypatch.setattr(gcl, "_espn_game", lambda *a, **k: None)  # ESPN unreachable at serve time
    worker_box = {"kind": "periods", "labels": ["1", "2", "3"], "away": [15, 14, 12], "home": [17, 10, 13]}
    chip = {"sport": "wncaab", "state": "live", "game_key": "401", "status_token": "Q3 4:12", "start_time_utc": "2026-11-02T19:00:00Z",
            "linescore": dict(worker_box), "away": {"abbr": "UCSD", "score": "41"}, "home": {"abbr": "WASH", "score": "40"}}
    gcs.attach_served_linescores([chip], "2026-11-02")
    assert chip["linescore"] == worker_box  # not erased
    assert chip["situation"] == "UCSD on a 9–2 run · UCSD in bonus"
    # The run ended and the file says nothing now: the stale line goes, ESPN's own text stays.
    stale = {**chip, "game_key": "999", "situation": "Media timeout · WASH on a 8–0 run · UCSD in bonus", "linescore": dict(worker_box)}
    gcs.attach_served_linescores([stale], "2026-11-02")
    assert stale["situation"] == "Media timeout"
