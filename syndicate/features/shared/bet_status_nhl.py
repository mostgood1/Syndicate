"""Resolve an NHL bet's CURRENT value from the NHL's own public API (api-web.nhle.com).

The sixth sibling of `bet_status_mlb` / `_wnba` / `_soccer` / `_nfl` / `_ncaaf`, and the same
shape: it answers "what is the thing this bet is on worth right now" and leaves every
judgement about winning and losing to `bet_status.resolve_bet_status`.

--------------------------------------------------------------------------
WHY THIS EXISTS
--------------------------------------------------------------------------

`paper_settlement._default_resolver` had no `nhl` builder, so every NHL order returned
`no_resolver_for_nhl` forever -- the gap `test_the_traded_sports_WITHOUT_a_resolver_are_pinned`
held open. The preseason starts 2026-09-19 [user, 2026-09-17: "build the NHL settler before
the 09-19 preseason"], and soccer and NFL were each wired only AFTER their bets had sat
ungradeable. This one is wired before the first NHL order exists.

`population_outcomes_nhl` (the scorecard settler) grades through the SAME reader, matcher and
classifier below -- one implementation of game matching and stat reading, not two.

--------------------------------------------------------------------------
THE FEED, AS MEASURED 2026-09-17 (not as assumed)
--------------------------------------------------------------------------

    GET /v1/score/{YYYY-MM-DD}                   every game filed under that date
    GET /v1/gamecenter/{id}/right-rail           `linescore.byPeriod` + `totals`
    GET /v1/gamecenter/{id}/boxscore             `playerByGameStats`, ABBREVIATED names
    GET /v1/gamecenter/{id}/play-by-play         `rosterSpots`: FULL names by `playerId`

  * urllib's DEFAULT User-Agent is REFUSED (HTTP 403). `Mozilla/5.0` and `syndicate-nhl/1.0`
    (the one `local_nhl_odds` already sends) both return 200. So, unlike the ESPN readers,
    this one MUST send a User-Agent.
  * THE FINAL SCORE CREDITS THE SHOOTOUT WINNER ONE GOAL. 2025020549 PHI @ NYR (2025-12-20,
    `lastPeriodType SO`): score 4-5, byPeriod [0-1, 4-1, 0-2, OT 0-0, SO 0-1], totals 4-5 --
    and NYR's skaters' `goals` sum to 4. So game lines settle on `score` (OT and the shootout
    included, as books settle moneyline / puck line / total), while player `goals` / `points`
    already EXCLUDE shootout goals, as books settle props.
  * THE BOX HAS NO FULL NAMES. `name.default` is "B. Brink"; the board carries OddsAPI's
    "Bobby Brink". Full names come from play-by-play `rosterSpots`, joined on `playerId`.
    Measured on 2025030413: all 29 players with OddsAPI prop lines that night matched a
    rosterSpots full name exactly.
  * THE BOX LISTS EVERY DRESSED PLAYER (18 skaters + 2 goalies). A player absent from a final
    box did not dress -> `dnp_void`. A goalie in the box with `toi` "00:00" dressed and did
    not play (2025030413: A. Hill) -> `dnp_void`.
  * PRESEASON (`gameType` 1) BOX SCORES ARE FULL. 2025010004/5/8: 18 skaters + 2 goalies a
    side with goals / assists / points / sog / blockedShots / toi, goalies with saves; goalies
    usually split the game (`starter` is None). Preseason games stay `gameState` FINAL (never
    OFF) a year later, so FINAL and OFF are both final.
  * SPLIT SQUADS ARE REAL. 2025-09-21 carried FLA @ NSH TWICE (19:00Z and 23:00Z) and both
    CGY @ EDM and EDM @ CGY at 00:00Z; 2026-09-19 carries MTL @ TOR and TOR @ MTL at 23:00Z.
    Team pair + date is NOT unique in the preseason, so the kickoff time decides, and a pair
    it cannot separate refuses as ambiguous.
  * OddsAPI's `commence_time` is not the API's `startTimeUTC`: 2026-06-06 CAR @ VGK was
    00:10Z on OddsAPI and 00:00Z on the NHL API (Game 4: 00:20Z vs 00:00Z).

--------------------------------------------------------------------------
THE JOIN
--------------------------------------------------------------------------

`event_id` is OddsAPI's hash and addresses nothing here, so the game is found by TEAM PAIR,
home against home. The map is `local_nhl_odds.TEAM_NAME_TO_ABBR` via `_team_abbr` -- the
same module that writes the NHL odds rows these orders come from -- and it is strict: an
unknown name is None, never a three-letter guess. The API side is its own `abbrev`.

  This paragraph used to add "`team_aliases.canonical_team("nhl", ...)` resolves NOTHING (its
  `_alias_map` has no NHL branch)". **That stopped being true on 2026-09-23**: `_alias_map`
  now has an NHL branch, DERIVED FROM THIS VERY TABLE, so `canonical_team("nhl", ...)`
  resolves. Nothing here changes -- this file never called it, and going through `_team_abbr`
  keeps the resolution in the module that owns the vocabulary. The note is corrected rather
  than deleted because it reads as a reason to prefer `_team_abbr`, and that reason is gone;
  the remaining reason is provenance, not capability.

Dates searched: the kickoff's US-Eastern date first (and the previous day for a pre-06:00 ET
kickoff), then the order's plan date -- `bet_status_nfl.order_capture_dates`, shared.

--------------------------------------------------------------------------
MARKETS, AND THE HOCKEY RULES
--------------------------------------------------------------------------

The row vocabulary is not settled for NHL (no NHL row has reached Layer 2 this season), so
the classifier is TOLERANT and names what it cannot read:

    props   `local_nhl_odds` writes the display codes SOG / GOALS / ASSISTS / POINTS (and has
            SAVES / BLOCKS in its map); the recorder key lowercases them; Kalshi quote capture
            files `player_points` / `player_saves`. All resolve through
            `market_keys.canonical_market_key("nhl", ...)` plus `_alternate` stripping.
    lines   h2h / spreads / totals (+ `_alt`, `h2h_3_way`, puck line spellings), segment
            `full` or `p1`..`p3`, or a `totals_p1`-style key carrying its own period.

    h2h, spreads(_alt), totals(_alt)   the FINAL score, OT and shootout credit included.
    h2h_3_way                          REGULATION (periods 1-3); a draw is possible and wins
                                       only for the draw side. Decidable once period 4 starts.
    p1 / p2 / p3                       that period's goals alone (p3 excludes OT); closed once
                                       the next period starts, at an intermission after it,
                                       or at the final. A level two-way period `h2h` pushes.
    props                              the player's final box stat. `goals` / `points` exclude
                                       the shootout (the box already does). Absent -> void.
    anytime goal scorer                goals > 0.5 (yes/no), shootout excluded.

Every refusal is NAMED, permanent ones (market, segment) before any read.
"""

