"""The daily optimizer: model calibration and RECOMMENDATION accuracy, fitted on the scorecard cron.

Lane `daily-optimizer` `[2026-10-05]`. USER REQUEST, verbatim: "something that check each sport
daily for accuracy of model vs reality and optimizes, and something that checks for betting
reocmendation accuracy vs reality and optimizes ... runs daily without prompting". The user chose
"auto-apply within rails" and "cron + daily Claude review".

WHERE IT RUNS. Inside `scripts/publish_model_scorecard.py` (the 11:30Z `model-scorecard` cron), on
the SAME graded rows the scorecard grades -- never a second grader (the `daily-accuracy` skill's
rule: two numbers for one question, computed by different code, is an argument nobody settles).
It wraps the scorecard's `grade` callable, so `bucket_search.grade_population` -- whose source is
hashed into the scorecard's grader signature -- is not touched and no graded history resets.

WHAT IT MEASURES, per cell `sport|market|segment|phase` (the scorecard's cell):

1. MODEL CALIBRATION. The Brier-optimal shrink of the model's edge toward the market:
       p(w) = p_market + w * (p_model - p_market),   w* = sum(d*r) / sum(d*d)
   with d = p_model - p_market and r = y - p_market. w* = 1 means the edge is sized right; w* < 1
   means the model is overconfident (w* ~ 0: no information beyond the line -- what the 2026-10-05
   NBA prop finding measured as an OOS blend weight of ~0.05). Seeded bootstrap over GAMES,
   leave-one-date-out, Benjamini-Hochberg across cells.
2. RECOMMENDATIONS. The rows the shortlist PUBLISHED (`clv_openings/<date>.jsonl`, joined on the
   recorder's own population key, as `opportunity_population_ledger`'s docstring prescribes),
   graded by EV band: bets, hit rate, realised ROI per game against the EV predicted for them.
   The POOLED population's same band is reported BESIDE it, never instead of it (learnings
   2026-09-21: the 2026-09-12 FORBIDDEN rule -- a publication filter freezes a metric -- still
   stands, so the published column is a second column, not a replacement).

WHAT IT MAY CHANGE -- the 2026-10-05 PRIME DIRECTIVE. "No market is withheld; accuracy ranks, it
never hides." A gate on a (sport, market) verdict is FORBIDDEN. So the overlay this writes carries
only MULTIPLIERS in [FACTOR_FLOOR, 1.0] that a consumer applies to a line's RANK and STAKE:
  - `edge_shrink`: validated w* < 1 (CI upper < 1), applied as max(FACTOR_FLOOR, CI upper) -- the
    SMALLEST shrink the evidence supports, never the point estimate.
  - `stake_scale`: published bets in the cell realised significantly less than predicted EV
    (realised-minus-predicted CI upper < 0); factor = (predicted + CI upper) / predicted, floored.
Never > 1 (the optimizer never amplifies), never 0, never a removal. 72 h expiry, capped entry
count, and `validate_overlay` re-checks every rail on the consumer side. CONSUMERS (phase 2,
2026-10-05): `optimizer_overlay.factor_for_row`, multiplied into `layer2_board._apply_skill_reliability`
(rank) and `portfolio_commit._sizing_skill_factor` (stake).

STATE. Its own file (`OPT_STATE_PATH`), because `model_scorecard.load_state` copies back only the
fields it knows. Per graded game: the calibration sums and the banded recommendation / pooled sums.
Per pending game: which of its population keys were published. Reset on the scorecard's grader
signature, and per sport on its settler version -- the same no-pooling rule the scorecard obeys.
"""

from __future__ import annotations

import collections
import json
import math
import random
import zlib
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import date as date_cls, datetime, timedelta, timezone
from typing import Any

# /2 [2026-10-06]: band accumulators carry the MODEL's EV beside the market's. /1's `predicted_ev` was
# p_market * odds - 1 -- the price against the de-vigged fair, i.e. ~minus the vig (-3.6% to -5.6% on
# the first run) -- so it was never what the model promised, and `stake_scale` (needs ev > 0) could
# fire only on price-shopped cells. /1 states carry 4-slot accumulators and are reset, not migrated.
OPTIMIZER_VERSION = "daily_optimizer/2"
REPORT_DIR = "reports/model_scorecard"
# Names match the EXISTING `HOT_ARTIFACT_PATTERNS` entry `reports/model_scorecard/model_scorecard_*.json`,
# so publishing needs no allowlist change on web; no ISO date in them, so date-scoped worker pulls skip them.
OPTIMIZER_PATH = f"{REPORT_DIR}/model_scorecard_optimizer.json"
OPT_STATE_PATH = f"{REPORT_DIR}/model_scorecard_optimizer_state.json"
# The overlay ALONE, small, for the consumers (`optimizer_overlay`): they re-read it every 10 minutes
# and must not parse the whole report to do so.
OVERLAY_PATH = f"{REPORT_DIR}/model_scorecard_optimizer_overlay.json"
OPENINGS_TEMPLATE = "reports/intelligence/clv_openings/{date}.jsonl"
SOURCE = "model_scorecard/daily_optimizer"

