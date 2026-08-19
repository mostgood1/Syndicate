"""Feature loaders: Syndicate NHL data -> frozen ``hockeysim`` contracts -> projected lambdas.

Mirrors ``soccersim.features.loaders`` / football ``features/loaders.py``. Reads the
Syndicate-owned NHL artifact mirror (``data/nhl_source/data/processed`` + the odds games mirror)
and ``syndicate.local_nhl_odds`` team maps, assembles :class:`HockeyGameFeatures`, and runs the
:mod:`hockeysim.projection` layer so every game carries per-period goal lambdas the game-market
adapter consumes.

Reader discipline (soccersim ``sources.py`` lesson): per-date artifacts are **not** cached (a
gunicorn worker would otherwise serve a stale slate forever); only the process-wide root
resolution is memoized. All readers degrade gracefully — a missing file yields league-average
features, never an exception, matching the "degraded/empty state, not on-request backfill" rule.
"""
from __future__ import annotations

import csv
import os
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from syndicate.local_nhl_odds import TEAM_NAME_TO_ABBR, _team_abbr

from ..contracts import HockeyGameFeatures, HockeyMarketLines, HockeyPlayerFeatures, HockeyTeamFeatures
from ..projection import NHL_PROJECTION_PROFILE, ProjectionProfile, apply_projection

# ---------------------------------------------------------------------------
# Root + path resolution
# ---------------------------------------------------------------------------

# loaders.py -> features -> hockeysim -> sim_engine -> nhl -> features -> syndicate -> <repo root>
_REPO_ROOT = Path(__file__).resolve().parents[6]


@lru_cache(maxsize=4)
def nhl_source_root() -> Path:
    """Resolve the NHL artifact mirror root.

    Honors ``SYNDICATE_ARTIFACT_ROOT_NHL`` (a published bundle) then falls back to the in-repo
    ``data/nhl_source`` mirror. Cached because the root is process-stable (unlike per-date files).
    """
    env = os.getenv("SYNDICATE_ARTIFACT_ROOT_NHL")
    if env:
        p = Path(env)
        if p.exists():
            return p
    return _REPO_ROOT / "data" / "nhl_source"


def _processed_dir(root: Optional[Path] = None) -> Path:
    return (root or nhl_source_root()) / "data" / "processed"


def _odds_games_dir(root: Optional[Path] = None) -> Path:
    return (root or nhl_source_root()) / "data" / "odds" / "games"


def _read_csv_rows(path: Path) -> List[Dict[str, str]]:
    """Read a CSV into a list of dict rows; ``[]`` if absent/empty/unreadable."""
    try:
        if not path.exists() or path.stat().st_size == 0:
            return []
        with path.open("r", encoding="utf-8-sig", newline="") as fh:
            return [dict(r) for r in csv.DictReader(fh)]
    except (OSError, csv.Error, UnicodeDecodeError):
        return []


def _season_code_for_date(date: str) -> str:
    """NHL season code ``YYYY-YYYY+1`` from a ``YYYY-MM-DD`` date (season flips ~July)."""
    try:
        year = int(str(date)[:4])
        month = int(str(date)[5:7])
    except (ValueError, IndexError):
        return ""
    # NHL season starts in October; Jan-Jun belongs to the season that began the prior year.
    start_year = year if month >= 7 else year - 1
    return f"{start_year}-{start_year + 1}"


# Public alias. `load_team_xg_map` and `load_team_elo_map` both key their artifact filename off
# this convention (`team_{xg,elo}_{season}.csv`); a producer script needs the SAME convention to
# name what it writes, not the raw NHL API `season` field (`"20252026"`, no dash) -- that mismatch
# is exactly the kind of silent miss `model_engine_standard.md` §4.1 warns about ("absent" vs.
# "named differently"). `scripts/build_nhl_elo_artifact.py` imports this rather than reimplementing it.
season_code_for_date = _season_code_for_date


def _to_float(value: object) -> Optional[float]:
    try:
        if value is None or str(value).strip() == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _abbr(name: str) -> Optional[str]:
    return _team_abbr(name)


# ---------------------------------------------------------------------------
# Data readers (all degrade to empty/None; never raise on missing data)
# ---------------------------------------------------------------------------


