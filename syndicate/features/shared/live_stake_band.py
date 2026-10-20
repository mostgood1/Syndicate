"""The live stake BAND: a bet that passed every gate is sized $5-$10, scaled by edge.

USER DECISION 2026-10-20 (lane `live-stake-band`): "Bets should be $5-$10 not
under $1", rule chosen "Scale by edge":

    stake = min(max_dollars, min_dollars + (max_dollars - min_dollars) * full_kelly / kelly_at_max)

WHY A BAND AND NOT A BIGGER KELLY. Measured on the fleet's 10-20 Kalshi plan:
the edge left after the venue fee is 0.5-1.5 probability points, so FULL Kelly
is 0.47% (NCAAF DEL -3.5) and 3.17% (NBA Maxey U24.5) of bankroll. Quarter
Kelly on the order's own shard cash ($170 / $245) is $0.20 / $0.49 -- under the
$1 minimum -- and even full Kelly on $170 is $0.80. No Kelly multiplier reaches
$5 on these edges, so the dollar amount is set by the band and Kelly only
decides WHERE in the band a bet sits.

WHAT THE BAND DOES NOT CHANGE. Which rows are bet: every EV gate, the fee
gate, `zero_kelly_stake`, the position cut and the in-play refusal ran before
this, in `commit_portfolio`. Every executor cap still runs after it. Only the
dollar amount of a position that already exists is replaced.

FUNDING. A position may not be sized past the cash that pays for it: the
order's Kalshi shard, or the venue's capital elsewhere, as the compounding
step stamped it. Cash that cannot cover the band's FLOOR refuses by name
(`stake_band_exceeds_funding_cash`) -- the floor is the user's minimum, so a
bet below it is not placed. Cash between the floor and the band stake trims
the stake to the cash. No stamp (compounding off) means no plan-side bound;
the executor's balance and shard checks still apply.

Absent / anything but `on` => OFF, today's behaviour byte-identical. An
unparseable number falls back to OFF, never to a guessed band: an unknown must
not land on the permissive branch.
"""

from __future__ import annotations

import os
from typing import Any, Mapping

MODE_ENV = "SYNDICATE_LIVE_STAKE_BAND"
_MIN_ENV = "SYNDICATE_LIVE_STAKE_BAND_MIN_DOLLARS"
_MAX_ENV = "SYNDICATE_LIVE_STAKE_BAND_MAX_DOLLARS"
_KELLY_AT_MAX_ENV = "SYNDICATE_LIVE_STAKE_BAND_KELLY_AT_MAX"

DEFAULT_MIN_DOLLARS = 5.0
DEFAULT_MAX_DOLLARS = 10.0
# Full Kelly at which a bet reaches the top of the band. 5% of bankroll at full
# Kelly is a large edge on these markets (the 10-20 plan's best was 3.17%).
DEFAULT_KELLY_AT_MAX = 0.05

REFUSAL_NO_KELLY = "stake_band_no_kelly"
REFUSAL_EXCEEDS_FUNDING = "stake_band_exceeds_funding_cash"
# THE HEAVY-FAVOURITE CAP [user 2026-10-20, "C: -1000 cutoff + $5 cap"]: a tiny
# edge on a near-certain favourite gives a large Kelly fraction, so the band put
# $10 on SAS/OKC +20.5 at -1329 to win ~$0.75. With the cap on, a band bet
# priced shorter than the cutoff is refused, and one shorter than the favourite
# line is capped at a maximum loss (on these venues the stake IS the loss).
# Near-evens and underdogs keep the band's size. Off unless `..._CAP=on`.
REFUSAL_HEAVY_FAVOURITE = "stake_band_heavy_favourite"
FAVOURITE_CAP_ENV = "SYNDICATE_LIVE_BAND_FAVOURITE_CAP"
_REFUSE_SHORTER_ENV = "SYNDICATE_LIVE_BAND_REFUSE_SHORTER_THAN"
_FAVOURITE_SHORTER_ENV = "SYNDICATE_LIVE_BAND_FAVOURITE_SHORTER_THAN"
_FAVOURITE_MAX_LOSS_ENV = "SYNDICATE_LIVE_BAND_FAVOURITE_MAX_LOSS"
DEFAULT_REFUSE_SHORTER_THAN = -1000.0
DEFAULT_FAVOURITE_SHORTER_THAN = -200.0
DEFAULT_FAVOURITE_MAX_LOSS = 5.0


def _american_env(name: str, default: float) -> float:
    """A negative American price from env (e.g. -1000), or the default."""
    raw = str(os.environ.get(name) or "").strip()
    try:
        value = float(raw) if raw else default
    except ValueError:
        return default
    return value if value <= -100 else default


