"""Real per-player game-log aggregation from nflverse play-by-play.

This is NFL's equivalent of two MLB pieces at once: the rolling rate
computation `scripts/generate_smartsim2_nfl_projections.py` uses for
TEAM ratings, applied at the PLAYER level instead, and
`syndicate/features/mlb/box_score_stats.py`'s actual-result lookup for
grading a settled prop. Both read the same real play-by-play data
(`data/nfl_source/tracking/nflverse/pbp/pbp_{season}.csv`) -- there is no
separate player-stats feed to pull from.

Stat keys match the real markets seen in oddsapi_player_props_*.csv:
passing_yards, passing_attempts, passing_tds, rushing_yards,
rushing_attempts, receptions, anytime_td, receiving_yards, interceptions.
"""

from __future__ import annotations

import csv
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from syndicate.features.nfl.sources import default_nfl_source_root

_PLAY_COLUMNS = (
    "game_id",
    "week",
    "passer_player_id",
    "passer_player_name",
    "passing_yards",
    "pass_attempt",
    # Official attempts exclude sacks and two-point tries; nflverse's `pass_attempt` counts both.
    "sack",
    "two_point_attempt",
    "pass_touchdown",
    "rusher_player_id",
    "rusher_player_name",
    "rushing_yards",
    "rush_attempt",
    "rush_touchdown",
    "receiver_player_id",
    "receiver_player_name",
    "receiving_yards",
    "complete_pass",
    "touchdown",
    "interception",
    # Added for syndicate.features.nfl.injury_adjustment -- real per-play
    # team/value attribution, not used by any stat extractor above.
    "posteam",
    "defteam",
    "epa",
    "sack_player_id",
    "half_sack_1_player_id",
    "half_sack_2_player_id",
    "interception_player_id",
    "tackle_for_loss_1_player_id",
    "tackle_for_loss_2_player_id",
    "forced_fumble_player_1_player_id",
    "forced_fumble_player_2_player_id",
    "fumble_recovery_1_player_id",
    "fumble_recovery_2_player_id",
    "pass_defense_1_player_id",
    "pass_defense_2_player_id",
)


def _pbp_path(season: int) -> Path:
    """`#672`: resolve the pbp PER FILE, the way `#441` already fixed it elsewhere.

    This read used `default_nfl_source_root()`, whose probe file is git-tracked,
    so on refresh-worker it pointed into the ephemeral checkout -- where
    `tracking/` is gitignored and the file can never be. `load_player_plays`
    returns `()` for a missing file, so the failure was silent at every level
    except the row count: 2,296 odds rows in, zero sim rows out, hourly.
    """
    from syndicate.features.nfl.sources import nfl_pbp_path

    return nfl_pbp_path(season)


@lru_cache(maxsize=8)
def load_player_plays(season: int) -> tuple[dict[str, Any], ...]:
    """Every real regular-season play, trimmed to the columns player-stat
    aggregation needs. Cached per season -- callers may ask for many
    different players' rates against the same season within one request."""
    path = _pbp_path(season)
    if not path.exists():
        return ()
    plays: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            if row.get("season_type") != "REG":
                continue
            try:
                week = int(row.get("week") or 0)
            except (TypeError, ValueError):
                continue
            plays.append({column: row.get(column) or "" for column in _PLAY_COLUMNS} | {"week": week})
    return tuple(plays)


def _player_name_candidates(season: int) -> dict[str, frozenset[str]]:
    """nflverse display name -> EVERY player id that name refers to.

    The set, not one winner. `player_name_index` collapses this to the
    unambiguous entries and `player_name_collisions` reports the rest.

    DELIBERATELY NOT `lru_cache`d, even though it does a full play scan.
    `player_name_index` is the cached entry point and several test files
    reset it with `player_name_index.cache_clear()`. Caching here too adds a
    second layer that call does not reach, so a stale index survives the
    reset and leaks across tests -- which is exactly what happened when this
    was first written cached (tests/test_nfl_props.py went red on a fixture
    it had nothing to do with).
    """
    candidates: dict[str, set[str]] = {}
    for play in load_player_plays(season):
        for id_key, name_key in (
            ("passer_player_id", "passer_player_name"),
            ("rusher_player_id", "rusher_player_name"),
            ("receiver_player_id", "receiver_player_name"),
        ):
            player_id = play.get(id_key)
            name = play.get(name_key)
            if player_id and name:
                candidates.setdefault(name.strip().lower(), set()).add(player_id)
    return {name: frozenset(ids) for name, ids in candidates.items()}


@lru_cache(maxsize=8)
def player_name_index(season: int) -> dict[str, str]:
    """Real nflverse display name (e.g. "K.Murray") -> player id, for names
    that identify EXACTLY ONE player. Case/whitespace-normalized key.

    AMBIGUOUS NAMES ARE OMITTED, not resolved to a guess. This used to be
    `index.setdefault(name, player_id)`, so the first id encountered won and
    every other player sharing that short name silently resolved to them --
    the docstring on `short_name_from_full` called the collision "acceptable
    for a v1" because nothing had ever measured its consequence. Measured
    2026-08-20, the first time real quoted prop lines existed to join against:

      season 2023: 14 of 573 short names collide (2.4%), hiding 16 players.
      `j.williams` alone maps to FOUR distinct player ids.

    2.4% sounds survivable and is not, because the errors are not random. A
    collision takes the PRICE of a longshot and the MODEL RATE and OUTCOME of
    whichever star shares their initial+surname, which is exactly the shape of
    a fake edge. In the first NFL prop ROI run it produced `Troy Hill` (a
    cornerback) priced +4000 carrying Tyreek Hill's game log, `D.J. Montgomery`
    at +3000 carrying David Montgomery's, and a headline anytime_td ROI of
    +125% that was entirely an artifact of the join.

    An unresolvable name costs us one bet. A wrongly resolved name prices a
    projection against a different human being, which is worse than no bet at
    any stake -- so `unknown` maps to None here, never to a permissive guess.

    RECOVERABLE, and deliberately not attempted in this pass: the odds row
    carries home/away team, so a player_id -> team map would disambiguate most
    of these. That needs `posteam` added to `_PLAY_COLUMNS`, which widens every
    play dict in memory, and is its own change with its own measurement.
    """
    return {
        name: next(iter(ids))
        for name, ids in _player_name_candidates(season).items()
        if len(ids) == 1
    }


def player_name_collisions(season: int) -> dict[str, frozenset[str]]:
    """Names that refer to more than one player, so a caller can REPORT the
    coverage it is losing rather than silently missing those rows."""
    return {
        name: ids
        for name, ids in _player_name_candidates(season).items()
        if len(ids) > 1
    }


