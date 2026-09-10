"""Read the bucket a controlled transfer landed in, and score the pre-registered predictions.

Pairs with `controlled_transfer_probe.py`. That script put a KNOWN number of
bytes through web's public edge; this one reads back the three numbers that the
`[render-egress-spikes]` contradiction is between, over the bandwidth bucket
labelled with the hour the transfer ran in:

  P1  the EDGE log's count and bytes for requests we know we made
  P2  the APP log's size field for those same requests
  P3  the bucket's metered MB against the known volume

WHAT MAKES THIS SCORABLE RATHER THAN SUGGESTIVE. Every probe request carries a
unique `ctprobe` token and a dedicated user agent, so its bytes are separable
from the background inside the same hour -- and the probe recorded exactly how
many it sent and how many bytes came back. A log that under-reports THOSE is
under-reporting something we counted independently.

A BANDWIDTH BUCKET IS LABELLED BY ITS HOUR'S START. Bucket `X:00` holds the
bytes of `X:00..(X+1):00` (`.syndicate/findings_2026-09-10_spike_crossing_and_labelling.md`).
Until 2026-09-10 this read the bucket labelled with the hour AFTER the transfer:
the log window was still the transfer's own hour, so P1 and P2 were read over
the right hour, but P3 took the meter of the FOLLOWING hour. A re-read keeps the
earlier reading under `superseded` rather than overwriting it.

TRAP THE CALLER CANNOT SKIP: a bucket keeps growing for ~60 minutes after its
label -- its own hour filling in -- and a fresh low reading is INCOMPLETE, not
low. This refuses to score P3 until the bucket's LABEL is at least
`--settle-minutes` old, and prints the unsettled value as informational only.

    py -3 scripts/controlled_transfer_read.py reports/bandwidth_spikes/controlled_transfer_<stamp>.json
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from scripts.bandwidth_tripwire import (  # noqa: E402
    SERVICE_IDS, _ACCESS, _CLIENT_IP, _RESP_BYTES, _USER_AGENT, _api_key, _logs, _metric,
)

PROBE_UA = "syndicate-controlled-transfer/1.0"
SETTLE_MINUTES = 70


def _bucket_for(when: str) -> str:
    """The bandwidth bucket holding the moment `when`: the hour it falls in.

    A bandwidth bucket is labelled by its hour's START. This returned that label
    PLUS ONE HOUR until 2026-09-10, which is the `http-requests` metric's
    convention, not bandwidth's. `controlled_transfer_probe.py` still records its
    own end-labelled `bucket_label`; that file is claimed by lane
    `bandwidth-controlled-transfer` and was NOT changed here. This reader never
    uses that field -- it derives the bucket from the transfer's own timestamps.
    """
    moment = dt.datetime.strptime(when[:19], "%Y-%m-%dT%H:%M:%S")
    return moment.replace(minute=0, second=0, microsecond=0).strftime("%Y-%m-%dT%H:00:00Z")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("transfer_json")
    parser.add_argument("--settle-minutes", type=int, default=SETTLE_MINUTES)
    args = parser.parse_args()

    transfer = json.loads(Path(args.transfer_json).read_text(encoding="utf-8"))
    started = transfer["transfer_started_at"]
    ended = transfer["transfer_ended_at"]
    bucket = _bucket_for(started)
    if _bucket_for(ended) != bucket:
        print(f"WARNING: transfer straddles buckets ({_bucket_for(started)} .. {_bucket_for(ended)})")
    window_start = dt.datetime.strptime(bucket[:19], "%Y-%m-%dT%H:%M:%S")
    window_end = window_start + dt.timedelta(hours=1)
    start_s = window_start.strftime("%Y-%m-%dT%H:%M:%SZ")
    end_s = window_end.strftime("%Y-%m-%dT%H:%M:%SZ")

    sent = transfer["requests_200"]
    known_body = transfer["known_bytes"]
    known_edge = transfer.get("known_edge_basis_bytes", known_body)
    print(f"transfer  {started} .. {ended}   {sent} x 200")
    print(f"          body {known_body/1048576:.3f} MB | edge basis {known_edge/1048576:.3f} MB")
    print(f"bucket    {bucket}  covers {start_s} .. {end_s}")

    key = _api_key()

    # --- the meter -------------------------------------------------------
    now = dt.datetime.utcnow()
    age_min = (now - window_start).total_seconds() / 60
    values = _metric(
        key, "bandwidth", SERVICE_IDS["web"],
        (window_start - dt.timedelta(hours=3)).strftime("%Y-%m-%dT%H:00:00Z"),
        now.strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    metered = values.get(bucket)
    settled = age_min >= args.settle_minutes
    print(f"\n== METER  bucket label is {age_min:.0f} min old "
          f"({'SETTLED' if settled else 'UNSETTLED -- informational only'})")
    for b in sorted(values):
        mark = "  <-- transfer" if b == bucket else ""
        print(f"   {b}  {values[b]:9.2f} MB{mark}")

    # --- the logs --------------------------------------------------------
    edge = _logs(key, SERVICE_IDS["web"], start_s, end_s, "request")
    mine_edge_bytes = 0
    mine_edge_count = 0
    other_edge_bytes = 0
    other_edge_count = 0
    others: dict[str, list] = defaultdict(lambda: [0, 0])
    for _ts, message, _labels in edge:
        size_match = _RESP_BYTES.search(message)
        size = int(size_match.group(1)) if size_match else 0
        ua_match = _USER_AGENT.search(message)
        ua = ua_match.group(1) if ua_match else "?"
        if PROBE_UA in ua:
            mine_edge_bytes += size
            mine_edge_count += 1
        else:
            other_edge_bytes += size
            other_edge_count += 1
            ip_match = _CLIENT_IP.search(message)
            who = f"{ip_match.group(1) if ip_match else '?'} | {ua[:45]}"
            others[who][0] += size
            others[who][1] += 1

    app = _logs(key, SERVICE_IDS["web"], start_s, end_s, "app")
    mine_app_bytes = 0
    mine_app_count = 0
    app_total = 0
    for _ts, message, _labels in app:
        match = _ACCESS.match(message.strip())
        if not match:
            continue
        _ip, _method, path, _status, size_text = match.groups()
        size = int(size_text) if size_text.isdigit() else 0
        app_total += size
        if "ctprobe=" in path:
            mine_app_bytes += size
            mine_app_count += 1

    print(f"\n== P1  EDGE log vs what we know we sent")
    print(f"   sent (200s)            {sent}")
    print(f"   edge lines with our UA {mine_edge_count}   "
          f"({mine_edge_count - sent:+d})")
    print(f"   edge bytes             {mine_edge_bytes:,} = {mine_edge_bytes/1048576:.3f} MB")
    print(f"   known edge basis       {known_edge:,} = {known_edge/1048576:.3f} MB")
    if known_edge:
        print(f"   edge / known           {mine_edge_bytes / known_edge:.4f}")
    print("   VERDICT: " + (
        "edge log ACCOUNTS for the probe -- log-incompleteness FALSIFIED at this rate"
        if mine_edge_count == sent and abs(mine_edge_bytes - known_edge) <= max(known_edge * 0.02, 4096)
        else "edge log DOES NOT match what we sent -- see the numbers above"))

    print(f"\n== P2  APP log for the same requests")
    print(f"   access lines with ctprobe {mine_app_count}")
    print(f"   bytes they report         {mine_app_bytes:,}")
    print(f"   whole-hour app served     {app_total/1048576:.3f} MB")

    print(f"\n== P3  METER vs known volume")
    print(f"   background edge (not ours) {other_edge_bytes/1048576:.3f} MB over {other_edge_count} reqs")
    for who, (b, c) in sorted(others.items(), key=lambda kv: -kv[1][0])[:5]:
        print(f"      {b/1048576:8.3f} MB  {c:4d}  {who}")
    total_edge = mine_edge_bytes + other_edge_bytes
    print(f"   whole-hour edge total      {total_edge/1048576:.3f} MB")
    if metered is None:
        print("   metered: NO VALUE for this bucket yet")
    else:
        print(f"   metered                    {metered:.2f} MB"
              f"{'' if settled else '  (UNSETTLED -- do not score)'}")
        if settled:
            print(f"   metered / known (ours)     {metered / (known_edge/1048576):.4f}")
            print(f"   metered / whole-hour edge  {metered / max(total_edge/1048576, 1e-9):.4f}")
            print("   NOTE: 'metered / known' is only the meter's coefficient on OUR bytes if the "
                  "background is small; read it beside the background line above.")

    reading = {
        "transfer": args.transfer_json,
        "bucket": bucket,
        "window": {"start": start_s, "end": end_s},
        "labelling": "bandwidth bucket labelled by its hour's START (corrected 2026-09-10)",
        "bucket_age_minutes": round(age_min, 1),
        "settled": settled,
        "metered_mb": metered,
        "sent_200": sent,
        "known_body_bytes": known_body,
        "known_edge_basis_bytes": known_edge,
        "edge": {"ours_count": mine_edge_count, "ours_bytes": mine_edge_bytes,
                 "background_bytes": other_edge_bytes, "background_count": other_edge_count,
                 "hour_total_bytes": total_edge},
        "app": {"ours_count": mine_app_count, "ours_bytes": mine_app_bytes,
                "hour_served_bytes": app_total},
        "neighbour_buckets": values,
    }
    out = Path(args.transfer_json).with_name(
        Path(args.transfer_json).stem + "_reading.json")
    # A reading of a DIFFERENT bucket is evidence, not a draft: ledger entries
    # quote it. Keep it rather than overwrite it.
    if out.exists():
        try:
            previous = json.loads(out.read_text(encoding="utf-8"))
        except ValueError:
            previous = None
        if isinstance(previous, dict) and previous.get("bucket") != bucket:
            reading["superseded"] = previous
            print(f"   (earlier reading of bucket {previous.get('bucket')} kept under `superseded`)")
    out.write_text(json.dumps(reading, indent=2, sort_keys=True), encoding="utf-8")
    print(f"\n-> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
