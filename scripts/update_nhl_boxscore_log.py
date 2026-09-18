"""Update NHL's per-game player log by hand: a backfill, or a check of what the scheduled run would do. `#674`.

The scheduled writer is `scripts/refresh_nhl_oddsapi.py`, which calls
`syndicate.features.nhl.boxscore_log.refresh_hosted_game_log` on every NHL refresh. This CLI
runs the same `update_game_log` against any path, and publishes only when asked.

    py -3 scripts/update_nhl_boxscore_log.py --path <csv> [--today 2026-09-20] [--lookback-days 10] [--publish]
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.nhl import boxscore_log  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--path", default=str(REPO_ROOT / "data" / "nhl_source" / boxscore_log.RELATIVE_PATH))
    parser.add_argument("--today", default="", help="Eastern date the window ends on (default: today, Eastern)")
    parser.add_argument("--lookback-days", type=int, default=boxscore_log.LOOKBACK_DAYS)
    parser.add_argument("--max-games", type=int, default=boxscore_log.MAX_GAMES_PER_RUN)
    parser.add_argument("--publish", action="store_true", help="publish the file to web when it changed")
    args = parser.parse_args(argv)

    today = date.fromisoformat(args.today) if args.today else boxscore_log._eastern_today()
    path = Path(args.path)
    result = boxscore_log.update_game_log(path, today=today, lookback_days=args.lookback_days, max_games=args.max_games)
    print(f"NHL_GAME_LOG path={path} {result.summary()}", flush=True)
    if args.publish and result.wrote:
        from syndicate.features.shared import artifact_publisher as publisher

        print(f"NHL_GAME_LOG published={publisher.publish_hot_artifact(path, timeout_seconds=60)}", flush=True)
    return 1 if result.unreadable_days or result.unreadable_boxes else 0


if __name__ == "__main__":
    raise SystemExit(main())
