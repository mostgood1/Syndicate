"""SmartSim 2.0 projections joined onto the NCAAF Layer 1 board.

WHY THIS EXISTS. Layer 1 gained real NCAAF prices once the OddsAPI capture
landed (`#552`), but `_attach_projections_by_sport` had no `ncaaf` branch, so the
board reported `no_projection_source_for_sport` and the Proj/Edge columns stayed
dead. Prices without a model are an odds screen, not a betting board.

WHY IT IS NOT `nfl_game_projections` WITH A SPORT ARGUMENT. Two reasons, and
both are rules rather than taste:

  1. That module hardcodes `"source": "nfl_smartsim2"` in three places. Reusing
     it would stamp NCAAF rows with NFL's provenance -- `learnings.md`
     2026-08-21's FORBIDDEN rule, a value published under a name that describes a
     different quantity.
  2. Its caveat machinery (`skill_note`, `calibrated_total`) is gated on
     `is_preseason_profile`, i.e. NFL PRESEASON profiles only. An NCAAF profile
     falls straight through it, so reusing that path would have attached NCAAF
     projections with NO caveat at all -- the precise opposite of what the
     measurement below requires.

The generic parts ARE shared, not copied: `_no_vig_over_probability` is imported
from `prop_projections` exactly as the NFL module imports it.

THE CAVEAT IS THE POINT, NOT A DISCLAIMER. `football/pick_gate.py` is explicit
that suppressing PICKS "does NOT stop projections being generated, published, or
displayed -- the board still shows what the model thinks", because a gate that
blinds its own exit criterion never opens. So displaying is correct. But the
model is MEASURED as losing to the closing line, and a bare number in a column
headed PROJECTED has nowhere to say so. Same resolution NFL reached for its own
skill-less markets: keep the probability, blank the bare numeric, and travel with
the measurement.
"""

from __future__ import annotations

import csv
import logging
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from syndicate.features.ncaaf.oddsapi_lines import resolve_team
from syndicate.features.shared.probability_refusal import refuse_published_certainty

_LOGGER = logging.getLogger(__name__)

SOURCE = "ncaaf_smartsim2"

# Measured 2026-08-19 by `scripts/grade_football_playability.py` and recorded in
# `football/pick_gate.py`, whose docstring is the primary source for every number
# here. Clean and out-of-sample: 2023 SP+ ratings projected onto 2024 games, all
# 15 weeks, produced by the PRODUCTION generator and graded from the pick ledger
# with `graded_leak_status {'clean': 2236}`.
#
# UNLIKE NFL'S TABLE THIS IS NOT GATED ON A PROFILE. NFL's applies to preseason
# only; this measurement is of the production NCAAF model itself, so it applies
# to every projection this module emits.
NCAAF_MEASURED_SKILL: Mapping[str, Any] = {
    "sample_games": 2233,
    "seasons": "2023 SP+ -> 2024 games, clean out-of-sample",
    "margins": {
        "model_mae": 15.775,
        "market_mae": 12.212,
        "delta_mae": 3.563,
        "t_stat": 17.20,
        "verdict": (
            "loses to the closing line by 3.56 points of margin MAE at 17 sigma, "
            "and to the opening line by nearly as much"
        ),
    },
    "totals": {
        # Deliberately NOT a correlation: there isn't one. `state.md`
        # [ncaaf-margin-calibration] records that no model-vs-market accuracy
        # measurement exists for NCAAF totals AT ALL, which is why default-deny
        # applies to them on its own terms.
        "model_sd": 5.77,
        "market_sd": 3.46,
        "dispersion_ratio": 1.67,
        "verdict": (
            "never scored against the close, and 1.67x over-dispersed against it "
            "-- an inflated spread of projected totals crosses more lines by "
            "further, which reads as conviction"
        ),
    },
}


def skill_note(market: Any) -> dict[str, Any]:
    """What the backtest says this market's projection is actually worth.

    Always returns a note. There is no "this profile is fine" branch, because
    no NCAAF market has a recorded win -- and `pick_gate.py`'s central argument
    is that an absent measurement is indistinguishable from an unmeasured loss.
    """
    key = "totals" if str(market).strip().lower() == "totals" else "margins"
    block = NCAAF_MEASURED_SKILL[key]
    note = {
        "sample_games": NCAAF_MEASURED_SKILL["sample_games"],
        "seasons": NCAAF_MEASURED_SKILL["seasons"],
        "verdict": block["verdict"],
    }
    note.update({k: v for k, v in block.items() if k != "verdict"})
    return note


