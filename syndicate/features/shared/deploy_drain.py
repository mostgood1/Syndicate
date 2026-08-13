"""`#409` phase 2 -- drain the PIPELINE before a deploy, not the PROCESS.

THE CONSTRAINT THAT SHAPES THIS. refresh-worker runs a board build measured at
804s / 1080s / 1372s (and 77 min once, `intelligence.py:9976`) and MLB sims with
no ETA. A Render deploy on a disk-attached service is stop-then-start, so every
deploy is a hard kill. You cannot finish a 22-minute build inside a SIGTERM
grace measured in seconds -- so classic drain is impossible here.

What IS possible: stop new long work from STARTING, then wait for what is
running to finish, then deploy into an idle worker. Drain becomes a state
entered before the deploy rather than something attempted during shutdown.

    deployer                          worker
       |-- request_drain(owner) ------>|  refuses to START new builds/sims
       |<-- publish_worker_state ------|  in_flight + acked_drain_at + commit
       |   poll until in_flight empty  |
       |-- deploy -------------------->|  killed while idle: nothing lost
       |-- clear_drain(owner) -------->|  resumes

`#409` phase 1 (`worker_shutdown.py`) records what a kill destroyed. This stops
there being anything to destroy.

UNKNOWN RESOLVES DIFFERENTLY FOR EACH SIDE, AND THAT ASYMMETRY IS DELIBERATE.
The same unreadable state means opposite things depending on who is asking:

  - WORKER asking "am I drained?" -> unreadable means NO, work normally.
    A keyvalue hiccup must never stop the board building forever. The cost of
    a wrong "no" is one build during a deploy window; the cost of a wrong
    "yes" is a permanent silent outage.
  - DEPLOYER asking "is the worker idle?" -> unreadable means UNKNOWN, BLOCK.
    The cost of a wrong "idle" is a destroyed 23-minute build.

Both are the safe direction for their own side, and they point opposite ways.
Encoding that once, here, is the point of this module.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

# A drain flag that outlives its deployer is a worker that never builds the
# board again -- a permanent outage manufactured by a crashed deploy script. So
# the flag carries its own expiry and is ignored past it, regardless of whether
# anything ever clears the key.
#
# THIS WAS 45 MIN AND THAT WAS TOO SHORT -- raised on review. The expiry must
# EXCEED the longest work the drain can be waiting on, or the sequence is:
# drain set -> long build in flight -> flag expires mid-wait -> the deployer's
# next poll sees no drain, the worker starts fresh work, and the deploy lands on
# it anyway. The drain reports success and destroys precisely what it was
# protecting -- and only on the SLOWEST builds, which are the most expensive to
# lose. A silent partial failure that looks like a working drain on every fast
# build.
#
# Measured worst case: `collect_candidates` was once observed at 77 minutes
# (4620s, `intelligence.py:9976`), against typical maxima of 1169s.
# 2.5h clears that with headroom.
#
# A long expiry is only safe because it is the LAST-RESORT self-heal, not the
# primary one: `drain_active()` also ignores any drain requested before this
# process booted (see below), so an ordinary restart clears it in seconds.
_DEFAULT_TTL_SECONDS = 150 * 60

# When this process started. A drain requested BEFORE it is already satisfied --
# see `drain_active`.
_PROCESS_BOOTED_AT = time.time()

# A worker's published state is only meaningful while it is still ticking. Two
# cycles of slack; past that the deployer must treat it as UNKNOWN rather than
# reading a dead worker's last "in_flight: {}" as "idle".
_HEARTBEAT_STALE_SECONDS = 180


def _state_dir() -> Path:
    from syndicate.features.shared.refresh_state_store import reports_root

    return reports_root() / "refresh_status" / "latest"


def _drain_path() -> Path:
    # SHARED between services on purpose, unlike `#405`'s per-service stamp.
    # A drain request is about "the deployment", not about one worker's own
    # schedule. If the two workers ever need independent drains this becomes
    # per-service the same way `#405` did.
    return _state_dir() / "deploy_drain.json"


def _worker_state_path(worker: str) -> Path:
    slug = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in str(worker).strip().lower()) or "worker"
    return _state_dir() / f"worker_drain_state_{slug}.json"


def _now() -> float:
    return time.time()


# --------------------------------------------------------------------------
# deployer side
# --------------------------------------------------------------------------

def request_drain(owner: str, *, ttl_seconds: int = _DEFAULT_TTL_SECONDS, reason: str = "") -> dict[str, Any]:
    from syndicate.features.shared.refresh_state_store import write_json_file

    payload = {
        "owner": str(owner),
        "reason": str(reason or ""),
        "requested_at": _now(),
        "expires_at": _now() + max(60, int(ttl_seconds)),
    }
    write_json_file(_drain_path(), payload)
    print(f"[deploy_drain] DRAIN_REQUESTED owner={owner} ttl_s={int(ttl_seconds)} reason={reason}", flush=True)
    return payload


def clear_drain(owner: str) -> bool:
    """Clear only if this owner set it. Returns whether it cleared.

    Owner-scoped so two concurrent deployers cannot clear each other's drain --
    the second joins the first's rather than overriding it, and neither ends up
    deploying into a worker the other is still waiting on.
    """
    from syndicate.features.shared.refresh_state_store import read_json_file, write_json_file

    current = read_json_file(_drain_path()) or {}
    current_owner = str(current.get("owner") or "")
    if current_owner and current_owner != str(owner):
        print(f"[deploy_drain] DRAIN_CLEAR_REFUSED owner={owner} held_by={current_owner}", flush=True)
        return False
    write_json_file(_drain_path(), {"owner": "", "requested_at": 0, "expires_at": 0, "reason": "cleared"})
    print(f"[deploy_drain] DRAIN_CLEARED owner={owner}", flush=True)
    return True


def read_worker_state(worker: str) -> tuple[dict[str, Any] | None, str]:
    """(state, verdict) for the DEPLOYER. verdict is 'idle' | 'busy' | 'unknown'.

    UNKNOWN IS NEVER 'idle'. Three distinct ways this is unknown, and all of
    them block:
      - the read failed (keyvalue hiccup) -- absence of evidence, not evidence
      - nothing published at all -- the deployed code may predate drain support,
        which is `#401`'s exact lesson: a flag read by code that is not
        deployed is inert, and the deployer must not mistake that for compliance
      - the heartbeat is stale -- a dead worker's last "in_flight: {}" is not
        idleness
    """
    from syndicate.features.shared.refresh_state_store import read_json_file_result

    payload, read_ok = read_json_file_result(_worker_state_path(worker))
    if not read_ok:
        return None, "unknown"
    if not isinstance(payload, dict) or not payload:
        return None, "unknown"
    try:
        age = _now() - float(payload.get("heartbeat_at") or 0.0)
    except (TypeError, ValueError):
        return payload, "unknown"
    if age > _HEARTBEAT_STALE_SECONDS:
        return payload, "unknown"
    if not payload.get("drain_aware"):
        # Published state from a build that does not understand drain at all.
        return payload, "unknown"
    in_flight = payload.get("in_flight") or {}
    busy = [k for k, v in in_flight.items() if v]
    return payload, ("busy" if busy else "idle")


# --------------------------------------------------------------------------
# worker side
# --------------------------------------------------------------------------

def drain_active() -> bool:
    """Is a drain in force RIGHT NOW?

    Unreadable or absent -> False. See the module docstring: for the worker the
    permissive direction is the safe one, because a wrong "yes" is a permanent
    board outage and a wrong "no" costs one build.
    """
    from syndicate.features.shared.refresh_state_store import read_json_file

    try:
        payload = read_json_file(_drain_path()) or {}
        if not payload.get("owner"):
            return False
        if _now() >= float(payload.get("expires_at") or 0.0):
            return False
        # A DRAIN REQUESTED BEFORE THIS PROCESS BOOTED IS ALREADY SATISFIED.
        #
        # Raised on review: nothing cleared the flag on SUCCESS. The deployer is
        # told to run `--undrain` afterwards, but if it does not -- crash,
        # forgotten step, someone deploying by hand -- the board stays deferred
        # for the remainder of the TTL AFTER the restart it was waiting for has
        # already happened. With the TTL now at 2.5h that is a long outage
        # bought by a fix for a shorter one.
        #
        # The restart IS the completion signal: a drain exists to get the worker
        # to an idle restart, so once this process has restarted, its purpose is
        # served. Computed locally from our own boot time -- no extra
        # coordination, no dependency on the deployer remembering.
        #
        # The awkward case is a drain set for a deploy that has not happened yet
        # while the worker restarts for an unrelated reason (OOM, the 6h
        # recycle). Then this ignores a still-wanted drain. It is not harmful:
        # the deployer polls `read_worker_state` for idle before deploying and
        # will simply see the new work and keep waiting. Slower, not unsafe --
        # and the alternative failure (a stale drain silencing the board) is the
        # one that is silent.
        return float(payload.get("requested_at") or 0.0) >= _PROCESS_BOOTED_AT
    except Exception:
        return False


def drain_hold_reason() -> str | None:
    """Reason string for a deferral site, or None to proceed."""
    if not drain_active():
        return None
    return "deploy_drain_requested"


_IN_FLIGHT: dict[str, bool] = {}


def set_in_flight(name: str, value: bool) -> None:
    _IN_FLIGHT[str(name)] = bool(value)


def publish_worker_state(worker: str, *, extra: dict[str, Any] | None = None) -> None:
    """Publish what this worker is doing. Called from the loop, every cycle.

    `in_flight` is set by the code that LAUNCHES the work, never inferred --
    a deployer acting on an inferred idle would be trusting a guess with a
    23-minute build behind it.
    """
    from syndicate.features.shared.refresh_state_store import write_json_file

    payload = {
        "worker": str(worker),
        "heartbeat_at": _now(),
        # Proves this build understands drain at all. Without it the deployer
        # cannot distinguish "not draining" from "cannot read the flag".
        "drain_aware": True,
        "acked_drain_at": _now() if drain_active() else None,
        "commit": str(os.environ.get("RENDER_GIT_COMMIT") or "")[:12] or None,
        "in_flight": dict(_IN_FLIGHT),
        **(extra or {}),
    }
    try:
        write_json_file(_worker_state_path(worker), payload)
    except Exception:
        # Never let publishing state take down the loop that publishes it.
        pass
