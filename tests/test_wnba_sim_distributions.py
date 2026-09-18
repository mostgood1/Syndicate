"""The WNBA smart sim's own draws, published and priced -- lane wnba-sim-distributions, 2026-09-18.

Measured on Layer 2 2026-09-18 21:55Z: 437 of 562 WNBA game rows could not be
priced ("sim priced only its own market line; this is an alternate line the
sim's 3-point quantile summary cannot answer"), 101 half/quarter rows had no
projection, and 58 combo props shipped a mean only. The sim draws every one of
those distributions and throws them away. These tests pin, in order:

  1. the recorder is a pure pass-through that keeps every draw;
  2. the histograms reproduce the sim's own P(total > line) exactly, and `full`
     adds overtime;
  3. combo ladders equal the ladder of the summed draws, and existing ladders
     are never overwritten;
  4. REACHABILITY: through the real `_call_source_simulate_smart_game_local`,
     with a stand-in vendor module, the result gains `score.dist` (off != on);
  5. the Layer 2 join prices an alternate line and a quarter from the
     histograms, refuses a certainty with a reason, and is unchanged without one;
  6. `cards_sim_detail` carries `score_dist` to the board.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import syndicate.features.shared.basketball_props_smart_sim as smart_sim
from syndicate.features.shared import wnba_game_projections as wgp

REPO_ROOT = Path(__file__).resolve().parents[1]


def _draw(hq, aq, *, hot=(), aot=(), home=None, away=None):
    h_box = {"ot_pts": list(hot), "players": [{"player_name": n, "pts": s[0], "reb": s[1], "ast": s[2]} for n, s in (home or {}).items()]}
    a_box = {"ot_pts": list(aot), "players": [{"player_name": n, "pts": s[0], "reb": s[1], "ast": s[2]} for n, s in (away or {}).items()]}
    return h_box, a_box, list(hq), list(aq)


DRAWS = [
    _draw([20, 21, 19, 22], [18, 20, 21, 20], home={"A Guard": (18, 4, 6)}, away={"B Wing": (12, 7, 2)}),
    _draw([22, 18, 20, 20], [21, 19, 20, 20], hot=(9,), aot=(7,), home={"A Guard": (25, 3, 8)}, away={"B Wing": (9, 9, 3)}),
    _draw([19, 20, 22, 18], [20, 22, 19, 21], home={"A Guard": (14, 5, 4)}, away={"B Wing": (15, 6, 1)}),
    _draw([24, 20, 18, 21], [17, 18, 20, 19], home={"A Guard": (21, 2, 7)}, away={"B Wing": (11, 8, 4)}),
]


def _recorded(draws):
    recorded: list = []
    wrapped = smart_sim._recording_sim_draws_local(lambda **kw: draws[kw["i"]], recorded)
    outs = [wrapped(i=i) for i in range(len(draws))]
    return recorded, outs


# 1. ---------------------------------------------------------------------------


def test_the_recorder_passes_every_draw_through_unchanged_and_keeps_each_one():
    recorded, outs = _recorded(DRAWS)
    assert outs == DRAWS
    assert len(recorded) == len(DRAWS)
    assert recorded[1]["hot"] == [9] and recorded[1]["aot"] == [7]
    assert recorded[0]["home"]["A Guard"] == (18, 4, 6)


def test_a_draw_the_recorder_cannot_read_is_skipped_not_raised():
    recorded: list = []
    wrapped = smart_sim._recording_sim_draws_local(lambda **kw: "not a 4-tuple", recorded)
    assert wrapped() == "not a 4-tuple"
    assert recorded == []


# 2. ---------------------------------------------------------------------------


def _prob_over(hist, line):
    n = sum(hist.values())
    return sum(c for v, c in hist.items() if int(v) > line) / n


def test_histograms_reproduce_the_sims_own_probability_and_full_adds_overtime():
    recorded, _ = _recorded(DRAWS)
    out = {"score": {"p_total_over": None}, "players": {}}
    smart_sim._attach_sim_distributions_local(out, recorded)
    dist = out["score"]["dist"]
    assert dist["n"] == 4 and dist["margin_frame"] == "home_minus_away"

    reg_totals = [sum(d[2]) + sum(d[3]) for d in DRAWS]
    reg = dist["segments"]["regulation"]["total"]
    for line in (155.5, 160.5, 163.5):
        # The vendor's own p_total_over is mean(regulation total > line).
        assert _prob_over(reg, line) == sum(t > line for t in reg_totals) / 4

    full = dist["segments"]["full"]["total"]
    assert sum(int(v) * c for v, c in full.items()) == sum(reg_totals) + 9 + 7

    q1 = dist["segments"]["q1"]["margin"]
    assert sorted(int(v) for v, c in q1.items() for _ in range(c)) == sorted(d[2][0] - d[3][0] for d in DRAWS)
    h2 = dist["segments"]["h2"]["total"]
    assert sum(h2.values()) == 4


def test_no_draws_leaves_the_result_exactly_as_the_sim_wrote_it():
    out = {"score": {"p_total_over": 0.51}, "players": {"home": [{"player_name": "A Guard", "prop_ladders": {}}]}}
    before = json.dumps(out, sort_keys=True)
    smart_sim._attach_sim_distributions_local(out, [])
    assert json.dumps(out, sort_keys=True) == before


# 3. ---------------------------------------------------------------------------


def _ladder(values):
    return {"simCount": len(values), "values": sorted(values)}


def test_combo_ladders_are_the_ladder_of_the_summed_draws_and_never_overwrite():
    recorded, _ = _recorded(DRAWS)
    existing_pr = {"simCount": 99, "values": ["kept"]}
    out = {
        "score": {},
        "players": {
            "home": [{"player_name": "A Guard", "prop_ladders": {"pra": {"x": 1}, "pr": existing_pr}}],
            "away": [{"player_name": "B Wing"}],
        },
    }
    smart_sim._attach_sim_distributions_local(out, recorded, build_ladder=_ladder)
    home = out["players"]["home"][0]["prop_ladders"]
    away = out["players"]["away"][0]["prop_ladders"]
    assert home["pr"] is existing_pr, "an existing ladder must never be overwritten"
    assert home["pa"]["values"] == sorted([18 + 6, 25 + 8, 14 + 4, 21 + 7])
    assert home["ra"]["values"] == sorted([4 + 6, 3 + 8, 5 + 4, 2 + 7])
    assert away["pr"]["values"] == sorted([12 + 7, 9 + 9, 15 + 6, 11 + 8])


# 4. ---------------------------------------------------------------------------


def test_reachability_through_the_real_wrapper_off_is_not_on(monkeypatch, tmp_path):
    """The stand-in vendor module calls its module-level
    `simulate_pbp_game_boxscore` per draw, as the real one does. Inside
    `_call_source_simulate_smart_game_local` that name is Syndicate's recorder."""
    draws = iter(DRAWS)
    monkeypatch.setattr(smart_sim, "_simulate_pbp_game_boxscore_local", lambda **kw: next(draws))

    module = SimpleNamespace(build_exact_ladder_payload=_ladder)

    def simulate_smart_game(n_sims):
        for _ in range(n_sims):
            module.simulate_pbp_game_boxscore(rng=None)
        return {"score": {"p_total_over": 0.5}, "players": {"home": [{"player_name": "A Guard"}], "away": []}}

    module.simulate_smart_game = simulate_smart_game

    # OFF: the vendor sim called directly never reaches the recorder.
    module.simulate_pbp_game_boxscore = lambda **kw: DRAWS[0]
    direct = module.simulate_smart_game(n_sims=4)
    assert "dist" not in direct["score"]

    # ON: through the wrapper.
    out = smart_sim._call_source_simulate_smart_game_local(
        smart_sim_module=module, processed_root=tmp_path / "data" / "processed", league_code="wnba", kwargs={"n_sims": 4}
    )
    assert out["score"]["dist"]["n"] == 4
    assert "pa" in out["players"]["home"][0]["prop_ladders"]
    # The wrapper restores the module's own attribute afterwards.
    assert module.simulate_pbp_game_boxscore(rng=None) == DRAWS[0]


