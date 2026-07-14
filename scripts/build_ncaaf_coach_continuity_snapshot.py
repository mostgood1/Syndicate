from __future__ import annotations

import argparse
from pathlib import Path

from syndicate.features.ncaaf.cfbd import CfbdClient
from syndicate.features.ncaaf.cfbd import build_ncaaf_coach_continuity_generation_report
from syndicate.features.ncaaf.cfbd import write_ncaaf_coach_continuity_snapshot_csv
from syndicate.features.ncaaf.sources import coach_continuity_snapshot_path


def _default_report_path() -> Path:
    return Path(__file__).resolve().parents[1] / "ncaaf_coach_continuity_generation_report.md"


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the canonical NCAAF coach continuity snapshot from CFBD.")
    parser.add_argument("--season", type=int, required=True, help="Season year to fetch from CFBD.")
    parser.add_argument("--output-path", type=Path, default=None, help="Optional coach continuity CSV output path.")
    parser.add_argument("--report-path", type=Path, default=None, help="Optional markdown report path.")
    parser.add_argument("--registry-path", type=Path, default=None, help="Optional canonical team registry file.")
    parser.add_argument("--base-url", type=str, default="https://api.collegefootballdata.com", help="CFBD base URL.")
    parser.add_argument("--timeout", type=float, default=30.0, help="Request timeout in seconds.")
    args = parser.parse_args()

    client = CfbdClient.from_env(base_url=args.base_url, timeout=args.timeout)
    result = write_ncaaf_coach_continuity_snapshot_csv(
        client=client,
        season=args.season,
        output_path=args.output_path or coach_continuity_snapshot_path(),
    )
    report_text = build_ncaaf_coach_continuity_generation_report(
        season=args.season,
        output_path=result.output_path,
        rows=result.rows,
        validation_issues=result.validation_issues,
        source_system=result.source_system,
        source_snapshot_date=result.source_snapshot_date,
    )
    report_path = args.report_path or _default_report_path()
    report_path.write_text(report_text, encoding="utf-8")
    print(report_text)
    return 0 if not result.validation_issues else 1


if __name__ == "__main__":
    raise SystemExit(main())