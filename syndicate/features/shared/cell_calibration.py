"""ONE per-cell calibrated model probability, used everywhere a model probability is shown or used (todo #847).

Lane `cell-calibration-847` (2026-11-18), from the product optimization program's P1 / theme T2
(`.syndicate/findings_2026-11-18_product_optimization_program.md` §3.2). The pre-registration this module
implements is `.syndicate/findings_2026-11-18_cell_calibration.md` §1, committed before any k was fitted.

THE FINDING. The model's probability is over-confident everywhere it is measured: Games Rail flags hit 9.1 pp
below the model's own probability [-12.7, -5.3] (1,120 flags / 177 games / 3 dates), and the daily optimizer has
61 of 63 validated cells with w* below 1. The over-confidence differs by cell -- NCAAB totals near 0, NBA
spreads ~0.4, cheat-sheet NBA props UNDER-confident -- so there is never one global k.

THE TRANSFORM, per line:

    logit p' = logit fair + k_cell * (logit p_model - logit fair)

k = 1 is the line as served today; k -> 0 is the fair. `fair` is the line's own de-vigged fair for its side.

THE CELL is the daily optimizer's `sport|market|segment|phase` (`optimizer_overlay.cell_of_row`, the same
function rank and stake already key on), so a board row, the scorecard's grading and this table agree on it.

WHERE k COMES FROM (`fit_table`, run daily by the model-scorecard cron beside the optimizer):
  1. Per cell, w*, its game-bootstrap CI and the optimizer's verdict -- `daily_optimizer.fit_calibration` itself,
     over the optimizer's 28-day window of per-game sums, after the fit floors below.
  2. Partial pooling per sport x market: a normal-normal posterior between the cell's own w* and its group's
     data-weighted w*, between-cell variance by DerSimonian-Laird, plus the group mean's own variance (Morris).
  3. Served k = clip(posterior mean + 1.96 * posterior sd, K_FLOOR, 1.0) -- the CI UPPER, the optimizer's own
     "smallest shrink the evidence supports" -- on a cell whose OWN verdict is `overconfident`. Every other cell
     is absent from the table (k = 1).

  The w* fit is linear in probability (p_market + w * d) while the served transform is logit; they agree to
  first order for the gaps the board carries, and the logit form keeps p' inside (0, 1).

RAILS. k is never above 1 (no amplification: an under-confident cell needs its own test) and never below
K_FLOOR > 0 (no cell is zeroed: every line keeps part of its own disagreement, so no rule built on k can withhold
a whole cell -- the 2026-10-05 PRIME DIRECTIVE). The table expires TTL_HOURS after the cron wrote it, so a dead
cron degrades to the raw model, never to a frozen table.

FIT FLOORS (dates a cell's fit may not read):
  - nba: before 2026-11-19 (I-25: duplicated history inflated Elo in every NBA row before 11-18 3:02 PM CST).
  - ncaab / wncaab totals*: before 2026-11-17 (#816 calibrates those rows upstream since 11-17 00:04Z, so their k
    is a RESIDUAL on #816's number and is fitted on that number only).

FOUR USES, each behind its own switch (absent = off; on / 1 / true / yes enables). Each consumer asks
`stamp(row, p_model, fair, use=...)` or `rank_stake_factor(cell)` and gets nothing when its switch is off, so an
off build is bit-identical to today's:
  - USE_RAIL        SYNDICATE_CELL_CALIBRATION_RAIL         the Games Rail's >= 3 pp MODEL != LINE test (display)
  - USE_DISPLAY     SYNDICATE_CELL_CALIBRATION_DISPLAY      the board's shown model probability / model EV (display)
  - USE_RANK_STAKE  SYNDICATE_CELL_CALIBRATION_RANK_STAKE   rank + stake below the optimizer's 0.5 floor (BETTING)
  - USE_LIVE_PROB   SYNDICATE_CELL_CALIBRATION_LIVE_PROB    the shared live probability (BETTING)

WEB-SAFE: applying k is two logits and a sigmoid; the table is one small JSON read, cached CHECK_INTERVAL_SECONDS.
Pure Python, never raises on the read path.
"""

from __future__ import annotations

import json
import math
import os
import threading
import time
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