from __future__ import annotations

import collections
import hashlib
import json
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from syndicate.features.shared.bet_status import FULL_GAME_SEGMENT
from syndicate.features.shared.segment_actuals import (
    REASON_SEGMENT_ACTUAL_PREFIX,
    REASON_UNSUPPORTED_SEGMENT_PREFIX,
    order_segment,
)

__all__ = [
    "NHLE_DEFAULT_BASE",
    "NhlFeed",
    "classify_nhl_order",
    "locate_nhl_game",
    "match_player",
    "nhl_status_resolver",
    "parse_boxscore_players",
    "parse_linescore",
    "parse_roster_spots",
    "parse_score_games",
    "resolve_classified",
    "resolve_nhl_order",
]

NHLE_DEFAULT_BASE = "https://api-web.nhle.com/v1"
# The feed refuses urllib's default agent (403, measured 2026-09-17). This is the agent
# `local_nhl_odds` already sends to the same host.
_USER_AGENT = "syndicate-nhl/1.0"
_FETCH_TIMEOUT_SECONDS = 10.0
# Bumped when a reducer's output shape changes, so a disk cache cannot serve an old shape.
READER_VERSION = "nhle-reader/1"

# ---- reasons --------------------------------------------------------------------------
REASON_NOT_NHL = "not_an_nhl_order"
# Exactly `unmapped_market`: `paper_settlement` names the market beside this reason.
REASON_UNKNOWN_MARKET = "unmapped_market"
REASON_TEAM_TOTAL = "team_totals_needs_a_per_team_score"
REASON_SEGMENT_MARKET_DISAGREE = "nhl_segment_disagrees_with_market_key"
REASON_PROP_MARKET = "nhl_prop_market_not_mapped"
REASON_PROP_SEGMENT = "nhl_prop_needs_full_game"
REASON_NO_MATCHUP = "no_home_away_teams_on_order"
REASON_TEAM_MAP_UNAVAILABLE = "nhl_team_map_unavailable"
REASON_TEAM_UNRESOLVED = "nhl_team_unresolved"
REASON_NO_GAME_DATE = "nhl_no_game_date_on_order"
REASON_SCHEDULE_UNAVAILABLE = "nhl_schedule_unavailable"
REASON_GAME_NOT_FOUND = "game_not_in_nhl_schedule"
REASON_GAME_AMBIGUOUS = "nhl_game_ambiguous"
REASON_START_MISMATCH = "nhl_game_start_time_mismatch"
# Same string `game_line_bet` uses for the same finding.
REASON_HOME_AWAY = "home_away_disagree_between_sources"
REASON_POSTPONED = "nhl_game_postponed_or_cancelled"
# Contains "unavailable" on purpose: `model_scorecard` holds a date open on it.
REASON_STATE_UNREADABLE = "nhl_game_state_unavailable"
REASON_NO_SCORES = "game_carries_no_scores"
REASON_LINESCORE_UNAVAILABLE = "nhl_linescore_unavailable"
REASON_LINESCORE_DISAGREES = "nhl_linescore_disagrees_with_final_score"
REASON_REGULATION_UNAVAILABLE = "nhl_regulation_actual_unavailable"
REASON_BOX_UNAVAILABLE = "nhl_player_box_unavailable"
REASON_ROSTER_UNAVAILABLE = "nhl_roster_names_unavailable"
REASON_LIMITED_SCORING = "nhl_limited_scoring_game"
REASON_DNP_VOID = "dnp_void"
REASON_PLAYER_NOT_IN_LIVE_BOX = "nhl_player_not_in_live_box_yet"
REASON_PLAYER_AMBIGUOUS = "nhl_player_ambiguous_in_box"
# Same last name and first initial as a dressed player, but a first name that is not a
# prefix either way ("Nick" / "Nicholas"): not provably absent, so NOT voided.
REASON_PLAYER_NAME_UNMATCHED = "nhl_player_name_unmatched"
REASON_TOI_UNAVAILABLE = "nhl_player_toi_unavailable"
REASON_STAT_UNAVAILABLE = "nhl_stat_not_in_box"

FINAL_STATES = frozenset({"FINAL", "OFF"})
LIVE_STATES = frozenset({"LIVE", "CRIT"})
PREGAME_STATES = frozenset({"FUT", "PRE"})
CALLED_OFF_SCHEDULE_STATES = frozenset({"PPD", "CNCL", "SUSP"})

