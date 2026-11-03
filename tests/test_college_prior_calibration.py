"""College prior calibration (lane wncaab-module; user 2026-11-03 "College model fit").

`college_basketball/prior_calibration.py` fits the team prior's mean margin and total to the closing line (or the
finals) over a trailing window, and `live_team_model.prior_for_game` applies the newest fit dated strictly before
the game. These pin the fit's arithmetic, the no-leakage rule, the switch (off != on), and that the pregame and
live sims' provenance and inputs key carry it.
"""
from __future__ import annotations

import csv
import datetime as dt
import json
import random

import pytest

from syndicate.features.college_basketball import pregame_sim as ps
from syndicate.features.college_basketball import prior_calibration as pc
from syndicate.features.ncaab import live_team_model as tm
from syndicate.features.ncaab import slate

FIELDS = ("team", "espn_id", "adj_off", "adj_def", "adj_em", "tempo", "games", "prior_weight", "calibration_k", "season", "as_of")
TEAMS = [("1", 115.0, 95.0, 70.0, 10), ("2", 100.0, 110.0, 64.0, 10), ("3", 105.0, 105.0, 67.0, 10)]
GAME_DAY = dt.date(2026, 1, 20)


def _table(directory, season, as_of, rows=TEAMS):
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / f"team_ratings_{season}_asof_{as_of.replace('-', '')}.csv").open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS)
        writer.writeheader()
        for tid, off, deff, tempo, games in rows:
            writer.writerow({"team": f"T{tid}", "espn_id": tid, "adj_off": off, "adj_def": deff, "adj_em": off - deff, "tempo": tempo,
                             "games": games, "prior_weight": 0.2, "calibration_k": 0.78, "season": season, "as_of": as_of})


def _calibration(directory, as_of, *, season=2026, **fields):
    payload = {"league": "ncaab", "season": season, "as_of": as_of, "calibrated": True, "target": "close", "games": 120,
               "beta": 1.2, "gamma": 2.0, "total_slope": 0.7, "total_prior_mean": 140.0, "total_target_mean": 145.0, **fields}
    path = directory / f"prior_calibration_{season}_asof_{as_of.replace('-', '')}.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


@pytest.fixture(autouse=True)
def _switch_absent(monkeypatch):
    monkeypatch.delenv(pc.ENV, raising=False)


# ------------------------------------------------------------------------------------------------ the fit

def test_the_fit_recovers_known_coefficients():
    rng = random.Random(7)
    margins = [(x, h, 1.15 * x + (2.5 if h else 0.0) + rng.gauss(0, 0.2)) for x, h in ((rng.uniform(-20, 30), rng.random() < 0.8) for _ in range(400))]
    beta, gamma = pc.fit_margin(margins)
    assert beta == pytest.approx(1.15, abs=0.01) and gamma == pytest.approx(2.5, abs=0.1)
    totals = [(x, 150.0 + 0.7 * (x - 140.0) + rng.gauss(0, 0.2)) for x in (rng.uniform(120, 165) for _ in range(400))]
    slope, prior_mean, target_mean = pc.fit_total(totals)
    assert slope == pytest.approx(0.7, abs=0.01)
    assert target_mean + slope * (140.0 - prior_mean) == pytest.approx(150.0, abs=0.1)


def test_all_neutral_games_fit_no_home_term():
    beta, gamma = pc.fit_margin([(x, False, 1.1 * x) for x in range(-10, 20)])
    assert beta == pytest.approx(1.1) and gamma == 0.0


def _rows(n, *, closes=True, finals=True):
    return [pc.FitRow(date="2026-01-10", event_id=str(i), home_site=True, prior_margin=float(i % 30 - 5), prior_total=130.0 + i % 30,
                      close_margin=1.1 * (i % 30 - 5) + 2 if closes else None, close_total=135.0 + 0.8 * (i % 30) if closes else None,
                      final_margin=float(i % 30 - 5) if finals else None, final_total=130.0 + i % 30 if finals else None) for i in range(n)]