# 5. ---------------------------------------------------------------------------


def _hist(values):
    out: dict[str, int] = {}
    for v in values:
        out[str(v)] = out.get(str(v), 0) + 1
    return out


TOTALS = [150, 155, 158, 160, 162, 163, 165, 168, 170, 175]
MARGINS = [-12, -6, -3, -1, 0, 2, 4, 5, 9, 14]
DIST = {
    "n": 10,
    "segments": {
        "full": {"total": _hist(TOTALS), "margin": _hist(MARGINS)},
        "q1": {"total": _hist([36, 38, 40, 41, 42, 42, 44, 45, 47, 50]), "margin": _hist([-5, -3, -1, 0, 0, 1, 2, 3, 4, 6])},
    },
}


def _index(with_dist=True):
    entry = {"pred_margin": 1.2, "pred_total": 162.6, "p_home_win": 0.55, "p_home_cover": 0.52,
             "p_total_over": 0.5, "sim_market_home_spread": -1.5, "sim_market_total": 162.5}
    if with_dist:
        entry["dist"] = DIST
    index = wgp.WnbaGameProjectionIndex()
    index.by_teams[("home team", "away team")] = entry
    index.by_tri[("hom", "awy")] = entry
    index.games = 1
    index.games_with_dist = 1 if with_dist else 0
    return index


def _row(market, line=None, segment="full"):
    return {"kind": "game", "market": market, "line": line, "segment": segment,
            "home_team": "Home Team", "away_team": "Away Team", "side": "over"}


