# Bandwidth buckets are labelled by the hour's START, request counts by its END — and how early real spikes cross 300 MB

`[lane bandwidth-controlled-transfer, session 92a71e78, 2026-09-10 ~14:30-15:20Z; user: "measure how early real spikes cross 300 MB"]`
Subject: `state_worker.md [render-egress-spikes]`. **Measurement and direct observation. No code changed, no deploy, no bytes sent.**

## 0. Headline

1. **Real spikes cross 300 MB in the first 6-11 minutes of the hour** (1,660-2,963 MB buckets).
   The 300 MB bar is never what delays arm A. The RATIO bar is (section 5).
2. **Answering that exposed a labelling error the whole `[render-egress-spikes]` record rests
   on.** Render's `bandwidth` bucket `X:00` holds the traffic of `X:00-(X+1):00`.
   `http-requests` bucket `X:00` holds `(X-1):00-X:00`. The ledger established
   "RIGHT-labelled" against REQUEST COUNTS (true) and applied it to BANDWIDTH (false).
   Every tripwire capture has paired a metered hour with the logs of the hour BEFORE it.

## 1. Direct observation — same instant, both metrics, the hour in flight

Read at **15:13:07Z**, 13 min into wall hour 15:00, in ONE script run:

| source | this hour so far | previous hour |
|---|---|---|
| edge log | 35 reqs / 18.5 MB | 233 reqs / 101.1 MB |
| `http-requests` | bucket **`16:00Z` = 35** | bucket `15:00Z` = 231 |
| `bandwidth` | bucket **`15:00Z` = 16.7 MB** | bucket `14:00Z` = 87.7 MB |

The same hour is filed under `16:00Z` by one metric and `15:00Z` by the other.

**And against a known event.** Arm 1 sent 2,596 requests at 2026-09-09 00:06-00:29Z. The
`http-requests` metric carries them in bucket **`01:00Z` = 2,764**, and its neighbours
match the edge log's WALL-hour counts shifted by one (`00:00Z`=372 vs wall 23:00 366;
`02:00Z`=374 vs wall 01:00 365; `03:00Z`=199 vs wall 02:00 200). So the request metric
IS right-labelled, exactly as `state_worker.md` says ("confirmed twice against request
counts"). That check was sound. It was then applied to a different metric.

## 2. Timing evidence for bandwidth (independent of the direct read)

**The "settle" curves are the hour filling in.** Every poll of the three arm-2 watcher
records of 2026-09-10 (184 polls), partial / final by minutes after the label: flat while
the hour is quiet, then jumps — `13:00Z` sat at 4% from minute 6 to 38 and was 77% by 46;
`11:00Z` 1% until 46, 82% at 50. Each bucket appears ~5-6 min after its label at ~0 MB
and reaches ~99% at minute 57-62.

**The jumps land in the same wall-clock minutes as served bursts, not an hour earlier.**

| bucket | metered jump | served, same minutes | served, 60 min earlier |
|---|---|---|---|
| `13:00Z` | +57.3 MB, 13:38-13:46 | 28.6 MB (13.7 in 13:40 alone) | 10.7 MB, spread |
| `12:00Z` | +21.4 MB, 12:10-12:26 | edge 12.7 MB, burst 12:11-12:15 | edge 0.0 MB |

**The 2026-09-08 run's boundaries.** Edge per 10 min: wall 16:00-20:00 is a flat
~35-70 MB per bin; it starts sharply at 16:00 (48.4 MB) and collapses at ~20:05 (14.4 MB
in 20:00-20:10, then 0.1-7.4). Start-labelled, buckets `16:00Z`-`19:00Z` (2,471-2,963 MB)
ARE that block, and `20:00Z` = 220.7 MB is ~4.6 min at the run's ~48 MB/min. End-labelled,
the meter would start AND stop exactly one hour before the edge flow, at both ends.

**LAG SCAN — supplementary, still running at time of writing; see addendum.** ~180
same-bucket poll intervals, metered delta vs served bytes shifted by every lag -70..+5 min.

## 3. The ratio evidence, and why it is WEAK

Ratios of metered to edge-log bytes are what the ledger reasoned with, so they were checked
— but they cannot decide labelling on their own: **the meter can read BELOW the edge log**
(`14:00Z` today: 87.7 metered against 101.1 MB edge). With response gzip on since 09-05, the
log's byte field and the wire bytes need not agree, and the gap depends on the traffic mix.
For the record: start-paired, the arm-1 night reads 1.28-1.81 m/edge from 22:00 to 03:00;
end-paired it swings 0.62-3.56. Suggestive only.

## 4. The headline numbers that came from the wrong pairing

| bucket | metered | edge, hour BEFORE label (ledger) | edge, hour AFTER label (its own hour) |
|---|---|---|---|
| 09-04 18:00Z | 4,050.1 | **2.6 MB / 131 reqs** | **178.2 MB / 1,366 reqs** |
| 09-01 23:00Z | 2,809.1 | 61.1 / 223 | 144.5 / 235 |
| 09-01 22:00Z | 1,774.8 | 44.2 / 259 | 61.1 / 223 |
| 09-04 01:00Z | 1,006.9 | 226.2 / 306 | 148.9 / 434 |
| 09-03 22:00Z | 937.0 | 77.6 / 778 | 283.7 / 408 |
| 09-04 00:00Z | 914.1 | 178.2 / 412 | 226.2 / 306 |

- **"4,050 MB in a single hour against 2.6 MB of public traffic"** — the investigation's
  headline — is the pairing. Its own hour carried 178.2 MB over 1,366 requests. Still ~23x
  metered-over-edge, so the spike stays anomalous; "an hour with almost no traffic" dies.
- **`findings_2026-09-08_egress_run_boundaries.md`: "nothing in any log started it, and
  nothing in any log stopped it"** — reversed. Correctly paired, the dominant logged edge
  flow (which that file identifies as the export pollers) switches on at 16:00 and off at
  ~20:05 WITH the meter.
- **"ELIMINATED: the export pollers"** rested on their running "at FULL RATE straight
  through the stop" — true of the hour BEFORE the stop. This is the new evidence the
  tripwire's "do not re-propose" rule asks for. NOT re-proposed here as the driver: in run
  hours the meter is still ~11x the logged edge bytes, and that multiplier is unexplained.
- **Arm 1's P3** read bucket `01:00Z` (401.1). The transfer's own hour is `00:00Z` (437.7
  against 241.5 MB edge). The coefficient built on it needs re-deriving on the right bucket.

## 5. The answer: how early real spikes cross 300 MB

Under either labelling the watcher sees a partial value climbing as that bucket's hour
arrives, so this part stands on its own. Assumed: bytes arrive evenly through the hour (the
09-08 edge profile is flat to within ~30%; 16:00-17:00 is front-loaded, which only makes
crossing earlier), 2-5 min reporting lag, 4-min polls. Denominator as coded: app-served
over label-1h..label.

| bucket | final MB | crosses 300 MB | reaches 5x served | earliest fire | verdict |
|---|---|---|---|---|---|
| 09-08 16:00Z | 2,470.7 | min 7.3 | min 17.8 | 19.8-26.8 | **fires in-hour** |
| 09-08 00:00Z | 1,660.8 | min 10.8 | min 26.7 | 28.7-35.7 | in-hour only on a lucky poll phase |
| 09-08 17:00Z | 2,962.7 | min 6.1 | min 32.2 | 34.2-41.2 | **deferred** past the 1,600 s guard |
| 09-08 18:00Z | 2,817.1 | min 6.4 | min 36.6 | 38.6-45.6 | **deferred** |
| 09-08 19:00Z | 2,904.8 | min 6.2 | min 35.1 | 37.1-44.1 | **deferred** |
| 420-927 MB hours | | min 19-43 | never | — | never fires |

- **The 300 MB bar is never binding for a real spike.** The ratio bar is: it divides a
  PARTIAL hour of meter by a FULL hour of served bytes — and, given section 1, the full hour
  it divides by is the PREVIOUS one. A run's first hour clears it early (the hour before was
  quiet); mid-run hours carry ~320-345 MB of served bytes and only reach 5x at minute 32-37.