REGULATION_PERIODS = 3
PERIOD_SEGMENTS: Mapping[str, int] = {"p1": 1, "p2": 2, "p3": 3}
_SEGMENT_ALIASES: Mapping[str, str] = {
    "full": FULL_GAME_SEGMENT, "full_game": FULL_GAME_SEGMENT, "game": FULL_GAME_SEGMENT,
    **{alias: f"p{n}" for n, words in ((1, ("1st", "first")), (2, ("2nd", "second")), (3, ("3rd", "third")))
       for alias in (f"p{n}", f"{n}p", f"period{n}", f"period_{n}", f"{words[0]}_period", f"{words[1]}_period")},
}

# A kickoff within this of the API's start is the same game; with two such games (split
# squads), only one within the tighter window may be chosen.
_START_WINDOW = timedelta(hours=6)
_START_EXACT = timedelta(minutes=90)

TOTAL_MARKETS = frozenset({"totals", "totals_alt"})
LINE_MARKETS = frozenset({"h2h", "h2h_3_way", "spreads", "spreads_alt"})
_GAME_MARKETS: Mapping[str, str] = {
    "h2h": "h2h", "moneyline": "h2h", "money_line": "h2h", "ml": "h2h",
    "h2h_3_way": "h2h_3_way", "h2h_3way": "h2h_3_way", "3_way": "h2h_3_way", "3way": "h2h_3_way",
    "three_way": "h2h_3_way", "moneyline_3_way": "h2h_3_way", "3_way_moneyline": "h2h_3_way",
    "regulation_moneyline": "h2h_3_way", "1x2": "h2h_3_way",
    "spreads": "spreads", "spread": "spreads", "puck_line": "spreads", "puckline": "spreads",
    "handicap": "spreads",
    "spreads_alt": "spreads_alt", "alternate_spreads": "spreads_alt", "alt_spreads": "spreads_alt",
    "alternate_puck_line": "spreads_alt",
    "totals": "totals", "total": "totals", "over_under": "totals", "game_total": "totals",
    "totals_alt": "totals_alt", "alternate_totals": "totals_alt", "alt_totals": "totals_alt",
}
_TEAM_TOTAL_MARKETS = frozenset({"team_totals", "team_total", "team_totals_alt", "alternate_team_totals"})

# canonical prop market -> box field
_PROP_STATS: Mapping[str, str] = {
    "player_points": "points",
    "player_assists": "assists",
    "player_goals": "goals",
    "player_shots_on_goal": "sog",
    "player_blocked_shots": "blocked_shots",
    "player_blocks": "blocked_shots",
    "player_saves": "saves",
    "player_goalie_saves": "saves",
    "player_total_saves": "saves",
    "goalie_saves": "saves",
}
_ANYTIME_GOAL_MARKETS = frozenset({
    "player_goal_scorer_anytime", "player_anytime_goal_scorer", "anytime_goal_scorer",
    "anytime_goalscorer", "player_anytime_goal", "anytime_goal", "goal_scorer_anytime",
    "anytime_goal_scorer_yes",
})
_ANYTIME_LINE = 0.5
_GOALIE_STATS = frozenset({"saves"})

_HOME_AWAY_DRAW_TOKENS = frozenset({
    "home", "home_team", "h", "away", "away_team", "a", "road", "draw", "tie", "x", "the draw",
})


def _norm(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _token(value: Any) -> str:
    return _norm(value).replace(" ", "_").replace("-", "_")


def _as_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return None if parsed != parsed else parsed


def _as_int(value: Any) -> int | None:
    parsed = _as_float(value)
    return None if parsed is None else int(parsed)


def _default_text(value: Any) -> str:
    if isinstance(value, Mapping):
        value = value.get("default")
    return str(value or "").strip()


def _parse_utc(value: Any) -> datetime | None:
    text = str(value or "").strip()
    # A bare date carries no time and must not become midnight UTC.
    if len(text) <= 10:
        return None
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _toi_seconds(value: Any) -> int | None:
    minutes, sep, seconds = str(value or "").strip().partition(":")
    if not sep:
        return None
    try:
        return int(minutes) * 60 + int(seconds)
    except ValueError:
        return None


def _nhle_base() -> str:
    return (os.getenv("NHLE_BASE_URL") or NHLE_DEFAULT_BASE).rstrip("/")


def _default_fetch_json(url: str) -> Any:
    """GET -> parsed JSON, or None. Never raises. Sends a User-Agent: the feed 403s without one."""
    import urllib.request

    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=_FETCH_TIMEOUT_SECONDS) as response:  # noqa: S310
            return json.loads(response.read().decode("utf-8"))
    except Exception:
        return None


# ---------------------------------------------------------------------------
# payload readers -- pure, and each returns None for a payload that is not its shape
# ---------------------------------------------------------------------------


