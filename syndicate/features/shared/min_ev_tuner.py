"""Close the learning loop: per-cell `min_ev_pct`, moved by settled results.

**WHAT THIS IS.** `portfolio_settings.DEFAULT_MIN_EV_PCT` is one number for
every venue, sport and market, and nothing ever moved it: settled results were
graded, CLV was stamped, and neither fed back into what the next slate accepts.
This reads the settled execution ledger once a night, groups it into CELLS --
`venue x sport x market x season_phase` -- and proposes moving that cell's EV
cut line one bounded step:

- **raise** when the cell's MARGINAL rows -- those with EV in
  `[cut, cut + band)`, exactly the rows a raise would stop taking -- have
  trailing ROI AND CLV both significantly NEGATIVE;
- **lower** when those marginal rows are both significantly POSITIVE (the bets
  just above the cut are earning, so the step below it is extrapolated to);
- **hold** otherwise, with the reason named.

**WHY THE MARGINAL BAND AND NOT THE WHOLE CELL.** `learnings.md` 2026-09-29
(STANDING): claimed edge has run ANTI-correlated with realised return in two
sports. Measured again on this ledger 2026-10-19 (8,598 settled paper rows, 17
dates, all books): ROI by EV band [2,3) +0.4%, [3,4) +2.1%, [4,5) -8.3%,
[5,7) -9.8%, with same-book CLV positive in every band (t 6-8). A whole-cell
rule would answer a cell lost by its 5%-EV rows by cutting its 2%-EV rows --
the better ones. Deciding on the band a move actually changes cannot. The
whole-cell numbers are still computed and logged, as the readout.

**WHAT THIS IS NOT -- user decision 2026-09-16 (`learnings.md`, FORBIDDEN):**
*"we shouldnt block anything globally ... every prop and game line is its own
entity"*. This never excludes a sport or a market. It moves a THRESHOLD, inside
a hard `[floor, ceiling]`, and every row is still judged on its own EV against
it -- a row whose EV clears the ceiling clears every cell. The ceiling is the
guarantee that a raised cell is a stricter bar, never a closed door.

**NEVER POOLS SEASON PHASES.** `season_phase` returns None for a date it cannot
place; such rows form no cell and are reported as `unphased`, never folded into
the regular season (`learnings.md`, season-phase models).

**SIGNIFICANCE IS COUNTED IN EVENTS, NOT ROWS.** Several props on one game are
one draw of that game's script; `learnings.md` 2026-08-20 measured row-pooling
overstating significance 3.4x. Returns and CLV are aggregated per `event_id`
first and the t-statistics are taken over events.

**CLV IS SAME-BOOK BY DEFAULT.** `order_clv` measured a different book's close
biased upward regardless of bet quality (+6.2 avg, 29/32 "beat"). Only
`close_book_scope == same_book` marks count toward the gate unless the scope
env says otherwise; every scope is still reported.

**ONE MOVE PER EVIDENCE BATCH.** A cell that moved is not moved again until
`min_new_events` NEW settled events have arrived since -- otherwise the same
losing fortnight would walk a cell from floor to ceiling in eight nights on one
piece of evidence.

**MODES** (`SYNDICATE_MIN_EV_TUNER`): `off` (nothing runs), `shadow` (the
default: proposals are computed, persisted and logged, nothing reads them at
commit time), `apply` (commit uses the per-cell cut). Absent or unrecognised
resolves to `shadow`, which changes no money -- never to `apply`.

Worker-owned: `run_nightly` is called from the settlement sweep on the worker,
never from a Flask route (CLAUDE.md, web does no heavy work).
"""

from __future__ import annotations

import math
import os
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from typing import Any, Callable

MODE_OFF = "off"
MODE_SHADOW = "shadow"
MODE_APPLY = "apply"
_ENV_MODE = "SYNDICATE_MIN_EV_TUNER"

# Venue families this tunes. Everything else (sportsbook paper rows) is out of
# scope and reported as such.
TUNED_VENUES = ("kalshi", "polymarket")

ACTION_RAISE = "raise"
ACTION_LOWER = "lower"
ACTION_HOLD = "hold"

_STATE_VERSION = 1
_AUDIT_CAP = 400
_PROPOSAL_CELLS_CAP = 400

