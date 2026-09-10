"""Join the precomputed NFL player-prop model onto board rows.

WHY THIS FILE EXISTS, measured rather than assumed.

`portfolio_commit`'s own `PLAN_WRITTEN` counter, 2026-09-10T00:11:12Z:

    rows_in=3029 sized=25 positions=22 staked=$98.66
    refusals={'no_model_edge_pct': 1872, 'below_min_ev_pct': 573,
              'market_family_excluded': 501, 'beyond_max_positions': 56,
              'below_min_stake': 3, 'zero_kelly_stake': 2}
    no_model_edge_by_sport={'nfl': 1503, 'mlb': 285, 'soccer': 84}
    top_market_per_refusal={'no_model_edge_pct': 'receiving yards:473'}

**`no_model_edge_pct` is 61.8% of the funnel and NFL is 80% of that**, which
makes it the single largest term between a 3,029-row board and 22 positions.

AND THE MODEL FOR THOSE ROWS ALREADY EXISTS. `nfl_prop_projections_2026_wk1.json`
is published, allowlisted (`artifact_publisher.py:246`) and current -- 476,295
bytes, rebuilt 2026-09-10T00:09:04Z, two minutes before the board build above.
It carries **1,140 rows over 9 markets, 16 games and 249 players**, and
`receiving_yards` is its LARGEST family at 327 rows -- the very market the
refusal counter names.

Nothing on the board path read it. `nfl_props_rows_for_week` had exactly one
consumer, `nfl/cards.py:863` (the game-card UI), and
`attach_nfl_game_projections` skips prop rows outright at its second line
(`nfl_game_projections.py:361`, `if row["kind"] == "prop": continue`). So the
sim's answer was computed, published, and then discarded at the board seam --
the same shape as the football quarter_log, the MLB inning vectors and the
Kalshi liquidity fields.

WHAT MAKES THIS A JOIN AND NOT A MODEL. `sim_projection` IS ALREADY A COVER
PROBABILITY, not a mean: `props.py:635` computes it through
`_nfl_prop_model_probability` (a validated Normal/log-normal blend) and
`props.py:645` writes it beside `projected_value`, which is the mean. So a
probability-space `edge_vs_market_pct` needs no new modelling here -- only the
market's de-vigged fair, which `_attach_sim_probability_edge` already computes
the same way every other sport does.

THE LINE IS IN THE KEY, AND A STALE DOCSTRING SAYS OTHERWISE.
`_nfl_card_prop_projection_index` states that "the artifact has no line field
and several rows share a market key with different lines, so a sim_projection
cannot be attributed to the line a card happens to show". **That was true until
2026-09-08 and is not true now.** `_nfl_prop_join_market_key` was changed that
day to include the line precisely because omitting it was "a live scoring bug
rather than a tidiness problem" (371 of 371 multi-line groups showing an
identical probability). The published artifact confirms it:

    receiving_yards::aj barner::24.5   sim_projection 0.5565
    receiving_yards::aj barner::25.5   sim_projection 0.5368
    receiving_yards::aj barner::27.5   sim_projection 0.4978

Three lines, three probabilities, one player. The cards' own two-segment
collapse remains correct for what the cards render (the stat, which is
line-independent); only the stated REASON is out of date. This module keys on
all three segments and is therefore line-exact.

WHAT THIS DOES NOT DO. It does not change the model, does not write an
artifact, and does not touch `nfl/props.py`. It reads what is already
published and stamps the projection contract every other sport already emits.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from syndicate.features.shared.wnba_game_projections import _attach_sim_probability_edge

#: Stamped on every projection this module writes, so a board row's model view
#: is attributable to THIS join rather than to the game-line join that shares
#: the same `projection` key. `projection_skill`/`detect_degenerate_projections`
#: both read `source`.
PROJECTION_SOURCE = "nfl_prop_model"


def _as_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if parsed != parsed or parsed in (float("inf"), float("-inf")):
        return None
    return parsed


@dataclass
class NflPropProjectionIndex:
    """Artifact sim rows keyed by `_nfl_prop_join_market_key`.

    `season`/`week`/`row_count`/`source` are carried so the coverage payload can
    say WHICH artifact answered. A week that resolves to the wrong number
    produces an empty join that is otherwise indistinguishable from "no model
    for these players", and that ambiguity is the one this dataclass exists to
    remove -- `#471`'s week self-pinning is a defect this repo has already had.
    """

    entries: dict[str, Mapping[str, Any]] = field(default_factory=dict)
    season: int | None = None
    week: int | None = None
    row_count: int = 0
    generated_at: str | None = None
    #: `"resolved"` when `latest_season`/`default_week` answered and their
    #: artifact had rows; `"artifact_scan"` when that answer was empty and the
    #: disk was asked instead. A fallback must never read as a clean resolution.
    resolution: str = "resolved"

    def get(self, key: str) -> Mapping[str, Any] | None:
        return self.entries.get(key)


def _season_candidates(resolved_season: Any, selected_date: Any) -> list[int]:
    """Seasons to probe, newest first.

    THE DATE'S OWN YEAR COMES FIRST, AND THAT IS THE WHOLE FIX. Measured
    2026-09-09 against the real published artifact: `latest_season()` answered
    **2025** while the artifact on disk was `nfl_prop_projections_2026_wk1.json`.
    `latest_season` derives from `week_summaries()`, which globs a DIFFERENT
    artifact family (SmartSim2 projections), so early in a season -- exactly
    when week 1 props exist and last season's projections still dominate the
    glob -- it lags by a year.

    A first draft of this scan probed only `[resolved, resolved - 1]` and
    therefore could never reach 2026 from a resolved 2025. It found nothing on
    the real data and the reachability run caught it; the season the DATE names
    is the signal that does not depend on which artifact family is on this disk.
    """
    candidates: list[int] = []
    text = str(selected_date or "").strip()
    if len(text) >= 4 and text[:4].isdigit():
        year = int(text[:4])
        # An NFL season spans a new year: January belongs to the PREVIOUS
        # season's playoffs, so a January date names `year - 1` first.
        month = int(text[5:7]) if len(text) >= 7 and text[5:7].isdigit() else 0
        candidates.extend([year - 1, year] if month and month <= 2 else [year, year - 1])
    if resolved_season is not None:
        candidates.extend([int(resolved_season), int(resolved_season) + 1, int(resolved_season) - 1])
    ordered: list[int] = []
    for value in candidates:
        if value not in ordered:
            ordered.append(value)
    return ordered


def _newest_available_artifact(
    reader: Any, resolved_season: Any, selected_date: Any
) -> tuple[int, int, list] | None:
    """The most recent (season, week) that HAS a populated prop artifact.

    Walks weeks downward rather than globbing, because the reader already owns
    root resolution (`nfl_prop_projection_artifact_path` prefers a root whose
    copy has ROWS, so a zero-row stub on one disk cannot shadow a real file on
    another) and reimplementing that here would be a second, weaker copy of it.

    Bounded and cheap: at most a handful of seasons x 22 weeks of a file probe
    that short-circuits on the first hit, and it runs only when the primary
    resolution already came back empty.
    """
    for candidate_season in _season_candidates(resolved_season, selected_date):
        for candidate_week in range(22, 0, -1):
            try:
                rows = reader(candidate_season, candidate_week)
            except Exception:
                continue
            if rows:
                return candidate_season, candidate_week, list(rows)
    return None


def _resolve_season_week(season: Any, week: Any) -> tuple[int | None, int | None]:
    """Explicit args win; otherwise ask the NFL module what today's week is."""
    resolved_season = None if season is None else int(season)
    resolved_week = None if week is None else int(week)
    if resolved_season is not None and resolved_week is not None:
        return resolved_season, resolved_week
    try:
        from syndicate.features.nfl.sources import default_week, latest_season

        if resolved_season is None:
            resolved_season = int(latest_season())
        if resolved_week is None:
            resolved_week = int(default_week(resolved_season))
    except Exception:
        return resolved_season, resolved_week
    return resolved_season, resolved_week


