from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional

from .disk_cache import DiskCache
from ..models import PitchType


@dataclass(frozen=True)
class PitcherPitchSplits:
    pitcher_id: int
    season: int
    n_pitches: int
    pitch_mix: Dict[PitchType, float]
    whiff_mult: Dict[PitchType, float]
    inplay_mult: Dict[PitchType, float]
    source: str = "statcast_cache"
    start_date: str = ""
    end_date: str = ""


# Canonical mapping lives in pitch_codes.py -- ONE map for the engine. The
# local table here knew nothing of the sweeper (8.20% of 2026 pitches), which
# fell through to OTHER and a 1.00 whiff multiplier.
from .pitch_codes import canon_pitch_type as _canon


def _canon_pitch_type(code: str) -> PitchType:
    """Statcast code -> canonical PitchType. Non-pitches fall back to OTHER
    here, because this module's callers key dicts by the result and cannot
    represent 'drop it'."""
    return _canon(code) or PitchType.OTHER


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, float(x)))


def default_statcast_cache(ttl_seconds: int = 7 * 24 * 3600, cache_dir: str | None = None) -> DiskCache:
    root = Path(cache_dir) if cache_dir else (Path(__file__).resolve().parents[2] / "data" / "cache" / "statcast")
    return DiskCache(root_dir=root, default_ttl_seconds=ttl_seconds)


_ARTIFACT_CACHE: Dict[int, Optional[Dict[str, dict]]] = {}
_ARTIFACT_REL = "mlb_source/source_artifacts/data/pitch_splits"


def _artifact_root() -> Path:
    """Mounted disk on Render, repo `data/` locally.

    Same `SYNDICATE_DATA_ROOT` contract as `refresh_state_store.data_root()`,
    read via env so this module keeps no dependency on the syndicate package.
    """
    import os
    override = str(os.environ.get("SYNDICATE_DATA_ROOT") or "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return Path(__file__).resolve().parents[4] / "data"


def _load_artifact(season: int) -> Optional[Dict[str, dict]]:
    """Whole-season pitch splits, loaded once per season and memoised.

    Returns None when absent -- callers then fall back to the DiskCache, and a
    miss on both leaves the multipliers empty (1.0), which is the pre-`#440`
    behaviour and is therefore a safe default rather than a silent change.
    """
    if season in _ARTIFACT_CACHE:
        return _ARTIFACT_CACHE[season]
    out: Optional[Dict[str, dict]] = None
    try:
        path = _artifact_root() / _ARTIFACT_REL / f"pitch_splits_{int(season)}.json"
        if path.is_file():
            import json as _json
            payload = _json.loads(path.read_text(encoding="utf-8"))
            pitchers = payload.get("pitchers")
            if isinstance(pitchers, dict) and pitchers:
                out = pitchers
    except Exception:
        out = None
    _ARTIFACT_CACHE[season] = out
    return out


def _splits_from_artifact(pitcher_id: int, season: int) -> Optional["PitcherPitchSplits"]:
    pitchers = _load_artifact(season)
    if not pitchers:
        return None
    entry = pitchers.get(str(int(pitcher_id)))
    if not isinstance(entry, dict) or not entry.get("n_pitches"):
        return None
    try:
        return PitcherPitchSplits(
            pitcher_id=int(pitcher_id),
            season=int(season),
            n_pitches=int(entry["n_pitches"]),
            pitch_mix={_canon_pt(k): float(v) for k, v in (entry.get("pitch_mix") or {}).items()},
            whiff_mult={_canon_pt(k): float(v) for k, v in (entry.get("whiff_mult") or {}).items()},
            inplay_mult={_canon_pt(k): float(v) for k, v in (entry.get("inplay_mult") or {}).items()},
            source=str(entry.get("source") or "artifact"),
            start_date=str(entry.get("start_date") or ""),
            end_date=str(entry.get("end_date") or ""),
        )
    except Exception:
        return None


def _canon_pt(code: str) -> PitchType:
    return _canon_pitch_type(code)


def fetch_pitcher_pitch_splits(
    cache: DiskCache,
    pitcher_id: int,
    season: int,
    ttl_seconds: Optional[int] = None,
) -> Optional[PitcherPitchSplits]:
    """Load cached Statcast-derived pitch splits.

    This function is intentionally *cache-only* so the simulator can run in
    Windows ARM64 environments without `pybaseball` (which pulls `cryptography`).

    Populate the cache using the x64 fetch tool:
    - tools/statcast/fetch_pitcher_pitch_splits_x64.py
    """
    if pitcher_id <= 0:
        return None

    # ARTIFACT FIRST, cache second. `#440`.
    #
    # The DiskCache lives at `vendor/mlb_bettingv2/data/cache/statcast`, which on
    # Render is inside the EPHEMERAL REPO CHECKOUT and is gitignored -- so it can
    # never ship with a deploy and anything written there is discarded by the
    # next one. That is the `#389` failure shape exactly. A worker therefore
    # always missed, `fetch_pitcher_pitch_splits` always returned None, and every
    # pitch-type multiplier silently resolved to 1.0.
    #
    # The artifact is a plain document on the MOUNTED DISK, keyed by pitcher id,
    # publishable through `artifact_publisher` and inspectable through
    # `/api/ops/artifacts/*`. The cache remains as a local-development fallback.
    from_artifact = _splits_from_artifact(pitcher_id, season)
    if from_artifact is not None:
        return from_artifact

    cache_key = {"pitcher_id": int(pitcher_id), "season": int(season)}
    hit = cache.get("pitcher_pitch_splits", cache_key, ttl_seconds=ttl_seconds)
    if isinstance(hit, dict) and hit.get("n_pitches"):
        try:
            return PitcherPitchSplits(
                pitcher_id=int(hit["pitcher_id"]),
                season=int(hit["season"]),
                n_pitches=int(hit["n_pitches"]),
                pitch_mix={PitchType(k): float(v) for k, v in (hit.get("pitch_mix") or {}).items()},
                whiff_mult={PitchType(k): float(v) for k, v in (hit.get("whiff_mult") or {}).items()},
                inplay_mult={PitchType(k): float(v) for k, v in (hit.get("inplay_mult") or {}).items()},
                source=str(hit.get("source") or "statcast_cache"),
                start_date=str(hit.get("start_date") or ""),
                end_date=str(hit.get("end_date") or ""),
            )
        except Exception:
            pass
    return None


def normalize_pitch_mix(mix: Dict[PitchType, float], min_share: float = 0.02) -> Dict[PitchType, float]:
    """Drop tiny categories and re-normalize to sum to ~1.0."""
    filtered = {k: float(v) for k, v in (mix or {}).items() if float(v) >= float(min_share)}
    s = sum(max(0.0, float(v)) for v in filtered.values())
    if s <= 0:
        return {}
    return {k: float(v) / s for k, v in filtered.items()}
