"""Exit vs hold-to-settle: the readout for the paper exit path.

Read-only. Run it where the execution ledger lives (the fleet, with its env):

    python scripts/exit_counterfactual_report.py            # summary JSON
    python scripts/exit_counterfactual_report.py --exits    # plus every exit row

Grades every recorded exit (`execution_exits.json`) against the entry's own
settled outcome, and replays each watched position's best net bid against a grid
of take-profit margins. See `execution_exits.exit_counterfactual` for what is and
is not counted.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--exits", action="store_true", help="include every exit row")
    args = parser.parse_args(argv)

    from syndicate.features.shared.execution_exits import (
        archived_watch_rows,
        exit_counterfactual,
        load_state,
    )
    from syndicate.features.shared.execution_ledger import full_history_orders

    state = load_state()
    report = exit_counterfactual(state, full_history_orders(), archived_watch=archived_watch_rows())
    report["last_tick"] = state.get("last_tick")
    if args.exits:
        report["exit_rows"] = sorted(
            (state.get("exits") or {}).values(), key=lambda r: str(r.get("decided_at") or "")
        )
    print(json.dumps(report, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
