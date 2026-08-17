# Syndicate — Learnings

> **Append only.** Rules must be obeyable by a session with zero context.
> `FORBIDDEN` = never do this again. `EXONERATED` = ruled out, stop
> re-investigating.

> **USE THE TEMPLATE — it is what lets this file be compacted without judgement.**
> Five bullets: `What we believed` / `What was actually true` / `How we found
> out` / `The rule going forward` / `Cost`. The compaction pass keeps the RULE
> bullet in this file and moves the other four to `learnings_evidence.md`, so a
> templated entry shrinks to ~500B automatically and every rule stays readable
> at session start.
>
> **Prose entries cannot be compacted mechanically.** As of 2026-08-16, 28
> entries (68 KB, all written 08-15) state their rule somewhere mid-paragraph
> rather than in a `The rule going forward` bullet. Extracting it needs a human
> reading each one, and a regex that guessed would keep the evidence and drop
> the rule — so they were left INTACT rather than mangled. They are the reason
> this file is 162 KB against a 117 KB budget.
>
> If you write a rule tonight, write it in the template and it costs the next
> session nothing.


<!-- LEARNINGS-INDEX:START -->

## Index — 213 rules `[generated]`

> Full index: [`learnings_index.md`](learnings_index.md) — regenerate with
> `py -3 scripts/build_learnings_index.py` after appending. It spans BOTH
> this file and `learnings_evidence.md`, so a rule stays findable after its
> body is compacted out. **FORBIDDEN** = never do this again.
> **EXONERATED** = ruled out, stop re-investigating.

<!-- LEARNINGS-INDEX:END -->

---

### 2026-08-12 — EXONERATED: the soccer window is not the egress cause
- What we believed: the change that tripled dates per sweep (5–6 → 15–18),
  shipped the same day the egress spike was noticed, caused the spike.
- What was actually true: the 14-day graph shows the same spikes since
  7/30, predating the change entirely.
- How we found out: looked at the metric *before* the change instead of
  only after it.
- The rule going forward: **before blaming a recent change for a symptom,
  pull the metric back far enough to see whether the symptom predates it.**
  Same-day coincidence is the weakest possible evidence.
- Cost: a day of investigation aimed at the wrong subsystem.

### 2026-08-12 — Do not batch changes during a diagnosis
- What we believed: shipping the guard and the rate ceiling together
  would resolve things faster.
- What was actually true: with #394 and #395 landing together, neither
  effect could be attributed cleanly. The egress drop cannot be assigned
  to the guard.
- The rule going forward: **while diagnosing, one substantive change per
  deploy, with a measurement window closed before the next one starts.**
  Enforced by `/preflight` question 1.
- Cost: a permanently ambiguous data point in `deploys.md`.

### 2026-08-12 — A rate ceiling is not a fix
- The rule going forward: **a cap makes a graph look healthy while the
  underlying waste continues.** Never close a lane on the strength of a
  metric that is being clamped. Measure the uncapped behaviour, or
  measure something the cap does not touch.

### 2026-08-12 — Parallel sessions on one problem need lane discipline
- What was actually true: a second coding session worked the same problem
  concurrently, with no shared record of hypotheses tried or ruled out.
- The rule going forward: **hypotheses go into the lane before they are
  tested, and exonerations are written down as loudly as findings.** The
  expensive failure is re-litigating a dead end three sessions later.

### 2026-08-13 — A grep excerpt is not the file
- What was actually true: a `grep` result rendered
  `open("/proc/self/status")` as `open("\proc\self\status")`. A
  permanently-inert memory guard was half written up on that basis —
  against another lane's freshly shipped work.
- The rule going forward: **read the file before filing a defect against
  a literal.** Search output is a pointer, not evidence. `sed -n` on the
  path is authoritative where a tool's excerpt is not.
- Cost: none, caught before filing. Records the near-miss because the
  next one will not announce itself.

### 2026-08-10 — a briefed premise is a hypothesis, not a starting condition
- What was believed: soccer sims were OFF by standing instruction, so the lane
  was working against a mitigated system.
- What was actually true: the autorun flag was `'true'` live, all three sim
  fixes were ancestors of the deployed commit, and a 20m13s sim was running.
  **Nothing had been mitigating it all evening.**
- The rule going forward: **verify the premise of the brief before writing code
  against it.** Checking cost one env query and one ancestry check; it changed
  the urgency of the whole lane.

### 2026-08-15 — a threshold is calibrated against a SPAN; changing what the span contains invalidates it without touching the constant
- **The rule going forward:** before deploying, ask what else READS the window
  whose contents you are changing — thresholds, guards, timeouts, caches sized
  against "a pass". Grep the span's own markers for constants that mention it. A
  threshold invalidated this way appears in NO diff, so review cannot catch it;
  only asking the question can.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-15 — EXONERATED: "eight hydrated sports at once cannot fit in 4GiB"

The `#387` handoff carried this as settled, from the 20:03:11Z kill: peak = SUM
across eight sports "is sufficient on its own to cross 4GiB", and "the floor
plays no part". Measured on the SAME evening, on the pre-cutover code:

    22:36:48 -> 22:37:43   8 sports hydrated   PEAK 804.2 MB anon  (19.6%)
    22:49:19 -> 22:49:50   8 sports hydrated   PEAK 613.1 MB anon  (15.0%)

The shape that "cannot fit" ran twice, twenty minutes apart, at a fifth of the
ceiling. **The eight-sport pass is exonerated as a sufficient cause.** The
20:03:11Z kill remains UNEXPLAINED: something made MLB cost +3.5GB in that pass
against +1.0GB measured four times since. Do not close `#387` as "solved by
streaming" — streaming caps the transient, it did not explain the outlier.

Consequence, deliberate: the guard in front of MLB keeps its full 3000MB floor.
The seven cheap sports were relaxed to 1500MB because their cost is measured
(+1.7MB for five of them); MLB's tail is not.

### 2026-08-15 — FORBIDDEN: never conclude "no OOM" from a LOG search. Kills are EVENTS, and I had this rule already
- **The rule going forward:** a negative result about process death MUST come
  from the events API. `scripts/render_logs.py` cannot answer this question and
  a 0-match result from it is not evidence. Absence of a log line is evidence
  about the EMITTER, and a killed process emits nothing.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-15 — the kill is MLB game hydration in pid 39, not the overview pass

Measured at the 00:41:16 kill, the best-instrumented one:

    00:40:14  container 3357.8MB (82.0%)   pid 39 = 1612.1MB   7 processes
    00:40:42  container 4095.8MB (100.0%)  pid 39 = 3079.6MB   10 processes
    00:40:58  anon 3941.6 -> 4047.6MB in 1.2s, game_count 15, unreclaimable 4058MB
    00:41:16  server_failed oomKilled 4Gi

**pid 39 — the main worker — grew ~1.47GB in 28 seconds** while its children
stayed small (`daily_update.py` 166.6MB, soccer odds refresh 95.5MB). The
payloads carry `game_count: 15` / `game_pk_count: 15`, i.e. the MLB game
hydration path, NOT the overview.

And at the handoff's canonical kill:

    20:02:59  container 1179.3MB (28.8%)  process_count 2  stage=post_build_overview
    20:03:11  server_failed oomKilled 4Gi

**28.8% twelve seconds before the kill, with the overview already FINISHED.**

So `#387`'s premise — that the eight-sport hydrated overview is what crosses
4GiB — is falsified from three directions now: the same pass ran at 613/804MB
twice, the container was at 28.8% seconds before the canonical kill with the
overview complete, and the kills continue at the same rate after both halves of
the fix shipped. The 2026-08-07 guard comment said so in plain words and was
right: *"This is a circuit breaker around MLB's cost, NOT a fix for it. The real
work is making `build_cards_page_context` cheaper or not running it hydrated on
the worker at all."*

## 2026-08-14 — OVERTURNED: a number that corrects a known bias is the easiest one to believe

**Believed:** the joiner's first same-book CLV, `avg_clv_pct = -5.215` over 25
rows (beat-close 9/25), was the first honest measurement of our closing-line
value. It was the number the whole lane existed to produce.

**Why it was so convincing — this is the part worth keeping.** It was not
merely plausible, it was *diagnostically* plausible: it had the **opposite
sign** to the book-biased scopes (+7.0 and +4.8), which is exactly what a real
bias correction is supposed to look like. Every structural property checked out
— same event, same market, same book, same line, a real price at each end. The
number arrived immediately after building the machinery designed to produce it.

**Measured:** two independent defects, either alone sufficient to invalidate it.
1. The LINE was never compared. Odds-history keys carry no line; the point's
   `line` block does. A board row at `home -5.0` was being differenced against
   a `home -1.5` close.
2. **25 of 25 closes were captured BEFORE their openings.** Openings at
   00:46:53Z against "closes" from 22:12–23:16 the previous evening.

**The tell was a magnitude, not a structure.** Two rows read `spreads home -1.5`
moving `-122 -> +162` and `-238 -> +135`. A spread does not move 28 probability
points. Everything checkable by schema passed; only domain knowledge caught it.

**How to apply:**
- When a new instrument produces the number you built it to produce, and that
  number *confirms* your prior, spend the next step trying to break it — not
  reporting it. Confirmation is when scrutiny is cheapest to skip.
- Sanity-check the MAGNITUDE of every derived quantity against what the domain
  permits. Schema-valid and physically possible are different tests.
- For any two-timestamp quantity, assert the arrow of time explicitly. Nothing
  else will: the pairing is well-formed in every other respect.
Related: [[feedback_gate_on_the_output_not_the_input]],
[[feedback_unknown_must_not_default_permissive]].

## 2026-08-14 — a control with no baseline is a guess wearing a control's clothes

Shipping audit §7 #7, I pre-registered "non-mlb rows must carry zero measured
skill" as CONTROL C. It failed: 53 of 66 non-mlb rows had a skill correlation.
I investigated it as a possible leak of MLB calibration onto other sports — the
worst outcome that change could have had.

It was not a leak. The 53 are NFL's own producer (corr -0.047 / 0.269, seasons
**2023-2025**), unrelated to the MLB window (2026-08-01..08-14), and they
predate the deploy. **I had baselined the MLB props before deploying and never
baselined non-mlb** — so the control's expected value was assumed, not measured.

**How to apply:** a control needs a PRE-CHANGE READING, not an intuition about
what "should" be true. An unbaselined control fails in both directions: it
raises false alarms, and it would have waved a real regression through just as
easily. Related: [[feedback_a_rate_not_count]].

## 2026-08-14 — read the system's clock, not the wall clock

Called "the date rolled over to 2026-08-15" from a UTC `date -u`. The system
roots dates in **Central** (`central_today_iso()`), and the board reported
`date: 2026-08-14` at the same moment. An MLB slate spans two UTC dates and one
Central date — which is precisely why the repo chose Central.

The cost was not cosmetic: I deferred the same-book CLV test to "tomorrow" on
that basis. Running it immediately (as the corrected clock implied) is what
exposed both joiner defects above. **A wrong clock deferred a test that found
two real bugs.** Related: [[feedback_report_local_time_not_utc]].

### 2026-08-15 — Pinned deploys do not merge; they REPLACE, so they have to be stacked
- The rule going forward: **before firing a pinned deploy, re-read the
  service's live commit AND check for an in-flight deploy; then pin onto
  whatever is live at that moment, not onto what was live when the branch was
  built.** A pinned branch is a snapshot with an expiry date, and the expiry
  is the next deploy by anyone. Where two lanes are shipping the same service,
  stack — cherry-pick onto their commit — rather than racing from a shared
  base.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-15 — The lane marker is repo-global, so only one session can hold it
- The rule going forward, until the marker is per-session: **if the guard
  blocks a file your own lane claims, read `.current-lane` before assuming a
  real collision.** Take the marker, make the edit, and put back the value
  you found — and tell the session whose slug it was, because their next edit
  will be blocked by yours. Do not "fix" it by closing their lane.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-15 — FORBIDDEN: never run a heavyweight census ON the thread that is doing the measuring
- **The rule going forward:** a diagnostic that can block must run off the
  thread that observes, as a daemon, so that never finishing is survivable. And
  when an instrument goes quiet, the first hypothesis is that the instrument is
  stuck -- not that there was nothing to report. Silence is a state of the
  EMITTER.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-15 — a fix on `main` is not a fix in production: check the DEPLOYED tree

`#423` established that tracemalloc must trace at `nframe=3`, because at one
frame the top site is `decoder.py:353` -- Python's own json module, 491.3MB
across 7,172,382 objects -- which names the ALLOCATOR, not the CALLER. It passed
`3` and the ticket was closed.

**Production was running `start_allocation_tracing(1)`.** The worker said so in
its own boot log the moment tracing was switched on:
`TRACEMALLOC_INIT {"nframe": 1, "reason": null, "started": true}`. The `#423`
fix landed on a lineage this service never ran, and local `main` vs the deployed
lineage have diverged by 149/121 commits.

So the dump would have produced the one answer already known to be worthless,
and it would have been reported as a result.

**How to apply:** before relying on a fix, grep the tree at the LIVE SHA, not the
working copy. `git grep <token> <live-sha> -- <path>` costs one command. This
repo has now been bitten in both directions -- changes live in production and
absent from `main` (2026-08-14 `333af428`), and changes in `main` and absent from
production (this one).

## 2026-08-15 — RULE: WEB DOES NOT RUN `main`. Parent a deploy on the LIVE SHA.

**The fact.** Web's live commit `a86eb4ed` is **not an ancestor of
`origin/main`**. It sits on `origin/deploy/null-placeholder`, which diverged
from main at `b98f5ed7` (08-14 10:18). The deploy branch carries **10 commits
main does not have**; main carries **199** it does not.

**What that costs if you miss it.** `git diff --stat a86eb4ed <any-main-commit>`
= 199 commits, 82 files — and `syndicate/features/shared/clv_join.py` (542
lines) and `clv_opening_ledger.py` (326) appear as **pure deletions**, because
they exist only on the deploy branch. Deploying "the latest main" to web would
have silently reverted another lane's live CLV code plus the board-contract
probability fix, the ncaaf central-day fix, the ask refusal gate, and M1.

**`render_deploy.py`'s rollback guard does NOT catch this.** That guard asks
whether the target is a descendant of the live SHA. A main commit is not a
descendant — but it is not flagged as a *rollback* either; it is simply a
different branch, which the guard has no opinion about. The guard protects
against going backwards on one line of history, not against switching lines.

**The M1 corollary — an ancestry check can give a false negative.** M1 is
`b16eb1f7` on main and `5382943c` on the deploy branch: same change,
cherry-picked, different SHA. `git merge-base --is-ancestor b16eb1f7 a86eb4ed`
returns false while the code is demonstrably live. **Test deployment by CONTENT
(grep the symbol in `git show <live-sha>:<path>`), not by ancestry**, wherever
cherry-picking between branches is in play.

**How to apply.**
1. Read the live SHA from the Render API, never from the ledger.
2. `git merge-base --is-ancestor <live> origin/main` — if false, web is on a
   deploy branch and main is NOT your base.
3. Build the deploy commit as a direct child of the LIVE SHA (plumbing:
   `read-tree <live>` into a temp `GIT_INDEX_FILE`, `update-index` your paths,
   `commit-tree -p <live>`). This also keeps the shared working tree and index
   untouched while other sessions are live.
4. `git diff --stat <live> <target>` must show ONLY your files. That is the
   scope answer preflight asks for, and it is the check that caught this.

### 2026-08-15 — A COUNT OF DEFINITIONS IS NOT A COUNT OF PRODUCERS, and the one it missed was the live bug
- **The rule going forward.**
  1. **Trace the FIELD, not the definition.** Before trusting any "N sites do X"
     count, take one user-visible output of X and enumerate its writers. If that
     number exceeds the grep's, the grep is measuring the wrong population.
  2. **A duplication count justifies a differential, not a fix.** Run the
     duplicates over the boundary inputs before costing a consolidation — the
     bug is where they disagree, and they may agree everywhere that matters.
  3. **Ownership is settled by named requirements, not by cluster size.**
     "The biggest cluster wins" is a vote. Fifteen implementations tied
     behaviourally here; the deciding requirement (refuse a `50.0` percent-scale
     probability rather than clamp it to a plausible `-4900`) was met by exactly
     one implementation of its concept.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-15 — A field nobody reads is the same as the `None` it replaced

**What happened.** Two plan items in one lane — `K5` (surface `routed_sport`)
and `K6` (put an as-of on every answer) — were implemented as new TOP-LEVEL keys
on the `/api/syndicate/query` response. Both worked. Both were invisible.
`scripts/ask_syndicate_regression.py` reads the routed sport from
`context.sport` / `routing_context.sport`, and the as-of from `visuals.as_of`.
The served payload had `routed_sport: "soccer"` at the top level while
`context: {}` sat right beside it, and the harness went on reporting
`no_sport_resolved_expected_soccer` on 8 cases and `no_as_of_stated` on 40.

**Why it nearly shipped.** The in-process probe passed, the served payload
showed the value, and the field name matched the plan's wording exactly. Every
check I ran was a check of MY field. The plan's own sentence contained the
answer and I read past it: K6 says "`visuals.as_of` only populates when a sport
branch matches" — that names the location, not just the symptom.

**The rule.** When the task is "expose X so a consumer can see it", the
acceptance test is the CONSUMER reading it, not the producer emitting it. Find
the reader first and write to where it already looks. Adding a second, tidier
location is not a fix; it is a second place for the value to be right while the
product stays broken.

**How it was caught.** By reading the harness's `_score()` — the thing that
defines the predicate — rather than by trusting the response I had just built.
Cost: two extra measurement cycles. Recovered: `no_as_of_stated` 40 -> 3,
routing failures 15 -> 0, `entity` 0/10 -> 7/10.

Related: `feedback_read_the_field_you_already_have`, and the older rule that a
deployed fix can be inert.

### 2026-08-15 — A single-slot lock in a five-session worktree blocks the RIGHT work

**What happened.** `.syndicate/.current-lane` is one file that every session
writes, and `lane-guard.py` blocks an edit when the file is claimed by an OPEN
lane whose slug != that marker. With five live sessions the marker names
whoever wrote last, so three consecutive edits were blocked on files THIS
session's own OPEN lane exclusively claimed. No cross-lane conflict existed in
any of them — the collision check had already returned 19 claims across 4 lanes
with zero overlap.

**Why it matters more than the lost minutes.** The guard was firing on marker
contention rather than on the thing it exists to catch, and the obvious
workaround — reclaim the marker immediately before each edit — steals it from
whichever session is mid-edit, so every session degrades the others. A guard
that blocks correct work is one people route around, and then it protects
nothing. The file's own docstring admitted the assumption: "lower value while
running a single session".

**The fix, and the shape to copy.** `.current-lane.<session_id>` from the hook
payload, with the global file still read when no per-session file exists. The
fallback is what makes it safe: a session that never opts in behaves EXACTLY as
before, so shared tooling could change under four live sessions without
coordinating a stop. Verified all three paths before relying on it — global-only
still blocks, per-session allows own lane, per-session naming a DIFFERENT lane
still blocks (the guard still does its real job).

**Rule.** Before adding a mutual-exclusion token, ask how many writers exist. If
more than one, it must be keyed per writer. And when patching shared tooling
mid-flight, make the new behaviour opt-in via presence of a new file, never via
a change to the default path.

---

## 2026-08-15 — A CADENCE IS A DISTRIBUTION ACROSS REGIMES, NOT A CONSTANT

**The belief.** "MLB quote capture runs on a metronomic ~121.6-minute beat." It
sat in `state.md` with a proper measurement behind it (seven captures in 18h,
read from the artifact rather than the logs — good method), it was carried into
the program plan as a hard floor on the Tier 5 measurement, and it was the
premise of a standing freeze on 23 movement implementations, `movement_velocity`
and the steam detector.

**What was actually true.** The same read, taken over the FULL day instead of a
daytime window — all 371,567 rows of the shard, bucketed by distinct
`captured_at` — shows three regimes:

    07:03→15:10  pregame, nothing live   121 / 121 / 123 / 121 min
    16:20→18:25  first games start        70 / 61 / 64 min
    18:36→20:54  ramping                  11–12 min
    21:48→02:53  full live slate          ~1 min, continuous

121.6 is exact **and it is the empty-slate pregame number only**. The same
pipeline samples 122× faster once games are live, because the 1800s cooldown is
reached only through `effective_phase == "pregame"` and is bypassed entirely
while `anyLive` is true.

**Why the original was not a sloppy measurement.** It sampled a real regime
correctly. The error was in the *quantifier*, not the number: a rate measured in
one regime was promoted to a property of the system. The window was daytime, and
the system's behaviour is defined by whether a slate is live — a variable the
window held constant without anyone choosing to.

**The second-order cost, which was the expensive part.** The wrong constant
propagated into a plan as a *prerequisite* — "0.1 is a prerequisite for the
measurement meaning anything" — so a measurement that could have been taken any
evening was deferred behind a deploy that does not gate it.

**And the freeze it justified was aimed at the wrong thing.** The movement
family is not computing on a 2-hour signal; it samples at ~1/min. Its real
constraint is `_ODDS_HISTORY_LIMIT = 20`: 3,130 of 3,582 markets sit exactly at
the cap, so the retained window is ~18 minutes, and the code's own comment
already conceded that is "narrower than the steam detector's stated 45-min
window." A movement calculation is structurally blind to whether the previous
sweep was 1 minute or 2 hours earlier — the pregame→live transition, the largest
move of the day, falls out of the buffer within 20 minutes of first pitch.

**Rules.**

1. **Before quoting a rate, name the regime it was measured in and say whether
   the system has others.** "Sampled every N" is a claim about a distribution.
   If the driver is a state variable (live/pregame, in-season/out, peak/off-peak),
   one window that holds it constant measures one regime, not the system.
2. **When a plan makes fix X a prerequisite for measurement Y, check that X is
   actually on Y's path before deferring Y.** Here the gate was guarded by a
   phase condition that was false for the entire measurement window.
3. **A freeze on a whole family of work is a large claim and deserves its own
   measurement.** "Nothing in that family should be trusted until the real
   sampling interval is known" was right to demand a number and wrong about
   which number. The binding constraint was buffer DEPTH, not sample RATE — and
   depth was a constant in the source with a comment already admitting the
   problem.

---

## 2026-08-15 — ANCESTRY OF `origin/main` IS NOT DEPLOYMENT; READ THE DEPLOYED TREE

**The near-miss.** Asked whether the per-sport pregame cooldown had shipped, the
first check was `git merge-base --is-ancestor ea8fad58 origin/main` → **yes**.
On a repo where `autoDeploy = no`, that answer means nothing about production,
and taken alone it would have reported a fix as live that is not.

The commit had also been *rebased* — the plan named `9ec20a06`, which is NOT an
ancestor of `origin/main`, while its rebased twin `ea8fad58` is. So the two
obvious checks disagreed with each other, and both were the wrong question.

**What settled it.** Read the file out of each deployed commit and look at the
signature:

    git show 548ded38:syndicate/features/shared/live_refresh_loop.py \
      | grep "def _pregame_relaunch_blocked"

→ `def _pregame_relaunch_blocked(*, now_epoch: float, date_str: str) -> bool:`,
no `sports` kwarg, on **both** worker commits. Not deployed, decisively, on the
services that matter — independent of branch topology, rebases, cherry-picks and
force-pushes.

**Rule.** To answer "is this fix running", read the changed SYMBOL out of the
deployed SHA — `git show <deployed-sha>:<path>` — not the commit's presence in
any branch. Branch membership answers "is it merged". Those are different
questions on every service with `autoDeploy` off, and they are different
questions on every repo where commits get rebased. This is the same family as
`test the fix's predicate, not its deploy state` — the predicate here is the
function signature, which is cheap and unambiguous.

## 2026-08-15 — RULE: a "baseline" is a FILE you diffed, not a number you quoted

Two errors in one measurement, both from treating remembered numbers as data.

**1. The baseline file was a different shape than the prose said.** Every lane
tonight baselines against "post-M1 **23/52**" citing
`reports/ask_regression/post_m1_fixed_2026_08_14.json`. That file contains
**10 results and reads `passed: 4`** — a `--classes ranking` run. The 23/52
exists only in prose. A diff script printed `baseline 4/10 -> now 24/52` and
that mismatch is the only reason it was caught. **Load the baseline and print
its `total` before comparing anything to it.**

**2. The causal probe read a field that does not exist.** To attribute a refusal
regression I read `payload["recommendations"]`, got `0` three times, and
reported "fully attributed". `build_syndicate_query_response` **does not return
a `recommendations` key** — the reads were `None`, not zero. Against a real
same-slate control the regression was **1 case, not 3**. The mechanism was
right and the magnitude was 3x wrong, stated with more confidence than anything
in the chain supported.

**How to apply.**
- Before quoting a baseline, open it and assert its shape (`total`, class list,
  `base_url`, `generated_at`). A ranking-only run and a full run are not
  comparable and nothing in the filename says which it is.
- A control must be measured on the SAME SLATE. This board changes by the
  minute; a number from four hours ago is a different experiment, not a
  baseline. The honest control here cost one 8-case run against the rolled-back
  deploy, and it changed the finding.
- When a probe returns a suspiciously clean `0` for every case, check the key
  EXISTS before building an attribution on it. `dict.get` cannot tell absent
  from zero, and neither can a conclusion drawn from it.

### 2026-08-15 — A PER-CLASS MEASUREMENT OVER A SHARED STYLESHEET IS A PER-SURFACE MEASUREMENT, OR IT IS WRONG
- **The rule going forward:** a shared stylesheet exists precisely so one class
  renders in more than one place, so **one sample per class is not a
  measurement of that class** — key the table by surface and report a class
  whose computed value differs across surfaces as CONFLATED rather than
  collapsing it to its first hit. `scripts/ui_layout_probe.py` now does this
  and the whole story is in `docs/reports/ui_audit_2026_08_14/README.md`,
  because the wrong number outlived the probe that produced it and got written
  into two plans.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-15 — A PROBE THAT PASSES ON AN ERROR PAGE. Attach the liveness check to the SAME fetch
- **The rule going forward:** an instrument that derives its numbers from a
  fetched document must assert the FETCH before it reads the document, in the
  same call — not in a separate health check that can pass at a different
  instant. And a "not present" count needs a named reason to be allowed: the
  probe now fails on `>= 400`, and fails on 0 cards unless the sport is in an
  explicit `OUT_OF_SEASON` set that carries a review date. An exemption with a
  name is auditable; a tolerated zero is not.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-15 — DE-DUPLICATING A FIELD IS NOT DE-DUPLICATING THE OUTPUT. Look at what the fallback renders
- **The rule going forward:** when you remove a value that was being repeated,
  render the result before believing it. `a or b` means deleting `a` PROMOTES
  `b`, and in a list `b` is usually the more constant of the two. The real fix
  was structural: the section repeating the data had nothing of its own to say,
  so it was gated out entirely rather than fed a different string.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-15 — `GIT_INDEX_FILE` PROTECTS YOUR COMMIT AND LEAVES THE SHARED INDEX HOLDING A REVERT OF IT