def _skill_reason(note: Mapping[str, Any]) -> str:
    """The measured verdict, phrased for a tooltip on the board."""
    return (
        f"margin model loses to the closing line by {note.get('delta_mae')} points "
        f"of MAE over {note.get('sample_games')} games (t={note.get('t_stat')})"
    )


def _norm(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _as_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


# The rating source is FBS-ONLY, and that is a coverage BOUNDARY rather than a
# gap. Measured 2026-08-31 over the whole of 2026 week 1: 99 scheduled games,
# 51 projections, and the split is total --
#
#     missing   48 of 48   (fbs, fcs)
#     projected 51 of 51   (fbs, fbs)
#
# `rating_source` on every row is
# `cfbd_sp_plus_2026[scale=10]+cfbd_ppa_season_2025_fallback_for_2026`, and
# CFBD's SP+ covers FBS. An FBS-vs-FCS fixture has no rating for one side, so it
# can never be projected by this model no matter how healthy the pipeline is.
#
# WHY THIS IS WORTH A STRING. Without it the board shows an FBS-vs-FCS row with
# no model and no explanation, which is indistinguishable from a failed
# generation — and the failure it most resembles is real and current (a peer
# session found the CFBD monthly quota exhausted the same week). I read
# `games_indexed: 1` against `scheduled_games: 39` and concluded the join was
# broken; it was not, and the one game that date was the only game that date.
# The next reader should not have to run that probe.
_RATED_CLASSIFICATION = "fbs"


def _unratable_reason(game: Mapping[str, Any]) -> str | None:
    """Why this scheduled fixture can never be projected, or None.

    Deliberately conservative: an ABSENT or unrecognised classification returns
    None rather than "unratable". An unknown must not be reported as a stated
    boundary — that would turn a data gap into a confident explanation, which is
    the failure this string exists to prevent.
    """
    home = str(game.get("homeClassification") or "").strip().lower()
    away = str(game.get("awayClassification") or "").strip().lower()
    if not home or not away:
        return None
    if home == _RATED_CLASSIFICATION and away == _RATED_CLASSIFICATION:
        return None
    other = away if home == _RATED_CLASSIFICATION else home
    if other == _RATED_CLASSIFICATION:
        return None
    side = "away" if home == _RATED_CLASSIFICATION else "home"
    return (
        f"the {side} team is {other.upper()}, and the rating source (CFBD SP+) "
        f"covers FBS only -- this fixture has no model by construction, not by failure"
    )


@dataclass
class NcaafGameProjectionIndex:
    """(kickoff date, home, away) -> one projection row.

    Keyed on CFBD canonical names; `lookup` resolves the board's names -- which
    come from OddsAPI and carry mascots ("TCU Horned Frogs") -- through the same
    validated resolver the line capture uses. Ambiguity yields a miss, never a
    guess: ~680 schools share mascots, so a wrong join puts another game's model
    on this card.
    """

    by_date_teams: dict[tuple[str, str, str], dict[str, Any]] = field(default_factory=dict)
    games: int = 0
    sources: list[str] = field(default_factory=list)
    rows_unresolved_team: int = 0
    # (date, home, away) -> why this SCHEDULED fixture can never carry a
    # projection. Populated from the schedule's own classifications, so a board
    # row with no model can say WHICH kind of absence it is. See
    # `_unratable_reason`.
    unratable: dict[tuple[str, str, str], str] = field(default_factory=dict)
    unratable_games: int = 0

    def unratable_reason(self, game_date: str, home: Any, away: Any) -> str | None:
        """Why this fixture has no projection, or None if it is not that case.

        Resolved through the SAME `resolve_team` path as `lookup`, so a fixture
        cannot be called unratable on a name the lookup would have matched.
        """
        date_key = str(game_date or "")[:10]
        if not date_key or not self.unratable:
            return None
        home_canonical = resolve_team(home)
        away_canonical = resolve_team(away)
        if not (home_canonical and away_canonical):
            return None
        return self.unratable.get((date_key, _norm(home_canonical), _norm(away_canonical)))

    def lookup(self, game_date: str, home: Any, away: Any) -> dict[str, Any] | None:
        date_key = str(game_date or "")[:10]
        if not date_key:
            return None
        home_canonical = resolve_team(home)
        away_canonical = resolve_team(away)
        if not (home_canonical and away_canonical):
            return None
        return self.by_date_teams.get((date_key, _norm(home_canonical), _norm(away_canonical)))


def _season_for_date(date_str: str) -> int | None:
    """The college football season a calendar date belongs to.

    A season is named for the calendar year it STARTS in, and runs into January
    (bowls, playoff). So January dates belong to the previous season -- getting
    that wrong in the other direction would look for a week that does not exist
    and silently return no projections.
    """
    text = str(date_str or "").strip()
    if len(text) < 7:
        return None
    try:
        year, month = int(text[:4]), int(text[5:7])
    except ValueError:
        return None
    return year - 1 if month <= 2 else year


def load_ncaaf_game_projections(selected_date: str) -> NcaafGameProjectionIndex:
    """Every projection whose game kicks off on `selected_date`.

    Resolves the WEEK from the schedule rather than from the date, because NCAAF
    weeks are not calendar windows -- 2026 week 1 spans 08-29 to 09-07 -- so a
    week guessed from a date would miss most of a slate.
    """
    index = NcaafGameProjectionIndex()
    date_key = str(selected_date or "")[:10]
    season = _season_for_date(date_key)
    if not season:
        return index

    try:
        from syndicate.features.football.sim_engine.smartsim2.historical_truth.ncaaf_historical_loader import (
            load_games_season,
        )

        schedule = load_games_season(season)
    except Exception:
        _LOGGER.exception("NCAAF_PROJECTION_SCHEDULE_FAILURE season=%s", season)
        return index

    # date -> the weeks that have a game on it, and (home, away) -> date.
    weeks: set[int] = set()
    kickoff: dict[tuple[str, str], str] = {}
    for game in schedule:
        if not isinstance(game, dict):
            continue
        game_date = str(game.get("startDate") or "").split("T")[0]
        if game_date != date_key:
            continue
        week = game.get("week")
        if isinstance(week, int):
            weeks.add(week)
        home = str(game.get("homeTeam") or "").strip()
        away = str(game.get("awayTeam") or "").strip()
        if home and away:
            kickoff[(_norm(home), _norm(away))] = game_date
            reason = _unratable_reason(game)
            if reason:
                index.unratable[(game_date, _norm(home), _norm(away))] = reason
    index.unratable_games = len(index.unratable)
    if not weeks:
        return index

    from syndicate.features.ncaaf.sources import default_ncaaf_source_root

    data_root = default_ncaaf_source_root() / "data"
    for week in sorted(weeks):
        path = data_root / f"smartsim2_projections_{season}_wk{week}.csv"
        if not path.is_file():
            continue
        try:
            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))
        except Exception:
            _LOGGER.exception("NCAAF_PROJECTION_READ_FAILURE path=%s", path)
            continue
        index.sources.append(str(path))
        for row in rows:
            home = str(row.get("home_team") or "").strip()
            away = str(row.get("away_team") or "").strip()
            if not (home and away):
                continue
            game_date = kickoff.get((_norm(home), _norm(away)))
            if game_date is None:
                # The projection is for a game that does not kick off on this
                # date. Not an error -- a week spans many days.
                continue
            index.by_date_teams[(game_date, _norm(home), _norm(away))] = {
                "home_team": home,
                "away_team": away,
                "margin_mean": _as_float(row.get("margin_mean")),
                "margin_stdev": _as_float(row.get("margin_stdev")),
                "total_mean": _as_float(row.get("total_mean")),
                "total_stdev": _as_float(row.get("total_stdev")),
                "home_win_rate": _as_float(row.get("home_win_rate")),
                "profile": row.get("profile_name"),
                "generated_at": row.get("generated_at"),
            }
    index.games = len(index.by_date_teams)
    return index


