"""Season-level metric VALUES for intelligence pick explanations, per sport.

WHY THIS EXISTS (lane `intelligence-evidence-coverage`, 2026-10-07). The
intelligence layer's "advanced inputs" (`intelligence._advanced_input_specs_for_sport`)
only ever checked that a file EXISTED and then printed the metric NAMES it
"covers" -- a pick explanation read "Advanced drivers in play: Statcast batter
and pitcher features: Launch angle, Exit velocity, Barrel rate" with no number
from that file anywhere in the payload. Measured on the fleet 2026-10-07 16:33Z:
`advanced_signals` was empty on 77 of 77 recommendations, and the readiness gate
read `ready` for NCAAF with 0 of 27 inputs present, because it counted only
paths inside the git checkout and production data lives under
`SYNDICATE_DATA_ROOT`.

This module reads the season tables that ARE on the data root and returns the
numbers for the two teams (or the player) a candidate is about, each with its
league rank, sample size, source file and a season status:

  * ``current``                 -- built from this season's games.
  * ``prior_season_expected``   -- the new season has not started; last
                                   season's table is the right prior.
  * ``prior_season``            -- the new season HAS started and this table
                                   still predates it. Served, but flagged in the
                                   explanation; it is not hidden.
  * ``missing``                 -- no table on the data root at all.

Only ``missing`` makes a sport not-ready. A stale table is still evidence, and
`advanced_ready` LEADS the recommendation rank tuple
(`intelligence._candidate_betting_rank_key`), so demoting a whole sport for
staleness would be a ranking change dressed as a data fix.

NOT A SCORE TERM. Nothing here feeds `advanced_signal_score`, `board_score` or
any rank key: these are `season_signals`, read by the explanation only. Adding
them to a score is a separate, backtested decision (the lane's phase 2) --
adding a mechanism to a calibrated ranker without re-fitting it is how two
mechanisms produced a negative interaction in 4 of 4 markets
(docs/ai_context/model_engine_standard.md).

READS ARE BOUNDED. Every table here is under ~100 KB except MLB Statcast, which
`intelligence` already loads and caches itself and which this module does not
touch. Parsed tables are cached keyed on (path, mtime_ns, size), so a rewrite is
picked up on the next call and the cache cannot outgrow ``_CACHE_MAX`` entries.
"""

from __future__ import annotations

import csv
import datetime as _dt
import glob
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from syndicate.features.shared.prop_evidence.common import data_root

# --------------------------------------------------------------------------- #
# Season calendar. Approximate opening day of each sport's REGULAR season for a
# season that starts in calendar year Y. A table whose content predates the
# current season's opening day is "prior season". Off by a few days is harmless:
# it only decides between two flags, never whether data is served.
# --------------------------------------------------------------------------- #
_SEASON_OPEN_MONTH_DAY: dict[str, tuple[int, int]] = {
    "mlb": (3, 26),
    "nba": (10, 20),
    "wnba": (5, 15),
    "nhl": (10, 7),
    "nfl": (9, 4),
    "ncaaf": (8, 23),
    "ncaab": (11, 3),
    "soccer": (8, 8),
}

# Sports whose season ends in the calendar year after it opens.
_CROSS_YEAR = {"nba", "nhl", "ncaab", "soccer"}

# Rough length of the regular season + playoffs in days, used only to decide
# whether "today" is inside the season that opened most recently.
_SEASON_LENGTH_DAYS: dict[str, int] = {
    "mlb": 220,
    "nba": 240,
    "wnba": 160,
    "nhl": 250,
    "nfl": 160,
    "ncaaf": 140,
    "ncaab": 160,
    "soccer": 300,
}


def season_open(sport: str, today: _dt.date) -> _dt.date:
    """Opening day of the most recent season that has opened on or before ``today``.

    Before this year's opening day that is LAST year's opening day.
    """
    month, day = _SEASON_OPEN_MONTH_DAY[sport]
    this_year = _dt.date(today.year, month, day)
    return this_year if today >= this_year else _dt.date(today.year - 1, month, day)


def next_season_open(sport: str, today: _dt.date) -> _dt.date:
    month, day = _SEASON_OPEN_MONTH_DAY[sport]
    this_year = _dt.date(today.year, month, day)
    return this_year if today < this_year else _dt.date(today.year + 1, month, day)


def season_status(sport: str, as_of: _dt.date | None, today: _dt.date) -> str:
    """Classify a table's content date against the sport's calendar.

    ``as_of`` is when the table's CONTENT was computed (an embedded stamp when
    the file carries one, else its mtime). Unknown age is ``prior_season``:
    unknown must not default permissive (learnings 2026-09-18).
    """
    if as_of is None:
        return "prior_season"
    opened = season_open(sport, today)
    in_season = (today - opened).days <= _SEASON_LENGTH_DAYS[sport]
    if in_season:
        return "current" if as_of >= opened else "prior_season"
    # Offseason or preseason: the season that opened last is over. A table
    # built during it is the right prior for the next one; anything older is
    # two seasons stale.
    return "prior_season_expected" if as_of >= opened else "prior_season"


def season_label(sport: str, today: _dt.date) -> str:
    """Human label of the season ``today`` belongs to (or the next one, preseason)."""
    opened = season_open(sport, today)
    in_season = (today - opened).days <= _SEASON_LENGTH_DAYS[sport]
    start = opened if in_season else next_season_open(sport, today)
    if sport in _CROSS_YEAR:
        return f"{start.year}-{str(start.year + 1)[-2:]}"
    return str(start.year)


# --------------------------------------------------------------------------- #
# Bounded parse cache.
# --------------------------------------------------------------------------- #
_CACHE: dict[tuple[str, int, int], Any] = {}
_CACHE_MAX = 64


