# The Model Engine Standard — what every sim engine must document and prove

> Written 2026-08-18 from the MLB engine audit (`#440`). **This applies to every
> current and future engine**: smartsim2 (NFL/NCAAF), soccersim, hockeysim,
> basketball smart-sim, MLB, and anything added later.
>
> It exists because a single day's audit of the *most mature* engine in the
> platform found **26 input fields that the simulation reads and nothing feeds**,
> **four features that were built, tested, and inert**, and **three published
> claims of mine that were wrong** — none of which produced an error, a failing
> test, or a log line.

---

## 0. The failure this standard prevents

A sim engine can be **completely broken and completely silent**. The specific
shape, measured repeatedly:

```python
mult = float((pitcher.pitch_type_whiff_mult or {}).get(pitch_type, 1.0))
```

If nothing populates `pitch_type_whiff_mult`, this returns `1.0` forever. The sim
runs. The tests pass. The numbers look plausible. **The output is identical to a
build where the feature does not exist.**

Every check this repo had — unit tests, the migration gate, browser parity, the
archive suite — passes cleanly while that is true. **Nothing in this repo could
see it before the checklist.**

---

## 1. MANDATORY: an input checklist that gates

**Every engine must have a runnable script that exits non-zero when an input the
engine reads is not populated.** Reference implementation:
`scripts/sim_input_checklist.py` (MLB).

It must cross-reference **two** things per field, and neither alone is
sufficient:

| question | how | why alone it fails |
|---|---|---|
| is it **CONSUMED**? | search the engine source for the field name | a populated field nothing reads is dead weight, not a defect |
| is it **POPULATED**? | measure over real artifacts, not fixtures | a consumed field nothing feeds is a silent no-op |

**CONSUMED + UNPOPULATED is the alarm.** That is the only combination that is
both broken and invisible.

Requirements:

- **Enumerate `dataclasses.fields()`. Never grep for names you expect.** A name
  search proves only that *your vocabulary* is absent — see §4.1.
- **Compare against the dataclass DEFAULT**, not against `None`. A field sitting
  at its default is unfed even though it holds a number.
- **Document legitimately-sparse fields explicitly** (`EXPECTED_SPARSE`), with a
  reason each. Anything not listed and consumed must clear a floor.
- **Exit 1 on failure** so it can gate `/preflight` or `migration_gate.py`.
- **Publish a bounded report artifact** so PRODUCTION can be audited without
  streaming the raw inputs (see §3).

---

## 2. MANDATORY: a documented pipeline trace

Every engine must document the full chain, **naming the file and line at each
hop**, from scheduler to artifact:

```
loop/scheduler  ->  job script  ->  builder  ->  engine  ->  artifact written
```

MLB's, as the worked example:

```
live_refresh_loop._run_mlb_sim_tick
  -> scripts/run_mlb_daily_sim_job.py            (detached subprocess)
    -> vendor/mlb_bettingv2/tools/daily_update.py    (:236)
      -> build_roster  (statcast_cache passed when --statcast-starter-splits != off)
        -> _apply_cached_statcast_pitch_splits
          -> fetch_pitcher_pitch_splits -> artifact-first, cache fallback
   writes: snapshot_dir/roster_objs/*.json, daily_summary_<date>.json
```

**Without this trace you cannot tell whether a change reaches production**, and
three separate features were shipped this session believing they did.

---

## 3. MANDATORY: inputs must exist in production AS ARTIFACTS

A model input that lives only in a local cache **cannot reach production**, and
this is not obvious from the code.

Measured failure: MLB pitch splits lived in a `DiskCache` under
`vendor/mlb_bettingv2/data/cache/`, which is **gitignored** *and* inside Render's
**ephemeral repo checkout**. It could never ship with a deploy, and anything
written there is destroyed by the next one.

Requirements for every engine input:

- **Disk-backed**, resolved through `SYNDICATE_DATA_ROOT` (the mounted disk),
  never a path relative to the source tree.