- The watcher stops at its first fire, so a run like 09-08's would be caught in its first
  hour, at ~minute 20-27, **with the transfer landing inside the spike hour itself** — the
  in-flight bucket IS the current hour. That is better than §3 of the arm-2 pre-registration
  assumed ("current hour on the previous hour's evidence").
- **Correction to this lane's 14:17Z entry:** it said a deferred fire "can land TWO hours
  after the hour that triggered it". Under start-labelling a deferred fire lands in the NEXT
  hour — one hour, not two.

Not measured, and only a live spike can measure it: the within-hour arrival of a real spike's
metered bytes. The restarted watcher (`8e04ddf3`) records `arm_a` on every poll.

## 6. Pre-registration outcome

Written to a timestamped scratch file before computing (no bytes sent, so a scratch file
stood in for a ledger push). Predicted: a "roughly linear settle over ~50 min", big spikes
crossing by minute ~10-15. **The framing was wrong** — there is no settle, only the hour
filling in. **The number held** (6-11 min), for a reason the prediction did not have.

## 7. NOT acted on — each needs the user's decision

- `bandwidth_tripwire.py` window (`label-1h..label`) → should be `label..label+1h`. Every
  committed capture's edge / app / publish-in numbers are from the hour before its metered
  hour; re-deriving them is a re-read of logs Render still holds (09-01 is still readable).
- Arm 2's gate denominator is the previous hour's served bytes. The consistent denominator is
  served bytes in the bucket's own hour SO FAR.
- `score_arm_a_gate.py`'s five-hour separation was scored on the shifted pairing.
- The tripwire task's instrument trap 1 ("do not correct it") was written on the wrong fact.

**What would settle labelling beyond the same-instant read:** a small known transfer at a
known minute. It puts bytes on the bill, and section 1 makes it unnecessary.
