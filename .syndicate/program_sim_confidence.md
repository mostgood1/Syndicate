# Program: trustworthy sim engines, then bucketed edges

`[opened 2026-09-07 by session 3492626c, at user request, to be co-owned with
lane ncaaf-live-resim-wire]`

**The ask, in the user's words:** fix the sim engines end to end to use ALL
data, be confident in their ability to sim correctly, and get back on track
identifying the right edges — combining EV and the sims — to drive pregame,
live and props bets, grouping by interval/prop/segment for every sport
uniquely, and finding edges by bucket.

This file is the shared contract between two sessions. **The football half and
the output-checklist half are `ncaaf-live-resim-wire`'s to rewrite**; they are
sketched here only so the whole shape is visible in one place.

---

## The sequencing, and why it is not negotiable

**Inputs verified in production → outputs verified in production → buckets.**

The temptation is to start at the bucket layer, because that is what the user
can see and bet. The reason not to is measured, today, twice:

- "Four of five engines FAIL their input checklist" was TRUE and its headline
  number was wrong. **NINE of MLB's ten** unfed pitcher fields were a
  **checklist artifact** — it globbed the wrong pipeline directory and sorted
  ascending, so it re-measured eight June roster files every night for nineteen
  nights. Seven of the ten had been fed the whole time.
  **The TENTH was real** `[correction accepted 2026-09-07 from lane
  soccer-unfed-inputs]`: `conditional_arsenal_source` was a write-side drop —
  set in memory by `conditional_mix.py`, read back by `de_pitcher`, never
  written by `ser_pitcher`, and silent because the dataclass default is `""`.
  Fixed and measured in production: 64/65 -> 65/65, `failures: []`, the field
  0.0 -> 0.86, matching its sibling exactly. **Retracting a sampling artifact
  does not exonerate every field it covered** — I said "ten fields were a
  checklist artifact" and one of them was a genuine bug.
- A local run of the same checklist reports **24** failures where production
  reports **10** then **1**. The mirror overstated it by 14 fields.

A bucket-level edge finder built on an engine whose inputs are unverified
inherits that ambiguity in every cell. A bucket that looks flat because a
feature is unfed and a bucket that is genuinely flat are the same number. We
would not be able to tell them apart, and the whole point of bucketing is to
tell things apart.

---

## Definition of done, per sport

A sport is TRUSTWORTHY when all four hold, each read from **production**, not a
local mirror:

1. **Every input alarm is FED or EXPLAINED — not "green".**
   `[corrected 2026-09-07 by lane soccer-unfed-inputs, who measured it]` The
   first draft of this file said "input checklist green in production", and
   that definition would have driven a session into a MEASURED regression.
   Soccer's gate reported 9 CONSUMED+UNPOPULATED and only 2 are defects:

     * 5 are DELIBERATE. `goals_per_match` / `goals_against_per_match`: goals
       ARE the xG stand-in on the football-data path, so feeding a goals field
       puts the same number through `_attack_strength` twice — A/B'd at
       `total_mean` 3.16 -> 3.39, `home_mean` 1.71 -> 1.89. Both `ppda` entries:
       the source has no ppda column and `compute_team_ratings` emits 0.0,
       which does not read as "no pressing" — it reads as the MOST aggressive
       press possible, so the loader drops it rather than fabricate an extreme.
       `model_probability` is the model's own view, circular at prior-build time.
     * 2 were the GATE'S OWN BLIND SPOT — `spread`/`total` are sub-dicts inside
       `market_features`, so the AST walk saw local names and filed them "NO
       MAPPING": alarms carrying no evidence in either direction.
     * 2 have NO DATA SOURCE at all (`big_chances_per_match`,
       `pace_seconds_per_event`). Those need a source, not wiring.

   So DONE is: **every alarm is either FED, or sits in a `disabled` category
   with its reason and evidence recorded** — MLB's `7dc4893d` precedent. Chasing
   "green" would wire four fields that are regressions, one of them already
   measured as one. The report is still published to
   `<sport>_source/source_artifacts/data/sim_input_report/sim_input_report_<date>.json`
   so the number is readable rather than asserted.
2. **Output checklist green in production** (`scripts/sim_output_checklist.py`):
   no exact 0.0/1.0 certainty, estimator and interval agree, quantisation
   matches the claimed `sims_run`, resume identity holds, the sim
   DISCRIMINATES, and the interval is real.