def attach_ncaaf_game_projections(
    grid: Iterable[Mapping[str, Any]],
    index: NcaafGameProjectionIndex,
    *,
    selected_date: str | None = None,
) -> dict[str, Any]:
    """Stamp `projection` onto NCAAF full-game h2h/spreads/totals rows.

    Mirrors the shape `nfl_game_projections` established, including its central
    judgement: **a bare numeric in a column headed PROJECTED cannot carry a
    caveat, so where the model has no measured skill the honest value is none.**
    Every projection here travels with `model_skill`, because no NCAAF market has
    a recorded win.

    `selected_date` SCOPES THE COUNTERS, and without it they are not
    interpretable. `load_ncaaf_game_projections` builds a DATE-SCOPED index, but
    `_attach_projections_over_window` calls this once per date in NCAAF's 7-day
    slate window passing the SAME unfiltered grid every time -- so a row is
    counted in `considered` on all seven passes while it can only ever match the
    one date equal to its own kickoff. The window wrapper then SUMS
    `rows_considered`, inflating the denominator while `rows_with_projection`
    stays honest.

    Measured 2026-09-03: the log read `considered=3625 projected=336` (9.3%) and
    `3625 / 5 non-empty dates = 725`, exactly the shared grid's size. Re-derived
    per date from the served board it is **327 of 692 (~47%)**, matching the
    model's documented FBS-vs-FBS boundary. That 9.3% was reported up the chain
    as a production outage and it was a counting artefact.

    ATTACHMENT IS UNCHANGED by this: a skipped row would have failed
    `index.lookup` on that date anyway. Only the counters move.
    """
    from syndicate.features.shared.prop_projections import _no_vig_over_probability

    considered = attached = unmatched = non_full_segment = 0
    unratable_rows = 0

    for row in grid:
        if str(row.get("kind") or "") == "prop":
            continue
        market = str(row.get("market") or "").strip().lower()
        if market not in {"h2h", "spreads", "totals"}:
            continue
        # BEFORE `considered`, deliberately: a row belonging to another date is
        # not a miss on THIS date, and counting it as one is what made a healthy
        # join read as a near-total failure.
        if selected_date:
            row_date = str(row.get("commence_time") or "")[:10]
            if row_date and row_date != str(selected_date)[:10]:
                continue
        considered += 1
        if str(row.get("segment") or "full").strip().lower() not in {"", "full"}:
            # margin/total means are full-game; a quarter market is a different bet.
            non_full_segment += 1
            continue
        entry = index.lookup(str(row.get("commence_time") or "")[:10], row.get("home_team"), row.get("away_team"))
        if entry is None:
            # SAY WHICH KIND OF ABSENCE THIS IS. An FBS-vs-FCS fixture can never
            # carry a projection (see `_unratable_reason`); a row that is
            # unmatched for any OTHER reason is a real miss worth chasing.
            # Counting them together is what makes a healthy boundary look like
            # a broken pipeline.
            #
            # The reason goes on the ROW, NOT inside a `projection` dict, and
            # that placement is load-bearing: `layer1_board` counts any
            # `projection` dict as `rows_with_projection`, so stamping one here
            # would inflate coverage with rows that have no model at all --
            # improving the number that made this look broken while making the
            # board less true. `projection_unavailable_reason` (this file, and
            # NFL) stays what it is: a reason INSIDE a projection that exists.
            reason = index.unratable_reason(
                str(row.get("commence_time") or "")[:10], row.get("home_team"), row.get("away_team")
            )
            if reason:
                row["projection_absent_reason"] = reason  # type: ignore[index]
                unratable_rows += 1
            else:
                unmatched += 1
            continue

        projection: dict[str, Any] | None = None

        if market == "h2h":
            prob = entry.get("home_win_rate")
            if prob is not None:
                note = skill_note("margins")
                projection = {
                    # The probability STAYS. It has somewhere to carry its
                    # caveat, and `pick_gate.py` needs the model visible for the
                    # measurement that would lift the gate.
                    "model_prob_over": round(float(prob), 4),
                    "side": str(row.get("home_team") or "").strip(),
                    # Blanked for the same reason NFL blanks it: the home win
                    # rate derives from the margin model this note condemns, and
                    # `projected` lands in a bare numeric column.
                    "projected": None,
                    "basis": "smartsim2_home_win_rate",
                    "source": SOURCE,
                    "generated_at": entry.get("generated_at"),
                    "model_skill": note,
                    "projection_unavailable_reason": _skill_reason(note),
                    # THE ONLY CHANNEL A HUMAN CAN ACTUALLY READ, and picking the
                    # right field name is the whole difference between a stated
                    # caveat and a silent one. `layer1_board.html` renders the
                    # EDGE cell as "·*" with a hover title when
                    # `edge_unavailable_reason` is set; the PROJ cell (line
                    # ~1012) has no tooltip channel at all, and `model_skill` is
                    # rendered nowhere. So a reason placed anywhere else is
                    # payload-only -- the same "stated refusal that nobody could
                    # read" `state.md` records for the frozen-chip corrector.
                    "edge_unavailable_reason": _skill_reason(note),
                }
        elif market == "totals":
            mean = entry.get("total_mean")
            stdev = entry.get("total_stdev")
            line = _as_float(row.get("line"))
            if mean is not None:
                note = skill_note("totals")
                projection = {
                    # The MEAN is kept: it is the model's own statement about the
                    # game and is not itself inflated. What is inflated is the
                    # EDGE derived from it, which is why the dispersion ratio
                    # travels alongside and the edge is suppressed below.
                    "projected": round(float(mean), 3),
                    "side": "over",
                    "basis": "smartsim2_total_mean",
                    "source": SOURCE,
                    "generated_at": entry.get("generated_at"),
                    "model_prob_over": None,
                    "model_skill": note,
                }
                if stdev is None or stdev <= 0 or line is None:
                    projection["edge_vs_market_pct"] = None
                    projection["edge_unavailable_reason"] = (
                        "no over probability: the sim reported no usable total_stdev"
                        if line is not None
                        else "no over probability: the row carries no line to price against"
                    )
                else:
                    # NO EDGE PERCENTAGE ON TOTALS, DELIBERATELY.
                    #
                    # The model's total SD is 5.77 against the market's 3.46
                    # (1.67x). Pricing a line against an over-dispersed
                    # distribution is exactly what `state.md` calls manufacturing
                    # an edge: the wider the model's spread, the further past
                    # each line it lands, and the more confident the number
                    # looks. Publishing that percentage would be selling
                    # dispersion as insight.
                    #
                    # `edge_vs_line` below is still computed -- a derived
                    # diagnostic that travels with `model_skill`, so anyone
                    # auditing this can see the input.
                    projection["edge_vs_market_pct"] = None
                    projection["edge_unavailable_reason"] = (
                        f"totals are {note.get('dispersion_ratio')}x over-dispersed against the "
                        f"market and were never scored against the close"
                    )
                    market_fair = _no_vig_over_probability(row)
                    if market_fair is not None:
                        projection["market_fair_prob_over"] = round(float(market_fair), 4)
                if line is not None:
                    projection["edge_vs_line"] = round(float(mean) - line, 3)
        else:  # spreads
            mean = entry.get("margin_mean")
            line = _as_float(row.get("line"))
            if mean is not None:
                note = skill_note("margins")
                projection = {
                    "projected": None,
                    "side": str(row.get("home_team") or "").strip(),
                    "basis": "smartsim2_margin_mean",
                    "source": SOURCE,
                    "generated_at": entry.get("generated_at"),
                    "model_prob_over": None,
                    "edge_vs_market_pct": None,
                    "model_skill": note,
                    "projection_unavailable_reason": _skill_reason(note),
                    # See the h2h branch: this is the field the board can show.
                    "edge_unavailable_reason": _skill_reason(note),
                    # Inherited verbatim from the NFL module's finding: the row's
                    # `line` does not state which side it belongs to, and a
                    # guessed sign inverts the edge while looking plausible.
                    "probability_unavailable_reason": "spread row does not state which side its line belongs to",
                }
                if line is not None:
                    projection["edge_vs_line"] = round(float(mean) - line, 3)

        if projection is not None:
            row["projection"] = refuse_published_certainty(projection)  # type: ignore[index]
            attached += 1

    return {
        "supported": True,
        "rows_considered": considered,
        "rows_with_projection": attached,
        # `rows_unmatched` now means "unmatched for a reason we do NOT know",
        # which is the only population worth investigating. It used to include
        # every FBS-vs-FCS row and was therefore ~half the board on an opener
        # weekend.
        "rows_unmatched": unmatched,
        "rows_unratable_opponent": unratable_rows,
        "rows_non_full_segment": non_full_segment,
        "games_indexed": index.games,
        # Scheduled fixtures on this date that no model can cover. Reported
        # beside `games_indexed` so the pair reads as a RATE: measured over 2026
        # week 1, 51 of 99 scheduled games are rateable and 51 of 51 of those
        # are projected.
        "games_unratable_opponent": index.unratable_games,
        "sources": index.sources,
        # Stated on every payload, not only when something is wrong: a consumer
        # that reads `rows_with_projection` without it would treat these as
        # ordinary edges.
        "model_skill": {
            "margins": skill_note("margins"),
            "totals": skill_note("totals"),
        },
    }
