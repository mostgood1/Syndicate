"""hockeysim's pregame predictions joined onto the NHL Layer 1 board.

WHY THIS EXISTS. NHL Layer 1 reported `no_projection_source_for_sport` and the
Proj/Edge columns stayed dead, while `predictions_<date>.csv` was being written
and published the whole time -- verified on production 2026-09-26, HTTP200,
14 games carrying `p_home_ml`, `model_total`, `model_spread` and puckline
probabilities. `_attach_projections_by_sport` simply had no `nhl` branch, so the
default arm returned `{"supported": False}`. This was a JOIN that was never
wired, not a missing sim, and prices with no model are an odds screen rather
than a betting board.

WHY IT IS NOT `ncaaf_game_projections` WITH A SPORT ARGUMENT -- the same rule
that module states for itself. It hardcodes `source: "ncaaf_smartsim2"`, and its
caveats describe a football margin model measured against the closing line.
Reusing it would stamp NHL rows with another sport's provenance, which
`learnings.md` 2026-08-21 makes FORBIDDEN: a value published under a name that
describes a different quantity. The genuinely generic pieces ARE shared and not
copied -- `_no_vig_over_probability`, `live_edge_unavailable_reason` and
`refuse_published_certainty` are imported.

THE CENTRAL RULE HERE: A PROJECTION IS LINE-INDEPENDENT, A PROBABILITY IS NOT.

`model_total` (6.7993) and `model_spread` (the home margin) are the model's view
of the game and stay true whatever number a book hangs. `p_over` is the
probability of going over ONE SPECIFIC NUMBER -- `totals_line_used` -- and
against a board row at any other line it answers a different question. So every
matched game publishes a projection, and a probability is published only where
the model priced that exact line. Everything else is projection-only with the
refusal named: shown on the board, NOT priced. That is the posture WNBA's live
tier and NFL already take.

THE ZERO THAT MUST NEVER BE PUBLISHED. When hockeysim runs with no market
available it writes `anchor_state=no_market`, leaves `totals_line_used` empty,
and writes `p_over = p_under = p_push_total = 0.0`. Those zeros are MISSING
VALUES WEARING A NUMBER'S CLOTHES. Measured across four dates:

    2026-09-26  14 games   anchored  0/14    p_over != 0   0/14
    2026-09-25   4 games   anchored  4/4     p_over != 0   4/4
    2026-09-24  11 games   anchored 11/11    p_over != 0  11/11
    2026-09-23   4 games   anchored  2/4     p_over != 0   2/4   <- MIXED IN ONE FILE

So the refusal is per-GAME and conditional, never a per-file or hardcoded
switch. Publishing `p_over = 0.0` would tell the board the under is a certainty
and hand `edge_vs_market_pct` a fabricated edge on every totals row of a
14-game slate.

ONLY ONE PUCKLINE IS PRICED. `p_home_pl_-1.5` and `p_away_pl_+1.5` are exact
complements (0.18635 / 0.81365 on 2026-09-26) -- the same bet stated twice, not
two lines. P(home covers +1.5) needs the probability of losing by exactly one
goal, which this artifact does not carry. So a puckline probability is published
at the home -1.5 line and nowhere else; the projected margin still goes out on
every spread row.

SKILL IS UNMEASURED, AND THAT IS SAID RATHER THAN IMPLIED. Unlike NCAAF's model,
which is measured as LOSING to the close, hockeysim has no powered market
backtest -- it is an EV/Poisson approximation per period and the sample is
n=14-15 games. `model_skill` therefore reports "unmeasured", which is a third
value beside good and bad, and a reader must not infer either.
"""

from __future__ import annotations

import csv
import logging
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from syndicate.features.shared.probability_refusal import refuse_published_certainty

_LOGGER = logging.getLogger(__name__)

SOURCE = "nhl_hockeysim"

PUCKLINE = 1.5


def _as_float(value: Any) -> float | None:
    try:
        if value is None or str(value).strip() == "":
            return None
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return number


def _norm_team(name: Any) -> str:
    return "".join(ch for ch in str(name or "").lower() if ch.isalnum())


