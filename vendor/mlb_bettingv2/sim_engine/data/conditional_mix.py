"""Apply the CONDITIONAL PITCH MIX artifact to a pitcher profile. `#440`.

The engine drew pitch type from ONE season-long vector (`PitcherProfile.arsenal`)
at `simulate.py:1066` and `:2803` -- unconditional on count and on batter
handedness. Measured on 1,472,453 statcast pitches, real 3-0 counts are 94.5%
fastball against a 55.2% season mix, and lefty-on-lefty the changeup collapses
from 14.1% to 3.8%. The engine threw the season mix in both.

**The conditioning is majority PER-PITCHER, which is why this is not a league
constant.** Tilting each pitcher's season vector by the league count shift -- the
best a single global rule can do -- removes only 14-45% of the per-pitcher
deviation. 55-86% is irreducible. That distinguishes it from the first-pitch take
term (`d8bf0b04`), which WAS a league constant and came back market-neutral.

This module only LOADS and ATTACHES. The consumption is in `simulate.py`, which
falls back to `arsenal` for any pitcher, bucket or hand not covered -- so a
missing artifact degrades to exactly today's behaviour rather than to an empty
mix.

Keys are `"<bucket>|<hand>"` where bucket is a `|`-joined set of counts, e.g.
`"0-2|1-2|2-2|R"`. The count->bucket map travels WITH the artifact rather than
being hardcoded here: the buckets were cut by measured TVD and will move if the
builder is re-run on another season.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

_CACHE: Dict[int, Optional[dict]] = {}
_REL = "mlb_source/source_artifacts/data/conditional_mix"


def _root() -> Path:
    override = str(os.environ.get("SYNDICATE_DATA_ROOT") or "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return Path(__file__).resolve().parents[4] / "data"


def load_conditional_mix(season: int) -> Optional[dict]:
    """Whole-season conditional-mix artifact, memoised. None when absent."""
    if season in _CACHE:
        return _CACHE[season]
    out = None
    try:
        p = _root() / _REL / f"conditional_mix_{int(season)}.json"
        if p.is_file():
            payload = json.loads(p.read_text(encoding="utf-8"))
            if payload.get("pitchers") and payload.get("count_to_bucket"):
                out = payload
    except Exception:
        out = None
    _CACHE[season] = out
    return out


def apply_conditional_mix_to_pitcher(prof: Any, *, season: int) -> bool:
    """Attach this pitcher's count x hand mixes. False when he is not covered.

    Pitch-type codes are canonicalised through `pitch_codes`, and a canonical
    collision (ST and SL both become SL) SUMS rather than overwrites -- these are
    probabilities of throwing a pitch, so the mass of a slider and a sweeper adds.
    That differs from `arsenal.py`, where the values are multipliers and the
    correct merge is a usage-weighted mean.
    """
    from .pitch_codes import canon_pitch_type

    art = load_conditional_mix(season)
    if not art:
        return False
    pid = int(getattr(getattr(prof, "player", None), "mlbam_id", 0) or 0)
    if pid <= 0:
        return False
    entry = (art.get("pitchers") or {}).get(str(pid))
    if not isinstance(entry, dict) or not entry:
        return False

    cells: Dict[str, Dict[Any, float]] = {}
    for cell_key, mix in entry.items():
        if not isinstance(mix, dict):
            continue
        acc: Dict[Any, float] = {}
        for code, prob in mix.items():
            pt = canon_pitch_type(code)
            if pt is None or not isinstance(prob, (int, float)):
                continue
            acc[pt] = acc.get(pt, 0.0) + float(prob)
        total = sum(acc.values())
        if total > 0:
            cells[str(cell_key)] = {k: v / total for k, v in acc.items()}
    if not cells:
        return False

    try:
        prof.conditional_arsenal = cells
        prof.count_bucket_map = dict(art.get("count_to_bucket") or {})
        prof.conditional_arsenal_source = "statcast_conditional_mix"
        return True
    except Exception:
        return False


__all__ = ["apply_conditional_mix_to_pitcher", "load_conditional_mix"]
