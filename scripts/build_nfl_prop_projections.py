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
from play-by-play.

CORRECTED 2026-09-08, and the correction is the whole point of this header.
The first version of this docstring said "**web has no pbp.** refresh-worker
does -- its projection artifact carries `rating_source=nflverse_pbp_epa_rolling`".
That inference was wrong. `nflverse_pbp_epa_rolling` is TEAM-level EPA and
says nothing about the player-level columns this model needs. The worker's own
log, at the instant its first autorun ran:

    19:19:57.443  NFL_PROP_PROJECTION_LAUNCHING season=2026 week=1
    19:19:57.565  [nfl_props] JOIN ... sim_source=computed odds_rows=2463
                  sim_rows=0 refused_wrong_team=0 refused_unknown_team=0

**refresh-worker had 2,463 odds rows and still produced zero sim rows**, with
both refusal counters at zero -- the identical signature web showed. So the
odds capture was never the missing input, and NEITHER SERVICE CAN RESOLVE A
PLAYER NAME.

Why it cannot simply be shipped there: `_pbp_path` reads
`nfl_source/tracking/nflverse/pbp/pbp_<season>.csv`, that path is **not in
`HOT_ARTIFACT_PATTERNS` at all** (so it can neither publish nor stream), and
`pbp_2025.csv` is **97.9 MB** against a 12 MiB `_PUBLISH_MAX_BYTES`. Loading it
also materialises every REG play as a dict on a worker that already plateaus at
2.65-2.70 GB of 4 GB.

WHAT THAT MEANS FOR THIS SCRIPT. On a service with the pbp -- today, a
developer checkout -- it is the producer, and `CLAUDE.md` explicitly permits
that arm: artifact generation happens in background workers "or offline
scripts". On refresh-worker it CANNOT succeed, so its job there is to refuse
without damage and repair itself, which is what the two guards below do.
`load_player_plays` returns `()` for a missing file, so the failure is silent
at every level except the row count -- exactly the `.get(key, 1.0)` shape
`model_engine_standard.md` exists to forbid.

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
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.nfl.props import (  # noqa: E402
    nfl_props_rows_for_week,
    read_nfl_prop_projection_artifact,
    write_nfl_prop_projection_artifact,
)
from syndicate.features.shared.artifact_publisher import publish_hot_artifact  # noqa: E402
from syndicate.features.shared.artifact_publisher import pull_streamed_artifact  # noqa: E402
from syndicate.features.shared.refresh_state_store import data_root  # noqa: E402


def _artifact_vintage(payload_bytes: bytes | None) -> tuple[int, datetime | None, str | None]:
    """(rows, generated_at, generated_at as written) of a prop artifact's bytes.

    (0, None, None) for anything unreadable -- the same "unreadable is empty"
    reading `nfl.props._prop_projection_row_count` applies.
    """
    if not payload_bytes:
        return 0, None, None
    try:
        payload = json.loads(payload_bytes.decode("utf-8-sig"))
    except Exception:
        return 0, None, None
    if not isinstance(payload, dict):
        return 0, None, None
    rows = payload.get("sim_rows")
    count = sum(1 for row in rows if isinstance(row, dict)) if isinstance(rows, list) else 0
    text = str(payload.get("generated_at") or "").strip() or None
    parsed = None
    if text:
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            parsed = None
    return count, parsed, text


def _restore(target: Path, before: bytes | None, before_stat: os.stat_result | None) -> None:
    """Put `target` back exactly as it was: bytes AND mtime, or absent."""
    if before is None:
        target.unlink(missing_ok=True)
        return
    temp = target.with_name(f"{target.name}.{os.getpid()}.restore.tmp")
    temp.write_bytes(before)
    os.replace(temp, target)
    if before_stat is not None:
        # THE MTIME TOO. `pull_streamed_artifact` asks web for a copy newer than
        # this file's mtime, and the hot-artifact sweep publishes files whose
        # mtime moved. A restore stamped "now" would read as a fresh edit to
        # both -- the republish-a-bad-copy shape 2026-09-08 cost.
        os.utime(target, ns=(before_stat.st_atime_ns, before_stat.st_mtime_ns))


