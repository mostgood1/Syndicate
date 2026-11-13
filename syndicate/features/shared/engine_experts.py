"""Engine experts: every source proposes a shift on the log-odds scale, with its own sigma (Phase 1B M1).

Plan: `docs/ai_context/plan_one_engine_pregame_live.md` §2 ("Experts") and §3 (M1). Contract and pipeline trace:
`docs/ai_context/engine_experts.md`. Lane `engine-experts`, umbrella `#736`.

ONE CONTRACT. An expert looks at one line at one instant and returns an `ExpertOpinion`:

    delta_logit = logit(p_expert) - logit(p_prior)        the shift it proposes against the market prior
    sigma                                                  its own uncertainty on that shift, logit scale
    sigma_basis                                            what the sigma measures (and "unrecorded" when nothing can)
    phase, clock_bucket                                    pregame, or live and how far into the game
    inputs                                                 the scalars it read, so the opinion is auditable
    refusal                                                a NAME when it cannot opine; never a silent neutral 0

A refused opinion carries `delta_logit = None`, never 0.0: a neutral default is indistinguishable from a working
expert that agrees with the market (`model_engine_standard.md` §0), and the M2 learner must be able to tell them apart.

SHADOW. Nothing in placement, sizing, the board or the portfolio reads this module; `tests/test_engine_experts.py`
pins that it imports no order or board module, and `tests/test_decision_record.py` lists it as a paper-only reader.
The experts are PURE functions of logged evidence (the DecisionRecord, the live evidence log, the live gameline
ledger), so any past night can be re-run; no worker calls them.

THE THREE EXPERTS IN SLICE 1.
- `sim` (pregame): the sim's calibrated probability against the record's market prior. The record carries no sim
  count, so sigma is `None` with basis `unrecorded:no_sims_in_record` -- a named gap, not a guess. A model
  probability within `ANCHOR_TOL` of the prior is refused as `model_anchored_to_prior`: on 11-10 that was every NBA
  and NCAAB pregame spread, whose margin distribution is anchored on the market spread.
- `under_tilt` (pregame): the SUPPORTED prop under-bias (`matchup_signals.likelihood_adjustments`, NBA 1.23 pp,
  NCAAF 2.38 pp) applied to the record's market prior. Sigma is the measured residual's own uncertainty: the larger
  of its binomial standard error and half the gap between the two windows it was measured on.
- `live_resim` (live): the live re-sim's distribution at the instant the live join priced a line, against the
  join's de-vigged market probability for that line (`live_gameline_ledger`). The probability is two-way (push
  sims excluded, like the de-vigged price it is compared with) and Agresti-Coull smoothed, as the join smooths;
  sigma is the Monte Carlo error of that estimate on the logit scale.

SLICE 3 (lane `live-stat-progress-expert`, 2026-11-13).
- `stat_progress` (live): a player's banked actual plus the re-sim's rest-of-game draws, i.e. the published live
  P(over) of one player prop at one logged tick (`live_prop_evidence`), against the live BOOK prior at that instant,
  rebuilt from `book_quotes` with the board's own de-vig rules (`prop_prior`). Agresti-Coull at n = simsRun, MC sigma,
  as `live_resim`. Rows at a ladder line no book quoted are counted, not opined (`stat_progress_opinions`).

SLICE 4 (lane `live-segment-expert`, 2026-11-13).
- `live_segment` (live): an unsettled segment (college h1 / h2) totals or spreads line some book was quoting at a
  logged re-sim tick, priced from the tick's segment histogram exactly as the live join would price it (its estimator,
  its away-frame line; the join itself refuses college segments, #763), against the in-play book prior rebuilt from
  `book_quotes` (`prop_prior`). Enumerated from the evidence log's ticks (`live_segment_opinions`), because the
  ledger keeps one row per segment line per day.

Every expert reads its inputs through `Reader`, which records the paths it actually touched, so the input
checklist (`scripts/engine_experts.py checklist`) compares CONSUMED (observed at run time, never a name grep)
against POPULATED (measured on real rows).
"""

from __future__ import annotations

import math
import os
import re
from dataclasses import MISSING, asdict, dataclass, field, fields
from datetime import datetime, timezone
from typing import Any, Callable, Iterable, Mapping, Sequence

CONTRACT_VERSION = "engine_expert/1"
OFF_ENV = "SYNDICATE_ENGINE_EXPERTS_OFF"  # comma list of expert names to switch off; absent = all on

PHASE_PREGAME = "pregame"
PHASE_LIVE = "live"

_P_CLIP = (0.001, 0.999)

# Regulation clock per sport: (periods, seconds per period). The live lanes' `clockSeconds` is the time REMAINING in
# the period (fleet evidence log, 2026-11-09: NBA 720 -> 0 within a quarter, NCAAB 1200, WNCAAB 600, NFL 900, NHL
# 1200). A period past the last is overtime.
SPORT_CLOCK: dict[str, tuple[int, int]] = {
    "nba": (4, 720),
    "wnba": (4, 600),
    "ncaab": (2, 1200),
    "wncaab": (4, 600),
    "nfl": (4, 900),
    "ncaaf": (4, 900),
    "nhl": (3, 1200),
    "soccer": (2, 2700),
}

# Plan §2: the live clock buckets are shares of the game elapsed. 95-100 and overtime are kept apart rather than
# folded into 75-95, so the learner can see the end of a game on its own.
CLOCK_BUCKETS: tuple[tuple[float, float, str], ...] = (
    (0.00, 0.25, "0-25"),
    (0.25, 0.50, "25-50"),
    (0.50, 0.75, "50-75"),
    (0.75, 0.95, "75-95"),
    (0.95, 1.0000001, "95-100"),
)
BUCKET_PREGAME = "pre"  # pregame, start time unknown
BUCKET_OVERTIME = "ot"

# The pregame analogue of the clock bucket: hours to the start at the record's instant (slice 2). Syndicate Fair v1
# splits its families by time to start the same way (`tts`); the learner's pregame cells need the axis.
PREGAME_BUCKETS: tuple[tuple[float, str], ...] = ((1.0, "pre<1h"), (6.0, "pre1-6h"), (24.0, "pre6-24h"))
PREGAME_BUCKET_FAR = "pre>24h"

# The live join's markets. The `_alt` ladders are priced the same way as the main line.
_TOTALS = frozenset({"totals", "totals_alt"})
_SPREADS = frozenset({"spreads", "spreads_alt"})
_H2H = frozenset({"h2h"})

# The lane-age gate the board applies to live lanes is 600 s (`#762`). An evidence row older than this at the
# instant the line was priced is not the state the price was formed against.
LIVE_EVIDENCE_MAX_AGE_S = 900.0

# A pregame "model" probability within this of the record's own prior is the prior restated, not an opinion.
# MEASURED 2026-11-10 on the fleet's 11-10 record (build 16:00:47Z): every NBA spread (744 within 1e-6 plus 12 exact,
# of 756, basis `sim_margin_dist/*`), every NCAAB spread (70 of 70) and 332 of 862 NBA totals -- the pregame margin
# distribution is anchored on the market's spread, so P(cover) at the market's line IS the market. Read as an
# opinion it would be a delta of 0 that looks exactly like a sim agreeing with the market (model_engine_standard §0).
# A Monte Carlo sim matching a de-vigged price to 1e-5 by chance is not a real case.
ANCHOR_TOL = 1e-5

# under_tilt's own uncertainty, in probability points, from the measurements that set the deltas:
#   nba.under_bias   findings_2026-10-13_nba_signals_v1.md: windows 1.01% (n 81,395) and 1.61% (n 46,262), pooled 1.23
#                    on 127,657 -> binomial SE 0.14 pp; half the window gap 0.30 pp -> 0.30 pp.
#   ncaaf.under_bias findings_2026-10-14_football_signals_v1.md: windows 2.35% (n 3,737) and 2.42% (n 3,219), pooled
#                    2.38 on 6,956 -> binomial SE 0.60 pp; half the window gap 0.035 pp -> 0.60 pp.
UNDER_TILT_SIGMA_PP: dict[str, float] = {"nba.under_bias": 0.30, "ncaaf.under_bias": 0.60}


# ----------------------------------------------------------------------------- the contract


@dataclass(slots=True)
class ExpertOpinion:
    expert: str = ""
    expert_version: str = ""
    phase: str = ""
    t: str = ""
    sport: str = ""
    event_id: str = ""
    line_key: str = ""
    market: str = ""
    segment: str = ""
    side: str = ""
    line: float | None = None
    player: str | None = None
    p_prior: float | None = None
    prior_basis: str | None = None
    prior_age_s: float | None = None
    p_expert: float | None = None
    delta_logit: float | None = None
    sigma: float | None = None
    sigma_basis: str | None = None
    clock_bucket: str | None = None
    elapsed_share: float | None = None
    inputs: dict[str, Any] = field(default_factory=dict)
    refusal: str | None = None
    v: str = CONTRACT_VERSION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def opinion_fields() -> tuple[str, ...]:
    return tuple(f.name for f in fields(ExpertOpinion))


# ----------------------------------------------------------------------------- switches and math


def experts_off(env: Mapping[str, str] | None = None) -> frozenset[str]:
    raw = str((env if env is not None else os.environ).get(OFF_ENV) or "")
    return frozenset(x.strip().lower() for x in raw.split(",") if x.strip())


