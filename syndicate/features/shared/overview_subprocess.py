"""Run one sport's hydrated overview out-of-process, under a derived cap.

THE POINT: MLB's hydration excursion becomes SURVIVABLE instead of pre-empted.
`_OVERVIEW_MIN_SAFE_HEADROOM_BYTES` refuses MLB whenever headroom is under
3000MB, and measured 2026-08-28 headroom sits at 2167-2363MB, so it refuses
ALWAYS -- `BOARD_OVERVIEW_READY sports=7` with no `mlb:` entry for hours. The
floor is not wrong about the risk (`learnings.md 2026-08-15` names "MLB game
hydration in pid 39" as the kill, and the +3.5GB excursion is unexplained) but
a margin cannot cover a +3.5GB spike in a 4096MB container at ANY headroom it
could admit. So the margin only buys "MLB never builds".

A capped child buys the other thing: the excursion kills the child.

THE CAP IS DERIVED, NOT CONSTANT, and that is the load-bearing decision here.
`_OVERVIEW_MIN_SAFE_HEADROOM_BYTES` is a fixed 3000MB that became unreachable
because the PARENT's baseline drifted up underneath it -- the constant never
changed, the process did. A fixed child cap would repeat that failure exactly:
fine on a quiet worker, either useless or fatal on a busy one. So the cap is
computed from headroom AT CALL TIME, and the call refuses itself when there is
not enough room to try.

    cap = headroom - RESERVE
    refuse if cap < MIN_VIABLE

`RESERVE` is what the parent must keep for itself while the child runs; the
child can never be sized into the parent's own working set. `MIN_VIABLE` is the
floor below which a child would die on interpreter startup and teach us
nothing -- refusing is honest, a guaranteed-dead child is not.

OFF BY DEFAULT. This worker has 110 OOM kills on record and `#241` put it into
a restart loop by adding periodic work. A subprocess per board build is
periodic work.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Mapping

__all__ = [
    "overview_isolation_enabled",
    "isolated_sport_slugs",
    "build_sport_overview_isolated",
]

_REPO_ROOT = Path(__file__).resolve().parents[3]
_CHILD = _REPO_ROOT / "scripts" / "build_sport_overview_child.py"

# What the PARENT keeps while the child runs. The child is capped at
# `headroom - RESERVE`, so this is the margin that stops a correctly-sized
# child from squeezing the parent into its own OOM.
_RESERVE_BYTES = 400 * 1024 * 1024

# Below this a child cannot get through interpreter startup plus this app's
# imports, so it would die every time and report nothing useful. Refusing is a
# reading; a guaranteed-dead child is noise.
_MIN_VIABLE_CAP_BYTES = 900 * 1024 * 1024

_DEFAULT_TIMEOUT_SECONDS = 900


def overview_isolation_enabled() -> bool:
    """Default OFF. See the module docstring on why."""
    raw = (os.environ.get("SYNDICATE_OVERVIEW_ISOLATION_ENABLED") or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def isolated_sport_slugs() -> frozenset[str]:
    """Which sports go out-of-process.

    Defaults to `mlb` alone, because MLB is the only sport the expensive floor
    actually refuses -- the other seven clear the 1500MB streamed floor at
    today's headroom and cost +1.7MB/171ms for five of them measured together.
    Isolating a cheap sport would buy a process spawn and nothing else.
    """
    raw = (os.environ.get("SYNDICATE_OVERVIEW_ISOLATION_SPORTS") or "mlb").strip().lower()
    return frozenset(part.strip() for part in raw.split(",") if part.strip())


def _timeout_seconds() -> int:
    try:
        parsed = int(str(os.environ.get("SYNDICATE_OVERVIEW_ISOLATION_TIMEOUT_SECONDS") or "").strip())
    except (TypeError, ValueError):
        return _DEFAULT_TIMEOUT_SECONDS
    return parsed if parsed > 0 else _DEFAULT_TIMEOUT_SECONDS


def _headroom_bytes() -> int | None:
    """Measured headroom, or None when it cannot be read.

    None is NOT zero. On a machine with no cgroups (local dev) the caller must
    be able to tell "no room" from "no measurement" -- the first is a refusal,
    the second means isolation simply is not applicable and the in-process path
    should run as it always did.
    """
    try:
        from syndicate.features.shared.memory_observability import memory_headroom_snapshot

        snapshot = memory_headroom_snapshot(0)
    except Exception:
        return None
    if not isinstance(snapshot, Mapping):
        return None
    headroom_mb = snapshot.get("headroom_mb")
    try:
        return int(float(headroom_mb) * 1024 * 1024)
    except (TypeError, ValueError):
        return None


def _derive_cap_bytes() -> tuple[int | None, str]:
    """(cap, reason). cap is None when isolation must not be attempted."""
    headroom = _headroom_bytes()
    if headroom is None:
        return None, "headroom_unmeasurable"
    cap = headroom - _RESERVE_BYTES
    if cap < _MIN_VIABLE_CAP_BYTES:
        return None, f"cap_below_viable cap_mb={cap // (1024 * 1024)} min_mb={_MIN_VIABLE_CAP_BYTES // (1024 * 1024)}"
    return cap, "ok"


def build_sport_overview_isolated(
    sport: Mapping[str, Any],
    effective_date: str,
    *,
    force_refresh: bool = False,
    preserve_requested_date: bool = False,
) -> tuple[dict[str, Any] | None, str]:
    """Build one sport's row in a capped child. Returns (row, reason).

    `(None, reason)` on every failure path and NEVER raises: the caller is
    mid-board-build and a failure here must degrade to "this sport is absent",
    which is precisely the state MLB is in today anyway. There is no path where
    trying this is worse than the status quo.
    """
    slug = str((sport or {}).get("slug") or "?").lower()
    cap, reason = _derive_cap_bytes()
    if cap is None:
        print(f"[overview_isolation] REFUSED sport={slug} reason={reason}", flush=True)
        return None, reason
    if not _CHILD.exists():
        print(f"[overview_isolation] REFUSED sport={slug} reason=child_script_missing", flush=True)
        return None, "child_script_missing"

    started = time.monotonic()
    tmpdir = tempfile.mkdtemp(prefix="overview_iso_")
    sport_path = Path(tmpdir) / "sport.json"
    out_path = Path(tmpdir) / "row.json"
    try:
        sport_path.write_text(json.dumps(dict(sport), default=str), encoding="utf-8")
        argv = [
            sys.executable, str(_CHILD),
            "--sport-json", str(sport_path),
            "--date", str(effective_date or ""),
            "--out", str(out_path),
            "--cap-bytes", str(int(cap)),
        ]
        if force_refresh:
            argv.append("--force-refresh")
        if preserve_requested_date:
            argv.append("--preserve-requested-date")

        proc = subprocess.run(
            argv, cwd=str(_REPO_ROOT), capture_output=True, text=True,
            timeout=_timeout_seconds(),
        )
        elapsed = round(time.monotonic() - started, 2)
        # The child's own diagnostics are RELAYED, not swallowed. Its
        # CAP_SET/MEMORY_CAP_HIT lines are the only evidence of what the cap
        # did, and they are on the child's stdout.
        for line in (proc.stdout or "").splitlines():
            if line.strip():
                print(f"  {line.strip()}", flush=True)
        if proc.returncode != 0:
            tail = (proc.stderr or "").strip().splitlines()[-1:] or [""]
            print(
                f"[overview_isolation] CHILD_FAILED sport={slug} rc={proc.returncode} "
                f"elapsed_s={elapsed} cap_mb={cap // (1024 * 1024)} stderr={tail[0][:160]}",
                flush=True,
            )
            return None, f"child_rc_{proc.returncode}"
        row = json.loads(out_path.read_text(encoding="utf-8"))
        if not isinstance(row, dict):
            print(f"[overview_isolation] CHILD_BAD_ROW sport={slug} type={type(row).__name__}", flush=True)
            return None, "bad_row_type"
        print(
            f"[overview_isolation] OK sport={slug} elapsed_s={elapsed} "
            f"cap_mb={cap // (1024 * 1024)} keys={len(row)}",
            flush=True,
        )
        return row, "ok"
    except subprocess.TimeoutExpired:
        print(
            f"[overview_isolation] CHILD_TIMEOUT sport={slug} "
            f"timeout_s={_timeout_seconds()} elapsed_s={round(time.monotonic() - started, 2)}",
            flush=True,
        )
        return None, "timeout"
    except Exception as exc:
        print(f"[overview_isolation] FAILED sport={slug} {type(exc).__name__}: {exc}", flush=True)
        return None, f"{type(exc).__name__}"
    finally:
        # Best-effort cleanup. A leaked temp dir on a disk-backed worker is a
        # slow leak, so it is attempted, but failing to clean up must not turn
        # a successful build into a failed one.
        try:
            for path in (sport_path, out_path):
                if path.exists():
                    path.unlink()
            os.rmdir(tmpdir)
        except Exception:
            pass
