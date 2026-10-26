"""Decision policy v1 PAPER track -- the fleet job (lane `decision-policy-paper`, Decision Engine Phase 2, #736).

PAPER ONLY. Pre-registration: `.syndicate/findings_2026-10-26_decision_policy_v1_preregistration.md` (8d16ab07).
No order module is imported here or below (tests/test_decision_policy_paper.py pins it).

    python scripts/run_decision_policy_paper.py book       # every 15 min: book from the newest heavy builds' records
    python scripts/run_decision_policy_paper.py nightly    # grade on the Pinnacle close + final scores, then the gate read
    python scripts/run_decision_policy_paper.py grade | evaluate

`SYNDICATE_DECISION_POLICY_PAPER=paper` turns booking on; absent is OFF (enabling is the user's decision). Grading
and the gate read run whenever there is a book to read, so a book stays graded if booking is switched off.
Runs at nice 19: the fleet shares this host.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from syndicate.features.shared import decision_policy_paper as paper  # noqa: E402


def _nice() -> None:
    try:
        os.nice(19)
    except (AttributeError, OSError):
        pass


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", nargs="?", default="book", choices=("book", "grade", "evaluate", "nightly"))
    ap.add_argument("--data-root", default=None, help="defaults to SYNDICATE_DATA_ROOT")
    args = ap.parse_args(argv)
    _nice()
    root = Path(args.data_root).expanduser() if args.data_root else None
    if args.command == "book":
        paper.run_book(root)
        return 0
    if args.command in ("grade", "nightly"):
        paper.run_grade(root)
    if args.command in ("evaluate", "nightly"):
        paper.run_evaluate(root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