@lru_cache(maxsize=8)
def player_team_by_week(season: int) -> dict[str, dict[int, str]]:
    """{player_id: {week: team_abbr}} from each play's `posteam`.

    PER WEEK, not per season, and that is not pedantry: players are traded and
    signed mid-season, and a game-context lookup keyed on the wrong team reads
    the wrong side of the wrong game -- an error that would be invisible because
    it still returns a plausible number.

    The team for a week is the MODE of `posteam` over that player's plays that
    week. A mode rather than the first value because a player can appear on a
    play credited to the opposing offence (a lateral, a turnover return), and
    one such play must not reassign him for the whole week.

    `posteam` was already in `_PLAY_COLUMNS` for injury_adjustment, so this adds
    no new column and no extra memory per play.
    """
    counts: dict[str, dict[int, dict[str, int]]] = {}
    for play in load_player_plays(season):
        team = str(play.get("posteam") or "").strip()
        if not team:
            continue
        week = play["week"]
        for key in ("passer_player_id", "rusher_player_id", "receiver_player_id"):
            player_id = play.get(key)
            if not player_id:
                continue
            per_week = counts.setdefault(player_id, {}).setdefault(week, {})
            per_week[team] = per_week.get(team, 0) + 1
    return {
        player_id: {
            week: max(teams.items(), key=lambda kv: kv[1])[0]
            for week, teams in weeks.items()
        }
        for player_id, weeks in counts.items()
    }


def short_name_from_full(full_name: str) -> str:
    """"Drake Maye" -> "D.Maye" -- real player-prop odds carry full names
    while nflverse pbp uses first-initial.last-name; this bridges the two
    real data sources. Two players sharing a first initial + last
    name collide here. That is unavoidable in this direction (the short
    name genuinely carries less information), which is why the COLLISION
    IS HANDLED IN `player_name_index` -- it omits ambiguous names so this
    function can stay a pure format bridge. See that docstring for the
    measurement."""
    parts = [part for part in str(full_name or "").strip().split() if part]
    if len(parts) < 2:
        return str(full_name or "").strip()
    return f"{parts[0][0]}.{parts[-1]}"


def resolve_player_id(season: int, full_name: str) -> str | None:
    return player_name_index(season).get(short_name_from_full(full_name).strip().lower())


# WEEK 1 HAS NO CURRENT-SEASON PLAYS, AND THAT KILLED EVERY PROP.
#
# MEASURED 2026-09-08, production, NFL week 1: `/nfl/api/props` served
# **0 cards** against a capture of **5,929 real quotes** (519 players, 8 books,
# 16 matchups). The odds half was fine -- running production's own file through
# the real reader yields 2,442 odds rows. The SIM half was zero, and it failed
# at the FIRST gate:
#
#     player_name_index(2026):   0 names      <- no 2026 plays exist yet
#     player_name_index(2025): 574 names
#
# `player_name_index` is derived from `load_player_plays(season)`, so in week 1
# no player resolves, `resolve_player_id` returns None for everyone, and
# `nfl_props_rows_for_week` hits `continue` on every row. `player_rate` fails
# the same way one line later: its window is `row["week"] < week`, which is
# empty at week 1. So NFL props are structurally dead every week 1 and start
# working in week 2 -- silently, with no error and no log line.
#
# THE TEAM PATH ALREADY SOLVED THIS. `generate_smartsim2_nfl_projections.py`'s
# `_team_rating` falls back to the entire prior season and TAGS the result
# `prior_season_fallback`; every 2026 week-1 game carries that tag today. The
# player path had no equivalent.
#
# WHY THESE ARE NEW FUNCTIONS RATHER THAN A FIX IN PLACE. `resolve_player_id`
# and `player_rate` are called by `backtest_nfl_props.py`,
# `fit_nfl_props_game_context.py` and `report_nfl_props_roi.py`. Adding a
# prior-season fallback inside them would change what those runs measure --
# a denominator moving for a reason unrelated to the thing being measured is
# how a model looks like it improved. The backtests keep the strict functions;
# the BOARD gets the fallback, and every caller can see which it used.
#
# EVERY RETURN CARRIES ITS SOURCE, because a prior-season rate is a different
# claim from a current-form one and the card has to be able to say so.


def resolve_player_id_with_prior(season: int, full_name: str) -> tuple[str | None, str]:
    """(player_id, source) -- current season first, prior season as fallback.

    The nflverse player id is stable across seasons, so an id resolved from the
    prior season is the same human in this one. Ambiguous short names are still
    dropped rather than guessed, in BOTH seasons -- see `player_name_index`,
    which records what a wrong resolution costs (a cornerback priced +4000
    carrying Tyreek Hill's game log).
    """
    key = short_name_from_full(full_name).strip().lower()
    current = player_name_index(season).get(key)
    if current is not None:
        return current, "current_season"
    # AMBIGUOUS IS NOT ABSENT (lane `nfl-passing-yards-prop-coin`, 2026-10-08). A
    # short name two current-season players share must NOT fall through to the
    # prior season, where it may have been unique: "Jalon Daniels" (TB, 2026)
    # collides with Jayden Daniels on `j.daniels`, and the fallback returned
    # Jayden's id because 2025 had only him. Fall back only when the name is
    # genuinely unknown this season. The board resolves through
    # `resolve_player_id_for_game` and reaches this only without game teams; the
    # backtest harnesses call it directly (27 names / 277 FIT quote rows).
    if key in player_name_collisions(season):
        return None, "ambiguous_current_season"
    prior = player_name_index(season - 1).get(key)
    if prior is not None:
        return prior, "prior_season_fallback"
    return None, "unresolved"


_NAME_SUFFIXES = frozenset({"jr", "jr.", "sr", "sr.", "ii", "iii", "iv", "v"})
_CANDIDATE_CACHE: dict[int, tuple[int, dict[str, frozenset[str]]]] = {}


def _cached_name_candidates(season: int) -> dict[str, frozenset[str]]:
    """`_player_name_candidates`, cached against the identity of the season's plays.

    Keyed on `id(load_player_plays(season))` rather than an `lru_cache`, so a test
    that clears or patches the play loader gets a fresh scan (the leak
    `_player_name_candidates`'s docstring warns about cannot happen here).
    """
    plays_id = id(load_player_plays(season))
    held = _CANDIDATE_CACHE.get(season)
    if held is not None and held[0] == plays_id:
        return held[1]
    candidates = _player_name_candidates(season)
    _CANDIDATE_CACHE[season] = (plays_id, candidates)
    return candidates


