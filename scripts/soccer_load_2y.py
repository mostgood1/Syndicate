"""Load the 2-year FotMob research cache, from the gz if the raw json is absent.

RETENTION CONTRACT. The raw json is 46MB and gitignored; the gzip is 4.7MB and
COMMITTED. Analysis code should call `load_2y()` rather than opening a path, so
a fresh checkout works with no harvest step -- the 5,552-match sample took ~15
minutes and ~8k HTTP calls against someone else's API, and nothing should have
to repeat that to re-run an analysis.
"""

from __future__ import annotations

import gzip
import json
from pathlib import Path

_RAW = Path("reports/soccer_backtest/fotmob_2y.json")
_GZ = Path("reports/soccer_backtest/fotmob_2y.json.gz")


def load_2y() -> dict:
    if _RAW.exists():
        return json.loads(_RAW.read_text(encoding="utf-8"))
    if _GZ.exists():
        with gzip.open(_GZ, "rt", encoding="utf-8") as handle:
            return json.load(handle)
    raise FileNotFoundError(
        "neither %s nor %s present -- run scripts/soccer_fotmob_harvest_2y.py" % (_RAW, _GZ))


__all__ = ["load_2y"]
