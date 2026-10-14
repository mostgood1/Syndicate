"""Football matchup signals: as-of features (no look-ahead), firing rules, main lines, lift (lane signal-engine-football)."""
from __future__ import annotations

import importlib.util
from pathlib import Path

from syndicate.features.shared import matchup_signals_football as fb


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).resolve().parents[1] / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


T = {**fb.THRESHOLDS, "nfl_tgt_up": 0.05, "nfl_tgt_down": 0.05, "nfl_carry_up": 0.10, "nfl_carry_down": 0.10,
     "nfl_vac_tgt": 0.15, "nfl_vac_carry": 0.25, "nfl_proe_high": 3.0, "nfl_proe_low": 6.0, "ncaaf_carry_up": 0.10,
     "ncaaf_carry_down": 0.10, "ncaaf_rec_up": 0.05, "ncaaf_rec_down": 0.05, "ncaaf_pace": 150.0}


def test_share_features_pool_counts_and_need_two_base_games() -> None:
    f = fb.share_features([(2, 10), (2, 10), (5, 10), (5, 10), (5, 10)], "tgt")
    assert f["tgt_l3"] == 0.5 and f["tgt_base"] == 0.2 and f["tgt_trend"] == 0.3 and f["tgt_season"] == 0.38
    short = fb.share_features([(2, 10), (5, 10), (5, 10), (5, 10)], "tgt")
    assert short["tgt_base"] is None and short["tgt_trend"] is None
    assert fb.share_features([(1, 0)], "x")["x_season"] is None  # no team volume -> unknown, not zero


def _play(game, week, team, **kw):
    base = {"season_type": "REG", "game_id": game, "week": str(week), "posteam": team, "pass_attempt": "0",
            "rush_attempt": "0", "sack": "0", "two_point_attempt": "0", "play_type": "pass", "pass_oe": ""}
    return {**base, **{k: str(v) for k, v in kw.items()}}


def test_nfl_counts_use_official_targets_and_real_carries() -> None:
    b = _load("build_nfl_signals")
    plays = [
        _play("g1", 1, "KC", pass_attempt=1, passer_player_id="qb", receiver_player_id="wr", air_yards=12, pass_oe=20),
        _play("g1", 1, "KC", pass_attempt=1, passer_player_id="qb", sack=1, pass_oe=-10),           # sack: no target
        _play("g1", 1, "KC", pass_attempt=1, passer_player_id="qb", receiver_player_id="wr", two_point_attempt=1),
        _play("g1", 1, "KC", rush_attempt=1, rusher_player_id="rb", play_type="run"),
        _play("g1", 1, "KC", rush_attempt=1, rusher_player_id="qb", play_type="qb_kneel"),            # kneel: no carry
    ]
    players, teams = b.game_counts(plays)
    assert teams[("g1", "KC")]["targets"] == 1 and teams[("g1", "KC")]["carries"] == 1
    assert teams[("g1", "KC")]["pass_att"] == 1 and teams[("g1", "KC")]["proe_sum"] == 10.0
    assert players[("g1", "wr")]["air_yards"] == 12.0 and ("g1", "rb") in players


def test_nfl_week_table_is_as_of_and_vacated_counts_only_fresh_absences() -> None:
    b = _load("build_nfl_signals")
    plays = []
    for wk in (1, 2, 3):
        g = f"g{wk}"
        plays += [_play(g, wk, "KC", pass_attempt=1, passer_player_id="qb", receiver_player_id="wr1")] * 3
        plays += [_play(g, wk, "KC", pass_attempt=1, passer_player_id="qb", receiver_player_id="wr2")]
        if wk == 1:  # wr3 played week 1 only
            plays += [_play(g, wk, "KC", pass_attempt=1, passer_player_id="qb", receiver_player_id="wr3")] * 4
    plays += [_play("g4", 4, "KC", pass_attempt=1, passer_player_id="qb", receiver_player_id="wr2")] * 50  # week 4 itself
    players, teams = b.game_counts(plays)
    out = {(4, "KC"): {"wr1", "wr3"}}  # wr1 played week 3 (fresh); wr3 last played week 1 (stale)
    rows = {r["player_id"]: r for r in b.build_week(players, teams, out, 4)}
    assert rows["wr2"]["games_prior"] == 3 and rows["wr2"]["tgt_share_season"] == round(3 / 16, 4)  # week 4 unseen
    assert rows["wr1"]["out_this_week"] is True and rows["wr2"]["out_this_week"] is False
    assert rows["wr2"]["vac_tgt_fresh"] == rows["wr1"]["tgt_share_season"]  # wr3 not counted
    assert rows["wr2"]["vac_players"] == ["wr1"]


def test_nfl_firing_rules_follow_thresholds_and_never_fire_on_unknowns_or_an_out_player() -> None:
    f = {"tgt_trend": 0.06, "carry_trend": -0.12, "vac_tgt_fresh": 0.2, "tgt_share_season": 0.12,
         "vac_carry_fresh": 0.0, "carry_share_season": 0.3, "team_proe": 4.0, "pass_share_season": 0.0}
    assert set(fb.nfl_signal_fires(f, T)) == {"nfl.target_share_up", "nfl.carry_share_down", "nfl.vacated_targets"}
    assert fb.nfl_signal_fires({**f, "out_this_week": True}, T) == []
    assert "nfl.team_pass_heavy" in fb.nfl_signal_fires({**f, "pass_share_season": 0.95}, T)
    assert fb.nfl_signal_fires({}, T) == []
    assert fb.nfl_signal_fires(f, {**T, "nfl_tgt_up": 0.0, "nfl_carry_down": 0.0, "nfl_vac_tgt": 0.0}) == []  # 0.0 never fires
    assert fb.nfl_eligible("nfl.vacated_targets", f, T) and not fb.nfl_eligible("nfl.vacated_targets", {**f, "tgt_share_season": 0.05}, T)