def short_name_keys(full_name: str) -> list[str]:
    """Candidate nflverse short names for a full name, most specific first.

    `short_name_from_full` takes the LAST token, so "Michael Penix Jr." became
    `m.jr.` and "Amon-Ra St. Brown" became `a.brown` (A.J. Brown). Measured on the
    2026 week-5 capture (lane `nfl-prop-name-resolution`): suffix names cost 55
    prop rows / 20 players, and St. Brown 7 rows. Keys, in order: the plain short
    name (unchanged behaviour), the suffix-stripped one, and first-initial + every
    remaining token ("a.st. brown") for multi-word surnames.
    """
    parts = [part for part in str(full_name or "").strip().split() if part]
    if len(parts) < 2:
        return [str(full_name or "").strip().lower()] if parts else []
    keys = [f"{parts[0][0]}.{parts[-1]}".lower()]
    core = list(parts)
    while len(core) > 2 and core[-1].lower() in _NAME_SUFFIXES:
        core.pop()
    keys.append(f"{core[0][0]}.{core[-1]}".lower())
    if len(core) > 2:
        keys.append(f"{core[0][0]}.{' '.join(core[1:])}".lower())
    # nflverse disambiguates same-initial teammates with a two-letter prefix
    # ("bi.robinson" Bijan / "br.robinson" Brian, ATL 2026); the one-letter key
    # alone fell back to last season and read both as ambiguous (12 rows,
    # measured 2026-10-08). Tried after the plain keys, so nothing that joined
    # before changes.
    if len(core[0]) >= 2 and core[0][1].isalpha():
        keys.append(f"{core[0][:2]}.{core[-1]}".lower())
    out: list[str] = []
    for key in keys:
        if key not in out:
            out.append(key)
    return out


def resolve_player_id_for_game(
    season: int,
    week: int,
    full_name: str,
    game_teams: set[str],
    canonical,
) -> tuple[str | None, str]:
    """(player_id, source): the ONE player behind a prop name who plays in THIS game.

    Lane `nfl-prop-name-resolution` (2026-10-07). `resolve_player_id_with_prior`
    drops any short name two players share, so stars went unrated every week
    (week 5: Bijan Robinson vs Brian Robinson, Kyren / Javonte / Jameson Williams,
    Mike Evans -- 59 rows), and it cannot see suffixes or multi-word surnames. The
    odds row names both clubs, so the disambiguator `player_name_index` calls
    RECOVERABLE is available: for each candidate short name (`short_name_keys`),
    current season then prior, keep the candidates whose team
    (`player_team_with_prior`) is one of the game's two; exactly one wins.

    REFUSES as before when none or several qualify, or when the game's teams are
    unknown (then it is exactly `resolve_player_id_with_prior`). `canonical` maps
    a team string to the same canonical form as `game_teams`.
    """
    teams = {t for t in (game_teams or set()) if t}
    if not teams:
        return resolve_player_id_with_prior(season, full_name)
    ambiguous = False
    for key in short_name_keys(full_name):
        for season_try, label in ((season, "current_season"), (season - 1, "prior_season_fallback")):
            ids = _cached_name_candidates(season_try).get(key)
            if not ids:
                continue
            in_game = []
            for pid in ids:
                team, _src = player_team_with_prior(season, week, pid)
                if team and canonical(team) in teams:
                    in_game.append(pid)
            if len(in_game) == 1:
                return in_game[0], label if len(ids) == 1 else f"{label}_team_disambiguated"
            if len(in_game) > 1:
                # A LATER, more specific key may still separate them -- nflverse's
                # two-letter "bi.robinson" / "br.robinson" (2026-10-08). Refused
                # only once every key has been tried.
                ambiguous = True
                break
    return None, "ambiguous_in_game" if ambiguous else "unresolved"


# A week past any real NFL season, so the prior-season lookup takes the WHOLE
# season rather than a slice. `player_rate` filters `row["week"] < week`, and
# passing the current week (1) would return an empty prior season too -- the
# same off-by-a-season trap the fallback exists to remove.
_ALL_WEEKS = 999


def player_rate_with_prior(
    season: int, week: int, player_id: str, stat: str
) -> tuple[float | None, float | None, int, str]:
    """(mean, stdev, n, source) with a whole-prior-season fallback.

    Falls back only when the current season cannot answer -- so from week 3 or
    so onward this is the strict function plus a tag, and the fallback quietly
    stops being used as real form accumulates.
    """
    mean, stdev, n = player_rate(season, week, player_id, stat)
    if mean is not None:
        return mean, stdev, n, "current_season_rolling"
    prior_mean, prior_stdev, prior_n = player_rate(season - 1, _ALL_WEEKS, player_id, stat)
    if prior_mean is not None:
        return prior_mean, prior_stdev, prior_n, "prior_season_fallback"
    return None, None, n, "no_data"


def anytime_td_rate_with_prior(
    season: int, week: int, player_id: str
) -> tuple[float | None, int, str]:
    """(mean, n, source) for anytime_td, with the same prior-season fallback.

    Routed through `anytime_td_rate` in BOTH arms so `#471`'s Gamma-Poisson
    shrinkage still applies to the prior-season sample -- a full prior season is
    a large n, so the shrinkage correctly does almost nothing there, but going
    around it would have silently reintroduced the raw-MLE underestimate the
    shrinkage exists to fix.
    """
    mean, n = anytime_td_rate(season, week, player_id)
    if mean is not None:
        return mean, n, "current_season_rolling"
    prior_mean, prior_n = anytime_td_rate(season - 1, _ALL_WEEKS, player_id)
    if prior_mean is not None:
        return prior_mean, prior_n, "prior_season_fallback"
    return None, n, "no_data"


def player_team_with_prior(season: int, week: int, player_id: str) -> tuple[str | None, str]:
    """(team_abbr, source) -- the team this player last played for.

    THE DISAMBIGUATOR THIS MODULE'S OWN DOCSTRING ASKED FOR AND DID NOT BUILD.
    `player_name_index` says it: "the odds row carries home/away team, so a
    player_id -> team map would disambiguate most of these", listed as
    RECOVERABLE and deliberately deferred. `player_team_by_week` is that map;
    this is the accessor with the same prior-season fallback the rest of the
    week-1 path now has.

    WHY IT MATTERS MORE THAN THE COLLISION GUARD ABOVE. That guard drops a short
    name shared by two players IN THE INDEX -- and the index is built from
    play-by-play, so it can only see players who touch the ball. A DEFENDER
    quoted for anytime TD has no offensive plays, is absent from the index
    entirely, and therefore triggers no collision at all: he silently inherits
    the one offensive player who shares his short name.

    MEASURED 2026-09-08 on the real week-1 capture:

        "Cam Brown"   -> c.brown -> 00-0038597
        "Chase Brown" -> c.brown -> 00-0038597    <- the SAME id
        c.brown flagged as a collision?  False
        anytime_td rate carried across:  0.518 over n=17

    Cam Brown is a linebacker. That is Chase Brown's running-back season
    attached to a +2200 line, and it rendered as a +47.5% edge -- the same
    shape as the `Troy Hill` / `Tyreek Hill` join this file already records
    producing a fake +125% ROI.

    Returns the most recent week STRICTLY BEFORE `week` in the current season,
    else the last week of the prior season. None when neither can answer, and
    the caller must treat that as REFUSE rather than as permission -- an
    unknown resolved permissively is how this class of defect ships.
    """
    current = player_team_by_week(season).get(player_id) or {}
    earlier = [w for w in current if w < week]
    if earlier:
        return current[max(earlier)], "current_season"
    prior = player_team_by_week(season - 1).get(player_id) or {}
    if prior:
        return prior[max(prior)], "prior_season_fallback"
    return None, "unknown"