# (env key, default, low, high). Bounds refuse rather than clamp, as
# `portfolio_settings._coerce` does: a typo must not become a different policy.
_KNOBS: dict[str, tuple[str, float, float, float]] = {
    "step_pct": ("SYNDICATE_MIN_EV_TUNER_STEP_PCT", 0.5, 0.05, 2.0),
    # 0.0, not higher: production's base IS 0.0 (`SYNDICATE_PORTFOLIO_MIN_EV_PCT=0`
    # on refresh-worker, user decision 2026-09-16, read in the first nightly line
    # 2026-10-19 19:25:36Z `base=0.0`). A floor above the base would make the
    # first raise from it (0.0 -> 0.5) an out-of-bounds override that
    # `shadow_cut_line` refuses. The floor's job is "never accept negative EV".
    "floor_pct": ("SYNDICATE_MIN_EV_TUNER_FLOOR_PCT", 0.0, 0.0, 10.0),
    "ceiling_pct": ("SYNDICATE_MIN_EV_TUNER_CEILING_PCT", 6.0, 0.5, 20.0),
    "trailing_events": ("SYNDICATE_MIN_EV_TUNER_TRAILING_EVENTS", 150.0, 10.0, 5000.0),
    "min_events": ("SYNDICATE_MIN_EV_TUNER_MIN_EVENTS", 40.0, 5.0, 5000.0),
    "min_clv_events": ("SYNDICATE_MIN_EV_TUNER_MIN_CLV_EVENTS", 30.0, 5.0, 5000.0),
    "min_new_events": ("SYNDICATE_MIN_EV_TUNER_MIN_NEW_EVENTS", 20.0, 1.0, 5000.0),
    "z": ("SYNDICATE_MIN_EV_TUNER_Z", 2.0, 1.0, 5.0),
    "band_pct": ("SYNDICATE_MIN_EV_TUNER_BAND_PCT", 1.0, 0.25, 5.0),
}
_ENV_CLV_SCOPES = "SYNDICATE_MIN_EV_TUNER_CLV_SCOPES"
_ENV_EVIDENCE_MODES = "SYNDICATE_MIN_EV_TUNER_EVIDENCE_MODES"
# `flat` (default; absent or unrecognised) or `dollars`. See `cell_evidence`.
_ENV_ROI_BASIS = "SYNDICATE_MIN_EV_TUNER_ROI_BASIS"


def roi_basis() -> str:
    raw = str(os.environ.get(_ENV_ROI_BASIS) or "").strip().lower()
    return "dollars" if raw == "dollars" else "flat"
_DEFAULT_CLV_SCOPES = ("same_book",)
# Paper venue orders run the SAME code as live up to the submit (see
# `execution_ledger`), priced at the venue's own quote; live alone is one day
# old at the time of writing. Both count by default and every cell reports the
# split, so a paper-only conclusion is visible as one.
_DEFAULT_EVIDENCE_MODES = ("live", "paper")


def tuner_mode() -> str:
    raw = str(os.environ.get(_ENV_MODE) or "").strip().lower()
    if raw in {"off", "0", "false", "no", "disabled"}:
        return MODE_OFF
    if raw == MODE_APPLY:
        return MODE_APPLY
    return MODE_SHADOW


def knobs() -> dict[str, float]:
    out: dict[str, float] = {}
    for name, (env_key, default, low, high) in _KNOBS.items():
        value = default
        raw = os.environ.get(env_key)
        if raw not in (None, ""):
            try:
                parsed = float(str(raw).strip())
            except ValueError:
                parsed = None
            if parsed is not None and low <= parsed <= high and parsed == parsed:
                value = parsed
        out[name] = value
    if out["floor_pct"] >= out["ceiling_pct"]:
        out["floor_pct"], out["ceiling_pct"] = _KNOBS["floor_pct"][1], _KNOBS["ceiling_pct"][1]
    return out


def _csv_env(name: str, default: Sequence[str]) -> tuple[str, ...]:
    raw = str(os.environ.get(name) or "").strip().lower()
    if not raw:
        return tuple(default)
    values = tuple(part.strip() for part in raw.split(",") if part.strip())
    return values or tuple(default)


# --------------------------------------------------------------------------
# Cells
# --------------------------------------------------------------------------


def venue_family(venue: Any) -> str | None:
    text = str(venue or "").strip().lower()
    for family in TUNED_VENUES:
        if family in text:
            return family
    return None


def is_ladder_venue(venue: Any) -> bool:
    """`paper:kalshi:ladder` / `paper:polymarket:ladder` -- the paper EV-band ladder book."""
    return str(venue or "").strip().lower().endswith(":ladder")


def order_mode(order: Mapping[str, Any]) -> str:
    mode = str(order.get("mode") or "").strip().lower()
    if mode:
        return mode
    return "paper" if str(order.get("venue") or "").lower().startswith("paper") else "unknown"


