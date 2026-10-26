"""Syndicate Fair v1 -- fit and walk-forward evaluation of a learned, sharpness-weighted fair (OFFLINE research).

Lane `syndicate-fair-v1`, Decision Engine Phase 1 (`#736`, plan `docs/ai_context/plan_syndicate_decision_engine.md`
section 3 L1). The specification, the targets, the gate and every threshold are pre-registered in
`.syndicate/findings_2026-10-26_syndicate_fair_v1_preregistration.md`; this script implements that document and
nothing else. Nothing here is wired into the board, the DecisionRecord or any order path.

THREE STAGES, because the data and the compute live in different places:

  extract   ON THE FLEET (stdlib only, streaming, run at nice 19). Reads `<root>/<sport>_source/tracking/book_quotes`
            (the per-slate change log: one row per (event, book, market, selection, line) price CHANGE) and writes,
            per (line, book, side), the book's latest quote at or before each decision snapshot and at the close.
            Two passes per sport: pass 1 settles each event's final commence time (a game that moved keeps the
            later time) and counts coverage; pass 2 takes the snapshots against that time. Writes
            `<out>/<sport>.snaps.jsonl.gz`, `<out>/<sport>.events.json` and `<out>/coverage.json`.
  outcomes  Fetches final scores from the fleet web's public `/api/board/game-chips` (read-only GET, one call per
            US-Central date) into `<out>/chips/<date>.json`. No OddsAPI call is made anywhere in this script.
  fit       Off the fleet (numpy/scipy; run at Idle priority). Assembles lines, computes both fairs, fits the
            weights walk-forward by date and writes the report the findings are read from.

    nice -n 19 python3 scripts/syndicate_fair_fit.py extract --data-root ~/syndicate-prod/data --out /mnt/c/tmp/sfv1
    py -3 scripts/syndicate_fair_fit.py outcomes --out C:/tmp/sfv1
    py -3 scripts/syndicate_fair_fit.py fit --out C:/tmp/sfv1 --report C:/tmp/sfv1/report.json
"""
from __future__ import annotations

import argparse
import gzip
import json
import math
import os
import re
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping

REPO_ROOT = Path(__file__).resolve().parents[1]

SPORTS = ("mlb", "nba", "wnba", "nhl", "nfl", "ncaaf", "soccer")
#: The pre-registered window: kickoffs from the fleet's first quote day to before the stage-1 cut.
WINDOW_START = "2026-09-30T00:00:00+00:00"
WINDOW_END = "2026-10-26T08:00:00+00:00"
#: Decision snapshots, seconds before commence, then the close (captured_at <= commence).
SNAPSHOTS: tuple[tuple[str, int], ...] = (("t24h", 24 * 3600), ("t6h", 6 * 3600), ("t2h", 2 * 3600), ("t30m", 1800))
CLOSE = "close"
SNAP_NAMES: tuple[str, ...] = tuple(name for name, _ in SNAPSHOTS) + (CLOSE,)
SHARP_BOOK = "pinnacle"

_EVENT_RE = re.compile(r'"event_id"\s*:\s*"([^"]*)"')


# ----------------------------------------------------------------------------- shared helpers (stdlib)


def epoch(value: Any) -> int | None:
    """ISO-8601 (any offset, or Z) -> whole epoch seconds; None when unparseable."""
    try:
        d = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return int(d.timestamp())


def utc_date(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).date().isoformat()


def _num(value: Any) -> float | None:
    """A finite float, else None. NaN is None: the NBA/WNBA/NHL h2h and yes/no rows carry `"line": NaN`, and NaN
    never equals itself, so as a key part it made every quote row its own line (667,804 NHL h2h "lines" for 179
    events before this)."""
    try:
        out = None if value is None else float(value)
    except (TypeError, ValueError):
        return None
    return None if out is None or math.isnan(out) or math.isinf(out) else out


def line_key(market: Any, segment: Any, player: Any, side: Any, line: Any) -> tuple[str, str, str, float | None]:
    """(market, segment, player, line) with both sides of one bet on ONE key: spreads framed on the HOME line.

    The same identity `scripts/fair_price_eval.py::group_key` builds (minus the event), re-stated here because this
    stage must run on the fleet's bare python3 with no repo imports; `tests/test_syndicate_fair_fit.py` pins the two
    together.
    """
    m = str(market or "").strip().lower()
    seg = str(segment or "full").strip().lower() or "full"
    pl = str(player or "").strip().casefold()
    sd = str(side or "").strip().lower()
    ln = _num(line)
    if ln is not None and ("spread" in m or "handicap" in m) and sd == "away":
        ln = -ln
    return (m, seg, pl, None if ln is None else round(ln, 3))


def quote_files(data_root: Path, sport: str) -> list[Path]:
    directory = data_root / f"{sport}_source" / "tracking" / "book_quotes"
    if not directory.is_dir():
        return []
    return sorted(p for p in directory.iterdir()
                  if p.name.endswith((".jsonl", ".jsonl.gz")) and not p.name.startswith("."))


