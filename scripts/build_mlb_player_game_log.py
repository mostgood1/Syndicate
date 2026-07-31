from __future__ import annotations

"""Build/update the MLB pitcher & batter game-log CSVs from mirrored
`feed_live` game feeds. Standalone entrypoint for `bootstrap_mlb_player_game_log`
-- also usable for a one-time local backfill; the same function is called
incrementally by scripts/run_mlb_daily_sim_job.py on every worker run.
"""

import argparse
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.mlb.player_game_log import bootstrap_mlb_player_game_log


def _default_data_root() -> str:
    override = str(os.environ.get("MLB_BETTING_DATA_ROOT") or "").strip()
    if override:
        return override
    data_root = str(os.environ.get("SYNDICATE_DATA_ROOT") or "data").strip()
    return os.path.join(data_root, "mlb_source", "source_artifacts", "data")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data-root", default=_default_data_root(), help="MLB data root (the dir containing raw/, processed/, daily/)")
    args = ap.parse_args()

    summary = bootstrap_mlb_player_game_log(args.data_root)
    print(f"MLB_PLAYER_GAME_LOG data_root={args.data_root} {summary}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