def load_team_xg_map(date: str, *, root: Optional[Path] = None) -> Dict[str, Dict[str, float]]:
    """Load ``{ABBR: {"xgf60": float, "xga60": float}}`` for a date.

    Re-homed from the vendor ``data/team_xg.py`` reader against the Syndicate mirror path. Looks
    for ``team_xg_{season}.csv`` then ``team_xg_latest.csv`` under the processed dir. Returns an
    empty map when unavailable so the projection falls back to league-average strength.
    """
    proc = _processed_dir(root)
    season = _season_code_for_date(date)
    candidates = [proc / f"team_xg_{season}.csv", proc / "team_xg_latest.csv"]
    rows: List[Dict[str, str]] = []
    for path in candidates:
        rows = _read_csv_rows(path)
        if rows:
            break
    if not rows:
        return {}

    out: Dict[str, Dict[str, float]] = {}
    for row in rows:
        lower = {k.lower(): v for k, v in row.items()}
        ab = lower.get("abbr") or lower.get("team") or lower.get("team_abbr")
        xf = _to_float(lower.get("xgf60") or lower.get("xgf_per60") or lower.get("xgf60_all"))
        xa = _to_float(lower.get("xga60") or lower.get("xga_per60") or lower.get("xga60_all"))
        key = _abbr(ab) or (str(ab).upper() if ab else None)
        if not key or xf is None:
            continue
        entry = {"xgf60": xf}
        if xa is not None:
            entry["xga60"] = xa
        out[key] = entry
    return out


def load_team_rates_map(date: str, *, root: Optional[Path] = None) -> Dict[str, Dict[str, float]]:
    """Load ``{ABBR: {"shots_per_60":.., "faceoff_win_pct":..}}`` for a date.

    Written by ``scripts/build_nhl_team_rates_artifact.py`` from real boxscore (SOG) and
    play-by-play (faceoffs) data -- closes 2 of the 4 team-level ``HockeyTeamFeatures`` fields
    ``docs/ai_context/hockeysim_engine_reference.md`` §5 originally flagged as genuinely absent.
    `penalties_per_60` was handled separately (from `special_teams_map`'s already-computed
    `committed_per_game`) and `blocks_per_60` came from this same producer -- **both were later
    REMOVED from `HockeyTeamFeatures`/`TeamRates` entirely** (§2l) once proven a confirmed dead
    gate (`engine.py` never read either). The CSV this reads may still carry a `blocks_per_60`
    column from an older producer run; it is deliberately ignored below. Same candidate-order
    convention as `load_team_xg_map`/`load_team_elo_map`. Returns an empty map when unavailable,
    so `HockeyTeamFeatures` falls back to its own hardcoded league-average defaults
    (`shots_per_60=30.0`/`faceoff_win_pct=0.5`) exactly as it did before this producer existed --
    a missing file degrades, it does not break.
    """
    proc = _processed_dir(root)
    season = _season_code_for_date(date)
    candidates = [proc / f"team_rates_{season}.csv", proc / "team_rates_latest.csv"]
    rows: List[Dict[str, str]] = []
    for path in candidates:
        rows = _read_csv_rows(path)
        if rows:
            break
    if not rows:
        return {}

    out: Dict[str, Dict[str, float]] = {}
    for row in rows:
        lower = {k.lower(): v for k, v in row.items()}
        ab = lower.get("abbr") or lower.get("team")
        key = _abbr(ab) or (str(ab).upper() if ab else None)
        if not key:
            continue
        shots = _to_float(lower.get("shots_per_60"))
        fo = _to_float(lower.get("faceoff_win_pct"))
        entry: Dict[str, float] = {}
        if shots is not None:
            entry["shots_per_60"] = shots
        if fo is not None:
            entry["faceoff_win_pct"] = fo
        if entry:
            out[key] = entry
    return out


def load_player_rates_map(date: str, *, root: Optional[Path] = None) -> Dict[int, Dict[str, float]]:
    """Load ``{player_id: {"shot_weight":.., "goal_weight":.., "block_weight":..}}`` for a date.

    Written by ``scripts/build_nhl_player_rates_artifact.py`` from real boxscore per-skater stats --
    closes the last 3 genuinely-absent ``HockeyPlayerFeatures`` fields
    ``docs/ai_context/hockeysim_engine_reference.md`` §5 tracked. UNLIKE the team-rates producer,
    keyed by integer player id, not team abbreviation -- season-wide, so the SAME candidate-order
    convention (season file, then ``_latest``) still applies, just with a per-player row shape.
    Returns an empty map when unavailable, so `HockeyPlayerFeatures` falls back to `None` on these
    fields, which `engine.py`'s own position/TOI heuristic already handles gracefully -- a missing
    file degrades to that existing fallback, it does not break.
    """
    proc = _processed_dir(root)
    season = _season_code_for_date(date)
    candidates = [proc / f"player_rates_{season}.csv", proc / "player_rates_latest.csv"]
    rows: List[Dict[str, str]] = []
    for path in candidates:
        rows = _read_csv_rows(path)
        if rows:
            break
    if not rows:
        return {}

    out: Dict[int, Dict[str, float]] = {}
    for row in rows:
        lower = {k.lower(): v for k, v in row.items()}
        pid = _safe_int(lower.get("player_id"))
        if pid is None:
            continue
        sw = _to_float(lower.get("shot_weight"))
        gw = _to_float(lower.get("goal_weight"))
        bw = _to_float(lower.get("block_weight"))
        entry: Dict[str, float] = {}
        if sw is not None:
            entry["shot_weight"] = sw
        if gw is not None:
            entry["goal_weight"] = gw
        if bw is not None:
            entry["block_weight"] = bw
        if entry:
            out[pid] = entry
    return out


