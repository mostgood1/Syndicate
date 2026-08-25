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
    grid: Iterable[Mapping[str, Any]], index: NcaafGameProjectionIndex
) -> dict[str, Any]:
    """Stamp `projection` onto NCAAF full-game h2h/spreads/totals rows.

    Mirrors the shape `nfl_game_projections` established, including its central
    judgement: **a bare numeric in a column headed PROJECTED cannot carry a
    caveat, so where the model has no measured skill the honest value is none.**
    Every projection here travels with `model_skill`, because no NCAAF market has
    a recorded win.
    """
    from syndicate.features.shared.prop_projections import _no_vig_over_probability

    considered = attached = unmatched = non_full_segment = 0

    for row in grid:
        if str(row.get("kind") or "") == "prop":
            continue
        market = str(row.get("market") or "").strip().lower()
        if market not in {"h2h", "spreads", "totals"}:
            continue
        considered += 1
        if str(row.get("segment") or "full").strip().lower() not in {"", "full"}:
            # margin/total means are full-game; a quarter market is a different bet.
            non_full_segment += 1
            continue
        entry = index.lookup(str(row.get("commence_time") or "")[:10], row.get("home_team"), row.get("away_team"))
        if entry is None:
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
            row["projection"] = projection  # type: ignore[index]
            attached += 1

    return {
        "supported": True,
        "rows_considered": considered,
        "rows_with_projection": attached,
        "rows_unmatched": unmatched,
        "rows_non_full_segment": non_full_segment,
        "games_indexed": index.games,
        "sources": index.sources,
        # Stated on every payload, not only when something is wrong: a consumer
        # that reads `rows_with_projection` without it would treat these as
        # ordinary edges.
        "model_skill": {
            "margins": skill_note("margins"),
            "totals": skill_note("totals"),
        },
    }
