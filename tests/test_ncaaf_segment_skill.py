"""NCAAF quarter/half skill grade (lane ncaaf-segment-skill, todo #805).

Covers what `scripts/ncaaf_segment_skill.py` adds to the #752 method it imports: the
production bridge (OddsAPI names -> the week CSV's ESPN game id -> that week's sidecar
block), the as-of rule (a sidecar written at or after kickoff is refused), the box
lookup by ESPN event id, count-only mode reading no outcome, the registered
`established_loss_rel` rule, and a planted-edge positive control plus a null.
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import ncaaf_segment_skill as G  # noqa: E402

START = "2026-11-07T20:00:00Z"
SEG = {"total_points_dist": {"3": 30, "7": 40, "14": 30}, "margin_dist": {"-7": 30, "0": 20, "7": 50},
       "home_points_mean": 5.0, "away_points_mean": 3.0}


def _q(book, sel, line, price, *, market="totals", segment="q1", start=START, event="e1",
       cap="2026-11-07T19:00:00Z", home="Ohio State Buckeyes", away="Michigan Wolverines"):
    return {"kind": "game", "event_id": event, "segment": segment, "market": market, "bookmaker": book,
            "captured_at": cap, "commence_time": start, "selection": sel, "line": line, "price": price,
            "home_team": home, "away_team": away}


def _week(tmp_path, *, week=11, generated_at="2026-11-07T16:30:00+00:00", game_id="401999001",
          home="Ohio State", away="Michigan"):
    csv_path = tmp_path / f"smartsim2_projections_2026_wk{week}.csv"
    csv_path.write_text(f"game_id,season,week,home_team,away_team\n{game_id},2026,{week},{home},{away}\n",
                        encoding="utf-8")
    payload = {"generated_at": generated_at, "games": {game_id: {"sims": 100, "segments": {"q1": SEG, "full": SEG}}}}
    (tmp_path / f"smartsim2_segment_distributions_2026_wk{week}.json").write_text(json.dumps(payload),
                                                                                    encoding="utf-8")


def _box(home=(7, 0, 3, 3), away=(7, 3, 10, 3), *, date=START, final=True):
    return {"date": date, "home": list(home), "away": list(away), "final": final}


def _totals_pair(**kw):
    return [_q("a", "over", 9.5, -110, **kw), _q("a", "under", 9.5, -110, **kw)]


# ---------------------------------------------------------------- bridge ----
def test_the_bridge_is_productions_name_join_and_prices_with_its_arithmetic(tmp_path):
    from syndicate.features.ncaaf.segment_projections import probability_above

    _week(tmp_path)
    weeks = G.load_weeks(tmp_path)
    consensus = G.consensus_markets(_totals_pair())
    obs, refused, eligible = G.build_observations(consensus, weeks, {"401999001": _box()})
    assert refused == {}
    (only,) = obs
    assert only["espn_id"] == "401999001" and only["y"] == 1  # q1 7-7 = 14 > 9.5
    assert only["p_model"] == pytest.approx(probability_above(SEG["total_points_dist"], 9.5)[0])
    assert only["p_market"] == pytest.approx(0.5)
    assert len(eligible) == 1


def test_a_sidecar_written_at_or_after_kickoff_is_refused(tmp_path):
    _week(tmp_path, generated_at="2026-11-07T20:00:00+00:00")  # == kickoff
    weeks = G.load_weeks(tmp_path)
    obs, refused, _ = G.build_observations(G.consensus_markets(_totals_pair()), weeks, {"401999001": _box()})
    assert obs == [] and refused == {"sidecar_written_after_kickoff": 1}


def test_a_week_is_chosen_by_the_espn_event_date_not_the_pair_alone(tmp_path):
    # The same pairing in two weeks (a rematch): only the event dated near kickoff counts.
    _week(tmp_path, week=5, game_id="401999000", generated_at="2026-10-03T16:00:00+00:00")
    _week(tmp_path, week=11)
    weeks = G.load_weeks(tmp_path)
    boxes = {"401999000": _box(date="2026-10-03T20:00:00Z"), "401999001": _box()}
    obs, refused, _ = G.build_observations(G.consensus_markets(_totals_pair()), weeks, boxes)
    assert refused == {} and obs[0]["espn_id"] == "401999001" and obs[0]["sim_week"] == 11


@pytest.mark.parametrize("boxes, reason", [
    ({}, "no_espn_event_near_kickoff"),
    ({"401999001": _box(date="2026-11-10T20:00:00Z")}, "no_espn_event_near_kickoff"),
    ({"401999001": _box(final=False)}, "no_final_box"),
])
def test_refusals_are_named(tmp_path, boxes, reason):
    _week(tmp_path)
    obs, refused, _ = G.build_observations(G.consensus_markets(_totals_pair()), G.load_weeks(tmp_path), boxes)
    assert obs == [] and refused == {reason: 1}


def test_an_unknown_pairing_is_refused_not_guessed(tmp_path):
    _week(tmp_path)
    quotes = _totals_pair(home="Alabama Crimson Tide", away="Auburn Tigers")
    obs, refused, _ = G.build_observations(G.consensus_markets(quotes), G.load_weeks(tmp_path), {"401999001": _box()})
    assert obs == [] and refused == {"no_projection_pair": 1}


def test_count_only_reads_no_outcome(tmp_path):
    # A box with NO linescores would refuse `no_segment_score` if any outcome were read.
    _week(tmp_path)
    box = {"date": START, "home": None, "away": None, "final": True}
    obs, refused, eligible = G.build_observations(
        G.consensus_markets(_totals_pair()), G.load_weeks(tmp_path), {"401999001": box}, count_only=True)
    assert obs == [] and refused == {} and len(eligible) == 1
    obs, refused, _ = G.build_observations(G.consensus_markets(_totals_pair()), G.load_weeks(tmp_path),
                                           {"401999001": box})
    assert refused == {"no_segment_score": 1}


# ---------------------------------------------------------- registered rule ----
def test_established_loss_rel_is_the_ci_lower_bound_over_the_market_brier():
    assert G.established_loss_rel({"ci95": [0.002, 0.02], "brier_market": 0.25}) == pytest.approx(0.008)
    assert G.established_loss_rel({"ci95": [-0.001, 0.02], "brier_market": 0.25}) == 0.0
    assert G.established_loss_rel({"ci95": [0.0, 0.02], "brier_market": 0.25}) == 0.0
    assert G.established_loss_rel({}) == 0.0


def _synthetic(model_noise: float, *, games=120, seed=1):
    rng = random.Random(seed)
    obs = []
    for g in range(games):
        for seg in ("h1", "q1", "q2"):
            truth = rng.uniform(0.25, 0.75)
            y = int(rng.random() < truth)
            market = min(max(truth + rng.gauss(0, 0.12), 0.02), 0.98)
            model = min(max(truth + rng.gauss(0, model_noise), 0.02), 0.98)
            obs.append({"game": f"g{g}", "segment": seg, "market": "totals", "y": y,
                        "p_model": model, "p_market": market})
    return obs


def test_a_planted_edge_is_found():
    # The model sees the truth almost exactly; the market is noisy: the grade must say so.
    fam = G.grade(_synthetic(0.01), reps=400, seed=804)["families"]["totals"]
    assert fam["verdict_class"] == "beats_market" and fam["ci95"][1] < 0


def test_a_worse_model_is_found_losing_and_earns_a_loss_rel():
    fam = G.grade(_synthetic(0.25), reps=400, seed=804)["families"]["totals"]
    assert fam["verdict_class"] == "loses_to_market"
    assert G.established_loss_rel(fam) > 0


def test_books_against_books_is_parity():
    # The model is a second book with the market's own noise, independent of it.
    fam = G.grade(_synthetic(0.12, seed=7), reps=400, seed=804)["families"]["totals"]
    assert fam["verdict_class"] == "parity" and fam["ci95"][0] < 0 < fam["ci95"][1]


# -------------------------------------------------------------- registry ----
from syndicate.features.shared import measured_market_skill as mms  # noqa: E402
from syndicate.features.shared.projection_skill import attach_projection_skill  # noqa: E402

SEGMENTS = ("h1", "h2", "q1", "q2", "q3", "q4")


@pytest.mark.parametrize("market", ["totals", "spreads", "h2h"])
@pytest.mark.parametrize("segment", SEGMENTS)
def test_every_ncaaf_segment_market_has_a_pregame_note_and_no_live_one(market, segment):
    note = mms.skill_note(sport="ncaaf", market=market, segment=segment, phase=mms.PHASE_PREGAME)
    assert note and note["basis"] == mms.NOTE_BASIS and note["sample_games"] == 161
    assert mms.skill_note(sport="ncaaf", market=market, segment=segment, phase=mms.PHASE_LIVE) is None


def test_the_registered_rule_sets_the_rank_weights():
    weight = {m: mms.skill_reliability(dict(mms.skill_note(sport="ncaaf", market=m, segment="q2",
                                                           phase=mms.PHASE_PREGAME), status="measured"))
              for m in ("totals", "spreads", "h2h")}
    assert weight["totals"] == pytest.approx(1 - mms.SKILL_GAIN * 0.01152 / 0.24949, abs=1e-4)  # ~0.769
    assert weight["spreads"] == pytest.approx(1 - mms.SKILL_GAIN * 0.00096 / 0.24802, abs=1e-4)  # ~0.981
    assert weight["h2h"] == 1.0  # parity: nothing established


def _ncaaf_grid(monkeypatch):
    from syndicate.features.ncaaf import segment_projections as sp
    from syndicate.features.ncaaf.game_projections import _norm

    monkeypatch.setattr("syndicate.features.ncaaf.oddsapi_lines.resolve_team", lambda n: n)
    base = {"kind": "game", "home_team": "Kentucky Wildcats", "away_team": "South Alabama Jaguars",
            "commence_time": "2099-01-01T18:00:00Z"}
    rows = [dict(base, market="totals", segment="q1", line=9.5), dict(base, market="spreads", segment="h1", line=1.5),
            dict(base, market="h2h", segment="q2", line=None)]
    sp.attach_ncaaf_segment_projections(
        rows, blocks={"gid1": {"sims": 100, "segments": {"q1": SEG, "h1": SEG, "q2": SEG}}},
        game_id_by_pair={(_norm("Kentucky Wildcats"), _norm("South Alabama Jaguars")): "gid1"},
        selected_date="2099-01-01")
    return rows


def test_segment_rows_reach_the_registry_and_totals_rank_below_full_weight(monkeypatch):
    # off != on: the old producer note ({"state": "measured_loss"}) scored 1.0 on every row.
    old_note = {"state": "measured_loss", "note": "game level", "status": "measured"}
    assert mms.skill_reliability(old_note) == 1.0
    rows = _ncaaf_grid(monkeypatch)
    probs = [r["projection"]["model_prob_over"] for r in rows]
    assert all("model_skill" not in r["projection"] for r in rows)
    coverage = attach_projection_skill(rows, sport="ncaaf")
    assert coverage["rows_with_measured_skill_from_registry"] == 3
    total, spread, h2h = (r["projection"]["model_skill"] for r in rows)
    assert total["verdict_class"] == spread["verdict_class"] == mms.VERDICT_LOSES
    assert h2h["verdict_class"] == mms.VERDICT_PARITY
    assert mms.skill_reliability(total) < 0.8 < mms.skill_reliability(spread) < 1.0 == mms.skill_reliability(h2h)
    assert [r["projection"]["model_prob_over"] for r in rows] == probs  # pricing untouched