def iter_rows(path: Path) -> Iterator[dict]:
    opener = gzip.open if path.suffix == ".gz" else open
    try:
        with opener(path, "rt", encoding="utf-8") as fh:
            for raw in fh:
                try:
                    yield json.loads(raw)
                except ValueError:
                    continue
    except (OSError, EOFError) as exc:  # a file being appended to, or a truncated gzip, is read as far as it goes
        print(f"READ_ERROR {path.name} {type(exc).__name__}", flush=True)


# ----------------------------------------------------------------------------- stage 1: extract (fleet)


def snapshot_targets(commence: int) -> list[int]:
    """Epoch cut-offs, in SNAP_NAMES order: each decision snapshot, then the close (= commence)."""
    return [commence - offset for _, offset in SNAPSHOTS] + [commence]


def update_snaps(snaps: list, targets: list[int], captured: int, price: Any) -> None:
    """Keep, per cut-off, the quote with the latest captured_at at or before it (a change log: the price stands)."""
    for i, cut in enumerate(targets):
        if captured <= cut:
            held = snaps[i]
            if held is None or captured >= held[0]:
                snaps[i] = [captured, price]


def extract_sport(data_root: Path, sport: str, start: int, end: int,
                  flush: Any = None) -> tuple[dict, dict, dict]:
    """(events, snaps, coverage) for one sport. See the module docstring for the two passes.

    With `flush(snaps)`, the snapshots are handed over and dropped after EACH FILE, so memory is bounded by the
    largest file rather than the sport (the fleet's VM is production's). A key can then appear once per file it was
    quoted in; `merge_snaps` takes the latest quote per cut-off across them, which is the same answer.
    """
    files = quote_files(data_root, sport)
    events: dict[str, dict] = {}
    for path in files:  # pass 1: each event's commence time as of its LAST quote, and its teams
        for q in iter_rows(path):
            ev, cap, ct = q.get("event_id"), epoch(q.get("captured_at")), epoch(q.get("commence_time"))
            if not ev or cap is None or ct is None:
                continue
            held = events.get(ev)
            if held is None or cap >= held["cap"]:
                events[ev] = {"cap": cap, "commence": ct, "home": q.get("home_team"), "away": q.get("away_team"),
                              "date": q.get("date")}
    events = {ev: e for ev, e in events.items() if start <= e["commence"] < end}
    snaps: dict[tuple, list] = {}
    cov_rows: dict[str, int] = defaultdict(int)
    cov_books: dict[str, set] = defaultdict(set)
    cov_sharp_events: dict[str, set] = defaultdict(set)
    cov_markets: dict[str, int] = defaultdict(int)
    n_keys = 0
    for path in files:  # pass 2: the snapshots, against the settled commence time
        for q in iter_rows(path):
            ev = q.get("event_id")
            e = events.get(ev)
            if e is None:
                continue
            cap = epoch(q.get("captured_at"))
            if cap is None or cap > e["commence"]:
                continue  # in-play, or after the close
            side = str(q.get("selection") or "").strip().lower()
            book = str(q.get("bookmaker") or "").strip().lower()
            if not side or not book or q.get("price") is None:
                continue
            kind = "prop" if (q.get("kind") == "prop" or q.get("player_name")) else "game"
            m, seg, pl, ln = line_key(q.get("market"), q.get("segment"), q.get("player_name"), side, q.get("line"))
            lk = (sys.intern(m), sys.intern(seg), sys.intern(pl), ln)
            key = (sys.intern(ev), *lk, sys.intern(book), sys.intern(side), sys.intern(kind))
            held = snaps.get(key)
            if held is None:
                held = snaps[key] = [None] * len(SNAP_NAMES)
            update_snaps(held, snapshot_targets(e["commence"]), cap, q.get("price"))
            day = utc_date(e["commence"])
            cov_rows[day] += 1
            cov_books[day].add(book)
            if book == SHARP_BOOK and kind == "game":
                cov_sharp_events[day].add(ev)
            cov_markets[f"{kind}|{lk[0]}|{lk[1]}"] += 1
        if flush is not None:
            n_keys += len(snaps)
            flush(snaps)
            snaps = {}
    n_keys += len(snaps)
    by_day: dict[str, dict] = {}
    events_by_day: dict[str, set] = defaultdict(set)
    for ev, e in events.items():
        events_by_day[utc_date(e["commence"])].add(ev)
    for day in sorted(set(events_by_day) | set(cov_rows)):
        by_day[day] = {"events": len(events_by_day.get(day, ())), "quote_rows": cov_rows.get(day, 0),
                       "books": len(cov_books.get(day, ())), "pinnacle_game_events": len(cov_sharp_events.get(day, ()))}
    coverage = {"files": len(files), "events": len(events), "keys": n_keys, "by_day": by_day,
                "markets": dict(sorted(cov_markets.items(), key=lambda kv: -kv[1]))}
    return events, snaps, coverage


def snap_records(snaps: Mapping[tuple, list]) -> Iterator[str]:
    for (ev, m, seg, pl, ln, book, side, kind), s in snaps.items():
        yield json.dumps({"e": ev, "m": m, "sg": seg, "pl": pl, "ln": ln, "b": book, "sd": side, "k": kind, "s": s},
                         separators=(",", ":")) + "\n"