def _skill_note() -> dict[str, Any]:
    """NOT a disclaimer -- the honest state of the evidence.

    "Unmeasured" is a third value beside good and bad. hockeysim's market
    backtest is unpowered (n=14-15), so a claim in either direction would be
    invented.
    """
    return {
        "state": "unmeasured",
        "note": (
            "hockeysim has no powered market backtest (EV/Poisson per period, n=14-15 games); "
            "this projection is neither validated nor disproven against the close"
        ),
    }


@dataclass
class NhlGameProjectionEntry:
    home: str
    away: str
    p_home_ml: float | None
    model_total: float | None
    model_spread: float | None
    p_home_pl_minus_1_5: float | None
    p_over: float | None
    totals_line_used: float | None
    anchor_state: str
    orientation_flipped: bool = False

    def oriented(self, *, flipped: bool) -> "NhlGameProjectionEntry":
        """Restate every number in the BOARD's home/away frame.

        A silent frame mismatch is the worst failure available here: it does not
        blank a column, it publishes a confident number for the other team.
        """
        if not flipped:
            return self
        return NhlGameProjectionEntry(
            home=self.away,
            away=self.home,
            p_home_ml=None if self.p_home_ml is None else 1.0 - self.p_home_ml,
            model_total=self.model_total,
            model_spread=None if self.model_spread is None else -self.model_spread,
            # The away side of a home -1.5 puckline is NOT the complement of
            # this number (see the module docstring), so it is dropped rather
            # than converted. A wrong puckline is worse than no puckline.
            p_home_pl_minus_1_5=None,
            p_over=self.p_over,
            totals_line_used=self.totals_line_used,
            anchor_state=self.anchor_state,
            orientation_flipped=True,
        )


@dataclass
class NhlGameProjectionIndex:
    date: str
    by_pair: dict[tuple[str, str], NhlGameProjectionEntry] = field(default_factory=dict)

    @property
    def games(self) -> int:
        return len(self.by_pair)

    def lookup(self, home: Any, away: Any) -> NhlGameProjectionEntry | None:
        h, a = _norm_team(home), _norm_team(away)
        if not h or not a:
            return None
        entry = self.by_pair.get((h, a))
        if entry is not None:
            return entry.oriented(flipped=False)
        entry = self.by_pair.get((a, h))
        if entry is not None:
            return entry.oriented(flipped=True)
        return None


def load_nhl_game_projections(selected_date: str) -> NhlGameProjectionIndex:
    """Read `predictions_<date>.csv` into a date-scoped index.

    A missing file is an EMPTY index, not an exception: the caller then reports
    "no projections for this date", which is a different and less alarming
    statement than "the join failed".
    """
    from syndicate.features.nhl.sources import processed_path

    index = NhlGameProjectionIndex(date=str(selected_date)[:10])
    path = processed_path("predictions_" + index.date + ".csv")
    try:
        if not path.exists():
            return index
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
    except OSError:
        _LOGGER.exception("NHL_GAME_PROJECTIONS_READ_FAILED date=%s path=%s", index.date, path)
        return index

    for raw in rows:
        home = str(raw.get("home") or "").strip()
        away = str(raw.get("away") or "").strip()
        if not home or not away:
            continue
        anchor_state = str(raw.get("anchor_state") or "").strip().lower()
        totals_line = _as_float(raw.get("totals_line_used"))
        p_over = _as_float(raw.get("p_over"))
        # THE REFUSAL, per game. `no_market` means hockeysim priced no total at
        # all and wrote 0.0; keeping that would publish a certainty.
        if anchor_state != "anchored" or totals_line is None:
            p_over = None
            totals_line = None
        index.by_pair[(_norm_team(home), _norm_team(away))] = NhlGameProjectionEntry(
            home=home,
            away=away,
            p_home_ml=_as_float(raw.get("p_home_ml")),
            model_total=_as_float(raw.get("model_total")),
            model_spread=_as_float(raw.get("model_spread")),
            p_home_pl_minus_1_5=_as_float(raw.get("p_home_pl_-1.5")),
            p_over=p_over,
            totals_line_used=totals_line,
            anchor_state=anchor_state,
        )
    return index


