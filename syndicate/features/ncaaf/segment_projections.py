"""SmartSim 2.0's per-segment distributions joined onto NCAAF segment rows.

WHY THIS EXISTS. Measured on the served board 2026-09-26T18:51Z, mid-slate:

    full   686 / 898  = 76%   projected
    h1       0 / 351  =  0%
    q1       0 / 282  =  0%
    q3       0 / 260  =  0%
    q4       0 / 260  =  0%
    q2       0 / 232  =  0%
    h2       0 / 213  =  0%

1,598 rows -- 64% of every NCAAF game row -- showed a PRICE and no model.
`attach_ncaaf_game_projections` skips anything whose segment is not `full`, and
correctly so: its `margin_mean` / `total_mean` describe a whole game, and
"a quarter market is a different bet".

THIS IS A JOIN, NOT MODELLING, AND THAT WAS CHECKED BEFORE A LINE WAS WRITTEN.
The sim already stops discarding its per-quarter output (package S1,
`football_segment_distributions.py`), the flag is ON in production, and the
artifact is published and CURRENT: `smartsim2_segment_distributions_2026_wk4.json`
returned HTTP200 with 58 games, generated 16:20:22Z the same afternoon. Nothing
consumed it. A producer publishing to nobody is the same shape as the NHL
projection gap found earlier that day.

THE DISTRIBUTIONS ARE EMPIRICAL, WHICH IS STRICTLY BETTER THAN THE FULL-GAME
PATH. Each segment carries `total_points_dist` and `margin_dist` as histograms
over the run's sims (300), plus `home_points_mean` / `away_points_mean`. So a
probability here is a COUNT, not a normal approximation of one -- no `stdev`
assumption, and no fabricated shape for a quarter, which is exactly where a
normal fits worst (scores are lumpy multiples of 3 and 7, and a quarter has few
of them).

THE LINE IS THE AWAY LINE. `book_grid._canonical_line` states it, and
`margin_dist` is HOME-POSITIVE, so home covers when `margin > line` -- NOT
`margin > -line`, "the inversion that once put 0.74 on MLB underdogs"
(`test_spread_probability_is_home_covering_the_AWAY_FRAME_line`). One rule
serves all three markets here: STRICTLY GREATER THAN THE LINE, with the equality
bucket counted as a PUSH rather than folded into either side.

PUSHES ARE REPORTED, NOT ABSORBED. A discrete empirical distribution has real
mass exactly on integer lines, unlike the continuous full-game path where a push
has measure zero. `model_prob_over` is therefore conditional on NOT pushing --
which is how the bet actually settles, since a push returns the stake -- and
`push_probability` travels beside it so the conditioning is visible instead of
silently inflating the favourite. A row whose line can ONLY push (every sim
lands on it) publishes no probability at all.

SKILL: the same measured loss the full-game module carries. `#555` records this
model losing to the closing line (margin MAE 15.775 vs 12.212, n=2233) with
totals 1.67x over-dispersed, and `football/pick_gate.py` is explicit that
suppressing PICKS "does NOT stop projections being generated, published, or
displayed". So segments display, carrying `model_skill`, and the measured loss
acts through ranking rather than through a blank column.
"""

from __future__ import annotations

import logging
from typing import Any, Iterable, Mapping

from syndicate.features.shared.probability_refusal import refuse_published_certainty

_LOGGER = logging.getLogger(__name__)

SOURCE = "ncaaf_smartsim2_segment"

# The segments the sim publishes. `full` is deliberately NOT here: it belongs to
# `game_projections`, and two producers writing one row is how a board ends up
# unable to say which model it is showing.
SEGMENTS = ("h1", "h2", "q1", "q2", "q3", "q4")

MARKETS = ("h2h", "spreads", "totals")


def _as_float(value: Any) -> float | None:
    try:
        if value is None or str(value).strip() == "":
            return None
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and number not in (float("inf"), float("-inf")) else None


def _histogram(block: Mapping[str, Any], key: str) -> dict[float, int] | None:
    """`{outcome: count}` with numeric keys, or None when unusable.

    The artifact stores JSON object keys, so they arrive as strings; a
    silently-skipped unparseable key would quietly reweight the distribution,
    so any bad key voids the whole histogram rather than shrinking it.
    """
    raw = block.get(key)
    if not isinstance(raw, Mapping) or not raw:
        return None
    out: dict[float, int] = {}
    for outcome, count in raw.items():
        value = _as_float(outcome)
        try:
            n = int(count)
        except (TypeError, ValueError):
            return None
        if value is None or n < 0:
            return None
        out[value] = out.get(value, 0) + n
    return out or None