WINDOW_DAYS = 28
RETAIN_DAYS = 35
PUB_RETAIN_DAYS = 10
MIN_GAMES = 60
MIN_DATES = 5
FDR_Q = 0.10
RESAMPLES = 2000
SEED = 20261005
FACTOR_FLOOR = 0.5
MAX_ENTRIES = 200
OVERLAY_TTL_HOURS = 72

# EV of the recorded price against the recorded fair, in percent. Lower bound inclusive.
EV_BANDS: tuple[tuple[float | None, float | None, str], ...] = (
    (None, 0.0, "ev<0"),
    (0.0, 2.0, "ev0-2"),
    (2.0, 5.0, "ev2-5"),
    (5.0, 10.0, "ev5-10"),
    (10.0, None, "ev10+"),
)
ALL_BAND = "all"


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------


def _decimal_odds(american: float) -> float:
    return 1.0 + (american / 100.0 if american > 0 else 100.0 / -american)


def ev_band(ev_pct: float) -> str:
    for low, high, label in EV_BANDS:
        if (low is None or ev_pct >= low) and (high is None or ev_pct < high):
            return label
    return EV_BANDS[-1][2]


def cell_of(row: Mapping[str, Any]) -> str | None:
    buckets = list(row.get("buckets") or [])
    if not buckets:
        return None
    return "|".join(str(buckets[0]).split("|")[:4])


def _shift(day: str, days: int) -> str:
    return (date_cls.fromisoformat(day) + timedelta(days=days)).isoformat()


def _seed(cell: str, metric: str) -> int:
    return (SEED + zlib.crc32(f"{cell}|{metric}".encode("utf-8"))) % (2**32)


def _r(value: Any, digits: int = 5) -> Any:
    return round(value, digits) if isinstance(value, float) and math.isfinite(value) else value


def log(message: str) -> None:
    print(f"[daily_optimizer] {message}", flush=True)


# ---------------------------------------------------------------------------
# state
# ---------------------------------------------------------------------------


def empty_state(grader_signature: str, sport_versions: Mapping[str, str] | None = None) -> dict[str, Any]:
    return {"version": OPTIMIZER_VERSION, "grader_signature": grader_signature,
            "sport_versions": dict(sport_versions or {}), "games": {}, "pub": {}, "resets": []}


def load_state(payload: Any, grader_signature: str, *, sport_versions: Mapping[str, str] | None = None,
               now: datetime | None = None) -> tuple[dict[str, Any], str | None]:
    """The saved state or a fresh one, under the scorecard's own reset rules (no pooling across graders)."""
    sport_versions = dict(sport_versions or {})
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")
    if not isinstance(payload, Mapping) or payload.get("version") != OPTIMIZER_VERSION:
        return empty_state(grader_signature, sport_versions), (None if payload is None else "state_version_changed")
    resets = list(payload.get("resets") or [])[-9:]
    if payload.get("grader_signature") != grader_signature:
        state = empty_state(grader_signature, sport_versions)
        state["resets"] = resets + [{"at": stamp, "reason": "grader_signature_changed"}]
        return state, "grader_signature_changed"
    state = empty_state(grader_signature, sport_versions)
    state["games"] = dict(payload.get("games") or {})
    state["pub"] = dict(payload.get("pub") or {})
    state["orders"] = dict(payload.get("orders") or {})
    state["resets"] = resets
    saved = dict(payload.get("sport_versions") or {})
    changed = sorted(s for s in set(saved) | set(sport_versions) if saved.get(s) != sport_versions.get(s))
    if not changed:
        return state, None
    state["games"] = {k: g for k, g in state["games"].items() if str(g.get("sport")) not in changed}
    state["resets"].append({"at": stamp, "reason": "sport_versions_changed", "sports": changed})
    return state, "sport_versions_changed:" + ",".join(changed)


def prune(state: dict[str, Any], today: str) -> None:
    floor = _shift(today, -RETAIN_DAYS)
    state["games"] = {k: g for k, g in state["games"].items() if str(g.get("date") or "") >= floor}
    pub_floor = _shift(today, -PUB_RETAIN_DAYS)
    state["pub"] = {k: p for k, p in state["pub"].items() if str(p.get("seen") or "") >= pub_floor}
    state["orders"] = {k: m for k, m in (state.get("orders") or {}).items() if str(m.get("seen") or "") >= floor}


# ---------------------------------------------------------------------------
# published join
# ---------------------------------------------------------------------------


def published_keys(text: str | None, bs: Any) -> set[str]:
    """Population keys of one date's published openings, built by the recorder's own key builder."""
    if not text:
        return set()
    return {str(r.get("k")) for r in bs.records_from_openings(bs.parse_openings_text(text)) if r.get("k")}


