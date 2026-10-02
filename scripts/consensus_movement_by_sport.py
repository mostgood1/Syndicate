"""Nightly: does the MARKET's move since a price was first seen predict the close, per sport?

WHY THIS EXISTS (lane `layer2-freshness-1h`, 2026-10-02, user: "the movement of the
market absolutely needs to influence the ranking ... consistently and correctly").
The Layer 2 score dropped its single-book movement term that day (one book's own
drift REVERTS: MLB 408 games, drifted longer +0.39 pp, shortened -0.33) and now lets
the market's move rank rows through EV against the current consensus. Whether a
market-wide move carries information BEYOND fair value -- momentum, or reversion --
was small and sport-inconsistent on the day (MLB -0.09/+0.11 pp over 408 games; NHL
+0.62/-0.56 over 8). This job measures it every night so a sport-specific weight is
added only where the data says so.

METHOD. From the per-book quote log (`<sport>_source/tracking/book_quotes/<date>.jsonl`)
for games that have STARTED: per (event, market, segment, player, line) and capture
batch, the no-vig consensus is the median across books quoting both sides
(multiplicative de-vig) -- the board's own fair. For every interior observation
(not the first capture, not the last) of every (book, side):

    consensus_move = consensus(t) - consensus(first)     [pp, this side]
    book_move      = implied(book, t) - implied(book, first)
    forward_clv    = implied(book, last pregame) - implied(book, t)   [pp]
                     (+ = the close moved toward this side after t)

Rows are split by consensus move (toward >= +0.25 pp, against <= -0.25, else held);
the contrast is mean forward CLV toward minus against, with a bootstrap over EVENTS.

VERDICT per sport: `momentum` (contrast CI above 0), `reversion` (below 0),
`no_effect` (CI spans 0) or `insufficient` (< MIN_EVENTS events). CLV is not ROI.

Read-only on the quote log; writes one JSON report under the data root.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import random
import statistics
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

THRESHOLD_PP = 0.25
MIN_EVENTS = 20
BOOTSTRAP_DRAWS = 1000
DEFAULT_SPORTS = ("nfl", "ncaaf", "wnba", "nhl", "mlb", "soccer")


def _implied(price: Any) -> float:
    p = float(price)
    return 100.0 / (p + 100.0) if p > 0 else -p / (-p + 100.0)


def _ts(text: Any) -> datetime:
    stamp = datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)


def observations(rows: Iterable[dict], *, now: datetime) -> list[tuple[str, float, float, float]]:
    """(event_id, consensus_move_pp, book_move_pp, forward_clv_pp) for finished games."""
    grid: dict[tuple, dict[str, dict[str, dict[str, float]]]] = defaultdict(lambda: defaultdict(lambda: defaultdict(dict)))
    for r in rows:
        try:
            commence = _ts(r["commence_time"])
            captured = _ts(r["captured_at"])
            price = _implied(r["price"])
        except Exception:
            continue
        if commence > now or captured >= commence:
            continue
        market = str(r.get("market") or "")
        line = r.get("line")
        try:
            key_line = abs(float(line)) if market.startswith("spreads") and line is not None else line
        except (TypeError, ValueError):
            key_line = line
        group = (r.get("event_id"), market, r.get("segment") or "full", str(r.get("player_name") or ""), key_line)
        grid[group][captured.isoformat()][str(r.get("bookmaker"))][str(r.get("selection") or "").lower()] = price
    out: list[tuple[str, float, float, float]] = []
    for group, caps in grid.items():
        times = sorted(caps)
        if len(times) < 3:
            continue
        consensus: dict[str, dict[str, float]] = {}
        for t in times:
            per_side: dict[str, list[float]] = defaultdict(list)
            for sides in caps[t].values():
                if len(sides) != 2:
                    continue
                total = sum(sides.values())
                if total <= 0:
                    continue
                for side, p in sides.items():
                    per_side[side].append(p / total)
            consensus[t] = {s: statistics.median(v) for s, v in per_side.items() if v}
        first_t = next((t for t in times if consensus.get(t)), None)
        if first_t is None:
            continue
        first_book: dict[tuple[str, str], float] = {}
        close: dict[tuple[str, str], float] = {}
        for t in times:
            for book, sides in caps[t].items():
                for side, p in sides.items():
                    first_book.setdefault((book, side), p)
                    close[(book, side)] = p
        for t in times[1:-1]:
            if not consensus.get(t):
                continue
            for book, sides in caps[t].items():
                for side, p in sides.items():
                    if side not in consensus[t] or side not in consensus[first_t]:
                        continue
                    out.append((
                        str(group[0]),
                        100.0 * (consensus[t][side] - consensus[first_t][side]),
                        100.0 * (p - first_book[(book, side)]),
                        100.0 * (close[(book, side)] - p),
                    ))
    return out


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def contrast(obs: list[tuple[str, float, float, float]], *, seed: int = 20261002) -> dict[str, Any]:
    """Forward CLV by consensus bucket, and toward-minus-against with an event bootstrap."""
    def bucket(o):
        return "toward" if o[1] >= THRESHOLD_PP else "against" if o[1] <= -THRESHOLD_PP else "held"

    by_event: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for o in obs:
        by_event[o[0]][bucket(o)].append(o[3])
    events = list(by_event)
    pooled = {b: [x for e in events for x in by_event[e][b]] for b in ("toward", "held", "against")}
    held = [o for o in obs if bucket(o) == "held"]
    drift_long = [o[3] for o in held if o[2] <= -THRESHOLD_PP]
    drift_short = [o[3] for o in held if o[2] >= THRESHOLD_PP]
    result: dict[str, Any] = {
        "events": len(events),
        "observations": len(obs),
        "forward_clv_pp": {b: _mean(v) for b, v in pooled.items()},
        "n": {b: len(v) for b, v in pooled.items()},
        "single_book_drift_with_consensus_held": {
            "drifted_longer": _mean(drift_long), "n_longer": len(drift_long),
            "shortened": _mean(drift_short), "n_shorter": len(drift_short),
        },
    }
    diff = None
    if pooled["toward"] and pooled["against"]:
        diff = _mean(pooled["toward"]) - _mean(pooled["against"])
    result["toward_minus_against_pp"] = diff
    if diff is None or len(events) < MIN_EVENTS:
        result["ci95"] = None
        result["verdict"] = "insufficient"
        return result
    rng = random.Random(seed)
    draws: list[float] = []
    for _ in range(BOOTSTRAP_DRAWS):
        sample = [by_event[rng.choice(events)] for _ in events]
        toward = [x for e in sample for x in e["toward"]]
        against = [x for e in sample for x in e["against"]]
        if toward and against:
            draws.append(_mean(toward) - _mean(against))
    draws.sort()
    lo, hi = draws[int(0.025 * len(draws))], draws[int(0.975 * len(draws)) - 1]
    result["ci95"] = [round(lo, 3), round(hi, 3)]
    result["verdict"] = "momentum" if lo > 0 else "reversion" if hi < 0 else "no_effect"
    return result


def _data_root() -> Path:
    from syndicate.features.shared.refresh_state_store import data_root

    return Path(data_root())


def _quote_files(root: Path, sport: str, end: date, days: int) -> list[Path]:
    keep = {(end - timedelta(days=i)).isoformat() for i in range(days)}
    return [
        Path(p) for p in sorted(glob.glob(str(root / f"{sport}_source" / "tracking" / "book_quotes" / "*.jsonl")))
        if Path(p).stem in keep
    ]


def run(sports: Iterable[str], *, days: int, now: datetime, root: Path) -> dict[str, Any]:
    report: dict[str, Any] = {
        "generated_at": now.isoformat(timespec="seconds"),
        "window_days": days,
        "threshold_pp": THRESHOLD_PP,
        "min_events": MIN_EVENTS,
        "sports": {},
    }
    for sport in sports:
        obs: list[tuple[str, float, float, float]] = []
        files = _quote_files(root, sport, now.date(), days)
        for path in files:  # one date at a time: a game's captures share its kickoff-date file
            rows = []
            with open(path, encoding="utf-8") as handle:
                for line in handle:
                    try:
                        rows.append(json.loads(line))
                    except Exception:
                        continue
            obs.extend(observations(rows, now=now))
        result = contrast(obs)
        result["files"] = [p.name for p in files]
        report["sports"][sport] = result
    return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--sports", default=",".join(DEFAULT_SPORTS))
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args(argv)
    now = datetime.now(timezone.utc)
    root = _data_root()
    report = run([s.strip() for s in args.sports.split(",") if s.strip()], days=args.days, now=now, root=root)
    out = args.out or root / "reports" / "intelligence" / "movement_by_sport" / f"{now.date().isoformat()}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(report, indent=2), encoding="utf-8")
    os.replace(tmp, out)
    for sport, r in report["sports"].items():
        print(
            f"[movement_by_sport] sport={sport} verdict={r['verdict']} events={r['events']} "
            f"toward_minus_against={r['toward_minus_against_pp']} ci95={r['ci95']} n={r['n']}",
            flush=True,
        )
    print(f"[movement_by_sport] WROTE {out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
