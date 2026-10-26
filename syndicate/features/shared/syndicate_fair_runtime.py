"""Syndicate Fair v1 at RECORD time -- shadow only (Decision Engine `#736`, lane `syndicate-decision-engine`).

**RECORDED, NEVER USED.** The DecisionRecord stores what this module returns (`FairV1View`) beside the
Shin-consensus fair it actually decides on. Nothing reads it for EV, pricing, gates or stakes: the user's
words (2026-10-26) were "Never use p_fair_v1 for EV, pricing or staking", and stage 1 measured why -- v1
wins held-out log loss in 4 of 13 families but sits slightly FURTHER from the close in absolute pp, and EV is
linear in p (`.syndicate/findings_2026-10-26_syndicate_fair_v1.md`). What is worth recording is `sigma_fair`
(its +/-1 sigma coverage was 0.70-0.74 against a nominal 0.683), the input a lower-bound EV will need.

WHERE THE INPUTS COME FROM
--------------------------
* The fitted weights: `<data root>/reports/syndicate_fair/syndicate_fair_v1_params.json`, written by
  `scripts/publish_syndicate_fair_params.py` from the stage-1 walk-forward's LAST fold (the model whose
  held-out score the findings report). Only the families that PASSED stage 1 are in it.
* Every book's two-sided price and when it was observed: the book grid
  (`<sport>_source/data/book_grid/book_grid_<date>.json`), the same pivot of the quote log the fit's extract
  read. A board row carries every book's price for ITS side only (`quote.book_prices`) and one best price for
  the other side, which cannot de-vig a book.

PARITY WITH THE FIT (`scripts/syndicate_fair_fit.py`, which is what was scored)
--------------------------------------------------------------------------------
Same canonical outcome order, same per-book Shin de-vig (`opportunity_signals.devig`), the same 12h quote-age
cut, MIN_BOOKS = 2, family = sport|season_phase|kind with the phase of the CENTRAL commence date, and the
time-to-start bucket nearest (on a log scale) to the fit's four snapshots. Rows more than 36h out or already
started are outside what was fitted and get a reason, not a number. Quote age is now minus the latest
`observed_at` of the book's sides; the fit used the quote log's capture time of the last change -- the same
instant whenever the grid is fresh.

Log weights are summed from `term_index` directly, so the worker needs numpy and not scipy.
"""

from __future__ import annotations

import json
import math
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

PARAMS_RELPATH = Path("reports") / "syndicate_fair" / "syndicate_fair_v1_params.json"
MAX_HOURS_TO_START = 36.0
MIN_BOOKS = 2
# The fit's snapshots (seconds before commence) and the log-midpoints between neighbours.
_SNAPSHOTS: tuple[tuple[str, int], ...] = (("t24h", 24 * 3600), ("t6h", 6 * 3600), ("t2h", 2 * 3600), ("t30m", 1800))
_CANONICAL_ORDERS: tuple[tuple[str, ...], ...] = (("home", "away", "draw"), ("home", "away"), ("over", "under"),
                                                  ("yes", "no"))
_CENTRAL_OFFSET_FALLBACK = timedelta(hours=-5)


def canonical_sides(sides: Iterable[str]) -> tuple[str, ...] | None:
    """The line's outcome set in a fixed order (outcome 0 = home / over / yes), or None. Same as the fit's."""
    s = {str(x) for x in sides}
    if s == {"home", "away", "draw"}:
        return _CANONICAL_ORDERS[0]
    for order in _CANONICAL_ORDERS[1:]:
        if s == set(order):
            return order
    return None


def tts_bucket(seconds_to_start: float) -> str | None:
    """The fitted snapshot nearest on a log scale; None when started or beyond MAX_HOURS_TO_START."""
    if seconds_to_start <= 0 or seconds_to_start > MAX_HOURS_TO_START * 3600:
        return None
    best = min(_SNAPSHOTS, key=lambda s: abs(math.log(seconds_to_start) - math.log(s[1])))
    return best[0]


def _epoch(value: Any) -> float | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return None


def _central_date(ts: float) -> str:
    try:
        from zoneinfo import ZoneInfo

        return datetime.fromtimestamp(ts, tz=ZoneInfo("America/Chicago")).date().isoformat()
    except Exception:  # noqa: BLE001 -- no tzdata: a fixed CDT offset is right for the whole regular season
        return (datetime.fromtimestamp(ts, tz=timezone.utc) + _CENTRAL_OFFSET_FALLBACK).date().isoformat()


