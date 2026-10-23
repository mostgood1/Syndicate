"""Render (or re-render) the DecisionRecord daily agreement report for a date.

The refresh-worker re-renders it after every build (`decision_agreement.write_daily_report`),
so this is for reading a finished day or re-rendering after a format change. It reads
only the per-build lines on disk (`<data root>/reports/intelligence/decision_records/
<date>.agreement.jsonl`); it never touches the plans or the ledger.

    python scripts/decision_record_agreement_report.py --date 2026-10-23 [--root <data root>] [--json]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from syndicate.features.shared import decision_agreement as da  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--date", required=True)
    parser.add_argument("--root", help="data root (default: SYNDICATE_DATA_ROOT)")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    root = Path(args.root) if args.root else None
    summary = da.write_daily_report(args.date, root=root)
    json_path, md_path = da.report_paths(args.date, root)
    if args.json:
        print(json.dumps(summary, indent=1, default=str))
    else:
        print(md_path.read_text(encoding="utf-8"))
        print(f"(written: {md_path} and {json_path})")
    return 0 if summary.get("builds") else 1


if __name__ == "__main__":
    raise SystemExit(main())
