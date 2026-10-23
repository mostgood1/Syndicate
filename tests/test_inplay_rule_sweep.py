"""The rule sweep must replay inplay_entries_paper.decide exactly, not a drifting copy."""

from __future__ import annotations

import importlib.util
import itertools
import json
from datetime import datetime, timezone
from pathlib import Path

from syndicate.features.shared import inplay_entries_paper as ip

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("inplay_rule_sweep", ROOT / "scripts" / "inplay_rule_sweep.py")
sw = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sw)

T0 = datetime(2026, 10, 22, 23, 30, tzinfo=timezone.utc).timestamp()
TICK = "KXNHLSPREAD-26OCT22TORCBJ-TOR2"


def iso(t):
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _night(tmp_path: Path) -> Path:
    d = tmp_path / "inplay_2026-10-22"
    d.mkdir()
    k, b, e = [], [], []
    for i in range(0, 1200, 10):
        t = T0 + i
        ya = 0.30 + 0.02 * ((i // 120) % 3)  # wiggles: some windows move, some don't
        k.append({"ts": iso(t), "t": TICK, "ev": "KXNHLSPREAD-26OCT22TORCBJ", "st": "active", "ya": f"{ya:.4f}",
                  "yb": f"{ya - 0.01:.4f}", "na": f"{1 - ya + 0.01:.4f}", "nb": f"{1 - ya:.4f}",
                  "sub": "Toronto wins by over 1.5 goals", "fs": 1.5, "res": ""})
        if i % 60 == 0:
            p = 0.33 + 0.01 * ((i // 60) % 7)
            bks = [{"key": f"b{j}", "markets": [{"key": "spreads", "last_update": iso(t - 20 * j), "outcomes": [
                {"name": "Toronto Maple Leafs", "price": 1 / p, "point": -1.5},
                {"name": "Columbus Blue Jackets", "price": 1 / (1 - p), "point": 1.5}]}]} for j in range(6)]
            b.append({"ts": iso(t), "sport": "nhl", "events": [{"id": "ev1", "home_team": "Columbus Blue Jackets",
                                                                 "away_team": "Toronto Maple Leafs", "bookmakers": bks}]})
        if i % 30 == 0:
            score = "1" if i >= 600 else "0"  # a goal at +600 s
            e.append({"ts": iso(t), "sport": "nhl", "state": "in",
                      "teams": [{"abbr": "TOR", "score": score}, {"abbr": "CBJ", "score": "0"}]})
    k.append({**k[-1], "st": "finalized", "res": "yes", "ts": iso(T0 + 4000)})
    for name, rows in (("kalshi.jsonl", k), ("books.jsonl", b), ("espn.jsonl", e)):
        (d / name).write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return d


def test_fast_filter_equals_decide(tmp_path):
    rows = sw.load_night(_night(tmp_path), ["nhl"])
    assert rows, "the synthetic night produced no feature rows"
    by_sample = {}
    for r in rows:
        by_sample.setdefault(r["t"], []).append(r)
    configs = [dict(zip(sw.GRID, v)) for v in itertools.product(
        [0.02, 0.05], [60, 300], [3, 5], [0.01, 0.05], [("yes", "no"), ("no",)], [(0.05, 0.95), (0.30, 0.70)])]
    checked = 0
    agreements_with_a_signal = 0
    for t, legs in by_sample.items():
        r0 = legs[0]
        for cfg in configs:
            fast = [r for r in legs if sw.qualifies(r, cfg)]
            d = ip.decide(market=r0["_market"], event=r0["_event"], poll_t=r0["_poll_t"], since_score_s=r0["since"],
                          mid_move_60s=r0["move"], now_t=t, params=sw.to_params(cfg))
            if not fast:
                assert d is None, (cfg, r0["since"], r0["move"])
            else:
                best = max(fast, key=lambda r: r["edge"])
                assert d is not None and d["leg"] == best["leg"], (cfg, d, best["leg"])
                assert abs(d["edge"] - round(best["edge"], 4)) < 1e-4
                agreements_with_a_signal += 1
            checked += 1
    assert checked > 100 and agreements_with_a_signal > 0  # both branches exercised


def test_booking_is_first_sample_per_ticker_leg_and_grades(tmp_path):
    rows = sw.load_night(_night(tmp_path), ["nhl"])
    rows.sort(key=lambda r: r["t"])
    loose = {"min_edge": -1.0, "score_quiet_s": -1, "min_books": 1, "mid_max_move": 1.0,
             "legs": ("yes", "no"), "ask_band": (0.0, 1.0)}
    ents = sw.book(rows, loose)
    assert len(ents) == 2 and {e["leg"] for e in ents} == {"yes", "no"}
    yes = next(e for e in ents if e["leg"] == "yes")
    assert yes["pnl"] == 1.0 - yes["ask"] - yes["fee"]  # settled YES
    assert yes["markout300"] is not None


def test_score_gate_counts_first_sight_as_a_change(tmp_path):
    rows = sw.load_night(_night(tmp_path), ["nhl"])
    first = min(rows, key=lambda r: r["t"])
    assert first["since"] is not None and first["since"] < 60  # just "changed" at first sight
    after_goal = [r for r in rows if T0 + 600 <= r["t"] < T0 + 660]
    assert after_goal and all(r["since"] < 120 for r in after_goal)
