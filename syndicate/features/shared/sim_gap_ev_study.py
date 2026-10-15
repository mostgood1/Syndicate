"""Sim gap x EV: what the sim's disagreement with the market was worth, and where the sim is wrong.

Lane `sim-gap-ev-study` `[2026-10-15]`. USER REQUEST, verbatim: "how much have we examined any
correlations around how far sims are off by? and correlations around EV%? and connecting them
together in buckets around ROI and accuracy in general?", then "also add the daily version to the
fleet", with the standing rule that came between them: "we really need to always be thinking about
not only betting edges, but how do we make our sim engines better with any and all data we have".

WHY IT EXISTS. Each axis was measured alone -- the scorecard's `disagreement` bucket, the
optimizer's EV bands -- and `measured_bucket_skill` is explicit that it is "never a cross-product".
So "is a +5% EV bet better when the sim agrees?" had no instrument, and neither did "which of the
sim's misses are engine faults?".

WHERE IT RUNS. Inside `scripts/publish_model_scorecard.py`, on the SAME graded rows: `wrap_grade`
rides the scorecard's `grade` the way `daily_optimizer.wrap_grade` does, and `commit` keeps only
games the scorecard committed. The extra grading below (lead-time partitions, the big-miss list)
goes through the UNWRAPPED grader, so the optimizer's accumulation never sees a partial game.

TWO READS, PRE-REGISTERED in the lane block (commit ca52ea13) before any run:

(A) BETTING. Per cell x |gap| band x direction (sim FOR or AGAINST the side, or `nosim`) x EV
    band: bets, hit rate, ROI at the recorded price, mean EV, and a 95% CI from a game bootstrap.
    A cell is a SIGNAL only when its CI excludes 0 with >= MIN_GAMES games, and every table
    reports how many cells were tested next to how many passed. H1: inside one EV band, FOR does
    not beat AGAINST.

(B) ENGINE -- where the sim is wrong, in terms an engine owner can act on:
    - trust curve: w in p = fair + w * (sim - fair) per |gap| band. w ~ 1 trust the sim, ~ 0 its
      deviation is noise, < 0 it is anti-informative. H2: w FALLS as |gap| grows.
    - mean vs spread: the calibration slope of outcome on the sim's probability (< 1 means the
      sim is overconfident: its distribution is too narrow or its inputs too extreme), next to
      the market's own slope on the same rows, and the mean miss on near-even lines (0.4-0.6),
      which is the sim's MEAN being off.
    - lead time: w and the Brier gap by how long before the start a side was first priced.
      The recorder writes a side ONCE per day and phase (`opportunity_population_ledger`), so in
      a same-day sport a lead band holds the sides FIRST PRICED that early -- it mixes when a
      market opens with how stale the sim is. Read a band trend inside one market, not across
      markets. Multi-day sports (NFL, NCAAF, soccer) also see the same side on earlier days.
    - big misses: the largest disagreements the market won, by population key, for the
      engine's input checklist (`docs/ai_context/model_engine_standard.md`).

WHAT IT CANNOT SEE. |gap| > 15 points. `layer2_board._MODEL_EDGE_MAX_POINTS` turns the edge into
None before the recorder writes `me`, so those rows reach the grader with no sim probability and
are counted `nosim`. H3 is reported NOT COMPUTABLE here, never as a null.

REPORTING ONLY. No overlay and no consumer: nothing reads this for rank, stake or publication.
"""

from __future__ import annotations

import collections
import contextlib
import json
import math
import zlib
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from datetime import date as date_cls, datetime, timedelta, timezone
from typing import Any

import numpy as np

from syndicate.features.shared import measured_bucket_skill as mbs

VERSION = "sim_gap_ev/1"
REPORT_DIR = "reports/model_scorecard"
# Inside the EXISTING allowlist entries `reports/model_scorecard/model_scorecard_*.json|.md`, and no ISO
# date in the names, so date-scoped worker pulls skip them (the optimizer's reasoning).
STATE_PATH = f"{REPORT_DIR}/model_scorecard_simgap_state.json"
REPORT_PATH = f"{REPORT_DIR}/model_scorecard_simgap.json"
MARKDOWN_PATH = f"{REPORT_DIR}/model_scorecard_simgap.md"
SOURCE = "model_scorecard/sim_gap_ev"
PREREGISTRATION = {"lane": "sim-gap-ev-study", "commit": "ca52ea13", "registered": "2026-10-15"}

WINDOW_DAYS = 28
RETAIN_DAYS = 35
MIN_GAMES = 30            # pre-registered: a cell is read only with this many games
CELL_ROW_MIN_GAMES = 10   # market-level rows below this are left out of the report (point estimates only)
RESAMPLES = 2000
SEED = 20261015
BIG_GAP_POINTS = 10.0
BIG_CALLS_PER_GAME = 40   # single-side regrades per game for the big-miss list, largest |gap| first
BIG_KEEP_PER_GAME = 15
BIG_LIST = 40
MID_LOW, MID_HIGH = 0.4, 0.6