def test_the_target_is_the_close_then_the_final_then_nothing():
    on_close = pc.fit(_rows(pc.MIN_CLOSES), league="ncaab", season=2026, as_of=GAME_DAY)
    assert on_close.calibrated and on_close.target == "close" and on_close.beta == pytest.approx(1.1, abs=1e-3)
    on_final = pc.fit(_rows(pc.MIN_FINALS, closes=False), league="wncaab", season=2026, as_of=GAME_DAY)
    assert on_final.calibrated and on_final.target == "final" and on_final.beta == pytest.approx(1.0, abs=1e-3)
    thin = pc.fit(_rows(pc.MIN_FINALS - 1, closes=False), league="wncaab", season=2026, as_of=GAME_DAY)
    assert not thin.calibrated and "finals" in thin.reason
    assert thin.margin(10.0, home_site=True) == 10.0 and thin.total(140.0) == 140.0


def test_a_fit_outside_the_guard_range_is_clamped_and_says_so():
    rows = [pc.FitRow("2026-01-10", str(i), True, float(i - 30), 140.0 + i % 9, close_margin=3.0 * (i - 30), close_total=140.0 + i % 9)
            for i in range(pc.MIN_CLOSES)]
    cal = pc.fit(rows, league="ncaab", season=2026, as_of=GAME_DAY)
    assert cal.beta == pc.BETA_RANGE[1] and any(c.startswith("beta=") for c in cal.clamped)


# ------------------------------------------------------------------------------------------------ files

def test_only_a_fit_dated_strictly_before_the_game_applies(tmp_path):
    _calibration(tmp_path, "2026-01-19", beta=1.1)
    _calibration(tmp_path, "2026-01-20", beta=1.3)  # fitted on games of the 20th itself: not for them
    assert pc.calibration_for(GAME_DAY, dirs=[tmp_path]).beta == 1.1
    assert pc.calibration_for(GAME_DAY + dt.timedelta(days=1), dirs=[tmp_path]).beta == 1.3


def test_the_newest_fit_wins_even_when_it_is_uncalibrated(tmp_path):
    _calibration(tmp_path, "2026-01-15", beta=1.2)
    _calibration(tmp_path, "2026-01-18", calibrated=False, reason="30 closes < 60 and 40 finals < 80")
    cal = pc.calibration_for(GAME_DAY, dirs=[tmp_path])
    assert cal is not None and not cal.calibrated and "closes" in cal.reason


def test_last_seasons_fit_never_prices_this_season(tmp_path):
    _calibration(tmp_path, "2026-04-06", season=2026)
    assert pc.calibration_for(dt.date(2026, 11, 3), dirs=[tmp_path]) is None


def test_an_unreadable_newest_file_serves_the_raw_prior_by_name(tmp_path):
    _calibration(tmp_path, "2026-01-15")
    (tmp_path / "prior_calibration_2026_asof_20260118.json").write_text("{not json", encoding="utf-8")
    cal = pc.calibration_for(GAME_DAY, dirs=[tmp_path])
    assert not cal.calibrated and cal.reason.startswith("unreadable")


# ------------------------------------------------------------------------------------------------ the prior

def test_the_prior_carries_the_fit_and_its_raw_values(tmp_path):
    _table(tmp_path, 2026, "2026-01-10")
    _calibration(tmp_path, "2026-01-19")
    raw = tm.prior_for_game(GAME_DAY, "1", "2", neutral=False, dirs=[tmp_path], calibrate=False)
    cal = tm.prior_for_game(GAME_DAY, "1", "2", neutral=False, dirs=[tmp_path])
    assert raw.calibration == {"calibrated": False, "reason": "raw prior requested"} and raw.raw_total == raw.total
    assert cal.home_margin == pytest.approx(1.2 * raw.home_margin + 2.0)
    assert cal.total == pytest.approx(145.0 + 0.7 * (raw.total - 140.0))
    assert cal.home_points - cal.away_points == pytest.approx(cal.home_margin)
    assert cal.home_points + cal.away_points == pytest.approx(cal.total)
    assert cal.possessions == raw.possessions, "an estimator fit: pace is not moved"
    assert (cal.raw_home_margin, cal.raw_total) == (raw.home_margin, raw.total)
    assert cal.calibration["calibrated"] is True and cal.calibration["asOf"] == "2026-01-19"


