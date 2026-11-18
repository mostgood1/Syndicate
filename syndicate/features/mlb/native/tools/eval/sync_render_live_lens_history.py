"""COMPATIBILITY SHIM: this tool is `eval/sync_fleet_live_lens_history.py` now.

Renamed 2026-11-17 (lane mlb-native-fleet-names, todo #766 follow-up). It has synced from the
fleet (`http://127.0.0.1:10000`) since lane render-retirement `193df776e`; the Render name was
all that was left. Ledger entries name this file, so the name keeps working:

    python .../eval/sync_render_live_lens_history.py ...   # same arguments, same output
    from ...eval.sync_render_live_lens_history import sync_render_live_lens_history

The old function names resolve to the renamed ones, and every other attribute is the new
module's. New code imports `sync_fleet_live_lens_history`.
"""

from __future__ import annotations

import sys
from pathlib import Path

_SYNDICATE_ROOT = str(Path(__file__).resolve().parents[6])
if _SYNDICATE_ROOT not in sys.path:
    sys.path.insert(0, _SYNDICATE_ROOT)

from syndicate.features.mlb.native.tools.eval import sync_fleet_live_lens_history as _impl  # noqa: E402

# Old name -> new name, for `from <this shim> import <old name>`.
_RENAMED = {
    "sync_render_live_lens_history": "sync_fleet_live_lens_history",
    "_infer_render_base_url": "_infer_fleet_base_url",
}


def __getattr__(name: str):
    return getattr(_impl, _RENAMED.get(name, name))


if __name__ == "__main__":
    raise SystemExit(_impl.main())