_STAT_EXTRACTORS = {
    "passing_yards": lambda play, pid: float(play["passing_yards"] or 0) if play.get("passer_player_id") == pid and play.get("passing_yards") else 0.0,
    # OFFICIAL attempts (lane `nfl-passing-yards-prop-coin`, 2026-10-08). nflverse's `pass_attempt` is 1 on
    # SACKS (and two-point tries), so this counted +2.42 attempts per QB-game vs the official box score
    # (exact on 12% of 561 2025 QB-games; with both excluded, exact on 100%). The market prices official
    # attempts, and the same extractor grades every backtest, so the over-rate read 0.607 vs 0.492.
    "passing_attempts": lambda play, pid: 1.0 if play.get("passer_player_id") == pid and play.get("pass_attempt") == "1" and play.get("sack") != "1" and play.get("two_point_attempt") != "1" else 0.0,
    "passing_tds": lambda play, pid: 1.0 if play.get("passer_player_id") == pid and play.get("pass_touchdown") == "1" else 0.0,
    "rushing_yards": lambda play, pid: float(play["rushing_yards"] or 0) if play.get("rusher_player_id") == pid and play.get("rushing_yards") else 0.0,
    "rushing_attempts": lambda play, pid: 1.0 if play.get("rusher_player_id") == pid and play.get("rush_attempt") == "1" else 0.0,
    "receptions": lambda play, pid: 1.0 if play.get("receiver_player_id") == pid and play.get("complete_pass") == "1" else 0.0,
    "receiving_yards": lambda play, pid: float(play["receiving_yards"] or 0) if play.get("receiver_player_id") == pid and play.get("receiving_yards") else 0.0,
    "interceptions": lambda play, pid: 1.0 if play.get("passer_player_id") == pid and play.get("interception") == "1" else 0.0,
    # Anytime TD attributed only to the ball-carrier/receiver of the
    # scoring play -- deliberately checked against rusher/receiver id
    # only, so a passer's OWN touchdown pass never counts as their own
    # anytime-TD (that's a passing_tds event, a different market), and a
    # passing touchdown never inflates the receiver's own rushing/other
    # attribution.
    "anytime_td": lambda play, pid: 1.0 if play.get("touchdown") == "1" and pid in (play.get("rusher_player_id"), play.get("receiver_player_id")) else 0.0,
}

STAT_KEYS: tuple[str, ...] = tuple(_STAT_EXTRACTORS.keys())


def player_game_log(season: int, player_id: str) -> list[dict[str, Any]]:
    """One row per game this player has a qualifying play in: {game_id,
    week, <stat>: total, ...} for every stat in STAT_KEYS -- the real
    "box score" line a player's card would show for that game."""
    totals: dict[str, dict[str, Any]] = {}
    for play in load_player_plays(season):
        if player_id not in (play.get("passer_player_id"), play.get("rusher_player_id"), play.get("receiver_player_id")):
            continue
        game_id = play["game_id"]
        row = totals.setdefault(game_id, {"game_id": game_id, "week": play["week"], **{stat: 0.0 for stat in STAT_KEYS}})
        for stat, extractor in _STAT_EXTRACTORS.items():
            row[stat] += extractor(play, player_id)
    return sorted(totals.values(), key=lambda row: row["week"])


def _zero_involvement_weeks(log: list[dict[str, Any]], before_week: int) -> int:
    """Count games the player almost certainly PLAYED but recorded nothing.

    `player_game_log` only creates a row for a game the player has a
    QUALIFYING PLAY in -- passer, rusher or receiver. A receiver who dressed
    and was never targeted produces NO ROW, so that game vanishes from the
    denominator and the mean becomes "yards per game he was INVOLVED in"
    rather than "yards per game". The market prices the second quantity.

    MEASURED 2026-09-08 against the real week-1 capture, model minus line over
    1,923 quoted rows: median **+7.7%**, mean **+12.1%**, with **24% of rows
    more than 25% ABOVE the line and only 5% below**. The bias is exactly where
    this mechanism predicts -- `receiving_yards` +18.2% and `rushing_yards`
    +11.9%, where empty games are common, against `passing_yards` -1.1% and
    `passing_attempts` +4.1%, where a quarterback always has plays and so never
    loses a game from the denominator.

    ISOLATED GAPS ONLY, and this is the whole judgement in one line. Over 2025:
    1,619 games are missing from inside players' spans, but only **514 are
    single-week gaps**; the rest are runs (121 of length 2, 63 of 3, 32 of 4, 79
    of 5+). A five-week run is an injury, and scoring it as five 0-yard games
    would understate a healthy player badly -- the opposite error. A lone
    missing week is far more likely a game he played without a target. Counting
    every in-span gap moves the mean -17.6%/-12.5%; counting only isolated ones
    moves it -7.1%/-6.5%.

    NOT VALIDATED AGAINST OUTCOMES, and that is stated here rather than in a
    commit message nobody re-reads: `scripts/backtest_nfl_props.py` grades with
    `excluded_zero_engagement` (7,326 graded vs 1,138 excluded for
    receiving_yards; 4,673 vs 3,791 for rushing_yards), i.e. it drops the very
    games this corrects, so it is STRUCTURALLY BLIND to this defect and cannot
    referee the change. Matching the market is not evidence either -- the market
    can be wrong. What is established is that the estimator was answering a
    different question from the one being priced.

    Weeks at or after `before_week` are never considered, so this inherits the
    no-lookahead discipline unchanged.
    """
    weeks = sorted(row["week"] for row in log)
    if len(weeks) < 2:
        return 0
    present = set(weeks)
    missing = [w for w in range(weeks[0], weeks[-1] + 1) if w not in present and w < before_week]
    isolated = 0
    for week in missing:
        if (week - 1) not in missing and (week + 1) not in missing:
            isolated += 1
    return isolated