def _repair_populated_local_copy(artifact_relative: str, local_rows: int) -> dict:
    """Pull web's copy over a POPULATED local one; keep it only if it is not older.

    WHY A POPULATED COPY IS REPAIRED AT ALL, measured 2026-09-10 on
    refresh-worker. The rule used to be "a local copy with rows is left alone no
    matter what web is serving", and the worker logged, every hour all day:

        REPAIR_SKIPPED_LOCAL_OK local_rows=980 (not overwriting a good local copy)

    while web served the 1,140-row artifact built 2026-09-10T00:09:04Z. The
    worker cannot build this artifact (no player pbp), so a copy it ever held
    was a copy it kept FOREVER, and the NFL board joined against it: ingest
    `prop_coverage.artifact_rows 683`, and 119 of 119 NFL prop rows carrying a
    sim view were Anytime TD -- the one lineless market, the signature of a
    build from before the `stat::player::line` key (2026-09-08). Against web's
    copy the same page's prop rows match 599 of 967.

    WHAT STILL CANNOT HAPPEN, and why the old rule existed: web's copy
    destroying a good local one. That was a 111-byte EMPTY artifact pulled over
    a real one. So the pulled copy survives ONLY when it has rows AND its own
    `generated_at` is not older than the local copy's (equal is the same build,
    and keeping it lets the next pull 304). Empty, older, or a vintage either
    side cannot state is rolled back byte-for-byte, mtime included. Gated on the
    OUTPUT -- what actually landed -- not on a prediction of what web would send.

    Cheap in the steady state: `pull_streamed_artifact` sends the local mtime,
    and web answers 304 when its copy is not newer, which writes nothing.
    """
    target = data_root() / Path(artifact_relative)
    try:
        before = target.read_bytes() if target.is_file() else None
        before_stat = target.stat() if before is not None else None
    except OSError:
        before, before_stat = None, None
    before_rows, before_generated, before_text = _artifact_vintage(before)

    ok, written = pull_streamed_artifact(artifact_relative)
    if not written:
        print(
            f"[build_nfl_prop_projections] REPAIR_LOCAL_CURRENT local_rows={local_rows} "
            f"generated_at={before_text} (web's copy is not newer; nothing pulled) ok={ok}",
            flush=True,
        )
        return {"ok": bool(ok), "written": 0, "outcome": "local_current"}

    try:
        after = target.read_bytes() if target.is_file() else None
    except OSError:
        after = None
    after_rows, after_generated, after_text = _artifact_vintage(after)
    if after_rows <= 0:
        reason = "pulled_copy_empty"
    elif before is None or before_rows <= 0:
        # Nothing at this path to protect -- the empty-local rule, unchanged.
        reason = None
    elif before_generated is None or after_generated is None:
        reason = "vintage_unknown"
    elif after_generated < before_generated:
        reason = "pulled_copy_older"
    else:
        reason = None

    if reason is None:
        outcome = (
            "same_build"
            if before_generated is not None and after_generated == before_generated
            else "pulled_newer"
        )
        print(
            f"[build_nfl_prop_projections] REPAIR_PULLED_NEWER outcome={outcome} "
            f"local_rows={before_rows} generated_at={before_text} -> rows={after_rows} "
            f"generated_at={after_text} path={target}",
            flush=True,
        )
        return {"ok": True, "written": int(written), "outcome": outcome}

    _restore(target, before, before_stat)
    print(
        f"[build_nfl_prop_projections] REPAIR_ROLLED_BACK reason={reason} "
        f"local_rows={before_rows} generated_at={before_text} "
        f"pulled_rows={after_rows} pulled_generated_at={after_text} (local copy restored)",
        flush=True,
    )
    return {"ok": False, "written": 0, "outcome": f"rolled_back_{reason}"}


