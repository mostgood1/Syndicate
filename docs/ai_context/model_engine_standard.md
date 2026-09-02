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
- **Allowlisted**, or it cannot be read through `/api/ops/artifacts/*` at all —
  in `HOT_ARTIFACT_PATTERNS` if web must SERVE it, or
  `EXPORT_ONLY_ARTIFACT_PATTERNS` if it must only be auditable and mirrorable.
  The two are not interchangeable; see §3b's "Requirements for a gate".
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

## 3b. MANDATORY: NAME YOUR SUBSTRATE. RENDER IS THE SOURCE OF TRUTH; NOTHING MAY RELY ON AN UNVERIFIED LOCAL READ.

**`[user directive, 2026-08-18]` — this applies to every engine, every audit,
every backtest, and every gate.**

**The directive is unchanged. `[#625, 2026-09-02]` adds ONE thing to it: a local
read that cites a VERIFIED MIRROR MANIFEST is admissible for a stated class of
questions.** The original wording — "nothing may rely on local" — was right
about every incident behind it, and the reason it was right is worth being
precise about, because it is what the extension turns on: each of those
incidents came from a mirror that was PARTIAL and whose partiality was
INVISIBLE. A mirror that can be re-verified file-by-file against a
content-addressed manifest is a different object from the one this rule was
written against. **An unverified local read is still not a claim, and that has
not moved.**

Model *testing* may run locally. Model *facts* may come from there only under
substrate 2 below. The `data/**` trees in git are a **cold-start safety net**,
refreshed per-family on unrelated schedules — not a snapshot of what production
computed, and never substrate 2. A read from the checkout answers a question
about the checkout and nothing else.

### The rule

**Every claim about what an engine has, produces, or is missing must name the
SUBSTRATE it was read from, and that substrate must be one of the three below.
A claim that does not name its substrate is not yet a claim.**

| question | read this | NEVER this |
|---|---|---|
| does the model output reach users? | the **served payload** (`GET /<sport>/api/cards?...`) | a local artifact file |
| does an input artifact exist? | `/api/ops/artifacts/export?path=...` | `ls data/<sport>_source/` |
| is a config key set? | live `/v1/services/<id>/env-vars`, paginated | `render.yaml` |
| which code is running? | the **content** of the deployed blob | ancestry from `main` |
| would this code change the artifact? | a **replay-diff** on a verified mirror, citing its manifest id | a local run on whatever is on disk |

### The three admissible substrates `[#625, 2026-09-02]`

This section used to say the substrate "must be Render", full stop. That was
right about every incident behind it and slightly wrong about why. **The
invariant is not REMOTENESS, it is CHECKABILITY** — every failure below came
from a mirror that was PARTIAL and whose partiality was invisible, not from
locality as such. So a local substrate is admissible exactly when it can be
checked, and inadmissible otherwise, which is what it always was.

**1. PRODUCTION (`render`).** The served payload, `/api/ops/artifacts/*`, the
live env-vars API. The only substrate that can answer *what is true right now*.

**2. A VERIFIED LOCAL MIRROR (`mirror:<manifest_id>`).** Admissible only when
all three hold, and the claim must carry the id:

- the day was synced by `scripts/mirror_manifest.py`, which records a
  content-addressed manifest of every file it pulled;
- `mirror_manifest.py verify --date <D>` passes NOW — it re-hashes every file
  against the manifest, so drift and truncation are caught rather than assumed;
- the question is in the reproducible class (below).

Cite it as `mirror:8d5c42ba8cb18c34`. An id nobody can re-verify is decoration;
`verify` is what makes it a claim.

**3. THE GIT MIRROR (`checkout`).** Still not a substrate for any model fact.
`data/**` in git is refreshed per family on unrelated schedules — measured, four
MLB families whose date windows are 46 / 33 / 26 / 11 dates and whose
intersection is **one usable date**. A reading from here is a statement about a
checkout. It may be labelled and reported; it may not be a claim.

### What a verified mirror may and may NOT answer

A mirror is a copy of ARTIFACTS. It is not a copy of the running system, and the
line falls exactly where §3b's own worked example does — NCAAF's local **0
games** against production's **16** was a question about what production
PRODUCES, and no mirror can answer that.

| a verified mirror CAN answer | it can NEVER answer |
|---|---|
| what an input file contains, for the dates in its manifest | whether production has that file **now** |
| whether this code, run over those bytes, reproduces production's artifact | whether the model output reaches a user |
| whether a field is populated **in the mirrored dates** | whether a job is enabled, or ran |
| how much memory a producer uses on those inputs | which commit is deployed |

**A local run is evidence about the CODE, never about the DEPLOYMENT.** The
strongest form is a replay-diff (`scripts/replay_diff_gate.py`): run the real
worker entrypoint over a mirrored day and diff against production's own output.
Measured 2026-09-01 — 280,840 leaves exact, 0 mismatches — which is what
licenses substrate 2 at all. It also comes with two preconditions that any local
claim inherits: **every input must predate the output**, or the diff measures
elapsed time; and **the checkout must be the commit that produced the output**,
or it measures code drift (refresh-worker took 465 successful deploys in 21 days,
and of nine consecutive dates only ONE was built by the then-current HEAD).

