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


def test_forward_split_holds_a_game_out_whole():
    pre = _synthetic(n_games=1, lines_per_game=2, true_w={"sim": 1.0}, seed=13, date="2026-11-10")
    live = _synthetic(n_games=1, lines_per_game=2, true_w={"sim": 1.0}, seed=14, date="2026-11-12")
    for ex in live:
        ex.cluster = pre[0].cluster                      # the same game: pregame on an earlier slate, live later
    train, test = el.forward_split(pre + live, "2026-11-11")
    assert train == [] and len(test) == 4


def test_game_dated_moves_a_pregame_line_to_its_games_date():
    events = {"EV1": {"commence": "2026-11-13T01:15:00Z"}}
    ops = [("2026-11-10", {"phase": "pregame", "event_id": "EV1"}), ("2026-11-10", {"phase": "pregame",
                                                                                     "event_id": "NOPE"}),
           ("2026-11-12", {"phase": "live", "event_id": "EV1"})]
    assert [d for d, _ in els.game_dated(ops, events)] == ["2026-11-12", "2026-11-10", "2026-11-12"]


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
            return None, el.PUSH
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


# ----------------------------------------------------------------------------- slice 2: pushes, chips, the close


def test_push_is_a_named_refusal_and_an_even_close_is_a_label():
    ops = [("2026-11-10", _op()), ("2026-11-10", _op(line_key="nba|E1|totals|full||over|221", line=221.0))]

    def truth(op):
        return (None, el.PUSH) if op["line"] == 221.0 else (0.5, None)   # a close at even money

    exs, st = el.build_examples(ops, truth)
    assert st.push == 1 and st.examples == 1 and exs[0].y == 0.5


def test_basketball_push_maps_to_the_push_refusal(tmp_path):
    t = _truth(tmp_path)
    assert t(_lop(line=224.0)) == (None, el.PUSH)                      # 108 + 116 = 224


def test_outcome_book_is_the_books_own_frame():
    # home -6.5 won by 7: covers; away +6.5 lost by 7: does not; home -7: push
    assert els.outcome_book("spreads", "home", -6.5, 27, 20) == 1.0
    assert els.outcome_book("spreads", "away", 6.5, 27, 20) == 0.0
    assert els.outcome_book("spreads", "home", -7.0, 27, 20) == 0.5
    assert els.outcome_book("spreads", "away", -2.5, 20, 27) == 1.0
    assert els.outcome_book("totals", "under", 47.5, 27, 20) == 1.0
    assert els.outcome_book("h2h", "away", None, 27, 20) == 0.0


START = "2026-11-10T01:15:00Z"   # Central 2026-11-09 19:15


def _chip(**kw):
    c = {"sport": "nfl", "state": "final", "start_time_utc": "2026-11-10T01:15:00+00:00",
         "away": {"key": "los angeles chargers", "name": "Los Angeles Chargers", "score": "20"},
         "home": {"key": "baltimore ravens", "name": "Baltimore Ravens", "score": "27"},
         "linescore": {"away": [3, 7, 3, 7], "home": [7, 10, 0, 10], "kind": "periods"}}
    c.update(kw)
    return c


def _events(**extra):
    ev = {
        "EV1": {"sport": "nfl", "home": "Baltimore Ravens", "away": "Los Angeles Chargers", "commence": START,
                "source": "decision_record"},
        "EVSW": {"sport": "nfl", "home": "Los Angeles Chargers", "away": "Baltimore Ravens", "commence": START,
                 "source": "decision_record"},
        "LATE": {"sport": "nfl", "home": "Baltimore Ravens", "away": "Los Angeles Chargers",
                 "commence": "2026-11-15T18:00:00Z", "source": "decision_record"},
        "NHL1": {"sport": "nhl", "home": "Seattle Kraken", "away": "Carolina Hurricanes", "commence": START,
                 "source": "live_ledger"},
        "CB1": {"sport": "ncaab", "home": "Duke Blue Devils", "away": "Army Black Knights", "commence": START,
                "source": "decision_record"},
    }
    ev.update(extra)
    return ev