def build(season: int, week: int) -> dict:
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
        # REPAIR THIS SERVICE'S LOCAL COPY, because "left untouched" is not
        # enough on refresh-worker: the damage there is a file that ALREADY
        # exists and is already wrong.
        #
        # MEASURED 2026-09-08. The pre-guard autorun wrote a 284-byte empty
        # artifact to the worker's disk. A periodic sweep then publishes hot
        # artifacts to web, and it republishes that file after every restart --
        # `PUBLISH_OK ... bytes=284` at 19:19:57, again at 19:22:34, and again
        # at 20:01:38 immediately after the 19:58:07 deploy, with
        # `PUBLISH_SKIPPED_UNCHANGED checksum=77a9ed3cd0c7` in between. So the
        # board did not break once; it breaks again on every boot, and each
        # time it silently overwrites a good 966-row artifact with an empty one.
        # `/nfl/api/props` was serving 0 cards when this was written.
        #
        # A guard that only declines to write leaves that file in place
        # forever. Pulling the PUBLISHED copy makes the local file equal to the
        # good one, so the very next sweep is a no-op
        # (`PUBLISH_SKIPPED_UNCHANGED`) instead of a clobber -- it converts a
        # recurring outage into a self-correcting one.
        #
        # Ordering this matters and is not obvious: if web's copy is ALSO empty
        # this pull is worthless, so the published artifact must be restored
        # FIRST and the worker then converges onto it. It cannot make things
        # worse -- pulling an empty over an empty is a no-op, and
        # `pull_streamed_artifact` never raises.
        # ONLY REPAIR A LOCAL COPY THAT IS ALREADY BROKEN. Measured while
        # writing this: run on a checkout whose odds capture was missing, the
        # unconditional version pulled web's 111-byte EMPTY artifact straight
        # over the local one -- `STREAM_PULL_OK ... bytes=111`. A repair that
        # can destroy a good copy is not a repair; on a developer box, which is
        # the only machine that CAN build this today, it would delete the one
        # artifact in existence.
        #
        # The worker's broken state is specifically "local artifact present and
        # EMPTY", so condition on exactly that. A local copy with rows is left
        # alone no matter what web is serving.
        #
        # CORRECTED 2026-09-10: "left alone no matter what web is serving" was
        # the worker's SECOND broken state, and it lasted a day. A POPULATED
        # copy is now offered web's and keeps its own unless web's is populated
        # and not older -- `_repair_populated_local_copy` has the measurement
        # and the rule. An EMPTY local copy is pulled over exactly as before.
        existing = read_nfl_prop_projection_artifact(season, week)
        local_rows = len(existing or [])
        artifact_relative = (
            f"nfl_source/nfl_prop_projections_{season}_wk{week}.json"
        )
        if local_rows:
            repair = _repair_populated_local_copy(artifact_relative, local_rows)
            repaired_ok, repaired_n = repair["ok"], repair["written"]
            repair_outcome = repair["outcome"]
        else:
            repaired_ok, repaired_n = pull_streamed_artifact(artifact_relative)
            repair_outcome = "pulled_over_empty_local"
        print(
            f"[build_nfl_prop_projections] REFUSED season={season} week={week} "
            f"reason=zero_sim_rows odds_rows={len(odds_rows)} "
            f"(nothing written) repair_pull={artifact_relative} "
            f"ok={repaired_ok} written={repaired_n} outcome={repair_outcome}",
            flush=True,
        )
        return {
            "ok": False,
            "refused": "zero_sim_rows",
            "season": season,
            "week": week,
            "path": None,
            "published": False,
            "repair_pull_ok": bool(repaired_ok),
            "repair_pull_written": int(repaired_n or 0),
            "repair_outcome": repair_outcome,
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
