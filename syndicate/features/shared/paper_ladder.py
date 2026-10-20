"""The PAPER LADDER: what the Kalshi / Polymarket paper books would hold below today's floor.

[2026-10-20, lane paper-alongside-live, USER DECISION relayed by session b87af0fc:
"yes - but we should reconsider the floors" -- to "Let Kalshi/Polymarket paper books
record a wider selection, paper only?"]

WHY. The venue paper books (`paper:kalshi`, `paper:polymarket`) record only what clears
the current floor: the board's Suggested flag (+2% net of fee at the best book) and then
a positive net-of-fee EV at the venue's own price. On 2026-10-20 both books' plans had
0 positions in every build after 11:18 AM CT, so the evidence that would let the user
reconsider those floors was not being collected at all.

WHAT. A SEPARATE paper book per venue, `paper:<venue>:ladder`, holding the venue-priced
rows the paper2 book did NOT stake, banded by net-of-fee EV at the venue's price:

    ge2     >= 2%      (Suggested rows the venue book still refused: zero Kelly,
                        position cap, venue-price floor, ...)
    1to2    [1, 2)
    0to1    [0, 1)
    m1to0   [-1, 0)

Below -1% is not recorded. Every NON-EV gate stays: the board's own Suggested
reasons other than the two EV-floor ones (opportunity lane, implausible book, fair
method, stale quote, single-book fair), the in-play market-fair refusal, valid sizing
inputs, and one side per line. Stake is a flat $1 (`stake_basis = flat_1`): the
question is per-band ROI, which is read flat, and Kelly is zero below 0% EV.

NEVER LIVE. Nothing here is read by the live plan (`_write_live_venue_plan` reads its
own scoped rows), `run_execution` refuses `book="ladder"` in live mode, and the book's
venue name is not one any live or pre-registered reader matches exactly. The min_ev
tuner matches venues by substring; it must exclude `:ladder` rows until its own lane
pre-registers how it reads them (see `.syndicate/findings_2026-10-20_paper_ladder.md`).

Off switch: `SYNDICATE_PAPER_LADDER=off` (absent = on).
"""

from __future__ import annotations

import os
from typing import Any, Mapping, Sequence

LADDER_VENUES = ("kalshi", "polymarket")
LADDER_BOOK = "ladder"
LADDER_STAKE_DOLLARS = 1.0
LADDER_FLOOR_PCT = -1.0
# (lower bound inclusive, upper bound exclusive or None, label). Order matters: first match.
LADDER_BANDS: tuple[tuple[float, float | None, str], ...] = (
    (2.0, None, "ge2"),
    (1.0, 2.0, "1to2"),
    (0.0, 1.0, "0to1"),
    (-1.0, 0.0, "m1to0"),
)
# The ONLY Suggested reasons a ladder row may carry: the EV floor itself.
EV_FLOOR_REASONS = frozenset({"ev_below_min", "ev_net_of_fee_below_min"})
REASON_SUGGESTED = "suggested_not_staked"
REASON_BELOW_FLOOR = "below_suggested_floor"


def ladder_enabled() -> bool:
    raw = str(os.environ.get("SYNDICATE_PAPER_LADDER") or "").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def ladder_venue_name(venue: str) -> str:
    """The ledger venue of a ladder row: `paper:kalshi:ladder`."""
    return f"paper:{str(venue).strip().lower()}:{LADDER_BOOK}"


def ev_band(ev_net_pct: float | None) -> str | None:
    if ev_net_pct is None:
        return None
    for low, high, label in LADDER_BANDS:
        if ev_net_pct >= low and (high is None or ev_net_pct < high):
            return label
    return None


def _as_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number else None


def ladder_reason(row: Mapping[str, Any]) -> str | None:
    """Why this shortlist row may enter the ladder, or None if it may not.

    A row with no `suggested_reasons` stamp is UNKNOWN and is refused: unknown must not
    take the permissive branch.
    """
    if row.get("suggested") is True:
        return REASON_SUGGESTED
    reasons = row.get("suggested_reasons")
    if not isinstance(reasons, (list, tuple)) or not reasons:
        return None
    return REASON_BELOW_FLOOR if set(str(r) for r in reasons) <= EV_FLOOR_REASONS else None


def eligible_rows(shortlist_rows: Sequence[Any]) -> list[Mapping[str, Any]]:
    """The shortlist rows the ladder may price at a venue: Suggested, or refused ONLY by the EV floor."""
    return [row for row in shortlist_rows or () if isinstance(row, Mapping) and ladder_reason(row)]