def probability_above(hist: Mapping[float, int], line: float) -> tuple[float | None, float]:
    """`(P(outcome > line | not a push), P(push))`.

    STRICTLY GREATER, because the line is the away line and a bet on the over /
    on home covering wins only past it. Equality is a PUSH: it returns the
    stake, so it belongs in neither numerator nor denominator.

    Returns `(None, 1.0)` when every sim lands exactly on the line -- there is
    no non-push outcome to have a probability about, and 0.0 or 0.5 would both
    be inventions.
    """
    over = under = push = 0
    for raw_outcome, count in hist.items():
        # ACCEPTS THE RAW ARTIFACT SHAPE. JSON object keys arrive as strings,
        # and this is the most natural thing to hand this function -- it used to
        # TypeError on exactly that. Parsing here is STRICT, not lenient: an
        # unparseable key voids the whole histogram rather than being skipped,
        # because silently dropping a bucket reweights the distribution.
        outcome = _as_float(raw_outcome)
        if outcome is None:
            return None, 0.0
        if outcome > line:
            over += count
        elif outcome < line:
            under += count
        else:
            push += count
    total = over + under + push
    if total <= 0:
        return None, 0.0
    decided = over + under
    push_prob = push / total
    if decided <= 0:
        return None, push_prob
    return over / decided, push_prob


def _segment_block(block: Mapping[str, Any], segment: str) -> Mapping[str, Any] | None:
    segments = block.get("segments")
    if not isinstance(segments, Mapping):
        return None
    got = segments.get(segment)
    return got if isinstance(got, Mapping) else None


def _skill_note() -> dict[str, Any]:
    """The full-game module's measurement, not a softer one for segments.

    A per-segment skill number does not exist yet. Reporting the game-level
    loss is honest; inventing a segment-level one, or omitting the caveat
    because none was measured at this grain, would both read as better news
    than the evidence supports.
    """
    return {
        "state": "measured_loss",
        "note": (
            "smartsim2 is measured LOSING to the closing line at game level "
            "(margin MAE 15.775 vs 12.212, n=2233; totals 1.67x over-dispersed). "
            "No per-segment skill measurement exists yet, so the game-level "
            "figure travels here rather than a segment-level claim"
        ),
    }


def segment_projection(
    row: Mapping[str, Any],
    *,
    market: str,
    segment: str,
    block: Mapping[str, Any],
    sims: Any = None,
) -> dict[str, Any] | None:
    """One segment row's view, or None when this segment carries no usable data.

    `model_prob_over` follows the grid convention every game producer uses: the
    HOME side for h2h and spreads, the OVER for totals.
    """
    seg = _segment_block(block, segment)
    if seg is None:
        return None
    home_mean = _as_float(seg.get("home_points_mean"))
    away_mean = _as_float(seg.get("away_points_mean"))
    if home_mean is None or away_mean is None:
        return None

    line = _as_float(row.get("line"))
    common: dict[str, Any] = {
        "source": SOURCE,
        "segment": segment,
        "basis": f"smartsim2_{segment}_empirical",
        "model_skill": _skill_note(),
        "sims": sims,
    }
    if seg.get("h2_regulation_only") is not None:
        # Said on the row because it changes what the number MEANS: an h2 that
        # includes overtime is a different bet from one that does not, and the
        # binning here matches how `segment_actuals` grades it.
        common["h2_regulation_only"] = bool(seg.get("h2_regulation_only"))

    if market == "totals":
        hist = _histogram(seg, "total_points_dist")
        projection: dict[str, Any] = {
            **common,
            "projected": round(home_mean + away_mean, 3),
            "side": "over",
            "model_prob_over": None,
        }
        if line is not None:
            projection["edge_vs_line"] = round(home_mean + away_mean - line, 3)
        if hist is None:
            projection["probability_unavailable_reason"] = (
                f"no over probability: the sim published no usable total_points_dist for {segment}"
            )
        elif line is None:
            projection["probability_unavailable_reason"] = "no over probability: the row carries no line"
        else:
            prob, push = probability_above(hist, line)
            projection["push_probability"] = round(push, 4)
            if prob is None:
                projection["probability_unavailable_reason"] = (
                    f"no over probability at {line}: every simulated {segment} total landed exactly on it, "
                    "so there is no non-push outcome to price"
                )
            else:
                projection["model_prob_over"] = round(prob, 4)
        return projection

    margin_hist = _histogram(seg, "margin_dist")
    margin_mean = home_mean - away_mean
    home_name = str(row.get("home_team") or "").strip()

    if market == "spreads":
        projection = {
            **common,
            "projected": round(margin_mean, 3),
            "side": home_name,
            "model_prob_over": None,
        }
        if line is not None:
            projection["edge_vs_line"] = round(margin_mean - line, 3)
        if margin_hist is None:
            projection["probability_unavailable_reason"] = (
                f"no cover probability: the sim published no usable margin_dist for {segment}"
            )
        elif line is None:
            projection["probability_unavailable_reason"] = "no cover probability: the row carries no line"
        else:
            # THE AWAY LINE. Home covers strictly PAST it.
            prob, push = probability_above(margin_hist, line)
            projection["push_probability"] = round(push, 4)
            if prob is None:
                projection["probability_unavailable_reason"] = (
                    f"no cover probability at {line}: every simulated {segment} margin landed exactly on it"
                )
            else:
                projection["model_prob_over"] = round(prob, 4)
        return projection

    if market == "h2h":
        projection = {
            **common,
            # A win probability is not a projected STAT; the board reads its
            # Win% column from `model_prob_over`. The projected MARGIN is still
            # useful context and rides as `edge_vs_line`-free metadata.
            "projected": None,
            "projected_margin": round(margin_mean, 3),
            "side": home_name,
            "model_prob_over": None,
        }
        if margin_hist is None:
            projection["probability_unavailable_reason"] = (
                f"no win probability: the sim published no usable margin_dist for {segment}"
            )
        else:
            # Winning the SEGMENT is margin > 0. A tied segment is a push on a
            # 3-way market and is reported rather than split.
            prob, push = probability_above(margin_hist, 0.0)
            projection["push_probability"] = round(push, 4)
            if prob is None:
                projection["probability_unavailable_reason"] = (
                    f"no win probability: every simulated {segment} ended level"
                )
            else:
                projection["model_prob_over"] = round(prob, 4)
        return projection

    return None


