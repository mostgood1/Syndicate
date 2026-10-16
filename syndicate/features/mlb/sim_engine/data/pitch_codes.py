"""ONE canonical Statcast-code -> PitchType map for the whole engine. `#440`.

**Why this module exists.** Three independent mappings existed
(`statsapi.canon`, `statcast_pitch_splits._SC_TO_CANON`, `arsenal._pt`) and
**none of them knew what a sweeper is.** Measured on the 2026 corpus,
994,643 pitches:

    ST (sweeper)   81,586   8.20%   -> PitchType.OTHER, or dropped outright
    SV (slurve)     4,475   0.45%   -> PitchType.OTHER, or dropped outright

Two different silent failures came out of that:

  * `arsenal._pt` does `PitchType(code)` and returns None on failure, so the
    sweeper ROW WAS DISCARDED -- a sweeper-first pitcher's whiff/in-play/HR
    multipliers for his primary breaking ball never reached the sim at all;
  * where it did survive as `OTHER`, `pitch_model.py:243` gives OTHER a **1.00**
    whiff multiplier against SL's **1.12**. The highest-whiff breaking ball in
    baseball was being modelled as an average pitch.

A sweeper IS a slider (Statcast split it out of SL in 2023; it is a horizontal
slider variant, and every pitcher who throws one has it classified as his
slider by every source predating the split). `SV` is Statcast's slurve, also a
slider variant. Both map to SL.

**`OTHER` is now only genuinely-other**: eephus, pitchouts, unknown. Codes that
are not pitches to model (`PO` pitchout, `UN` unknown, blank) return None and
callers drop them -- distinct from OTHER, which is a real pitch of an odd kind.

Do not add a fourth mapping. Import from here.
"""

from __future__ import annotations

from typing import Dict, Optional

from ..models import PitchType

# Real pitches, canonicalised. Kept deliberately conservative: entries that
# already existed elsewhere keep their incumbent target (FO -> CH, CS -> CU) so
# this module is a UNION of what was there plus the missing breaking balls, not
# a re-classification of things that already worked.
_CANON: Dict[str, PitchType] = {
    "FF": PitchType.FF,
    "FA": PitchType.FF,     # generic "fastball"
    "FT": PitchType.SI,     # two-seam, retired code
    "SI": PitchType.SI,
    "FC": PitchType.FC,
    "SL": PitchType.SL,
    "ST": PitchType.SL,     # sweeper  -- 8.20% of pitches, previously OTHER
    "SV": PitchType.SL,     # slurve   -- 0.45% of pitches, previously OTHER
    "CU": PitchType.CU,
    "CS": PitchType.CU,     # slow curve
    "KC": PitchType.KC,
    "CH": PitchType.CH,
    "FO": PitchType.CH,     # forkball; incumbent choice, preserved
    "FS": PitchType.FS,
    "KN": PitchType.KN,
    "SC": PitchType.OTHER,  # screwball, 16 pitches in 2026
    "EP": PitchType.OTHER,  # eephus
}

# Not pitches to model. Distinct from OTHER: these are dropped, not bucketed.
_NOT_A_PITCH = frozenset({"PO", "UN", "IN", "AB", ""})


def canon_pitch_type(code: str) -> Optional[PitchType]:
    """Canonical PitchType, or **None** when the code is not a pitch to model.

    None and `PitchType.OTHER` mean different things and callers must not
    conflate them: OTHER is a real pitch of an unusual kind and belongs in a
    mix; None is a pitchout or a parse failure and belongs nowhere.
    """
    c = (code or "").strip().upper()
    if c in _NOT_A_PITCH:
        return None
    return _CANON.get(c, PitchType.OTHER)


__all__ = ["canon_pitch_type"]