def note_published(state: dict[str, Any], day: str, records: Iterable[Mapping[str, Any]],
                   keys: set[str] | None, *, game_key: Callable[[Mapping[str, Any]], str | None],
                   pending: Any = None) -> dict[str, int]:
    """Mark, per game, which of its recorded keys the shortlist published on `day`.

    `keys=None` means the openings read FAILED: the game is marked `known: False` and stays out of
    the recommendation grade. Unknown never defaults to "not published" (learnings 2026-10-01) --
    that would grade a published bet as unpublished and quietly shrink the published column.

    `pending` (the scorecard's `state["pending"]`): only games still waiting to be graded are noted.
    A board date re-read for completeness carries tens of thousands of records of games already
    graded (39,978 `late` on 2026-10-04); noting those only grew the state (2.1 MB on the first dry run).
    """
    counts = collections.Counter()
    for record in records:
        gk = game_key(record)
        if gk is None or (pending is not None and gk not in pending):
            continue
        entry = state["pub"].setdefault(gk, {"known": True, "keys": [], "seen": day})
        entry["seen"] = max(str(entry.get("seen") or day), day)
        if keys is None:
            entry["known"] = False
            counts["unknown"] += 1
            continue
        k = str(record.get("k") or "")
        if k in keys and k not in entry["keys"]:
            entry["keys"].append(k)
            counts["published"] += 1
    return dict(counts)


# ---------------------------------------------------------------------------
# accumulation
# ---------------------------------------------------------------------------


def accumulate(graded: Iterable[Mapping[str, Any]]) -> tuple[dict[str, list[float]], dict[str, list[float]]]:
    """(calibration sums per cell, banded betting sums per cell|band) for one game's graded rows.

    cal[cell]       = [rows, sum d*d, sum d*r]
    bands[cell|b]   = [bets, wins, pnl, market ev, model bets, model pnl, model ev]   (b = an EV band, or `all`)

    market ev = p_market * odds - 1: the price against the de-vigged fair (~minus the vig unless the
    price was shopped). model ev = p_model * odds - 1: what the model PROMISED, the shortlist's own
    selection quantity. A row without p_model has no model EV, so it is counted in the market slots
    only -- never as a zero-EV model bet.
    """
    cal: dict[str, list[float]] = {}
    bands: dict[str, list[float]] = {}
    for row in graded:
        cell = cell_of(row)
        if cell is None:
            continue
        p_model, p_market, y = row.get("p_model"), row.get("p_market"), row.get("y")
        if p_model is not None and p_market is not None and y is not None:
            d, r = float(p_model) - float(p_market), float(y) - float(p_market)
            acc = cal.setdefault(cell, [0, 0.0, 0.0])
            acc[0] += 1
            acc[1] += d * d
            acc[2] += d * r
        price, pnl = row.get("price"), row.get("pnl")
        if price in (None, 0) or p_market is None or pnl is None or y is None:
            continue
        odds = _decimal_odds(float(price))
        ev = float(p_market) * odds - 1.0
        model_ev = None if p_model is None else float(p_model) * odds - 1.0
        for band in (ev_band(100.0 * ev), ALL_BAND):
            acc = bands.setdefault(f"{cell}|{band}", [0, 0, 0.0, 0.0, 0, 0.0, 0.0])
            acc[0] += 1
            acc[1] += 1 if float(y) >= 1.0 else 0
            acc[2] += float(pnl)
            acc[3] += ev
            if model_ev is not None:
                acc[4] += 1
                acc[5] += float(pnl)
                acc[6] += model_ev
    return cal, bands


def wrap_grade(grade: Callable[..., tuple[list[dict[str, Any]], dict[str, int]]], state: dict[str, Any], *,
               game_key: Callable[[Mapping[str, Any]], str | None]) -> Callable[..., Any]:
    """`grade` with the optimizer's accumulation riding along. Returns EXACTLY what `grade` returns.

    The scorecard's `grade_pending` may call this for a game and then decide it is still waiting
    for a final, so results go to `state["candidates"]` and only `commit` keeps those whose game the
    scorecard actually committed.
    """
    candidates = state.setdefault("candidates", {})

    def graded_with_optimizer(records: Sequence[Mapping[str, Any]], chips: Any, **kwargs: Any) -> Any:
        graded, ungraded = grade(records, chips, **kwargs)
        try:
            gk = next((key for key in (game_key(r) for r in records) if key), None)
            if gk is not None:
                cal, pooled = accumulate(graded)
                entry: dict[str, Any] = {"sport": gk.split("|", 1)[0], "cal": cal, "pool": pooled,
                                         "rec": {}, "pub_known": False, "pub_rows": 0}
                pub = state["pub"].get(gk)
                if pub is not None and pub.get("known"):
                    entry["pub_known"] = True
                    keys = set(pub.get("keys") or [])
                    published = [r for r in records if str(r.get("k") or "") in keys]
                    entry["pub_rows"] = len(published)
                    if published:
                        side = {k: v for k, v in kwargs.items() if k != "ungraded_by_sport"}
                        rec_graded, _ = grade(published, chips, ungraded_by_sport={}, **side)
                        entry["rec"] = accumulate(rec_graded)[1]
                candidates[gk] = entry
        except Exception as exc:  # the optimizer must never break the scorecard
            log(f"ACCUMULATE_FAILED {type(exc).__name__}: {exc}")
        return graded, ungraded

    return graded_with_optimizer