def _price_against_market(row: Mapping[str, Any], projection: dict[str, Any], no_vig_over) -> None:
    """Stamp the market fair and the edge, or the NAMED reason there is none.

    Delegates the live rule to `live_edge_unavailable_reason` (`#340`) rather
    than re-deciding it here -- a per-sport copy of that rule is what had to be
    removed from the NHL module the same day.
    """
    from syndicate.features.shared.live_edge_policy import live_edge_unavailable_reason

    fair = no_vig_over(row)
    projection["market_fair_prob_over"] = round(float(fair), 4) if fair is not None else None
    prob = projection.get("model_prob_over")
    live_reason = live_edge_unavailable_reason(row)
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


def load_ncaaf_segment_inputs(selected_date: str) -> tuple[dict[str, Any], dict[tuple[str, str], str]]:
    """`(blocks_by_game_id, game_id_by_team_pair)` for the dates in view.

    DERIVED FROM THE FULL-GAME INDEX'S OWN `sources`, not from a second
    season/week resolution. That index already decided which
    `smartsim2_projections_{season}_wk{week}.csv` files this date reads, and the
    segment artifact is the sidecar beside each one. Resolving it independently
    is how the two joins would quietly end up on different weeks.

    Returns empty on any failure: this artifact is optional by construction (its
    producer is behind a flag that defaults OFF), so absent is a NORMAL state and
    must never break the full-game join that runs beside it.
    """
    import csv as _csv
    import re as _re

    from syndicate.features.ncaaf.game_projections import _norm, load_ncaaf_game_projections
    from syndicate.features.shared.football_segment_distributions import (
        read_segment_distributions_artifact,
    )

    blocks: dict[str, Any] = {}
    game_ids: dict[tuple[str, str], str] = {}
    try:
        index = load_ncaaf_game_projections(selected_date)
    except Exception:
        _LOGGER.exception("NCAAF_SEGMENT_INDEX_FAILURE date=%s", selected_date)
        return {}, {}

    for source in getattr(index, "sources", None) or ():
        path = Path(str(source))
        match = _re.search(r"smartsim2_projections_(\d+)_wk(\d+)\.csv$", path.name)
        if not match:
            continue
        season, week = int(match.group(1)), int(match.group(2))
        try:
            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                for row in _csv.DictReader(handle):
                    home = str(row.get("home_team") or "").strip()
                    away = str(row.get("away_team") or "").strip()
                    game_id = str(row.get("game_id") or "").strip()
                    if home and away and game_id:
                        game_ids[(_norm(home), _norm(away))] = game_id
        except OSError:
            _LOGGER.exception("NCAAF_SEGMENT_CSV_READ_FAILURE path=%s", path)
            continue
        try:
            blocks.update(
                read_segment_distributions_artifact(season=season, week=week, data_root=path.parent)
            )
        except Exception:
            _LOGGER.exception("NCAAF_SEGMENT_ARTIFACT_READ_FAILURE season=%s week=%s", season, week)
    return blocks, game_ids