def load_team_elo_map(date: str, *, root: Optional[Path] = None) -> Dict[str, float]:
    """Load ``{ABBR: elo}`` for a date.

    Written by ``scripts/build_nhl_elo_artifact.py`` from real settled results
    (`historical_truth.elo_builder`). Looks for ``team_elo_{season}.csv`` then
    ``team_elo_latest.csv`` under the processed dir, mirroring :func:`load_team_xg_map`'s
    candidate order exactly. Returns an empty map when unavailable so ``elo_rating`` stays
    ``None`` and the projection's Elo blend (already gated at ``elo_blend_weight == 0.0`` by
    default) has nothing to blend -- a missing file is a silent no-op here precisely because
    the consumer already treats an absent rating as "no signal", not an error.
    """
    proc = _processed_dir(root)
    season = _season_code_for_date(date)
    candidates = [proc / f"team_elo_{season}.csv", proc / "team_elo_latest.csv"]
    rows: List[Dict[str, str]] = []
    for path in candidates:
        rows = _read_csv_rows(path)
        if rows:
            break
    if not rows:
        return {}

    out: Dict[str, float] = {}
    for row in rows:
        lower = {k.lower(): v for k, v in row.items()}
        ab = lower.get("abbr") or lower.get("team") or lower.get("team_abbr")
        elo = _to_float(lower.get("elo") or lower.get("rating"))
        key = _abbr(ab) or (str(ab).upper() if ab else None)
        if not key or elo is None:
            continue
        out[key] = elo
    return out


def load_team_special_teams_map(date: str, *, root: Optional[Path] = None) -> Dict[str, Dict[str, float]]:
    """Load ``{ABBR: {"pp_pct":..., "pk_pct":..., "committed_per_game":..., "pp_shot_index":...,
    "pk_shot_index_allowed":..., "block_rate_index":..., "faceoff_ev_index":...,
    "faceoff_oz_index":...}}`` for a date.

    Written by ``scripts/build_nhl_special_teams_artifact.py`` from real settled results
    (`historical_truth.special_teams_builder` for the first three keys;
    `historical_truth.boxscore_shot_strength` for the shot-index pair, §2f;
    `historical_truth.boxscore_block_rate` for `block_rate_index`, §2g;
    `historical_truth.faceoff_ev_index` for `faceoff_ev_index`/`faceoff_oz_index`, §2m/§2n -- all
    absent when the producer ran without the matching cache, degrading to the engine's own neutral
    default rather than missing entirely). Same candidate-order convention as
    :func:`load_team_xg_map`/:func:`load_team_elo_map`. Returns an empty map when unavailable, so
    ``HockeyTeamFeatures.special_teams`` stays ``{}`` and the engine falls back to its own
    league-average defaults (`engine.py:667-668`) exactly as it did before this producer existed --
    a missing file degrades, it does not break.
    """
    proc = _processed_dir(root)
    season = _season_code_for_date(date)
    candidates = [proc / f"team_special_teams_{season}.csv", proc / "team_special_teams_latest.csv"]
    rows: List[Dict[str, str]] = []
    for path in candidates:
        rows = _read_csv_rows(path)
        if rows:
            break
    if not rows:
        return {}

    out: Dict[str, Dict[str, float]] = {}
    for row in rows:
        lower = {k.lower(): v for k, v in row.items()}
        ab = lower.get("abbr") or lower.get("team")
        key = _abbr(ab) or (str(ab).upper() if ab else None)
        if not key:
            continue
        pp = _to_float(lower.get("pp_pct"))
        pk = _to_float(lower.get("pk_pct"))
        committed = _to_float(lower.get("committed_per_game"))
        pp_shot_idx = _to_float(lower.get("pp_shot_index"))
        pk_shot_idx = _to_float(lower.get("pk_shot_index_allowed"))
        block_idx = _to_float(lower.get("block_rate_index"))
        faceoff_ev_idx = _to_float(lower.get("faceoff_ev_index"))
        faceoff_oz_idx = _to_float(lower.get("faceoff_oz_index"))
        entry: Dict[str, float] = {}
        if pp is not None:
            entry["pp_pct"] = pp
        if pk is not None:
            entry["pk_pct"] = pk
        if committed is not None:
            entry["committed_per_game"] = committed
        if pp_shot_idx is not None:
            entry["pp_shot_index"] = pp_shot_idx
        if pk_shot_idx is not None:
            entry["pk_shot_index_allowed"] = pk_shot_idx
        if block_idx is not None:
            entry["block_rate_index"] = block_idx
        if faceoff_ev_idx is not None:
            entry["faceoff_ev_index"] = faceoff_ev_idx
        if faceoff_oz_idx is not None:
            entry["faceoff_oz_index"] = faceoff_oz_idx
        if entry:
            out[key] = entry
    return out


