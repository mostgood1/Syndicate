"""Grade the Layer 2 board's SUGGESTED set -- the lines it flags `suggested` -- as a set of its own.

Lane `layer2-suggested-grader` `[2026-11-18]`. The user asked the rail monitor on 11-18: "are we tracking
recomendations and success of recomendations on the rail? can we incorporate layer 2 board performance and
suggested opportunities performance? We should have a lot of history to look at for this as well".

WHY IT EXISTS. The daily scorecard (`publish_model_scorecard.py`, optimizer `daily_optimizer.py`) grades three
sets per sport: `pooled` (every priced line), `recommended` (every line the shortlist PUBLISHED, 40-86% of the
board) and `staked` (the paper book's orders). Nothing graded `suggested`, the board's per-line bet flag
(`layer2_board._stamp_suggested`, `[layer2-suggested-opps]`). That flag sits between the published and staked
sets, and the paper book stakes only it. Four one-off grades exist (findings 10-19, 10-23, 10-26 and 11-02);
this is the same reading, made daily.

THE SOURCE. The opportunity-population recorder (`opportunity_population_ledger`), field `sg`. It is the only
per-sighting history of the flag. Coverage measured on the fleet 2026-11-18:
  - `sg` is recorded from 2026-10-13 16:49Z. 10-13 and 10-14 are partial (27,007 and 21,841 records written
    before the load carry no `sg`). Every record from 10-15 on carries it.
  - The decision records (`decision_records/<date>.json.gz`, `board_suggested`) keep only each day's LAST
    build, from 10-23. Their `pregame_lines` and `clv_openings` do not carry the flag at all.

THE ROW GRADED. The earliest `sg=true` sighting per (sport, identity, phase):
`score_ranking_backtest.earliest_per_phase`, which is `grade_population`'s own selection rule, applied to the
suggested records only.

  CAVEAT: the recorder writes a line once per (board date, phase), at its FIRST sighting that day. A line that
  became suggested at a later build of the same day was recorded with `sg=false`, so it is not in this set. It
  appears only if a later board date's first sighting of it is suggested. The findings measure that gap.

THE GRADER IS THE SCORECARD'S. `score_ranking_backtest.grade_rows` -> `bucket_search.grade_population`, with
the MLB prop grader, the production extra settlers (`population_outcomes.build_extra_settler`) and the
public scoreboard. Nothing here decides win, loss, push or "ungradable".

THE NUMBERS, by the optimizer's definitions (`daily_optimizer.accumulate`). Flat 1 unit per bet at the
recorded price; venue fees are NOT netted.
  roi           sum(pnl) / bets
  market_ev     mean(p_market * decimal(price) - 1): the price against the de-vigged fair
  predicted_ev  mean(p_model * decimal(price) - 1), over MODEL-BASIS rows only (`eb` in
                `MODEL_EV_BASES`): what the model promised, where the board ranked on the model.
                EMPTY FOR THIS SET BY CONSTRUCTION: every suggested record ranks on the market
                (`eb = market_fair`, 13,030 of 13,030 on the fleet 10-13..11-19), because the flag's
                rule is market EV >= +2% against a two-sided fair. Kept so the column means the same
                thing in every set.
  sim_ev        mean(p_model * decimal(price) - 1) over every row the sim priced (`me` recorded; 38%),
                whatever the board ranked on, with `sim_roi` on the same rows: does the sim agree
                with the lines the market flagged? NOT a promise the board made.
  ci95          a 95% percentile interval on roi, `RESAMPLES` bootstrap resamples over GAMES
  ladder_roi    each alt LADDER once (its rungs' mean pnl), averaged over ladders -- the paper book caps
                stake per ladder (`portfolio_commit.cap_alt_ladder_stakes`), so per bet over-weights them
Windows: `1d` is one kickoff date (Central). `28d` is the scorecard's window: for run day D, kickoff dates
[D-28, D-1], labelled D, so a `28d` row sits beside `model_scorecard_<D>.json`'s three sets.
Season phases are NEVER pooled (`season_phase`, learnings 2026-10-05). Every row names its phase, and the
all-sports row pools the regular season only.

OUTPUT, under the data root (`reports/suggested_set/`). Nothing reads these files for betting.
  suggested_set_latest.json, suggested_set_<YYYYMMDD>.json: {version, generated_at, today, source, grading,
      grader, method, rows}. Rows have the rail monitor's board-results shape: {id, day, sport, set, bets,
      games, roi_pct, predicted_ev_pct, market_ev_pct} plus the interval and breakdown fields.
  suggested_set_state.json: graded rows by identity. A rerun grades only lines it has not graded, and
      resets when the scorecard's grader signature changes (per sport on its settler version), as the
      scorecard does.

    # on the fleet, read-only except its own output directory:
    nice -n 19 python scripts/grade_suggested_set.py --data-root ~/syndicate-prod/data --write
    # a dry run (no writes), or a reproduction into a scratch directory with no state:
    python scripts/grade_suggested_set.py --data-root ~/syndicate-prod/data
    python scripts/grade_suggested_set.py --data-root ... --files-from 2026-10-17 --files-to 2026-11-01 \\
        --today 2026-11-02 --no-state --out /tmp/repro

REFUSALS. No data root: exit 2. The checkout's `data/` is a lossy mirror, never a default. No recorder file
read: exit 3. A failed write: exit 5.
"""