def load_nfl_prop_projections(
    selected_date: str | None = None, *, season: Any = None, week: Any = None
) -> NflPropProjectionIndex:
    """The published prop artifact for this season/week, keyed for the join.

    An absent artifact yields an EMPTY index rather than raising, and the caller
    reports that as a named reason. `selected_date` is accepted for signature
    parity with `load_nfl_game_projections` and is deliberately unused: NFL
    props are keyed by (season, week), and a date-keyed lookup would silently
    return nothing on every day of a week except one.
    """
    resolved_season, resolved_week = _resolve_season_week(season, week)
    index = NflPropProjectionIndex(season=resolved_season, week=resolved_week)
    try:
        from syndicate.features.nfl.props import read_nfl_prop_projection_artifact
    except Exception:
        return index

    rows = None
    if resolved_season is not None and resolved_week is not None:
        try:
            rows = read_nfl_prop_projection_artifact(resolved_season, resolved_week)
        except Exception:
            rows = None

    if not rows and season is None and week is None:
        # THE WEEK-PINNING FAILURE MODE, CLOSED RATHER THAN DOCUMENTED.
        #
        # `latest_season`/`default_week` resolve by probing for OTHER artifact
        # families (`week_summaries` globs projection files), so on a service
        # whose disk carries a different mix they can answer a season/week that
        # has no prop artifact -- and the join then returns nothing, which is
        # indistinguishable from "the model has no view on these players". This
        # repo has already shipped that exact defect once: `#471`, NFL week
        # self-pinning to 1.
        #
        # So when the resolved week yields nothing, ASK THE DISK what weeks
        # actually exist and take the newest populated one. The index reports
        # which it used, and `resolution` records that this branch ran, so a
        # fallback is never mistaken for a clean primary resolution.
        found = _newest_available_artifact(
            read_nfl_prop_projection_artifact, resolved_season, selected_date
        )
        if found is not None:
            found_season, found_week, rows = found
            index.season, index.week = found_season, found_week
            index.resolution = "artifact_scan"
    if not rows:
        # None ("cannot answer") and [] ("answered, nothing there") are both an
        # empty index HERE, but the caller distinguishes them by row_count == 0
        # against an artifact path that does or does not exist.
        return index
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        key = str(row.get("market") or "").strip()
        if not key:
            continue
        # `setdefault`, not assignment: the artifact is already unique per
        # (stat, player, line) by construction, and a duplicate would mean the
        # producer emitted two views of one bet. Keeping the FIRST is
        # arbitrary, so it is better that this never silently prefers the last.
        index.entries.setdefault(key, row)
    index.row_count = len(index.entries)
    index.generated_at = None
    return index