def merge_snaps(records: Iterable[Mapping[str, Any]]) -> dict[tuple, list]:
    """Records from several files -> one snapshot list per key: the latest captured_at per cut-off wins."""
    merged: dict[tuple, list] = {}
    for r in records:
        key = (r["e"], r["m"], r["sg"], r["pl"], r["ln"], r["b"], r["sd"], r["k"])
        held = merged.get(key)
        if held is None:
            merged[key] = list(r["s"])
            continue
        for i, q in enumerate(r["s"]):
            if q is not None and (held[i] is None or q[0] >= held[i][0]):
                held[i] = q
    return merged


def cmd_extract(args: argparse.Namespace) -> int:
    root = Path(os.path.expanduser(args.data_root))
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    start, end = epoch(args.start), epoch(args.end)
    coverage: dict[str, Any] = {"window": [args.start, args.end], "data_root": str(root), "sports": {}}
    for sport in args.sports.split(","):
        t0 = time.time()
        with gzip.open(out / f"{sport}.snaps.jsonl.gz", "wt", encoding="utf-8") as fh:
            events, _, cov = extract_sport(root, sport, start, end, flush=lambda s: fh.writelines(snap_records(s)))
        (out / f"{sport}.events.json").write_text(json.dumps(events, sort_keys=True), encoding="utf-8")
        coverage["sports"][sport] = cov
        print(f"EXTRACT {sport} files={cov['files']} events={cov['events']} keys={cov['keys']} "
              f"secs={time.time() - t0:.0f}", flush=True)
        del events
    (out / "coverage.json").write_text(json.dumps(coverage, indent=1, sort_keys=True), encoding="utf-8")
    return 0


# ----------------------------------------------------------------------------- stage 2: outcomes (fleet web, GET)


def _load_script(name: str) -> Any:
    import importlib.util

    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def central_dates(start: int, end: int) -> list[str]:
    """Every US-Central date a kickoff in [start, end) can carry (the scoreboard is keyed by it)."""
    first = datetime.fromtimestamp(start, tz=timezone.utc) - timedelta(hours=6)
    last = datetime.fromtimestamp(end, tz=timezone.utc) - timedelta(hours=5)
    day, out = first.date(), []
    while day <= last.date():
        out.append(day.isoformat())
        day += timedelta(days=1)
    return out


def cmd_outcomes(args: argparse.Namespace) -> int:
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    sc = _load_script("layer2_live_scorecard")
    chips_dir = Path(args.out) / "chips"
    chips_dir.mkdir(parents=True, exist_ok=True)
    for day in central_dates(epoch(args.start), epoch(args.end)):
        target = chips_dir / f"{day}.json"
        if target.exists() and not args.refresh:
            continue
        chips = sc.fetch_chips(args.base_url, day, None)
        target.write_text(json.dumps({"chips": chips}), encoding="utf-8")
        finals = sum(1 for c in chips if str(c.get("state") or "").lower() == "final")
        print(f"CHIPS {day} chips={len(chips)} final={finals}", flush=True)
    return 0


# ----------------------------------------------------------------------------- stage 3: fit (pre-registered)
#
# Every constant below is fixed by the pre-registration; changing one is a new registration, not a re-run.

MIN_BOOKS = 2                 # two-sided books at the snapshot, for a line to be scored at all
MIN_TRAIN_DATES = 5           # UTC commence dates with a close target before a family is first fitted
MIN_TRAIN_GAMES = 30
INNER_VAL_DATES = 2           # the last N training dates choose lambda
LAMBDA_GRID: tuple[float, ...] = (1e-5, 1e-4, 1e-3, 1e-2)
MAX_ITER = 300
MIN_GATE_GAMES = 30           # held-out games for a family verdict
MIN_GATE_DATES = 3            # held-out test dates for a family verdict
BOOT_B = 2000
SEED = 20261026
SIGMA_BAND = (0.60, 0.76)     # 1-sigma coverage read as calibrated (nominal 0.683)
GRADED_FAMILIES = ("h2h", "spreads", "totals")  # full-game markets a final score settles
ENGINE_MIN_ROWS = 200
CANONICAL_ORDERS: tuple[tuple[str, ...], ...] = (("home", "away", "draw"), ("home", "away"), ("over", "under"),
                                                  ("yes", "no"))


def canonical_sides(sides: Iterable[str]) -> tuple[str, ...] | None:
    """The line's outcome set in a fixed order (outcome 0 = home / over / yes), or None when it is not one."""
    s = set(sides)
    if s == {"home", "away", "draw"}:
        return CANONICAL_ORDERS[0]
    for order in CANONICAL_ORDERS[1:]:
        if s == set(order):
            return order
    return None


class Devig:
    """Production's per-book de-vig (`opportunity_signals.devig`), memoised on the price tuple."""

    def __init__(self) -> None:
        if str(REPO_ROOT) not in sys.path:
            sys.path.insert(0, str(REPO_ROOT))
        from syndicate.features.shared.opportunity_signals import devig

        self._devig = devig
        self._cache: dict[tuple, tuple | None] = {}

    def __call__(self, prices: Iterable[Any], method: str) -> tuple | None:
        key = (method, tuple(prices))
        if key not in self._cache:
            out = self._devig(list(key[1]), method=method)
            self._cache[key] = None if out is None else tuple(out)
        return self._cache[key]