def clip(p: float) -> float:
    return min(_P_CLIP[1], max(_P_CLIP[0], float(p)))


def logit(p: float) -> float:
    q = clip(p)
    return math.log(q / (1.0 - q))


def _f(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _parse(ts: Any) -> datetime | None:
    if not ts:
        return None
    text = str(ts).strip().replace("Z", "+00:00")
    try:
        out = datetime.fromisoformat(text)
    except ValueError:
        return None
    return out if out.tzinfo else out.replace(tzinfo=timezone.utc)


def agresti_coull(k: float, n: float) -> tuple[float, float]:
    """(point, standard error) of a binomial share, add-two smoothed -- the live join's estimator
    (`live_gameline_join.agresti_coull_point` / `prob_std_err`)."""
    n_adj = float(n) + 4.0
    p_adj = (float(k) + 2.0) / n_adj
    return p_adj, math.sqrt(max(0.0, p_adj * (1.0 - p_adj)) / n_adj)


def sigma_logit_from_se(p: float, se: float) -> float:
    """A probability's standard error carried to the logit scale (delta method)."""
    q = clip(p)
    return se / (q * (1.0 - q))


def elapsed_share(sport: str, state: Mapping[str, Any] | None) -> tuple[float | None, str | None]:
    """(share of regulation elapsed, clock bucket) from a live state. Overtime -> (None, "ot")."""
    spec = SPORT_CLOCK.get(str(sport or "").lower())
    if not spec or not isinstance(state, Mapping):
        return None, None
    period = _f(state.get("period"))
    clock = _f(state.get("clockSeconds"))
    if period is None or clock is None or period < 1:
        return None, None
    periods, length = spec
    if period > periods:
        return None, BUCKET_OVERTIME
    clock = min(max(clock, 0.0), float(length))
    share = ((period - 1.0) * length + (length - clock)) / float(periods * length)
    for lo, hi, name in CLOCK_BUCKETS:
        if lo <= share < hi:
            return round(share, 4), name
    return round(share, 4), CLOCK_BUCKETS[-1][2]


def pregame_bucket(commence_time: Any, t: Any) -> str:
    """Hours from the record's instant `t` to the start. Unknown either side -> "pre"."""
    start, at = _parse(commence_time), _parse(t)
    if start is None or at is None:
        return BUCKET_PREGAME
    hours = (start - at).total_seconds() / 3600.0
    for limit, name in PREGAME_BUCKETS:
        if hours < limit:
            return name
    return PREGAME_BUCKET_FAR


def two_way_share(dist: Mapping[str, Any], line: float, *, over: bool = True) -> tuple[int, int, int]:
    """(k, n_two_way, n_push) for P(value > line) in a histogram {value: count}, push sims excluded from n.

    Over a margin histogram with `line` the AWAY-frame spread, `k` counts the sims where home covers: the live
    join's frame (`live_gameline_join.price_distribution_market`: home covers when margin > L, no negation)."""
    above = below = push = 0
    for key, count in dist.items():
        value, c = _f(key), _f(count)
        if value is None or c is None or c <= 0:
            continue
        if value > line:
            above += int(c)
        elif value < line:
            below += int(c)
        else:
            push += int(c)
    k = above if over else below
    return k, above + below, push


# ----------------------------------------------------------------------------- input tracing


class Reader:
    """Reads dotted paths from mappings or dataclasses and remembers which paths an expert touched, so the input
    checklist sees what is CONSUMED at run time instead of guessing it from names."""

    def __init__(self) -> None:
        self.consumed: dict[str, set[str]] = {}

    def get(self, expert: str, source: str, obj: Any, path: str) -> Any:
        self.consumed.setdefault(expert, set()).add(f"{source}:{path}")
        cur = obj
        for part in path.split("."):
            if cur is None:
                return None
            if isinstance(cur, Mapping):
                cur = cur.get(part)
            else:
                cur = getattr(cur, part, None)
        return cur


def _opinion(expert: str, version: str, phase: str, **kw: Any) -> ExpertOpinion:
    return ExpertOpinion(expert=expert, expert_version=version, phase=phase, **kw)


def _finish(op: ExpertOpinion, p_expert: float | None, sigma: float | None, sigma_basis: str | None) -> ExpertOpinion:
    if op.refusal:
        return op
    if p_expert is None or op.p_prior is None:
        op.refusal = op.refusal or "no_probability"
        return op
    op.p_expert = round(clip(p_expert), 6)
    op.delta_logit = round(logit(p_expert) - logit(op.p_prior), 6)
    op.sigma = None if sigma is None else round(float(sigma), 6)
    op.sigma_basis = sigma_basis
    return op


# ----------------------------------------------------------------------------- pregame experts (DecisionRecord)

_PREGAME_STATES = frozenset({"", "pre", "pregame", "scheduled", "upcoming", "not_started", "none"})


def _record_head(expert: str, version: str, rec: Any, t: str, reader: Reader) -> ExpertOpinion:
    g = lambda path: reader.get(expert, "decision_record", rec, path)  # noqa: E731
    op = _opinion(
        expert, version, PHASE_PREGAME, t=t,
        sport=str(g("identity.sport") or ""), event_id=str(g("identity.event_id") or ""),
        line_key=str(g("identity.line_key") or ""), market=str(g("identity.market") or ""),
        segment=str(g("identity.segment") or ""), side=str(g("identity.side") or ""),
        line=_f(g("identity.line")), player=g("identity.player"),
        clock_bucket=pregame_bucket(g("identity.commence_time"), t),
    )
    state = str(g("identity.game_state") or "").strip().lower()
    if state not in _PREGAME_STATES:
        op.refusal = "game_not_pregame"
    p_prior = _f(g("market.p_market"))
    op.p_prior = None if p_prior is None else round(p_prior, 6)
    op.prior_basis = f"decision_record.market:{g('market.fair_method') or 'unknown'}"
    op.prior_age_s = _f(g("market.book_age_seconds"))
    if p_prior is None and not op.refusal:
        op.refusal = "no_prior"
    return op


def sim_expert(rec: Any, t: str, reader: Reader, off: frozenset[str] = frozenset()) -> ExpertOpinion:
    name, version = "sim", "sim/1"
    op = _record_head(name, version, rec, t, reader)
    if name in off:
        op.refusal = "expert_off"
        return op
    p_model = _f(reader.get(name, "decision_record", rec, "model.p_model"))
    op.inputs = {
        "source_field": reader.get(name, "decision_record", rec, "model.source_field"),
        "engine": reader.get(name, "decision_record", rec, "model.engine"),
        "basis": reader.get(name, "decision_record", rec, "model.basis"),
        "skill_status": reader.get(name, "decision_record", rec, "model.skill_status"),
        "calibration_cell": reader.get(name, "decision_record", rec, "model.calibration_cell"),
    }
    if p_model is None and not op.refusal:
        op.refusal = "no_model_probability"
    if not op.refusal and op.p_prior is not None and abs(p_model - op.p_prior) < ANCHOR_TOL:
        op.refusal = "model_anchored_to_prior"
    return _finish(op, p_model, None, "unrecorded:no_sims_in_record")


def under_tilt_expert(rec: Any, t: str, reader: Reader, off: frozenset[str] = frozenset()) -> ExpertOpinion:
    from syndicate.features.shared.matchup_signals import likelihood_adjustments

    name, version = "under_tilt", "under_tilt/1"
    op = _record_head(name, version, rec, t, reader)
    if name in off:
        op.refusal = "expert_off"
        return op
    row = {
        "sport": reader.get(name, "decision_record", rec, "identity.sport"),
        "kind": reader.get(name, "decision_record", rec, "identity.kind"),
        "market": reader.get(name, "decision_record", rec, "identity.market"),
        "side": reader.get(name, "decision_record", rec, "identity.side"),
    }
    adjustments = likelihood_adjustments(row)
    if not adjustments:
        op.refusal = op.refusal or "signal_not_applicable"
        return op
    adj = adjustments[0]
    delta_pp = float(adj["delta"])
    op.inputs = {"signal": adj["signal"], "delta_pp": round(delta_pp * 100.0, 4)}
    if op.refusal or op.p_prior is None:
        return op
    p_expert = clip(op.p_prior + delta_pp)
    sigma_pp = UNDER_TILT_SIGMA_PP.get(str(adj["signal"]))
    sigma = None if sigma_pp is None else sigma_logit_from_se(op.p_prior, sigma_pp / 100.0)
    return _finish(op, p_expert, sigma, "measured_residual:max(binomial_se,half_window_gap)")


PREGAME_EXPERTS: dict[str, Callable[..., ExpertOpinion]] = {"sim": sim_expert, "under_tilt": under_tilt_expert}


def pregame_opinions(records: Iterable[Any], t: str, reader: Reader | None = None,
                     env: Mapping[str, str] | None = None) -> list[ExpertOpinion]:
    """Every pregame expert on records that share one instant (a single build's record file)."""
    return pregame_opinions_at(((rec, t, "build") for rec in records), reader, env)


def pregame_opinions_at(items: Iterable[tuple[Any, str, str]], reader: Reader | None = None,
                        env: Mapping[str, str] | None = None) -> list[ExpertOpinion]:
    """Every pregame expert on (record, its own instant, snapshot) -- the kept pregame lines, where each line's
    `first` and `last` records were written by different builds (`decision_record.keep_pregame_lines`)."""
    reader = reader or Reader()
    off = experts_off(env)
    out: list[ExpertOpinion] = []
    for rec, t, snapshot in items:
        for fn in PREGAME_EXPERTS.values():
            op = fn(rec, t, reader, off)
            op.inputs["snapshot"] = snapshot
            out.append(op)
    return out


# ----------------------------------------------------------------------------- live expert (evidence log + ledger)

_NAME_RE = re.compile(r"[^a-z0-9]+")


def team_key(name: Any) -> str:
    return _NAME_RE.sub(" ", str(name or "").lower()).strip()


class EvidenceIndex:
    """The live evidence log's fresh rows for one sport, by (home, away) team key, in instant order."""

    def __init__(self, rows: Iterable[Mapping[str, Any]]) -> None:
        self.by_game: dict[tuple[str, str], list[tuple[datetime, Mapping[str, Any]]]] = {}
        for row in rows:
            if row.get("refusal") is not None or row.get("carried"):
                continue
            t = _parse(row.get("t"))
            if t is None:
                continue
            # ONCE PER DISTINCT KEY (lane college-segment-grade, 2026-11-13). NCAAB's evidence rows carry `home` /
            # `away` that reduce to the same key as the names, and a row filed under both landed TWICE in one series:
            # on the fleet's NCAAB 11-09..11-12, 3,529-6,029 duplicate instants a night, so `live_segment_opinions`
            # (which walks every tick) wrote every NCAAB segment opinion twice. `lookup` was unaffected.
            keys = {(team_key(home), team_key(away))
                    for home, away in ((row.get("home_name"), row.get("away_name")), (row.get("home"), row.get("away")))}
            for key in sorted(keys):
                if key[0] and key[1]:
                    self.by_game.setdefault(key, []).append((t, row))
        for series in self.by_game.values():
            series.sort(key=lambda item: item[0])

    def lookup(self, home: Any, away: Any, at: datetime, state_as_of: datetime | None
               ) -> tuple[Mapping[str, Any] | None, str]:
        """The evidence the line was priced against: the latest row at or before `at` whose lane state is the one
        the join recorded (`same_state`), else the latest row at or before `at` (`as_of_instant`)."""
        series = self.by_game.get((team_key(home), team_key(away)))
        if not series:
            return None, "no_game_match"
        latest = exact = None
        for t, row in series:
            if t > at:
                break
            latest = row
            if state_as_of is not None and _parse(row.get("as_of")) == state_as_of:
                exact = row
        if exact is not None:
            return exact, "same_state"
        if latest is None:
            return None, "no_evidence_before_instant"
        return latest, "as_of_instant"


def is_ledger_refusal_row(row: Mapping[str, Any]) -> bool:
    """The live gameline ledger's REFUSED half (`live_gameline_ledger.build_records`, the second loop): identity, a
    `withheld_reason`, at most the join's observed numbers, and no lane state. Those rows never write the
    `live_state_as_of` key the priced rows always write (null or not)."""
    return "live_state_as_of" not in row


def live_resim_expert(ledger_row: Mapping[str, Any], index: EvidenceIndex, reader: Reader,
                      off: frozenset[str] = frozenset()) -> ExpertOpinion:
    name, version = "live_resim", "live_resim/1"
    if is_ledger_refusal_row(ledger_row):
        op = _opinion(name, version, PHASE_LIVE, t=str(ledger_row.get("recorded_at") or ""),
                      sport=str(ledger_row.get("sport") or "").lower(), event_id=str(ledger_row.get("event_id") or ""),
                      market=str(ledger_row.get("market") or "").lower(),
                      segment=str(ledger_row.get("segment") or "full").lower(), line=_f(ledger_row.get("line")))
        op.inputs = {"withheld_reason": ledger_row.get("withheld_reason")}
        op.refusal = "ledger_refusal_row"
        return op
    g = lambda path: reader.get(name, "live_gameline_ledger", ledger_row, path)  # noqa: E731
    sport = str(g("sport") or "").lower()
    market = str(g("market") or "").lower()
    segment = str(g("segment") or "full").lower() or "full"
    line = _f(g("line"))
    side = "home" if market in _SPREADS or market in _H2H else "over"
    t = str(g("recorded_at") or "")
    op = _opinion(name, version, PHASE_LIVE, t=t, sport=sport, event_id=str(g("event_id") or ""), market=market,
                  segment=segment, side=side, line=line,
                  line_key="|".join([sport, str(g("event_id") or ""), market, segment, "", side,
                                     "" if line is None else f"{line:g}"]))
    p_prior = _f(g("market_fair_prob"))
    op.p_prior = None if p_prior is None else round(p_prior, 6)
    op.prior_basis = "live_gameline_ledger.market_fair_prob"
    op.prior_age_s = _f(g("quote_age_seconds"))
    # THE ENGINE'S NUMBER, NOT #780's TEMPERED ONE. A ledger v7 record on a full-game total (NBA k 2.16, NCAAF 2.48;
    # `live_gameline_join.totals_prob_scale`) or, from 2026-11-13 (`273a4a599`), a full-game spread (NBA 2.02, NCAAF
    # 1.80, NCAAB 1.34; `spreads_prob_scale`) carries the TEMPERED probability in `model_home_win_prob` and the
    # engine's own in `model_home_win_prob_unscaled`, which the join sets only where `prob_scale` != 1. This expert
    # reads the histogram the engine priced, so `join_model_p` (the join check's input) is the engine's number wherever
    # the record says it was tempered; a tempered record without it carries None and is not checked.
    join_p = _f(g("model_home_win_prob"))
    prob_scale = _f(g("prob_scale"))
    if prob_scale is not None and prob_scale != 1.0:
        join_p = _f(g("model_home_win_prob_unscaled"))
    op.inputs = {"join_model_p": join_p, "join_prob_scale": prob_scale, "join_point_estimator": g("point_estimator"),
                 "join_sims": g("sims_run"), "join_priceable": g("priceable")}
    if name in off:
        op.refusal = "expert_off"
        return op
    if market not in _TOTALS | _SPREADS | _H2H:
        op.refusal = "unknown_market"
        return op
    at = _parse(t)
    if at is None:
        op.refusal = "no_instant"
        return op
    state_as_of = _parse(g("live_state_as_of"))
    row, match = index.lookup(g("home_team"), g("away_team"), at, state_as_of)
    op.inputs["evidence_match"] = match
    if row is None:
        op.refusal = match
        return op
    e = lambda path: reader.get(name, "live_evidence", row, path)  # noqa: E731
    ev_t = _parse(e("t"))
    age = None if ev_t is None else (at - ev_t).total_seconds()
    op.inputs.update({"evidence_t": e("t"), "evidence_age_s": None if age is None else round(age, 1),
                      "evidence_event_id": e("event_id")})
    share, bucket = elapsed_share(sport, e("state"))
    op.elapsed_share, op.clock_bucket = share, bucket
    if age is not None and age > LIVE_EVIDENCE_MAX_AGE_S:
        op.refusal = "evidence_stale"
        return op
    if p_prior is None:
        op.refusal = "no_prior"
        return op

    if segment == "full":
        block_total, block_margin = e("totalRunsDist"), e("marginDist")
        sims = _f(e("simsRun"))
        anchored = True
    else:
        segments = e("segments") or {}
        block = segments.get(segment) if isinstance(segments, Mapping) else None
        if not isinstance(block, Mapping):
            op.refusal = "segment_absent"
            return op
        if block.get("settled"):
            op.refusal = "segment_settled"
            return op
        block_total, block_margin = block.get("total_dist"), block.get("margin_dist")
        sims = _f(block.get("sims"))
        anchored = block.get("marginAnchored") is True

    if market in _H2H:
        if segment == "full":
            p_home = _f(e("modelHomeWinProb"))
            if p_home is None or sims is None or sims <= 0:
                op.refusal = "no_win_probability"
                return op
            p_adj, se = agresti_coull(p_home * sims, sims)
            op.inputs.update({"k": round(p_home * sims, 3), "n": sims})
            return _finish(op, p_adj, sigma_logit_from_se(p_adj, se), "mc_agresti_coull")
        if not anchored:
            op.refusal = "segment_margin_unanchored"
            return op
        dist, cut = block_margin, 0.0
    elif market in _TOTALS:
        dist, cut = block_total, line
    else:
        if segment != "full" and not anchored:
            op.refusal = "segment_margin_unanchored"
            return op
        dist, cut = block_margin, line
    if not isinstance(dist, Mapping) or not dist:
        op.refusal = "no_distribution"
        return op
    if cut is None:
        op.refusal = "no_line"
        return op
    k, n2, push = two_way_share(dist, cut)
    op.inputs.update({"k": k, "n": n2, "push": push})
    if n2 <= 0:
        op.refusal = "all_push"
        return op
    p_adj, se = agresti_coull(k, n2)
    return _finish(op, p_adj, sigma_logit_from_se(p_adj, se), "mc_agresti_coull")


# ----------------------------------------------------------------------------- live expert: stat progress (props)
#
# Lane `live-stat-progress-expert` (2026-11-13, user "Yes, start it"). The live re-sim publishes, per player, stat and
# line, P(over) from its rest-of-game draws given what the player has already banked (`nba/live_resim.py
# build_live_props`); `live_prop_evidence` keeps every such row per game per changed tick. This expert reads one row at
# its tick and opines against the live book prior AT THAT INSTANT, rebuilt from `book_quotes` (the append-only per-book
# change log, which carries in-play prop quotes: 168,511 in-game NBA prop rows from 11 books on 11-11).

# A book's pair is the market only while its newer side moved within this of the instant. `book_quotes` appends on a
# CHANGE, so an old row can still be the posted price; but an in-play prop that has not moved in 15 min is more likely
# suspended than standing. Same bound as the lane-state gate (`LIVE_EVIDENCE_MAX_AGE_S`); the opinion carries the age.
PROP_QUOTE_MAX_AGE_S = 900.0
# Yes/No markets are a count of stats reaching ten, so Yes is OVER the producer's fixed line
# (`nba/live_resim.DOUBLES_LINES`); the books quote them with no line (NaN).
DOUBLES_MARKET_LINES: dict[str, float] = {"player_double_double": 1.5, "player_triple_double": 2.5}
_PROP_SELECTIONS = {"over": "over", "under": "under", "yes": "over", "no": "under"}
# The quote fields the index reads, in the board's observed-time order (`odds_book_quotes._fair_value_fields`).
_QUOTE_PATHS = ("kind", "market", "selection", "line", "price", "bookmaker", "player_name", "home_team", "away_team",
                "captured_at", "book_updated_at", "snapshot_ts")


def _fold_player(name: Any) -> str:
    from syndicate.features.shared.odds_book_quotes import fold_market_identity_term

    return fold_market_identity_term("player_name", name)


class PropQuoteIndex:
    """`book_quotes` PROP rows for one sport-date, by (home, away, folded player, market) -> line -> entries in the
    order we CAPTURED them. An entry is (captured_at, observed stamp, book, side, price, raw selection). Only those
    scalars are kept, so a busy night's shard (283k prop rows on 11-11) does not sit in memory as dicts.

    Every field read goes through `reader` as source `book_quotes`, and the non-null count of each is kept, so the
    input checklist measures population on every row ingested (`populated`)."""

    def __init__(self, rows: Iterable[Mapping[str, Any]], reader: Reader | None = None,
                 expert: str = "stat_progress") -> None:
        self.by_key: dict[tuple[str, str, str, str], dict[float, list[tuple]]] = {}
        self.rows = 0
        self.non_null: dict[str, int] = {}
        reader = reader or Reader()
        for row in rows:
            got = {path: reader.get(expert, "book_quotes", row, path) for path in _QUOTE_PATHS}
            if str(got["kind"] or "") != "prop":
                continue
            self.rows += 1
            for path, value in got.items():
                if value is not None and not (isinstance(value, float) and value != value):
                    self.non_null[path] = self.non_null.get(path, 0) + 1
            market = str(got["market"] or "").lower()
            side = _PROP_SELECTIONS.get(str(got["selection"] or "").strip().lower())
            seen = _parse(got["captured_at"])
            price = _f(got["price"])
            line = DOUBLES_MARKET_LINES.get(market, _f(got["line"]))
            if side is None or seen is None or price is None or line is None:
                continue
            stamp = _parse(got["book_updated_at"]) or _parse(got["snapshot_ts"]) or seen
            key = (team_key(got["home_team"]), team_key(got["away_team"]), _fold_player(got["player_name"]), market)
            self.by_key.setdefault(key, {}).setdefault(float(line), []).append(
                (seen, stamp, str(got["bookmaker"] or "").lower(), side, int(price), str(got["selection"] or "")))
        for lines in self.by_key.values():
            for entries in lines.values():
                entries.sort(key=lambda e: e[0])

    def populated(self) -> tuple[int, dict[str, int]]:
        return self.rows, dict(self.non_null)

    def lookup(self, home: Any, away: Any, player: Any, market: Any, line: Any) -> tuple[list[tuple] | None, str]:
        name, mkt = _fold_player(player), str(market or "").lower()
        lines = self.by_key.get((team_key(home), team_key(away), name, mkt)) or \
            self.by_key.get((team_key(away), team_key(home), name, mkt))
        if lines is None:
            return None, "no_quotes_for_player_market"
        value = DOUBLES_MARKET_LINES.get(mkt, _f(line))
        entries = None if value is None else lines.get(float(value))
        if entries is None:
            return None, "line_not_quoted"
        return entries, "quoted_line"


def prop_prior(entries: Sequence[tuple], at: datetime, *,
               max_age_s: float = PROP_QUOTE_MAX_AGE_S) -> dict[str, Any]:
    """The live book prior for OVER at one line at instant `at`, from `PropQuoteIndex` entries.

    The board's own rules (`odds_book_quotes._fair_value_fields`): per (book, side) the freshest quote by observed
    stamp, among those CAPTURED by `at`; a book counts only with both sides observed within
    `_FAIR_PAIR_TOLERANCE_S` of each other; each book de-vigged within itself, median across books, renormalised
    (`opportunity_signals.consensus_fair_probability`); refused when the best prices imply a hold below
    `_IMPLAUSIBLE_HOLD_PCT` (a dead leg, not an arbitrage). One rule more, because this is in play: a book whose newer
    side is older than `max_age_s` is left out (`stale_books`)."""
    from syndicate.features.shared.odds_book_quotes import _FAIR_PAIR_TOLERANCE_S, _IMPLAUSIBLE_HOLD_PCT
    from syndicate.features.shared.opportunity_signals import (
        consensus_fair_probability, fair_probability_by_book, hold_pct, implied_probability,
    )

    freshest: dict[tuple[str, str], tuple[datetime, int]] = {}
    for seen, stamp, book, side, price, _sel in entries:
        if seen > at:
            break
        previous = freshest.get((book, side))
        if previous is None or stamp >= previous[0]:
            freshest[(book, side)] = (stamp, price)
    sides: dict[str, dict[str, tuple[datetime, int]]] = {}
    for (book, side), value in freshest.items():
        sides.setdefault(book, {})[side] = value
    usable: dict[str, dict[str, int]] = {}
    newest: datetime | None = None
    dropped = {"one_sided_books": [], "unpaired_books": [], "stale_books": []}
    for book, pair in sorted(sides.items()):
        if set(pair) != {"over", "under"}:
            dropped["one_sided_books"].append(book)
            continue
        s_over, s_under = pair["over"][0], pair["under"][0]
        if abs((s_over - s_under).total_seconds()) > _FAIR_PAIR_TOLERANCE_S:
            dropped["unpaired_books"].append(book)
            continue
        latest = max(s_over, s_under)
        if (at - latest).total_seconds() > max_age_s:
            dropped["stale_books"].append(book)
            continue
        usable[book] = {"over": pair["over"][1], "under": pair["under"][1]}
        newest = latest if newest is None else max(newest, latest)
    out: dict[str, Any] = {"p": None, "refusal": None, "books": len(usable), "book_p": {}, "age_s": None,
                           "hold_pct": None, **{k: v for k, v in dropped.items() if v}}
    if not freshest:
        out["refusal"] = "no_quote_before_instant"
        return out
    if not usable:
        out["refusal"] = ("prior_stale" if dropped["stale_books"] else
                          "prior_unpaired" if dropped["unpaired_books"] else "prior_one_sided")
        return out
    best = {side: min((p[side] for p in usable.values()), key=lambda x: implied_probability(x) or 1.0)
            for side in ("over", "under")}
    out["hold_pct"] = hold_pct([best["over"], best["under"]])
    if out["hold_pct"] is not None and out["hold_pct"] < _IMPLAUSIBLE_HOLD_PCT:
        out["refusal"] = "prior_implausible_hold"
        return out
    consensus = consensus_fair_probability(usable)
    if not consensus or "over" not in consensus:
        out["refusal"] = "prior_no_consensus"
        return out
    out["p"] = consensus["over"]
    out["book_p"] = {book: round(p["over"], 6) for book, p in sorted(fair_probability_by_book(usable).items())}
    out["age_s"] = round((at - newest).total_seconds(), 1) if newest is not None else None
    return out


def stat_progress_expert(prop: Mapping[str, Any], props_row: Mapping[str, Any], quotes: PropQuoteIndex,
                         index: EvidenceIndex, reader: Reader, off: frozenset[str] = frozenset()) -> ExpertOpinion:
    """One published `liveProps` row (`prop`) of one logged game tick (`props_row`) -> an opinion on OVER.

    p_expert: the re-sim's own P(over) given the banked actual, Agresti-Coull smoothed at n = `simsRun` (the live
    join's estimator, as `live_resim`); sigma: its Monte Carlo error on the logit scale. Prior: `prop_prior` at the
    tick's instant `t`. Clock bucket: the lane row the evidence log kept for the same game at that tick."""
    name, version = "stat_progress", "stat_progress/1"
    g = lambda path: reader.get(name, "props_log", props_row, path)  # noqa: E731
    pr = lambda path: reader.get(name, "live_props", prop, path)  # noqa: E731
    sport = str(g("sport") or "").lower()
    event_id = str(g("event_id") or "")
    t = str(g("t") or "")
    market = str(pr("prop") or "").lower()
    line = _f(pr("line"))
    player = pr("playerName")
    op = _opinion(name, version, PHASE_LIVE, t=t, sport=sport, event_id=event_id, market=market, segment="full",
                  side="over", line=line, player=None if player is None else str(player),
                  line_key="|".join([sport, event_id, market, "full", str(player or ""), "over",
                                     "" if line is None else f"{line:g}"]))
    op.prior_basis = "book_quotes:median_devig_2way"
    published = _f(pr("liveModelProbOver"))
    sims = _f(pr("simsRun"))
    op.inputs = {"actual_so_far": pr("actualSoFar"), "live_projection": pr("liveProjection"),
                 "published_p": published, "sims": sims, "team_side": pr("side"),
                 "unpriced_reason": pr("unpricedReason")}
    if name in off:
        op.refusal = "expert_off"
        return op
    at = _parse(t)
    if at is None:
        op.refusal = "no_instant"
        return op
    home, away = g("home_name"), g("away_name")
    entries, quoted = quotes.lookup(home, away, player, market, line)
    op.inputs.update({"home_name": home, "away_name": away, "quote_match": quoted})
    if entries is None:
        op.refusal = quoted
        return op
    row, match = index.lookup(home, away, at, None)
    op.inputs["evidence_match"] = match
    if row is not None:
        e = lambda path: reader.get(name, "live_evidence", row, path)  # noqa: E731
        ev_t = _parse(e("t"))
        age = None if ev_t is None else (at - ev_t).total_seconds()
        op.inputs["evidence_age_s"] = None if age is None else round(age, 1)
        if age is not None and age <= LIVE_EVIDENCE_MAX_AGE_S:
            op.elapsed_share, op.clock_bucket = elapsed_share(sport, e("state"))
    if published is None:
        op.refusal = str(pr("unpricedReason") or "no_model_probability")
        return op
    if sims is None or sims <= 0:
        op.refusal = "no_sims"
        return op
    prior = prop_prior(entries, at)
    op.inputs.update({"prior_books": prior["books"], "book_p": prior["book_p"], "prior_hold_pct": prior["hold_pct"],
                      **{k: prior[k] for k in ("one_sided_books", "unpaired_books", "stale_books") if k in prior}})
    if prior["p"] is None:
        op.refusal = prior["refusal"]
        return op
    op.p_prior = round(prior["p"], 6)
    op.prior_age_s = prior["age_s"]
    k = published * sims
    p_adj, se = agresti_coull(k, sims)
    op.inputs.update({"k": round(k, 3), "n": sims})
    return _finish(op, p_adj, sigma_logit_from_se(p_adj, se), "mc_agresti_coull")


def stat_progress_opinions(props_rows: Iterable[Mapping[str, Any]], quotes: PropQuoteIndex, index: EvidenceIndex,
                           reader: Reader | None = None, env: Mapping[str, str] | None = None,
                           keep_rows: list[Mapping[str, Any]] | None = None
                           ) -> tuple[list[ExpertOpinion], dict[str, int]]:
    """Every published prop row of every logged tick -> opinions, plus what was not a line.

    The re-sim publishes each posted line with +-3 neighbour lines (`LIVE_LINE_WINDOW`), so most rows are a ladder
    no book quotes. A row at a line no book quoted that day (`line_not_quoted`), or for a player + market no book
    quoted that day (`no_quotes_for_player_market`), is not a line: it is COUNTED in the second value and never becomes
    an opinion, so the coverage table's `lines` are lines a bettor could have taken. `keep_rows`, when given, collects
    the published rows that did become opinions (the checklist's `live_props` population)."""
    from syndicate.features.shared.live_prop_evidence import expand_props

    reader = reader or Reader()
    off = experts_off(env)
    out: list[ExpertOpinion] = []
    skipped: dict[str, int] = {}
    for props_row in props_rows:
        for prop in expand_props(props_row.get("props") or []):
            op = stat_progress_expert(prop, props_row, quotes, index, reader, off)
            if op.refusal in ("line_not_quoted", "no_quotes_for_player_market"):
                skipped[op.refusal] = skipped.get(op.refusal, 0) + 1
                continue
            out.append(op)
            if keep_rows is not None:
                keep_rows.append(prop)
    return out, skipped


def board_fair_over(entries: Sequence[tuple], at: datetime | None, books: set[str]) -> float | None:
    """P(over) by the BOARD's own fair-value function (`odds_book_quotes._fair_value_fields`) over the index entries
    captured by `at` from `books` -- the independent recomputation both prior checks compare an expert's prior with."""
    from syndicate.features.shared.odds_book_quotes import _fair_value_fields

    if at is None:
        return None
    rows = [{"bookmaker": book, "selection": side, "price": price, "book_updated_at": stamp.isoformat()}
            for seen, stamp, book, side, price, _sel in entries if seen <= at and book in books]
    best = min((r["price"] for r in rows if r["selection"] == "over"), default=None)
    fair = _fair_value_fields(rows, selection="over", price=best or 100, best_price=best or 100)
    p = fair.get("fair_probability")
    return None if p is None else float(p)


# ----------------------------------------------------------------------------- live expert: segments (halves)
#
# Lane `live-segment-expert` (2026-11-13, user "Yes, start it"). The plan ranks college live totals and second halves
# first (`plan_one_engine_pregame_live.md` §4). The live re-sim keeps, per tick, a block per segment (h1 / h2, and
# quarters where the sport has them) with the segment's own total and home-margin histograms
# (`live_evidence.segments.<seg>`: total_dist, margin_dist, sims, settled, marginAnchored). The live join REFUSES every
# college segment line (`segment_pricing_disabled`, #763) and its ledger keeps one row per line per day with no market
# price on purpose (`live_gameline_join.attach_live_gamelines`), so the ledger cannot say WHEN a segment line stood.
# This expert therefore enumerates the evidence log's ticks: at each logged tick of a game, each unsettled segment,
# and each totals / spreads line some book was quoting within `PROP_QUOTE_MAX_AGE_S`, it opines with the histogram the
# join would price (its estimator, its away-frame line) against the in-play book prior rebuilt from `book_quotes`
# with the board's own rules (`prop_prior`, as `stat_progress`).
#
# Measured on the fleet, NCAAB 11-12: in-play h1 / h2 totals and spreads quotes from 6 books; WNCAAB has segment
# blocks in the evidence log but NO segment quotes, so it gets no prior. No books quote in-play segment moneylines.

SEGMENT_MARKETS = _TOTALS | _SPREADS
_GAME_QUOTE_PATHS = ("kind", "market", "segment", "selection", "line", "price", "bookmaker", "home_team", "away_team",
                     "captured_at", "book_updated_at", "snapshot_ts")


def canonical_quote_side(market: Any, selection: Any, line: Any) -> tuple[str, float] | None:
    """One `book_quotes` game-line row -> (side, L) in the LIVE JOIN's frame, or None.

    Totals: over / under at the line. Spreads: each side carries its OWN handicap -- `selection` is "home" / "away"
    and the two lines have opposite signs (13,946 of 14,257 same-snapshot pairs on NCAAB 11-12; the rest are books
    quoting several lines at once). The join's line is the AWAY-frame one: home covers when margin > L
    (`live_gameline_join.price_distribution_market`). So home at h is ("over", -h) -- "over" meaning home covers --
    and away at a is ("under", a). Getting the sign backwards is the 2026-08-08 phantom-edge defect; the runner's
    FRAME check reads the rebuilt prior against the join's own on full-game lines to catch it."""
    mkt = str(market or "").strip().lower()
    sel = str(selection or "").strip().lower()
    value = _f(line)
    if value is None:
        return None
    if mkt in _TOTALS:
        return (sel, value) if sel in ("over", "under") else None
    if mkt in _SPREADS:
        if sel == "home":
            return "over", -value + 0.0  # + 0.0: no -0.0 key
        if sel == "away":
            return "under", value + 0.0
    return None


class GameLineQuoteIndex:
    """`book_quotes` TOTALS / SPREADS rows for one sport-date, every segment, by (home key, away key, market, segment)
    -> canonical line L -> entries in the order we CAPTURED them: (captured_at, observed stamp, book, side, price, raw
    selection), the `PropQuoteIndex` entry shape, so `prop_prior` and `board_fair_over` read both. Side "over" is
    P(over) on totals and P(home covers) on spreads (`canonical_quote_side`).

    Every field read goes through `reader` as source `book_quotes`, and the non-null count of each is kept over the
    totals / spreads rows, the population the expert reads (`populated`)."""

    def __init__(self, rows: Iterable[Mapping[str, Any]], reader: Reader | None = None,
                 expert: str = "live_segment") -> None:
        self.by_key: dict[tuple[str, str, str, str], dict[float, list[tuple]]] = {}
        self.rows = 0
        self.non_null: dict[str, int] = {}
        self.unmapped = 0
        reader = reader or Reader()
        for row in rows:
            got = {path: reader.get(expert, "book_quotes", row, path) for path in _GAME_QUOTE_PATHS}
            market = str(got["market"] or "").lower()
            if str(got["kind"] or "") == "prop" or market not in SEGMENT_MARKETS:
                continue
            self.rows += 1
            for path, value in got.items():
                if value is not None and not (isinstance(value, float) and value != value):
                    self.non_null[path] = self.non_null.get(path, 0) + 1
            mapped = canonical_quote_side(market, got["selection"], got["line"])
            seen = _parse(got["captured_at"])
            price = _f(got["price"])
            if mapped is None or seen is None or price is None:
                self.unmapped += 1
                continue
            side, line = mapped
            stamp = _parse(got["book_updated_at"]) or _parse(got["snapshot_ts"]) or seen
            segment = str(got["segment"] or "full").strip().lower() or "full"
            key = (team_key(got["home_team"]), team_key(got["away_team"]), market, segment)
            self.by_key.setdefault(key, {}).setdefault(float(line), []).append(
                (seen, stamp, str(got["bookmaker"] or "").lower(), side, int(price), str(got["selection"] or "")))
        for lines in self.by_key.values():
            for entries in lines.values():
                entries.sort(key=lambda e: e[0])

    def populated(self) -> tuple[int, dict[str, int]]:
        return self.rows, dict(self.non_null)

    def lines(self, home_key: str, away_key: str, market: str, segment: str) -> dict[float, list[tuple]]:
        return self.by_key.get((home_key, away_key, market, segment)) or {}

    def segment_games(self) -> dict[tuple[str, str], set[str]]:
        """(home key, away key) -> the non-full segments the books quoted for that game this date."""
        out: dict[tuple[str, str], set[str]] = {}
        for home, away, _market, segment in self.by_key:
            if segment != "full":
                out.setdefault((home, away), set()).add(segment)
        return out


def line_live_at(entries: Sequence[tuple], at: datetime, max_age_s: float = PROP_QUOTE_MAX_AGE_S) -> bool:
    """True when some book's quote on this line, captured by `at`, was observed within `max_age_s` of it: the line
    stood at that instant. A line no book carried then is not a line a bettor could take, so it is not an opinion."""
    for seen, stamp, *_rest in entries:
        if seen > at:
            break
        if (at - stamp).total_seconds() <= max_age_s:
            return True
    return False


def live_segment_expert(evidence_row: Mapping[str, Any], segment: str, market: str, line: float,
                        entries: Sequence[tuple], reader: Reader, off: frozenset[str] = frozenset(),
                        game_key: tuple[str, str] | None = None) -> ExpertOpinion:
    """One segment line at one logged tick -> an opinion on OVER (totals) / HOME COVERS (spreads).

    p_expert: the segment block's histogram, two-way (push sims out) and Agresti-Coull smoothed -- the join's
    estimator, as `live_resim`; sigma: its Monte Carlo error on the logit scale. Prior: `prop_prior` over the line's
    `GameLineQuoteIndex` entries at the tick's instant. A spread needs `marginAnchored` (the join's own rule)."""
    name, version = "live_segment", "live_segment/1"
    e = lambda path: reader.get(name, "live_evidence", evidence_row, path)  # noqa: E731
    sport = str(e("sport") or "").lower()
    event_id = str(e("event_id") or "")
    t = str(e("t") or "")
    market = str(market or "").lower()
    segment = str(segment or "").lower()
    side = "home" if market in _SPREADS else "over"
    op = _opinion(name, version, PHASE_LIVE, t=t, sport=sport, event_id=event_id, market=market, segment=segment,
                  side=side, line=line,
                  line_key="|".join([sport, event_id, market, segment, "", side, "" if line is None else f"{line:g}"]))
    op.prior_basis = "book_quotes:median_devig_2way"
    op.elapsed_share, op.clock_bucket = elapsed_share(sport, e("state"))
    segs = e("segments")
    block = segs.get(segment) if isinstance(segs, Mapping) else None
    # The block's fields are their own source (`segment_block`), so the checklist measures each field once over the
    # blocks read, not once per segment key (NBA's blocks carry no `marginAnchored` / `remainingFraction` at all).
    b = lambda path: reader.get(name, "segment_block", block, path)  # noqa: E731
    sims = _f(b("sims"))
    anchored = b("marginAnchored") is True
    op.inputs = {"home_key": game_key[0] if game_key else None, "away_key": game_key[1] if game_key else None,
                 "remaining_fraction": _f(b("remainingFraction")), "segment_sims": sims,
                 "margin_anchored": anchored}
    if name in off:
        op.refusal = "expert_off"
        return op
    at = _parse(t)
    if at is None:
        op.refusal = "no_instant"
        return op
    if not isinstance(block, Mapping):
        op.refusal = "segment_absent"
        return op
    if b("settled"):
        op.refusal = "segment_settled"
        return op
    if market not in SEGMENT_MARKETS:
        op.refusal = "unknown_market"
        return op
    if market in _SPREADS and not anchored:
        op.refusal = "segment_margin_unanchored"
        return op
    dist = b("total_dist") if market in _TOTALS else b("margin_dist")
    if not isinstance(dist, Mapping) or not dist:
        op.refusal = "no_distribution"
        return op
    if line is None:
        op.refusal = "no_line"
        return op
    prior = prop_prior(entries, at)
    op.inputs.update({"prior_books": prior["books"], "book_p": prior["book_p"], "prior_hold_pct": prior["hold_pct"],
                      **{k: prior[k] for k in ("one_sided_books", "unpaired_books", "stale_books") if k in prior}})
    if prior["p"] is None:
        op.refusal = prior["refusal"]
        return op
    op.p_prior = round(prior["p"], 6)
    op.prior_age_s = prior["age_s"]
    k, n2, push = two_way_share(dist, line)
    op.inputs.update({"k": k, "n": n2, "push": push})
    if n2 <= 0:
        op.refusal = "all_push"
        return op
    # THE JOIN REFUSES A SAMPLE CERTAINTY (`prop_projections._dist_prob_over`, #624): every sim on one side of the line
    # says something about the sample, not the world, and the smoothing would turn it into a number the sim did not
    # produce. Measured on NCAAB 11-12 before this rule: 442 of 21,462 half-point segment lines were 200 of 200 (or 0),
    # all of them lines the join would have refused. The live_resim expert never meets them: the ledger prices none.
    if k == 0 or k == n2:
        op.refusal = "sample_certainty"
        return op
    p_adj, se = agresti_coull(k, n2)
    return _finish(op, p_adj, sigma_logit_from_se(p_adj, se), "mc_agresti_coull")


def live_segment_opinions(index: EvidenceIndex, quotes: GameLineQuoteIndex, reader: Reader | None = None,
                          env: Mapping[str, str] | None = None, keep_rows: list[Mapping[str, Any]] | None = None,
                          keep_blocks: list[Mapping[str, Any]] | None = None
                          ) -> tuple[list[ExpertOpinion], dict[str, Any]]:
    """Every logged tick of every game the books quoted segment lines for -> one opinion per UNSETTLED segment x
    market x line that stood at that tick (`line_live_at`).

    The second value counts what was not a line: games the books quoted that no evidence game matches by team key
    (`games_unmatched`, with `games_matched`), and (tick, segment) pairs skipped because the segment had settled or the
    tick had no block for it. `keep_rows` / `keep_blocks`, when given, collect the evidence rows and the segment blocks
    that produced opinions (the checklist's `live_evidence` and `segment_block` populations)."""
    reader = reader or Reader()
    off = experts_off(env)
    out: list[ExpertOpinion] = []
    stats: dict[str, Any] = {"games_quoted": 0, "games_matched": 0, "games_unmatched": [], "ticks": 0,
                             "segment_settled": 0, "segment_not_in_tick": 0}
    for game_key, segments in sorted(quotes.segment_games().items()):
        stats["games_quoted"] += 1
        series = index.by_game.get(game_key)
        if not series:
            stats["games_unmatched"].append("|".join(game_key))
            continue
        stats["games_matched"] += 1
        for t, row in series:
            stats["ticks"] += 1
            blocks = row.get("segments") if isinstance(row.get("segments"), Mapping) else {}
            used = False
            for segment in sorted(segments):
                block = blocks.get(segment)
                if not isinstance(block, Mapping):
                    stats["segment_not_in_tick"] += 1
                    continue
                if block.get("settled"):
                    stats["segment_settled"] += 1
                    continue
                block_used = False
                for market in sorted(SEGMENT_MARKETS):
                    for line, entries in sorted(quotes.lines(game_key[0], game_key[1], market, segment).items()):
                        if not line_live_at(entries, t):
                            continue
                        out.append(live_segment_expert(row, segment, market, line, entries, reader, off, game_key))
                        used = block_used = True
                if block_used and keep_blocks is not None:
                    keep_blocks.append(block)
            if used and keep_rows is not None:
                keep_rows.append(row)
    return out, stats


def segment_join_reproduction(opinions: Sequence[ExpertOpinion], index: EvidenceIndex,
                              tol: float = 1e-6) -> dict[str, Any]:
    """The segment expert against the LIVE JOIN's own pricing function on the same histogram.

    For each opined line, the tick's segment block is handed to `live_gameline_join.price_distribution_market` (the
    function that would price this line were college segment pricing on; prob_scale 1, as the join prices segments).
    THE GATE is half-point lines, where no sim can push and the two estimators must agree to `tol`; this is what pins
    the expert's line frame and side to the join's. Whole-number lines are counted beside it, not gated: the expert
    drops push sims on purpose (the prior it is compared with is two-way)."""
    from syndicate.features.shared.live_gameline_join import price_distribution_market

    rows_at: dict[tuple[str, str, str], Mapping[str, Any]] = {}
    for key, series in index.by_game.items():
        for _t, row in series:
            rows_at[(key[0], key[1], str(row.get("t") or ""))] = row
    out: dict[str, Any] = {"checked": 0, "mismatched": 0, "examples": [],
                           "whole_number": {"checked": 0, "differ": 0}}
    for op in opinions:
        if op.expert != "live_segment" or op.p_expert is None or op.line is None:
            continue
        row = rows_at.get((str(op.inputs.get("home_key")), str(op.inputs.get("away_key")), op.t))
        block = ((row or {}).get("segments") or {}).get(op.segment) if row else None
        if not isinstance(block, Mapping):
            out["checked"] += 1
            out["mismatched"] += 1
            if len(out["examples"]) < 10:
                out["examples"].append({"line_key": op.line_key, "t": op.t, "why": "tick_not_found"})
            continue
        dist = block.get("total_dist") if op.market in _TOTALS else block.get("margin_dist")
        priced = price_distribution_market(dist=dist, line=op.line, side=op.side, market=op.market,
                                           market_prob=op.p_prior, sims=block.get("sims"), sport=op.sport,
                                           prob_scale=1.0)
        join_p = priced.get("model_prob")
        whole = float(op.line) == math.floor(float(op.line))
        bucket = out["whole_number"] if whole else out
        bucket["checked"] += 1
        bad = join_p is None or abs(float(join_p) - float(op.p_expert)) > tol
        if whole:
            bucket["differ"] += int(bad)
            continue
        if bad:
            out["mismatched"] += 1
            if len(out["examples"]) < 10:
                out["examples"].append({"line_key": op.line_key, "t": op.t, "expert": op.p_expert, "join": join_p,
                                        "join_refusal": priced.get("withheld_reason"), "k": op.inputs.get("k"),
                                        "n": op.inputs.get("n")})
    return out


def segment_prior_reproduction(opinions: Sequence[ExpertOpinion], quotes: GameLineQuoteIndex,
                               tol: float = 1e-6) -> dict[str, Any]:
    """The segment expert's prior against the board's own fair-value function (`board_fair_over`), recomputed from the
    raw index entries of the books it used. The gate: 0 mismatched."""
    out: dict[str, Any] = {"checked": 0, "mismatched": 0, "examples": []}
    for op in opinions:
        if op.expert != "live_segment" or op.p_prior is None or op.line is None:
            continue
        entries = quotes.lines(str(op.inputs.get("home_key")), str(op.inputs.get("away_key")), op.market,
                               op.segment).get(float(op.line)) or []
        p_board = board_fair_over(entries, _parse(op.t), set((op.inputs.get("book_p") or {}).keys()))
        out["checked"] += 1
        if p_board is None or abs(p_board - float(op.p_prior)) > tol:
            out["mismatched"] += 1
            if len(out["examples"]) < 10:
                out["examples"].append({"line_key": op.line_key, "t": op.t, "p_prior": op.p_prior, "board": p_board})
    return out


def segment_frame_check(ledger_rows: Iterable[Mapping[str, Any]], quotes: GameLineQuoteIndex) -> dict[str, Any]:
    """A READING, not a gate: the prior this expert would rebuild (`prop_prior` over `GameLineQuoteIndex`) against the
    live join's OWN de-vigged price (`market_fair_prob`), on the full-game totals / spreads rows the join priced, at
    the instant it priced them. The two use different rules (the join de-vigs the grid's consensus price per side; the
    expert takes the median of per-book de-vigs), so they differ by a little; what this catches is a wrong FRAME. For
    spreads it also reads the sign-flipped frame (the quotes at -L), which must be clearly worse."""
    diffs: dict[str, list[float]] = {"totals": [], "spreads": []}
    flipped: list[float] = []
    no_quotes = refused = 0
    for row in ledger_rows:
        if is_ledger_refusal_row(row) or str(row.get("segment") or "full").lower() != "full":
            continue
        market = str(row.get("market") or "").lower()
        if market not in SEGMENT_MARKETS:
            continue
        p_join, line, at = _f(row.get("market_fair_prob")), _f(row.get("line")), _parse(row.get("recorded_at"))
        if p_join is None or line is None or at is None:
            continue
        lines = quotes.lines(team_key(row.get("home_team")), team_key(row.get("away_team")), market, "full")
        entries = lines.get(float(line))
        if not entries:
            no_quotes += 1
            continue
        prior = prop_prior(entries, at)
        if prior["p"] is None:
            refused += 1
            continue
        family = "totals" if market in _TOTALS else "spreads"
        diffs[family].append(abs(prior["p"] - p_join))
        if family == "spreads" and line != 0:
            other = lines.get(-float(line) + 0.0)
            p_other = prop_prior(other, at)["p"] if other else None
            if p_other is not None:
                flipped.append(abs(p_other - p_join))

    def summary(values: list[float]) -> dict[str, Any] | None:
        if not values:
            return None
        v = sorted(values)
        return {"n": len(v), "median_pp": round(100 * v[len(v) // 2], 3),
                "p90_pp": round(100 * v[int(len(v) * 0.9)], 3),
                "within_2pp": round(sum(1 for x in v if x <= 0.02) / len(v), 4)}

    return {"totals": summary(diffs["totals"]), "spreads": summary(diffs["spreads"]),
            "spreads_sign_flipped": summary(flipped), "rows_without_quotes": no_quotes, "prior_refused": refused}


def prior_reproduction(opinions: Sequence[ExpertOpinion], quotes: PropQuoteIndex, tol: float = 1e-6) -> dict[str, Any]:
    """The stat-progress prior against the BOARD's own fair-value function, recomputed from the raw index entries.

    For each opined line: the entries captured by `t` from the books the expert used (`book_p`), handed to
    `odds_book_quotes._fair_value_fields` (`board_fair_over`) -- the function the board prices with -- must give the
    same `p_prior`. And the expert's probability must be the published P(over) smoothed at n = simsRun."""
    out: dict[str, Any] = {"checked": 0, "prior_mismatched": 0, "p_mismatched": 0, "examples": []}
    for op in opinions:
        if op.expert != "stat_progress" or op.p_prior is None or op.p_expert is None:
            continue
        entries, _ = quotes.lookup(op.inputs.get("home_name"), op.inputs.get("away_name"), op.player, op.market,
                                   op.line)
        books = set((op.inputs.get("book_p") or {}).keys())
        out["checked"] += 1
        p_board = board_fair_over(entries or [], _parse(op.t), books)
        bad_prior = p_board is None or abs(float(p_board) - float(op.p_prior)) > tol
        k, n = op.inputs.get("k"), op.inputs.get("n")
        p_adj = None if k is None or not n else agresti_coull(float(k), float(n))[0]
        bad_p = p_adj is None or abs(round(clip(p_adj), 6) - float(op.p_expert)) > tol
        out["prior_mismatched"] += int(bad_prior)
        out["p_mismatched"] += int(bad_p)
        if (bad_prior or bad_p) and len(out["examples"]) < 10:
            out["examples"].append({"line_key": op.line_key, "t": op.t, "p_prior": op.p_prior, "board": p_board,
                                    "p_expert": op.p_expert, "p_from_published": p_adj, "books": sorted(books)})
    return out


LIVE_EXPERTS: dict[str, Callable[..., ExpertOpinion]] = {"live_resim": live_resim_expert,
                                                         "stat_progress": stat_progress_expert,
                                                         "live_segment": live_segment_expert}


def live_opinions(ledger_rows: Iterable[Mapping[str, Any]], index: EvidenceIndex, reader: Reader | None = None,
                  env: Mapping[str, str] | None = None) -> list[ExpertOpinion]:
    reader = reader or Reader()
    off = experts_off(env)
    return [live_resim_expert(row, index, reader, off) for row in ledger_rows]


# ----------------------------------------------------------------------------- summaries


def coverage(opinions: Sequence[ExpertOpinion]) -> list[dict[str, Any]]:
    """One row per (sport, phase, clock bucket, expert): lines seen, opined, refusals, and the shift's size."""
    groups: dict[tuple[str, str, str, str], list[ExpertOpinion]] = {}
    for op in opinions:
        groups.setdefault((op.sport, op.phase, op.clock_bucket or "-", op.expert), []).append(op)
    out = []
    for (sport, phase, bucket, expert), ops in sorted(groups.items()):
        opined = [o for o in ops if o.delta_logit is not None]
        refusals: dict[str, int] = {}
        for o in ops:
            if o.refusal:
                refusals[o.refusal] = refusals.get(o.refusal, 0) + 1
        deltas = sorted(abs(o.delta_logit) for o in opined)
        sigmas = sorted(o.sigma for o in opined if o.sigma is not None)
        out.append({
            "sport": sport, "phase": phase, "bucket": bucket, "expert": expert, "lines": len(ops),
            "opined": len(opined), "share": round(len(opined) / len(ops), 4) if ops else None,
            "median_abs_delta": deltas[len(deltas) // 2] if deltas else None,
            "mean_delta": round(sum(o.delta_logit for o in opined) / len(opined), 4) if opined else None,
            "median_sigma": sigmas[len(sigmas) // 2] if sigmas else None,
            "refusals": dict(sorted(refusals.items(), key=lambda kv: -kv[1])),
        })
    return out


def join_reproduction(opinions: Sequence[ExpertOpinion], tol: float = 1e-6) -> dict[str, Any]:
    """The live re-sim expert against the live join's own model probability, where both read the SAME lane state.

    THE GATE is totals and spreads on HALF-POINT lines: there no sim can push, so the expert's two-way share and the
    join's unconditioned share are the same estimator and must agree to `tol`. Whole-number lines and moneylines are
    counted separately and are NOT the gate: on a whole number the expert drops push sims on purpose (the price it is
    compared with is two-way), and the moneyline compares two smoothings of the lane's own win probability."""
    out: dict[str, Any] = {"checked": 0, "mismatched": 0, "examples": [],
                           "whole_number": {"checked": 0, "differ": 0, "mean_expert_minus_join": None},
                           "h2h": {"checked": 0, "differ": 0}}
    whole_gaps: list[float] = []
    for op in opinions:
        if op.expert != "live_resim" or op.p_expert is None:
            continue
        join_p = op.inputs.get("join_model_p")
        if op.inputs.get("evidence_match") != "same_state" or join_p is None:
            continue
        gap = float(op.p_expert) - float(join_p)
        if op.market in _H2H:
            out["h2h"]["checked"] += 1
            out["h2h"]["differ"] += int(abs(gap) > tol)
            continue
        if op.line is None:
            continue
        if float(op.line) == math.floor(float(op.line)):
            out["whole_number"]["checked"] += 1
            out["whole_number"]["differ"] += int(abs(gap) > tol)
            whole_gaps.append(gap)
            continue
        out["checked"] += 1
        if abs(gap) > tol:
            out["mismatched"] += 1
            if len(out["examples"]) < 10:
                out["examples"].append({"line_key": op.line_key, "t": op.t, "expert": op.p_expert, "join": join_p,
                                        "estimator": op.inputs.get("join_point_estimator"), "k": op.inputs.get("k"),
                                        "n": op.inputs.get("n"), "push": op.inputs.get("push")})
    if whole_gaps:
        out["whole_number"]["mean_expert_minus_join"] = round(sum(whole_gaps) / len(whole_gaps), 5)
    return out


def _field_default(f: Any) -> Any:
    if f.default is not MISSING:
        return f.default
    if f.default_factory is not MISSING:
        return f.default_factory()
    return None


def checklist(opinions: Sequence[ExpertOpinion], reader: Reader, sources: Mapping[str, Sequence[Any]],
              *, sport: str = "", expected_sparse: Mapping[str, str] | None = None,
              floor: float = 0.01, min_opined: int = 20,
              populated: Mapping[str, tuple[int, Mapping[str, int]]] | None = None) -> dict[str, Any]:
    """`model_engine_standard.md` §1 for the experts, for ONE sport's run.

    CONSUMED: every input path an expert read during THIS run (`Reader.consumed`), never a name list.
    POPULATED: the share of that source's real rows where the path is non-null.
    CONSUMED + populated below `floor` and not documented in `expected_sparse` (as `expert:source:path`, or
    `sport:expert:source:path` for a gap one sport has by design) is the alarm.

    Also, over `dataclasses.fields(ExpertOpinion)`: an output field that sits at its default on EVERY opined
    opinion of an expert is an alarm unless documented as `expert:out:field` (sigma None on `sim` is one). Checked
    only once an expert has `min_opined` opinions: "always at default" over one line is not evidence of anything
    (11-10: one WNCAAB moneyline tripped it).

    `populated` gives a source's (rows, non-null count per path) measured while streaming it (`PropQuoteIndex`
    counts every prop row of a shard it does not keep as dicts); it takes the place of `sources` for that source."""
    expected_sparse = dict(EXPECTED_SPARSE if expected_sparse is None else expected_sparse)
    alarms: list[dict[str, Any]] = []
    inputs: list[dict[str, Any]] = []
    probe = Reader()
    for expert, paths in sorted(reader.consumed.items()):
        for qualified in sorted(paths):
            source, path = qualified.split(":", 1)
            if populated is not None and source in populated:
                n_rows, counts = populated[source]
                n_populated = int(counts.get(path, 0))
            else:
                rows = sources.get(source) or []
                n_rows = len(rows)
                n_populated = sum(1 for r in rows if probe.get("_", source, r, path) is not None)
            share = (n_populated / n_rows) if n_rows else None
            entry = {"sport": sport, "expert": expert, "input": qualified, "rows": n_rows,
                     "populated_share": None if share is None else round(share, 4)}
            documented = expected_sparse.get(f"{expert}:{qualified}") or expected_sparse.get(f"{sport}:{expert}:{qualified}")
            if documented:
                entry["documented_sparse"] = documented
            inputs.append(entry)
            if n_rows and share is not None and share < floor and not documented:
                alarms.append({**entry, "alarm": "CONSUMED_UNPOPULATED"})
    outputs: list[dict[str, Any]] = []
    for expert in sorted({o.expert for o in opinions}):
        opined = [o for o in opinions if o.expert == expert and o.delta_logit is not None]
        if len(opined) < max(1, min_opined):
            continue
        for f in fields(ExpertOpinion):
            if f.name in ("refusal", "inputs", "v"):
                continue
            default = _field_default(f)
            if all(getattr(o, f.name) == default for o in opined):
                documented = expected_sparse.get(f"{expert}:out:{f.name}") or \
                    expected_sparse.get(f"{sport}:{expert}:out:{f.name}")
                outputs.append({"sport": sport, "expert": expert, "field": f.name, "documented": documented})
                if not documented:
                    alarms.append({"sport": sport, "expert": expert, "field": f.name, "alarm": "OUTPUT_AT_DEFAULT"})
    return {"inputs": inputs, "outputs_at_default": outputs, "alarms": alarms, "ok": not alarms}


# Legitimately sparse, each with its reason. Anything else consumed must clear the floor.
EXPECTED_SPARSE: dict[str, str] = {
    "sim:out:sigma": "the DecisionRecord carries no sim count (model.sims is not a field), so the sim's own MC error "
                     "cannot be computed from the record; named in sigma_basis",
    "sim:out:elapsed_share": "pregame",
    "under_tilt:out:elapsed_share": "pregame",
    "sim:decision_record:identity.player": "game lines have no player",
    "under_tilt:decision_record:identity.player": "game lines have no player",
    "sim:decision_record:identity.line": "moneylines have no line",
    "under_tilt:decision_record:identity.line": "moneylines have no line",
    "sim:decision_record:model.calibration_cell": "set only where the optimizer covers the cell",
    "under_tilt:decision_record:model.calibration_cell": "set only where the optimizer covers the cell",
    "sim:decision_record:market.book_age_seconds": "absent on venue-only priors",
    "under_tilt:decision_record:market.book_age_seconds": "absent on venue-only priors",
    "sim:decision_record:identity.game_state": "set by the board only once a game's state is known",
    "under_tilt:decision_record:identity.game_state": "set by the board only once a game's state is known",    "live_resim:out:player": "the live join prices game lines only",
    "sim:out:player": "game lines carry no player; a sport whose record holds only game lines (NCAAB, 11-09) has none",
    "nhl:live_resim:out:line": "NHL live prices only the moneyline: its lanes publish no distributions",
    "nhl:live_resim:live_evidence:event_id": "NHL lanes carry no event id; the expert joins on team names",
    "nfl:live_resim:live_evidence:event_id": "NFL lanes carry no event id; the expert joins on team names",
    "nfl:live_resim:out:line": "the live join refuses every NFL totals/spreads row (no_distribution: the lane "
                               "publishes its histograms at lane level, snake_case), so only moneylines carry a prior",
    "nhl:live_resim:live_evidence:segments": "NHL lanes emit no segments",
    "nfl:live_resim:live_evidence:segments": "NFL lanes emit no segments",
    "ncaaf:live_resim:live_evidence:segments": "NCAAF lanes emit no segments",
    "nhl:live_resim:live_evidence:marginDist": "NHL lanes publish no distributions",
    "nhl:live_resim:live_evidence:totalRunsDist": "NHL lanes publish no distributions",
    "live_resim:live_gameline_ledger:point_estimator": "None on records written before 2026-09-06",
    "live_resim:live_gameline_ledger:prob_scale": "ledger v7 (#780, 2026-11-13): set only on totals and spreads rows "
                                                  "the join priced from a distribution (spreads from 273a4a599 on); "
                                                  "None on moneylines and on spreads written before it, and absent "
                                                  "from every record written before v7",
    "live_segment:out:player": "segment lines are game lines; no player",
    "nba:live_segment:segment_block:marginAnchored": "NBA's segment blocks carry no margin anchor (fleet 11-11 / "
                                                     "11-12: 0 of every block read), so its segment spreads refuse "
                                                     "segment_margin_unanchored, the join's own rule",
    "nba:live_segment:segment_block:remainingFraction": "NBA's segment blocks do not carry it; recorded in inputs "
                                                        "only, nothing branches on it",
    "live_resim:live_gameline_ledger:model_home_win_prob_unscaled": "ledger v7 (#780): set only where prob_scale != 1 "
                                                                    "(NBA / NCAAF full-game totals; NBA / NCAAF / "
                                                                    "NCAAB full-game spreads), and read only there",
}
