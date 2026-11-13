"""Pre-registered grade of the live segment expert's NCAAB HALF lines against the books, by quote age.

Lane `college-segment-grade` (2026-11-13), for `#763` (college live halves are built and OFF: "to turn on, a measured
college segment quote-age ceiling ... then a scored sample") and `#736` (the engine-experts umbrella).

WHAT IS GRADED
--------------
Every OPINED row of `engine_experts.live_segment_expert` (`live_segment/1`, on main `0f14bdcc1`; its evidence index
de-duplicated as of this lane) on NCAAB, h1 / h2 x totals / spreads, for every game FINAL on the registered dates'
scoreboards: at one logged re-sim tick, one half line some book was quoting, the engine's two-way probability
(`p_expert`, the live join's own estimator) beside the books' de-vigged median at the same instant (`p_prior`), with
`prior_age_s` = the age of the NEWEST usable book's quote at that instant. One enumeration covers every evidence file
and quote shard from the day before the first date to the day after the last (`span`).

    outcome   ESPN's half scores (`ncaab_source/data/scoreboard/scoreboard_<date>.json`, `games[].live_state`
              `{home,away}_linescores`, final games only), joined on the ESPN event id the evidence log carries.
              h1 = period 1. h2 = period 2 AND EVERY OVERTIME PERIOD (the books' second-half rule, the college
              re-sim's h2 -- `#763` -- and `segment_actuals`' football h2).
    event     totals: total > line ("over"). spreads: home margin > line, the expert's AWAY-FRAME line
              (`canonical_quote_side`: a home -2.5 quote is line 2.5). A row whose outcome lands ON the line is a push
              and is dropped (both numbers are two-way).
    score     d = (p_expert - y)^2 - (p_prior - y)^2 per row, NEGATIVE where the engine beats the books. A cell's
              number is the row-weighted mean of d; its interval a GAME-clustered bootstrap (games resampled with
              replacement; `PREREG["bootstrap"]` draws, fixed seed).

THE REGISTERED DECISION (fixed before any outcome was read; `PREREG`)
--------------------------------------------------------------------
Eight primary tests: (h1, h2) x (totals, spreads) x quote age <= 30 s and <= 120 s (cumulative ceilings). A test
PASSES when its cell has >= `min_games` graded games AND the upper bound of its family-wise interval (Bonferroni:
two-sided level 1 - 0.05 / 8) is below 0: the engine beats FRESH books there beyond family-wise noise, and that pair is
a candidate to price at that ceiling. Fewer games -> `insufficient` (no decision). Otherwise `no_edge`.

    verdict   no test passes  -> the hypothesis holds: on this evidence the engine does not beat fresh books on any
                                 college half line; `#763` stays off, and the interval half-widths say how large an
                                 edge this sample could have missed.
              any test passes -> the hypothesis is falsified for that pair; the smallest passing ceiling is the
                                 measured quote-age ceiling `#763` asks for (a candidate, not a switch: turning
                                 pricing on is the user's decision).

Read beside it, never as a decision: d by DISJOINT quote-age bucket (the hypothesis says the engine's apparent
advantage grows with age: a stale quote does not know the state the re-sim does), and the claimed-vs-realised edge
on rows where |p_expert - p_prior| >= 5 pp, betting the engine's side at the books' fair.

Usage (fleet, read-only, nice 19; env from refresh-worker, see the lane):
    python scripts/college_segment_grade.py --count-only        # counts only: no score is read
    python scripts/college_segment_grade.py --grade --json out.json
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

PREREG: dict[str, Any] = {
    "id": "college_segment_grade/1",
    "registered": "2026-11-13, lane college-segment-grade, before any outcome was read",
    "sport": "ncaab",
    "dates": ("2026-11-09", "2026-11-10", "2026-11-11", "2026-11-12"),
    "expert_version": "live_segment/1",
    "segments": ("h1", "h2"),
    "markets": ("totals", "spreads"),
    "ceilings_s": (30.0, 120.0),
    "age_buckets": ((0.0, 30.0, "0-30s"), (30.0, 120.0, "30-120s"), (120.0, 300.0, "120-300s"),
                    (300.0, 900.0, "300-900s")),
    "min_games": 30,
    "alpha": 0.05,
    "n_tests": 8,
    "bootstrap": 20000,
    "seed": 763,
    "edge_pp": 0.05,
}

STATUS_PASS = "PASS"
STATUS_NO_EDGE = "no_edge"
STATUS_INSUFFICIENT = "insufficient"


# ----------------------------------------------------------------------------- outcomes


def segment_points(periods: Sequence[Any] | None, segment: str) -> int | None:
    """One team's points in a college half. h1 = period 1; h2 = period 2 plus every overtime period. None when the
    line score cannot answer (missing, short, or a non-integer entry)."""
    if not isinstance(periods, (list, tuple)) or len(periods) < 2:
        return None
    values = list(periods)
    if any(not isinstance(v, int) or isinstance(v, bool) for v in values):
        return None
    if segment == "h1":
        return values[0]
    if segment == "h2":
        return sum(values[1:])
    return None


def outcome(market: str, line: float, home_pts: int, away_pts: int) -> int | None:
    """1 / 0 for the expert's event (over; home covers the away-frame line), None for a push."""
    value = home_pts + away_pts if market == "totals" else home_pts - away_pts
    if value == line:
        return None
    return 1 if value > line else 0


