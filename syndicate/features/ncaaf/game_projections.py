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
blinds its own exit criterion never opens. So displaying is correct. The model
is MEASURED as losing to the closing line, and that measurement travels on every
projection as `model_skill`.

UNTIL 2026-09-18 THIS MODULE ALSO BLANKED: spreads published `projected: None`
and all three markets published no edge. The user reversed that ("they should be
shown, period ... every game/prop is its own entity"; "Publish,
skill-discounted"), so every market now carries its projection, probability and
edge, and the measured loss acts through `layer2_board._apply_skill_reliability`
(ranking) while `portfolio_commit` keeps NCAAF stakes on the market-fair basis.
See the block above `_normal_prob_above`.
"""

from __future__ import annotations

import csv
import logging
import math
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
        # THE 2026 SEASON AGAINST REAL CLOSES `[2026-09-14, lane
        # accuracy-assessment-0914]`: weeks 1-2, 100 FBS games, inputs verified
        # pregame (SP+ unchanged 09-05..09-14), bootstrap over games. Same sign,
        # smaller gap -- the 2024 +3.563 lies OUTSIDE the 2026 CI, so the row
        # quotes 2026 and keeps the backtest beside it. Margins are 1.28x as
        # spread as the close, not calibrated.
        "sample_games_2026": 100,
        "delta_mae_2026": 1.75,
        "ci95_2026": (0.45, 3.06),
        "dispersion_ratio_2026": 1.28,
        # For Layer 2 scoring (`measured_market_skill.skill_reliability`): the 2026 CI's
        # lower bound over the 2026 close's MAE, 0.45 / 12.102.
        "established_loss_rel": 0.03718,
        "verdict": (
            "loses to the closing line: 2026 margin MAE +1.75 [+0.45, +3.06] over "
            "100 games (2024 backtest +3.56 over 2,233)"
        ),
    },
    "totals": {
        # FIRST SCORE AGAINST THE CLOSE `[2026-09-14, lane accuracy-assessment-0914]`.
        # Until then this block said "never scored against the close" and carried
        # only the 2026-08-19 dispersion reading (SD 5.77 vs 3.46 = 1.67x). Measured
        # over 100 FBS games in 2026 weeks 1-2 it LOSES, and the dispersion is worse
        # than recorded. Correlation with actual totals is 0.14; shrinking to the
        # mean only reaches parity. Still deliberately not a correlation field.
        "sample_games": 100,
        "seasons": "2026 weeks 1-2 vs the close, inputs verified pregame",
        "model_mae": 14.374,
        "market_mae": 11.51,
        "delta_mae": 2.864,
        "ci95": (1.119, 4.594),
        "dispersion_ratio": 2.48,
        "bias_points": 4.6,
        # For Layer 2 scoring: the CI's lower bound over the close's MAE, 1.119 / 11.51.
        "established_loss_rel": 0.09722,
        "verdict": (
            "loses to the closing line by 2.86 points of total MAE [+1.12, +4.59] "
            "over 100 games; 2.48x over-dispersed and 4.6 points high"
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
    # A block that was measured on its own sample says so; otherwise it inherits
    # the backtest's. Totals were scored on a different population (2026 closes)
    # from margins (the 2024 backtest), and one shared `sample_games` would put the
    # wrong denominator on one of them.
    note = {
        "sample_games": block.get("sample_games", NCAAF_MEASURED_SKILL["sample_games"]),
        "seasons": block.get("seasons", NCAAF_MEASURED_SKILL["seasons"]),
        "verdict": block["verdict"],
    }
    note.update({k: v for k, v in block.items() if k not in ("verdict", "sample_games", "seasons")})
    return note


def _skill_reason(note: Mapping[str, Any]) -> str:
    """The measured verdict, phrased for a tooltip on the board.

    Quotes the 2026 season when the note carries it: the 2024 backtest's gap lies
    outside the 2026 CI, so leading with it would overstate the current loss.
    """
    if note.get("delta_mae_2026") is not None:
        return (
            f"margin model loses to the closing line by {note.get('delta_mae_2026')} points "
            f"of MAE over {note.get('sample_games_2026')} games this season "
            f"(2024 backtest: {note.get('delta_mae')} over {note.get('sample_games')})"
        )
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


# HOW FAR A KICKOFF DATE MAY DRIFT BETWEEN THE SCHEDULE AND THE BOARD. One day.
#
# The date on the index comes from the CFBD schedule; the date on the row comes
# from OddsAPI's `commence_time`. They disagree for ordinary reasons, and the
# join used to demand byte-equality anyway. Measured 2026-09-18 on the served
# board: North Texas @ Texas State sat at `2026-09-20T02:00Z` in the schedule
# copy the join reads (git-tracked, written 2026-08-01, and reset to that copy by
# every deploy) while the board had `2026-09-19T16:00Z` -- the kickoff was set
# after the copy was taken, and the game carried no model.
#
# ONE day and not "any day of the week", because a week spans ten days and a
# projection must not leak onto a different day's row -- `test_lookup_is_date_scoped`
# pins a 7-day gap as a miss, and that still holds. A team pair plays once per
# regular-season week, so +/-1 day cannot confuse two different games.
_KICKOFF_DATE_TOLERANCE_DAYS = 1


def _shift_date(date_key: str, days: int) -> str | None:
    from datetime import date, timedelta

    try:
        return (date.fromisoformat(date_key) + timedelta(days=days)).isoformat()
    except ValueError:
        return None


def _date_window(date_key: str) -> list[str]:
    """`date_key` first, then each neighbour within the tolerance."""
    out = [date_key]
    for offset in range(1, _KICKOFF_DATE_TOLERANCE_DAYS + 1):
        for signed in (-offset, offset):
            shifted = _shift_date(date_key, signed)
            if shifted:
                out.append(shifted)
    return out


def _oriented(entry: Mapping[str, Any], *, flipped: bool, date_shifted: bool) -> dict[str, Any]:
    """The entry restated in the BOARD ROW's home/away frame.

    NEUTRAL-SITE GAMES HAVE A NOMINAL HOME, AND THE TWO FEEDS PICK DIFFERENTLY.
    Measured 2026-09-18: CFBD lists `Arizona State @ Kansas` (Wembley Stadium,
    `neutralSite: true`) and `West Virginia @ Virginia` (Bank of America Stadium,
    `neutralSite: true`); OddsAPI lists both the other way round. The lookup was
    keyed on the exact (home, away) order, so both FBS games carried no model.

    Every home-relative number flips; the total does not. The projection's own
    HFA stays whatever the generator applied for CFBD's reading of the venue --
    that is the model's statement, and restating its frame does not change it.
    """
    out = dict(entry)
    if flipped:
        margin = _as_float(entry.get("margin_mean"))
        win = _as_float(entry.get("home_win_rate"))
        out["margin_mean"] = -margin if margin is not None else None
        out["home_win_rate"] = (1.0 - win) if win is not None else None
        out["home_team"], out["away_team"] = entry.get("away_team"), entry.get("home_team")
    out["orientation_flipped"] = bool(flipped)
    out["kickoff_date_shifted"] = bool(date_shifted)
    return out


@dataclass
class NcaafGameProjectionIndex:
    """(schedule kickoff date, home, away) -> one projection row.

    Keyed on CFBD canonical names in CFBD's orientation; `lookup` resolves the
    board's names -- which come from OddsAPI and carry mascots ("TCU Horned
    Frogs") -- through the same validated resolver the line capture uses, and
    returns the entry restated in the BOARD's frame. Ambiguity yields a miss,
    never a guess: ~680 schools share mascots, so a wrong join puts another
    game's model on this card.

    `undated` holds projections for games the schedule copy does not contain at
    all (added after the copy was taken). Keyed on the pair alone and consulted
    last: the generator on refresh-worker refreshes its schedule before it
    writes the CSV, while this join reads whatever copy this service holds.
    """

    by_date_teams: dict[tuple[str, str, str], dict[str, Any]] = field(default_factory=dict)
    undated: dict[tuple[str, str], dict[str, Any]] = field(default_factory=dict)
    games: int = 0
    sources: list[str] = field(default_factory=list)
    rows_unresolved_team: int = 0
    # (date, home, away) -> why this SCHEDULED fixture can never carry a
    # projection. Populated from the schedule's own classifications, so a board
    # row with no model can say WHICH kind of absence it is. See
    # `_unratable_reason`.
    unratable: dict[tuple[str, str, str], str] = field(default_factory=dict)
    unratable_games: int = 0

    @staticmethod
    def _find(table: Mapping[tuple[str, str, str], Any], date_key: str, home: str, away: str):
        """(value, flipped, date_shifted) for the first key in the window, or None.

        Exact date and orientation first, so a normal game can never be answered
        by a neighbour.
        """
        for position, candidate in enumerate(_date_window(date_key)):
            for key_home, key_away, flipped in ((home, away, False), (away, home, True)):
                value = table.get((candidate, key_home, key_away))
                if value is not None:
                    return value, flipped, position > 0
        return None

    def unratable_reason(self, game_date: str, home: Any, away: Any) -> str | None:
        """Why this fixture has no projection, or None if it is not that case.

        Resolved through the SAME `resolve_team` path and the same date and
        orientation tolerance as `lookup`, so a fixture cannot be called
        unratable on a name or date the lookup would have matched.
        """
        date_key = str(game_date or "")[:10]
        if not date_key or not self.unratable:
            return None
        home_canonical = resolve_team(home)
        away_canonical = resolve_team(away)
        if not (home_canonical and away_canonical):
            return None
        found = self._find(self.unratable, date_key, _norm(home_canonical), _norm(away_canonical))
        return found[0] if found else None

    def lookup(self, game_date: str, home: Any, away: Any) -> dict[str, Any] | None:
        date_key = str(game_date or "")[:10]
        if not date_key:
            return None
        home_canonical = resolve_team(home)
        away_canonical = resolve_team(away)
        if not (home_canonical and away_canonical):
            return None
        home_key, away_key = _norm(home_canonical), _norm(away_canonical)
        found = self._find(self.by_date_teams, date_key, home_key, away_key)
        if found is not None:
            entry, flipped, shifted = found
            return _oriented(entry, flipped=flipped, date_shifted=shifted)
        for key_home, key_away, flipped in ((home_key, away_key, False), (away_key, home_key, True)):
            entry = self.undated.get((key_home, key_away))
            if entry is not None:
                return _oriented(entry, flipped=flipped, date_shifted=False)
        return None


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

    # The weeks with a game on this date or a neighbour within the tolerance,
    # and (home, away) -> its OWN schedule date for every game in that window.
    # Keyed on the schedule's date rather than this one so `lookup` can prefer
    # an exact-date match and only then fall back to a neighbour.
    window = set(_date_window(date_key))
    weeks: set[int] = set()
    kickoff: dict[tuple[str, str], str] = {}
    # Every scheduled pair in the season, either orientation. A CSV row whose
    # pair is scheduled OUTSIDE this window is another date's game; one whose
    # pair is not scheduled at all is a game this copy of the schedule predates.
    scheduled_pairs: set[frozenset[str]] = set()
    for game in schedule:
        if not isinstance(game, dict):
            continue
        home = str(game.get("homeTeam") or "").strip()
        away = str(game.get("awayTeam") or "").strip()
        if home and away:
            scheduled_pairs.add(frozenset((_norm(home), _norm(away))))
        game_date = str(game.get("startDate") or "").split("T")[0]
        if game_date not in window:
            continue
        week = game.get("week")
        if isinstance(week, int):
            weeks.add(week)
        if home and away:
            kickoff[(_norm(home), _norm(away))] = game_date
            reason = _unratable_reason(game)
            if reason:
                index.unratable[(game_date, _norm(home), _norm(away))] = reason
    # A RATE, so it stays scoped to THIS date: the window's neighbours are here
    # only so a moved kickoff can still be explained.
    index.unratable_games = sum(1 for key in index.unratable if key[0] == date_key)
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
            entry = {
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
            home_key, away_key = _norm(home), _norm(away)
            game_date = kickoff.get((home_key, away_key))
            if game_date is None:
                # The CSV and the schedule can disagree on orientation for the
                # same neutral-site reason `_oriented` documents; store the
                # entry in the CSV's own frame under the schedule's date.
                game_date = kickoff.get((away_key, home_key))
            if game_date is not None:
                index.by_date_teams[(game_date, home_key, away_key)] = entry
            elif frozenset((home_key, away_key)) not in scheduled_pairs:
                # Not in this copy of the schedule AT ALL. The CSV is week-scoped
                # and a pair plays once a week, so the pair alone identifies it.
                index.undated[(home_key, away_key)] = entry
            # else: scheduled on another date outside the window. Not an error --
            # a week spans many days.
    # Scoped to THIS date, as before, so `games_indexed` beside
    # `games_unratable_opponent` still reads as a per-date rate. Undated entries
    # count because they may be on this date and nothing says otherwise.
    index.games = sum(1 for key in index.by_date_teams if key[0] == date_key) + len(index.undated)
    return index



# ---------------------------------------------------------------------------
# PER-ROW PROJECTION AND PRICE, EVERY MARKET. `[2026-09-18, user decisions]`
#
# "they should be shown, period ... we shouldnt be hiding anything globally,
# every game/prop is its own entity" and "Publish, skill-discounted". Until this
# date every NCAAF spread row published `projected: None`, and every NCAAF row
# of all three markets published `edge_vs_market_pct: None`, because the model
# is MEASURED as losing to the close. That was a sport-wide suppression: on the
# served board 2026-09-18 14:55Z, 0 of 938 NCAAF rows carried `model_edge_pct`
# and 154 FBS spread rows read "no sim view" while the sim held a margin.
#
# THE MEASUREMENT STILL TRAVELS, AND IT STILL BITES -- where the user put it.
# Every projection carries `model_skill` (the loss to the close, with its CI).
# `layer2_board._apply_skill_reliability` reads that note's
# `established_loss_rel` and demotes the row's SCORE by it, so a losing model
# ranks lower rather than being hidden. STAKE SIZE is a separate decision:
# `portfolio_commit` keeps sizing NCAAF on the market-fair basis ("Show edges,
# size on price", 2026-09-18), so publishing an edge here does not put money
# behind a model that loses to the close.
#
# PROBABILITIES ARE NORMAL, off the sim's own mean and SD. Both are the
# generator's outputs (`margin_stdev`, `total_stdev`); the dispersion ratios in
# `NCAAF_MEASURED_SKILL` (margins 1.28x, totals 2.48x the close's) say those SDs
# are too wide, which pulls probabilities TOWARD 0.5 -- the conservative
# direction for an edge. Not corrected here: that is engine work under
# `model_engine_standard.md`, not a join.
# ---------------------------------------------------------------------------


def _normal_prob_above(threshold: float | None, mean: float | None, stdev: float | None) -> float | None:
    """P(X > threshold) for X ~ Normal(mean, stdev), or None without a usable SD."""
    if threshold is None or mean is None or stdev is None or not stdev > 0:
        return None
    return 0.5 * math.erfc(((threshold - mean) / stdev) / math.sqrt(2.0))


def _game_projection(row: Mapping[str, Any], market: str, entry: Mapping[str, Any]) -> dict[str, Any] | None:
    """The sim's view of one full-game row, in the ROW's home/away frame.

    `entry` has already been restated in the board's frame by `lookup`
    (`_oriented`), so `home_win_rate` and `margin_mean` are the board home
    team's. `model_prob_over` follows the grid convention every game producer
    uses (`prop_projections.attach_projections`): the HOME side for h2h and
    spreads, the OVER for totals.
    """
    line = _as_float(row.get("line"))
    home_name = str(row.get("home_team") or "").strip()
    common: dict[str, Any] = {
        "source": SOURCE,
        "generated_at": entry.get("generated_at"),
    }
    if entry.get("orientation_flipped"):
        # Said on the row, so a reader auditing a neutral-site game can see the
        # model's home was the other team and every number was restated.
        common["orientation_flipped"] = True
    if entry.get("kickoff_date_shifted"):
        common["kickoff_date_shifted"] = True

    if market == "h2h":
        prob = _as_float(entry.get("home_win_rate"))
        if prob is None:
            return None
        return {
            **common,
            "model_prob_over": round(prob, 4),
            "side": home_name,
            # A win probability is not a projected STAT; the board shows it in
            # its Win% column from `model_prob_over`.
            "projected": None,
            "basis": "smartsim2_home_win_rate",
            "model_skill": skill_note("margins"),
        }

    if market == "totals":
        mean = _as_float(entry.get("total_mean"))
        if mean is None:
            return None
        prob = _normal_prob_above(line, mean, _as_float(entry.get("total_stdev")))
        projection = {
            **common,
            "projected": round(mean, 3),
            "side": "over",
            "basis": "smartsim2_total_normal",
            "model_prob_over": round(prob, 4) if prob is not None else None,
            "model_skill": skill_note("totals"),
        }
        if line is not None:
            projection["edge_vs_line"] = round(mean - line, 3)
        if prob is None:
            projection["probability_unavailable_reason"] = (
                "no over probability: the sim reported no usable total_stdev"
                if line is not None
                else "no over probability: the row carries no line to price against"
            )
        return projection

    # spreads
    mean = _as_float(entry.get("margin_mean"))
    if mean is None:
        return None
    # THE LINE ARRIVES IN THE AWAY FRAME (`book_grid._canonical_line`, `#262`).
    # With L the away team's line, home covers when (home - away) > L -- the
    # same algebra `prop_projections.project_game_market` states for MLB's
    # spreads, where negating it once inverted every home probability.
    prob = _normal_prob_above(line, mean, _as_float(entry.get("margin_stdev")))
    projection = {
        **common,
        # HOME MINUS AWAY, the frame MLB's and NFL's spread rows already publish.
        "projected": round(mean, 3),
        "side": home_name,
        "basis": "smartsim2_margin_normal",
        "model_prob_over": round(prob, 4) if prob is not None else None,
        "model_skill": skill_note("margins"),
    }
    if line is not None:
        projection["edge_vs_line"] = round(mean - line, 3)
    if prob is None:
        projection["probability_unavailable_reason"] = (
            "no cover probability: the sim reported no usable margin_stdev"
            if line is not None
            else "no cover probability: the row carries no line to price against"
        )
    return projection


def _price_against_market(row: Mapping[str, Any], projection: dict[str, Any], no_vig_over) -> None:
    """Stamp the market fair and the edge -- or the NAMED reason there is none.

    Same three outcomes as `prop_projections.attach_projections`, including its
    live rule: a PREGAME projection priced against a market that has watched
    the game is not an edge, it is the score (`live_edge_policy`, `#340`).
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
        projection["edge_unavailable_reason"] = projection.get("probability_unavailable_reason") or "no model probability"
    else:
        projection["edge_vs_market_pct"] = None
        projection["edge_unavailable_reason"] = "no no-vig fair: the market is not quoted on both sides"


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

        projection = _game_projection(row, market, entry)
        if projection is not None:
            _price_against_market(row, projection, _no_vig_over_probability)
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
