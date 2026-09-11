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

**LAG SCAN (addendum, landed after the first commit) — PEAK AT -4 MIN, NOT -60.** All 180
same-bucket poll intervals across the three watcher records (1,101.6 MB of metered
increments), each correlated against served bytes in the same window shifted by every lag
from -70 to +5 min. The per-second logs were complete, with no truncated hour: 1,310.1 MB of
app-served bytes and 483.3 MB of edge.

| lag | r (app-served) | r (edge) |
|---|---|---|
| **-4 min** | **0.488** | 0.502 |
| -3 | 0.458 | 0.498 |
| -2 | 0.423 | **0.510** |
| -1 | 0.454 | 0.500 |
| 0 | 0.411 | 0.482 |
| -58 / -60 / -62 | 0.155 / 0.154 / 0.205 | 0.173 / 0.132 / 0.125 |

The five best lags are all between -4 and 0 min. The -60 min that an end-labelled bucket
with a one-hour replay would need scores about a third of that. **A bandwidth bucket fills
with its OWN hour's traffic, 1-4 minutes behind real time.** r ~0.5 rather than higher is
expected from 4-minute polls against bursty traffic; the peak's POSITION is the result.

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

## 8. ACTED ON, the same day — addendum `[2026-09-10 ~20:2xZ, lane tripwire-bucket-window, CLOSED]`

The user directed every item in §7. All of them are done:

- **Tripwire window** → `label..label+1h`, in `a5ef5d84`. It also flags an access-log emitter
  that dies or comes back INSIDE an hour (`instrument_partial`), and adds `--rederive`. The
  primary tree's untracked copy, which the scheduled task runs, was updated and hash-checked,
  and a `--check` ran from there.
