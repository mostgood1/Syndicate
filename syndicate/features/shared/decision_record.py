"""ONE decision record per board line, written once per build by the worker. SHADOW.

`#709` step 2 (lane `decision-record-shadow`; design in
`.syndicate/findings_2026-10-20_one_engine_audit.md` section 4). Today every surface
recomputes its own fair, price, EV, floor and size, and the audit measured what that
costs: the board suggested a side its own sim opposed on 33 of 56 rows, 12 of 13
suggested Kalshi sides were negative at Kalshi's own price, and the live stake band
reads FULL Kelly. This module computes those quantities ONCE per line, by one rule each,
and writes them beside the shortlist.

**NOTHING READS THE RECORD FOR PLACEMENT, SIZING OR THE BOARD.** It is written, and it is
compared (`decision_agreement`) against what the board, the paper books and the live
executor actually did. The disagreement counts are the gate for step 3.

The record, per line:

* identity -- the board row's own identity plus each venue's contract, date-checked
  by the board fan-in's guard (`venue_quote_fanin._quote_is_for_another_date`);
* `p_market` -- the board's consensus no-vig fair (`quote.fair_probability`);
* `p_model` -- the sim's probability for THIS side, with its measured skill and the
  daily optimizer's calibration weight w* for its cell;
* form -- the cheat sheet's last-5 / last-10 record and the market-anchored
  beta-binomial posterior (`cheat_sheets.consistency_posterior`, k provisional);
* `p_decision` -- ONE probability, anchored on `p_market`; the model and form move it
  only by their measured weight (w* where the optimizer's fit has a ci95 lower bound
  above 0, else 0), and the weights are recorded;
* prices -- best bettable book and each venue, priced by ONE formula
  `ev_net = p / (price + fee) - 1` with `venue_fees.taker_fee_per_contract`;
* gates by name, verdict per destination, and the size chain with each layer's effect.

Switch: `SYNDICATE_DECISION_RECORD=off|shadow`, absent = shadow. Shadow only WRITES a
file nobody reads; `off` is the kill switch if the write ever costs the worker.
"""

from __future__ import annotations

import gzip
import json
import os
import time
from dataclasses import MISSING, dataclass, field, fields, is_dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

RECORD_VERSION = "decision_record/1"
MODE_ENV = "SYNDICATE_DECISION_RECORD"
MODE_OFF = "off"
MODE_SHADOW = "shadow"

# THE BLEND'S DEFAULTS, used only where nothing has been measured.
#
# Model: the daily optimizer's w* is the measured weight (`daily_optimizer.fit_calibration`,
# the least-squares weight on the model's departure from the market). The model moves
# p_decision ONLY where that weight is EARNED: a fitted cell (not `insufficient`) whose w*
# ci95 LOWER bound is above 0. Everywhere else it gets NONE -- unmeasured cells included.
# Was 0.25 for unmeasured cells until 2026-10-26 (user decision D3, plan #736): the sim's
# fitted weight on 4,876 settled orders was -0.27 [-0.78, +0.18] and every venue-pooled fit
# picked beta 0, so a quarter of its departure was a weight nothing had earned.
DEFAULT_MODEL_WEIGHT = 0.0
# The optimizer verdicts whose w* is a fit (not `insufficient` games or dates).
_FITTED_W_VERDICTS = frozenset({"overconfident", "not_proven"})
# Form: no measurement of form's weight exists, and the same research says form is
# mostly already priced. Its posterior is recorded and moves nothing until measured.
DEFAULT_FORM_WEIGHT = 0.0

DESTINATION_BOARD = "board"
DESTINATION_PAPER = "paper"
LIVE_VENUES = ("kalshi", "polymarket")
DESTINATIONS = (DESTINATION_BOARD, DESTINATION_PAPER) + tuple(f"live:{v}" for v in LIVE_VENUES)

# The live entry band's reference value (user 2026-10-23, "Band: 40c-75c only"). The
# gate is EVALUATED against the configured band when `SYNDICATE_LIVE_PRICE_BAND` is set,
# else against this, and `enforced_live` says which.
REFERENCE_PRICE_BAND = (0.40, 0.75)
# Research 2026-10-23 section 3: refuse long-shot buys around 15c and below.
LONGSHOT_MAX_PROB = 0.15
# The board's Suggested floor, when its module cannot be imported.
_FALLBACK_BOARD_MIN_EV_PCT = 2.0
_ONE_SIDED_FAIR_METHODS = frozenset({"book_margin_model", "one_sided", "assumed_hold"})
_P_CLIP = (0.001, 0.999)

# How many sheet days past the board date to read form from. Form exists for props,
# which are near-dated; a wider window only costs the worker reads.
FORM_SHEET_DAYS = 2


# --------------------------------------------------------------------------- dataclasses
#
# Every field has a default, and the DEFAULT is what "not fed" looks like: the checklist
# (`scripts/decision_record_checklist.py`) walks `dataclasses.fields()` and counts how
# often each field differs from it. A field that never leaves its default is unfed.


@dataclass(slots=True)
class Identity:
    line_key: str = ""
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
    game_state: str | None = None


@dataclass(slots=True)
class VenueContract:
    venue: str = ""
    ref: str | None = None
    # ok | wrong_date | undated | no_contract
    identity: str = "no_contract"
    ref_date: str | None = None


@dataclass(slots=True)
class MarketFair:
    p_market: float | None = None
    devig_method: str | None = None
    fair_method: str | None = None
    books_quoting: int | None = None
    book_age_seconds: float | None = None
    quote_seen_age_seconds: float | None = None
    two_sided: bool | None = None
    suspect_stale: bool | None = None


@dataclass(slots=True)
class ModelView:
    p_model: float | None = None
    source_field: str | None = None
    engine: str | None = None
    basis: str | None = None
    skill_status: str | None = None
    skill_verdict: str | None = None
    skill_loses_to_market: bool | None = None
    calibration_cell: str | None = None
    w_star: float | None = None
    w_star_ci_lower: float | None = None
    w_star_ci_upper: float | None = None
    w_star_verdict: str | None = None
    w_star_games: int | None = None


@dataclass(slots=True)
class FormView:
    source: str | None = None
    games5: int | None = None
    hits5: int | None = None
    games10: int | None = None
    hits10: int | None = None
    p_posterior: float | None = None
    prior_strength: float | None = None
    provisional: bool | None = None


