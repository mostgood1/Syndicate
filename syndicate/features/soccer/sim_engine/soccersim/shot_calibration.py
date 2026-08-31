"""The soccer shot-mean shrinkage divisor, read from a re-fittable artifact.

WHY A DIVISOR EXISTS AT ALL. Measured 2026-08-31 against production: the shots
model over-predicts by **1.398x** on n=9,840 (player, match) pairs over 247
matches and 9 leagues, joining the archived `expected_shots` predictions to ESPN
shot events. Raw predictions barely beat predicting the average (MAE 0.6251 vs
0.6278). Divided, they beat it by 11.6% (0.5551). The per-player ORDERING was
always informative; the LEVEL was eating nearly all of the value.

WHY A DIVISOR AND NOT A REGRESSION. Pre-registered before the held-out numbers
were seen, and the expectation was WRONG: an affine fit `a + b*x` loses to a
plain divisor on held-out data, in all 9 leagues and all 4 date splits tried.
The bottom deciles genuinely under-predict, but they predict 0.00-0.22 shots, so
they carry almost none of the absolute error. A miscalibration can be real and
still not be worth correcting for.

WHY AN ARTIFACT AND NOT A CONSTANT. The fitted value DRIFTS with the training
window -- 1.244 / 1.314 / 1.333 / 1.438 across the splits tried -- so it is not
a fixed property of the engine. Hard-coding it would bake in one month's
estimate and go stale silently. `scripts/fit_soccer_shot_shrinkage.py --apply`
re-fits and rewrites this artifact; the engine picks the new value up on its
next build with no deploy.

ABSENT MEANS 1.0, WHICH IS EXACTLY TODAY'S BEHAVIOUR. This repo's standing rule
is that an unknown must not default permissive -- here the permissive direction
is APPLYING an unvalidated correction to a live money path, so the safe default
is the identity. A missing, unreadable, malformed or out-of-range artifact
yields 1.0 and the engine behaves precisely as it did before this module existed.

CLAMPED TO [1.0, 2.0]. A corrupt fit must not be able to zero the board or
invert the correction. The measured range across every split is 1.24-1.44, so
the clamp is wide enough to be inert on any plausible re-fit and narrow enough
that a garbage value cannot ship.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

__all__ = [
    "DEFAULT_DIVISOR",
    "MIN_DIVISOR",
    "MAX_DIVISOR",
    "shot_shrinkage_path",
    "load_shot_shrinkage",
    "shot_shrinkage_divisor",
]

DEFAULT_DIVISOR = 1.0
MIN_DIVISOR = 1.0
MAX_DIVISOR = 2.0


def _calibration_dir() -> Path:
    """Where the fitted divisor lives.

    Resolved through `SYNDICATE_DATA_ROOT` -- the MOUNTED DISK on Render -- and
    never relative to the source tree, which is the ephemeral checkout and is
    destroyed by the next deploy. Allowlisted in
    `artifact_publisher.HOT_ARTIFACT_PATTERNS` so it can be published to the
    worker and audited through `/api/ops/artifacts/*`; without that it could not
    be read on Render at all.
    """
    root = str(os.environ.get("SYNDICATE_DATA_ROOT") or "").strip()
    base = Path(root) if root else Path(__file__).resolve().parents[5] / "data"
    return base / "soccer_source" / "calibration"


def shot_shrinkage_path() -> Path | None:
    """The NEWEST dated calibration file, or None.

    DATE-SUFFIXED ON PURPOSE, and this is the whole reason the file is named
    the way it is. The worker does not receive pushes -- it PULLS from web via
    `pull_hot_artifacts`, and that per-cycle pull is scoped to
    `?pattern=*<today>*` because an unfiltered pull reproducibly hit Render's
    proxy timeout. **A file with no date in its name can never be reached by
    it.** `run_refresh_worker` records exactly this for `schedule_2026.json`.

    The boot seeder is not an alternative: it copies only into a subdirectory
    with NONE matching yet, so it can seed a first value and can never deliver
    a re-fit. A monthly re-fit writes a NEW dated file, which the pull picks up
    on the day it is written; older ones stay on disk and are ignored here.
    """
    directory = _calibration_dir()
    try:
        dated = sorted(directory.glob("shot_shrinkage_*.json"))
    except Exception:
        return None
    return dated[-1] if dated else None


def load_shot_shrinkage() -> dict[str, Any]:
    """The whole artifact, or `{}`. Never raises."""
    path = shot_shrinkage_path()
    if path is None:
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def shot_shrinkage_divisor(*, log=None) -> float:
    """The divisor to apply to a player's expected shots. 1.0 when unknown.

    Every failure path returns the identity, so this can never be the reason a
    board loses its shot props.
    """
    payload = load_shot_shrinkage()
    if not payload:
        return DEFAULT_DIVISOR
    raw = payload.get("divisor")
    try:
        value = float(raw)
    except (TypeError, ValueError):
        if log:
            log("[shot_calibration] UNREADABLE divisor=%r -- using 1.0" % (raw,))
        return DEFAULT_DIVISOR
    if not (value == value) or value in (float("inf"), float("-inf")):  # NaN/inf
        return DEFAULT_DIVISOR
    if value < MIN_DIVISOR or value > MAX_DIVISOR:
        if log:
            log("[shot_calibration] OUT OF RANGE divisor=%s not in [%s, %s] -- using 1.0"
                % (value, MIN_DIVISOR, MAX_DIVISOR))
        return DEFAULT_DIVISOR
    return value
