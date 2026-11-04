"""Women's college basketball sims (lane wncaab-module, user 2026-11-02 "Approve the loans").

The men's producers, team model and re-sim take a `league` switch; every NCAAB path and value stays the
default. These tests pin both halves: the women's switch reaches the women's data, and the men's does not move.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, REPO / rel)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_ratings_producer_switches_registry_path_and_root(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNDICATE_DATA_ROOT", str(tmp_path))
    monkeypatch.delenv("SYNDICATE_NCAAB_SOURCE_ROOT", raising=False)
    monkeypatch.delenv("SYNDICATE_WNCAAB_SOURCE_ROOT", raising=False)
    ratings = _load("ratings_wncaab_test", "scripts/build_ncaab_team_ratings.py")
    men = ratings.load_registry()
    assert "mens-college-basketball" in ratings.SPORT_PATH and ratings.ncaab_root() == tmp_path / "ncaab_source"
    ratings.configure_league("wncaab")
    women = ratings.load_registry()
    assert "womens-college-basketball" in ratings.SPORT_PATH and ratings.processed_dir() == tmp_path / "wncaab_source" / "data" / "processed"
    # Queens is D-I in both leagues: ESPN's men's team list omits it and the registry supplement adds it (11-04).
    assert len(women) >= 350 and {"2511", "88"} <= set(women) and "2511" in men and "2385" in women
    ratings.configure_league("ncaab")
    assert ratings.load_registry() == men


def test_player_priors_producer_follows_the_ratings_switch(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNDICATE_DATA_ROOT", str(tmp_path))
    monkeypatch.delenv("SYNDICATE_WNCAAB_SOURCE_ROOT", raising=False)
    priors = _load("priors_wncaab_test", "scripts/build_ncaab_player_priors.py")
    priors.ratings.configure_league("wncaab")
    try:
        assert priors.box_path(2026) == tmp_path / "wncaab_source" / "data" / "processed" / "player_game_box_2026.csv"
    finally:
        priors.ratings.configure_league("ncaab")
    assert priors.box_path(2026) == tmp_path / "ncaab_source" / "data" / "processed" / "player_game_box_2026.csv"


def test_womens_engine_is_bound_to_four_quarters():
    from syndicate.features.basketball_engine import league_params
    from syndicate.features.ncaab import live_resim as lr

    params = league_params("wncaab")
    assert (params.regulation_periods, params.regulation_period_seconds, params.shot_clock_seconds) == (4, 600, 30)
    assert params.personal_foul_limit == 5 and params.team_fouls_for_bonus == 5
    assert league_params("ncaab").regulation_periods == 2  # the men's geometry is unchanged
    assert lr.ncaab_engine(exact_target=True, league="wncaab").params.code == "wncaab"
    assert lr.ncaab_engine(exact_target=True).params.code == "ncaab"


def test_resim_segments_follow_the_league():
    from syndicate.features.ncaab import live_resim as lr

    women = lr.resim_live_game({}, None, sims=100, simulate=lambda rng, gs: (None, None, [20, 18, 15, 17], [16, 14, 19, 12]),
                               league="wncaab")
    segs = women["segments"]
    assert sorted(segs) == ["h1", "h2", "q1", "q2", "q3", "q4"]
    assert segs["q3"]["total_dist"] == {"34": 100} and segs["q3"]["margin_dist"] == {"-4": 100}
    assert segs["h1"]["total_dist"] == {"68": 100} and segs["h2"]["margin_dist"] == {"1": 100}
    assert women["total_dist"] == {"131": 100}
    men = lr.resim_live_game({}, None, sims=100, simulate=lambda rng, gs: (None, None, [40, 38], [35, 33]))
    assert sorted(men["segments"]) == ["h1", "h2"] and men["segments"]["h1"]["margin_dist"] == {"5": 100}


def test_womens_inputs_run_no_men_fitted_adjustment(monkeypatch, tmp_path):
    from types import SimpleNamespace

    from syndicate.features.ncaab import live_resim as lr

    monkeypatch.setenv("SYNDICATE_NCAAB_HALF_SPLIT", "1")
    monkeypatch.setenv("SYNDICATE_NCAAB_LIVE_MECHANISMS", '{"endgame_foul_window_s": 120}')
    monkeypatch.setattr(lr, "team_frame", lambda rows, team_code, date: f"frame:{team_code}")
    prior = SimpleNamespace(possessions=70.0, home_points=72.0, away_points=66.0, total=138.0, home_margin=6.0,
                            ratings_as_of=__import__("datetime").date(2026, 11, 2), prior_season_fallback=True)
    priors = SimpleNamespace(by_team={"1": [{}], "2": [{}]}, as_of=__import__("datetime").date(2026, 11, 2))
    women = lr.build_engine_inputs("2026-11-03", "1", "2", neutral=False, priors=priors, team_prior=prior, league="wncaab")
    men = lr.build_engine_inputs("2026-11-03", "1", "2", neutral=False, priors=priors, team_prior=prior)
    assert women["quarters"] is None and women["_provenance"]["halfSplit"] is False and women["_provenance"]["mechanisms"] == []
    assert women["_provenance"]["league"] == "wncaab"
    assert men["quarters"] is not None and men["_provenance"]["halfSplit"] is True and men["_provenance"]["mechanisms"] == ["endgame_foul_window_s"]


def test_team_model_reads_the_womens_tables(tmp_path, monkeypatch):
    from syndicate.features.ncaab import live_team_model as tm

    monkeypatch.setenv("SYNDICATE_WNCAAB_SOURCE_ROOT", str(tmp_path / "w"))
    monkeypatch.setenv("SYNDICATE_NCAAB_SOURCE_ROOT", str(tmp_path / "m"))
    assert tmp_path / "w" / "data" / "processed" in tm.ratings_dirs("wncaab")
    assert tmp_path / "m" / "data" / "processed" in tm.ratings_dirs()
    refusal = tm.prior_for_game(__import__("datetime").date(2026, 11, 3), "1", "2", neutral=False, league="wncaab")
    assert refusal.reason == "no_ratings_table" and "wncaab_source" not in str(tmp_path) and str(tmp_path / "w").replace("\\", "\\\\") in refusal.detail


def test_daily_womens_input_refresh_runs_once_after_11z(tmp_path, monkeypatch):
    import datetime as dt

    monkeypatch.setenv("SYNDICATE_DATA_ROOT", str(tmp_path))
    build = _load("build_pregame_test", "scripts/build_college_pregame_sims.py")
    calls = []
    run = lambda command, cwd=None: calls.append(command) or type("P", (), {"returncode": 0})()  # noqa: E731
    early = dt.datetime(2026, 11, 3, 9, 0, tzinfo=dt.timezone.utc)
    late = dt.datetime(2026, 11, 3, 12, 0, tzinfo=dt.timezone.utc)
    assert build.refresh_womens_inputs(early, run=run) == "before_11z" and not calls
    assert build.refresh_womens_inputs(late, run=run) == "refreshed" and len(calls) == 2
    assert all("--league" in c and "wncaab" in c for c in calls)
    assert build.refresh_womens_inputs(late, run=run) == "already_today" and len(calls) == 2


def test_ratings_producer_does_not_regress_a_calibrated_prior_again():
    # One neutral game each way, so this season's estimate is the league mean and the prior carries the rest.
    ratings = _load("ratings_prior_k_test", "scripts/build_ncaab_team_ratings.py")
    d1 = {"1": "A", "2": "B"}
    rows = [{"game_id": "g", "team_id": "1", "opp_id": "2", "pts": 70, "opp_pts": 70, "poss": 70, "site": "neutral"},
            {"game_id": "g", "team_id": "2", "opp_id": "1", "pts": 70, "opp_pts": 70, "poss": 70, "site": "neutral"}]

    def gap(prior):
        out = ratings.compute_ratings(rows, d1, prior=prior)
        return out["1"]["adj_off"] - out["2"]["adj_off"]

    calibrated = {"1": {"adj_off": 120.0, "adj_def": 100.0, "tempo": 70.0, "calibration_k": 0.78},
                  "2": {"adj_off": 80.0, "adj_def": 100.0, "tempo": 70.0, "calibration_k": 0.78}}
    legacy = {t: {k: v for k, v in r.items() if k != "calibration_k"} for t, r in calibrated.items()}
    weight = 1 / (1 + ratings.PRIOR_GAMES)  # one game played: the prior's share is 1 - weight
    assert abs(gap(calibrated) - (1 - weight) * 40.0) < 0.05  # the calibrated prior's gap, unshrunk
    assert abs(gap(legacy) - (1 - weight) * 40.0 * (1 - ratings.PRIOR_REGRESSION)) < 0.05  # legacy still regressed