@dataclass(slots=True)
class Blend:
    p_decision: float | None = None
    anchor: str = "p_market"
    w_model: float = 0.0
    w_model_source: str | None = None
    w_form: float = 0.0
    w_form_source: str | None = None
    model_shift_pp: float | None = None
    form_shift_pp: float | None = None


@dataclass(slots=True)
class PriceQuote:
    book: str = ""
    role: str = ""  # best_bettable | venue
    american: float | None = None
    price_prob: float | None = None
    fee_per_contract: float | None = None
    fee_basis: str | None = None
    fee_is_bound: bool | None = None
    ev_net_pct: float | None = None
    ev_net_pct_at_market: float | None = None


@dataclass(slots=True)
class Gate:
    name: str = ""
    destination: str = ""
    passed: bool | None = None
    blocks_on_unknown: bool = True
    enforced_live: bool | None = None
    detail: str | None = None


@dataclass(slots=True)
class Verdict:
    destination: str = ""
    bet: bool = False
    reason: str | None = None
    book: str | None = None
    price_prob: float | None = None
    ev_net_pct: float | None = None
    failed_gates: list[str] = field(default_factory=list)


@dataclass(slots=True)
class SizeLayer:
    name: str = ""
    value: float | None = None
    stake_fraction_after: float | None = None
    dollars_after: float | None = None
    applied: bool = False
    live_applies: bool | None = None
    note: str | None = None


@dataclass(slots=True)
class Size:
    destination: str = ""
    kelly_full: float | None = None
    stake_fraction: float | None = None
    bankroll: float | None = None
    bankroll_source: str | None = None
    stake_dollars: float | None = None
    stake_dollars_live_equivalent: float | None = None
    binding_layer: str | None = None
    layers: list[SizeLayer] = field(default_factory=list)


@dataclass(slots=True)
class DecisionRecord:
    key: str = ""
    identity: Identity = field(default_factory=Identity)
    contracts: list[VenueContract] = field(default_factory=list)
    market: MarketFair = field(default_factory=MarketFair)
    model: ModelView = field(default_factory=ModelView)
    form: FormView = field(default_factory=FormView)
    blend: Blend = field(default_factory=Blend)
    prices: list[PriceQuote] = field(default_factory=list)
    gates: list[Gate] = field(default_factory=list)
    verdicts: list[Verdict] = field(default_factory=list)
    sizes: list[Size] = field(default_factory=list)
    board_suggested: bool | None = None
    board_ev_pct: float | None = None
    board_model_edge_pct: float | None = None


COMPONENT_CLASSES = (
    DecisionRecord, Identity, VenueContract, MarketFair, ModelView, FormView, Blend,
    PriceQuote, Gate, Verdict, Size, SizeLayer,
)


# --------------------------------------------------------------------------- small helpers


def mode() -> str:
    raw = str(os.environ.get(MODE_ENV) or "").strip().lower()
    if raw in {"off", "0", "false", "no"}:
        return MODE_OFF
    return MODE_SHADOW


