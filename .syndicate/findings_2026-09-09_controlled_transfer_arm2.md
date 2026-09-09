# Controlled transfer, ARM 2 — the pre-registration

`[lane bandwidth-controlled-transfer, adopted by session 1e77a7da, 2026-09-09 ~20:0xZ]`

**User decision, 2026-09-09 (scheduled task `bandwidth-spike-tripwire`, then
directly): "do option 2".** Option 2 had already fired once — I found arm 1 on
`origin/main` before building anything, per `learnings.md` 2026-09-07. This file
is the pre-registration for the SECOND arm, written and committed **before** any
byte is sent.

**Lane ownership:** session `40d9e921` does not appear in the session roster
(checked by the third reader 2026-09-09 ~13:5xZ, archived included). Two later
sessions appended readings without adopting. I am adopting it, because this arm
sends bytes rather than reading them back, and an unowned lane cannot answer for
that.

---

## 1. WHAT ARM 1 SETTLED, AND WHAT IT EXPLICITLY DID NOT

Arm 1 (`controlled_transfer_20260909T000627Z`, bucket `2026-09-09T01:00:00Z`,
150.881 MB known over 2,596 requests) calibrated both instruments in a NORMAL
hour, and the lane's own conclusion is that **both are close to true**:

    edge log recorded   0.913-0.919 of requests we knew we made   (P1, ~8% deficit)
    meter charged       1.516-1.575x real delivered bytes         (P3)

Neither is within two orders of the **10.77x** (2026-09-08 17:00Z) and **24.37x**
(16:00Z) that the spike hours need. The lane says so itself: *"A follow-up firing
DURING a live spike is the experiment that would separate the horns; this one
could not, because no spike was running."*

**This is that firing.** Arm 1 is the control it needs.

## 2. WHY P1 IN A SPIKE HOUR IS DECISIVE WITHOUT THE METER

P1 does not use the meter at all. Every request carries a unique `ctprobe` token
and a dedicated UA, so the edge log either accounts for requests we counted
independently, or it does not. Run the SAME transfer in a spike hour:

| edge log records | what it means |
|---|---|
| ~0.92, as in the normal hour | the log does **not** drop lines under spike load. Log incompleteness then cannot explain a 10-24x gap, and the metered bytes **never appeared as edge requests at all** — the second horn dies and the first is forced. |
| materially below 0.92 | the log **does** drop under spike load, and the size of the drop bounds how much of the gap it explains. First direct evidence for that horn at the size required. |

**Arm A is deliberately the SAME VOLUME as arm 1** — 150 MB, ~2,500 requests of
the same incompressible 60,588 B PNG — so spike-vs-normal is the only variable
between the two readings.

## 3. THE TWO ARMS

Spikes cannot be summoned (seven on 09-08, two on 09-09, none since 02:00Z), so
the watcher `scripts/controlled_transfer_arm2_watch.py` carries a fallback.
Whichever fires first ends the watch.

- **ARM A — a spike is running.** Detected from the last bucket Render returns,
  settled or not, at `>= 350 MB`: a partial reading can only grow, and today's
  normal hours settle at 90-175 MB. Fires 150 MB with `--skip-quiet-check`.
  **The bet is that spikes CLUSTER** — 2026-09-08 ran five consecutive hours —
  so firing in the current hour on the previous hour's evidence lands inside the
  episode. If the episode has ended by then, the reading is a normal-hour
  replication of arm 1, and **must be reported as that**, not as arm A.
- **ARM B — a verified-quiet hour, 05:00-11:00Z.** Fires 300 MB, twice arm 1's
  volume. This is the *"second arm at a different volume"* the lane requires
  before anyone acts on the 1.5x coefficient.

## 4. PRE-REGISTERED PREDICTIONS

- **A-P1 (the one that matters).** I predict the edge log records **~0.92 of our
  requests in a spike hour too** — i.e. no material extra loss — because arm 1's
  deficit plateaued under re-paging and looked like a steady sampling loss, not a
  load-dependent one. **If that is right, the log-incompleteness horn is dead as
  an explanation of the spikes** and the remaining explanation is that the meter
  counts bytes that are not edge requests. I am predicting the result that
  closes off the horn my own instrument would otherwise be blamed for.
- **A-P3.** Report the bucket, do **not** compute a coefficient: a spike hour's
  background is the unexplained quantity itself, so `metered - known` is
  uninterpretable. Any coefficient stated from arm A is a reading error.
- **B-P1.** ~0.92 again, replicated at twice the volume. A materially different
  fraction means the deficit is volume-dependent and arm 1's 8% does not
  generalise.
- **B-P3.** Coefficient in **1.45-1.65** if it is volume-invariant. Outside that
  band means there is no coefficient, only per-hour composition — which is what
  the lane's own ladder (1.66 / 2.15 / 3.56 / 10.77 / 24.37) already suggests.
- **Falsifier for the whole watch:** no spike and no quiet window in the band
  means **no reading**. That is to be reported as no reading, not as a null
  result about the meter.

## 5. WHAT IS DIFFERENT FROM ARM 1 BY DESIGN

- **The quiet gate is held for the WHOLE transfer, not the ten minutes before
  it** — the lane's item (c). Arm 1 passed its pre-fire check at 5.493 MB and the
  hour still ended 43% background, because the board came back at ~00:2xZ. Arm B
  samples non-probe edge bytes every 5 minutes during the transfer and **kills
  it** above 8 MB per 5-minute sample, rather than scoring it dirty. Arm A is
  exempt: a spike hour is contaminated by definition and P1 counts our own
  tokens regardless.
- **Nothing else is changed.** `controlled_transfer_probe.py` and
  `controlled_transfer_read.py` are used as they stand, unedited.

## 6. COST AND BLAST RADIUS

150-300 MB of real metered egress (~$0.02-0.04), concurrency 2 of web's 8
gunicorn slots, an incompressible static PNG that touches no sim, no artifact
and no memory. `/healthz` is sampled throughout and the probe aborts on a slow
or failing sample. **No deploy, no code change to any deployed path, no
`render.yaml`** — this arm cannot cause a `blueprint_sync`.

---

## 7. THE READING

*(to be written by the scoring pass, `controlled_transfer_read.py` against the
transfer JSON, once the bucket has settled >= 70 minutes after its hour closed)*