def _norm(value: Any) -> str:
    return str(value or "").strip().casefold()


def _norm_segment(value: Any) -> str:
    seg = _norm(value)
    return "full" if seg in ("", "full_game", "game") else seg


def _line(value: Any) -> float | None:
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(x) else round(x, 2)


def grid_key(event_id: Any, market: Any, segment: Any, player: Any, line: Any) -> tuple:
    """A grid row's identity. A SPREADS grid row's `line` is the AWAY handicap (measured: every book cell has
    home == -away), so callers holding a home side's line must negate it first (`record_grid_key`)."""
    return (str(event_id or ""), _norm(market), _norm_segment(segment), _norm(player), _line(line))


def record_grid_key(sport: str, event_id: Any, market: Any, segment: Any, player: Any, side: Any, line: Any) -> tuple:
    ln = _line(line)
    if _norm(market) in ("spreads", "spread") and _norm(side) == "home" and ln is not None:
        ln = round(-ln, 2)
    return grid_key(event_id, market, segment, player, ln)


# ----------------------------------------------------------------------------- the per-build runtime


@dataclass
class Runtime:
    """Loaded once per record build: the fitted families and an index of the book grids they need."""

    version: str | None = None
    families: dict[str, dict[str, Any]] = field(default_factory=dict)
    grid: dict[tuple, dict[str, Any]] = field(default_factory=dict)
    grid_files: list[str] = field(default_factory=list)
    load_error: str | None = None