def shin_median(per_book: Mapping[str, Iterable[float]], k: int) -> list[float]:
    """The board's consensus from per-book Shin vectors: the median per outcome, renormalised
    (`opportunity_signals.consensus_fair_probability`; parity with `layer2_board._consensus_fair` is checked live)."""
    import statistics

    med = [statistics.median(p[j] for p in per_book.values()) for j in range(k)]
    total = sum(med)
    return [m / total for m in med]


def iso(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def assemble_sport(out: Path, sport: str, chips_by_date: Mapping[str, list], *, parity_every: int = 50) -> tuple[list, dict]:
    """(rows, counters) for one sport: one row per (line, decision snapshot) with >= MIN_BOOKS de-viggable books."""
    from syndicate.features.shared import layer2_board, season_phase, syndicate_fair as sf

    sc = _load_script("layer2_live_scorecard")
    devig = Devig()
    events = json.loads((out / f"{sport}.events.json").read_text(encoding="utf-8"))
    with gzip.open(out / f"{sport}.snaps.jsonl.gz", "rt", encoding="utf-8") as fh:
        merged = merge_snaps(json.loads(line) for line in fh)
    lines: dict[tuple, dict[str, dict[str, list]]] = defaultdict(lambda: defaultdict(dict))
    for (ev, m, seg, pl, ln, book, side, kind), s in merged.items():
        lines[(ev, m, seg, pl, ln, kind)][book][side] = s
    del merged
    chips_index = {day: sc.index_chips(chips) for day, chips in chips_by_date.items()}
    counters: dict[str, int] = defaultdict(int)
    rows: list[dict] = []
    for (ev, m, seg, pl, ln, kind), by_book in lines.items():
        e = events.get(ev)
        sides = canonical_sides({sd for sides_map in by_book.values() for sd in sides_map})
        if e is None or sides is None:
            counters["lines_not_two_sided_or_unknown"] += 1
            continue
        commence, k = int(e["commence"]), len(sides)
        cdate = sc.central_date(iso(commence))
        phase = season_phase.season_phase(sport, cdate)
        if phase is None:
            counters["lines_phase_unknown"] += 1
            continue
        mfam = sf.market_family(m, seg, kind)
        # -- the close: each book's last pregame pair, if it was quoted within MAX_AGE_S of the start
        close_prices: dict[str, list] = {}
        for book, sm in by_book.items():
            quotes = [sm.get(sd, [None] * len(SNAP_NAMES))[-1] for sd in sides]
            if all(q is not None for q in quotes) and commence - max(q[0] for q in quotes) <= sf.MAX_AGE_S:
                close_prices[book] = [q[1] for q in quotes]
        sharp = None
        if SHARP_BOOK in close_prices:
            sharp = devig(close_prices[SHARP_BOOK], "power")  # the board's sharp-anchor de-vig (_ANCHOR_DEVIG_METHOD)
        close_shin = {b: p for b, prices in close_prices.items() if (p := devig(prices, "shin")) is not None}
        cons_close = shin_median(close_shin, k) if len(close_shin) >= MIN_BOOKS else None
        target, src = (list(sharp), "sharp") if sharp is not None else ((cons_close, "consensus") if cons_close else (None, None))
        # -- the outcome, for full-game lines a final score settles
        outcome = None
        if kind == "game" and mfam in GRADED_FAMILIES:
            chip, _why = sc.match_chip({"sport": sport, "home_team": e.get("home"), "away_team": e.get("away")},
                                       chips_index.get(cdate, {}).get(sport, []))
            if chip is not None and chip["state"] == "final" and chip["scores"] is not None:
                away, home = chip["scores"]
                results = []
                for sd in sides:
                    line_for_side = None if ln is None else (-ln if (mfam == "spreads" and sd == "away") else ln)
                    results.append(sc.grade({"market": m, "side": sd, "line": line_for_side, "sport": sport}, away, home))
                if results.count("win") == 1 and all(r in ("win", "loss") for r in results):
                    outcome = [1.0 if r == "win" else 0.0 for r in results]
                else:
                    counters["outcome_push_or_unsettled"] += 1
            else:
                counters["outcome_no_final_chip"] += 1
        # -- one row per decision snapshot
        for i, (tts, offset) in enumerate(SNAPSHOTS):
            t_snap = commence - offset
            books_here, prices_here = [], {}
            for book, sm in by_book.items():
                quotes = [sm.get(sd, [None] * len(SNAP_NAMES))[i] for sd in sides]
                if any(q is None for q in quotes):
                    continue
                age = t_snap - max(q[0] for q in quotes)
                if age > sf.MAX_AGE_S:
                    continue
                probs = devig([q[1] for q in quotes], "shin")
                if probs is None:
                    continue
                books_here.append((book, float(age), list(probs)))
                prices_here[book] = [q[1] for q in quotes]
            if len(books_here) < MIN_BOOKS:
                counters["rows_under_min_books"] += 1
                continue
            base = shin_median({b: p for b, _, p in books_here}, k)
            counters["rows"] += 1
            if parity_every and counters["rows"] % parity_every == 0:
                cells = {b: {sd: {"price": pr} for sd, pr in zip(sides, prices)} for b, prices in prices_here.items()}
                prod = layer2_board._consensus_fair(cells, list(sides), method="shin")
                counters["parity_checked"] += 1
                if not prod or max(abs(prod[sd] - base[j]) for j, sd in enumerate(sides)) > 1e-9:
                    counters["parity_mismatch"] += 1
            rows.append({"sport": sport, "phase": phase, "kind": kind, "family": f"{sport}|{phase}|{kind}",
                         "ev": ev, "line": f"{m}|{seg}|{pl}|{ln}", "mfam": mfam, "tts": tts, "commence": commence,
                         "date": utc_date(commence), "k": k, "books": books_here, "base": base,
                         "target": target, "src": src, "cons_close": cons_close,
                         "sharp_close": None if sharp is None else list(sharp), "y": outcome})
    counters["lines"] = len(lines)
    return rows, dict(counters)


def cluster_boot(values: Any, clusters: Any, *, B: int = BOOT_B, seed: int = SEED,
                 levels: tuple[float, ...] = (0.95,)) -> dict[str, Any]:
    """Mean of `values` with percentile CIs from resampling CLUSTERS (games) with replacement."""
    import numpy as np

    values = np.asarray(values, dtype=float)
    keys, inv = np.unique(np.asarray(clusters), return_inverse=True)
    sums = np.bincount(inv, weights=values, minlength=len(keys))
    counts = np.bincount(inv, minlength=len(keys)).astype(float)
    out: dict[str, Any] = {"mean": float(values.mean()) if len(values) else None, "n": int(len(values)),
                           "games": int(len(keys))}
    if len(keys) < 5:
        return out
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(keys), size=(B, len(keys)))
    boots = sums[idx].sum(axis=1) / counts[idx].sum(axis=1)
    for level in levels:
        lo, hi = np.quantile(boots, [(1 - level) / 2, 1 - (1 - level) / 2])
        out[f"ci{level:g}"] = [float(lo), float(hi)]
    return out