# A QUARTERBACK WHO DRESSES ALWAYS THROWS, so a missing week for him means he
# DID NOT PLAY -- not that he played without being involved. Imputing zeros
# there invents games he never appeared in.
#
# MEASURED, and the data said so before this rule existed. Applying the
# correction to every stat moved `passing_yards` from **-1.1%** (already the
# best-calibrated market on the board) to **-7.7%**, and `passing_attempts`
# from +4.1% to -2.2% -- i.e. it BROKE the two markets that never had the
# defect. That is the signature of a mechanism applied outside its domain: the
# passing markets were well calibrated precisely BECAUSE a quarterback never
# loses a game from his denominator.
#
# Scoped by the player's OWN log rather than a roster/position join: a real
# quarterback accumulates passing attempts, and no roster file is needed (the
# 2026 depth chart is missing real starters and `injuries_2026.csv` does not
# exist, so neither is a dependable source here).
_QB_PASSING_ATTEMPTS_FLOOR = 20.0

_ZERO_IMPUTABLE_STATS = frozenset({
    "receiving_yards",
    "receptions",
    "rushing_yards",
    "rushing_attempts",
})


def _zero_game_imputation_applies(stat: str, log: list[dict[str, Any]]) -> bool:
    """Only skill-position USAGE stats, and never for a quarterback.

    `anytime_td` is absent from the imputable set on purpose -- see
    `player_rate`'s docstring for why its calibration must not be disturbed.
    The passing markets are absent because they never had the defect.
    """
    if stat not in _ZERO_IMPUTABLE_STATS:
        return False
    return sum(row.get("passing_attempts") or 0.0 for row in log) < _QB_PASSING_ATTEMPTS_FLOOR


def _zero_game_imputation_enabled() -> bool:
    """Absent = ON. The uncorrected estimator is measurably answering the wrong
    question, so the corrected one is the default; the switch exists to turn it
    OFF for an A/B, not to opt in."""
    raw = os.environ.get("SYNDICATE_NFL_PROP_ZERO_GAMES")
    return True if raw is None else str(raw).strip().lower() not in {"0", "false", "off", "no"}


def player_rate(season: int, week: int, player_id: str, stat: str) -> tuple[float | None, float | None, int]:
    """Rolling pre-week (mean, stdev, sample_size) for one stat -- only
    games strictly before `week`, same no-lookahead discipline as the
    team-rating aggregator in generate_smartsim2_nfl_projections.py.
    Returns (None, None, 0) with fewer than 2 qualifying games -- a rate
    off a single game is not a real distribution, never fabricated.

    Games the player played without recording anything are counted as ZEROS for
    every stat EXCEPT `anytime_td` -- see `_zero_involvement_weeks`.

    WHY `anytime_td` IS EXEMPT, deliberately and not by oversight:
    `anytime_td_rate` calls straight into this function, and its shrinkage
    constant `ANYTIME_TD_SHRINKAGE_K = 12.0` was SWEPT AND SELECTED against the
    rate this function returns today (fit on 2022-2023, reported on 2024-2025,
    Brier 0.1973 -> 0.1680 on 8,464 held-out rows). Adding zeros underneath a
    constant that was fitted on top of their absence would silently invalidate
    that calibration -- `docs/ai_context/model_engine_standard.md`: adding a
    MECHANISM to a calibrated engine requires RE-FITTING the rates that were
    absorbing it. Re-fitting k is its own measured piece of work, so the TD
    market keeps the estimator its constant was tuned for.
    """
    import statistics

    log = [row for row in player_game_log(season, player_id) if row["week"] < week]
    values = [row[stat] for row in log]
    # The n>=2 floor is judged on REAL games, before any imputation, so an
    # imputed zero can never manufacture a "distribution" out of one game.
    if len(values) < 2:
        return None, None, len(values)
    if _zero_game_imputation_applies(stat, log) and _zero_game_imputation_enabled():
        values = values + [0.0] * _zero_involvement_weeks(log, before_week=week)
    # `stdev`, NOT `pstdev`, and the difference is not pedantry at these n.
    #
    # These games are a SAMPLE used to estimate the player's true game-to-game
    # spread for a game that has not happened yet. `pstdev` divides by n and so
    # describes the spread OF THESE GAMES; `stdev` divides by n-1 and estimates
    # the spread of the process that generated them. The first understates the
    # second by `sqrt((n-1)/n)`:
    #
    #     n=2  -29.3%     n=3  -18.4%     n=4  -13.4%     n=8  -6.5%
    #
    # and this function filters `row["week"] < week`, so n IS 3 at week 4. The
    # consequence reached the board: the model's own implied sd, back-derived
    # from its served rows on 2026-09-28, was 0.97 for rushing ATTEMPTS -- a
    # back's carry count known to within one carry -- and 86% of NFL model edges
    # then exceeded `layer2_board._MODEL_EDGE_MAX_POINTS` and were dropped, so
    # the model reached 3% of served rows against NCAAF's 55%.
    #
    # MEASURED, not reasoned (`scripts/calibrate_nfl_spread_shrinkage.py`, fit
    # 2022-23, reported 2024-25, graded through `_nfl_prop_model_probability`
    # against real settled outcomes, all arms on an identical row set):
    #
    #     all rows        Brier 0.192516 -> 0.190527   cov80 0.7011 -> 0.7448
    #     high-usage p70  Brier 0.219752 -> 0.217536   cov80 0.6791 -> 0.7258
    #
    # It is the only arm that improved BOTH populations. Shrinking the spread
    # toward a flat per-stat league prior was swept alongside and REFUSED: it won
    # on all rows and was monotonically HARMFUL on the high-usage rows the board
    # actually quotes, because that prior is dominated by marginal players
    # (median `rushing_yards` sd 10.2 across 564 "rushers" against a workhorse's
    # ~25), so it made starters NARROWER. A usage-scaled prior is still open.
    #
    mean = statistics.fmean(values)
    return mean, shrink_spread(statistics.stdev(values), len(values), mean, stat), len(values)


#: The league's typical COEFFICIENT OF VARIATION per market -- median per-player
#: `sd/mean`, derived from the FIT SEASONS ONLY (2022-2023), so 2024-2025 stayed
#: held out for the grade and 2026 is wholly unseen.
#:
#: A CV RATHER THAN AN ABSOLUTE SD, and that distinction was measured, not
#: assumed. A flat per-stat prior sd was swept first and REFUSED: the league
#: median `rushing_yards` sd over 2022-23 is 10.2, computed across 564 "rushers"
#: who are overwhelmingly marginal, while a workhorse back's own sd is ~25.
#: Shrinking him toward 10.2 makes him NARROWER -- the exact opposite of the
#: defect being fixed. On the high-usage rows the board actually quotes, flat
#: shrinkage was monotonically harmful in BOTH Brier and coverage (cov80 0.7356
#: at k=0 falling to 0.5557 at k=20). A CV carries the usage level with it, so a
#: starter is shrunk toward a starter-sized spread.
LEAGUE_SPREAD_CV: dict[str, float] = {
    "passing_yards": 0.4256,
    "passing_attempts": 0.4281,  # re-derived 2026-10-08 on OFFICIAL attempts (sacks excluded); was 0.5444
    "passing_tds": 0.9354,
    "rushing_yards": 1.2271,
    "rushing_attempts": 0.9129,
    "receiving_yards": 0.9424,
    "receptions": 0.7092,
    "interceptions": 1.2766,
}

