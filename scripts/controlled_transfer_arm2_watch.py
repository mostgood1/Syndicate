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
437.7 MB and was one human browsing. The discriminator is metered / APP-SERVED
over the same window: 0.35-3.05 for ordinary hours against 8.20-16.84 for the
five anomalous ones, scored over all 19 captured hours. Both bars must be
cleared. A half-settled bucket makes the ratio read LOW, so this detector is
conservative and fires late rather than early.

**The denominator was `edge` until 2026-09-10 and that was wrong** -- it
overlaps (10.23-33.58 anomalous vs 0.52-20.59 ordinary; a 0.41 MB near-idle
hour reads 20.59), and at the old 6.0 bar it admitted one false fire. It is
still recorded on every poll, so polls either side of the switch stay
comparable; it just no longer decides. When the app log is BLIND the gate
REFUSES -- it does not fall back to the edge ratio. The bet is that spikes CLUSTER -- 2026-09-08 ran five consecutive hours --
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
    SERVICE_IDS, _ACCESS, _RESP_BYTES, _USER_AGENT, _api_key, _logs, _metric,
)

OUT_DIR = REPO_ROOT / "reports" / "bandwidth_spikes"
PROBE = REPO_ROOT / "scripts" / "controlled_transfer_probe.py"
PROBE_UA = "syndicate-controlled-transfer/1.0"

#: METERED MB ALONE DOES NOT IDENTIFY A SPIKE, and using it as the trigger was
#: this script's first bug. `2026-09-09T00:00:00Z` metered 437.7 MB and was ONE
#: HUMAN BROWSING (edge 203.57 MB, ratio 2.15) -- the third reader's entry in the
#: lane exists precisely to stop that bucket being counted as a spike. So a
#: RATIO bar is needed beside the MB bar, and the cheap one is checked first.
#:
#: THE RATIO'S DENOMINATOR IS `app-served`, NOT `edge` `[2026-09-10, user
#: directed; lane `bandwidth-excess-vs-ratio`, evidence `42d4794b`]`. Scored
#: against all 19 captured hours: `metered/edge` runs 10.23-33.58 in the five
#: anomalous hours against 0.52-20.59 in the fourteen others -- it OVERLAPS, and
#: a near-idle hour (`2026-09-09 09:00Z`, 0.41 MB metered, 66 requests) reads
#: 20.59, inside the band `09-08 16:00Z` occupies at 2,470 MB. `metered/app`
#: runs 8.20-16.84 against 0.35-3.05 -- it SEPARATES. At the old bar of 6.0 on
#: edge, eleven hours clear 300 MB and six clear the ratio: the five real ones
#: plus `09-08 15:00Z` (420 MB, edge ratio 7.09, app ratio 3.05 -- not
#: anomalous). `metered/app >= 5.0` cuts to exactly the five, no false fire and
#: none missed. A false fire is not free: it spends 150 MB of billed bytes and
#: hands P1 a reading LABELLED a spike hour that is not one, which destroys the
#: single variable arm 2 controls.
DEFAULT_SPIKE_MB = 300.0
#: Kept, RECORDED, and NO LONGER GATING -- the field stays comparable with the
#: polls taken before the switch, but nothing branches on it.
DEFAULT_SPIKE_RATIO = 6.0
DEFAULT_SPIKE_APP_RATIO = 5.0
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


#: THE APP LOG IS FAR BIGGER THAN THE EDGE LOG AND `_logs` PAGES AT 100 LINES.
#: `edge_mb_for_bucket` uses 120 pages and that is ample for a request log
#: (377-449 lines in the hours captured so far); the same budget on the APP log
#: would have TRUNCATED `2026-09-08T00:00:00Z`, a real spike hour, at 12,000 of
#: its 15,644 lines. Truncation is the dangerous direction: it under-counts the
#: DENOMINATOR, inflates `metered/app`, and manufactures precisely the false
#: fire this gate was switched to prevent. 400 pages is 2.6x the largest hour
#: on record (15,644), and the coverage check below refuses rather than trusting
#: the budget to be enough.
APP_LOG_MAX_PAGES = 400
#: The pager walks BACKWARD from the end of the window. If it never reached the
#: start, the oldest row we hold is materially after it and the total is short.
APP_LOG_COVERAGE_TOLERANCE_S = 120


def app_served_mb_for_bucket(key: str, bucket: str) -> tuple[float, int, bool]:
    """Application-served bytes (gunicorn access lines) over a bucket's window.

    This is the ratio's denominator now. Unlike the edge log it includes
    internal service-to-service traffic, which is why it separates the
    anomalous hours and `edge` does not.

    Returns (served_mb, access_lines, covered). `access_lines == 0` is NOT a
    served total of zero, and `covered is False` is not a small total -- the
    caller refuses on both rather than dividing.
    """
    end = dt.datetime.strptime(bucket[:19], "%Y-%m-%dT%H:%M:%S")
    start = end - dt.timedelta(hours=1)
    rows = _logs(
        key, SERVICE_IDS["web"],
        start.strftime("%Y-%m-%dT%H:%M:%SZ"), end.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "app", max_pages=APP_LOG_MAX_PAGES,
    )
    total = 0
    lines = 0
    for _ts, message, _labels in rows:
        match = _ACCESS.match(message.strip())
        if not match:
            continue
        lines += 1
        size_text = match.groups()[4]
        total += int(size_text) if size_text.isdigit() else 0
    covered = True
    if rows:
        oldest = dt.datetime.strptime(rows[0][0][:19], "%Y-%m-%dT%H:%M:%S")
        covered = (oldest - start).total_seconds() <= APP_LOG_COVERAGE_TOLERANCE_S
    return total / 1048576, lines, covered


