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

@pytest.fixture(autouse=True)
def _fresh_team_registry():
    """The bridge resolves names through `oddsapi_lines`' `lru_cache`d registry. A test
    elsewhere that points SYNDICATE_NCAAF_SOURCE_ROOT at an empty tmp dir leaves an EMPTY
    map cached (measured: `test_ncaaf_live_resim_wiring.py` first, then every bridge test
    here refused `team_unresolved`), so each test starts from the real registry."""
    from syndicate.features.ncaaf import oddsapi_lines

    caches = (oddsapi_lines._alias_map, oddsapi_lines._mascot_tails, oddsapi_lines.fbs_canonical_names)
    for cached in caches:
        cached.cache_clear()
    yield
    for cached in caches:
        cached.cache_clear()


START = "2026-11-07T20:00:00Z"
SEG = {"total_points_dist": {"3": 30, "7": 40, "14": 30}, "margin_dist": {"-7": 30, "0": 20, "7": 50},
       "home_points_mean": 5.0, "away_points_mean": 3.0}


def _q(book, sel, line, price, *, market="totals", segment="q1", start=START, event="e1",
       cap="2026-11-07T19:00:00Z", home="Ohio State Buckeyes", away="Michigan Wolverines"):
    return {"kind": "game", "event_id": event, "segment": segment, "market": market, "bookmaker": book,
            "captured_at": cap, "commence_time": start, "selection": sel, "line": line, "price": price,
            "home_team": home, "away_team": away}


def _week(tmp_path, *, week=11, generated_at="2026-11-07T16:30:00+00:00", game_id="401999001",
          home="Ohio State", away="Michigan", seg=SEG):
    tmp_path.mkdir(parents=True, exist_ok=True)
    csv_path = tmp_path / f"smartsim2_projections_2026_wk{week}.csv"
    csv_path.write_text(f"game_id,season,week,home_team,away_team\n{game_id},2026,{week},{home},{away}\n",
                        encoding="utf-8")
    payload = {"generated_at": generated_at, "games": {game_id: {"sims": 100, "segments": {"q1": seg, "full": seg}}}}
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


# ------------------------------------------------- kept dated writes (#807) ----
SEG_TUE = {**SEG, "total_points_dist": {"3": 80, "14": 20}}  # P(q1 total > 9.5) = 0.2
SEG_WED = {**SEG, "total_points_dist": {"3": 40, "14": 60}}  # 0.6
SEG_SAT = {**SEG, "total_points_dist": {"3": 10, "14": 90}}  # 0.9, written AFTER kickoff


def _history(tmp_path):
    """Tue + Wed writes kept; the current (Sat) file was rewritten after the 20:00Z kickoff."""
    from syndicate.features.shared.football_segment_distributions import archive_sim_write

    history = tmp_path / "history"
    for name, gen, seg in (("tue", "2026-11-03T16:00:00+00:00", SEG_TUE), ("wed", "2026-11-04T16:00:00+00:00", SEG_WED)):
        _week(tmp_path / name, generated_at=gen, seg=seg)
        assert archive_sim_write(projections_csv=tmp_path / name / "smartsim2_projections_2026_wk11.csv",
                                 sidecar=tmp_path / name / "smartsim2_segment_distributions_2026_wk11.json",
                                 season=2026, week=11, history_dir=history) is not None
    _week(tmp_path / "current", generated_at="2026-11-07T21:00:00+00:00", seg=SEG_SAT)
    return tmp_path / "current", history


def test_with_kept_writes_a_game_is_priced_off_its_last_write_before_kickoff(tmp_path):
    current, history = _history(tmp_path)
    consensus = G.consensus_markets(_totals_pair())
    boxes = {"401999001": _box()}

    obs, refused, _ = G.build_observations(consensus, G.load_weeks(current), boxes)
    assert obs == [] and refused == {"sidecar_written_after_kickoff": 1}  # the #805 refusal

    obs, refused, _ = G.build_observations(consensus, G.load_weeks(current, history), boxes)
    assert refused == {}
    (only,) = obs
    assert only["sidecar_generated_at"] == "2026-11-04T16:00:00+00:00"  # Wed, not Tue, not Sat
    assert only["p_model"] == pytest.approx(0.6)


def test_kept_writes_ride_along_only_with_the_archive(tmp_path):
    current, history = _history(tmp_path)
    assert "writes" not in G.load_weeks(current)[(2026, 11)]
    slot = G.load_weeks(current, history)[(2026, 11)]
    assert [w["generated_at"] for w in slot["writes"]] == [
        "2026-11-03T16:00:00+00:00", "2026-11-04T16:00:00+00:00", "2026-11-07T21:00:00+00:00"]
    assert slot["generated_at"] == "2026-11-07T21:00:00+00:00"  # the current file is still the current file


def test_half_a_kept_write_is_ignored(tmp_path):
    # The sidecar is renamed into place second, so a sidecar without its CSV is a stray.
    current, history = _history(tmp_path)
    (history / "smartsim2_projections_2026_wk11.20261104T160000Z.csv.gz").unlink()
    obs, _, _ = G.build_observations(G.consensus_markets(_totals_pair()), G.load_weeks(current, history),
                                     {"401999001": _box()})
    assert obs[0]["sidecar_generated_at"] == "2026-11-03T16:00:00+00:00"


def test_the_engine_read_uses_the_kept_write_too(tmp_path):
    current, history = _history(tmp_path)
    boxes = {"401999001": _box()}
    assert G.engine_read(G.load_weeks(current), boxes, reps=50, seed=1)["games"] == 0
    read = G.engine_read(G.load_weeks(current, history), boxes, reps=50, seed=1)
    assert read["games"] == 1
    assert read["q1"]["sim_total_mean"] == pytest.approx(8.0)  # SEG's means, from the Wed block


def test_a_game_only_an_earlier_write_held_is_still_bridged(tmp_path):
    # A game dropped from the current CSV (e.g. moved off the slate) keeps its kept pair.
    current, history = _history(tmp_path)
    _week(current, generated_at="2026-11-07T21:00:00+00:00", game_id="401999777", home="Texas", away="Baylor")
    obs, refused, _ = G.build_observations(G.consensus_markets(_totals_pair()), G.load_weeks(current, history),
                                           {"401999001": _box()})
    assert refused == {} and obs[0]["espn_id"] == "401999001"


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