def attach_nfl_prop_projections(
    grid: Iterable[Mapping[str, Any]], index: NflPropProjectionIndex
) -> dict[str, Any]:
    """Stamp `projection` onto NFL player-prop rows. Returns coverage.

    EVERY REFUSAL IS COUNTED UNDER ITS OWN NAME. A prop row can fail this join
    for four unrelated reasons and they have four different fixes:

      `unsupported_market_rows`  the board's market label is not in
                                 `_NFL_PROP_MARKET_TO_STAT`. Measured on the
                                 served board 2026-09-09: 24 rows quoted as the
                                 RAW OddsAPI key `player_receptions` and 4 as
                                 `player_pass_tds`, against 1,394 rows carrying
                                 the display label the map expects. That is a
                                 producer inconsistency, and it is REPORTED
                                 rather than papered over with an alias -- an
                                 alias map here would hide which producer is
                                 emitting the wrong shape.
      `unmatched_key_rows`       the (stat, player, line) triple has no sim row.
                                 A player the model could not rate, or a line
                                 quoted after the artifact was built.
      `no_probability_rows`      matched, but `sim_projection` is absent. Never
                                 substituted with `projected_value`: that is the
                                 MEAN (256.2 passing yards), and putting it in a
                                 probability field is the exact `.get(key, 1.0)`
                                 failure `model_engine_standard.md` forbids.
      `no_line_rows`             a lined market quoted with no line. The key
                                 cannot be built, and `anytime_td` -- the one
                                 market that legitimately has no line -- is
                                 excluded from this counter.
    """
    rows_considered = 0
    rows_with_projection = 0
    unsupported_market_rows = 0
    unmatched_key_rows = 0
    no_probability_rows = 0
    no_line_rows = 0
    unsupported_markets: dict[str, int] = {}

    try:
        from syndicate.features.nfl.props import (
            _NFL_PROP_MARKET_TO_STAT,
            _nfl_prop_join_market_key,
        )
    except Exception:
        return {
            "supported": True,
            "rows_with_projection": 0,
            "error": "nfl prop join helpers unavailable",
        }

    # The map is keyed by the DISPLAY label the producer writes ("Receiving
    # Yards"). Matching casefolded as well costs nothing and makes the join
    # independent of a casing change in a producer this module does not own.
    stat_by_label = {str(k).strip().casefold(): v for k, v in _NFL_PROP_MARKET_TO_STAT.items()}

    for row in grid:
        if str(row.get("kind") or "") != "prop":
            continue
        rows_considered += 1
        label = str(row.get("market") or "").strip()
        stat = _NFL_PROP_MARKET_TO_STAT.get(label) or stat_by_label.get(label.casefold())
        if stat is None:
            unsupported_market_rows += 1
            unsupported_markets[label] = unsupported_markets.get(label, 0) + 1
            continue
        line = _as_float(row.get("line"))
        if line is None and stat != "anytime_td":
            no_line_rows += 1
            continue
        key = _nfl_prop_join_market_key(stat, str(row.get("player_name") or ""), line)
        entry = index.get(key)
        if entry is None:
            unmatched_key_rows += 1
            continue
        model_prob = _as_float(entry.get("sim_projection"))
        if model_prob is None:
            no_probability_rows += 1
            continue

        projection: dict[str, Any] = {
            # The projected STAT, for the display column. Distinct from the
            # probability below and never interchangeable with it.
            "projected": _as_float(entry.get("projected_value")),
            "side": "over",
            "basis": "nfl_prop_model_probability",
            "source": PROJECTION_SOURCE,
            # Carried through verbatim so a board row can be traced to the rate
            # that produced it. On 2026-09-09 all 1,140 artifact rows read
            # `nfl_prior_season_fallback` -- correct for week 1, and something a
            # reader must be able to SEE rather than infer.
            "sim_source": entry.get("sim_source"),
            "rate_source": entry.get("rate_source"),
            "player_team": entry.get("player_team"),
        }
        # Sets `model_prob_over`, `market_fair_prob_over` and
        # `edge_vs_market_pct` (or a named `edge_unavailable_reason`), applying
        # the same live-edge suppression every other sport goes through. Reused
        # rather than hand-rolled -- this would otherwise be the sixth copy of
        # one de-vig.
        _attach_sim_probability_edge(projection, row=row, model_prob=model_prob)
        row["projection"] = projection
        rows_with_projection += 1

    coverage: dict[str, Any] = {
        "supported": True,
        "rows_considered": rows_considered,
        "rows_with_projection": rows_with_projection,
        "unsupported_market_rows": unsupported_market_rows,
        "unmatched_key_rows": unmatched_key_rows,
        "no_probability_rows": no_probability_rows,
        "no_line_rows": no_line_rows,
        # WHICH artifact answered, so an empty join is attributable to a wrong
        # week rather than read as "the model has no view on these players".
        "artifact_season": index.season,
        "artifact_week": index.week,
        "artifact_rows": index.row_count,
    }
    if unsupported_markets:
        coverage["unsupported_markets"] = dict(
            sorted(unsupported_markets.items(), key=lambda kv: -kv[1])[:8]
        )
    if rows_considered:
        coverage["pct_projected"] = round(rows_with_projection / rows_considered * 100.0, 1)
    return coverage