TABLE_PATH = "reports/model_scorecard/model_cell_calibration.json"
SOURCE = "model_scorecard/cell_calibration"
VERSION = "cell_calibration/1"
K_FLOOR = 0.10
K_CEILING = 1.0
Z95 = 1.96
TTL_HOURS = 72
MAX_ENTRIES = 400
CHECK_INTERVAL_SECONDS = 600.0
_EPS = 1e-6

USE_RAIL = "rail"
USE_DISPLAY = "display"
USE_RANK_STAKE = "rank_stake"
USE_LIVE_PROB = "live_prob"
SWITCHES = {
    USE_RAIL: "SYNDICATE_CELL_CALIBRATION_RAIL",
    USE_DISPLAY: "SYNDICATE_CELL_CALIBRATION_DISPLAY",
    USE_RANK_STAKE: "SYNDICATE_CELL_CALIBRATION_RANK_STAKE",
    USE_LIVE_PROB: "SYNDICATE_CELL_CALIBRATION_LIVE_PROB",
}
_ON_VALUES = frozenset({"on", "1", "true", "yes"})

#: sport -> first game date a cell of that sport may be fitted on.
SPORT_FIT_FLOORS = {"nba": "2026-11-19"}
#: (sports, market prefix) -> first game date; #816's college totals.
MARKET_FIT_FLOORS = ((("ncaab", "wncaab"), "totals", "2026-11-17"),)


# ---------------------------------------------------------------------------
# the transform
# ---------------------------------------------------------------------------


def _logit(p: float) -> float:
    p = min(1.0 - _EPS, max(_EPS, float(p)))
    return math.log(p / (1.0 - p))


def _sigmoid(z: float) -> float:
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    e = math.exp(z)
    return e / (1.0 + e)


