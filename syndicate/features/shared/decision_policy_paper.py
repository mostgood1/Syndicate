"""Decision policy v1's PAPER BOOK: book from each heavy build's DecisionRecord, grade on the sharp close, read the gate.

Lane `decision-policy-paper`, Decision Engine Phase 2 (`#736`). Pre-registration:
`.syndicate/findings_2026-10-26_decision_policy_v1_preregistration.md` (`8d16ab07`); the policy itself is
`decision_policy_v1`. **PAPER ONLY: no order module is imported here or in the policy (a test pins it), and
nothing reads this book for placement, sizing or the board.**

PIPELINE (file:line at commit time is in the findings; the shape is):

    refresh-worker heavy build -> decision_record.run_shadow -> <root>/reports/intelligence/decision_records/<date>.json.gz
    scripts/run_decision_policy_paper.py book  (every 15 min)
      -> run_book: every record file written in the last LOOKBACK_S, newest build per date not yet processed
         -> sigma per record: record.fair_v1.sigma_fair_v1 (S1) | book-grid dispersion (S2) | inflated (S3)
         -> decision_policy_v1.evaluate per (record, venue) -> select per strategy per (event, axis)
         -> APPENDS <root>/reports/intelligence/decision_policy_paper/bets.jsonl (first qualification only)
         -> APPENDS builds.jsonl (one line per processed build)
    scripts/run_decision_policy_paper.py nightly
      -> run_grade: Pinnacle close (power) + Shin-median consensus close from book_quotes, final score from the
         fleet web's game chips -> WRITES grades.json
      -> run_evaluate: the pre-registered looks -> WRITES reads/<date>.json, looks.json

Switch: `SYNDICATE_DECISION_POLICY_PAPER=paper` books; anything else, ABSENT INCLUDED, is off. Turning it on is
the user's decision (it adds a periodic process to the fleet), routed through the decision-engine session.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import statistics
import time
from collections import defaultdict
from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from syndicate.features.shared import decision_policy_v1 as dp

MODE_ENV = "SYNDICATE_DECISION_POLICY_PAPER"
MODE_OFF = "off"
MODE_PAPER = "paper"
STORE_RELPATH = Path("reports") / "intelligence" / "decision_policy_paper"
PREREGISTRATION = "8d16ab07"

#: Record files written within this window are read; older ones were processed by an earlier run (or missed).
LOOKBACK_S = 3 * 3600
#: Grading: a bet is closed out once this long after commence (a postponed game stays ungraded and is reported).
GRADE_GIVE_UP_S = 7 * 24 * 3600
GRADE_AFTER_START_S = 30 * 60
SHARP_BOOK = "pinnacle"
CLOSE_MAX_AGE_S = 12 * 3600
GRADED_MFAMS = ("h2h", "spreads", "totals")

#: The pre-registered looks (section 7): (min bets with a sharp close, min games, one-sided boundary).
LOOKS: tuple[tuple[str, int, int, float], ...] = (("L1", 400, 100, 3.935), ("L2", 800, 200, 2.783),
                                                  ("L3", 1200, 300, 2.272))
FINAL_READ_DATE = "2027-01-31"
BOOT_B = 2000
BOOT_SEED = 20261026


# --------------------------------------------------------------------------- switches and paths


def mode() -> str:
    """`paper` only when explicitly set. Absent is OFF: enabling adds a periodic fleet process (user's call)."""
    raw = str(os.environ.get(MODE_ENV) or "").strip().lower()
    return MODE_PAPER if raw in {"paper", "on", "1", "true", "yes"} else MODE_OFF


def _data_root() -> Path:
    from syndicate.features.shared.refresh_state_store import data_root

    return data_root()


def store_dir(root: Path | None = None) -> Path:
    return (root or _data_root()) / STORE_RELPATH


def _utc(ts: float | None = None) -> str:
    return datetime.fromtimestamp(time.time() if ts is None else ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _epoch(value: Any) -> float | None:
    try:
        d = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.timestamp()


def _central_date(ts: float) -> str:
    from syndicate.features.shared.syndicate_fair_runtime import _central_date as central

    return central(ts)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as fh:
            for raw in fh:
                raw = raw.strip()
                if raw:
                    try:
                        out.append(json.loads(raw))
                    except ValueError:
                        continue
    except OSError:
        pass
    return out


def _append_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> int:
    rows = list(rows)
    if not rows:
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, separators=(",", ":"), sort_keys=True, default=str) + "\n")
    return len(rows)


def _atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".tmp{os.getpid()}")
    tmp.write_text(json.dumps(payload, indent=1, sort_keys=True, default=str), encoding="utf-8")
    os.replace(tmp, path)


