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
