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
    return Path(__file__).resolve().parents[1] / "docs" / "reports" / "ncaaf_roster_snapshot_generation_report.md"


def _load_env() -> None:
    try:
        from dotenv import load_dotenv  # type: ignore
    except Exception:
        return
    load_dotenv()


def main() -> int:
    _load_env()
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
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report_text, encoding="utf-8")
    print(report_text)

    # PUBLISH TO WEB -- `lane ncaaf-roster-snapshot-publish`, 2026-09-09.
    #
    # Nothing published this artifact before today. Measured on production
    # 2026-09-09 23:2xZ: `/api/ops/artifacts/export?pattern=ncaaf_source/**/
    # ncaaf_roster_snapshot.csv` returned 0 artifacts, so every NCAAF card's
    # per-side sim projection table (`16d5d811`) rendered its stated empty
    # state -- "The 2026 roster snapshot carries no skill-position players for
    # <team>" -- on all 51 cards. That empty state was CORRECT: the reader
    # works and the file had never crossed the service boundary. The worker
    # writes to its own mounted disk; `_roster_index_cached` in
    # `syndicate/features/ncaaf/player_projections.py` reads WEB's.
    #
    # The allowlist entry added alongside this (`HOT_ARTIFACT_PATTERNS`) only
    # PERMITS the transfer -- `#208`. There is no blanket sweep on
    # refresh-worker (`sweep_changed_hot_artifacts`'s only production caller is
    # `live_lens_loop`, on another service), so without this explicit call the
    # entry is inert and every upstream stage still reports success.
    #
    # UNCONDITIONAL, deliberately, and on a COMPLETED run rather than a clean
    # one: the CSV is written by `write_ncaaf_roster_snapshot_csv` before
    # validation is scored, `validation_issues` only changes this process's
    # EXIT CODE, and a run that produced a file web does not have should
    # converge web on it. Gating the push on a flag or on a clean validation is
    # how a stale bootstrapped copy survives every subsequent rebuild.
    # `publish_hot_artifact` itself checks the allowlist and is a best-effort
    # no-op when unconfigured, so this costs nothing off Render -- the same
    # shape `build_nfl_roster_snapshot.py` already uses.
    try:
        from syndicate.features.shared.artifact_publisher import publish_hot_artifact

        published = publish_hot_artifact(roster_result.output_path)
    except Exception as exc:  # noqa: BLE001 - transfer must never fail the build
        published = False
        print(f"artifact_publish_error={type(exc).__name__}: {exc}", flush=True)
    print(f"artifact_published={published}", flush=True)

    return 0 if not roster_result.validation_issues else 1


if __name__ == "__main__":
    raise SystemExit(main())