def load_bets(root: Path | None = None) -> list[dict[str, Any]]:
    return _read_jsonl(store_dir(root) / "bets.jsonl")


def load_grades(root: Path | None = None) -> dict[str, dict[str, Any]]:
    try:
        return json.loads((store_dir(root) / "grades.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


# --------------------------------------------------------------------------- sigma: S1 / S2 / S3


def load_grid(root: Path, kinds_by_sport: Mapping[str, set], selected_date: str) -> dict[tuple, dict[str, Any]]:
    """Every sport's book grid for the selected date and the next (the record's 36 h), indexed like fair_v1's."""
    from syndicate.features.shared import syndicate_fair_runtime as sfr

    grid: dict[tuple, dict[str, Any]] = {}
    try:
        day = date.fromisoformat(str(selected_date)[:10])
    except ValueError:
        return grid
    for sport, kinds in sorted(kinds_by_sport.items()):
        for d in (day, day + timedelta(days=1)):
            path = root / f"{sport}_source" / "data" / "book_grid" / f"book_grid_{d.isoformat()}.json"
            if path.is_file():
                sfr._index_grid(path, {sport: set(kinds)}, sport, grid)
    return grid


def sigma_for_record(rec: Any, grid: Mapping[tuple, Mapping[str, Any]], params: dp.Params,
                     decided_epoch: float | None) -> tuple[float | None, str | None, str | None]:
    """(sigma, source, detail) for one record side, in the registered order S1 -> S2 -> S3."""
    s1 = rec.fair_v1.sigma_fair_v1
    if s1 is not None and s1 > 0:
        return float(s1), dp.SIGMA_S1, f"fair_v1:{rec.fair_v1.family}:{rec.fair_v1.tts}"
    ident = rec.identity
    s3 = (dp.sigma_s3(params), dp.SIGMA_S3)
    if decided_epoch is None:
        return s3[0], s3[1], "no_decision_instant"
    from syndicate.features.shared import syndicate_fair_runtime as sfr
    from syndicate.features.shared.opportunity_signals import devig

    entry = grid.get(sfr.record_grid_key(ident.sport, ident.event_id, ident.market, ident.segment, ident.player,
                                         ident.side, ident.line))
    if entry is None:
        return s3[0], s3[1], "no_grid_line"
    if entry.get("one_sided"):
        return s3[0], s3[1], "one_sided_line"
    sides = entry["sides"]
    side = str(ident.side or "").strip().casefold()
    if side not in sides:
        return s3[0], s3[1], "side_not_on_grid_line"
    books: list[list[float]] = []
    for per_side in entry["books"].values():
        observed = [per_side[sd][1] for sd in sides]
        if any(t is None for t in observed):
            continue
        # As of the decision instant: a quote first seen after it did not exist then.
        if max(observed) > decided_epoch or decided_epoch - max(observed) > dp.MAX_QUOTE_AGE_S:
            continue
        probs = devig([per_side[sd][0] for sd in sides], method="shin")
        if probs is not None:
            books.append([float(x) for x in probs])
    if len(books) < dp.MIN_BOOKS:
        return s3[0], s3[1], f"under_min_books:{len(books)}"
    from syndicate.features.shared import syndicate_fair as sf

    start = _epoch(ident.commence_time)
    tts = sfr.tts_bucket(start - decided_epoch) if start is not None else None
    tts = tts or sf.TTS_BUCKETS[0]
    mfam = sf.market_family(str(entry.get("market") or ident.market), str(entry.get("segment") or ident.segment),
                            str(ident.kind or "").strip().casefold())
    kind = "prop" if mfam == "prop" else "game"
    var = dp.dispersion_var(books, sides.index(side)) + dp.r2_for(params, kind, mfam, tts)
    return math.sqrt(var), dp.SIGMA_S2, f"books={len(books)}:{kind}|{mfam}|{tts}"


# --------------------------------------------------------------------------- booking


def bet_id(strategy: str, event_id: str, axis: str) -> str:
    return hashlib.sha1(f"{strategy}|{event_id}|{axis}".encode("utf-8")).hexdigest()[:16]


def _processed(builds: Sequence[Mapping[str, Any]]) -> tuple[set[str], dict[str, float]]:
    ids = {str(b.get("build_id")) for b in builds}
    latest: dict[str, float] = {}
    for b in builds:
        t = _epoch(b.get("written_at"))
        if t is not None:
            latest[str(b.get("selected_date"))] = max(latest.get(str(b.get("selected_date")), 0.0), t)
    return ids, latest


def book_build(path: Path, *, root: Path, params: dp.Params, now: float | None = None,
               existing: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Book one record file's build. Returns its summary; appends to bets.jsonl and builds.jsonl."""
    from syndicate.features.shared import decision_record as drm

    now = time.time() if now is None else now
    store = store_dir(root)
    builds = _read_jsonl(store / "builds.jsonl")
    seen_ids, latest_by_date = _processed(builds)
    doc = drm.read_records_file(path)
    if not doc:
        return {"status": "unreadable", "path": str(path)}
    build_id, written_at, selected_date = str(doc.get("build_id") or ""), doc.get("written_at"), str(doc.get("selected_date") or "")
    decided = _epoch(written_at)
    if not build_id or decided is None:
        return {"status": "no_build_id", "path": str(path)}
    if build_id in seen_ids or decided <= latest_by_date.get(selected_date, float("-inf")):
        return {"status": "already_processed", "build_id": build_id}
    raw_records = doc.get("records") or []
    del doc
    # Only a side a venue prices can become a bet: the rest is never expanded (the worker writes ~5,000 a build).
    records = [drm.expand_record(r) for r in raw_records if isinstance(r, Mapping)
               and any(isinstance(p, Mapping) and p.get("role") == "venue" for p in r.get("prices") or [])]
    n_records = len(raw_records)
    del raw_records
    kinds: dict[str, set] = defaultdict(set)
    for rec in records:
        if rec.identity.sport:
            kinds[rec.identity.sport].add(rec.identity.kind or "game")
    grid = load_grid(root, kinds, selected_date)
    candidates: list[dp.Candidate] = []
    sigma_mix: dict[str, int] = defaultdict(int)
    failed: dict[str, int] = defaultdict(int)
    for rec in records:
        if not any(q.role == "venue" for q in rec.prices):
            continue
        info = sigma_for_record(rec, grid, params, decided)
        for venue in dp.VENUES:
            cand = dp.evaluate(rec, venue, str(written_at), info, params)
            if cand is None:
                continue
            candidates.append(cand)
            if cand.eligible:
                sigma_mix[str(cand.sigma_source)] += 1
            for gate in cand.failed_gates:
                failed[gate] += 1
    existing = load_bets(root) if existing is None else existing
    booked = {(b["strategy"], b["event_id"], b["axis"]) for b in existing}
    game_used: dict[tuple[str, str], float] = defaultdict(float)
    for b in existing:
        game_used[(b["strategy"], b["event_id"])] += float(b.get("fraction_after_cap") or 0.0)
    new: list[dict[str, Any]] = []
    for strategy in dp.STRATEGIES:
        for (event_id, axis), cand in sorted(dp.select(strategy, candidates).items()):
            if (strategy, event_id, axis) in booked:
                continue
            stake, fraction = dp.stake_units(cand, game_used[(strategy, event_id)])
            row = asdict(cand)
            row.pop("failed_gates", None)
            row.update({
                "bet_id": bet_id(strategy, event_id, axis), "strategy": strategy, "build_id": build_id,
                "selected_date": selected_date, "booked_at": _utc(now), "policy_version": dp.POLICY_VERSION,
                "params_version": params.version, "preregistration": PREREGISTRATION,
                "stake_units": stake, "fraction_after_cap": fraction,
            })
            new.append(row)
            booked.add((strategy, event_id, axis))
            game_used[(strategy, event_id)] += fraction
    _append_jsonl(store / "bets.jsonl", new)
    existing.extend(new)
    eligible = sum(1 for c in candidates if c.eligible)
    by_strategy = {s: sum(1 for r in new if r["strategy"] == s) for s in dp.STRATEGIES}
    qualifying = {s: sum(1 for c in candidates if dp.qualifies(s, c)) for s in dp.STRATEGIES}
    summary = {"build_id": build_id, "selected_date": selected_date, "written_at": written_at, "processed_at": _utc(now),
               "records": n_records, "venue_records": len(records), "candidates": len(candidates), "eligible": eligible,
               "sigma_sources": dict(sigma_mix), "failed_gates": dict(failed), "qualifying": qualifying,
               "booked": by_strategy, "params_version": params.version}
    _append_jsonl(store / "builds.jsonl", [summary])
    print(f"[decision_policy_paper] PAPER_BOOKED date={selected_date} build={build_id} records={n_records} "
          f"venue_records={len(records)} "
          f"candidates={len(candidates)} eligible={eligible} sigma={dict(sigma_mix)} qualifying={qualifying} "
          f"booked={by_strategy}", flush=True)
    return {"status": "ok", **summary}


def run_book(root: Path | None = None, *, now: float | None = None, params: dp.Params | None = None) -> dict[str, Any]:
    """The 15-minute job. Off -> writes nothing at all."""
    if mode() == MODE_OFF:
        print(f"[decision_policy_paper] MODE_OFF {MODE_ENV} is not 'paper'; nothing booked", flush=True)
        return {"status": "off"}
    from syndicate.features.shared import decision_record as drm

    root = root or _data_root()
    now = time.time() if now is None else now
    params = params or dp.load_params()
    if not params.loaded:
        print(f"[decision_policy_paper] PARAMS_MISSING error={params.error}; nothing booked", flush=True)
        return {"status": "no_params"}
    directory = drm.records_dir(root)
    files = sorted((p for p in directory.glob("*.json.gz") if now - p.stat().st_mtime <= LOOKBACK_S),
                   key=lambda p: p.stat().st_mtime) if directory.is_dir() else []
    existing = load_bets(root)
    results = [book_build(p, root=root, params=params, now=now, existing=existing) for p in files]
    return {"status": "ok", "files": len(files), "builds": results}


# --------------------------------------------------------------------------- grading


def _norm_segment(value: Any) -> str:
    seg = str(value or "").strip().lower()
    return "full" if seg in {"", "full", "full_game", "game"} else seg


def _num(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def close_key(event_id: Any, market: Any, segment: Any, player: Any, side: Any, line: Any) -> tuple:
    """Both sides of one bet on ONE key, spreads framed on the HOME line (`syndicate_fair_fit.line_key`'s rule)."""
    m = str(market or "").strip().lower()
    sd = str(side or "").strip().lower()
    ln = _num(line)
    if ln is not None and ("spread" in m or "handicap" in m) and sd == "away":
        ln = -ln
    return (str(event_id or ""), m, _norm_segment(segment), str(player or "").strip().casefold(),
            None if ln is None else round(ln, 3))


def _canonical(sides: Iterable[str]) -> tuple[str, ...] | None:
    from syndicate.features.shared.syndicate_fair_runtime import canonical_sides

    return canonical_sides(sides)


def collect_closes(bets: Sequence[Mapping[str, Any]], iter_quotes: Callable[[str, str], Iterable[Mapping[str, Any]]]
                   ) -> tuple[dict[tuple, dict[str, dict[str, list]]], dict[str, float]]:
    """(per close key: book -> side -> [captured, price] latest at or before the event's commence, event commence).

    Reads each sport's shards for every bet's commence Central date and the day before. Pass 1 settles each event's
    commence as of its LAST quote (a moved game keeps the later time), as stage 1's extract does."""
    want_events = {str(b["event_id"]) for b in bets}
    want_keys = {close_key(b["event_id"], b["market"], b["segment"], b.get("player"), b["side"], b["line"])
                 for b in bets}
    shards: dict[str, set] = defaultdict(set)
    for b in bets:
        start = _epoch(b.get("commence_time"))
        if start is None:
            continue
        cdate = date.fromisoformat(_central_date(start))
        for d in (cdate - timedelta(days=1), cdate):
            shards[str(b["sport"])].add(d.isoformat())
    commence: dict[str, tuple[float, float]] = {}
    shard_list = [(sport, d) for sport, dates in sorted(shards.items()) for d in sorted(dates)]
    for sport, d in shard_list:  # pass 1: each event's commence as of its last quote
        for q in iter_quotes(sport, d):
            ev = str(q.get("event_id") or "")
            if ev not in want_events:
                continue
            cap, ct = _epoch(q.get("captured_at")), _epoch(q.get("commence_time"))
            if cap is not None and ct is not None and (ev not in commence or cap >= commence[ev][0]):
                commence[ev] = (cap, ct)
    closes: dict[tuple, dict[str, dict[str, list]]] = defaultdict(lambda: defaultdict(dict))
    for sport, d in shard_list:  # pass 2: streamed again, so no shard is ever held in memory
        for q in iter_quotes(sport, d):
            ev = str(q.get("event_id") or "")
            if ev not in want_events:
                continue
            side = str(q.get("selection") or "").strip().lower()
            key = close_key(ev, q.get("market"), q.get("segment"), q.get("player_name"), side, q.get("line"))
            if key not in want_keys:
                continue
            start = commence.get(ev, (None, None))[1]
            cap = _epoch(q.get("captured_at"))
            book = str(q.get("bookmaker") or "").strip().lower()
            if start is None or cap is None or cap > start or not side or not book or q.get("price") is None:
                continue
            held = closes[key][book].get(side)
            if held is None or cap >= held[0]:
                closes[key][book][side] = [cap, q.get("price")]
    return closes, {ev: ct for ev, (_cap, ct) in commence.items()}


def close_probabilities(per_book: Mapping[str, Mapping[str, list]], side: str, start: float | None
                        ) -> dict[str, Any]:
    """The bet side's Pinnacle (power) close and Shin-median consensus close, with reasons when absent."""
    from syndicate.features.shared.opportunity_signals import devig

    out: dict[str, Any] = {"sharp_close": None, "sharp_reason": None, "consensus_close": None, "consensus_books": 0}
    sides = _canonical({sd for m in per_book.values() for sd in m})
    if sides is None or side not in sides or start is None:
        out["sharp_reason"] = "line_not_two_sided_or_side_missing"
        return out
    j = sides.index(side)
    fresh: dict[str, list] = {}
    for book, by_side in per_book.items():
        quotes = [by_side.get(sd) for sd in sides]
        if all(q is not None for q in quotes) and start - max(q[0] for q in quotes) <= CLOSE_MAX_AGE_S:
            fresh[book] = [q[1] for q in quotes]
    if SHARP_BOOK in fresh:
        p = devig(fresh[SHARP_BOOK], method="power")
        if p is not None:
            out["sharp_close"] = round(float(p[j]), 6)
        else:
            out["sharp_reason"] = "pinnacle_not_devigable"
    else:
        out["sharp_reason"] = "no_pinnacle_close_at_this_line"
    shin = [list(p) for prices in fresh.values() if (p := devig(prices, method="shin")) is not None]
    out["consensus_books"] = len(shin)
    if len(shin) >= 2:
        med = [statistics.median(v[i] for v in shin) for i in range(len(sides))]
        out["consensus_close"] = round(med[j] / sum(med), 6)
    return out


def _default_iter_quotes(sport: str, date_str: str) -> Iterable[Mapping[str, Any]]:
    from syndicate.features.shared.odds_book_quotes import iter_book_quotes

    return iter_book_quotes(sport, date_str)


def _scorecard() -> Any:
    import importlib.util

    path = Path(__file__).resolve().parents[3] / "scripts" / "layer2_live_scorecard.py"
    spec = importlib.util.spec_from_file_location("layer2_live_scorecard", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _default_chips(cdate: str) -> list[dict[str, Any]]:
    sc = _scorecard()
    base = os.environ.get("SYNDICATE_BASE_URL") or sc.DEFAULT_BASE_URL
    return sc.fetch_chips(base, cdate, None)


def grade_outcome(bet: Mapping[str, Any], chips_for: Callable[[str], list], sc: Any) -> tuple[str | None, str]:
    """('win'|'loss'|'push'|None, reason): full-game h2h/spreads/totals from the final score; others ungraded."""
    from syndicate.features.shared import syndicate_fair as sf

    mfam = sf.market_family(str(bet.get("market") or ""), str(bet.get("segment") or ""),
                            "prop" if bet.get("player") or bet.get("kind") == "prop" else "game")
    if mfam not in GRADED_MFAMS:
        return None, f"no_outcome_grader:{mfam}"
    start = _epoch(bet.get("commence_time"))
    if start is None:
        return None, "no_commence_time"
    cdate = _central_date(start)
    index = sc.index_chips(chips_for(cdate) or [])
    chip, why = sc.match_chip({"sport": bet.get("sport"), "home_team": bet.get("home_team"),
                               "away_team": bet.get("away_team")}, index.get(str(bet.get("sport")), []))
    if chip is None:
        return None, f"no_chip:{why}"
    if str(chip.get("state") or "").lower() != "final" or chip.get("scores") is None:
        return None, "not_final"
    away, home = chip["scores"]
    result = sc.grade({"market": bet.get("market"), "side": bet.get("side"), "line": bet.get("line"),
                       "sport": bet.get("sport")}, away, home)
    return result, "graded" if result else "ungradable"


def flat_return(outcome: str | None, cost: float | None) -> float | None:
    if outcome is None or cost is None or not (0.0 < cost < 1.0):
        return None
    return {"win": (1.0 - cost) / cost, "loss": -1.0, "push": 0.0}.get(outcome)


def run_grade(root: Path | None = None, *, now: float | None = None,
              iter_quotes: Callable[[str, str], Iterable[Mapping[str, Any]]] | None = None,
              chips_for: Callable[[str], list] | None = None, sc: Any = None) -> dict[str, Any]:
    """Grade every started bet not yet final. Writes grades.json; idempotent."""
    root = root or _data_root()
    now = time.time() if now is None else now
    bets = load_bets(root)
    grades = load_grades(root)
    todo = []
    for b in bets:
        start = _epoch(b.get("commence_time"))
        g = grades.get(b["bet_id"]) or {}
        if start is None or now < start + GRADE_AFTER_START_S or g.get("final"):
            continue
        todo.append(b)
    if not todo:
        return {"status": "ok", "graded": 0}
    closes, commence = collect_closes(todo, iter_quotes or _default_iter_quotes)
    sc = sc or _scorecard()
    chip_cache: dict[str, list] = {}

    def _chips(cdate: str) -> list:
        if cdate not in chip_cache:
            try:
                chip_cache[cdate] = (chips_for or _default_chips)(cdate)
            except Exception as exc:  # noqa: BLE001 -- the web may be down; the outcome waits for the next night
                print(f"[decision_policy_paper] CHIPS_UNREADABLE date={cdate} error={type(exc).__name__}", flush=True)
                chip_cache[cdate] = []
        return chip_cache[cdate]

    counts: dict[str, int] = defaultdict(int)
    for b in todo:
        key = close_key(b["event_id"], b["market"], b["segment"], b.get("player"), b["side"], b["line"])
        start = commence.get(str(b["event_id"])) or _epoch(b.get("commence_time"))
        c = close_probabilities(closes.get(key, {}), str(b["side"]).strip().lower(), start)
        cost = _num(b.get("cost"))
        outcome, why = grade_outcome(b, _chips, sc)
        g = {
            "bet_id": b["bet_id"], "graded_at": _utc(now), "commence_used": _utc(start) if start else None,
            **c,
            "clv_sharp_pct": round((c["sharp_close"] / cost - 1.0) * 100.0, 4) if c["sharp_close"] and cost else None,
            "clv_consensus_pct": (round((c["consensus_close"] / cost - 1.0) * 100.0, 4)
                                  if c["consensus_close"] and cost else None),
            "outcome": outcome, "outcome_reason": why, "return_flat": flat_return(outcome, cost),
        }
        old_enough = start is not None and now - start > GRADE_GIVE_UP_S
        close_done = g["sharp_close"] is not None or old_enough or now - (start or now) > 2 * 24 * 3600
        outcome_done = outcome is not None or why.startswith("no_outcome_grader") or old_enough
        g["final"] = bool(close_done and outcome_done)
        grades[b["bet_id"]] = g
        counts["graded"] += 1
        counts["sharp"] += int(g["sharp_close"] is not None)
        counts["outcome"] += int(outcome is not None)
    _atomic_json(store_dir(root) / "grades.json", grades)
    print(f"[decision_policy_paper] PAPER_GRADED bets={len(todo)} sharp_close={counts['sharp']} "
          f"outcome={counts['outcome']}", flush=True)
    return {"status": "ok", **counts}


# --------------------------------------------------------------------------- the gate


def clustered(values: Sequence[float], clusters: Sequence[str]) -> dict[str, Any]:
    """Mean, game-clustered SE (`G/(G-1) * sum_g (sum_i (x - mean))^2 / n^2`) and Z."""
    n = len(values)
    out: dict[str, Any] = {"n": n, "games": len(set(clusters)), "mean": None, "se": None, "z": None}
    if not n:
        return out
    mean = sum(values) / n
    out["mean"] = round(mean, 4)
    sums: dict[str, float] = defaultdict(float)
    for x, g in zip(values, clusters):
        sums[g] += x - mean
    G = len(sums)
    if G < 2:
        return out
    se = math.sqrt(G / (G - 1) * sum(s * s for s in sums.values())) / n
    out["se"] = round(se, 4)
    out["z"] = round(mean / se, 4) if se > 0 else None
    return out


def boot_ci(values: Sequence[float], clusters: Sequence[str], level: float = 0.95) -> list[float] | None:
    try:
        import numpy as np
    except ImportError:  # pragma: no cover
        return None
    if len(set(clusters)) < 5:
        return None
    keys, inv = np.unique(np.asarray(clusters), return_inverse=True)
    sums = np.bincount(inv, weights=np.asarray(values, dtype=float), minlength=len(keys))
    counts = np.bincount(inv, minlength=len(keys)).astype(float)
    rng = np.random.default_rng(BOOT_SEED)
    idx = rng.integers(0, len(keys), size=(BOOT_B, len(keys)))
    boots = sums[idx].sum(axis=1) / counts[idx].sum(axis=1)
    lo, hi = np.quantile(boots, [(1 - level) / 2, 1 - (1 - level) / 2])
    return [round(float(lo), 4), round(float(hi), 4)]


def _stats(rows: Sequence[tuple[Mapping[str, Any], Mapping[str, Any]]], field: str) -> dict[str, Any]:
    vals = [float(g[field]) for _b, g in rows if g.get(field) is not None]
    games = [str(b["event_id"]) for b, g in rows if g.get(field) is not None]
    out = clustered(vals, games)
    out["ci95_boot"] = boot_ci(vals, games)
    return out


def _weighted(rows: Sequence[tuple[Mapping[str, Any], Mapping[str, Any]]], field: str) -> float | None:
    num = den = 0.0
    for b, g in rows:
        if g.get(field) is not None and float(b.get("stake_units") or 0) > 0:
            num += float(b["stake_units"]) * float(g[field])
            den += float(b["stake_units"])
    return round(num / den, 4) if den else None


def _by(rows: Sequence[tuple[Mapping[str, Any], Mapping[str, Any]]], keyfn: Callable[[Mapping[str, Any]], Any],
        field: str) -> dict[str, Any]:
    groups: dict[str, list] = defaultdict(list)
    for b, g in rows:
        groups[str(keyfn(b))].append((b, g))
    return {k: clustered([float(g[field]) for _b, g in v if g.get(field) is not None],
                         [str(b["event_id"]) for b, g in v if g.get(field) is not None]) for k, v in sorted(groups.items())}


def _mfam(b: Mapping[str, Any]) -> str:
    from syndicate.features.shared import syndicate_fair as sf

    return sf.market_family(str(b.get("market") or ""), str(b.get("segment") or ""),
                            "prop" if b.get("player") or b.get("kind") == "prop" else "game")


def strategy_read(strategy: str, bets: Sequence[Mapping[str, Any]], grades: Mapping[str, Mapping[str, Any]]
                  ) -> dict[str, Any]:
    mine = [b for b in bets if b["strategy"] == strategy]
    graded = [(b, grades[b["bet_id"]]) for b in mine if b["bet_id"] in grades]
    sharp = [(b, g) for b, g in graded if g.get("clv_sharp_pct") is not None]
    no_sharp = [(b, g) for b, g in graded if g.get("clv_sharp_pct") is None]
    outcome = [(b, g) for b, g in graded if g.get("return_flat") is not None]
    reasons: dict[str, int] = defaultdict(int)
    for _b, g in no_sharp:
        reasons[str(g.get("sharp_reason"))] += 1
    return {
        "bets": len(mine), "graded": len(graded),
        "gate_clv_sharp": _stats(sharp, "clv_sharp_pct"),
        "clv_consensus_all_graded": _stats(graded, "clv_consensus_pct"),
        "no_sharp_close": {"n": len(no_sharp), "reasons": dict(reasons),
                           "clv_consensus": _stats(no_sharp, "clv_consensus_pct")},
        "roi_flat": _stats(outcome, "return_flat"),
        "stake_weighted": {"clv_sharp_pct": _weighted(sharp, "clv_sharp_pct"),
                           "roi": _weighted(outcome, "return_flat")},
        "by_venue": _by(sharp, lambda b: b.get("venue"), "clv_sharp_pct"),
        "by_sport": _by(sharp, lambda b: b.get("sport"), "clv_sharp_pct"),
        "by_market_family": _by(sharp, _mfam, "clv_sharp_pct"),
        "by_price_band": _by(sharp, lambda b: "in_band_0.40_0.75" if b.get("in_band") else "outside_band",
                             "clv_sharp_pct"),
        "by_sigma_source": _by(sharp, lambda b: b.get("sigma_source"), "clv_sharp_pct"),
    }


def _overlap(bets: Sequence[Mapping[str, Any]], grades: Mapping[str, Mapping[str, Any]], a: str, b: str) -> dict[str, Any]:
    """a - b on the (event, axis) both booked, each with a sharp close. Reported, never decisive."""
    def index(s: str) -> dict[tuple, float]:
        return {(x["event_id"], x["axis"]): float(grades[x["bet_id"]]["clv_sharp_pct"]) for x in bets
                if x["strategy"] == s and (grades.get(x["bet_id"]) or {}).get("clv_sharp_pct") is not None}
    ia, ib = index(a), index(b)
    keys = sorted(set(ia) & set(ib))
    out = clustered([ia[k] - ib[k] for k in keys], [k[0] for k in keys])
    out["ci95_boot"] = boot_ci([ia[k] - ib[k] for k in keys], [k[0] for k in keys])
    return out


def take_look(state: dict[str, Any], strategy: str, gate: Mapping[str, Any], read_date: str) -> dict[str, Any]:
    """The pre-registered looks. ONE look per read, in order; the first pass ends the strategy's test."""
    s = state.setdefault(strategy, {"looks": [], "passed": None, "closed": None})
    if s.get("passed"):
        return {"status": "already_passed", "passed": s["passed"]}
    if s.get("closed"):
        return {"status": "test_closed", "closed": s["closed"]}
    if any(lk.get("date") == read_date for lk in s["looks"]):
        return {"status": "look_already_taken_today"}   # a DAILY read: one look per strategy per date
    name, n_min, g_min, bound = LOOKS[len(s["looks"])]
    n, games, z = int(gate.get("n") or 0), int(gate.get("games") or 0), gate.get("z")
    final_by_date = read_date >= FINAL_READ_DATE
    if final_by_date and n >= LOOKS[0][1] and games >= LOOKS[0][2]:
        name, n_min, g_min, bound = LOOKS[-1]   # the calendar final reads at L3's boundary
    elif not (n >= n_min and games >= g_min):
        if final_by_date:
            s["closed"] = {"reason": "final_underpowered", "date": read_date, "n": n, "games": games}
            return {"status": "final_underpowered", "n": n, "games": games}
        return {"status": "waiting", "next_look": name, "need_n": n_min, "need_games": g_min, "n": n, "games": games}
    passed = z is not None and z >= bound
    look = {"look": name, "date": read_date, "n": n, "games": games, "mean": gate.get("mean"), "se": gate.get("se"),
            "z": z, "boundary": bound, "pass": passed}
    s["looks"].append(look)
    if passed:
        s["passed"] = look
    elif name == LOOKS[-1][0]:
        s["closed"] = {"reason": "final_look_not_passed", "date": read_date}
    return {"status": "look_taken", **look}


def run_evaluate(root: Path | None = None, *, now: float | None = None) -> dict[str, Any]:
    root = root or _data_root()
    now = time.time() if now is None else now
    read_date = datetime.fromtimestamp(now, tz=timezone.utc).date().isoformat()
    bets, grades = load_bets(root), load_grades(root)
    if not bets:  # no book (booking never enabled): the read writes nothing, so `off` leaves no trace at all
        print(f"[decision_policy_paper] NO_BOOK date={read_date}; no read written", flush=True)
        return {"status": "no_book", "read_date": read_date}
    store = store_dir(root)
    looks_path = store / "looks.json"
    try:
        state = json.loads(looks_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        state = {}
    out: dict[str, Any] = {"read_date": read_date, "read_at": _utc(now), "preregistration": PREREGISTRATION,
                           "strategies": {}, "looks": {}}
    for strategy in dp.STRATEGIES:
        out["strategies"][strategy] = strategy_read(strategy, bets, grades)
    for strategy in dp.CANDIDATE_STRATEGIES:
        gate = out["strategies"][strategy]["gate_clv_sharp"]
        look = take_look(state, strategy, gate, read_date)
        if look.get("status") == "look_taken" and look.get("pass"):
            roi = out["strategies"][strategy]["roi_flat"]
            ci = roi.get("ci95_boot")
            look["roi_flat"] = roi
            look["clv_roi_contradiction"] = bool(ci and ci[1] < 0)
            state[strategy]["passed"]["clv_roi_contradiction"] = look["clv_roi_contradiction"]
        out["looks"][strategy] = look
    out["comparison_ev_lb_minus_suggested"] = _overlap(bets, grades, dp.STRATEGY_EV_LB, dp.STRATEGY_SUGGESTED)
    out["comparison_net_floor_minus_suggested"] = _overlap(bets, grades, dp.STRATEGY_NET_FLOOR, dp.STRATEGY_SUGGESTED)
    passed = [s for s in dp.CANDIDATE_STRATEGIES if (state.get(s) or {}).get("passed")]
    out["gate"] = {"passed_by": passed, "verdict": "PASS" if passed else "NOT_YET"}
    _atomic_json(looks_path, state)
    _atomic_json(store / "reads" / f"{read_date}.json", out)
    for strategy in dp.STRATEGIES:
        g = out["strategies"][strategy]["gate_clv_sharp"]
        print(f"[decision_policy_paper] GATE_READ date={read_date} strategy={strategy} bets="
              f"{out['strategies'][strategy]['bets']} n={g['n']} games={g['games']} mean={g['mean']} z={g['z']} "
              f"look={(out['looks'].get(strategy) or {}).get('status', 'comparator')}", flush=True)
    return out
