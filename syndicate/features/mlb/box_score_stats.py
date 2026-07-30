from __future__ import annotations

from typing import Any

from syndicate.features.mlb.cards import _actual_pitcher_stat_value
from syndicate.features.mlb.cards import _iter_team_players
from syndicate.features.mlb.cards import _normalize_live_name
from syndicate.features.mlb.sources import raw_feed_live_path


def _safe_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# daily_top_props' own "stat" vocabulary ("hits", "runs", "rbi", "home_runs",
# "total_bases") -- distinct from cards.py's _actual_hitter_stat_value, which
# uses a different key convention ("runs_scored", "rbis") and has no entry
# for the combined "hits_runs_rbis" market at all, so this is a small,
# self-contained dispatch against the raw MLB Stats API batting fields
# rather than reconciling two mismatched vocabularies.
_HITTER_STAT_FIELDS = {
    "hits": "hits",
    "runs": "runs",
    "rbi": "rbi",
    "home_runs": "homeRuns",
    "total_bases": "totalBases",
}


def _hitter_stat_value(batting: dict[str, Any] | None, stat: str) -> float | None:
    if not isinstance(batting, dict):
        return None
    stat_key = str(stat or "").strip().lower()
    if stat_key == "hits_runs_rbis":
        hits = _safe_float(batting.get("hits"))
        runs = _safe_float(batting.get("runs"))
        rbi = _safe_float(batting.get("rbi"))
        if hits is None and runs is None and rbi is None:
            return None
        return (hits or 0.0) + (runs or 0.0) + (rbi or 0.0)
    field = _HITTER_STAT_FIELDS.get(stat_key)
    if not field:
        return None
    return _safe_float(batting.get(field))


def _stat_indexes(feed: dict[str, Any] | None) -> tuple[dict[str, dict[str, Any]], dict[int, dict[str, Any]], dict[str, dict[str, Any]], dict[int, dict[str, Any]]]:
    batting_by_name: dict[str, dict[str, Any]] = {}
    batting_by_id: dict[int, dict[str, Any]] = {}
    pitching_by_name: dict[str, dict[str, Any]] = {}
    pitching_by_id: dict[int, dict[str, Any]] = {}
    if not isinstance(feed, dict):
        return batting_by_name, batting_by_id, pitching_by_name, pitching_by_id
    for side in ("away", "home"):
        for player_obj in _iter_team_players(feed, side):
            person = player_obj.get("person") if isinstance(player_obj.get("person"), dict) else {}
            name = _normalize_live_name((person or {}).get("fullName"))
            try:
                person_id = int((person or {}).get("id") or 0)
            except (TypeError, ValueError):
                person_id = 0
            stats = player_obj.get("stats") if isinstance(player_obj.get("stats"), dict) else {}
            batting = stats.get("batting") if isinstance(stats.get("batting"), dict) else None
            pitching = stats.get("pitching") if isinstance(stats.get("pitching"), dict) else None
            if isinstance(batting, dict) and batting:
                if name:
                    batting_by_name[name] = batting
                if person_id > 0:
                    batting_by_id[person_id] = batting
            if isinstance(pitching, dict) and pitching:
                if name:
                    pitching_by_name[name] = pitching
                if person_id > 0:
                    pitching_by_id[person_id] = pitching
    return batting_by_name, batting_by_id, pitching_by_name, pitching_by_id


def final_stat_value(
    feed: dict[str, Any] | None,
    *,
    group: str,
    stat: str,
    player_name: str,
    player_id: int | None = None,
) -> float | None:
    """The final box-score value for one player's stat, from a completed
    game's cached `feed/live` payload (see `raw_feed_live_path`) -- shared by
    `scripts/build_mlb_actuals.py` and anywhere else that needs a settled
    MLB prop's real outcome, keyed the same way daily_top_props rows already
    are (group in {"pitcher", "hitter"}, stat in daily_top_props' own "stat"
    vocabulary: strikeouts/outs/hits_allowed/earned_runs/walks_allowed for
    pitchers, hits/runs/rbi/home_runs/total_bases/hits_runs_rbis for
    hitters). MLBAM id match first, normalized-name fallback (accents,
    suffixes, Jr./Sr. variants silently miss on name matching alone).
    """
    batting_by_name, batting_by_id, pitching_by_name, pitching_by_id = _stat_indexes(feed)
    name = _normalize_live_name(player_name)
    pid = int(player_id or 0)
    group_key = str(group or "").strip().lower()
    if group_key == "pitcher":
        row = (pitching_by_id.get(pid) if pid > 0 else None) or pitching_by_name.get(name)
        return _actual_pitcher_stat_value(row, stat)
    row = (batting_by_id.get(pid) if pid > 0 else None) or batting_by_name.get(name)
    return _hitter_stat_value(row, stat)


def load_final_feed(selected_date: str, game_pk: int, *, fetch_if_missing: bool = True) -> dict[str, Any] | None:
    """The cached raw `feed/live` payload for a game, falling back to a
    fresh MLB Stats API fetch when the local cache has aged out -- the
    cache's retention isn't guaranteed for an arbitrary past date, but MLB
    Stats API keeps historical boxscores available indefinitely, so a
    completed game's stats are always recoverable regardless of local cache
    retention.
    """
    cached_path = raw_feed_live_path(selected_date, game_pk)
    if cached_path is not None:
        try:
            import gzip
            import json

            raw_bytes = cached_path.read_bytes()
            if cached_path.suffix == ".gz":
                raw_bytes = gzip.decompress(raw_bytes)
            payload = json.loads(raw_bytes.decode("utf-8"))
            if isinstance(payload, dict):
                return payload
        except Exception:
            pass
    if not fetch_if_missing:
        return None
    try:
        import urllib.request
        import json

        url = f"https://statsapi.mlb.com/api/v1.1/game/{int(game_pk)}/feed/live"
        with urllib.request.urlopen(url, timeout=15) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return payload if isinstance(payload, dict) else None
    except Exception:
        return None