def _name_keys(*names: Any) -> set[str]:
    from syndicate.features.shared.engine_experts import team_key

    keys = {team_key(n) for n in names if str(n or "").strip()}
    try:
        from syndicate.features.shared.team_aliases import chip_join_key

        keys |= {k for k in (chip_join_key("ncaab", str(n or "")) for n in names if str(n or "").strip()) if k}
    except Exception:  # noqa: BLE001 -- the alias table is an extra key, never a requirement
        pass
    return {k for k in keys if k}


def orientation(evidence_teams: Mapping[str, Any], game: Mapping[str, Any]) -> str | None:
    """"same" when the evidence log's home team is the scoreboard's home, "swapped" when it is the scoreboard's away
    (the slate re-orients neutral sites to the odds feed; the evidence may not), None when names and abbreviations
    cannot tell. Totals do not need it; a spread with None is not graded."""
    home, away = game.get("home") or {}, game.get("away") or {}
    ev_home = _name_keys(evidence_teams.get("home_name")) | {str(evidence_teams.get("home") or "").upper() or "?"}
    ev_away = _name_keys(evidence_teams.get("away_name")) | {str(evidence_teams.get("away") or "").upper() or "?"}
    sb_home = _name_keys(home.get("name"), home.get("short_name")) | {str(home.get("abbr") or "").upper() or "!"}
    sb_away = _name_keys(away.get("name"), away.get("short_name")) | {str(away.get("abbr") or "").upper() or "!"}
    same = bool(ev_home & sb_home) and bool(ev_away & sb_away)
    swapped = bool(ev_home & sb_away) and bool(ev_away & sb_home)
    if same and not swapped:
        return "same"
    if swapped and not same:
        return "swapped"
    return None


