"""Settle NFL / NCAAF / WNBA props and segment lines in the priced population, from ESPN.

`scripts/bucket_search.py::grade_population` grades full-game h2h / spreads / totals from
final scores and, for every sport but MLB, counts a player prop `player_prop` and a segment
row `segment_not_full_game`. Measured 2026-09-15/16: NFL 2,621 props and 36 h1 rows, NCAAF
2,558 props, and from 2026-09-17 WNBA quarter/half lines and ten prop markets -- none of it
gradeable. This is the `extra_settler(shaped, view)` hook it consults BEFORE those skips:

    None                  not handled here; `grade_population` carries on as before
    (result, reason)      result 'win' | 'loss' | 'push', or None with a NAMED reason

WHAT IT HANDLES
    props       every player prop for nfl / ncaaf / wnba (an unmapped market is a named
                refusal, not a passthrough, so it is counted as what it is)
    segments    q1..q4 / h1 / h2 for h2h, h2h_3_way, spreads(_alt), totals(_alt)
    full game   only the markets `grade_population` cannot grade from a final score:
                h2h_3_way, spreads_alt, totals_alt. Full-game h2h / spreads / totals pass
                through untouched -- that grader already owns them.

THE JOIN. A record's `event_id` is OddsAPI's hash and ESPN's is not in that namespace, so
the game is found on ESPN's scoreboard for the kickoff's US-Eastern date(s)
(`bet_status_nfl.kickoff_capture_dates`) by the TEAM PAIR, home against home:
`team_aliases.canonical_team` for NFL and WNBA, and for NCAAF the registry
(`ncaaf_team_registry.resolve_ncaaf_team_id`), never `teams_match` -- its prefix heuristic
joins "Michigan" to "Michigan State". A pair that matches only swapped refuses
(`home_away_disagree`); two matches refuse (`game_ambiguous`).

FINALITY. `status.type.completed` is the authority. A game line on a segment settles once
that segment's periods are behind the live period (`h2` and anything with overtime only at
the final); a prop only at the final. `state == "post"` without `completed` is a postponed or
cancelled game and never grades.

THE SEGMENT CONVENTIONS are the platform's, imported: football periods and `h2`-includes-
overtime from `segment_actuals`, WNBA's from `bet_status_wnba._segment_points`. A THREE-WAY
full-game moneyline settles on REGULATION (periods 1-4) -- that is the market's definition;
a tie after four quarters is the draw even when overtime decides the game. A two-way `h2h`
tie in a segment is a push (`game_line_view(draw_possible=False)`), and every win / loss /
push decision is `bet_status.resolve_bet_status`, the one grader.

PROPS AND ABSENCE -- ABSENT IS NOT ZERO
    nfl     ESPN summary box (`nfl.live_player_box.player_stat_rows_from_summary`). A player in
            ANY stat group played, so his zeros are real. Absent from the final box ->
            (None, 'dnp_void'): inactive players are voided by books, and the box cannot tell
            an inactive player from an active one with no stat line, so it never grades one.
    ncaaf   the weekly CFBD snapshot on web's disk FIRST (`fetch_export`), keyed by ESPN's
            event id (CFBD game ids are ESPN's). It holds only passing / rushing / receiving
            lines, so a player absent from a game it carries -> (None,
            'player_absent_unverifiable'). A game the snapshot lacks falls back to the ESPN
            summary, read exactly as NFL's.
    wnba    ESPN summary box; `didNotPlay` or absent -> (None, 'dnp_void').
    Anytime TD is `td > 0.5`; from ESPN it counts rushing, receiving, kick / punt return,
    interception-return and defensive touchdowns (a binary, so an overlap cannot matter). The
    CFBD snapshot's `anytime_td` is rushing + receiving only, so a return touchdown is missed
    there -- a known limit, stated rather than hidden.

FETCHING. `fetch_json(url)` defaults to urllib with its DEFAULT User-Agent (ESPN refused a
custom one from Render), `site.api.espn.com` first and `site.web.api.espn.com` second (the
WNBA box builder measured the first host refusing Render). Sequential; every payload is
memoised per instance, and with `cache_dir` an IMMUTABLE one -- a scoreboard whose every
event is completed, a completed game's summary -- is kept on disk. A pregame or live payload
never is.
"""

from __future__ import annotations

import collections
import csv
import hashlib
import io
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from syndicate.features.shared.bet_status import (
    STATUS_LIVE_TIED,
    STATUS_LOST,
    STATUS_WON,
    resolve_bet_status,
)

__all__ = [
    "GRADER_VERSION",
    "EspnPopulationSettler",
    "NCAAF_PLAYER_STATS_SNAPSHOT",
    "HANDLED_SPORTS",
]