# |sim - fair| in points. Lower bound inclusive. 15+ is listed so its emptiness is visible, not hidden.
GAP_BANDS: tuple[tuple[float | None, float | None, str], ...] = (
    (0.0, 2.0, "gap0-2"), (2.0, 5.0, "gap2-5"), (5.0, 10.0, "gap5-10"), (10.0, 15.0, "gap10-15"),
    (15.0, None, "gap15+"),
)
NOSIM = "nosim"
SMALL_GAPS = ("gap0-2", "gap2-5")
LARGE_GAP = "gap10-15"
# EV of the recorded price against the recorded fair, in percent (gross of any exchange fee).
EV_BANDS: tuple[tuple[float | None, float | None, str], ...] = (
    (None, 0.0, "ev<0"), (0.0, 2.0, "ev0-2"), (2.0, 5.0, "ev2-5"), (5.0, 10.0, "ev5-10"), (10.0, None, "ev10+"),
)
# Minutes between first pricing and the start.
LEAD_BANDS: tuple[tuple[float | None, float | None, str], ...] = (
    (1440.0, None, "lead24h+"), (360.0, 1440.0, "lead6-24h"), (120.0, 360.0, "lead2-6h"), (0.0, 120.0, "lead<2h"),
)

# Per-game accumulator layouts.
BET_FIELDS = ("bets", "wins", "pnl", "ev")
CAL_FIELDS = ("rows", "dd", "dr")
FIT_FIELDS = ("rows", "sp", "spp", "sy", "spy", "sq", "sqq", "sqy", "mid_rows", "mid_miss")


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------


def log(message: str) -> None:
    print(f"[sim_gap_ev] {message}", flush=True)


def _shift(day: str, days: int) -> str:
    return (date_cls.fromisoformat(day) + timedelta(days=days)).isoformat()


def _seed(key: str, metric: str) -> int:
    return (SEED + zlib.crc32(f"{key}|{metric}".encode("utf-8"))) % (2**32)


def _r(value: Any, digits: int = 5) -> Any:
    if isinstance(value, (float, np.floating)):
        value = float(value)
        return round(value, digits) if math.isfinite(value) else None
    return value


def _band(value: float, bands: Sequence[tuple[float | None, float | None, str]]) -> str | None:
    for low, high, label in bands:
        if (low is None or value >= low) and (high is None or value < high):
            return label
    return None


def gap_band(edge_points: float) -> str:
    return _band(abs(float(edge_points)), GAP_BANDS) or GAP_BANDS[-1][2]


def ev_band(ev_pct: float) -> str:
    return _band(float(ev_pct), EV_BANDS) or EV_BANDS[-1][2]


def lead_band(minutes: float | None) -> str | None:
    if minutes is None or minutes < 0:
        return None
    return _band(float(minutes), LEAD_BANDS)


def direction(d: float) -> str:
    return "for" if d > 0 else "against" if d < 0 else "flat"


def cell_of(row: Mapping[str, Any]) -> str | None:
    """The scorecard's cell, `sport|market|segment|phase` -- the prefix `msc._accumulate` keys on."""
    buckets = list(row.get("buckets") or [])
    return "|".join(str(buckets[0]).split("|")[:4]) if buckets else None


def _decimal_odds(american: float) -> float:
    return 1.0 + (american / 100.0 if american > 0 else 100.0 / -american)


def minutes_before_start(record: Mapping[str, Any]) -> float | None:
    sighted, start = mbs._parse_time(record.get("t")), mbs._parse_time(record.get("ct"))  # noqa: SLF001
    if sighted is None or start is None:
        return None
    return (start - sighted).total_seconds() / 60.0


def _phase_of(record: Mapping[str, Any]) -> str:
    return mbs._phase(record.get("gs"), sighted_at=record.get("t"), commence_time=record.get("ct"))  # noqa: SLF001


def _add(target: list[float], acc: Sequence[float]) -> None:
    for index, value in enumerate(acc):
        target[index] += value


# ---------------------------------------------------------------------------
# state -- the optimizer's rules: no pooling across grader versions
# ---------------------------------------------------------------------------


def empty_state(grader_signature: str, sport_versions: Mapping[str, str] | None = None) -> dict[str, Any]:
    return {"version": VERSION, "grader_signature": grader_signature,
            "sport_versions": dict(sport_versions or {}), "games": {}, "resets": []}


def load_state(payload: Any, grader_signature: str, *, sport_versions: Mapping[str, str] | None = None,
               now: datetime | None = None) -> tuple[dict[str, Any], str | None]:
    """The saved state or a fresh one. A grader change resets everything; a settler change, its sports."""
    sport_versions = dict(sport_versions or {})
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")
    if not isinstance(payload, Mapping) or payload.get("version") != VERSION:
        return empty_state(grader_signature, sport_versions), (None if payload is None else "state_version_changed")
    resets = list(payload.get("resets") or [])[-9:]
    if payload.get("grader_signature") != grader_signature:
        state = empty_state(grader_signature, sport_versions)
        state["resets"] = resets + [{"at": stamp, "reason": "grader_signature_changed"}]
        return state, "grader_signature_changed"
    state = empty_state(grader_signature, sport_versions)
    state["games"] = dict(payload.get("games") or {})
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


def commit(state: dict[str, Any], scorecard_games: Mapping[str, Mapping[str, Any]]) -> dict[str, int]:
    """Keep the candidates whose game the scorecard committed; drop the rest (they are re-graded later)."""
    counts: collections.Counter[str] = collections.Counter()
    for gk, entry in (state.pop("candidates", None) or {}).items():
        game = scorecard_games.get(gk)
        if game is None or gk in state["games"]:
            counts["not_committed"] += 1
            continue
        state["games"][gk] = {**entry, "date": str(game.get("date"))}
        counts["committed"] += 1
    return dict(counts)


