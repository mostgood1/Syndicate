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
BUCKET_PREGAME = "pre"
BUCKET_OVERTIME = "ot"

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
        line=_f(g("identity.line")), player=g("identity.player"), clock_bucket=BUCKET_PREGAME,
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
    reader = reader or Reader()
    off = experts_off(env)
    out: list[ExpertOpinion] = []
    for rec in records:
        for fn in PREGAME_EXPERTS.values():
            out.append(fn(rec, t, reader, off))
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
            for home, away in ((row.get("home_name"), row.get("away_name")), (row.get("home"), row.get("away"))):
                key = (team_key(home), team_key(away))
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
    join_p = _f(g("model_home_win_prob"))
    op.inputs = {"join_model_p": join_p, "join_point_estimator": g("point_estimator"),
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


LIVE_EXPERTS: dict[str, Callable[..., ExpertOpinion]] = {"live_resim": live_resim_expert}


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
              floor: float = 0.01, min_opined: int = 20) -> dict[str, Any]:
    """`model_engine_standard.md` §1 for the experts, for ONE sport's run.

    CONSUMED: every input path an expert read during THIS run (`Reader.consumed`), never a name list.
    POPULATED: the share of that source's real rows where the path is non-null.
    CONSUMED + populated below `floor` and not documented in `expected_sparse` (as `expert:source:path`, or
    `sport:expert:source:path` for a gap one sport has by design) is the alarm.

    Also, over `dataclasses.fields(ExpertOpinion)`: an output field that sits at its default on EVERY opined
    opinion of an expert is an alarm unless documented as `expert:out:field` (sigma None on `sim` is one). Checked
    only once an expert has `min_opined` opinions: "always at default" over one line is not evidence of anything
    (11-10: one WNCAAB moneyline tripped it)."""
    expected_sparse = dict(EXPECTED_SPARSE if expected_sparse is None else expected_sparse)
    alarms: list[dict[str, Any]] = []
    inputs: list[dict[str, Any]] = []
    probe = Reader()
    for expert, paths in sorted(reader.consumed.items()):
        for qualified in sorted(paths):
            source, path = qualified.split(":", 1)
            rows = sources.get(source) or []
            populated = sum(1 for r in rows if probe.get("_", source, r, path) is not None)
            share = (populated / len(rows)) if rows else None
            entry = {"sport": sport, "expert": expert, "input": qualified, "rows": len(rows),
                     "populated_share": None if share is None else round(share, 4)}
            documented = expected_sparse.get(f"{expert}:{qualified}") or expected_sparse.get(f"{sport}:{expert}:{qualified}")
            if documented:
                entry["documented_sparse"] = documented
            inputs.append(entry)
            if rows and share is not None and share < floor and not documented:
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
    "under_tilt:decision_record:identity.game_state": "set by the board only once a game's state is known",
    "live_resim:out:player": "the live join prices game lines only",
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
}