CHIPS = {"2026-11-09": [
    _chip(),
    _chip(sport="nhl", away={"key": "carolina hurricanes", "name": "Carolina Hurricanes", "score": "4"},
          home={"key": "seattle kraken", "name": "Seattle Kraken", "score": "1"},
          linescore={"away": [1, 2, 1], "home": [0, 1, 0], "kind": "periods"}),
    _chip(sport="ncaab", away={"key": "army black knights", "name": "Army Black Knights", "score": "76"},
          home={"key": "duke blue devils", "name": "Duke Blue Devils", "score": "80"},
          linescore={"away": [35, 35, 6], "home": [30, 40, 10], "kind": "periods"}),
]}


def _chip_truth(chips=CHIPS, events=None, max_commence="2026-11-15T06:00:00Z"):
    calls = []

    def fetch(d):
        calls.append(d)
        return {"chips": chips.get(d, [])}

    src = els.Chips(fetch=fetch, last_date="2026-11-14")
    t = els.ChipTruth(events or _events(), src, max_commence=els._dpp()._epoch(max_commence))
    return t, calls


def _gop(**kw):
    base = {"phase": "pregame", "sport": "nfl", "event_id": "EV1", "market": "totals", "segment": "full",
            "side": "over", "line": 46.5}
    base.update(kw)
    return base


def test_chips_grade_pregame_in_the_books_frame_and_live_in_the_joins():
    t, _ = _chip_truth()
    assert t(_gop()) == (1.0, None)                                                 # 27 + 20 = 47
    assert t(_gop(market="spreads", side="home", line=-6.5)) == (1.0, None)
    assert t(_gop(market="spreads_alt", side="away", line=6.5)) == (0.0, None)
    assert t(_gop(market="spreads", side="home", line=-7.0)) == (None, el.PUSH)
    assert t(_gop(phase="live", market="spreads", side="home", line=6.5)) == (1.0, None)  # live: 7 > 6.5
    assert t(_gop(phase="live", market="h2h", side="home", line=None)) == (1.0, None)


def test_chips_segments_by_the_platform_rule():
    t, _ = _chip_truth()
    assert t(_gop(segment="h1", line=23.5)) == (1.0, None)                          # 17 + 10 = 27
    assert t(_gop(segment="q3", line=3.5)) == (0.0, None)                           # 0 + 3
    assert t(_gop(sport="ncaab", event_id="CB1", segment="h2", line=90.5)) == (1.0, None)   # 50 + 41: OT counts
    assert t(_gop(sport="nhl", event_id="NHL1", segment="p1", line=0.5)) == (None, els.R_SEGMENT)


def test_chips_orientation_window_and_refusals():
    t, _ = _chip_truth()
    # the records name the game the other way round: the chip is matched swapped and the side follows the record
    assert t(_gop(event_id="EVSW", market="h2h", side="home", line=None)) == (0.0, None)
    assert t(_gop(event_id="EVSW", market="spreads", side="away", line=-6.5)) == (1.0, None)
    assert t(_gop(event_id="NOPE")) == (None, els.R_NO_EVENT)
    assert t(_gop(event_id="LATE")) == (None, els.R_AFTER_WINDOW)
    assert t(_gop(market="player_points", player="x")) == (None, els.R_PROP_OUTCOME)
    t2, _ = _chip_truth(chips={"2026-11-09": [_chip(state="in")]})
    assert t2(_gop()) == (None, els.R_NOT_FINAL)
    t3, _ = _chip_truth(chips={"2026-11-09": [_chip(start_time_utc="2026-11-11T01:15:00+00:00")]})
    assert t3(_gop()) == (None, "no_chip_match")                                    # same teams, another day


def test_chips_never_read_after_the_last_slate():
    events = _events(EDGE={"sport": "nfl", "home": "Baltimore Ravens", "away": "Los Angeles Chargers",
                           "commence": "2026-11-15T02:00:00Z", "source": "decision_record"})   # Central 11-14 20:00
    t, calls = _chip_truth(events=events)
    t(_gop(event_id="EDGE"))
    assert calls and max(calls) <= "2026-11-14"