def test_a_neutral_site_game_gets_no_home_term(tmp_path):
    _table(tmp_path, 2026, "2026-01-10")
    _calibration(tmp_path, "2026-01-19")
    raw = tm.prior_for_game(GAME_DAY, "1", "2", neutral=True, dirs=[tmp_path], calibrate=False)
    cal = tm.prior_for_game(GAME_DAY, "1", "2", neutral=True, dirs=[tmp_path])
    assert cal.home_margin == pytest.approx(1.2 * raw.home_margin)


def test_the_switch_is_reachable_off_differs_from_on(tmp_path, monkeypatch):
    _table(tmp_path, 2026, "2026-01-10")
    _calibration(tmp_path, "2026-01-19")
    on = tm.prior_for_game(GAME_DAY, "1", "2", neutral=False, dirs=[tmp_path])
    monkeypatch.setenv(pc.ENV, "0")
    off = tm.prior_for_game(GAME_DAY, "1", "2", neutral=False, dirs=[tmp_path])
    assert on.home_margin != off.home_margin and on.total != off.total
    assert off.calibration == {"calibrated": False, "reason": f"switched off ({pc.ENV})"}


def test_no_file_serves_the_raw_prior_and_says_why(tmp_path):
    _table(tmp_path, 2026, "2026-01-10")
    got = tm.prior_for_game(GAME_DAY, "1", "2", neutral=False, dirs=[tmp_path])
    raw = tm.prior_for_game(GAME_DAY, "1", "2", neutral=False, dirs=[tmp_path], calibrate=False)
    assert got.home_margin == raw.home_margin and got.calibration["calibrated"] is False
    assert got.calibration["reason"].startswith("no calibration file") and got.raw_home_margin == raw.home_margin


def test_the_sims_provenance_and_inputs_key_carry_the_fit(tmp_path, monkeypatch):
    from syndicate.features.ncaab import live_resim as lr

    _table(tmp_path, 2026, "2026-01-10")
    _calibration(tmp_path, "2026-01-19")
    monkeypatch.setattr(lr, "team_frame", lambda rows, team_code, date: object())
    priors = lr.PlayerPriors(season=2026, as_of=dt.date(2026, 1, 19), source="t", by_team={"1": [{}], "2": [{}]})
    built = lr.build_engine_inputs(GAME_DAY.isoformat(), "1", "2", neutral=False, priors=priors, dirs=[tmp_path])
    prov = built["_provenance"]
    assert prov["priorCalibration"]["calibrated"] is True and prov["rawPregameHomeMargin"] is not None
    assert built["target_home_points"] - built["target_away_points"] == pytest.approx(prov["pregameHomeMargin"], abs=0.01)
    other = dict(prov, priorCalibration={**prov["priorCalibration"], "asOf": "2026-01-18"})
    assert ps.inputs_key(prov, 200) != ps.inputs_key(other, 200), "a new fit must re-sim the game"


# ------------------------------------------------------------------------------------------------ fit rows

def _quote(market, selection, line, *, home, away, book, seen, commence="2026-01-20T01:00:00+00:00"):
    return {"market": market, "selection": selection, "line": line, "segment": "full", "home_team": home, "away_team": away,
            "bookmaker": book, "snapshot_ts": seen, "commence_time": commence}