def cell_key(venue: Any, sport: Any, market: Any, selected_date: Any) -> str | None:
    """`venue|sport|market|phase`, or None when any part is unknown."""
    from syndicate.features.shared.season_phase import season_phase

    family = venue_family(venue)
    sport_key = str(sport or "").strip().lower()
    market_key = str(market or "").strip().lower()
    phase = season_phase(sport_key, selected_date)
    if not family or not sport_key or not market_key or not phase:
        return None
    return f"{family}|{sport_key}|{market_key}|{phase}"


def _as_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _stake(order: Mapping[str, Any]) -> float | None:
    for field in ("fill_stake_dollars", "requested_stake_dollars"):
        value = _as_float(order.get(field))
        if value is not None and value > 0:
            return value
    return None


def _settled_at(order: Mapping[str, Any]) -> str:
    return str(order.get("graded_at") or order.get("commence_time") or order.get("selected_date") or "")


def _clv(order: Mapping[str, Any], scopes: Sequence[str]) -> float | None:
    """Same-book CLV for one order, RECOMPUTED from its own prices where possible.

    WHY NOT JUST READ `closing_mark.clv_pct` (todo #719): every LIVE Kalshi mark
    was stamped with the contract fill price (0.65) read as American odds and came
    out ~-35 pt (13 live marks recomputed +0.46 +- 0.35). The unit fix lives at
    the shared choke point (`prediction_ledger._implied_from_price`), but marks
    already stamped keep the wrong number. With this lane's evidence now mostly
    LIVE fills, 30 such marks would read as a large spurious negative CLV --
    half of a RAISE signal. So: entry price (fill, else requested -- the same
    order as `order_clv._entry_price`) against the mark's `close_price`, through
    the shared converter. A contract-price entry whose close cannot be recomputed
    is dropped, never trusted.
    """
    mark = order.get("closing_mark")
    if not isinstance(mark, Mapping):
        return None
    if str(mark.get("close_book_scope") or "") not in scopes:
        return None
    entry = _as_float(order.get("fill_price"))
    if entry is None:
        entry = _as_float(order.get("requested_price"))
    close = mark.get("close_price")
    if entry is not None and close is not None:
        try:
            from syndicate.features.shared.clv_join import clv_pct_from_prices

            recomputed = _as_float(clv_pct_from_prices(entry, close))
        except Exception:  # noqa: BLE001 -- fall through to the guarded stored value
            recomputed = None
        if recomputed is not None:
            return recomputed
    if entry is not None and 0.0 < entry < 1.0:
        return None  # a contract-price mark we cannot recompute: stamped in the wrong unit pre-#719
    return _as_float(mark.get("clv_pct"))


# --------------------------------------------------------------------------
# Statistics -- over EVENTS
# --------------------------------------------------------------------------


def _t_stat(values: Sequence[float]) -> float | None:
    n = len(values)
    if n < 2:
        return None
    mean = sum(values) / n
    var = sum((v - mean) ** 2 for v in values) / (n - 1)
    if var <= 0:
        return None
    return mean / math.sqrt(var / n)


def _ratio_t(pnls: Sequence[float], stakes: Sequence[float]) -> float | None:
    """t of ROI = sum(pnl)/sum(stake), cluster-robust over events.

    The STAKE-WEIGHTED ratio, so its sign always matches the `roi_pct` printed
    beside it -- an equal-weighted mean of per-event returns read +0.37 on a
    cell whose ROI was -15% (kalshi ncaaf h2h, 2026-10-19 backtest).
    Linearised: u_e = pnl_e - roi * stake_e, se = sqrt(n/(n-1) * sum u_e^2) / sum stake.
    """
    n = len(pnls)
    total = sum(stakes)
    if n < 2 or total <= 0:
        return None
    roi = sum(pnls) / total
    resid = sum((p - roi * s) ** 2 for p, s in zip(pnls, stakes))
    if resid <= 0:
        return None
    se = math.sqrt(n / (n - 1) * resid) / total
    return roi / se


def _event_id(order: Mapping[str, Any]) -> str:
    return str(order.get("event_id") or order.get("game_pk") or order.get("idempotency_key") or "")


def _sim_share(order: Mapping[str, Any]) -> float:
    share = _as_float(order.get("sim_share_of_stake"))
    return min(1.0, max(0.0, share)) if share is not None else 0.0


