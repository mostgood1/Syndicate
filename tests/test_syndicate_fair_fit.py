"""`scripts/syndicate_fair_fit.py` -- extract, assembly, the walk-forward and the pre-registered verdict.

Hermetic: a synthetic data root in tmp_path and synthetic scoreboard chips. Nothing here reads the fleet.
There is no flag in this lane (the script is offline and nothing in production imports the module), so the
reachability check is that the FITTED path actually runs and moves the fair off the equal-weight pool.
"""
from __future__ import annotations

import gzip
import importlib.util
import json
import math
from pathlib import Path

import numpy as np
import pytest

from syndicate.features.shared import layer2_board
from syndicate.features.shared.opportunity_signals import devig

_ROOT = Path(__file__).resolve().parents[1]


def _load(name):
    spec = importlib.util.spec_from_file_location(name, _ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


fit = _load("syndicate_fair_fit")
fpe = _load("fair_price_eval")


def _iso(ts: int) -> str:
    return fit.iso(ts)


def _q(ev, book, side, price, cap, ct, market="h2h", line=None, home="Home Team", away="Away Team", player=None, kind="game"):
    return {"captured_at": _iso(cap), "commence_time": _iso(ct), "event_id": ev, "bookmaker": book, "market": market,
            "segment": "full", "selection": side, "price": price, "line": line, "player_name": player, "kind": kind,
            "home_team": home, "away_team": away, "date": fit.utc_date(ct)}


def _write(root: Path, sport: str, name: str, rows: list[dict]) -> None:
    d = root / f"{sport}_source" / "tracking" / "book_quotes"
    d.mkdir(parents=True, exist_ok=True)
    with gzip.open(d / name, "wt", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")


# ----------------------------------------------------------------------------- identity


@pytest.mark.parametrize("market,side,line", [("spreads", "home", -3.5), ("spreads", "away", 3.5), ("totals", "over", 44.5),
                                              ("h2h", "home", None), ("player_points", "under", 22.5)])
def test_line_key_is_the_evaluators_group_key(market, side, line) -> None:
    assert fit.line_key(market, "full", "P", side, line) == fpe.group_key("e", market, "full", "P", side, line)[1:]


def test_a_nan_line_is_no_line() -> None:
    """NBA/WNBA/NHL h2h rows carry `"line": NaN`; as a key part it made every quote row its own line."""
    assert fit.line_key("h2h", "full", "", "home", float("nan")) == ("h2h", "full", "", None)
    assert fit.line_key("h2h", "full", "", "home", float("nan")) == fit.line_key("h2h", "full", "", "away", float("nan"))


@pytest.mark.parametrize("sides,expected", [({"away", "home"}, ("home", "away")), ({"draw", "home", "away"}, ("home", "away", "draw")),
                                            ({"under", "over"}, ("over", "under")), ({"yes"}, None), ({"over"}, None),
                                            ({"no", "yes"}, ("yes", "no"))])
def test_canonical_sides(sides, expected) -> None:
    assert fit.canonical_sides(sides) == expected


def test_shin_median_is_the_boards_consensus_fair() -> None:
    books = {"a": [-150, 130], "b": [-140, 120], "c": [-165, 140]}
    per_book = {b: devig(p, method="shin") for b, p in books.items()}
    ours = fit.shin_median(per_book, 2)
    cells = {b: {"home": {"price": p[0]}, "away": {"price": p[1]}} for b, p in books.items()}
    prod = layer2_board._consensus_fair(cells, ["home", "away"], method="shin")
    assert ours[0] == pytest.approx(prod["home"], abs=1e-12) and ours[1] == pytest.approx(prod["away"], abs=1e-12)


# ----------------------------------------------------------------------------- extract


def test_extract_takes_each_cutoffs_latest_quote_and_drops_in_play(tmp_path: Path) -> None:
    ct = fit.epoch("2026-10-10T20:00:00+00:00")
    rows = [_q("e1", "pinnacle", "home", -120, ct - 30 * 3600, ct), _q("e1", "pinnacle", "home", -125, ct - 5 * 3600, ct),
            _q("e1", "pinnacle", "home", -130, ct - 600, ct), _q("e1", "pinnacle", "home", -400, ct + 600, ct)]
    _write(tmp_path, "mlb", "2026-10-10.jsonl.gz", rows)
    _, snaps, cov = fit.extract_sport(tmp_path, "mlb", fit.epoch(fit.WINDOW_START), fit.epoch(fit.WINDOW_END))
    (s,) = snaps.values()
    # t24h, t6h (the -125 at T-5h is after it), t2h, t30m, close; the in-play -400 never
    assert [q[1] for q in s] == [-120, -120, -125, -125, -130]
    assert cov["events"] == 1 and cov["by_day"]["2026-10-10"]["pinnacle_game_events"] == 1


def test_a_moved_game_is_snapshotted_against_its_final_commence_time(tmp_path: Path) -> None:
    old, new = fit.epoch("2026-10-10T17:00:00+00:00"), fit.epoch("2026-10-10T20:00:00+00:00")
    rows = [_q("e1", "dk", "home", -110, old - 3600, old), _q("e1", "dk", "home", -115, old + 60, new)]
    _write(tmp_path, "nfl", "2026-10-10.jsonl.gz", rows)
    events, snaps, _ = fit.extract_sport(tmp_path, "nfl", fit.epoch(fit.WINDOW_START), fit.epoch(fit.WINDOW_END))
    assert events["e1"]["commence"] == new
    (s,) = snaps.values()
    assert s[-1][1] == -115  # a quote after the OLD start is still pregame for the moved game


def test_per_file_flush_then_merge_equals_one_pass(tmp_path: Path) -> None:
    ct = fit.epoch("2026-10-12T00:00:00+00:00")
    a = [_q("e1", "dk", "over", -110, ct - 8 * 3600, ct, market="totals", line=44.5),
         _q("e1", "dk", "over", -105, ct - 1000, ct, market="totals", line=44.5)]
    b = [_q("e1", "dk", "over", -108, ct - 3 * 3600, ct, market="totals", line=44.5)]
    _write(tmp_path, "nfl", "2026-10-11.jsonl.gz", a)
    _write(tmp_path, "nfl", "2026_wk6.jsonl.gz", b)
    start, end = fit.epoch(fit.WINDOW_START), fit.epoch(fit.WINDOW_END)
    _, whole, _ = fit.extract_sport(tmp_path, "nfl", start, end)
    parts: list[str] = []
    fit.extract_sport(tmp_path, "nfl", start, end, flush=lambda s: parts.extend(fit.snap_records(s)))
    merged = fit.merge_snaps(json.loads(p) for p in parts)
    assert len(parts) == 2 and {k: v for k, v in merged.items()} == {k: v for k, v in whole.items()}


# ----------------------------------------------------------------------------- assembly


def _chips(day: str, sport: str, away: int, home: int) -> dict:
    return {day: [{"sport": sport, "state": "final", "away": {"name": "Away Team", "key": "away team", "score": str(away)},
                   "home": {"name": "Home Team", "key": "home team", "score": str(home)}}]}


def _extract_to(tmp_path: Path, sport: str, rows: list[dict]) -> Path:
    data, out = tmp_path / "data", tmp_path / "out"
    _write(data, sport, "d.jsonl.gz", rows)
    fit.cmd_extract(type("A", (), {"data_root": str(data), "out": str(out), "sports": sport,
                                   "start": fit.WINDOW_START, "end": fit.WINDOW_END})())
    return out


def test_assembly_targets_the_sharp_close_by_power_and_falls_back_to_the_shin_consensus(tmp_path: Path) -> None:
    ct = fit.epoch("2026-10-11T18:00:00+00:00")
    rows = []
    for ev, with_pinnacle in (("e1", True), ("e2", False)):
        for book, (h, a) in {"dk": (-150, 130), "fd": (-145, 125), "pinnacle": (-160, 145)}.items():
            if book == "pinnacle" and not with_pinnacle:
                continue
            rows += [_q(ev, book, "home", h, ct - 7 * 3600, ct), _q(ev, book, "away", a, ct - 7 * 3600, ct)]
    out = _extract_to(tmp_path, "nfl", rows)
    got, counters = fit.assemble_sport(out, "nfl", _chips("2026-10-11", "nfl", 17, 24), parity_every=1)
    by_ev = {r["ev"]: r for r in got if r["tts"] == "t6h"}
    assert by_ev["e1"]["src"] == "sharp"
    assert by_ev["e1"]["target"] == pytest.approx(devig([-160, 145], method="power"))
    assert by_ev["e2"]["src"] == "consensus"
    assert by_ev["e2"]["target"] == pytest.approx(fit.shin_median({"dk": devig([-150, 130], method="shin"),
                                                                    "fd": devig([-145, 125], method="shin")}, 2))
    assert by_ev["e1"]["y"] == [1.0, 0.0]  # home won 24-17
    assert by_ev["e1"]["family"] == "nfl|regular|game" and by_ev["e1"]["mfam"] == "h2h"
    assert counters["parity_checked"] > 0 and counters.get("parity_mismatch", 0) == 0
    # t24h: every quote is 7h before the start, so there is no row 24h out
    assert {r["tts"] for r in got} == {"t6h", "t2h", "t30m"}


def test_a_quote_older_than_twelve_hours_at_the_snapshot_is_not_used(tmp_path: Path) -> None:
    ct = fit.epoch("2026-10-11T18:00:00+00:00")
    rows = []
    for book, cap in (("dk", ct - 13 * 3600), ("fd", ct - 13 * 3600), ("mgm", ct - 3 * 3600), ("bet", ct - 3 * 3600)):
        rows += [_q("e1", book, "over", -110, cap, ct, market="totals", line=44.5),
                 _q("e1", book, "under", -110, cap, ct, market="totals", line=44.5)]
    out = _extract_to(tmp_path, "nfl", rows)
    got, _ = fit.assemble_sport(out, "nfl", {})
    books = {r["tts"]: sorted(b for b, _, _ in r["books"]) for r in got}
    assert books == {"t6h": ["dk", "fd"],                       # mgm/bet had not quoted yet
                     "t2h": ["bet", "dk", "fd", "mgm"],          # dk/fd are 11h old: in
                     "t30m": ["bet", "mgm"]}                     # dk/fd are 12.5h old: out


def test_a_one_sided_market_never_becomes_a_line(tmp_path: Path) -> None:
    ct = fit.epoch("2026-10-11T18:00:00+00:00")
    rows = [_q("e1", b, "yes", 250, ct - 3600, ct, market="anytime td", player="P", kind="prop") for b in ("dk", "fd")]
    out = _extract_to(tmp_path, "ncaaf", rows)
    got, counters = fit.assemble_sport(out, "ncaaf", {})
    assert got == [] and counters["lines_not_two_sided_or_unknown"] == 1


def test_central_dates_cover_late_utc_kickoffs() -> None:
    days = fit.central_dates(fit.epoch("2026-10-01T00:00:00+00:00"), fit.epoch("2026-10-03T08:00:00+00:00"))
    assert days[0] == "2026-09-30" and days[-1] == "2026-10-03"


# ----------------------------------------------------------------------------- statistics and the verdict


def test_cluster_boot_resamples_games_not_rows() -> None:
    values = [1.0] * 50 + [-1.0] * 50
    games = ["a"] * 50 + [f"g{i}" for i in range(50)]
    out = fit.cluster_boot(values, games, B=500)
    assert out["n"] == 100 and out["games"] == 51 and out["mean"] == 0.0
    lo, hi = out["ci0.95"]
    assert lo < -0.3 and hi > 0.3  # one game holds half the rows: the CI is wide, as it must be


@pytest.mark.parametrize("g1,g2,expected", [
    ({"games": 10, "test_dates": 5, "ci0.95": [-1, -0.5]}, {}, "UNDERPOWERED"),
    ({"games": 40, "test_dates": 2, "ci0.95": [-1, -0.5]}, {}, "UNDERPOWERED"),
    ({"games": 40, "test_dates": 5, "ci0.95": [-1, -0.5]}, {}, "PASS (outcome unmeasured)"),
    ({"games": 40, "test_dates": 5, "ci0.95": [-1, -0.5]}, {"games": 40, "ci0.95": [-0.1, 0.2]}, "PASS"),
    ({"games": 40, "test_dates": 5, "ci0.95": [-1, -0.5]}, {"games": 40, "ci0.95": [0.01, 0.2]}, "FAIL (worse on outcomes)"),
    ({"games": 40, "test_dates": 5, "ci0.95": [-1, 0.1]}, {"games": 40, "ci0.95": [-0.1, 0.2]}, "FAIL"),
    ({"games": 40, "test_dates": 5, "ci0.95": [-1, -0.5]}, {"games": 10, "ci0.95": [0.01, 0.2]}, "PASS (outcome unmeasured)"),
])
def test_verdict(g1, g2, expected) -> None:
    assert fit.verdict({"g1_close": g1, "g2_outcome": g2}) == expected


def _synthetic_family(seed: int, n_dates: int = 12, games_per_date: int = 8) -> list[dict]:
    """A sharp book that IS the close (plus a hair of noise) and three soft books scattered around it."""
    rng = np.random.default_rng(seed)
    rows = []
    for d in range(n_dates):
        date = f"2026-10-{d + 1:02d}"
        for g in range(games_per_date):
            truth = rng.normal(0, 0.6)
            close = 1 / (1 + math.exp(-truth))
            ev = f"{date}-{g}"
            for i, tts in enumerate(("t24h", "t6h", "t2h", "t30m")):
                books = [("sharp", 600.0, None)] + [(f"soft{j}", 600.0, None) for j in range(3)]
                probs = []
                for b, age, _ in books:
                    noise = 0.02 if b == "sharp" else 0.25
                    p = 1 / (1 + math.exp(-(truth + rng.normal(0, noise))))
                    probs.append((b, age, [p, 1 - p]))
                base = fit.shin_median({b: p for b, _, p in probs}, 2)
                rows.append({"ev": ev, "date": date, "commence": fit.epoch(f"{date}T18:00:00+00:00"), "k": 2,
                             "mfam": "h2h", "tts": tts, "books": probs, "base": base, "target": [close, 1 - close],
                             "src": "consensus", "cons_close": [close, 1 - close], "y": None})
    return rows


def test_walk_forward_is_strictly_as_of_and_the_fitted_path_runs() -> None:
    rows = _synthetic_family(23)
    wf = fit.walk_forward(rows, log=lambda s: None)
    first = wf["fits"][0]
    # trained on >= MIN_TRAIN_DATES dates, all of which closed a full day before the test date
    assert first["train_dates"] >= fit.MIN_TRAIN_DATES and first["test_date"] == "2026-10-07"
    scored = ~np.isnan(wf["p_v1"][:, 0])
    assert not scored[[r["date"] < "2026-10-07" for r in rows]].any()
    # reachability: the fit moved the fair off the equal-weight pool (theta != 0 reached the prediction)
    assert np.abs(wf["p_v1"][scored, 0] - wf["p_eq"][scored, 0]).max() > 1e-3
    result = fit.evaluate_family(rows, wf, n_families=1)
    assert result["g1_close"]["mean"] < 0 and result["g1_close"]["ci0.95"][1] < 0
    assert result["verdict"] == "PASS (outcome unmeasured)"
    table = wf["model"].weights_table("h2h", "t2h")
    assert table["sharp"] > max(table["soft0"], table["soft1"], table["soft2"])


def test_with_no_signal_the_fair_does_not_pass() -> None:
    rows = _synthetic_family(29)
    for r in rows:  # every book equally noisy: nothing to learn, the median is as good as any pool
        r["books"] = [(b.replace("sharp", "soft9"), a, p) for b, a, p in r["books"]]
    rng = np.random.default_rng(1)
    for r in rows:
        r["books"] = [(b, a, [q, 1 - q]) for b, a, (p, _) in r["books"]
                      for q in [1 / (1 + math.exp(-(math.log(p / (1 - p)) + rng.normal(0, 0.25))))]]
        r["base"] = fit.shin_median({b: p for b, _, p in r["books"]}, 2)
    wf = fit.walk_forward(rows, log=lambda s: None)
    assert fit.evaluate_family(rows, wf, n_families=1)["verdict"] in ("FAIL", "PASS (outcome unmeasured)")
    table = wf["model"].weights_table("h2h", "t2h")
    assert max(table.values()) / min(table.values()) < 3  # no book is singled out when none is sharp