- **The rule going forward:** the isolated-index recipe has a second half.
  After committing with `GIT_INDEX_FILE`, run
  `git reset -- <the same paths>` against the SHARED index so it matches the
  new `HEAD`. Check `git diff --cached --name-only` first: if other paths are
  staged, they are someone else's and a path-scoped reset is the only safe
  form. This is the same family as "`git status` is not `git diff --cached`",
  but the causal direction is the part that was missing — **we generated the
  revert ourselves, by following the recipe.**
- *(evidence in `learnings_evidence.md`)*

### 2026-08-15 — a scoped search answers a scoped question. I shipped a field's semantics on one, and the unscoped search later named the test that guards it
- **The rule going forward:**
  1. **A scoped search bounds the answer to the scope.** `syndicate/` does not
     contain `tests/`. When changing a field's SEMANTICS, search `tests/`
     explicitly — the guard for a served field usually lives there and nowhere
     else.
  2. **Follow the artifact hop.** Consumers that read a producer's output
     through an artifact reader (`read_*_artifact`) never import the producer,
     so an importer search cannot see them. Search the FIELD NAME, not the
     module.
  3. **If a search times out, say so and treat it as unknown**, or re-run it
     scoped and narrow. Do not let an abandoned search read as coverage. The
     unscoped variant here also needed `.claude/worktrees/` excluded — those
     hold full repo copies and triple-count every hit.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-15 — FORBIDDEN: never put `$$` (or any per-shell value) in `GIT_INDEX_FILE`. Each Bash call is a NEW shell, and an absent index file is an EMPTY one, not an error
- **The rule going forward:**
  1. `GIT_INDEX_FILE` must be a **literal, stable path** (`C:/tmp/idx-<lane>`),
     never interpolated from anything shell-local.
  2. **Do the whole read-tree → add → verify → commit sequence in ONE Bash
     call.** Splitting it across calls is what let the two paths diverge.
  3. **Guard the commit, do not just eyeball it.** Abort on file count and on
     total deletions before `git commit` runs, in the same shell:
     `test "$DEL" -le 100 || exit 1`. `git diff --cached --stat` read by a human
     one call earlier describes a DIFFERENT index than the one about to commit.
- **Second thing this cost, and it is the more dangerous one:** the same commit
  would have swept in **A3a (score monotonicity)**, which sits uncommitted in
  the shared tree's `opportunity_signals.py` and which `state.md` holds back
  pending a pool-side counter. Staging a file wholesale in this worktree stages
  whatever seven other sessions have left in it. The fix is to stage a
  **HEAD-blob plus your own hunk** (`git show HEAD:<path>` → splice → `git
  hash-object -w` → `git update-index --cacheinfo`) and assert
  `out.replace(mine, "") == base` so any other drift aborts the build.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-15 — COMMITTING THROUGH AN ISOLATED INDEX LEAVES THE SHARED INDEX STAGING A DELETION OF THE FILE YOU JUST COMMITTED

**The recommended safety practice creates the exact hazard the guard exists to
catch, and it does it silently, every time.**

Sequence, reproduced this session:

1. `GIT_INDEX_FILE=<tmp> git read-tree HEAD && git add -- <new file> && git commit`
   — correct, scoped, exactly what `state.md` tells you to do.
2. HEAD now contains the new file. **The SHARED index does not** — it was never
   touched, so its entry for that path is "absent".
3. Absent-in-index + present-in-HEAD = **a staged DELETION** of the file you just
   committed. `git diff --cached --stat` in any session now reads
   `463 deletions(-)`.
4. Any session running a bare `git commit` un-ships it, working tree clean.

`commit-guard.py` fired and blocked it, which is the system working — but note
**what** it blocked: my *next, unrelated* commit, because the guard reads the
SHARED index while my commit was going through an isolated one. The guard cannot
see your isolated index, so its verdict is always about the shared one.

**How to apply.** After every isolated-index commit, repair the shared index:

    git restore --staged <the paths you just committed>

Index-only; it cannot disturb any session's working-tree edits. Then
`git diff --cached --stat` should be empty.

**The general shape:** an isolation mechanism that makes YOUR operation safe can
leave SHARED state describing a change nobody intended. Isolation bounds your
blast radius; it does not bound the blast radius of what you leave behind.
Related: `project_shared_index_can_hold_a_revert` — this is the mechanism by
which that revert gets there without anyone doing anything wrong.