def cell_evidence(
    orders: Sequence[Mapping[str, Any]],
    *,
    trailing_events: int,
    clv_scopes: Sequence[str],
    roi_basis: str = "flat",
) -> dict[str, Any]:
    """ROI and CLV for one cell's settled orders, clustered by event.

    The trailing window is the most recent `trailing_events` EVENTS (by the
    latest settle time among each event's orders), so one 12-prop game cannot
    crowd eleven other games out of the window.

    **`roi_pct` / `roi_t` -- the numbers `decide` reads -- are FLAT UNITS by
    default** (`roi_basis="flat"`): each bet counts once, whatever it was staked.
    WHY (`findings_2026-10-19_ev_overstatement_decomp.md`, lane
    ev-overstatement-decomp): from 10-05 the sizer stakes the raw sim
    probability at full weight (no fitted profile on the fleet), so 58-69% of
    every EV band's DOLLARS are sim-added stake, and the sim's fitted weight on
    those orders is w = -0.27 [-0.78, +0.18]. A dollar ROI therefore grades the
    sim's SIZING, not the cut line; "is a bet at this EV worth taking at all"
    is a per-bet question. The dollar ROI and its EV-only part (dollars net of
    `sim_share_of_stake`) are still computed, as the readout.
    """
    by_event: dict[str, list[Mapping[str, Any]]] = {}
    for order in orders:
        by_event.setdefault(_event_id(order), []).append(order)
    ordered = sorted(by_event.items(), key=lambda kv: max(_settled_at(o) for o in kv[1]))
    window = ordered[-trailing_events:] if trailing_events > 0 else ordered

    event_pnls: list[float] = []
    event_stakes: list[float] = []
    event_flat_returns: list[float] = []
    event_flat_counts: list[float] = []
    event_clvs: list[float] = []
    pnl_total = stake_total = 0.0
    ev_only_pnl_total = ev_only_stake_total = 0.0
    rows = 0
    modes: dict[str, int] = {}
    authority: dict[str, int] = {}
    ev_values: list[float] = []
    for _, group in window:
        pnl = stake = flat = 0.0
        flat_n = 0
        clvs: list[float] = []
        for order in group:
            rows += 1
            s = _stake(order) or 0.0
            p = _as_float(order.get("pnl_dollars")) or 0.0
            pnl += p
            stake += s
            if s > 0:
                flat += p / s
                flat_n += 1
                ev_only = 1.0 - _sim_share(order)
                ev_only_pnl_total += p * ev_only
                ev_only_stake_total += s * ev_only
            mode = order_mode(order)
            modes[mode] = modes.get(mode, 0) + 1
            who = "venue" if str(order.get("settled_by") or "") == "venue" else "inferred"
            authority[who] = authority.get(who, 0) + 1
            clv = _clv(order, clv_scopes)
            if clv is not None:
                clvs.append(clv)
            ev = _as_float(order.get("ev_pct"))
            if ev is not None:
                ev_values.append(ev)
        if stake > 0:
            event_pnls.append(pnl)
            event_stakes.append(stake)
            event_flat_returns.append(flat)
            event_flat_counts.append(float(flat_n))
            pnl_total += pnl
            stake_total += stake
        if clvs:
            event_clvs.append(sum(clvs) / len(clvs))

    dollar_t = _ratio_t(event_pnls, event_stakes)
    flat_t = _ratio_t(event_flat_returns, event_flat_counts)
    flat_n_total = sum(event_flat_counts)
    flat_roi = 100.0 * sum(event_flat_returns) / flat_n_total if flat_n_total > 0 else None
    dollar_roi = 100.0 * pnl_total / stake_total if stake_total > 0 else None
    if roi_basis == "dollars":
        roi, roi_t = dollar_roi, dollar_t
    else:
        roi_basis, roi, roi_t = "flat", flat_roi, flat_t
    clv_t = _t_stat(event_clvs)
    return {
        "events": len(event_pnls),
        "rows": rows,
        "roi_basis": roi_basis,
        "roi_pct": round(roi, 3) if roi is not None else None,
        "roi_t": round(roi_t, 3) if roi_t is not None else None,
        "staked_dollars": round(stake_total, 2),
        "pnl_dollars": round(pnl_total, 2),
        "dollar_roi_pct": round(dollar_roi, 3) if dollar_roi is not None else None,
        "dollar_roi_t": round(dollar_t, 3) if dollar_t is not None else None,
        "ev_only_roi_pct": (
            round(100.0 * ev_only_pnl_total / ev_only_stake_total, 3) if ev_only_stake_total > 0 else None
        ),
        "clv_events": len(event_clvs),
        "avg_clv_pct": round(sum(event_clvs) / len(event_clvs), 3) if event_clvs else None,
        "clv_t": round(clv_t, 3) if clv_t is not None else None,
        "avg_ev_pct": round(sum(ev_values) / len(ev_values), 3) if ev_values else None,
        "modes": dict(sorted(modes.items())),
        "authority": dict(sorted(authority.items())),
        "window_start": _settled_at(window[0][1][0]) if window else None,
        "window_end": max(_settled_at(o) for o in window[-1][1]) if window else None,
    }