def _f(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if out == out and out not in (float("inf"), float("-inf")) else None


def _r(value: float | None, digits: int = 5) -> float | None:
    return None if value is None else round(value, digits)


def american_to_prob(american: Any) -> float | None:
    a = _f(american)
    if a is None or -100 < a < 100:
        return None
    return 100.0 / (a + 100.0) if a > 0 else -a / (-a + 100.0)


def ev_net_pct(p: float | None, price_prob: float | None, fee: float | None) -> float | None:
    """THE one EV formula: `p / (price + fee) - 1`, in percent. Fee per $1 contract."""
    if p is None or price_prob is None:
        return None
    cost = price_prob + (fee or 0.0)
    if cost <= 0:
        return None
    return (p / cost - 1.0) * 100.0


def full_kelly(p: float | None, price_prob: float | None, fee: float | None) -> float | None:
    """Full Kelly on the fee-inclusive cost of one $1 contract. 0 when there is no edge."""
    if p is None or price_prob is None:
        return None
    cost = price_prob + (fee or 0.0)
    if not (0.0 < cost < 1.0):
        return None
    b = 1.0 / cost - 1.0
    return max(0.0, (p * (b + 1.0) - 1.0) / b)


def _norm_segment(value: Any) -> str:
    seg = str(value or "").strip().lower()
    return "full" if seg in {"", "full", "full_game", "game"} else seg


def _norm_line(value: Any) -> str:
    f = _f(value)
    return "" if f is None else f"{f:g}"


def line_key(obj: Mapping[str, Any]) -> str:
    """Book-free identity of one bet, shared by board rows, plan positions and orders.

    `portfolio_commit.position_key` hashes the BOOK too, so a venue-scoped position and
    its board row key differently. Agreement must ask "same line, same side?", so the
    book is left out on purpose.
    """
    player = str(obj.get("player_name") or obj.get("player") or "").strip().lower()
    return "|".join((
        str(obj.get("sport") or "").strip().lower(),
        str(obj.get("event_id") or "").strip(),
        str(obj.get("market") or "").strip().lower(),
        _norm_segment(obj.get("segment")),
        player,
        str(obj.get("side") or "").strip().lower(),
        _norm_line(obj.get("line")),
    ))


def _side_prob(p_over: Any, side: str) -> float | None:
    p = _f(p_over)
    if p is None:
        return None
    if side in ("over", "yes"):
        return p
    if side == "under":
        return 1.0 - p
    return None


def _board_min_ev_pct() -> float:
    try:
        from syndicate.features.shared.layer2_board import SUGGESTED_MIN_EV_PCT

        return float(SUGGESTED_MIN_EV_PCT)
    except Exception:  # noqa: BLE001
        return _FALLBACK_BOARD_MIN_EV_PCT


def _min_implied_book_total_pct() -> float:
    try:
        from syndicate.features.shared.venue_scope import _min_implied_book_total_pct as fn

        return float(fn())
    except Exception:  # noqa: BLE001
        return 95.0


def _live_price_band() -> tuple[tuple[float, float], bool]:
    """(band, configured). The executor's own parser, so the two cannot disagree."""
    try:
        from pipeline.execute_portfolio import live_price_band

        band = live_price_band()
    except Exception:  # noqa: BLE001
        band = None
    return (band, True) if band else (REFERENCE_PRICE_BAND, False)


def _live_net_floor(venue: str) -> float | None:
    try:
        from pipeline.portfolio_commit import live_net_floor

        value, _refusal = live_net_floor(venue)
        return value
    except Exception:  # noqa: BLE001
        return None


def _fee(book: str, price_prob: float | None, row: Mapping[str, Any], venue_ref: Any) -> tuple[float | None, str | None, bool | None]:
    if price_prob is None:
        return None, None, None
    try:
        from syndicate.features.shared.venue_fees import taker_fee_per_contract

        state = str(row.get("game_state") or row.get("market_state") or "").lower()
        fee, basis, bound = taker_fee_per_contract(
            book, price_prob, venue_ref=venue_ref, sport=row.get("sport"), market=row.get("market"),
            segment=row.get("segment"), in_play=(state in {"live", "in_progress"}) if state else None,
        )
        return float(fee), basis, bool(bound)
    except Exception as exc:  # noqa: BLE001 -- an unknown fee is recorded as unknown, never as 0
        return None, f"error:{type(exc).__name__}", None


# --------------------------------------------------------------------------- context


@dataclass(slots=True)
class RecordContext:
    """Everything a build reads besides the rows, loaded once per build."""

    selected_date: str = ""
    now: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    calibration: dict[str, dict[str, Any]] = field(default_factory=dict)
    form_index: dict[str, dict[str, Any]] = field(default_factory=dict)
    settled_sample_by_sport: dict[str, int] = field(default_factory=dict)
    paper_bankroll: float | None = None
    live_capital: dict[str, float] = field(default_factory=dict)
    board_min_ev_pct: float = _FALLBACK_BOARD_MIN_EV_PCT
    implied_book_total_pct: float = 95.0
    price_band: tuple[float, float] = REFERENCE_PRICE_BAND
    price_band_configured: bool = False
    live_net_floor: dict[str, float | None] = field(default_factory=dict)
    max_order_dollars: dict[str, float | None] = field(default_factory=dict)
    band_config: dict[str, Any] = field(default_factory=dict)
    favourite_cap: dict[str, Any] = field(default_factory=dict)


def _data_root() -> Path:
    from syndicate.features.shared.refresh_state_store import data_root

    return Path(data_root())


def load_calibration(path: Path | None = None) -> dict[str, dict[str, Any]]:
    """The daily optimizer's per-cell calibration (`w`, CI, verdict), keyed by cell."""
    try:
        from syndicate.features.shared import daily_optimizer as opt

        target = path or (_data_root() / opt.OPTIMIZER_PATH)
        payload = json.loads(Path(target).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}
    table: dict[str, dict[str, Any]] = {}
    for entry in payload.get("calibration") or []:
        if isinstance(entry, Mapping) and entry.get("cell"):
            table[str(entry["cell"])] = dict(entry)
    return table


_FORM_CACHE: dict[str, tuple[float, dict[str, dict[str, Any]]]] = {}


def _form_from_sheet(path: Path) -> dict[str, dict[str, Any]]:
    """`line_key -> form` for one sheet, cached on mtime: a sheet can be several MB."""
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return {}
    cached = _FORM_CACHE.get(str(path))
    if cached and cached[0] == mtime:
        return cached[1]
    index: dict[str, dict[str, Any]] = {}
    try:
        sheet = json.loads(path.read_text(encoding="utf-8"))
        sport = str(sheet.get("sport") or path.parent.name)
        for row in sheet.get("rows") or []:
            check = row.get("check") if isinstance(row, Mapping) else None
            if not isinstance(check, Mapping):
                continue
            key = line_key({**row, "sport": sport, "player_name": row.get("player")})
            index[key] = {
                "form5": dict(check.get("form5") or {}),
                "form10": dict(check.get("form10") or {}),
                "sheet": path.name,
            }
    except Exception:  # noqa: BLE001
        index = {}
    _FORM_CACHE[str(path)] = (mtime, index)
    return index


def load_form_index(selected_date: str, sports: Iterable[str], *, root: Path | None = None) -> dict[str, dict[str, Any]]:
    base = (root or _data_root()) / "cheatsheets"
    out: dict[str, dict[str, Any]] = {}
    try:
        start = datetime.strptime(selected_date, "%Y-%m-%d")
    except ValueError:
        return out
    for sport in sorted({str(s or "").lower() for s in sports if s}):
        for offset in range(FORM_SHEET_DAYS):
            day = (start + timedelta(days=offset)).strftime("%Y-%m-%d")
            out.update(_form_from_sheet(base / sport / f"{day}.json"))
    return out


def context_from_plans(ctx: RecordContext, plans: Mapping[str, Any]) -> None:
    """Bankrolls and per-sport settled samples, read off the plans this build wrote.

    The record does not re-derive these: the plan's own stamps are what the sizer used.
    """
    paper = plans.get(DESTINATION_PAPER)
    if isinstance(paper, Mapping):
        ctx.paper_bankroll = _f(paper.get("bankroll_units"))
        for position in paper.get("positions") or []:
            sizing = position.get("sizing") if isinstance(position, Mapping) else None
            n = _f((sizing or {}).get("settled_sample_size"))
            sport = str(position.get("sport") or "").lower()
            if n is not None and sport:
                ctx.settled_sample_by_sport[sport] = int(max(n, ctx.settled_sample_by_sport.get(sport, 0)))
    for venue in LIVE_VENUES:
        plan = plans.get(f"live:{venue}")
        if not isinstance(plan, Mapping):
            continue
        capital = None
        for position in plan.get("positions") or []:
            stamp = position.get("compounding") if isinstance(position, Mapping) else None
            if isinstance(stamp, Mapping) and stamp.get("known"):
                value = _f(stamp.get("capital"))
                if value is not None:
                    capital = max(capital or 0.0, value)
        if capital is not None:
            ctx.live_capital[venue] = capital


def load_context(selected_date: str, rows: Sequence[Mapping[str, Any]], plans: Mapping[str, Any] | None = None) -> RecordContext:
    ctx = RecordContext(selected_date=selected_date)
    ctx.calibration = load_calibration()
    ctx.form_index = load_form_index(selected_date, {r.get("sport") for r in rows if r.get("kind") == "prop"})
    ctx.board_min_ev_pct = _board_min_ev_pct()
    ctx.implied_book_total_pct = _min_implied_book_total_pct()
    ctx.price_band, ctx.price_band_configured = _live_price_band()
    for venue in LIVE_VENUES:
        ctx.live_net_floor[venue] = _live_net_floor(venue)
        try:
            from syndicate.features.shared.execution_guard import limits

            ctx.max_order_dollars[venue] = _f(limits("live", venue).get("max_order_dollars"))
        except Exception:  # noqa: BLE001
            ctx.max_order_dollars[venue] = None
    try:
        from syndicate.features.shared.live_stake_band import band_config, favourite_cap_config

        ctx.band_config = dict(band_config())
        ctx.favourite_cap = dict(favourite_cap_config())
    except Exception:  # noqa: BLE001
        pass
    context_from_plans(ctx, plans or {})
    return ctx


# --------------------------------------------------------------------------- the record


def _identity(row: Mapping[str, Any]) -> Identity:
    return Identity(
        line_key=line_key(row),
        sport=str(row.get("sport") or "").lower(),
        event_id=str(row.get("event_id") or ""),
        kind=str(row.get("kind") or ""),
        market=str(row.get("market") or ""),
        segment=_norm_segment(row.get("segment")),
        player=row.get("player_name") or None,
        side=str(row.get("side") or "").lower(),
        line=_f(row.get("line")),
        commence_time=row.get("commence_time"),
        home_team=row.get("home_team"),
        away_team=row.get("away_team"),
        game_state=row.get("game_state") or row.get("market_state"),
    )


_PRICE_SOURCE_VENUE = {"kalshi": "kalshi", "polymarket_us": "polymarket", "polymarket": "polymarket"}


def _contracts(row: Mapping[str, Any]) -> list[VenueContract]:
    """Each venue's contract as the board carries it, date-checked like the fan-in.

    The board carries ONE `venue_ref`, for the venue whose feed priced the row
    (`price_source`). A venue with no ref is `no_contract` here; the Kalshi executor
    resolves its own ticker through `kalshi_board_join`, so `no_contract` is not a
    claim that the venue cannot be bought -- the gate reads it as UNKNOWN.
    """
    out: list[VenueContract] = []
    ref_venue = _PRICE_SOURCE_VENUE.get(str(row.get("price_source") or "").lower())
    ref = row.get("venue_ref") or None
    for venue in LIVE_VENUES:
        contract = VenueContract(venue=venue)
        if ref and ref_venue == venue:
            contract.ref = str(ref)
            try:
                from types import SimpleNamespace

                from syndicate.features.shared.venue_quote_fanin import (
                    _quote_is_for_another_date,
                    _venue_ref_game_date,
                )

                quote = SimpleNamespace(
                    venue_ref=ref, source="kalshi" if venue == "kalshi" else "polymarket_us",
                    sport=row.get("sport"), venue_close_time=None,
                )
                contract.ref_date = _venue_ref_game_date(quote)
                if not contract.ref_date:
                    contract.identity = "undated"
                elif _quote_is_for_another_date(quote, row):
                    contract.identity = "wrong_date"
                else:
                    contract.identity = "ok"
            except Exception:  # noqa: BLE001
                contract.identity = "undated"
        out.append(contract)
    return out


def _market(row: Mapping[str, Any]) -> MarketFair:
    quote = row.get("quote") if isinstance(row.get("quote"), Mapping) else {}
    fair_method = quote.get("fair_method")
    return MarketFair(
        p_market=_f(quote.get("fair_probability")),
        devig_method=quote.get("fair_devig_method"),
        fair_method=fair_method,
        books_quoting=int(quote["books_quoting"]) if _f(quote.get("books_quoting")) is not None else None,
        book_age_seconds=_f(quote.get("book_age_seconds")),
        quote_seen_age_seconds=_f(quote.get("quote_seen_age_seconds")),
        two_sided=not (str(fair_method or "") in _ONE_SIDED_FAIR_METHODS or quote.get("assumed_hold_pct") is not None),
        suspect_stale=bool(quote.get("suspect_stale")) if quote.get("suspect_stale") is not None else None,
    )


def _calibration_cell(row: Mapping[str, Any], now: datetime) -> str | None:
    try:
        from syndicate.features.shared.optimizer_overlay import cell_of_row

        return cell_of_row(row, now=now)
    except Exception:  # noqa: BLE001
        return None


def _model(row: Mapping[str, Any], ctx: RecordContext) -> ModelView:
    proj = row.get("projection") if isinstance(row.get("projection"), Mapping) else {}
    side = str(row.get("side") or "").lower()
    view = ModelView()
    for name in ("model_probability_cal", "model_probability_raw"):
        if _f(row.get(name)) is not None:
            view.p_model, view.source_field = _f(row.get(name)), name
            break
    if view.p_model is None and proj:
        p = _side_prob(proj.get("model_prob_over"), side)
        if p is not None:
            view.p_model, view.source_field = p, "projection.model_prob_over"
    if view.p_model is None:
        return view
    view.engine = proj.get("source")
    view.basis = proj.get("basis")
    skill = proj.get("model_skill") if isinstance(proj.get("model_skill"), Mapping) else {}
    view.skill_status = skill.get("status")
    view.skill_verdict = skill.get("verdict")
    verdict = str(skill.get("verdict") or "").lower()
    if "loses" in verdict:
        view.skill_loses_to_market = True
    elif view.skill_status == "measured" and "beats" in verdict:
        view.skill_loses_to_market = False
    view.calibration_cell = _calibration_cell(row, ctx.now)
    entry = ctx.calibration.get(view.calibration_cell or "")
    if entry:
        view.w_star = _f(entry.get("w"))
        ci = entry.get("ci95") or []
        view.w_star_ci_lower = _f(ci[0]) if len(ci) > 1 else None
        view.w_star_ci_upper = _f(ci[1]) if len(ci) > 1 else None
        view.w_star_verdict = entry.get("verdict")
        view.w_star_games = int(entry.get("games") or 0)
    return view


def _form(row: Mapping[str, Any], p_market: float | None, ctx: RecordContext, key: str) -> FormView:
    hit = ctx.form_index.get(key)
    if not hit:
        return FormView()
    from syndicate.features.shared.cheat_sheets import K_IS_PROVISIONAL, PRIOR_STRENGTH, consistency_posterior

    f5, f10 = hit.get("form5") or {}, hit.get("form10") or {}
    games10, hits10 = int(f10.get("games") or 0), int(f10.get("hits") or 0)
    return FormView(
        source=f"cheat_sheet:{hit.get('sheet')}",
        games5=int(f5.get("games") or 0), hits5=int(f5.get("hits") or 0),
        games10=games10, hits10=hits10,
        # Re-anchored on THIS build's p_market: the sheet was built at another time.
        p_posterior=consistency_posterior(p_market, hits10, games10) if games10 else None,
        prior_strength=PRIOR_STRENGTH,
        provisional=bool(K_IS_PROVISIONAL),
    )


def _blend(market: MarketFair, model: ModelView, form: FormView) -> Blend:
    blend = Blend()
    p = market.p_market
    if p is None:
        blend.w_model_source = blend.w_form_source = "no_market_fair"
        return blend
    fitted = model.w_star is not None and model.w_star_verdict in _FITTED_W_VERDICTS
    earned = fitted and model.w_star_ci_lower is not None and model.w_star_ci_lower > 0.0
    if model.p_model is None:
        blend.w_model, blend.w_model_source = 0.0, "no_model"
    elif earned:
        blend.w_model, blend.w_model_source = min(1.0, max(0.0, float(model.w_star))), f"optimizer_w:{model.w_star_verdict}"
    elif fitted:
        # A fit whose CI reaches 0 has not shown the model adds anything: record it, weigh it 0.
        blend.w_model, blend.w_model_source = 0.0, f"optimizer_w_ci_spans_0:{model.w_star_verdict}"
    elif model.skill_loses_to_market:
        blend.w_model, blend.w_model_source = 0.0, "skill_loses_to_market"
    else:
        blend.w_model, blend.w_model_source = DEFAULT_MODEL_WEIGHT, "default_unmeasured"
    if form.p_posterior is None:
        blend.w_form, blend.w_form_source = 0.0, "no_form"
    else:
        blend.w_form, blend.w_form_source = DEFAULT_FORM_WEIGHT, "default_unmeasured"
    model_shift = blend.w_model * (model.p_model - p) if model.p_model is not None else 0.0
    form_shift = blend.w_form * (form.p_posterior - p) if form.p_posterior is not None else 0.0
    blend.model_shift_pp = round(model_shift * 100.0, 3)
    blend.form_shift_pp = round(form_shift * 100.0, 3)
    blend.p_decision = round(min(_P_CLIP[1], max(_P_CLIP[0], p + model_shift + form_shift)), 6)
    return blend


def _quote_for(book: str, role: str, american: Any, row: Mapping[str, Any], p_decision: float | None,
               p_market: float | None, venue_ref: Any) -> PriceQuote:
    prob = american_to_prob(american)
    fee, basis, bound = _fee(book, prob, row, venue_ref)
    return PriceQuote(
        book=book, role=role, american=_f(american), price_prob=_r(prob, 6), fee_per_contract=_r(fee, 6),
        fee_basis=basis, fee_is_bound=bound,
        ev_net_pct=_r(ev_net_pct(p_decision, prob, fee) if fee is not None else None, 4),
        ev_net_pct_at_market=_r(ev_net_pct(p_market, prob, fee) if fee is not None else None, 4),
    )


def _prices(row: Mapping[str, Any], blend: Blend, market: MarketFair, contracts: Sequence[VenueContract]) -> list[PriceQuote]:
    quote = row.get("quote") if isinstance(row.get("quote"), Mapping) else {}
    book_prices = quote.get("book_prices") if isinstance(quote.get("book_prices"), Mapping) else {}
    refs = {c.venue: c.ref for c in contracts}
    out = [_quote_for(str(quote.get("bookmaker") or ""), "best_bettable", quote.get("price"), row,
                      blend.p_decision, market.p_market, refs.get(str(quote.get("bookmaker") or "")))]
    for venue in LIVE_VENUES:
        if venue in book_prices:
            out.append(_quote_for(venue, "venue", book_prices.get(venue), row, blend.p_decision, market.p_market, refs.get(venue)))
    return out


def _is_live_state(identity: Identity, now: datetime) -> tuple[bool | None, str]:
    state = str(identity.game_state or "").lower()
    if state in {"live", "in_progress", "final"}:
        return True, f"game_state={state}"
    try:
        start = datetime.fromisoformat(str(identity.commence_time).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return (False, f"game_state={state}") if state == "pregame" else (None, "no commence_time")
    if start.tzinfo is None:
        return None, "naive commence_time"
    return (start <= now), f"commence={identity.commence_time}"


def _gates_for(dest: str, rec: DecisionRecord, q: PriceQuote | None, ctx: RecordContext) -> list[Gate]:
    gates: list[Gate] = []

    def add(name: str, passed: bool | None, detail: str | None = None, *, blocks_on_unknown: bool = True,
            enforced_live: bool | None = None) -> None:
        # A PASSED gate keeps no detail: the numbers behind it are on the record's prices,
        # and ~36 gates a record times ~5,000 rows is the memory this build pays for.
        gates.append(Gate(name=name, destination=dest, passed=passed, blocks_on_unknown=blocks_on_unknown,
                          enforced_live=enforced_live, detail=None if passed else detail))

    live = dest.startswith("live:")
    add("price_quoted", q is not None and q.price_prob is not None, None if q else "no price at this destination")
    add("market_fair", rec.market.p_market is not None, rec.market.fair_method)
    add("two_sided_fair", rec.market.two_sided, rec.market.fair_method)
    add("fresh_quote", None if rec.market.suspect_stale is None else not rec.market.suspect_stale,
        f"book_age_s={rec.market.book_age_seconds}", blocks_on_unknown=False)
    if q is not None and q.ev_net_pct_at_market is not None:
        implied_total = 100.0 / (1.0 + q.ev_net_pct_at_market / 100.0)
        add("plausible_price", implied_total >= ctx.implied_book_total_pct,
            f"implied_total={implied_total:.2f} floor={ctx.implied_book_total_pct}")
    else:
        add("plausible_price", None, "no fee-net EV at the market fair")
    if dest == DESTINATION_BOARD:
        floor = ctx.board_min_ev_pct
    elif dest == DESTINATION_PAPER:
        floor = 0.0
    else:
        configured = ctx.live_net_floor.get(dest.split(":", 1)[1])
        floor = configured if configured is not None else 0.0
    ev = q.ev_net_pct if q is not None else None
    add("min_ev_floor", None if ev is None else ev > floor if floor == 0.0 else ev >= floor,
        f"ev_net={ev} floor={floor}")
    if live:
        venue = dest.split(":", 1)[1]
        contract = next((c for c in rec.contracts if c.venue == venue), None)
        identity = contract.identity if contract else "no_contract"
        add("venue_contract_identity", {"ok": True, "wrong_date": False}.get(identity), identity,
            blocks_on_unknown=False, enforced_live=True)
        in_play, detail = _is_live_state(rec.identity, ctx.now)
        add("pregame", None if in_play is None else not in_play, detail, enforced_live=True)
        low, high = ctx.price_band
        prob = q.price_prob if q else None
        add("price_band", None if prob is None else (low - 1e-9 <= prob < high - 1e-9),
            f"prob={prob} band=[{low:.2f},{high:.2f})", enforced_live=ctx.price_band_configured)
        add("longshot", None if prob is None else prob > LONGSHOT_MAX_PROB, f"prob={prob} max={LONGSHOT_MAX_PROB}",
            enforced_live=False)
    return gates


def _verdict(dest: str, gates: Sequence[Gate], q: PriceQuote | None) -> Verdict:
    failed = [g.name for g in gates if g.passed is False or (g.passed is None and g.blocks_on_unknown)]
    unknown = [g.name for g in gates if g.passed is None and not g.blocks_on_unknown]
    reason = ("fails:" + ",".join(failed)) if failed else ("bet" + ("; unverified:" + ",".join(unknown) if unknown else ""))
    return Verdict(destination=dest, bet=not failed, reason=reason, book=q.book if q else None,
                   price_prob=q.price_prob if q else None, ev_net_pct=q.ev_net_pct if q else None, failed_gates=failed)


def _apply_concentration(records: Sequence[DecisionRecord]) -> None:
    """R1 within this build: one bet per game AXIS per live venue, the best net EV.

    `event_concentration.axis_key` is the executor's own axis. The HELD book is not
    read here (the record is a per-build view), so a game already held still passes.
    """
    try:
        from syndicate.features.shared.event_concentration import axis_key
    except Exception:  # noqa: BLE001
        axis_key = None
    for venue in LIVE_VENUES:
        dest = f"live:{venue}"
        best: dict[str, tuple[float, DecisionRecord]] = {}
        for rec in records:
            verdict = next((v for v in rec.verdicts if v.destination == dest), None)
            if verdict is None or not verdict.bet:
                continue
            obj = {"sport": rec.identity.sport, "event_id": rec.identity.event_id, "market": rec.identity.market,
                   "segment": rec.identity.segment, "player_name": rec.identity.player}
            try:
                axis = axis_key(obj) if axis_key else None
            except Exception:  # noqa: BLE001
                axis = None
            group = f"{rec.identity.event_id}|{axis or rec.identity.market}"
            ev = verdict.ev_net_pct if verdict.ev_net_pct is not None else float("-inf")
            if group not in best or ev > best[group][0]:
                best[group] = (ev, rec)
        winners = {id(rec) for _ev, rec in best.values()}
        for rec in records:
            verdict = next((v for v in rec.verdicts if v.destination == dest), None)
            if verdict is None:
                continue
            passed = (id(rec) in winners) if verdict.bet else None
            rec.gates.append(Gate(name="concentration", destination=dest, passed=passed,
                                  blocks_on_unknown=False, enforced_live=None,
                                  detail="R1 one bet per game axis, within this build (held book not read)"))
            if verdict.bet and not passed:
                verdict.bet = False
                verdict.failed_gates.append("concentration")
                verdict.reason = "fails:concentration"


def _size(rec: DecisionRecord, dest: str, row: Mapping[str, Any], ctx: RecordContext) -> Size:
    verdict = next(v for v in rec.verdicts if v.destination == dest)
    q = next((p for p in rec.prices if p.book == verdict.book and (p.role == "venue") == dest.startswith("live:")), None)
    size = Size(destination=dest)
    p = rec.blend.p_decision
    size.kelly_full = _r(full_kelly(p, q.price_prob if q else None, q.fee_per_contract if q else None), 6)
    if size.kelly_full is None:
        return size
    fraction = size.kelly_full
    layers = size.layers
    layers.append(SizeLayer(name="kelly_full", value=size.kelly_full, stake_fraction_after=_r(fraction, 6), applied=True,
                            live_applies=True, note=f"p_decision={p} on fee-inclusive {q.book if q else None}"))
    try:
        from syndicate.features.bankroll_manager import _kelly_multiplier, _sample_credibility

        multiplier = float(_kelly_multiplier())
    except Exception:  # noqa: BLE001
        multiplier, _sample_credibility = 0.25, None
    fraction *= multiplier
    layers.append(SizeLayer(name="kelly_multiplier", value=multiplier, stake_fraction_after=_r(fraction, 6),
                            applied=True, live_applies=True))
    n = ctx.settled_sample_by_sport.get(rec.identity.sport)
    if n is not None and _sample_credibility is not None:
        credibility = float(_sample_credibility(n))
        fraction *= credibility
        layers.append(SizeLayer(name="credibility", value=credibility, stake_fraction_after=_r(fraction, 6),
                                applied=True, live_applies=True, note=f"settled_sample={n}"))
    else:
        layers.append(SizeLayer(name="credibility", value=None, stake_fraction_after=_r(fraction, 6), applied=False,
                                live_applies=True, note="settled sample unknown (no paper plan stamp for this sport)"))
    try:
        from syndicate.features.shared.portfolio_commit import _sizing_skill_factor

        skill = float(_sizing_skill_factor(row))
    except Exception:  # noqa: BLE001
        skill = None
    if skill is not None:
        fraction *= skill
    layers.append(SizeLayer(name="skill_and_optimizer", value=skill, stake_fraction_after=_r(fraction, 6),
                            applied=skill is not None, live_applies=True, note="portfolio_commit._sizing_skill_factor"))
    size.stake_fraction = _r(fraction, 6)
    if dest == DESTINATION_PAPER:
        size.bankroll, size.bankroll_source = ctx.paper_bankroll, "paper_plan.bankroll_units"
    else:
        venue = dest.split(":", 1)[1]
        size.bankroll = ctx.live_capital.get(venue)
        size.bankroll_source = "live_plan.compounding.capital" if size.bankroll is not None else None
    if size.bankroll is None:
        size.binding_layer = "bankroll_unknown"
        return size
    dollars = round(fraction * size.bankroll, 2)
    layers.append(SizeLayer(name="compounding_bankroll", value=size.bankroll, stake_fraction_after=size.stake_fraction,
                            dollars_after=dollars, applied=True, live_applies=dest.startswith("live:"),
                            note=size.bankroll_source))
    binding = "kelly"
    live_dollars = dollars
    if dest.startswith("live:"):
        venue = dest.split(":", 1)[1]
        cfg = ctx.band_config or {}
        small = cfg.get("small_edge_fraction")
        if cfg.get("on") and not (small is not None and fraction < float(small)):
            from syndicate.features.shared.live_stake_band import band_stake, favourite_cap_verdict

            band = band_stake(size.kelly_full, cfg)
            # THE BAND READS FULL KELLY (audit section 3, rank 3). Recorded as what live
            # does; NOT applied to the record's own stake, which stays applied Kelly.
            layers.append(SizeLayer(name="stake_band", value=band, dollars_after=band, applied=False, live_applies=True,
                                    note=f"band_stake(full_kelly={size.kelly_full}) in [{cfg.get('min_dollars')},{cfg.get('max_dollars')}]"))
            verdict_cap, capped = favourite_cap_verdict({"price": q.american if q else None}, band, ctx.favourite_cap or {})
            if verdict_cap != "band":
                layers.append(SizeLayer(name="favourite_cap", value=capped, dollars_after=capped, applied=False,
                                        live_applies=True, note=verdict_cap))
            live_dollars = capped
        cap = ctx.max_order_dollars.get(venue)
        if cap is not None:
            if dollars > cap:
                dollars, binding = round(cap, 2), "order_cap"
            live_dollars = min(live_dollars, cap)
            layers.append(SizeLayer(name="order_cap", value=cap, dollars_after=dollars, applied=True, live_applies=True))
    size.stake_dollars = dollars
    size.stake_dollars_live_equivalent = round(live_dollars, 2) if dest.startswith("live:") else dollars
    size.binding_layer = binding
    return size


def build_record(row: Mapping[str, Any], ctx: RecordContext) -> DecisionRecord:
    identity = _identity(row)
    rec = DecisionRecord(key=identity.line_key, identity=identity)
    rec.contracts = _contracts(row)
    rec.market = _market(row)
    rec.model = _model(row, ctx)
    rec.form = _form(row, rec.market.p_market, ctx, identity.line_key)
    rec.blend = _blend(rec.market, rec.model, rec.form)
    rec.prices = _prices(row, rec.blend, rec.market, rec.contracts)
    rec.board_suggested = bool(row.get("suggested")) if row.get("suggested") is not None else None
    rec.board_ev_pct = _f(row.get("ev_pct"))
    rec.board_model_edge_pct = _f(row.get("model_edge_pct"))
    best = next((p for p in rec.prices if p.role == "best_bettable"), None)
    for dest in DESTINATIONS:
        if dest.startswith("live:"):
            q = next((p for p in rec.prices if p.role == "venue" and p.book == dest.split(":", 1)[1]), None)
        else:
            q = best
        gates = _gates_for(dest, rec, q, ctx)
        rec.gates.extend(gates)
        rec.verdicts.append(_verdict(dest, gates, q))
    return rec


def build_records(rows: Sequence[Mapping[str, Any]], ctx: RecordContext) -> list[DecisionRecord]:
    records: list[DecisionRecord] = []
    by_key: dict[int, Mapping[str, Any]] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        rec = build_record(row, ctx)
        records.append(rec)
        by_key[id(rec)] = row
    _apply_concentration(records)
    order = {dest: index for index, dest in enumerate(DESTINATIONS)}
    for rec in records:
        # Grouped by destination (stable), the order the on-disk form stores them in.
        rec.gates.sort(key=lambda g: order.get(g.destination, len(order)))
        for verdict in rec.verdicts:
            if verdict.bet and verdict.destination != DESTINATION_BOARD:
                rec.sizes.append(_size(rec, verdict.destination, by_key[id(rec)], ctx))
    return records


# --------------------------------------------------------------------------- storage


def records_dir(root: Path | None = None) -> Path:
    return (root or _data_root()) / "reports" / "intelligence" / "decision_records"


def records_path(selected_date: str, root: Path | None = None) -> Path:
    return records_dir(root) / f"{selected_date}.json.gz"


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".tmp{os.getpid()}")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


_DEFAULTS: dict[type, dict[str, Any]] = {}


def _defaults_of(cls: type) -> dict[str, Any]:
    if cls not in _DEFAULTS:
        _DEFAULTS[cls] = {f.name: f.default for f in fields(cls) if f.default is not MISSING}
    return _DEFAULTS[cls]


def _compact(obj: Any) -> Any:
    """A dataclass as a dict WITHOUT the fields still at their default.

    The on-disk form. Measured on the 2026-10-23 board (2,000 rows), the plain
    `asdict` form was 15.8 MB a build; a field left out reads back as its default
    (`expand_record`), which is exactly what the checklist compares against.
    Gates are grouped by destination for the same reason.
    """
    if is_dataclass(obj):
        defaults = _defaults_of(type(obj))
        out: dict[str, Any] = {}
        for f in fields(obj):
            value = getattr(obj, f.name)
            if f.name == "gates" and isinstance(obj, DecisionRecord):
                grouped: dict[str, list[Any]] = {}
                for gate in value:
                    item = _compact(gate)
                    item.pop("destination", None)
                    grouped.setdefault(gate.destination, []).append(item)
                if grouped:
                    out["gates"] = grouped
                continue
            if f.name in defaults and value == defaults[f.name]:
                continue
            if isinstance(value, list) and not value:
                continue
            out[f.name] = _compact(value)
        return out
    if isinstance(obj, list):
        return [_compact(v) for v in obj]
    return obj


_NESTED = {"identity": Identity, "market": MarketFair, "model": ModelView, "form": FormView, "blend": Blend}
_LISTS = {"contracts": VenueContract, "prices": PriceQuote, "verdicts": Verdict, "sizes": Size}


def _build(cls: type, data: Mapping[str, Any]) -> Any:
    names = {f.name for f in fields(cls)}
    return cls(**{k: v for k, v in data.items() if k in names})


def expand_record(data: Mapping[str, Any]) -> DecisionRecord:
    """The on-disk form back into dataclasses, defaults restored."""
    rec = _build(DecisionRecord, {k: v for k, v in data.items() if k not in _NESTED and k not in _LISTS and k != "gates"})
    for name, cls in _NESTED.items():
        setattr(rec, name, _build(cls, data.get(name) or {}))
    for name, cls in _LISTS.items():
        items = []
        for item in data.get(name) or []:
            built = _build(cls, item)
            if cls is Size:
                built.layers = [_build(SizeLayer, layer) for layer in item.get("layers") or []]
            items.append(built)
        setattr(rec, name, items)
    rec.gates = [_build(Gate, {**gate, "destination": dest})
                 for dest, gates in (data.get("gates") or {}).items() for gate in gates]
    return rec


def write_records(selected_date: str, records: Sequence[DecisionRecord], *, build_id: str,
                  root: Path | None = None, extra: Mapping[str, Any] | None = None) -> Path:
    """The LATEST build's records for a date, overwritten atomically, gzip JSON.

    Disk, not keyvalue: nothing on web serves it, and a per-build set this size has no
    business in the store. STREAMED one record at a time so the worker never holds the
    whole serialised document (it is the memory-constrained service).
    """
    header = {
        "version": RECORD_VERSION,
        "selected_date": selected_date,
        "build_id": build_id,
        "written_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "records_count": len(records),
        "encoding": "defaults_omitted; gates grouped by destination; decode with decision_record.expand_record",
        **dict(extra or {}),
    }
    path = records_path(selected_date, root)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".tmp{os.getpid()}")
    with gzip.open(tmp, "wt", encoding="utf-8", compresslevel=6) as fh:
        head = json.dumps(header, separators=(",", ":"), default=str)
        fh.write(head[:-1] + ',"records":[')
        for index, rec in enumerate(records):
            if index:
                fh.write(",")
            fh.write(json.dumps(_compact(rec), separators=(",", ":"), default=str))
        fh.write("]}")
    os.replace(tmp, path)
    return path