def _cached(path: Path, loader: Callable[[Path], Any]) -> Any:
    try:
        stat = path.stat()
    except OSError:
        return None
    key = (str(path), int(stat.st_mtime_ns), int(stat.st_size))
    if key in _CACHE:
        return _CACHE[key]
    try:
        value = loader(path)
    except Exception as exc:  # a corrupt table must read as absent, not crash the build
        print(f"[intelligence_season] TABLE_UNREADABLE path={path} error={type(exc).__name__}: {exc}", flush=True)
        value = None
    if len(_CACHE) >= _CACHE_MAX:
        _CACHE.clear()
    _CACHE[key] = value
    return value


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _num(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if out != out:  # NaN
        return None
    return out


def _mtime_date(path: Path) -> _dt.date | None:
    try:
        return _dt.datetime.fromtimestamp(path.stat().st_mtime, _dt.timezone.utc).date()
    except OSError:
        return None


def _iso_date(value: Any) -> _dt.date | None:
    text = str(value or "").strip()
    match = re.search(r"(\d{4})-?(\d{2})-?(\d{2})", text)
    if not match:
        return None
    try:
        return _dt.date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None


def _sport_dirs(sport: str) -> list[Path]:
    """Every root a sport's tables are published under, most specific first.

    Same rule as `prop_evidence.common.sport_roots`, plus the per-sport
    ``SYNDICATE_<SPORT>_SOURCE_ROOT`` override the fleet sets.
    """
    bases: list[Path] = []
    override = str(os.environ.get(f"SYNDICATE_{sport.upper()}_SOURCE_ROOT") or "").strip()
    if override:
        bases.append(Path(override))
    bases.append(data_root() / f"{sport}_source")
    out: list[Path] = []
    for base in bases:
        for root in (base / "data", base / "source_artifacts" / "data", base):
            if root not in out:
                out.append(root)
    return out


def _glob_all(sport: str, pattern: str) -> list[Path]:
    seen: set[str] = set()
    found: list[Path] = []
    for root in _sport_dirs(sport):
        for raw in glob.glob(str(root / pattern), recursive=True):
            real = os.path.realpath(raw)
            if real in seen or not os.path.isfile(raw):
                continue
            seen.add(real)
            found.append(Path(raw))
    return found


# --------------------------------------------------------------------------- #
# Table resolution.
# --------------------------------------------------------------------------- #
@dataclass
class Table:
    """One season table, resolved on the data root."""

    family: str
    label: str
    path: Path | None
    as_of: _dt.date | None
    rows: dict[str, dict[str, Any]] = field(default_factory=dict)
    sample_field: str | None = None
    note: str = ""
    # appended to every metric label from this table, e.g. "this season" -- so a
    # sentence mixing a season-to-date table with a full-season one says which is which
    metric_suffix: str = ""


def _newest_asof(paths: list[Path], stem_regex: str) -> Path | None:
    """Pick the table to trust from a family of season/asof files.

    The dated ``_asof_YYYYMMDD`` files are the live ones. The plain
    ``<stem>_<season>.csv`` can be a stale git seed: measured on the fleet
    2026-10-07, WNBA's plain ``team_advanced_stats_2026.csv`` held 5-8 games
    per team while ``..._asof_20261007.csv`` held 43-47. So: newest asof first,
    then the plain file with the highest season, newest mtime breaking ties.
    """
    dated: list[tuple[str, float, Path]] = []
    plain: list[tuple[int, float, Path]] = []
    for path in paths:
        name = path.name
        match = re.fullmatch(stem_regex + r"_(\d{4})_asof_(\d{4}-?\d{2}-?\d{2})\.csv", name)
        if match:
            dated.append((int(match.group(1)), match.group(2).replace("-", ""), path.stat().st_mtime, path))
            continue
        match = re.fullmatch(stem_regex + r"_(\d{4})\.csv", name)
        if match:
            plain.append((int(match.group(1)), path.stat().st_mtime, path))
    if dated:
        # Season FIRST, then as-of: a later-dated rebuild of an OLDER season
        # (`team_advanced_stats_2025_asof_2026-06-03.csv`, measured 2026-10-07:
        # every NBA team identical) must not outrank the newest season.
        return max(dated, key=lambda item: item[:3])[3]
    if plain:
        return max(plain)[2]
    return None


def _team_table(
    sport: str,
    family: str,
    label: str,
    path: Path | None,
    *,
    key_field: str,
    canonical: Callable[[str], str | None],
    as_of: _dt.date | None = None,
    sample_field: str | None = "games",
) -> Table:
    table = Table(family=family, label=label, path=path, as_of=as_of, sample_field=sample_field)
    if path is None:
        return table
    rows = _cached(path, _read_csv) or []
    for row in rows:
        raw = str(row.get(key_field) or "").strip()
        if not raw:
            continue
        key = canonical(raw) or raw.lower()
        table.rows[key] = row
    if table.as_of is None:
        asof_match = re.search(r"_asof_(\d{4}-?\d{2}-?\d{2})", path.name)
        table.as_of = _iso_date(asof_match.group(1)) if asof_match else _mtime_date(path)
    return table


def _canonical(sport: str) -> Callable[[str], str | None]:
    def resolve(value: str) -> str | None:
        try:
            from syndicate.features.shared.team_aliases import canonical_team
        except Exception:
            return None
        try:
            return canonical_team(sport, value)
        except Exception:
            return None

    return resolve


def _basketball_tables(sport: str) -> list[Table]:
    path = _newest_asof(_glob_all(sport, "processed/team_advanced_stats_*.csv"), r"team_advanced_stats")
    return [
        _team_table(sport, "team_advanced", "Team advanced stats", path, key_field="team", canonical=_canonical(sport)),
    ]


def _nhl_season_code(today: _dt.date) -> str:
    start = today.year if today.month >= 9 else today.year - 1
    return f"{start}-{start + 1}"


def _nhl_tables(today: _dt.date) -> list[Table]:
    """NHL season tables, THIS season first where it exists (user 2026-10-08: "utilize
    advanced data that includes this season").

    * `<stem>_<season>.csv` -- the in-season blend production's sim reads (lane
      `nhl-season-inputs-in-season`: team xG from the first game, the other stems
      from Nov 1) -- is preferred over the frozen `<stem>_latest.csv`. Its `games`
      column counts THIS season's games while the value blends last season in, so
      it carries no sample and says "blended" on the label.
    * `nhl_team_season_to_date_<season>.csv` (scripts/build_nhl_season_to_date.py)
      -- this season's raw numbers, labelled "this season", FIRST in order so the
      sentence reads this season, then the blend, then last season's tables.
    """
    canonical = _canonical("nhl")
    season = _nhl_season_code(today)
    out: list[Table] = []
    for family, label, stem in (
        ("team_season_to_date", f"This season to date ({season} regular season)", None),
        ("team_xg", "Team expected goals (5v5-weighted)", "team_xg"),
        ("team_special_teams", "Special teams", "team_special_teams"),
        ("team_rates", "Shot and faceoff rates", "team_rates"),
        ("team_elo", "Elo rating", "team_elo"),
    ):
        if stem is None:
            paths = _glob_all("nhl", f"processed/nhl_team_season_to_date_{season}.csv")
            table = _team_table("nhl", family, label, paths[0] if paths else None, key_field="abbr",
                                canonical=canonical, sample_field="games")
            table.metric_suffix = "this season"
            out.append(table)
            continue
        current = sorted(_glob_all("nhl", f"processed/{stem}_{season}.csv"), key=lambda p: p.stat().st_mtime)
        if current:
            table = _team_table("nhl", family, f"{label}, last season blended with this season's games", current[-1],
                                key_field="abbr", canonical=canonical, sample_field=None)
            table.metric_suffix = "blended with this season"
            out.append(table)
            continue
        paths = sorted(_glob_all("nhl", f"processed/{stem}_latest.csv"), key=lambda p: p.stat().st_mtime)
        sample = None if family == "team_elo" else "games"
        out.append(
            _team_table("nhl", family, label, paths[-1] if paths else None, key_field="abbr", canonical=canonical, sample_field=sample)
        )
    return out


def _nfl_tables() -> list[Table]:
    canonical = _canonical("nfl")
    best: tuple[int, int, float, Path] | None = None
    for path in _glob_all("nfl", "smartsim2_ratings_*.json") + [
        Path(p) for p in glob.glob(str(data_root() / "nfl_source" / "smartsim2_ratings_*.json"))
    ]:
        match = re.fullmatch(r"smartsim2_ratings_(\d{4})_wk(\d+)\.json", path.name)
        if not match:
            continue
        key = (int(match.group(1)), int(match.group(2)), path.stat().st_mtime, path)
        if best is None or key[:3] > best[:3]:
            best = key
    table = Table(family="team_epa", label="SmartSim team ratings (EPA/play)", path=best[3] if best else None, as_of=None, sample_field=None)
    if best is None:
        return [table]
    payload = _cached(best[3], _read_json) or {}
    teams = payload.get("teams") if isinstance(payload, dict) else None
    for abbr, entry in (teams or {}).items():
        if not isinstance(entry, dict):
            continue
        key = canonical(str(abbr)) or str(abbr).lower()
        table.rows[key] = {
            "offense_epa": entry.get("offense"),
            "defense_epa": entry.get("defense"),
            "rating_source": entry.get("rating_source"),
        }
    table.as_of = _iso_date(payload.get("generated_at")) if isinstance(payload, dict) else None
    table.as_of = table.as_of or _mtime_date(best[3])
    table.note = f"{payload.get('season')} week {payload.get('week')}" if isinstance(payload, dict) else ""
    return [table]


def _ncaaf_norm(value: str) -> str:
    """CFBD SP+ keys abbreviate "State" (`kennesaw st`); event ids spell it out
    (`Kennesaw_State`). Normalise both sides to the abbreviation."""
    text = re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()
    return re.sub(r"\bstate\b", "st", text)


def _ncaaf_tables(today: _dt.date) -> list[Table]:
    paths = _glob_all("ncaaf", "**/sp_ratings_*.json") + [
        Path(p) for p in glob.glob(str(data_root() / "ncaaf_source" / "historical_truth" / "sp_ratings_*.json"))
    ]
    best: tuple[int, float, Path] | None = None
    for path in paths:
        match = re.fullmatch(r"sp_ratings_(\d{4})\.json", path.name)
        if not match:
            continue
        key = (int(match.group(1)), path.stat().st_mtime, path)
        if best is None or key[:2] > best[:2]:
            best = key
    table = Table(family="sp_plus", label="SP+ ratings", path=best[2] if best else None, as_of=None, sample_field=None)
    if best is None:
        return [table]
    payload = _cached(best[2], _read_json) or {}
    for team, pair in ((payload.get("teams") if isinstance(payload, dict) else None) or {}).items():
        try:
            offense, defense = float(pair[0]), float(pair[1])
        except (TypeError, ValueError, IndexError, KeyError):
            continue
        # SP+ defence is points allowed per game against an average offence:
        # LOWER is better, so the overall margin is offence minus defence.
        table.rows[_ncaaf_norm(team)] = {"sp_offense": offense, "sp_defense": defense, "sp_overall": offense - defense}
    table.as_of = _iso_date(payload.get("fetched_at")) or _mtime_date(best[2])
    table.note = f"CFBD SP+ {payload.get('season')}"
    return [table]


def _soccer_player_tables() -> list[Table]:
    """Current-season per-player rates, one table per league (``<league>/players/players_<season>.csv``)."""
    base_dirs = [data_root() / "soccer_source"]
    override = str(os.environ.get("SYNDICATE_SOCCER_SOURCE_ROOT") or "").strip()
    if override:
        base_dirs.insert(0, Path(override))
    newest: dict[str, tuple[int, Path]] = {}
    for base in base_dirs:
        for raw in glob.glob(str(base / "*" / "players" / "players_*.csv")):
            path = Path(raw)
            match = re.fullmatch(r"players_(\d{4})\.csv", path.name)
            if not match:
                continue
            league = path.parent.parent.name
            season = int(match.group(1))
            if league not in newest or season > newest[league][0]:
                newest[league] = (season, path)
    tables: list[Table] = []
    for league, (season, path) in sorted(newest.items()):
        table = Table(family=f"players:{league}", label=f"{league} player rates {season}", path=path, as_of=_mtime_date(path), sample_field="games")
        for row in _cached(path, _read_csv) or []:
            name = str(row.get("player_name") or "").strip()
            if name:
                table.rows[name.lower()] = row
        tables.append(table)
    return tables


def _ncaab_tables() -> list[Table]:
    # Dated tables from `scripts/build_ncaab_team_ratings.py`
    # (`team_ratings_<season>_asof_<YYYYMMDD>.csv`): newest season, then newest as-of.
    path = _newest_asof(_glob_all("ncaab", "processed/team_ratings_*.csv"), r"team_ratings")
    return [
        _team_table("ncaab", "team_ratings", "Team efficiency ratings", path, key_field="team", canonical=_canonical("ncaab")),
    ]


# --------------------------------------------------------------------------- #
# MLB: player-level Statcast season features, keyed by MLBAM id.
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class _MlbSpec:
    field: str
    key: str
    label: str
    higher_is_better: bool
    fmt: str


_MLB_BATTER_METRICS = [
    _MlbSpec("xwoba", "batter_xwoba", "xwOBA", True, "num3"),
    _MlbSpec("barrel_rate", "batter_barrel_rate", "Barrel rate", True, "pct1"),
    _MlbSpec("hardhit_rate", "batter_hardhit_rate", "Hard-hit rate", True, "pct1"),
    _MlbSpec("ev_mean", "batter_ev_mean", "Exit velocity", True, "num1"),
    _MlbSpec("whiff_rate", "batter_whiff_rate", "Whiff rate", False, "pct1"),
]
_MLB_PITCHER_METRICS = [
    _MlbSpec("whiff_rate", "pitcher_whiff_rate", "Whiff rate", True, "pct1"),
    _MlbSpec("csw_rate", "pitcher_csw_rate", "CSW rate", True, "pct1"),
    _MlbSpec("xwoba", "pitcher_xwoba_allowed", "xwOBA allowed", False, "num3"),
    _MlbSpec("barrel_rate", "pitcher_barrel_rate_allowed", "Barrel rate allowed", False, "pct1"),
    _MlbSpec("gb_rate", "pitcher_gb_rate", "Ground-ball rate", True, "pct1"),
]
# A pitcher prop names the pitcher; everything else about a player is a batter
# prop. Two-way players sit in both pools, so the market decides which one.
_MLB_PITCHER_MARKET_TOKENS = ("pitcher", "strikeout", "outs", "earned run", "hits allowed", "walks allowed")


def _mlb_statcast_path() -> Path | None:
    candidates: list[Path] = []
    override = str(os.environ.get("SYNDICATE_MLB_DATA_ROOT") or "").strip()
    if override:
        candidates.append(Path(override) / "statcast" / "features" / "player_features_latest.json")
    for root in _sport_dirs("mlb"):
        candidates.append(root / "statcast" / "features" / "player_features_latest.json")
    for path in candidates:
        if path.is_file():
            return path
    return None


def _slim_statcast(path: Path) -> dict[str, Any]:
    """Keep only each player's overall season block -- the raw file is ~9 MB."""
    raw = _read_json(path)
    keep = {spec.field for spec in _MLB_BATTER_METRICS + _MLB_PITCHER_METRICS} | {"pitches"}
    out: dict[str, Any] = {"meta": dict(raw.get("meta") or {}), "batters": {}, "pitchers": {}}
    for group in ("batters", "pitchers"):
        for pid, entry in (raw.get(group) or {}).items():
            overall = entry.get("overall") if isinstance(entry, dict) else None
            if isinstance(overall, dict):
                out[group][str(pid)] = {k: overall.get(k) for k in keep}
    return out


def mlb_statcast_index() -> tuple[Path | None, dict[str, Any] | None]:
    path = _mlb_statcast_path()
    if path is None:
        return None, None
    return path, _cached(path, _slim_statcast)


def _mlb_as_of(index: dict[str, Any] | None, path: Path | None) -> _dt.date | None:
    meta = (index or {}).get("meta") or {}
    return _iso_date(meta.get("end_date") or meta.get("generated_at")) or (_mtime_date(path) if path else None)


def mlb_readiness_rows(today: _dt.date) -> list[dict[str, Any]]:
    path, index = mlb_statcast_index()
    exists = bool(index and (index.get("batters") or index.get("pitchers")))
    as_of = _mlb_as_of(index, path)
    return [
        {
            "label": "Statcast season features",
            "metrics": ["xwOBA", "Barrel rate", "Hard-hit rate", "Whiff rate", "CSW rate"],
            "path": str(path) if path else "mlb_source/<statcast/features/player_features_latest.json>",
            "exists": exists,
            "tracked": False,
            "inside_repo": False,
            "required": True,
            "season_input": True,
            "family": "statcast",
            "season_status": season_status("mlb", as_of, today) if exists else "missing",
            "as_of": as_of.isoformat() if as_of else None,
            "season_label": season_label("mlb", today),
            "row_count": len((index or {}).get("batters") or {}) + len((index or {}).get("pitchers") or {}),
        }
    ]


def mlb_player_signals(candidate: dict[str, Any], today: _dt.date) -> list[dict[str, Any]]:
    raw_id = candidate.get("player_id") or candidate.get("pitcher_id") or candidate.get("batter_id")
    try:
        pid = str(int(float(raw_id)))
    except (TypeError, ValueError):
        return []
    path, index = mlb_statcast_index()
    if not index:
        return []
    market = " ".join(str(candidate.get(k) or "") for k in ("market", "market_key", "pick")).lower()
    wants_pitcher = any(token in market for token in _MLB_PITCHER_MARKET_TOKENS)
    order = ("pitchers", "batters") if wants_pitcher else ("batters", "pitchers")
    group = next((g for g in order if pid in (index.get(g) or {})), None)
    if group is None:
        return []
    specs = _MLB_PITCHER_METRICS if group == "pitchers" else _MLB_BATTER_METRICS
    pool = index[group]
    row = pool[pid]
    as_of = _mlb_as_of(index, path)
    status = season_status("mlb", as_of, today)
    name = str(candidate.get("player_name") or candidate.get("entity_name") or "").strip() or pid
    signals = []
    for spec in specs:
        value = _num(row.get(spec.field))
        if value is None:
            continue
        league = [v for v in (_num(r.get(spec.field)) for r in pool.values()) if v is not None]
        ranked = len(league) > 1 and max(league) != min(league)
        signals.append(
            {
                "key": f"mlb_{spec.key}",
                "label": spec.label,
                "kind": "season_metric",
                "family": "statcast",
                "side": "player",
                "is_pick_side": True,
                "team": name,
                "value": round(value, 4),
                "display": _format(value, spec.fmt),
                "rank": _rank(league, value, spec.higher_is_better) if ranked else None,
                "of": len(league) if ranked else None,
                "higher_is_better": spec.higher_is_better,
                "league_mean": round(sum(league) / len(league), 4) if league else None,
                "sample_games": None,
                "sample_pitches": int(_num(row.get("pitches")) or 0) or None,
                "season_status": status,
                "as_of": as_of.isoformat() if as_of else None,
                "source": path.name if path else None,
            }
        )
    return signals


_TABLES_MEMO: dict[tuple[str, str, int], list[Table]] = {}
_TABLES_TTL_SECONDS = 60


def season_tables(sport: str, today: _dt.date) -> list[Table]:
    """Resolved tables for a sport, memoised for a minute.

    The candidate loop calls this once per candidate (hundreds per build);
    without the memo every call re-globs the sport's tree. The parse itself is
    already keyed on (path, mtime, size), so a minute bounds only how late a
    NEW file is noticed, never whether a rewritten one is read.
    """
    import time

    key = (sport.lower(), today.isoformat(), int(time.time() // _TABLES_TTL_SECONDS))
    hit = _TABLES_MEMO.get(key)
    if hit is not None:
        return hit
    if len(_TABLES_MEMO) > 32:
        _TABLES_MEMO.clear()
    tables = _season_tables_uncached(sport, today)
    _TABLES_MEMO[key] = tables
    return tables


def _season_tables_uncached(sport: str, today: _dt.date) -> list[Table]:
    sport = sport.lower()
    if sport in {"nba", "wnba"}:
        return _basketball_tables(sport)
    if sport == "nhl":
        return _nhl_tables(today)
    if sport == "nfl":
        return _nfl_tables()
    if sport == "ncaaf":
        return _ncaaf_tables(today)
    if sport == "soccer":
        return _soccer_player_tables()
    if sport == "ncaab":
        return _ncaab_tables()
    return []


# --------------------------------------------------------------------------- #
# Readiness rows -- the shape `intelligence._advanced_readiness_summary` reads.
# --------------------------------------------------------------------------- #
_FAMILY_METRICS: dict[str, list[str]] = {
    "team_advanced": ["Offensive rating", "Defensive rating", "Net rating", "Pace", "eFG%"],
    "team_xg": ["xGF/60", "xGA/60", "xG share"],
    "team_special_teams": ["PP%", "PK%"],
    "team_rates": ["Shots/60", "Faceoff win%"],
    "team_elo": ["Elo"],
    "team_season_to_date": ["xG share", "Goals/game", "Goals against/game", "PP%", "PK%"],
    "team_epa": ["Offense EPA/play", "Defense EPA/play allowed"],
    "sp_plus": ["SP+ overall", "SP+ offense", "SP+ defense"],
    "team_ratings": ["Adjusted efficiency margin", "Adjusted offense", "Adjusted defense", "Tempo"],
}


def readiness_rows(sport: str, today: _dt.date) -> list[dict[str, Any]]:
    """One row per season table, REQUIRED, with exists and season status measured on the data root.

    ``inside_repo`` is reported for compatibility with the existing row shape;
    it no longer decides whether the row counts.
    """
    if sport == "mlb":
        return mlb_readiness_rows(today)
    rows: list[dict[str, Any]] = []
    for table in season_tables(sport, today):
        exists = table.path is not None and bool(table.rows)
        status = season_status(sport, table.as_of, today) if exists else "missing"
        rows.append(
            {
                "label": table.label,
                "metrics": list(_FAMILY_METRICS.get(table.family.split(":")[0], [])),
                "path": str(table.path) if table.path is not None else f"{sport}_source/<{table.family}>",
                "exists": exists,
                "tracked": False,
                "inside_repo": False,
                "required": True,
                "season_input": True,
                "family": table.family,
                "season_status": status,
                "as_of": table.as_of.isoformat() if table.as_of else None,
                "season_label": season_label(sport, today),
                "row_count": len(table.rows),
            }
        )
    if not rows and sport in _SEASON_OPEN_MONTH_DAY and sport != "mlb":
        rows.append(
            {
                "label": "Season team metrics",
                "metrics": [],
                "path": f"{sport}_source/<season table>",
                "exists": False,
                "tracked": False,
                "inside_repo": False,
                "required": True,
                "season_input": True,
                "family": "season_table",
                "season_status": "missing",
                "as_of": None,
                "season_label": season_label(sport, today),
                "row_count": 0,
            }
        )
    return rows


# --------------------------------------------------------------------------- #
# Per-candidate signals.
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class MetricSpec:
    field: str
    key: str
    label: str
    higher_is_better: bool
    fmt: str  # "num1", "num2", "num3", "pct1", "signed1", "signed2", "int"


_TEAM_METRICS: dict[str, list[MetricSpec]] = {
    "team_advanced": [
        MetricSpec("net_rtg", "net_rtg", "Net rating", True, "signed1"),
        MetricSpec("off_rtg", "off_rtg", "Offensive rating", True, "num1"),
        MetricSpec("def_rtg", "def_rtg", "Defensive rating", False, "num1"),
        MetricSpec("pace", "pace", "Pace", True, "num1"),
        MetricSpec("efg_pct", "efg_pct", "eFG%", True, "pct1"),
        MetricSpec("tov_pct", "tov_pct", "Turnover rate", False, "pct1"),
    ],
    "team_xg": [
        MetricSpec("xg_share", "xg_share", "xG share", True, "pct1"),
        MetricSpec("xgf60", "xgf60", "xGF/60", True, "num2"),
        MetricSpec("xga60", "xga60", "xGA/60", False, "num2"),
    ],
    "team_special_teams": [
        MetricSpec("pp_pct", "pp_pct", "Power play", True, "pct1"),
        MetricSpec("pk_pct", "pk_pct", "Penalty kill", True, "pct1"),
    ],
    "team_rates": [
        MetricSpec("shots_per_60", "shots_per_60", "Shots/60", True, "num1"),
        MetricSpec("faceoff_win_pct", "faceoff_win_pct", "Faceoff win%", True, "pct1"),
    ],
    "team_elo": [MetricSpec("elo", "elo", "Elo", True, "int")],
    "team_season_to_date": [
        MetricSpec("xg_share", "std_xg_share", "xG share", True, "pct1"),
        MetricSpec("gf_pg", "std_gf_pg", "Goals/game", True, "num2"),
        MetricSpec("ga_pg", "std_ga_pg", "Goals against/game", False, "num2"),
        MetricSpec("pp_pct", "std_pp_pct", "Power play", True, "pct1"),
        MetricSpec("pk_pct", "std_pk_pct", "Penalty kill", True, "pct1"),
    ],
    "team_epa": [
        MetricSpec("offense_epa", "offense_epa", "Offense EPA/play", True, "signed3"),
        MetricSpec("defense_epa", "defense_epa", "Defense EPA/play (higher = fewer allowed)", True, "signed3"),
    ],
    "sp_plus": [
        MetricSpec("sp_overall", "sp_overall", "SP+ margin", True, "signed1"),
        MetricSpec("sp_offense", "sp_offense", "SP+ offense", True, "num1"),
        MetricSpec("sp_defense", "sp_defense", "SP+ defense (pts allowed)", False, "num1"),
    ],
    "team_ratings": [
        MetricSpec("adj_em", "adj_em", "Adjusted efficiency margin", True, "signed1"),
        MetricSpec("adj_off", "adj_off", "Adjusted offense", True, "num1"),
        MetricSpec("adj_def", "adj_def", "Adjusted defense", False, "num1"),
        MetricSpec("tempo", "tempo", "Tempo", True, "num1"),
    ],
}

_SOCCER_PLAYER_METRICS = [
    MetricSpec("xg_per90", "xg_per90", "xG/90", True, "num2"),
    MetricSpec("shots_per90", "shots_per90", "Shots/90", True, "num2"),
    MetricSpec("xa_per90", "xa_per90", "xA/90", True, "num2"),
    MetricSpec("goals_per90", "goals_per90", "Goals/90", True, "num2"),
    MetricSpec("minutes", "minutes", "Minutes", True, "int"),
]


def _derived(family: str, row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    if family == "team_advanced":
        off, deff = _num(row.get("off_rtg")), _num(row.get("def_rtg"))
        if off is not None and deff is not None:
            out["net_rtg"] = off - deff
    if family == "team_xg":
        xgf, xga = _num(row.get("xgf60")), _num(row.get("xga60"))
        if xgf is not None and xga is not None and (xgf + xga) > 0:
            out["xg_share"] = xgf / (xgf + xga)
    return out


def _format(value: float, fmt: str) -> str:
    if fmt == "pct1":
        return f"{value * 100.0:.1f}%"
    if fmt == "signed1":
        return f"{value:+.1f}"
    if fmt == "signed2":
        return f"{value:+.2f}"
    if fmt == "signed3":
        return f"{value:+.3f}"
    if fmt == "num2":
        return f"{value:.2f}"
    if fmt == "num3":
        return f"{value:.3f}"
    if fmt == "int":
        return f"{value:.0f}"
    return f"{value:.1f}"


def _ordinal(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _rank(values: list[float], value: float, higher_is_better: bool) -> int:
    ordered = sorted(values, reverse=higher_is_better)
    return ordered.index(value) + 1


def split_matchup(matchup: Any) -> tuple[str, str] | None:
    text = str(matchup or "").strip()
    for sep in (" @ ", " at ", " vs. ", " vs "):
        if sep in text:
            away, home = text.split(sep, 1)
            if away.strip() and home.strip():
                return away.strip(), home.strip()
    return None


def _ncaaf_teams_from_event(event_id: Any, keys: set[str]) -> tuple[str, str] | None:
    """`6_Jacksonville_State_Kennesaw_State` -> ('jacksonville state', 'kennesaw state').

    The id is ``<week>_<Away>_<Home>`` with spaces as underscores, so the split
    point is ambiguous; take the one split where BOTH halves are rated teams.
    """
    parts = [p for p in str(event_id or "").split("_") if p]
    if parts and parts[0].isdigit():
        parts = parts[1:]
    matches = []
    for cut in range(1, len(parts)):
        away = _ncaaf_norm(" ".join(parts[:cut]))
        home = _ncaaf_norm(" ".join(parts[cut:]))
        if away in keys and home in keys:
            matches.append((away, home))
    return matches[0] if len(matches) == 1 else None


def _ncaaf_table_key(name: str, keys: set[str]) -> str | None:
    """A board team name ("Kennesaw State Owls") -> its SP+ key ("kennesaw st"), or None.

    Exact normalised match first, then the CFBD registry via `canonical_team`
    (display name with mascot -> school). Never by dropping trailing words: that
    turns "Texas Southern Tigers" (FCS, unrated) into "texas" -- a confident
    wrong join, measured in this lane's backtest on 2026-10-07.
    """
    direct = _ncaaf_norm(name)
    if direct in keys:
        return direct
    school = _canonical("ncaaf")(name)
    if school:
        key = _ncaaf_norm(school)
        if key in keys:
            return key
    return None


def _resolve_side_keys(sport: str, candidate: dict[str, Any], tables: list[Table]) -> tuple[str | None, str | None, str | None]:
    """(away_key, home_key, pick_key) in each table's key space, or Nones."""
    pair = split_matchup(candidate.get("matchup"))
    pick_raw = str(candidate.get("team") or "").strip()
    if sport == "ncaaf":
        keys: set[str] = set()
        for table in tables:
            keys |= set(table.rows)
        teams = _ncaaf_teams_from_event(candidate.get("event_id"), keys)
        if teams is None and pair is not None:
            away, home = _ncaaf_table_key(pair[0], keys), _ncaaf_table_key(pair[1], keys)
            teams = (away, home) if away and home else None
        if teams is None:
            return None, None, None
        away, home = teams
        pick = None
        if pick_raw and pair is not None:
            if pick_raw == pair[0]:
                pick = away
            elif pick_raw == pair[1]:
                pick = home
        return away, home, pick
    if pair is None:
        return None, None, None
    resolve = _canonical(sport)
    away = resolve(pair[0]) or pair[0].lower()
    home = resolve(pair[1]) or pair[1].lower()
    pick = (resolve(pick_raw) or pick_raw.lower()) if pick_raw and pick_raw not in {"-", "—"} else None
    if pick not in {away, home}:
        pick = None
    return away, home, pick


def _display_team(candidate: dict[str, Any], side: str) -> str:
    pair = split_matchup(candidate.get("matchup"))
    if pair is None:
        return side
    return pair[0] if side == "away" else pair[1]


def _prepared(table: Table) -> tuple[dict[str, dict[str, Any]], dict[str, list[float]]]:
    """Derived rows and each metric's ASCENDING league column, computed once per table.

    The candidate loop asks for the same table thousands of times per build
    (4,706 Layer 2 cards on 2026-10-07); recomputing these per call cost ~18 ms
    a game. Stored on the Table, which itself lives for the 60 s table memo.
    A column with no spread across the league is dropped here: it is a
    placeholder, not a measurement, and ranking it "1st of 30" for every team
    would be a confident-looking lie.
    """
    cached = getattr(table, "_prepared_cache", None)
    if cached is not None:
        return cached
    derived_rows = {key: _derived(table.family, row) for key, row in table.rows.items()}
    columns: dict[str, list[float]] = {}
    for spec in _TEAM_METRICS.get(table.family, []):
        values = sorted(v for v in (_num(r.get(spec.field)) for r in derived_rows.values()) if v is not None)
        if len(values) >= 2 and values[0] != values[-1]:
            columns[spec.field] = values
    cached = (derived_rows, columns)
    object.__setattr__(table, "_prepared_cache", cached)
    return cached


def _sorted_rank(ascending: list[float], value: float, higher_is_better: bool) -> int:
    """1-based league rank against an ascending column (ties share the best rank)."""
    import bisect

    if higher_is_better:
        return len(ascending) - bisect.bisect_right(ascending, value) + 1
    return bisect.bisect_left(ascending, value) + 1


def team_signals(sport: str, candidate: dict[str, Any], today: _dt.date) -> list[dict[str, Any]]:
    sport = sport.lower()
    tables = [t for t in season_tables(sport, today) if t.rows and not t.family.startswith("players:")]
    if not tables:
        return []
    away, home, pick = _resolve_side_keys(sport, candidate, tables)
    if away is None or home is None:
        return []
    signals: list[dict[str, Any]] = []
    for table in tables:
        status = season_status(sport, table.as_of, today)
        derived_rows, columns = _prepared(table)
        for spec in _TEAM_METRICS.get(table.family, []):
            league = columns.get(spec.field)
            if not league:
                continue
            for side, key in (("away", away), ("home", home)):
                row = derived_rows.get(key)
                value = _num(row.get(spec.field)) if row else None
                if value is None:
                    continue
                sample = _num(row.get(table.sample_field)) if (row and table.sample_field) else None
                signals.append(
                    {
                        "key": f"{sport}_{spec.key}",
                        "label": f"{spec.label} {table.metric_suffix}" if table.metric_suffix else spec.label,
                        "kind": "season_metric",
                        "family": table.family,
                        "table_suffix": table.metric_suffix or None,
                        "side": side,
                        "is_pick_side": pick is not None and key == pick,
                        "team": _display_team(candidate, side),
                        "value": round(value, 4),
                        "display": _format(value, spec.fmt),
                        "rank": _sorted_rank(league, value, spec.higher_is_better),
                        "of": len(league),
                        "higher_is_better": spec.higher_is_better,
                        "league_mean": round(sum(league) / len(league), 4),
                        "sample_games": int(sample) if sample is not None else None,
                        "season_status": status,
                        "as_of": table.as_of.isoformat() if table.as_of else None,
                        "source": table.path.name if table.path else None,
                    }
                )
    return signals


def soccer_player_signals(candidate: dict[str, Any], today: _dt.date) -> list[dict[str, Any]]:
    name = str(candidate.get("player_name") or candidate.get("entity_name") or "").strip().lower()
    if not name:
        return []
    league_hint = str(candidate.get("league") or candidate.get("league_key") or "").strip().lower()
    tables = _soccer_player_tables()
    if league_hint:
        tables = sorted(tables, key=lambda t: 0 if t.family == f"players:{league_hint}" else 1)
    for table in tables:
        row = table.rows.get(name)
        if row is None:
            continue
        status = season_status("soccer", table.as_of, today)
        qualified = [r for r in table.rows.values() if (_num(r.get("minutes")) or 0.0) >= 270.0]
        signals = []
        for spec in _SOCCER_PLAYER_METRICS:
            value = _num(row.get(spec.field))
            if value is None:
                continue
            league = [v for v in (_num(r.get(spec.field)) for r in qualified) if v is not None]
            ranked = spec.field != "minutes" and league and (_num(row.get("minutes")) or 0.0) >= 270.0
            signals.append(
                {
                    "key": f"soccer_{spec.key}",
                    "label": spec.label,
                    "kind": "season_metric",
                    "family": table.family,
                    "side": "player",
                    "is_pick_side": True,
                    # The sentence names its subject from this field: the
                    # player, with the club for disambiguation.
                    "team": f"{row.get('player_name') or name} ({row.get('team')})" if row.get("team") else (row.get("player_name") or name),
                    "club": row.get("team"),
                    "value": round(value, 4),
                    "display": _format(value, spec.fmt),
                    "rank": _rank(league + ([value] if value not in league else []), value, spec.higher_is_better) if ranked else None,
                    "of": len(league) if ranked else None,
                    "higher_is_better": spec.higher_is_better,
                    "league_mean": round(sum(league) / len(league), 4) if league else None,
                    "sample_games": int(_num(row.get("games")) or 0) or None,
                    "season_status": status,
                    "as_of": table.as_of.isoformat() if table.as_of else None,
                    "source": table.path.name if table.path else None,
                }
            )
        return signals
    return []


def candidate_season_signals(candidate: dict[str, Any], today: _dt.date) -> list[dict[str, Any]]:
    """All season-metric signals for one candidate. Never raises."""
    sport = str(candidate.get("sport_slug") or candidate.get("sport") or "").strip().lower()
    if sport not in _SEASON_OPEN_MONTH_DAY:
        return []
    try:
        if sport == "soccer":
            return soccer_player_signals(candidate, today)
        if sport == "mlb":
            return mlb_player_signals(candidate, today)
        return team_signals(sport, candidate, today)
    except Exception as exc:
        print(f"[intelligence_season] SIGNALS_FAILED sport={sport} error={type(exc).__name__}: {exc}", flush=True)
        return []


_STATUS_NOTE = {
    "prior_season": "last season's numbers -- this season's table has not been rebuilt",
    "prior_season_expected": "last season's numbers -- the new season has not started",
}


def season_evidence_text(signals: list[dict[str, Any]], *, limit_metrics: int = 3) -> str:
    """One sentence of real numbers for the explanation, e.g.

    ``Season metrics: Net rating MIN +4.1 (7th of 30) vs IND -1.2 (19th); Pace MIN 99.1 (22nd) vs IND 101.3 (9th).``
    """
    if not signals:
        return ""
    by_key: dict[str, dict[str, dict[str, Any]]] = {}
    order: list[str] = []
    family_of: dict[str, str] = {}
    for signal in signals:
        key = str(signal.get("key"))
        if key not in by_key:
            by_key[key] = {}
            order.append(key)
            family_of[key] = str(signal.get("family") or "")
        by_key[key][str(signal.get("side"))] = signal
    # One metric from each table before a second from any: with several tables
    # (NHL: in-season blend, this season, last season) the head metric of each is
    # what the sentence is for. Stable within a table.
    seen_in: dict[str, int] = {}
    position: dict[str, int] = {}
    for key in order:
        family = family_of[key]
        position[key] = seen_in.get(family, 0)
        seen_in[family] = position[key] + 1
    # Current-season tables before last season's, so a stale table never crowds
    # out a current one at the metric limit.
    def _is_prior(key: str) -> bool:
        return str(next(iter(by_key[key].values())).get("season_status")) in _STATUS_NOTE

    order = sorted(order, key=lambda k: (_is_prior(k), position[k]))
    shown_status = {_is_prior(k) for k in order[:limit_metrics]}
    mixed = shown_status == {True, False}
    fragments: list[str] = []
    statuses: set[str] = set()
    for key in order[:limit_metrics]:
        sides = by_key[key]
        first = next(iter(sides.values()))
        statuses.add(str(first.get("season_status")))

        def one(signal: dict[str, Any]) -> str:
            rank = signal.get("rank")
            rank_text = f" ({_ordinal(int(rank))} of {signal.get('of')})" if rank else ""
            return f"{signal.get('team')} {signal.get('display')}{rank_text}"

        label = str(first.get("label"))
        if mixed and _is_prior(key):
            label += " (last season)"  # mixed sentence: tag the stale fragment, not the whole sentence
        if "player" in sides:
            fragments.append(f"{label} {one(sides['player'])}")
        elif "away" in sides and "home" in sides:
            fragments.append(f"{label} {one(sides['away'])} vs {one(sides['home'])}")
        else:
            fragments.append(f"{label} {one(first)}")
    shown = [s for key in order[:limit_metrics] for s in by_key[key].values()]
    games = sorted({int(s["sample_games"]) for s in shown if s.get("sample_games")})
    sample = f", {games[0]}-{games[-1]} games" if len(games) > 1 else (f", {games[0]} games" if games else "")
    sampled_suffixes = {s.get("table_suffix") for s in shown if s.get("sample_games")}
    if sample and sampled_suffixes == {"this season"}:
        sample = sample.replace(", ", ", this season ", 1)
    pitches = [int(s["sample_pitches"]) for s in shown if s.get("sample_pitches")]
    if pitches and not sample:
        sample = f", {pitches[0]:,} pitches"
    caveat = "" if mixed else "; ".join(_STATUS_NOTE[s] for s in sorted(statuses) if s in _STATUS_NOTE)
    head = f"Season metrics{sample}"
    if caveat:
        head += f" ({caveat})"
    return f"{head}: " + "; ".join(fragments) + "."