def walk_forward(rows: list[dict], log: Any = print) -> dict[str, Any]:
    """Refit at every test date on everything that closed before it; predict that date. Returns arrays + fit log."""
    import numpy as np
    from syndicate.features.shared import syndicate_fair as sf

    books = sorted({b for r in rows for b, _, _ in r["books"]})
    for r in rows:
        r["_t"] = r["target"] if r["target"] is not None else [0.0] * r["k"]
    ds = sf.build_dataset(rows, books, target_key="_t")
    dates = np.array([r["date"] for r in rows])
    commence = np.array([r["commence"] for r in rows])
    games = np.array([r["ev"] for r in rows])
    has_close = np.array([r["target"] is not None for r in rows])
    n = len(rows)
    p_v1 = np.full((n, 3), np.nan)
    p_eq = np.full((n, 3), np.nan)
    sigma = np.full((n, 3), np.nan)
    fits, model, warm_inner, warm_full = [], None, {}, {}
    eq_model = sf.WeightModel(books)
    for d in sorted(set(dates)):
        cutoff = epoch(f"{d}T00:00:00+00:00") - 86400
        train = has_close & (commence < cutoff)
        t_dates = sorted(set(dates[train]))
        if len(t_dates) < MIN_TRAIN_DATES or len(set(games[train])) < MIN_TRAIN_GAMES:
            continue
        val = train & np.isin(dates, t_dates[-INNER_VAL_DATES:])
        inner = train & ~val
        ds_inner, ds_val, ds_train = ds.subset(inner), ds.subset(val), ds.subset(train)
        scores = {}
        for lam in LAMBDA_GRID:
            m = sf.WeightModel(books)
            sf.fit(m, ds_inner, lam, max_iter=MAX_ITER, warm=warm_inner.get(lam))
            warm_inner[lam] = m.theta
            scores[lam] = float(sf.cross_entropy(sf.predict(m, ds_val)[0], ds_val.target, ds_val.mask).mean())
        lam = min(scores, key=scores.get)
        model = sf.WeightModel(books)
        info = sf.fit(model, ds_train, lam, max_iter=MAX_ITER, warm=warm_full.get(lam))
        warm_full[lam] = model.theta
        p_tr, pi_tr = sf.predict(model, ds_train)
        r2 = sf.fit_residual_var(ds_train, p_tr, pi_tr)
        test = np.flatnonzero(dates == d)
        ds_test = ds.subset(test)
        p, pi = sf.predict(model, ds_test)
        p_v1[test] = p
        sigma[test] = sf.sigma_fair(ds_test, p, pi, r2)
        p_eq[test] = sf.predict(eq_model, ds_test)[0]
        fits.append({"test_date": d, "train_rows": int(train.sum()), "train_dates": len(t_dates),
                     "train_games": len(set(games[train])), "lambda": lam,
                     "inner_val_ce": {f"{k:g}": round(v, 6) for k, v in scores.items()},
                     "iters": info["iters"], "converged": info["converged"], "test_rows": int(len(test)),
                     "r2": {f"{sf.MARKET_FAMILIES[m_]}|{sf.TTS_BUCKETS[t_]}": round(v, 5) for (m_, t_), v in r2.items()}})
        log(f"  FIT {d} train_rows={int(train.sum())} dates={len(t_dates)} lam={lam:g} iters={info['iters']} "
            f"conv={info['converged']} test_rows={len(test)}")
    return {"books": books, "ds": ds, "p_v1": p_v1, "p_eq": p_eq, "sigma": sigma, "fits": fits, "model": model}


