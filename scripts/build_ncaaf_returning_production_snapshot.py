from __future__ import annotations

import argparse
from pathlib import Path

from syndicate.features.ncaaf.cfbd import CfbdClient
from syndicate.features.ncaaf.cfbd import build_ncaaf_returning_production_generation_report
from syndicate.features.ncaaf.cfbd import write_ncaaf_returning_production_snapshot_csv
from syndicate.features.ncaaf.sources import returning_production_snapshot_path
from syndicate.features.ncaaf.sources import roster_snapshot_path
from syndicate.features.ncaaf.sources import transfer_portal_snapshot_path


def _default_report_path() -> Path:
    return Path(__file__).resolve().parents[1] / "docs" / "reports" / "ncaaf_returning_production_generation_report.md"


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the canonical NCAAF returning-production snapshot from CFBD.")
    parser.add_argument("--season", type=int, required=True, help="Season year to fetch from CFBD.")
    parser.add_argument("--output-path", type=Path, default=None, help="Optional returning-production CSV output path.")
    parser.add_argument("--report-path", type=Path, default=None, help="Optional markdown report path.")
    parser.add_argument("--roster-path", type=Path, default=None, help="Optional roster snapshot path.")
    parser.add_argument("--transfer-path", type=Path, default=None, help="Optional transfer portal snapshot path.")
    parser.add_argument("--registry-path", type=Path, default=None, help="Optional canonical team registry file.")
    parser.add_argument("--base-url", type=str, default="https://api.collegefootballdata.com", help="CFBD base URL.")
    parser.add_argument("--timeout", type=float, default=30.0, help="Request timeout in seconds.")
    args = parser.parse_args()

    client = CfbdClient.from_env(base_url=args.base_url, timeout=args.timeout)
    result = write_ncaaf_returning_production_snapshot_csv(
        client=client,
        season=args.season,
        roster_snapshot_path_input=args.roster_path or roster_snapshot_path(),
        transfer_snapshot_path_input=args.transfer_path or transfer_portal_snapshot_path(),
        registry_path=args.registry_path,
        output_path=args.output_path or returning_production_snapshot_path(),
    )
    report_text = build_ncaaf_returning_production_generation_report(
        season=args.season,
        output_path=result.output_path,
        roster_path=args.roster_path or roster_snapshot_path(),
        transfer_path=args.transfer_path or transfer_portal_snapshot_path(),
        rows=result.rows,
        validation_issues=result.validation_issues,
        source_system=result.source_system,
        source_snapshot_date=result.source_snapshot_date,
    )
    report_path = args.report_path or _default_report_path()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report_text, encoding="utf-8")
    print(report_text)
    return 0 if not result.validation_issues else 1


if __name__ == "__main__":
    raise SystemExit(main())