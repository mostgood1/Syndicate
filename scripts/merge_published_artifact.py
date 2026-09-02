"""Merge one published artifact, OUT OF PROCESS. `#630`.

WHY A SUBPROCESS RATHER THAN A THREAD. Both merges allocate, and CPython does
not return freed arenas to the OS, so anything run inside gunicorn ratchets the
worker's RSS permanently. A background thread would not have helped -- same
process, same arenas. A child gives the whole address space back on exit. It
also restores `CLAUDE.md`'s rule that the web service does no heavy computation.

MEASURED, and the second line is why `book_quotes` is here too:

    book_quotes  (line union)   34 MB in     ->  20 MB peak   <- SYNTHETIC
    book_quotes  (line union)  154 MB target ->  81 MB peak   <- REAL SCALE
    odds_history (JSON union)   88 MB in     -> 276 MB peak

The line union was kept on the request path on the strength of the 20 MB figure.
Production's shard is 150 MB, not 34 MB, and at that size it peaks at 81 MB --
on the most frequent publish on the platform, ~10 a minute. The ratio held; the
absolute number, which is what ratchets a worker, was 4x larger.

LOCKING DIFFERS BY FAMILY, ON PURPOSE:
  * odds_history takes ONE service-wide lock, because 276 MB a merge is what
    needed bounding in the first place.
  * append-only takes a PER-PATH lock: 81 MB children on different files are
    affordable, and serialising them would queue the platform's most frequent
    publish behind everything else. Two children on the SAME target must still
    not race.

The parent writes the incoming body to a staging file and spawns this; it does
NOT wait. If this never runs, the target keeps the copy it already had -- stale
by one publish, which is the pre-merge behaviour and not a clobber.

THIS OWNS ITS STAGING FILE. On success it is deleted; on a refusal it is
PROMOTED (the plain replace, i.e. pre-merge behaviour) rather than discarded --
with one exception: an incoming that is not valid JSON is dropped, because
promoting it would overwrite a good artifact with garbage.

Usage:
    py -3 scripts/merge_published_artifact.py --target T --incoming S --family append_only
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.shared.artifact_merge import (  # noqa: E402
    merge_append_only,
    merge_odds_history,
    merge_quote_state,
)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--target", required=True)
    ap.add_argument("--incoming", required=True)
    ap.add_argument("--family", required=True, choices=("append_only", "odds_history", "quote_state"))
    ap.add_argument("--relative-path", default="")
    ap.add_argument("--lock-wait-seconds", type=float, default=180.0)
    args = ap.parse_args()

    target = Path(args.target)
    incoming = Path(args.incoming)
    result: dict = {}
    try:
        if not target.is_file():
            # Nothing to merge INTO. The parent only stages when the target
            # exists, so it vanished underneath us -- promote rather than drop.
            if incoming.is_file():
                incoming.replace(target)
                result = {"merged": False, "error": "target_absent: promoted staged copy",
                          "promoted_staged_copy": True}
            else:
                result = {"merged": False, "error": "target_absent_and_staging_absent"}
        elif not incoming.is_file():
            result = {"merged": False, "error": "staging_absent"}
        elif args.family == "append_only":
            result = merge_append_only(target, incoming,
                                       lock_wait_seconds=args.lock_wait_seconds)
        elif args.family == "quote_state":
            # No lock: the sidecar is ~5 MB, so it does not need the memory
            # bound the other two do, and a race here self-heals like any other
            # -- every publisher sends its whole file each cycle.
            result = merge_quote_state(target, incoming)
        else:
            result = merge_odds_history(target, incoming,
                                        lock_wait_seconds=args.lock_wait_seconds)
    except Exception as exc:  # never let a crash strand the staging file
        result = {"merged": False, "error": f"{type(exc).__name__}: {exc}"}
    finally:
        try:
            if incoming.is_file():
                if result.get("merged") or result.get("do_not_promote"):
                    incoming.unlink(missing_ok=True)
                elif not result.get("promoted_staged_copy"):
                    incoming.replace(target)
                    result = dict(result)
                    result["promoted_staged_copy"] = True
        except Exception:
            try:
                incoming.unlink(missing_ok=True)
            except Exception:
                pass

    payload = dict(result)
    payload["family"] = args.family
    if args.relative_path:
        payload["path"] = args.relative_path
    try:
        payload["bytes"] = target.stat().st_size
    except Exception:
        pass
    # The parent is not waiting, so this line IS the record.
    print(f"[artifact_merge] ARTIFACT_MERGE_CHILD {json.dumps(payload, sort_keys=True)}",
          flush=True)
    return 0 if result.get("merged") else 1


if __name__ == "__main__":
    sys.exit(main())