def final_games(scoreboards: Iterable[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    """ESPN event id -> the scoreboard game record, FINAL games only (a later file's final record wins)."""
    out: dict[str, Mapping[str, Any]] = {}
    for board in scoreboards:
        for game in (board or {}).get("games") or []:
            live = game.get("live_state") or {}
            if live.get("final") and str(game.get("event_id") or ""):
                out[str(game["event_id"])] = game
    return out


# ----------------------------------------------------------------------------- rows


@dataclass
class GradeRow:
    event_id: str
    segment: str
    market: str
    line: float
    t: str
    p_model: float
    p_books: float
    age_s: float
    clock_bucket: str | None
    y: int | None = None

    @property
    def d(self) -> float:
        return (self.p_model - self.y) ** 2 - (self.p_books - self.y) ** 2


def build_rows(opinions: Iterable[Any], teams: Mapping[str, Mapping[str, Any]],
               games: Mapping[str, Mapping[str, Any]], *, read_scores: bool) -> tuple[list[GradeRow], dict[str, int]]:
    """Opined NCAAB half rows -> graded rows. `read_scores=False` (the count-only run) keeps every row whose game is
    FINAL and orientable without reading a score, so the registration's counts come before any outcome."""
    counts = {"opined": 0, "duplicate": 0, "out_of_scope": 0, "no_age": 0, "not_a_final_window_game": 0,
              "orientation_unresolved": 0, "unscorable": 0, "push": 0, "kept": 0}
    seen: set[tuple] = set()
    rows: list[GradeRow] = []
    for op in opinions:
        if op.delta_logit is None or op.p_expert is None or op.p_prior is None:
            continue
        counts["opined"] += 1
        if (op.sport != PREREG["sport"] or op.expert_version != PREREG["expert_version"]
                or op.segment not in PREREG["segments"] or op.market not in PREREG["markets"] or op.line is None):
            counts["out_of_scope"] += 1
            continue
        key = (op.event_id, op.segment, op.market, float(op.line), op.t)
        if key in seen:
            counts["duplicate"] += 1
            continue
        seen.add(key)
        if op.prior_age_s is None:
            counts["no_age"] += 1
            continue
        game = games.get(str(op.event_id))
        if game is None:
            counts["not_a_final_window_game"] += 1
            continue
        orient = orientation(teams.get(str(op.event_id)) or {}, game)
        if op.market == "spreads" and orient is None:
            counts["orientation_unresolved"] += 1
            continue
        row = GradeRow(str(op.event_id), op.segment, op.market, float(op.line), op.t, float(op.p_expert),
                       float(op.p_prior), float(op.prior_age_s), op.clock_bucket)
        if read_scores:
            live = game.get("live_state") or {}
            h = segment_points(live.get("home_linescores"), op.segment)
            a = segment_points(live.get("away_linescores"), op.segment)
            if h is None or a is None:
                counts["unscorable"] += 1
                continue
            if orient == "swapped":
                h, a = a, h
            row.y = outcome(op.market, row.line, h, a)
            if row.y is None:
                counts["push"] += 1
                continue
        rows.append(row)
        counts["kept"] += 1
    return rows, counts


# ----------------------------------------------------------------------------- the statistics


def cluster_bootstrap(rows: Sequence[GradeRow], value: Callable[[GradeRow], float], *, levels: Sequence[float],
                      draws: int, seed: Sequence[int]) -> dict[str, Any]:
    """Row-weighted mean of `value` with GAME-clustered bootstrap intervals at each two-sided `levels`."""
    import numpy as np

    by_game: dict[str, list[float]] = {}
    for r in rows:
        by_game.setdefault(r.event_id, []).append(value(r))
    out: dict[str, Any] = {"games": len(by_game), "rows": len(rows), "mean": None, "ci": {}}
    if not by_game:
        return out
    sums = np.array([sum(v) for v in by_game.values()], dtype=float)
    ns = np.array([len(v) for v in by_game.values()], dtype=float)
    out["mean"] = float(sums.sum() / ns.sum())
    rng = np.random.default_rng(list(seed))
    idx = rng.integers(0, len(sums), size=(draws, len(sums)))
    means = sums[idx].sum(axis=1) / ns[idx].sum(axis=1)
    for level in levels:
        lo, hi = np.quantile(means, [(1 - level) / 2, 1 - (1 - level) / 2])
        out["ci"][f"{level:.5f}"] = [float(lo), float(hi)]
    return out


def _rnd(x: Any, n: int = 5) -> Any:
    return None if x is None else round(x, n)


def grade(rows: Sequence[GradeRow], prereg: Mapping[str, Any] = PREREG) -> dict[str, Any]:
    """The registered decision (eight primary tests) plus the two readings beside it."""
    fw_level = 1 - prereg["alpha"] / prereg["n_tests"]
    nominal = 1 - prereg["alpha"]
    draws, seed = prereg["bootstrap"], prereg["seed"]
    d = lambda r: r.d  # noqa: E731
    primary, by_age, edges = [], [], []
    for si, segment in enumerate(prereg["segments"]):
        for mi, market in enumerate(prereg["markets"]):
            pair = [r for r in rows if r.segment == segment and r.market == market]
            for ci, ceiling in enumerate(prereg["ceilings_s"]):
                cell = [r for r in pair if r.age_s <= ceiling]
                res = cluster_bootstrap(cell, d, levels=(nominal, fw_level), draws=draws, seed=(seed, si, mi, ci))
                fw = res["ci"].get(f"{fw_level:.5f}")
                if res["games"] < prereg["min_games"]:
                    status = STATUS_INSUFFICIENT
                elif fw is not None and fw[1] < 0:
                    status = STATUS_PASS
                else:
                    status = STATUS_NO_EDGE
                n95 = res["ci"].get(f"{nominal:.5f}")
                primary.append({
                    "segment": segment, "market": market, "ceiling_s": ceiling, "games": res["games"],
                    "rows": res["rows"], "d_brier": _rnd(res["mean"], 6),
                    "ci95": [_rnd(x, 6) for x in n95] if n95 else None,
                    "ci_fw": [_rnd(x, 6) for x in fw] if fw else None,
                    "half_width95": _rnd((n95[1] - n95[0]) / 2, 6) if n95 else None,
                    "brier_model": _rnd(sum((r.p_model - r.y) ** 2 for r in cell) / len(cell), 6) if cell else None,
                    "brier_books": _rnd(sum((r.p_books - r.y) ** 2 for r in cell) / len(cell), 6) if cell else None,
                    "status": status,
                })
            for bi, (lo, hi, name) in enumerate(prereg["age_buckets"]):
                # the first bucket takes a slightly negative age (a book stamp a moment ahead of the capture clock),
                # as the <= 30 s ceiling does; the last is closed at the prior's 900 s bound
                last = bi == len(prereg["age_buckets"]) - 1
                cell = [r for r in pair if (bi == 0 or lo <= r.age_s) and (r.age_s < hi or (last and r.age_s == hi))]
                res = cluster_bootstrap(cell, d, levels=(nominal,), draws=draws, seed=(seed, si, mi, 100 + bi))
                n95 = res["ci"].get(f"{nominal:.5f}")
                by_age.append({"segment": segment, "market": market, "age": name, "games": res["games"],
                               "rows": res["rows"], "d_brier": _rnd(res["mean"], 6),
                               "ci95": [_rnd(x, 6) for x in n95] if n95 else None})
            for wi, (label, ceiling) in enumerate((("<=120s", 120.0), ("all ages", float("inf")))):
                cell = [r for r in pair if r.age_s <= ceiling and abs(r.p_model - r.p_books) >= prereg["edge_pp"]]
                claimed = cluster_bootstrap(cell, _claimed, levels=(nominal,), draws=draws,
                                            seed=(seed, si, mi, 200 + wi))
                realised = cluster_bootstrap(cell, _realised, levels=(nominal,), draws=draws,
                                             seed=(seed, si, mi, 300 + wi))
                n95 = realised["ci"].get(f"{nominal:.5f}")
                edges.append({"segment": segment, "market": market, "ages": label, "games": realised["games"],
                              "rows": realised["rows"], "claimed_pp": _pp(claimed["mean"]),
                              "realised_pp": _pp(realised["mean"]),
                              "realised_ci95_pp": [_pp(x) for x in n95] if n95 else None})
    passes = [p for p in primary if p["status"] == STATUS_PASS]
    verdict = {
        "hypothesis": "HOLDS" if not passes else "FALSIFIED",
        "passing": [{"segment": p["segment"], "market": p["market"], "ceiling_s": p["ceiling_s"]} for p in passes],
        "insufficient": [{"segment": p["segment"], "market": p["market"], "ceiling_s": p["ceiling_s"]}
                         for p in primary if p["status"] == STATUS_INSUFFICIENT],
    }
    return {"prereg": dict(prereg), "family_level": fw_level, "primary": primary, "by_age": by_age, "edges": edges,
            "verdict": verdict}


def _side_model(r: GradeRow) -> int:
    """1 when the engine's side is the expert's event (over / home covers), 0 when it is the other side."""
    return 1 if r.p_model > r.p_books else 0


def _claimed(r: GradeRow) -> float:
    return abs(r.p_model - r.p_books)


def _realised(r: GradeRow) -> float:
    fair = r.p_books if _side_model(r) else 1.0 - r.p_books
    won = r.y if _side_model(r) else 1 - r.y
    return won - fair


def _pp(x: Any) -> Any:
    return None if x is None else round(100.0 * x, 2)


# ----------------------------------------------------------------------------- the fleet run


def _runner():
    spec = importlib.util.spec_from_file_location("engine_experts_runner", REPO / "scripts" / "engine_experts.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def span(dates: Sequence[str]) -> list[str]:
    """The registered game dates widened by a day each side: a late tip's ticks fall on the next Central date, and a
    game whose quote rows carry two kickoff times is split across two `book_quotes` shards (`kickoff_shard_date`)."""
    first, last = date.fromisoformat(min(dates)), date.fromisoformat(max(dates))
    return [(first + timedelta(days=k)).isoformat() for k in range(-1, (last - first).days + 2)]


def collect(dates: Sequence[str], root: Path | None = None) -> tuple[list[Any], dict[str, dict[str, Any]],
                                                                     dict[str, Any]]:
    """The expert's NCAAB segment opinions, ONE enumeration over every evidence file and every quote shard in `span`
    (so a game split across two shards is priced against all of its quotes, not two partial halves), the evidence
    log's team names per ESPN event id, and the expert's stats. The window is applied after, by game: `final_games`
    over the registered dates' scoreboards."""
    from syndicate.features.shared import engine_experts as ee
    from syndicate.features.shared import live_evidence_log as lel

    runner = _runner()
    sport = PREREG["sport"]
    days = span(dates)
    evidence = [row for d in days for row in lel.iter_rows(sport, d, root=root)]
    teams: dict[str, dict[str, Any]] = {}
    for row in evidence:
        eid = str(row.get("event_id") or "")
        if eid and eid not in teams:
            teams[eid] = {k: row.get(k) for k in ("home_name", "away_name", "home", "away")}
    index = ee.EvidenceIndex(evidence)
    quotes = ee.GameLineQuoteIndex((row for d in days for row in runner._iter_quote_rows(sport, d)), ee.Reader())
    ops, st = ee.live_segment_opinions(index, quotes, ee.Reader())
    stats = {k: (len(v) if isinstance(v, list) else v) for k, v in st.items()}
    stats.update({"days": days, "evidence_rows": len(evidence), "quote_rows": quotes.rows, "lines": len(ops)})
    # only what the grade reads, so the opinions' inputs are not held through the bootstrap
    opinions = [SlimOpinion(**{f: getattr(o, f) for f in SlimOpinion.__dataclass_fields__})
                for o in ops if o.delta_logit is not None]
    stats["opined"] = len(opinions)
    return opinions, teams, stats


@dataclass
class SlimOpinion:
    """The `ExpertOpinion` fields the grade reads."""
    sport: str
    expert_version: str
    event_id: str
    segment: str
    market: str
    line: float | None
    t: str
    p_expert: float | None
    p_prior: float | None
    prior_age_s: float | None
    clock_bucket: str | None
    delta_logit: float | None


def load_scoreboards(dates: Sequence[str]) -> list[Mapping[str, Any]]:
    """The registered dates' scoreboards, exactly: a game is in the window when ESPN lists it on one of them."""
    from syndicate.features.ncaab.slate import slate_artifact_path

    boards = []
    for d in sorted(dates):
        path = slate_artifact_path(d, "ncaab")
        if path.exists():
            boards.append(json.loads(path.read_text(encoding="utf-8")))
    return boards


def count_table(rows: Sequence[GradeRow], prereg: Mapping[str, Any] = PREREG) -> list[dict[str, Any]]:
    out = []
    for segment in prereg["segments"]:
        for market in prereg["markets"]:
            pair = [r for r in rows if r.segment == segment and r.market == market]
            for ceiling in prereg["ceilings_s"]:
                cell = [r for r in pair if r.age_s <= ceiling]
                out.append({"segment": segment, "market": market, "ceiling_s": ceiling, "rows": len(cell),
                            "games": len({r.event_id for r in cell})})
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--count-only", action="store_true", help="counts only; no score is read")
    mode.add_argument("--grade", action="store_true", help="the registered grade (run once)")
    parser.add_argument("--json", type=Path, default=None)
    args = parser.parse_args(argv)

    dates = list(PREREG["dates"])
    opinions, teams, stats = collect(dates)
    games = final_games(load_scoreboards(dates))
    rows, counts = build_rows(opinions, teams, games, read_scores=bool(args.grade))
    report: dict[str, Any] = {"mode": "grade" if args.grade else "count_only", "dates": dates, "expert_stats": stats,
                              "row_counts": counts, "final_games": len(games), "counts": count_table(rows)}
    print("STATS", json.dumps(stats, sort_keys=True))
    print("ROWS", json.dumps(counts, sort_keys=True), "final_games", len(games))
    for c in report["counts"]:
        print("COUNT", json.dumps(c, sort_keys=True))
    if args.grade:
        g = grade(rows)
        report.update(g)
        for p in g["primary"]:
            print("PRIMARY", json.dumps(p, sort_keys=True))
        for b in g["by_age"]:
            print("BY_AGE", json.dumps(b, sort_keys=True))
        for e in g["edges"]:
            print("EDGE", json.dumps(e, sort_keys=True))
        print("VERDICT", json.dumps(g["verdict"], sort_keys=True))
    if args.json:
        args.json.write_text(json.dumps(report, indent=1, default=str), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