def load_params(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _index_grid(path: Path, kinds_by_sport: Mapping[str, set], sport: str, into: dict[tuple, dict[str, Any]]) -> bool:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    kinds = kinds_by_sport.get(sport) or set()
    for row in payload.get("rows") or []:
        if not isinstance(row, Mapping) or str(row.get("kind") or "") not in kinds:
            continue
        sides = canonical_sides(row.get("sides") or [])
        commence = _epoch(row.get("commence_time"))
        key = grid_key(row.get("event_id"), row.get("market"), row.get("segment"), row.get("player_name"), row.get("line"))
        if sides is None and row.get("sides"):
            # Quoted on one side only (measured 10-26: NHL GOALS over, 129 of 138 unmatched in-window lines). The
            # fit could not de-vig these either; keep the key so the reason says so instead of "no_grid_line".
            into.setdefault(key, {"one_sided": True, "updated": 0.0})
            continue
        if sides is None or commence is None:
            continue
        books: dict[str, dict[str, tuple[Any, float | None]]] = {}
        for book, cell in (row.get("cells") or {}).items():
            if not isinstance(cell, Mapping):
                continue
            per_side = {}
            for sd in sides:
                q = cell.get(sd)
                if isinstance(q, Mapping) and q.get("price") is not None:
                    per_side[sd] = (q.get("price"), _epoch(q.get("observed_at")))
            if len(per_side) == len(sides):
                books[str(book)] = per_side
        updated = _epoch(row.get("updated_at")) or 0.0
        held = into.get(key)
        if held is None or held.get("one_sided") or updated >= held["updated"]:
            into[key] = {"sport": sport, "kind": str(row.get("kind") or ""), "sides": sides, "commence": commence,
                         "market": row.get("market"), "segment": row.get("segment"), "books": books, "updated": updated}
    return True


def load_runtime(selected_date: str, data_root: Path) -> Runtime:
    """Params + the grids of the selected date and the next (the 36h window). Never raises."""
    rt = Runtime()
    params = load_params(Path(data_root) / PARAMS_RELPATH)
    if not params or not isinstance(params.get("families"), Mapping):
        rt.load_error = "no_params"
        return rt
    rt.version = str(params.get("version") or "") or None
    rt.families = {str(k): dict(v) for k, v in params["families"].items() if isinstance(v, Mapping)}
    kinds_by_sport: dict[str, set] = {}
    for fam in rt.families:
        sport, _phase, kind = (fam.split("|") + ["", ""])[:3]
        kinds_by_sport.setdefault(sport, set()).add(kind)
    try:
        day = datetime.fromisoformat(str(selected_date)[:10]).date()
    except ValueError:
        rt.load_error = "bad_selected_date"
        return rt
    for sport in sorted(kinds_by_sport):
        for d in (day, day + timedelta(days=1)):
            path = Path(data_root) / f"{sport}_source" / "data" / "book_grid" / f"book_grid_{d.isoformat()}.json"
            if path.is_file() and _index_grid(path, kinds_by_sport, sport, rt.grid):
                rt.grid_files.append(str(path))
    return rt


# ----------------------------------------------------------------------------- scoring one line


@dataclass
class Score:
    p_fair_v1: float | None = None
    sigma_fair_v1: float | None = None
    p_shin_median: float | None = None
    family: str | None = None
    tts: str | None = None
    books_used: int | None = None
    books_dropped: int | None = None
    reason: str | None = None


def _devig(prices: Sequence[Any]) -> list[float] | None:
    from syndicate.features.shared.opportunity_signals import devig

    out = devig(list(prices), method="shin")
    return None if out is None else [float(x) for x in out]


def score(rt: Runtime, *, sport: str, kind: str, event_id: Any, market: Any, segment: Any, player: Any,
          side: Any, line: Any, commence_time: Any, now: datetime) -> Score:
    """v1's fair and sigma for ONE side of one line, or a Score whose `reason` says why not."""
    import numpy as np

    from syndicate.features.shared import season_phase
    from syndicate.features.shared import syndicate_fair as sf

    out = Score()
    if rt.load_error:
        out.reason = rt.load_error
        return out
    commence = _epoch(commence_time)
    if commence is None:
        out.reason = "no_commence_time"
        return out
    phase = season_phase.season_phase(sport, _central_date(commence))
    family = f"{_norm(sport)}|{phase}|{_norm(kind)}"
    out.family = family
    fam = rt.families.get(family)
    if fam is None:
        out.reason = "not_a_v1_family"
        return out
    tts = tts_bucket(commence - now.timestamp())
    if tts is None:
        out.reason = "in_play" if commence <= now.timestamp() else "outside_fitted_window"
        return out
    out.tts = tts
    entry = rt.grid.get(record_grid_key(sport, event_id, market, segment, player, side, line))
    if entry is None:
        out.reason = "no_grid_line" if rt.grid_files else "no_book_grid"
        return out
    if entry.get("one_sided"):
        out.reason = "one_sided_line"
        return out
    sides = entry["sides"]
    side_norm = _norm(side)
    if side_norm not in sides:
        out.reason = "side_not_on_grid_line"
        return out
    k, j = len(sides), sides.index(side_norm)
    fitted = set(fam["books"])
    books_here, dropped = [], 0
    for book, per_side in entry["books"].items():
        if book not in fitted:
            dropped += 1
            continue
        observed = [per_side[sd][1] for sd in sides]
        if any(t is None for t in observed):
            dropped += 1
            continue
        age = now.timestamp() - max(observed)
        if age > sf.MAX_AGE_S:
            dropped += 1
            continue
        probs = _devig([per_side[sd][0] for sd in sides])
        if probs is None:
            dropped += 1
            continue
        books_here.append((book, max(0.0, float(age)), probs))
    out.books_used, out.books_dropped = len(books_here), dropped
    if len(books_here) < MIN_BOOKS:
        out.reason = "under_min_books"
        return out
    mfam = sf.market_family(str(entry.get("market") or market), str(entry.get("segment") or segment), _norm(kind))
    ds = sf.build_dataset([{"books": books_here, "mfam": mfam, "tts": tts, "t": [0.0] * k}], fam["books"], target_key="t")
    model = sf.WeightModel(fam["books"])
    theta = np.asarray(fam["theta"], dtype=float)
    if theta.shape != (model.n_params,):
        out.reason = "params_shape_mismatch"
        return out
    model.theta = theta
    log_w = np.sum([theta[ix] for ix in model.term_index(ds)], axis=0)
    p, _z, pi = sf.pooled(ds, log_w)
    r2 = {}
    for cell, value in (fam.get("r2") or {}).items():
        m_name, t_name = (str(cell).split("|") + [""])[:2]
        if m_name in sf.MARKET_FAMILIES and t_name in sf.TTS_BUCKETS:
            r2[(sf.MARKET_FAMILIES.index(m_name), sf.TTS_BUCKETS.index(t_name))] = float(value)
    sigma = sf.sigma_fair(ds, p, pi, r2)
    med = [statistics.median(probs[i] for _b, _a, probs in books_here) for i in range(k)]
    out.p_fair_v1 = round(float(p[0, j]), 6)
    out.sigma_fair_v1 = round(float(sigma[0, j]), 6)
    out.p_shin_median = round(med[j] / sum(med), 6)
    return out
