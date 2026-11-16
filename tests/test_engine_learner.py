"""Phase 1B M2 shadow learner (lane engine-learner): off == prior, signal recovered, noise / harm never applied,
partial pooling, clustered uncertainty, example building."""
from __future__ import annotations

import math
import random

import pytest

from syndicate.features.shared import engine_learner as el


def _sig(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def _synthetic(*, n_games: int, lines_per_game: int, true_w: dict[str, float], seed: int, date: str = "2026-11-10",
               cell: tuple[str, ...] = ("nba", "totals", "totals_alt", "full", "live", "25-50"),
               ticks: int = 1) -> list[el.Example]:
    rng = random.Random(seed)
    out = []
    for g in range(n_games):
        for i in range(lines_per_game):
            lp = rng.uniform(-1.5, 1.5)
            deltas = {e: rng.gauss(0.0, 0.6) for e in true_w}
            p = _sig(lp + sum(true_w[e] * d for e, d in deltas.items()))
            y = 1.0 if rng.random() < p else 0.0
            for t in range(ticks):
                out.append(el.Example(key=f"{date}|g{g}|l{i}|t{t}", line_key=f"{date}|g{g}|l{i}", cluster=f"{date}|g{g}",
                                      date=date, cell=cell, logit_prior=lp, deltas=dict(deltas), y=y,
                                      weight=1.0 / ticks))
    return out


def test_off_is_the_prior_exactly():
    exs = _synthetic(n_games=40, lines_per_game=10, true_w={"live_resim": 1.0}, seed=1)
    for ex in exs:
        assert el.p_decision(ex, None) == pytest.approx(_sig(ex.logit_prior), abs=1e-15)
    rep = el.evaluate(exs, None)
    assert all(v["delta_log_loss"] == 0.0 for v in rep.values())


def test_zero_deltas_fit_zero_weights():
    exs = _synthetic(n_games=30, lines_per_game=10, true_w={"sim": 1.0}, seed=2)
    for ex in exs:
        ex.deltas = {"sim": 0.0}
    model = el.fit(exs)
    assert max(abs(t) for t in model.theta) < 1e-9
    for ex in exs[:50]:
        assert el.p_decision(ex, model) == pytest.approx(_sig(ex.logit_prior), abs=1e-12)


def test_signal_recovered_applied_and_beats_prior_held_out():
    train = _synthetic(n_games=200, lines_per_game=20, true_w={"live_resim": 1.0}, seed=3, date="2026-11-10")
    test = _synthetic(n_games=100, lines_per_game=20, true_w={"live_resim": 1.0}, seed=4, date="2026-11-20")
    model = el.fit(train)
    cell = train[0].cell
    w, se = model.weight("live_resim", cell)
    assert 0.75 < w < 1.15, (w, se)
    assert model.applied_weight("live_resim", cell) == w
    rep = el.evaluate(test, model)
    (k, v), = rep.items()
    assert k == ("nba", "totals", "live")
    assert v["delta_log_loss"] < 0 and v["beats_prior"], v
    # off != on: the fitted learner moves the probability
    assert any(abs(el.p_decision(ex, model) - el.p_decision(ex, None)) > 1e-3 for ex in test[:20])


def test_noise_expert_rarely_applied_and_prior_exact_when_not():
    """A useless expert is applied only at the bound's false-positive rate (one-sided 2.5%), never routinely; and
    where it is not applied, p_decision is the prior exactly. (Seed 5 alone lands at 2.2 SE -- a single draw cannot
    test a 95% bound, a rate over seeds can.)"""
    applied = 0
    for seed in range(100, 120):
        exs = _synthetic(n_games=100, lines_per_game=15, true_w={"under_tilt": 0.0}, seed=seed)
        model = el.fit(exs)
        if model.applied_weight("under_tilt", exs[0].cell) != 0.0:
            applied += 1
            continue
        for ex in exs[:20]:
            assert el.p_decision(ex, model) == pytest.approx(_sig(ex.logit_prior), abs=1e-12)
    assert applied <= 3, applied


def test_harmful_expert_never_applied():
    exs = _synthetic(n_games=150, lines_per_game=20, true_w={"sim": -1.0}, seed=6)
    model = el.fit(exs)
    w, _ = model.weight("sim", exs[0].cell)
    assert w < -0.5
    assert model.applied_weight("sim", exs[0].cell) == 0.0


def test_thin_leaf_borrows_its_parent():
    fat = _synthetic(n_games=200, lines_per_game=20, true_w={"live_resim": 1.0}, seed=7,
                     cell=("nba", "totals", "totals_alt", "full", "live", "25-50"))
    thin = _synthetic(n_games=3, lines_per_game=2, true_w={"live_resim": 1.0}, seed=8,
                      cell=("nba", "totals", "totals_alt", "full", "live", "75-95"))
    model = el.fit(fat + thin)
    w_thin, _ = model.weight("live_resim", thin[0].cell)
    w_fat, _ = model.weight("live_resim", fat[0].cell)
    assert w_thin > 0.5 and abs(w_thin - w_fat) < 0.3, (w_thin, w_fat)
    # an unseen cell under a seen parent falls back to the parent's path
    unseen = ("nba", "totals", "totals_alt", "full", "live", "0-25")
    w_unseen, _ = model.weight("live_resim", unseen)
    assert w_unseen > 0.5


def test_unseen_expert_or_sport_contributes_nothing():
    exs = _synthetic(n_games=50, lines_per_game=10, true_w={"live_resim": 1.0}, seed=9)
    model = el.fit(exs)
    assert model.weight("stat_progress", exs[0].cell) == (0.0, 0.0)


def test_repeated_ticks_do_not_shrink_the_clustered_error():
    one = _synthetic(n_games=60, lines_per_game=10, true_w={"live_resim": 0.5}, seed=10, ticks=1)
    many = _synthetic(n_games=60, lines_per_game=10, true_w={"live_resim": 0.5}, seed=10, ticks=8)
    m1, m8 = el.fit(one), el.fit(many)
    w1, se1 = m1.weight("live_resim", one[0].cell)
    w8, se8 = m8.weight("live_resim", many[0].cell)
    assert w8 == pytest.approx(w1, abs=1e-4)
    assert se8 == pytest.approx(se1, rel=0.05)


def test_forward_split_by_date():
    a = _synthetic(n_games=2, lines_per_game=2, true_w={"sim": 1.0}, seed=11, date="2026-11-10")
    b = _synthetic(n_games=2, lines_per_game=2, true_w={"sim": 1.0}, seed=12, date="2026-11-12")
    train, test = el.forward_split(a + b, "2026-11-11")
    assert {e.date for e in train} == {"2026-11-10"} and {e.date for e in test} == {"2026-11-12"}


def _op(**kw):
    base = {"expert": "live_resim", "phase": "live", "t": "2026-11-10T01:00:00Z", "sport": "nba", "event_id": "E1",
            "line_key": "nba|E1|totals|full||over|220.5", "market": "totals", "segment": "full", "side": "over",
            "line": 220.5, "p_prior": 0.5, "delta_logit": 0.2, "clock_bucket": "25-50", "refusal": None}
    base.update(kw)
    return base


def test_build_examples_counts_and_tick_weights():
    ops = [
        ("2026-11-10", _op()),
        ("2026-11-10", _op(t="2026-11-10T01:01:00Z")),
        ("2026-11-10", _op(expert="live_segment", delta_logit=-0.1)),          # same line-instant, second expert
        ("2026-11-10", _op(expert="live_segment", p_prior=0.6, t="2026-11-10T01:01:00Z")),  # prior disagrees
        ("2026-11-10", _op(refusal="stale_prior")),
        ("2026-11-10", _op(delta_logit=None, t="x")),
        ("2026-11-10", _op(line_key="nba|E1|totals|full||over|221", line=221.0)),  # push
        ("2026-11-10", _op(line_key="nba|E2|totals|full||over|210.5", event_id="E2")),  # no truth
    ]

    def truth(op):
        if op["event_id"] == "E2":
            return None, "no_final"
        if op["line"] == 221.0:
            return 0.5, None
        return 1.0, None

    exs, st = el.build_examples(ops, truth)
    assert st.refused == 1 and st.unusable == 1 and st.push == 1 and st.no_truth == 1
    assert st.by_truth_refusal == {"no_final": 1} and st.prior_disagree == 1
    assert st.examples == 2 and st.lines == 1 and st.games == 1
    assert all(ex.weight == 0.5 for ex in exs)
    first = next(ex for ex in exs if ex.key.endswith("01:00:00Z"))
    assert first.deltas == {"live_resim": 0.2, "live_segment": -0.1}
    assert first.cell == ("nba", "totals", "totals", "full", "live", "25-50", "a?")


def test_game_id_prefers_the_evidence_id_and_age_buckets():
    assert el.game_id({"event_id": "ledger1", "inputs": {"evidence_event_id": "401"}}) == "401"
    assert el.game_id({"event_id": "401", "inputs": {}}) == "401"
    exs, _ = el.build_examples([("2026-11-10", _op(event_id="ledger1", inputs={"evidence_event_id": "401"},
                                                   prior_age_s=45.0))], lambda op: (1.0, None))
    assert exs[0].cluster == "nba|401" and exs[0].cell[-1] == "a<=60" and exs[0].prior_age_s == 45.0
    assert [el.prior_age_bucket(a) for a in (60, 61, 180, 900, 901, None)] == [
        "a<=60", "a60-180", "a60-180", "a180-900", "a>900", "a?"]


def test_family_mapping():
    assert el.family_of("totals_alt") == "totals"
    assert el.family_of("spreads") == "spreads"
    assert el.family_of("h2h") == "h2h"
    assert el.family_of("player_points") == "props"


def test_module_is_shadow_only():
    import pathlib

    src = pathlib.Path(el.__file__).read_text(encoding="utf-8")
    assert "import engine_experts" not in src and "from syndicate.features.shared.engine_experts" not in src
    for banned in ("kalshi_order", "portfolio_commit", "kalshi_board_join"):
        assert banned not in src


# ----------------------------------------------------------------------------- the runner's truth join (slice 1)

import importlib.util  # noqa: E402
import json  # noqa: E402
import sys  # noqa: E402
from pathlib import Path  # noqa: E402

_spec = importlib.util.spec_from_file_location("engine_learner_script",
                                               Path(__file__).resolve().parents[1] / "scripts" / "engine_learner.py")
els = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = els
_spec.loader.exec_module(els)


def test_outcome_rules():
    assert els.outcome("totals", "over", 220.5, 110, 111) == 1.0
    assert els.outcome("totals", "under", 220.5, 110, 111) == 0.0
    assert els.outcome("totals", "over", 221.0, 110, 111) == 0.5
    # spreads: the live join's away frame, home covers when home - away > line
    assert els.outcome("spreads", "home", -8.5, 108, 116) == 1.0
    assert els.outcome("spreads", "home", 7.5, 108, 116) == 0.0
    assert els.outcome("spreads", "home", -8.0, 108, 116) == 0.5
    assert els.outcome("spreads", "away", 3.5, 108, 116) == els.R_SIDE
    assert els.outcome("h2h", "home", None, 108, 116) == 0.0
    assert els.outcome("h2h", "away", None, 108, 116) == 1.0


def _root(tmp_path):
    p = tmp_path / "nba_source" / "data" / "processed"
    p.mkdir(parents=True)
    (p / "linescores_2026-11-10.json").write_text(json.dumps({"date": "2026-11-10", "games": {
        "E1": {"home": "NO", "away": "DEN", "home_periods": [23, 28, 31, 26], "away_periods": [29, 27, 30, 30]},
        "E3": {"home": "NO", "away": "DEN", "home_periods": [23, 28, None, 26], "away_periods": [29, 27, 30, 30]},
    }}), encoding="utf-8")
    c = tmp_path / "ncaab_source" / "data" / "scoreboard"
    c.mkdir(parents=True)
    (c / "scoreboard_2026-11-10.json").write_text(json.dumps({"games": [
        {"event_id": "C1", "live_state": {"final": True, "home_linescores": [30, 40, 10], "away_linescores": [35, 35, 6]},
         "home": {"name": "Duke Blue Devils", "abbr": "DUKE"}, "away": {"name": "Army Black Knights", "abbr": "ARMY"}},
        {"event_id": "C2", "live_state": {"final": False, "home_linescores": [30], "away_linescores": [35]},
         "home": {"name": "Duke Blue Devils", "abbr": "DUKE"}, "away": {"name": "Army Black Knights", "abbr": "ARMY"}},
    ]}), encoding="utf-8")
    return tmp_path


TEAMS = {
    ("nba", "E1"): {"home": "NOP", "away": "DEN"},
    ("nba", "E2"): {"home": "NOP", "away": "DEN"},
    ("nba", "E3"): {"home": "NOP", "away": "DEN"},
    ("ncaab", "C1"): {"home_name": "Duke Blue Devils", "away_name": "Army Black Knights", "home": "DUKE", "away": "ARMY"},
}


def _truth(tmp_path, teams=TEAMS):
    return els.BasketballTruth(["2026-11-10"], root=_root(tmp_path), evidence_teams=teams)


def _lop(**kw):
    base = {"phase": "live", "sport": "nba", "event_id": "E1", "market": "totals", "segment": "full", "side": "over",
            "line": 220.5}
    base.update(kw)
    return base


def test_nba_full_and_segments(tmp_path):
    t = _truth(tmp_path)
    assert t(_lop()) == (1.0, None)                                    # 108 + 116 = 224
    assert t(_lop(market="spreads_alt", side="home", line=-8.5)) == (1.0, None)
    assert t(_lop(market="h2h", side="home", line=None)) == (0.0, None)
    assert t(_lop(segment="h1", line=106.5)) == (1.0, None)            # 51 + 56 = 107
    assert t(_lop(segment="q3", line=61.5)) == (0.0, None)             # 31 + 30 = 61


def test_nba_espn_codes_alias_and_swapped(tmp_path):
    teams = dict(TEAMS)
    teams[("nba", "E1")] = {"home": "DEN", "away": "NOP"}             # the slate re-oriented the game
    t = _truth(tmp_path, teams)
    assert t(_lop(market="h2h", side="home", line=None)) == (1.0, None)   # evidence home DEN won 116-108
    assert t(_lop(market="spreads", side="home", line=7.5)) == (1.0, None)


def test_unresolved_orientation_grades_totals_only(tmp_path):
    teams = dict(TEAMS)
    teams[("nba", "E1")] = {"home": "BOS", "away": "MIA"}
    t = _truth(tmp_path, teams)
    assert t(_lop()) == (1.0, None)
    assert t(_lop(market="spreads", side="home", line=-8.5)) == (None, els.R_ORIENT)


def test_refusals_by_name(tmp_path):
    t = _truth(tmp_path)
    assert t(_lop(event_id="E2")) == (None, els.R_NO_FINAL)
    assert t(_lop(event_id="E3")) == (None, els.R_SEGMENT)                          # a hole in q3: no full game
    assert t(_lop(event_id="E3", segment="q4", line=50.5)) == (1.0, None)            # q4 is period 4 alone
    assert t(_lop(phase="pregame")) == (None, els.R_PREGAME)
    assert t(_lop(market="player_points")) == (None, els.R_PROPS)
    assert t(_lop(sport="nhl", market="h2h", side="home")) == (None, els.R_SPORT)


def test_college_h2_includes_overtime_and_final_only(tmp_path):
    t = _truth(tmp_path)
    assert t(_lop(sport="ncaab", event_id="C1", segment="h2", line=90.5)) == (1.0, None)   # 50 + 41 = 91
    assert t(_lop(sport="ncaab", event_id="C1", line=155.5)) == (1.0, None)                # 80 + 76 = 156
    assert t(_lop(sport="ncaab", event_id="C1", market="spreads", side="home", line=3.5)) == (1.0, None)
    assert t(_lop(sport="ncaab", event_id="C2")) == (None, els.R_NO_FINAL)