#: Shrinkage weight for the SPREAD, the same `k/(n+k)` shape
#: `ANYTIME_TD_SHRINKAGE_K` uses for the mean. SWEPT AND SELECTED, not guessed:
#: `scripts/calibrate_nfl_spread_shrinkage.py`, fit 2022-23, reported 2024-25,
#: graded through `_nfl_prop_model_probability` against real settled outcomes,
#: every arm scored on an IDENTICAL row set.
#:
#: HELD OUT 2024-2025, high-usage p70, same 8,629 rows:
#:
#:     arm                       Brier     cov80   worst bucket   #499 bar 0.150
#:     pstdev  k=0 (was prod)  0.219744   0.6791     0.2229           FAIL
#:     stdev   k=0             0.217529   0.7258     0.2135           FAIL
#:     stdev+cv k=4            0.212150   0.8694     0.0943           pass
#:     stdev+cv k=6            0.212121   0.8906     0.0929           pass
#:     stdev+cv k=8            0.212196   0.9033     0.0721           pass
#:
#: k=6 is the Brier minimum out of sample as well as in fit, and it is the first
#: configuration to PASS the platform's calibration bar at all.
#:
#: THE ONE NUMBER THAT IS NOT IMPROVED BY THIS, recorded rather than buried:
#: 80% interval coverage OVERSHOOTS to 0.8906. The distribution went from too
#: narrow to somewhat too wide. Brier and the bucket gap both still prefer this,
#: and being too wide costs opportunities while being too narrow manufactures
#: false edges, but it is not calibrated and should not be described as such.
SPREAD_SHRINKAGE_K = 6.0

#: PER-MARKET OVERRIDES, and the list is short on purpose.
#:
#: A FULL per-market table was swept and REFUSED. Selected on the fit seasons and
#: graded out of sample it moved the pooled Brier by **-0.000077** -- one percent
#: of what the shrinkage itself delivered -- with five markets better, three
#: worse, and the calibration gap moving BACKWARDS on the two best-calibrated
#: markets (`rushing_yards` 0.0359 -> 0.0560, `rushing_attempts` 0.0404 ->
#: 0.0504). Eight maintained constants for a gain indistinguishable from noise is
#: a worse artifact than one, so the global k stands everywhere it is not beaten
#: decisively.
#:
#: `passing_attempts` IS beaten decisively, and it was the last market failing the
#: `#499` bar. Selected on the fit seasons, where BOTH metrics agree on k=2:
#:
#:     k      fit Brier   fit bucket  |  held Brier   held bucket
#:     0       0.184303     0.1621    |   0.181048      0.1493
#:     1       0.177927     0.1120    |   0.175128      0.1198
#:     2       0.176890     0.1068    |   0.173932      0.1463   <- selected
#:     3       0.176993     0.1232    |   0.173891      0.1482
#:     6       0.178508     0.1417    |   0.175056      0.1619   <- global k
#:
#: **k=1 HAS A BETTER HELD-OUT BUCKET (0.1198) AND WAS NOT TAKEN.** Choosing it
#: would be selecting on the test set, which is the one thing the fit/held-out
#: split exists to prevent -- and this file already carries a constant (`#471`'s
#: k=12) that was accepted only because its minimum was interior and in-sample.
#:
#: **THE PASS IS THIN AND SAYS SO: 0.1463 against a 0.150 bar.** It is a pass on
#: the measurement that was declared in advance, not a comfortable one, and a
#: re-fit on more seasons could move it either way.
#:
#: Why this market and not the count markets: `passing_attempts` has 57 distinct
#: outcomes, so a continuous model is the right family and only the width was
#: wrong. `interceptions` and `passing_tds` have 5 and 6, and no k fixes those --
#: they moved to a Poisson (`props._DISCRETE_COUNT_STATS`).
#: RE-SELECTED 2026-10-08 ON OFFICIAL ATTEMPTS (lane `nfl-passing-yards-prop-coin`). The table above was
#: fitted on nflverse `pass_attempt`, which counts SACKS; the extractor now excludes them, the league CV was
#: re-derived (0.5444 -> 0.4281) and k re-swept with the same script, split, p70 usage filter and rule
#: (min fit Brier; ties within 0.1% broken by bucket gap). k=4 and k=6 tie on fit Brier; k=4 wins the gap:
#:
#:     k      fit Brier   fit bucket  |  held Brier   held bucket  held cov80
#:     2       0.173426     0.0952    |   0.166868      0.1429      0.8245
#:     4       0.172558     0.1085    |   0.166145      0.1238      0.8715   <- selected
#:     6       0.172576     0.1241    |   0.166186      0.1490      0.8997
SPREAD_SHRINKAGE_K_BY_MARKET: dict[str, float] = {
    "passing_attempts": 4.0,
}


def spread_shrinkage_enabled() -> bool:
    """DEFAULT ON, stated because the code's default is what decides.

    `off`/`0`/`false`/`no` restores the unshrunk sample sd without a deploy, so
    the mechanism has a reachability test (`off != on`) rather than only
    correctness tests -- the model-engine standard's requirement for anything
    behind a flag.
    """
    raw = str(os.environ.get("SYNDICATE_NFL_SPREAD_SHRINKAGE") or "").strip().lower()
    return raw not in {"off", "0", "false", "no"}


def shrink_spread(raw_sd: float, n: int, mean: float, stat: str) -> float:
    """`(n*raw_sd + k*cv*mean) / (n+k)` -- the spread's analogue of `#471`.

    NO SHRINKAGE WHEN THE MEAN IS NOT POSITIVE. The prior is `cv * mean`, so a
    mean of zero makes it zero, and blending toward zero would make an already
    narrow distribution NARROWER -- turning the fix into the defect for exactly
    the players with the least evidence. Those rows keep the raw sample sd.
    """
    if not spread_shrinkage_enabled():
        return raw_sd
    cv = LEAGUE_SPREAD_CV.get(stat)
    if cv is None or mean is None or mean <= 0 or n <= 0:
        return raw_sd
    k = SPREAD_SHRINKAGE_K_BY_MARKET.get(stat, SPREAD_SHRINKAGE_K)
    return (n * raw_sd + k * cv * float(mean)) / (n + k)


