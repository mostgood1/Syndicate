# -*- coding: utf-8 -*-
"""scripts/soccer_season_audit/forward_grade.py: the H27 and W1r/W2/W3 forward grades over the pre-kickoff freeze.

The first test runs `grade()` end to end over a one-match cache and asserts every cell's funnel reaches a
price and a graded line -- a join that silently produces zero is the failure this file exists to catch.
"""
import datetime as dt
import json
import random
import sys
from pathlib import Path

import pytest

AUDIT = Path(__file__).resolve().parents[1] / "scripts" / "soccer_season_audit"
sys.path.insert(0, str(AUDIT))

import common  # noqa: E402
import forward_grade as fg  # noqa: E402

KICKOFF = "2026-09-17T19:30:00+00:00"
MID = "740001"


def _match(frozen_home_corners=6.5, frozen_away_corners=5.0, basis=fg.CORNERS_BASIS):
    return {
        "match_id": MID, "kickoff": KICKOFF, "status_state": "pre",
        "matchup": {"home_team": "Real Madrid", "away_team": "Sevilla"},
        "win_probability": {"home": 0.6, "draw": 0.22, "away": 0.18},
        "volume_projection": {"home_corners": frozen_home_corners, "away_corners": frozen_away_corners, "corners_basis": basis},
    }


def _props():
    return [{"match_id": MID, "player_name": "Kylian Mbappe", "side": "home",
             "expected_shots_on_target_if_playing": 2.4, "anytime_scorer_probability_if_playing": 0.62}]


def _freeze(path: Path, service: str, frozen_at: str, match=None):
    path.write_text(json.dumps({
        "schema": "soccer_prekickoff_freeze_v1", "league": "la_liga", "date": "2026-09-17", "service": service,
        "matches": {MID: {"frozen_at": frozen_at, "kickoff": KICKOFF, "match": match or _match(), "player_props": _props()}},
    }), encoding="utf-8")


def _espn(corners_home=8, corners_away=6, mbappe_sot=3, mbappe_goals=1, completed=True):
    return {
        "header": {"competitions": [{
            "date": "2026-09-17T19:30Z",
            "status": {"type": {"name": "STATUS_FULL_TIME" if completed else "STATUS_POSTPONED", "completed": completed}},
            "competitors": [
                {"homeAway": "home", "score": "2", "team": {"id": "86", "displayName": "Real Madrid"}},
                {"homeAway": "away", "score": "1", "team": {"id": "243", "displayName": "Sevilla"}},
            ]}]},
        "boxscore": {"teams": [
            {"team": {"id": "86"}, "statistics": [{"name": "wonCorners", "displayValue": str(corners_home)}]},
            {"team": {"id": "243"}, "statistics": [{"name": "wonCorners", "displayValue": str(corners_away)}]},
        ]},
        "rosters": [
            {"homeAway": "home", "roster": [{"athlete": {"displayName": "Kylian Mbappe"}, "starter": True, "subbedIn": False,
                                             "stats": [{"name": "shotsOnTarget", "value": mbappe_sot}, {"name": "totalGoals", "value": mbappe_goals},
                                                       {"name": "totalShots", "value": 5}, {"name": "appearances", "value": 1}]}]},
            {"homeAway": "away", "roster": []},
        ],
    }


def _game_markets(generated_at="2026-09-17T04:10:00+00:00"):
    rows = []
    for book, over, under in (("draftkings", 105, -135), ("fanduel", 100, -130), ("betmgm", 110, -140)):
        for side, price in (("over", over), ("under", under)):
            rows.append({"league": "la_liga", "event_id": "odds-ev-1", "home_team": "Real Madrid", "away_team": "Sevilla",
                         "game_time": "2026-09-17T19:30:00Z", "book": book, "market_key": "alternate_totals_corners",
                         "line": 10.5, "side": side, "price": price})
    return {"league": "la_liga", "generated_at": generated_at, "rows": rows}


PROPS_HEADER = "league,player,market,market_key,line,over_price,under_price,book,event,event_id,game_time,home_team,away_team\n"


def _props_csv(sot_price=300, anytime_price=120):
    common_cols = "la_liga,Kylian Mbappe,{m},{mk},{line},{price},,{book},ev,odds-ev-1,2026-09-17T19:30:00Z,Real Madrid,Sevilla\n"
    text = PROPS_HEADER
    for book in ("draftkings", "fanduel"):
        text += common_cols.format(m="SOT", mk="player_shots_on_target", line="1.5", price=sot_price, book=book)
        text += common_cols.format(m="Anytime", mk="player_goal_scorer_anytime", line="", price=anytime_price, book=book)
    return text


def _history(root: Path):
    h = root / "data" / "soccer_source" / "la_liga" / "history"
    h.mkdir(parents=True)
    rows = ["date,home_team,away_team,home_corners,away_corners"]
    for i, (hc, ac) in enumerate(((6, 4), (3, 2), (9, 7), (5, 5), (8, 1), (2, 6))):
        rows.append(f"{10 + i}/08/2025,Team{i},Other{i},{hc},{ac}")
    (h / "matches_2025.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")


