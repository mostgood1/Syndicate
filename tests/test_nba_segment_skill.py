"""`scripts/nba_segment_skill.py` (todo #818): the bridge, the as-of refusal, and `--count-only` reading no box."""

from __future__ import annotations

import gzip
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts import nba_segment_skill as skill

TIP = "2026-11-13T01:10:00Z"
DIST = {
    "n": 100,
    "margin_frame": "home_minus_away",
    "segments": {
        "q1": {"total": {"50": 30, "56": 70}, "margin": {"-2": 40, "0": 10, "3": 50}},
        "h1": {"total": {"110": 45, "116": 55}, "margin": {"-4": 35, "5": 65}},
    },
}


def _epoch(text: str) -> float:
    return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()


@pytest.fixture
def nba_root(tmp_path, monkeypatch):
    root = tmp_path / "nba_source"
    processed = root / "data" / "processed"
    (processed / "_espn_cache" / "nba").mkdir(parents=True)
    # monkeypatch owns both keys, so the grader's own os.environ writes are undone at teardown.
    monkeypatch.setenv("SYNDICATE_NBA_SOURCE_ROOT", str(root))
    monkeypatch.setenv("SYNDICATE_DATA_ROOT", str(tmp_path))
    (processed / "game_cards_2026-11-12.csv").write_text(
        "date,game_id,home_team,visitor_team,commence_time,home_tri,away_tri,pred_margin,pred_total\n"
        f"2026-11-12,401909978,Minnesota Timberwolves,Dallas Mavericks,{TIP},MIN,DAL,8.19,232.83\n",
        encoding="utf-8",
    )
    sim = processed / "smart_sim_2026-11-12_MIN_DAL.json"
    sim.write_text(json.dumps({"game_id": "401909978", "score": {"p_home_win": 0.6, "dist": DIST},
                               "market_anchor": {"model_margin_raw": 0.0}}), encoding="utf-8")
    written = _epoch("2026-11-13T00:19:00Z")
    os.utime(sim, (written, written))
    (processed / "_espn_cache" / "nba" / "scoreboard_20261112.json").write_text(
        json.dumps({"events": [{"season": {"type": 2}}]}), encoding="utf-8")
    return root


def _consensus(line=52.5, market="totals"):
    return {"home_team": "Minnesota Timberwolves", "away_team": "Dallas Mavericks", "commence_time": TIP,
            "line": line, "market_prob": 0.5, "books_at_line": 2, "books": 2}


def test_bridge_finds_production_entry_and_prices_the_raw_sim(nba_root):
    from syndicate.features.shared.wnba_game_projections import _projection_from_dist

    bridge = skill.Bridge(skill.use_nba_root(nba_root))
    why, found = bridge.find(_consensus())
    assert why is None
    assert found["entry"].home_tri == "MIN" and found["central_date"] == "2026-11-12"
    assert found["minutes_before_tip"] == pytest.approx(51.0)
    why, p = skill.raw_model_prob(_consensus(), "q1", "totals", found["entry"])
    assert why is None and p == pytest.approx(0.70)
    # The exact production number, BEFORE served_game_probability.
    direct = _projection_from_dist({"line": 52.5}, "totals", DIST["segments"]["q1"], segment="q1", sims=100)
    assert p == direct["model_prob_over"]
    # Spreads in the away frame: home covers when margin > line; a whole-number line keeps the push mass
    # in the denominator (production's convention): P(margin > 0) = 50/100.
    assert skill.raw_model_prob(_consensus(line=0.0), "q1", "spreads", found["entry"])[1] == pytest.approx(0.50)
    # h2h: P(home wins | no tie) = 50 / (50 + 40).
    assert skill.raw_model_prob(_consensus(line=0.0), "q1", "h2h", found["entry"])[1] == pytest.approx(0.5556)
    assert skill.raw_model_prob(_consensus(), "q3", "totals", found["entry"])[0] == "no_segment_block"