def favourite_cap_config() -> dict[str, Any]:
    """The cap's knobs; `on` only when `SYNDICATE_LIVE_BAND_FAVOURITE_CAP=on`."""
    on = str(os.environ.get(FAVOURITE_CAP_ENV) or "").strip().lower() in {"on", "1", "true", "yes"}
    refuse = _american_env(_REFUSE_SHORTER_ENV, DEFAULT_REFUSE_SHORTER_THAN)
    favourite = _american_env(_FAVOURITE_SHORTER_ENV, DEFAULT_FAVOURITE_SHORTER_THAN)
    max_loss = _env_number(_FAVOURITE_MAX_LOSS_ENV, DEFAULT_FAVOURITE_MAX_LOSS)
    return {
        "on": on,
        "refuse_shorter_than": refuse,
        "favourite_shorter_than": favourite,
        "favourite_max_loss": max_loss if max_loss is not None else DEFAULT_FAVOURITE_MAX_LOSS,
    }


def favourite_cap_verdict(position: Mapping[str, Any], stake: float, cap: Mapping[str, Any]) -> tuple[str, float]:
    """(`band` | `capped` | `refused`, stake) for one band-sized bet."""
    if not cap.get("on"):
        return "band", stake
    try:
        american = float(position.get("price"))
    except (TypeError, ValueError):
        return "band", stake
    if american <= float(cap["refuse_shorter_than"]):
        return "refused", 0.0
    if american <= float(cap["favourite_shorter_than"]) and stake > float(cap["favourite_max_loss"]):
        return "capped", round(float(cap["favourite_max_loss"]), 2)
    return "band", stake