def _ce(p: Any, t: Any, k: Any) -> Any:
    import numpy as np

    mask = np.arange(3)[None, :] < np.asarray(k)[:, None]
    return -np.where(mask, np.asarray(t) * np.log(np.clip(p, 1e-6, 1 - 1e-6)), 0.0).sum(axis=1)


def _pad(vectors: Iterable[Any]) -> Any:
    import numpy as np

    return np.array([list(v) + [0.0] * (3 - len(v)) for v in vectors], dtype=float).reshape(-1, 3)


def evaluate_family(rows: list[dict], wf: Mapping[str, Any], n_families: int) -> dict[str, Any]:
    """The pre-registered reads for one family, on its held-out (walk-forward) rows."""
    import numpy as np
    from syndicate.features.shared import syndicate_fair as sf

    scored = ~np.isnan(wf["p_v1"][:, 0])
    k = np.array([r["k"] for r in rows])
    games = np.array([r["ev"] for r in rows])
    dates = np.array([r["date"] for r in rows])
    base = _pad(r["base"] for r in rows)
    bonf = 1 - 0.05 / max(n_families, 1)
    levels = (0.95, round(bonf, 6))
    out: dict[str, Any] = {"rows_total": len(rows), "rows_scored": int(scored.sum()),
                           "test_dates": sorted(set(dates[scored])), "games_scored": int(len(set(games[scored])))}
    # G1: the close target
    has_t = scored & np.array([r["target"] is not None for r in rows])
    if has_t.any():
        T = _pad(r["target"] if r["target"] is not None else [0.0] * r["k"] for r in rows)
        d1 = _ce(wf["p_v1"], T, k) - _ce(base, T, k)
        d_eq = _ce(wf["p_eq"], T, k) - _ce(base, T, k)
        out["g1_close"] = cluster_boot(d1[has_t], games[has_t], levels=levels)
        out["g1_close"]["ce_shin"] = float(_ce(base, T, k)[has_t].mean())
        out["g1_close"]["ce_v1"] = float(_ce(wf["p_v1"], T, k)[has_t].mean())
        out["g1_close"]["test_dates"] = len(set(dates[has_t]))
        out["ref_equal_weight_pool_close"] = cluster_boot(d_eq[has_t], games[has_t])
        src = np.array([r["src"] or "" for r in rows])
        out["g1_by_target_source"] = {s: cluster_boot(d1[has_t & (src == s)], games[has_t & (src == s)])
                                      for s in ("sharp", "consensus") if (has_t & (src == s)).any()}
        tts = np.array([r["tts"] for r in rows])
        out["g1_by_tts"] = {t: cluster_boot(d1[has_t & (tts == t)], games[has_t & (tts == t)])
                            for t in sf.TTS_BUCKETS if (has_t & (tts == t)).any()}
        mf = np.array([r["mfam"] for r in rows])
        out["g1_by_mfam"] = {m: cluster_boot(d1[has_t & (mf == m)], games[has_t & (mf == m)])
                             for m in sf.MARKET_FAMILIES if (has_t & (mf == m)).any()}
        # sigma calibration on held-out closes
        ds_t = wf["ds"].subset(np.flatnonzero(has_t))
        p_t, sig_t = wf["p_v1"][has_t], wf["sigma"][has_t]
        in1, nsc = sf.sigma_coverage(ds_t, p_t, sig_t, 1.0)
        in2, _ = sf.sigma_coverage(ds_t, p_t, sig_t, 2.0)
        use = sf.scored_outcomes(ds_t.mask)
        sig_pp = (sig_t * p_t * (1 - p_t))[use]
        out["sigma"] = {"scored": nsc, "inside_1sigma": round(in1 / nsc, 4) if nsc else None,
                        "inside_2sigma": round(in2 / nsc, 4) if nsc else None,
                        "median_sigma_logit": float(np.median(sig_t[use])) if nsc else None,
                        "median_sigma_pp": float(100 * np.median(sig_pp)) if nsc else None,
                        "calibrated_1sigma": bool(nsc and SIGMA_BAND[0] <= in1 / nsc <= SIGMA_BAND[1])}
    # G2: the outcome (harm guard)
    has_y = scored & np.array([r["y"] is not None for r in rows])
    if has_y.any():
        Y = _pad(r["y"] if r["y"] is not None else [0.0] * r["k"] for r in rows)
        d2 = _ce(wf["p_v1"], Y, k) - _ce(base, Y, k)
        out["g2_outcome"] = cluster_boot(d2[has_y], games[has_y])
        out["g2_outcome"]["ce_shin"] = float(_ce(base, Y, k)[has_y].mean())
        out["g2_outcome"]["ce_v1"] = float(_ce(wf["p_v1"], Y, k)[has_y].mean())
    out["verdict"] = verdict(out)
    return out


