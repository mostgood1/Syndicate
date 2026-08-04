"""CLI entrypoint for intelligence_evaluation.build_accuracy_summary --
one combined accuracy view per sport: overall metrics, the segmented
(sport, market_family, confidence_tier) reliability surface, and
day-bucketed win-rate/CLV drift.

Context: docs/reports/syndicate_learning_loop_plan_2026_08_03.md, Stage 5.

Must run somewhere with real access to the evaluation ledger -- that's
refresh-worker's disk in production, not the web service's (same
constraint /api/ops/evaluation-settlement/status works around via the
keyvalue store). This script is the manual/ad hoc entrypoint today; the
natural next step is wiring the same call into a refresh-worker autorun
that publishes its result through refresh_state_store, mirroring
run_refresh_worker.py's _launch_autorun_evaluation_settlement.

Usage:
    python scripts/build_accuracy_summary.py --sport mlb
    python scripts/build_accuracy_summary.py --sport wnba --recent-days 3 --baseline-days 14
    python scripts/build_accuracy_summary.py  # all sports combined
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from syndicate.features.shared.intelligence_evaluation import build_accuracy_summary


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sport", default=None, help="Sport slug to scope to (default: all sports combined)")
    parser.add_argument("--ledger-path", default="", help="Optional ledger path override")
    parser.add_argument("--recent-days", type=int, default=7)
    parser.add_argument("--baseline-days", type=int, default=21)
    args = parser.parse_args(list(argv) if argv is not None else None)

    ledger_path = Path(args.ledger_path) if str(args.ledger_path or "").strip() else None
    summary = build_accuracy_summary(
        ledger_path=ledger_path,
        sport=args.sport,
        recent_days=args.recent_days,
        baseline_days=args.baseline_days,
    )
    print(json.dumps(summary, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