def window_games(state: Mapping[str, Any], today: str, days: int = WINDOW_DAYS) -> list[dict[str, Any]]:
    floor = _shift(today, -days)
    return [{**game, "key": key} for key, game in sorted(state["games"].items())
            if floor <= str(game.get("date") or "") < today]


# ---------------------------------------------------------------------------
# accumulation
# ---------------------------------------------------------------------------


def accumulate(graded: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, list[float]]]:
    """One game's graded rows -> the per-game sums every table is built from.

        bet[cell|gap|dir|ev] = [bets, wins, pnl, ev]       rows with a price; `nosim|none` without a sim
        cal[cell|gap]        = [rows, sum d*d, sum d*r]     d = sim - fair, r = y - fair; w = sum dr / sum dd
        fit[cell]            = FIT_FIELDS                   p = sim, q = fair, y = outcome

    Per-game SUMS, so a game bootstrap is exact and a month fits in a small state.
    """
    bet: dict[str, list[float]] = {}
    cal: dict[str, list[float]] = {}
    fit: dict[str, list[float]] = {}
    for row in graded:
        cell = cell_of(row)
        y, q = row.get("y"), row.get("p_market")
        if cell is None or y is None or q is None:
            continue
        y, q = float(y), float(q)
        p, edge = row.get("p_model"), row.get("model_edge_pct")
        has_sim = p is not None and edge is not None
        d = 0.0
        gap = NOSIM
        if has_sim:
            p = float(p)
            d = p - q
            gap = gap_band(float(edge))
            acc = cal.setdefault(f"{cell}|{gap}", [0, 0.0, 0.0])
            _add(acc, (1, d * d, d * (y - q)))
            f = fit.setdefault(cell, [0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0, 0.0])
            _add(f, (1, p, p * p, y, p * y, q, q * q, q * y, 0, 0.0))
            if MID_LOW <= p <= MID_HIGH:
                f[8] += 1
                f[9] += y - p
        price, pnl = row.get("price"), row.get("pnl")
        if price in (None, 0) or pnl is None:
            continue
        ev = q * _decimal_odds(float(price)) - 1.0
        key = f"{cell}|{gap}|{direction(d) if has_sim else 'none'}|{ev_band(100.0 * ev)}"
        acc = bet.setdefault(key, [0, 0, 0.0, 0.0])
        _add(acc, (1, 1 if y >= 1.0 else 0, float(pnl), ev))
    return {"bet": bet, "cal": cal, "fit": fit}


def lead_sums(records: Sequence[Mapping[str, Any]], chips: Any, grade: Callable[..., Any],
              side: Mapping[str, Any]) -> dict[str, list[float]]:
    """`cal`-shaped sums per `cell|lead band`, grading each band's PREGAME sightings on their own.

    The main grade keeps one (the earliest) sighting per side, so it cannot say how the sim's error
    moves with time to the start. Each band is graded alone: earliest sighting INSIDE the band.
    """
    groups: dict[str, list[Mapping[str, Any]]] = collections.defaultdict(list)
    for record in records:
        if _phase_of(record) != "pregame":
            continue
        band = lead_band(minutes_before_start(record))
        if band:
            groups[band].append(record)
    out: dict[str, list[float]] = {}
    for band, group in sorted(groups.items()):
        graded, _ = grade(group, chips, ungraded_by_sport={}, **side)
        for key, acc in accumulate(graded)["cal"].items():
            cell = key.rsplit("|", 1)[0]
            _add(out.setdefault(f"{cell}|{band}", [0, 0.0, 0.0]), acc)
    return out


def big_misses(records: Sequence[Mapping[str, Any]], chips: Any, grade: Callable[..., Any],
               side: Mapping[str, Any]) -> tuple[list[dict[str, Any]], dict[str, list[int]]]:
    """(the big disagreements the MARKET won, [graded, market_right] per cell) for one game.

    A graded row carries no population key, so each candidate side (|gap| >= BIG_GAP_POINTS, the
    earliest such sighting per key and phase) is regraded ALONE: the key is then known. Capped at
    BIG_CALLS_PER_GAME, largest |gap| first.
    """
    chosen: dict[tuple[str, str], Mapping[str, Any]] = {}
    for record in records:
        edge = record.get("me")
        if edge is None or not record.get("k"):
            continue
        try:
            if abs(float(edge)) < BIG_GAP_POINTS:
                continue
        except (TypeError, ValueError):
            continue
        key = (str(record["k"]), _phase_of(record))
        held = chosen.get(key)
        if held is None or str(record.get("t") or "") < str(held.get("t") or ""):
            chosen[key] = record
    ranked = sorted(chosen.values(), key=lambda r: -abs(float(r["me"])))[:BIG_CALLS_PER_GAME]
    misses: list[dict[str, Any]] = []
    counts: dict[str, list[int]] = {}
    for record in ranked:
        graded, _ = grade([record], chips, ungraded_by_sport={}, **side)
        row = next((g for g in graded if g.get("p_model") is not None and g.get("y") is not None), None)
        if row is None:
            continue
        cell = cell_of(row) or "unknown"
        d = float(row["p_model"]) - float(row["p_market"])
        market_right = (d > 0 and float(row["y"]) < 1.0) or (d < 0 and float(row["y"]) >= 1.0)
        tally = counts.setdefault(cell, [0, 0])
        tally[0] += 1
        tally[1] += 1 if market_right else 0
        if market_right:
            misses.append({"k": str(record["k"]), "cell": cell, "sim": _r(float(row["p_model"]), 4),
                           "fair": _r(float(row["p_market"]), 4), "gap_pts": _r(100.0 * d, 2),
                           "y": float(row["y"]), "price": row.get("price"), "t": record.get("t"),
                           "ct": record.get("ct")})
    misses.sort(key=lambda m: -abs(m["gap_pts"] or 0.0))
    return misses[:BIG_KEEP_PER_GAME], counts


