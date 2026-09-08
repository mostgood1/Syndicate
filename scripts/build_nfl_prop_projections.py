"""Precompute NFL player-prop projections into an artifact web can read.

WHY THIS SCRIPT EXISTS, measured rather than assumed.

On 2026-09-08, the day before the season opener, `/nfl/api/props` served **0
cards** for week 1 against a capture of 5,929 real quotes (519 players, 8
books, 16 matchups). Nothing errored and nothing logged. Web's own request log,
once the join was instrumented:

    [nfl_props] JOIN season=2026 week=1 odds_rows=2455 sim_rows=0
                refused_wrong_team=0 refused_unknown_team=0

The ODDS half was healthy end to end -- 2,455 rows. BOTH refusal counters at
zero prove nothing reached the team check, so the loop exited at the only
`continue` above it, `player_id is None`, on every row. That requires
`player_name_index` to be empty for BOTH 2026 and 2025, and both are derived
from play-by-play. **web has no pbp.** refresh-worker does -- its projection
artifact carries `rating_source=nflverse_pbp_epa_rolling[...]`.

Three services, three disks (`CLAUDE.md`: cross-disk access is a hard
requirement). The prop model was being computed on the service WITHOUT the
data, which is also the service `CLAUDE.md` says must do no heavy computation:
"workers write artifacts, web reads them". This script is the worker half.

WHAT IT DOES NOT DO. It does not change the model. `nfl_props_rows_for_week`
computes exactly what it always computed -- the week-1 prior-season fallback,
the team check that rejects a defender inheriting a running back's game log,
and `#471`'s anytime-TD shrinkage all live there and are simply run HERE
instead of on a request. `--use-artifact` is forced OFF for this run, so the
producer can never read its own previous output and republish it unchanged.

USAGE
    py -3 scripts/build_nfl_prop_projections.py --season 2026 --week 1
    py -3 scripts/build_nfl_prop_projections.py --season 2026 --week 1 --json
"""
from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.nfl.props import (  # noqa: E402
    nfl_props_rows_for_week,
    write_nfl_prop_projection_artifact,
)
from syndicate.features.shared.artifact_publisher import publish_hot_artifact  # noqa: E402


def build(season: int, week: int) -> dict:
    # use_artifact=False is load-bearing: the producer must COMPUTE, never read
    # back the artifact it is about to overwrite. Without it a stale artifact
    # would be republished forever and look like a healthy rebuild.
    odds_rows, sim_rows = nfl_props_rows_for_week(season, week, use_artifact=False)
    path = write_nfl_prop_projection_artifact(season, week, sim_rows)
    # PUBLISH, or the worker writes to its own disk and web never sees it --
    # which is the entire defect this artifact exists to fix, reintroduced one
    # layer up. `publish_hot_artifact` no-ops with a printed
    # SKIP_NOT_CONFIGURED when the publish URL/token are unset (local runs), so
    # this is safe off-worker and loud about it rather than silent.
    published = publish_hot_artifact(path)
    rate_sources = collections.Counter(str(row.get("rate_source") or "?") for row in sim_rows)
    markets = collections.Counter(
        str(row.get("market") or "").split("::", 1)[0] for row in sim_rows
    )
    return {
        "ok": True,
        "season": season,
        "week": week,
        "path": str(path),
        "published": bool(published),
        "odds_rows": len(odds_rows),
        "sim_rows": len(sim_rows),
        "entities": len({str(row.get("entity") or "") for row in sim_rows}),
        "rate_sources": dict(rate_sources),
        "markets": dict(markets.most_common()),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--week", type=int, required=True)
    parser.add_argument("--json", action="store_true", help="machine-readable summary")
    args = parser.parse_args()

    result = build(args.season, args.week)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"wrote {result['path']}  published={result['published']}")
        print(f"  odds_rows {result['odds_rows']}  sim_rows {result['sim_rows']}  "
              f"entities {result['entities']}")
        print(f"  rate_sources {result['rate_sources']}")
        print(f"  markets {result['markets']}")

    # A zero-row artifact is a FAILURE to report, not a file to publish quietly:
    # it is indistinguishable downstream from "this week has no market", and
    # that ambiguity is the whole defect this script exists to remove.
    return 0 if result["sim_rows"] > 0 else 3


if __name__ == "__main__":
    raise SystemExit(main())