def test_sim_written_at_or_after_tip_is_refused(nba_root):
    sim = nba_root / "data" / "processed" / "smart_sim_2026-11-12_MIN_DAL.json"
    bridge = skill.Bridge(skill.use_nba_root(nba_root))
    for stamp in (TIP, "2026-11-13T03:00:00Z"):
        os.utime(sim, (_epoch(stamp), _epoch(stamp)))
        assert bridge.find(_consensus()) == ("sim_written_after_tip", {})


def test_phase_and_window_refusals(nba_root):
    bridge = skill.Bridge(skill.use_nba_root(nba_root))
    assert bridge.find({**_consensus(), "commence_time": "2026-11-16T12:00:00Z"})[0] == "outside_window"
    board = nba_root / "data" / "processed" / "_espn_cache" / "nba" / "scoreboard_20261112.json"
    board.write_text(json.dumps({"events": [{"season": {"type": 1}}]}), encoding="utf-8")
    os.utime(board, (_epoch("2026-11-12T10:00:00Z"),) * 2)  # a new (mtime, size) so the phase cache re-reads
    assert skill.Bridge(nba_root.resolve()).find(_consensus())[0] == "not_regular_season"


def test_count_only_reads_no_box(nba_root, tmp_path, monkeypatch):
    def _boom(*_a, **_k):
        raise AssertionError("an outcome was read in --count-only")

    monkeypatch.setattr(skill, "fetch_linescores", _boom)
    monkeypatch.setattr(skill, "find_box", _boom)
    monkeypatch.setattr("syndicate.features.shared.segment_actuals.segment_score_pair", _boom)
    quotes = tmp_path / "quotes"
    quotes.mkdir()
    rows = []
    for book, over, under in (("fanduel", -110, -110), ("draftkings", -115, -105)):
        for sel, price in (("over", over), ("under", under)):
            rows.append({"captured_at": "2026-11-12T20:00:00+00:00", "commence_time": TIP, "kind": "game",
                         "event_id": "e1", "home_team": "Minnesota Timberwolves", "away_team": "Dallas Mavericks",
                         "bookmaker": book, "market": "totals", "segment": "q1", "selection": sel,
                         "line": 52.5, "price": price, "player_name": None})
    with gzip.open(quotes / "2026-11-12.jsonl.gz", "wt", encoding="utf-8") as fh:
        fh.write("\n".join(json.dumps(r) for r in rows) + "\n")
    out = tmp_path / "count.json"
    assert skill.main(["--nba-root", str(nba_root), "--quotes", str(quotes), "--linescores",
                       str(tmp_path / "linescores.json"), "--out", str(out), "--count-only"]) == 0
    population = json.loads(out.read_text(encoding="utf-8"))["population"]
    assert population["eligible_markets"] == 1 and population["eligible_games_by_family"] == {"totals": 1}
    assert not (tmp_path / "linescores.json").exists()


def test_g2_ties_go_to_the_smaller_w_and_frozen_skips_the_fit():
    early, late = "2026-10-25T00:00:00Z", "2026-11-05T00:00:00Z"
    same = [{"game": f"g{i}", "segment": "q1", "market": "totals", "y": i % 2, "p_model": 0.5, "p_market": 0.5,
             "commence_time": early if i < 10 else late} for i in range(20)]
    out = skill.g2(same, reps=50, seed=818)
    assert out["families"]["totals"]["w_fit"] == 0.0 and out["families"]["totals"]["earns_weight"] is False
    sharp = [{**o, "p_model": 0.9 if o["y"] else 0.1} for o in same]
    assert skill.g2(sharp, reps=50, seed=818)["families"]["totals"]["w_fit"] == 1.0
    frozen = skill.g2(sharp, reps=50, seed=818, frozen={"totals": 0.05, "spreads": 0.0, "h2h": 0.0})
    assert frozen["families"]["totals"]["w_frozen"] == 0.05 and frozen["families"]["totals"]["test"]["n"] == 20