### A 403 IS NOT AN ABSENCE, and it has now cost three readings

`/api/ops/artifacts/export` — `names_only` and body form alike — globs the
artifact allowlist and returns only what matches. **So it can never establish
that a non-allowlisted family is absent**; it reports the intersection of the
allowlist with the disk, and a family outside the allowlist is INVISIBLE, not
missing. Measured 2026-09-02: a full inventory returned zero `feed_live` files
and the conclusion "absent" was published; there were **146 files, 16,721,077
bytes** on that disk the whole time. Two earlier readings made the same error on
`locked_cards_retuned` and `market/oddsapi/`.

Before reading absence out of any listing, state what the listing is FILTERED
by, and ask whether the thing you are looking for could pass that filter. If it
could not, the listing says nothing about it.

### Why this is stated at this length

Measured twice in one session, on the same engine:

- `FootballSimulationAdapter(sport="ncaaf").load_features(...)` returns **0
  games** locally. Production serves **16**. That local zero was written into
  `todo.md` and a reference doc as a production defect, and had to be retracted.
- The same checklist's population level, run against a local mirror, reported
  **"0.0% populated"** on nine input blocks — from a **1-game** degenerate load.
  The real load is **272 games** with three blocks at **100%**.

Both readings were correct about the laptop and wrong about the system. **The
dangerous case is when the local reading AGREES with something true** — NCAAF
genuinely produces no model output — because then a second "nothing" reads as
corroboration instead of as a measurement of a different subject.

### Requirements for a gate

- A gate that measures population **must** report **UNMEASURED** — never `0%` —
  when its substrate is a local checkout, and must say so in the failure text.
  `scripts/football_sim_input_checklist.py` emits *"FROM THIS CHECKOUT ...
  `data/**` is a lossy mirror ... check the served board"*.
  **A VERIFIED MIRROR IS NOT A CHECKOUT** `[#625, 2026-09-02]`: a gate whose
  substrate is substrate 2 may report a real number, provided it prints the
  manifest id and the dates that manifest covers alongside it. The number then
  describes those dates and nothing else — which is the whole point of citing
  them. A gate that cannot tell the two apart must assume checkout and report
  UNMEASURED; **unknown does not get the permissive branch.**
- **Every model input must be in an artifact allowlist**, or it cannot be read
  through `/api/ops/artifacts/*` — which means it cannot be audited on Render at
  all, and every question about it falls back to the local guess this rule
  forbids. Measured: NCAAF's `recommendations_summary/week_N.json` — **the
  artifact its board renders from** — is not allowlisted, so its row count was
  unanswerable from outside and had to be instrumented in the payload instead.
- **THERE ARE TWO ALLOWLISTS NOW, AND PICKING THE WRONG ONE IS A REAL DEFECT**
  `[#625(2), 2026-09-02]`:
  - `HOT_ARTIFACT_PATTERNS` — **WRITE**. Publishable to web and swept for
    publishing. Use this for an input web must SERVE.
  - `EXPORT_ONLY_ARTIFACT_PATTERNS` — **READ**. Exportable and streamable,
    never published, never swept. Use this for an input that must be
    AUDITABLE and MIRRORABLE but must not reach web's serving path.

  The read predicate is `is_exportable_artifact_relative_path`; the write
  predicate is `is_hot_artifact_relative_path`. **Choosing the write list for a
  read-only need is not a tidiness question.** `raw/statsapi/feed_live` on web's
  disk freezes live game state for every reader — `_mlb_feed_live_payload`
  returns the cached file IF IT EXISTS and only fetches live when it is absent
  (`blueprints/home.py:3560`), so the trigger is PRESENCE ON DISK and no
  allowlist setting can undo it once the bytes are there.
- **Maintaining that allowlist is part of shipping an input**, not follow-up
  work. An unallowlisted artifact is an unauditable one — and a large or binary
  one needs `/api/ops/artifacts/stream`, because `export?path=` returns a JSON
  envelope of DECODED TEXT and answers 415 on anything that is not UTF-8.

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
- [ ] **Every input allowlisted** — `HOT_ARTIFACT_PATTERNS` if web must SERVE it,
      `EXPORT_ONLY_ARTIFACT_PATTERNS` if it must only be AUDITABLE and
      MIRRORABLE. Unallowlisted = unauditable; wrong list = a publish that
      should never have happened (§3b)
- [ ] **Every claim names its substrate** — `render`, `mirror:<manifest_id>`, or
      `checkout` — and `checkout` is never a claim (§3b)
- [ ] **Any local claim cites a manifest id that `verify` passes TODAY**, and
      states the dates it covers (§3b)
- [ ] **A replay-diff for the producer**, if its output is an artifact anyone
      reads — the real entrypoint over a mirrored day, diffed against
      production's own output (`scripts/replay_diff_gate.py`)
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