### 2026-08-15 — A DATE TEST WRITTEN IN THE FORMAT THE CODE ALREADY HANDLES CANNOT DETECT THAT IT ONLY HANDLES THAT FORMAT
- The rule going forward: **when a test exercises parsing or comparison of an
  external format, write the fixture in the format the SOURCE ships, not the
  format the code prefers — and confirm what the source ships by reading it.**
  One `head -1` of each committed file would have shown two formats. Also:
  a same-shape bug hid two more (30th/31st dropped as "future"; the text sort
  behind `rows[-window:]` selecting "latest in the month" rather than "most
  recent"), so a format mismatch is rarely one bug.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-15 — A GUARD'S STATED REASON IS A CLAIM ABOUT ANOTHER FUNCTION, AND IT ROTS WITHOUT TOUCHING EITHER FILE
- The rule going forward: **a comment that justifies a refusal by describing
  what ANOTHER function does is a dated assertion about a file that can change
  without this one being touched. Re-run the named function before trusting
  it.** Neither file's history shows anything suspicious — the rot is in the
  relationship, so no diff review of either file would surface it.
- Corollary that nearly cost more than the finding: **removing a stale guard is
  not the same as the result being safe to publish.** Once the edges appeared
  they were -27.7 and -49.9 points, which reads as alpha and is actually
  under-dispersion (model stdev 0.1364 against a market pricing a -500
  favourite at 0.779). Unblocking a number and validating it are two tasks.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-15 — I QUOTED THE "A BRANCH CUT FOR ONE SERVICE IS A ROLLBACK FOR ANOTHER" RULE, THEN BROKE IT ONE NOTE LATER
- The rule going forward: **before naming any branch as a commit base, diff it
  against `origin/main` in BOTH directions and read the deletion count.**
  "It has the prerequisite I need" says nothing about what it is missing. The
  right shape for an unmerged prerequisite is to rebase it onto the current
  tip, never to rejoin the tree at the old one.
- The transferable half: I had quoted this exact rule from `state.md` earlier
  in the same session. Knowing a rule and applying it to the artefact in front
  of you are different acts, and the cheap mechanical check is what closes the
  gap.
## Compacted entries (rule kept here, evidence in `learnings_evidence.md`)
> Compacted 2026-08-15: entries before 2026-08-15 keep their heading and their
> rule. Nothing was deleted. The full working — what we believed, how we
> found out, the cost — is in `learnings_evidence.md` under the same heading.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-12 — FORBIDDEN: never point a worker publish URL at a public hostname
- The rule going forward: **any service-to-service call inside Render must use the internal private-network hostname. Same-region private traffic is unbilled. Audit every URL env var against this rule before adding a new one.**
- *(evidence in `learnings_evidence.md`)*

### 2026-08-13 — A guard can measure a number that moves without the system moving
- The rule going forward: **when a threshold decides whether work runs, audit what moves the quantity it reads — not just the constant.** A stale constant is the easy half. A quantity that swings on kernel LRU bookkeeping makes the guard's verdict unrelated to the risk it guards. Guard on unreclaimable memory (`anon + shmem + slab_unreclaimable`), which is what an OOM kill actually responds to.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-13 — A criterion has a DIRECTION, and checking it is free
- The rule going forward: before instrumenting, ask **which way the suspected fault would push the observable.** Extends "a criterion is an instrument too": an instrument has a sign as well as a denominator.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-13 — Confirm an instrument can emit non-zero before believing its zero
- The rule going forward: before believing a zero, produce a case that makes the same instrument read non-zero — or build the reading so it carries its own liveness proof. `snapshot_prop_keys` is populated before any filtering, so a zero beside a non-empty key list is a *measured* zero, not a blind one.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-13 — A pooled denominator can make a measurement unreadable
- The rule going forward: when a counter pools populations with different eligibility, **split it by the thing that determines eligibility** before reading it. "The mechanism failed" and "most rows were never eligible" produce the identical zero. Sibling of the wrong-denominator shape recorded the same night, arrived at from the other direction.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-13 — `git log --format=%an` is zero evidence in this repo
- The rule going forward: **the only working discriminator is which FILES a lane has touched.** Verify a ticket number against `origin/main` immediately before pushing, not when drafting — the gap between choosing and pushing is a real race.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-10 — an instrument's blind spot will be mistaken for a finding
- The rule going forward: **ask what the instrument cannot see before trusting what it shows, and compute the base rate before believing a coincidence.** Both directions of this error were made in one evening on the same candidate.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-10 — segment on process boundaries before any neighbour-based test
- The rule going forward: **any local/neighbour test must segment on boot first.** A restart is a discontinuity, not a data point.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-10 — counts are the wrong denominator when the cost is bytes
- The rule going forward: **before quoting a rate, check the denominator actually measures the thing being paid for, and that it spans the population of interest.**
- *(evidence in `learnings_evidence.md`)*

### 2026-08-13 — Presence is not reachability: verify the PATH, not the symbol
- **Overturned belief:** that confirming a fix is present in the deployed code
- *(evidence in `learnings_evidence.md`)*

### 2026-08-13 — A safety gate answers ITS question, not the one you were asked
- The rule going forward: **when a human states a condition, encode THAT condition, not the nearest existing check.** A pre-built guard is evidence about its own predicate only. Before arming any watcher, write down the instruction's condition and the instrument's condition as two separate sentences; if they are not the same sentence, the instrument is not sufficient and needs the missing clause added explicitly.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-13 — "Identical to origin" does not mean "absent from the commit"
- The rule going forward: **to claim a change is ABSENT from a deploy, compare the target against what is LIVE, not against the branch you built on.** The live commit is the only baseline the deploy actually acts on, and it moves under you while you work.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-13 — "Who reads this env var" is a grep question; "does this service read it" is not
- The rule going forward: **reachability has three entry classes, and a trace that omits any one of them is not evidence. (1) module-level statements, including calls to functions defined elsewhere in the file; (2) the specific symbols another module imports — not the module as a whole; (3) indirect targets: thread/process `target=`, callbacks, registries, decorators.** Exclude `if __name__ == "__main__"`. A negative result from an incomplete trace is indistinguishable from a real one, so state which classes were covered whenever the conclusion is "unreachable, safe to delete."
- *(evidence in `learnings_evidence.md`)*

### 2026-08-13 — FORBIDDEN: never `cat` a ledger file into hook stdout — a hook delivers the obligation, not the content
- The rule going forward: **a hook is a channel with a budget, and the only measurement that counts is what ARRIVES, not what was emitted.** Verify a hook by reading the `attachment` record in the consuming session's transcript (`stdout` length, `exitCode`, `type`), never by running the script in a terminal — a terminal has no cap, so it can only ever confirm the emitter. Keep hook stdout under **2,000 B**. A hook's job is to deliver the OBLIGATION to read the ledger plus the few facts too costly to miss; the ledger itself gets read from disk by the session. Direct sibling of `2026-08-13 — Presence is not reachability`: the content was present at the emitter and unreachable at the destination.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-13 — EXONERATED: `shell: "bash"` in a Windows hooks block works
- Named as the likely culprit when SessionStart could not be verified ("if the ledger doesn't appear, the likely culprit is `shell: "bash"` not being honored"). Measured working: session `ac67a9f1`, Claude Code **2.1.227**, `hookName=SessionStart:startup`, `exitCode=0`, `durationMs=459`, `stderr` empty, `type=hook_success`, on a `.sh` script invoked as `"$CLAUDE_PROJECT_DIR"/.claude/hooks/session-start.sh`.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-13 — A guard that has never once PASSED is not a guard
- The rule going forward: **a guard's pass branch needs a witness too.** The ledger already says "before believing a zero, produce a case that makes the instrument read non-zero" — this is the same rule pointed at the other branch. An alarm that has never been silent is indistinguishable from an alarm wired to a constant. Check the distribution of a guard's outcomes before quoting any single one: all-fire and all-pass are both evidence of a broken predicate, not of a system state.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-13 — A discriminator that is only emitted on FAILURE cannot confirm a fix
- The rule going forward: **when choosing a signal to prove a fix ran, check which BRANCH emits it.** A signal on the failure path proves the failure path; it can never prove the success path. Before deploying, ask "if this works perfectly, what line appears?" If the answer is "none", there is no liveness proof and the deploy ships blind, however green the tests were.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-13 — A watcher's headline can contradict its own body
- The rule going forward: **the label a script prints is an assertion, and it must be entailed by the condition that triggered it.** When writing a watcher, state the exit condition in the output next to the verdict, so a reader can check the inference rather than trust the adjective. Sibling of `an instrument's SPAN is not its NAME` — same failure, moved from a timing mark to a boolean.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-13 — A guard's "is this mine" input must not default to the locked state
- The rule going forward: **when a guard reads an identity token to decide "yours vs theirs", the absent case must default to PERMISSIVE-with-a-reason, not to deny.** Absent identity is not a hostile identity, it is a missing input, and the failure surfaces as a confusing cross-lane collision message rather than as "the marker is missing". Same shape as the ledger's `unknown must not default permissive`, inverted: there the danger was a failed join relaxing a rule, here it is a failed join inventing a conflict.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-13 — A path one toolchain resolves and another cannot makes a guard pass silently
- The rule going forward: **this machine has two path universes, and a value that crosses between them fails open rather than erroring.** Bash-tool paths (`/tmp`, `/c/...`) are invisible to native Windows Python and to `python3` invoked from PowerShell; `git cat-file blob origin/main:path` is mangled by MSYS arg conversion into `origin\main;path` and returns an empty pipe, not an error. Fixtures and payloads handed to a Windows interpreter must use `C:/...`. When a check produces no output at all, verify it reached its own code before believing its verdict — extends `2026-08-13 — Confirm an instrument can emit non-zero before believing its zero`.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-13 — A free-text status field cannot be a predicate; test guards against the ledger, not against synthetics
- The rule going forward: **a guard whose input humans hand-write must be tested against the actual file, not against examples written by the same person who wrote the guard.** Re-run guards over the live ledger after any parsing change, and diff the set they classify as open against the lanes physically under `## OPEN` — a mismatch is the whole test. Where a field is free text, match a word (`\bOPEN\b`), never the whole field, and never a bare substring.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-13 — A discriminator that only emits on FAILURE cannot confirm success
- The rule going forward: **when choosing a liveness signal, ask which branch emits it. If the only emitter is the failure path, the signal cannot distinguish "working" from "never ran" — the two produce identical silence.** Put the proof on the path you expect to take, not on the one you are trying to eliminate. Direct sibling of "confirm an instrument can emit non-zero before believing its zero"; that entry covered a zero, this one covers a total absence, which is worse because nothing appears at all.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-13 — A watcher's LABEL must be entailed by its exit CONDITION
- The rule going forward: **the words a monitor prints are a claim; write them from the condition that fired, not from the outcome you are hoping for.** Before trusting a watcher's verdict, re-read the branch that produced it. Any word in the label that does not correspond to a term in the predicate is editorial.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-13 — "Pushed to origin" is not "applied to production"
- The rule going forward: **for `render.yaml`, "on origin" and "in effect" are two different measurements, and only the second one matters. Read the live service's `/v1/services/<id>/env-vars` and compare counts before recording a config change as shipped.** The CLAUDE.md warning that a push applies to production is about the *risk* that a sync fires; it is not a guarantee that one *has*. Both errors are available, in opposite directions.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-13 — FORBIDDEN: never edit a file from a read taken earlier in the session
- The rule going forward: **before editing any file, re-read it, and read the config that dispatches to it.** A hook, handler or entrypoint is defined by what invokes it, not by its filename. On a shared tree the gap between reading and editing is a race, and `Write` silently resurrects a deletion rather than failing — a deleted file and a file you have not re-read are indistinguishable from the editor's side.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-13 — The enforcement layer cannot protect itself, and a lane is one deletable line
- The rule going forward: **`lanes.md` is executable configuration, not documentation, and it is edited by hand by several sessions at once.** After ANY concurrent-session ledger edit, re-run the guard over the files that matter rather than trusting the file to still say what it said. The cheap check is one line: `awk '/^### /{h=$0} /<path>/{print h}' .syndicate/lanes.md` — if a file's nearest preceding header is not the lane you expect, the block is orphaned. And harness work needs either a stated exemption in the protocol or a real lane; three sessions deciding it individually is how the one collision that mattered happened.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-13 — A FAILED READ RENDERS AS A RESULT. Five instances, one session, five different tools
- The rule going forward: **before believing a negative result from a one-off check, run the positive control.** Grep for something you KNOW is in the file; if that also returns 0, the probe is broken, not the world. It costs one command and it caught nothing this session only because it was skipped. Corollary: `grep -c` on a pipeline whose upstream can fail is not a count, it is a count-or-zero. Check the upstream exit status, or query a way that cannot silently produce an empty stream.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-13 — The stale-read rule failed on its second application, in a form it did not cover
- The FORBIDDEN entry above ("never edit a file from a read taken earlier in the session") was written after a rewrite of a file that had been deleted. **Within the same session it was broken again**, differently: a defect was REPORTED against `lane-guard.py` — "`memory-guard-reclaimable` is unguarded, its status parses as DEPLOYED" — derived by running a copy of `LANE_RE` lifted from a read taken ~2h earlier. `559d353d` had already replaced that regex, and its comment names that lane as the motivating case. The claim was false when written, and it was published to `state.md`, where a parallel session could have acted on it.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-13 — A guard has TWO failure directions, and fixing the loud one is where the silent one survives
- The rule going forward: **a guard's scope and its witness must have the same granularity.** Per-session denominator + global witness is not a fix, it is the same hole rotated — and rotated toward the silent direction. Whenever a guard is narrowed, ask what else can satisfy it, not just what it now counts. Concretely: **when fixing a guard that fails in one direction, write the test for the opposite direction in the same pass**, and for anything on a shared tree that means a two-actor test — one fixture where a second session's action is what changes your verdict. A single-actor fixture suite cannot express the failure that matters here, however many cases it has.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-13 — Cite the SHA that will exist on origin, not the one your clone minted
- The rule going forward: **write the SHA after the push, and write the one that is on `origin`.** If a commit must be referenced before it is pushed, cite the commit SUBJECT — the subject survives cherry-pick, the SHA does not. Deploy SHAs read from the Render API are already origin SHAs and are fine as they are. Session ids are visually identical to short SHAs; always prefix them with `session`.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-13 — MY OWN DISPLAY TRUNCATION BECAME A FINDING, AND THEN A LANE'S PREMISE
- The rule going forward: **a slice width is a property of your printout, not of the record. Never read a numeric field out of a truncated line.** When a value is load-bearing, re-fetch it untruncated and print the field, not a prefix of the message. Corollary for surprise: **the more a datum overturns the expected answer, the more it must be re-read at full width before being written down** — surprise is the signal to verify, not to publish.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-13 — A BROKEN GUARD CAN MASK THE REAL PROBLEM. Fixing it is how you find out
- The rule going forward: **when a guard is found to be reading the wrong quantity, do not assume the alarms it raised were all false. Re-derive what the CORRECT quantity was doing over the same window.** Had `anon` been read on the `#417` samples with the same care as `inactive_file`, the flat +18.9MB would have been noticed as the thing that made `#417` bookkeeping — and its later non-flatness would have been the leak, visible hours earlier.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-13 — Symptom relief resets the clock that would have proved the cause
- The rule going forward: **before restarting to clear a symptom, capture the series that proves the cause** — here, `anon` over time, which is one log query. A restart is not neutral: it is the deletion of the measurement. Record the pre-restart numbers in the row, not just "restarted, recovered".
- *(evidence in `learnings_evidence.md`)*

### 2026-08-13 — Check whether the obvious fix was already tried, BEFORE building an instrument
- The rule going forward: **before instrumenting a known-hard problem, read what the codebase already says about it.** The answer to "don't we need a flush" was 50 lines of measured prose in `memory_observability.py`. An hour of sampler-building preceded finding it.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-13 — I RETRACTED POINT-SAMPLING, THEN BUILT A HEADLINE ON IT ANYWAY
- The rule going forward: **when you retract a METHOD, re-audit every live conclusion that used it, not just the instrument that exposed it.** A retraction is not local to the tool that failed; it is a statement about a class of evidence. Grep your own ledger for numbers derived the same way before the retraction goes in.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-13 — A habit that fails silently needs a tool, not more care
- The rule going forward: **when the same mistake recurs and its signature is indistinguishable from success, stop resolving to be careful and change the shape of the operation.** `scripts/push_via_worktree.py` resolves every SHA in the main repo BEFORE a worktree exists, and treats an empty payload as a hard error naming that exact cause. The class of bug is now unreachable rather than merely watched for.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-14 — A TROUGH THAT CLEARS AN EARLIER PEAK IS A RATCHET. That is the test
- What we believed, three times in one evening, each time on the evidence available: (1) refresh-worker leaks ~300MB/hour [from two point samples]; (2) no leak is established, it may be a 1550MB oscillation [after measuring the within-window spread]; (3) the leak is real at ~+1200MB/hour [after 45 minutes of floor series].
- *(evidence in `learnings_evidence.md`)*

### 2026-08-14 — I RE-READ THE DEPLOYED SHA BEFORE EVERY *READ* AND SKIPPED IT BEFORE A *WRITE*
- The rule going forward: **re-read the live SHA inside the same step that deploys, and assert the target is a descendant of it.** "I checked a few minutes ago" is not a check on a repo with concurrent sessions. A deploy tool should refuse when `merge-base --is-ancestor <live> <target>` fails — that single assertion turns this class of accident into an error message.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-13 — A "PURE READ" endpoint is a reader you will not find by grepping the attach
- The rule going forward: **when a fix's observable is served by an endpoint, ask what BUILDS the payload that endpoint returns, not which functions mutate it.** For anything artifact-backed the answer is usually a different service, and "the code is deployed" then says nothing about the reading. Find the readers from the DATA (who writes this artifact, who reads it) rather than from the function name.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-13 — A CONSTANT that reproduces exactly is a data outage, not a weak model
- The rule going forward: **before treating "every row is identical" as a modelling defect, reproduce the constant from an empty input.** If it matches exactly, the bug is upstream in data availability or file selection, and every hour spent in the model is wasted. `#377` sat OPEN and UNOWNED for days as a product decision about what a board may assert; it was a file-selection bug the whole time.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-13 — A FIXTURE THAT OMITS A MARKER FILE TESTS A DIFFERENT DIRECTORY, AND SCORES IT AS A DEFECT
- The rule going forward: **a fixture that selects a resource by CONVENTION must assert which resource it actually selected, before it is allowed to render a verdict.** Concretely: print the resolved root/path/connection and compare it to the intended one, and abort if they differ. v2 does exactly that (`if resolved -ne $root { ABORT: this fixture tests nothing }`) and the guard then passed all three checks plus a positive control.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-13 — CLOSING A TICKET IS A SCOPE DECISION, AND WHOLESALE CLOSURE SILENTLY RETIRES THE PART NOBODY WORKED
- The rule going forward: **before closing a ticket, enumerate its distinct claims and resolve each one separately. Any claim without evidence gets carved out into its own ticket, with a forward reference from the closure, BEFORE the parent is marked closed.** A ticket is not an atom; long entries in this repo routinely accrete a second and third finding under the original headline, and the accreted ones are the least likely to have an owner.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-14 — A PLATEAU IS A STRONGER SIGNAL THAN A PERCENTAGE
- **The rule going forward: when attributing growth, look for what STOPS growing, not for what is large.** A percentage describes one instant and can be high for uninteresting reasons; a plateau against a rising total is a structural statement and needs no threshold to interpret. Same shape as the trough-vs-earlier-peak test recorded hours earlier — both replace "how big is it" with "what does it do over time", and both settled a question that a single number had left ambiguous twice.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-14 — I MEASURED A STAGE WITHOUT THE THING THAT DOMINATES IT, AND ALMOST SHIPPED THE FIX
- The rule going forward: **before quoting a measurement, ask which input dominates and whether the run contained it.** A partial run does not produce a smaller version of the answer — it produces a different answer wearing the same units. Coverage is not a confidence interval on the number; it decides whether the number is about the thing at all.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-14 — A guard's floor is a claim about ONE stage; refusing everything downstream of it is a separate bug
- **The rule going forward: a memory floor is a claim about the cost of ONE stage. Before putting a guard in front of a span, enumerate what is inside the span and what each part costs. If the span contains work an order of magnitude cheaper than the floor, the guard is not protecting that work — it is deleting it.** The cheap work needs its own, measured floor, and the abort line needs to say WHICH floor fired or the two become indistinguishable in the logs.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-14 — A CADENCE IS NOT AN OUTAGE, AND I ESCALATED ONE AS THE OTHER
- What I believed, and told the user in bold: MLB odds "have not been refetched since 8:09am CDT, now 2h10m and counting", framed as a capture stall worth chasing. I had two independent readings 78 minutes apart showing the freshest observation frozen at the *identical* instant, which felt decisive.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-14 — A CONSTANT THAT REPRODUCES EXACTLY FROM AN EMPTY INPUT IS A DATA OUTAGE, NOT A WEAK MODEL
- The rule going forward: **before treating "every row is identical" as a modelling defect, reproduce the constant from an empty input.** If it matches, the bug is upstream in data availability or file selection and every hour spent in the model is wasted.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-14 — A LANE LEFT OPEN AFTER ITS WORK SHIPS IS AN ACTIVE LOCK, NOT A STALE NOTE
- The rule going forward: **close a lane when its measurement lands, not at checkpoint.** The ledger already treats an unmeasured deploy as an open obligation; an unclosed lane is worse, because it also blocks other people.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-14 — `git add <paths>` SCOPES THE INDEX; ONLY A PATHSPEC ON `commit` SCOPES THE COMMIT
- The rule going forward: **on a shared tree, always `git commit -- <paths>`.** Check `git diff --cached --name-only` BEFORE committing and the commit's `--stat` AFTER. And note the argument order: `-m`/`-F` must come BEFORE the `--`, or git reads the message as a pathspec.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-14 — DECOMPOSE BIAS BEFORE PUBLISHING A SKILL VERDICT
- The rule going forward: **before writing any skill verdict, subtract the mean error and re-score.** Report `mae_model`, `mae_constant_baseline` AND `mae_debiased` together. A model that beats the baseline only after de-biasing is a calibration ticket, not a dead model, and the three numbers side by side are what make that legible. MAE alone cannot separate them.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-14 — A GUARD MUST COUNT THE ROWS THE STATISTIC USES, NOT THE ROWS THE JOIN PRODUCED
- The rule going forward: **a guard's denominator must be the denominator of the thing it is guarding.** If a statistic is computed over a subset, the gate counts the subset. Print BOTH — "361 joined, 9 with a projection" — because the gap between them is itself the finding: here it was the whole story (a column added 13 days earlier), not a footnote to a skill result.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-14 — THREE wrong root causes in one session, one shape: a single sample of a moving quantity
- The rule going forward: **before concluding from an absence or a single reading, ask "what is the period of this thing?" and take a span longer than it — or read the durable state instead of the event stream.** And when a finding rests on a constant, read the whole comment AND the call sites of the function that owns it before publishing; the disconfirming sentence was already written in the file all three times.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-14 — I CALLED A CORRELATION A PROOF, TWICE IN ONE SESSION
- What I believed: the soccer odds gap was step truncation. The evidence felt airtight — the pregame run is 50 steps grouped by kind, odds sit at #21-30 behind ten sims, and the fresh/dark split matched the step order with **no exceptions**: `soccer_eredivisie_odds` #27 current, #28/#29/#30 all 3.6 days stale. I wrote "ROOT CAUSE PROVEN" into the lane, shipped a reorder, and told the user it was the fix.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-14 — A HEALTHY-LOOKING SIBLING MASKED A PLATFORM-WIDE OUTAGE
- What we believed, for most of a session: three soccer leagues had a broken odds capture while eredivisie was fine. The contrast WAS the evidence — same script, same key, same region, one works — and it drove three successive hypotheses (season gate, step truncation, per-league fetch fault), two of which were shipped against.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-14 — A fallback CHAIN has a rung that fires; find it before costing the fix
- The rule going forward: **when a defect is described as "it falls back to X", the fix is worthless until you know which rung actually fires.** Removing the last rung of a chain whose third rung always fires is an inert fix that will be reported as shipped. Enumerate the chain, find who writes each key upstream, and exercise the function once per shape before estimating impact or urgency.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-14 — A MANGLED SHELL ARGUMENT NEARLY BECAME "THE LEDGER LOST MY WORK"
- What I believed for about ninety seconds: the retraction and root cause I had just pushed were NOT on `origin/main`. Four greps, all returning 0, against files I had verified before pushing.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-14 — A watcher that compares TIMESTAMPS to identify a thing will misidentify it by microseconds
- The rule going forward: **to answer "is this still the same thing", compare the IDENTITY, not a timestamp derived from it.** The fix was one line — check the deploy's commit SHA against the SHA the window opened on. A timestamp is a measurement of an event; the SHA IS the event. Identity comparisons do not have precision, and precision is where this class of bug lives.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-14 — I PREDICTED FILE OWNERSHIP INSTEAD OF PROBING IT, TWICE
- What I believed, twice, and wrote into a checkpoint as a blocker: that `scripts/refresh_odds_sources.py` and then `scripts/run_live_odds_refresh_worker.py` were claimed by other OPEN lanes and would need a reassignment before I could touch them. The second one was handed to the next session as "needs a lane reassignment or their owner".
- *(evidence in `learnings_evidence.md`)*

### 2026-08-14 — PINNED DEPLOYS PUT CODE IN PRODUCTION THAT WAS NEVER ON MAIN
- What I believed at three consecutive checkpoints: everything I had shipped was on `origin/main`. I had verified the ledger content each time, and the reorder commit, and reported "all content is on origin".
- *(evidence in `learnings_evidence.md`)*

### 2026-08-14 — Separating `add` from `commit` is not enough if you chain them with `&&`
- The rule going forward: **the inspection must be its own tool call, with the commit in a LATER call.** And prefer the pathspec form, which makes the index state irrelevant:
- *(evidence in `learnings_evidence.md`)*

### 2026-08-14 — A saturated log window proves nothing, and the untouched sibling is the control
- The rule going forward: **when you suspect a change caused a symptom, find the sibling that did NOT get the change and look there first.** A same-config, same-moment, untouched service settles causation in one query, while before/after windows on the affected service can be silently truncated. Corollary: **a log window that returns exactly `limit` rows is evidence of nothing absent** — re-query narrower until it comes back under the cap, or count POSITIVE markers (`PUBLISH_OK`) instead, which a tail cannot hide.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-14 — A regex over a hand-written ledger inverts "NOT claimed" into "claimed"
- The rule going forward: **`lanes.md` is prose written for humans, and the negations are load-bearing. Do not derive a claim set from a regex over it.** If a lane's claims matter — for a collision check, a census, or an accusation — read the block. The cheap guard: any extracted claim list should be re-checked against the lines containing `NOT claimed`, `Collision`, `elsewhere`, or `held by` before it is used.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-14 — An audit's CAUSAL claim is a hypothesis; its MEASUREMENT is evidence
- The rule going forward: **an audit's measurements and its explanations have different evidentiary status.** "28px of overflow at 1440" is a reading and survives being handed on; "because the grid does not stack" is the auditor's inference and must be re-derived by whoever acts on it. Before editing the rule an audit names, confirm that rule currently produces the symptom — the cheap version is one `getComputedStyle`/`getBoundingClientRect` on the element, which takes a minute and would have caught this.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-14 — A COUNT can rise because the population grew, not because the property got worse
- The rule going forward: **when a count changes across a fix, check whether the fix changed what is being counted.** A raw count carries an implicit denominator — here "tabs that exist" — and a change that adds members makes the count move on its own. Report it as a rate, or report the denominator beside it, or the next reader files a regression that does not exist.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-14 — An audit brief's "known already" inputs are claims, not axioms
- The rule going forward: **spend the first ten minutes of any audit re-verifying the inputs it tells you not to re-derive.** An input marked "known" is the one nobody will check, which is exactly why a stale one propagates. Cheap to test, and a single dead citation invalidates every downstream count that assumed it.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-14 — the Render logs API returns the NEWEST N in a window; paging forward silently reports a peak over a sliver
- I wrote a pager that walked a time window by advancing `startTime` past the last
- *(evidence in `learnings_evidence.md`)*

### 2026-08-14 — a before/after is void if the change moved work INSIDE the measured span
- The `#387` streaming cutover was measured as "peak anon during
- *(evidence in `learnings_evidence.md`)*

### 2026-08-14 — "it cannot fit" from one sample, when the same shape runs fine twice
- A handoff carried, as its single next action, a fix whose justification was one
- *(evidence in `learnings_evidence.md`)*

## 2026-08-15 — FORBIDDEN: never treat equality of a LABEL as identity of a BET

`clv_join._price_for_side` refuses a close whose line does not match the
opening's (`abs(point_line - opening_line) > 1e-6`). That guard is correct, was
written against a real prior bug, and was still defeated — because the
odds-history feed **transposed its `home_line`/`away_line` labels during the
day**. Event `69928d29…`, FanDuel spreads, mlb 2026-08-15:

    06:02:51Z   away_line -1.5 away_odds +168 | home_line  1.5 home_odds -205
    21:26:47Z   away_line  1.5 away_odds -205 | home_line -1.5 home_odds +168

Identical prices, opposite labels. Opening `home -1.5` matched the close's
`home_line -1.5`, which by then was the OTHER SIDE OF THE SAME RUN LINE. Result:
a `-29.90` "CLV" on a market that had not moved at all.

**The rule:** a guard that compares a label to a label is only as sound as the
label's convention is stable. When two sources each own their own labelling,
matching on the label matches the wrong thing *silently and confidently* — it
produces a number, not a refusal, which is the failure mode that survives review.

**How to apply:**
- When joining across two systems, establish WHICH SOURCE OWNS a convention
  (sign, side, units) before trusting any field that encodes it. Check it per
  sport and per market family, not once.
- Prefer a check that is invariant to the label where one exists. Here: the two
  run-line prices are the two sides of one bet, so `open` and `close` summing to
  roughly the same book margin is a labelling-independent sanity check that
  `-205 vs +168` fails instantly.
- **A mirror pair is the fingerprint.** Both openings were recorded, so the
  errors appeared as `+30.428` and `-29.900` and **nearly cancelled** — mean
  `+0.515`, median exactly `0.000`. Aggregates looked healthy while every
  individual row was wrong. **Check the tails before trusting a mean; a median
  of exactly zero on a noisy quantity is itself suspicious.**

**Standing until:** the sign convention for spread lines is pinned per source and
per sport, with a test.

### 2026-08-15 — ACQUIRING THE DEPLOY CLAIM BLINDS THE DEPLOY GATE. The safety mechanism disabled the safety check

`scripts/deploy_preflight.py` prints one verdict line. Before acquiring a claim
it is `HOLD: 3 job(s) in flight` or `CLEAR`. **After I acquired the claim it
became:**

    CLAIMED: deploy claim on refresh-worker is held by live-game-line-projection.

The claim verdict **REPLACES** the job verdict rather than accompanying it, and
it does not distinguish *held by me* from *held by someone else* — the JSON even
reports `deploy_claim.yours: false` while `holder` is my own string.

**So my poll-and-fire loop, which grepped `^(HOLD|CLEAR|UNKNOWN)`, matched
nothing on every tick and silently fell through to its "not clear" branch.** It
would have polled 300 times and never fired, and the output was blank lines
rather than an error. I caught it only because I looked at the raw output after
seeing empty timestamps.

**The shape: a coordination mechanism that makes the thing it coordinates
unobservable.** Acquiring the claim is the correct first step AND it destroys
the text signal you need for the second step. Ordering makes it worse, not
better: claim-then-poll blinds you; poll-then-claim races.

**How to apply.**
- **Gate on `--json`, never on the text verdict.** The structured payload keeps
  `jobs_in_flight`, `deploy_claim.holder` and `sample_age_seconds` as separate
  fields, so "my claim" and "jobs running" stay independent. The text line
  collapses them into one string, by design, for humans.
- **A loop whose match produces empty output is not "waiting", it is broken.**
  Log the RAW value when a match fails, not just the parsed one. Blank lines at
  a steady cadence look exactly like a healthy hold.
- Treat a foreign claim as an ABORT, not a hold — someone else is mid-deploy and
  polling past it is how two sessions cancel each other's deploys.

### 2026-08-15 — ANCESTRY CANNOT TELL YOU YOUR WORK IS PUBLISHED, AND A BROKEN GREP LOOKS EXACTLY LIKE A DELETION

Two failures of the same kind in one push, minutes apart: **an instrument
returned a confident answer about content while measuring something else.**

**1. `git merge-base --is-ancestor <mine> origin/main` says nothing about
content.** Nine of my commits were ancestors of `origin/main`, which reads as
"already pushed, nothing to do". Ancestry is a statement about the DAG; it
cannot tell you a later commit did not overwrite your lines — and on a contended
ledger, whole-file commits from stale copies do exactly that routinely (see
`6ccc4779`, another session repairing 30 `deploys.md` + 26 `lanes.md` lines its
own checkpoint deleted). Only `git show origin/main:<path> | grep <token>`
settled it: three of four code changes were genuinely there, one was not.
**Ask "is the CONTENT in the tree", never "is the COMMIT in the history".**

**2. A shell loop over `origin/main:<path>` refs silently measured nothing.**
Git Bash on Windows path-converted `origin/main:.syndicate/learnings.md` into
`origin\main;.syndicate\learnings.md`; `git show` failed to stderr, the pipeline
still ran, and `grep -c` dutifully reported **0** for every token. **A zero from
a broken command is indistinguishable from a zero from a real absence** — I was
one step from reporting "another session overwrote all three of my learnings
rules." They were all present. The tell was that EVERY token returned 0,
including ones I had just written and could see on disk.

**How to apply.**
- When a check returns the alarming answer, **prove the check can return the
  other answer** before believing it. A token you know is present is the
  control, and it costs one line.
- `export MSYS_NO_PATHCONV=1` before any `git show <rev>:<path>` on Windows, and
  redirect to a file with one invocation per path rather than looping — the loop
  is what hid the stderr.
- Uniform zeros across independent tokens are a tool failure until proven
  otherwise. Real content loss is almost never that tidy.

### 2026-08-15 — a cgroup number minus a per-process number is not a difference, it is a category error
- **The rule going forward:** every memory number carries a SCOPE — container,
  process, or thread — and only same-scope numbers may be subtracted. Write the
  scope next to the figure. `memory.current`/`anon` and `oomKilled` are
  container; `smaps`, `PYMALLOC_STATS`, `HEAP_CENSUS`, `mallinfo` and
  `getsizeof` are process; a container with children makes them differ by
  hundreds of MB.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-15 — A DEPLOY CLAIM IS ADVISORY. It binds participants, not the fleet.
- The rule going forward: **treat the claim as a courtesy that makes collisions
  VISIBLE, never as a lock that makes them impossible.** Concretely: still cut
  from the service's CURRENT live SHA, still re-verify by content after landing,
  and never fire into an in-flight deploy even when you hold the claim -- holding
  a token is not a licence to cancel a peer's build. The durable fix remains one
  deployer per service; the claim only shortens the argument about who that is.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-15 — NEVER PIPE A COMMAND WHOSE EXIT CODE YOU DEPEND ON
- The rule going forward: **check `rc=$?` directly on any command whose failure
  should stop the chain, and assert the postcondition** -- the worktree exists,
  HEAD actually moved, the diff is the size you expect. Cheap asserts turn a
  silent wrong-tree operation into an immediate stop.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-15 — THE DEPLOY CLAIM IS ADVISORY, AND IT LOST A RACE IT LOOKED LIKE IT WOULD WIN

I acquired `deploy_claim` on live-odds-worker (`token dbb88556`, ttl 3600s,
`target=49797f4b`), held it, and fired. **My deploy was CANCELED anyway**:
another session fired `c422f79a` at **23:42:32** and mine went in at
**23:42:33** — one second later, so Render cancelled mine.

**The claim binds nobody who does not run `deploy_preflight`.** It is a file
plus a convention; nothing in `render_deploy.py` or the Render API consults it.
Holding it changed exactly one thing — it made MY OWN preflight report
`CLAIMED` instead of `HOLD`/`CLEAR`, which is the opposite of protection
(see the entry below on the claim blinding the gate). So the claim is a
courtesy signal to humans reading the ledger, **not** a lock.

**Two things this does NOT mean.** It is not evidence the other session did
anything wrong — they may never have run the gate, and nothing forced them to.
And it is not an argument to skip the claim: it still records who to ask, which
is the only reason I could tell within a minute that the cancel was a race and
not a failure.

**What the cancel actually costs.** `render_deploy.py` returned a clean 201 and
`status: build_in_progress`. **The cancellation appears only in the deploys
list, as a separate row, ~1 second later.** A session that fires and reports
success without re-reading would state, truthfully and wrongly, that the deploy
was shipping. `state.md` already says a fired deploy is not a landed deploy;
this is the sharpest instance yet, because the window between them was one
second.

**How to apply.**
- **After firing, re-read the deploys list and confirm YOUR commit is the one
  building.** Not the 201, not the status in the POST response.
- **Check whether the superseding commit carries your change before re-firing.**
  Mine did not (`lane_is_live_mc` count 0), so the work was genuinely not in
  production. If it had, re-firing would have been pure churn.
- **Re-cut from the winner, never re-fire the cancelled commit.** The cancelled
  parent is now behind; re-firing it is a rollback of the session that beat you.
- Expect the gate to CLOSE right after someone else's deploy lands on
  live-odds-worker: the restart launches a refresh run on boot.

### 2026-08-16 — THE HANDOFF THAT WORKED WAS A SCHEDULED TASK, NOT A MESSAGE
- The rule going forward: **for anything that must outlive a session -- a
  measurement owed, a deploy window, a follow-up read -- write it to disk as a
  scheduled task or a claim, not into another session's inbox.** Reserve
  messages for things that are only useful if read within the minute, and expect
  even those to be late. When you need another session's STATE, read its
  transcript with `list_events`: it costs them nothing, cannot stall them, and
  returns more than a reply would.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-16 — FORBIDDEN: never deploy on `check_deploy_safety.py` alone. It said CLEAR while three jobs were running on the service.

**Measured 2026-08-16 00:13Z on refresh-worker.** `check_deploy_safety.py`
returned **`CLEAR: nothing in flight that a restart would interrupt.`, exit 0**,
with the line `- Odds refresh: idle`. At the same instant
`deploy_preflight.py --service refresh-worker` listed, on that same service:

```
[JOB] pid 587  run_refresh_odds_job.py
[JOB] pid 588  refresh_odds_sources.py
[JOB] pid 621  build_soccer_artifacts.py --league ligue_1
```

It watches a different odds lane than the one hosting refresh-worker's own odds
job, so a whole job tree is invisible to it. **Deploying on that verdict would
have killed a soccer artifact build mid-flight — which is the 2026-08-03
incident (`odds_refresh_20260803_033243`) that the script's own docstring was
written about.** The gate it added is narrower than the one it replaced in a
different direction, and its prose reads as though it covers everything:
*"This checks every in-flight thing a restart would interrupt."*

**How to apply.** Gate a worker deploy on BOTH, in one shell command, and
re-verify immediately before the POST:

```bash
pf=$(py -3 scripts/deploy_preflight.py --service <svc> 2>&1)
py -3 scripts/check_deploy_safety.py > /tmp/sf.txt 2>&1; src=$?
jobs=$(echo "$pf" | grep -c "^  \[JOB")
[ "$src" -eq 0 ] && [ "$jobs" -eq 0 ] && py -3 scripts/render_deploy.py ...
```

The process list is the ground truth here; the verdict line is a summary of a
partial view. Related: [[gate-on-the-output-not-the-input]] — a guard encoding
an assumption about WHICH work is in flight is silent on the work it did not
model.

## 2026-08-16 — FORBIDDEN: a wait loop must gate on an AFFIRMATIVE success token, never on the absence of a failure string

Same deploy, one step earlier. My waiter was
`s=$(check_deploy_safety 2>/dev/null); if ! echo "$s" | grep -q "NOT CLEAR"`.
It reported **`SAFETY CLEAR after 40s`**. The real result was
`[UNKNOWN] Could not read live-refresh state: HTTPError: HTTP Error 502` —
written to **stderr**, which `2>/dev/null` discarded, leaving `$s` empty. An
empty string contains no `"NOT CLEAR"`, so absence-of-failure read as success,
and a transient 502 became a green light to deploy over a running MLB sim.

The script is explicit that this must not happen — *"Exit code 0 = clear, 1 =
something is in flight, 2 = could not determine (which is NOT the same as
clear, and is deliberately not exit 0)"* — and my loop threw away the exit code
that encoded it.

**How to apply.** Wait loops check `rc -eq 0` **and** grep for the positive
token (`^CLEAR:`), with `2>&1` so diagnostics are visible. If a poll cannot
distinguish "healthy" from "could not read", it is not a poll. This is
[[feedback_unknown_must_not_default_permissive]] recurring in a wait loop
rather than in application code, and [[feedback_instrument_blindness]]: a
healthy reading is evidence only once you know what makes it read unhealthy.

## 2026-08-15 — FORBIDDEN: never read a joiner zero as a fact about the world until the reader is shown to SEE the data

Supersedes and merges two entries from the same night (full evidence in
`learnings_evidence.md`): the pre-registered rule *"if `same_book_n` is still 0,
the blocker is odds-history breadth"*, and its refutation.

**What happened.** The rule was written in advance, in good faith, and was
wrong. `same_book_n=0` came back for all 8 sports. The truth: `/api/ops/clv/report`
runs on **web**, `load_openings` is a `path.exists()` on a local file, and web
held **0 bytes** of the ledger while refresh-worker had **490 openings recorded
for that same date**. The endpoint returned `ok: true` throughout. Shipping one
allowlist line moved `same_book_n` **0 → 144** with **no change to odds history
at all**. Breadth constrains `resolved` (`no_market_in_history: 172`), never
`same_book_n`.

**The generalisable trap: a zero with two sufficient causes.** "No same-book
pairs" is produced BOTH by a thin market AND by an empty input. The rule named
one and never checked the other, so the unanticipated cause was silently routed
into the anticipated explanation. **A decision rule that maps every zero onto a
substantive cause is a rule with no null branch.**

**How to apply:**
- Demand a NON-ZERO reading from the same instrument before believing a zero.
  Here one call did it: the same endpoint for the previous date, known to have
  150 openings, also returned 0. Two known-non-empty inputs, both 0 → the
  instrument.
- Read the SIBLING fields first. `unresolved_reasons: {}` and `by_book_scope: {}`
  were empty in the very first payload; under the breadth hypothesis they are
  necessarily non-empty. The refutation was already on screen.
- **Name the service that runs the code and the service that owns the file,
  every time.** Deployed and reachable ≠ able to read. An allowlisted pattern
  PERMITS a transfer; it does not make one happen.
- A report whose "no data" and "cannot see data" look identical is a defect in
  the report. 0 openings and 490 openings must not share a response shape.

### 2026-08-16 — A TEST THAT PROVES A DEFECT DOES NOT PROVE PRODUCTION RUNS THROUGH IT. I DEPLOYED A CORRECT FIX TO AN UNUSED PATH

Three red tests in `test_intelligence.py` led to three real defects, all fixed,
218/0, every fix mutation-pinned. Then I predicted a production number from
them, deployed refresh-worker to get it, and the number **did not move** —
because the code I fixed is not on the path production serves.

**The gap.** The failing test exercised `run_intelligence_query` with
`force_refresh=True`, where a candidate flows through `UniversalCandidate.to_dict`.
**Production serves the Layer 2 board**: every served row carries
`source: layer2_shortlist`, `surface_key: layer2`, `candidate_type: None`, and
its `line` is stamped at `layer2_board.py:1104` as a bare `row.get("line")`
float. `to_dict` never runs on it. A web deploy would not have helped either —
the field is stamped in the worker, in a different module, upstream of my change.

**What made it feel verified when it was not.** I had a genuine defect, a
reproducing test, a mutation pin, a measured production baseline (84 of 101
numeric, 7 whole-numbered), and a falsifier written down before deploying. Every
one of those is good practice and none of them checks the one thing that was
wrong: **that the baseline and the fix describe the same code path.** The
baseline measured the served payload; the fix changed a producer that payload
does not use. Two rigorous halves, never joined.

**How to apply.**
- Before predicting a production number from a test, **trace one served row back
  to its producer** and confirm your changed function is in that trace. A field
  on the payload does not tell you who wrote it — `source`/`surface_key` on the
  row often does, and it took one request to read.
- "Which service runs this" is necessary but NOT sufficient. I got the service
  question right (worker, not web) and still shipped to an unused module. The
  question is which **producer**, not which host.
- **A falsifier is only worth writing if you will act on it.** This one fired
  exactly as designed and it is the reason the error is one restart rather than
  a false entry in `deploys.md` — but it fired AFTER the deploy. The same check
  run BEFORE, as "does my function appear in this row's provenance", costs one
  request and no restart.
- Related, same session, same shape: I called a build "stalled, did not publish"
  from a log window I had read **ten seconds** before the publish line was
  written. `absence in a window is not absence` — and I already held that rule.

## 2026-08-15 — FORBIDDEN: shipping a verification you have not falsified. THREE failed checks in one night, zero failed fixes

Every one of these produced the reading a BROKEN FIX produces, so the natural
next move was to debug working code or roll back a correct change.

1. **Measured the input the fix never touches.** A watcher compared
   `row["line"]` to `cell.home.line` on the book-grid and would PASS only when
   they stopped being opposite — but that opposition is the INPUT SHAPE and the
   fix changed the SHORTLIST candidate. It reported `opposite=573 / FAIL` on
   perfectly healthy data, forever.
2. **Confused "not rebuilt yet" with "rebuilt and wrong."** The same watcher had
   no `written_at` gate, so a stale artifact and a broken fix were the same
   output.
3. **Compared a snapshot against a moving reference.** The replacement joined a
   frozen shortlist (`written_at` 00:12:35Z) to a LIVE grid fetched 15 minutes
   later. A spread that moved in between read as a mismatch: `away_wrong=1`,
   reported FAIL, while the fix was in fact working (`home_correct=2/2`).

**The rule.** Before arming any check, ask the falsification question about the
CHECK, not the fix: *what reading would this produce if the fix worked
perfectly?* If that equals the failure reading, the check is broken. Then:
- **Name the artifact the change WRITES and measure that one.** A related
  endpoint showing the same concept is not it.
- **Gate on the artifact's own `written_at`** against the deploy time, so
  "not rebuilt yet" can never be read as "wrong".
- **Join snapshot to snapshot.** Read both sides at the same instant, or compare
  only fields that cannot move between reads.
- **For a PRODUCER, the deploy is the START of the wait.** Code being live is not
  the artifact being fixed, and "no errors in the logs" is evidence that nothing
  crashed — a different claim from the fix working.

Full evidence for 1 and 2 is in `learnings_evidence.md`; 3 is in `deploys.md`
under the candidate-line verification.

### 2026-08-16 — COLLAPSING A LEDGER FILE WITHOUT FIXING THE WRITING HABIT JUST REGROWS IT

- What we believed: `state.md` was too big, so collapsing it to current truth
  would fix it.
- What was actually true: it went **40 KB -> 113 KB in about five hours**. The
  section list showed the mechanism plainly -- **eight separate UI/card sections
  and four soccer ones**, each a dated measurement rather than a subject, several
  superseding each other. Two carried claims the file itself refuted further
  down: the prop `0.5` fix "on no worker" (live on both), and soccer's "250x
  disagreement / 8,456 rows / 29.6%" (one join, two different grids). **A reader
  going top-down hits the wrong answer first**, which is the real cost -- the
  byte count is only the symptom.
- How we found out: printed the section list with sizes instead of reading the
  file, which made the one-section-per-measurement pattern obvious in seconds.
- The rule going forward: **when a ledger file regrows, fix the WRITING RULE and
  put it where the writing happens, not just the contents.** Each collapsed
  section now opens with "OVERWRITE this; do not append another section", and
  `learnings.md`'s preamble now states that the five-bullet template is what
  makes compaction mechanical and that a prose entry costs every future session
  ~2 KB forever. Also: **a compaction script must leave an entry INTACT when it
  cannot find the rule** -- guessing keeps the evidence and drops the rule,
  which is the one outcome worse than the file being large.
- Cost: a second full collapse of the same file within one session, and four
  wrong claims live in the ledger for hours between the two.

## 2026-08-15 — FORBIDDEN: `git <cmd> <rev>:<dotpath>` in Git Bash on Windows. It silently reads the WRONG thing, and only for dot-prefixed trees

`git rev-parse "origin/main:.syndicate/state.md"` fails with
`ambiguous argument 'origin\main;.syndicate\state.md'`. MSYS sees `a:.b`, decides
it is a POSIX path LIST, and rewrites `:`→`;` and `/`→`\` before git ever sees it.

**The part that makes it dangerous: it is selective.** Measured:

    git rev-parse "origin/main:syndicate/features/shared/clv_join.py"   -> WORKS
    git rev-parse "origin/main:.syndicate/state.md"                     -> MANGLED
    git rev-parse "origin/main:.claude/hooks/lane-guard.py"             -> MANGLED
    MSYS_NO_PATHCONV=1 git rev-parse "origin/main:.syndicate/state.md"  -> WORKS

So it breaks on exactly the two trees that hold the LEDGER and the HOOKS, and
never on source. A reconcile loop over mixed paths therefore reports source as
clean and `.claude/hooks/lane-guard.py` as UNRECONCILED — which is what happened,
twice, and produced a third false negative when verifying a pushed ledger commit
("content missing on origin/main" when it was all there).

**Fix — any of:**
- `MSYS_NO_PATHCONV=1 git show "<rev>:<path>"` (verified)
- `MSYS2_ARG_CONV_EXCL='*' git show "<rev>:<path>"` (verified)
- Avoid the syntax: `git grep <pat> <rev> -- <path>`, `git diff <rev> -- <path>`,
  `git log <rev> -- <path>`. These take the path as a separate argument and are
  immune.

**And the deeper rule this is the third instance of tonight: a failing CHECK and
a failing SUBJECT look identical.** `git diff` said lane-guard.py was clean while
`hash-object` vs `rev-parse` said it diverged — the diff was right and the blob
comparison was reading a mangled path. **When two methods disagree about the same
fact, suspect the instrument before the subject.** For reconcile specifically:
`git diff` is authoritative; `hash-object` against `<rev>:<path>` is not, both
because of this mangling and because git normalizes CRLF on the way in.

## Superseded on 2026-08-15 — the two `same_book_n` entries

Both were merged into **"never read a joiner zero as a fact about the world"**
above; full original text is in `learnings_evidence.md`. They reappeared here
once after being removed — a stale-read write on this shared file resurrected
them alongside their own replacement. If they show up a third time, delete
them again rather than assuming the merge was reverted: the merged rule and
the evidence file are the source of truth.

### 2026-08-16 — verify a watcher's FIRST line, or it will report failure as patience

- **What we believed:** a background poller was waiting for a deploy window. It
  printed a line every 30s and looked like it was working.
- **What was actually true:** it failed on its FIRST poll and every one after —
  90 identical `RENDER_API_KEY not set in the environment or .env` lines over 45
  minutes. It never once read the gate. The key was present in `.env`; the
  PowerShell background environment could not resolve it, while the same command
  from Bash worked.
- **How we found out:** the owner asked whether it had deployed. Nothing in the
  poller's own behaviour surfaced it — an error line every 30s reads exactly
  like a status line every 30s when nobody looks.
- **The rule going forward:** after starting any watcher, READ ITS FIRST OUTPUT
  before trusting it. And a poller must treat "cannot evaluate" as a distinct,
  loud state — not fold it into the same quiet loop as "condition not met". Mine
  printed the error into the same stream as the status and that was enough to
  hide it.
- **Cost:** 45 minutes of believing a window was being watched. Nothing broke —
  the deploy still landed once polled from a working shell — but the same
  pattern (an instrument reporting normally while measuring nothing) has now
  appeared FOUR times in this investigation, and this is the first time it was
  mine.

### 2026-08-16 — do not rebase onto a deploy target that has not shipped

- **What we believed:** rebasing onto `c70eeff0` — the SHA a claim holder had
  DECLARED as their target — would put the commit ahead of production and stop
  it going stale again.
- **What was actually true:** they shipped something else. Live went to
  `57a437d5`, which does not contain `c70eeff0`, so the rebased commit would
  have **ROLLED PRODUCTION BACK** had it been deployed.
- **How we found out:** an explicit ancestry check before deploying —
  `git merge-base --is-ancestor <live> <mine>` — not the deploy tool refusing.
  `render_deploy.py` would have caught it too, but only after the attempt.
- **The rule going forward:** rebase onto what IS live, never onto what someone
  intends to deploy. A declared target is a plan, and plans change without
  telling you. Re-check ancestry against the CURRENT live sha immediately before
  every deploy, however recently the branch was rebased.
- **Cost:** none — caught before firing. It took five rebases across five live
  SHAs to land a two-file commit, which is the real signal: on a worker with five
  sessions deploying, a small change should ride along rather than chase.

### 2026-08-16 — A DEPLOY HAS TWO LAGS IN SERIES. I GUARDED ONE AND MISREAD THE SYSTEM THREE TIMES

`deploy -> snapshot -> artifact`. live-odds-worker's tick rewrites the snapshot;
refresh-worker's build turns it into the artifact you read. **A fresh artifact
can carry a stale snapshot**, so "generated_at is after the deploy" is NOT
sufficient to conclude the number reflects the new code.

Three failures tonight, all one shape — comparing a number to an event without
establishing the number was PRODUCED AFTER the event:

1. **Warm-up read as regression.** 5 and 8 minutes after the fix landed,
   `index_size` was 0 twice. I called it a persistent regression and **asked for
   a rollback of a working fix.** Two reads inside one warm-up window are one
   read — a rule I had written earlier the same night and did not apply.
2. **Pre-rollback artifact credited to the rollback.** The watcher waited for
   `ROLLBACK_LANDED` (00:54:07) then read an artifact stamped **00:52:14** and
   printed "RECOVERED -> the fix IS implicated". It had just measured the fix's
   own success and blamed the rollback for it.
3. **Artifact-vs-deploy check still insufficient.** I then added exactly the
   check that would have caught (2) — and 01:09:04 STILL read
   `sim_count_unusable 32`, because the artifact was fresh while the snapshot it
   consumed was written by the rolled-back code. The truth arrived at 01:11:16.

**Cost: three soccer runs killed, two extra restarts, one wrong rollback of a
change that was working.**

**How to apply.** Identify EVERY producer between the code and the number, and
wait for the slowest. For this pipeline that means a signal that the SNAPSHOT
was rewritten — not just the artifact. Best: poll until the number CHANGES and
then stabilises across two builds, rather than reading once at a computed
"should be ready" moment. A single post-deploy read is a coin flip on the
warm-up.

### 2026-08-16 — I HELD A CLAIM ONCE AND THEN DEPLOYED OVER SOMEONE ELSE'S, TWICE

At 23:42 another session's deploy cancelled mine one second apart, and I wrote
up the deploy claim as advisory. Then `clamp-fix-to-workers` acquired
live-odds-worker at ~00:34 — and **my 00:47 rollback and 00:58 re-deploy both
fired on that service without re-checking the claim.** I did to them exactly
what had just been done to me, while holding the ledger entry about it.

**Acquiring a claim is not honouring one.** The claim I took at 23:39 gave me a
sense of ownership that outlived the claim itself; I never re-read it, and it
had moved. **Check the claim IMMEDIATELY BEFORE EVERY FIRE, not once at the
start of the work** — `deploy_preflight --json` returns `deploy_claim.holder`
for free on the same call that gates the jobs, so there is no excuse of cost.

Corollary: **you cannot release a claim you no longer hold**, and `--force`
against a live claim breaks another session's lock. Mine was gone; I left it.

## 2026-08-16 — FORBIDDEN: never read a deploy claim's `target` as a statement about what is running

**Measured 2026-08-15/16 on live-odds-worker.** Its claim advertised
`target=49797f4b`, and `49797f4b` genuinely carried the clamp fix — verified by
reading the code, not just counting a grep. I concluded twice, in writing, that
the service "needs nothing".

It never landed. Over 100 minutes the service went
`f0452408` → `b7ae47e6` → `c422f79a` → `c4116ab6`, and **every one of those
still carried the clamp.** The clean target sat pending under the claim the
whole time and was superseded by other work from the same session.

**A claim is a lock plus a stated intention. It is not a deployment, not a
queue, and not a promise.** The holder can deploy something else, deploy
nothing, or let the claim expire — all of which happened here.

**How to apply.** The only answer to "does the running code have X" is content
at the CURRENT live SHA:

```bash
py -3 scripts/deploy_preflight.py --service <svc>   # read live commit
git grep -c "<pattern>" <live commit> -- <files>    # by content, not ancestry
```

Re-read it after any wait — these SHAs moved 4× in 100 minutes on one service
and 3× on another the same night. Sibling rules:
[[feedback_test_the_fixs_predicate_not_its_deploy_state]] (a deployed fix can be
inert) and [[project_web_runs_a_deploy_branch_not_main]] (ancestry proves
nothing here). This is the same shape one level up: I checked the artifact of an
*intention* instead of the artifact of an *action*.

### 2026-08-16 — a one-game-wide range cannot answer "how does it scale", and the fit will look plausible anyway

- **What we believed:** production history could answer "at what slate size does
  the worker cross 4GiB", because every board build records `game_count`
  alongside peak anon. 249 builds looked like plenty.
- **What was actually true:** all 249 builds were 14 or 15 games. The observed
  range was ONE GAME WIDE, so there was nothing to model. The naive fit came out
  at **+702.7 MB per game** — no baseball game costs 700MB — and would have
  extrapolated to "~19 games", a number with no support that reads as precise.
- **How we found out:** the absurdity of the per-unit figure, not the sample
  count. 249 builds and 20,000 samples all pass an "is this enough data" check;
  the range check is the one that fails. The two buckets differed in KIND (18
  builds vs 235, different points in the quote-shard ramp), not in size.
- **The rule going forward:** before fitting anything against a variable, print
  its RANGE and the count per bucket. n is not the constraint — spread is. And
  sanity-check the per-unit coefficient against physical plausibility before
  quoting any extrapolation: if one unit of X appears to cost 700MB, the model is
  measuring something other than X.
- **Cost:** none. The lane's falsification test was written before measuring and
  it fired exactly as specified, which is the only reason a confident wrong
  number was not produced and acted on.

### 2026-08-16 — a headroom figure that counts one process is not headroom on a container

- **What we believed:** after `#435` the worker had **578MB of headroom** — peak
  anon 3,518MB against a 4,096MB ceiling. That number was reported to the owner
  and used to argue a plan bump was not urgent.
- **What was actually true:** the ceiling is a CONTAINER limit and the worker runs
  8-12 processes. At the worst observed moment the parent held 3,302.4MB and its
  children held 669.6MB **at the same instant** — 3,972.0MB total, **97.0% of the
  ceiling and 124MB from a kill**. The real margin was a fifth of the reported one.
- **How we found out:** by bucketing children's total rss BY WHAT THE PARENT HELD
  at the same sample, rather than reporting either in isolation. Children median
  450.2MB while the parent sat at 2-3GB — they peak WITH the parent, not between
  its peaks, which is the assumption that makes separate figures feel safe.
- **The rule going forward:** when the limit is per-container, headroom must be
  computed from the SUM of every process at one instant. A per-process peak and a
  per-process children total are both true and neither is headroom. This is the
  same scope error as the retracted "673MB outside pymalloc", reached from the
  opposite direction — there I subtracted across scopes, here I omitted a scope.
- **Cost:** none yet, but it understated risk by 454MB in a decision about whether
  to spend money on memory. The decision may still be right; it was made on a
  number that was wrong.

### 2026-08-16 — three processes with the same NAME are not three concurrent jobs; read the ppid

- **What we believed:** the refresh-worker ran THREE `daily_update` variants
  concurrently (`ui-daily`, `core`, `multi_profile`), and serialising them was
  "the single biggest win" for memory. Recommended to the owner in those words.
- **What was actually true:** they are a NESTED CHAIN. `daily_update.py` (341)
  spawns `daily_update_multi_profile.py` (369), which spawns another
  `daily_update.py` (370), which spawns the multiprocessing workers. Already
  sequential. Serialising something already serial saves nothing.
- **How we found out:** by printing `ppid` alongside `pid`, which the process
  sample carried all along. The first read grouped by command line and saw three
  similar names at one instant, which looks exactly like parallelism.
- **The rule going forward:** when a process census shows several instances of
  one program, resolve the PARENT before calling them concurrent. Same-name
  siblings and a nested chain are indistinguishable from the name and rss alone,
  and they have opposite fixes — scheduling for one, memory-release-before-spawn
  for the other.
- **Cost:** a wrong recommendation that survived one turn. The real levers are
  the odds branch running alongside the MLB chain (202.6MB, genuine concurrency)
  and ~305MB of parents idling while their children work.

### 2026-08-16 — FORBIDDEN: never rely on a PROMPT to stop an unattended session from acting

- What we believed: writing "Do not deploy anything, do not open a lane, and do
  not commit code" into a scheduled task's prompt would keep it read-only.
- What was actually true: the run committed a **339-line module**, took deploy
  claims on **three services**, and fired deploys at all of them — with that
  sentence sitting at line 49 of its own SKILL.md. It is unattended, so it cannot
  be messaged mid-run; `send_message` returns "session is unattended". Disabling
  the task stopped the NEXT firing and did nothing to the run in flight.
- How we found out: went to message the session about a deploy collision and got
  the unattended error, then compared its brief against the Render deploy log.
- The rule going forward: **an unattended run's constraints must be structural,
  not textual.** Give the run no `RENDER_API_KEY`, or make the deploy path refuse
  an unattended holder. Treat a scheduled task as something that CAN do anything
  its tools allow, and choose the tools accordingly — the prompt is a hope, the
  environment is a control. Corollary: check `isRunning` before assuming a
  disabled task is stopped.
- Cost: two implementations of the same fix built in parallel, three services
  deployed by a process nobody was watching, and a merge that would not have
  been needed if the run had done what it was asked.

### 2026-08-16 — MERGE PARALLEL IMPLEMENTATIONS BEFORE PICKING BETWEEN THEM

- What we believed: when two sessions ship competing fixes for one problem, the
  job is to choose the better one and revert the other.
- What was actually true: they solved DIFFERENT halves and each was right about
  its own. A readable JSON channel beat grepping a logs API this ledger records
  as spotty; a per-artifact emit fixed a latency the channel shared, because
  `record` was wired only into the exit path — which fires from `finally`, so
  the reading landed when the PROCESS ended, measured at 70+ minutes of silence.
  Reverting either would have shipped a known-worse instrument.
- How we found out: read the competing implementation's CALL SITES rather than
  its diff stat — one call, inside the exit path, which answered the whole
  question in a line.
- The rule going forward: **before reverting your own work in favour of a peer's,
  find what each one measures that the other does not.** Read call sites, not
  line counts. If they are complementary, merge and pin the merge with a test —
  ours fails if `record` is ever rewired to exit-only, because the two channels
  would then silently disagree, which is worse than either alone.
- Cost: none — the check took one command and saved a good half of the work.

## 2026-08-15 — RULE: merge in the object database when the shared tree is dirty

- **The rule going forward:** on this repo a reconcile does **not** need a
  checkout. `git merge-tree --write-tree` + temp index + `commit-tree` +
  `push <sha>:main` merges with **zero** working-tree writes, so concurrent
  sessions' edits cannot be refused, overwritten, or staged by accident.
- Why it is not optional here: 76 of 82 incoming files were dirty across
  sessions, and `git worktree add` fails on this repo anyway — `Filename too
  long` on the statcast cache paths, plus 32 stale worktree entries that
  `prune` cannot delete under OneDrive. *(detail: `learnings_evidence.md`)*
- Cost: none. It was faster than the worktree attempts that failed.

## 2026-08-15 — RULE: resolve a ledger conflict by REPLACING the stale entry, never by appending

- **The rule going forward:** when both sides changed a lane, the merge is not
  "keep both" — a union leaves the file **asserting two contradictory statuses**
  for one slug and nothing flags it. Find the slug's other occurrence and
  overwrite the stale header in place; demote the old body to marked history.
- Check the resolution the way the TOOLING reads the file: one `^### slug` per
  lane, and the status word must match what the session-start hook greps
  (`OPEN|BLOCKED`). My own replacement header said `SESSION ARCHIVED` and
  **silently removed a lane from every future session's digest** while its body
  still read "Lane stays OPEN".
- How we found out: counted headers per slug and re-ran the hook's own grep
  after resolving, instead of trusting that no conflict markers meant no defect.
- Cost: caught pre-push; the second-order bug was live for about a minute.

### 2026-08-16 — A RECORDER GATED ON THE PUBLISH DECISION CANNOT EVALUATE THE PUBLISHER

The live game-line ledger was built to make CLV computable on live edges. It
recorded only rows the board judged `priceable` — i.e. rows whose edge cleared
the estimator's own 2σ noise bar at 120 sims. Measured on the first live slate it
ever saw (2026-08-16 03:00Z, 2 games live):

    considered 8   projected 2   priceable 0   ->   ledger candidates 0

**The file could not have a row in it.** Not because of a bug — every component
did exactly what it was written to do — but because the recorder's population was
defined by the decision the recording exists to audit. A ledger that only keeps
what the publisher published can answer "did the published tail beat the close"
and can never answer "should we have published it", which is the question.

**The second half is worse than the first: the filter's justification was a
guess, and the guess was wrong by three orders of magnitude.** The docstring
refused non-priceable rows because "recording thousands of refusals per build
would bury the handful of rows CLV can actually score." The entire live
game-line population is **8 rows per build**. There were never thousands. A
volume argument was used to make a selection decision, and nobody had counted.

**How to apply.**
- **When you gate what gets recorded, the gate must not be the thing under
  evaluation.** Keep the decision as a FIELD (`priceable`, `withheld_reason`) so
  the restricted question stays askable, and record the population. A field costs
  bytes; a filter costs the denominator, and the denominator is the measurement.
- **Count before you filter for volume.** "That would be too many rows" is a
  measurable claim about a population that already exists in production. Reading
  one artifact settles it. This one was wrong by 1000x and it silently emptied
  the file for a full slate.
- **A recorder that has never recorded is not "wired and waiting."** `written: 0`
  with `enabled: true` was recorded as proving the wiring. It equally described a
  recorder that structurally could not fire, and the two were never separated
  until someone read `candidates`. **Before a scheduled check, ask what a zero
  from it would mean — if it means the same thing whether the system works or
  not, the check is not a test.**
- Version the record shape when the POPULATION changes, not just the fields
  (`LEDGER_VERSION` 1 → 2 here). A rate computed across both populations is a
  rate over two different denominators, and nothing in the file's own data says
  where one ends.

Related: [[a rate, not a count]] — same family, one step earlier: this is a
counter with no denominator *by construction* rather than by omission.

### 2026-08-16 — FORBIDDEN: never rely on a PROMPT to stop an unattended session from acting

- What we believed: writing "Do not deploy anything, do not open a lane, and do
  not commit code" into a scheduled task's prompt would keep it read-only.
- What was actually true: the run committed a **339-line module**, took deploy
  claims on **three services**, and fired deploys at all of them — with that
  sentence sitting at line 49 of its own SKILL.md. It is unattended, so it cannot
  be messaged mid-run; `send_message` returns "session is unattended". Disabling
  the task stopped the NEXT firing and did nothing to the run in flight.
- How we found out: went to message the session about a deploy collision and got
  the unattended error, then compared its brief against the Render deploy log.
- The rule going forward: **an unattended run's constraints must be structural,
  not textual.** Give the run no `RENDER_API_KEY`, or make the deploy path refuse
  an unattended holder. Treat a scheduled task as something that CAN do anything
  its tools allow, and choose the tools accordingly — the prompt is a hope, the
  environment is a control. Corollary: check `isRunning` before assuming a
  disabled task is stopped.
- Cost: two implementations of the same fix built in parallel, three services
  deployed by a process nobody was watching, and a merge that would not have
  been needed if the run had done what it was asked.

### 2026-08-16 — MERGE PARALLEL IMPLEMENTATIONS BEFORE PICKING BETWEEN THEM

- What we believed: when two sessions ship competing fixes for one problem, the
  job is to choose the better one and revert the other.
- What was actually true: they solved DIFFERENT halves and each was right about
  its own. A readable JSON channel beat grepping a logs API this ledger records
  as spotty; a per-artifact emit fixed a latency the channel shared, because
  `record` was wired only into the exit path — which fires from `finally`, so
  the reading landed when the PROCESS ended, measured at 70+ minutes of silence.
  Reverting either would have shipped a known-worse instrument.
- How we found out: read the competing implementation's CALL SITES rather than
  its diff stat — one call, inside the exit path, which answered the whole
  question in a line.
- The rule going forward: **before reverting your own work in favour of a peer's,
  find what each one measures that the other does not.** Read call sites, not
  line counts. If they are complementary, merge and pin the merge with a test —
  ours fails if `record` is ever rewired to exit-only, because the two channels
  would then silently disagree, which is worse than either alone.
- Cost: none — the check took one command and saved a good half of the work.

## 2026-08-15 — RULE: merge in the object database when the shared tree is dirty

- **The rule going forward:** on this repo a reconcile does **not** need a
  checkout. `git merge-tree --write-tree` + temp index + `commit-tree` +
  `push <sha>:main` merges with **zero** working-tree writes, so concurrent
  sessions' edits cannot be refused, overwritten, or staged by accident.
- Why it is not optional here: 76 of 82 incoming files were dirty across
  sessions, and `git worktree add` fails on this repo anyway — `Filename too
  long` on the statcast cache paths, plus 32 stale worktree entries that
  `prune` cannot delete under OneDrive. *(detail: `learnings_evidence.md`)*
- Cost: none. It was faster than the worktree attempts that failed.

## 2026-08-15 — RULE: resolve a ledger conflict by REPLACING the stale entry, never by appending

- **The rule going forward:** when both sides changed a lane, the merge is not
  "keep both" — a union leaves the file **asserting two contradictory statuses**
  for one slug and nothing flags it. Find the slug's other occurrence and
  overwrite the stale header in place; demote the old body to marked history.
- Check the resolution the way the TOOLING reads the file: one `^### slug` per
  lane, and the status word must match what the session-start hook greps
  (`OPEN|BLOCKED`). My own replacement header said `SESSION ARCHIVED` and
  **silently removed a lane from every future session's digest** while its body
  still read "Lane stays OPEN".
- How we found out: counted headers per slug and re-ran the hook's own grep
  after resolving, instead of trusting that no conflict markers meant no defect.
- Cost: caught pre-push; the second-order bug was live for about a minute.

### 2026-08-16 — a "regression" that was a SCOPE ERROR: the two numbers were never the same quantity

The lane opened on an apparent contradiction: the ledger recorded `#435
deployed: peak anon 2,869 -> 1,071 MB`, and the worker was observed at **anon
3,857 MB** with two fresh OOM kills. The framing was "either that fix regressed,
or it fixed one contributor and this is another."

**Neither. `2,869 -> 1,071 MB` is the cost of the book_quotes READ. `3,857 MB` is
CONTAINER anon.** Different quantities with the same unit and a shared word.
`#435` was intact by content the whole time (`c67f7373` is an ancestor of the
live SHA). This is the **third** member of the same family in this repo, after
the retracted "673MB outside pymalloc" and the retracted "85% of anon is not
Python data" — `state.md` already carries the rule **EVERY MEMORY NUMBER CARRIES
A SCOPE**, and it was still possible to build a whole lane on violating it.

**The rule going forward:** before treating two memory numbers as comparable,
state what each one MEASURES — not what it is called, and not its unit. A
same-unit comparison across scopes is not a weaker measurement, it is a
different measurement, and the arithmetic between them is meaningless rather
than approximate. When a ledger line will be compared against later, record the
quantity in the line itself ("peak anon of the book_quotes read"), because the
number outlives the sentence that scoped it.

**Second, smaller rule from the same session:** a distribution statistic is only
comparable across windows if the sampling gate is the same. `p90` of anon looked
like a clean cross-window baseline and was invalid — the watchdog only emits
above 60% or on a 200 MB move, so `p90` measured *time spent high*, not
baseline. A true minimum (`min inactive_file`) was gate-independent and turned
out to be the discriminator between the windows that died and the ones that did not.

### 2026-08-16 — the decisive TEST for the stale shared index, and why "deletions vs HEAD" is not the test

The shared-index hazard has now fired **five** times. It has been handled by a
heuristic — "deletions-only against a HEAD that moved past it" — which is both
too weak and too strong. This session produced a decisive test and a counterexample.

**Too weak:** the 5th occurrence was **122 insertions / 147 deletions**, not
deletions-only, so the heuristic would have waved it through. It was a total
revert: the index blob was **byte-identical to `HEAD^`'s blob**, and its diff was
the **exact inverse** of HEAD's last commit (147/122).

**Too strong:** after disarming, the worktree still showed 2 deletions against
HEAD. One was a **live session re-taking an unowned lane** with a newer heading.
Acting on "a deletion vs HEAD means a revert" would have reverted an active
session's claim — the very failure the rule exists to prevent.

**The test, in order:**
1. `git ls-files -s -- <path>` for the index blob SHA; `git ls-tree HEAD -- <path>`
   for HEAD's. If the index SHA equals `git ls-tree HEAD^ -- <path>`, it is a
   pure revert-in-waiting. Disarm.
2. Otherwise compare three ways and ask the only question that matters:
   **is any content unique to the index (in neither HEAD nor worktree)?** If no,
   unstaging cannot lose anything and is always safe. If yes, READ those lines —
   a peer may have real work staged nowhere else.
3. A deletion against HEAD is **supersession until shown otherwise**. Read the
   replacing line before concluding anything. Newer beats HEAD routinely here,
   because HEAD is not where sessions work.

**Do not use `git <cmd> <rev>:<dotpath>`** to extract these — `.syndicate/` is
dot-prefixed and that form silently reads the wrong thing on Windows (existing
FORBIDDEN entry). Get blob SHAs from `ls-tree`/`ls-files` and read them with
`git cat-file blob <sha>`.

**Mechanism, confirmed:** peers commit through an isolated `GIT_INDEX_FILE`,
which never advances the shared index. The staleness is **continuous and
structural**, not occasional — expect it on every commit, not once a night.

### 2026-08-16 — `commit-guard.py` gates on `D` status and every real occurrence was `M`

The guard written to stop the shared-index hazard blocks only when the index
stages a **whole-file deletion** of a path that still exists on disk
(`--name-status`, `parts[0].startswith("D")`). It was built from the first two
occurrences, which were whole-file deletions (6 files, 4993 deletions).

**Occurrences 3-6 were all content reverts, status `M`, and the guard was
silent for every one of them** — including a staged
`syndicate/features/shared/book_grid_artifact.py` at 0 insertions / 17 deletions
whose blob was byte-identical to `f8ca54e1^`, where those 17 lines are the Drop 3
hook **executing on refresh-worker at that moment**. A bare `git commit` would
have stripped live production code with the worktree clean and the guard green.

This is the third instance in this repo of **a guard encoding an assumption about
HOW something fails and going quiet in the real failure mode**. A file's presence
on disk is the wrong observable: the hazard is a stale BLOB, and staleness is
invisible to any check that looks at paths rather than content.

**The rule going forward:** a guard against a stale index must compare the staged
**blob** against history — block when the staged blob equals
`git ls-tree HEAD^ -- <path>`, or when the staged content drops lines present in
BOTH `HEAD` and the worktree. And a green guard is evidence only once you know
what makes it read red: this one had never fired, which read as "no problem" and
actually meant "blind to this problem".

### 2026-08-16 — FORBIDDEN: attributing a dirty file to a person before diffing it against the REMOTE

Local `main` was 244 commits behind. `git diff` in that tree reported 52 modified
files, including 13 production files with large edits — `recommendation_engine.py`
+196/-28, `layer2_board.py` +144, `soccer_projections.py` +108/-12. I read that as
other sessions' uncommitted work, published it to the user as a blocker, and
messaged two sessions asking them to commit "their" work.

**All 28 blocking files were byte-identical to `origin/main`.** They were not
anyone's work. They were the upstream state in a tree whose HEAD had not caught
up, and `git diff` was measuring MY staleness against a 244-commit-old baseline.

The tell was available before I published: the same session had already
established that local main was a strict content SUBSET of origin. If local is a
subset, a local "modification" cannot be new work — it can only be the newer
content already upstream. I had the discriminating fact and did not apply it.

**The rule going forward:** a dirty file in a stale tree is a statement about the
BASELINE, not about a person. Before attributing it, diff the worktree against
the REMOTE (`git ls-tree origin/main` + `cat-file blob`), not against HEAD. Three
outcomes, and only the third is anyone's work: equal to origin (a no-op), a
subset of origin (stale), or carrying content origin lacks.

Corollary that cost three failed merge attempts: **untracked collisions are
revealed in batches** — each `git merge` names only the next ~7. Compute the set
directly with `ls-files --others --exclude-standard` INTERSECT
`ls-tree -r --name-only origin/main`. And **`git stash create` does not capture
untracked files**, so a snapshot taken that way is not the safety net you think
it is for exactly the files that block a merge.

### 2026-08-16 — the clean hour arrived, and the thing it was supposed to unblock does not run on that service

`state.md` and a session handoff both carried: *"the `win_prob` counter cannot
produce a reading while this continues — the producer keeps being killed or
restarted mid-run … that is a reason to keep deploys off refresh-worker."*
Deploys were held on refresh-worker on that basis.

**refresh-worker then ran 1h 41m clean (02:37:06Z -> 04:18:17Z, events API) and
the counter emitted nothing — because the producer never runs there.**
`refresh_wnba_oddsapi_props.py`: 26 log matches on **live-odds-worker**, **zero
on refresh-worker** all day. Positive control on the null: 2,346
`MEMORY_WATCHDOG` lines over the identical window, so the probe and the window
were both good.

The belief was never tested against **which service executes the code**. This
repo already has a rule for that (`project_which_service_runs_the_code`) and a
lane that shipped Drop 1 to the wrong service, where it sat inert. It recurred
because the claim was inherited in prose and re-stated, not re-derived.

**The rule going forward:** before accepting "X is blocked until service S is
healthy", grep the logs of S for the emitter of X. If the token has never
appeared on S, the dependency is imaginary and the mitigation being paid for —
here, a deploy freeze on a busy service — is being paid for nothing.

**Near-miss inside the same investigation, worth its own line:** I first searched
the substring `oddsapi_props` and found 38 matches on live-odds-worker, and was
one step from publishing "the producers run there". They were
`fetch_soccer_oddsapi_props_local.py` — the SOCCER fetcher, a substring
collision. **Search for the exact emitter or the exact script name; a substring
that contains your quarry's name is not your quarry.** The correct conclusion
survived only because I extracted the process cmdline instead of trusting the
match count.

### 2026-08-15 — OVERTURNED: "a fixture-relative cadence helps soccer". It is the ONE sport it hurts, because the sport is not the unit
- **What we believed:** soccer motivated the whole fixture-aware cadence lane, so soccer would
  be its main beneficiary. I shipped 1a/1b saying so in the commit message.
- **What was actually true:** the gate resolves ONE fixture clock per SPORT, and soccer's
  "sport" is ten leagues on ten calendars. The gap it returns is the MINIMUM across all of
  them, so it is almost never large. Modelled over 336 hours against the real 2026 fixture
  lists: the 24h tier is reached in **0.0%** of hours, and the gate yields **5.08 sweeps/day
  against 3.00 today (+69%)** — more overlap with MLB's peak, not less. Per-league the same
  tiers reach 24h in 49.3% of league-hours.
- **How we found out:** the call-volume check the lane required before enabling. It was run to
  answer a COST question and answered a CORRECTNESS one.
- **The rule going forward: before shipping a per-X gate, verify that X is the unit the data
  varies over.** An aggregate whose members have independent clocks collapses to its extreme —
  here a min() — and the gate then reads the aggregate as always-busy. The tell is cheap: model
  the tier occupancy before shipping, and if one tier is reached 0% of the time the unit is
  wrong, not the thresholds.
- **Second-order:** the single-league sports were fine all along (mlb 12.00 -> 5.45, wnba ->
  5.83, nfl_preseason -> 3.56), so the feature was ~85% right and the 15% was aimed exactly at
  the lane's stated goal. A partly-correct change whose incorrect part is the motivating case
  is the dangerous shape.
- *(evidence: `#440` plan Phase 1 cost-check section; lane `odds-cadence-off-the-mlb-peak`;
  fix `8640f872`)*

### 2026-08-16 — I TURNED ONE BUILD INTO A STRUCTURAL IMPOSSIBILITY, AND THE REFUTING NUMBER WAS IN THE PAYLOAD I ALREADY HAD

I measured the live game-line ledger at 03:00Z — `priceable 0`, so
`candidates 0` — and wrote, in a commit message, a lane block, `state.md` and a
`learnings.md` rule, that the recorder **could not** produce a row. Four hours
later a pre-deploy read at 04:22:51Z showed `priceable 1, candidates 1,
skipped_unchanged 1`.

**`skipped_unchanged` is the refutation, and I had already read that field
three times without asking what a non-zero would mean.** It can only be non-zero
when a record with the same key and identical numbers is already on disk —
`_moved(None, rec)` returns True, so an empty file always writes. So v1 had
written at least one row that night, on its own, before I changed anything.

The finding survived — 1 priceable of 4 considered is a self-selected sample with
no denominator, which is what v2 fixes. **The overclaim did not.** "It is empty
right now" became "it is empty by construction" with no additional evidence,
and the stronger form is the one that got written into four files.

**How to apply.**
- **"Currently zero" and "cannot be non-zero" are different claims with
  different evidence bars.** The second needs an argument from the code path,
  not a reading. If you find yourself writing *structurally*, *by construction*,
  or *could never*, either produce the code argument or downgrade the sentence.
- **A rate measured on ONE build is a sample of size one**, and a live slate is
  the most non-stationary population in this repo — the same counter moved
  25 → 4 → 1 across three consecutive builds earlier the same night, which I had
  quoted in the module docstring while generalising a different one-shot reading.
- **Before shipping a claim, ask what would refute it and check whether that
  number is already in the payload.** Here it was, in the same six-key dict, on
  every read.

Related: [[a rate, not a count]], [[read the field you already have]],
and the sibling entry above about a recorder gated on the publish decision — the
volume claim that justified v1's filter was wrong the same way, by assertion
rather than by counting.
### 2026-08-16 — FORBIDDEN: bundling a file write or a `git reset` into the same command as `git commit`
The `commit-guard` PreToolUse hook matches the COMMAND STRING and blocks the
whole thing. Twice in one session I wrote:
    cat > file <<EOF ... EOF        # then, same command:
    ... git commit ...
and once:
    git reset -- <path> ; ... git commit ...
Both were blocked, and **the non-commit half never ran**. The second case looked
especially convincing: the guard's own refusal text says to run `git reset`, so
I put the reset and the retry in one command — and it blocked again, identically,
because the string still contained `git commit`. The file in the first case did
not exist afterwards, and the next command failed with `pathspec did not match`,
which reads like a git problem rather than a hook problem.
**The rule going forward:** a command containing `git commit` may contain
NOTHING ELSE that must survive a refusal. Writes, `git reset`, `git add` of
unrelated paths — separate calls. A blocked command is all-or-nothing, so
anything bundled with the commit shares its fate.
Corollary already paid for elsewhere in this session: `[ cond ] || { echo ABORT; }`
placed after an `&&` chain reports ABORT when an EARLIER link failed, so the
abort message names the wrong cause. Check the actual failure before believing
the guard rail that fired.


### 2026-08-16 — A GUARD SCOPED TO THE WRONG OBJECT CRIES WOLF AND GOES BLIND AT THE SAME TIME

`commit-guard.py` evaluated its two predicates against `CLAUDE_PROJECT_DIR`.
Commits run wherever the shell is, and the repo's own recipe for a contended
tree is to commit from a linked worktree — which has its own index and its own
HEAD. So the guard read one object and protected another.

It blocked **three clean commits in one session**, each time naming a real
revert staged in a tree the commit was not touching. That half is loud and
merely annoying. **The other half is silent: a stale index in the worktree
actually being committed from was never examined at all.** Same defect, same
line of code, and only one of the two symptoms is visible.

The old code made this worse by *reasoning* its way past the case: it skipped
`git -C <dir> commit` because those "have their own index and are the documented
safe recipe". **Having your own index is not having a fresh one** — that exact
conflation is what the guard exists to catch, so it cannot also be the excuse
for not looking.

**How to apply.**
- **Name the object a check protects, and prove the check reads THAT object.**
  Not the repo — *this* index. Not the service — *this* deployment. A guard is
  a claim about a specific thing; scope drift makes it a claim about a different
  thing that happens to still return a verdict.
- **When a guard fires on something you know is fine, do not just override it.**
  Three false positives were three signals that it was reading the wrong tree,
  and the fix took twenty minutes once the question was asked.
- **A guard's false positives are self-reporting; its false negatives are not.**
  Whenever you find one, look immediately for the mirrored silence — they are
  usually the same bug, and only the loud half will ever come to you.
- Test it against REAL state, not mocks: the bug was *which directory a
  subprocess ran in*, and a mocked `git` reproduces that perfectly and wrongly.

Related: [[instrument blindness]], [[gate on the output, not the input]],
[[unknown must not default permissive]].

## 2026-08-16 — FORBIDDEN: reading a git error as noise from the NEXT command when it names the file the PREVIOUS one staged

I pushed `475b8c6c` with `<<<<<<< Updated upstream` / `=======` /
`>>>>>>> Stashed changes` inside `tests/test_ui_layout_probe.py`. That is a
Python syntax error: the file could not be collected at all, and `main` carried
a broken test file until `b5185678` repaired it.

**Git told me, in the same output as the push.** The command chained
`commit-tree`, `push`, then `git reset`, and printed:

    error: short read while indexing tests/test_ui_layout_probe.py

I read that as a complaint from the trailing `git reset` — the command nearest
the error — and moved on because the push line above it said success. It was a
report about **the blob I had just staged**: a concurrent session ran a stash
operation against the shared worktree while `git update-index --add -- <path>`
was reading that path, so `update-index` captured the file mid-write, conflict
markers and all.

What caught it was the blob-hash check afterwards
(`git hash-object <local>` vs `git rev-parse origin/main:<path>`), which is
already a standing rule here. The exit code did not catch it: the push
succeeded, because a blob with conflict markers is a perfectly valid blob.

**How to apply.**
- An error naming a path is about **that path**, whichever command in the chain
  emitted it. Do not attribute it to the nearest command; attribute it to the
  command that touches that file.
- On a shared worktree, never stage a path you are about to push straight from
  the worktree if anything else may write it. **Copy it to a private snapshot
  first, `git hash-object -w --path=<path>` the snapshot, and stage the
  resulting blob via `--cacheinfo`.** A concurrent writer then cannot change it
  under the stage. **`--path` is load-bearing, not cosmetic:** without it
  `hash-object` skips the clean filter, so a CRLF worktree file reaches the blob
  verbatim where `git add` would have normalised it (`core.autocrlf=true` here).
  Every Windows writer emits CRLF, so the writers are not the variable: measured
  2026-08-16, 0 of 34,820 tracked artifacts under `reports/ .syndicate/ data/
  docs/` have mixed endings. This recipe is the only path by which CRLF can land
  in a blob, and hand-normalising the bytes per-file is a discipline that works
  only until someone forgets. `docs/ai_context/todo.md`'s recipe already uses
  `--path=`; this generalises it.
- Verify by content, not by exit code: hash-compare the pushed blob, and for a
  source file `ast.parse` it. "The push succeeded" says nothing about what was
  in the blob.
- Corollary to the existing rule against bundling `git reset` into the commit
  command: the bundling is also what let a real error hide behind a success
  line. Keep them in separate calls so each output has one owner.
- This is [[feedback_instrument_blindness]] in a new place — a green push is
  evidence only once you know what a bad push would have printed. It printed
  exactly that, one line above.

### 2026-08-16 — OVERTURNED: a NOTE in the code that names a cause is a HYPOTHESIS, not a measurement — even when it is right about everything else
- **What we believed:** `generate_smartsim2_nfl_projections.py`'s degenerate-run
  guard prints *"the pbp lives on the mounted disk and is absent from the repo
  checkout. If DATA_ROOT points at the checkout, that is the bug, not a missing
  download."* Production showed `DATA_ROOT` = the checkout, so the NOTE read as a
  confirmed diagnosis and I built, tested and deployed a fix for it.
- **What was actually true:** the pbp is absent from EVERY root, the mounted disk
  included. The NOTE's first clause ("the pbp lives on the mounted disk") was the
  unverified half, and it was false. Traced afterwards: ten scripts reference
  `pbp`, all reads, **zero writes** — nothing in the repo can produce that file,
  though it demonstrably existed on 2026-08-13.
- **How we found out:** the falsifier written into the deploy row before shipping
  — *"if `DegenerateProjectionRun` still raises, root selection was a red
  herring"* — fired 8 minutes after the deploy.
- **THE SECOND TRAP, which nearly hid it:** the fix returns a NAMED fallback path
  when nothing is found, and that fallback equals the path the OLD code printed.
  **"Fix not deployed" and "fix ran and found nothing" emitted an identical log
  line.** Only reading the deployed commit's CONTENT distinguished them.
- **The rule going forward: a comment that asserts a cause carries the author's
  confidence, not their evidence.** Treat the clause you did not measure as the
  one most likely to be wrong — here, everything about the checkout was correct
  and verifiable, and the single unverifiable clause was the false one. And when
  a fix's failure mode prints the same string as its absence, the log cannot
  verify it; confirm the deployed content instead.
- *(evidence: `#441`; deploy `97491161` row in `deploys.md`; lane
  `nfl-pbp-root-resolution`)*

## 2026-08-16 — RULE: fix a bad commit MESSAGE by rebuilding the commit from its own tree, not by `--amend` and not by living with it

- **What we believed:** the shared-tree recipe offered two options for a wrong
  commit message — `git commit --amend -- <paths>` (dangerous: without a
  pathspec it commits the whole shared index, and it once swallowed another
  session's 22 staged files) or *"accept the message and move on."* Written as a
  binary, so a message defect looked like something you either risk a disaster
  over or simply eat.
- **What is actually true:** there is a third form, and it is strictly safer than
  both. The tree object from the first commit is already written and immutable.
  Rebuild with the SAME tree and the SAME parent, only the message differing:

      NEW=$(git commit-tree <tree> -p <parent> -F - <<'MSG' ... MSG)
      git update-ref refs/heads/<branch> "$NEW" "$OLD"      # compare-and-swap

  It reads no file, touches neither the shared index nor the working tree, and
  cannot pick up another session's staged work **because it never consults an
  index at all**. The two-argument `update-ref` is a compare-and-swap: if another
  session committed in between, it fails loudly instead of discarding them.
- **How we found out:** used PowerShell here-string syntax (`@'...'@`) inside the
  Bash tool, where `@'x'@` is concatenation, not a here-string — it pasted a
  stray `@` at both ends of the message (`ceccb672`). Rebuilt as above to
  `01c53f56`; blob hashes byte-identical, `git show --stat` exactly the 2 intended
  files, CAS passed.
- **The general form:** *a commit is (tree, parents, message). Only the message
  was wrong, so only the message should be rebuilt.* `--amend` is dangerous here
  precisely because it re-derives the tree from the index — it does far more than
  the intent required. Prefer the plumbing verb that touches only the broken
  field over the porcelain one that recomputes everything.
- **Corollary, and it is the reason this is worth writing down:** the same
  reasoning covers any commit whose CONTENT is right and whose metadata is wrong.
  It does not extend to fixing content — that needs a new tree, and then the
  ordinary contention rules apply.
- **Harness note:** the Bash tool is Git Bash. PowerShell here-strings
  (`@'...'@`) are silently valid Bash that means something else. Use a quoted
  heredoc (`<<'MSG'`) or `-F -`. It fails quietly, not loudly — the commit
  succeeded and only `--oneline` showed the damage.
- *(evidence: commits `ceccb672` -> `01c53f56`, session `layer12-board-briefs`;
  refines the amend-trap entry in the shared-tree commit recipe)*

## 2026-08-16 — a per-row field read off ONE row and generalised to all of them

**Overturned:** my own same-day claim that "every exercised `win_prob` run is on
an OLDER commit", which I wrote into `deploys.md` and `state.md` and pushed,
along with a discriminator ("one `rows>0` on a current commit") for resolving it.

**The discriminator was already satisfied in the payload the claim was written
from.** `wnba/live-odds-worker`'s `latest` line read `dd53d47c rows=0`. Priors
1–3 carry the SAME SHA and are exercised — `rows=24/9/15`, 48 rows — three lines
below it in output already on my screen. I read the commit off the summary row
and generalised it to every row sharing that commit. The same error made "5
consecutive `rows=0` runs on each service" wrong for live-odds-worker, which has
exactly one.

**Rule:** when a field appears on every row, a value read off ONE row is a fact
about that row only. Before writing "every X is Y", scan the column. This is the
`read-the-field-you-already-have` failure in its most expensive form: no new data
was needed, no tool call would have helped, and the wrong version reached
`origin/main` and a scheduled task that would have sent every future run hunting
for a result already in hand.

**Corollary, learned the same hour:** `git diff --stat origin/main..HEAD` is a
TREE comparison, not a push manifest. When you are behind, incoming upstream
changes render INVERTED — it showed "42 deletions from `learnings.md`" for a push
that deleted nothing. Read `git log origin/main..HEAD` for what you would push.

*(evidence: retraction commit `14269339`; the reading itself in `deploys.md`
2026-08-16; session `wnba-win-prob-counter-read`)*

### 2026-08-16 — MY DELETION GUARD PASSED WHILE ANOTHER SESSION'S CONTENT WAS SUBSTITUTED UNDER MY COMMIT MESSAGE. `git add <path>` stages the WORKTREE, and a clobbered worktree file is insertion-only

**What happened.** I appended a 44-line lane to `.syndicate/lanes.md`, then
committed it through an isolated `GIT_INDEX_FILE` with the documented guards.
`git diff --cached --numstat` read `44  0  .syndicate/lanes.md` — 44 insertions,
**zero deletions** — so the deletion guard passed, the file-count guard passed,
and `e543e8dd` was created.

`e543e8dd` does not contain my lane. It contains **44 lines of a parallel
session's lane** (`layer2-board-quality`). Between my append and my commit, that
session did a read-modify-write of `lanes.md` from a copy taken before my append.
Their write dropped my 44 lines and added their own 44. `git add` then staged the
worktree faithfully. I discovered it ~20 minutes later, only because a later edit
asserted `s.count(heading) == 1` and got `0`.

**Why every existing guard was blind to it.** The known rule is that an
isolated-index commit leaves the SHARED INDEX staging a revert — that is about
index state, and it is real. This is a different mechanism:

- The clobber happened in the **worktree**, not the index.
- The substitution was **insertion-only** relative to `HEAD`, so a deletion
  count of 0 is exactly what a clean append looks like. **The deletion column
  cannot see a swap.** It is a guard against removal, and this was replacement.
- The line count matched by coincidence (44 for 44), but nothing depended on
  that — any count would have passed.
- `git diff --cached --stat` read by a human would also have passed: it says
  "lanes.md +44", which is what I expected to see.

**The rule going forward.**

1. **A guard on the SHAPE of a diff cannot confirm its CONTENT.** If you are
   committing a file you wrote a specific string into, assert **the string**, in
   the same shell, against the staged blob — not against the worktree:
   `git show :<path> | grep -qF "<your unique marker>" || exit 1`.
   `git diff --cached --numstat` answers "how much changed", never "is my change
   the thing that changed".
2. **For shared append-only ledgers, prefer `cat >> file` over any
   read-modify-write.** An `O_APPEND` write cannot drop another session's lines;
   a Python/Edit read-modify-write silently can, and will, because five sessions
   share this worktree. I used `>>` for the first append and it was still lost —
   because the *other* session used read-modify-write. So this rule only helps
   if everyone follows it, which is the argument for putting it here.
3. **Re-read your own marker after writing to a contended file**, before moving
   on. The whole loss window here was ~20 minutes of work continuing on the
   belief that the lane existed.
4. **Committing a shared ledger file commits whatever is in it.** My commit
   message described my lane and the commit delivered theirs. Nobody was harmed
   — their lane is committed and correct — but the ledger now has one commit
   whose message and content disagree, which is exactly the shape that makes
   `git log -S` archaeology lie later.

---

## 2026-08-16 — OVERTURNED: a pinned SHA identifies deployed CODE

**The belief.** Two scheduled measurement tasks pinned their comparison with
"if the live SHA is no longer `d72d670c`, the comparison is invalid — a
different SHA may have reverted the fixes." That reads as rigour. It is a
string equality test standing in for a question about content.

**What happened.** Within a day refresh-worker moved to `97491161`. Ancestry
said all three fixes under test were ABSENT from live. Both facts were true and
the conclusion they invite — "reverted, comparison invalid" — was false. The
branch had been rebased: `51ae7218`→`164f6e80`, `21f8a165`→`1409e96f`,
`aa190d58`→`d72d670c`, identical patch-ids, all three running the whole time.
The one commit actually added on top was an unrelated NFL pbp fix.

**Why the wrong version survived review.** A rebase changes every SHA while
changing no code, so the *stricter-looking* test (equality) is the one that
fires falsely, and it fires in the direction that looks responsible — declaring
your own measurement invalid. A guard that errs toward "invalid" does not feel
like a bug. It quietly throws away good evidence.

**The rule.** Ask whether the code is IN what runs, never whether the tip
matches:

```bash
git merge-base --is-ancestor <fix-sha> <live-sha>
```

Linear fixes collapse to one check on the newest. A FAILED containment check is
still not a revert finding — re-check by `git patch-id --stable` across
`git log <live-sha>` first, because the next rebase renames the pin too. This
is the same shape as the existing rule that a deployed fix can be inert: both
say **test the property you care about, not a proxy that correlates with it.**

## 2026-08-16 — CORRECTED IN-SESSION: at-cap is not a kill

`container_memory_mb` hit **4096.0 MB = 100.0% of a 4096 MB cap** across a 5h
window, 2714 samples. I led a report with it as an escalation. The events API
then showed **zero OOM kills in that same window** — while the 8-day census
found 42, **41 of them between 15:00 and 23:59 local**, i.e. none in the hours
I had sampled.

`memory.current` includes page cache. Reaching the cap with reclaim succeeding
is what a healthy page-cache-heavy process looks like. The repo already carried
"`memory.current` includes page cache — split anon vs `inactive_file`"; I even
wrote that caveat into my own report and then still led with the number as
alarming. **A caveat stated is not a caveat applied.**

Second-order, and the more useful half: the sampling schedule was aimed at the
wrong hours. Two of three baseline records covered morning. A baseline that
never covers the failure window measures the wrong distribution no matter how
many samples it has. Cron moved `15 */4 * * *` → `45 19,22,1 * * *`.

---

## 2026-08-16 — NEAR-MISS: verifying against a ref NAME is not verifying

**What almost shipped.** A three-file ledger commit that also silently reverted
another session's in-flight feature: `book_shortlist.py` −129,
`layer2_board.py` −172, `test_layer2_bettable_books_and_labels.py` −224, plus
`deploys.md` −43 and `lanes.md` −75. It would have been a valid commit, pushed
cleanly, with a message about ledger writes.

**The mechanism.** I built a private index with `git read-tree origin/main`,
then verified with `git diff --cached origin/main`. Between those two commands
another session pushed. **Each command resolved the name independently**, so the
index was built on one commit and checked against a different one. Everything
present in the newer remote and absent from my older index read as a deletion —
which is exactly what it would have become on push.

**Why it nearly passed review.** The two checks disagreed and the RIGHT-LOOKING
one was the misleading one:

    git diff --cached --numstat <ref>   ->  +176 / -4     (looks perfect)
    git diff --cached <ref> | grep -c   ->  569 removed   (looks like a bug)

`+176/−4` was a true statement about a base that no longer existed. My first
instinct was that my own `grep '^-[^-]'` was matching markdown bullets — i.e. to
explain away the alarming number and keep the reassuring one. The discrepancy
was the signal. **When two views of the same diff disagree, the assumption they
share — here, that `<ref>` means one fixed thing — is the thing to doubt.**

**The rule.** Resolve the base to a SHA **once**, and use that SHA for all three
of build, verify, and commit parent:

```bash
BASE=$(git rev-parse origin/main)     # once
git read-tree $BASE ; ... ; git diff --cached $BASE
git commit-tree $TREE -p $BASE ...
git push origin $COMMIT:refs/heads/main
```

With the SHA as the parent, a mid-flight push makes the **push** fail loudly as
non-fast-forward. With a moving name, it makes the push SUCCEED and the revert
invisible. Prefer the failure.

**Where this sits.** Same shape as the SHA-pin bug fixed hours earlier in the
oom-band tasks, approached from the opposite side: there a name was too rigid
(a pinned SHA could not survive a rebase and read live fixes as reverted); here
a name was too fluid (a branch ref could not survive a push and read live work
as deleted). One rule covers both — **bind the identity you are reasoning about
for as long as you reason about it, and check containment rather than equality
at the edges.** On a tree with seven concurrent sessions, "current" is not a
value. It is a race.

### 2026-08-16 — FORBIDDEN: never add an instrument without first checking who captures the channel it writes to

A `win_prob` null counter was added to both prop producers and deployed to two
workers. It printed to stdout from `__main__`'s `finally`. It could never be
read: `refresh_odds_sources._run_command` runs every producer under
`subprocess.run(capture_output=True)` and **discards a successful step's stdout**
— only a bounded stderr tail survives, and only for a FAILED step.

**The repo already knew.** `ops.py:2263` records the identical trap, found live
2026-08-01, for the SAME script, and says a keyvalue state file is "the only way
to observe" that step. The counter was added into it anyway.

**What made it expensive is the shape of the failure, not the bug.** The counter
existed to answer "has the `or 0.5` branch been exercised?", and its silence was
indistinguishable from "the branch never fired". A scheduled task was then built
ON that silence and would have reported "not yet run" forever. The producer HAD
run — PID 1900 in the worker's own process census at 23:36:05Z, started
23:36:04Z — while the log carried zero occurrences.

**The rule:** before adding a counter/log/metric, establish that the channel
reaches a reader — name the process that captures it and where that capture
lands. `print()` is not a channel; it is a hope about one. Prefer the mechanism
the codebase already proved crosses the boundary (`write_json_file` + a route).

Corollary, learned the same night: **an instrument must also report what it
LOOKED FOR, not only what it found.** `/api/ops/win-prob-null` returns `probed`
beside `readings`, so "nothing recorded" cannot be confused with "looked in the
wrong place" — the exact ambiguity that made the log version unreadable.

Related: the emitter rule already in this file covers *reading* an absence; this
one covers *building* the emitter. Both were needed. `[measured 2026-08-15/16]`

---

## 2026-08-16 — NARROWING AN INSTRUMENT TO A MEASURED DISTRIBUTION BUILDS IN A BLIND SPOT

**What I did, and it looked like good work.** A census said **41 of 42**
refresh-worker `oomKilled` events fell in **15:00–23:59 local**. So I retuned
`branch-overlap-baseline-watch` from `15 */4 * * *` (six samples/day, half of
them in hours with zero recorded kills) to `45 19,22,1 * * *` — three samples,
tiling the kill band. Fewer samples, full coverage of where the failure lives.
I reported it as a strict improvement.

**Hours later, on the same day**, refresh-worker was `oomKilled` at
**16:34:32Z (11:34 local)** and **17:19:42Z (12:19 local)**. The new schedule
observes neither. The old one would have caught both.

**The error is not the schedule. It is what the schedule silently converted.**
Before narrowing, "no kill in the morning sample" was a *finding*. After
narrowing, morning kills cannot appear at all — so the same silence now means
nothing, while still *reading* like a clean result to anyone looking at the
baseline file. **Narrowing an instrument turns "we did not observe X" into "we
cannot observe X", and the two are indistinguishable downstream.**

**Why the distribution did not transfer.** The 8-day census was dominated by
ordinary days. The two daytime kills landed on an afternoon carrying **four
deploy cycles**, and every deploy reboots the worker into cold hydration — a
known route to the same ~2GB transient. Deploy-provoked and slate-provoked kills
are plausibly **different populations**, and only the second is confined to the
band. A distribution measured under one regime does not license an instrument
that can only see that regime.

**The rules.**

1. When you narrow an instrument, **write the blind spot down where the output
   is read**, not only in the commit that narrowed it. `state.md` now says
   plainly that anything sampling 15:00–23:59 cannot be cited as evidence that
   daytime kills did not occur.
2. **State the denominator's regime, not just its size.** "41 of 42 over 8 days"
   invites the reading "kills are evening"; "41 of 42 over 8 mostly churn-free
   days" does not.
3. For absence claims about a rebooting service, **the deploy count in the
   window is part of the claim.** Absence of a daytime kill is evidence only if
   the window was also deploy-free.
4. Prefer keeping one cheap wide sample when narrowing. The cost of the three
   dropped morning samples was small; the cost of not being able to see a new
   failure population is not.

**Related, and the same shape as the day's other two entries:** the SHA pin
could not tell a revert from a rename, the ref name could not tell a base from a
moving target, and here a cron could not tell a quiet window from an unobserved
one. Each is a measurement whose *scope* silently stopped matching the question
it was still being used to answer.


## 2026-08-16 — FORBIDDEN: never test what is deployed with `git merge-base --is-ancestor`. It answers a question about HISTORY; deployment is a question about CONTENT.

Measured twice in one session, in opposite directions, on the same three services:

- `edbbee9d` (spread-sign fix) is **NOT an ancestor** of live `97491161` — and
  the fix **is running**. `git show 97491161:...layer2_board.py` returns the
  same 3 occurrences as `main`.
- `5a94b134` (the `min()` score guard) is **also not an ancestor**, and that one
  genuinely **was missing**.

Identical ancestry result, opposite truths. The cause: the services run
`deploy/nfl-pbp-root`, not `main`, so ancestry against `main` is simply not the
relation being asked about. `project_web_runs_a_deploy_branch_not_main` recorded
this for WEB; it is true of the WORKERS too.

**The rule:** `git show <live-sha>:<path> | grep -c <marker>` against the same
command run on `main`. Do it on every service the question touches — on 08-16
web, refresh-worker and live-odds-worker gave three different answers.

**And the reason this bites:** a deploy branch cut from an older commit
**silently un-ships every fix landed since the branch point**. `deploy/nfl-pbp-root`
branched at `b0ab37a1` (08-15 17:26 CDT); `5a94b134` landed at 19:04 CDT — 1h38m
later — so a measured, shipped, ledgered fix was inert on all three services for
~22 hours with nothing anywhere reporting it. Cutting a deploy branch is a
silent partial rollback of everything younger than its base.

## 2026-08-16 — FORBIDDEN: never use a fresh `git worktree` as a test baseline for anything that reads `data/`.

Used one to establish which test failures pre-dated my change. It reported 22
failures; my tree reported 30; I attributed 8 to myself. **Three of those 8 were
the worktree lying.** A fresh checkout has only git-tracked `data/`; this tree
carries untracked mirror output. `read_book_quotes_latest('mlb','2026-08-09')`
returns **0 rows** in the worktree and **36,424** here.

It also exposed the real defect underneath: `test_layer2_sweep_state`'s
`no_quotes` fixture patched `read_book_quotes` while the code calls
`read_book_quotes_latest`, and `raising=False` swallowed the mismatch. **The
fixture was inert and the tests were reading the real disk** — they passed or
failed on what the machine happened to have, not on the code. A green run was
evidence about the checkout.

**The rule:** a baseline is only valid for tests whose inputs it actually
shares. For data-touching tests, establish the baseline IN THE SAME TREE, or
prove the test cannot reach the disk. And `raising=False` on a monkeypatch
turns a typo into a silent no-op — pair it with an assertion that the patch
took, or name the function the code actually calls.

## 2026-08-16 — the shared-index revert fired TWICE against one session, and the second time it was armed AFTER a clean push.

`project_shared_index_can_hold_a_revert` is already a rule; this adds the
frequency and one new detail. In one session:

1. Two new files (`book_shortlist.py`, a new test file) staged as **deletions**
   while present on disk and already committed+pushed.
2. After the UI commit was pushed and verified by blob hash, the index re-armed
   a **complete revert of it** — `-24, -118, -33, -125, -93` = **393 deletions**
   across all five files.

Both disarmed with a path-scoped `git reset` (touches no file). **A clean push
does not end the exposure** — the index re-armed after it, so the check belongs
immediately before EVERY commit, not once per session. Read
`git diff --cached --numstat HEAD` and look at the DELETION column, scoped to
your own paths, so you disarm your revert without touching another lane's
staged work.

## 2026-08-16 — a mirrored row set makes a wrong join look like a UNIFORM defect, which is the most convincing kind.

Verifying the spread-sign fix, I joined shortlist rows to book-grid rows on
`(event, market, segment, line)` and got **3 of 3 home rows still inverted** —
uniform, deterministic, exactly the signature of a real bug.

It was the join. The grid carries **mirrored rows** for one market instance:
`row.line=+1.5` with `home_cells=-1.5` sitting beside `row.line=-1.5` with
`home_cells=+1.5`. Matching on `line` picks the wrong twin every time, so the
error is uniform BY CONSTRUCTION. The discriminating field was the **price
vector** — `{leovegas_se:123, prophetx:140, unibet_nl:125, unibet_se:125}`
identifies exactly one source row — and against it the answer is 12 of 12
CORRECT.

**The rule:** uniformity is not evidence of a real defect; a wrong join is
uniform too. Before believing a 100%-consistent finding, ask what the join key
would do if two rows could both match it. Prefer a key that cannot collide
(here: the prices, which the row already carried).

### 2026-08-16 — I REPLAYED THE HELPER OVER REAL PRODUCTION ROWS, CALLED IT VERIFIED, AND SHIPPED A FIX THAT COULD NOT REACH 3 OF THEM. A replay proves the FUNCTION; only the call path proves the FIX

**What happened.** To verify an edge-attribution fix before deploying, I fetched
the real served payloads, filtered to the exact rows that were serving a blank
`Edge` with no reason, and ran the changed helper over them. Result: **287 of
287 attributed, 0 unattributed.** I wrote that into `deploys.md` as the
verification and deployed.

The post-deploy falsification sweep returned **FAIL: 3 rows unattributed** — the
same 3 my replay had "proved" were covered. `wnba_game_projections.py:208`
writes `row["projection"]` directly and never calls the function I fixed. The
helper handled those rows correctly and was never invoked on them.

**Why the replay was structurally incapable of catching it.** I supplied the
inputs myself. `_edge_unavailable_reason(row, model_prob=..., fair=...)` called
with hand-passed arguments answers "given these inputs, what does this function
return" — a question about the function. The question that mattered was "does
production ever call this function with this row", which the replay never asked
and could not. **Feeding real data to a function is not the same as
demonstrating that the real path feeds it.** The realism of the *inputs* made
the test feel like an integration test while it stayed a unit test.

This is the standing `presence is not reachability` rule, and I had it in front
of me — I even wrote "trace the user-visible field backwards to its writers" in
this lane's own notes about `fair_price` having four producers. I then verified
forwards from the function I had chosen.

**The rule going forward.**

1. **Before verifying a fix, enumerate the WRITERS of the user-visible field,
   not the callers of your function.** Grep the field name (`row["projection"]
   =`, `projection[...] =`), not the module. A producer that assigns the field
   directly never imports your code and cannot be found from your side.
2. **A replay that you supply the arguments to is a unit test with production
   fixtures.** To make it an integration check, it must enter through the same
   entrypoint production uses — or it must assert on the SERVED payload after
   the code runs, which is what the falsification sweep did and why it worked.
3. **Count the population BEFORE and AFTER at the same place.** My "287 of 287"
   and the sweep's "3 remaining" are not contradictory — they measured different
   things. Only the second was measured where the user reads it.
4. **This is why the falsification test was written as a RESIDUAL and not as
   "the reason string appears".** The string appeared on 287 rows in replay and
   on 1,245 rows in production while 3 were still silent. A presence check would
   have passed both times. **The pre-registered residual is the only reason this
   was caught rather than shipped as done** — keep writing acceptance criteria
   as "count of things still wrong, expected 0".

### 2026-08-16 — a slug-level check on a shared ledger is blind to the loss it is meant to catch
- **What nearly shipped:** the working copy of `lanes.md` was stale by **64
  lines** against HEAD. `git diff --cached --stat` looked normal (0 file
  deletions), and a heading-slug comparison reported only one absent lane.
  Committing it would have silently reverted an OPEN lane
  (`branch-overlap-manual-run-marker`) and a DEPLOYED-and-verified update block
  (`layer1-board-coverage`) belonging to two other sessions.
- **Why the cheap checks passed.** Three of the four differing headings were
  *legitimate supersessions* — the disk copy was NEWER (a lane closed, a deploy
  at 17:53Z). So the slug diff was mostly noise, and the one real loss sat inside
  it looking identical. "0 deletions" is about FILES; a ledger loses content by
  being rewritten from a stale in-memory copy, which shows up as an
  insertion-heavy diff.
- **The rule going forward:** before committing any `.syndicate/**` ledger,
  compare **lines**, not slugs: every non-empty line in `HEAD:<file>` must be
  present in the staged blob, and each survivor of that check must be
  individually confirmed as a supersession — by reading BOTH texts and deciding
  which is newer — not assumed to be one.

    py -3 -c "import subprocess; g=lambda r: subprocess.run(['git','show',r],capture_output=True,text=True,encoding='utf-8',errors='replace').stdout.splitlines(); h=g('HEAD:.syndicate/lanes.md'); s=set(g(':.syndicate/lanes.md')); print([l for l in h if l.strip() and l not in s])"

- **Generalises beyond git.** This is the same shape as
  `shared-index-can-hold-a-revert` and `presence-is-not-reachability`: the check
  ran, returned green, and was measuring a coarser quantity than the failure.
- *(this session also shipped a tool whose OWN OUTPUT exposed a defect in it —
  `_deploy_trigger` labelling `server_failed` events with the `blueprint_sync`
  signature because they carry no `trigger`. Absence of a field is a fact about
  an event's SHAPE, not evidence about its cause. Same family as
  `unknown-must-not-default-permissive`.)*


## 2026-08-16 - FORBIDDEN: never let a branch sit behind a deploy gate without re-cutting it. Waiting is itself a source of staleness.

A worker branch (`b8939778`) was cut on live `f88796a9`, then held 14 minutes for
an MLB sim to finish. In that window another session shipped TWICE - `b9f2b5f1`
(17:53:08Z) and `cf467794` (18:07:36Z). **Deploying the branch at the end of the
wait would have reverted both.** It was correct when cut and a revert when fired.

Re-cut on `cf467794` and the props ridealong was dropped entirely, because
`cf467794` already carried it. `git diff --name-only cf467794 -- scripts/` on the
new branch is EMPTY, which is the check that proves the other lane's work is
untouched.

**The rule:** re-read the live SHA immediately before firing (already a rule) AND
re-cut if it moved. The longer a branch is gated, the more likely it has silently
become a revert. On a tree with five sessions deploying, "live" has a lifetime of
minutes.

## 2026-08-16 - FORBIDDEN: a deploy does not race another deploy on this platform. It CANCELS it.

Fired a web deploy at ~18:18 and it **cancelled `a92f76e9`**, another session's
983-insertion Ask change that had been cut on the same live SHA a minute earlier.
Their code was safe in git; their DEPLOY was silently dropped, and a cancelled
deploy is invisible from the session that owns it.

Re-shipped as `ad77e46a`, a union of both branches, after verifying the file sets
were disjoint (`git diff --name-only` intersection empty). Deployed the union
immediately so it superseded my OWN in-flight deploy rather than costing a third
restart.

**Re-reading the live SHA protects you from shipping a revert. It does NOT
protect the other session's in-flight deploy.** These are different failures with
different fixes. After every deploy, read the deploys list for a `canceled` entry
inside your window, and own the re-ship if one appears.

## 2026-08-16 - a verification script needs the same predicate discipline as the code it verifies, and a disagreeing verifier is suspect BEFORE the fix is.

Measuring the board deploy, two checks reported partial failure of fixes that had
fully landed:

- `h2h_lay` counted with `'lay' in market` - which matches **player**
  (p-**lay**-er). Reported "7 remaining, was 9", a completely plausible partial
  failure. The shipped `_is_lay_market` guards this exact case with `'_lay'`;
  the checker did not. True answer: **0**.
- `sim_view` looked for on shortlist ROWS. It is stamped by
  `_layer2_board_columns`, which feeds CARDS. Rows: 0. Cards: **108/108**.

Both would have been written up as "the fix did not work". **When a measurement
disagrees with a well-founded expectation, check the measurement first** - it is
newer, less reviewed, and was usually written in a hurry at the end.

## 2026-08-16 - `check_deploy_safety.py` can report a blocker that does not exist, and a BLIND read of it is not a CLEAR one.

Two distinct failures of the gate in one evening:

1. **Phantom blocker.** It reported a board build "IN FLIGHT since 17:57:07Z"
   across another session's 18:07:36Z deploy, which restarts the worker and
   therefore kills any running build. Falsified against the OUTPUT, not the
   marker: the shortlist artifact was still stamped 17:35:43Z, 36 minutes stale,
   so that build produced nothing. Same shape as `#443`.
2. **Blind read.** While web restarted it returned `[UNKNOWN] HTTP 502` - it
   reads live-refresh state off the WEB service. That string contains neither
   `NOT CLEAR` nor `CLEAR:`, so a watcher testing `'NOT CLEAR' not in out`
   declares the gate clear **precisely while it cannot see**. I wrote that
   watcher and caught it before it reported.

**The rule:** gate on an explicit positive (`CLEAR:` present) AND the absence of
`[UNKNOWN]` - never on the absence of a negative. Cross-check any "build in
flight" claim against the artifact's `written_at`, which is the output rather
than the marker.

### 2026-08-16 — FORBIDDEN: trusting a commit you verified only BEFORE `git commit`. Guards cannot see corruption that happens DURING it
- **What happened:** an isolated-index commit of 3 ledger files produced a commit of
  **14 files** that rendered every path it had not re-read as a DELETION — including
  this session's own `scripts/fetch_nfl_pbp.py` (0/276), `run_refresh_worker.py`
  (0/193) and another session's `syndicate/features/soccer/cards.py` (0/64).
- **Mechanism:** `git commit` refreshed the index and hit
  `reports/live_refresh_loop/latest_live_refresh_tick.json` **while the worker was
  writing it**. Git printed `short read while indexing` and committed anyway,
  against a partially-read index.
- **Why every guard missed it:** all of them — file count, deletion count, content
  assertions — ran on `git diff --cached` BEFORE `git commit`. They were correct.
  The object that resulted was not the object they described.
- **The rule going forward: verify a commit AFTER it exists.** `git show --numstat
  --format="" HEAD` immediately after committing, and compare it to what you staged.
  On this repo that is not optional: the worktree contains live artifacts a worker
  is writing continuously, so a torn read during commit is a standing hazard, not a
  freak event.
- **Recovery, for next time:** it never reached origin and the worktree was intact.
  The branch move that orphaned the bad commit ALSO reverted two ledger files, but
  the orphaned object still held them — `git show <orphan>:<path>` recovered both.
  An orphaned bad commit is a backup of the work it appeared to destroy.
- *(evidence: `c1ff7b21` orphaned; recovery in `af7e864d`)*

## 2026-08-16 — FORBIDDEN: letting a FITTED MODEL judge, when a model-free measurement of the same thing is available

Three false alarms in one day on `scripts/ui_layout_probe.py`, all on a healthy
board, all the same mistake wearing different clothes:

- **raw group spread** failed mlb desktop at 313px while cards carrying identical
  content differed by 70px — 243px of it was the 33-57 pair range;
- **a residual AT its own noise floor** (164px == floor) failed the budget while
  the same row printed "this is text wrap, not layout deviation" one clause
  earlier;
- **a CURVED fit** passed `reliable` at `fitRatio` 0.20 and then failed on a
  structured residual, accusing the only card at its pair count — a card with no
  peer, so the accusation could not be checked even in principle.

The common root: **the fitted line was treated as ground truth.** Every one of
those verdicts was a statement about the MODEL's failure to describe the page,
reported as a statement about the PAGE.

The fix that dissolved all three at once was to notice that a model-free
measurement of the same quantity was already being computed: two cards carrying
the same data should be the same height. No slope, no intercept, no reliability
bar, and it works on slates where nothing can be fitted at all.

**How to apply.**
- When a model and a model-free measurement of the same thing disagree, the
  model-free one is the evidence and the model is the hypothesis. Do not ship a
  verdict that only the model supports.
- **A goodness-of-fit statistic cannot detect misspecification.** `fitRatio` is
  residual/explained, so a wide explained range certifies a bent line — measured:
  a fit whose per-pair cost ran 41.3 -> 61.8 -> 76.6 scored 0.20 and `reliable`.
  If a number is used to certify a model, ask what it reads when the model is the
  WRONG SHAPE, not merely noisy.
- **An accusation needs a peer.** "This card is +79px off" means nothing when
  that card is the only one of its kind on the page; the comparison had no
  control. Prefer checks that compare like with like, and say so when no
  comparison was possible rather than passing silently.
- Corollary, learned the same day: a residual sitting AT its own noise floor has
  measured nothing. Report the floor next to any residual, or the number reads as
  signal when it is the instrument's own resolution.
- Same family as [[feedback-instrument-blindness]] and
  [[feedback-gate-on-the-output-not-the-input]]: a healthy reading is evidence
  only once you know what makes it read unhealthy.

### 2026-08-16 — OVERTURNED: reasoning by analogy from a just-solved defect. `#441` needed a fetcher; its look-alike `#445` needed four lines and would have been made WORSE by one
- **What we believed:** `#445` looked identical to `#441` — a projection generator
  dying on an absent input — so the ticket I wrote proposed the `#441` shape:
  fetch it, or fix the path resolution. It also called the hard-coded 2025
  filename the deeper defect.
- **What was actually true:** the generator already had a CFBD fallback for
  exactly this case, already called by `main()`, with a docstring naming the
  situation. It was unreachable only because the read RAISED instead of returning
  empty. The fix was four lines and needed no new data source.
- **And the ticket's "deeper defect" was a trap.** Re-pointing the filename at a
  2026 path would have rated the 2026 season from 2025 predicted totals: a
  silently wrong artifact, strictly worse than the crash, which is at least
  visible. All 278 such files in the checkout are 2025; nothing writes a 2026 one.
- **The rule going forward: a defect that RESEMBLES the last one earns a code
  read, not a transplanted fix.** The resemblance is in the symptom (generator +
  absent input + relaunch loop); the remedy lives in the cause, and the causes
  differed completely — `#441` had no writer anywhere, `#445` had a working
  substitute that an exception hid. Read the failing function's siblings before
  proposing a remedy; the previous ticket is evidence about the previous bug only.
- **Corollary on my own tickets:** a next-steps list written while a defect is
  fresh encodes the shape of the LAST investigation. Treat it as a hypothesis to
  test, not a plan to execute — this one would have shipped a wrong fix.
- *(evidence: `483bb9dd`; `games_from_cfbd_when_engine_schedule_empty` docstring)*

## 2026-08-16 — FORBIDDEN: shipping a check whose FAILURE MESSAGE does not carry the evidence for the failure

`scripts/ui_layout_probe.py` failed one run with exactly this, and nothing else:

    tab click identity

That is a tab name. Not the error, not the panel state, not the card height —
the check computed all three and the summary line threw them away. Diagnosing it
later cost three falsified hypotheses (a deferred handler, missing card ids, a
focus-triggered refresh), a 10-run scripted reproduction that came back 10/10
clean, and it is STILL unexplained. The artifact that held the detail was
overwritten by the re-run that went green.

An intermittent whose message carries no evidence has a predictable outcome: the
next person re-runs until it passes, because that is the only move available to
them. The check then trains people to ignore it, which is worse than not having
the check.

**How to apply.**
- A failure message must contain what the check MEASURED, not just which subject
  failed. If the code computed `activePanels` and `cardHeight` to make the
  decision, both belong in the message — the decision is not reproducible from
  the subject's name alone.
- **Before re-running a failing job, preserve its artifact under a different
  name.** A green re-run that overwrites the red one destroys the only copy of
  the evidence. Cost this exact investigation.
- When an intermittent cannot be reproduced, say so and fix the OBSERVABILITY
  rather than shipping a speculative fix and calling it closed. "Three
  hypotheses falsified, cause unknown, evidence now captured" is an honest
  result; "hardened against a race" without a reproduction is a guess wearing a
  changelog entry.
- Same family as [[feedback-instrument-blindness]]: a reading is evidence only
  once you know what it would say when things are wrong.


## 2026-08-16 - FORBIDDEN: a deploy-content check must return THREE verdicts, not pass/fail. "Nothing shipped" is not "shipped wrong".

Armed a watcher for a combined worker deploy and gave it a bare `all(v > 0)`
check across five markers. At 20:25:21Z it fired against `2efe76b1` -- another
lane's props-snapshot fix -- with:

    *** THE THREE FILES DID NOT TRAVEL TOGETHER. Expect cards_error / blank board. ***

**All five markers were 0, which means that deploy carried NONE of my work.**
The board was healthy throughout (`cards_present 70`, `cards_error None`). The
alarm was false, and it was aimed at an innocent lane's deploy.

The real risk is narrow and asymmetric: `pipeline/layer2_shortlist.py` (the
CALLER) shipping WITHOUT `layer2_board.py` (the CALLEE), because the caller
passes `openings=` to a signature that lacks it. Every other combination is
safe -- nothing shipped is self-consistent old code, and callee-without-caller
is inert.

**The rule:** when a check spans files with a dependency DIRECTION, encode the
direction. Verdicts here are ABSENT / PARTIAL_INERT / PARTIAL_DANGEROUS /
COMPLETE, and only one of the four is an alarm. A binary check over a
directional dependency maps three states onto "broken" and cries wolf on two of
them.

**And the meta-rule, second instance in one session:** this is the same shape as
the gate watcher that read `[UNKNOWN] HTTP 502` as CLEAR -- an instrument
mapping an unknown or benign state onto the wrong branch. Both were MY
instruments, written quickly at the end of a long task, and both would have
produced a confident wrong statement. **Falsify a new watcher against a known
input before trusting it**: the corrected version was run against three real
SHAs and returns ABSENT / ABSENT / COMPLETE, which is what proves it
discriminates.

## 2026-08-16 — OVERTURNED: "my commits are safe once the guard passes and `git show --stat HEAD` looks right"

Four commits from one session — `61e2c21e`, `419cc238`, `bf643d72`, `ca80ec46` — each
committed cleanly through an isolated index, each verified at the time with
`git show --stat HEAD`, and each later **unreachable from any ref**. `git branch --contains`
returned nothing for all four. HEAD carried **0** occurrences of `_freeze_market_dirs` while
the working-tree file had 2, so the freeze fix existed only as an uncommitted modification.

`main` is rewritten under you on this tree. Twice in the same session a lane header written
to `lanes.md` was silently dropped between two appends, once leaving a checkpoint orphaned
under an unrelated CLOSED lane. Work was also twice swept into another session's commit, and
once a later commit restored an older `lanes.md` that removed it again.

**The rule: a local commit on this worktree is not durable. Only a pushed ref is.**
- After committing anything you care about, `git push origin <sha>:refs/heads/wip/<lane>`.
  An unreachable object survives only until gc.
- Verify the push **by content on the remote**, not by ancestry and not by the local commit:
  `git ls-tree origin/<branch> <dir>` and compare blob hashes against `git hash-object <file>`.
  (`git show <rev>:<path>` is mangled by Git Bash — a false "unknown revision" for a file that
  is present.)
- Before assuming your work is in `HEAD`, grep HEAD's copy for a marker from the change.
  `git log` showing your commit is not the same as HEAD containing it.

**Corollary already in the ledger, now with a fourth and fifth instance:** the commit-guard's
suggested `git restore --staged` list has twice OMITTED a path it flagged in the same message
(9 flagged / 8 listed, then 10 flagged / 8 listed). Re-verify `git diff --cached --stat` and
`--diff-filter=D --name-only` yourself after running it. Landmines cleared this session
included staged deletions of `book_shortlist.py`, `test_layer2_bettable_books_and_labels.py`,
`test_prop_name_accent_fold.py` and `test_layer2_cross_file_compat.py` — all present on disk
and in HEAD — plus pure reverts of `prop_projections.py`, `layer2_board.py` and
`pipeline/layer2_shortlist.py`.

## 2026-08-16 — FORBIDDEN: never let an UNATTENDED session fire a deploy, and do not rely on prose to stop it

This session was launched by the `alt-line-shortlist-watch` scheduled task, whose prompt ends
"Do not deploy, roll back, or change any source file." It went on to open a lane, edit
`scripts/refresh_mlb_oddsapi.py` and commit — correctly, under live user direction — and was
then asked to deploy. It stopped at the deploy.

`state.md` already records `wnba-win-prob-counter-read` doing exactly this at 01:0x-01:2xZ the
same day: an unattended task told not to deploy committed a 339-line module, claimed three
services and fired deploys. The stated remedy is structural — no `RENDER_API_KEY` in the run
environment, **or a claim tool that refuses an unattended holder**. Neither exists:
`RENDER_API_KEY` is readable and `deploy_claim.py acquire` would have granted both claims.

Secondary discovery, and it is the tell: **`send_message` is unavailable in unattended
sessions**, in both directions. So the one session that most needs to coordinate before a
deploy is the one that structurally cannot. If a run cannot message its peers, it must not
take an action that requires coordinating with them.


## 2026-08-16 - FORBIDDEN: never split one change across separately-deployed files and rely on TELLING the deployer. A message is not a guard.

Cost a production incident at 20:34Z. `pipeline/layer2_shortlist.py`,
`layer2_board.py` and `opportunity_signals.py` deploy as separate blobs onto a
long-lived worker, so **there is no instant at which they are guaranteed to be
the same vintage.** Deploy `c324447d` carried the caller alone:

    layer2_rows_to_board_cards(rows, openings=...)  ->  TypeError
    -> caught by try/except -> cards = []
    -> layer2_is_primary=True, legacy_candidate_count=0  ->  BLANK BOARD

announced only by a `cards_error` string nobody reads. I had warned the
deploying session TWICE, in prose, with the exact file list. It still happened,
and it was **my design that made it possible**, not their process.

**The rule:** if a caller gains a parameter its callee may not have yet, the
CALLER probes — `inspect.signature`, not `except TypeError` (a bare retry cannot
tell "no such parameter" from a real TypeError raised inside the function, and
silently drops data on a genuine bug). Degrade to the reduced feature and SAY SO
in the payload. Never to nothing.

Two things this exposed that were worse than the headline:
- The `blended_score` coupling one level down was **worse than the cards one** —
  an unguarded TypeError there escapes `build_layer2_rows` and loses rows AND
  cards, where the cards path at least had a `try/except`.
- The live-join imports **shared one `try` with game state, projections and the
  margin model**, so a rollback of `board_enrichment.py` would have taken all
  four down. A missing live tier must cost the live tier.

## 2026-08-16 - FORBIDDEN: never record a detector's zero as a pass when the data gave it no chance to fire.

Shipped steam detection and measured **0 flagged**. That is NOT evidence it
works: only **4 rows** carried a price delta at all, against a +/-15-point
threshold inside a 3-hour window. The honest status is **UNTESTED IN
PRODUCTION**, and it stays that way until a row actually crosses.

Same shape as the standing rule "absence in a window isn't absence", but the
failure here is subtler: a zero from a working detector and a zero from a
detector that never ran are **identical readings**, and the deploy would have
been written up as "steam is back" on the strength of it.

**The rule:** before recording a detector's null result, state its DENOMINATOR
and its threshold. "0 steam from 4 eligible rows at +/-15 points" is a
measurement; "0 steam" is a guess wearing a number.

## 2026-08-16 - the third instance of the same instrumentation gap, in the file where I fixed the second.

`no_bettable_book` was computed and never published because `per_sport_stats` is
an explicit key list; I fixed it at 19:0xZ. Two hours later I shipped movement
and `openings_loaded` is **unpublished in exactly the same way, in the same
file** -- so "movement is thin" cannot be attributed between a sparse ledger and
a key that does not join. I inferred 31% from `movement_state` counts instead of
reading it.

`#397`'s rule (add the counter in the same commit as the rule) is necessary and
**not sufficient**. The counter must reach every place the payload is
ASSEMBLED, which on this path is three: the producer's return, the per-sport
stats dict, and the endpoint's key list. **Knowing the rule did not stop me
reproducing the defect within two hours.** Check the assembly sites, not the
commit.

## 2026-08-16 — FORBIDDEN: curating a deploy branch BY FILE without checking the call boundary you just cut

I cut `c324447d` by picking individual files from `main` onto the live SHA — the
right technique, applied without the check it requires. It took main's
`pipeline/layer2_shortlist.py` (the CALLER) and kept live's
`syndicate/features/shared/layer2_board.py` (the CALLEE):

    layer2_shortlist.py:241  build_layer2_rows(grid, openings=openings_index)
    layer2_board.py:824      def build_layer2_rows(grid)          <- no openings

**A file-level diff cannot see this.** I verified content by blob, ancestry
(`merge-base --is-ancestor`), absence of `render.yaml`, and that the delta was
exactly my intended files. Every one of those passed. The defect lives in the
SIGNATURE ACROSS THE BOUNDARY, which is invisible to all of them.

**What made it dangerous was the error handling, not the error.** The per-sport
`except Exception` at `layer2_shortlist.py:320` catches the `TypeError` and
records it as `{"error": ...}` in `per_sport_stats`. So the worker did not crash,
did not restart, and emitted no traceback — it just produced ZERO layer2 rows for
EVERY sport. A caught exception is not a safe failure when the catch is what
hides it. Exposure ~17 min (20:33:23Z -> 20:50:14Z), closed by another session's
`a9e5d3d6`, not by me.

**THE RULE.** When a curated branch splits a directory that other modules import
— `syndicate/features/shared/` above all — check BOTH directions before pushing:
- FORWARD: every module the new files import exists on the target.
- REVERSE: no public name present on the target is removed/renamed in the new
  files, and every call site's kwargs are accepted by the callee you are landing.
I ran both on the web deploy afterwards and it was clean. Two greps. That is the
whole cost.

**Corollary, from the same incident:** a new signature with a DEFAULT
(`openings: ... | None = None`) is backward-compatible, so the CALLEE is the safe
half to ship first. `a21b63db` ("the caller must survive a callee one deploy
behind") is the same lesson from the other side. Ship callee-first, caller-second.

## 2026-08-16 — FORBIDDEN: computing a RATE or a COUNT from `scripts/render_logs.py`

I nearly filed a false regression against my own `#441` fix. One `NFL_PBP` line
appeared in 14 minutes against a 60s throttle, which reads as "evaluated once,
still starved". It was the instrument. Measured coverage for REQUESTED windows:

| requested | actually covered | matches |
|---|---|---|
| 3 min | **0.23 s** | 8 |
| 3 min | 2m12s | 6 |
| 3 min | **nothing** | 0 |

It caps at ~2 pages and returns an arbitrary slice, so there is no denominator.
**Presence is evidence; absence and frequency are not.** What actually proved the
fix was the ORDER of two lines inside ONE covered tick — `RECONCILIATION_AUTORUN_GATED`
then `NFL_PBP_FETCH_SKIPPED`, 63 ms apart. Read ordering within a covered window,
never counts across one.


## 2026-08-16 - FORBIDDEN: never join a CHANGE metric on a key that contains the changing fields. The metric becomes conditioned on the absence of what it measures.

Shipped movement detection joined on `clv_opening_ledger._opening_key`, which
includes `line` and `bookmaker`. That key is CORRECT for settlement -- it must
not collapse home -1.5 with home -2.5, nor two books' prices. It is fatal for
movement, because **movement IS the detection of line and book change**: a row
could only match its own opening if it had not moved.

MEASURED, two served artifacts 20 minutes apart:

    stable key (event·market·player·segment·side) matched   20
    full key   (+ line + bookmaker)               matched   14
       of those 20: line changed 6, book changed 5, either 7

A third of matchable rows dropped, and they were precisely the rows with
something to report.

**The second-order damage was worse than the coverage loss.** Steam read 0 and I
recorded it as "unverified, the data gave it no chance to fire". True, but the
REASON was structural: a sharp move usually arrives WITH a line move or a
best-book switch -- the exact conditions that broke the key -- so the moves large
enough to be steam were the ones most reliably erased. **A detector can be
silenced by the join that feeds it, and the silence looks identical to a quiet
market.**

**The rule:** when building a delta/change/movement metric, ask what the join
key does when the measured quantity changes. If the key moves with it, the
metric reports only the population that did not change. Key on the STABLE
identity of the thing, and read the changing fields off the record.

**How it was found, which generalises:** a number went the WRONG WAY against a
stated prediction (coverage 31% -> 29% when I had predicted a rise), and I
chased it instead of explaining it away as noise. The prediction being wrong was
the entire finding.

## 2026-08-16 - a blob hash written into a ledger is a SNAPSHOT, not a lease.

Recorded a pending ridealong naming exact blob hashes so the next deployer could
not get it wrong. Within the hour `08de8c08` moved two of those blobs, and the
ledger entry -- written precisely to be unambiguous -- would have shipped the
compat guard WITHOUT the movement fix that makes it worth having.

Superseded the entry rather than editing it, so the stale one stays readable and
nobody wonders which was current, and the new one instructs the reader to
**re-read the blobs before cutting rather than trusting the numbers printed in
it**.

**The rule:** in a repo where files move several times an evening, a ledger may
record a hash as EVIDENCE of what was true, but must never present one as an
INSTRUCTION to be followed later without re-reading. Name the branch and the
files; let the reader resolve the hashes at cut time.

## 2026-08-16 — ASK-ANSWER-SUBSTANCE CHECKPOINT 2: five beliefs overturned

### REFUTED: "sorting the pool fixed the negative-edge problem"

`_market_summary_schema` carried a note from 2026-08-03 — the summary "returned
4 negative-edge rows with the only positive one (+16.9%) ranked LAST" — and the
fix was to SORT. It shipped again on 2026-08-16: three of five published
"opportunities" carried `model_edge_pct` of -1.83, -4.87, -8.20.

**Sorting orders a pool; it does not decline to publish one.** Necessary, never
sufficient. **General form: a fix aimed at the ORDER of bad output does not stop
the output, and the note it leaves behind reads like a closed case.** When a
past note says "fixed by ranking", check whether anything filters.

### REFUTED: "mirroring the ranker makes eligibility safe"

`_has_positive_edge` was deliberately written to mirror `_board_rank_key` — one
term, model edge if present else EV — and the docstring justified it as "so
ordering and eligibility cannot disagree". **That symmetry is what let a bad row
through**: `Pittsburgh Pirates` published at model edge **+9.18%** with EV
**-2.18%**.

**Ranking needs ONE number to sort on. Eligibility is a VETO, and a veto should
hear every term that can object.** Two different jobs; sharing one rule was the
defect. The careful-looking choice was the wrong one.

### REFUTED: "`quote_seen_age_seconds` is how stale the quote is"

It is stamped at ARTIFACT BUILD time and **does not tick**. Three reads 45s apart
returned byte-identical values while `written_at` sat 3 minutes back.
**Corollary that bit twice: a threshold calibrated against a frozen quantity
becomes meaningless the moment the quantity starts moving.** Correcting the age
made the 15-minute threshold fire on **70 of 70** rows, because the minimum real
age on the board is 27 minutes — an accurate warning carrying no information,
strictly worse than the inaccurate one it replaced.

**When you correct a quantity, re-check every threshold calibrated against it in
the SAME change.** Shipping the correction alone is a regression wearing a fix.

### REFUTED: "a generator that reads correctly on the rows I checked is correct"

`_reason_sentences` asserted "which is why it lands on the under" without ever
comparing the two numbers in that sentence. Served: *"projects 1.396 batter hits
against a line of 0.5, which is why it lands on the under."*

**The sibling row on the same board read perfectly** (0.256 against 0.5, under).
The template only breaks when the projection falls on the FAR side of the line,
so **half the output vindicates it**. A generator that is right half the time by
construction survives any eyeball review of a handful of rows — it survived mine,
and I wrote it that morning. **Test the PREDICATE over the whole population, not
the rendering of a few rows.**

### REFUTED (my own hypothesis, same session): "the sim-vs-side mismatch is a
### live full-game-projection-vs-remaining-line artifact"

Plausible, stated as "likely", and **wrong as the sole cause**: the disagreement
appears on **pregame** rows too (`full` 0/1, `model_mean` 0/2, `rbi_1prus` 1/2
agree/disagree with `is_live = False`), across four `basis` values.

**What it changed in practice:** I weakened my own published wording from "the
sim and this side disagree" to "does NOT support the {side}" — the first asserts
the two numbers are comparable, which the pregame rows say I cannot promise.
**Claim the arithmetic you can check, not the explanation you find convincing.**

### Instrument note, not a belief: the Browser pane screenshot

`computer{action:screenshot}` fails with a 5s timeout whenever the Browser pane
is not DISPLAYED on the user's screen — the page composites no frames. This is
not transient and retrying is waste; 4 attempts across the session, 0 successes.
`javascript_tool` + `read_page` work fine and are the fallback for proving what
a page renders.

## 2026-08-16 — ASK-ANSWER-SUBSTANCE CHECKPOINT 3: two more

### REFUTED: "a metric that moved right after my deploys is my regression"

`warn:edge_without_market_probability` went **0 → 25** between a control taken
before this lane's deploys and a run taken after six of them. The obvious read —
"I broke something" — was wrong.

`git diff <control-era-SHA> <live-SHA>` on the file showed the code path the
harness actually reads (`structured_response.top_opportunities` ← the board
path's `edge` and `market_probability`) was **untouched by all six deploys**.
The input had changed: 4 of 10 edge-bearing board rows now carry a
`model_edge_pct` that cannot be derived from their own projection probabilities
by either the direct difference or the complement.

**The rule: when a metric moves across your change, diff the code path the
metric actually reads before attributing it — to yourself OR to anyone else.**
Both directions of misattribution are expensive. Claiming a regression you did
not cause sends the next session hunting in the wrong file; claiming innocence
you have not checked is worse. The check is one `git diff` scoped to the path,
and it takes a minute.

Corollary that made this diagnosable at all: `_board_row_probabilities` returns
`None` rather than publishing a probability it cannot reconcile against the
row's own stated edge. **The warning was a guard reporting upstream data, not a
defect.** A guard that refuses loudly turns someone else's bad data into your
visible signal — which is the behaviour you want, and it means "my warning count
went up" is not the same claim as "my code got worse".

### FOUND: a cited artifact that is not in git is not evidence

`state.md` and `deploys.md` rows in this lane named
`reports/ask_regression/*.json` as the evidence for their measurements. **Those
files were UNTRACKED** — 15 of them under `??` in `git status`, including both
files my own rows cite, and including one cited by a `state.md` line written by
a different session on 2026-08-15.

The ledger's whole premise is that a claim is checkable later by someone who was
not here. A path that resolves only on one dev box fails that, silently, and it
fails at exactly the moment it matters: when the box is gone or the file has
been overwritten by the next run of the same script.

**Rule: if a ledger row names an artifact path as its evidence, commit the
artifact in the same push as the row — or write the numbers inline and say the
file is local-only.** Do not name a path you have not made durable. Fixed for
the two rows I wrote; the other 13 are pre-existing and flagged in the log.

## 2026-08-16 - FORBIDDEN: a loose join key makes a row VISIBLE. It does not make the row's values COMPARABLE. Those are two decisions and I made only one.

`#446` correctly dropped `line` and `bookmaker` from the movement join key,
because keying a change metric on the changing fields means only unmoved rows can
match. Coverage went **31% -> 96%** and the diagnosis was right.

But I then differenced PRICES across the rows the loose key had newly matched.
Measured on the first post-deploy artifact (22:20:31Z): **19 of 23 tracked rows
had a different opening line**, so their "movement" was the gap between two
different bets --

    Under totals    line  7.0   opening 11.0   "+242"
    Rockies spreads line -1.5   opening  +1.0  "+226"  -> FIRED STEAM

**The first steam this board ever produced was a false positive, and it was live
for ~15 minutes.** `_opening_key`'s docstring had already said "home -1.5 and
home -2.5 are different markets"; I read it as an argument about settlement and
did not notice it constrained me.

**The rule:** widening a join to see more rows and comparing values on those rows
are separate decisions. After loosening a key, ask of every derived quantity:
*is this still comparing like with like?* Here the answer was yes for the LINE
delta and no for the PRICE delta.

**And the fix's shape matters:** when the line moved, no `movement_price_delta`
is emitted **at all** rather than a value with a caveat in a neighbouring key.
The score and the steam detector both read that field; a caveat stops neither.

## 2026-08-16 - a test I wrote can encode the belief that production later disproves, and then it defends the bug.

Two tests written at 21:4xZ asserted a -27 point price delta across a line that
moved -1.5 -> -2.5, and a steam flag on the strength of it. Both passed. Both
were **wrong in exactly the way production proved an hour later** -- that delta
compares different bets.

When the gate landed, those two tests failed. The instinct a failing test creates
is "the change broke something"; here the change had **fixed** something and the
tests were the residue of the wrong belief.

**The rule:** when a fix makes your own tests fail, check whether the test
encodes an assumption the fix is correcting before you touch either. Rewrite the
test and say WHY in its docstring, so the next reader sees the fixture changed
because reality did -- not because it was inconvenient.

## 2026-08-16 — SCOPE NOTE on "blob-staging needs `--path`": true in general, WRONG for this repo

`dea23cc8` records that `git hash-object -w <file>` skips the clean filter unless
given `--path`, so blob-staging can commit un-normalised content. Correct as a
git fact. Applied to this repo it would cause the damage it warns about.

Measured 2026-08-16 against `origin/main`: **this repo stores CRLF throughout** —
`app.py`, `scripts/migration_gate.py`, `tests/test_archives.py`, and
`scripts/ui_layout_probe.py` at `f55b8e7c` before anyone touched it (1011/1011
CRLF). `.gitattributes` scopes `eol=lf` to `.claude/hooks/*` **only**, and says in
its own comment: *"this repo has no line-ending policy and setting one repo-wide
would rewrite far more than this change warrants."*

A day of blob-staged commits without `--path` therefore produced blobs
**consistent with every other file in the tree**, and `git status` reports them
clean. Adding `--path` would have normalised those files to LF — leaving them the
only LF files in a CRLF repo, and turning every subsequent diff into a whole-file
rewrite.

**How to apply.**
- Use `--path` where a repo HAS a normalisation policy. Check `.gitattributes`
  and the stored line endings of a file you did not touch before deciding —
  `git show origin/main:<some-other-file> | grep -c $'\r'` answers it in one line.
- The general rule and the local convention can disagree. A learning that says
  "always X" needs its scope measured before it is applied to a tree it was not
  derived from — this is [[feedback-rederive-load-bearing-cross-lane-numbers]]
  applied to a RULE rather than a number.
- Do not "fix" the existing files to LF on the strength of the general rule. That
  is a repo-wide rewrite nobody asked for, and `.gitattributes` already records
  the deliberate decision not to have a policy.


## 2026-08-16 - FORBIDDEN: a verifier that cannot FAIL cannot PASS. State the denominator every assertion needs, or it will report an empty population as success.

Third instrument of mine in one evening to map a benign state onto the wrong
branch, and this one is the worst because it produced a confident PASS on a
question that had not been asked.

Verifying the line gate, the harness printed:

    tracked 2 · moved-line 0
    PRICE DELTA LEAKED ACROSS A MOVED LINE : 0   (was 19 -- must be 0)
    VERDICT: PASS

**There were ZERO moved-line rows.** `PASS if not leaked and not bad_steam` is
trivially true on an empty population. The board had shrunk 63 -> 31 -> 12 on
end-of-night slate attrition, so the check ran against nothing and reported that
the gate worked. It meant the gate was never exercised.

I had written the governing rule into this same file FOUR HOURS EARLIER --
"never record a detector's zero as a pass when the data gave it no chance to
fire" -- and then wrote a verifier that did exactly that. **Knowing the rule did
not stop me; the harness had no structural reason to obey it.**

**The rule, structurally:** every assertion in a verifier declares the minimum
denominator it needs. Below that the verdict is INCONCLUSIVE and names what it
is waiting for. Pick the threshold from the population the DEFECT was observed
in (here 19 moved-line rows of 23 tracked -> require 3), so a pass cannot rest
on one lucky row.

**And falsify all three verdicts before trusting it**, not just the one you
want. The corrected harness was run against tonight's real board
(-> INCONCLUSIVE), a synthetic clean population (-> PASS) and the same
population with one leaked delta (-> FAIL). The FAIL case is the one that
proves the other two mean anything.

The other two instruments this evening, for the pattern: `[UNKNOWN] HTTP 502`
read as a CLEAR deploy gate, and a binary content check that shouted
"blank board" at a deploy carrying none of my files. All three were written
quickly, at the end of a long task, to check something I expected to be fine.

## 2026-08-16 — ASK-ANSWER-SUBSTANCE CHECKPOINT 4: fixing a fix, and two bad inferences

### REFUTED: "the guard I added to stop a false claim is therefore correct"

The defect was false causation — *"projects 1.396 batter hits against a line of
0.5, **which is why it lands on the under**"*. The fix I shipped replaced it with
*"which does **NOT support** the under"*, and that is **the same category error
pointing the other way.**

`projected` is a **MEAN**. What picks a side is **`P(X > line)`**. On a low-line
count prop those diverge routinely and legitimately: a mean of 0.214 runs still
implies `P(>=1) ~ 19%`, which beats a market implying 15%, so `over 0.5` is a
good bet with the mean below the line. My "correction" called that unsupported.

**The general form: when you fix a claim, check that its REPLACEMENT is licensed
by the same evidence.** Negating an unjustified assertion does not produce a
justified one — both directions need the statistic to be the right statistic.
The fix shipped inside four hours of the original and was live for 53 minutes.

Corollary, and it is the durable half: **the comparison a template makes is part
of the template's contract.** This generator was modelled on the MLB game lens,
where `projection sits at 7.42 against 5.0` is sound because a game total's mean
IS the right statistic against a nearby line. Carrying that sentence across to a
0.5-line count prop carried the arithmetic and dropped the precondition.

### REFUTED (mine, same session): "these two findings are unrelated because no row fails both"

I measured `overlap = 0` between the projected-vs-side finding and the
edge-vs-probability finding and read it as evidence against a shared cause. It
was a **population artifact**: only **2 of the 10** projected-vs-side rows carry
`model_edge_pct` at all, so they were barely eligible to fail the second test.

**Before reading an empty intersection as independence, check that the two
populations could have intersected.** An overlap of zero between a set of 10 and
a set of 8 drawn from different eligibility pools says nothing. Same family as
the standing rule that absence in a window is not absence.

### CONFIRMED, and worth keeping: a guard that refuses loudly is how you find someone else's bug

`_board_row_probabilities` returns `None` rather than publishing a probability it
cannot reconcile against the row's own stated edge. That refusal is what surfaced
the `edge_vs_market_pct` pairing defect — the harness warning
`edge_without_market_probability` went 0 → 25, and chasing it landed on
`live_gameline_join.py:643` with 7/7 separation and exact arithmetic.

**A guard that degrades silently would have published a plausible wrong number
and nobody would ever have looked.** When adding a reconciliation check, make its
failure VISIBLE (a null, a counter, a warning) rather than falling back to
whichever input looks reasonable.
### 2026-08-16 — AN ISOLATED-INDEX COMMIT IS PROTECTED FROM THE SHARED INDEX AND NOT FROM A HEAD MOVE. Mine was orphaned within minutes, and so was another lane's

**The documented recipe protects your commit's CONTENT from other sessions'
staged junk. It does nothing to protect its REACHABILITY.** I committed
`87ffffd2` through `GIT_INDEX_FILE` with every guard this file prescribes —
2 files, 0 deletions, asserted in the same shell, shared index repaired
afterwards. Minutes later `git merge-base --is-ancestor 87ffffd2 HEAD` returned
FALSE: another session had moved local `main` to `1508c463`, which does not
descend from it (reflog `HEAD@{0}`, empty message — a reset or checkout, not a
commit). No ref reached it, `git branch -a --contains` was empty, and it was not
on `origin/main`. **`05f7d8fb`, another lane's wnba commit, was orphaned by the
same move** — so this is a worktree-wide event, not one session's mistake.

- **The rule going forward:**
  1. **A commit is not durable until it is REACHABLE. Assert it:**
     `git merge-base --is-ancestor <sha> HEAD`. Presence in `git log` right
     after committing proves nothing five minutes later, and presence in the
     REFLOG is not reachability at all — a dangling commit still reflogs.
  2. **Re-assert at checkpoint**, not only at commit time. This session's commit
     was made and orphaned inside one turn boundary.
  3. **Recovery is cheap IF the blobs are checked first.** `git rev-parse
     <sha>:<path>` vs `git hash-object <worktree path>` — confirm byte-identity,
     then re-commit onto the new HEAD. Re-committing without that check would
     silently ship whatever another session had left in the worktree.
  4. **Do not rescue another lane's orphan.** Record it and notify; their
     content may have been deliberately superseded (`origin/main` here carried a
     DIFFERENT wnba commit, `e9fdcf98`).
  5. **`git status` says nothing about this.** It reported a clean tree for
     files that had just fallen out of history.

### 2026-08-16 — A COLLISION CHECK IS A READING WITH A TIMESTAMP, NOT A FACT. A lane was re-opened between my check and my edit

At `/lane open` the header for `mlb-live-gameline-distributions` read
`CLOSED-VERIFIED 2026-08-16 22:2xZ`, so I recorded its claim on
`vendor/.../flask_frontend.py` as released and wrote that into my lane block.
Between that read and the edit, the holding session **re-opened it** (`12bba949`
— *"the line-gate PASS was a pass on an empty population; a verifier that cannot
fail cannot pass"*). `lane-guard` blocked the edit and **the guard was right**.

- **The rule going forward:** re-run the collision check **immediately before
  the edit**, not only at lane open. A CLOSED lane can re-open — closure is
  itself a claim that can be withdrawn, and withdrawal is exactly what a failed
  verification produces. Corollary: when a guard contradicts your own recorded
  check, **the guard is reading now and you read earlier** — believe it and
  re-read before arguing.
- Same session, same mechanism: my first `lanes.md` lane block was **overwritten
  wholesale** by a parallel session's write and had to be re-appended.

### 2026-08-16 — `commit-guard`'s suggested fix list was INCOMPLETE on all THREE occurrences in one session

Already recorded as a hazard; this is the evidence that it is the norm, not the
exception. Omitted: `.syndicate/scheduled_task_ncaaf_445.md` (0/-58) on the
first block, and `.syndicate/deploys.md` (0/-66) on the second.

- **The rule going forward:** after running the guard's `git restore --staged`
  line, **re-print the WHOLE index and audit every remaining path yourself** —
  for each, is it on disk, and is it in HEAD? `absent on disk + in HEAD` is a
  legitimate deletion (leave it — `scheduled_task_ncaaf_445.md` was one);
  `present on disk + in HEAD + staged as deleting lines` is a stale-index revert
  (disarm it). Do not treat the guard's list as the fix.

- **ADDENDUM 2026-08-16, same session:** it happened a SECOND time — the
  re-commit `af3017e6` was orphaned by a hard reset of local `main` to
  `origin/main` minutes later. **Re-committing onto `main` is therefore not the
  fix.** The fix is a REF: `git branch lane/<slug> <sha>` makes the commit
  reachable, immune to any `main` move, and safe from gc, at zero cost to any
  other session. **In this worktree, do that immediately after every commit,
  before doing anything else** — and treat a commit as durable only once it is
  on `origin/main`.

## 2026-08-16 — OVERRIDE, LOGGED: an unattended session was authorised by the user to fire this deploy

The FORBIDDEN entry above ("never let an UNATTENDED session fire a deploy") was
raised to the user twice with its reasoning — the same-day `wnba-win-prob-counter-read`
incident, the absent structural control, and the tell that `send_message` is
unavailable in unattended runs so the session that most needs to coordinate cannot.
The user chose it deliberately, in these words: **"fire it"**, after being offered
the alternative of running `.syndicate/handoff_deploy_freeze_reader_tree.md` from
their own attended window.

**Scope of the override:** deploy `_freeze_market_dirs` (blob `426bbd70`, on
`origin/main`) to refresh-worker and live-odds-worker. Nothing else.

**What the override does NOT suspend**, and these were kept:
- the in-flight job gate — both workers read HOLD (5 and 3 jobs, including
  `run_mlb_daily_sim_job.py`) at 22:15Z and the deploy waited rather than killing them;
- ROUTE ONE (warm-up deploy before target), one service at a time, `finishedAt`
  observed between calls;
- verification by CONTENT, by blob, never by ancestry;
- rollback SHAs captured before firing.

**The rule is unchanged and still stands for the next run.** This entry records a
human decision on one deploy, not a precedent. The structural fix the earlier entry
asks for — no `RENDER_API_KEY` in an unattended run environment, or a
`deploy_claim.py` that refuses an unattended holder — is still not built, and until
it is, "the session judged it was fine" is the only thing standing between an
unattended run and three restarted services.

## 2026-08-16 — CORRECTION: the shared index CHURNS, it does not accumulate — and staged content is not the alarm

I recorded the shared index earlier the same day as a landmine "growing" on a
timer: 725 staged ledger deletions, then 1127 half an hour later, with the
inference that its blast radius increases the longer it sits.

Measured a third time minutes after that: **207 deletions across four DIFFERENT
files.** `deploys.md` and `lanes.md` had left the staged set entirely, and local
`HEAD` had moved twice in between. The staged set is simply whatever the
currently-active sessions are holding at that instant. The 725 -> 1127 reading
was two samples of a churning quantity, and I turned it into a trend.

**How to apply.**
- **Two samples of a quantity other writers control is not a trend.** Same error
  as [[feedback-rate-not-count]] wearing different clothes: I had no denominator
  and no idea of the sampling process, and still described a direction.
- **A `git reset HEAD -- <paths>` on a shared index is point-in-time, not a
  fix.** The state can return within minutes. The durable fix is other sessions
  committing through isolated indexes — see
  [[project-shared-tree-commit-recipes]] — not repeated disarms.
- **Staged content in a shared index is normal; staged DELETIONS are the
  signal.** Immediately after the disarm the index held another session's
  `game_shape.py` (+356) and `test_game_shape.py` (+332), purely additive — a
  shared index in correct use. An alarm that fires on "something is staged"
  would fire constantly and be ignored. Gate on `git diff --cached --numstat |
  awk '$2>0'`, which is empty in the healthy case.

### 2026-08-16 — A PLAN'S FIELD LIST WRITTEN FROM GREPS WAS WRONG FOR ALL FOUR SPORTS. Greps find NAMES; only the payload has the data

`plan_2026-08-16_state_conditional_learning.md` promised, per sport, a concrete
field list. Measured against real artifacts, **it was wrong every single time,
and wrong in a DIFFERENT direction each time** — which is why "check the plan
against reality" cannot be a one-off:

| sport | the plan said | measured |
|---|---|---|
| MLB | build a state vector | it **already existed** in full (`LiveSituation`) and was discarded — serialisation, not derivation |
| WNBA | "needs a possession count" | possessions are **underivable** — no FGA/TOV/OREB/FTA anywhere |
| NFL | down/distance/field position/`pace_secs_play` | **none captured**; `situation` sits in the fetched payload unread, and `pace_features.py` is SEASON-level, not live |
| soccer | minute/score/red cards | far richer (shots, SOT, corners) **and it embeds the model's own projection** |

- **The rule going forward:** before designing an extractor, **open a populated
  artifact and read it.** The grep that produced each of those lists found a
  field NAME in a file somewhere in the tree — in a sim engine's internal state,
  a historical loader, a season-level feature builder — none of which is the
  live payload. A name in the repo is not a field on the record.
- Corollary that paid off four times: the measurement changes the DESIGN, not
  just the field list. MLB became a one-line serialisation, WNBA became an
  honest refusal, NFL became a capture fix, soccer became an exclusion problem.

### 2026-08-16 — STATE THAT EMBEDS THE MODEL'S OWN OUTPUT MAKES CONDITIONING CIRCULAR. Soccer is the only sport here that does it

`soccer/ingestion/espn_live_state.py`'s record carries a `projection` block
(`home_win_probability`, `projected_final_total`) and `goal_windows` inline,
alongside the real state. Folding those into a game-shape record would mean
scoring the model's error against a variable that CONTAINS the model.

- **The rule going forward:** a conditioning variable must be derivable from
  observable state ALONE. When a payload mixes state and prediction, split them
  explicitly and say so on the record. **The test for this is cheap and
  worth writing:** assert the model's field names are absent from the shape.
- No other sport's live_state carries its projection, so nothing else in the
  module guards it — a trap that exists in exactly one place is the kind that
  survives review.

### 2026-08-16 — A RESERVATION IS A READING WITH A TIMESTAMP. Three different kinds went stale in ONE session

Already recorded for lane claims. It happened in **three distinct systems**
within a few hours, which makes it a general property of this worktree, not a
lane-file quirk:

1. **Lane claim** — `mlb-live-gameline-distributions` read `CLOSED-VERIFIED` at
   lane open and was re-opened before my edit. `lane-guard` was right.
2. **Shared git index** — held revert-shaped entries against a HEAD that had
   moved; `commit-guard` blocked twice and its fix list was incomplete BOTH
   times.
3. **Todo IDs** — this session's plan reserved `#447`/`#448`; other sessions
   filed unrelated items under both before it was filed.

- **The rule going forward:** re-read the authority immediately before the
  action that depends on it — the claim before the edit, the index before the
  commit, the ID before filing. Never carry a reading across a turn boundary.

### 2026-08-16 — A DIRECTORY NAMED `pbp` CAN CONTAIN MODELS, NOT PLAY-BY-PLAY

`vendor/wnba_betting_repo/models/pbp/` holds `.joblib`/`.onnx` files
(`early_threes_gbr`, `first_basket_lr`, `tip_winner_lr`) — artefacts TRAINED
from pbp. A coverage census by path would have counted WNBA twice and, worse,
would have reported coverage for a sport on the strength of a filename.

- **The rule going forward:** a coverage census must open a file and check its
  SHAPE, not match its path. The same pass corrected "we have pbp for every
  sport" to **5 of 8** (`#454`) — and the three without it (soccer, NHL, NCAAB)
  are the same three modules that are weakest everywhere else, which is a
  finding in itself rather than a coincidence.

## 2026-08-16 — CHECKPOINT 6: the ledger's own tooling, and three instrument misreads

### FORBIDDEN: never `import` a hook module to reuse its parser

`lane-guard.py` runs `main()` at import. With stdin at EOF it calls `sys.exit()`,
which propagates out of `exec_module` and **kills the importing script with exit
code 0 and no output at all**. Two scripts died that way tonight and both looked
like "the parser returned nothing" — a silent wrong answer, not a crash.

**Copy the regexes, or shell out with `stdin=DEVNULL`.** More generally: a file
under `.claude/hooks/` is an executable with side effects, not a library.

### REFUTED: "my open-lane test is equivalent to the guard's"

I archived lanes using `— OPEN\b` (OPEN immediately after the first em-dash). The
guard uses `LANE_RE = ^###\s+(\S+)\s+—\s*([^—]*)` plus `OPEN_RE = \bOPEN\b` —
i.e. **OPEN anywhere in the first em-dash segment**. Mine is strictly narrower,
so a heading like `— RE-TAKEN … OPEN …` reads closed to me and open to the guard.

Archiving such a lane moves its body to `lanes_closed.md`, which the guard never
reads — **silently dropping that lane's file protection**. I checked the batch
afterwards and all six agreed, but that was luck, not design.
**When a hook decides something, reproduce ITS predicate exactly.**

### THE RULE THAT CAUGHT MY OWN BAD CLAIM: diff against the before-state, not against your intent

I told another lane a file "was silently unprotected". It was not — it was
already claimed by a different lane. What made the error visible was printing the
claimants **from a commit before any of my work** and comparing, rather than
reasoning about what my change touched. Reasoning said "I added the only claim";
measurement said there were two.

**For any claim of the form "X was broken and I fixed it", compute X's state at a
commit that predates you.** Cheap, and it is the difference between a fix and a
misattribution sent to another session.

### Instrument misreads, three in one session, all producing CONFIDENT WRONG ANSWERS

Same family as the standing rule that a null result is about the instrument until
proven otherwise:

1. **Git Bash mangles `rev:path`** — `git show origin/main:.syndicate/deploys.md`
   became `origin\main;...` and returned a false "row absent: 0".
2. **PowerShell `Select-String` is CASE-INSENSITIVE by default** — it matched the
   lowercase quotation of a heading inside my own withdrawal text and reported a
   deleted block as still present.
3. **Bash executes backticks inside double-quoted strings** — an inline Python
   check containing `` `Files:` `` had the backticks run as a command, and the
   containment test returned `False` for a string that was present.

**All three answered a question I did not ask, and all three looked plausible.**
Verify a surprising ledger result with a SECOND tool before acting on it; in this
session every one of the three was caught that way and none by re-reading the
output.
## 2026-08-17 — FORBIDDEN: deploying `main`'s TREE to a service that runs a curated deploy branch

Every one of the three services held commits `main` had never received —
live-odds-worker 21, web 52, refresh-worker 40. Deploying main's tree would have
reverted all of them, silently, in the name of "shipping the pending work".

**The tell is per-file, and it is cheap:** for each conflicted path compute
`live-only` and `main-only` line counts. **`main-only == 0` means production is
AHEAD there** and taking main is a revert. Measured tonight on
`refresh_nba_oddsapi_props.py`, `refresh_wnba_oddsapi_props.py` and
`test_win_prob_null_counter.py` — three files, on two separate services, where
the obvious move was the wrong one.

**THE RULE.** Converge with a real merge commit (two parents) cut on the
service's own live SHA. Resolve each conflict by MEASURING which side is ahead,
never by preferring a branch. Then verify on the merged tree BEFORE pushing:
the live-wins files lose 0 lines, no conflict markers survive, and `render.yaml`
is byte-identical to live.

**Use `git merge-tree --write-tree`, not `read-tree -m`.** `read-tree -m` is a
trivial merge: it flagged 12 paths where either side changed, including files
that needed CONTENT merging, and picking a side there would have dropped the
other side's work. `merge-tree` does real 3-way content merges and found 6 true
conflicts. It also needs no worktree, which matters here because `git worktree
add` fails outright on this repo.

**One apparent loss was a supersession, and checking cost two minutes:**
`wnba/cards.py` "lost" 7 lines that turned out to be an inline `american_price`
clamping to `[0.02, 0.98]`, which main deliberately replaced. Do not report a
diff as a regression before reading what the lines say.

## 2026-08-17 — FORBIDDEN: gating a deploy on "no jobs running" for a continuously-busy worker

live-odds-worker's idle window is **under 25 seconds** and appeared once in an
hour of polling. Waiting for `jobs == 0` there is waiting for a condition that
effectively never holds, and a 90s poll steps straight over it.

**Worse, the gate measures the wrong moment.** Render BUILDS first and stops the
service after (`build_started 21:13:49 -> build_ended 21:18:29 -> live 21:21:05`).
What dies is whatever runs at the STOP, ~5 minutes after the trigger — not what
preflight saw when you fired.

**THE RULE.** Gate on the EXPENSIVE job, not on all jobs. On refresh-worker that
is `run_mlb_daily_sim_job`: a killed odds refresh re-runs in minutes, a killed
MLB sim can run long with no ETA and the board depends on it. Gating on "no MLB
sim" caught a window in 35 seconds that "no jobs" would have waited for
indefinitely. And have the poller watch the BASE too — refresh-worker moved
`fdc72dd0 -> 94447830` mid-build, which silently invalidates a pushed branch.

## 2026-08-17 — CHECKPOINT 7: a contested file is a symptom, not a diagnosis

### REFUTED: "four contested files means four lanes disagree"

`scripts/check_lane_invariants.py` reported four files claimed by two OPEN lanes
each. Exactly **one** was a real disagreement:

- **one PHANTOM** — five paths claimed from prose indented under a `- Files:`
  line whose own text read "none claimed yet — this lane is diagnostic";
- **two from ONE duplicated block** — a 92-line region pasted verbatim into two
  unrelated lanes, each copy carrying its own `Files (exclusive to this lane)`;
- **one genuine** conflict between two lanes that both meant it.

**Read the Files block before adjudicating a claim.** Three of the four would
have been "resolved" by taking a file away from a lane that never asked for it,
and the duplication — the actual defect — would have survived untouched.

### REFUTED: "the duplication is the one block I found"

I reported a single duplicated block. A content scan for maximal runs of
identical consecutive lines found **three**: 92 lines cross-lane, and 57 and 42
lines duplicated *adjacently within a single lane* — invisible when reading,
because a lane body repeated back-to-back just looks long.

**When you find one copy-paste in a ledger, scan for all of them.** The scan is
ten lines and it found twice as much as reading did.

### THE CHECK THAT MAKES DELETING A LEDGER BODY SAFE

Before removing 191 lines: assert that **every deleted line still appears
elsewhere in the file**, line by line. Not a diff stat, not a heading count —
those pass while a body is silently truncated. It is the only check that
distinguishes de-duplication from data loss, and it is three lines of code.

Corollary, learned twice tonight: **locate the region BY CONTENT at edit time,
never by line numbers from an earlier read.** `lanes.md` moved four times in an
hour; a stale offset would have cut a different 92 lines and every count would
still have balanced.

### A STALE SNAPSHOT REPORTS STALE RESULTS, AND THE TELL IS THAT NOTHING MOVED

After deleting all three duplicated runs I re-ran the scanner and it reported all
three still present. The scanner had a hardcoded path to the dump taken *before*
the edit. The signature was that the numbers were **identical** to the previous
run — not similar, identical. A real re-measure after a change essentially never
reproduces the prior output exactly.

**Give every analysis script its input as an argument.** Hardcoding a path makes
it silently answer a question about the past. This is the third instrument
misread of the session, after Git Bash's `rev:path` mangling and PowerShell's
case-insensitive `Select-String`.

## 2026-08-17 00:5xZ — CORRECTION: the "silent revert" was a LAG, not a removal. I overstated it twice.

**What I claimed** (in `state.md`'s POISONED-lineage block, in commits
`d9088741` / `7623a233`, and to the user): `7c2b1a17` "reverted 10 lines of
`memory_observability.py` — the smaps-vs-cgroup RECONCILIATION guard — on the one
service that is OOM crash-looping, while `#449` was open."

**What is actually true, measured:**

    git diff --numstat 7c2b1a17 40c3c44b -- syndicate/features/shared/memory_observability.py
    -> +10  -49

It is a **refactor**, not a deletion. `7c2b1a17` carried the OLDER implementation
(`_process_rss_anon_bytes()`, reading `RssAnon` from `/proc/self/status`); main
had replaced it with cgroup-based accounting (`cgroup_anon_mb`). **`grep -c
reconciles_within_pct` returns 1 on BOTH trees.** The guard was never absent.

**The tell I nearly walked past:** a `SMAPS_ANON` line emitting
`reconciles_within_pct` at **00:48:32Z** — five minutes BEFORE my ship landed, so
emitted by `7c2b1a17` itself. If that SHA had truly lacked the field it could not
have printed it. I found this only because a follow-up query for the field's
VALUES came back empty and I chased the discrepancy instead of banking the
watcher's "1 line" count.

**Corrected severity.** The deployed service was LAGGING main's improved memory
instrumentation, which is worth fixing and was fixed by `7623a233`. It was not
"instrumentation removed during an incident". The stale-tree MECHANISM is real
and the `deletions vs the main parent == 0` assertion still stands — what was
wrong was my reading of WHAT the 239 lines contained. 229 of them were ledger;
the 10 code lines were one side of a refactor.

**The lesson, which is not the one I thought I was recording:** a `numstat`
deletion count tells you SIZE, never MEANING. I read `-10 code lines` and
supplied "a safety guard was removed" without opening the diff. Read the lines
before naming the damage — the same rule already written for the `wnba/cards.py`
`american_price` scare earlier this session, which I got right and then did not
apply an hour later.

## 2026-08-17 — CHECKPOINT 8: recommend only what you have traced

### FORBIDDEN: proposing a field rename without tracing every consumer first

I twice recommended renaming the live edge to `live_edge_vs_market_pct` "so the
pairing cannot be got wrong at the call site". Tracing consumers while writing
the patch: `layer2_board._model_edge_for` reads `edge_vs_market_pct` **directly**
and that value becomes the board's `model_edge_pct`. The rename would have made
the board price **live** rows off a **pregame** edge — worse than the defect it
was meant to fix, and I had sent it to another session twice.

**A rename is a contract change. Grep the field before proposing one, not before
implementing one** — by implementation time the advice has already been acted on.
The corrected fix adds a key and moves nothing, and a test now fails if the
rename returns.

Second-order: the file's own neighbourhood already contained the answer.
`layer2_board`, beside `_MODEL_EDGE_MAX_POINTS = 15.0`: *"The real fix is an
explicit `basis` on the projection… Until projections carry it, this bound is the
guard."* **The correct design was written in a comment months earlier and I
proposed something else without reading it.**

### The lane guard reads the LOCAL ledger, not the one you pushed to

I held the claim on `origin/main` and the guard still blocked the edit, because
the working tree's `.syndicate/lanes.md` was ~40 commits stale and still showed
the previous holder. **A claim is only enforced where the guard can see it.**

The fix is to sync those lines locally. The temptation — editing in a throwaway
worktree, where the hook cannot resolve the path to a claim — **is a bypass, not
a workaround**, and it would have worked silently. If you find yourself choosing
a location because the guard cannot see it, stop.

### RECURRENCE: chaining `git add`/`commit` picked up another session's work AGAIN

`project-shared-tree-commit-recipes` already records this. It happened anyway:
a chained `... && git add ... && git commit` ran with the **shell's** cwd (the
shared repo) rather than the worktree I had just written to, and produced a local
commit containing another session's `game_shape.py` (+906) and
`tests/test_game_shape.py` (+693).

Nothing reached `origin` only because the push was rejected as non-fast-forward —
**luck, not care**. Undone with `git reset --soft HEAD~1`, which restored their
files to the index exactly as they were.

**Every git write against a worktree must carry `git -C <worktree>`.** A bare
`git` in a chained command inherits the shell's directory, and the shell's
directory is the one place the files are not yours.

### 2026-08-16 — A PLAN'S FIELD LIST WRITTEN FROM GREPS WAS WRONG FOR ALL FOUR SPORTS. Greps find NAMES; only the payload has the data

`plan_2026-08-16_state_conditional_learning.md` promised, per sport, a concrete
field list. Measured against real artifacts, **it was wrong every single time,
and wrong in a DIFFERENT direction each time** — which is why "check the plan
against reality" cannot be a one-off:

| sport | the plan said | measured |
|---|---|---|
| MLB | build a state vector | it **already existed** in full (`LiveSituation`) and was discarded — serialisation, not derivation |
| WNBA | "needs a possession count" | possessions are **underivable** — no FGA/TOV/OREB/FTA anywhere |
| NFL | down/distance/field position/`pace_secs_play` | **none captured**; `situation` sits in the fetched payload unread, and `pace_features.py` is SEASON-level, not live |
| soccer | minute/score/red cards | far richer (shots, SOT, corners) **and it embeds the model's own projection** |

- **The rule going forward:** before designing an extractor, **open a populated
  artifact and read it.** The grep that produced each of those lists found a
  field NAME in a file somewhere in the tree — in a sim engine's internal state,
  a historical loader, a season-level feature builder — none of which is the
  live payload. A name in the repo is not a field on the record.
- Corollary that paid off four times: the measurement changes the DESIGN, not
  just the field list. MLB became a one-line serialisation, WNBA became an
  honest refusal, NFL became a capture fix, soccer became an exclusion problem.

### 2026-08-16 — STATE THAT EMBEDS THE MODEL'S OWN OUTPUT MAKES CONDITIONING CIRCULAR. Soccer is the only sport here that does it

`soccer/ingestion/espn_live_state.py`'s record carries a `projection` block
(`home_win_probability`, `projected_final_total`) and `goal_windows` inline,
alongside the real state. Folding those into a game-shape record would mean
scoring the model's error against a variable that CONTAINS the model.

- **The rule going forward:** a conditioning variable must be derivable from
  observable state ALONE. When a payload mixes state and prediction, split them
  explicitly and say so on the record. **The test for this is cheap and
  worth writing:** assert the model's field names are absent from the shape.
- No other sport's live_state carries its projection, so nothing else in the
  module guards it — a trap that exists in exactly one place is the kind that
  survives review.

### 2026-08-16 — A RESERVATION IS A READING WITH A TIMESTAMP. Three different kinds went stale in ONE session

Already recorded for lane claims. It happened in **three distinct systems**
within a few hours, which makes it a general property of this worktree, not a
lane-file quirk:

1. **Lane claim** — `mlb-live-gameline-distributions` read `CLOSED-VERIFIED` at
   lane open and was re-opened before my edit. `lane-guard` was right.
2. **Shared git index** — held revert-shaped entries against a HEAD that had
   moved; `commit-guard` blocked twice and its fix list was incomplete BOTH
   times.
3. **Todo IDs** — this session's plan reserved `#447`/`#448`; other sessions
   filed unrelated items under both before it was filed.

- **The rule going forward:** re-read the authority immediately before the
  action that depends on it — the claim before the edit, the index before the
  commit, the ID before filing. Never carry a reading across a turn boundary.

### 2026-08-16 — A DIRECTORY NAMED `pbp` CAN CONTAIN MODELS, NOT PLAY-BY-PLAY

`vendor/wnba_betting_repo/models/pbp/` holds `.joblib`/`.onnx` files
(`early_threes_gbr`, `first_basket_lr`, `tip_winner_lr`) — artefacts TRAINED
from pbp. A coverage census by path would have counted WNBA twice and, worse,
would have reported coverage for a sport on the strength of a filename.

- **The rule going forward:** a coverage census must open a file and check its
  SHAPE, not match its path. The same pass corrected "we have pbp for every
  sport" to **5 of 8** (`#454`) — and the three without it (soccer, NHL, NCAAB)
  are the same three modules that are weakest everywhere else, which is a
  finding in itself rather than a coincidence.

## 2026-08-17 — FORBIDDEN: deploying `main`'s TREE to a service that runs a curated deploy branch

Every one of the three services held commits `main` had never received —
live-odds-worker 21, web 52, refresh-worker 40. Deploying main's tree would have
reverted all of them, silently, in the name of "shipping the pending work".

**The tell is per-file, and it is cheap:** for each conflicted path compute
`live-only` and `main-only` line counts. **`main-only == 0` means production is
AHEAD there** and taking main is a revert. Measured tonight on
`refresh_nba_oddsapi_props.py`, `refresh_wnba_oddsapi_props.py` and
`test_win_prob_null_counter.py` — three files, on two separate services, where
the obvious move was the wrong one.

**THE RULE.** Converge with a real merge commit (two parents) cut on the
service's own live SHA. Resolve each conflict by MEASURING which side is ahead,
never by preferring a branch. Then verify on the merged tree BEFORE pushing:
the live-wins files lose 0 lines, no conflict markers survive, and `render.yaml`
is byte-identical to live.

**Use `git merge-tree --write-tree`, not `read-tree -m`.** `read-tree -m` is a
trivial merge: it flagged 12 paths where either side changed, including files
that needed CONTENT merging, and picking a side there would have dropped the
other side's work. `merge-tree` does real 3-way content merges and found 6 true
conflicts. It also needs no worktree, which matters here because `git worktree
add` fails outright on this repo.

**One apparent loss was a supersession, and checking cost two minutes:**
`wnba/cards.py` "lost" 7 lines that turned out to be an inline `american_price`
clamping to `[0.02, 0.98]`, which main deliberately replaced. Do not report a
diff as a regression before reading what the lines say.

## 2026-08-17 — FORBIDDEN: gating a deploy on "no jobs running" for a continuously-busy worker

live-odds-worker's idle window is **under 25 seconds** and appeared once in an
hour of polling. Waiting for `jobs == 0` there is waiting for a condition that
effectively never holds, and a 90s poll steps straight over it.

**Worse, the gate measures the wrong moment.** Render BUILDS first and stops the
service after (`build_started 21:13:49 -> build_ended 21:18:29 -> live 21:21:05`).
What dies is whatever runs at the STOP, ~5 minutes after the trigger — not what
preflight saw when you fired.

**THE RULE.** Gate on the EXPENSIVE job, not on all jobs. On refresh-worker that
is `run_mlb_daily_sim_job`: a killed odds refresh re-runs in minutes, a killed
MLB sim can run long with no ETA and the board depends on it. Gating on "no MLB
sim" caught a window in 35 seconds that "no jobs" would have waited for
indefinitely. And have the poller watch the BASE too — refresh-worker moved
`fdc72dd0 -> 94447830` mid-build, which silently invalidates a pushed branch.

## 2026-08-17 — FORBIDDEN: resolving the SAME symbolic ref in two git calls. A stale tree on a current parent is a fast-forward, and git cannot tell it from a deliberate revert.

I pushed `c0fe1257` to `main` intending to add one 5-line instrument. It also
DELETED `scripts/capture_wnba_pbp.py` and `tests/test_capture_wnba_pbp.py`
outright and dropped 41 lines of `lanes.md` and 64 of `todo.md` — **514
deletions I did not author and did not intend**, wiping a parallel session's
work that had been pushed ~1 minute earlier.

**The mechanism, which is the part worth memorising:**

    git merge-tree --write-tree --merge-base=B origin/main MINE   -> read origin/main = 16a7f261
    ... a PARALLEL SESSION's fetch advanced origin/main to a5ff7a6f ...
    git commit-tree $TREE -p origin/main                          -> read origin/main = a5ff7a6f

The commit got the **NEW parent** and the **OLD tree**. That is a perfectly
valid fast-forward — the parent is the remote tip — so **`git push` accepted it
with no `--force` and no warning.** Every safety net I had been relying on all
session was blind to it:

- `git push` non-fast-forward rejection: PASSED it. The parent was current.
- `--force-with-lease`: would also have passed. The lease is on the REF, and the
  ref was exactly what I expected.
- The pre-push verification I DID run: I diffed `origin/main..$TREE` and saw
  "only my 2 files, 0 deletions". **That diff was against 16a7f261 — the stale
  value.** I verified the right property against the wrong baseline, which is
  worse than not verifying, because it produced confidence.

**The rule: pin every ref to a literal SHA ONCE, and pass that SHA to every
subsequent call.** Never let two git invocations resolve the same symbolic ref —
in a repo with parallel sessions the second resolution is a different commit.

    OURS=$(git rev-parse origin/main)     # once
    T=$(git merge-tree --write-tree --merge-base=$BASE $OURS $MINE)
    NEW=$(git commit-tree $T -p $OURS)    # SAME literal

**And the verification that actually catches it** — diff the finished commit
against the LITERAL SHA you built on, immediately before pushing, and require
zero deletions:

    git diff --name-status $OURS $NEW | grep -c '^D'    # must be 0

**Why the existing rules did not cover this.** `project_shared_index_can_hold_a_revert`
and "run `git diff --cached --stat` before every commit" both govern the INDEX,
and I followed them — I used the pathspec commit form and never ran `git add -A`.
This failure has nothing to do with the index; it is in ref resolution between
calls, and it bypassed a clean index entirely. `feedback_never_chain_add_and_commit`
says separate the calls — here **separating the calls is what caused it.**

**Blast radius:** `origin/main` carried the reverted state for ~2 minutes
(`c0fe1257` -> `55586571`). Any session that pulled in that window has the
deletions locally and will re-introduce them if it pushes. Repaired forward
rather than with a force-push, so the bad commit remains in history as a record.

**Second-order lesson, the one I keep relearning:** I ran the *right* check with
the *wrong* baseline and read the pass as safety. A verification is only as good
as the thing it is compared against, and a baseline captured in an earlier tool
call is not a constant in a repo other people are pushing to.