def test_truth_dispatch_routes_each_line(tmp_path):
    chip_t, _ = _chip_truth()
    t = els.Truth("outcome", basketball=_truth(tmp_path), chips=chip_t)
    assert t(_lop()) == (1.0, None)                                                  # live NBA: slice 1's scores
    assert t(_gop(phase="live", sport="nhl", event_id="NHL1", market="h2h", side="away", line=None)) == (1.0, None)
    assert t(_gop()) == (1.0, None)                                                  # pregame NFL: the chips
    assert t(_lop(market="player_points")) == (None, els.R_PROP_OUTCOME)


def _q(book, side, price, line=46.5, market="totals", at="2026-11-10T00:30:00Z", ev="EV1", player=None):
    return {"event_id": ev, "captured_at": at, "commence_time": START, "selection": side, "market": market,
            "segment": "full", "player_name": player, "line": line, "bookmaker": book, "price": price}


def _close_truth(quotes, events=None):
    reads = []

    def iter_quotes(sport, d):
        reads.append((sport, d))
        return iter(quotes if d == "2026-11-09" else [])

    t = els.CloseTruth(events or _events(), max_commence=els._dpp()._epoch("2026-11-15T06:00:00Z"),
                       last_date="2026-11-14", iter_quotes=iter_quotes)
    return t, reads


def test_close_truth_sharp_then_consensus_then_refused():
    quotes = [
        _q("pinnacle", "over", -125), _q("pinnacle", "under", 105),
        _q("pinnacle", "over", -300, at="2026-11-10T02:00:00Z"),             # after the start: never the close
        _q("draftkings", "home", -110, line=-6.5, market="spreads"), _q("draftkings", "away", -110, line=6.5,
                                                                        market="spreads"),
        _q("fanduel", "home", -120, line=-6.5, market="spreads"), _q("fanduel", "away", 100, line=6.5,
                                                                     market="spreads"),
        _q("draftkings", "over", -110, line=20.5, market="player_points", player="J Doe"),
        _q("draftkings", "under", -110, line=20.5, market="player_points", player="J Doe"),
    ]
    t, reads = _close_truth(quotes)
    ops = [("2026-11-09", dict(_gop(), line_key="k_tot")),
           ("2026-11-09", dict(_gop(market="spreads", side="away", line=6.5), line_key="k_spr")),
           ("2026-11-09", dict(_gop(market="player_points", player="J Doe", line=20.5), line_key="k_prop")),
           ("2026-11-09", dict(_gop(event_id="LATE"), line_key="k_late"))]
    assert t.prepare(ops) == 3
    y, why = t(dict(_gop(), line_key="k_tot"))
    assert why is None and 0.5 < y < 0.56 and t.basis["k_tot"] == "sharp"
    y, why = t(dict(_gop(market="spreads", side="away", line=6.5), line_key="k_spr"))
    assert why is None and 0.47 < y < 0.5 and t.basis["k_spr"] == "consensus"     # away the cheaper side
    y, why = t(dict(_gop(market="player_points"), line_key="k_prop"))
    assert y is None and why.startswith(els.R_NO_CLOSE)                            # one book: no close
    assert t(dict(_gop(event_id="LATE"), line_key="k_late")) == (None, els.R_AFTER_WINDOW)
    assert t(dict(_gop(phase="live"), line_key="k_tot")) == (None, els.R_PREGAME_ONLY)
    assert reads and all(d <= "2026-11-14" for _s, d in reads)
    assert list(t._quotes("nfl", "2026-11-15")) == []
    assert ("nfl", "2026-11-15") not in reads


def test_default_window_is_midnight_central_after_the_last_slate():
    from datetime import datetime, timezone

    assert datetime.fromtimestamp(els.default_max_commence("2026-11-14"), timezone.utc).isoformat() \
        == "2026-11-15T06:00:00+00:00"


# ----------------------------------------------------------------------------- slice 3a: NBA player props


def _brow(name, team, matchup, d="2026-11-10", pts=20, reb=8, ast=5, fg3m=2, stl=1, blk=0):
    return {"GAME_DATE": d, "TEAM_ABBREVIATION": team, "MATCHUP": matchup, "PLAYER_NAME": name, "PTS": str(pts),
            "REB": str(reb), "AST": str(ast), "FG3M": str(fg3m), "STL": str(stl), "BLK": "" if blk is None else str(blk)}