def _effective_cut(orders: Sequence[Mapping[str, Any]], current: float, quantile: float = 0.05) -> float:
    """Where the cell is ACTUALLY cut: max(configured cut, the low-quantile EV taken).

    WHY. Production's configured cut is 0.0 (`SYNDICATE_PORTFOLIO_MIN_EV_PCT=0`)
    but the rows that reach the ledger sit at EV >= ~2: other gates (fair noise,
    net of fee, the shortlist) bind first. Measured 2026-10-19: with the band
    anchored at the configured 0.0, `[0, 1)` held 0-5 events in every cell, so
    the tuner could never move -- holds by construction, not by evidence.
    """
    values = sorted(v for v in (_as_float(o.get("ev_pct")) for o in orders) if v is not None and v >= current)
    if not values:
        return current
    idx = min(len(values) - 1, max(0, int(math.floor(quantile * (len(values) - 1)))))
    return max(current, values[idx])


def decide(
    evidence: Mapping[str, Any],
    *,
    current_pct: float,
    events_since_move: int | None,
    params: Mapping[str, float],
    effective_pct: float | None = None,
) -> tuple[str, float, str]:
    """(action, proposed_pct, reason). Pure: no I/O, no clock.

    `effective_pct` is where the cell is ACTUALLY being cut (see
    `_effective_cut`); a raise steps from there so it removes real rows, and a
    lower is only proposed when the configured cut is the binding gate.
    """
    effective = current_pct if effective_pct is None else max(current_pct, effective_pct)
    z = params["z"]
    if events_since_move is not None and events_since_move < params["min_new_events"]:
        return ACTION_HOLD, current_pct, "cooldown_awaiting_new_events"
    if (evidence.get("events") or 0) < params["min_events"]:
        return ACTION_HOLD, current_pct, "insufficient_events"
    if (evidence.get("clv_events") or 0) < params["min_clv_events"]:
        return ACTION_HOLD, current_pct, "insufficient_clv_events"
    roi_t, clv_t = evidence.get("roi_t"), evidence.get("clv_t")
    if roi_t is None or clv_t is None:
        return ACTION_HOLD, current_pct, "no_variance"
    step = params["step_pct"]
    if roi_t <= -z and clv_t <= -z:
        proposed = min(params["ceiling_pct"], round(effective + step, 4))
        if proposed <= current_pct:
            return ACTION_HOLD, current_pct, "at_ceiling"
        return ACTION_RAISE, proposed, "roi_and_clv_significantly_negative"
    if roi_t >= z and clv_t >= z:
        if effective - current_pct >= step:
            # Another gate cuts this cell above the configured line: lowering
            # the line would change nothing that is placed.
            return ACTION_HOLD, current_pct, "cut_not_binding"
        proposed = max(params["floor_pct"], round(current_pct - step, 4))
        if proposed >= current_pct:
            return ACTION_HOLD, current_pct, "at_floor"
        return ACTION_LOWER, proposed, "roi_and_clv_significantly_positive"
    roi_sig, clv_sig = abs(roi_t) >= z, abs(clv_t) >= z
    if roi_sig and clv_sig:
        return ACTION_HOLD, current_pct, "roi_and_clv_opposite_signs"
    if clv_sig:
        return ACTION_HOLD, current_pct, "only_clv_significant"
    if roi_sig:
        return ACTION_HOLD, current_pct, "only_roi_significant"
    return ACTION_HOLD, current_pct, "not_significant"


# --------------------------------------------------------------------------
# State (date-free path: see `portfolio_settings` on the keyvalue TTL)
# --------------------------------------------------------------------------


def _state_path():
    from syndicate.features.shared.refresh_state_store import reports_root

    return reports_root() / "intelligence" / "min_ev_tuner_state.json"


def load_state() -> dict[str, Any]:
    from syndicate.features.shared.refresh_state_store import read_json_file

    try:
        payload = read_json_file(_state_path())
    except Exception:  # noqa: BLE001 -- an unreadable state applies nothing
        return {}
    return dict(payload) if isinstance(payload, Mapping) else {}


def _save_state(state: Mapping[str, Any]) -> None:
    from syndicate.features.shared.refresh_state_store import write_json_file

    write_json_file(_state_path(), dict(state))


