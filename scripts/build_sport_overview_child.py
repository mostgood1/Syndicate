"""Build ONE sport's overview row in a capped child process.

WHY THIS EXISTS. `build_intelligence_overview` refuses MLB every cycle:
measured 2026-08-28, `OVERVIEW_STOPPED_FOR_MEMORY next_sport=mlb
floor=expensive floor_mb=3000` against `headroom_mb` 2167-2363. The board has
carried zero MLB games for hours as a result.

The floor is not wrong and this does not lower it. `learnings.md 2026-08-15`
EXONERATES the eight-sport pass and names "MLB game hydration in pid 39" as the
kill, and the +3.5GB excursion behind the floor is still unexplained. But a
margin cannot cover it: +3.5GB kills a 4096MB container at ANY headroom the
floor could admit. So the margin buys nothing except MLB never building.

WHAT THIS BUYS INSTEAD: the excursion becomes SURVIVABLE. The hydration runs
here, under `RLIMIT_AS`. If it excurses, THIS process dies and the parent reads
a failure and carries on. The unexplained variance stops being something to
pre-empt and becomes something to contain.

CONTRACT, deliberately narrow:
  argv: --sport-json <path> --date <iso> --out <path> [--force-refresh]
        [--preserve-requested-date] [--cap-bytes N]
  stdout: diagnostics only, prefixed `[overview_child]`
  exit 0  -> `--out` holds the JSON row
  exit != 0 -> parent degrades; `--out` may not exist

THE ROW GOES TO A FILE, NOT STDOUT. A hydrated MLB row is large, and a parent
reading a multi-megabyte payload off a pipe while the child is still writing is
a deadlock waiting for a slow day. A file has no such failure mode, and the
parent deletes it.

`RLIMIT_AS` AND NOT `RLIMIT_DATA`: address space is what the allocator actually
fails on under CPython, and it is the limit the container's own OOM shape most
resembles. It is blunt -- it counts reservations, not residency -- which is why
the parent sizes the cap from MEASURED HEADROOM rather than from a guess about
how much MLB "should" need.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def _apply_memory_cap(cap_bytes: int) -> None:
    """Cap address space so an excursion kills THIS process, not the worker.

    Best-effort and NAMED on failure. A platform without `resource` (Windows
    dev) still runs the build -- it just runs uncapped, which is exactly the
    behaviour it had before this file existed. Refusing to build because the
    cap could not be set would trade a real degradation for a hypothetical one.
    """
    if cap_bytes <= 0:
        print("[overview_child] CAP_SKIPPED reason=non_positive", flush=True)
        return
    try:
        import resource
    except Exception as exc:  # pragma: no cover - Windows/dev
        print(f"[overview_child] CAP_UNAVAILABLE {type(exc).__name__}: {exc}", flush=True)
        return
    try:
        soft, hard = resource.getrlimit(resource.RLIMIT_AS)
        # Never raise an existing hard limit -- that would fail, and on a
        # container that already caps us the existing one is the real ceiling.
        new_hard = hard if hard != resource.RLIM_INFINITY and hard < cap_bytes else cap_bytes
        resource.setrlimit(resource.RLIMIT_AS, (cap_bytes, new_hard))
        print(f"[overview_child] CAP_SET rlimit_as_bytes={cap_bytes} prev_soft={soft}", flush=True)
    except Exception as exc:
        print(f"[overview_child] CAP_FAILED {type(exc).__name__}: {exc}", flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sport-json", required=True, help="path to the sport config dict, JSON")
    parser.add_argument("--date", default="", help="effective date, ISO")
    parser.add_argument("--out", required=True, help="where to write the row JSON")
    parser.add_argument("--force-refresh", action="store_true")
    parser.add_argument("--preserve-requested-date", action="store_true")
    parser.add_argument("--cap-bytes", type=int, default=0)
    args = parser.parse_args(argv)

    # CAP FIRST, before importing the app. The import itself allocates, and a
    # cap applied afterwards would let the expensive part of startup run
    # uncapped and then constrain only the hydration.
    _apply_memory_cap(int(args.cap_bytes or 0))

    try:
        sport = json.loads(Path(args.sport_json).read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"[overview_child] SPORT_JSON_UNREADABLE {type(exc).__name__}: {exc}", flush=True)
        return 2

    try:
        from syndicate.features.intelligence import _build_sport_overview
    except Exception as exc:
        print(f"[overview_child] IMPORT_FAILED {type(exc).__name__}: {exc}", flush=True)
        return 3

    slug = str((sport or {}).get("slug") or "?")
    try:
        row = _build_sport_overview(
            sport,
            str(args.date or ""),
            force_refresh=bool(args.force_refresh),
            preserve_requested_date=bool(args.preserve_requested_date),
            skip_game_hydration=False,
        )
    except MemoryError:
        # The cap doing its job, reported as itself rather than as a generic
        # crash. This is the outcome the whole file exists to produce.
        print(f"[overview_child] MEMORY_CAP_HIT sport={slug}", flush=True)
        return 4
    except Exception as exc:
        print(f"[overview_child] BUILD_FAILED sport={slug} {type(exc).__name__}: {exc}", flush=True)
        return 5

    try:
        # `default=str` because the row is display data assembled from many
        # modules and has carried datetimes before. A row that cannot round-trip
        # must degrade to a STRING, not take the build down.
        payload = json.dumps(row, default=str)
    except Exception as exc:
        print(f"[overview_child] SERIALISE_FAILED sport={slug} {type(exc).__name__}: {exc}", flush=True)
        return 6

    try:
        Path(args.out).write_text(payload, encoding="utf-8")
    except Exception as exc:
        print(f"[overview_child] WRITE_FAILED sport={slug} {type(exc).__name__}: {exc}", flush=True)
        return 7

    print(f"[overview_child] OK sport={slug} bytes={len(payload)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