def parse_score_games(payload: Any) -> list[dict[str, Any]] | None:
    """`/v1/score/{date}` -> one flat dict per game."""
    if not isinstance(payload, Mapping) or not isinstance(payload.get("games"), list):
        return None
    games: list[dict[str, Any]] = []
    for game in payload["games"]:
        if not isinstance(game, Mapping) or game.get("id") is None:
            continue
        home = game.get("homeTeam") if isinstance(game.get("homeTeam"), Mapping) else {}
        away = game.get("awayTeam") if isinstance(game.get("awayTeam"), Mapping) else {}
        period = game.get("periodDescriptor") if isinstance(game.get("periodDescriptor"), Mapping) else {}
        clock = game.get("clock") if isinstance(game.get("clock"), Mapping) else {}
        outcome = game.get("gameOutcome") if isinstance(game.get("gameOutcome"), Mapping) else {}
        games.append({
            "game_id": str(game.get("id")),
            "game_type": _as_int(game.get("gameType")),
            "game_date": str(game.get("gameDate") or ""),
            "start": str(game.get("startTimeUTC") or ""),
            "state": str(game.get("gameState") or "").strip().upper(),
            "schedule_state": str(game.get("gameScheduleState") or "").strip().upper(),
            "home_abbr": str(home.get("abbrev") or "").strip().upper(),
            "away_abbr": str(away.get("abbrev") or "").strip().upper(),
            "home_name": _default_text(home.get("name")) or _default_text(home.get("commonName")),
            "away_name": _default_text(away.get("name")) or _default_text(away.get("commonName")),
            "home_score": _as_int(home.get("score")),
            "away_score": _as_int(away.get("score")),
            "period": _as_int(period.get("number")) if period else _as_int(game.get("period")),
            "period_type": str(period.get("periodType") or "").strip().upper(),
            "in_intermission": bool(clock.get("inIntermission")),
            "last_period_type": str(outcome.get("lastPeriodType") or "").strip().upper(),
        })
    return games


def parse_linescore(payload: Any) -> dict[str, Any] | None:
    """`/v1/gamecenter/{id}/right-rail` -> `{periods: [{number, type, home, away}], totals}`."""
    if not isinstance(payload, Mapping) or not isinstance(payload.get("linescore"), Mapping):
        return None
    linescore = payload["linescore"]
    by_period = linescore.get("byPeriod")
    if not isinstance(by_period, list):
        return None
    periods: list[dict[str, Any]] = []
    for entry in by_period:
        if not isinstance(entry, Mapping):
            continue
        descriptor = entry.get("periodDescriptor") if isinstance(entry.get("periodDescriptor"), Mapping) else {}
        number = _as_int(descriptor.get("number"))
        if number is None:
            continue
        periods.append({
            "number": number,
            "type": str(descriptor.get("periodType") or "").strip().upper(),
            "home": _as_int(entry.get("home")),
            "away": _as_int(entry.get("away")),
        })
    totals = linescore.get("totals") if isinstance(linescore.get("totals"), Mapping) else {}
    return {"periods": periods, "totals": {"home": _as_int(totals.get("home")), "away": _as_int(totals.get("away"))}}


def parse_boxscore_players(payload: Any) -> dict[str, Any] | None:
    """`/v1/gamecenter/{id}/boxscore` -> every dressed player's settlement fields."""
    if not isinstance(payload, Mapping) or not isinstance(payload.get("playerByGameStats"), Mapping):
        return None
    by_team = payload["playerByGameStats"]
    players: list[dict[str, Any]] = []
    for side in ("homeTeam", "awayTeam"):
        team = payload.get(side) if isinstance(payload.get(side), Mapping) else {}
        block = by_team.get(side) if isinstance(by_team.get(side), Mapping) else {}
        abbr = str(team.get("abbrev") or "").strip().upper()
        for group in ("forwards", "defense", "goalies"):
            for entry in block.get(group) or []:
                if not isinstance(entry, Mapping) or entry.get("playerId") is None:
                    continue
                goalie = group == "goalies"
                row: dict[str, Any] = {
                    "player_id": str(entry.get("playerId")),
                    "team_abbr": abbr,
                    "role": "goalie" if goalie else "skater",
                    "name_abbrev": _default_text(entry.get("name")),
                    "toi_seconds": _toi_seconds(entry.get("toi")),
                }
                if goalie:
                    row["saves"] = _as_int(entry.get("saves"))
                    row["shots_against"] = _as_int(entry.get("shotsAgainst"))
                else:
                    row["goals"] = _as_int(entry.get("goals"))
                    row["assists"] = _as_int(entry.get("assists"))
                    row["points"] = _as_int(entry.get("points"))
                    row["sog"] = _as_int(entry.get("sog"))
                    row["blocked_shots"] = _as_int(entry.get("blockedShots"))
                players.append(row)
    return {
        "state": str(payload.get("gameState") or "").strip().upper(),
        "limited_scoring": bool(payload.get("limitedScoring")),
        "players": players,
    }


def parse_roster_spots(payload: Any) -> dict[str, Any] | None:
    """`/v1/gamecenter/{id}/play-by-play` -> `playerId` -> full first / last name. Plays dropped."""
    if not isinstance(payload, Mapping) or not isinstance(payload.get("rosterSpots"), list):
        return None
    names: dict[str, dict[str, str]] = {}
    for spot in payload["rosterSpots"]:
        if not isinstance(spot, Mapping) or spot.get("playerId") is None:
            continue
        names[str(spot["playerId"])] = {
            "first": _default_text(spot.get("firstName")),
            "last": _default_text(spot.get("lastName")),
        }
    return {"state": str(payload.get("gameState") or "").strip().upper(), "names": names}


# ---------------------------------------------------------------------------
# the feed: memoised per instance, and optionally a disk cache for FINAL payloads
# ---------------------------------------------------------------------------


# PROCESS-WIDE CACHE for the paper-settlement resolver. `portfolio_commit` builds a NEW
# resolver (and so a new feed) on every cycle, so a per-instance memo alone re-reads the score,
# box, roster and linescore of every NHL game with an order on EVERY cycle -- ~4 requests per
# game per cycle, measured from the endpoints this module reads. Reduced payloads that can no
# longer change are kept for the process; anything else for `LIVE_TTL_SECONDS`. Failures are
# never cached. Bounded by `SHARED_CACHE_MAX` entries, oldest evicted first.
LIVE_TTL_SECONDS = 60.0
SHARED_CACHE_MAX = 512
_SHARED_CACHE: dict[str, tuple[float | None, Any]] = {}
_SHARED_LOCK = threading.Lock()