BOX_ROWS = [
    _brow("Zion Williamson", "NOP", "NOP vs. DEN", pts=27, reb=10, ast=4),
    _brow("Nikola Jokic", "DEN", "DEN @ NOP", pts=31, reb=14, ast=11, stl=2, blk=1),
    _brow("Herb Jones", "NOP", "NOP vs. DEN", pts=8, reb=5, ast=2, stl=3, blk=None),   # BLK missing in the box
    _brow("Alex Same", "NOP", "NOP vs. DEN"), _brow("Alex Same", "DEN", "DEN @ NOP"),  # one name on both teams
    _brow("Nikola Jokic", "DEN", "DEN @ NOP", d="2026-11-15", pts=0),                  # after the window
]
PROP_EVENTS = {
    "PG1": {"sport": "nba", "home": "New Orleans Pelicans", "away": "Denver Nuggets",
            "commence": "2026-11-11T01:00:00Z", "source": "decision_record"},          # Central 11-10 19:00
    "PGSW": {"sport": "nba", "home": "Denver Nuggets", "away": "New Orleans Pelicans",
             "commence": "2026-11-11T01:00:00Z", "source": "decision_record"},
    "PGLATE": {"sport": "nba", "home": "New Orleans Pelicans", "away": "Denver Nuggets",
               "commence": "2026-11-15T18:00:00Z", "source": "decision_record"},      # after the window
    "PG14": {"sport": "nba", "home": "New Orleans Pelicans", "away": "Denver Nuggets",
             "commence": "2026-11-15T01:00:00Z", "source": "decision_record"},         # Central 11-14: no box game
}
LIVE_GAMES = {"E1": ("2026-11-10", "NOP", "DEN"), "E9": ("2026-11-15", "NOP", "DEN")}


def _prop_truth(rows=BOX_ROWS):
    box = els.NbaBox(rows, first="2026-11-09", last="2026-11-14")
    return els.NbaPropTruth(box, PROP_EVENTS, LIVE_GAMES, max_commence=els._dpp()._epoch("2026-11-15T06:00:00Z"))


def _pop(**kw):
    base = {"phase": "live", "sport": "nba", "event_id": "E1", "market": "player_points", "segment": "full",
            "side": "over", "line": 25.5, "player": "Zion Williamson",
            "inputs": {"team_side": "home", "home_name": "New Orleans Pelicans", "away_name": "Denver Nuggets",
                       "actual_so_far": 10}}
    base.update(kw)
    return base


def test_prop_final_and_outcome_rules():
    stats = {"pts": 31, "reb": 14, "ast": 11, "threes": 2, "stl": 2, "blk": 1}
    assert els.prop_final("player_points_rebounds_assists", stats) == 56
    assert els.prop_final("player_rebounds_assists", stats) == 25
    assert els.prop_final("player_triple_double", stats) == 3          # pts, reb, ast at 10+
    assert els.prop_final("player_double_double", {**stats, "ast": 9}) == 2
    assert els.prop_final("player_blocks", {**stats, "blk": None}) is None   # missing, never read as 0
    assert els.prop_final("player_double_double", {**stats, "stl": None}) is None
    assert els.prop_final("player_turnovers", stats) is None
    assert els.prop_outcome("over", 25.5, 27) == 1.0 and els.prop_outcome("under", 25.5, 27) == 0.0
    assert els.prop_outcome("under", 9.5, 8) == 1.0
    assert els.prop_outcome("over", 27.0, 27) == 0.5
    assert els.prop_outcome("yes", 0.5, 1) == els.R_SIDE and els.prop_outcome("over", None, 1) == els.R_SIDE


def test_nba_box_reads_only_its_window_and_orients_by_matchup():
    box = els.NbaBox(BOX_ROWS, first="2026-11-09", last="2026-11-14")
    assert set(box.games) == {("2026-11-10", "NOP", "DEN")}                      # the 11-15 row is never kept
    assert box.rows == 5 and box.duplicates == 0
    assert box.game("2026-11-10", "DEN", "NOP") == ("2026-11-10", "NOP", "DEN")   # either orientation finds it
    assert box.game("2026-11-11", "NOP", "DEN") is None
    assert box.by_name[("2026-11-10", "NOP", "DEN")]["alex same"] == ["NOP", "DEN"]
    assert els.parse_matchup("NO @ DEN", "NOP") == ("DEN", "NOP")                 # ESPN's codes fold to nba_api's


