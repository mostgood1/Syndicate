"""The prop fair side-lean study rebuilds the board's consensus from raw quotes and frames every group on its over."""
from __future__ import annotations

import gzip
import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


def _script():
    spec = importlib.util.spec_from_file_location(
        "prop_fair_side_lean", Path(__file__).resolve().parents[1] / "scripts" / "prop_fair_side_lean.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_a_book_reads_the_same_fair_under_every_devig_when_it_is_even():
    m = _script()
    f = m.book_over_fairs(-110, -110)
    assert f["mult"] == pytest.approx(0.5) and f["shin"] == pytest.approx(0.5) and f["power"] == pytest.approx(0.5)
    assert f["under_face"] == pytest.approx(1 - 110 / 210) and f["over_face"] == pytest.approx(110 / 210)
    assert f["hold"] == pytest.approx(2 * 110 / 210 - 1) and f["asym"] == pytest.approx(0.0)
    juiced = m.book_over_fairs(-130, +100)
    assert juiced["asym"] > 0 and juiced["under_face"] < juiced["mult"] < juiced["over_face"]


def test_graded_rows_are_framed_on_the_over_once_per_group(tmp_path):
    m = _script()
    base = {"game": "nba|e1", "phase": "pregame", "player": "A", "fm": "consensus", "market": "player_points",
            "segment": "full", "line": 20.5, "t": "2026-11-01T18:00:00Z", "date": "2026-11-01"}
    rows = [dict(base, side="under", y=1.0, fp=0.48), dict(base, side="over", y=0.0, fp=0.52),        # one group
            dict(base, player="B", side="under", y=0.0, fp=0.45),                                       # under only
            dict(base, player="C", side="over", y=0.5, fp=0.5),                                         # a push: out
            dict(base, player="D", side="over", y=1.0, fp=0.5, fm="book_margin_model")]                 # one-sided: out
    path = tmp_path / "g.jsonl.gz"
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        fh.write("\n".join(json.dumps(r) for r in rows))
    got = {r["player"]: r for r in m.load_graded(path, {"nba"})}
    assert set(got) == {"A", "B"}
    assert got["A"]["y_over"] == 0.0 and got["A"]["fp_over"] == pytest.approx(0.52)
    assert got["B"]["y_over"] == 1.0 and got["B"]["fp_over"] == pytest.approx(0.55)


def test_extract_uses_the_sighting_window_and_the_close():
    m = _script()
    t = datetime(2026, 11, 1, 18, tzinfo=timezone.utc)
    ct = t + timedelta(hours=6)
    row = {"sport": "nba", "event_id": "e1", "game": "nba|e1", "date": "2026-11-01", "market": "player_points",
           "segment": "full", "player": "A", "line": 20.5, "t": "2026-11-01T18:00:00Z", "y_over": 0.0, "fp_over": 0.5}

    def quotes(_root, _sport, _events, groups):
        (g,) = groups
        return {(g, "fanduel", "over"): [(t - timedelta(hours=1), -110, ct), (ct - timedelta(minutes=5), -125, ct)],
                (g, "fanduel", "under"): [(t - timedelta(hours=1), -110, ct), (ct - timedelta(minutes=5), +105, ct)],
                (g, "pinnacle", "over"): [(t - timedelta(hours=13), -105, ct)],                       # too old to sight
                (g, "pinnacle", "under"): [(t - timedelta(hours=13), -105, ct)]}

    (rec,) = m.extract([row], Path("."), max_age_h=12, max_stale_h=6, read_quotes=quotes)
    assert rec["sight"]["books"] == ["fanduel"] and rec["sight"]["shin"] == pytest.approx(0.5)
    assert rec["close"]["shin"] > 0.5 and rec["sharp_sight"] == {}                                    # moved to the over
    assert rec["close"]["books"] == ["fanduel"]                                                       # pinnacle stale at close


def test_lean_and_its_interval_are_by_game():
    m = _script()
    rows = [{"game": g, "y_over": y, "p": 0.5} for g, y in (("a", 0.0), ("a", 0.0), ("b", 1.0), ("c", 0.0), ("d", 0.0))]
    got = m.lean(rows, lambda r: r["p"])
    assert got["n"] == 5 and got["games"] == 4 and got["pts"] == pytest.approx(-30.0)
    assert got["ci"][0] <= -30.0 <= got["ci"][1]
    flat = m.slope_on([{"game": str(i), "y_over": 0.5, "p": 0.5, "x": i / 100} for i in range(40)], lambda r: r["x"], lambda r: r["p"])
    assert flat["slope_pts"] == pytest.approx(0.0)


def test_holdout_fits_before_and_scores_after_or_reads_a_frozen_shift():
    m = _script()
    import random
    rng = random.Random(11)
    rows = []
    for i in range(6000):
        date = "2026-10-20" if i < 3000 else "2026-11-05"
        rows.append({"sport": "nba", "game": f"g{i // 30}", "date": date, "fp_over": 0.5,
                     "y_over": 1.0 if rng.random() < 0.46 else 0.0})
    got = m.holdout(rows, sport="nba", fit=("2026-10-01", "2026-11-01"), test=("2026-11-02", "2026-11-12"))
    assert got["delta"] < 0 and got["lean_before"]["n"] == 3000 and got["dll"] < 0
    assert abs(got["lean_after"]["pts"]) < abs(got["lean_before"]["pts"])
    off = m.holdout(rows, sport="nba", fit=None, test=("2026-11-02", "2026-11-12"), delta=0.0)
    assert off["dll"] == 0.0 and not off["passes"]                                   # off != on
    assert m.holdout(rows, sport="nfl", fit=("2026-10-01", "2026-11-01"), test=("2026-11-02", "2026-11-12")) is None


def test_pull_keeps_opportunity_props_only_and_reads_the_local_disk(tmp_path):
    m = _script()
    (tmp_path / "reports").mkdir()
    (tmp_path / "reports" / "x.jsonl").write_text("hello", encoding="utf-8")
    reader = m.LocalReader(tmp_path)
    assert reader.text("reports/x.jsonl") == "hello" and reader.text("reports/missing.jsonl") is None
    recs = [{"k": "prop", "ln": "opportunity"}, {"k": "game", "ln": "opportunity"}, {"k": "prop", "ln": "watch"}]
    ident = {"prop": {"player_name": "A"}, "game": {"player_name": ""}}
    got = m.prop_records(["t1", None], lambda text: recs if text else [], lambda k: ident.get(k))
    assert got == [recs[0]]