def load_lineups(date: str, *, root: Optional[Path] = None) -> Dict[str, List[Dict[str, str]]]:
    """Load ``lineups_{date}.csv`` grouped by team abbreviation."""
    rows = _read_csv_rows(_processed_dir(root) / f"lineups_{date}.csv")
    grouped: Dict[str, List[Dict[str, str]]] = {}
    for row in rows:
        key = _abbr(row.get("team")) or str(row.get("team") or "").upper()
        if key:
            grouped.setdefault(key, []).append(row)
    return grouped


def load_roster(date: str, *, root: Optional[Path] = None) -> Dict[str, List[Dict[str, str]]]:
    """Load ``roster_snapshot_{date}.csv`` grouped by team abbreviation."""
    rows = _read_csv_rows(_processed_dir(root) / f"roster_snapshot_{date}.csv")
    grouped: Dict[str, List[Dict[str, str]]] = {}
    for row in rows:
        key = _abbr(row.get("team")) or str(row.get("team") or "").upper()
        if key:
            grouped.setdefault(key, []).append(row)
    return grouped


def load_starting_goalies(date: str, *, root: Optional[Path] = None) -> Dict[str, Dict[str, str]]:
    """Load ``starting_goalies_{date}.csv`` keyed by team abbreviation."""
    rows = _read_csv_rows(_processed_dir(root) / f"starting_goalies_{date}.csv")
    out: Dict[str, Dict[str, str]] = {}
    for row in rows:
        key = _abbr(row.get("team")) or str(row.get("team") or "").upper()
        if key:
            out[key] = row
    return out


# ---------------------------------------------------------------------------
# Feature assembly (pure — inputs in, contracts out)
# ---------------------------------------------------------------------------

_POSITION_MAP = {
    "C": "F", "L": "F", "R": "F", "LW": "F", "RW": "F", "F": "F", "W": "F",
    "D": "D", "LD": "D", "RD": "D",
    "G": "G",
}


def _canonical_position(raw: object) -> str:
    token = str(raw or "").strip().upper()
    return _POSITION_MAP.get(token, "F" if token and token != "G" else token or "F")


