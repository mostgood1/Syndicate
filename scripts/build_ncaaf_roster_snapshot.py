from __future__ import annotations

import argparse
from pathlib import Path

from syndicate.features.ncaaf.cfbd import CfbdClient
from syndicate.features.ncaaf.cfbd import build_ncaaf_roster_generation_report
from syndicate.features.ncaaf.cfbd import run_cfbd_player_identity_build
from syndicate.features.ncaaf.cfbd import write_ncaaf_roster_snapshot_csv
from syndicate.features.ncaaf.sources import player_identity_snapshot_path
from syndicate.features.ncaaf.sources import roster_snapshot_path


def _default_report_path() -> Path:
    return Path(__file__).resolve().parents[1] / "ncaaf_roster_snapshot_generation_report.md"


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the canonical NCAAF roster snapshot from CFBD-backed player identity data.")
    parser.add_argument("--season", type=int, required=True, help="Season year to fetch from CFBD.")
    parser.add_argument("--identity-output-path", type=Path, default=None, help="Optional player identity CSV output path.")
    parser.add_argument("--roster-output-path", type=Path, default=None, help="Optional roster CSV output path.")
    parser.add_argument("--report-path", type=Path, default=None, help="Optional markdown report path.")
    parser.add_argument("--registry-path", type=Path, default=None, help="Optional canonical team registry file.")
    parser.add_argument("--base-url", type=str, default="https://api.collegefootballdata.com", help="CFBD base URL.")
    parser.add_argument("--timeout", type=float, default=30.0, help="Request timeout in seconds.")
    parser.add_argument("--source-snapshot-date", type=str, default=None, help="Optional roster snapshot provenance date.")
    args = parser.parse_args()

    client = CfbdClient.from_env(base_url=args.base_url, timeout=args.timeout)
    identity_result = run_cfbd_player_identity_build(
        client=client,
        season=args.season,
        registry_path=args.registry_path,
        output_path=args.identity_output_path or player_identity_snapshot_path(),
    )
    roster_result = write_ncaaf_roster_snapshot_csv(
        season=args.season,
        identity_snapshot_path=identity_result.output_path,
        identity_rows=identity_result.rows,
        output_path=args.roster_output_path or roster_snapshot_path(),
        source_snapshot_date=args.source_snapshot_date or identity_result.connectivity.get("season") and str(args.source_snapshot_date or ""),
    )
    report_text = build_ncaaf_roster_generation_report(
        season=args.season,
        output_path=roster_result.output_path,
        identity_path=identity_result.output_path,
        rows=roster_result.rows,
        validation_issues=roster_result.validation_issues,
        source_system=roster_result.source_system,
        source_snapshot_date=roster_result.source_snapshot_date,
    )
    report_path = args.report_path or _default_report_path()
    report_path.write_text(report_text, encoding="utf-8")
    print(report_text)
    return 0 if not roster_result.validation_issues else 1


if __name__ == "__main__":
    raise SystemExit(main())