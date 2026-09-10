# The metered/edge LADDER is a ratio artifact — `metered - edge` separates cleanly

`[2026-09-09 19:1x local / 2026-09-10 00:1xZ, session local_7fa9d375, scheduled task
bandwidth-spike-tripwire. Handed to lane bandwidth-controlled-transfer. NOT written by
the lane owner, and written in a NEW file on purpose: the adopting session's own block
says findings_2026-09-08_controlled_transfer.md is used UNEDITED, so nothing here
touches it.]`

**Why this is a file and not a message.** Neither session that has held this lane is
reachable. `40d9e921` (opener) was already recorded absent from the roster by the third
reader; `1e77a7da` (adopter, 2026-09-09 ~20:0xZ, arm 2 armed) is ALSO absent as of
2026-09-10 00:1xZ — `get_session` not found, `list_sessions` with `include_archived`
does not list it. Writing is the only channel left.

**IT DOES NOT THREATEN ARM 2.** Arm 2's P1 is meter-free by design — unique `ctprobe`
tokens against an independently known request count — so nothing below changes what
that test can conclude. What it bears on is (i) how the FIRED spike hour's metered side
is read afterwards, and (ii) the ratio being used as the fire discriminator.

---

## Why this was computed at all

The tripwire fire of 2026-09-09 23:2xZ found two web buckets over 400 MB in the last
24h — `2026-09-09T00:00Z` at 437.7 MB and `01:00Z` at 401.1 MB — both already captured,
both already on `origin/main`, neither worker over threshold. The user then asked why
the ratio "dropped back to 1.66 today". It did not drop back to anything, and the answer
splits in two.

## (a) 1.66 is the LOWEST metered/edge ever recorded on web, and WE CAUSED IT

The 1.66 hour is `01:00Z` — the arm 1 hour. The probe moved the DENOMINATOR, not the
meter: 2,531 edge requests that hour against 366 in the neighbour. Backing arm 1's known
150.881 MB out of both terms:

| treatment | metered | edge | ratio |
|---|---|---|---|
| as recorded | 401.11 | 241.52 | **1.66** |
| probe bytes metered 1:1, fully logged | 250.23 | 90.64 | **2.76** |
| probe bytes metered 1:1, logged at the 0.9257 rate P1 measured | 250.23 | 101.82 | **2.46** |

Either correction puts the hour WITH its neighbours (`00:00Z` 2.15, `23:00Z` 3.56)
instead of below them.

**A calibration probe depresses this ratio by construction** — it adds bytes that are
fully logged to an hour whose unlogged term is unchanged. **Arm 2 will do it harder.**
Firing 150 MB into an hour shaped like `09-08 16:00Z` takes that hour's ratio from
`2470.7/101.4 = 24.37` to roughly `2620/251 = 10.4` on the meter alone, with no change
whatever in the phenomenon. So: the fired spike hour's ratio must NOT be compared
against unfired spike hours without this correction, and the fire gate should read the
ratio of a bucket the probe has not touched.

## (b) Separately, the spike STOPPED — a numerator collapse, unrelated to the probe

Metered fell from 2,400-2,960 MB/h across four `2026-09-08` hours to 401-438 MB/h.
Nothing here explains why. Recorded so the two effects are not conflated — and it is
why arm 2 has not fired yet.

## (c) The "smooth ladder" is at least partly an artifact of a moving denominator

`findings_2026-09-08_controlled_transfer.md` section 4(a) reads the ratios
`1.66 -> 2.15 -> 3.56 -> 10.77 -> 24.37` as "a smooth ladder, not two regimes".
Recomputed over **every** captured web bucket on `2026-09-08..09` — from the capture
JSONs themselves, `metered_mb` and `edge.mb` — with `metered - edge` added:

| bucket | metered | edge | reqs | ratio | **excess** | app served |
|---|---|---|---|---|---|---|
| 09-08 00:00Z | 1660.8 | 49.5 | 213 | 33.58 | 1611.3 | 147.6 |
| 09-08 15:00Z | 420.6 | 59.3 | 348 | 7.09 | 361.3 | 137.8 |
| 09-08 16:00Z | 2470.7 | 101.4 | 449 | 24.37 | 2369.3 | 146.7 |
| 09-08 17:00Z | 2962.7 | 275.0 | 536 | 10.77 | 2687.7 | 317.8 |
| 09-08 18:00Z | 2817.1 | 275.4 | 572 | 10.23 | 2541.8 | 343.7 |
| 09-08 19:00Z | 2904.8 | 245.1 | 417 | 11.85 | 2659.7 | 339.6 |
| 09-09 00:00Z | 437.7 | 203.6 | 366 | 2.15 | 234.2 | 249.2 |
| 09-09 01:00Z | 401.1 | 241.5 | 2531 | 1.66 | 159.6 | 0.0 |