def arm_a_verdict(metered: float, edge_mb: float, edge_requests: int,
                  served_mb: float, access_lines: int, covered: bool,
                  spike_mb: float, spike_app_ratio: float) -> tuple[str, str, float | None]:
    """The arm A gate, as a PURE function so it can be scored off captures.

    It lives outside the poll loop deliberately: a predicate that only exists
    inline can only ever be tested by a paraphrase of itself, and
    `scripts/score_arm_a_gate.py` scores THIS function against all 23 captured
    hours -- positive and negative -- rather than a restatement.

    Returns (decision, reason, metered_over_app). Decision is one of
    "ARM_A", "not a spike", "UNDECIDABLE", "under MB bar".
    """
    if metered < spike_mb:
        return "under MB bar", f"metered {metered:.1f} MB < {spike_mb}", None
    # REFUSE WHEN THE APP LOG IS BLIND -- DO NOT FALL BACK TO THE EDGE RATIO
    # (`learnings.md`: unknown must not default permissive). web's access-line
    # emitter was structurally dead from 2026-09-08T23:45:58Z until it was
    # restored at 2026-09-09T14:38Z, and one hour already in the captured set --
    # `09-09 01:00Z`, over 300 MB -- has no readable app number at all. Zero
    # access lines against a NON-EMPTY edge log is the discriminator: it
    # separates "nothing was served" from "nobody wrote it down". Falling back
    # to `metered/edge` here would reinstate exactly the bar this switch
    # removed, in precisely the hours where it is least trustworthy.
    if access_lines == 0 and edge_requests > 0:
        return "UNDECIDABLE", "app log blind (0 access lines against a non-empty edge log)", None
    if served_mb <= 0:
        return "UNDECIDABLE", "no app-served bytes to divide by", None
    if not covered:
        return ("UNDECIDABLE",
                "app log page budget exhausted -- denominator is truncated, "
                "which would inflate the ratio", None)
    ratio = metered / served_mb
    if ratio >= spike_app_ratio:
        return "ARM_A", f"metered/app {ratio:.2f} >= {spike_app_ratio}", ratio
    return "not a spike", f"metered/app {ratio:.2f} < {spike_app_ratio}", ratio


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
                        help="RECORDED, NOT GATING since 2026-09-10: metered / edge-logged "
                             "MB. Scored over 19 captured hours it OVERLAPS (10.23-33.58 "
                             "anomalous vs 0.52-20.59 ordinary), so it cannot decide.")
    parser.add_argument("--spike-app-ratio", type=float, default=DEFAULT_SPIKE_APP_RATIO,
                        help="THE GATE: metered / app-served MB over the same window. "
                             "Anomalous hours run 8.20-16.84, ordinary 0.35-3.05. Refuses "
                             "(does not fire) when the app access log is blind.")
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
        "spike_app_ratio": args.spike_app_ratio,
        "gate": "metered/app-served (edge ratio recorded, not gating) [switched 2026-09-10]",
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
            served, access_lines, covered = app_served_mb_for_bucket(key, bucket)
            edge_ratio = metered / edge if edge > 0 else float("inf")
            poll.update({"edge_mb": round(edge, 2), "edge_requests": requests,
                         "metered_over_edge": round(edge_ratio, 2),
                         "app_served_mb": round(served, 2), "access_lines": access_lines,
                         "app_log_covered": covered})
            decision, reason, ratio = arm_a_verdict(
                metered, edge, requests, served, access_lines, covered,
                args.spike_mb, args.spike_app_ratio,
            )
            poll["ratio_verdict"] = reason
            if ratio is not None:
                poll["metered_over_app"] = round(ratio, 2)
            _say(f"   over {args.spike_mb} MB: app-served {served:.1f} MB / {access_lines} lines "
                 f"-> {decision} ({reason}); edge {edge:.1f} MB / {requests} reqs, edge ratio "
                 f"{edge_ratio:.2f}, NOT gating")
            if decision == "UNDECIDABLE":
                poll["decision"] = "UNDECIDABLE"
                _say("   refusing -- NOT falling back to the edge ratio")
                record["polls"].append(poll)
                out.write_text(json.dumps(record, indent=2, sort_keys=True), encoding="utf-8")
                if args.dry_run:
                    break
                time.sleep(args.poll_minutes * 60)
                continue
            if decision == "ARM_A":
                poll["decision"] = "ARM_A"
                record["polls"].append(poll)
                _say(f"SPIKE DETECTED: {bucket} {metered:.1f} MB -- {reason} -- arm A")
                if args.dry_run:
                    record["fired"] = {"arm": "A", "dry_run": True}
                    break
                record["fired"] = fire("A", args.arm_a_mb, skip_quiet=True, key=key, watch=False)
                break

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