@contextlib.contextmanager
def keep_counters(obj: Any, *names: str) -> Iterator[None]:
    """Restore `obj`'s Counter attributes on exit, so the extra grading leaves a settler's report as it was."""
    saved = {name: collections.Counter(getattr(obj, name)) for name in names if hasattr(obj, name)}
    try:
        yield
    finally:
        for name, value in saved.items():
            setattr(obj, name, value)


def wrap_grade(grade: Callable[..., tuple[list[dict[str, Any]], dict[str, int]]], state: dict[str, Any], *,
               game_key: Callable[[Mapping[str, Any]], str | None],
               base: Callable[..., Any] | None = None, lead: bool = True,
               quiet: Callable[[], contextlib.AbstractContextManager[Any]] | None = None) -> Callable[..., Any]:
    """`grade` with this study riding along. Returns EXACTLY what `grade` returns.

    `base` is the UNWRAPPED grader the extra calls go through. Wrap this OUTSIDE the optimizer's
    wrapper and pass the bare grader here: the optimizer's wrapper keys its candidates by game, so a
    lead-band or single-side call through it would overwrite that game's accumulation with a part.
    `quiet` wraps those extra calls (the cron passes `keep_counters(settler, ...)`): the settler counts
    every call, and the scorecard logs those counts as ITS grading.
    """
    candidates = state.setdefault("candidates", {})
    regrade = base or grade

    def graded_with_study(records: Sequence[Mapping[str, Any]], chips: Any, **kwargs: Any) -> Any:
        graded, ungraded = grade(records, chips, **kwargs)
        try:
            gk = next((key for key in (game_key(r) for r in records) if key), None)
            if gk is not None:
                side = {k: v for k, v in kwargs.items() if k != "ungraded_by_sport"}
                entry: dict[str, Any] = {"sport": gk.split("|", 1)[0], **accumulate(graded)}
                with (quiet() if quiet is not None else contextlib.nullcontext()):
                    if lead:
                        entry["lead"] = lead_sums(records, chips, regrade, side)
                    entry["big"], entry["bigc"] = big_misses(records, chips, regrade, side)
                candidates[gk] = entry
        except Exception as exc:  # the study must never break the scorecard
            log(f"ACCUMULATE_FAILED {type(exc).__name__}: {exc}")
        return graded, ungraded

    return graded_with_study


# ---------------------------------------------------------------------------
# statistics -- game bootstrap over per-game sums
# ---------------------------------------------------------------------------


Entries = list[tuple[str, str, list[float]]]


def _collect(games: Sequence[Mapping[str, Any]], field: str,
             keys_for: Callable[[str], Sequence[str]]) -> dict[str, Entries]:
    """key -> [(date, game, summed acc)], one entry per game, in a canonical order."""
    per: dict[str, dict[str, list[float]]] = collections.defaultdict(dict)
    dates: dict[str, str] = {}
    for game in games:
        gk = str(game["key"])
        dates[gk] = str(game.get("date"))
        for raw, acc in (game.get(field) or {}).items():
            if not acc or not acc[0]:
                continue
            for key in keys_for(raw):
                held = per[key].get(gk)
                if held is None:
                    per[key][gk] = [float(v) for v in acc]
                else:
                    _add(held, acc)
    return {key: sorted(((dates[gk], gk, acc) for gk, acc in by_game.items()), key=lambda e: (e[0], e[1]))
            for key, by_game in per.items()}


def _matrix(entries: Entries) -> np.ndarray:
    return np.array([acc for _, _, acc in entries], dtype=float)


def _weights(n: int, *, seed: int, resamples: int) -> np.ndarray:
    """(resamples, n) game counts drawn with replacement."""
    rng = np.random.default_rng(seed)
    return rng.multinomial(n, np.full(n, 1.0 / n), size=resamples)


def _ci(values: np.ndarray) -> list[float] | None:
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return None
    lo, hi = np.quantile(finite, [0.025, 0.975])
    return [_r(lo), _r(hi)]


def _ratio(sums: np.ndarray, num: int, den: int) -> np.ndarray:
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(sums[..., den] > 0, sums[..., num] / sums[..., den], np.nan)


def _slope(sums: np.ndarray, sx: int, sxx: int, sy: int, sxy: int) -> np.ndarray:
    n = sums[..., 0]
    with np.errstate(divide="ignore", invalid="ignore"):
        var = sums[..., sxx] - sums[..., sx] ** 2 / n
        cov = sums[..., sxy] - sums[..., sx] * sums[..., sy] / n
        return np.where(var > 1e-12, cov / var, np.nan)


def _excludes_zero(ci: list[float] | None) -> bool:
    return bool(ci is not None and ci[0] is not None and ci[1] is not None and (ci[0] > 0 or ci[1] < 0))