def _game_projection(
    row: Mapping[str, Any], market: str, entry: NhlGameProjectionEntry
) -> dict[str, Any] | None:
    """The model's view of one full-game row, already in the row's frame.

    `model_prob_over` follows the grid convention every game producer uses: the
    HOME side for h2h and spreads, the OVER for totals.
    """
    line = _as_float(row.get("line"))
    home_name = str(row.get("home_team") or "").strip()
    common: dict[str, Any] = {"source": SOURCE, "model_skill": _skill_note()}
    if entry.orientation_flipped:
        common["orientation_flipped"] = True

    if market == "h2h":
        if entry.p_home_ml is None:
            return None
        return {
            **common,
            "model_prob_over": round(entry.p_home_ml, 4),
            "side": home_name,
            # A win probability is not a projected STAT; the board reads its
            # Win% column from `model_prob_over`.
            "projected": None,
            "basis": "hockeysim_home_ml",
        }

    if market == "totals":
        if entry.model_total is None:
            return None
        projection: dict[str, Any] = {
            **common,
            "projected": round(entry.model_total, 3),
            "side": "over",
            "basis": "hockeysim_model_total",
            "model_prob_over": None,
        }
        if line is not None:
            projection["edge_vs_line"] = round(entry.model_total - line, 3)
        # A probability ONLY at the number the model actually priced.
        if entry.p_over is None:
            projection["probability_unavailable_reason"] = (
                "no over probability: hockeysim ran with no market for this game "
                "(anchor_state=" + (entry.anchor_state or "unknown") + "), so its p_over is an unset 0.0"
            )
        elif line is None:
            projection["probability_unavailable_reason"] = "no over probability: the row carries no line"
        elif entry.totals_line_used is None or abs(line - entry.totals_line_used) > 1e-9:
            projection["probability_unavailable_reason"] = (
                "no over probability at " + str(line) + ": hockeysim priced only "
                + str(entry.totals_line_used) + ", and P(over) at another number is a different question"
            )
        else:
            projection["model_prob_over"] = round(entry.p_over, 4)
        return projection

    if market == "spreads":
        if entry.model_spread is None:
            return None
        projection = {
            **common,
            "projected": round(entry.model_spread, 3),
            "side": home_name,
            "basis": "hockeysim_model_spread",
            "model_prob_over": None,
        }
        if line is not None:
            projection["edge_vs_line"] = round(entry.model_spread - line, 3)
        if line is not None and abs(line + PUCKLINE) <= 1e-9 and entry.p_home_pl_minus_1_5 is not None:
            # home -1.5, the one puckline this artifact prices.
            projection["model_prob_over"] = round(entry.p_home_pl_minus_1_5, 4)
        else:
            projection["probability_unavailable_reason"] = (
                "no cover probability at " + str(line) + ": hockeysim prices only the home -1.5 "
                "puckline, and its away +1.5 column is that same bet restated, not a second line"
            )
        return projection

    return None


def _started_game_reason(row: Mapping[str, Any]) -> str | None:
    """A PER-SPORT BELT over `live_edge_unavailable_reason`, and why it is needed.

    That policy keys on the GAME STATE and says, deliberately, that an unknown
    state still allows an edge -- correct, because a resolvable-state gap should
    not blank the whole edge column.

    NHL's state is not unknown, it is WRONG. Measured 2026-09-26 on the served
    board: BOS @ WSH `commence_time=2026-09-25T23:08:24Z` still reported
    `state: pregame` with null scores about fifteen hours after puck drop. So
    the guard could not fire, and this join published `edge_vs_market_pct
    +54.83` for over 5.5 against a SETTLED market quoting +800 / -750 -- the
    exact `#340` failure, a pregame model priced against a market that already
    knows the answer.

    `commence_time` is on the row and is not derived from the broken join, so it
    answers the only question that matters here: has the market already watched
    this game. Absent or unparseable -> None, i.e. fail OPEN to the policy above,
    because blanking edges on a parsing gap is the harm the policy warns about.

    DELETE THIS once NHL game state is trustworthy; it is compensation for a
    defect elsewhere, not a rule about hockey.
    """
    raw = str(row.get("commence_time") or "").strip()
    if not raw:
        return None
    try:
        from datetime import datetime, timezone

        start = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) < start:
            return None
    except (ValueError, TypeError):
        return None
    return (
        "the game has already started (commence_time " + raw + "): a pregame projection "
        "cannot be priced against a market that has watched it"
    )


