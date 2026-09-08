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
from syndicate.features.shared.artifact_publisher import pull_streamed_artifact  # noqa: E402


def build(season: int, week: int) -> dict:
    # PULL THE ODDS CAPTURE FIRST -- IT LIVES ON WEB, NOT HERE, AND THAT SPLIT
    # IS WHAT MADE THIS SCRIPT PUBLISH AN EMPTY ARTIFACT OVER A GOOD ONE.
    #
    # MEASURED 2026-09-08: the autorun's first real run built 0 rows on
    # refresh-worker and clobbered a healthy 966-row artifact. Reproduced
    # locally by deleting the odds file -- `odds_rows=0 -> sim_rows=0`, exactly
    # the artifact the worker produced. **refresh-worker has the play-by-play
    # but NOT the NFL odds capture; web has the odds capture but NOT the
    # play-by-play. Neither service has both.**
    #
    # WHY THE CAPTURE NEVER ARRIVED ON ITS OWN, and it is by construction, not
    # by accident: `pull_hot_artifacts` is DATE-scoped (`?pattern=*<date>*`)
    # because an unfiltered pull reproducibly hit Render's proxy timeout. This
    # file is WEEK-suffixed -- `oddsapi_player_props_2026_wk1.csv` -- so it can
    # never match a date pattern. `pull_hot_artifacts`'s own docstring names the
    # class: "a handful of non-dated files ... are out of scope for this
    # per-cycle pull and would need a separate, infrequent full sync."
    #
    # ONE NAMED FILE, NOT A WIDER PATTERN. `_SEASON_ARTIFACT_PATTERNS` was the
    # other candidate and is the wrong lever: `pull_season_artifacts` is called
    # before an MLB ROSTER build, so adding an NFL pattern there would make
    # every MLB build pull NFL props, and that function's docstring is explicit
    # that each request must stay narrow for the same 502 reason. This pulls
    # exactly the file this script needs, when it needs it.
    #
    # Never fatal: `pull_streamed_artifact` never raises, and a 304 (already
    # current) is a success that writes nothing -- the normal steady state. If
    # the pull fails, the build proceeds and the zero-row guard below refuses,
    # which is the correct degradation.
    odds_relative = f"nfl_source/oddsapi_player_props_{season}_wk{week}.csv"
    pulled_ok, pulled_n = pull_streamed_artifact(odds_relative)
    print(
        f"[build_nfl_prop_projections] ODDS_PULL path={odds_relative} "
        f"ok={pulled_ok} written={pulled_n}",
        flush=True,
    )

    # use_artifact=False is load-bearing: the producer must COMPUTE, never read
    # back the artifact it is about to overwrite. Without it a stale artifact
    # would be republished forever and look like a healthy rebuild.
    odds_rows, sim_rows = nfl_props_rows_for_week(season, week, use_artifact=False)

    # REFUSE BEFORE WRITING. A zero-row build must not touch the artifact at
    # all -- not write it, not publish it.
    #
    # THIS IS THE BUG THAT CLOBBERED PRODUCTION, and my first cut wrote the
    # guard in the wrong PLACE rather than omitting it. `main()` returned
    # `0 if sim_rows > 0 else 3`, which reads like a guard and is not one: the
    # write and the publish both happen ABOVE it, so the exit code reports
    # damage already done. Measured 2026-09-08: the autorun fired at 19:19:57Z,
    # built 0 rows on the worker, published them over a healthy 966-row
    # artifact, and `/nfl/api/props` went 1,684 cards -> 0 in production.
    #
    # An exit code is a REPORT. A guard has to sit before the side effect.
    #
    # Empty is not an error worth crashing on -- a week with no capture
    # legitimately has nothing to build -- so this returns a refusal the caller
    # can log, and leaves whatever is already published untouched. Stale beats
    # empty here: a stale prop board is wrong about prices, an empty one is
    # indistinguishable from "this week has no market".
    if not sim_rows:
        print(
            f"[build_nfl_prop_projections] REFUSED season={season} week={week} "
            f"reason=zero_sim_rows odds_rows={len(odds_rows)} "
            f"(existing artifact left untouched)",
            flush=True,
        )
        return {
            "ok": False,
            "refused": "zero_sim_rows",
            "season": season,
            "week": week,
            "path": None,
            "published": False,
            "odds_pull_ok": bool(pulled_ok),
            "odds_pull_written": int(pulled_n or 0),
            "odds_rows": len(odds_rows),
            "sim_rows": 0,
            "entities": 0,
            "rate_sources": {},
            "markets": {},
        }

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
        "odds_pull_ok": bool(pulled_ok),
        "odds_pull_written": int(pulled_n or 0),
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
        if result.get("refused"):
            print(f"REFUSED: {result['refused']} -- odds_rows {result['odds_rows']}, "
                  f"nothing written, existing artifact left untouched")
        else:
            print(f"wrote {result['path']}  published={result['published']}")
        print(f"  odds_rows {result['odds_rows']}  sim_rows {result['sim_rows']}  "
              f"entities {result['entities']}")
        print(f"  rate_sources {result['rate_sources']}")
        print(f"  markets {result['markets']}")

    # The exit code REPORTS; `build()` above is what actually refuses. Keeping
    # both is deliberate -- the autorun reads neither today, and a future caller
    # that checks the code should still get a non-zero on a refusal.
    return 0 if result.get("sim_rows") else 3


if __name__ == "__main__":
    raise SystemExit(main())