def _paired(a: Entries, b: Entries, width: int) -> tuple[np.ndarray, np.ndarray, int]:
    """Two keys' per-game sums over the UNION of their games (zeros where a game lacks one)."""
    games = sorted({(d, g) for d, g, _ in a} | {(d, g) for d, g, _ in b})
    index = {key: i for i, key in enumerate(games)}
    ma, mb = np.zeros((len(games), width)), np.zeros((len(games), width))
    for d, g, acc in a:
        ma[index[(d, g)]] = acc
    for d, g, acc in b:
        mb[index[(d, g)]] = acc
    return ma, mb, len(games)


# ---------------------------------------------------------------------------
# (A) betting
# ---------------------------------------------------------------------------


def _bet_row(key: str, entries: Entries, *, resamples: int) -> dict[str, Any]:
    m = _matrix(entries)
    total = m.sum(axis=0)
    bets = int(total[0])
    row: dict[str, Any] = {
        "key": key, "games": len(entries), "dates": len({d for d, _, _ in entries}), "bets": bets,
        "hit_rate": _r(total[1] / bets) if bets else None,
        "roi": _r(total[2] / bets) if bets else None,
        "mean_ev": _r(total[3] / bets) if bets else None,
        "ci95": None, "tested": False, "signal": False,
    }
    if len(entries) >= MIN_GAMES and bets:
        sums = _weights(len(entries), seed=_seed(key, "roi"), resamples=resamples) @ m
        row["ci95"] = _ci(_ratio(sums, 2, 0))
        row["tested"] = True
        row["signal"] = _excludes_zero(row["ci95"])
    return row


def betting(games: Sequence[Mapping[str, Any]], *, resamples: int = RESAMPLES) -> dict[str, Any]:
    """Sport x phase tables (cross, by gap, by EV, by sim view within EV) plus market-level cross rows."""

    def keys_for(raw: str) -> list[str]:
        sport, market, segment, phase, gap, view, ev = raw.split("|")
        base = f"{sport}|{phase}"
        return [f"cross|{base}|{gap}|{view}|{ev}", f"gap|{base}|{gap}|{view}", f"ev|{base}|{ev}",
                f"view|{base}|{view}|{ev}", f"cell|{raw}"]

    collected = _collect(games, "bet", keys_for)
    tables: dict[str, list[dict[str, Any]]] = {"cross": [], "gap": [], "ev": [], "view": [], "cell": []}
    for key in sorted(collected):
        kind, rest = key.split("|", 1)
        entries = collected[key]
        if kind == "cell" and len(entries) < CELL_ROW_MIN_GAMES:
            continue
        row = _bet_row(rest, entries, resamples=resamples)
        parts = rest.split("|")
        if kind == "cell":
            row.update(zip(("sport", "market", "segment", "phase", "gap", "view", "ev"), parts))
        else:
            row.update(zip(("sport", "phase"), parts[:2]))
            row.update(zip({"cross": ("gap", "view", "ev"), "gap": ("gap", "view"), "ev": ("ev",),
                            "view": ("view", "ev")}[kind], parts[2:]))
        tables[kind].append(row)
    tested = sum(1 for t in ("cross", "cell") for r in tables[t] if r["tested"])
    signals = [r for t in ("cross", "cell") for r in tables[t] if r["signal"]]
    h1 = _h1(collected, resamples=resamples)
    return {**tables, "tested": tested, "signals": [r["key"] for r in signals],
            "expected_false_signals": _r(0.05 * tested, 1), "h1": h1}


def _h1(collected: Mapping[str, Entries], *, resamples: int) -> list[dict[str, Any]]:
    """Inside one sport x phase x EV band: ROI(sim FOR) - ROI(sim AGAINST), game-paired bootstrap."""
    out: list[dict[str, Any]] = []
    for key in sorted(k for k in collected if k.startswith("view|") and k.split("|")[3] == "for"):
        _, sport, phase, _, ev = key.split("|")
        other = f"view|{sport}|{phase}|against|{ev}"
        a, b = collected[key], collected.get(other, [])
        row: dict[str, Any] = {"sport": sport, "phase": phase, "ev": ev, "for_games": len(a), "against_games": len(b)}
        ta, tb = _matrix(a).sum(axis=0), (_matrix(b).sum(axis=0) if b else np.zeros(4))
        row["for_bets"], row["against_bets"] = int(ta[0]), int(tb[0])
        row["for_roi"] = _r(ta[2] / ta[0]) if ta[0] else None
        row["against_roi"] = _r(tb[2] / tb[0]) if tb[0] else None
        row["diff"] = _r(row["for_roi"] - row["against_roi"]) if None not in (row["for_roi"], row["against_roi"]) else None
        row["ci95"] = None
        if len(a) < MIN_GAMES or len(b) < MIN_GAMES:
            row["verdict"] = "insufficient"
        else:
            ma, mb, n = _paired(a, b, 4)
            w = _weights(n, seed=_seed(key, "h1"), resamples=resamples)
            row["ci95"] = _ci(_ratio(w @ ma, 2, 0) - _ratio(w @ mb, 2, 0))
            ci = row["ci95"]
            row["verdict"] = ("for_beats_against" if ci and ci[0] > 0 else
                              "against_beats_for" if ci and ci[1] < 0 else "no_difference")
        out.append(row)
    return out


# ---------------------------------------------------------------------------
# (B) engine
# ---------------------------------------------------------------------------


