from __future__ import annotations

import argparse
from pathlib import Path

from syndicate.features.ncaaf.cfbd import CfbdClient
from syndicate.features.ncaaf.cfbd import build_integration_report
from syndicate.features.ncaaf.cfbd import run_cfbd_player_identity_build
from syndicate.features.ncaaf.sources import player_identity_snapshot_path


def _default_report_path() -> Path:
    return Path(__file__).resolve().parents[1] / "docs" / "reports" / "ncaaf_cfbd_integration_report.md"


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the NCAAF player identity snapshot from CFBD.")
    parser.add_argument("--season", type=int, required=True, help="Season year to fetch from CFBD.")
    parser.add_argument("--output-path", type=Path, default=None, help="Optional CSV output path.")
    parser.add_argument("--report-path", type=Path, default=None, help="Optional markdown report path.")
    parser.add_argument("--registry-path", type=Path, default=None, help="Optional canonical team registry file.")
    parser.add_argument("--base-url", type=str, default="https://api.collegefootballdata.com", help="CFBD base URL.")
    parser.add_argument("--timeout", type=float, default=30.0, help="Request timeout in seconds.")
    args = parser.parse_args()

    client = CfbdClient.from_env(base_url=args.base_url, timeout=args.timeout)
    result = run_cfbd_player_identity_build(
        client=client,
        season=args.season,
        registry_path=args.registry_path,
        output_path=args.output_path or player_identity_snapshot_path(),
    )

    report_text = build_integration_report(
        season=args.season,
        connectivity=result.connectivity,
        team_registry_rows=result.team_registry_rows,
        roster_rows=result.roster_rows,
        snapshot_rows=result.rows,
        validation_issues=result.validation_issues,
        output_path=result.output_path,
        registry_mode="provided" if args.registry_path else "provisional_cfbd_team_catalog",
    )
    report_path = args.report_path or _default_report_path()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report_text, encoding="utf-8")
    print(report_text)
    return 0 if not result.validation_issues else 1


if __name__ == "__main__":
    raise SystemExit(main())