class NhlFeed:
    """Sequential reads of api-web.nhle.com, one per path per instance.

    `fetch_json(url) -> payload | None`; None means "use the module default", resolved at call
    time so a test can substitute it. `cache_dir` keeps the REDUCED form of a payload that can
    no longer change (a final game, a date whose every game is final) between runs.
    `shared_cache` (a dict, e.g. `_SHARED_CACHE`) keeps reduced payloads across feeds in one
    process: immutable ones indefinitely, live ones for `LIVE_TTL_SECONDS`.
    """

    def __init__(self, *, fetch_json: Callable[[str], Any] | None = None, cache_dir: Path | str | None = None,
                 shared_cache: dict[str, tuple[float | None, Any]] | None = None) -> None:
        self._fetch_json = fetch_json
        self._cache_dir = Path(cache_dir) if cache_dir else None
        self._shared = shared_cache
        self._memo: dict[str, Any] = {}
        self.counters: collections.Counter[str] = collections.Counter()

    def games_on(self, day: str) -> list[dict[str, Any]] | None:
        return self._get(
            f"/score/{day}",
            reduce=parse_score_games,
            immutable=lambda games: bool(games) and all(game["state"] in FINAL_STATES for game in games),
        )

    def linescore(self, game: Mapping[str, Any]) -> dict[str, Any] | None:
        final = game.get("state") in FINAL_STATES
        return self._get(f"/gamecenter/{game['game_id']}/right-rail", reduce=parse_linescore, immutable=lambda _v: final)

    def box(self, game: Mapping[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
        """`({limited_scoring, players}, None)` with full names on every player, or `(None, reason)`."""
        final = game.get("state") in FINAL_STATES
        stats = self._get(
            f"/gamecenter/{game['game_id']}/boxscore",
            reduce=parse_boxscore_players,
            immutable=lambda value: final and value.get("state") in FINAL_STATES,
        )
        if stats is None:
            return None, REASON_BOX_UNAVAILABLE
        roster = self._get(
            f"/gamecenter/{game['game_id']}/play-by-play",
            reduce=parse_roster_spots,
            immutable=lambda value: final and value.get("state") in FINAL_STATES,
        )
        if roster is None:
            return None, REASON_ROSTER_UNAVAILABLE
        players = []
        for row in stats["players"]:
            merged = dict(row)
            name = roster["names"].get(row["player_id"])
            if name and (name["first"] or name["last"]):
                merged["first"], merged["last"] = name["first"], name["last"]
            else:
                # Not in rosterSpots: the box's own "A. Panarin" -- an initial, matched by prefix.
                first, _, last = row["name_abbrev"].partition(" ")
                merged["first"], merged["last"] = first, last
            merged["player_name"] = f"{merged['first']} {merged['last']}".strip()
            players.append(merged)
        return {"limited_scoring": stats["limited_scoring"], "players": players}, None

    def _get(self, path: str, *, reduce: Callable[[Any], Any], immutable: Callable[[Any], bool]) -> Any:
        if path in self._memo:
            return self._memo[path]
        if self._shared is not None:
            with _SHARED_LOCK:
                hit = self._shared.get(path)
            if hit is not None and (hit[0] is None or time.monotonic() < hit[0]):
                self.counters["nhle_shared_cache_hits"] += 1
                self._memo[path] = hit[1]
                return hit[1]
        cached = self._cache_path(path)
        if cached is not None and cached.is_file():
            try:
                value = json.loads(cached.read_text(encoding="utf-8"))
                self.counters["nhle_disk_cache_hits"] += 1
                self._memo[path] = value
                return value
            except (OSError, ValueError):
                pass
        self.counters["nhle_requests"] += 1
        fetch = self._fetch_json or _default_fetch_json
        try:
            payload = fetch(f"{_nhle_base()}{path}")
        except Exception:
            payload = None
        value = None
        if payload is not None:
            try:
                value = reduce(payload)
            except Exception:
                value = None
        if value is None:
            self.counters["nhle_failures"] += 1
        self._memo[path] = value
        if value is not None and self._shared is not None:
            try:
                final = bool(immutable(value))
            except Exception:
                final = False
            with _SHARED_LOCK:
                self._shared[path] = (None if final else time.monotonic() + LIVE_TTL_SECONDS, value)
                while len(self._shared) > SHARED_CACHE_MAX:
                    self._shared.pop(next(iter(self._shared)))
        if value is not None and cached is not None:
            try:
                keep = bool(immutable(value))
            except Exception:
                keep = False
            if keep:
                try:
                    cached.parent.mkdir(parents=True, exist_ok=True)
                    cached.write_text(json.dumps(value), encoding="utf-8")
                except OSError:
                    pass
        return value

    def _cache_path(self, path: str) -> Path | None:
        if self._cache_dir is None:
            return None
        digest = hashlib.sha1(f"{READER_VERSION}|{path}".encode("utf-8")).hexdigest()
        return self._cache_dir / "nhle" / f"{digest}.json"


# ---------------------------------------------------------------------------
# classification -- pure, and every permanent refusal happens here, before any read
# ---------------------------------------------------------------------------


def normalize_nhl_segment(value: Any) -> str:
    token = _token(value)
    return _SEGMENT_ALIASES.get(token, token) or FULL_GAME_SEGMENT


def _strip_alternate(token: str) -> str:
    for suffix in ("_alternate", "_alt"):
        if token.endswith(suffix):
            return token[: -len(suffix)]
    return token


def _prop_market(market: Any) -> tuple[str | None, bool]:
    """(box field, is anytime-goal) for a prop market, or (None, False)."""
    from syndicate.features.shared.market_keys import canonical_market_key

    token = _token(market)
    if not token:
        return None, False
    if token in _ANYTIME_GOAL_MARKETS or _strip_alternate(token) in _ANYTIME_GOAL_MARKETS:
        return "goals", True
    stripped = _strip_alternate(token)
    for candidate in (token, stripped):
        canonical = _strip_alternate(str(canonical_market_key("nhl", candidate) or ""))
        if canonical in _PROP_STATS:
            return _PROP_STATS[canonical], False
        if candidate in _PROP_STATS:
            return _PROP_STATS[candidate], False
    return None, False


def _game_market(market: Any) -> tuple[str, str] | str | None:
    """`(canonical market, segment)`, the string "team_total", or None."""
    from syndicate.features.shared.market_keys import canonical_game_market
    from syndicate.features.shared.market_segments import split_segment_market_key

    token = _token(market)
    if not token:
        return None
    if token in _TEAM_TOTAL_MARKETS:
        return "team_total"
    if token in _GAME_MARKETS:
        return _GAME_MARKETS[token], FULL_GAME_SEGMENT
    split = split_segment_market_key("nhl", token)
    if split:
        segment, canonical = split
        return (canonical, segment) if canonical in _GAME_MARKETS.values() else None
    # A display label ("1st Period Total", "Alternate Puck Line") -- the shared parser.
    parsed = canonical_game_market(str(market or ""))
    if not parsed:
        return None
    for segment in PERIOD_SEGMENTS:
        if parsed.endswith(f"_{segment}"):
            base = parsed[: -len(segment) - 1]
            return (base, segment) if base in _GAME_MARKETS.values() else None
    return (parsed, FULL_GAME_SEGMENT) if parsed in _GAME_MARKETS.values() else None


def classify_nhl_order(order: Mapping[str, Any]) -> dict[str, Any]:
    """`{kind, market, segment, stat, anytime}` or `{unavailable_reason}`. Reads nothing."""
    if not isinstance(order, Mapping) or _norm(order.get("sport")) != "nhl":
        return {"unavailable_reason": REASON_NOT_NHL}
    raw_segment = order_segment(order)
    segment = normalize_nhl_segment(raw_segment)
    if segment != FULL_GAME_SEGMENT and segment not in PERIOD_SEGMENTS:
        return {"unavailable_reason": f"{REASON_UNSUPPORTED_SEGMENT_PREFIX}{raw_segment}"}

    if order.get("player_name"):
        # A PLAYER PROP. Segment first -- the box is whole-game, so a period prop can never
        # be graded from it, whatever its market.
        if segment != FULL_GAME_SEGMENT:
            return {"unavailable_reason": REASON_PROP_SEGMENT}
        stat, anytime = _prop_market(order.get("market"))
        if stat is None:
            return {"unavailable_reason": REASON_PROP_MARKET}
        return {"kind": "prop", "market": _token(order.get("market")), "segment": segment, "stat": stat,
                "anytime": anytime}

    game_market = _game_market(order.get("market"))
    if game_market == "team_total":
        return {"unavailable_reason": REASON_TEAM_TOTAL}
    if game_market is None:
        return {"unavailable_reason": REASON_UNKNOWN_MARKET}
    market, market_segment = game_market
    if market_segment != FULL_GAME_SEGMENT:
        if segment not in (FULL_GAME_SEGMENT, market_segment):
            return {"unavailable_reason": REASON_SEGMENT_MARKET_DISAGREE}
        segment = market_segment
    return {"kind": "total" if market in TOTAL_MARKETS else "line", "market": market, "segment": segment,
            "stat": None, "anytime": False}


# ---------------------------------------------------------------------------
# the join
# ---------------------------------------------------------------------------


def _team_abbr(value: Any) -> str | None:
    from syndicate.local_nhl_odds import _team_abbr as odds_team_abbr

    return odds_team_abbr(value)


def locate_nhl_game(
    order: Mapping[str, Any], feed: NhlFeed, selected_date: str | None = None
) -> tuple[dict[str, Any] | None, str | None]:
    """`(game, None)` or `(None, reason)`: team pair home-against-home, then the kickoff time."""
    from syndicate.features.shared.bet_status_nfl import order_capture_dates

    home_name, away_name = order.get("home_team"), order.get("away_team")
    if not home_name or not away_name:
        return None, REASON_NO_MATCHUP
    try:
        home, away = _team_abbr(home_name), _team_abbr(away_name)
    except ImportError:  # pragma: no cover - deploy-skew guard
        return None, REASON_TEAM_MAP_UNAVAILABLE
    if not home or not away or home == away:
        return None, REASON_TEAM_UNRESOLVED
    dates = order_capture_dates(order, str(selected_date or ""))
    if not dates:
        return None, REASON_NO_GAME_DATE

    exact: dict[str, dict[str, Any]] = {}
    swapped = False
    for day in dates:
        for game in feed.games_on(day) or ():
            if game["home_abbr"] == home and game["away_abbr"] == away:
                exact[game["game_id"]] = game
            elif game["home_abbr"] == away and game["away_abbr"] == home:
                swapped = True
    if not exact:
        # The kickoff date's schedule unread is TRANSIENT, whatever the plan date held.
        if feed.games_on(dates[0]) is None:
            return None, REASON_SCHEDULE_UNAVAILABLE
        return None, REASON_HOME_AWAY if swapped else REASON_GAME_NOT_FOUND

    candidates = list(exact.values())
    kickoff = _parse_utc(order.get("commence_time"))
    if kickoff is None:
        return (candidates[0], None) if len(candidates) == 1 else (None, REASON_GAME_AMBIGUOUS)
    timed = []
    for game in candidates:
        start = _parse_utc(game.get("start"))
        if start is not None:
            timed.append((abs(start - kickoff), game))
    near = [game for delta, game in timed if delta <= _START_WINDOW]
    if len(near) == 1:
        return near[0], None
    if len(near) > 1:
        close = [game for delta, game in timed if delta <= _START_EXACT]
        return (close[0], None) if len(close) == 1 else (None, REASON_GAME_AMBIGUOUS)
    return None, REASON_START_MISMATCH


def match_player(players: list[Mapping[str, Any]], name: Any) -> tuple[Mapping[str, Any] | None, str | None]:
    """`(row, None)`, `(None, "absent")`, or `(None, reason)`.

    Exact full-name key first (`bet_status_nfl._player_key`: accents, initials, suffixes).
    Then the same last name with a first name that is a PREFIX either way ("Alex" /
    "Alexander", "Mitch" / "Mitchell"), unique. A same-last-name, same-initial player that is
    not prefix-compatible is NOT proof of absence and refuses rather than voids.
    """
    from syndicate.features.shared.bet_status_nfl import _player_key

    key = _player_key(name)
    if not key:
        return None, REASON_PLAYER_NAME_UNMATCHED
    exact = [row for row in players if _player_key(row.get("player_name")) == key]
    if len(exact) == 1:
        return exact[0], None
    if len(exact) > 1:
        return None, REASON_PLAYER_AMBIGUOUS
    tokens = key.split()
    if len(tokens) >= 2:
        first, last = tokens[0], " ".join(tokens[1:])
        same_last = [row for row in players if _player_key(row.get("last")) == last]
        compatible = []
        for row in same_last:
            theirs = _player_key(row.get("first"))
            if theirs and (theirs.startswith(first) or first.startswith(theirs)):
                compatible.append(row)
        if len(compatible) == 1:
            return compatible[0], None
        if len(compatible) > 1:
            return None, REASON_PLAYER_AMBIGUOUS
        if any(_player_key(row.get("first"))[:1] == first[:1] for row in same_last):
            return None, REASON_PLAYER_NAME_UNMATCHED
    return None, "absent"


# ---------------------------------------------------------------------------
# resolution
# ---------------------------------------------------------------------------


def _translate_side(side: Any, game: Mapping[str, Any]) -> Any:
    """A team-name side -> `home` / `away` through the NHL map (`canonical_team` knows no NHL club)."""
    token = _norm(side)
    if not token or token in _HOME_AWAY_DRAW_TOKENS:
        return side
    try:
        abbr = _team_abbr(side)
    except ImportError:  # pragma: no cover - deploy-skew guard
        return side
    if abbr and abbr == game.get("home_abbr"):
        return "home"
    if abbr and abbr == game.get("away_abbr"):
        return "away"
    return side


def _period_entry(linescore: Mapping[str, Any], number: int) -> Mapping[str, Any] | None:
    found = [entry for entry in linescore["periods"] if entry["number"] == number]
    return found[0] if len(found) == 1 else None


def _linescore_agrees(linescore: Mapping[str, Any], game: Mapping[str, Any]) -> bool:
    """At the final: every period (shootout included) sums to the totals, and the totals to the score."""
    totals = linescore["totals"]
    if totals["home"] is None or totals["away"] is None:
        return False
    periods = linescore["periods"]
    if any(entry["home"] is None or entry["away"] is None for entry in periods):
        return False
    if sum(entry["home"] for entry in periods) != totals["home"] or sum(entry["away"] for entry in periods) != totals["away"]:
        return False
    return totals["home"] == game.get("home_score") and totals["away"] == game.get("away_score")


def _resolve_line(order: Mapping[str, Any], classified: Mapping[str, Any], game: Mapping[str, Any], feed: NhlFeed) -> dict[str, Any]:
    from syndicate.features.shared.game_line_bet import game_line_view

    market, segment = classified["market"], classified["segment"]
    final = game["state"] in FINAL_STATES
    current_period = game.get("period") or 0
    settled_segment = segment

    if segment == FULL_GAME_SEGMENT and market != "h2h_3_way":
        home, away = game.get("home_score"), game.get("away_score")
        if home is None or away is None:
            return {"unavailable_reason": REASON_NO_SCORES}
        complete, source = final, "nhl_final"
    else:
        linescore = feed.linescore(game)
        if linescore is None:
            return {"unavailable_reason": REASON_LINESCORE_UNAVAILABLE}
        if final and not _linescore_agrees(linescore, game):
            return {"unavailable_reason": REASON_LINESCORE_DISAGREES}
        source = "nhl_linescore"
        if segment == FULL_GAME_SEGMENT:
            # THREE-WAY = REGULATION. Periods 1-3 only; a tie after sixty minutes is the draw
            # whatever overtime or the shootout did afterwards.
            settled_segment = "regulation"
            complete = final or current_period > REGULATION_PERIODS
            entries = [_period_entry(linescore, number) for number in range(1, REGULATION_PERIODS + 1)]
            present = [entry for entry in entries if entry is not None]
            if complete and len(present) != REGULATION_PERIODS:
                return {"unavailable_reason": REASON_REGULATION_UNAVAILABLE}
            if any(entry["home"] is None or entry["away"] is None for entry in present):
                return {"unavailable_reason": REASON_REGULATION_UNAVAILABLE}
            home = sum(entry["home"] for entry in present)
            away = sum(entry["away"] for entry in present)
        else:
            number = PERIOD_SEGMENTS[segment]
            if not final and current_period < number:
                return {"current_value": None, "is_final": False, "started": False}
            entry = _period_entry(linescore, number)
            if entry is None or entry["home"] is None or entry["away"] is None:
                return {"unavailable_reason": f"{REASON_SEGMENT_ACTUAL_PREFIX}{segment}"}
            complete = final or current_period > number or (current_period == number and bool(game.get("in_intermission")))
            home, away = entry["home"], entry["away"]

    scoreboard = {
        "is_final": bool(complete),
        "started": True,
        "matched_by": "nhl_api_team_pair",
        "home_score": float(home),
        "away_score": float(away),
        "home_name": game.get("home_name") or game.get("home_abbr"),
        "away_name": game.get("away_name") or game.get("away_abbr"),
        "nhl_game_id": game.get("game_id"),
        "source": source,
    }
    if settled_segment != FULL_GAME_SEGMENT:
        scoreboard["settled_segment"] = settled_segment

    if classified["kind"] == "total":
        return {"current_value": float(home + away), **scoreboard}

    view = game_line_view(
        sport="nhl",
        market=market,
        side=_translate_side(order.get("side"), game),
        line=order.get("line"),
        home_team=game.get("home_name"),
        away_team=game.get("away_name"),
        home_score=home,
        away_score=away,
        # Two-way: a level score (a period, or a game that somehow ends tied) PUSHES.
        # `h2h_3_way` is three-way by name in `game_line_view` regardless.
        draw_possible=False,
    )
    if view.get("unavailable_reason"):
        return view
    return {"current_value": view["current_value"], "side": view["side"], "line": view["line"], **scoreboard}


def _resolve_prop(order: Mapping[str, Any], classified: Mapping[str, Any], game: Mapping[str, Any], feed: NhlFeed) -> dict[str, Any]:
    final = game["state"] in FINAL_STATES
    box, why = feed.box(game)
    if box is None:
        return {"unavailable_reason": why or REASON_BOX_UNAVAILABLE}
    if box["limited_scoring"]:
        return {"unavailable_reason": REASON_LIMITED_SCORING}
    players = box["players"]
    if not players:
        # An empty box at the final is a feed gap, not twenty scratches.
        return {"unavailable_reason": REASON_BOX_UNAVAILABLE}
    row, why = match_player(players, order.get("player_name"))
    if why == "absent":
        return {"unavailable_reason": REASON_DNP_VOID if final else REASON_PLAYER_NOT_IN_LIVE_BOX}
    if row is None:
        return {"unavailable_reason": why}

    toi = row.get("toi_seconds")
    if toi is None:
        return {"unavailable_reason": REASON_TOI_UNAVAILABLE}
    if final and toi <= 0:
        # Dressed, never on the ice -- a backup goalie, a warm-up scratch. Books void.
        return {"unavailable_reason": REASON_DNP_VOID}

    stat = classified["stat"]
    if (stat in _GOALIE_STATS) != (row["role"] == "goalie"):
        return {"unavailable_reason": REASON_STAT_UNAVAILABLE}
    value = row.get(stat)
    if value is None:
        return {"unavailable_reason": REASON_STAT_UNAVAILABLE}
    resolved: dict[str, Any] = {
        "current_value": float(value),
        "is_final": final,
        "started": True,
        "source": "nhl_box",
        "nhl_game_id": game.get("game_id"),
    }
    if classified["anytime"] and _as_float(order.get("line")) is None:
        resolved["line"] = _ANYTIME_LINE
    return resolved


def resolve_classified(
    order: Mapping[str, Any], classified: Mapping[str, Any], feed: NhlFeed, selected_date: str | None = None
) -> dict[str, Any]:
    """The resolver dict for an already-classified order. Reads the feed."""
    game, why = locate_nhl_game(order, feed, selected_date)
    if game is None:
        return {"unavailable_reason": why}
    if game.get("schedule_state") in CALLED_OFF_SCHEDULE_STATES:
        return {"unavailable_reason": REASON_POSTPONED}
    state = game.get("state")
    if state in PREGAME_STATES:
        return {"current_value": None, "is_final": False, "started": False}
    if state not in FINAL_STATES and state not in LIVE_STATES:
        return {"unavailable_reason": REASON_STATE_UNREADABLE}
    if classified["kind"] == "prop":
        return _resolve_prop(order, classified, game, feed)
    return _resolve_line(order, classified, game, feed)


def resolve_nhl_order(order: Mapping[str, Any], feed: NhlFeed, selected_date: str | None = None) -> dict[str, Any]:
    classified = classify_nhl_order(order)
    if classified.get("unavailable_reason"):
        return classified
    return resolve_classified(order, classified, feed, selected_date)


def nhl_status_resolver(selected_date: str):
    """A resolver `paper_settlement` can inject, for NHL orders.

    Constructing it reads nothing. One feed per resolver, so a slate of forty orders on one
    game is one schedule read, one box, one roster and one linescore -- not forty of each.
    """
    feed = NhlFeed(shared_cache=_SHARED_CACHE)

    def resolve(order: Mapping[str, Any]) -> dict[str, Any]:
        try:
            return resolve_nhl_order(order, feed, selected_date)
        except Exception as exc:  # never raise into the settlement loop
            return {"unavailable_reason": f"nhl_resolver_error:{type(exc).__name__}"}

    return resolve
