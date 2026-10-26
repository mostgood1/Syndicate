"""Decision policy v1 -- venue-native LOWER-BOUND EV, PAPER ONLY (Decision Engine Phase 2, `#736`).

Lane `decision-policy-paper`. Every rule here is pre-registered in
`.syndicate/findings_2026-10-26_decision_policy_v1_preregistration.md` (committed `8d16ab07`, before the z
fit and before any forward bet); this module implements that document and nothing else. Plan:
`docs/ai_context/plan_syndicate_decision_engine.md` section 3 L3.

**NOTHING HERE PLACES, SIZES OR SHOWS A LIVE BET.** The only caller is `decision_policy_paper`, which writes
its own paper book. User decision D2 (2026-10-26): select and size on venue-native net EV, paper2 FIRST,
canary live only after the Phase-2 edge gate.

THE POLICY, per DecisionRecord side x venue
-------------------------------------------
    p      = market.p_market                    # the Shin consensus; p_fair_v1 is NEVER read (user, 10-26)
    p_lb   = sigmoid(logit p - z_s * sigma)      # sigma on the one-vs-rest logit scale; z per sigma source
    c      = venue ask + venue_fees fee          # per $1 payout, as the record priced it
    EV_net = p / c - 1        EV_lb = p_lb / c - 1
    f      = min(0.02, max(0, (p_lb - c)/(1 - c)) * lambda_BM),  lambda_BM = D^2 / (D^2 + s_p^2), D = p - c

Sigma, in the plan's "inflating at each step" order: S1 the record's `sigma_fair_v1`; S2 the equal-weight
book-dispersion sigma plus a fitted residual; S3 twice the largest fitted residual when S2 cannot be computed.

Every line is its own decision. The gates below are per-line data quality and timing; nothing switches a
market off -- an uncertain fair only shrinks EV_lb.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

POLICY_VERSION = "decision_policy_v1"
PARAMS_PATH = Path(__file__).with_name("decision_policy_v1_params.json")

#: The one-sided lower-bound level: P(close below the bound) = 1 - Phi(1).
LOWER_BOUND_TAIL = 0.1587
#: A fitted z outside this range is degenerate: that source takes Z_DEFAULT instead (pre-registration s3).
Z_GUARD = (0.5, 2.0)
Z_DEFAULT = 1.0

DECISION_WINDOW_S = 36 * 3600
MAX_QUOTE_AGE_S = 12 * 3600
MIN_BOOKS = 2
P_CLIP = 1e-6

BANKROLL_UNITS = 1000.0
MAX_BET_FRACTION = 0.02
MAX_GAME_FRACTION = 0.05

VENUES = ("kalshi", "polymarket")
#: `#719`'s per-venue net floors (live on the fleet's floor-extras since 2026-10-21).
NET_FLOOR_PCT = {"kalshi": 1.0, "polymarket": 0.5}
#: The live entry band (user 2026-10-23); a REPORTED subset here, never a gate.
PRICE_BAND = (0.40, 0.75)

STRATEGY_EV_LB = "ev_lb"
STRATEGY_NET_FLOOR = "net_floor_719"
STRATEGY_SUGGESTED = "suggested_2pct"
CANDIDATE_STRATEGIES = (STRATEGY_EV_LB, STRATEGY_NET_FLOOR)
STRATEGIES = CANDIDATE_STRATEGIES + (STRATEGY_SUGGESTED,)

SIGMA_S1 = "S1_fair_v1"
SIGMA_S2 = "S2_dispersion"
SIGMA_S3 = "S3_inflated"

_LIVE_STATES = frozenset({"live", "in_progress", "final"})


# --------------------------------------------------------------------------- params


@dataclass
class Params:
    """The frozen fit (`scripts/fit_decision_policy_z.py`). Absent -> every z is Z_DEFAULT and r^2 is 0,
    and `loaded` is False so the job can say so instead of booking on unfitted numbers."""

    z_s1: float | None = None
    z_s2: float | None = None
    r2_s2: dict[str, float] = field(default_factory=dict)
    version: str | None = None
    loaded: bool = False
    error: str | None = None


def load_params(path: Path | None = None) -> Params:
    try:
        raw = json.loads(Path(path or PARAMS_PATH).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return Params(error=f"{type(exc).__name__}")
    r2 = {str(k): float(v) for k, v in (raw.get("r2_s2") or {}).items() if _finite(v)}
    return Params(z_s1=_finite(raw.get("z_s1")), z_s2=_finite(raw.get("z_s2")), r2_s2=r2,
                  version=raw.get("version"), loaded=True)


def guarded_z(z: float | None) -> float:
    """A fitted z inside Z_GUARD, else Z_DEFAULT (the pre-registered degenerate-fit guard)."""
    if z is None or not (Z_GUARD[0] <= z <= Z_GUARD[1]):
        return Z_DEFAULT
    return float(z)


def z_for(source: str, params: Params) -> float:
    if source == SIGMA_S1 and params.z_s1 is not None:
        return guarded_z(params.z_s1)
    return guarded_z(params.z_s2)


def r2_for(params: Params, kind: str, mfam: str, tts: str) -> float:
    """r^2_S2 for the cell, falling back (kind, mfam) then kind -- the fit writes all three levels."""
    for key in (f"{kind}|{mfam}|{tts}", f"{kind}|{mfam}", kind):
        if key in params.r2_s2:
            return params.r2_s2[key]
    return max(params.r2_s2.values(), default=0.0)


def sigma_s3(params: Params) -> float:
    return 2.0 * math.sqrt(max(params.r2_s2.values(), default=0.0))


# --------------------------------------------------------------------------- math


def _finite(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def logit(p: float) -> float:
    p = min(1.0 - P_CLIP, max(P_CLIP, p))
    return math.log(p / (1.0 - p))


def sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x)) if x >= 0 else math.exp(x) / (1.0 + math.exp(x))


def equal_pool(books: Sequence[Sequence[float]]) -> list[float]:
    """The equal-weight normalised log pool of per-book outcome vectors (`syndicate_fair.log_pool`, pi = 1/n)."""
    k = len(books[0])
    logs = [sum(math.log(max(P_CLIP, b[o])) for b in books) / len(books) for o in range(k)]
    top = max(logs)
    weights = [math.exp(v - top) for v in logs]
    total = sum(weights)
    return [w / total for w in weights]


def dispersion_var(books: Sequence[Sequence[float]], j: int) -> float:
    """D^2 * sum pi^2 for outcome j with equal weights: the pooled logit's variance IF the books were independent
    (`syndicate_fair.dispersion_var`). They are not, which is what the fitted r^2 adds back."""
    n = len(books)
    pool_logit = logit(equal_pool(books)[j])
    d2 = sum((logit(b[j]) - pool_logit) ** 2 for b in books) / n
    return d2 / n


def kelly_lb(p_lb: float, cost: float) -> float:
    return max(0.0, (p_lb - cost) / (1.0 - cost)) if 0.0 < cost < 1.0 else 0.0


def baker_mchale(p: float, cost: float, sigma: float) -> float:
    """lambda = D^2 / (D^2 + s_p^2): the Kelly shrink for an estimated edge D with standard error s_p.

    Baker & McHale (2013): when the bet fraction is computed from an ESTIMATED probability, the scaling that
    maximises expected log growth is about edge^2 / (edge^2 + var). s_p is sigma mapped to the probability scale
    by the delta method, s_p = sigma * p * (1 - p)."""
    edge = p - cost
    if edge <= 0:
        return 0.0
    s_p = sigma * p * (1.0 - p)
    return edge * edge / (edge * edge + s_p * s_p)


# --------------------------------------------------------------------------- one candidate


@dataclass
class Candidate:
    """One record side at one venue, with every number the policy and the gate read."""

    line_key: str = ""
    venue: str = ""
    sport: str = ""
    event_id: str = ""
    kind: str = ""
    market: str = ""
    segment: str = ""
    player: str | None = None
    side: str = ""
    line: float | None = None
    commence_time: str | None = None
    home_team: str | None = None
    away_team: str | None = None
    axis: str = ""
    decided_at: str | None = None
    seconds_to_start: float | None = None
    p: float | None = None
    sigma: float | None = None
    sigma_source: str | None = None
    sigma_detail: str | None = None
    z: float | None = None
    p_lb: float | None = None
    price_prob: float | None = None
    fee: float | None = None
    fee_is_bound: bool | None = None
    cost: float | None = None
    ev_net_pct: float | None = None
    ev_lb_pct: float | None = None
    kelly_lb: float | None = None
    bm_lambda: float | None = None
    fraction: float | None = None
    board_suggested: bool | None = None
    board_ev_pct: float | None = None
    in_band: bool | None = None
    failed_gates: list[str] = field(default_factory=list)

    @property
    def eligible(self) -> bool:
        return not self.failed_gates


def _epoch(value: Any) -> float | None:
    from datetime import datetime, timezone

    try:
        d = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.timestamp()


def axis_of(rec: Any) -> str:
    """The executor's own game axis (`event_concentration.axis_key`, `#711` R1)."""
    from syndicate.features.shared.event_concentration import axis_key

    ident = rec.identity
    return axis_key({"sport": ident.sport, "event_id": ident.event_id, "market": ident.market,
                     "segment": ident.segment, "player_name": ident.player, "side": ident.side})


