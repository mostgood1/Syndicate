"""Feed `statcast_quality_mult` from the QUALITY artifact. `#440`.

CONTRACT (settled 2026-08-18, documented on both profiles in models.py):
the field is a UNION bag, PARTIAL BY DESIGN. Consumers guard every read and
`_rate_ratio_mult` returns 1.0 for anything missing or non-numeric, so a subset
is legal.

**RAW METRICS ONLY.** `k`/`bb`/`hr`/`inplay` are DERIVED by
`simulate.py:_statcast_shape_rate_mults`; writing them here as well would let the
lookahead term add pressure from a value the shape function has separately
applied. That is double-counting -- the failure measured 2026-08-17 (two
mechanisms, interaction -0.00331, negative in 4 of 4).

Currently supplied: xwoba, ev_mean, ev_max.
Absent and deliberately NOT guessed: chase_swing_rate, zone_rate, csw_rate,
contact_rate, pulled_air_rate, pitch_velo_mean, pitch_extension_mean.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

_CACHE: Dict[int, Optional[dict]] = {}
_REL = "mlb_source/source_artifacts/data/quality"

# k/bb/hr/inplay are derived downstream; if one ever appears in the artifact it
# is a producer bug and must not reach a profile.
_FORBIDDEN = {"k", "bb", "hr", "inplay"}

# Range guards. A first draft of the producer fed PERCENTILE RANKS (1..100) as if
# they were metric values -- xwoba 1.0, ev_mean 26.0 -- and nothing errored.
# These bounds are the check that caught it, so they live on the read side too.
_BOUNDS = {"xwoba": (0.10, 0.60), "ev_mean": (60.0, 105.0), "ev_max": (80.0, 130.0),
           "contact_rate": (0.30, 1.0), "chase_swing_rate": (0.05, 0.70),
           "zone_rate": (0.20, 0.80), "csw_rate": (0.10, 0.50),
           "pulled_air_rate": (0.0, 1.0)}


def _root() -> Path:
    o = str(os.environ.get("SYNDICATE_DATA_ROOT") or "").strip()
    if o:
        return Path(o).expanduser().resolve()
    return Path(__file__).resolve().parents[4] / "data"


def load_quality(season: int) -> Optional[dict]:
    if season in _CACHE:
        return _CACHE[season]
    out = None
    try:
        p = _root() / _REL / f"quality_{int(season)}.json"
        if p.is_file():
            payload = json.loads(p.read_text(encoding="utf-8"))
            if payload.get("batters") or payload.get("pitchers"):
                out = payload
    except Exception:
        out = None
    _CACHE[season] = out
    return out


def apply_quality(prof: Any, *, season: int, side: str) -> bool:
    """Merge raw statcast metrics onto `prof.statcast_quality_mult`.

    `side` is "batters" or "pitchers". Returns True when anything was set.
    Out-of-range and forbidden keys are DROPPED rather than clamped: a value
    outside its physical range means the producer fed the wrong quantity, and
    silently rescaling it would hide that.
    """
    art = load_quality(season)
    if not art:
        return False
    pid = int(getattr(getattr(prof, "player", None), "mlbam_id", 0) or 0)
    entry = (art.get(side) or {}).get(str(pid))
    if not isinstance(entry, dict) or not entry:
        return False
    clean: Dict[str, float] = {}
    for k, v in entry.items():
        if k in _FORBIDDEN or not isinstance(v, (int, float)):
            continue
        lo_hi = _BOUNDS.get(k)
        if lo_hi and not (lo_hi[0] <= float(v) <= lo_hi[1]):
            continue
        clean[k] = float(v)
    if not clean:
        return False
    try:
        existing = getattr(prof, "statcast_quality_mult", None)
        merged = dict(existing) if isinstance(existing, dict) else {}
        merged.update(clean)
        prof.statcast_quality_mult = merged
        return True
    except Exception:
        return False


__all__ = ["apply_quality", "load_quality"]