def verdict(result: Mapping[str, Any]) -> str:
    """The pre-registered family verdict. Never pooled: one family, one verdict."""
    g1 = result.get("g1_close") or {}
    if (g1.get("games") or 0) < MIN_GATE_GAMES or (g1.get("test_dates") or 0) < MIN_GATE_DATES or "ci0.95" not in g1:
        return "UNDERPOWERED"
    g2 = result.get("g2_outcome") or {}
    if "ci0.95" in g2 and (g2.get("games") or 0) >= MIN_GATE_GAMES and g2["ci0.95"][0] > 0:
        return "FAIL (worse on outcomes)"
    if g1["ci0.95"][1] >= 0:
        return "FAIL"
    if "ci0.95" in g2 and (g2.get("games") or 0) >= MIN_GATE_GAMES:
        return "PASS"
    return "PASS (outcome unmeasured)"


def engine_read(rows: list[dict], *, target: str) -> dict[str, Any]:
    """Which books LEAD the close: per book x snapshot, beta = sum(x y) / sum(x x) on two-way lines, with
    x = logit(book) - logit(consensus now) and y = logit(close) - logit(consensus now). beta = 1: the close moves
    all the way to the book; 0: the book's disagreement is noise. Descriptive, in-sample, all rows of the family."""
    import numpy as np
    from syndicate.features.shared import syndicate_fair as sf

    acc: dict[tuple[str, str], list] = defaultdict(lambda: [[], [], []])
    for r in rows:
        t = r.get(target)
        if r["k"] != 2 or t is None:
            continue
        c = float(sf.logit(r["base"][0]))
        y = float(sf.logit(t[0])) - c
        for b, _age, p in r["books"]:
            cell = acc[(b, r["tts"])]
            cell[0].append(float(sf.logit(p[0])) - c)
            cell[1].append(y)
            cell[2].append(r["ev"])
    out: dict[str, Any] = {}
    for (b, tts), (xs, ys, gs) in sorted(acc.items()):
        if len(xs) < ENGINE_MIN_ROWS:
            continue
        x, y = np.asarray(xs), np.asarray(ys)
        sxx = float((x * x).sum())
        if sxx <= 0:
            continue
        keys, inv = np.unique(np.asarray(gs), return_inverse=True)
        sxy_g = np.bincount(inv, weights=x * y, minlength=len(keys))
        sxx_g = np.bincount(inv, weights=x * x, minlength=len(keys))
        rng = np.random.default_rng(SEED)
        idx = rng.integers(0, len(keys), size=(500, len(keys)))
        den = sxx_g[idx].sum(axis=1)
        boots = sxy_g[idx].sum(axis=1) / np.where(den > 0, den, np.nan)
        lo, hi = np.nanquantile(boots, [0.025, 0.975])
        out.setdefault(b, {})[tts] = {"beta": round(float((x * y).sum() / sxx), 3), "ci95": [round(float(lo), 3), round(float(hi), 3)],
                                      "rows": len(xs), "games": len(keys),
                                      "mean_abs_dev_pp": round(float(np.mean(np.abs(x))) * 25, 3)}
    return out


def weights_report(model: Any, rows: list[dict]) -> dict[str, Any]:
    """The final fit's relative weights (1.0 = an equal vote), per market family x snapshot present in the family."""
    from syndicate.features.shared import syndicate_fair as sf

    if model is None:
        return {}
    present = sorted({(r["mfam"], r["tts"]) for r in rows})
    out: dict[str, Any] = {}
    for mfam, tts in present:
        table = model.weights_table(mfam, tts, sf.AGE_BUCKETS[0])
        out[f"{mfam}|{tts}"] = {b: round(w, 3) for b, w in sorted(table.items(), key=lambda kv: -kv[1])}
    age = {a: round(float(model.theta[model.offsets["a"] + i]), 3) for i, a in enumerate(sf.AGE_BUCKETS)}
    return {"by_cell_at_age_lt15m": out, "age_log_weight": age}