- **All 23 committed captures re-derived** on their own hour. Each keeps its old numbers under
  `rederived.prior`, and the five null `metered_mb` values are filled. Both of the lane's
  falsification tests passed:
  `09-04 18:00Z` edge 2.63 MB / 131 reqs → **178.16 MB / 1,366**, and `09-08 20:00Z` edge
  253.26 → **29.19 MB** (the run's edge flow collapses in the same hour as the meter). Flags now
  carried: `09-08 23:00Z` PARTIAL (the emitter died at 23:45:58Z inside it); `09-09 00:00Z`,
  `01:00Z`, `09:00Z` and `13:00Z` BLIND.
- **Arm 2 gate denominator** → the bucket's own hour so far, in `d536173e`; the watcher was
  restarted at 17:06:22Z.
- **Reader** `ba6383b9`; **probe label and arm 1 re-read** `e080f97c`. Arm 1's P3 coefficient
  is 1.655-1.719x, not 1.516-1.575x; its P1 is unchanged.
- **The tripwire task's trap text** was rewritten.

**`score_arm_a_gate.py` on the corrected captures: the SAME five fires** — 09-08 00, 16, 17,
18, 19Z at m/app 5.10 / 7.78 / 8.62 / 8.30 / 9.41. Ordinary hours now run up to **3.92**
(`09-09 23:00Z`, was 2.32), so the margin under the 5.0 bar is narrower. The script exits 1
on two rows of its EXPECTED table. Both are artefacts of the table, not of the gate, and the
table is left unedited:
`09-09 00:00Z` is now UNDECIDABLE, because its real hour sits inside the access-log outage;
and `09-04 18:00Z` is scored for the first time (m/app 2.79, "not a spike").

**The result that matters most here: the investigation's headline hour is not anomalous on
the app ratio.** `09-04 18:00Z` metered 4,050.1 MB and, correctly paired, served **1,452.38 MB**
in its own hour through the app log (178.16 MB of it at the edge). m/app 2.79 sits inside the
ordinary range (up to 3.92). "4,050 MB against 2.6 MB of public traffic" was the pairing error,
start to finish. **The 2026-09-08 run is now the only anomalous set in the captures.**
**What would falsify that:** none of the other nine 09-01..04 spike buckets is captured.
Capturing them (Render's logs still reach 09-01) would show whether `09-04 18:00Z` is typical
of that week or the exception.

## 9. The other nine 09-01..04 spike buckets, captured — addendum `[2026-09-11 ~15:5xZ, lane sept-spike-captures, CLOSED]`

User directed: "capture the other nine 09-01..04 spike buckets". Together with `09-04 18:00Z`,
they are the metered top ten of 09-01..04, holding 70.8% of that period's 19.24 GB: the
ledger's "~68% in about ten spike buckets". Each was captured on its own hour. `capture()` was
called with the bucket's metered value, because `--capture` leaves it null. All nine are
clean: no BLIND or PARTIAL flag, no deploy in any window, and both workers flat at 6-63 MB, so
web-only as before. The lane's falsification test was written before any number was read.

| bucket | metered MB | edge MB / reqs | app-served MB | **m/app** | metered/edge | publish-in MB |
|---|---|---|---|---|---|---|
| 09-01 22:00Z | 1,774.8 | 61.08 / 223 | 2,707.25 | **0.66** | 29.1 | 1,158.9 |
| 09-01 23:00Z | 2,809.1 | 144.45 / 235 | 4,865.53 | **0.58** | 19.4 | 1,142.5 |
| 09-03 20:00Z | 632.2 | 236.79 / 1,241 | 3,748.17 | **0.17** | 2.7 | 1,934.1 |
| 09-03 21:00Z | 356.4 | 77.61 / 778 | 1,556.27 | **0.23** | 4.6 | 926.6 |
| 09-03 22:00Z | 937.0 | 283.67 / 408 | 3,794.61 | **0.25** | 3.3 | 1,158.0 |
| 09-03 23:00Z | 562.8 | 178.16 / 412 | 2,953.30 | **0.19** | 3.2 | 1,245.7 |
| 09-04 00:00Z | 914.1 | 226.19 / 306 | 3,558.06 | **0.26** | 4.0 | 1,594.2 |
| 09-04 01:00Z | 1,006.9 | 148.90 / 434 | 2,797.53 | **0.36** | 6.8 | 1,605.6 |
| 09-04 18:00Z *(§8)* | 4,050.1 | 178.16 / 1,366 | 1,452.38 | **2.79** | 22.7 | see capture |
| 09-04 19:00Z | 901.1 | 46.78 / 160 | 1,625.35 | **0.55** | 19.3 | 1,513.7 |

**Verdict against the pre-registered test: the SECOND branch.** All nine read m/app at or
below 0.66. Early September's "spikes" were HEAVY SERVED TRAFFIC: 1.5-4.9 GB an hour through
web's app log, nearly all of it internal (the edge carried 47-284 MB). And the meter charged
LESS than that served traffic in every one of those hours. The 09-08 run is the opposite: modest
served traffic, ~300 MB an hour, metered 5.1-9.4x ABOVE it. **The 09-08 run stands alone.**
`09-04 18:00Z` is the outlier of its own week, the only hour above 1x.

**What this does NOT settle.** The meter is still 2.7-29x the edge bytes, so it counts some
share of internal traffic, but that share has no stable ratio (m/app 0.17-0.66). Publish-in
(worker POST bodies, invisible to every response count) ran 0.9-1.9 GB an hour and does not
track the meter either. No mechanism is proposed from this.

**ELIMINATED entries in `state_worker.md` `[render-egress-spikes]` that quote spike-hour numbers
from the OLD pairing.** They are listed with corrected values and NOT rewritten; whether each
elimination still stands is the user's call.

| entry | as recorded (hour BEFORE the label) | correctly paired (the bucket's own hour) |
|---|---|---|
| public edge traffic | "carries 2.6-61 MB in the spike hours" | 46.8-283.7 MB across the ten; `09-04 18:00Z` 178.16 MB, `09-01 23:00Z` 144.45 MB. Its completeness half (edge log vs `http-requests`, 223 vs 221) compared two END-labelled views and is unaffected. Metered/edge is 2.7-29x, so edge still cannot be the whole meter. |
| internal worker<->web HTTP | "matches the meter in ONE spike hour and contradicts it in two others" | App-served exceeds metered in 9 of the 10 early-September hours (m/app 0.17-0.66) and is below it in `09-04 18:00Z` (2.79) and every 09-08 run hour (5.10-9.41). Which three hours the old entry compared is not recorded, so its "one match" cannot be re-scored. |
| bootstrap disk sync | "the 4,050 MB hour had 37 bootstrap lines" | Counted over 17:00-18:00, the hour BEFORE that bucket. Its own hour, 18:00-19:00, was not recounted here. |
| the unresolved contradiction | "09-01 22:00-23:00 served 2,707 / metered 2,809 (1.04)" | 22:00-23:00 is bucket `09-01 22:00Z` = 1,774.8 MB: served/metered **1.53** (m/app 0.66). |
| the unresolved contradiction | "09-04 17:00-18:00 served 699 / metered 4,050 (0.17)" | 4,050 MB is 18:00-19:00, against 1,452.38 MB served: served/metered **0.36** (m/app 2.79). 17:00-18:00 is the 21 MB bucket. |
