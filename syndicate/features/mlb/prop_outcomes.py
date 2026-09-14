"""MLB player-prop outcomes from MLB's public box scores, for grading a recorded population.

OFFLINE ONLY. `scripts/bucket_search.py` settles Layer 2 population records (and published
openings) with this. Nothing on the serving path imports it, and it never calls production:
the schedule and the box scores come from statsapi.mlb.com.

ONE DEFINITION OF THE STAT. The box-score readers are `syndicate.features.mlb.cards`' own:
- `_actual_batting_context_by_name` / `_actual_pitching_context_by_name`, keyed by
  `_normalize_live_name`;
- `_actual_hitter_stat_value` / `_actual_pitcher_stat_value`;
- `_market_name_variants`.
The MLB page settles its props with those. This module adds only what the page does not need:
the Layer 2 market key -> stat map, finding the game from the odds feed's identity (team names
and commence time), and a push.

A player absent from the box score (did not bat, did not pitch) settles NOTHING. Books void
those bets; counting them as a loss would manufacture winning unders.
"""

from __future__ import annotations

import json
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from syndicate.features.mlb import cards

STATSAPI = "https://statsapi.mlb.com/api/v1"
NOT_PLAYED_STATES = frozenset({"postponed", "cancelled", "canceled", "suspended"})
# A schedule match further than this from the quoted start is another game: the same two teams
# play on consecutive days all series long.
MAX_START_GAP_SECONDS = 12 * 3600

#: Layer 2 / OddsAPI market key -> (role, `cards` prop key).
MARKET_STATS: dict[str, tuple[str, str]] = {
    "batter_hits": ("hitter", "hits"),
    "batter_total_bases": ("hitter", "total_bases"),
    "batter_rbis": ("hitter", "rbis"),
    "batter_runs_scored": ("hitter", "runs_scored"),
    "batter_home_runs": ("hitter", "home_runs"),
    "batter_hits_runs_rbis": ("hitter", "hits_runs_rbis"),
    "strikeouts": ("pitcher", "strikeouts"),
    "pitcher_strikeouts": ("pitcher", "strikeouts"),
    "outs": ("pitcher", "outs"),
    "pitcher_outs": ("pitcher", "outs"),
    "hits_allowed": ("pitcher", "hits_allowed"),
    "pitcher_hits_allowed": ("pitcher", "hits_allowed"),
    "earned_runs": ("pitcher", "earned_runs"),
    "pitcher_earned_runs": ("pitcher", "earned_runs"),
    "walks_allowed": ("pitcher", "walks_allowed"),
    "pitcher_walks": ("pitcher", "walks_allowed"),
}

try:
    from zoneinfo import ZoneInfo

    _EASTERN: Any = ZoneInfo("America/New_York")
except Exception:  # pragma: no cover - tzdata missing
    _EASTERN = timezone(timedelta(hours=-4))


def _parse_ts(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _as_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return None if parsed != parsed else parsed


def team_key(name: Any) -> str:
    """The alias registry's MLB key, or the lowercased name when it has none."""
    text = str(name or "").strip().lower()
    if not text:
        return ""
    try:
        from syndicate.features.shared.team_aliases import chip_join_key

        canon = chip_join_key("mlb", text)
    except Exception:
        canon = None
    return str(canon or text).strip().lower()


def settle_prop(side: Any, line: Any, actual: Any) -> str | None:
    """'win' | 'loss' | 'push' for an over/under at `line`, or None when it cannot settle."""
    pick = str(side or "").strip().lower()
    line_value, actual_value = _as_float(line), _as_float(actual)
    if pick not in {"over", "under"} or line_value is None or actual_value is None:
        return None
    if actual_value == line_value:
        return "push"
    return "win" if (actual_value > line_value) == (pick == "over") else "loss"


def player_actual(market: Any, player_name: Any, feed: Mapping[str, Any]) -> tuple[float | None, str | None]:
    """(actual, None) or (None, reason), read with the MLB page's own box-score readers."""
    stat = MARKET_STATS.get(str(market or "").strip().lower())
    if stat is None:
        return None, "prop_market_unmapped"
    role, prop_key = stat
    if role == "hitter":
        contexts = cards._actual_batting_context_by_name(dict(feed))
        reader = cards._actual_hitter_stat_value
    else:
        contexts = cards._actual_pitching_context_by_name(dict(feed))
        reader = cards._actual_pitcher_stat_value
    for variant in cards._market_name_variants(player_name):
        row = contexts.get(variant)
        if row:
            value = reader(row.get("stats"), prop_key)
            return (value, None) if value is not None else (None, "stat_absent")
    return None, "player_not_in_boxscore"


def schedule_games(payload: Any) -> list[dict[str, Any]]:
    games: list[dict[str, Any]] = []
    days = payload.get("dates") if isinstance(payload, Mapping) else None
    for day in days or []:
        for game in (day.get("games") or []) if isinstance(day, Mapping) else []:
            teams = game.get("teams") or {}
            status = game.get("status") or {}
            games.append(
                {
                    "game_pk": game.get("gamePk"),
                    "home": ((teams.get("home") or {}).get("team") or {}).get("name"),
                    "away": ((teams.get("away") or {}).get("team") or {}).get("name"),
                    "game_date": game.get("gameDate"),
                    "state": str(status.get("abstractGameState") or ""),
                    "detailed_state": str(status.get("detailedState") or ""),
                }
            )
    return games


def match_game(
    home_team: Any, away_team: Any, commence_time: Any, games: list[Mapping[str, Any]]
) -> Mapping[str, Any] | None:
    """The scheduled game for these teams, nearest the quoted start (doubleheaders)."""
    home, away = team_key(home_team), team_key(away_team)
    if not home or not away:
        return None
    candidates = [g for g in games if team_key(g.get("home")) == home and team_key(g.get("away")) == away]
    if len(candidates) <= 1:
        return candidates[0] if candidates else None
    start = _parse_ts(commence_time)
    if start is None:
        return None

    def gap(game: Mapping[str, Any]) -> float:
        when = _parse_ts(game.get("game_date"))
        return abs((when - start).total_seconds()) if when else float("inf")

    return min(candidates, key=gap)


def _http_json(url: str) -> Any:
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "syndicate-bucket-search"})
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.loads(response.read())
    except Exception:
        return None


