"""NFL historical data loader for the SmartSim 2.0 truth layer.

Acquisition strategy:

1. Preferred: ``nfl_data_py`` (``import_pbp_data``), the integration already
   proven in the NFL-Betting workspace.
2. Fallback: download the identical nflverse release assets directly
   (``play_by_play_<season>.csv.gz``). ``nfl_data_py`` is a thin wrapper over
   these same files, so both paths produce the same data. The fallback exists
   because this workstation (Windows ARM64, pandas 3.x) cannot install
   ``nfl_data_py``'s pinned dependency set.

All downloads are cached under the Syndicate NFL source mirror so repeated
snapshot builds are offline and replayable.
"""

from __future__ import annotations

import urllib.request
from pathlib import Path
from typing import Iterable
from typing import Sequence

import pandas as pd

DEFAULT_CACHE_DIR = Path(__file__).resolve().parents[6] / "data" / "nfl_source" / "historical_truth"

NFLVERSE_PBP_URL_TEMPLATE = "https://github.com/nflverse/nflverse-data/releases/download/pbp/play_by_play_{season}.csv.gz"

# Column subset required by the snapshot builder; keeps three seasons of PBP
# comfortably in memory without pyarrow.
DEFAULT_PBP_COLUMNS: tuple[str, ...] = (
    "play_id",
    "game_id",
    "season",
    "week",
    "season_type",
    "home_team",
    "away_team",
    "posteam",
    "defteam",
    "qtr",
    "down",
    "ydstogo",
    "yardline_100",
    "yards_gained",
    "play",
    "fixed_drive",
    "fixed_drive_result",
    "drive_play_count",
    "drive_time_of_possession",
    "posteam_score",
    "posteam_score_post",
    "total_home_score",
    "total_away_score",
)


def _cache_path(season: int, cache_dir: Path) -> Path:
    return cache_dir / f"play_by_play_{season}.csv.gz"


def _download_nflverse_release(season: int, destination: Path) -> None:
    url = NFLVERSE_PBP_URL_TEMPLATE.format(season=season)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".part")
    request = urllib.request.Request(url, headers={"User-Agent": "syndicate-smartsim2-truth-layer"})
    with urllib.request.urlopen(request, timeout=300) as response, temporary.open("wb") as handle:
        while True:
            chunk = response.read(1 << 20)
            if not chunk:
                break
            handle.write(chunk)
    temporary.replace(destination)


def _load_season_via_nfl_data_py(season: int) -> pd.DataFrame | None:
    try:
        import nfl_data_py as nfl  # type: ignore
    except Exception:  # noqa: BLE001 - optional dependency
        return None
    try:
        frame = nfl.import_pbp_data([season], downcast=False, cache=False)
    except Exception:  # noqa: BLE001 - fall back to direct release download
        return None
    return frame


def ensure_pbp_cached(season: int, *, cache_dir: Path = DEFAULT_CACHE_DIR) -> Path:
    """Ensure the season's play-by-play file exists locally and return its path."""
    path = _cache_path(season, cache_dir)
    if path.exists():
        return path
    frame = _load_season_via_nfl_data_py(season)
    if frame is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        frame.to_csv(path, index=False, compression="gzip")
        return path
    _download_nflverse_release(season, path)
    return path


def load_pbp_season(
    season: int,
    *,
    cache_dir: Path = DEFAULT_CACHE_DIR,
    columns: Sequence[str] = DEFAULT_PBP_COLUMNS,
) -> pd.DataFrame:
    path = ensure_pbp_cached(season, cache_dir=cache_dir)
    wanted = set(columns)
    frame = pd.read_csv(
        path,
        compression="gzip",
        usecols=lambda name: name in wanted,
        low_memory=False,
    )
    if "season" not in frame.columns:
        frame["season"] = season
    return frame


def load_pbp_seasons(
    seasons: Iterable[int],
    *,
    cache_dir: Path = DEFAULT_CACHE_DIR,
    columns: Sequence[str] = DEFAULT_PBP_COLUMNS,
) -> pd.DataFrame:
    """Load play-by-play for the requested seasons (drives and game summaries derive from it)."""
    frames = [load_pbp_season(season, cache_dir=cache_dir, columns=columns) for season in seasons]
    if not frames:
        return pd.DataFrame(columns=list(columns))
    return pd.concat(frames, ignore_index=True)


__all__ = [
    "DEFAULT_CACHE_DIR",
    "DEFAULT_PBP_COLUMNS",
    "NFLVERSE_PBP_URL_TEMPLATE",
    "ensure_pbp_cached",
    "load_pbp_season",
    "load_pbp_seasons",
]
