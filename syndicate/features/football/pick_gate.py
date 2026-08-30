"""Which football markets have EARNED the right to be served as picks.

A projection is not a bet. A bet claims the model prices something better than
the market does, and that claim is measurable: score the model against realised
outcomes on the same games the market priced, and compare. Until that comparison
has been made AND won, serving a pick means selling an edge the model has not
demonstrated.

MEASURED 2026-08-19, NCAAF margins, and this is why the gate exists:

    2023 SP+ ratings -> 2024 games, all 15 weeks, 100 seeds/game, produced by
    the PRODUCTION generator and graded from the pick ledger.
    CLEAN AND OUT-OF-SAMPLE -- graded_leak_status {'clean': 2236}, no warning.

        vs CLOSE  n=2233  model MAE 15.775  market 12.212  +3.563  t=+17.20
        vs OPEN   n=2148  model MAE 15.684  market 12.355  +3.329  t=+16.23

    The model is worse than the closing line by 3.6 points of margin MAE at
    17 sigma, and loses to Bovada, DraftKings and ESPN Bet independently. It
    loses to the OPENING line by nearly as much, so there is no softer target
    behind the close -- this is an accuracy problem, not a timing one. It
    replicates on 2025 (+3.419, leaked) and is slightly WORSE clean, the
    direction leakage predicts. Every scale from 6 to 24 loses, so this is a
    property of the MODEL, not of a tuning constant.

DEFAULT IS DENY, AND THAT IS THE WHOLE POINT.
A gate that maps "never measured" onto its permissive branch is not a gate, it
is a formality that fires only for failures someone already bothered to look
for. Serving requires a recorded WIN. An absent measurement is indistinguishable
from an unmeasured loss, so both suppress.

WHAT THIS DELIBERATELY DOES NOT DO:

  * It does NOT stop projections being generated, published, or displayed. The
    board still shows what the model thinks. Generation must continue or the
    measurement that LIFTS the gate can never be taken -- a gate that blinds its
    own exit criterion never opens.
  * It does NOT touch the archive or evaluation paths. Those are records of what
    happened; suppressing there would rewrite history and destroy the evidence
    base the gate is waiting on.
  * It is NOT silent. notice_for() gives every caller the reason and the
    numbers. An empty picks page with no explanation reads as an outage, and
    someone will "fix" it by removing the gate.

  * **It does NOT govern an edge the model had no part in.** Added 2026-08-29,
    and the omission was costing the whole board. Every verdict above is about
    the MODEL's claim, but the registry was keyed on `(sport, market)` alone --
    so it also denied a claim that was never measured here and needs no model:
    *this book's price is better than the market's own consensus.* Measured on
    production the same day, NCAAF served 45 grid rows in which 90 of 90 sides
    carried a computed `edge_vs_consensus_pct` and 45 of 45 rows showed no edge
    at all, because both the board and the sizing path read only the model
    field. A gate is entitled to deny what it measured; denying a different
    claim by sharing a key with it is an accident, not a policy.

    The registry is therefore keyed on `(sport, market, BASIS)`. Model basis is
    unchanged in every value and still default-deny. Market basis is governed by
    `shared/market_basis_edge.py`, which owns its own four guards and is where
    the reasoning for them lives -- **including that it is a price-shopping
    delta against a VIGGED consensus and is not expected value.** Nothing here
    relaxes anything: a market-basis row still has to clear that module, and an
    unknown basis still lands on DENY.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from syndicate.features.shared.market_basis_edge import BASIS as MARKET_BASIS
from syndicate.features.shared.market_basis_edge import MIN_BOOKS_TO_SERVE
from syndicate.features.shared.market_basis_edge import MIN_EDGE_PCT_TO_SERVE
from syndicate.features.shared.market_basis_edge import MODEL_BASIS
from syndicate.features.shared.market_keys import canonical_market_key


@dataclass(frozen=True)
class MarketVerdict:
    """One (sport, market) serving decision and the evidence behind it."""

    servable: bool
    reason: str
    measured_on: str | None = None
    model_metric: float | None = None
    market_metric: float | None = None
    metric_name: str = "MAE"
    sample_size: int | None = None
    detail: str = ""

    def summary(self) -> str:
        if self.model_metric is None or self.market_metric is None:
            return self.reason
        return (
            f"{self.reason} (model {self.metric_name} {self.model_metric:.3f} vs "
            f"market {self.market_metric:.3f}, n={self.sample_size}, "
            f"measured {self.measured_on})"
        )


# Markets a model claim is priced against. Anything not listed is denied by
# default -- see the module docstring.
_SERVING_REGISTRY: dict[tuple[str, str, str], MarketVerdict] = {
    ("ncaaf", "spread", MODEL_BASIS): MarketVerdict(
        servable=False,
        reason="NCAAF margin model loses to the closing line",
        measured_on="2026-08-19",
        model_metric=15.775,
        market_metric=12.212,
        sample_size=2233,
        detail=(
            "Paired dMAE +3.563, SE 0.207, t=+17.20. CLEAN AND OUT-OF-SAMPLE: "
            "2023 SP+ ratings on 2024 games, all 15 weeks, generated by the "
            "PRODUCTION generator (--ratings-season), graded from the pick "
            "ledger with graded_leak_status {'clean': 2236} and no leak "
            "warning. Loses to Bovada (+3.578), DraftKings (+3.560) and ESPN "
            "Bet (+3.549) INDEPENDENTLY, so it is not an artefact of one sharp "
            "book. Replicates the 2025 season (+3.419) and is slightly WORSE "
            "there once hindsight is removed, which is the direction leakage "
            "predicts. Every scale 6..24 loses, so retuning SP_RATING_SCALE "
            "cannot lift this."
        ),
    ),
    ("ncaaf", "moneyline", MODEL_BASIS): MarketVerdict(
        servable=False,
        reason="NCAAF moneyline is the same margin distribution, priced differently",
        measured_on="2026-08-19",
        model_metric=15.775,
        market_metric=12.212,
        sample_size=2233,
        detail=(
            "Win probability is derived from the margin distribution this "
            "measurement condemns. Suppressing spread while leaving moneyline "
            "open would let the identical unearned edge through under another "
            "label, which is a loophole, not a narrower scope."
        ),
    ),
    ("ncaaf", "total", MODEL_BASIS): MarketVerdict(
        servable=False,
        reason="NCAAF totals are over-dispersed and were never scored against the close",
        measured_on="2026-08-19",
        detail=(
            "Model total SD 5.77 vs market 3.46 = 1.67x. Over-dispersion "
            "MANUFACTURES edges: an inflated spread of projected totals crosses "
            "more lines by further, so it reads as conviction. Carrier is the "
            "drive-loop scoring rate (20.8 -> 53.9 percent against a real "
            "35-45). No model-vs-market accuracy measurement exists for totals "
            "at all, so default-deny applies on its own terms."
        ),
    ),
}


#: `market_keys`' canonical game-line vocabulary -> this registry's spelling.
#: Held as a MAPPING FROM the authority rather than as a private list, and the
#: test `test_pick_gate_market_folding_covers_market_keys` derives one from the
#: other. `learnings.md` 2026-08-23 FORBIDS a module holding its own list of
#: market names -- "hold BOTH spellings AND a test that derives one set from the
#: other; a private list with no such test is a silent time bomb". This is that
#: shape: the fallback below still exists because the registry's own words
#: ("spread"/"moneyline"/"total") are not `market_keys`' words ("spreads"/"h2h"/
#: "totals"), and a rename on either side must not silently open the gate.
_CANONICAL_TO_REGISTRY: dict[str, str] = {
    "h2h": "moneyline",
    "spreads": "spread",
    "totals": "total",
}


def _normalise_market(market: Any, sport: Any = None) -> str:
    """Fold the market spellings that reach this code onto registry keys.

    The same market arrives as 'SPREAD', 'spread', 'moneyline_home' and
    'game bet' depending on which surface built the row, so a bare equality
    check would silently pass most of them straight through the gate.

    `canonical_market_key` FIRST when a sport is in hand -- it is the one
    authority for market names (`#224`) and it resolves spellings this function
    never knew about. Its answer is then folded onto the registry's own
    vocabulary. The hand-rolled rules below remain as the no-sport fallback and
    as the branch for spellings the authority returns None for; they are second,
    not first, so a market the authority knows can no longer be classified here
    by accident.
    """
    text = str(market or "").strip().lower()
    if not text:
        return ""
    if sport is not None:
        canonical = canonical_market_key(sport, text)
        folded = _CANONICAL_TO_REGISTRY.get(str(canonical or "").strip().lower())
        if folded:
            return folded
    if text.startswith("moneyline") or text in {"ml", "h2h"}:
        return "moneyline"
    if text.startswith("spread") or text in {"ats", "handicap", "run_line", "puck_line"}:
        return "spread"
    if text.startswith("total") or text in {"ou", "over_under", "overunder"}:
        return "total"
    return text


#: The market-basis verdict. Not in `_SERVING_REGISTRY` because it is not a
#: per-(sport, market) measurement and pretending otherwise would invite someone
#: to "measure" it per market and find nothing to measure -- the claim is
#: arithmetic over live prices, identical in every sport, and its conditions are
#: per-ROW rather than per-market. `market_basis_edge` enforces those per row;
#: this verdict only says the BASIS is allowed to reach a picks surface at all.
_MARKET_BASIS_VERDICT = MarketVerdict(
    servable=True,
    reason="best available price against the market's own multi-book consensus",
    measured_on="2026-08-29",
    detail=(
        "A PRICE-SHOPPING delta, NOT expected value: the anchor is "
        "`consensus_vigged_price` and nothing de-vigs it. It asserts only that "
        "one book is quoting a better number than the others on the same market "
        "at the same moment, which uses no model and is unaffected by the model "
        "measurements above. Price shopping is measured at +2.79 ROI pts "
        "platform-wide and +2.95 pts on the NFL prop grade, both on controlled "
        f"identical bets. Per-row conditions are owned by "
        f"`shared/market_basis_edge.py` and are NOT relaxed here: at least "
        f"{MIN_BOOKS_TO_SERVE} fresh books, a pregame market, no stale side, and "
        f"at least {MIN_EDGE_PCT_TO_SERVE:.2f} pts against consensus. On the "
        "2026-09-05 NCAAF pregame slate those leave 3 of 552 sides, and on "
        "2026-09-06 they leave zero -- a short or empty list is the correct "
        "output, not a threshold to tune."
    ),
)


def market_verdict(sport: str, market: str, *, basis: str = MODEL_BASIS) -> MarketVerdict:
    """The serving decision for one (sport, market, basis). Unknown -> DENY.

    `basis` defaults to MODEL so every existing caller keeps the verdict it had
    before the dimension existed. That default is deliberate and is the safe
    direction: a caller that has not been taught about bases asks the same
    question it always asked and gets the same answer.
    """
    resolved_basis = str(basis or "").strip().lower() or MODEL_BASIS
    if resolved_basis == MARKET_BASIS:
        return _MARKET_BASIS_VERDICT
    key = (
        str(sport or "").strip().lower(),
        _normalise_market(market, sport),
        resolved_basis,
    )
    known = _SERVING_REGISTRY.get(key)
    if known is not None:
        return known
    if resolved_basis != MODEL_BASIS:
        # An unrecognised basis is the most dangerous input here: it is not a
        # market we failed to measure, it is a claim nobody has described. It
        # must not inherit the model branch's wording either, which would
        # attribute a measurement to it that was never taken.
        return MarketVerdict(
            servable=False,
            reason=f"unknown edge basis {resolved_basis!r}",
            detail=(
                "Default-deny. A basis names WHAT a pick claims; an unrecognised "
                f"one claims something undescribed. Known bases: {MODEL_BASIS!r}, "
                f"{MARKET_BASIS!r}."
            ),
        )
    return MarketVerdict(
        servable=False,
        reason=(
            f"{key[0] or 'unknown sport'} {key[1] or 'unknown market'} has no "
            "recorded model-vs-market measurement"
        ),
        detail=(
            "Default-deny. Serving a pick asserts the model beats the price; "
            "that assertion needs a measurement, and none is on file."
        ),
    )


def is_servable(sport: str, market: str, *, basis: str = MODEL_BASIS) -> bool:
    return market_verdict(sport, market, basis=basis).servable


def filter_pick_rows(
    sport: str,
    rows: Iterable[Mapping[str, Any]],
    *,
    market_key: str = "market",
    basis_key: str = "edge_basis",
) -> tuple[list[Mapping[str, Any]], dict[str, int]]:
    """Split priced pick rows into (servable, suppressed-counts-by-market).

    Returns the counts so callers can SAY what was withheld. A suppression
    nobody can see is one somebody deletes.

    A row may declare its own `edge_basis`. **A row that does not declare one is
    read as MODEL basis, not as "any basis"** -- these rows come from the
    recommendation artifact, whose edge has always been the model's, so absent
    means model here rather than unknown. The permissive reading would let a
    model pick through by omitting a field, which is the failure mode
    `learnings.md` calls "unknown must not default permissive"; the strict
    reading costs a market-basis producer one explicit field.
    """
    kept: list[Mapping[str, Any]] = []
    suppressed: dict[str, int] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        market = _normalise_market(row.get(market_key), sport)
        basis = str(row.get(basis_key) or "").strip().lower() or MODEL_BASIS
        if is_servable(sport, market, basis=basis):
            kept.append(row)
        else:
            label = market or "unknown"
            if basis != MODEL_BASIS:
                label = f"{label} ({basis})"
            suppressed[label] = suppressed.get(label, 0) + 1
    return kept, suppressed


def notice_for(sport: str, suppressed: Mapping[str, int] | None = None) -> dict[str, Any] | None:
    """A user-facing explanation of what is being withheld and why.

    None when nothing was suppressed, so a healthy surface stays quiet.
    """
    if not suppressed:
        return None
    markets = sorted(suppressed)
    verdicts = {m: market_verdict(sport, m) for m in markets}
    total = sum(suppressed.values())
    plural = "" if total == 1 else "s"
    scope = "this market" if len(markets) == 1 else "these markets"
    return {
        "kind": "picks_suppressed",
        "sport": str(sport or "").lower(),
        "suppressed_count": total,
        "markets": markets,
        "headline": (
            f"{total} {str(sport or '').upper()} MODEL pick{plural} withheld: the "
            f"model does not beat the closing line in {scope}."
        ),
        # NAMED, because the page now serves a second kind of pick beside these.
        # A headline that says "picks withheld" next to a list of picks reads as
        # a contradiction, and the reader resolves it by distrusting whichever
        # one they notice second.
        "basis": MODEL_BASIS,
        "other_bases_unaffected": [MARKET_BASIS],
        "reasons": [
            {
                "market": m,
                "reason": verdicts[m].summary(),
                "detail": verdicts[m].detail,
            }
            for m in markets
        ],
        "lift_condition": LIFT_CONDITION,
    }


#: What it now takes to reopen a market. REPLACED 2026-08-20 -- the old
#: condition ("paired error at or below the closing line's") is NECESSARY BUT
#: FAR TOO WEAK: a model can approach the close on MAE while still losing money
#: against the spread AND still being worse than a mindless side bet.
#:
#: Measured on 751 clean out-of-sample NCAAF games and 95 NFL preseason games:
#:
#:                        always bet the dog   the model   model adds
#:     NFL preseason            58.9%            54.7%       -4.2 pts
#:     NCAAF 2024               51.2%            46.8%       -4.4 pts
#:
#: The model is WORSE THAN IGNORING IT, in both sports, by nearly the same
#: margin. NCAAF ATS also gets WORSE as the edge filter tightens (46.8% at any
#: edge, 45.2% at 10+ points), so "serve only the strong picks" fails in the
#: direction opposite to the one that would help.
LIFT_CONDITION = (
    "A market reopens ONLY when all four hold, measured with "
    "scripts/grade_football_playability.py: (1) ATS win rate strictly above the "
    "better naive baseline -- always-bet-the-underdog or always-bet-the-favourite "
    "-- on the same games; the model currently LOSES to that baseline by ~4.3 "
    "points in both NCAAF and NFL. (2) 95% CI LOWER BOUND above the 52.4% "
    "breakeven at -110, not the point estimate and not 50%. (3) Out-of-sample, "
    "on a season that played no part in building or tuning it, with any subset "
    "PRE-SPECIFIED before testing. (4) Denominator in BETS, not rows -- per-book "
    "rows overstated significance 3.4x on the NFL grade. MAE is a diagnostic for "
    "the engine and is NOT evidence of playability; do not substitute it."
)


def board_notice(sport: str, markets: Iterable[str]) -> dict[str, Any] | None:
    """Explain a WHOLESALE suppression: no market this board can serve is open.

    Distinct from notice_for(), which reports how many actual rows were
    withheld. Here the board is stopped before candidates are built, so there is
    no row count -- and inventing one would put a fabricated number on a
    user-facing surface. Returns None the moment ANY market opens, so the board
    comes back on its own when a measurement lifts the gate, with no second edit.
    """
    wanted = [str(m).strip().lower() for m in markets if str(m).strip()]
    if not wanted:
        return None
    blocked = [m for m in wanted if not is_servable(sport, m, basis=MODEL_BASIS)]
    if len(blocked) < len(wanted):
        return None
    verdicts = {m: market_verdict(sport, m) for m in blocked}
    return {
        "kind": "picks_board_suppressed",
        "sport": str(sport or "").lower(),
        "markets": blocked,
        "headline": (
            f"{str(sport or '').upper()} MODEL picks are suppressed: the model "
            "does not beat the closing line in any market this board serves."
        ),
        # See notice_for(). This notice is now a BANNER on a board that may
        # still have market-basis rows under it, not necessarily a blackout --
        # the caller decides which, and says so.
        "basis": MODEL_BASIS,
        "other_bases_unaffected": [MARKET_BASIS],
        "reasons": [
            {
                "market": m,
                "reason": verdicts[m].summary(),
                "detail": verdicts[m].detail,
            }
            for m in blocked
        ],
        # Same constant as notice_for(). This is the copy the SERVED board
        # renders, so a divergence here would show users a criterion that is no
        # longer the one in force -- two copies where only one gets updated.
        "lift_condition": LIFT_CONDITION,
    }


def registry_snapshot() -> list[dict[str, Any]]:
    """Every recorded verdict, for ops/audit surfaces."""
    return [
        {
            "sport": sport,
            "market": market,
            "servable": verdict.servable,
            "reason": verdict.reason,
            "measured_on": verdict.measured_on,
            "model_metric": verdict.model_metric,
            "market_metric": verdict.market_metric,
            "metric_name": verdict.metric_name,
            "sample_size": verdict.sample_size,
            "detail": verdict.detail,
        }
        for (sport, market), verdict in sorted(_SERVING_REGISTRY.items())
    ]
