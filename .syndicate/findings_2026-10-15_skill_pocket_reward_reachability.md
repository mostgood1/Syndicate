# RETRACTED: "a pocket earns nothing" is wrong. The reward is live, it fires on 794 rows, and it cancelled 244 of the demotions I shipped an hour ago

`[2026-10-15 21:0x–21:3xZ, session 4ab694ed, lane skill-pocket-reward-reachability, taking the reward-asymmetry lead I filed myself]`

## What I claimed, and what is true

I filed this twice — in `findings_2026-10-15_unmeasured_edge_risk_cost.md` and in
`state_model.md` `[model-skill]`:

> **`established_loss_rel` is None on all 14 and a pocket carries NO reward
> field**, so `skill_reliability` returns 1.0 for it — a bucket measured to beat
> the market ranks identically to one never backtested.

**Every clause of that is literally true and the conclusion does not follow.**
`skill_reliability` is the CATEGORY instrument. Pockets are consumed by a
different one, `measured_bucket_skill.bucket_factor`, which `layer2_board`
consults *first*:

> A VALIDATED BUCKET OUTRANKS THE CATEGORY. … a validated pocket returns 1.0
> (the category demotion is cancelled for that row, never raised past its
> value), a validated bucket loss returns its own scaled factor, and no match or
> a pocket/loss conflict leaves the category factor.

So a pocket's reward is **cancelling a demotion**, and the 1.0 ceiling is a
stated design constraint — *"never above 1.0: the score's own guard only
lowers"* — not an omission. I had the mechanism, the ceiling and the rationale
all one file away and asserted absence from the wrong function's behaviour.

## It is not merely present — it is firing

Measured through the scorer's own adapter (`view_from_candidate`) with the
overlay the runtime actually loads. The fleet log line proves the load:

```
[skill_overlay] SOURCE=overlay reason=ok buckets=43
                generated_at=2026-10-15T11:30:01Z expires_at=2026-10-18T11:30:01Z
```

Over **4,549 served rows across six sports**, phase `pregame` on all of them:

| `bucket_factor` returns | rows | meaning |
|---|---|---|
| `None` | 3,029 | no validated match — the category factor stands |
| **1.0** | **794** | **a POCKET cancelled the category demotion** |
| 0.9685 | 104 | a validated bucket LOSS, own scaled factor |
| 0.95765 | 279 | ditto |
| 0.91225 | 143 | ditto |
| 0.9117 | 114 | ditto |
| 0.90115 | 85 | ditto |
| 0.85255 | 1 | ditto |

**1,520 of 4,549 rows match a validated bucket.** Pocket hits are all soccer
props — `player_shots_on_target` 422, `player_shots` 244, `player_assists` 128,
across 10 distinct buckets. Loss hits are NHL `points`/`assists`, 14 buckets.

## And it cancelled 244 of the demotions I shipped an hour earlier

The served **score** (not the projection note), soccer, cap defeated:

| market | rows | `score.skill_reliability` / `skill_source` |
|---|---|---|
| `player_shots` | 373 | **244 → `None` / `None`** (pocket cancelled it) · **129 → `0.915` / `category`** |
| `player_shots_on_target` | 422 | 422 → `None` / `None` |
| `player_assists` | 128 | 128 → `None` / `None` |

244 is exactly the row count of the pocket `soccer|player_shots|full|pregame|price=long`.
The two instruments agree.

**So my `deploys.md` verify line for `28ded758` is overstated and is corrected
there.** It said "382 rows measured factor 0.9150". True of the **note**; of the
**applied** factor only ~129 rows carry the demotion, because a validated pocket
outranks the category for the other 244. That is the designed interaction, and
it is the same error my own learnings already name: *count the field the CONSUMER
reads*. The note is not the applied factor.

## Three invalid measurements on the way here, all retracted

Stated because the sequence is the lesson, not a confession:

1. **`bucket_factor(view, table=...)` against a table I had failed to load.**
   `so.active_table()` raised `TypeError`, my fallback silently used
   `MEASURED_BUCKET_SKILL` (the static table, **0 entries** — the documented
   shipped state), and I read `matching_table=0` as a finding. It measured an
   empty dict.
2. **`bucket_ids(row)` on the RAW row.** The raw row has no `phase` key, so
   `bucket_prefix`'s `view.get("phase") or "unknown"` stamped `unknown` on every
   id, against a table keyed `pregame`/`live` — and I got "**0 of 1,414 rows
   match**" and a tidy root-cause story about a broken "ONE DEFINITION" promise.
   The scorer calls `bucket_factor(view_from_candidate(row))`, and that adapter
   sets phase via `_phase(row["game_state"], …)`. With the adapter: **100%
   `pregame`, 1,520 matches.** The promise is kept; I had broken it in my test.
3. **A service-split hypothesis** (overlay published to web's disk, board built
   on refresh-worker) — falsified in one read: this fleet shares one data root,
   the overlay is present, source `model_scorecard/1`, unexpired.

Each wrong answer was self-consistent and had a plausible mechanism attached.
What distinguished them was reading the **call site** rather than guessing the
call.

## The answer to the lead

**There is no reward asymmetry to fix.** The asymmetry I filed does not exist in
the form I described:

- a pocket **does** earn something — cancellation of a category demotion, live
  on 794 rows right now;
- the "never above 1.0" ceiling is **deliberate and justified** in the module
  (the score's guard only lowers), under a 2026-09-14 user decision
  (*"Category now, buckets next"*, *"then build the bucket search on the
  recorder data"*);
- the static table being empty is the **documented shipped state**, and the
  overlay supplies the live table through `skill_overlay` with a 72h expiry, a
  source-prefix check and a background pull.

**What remains is a genuine open question for a human, and it is small:** should
a pocket be allowed to raise a score *above* 1.0 rather than only cancel a
demotion? That is a risk decision about letting 66–88-game results amplify a
rank, which this repo has explicitly declined once already. I am not taking it.

## Method note

Every number here comes from the deployed functions called the way the scorer
calls them, over the served board with the row cap defeated, plus the fleet's own
`[skill_overlay] SOURCE=overlay` log line as independent confirmation that the
table is loaded in production rather than only loadable. The three retracted
measurements are listed with what each actually measured.