def build_team_features(
    name: str,
    *,
    abbrev: Optional[str] = None,
    xg_map: Optional[Dict[str, Dict[str, float]]] = None,
    elo_map: Optional[Dict[str, float]] = None,
    special_teams_map: Optional[Dict[str, Dict[str, float]]] = None,
    rates_map: Optional[Dict[str, Dict[str, float]]] = None,
) -> HockeyTeamFeatures:
    """Assemble one side's team-strength features, filling xGF/xGA/Elo/special-teams/rates when
    present. `shots_per_60`/`faceoff_win_pct` are NOT Optional on `HockeyTeamFeatures` (unlike
    xGF/Elo) -- they carry hardcoded league-average defaults, so a value is only passed through
    when one is genuinely available; omitting the keyword lets the dataclass's own default apply,
    exactly the fallback behavior this function had before these inputs existed.

    `blocks_per_60`/`penalties_per_60` are NOT wired here (`docs/ai_context/
    hockeysim_engine_reference.md` §2l) -- both were REMOVED from `HockeyTeamFeatures` after being
    proven a confirmed dead gate: `engine.py` never read either field once populated. Block volume
    is already fully governed by the truth-calibrated per-shot `block_rate_*` mechanism; penalty
    rate already drives PP/PK segment generation via `special_teams`'s `committed_per_game` below.
    """
    ab = abbrev or _abbr(name)
    xgf = xga = None
    if xg_map and ab and ab in xg_map:
        xgf = xg_map[ab].get("xgf60")
        xga = xg_map[ab].get("xga60")
    elo = elo_map.get(ab) if (elo_map and ab) else None
    special_teams = dict(special_teams_map[ab]) if (special_teams_map and ab and ab in special_teams_map) else {}

    extra: Dict[str, float] = {}
    if rates_map and ab and ab in rates_map:
        r = rates_map[ab]
        if "shots_per_60" in r:
            extra["shots_per_60"] = r["shots_per_60"]
        if "faceoff_win_pct" in r:
            extra["faceoff_win_pct"] = r["faceoff_win_pct"]

    return HockeyTeamFeatures(
        name=name, abbrev=ab, xgf_per_60=xgf, xga_per_60=xga, elo_rating=elo,
        special_teams=special_teams, **extra,
    )


def build_player_features(
    team_rows: List[Dict[str, str]],
    *,
    starting_goalie: Optional[Dict[str, str]] = None,
    player_rates_map: Optional[Dict[int, Dict[str, float]]] = None,
) -> Tuple[HockeyPlayerFeatures, ...]:
    """Assemble a team's player features from lineup/roster rows (+ optional starting goalie).

    `shot_weight`/`goal_weight`/`block_weight` ARE `Optional` on `HockeyPlayerFeatures` (unlike the
    team-rate fields) -- `None` is the correct "no data" value, and `engine.py` already has a
    documented position/TOI heuristic fallback for exactly that case, so a value is only passed
    through when `player_rates_map` genuinely has one for this player.
    """
    goalie_name = str((starting_goalie or {}).get("goalie") or "").strip().lower()
    players: List[HockeyPlayerFeatures] = []
    for row in team_rows:
        pid = row.get("player_id")
        try:
            pid_int = int(float(pid)) if pid not in (None, "") else 0
        except (TypeError, ValueError):
            pid_int = 0
        position = _canonical_position(row.get("position"))
        full_name = str(row.get("full_name") or "").strip()
        is_starter = bool(goalie_name) and position == "G" and full_name.lower() == goalie_name
        rates = player_rates_map.get(pid_int) if (player_rates_map and pid_int) else None
        players.append(
            HockeyPlayerFeatures(
                player_id=pid_int,
                full_name=full_name,
                position=position,
                proj_toi=_to_float(row.get("proj_toi")) or 0.0,
                shot_weight=(rates or {}).get("shot_weight"),
                goal_weight=(rates or {}).get("goal_weight"),
                block_weight=(rates or {}).get("block_weight"),
                line_slot=(str(row.get("line_slot")).strip() or None) if row.get("line_slot") else None,
                pp_unit=_safe_int(row.get("pp_unit")),
                pk_unit=_safe_int(row.get("pk_unit")),
                is_starting_goalie=is_starter,
            )
        )
    return tuple(players)


def _safe_int(value: object) -> Optional[int]:
    try:
        if value is None or str(value).strip() == "":
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None


