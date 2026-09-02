"""Merge one published `odds_history` artifact, OUT OF PROCESS. `#630`.

WHY A SUBPROCESS RATHER THAN A THREAD. The JSON union holds two parsed
documents: measured 276 MB peak on 88 MB of input (3.13x) on the real MLB
shard. Run inside gunicorn on web -- a 2Gi service -- that RATCHETED the memory
floor from 717.7 MB at boot to ~1030 MB once merges started, and it did not come
back, because CPython does not return freed arenas to the OS. A background
thread would not have helped: same process, same arenas.

A child process gives the whole address space back on exit, so the gunicorn
worker's RSS never grows. It also restores `CLAUDE.md`'s rule that the web
service does no heavy computation.

The parent writes the incoming body to a staging file and spawns this; it does
NOT wait. If this never runs, the target keeps the copy it already had -- stale
by one publish, which is the pre-merge behaviour and not a clobber.

THIS DELETES ITS OWN STAGING FILE, including on refusal. A staging file left
behind is disk that nothing will ever reclaim.

Usage:
    py -3 scripts/merge_odds_history_artifact.py --target T --incoming S
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.shared.artifact_merge import merge_odds_history  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--target", required=True)
    ap.add_argument("--incoming", required=True)
    ap.add_argument("--relative-path", default="")
    args = ap.parse_args()

    target = Path(args.target)
    incoming = Path(args.incoming)
    try:
        if not target.is_file():
            # Nothing to merge INTO. The parent only stages when the target
            # exists, so this means it vanished underneath us -- promote the
            # staged copy rather than dropping it on the floor.
            if incoming.is_file():
                incoming.replace(target)
                result = {"merged": False, "error": "target_absent: promoted staged copy"}
            else:
                result = {"merged": False, "error": "target_absent_and_staging_absent"}
        elif not incoming.is_file():
            result = {"merged": False, "error": "staging_absent"}
        else:
            result = merge_odds_history(target, incoming)
    except Exception as exc:  # never let a crash strand the staging file
        result = {"merged": False, "error": f"{type(exc).__name__}: {exc}"}
    finally:
        try:
            incoming.unlink(missing_ok=True)
        except Exception:
            pass

    payload = dict(result)
    if args.relative_path:
        payload["path"] = args.relative_path
    try:
        payload["bytes"] = target.stat().st_size
    except Exception:
        pass
    # The parent is not waiting, so this line IS the record.
    print(f"[artifact_merge] ODDS_HISTORY_MERGE {json.dumps(payload, sort_keys=True)}", flush=True)
    return 0 if result.get("merged") else 1


if __name__ == "__main__":
    sys.exit(main())