def _env_number(name: str, default: float) -> float | None:
    raw = str(os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        return None
    if value != value or value <= 0 or value in (float("inf"), float("-inf")):
        return None
    return value


# THE SMALL-EDGE LINE [user 2026-10-20, option C]: a position whose
# `stake_fraction` (the system's own trust-adjusted size, after the Kelly
# multiplier, credibility, skill and price reliability) is under this is NOT put
# in the band -- it keeps its compounded stake, which the one-contract floor
# makes about one contract. Without it the band turns every admitted row into
# $5+, however thin. Absent = no line (the band sizes every position, as
# before). 0.001 is the line the fixed $1-of-$1,000 minimum used to draw.
SMALL_EDGE_ENV = "SYNDICATE_LIVE_SMALL_EDGE_FRACTION"


def small_edge_fraction() -> float | None:
    """The stake-fraction line, or None when unset or unusable (0 < x < 1)."""
    value = _env_number(SMALL_EDGE_ENV, -1.0)
    if value is None or value <= 0 or value >= 1:
        return None
    return value


def band_config() -> dict[str, Any]:
    """Resolved knobs, and `on` only when every one of them is usable."""
    requested = str(os.environ.get(MODE_ENV) or "").strip().lower() == "on"
    low = _env_number(_MIN_ENV, DEFAULT_MIN_DOLLARS)
    high = _env_number(_MAX_ENV, DEFAULT_MAX_DOLLARS)
    kelly_at_max = _env_number(_KELLY_AT_MAX_ENV, DEFAULT_KELLY_AT_MAX)
    invalid = None
    if low is None or high is None or kelly_at_max is None:
        invalid = "unparseable_number"
    elif low > high:
        invalid = "min_above_max"
    elif kelly_at_max > 1.0:
        invalid = "kelly_at_max_above_one"
    return {
        "on": requested and invalid is None,
        "requested": requested,
        "invalid": invalid if requested else None,
        "min_dollars": low,
        "max_dollars": high,
        "kelly_at_max": kelly_at_max,
        "small_edge_fraction": small_edge_fraction(),
    }


def band_stake(full_kelly: float, config: Mapping[str, Any]) -> float:
    """Dollars for one bet: the floor plus the band's width times its share of `kelly_at_max`."""
    low = float(config["min_dollars"])
    high = float(config["max_dollars"])
    share = max(0.0, float(full_kelly)) / float(config["kelly_at_max"])
    return round(min(high, low + (high - low) * share), 2)


def full_kelly_of(position: Mapping[str, Any]) -> float | None:
    """`sizing.kelly_fraction` -- FULL Kelly on the fee-inclusive price, before the
    quarter-Kelly multiplier and the sample credibility (`compute_board_stake`)."""
    sizing = position.get("sizing")
    if not isinstance(sizing, Mapping):
        return None
    value = sizing.get("kelly_fraction")
    if value is None or isinstance(value, bool):
        return None
    try:
        kelly = float(value)
    except (TypeError, ValueError):
        return None
    return kelly if kelly > 0 else None


def funding_cash_of(position: Mapping[str, Any], venue: str) -> float | None:
    """The cash that pays for this order, as the compounding step stamped it, or None."""
    stamp = position.get("compounding")
    if not isinstance(stamp, Mapping) or not stamp.get("known"):
        return None
    raw = stamp.get("shard_cash") if str(venue).strip().lower() == "kalshi" else None
    if raw is None:
        raw = stamp.get("capital")
    try:
        return float(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None


def apply_live_stake_band(
    plan: dict[str, Any],
    *,
    venue: str,
    refusals: dict[str, int],
    by_market: dict[str, dict[str, int]],
    by_sport: dict[str, dict[str, int]],
    config: Mapping[str, Any] | None = None,
) -> None:
    """Re-dollar every live position into the band. In place; a no-op when off.

    Refusals land in the plan's own tables, so `sum(refusals) + positions ==
    rows_in` still holds. `plan["stake_band"]` records what was applied.
    """
    cfg = dict(config or band_config())
    if not cfg.get("on"):
        if cfg.get("requested"):
            plan["stake_band"] = {"on": False, "invalid": cfg.get("invalid")}
        return

    kept: list[dict[str, Any]] = []
    refused: dict[str, int] = {}
    refused_keys: list[str] = []
    trimmed = 0
    left_small = 0
    fav_cap = favourite_cap_config()
    fav_capped = 0
    before = 0.0
    line = cfg.get("small_edge_fraction")

    def _refuse(reason: str, position: Mapping[str, Any]) -> None:
        refusals[reason] = refusals.get(reason, 0) + 1
        market = str(position.get("market") or "").strip().lower() or "unkeyed"
        sport = str(position.get("sport") or "").strip().lower() or "unkeyed"
        by_market.setdefault(reason, {})[market] = by_market.setdefault(reason, {}).get(market, 0) + 1
        by_sport.setdefault(reason, {})[sport] = by_sport.setdefault(reason, {}).get(sport, 0) + 1
        refused[reason] = refused.get(reason, 0) + 1
        refused_keys.append(str(position.get("position_key") or ""))

    for position in list(plan.get("positions") or []):
        if not isinstance(position, dict):
            continue
        prior = float(position.get("stake_dollars") or 0.0)
        before += prior
        fraction = position.get("stake_fraction")
        try:
            fraction = float(fraction) if fraction is not None else None
        except (TypeError, ValueError):
            fraction = None
        if line is not None and fraction is not None and fraction < float(line):
            # A small edge stays small: the compounded stake (one contract after
            # the floor) is placed as is, not lifted to the band's $5 floor.
            position["stake_band"] = {
                "left_below_small_edge_fraction": True,
                "stake_fraction": fraction,
                "small_edge_fraction": line,
                "stake_dollars": round(prior, 2),
            }
            left_small += 1
            kept.append(position)
            continue
        kelly = full_kelly_of(position)
        if kelly is None:
            _refuse(REFUSAL_NO_KELLY, position)
            continue
        stake = band_stake(kelly, cfg)
        verdict, capped_stake = favourite_cap_verdict(position, stake, fav_cap)
        if verdict == "refused":
            position["stake_band"] = {"full_kelly": kelly, "band_stake_dollars": stake,
                                      "heavy_favourite_refused": True, "price": position.get("price")}
            _refuse(REFUSAL_HEAVY_FAVOURITE, position)
            continue
        if verdict == "capped":
            fav_capped += 1
        favourite_capped_from = stake if verdict == "capped" else None
        stake = capped_stake
        funding = funding_cash_of(position, venue)
        record = {
            "full_kelly": kelly,
            "band_stake_dollars": stake,
            "favourite_capped_from": favourite_capped_from,
            "stake_dollars_before_band": round(prior, 2),
            "funding_cash": funding,
        }
        if funding is not None:
            if funding < float(cfg["min_dollars"]):
                position["stake_band"] = record
                _refuse(REFUSAL_EXCEEDS_FUNDING, position)
                continue
            if stake > funding:
                stake = round(funding, 2)
                record["trimmed_to_funding"] = True
                trimmed += 1
        record["stake_dollars"] = stake
        position["stake_band"] = record
        scale = (stake / prior) if prior else None
        position["stake_dollars"] = stake
        attribution = position.get("attribution")
        if isinstance(attribution, dict):
            for key in ("stake_dollars_ev_only", "stake_dollars_sim_delta"):
                if attribution.get(key) is not None:
                    attribution[key] = round(float(attribution[key]) * scale, 2) if scale is not None else None
        kept.append(position)

    plan["positions"] = kept
    totals = dict(plan.get("totals") or {})
    totals["positions"] = len(kept)
    totals["staked_dollars"] = round(sum(float(p.get("stake_dollars") or 0.0) for p in kept), 2)
    plan["totals"] = totals
    plan["stake_band"] = {
        "on": True,
        "venue": venue,
        "config": {k: cfg.get(k) for k in ("min_dollars", "max_dollars", "kelly_at_max", "small_edge_fraction")},
        "left_below_small_edge_fraction": left_small,
        "favourite_cap": dict(fav_cap),
        "favourite_capped": fav_capped,
        "positions_in": len(kept) + sum(refused.values()),
        "positions_out": len(kept),
        "staked_dollars_before": round(before, 2),
        "staked_dollars_after": totals["staked_dollars"],
        "trimmed_to_funding": trimmed,
        "refused": dict(sorted(refused.items())),
        "refused_keys": refused_keys,
    }
