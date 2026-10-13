"""Matchup-signal engine: registry rules, as-of features (no look-ahead), lift statistics (lane signal-engine-nba)."""
from __future__ import annotations

import importlib.util
from datetime import date
from pathlib import Path

from syndicate.features.shared import matchup_signals as ms


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).resolve().parents[1] / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_player_names_join_across_sources() -> None:
    assert ms.norm_player("Luka Dončić") == ms.norm_player("luka doncic")
    assert ms.norm_player("Jaren Jackson Jr.") == ms.norm_player("Jaren Jackson")
    assert ms.norm_player("D'Angelo Russell") == "dangelo russell"


def test_minutes_trend_needs_13_prior_games_and_compares_last3_to_the_10_before() -> None:
    assert ms.minutes_features([30.0] * 12)["min_trend"] is None
    f = ms.minutes_features([20.0] * 10 + [30.0] * 3)
    assert f["min_trend"] == 10.0 and f["min_prior10"] == 23.0


def test_start_promotion_inputs_and_rest_days() -> None:
    assert ms.start_features([0] * 10 + [1]) == {"started_last": True, "starts_prior10_before_last": 0}
    assert ms.start_features([0] * 5 + [None] * 5 + [1])["started_last"] is None  # too few known starts
    assert ms.team_rest_days([date(2026, 1, 1), date(2026, 1, 3)], date(2026, 1, 4)) == 1
    assert ms.team_rest_days([], date(2026, 1, 4)) is None


def test_firing_rules_match_the_registered_thresholds() -> None:
    base = {"min_trend": 0.0, "min_prior10": 32.0, "started_last": False, "starts_prior10_before_last": 10,
            "rest_days": 2, "spread_abs": 3.0}
    assert ms.nba_signal_fires(base) == []
    assert ms.nba_signal_fires({**base, "min_trend": 4.0}) == ["nba.minutes_trend_up"]
    assert ms.nba_signal_fires({**base, "min_trend": -4.0}) == ["nba.minutes_trend_down"]
    assert ms.nba_signal_fires({**base, "started_last": True, "starts_prior10_before_last": 3}) == ["nba.start_promotion"]
    assert ms.nba_signal_fires({**base, "rest_days": 1}) == ["nba.b2b"]
    assert ms.nba_signal_fires({**base, "rest_days": 1, "min_prior10": 27.9}) == []
    assert ms.nba_signal_fires({**base, "spread_abs": 10.0}) == ["nba.blowout_risk"]
    assert ms.nba_signal_fires({**base, "min_trend": None, "rest_days": None, "spread_abs": None}) == []
    assert set(ms.REGISTRY) >= {"nba.minutes_trend_up", "nba.minutes_trend_down", "nba.start_promotion",
                                "nba.b2b", "nba.blowout_risk"}


def test_built_features_never_see_the_game_itself_or_later() -> None:
    bns = _load("build_nba_signals")
    logs = [{"player": "A B", "key": "a b", "team": "T", "game_id": str(i), "date": f"2026-01-{i + 1:02d}",
             "min": 20.0 if i < 13 else 45.0} for i in range(15)]
    tables = bns.build(logs, starts={}, spreads={})
    day14 = tables["2026-01-14"][0]  # game index 13: the first 45-minute game
    assert day14["min_trend"] == 0.0  # computed from the 13 earlier 20-minute games only
    day15 = tables["2026-01-15"][0]
    assert day15["min_trend"] == round(((20 + 20 + 45) / 3) - 20, 3)
    assert day15["rest_days"] == 1


def test_residual_stats_and_bh() -> None:
    rows = [{"y": 1.0, "p": 0.5, "game": g} for g in range(20)] + [{"y": 0.0, "p": 0.5, "game": g} for g in range(20, 30)]
    s = ms.residual_stats(rows, B=300)
    assert s["n"] == 30 and s["games"] == 30 and abs(s["residual"] - (20 / 30 - 0.5)) < 1e-4
    assert s["ci95"][0] < s["residual"] < s["ci95"][1]
    assert ms.bh_adjust({"a": 0.001, "b": 0.04, "c": 0.5}, q=0.10) == {"a": True, "b": True, "c": False}


def test_lift_evaluate_joins_lines_outcomes_and_signals() -> None:
    sl = _load("signal_lift")
    day = "2026-02-10"  # confirm window
    lines = {day: [{"event": "e1", "market": "player_points", "player_key": "a b", "point": 20.5, "p_over": 0.5, "books": 3},
                   {"event": "e2", "market": "player_points", "player_key": "c d", "point": 10.5, "p_over": 0.5, "books": 3}]}
    outcomes = {("a b", day): {"PTS": 25.0, "REB": 1.0, "AST": 1.0, "FG3M": 0.0, "MIN": 34.0},
                ("c d", day): {"PTS": 5.0, "REB": 1.0, "AST": 1.0, "FG3M": 0.0, "MIN": 20.0}}
    signals = {day: {"a b": {"min_trend": 6.0, "fires": ["nba.minutes_trend_up"]},
                     "c d": {"min_trend": 0.0, "fires": []}}}
    rep = sl.evaluate(lines, outcomes, signals)
    up = rep["signals"]["nba.minutes_trend_up"]["confirm"]
    assert rep["lines_joined"] == 2
    assert up["fired"]["n"] == 1 and up["fired"]["hit_rate"] == 1.0 and up["fired"]["residual"] == 0.5
    assert up["baseline"]["n"] == 1 and up["baseline"]["hit_rate"] == 0.0