def _gate(rec: Any, dest: str, name: str) -> bool | None:
    return next((g.passed for g in rec.gates if g.destination == dest and g.name == name), None)


def evaluate(rec: Any, venue: str, decided_at: str, sigma_info: tuple[float | None, str | None, str | None],
             params: Params) -> Candidate | None:
    """The candidate for `rec` (an expanded `decision_record.DecisionRecord`) at `venue`, or None when the record
    carries no price there. `sigma_info` = (sigma, source, detail) from the caller, which owns the I/O."""
    quote = next((q for q in rec.prices if q.role == "venue" and q.book == venue), None)
    if quote is None or quote.price_prob is None:
        return None
    ident = rec.identity
    cand = Candidate(line_key=rec.key or ident.line_key, venue=venue, sport=ident.sport, event_id=ident.event_id,
                     kind=ident.kind, market=ident.market, segment=ident.segment, player=ident.player,
                     side=ident.side, line=ident.line, commence_time=ident.commence_time,
                     home_team=ident.home_team, away_team=ident.away_team, decided_at=decided_at,
                     price_prob=quote.price_prob, fee=quote.fee_per_contract, fee_is_bound=quote.fee_is_bound,
                     board_suggested=rec.board_suggested, board_ev_pct=rec.board_ev_pct)
    try:
        cand.axis = axis_of(rec)
    except Exception:  # noqa: BLE001 -- no axis is a failed gate, never a guessed group
        cand.axis = ""
    failed = cand.failed_gates
    # G1 pregame + G2 the decision window
    start, now = _epoch(ident.commence_time), _epoch(decided_at)
    if start is None or now is None:
        failed.append("no_commence_time")
    else:
        cand.seconds_to_start = round(start - now, 1)
        if start <= now or str(ident.game_state or "").lower() in _LIVE_STATES:
            failed.append("not_pregame")
        elif start - now > DECISION_WINDOW_S:
            failed.append("outside_decision_window")
    # G3 + G4 the market fair
    cand.p = rec.market.p_market
    if cand.p is None or not (0.0 < cand.p < 1.0):
        failed.append("no_market_fair")
    if rec.market.two_sided is not True:
        failed.append("one_sided_fair")
    if rec.market.suspect_stale is True:
        failed.append("stale_quote")
    # G5 + G6 the record's own venue gates
    dest = f"live:{venue}"
    if _gate(rec, dest, "plausible_price") is not True:
        failed.append("implausible_venue_price")
    contract = next((c for c in rec.contracts if c.venue == venue), None)
    if contract is not None and contract.identity == "wrong_date":
        failed.append("wrong_date_contract")
    # G7 the cost
    if cand.fee is None:
        failed.append("fee_unknown")
    else:
        cand.cost = cand.price_prob + cand.fee
        if not (0.0 < cand.cost < 1.0):
            failed.append("cost_out_of_range")
    if not cand.axis:
        failed.append("no_axis")
    cand.in_band = PRICE_BAND[0] - 1e-9 <= cand.price_prob < PRICE_BAND[1] - 1e-9
    # The numbers, wherever they can be computed (an ineligible row still reports them).
    if cand.p is not None and 0.0 < cand.p < 1.0 and cand.cost is not None and 0.0 < cand.cost < 1.0:
        cand.ev_net_pct = round((cand.p / cand.cost - 1.0) * 100.0, 4)
        sigma, source, detail = sigma_info
        cand.sigma, cand.sigma_source, cand.sigma_detail = sigma, source, detail
        if sigma is None:
            failed.append("no_sigma")
        else:
            cand.z = z_for(source or SIGMA_S2, params)
            cand.p_lb = round(sigmoid(logit(cand.p) - cand.z * sigma), 6)
            cand.ev_lb_pct = round((cand.p_lb / cand.cost - 1.0) * 100.0, 4)
            cand.kelly_lb = round(kelly_lb(cand.p_lb, cand.cost), 6)
            cand.bm_lambda = round(baker_mchale(cand.p, cand.cost, sigma), 6)
            cand.fraction = round(min(MAX_BET_FRACTION, cand.kelly_lb * cand.bm_lambda), 6)
    return cand