def test_fit_rows_read_the_close_the_final_and_skip_unplayed_games(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNDICATE_DATA_ROOT", str(tmp_path))
    _table(tmp_path / "tables", 2026, "2026-01-10")
    day = "2026-01-19"

    def game(eid, home, away, *, final=True, neutral=False, status=""):
        return {"event_id": eid, "start_time_utc": "2026-01-20T01:00:00Z", "neutral_site": neutral,
                "home": {"espn_id": home, "name": f"Team {home}", "score": 80 if final else None},
                "away": {"espn_id": away, "name": f"Team {away}", "score": 70 if final else None},
                "live_state": {"final": final, "status": status}}

    path = slate.slate_artifact_path(day, "ncaab")
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"games": [game("10", "1", "2"), game("11", "3", "2", neutral=True), game("12", "1", "3", final=False, status="Postponed")]}),
                    encoding="utf-8")
    quotes = [
        _quote("spreads", "home", -6.5, home="Team 1", away="Team 2", book="a", seen="2026-01-19T20:00:00+00:00"),
        _quote("spreads", "home", -7.5, home="Team 1", away="Team 2", book="a", seen="2026-01-20T00:30:00+00:00"),
        _quote("spreads", "home", -9.0, home="Team 1", away="Team 2", book="a", seen="2026-01-20T01:05:00+00:00"),  # after the tip
        _quote("spreads", "home", -8.5, home="Team 1", away="Team 2", book="b", seen="2026-01-20T00:40:00+00:00"),
        _quote("totals", "over", 141.5, home="Team 1", away="Team 2", book="a", seen="2026-01-20T00:30:00+00:00"),
        _quote("totals", "over", 142.5, home="Team 1", away="Team 2", book="b", seen="2026-01-20T00:40:00+00:00"),
        # the feed oriented the neutral-site game the other way: the close margin flips onto the slate's home
        _quote("spreads", "home", -3.0, home="Team 2", away="Team 3", book="a", seen="2026-01-20T00:30:00+00:00"),
    ]
    rows = pc.build_fit_rows("ncaab", [day], now=dt.datetime(2026, 1, 20, 12, tzinfo=dt.timezone.utc),
                             dirs=[tmp_path / "tables"], quote_rows={day: quotes})
    by_event = {r.event_id: r for r in rows}
    assert set(by_event) == {"10", "11"}, "a postponed game is not a fit row"
    assert by_event["10"].close_margin == pytest.approx(8.0)  # median of each book's last pre-tip line: 7.5, 8.5
    assert by_event["10"].close_total == pytest.approx(142.0)
    assert (by_event["10"].final_margin, by_event["10"].final_total) == (10.0, 150.0)
    assert by_event["10"].home_site is True and by_event["11"].home_site is False
    assert by_event["11"].close_margin == pytest.approx(-3.0)
    raw = tm.prior_for_game(dt.date.fromisoformat(day), "1", "2", neutral=False, dirs=[tmp_path / "tables"], calibrate=False)
    assert by_event["10"].prior_margin == pytest.approx(raw.home_margin), "the fit reads the RAW prior"


def test_refresh_writes_the_file_for_the_next_days_games(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNDICATE_DATA_ROOT", str(tmp_path))
    monkeypatch.setattr(pc, "build_fit_rows", lambda league, dates, **_: _rows(pc.MIN_CLOSES))
    cal, report = pc.refresh_calibration("ncaab", today=dt.date(2026, 11, 4))
    assert cal.as_of == dt.date(2026, 11, 3) and cal.season == 2027
    assert report["written"].endswith("prior_calibration_2027_asof_20261103.json")
    assert report["window"][0] >= "2026-11-01", "the window never reaches into last season"
    assert pc.calibration_for(dt.date(2026, 11, 4), dirs=[pc.processed_dir("ncaab")]).beta == cal.beta


def test_the_pregame_child_refits_once_a_day_after_11z(tmp_path, monkeypatch):
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location("bcps", Path(__file__).resolve().parents[1] / "scripts" / "build_college_pregame_sims.py")
    bcps = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bcps)
    monkeypatch.setenv("SYNDICATE_DATA_ROOT", str(tmp_path))
    calls = []

    def refit(league, *, today, now):
        calls.append(league)
        path = pc.calibration_path(league, 2027, today - dt.timedelta(days=1))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}", encoding="utf-8")

    early = dt.datetime(2026, 11, 4, 10, 59, tzinfo=dt.timezone.utc)
    assert bcps.refresh_prior_calibrations(["ncaab"], early, refit=refit) == {"ncaab": "before_11z"}
    later = dt.datetime(2026, 11, 4, 11, 30, tzinfo=dt.timezone.utc)
    assert bcps.refresh_prior_calibrations(["ncaab", "wncaab"], later, refit=refit) == {"ncaab": "refitted", "wncaab": "refitted"}
    assert bcps.refresh_prior_calibrations(["ncaab", "wncaab"], later, refit=refit) == {"ncaab": "already_today", "wncaab": "already_today"}
    assert calls == ["ncaab", "wncaab"]

    def broken(league, *, today, now):
        raise RuntimeError("quote log unreadable")

    assert bcps.refresh_prior_calibrations(["ncaab"], dt.datetime(2026, 11, 5, 12, tzinfo=dt.timezone.utc), refit=broken) == {"ncaab": "failed"}