def cmd_fit(args: argparse.Namespace) -> int:
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    out = Path(args.out)
    chips_by_date = {}
    for path in sorted((out / "chips").glob("????-??-??.json")):
        chips_by_date[path.stem] = json.loads(path.read_text(encoding="utf-8")).get("chips") or []
    by_family: dict[str, list] = defaultdict(list)
    assembly: dict[str, Any] = {}
    for sport in args.sports.split(","):
        rows, counters = assemble_sport(out, sport, chips_by_date)
        assembly[sport] = counters
        print(f"ASSEMBLE {sport} {json.dumps(counters, sort_keys=True)}", flush=True)
        for r in rows:
            by_family[r["family"]].append(r)
    coverage = {}
    for fam, rs in sorted(by_family.items()):
        dates = {r["date"] for r in rs}
        d_close = {r["date"] for r in rs if r["target"] is not None}
        d_sharp = {r["date"] for r in rs if r["src"] == "sharp"}
        d_y = {r["date"] for r in rs if r["y"] is not None}
        coverage[fam] = {"rows": len(rs), "games": len({r["ev"] for r in rs}), "dates": sorted(dates),
                         "rows_with_sharp_close": sum(1 for r in rs if r["src"] == "sharp"),
                         "rows_with_consensus_close": sum(1 for r in rs if r["src"] == "consensus"),
                         "rows_with_outcome": sum(1 for r in rs if r["y"] is not None),
                         "dates_close": sorted(d_close), "dates_sharp": sorted(d_sharp), "dates_outcome": sorted(d_y),
                         "dates_close_and_outcome": sorted(d_close & d_y), "dates_sharp_and_outcome": sorted(d_sharp & d_y)}
    for fam, c in coverage.items():
        print(f"FAMILY {fam} rows={c['rows']} games={c['games']} dates={len(c['dates'])} sharp={c['rows_with_sharp_close']} "
              f"consensus={c['rows_with_consensus_close']} outcome={c['rows_with_outcome']} | dates close={len(c['dates_close'])} "
              f"sharp={len(c['dates_sharp'])} outcome={len(c['dates_outcome'])} close&outcome={len(c['dates_close_and_outcome'])} "
              f"sharp&outcome={len(c['dates_sharp_and_outcome'])}", flush=True)
    if args.coverage_only:
        Path(args.report).write_text(json.dumps({"assembly": assembly, "families": coverage}, indent=1), encoding="utf-8")
        return 0
    gated = [f for f in by_family if f.split("|")[1] != "preseason"]
    report: dict[str, Any] = {"assembly": assembly, "families": {}, "constants": {
        "MIN_BOOKS": MIN_BOOKS, "MIN_TRAIN_DATES": MIN_TRAIN_DATES, "MIN_TRAIN_GAMES": MIN_TRAIN_GAMES,
        "INNER_VAL_DATES": INNER_VAL_DATES, "LAMBDA_GRID": LAMBDA_GRID, "MIN_GATE_GAMES": MIN_GATE_GAMES,
        "MIN_GATE_DATES": MIN_GATE_DATES, "BOOT_B": BOOT_B, "SEED": SEED, "SIGMA_BAND": SIGMA_BAND,
        "families_gated": len(gated)}}
    for fam in sorted(by_family):
        rows = sorted(by_family[fam], key=lambda r: r["commence"])
        print(f"WALK {fam} rows={len(rows)}", flush=True)
        t0 = time.time()
        wf = walk_forward(rows, log=lambda s: print(s, flush=True))
        result = evaluate_family(rows, wf, len(gated))
        if fam not in gated:
            result["verdict"] = "NOT GATED (preseason)"
        result["coverage"] = coverage[fam]
        result["fits"] = wf["fits"]
        result["weights"] = weights_report(wf["model"], rows)
        result["engine_read_vs_target"] = engine_read(rows, target="target")
        result["engine_read_vs_consensus_close"] = engine_read(rows, target="cons_close")
        result["secs"] = round(time.time() - t0, 1)
        report["families"][fam] = result
        g1, g2 = result.get("g1_close") or {}, result.get("g2_outcome") or {}
        print(f"RESULT {fam} verdict={result['verdict']} g1={g1.get('mean')} ci={g1.get('ci0.95')} games={g1.get('games')} "
              f"g2={g2.get('mean')} ci={g2.get('ci0.95')} sigma1={(result.get('sigma') or {}).get('inside_1sigma')}",
              flush=True)
        Path(args.report).write_text(json.dumps(report, indent=1, default=str), encoding="utf-8")
    return 0


# ----------------------------------------------------------------------------- driver


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    ex = sub.add_parser("extract", help="fleet side: book_quotes -> per-(line, book, side) snapshots")
    ex.add_argument("--data-root", default=os.environ.get("SYNDICATE_DATA_ROOT") or "~/syndicate-prod/data")
    ex.add_argument("--out", required=True)
    ex.add_argument("--sports", default=",".join(SPORTS))
    ex.add_argument("--start", default=WINDOW_START)
    ex.add_argument("--end", default=WINDOW_END)
    ex.set_defaults(func=cmd_extract)
    oc = sub.add_parser("outcomes", help="final scores from the fleet web's public game-chips endpoint")
    oc.add_argument("--out", required=True)
    oc.add_argument("--base-url", default=os.environ.get("SYNDICATE_BASE_URL") or "http://127.0.0.1:10000")
    oc.add_argument("--start", default=WINDOW_START)
    oc.add_argument("--end", default=WINDOW_END)
    oc.add_argument("--refresh", action="store_true")
    oc.set_defaults(func=cmd_outcomes)
    ft = sub.add_parser("fit", help="assemble, walk-forward fit, and the pre-registered reads")
    ft.add_argument("--out", required=True)
    ft.add_argument("--report", required=True)
    ft.add_argument("--sports", default=",".join(SPORTS))
    ft.add_argument("--coverage-only", action="store_true", help="assemble and print family coverage; fit nothing")
    ft.set_defaults(func=cmd_fit)
    args = ap.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