def _line_key(row: Mapping[str, Any]) -> tuple:
    line = _as_float(row.get("line"))
    return (
        str(row.get("sport") or "").strip().lower(),
        str(row.get("event_id") or ""),
        str(row.get("market") or "").strip().lower(),
        str(row.get("segment") or "full").strip().lower() or "full",
        str(row.get("player_name") or "").strip().lower(),
        None if line is None else abs(line),
    )


def build_ladder_plan(
    scoped_rows: Sequence[Mapping[str, Any]],
    *,
    venue: str,
    selected_date: str,
    staked_position_keys: set[str] | frozenset[str],
) -> dict[str, Any]:
    """The ladder plan for one venue: positions + per-band counts + named refusals.

    `scoped_rows` are `scope_rows_to_venue` output over `eligible_rows(...)`, so each
    carries the venue's price and `ev_pct_net_of_fee` (absent = the venue charges no
    fee, so net == gross `ev_pct`). `staked_position_keys` are the paper2 book's
    positions for this venue in the same build: the ladder is their complement.
    """
    from syndicate.features.shared.portfolio_commit import (
        _POSITION_IDENTITY_FIELDS,
        _refuses_in_play_market_fair,
        _sim_view_of,
        legacy_position_key,
        opening_key_for_row,
        position_key,
        sizing_inputs_with_provenance,
    )

    refusals: dict[str, int] = {}

    def refuse(reason: str) -> None:
        refusals[reason] = refusals.get(reason, 0) + 1

    best: dict[tuple, tuple[float, dict[str, Any]]] = {}
    for row in scoped_rows or ():
        if not isinstance(row, Mapping):
            refuse("row_not_a_mapping")
            continue
        reason = ladder_reason(row)
        if reason is None:
            refuse("not_ladder_eligible")
            continue
        key = position_key(row)
        if key in staked_position_keys:
            refuse("staked_by_venue_book")
            continue
        if _refuses_in_play_market_fair(row):
            refuse("in_play_market_fair")
            continue
        inputs, why, _provenance = sizing_inputs_with_provenance(row)
        if inputs is None:
            refuse(why or "no_sizing_inputs")
            continue
        net = _as_float(row.get("ev_pct_net_of_fee"))
        if net is None:
            net = _as_float(row.get("ev_pct"))
        band = ev_band(net)
        if band is None:
            refuse("below_ladder_floor" if net is not None else "no_ev")
            continue
        quote = row.get("quote") if isinstance(row.get("quote"), Mapping) else {}
        position = {field: row.get(field) for field in _POSITION_IDENTITY_FIELDS}
        position.update(
            {
                "commence_time": row.get("commence_time"),
                "position_key": key,
                "legacy_position_key": legacy_position_key(row),
                "opening_key": opening_key_for_row(row),
                "game_pk": row.get("gamePk") or row.get("game_id") or None,
                "side": row.get("side"),
                "line": row.get("line"),
                "book": quote.get("bookmaker"),
                "price": inputs.american_price,
                "stake_dollars": LADDER_STAKE_DOLLARS,
                "ev_pct": _as_float(row.get("ev_pct")),
                "model_edge_pct": _as_float(row.get("model_edge_pct")),
                **_sim_view_of(row),
                "venue": row.get("venue"),
                "price_source": row.get("price_source"),
                "venue_ticker": row.get("venue_ticker"),
                # THE LADDER TAGS, copied onto the ledger row by `run_execution`.
                "ev_band": band,
                "ev_net_pct": round(net, 4),
                "ladder_reason": reason,
                "stake_basis": "flat_1",
            }
        )
        # ONE SIDE PER LINE, the better net EV, as the board's Suggested rule does.
        line = _line_key(row)
        incumbent = best.get(line)
        if incumbent is not None:
            refuse("other_side_on_ladder")
            if incumbent[0] >= net:
                continue
        best[line] = (net, position)

    positions = [position for _net, position in best.values()]
    bands: dict[str, int] = {}
    for position in positions:
        bands[position["ev_band"]] = bands.get(position["ev_band"], 0) + 1
    return {
        "book": LADDER_BOOK,
        "venue": str(venue).strip().lower(),
        "selected_date": selected_date,
        "rows_in": len(scoped_rows or ()),
        "positions": positions,
        "bands": dict(sorted(bands.items())),
        "refusals": dict(sorted(refusals.items())),
        "totals": {"positions": len(positions), "staked_dollars": round(LADDER_STAKE_DOLLARS * len(positions), 2)},
    }


def ladder_report_line(plan: Mapping[str, Any], *, eligible: int) -> str:
    return (
        f"[paper_ladder] LADDER_PLAN_WRITTEN date={plan.get('selected_date')} venue={plan.get('venue')} "
        f"eligible={eligible} scoped={plan.get('rows_in')} positions={(plan.get('totals') or {}).get('positions')} "
        f"bands={plan.get('bands')} refusals={plan.get('refusals')}"
    )