from __future__ import annotations

import argparse
import collections
import functools
import json
import math
import os
import random
import re
import sys
import tempfile
import time
import zlib
from datetime import date as date_cls, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
for _path in (REPO_ROOT, REPO_ROOT / "scripts"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import score_ranking_backtest as srb  # noqa: E402
from syndicate.features.shared import daily_optimizer as opt  # noqa: E402
from syndicate.features.shared import model_scorecard as msc  # noqa: E402
from syndicate.features.shared import season_phase as phases  # noqa: E402
from syndicate.features.shared.opportunity_population_ledger import POPULATION_SUBDIR, parse_population_key  # noqa: E402

VERSION = "suggested_set/1"
SET_LABEL = "Suggested by the board"
OUT_DIR = "reports/suggested_set"
LATEST_PATH = f"{OUT_DIR}/suggested_set_latest.json"
STATE_PATH = f"{OUT_DIR}/suggested_set_state.json"
WINDOW_DAYS = opt.WINDOW_DAYS
RESAMPLES = 2000
SEED = 20261118
# An ungraded line is retried while its kickoff is this recent (box scores and settlers can lag); after that its
# reason is final and it is not fetched again.
RETRY_DAYS = 7
# Dated copies kept beside `latest` (~3 MB each on 11-18). `latest` carries every day's rows, so these are an audit
# trail, not history; older ones are deleted (this folder only).
DATED_KEEP_DAYS = 14
DATED_RE = re.compile(r"^suggested_set_(\d{8})\.json$")
# The first board date whose recorder file can carry `sg` (`[layer2-suggested-opps]`, loaded 10-13 16:49Z).
SG_FIRST_DATE = "2026-10-13"
SG_TRUE = '"sg":true'
# What the state keeps of a graded row (`score_ranking_backtest.graded_row`): the cuts, the outcome, the price, the
# grader's probabilities, and enough of the record to trace it. Not `bp` (every book's price), which is most of a row.
ROW_KEYS = ("date", "sport", "game", "k", "market", "family", "segment", "phase", "side", "line", "player", "t",
            "y", "pnl", "price", "p_market", "p_model", "eb", "ev", "me", "fp", "fm", "px", "bk", "ln")
PART_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})__([a-z0-9_]+)__part(\d{3})\.jsonl$")
ALL_SPORTS = "all"
UNKNOWN_PHASE = "unknown"
# The rail monitor's display names (`perf_build.py`), so a row drops in beside its board rows.
SPORT_NAMES = {"nba": "NBA", "ncaab": "NCAAB", "wncaab": "Women's college", "ncaaf": "NCAAF", "nfl": "NFL",
               "nhl": "NHL", ALL_SPORTS: "All sports"}


def log(message: str) -> None:
    print(f"[suggested_set] {message}", flush=True)


def sport_name(sport: str) -> str:
    return SPORT_NAMES.get(sport, sport.upper() if len(sport) <= 4 else sport.title())


def _shift(day: str, days: int) -> str:
    return (date_cls.fromisoformat(day) + timedelta(days=days)).isoformat()