Provenance, because it is not uniform: `09-08 14:00Z` and `20:00Z` carry no
`metered_mb` in their captures and are omitted. `09-08 23:00Z` — 315.35 / 88.48,
excess 226.87 — is quoted from section 4(a)'s own table and NOT recomputed, because
no `web_20260908T230000Z.json` exists. `09-09 01:00Z` shows app served 0.0 because
the access-log emitter was dead, which is why this uses edge throughout and not app.

**The excess column clusters where the ratio column is a continuum:** ~160-235 MB/h in
the three non-spike hours, ~2,370-2,690 MB/h in the four big spikes, with `09-08 01:00Z`
(660.7) and `15:00Z` (361.3) in between. The ratio spreads smoothly from 1.66 to 33.58
only because its own denominator ranges 49 -> 275 MB.

**The two orderings disagree, which is the tell:** `09-08 16:00Z` is the second-highest
ratio and only the fourth-highest excess. And section 4(a)'s ladder tops out at 24.37
while `09-08 00:00Z` reads **33.58** — the top rung was not the top.

## Status: a reframing to TEST, not a result

It assumes edge bytes are metered at ~1x, which is exactly what is unproven; at a true
coefficient of 2x the excesses shrink by one edge-volume and the clustering weakens. It
rests on 8 buckets over two days from one service, only three of them non-spike.

**Falsifier, needing no new bytes on the bill:** the additive read predicts
`metered - edge` is roughly INDEPENDENT of edge volume within normal hours. Capture
several non-spike, non-probe hours whose edge volume differs by 3x or more. If the
excess tracks edge volume it is multiplicative after all and this file is wrong; if it
holds ~200 MB/h across a 3x swing in edge, the ratio framing should be retired from the
ledger in favour of the excess — including from arm 2's fire discriminator.

**Not acted on further.** No lane opened, no lane block edited, no deploy, no probe fired.

---

## RESULT — the falsifier ran. BOTH framings are dead, and a THIRD column separates cleanly

`[2026-09-09 ~19:5x local / 2026-09-10 ~00:5xZ, lane bandwidth-excess-vs-ratio, session
local_7fa9d375. Nine quiet hours captured for this, spanning metered 0.41 -> 315.35 MB
and edge 0.02 -> 135.77 MB — a 6,000x swing in edge, far past the 3x the falsifier asked
for. Deploy-adjacent hours (2026-09-09 14:00Z/15:00Z/16:00Z, web env redeploy 14:38Z and
ship-forward 15:05Z) and both arm-1 probe hours EXCLUDED by name. Read-only: no bytes sent.]`

### The table — every captured web bucket, 2026-09-08..09

| bucket | metered | edge | reqs | m/edge | excess | app served | m/app |
|---|---|---|---|---|---|---|---|
| 09-08 00:00Z | 1660.78 | 49.45 | 213 | 33.58 | 1611.33 | 147.60 | 11.25 |
| 09-08 01:00Z | 927.21 | 266.49 | 407 | 3.48 | 660.72 | 325.79 | 2.85 |
| 09-08 15:00Z | 420.55 | 59.29 | 348 | 7.09 | 361.26 | 137.75 | 3.05 |
| 09-08 16:00Z | 2470.66 | 101.39 | 449 | 24.37 | 2369.27 | 146.71 | 16.84 |
| 09-08 17:00Z | 2962.71 | 275.03 | 536 | 10.77 | 2687.68 | 317.75 | 9.32 |
| 09-08 18:00Z | 2817.15 | 275.39 | 572 | 10.23 | 2541.76 | 343.74 | 8.20 |
| 09-08 19:00Z | 2904.79 | 245.13 | 417 | 11.85 | 2659.66 | 339.55 | 8.55 |
| 09-08 21:00Z | 78.19 | 29.19 | 211 | 2.68 | 49.00 | 112.58 | 0.69 |
| 09-08 22:00Z | 136.33 | 18.33 | 356 | 7.44 | 118.00 | 97.82 | 1.39 |
| 09-08 23:00Z | 315.35 | 88.48 | 285 | 3.56 | 226.87 | 176.36 | 1.79 |
| 09-09 00:00Z | 437.73 | 203.57 | 366 | 2.15 | 234.16 | 249.16 | 1.76 |
| 09-09 01:00Z | 401.11 | 241.52 | 2531 | 1.66 | 159.59 | — | — |
| 09-09 09:00Z | 0.41 | 0.02 | 66 | **20.59** | 0.39 | — | — |
| 09-09 13:00Z | 12.47 | 3.54 | 130 | 3.52 | 8.93 | — | — |
| 09-09 18:00Z | 110.38 | 122.41 | 445 | **0.90** | **-12.03** | 186.50 | 0.59 |
| 09-09 20:00Z | 62.72 | 121.40 | 480 | **0.52** | **-58.68** | 179.13 | 0.35 |
| 09-09 21:00Z | 180.51 | 60.73 | 105 | 2.97 | 119.78 | 141.17 | 1.28 |
| 09-09 22:00Z | 257.36 | 135.77 | 481 | 1.90 | 121.59 | 247.96 | 1.04 |
| 09-09 23:00Z | 605.10 | 178.28 | 389 | 3.39 | 426.82 | 261.01 | 2.32 |