GRADER_VERSION = "espn/1"
# NBA added 2026-09-20 (lane `daily-accuracy-suite`). It is a REGISTRATION, not a new
# settler: the WNBA path already grades ESPN basketball -- same summary box, same
# `_BASKETBALL_SINGLE`/`_BASKETBALL_DOUBLES` stat tables, same four quarters -- and
# `team_aliases` already carries an NBA map (`team_aliases.py:709`).
#
# NCAAB IS DELIBERATELY NOT HERE, and the reason is one thing only: there is no NCAAB
# team registry. `_resolve_team` sends every non-NCAAF sport to `canonical_team`, whose
# alias map has no `ncaab` entry, so every NCAAB game would resolve to None and the
# settler would return `team_unresolved` for 100% of rows -- a sport that LOOKS covered
# and grades nothing, which is worse than an honest absence. NCAAF needed a 684-team,
# 2,342-key registry that REFUSES its 128 ambiguous names ("tigers" names 25 schools);
# NCAAB needs the same and it does not exist yet. Everything else below is ready for it
# (`_SPORT_PATHS`, the halves in `_REGULATION_PERIODS`/`_segment_closed`), so adding the
# registry and this one string is the whole remaining job. NCAAB opens in November.
HANDLED_SPORTS = frozenset({"nfl", "ncaaf", "wnba", "nba"})

# Every basketball sport reads the same ESPN summary box and the same stat tables.
BASKETBALL_SPORTS = frozenset({"wnba", "nba", "ncaab"})

NCAAF_PLAYER_STATS_SNAPSHOT = (
    "ncaaf_source/source_artifacts/data/processed/player_game_stats/ncaaf_player_game_stats_snapshot.csv"
)

ESPN_HOSTS = ("site.api.espn.com", "site.web.api.espn.com")
_SPORT_PATHS = {
    "nfl": "football/nfl",
    "ncaaf": "football/college-football",
    "wnba": "basketball/wnba",
    "nba": "basketball/nba",
    # Present but unreachable until `ncaab` joins HANDLED_SPORTS -- see the note there.
    "ncaab": "basketball/mens-college-basketball",
}
# FBS, and a page size that holds a full Saturday (`poll_ncaaf_live_state` measured it).
_SCOREBOARD_EXTRA = {"ncaaf": "&groups=80&limit=200"}
_FETCH_TIMEOUT_SECONDS = 20.0

FULL = "full"
_SEGMENTS = frozenset({"q1", "q2", "q3", "q4", "h1", "h2"})
_TOTAL_MARKETS = frozenset({"totals", "totals_alt"})
_LINE_MARKETS = frozenset({"h2h", "h2h_3_way", "spreads", "spreads_alt"})
# Full-game markets `grade_population` cannot settle from a final score; the rest of the
# full game is its job and passes through.
_FULL_GAME_MARKETS_HANDLED = frozenset({"h2h_3_way", "spreads_alt", "totals_alt"})
_REGULATION_PERIODS = 4
# NCAAB plays two 20-minute HALVES, not quarters, so regulation is 2 periods there and a
# `h2h_3_way` graded on `values[:4]` would silently fold overtime into regulation.
_REGULATION_PERIODS_BY_SPORT = {"ncaab": 2}


def regulation_periods(sport: str) -> int:
    return _REGULATION_PERIODS_BY_SPORT.get(str(sport or "").strip().lower(), _REGULATION_PERIODS)

# ---- reasons (ungraded), each a different job ----------------------------------------
R_NO_COMMENCE = "no_commence_time"
R_NOT_STARTED = "not_started"
R_NO_TEAMS = "no_team_names"
R_TEAM_UNRESOLVED = "team_unresolved"
R_SCOREBOARD_UNAVAILABLE = "scoreboard_unavailable"
R_GAME_NOT_FOUND = "game_not_found"
R_GAME_AMBIGUOUS = "game_ambiguous"
R_HOME_AWAY = "home_away_disagree"
R_GAME_NOT_FINAL = "game_not_final"
R_GAME_NOT_COMPLETED = "game_postponed_or_cancelled"
R_SEGMENT_NOT_FINAL = "segment_not_final"
R_SEGMENT_ACTUAL = "segment_actual_unavailable"
R_REGULATION_ACTUAL = "regulation_actual_unavailable"
R_PROP_MARKET = "prop_market_unmapped"
R_PROP_SEGMENT = "prop_segment_unsupported"
# "No Scorer" and "<Team> D/ST" are priced as players in the anytime-TD market and are not
# players: absent from every box, they would otherwise read as a DNP void.
R_NON_PLAYER = "non_player_prop_unsupported"
R_SUMMARY_UNAVAILABLE = "summary_unavailable"
R_BOX_UNAVAILABLE = "box_unavailable"
R_DNP_VOID = "dnp_void"
R_ABSENT_UNVERIFIABLE = "player_absent_unverifiable"
R_PLAYER_AMBIGUOUS = "player_ambiguous"
R_STAT_UNAVAILABLE = "stat_unavailable"
R_UNSETTLEABLE = "unsettleable_side_or_line"