def _days(first: str, last: str) -> list[str]:
    if first > last:
        return []
    return [_shift(first, i) for i in range((date_cls.fromisoformat(last) - date_cls.fromisoformat(first)).days + 1)]


# --------------------------------------------------------------------------- reading the recorder


def recorder_files(data_root: Path, *, first: str | None = None, last: str | None = None) -> list[tuple[str, str, Path]]:
    """(board date, sport, path) for every recorder part in [first, last], sorted."""
    folder = data_root / "reports" / "intelligence" / POPULATION_SUBDIR
    out = []
    for path in sorted(folder.glob("*__*__part*.jsonl")) if folder.is_dir() else ():
        match = PART_RE.match(path.name)
        if not match:
            continue
        day, sport = match.group(1), match.group(2)
        if (first and day < first) or (last and day > last):
            continue
        out.append((day, sport, path))
    return out


def scan_suggested(files: Iterable[tuple[str, str, Path]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Every `sg=true` record in the files, plus what was read. Only lines carrying the flag are parsed."""
    records: list[dict[str, Any]] = []
    by_file_date: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    scanned = parts = 0
    for day, sport, path in files:
        parts += 1
        counter = by_file_date[day]
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                scanned += 1
                counter["records"] += 1
                if SG_TRUE not in line:
                    continue
                try:
                    record = json.loads(line)
                except ValueError:
                    counter["torn"] += 1
                    continue
                if not isinstance(record, dict) or record.get("sg") is not True or not record.get("k"):
                    continue
                record.setdefault("sport", sport)
                counter["sg_true"] += 1
                records.append(record)
    days = sorted(by_file_date)
    summary = {
        "parts_read": parts,
        "first_file_date": days[0] if days else None,
        "last_file_date": days[-1] if days else None,
        "records_scanned": scanned,
        "sg_records": len(records),
        "by_file_date": {day: dict(by_file_date[day]) for day in days},
    }
    return records, summary


def lend_names(records: Sequence[dict[str, Any]]) -> int:
    """Team names lent across sightings of one event, as `grade_population` lends them within a batch: the
    earliest sighting is the one graded and can predate the recorder carrying names. Returns how many were filled."""
    named: dict[tuple[str, str], tuple[str, str]] = {}
    for record in records:
        identity = parse_population_key(str(record.get("k") or ""))
        if identity and record.get("ht") and record.get("at"):
            named.setdefault((str(record.get("sport") or "").lower(), identity["event_id"]), (record["ht"], record["at"]))
    filled = 0
    for record in records:
        if record.get("ht") and record.get("at"):
            continue
        identity = parse_population_key(str(record.get("k") or ""))
        names = named.get((str(record.get("sport") or "").lower(), identity["event_id"])) if identity else None
        if names:
            record["ht"], record["at"] = names
            filled += 1
    return filled


def identity_of(record: Mapping[str, Any]) -> str:
    """The grader's selection key, (sport, identity, phase), as one string."""
    from syndicate.features.shared import measured_bucket_skill as mbs

    phase = mbs._phase(record.get("gs"), sighted_at=record.get("t"), commence_time=record.get("ct"))
    return f"{str(record.get('sport') or '').strip().lower()}|{record.get('k')}|{phase}"


# --------------------------------------------------------------------------- state


def empty_state(signature: str, sport_versions: Mapping[str, str]) -> dict[str, Any]:
    return {"version": VERSION, "signature": signature, "sport_versions": dict(sport_versions),
            "graded": {}, "ungradable": {}, "resets": []}


def load_state(payload: Any, signature: str, sport_versions: Mapping[str, str], *,
               now: datetime) -> tuple[dict[str, Any], str]:
    """The saved state, or a fresh one. A changed core signature resets everything; a changed settler version
    resets that sport only -- the scorecard's no-pooling rule for two grader versions."""
    stamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    if not isinstance(payload, dict) or payload.get("version") != VERSION:
        return empty_state(signature, sport_versions), "fresh"
    if payload.get("signature") != signature:
        state = empty_state(signature, sport_versions)
        state["resets"] = list(payload.get("resets") or []) + [{"at": stamp, "scope": "all"}]
        return state, "reset_all"
    old = payload.get("sport_versions") or {}
    changed = sorted(s for s in set(old) | set(sport_versions) if old.get(s) != sport_versions.get(s))
    state = {**empty_state(signature, sport_versions), "resets": list(payload.get("resets") or [])}
    for bucket in ("graded", "ungradable"):
        state[bucket] = {ident: entry for ident, entry in (payload.get(bucket) or {}).items()
                         if ident.split("|", 1)[0] not in changed}
    if changed:
        state["resets"].append({"at": stamp, "scope": changed})
        return state, "reset:" + ",".join(changed)
    return state, "loaded"


def grade_suggested(chosen: Sequence[Mapping[str, Any]], state: dict[str, Any], *, today: str,
                    grade_record: Callable[[Mapping[str, Any]], tuple[dict[str, Any] | None, str | None]],
                    central_date: Callable[[Any], str | None]) -> dict[str, Any]:
    """Grade every chosen record the state has not settled. Mutates `state`; returns the counts."""
    counts: collections.Counter = collections.Counter()
    reasons: collections.Counter = collections.Counter()
    keep: set[str] = set()
    retry_floor = _shift(today, -RETRY_DAYS)
    for record in chosen:
        ident = identity_of(record)
        keep.add(ident)
        t = str(record.get("t") or "")
        held = state["graded"].get(ident)
        if held is not None and held.get("t") == t:
            counts["reused"] += 1
            continue
        dead = state["ungradable"].get(ident)
        if dead is not None and dead.get("t") == t:
            counts["ungradable_known"] += 1
            reasons[dead.get("reason") or "unknown"] += 1
            continue
        state["graded"].pop(ident, None)
        state["ungradable"].pop(ident, None)
        row, reason = grade_record(record)
        if row is not None:
            state["graded"][ident] = {"t": t, "row": {key: row.get(key) for key in ROW_KEYS}}
            counts["graded_now"] += 1
            continue
        reason = reason or "unknown"
        reasons[reason] += 1
        kickoff = central_date(record.get("ct"))
        if reason == "not_yet" or (kickoff is not None and kickoff >= retry_floor):
            counts["pending"] += 1
        else:
            state["ungradable"][ident] = {"t": t, "reason": reason, "kickoff": kickoff}
            counts["ungradable_now"] += 1
    # An identity no longer chosen (its earliest suggested sighting moved, or its file is outside the read) is dropped.
    for bucket in ("graded", "ungradable"):
        for ident in [i for i in state[bucket] if i not in keep]:
            del state[bucket][ident]
            counts[f"dropped_{bucket}"] += 1
    counts["graded_total"] = len(state["graded"])
    return {"counts": dict(counts), "ungraded_reasons": dict(reasons.most_common())}


def make_grade_record(bs: Any, *, grade: Callable[..., Any], chips_for: Callable[[str], Any],
                      today: str) -> Callable[[Mapping[str, Any]], tuple[dict[str, Any] | None, str | None]]:
    """One record through `score_ranking_backtest.grade_rows` -- the scorecard's grader, its reasons kept."""

    def grade_record(record: Mapping[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
        rows, reasons = srb.grade_rows([record], grade=grade, chips_for=chips_for,
                                       central_date=bs.SCORECARD.central_date, today=today)
        if rows:
            return rows[0], None
        reasons.pop("graded", None)
        return None, (reasons.most_common(1)[0][0] if reasons else "unknown")

    return grade_record


# --------------------------------------------------------------------------- statistics


def _decimal(price: float) -> float:
    return opt._decimal_odds(price)  # noqa: SLF001 -- the optimizer's own conversion


def _seed(row_id: str) -> int:
    return (SEED + zlib.crc32(row_id.encode("utf-8"))) % (2**32)


def roi_interval(per_game: Sequence[tuple[float, int]], *, resamples: int, seed: int) -> list[float] | None:
    """95% percentile interval of sum(pnl)/sum(bets), resampling GAMES with replacement."""
    n = len(per_game)
    if n < 2 or resamples <= 0:
        return None
    pnl = [p for p, _ in per_game]
    bets = [b for _, b in per_game]
    try:
        import numpy as np

        rng = np.random.default_rng(seed)
        idx = rng.integers(0, n, size=(resamples, n))
        p_arr, b_arr = np.asarray(pnl, dtype=float), np.asarray(bets, dtype=float)
        samples = np.sort(p_arr[idx].sum(axis=1) / b_arr[idx].sum(axis=1))
        values = samples.tolist()
    except ImportError:
        rng = random.Random(seed)
        values = []
        for _ in range(resamples):
            picks = [rng.randrange(n) for _ in range(n)]
            values.append(sum(pnl[i] for i in picks) / sum(bets[i] for i in picks))
        values.sort()
    return [values[int(0.025 * resamples)], values[min(resamples - 1, int(0.975 * resamples))]]


def _pct(value: float | None, digits: int = 2) -> float | None:
    return None if value is None else round(100.0 * value, digits)


def ladder_of(row: Mapping[str, Any]) -> tuple[Any, ...]:
    """The paper book's alt-ladder unit (`portfolio_commit.cap_alt_ladder_stakes`): event, market without
    `_alt` / `_alternate`, segment, player and side -- plus the pregame/live phase, as the 11-02 grade kept it."""
    market = str(row.get("market") or "")
    for suffix in ("_alternate", "_alt"):
        market = market.removesuffix(suffix)
    return (row.get("game"), row.get("phase"), market, row.get("segment"), row.get("player"), row.get("side"))


def summarise(rows: Sequence[Mapping[str, Any]], *, row_id: str, resamples: int) -> dict[str, Any] | None:
    """The set's numbers over `rows` (graded rows), or None when no row is priced."""
    priced = [r for r in rows if r.get("pnl") is not None and r.get("price") not in (None, 0) and r.get("y") is not None]
    if not priced:
        return None
    games: dict[str, list[float]] = {}
    market_ev: list[float] = []
    model_ev: list[float] = []
    model_pnl: list[float] = []
    sim_ev: list[float] = []
    sim_pnl: list[float] = []
    for r in priced:
        acc = games.setdefault(str(r.get("game")), [0.0, 0])
        acc[0] += float(r["pnl"])
        acc[1] += 1
        odds = _decimal(float(r["price"]))
        if r.get("p_market") is not None:
            market_ev.append(float(r["p_market"]) * odds - 1.0)
        if r.get("p_model") is not None:
            sim_ev.append(float(r["p_model"]) * odds - 1.0)
            sim_pnl.append(float(r["pnl"]))
            if str(r.get("eb") or "").strip() in opt.MODEL_EV_BASES:
                model_ev.append(sim_ev[-1])
                model_pnl.append(float(r["pnl"]))
    bets = len(priced)
    units = sum(float(r["pnl"]) for r in priced)
    wins = sum(1 for r in priced if float(r["y"]) >= 1.0)
    ladders: dict[tuple[Any, ...], list[float]] = collections.defaultdict(list)
    for r in priced:
        ladders[ladder_of(r)].append(float(r["pnl"]))
    ladder_means = [sum(v) / len(v) for v in ladders.values()]
    # Games in a FIXED order: the seed alone does not make the draw repeatable when the rows arrive in another order
    # (the state reloads sorted), and a daily number must not move on identical data.
    ci = roi_interval([tuple(games[g]) for g in sorted(games)], resamples=resamples, seed=_seed(row_id))
    return {
        "bets": bets,
        "games": len(games),
        "wins": wins,
        "hit_pct": _pct(wins / bets, 1),
        "units": round(units, 2),
        "roi_pct": _pct(units / bets),
        "roi_ci95_lo_pct": _pct(ci[0]) if ci else None,
        "roi_ci95_hi_pct": _pct(ci[1]) if ci else None,
        "ladders": len(ladder_means),
        "ladder_roi_pct": _pct(sum(ladder_means) / len(ladder_means)),
        "predicted_ev_pct": _pct(sum(model_ev) / len(model_ev)) if model_ev else None,
        "model_bets": len(model_ev),
        "model_roi_pct": _pct(sum(model_pnl) / len(model_pnl)) if model_pnl else None,
        "sim_ev_pct": _pct(sum(sim_ev) / len(sim_ev)) if sim_ev else None,
        "sim_bets": len(sim_ev),
        "sim_roi_pct": _pct(sum(sim_pnl) / len(sim_pnl)) if sim_pnl else None,
        "market_ev_pct": _pct(sum(market_ev) / len(market_ev)) if market_ev else None,
        "market_ev_bets": len(market_ev),
    }


def phase_of(row: Mapping[str, Any]) -> str:
    return phases.season_phase(row.get("sport"), row.get("date")) or UNKNOWN_PHASE


def row_id(day: str, sport: str, window: str, phase: str, scope: str, value: str | None) -> str:
    """`<day>|<sport>|Suggested by the board` for a sport's regular-season 28-day row -- the rail monitor's own id
    shape (`<day>|<sport>|<set>`) -- with a suffix for every other cut."""
    parts = [day, sport, SET_LABEL]
    if window != f"{WINDOW_DAYS}d":
        parts.append(window)
    if phase != phases.REGULAR:
        parts.append(phase)
    if value is not None:
        parts.append(f"{scope}:{value}")
    return "|".join(parts)


def _groups(rows: Sequence[Mapping[str, Any]]) -> dict[tuple[str, str, str, str | None], list[Mapping[str, Any]]]:
    """(sport, phase, scope, value) -> rows. Sport, market and pregame/live cuts per sport and phase; the all-sports
    cut pools the REGULAR season only."""
    out: dict[tuple[str, str, str, str | None], list[Mapping[str, Any]]] = collections.defaultdict(list)
    for r in rows:
        sport, phase = str(r.get("sport") or ""), phase_of(r)
        out[(sport, phase, "sport", None)].append(r)
        out[(sport, phase, "market", str(r.get("market") or "unknown"))].append(r)
        out[(sport, phase, "state", str(r.get("phase") or "unknown"))].append(r)
        if phase == phases.REGULAR:
            out[(ALL_SPORTS, phase, "all", None)].append(r)
    return out


def build_rows(graded: Sequence[Mapping[str, Any]], *, today: str, resamples: int = RESAMPLES,
               first_day: str | None = None) -> list[dict[str, Any]]:
    """Daily (`1d`, by kickoff date) and rolling (`28d`, scorecard semantics) rows for every cut."""
    dated = [r for r in graded if r.get("date") and str(r["date"]) < today]
    if not dated:
        return []
    by_date: dict[str, list[Mapping[str, Any]]] = collections.defaultdict(list)
    for r in dated:
        by_date[str(r["date"])].append(r)
    first = first_day or min(by_date)
    out: list[dict[str, Any]] = []

    def emit(day: str, window: str, first_d: str, last_d: str, rows: Sequence[Mapping[str, Any]]) -> None:
        for (sport, phase, scope, value), group in sorted(_groups(rows).items(), key=lambda kv: tuple(str(x) for x in kv[0])):
            rid = row_id(day, sport, window, phase, scope, value)
            numbers = summarise(group, row_id=rid, resamples=resamples)
            if numbers is None:
                continue
            out.append({
                "id": rid, "day": day, "sport": sport_name(sport), "sport_key": sport, "set": SET_LABEL,
                "season_phase": phase, "scope": scope,
                "market": value if scope == "market" else None, "state": value if scope == "state" else None,
                "window": window, "window_first": first_d, "window_last": last_d, **numbers,
            })

    for day in _days(first, _shift(today, -1)):
        if by_date.get(day):
            emit(day, "1d", day, day, by_date[day])
    for day in _days(_shift(first, 1), today):
        lo, hi = _shift(day, -WINDOW_DAYS), _shift(day, -1)
        window_rows = [r for d in _days(max(lo, first), hi) for r in by_date.get(d, ())]
        if window_rows:
            emit(day, f"{WINDOW_DAYS}d", lo, hi, window_rows)
    return out


# --------------------------------------------------------------------------- run


def write_json(path: Path, payload: Any) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".tmp{os.getpid()}")
    tmp.write_text(json.dumps(payload, separators=(",", ":"), sort_keys=True, default=str), encoding="utf-8")
    os.replace(tmp, path)
    return path.stat().st_size


def prune_dated(out_dir: Path, today: str, keep_days: int = DATED_KEEP_DAYS) -> list[str]:
    """Delete this grader's own dated copies older than `keep_days`. Touches nothing else in the folder."""
    floor = _shift(today, -keep_days).replace("-", "")
    removed = []
    for path in sorted(out_dir.glob("suggested_set_*.json")):
        match = DATED_RE.match(path.name)
        if match and match.group(1) < floor:
            path.unlink()
            removed.append(path.name)
    return removed


def resolve_data_root(arg: str | None) -> Path | None:
    raw = (arg or os.environ.get("SYNDICATE_DATA_ROOT") or "").strip()
    return Path(raw).expanduser().resolve() if raw else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data-root", help="the fleet data root (default SYNDICATE_DATA_ROOT; no other default)")
    parser.add_argument("--today", help="Central run date (default: now). Kickoffs on or after it are not graded.")
    parser.add_argument("--files-from", default=SG_FIRST_DATE, help="first recorder board date read")
    parser.add_argument("--files-to", default=None, help="last recorder board date read (default: all)")
    parser.add_argument("--write", action="store_true", help=f"write {OUT_DIR}/ under the data root")
    parser.add_argument("--out", help="write the report and state to this directory instead (implies writing)")
    parser.add_argument("--no-state", action="store_true", help="neither read nor write the state: grade everything")
    parser.add_argument("--resamples", type=int, default=RESAMPLES)
    parser.add_argument("--cache-dir", help="settler / box-score cache (default: a temporary directory)")
    args = parser.parse_args(argv)

    started = time.monotonic()
    now = datetime.now(timezone.utc)
    data_root = resolve_data_root(args.data_root)
    if data_root is None or not data_root.is_dir():
        log(f"REFUSING: no data root ({args.data_root or 'SYNDICATE_DATA_ROOT unset'}). The checkout's data/ is a "
            "lossy mirror and is never read by default.")
        return 2
    bs = msc.load_bucket_search()
    today = args.today or msc.central_today(now, bs.SCORECARD.central_date)
    files = recorder_files(data_root, first=args.files_from, last=args.files_to)
    if not files:
        log(f"REFUSING: no recorder part under {data_root} for {args.files_from}..{args.files_to or 'latest'}")
        return 3
    log(f"START today_central={today} data_root={data_root} files={len(files)} "
        f"{files[0][0]}..{files[-1][0]}")

    records, source = scan_suggested(files)
    source["names_lent"] = lend_names(records)
    chosen = srb.earliest_per_phase(records)
    source["identities"] = len(chosen)
    source["first_sg_sighting_t"] = min((str(r.get("t") or "") for r in records), default=None)
    source["identities_by_sport"] = dict(collections.Counter(str(r.get("sport")) for r in chosen).most_common())
    log(f"SCANNED records={source['records_scanned']} sg={source['sg_records']} identities={len(chosen)} "
        f"names_lent={source['names_lent']} seconds={time.monotonic() - started:.0f}")

    pub = srb._load_publisher()  # noqa: SLF001 -- the scorecard's own chip fetch and grader signature
    from syndicate.features.mlb.prop_outcomes import MlbPropGrader
    from syndicate.features.shared.population_outcomes import build_extra_settler

    class LocalReader:
        """The scorecard's settlers read artifacts by relative path; on the fleet they are on this disk."""

        def text(self, relative: str) -> str | None:
            path = data_root / relative
            return path.read_text(encoding="utf-8") if path.is_file() else None

    cache = Path(args.cache_dir) if args.cache_dir else Path(tempfile.mkdtemp(prefix="suggested_set_cache_"))
    mlb = MlbPropGrader(cache_dir=cache / "statsapi")
    settler = build_extra_settler(cache_dir=cache / "settlers", fetch_export=LocalReader().text)
    signature, sport_versions, grader = pub.grader_signature(bs, settler)
    bs.SCORECARD.index_chips = srb.stable_chip_index(bs.SCORECARD.index_chips)

    out_dir = Path(args.out) if args.out else (data_root / OUT_DIR)
    state_file = out_dir / Path(STATE_PATH).name
    saved = None
    if not args.no_state and state_file.is_file():
        try:
            saved = json.loads(state_file.read_text(encoding="utf-8"))
        except ValueError as exc:
            log(f"STATE_UNREADABLE {exc} -- grading from scratch")
    state, state_status = load_state(saved, signature, sport_versions, now=now)
    log(f"STATE {state_status} graded={len(state['graded'])} ungradable={len(state['ungradable'])}")

    chips: dict[str, Any] = {}

    def chips_for(day: str) -> Any:
        if day not in chips:
            chips[day] = pub.fetch_chips_with_retry(bs, day)
        return chips[day]

    grade = functools.partial(bs.grade_population, prop_settler=mlb.settle, score_source=mlb.final_score,
                              extra_settler=settler)
    grading = grade_suggested(chosen, state, today=today, central_date=bs.SCORECARD.central_date,
                              grade_record=make_grade_record(bs, grade=grade, chips_for=chips_for, today=today))
    grading["settlers"] = settler.report()
    grading["chip_dates_fetched"] = len(chips)
    log(f"GRADED {json.dumps(grading['counts'], sort_keys=True)} reasons={json.dumps(grading['ungraded_reasons'])}")

    graded_rows = [entry["row"] for entry in state["graded"].values()]
    rows = build_rows(graded_rows, today=today, resamples=args.resamples)
    report = {
        "version": VERSION,
        "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "today": today,
        "source": source,
        "grading": grading,
        "grader": grader,
        "state": {"status": state_status, "resets": state["resets"]},
        "method": {
            "set": "the earliest sg=true recorder sighting per (sport, identity, phase); recorder = "
                   "opportunity_population, written once per (board date, phase) at the line's first sighting",
            "grader": "score_ranking_backtest.grade_rows -> bucket_search.grade_population (the scorecard's grader, "
                      "MLB prop grader, production extra settlers, public scoreboard)",
            "roi": "flat 1 unit per bet at the recorded price, sum(pnl)/bets; venue fees not netted",
            "market_ev": "mean(p_market * decimal(price) - 1), daily_optimizer.accumulate's market EV",
            "predicted_ev": "mean(p_model * decimal(price) - 1) over model-basis rows (eb in MODEL_EV_BASES), the "
                            "optimizer's definition; null for this set because every suggested row ranks on the "
                            "market (eb = market_fair)",
            "sim_ev": "mean(p_model * decimal(price) - 1) over every row the sim priced, whatever the board ranked "
                      "on; sim_roi on the same rows. Not a promise the board made.",
            "ci95": f"percentile interval of roi, {args.resamples} bootstrap resamples over games",
            "ladder_roi": "each alt ladder (game, phase, market without _alt/_alternate, segment, player, side) "
                          "counted once at its rungs' mean pnl",
            "windows": f"1d = one Central kickoff date; {WINDOW_DAYS}d = kickoff dates [day-{WINDOW_DAYS}, day-1], "
                       "the scorecard's window, labelled with the scorecard's run day",
            "season_phase": "season_phase.season_phase per kickoff date; never pooled; the all-sports row is "
                            "regular season only",
        },
        "seconds": round(time.monotonic() - started, 1),
        "rows": rows,
    }
    log(f"ROWS {len(rows)} days={len({r['day'] for r in rows})} graded_rows={len(graded_rows)}")
    for r in rows:
        if r["day"] == today and r["window"] == f"{WINDOW_DAYS}d" and r["scope"] in ("sport", "all"):
            log(f"LATEST {r['id']} bets={r['bets']} games={r['games']} roi={r['roi_pct']}% "
                f"[{r['roi_ci95_lo_pct']}, {r['roi_ci95_hi_pct']}] model_ev={r['predicted_ev_pct']}% "
                f"market_ev={r['market_ev_pct']}%")

    if not (args.write or args.out):
        log("NOT WRITTEN (--write not given)")
        return 0
    try:
        stamp = today.replace("-", "")
        for name, payload in ((Path(LATEST_PATH).name, report), (f"suggested_set_{stamp}.json", report)):
            log(f"WROTE {out_dir / name} bytes={write_json(out_dir / name, payload)}")
        if not args.no_state:
            log(f"WROTE {state_file} bytes={write_json(state_file, state)}")
        removed = prune_dated(out_dir, today)
        if removed:
            log(f"PRUNED {len(removed)} dated copies older than {DATED_KEEP_DAYS} days: {removed[0]}..{removed[-1]}")
    except OSError as exc:
        log(f"WRITE_FAILED {type(exc).__name__}: {exc}")
        return 5
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