`app served` is blank where web's access-log emitter was dead (`2026-09-08T23:45:58Z` to
the restore at `2026-09-09T14:38Z`); the tool marks those `instrument_blind` rather than
printing a number. `09-08 14:00Z` and `20:00Z` are omitted — their captures carry no
`metered_mb`. **`09-08 23:00Z` is now RECOMPUTED, not quoted: 88.48 MB / 315.35 metered,
matching section 4(a)'s table exactly.**

### 1. Additive is dead — TWO HOURS HAVE NEGATIVE EXCESS

`09-09 18:00Z` metered **110.38** against **122.41** edge-logged; `09-09 20:00Z` metered
**62.72** against **121.40**. The meter charged LESS than the edge log recorded. Whatever
the meter is doing, `metered = edge + hidden extra` is not it, and that framing should be
retired rather than re-fitted.

### 2. My own r ~ 0 is NOT the confirmation it looks like — this is the trap in this result

Across the nine non-spike hours, `excess` vs `edge` gives **r = +0.049, r2 = 0.002**. Read
carelessly that is "excess is independent of edge volume" — the hypothesis CONFIRMED. It is
not. Excess over those hours runs **-58.68 to +226.87, mean 63.8, sd 89.4** — the spread is
LARGER than the mean. **r ~ 0 with high variance means NO RELATIONSHIP, not a constant
offset.** A constant offset would show r ~ 0 AND small variance; only the second half
distinguishes them, and only the first half is what a correlation reports. The additive
hypothesis is falsified by the variance, and it would have been "confirmed" by the
correlation alone.

For completeness, neither straight fit is any better: `metered ~ edge` gives r2 = 0.301
(n = 9), `metered ~ app-served` r2 = 0.200 (n = 7). **The meter is not a function of either
logged quantity.**

### 3. metered/edge DOES NOT SEPARATE SPIKES — so it is the wrong fire discriminator

Taking the five big anomalous hours (`09-08 00, 16, 17, 18, 19:00Z`, all >= 1,660 MB)
against everything else:

    metered/edge   big  10.23 - 33.58   |   everything else   0.52 - 20.59   OVERLAPS
    metered/app     big   8.20 - 16.84   |   everything else   0.35 -  3.05   SEPARATES

A **near-idle** hour — `09-09 09:00Z`, 0.41 MB metered, 66 requests — sits at **20.59**,
inside the band `09-08 16:00Z` occupies at 2,470 MB. And `09-08 22:00Z` (7.44 at 136 MB)
is indistinguishable from `09-08 15:00Z` (7.09 at 420 MB). **The ratio carries no
information about whether an hour is anomalous.** This directly answers section 4(a): the
"ladder" is not a continuum of one mechanism, it is a ratio whose denominator wanders.

### 4. What to use instead: metered / app-served, now that the emitter is back

`metered/app` separates the five big hours from all twelve others with a clean gap —
**8.20 at the bottom of the anomalous set against 3.05 at the top of the rest**. That is
actionable for arm 2, whose fire gate currently reads the ratio that does not work, and it
became available only today when the access-log emitter was restored at 14:38Z.

**Two honest limits on that recommendation.** (i) `09-08 01:00Z` (2.85) and `15:00Z` (3.05)
are elevated hours sitting just above the quiet maximum of 2.32, so the margin there is
thin — a threshold near **5.0** catches the big five and deliberately does not claim those
two. (ii) app-served is itself the log whose completeness is the open question; a clean
separation makes it a good DISCRIMINATOR and does not make it a validated MEASUREMENT.

### 5. Scope

n = 9 quiet hours, 5 big hours, 12 hours with a live app log, one service, two days. Two of
the negative-excess hours are post-`15:05Z`-deploy — but so are `21:00Z`, `22:00Z` and
`23:00Z`, which are all positive, so it is not a simple post-deploy artifact. Flagged, not
concluded.

**Lane `bandwidth-excess-vs-ratio` closes on this.** No probe fired, no bytes sent, no
deploy, no `render.yaml`, and neither the controlled-transfer lane's files nor its block
were touched.