def read_records(selected_date: str, root: Path | None = None) -> dict[str, Any] | None:
    return read_records_file(records_path(selected_date, root))


def read_records_file(path: Path | str) -> dict[str, Any] | None:
    try:
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:  # noqa: BLE001
        return None


# --------------------------------------------------------------------------- the worker hook


def _read_plans(selected_date: str) -> dict[str, Any]:
    """The plans THIS build just wrote, through their own readers. Read-only."""
    plans: dict[str, Any] = {}
    try:
        from pipeline import portfolio_commit as pc

        plans[DESTINATION_PAPER] = pc.read_portfolio_plan(selected_date)
        for venue in LIVE_VENUES:
            plans[f"live:{venue}"] = pc.read_live_portfolio_plan_for_venue(selected_date, venue)
            plans[f"paper:{venue}"] = pc.read_portfolio_plan_for_venue(selected_date, venue)
    except Exception as exc:  # noqa: BLE001
        print(f"[decision_record] PLANS_UNREADABLE error={type(exc).__name__}: {exc}", flush=True)
    return plans


def run_shadow(selected_date: str, shortlist: Mapping[str, Any] | None, *, root: Path | None = None,
               plans: Mapping[str, Any] | None = None, live_orders: Sequence[Mapping[str, Any]] | None = None) -> dict[str, Any]:
    """Build, write and compare. Never raises into the build; returns a summary.

    Called by `pipeline/intelligence_state.py` right after the portfolio commit, so the
    plans it compares against were derived from the same shortlist in the same tick.
    """
    started = time.time()
    if mode() == MODE_OFF:
        return {"status": "off"}
    if not selected_date or not isinstance(shortlist, Mapping) or shortlist.get("error"):
        return {"status": "no_shortlist"}
    rows = [r for r in (shortlist.get("rows") or []) if isinstance(r, Mapping)]
    if not rows:
        return {"status": "no_rows"}
    if plans is None:
        plans = _read_plans(selected_date)
    ctx = load_context(selected_date, rows, plans)
    if root is not None:
        ctx.calibration = ctx.calibration or load_calibration(root / "reports" / "model_scorecard" / "model_scorecard_optimizer.json")
        ctx.form_index = ctx.form_index or load_form_index(selected_date, {r.get("sport") for r in rows}, root=root)
    records = build_records(rows, ctx)
    build_id = f"{shortlist.get('written_at') or ''}|{int(started)}"
    bets = {d: sum(1 for r in records for v in r.verdicts if v.destination == d and v.bet) for d in DESTINATIONS}
    path = write_records(selected_date, records, build_id=build_id, root=root, extra={
        "shortlist_written_at": shortlist.get("written_at"),
        "context": {
            "price_band": list(ctx.price_band), "price_band_configured": ctx.price_band_configured,
            "live_net_floor": ctx.live_net_floor, "max_order_dollars": ctx.max_order_dollars,
            "band_on": bool((ctx.band_config or {}).get("on")), "paper_bankroll": ctx.paper_bankroll,
            "live_capital": ctx.live_capital, "calibration_cells": len(ctx.calibration),
            "form_lines": len(ctx.form_index),
        },
        "bets": bets,
    })
    summary: dict[str, Any] = {"status": "ok", "records": len(records), "bets": bets, "path": str(path)}
    try:
        from syndicate.features.shared.decision_agreement import record_build_agreement

        if live_orders is None:
            live_orders = _live_orders(selected_date)
        summary["agreement"] = record_build_agreement(
            selected_date, records, rows, plans, live_orders, build_id=build_id, root=root)
    except Exception as exc:  # noqa: BLE001
        print(f"[decision_record] DECISION_AGREEMENT_FAILED error={type(exc).__name__}: {exc}", flush=True)
    print(
        f"[decision_record] DECISION_RECORD_WRITTEN date={selected_date} mode={mode()} records={len(records)} "
        f"bets={bets} form_lines={len(ctx.form_index)} calibration_cells={len(ctx.calibration)} "
        f"path={path} elapsed_s={round(time.time() - started, 2)}",
        flush=True,
    )
    return summary


def _live_orders(selected_date: str) -> list[dict[str, Any]]:
    """LIVE orders on this slate from the execution ledger. Read-only.

    `_load()` is the operational document (the archive holds trimmed rows, and was
    measured 2026-10-23 to hold paper only); read, never written back.
    """
    try:
        from syndicate.features.shared.execution_ledger import _load

        orders = list((_load() or {}).get("orders") or [])
    except Exception as exc:  # noqa: BLE001
        print(f"[decision_record] LEDGER_UNREADABLE error={type(exc).__name__}: {exc}", flush=True)
        return []
    return [dict(o) for o in orders if isinstance(o, Mapping)
            and str(o.get("mode") or "").lower() == "live" and str(o.get("selected_date") or "") == selected_date]