def build_game_features(
    game_pk: str,
    date: str,
    home_name: str,
    away_name: str,
    *,
    root: Optional[Path] = None,
    market: Optional[HockeyMarketLines] = None,
    xg_map: Optional[Dict[str, Dict[str, float]]] = None,
    elo_map: Optional[Dict[str, float]] = None,
    special_teams_map: Optional[Dict[str, Dict[str, float]]] = None,
    rates_map: Optional[Dict[str, Dict[str, float]]] = None,
    player_rates_map: Optional[Dict[int, Dict[str, float]]] = None,
    lineups: Optional[Dict[str, List[Dict[str, str]]]] = None,
    goalies: Optional[Dict[str, Dict[str, str]]] = None,
    profile: ProjectionProfile = NHL_PROJECTION_PROFILE,
    project: bool = True,
    anchor_to_market: bool = False,
    anchor_weight: float = 0.35,
) -> HockeyGameFeatures:
    """Assemble a fully-featured, projection-primed :class:`HockeyGameFeatures` for one game.

    When ``project`` is true (default) the projection layer is run and each side's
    ``period_goal_lambdas`` is set from it, so the game-market adapter needs no extra step.
    When ``anchor_to_market`` is true and a usable market moneyline is present, the projected
    lambdas are then anchored toward the book (Phase 4, opt-in; no-op without odds).
    Pre-loaded maps may be passed (slate loader shares them across games); otherwise they are
    read per call. Unavailable inputs degrade to league-average / empty, never an exception.
    """
    if xg_map is None:
        xg_map = load_team_xg_map(date, root=root)
    if elo_map is None:
        elo_map = load_team_elo_map(date, root=root)
    if special_teams_map is None:
        special_teams_map = load_team_special_teams_map(date, root=root)
    if rates_map is None:
        rates_map = load_team_rates_map(date, root=root)
    if player_rates_map is None:
        player_rates_map = load_player_rates_map(date, root=root)
    if lineups is None:
        lineups = load_lineups(date, root=root)
    if goalies is None:
        goalies = load_starting_goalies(date, root=root)

    home = build_team_features(home_name, xg_map=xg_map, elo_map=elo_map, special_teams_map=special_teams_map, rates_map=rates_map)
    away = build_team_features(away_name, xg_map=xg_map, elo_map=elo_map, special_teams_map=special_teams_map, rates_map=rates_map)

    if project:
        home, away, _proj = apply_projection(home, away, profile=profile)

    home_ab = home.abbrev or _abbr(home_name)
    away_ab = away.abbrev or _abbr(away_name)
    home_players = build_player_features(
        lineups.get(home_ab, []) if home_ab else [], starting_goalie=(goalies or {}).get(home_ab or ""),
        player_rates_map=player_rates_map,
    )
    away_players = build_player_features(
        lineups.get(away_ab, []) if away_ab else [], starting_goalie=(goalies or {}).get(away_ab or ""),
        player_rates_map=player_rates_map,
    )

    game = HockeyGameFeatures(
        game_pk=str(game_pk),
        date=str(date),
        home=home,
        away=away,
        home_players=home_players,
        away_players=away_players,
        market=market or HockeyMarketLines(),
    )

    if anchor_to_market and project:
        from ..market_anchoring import anchor_game_features
        game = anchor_game_features(game, weight=anchor_weight)
    return game


def _load_scoreboard_games(date: str, root: Optional[Path] = None) -> List[Tuple[str, str, str]]:
    """Return ``[(game_pk, home_name, away_name)]`` for a date from the odds games mirror."""
    path = _odds_games_dir(root) / f"date={date}" / "scoreboard.csv"
    rows = _read_csv_rows(path)
    seen: Dict[str, Tuple[str, str, str]] = {}
    for row in rows:
        pk = str(row.get("gamePk") or row.get("game_pk") or "").strip()
        home = str(row.get("home") or row.get("home_team") or "").strip()
        away = str(row.get("away") or row.get("away_team") or "").strip()
        if pk and home and away and pk not in seen:
            seen[pk] = (pk, home, away)
    return list(seen.values())


def build_slate_features(
    date: str,
    *,
    root: Optional[Path] = None,
    profile: ProjectionProfile = NHL_PROJECTION_PROFILE,
    project: bool = True,
    anchor_to_market: bool = False,
    anchor_weight: float = 0.35,
) -> List[HockeyGameFeatures]:
    """Assemble projection-primed features for every game on a date's scoreboard.

    Shared per-date maps (xG / Elo / special-teams / team-rates / player-rates / lineups /
    goalies) are read once and reused across games. ``anchor_to_market`` opts into Phase-4 market
    anchoring per game (no-op without odds). Returns ``[]`` when no scoreboard is mirrored for the
    date.
    """
    games = _load_scoreboard_games(date, root=root)
    if not games:
        return []
    xg_map = load_team_xg_map(date, root=root)
    elo_map = load_team_elo_map(date, root=root)
    special_teams_map = load_team_special_teams_map(date, root=root)
    rates_map = load_team_rates_map(date, root=root)
    player_rates_map = load_player_rates_map(date, root=root)
    lineups = load_lineups(date, root=root)
    goalies = load_starting_goalies(date, root=root)
    out: List[HockeyGameFeatures] = []
    for pk, home_name, away_name in games:
        out.append(
            build_game_features(
                pk, date, home_name, away_name,
                root=root, xg_map=xg_map, elo_map=elo_map, special_teams_map=special_teams_map,
                rates_map=rates_map, player_rates_map=player_rates_map, lineups=lineups, goalies=goalies,
                profile=profile, project=project,
                anchor_to_market=anchor_to_market, anchor_weight=anchor_weight,
            )
        )
    return out