def _num(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def calibrate(p_model: Any, fair: Any, k: Any) -> float | None:
    """`sigmoid(logit fair + k (logit p_model - logit fair))`, or None when any input is unusable."""
    p, f, kk = _num(p_model), _num(fair), _num(k)
    if p is None or f is None or kk is None or not (0.0 < p < 1.0) or not (0.0 < f < 1.0):
        return None
    lf = _logit(f)
    return _sigmoid(lf + kk * (_logit(p) - lf))


# ---------------------------------------------------------------------------
# switches and the table
# ---------------------------------------------------------------------------


def enabled(use: str, env: Mapping[str, str] | None = None) -> bool:
    name = SWITCHES.get(use)
    if name is None:
        return False
    return str((env if env is not None else os.environ).get(name) or "").strip().lower() in _ON_VALUES


_LOCK = threading.Lock()
_STATE: dict[str, Any] = {"checked_at": None, "table": None, "sd": {}, "meta": {"reason": "not_checked"},
                         "logged": None}


def _table_file() -> Path | None:
    try:
        from syndicate.features.shared.refresh_state_store import data_root

        return Path(data_root()) / TABLE_PATH
    except Exception:
        return None


def validate_table(payload: Any, *, now: datetime | None = None) -> tuple[dict[str, float] | None, str]:
    """Consumer-side re-check of every rail: ({cell: k}, "ok") or (None, why). One bad entry rejects the file."""
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
    cells = payload.get("cells")
    if not isinstance(cells, Mapping) or len(cells) > MAX_ENTRIES:
        return None, "malformed_cells"
    from syndicate.features.shared import daily_optimizer as opt

    table: dict[str, float] = {}
    for cell, entry in cells.items():
        if str(cell).count("|") != 3 or not isinstance(entry, Mapping):
            return None, "malformed_cell"
        k = entry.get("k")
        if isinstance(k, bool) or not isinstance(k, (int, float)) or not K_FLOOR <= float(k) <= K_CEILING:
            return None, "k_out_of_rails"
        if int(entry.get("games") or 0) < opt.MIN_GAMES or int(entry.get("dates") or 0) < opt.MIN_DATES:
            return None, "below_sample_floor"
        table[str(cell)] = float(k)
    return table, "ok"


def _log(meta: Mapping[str, Any]) -> None:
    signature = (meta.get("reason"), meta.get("cells"), meta.get("generated_at"))
    if _STATE["logged"] == signature:
        return
    _STATE["logged"] = signature
    print("[cell_calibration] reason=%s cells=%s generated_at=%s expires_at=%s"
          % (meta.get("reason"), meta.get("cells"), meta.get("generated_at"), meta.get("expires_at")), flush=True)


def active_table(*, now: datetime | None = None, path: Path | None = None) -> dict[str, float] | None:
    """The validated {cell: k}, or None (absent, expired, invalid). Cached CHECK_INTERVAL_SECONDS."""
    clock = time.monotonic()
    with _LOCK:
        checked = _STATE["checked_at"]
        if checked is not None and clock - float(checked) < CHECK_INTERVAL_SECONDS and path is None and now is None:
            return _STATE["table"]
        _STATE["checked_at"] = clock
        target = path or _table_file()
        table, meta, sd = None, {"reason": "table_absent"}, {}
        try:
            if target is not None and target.is_file():
                payload = json.loads(target.read_text(encoding="utf-8"))
                table, reason = validate_table(payload, now=now)
                meta = {"reason": reason, "generated_at": payload.get("generated_at"),
                        "expires_at": payload.get("expires_at"), "cells": len(table or {})}
                for cell in table or {}:
                    value = _num((payload["cells"][cell] or {}).get("post_sd"))
                    sd[cell] = value if value is not None and value >= 0.0 else 0.0
        except Exception as exc:
            table, meta, sd = None, {"reason": f"error:{type(exc).__name__}"}, {}
        _STATE["table"], _STATE["meta"], _STATE["sd"] = table, meta, sd
        _log(meta)
        return table


def status() -> dict[str, Any]:
    return dict(_STATE["meta"])


def reset_cache() -> None:
    """Tests only."""
    _STATE.update({"checked_at": None, "table": None, "sd": {}, "meta": {"reason": "not_checked"}, "logged": None})


def cell_of_row(row: Mapping[str, Any], *, now: Any = None) -> str:
    from syndicate.features.shared.optimizer_overlay import cell_of_row as _cell

    return _cell(row, now=now)


def k_for_cell(cell: str | None, *, table: Mapping[str, float] | None = None) -> float | None:
    """The served k for a cell, or None when the cell is not served (the line stays raw)."""
    if not cell:
        return None
    table = table if table is not None else active_table()
    if not table:
        return None
    k = table.get(cell)
    return float(k) if k is not None else None


def stamp(row: Mapping[str, Any], p_model: Any, fair: Any, *, use: str, now: Any = None,
          table: Mapping[str, float] | None = None, cell: str | None = None) -> dict[str, Any] | None:
    """{"p": p', "k": k, "cell": cell, "p_raw": p_model} when `use` is switched on and the row's cell is served.

    None otherwise -- switch off, no table, unserved cell, or an unusable probability -- and a consumer that gets
    None serves exactly what it served before. Never raises.
    """
    try:
        if not enabled(use):
            return None
        cell = cell or cell_of_row(row, now=now)
        k = k_for_cell(cell, table=table)
        if k is None:
            return None
        p = calibrate(p_model, fair, k)
        if p is None:
            return None
        return {"p": round(p, 6), "k": round(k, 4), "cell": cell, "p_raw": round(float(p_model), 6)}
    except Exception:
        return None


def _row_fair(row: Mapping[str, Any], quote: Mapping[str, Any] | None = None) -> float | None:
    """This row's own de-vigged fair for its side: the quote's `fair_probability`, else `fair_consensus_prob`
    (the same pair, in the same order, the rail's `liveRowGap` reads)."""
    quote = quote if isinstance(quote, Mapping) else (row.get("quote") if isinstance(row.get("quote"), Mapping) else {})
    fair = _num(quote.get("fair_probability"))
    return fair if fair is not None else _num(quote.get("fair_consensus_prob"))


#: The key (d)'s live-join wiring sets on a row's projection when it calibrated the live probability itself, so
#: (a) never calibrates the same number twice, and the optimizer's calibration shrink is not applied on top of it
#: (`live_prob_stamp_of`, read by `optimizer_overlay.factor_for_row`).
LIVE_PROB_MARKER = "live_cell_calibration"


def live_prob_stamp_of(row: Any) -> Mapping[str, Any] | None:
    """(d)'s stamp on this row's projection -- the cell and k that moved its live probability -- or None.

    None on every row while the LIVE_PROB switch is off: the join sets the marker only when (d) served p'
    (`live_gameline_join._apply_verdict`). A stamp counts only with a numeric k in the table's rails, so a malformed
    one cannot switch the optimizer's shrink off. Never raises.
    """
    try:
        projection = row.get("projection") if isinstance(row, Mapping) else None
        found = projection.get(LIVE_PROB_MARKER) if isinstance(projection, Mapping) else None
        if not isinstance(found, Mapping):
            return None
        k = found.get("k")
        # A real number only, as `validate_table` requires of the k it serves (the join writes `round(k, 4)`).
        if isinstance(k, bool) or not isinstance(k, (int, float)):
            return None
        return found if K_FLOOR <= float(k) <= K_CEILING else None
    except Exception:
        return None


def rail_columns(row: Mapping[str, Any], live_prob: Any) -> dict[str, Any]:
    """(a) The fields the Games Rail's flag test reads, or {} (switch off, unserved cell, no fair, or the live
    probability was already calibrated upstream by (d))."""
    projection = row.get("projection") if isinstance(row.get("projection"), Mapping) else {}
    if projection.get(LIVE_PROB_MARKER):
        return {}
    found = stamp(row, live_prob, _row_fair(row), use=USE_RAIL)
    if not found:
        return {}
    return {"live_model_probability_cal": found["p"], "live_cal_k": found["k"], "live_cal_cell": found["cell"]}


def display_columns(row: Mapping[str, Any], quote: Mapping[str, Any], model_prob: Any) -> dict[str, Any]:
    """(b) The board's shown calibrated model probability and the model EV at it, or {}.

    The model EV is `expected_value_pct(best price, p')`, the same formula the board's market EV uses with the fair,
    so the two columns differ only by the probability. The market EV column itself is NOT changed (pre-registration
    §1.2: its over-promise is T1's, not this calibration's).
    """
    found = stamp(row, model_prob, _row_fair(row, quote), use=USE_DISPLAY)
    if not found:
        return {}
    out: dict[str, Any] = {"model_probability_cal": found["p"], "cal_k": found["k"], "cal_cell": found["cell"]}
    try:
        from syndicate.features.shared.opportunity_signals import expected_value_pct

        ev = expected_value_pct((quote or {}).get("price"), found["p"])
    except Exception:
        ev = None
    if ev is not None:
        out["model_ev_cal_pct"] = round(float(ev), 4)
    return out


#: (d) skips the cells #816 already calibrates in the live join (`college_live_total_calibration`).
_LIVE_PROB_SKIP = (("ncaab", "wncaab"), "totals")


def ncaaf_live_total_owned_by_835(cell: Any) -> bool:
    """True when `cell` is an NCAAF FULL-GAME LIVE total and #835's switch is on (todo #847 fix 2, lane
    cell-calibration-847d-fixes, user "Yes, fix (d) first" 2026-11-27).

    #835 (`ncaaf/live_total_dispersion`, `SYNDICATE_NCAAF_LIVE_TOTAL_CALIBRATION`) anchors the NCAAF live re-sim's
    full-game total draws to the close and widens them, in the refresh-worker's NCAAF tick, upstream of the join. This
    table's k for that cell (0.10 on 11-27) was fitted on the engine BEFORE that step, so serving it on top would
    correct the same over-confidence twice. While #835 is on, (c) and (d) leave the cell alone, the way (d) leaves
    #816's college basketball totals; with #835 off this is False and both behave exactly as before.

    FULL GAME ONLY, because that is all #835 moves (`calibrate_snapshot_totals` rewrites `totalRunsDist`, never a
    `segments` block). Every totals market of the cell (`totals`, `totals_alt`, ...) is priced from those draws.
    The switch is #835's OWN predicate, read where this runs: its key is GLOBAL in `local_production.env`, so every
    role that runs (c) or (d) reads the value the NCAAF tick reads. A failed import cannot leave #835 running either
    (the tick imports the same module), so it reads as off.
    """
    parts = str(cell or "").split("|")
    if len(parts) != 4 or parts[0] != "ncaaf" or not parts[1].startswith("totals") or parts[2] != "full" \
            or parts[3] != "live":
        return False
    try:
        from syndicate.features.ncaaf.live_total_dispersion import enabled as _835_on

        return bool(_835_on())
    except Exception:
        return False


def live_probability(sport: Any, market: Any, segment: Any, model_prob: Any, market_prob: Any, *,
                     table: Mapping[str, float] | None = None) -> tuple[float, dict[str, Any]] | None:
    """(d) The shared live probability, calibrated per cell: (p', stamp), or None to leave it as it is.

    Called where the live join has the side's model probability and its market probability (after the point
    estimator, #780's prob scale and #816's college-totals step), so it generalises #816 to every other served
    live cell: same transform shape with no level (#816's `a` = 0, `c` = k). None when the LIVE_PROB switch is off,
    the cell is not served, the cell is a college basketball total (#816 owns it), or it is an NCAAF full-game live
    total while #835's switch is on (#835 owns it: `ncaaf_live_total_owned_by_835`). A BETTING change: default off.

    THE CALLER MUST MARK THE ROW: when it serves p', it sets `projection[LIVE_PROB_MARKER]` to the stamp, so the
    rail's (a) does not calibrate the same live number a second time (`rail_columns`).
    """
    try:
        if not enabled(USE_LIVE_PROB):
            return None
        sport_key = str(sport or "").strip().lower()
        market_key = str(market or "").strip().lower()
        if sport_key in _LIVE_PROB_SKIP[0] and market_key.startswith(_LIVE_PROB_SKIP[1]):
            return None
        segment_key = str(segment or "").strip().lower() or "full"
        cell = f"{sport_key}|{market_key}|{'full' if segment_key in ('game', 'full_game') else segment_key}|live"
        if ncaaf_live_total_owned_by_835(cell):
            return None
        k = k_for_cell(cell, table=table)
        if k is None:
            return None
        p = calibrate(model_prob, market_prob, k)
        if p is None:
            return None
        sd = float((_STATE.get("sd") or {}).get(cell, 0.0)) if table is None else 0.0
        return p, {"cell": cell, "k": round(k, 4), "k_sd": round(sd, 4), "p_raw": round(float(model_prob), 6),
                   "version": VERSION}
    except Exception:
        return None


def live_std_err(p_raw: float, fair: float, p_cal: float, std_err: Any, stamp: Mapping[str, Any]) -> Any:
    """The precision gate's error for p', carried through the transform the way #816 carries its own.

    The sim's error times the transform's slope at p (`k p'(1-p') / (p(1-p))`), plus the fit's own error on k
    (`p'(1-p') |logit p - logit fair| sd_k`), added in quadrature. So a k the data barely supports cannot by itself
    clear the gate, and a shrink does not by itself withhold a line: the edge and the sim error shrink together.
    """
    se = _num(std_err)
    k = _num(stamp.get("k"))
    if se is None or k is None:
        return std_err
    p = min(1.0 - _EPS, max(_EPS, float(p_raw)))
    q = min(1.0 - _EPS, max(_EPS, float(p_cal)))
    slope = k * q * (1.0 - q) / (p * (1.0 - p))
    fit = q * (1.0 - q) * abs(_logit(p) - _logit(fair)) * float(_num(stamp.get("k_sd")) or 0.0)
    return math.sqrt((slope * se) ** 2 + fit ** 2)


def rank_stake_factor(cell: str | None, *, table: Mapping[str, float] | None = None) -> float | None:
    """(c): the cell's served k when the RANK_STAKE switch is on AND k is below the optimizer's floor, else None.

    Scope is exactly the pre-registered (c): only where the evidence supports MORE shrink than the 0.5 floor
    allows does the factor change; everywhere else the optimizer's own factor stands.
    """
    try:
        if not enabled(USE_RANK_STAKE):
            return None
        from syndicate.features.shared import daily_optimizer as opt

        # Fix 2 (#847): an NCAAF full-game live total is #835's while its switch is on, so its pre-#835 k (0.10) does
        # not drop the cell's rank and stake; the optimizer's own factor stands, exactly as with (c) off.
        if ncaaf_live_total_owned_by_835(cell):
            return None
        k = k_for_cell(cell, table=table)
        if k is None or k >= opt.FACTOR_FLOOR:
            return None
        return max(K_FLOOR, k)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# the fit (cron and scripts; never on a request path)
# ---------------------------------------------------------------------------


def fit_floor(cell: str) -> str | None:
    """The first game date this cell may be fitted on, or None for the window floor only."""
    parts = str(cell).split("|")
    sport = parts[0] if parts else ""
    market = parts[1] if len(parts) > 1 else ""
    floors = [SPORT_FIT_FLOORS[sport]] if sport in SPORT_FIT_FLOORS else []
    for sports, prefix, day in MARKET_FIT_FLOORS:
        if sport in sports and market.startswith(prefix):
            floors.append(day)
    return max(floors) if floors else None


def apply_floors(games: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Each game with only the cells its date may be fitted on (games left with no cell are dropped)."""
    out: list[dict[str, Any]] = []
    for game in games:
        day = str(game.get("date") or "")
        cal = {cell: acc for cell, acc in (game.get("cal") or {}).items()
               if (fit_floor(cell) is None or day >= str(fit_floor(cell)))}
        if cal:
            out.append({**game, "cal": cal})
    return out


def group_of(cell: str) -> str:
    parts = str(cell).split("|")
    return "|".join(parts[:2])


def _se(ci95: Any) -> float | None:
    if not isinstance(ci95, (list, tuple)) or len(ci95) != 2:
        return None
    lo, hi = _num(ci95[0]), _num(ci95[1])
    if lo is None or hi is None or hi <= lo:
        return None
    return (hi - lo) / (2.0 * Z95)


def pool(calibration: Sequence[Mapping[str, Any]], sums: Mapping[str, tuple[float, float]]) -> dict[str, dict[str, Any]]:
    """Per cell: the partially pooled posterior (pre-registration §1.1 step 2 + its 11-18 amendment).

    `calibration` is `daily_optimizer.fit_calibration` output; `sums[cell] = (Σd², Σd·r)` over the same games.
    """
    by_group: dict[str, list[Mapping[str, Any]]] = {}
    for result in calibration:
        by_group.setdefault(group_of(result["cell"]), []).append(result)
    out: dict[str, dict[str, Any]] = {}
    for group, results in sorted(by_group.items()):
        sdd = sum(sums.get(r["cell"], (0.0, 0.0))[0] for r in results)
        sdr = sum(sums.get(r["cell"], (0.0, 0.0))[1] for r in results)
        group_w = (sdr / sdd) if sdd > 0 else None
        usable = [(r, _se(r.get("ci95"))) for r in results if r.get("w") is not None]
        usable = [(r, se) for r, se in usable if se is not None and se > 0]
        tau2: float | None = None
        v_g: float | None = None
        if len(usable) >= 2 and group_w is not None:
            weights = [1.0 / (se * se) for _, se in usable]
            total = sum(weights)
            mean_iv = sum(wt * float(r["w"]) for (r, _), wt in zip(usable, weights)) / total
            q = sum(wt * (float(r["w"]) - mean_iv) ** 2 for (r, _), wt in zip(usable, weights))
            c = total - sum(wt * wt for wt in weights) / total
            tau2 = max(0.0, (q - (len(usable) - 1)) / c) if c > 0 else None
            v_g = 1.0 / total
        for result in results:
            cell = result["cell"]
            w, se = _num(result.get("w")), _se(result.get("ci95"))
            entry: dict[str, Any] = {"group": group, "group_w": group_w, "tau2": tau2, "w": w, "se": se,
                                     "pooled": False, "post_mean": None, "post_sd": None}
            if w is not None and se is not None and se > 0:
                if tau2 is None or v_g is None or group_w is None:
                    mean, var = w, se * se
                elif tau2 == 0.0:
                    mean, var = group_w, v_g
                    entry["pooled"] = True
                else:
                    prec = 1.0 / (se * se) + 1.0 / tau2
                    mean = (w / (se * se) + group_w / tau2) / prec
                    shrink = (se * se) / (se * se + tau2)
                    var = 1.0 / prec + shrink * shrink * v_g
                    entry["pooled"] = True
                entry["post_mean"], entry["post_sd"] = mean, math.sqrt(var)
            out[cell] = entry
    return out


def _cell_sums(games: Sequence[Mapping[str, Any]]) -> dict[str, tuple[float, float]]:
    sums: dict[str, list[float]] = {}
    for game in games:
        for cell, acc in (game.get("cal") or {}).items():
            if acc and acc[0]:
                s = sums.setdefault(cell, [0.0, 0.0])
                s[0] += float(acc[1])
                s[1] += float(acc[2])
    return {cell: (s[0], s[1]) for cell, s in sums.items()}


def served_k(entry: Mapping[str, Any], verdict: Any) -> float | None:
    """The served k for a pooled entry: clip(post_mean + 1.96 post_sd, K_FLOOR, 1) on an overconfident verdict."""
    if verdict != "overconfident":
        return None
    mean, sd = _num(entry.get("post_mean")), _num(entry.get("post_sd"))
    if mean is None or sd is None:
        return None
    k = min(K_CEILING, max(K_FLOOR, mean + Z95 * sd))
    return k if k < K_CEILING else None


def fit_table(games: Sequence[Mapping[str, Any]], *, now: datetime, today: str,
              resamples: int | None = None) -> dict[str, Any]:
    """The table payload from the optimizer's window games (already windowed by the caller)."""
    from syndicate.features.shared import daily_optimizer as opt

    floored = apply_floors(games)
    calibration = opt.fit_calibration(floored, resamples=resamples or opt.RESAMPLES)
    pooled = pool(calibration, _cell_sums(floored))
    cells: dict[str, dict[str, Any]] = {}
    diagnostics: list[dict[str, Any]] = []
    for result in calibration:
        entry = pooled.get(result["cell"], {})
        k = served_k(entry, result.get("verdict"))
        row = {"cell": result["cell"], "verdict": result.get("verdict"), "games": result["games"],
               "dates": result["dates"], "rows": result["rows"], "w": result.get("w"), "ci95": result.get("ci95"),
               "group": entry.get("group"), "group_w": opt._r(entry.get("group_w")), "tau2": opt._r(entry.get("tau2")),
               "pooled": entry.get("pooled"), "post_mean": opt._r(entry.get("post_mean")),
               "post_sd": opt._r(entry.get("post_sd")), "k": opt._r(k) if k is not None else None,
               "optimizer_factor": result.get("edge_shrink")}
        diagnostics.append(row)
        if k is not None:
            cells[result["cell"]] = {key: row[key] for key in
                                     ("k", "w", "ci95", "post_mean", "post_sd", "group", "group_w", "tau2",
                                      "pooled", "games", "dates", "rows", "optimizer_factor")}
    cells = dict(sorted(cells.items(), key=lambda kv: (-kv[1]["games"], kv[0]))[:MAX_ENTRIES])
    dates = sorted({str(g.get("date")) for g in floored})
    return {
        "source": SOURCE, "version": VERSION, "today": today,
        "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "expires_at": (now + timedelta(hours=TTL_HOURS)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "window": {"days": opt.WINDOW_DAYS, "first_date": dates[0] if dates else None,
                   "last_date": dates[-1] if dates else None, "games": len(floored), "dates": len(dates)},
        "rule": {"transform": "logit p' = logit fair + k (logit p_model - logit fair)",
                 "k": "clip(pooled w* posterior mean + 1.96 sd, K_FLOOR, 1) on an overconfident verdict",
                 "k_floor": K_FLOOR, "k_ceiling": K_CEILING, "pool_by": "sport|market",
                 "sport_fit_floors": dict(SPORT_FIT_FLOORS),
                 "market_fit_floors": [{"sports": list(s), "market_prefix": m, "from": d} for s, m, d in MARKET_FIT_FLOORS],
                 "findings": ".syndicate/findings_2026-11-18_cell_calibration.md"},
        "cells": cells,
        "diagnostics": diagnostics,
    }


def held_out_brier(games: Sequence[Mapping[str, Any]], ks: Mapping[str, float]) -> dict[str, list[float]]:
    """Per served cell, per held-out game: [rows, Δ Brier·rows of k vs raw] from the sums (linear twin).

    Brier(p_m + k d) - Brier(p_m + d) summed over a game's rows = (k² - 1) Σd² - 2 (k - 1) Σd·r.
    """
    out: dict[str, list[list[float]]] = {}
    for game in games:
        for cell, acc in (game.get("cal") or {}).items():
            k = ks.get(cell)
            if k is None or not acc or not acc[0]:
                continue
            delta = (k * k - 1.0) * float(acc[1]) - 2.0 * (k - 1.0) * float(acc[2])
            out.setdefault(cell, []).append([float(acc[0]), delta])
    return out