def _cache(tmp_path: Path) -> Path:
    cache = tmp_path / "cache"
    for sub in ("freeze", "espn", "prod/game_markets", "prod/props", "book_quotes"):
        (cache / sub).mkdir(parents=True)
    _freeze(cache / "freeze" / "la_liga__recommendations_prekickoff_2026-09-17.live-odds-worker.json", "live-odds-worker", "2026-09-17T19:20:00+00:00")
    (cache / "espn" / f"la_liga__{MID}.json").write_text(json.dumps(_espn()), encoding="utf-8")
    (cache / "prod" / "game_markets" / "la_liga_2026-09-16.json").write_text(json.dumps(_game_markets()), encoding="utf-8")
    (cache / "prod" / "props" / "la_liga_2026-09-16.csv").write_text(_props_csv(), encoding="utf-8")
    _history(tmp_path / "hist")
    return cache


# ---------------------------------------------------------------------------- reachability first

def test_every_cell_reaches_a_price_and_a_graded_line_end_to_end(tmp_path):
    cache = _cache(tmp_path)
    report = fg.grade(cache, tmp_path / "hist", today=dt.date(2026, 9, 18))
    reg = report["registered"]
    assert report["merged_prekickoff"] == 1
    assert reg["W1r"]["funnel"]["priced"] == 1
    assert reg["H27"]["n_with_k"] == 1 and reg["H27"]["funnel"]["priced"] == 1
    assert reg["W2"]["funnel"]["graded_lines"] == 1
    assert reg["W3"]["funnel"]["graded_lines"] == 1
    # frozen total 11.5 against a 10.5 line priced near even: the over leg clears 8 pp, and 14 corners won it
    assert reg["W1r"]["bets"] == 1 and reg["W1r"]["hit"] == 1.0
    assert reg["W1r"]["verdict"] == "WATCHING"
    assert report["sensitivity_book_quotes"] == {}


def test_book_quotes_sensitivity_is_reported_beside_the_registered_prices(tmp_path):
    cache = _cache(tmp_path)
    lines = []
    for book, over, under in (("draftkings", 105, -135), ("fanduel", 100, -130)):
        for sel, price in (("over", over), ("under", under)):
            lines.append({"captured_at": "2026-09-17T18:40:00+00:00", "commence_time": "2026-09-17T19:30:00Z", "league": "la_liga",
                          "event_id": "odds-ev-1", "home_team": "Real Madrid", "away_team": "Sevilla", "bookmaker": book,
                          "market": "alternate_totals_corners", "selection": sel, "player_name": None, "line": 10.5, "price": price})
    # an in-play row must never be the price
    lines.append({**lines[0], "captured_at": "2026-09-17T19:45:00+00:00", "price": 900})
    (cache / "book_quotes" / "2026-09-17.jsonl").write_text("\n".join(json.dumps(x) for x in lines) + "\n", encoding="utf-8")
    report = fg.grade(cache, tmp_path / "hist", today=dt.date(2026, 9, 18))
    sens = report["sensitivity_book_quotes"]
    assert sens["W1r"]["funnel"]["priced"] == 1
    assert sens["W1r"]["bets"] == 1
    assert max(b for b in (sens["W1r"]["mean_odds"],)) < 3.0


def test_a_postponed_match_and_a_wrong_basis_are_outside_the_population(tmp_path):
    cache = _cache(tmp_path)
    (cache / "espn" / f"la_liga__{MID}.json").write_text(json.dumps(_espn(completed=False)), encoding="utf-8")
    report = fg.grade(cache, tmp_path / "hist", today=dt.date(2026, 9, 18))
    assert report["registered"]["W1r"]["funnel"].get("finished", 0) == 0

    cache2 = _cache(tmp_path / "b")
    _freeze(cache2 / "freeze" / "la_liga__recommendations_prekickoff_2026-09-17.live-odds-worker.json", "live-odds-worker",
            "2026-09-17T19:20:00+00:00", match=_match(basis="sim"))
    report2 = fg.grade(cache2, tmp_path / "b" / "hist", today=dt.date(2026, 9, 18))
    assert report2["registered"]["W1r"]["funnel"]["finished"] == 1
    assert report2["registered"]["W1r"]["funnel"].get("in_window", 0) == 0
    assert report2["registered"]["H27"]["n_population"] == 0
    # the prop cells do not depend on the corners basis
    assert report2["registered"]["W2"]["funnel"]["graded_lines"] == 1


def test_a_prop_file_dated_after_the_game_is_not_a_price(tmp_path):
    cache = _cache(tmp_path)
    (cache / "prod" / "props" / "la_liga_2026-09-16.csv").unlink()
    (cache / "prod" / "props" / "la_liga_2026-09-18.csv").write_text(_props_csv(), encoding="utf-8")
    report = fg.grade(cache, tmp_path / "hist", today=dt.date(2026, 9, 18))
    assert report["registered"]["W2"]["funnel"].get("priced_lines", 0) == 0