class MlbPropGrader:
    """Settles MLB prop records: one schedule per date and one box score per game.

    `fetch(url)` returns parsed JSON or None; the default reads statsapi.mlb.com.
    With `cache_dir`, a schedule whose games are all Final, and a Final game's box score, are
    kept on disk, so a rerun over the same window fetches nothing twice. Anything not yet Final
    is refetched on every run.
    """

    def __init__(self, *, cache_dir: Path | str | None = None, fetch: Callable[[str], Any] | None = None) -> None:
        self._fetch = fetch or _http_json
        self._cache_dir = Path(cache_dir) if cache_dir else None
        self._memo: dict[str, Any] = {}
        self.fetches = 0

    def _get(self, name: str, url: str, *, keep: Callable[[Any], bool]) -> Any:
        if name in self._memo:
            return self._memo[name]
        path = self._cache_dir / name if self._cache_dir else None
        if path is not None and path.is_file():
            payload = json.loads(path.read_text(encoding="utf-8"))
        else:
            payload = self._fetch(url)
            self.fetches += 1
            if payload is not None and path is not None and keep(payload):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(payload), encoding="utf-8")
        self._memo[name] = payload
        return payload

    def games_on(self, day: str) -> list[dict[str, Any]] | None:
        def all_final(payload: Any) -> bool:
            games = schedule_games(payload)
            return bool(games) and all(game["state"] == "Final" for game in games)

        payload = self._get(f"schedule_{day}.json", f"{STATSAPI}/schedule?sportId=1&date={day}", keep=all_final)
        return None if payload is None else schedule_games(payload)

    def box_score(self, game_pk: Any) -> dict[str, Any] | None:
        """A Final game's box score, wrapped the way `cards` reads a live feed."""
        payload = self._get(f"boxscore_{game_pk}.json", f"{STATSAPI}/game/{game_pk}/boxscore", keep=lambda _p: True)
        return {"liveData": {"boxscore": payload}} if isinstance(payload, Mapping) else None

    def settle(self, record: Mapping[str, Any]) -> tuple[str | None, str | None]:
        """(result, None) or (None, reason) for a record shaped like `layer2_live_scorecard`'s."""
        market = str(record.get("market") or "").strip().lower()
        if market not in MARKET_STATS:
            return None, "prop_market_unmapped"
        if not (record.get("home_team") and record.get("away_team")):
            return None, "no_team_names"
        start = _parse_ts(record.get("commence_time"))
        if start is None:
            return None, "no_commence_time"
        games = self.games_on(start.astimezone(_EASTERN).date().isoformat())
        if games is None:
            return None, "schedule_unavailable"
        game = match_game(record["home_team"], record["away_team"], record.get("commence_time"), games)
        when = _parse_ts(game.get("game_date")) if game else None
        if game is None or when is None or abs((when - start).total_seconds()) > MAX_START_GAP_SECONDS:
            return None, "game_not_found"
        if game["detailed_state"].strip().lower() in NOT_PLAYED_STATES:
            return None, "game_not_played"
        if game["state"] != "Final":
            return None, "game_not_final"
        feed = self.box_score(game["game_pk"])
        if feed is None:
            return None, "boxscore_unavailable"
        actual, reason = player_actual(market, record.get("player_name"), feed)
        if actual is None:
            return None, reason
        result = settle_prop(record.get("side"), record.get("line"), actual)
        return (result, None) if result else (None, "unsettleable_side_or_line")