# `#471`: the raw per-player MLE rate badly underestimates `anytime_td` at
# small n. Measured (scripts/backtest_nfl_props.py, 2022-2025, 16,991
# rows): players whose rolling mean was EXACTLY 0.0 (2-4 games, zero TDs)
# had a REAL hit rate of ~13-14% that week, not 0%. The shrinkage vanishes
# as a player's own sample grows (k/(n+k) -> 0 as n -> inf), so it does the
# most work exactly where the defect was measured (n=2-4) and barely
# touches an established player.
#
# TUNED, not guessed: scripts/calibrate_nfl_anytime_td_shrinkage.py swept
# k in {0..30}, SELECTED on 2022-2023 (fit-Brier minimized at k=12.0, a
# genuine convex minimum -- 0.1905 at k=0 down to 0.1606 at k=12, back up
# to 0.1621 at k=30, not a monotone "more shrinkage is free" artifact),
# then only REPORTED on 2024-2025 (never re-selected there): Brier
# 0.1973 (k=0, pre-fix) -> 0.1680 (k=12) on 8,464 held-out observations.
# On the exact defect bucket (raw_mean == 0.0, n=2,814 out-of-sample
# rows): predicted probability moved 0.0% -> 18.0% against a real 14.1%
# hit rate -- closes most of the gap, does not eliminate it (a real,
# stated residual, not claimed as a perfect fix). Full sweep + OOS report:
# reports/nfl_anytime_td_shrinkage_calibration.json.
ANYTIME_TD_SHRINKAGE_K = 12.0


def shrink_count_mean(raw_mean: float, n: int, prior_mean: float, prior_weight: float) -> float:
    """Gamma-Poisson conjugate shrinkage for a per-game COUNT stat (not a
    Bernoulli -- a player can score more than once in a game):
    `posterior_mean = (n*raw + k*prior) / (n+k)`. Pulled out as its own
    function so `anytime_td_rate` (production) and
    `scripts/backtest_nfl_props.py` (which re-derives `raw_mean`/`n` from
    its own cached game log rather than calling `player_rate` again, to
    avoid rescanning the whole season per player-week) apply the IDENTICAL
    formula rather than two copies that could silently drift apart. The
    caller is responsible for not calling this with an unmeasured prior
    (`prior_mean` from zero observations) -- see `_anytime_td_league_prior`'s
    own (0.0, 0) floor and how `anytime_td_rate` guards it below."""
    return (n * raw_mean + prior_weight * prior_mean) / (n + prior_weight)


@lru_cache(maxsize=8)
def _anytime_td_league_week_totals(season: int) -> dict[int, tuple[int, int]]:
    """{week: (total anytime_td events, total player-game observations)}
    across EVERY offensive player with a qualifying play that week -- the
    same population `player_game_log` grades anytime_td against, just
    aggregated league-wide instead of per player. Substrate for the
    no-lookahead league prior `_anytime_td_league_prior` builds below; not
    itself no-lookahead (it is a plain per-week aggregate) -- the
    lookahead discipline is enforced by only summing weeks < the query
    week when this is consumed, same pattern as `player_rate`."""
    events_by_week: dict[int, int] = {}
    player_games_by_week: dict[int, set[tuple[str, str]]] = {}
    for play in load_player_plays(season):
        week = play["week"]
        for id_key in ("passer_player_id", "rusher_player_id", "receiver_player_id"):
            pid = play.get(id_key)
            if pid:
                player_games_by_week.setdefault(week, set()).add((pid, play["game_id"]))
        if play.get("touchdown") == "1":
            # A scoring play is attributed to exactly one of
            # rusher/receiver -- same convention as the anytime_td
            # extractor above, so this stays consistent with what
            # player_game_log would sum if asked about every player.
            scorer = play.get("rusher_player_id") or play.get("receiver_player_id")
            if scorer:
                events_by_week[week] = events_by_week.get(week, 0) + 1
    return {
        week: (events_by_week.get(week, 0), len(games))
        for week, games in player_games_by_week.items()
    }


def _anytime_td_league_prior(season: int, week: int) -> tuple[float, int]:
    """Cumulative, PRE-`week` league-wide mean anytime_td rate -- same
    no-lookahead discipline as `player_rate`: only games strictly before
    `week` count, so a week-3 prediction never sees week-4+ scoring. This
    is what makes the shrinkage prior itself leak-free, not just the raw
    rate it blends with. Returns (0.0, 0) before any games have been
    played that season (week 1) -- callers must handle a zero denominator,
    same as `player_rate`'s own (None, None, 0) floor."""
    totals = _anytime_td_league_week_totals(season)
    total_events = sum(events for w, (events, _n) in totals.items() if w < week)
    total_games = sum(games for w, (_events, games) in totals.items() if w < week)
    if total_games == 0:
        return 0.0, 0
    return total_events / total_games, total_games


def anytime_td_rate(season: int, week: int, player_id: str, *, prior_weight: float = ANYTIME_TD_SHRINKAGE_K) -> tuple[float | None, int]:
    """Shrunk `anytime_td` rate for one player: the player's own raw
    rolling mean (`player_rate`'s existing n>=2 floor, unchanged) blended
    toward the league's own pre-week empirical mean via a Gamma-Poisson
    conjugate estimator -- `anytime_td` is a per-game COUNT (a player can
    score more than once), not a Bernoulli, so the count-family shrinkage
    formula applies: `posterior_mean = (n*raw + k*prior) / (n+k)`.

    Returns (None, n) with the same n<2 floor as `player_rate` -- this
    does not create a rate where none existed, it only corrects the rate
    `player_rate` already returns. See `ANYTIME_TD_SHRINKAGE_K`'s comment
    for the measurement that motivated this and how the constant was
    tuned.

    The `prior_n == 0` branch below is UNREACHABLE under the current
    implementation, not defensive dead weight left in by accident: this
    player's own `n` qualifying games (required >= 2 for `raw_mean` to be
    non-None here) are themselves a subset of the population
    `_anytime_td_league_prior` counts for those same weeks, so `prior_n`
    can never be smaller than `n` whenever this line is reached. Kept
    anyway as a floor against `raw_mean` silently getting shrunk toward a
    fabricated 0.0 "league rate" if a future change ever decouples the two
    populations -- a `prior_n` genuinely at 0 must fall back to the raw
    rate, not be treated as evidence the league never scores."""
    raw_mean, _stdev, n = player_rate(season, week, player_id, "anytime_td")
    if raw_mean is None:
        return None, n
    prior_mean, prior_n = _anytime_td_league_prior(season, week)
    if prior_n == 0:
        return raw_mean, n
    return shrink_count_mean(raw_mean, n, prior_mean, prior_weight), n