def commit(state: dict[str, Any], scorecard_games: Mapping[str, Mapping[str, Any]]) -> dict[str, int]:
    """Keep the candidates whose game the scorecard committed; drop the rest (they are re-graded later)."""
    counts = collections.Counter()
    for gk, entry in (state.pop("candidates", None) or {}).items():
        game = scorecard_games.get(gk)
        if game is None or gk in state["games"]:
            counts["not_committed"] += 1
            continue
        state["games"][gk] = {**entry, "date": str(game.get("date"))}
        state["pub"].pop(gk, None)
        counts["committed"] += 1
        counts["with_published"] += 1 if entry.get("rec") else 0
    return dict(counts)


# ---------------------------------------------------------------------------
# statistics
# ---------------------------------------------------------------------------


def _bootstrap(items: Sequence[Any], stat: Callable[[Sequence[Any]], float | None], *, seed: int,
               resamples: int) -> list[float]:
    rng = random.Random(seed)
    n = len(items)
    out: list[float] = []
    for _ in range(resamples):
        value = stat([items[rng.randrange(n)] for _ in range(n)])
        if value is not None:
            out.append(value)
    out.sort()
    return out


def _ci(samples: Sequence[float]) -> list[float] | None:
    if not samples:
        return None
    return [samples[int(0.025 * len(samples))], samples[min(len(samples) - 1, int(0.975 * len(samples)))]]


def _bh(p_values: Sequence[float], q: float) -> set[int]:
    m = len(p_values)
    order = sorted(range(m), key=lambda i: p_values[i])
    passing = 0
    for rank, index in enumerate(order, start=1):
        if p_values[index] <= q * rank / m:
            passing = rank
    return {order[r] for r in range(passing)}


def _w(parts: Sequence[Sequence[float]]) -> float | None:
    sdd = sum(p[1] for p in parts)
    return (sum(p[2] for p in parts) / sdd) if sdd > 0 else None


def fit_calibration(games: Sequence[Mapping[str, Any]], *, resamples: int = RESAMPLES) -> list[dict[str, Any]]:
    """Per cell: w*, its game-bootstrap CI, a one-sided p for w* < 1, LODO and FDR. Sorted canonically."""
    per_cell: dict[str, list[tuple[str, str, list[float]]]] = collections.defaultdict(list)
    for game in games:
        for cell, acc in (game.get("cal") or {}).items():
            if acc and acc[0]:
                per_cell[cell].append((str(game.get("date")), str(game.get("key")), acc))
    results: list[dict[str, Any]] = []
    for cell, entries in sorted(per_cell.items()):
        entries.sort(key=lambda e: (e[0], e[1]))  # resampling by index: order must not depend on read order
        accs = [acc for _, _, acc in entries]
        dates = sorted({day for day, _, _ in entries})
        rows = int(sum(a[0] for a in accs))
        sdd, sdr = sum(a[1] for a in accs), sum(a[2] for a in accs)
        w = _w(accs)
        result: dict[str, Any] = {
            "cell": cell, "games": len(entries), "dates": len(dates), "rows": rows, "w": _r(w),
            # Brier relative to the market, per row: the model as is, and at the fitted w (clipped to [0, 1]).
            "brier_model_minus_market": _r((sdd - 2 * sdr) / rows) if rows else None,
        }
        w_clip = None if w is None else min(1.0, max(0.0, w))
        result["brier_at_w_minus_market"] = _r((w_clip * w_clip * sdd - 2 * w_clip * sdr) / rows) if rows and w_clip is not None else None
        samples = _bootstrap(accs, _w, seed=_seed(cell, "w"), resamples=resamples) if w is not None and len(accs) > 1 else []
        result["ci95"] = [_r(v) for v in _ci(samples)] if samples else None
        result["p_lt_1"] = _r(max(1.0 / resamples, sum(1 for s in samples if s >= 1.0) / len(samples))) if samples else None
        lodo = []
        for day in dates:
            rest = [acc for d, _, acc in entries if d != day]
            lodo.append(_w(rest) if rest else None)
        result["lodo_all_below_1"] = bool(len(dates) >= 2 and lodo and all(v is not None and v < 1.0 for v in lodo))
        results.append(result)
    eligible = [r for r in results if r["games"] >= MIN_GAMES and r["dates"] >= MIN_DATES and r["p_lt_1"] is not None]
    passing = _bh([r["p_lt_1"] for r in eligible], FDR_Q)
    for index, result in enumerate(eligible):
        result["fdr_pass"] = index in passing
    for result in results:
        ok = (result.get("fdr_pass") and result["lodo_all_below_1"] and result["ci95"] is not None
              and result["ci95"][1] < 1.0)
        result["verdict"] = ("overconfident" if ok else
                             "insufficient" if result["games"] < MIN_GAMES or result["dates"] < MIN_DATES else
                             "not_proven")
        result["edge_shrink"] = _r(max(FACTOR_FLOOR, min(1.0, result["ci95"][1]))) if ok else None
    return results