# --------------------------------------------------------------------------- strategies


def qualifies(strategy: str, cand: Candidate) -> bool:
    if not cand.eligible:
        return False
    if strategy == STRATEGY_EV_LB:
        return cand.ev_lb_pct is not None and cand.ev_lb_pct > 0.0
    if strategy == STRATEGY_NET_FLOOR:
        floor = NET_FLOOR_PCT.get(cand.venue)
        return floor is not None and cand.ev_net_pct is not None and cand.ev_net_pct >= floor
    if strategy == STRATEGY_SUGGESTED:
        return cand.board_suggested is True
    raise ValueError(f"unknown strategy {strategy!r}")


def rank_key(strategy: str, cand: Candidate) -> tuple:
    """Larger is better. Ties fall to the cheaper cost, then the line key, so a build's choice is deterministic."""
    if strategy == STRATEGY_EV_LB:
        primary = cand.ev_lb_pct
    elif strategy == STRATEGY_NET_FLOOR:
        primary = cand.ev_net_pct
    else:
        primary = cand.board_ev_pct
    return (primary if primary is not None else float("-inf"), -(cand.cost or 1.0), cand.line_key, cand.venue)


def group_key(cand: Candidate) -> tuple[str, str]:
    """ONE bet per (event, game axis) per strategy, across both venues (`#711` R1: a ladder is one position)."""
    return (cand.event_id, cand.axis)


def select(strategy: str, candidates: Iterable[Candidate]) -> dict[tuple[str, str], Candidate]:
    """Within one build: the best qualifying candidate per (event, axis)."""
    best: dict[tuple[str, str], Candidate] = {}
    for cand in candidates:
        if not qualifies(strategy, cand):
            continue
        key = group_key(cand)
        if key not in best or rank_key(strategy, cand) > rank_key(strategy, best[key]):
            best[key] = cand
    return best


def stake_units(cand: Candidate, game_used_fraction: float) -> tuple[float, float]:
    """(stake units, fraction) after the per-game cap: the room left on the event, possibly 0."""
    room = max(0.0, MAX_GAME_FRACTION - game_used_fraction)
    fraction = min(cand.fraction or 0.0, room)
    return round(fraction * BANKROLL_UNITS, 2), round(fraction, 6)