def test_nba_props_grade_live_and_pregame_lines():
    t = _prop_truth()
    assert t(_pop()) == (1.0, None)                                               # 27 > 25.5
    assert t(_pop(player="Nikola Jokic", market="player_triple_double", line=2.5,
                  inputs={"team_side": "away", "home_name": "New Orleans Pelicans",
                          "away_name": "Denver Nuggets"})) == (1.0, None)
    pg = {"phase": "pregame", "sport": "nba", "event_id": "PG1", "market": "player_rebounds", "segment": "full",
          "side": "under", "line": 9.5, "player": "Nikola Jokic"}
    assert t(pg) == (0.0, None)                                                   # 14 rebounds: the under lost
    assert t({**pg, "event_id": "PGSW", "side": "over"}) == (1.0, None)           # the record names it the other way
    assert t({**pg, "player": "Herbert Jones", "market": "player_steals", "line": 2.5, "side": "over"}) == (1.0, None)


def test_nba_props_refusals_by_name():
    t = _prop_truth()
    assert t(_pop(line=27.0)) == (None, el.PUSH)
    assert t(_pop(inputs={**_pop()["inputs"], "actual_so_far": 26})) == (None, els.R_DECIDED)
    assert t(_pop(inputs={**_pop()["inputs"], "team_side": "away"})) == (None, els.R_TEAM_SIDE)
    assert t(_pop(player="Nobody Here")) == (None, els.R_NO_PLAYER)
    assert t(_pop(player="Alex Same", inputs={})) == (None, els.R_AMBIGUOUS_PLAYER)
    assert t(_pop(player="Herb Jones", market="player_blocks", line=0.5, inputs={})) == (None, els.R_STAT_MISSING)
    assert t(_pop(market="player_turnovers")) == (None, els.R_PROP_MARKET)
    assert t(_pop(event_id="E2")) == (None, els.R_NO_FINAL)                      # not in the linescores
    assert t(_pop(event_id="E9")) == (None, els.R_NO_BOX_GAME)                   # dated after the window
    pg = {"phase": "pregame", "sport": "nba", "market": "player_points", "side": "over", "line": 20.5,
          "player": "Zion Williamson"}
    assert t({**pg, "event_id": "PGLATE"}) == (None, els.R_AFTER_WINDOW)
    assert t({**pg, "event_id": "PG14"}) == (None, els.R_NO_BOX_GAME)
    assert t({**pg, "event_id": "NOPE"}) == (None, els.R_NO_EVENT)
    assert t(_pop(sport="nhl", market="GOALS")) == (None, els.R_PROP_OUTCOME)


def test_truth_dispatch_sends_nba_props_to_the_box(tmp_path):
    chip_t, _ = _chip_truth()
    t = els.Truth("outcome", basketball=_truth(tmp_path), chips=chip_t, props=_prop_truth())
    assert t(_pop()) == (1.0, None)
    assert t(_lop()) == (1.0, None)                                               # a game line is unaffected
    assert t(_gop(market="player_points", player="x")) == (None, els.R_PROP_OUTCOME)   # NFL props still owed


def test_basketball_truth_dates_a_game_by_its_first_linescores_file(tmp_path):
    root = _root(tmp_path)
    late = root / "nba_source" / "data" / "processed" / "linescores_2026-11-11.json"
    late.write_text(json.dumps({"date": "2026-11-11", "games": {
        "E1": {"home": "NO", "away": "DEN", "home_periods": [23, 28, 31, 26], "away_periods": [29, 27, 30, 30]},
        "E4": {"home": "BOS", "away": "MIA", "home_periods": [20, 20, 20, 20], "away_periods": [21, 21, 21, 21]},
    }}), encoding="utf-8")
    t = els.BasketballTruth(["2026-11-10", "2026-11-11"], root=root, evidence_teams=TEAMS)
    assert t.nba_date["E1"] == "2026-11-10" and t.nba_date["E4"] == "2026-11-11"