# --------------------------------------------------------------------------
# The nightly pass
# --------------------------------------------------------------------------


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def collect_cells(
    orders: Sequence[Mapping[str, Any]],
    *,
    evidence_modes: Sequence[str],
) -> tuple[dict[str, list[Mapping[str, Any]]], dict[str, int]]:
    """Settled, filled, tuned-venue orders by cell, plus why the rest were left out."""
    cells: dict[str, list[Mapping[str, Any]]] = {}
    skipped: dict[str, int] = {}

    def skip(reason: str) -> None:
        skipped[reason] = skipped.get(reason, 0) + 1

    # Since 1006cb75 the paper books record alongside live, so a bet placed live
    # (`venue=kalshi`) usually has a paper twin (`venue=paper:kalshi`) with the
    # same position_key and selected_date, and `venue_family` puts both in one
    # cell. Keep the live row (the real fill) and drop the twin, or that bet
    # counts twice.
    live_keys = {
        (venue_family(order.get("venue")), str(order.get("position_key")), str(order.get("selected_date") or ""))
        for order in orders
        if isinstance(order, Mapping)
        and order_mode(order) == "live"
        and str(order.get("status") or "") == "filled"
        and order.get("position_key")
        and venue_family(order.get("venue")) is not None
    }

    for order in orders:
        if not isinstance(order, Mapping):
            skip("not_a_mapping")
            continue
        if str(order.get("status") or "") != "filled" or not order.get("outcome"):
            skip("not_settled")
            continue
        if venue_family(order.get("venue")) is None:
            skip("venue_not_tuned")
            continue
        # THE EV-BAND LADDER BOOK (lane paper-alongside-live: `paper:<venue>:ladder`,
        # $1 flat on rows the CURRENT floor refuses) is not evidence about the bets the
        # cut TAKES. Left in, its -1..2% rows would drag each cell's effective cut down
        # and land in the RAISE band. Skipped UNCONDITIONALLY until the ladder reader --
        # pre-registered in findings_2026-10-19_min_ev_tuner_backtest.md -- is built; no
        # opt-in flag exists before that, so no setting can mix the two populations.
        if is_ladder_venue(order.get("venue")):
            skip("ladder_not_pre_registered")
            continue
        if order_mode(order) not in evidence_modes:
            skip("mode_not_in_evidence")
            continue
        # Only when live counts: with paper-only evidence the twin is the sole copy.
        if (
            order_mode(order) == "paper"
            and "live" in evidence_modes
            and order.get("position_key")
            and (
                venue_family(order.get("venue")),
                str(order.get("position_key")),
                str(order.get("selected_date") or ""),
            )
            in live_keys
        ):
            skip("paper_twin_of_live")
            continue
        if _stake(order) is None or _as_float(order.get("pnl_dollars")) is None:
            skip("no_stake_or_pnl")
            continue
        # A row no EV cut line decided is not evidence about the cut line: the
        # 552 venue-rebuilt live rows (`source=venue_rebuild`, 2026-10-02) carry
        # results but no plan fields at all.
        if _as_float(order.get("ev_pct")) is None:
            skip("no_ev_pct")
            continue
        key = cell_key(order.get("venue"), order.get("sport"), order.get("market"), order.get("selected_date"))
        if key is None:
            from syndicate.features.shared.season_phase import season_phase

            phase = season_phase(order.get("sport"), order.get("selected_date"))
            skip("unphased" if phase is None else "uncelled")
            continue
        cells.setdefault(key, []).append(order)
    return cells, skipped