def _price_against_market(row: Mapping[str, Any], projection: dict[str, Any], no_vig_over) -> None:
    """Stamp the market fair and the edge -- or the NAMED reason there is none.

    Includes the live rule (`#340`): a PREGAME projection priced against a
    market that has already watched the game is not an edge, it is the score.
    """
    from syndicate.features.shared.live_edge_policy import live_edge_unavailable_reason

    fair = no_vig_over(row)
    started_reason = _started_game_reason(row)
    projection["market_fair_prob_over"] = round(float(fair), 4) if fair is not None else None
    prob = projection.get("model_prob_over")
    live_reason = live_edge_unavailable_reason(row) or started_reason
    if live_reason:
        projection["edge_vs_market_pct"] = None
        projection["edge_unavailable_reason"] = live_reason
    elif prob is not None and fair is not None:
        projection["edge_vs_market_pct"] = round((float(prob) - float(fair)) * 100.0, 2)
    elif prob is None:
        projection["edge_vs_market_pct"] = None
        projection["edge_unavailable_reason"] = (
            projection.get("probability_unavailable_reason") or "no model probability"
        )
    else:
        projection["edge_vs_market_pct"] = None
        projection["edge_unavailable_reason"] = "no no-vig fair: the market is not quoted on both sides"


def attach_nhl_game_projections(
    grid: Iterable[Mapping[str, Any]],
    index: NhlGameProjectionIndex,
    *,
    selected_date: str | None = None,
) -> dict[str, Any]:
    """Stamp `projection` onto NHL full-game h2h/spreads/totals rows.

    `selected_date` SCOPES THE COUNTERS. The index is date-scoped, and a row
    belonging to another date is not a miss on THIS date -- counting it as one
    is what made a healthy NCAAF join read as a near-total failure (9.3%
    against a re-derived 47%).
    """
    from syndicate.features.shared.prop_projections import _no_vig_over_probability

    considered = 0
    attached = 0
    unmatched = 0
    non_full_segment = 0
    priced = 0
    refusals: dict[str, int] = {}

    for row in grid:
        if str(row.get("kind") or "") == "prop":
            continue
        market = str(row.get("market") or "").strip().lower()
        if market not in {"h2h", "spreads", "totals"}:
            continue
        if selected_date:
            row_date = str(row.get("commence_time") or "")[:10]
            if row_date and row_date != str(selected_date)[:10]:
                continue
        considered += 1
        if str(row.get("segment") or "full").strip().lower() not in {"", "full"}:
            # Every number here is full-game; a period market is a different bet.
            non_full_segment += 1
            continue
        entry = index.lookup(row.get("home_team"), row.get("away_team"))
        if entry is None:
            unmatched += 1
            continue
        projection = _game_projection(row, market, entry)
        if projection is None:
            unmatched += 1
            continue
        _price_against_market(row, projection, _no_vig_over_probability)
        row["projection"] = refuse_published_certainty(projection)  # type: ignore[index]
        attached += 1
        if projection.get("model_prob_over") is not None:
            priced += 1
        else:
            reason = str(projection.get("probability_unavailable_reason") or "unknown").split(":")[0]
            refusals[reason] = refusals.get(reason, 0) + 1

    return {
        "supported": True,
        "rows_considered": considered,
        "rows_with_projection": attached,
        # Attached but UNPRICED is the population this join deliberately
        # creates: a projection shown on the board with no probability behind
        # it. Counting it separately is what keeps that visible.
        "rows_with_probability": priced,
        "rows_unmatched": unmatched,
        "rows_non_full_segment": non_full_segment,
        "probability_refusals": refusals,
        "games_in_artifact": index.games,
        "artifact_date": index.date,
    }
