"""WNBA GAME-LINE projections for the Layer 1 board (`#364`).

Measured 2026-08-11 on the live board: WNBA carried 1,013 rows across 3 games at
36.4% projection coverage -- and **0.0% of that was on game lines**. Every single
projection sat on a player prop; not one moneyline, spread or total had a sim
attached, on a board whose entire purpose is putting a model next to a price.

It was never a join or naming failure. `attach_wnba_projections` opens with

    if str(row.get("kind") or "") != "prop":
        continue

so game rows were never considered. The capability did not exist.

THE SOURCE WAS ALREADY THERE, and has been since 2026-08-02. `game_cards_<date>.csv`
carries `pred_margin` and `pred_total` -- the smart-sim means -- added in exactly
the commit whose comment reads "WNBA game markets had structurally zero edge".
The columns were written and nothing on the board ever read them.

FOUR DECISIONS, each one a place this could have produced a plausible wrong number:

1. `pred_margin` is HOME-POSITIVE. Confirmed at the writer, not inferred:
   `refresh_wnba_oddsapi_props.py:2558` computes `home_total - away_total`. Get
   this backwards and every moneyline probability inverts while still looking
   entirely reasonable.

2. Probability comes from `wnba.cards._margin_win_prob` -- IMPORTED, not copied.
   That function is the single sanctioned margin->probability transform, and its
   own comment says so ("probability derivation stays in wnba/cards.py's
   _source_betting so there is exactly one margin->probability transform site").
   A second copy here would drift silently.

3. Spreads and totals get `projected` ONLY, with probability left null -- UNLESS
   the row's own line is the sim's own market line (`#263`, below). This is the
   module rule from `wnba_projections`: the sim ships MEANS with no distribution
   attached, and turning a mean into P(over) needs an assumption nobody has
   measured. A blank is recoverable; a fabricated probability propagates into EV
   and eventually a stake (`#242`). Moneyline is different and legitimately gets
   a probability, because `_margin_win_prob` IS the measured model -- not an
   assumption invented at the join.

4. FULL-GAME SEGMENTS ONLY. `pred_margin`/`pred_total` are full-game means, so
   stamping them on a Q1 or H1 row would attach a 40-minute projection to a
   10-minute market -- a real number against the wrong bet, which `#262` and the
   soccer join both establish as worse than a blank.

`#263`, 2026-08-19: decision 3's premise was ONLY HALF TRUE. The persisted
smart-sim artifact (`smart_sim_<date>_<HOME>_<AWAY>.json`, read by
`_smart_sim_projection_index` in `refresh_wnba_oddsapi_props.py`) carries real,
model-free Monte Carlo probabilities in its `score` block --
`p_home_cover`/`p_total_over` -- computed AGAINST the specific market line the
sim was given. No distributional assumption is needed for THAT ONE LINE; it was
simply never threaded from the sim payload into `game_cards_<date>.csv`, and
then never read here. Threaded through as of this change:
`sim_market_home_spread`/`sim_market_total` travel alongside
`p_home_cover`/`p_total_over` specifically so this module can tell "the sim's
own line" from an alternate one -- the sim persists only 3-point quantiles
(p10/p50/p90), not a full draw array, so it can answer a probability for the
ONE line it priced and not for an arbitrary alt line. A `spreads_alt`/
`totals_alt` row at a different number stays exactly as decision 3 describes:
projected-only, probability null, honestly labelled as an alternate line rather
than reusing the "sim ships a mean, not a distribution" reason, which would be
false for these rows now that the main line is priced.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from syndicate.features.shared.live_edge_policy import live_edge_unavailable_reason
from syndicate.features.shared.prop_projections import _edge_unavailable_reason, _no_vig_over_probability
from syndicate.features.shared.team_aliases import teams_match

# Tolerance for comparing a board row's `line` against the sim's own market
# line. Both travel through `round(x, 3)` at their respective writers
# (`_sim_projection_fields`/`game_odds` ingestion), so a tolerance tighter than
# that rounding step would reject a legitimate match on float noise, and one
# looser than it would risk conflating two genuinely different alt lines.
_MARKET_LINE_MATCH_EPSILON = 1e-6


def _norm_team(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _as_float(value: Any) -> float | None:
    try:
        if value is None or str(value).strip() == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _lines_match(a: float | None, b: float | None) -> bool:
    """Is a board row's line the SAME number as the sim's own market line?

    `None` never matches `None` -- an absent sim line must not silently pass
    every row that also happens to have no line (h2h has none; this is only
    called for spreads/totals, which always carry one when priced).
    """
    if a is None or b is None:
        return False
    return abs(a - b) <= _MARKET_LINE_MATCH_EPSILON


@dataclass
class WnbaGameProjectionIndex:
    by_teams: dict[tuple[str, str], dict[str, Any]] = field(default_factory=dict)
    by_tri: dict[tuple[str, str], dict[str, Any]] = field(default_factory=dict)
    games: int = 0
    source_path: str = ""

    def lookup(self, home: Any, away: Any) -> dict[str, Any] | None:
        h, a = _norm_team(home), _norm_team(away)
        if not (h and a):
            return None
        exact = self.by_teams.get((h, a)) or self.by_tri.get((h, a))
        if exact is not None:
            return exact
        # Alias fallback, and DELIBERATELY only when it is unambiguous. Two
        # candidates matching means the join cannot know which, and a wrong
        # projection is worse than a blank -- same rule the soccer index uses.
        hits = [
            entry
            for (index_home, index_away), entry in self.by_teams.items()
            if teams_match("wnba", h, index_home) and teams_match("wnba", a, index_away)
        ]
        return hits[0] if len(hits) == 1 else None


def load_wnba_game_projections(selected_date: str) -> WnbaGameProjectionIndex:
    """Index `game_cards_<date>.csv` by team names and tri-codes.

    Read through `wnba.cards`' keyvalue-aware loader rather than pathlib: the
    refresh pipeline writes this file to BOTH the keyvalue store and the local
    disk, and which one a given service can see differs. That loader also carries
    the last-good fallback for a transient keyvalue read failure, which is the
    difference between "no games today" and "the backend blinked" -- a
    distinction that has already zeroed this board once.
    """
    index = WnbaGameProjectionIndex()
    try:
        from syndicate.features.wnba.cards import _load_game_cards_csv_rows_from_keyvalue

        rows = _load_game_cards_csv_rows_from_keyvalue(selected_date) or []
    except Exception:
        return index
    index.source_path = f"game_cards_{selected_date}.csv"
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        home = row.get("home_team")
        away = row.get("visitor_team") or row.get("away_team")
        margin = _as_float(row.get("pred_margin"))
        total = _as_float(row.get("pred_total"))
        if margin is None and total is None:
            continue
        entry = {
            "pred_margin": margin,
            "pred_total": total,
            # `#263`. Absent on any `game_cards` row written before this
            # column existed -- `.get()` on the CSV dict already returns
            # `""`, and `_as_float("")` is `None`, so an older row degrades to
            # exactly decision 3's original behaviour (probability null) with
            # no special-casing needed here.
            "p_home_cover": _as_float(row.get("p_home_cover")),
            "p_total_over": _as_float(row.get("p_total_over")),
            "sim_market_home_spread": _as_float(row.get("sim_market_home_spread")),
            "sim_market_total": _as_float(row.get("sim_market_total")),
        }
        h, a = _norm_team(home), _norm_team(away)
        if h and a:
            index.by_teams[(h, a)] = entry
        ht, at = _norm_team(row.get("home_tri")), _norm_team(row.get("away_tri"))
        if ht and at:
            index.by_tri[(ht, at)] = entry
    index.games = len(index.by_teams) or len(index.by_tri)
    return index


def _home_win_prob(margin: float | None) -> float | None:
    # Imported, never reimplemented -- see decision 2 in the module docstring.
    try:
        from syndicate.features.wnba.cards import _margin_win_prob

        return _margin_win_prob(margin)
    except Exception:
        return None


def _mean_only_reason(*, kind: str, sim_line: float | None, at_market_line: bool) -> str:
    """Why `model_prob_over` might stay null on a spreads/totals row.

    THREE distinguishable cases, not two -- collapsing them was decision 3's
    original shape and `#263` is partly a fix to the REASON, not only the
    number. `at_market_line=True` is included for completeness (the caller
    always tries to price it in that case) but this function only ever
    supplies the PRE-attach default; `_attach_sim_probability_edge` pops it on
    success.
    """
    if sim_line is None:
        # The sim never priced ANY line for this market on this row's game --
        # decision 3's original, still-true reason.
        return f"sim ships a {kind} mean, not a distribution"
    if not at_market_line:
        # `#263`. Genuinely different from the case above: the sim DID price
        # one line, just not this one. Keeping the old reason here would be a
        # false claim once this ships -- "not a distribution" reads as "never
        # measured", when a real measurement exists one line away.
        return (
            f"sim priced only its own market line ({sim_line:g}); "
            "this is an alternate line the sim's 3-point quantile summary cannot answer"
        )
    return f"sim ships a {kind} mean, not a distribution"


def _attach_sim_probability_edge(
    projection: dict[str, Any], *, row: Mapping[str, Any], model_prob: float | None
) -> None:
    """`#263`. Mutates `projection` in place, ONLY called once the row's line
    has already been confirmed to match the sim's own market line.

    REUSES the shared edge computation (`prop_projections.py:918-946`) rather
    than hand-rolling a fifth one -- same fair-probability source
    (`_no_vig_over_probability`, consensus-priced, two-sided-only by design)
    and the same live-edge suppression (`live_edge_unavailable_reason`) every
    other sport's game-market join already goes through. This function does
    NOT route through `attach_projections`/`project_game_market` itself --
    doing so would also fix the `#329` "fourth producer" duplication this
    module's docstring already flags, but that touches
    `prop_projections.py`, which MLB/soccer/NFL depend on too. Left as a
    follow-on, not taken here.
    """
    if model_prob is None:
        return
    projection["model_prob_over"] = round(model_prob, 4)
    # `probability_unavailable_reason` was set to the mean-only reason before
    # this call; it is now false (a probability WAS attached), so drop it
    # rather than leave a stale reason beside a real number.
    projection.pop("probability_unavailable_reason", None)

    live_reason = live_edge_unavailable_reason(row)
    if live_reason:
        projection["edge_vs_market_pct"] = None
        projection["edge_unavailable_reason"] = live_reason
        return
    fair = _no_vig_over_probability(row)
    projection["market_fair_prob_over"] = fair
    if fair is None:
        # REUSED, not a sixth phrasing: `_edge_unavailable_reason` already
        # enumerates every way a two-sided fair can fail to exist (one-sided
        # market, incomplete 3-way, missing consensus on a specific side) and
        # is what `prop_projections.attach_projections` reports for the
        # identical failure on every other sport's game markets.
        projection["edge_vs_market_pct"] = None
        projection["edge_unavailable_reason"] = _edge_unavailable_reason(row, model_prob=model_prob, fair=fair)
        return
    projection["edge_vs_market_pct"] = round((float(model_prob) - float(fair)) * 100.0, 2)


def attach_wnba_game_projections(
    grid: Iterable[Mapping[str, Any]], index: WnbaGameProjectionIndex
) -> dict[str, Any]:
    """Stamp `projection` onto WNBA full-game h2h/spreads/totals rows."""
    considered = 0
    attached = 0
    unmatched_games = 0
    non_full_segment = 0

    for row in grid:
        if str(row.get("kind") or "") == "prop":
            continue
        market = str(row.get("market") or "").strip().lower()
        if market not in {"h2h", "spreads", "totals"}:
            continue
        considered += 1
        # Decision 4: a full-game mean must not be stamped on a period market.
        if str(row.get("segment") or "full").strip().lower() not in {"", "full"}:
            non_full_segment += 1
            continue
        entry = index.lookup(row.get("home_team"), row.get("away_team"))
        if entry is None:
            unmatched_games += 1
            continue

        projection: dict[str, Any] | None = None
        if market == "h2h":
            prob_home = _home_win_prob(entry.get("pred_margin"))
            if prob_home is not None:
                home_name = str(row.get("home_team") or "").strip()
                projection = {
                    "model_prob_over": round(prob_home, 4),
                    "side": home_name,
                    "projected": entry.get("pred_margin"),
                    "basis": "margin_win_prob",
                    "source": "wnba_game_cards",
                    # THE ONLY BRANCH HERE THAT SET NEITHER AN EDGE NOR A REASON.
                    # `spreads` and `totals` below both state
                    # `probability_unavailable_reason` and both get an
                    # `edge_vs_line` from the block at the end of this loop --
                    # which `market != "h2h"` deliberately excludes h2h from,
                    # because a moneyline has no line to subtract. So h2h alone
                    # served a projection with no edge of either contract and
                    # nothing saying why.
                    #
                    # Caught by the 2026-08-16 falsification sweep AFTER the
                    # matching fix shipped to `prop_projections`: MLB went
                    # 284 -> 0 unattributed and these 3 rows did not move,
                    # because THIS function writes `row["projection"]` directly
                    # and never passes through `attach_projections`. A fourth
                    # producer, exactly the shape `#329`'s notes warn about for
                    # `fair_price` — a count of definitions is not a count of
                    # producers, and the residual is what found it.
                    "edge_vs_market_pct": None,
                    # NOT priced, deliberately. Unlike spreads/totals the term
                    # is not missing: these rows have a `model_prob_over` AND a
                    # computable two-sided no-vig fair, so an edge is
                    # arithmetically available. Measured 2026-08-16, Portland
                    # Fire @ Phoenix Mercury: model 0.9673 against a market fair
                    # of 0.6502 = +31.7 pp, on a projection whose own
                    # `model_skill` reads `sample_games: 0, "model never
                    # backtested"`. Publishing a 31-point moneyline edge off an
                    # unvalidated margin model is the clamp failure mode --
                    # a confident number from an input nobody has checked.
                    # Turning this on is a modelling decision, not a plumbing
                    # one, and it belongs with whoever validates the margin
                    # model.
                    "edge_unavailable_reason": (
                        "this projection's producer does not compute a "
                        "probability-space edge, so none was priced"
                    ),
                }
        elif market == "spreads":
            margin = entry.get("pred_margin")
            if margin is not None:
                sim_line = entry.get("sim_market_home_spread")
                # `#263`. Only at the SIM'S OWN line -- see the module
                # docstring for why an alt line can't be priced from a 3-point
                # quantile summary. Compared directly against `row.get("line")`,
                # the same convention `edge_vs_line` below already uses (both
                # home-positive) -- not newly introduced by this change.
                at_market_line = _lines_match(_as_float(row.get("line")), sim_line)
                projection = {
                    "projected": round(margin, 3),
                    "side": str(row.get("home_team") or "").strip(),
                    "basis": "model_margin_mean",
                    "source": "wnba_game_cards",
                    "model_prob_over": None,
                    "edge_vs_market_pct": None,
                    "probability_unavailable_reason": _mean_only_reason(
                        kind="margin", sim_line=sim_line, at_market_line=at_market_line
                    ),
                }
                if at_market_line:
                    _attach_sim_probability_edge(projection, row=row, model_prob=entry.get("p_home_cover"))
        else:  # totals
            total = entry.get("pred_total")
            if total is not None:
                sim_line = entry.get("sim_market_total")
                at_market_line = _lines_match(_as_float(row.get("line")), sim_line)
                projection = {
                    "projected": round(total, 3),
                    "side": "over",
                    "basis": "model_total_mean",
                    "source": "wnba_game_cards",
                    "model_prob_over": None,
                    "edge_vs_market_pct": None,
                    "probability_unavailable_reason": _mean_only_reason(
                        kind="total", sim_line=sim_line, at_market_line=at_market_line
                    ),
                }
                if at_market_line:
                    _attach_sim_probability_edge(projection, row=row, model_prob=entry.get("p_total_over"))
        if projection is None:
            continue
        line = _as_float(row.get("line"))
        projected = _as_float(projection.get("projected"))
        if line is not None and projected is not None and market != "h2h":
            projection["edge_vs_line"] = round(projected - line, 3)
        row["projection"] = projection  # type: ignore[index]
        attached += 1

    return {
        "supported": True,
        "rows_considered": considered,
        "rows_with_projection": attached,
        "unmatched_game_rows": unmatched_games,
        "non_full_segment_rows": non_full_segment,
        "games_in_index": index.games,
        "source_artifact": index.source_path,
    }