- **Allowlisted** in `artifact_publisher.HOT_ARTIFACT_PATTERNS`, or it cannot be
  published or read through `/api/ops/artifacts/*`.
- **A readable document**, keyed by a real id — not a hash-named cache. A cache
  cannot be diffed, validated, or inspected.
- **Bounded**: prefer one per-season document over per-date fan-out. The
  allowlist drives publishing as well as reading, and the egress history here is
  expensive (`#322`).

**Corollary — publishing is necessary, not sufficient.** MLB's
`--use-roster-artifacts` defaults to `on`, so the worker REUSES profiles
serialised before the new input existed. **A new input requires a REBUILD, not
just a publish.** Every engine must document its equivalent reuse flag.

---

## 4. The five rules, each earned by a measured failure

### 4.1 "Absent" needs a field audit, not a name search
I searched `ground_ball|fly_ball|launch_angle` and published *"no batted-ball
model"*. The fields are `bb_gb_rate` / `bb_fb_rate` / `bb_ld_rate` /
`bb_pu_rate`, the sim consumes all four, and all four were 0% populated.
**ABSENT and UNFED have opposite remedies** — design-and-build versus
populate-a-field. I recommended a modelling project where a data pipeline was
needed, and built the wrong thing on top of it.

### 4.2 A neutral default makes an unfed field invisible
`.get(key, 1.0)`, `or {}`, `or 0.0` — each converts "no data" into "no effect"
with no signal. **Measure population rates; never infer from code presence.**

### 4.3 Presence is not reachability — write the reachability test FIRST
For any feature behind a flag, artifact, or config key:
```python
assert run(enabled=False) != run(enabled=True)
```
**before** the correctness tests. Four features were caught by exactly this and
by nothing else. Two would otherwise have shipped as complete. Note
`dataclasses.replace()` silently drops attributes set with `setattr` — flags must
be **declared fields**.

### 4.4 Mechanism vs estimator — and calibration absorbs mechanisms
- A **mechanism** changes what the engine *does* (substitution, pitch effects).
- An **estimator** changes how well a parameter is *measured* (batted-ball
  quality informing `hr_rate`).

Measured: adding two mechanisms to a calibrated engine produced a **negative
interaction in 4 of 4 markets**. The fitted rates already absorb the average
effect of a missing mechanism, so re-adding it double-counts. **Adding a
mechanism is a two-part change: the mechanism AND a re-fit of the parameters
that were absorbing it.** Shipping half is worse than shipping neither.

### 4.5 A single-feature measurement understates a suppressed feature
Because of 4.4, an effect measured against un-refitted rates is **what survives
the calibration fighting it**, not the feature's ceiling. A small measured effect
is weak evidence that a mechanism is unimportant.

---

## 5. The checklist for a NEW engine

Before an engine is considered production-ready:

- [ ] **Input inventory** — every field, with `consumed?` and `populated%`
- [ ] **Gating checklist script**, exits 1, in `/preflight` or the migration gate
- [ ] **Pipeline trace documented**, file:line at each hop, including what it writes
- [ ] **Every input disk-backed** via `SYNDICATE_DATA_ROOT`, never the source tree
- [ ] **Every input allowlisted** in `HOT_ARTIFACT_PATTERNS`
- [ ] **Reuse/caching flags documented**, with the rebuild procedure for a new input
- [ ] **Reachability test per flagged feature** (`off != on`)
- [ ] **Mechanisms distinguished from estimators**, with the re-fit obligation stated
- [ ] **A market-relative scoreboard** — beating climatology is a screen, not the goal
- [ ] **Known-sparse fields documented with reasons**

---

## 6. Why "it passes its tests" is not evidence

Every inert feature found this session had passing tests. The tests verified the
function's behaviour **given inputs**, and the defect was that the inputs never
arrived. A test suite that constructs its own fixtures **cannot** detect an unfed
production field — it supplies the very data that is missing.

**The checklist is the only artifact in this repo that measures what production
actually holds.** Treat it as the gate, not the unit tests.