def test_unders_main_line_is_the_most_quoted_point_and_roi_uses_the_price(tmp_path) -> None:
    ut = _load("nba_unders_test")
    csv_path = tmp_path / "2026-02-10.csv"
    header = "snapshot_ts,event_id,commence_time,bookmaker,bookmaker_title,market,outcome_name,player_name,point,price,last_update,home_team,away_team\n"
    rows = []
    for book in ("dk", "fd", "mgm"):
        rows += [f"t,e1,c,{book},B,player_points,Over,A B,20.5,-110,t,H,A", f"t,e1,c,{book},B,player_points,Under,A B,20.5,-110,t,H,A"]
    rows += ["t,e1,c,dk,B,player_points,Over,A B,22.5,120,t,H,A", "t,e1,c,dk,B,player_points,Under,A B,22.5,-150,t,H,A"]
    csv_path.write_text(header + "\n".join(rows) + "\n")
    lines = ut.main_lines(csv_path)
    assert len(lines) == 1 and lines[0]["point"] == 20.5 and lines[0]["books"] == 3
    assert abs(lines[0]["p_over"] - 0.5) < 1e-9
    roi = ut.roi_stats([{"y": 1.0, "under_dec_best": 2.0, "game": "g1"}, {"y": 0.0, "under_dec_best": 2.0, "game": "g2"}],
                       "under_dec_best", B=50)
    assert roi["roi_pct"] == 0.0


def test_forward_as_of_table_uses_only_earlier_games_and_covers_every_player() -> None:
    bns = _load("build_nba_signals")
    logs = [{"player": "A B", "key": "a b", "team": "T", "game_id": str(i), "date": f"2026-11-{i + 1:02d}", "min": 30.0}
            for i in range(14)]
    logs.append({"player": "A B", "key": "a b", "team": "T", "game_id": "x", "date": "2026-11-15", "min": 99.0})
    rows = bns.build_as_of(logs, starts={}, spreads={}, day="2026-11-15")
    assert len(rows) == 1 and rows[0]["date"] == "2026-11-15" and rows[0]["as_of"] is True
    assert rows[0]["min_trend"] == 0.0           # the 99-minute game ON the date is never read
    assert rows[0]["rest_days"] == 1
    assert bns._season_for("2026-11-15") == ("2026-27", 2026) and bns._season_for("2027-03-01") == ("2026-27", 2026)


def test_under_bias_adjusts_nba_prop_likelihood_only_and_is_switchable(monkeypatch) -> None:
    monkeypatch.delenv("SYNDICATE_NBA_UNDER_BIAS_DELTA", raising=False)
    under = {"sport": "nba", "kind": "prop", "market": "player_threes", "side": "under"}
    over = dict(under, side="over")
    assert ms.likelihood_adjustments(under) == [{"signal": "nba.under_bias", "delta": 0.0123}]
    assert ms.likelihood_adjustments(over) == [{"signal": "nba.under_bias", "delta": -0.0123}]
    assert ms.likelihood_adjustments(dict(under, sport="nfl")) == []
    assert ms.likelihood_adjustments(dict(under, market="player_double_double")) == []
    assert ms.likelihood_adjustments({"sport": "nba", "kind": "game", "market": "totals", "side": "under"}) == []
    monkeypatch.setenv("SYNDICATE_NBA_UNDER_BIAS_DELTA", "0")
    assert ms.likelihood_adjustments(under) == []
    monkeypatch.setenv("SYNDICATE_NBA_UNDER_BIAS_DELTA", "garbage")
    assert ms.nba_under_bias_delta() == 0.0123


def test_board_stamps_the_shadow_likelihood_and_the_recorder_keeps_it(monkeypatch) -> None:
    from syndicate.features.shared import layer2_board as lb
    from syndicate.features.shared.opportunity_population_ledger import population_record

    monkeypatch.delenv("SYNDICATE_NBA_UNDER_BIAS_DELTA", raising=False)
    row = {"sport": "nba", "kind": "prop", "market": "player_rebounds", "side": "under",
           "quote": {"fair_probability": 0.5, "fair_method": "consensus", "price": -110}}
    one_sided = {"sport": "nba", "kind": "prop", "market": "player_rebounds", "side": "under",
                 "quote": {"fair_probability": 0.5, "fair_method": "book_margin_model", "price": -110}}
    assert lb._stamp_likelihood_shadow([row, one_sided]) == {"nba": 1}
    lk = row["likelihood"]
    assert lk["mode"] == "shadow" and lk["p"] == 0.5123 and lk["p_market"] == 0.5
    assert lk["ev_pct"] is not None and "likelihood" not in one_sided
    assert row["quote"]["fair_probability"] == 0.5  # the market fair the score reads is untouched
    rec = population_record(row, "k", "2026-10-13T00:00:00Z", sport="nba")
    assert rec["lk"] == 0.5123 and rec["lke"] == lk["ev_pct"]