def test_ncaaf_week_table_counts_team_rows_in_totals_but_never_as_players() -> None:
    b = _load("build_ncaaf_signals")
    box = []
    for wk in (1, 2):
        for name, ra, rec in (("Rb One", 10, 0), ("Team", 2, 0), ("Wr One", 0, 4)):
            box.append({"season": 2025, "week": wk, "game_id": f"g{wk}", "player_id": name, "player": name,
                        "key": name.lower(), "team": "State", "opponent": "Tech", "is_team_row": name == "Team",
                        "rushing_attempts": ra, "receptions": rec, "passing_attempts": 20})
    teams = b.team_games(box)
    rows = b.build_week(box, teams, 2025, 2)
    players = {r["player_key"]: r for r in rows if r["kind"] == "player"}
    assert set(players) == {"rb one", "wr one"} and players["rb one"]["carry_season"] == round(10 / 12, 4)
    team = [r for r in rows if r["kind"] == "team"][0]
    assert team["plays_pg"] == 12 + 60  # week 1 only: 12 rushes + 60 pass attempts (3 rows x 20)


def test_main_line_is_the_most_two_sided_point_with_the_shin_fair() -> None:
    lf = _load("signal_lift_football")
    q = []
    for book in ("dk", "fd", "mgm"):
        q += [{"kind": "prop", "event_id": "e", "market": "Receptions", "selection": s, "player_name": "A B",
               "line": 4.5, "price": -110, "bookmaker": book} for s in ("over", "under")]
    q += [{"kind": "prop", "event_id": "e", "market": "Receptions", "selection": "over", "player_name": "A B",
           "line": 5.5, "price": 120, "bookmaker": "dk"}]  # one-sided: never a candidate
    q += [{"kind": "prop", "event_id": "e", "market": "Anytime TD", "selection": "yes", "player_name": "A B",
           "line": None, "price": 150, "bookmaker": "dk"}]  # not an O/U market
    lines = lf.main_lines(q)
    assert len(lines) == 1 and lines[0]["point"] == 4.5 and lines[0]["books"] == 3 and abs(lines[0]["p_over"] - 0.5) < 1e-9


def test_ncaaf_join_needs_one_player_in_the_game_and_both_teams_for_pace() -> None:
    lf = _load("signal_lift_football")
    week_rows = [{"kind": "player", "player_key": "a b", "team": "State", "carry_trend": 0.2},
                 {"kind": "team", "team": "State", "plays_pg": 70.0}, {"kind": "team", "team": "Tech", "plays_pg": 75.0}]
    counts = {"game_not_in_box": 0, "no_signal_row": 0, "ambiguous_player": 0}
    feats = lf.ncaaf_join({"cfbd_game_id": 1, "player": "A. B"}, week_rows, {"1": {"State", "Tech"}}, counts)
    assert feats["game_pace"] == 145.0 and feats["carry_trend"] == 0.2
    assert lf.ncaaf_join({"cfbd_game_id": 2, "player": "A B"}, week_rows, {"1": {"State", "Tech"}}, counts) is None
    assert counts["game_not_in_box"] == 1


def test_lift_splits_fired_from_baseline_per_window(monkeypatch) -> None:
    lf = _load("signal_lift_football")
    for k, v in T.items():
        monkeypatch.setitem(fb.THRESHOLDS, k, v)
    recs = []
    for i in range(12):
        window = "discover" if i < 6 else "confirm"
        recs.append({"window": window, "game": f"g{i}", "stat": "receptions", "p_over": 0.5, "y_over": 1.0,
                     "feats": {"tgt_trend": 0.08}})
        recs.append({"window": window, "game": f"h{i}", "stat": "receptions", "p_over": 0.5, "y_over": 0.0,
                     "feats": {"tgt_trend": 0.0}})
    rep = lf.lift("nfl", recs)
    up = rep["signals"]["nfl.target_share_up"]
    assert up["confirm"]["fired"]["n"] == 6 and up["confirm"]["fired"]["residual"] == 0.5
    assert up["confirm"]["baseline"]["n"] == 6 and up["confirm"]["hit_lift_vs_baseline"] == 1.0
    assert up["verdict"] == "SUPPORTED"
    down = rep["signals"]["nfl.target_share_down"]
    assert down["confirm"]["fired"]["n"] == 0 and down["verdict"] == "NOT SUPPORTED"


def test_lift_mode_refuses_until_thresholds_are_registered(tmp_path) -> None:
    lf = _load("signal_lift_football")
    if all(v for k, v in fb.THRESHOLDS.items() if k.startswith("nfl")):
        return  # registered: the guard no longer applies
    assert lf.main(["--sport", "nfl", "--mode", "lift", "--data-root", str(tmp_path), "--quotes-dir", str(tmp_path),
                    "--out", str(tmp_path / "x.json")]) == 3


def test_v1_results_mark_every_football_signal_null_with_its_evidence() -> None:
    assert set(fb._V1_RESULTS) == set(fb.FOOTBALL_REGISTRY)
    for spec in fb.FOOTBALL_REGISTRY.values():
        assert spec.status == "null" and spec.evidence["verdict"] == "NOT SUPPORTED" and spec.evidence["confirm_n"] > 0