_RESULTS = {STATUS_WON: "win", STATUS_LOST: "loss", STATUS_LIVE_TIED: "push"}


def _norm(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _as_float(value: Any) -> float | None:
    try:
        parsed = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return None if parsed != parsed else parsed


def _utcnow() -> datetime:
    """A seam for tests; the settler reads the clock only to skip unplayed kickoffs."""
    return datetime.now(timezone.utc)


def _parse_utc(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _default_fetch_json(url: str) -> Any:
    """GET -> parsed JSON, or None. NO custom headers: urllib's default User-Agent is load-bearing."""
    import urllib.request

    try:
        with urllib.request.urlopen(urllib.request.Request(url), timeout=_FETCH_TIMEOUT_SECONDS) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception:
        return None


def _player_key(value: Any) -> str:
    # The NFL settlement join key: accents, initials ("A.J." == "AJ") and suffixes ("III").
    from syndicate.features.shared.bet_status_nfl import _player_key as key

    return key(value)


# ---------------------------------------------------------------------------
# prop vocabularies
# ---------------------------------------------------------------------------

# Football props: the NFL settlement table (both the board's labels and OddsAPI keys).
def _football_field(market: str) -> str | None:
    from syndicate.features.shared.bet_status_nfl import _PROP_FIELDS

    return _PROP_FIELDS.get(market)


# The CFBD snapshot's spelling of each football field.
_SNAPSHOT_COLUMNS = {
    "pass_yards": "passing_yards",
    "pass_attempts": "passing_attempts",
    "completions": "passing_completions",
    "pass_td": "passing_tds",
    "pass_int": "interceptions",
    "rush_yards": "rushing_yards",
    "rush_attempts": "rushing_attempts",
    "receptions": "receptions",
    "rec_yards": "receiving_yards",
    "td_scored": "anytime_td",
}
_ANYTIME_TD_FIELD = "td_scored"
# ESPN touchdown keys outside passing / rushing / receiving that score for the player.
_EXTRA_TD_KEYS = frozenset({
    "kickReturnTouchdowns", "puntReturnTouchdowns", "interceptionTouchdowns", "defensiveTouchdowns",
})

_WNBA_SINGLE = {
    "player_points": ("pts",),
    "player_rebounds": ("reb",),
    "player_assists": ("ast",),
    "player_threes": ("threes",),
    "player_steals": ("stl",),
    "player_blocks": ("blk",),
    "player_turnovers": ("tov",),
    "player_points_rebounds": ("pts", "reb"),
    "player_points_assists": ("pts", "ast"),
    "player_rebounds_assists": ("reb", "ast"),
    "player_points_rebounds_assists": ("pts", "reb", "ast"),
    "player_blocks_steals": ("blk", "stl"),
}
# yes/no: how many of these categories reached ten.
_WNBA_DOUBLES = {"player_double_double": 2, "player_triple_double": 3}
_WNBA_DOUBLE_STATS = ("pts", "reb", "ast", "stl", "blk")
_WNBA_KEYS = {
    "points": "pts", "rebounds": "reb", "assists": "ast", "steals": "stl",
    "blocks": "blk", "turnovers": "tov", "minutes": "min",
}
_WNBA_THREES_KEY = "threePointFieldGoalsMade-threePointFieldGoalsAttempted"


def _basketball_market(sport: str, market: str) -> str:
    """Canonical market key for a basketball sport.

    Keyed on the SPORT rather than pinned to "wnba": `market_keys` maps nba, wnba and
    ncaab all onto the same `_BASKETBALL` table (`market_keys.py:643`), so this is the
    same answer for all three -- but asking under the caller's own sport means a future
    per-league divergence is honoured instead of silently answered as WNBA.
    """
    from syndicate.features.shared.market_keys import canonical_market_key

    return str(canonical_market_key(sport, market) or canonical_market_key("wnba", market) or market)


def _wnba_market(market: str) -> str:
    return _basketball_market("wnba", market)


_NO_SCORER_NAMES = frozenset({"no scorer", "no touchdown scorer", "no td scorer"})
_TEAM_UNIT_SUFFIXES = ("d/st", "dst", "defense", "defence", "special teams")


def _non_player(sport: str, name: Any) -> bool:
    """A 'player' that is a whole team's defense or the no-scorer outcome (measured on DEN @ KC)."""
    text = _norm(name)
    if text in _NO_SCORER_NAMES:
        return True
    for suffix in _TEAM_UNIT_SUFFIXES:
        if text.endswith(" " + suffix):
            team = text[: -len(suffix) - 1].strip()
            if sport == "ncaaf":
                from syndicate.features.shared.ncaaf_team_registry import resolve_ncaaf_team_id

                return resolve_ncaaf_team_id(team) is not None
            from syndicate.features.shared.team_aliases import canonical_team

            return canonical_team(sport, team) is not None
    return False


def _prop_supported(sport: str, market: str) -> bool:
    if sport in ("nfl", "ncaaf"):
        return _football_field(market) is not None
    if sport in BASKETBALL_SPORTS:
        canonical = _basketball_market(sport, market)
        return canonical in _WNBA_SINGLE or canonical in _WNBA_DOUBLES
    return False


# ---------------------------------------------------------------------------
# ESPN payload readers
# ---------------------------------------------------------------------------


def _team_names(team: Mapping[str, Any]) -> list[Any]:
    return [team.get(field) for field in ("displayName", "shortDisplayName", "location", "abbreviation")]


def _competitor(row: Any) -> dict[str, Any] | None:
    from syndicate.features.shared.segment_actuals import linescores_from_competitor

    if not isinstance(row, Mapping):
        return None
    team = row.get("team") if isinstance(row.get("team"), Mapping) else {}
    return {
        "names": _team_names(team),
        "display": str(team.get("displayName") or team.get("abbreviation") or "").strip(),
        "espn_team_id": str(team.get("id") or "").strip(),
        "score": _as_float(row.get("score")),
        "linescores": linescores_from_competitor(row),
    }


def parse_scoreboard_events(payload: Any) -> list[dict[str, Any]] | None:
    """ESPN scoreboard -> one dict per event, or None when the payload is not a scoreboard."""
    if not isinstance(payload, Mapping) or not isinstance(payload.get("events"), list):
        return None
    events: list[dict[str, Any]] = []
    for event in payload["events"]:
        if not isinstance(event, Mapping):
            continue
        competitions = event.get("competitions") if isinstance(event.get("competitions"), list) else []
        competition = competitions[0] if competitions and isinstance(competitions[0], Mapping) else {}
        sides: dict[str, dict[str, Any]] = {}
        for row in competition.get("competitors") or []:
            parsed = _competitor(row)
            side = _norm(row.get("homeAway")) if isinstance(row, Mapping) else ""
            if parsed is not None and side in ("home", "away"):
                sides[side] = parsed
        if "home" not in sides or "away" not in sides:
            continue
        status = event.get("status") if isinstance(event.get("status"), Mapping) else {}
        status_type = status.get("type") if isinstance(status.get("type"), Mapping) else {}
        try:
            period = int(status.get("period")) if status.get("period") is not None else None
        except (TypeError, ValueError):
            period = None
        events.append({
            "event_id": str(event.get("id") or "").strip(),
            "start": str(event.get("date") or ""),
            "state": _norm(status_type.get("state")),
            "completed": bool(status_type.get("completed")),
            "status_name": str(status_type.get("name") or ""),
            "detail": str(status_type.get("shortDetail") or status_type.get("detail") or ""),
            "period": period,
            "home": sides["home"],
            "away": sides["away"],
        })
    return events


def _summary_completed(summary: Any) -> bool:
    if not isinstance(summary, Mapping):
        return False
    header = summary.get("header") if isinstance(summary.get("header"), Mapping) else {}
    competitions = header.get("competitions") or []
    competition = competitions[0] if competitions and isinstance(competitions[0], Mapping) else {}
    status = competition.get("status") if isinstance(competition.get("status"), Mapping) else {}
    status_type = status.get("type") if isinstance(status.get("type"), Mapping) else {}
    return bool(status_type.get("completed"))


def football_box_rows(summary: Any) -> list[dict[str, Any]] | None:
    """Every athlete in a football summary box, with the settlement fields, or None.

    `live_player_box.player_stat_rows_from_summary` is the reader; it credits rushing and
    receiving touchdowns only, so return / defensive touchdowns are added here for anytime TD.
    """
    from syndicate.features.nfl.live_player_box import player_stat_rows_from_summary

    rows = player_stat_rows_from_summary(summary)
    if rows is None:
        return None
    extra: collections.Counter[tuple[str, str]] = collections.Counter()
    for team_block in (summary.get("boxscore") or {}).get("players") or []:
        if not isinstance(team_block, Mapping):
            continue
        team = team_block.get("team") if isinstance(team_block.get("team"), Mapping) else {}
        abbr = str(team.get("abbreviation") or team.get("shortDisplayName") or "").strip().upper()
        for group in team_block.get("statistics") or []:
            if not isinstance(group, Mapping):
                continue
            keys = [str(key or "").strip() for key in (group.get("keys") or [])]
            positions = [at for at, key in enumerate(keys) if key in _EXTRA_TD_KEYS]
            if not positions:
                continue
            for entry in group.get("athletes") or []:
                if not isinstance(entry, Mapping):
                    continue
                athlete = entry.get("athlete") if isinstance(entry.get("athlete"), Mapping) else {}
                name = str(athlete.get("displayName") or athlete.get("shortName") or "").strip()
                stats = entry.get("stats") if isinstance(entry.get("stats"), list) else []
                for at in positions:
                    value = _as_float(stats[at]) if at < len(stats) else None
                    if name and value:
                        extra[(abbr, name)] += value
    out = []
    for row in rows:
        merged = dict(row)
        merged["td_any"] = float(row.get("td_scored") or 0.0) + extra.get((row.get("team_abbr"), row.get("player_name")), 0.0)
        out.append(merged)
    return out


def wnba_box_rows(summary: Any) -> list[dict[str, Any]] | None:
    """Every athlete ESPN lists in a WNBA box, DNPs included and flagged, or None."""
    if not isinstance(summary, Mapping):
        return None
    boxscore = summary.get("boxscore")
    if not isinstance(boxscore, Mapping) or not isinstance(boxscore.get("players"), list):
        return None
    out: list[dict[str, Any]] = []
    for team_block in boxscore["players"]:
        if not isinstance(team_block, Mapping):
            continue
        team = team_block.get("team") if isinstance(team_block.get("team"), Mapping) else {}
        abbr = str(team.get("abbreviation") or "").strip().upper()
        for group in team_block.get("statistics") or []:
            if not isinstance(group, Mapping):
                continue
            keys = [str(key or "").strip() for key in (group.get("keys") or [])]
            for entry in group.get("athletes") or []:
                if not isinstance(entry, Mapping):
                    continue
                athlete = entry.get("athlete") if isinstance(entry.get("athlete"), Mapping) else {}
                name = str(athlete.get("displayName") or "").strip()
                if not name:
                    continue
                stats = entry.get("stats") if isinstance(entry.get("stats"), list) else []
                row: dict[str, Any] = {
                    "player_name": name,
                    "team_abbr": abbr,
                    # No stat line is a DNP whatever the flag says; the flag alone is enough too.
                    "dnp": bool(entry.get("didNotPlay")) or not stats,
                }
                for at, key in enumerate(keys):
                    if at >= len(stats):
                        break
                    if key in _WNBA_KEYS:
                        row[_WNBA_KEYS[key]] = _as_float(stats[at])
                    elif key == _WNBA_THREES_KEY:
                        made, _, _attempted = str(stats[at]).partition("-")
                        row["threes"] = _as_float(made)
                out.append(row)
    return out


# ---------------------------------------------------------------------------
# the settler
# ---------------------------------------------------------------------------


class EspnPopulationSettler:
    """`grade_population`'s `extra_settler` for nfl / ncaaf / wnba props and segment lines.

    `fetch_json(url) -> payload | None`; `fetch_export(relative_path) -> text | None` reads
    web's disk (NCAAF's CFBD snapshot; without it NCAAF props read ESPN); `cache_dir` keeps
    immutable ESPN payloads between runs. `counters` records what each settle cost and read.
    """

    def __init__(
        self,
        *,
        fetch_json: Callable[[str], Any] | None = None,
        fetch_export: Callable[[str], Any] | None = None,
        cache_dir: Path | str | None = None,
    ) -> None:
        self._fetch_json = fetch_json or _default_fetch_json
        self._fetch_export = fetch_export
        self._cache_dir = Path(cache_dir) if cache_dir else None
        self._memo: dict[str, Any] = {}
        # A slate is thousands of rows over a few dozen games: resolve names and games once.
        self._team_memo: dict[tuple[str, tuple[str, ...]], str | None] = {}
        self._locate_memo: dict[tuple[Any, ...], tuple[dict[str, Any] | None, str]] = {}
        self._snapshot: dict[str, list[dict[str, str]]] | None = None
        self._snapshot_read = False
        self.counters: collections.Counter[str] = collections.Counter()

    # -- the hook ---------------------------------------------------------------------

    def __call__(self, shaped: Mapping[str, Any], view: Mapping[str, Any] | None = None) -> tuple[str | None, str | None] | None:
        if not self.handles(shaped):
            return None
        return self.settle(shaped)

    def handles(self, shaped: Mapping[str, Any]) -> bool:
        if not isinstance(shaped, Mapping):
            return False
        sport = _norm(shaped.get("sport"))
        if sport not in HANDLED_SPORTS:
            return False
        if shaped.get("player_name"):
            return True
        market = _norm(shaped.get("market"))
        segment = _norm(shaped.get("segment")) or FULL
        if segment in ("full", "full_game"):
            return market in _FULL_GAME_MARKETS_HANDLED
        return segment in _SEGMENTS and (market in _TOTAL_MARKETS or market in _LINE_MARKETS)

    def settle(self, shaped: Mapping[str, Any]) -> tuple[str | None, str | None]:
        sport = _norm(shaped.get("sport"))
        market = _norm(shaped.get("market"))
        segment = _norm(shaped.get("segment")) or FULL
        if segment == "full_game":
            segment = FULL
        is_prop = bool(shaped.get("player_name"))

        # PERMANENT BEFORE TRANSIENT: nothing is fetched for a row that can never grade.
        if is_prop:
            if segment != FULL:
                return None, R_PROP_SEGMENT
            if not _prop_supported(sport, market):
                return None, R_PROP_MARKET
            if _non_player(sport, shaped.get("player_name")):
                return None, R_NON_PLAYER

        kickoff = _parse_utc(shaped.get("commence_time"))
        if kickoff is None:
            return None, R_NO_COMMENCE
        if kickoff > _utcnow():
            return None, R_NOT_STARTED

        event, why = self._locate(sport, shaped)
        if event is None:
            return None, why

        if event["state"] == "pre":
            return None, R_NOT_STARTED
        if event["state"] == "post" and not event["completed"]:
            return None, R_GAME_NOT_COMPLETED

        if is_prop:
            if not event["completed"]:
                return None, R_GAME_NOT_FINAL
            return self._settle_prop(sport, market, shaped, event)
        return self._settle_line(sport, market, segment, shaped, event)

    # -- the game ------------------------------------------------------------------------

    def _team_key(self, sport: str, names: list[Any]) -> str | None:
        """One resolved team for these name forms, or None (unresolved or contradictory)."""
        memo_key = (sport, tuple(str(name or "") for name in names))
        if memo_key not in self._team_memo:
            self._team_memo[memo_key] = self._resolve_team(sport, names)
        return self._team_memo[memo_key]

    @staticmethod
    def _resolve_team(sport: str, names: list[Any]) -> str | None:
        if sport == "ncaaf":
            from syndicate.features.shared.ncaaf_team_registry import resolve_ncaaf_team_id as resolve
        else:
            from syndicate.features.shared.team_aliases import canonical_team

            def resolve(name: Any) -> str | None:
                return canonical_team(sport, name)

        found = {resolved for resolved in (resolve(name) for name in names if name) if resolved}
        return next(iter(found)) if len(found) == 1 else None

    def _scoreboard(self, sport: str, capture_date: str) -> list[dict[str, Any]] | None:
        query = f"?dates={capture_date.replace('-', '')}{_SCOREBOARD_EXTRA.get(sport, '')}"
        payload = self._espn(f"/apis/site/v2/sports/{_SPORT_PATHS[sport]}/scoreboard{query}",
                             immutable=lambda body: bool(parse_scoreboard_events(body)) and all(
                                 event["completed"] for event in parse_scoreboard_events(body)))
        return parse_scoreboard_events(payload)

    def _locate(self, sport: str, shaped: Mapping[str, Any]) -> tuple[dict[str, Any] | None, str]:
        from syndicate.features.shared.bet_status_nfl import kickoff_capture_dates

        memo_key = (sport, shaped.get("home_team"), shaped.get("away_team"),
                    tuple(kickoff_capture_dates(shaped.get("commence_time"))))
        if memo_key not in self._locate_memo:
            self._locate_memo[memo_key] = self._locate_uncached(sport, shaped)
        return self._locate_memo[memo_key]

    def _locate_uncached(self, sport: str, shaped: Mapping[str, Any]) -> tuple[dict[str, Any] | None, str]:
        from syndicate.features.shared.bet_status_nfl import kickoff_capture_dates

        home_name, away_name = shaped.get("home_team"), shaped.get("away_team")
        if not home_name or not away_name:
            return None, R_NO_TEAMS
        home_key = self._team_key(sport, [home_name])
        away_key = self._team_key(sport, [away_name])
        if not home_key or not away_key or home_key == away_key:
            self.counters[f"team_unresolved:{sport}"] += 1
            return None, R_TEAM_UNRESOLVED

        read_any = False
        exact: dict[str, dict[str, Any]] = {}
        swapped = False
        for capture_date in kickoff_capture_dates(shaped.get("commence_time")):
            events = self._scoreboard(sport, capture_date)
            if events is None:
                continue
            read_any = True
            for event in events:
                espn_home = self._team_key(sport, event["home"]["names"])
                espn_away = self._team_key(sport, event["away"]["names"])
                if espn_home == home_key and espn_away == away_key:
                    exact[event["event_id"]] = event
                elif espn_home == away_key and espn_away == home_key:
                    swapped = True
        if len(exact) == 1:
            return next(iter(exact.values())), ""
        if len(exact) > 1:
            return None, R_GAME_AMBIGUOUS
        if not read_any:
            return None, R_SCOREBOARD_UNAVAILABLE
        return None, R_HOME_AWAY if swapped else R_GAME_NOT_FOUND

    # -- game lines ------------------------------------------------------------------------

    def _segment_pair(self, sport: str, segment: str, event: Mapping[str, Any]) -> tuple[float, float] | None:
        home = event["home"]["linescores"]
        away = event["away"]["linescores"]
        if home is None or away is None:
            return None
        if sport in BASKETBALL_SPORTS:
            from syndicate.features.shared.bet_status_wnba import _segment_points

            return _segment_points({"home": home, "away": away}, segment)
        from syndicate.features.shared.segment_actuals import segment_score_pair

        pair = segment_score_pair(sport, segment, home_linescores=home, away_linescores=away)
        return (float(pair[0]), float(pair[1])) if pair else None

    @staticmethod
    def _segment_closed(segment: str, event: Mapping[str, Any], sport: str = "") -> bool:
        """A live game closes a fixed segment once the period after its last one is under way.

        `h1` ends at a different PERIOD NUMBER depending on the sport: period 2 of 4 in
        quarter sports, period 1 of 2 in NCAAB's halves. Reading NCAAB's h1 as "closed
        once period > 2" would never close it in regulation.
        """
        if event["completed"]:
            return True
        if segment == "h2":
            return False
        halves = regulation_periods(sport) == 2
        last = ({"h1": 1} if halves else {"q1": 1, "q2": 2, "q3": 3, "q4": 4, "h1": 2}).get(segment)
        period = event.get("period")
        return last is not None and period is not None and period > last

    def _settle_line(self, sport: str, market: str, segment: str, shaped: Mapping[str, Any],
                     event: Mapping[str, Any]) -> tuple[str | None, str | None]:
        if segment == FULL:
            if not event["completed"]:
                return None, R_GAME_NOT_FINAL
            if market == "h2h_3_way":
                home, away = event["home"]["linescores"], event["away"]["linescores"]
                periods = regulation_periods(sport)
                regulation = [values[:periods] for values in (home, away) if values is not None]
                if len(regulation) != 2 or any(len(values) < periods or None in values for values in regulation):
                    return None, R_REGULATION_ACTUAL
                pair = (float(sum(regulation[0])), float(sum(regulation[1])))
            else:
                if event["home"]["score"] is None or event["away"]["score"] is None:
                    return None, R_SEGMENT_ACTUAL
                pair = (event["home"]["score"], event["away"]["score"])
            source = "espn_final"
        else:
            if not self._segment_closed(segment, event, sport):
                return None, R_SEGMENT_NOT_FINAL
            pair = self._segment_pair(sport, segment, event)
            if pair is None:
                return None, R_SEGMENT_ACTUAL
            source = "espn_linescore"
        home_score, away_score = pair

        if market in _TOTAL_MARKETS:
            return self._grade(market, shaped.get("side"), shaped.get("line"), home_score + away_score, source)

        from syndicate.features.shared.game_line_bet import game_line_view

        view = game_line_view(
            sport=sport,
            market=market,
            side=shaped.get("side"),
            line=shaped.get("line"),
            home_team=event["home"]["display"],
            away_team=event["away"]["display"],
            home_score=home_score,
            away_score=away_score,
            # Two-way: a level segment is a push; `h2h_3_way` stays three-way by name.
            draw_possible=False,
        )
        if view.get("unavailable_reason"):
            return None, str(view["unavailable_reason"])
        return self._grade(market, view["side"], view["line"], view["current_value"], source)

    # -- props -----------------------------------------------------------------------------

    def _settle_prop(self, sport: str, market: str, shaped: Mapping[str, Any],
                     event: Mapping[str, Any]) -> tuple[str | None, str | None]:
        key = _player_key(shaped.get("player_name"))
        if sport in BASKETBALL_SPORTS:
            return self._settle_basketball_prop(sport, market, key, shaped, event)

        field = _football_field(market)
        line = shaped.get("line")
        if field == _ANYTIME_TD_FIELD and _as_float(line) is None:
            line = 0.5

        if sport == "ncaaf":
            rows = self._snapshot_rows(event["event_id"])
            if rows is not None:
                self.counters["ncaaf_prop_source:cfbd_snapshot"] += 1
                matches = [row for row in rows if _player_key(row.get("player_name")) == key]
                if len(matches) > 1:
                    return None, R_PLAYER_AMBIGUOUS
                if not matches:
                    return None, R_ABSENT_UNVERIFIABLE
                value = _as_float(matches[0].get(_SNAPSHOT_COLUMNS[field]))
                if value is None:
                    return None, R_STAT_UNAVAILABLE
                return self._grade(market, shaped.get("side"), line, value, "cfbd_snapshot")
            self.counters["ncaaf_prop_source:espn_summary"] += 1

        summary = self._summary(sport, event["event_id"])
        if summary is None:
            return None, R_SUMMARY_UNAVAILABLE
        rows = football_box_rows(summary)
        if rows is None:
            return None, R_BOX_UNAVAILABLE
        matches = [row for row in rows if _player_key(row.get("player_name")) == key]
        if len(matches) > 1:
            return None, R_PLAYER_AMBIGUOUS
        if not matches:
            return None, R_DNP_VOID
        value = _as_float(matches[0].get("td_any" if field == _ANYTIME_TD_FIELD else field))
        if value is None:
            return None, R_STAT_UNAVAILABLE
        return self._grade(market, shaped.get("side"), line, value, "espn_box")

    def _settle_basketball_prop(self, sport: str, market: str, key: str, shaped: Mapping[str, Any],
                                event: Mapping[str, Any]) -> tuple[str | None, str | None]:
        """WNBA, NBA and (once it has a team registry) NCAAB. ESPN serves one box shape
        for all three, so the only thing that was ever WNBA-specific here was the
        hard-coded sport in the summary fetch -- which would have fetched the wrong
        league's box for an NBA event id."""
        summary = self._summary(sport, event["event_id"])
        if summary is None:
            return None, R_SUMMARY_UNAVAILABLE
        rows = wnba_box_rows(summary)
        if rows is None:
            return None, R_BOX_UNAVAILABLE
        matches = [row for row in rows if _player_key(row.get("player_name")) == key]
        if len(matches) > 1:
            return None, R_PLAYER_AMBIGUOUS
        if not matches or matches[0]["dnp"]:
            return None, R_DNP_VOID
        row = matches[0]
        canonical = _basketball_market(sport, market)
        line = shaped.get("line")
        if canonical in _WNBA_DOUBLES:
            stats = [row.get(stat) for stat in _WNBA_DOUBLE_STATS]
            if any(stat is None for stat in stats):
                return None, R_STAT_UNAVAILABLE
            value = 1.0 if sum(1 for stat in stats if stat >= 10) >= _WNBA_DOUBLES[canonical] else 0.0
            if _as_float(line) is None:
                line = 0.5
        else:
            parts = [row.get(stat) for stat in _WNBA_SINGLE[canonical]]
            if any(part is None for part in parts):
                # A partial sum is a smaller number that looks real.
                return None, R_STAT_UNAVAILABLE
            value = float(sum(parts))
        return self._grade(canonical, shaped.get("side"), line, value, "espn_box")

    # -- grading ------------------------------------------------------------------------------

    def _grade(self, market: str, side: Any, line: Any, value: Any, source: str) -> tuple[str | None, str | None]:
        status = resolve_bet_status(market=market, side=side, line=line, current_value=value, is_final=True)
        result = _RESULTS.get(status.get("status"))
        if result is None:
            return None, str(status.get("unavailable_reason") or R_UNSETTLEABLE)
        self.counters[f"graded_from:{source}"] += 1
        return result, source

    # -- reads ----------------------------------------------------------------------------------

    def _summary(self, sport: str, event_id: str) -> Any:
        if not event_id:
            return None
        return self._espn(f"/apis/site/v2/sports/{_SPORT_PATHS[sport]}/summary?event={event_id}",
                          immutable=_summary_completed)

    def _espn(self, path_and_query: str, *, immutable: Callable[[Any], bool]) -> Any:
        """One ESPN payload: memo, then disk (immutable only), then each host in turn."""
        if path_and_query in self._memo:
            return self._memo[path_and_query]
        cached = self._cache_path(path_and_query)
        if cached is not None and cached.is_file():
            try:
                payload = json.loads(cached.read_text(encoding="utf-8"))
                self.counters["espn_disk_cache_hits"] += 1
                self._memo[path_and_query] = payload
                return payload
            except (OSError, ValueError):
                pass
        payload = None
        for host in ESPN_HOSTS:
            self.counters["espn_requests"] += 1
            payload = self._fetch_json(f"https://{host}{path_and_query}")
            if payload is not None:
                break
        if payload is None:
            self.counters["espn_failures"] += 1
        self._memo[path_and_query] = payload
        if payload is not None and cached is not None and immutable(payload):
            try:
                cached.parent.mkdir(parents=True, exist_ok=True)
                cached.write_text(json.dumps(payload), encoding="utf-8")
            except OSError:
                pass
        return payload

    def _cache_path(self, path_and_query: str) -> Path | None:
        if self._cache_dir is None:
            return None
        return self._cache_dir / "espn" / (hashlib.sha1(path_and_query.encode("utf-8")).hexdigest() + ".json")

    def _snapshot_rows(self, event_id: str) -> list[dict[str, str]] | None:
        """This game's rows from web's CFBD snapshot; None when unread or the game is absent."""
        if not self._snapshot_read:
            self._snapshot_read = True
            text = None
            if self._fetch_export is not None:
                try:
                    text = self._fetch_export(NCAAF_PLAYER_STATS_SNAPSHOT)
                except Exception:
                    text = None
            if isinstance(text, bytes):
                text = text.decode("utf-8", errors="replace")
            if text:
                by_game: dict[str, list[dict[str, str]]] = collections.defaultdict(list)
                for row in csv.DictReader(io.StringIO(str(text))):
                    game_id = str(row.get("game_id") or "").strip()
                    if game_id:
                        by_game[game_id].append(row)
                self._snapshot = dict(by_game)
                self.counters["ncaaf_snapshot_games"] = len(by_game)
        if not self._snapshot:
            return None
        return self._snapshot.get(str(event_id))
