"""Per-player NCAAF projections for the card's box tab.

--------------------------------------------------------------------------
THERE IS NO `ncaaf_prop_projections_{season}_wk{week}.json`, AND THAT IS
THE FINDING
--------------------------------------------------------------------------

NFL publishes one (`syndicate/features/nfl/props.py::
write_nfl_prop_projection_artifact`, allowlisted in
`artifact_publisher.HOT_ARTIFACT_PATTERNS` as
`nfl_source/nfl_prop_projections_*.json`). NCAAF publishes NOTHING of the
kind: there is no writer, no reader, no allowlist line and no file. Searched
2026-09-09 -- `scripts/` has no `build_ncaaf_prop_projections.py`, and the only
`*prop*` NCAAF artifact is the captured OddsAPI CSV, which is a MARKET
inventory and not a projection.

So this module does not read an artifact of projections. It COMPUTES them
from two artifacts that do exist, using the code that was graded:

  1. `ncaaf_roster_snapshot.csv`  -- who is on the team, with a position,
     for THIS season (15,496 rows / 138 teams for 2026).
  2. `ncaaf_player_game_stats_snapshot.csv`, through
     `prop_model.anytime_td_probability` -- the ONE market this platform has
     backtested out-of-sample and found beats both the player's own mean and
     the league base rate (Brier 0.18168 vs 0.21919 / 0.19400, n=18,989).

--------------------------------------------------------------------------
WHY THE TABLE IS ONE COLUMN OF MODEL OUTPUT AND NOT SIX
--------------------------------------------------------------------------

`prop_model`'s docstring records the measurement that forbids the obvious
"football-shaped" column set. On EVERY continuous market -- passing, rushing
and receiving yards, receptions, passing TDs -- the model LOSES to the
player's own prior-weeks mean, so none of them is projected anywhere in this
codebase. Filling `Pass yds` / `Rush yds` / `Rec yds` here would mean
inventing five projections that were measured to be worse than an average,
printed under a `Sim` chip beside a real CFBD box score. A projection that
looks like knowledge and is not is the failure this file exists to avoid, so
those columns are ABSENT rather than blank.

--------------------------------------------------------------------------
THE SEASON JOIN IS STRICT; THE MODEL'S HISTORY IS NAMED
--------------------------------------------------------------------------

Two different seasons are in play and conflating them is the defect
`cards.py::_ncaaf_player_box_section` already documents:

  * the ROSTER join is strictly the card's own season. A 2026 card lists 2026
    rostered players, never 2025's.
  * the model's RATE is fitted on whatever season has game logs, resolved by
    `prop_model.resolve_history_season` and carried out as a provenance
    string (`ncaaf_anytime_td_2025_for_2026` on opening weekend). That is a
    model INPUT, not last season's projections re-rendered -- and the section
    body prints it, so the reader can see which season the number rests on.

  * the MARKET columns are joined strictly on (season, week) -- they come from
    `oddsapi_player_props_{season}_wk{week}.csv` and nothing else.

--------------------------------------------------------------------------
CACHING
--------------------------------------------------------------------------

`_roster_index` is keyed on the snapshot's (path, mtime, size) rather than
plain `@lru_cache(maxsize=N)` -- the pattern
`nfl/props.py::_nfl_card_prop_projection_index` uses. `player_stats.py:68`
caches on season alone with no invalidation, and web served a stale empty
result for hours after fresh data was published; it took a deploy to clear.
Stamping the key means a newly published roster appears on the next request.

NOTE, and it is not fixed here: `prop_model._rates` / `available_seasons` /
`resolve_history_season` ARE plain `lru_cache`s on the game-log snapshot.
Those are pre-existing and unchanged by this module, so a newly published
player-game snapshot still needs `prop_model.reset_caches()` or a restart
before the probabilities move.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

from syndicate.features.ncaaf import prop_model
from syndicate.features.ncaaf.sources import roster_snapshot_path

# Reused, never reimplemented. `_norm` folds accents rather than stripping
# them, and `props.py` records what happens when that is done the other way:
# "San José State" and "San Jose State" stop matching and the team's whole
# panel disappears with no error. `_resolve_team_id` carries the longest-
# prefix rule that keeps North Carolina State off North Carolina's card.
# A private copy of either would be a second implementation that can drift
# from the one that was measured.
from syndicate.features.ncaaf.props import _find_captured_game
from syndicate.features.ncaaf.props import _norm
from syndicate.features.ncaaf.props import _read_snapshot
from syndicate.features.ncaaf.props import _resolve_team_id
from syndicate.features.ncaaf.props import _rows_by_game
from syndicate.features.ncaaf.props import _american
from syndicate.features.ncaaf.props import _better
from syndicate.features.ncaaf.props import _format_price

#: Positions that can plausibly score. A projection for an offensive lineman
#: is arithmetically defined and useless, and 2,568 of the 2026 roster's
#: 15,496 rows are OL -- they would be most of the table.
SKILL_POSITIONS: frozenset[str] = frozenset({"QB", "RB", "FB", "WR", "TE", "ATH"})

#: Rows per side. Measured on the 2026 roster: 24-60 skill players per team,
#: averaging 34.4, and the model refuses anyone under three prior games -- so
#: this caps the tail, it does not hide a squad.
MAX_ROWS_PER_SIDE = 20

#: The one market `prop_model` projects, spelled exactly as the capture spells
#: it (`props.py` keys off the same literal).
ANYTIME_TD_MARKET = "Anytime TD"


def _checkout_roster_path() -> Path:
    """The repo-checkout copy, for the reason `props.py` has one.

    `sources.roster_snapshot_path()` resolves the MOUNTED DISK, whose boot
    sync is seed-only, while a web deploy replaces the checkout. The two hold
    different vintages on Render, so both are tried.
    """
    return (
        Path(__file__).resolve().parents[3]
        / "data" / "ncaaf_source" / "source_artifacts" / "data" / "processed"
        / "roster" / "ncaaf_roster_snapshot.csv"
    )


def _stamp(*paths: Path) -> tuple[tuple[str, int, int], ...]:
    """(path, mtime_ns, size) for every copy that exists.

    This is the cache key, not the season. See this module's CACHING note.
    """
    stamp: list[tuple[str, int, int]] = []
    for path in paths:
        try:
            if path.exists():
                info = path.stat()
                stamp.append((str(path), int(info.st_mtime_ns), int(info.st_size)))
        except Exception:  # noqa: BLE001 -- a stat failure must not cost the board
            continue
    return tuple(stamp)


def _roster_stamp() -> tuple[tuple[str, int, int], ...]:
    return _stamp(roster_snapshot_path(), _checkout_roster_path())


def _game_log_stamp() -> tuple[tuple[str, int, int], ...]:
    return _stamp(prop_model._game_stats_path(), prop_model._checkout_game_stats_path())


#: One-element list, not a bare global, so the rebind below is unambiguous
#: under a threaded web worker: the worst race here is a redundant
#: `cache_clear()`, and `lru_cache` is itself thread-safe.
_LAST_GAME_LOG_STAMP: list[tuple[tuple[str, int, int], ...]] = []


def _sync_game_log_caches() -> None:
    """Drop `prop_model`'s caches when the game-log snapshot changes on disk.

    `prop_model._rates` / `available_seasons` / `resolve_history_season` are
    plain `lru_cache`s with no invalidation -- the same shape as
    `player_stats.py:68`, which served a stale empty result for hours after
    fresh data was published and took a deploy to clear. `reset_caches()`
    already exists there and nothing on the request path was calling it.
    """
    stamp = _game_log_stamp()
    if _LAST_GAME_LOG_STAMP:
        if _LAST_GAME_LOG_STAMP[0] != stamp:
            prop_model.reset_caches()
            _seasons_with_fittable_history.cache_clear()
            _LAST_GAME_LOG_STAMP[0] = stamp
        return
    _LAST_GAME_LOG_STAMP.append(stamp)


@lru_cache(maxsize=1)
def _seasons_with_fittable_history() -> tuple[int, ...]:
    """Seasons whose game logs can actually produce a projection, ascending.

    "Has rows" is NOT the criterion; "has somebody with
    `MIN_PRIOR_GAMES` games" is, because that is the test
    `anytime_td_probability` itself applies before it refuses.
    """
    fittable: list[int] = []
    for season in prop_model.available_seasons():
        table = prop_model._rates(season)
        if any(games >= prop_model.MIN_PRIOR_GAMES for games in table["games"].values()):
            fittable.append(season)
    return tuple(fittable)


def history_season_for(season: int) -> int | None:
    """The season these projections should be FITTED on, or None.

    -------------------------------------------------------------------
    SUFFICIENCY, NOT PRESENCE -- and the difference is a whole empty panel
    -------------------------------------------------------------------

    `prop_model.resolve_history_season` picks the requested season the moment
    it has ANY rows. That is right on opening weekend, when 2026 has none and
    it falls back to 2025. It is wrong in week 2: 2026 now has one week of
    logs, so it selects 2026, every player has ONE prior game, `MIN_PRIOR_GAMES`
    is 3, and the model refuses everybody. Presence flips the choice to a
    season that cannot yet fit, and the panel empties out exactly when the
    season starts.

    So the season chosen here is the most recent one that can actually fit --
    the current season once it has enough games, last season until then. The
    section body always prints which, so a fallback is never invisible.

    This does NOT change `prop_model`'s arithmetic or its own resolver; the
    backtest still imports and grades the same function. It changes only which
    season this panel asks it about.
    """
    _sync_game_log_caches()
    fittable = _seasons_with_fittable_history()
    if not fittable:
        return None
    at_or_before = [value for value in fittable if value <= int(season)]
    return max(at_or_before) if at_or_before else max(fittable)


@lru_cache(maxsize=8)
def _roster_index_cached(
    season: int, stamp: tuple[tuple[str, int, int], ...]
) -> dict[str, tuple[dict[str, str], ...]]:
    """team_id -> the season's skill-position roster rows.

    STRICTLY the requested season. The snapshot is season-ACCUMULATING (44,395
    rows across 2025 and 2026 as of the 2026 build), so an unfiltered read
    would put last year's departed players on this year's card -- the exact
    defect `_ncaaf_player_box_section` refuses for actuals.
    """
    by_team: dict[str, list[dict[str, str]]] = {}
    for row in _read_snapshot(roster_snapshot_path(), "roster", "ncaaf_roster_snapshot.csv"):
        if str(row.get("season") or "").strip() != str(int(season)):
            continue
        position = str(row.get("position") or "").strip().upper()
        if position not in SKILL_POSITIONS:
            continue
        team_id = str(row.get("team_id") or "").strip()
        name = str(row.get("player_name") or "").strip()
        if not team_id or not name:
            continue
        by_team.setdefault(team_id, []).append({"player_name": name, "position": position})
    return {team_id: tuple(rows) for team_id, rows in by_team.items()}


def _roster_index(season: int) -> dict[str, tuple[dict[str, str], ...]]:
    return _roster_index_cached(int(season), _roster_stamp())


def market_anytime_td_index(
    *, season: int, week: int, home_team: str, away_team: str
) -> dict[str, dict[str, Any]]:
    """normalised player -> {price, implied} for THIS (season, week) capture.

    Empty when nothing was captured, which is the correct pregame state for a
    slate whose books have not posted -- not an error, and not something to
    backfill on the request path.

    Best price across books, using the same `_better` comparison the props
    panel uses, so a player's price reads identically in both places.
    """
    try:
        rows = _find_captured_game(
            _rows_by_game(int(season), int(week)), home_team=home_team, away_team=away_team
        )
    except Exception:  # noqa: BLE001 -- named below by the caller, never fatal
        return {}
    if not rows:
        return {}
    best: dict[str, int] = {}
    for row in rows:
        if str(row.get("market") or "").strip() != ANYTIME_TD_MARKET:
            continue
        player = _norm(row.get("player"))
        price = _american(row.get("over_price"))
        if not player or price is None:
            continue
        best[player] = _better(best.get(player), price) or price
    return {
        player: {
            "price": _format_price(price),
            # Implied, NOT fair -- a one-sided anytime-TD price carries the
            # book's margin and has no opposing side to de-vig against.
            # `props.py` names it the same way for the same reason.
            "implied": prop_model.american_to_probability(price),
        }
        for player, price in best.items()
    }


def squad_projections(
    *, season: int, week: int, team_name: str, home_team: str, away_team: str
) -> dict[str, Any]:
    """One side's per-player projections, with the denominators.

    Returns counts as well as rows because a thin table and a dead join render
    identically: `roster` is how many skill players the season's roster holds
    for this team, `refused` is how many the model declined for insufficient
    history, and `team_id` is None when the registry could not place the team
    at all. Each of those is a different empty state with a different fix.
    """
    team_id = _resolve_team_id(team_name)
    if not team_id:
        return {"team_id": None, "roster": 0, "refused": 0, "rows": [], "history_season": None}

    roster = _roster_index(int(season)).get(team_id, ())
    history_season = history_season_for(int(season))
    market = market_anytime_td_index(
        season=int(season), week=int(week), home_team=home_team, away_team=away_team
    )
    if history_season is None:
        return {
            "team_id": team_id,
            "roster": len(roster),
            "refused": 0,
            "rows": [],
            "history_season": None,
            "quoted": 0,
        }

    rows: list[dict[str, Any]] = []
    refused = 0
    for entry in roster:
        # Asked about the FITTABLE season, not the card's -- see
        # `history_season_for`. The model's own resolver then returns that
        # season unchanged, so its arithmetic is untouched.
        projection = prop_model.anytime_td_probability(entry["player_name"], history_season)
        if not projection:
            refused += 1
            continue
        quote = market.get(_norm(entry["player_name"])) or {}
        rows.append(
            {
                "player_name": entry["player_name"],
                "position": entry["position"],
                "probability": projection.get("probability"),
                "prior_games": projection.get("prior_games"),
                "prior_tds": projection.get("prior_tds"),
                "source": projection.get("source"),
                "history_season": projection.get("history_season"),
                "market_price": quote.get("price") or "",
                "market_implied": quote.get("implied"),
            }
        )
    rows.sort(key=lambda row: (-(row.get("probability") or 0.0), str(row.get("player_name") or "")))
    return {
        "team_id": team_id,
        "roster": len(roster),
        "refused": refused,
        "rows": rows,
        "history_season": history_season,
        # TRUE when the rate is fitted on an EARLIER season than the card's.
        # The body prints it; a prior-season fallback that is not stated is
        # how "last season's numbers" get onto this season's card.
        "history_is_fallback": int(history_season) != int(season),
        "quoted": sum(1 for row in rows if row.get("market_price")),
    }


def reset_caches() -> None:
    """Drop the memoised roster index -- for tests, and after a fresh build."""
    _roster_index_cached.cache_clear()
    _seasons_with_fittable_history.cache_clear()
    _LAST_GAME_LOG_STAMP.clear()
    prop_model.reset_caches()