def _roi_gap(parts: Sequence[Sequence[float]]) -> float | None:
    """Realised ROI minus the MODEL's predicted EV, over the bets that carry a model EV."""
    bets = sum(p[4] for p in parts)
    return ((sum(p[5] for p in parts) - sum(p[6] for p in parts)) / bets) if bets else None


def grade_bands(games: Sequence[Mapping[str, Any]], field: str, *, resamples: int = RESAMPLES) -> list[dict[str, Any]]:
    """Per cell|band: bets, hit rate, ROI, the model's predicted EV and the market's, realised-minus-predicted
    (model) with a game CI. `predicted_ev`/`model_roi` are over `model_bets` (rows with a p_model)."""
    per_key: dict[str, list[tuple[str, str, list[float]]]] = collections.defaultdict(list)
    for game in games:
        for key, acc in (game.get(field) or {}).items():
            if acc and acc[0]:
                per_key[key].append((str(game.get("date")), str(game.get("key")), acc))
    results: list[dict[str, Any]] = []
    for key, entries in sorted(per_key.items()):
        entries.sort(key=lambda e: (e[0], e[1]))
        accs = [acc for _, _, acc in entries]
        dates = sorted({day for day, _, _ in entries})
        bets = int(sum(a[0] for a in accs))
        model_bets = int(sum(a[4] for a in accs))
        cell, band = key.rsplit("|", 1)
        gap = _roi_gap(accs)
        result: dict[str, Any] = {
            "cell": cell, "band": band, "games": len(entries), "dates": len(dates), "bets": bets,
            "hit_rate": _r(sum(a[1] for a in accs) / bets) if bets else None,
            "roi": _r(sum(a[2] for a in accs) / bets) if bets else None,
            "market_ev": _r(sum(a[3] for a in accs) / bets) if bets else None,
            "model_bets": model_bets,
            "model_roi": _r(sum(a[5] for a in accs) / model_bets) if model_bets else None,
            "predicted_ev": _r(sum(a[6] for a in accs) / model_bets) if model_bets else None,
            "realised_minus_predicted": _r(gap),
        }
        samples = _bootstrap(accs, _roi_gap, seed=_seed(key, field), resamples=resamples) if len(accs) > 1 else []
        result["gap_ci95"] = [_r(v) for v in _ci(samples)] if samples else None
        result["p_gap_lt_0"] = _r(max(1.0 / resamples, sum(1 for s in samples if s >= 0.0) / len(samples))) if samples else None
        lodo = [_roi_gap([acc for d, _, acc in entries if d != day]) for day in dates]
        result["lodo_all_below_0"] = bool(len(dates) >= 2 and all(v is not None and v < 0 for v in lodo))
        results.append(result)
    return results


