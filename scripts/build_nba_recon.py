"""Build NBA post-game reconciliation artifacts (recon_games / recon_quarters / recon_props), Syndicate-owned, from
ESPN -- the NBA entry point to `scripts/build_wnba_recon.py` (lane `nba-season-phase`, 2026-10-06).

WHY. Nothing wrote NBA recon after 2026-06-13, so the NBA props bias calibration (7/30-day windows,
`basketball_props_calibration`) had no outcomes. The same outcome-only, completed-games-only rows as WNBA, from NBA's
ESPN endpoints, under nba_source/data/processed with NBA team codes. Production runs it from the NBA props refresh
(`nba_history_refresh.refresh_recon`); this CLI is for backfills.

Usage: python scripts/build_nba_recon.py --date 2026-10-05 [--data-root DIR] [--dry-run]
       python scripts/build_nba_recon.py --start 2026-10-02 --end 2026-10-05
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.build_wnba_recon import main as _main  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if "--league" not in args:
        args += ["--league", "nba"]
    return _main(args)


if __name__ == "__main__":
    raise SystemExit(main())