def test_an_alternate_total_is_priced_from_the_full_histogram():
    row = _row("totals_alt", 158.5)
    coverage = wgp.attach_wnba_game_projections([row], _index())
    proj = row["projection"]
    assert proj["model_prob_over"] == pytest.approx(7 / 10)
    assert proj["basis"] == "sim_total_dist/full"
    assert "probability_unavailable_reason" not in proj
    assert coverage["rows_priced_from_sim_distribution"] == 1


def test_a_spread_is_home_covers_in_the_away_frame():
    row = _row("spreads_alt", 3.5)  # away-frame line: home covers iff margin > 3.5
    wgp.attach_wnba_game_projections([row], _index())
    assert row["projection"]["model_prob_over"] == pytest.approx(4 / 10)
    assert row["projection"]["side"] == "Home Team"


def test_a_quarter_total_is_priced_from_its_own_segment_not_the_full_game():
    row = _row("totals", 41.5, segment="q1")
    coverage = wgp.attach_wnba_game_projections([row], _index())
    assert row["projection"]["model_prob_over"] == pytest.approx(6 / 10)
    assert row["projection"]["basis"] == "sim_total_dist/q1"
    assert coverage["period_rows_priced"] == 1 and coverage["non_full_segment_rows"] == 0


def test_a_period_without_its_own_histogram_is_still_skipped():
    row = _row("totals", 81.5, segment="h1")
    coverage = wgp.attach_wnba_game_projections([row], _index())
    assert "projection" not in row
    assert coverage["non_full_segment_rows"] == 1


def test_a_period_moneyline_is_home_wins_given_no_tie_with_the_edge_withheld():
    row = _row("h2h", None, segment="q1")
    wgp.attach_wnba_game_projections([row], _index())
    proj = row["projection"]
    assert proj["model_prob_over"] == pytest.approx(5 / 8)  # 5 wins, 3 losses, 2 ties
    assert proj["edge_vs_market_pct"] is None and proj["edge_unavailable_reason"]


def test_a_line_every_draw_clears_is_refused_with_a_reason_not_clamped():
    row = _row("totals_alt", 140.5)
    wgp.attach_wnba_game_projections([row], _index())
    proj = row["projection"]
    assert proj.get("model_prob_over") is None
    assert "draws fell on one side" in proj["probability_unavailable_reason"]


def test_without_a_histogram_an_alternate_line_keeps_todays_reason():
    row = _row("totals_alt", 158.5)
    coverage = wgp.attach_wnba_game_projections([row], _index(with_dist=False))
    assert row["projection"]["model_prob_over"] is None
    assert "3-point quantile summary cannot answer" in row["projection"]["probability_unavailable_reason"]
    assert coverage["rows_priced_from_sim_distribution"] == 0


def test_the_loader_joins_score_dist_by_tri_code(monkeypatch, tmp_path):
    import syndicate.features.wnba.cards as cards
    import syndicate.features.wnba.sources as sources

    path = tmp_path / "cards_sim_detail_2026-09-18.json"
    path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(sources, "processed_path", lambda name: path)
    monkeypatch.setattr(cards, "_artifact_games_index", lambda p: {
        "g1": {"home_tri": "HOM", "away_tri": "AWY", "sim": {"score_dist": DIST}},
        "g2": {"home_tri": "XXX", "away_tri": "YYY", "sim": {"score_dist": DIST}},
    })
    index = _index(with_dist=False)
    wgp._attach_sim_distributions(index, "2026-09-18")
    assert index.by_tri[("hom", "awy")]["dist"] is DIST
    assert index.games_with_dist == 1


# 6. ---------------------------------------------------------------------------


def _load_producer():
    spec = importlib.util.spec_from_file_location("_producer_wnba_dist", REPO_ROOT / "scripts" / "refresh_wnba_oddsapi_props.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_cards_sim_detail_carries_score_dist_to_the_board(tmp_path):
    producer = _load_producer()
    (tmp_path / "smart_sim_2026-09-18_HOM_AWY.json").write_text(json.dumps({
        "home": "HOM", "away": "AWY", "score": {"p_total_over": 0.5, "dist": DIST},
        "players": {"home": [], "away": []},
    }), encoding="utf-8")
    (tmp_path / "smart_sim_2026-09-18_OLD_ONE.json").write_text(json.dumps({
        "home": "OLD", "away": "ONE", "score": {"p_total_over": 0.5}, "players": {"home": [], "away": []},
    }), encoding="utf-8")
    games = {(g["home_tri"], g["away_tri"]): g for g in producer._build_cards_sim_detail_from_local_smart_sim(processed_root=tmp_path, date_str="2026-09-18")}
    assert games[("HOM", "AWY")]["sim"]["score_dist"] == DIST
    assert games[("OLD", "ONE")]["sim"]["score_dist"] is None