def stake_scales(rec: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """Validated stake multipliers from the PUBLISHED `all` band: realised significantly below predicted."""
    rows = [r for r in rec if r["band"] == ALL_BAND and r["games"] >= MIN_GAMES and r["dates"] >= MIN_DATES
            and r["p_gap_lt_0"] is not None]
    passing = _bh([r["p_gap_lt_0"] for r in rows], FDR_Q)
    out: dict[str, dict[str, Any]] = {}
    for index, r in enumerate(rows):
        ev, ci = r["predicted_ev"], r["gap_ci95"]
        if index not in passing or not r["lodo_all_below_0"] or not ci or ci[1] >= 0 or not ev or ev <= 0:
            continue
        out[r["cell"]] = {"factor": _r(max(FACTOR_FLOOR, min(1.0, (ev + ci[1]) / ev))), "games": r["games"],
                          "dates": r["dates"], "bets": r["bets"], "predicted_ev": ev, "roi": r["roi"], "gap_ci95": ci}
    return out


# ---------------------------------------------------------------------------
# staked orders -- what the portfolio ACTUALLY bet (lane published-negative-ev, 2026-10-06)
# ---------------------------------------------------------------------------
#
# The published column above is most of the board (40-86% of recorded keys on 2026-10-05), not the
# recommendation set. The recommendation set is the paper portfolio: execution-ledger orders on the
# portfolio book (venue `paper`). Each is graded flat-stake per unit, pnl / stake, against the EV the
# portfolio ADMITTED it on (`ev_pct` at entry). Its cell and book count come from the published
# opening it was placed on (`opening_key`), recorded in the state the day that opening is read.

STAKED_FIELD = "staked"
PORTFOLIO_VENUE = "paper"
SETTLED_OUTCOMES = {"won": 1, "win": 1, "lost": 0, "loss": 0, "push": 0}


def books_band(books: Any) -> str:
    try:
        n = int(float(books))
    except (TypeError, ValueError):
        return "books_na"
    return "books1-2" if n <= 2 else "books3-4" if n <= 4 else "books5-7" if n <= 7 else "books8+"


def portfolio_orders(orders: Iterable[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """Portfolio-book paper orders (the venue-comparison books are excluded)."""
    return [o for o in orders if isinstance(o, Mapping) and str(o.get("mode") or "") == "paper"
            and str(o.get("venue") or "") == PORTFOLIO_VENUE]


def note_orders(state: dict[str, Any], text: str | None, bs: Any, wanted: set[str]) -> int:
    """Record cell / book count for each wanted opening key found in one date's openings text."""
    if not text or not wanted:
        return 0
    from syndicate.features.shared.measured_bucket_skill import _phase

    meta = state.setdefault("orders", {})
    added = 0
    for opening in bs.parse_openings_text(text):
        key = opening.get("key")
        if key not in wanted or key in meta:
            continue
        sport = str(opening.get("sport") or "").strip().lower()
        market = str(opening.get("market") or "").strip().lower()
        segment = str(opening.get("segment") or "full").strip().lower() or "full"
        phase = _phase(opening.get("game_state"), sighted_at=opening.get("captured_at"),
                       commence_time=opening.get("commence_time"))
        meta[key] = {"cell": f"{sport}|{market}|{segment}|{phase}", "books": opening.get("books_quoting"),
                     "seen": str(opening.get("captured_at") or "")[:10]}
        added += 1
    return added


def _num(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def staked_games(state: Mapping[str, Any], orders: Iterable[Mapping[str, Any]], today: str,
                 days: int = WINDOW_DAYS) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Settled portfolio orders as pseudo-games (date, event) carrying `staked` accumulators.

    Same 7-slot shape as `accumulate`'s bands, per unit stake: [bets, wins, pnl, ev, bets, pnl, ev].
    The "model" slots hold the EV the portfolio admitted the bet on, so `grade_bands` / `stake_scales`
    measure realised minus PROMISED on exactly what was staked. Bands: `all`, book count, basis.
    """
    meta = state.get("orders") or {}
    floor = _shift(today, -days)
    games: dict[tuple[str, str], dict[str, Any]] = {}
    counts: collections.Counter = collections.Counter()
    for order in portfolio_orders(orders):
        outcome = str(order.get("outcome") or "").strip().lower()
        if outcome not in SETTLED_OUTCOMES:
            continue
        day = str(order.get("selected_date") or "")
        if not (floor <= day <= today):
            continue
        stake, pnl, ev = _num(order.get("fill_stake_dollars")), _num(order.get("pnl_dollars")), _num(order.get("ev_pct"))
        if not stake or pnl is None or ev is None:
            counts["unpriced"] += 1
            continue
        info = meta.get(str(order.get("opening_key") or ""))
        if info is None:
            counts["unjoined"] += 1
            continue
        counts["graded"] += 1
        basis = "model" if _num(order.get("model_edge_pct")) is not None else "market_only"
        unit_pnl, unit_ev = pnl / stake, ev / 100.0
        win = SETTLED_OUTCOMES[outcome]
        event = str(order.get("event_id") or order.get("position_key") or "")
        game = games.setdefault((day, event), {"date": day, "key": f"{day}|{event}",
                                               "sport": str(order.get("sport") or "").lower(), STAKED_FIELD: {}})
        for band in (ALL_BAND, books_band(info.get("books")), basis):
            acc = game[STAKED_FIELD].setdefault(f"{info['cell']}|{band}", [0, 0, 0.0, 0.0, 0, 0.0, 0.0])
            acc[0] += 1
            acc[1] += win
            acc[2] += unit_pnl
            acc[3] += unit_ev
            acc[4] += 1
            acc[5] += unit_pnl
            acc[6] += unit_ev
    return list(games.values()), dict(counts)


def _pooled_bands(rows: Sequence[Mapping[str, Any]], band: str) -> dict[str, Any]:
    picked = [r for r in rows if r["band"] == band]
    bets = sum(r["bets"] for r in picked)
    if not bets:
        return {"bets": 0}
    roi = sum((r["roi"] or 0) * r["bets"] for r in picked) / bets
    model_bets = sum(r["model_bets"] for r in picked)
    ev = sum((r["predicted_ev"] or 0) * r["model_bets"] for r in picked) / model_bets if model_bets else 0.0
    return {"bets": bets, "roi": _r(roi), "predicted_ev": _r(ev), "realised_minus_predicted": _r(roi - ev)}


# ---------------------------------------------------------------------------
# overlay
# ---------------------------------------------------------------------------


def overlay_payload(calibration: Sequence[Mapping[str, Any]], stakes: Mapping[str, Mapping[str, Any]], *,
                    now: datetime, window: str) -> dict[str, Any]:
    shrink = {r["cell"]: {"factor": r["edge_shrink"], "w": r["w"], "ci95": r["ci95"], "games": r["games"],
                          "dates": r["dates"]}
              for r in calibration if r.get("edge_shrink") is not None}
    # Strongest evidence first when capping: the most games.
    shrink = dict(sorted(shrink.items(), key=lambda kv: (-kv[1]["games"], kv[0]))[:MAX_ENTRIES])
    stakes = dict(sorted(stakes.items(), key=lambda kv: (-kv[1]["games"], kv[0]))[:MAX_ENTRIES])
    return {
        "source": SOURCE, "version": OPTIMIZER_VERSION, "window": window,
        "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "expires_at": (now + timedelta(hours=OVERLAY_TTL_HOURS)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "rails": {"factor_floor": FACTOR_FLOOR, "factor_ceiling": 1.0, "min_games": MIN_GAMES,
                  "min_dates": MIN_DATES, "fdr_q": FDR_Q, "applies_to": "rank_and_stake_only",
                  "never": "withhold, remove or gate a line (2026-10-05 PRIME DIRECTIVE)"},
        "edge_shrink": shrink,
        "stake_scale": stakes,
    }


def validate_overlay(payload: Any, *, now: datetime | None = None) -> tuple[dict[str, dict[str, float]] | None, str]:
    """Consumer-side re-check of every rail. ({"edge_shrink": {cell: f}, "stake_scale": {cell: f}}, "ok") or (None, why)."""
    now = now or datetime.now(timezone.utc)
    if not isinstance(payload, Mapping) or payload.get("source") != SOURCE:
        return None, "unknown_source"
    try:
        expires = datetime.fromisoformat(str(payload.get("expires_at")).replace("Z", "+00:00"))
    except ValueError:
        return None, "no_expiry"
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if expires <= now:
        return None, "expired"
    table: dict[str, dict[str, float]] = {}
    for kind in ("edge_shrink", "stake_scale"):
        entries = payload.get(kind)
        if not isinstance(entries, Mapping) or len(entries) > MAX_ENTRIES:
            return None, f"malformed_{kind}"
        table[kind] = {}
        for cell, entry in entries.items():
            if str(cell).count("|") != 3 or not isinstance(entry, Mapping):
                return None, f"malformed_{kind}_cell"
            factor = entry.get("factor")
            if isinstance(factor, bool) or not isinstance(factor, (int, float)) or not FACTOR_FLOOR <= factor <= 1.0:
                return None, f"{kind}_factor_out_of_rails"
            if int(entry.get("games") or 0) < MIN_GAMES or int(entry.get("dates") or 0) < MIN_DATES:
                return None, f"{kind}_below_sample_floor"
            table[kind][str(cell)] = float(factor)
    return table, "ok"


# ---------------------------------------------------------------------------
# report
# ---------------------------------------------------------------------------


def window_games(state: Mapping[str, Any], today: str, days: int = WINDOW_DAYS) -> list[dict[str, Any]]:
    floor = _shift(today, -days)
    return [{**game, "key": key} for key, game in sorted(state["games"].items())
            if floor <= str(game.get("date") or "") < today]


def _sum_bands(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    bets = sum(r["bets"] for r in rows)
    if not bets:
        return {"bets": 0}
    roi = sum((r["roi"] or 0) * r["bets"] for r in rows) / bets
    market_ev = sum((r["market_ev"] or 0) * r["bets"] for r in rows) / bets
    out = {"bets": bets, "roi": _r(roi), "market_ev": _r(market_ev), "realised_minus_market": _r(roi - market_ev)}
    model_bets = sum(r["model_bets"] for r in rows)
    out["model_bets"] = model_bets
    if model_bets:
        model_roi = sum((r["model_roi"] or 0) * r["model_bets"] for r in rows) / model_bets
        ev = sum((r["predicted_ev"] or 0) * r["model_bets"] for r in rows) / model_bets
        out.update(predicted_ev=_r(ev), realised_minus_predicted=_r(model_roi - ev))
    return out


def build_report(state: Mapping[str, Any], *, today: str, now: datetime, run: Mapping[str, Any] | None = None,
                 resamples: int = RESAMPLES,
                 orders: Sequence[Mapping[str, Any]] | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    games = window_games(state, today)
    calibration = fit_calibration(games, resamples=resamples)
    rec = grade_bands(games, "rec", resamples=resamples)
    pool = grade_bands(games, "pool", resamples=resamples)
    # STAKE SCALE comes from what was STAKED, never from the published board (2026-10-06). Orders
    # unavailable (None) -> no stake-scale entries, rather than a fallback to the board.
    staked_rows: list[dict[str, Any]] = []
    staked_counts: dict[str, int] = {"orders_unavailable": 1} if orders is None else {}
    if orders is not None:
        staked_list, staked_counts = staked_games(state, orders, today)
        staked_rows = grade_bands(staked_list, STAKED_FIELD, resamples=resamples)
    stakes = stake_scales(staked_rows)
    overlay = overlay_payload(calibration, stakes, now=now, window=f"{WINDOW_DAYS}d")

    by_sport: dict[str, dict[str, Any]] = {}
    for sport in sorted({str(g.get("sport")) for g in games}):
        sport_games = [g for g in games if g.get("sport") == sport]
        cal_rows = [r for r in calibration if r["cell"].startswith(sport + "|")]
        rows = sum(r["rows"] for r in cal_rows)
        sdd_weighted = [r for r in cal_rows if r["w"] is not None]
        by_sport[sport] = {
            "games": len(sport_games),
            "dates": len({g.get("date") for g in sport_games}),
            "games_with_published_known": sum(1 for g in sport_games if g.get("pub_known")),
            "model_rows": rows,
            "model_brier_minus_market": _r(sum((r["brier_model_minus_market"] or 0) * r["rows"] for r in cal_rows) / rows) if rows else None,
            "cells": len(cal_rows),
            "cells_overconfident": sum(1 for r in cal_rows if r["verdict"] == "overconfident"),
            "cells_with_w": len(sdd_weighted),
            "staked": _pooled_bands([r for r in staked_rows if r["cell"].startswith(sport + "|")], ALL_BAND),
            "recommended": _sum_bands([r for r in rec if r["band"] == ALL_BAND and r["cell"].startswith(sport + "|")]),
            "pooled": _sum_bands([r for r in pool if r["band"] == ALL_BAND and r["cell"].startswith(sport + "|")]),
        }
    report = {
        "version": OPTIMIZER_VERSION, "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "today": today,
        "window": {"days": WINDOW_DAYS, "games": len(games), "dates": len({g.get("date") for g in games}),
                   "first_date": min((g["date"] for g in games), default=None)},
        "method": {"calibration": "w* = sum(d*r)/sum(d*d), d = p_model - p_market, r = y - p_market; game bootstrap",
                   "recommended": "shortlist-published rows (clv_openings joined on population key), graded at "
                                  "their first recorded sighting; pooled = every priced row, same grader",
                   "min_games": MIN_GAMES, "min_dates": MIN_DATES, "fdr_q": FDR_Q, "resamples": resamples},
        "by_sport": by_sport,
        "calibration": calibration,
        "recommended": rec,
        "pooled": pool,
        "staked": staked_rows,
        "staked_counts": staked_counts,
        "staked_summary": {band: _pooled_bands(staked_rows, band) for band in
                           (ALL_BAND, "market_only", "model", "books1-2", "books3-4", "books5-7", "books8+", "books_na")},
        "overlay": overlay,
        "run": dict(run or {}),
        "resets": list(state.get("resets") or []),
    }
    report["markdown"] = markdown(report)
    return report, overlay


def _pct(value: Any) -> str:
    return "-" if value is None else f"{100 * value:+.1f}%"


def markdown(report: Mapping[str, Any]) -> str:
    w = report["window"]
    lines = [f"# Daily optimizer -- {report['today']}", "",
             f"Window {w['days']}d nominal: {w['games']} graded games over {w['dates']} dates (first {w['first_date']}).",
             "", "| sport | games | model Brier - market | cells (overconfident) | published bets | pub ROI | "
                 "pub model EV | pub market EV | pooled bets | pooled ROI |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for sport, s in report["by_sport"].items():
        rec, pool = s["recommended"], s["pooled"]
        brier = "-" if s["model_brier_minus_market"] is None else f"{s['model_brier_minus_market']:+.4f}"
        lines.append(f"| {sport} | {s['games']} | {brier} | {s['cells']} ({s['cells_overconfident']}) | "
                     f"{rec.get('bets', 0)} | {_pct(rec.get('roi'))} | {_pct(rec.get('predicted_ev'))} | "
                     f"{_pct(rec.get('market_ev'))} | {pool.get('bets', 0)} | {_pct(pool.get('roi'))} |")
    lines += ["", "Model EV = p_model x odds - 1 (what the model promised); market EV = de-vigged fair x odds - 1 "
                  "(~minus the vig unless the price was shopped)."]
    staked = report.get("staked_summary") or {}
    if staked:
        lines += ["", "## Staked (the paper portfolio -- what was actually bet)", "",
                  f"Settled orders graded: {(report.get('staked_counts') or {}).get('graded', 0)} "
                  f"(unjoined {(report.get('staked_counts') or {}).get('unjoined', 0)}). Flat stake per unit vs the EV "
                  "each was admitted on.", "", "| slice | bets | ROI | predicted EV | realised - predicted |",
                  "|---|---|---|---|---|"]
        for band, row in staked.items():
            if row.get("bets"):
                lines.append(f"| {band} | {row['bets']} | {_pct(row.get('roi'))} | {_pct(row.get('predicted_ev'))} | "
                             f"{_pct(row.get('realised_minus_predicted'))} |")
        for sport, srow in report["by_sport"].items():
            st_ = srow.get("staked") or {}
            if st_.get("bets"):
                lines.append(f"| {sport} | {st_['bets']} | {_pct(st_.get('roi'))} | {_pct(st_.get('predicted_ev'))} | "
                             f"{_pct(st_.get('realised_minus_predicted'))} |")
    overlay = report["overlay"]
    lines += ["", f"Overlay: {len(overlay['edge_shrink'])} edge-shrink, {len(overlay['stake_scale'])} stake-scale "
                  f"entries (rank/stake only; never withholds). Expires {overlay['expires_at']}."]
    for cell, e in list(overlay["edge_shrink"].items())[:15]:
        lines.append(f"- shrink {cell}: x{e['factor']} (w*={e['w']}, CI {e['ci95']}, {e['games']}g/{e['dates']}d)")
    for cell, e in list(overlay["stake_scale"].items())[:15]:
        lines.append(f"- stake {cell}: x{e['factor']} (staked ROI {_pct(e['roi'])} vs admitted EV {_pct(e['predicted_ev'])}, {e['games']}g)")
    return "\n".join(lines) + "\n"


def dumps(payload: Any) -> str:
    return json.dumps(payload, indent=1, sort_keys=True, default=str)