def compute_proposals(
    orders: Sequence[Mapping[str, Any]],
    *,
    state: Mapping[str, Any],
    base_min_ev_pct: float,
    params: Mapping[str, float] | None = None,
    clv_scopes: Sequence[str] | None = None,
    evidence_modes: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Pure pass over `orders`: per-cell evidence and decision. No writes."""
    params = dict(params or knobs())
    clv_scopes = tuple(clv_scopes or _csv_env(_ENV_CLV_SCOPES, _DEFAULT_CLV_SCOPES))
    evidence_modes = tuple(evidence_modes or _csv_env(_ENV_EVIDENCE_MODES, _DEFAULT_EVIDENCE_MODES))
    basis = roi_basis()
    cells, skipped = collect_cells(orders, evidence_modes=evidence_modes)
    prior_cells = state.get("cells") if isinstance(state.get("cells"), Mapping) else {}

    out_cells: dict[str, dict[str, Any]] = {}
    actions: dict[str, int] = {}
    for key, group in sorted(cells.items()):
        prior = prior_cells.get(key) if isinstance(prior_cells.get(key), Mapping) else {}
        # The OVERRIDE, or None for a cell that has never moved -- which keeps
        # following the base, so a later user edit of the base still reaches it.
        override = _as_float(prior.get("min_ev_pct"))
        current = override if override is not None else float(base_min_ev_pct)
        evidence = cell_evidence(
            group, trailing_events=int(params["trailing_events"]), clv_scopes=clv_scopes, roi_basis=basis
        )
        effective = _effective_cut(group, current)
        band_hi = effective + params["band_pct"]
        marginal_rows = []
        for order in group:
            ev_pct = _as_float(order.get("ev_pct"))
            if ev_pct is not None and effective <= ev_pct < band_hi:
                marginal_rows.append(order)
        marginal = cell_evidence(
            marginal_rows, trailing_events=int(params["trailing_events"]), clv_scopes=clv_scopes, roi_basis=basis
        )
        marginal["band"] = [round(effective, 4), round(band_hi, 4)]
        # Cooldown counts the WHOLE cell's events: the band itself moves with
        # the cut, so its own count would reset on every move.
        total_events = len({_event_id(o) for o in group})
        moved_at_events = prior.get("moved_at_total_events")
        since = None if moved_at_events is None else max(0, total_events - int(moved_at_events))
        action, proposed, reason = decide(
            marginal, current_pct=current, events_since_move=since, params=params, effective_pct=effective
        )
        actions[action] = actions.get(action, 0) + 1
        entry = {
            "min_ev_pct": proposed if action != ACTION_HOLD else override,
            "previous_min_ev_pct": current,
            "effective_cut_pct": round(effective, 4),
            "action": action,
            "reason": reason,
            "total_events": total_events,
            "moved_at_total_events": total_events if action != ACTION_HOLD else moved_at_events,
            "marginal": marginal,
            "evidence": evidence,
        }
        if action == ACTION_HOLD and prior.get("moved_at"):
            entry["moved_at"] = prior.get("moved_at")
        out_cells[key] = entry
    # A cell with no settled rows tonight keeps its threshold: absence of
    # evidence is not evidence for moving it back.
    for key, prior in (prior_cells or {}).items():
        if key not in out_cells and isinstance(prior, Mapping):
            kept = dict(prior)
            kept.update(action=ACTION_HOLD, reason="no_settled_rows")
            out_cells[key] = kept
    return {
        "cells": out_cells,
        "skipped": dict(sorted(skipped.items())),
        "actions": dict(sorted(actions.items())),
        "params": params,
        "clv_scopes": list(clv_scopes),
        "evidence_modes": list(evidence_modes),
        "roi_basis": basis,
        "base_min_ev_pct": float(base_min_ev_pct),
    }


def run_nightly(
    *,
    orders_loader: Callable[[], Sequence[Mapping[str, Any]]] | None = None,
    now: datetime | None = None,
    force: bool = False,
    persist: bool = True,
) -> dict[str, Any]:
    """Once per UTC day: recompute, persist, log. Never raises.

    `force` skips the once-a-day gate (the CLI/backtest path). The decision is
    the same in shadow and apply; only `effective_min_ev_pct` reads the mode.
    """
    mode = tuner_mode()
    if mode == MODE_OFF:
        return {"ran": False, "reason": "off"}
    current = now or _utc_now()
    today = current.strftime("%Y-%m-%d")
    try:
        state = load_state()
        if not force and state.get("last_run_date") == today:
            return {"ran": False, "reason": "already_ran_today"}
        if orders_loader is None:
            from syndicate.features.shared.execution_ledger import full_history_orders

            orders_loader = full_history_orders
        from syndicate.features.shared.portfolio_settings import resolve_settings

        base = float(resolve_settings().min_ev_pct)
        result = compute_proposals(list(orders_loader() or ()), state=state, base_min_ev_pct=base)
    except Exception as exc:  # noqa: BLE001 -- a worker loop must not die here
        print(f"[min_ev_tuner] MIN_EV_TUNER_FAILED {type(exc).__name__}: {exc}", flush=True)
        return {"ran": False, "reason": "error", "error": f"{type(exc).__name__}: {exc}"}

    stamp = current.strftime("%Y-%m-%dT%H:%M:%SZ")
    moves = []
    for key, entry in result["cells"].items():
        if entry.get("action") in (ACTION_RAISE, ACTION_LOWER):
            entry["moved_at"] = stamp
            ev = entry.get("marginal") or {}
            moves.append(
                {
                    "at": stamp,
                    "mode": mode,
                    "cell": key,
                    "action": entry["action"],
                    "from": entry["previous_min_ev_pct"],
                    "to": entry["min_ev_pct"],
                    "band": ev.get("band"),
                    "events": ev.get("events"),
                    "roi_pct": ev.get("roi_pct"),
                    "roi_t": ev.get("roi_t"),
                    "avg_clv_pct": ev.get("avg_clv_pct"),
                    "clv_t": ev.get("clv_t"),
                    "modes": ev.get("modes"),
                }
            )
    audit = list(state.get("audit") or []) + moves
    new_state = {
        "version": _STATE_VERSION,
        "mode": mode,
        "last_run_date": today,
        "last_run_at": stamp,
        "base_min_ev_pct": result["base_min_ev_pct"],
        "params": result["params"],
        "clv_scopes": result["clv_scopes"],
        "evidence_modes": result["evidence_modes"],
        "roi_basis": result["roi_basis"],
        "skipped": result["skipped"],
        "actions": result["actions"],
        "cells": dict(list(result["cells"].items())[:_PROPOSAL_CELLS_CAP]),
        "audit": audit[-_AUDIT_CAP:],
    }
    if persist:
        try:
            _save_state(new_state)
        except Exception as exc:  # noqa: BLE001
            print(f"[min_ev_tuner] MIN_EV_TUNER_SAVE_FAILED {type(exc).__name__}: {exc}", flush=True)
            return {"ran": True, "persisted": False, "state": new_state}

    print(
        "[min_ev_tuner] MIN_EV_TUNER"
        f" mode={mode} date={today} cells={len(result['cells'])}"
        f" actions={result['actions']} skipped={result['skipped']}"
        f" base={result['base_min_ev_pct']} moves={len(moves)}",
        flush=True,
    )
    for move in moves:
        print(
            "[min_ev_tuner] MIN_EV_TUNER_MOVE "
            + " ".join(f"{k}={v}" for k, v in move.items()),
            flush=True,
        )
    return {"ran": True, "persisted": persist, "state": new_state, "moves": moves}


_ENV_RUN_AFTER_HOUR = "SYNDICATE_MIN_EV_TUNER_RUN_AFTER_HOUR_UTC"
# 12:00Z: after the night's games have graded and the closing-mark retries
# (`paper_settlement._CLOSE_MAX_ATTEMPTS` x 1h) have had their chance.
_DEFAULT_RUN_AFTER_HOUR = 12
_LAST_RUN_DATE_IN_PROCESS: dict[str, str] = {}


def maybe_run_nightly(*, now: datetime | None = None) -> dict[str, Any]:
    """The worker hook: cheap on every cycle, one real pass per UTC day.

    The in-process memo keeps the per-cycle cost at a clock read; the
    persisted `last_run_date` keeps a restart from running twice in a day.
    """
    if tuner_mode() == MODE_OFF:
        return {"ran": False, "reason": "off"}
    current = now or _utc_now()
    today = current.strftime("%Y-%m-%d")
    if _LAST_RUN_DATE_IN_PROCESS.get("date") == today:
        return {"ran": False, "reason": "already_ran_today"}
    try:
        after = int(str(os.environ.get(_ENV_RUN_AFTER_HOUR) or _DEFAULT_RUN_AFTER_HOUR).strip())
    except ValueError:
        after = _DEFAULT_RUN_AFTER_HOUR
    if not 0 <= after <= 23:
        after = _DEFAULT_RUN_AFTER_HOUR
    if current.hour < after:
        return {"ran": False, "reason": "before_run_hour"}
    result = run_nightly(now=current)
    if result.get("ran") or result.get("reason") == "already_ran_today":
        _LAST_RUN_DATE_IN_PROCESS["date"] = today
    return result


# --------------------------------------------------------------------------
# The read side -- what commit uses
# --------------------------------------------------------------------------


def effective_min_ev_pct(
    row: Mapping[str, Any],
    *,
    base_min_ev_pct: float,
    selected_date: str,
    state: Mapping[str, Any] | None = None,
    mode: str | None = None,
) -> tuple[float, str]:
    """(cut line, source) for one row. `source` is `base` unless a cell override applied.

    In `shadow` and `off` this returns the base unconditionally -- the shadow
    readout is computed beside it by `shadow_cut_line`, never instead of it.
    """
    mode = mode or tuner_mode()
    if mode != MODE_APPLY:
        return float(base_min_ev_pct), "base"
    override = shadow_cut_line(row, selected_date=selected_date, state=state)
    if override is None:
        return float(base_min_ev_pct), "base"
    return override, "tuned_cell"


def shadow_cut_line(
    row: Mapping[str, Any],
    *,
    selected_date: str,
    state: Mapping[str, Any] | None = None,
) -> float | None:
    """The tuned cut line for the row's cell, or None when the cell has none."""
    key = cell_key(row.get("venue"), row.get("sport"), row.get("market"), selected_date)
    if key is None:
        return None
    cells = (state if state is not None else load_state()).get("cells")
    entry = cells.get(key) if isinstance(cells, Mapping) else None
    if not isinstance(entry, Mapping):
        return None
    value = _as_float(entry.get("min_ev_pct"))
    params = knobs()
    if value is None or not params["floor_pct"] <= value <= params["ceiling_pct"]:
        return None
    return value