3. **Every input disk-backed under `SYNDICATE_DATA_ROOT` and allowlisted in
   `HOT_ARTIFACT_PATTERNS`.** A local cache cannot reach Render.
4. **A reachability test before correctness tests** for anything behind a flag
   (`off != on`).

Reading `host: worker` on a report is NOT sufficient evidence it came from
production — that field only means `SYNDICATE_DATA_ROOT` was set in the
producing process, and a laptop run with that var set stamps itself `worker`.
One did, today, with 24 failures. **Cite `resolved_root` and `generated_at`
alongside it.**

---

## Current state, labelled

| sport | can publish a production input report? | production population read? | output checklist run? |
|---|---|---|---|
| MLB | yes, 20 daily reports on disk | **yes** — 1 failure as of 16:27Z | partially (estimator fix verified) |
| NHL | yes, but **never once** — path was unallowlisted until today | no | no |
| soccer | yes, as of `08da43f0` | **DONE** — `359ef031` + `4c264a05`, 9 alarms -> 2 + 5 disabled | no |
| basketball | yes, as of `08da43f0` | **not yet** | no |
| football | yes, as of `08da43f0` | **not yet** | its 3 payload alarms cleared |

Football's three UNWIRED-PAYLOAD alarms were CODE facts and therefore true of
production; the population percentages for soccer/basketball were local-mirror
readings and are not yet evidence about anything.

---

## THE BLOCKER, and it outranks everything above

**Artifacts published to production do not reliably stay published.** Measured
2026-09-07: `arsenal` and `quality` were rebuilt and published at 17:53Z,
verified by read-back to the microsecond, and had **reverted to their
2026-08-18 content** by 18:20Z. Dated from web's own access log by response
size: fresh at 18:07:15Z, reverted by 18:20:56Z. `batted_ball` held.

Eliminated: refresh-worker's hot-artifact sweep (its only arsenal publishes
were 16:52 and 17:29, both before, and every later attempt logged
`PUBLISH_SKIPPED_UNCHANGED`); any deploy (web's last finished 18:00:11Z).

**Until the writer is identified, no "we fixed the inputs" claim is durable** —
including the ones already made today. Owner: session 3492626c.

---

## Ownership

| area | owner |
|---|---|
| artifact durability (the blocker) | 3492626c |
| MLB / soccer / basketball input population, from production | 3492626c |
| bucketing + edge layer, once engines are trustworthy | 3492626c |
| football (NFL + NCAAF) engines, NFL first calibration, NCAAF refit | `ncaaf-live-resim-wire` |
| output checklist rollout to soccer / basketball / NHL | `ncaaf-live-resim-wire` |
| **`_SCORE_SIM_WEIGHT` and the `blended_score` cap** | **neither, yet — see below** |

---

## The one decision neither session should take alone

`_SCORE_SIM_WEIGHT = 0.125`, capped at 1.5 EV points, is the sim's entire
ranking influence. The refusal audit established that **market EV is already
primary and already ungated**, and every audited gate sits on the MODEL term —
so "earn the augment" is the real unlock, and it is ONE decision across all
sports rather than a per-sport tuning.

It must not move until the engines are verified, and then it belongs to
whoever holds **CLV decomposed by component** — evidence that the sim's
contribution beats the closing line on its own, not that the blend does.

The precedent that makes this urgent rather than academic: the football
evidence is currently AGAINST the sim. NCAAF margins lose to the closing line
by 3.563 points of MAE at t=17.20 over 2,233 games; NFL regular season loses at
t=+3.34 over 272 held-out games and has **no skill gate at all**. Raising the
sim's weight before that is answered would be moving in the wrong direction.

---

## What the bucket layer will need, recorded now so it is not rediscovered

- Buckets are per sport AND per market family AND per segment
  (`full`/`first5`/`h1`/…) — the segment field already reaches order rows and
  was silently ignored by the MLB resolver until 2026-09-07, costing 49
  mis-graded orders and −$31.32.
- A bucket needs a DENOMINATOR before it needs a rate. Five wrong findings in
  one session came from counts without them.
- `settled_by == "venue"` rows must be excluded from any model-accuracy bucket:
  the venue graded the instrument actually held, which for five of ten was a
  whole-game contract against a first5 bet.
- Split every board-coverage number by GAME STATE, or a finished slate reads as
  a regression.