def test_a_player_who_did_not_appear_is_void(tmp_path):
    cache = _cache(tmp_path)
    summary = _espn()
    summary["rosters"][0]["roster"][0].update({"starter": False, "subbedIn": False,
                                              "stats": [{"name": "appearances", "value": 0}]})
    (cache / "espn" / f"la_liga__{MID}.json").write_text(json.dumps(summary), encoding="utf-8")
    report = fg.grade(cache, tmp_path / "hist", today=dt.date(2026, 9, 18))
    assert report["registered"]["W3"]["funnel"]["void_or_unmatched"] == 1
    assert report["registered"]["W3"]["bets"] == 0


# ---------------------------------------------------------------------------- merge

def test_merge_takes_the_latest_freeze_before_the_espn_kickoff_across_services():
    ko = dt.datetime(2026, 9, 17, 17, 0, tzinfo=dt.timezone.utc)
    files = [
        {"league": "la_liga", "date": "2026-09-17", "service": "live-odds-worker", "matches": {MID: {"frozen_at": "2026-09-17T15:00:00+00:00"}}},
        {"league": "la_liga", "date": "2026-09-17", "service": "refresh-worker", "matches": {MID: {"frozen_at": "2026-09-17T16:30:00+00:00"}}},
    ]
    assert fg.merge_frozen(files, {("la_liga", MID): ko})[("la_liga", MID)]["service"] == "refresh-worker"
    # ESPN moved kickoff earlier than one service's freeze: that entry is post-kickoff and must not win
    early = dt.datetime(2026, 9, 17, 16, 0, tzinfo=dt.timezone.utc)
    assert fg.merge_frozen(files, {("la_liga", MID): early})[("la_liga", MID)]["service"] == "live-odds-worker"
    assert fg.merge_frozen(files, {}) == {}


# ---------------------------------------------------------------------------- statistics + verdicts

def test_boot_ci_level_resamples_exactly_as_common_boot_ci():
    rng = random.Random(3)
    units = [[rng.choice((-1.0, 0.9, 1.1))] for _ in range(40)]
    stat = lambda s: sum(sum(u) for u in s) / sum(len(u) for u in s)  # noqa: E731
    assert fg.boot_ci_level(units, stat, level=0.95) == common.boot_ci(units, stat)
    lo, hi = fg.boot_ci_level(units, stat)
    lo95, hi95 = common.boot_ci(units, stat)
    assert lo <= lo95 and hi >= hi95


@pytest.mark.parametrize("n,roi,low,today,expected", [
    (99, 0.3, 0.1, dt.date(2026, 11, 14), "WATCHING"),
    (99, 0.3, 0.1, dt.date(2026, 11, 15), "INSUFFICIENT"),
    (99, 0.3, 0.1, dt.date(2026, 12, 15), "NOT SHOWN"),
    (100, 0.2, 0.01, dt.date(2026, 10, 1), "SUPPORTED"),
    (100, 0.0, -0.3, dt.date(2026, 10, 1), "FALSIFIED"),
    (100, 0.05, -0.1, dt.date(2026, 12, 14), "INCONCLUSIVE"),
    (100, 0.05, -0.1, dt.date(2026, 12, 15), "NOT SHOWN"),
    (100, 0.05, float("nan"), dt.date(2026, 10, 1), "INCONCLUSIVE"),
])
def test_watch_verdict(n, roi, low, today, expected):
    assert fg.watch_verdict(n, roi, low, today) == expected


@pytest.mark.parametrize("n,mae_m,mae_k,bias,today,expected", [
    (149, 2.7, 2.8, {}, dt.date(2026, 11, 14), "WATCHING"),
    (149, 2.7, 2.8, {}, dt.date(2026, 11, 15), "INSUFFICIENT"),
    (150, 2.8, 2.8, {"epl": {"n": 20, "bias": 0.5}}, dt.date(2026, 10, 1), "MET"),
    (150, 2.7, 2.8, {"epl": {"n": 20, "bias": -0.51}}, dt.date(2026, 10, 1), "FALSIFIED"),
    (150, 2.7, 2.8, {"epl": {"n": 19, "bias": 2.0}}, dt.date(2026, 10, 1), "MET"),
    (150, 2.81, 2.8, {}, dt.date(2026, 10, 1), "FALSIFIED"),
])
def test_h27_verdict(n, mae_m, mae_k, bias, today, expected):
    assert fg.h27_verdict(n, mae_m, mae_k, bias, today) == expected


def test_implied_mean_inverts_nb_sf():
    mean = fg.implied_mean(9.5, 0.5, 1.3)
    assert abs(common.nb_sf(10, mean, 1.3) - 0.5) < 1e-6
