"""Arm the controlled transfer for the ONE hour that can separate the horns: a live spike.

WHY A SECOND ARM. Arm 1 (`controlled_transfer_20260909T000627Z`, bucket
`2026-09-09T01:00:00Z`) calibrated both instruments in a NORMAL hour and found
them both close to true: the edge log recorded 0.913-0.919 of requests we knew
we made, and the meter charged 1.516-1.575x real delivered bytes. Neither is
anywhere near the 10.77x and 24.37x that the spike hours need. So the
calibration is a CONTROL, and it narrowed the contradiction without resolving
it: whatever happens in a spike hour is specific to spike hours.

The lane's own conclusion names the follow-up: *"A follow-up firing DURING a
live spike is the experiment that would separate the horns; this one could not,
because no spike was running."* This is that firing.

WHAT MAKES IT DECISIVE WITHOUT THE METER. P1 -- log completeness -- needs no
meter at all. Every request carries a unique `ctprobe` token, so the edge log
either accounts for requests we counted independently, or it does not. Run the
SAME transfer in a spike hour and the recorded fraction answers the disjunction
directly:

  recorded ~= 0.92, as in the normal hour  -> the edge log does NOT drop lines
      under spike load, so log incompleteness cannot explain a 10-24x gap, and
      the metered bytes never appeared as edge requests at all.
  recorded << 0.92                         -> the log DOES drop under spike
      load, and the size of the drop bounds how much of the gap it explains.

Arm A is therefore deliberately the SAME VOLUME as arm 1 (150 MB, ~2,500
requests): spike-vs-normal is then the only variable between the two readings.

TWO ARMS, ONE FIRING. Spikes cannot be summoned -- yesterday had seven, today
two, and none since 02:00Z -- so this also carries a fallback:

  ARM A  (preferred)  a spike is running   -> fire 150 MB, `--skip-quiet-check`.
  ARM B  (fallback)   a verified-quiet hour in the band -> fire 300 MB, twice
      arm 1's volume, which is the "second arm at a different volume" the lane
      requires before anyone acts on the 1.5x coefficient.

Whichever fires first ends the watch. Scoring is `controlled_transfer_read.py`,
run once the bucket has settled (>= 70 min after the hour closes).

DETECTION, AND THE TWO TRAPS IN IT. Render does not return a bucket for the hour
still in flight, and a closed bucket keeps growing for ~50 minutes. So a spike
is detected from the LAST RETURNED bucket, settled or not: a partial reading can
only grow, so a partial already over `--spike-mb` stays over it.

**Metered MB alone does not identify a spike** -- `2026-09-09T00:00:00Z` metered
437.7 MB and was one human browsing at a ratio of 2.15. The discriminator is
metered / edge-logged over the same window: 1.66 / 2.15 / 3.56 for ordinary
hours against 10.77 / 24.37 for the two spikes. Both bars must be cleared. A
half-settled bucket makes the ratio read LOW, so this detector is conservative
and fires late rather than early. The bet is that spikes CLUSTER -- 2026-09-08 ran five consecutive hours --
so firing in the current hour on the previous hour's evidence lands inside the
episode. If it does not, the reading is a normal-hour replication of arm 1,
which is worth having and is reported as such rather than as arm A.

CONTAMINATION, ARM B ONLY. `learnings.md` and this lane's own item (c): the
probe's quiet gate samples 10 minutes, the meter's unit is an hour, and arm 1
passed the gate at 5.493 MB and still ended 43% background. So arm B is watched
THROUGHOUT and killed if background arrives, rather than being scored dirty.
Arm A needs no such gate -- a spike hour IS contaminated by definition, and P1
counts our own tokens regardless.

    py -3 scripts/controlled_transfer_arm2_watch.py --until 2026-09-10T12:00:00Z
    py -3 scripts/controlled_transfer_arm2_watch.py --dry-run
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from scripts.bandwidth_tripwire import (  # noqa: E402
    SERVICE_IDS, _RESP_BYTES, _USER_AGENT, _api_key, _logs, _metric,
)

OUT_DIR = REPO_ROOT / "reports" / "bandwidth_spikes"
PROBE = REPO_ROOT / "scripts" / "controlled_transfer_probe.py"
PROBE_UA = "syndicate-controlled-transfer/1.0"

#: METERED MB ALONE DOES NOT IDENTIFY A SPIKE, and using it as the trigger was
#: this script's first bug. `2026-09-09T00:00:00Z` metered 437.7 MB and was ONE
#: HUMAN BROWSING (edge 203.57 MB, ratio 2.15) -- the third reader's entry in the
#: lane exists precisely to stop that bucket being counted as a spike. What
#: separates a spike is the RATIO of metered to edge-logged bytes: the ladder
#: runs 1.66 / 2.15 / 3.56 for ordinary hours and 10.77 / 24.37 for the two
#: spikes. So both conditions must hold, and the cheap one is checked first.
DEFAULT_SPIKE_MB = 300.0
DEFAULT_SPIKE_RATIO = 6.0
#: Arm A matches arm 1's volume exactly so spike-vs-normal is the only variable.
ARM_A_MB = 150.0
#: Arm B doubles it: the different-volume second arm the coefficient needs.
ARM_B_MB = 300.0
#: Non-probe bytes in a 5-minute sample that void arm B mid-flight.
ARM_B_CONTAMINATION_MB = 8.0
#: Arm B only fires with this much of the hour left, so 300 MB cannot straddle.
ARM_B_MIN_SECONDS_LEFT = 2600
#: Same for arm A. 150 MB at concurrency 2 measured ~1,136 s, plus the probe's
#: own 240 s boundary margin. The first draft of this guard was 900 s, which
#: would have detected a spike and then handed the probe an hour it could not
#: fit in -- an abort dressed up as a firing.
ARM_A_MIN_SECONDS_LEFT = 1600


def _now() -> dt.datetime:
    return dt.datetime.utcnow()


def _stamp(when: dt.datetime | None = None) -> str:
    return (when or _now()).strftime("%Y-%m-%dT%H:%M:%SZ")


def _say(message: str) -> None:
    print(f"[{_stamp()}] {message}", flush=True)


def latest_bucket(key: str) -> tuple[str, float]:
    """The most recent bucket Render will return, settled or not.

    Deliberately NOT filtered by settle time: this is a spike DETECTOR, and a
    partial reading over the threshold can only grow. `bandwidth_tripwire`'s
    settle rule exists to stop a low reading being called quiet -- the opposite
    error -- and does not apply here.
    """
    now = _now()
    values = _metric(
        key, "bandwidth", SERVICE_IDS["web"],
        (now - dt.timedelta(hours=4)).strftime("%Y-%m-%dT%H:00:00Z"),
        _stamp(now),
    )
    if not values:
        return "", 0.0
    bucket = max(values)
    return bucket, values[bucket]


def edge_mb_for_bucket(key: str, bucket: str) -> tuple[float, int]:
    """Edge-logged bytes over the window a RIGHT-labelled bucket covers."""
    end = dt.datetime.strptime(bucket[:19], "%Y-%m-%dT%H:%M:%S")
    start = end - dt.timedelta(hours=1)
    rows = _logs(
        key, SERVICE_IDS["web"],
        start.strftime("%Y-%m-%dT%H:%M:%SZ"), end.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "request", max_pages=120,
    )
    total = 0
    for _ts, message, _labels in rows:
        size = _RESP_BYTES.search(message)
        total += int(size.group(1)) if size else 0
    return total / 1048576, len(rows)


def background_mb(key: str, minutes: int) -> tuple[float, int]:
    """Non-probe edge bytes in the last `minutes`. Our own UA is excluded."""
    now = _now()
    rows = _logs(
        key, SERVICE_IDS["web"],
        (now - dt.timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        _stamp(now), "request", max_pages=40,
    )
    total = 0
    count = 0
    for _ts, message, _labels in rows:
        agent = _USER_AGENT.search(message)
        if agent and agent.group(1).startswith(PROBE_UA.split("/")[0]):
            continue
        size = _RESP_BYTES.search(message)
        total += int(size.group(1)) if size else 0
        count += 1
    return total / 1048576, count


def seconds_left_in_hour() -> float:
    now = _now()
    return 3600.0 - (now.minute * 60 + now.second + now.microsecond / 1e6)


def fire(arm: str, target_mb: float, skip_quiet: bool, key: str, watch: bool) -> dict:
    """Run the probe as a child, optionally killing it if background arrives."""
    command = [
        sys.executable, str(PROBE),
        "--target-mb", str(target_mb),
        "--concurrency", "2",
    ]
    if skip_quiet:
        command.append("--skip-quiet-check")
    _say(f"FIRING {arm}: {' '.join(command[2:])}")
    started = _stamp()
    process = subprocess.Popen(command, cwd=str(REPO_ROOT))
    samples: list[dict] = []
    voided = ""
    next_sample = time.time() + 300
    while process.poll() is None:
        time.sleep(5)
        if not watch or time.time() < next_sample:
            continue
        next_sample = time.time() + 300
        try:
            megabytes, requests = background_mb(key, 5)
        except Exception as exc:  # a sampling failure must not kill the transfer
            samples.append({"at": _stamp(), "error": repr(exc)})
            continue
        samples.append({"at": _stamp(), "background_mb": round(megabytes, 3), "requests": requests})
        _say(f"   background sample: {megabytes:.3f} MB / {requests} reqs in 5 min")
        if megabytes > ARM_B_CONTAMINATION_MB:
            voided = f"background {megabytes:.3f} MB in 5 min exceeds {ARM_B_CONTAMINATION_MB} MB"
            _say(f"   VOID: {voided} -- killing the transfer rather than scoring it dirty")
            process.terminate()
            break
    process.wait(timeout=120)
    return {
        "arm": arm,
        "target_mb": target_mb,
        "started_at": started,
        "ended_at": _stamp(),
        "returncode": process.returncode,
        "background_samples": samples,
        "voided": voided,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--until", default="", help="UTC ISO stamp to stop watching (default +14h)")
    parser.add_argument("--spike-mb", type=float, default=DEFAULT_SPIKE_MB)
    parser.add_argument("--spike-ratio", type=float, default=DEFAULT_SPIKE_RATIO,
                        help="metered / edge-logged MB over the same window; ordinary "
                             "hours run 1.66-3.56, the two spikes 10.77 and 24.37")
    parser.add_argument("--arm-a-mb", type=float, default=ARM_A_MB)
    parser.add_argument("--arm-b-mb", type=float, default=ARM_B_MB)
    parser.add_argument("--quiet-band", default="05:00-11:00",
                        help="UTC hours in which arm B may fire (start of hour)")
    parser.add_argument("--quiet-bucket-mb", type=float, default=20.0,
                        help="last bucket must be under this for arm B to be considered")
    parser.add_argument("--poll-minutes", type=float, default=4.0)
    parser.add_argument("--dry-run", action="store_true", help="evaluate the conditions once, fire nothing")
    args = parser.parse_args()

    key = _api_key()
    deadline = (
        dt.datetime.strptime(args.until[:19], "%Y-%m-%dT%H:%M:%S")
        if args.until else _now() + dt.timedelta(hours=14)
    )
    band_start, band_end = (int(part.split(":")[0]) for part in args.quiet_band.split("-"))

    record: dict = {
        "watch_started_at": _stamp(),
        "watch_until": _stamp(deadline),
        "spike_mb": args.spike_mb,
        "spike_ratio": args.spike_ratio,
        "quiet_band_utc": args.quiet_band,
        "polls": [],
        "fired": None,
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"arm2_watch_{_now().strftime('%Y%m%dT%H%M%SZ')}.json"
    _say(f"watching until {_stamp(deadline)}; record -> {out}")

    while _now() < deadline:
        bucket, metered = latest_bucket(key)
        left = seconds_left_in_hour()
        hour = _now().hour
        poll = {"at": _stamp(), "latest_bucket": bucket, "latest_bucket_mb": round(metered, 2),
                "seconds_left_in_hour": round(left)}

        # The ratio scan costs a full log page-through, so it is gated behind the
        # cheap metered test. A busy browsing hour clears the MB bar and fails
        # the ratio bar, which is the whole point of having two.
        if metered >= args.spike_mb and left > ARM_A_MIN_SECONDS_LEFT:
            edge, requests = edge_mb_for_bucket(key, bucket)
            ratio = metered / edge if edge > 0 else float("inf")
            poll.update({"edge_mb": round(edge, 2), "edge_requests": requests,
                         "metered_over_edge": round(ratio, 2)})
            _say(f"   over {args.spike_mb} MB: edge {edge:.1f} MB / {requests} reqs -> ratio {ratio:.2f}")
            if ratio >= args.spike_ratio:
                poll["decision"] = "ARM_A"
                record["polls"].append(poll)
                _say(f"SPIKE DETECTED: {bucket} {metered:.1f} MB at ratio {ratio:.2f} -- arm A")
                if args.dry_run:
                    record["fired"] = {"arm": "A", "dry_run": True}
                    break
                record["fired"] = fire("A", args.arm_a_mb, skip_quiet=True, key=key, watch=False)
                break
            poll["ratio_verdict"] = "busy hour, not a spike"

        in_band = band_start <= hour < band_end
        if in_band and metered <= args.quiet_bucket_mb and left >= ARM_B_MIN_SECONDS_LEFT:
            poll["decision"] = "ARM_B"
            record["polls"].append(poll)
            _say(f"QUIET WINDOW: {bucket} at {metered:.1f} MB, {left:.0f}s left -- arm B")
            if args.dry_run:
                record["fired"] = {"arm": "B", "dry_run": True}
                break
            fired = fire("B", args.arm_b_mb, skip_quiet=False, key=key, watch=True)
            record["fired"] = fired
            # The probe refuses a dirty window itself; if it aborted, keep watching.
            if fired["returncode"] == 0 and not fired["voided"]:
                break
            _say("   arm B did not land (probe aborted or voided) -- still watching")
            record.setdefault("attempts", []).append(fired)
            record["fired"] = None
        else:
            poll["decision"] = "wait"
            reasons = []
            if not in_band:
                reasons.append(f"hour {hour:02d}Z outside {args.quiet_band}")
            if metered > args.quiet_bucket_mb:
                reasons.append(f"last bucket {metered:.1f} MB > {args.quiet_bucket_mb}")
            if left < ARM_B_MIN_SECONDS_LEFT:
                reasons.append(f"{left:.0f}s left < {ARM_B_MIN_SECONDS_LEFT}")
            poll["why"] = "; ".join(reasons)
            record["polls"].append(poll)
            _say(f"wait: {bucket} {metered:.1f} MB -- {poll['why']}")

        out.write_text(json.dumps(record, indent=2, sort_keys=True), encoding="utf-8")
        if args.dry_run:
            break
        time.sleep(args.poll_minutes * 60)

    record["watch_ended_at"] = _stamp()
    if record["fired"] is None and not args.dry_run:
        record["outcome"] = "NO FIRING -- no spike detected and no quiet hour in the band"
        _say(record["outcome"])
    out.write_text(json.dumps(record, indent=2, sort_keys=True), encoding="utf-8")
    _say(f"record written -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