def attach_ncaaf_segment_projections(
    grid: Iterable[Mapping[str, Any]],
    *,
    blocks: Mapping[str, Mapping[str, Any]],
    game_id_by_pair: Mapping[tuple[str, str], str],
    selected_date: str | None = None,
) -> dict[str, Any]:
    """Stamp `projection` onto NCAAF h1/h2/q1-q4 rows.

    `game_id_by_pair` bridges the board to the artifact: the artifact is keyed
    by ESPN `game_id` and carries NO team names, while the board rows carry
    names and no such id. The sibling projections CSV has both, which is why
    the caller builds this map from the SAME file the full-game index is built
    from -- deriving it twice from two sources is how the two joins would drift
    onto different games. Its keys are `_norm` of the CSV's team names.

    MEASURED ON PRODUCTION 2026-09-26: 53 of 65 board games bridge. The 12 that
    do not are FBS-vs-FCS fixtures (Lindenwood, Central Arkansas, Gardner-Webb
    and nine more) -- the same boundary `game_projections._unratable_reason`
    already refuses at full game, not a join defect. They are counted as
    `segment_rows_unmatched_game` rather than dropped.
    """
    from syndicate.features.ncaaf.game_projections import _norm
    from syndicate.features.ncaaf.oddsapi_lines import resolve_team
    from syndicate.features.shared.prop_projections import _no_vig_over_probability

    considered = attached = 0
    priced = 0
    unmatched_game = 0
    no_segment_block = 0
    refusals: dict[str, int] = {}

    for row in grid:
        if str(row.get("kind") or "") == "prop":
            continue
        market = str(row.get("market") or "").strip().lower()
        segment = str(row.get("segment") or "").strip().lower()
        if market not in MARKETS or segment not in SEGMENTS:
            continue
        if selected_date:
            row_date = str(row.get("commence_time") or "")[:10]
            if row_date and row_date != str(selected_date)[:10]:
                continue
        considered += 1
        # THE SAME RESOLVER THE FULL-GAME JOIN USES, not a second one.
        # `resolve_team` canonicalises the BOARD's OddsAPI name against the
        # team registry; the map is keyed on `_norm` of the CSV's own name.
        # Using `team_aliases.normalize` instead matched 0 of 1752 rows --
        # measured, not guessed -- because the two name spaces differ.
        key = (_norm(resolve_team(row.get("home_team"))), _norm(resolve_team(row.get("away_team"))))
        game_id = game_id_by_pair.get(key)
        if game_id is None:
            unmatched_game += 1
            continue
        block = blocks.get(str(game_id))
        if not isinstance(block, Mapping):
            no_segment_block += 1
            continue
        projection = segment_projection(
            row, market=market, segment=segment, block=block, sims=block.get("sims")
        )
        if projection is None:
            no_segment_block += 1
            continue
        _price_against_market(row, projection, _no_vig_over_probability)
        row["projection"] = refuse_published_certainty(projection)  # type: ignore[index]
        attached += 1
        if projection.get("model_prob_over") is not None:
            priced += 1
        elif projection.get("model_prob_over_refused_value") is not None:
            # NOT "unknown". `refuse_published_certainty` blanked an exact
            # 0.0/1.0 -- a real outcome of 300 sims none of which crossed the
            # line (q1 over 0.5, say) -- and kept the value it refused. Counting
            # that as an unnamed failure would hide a working guard inside a
            # bucket that reads like a bug; measured 3 rows on 2026-09-26.
            refusals["refused_published_certainty"] = refusals.get("refused_published_certainty", 0) + 1
        else:
            reason = str(projection.get("probability_unavailable_reason") or "unnamed").split(":")[0]
            refusals[reason] = refusals.get(reason, 0) + 1

    return {
        "supported": True,
        "segment_rows_considered": considered,
        "segment_rows_with_projection": attached,
        # Attached but UNPRICED is a real population here: a projected segment
        # total with no probability shows and is not priced.
        "segment_rows_with_probability": priced,
        "segment_rows_unmatched_game": unmatched_game,
        "segment_rows_no_block": no_segment_block,
        "segment_probability_refusals": refusals,
        "segment_games_in_artifact": len(blocks),
    }
