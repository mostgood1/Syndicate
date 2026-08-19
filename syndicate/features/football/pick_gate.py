"""Which football markets have EARNED the right to be served as picks.

A projection is not a bet. A bet claims the model prices something better than
the market does, and that claim is measurable: score the model against realised
outcomes on the same games the market priced, and compare. Until that comparison
has been made AND won, serving a pick means selling an edge the model has not
demonstrated.

MEASURED 2026-08-19, NCAAF margins, and this is why the gate exists:

    n=220 games, prior-season 2024 SP+ -> realised 2025 margins (leak-free),
    40 seeds/game, closing spread on the same games as the benchmark.

        model MAE  13.763        market MAE  11.586
        paired dMAE +2.176, SE 0.518, t = +4.20   SIGNIFICANT

    The model is worse than the closing line by 2.2 points of margin MAE, at
    4.2 sigma. Not marginal, not noise: it loses to the close. Every scale from
    6 to 24 loses (best was 13.595, still +2.0 on the market), so this is a
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
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping


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
_SERVING_REGISTRY: dict[tuple[str, str], MarketVerdict] = {
    ("ncaaf", "spread"): MarketVerdict(
        servable=False,
        reason="NCAAF margin model loses to the closing line",
        measured_on="2026-08-19",
        model_metric=13.763,
        market_metric=11.586,
        sample_size=220,
        detail=(
            "Paired dMAE +2.176, SE 0.518, t=+4.20. Leak-free: prior-season "
            "2024 SP+ scoring realised 2025 margins. Every scale 6..24 loses to "
            "the close, so retuning SP_RATING_SCALE cannot lift this."
        ),
    ),
    ("ncaaf", "moneyline"): MarketVerdict(
        servable=False,
        reason="NCAAF moneyline is the same margin distribution, priced differently",
        measured_on="2026-08-19",
        model_metric=13.763,
        market_metric=11.586,
        sample_size=220,
        detail=(
            "Win probability is derived from the margin distribution this "
            "measurement condemns. Suppressing spread while leaving moneyline "
            "open would let the identical unearned edge through under another "
            "label, which is a loophole, not a narrower scope."
        ),
    ),
    ("ncaaf", "total"): MarketVerdict(
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


def _normalise_market(market: Any) -> str:
    """Fold the market spellings that reach this code onto registry keys.

    The same market arrives as 'SPREAD', 'spread', 'moneyline_home' and
    'game bet' depending on which surface built the row, so a bare equality
    check would silently pass most of them straight through the gate.
    """
    text = str(market or "").strip().lower()
    if not text:
        return ""
    if text.startswith("moneyline") or text in {"ml", "h2h"}:
        return "moneyline"
    if text.startswith("spread") or text in {"ats", "handicap", "run_line", "puck_line"}:
        return "spread"
    if text.startswith("total") or text in {"ou", "over_under", "overunder"}:
        return "total"
    return text


def market_verdict(sport: str, market: str) -> MarketVerdict:
    """The serving decision for one (sport, market). Unknown -> DENY."""
    key = (str(sport or "").strip().lower(), _normalise_market(market))
    known = _SERVING_REGISTRY.get(key)
    if known is not None:
        return known
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


def is_servable(sport: str, market: str) -> bool:
    return market_verdict(sport, market).servable


def filter_pick_rows(
    sport: str,
    rows: Iterable[Mapping[str, Any]],
    *,
    market_key: str = "market",
) -> tuple[list[Mapping[str, Any]], dict[str, int]]:
    """Split priced pick rows into (servable, suppressed-counts-by-market).

    Returns the counts so callers can SAY what was withheld. A suppression
    nobody can see is one somebody deletes.
    """
    kept: list[Mapping[str, Any]] = []
    suppressed: dict[str, int] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        market = _normalise_market(row.get(market_key))
        if is_servable(sport, market):
            kept.append(row)
        else:
            label = market or "unknown"
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
            f"{total} {str(sport or '').upper()} pick{plural} withheld: the "
            f"model does not beat the closing line in {scope}."
        ),
        "reasons": [
            {
                "market": m,
                "reason": verdicts[m].summary(),
                "detail": verdicts[m].detail,
            }
            for m in markets
        ],
        "lift_condition": (
            "Re-run the model-vs-market comparison on realised results. A market "
            "opens when the model's paired error is at or below the closing "
            "line's on the same games -- update _SERVING_REGISTRY with that "
            "measurement, never by loosening the default."
        ),
    }


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
    blocked = [m for m in wanted if not is_servable(sport, m)]
    if len(blocked) < len(wanted):
        return None
    verdicts = {m: market_verdict(sport, m) for m in blocked}
    return {
        "kind": "picks_board_suppressed",
        "sport": str(sport or "").lower(),
        "markets": blocked,
        "headline": (
            f"{str(sport or '').upper()} picks are suppressed: the model does "
            "not beat the closing line in any market this board serves."
        ),
        "reasons": [
            {
                "market": m,
                "reason": verdicts[m].summary(),
                "detail": verdicts[m].detail,
            }
            for m in blocked
        ],
        "lift_condition": (
            "Re-run the model-vs-market comparison on realised results. A market "
            "opens when the model's paired error is at or below the closing "
            "line's on the same games -- update _SERVING_REGISTRY with that "
            "measurement, never by loosening the default."
        ),
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