# QB STARTS REFUSAL (lane `nfl-passing-yards-prop-coin`, user decision 2026-10-08).
#
# `player_rate` averages EVERY game a passer has a play in. A quarterback quoted
# for a START whose log is mostly relief, mop-up or injury-exit appearances
# (59-73 passing yards per such game) gets a mean far below the line and
# P(over) ~0.07 -- and goes over ~51% of the time. Measured through the
# production probability on OddsAPI kickoff-10min quotes
# (`.syndicate/findings_2026-10-07_nfl_passing_yards_coin.md`): rows with fewer
# than 2 full starts in the as-of log are 5% of FIT 2023-24 passing-yards rows
# and carry 68% of the log-loss in excess of a coin (2025: 6% / 57%). The model
# has no evidence about this player AS A STARTER, so it gives no opinion.
QB_FULL_START_SHARE = 0.7
QB_MIN_FULL_STARTS = 2
QB_STARTS_REFUSAL_STATS = frozenset({"passing_yards", "passing_attempts"})


def qb_starts_refusal_enabled() -> bool:
    """DEFAULT ON. `off`/`0`/`false`/`no` restores the unrefused rows (the off != on test)."""
    raw = str(os.environ.get("SYNDICATE_NFL_QB_STARTS_REFUSAL") or "").strip().lower()
    return raw not in {"off", "0", "false", "no"}


@lru_cache(maxsize=8)
def _pass_attempt_shares(season: int) -> dict[tuple[str, str], float]:
    """(game_id, passer_id) -> the passer's share of his team's pass attempts in that game.

    `pass_attempt` (sacks included) in both numerator and denominator, so the
    share is a dropback share; the team is the play's `posteam`.
    """
    mine: dict[tuple[str, str], int] = {}
    team_of: dict[tuple[str, str], str] = {}
    team_total: dict[tuple[str, str], int] = {}
    for play in load_player_plays(season):
        passer = play.get("passer_player_id")
        if not passer or play.get("pass_attempt") != "1":
            continue
        key = (play["game_id"], passer)
        mine[key] = mine.get(key, 0) + 1
        team_of[key] = play.get("posteam") or ""
        team_key = (play["game_id"], team_of[key])
        team_total[team_key] = team_total.get(team_key, 0) + 1
    return {
        key: count / team_total[(key[0], team_of[key])]
        for key, count in mine.items()
        if team_total.get((key[0], team_of[key]))
    }


def qb_full_starts(season: int, week: int, player_id: str, rate_source: str) -> int:
    """Games in the SAME as-of log `player_rate_with_prior` priced from in which
    this player took >= `QB_FULL_START_SHARE` of his team's pass attempts.

    `rate_source` picks the log exactly as the rate did: the current season
    strictly before `week`, or the whole prior season for the fallback.
    """
    if rate_source == "current_season_rolling":
        log_season, before = season, int(week)
    else:
        log_season, before = season - 1, _ALL_WEEKS
    shares = _pass_attempt_shares(log_season)
    return sum(
        1
        for row in player_game_log(log_season, player_id)
        if row["week"] < before and shares.get((row["game_id"], player_id), 0.0) >= QB_FULL_START_SHARE
    )


def qb_starts_refused(season: int, week: int, player_id: str, stat: str, rate_source: str) -> bool:
    """True when the model must NOT price this passing line (see the block above)."""
    if stat not in QB_STARTS_REFUSAL_STATS or not qb_starts_refusal_enabled():
        return False
    return qb_full_starts(season, week, player_id, rate_source) < QB_MIN_FULL_STARTS


# STARTS-ONLY RATE (lane `nfl-passing-yards-prop-coin`, pre-registered 2026-10-08,
# user: "If it passes, ship it"). A quoted line is for a START, so the as-of mean
# and sd come from the player's full starts only -- relief and injury-exit games
# no longer drag the mean below the line. Selected on REAL 2023 OddsAPI quotes,
# read once on 2024 (2025 untouched), identical rows, starts-refused rows excluded:
#
#     passing_yards     LL 0.7341 -> 0.7074 (-0.0267 [-0.0603, +0.0029]),
#                       mean P(over) 0.428 -> 0.511 vs over-rate 0.500   SHIP
#     passing_attempts  LL 0.7732 -> 0.7619, mean P(over) 0.464 vs 0.499
#                       (gap 0.035 > 0.03)                              NO SHIP
#
# The fitted blend weight on top of it is 0.0 (Normal only); the props module
# switches its weight on the same flag so the two can never ship apart.
#
# passing_attempts JOINED 2026-10-08 on its own pre-registered read (official attempts + starts-only, w fitted on
# real 2023+2024 quotes pooled = 0.16, validated on 2025 real quotes, identical rows): LL 0.7371 -> 0.7183
# (-0.0188 [-0.0420, +0.0038]), mean P(over) 0.495 vs official over-rate 0.470 (gap 0.025 <= 0.03). SHIP.
QB_STARTS_ONLY_RATE_STATS = frozenset({"passing_yards", "passing_attempts"})


def qb_starts_only_rate_enabled() -> bool:
    """DEFAULT ON. `off`/`0`/`false`/`no` restores the all-games rate AND its blend weight."""
    raw = str(os.environ.get("SYNDICATE_NFL_QB_STARTS_ONLY_RATE") or "").strip().lower()
    return raw not in {"off", "0", "false", "no"}


def qb_starts_only_rate(
    season: int, week: int, player_id: str, stat: str, rate_source: str
) -> tuple[float | None, float | None, int]:
    """(mean, shrunk sd, n starts) over the same as-of log `player_rate_with_prior` used, full starts only."""
    import statistics

    if rate_source == "current_season_rolling":
        log_season, before = season, int(week)
    else:
        log_season, before = season - 1, _ALL_WEEKS
    shares = _pass_attempt_shares(log_season)
    values = [
        row[stat]
        for row in player_game_log(log_season, player_id)
        if row["week"] < before and shares.get((row["game_id"], player_id), 0.0) >= QB_FULL_START_SHARE
    ]
    if len(values) < 2:
        return None, None, len(values)
    mean = statistics.fmean(values)
    return mean, shrink_spread(statistics.stdev(values), len(values), mean, stat), len(values)


def final_stat_value(season: int, game_id: str, player_id: str, stat: str) -> float | None:
    """The real settled value for one game -- this module's actual-result
    grading primitive, the NFL analog of
    syndicate.features.mlb.box_score_stats.final_stat_value."""
    for row in player_game_log(season, player_id):
        if row["game_id"] == game_id:
            return row.get(stat)
    return None