def _cal_row(key: str, entries: Entries, *, resamples: int) -> dict[str, Any]:
    m = _matrix(entries)
    total = m.sum(axis=0)
    rows = int(total[0])
    row: dict[str, Any] = {
        "key": key, "games": len(entries), "rows": rows,
        "w": _r(total[2] / total[1]) if total[1] > 0 else None,
        # Brier(sim) - Brier(market) per row: (sum dd - 2 sum dr) / n. Positive = the sim is worse.
        "brier_sim_minus_market": _r((total[1] - 2.0 * total[2]) / rows) if rows else None,
        "w_ci95": None, "brier_ci95": None,
    }
    if len(entries) >= MIN_GAMES and rows:
        sums = _weights(len(entries), seed=_seed(key, "w"), resamples=resamples) @ m
        row["w_ci95"] = _ci(_ratio(sums, 2, 1))
        with np.errstate(divide="ignore", invalid="ignore"):
            row["brier_ci95"] = _ci((sums[:, 1] - 2.0 * sums[:, 2]) / sums[:, 0])
    return row


def trust(games: Sequence[Mapping[str, Any]], *, resamples: int = RESAMPLES) -> dict[str, Any]:
    def keys_for(raw: str) -> list[str]:
        sport, market, segment, phase, gap = raw.split("|")
        keys = [f"sport|{sport}|{phase}|{gap}", f"cell|{raw}"]
        if gap in SMALL_GAPS:
            keys.append(f"small|{sport}|{phase}")
        elif gap == LARGE_GAP:
            keys.append(f"large|{sport}|{phase}")
        return keys

    collected = _collect(games, "cal", keys_for)
    sport_rows, cell_rows = [], []
    for key in sorted(collected):
        kind, rest = key.split("|", 1)
        if kind in ("small", "large"):
            continue
        if kind == "cell" and len(collected[key]) < CELL_ROW_MIN_GAMES:
            continue
        row = _cal_row(rest, collected[key], resamples=resamples)
        parts = rest.split("|")
        if kind == "cell":
            row.update(zip(("sport", "market", "segment", "phase", "gap"), parts))
            cell_rows.append(row)
        else:
            row.update(zip(("sport", "phase", "gap"), parts))
            sport_rows.append(row)
    h2 = []
    for key in sorted(k for k in collected if k.startswith("small|")):
        _, sport, phase = key.split("|")
        small, large = collected[key], collected.get(f"large|{sport}|{phase}", [])
        ts, tl = _matrix(small).sum(axis=0), (_matrix(large).sum(axis=0) if large else np.zeros(3))
        row = {"sport": sport, "phase": phase, "small_games": len(small), "large_games": len(large),
               "w_small": _r(ts[2] / ts[1]) if ts[1] > 0 else None,
               "w_large": _r(tl[2] / tl[1]) if tl[1] > 0 else None, "ci95": None}
        row["diff"] = _r(row["w_large"] - row["w_small"]) if None not in (row["w_small"], row["w_large"]) else None
        if len(small) < MIN_GAMES or len(large) < MIN_GAMES:
            row["verdict"] = "insufficient"
        else:
            ms, ml, n = _paired(small, large, 3)
            w = _weights(n, seed=_seed(key, "h2"), resamples=resamples)
            row["ci95"] = _ci(_ratio(w @ ml, 2, 1) - _ratio(w @ ms, 2, 1))
            ci = row["ci95"]
            row["verdict"] = ("w_falls" if ci and ci[1] < 0 else "w_rises" if ci and ci[0] > 0 else "no_difference")
        h2.append(row)
    return {"by_sport": sport_rows, "cells": cell_rows, "h2": h2}


def _fit_row(key: str, entries: Entries, *, resamples: int) -> dict[str, Any]:
    m = _matrix(entries)
    total = m.sum(axis=0)
    rows = int(total[0])
    slope_sim = _slope(total[None, :], 1, 2, 3, 4)[0]
    slope_market = _slope(total[None, :], 5, 6, 3, 7)[0]
    row: dict[str, Any] = {
        "key": key, "games": len(entries), "rows": rows,
        "mean_outcome": _r(total[3] / rows) if rows else None,
        "mean_sim": _r(total[1] / rows) if rows else None,
        "mean_market": _r(total[5] / rows) if rows else None,
        "slope_sim": _r(slope_sim), "slope_market": _r(slope_market), "slope_sim_ci95": None,
        "mid_rows": int(total[8]),
        "mid_bias": _r(total[9] / total[8]) if total[8] else None, "mid_bias_ci95": None,
        "verdict": "insufficient",
    }
    if len(entries) >= MIN_GAMES and rows:
        sums = _weights(len(entries), seed=_seed(key, "fit"), resamples=resamples) @ m
        row["slope_sim_ci95"] = _ci(_slope(sums, 1, 2, 3, 4))
        row["mid_bias_ci95"] = _ci(_ratio(sums, 9, 8))
        ci = row["slope_sim_ci95"]
        row["verdict"] = ("overconfident" if ci and ci[1] < 1.0 else
                          "underconfident" if ci and ci[0] > 1.0 else "not_proven")
    return row


def calibration(games: Sequence[Mapping[str, Any]], *, resamples: int = RESAMPLES) -> dict[str, Any]:
    def keys_for(cell: str) -> list[str]:
        sport, market, segment, phase = cell.split("|")
        return [f"sport|{sport}|{phase}", f"cell|{cell}"]

    collected = _collect(games, "fit", keys_for)
    sport_rows, cell_rows = [], []
    for key in sorted(collected):
        kind, rest = key.split("|", 1)
        if kind == "cell" and len(collected[key]) < CELL_ROW_MIN_GAMES:
            continue
        row = _fit_row(rest, collected[key], resamples=resamples)
        parts = rest.split("|")
        if kind == "cell":
            row.update(zip(("sport", "market", "segment", "phase"), parts))
            cell_rows.append(row)
        else:
            row.update(zip(("sport", "phase"), parts))
            sport_rows.append(row)
    return {"by_sport": sport_rows, "cells": cell_rows}


def lead_time(games: Sequence[Mapping[str, Any]], *, resamples: int = RESAMPLES) -> dict[str, Any]:
    def keys_for(raw: str) -> list[str]:
        sport, market, segment, phase, band = raw.split("|")
        return [f"sport|{sport}|{band}", f"cell|{raw}"]

    collected = _collect(games, "lead", keys_for)
    sport_rows, cell_rows = [], []
    for key in sorted(collected):
        kind, rest = key.split("|", 1)
        if kind == "cell" and len(collected[key]) < CELL_ROW_MIN_GAMES:
            continue
        row = _cal_row(rest, collected[key], resamples=resamples)
        parts = rest.split("|")
        if kind == "cell":
            row.update(zip(("sport", "market", "segment", "phase", "lead"), parts))
            cell_rows.append(row)
        else:
            row.update(zip(("sport", "lead"), parts))
            sport_rows.append(row)
    return {"by_sport": sport_rows, "cells": cell_rows}


def big_miss_report(games: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    tally: dict[str, list[int]] = collections.defaultdict(lambda: [0, 0])
    rows: list[dict[str, Any]] = []
    for game in games:
        for cell, (graded, right) in (game.get("bigc") or {}).items():
            sport, market = (cell.split("|") + ["", ""])[:2]
            _add(tally[f"{sport}|{market}"], (graded, right))
        for miss in game.get("big") or []:
            rows.append({**miss, "game": game["key"], "date": game.get("date")})
    rows.sort(key=lambda m: (-abs(m.get("gap_pts") or 0.0), str(m.get("k"))))
    by_market = [{"sport": key.split("|")[0], "market": key.split("|")[1], "graded": n, "market_right": right,
                  "market_right_rate": _r(right / n) if n else None}
                 for key, (n, right) in sorted(tally.items())]
    return {"threshold_pts": BIG_GAP_POINTS, "by_market": by_market, "top": rows[:BIG_LIST]}


# ---------------------------------------------------------------------------
# report
# ---------------------------------------------------------------------------


def coverage(games: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for game in games:
        sport = str(game.get("sport"))
        entry = out.setdefault(sport, {"games": 0, "dates": set(), "bets": 0, "sim_rows": 0})
        entry["games"] += 1
        entry["dates"].add(str(game.get("date")))
        entry["bets"] += int(sum(acc[0] for acc in (game.get("bet") or {}).values()))
        entry["sim_rows"] += int(sum(acc[0] for acc in (game.get("fit") or {}).values()))
    return {sport: {**v, "dates": len(v["dates"])} for sport, v in sorted(out.items())}


def build_report(state: Mapping[str, Any], *, today: str, now: datetime, run: Mapping[str, Any] | None = None,
                 resamples: int = RESAMPLES) -> dict[str, Any]:
    games = window_games(state, today)
    dates = sorted({str(g.get("date")) for g in games})
    return {
        "version": VERSION,
        "source": SOURCE,
        "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "today": today,
        "window": {"days": WINDOW_DAYS, "from": dates[0] if dates else None, "to": dates[-1] if dates else None,
                   "games": len(games), "dates": len(dates)},
        "preregistration": {**PREREGISTRATION, "min_games": MIN_GAMES, "resamples": resamples, "seed": SEED},
        "definitions": {
            "gap": "sim probability minus the de-vigged fair, in points, on the side's own probability",
            "ev": "fair x decimal(recorded price) - 1, GROSS of any exchange fee",
            "w": "Brier-optimal weight in fair + w * (sim - fair)",
            "slope_sim": "least-squares slope of outcome on the sim's probability; < 1 = overconfident",
            "mid_bias": "mean(outcome - sim) on rows the sim put at 0.40-0.60",
            "lead": "minutes between a side's FIRST pricing that day and the start (pregame only)",
        },
        "coverage": coverage(games),
        "betting": betting(games, resamples=resamples),
        "engine": {
            "trust": trust(games, resamples=resamples),
            "calibration": calibration(games, resamples=resamples),
            "lead_time": lead_time(games, resamples=resamples),
            "big_misses": big_miss_report(games),
        },
        "h3": {"computable": False,
               "reason": "|gap| > 15 points never reaches the grader: layer2_board._MODEL_EDGE_MAX_POINTS sets "
                         "the edge to None before the recorder writes `me`, so those rows grade as `nosim`."},
        "run": dict(run or {}),
    }


def _pct(value: Any, digits: int = 1) -> str:
    return "-" if value is None else f"{100.0 * value:+.{digits}f}%"


def _num(value: Any, digits: int = 3) -> str:
    return "-" if value is None else f"{value:.{digits}f}"


def _range(ci: Any, fmt: Callable[[Any], str]) -> str:
    return "" if not ci else f" [{fmt(ci[0])}, {fmt(ci[1])}]"


def markdown(report: Mapping[str, Any]) -> str:
    window = report["window"]
    bet = report["betting"]
    eng = report["engine"]
    lines = [
        f"# Sim gap x EV -- {report['today']}",
        "",
        f"Window {window['from']}..{window['to']}: {window['games']} games over {window['dates']} dates. "
        f"Pre-registered (lane `{PREREGISTRATION['lane']}`, {PREREGISTRATION['commit']}): a cell counts only with "
        f">= {MIN_GAMES} games and a 95% game-bootstrap CI excluding 0. EV is gross of exchange fees.",
        "",
        "## Coverage",
        "",
        "| sport | games | dates | bets | sim rows |",
        "|---|---|---|---|---|",
    ]
    for sport, c in report["coverage"].items():
        lines.append(f"| {sport} | {c['games']} | {c['dates']} | {c['bets']} | {c['sim_rows']} |")
    lines += ["", "## (A) Betting", "",
              f"Cells tested: {bet['tested']}. Signals: {len(bet['signals'])} "
              f"(about {bet['expected_false_signals']} expected by chance at 5%).", ""]
    for key in bet["signals"][:20]:
        lines.append(f"- signal: `{key}`")
    lines += ["", "### H1 -- sim FOR vs AGAINST inside one EV band", "",
              "| sport | phase | EV | FOR roi (bets) | AGAINST roi (bets) | diff [CI] | verdict |",
              "|---|---|---|---|---|---|---|"]
    for r in bet["h1"]:
        lines.append(f"| {r['sport']} | {r['phase']} | {r['ev']} | {_pct(r['for_roi'])} ({r['for_bets']}) | "
                     f"{_pct(r['against_roi'])} ({r['against_bets']}) | {_pct(r['diff'])}{_range(r['ci95'], _pct)} | "
                     f"{r['verdict']} |")
    lines += ["", "### By sim view, all EV bands", "", "| sport | phase | gap | view | games | bets | ROI [CI] |",
              "|---|---|---|---|---|---|---|"]
    for r in bet["gap"]:
        lines.append(f"| {r['sport']} | {r['phase']} | {r['gap']} | {r['view']} | {r['games']} | {r['bets']} | "
                     f"{_pct(r['roi'])}{_range(r['ci95'], _pct)} |")
    lines += ["", "## (B) Engine", "", "### Trust in the sim by gap size (w: 1 = trust, 0 = noise, < 0 = wrong way)", "",
              "| sport | phase | gap | games | rows | w [CI] | Brier sim-market per row |",
              "|---|---|---|---|---|---|---|"]
    for r in eng["trust"]["by_sport"]:
        lines.append(f"| {r['sport']} | {r['phase']} | {r['gap']} | {r['games']} | {r['rows']} | "
                     f"{_num(r['w'], 2)}{_range(r['w_ci95'], lambda v: _num(v, 2))} | {_num(r['brier_sim_minus_market'], 4)} |")
    lines += ["", "### H2 -- does w fall as the gap grows?", "", "| sport | phase | w 0-5 | w 10-15 | diff [CI] | verdict |",
              "|---|---|---|---|---|---|"]
    for r in eng["trust"]["h2"]:
        lines.append(f"| {r['sport']} | {r['phase']} | {_num(r['w_small'], 2)} | {_num(r['w_large'], 2)} | "
                     f"{_num(r['diff'], 2)}{_range(r['ci95'], lambda v: _num(v, 2))} | {r['verdict']} |")
    lines += ["", "### Mean vs spread", "",
              "| sport | phase | rows | slope sim [CI] | slope market | mid-line bias [CI] | verdict |",
              "|---|---|---|---|---|---|---|"]
    for r in eng["calibration"]["by_sport"]:
        lines.append(f"| {r['sport']} | {r['phase']} | {r['rows']} | "
                     f"{_num(r['slope_sim'], 2)}{_range(r['slope_sim_ci95'], lambda v: _num(v, 2))} | "
                     f"{_num(r['slope_market'], 2)} | {_pct(r['mid_bias'])}{_range(r['mid_bias_ci95'], _pct)} "
                     f"({r['mid_rows']}) | {r['verdict']} |")
    lines += ["", "### Lead time (pregame; a band = sides FIRST priced that long before the start)", "",
              "| sport | lead | games | rows | w | Brier sim-market per row [CI] |", "|---|---|---|---|---|---|"]
    for r in eng["lead_time"]["by_sport"]:
        lines.append(f"| {r['sport']} | {r['lead']} | {r['games']} | {r['rows']} | {_num(r['w'], 2)} | "
                     f"{_num(r['brier_sim_minus_market'], 4)}{_range(r['brier_ci95'], lambda v: _num(v, 4))} |")
    big = eng["big_misses"]
    lines += ["", f"### Big disagreements (>= {big['threshold_pts']:.0f} points): how often the market was right", "",
              "| sport | market | graded | market right |", "|---|---|---|---|"]
    for r in big["by_market"]:
        lines.append(f"| {r['sport']} | {r['market']} | {r['graded']} | {r['market_right']} "
                     f"({_pct(r['market_right_rate'], 0)}) |")
    lines += ["", "Largest misses (engine input-checklist candidates):", ""]
    for m in big["top"][:15]:
        lines.append(f"- {m.get('date')} `{m['k']}` sim {_num(m['sim'], 3)} vs fair {_num(m['fair'], 3)} "
                     f"({m['gap_pts']:+.1f} pts), outcome {int(m['y'])}")
    lines += ["", "## Not computable", "", f"- H3 (|gap| > 15): {report['h3']['reason']}", ""]
    return "\n".join(lines)


def dumps(payload: Any) -> str:
    return json.dumps(payload, indent=1, sort_keys=True, default=str)
