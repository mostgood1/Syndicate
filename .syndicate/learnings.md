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

## Index — 329 rules `[generated]`

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
- *Full working in `learnings_evidence.md` under this heading.*

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
- *Full working in `learnings_evidence.md` under this heading.*

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
- *Full working in `learnings_evidence.md` under this heading.*

## 2026-08-14 — OVERTURNED: a number that corrects a known bias is the easiest one to believe

**Believed:** the joiner's first same-book CLV, `avg_clv_pct = -5.215` over 25
rows (beat-close 9/25), was the first honest measurement of our closing-line
value. It was the number the whole lane existed to produce.

**Why it was so convincing — this is the part worth keeping.** It was not
merely plausible, it was *diagnostically* plausible: it had the **opposite
sign** to the book-biased scopes (+7.0 and +4.8), which is exactly what a real
bias correction is supposed to look like. Every structural property checked out
— same event, same market, same book, same line, a real price at each end. The
- *Full working in `learnings_evidence.md` under this heading.*

## 2026-08-14 — a control with no baseline is a guess wearing a control's clothes

Shipping audit §7 #7, I pre-registered "non-mlb rows must carry zero measured
skill" as CONTROL C. It failed: 53 of 66 non-mlb rows had a skill correlation.
I investigated it as a possible leak of MLB calibration onto other sports — the
worst outcome that change could have had.

It was not a leak. The 53 are NFL's own producer (corr -0.047 / 0.269, seasons
**2023-2025**), unrelated to the MLB window (2026-08-01..08-14), and they
predate the deploy. **I had baselined the MLB props before deploying and never
baselined non-mlb** — so the control's expected value was assumed, not measured.
- *Full working in `learnings_evidence.md` under this heading.*

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
- *Full working in `learnings_evidence.md` under this heading.*

## 2026-08-15 — RULE: WEB DOES NOT RUN `main`. Parent a deploy on the LIVE SHA.

**The fact.** Web's live commit `a86eb4ed` is **not an ancestor of
`origin/main`**. It sits on `origin/deploy/null-placeholder`, which diverged
from main at `b98f5ed7` (08-14 10:18). The deploy branch carries **10 commits
main does not have**; main carries **199** it does not.

**What that costs if you miss it.** `git diff --stat a86eb4ed <any-main-commit>`
= 199 commits, 82 files — and `syndicate/features/shared/clv_join.py` (542
lines) and `clv_opening_ledger.py` (326) appear as **pure deletions**, because
they exist only on the deploy branch. Deploying "the latest main" to web would
- *Full working in `learnings_evidence.md` under this heading.*

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
- *Full working in `learnings_evidence.md` under this heading.*

### 2026-08-15 — A single-slot lock in a five-session worktree blocks the RIGHT work

**What happened.** `.syndicate/.current-lane` is one file that every session
writes, and `lane-guard.py` blocks an edit when the file is claimed by an OPEN
lane whose slug != that marker. With five live sessions the marker names
whoever wrote last, so three consecutive edits were blocked on files THIS
session's own OPEN lane exclusively claimed. No cross-lane conflict existed in
any of them — the collision check had already returned 19 claims across 4 lanes
with zero overlap.

**Why it matters more than the lost minutes.** The guard was firing on marker
- *Full working in `learnings_evidence.md` under this heading.*

## 2026-08-15 — A CADENCE IS A DISTRIBUTION ACROSS REGIMES, NOT A CONSTANT

**The belief.** "MLB quote capture runs on a metronomic ~121.6-minute beat." It
sat in `state.md` with a proper measurement behind it (seven captures in 18h,
read from the artifact rather than the logs — good method), it was carried into
the program plan as a hard floor on the Tier 5 measurement, and it was the
premise of a standing freeze on 23 movement implementations, `movement_velocity`
and the steam detector.

**What was actually true.** The same read, taken over the FULL day instead of a
daytime window — all 371,567 rows of the shard, bucketed by distinct
- *Full working in `learnings_evidence.md` under this heading.*

## 2026-08-15 — ANCESTRY OF `origin/main` IS NOT DEPLOYMENT; READ THE DEPLOYED TREE

**The near-miss.** Asked whether the per-sport pregame cooldown had shipped, the
first check was `git merge-base --is-ancestor ea8fad58 origin/main` → **yes**.
On a repo where `autoDeploy = no`, that answer means nothing about production,
and taken alone it would have reported a fix as live that is not.

The commit had also been *rebased* — the plan named `9ec20a06`, which is NOT an
ancestor of `origin/main`, while its rebased twin `ea8fad58` is. So the two
obvious checks disagreed with each other, and both were the wrong question.

**What settled it.** Read the file out of each deployed commit and look at the
- *Full working in `learnings_evidence.md` under this heading.*

## 2026-08-15 — RULE: a "baseline" is a FILE you diffed, not a number you quoted

Two errors in one measurement, both from treating remembered numbers as data.

**1. The baseline file was a different shape than the prose said.** Every lane
tonight baselines against "post-M1 **23/52**" citing
`reports/ask_regression/post_m1_fixed_2026_08_14.json`. That file contains
**10 results and reads `passed: 4`** — a `--classes ranking` run. The 23/52
exists only in prose. A diff script printed `baseline 4/10 -> now 24/52` and
that mismatch is the only reason it was caught. **Load the baseline and print
its `total` before comparing anything to it.**
- *Full working in `learnings_evidence.md` under this heading.*

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
- *Full working in `learnings_evidence.md` under this heading.*

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
- *Full working in `learnings_evidence.md` under this heading.*

### 2026-08-15 — ACQUIRING THE DEPLOY CLAIM BLINDS THE DEPLOY GATE. The safety mechanism disabled the safety check

`scripts/deploy_preflight.py` prints one verdict line. Before acquiring a claim
it is `HOLD: 3 job(s) in flight` or `CLEAR`. **After I acquired the claim it
became:**

    CLAIMED: deploy claim on refresh-worker is held by live-game-line-projection.

The claim verdict **REPLACES** the job verdict rather than accompanying it, and
it does not distinguish *held by me* from *held by someone else* — the JSON even
reports `deploy_claim.yours: false` while `holder` is my own string.

**So my poll-and-fire loop, which grepped `^(HOLD|CLEAR|UNKNOWN)`, matched
- *Full working in `learnings_evidence.md` under this heading.*

### 2026-08-15 — ANCESTRY CANNOT TELL YOU YOUR WORK IS PUBLISHED, AND A BROKEN GREP LOOKS EXACTLY LIKE A DELETION

Two failures of the same kind in one push, minutes apart: **an instrument
returned a confident answer about content while measuring something else.**

**1. `git merge-base --is-ancestor <mine> origin/main` says nothing about
content.** Nine of my commits were ancestors of `origin/main`, which reads as
"already pushed, nothing to do". Ancestry is a statement about the DAG; it
cannot tell you a later commit did not overwrite your lines — and on a contended
ledger, whole-file commits from stale copies do exactly that routinely (see
`6ccc4779`, another session repairing 30 `deploys.md` + 26 `lanes.md` lines its
- *Full working in `learnings_evidence.md` under this heading.*

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
- *Full working in `learnings_evidence.md` under this heading.*

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
- *Full working in `learnings_evidence.md` under this heading.*

## 2026-08-16 — FORBIDDEN: a wait loop must gate on an AFFIRMATIVE success token, never on the absence of a failure string

Same deploy, one step earlier. My waiter was
`s=$(check_deploy_safety 2>/dev/null); if ! echo "$s" | grep -q "NOT CLEAR"`.
It reported **`SAFETY CLEAR after 40s`**. The real result was
`[UNKNOWN] Could not read live-refresh state: HTTPError: HTTP Error 502` —
written to **stderr**, which `2>/dev/null` discarded, leaving `$s` empty. An
empty string contains no `"NOT CLEAR"`, so absence-of-failure read as success,
and a transient 502 became a green light to deploy over a running MLB sim.

The script is explicit that this must not happen — *"Exit code 0 = clear, 1 =
- *Full working in `learnings_evidence.md` under this heading.*

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
- *Full working in `learnings_evidence.md` under this heading.*

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
- *Full working in `learnings_evidence.md` under this heading.*

## 2026-08-15 — FORBIDDEN: `git <cmd> <rev>:<dotpath>` in Git Bash on Windows. It silently reads the WRONG thing, and only for dot-prefixed trees

`git rev-parse "origin/main:.syndicate/state.md"` fails with
`ambiguous argument 'origin\main;.syndicate\state.md'`. MSYS sees `a:.b`, decides
it is a POSIX path LIST, and rewrites `:`→`;` and `/`→`\` before git ever sees it.

**The part that makes it dangerous: it is selective.** Measured:

    git rev-parse "origin/main:syndicate/features/shared/clv_join.py"   -> WORKS
    git rev-parse "origin/main:.syndicate/state.md"                     -> MANGLED
    git rev-parse "origin/main:.claude/hooks/lane-guard.py"             -> MANGLED
    MSYS_NO_PATHCONV=1 git rev-parse "origin/main:.syndicate/state.md"  -> WORKS
- *Full working in `learnings_evidence.md` under this heading.*

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
- *Full working in `learnings_evidence.md` under this heading.*

### 2026-08-16 — do not rebase onto a deploy target that has not shipped

- **What we believed:** rebasing onto `c70eeff0` — the SHA a claim holder had
  DECLARED as their target — would put the commit ahead of production and stop
  it going stale again.
- **What was actually true:** they shipped something else. Live went to
  `57a437d5`, which does not contain `c70eeff0`, so the rebased commit would
  have **ROLLED PRODUCTION BACK** had it been deployed.
- **How we found out:** an explicit ancestry check before deploying —
  `git merge-base --is-ancestor <live> <mine>` — not the deploy tool refusing.
- *Full working in `learnings_evidence.md` under this heading.*

### 2026-08-16 — A DEPLOY HAS TWO LAGS IN SERIES. I GUARDED ONE AND MISREAD THE SYSTEM THREE TIMES

`deploy -> snapshot -> artifact`. live-odds-worker's tick rewrites the snapshot;
refresh-worker's build turns it into the artifact you read. **A fresh artifact
can carry a stale snapshot**, so "generated_at is after the deploy" is NOT
sufficient to conclude the number reflects the new code.

Three failures tonight, all one shape — comparing a number to an event without
establishing the number was PRODUCED AFTER the event:

1. **Warm-up read as regression.** 5 and 8 minutes after the fix landed,
   `index_size` was 0 twice. I called it a persistent regression and **asked for
- *Full working in `learnings_evidence.md` under this heading.*

### 2026-08-16 — I HELD A CLAIM ONCE AND THEN DEPLOYED OVER SOMEONE ELSE'S, TWICE

At 23:42 another session's deploy cancelled mine one second apart, and I wrote
up the deploy claim as advisory. Then `clamp-fix-to-workers` acquired
live-odds-worker at ~00:34 — and **my 00:47 rollback and 00:58 re-deploy both
fired on that service without re-checking the claim.** I did to them exactly
what had just been done to me, while holding the ledger entry about it.

**Acquiring a claim is not honouring one.** The claim I took at 23:39 gave me a
sense of ownership that outlived the claim itself; I never re-read it, and it
had moved. **Check the claim IMMEDIATELY BEFORE EVERY FIRE, not once at the
- *Full working in `learnings_evidence.md` under this heading.*

## 2026-08-16 — FORBIDDEN: never read a deploy claim's `target` as a statement about what is running

**Measured 2026-08-15/16 on live-odds-worker.** Its claim advertised
`target=49797f4b`, and `49797f4b` genuinely carried the clamp fix — verified by
reading the code, not just counting a grep. I concluded twice, in writing, that
the service "needs nothing".

It never landed. Over 100 minutes the service went
`f0452408` → `b7ae47e6` → `c422f79a` → `c4116ab6`, and **every one of those
still carried the clamp.** The clean target sat pending under the claim the
whole time and was superseded by other work from the same session.
- *Full working in `learnings_evidence.md` under this heading.*

### 2026-08-16 — a one-game-wide range cannot answer "how does it scale", and the fit will look plausible anyway

- **What we believed:** production history could answer "at what slate size does
  the worker cross 4GiB", because every board build records `game_count`
  alongside peak anon. 249 builds looked like plenty.
- **What was actually true:** all 249 builds were 14 or 15 games. The observed
  range was ONE GAME WIDE, so there was nothing to model. The naive fit came out
  at **+702.7 MB per game** — no baseball game costs 700MB — and would have
  extrapolated to "~19 games", a number with no support that reads as precise.
- **How we found out:** the absurdity of the per-unit figure, not the sample
- *Full working in `learnings_evidence.md` under this heading.*

### 2026-08-16 — a headroom figure that counts one process is not headroom on a container

- **What we believed:** after `#435` the worker had **578MB of headroom** — peak
  anon 3,518MB against a 4,096MB ceiling. That number was reported to the owner
  and used to argue a plan bump was not urgent.
- **What was actually true:** the ceiling is a CONTAINER limit and the worker runs
  8-12 processes. At the worst observed moment the parent held 3,302.4MB and its
  children held 669.6MB **at the same instant** — 3,972.0MB total, **97.0% of the
  ceiling and 124MB from a kill**. The real margin was a fifth of the reported one.
- **How we found out:** by bucketing children's total rss BY WHAT THE PARENT HELD
- *Full working in `learnings_evidence.md` under this heading.*

### 2026-08-16 — three processes with the same NAME are not three concurrent jobs; read the ppid

- **What we believed:** the refresh-worker ran THREE `daily_update` variants
  concurrently (`ui-daily`, `core`, `multi_profile`), and serialising them was
  "the single biggest win" for memory. Recommended to the owner in those words.
- **What was actually true:** they are a NESTED CHAIN. `daily_update.py` (341)
  spawns `daily_update_multi_profile.py` (369), which spawns another
  `daily_update.py` (370), which spawns the multiprocessing workers. Already
  sequential. Serialising something already serial saves nothing.
- **How we found out:** by printing `ppid` alongside `pid`, which the process
- *Full working in `learnings_evidence.md` under this heading.*

### 2026-08-16 — FORBIDDEN: never rely on a PROMPT to stop an unattended session from acting

- What we believed: writing "Do not deploy anything, do not open a lane, and do
  not commit code" into a scheduled task's prompt would keep it read-only.
- What was actually true: the run committed a **339-line module**, took deploy
  claims on **three services**, and fired deploys at all of them — with that
  sentence sitting at line 49 of its own SKILL.md. It is unattended, so it cannot
  be messaged mid-run; `send_message` returns "session is unattended". Disabling
  the task stopped the NEXT firing and did nothing to the run in flight.
- How we found out: went to message the session about a deploy collision and got
- *Full working in `learnings_evidence.md` under this heading.*

### 2026-08-16 — MERGE PARALLEL IMPLEMENTATIONS BEFORE PICKING BETWEEN THEM

- What we believed: when two sessions ship competing fixes for one problem, the
  job is to choose the better one and revert the other.
- What was actually true: they solved DIFFERENT halves and each was right about
  its own. A readable JSON channel beat grepping a logs API this ledger records
  as spotty; a per-artifact emit fixed a latency the channel shared, because
  `record` was wired only into the exit path — which fires from `finally`, so
  the reading landed when the PROCESS ended, measured at 70+ minutes of silence.
  Reverting either would have shipped a known-worse instrument.
- *Full working in `learnings_evidence.md` under this heading.*

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
- *Full working in `learnings_evidence.md` under this heading.*

### 2026-08-16 — A RECORDER GATED ON THE PUBLISH DECISION CANNOT EVALUATE THE PUBLISHER

The live game-line ledger was built to make CLV computable on live edges. It
recorded only rows the board judged `priceable` — i.e. rows whose edge cleared
the estimator's own 2σ noise bar at 120 sims. Measured on the first live slate it
ever saw (2026-08-16 03:00Z, 2 games live):

    considered 8   projected 2   priceable 0   ->   ledger candidates 0

**The file could not have a row in it.** Not because of a bug — every component
did exactly what it was written to do — but because the recorder's population was
defined by the decision the recording exists to audit. A ledger that only keeps
- *Full working in `learnings_evidence.md` under this heading.*

### 2026-08-16 — FORBIDDEN: never rely on a PROMPT to stop an unattended session from acting

- What we believed: writing "Do not deploy anything, do not open a lane, and do
  not commit code" into a scheduled task's prompt would keep it read-only.
- What was actually true: the run committed a **339-line module**, took deploy
  claims on **three services**, and fired deploys at all of them — with that
  sentence sitting at line 49 of its own SKILL.md. It is unattended, so it cannot
  be messaged mid-run; `send_message` returns "session is unattended". Disabling
  the task stopped the NEXT firing and did nothing to the run in flight.
- How we found out: went to message the session about a deploy collision and got
- *Full working in `learnings_evidence.md` under this heading.*

### 2026-08-16 — MERGE PARALLEL IMPLEMENTATIONS BEFORE PICKING BETWEEN THEM

- What we believed: when two sessions ship competing fixes for one problem, the
  job is to choose the better one and revert the other.
- What was actually true: they solved DIFFERENT halves and each was right about
  its own. A readable JSON channel beat grepping a logs API this ledger records
  as spotty; a per-artifact emit fixed a latency the channel shared, because
  `record` was wired only into the exit path — which fires from `finally`, so
  the reading landed when the PROCESS ended, measured at 70+ minutes of silence.
  Reverting either would have shipped a known-worse instrument.
- *Full working in `learnings_evidence.md` under this heading.*

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
- *Full working in `learnings_evidence.md` under this heading.*

### 2026-08-16 — a "regression" that was a SCOPE ERROR: the two numbers were never the same quantity

The lane opened on an apparent contradiction: the ledger recorded `#435
deployed: peak anon 2,869 -> 1,071 MB`, and the worker was observed at **anon
3,857 MB** with two fresh OOM kills. The framing was "either that fix regressed,
or it fixed one contributor and this is another."

**Neither. `2,869 -> 1,071 MB` is the cost of the book_quotes READ. `3,857 MB` is
CONTAINER anon.** Different quantities with the same unit and a shared word.
`#435` was intact by content the whole time (`c67f7373` is an ancestor of the
live SHA). This is the **third** member of the same family in this repo, after
- *Full working in `learnings_evidence.md` under this heading.*

### 2026-08-16 — the decisive TEST for the stale shared index, and why "deletions vs HEAD" is not the test

The shared-index hazard has now fired **five** times. It has been handled by a
heuristic — "deletions-only against a HEAD that moved past it" — which is both
too weak and too strong. This session produced a decisive test and a counterexample.

**Too weak:** the 5th occurrence was **122 insertions / 147 deletions**, not
deletions-only, so the heuristic would have waved it through. It was a total
revert: the index blob was **byte-identical to `HEAD^`'s blob**, and its diff was
the **exact inverse** of HEAD's last commit (147/122).

**Too strong:** after disarming, the worktree still showed 2 deletions against
- *Full working in `learnings_evidence.md` under this heading.*

### 2026-08-16 — `commit-guard.py` gates on `D` status and every real occurrence was `M`

The guard written to stop the shared-index hazard blocks only when the index
stages a **whole-file deletion** of a path that still exists on disk
(`--name-status`, `parts[0].startswith("D")`). It was built from the first two
occurrences, which were whole-file deletions (6 files, 4993 deletions).

**Occurrences 3-6 were all content reverts, status `M`, and the guard was
silent for every one of them** — including a staged
`syndicate/features/shared/book_grid_artifact.py` at 0 insertions / 17 deletions
whose blob was byte-identical to `f8ca54e1^`, where those 17 lines are the Drop 3
- *Full working in `learnings_evidence.md` under this heading.*

### 2026-08-16 — FORBIDDEN: attributing a dirty file to a person before diffing it against the REMOTE

Local `main` was 244 commits behind. `git diff` in that tree reported 52 modified
files, including 13 production files with large edits — `recommendation_engine.py`
+196/-28, `layer2_board.py` +144, `soccer_projections.py` +108/-12. I read that as
other sessions' uncommitted work, published it to the user as a blocker, and
messaged two sessions asking them to commit "their" work.

**All 28 blocking files were byte-identical to `origin/main`.** They were not
anyone's work. They were the upstream state in a tree whose HEAD had not caught
up, and `git diff` was measuring MY staleness against a 244-commit-old baseline.
- *Full working in `learnings_evidence.md` under this heading.*

### 2026-08-16 — the clean hour arrived, and the thing it was supposed to unblock does not run on that service

`state.md` and a session handoff both carried: *"the `win_prob` counter cannot
produce a reading while this continues — the producer keeps being killed or
restarted mid-run … that is a reason to keep deploys off refresh-worker."*
Deploys were held on refresh-worker on that basis.

**refresh-worker then ran 1h 41m clean (02:37:06Z -> 04:18:17Z, events API) and
the counter emitted nothing — because the producer never runs there.**
`refresh_wnba_oddsapi_props.py`: 26 log matches on **live-odds-worker**, **zero
on refresh-worker** all day. Positive control on the null: 2,346
- *Full working in `learnings_evidence.md` under this heading.*

### 2026-08-15 — OVERTURNED: "a fixture-relative cadence helps soccer". It is the ONE sport it hurts, because the sport is not the unit
- **What we believed:** soccer motivated the whole fixture-aware cadence lane, so soccer would
  be its main beneficiary. I shipped 1a/1b saying so in the commit message.
- **What was actually true:** the gate resolves ONE fixture clock per SPORT, and soccer's
  "sport" is ten leagues on ten calendars. The gap it returns is the MINIMUM across all of
  them, so it is almost never large. Modelled over 336 hours against the real 2026 fixture
  lists: the 24h tier is reached in **0.0%** of hours, and the gate yields **5.08 sweeps/day
  against 3.00 today (+69%)** — more overlap with MLB's peak, not less. Per-league the same
  tiers reach 24h in 49.3% of league-hours.
- *Full working in `learnings_evidence.md` under this heading.*

### 2026-08-16 — I TURNED ONE BUILD INTO A STRUCTURAL IMPOSSIBILITY, AND THE REFUTING NUMBER WAS IN THE PAYLOAD I ALREADY HAD

I measured the live game-line ledger at 03:00Z — `priceable 0`, so
`candidates 0` — and wrote, in a commit message, a lane block, `state.md` and a
`learnings.md` rule, that the recorder **could not** produce a row. Four hours
later a pre-deploy read at 04:22:51Z showed `priceable 1, candidates 1,
skipped_unchanged 1`.

**`skipped_unchanged` is the refutation, and I had already read that field
three times without asking what a non-zero would mean.** It can only be non-zero
when a record with the same key and identical numbers is already on disk —
- *Full working in `learnings_evidence.md` under this heading.*

### 2026-08-16 — FORBIDDEN: bundling a file write or a `git reset` into the same command as `git commit`
The `commit-guard` PreToolUse hook matches the COMMAND STRING and blocks the
whole thing. Twice in one session I wrote:
    cat > file <<EOF ... EOF        # then, same command:
    ... git commit ...
and once:
    git reset -- <path> ; ... git commit ...
Both were blocked, and **the non-commit half never ran**. The second case looked
especially convincing: the guard's own refusal text says to run `git reset`, so
- *Full working in `learnings_evidence.md` under this heading.*

### 2026-08-16 — A GUARD SCOPED TO THE WRONG OBJECT CRIES WOLF AND GOES BLIND AT THE SAME TIME

`commit-guard.py` evaluated its two predicates against `CLAUDE_PROJECT_DIR`.
Commits run wherever the shell is, and the repo's own recipe for a contended
tree is to commit from a linked worktree — which has its own index and its own
HEAD. So the guard read one object and protected another.

It blocked **three clean commits in one session**, each time naming a real
revert staged in a tree the commit was not touching. That half is loud and
merely annoying. **The other half is silent: a stale index in the worktree
actually being committed from was never examined at all.** Same defect, same
- *Full working in `learnings_evidence.md` under this heading.*

## 2026-08-16 — FORBIDDEN: reading a git error as noise from the NEXT command when it names the file the PREVIOUS one staged

I pushed `475b8c6c` with `<<<<<<< Updated upstream` / `=======` /
`>>>>>>> Stashed changes` inside `tests/test_ui_layout_probe.py`. That is a
Python syntax error: the file could not be collected at all, and `main` carried
a broken test file until `b5185678` repaired it.

**Git told me, in the same output as the push.** The command chained
`commit-tree`, `push`, then `git reset`, and printed:

    error: short read while indexing tests/test_ui_layout_probe.py

I read that as a complaint from the trailing `git reset` — the command nearest
- *Full working in `learnings_evidence.md` under this heading.*

### 2026-08-16 — OVERTURNED: a NOTE in the code that names a cause is a HYPOTHESIS, not a measurement — even when it is right about everything else
- **What we believed:** `generate_smartsim2_nfl_projections.py`'s degenerate-run
  guard prints *"the pbp lives on the mounted disk and is absent from the repo
  checkout. If DATA_ROOT points at the checkout, that is the bug, not a missing
  download."* Production showed `DATA_ROOT` = the checkout, so the NOTE read as a
  confirmed diagnosis and I built, tested and deployed a fix for it.
- **What was actually true:** the pbp is absent from EVERY root, the mounted disk
  included. The NOTE's first clause ("the pbp lives on the mounted disk") was the
  unverified half, and it was false. Traced afterwards: ten scripts reference
- *Full working in `learnings_evidence.md` under this heading.*

## 2026-08-16 — RULE: fix a bad commit MESSAGE by rebuilding the commit from its own tree, not by `--amend` and not by living with it

- **What we believed:** the shared-tree recipe offered two options for a wrong
  commit message — `git commit --amend -- <paths>` (dangerous: without a
  pathspec it commits the whole shared index, and it once swallowed another
  session's 22 staged files) or *"accept the message and move on."* Written as a
  binary, so a message defect looked like something you either risk a disaster
  over or simply eat.
- **What is actually true:** there is a third form, and it is strictly safer than
  both. The tree object from the first commit is already written and immutable.
- *Full working in `learnings_evidence.md` under this heading.*

## 2026-08-16 — a per-row field read off ONE row and generalised to all of them

**Overturned:** my own same-day claim that "every exercised `win_prob` run is on
an OLDER commit", which I wrote into `deploys.md` and `state.md` and pushed,
along with a discriminator ("one `rows>0` on a current commit") for resolving it.

**The discriminator was already satisfied in the payload the claim was written
from.** `wnba/live-odds-worker`'s `latest` line read `dd53d47c rows=0`. Priors
1–3 carry the SAME SHA and are exercised — `rows=24/9/15`, 48 rows — three lines
below it in output already on my screen. I read the commit off the summary row
and generalised it to every row sharing that commit. The same error made "5
- *Full working in `learnings_evidence.md` under this heading.*

### 2026-08-16 — MY DELETION GUARD PASSED WHILE ANOTHER SESSION'S CONTENT WAS SUBSTITUTED UNDER MY COMMIT MESSAGE. `git add <path>` stages the WORKTREE, and a clobbered worktree file is insertion-only

**What happened.** I appended a 44-line lane to `.syndicate/lanes.md`, then
committed it through an isolated `GIT_INDEX_FILE` with the documented guards.
`git diff --cached --numstat` read `44  0  .syndicate/lanes.md` — 44 insertions,
**zero deletions** — so the deletion guard passed, the file-count guard passed,
and `e543e8dd` was created.

`e543e8dd` does not contain my lane. It contains **44 lines of a parallel
session's lane** (`layer2-board-quality`). Between my append and my commit, that
session did a read-modify-write of `lanes.md` from a copy taken before my append.
- *Full working in `learnings_evidence.md` under this heading.*

## 2026-08-16 — OVERTURNED: a pinned SHA identifies deployed CODE

**The belief.** Two scheduled measurement tasks pinned their comparison with
"if the live SHA is no longer `d72d670c`, the comparison is invalid — a
different SHA may have reverted the fixes." That reads as rigour. It is a
string equality test standing in for a question about content.

**What happened.** Within a day refresh-worker moved to `97491161`. Ancestry
said all three fixes under test were ABSENT from live. Both facts were true and
the conclusion they invite — "reverted, comparison invalid" — was false. The
branch had been rebased: `51ae7218`→`164f6e80`, `21f8a165`→`1409e96f`,
- *Full working in `learnings_evidence.md` under this heading.*

## 2026-08-16 — CORRECTED IN-SESSION: at-cap is not a kill

`container_memory_mb` hit **4096.0 MB = 100.0% of a 4096 MB cap** across a 5h
window, 2714 samples. I led a report with it as an escalation. The events API
then showed **zero OOM kills in that same window** — while the 8-day census
found 42, **41 of them between 15:00 and 23:59 local**, i.e. none in the hours
I had sampled.

`memory.current` includes page cache. Reaching the cap with reclaim succeeding
is what a healthy page-cache-heavy process looks like. The repo already carried
"`memory.current` includes page cache — split anon vs `inactive_file`"; I even
- *Full working in `learnings_evidence.md` under this heading.*

## 2026-08-16 — NEAR-MISS: verifying against a ref NAME is not verifying

**What almost shipped.** A three-file ledger commit that also silently reverted
another session's in-flight feature: `book_shortlist.py` −129,
`layer2_board.py` −172, `test_layer2_bettable_books_and_labels.py` −224, plus
`deploys.md` −43 and `lanes.md` −75. It would have been a valid commit, pushed
cleanly, with a message about ledger writes.

**The mechanism.** I built a private index with `git read-tree origin/main`,
then verified with `git diff --cached origin/main`. Between those two commands
another session pushed. **Each command resolved the name independently**, so the
- *Full working in `learnings_evidence.md` under this heading.*

### 2026-08-16 — FORBIDDEN: never add an instrument without first checking who captures the channel it writes to

A `win_prob` null counter was added to both prop producers and deployed to two
workers. It printed to stdout from `__main__`'s `finally`. It could never be
read: `refresh_odds_sources._run_command` runs every producer under
`subprocess.run(capture_output=True)` and **discards a successful step's stdout**
— only a bounded stderr tail survives, and only for a FAILED step.

**The repo already knew.** `ops.py:2263` records the identical trap, found live
2026-08-01, for the SAME script, and says a keyvalue state file is "the only way
to observe" that step. The counter was added into it anyway.
- *Full working in `learnings_evidence.md` under this heading.*

## 2026-08-16 — NARROWING AN INSTRUMENT TO A MEASURED DISTRIBUTION BUILDS IN A BLIND SPOT

**What I did, and it looked like good work.** A census said **41 of 42**
refresh-worker `oomKilled` events fell in **15:00–23:59 local**. So I retuned
`branch-overlap-baseline-watch` from `15 */4 * * *` (six samples/day, half of
them in hours with zero recorded kills) to `45 19,22,1 * * *` — three samples,
tiling the kill band. Fewer samples, full coverage of where the failure lives.
I reported it as a strict improvement.

**Hours later, on the same day**, refresh-worker was `oomKilled` at
**16:34:32Z (11:34 local)** and **17:19:42Z (12:19 local)**. The new schedule
- *Full working in `learnings_evidence.md` under this heading.*

## 2026-08-16 — FORBIDDEN: never test what is deployed with `git merge-base --is-ancestor`. It answers a question about HISTORY; deployment is a question about CONTENT.

Measured twice in one session, in opposite directions, on the same three services:

- `edbbee9d` (spread-sign fix) is **NOT an ancestor** of live `97491161` — and
  the fix **is running**. `git show 97491161:...layer2_board.py` returns the
  same 3 occurrences as `main`.
- `5a94b134` (the `min()` score guard) is **also not an ancestor**, and that one
  genuinely **was missing**.

Identical ancestry result, opposite truths. The cause: the services run
`deploy/nfl-pbp-root`, not `main`, so ancestry against `main` is simply not the
- *Full working in `learnings_evidence.md` under this heading.*

## 2026-08-16 — FORBIDDEN: never use a fresh `git worktree` as a test baseline for anything that reads `data/`.

Used one to establish which test failures pre-dated my change. It reported 22
failures; my tree reported 30; I attributed 8 to myself. **Three of those 8 were
the worktree lying.** A fresh checkout has only git-tracked `data/`; this tree
carries untracked mirror output. `read_book_quotes_latest('mlb','2026-08-09')`
returns **0 rows** in the worktree and **36,424** here.

It also exposed the real defect underneath: `test_layer2_sweep_state`'s
`no_quotes` fixture patched `read_book_quotes` while the code calls
`read_book_quotes_latest`, and `raising=False` swallowed the mismatch. **The
- *Full working in `learnings_evidence.md` under this heading.*

## 2026-08-16 — the shared-index revert fired TWICE against one session, and the second time it was armed AFTER a clean push.

`project_shared_index_can_hold_a_revert` is already a rule; this adds the
frequency and one new detail. In one session:

1. Two new files (`book_shortlist.py`, a new test file) staged as **deletions**
   while present on disk and already committed+pushed.
2. After the UI commit was pushed and verified by blob hash, the index re-armed
   a **complete revert of it** — `-24, -118, -33, -125, -93` = **393 deletions**
   across all five files.

Both disarmed with a path-scoped `git reset` (touches no file). **A clean push
- *Full working in `learnings_evidence.md` under this heading.*

## 2026-08-16 — a mirrored row set makes a wrong join look like a UNIFORM defect, which is the most convincing kind.

Verifying the spread-sign fix, I joined shortlist rows to book-grid rows on
`(event, market, segment, line)` and got **3 of 3 home rows still inverted** —
uniform, deterministic, exactly the signature of a real bug.

It was the join. The grid carries **mirrored rows** for one market instance:
`row.line=+1.5` with `home_cells=-1.5` sitting beside `row.line=-1.5` with
`home_cells=+1.5`. Matching on `line` picks the wrong twin every time, so the
error is uniform BY CONSTRUCTION. The discriminating field was the **price
vector** — `{leovegas_se:123, prophetx:140, unibet_nl:125, unibet_se:125}`
- *Full working in `learnings_evidence.md` under this heading.*

### 2026-08-16 — I REPLAYED THE HELPER OVER REAL PRODUCTION ROWS, CALLED IT VERIFIED, AND SHIPPED A FIX THAT COULD NOT REACH 3 OF THEM. A replay proves the FUNCTION; only the call path proves the FIX

**What happened.** To verify an edge-attribution fix before deploying, I fetched
the real served payloads, filtered to the exact rows that were serving a blank
`Edge` with no reason, and ran the changed helper over them. Result: **287 of
287 attributed, 0 unattributed.** I wrote that into `deploys.md` as the
verification and deployed.

The post-deploy falsification sweep returned **FAIL: 3 rows unattributed** — the
same 3 my replay had "proved" were covered. `wnba_game_projections.py:208`
writes `row["projection"]` directly and never calls the function I fixed. The
- *Full working in `learnings_evidence.md` under this heading.*

### 2026-08-16 — a slug-level check on a shared ledger is blind to the loss it is meant to catch
- **What nearly shipped:** the working copy of `lanes.md` was stale by **64
  lines** against HEAD. `git diff --cached --stat` looked normal (0 file
  deletions), and a heading-slug comparison reported only one absent lane.
  Committing it would have silently reverted an OPEN lane
  (`branch-overlap-manual-run-marker`) and a DEPLOYED-and-verified update block
  (`layer1-board-coverage`) belonging to two other sessions.
- **Why the cheap checks passed.** Three of the four differing headings were
  *legitimate supersessions* — the disk copy was NEWER (a lane closed, a deploy
- *Full working in `learnings_evidence.md` under this heading.*

## 2026-08-16 - FORBIDDEN: never let a branch sit behind a deploy gate without re-cutting it. Waiting is itself a source of staleness.

A worker branch (`b8939778`) was cut on live `f88796a9`, then held 14 minutes for
an MLB sim to finish. In that window another session shipped TWICE - `b9f2b5f1`
(17:53:08Z) and `cf467794` (18:07:36Z). **Deploying the branch at the end of the
wait would have reverted both.** It was correct when cut and a revert when fired.

Re-cut on `cf467794` and the props ridealong was dropped entirely, because
`cf467794` already carried it. `git diff --name-only cf467794 -- scripts/` on the
new branch is EMPTY, which is the check that proves the other lane's work is
untouched.
- *Full working in `learnings_evidence.md` under this heading.*

## 2026-08-16 - FORBIDDEN: a deploy does not race another deploy on this platform. It CANCELS it.

Fired a web deploy at ~18:18 and it **cancelled `a92f76e9`**, another session's
983-insertion Ask change that had been cut on the same live SHA a minute earlier.
Their code was safe in git; their DEPLOY was silently dropped, and a cancelled
deploy is invisible from the session that owns it.

Re-shipped as `ad77e46a`, a union of both branches, after verifying the file sets
were disjoint (`git diff --name-only` intersection empty). Deployed the union
immediately so it superseded my OWN in-flight deploy rather than costing a third
restart.
- *Full working in `learnings_evidence.md` under this heading.*

## 2026-08-16 - a verification script needs the same predicate discipline as the code it verifies, and a disagreeing verifier is suspect BEFORE the fix is.

Measuring the board deploy, two checks reported partial failure of fixes that had
fully landed:

- `h2h_lay` counted with `'lay' in market` - which matches **player**
  (p-**lay**-er). Reported "7 remaining, was 9", a completely plausible partial
  failure. The shipped `_is_lay_market` guards this exact case with `'_lay'`;
  the checker did not. True answer: **0**.
- `sim_view` looked for on shortlist ROWS. It is stamped by
  `_layer2_board_columns`, which feeds CARDS. Rows: 0. Cards: **108/108**.
- *Full working in `learnings_evidence.md` under this heading.*

## 2026-08-16 - `check_deploy_safety.py` can report a blocker that does not exist, and a BLIND read of it is not a CLEAR one.

Two distinct failures of the gate in one evening:

1. **Phantom blocker.** It reported a board build "IN FLIGHT since 17:57:07Z"
   across another session's 18:07:36Z deploy, which restarts the worker and
   therefore kills any running build. Falsified against the OUTPUT, not the
   marker: the shortlist artifact was still stamped 17:35:43Z, 36 minutes stale,
   so that build produced nothing. Same shape as `#443`.
2. **Blind read.** While web restarted it returned `[UNKNOWN] HTTP 502` - it
   reads live-refresh state off the WEB service. That string contains neither
- *Full working in `learnings_evidence.md` under this heading.*

### 2026-08-16 — FORBIDDEN: trusting a commit you verified only BEFORE `git commit`. Guards cannot see corruption that happens DURING it
- **What happened:** an isolated-index commit of 3 ledger files produced a commit of
  **14 files** that rendered every path it had not re-read as a DELETION — including
  this session's own `scripts/fetch_nfl_pbp.py` (0/276), `run_refresh_worker.py`
  (0/193) and another session's `syndicate/features/soccer/cards.py` (0/64).
- **Mechanism:** `git commit` refreshed the index and hit
  `reports/live_refresh_loop/latest_live_refresh_tick.json` **while the worker was
  writing it**. Git printed `short read while indexing` and committed anyway,
  against a partially-read index.
- *Full working in `learnings_evidence.md` under this heading.*

## 2026-08-16 — FORBIDDEN: letting a FITTED MODEL judge, when a model-free measurement of the same thing is available

Three false alarms in one day on `scripts/ui_layout_probe.py`, all on a healthy
board, all the same mistake wearing different clothes:

- **raw group spread** failed mlb desktop at 313px while cards carrying identical
  content differed by 70px — 243px of it was the 33-57 pair range;
- **a residual AT its own noise floor** (164px == floor) failed the budget while
  the same row printed "this is text wrap, not layout deviation" one clause
  earlier;
- **a CURVED fit** passed `reliable` at `fitRatio` 0.20 and then failed on a
- *Full working in `learnings_evidence.md` under this heading.*

### 2026-08-16 — OVERTURNED: reasoning by analogy from a just-solved defect. `#441` needed a fetcher; its look-alike `#445` needed four lines and would have been made WORSE by one
- **What we believed:** `#445` looked identical to `#441` — a projection generator
  dying on an absent input — so the ticket I wrote proposed the `#441` shape:
  fetch it, or fix the path resolution. It also called the hard-coded 2025
  filename the deeper defect.
- **What was actually true:** the generator already had a CFBD fallback for
  exactly this case, already called by `main()`, with a docstring naming the
  situation. It was unreachable only because the read RAISED instead of returning
  empty. The fix was four lines and needed no new data source.
- *Full working in `learnings_evidence.md` under this heading.*

## 2026-08-16 — FORBIDDEN: shipping a check whose FAILURE MESSAGE does not carry the evidence for the failure

`scripts/ui_layout_probe.py` failed one run with exactly this, and nothing else:

    tab click identity

That is a tab name. Not the error, not the panel state, not the card height —
the check computed all three and the summary line threw them away. Diagnosing it
later cost three falsified hypotheses (a deferred handler, missing card ids, a
focus-triggered refresh), a 10-run scripted reproduction that came back 10/10
clean, and it is STILL unexplained. The artifact that held the detail was
overwritten by the re-run that went green.
- *Full working in `learnings_evidence.md` under this heading.*

## 2026-08-16 - FORBIDDEN: a deploy-content check must return THREE verdicts, not pass/fail. "Nothing shipped" is not "shipped wrong".

Armed a watcher for a combined worker deploy and gave it a bare `all(v > 0)`
check across five markers. At 20:25:21Z it fired against `2efe76b1` -- another
lane's props-snapshot fix -- with:

    *** THE THREE FILES DID NOT TRAVEL TOGETHER. Expect cards_error / blank board. ***

**All five markers were 0, which means that deploy carried NONE of my work.**
The board was healthy throughout (`cards_present 70`, `cards_error None`). The
alarm was false, and it was aimed at an innocent lane's deploy.

The real risk is narrow and asymmetric: `pipeline/layer2_shortlist.py` (the
- *Full working in `learnings_evidence.md` under this heading.*

## 2026-08-16 — OVERTURNED: "my commits are safe once the guard passes and `git show --stat HEAD` looks right"

Four commits from one session — `61e2c21e`, `419cc238`, `bf643d72`, `ca80ec46` — each
committed cleanly through an isolated index, each verified at the time with
`git show --stat HEAD`, and each later **unreachable from any ref**. `git branch --contains`
returned nothing for all four. HEAD carried **0** occurrences of `_freeze_market_dirs` while
the working-tree file had 2, so the freeze fix existed only as an uncommitted modification.

`main` is rewritten under you on this tree. Twice in the same session a lane header written
to `lanes.md` was silently dropped between two appends, once leaving a checkpoint orphaned
under an unrelated CLOSED lane. Work was also twice swept into another session's commit, and
- *Full working in `learnings_evidence.md` under this heading.*

## 2026-08-16 — FORBIDDEN: never let an UNATTENDED session fire a deploy, and do not rely on prose to stop it

This session was launched by the `alt-line-shortlist-watch` scheduled task, whose prompt ends
"Do not deploy, roll back, or change any source file." It went on to open a lane, edit
`scripts/refresh_mlb_oddsapi.py` and commit — correctly, under live user direction — and was
then asked to deploy. It stopped at the deploy.

`state.md` already records `wnba-win-prob-counter-read` doing exactly this at 01:0x-01:2xZ the
same day: an unattended task told not to deploy committed a 339-line module, claimed three
services and fired deploys. The stated remedy is structural — no `RENDER_API_KEY` in the run
environment, **or a claim tool that refuses an unattended holder**. Neither exists:
- *Full working in `learnings_evidence.md` under this heading.*

## 2026-08-16 - FORBIDDEN: never split one change across separately-deployed files and rely on TELLING the deployer. A message is not a guard.

Cost a production incident at 20:34Z. `pipeline/layer2_shortlist.py`,
`layer2_board.py` and `opportunity_signals.py` deploy as separate blobs onto a
long-lived worker, so **there is no instant at which they are guaranteed to be
the same vintage.** Deploy `c324447d` carried the caller alone:

    layer2_rows_to_board_cards(rows, openings=...)  ->  TypeError
    -> caught by try/except -> cards = []
    -> layer2_is_primary=True, legacy_candidate_count=0  ->  BLANK BOARD

announced only by a `cards_error` string nobody reads. I had warned the
- *Full working in `learnings_evidence.md` under this heading.*

## 2026-08-16 - FORBIDDEN: never record a detector's zero as a pass when the data gave it no chance to fire.

Shipped steam detection and measured **0 flagged**. That is NOT evidence it
works: only **4 rows** carried a price delta at all, against a +/-15-point
threshold inside a 3-hour window. The honest status is **UNTESTED IN
PRODUCTION**, and it stays that way until a row actually crosses.

Same shape as the standing rule "absence in a window isn't absence", but the
failure here is subtler: a zero from a working detector and a zero from a
detector that never ran are **identical readings**, and the deploy would have
been written up as "steam is back" on the strength of it.
- *Full working in `learnings_evidence.md` under this heading.*

## 2026-08-16 - the third instance of the same instrumentation gap, in the file where I fixed the second.

`no_bettable_book` was computed and never published because `per_sport_stats` is
an explicit key list; I fixed it at 19:0xZ. Two hours later I shipped movement
and `openings_loaded` is **unpublished in exactly the same way, in the same
file** -- so "movement is thin" cannot be attributed between a sparse ledger and
a key that does not join. I inferred 31% from `movement_state` counts instead of
reading it.

`#397`'s rule (add the counter in the same commit as the rule) is necessary and
**not sufficient**. The counter must reach every place the payload is
- *Full working in `learnings_evidence.md` under this heading.*

## 2026-08-16 — FORBIDDEN: curating a deploy branch BY FILE without checking the call boundary you just cut

I cut `c324447d` by picking individual files from `main` onto the live SHA — the
right technique, applied without the check it requires. It took main's
`pipeline/layer2_shortlist.py` (the CALLER) and kept live's
`syndicate/features/shared/layer2_board.py` (the CALLEE):

    layer2_shortlist.py:241  build_layer2_rows(grid, openings=openings_index)
    layer2_board.py:824      def build_layer2_rows(grid)          <- no openings

**A file-level diff cannot see this.** I verified content by blob, ancestry
(`merge-base --is-ancestor`), absence of `render.yaml`, and that the delta was
- *Full working in `learnings_evidence.md` under this heading.*

## 2026-08-16 — FORBIDDEN: computing a RATE or a COUNT from `scripts/render_logs.py`

I nearly filed a false regression against my own `#441` fix. One `NFL_PBP` line
appeared in 14 minutes against a 60s throttle, which reads as "evaluated once,
still starved". It was the instrument. Measured coverage for REQUESTED windows:

| requested | actually covered | matches |
|---|---|---|
| 3 min | **0.23 s** | 8 |
| 3 min | 2m12s | 6 |
| 3 min | **nothing** | 0 |
- *Full working in `learnings_evidence.md` under this heading.*

## 2026-08-16 - FORBIDDEN: never join a CHANGE metric on a key that contains the changing fields. The metric becomes conditioned on the absence of what it measures.

Shipped movement detection joined on `clv_opening_ledger._opening_key`, which
includes `line` and `bookmaker`. That key is CORRECT for settlement -- it must
not collapse home -1.5 with home -2.5, nor two books' prices. It is fatal for
movement, because **movement IS the detection of line and book change**: a row
could only match its own opening if it had not moved.

MEASURED, two served artifacts 20 minutes apart:

    stable key (event·market·player·segment·side) matched   20
    full key   (+ line + bookmaker)               matched   14
- *Full working in `learnings_evidence.md` under this heading.*

## 2026-08-16 - a blob hash written into a ledger is a SNAPSHOT, not a lease.

Recorded a pending ridealong naming exact blob hashes so the next deployer could
not get it wrong. Within the hour `08de8c08` moved two of those blobs, and the
ledger entry -- written precisely to be unambiguous -- would have shipped the
compat guard WITHOUT the movement fix that makes it worth having.

Superseded the entry rather than editing it, so the stale one stays readable and
nobody wonders which was current, and the new one instructs the reader to
**re-read the blobs before cutting rather than trusting the numbers printed in
it**.
- *Full working in `learnings_evidence.md` under this heading.*

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
- *Full working in `learnings_evidence.md` under this heading.*

## 2026-08-16 - a test I wrote can encode the belief that production later disproves, and then it defends the bug.

Two tests written at 21:4xZ asserted a -27 point price delta across a line that
moved -1.5 -> -2.5, and a steam flag on the strength of it. Both passed. Both
were **wrong in exactly the way production proved an hour later** -- that delta
compares different bets.

When the gate landed, those two tests failed. The instinct a failing test creates
is "the change broke something"; here the change had **fixed** something and the
tests were the residue of the wrong belief.

**The rule:** when a fix makes your own tests fail, check whether the test
- *Full working in `learnings_evidence.md` under this heading.*

## 2026-08-16 — SCOPE NOTE on "blob-staging needs `--path`": true in general, WRONG for this repo

`dea23cc8` records that `git hash-object -w <file>` skips the clean filter unless
given `--path`, so blob-staging can commit un-normalised content. Correct as a
git fact. Applied to this repo it would cause the damage it warns about.

Measured 2026-08-16 against `origin/main`: **this repo stores CRLF throughout** —
`app.py`, `scripts/migration_gate.py`, `tests/test_archives.py`, and
`scripts/ui_layout_probe.py` at `f55b8e7c` before anyone touched it (1011/1011
CRLF). `.gitattributes` scopes `eol=lf` to `.claude/hooks/*` **only**, and says in
its own comment: *"this repo has no line-ending policy and setting one repo-wide
- *Full working in `learnings_evidence.md` under this heading.*

## 2026-08-16 - FORBIDDEN: a verifier that cannot FAIL cannot PASS. State the denominator every assertion needs, or it will report an empty population as success.

Third instrument of mine in one evening to map a benign state onto the wrong
branch, and this one is the worst because it produced a confident PASS on a
question that had not been asked.

Verifying the line gate, the harness printed:

    tracked 2 · moved-line 0
    PRICE DELTA LEAKED ACROSS A MOVED LINE : 0   (was 19 -- must be 0)
    VERDICT: PASS

**There were ZERO moved-line rows.** `PASS if not leaked and not bad_steam` is
- *Full working in `learnings_evidence.md` under this heading.*

## 2026-08-16 — FORBIDDEN: reading `$?` after a pipeline. TWICE IN ONE HOUR, two different tools, both times the wrong answer was the REASSURING one

`$?` after `cmd | filter` is the FILTER's status. Both instances reported success.

1. **pytest.** `py -3 -m pytest ... | tail` reported exit 0 on a run that was
   **6 failed / 245 passed**. I nearly wrote "tests pass" into a checkpoint.
2. **deploy_preflight, within the hour, after banking rule 1.** A watcher built as
   `OUT=$(preflight ... | tr -d '\r'); CODE=$?` read `tr`'s 0 and printed
   **`CLEAR`** on its first tick — while the log line beside it said
   `jobs=3 claim=grading-blocker-settled-zero`. The real exit was **3 (CLAIMED)**.
   Acting on it would have killed a running `build_soccer_artifacts.py` job, i.e.
- *Full working in `learnings_evidence.md` under this heading.*

### 2026-08-16 — AN ISOLATED-INDEX COMMIT IS PROTECTED FROM THE SHARED INDEX AND NOT FROM A HEAD MOVE. Mine was orphaned within minutes, and so was another lane's

**The documented recipe protects your commit's CONTENT from other sessions'
staged junk. It does nothing to protect its REACHABILITY.** I committed
`87ffffd2` through `GIT_INDEX_FILE` with every guard this file prescribes —
2 files, 0 deletions, asserted in the same shell, shared index repaired
afterwards. Minutes later `git merge-base --is-ancestor 87ffffd2 HEAD` returned
FALSE: another session had moved local `main` to `1508c463`, which does not
descend from it (reflog `HEAD@{0}`, empty message — a reset or checkout, not a
commit). No ref reached it, `git branch -a --contains` was empty, and it was not
- *Full working in `learnings_evidence.md` under this heading.*

### 2026-08-16 — A COLLISION CHECK IS A READING WITH A TIMESTAMP, NOT A FACT. A lane was re-opened between my check and my edit

At `/lane open` the header for `mlb-live-gameline-distributions` read
`CLOSED-VERIFIED 2026-08-16 22:2xZ`, so I recorded its claim on
`vendor/.../flask_frontend.py` as released and wrote that into my lane block.
Between that read and the edit, the holding session **re-opened it** (`12bba949`
— *"the line-gate PASS was a pass on an empty population; a verifier that cannot
fail cannot pass"*). `lane-guard` blocked the edit and **the guard was right**.

- **The rule going forward:** re-run the collision check **immediately before
  the edit**, not only at lane open. A CLOSED lane can re-open — closure is
- *Full working in `learnings_evidence.md` under this heading.*

### 2026-08-16 — `commit-guard`'s suggested fix list was INCOMPLETE on all THREE occurrences in one session

Already recorded as a hazard; this is the evidence that it is the norm, not the
exception. Omitted: `.syndicate/scheduled_task_ncaaf_445.md` (0/-58) on the
first block, and `.syndicate/deploys.md` (0/-66) on the second.

- **The rule going forward:** after running the guard's `git restore --staged`
  line, **re-print the WHOLE index and audit every remaining path yourself** —
  for each, is it on disk, and is it in HEAD? `absent on disk + in HEAD` is a
  legitimate deletion (leave it — `scheduled_task_ncaaf_445.md` was one);
  `present on disk + in HEAD + staged as deleting lines` is a stale-index revert
- *Full working in `learnings_evidence.md` under this heading.*

## 2026-08-16 — OVERRIDE, LOGGED: an unattended session was authorised by the user to fire this deploy

The FORBIDDEN entry above ("never let an UNATTENDED session fire a deploy") was
raised to the user twice with its reasoning — the same-day `wnba-win-prob-counter-read`
incident, the absent structural control, and the tell that `send_message` is
unavailable in unattended runs so the session that most needs to coordinate cannot.
The user chose it deliberately, in these words: **"fire it"**, after being offered
the alternative of running `.syndicate/handoff_deploy_freeze_reader_tree.md` from
their own attended window.

**Scope of the override:** deploy `_freeze_market_dirs` (blob `426bbd70`, on
- *Full working in `learnings_evidence.md` under this heading.*

## 2026-08-16 — CORRECTION: the shared index CHURNS, it does not accumulate — and staged content is not the alarm

I recorded the shared index earlier the same day as a landmine "growing" on a
timer: 725 staged ledger deletions, then 1127 half an hour later, with the
inference that its blast radius increases the longer it sits.

Measured a third time minutes after that: **207 deletions across four DIFFERENT
files.** `deploys.md` and `lanes.md` had left the staged set entirely, and local
`HEAD` had moved twice in between. The staged set is simply whatever the
currently-active sessions are holding at that instant. The 725 -> 1127 reading
was two samples of a churning quantity, and I turned it into a trend.
- *Full working in `learnings_evidence.md` under this heading.*

### 2026-08-16 — a stale-copy commit can keep the DOC and drop the CODE, and every cheap check still passes
- **Extends the same-day rule about slug-level ledger checks.** That one framed
  whole-file rewrites from stale in-memory copies as a `.syndicate/**` hazard.
  Measured three hours later: the same mechanism reverted a **source file**.
- **What it looked like.** HEAD `fedd17ee` carried `scripts/render_events.py`,
  `#442` and `#444` in `todo.md` — but not the `_deploy_trigger` fix that `#444`
  was *found by*, and not its two regression tests (12 test functions in HEAD, 14
  on disk). A session had committed `todo.md` from a copy containing my entry
  and `render_events.py` from a copy predating my edit to it.
- *Full working in `learnings_evidence.md` under this heading.*

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

### 2026-08-16 — A PLAN'S FIELD LIST WRITTEN FROM GREPS WAS WRONG FOR ALL FOUR SPORTS. Greps find NAMES; only the payload has the data

`plan_2026-08-16_state_conditional_learning.md` promised, per sport, a concrete
field list. Measured against real artifacts, **it was wrong every single time,
and wrong in a DIFFERENT direction each time** — which is why "check the plan
against reality" cannot be a one-off:

| sport | the plan said | measured |
|---|---|---|
| MLB | build a state vector | it **already existed** in full (`LiveSituation`) and was discarded — serialisation, not derivation |
| WNBA | "needs a possession count" | possessions are **underivable** — no FGA/TOV/OREB/FTA anywhere |
- *Full working in `learnings_evidence.md` under this heading.*

### 2026-08-16 — STATE THAT EMBEDS THE MODEL'S OWN OUTPUT MAKES CONDITIONING CIRCULAR. Soccer is the only sport here that does it

`soccer/ingestion/espn_live_state.py`'s record carries a `projection` block
(`home_win_probability`, `projected_final_total`) and `goal_windows` inline,
alongside the real state. Folding those into a game-shape record would mean
scoring the model's error against a variable that CONTAINS the model.

- **The rule going forward:** a conditioning variable must be derivable from
  observable state ALONE. When a payload mixes state and prediction, split them
  explicitly and say so on the record. **The test for this is cheap and
  worth writing:** assert the model's field names are absent from the shape.
- *Full working in `learnings_evidence.md` under this heading.*

### 2026-08-16 — A RESERVATION IS A READING WITH A TIMESTAMP. Three different kinds went stale in ONE session

Already recorded for lane claims. It happened in **three distinct systems**
within a few hours, which makes it a general property of this worktree, not a
lane-file quirk:

1. **Lane claim** — `mlb-live-gameline-distributions` read `CLOSED-VERIFIED` at
   lane open and was re-opened before my edit. `lane-guard` was right.
2. **Shared git index** — held revert-shaped entries against a HEAD that had
   moved; `commit-guard` blocked twice and its fix list was incomplete BOTH
   times.
- *Full working in `learnings_evidence.md` under this heading.*

### 2026-08-16 — A DIRECTORY NAMED `pbp` CAN CONTAIN MODELS, NOT PLAY-BY-PLAY

`vendor/wnba_betting_repo/models/pbp/` holds `.joblib`/`.onnx` files
(`early_threes_gbr`, `first_basket_lr`, `tip_winner_lr`) — artefacts TRAINED
from pbp. A coverage census by path would have counted WNBA twice and, worse,
would have reported coverage for a sport on the strength of a filename.

- **The rule going forward:** a coverage census must open a file and check its
  SHAPE, not match its path. The same pass corrected "we have pbp for every
  sport" to **5 of 8** (`#454`) — and the three without it (soccer, NHL, NCAAB)
  are the same three modules that are weakest everywhere else, which is a
- *Full working in `learnings_evidence.md` under this heading.*

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

### 2026-08-16 — A KEY NAME THAT MATCHES ANOTHER SPORT'S CONTRACT IS NOT A CONTRACT. WNBA publishes `run_margin_dist` and `total_runs_dist` — the exact keys MLB prices from — carrying a three-point quantile summary MLB's reader cannot parse, and the failure is SILENT
- **The rule going forward:** before wiring a producer to a consumer on the
  strength of a matching key name, **read the VALUE's shape, not the key**.
  `vendor/wnba_betting_repo/app.py:7477-7478` emits `score.total_q` /
  `score.margin_q` under MLB's key names. `_quantiles` returns
  `{"p10": -8.0, "p50": 1.5, "p90": 11.0}`. MLB's `_dist_prob_over` iterates the
  dict treating each KEY as an outcome value and each VALUE as a count, so
  `float("p10")` raises, the entry is skipped, `total` stays 0, and it returns
  `None`. **A board that stays exactly as blank as before, with nothing saying
- *Full working in `learnings_evidence.md` under this heading.*

### 2026-08-16 — "THE ONLY OPEN WORK IS VERIFICATION" WAS FALSE, AND A CONTENT CENSUS ACROSS ALL THREE SERVICES IS WHAT CAUGHT IT
- **The rule going forward:** when a lane claims its code work is done and only
  verification remains, **count the defect by content at EVERY live service SHA
  before believing it.** `clamp-fix-to-workers` read that way for a day; the
  census found web 0, refresh-worker 0, **live-odds-worker 2** — one of them
  reachable (`_american_from_prob` → `home_ml`/`away_ml` on the WNBA cards that
  service publishes). A per-service census is three commands and it converts
  "should be fine" into a number.
- **And the second half:** the site that was dormant was dormant only because
- *Full working in `learnings_evidence.md` under this heading.*

### 2026-08-16 — RE-READ THE LIVE SHA IMMEDIATELY BEFORE CUTTING, NOT WHEN YOU DECIDED TO
- **The rule going forward:** the gap between "I measured the live SHA" and "I
  cut a branch on it" is where another session deploys. Authorised to ship the
  deferred clamp fix to live-odds-worker, I re-read the SHA first and found it
  had moved `16a898ef` → `c348da53` five minutes earlier, with the work already
  in it. **Cutting on the stale SHA would have re-applied a change that was
  already live.** Same session, the reverse case also bit: a `git commit` was
  refused because HEAD moved mid-sequence.
- *(evidence: `.syndicate/deploys.md`, clamp closure)*

## 2026-08-16 — FORBIDDEN: attributing an excursion with a field that is not THREAD-scoped. A process-global "last stage" names the last thread to speak, not the one allocating.

I spent an hour localizing a 2.4GB excursion to `_build_sport_overview` on the
strength of `MEMORY_WATCHDOG`'s `last_stage=board_contract_end`, wrote it into
`deploys.md` as a VERDICT twice, and designed a mitigation around it.

`_WATCHDOG_STATE` (`memory_observability.py:774`) is a module-level dict with no
thread-locals. refresh-worker runs several concurrent daemon threads
(`live_lens_loop.py:914` and `:814`, `run_refresh_worker.py:3498`). So
`last_stage` records **whichever thread most recently emitted a marker**, which
need not be — and here was not — the thread allocating.
- *Full working in `learnings_evidence.md` under this heading.*

### 2026-08-16 — A "NEVER DEFAULTS" TEST THAT ONLY EXERCISES GUARD CLAUSES IS VACUOUS. Three times in one session

Each time the pattern was identical: assert that a lookup does not fall back to a
permissive value, using inputs rejected BEFORE the fallback is reached. The test
passes against the broken implementation.

1. `wnba_pbp_possessions.team_possessions` — removing `home`/`away` from the key
   filter changed nothing, because the `poss_est <= 0` check already dropped them
   on real data.
2. `wnba/cards.py:_has_pbp_signal` — the same vacuity, reintroduced hours after
   fixing the first.
- *Full working in `learnings_evidence.md` under this heading.*

### 2026-08-16 — A RESIDUAL THAT CORRELATES WITH THE FITTED VALUE MEANS THE MODEL IS WRONG, NOT THE DATA

Comparing a freshly built RE24 table to published values under an ADDITIVE offset
gave 0.53 runs of post-offset scatter and a "does not reproduce" verdict — i.e. a
broken join. The residuals were strongly negative on low-RE cells and positive on
high-RE ones. That is a scale factor, not a shift: an environment 14.6% livelier
lifts a 2.3-run cell by 0.34 and a 0.10-run cell by 0.015, and no constant fits
both. Under a multiplicative fit the same data landed 21 of 23 cells inside 3 SE.

- **The rule going forward:** before concluding the DATA is wrong, scan the
  residual against the fitted value. Structure there indicts the model.
- *Full working in `learnings_evidence.md` under this heading.*

### 2026-08-16 — SAMPLE SIZE CHOOSES THE METHOD. An empirical win-expectancy table was refused at 4 observations per cell

Counting win rates per (inning, half, base-out, score band) over 47 dates gives
4,039 occupied cells, **median 4 observations**, 68.7% below 10, zero at 1,000+.
The composition route — estimating P(k runs | base-out state) at ~2,200
observations per state and convolving — answers the same question from the same
corpus.

- **The rule going forward:** when a table is too thin, the answer is usually a
  different ESTIMATOR over the same data, not more data and not a published
  number copied in. Compute the per-cell n BEFORE choosing the method.

### 2026-08-16 — AN ARCHIVED SESSION IS NOT AN ABANDONED LANE. The lineage forks forward

`wnba-live-tier`'s holder (`Layer 1 board coverage audit (fork 2)`) was archived,
and I was about to declare the lane orphaned and take a claim override — there is
precedent in this file for exactly that. The roster showed fork 2 -> fork 3 (also
archived) -> **fork 4, running**. The lane was actively held.

- **The rule going forward:** before calling a lane orphaned, list sessions with
  `include_archived: true` and look for a SUCCESSOR BY TITLE, not only for the
  session named in the lane. Archived means that session ended, not that the work
  stopped.

### 2026-08-17 — A DEPLOY BRANCH THAT NEVER GOES BACK TO `main` IS A REGRESSION WAITING FOR THE NEXT DEPLOY. Three commits ran in production for an hour while `main` did not have them
- **The rule going forward:** cutting a deploy branch on the LIVE SHA is correct
  and this session did it six times. **The other half is pushing the same commit
  to `main`, and it is easy to skip because production already works.** Measured
  at checkpoint: `live_gameline_score.py`'s two join fixes and the
  `blueprints/intelligence.py` reader line were live on refresh-worker and web
  and **absent from `origin/main`** — the next deploy cut from main would have
  silently reverted all three, and the symptom would have been the scorer
  reporting zero again with no code change to blame.
- **How to check, in one command per file:** `git show origin/main:<file> | grep
  -c <marker>` against the deployed SHA's count. Ancestry is the wrong test —
  these were cherry-picks, so their SHAs never appear on main at all.
- *(evidence: `.syndicate/log/2026-08-16.md`, this session's closing block)*

### 2026-08-17 — `a or b` IS NOT A FALLBACK WHEN `a` IS RELIABLY PRESENT AND RELIABLY WRONG
- **The rule going forward:** to try several keys against an index, **try each
  against the index** — `next(k for k in candidates if k in index)` — never
  `a or b`, which picks the first TRUTHY value and then fails the lookup.
  Measured: ledger records are written while a game is LIVE so they always carry
  `game_pk`; a row that has since gone FINAL carries no `live_gameline` and is
  indexed under `event_id` only. `game_pk or event_id` therefore chose the one
  key the index never held, on all 3,727 records, while the key that WAS there
  was never tried. **The first fix widened the INDEX and the bug survived,
  because the defect was in the LOOKUP.**
- *(evidence: `.syndicate/log/2026-08-16.md`)*

## 2026-08-16 — FORBIDDEN: instrumenting a WRAPPER when the hot path has siblings that reach the same work directly. Twice in one night.

Both instruments I placed on a caller measured my route instead of the work.

1. `board_contract_end` went on the shared builder only after `last_stage` —
   a PROCESS-GLOBAL field — was read as if it were thread-scoped.
2. `LEDGER_LOAD` went on `recommendation_engine._load_records_from_ledger`.
   Production returned `records=0 anon_delta_mb=0.2
   path=evaluation_ledger.jsonl`: that wrapper defaults to
   `DEFAULT_EVALUATION_LEDGER`, a FLAT path that does not exist, while the 830MB
   chunked load reaches `_iter_record_payloads` through
- *Full working in `learnings_evidence.md` under this heading.*

### And the second-order error, which was worse

My watcher auto-scored that `records=0` reading as **"VERDICT: KILLED — this load
is not the allocator"**. A 0.2MB delta on a load that returned ZERO records is a
NULL measurement. That is `learnings.md`'s own "never record a detector's zero as
a pass when the data gave it no chance to fire" — committed by the instrument I
built to avoid exactly that class of error, and I nearly reported it.

**Rule: any automated verdict must carry the denominator that makes it
readable.** The fix was to make `records` travel WITH the delta in the log line,
and to make the watcher refuse to score any load with `records < 1000`, printing
"NO VERDICT YET" instead. A threshold on the measured quantity alone will always
eventually fire on an empty sample.

### 2026-08-16 — SCOPING A DEPLOY WHEN `main` CARRIES OTHER LANES' WORK: parent on the LIVE SHA, not on `main`

`origin/main` had **14 pending code commits from six lanes** — a versioned-profile
seam across all three sim engines, four live-gameline-score changes, an
intelligence-evaluation trace. Deploying main would have shipped every one of
them on its FIRST ever deployment, alongside two unrelated fixes, into a
stop-then-start on a disk-backed service. If anything broke, attribution would
have been impossible.

- **The rule going forward — the recipe, because it worked and is reusable:**
  1. Read the **LIVE** SHA from the service, not from `state.md` (it had moved
- *Full working in `learnings_evidence.md` under this heading.*

### 2026-08-16 — A RESTART CONFOUNDS ANY FIX WHOSE CLAIM IS ABOUT STATE PERSISTING

`#455`'s claim is that a stale all-null snapshot was STICKY — served in
preference to real data all day once persisted. After the deploy, `generated_at`
read current where it had been frozen three hours, and that looks exactly like
the fix working.

**It is not evidence.** The deploy restarts the service, which clears the
replayed snapshot on its own. The convenient reading and the null hypothesis
predict the identical observation.

- **The rule going forward:** when a fix's claim is about state PERSISTING —
- *Full working in `learnings_evidence.md` under this heading.*

## 2026-08-17 — RULE: the em-dash in a lane header is SYNTAX, not punctuation. A hyphen header is an UNGUARDED lane

**Evidence.** `wnba-fixture-identity` was opened by a live session with ASCII
hyphens: `### wnba-fixture-identity - OPEN - **...`. `lane-guard.py` parses
`^###\s+(\S+)\s+—\s*([^—]*)` and requires U+2014, so the header did not parse at
all. Consequences, all silent: the lane's three claimed files were unguarded
(one of them contended with a lane closed minutes earlier), and the
session-start digest did not list the lane as OPEN, so an arriving session saw
no claim on those paths. Found 2026-08-17 12:3x CDT by the `ledger-sweep`
lane while verifying something else; the hook had been printing
`(1 lane header(s) have no parseable status and are NOT guarded)` and nobody
had read it as naming a specific live lane.

**Why it keeps happening.** Both hooks fail OPEN by design — a broken guard that
blocks all edits is worse than no guard. That is the right default and it is
also why a malformed header is invisible: it does not warn its owner, it just
stops protecting them. **Unparseable input lands on the permissive branch.**

**How to apply.**
- Copy an existing header when opening a lane; do not retype the separators.
- After `/lane open`, run `bash .claude/hooks/session-start.sh | grep -i guarded`
  and confirm your lane appears under OPEN LANES. Presence in `lanes.md` is not
  evidence of enforcement — *parseability* is.
- When a guard reports a count of unparseable/skipped items, resolve WHICH ones.
  A count is not a finding until it is a name.

**Related:** the same shape is already recorded twice — a guard that maps absent
onto its permissive branch turns a failed join into a relaxed rule with no
reason emitted, and `_is_disclaimer` had to be added to this same file after a
regex read "NOT claimed, deliberately" as a claim.

## 2026-08-17 — FORBIDDEN: diagnosing from FILTERED log projections. Six wrong attributions, one question, and the answer was in the lines I was truncating.

I spent a night attributing a memory excursion, wrong six times. Every
investigation used `text=` greps for markers I ALREADY SUSPECTED, windows with
`MEMORY_WATCHDOG`/`CONTAINER_MEMORY` stripped as "instrument noise", owner-
classified COUNTS instead of content, and messages cut at 78-130 characters.

The user asked: **"have you read the actual render logs line by line?"** I had
not. One unfiltered window immediately produced fields I had never seen —
`region_count` (366 -> 367, a NEW mapping appearing), `reconciles: true` (the
SMAPS data self-reconciles, which I had been hedging about),
`performance_publish_count=22078` against `recommendation_count=60`, and
`sample_size=0`. I had been quoting that last line TRUNCATED AT `"samp` for
hours.

**Each filter encoded the hypothesis I was trying to test.** A `text=` query
returns only what I already believed mattered; stripping the memory lines
removed the only rows carrying `seconds_since_stage` and `climb_mb_per_s`;
truncation hid the discriminating field. The phantom "third ledger pass" was a
filtered window that began mid-scan and invented a caller that never existed.

**The rule: on an unexplained symptom, read one FULL window — no `text=` filter,
no dropped line types, no truncation — BEFORE forming the hypothesis.** Filter
afterwards to confirm, never to discover. If the window comes back at the row
cap, narrow the time range until it is under the cap; do not narrow by content.

**Corollary that actually solved it:** when the logs cannot distinguish an
excursion from a quiet window — measured: zero stage markers in 16s, pull
activity 1/7 vs 1/6 across arms, thread activity IDENTICAL between excursion and
control, two excursions producing 6-8 rows that were ALL the watchdog's own —
then log correlation is EXHAUSTED and no further study of it will help. Reach
for something that does not require the code to volunteer a line:
`faulthandler.dump_traceback(all_threads=True)` named the allocator in one
excursion after six failed attributions.


## 2026-08-17 — RULE: committing through an ISOLATED index ARMS the shared index with a revert of that commit. Disarm after, not just before

**The recipe is still right; it has a second half nobody had written down.**
Committing via `GIT_INDEX_FILE` protects a peer's staged work from being swept
into your commit. But the shared index was populated from the OLD `HEAD`, so
the moment your commit moves `HEAD`, every path you just committed is staged in
the shared index **at its pre-commit content**. `git diff --cached` then reads
as the exact inverse of what you shipped:

    0    786   .syndicate/deploys.md          <- 786 deletions, seconds after
    657  1288  .syndicate/lanes.md               committing 786 insertions

A bare `git commit` by any of the other sessions would have reverted the whole
sweep, with a clean worktree and nothing visibly wrong. This is the same
mechanism recorded four times before, except **this time the session that armed
it was the one that had just spent an hour disarming it** — I disarmed a
1,110-line revert-in-waiting on `lanes.md` before committing, then created a
seven-file one by committing.

**How to apply.** After ANY isolated-index commit, path-scope-reset the same
paths in the shared index and re-read it:

```
git reset -q -- <the exact paths you committed>
git diff --cached --numstat          # must show only OTHER lanes' work
```

`git reset -- <path>` resets that path's index entry to `HEAD` and **touches no
file**, so it cannot lose worktree content. Leave every path you did not commit
alone — another lane's staged adds are theirs.

**The generalisation, which is the part worth keeping:** the shared index is
state shared between processes with no lock and no notification, and `HEAD`
moving under it silently changes what it MEANS. It is never enough to check it
before an operation; anything that moves `HEAD` invalidates the check. Read
`git diff --cached --numstat` **after** you commit, not only before.

**Related:** [stale shared index holds a revert], [never chain add and commit],
[blob-stage against HEAD].

## 2026-08-17 — OVERTURNED: "a statistical win on a sim parameter can be graded by betting hit rate on the same sample"

**Belief going in:** the overrides file records `starter_tto_quality_scaling`
being reverted because it won statistically and lost money, so the correct gate
on any sim-parameter change is a betting hit rate. I built that gate.

**What actually happened:** the gate could not discriminate, and it pointed the
wrong way. On 148 graded starts the leash grid read 53.38% → 59.46% hit rate and
+1.93% → +12.40% ROI, apparently reversing a clean statistical sweep. Three
checks killed it:

- **ALWAYS OVER returned 58.78% / +8.16% on the identical rows, with no model.**
  The best grid point was barely above a side-blind strategy, and the longest
  leash scored EXACTLY 58.78% because it picked over on 146 of 148 — it *was*
  always-over.
- The grid varied the **over-rate** monotonically (106 → 146 over-picks), so the
  ordering followed from over-propensity in a window where overs won 58.78%.
- The whole spread was **1.49 SE** (SE 4.09pp at n=148).

**The trap, and it is the general form:** the parameter under test *shifts the
mean of the projection*, which *shifts which side gets bet*. Any outcome window
with a directional base rate then scores the parameter by its directional bias
rather than its accuracy. Here that meant the grade would have **ENDORSED THE
DEFECT** — the sim over-projects outs, so it bets over, and overs won.

**RULE: never report a prop betting hit rate without the side-blind baseline
(ALWAYS OVER / ALWAYS UNDER) computed on the same rows.** Without it a +12.40%
"model edge" read as skill when +8.16% of it needed no model at all. A grade whose
picks are not side-balanced is measuring direction, not skill.

**Corollary, learned the same day:** a betting gate is not automatically stronger
evidence than a statistical one just because it is denominated in money. It has
its own confounds, and n is usually far smaller — 148 bets against 3,226 scored
projections.

## 2026-08-17 — RULE: before building a fix, check whether it was already considered and REJECTED in the code you are about to edit

**What happened.** Asked to namespace the shared cadence marker — a real defect,
correctly diagnosed, with a live production symptom. I opened the file to write
it and found the authoring lane had rejected exactly that fix **hours earlier, in
the docstring of the function I was about to change**:

> "This deliberately does NOT namespace the cadence marker. That would treat the
> symptom and leave an ungated sweep running on the wrong service; the ownership
> flags are the intended mutex and they are already correct."

**Why building it would have been actively harmful, not merely redundant.** The
shared marker is what currently prevents two services sweeping the same sport.
Namespacing it *without* the ownership gate deployed would have let refresh-worker
and live-odds-worker sweep MLB on independent clocks — **doubling** MLB OddsAPI
calls against a cap at ~62.7% with MLB already 93% of spend. The safe ordering is
the exact reverse of the request: deploy the gate, and then the marker never
matters.

**The generalisable part.** A defect being real does not make the obvious fix
right, and a rejected design usually leaves its reason near the code rather than
in the ledger — `grep` over `lanes.md` found nothing, because the decision lived
in a docstring. **Read the function you are about to edit before you edit it, and
read it for prior decisions and not only for mechanism.**

**Second-order:** the fix that WAS correct (`20025cc4`) turned out to be on `main`
and deployed nowhere — measured by CONTENT against each service's live SHA. The
real blocker was never missing code; it was an undeployed fix that everyone,
including me, assumed was live because it was merged. *Merged is not deployed*
already has a rule here; this is its fourth instance.

### 2026-08-17 — A GUARD'S ESCAPE HATCH MUST BE REACHABLE FROM WHERE THE GUARD RUNS, and a PreToolUse hook runs BEFORE the shell

- **What we believed:** `commit-guard.py` had three documented overrides —
  `GIT_INDEX_FILE`, `SYNDICATE_ALLOW_STAGED_DELETES`,
  `SYNDICATE_ALLOW_STAGED_REVERTS` — printed in its own refusal message as shell
  assignments. They were written down, tested, and reviewed twice.
- **What is actually true:** none of them could ever fire from a Bash call. All
  three were `os.environ.get(...)`, the HOOK's process env, while every
  documented spelling (`export VAR=…`, `VAR=1 git commit …`) lives in a command
  string the hook gates and therefore runs AFTER it. A session that did exactly
  what the refusal message instructed was refused again, by the same guard, over
  the same stale blob it could not clear without disturbing another session.
- **The rule going forward:** **an override is not an override until it has been
  exercised through the real entry point.** For a hook, that means over stdin as
  a payload — not by setting the variable in the test process, which is a
  different environment than any user of the documented recipe will ever have.
  Corollary: the test that would have caught this is the one that runs the
  guard's own printed text verbatim. If a tool prints instructions, those
  instructions are an interface and belong in the suite.
- **Second thing this cost:** the printed recipe also told sessions to use
  `GIT_INDEX_FILE=$(mktemp -u /tmp/idx.XXXX)`, which the 2026-08-15 FORBIDDEN
  entry in this file rules out (per-shell value; an absent index file is an
  EMPTY one). **The guard was printing an instruction this ledger forbids**, and
  had been since it was written. A message is not documentation-adjacent; it is
  the thing people actually follow.
- *(evidence: `5fb52342`; lane `commit-guard-blind-to-own-recipe`; 19 cases run
  through the pre-fix and post-fix guards together)*

### 2026-08-17 — "IT MATCHES NO SESSION IN THE ROSTER" IS NOT "IT POINTS AT NOBODY". One session has two ids, and the register holds the one you cannot look up

- **What I believed, and reported to the coordinator as a defect:**
  `.syndicate/coordinator.id` was stale. `get_session` on it returned "not
  found"; no roster entry matched in bare or `local_`-prefixed form with
  `include_archived` on. I identified the coordinator by title instead and told
  them their register pointed at nobody.
- **What is actually true:** every observation was correct and the conclusion
  was wrong. **A session has two ids** — one in the hook payload and the
  scratchpad path (`9ed7fd89-…`), one in `list_sessions` (`local_1d6f136e-…`).
  `.claude/hooks/deploy-guard.py:130-140` compares the register to
  `payload["session_id"]`, so it MUST hold the payload form, which is precisely
  the form the roster cannot see. `if not coordinator: return 0` — deleting the
  file is the documented off switch, so acting on "stale" stands the whole
  deploy-ownership role down.
- **The rule going forward:** **before calling a register stale, find the reader
  and see which id it compares.** The authority on an identifier's meaning is
  the code that consumes it, never the directory you happened to query. A lookup
  failure tells you about the LOOKUP's namespace, not about the referent — the
  same shape as [[absence in a window isn't absence]].
- **Why this is filed rather than shrugged off:** **two sessions reached this
  conclusion independently on the same day**, and one of them pushed it to
  `origin/main` — `52d45b10` writes "coordinator.id IS STALE" into `deploys.md`,
  where it now sits as a falsified ledger entry next to an instruction to delete
  the file. Neither of us deleted it; both were one step away. A wrong inference
  that two people reach separately is a property of the evidence, not of either
  reader, and the fix has to live where the evidence is — hence the comment now
  at `deploy-guard.py:68-79` and the verification recipe in `coordinator.md`.
- *(evidence: `deploy-guard.py:130-140` read directly; `52d45b10`; the
  coordinator's own dual-id measurement)*

## 2026-08-17 — RULE: score a DISTRIBUTIONAL forecast with a distributional baseline. A point test on a distribution is the wrong instrument, even when it agrees.

**What happened.** Phase 7's whole purpose was to build a proper scoring rule for
projections (CRPS, bias/dispersion). I built it, used it to find a real defect —
the MLB F5 starter leash, dispersion 1.002 vs a 0.7979 target — and then decided
whether the model had SKILL by comparing its **mean absolute error to a constant
point prediction**. That verdict went into `state.md`.

**Why that is wrong even though the conclusion survived.** A constant has no
distribution; it cannot price `P(outs > 17.5)`, which is the only thing a prop
model is for. And MAE is blind to calibration and sharpness — precisely the axis
on which the sweep's headline result moved. The instrument I reached for could
not see the finding I had just made with the other one.

**The corrected test, and it came out HARDER.** CRPS skill vs climatology (the
marginal empirical distribution): **−8.97% at the best leash value, −14.52% at
production's.** Negative skill everywhere. The model prices these starts worse
than the league-wide distribution of outs does. Shortening the leash reduces the
damage and does not make it positive.

**The generalisable rule.** Match the baseline's FORM to the forecast's form:
- point forecast -> compare to the climatological mean (MAE/RMSE)
- **distributional forecast -> compare to CLIMATOLOGY, with CRPS**
- probability forecast -> compare to the base rate, with Brier, **and to the
  market** where one exists

**And the trap that makes this easy to miss: my wrong test AGREED with the right
one.** Both said "loses to baseline". A confirming answer from the wrong
instrument feels like evidence and is not — had the leash genuinely carried
distributional skill, MAE-vs-constant would have hidden it and the model would
have been written off on a metric that could not see its value. This is the
`#428` lesson recurring: *"'No measured skill' would have been the WRONG
conclusion and would have suppressed a model that needs calibrating rather than
retiring."*

**Corollary already biting:** the replay ran at 100 sims/game against production's
1000, and a thin empirical PMF inflates CRPS. A distributional metric is
sensitive to the ESTIMATOR of the distribution, not only to the distribution —
so sim count is part of the measurement, not just part of the model.

## 2026-08-17 — RULE: a LEAKED backtest number is an UPPER BOUND, not merely an untrustworthy one

**Standing practice here is to mark a leaky backtest "not citable" and stop.**
`plan_2026-08-14_models.md` D1 did exactly that for the soccer validation CSVs.
That is right as far as it goes and it throws away information.

**A forecast that saw its own outcome should FLATTER itself.** So the leaked
number bounds the honest one from above:

    true out-of-sample skill  <=  leaked in-sample skill

**Measured today on NCAAF** (`rating_source=cfbd_ppa_season_2025` predicting
season-2025 games, `generated_at` 2026-07-16, 761 of 761 rows):

    margin  +1.72%  [+0.20%, +3.24%]   -> true skill is AT BEST +1.72%
    total   -3.65%  [-6.94%, -0.36%]   -> true skill is AT BEST -3.65%

So NCAAF total is **known to be bad** without any clean data at all, and NCAAF
margin is **known not to be good** — plausibly zero. "Not citable" would have
recorded both as unknown, and they are not unknown; they are bounded.

**How to apply.** When a leak is found: (a) refuse to call it skill, (b) still
compute it, (c) report it as a CEILING with the direction of the bias stated. A
leaked number that is already weak is a strong negative result. A leaked number
that is strong tells you nothing and must wait for clean data.

**The corollary that decides what to do next.** Do not repair a leak by
regenerating history with a better rating source — that just moves the leak
somewhere harder to see. Score FORWARD instead. NCAAF's 2026 projections already
carry the correct pattern (`cfbd_ppa_season_2025_fallback_for_2026`, prior-season
ratings), the season opens 2026-08-29, and 761 projections are written and
waiting for outcomes. The clean measurement costs nothing but time.

Related: `learnings.md` 2026-08-17 on matching the baseline's FORM to the
forecast's form. Both are the same underlying discipline — say precisely what a
number can and cannot support, rather than binning it as good or unusable.


## 2026-08-17 — RULE: a PATHSPEC commit is the default; the isolated index is the FALLBACK. The latter arms a revert every time

**Relayed by `commit-guard-blind-to-own-recipe`, owed to and written by the
coordinator.** That lane measured the two forms against a repo whose index held
a revert of `A.txt` and a deletion of `C.txt`:

- `git commit -m x -- <paths>` — **immune.** Tree kept `A.txt` at HEAD content
  and `C.txt` on disk. Same for `--amend -- <paths>` and `--pathspec-from-file`.
- `-i` / `--include` — **NOT immune**, a revert landed. Stays guarded.
- `-a` — immune to predicate 2 but commits the deletion under predicate 1.

**Why the pathspec form should be reached for FIRST:** it needs no repair step.
The isolated-index form (`GIT_INDEX_FILE`) protects a peer's staged work, but
`HEAD` moving under the shared index means every path you just committed is left
staged there at PRE-commit content — a revert of your own commit, armed, every
single time. That has to be disarmed afterwards, and forgetting is invisible.

So: **pathspec by default. Isolated index only when a pathspec cannot express
the commit**, and then `git reset -- <the same paths>` immediately after, with
`git diff --cached --numstat` re-read to prove it.

## 2026-08-17 — RULE: never close a queue item in BULK. Close each against its own evidence

**I did this to a live deploy request within hours of documenting the same
failure shape.** After deploying three requests I moved *everything* in
`.syndicate/deploy/requests/` to `done/` and stamped it all "EXECUTED by the
coordinator". A fourth request (`soccer-layer2-dates`) had been filed at 20:20Z,
after that batch was scoped. It was never deployed — its commits were not even
pushed — and it spent that time marked delivered.

**The morning's version of this rule was too narrow.** It said: after a merge
touching a queue directory, diff DELETIONS against the remote. That catches git
relocating files. It does not catch a human-or-agent bulk `Move-Item` over a
glob, which is what actually happened. The general form:

> **A status surface must only ever be advanced one item at a time, each against
> the evidence for THAT item.** "I deployed the batch" is not evidence about a
> file that entered the directory after the batch was scoped.

The tell was available and I did not look: the queue held 3 files when I scoped
the work and 4 when I moved them. **Count the items you are closing against the
count you inspected.** If they differ, something arrived while you worked.

Related: the same session had already written that a queue "only ever
accumulates because closing it was nobody's job" — the failure mode inverts the
moment closing becomes someone's job and they close too eagerly.

## 2026-08-17 — RULE: an aggregate dispersion check cannot see an UNINFORMATIVE CENTRE

**What happened.** Phase 7's bias/dispersion decomposition reported MLB pitcher
outs at **dispersion 0.791 against a 0.798 target** — as close to perfect as that
metric gets. I read it as "the shape is right, only the location is off" and went
looking for a calibration fix.

**The shape was NOT right in the way that matters.** Dispersion scores
`sd(actual − mean) / mean(sigma)`. It asks whether the stated UNCERTAINTY matches
the realised error. It says nothing about whether the per-item MEAN carries
information. Measured directly:

    corr(sim_mean, actual) = +0.05
    sim_mean spread sd     =  1.19
    actual spread   sd     =  4.06

The engine predicts nearly the same value for every start. Its per-start sigma
(~5) is genuinely well-calibrated **around a centre that does not move**, and
that combination passes a dispersion check cleanly.

**RULE: alongside bias and dispersion, always report the CORRELATION between the
forecast and the outcome, and the RATIO of forecast spread to outcome spread.**
A model can be perfectly calibrated and completely uninformative; those two
numbers separate the cases and neither bias nor dispersion will.

**The tell to watch for:** `sd(forecast) << sd(actual)`. Here it was 3.4x
narrower. That is near-degeneracy, and `#425`'s degeneracy detector only fires on
FULL collapse to a single value, so it did not trip.

**Why this matters beyond one market:** the remedy differs completely.
Miscalibration is fixed by a profile; an uninformative centre is not fixable at
all at the calibration layer, and shipping a profile for it burns a promotion
cycle to change nothing. I nearly recommended exactly that.

Related: `learnings.md` 2026-08-17 on matching the baseline's FORM, and the
`#428` rule about decomposing bias before publishing a skill verdict — which I
had ALSO skipped on this same model before catching it here.

## 2026-08-17 — RULE: a signature change needs a CALLER CENSUS, not a spot-check of the caller you just edited

**Evidence.** `_load_team_ratings` gained a required third parameter (`as_of`,
audit §7 #6). The author updated the caller inside the same module and wrote a test
for it:

```python
assert "_load_team_ratings(league, source_root, iso_date)" in inspect.getsource(mod)
```

That test asserted the ONE call site somebody remembered. **Four others were not
updated and the test stayed green through a total production outage** — soccer's
live lens was dead for as long as the change had been in, and `poll_soccer_live_state.py`
raised `TypeError: missing 1 required positional argument: 'as_of'` on exactly the
leagues that had a live match.

**Why asserting call-site TEXT is the trap.** It can only ever prove the site you
thought of. It reads like coverage and is a spot-check. The green result was not
weak evidence of correctness — it was NO evidence, about four of five sites.

**The replacement** (`tests/test_soccer_team_ratings_as_of.py::test_every_caller_passes_as_of`):
AST-walk the repo, resolve every call the way Python does (module-local `def` wins,
else the `from ... import` binding), assert arity. It found the two remaining broken
sites in `validate_soccer_vs_market.py` **by being written** — no run required.

**TWO functions, SAME name, DIFFERENT arities**, which is why a naive census would
also have been wrong: `build_soccer_artifacts._load_team_ratings(league, source_root,
as_of)` takes 3, `validate_soccer_vs_market._load_team_ratings(league, as_of)` takes 2.
Three of five sites bind to the 2-arg one. A census that assumes a single arity is
worse than none — it reports confident wrong answers.

**Also:** exclude `.claude/worktrees/` from any repo-wide AST sweep. It holds stale
copies of the same scripts from other sessions, still on the pre-change signature.

**HOW TO APPLY.** When you change a signature: census the callers before you finish,
and if you write a test for it, assert over ALL resolved call sites, never over the
text of one. Then verify the test FAILS with the bug reintroduced — I reverted the
fixed call site, confirmed the census named `poll_soccer_live_state.py:105 passes 2
arg(s), needs 3`, and restored. The old test was green against that exact state.

Related: [[feedback_confirm_the_code_ran]] (assert the branch, not the outcome) and
the standing "gate on the output, not the input" rule — a guard that encodes an
assumption about WHICH caller breaks is silent in the real failure mode.

## 2026-08-17 — RULE: a falsified prediction LOCALISES a bug; treat it as a measurement, not a miss

**Three predictions were falsified today and each was worth more than the
confirmation would have been.**

1. **"Totals will run HIGH"** (from a measured +15% plate-appearance inflation).
   They run **LOW, −0.481**. That single sign flip proved the opportunity bug is
   in the PROP PROJECTION path and not the game simulation — a localisation no
   amount of prop-side work had produced.
2. **"The home team skips the bottom of the 9th"** (a textbook cause of exactly
   the +0.5 AB signature). HOME +0.478 vs AWAY +0.535 — **flat**, so it is not
   side-specific, which pointed at substitution instead.
3. **"NFL's knee will be ~406"** (from the sigma/CRPS_clim scaling law). It is
   **below 50**, because NFL summarises draws into a Normal while MLB scores the
   empirical PMF — so the law applies to the FORECAST REPRESENTATION, not the
   sport.

**The rule:** state the prediction and its expected MAGNITUDE before running the
check, so a wrong answer carries information. "Totals should be +1.0 high" fails
informatively; "let us see if totals are biased" does not. All three of these
narrowed the search; none of them cost anything beyond the run.

**The discipline that makes it work:** say in advance what a negative result
would mean. I wrote "if the NFL knee is below 300 the honest reading is that the
scaling law is wrong, not that NFL is special" BEFORE seeing it — which made
accepting the answer automatic rather than a negotiation with myself.

## 2026-08-17 — A SIGNATURE CHANGE NEEDS A CALLER CENSUS, AND THE CALLER YOU CANNOT REACH IS THE ONE THAT BREAKS

`_load_team_ratings` gained a required third parameter (`as_of`). The change
updated the caller inside its own module and missed **three others**. One of them,
`poll_soccer_live_state.py:75`, is the soccer live lens. It was dead for every
league with a match in play, for as long as that change has been in.

**Why it survived â€” three independent covers, and each is a general shape:**

1. **The broken call sat behind `if live_events:`.** Only a league WITH a live
   match could execute it. Silent on a quiet slate, total on a busy one. A defect
   gated behind "there is something to do" is invisible in exactly the conditions
   nobody tests.
2. **The handler swallowed it with no log line.**
   `poll_active_leagues_for_tick` caught each league's exception into an `errors`
   dict that reaches only `data/live/soccer_live_lens.json` â€” not in the publisher
   allowlist, so unreadable from web. **A throwing league was indistinguishable
   from a league that was never active.**
3. **The test asserted the call-site TEXT of the ONE caller that was fixed.**
   `test_soccer_team_ratings_as_of.py:117` asserted
   `"_load_team_ratings(league, source_root, iso_date)" in getsource(mod)` for
   `build_soccer_artifacts` alone. It was green throughout. **A test that pins the
   caller you just edited proves you edited it â€” nothing more.**

**THE RULE.** When a function gains a required parameter, the test must enumerate
**every** call site by AST across the repo and assert arity against the signature â€”
not string-match one file. `18c5ecb9` does this. It found the live one plus two in
`validate_soccer_vs_market.py` that string-matching could never have seen.

**AND: `ok: true` was not evidence.** Three instruments read healthy while the
feature was entirely dead â€” the tick reported `ok: true` (because
`validate_live_lens_snapshot` accepts an EMPTY games list), seven leagues wrote
their files successfully, and no error appeared anywhere. The tell was a **ratio
nobody was printing**: 7 leagues written against 10 active. The discriminator was
in the data all along, as a count that was never compared to its denominator.

**Cross-reference:** this is the same family as the standing rules on absent
signals and on gating for the wrong failure mode. New here is the *test* being the
third cover â€” the other two are about instruments, this one is about the thing
that was supposed to catch it.

## 2026-08-17 — TEST DEPLOYMENT BY CONTENT, NEVER BY ANCESTRY OR BY A SHARED SYMBOL

Two near-misses in one session, opposite directions.

**False negative.** live-odds-worker deployed `7470939b`.
`git merge-base --is-ancestor 6bdc50de 7470939b` -> **NO**. By ancestry the fix was
absent. `git show 7470939b:scripts/poll_soccer_live_state.py` -> the 3-arg call is
**there**. Deploy-branch delivery, exactly as the existing "web runs a deploy
branch" rule describes â€” recorded again because I nearly reported a shipped fix as
missing.

**False positive.** Checking whether the web fix had shipped, grepping the served
page for `railDate` returns **present** â€” because `railDate` is the OLD,
insufficient filter that the fix REPLACES. The honest check derives markers from
the actual diff: **1 of 79** substantive lines present, i.e. not deployed.

**THE RULE.** To answer "is this change live", diff the deployed artifact against
the commit, or probe a string the commit UNIQUELY introduces. A symbol that exists
on both sides of the change answers a different question than the one asked.


## 2026-08-17 — RULE: the FIRST test for any flagged feature is "does enabling it change anything"

**I built three inert things today.** Not three bugs — three pieces of work that
existed, looked complete, passed their obvious tests, and did nothing:

1. **A `manager_tendencies.json` at the wrong path, wrong key, and wrong
   schema.** I announced it as fixing the root cause.
2. **`GameConfig.position_substitutions` set with `setattr`.**
   `dataclasses.replace()` rebuilds from DECLARED FIELDS ONLY, and the sim calls
   `replace(cfg, rng_seed=...)` on every run — so the attribute was discarded
   before the first pitch and the feature was permanently off.
3. Earlier, a **leash test reading `stats["outs"]` where the key is `"OUTS"`** —
   which made three no-op tests pass on `0.0 == 0.0`.

**Every one was caught by the same thing: a test that asserts ENABLING IT CHANGES
THE OUTPUT.** No amount of "the code is present", "the file exists" or "the
no-op case passes" would have found any of them. Two would have shipped as
completed work.

**RULE: for any feature behind a flag, artifact, or config key, write the
reachability assertion FIRST —**

    assert run(enabled=False) != run(enabled=True)

**— and only then write the correctness tests.** If that assertion cannot be
written, the feature has no observable effect and there is nothing to test.

**The corollary that bit hardest:** a no-op test and a reachability test look
like a pair, but they FAIL INDEPENDENTLY and the no-op half passes vacuously
when the feature is dead. Three green no-op tests are evidence of nothing on
their own.

**Specific trap worth naming: `dataclasses.replace()` silently drops
monkey-patched attributes.** Any config that is `replace()`d in a loop must
carry its flags as DECLARED FIELDS. An instance attribute survives exactly until
the first `replace()`, which in a simulator is before the first event.

Related: the standing "presence is not reachability" rule — this is its
test-shaped form, and today produced four fresh instances.


## 2026-08-17 — RULE: a watcher that reports a PEAK of ZERO has not measured a peak. Zero samples is NO DATA, never "clean"

**I wrote a memory watcher whose entire purpose was to catch an OOM I had
predicted, and it reported `Window clean. Peak live-odds-worker memory 0.0% of
2048MB` while the service was at 85.3% and climbing.** Had I trusted it, the
rollback would not have happened. It was caught only because the user asked me
to check the number by hand.

**The mechanism, and it is three ordinary mistakes stacked:**

1. `scripts/render_logs.py` TRUNCATES each log line (`--max-field`), so the
   embedded JSON arrives incomplete — the samples visibly end mid-key at
   `"date`. The text search was fine: `CONTAINER_MEMORY` matched 367 times.
2. `json.loads` therefore threw on every single line.
3. The parse sat inside `try: ... except: pass`, so every failure was silent,
   `pcts` stayed empty, and the danger check `if pcts:` never ran.

Then the fatal line: the summary printed `Window clean. Peak {worst:.1f}%`
unconditionally, where `worst` was still its initial `0.0`. **A peak of 0.0% on a
running service is physically impossible and the code presented it as the
healthy case.**

**How to apply, to any watcher:**
- **Assert the sample count, not just the value.** `if not samples: fail("NO
  DATA")`. A threshold check over an empty set passes vacuously, and a vacuous
  pass looks exactly like a healthy service.
- **An impossible reading is a bug report, not a measurement.** 0.0% memory,
  0 rows, 0 games, `n=0` — treat as instrument failure and say so loudly.
- **Never `except: pass` around parsing in a guard.** Count the failures and
  surface them; a guard that cannot parse its input is blind, and blind must
  never render as clean.
- **Parse defensively when the source truncates.** Prefer a regex for the one
  number you need (`container_memory_pct_of_max":\s*([\d.]+)`) over `json.loads`
  of a field the reader may cut.

**Why this one stings:** the same file's docstring says *"Terminal states, all of
them printed -- silence must never look like success."* I wrote that rule into
the header and then violated it in the summary line, because I guarded the
*absence of an event* and forgot to guard the *absence of a measurement*. This is
the fourth-plus instance of instrument blindness in this repo and the first that
was self-inflicted inside a tool built to prevent it.

## 2026-08-17 — RULE: a feature can be unfed at the DATA layer, and it looks nothing like a bug

**Standing rules here cover code that is present-but-unreachable.** This is the
same failure one level down: code that IS reached, with inputs that are empty.

**Measured:** the MLB sim consumes pitch-type multipliers at four call sites as
`.get(pitch_type, 1.0)`. `pitcher.arsenal` is **100% populated** — so the sim
samples a real pitch on every pitch — while `pitch_type_whiff_mult`,
`pitch_type_hr_mult` and `vs_pitch_type` are **0% populated on 449/449
pitchers**. Every multiplier resolves to 1.0. **Pitch selection is decorative.**

**Nothing about this presents as broken.** No error, no warning, no null. The
arsenal being populated makes it look MORE alive, not less. The tests pass. The
sim runs. The feature simply has no effect, and has had none for as long as the
cache has been empty.

**RULE: for any model input that flows through a `.get(key, NEUTRAL)` default,
measure the POPULATION RATE, not the presence of the code.** A neutral default
(1.0 for a multiplier, 0.0 for an additive term) is indistinguishable from a
working feature at every level except the data.

**The specific shape to hunt for:** a *pair* of fields where one is populated and
the other is not — an arsenal with no effectiveness, a lineup with no platoon
splits, a schedule with no clock. The populated half makes the empty half
invisible.

**Why it persisted:** the loader was CACHE-ONLY (returns None on a miss, never
fetches), its cache namespace had never been written, and its populator was a
manual out-of-band tool. Three separate silences, none of which logged anything.

**Corollary that cost the most:** the cache lived under `vendor/*/data/`, which
is **gitignored and inside Render's ephemeral checkout**. So even a correct local
fill could never reach production — *"I populated the cache"* and *"production
has the data"* are unrelated statements. Check the SHIPPING PATH before
celebrating a data fix.

## 2026-08-17 — RULE: rank modelling gaps by how much the dimension DISCRIMINATES, not by how complete its machinery is

**What I did.** Researching what the MLB sim was missing, I found pitch-type
effectiveness fully built — model fields, four consumption sites, a loader, a
cache, a fetch tool — and **0% populated**. I ranked it "where a market beat is
most likely" *because everything existed and only needed wiring*, and spent
**314 network calls and ~2 hours** filling it.

**Result at 98.4% coverage: ~+0.001 mean Brier, 3 of 4 markets, no market beat.**
The prediction was wrong and is retired.

**What I should have measured first, and later did — in twelve calls:**

    batted ball   barrel rate  p10  3.10%  ->  p90 13.85%     (4.5x spread)
    defence OAA   outs         p10 -6.0    ->  p90 +7.4       (13.4 outs)
    pitch splits  -- no spread probe was ever run --

**Both of the dimensions I ranked BELOW pitch-type are ONE CALL EACH** (season
leaderboards, not per-player) and have large, measured between-player spread. I
ranked by machinery-completeness; machinery-completeness predicted nothing.

**RULE: before investing in a modelling gap, measure the SPREAD of the input
across the population it would distinguish.** A dimension where p10 and p90 are
close cannot move a forecast however elegantly it is wired. A cheap spread probe
is minutes; the wiring was hours.

**The seductive part, and why this needs to be a rule rather than an
observation:** "everything is built, it just needs data" feels like the highest
expected value in the room. It is an argument about COST, and I let it stand in
for an argument about VALUE. Cheap and worthless is still worthless.

**Corollary:** state what fraction of a feature you actually tested. I populated
the PITCHER side and `batter.vs_pitch_type` remains 0%, so the matchup
INTERACTION was never tested — only per-pitcher average effectiveness. The
negative result stands for what was measured and must not be cited as broader.

## 2026-08-17 — RULE: you cannot add a MECHANISM to a CALIBRATED engine without re-fitting its rates

**Measured, 2x2 factorial, 4 of 4 markets:** adding position-player substitution
and pitch-type splits to the MLB sim produced a **NEGATIVE interaction, mean
−0.00331**. On RBIs each feature alone helped (−0.00573, −0.00271) and together
they gained almost nothing (−0.00046). **On runs, both-on was WORSE than
neither.**

**Why, and it generalises far beyond these two features.** The engine's
`k_rate` / `hr_rate` / `inplay_hit_rate` were fitted so the sim's OUTPUT matched
observed outcomes — using a sim that never substituted anyone and never varied
effectiveness by pitch type. **Those fitted rates therefore already ABSORB the
average effect of the missing mechanisms.**

Adding a mechanism back DOUBLE-COUNTS it. Adding two double-counts twice and the
errors compound. The negative interaction is not a quirk of these two features;
it is what a calibrated system does to any mechanism you hand it.

**RULE: adding a mechanism to a fitted model is a TWO-PART change — the mechanism
AND a re-fit of the parameters that were absorbing it.** Shipping half of that is
worse than shipping neither, and the factorial is how you find out.

**The corollary that reframes a whole day's measurements:** every
single-feature effect I measured (+0.001 pitch splits, 34.3% of the opportunity
gap from substitution) was measured AGAINST rates fighting it. **Those are not
the features' ceilings — they are what survives the calibration.** A small
measured effect from a mechanism added to a calibrated engine is weak evidence
that the mechanism is unimportant.

**And it inverts a plan:** batted-ball data had just cleared the predictive gate
(hard-hit% 1.9x `hr_rate` on future TB) and was the obvious next wiring target.
It is now the WRONG next step — it would be a third mechanism against the same
un-refitted rates. **The re-fit is the precondition, not a follow-up.**

## 2026-08-17 — RULE: "the model is absent" needs a FIELD AUDIT, not a name search

**I published a research document stating the MLB sim has "no batted-ball type
model — no GB/FB/LD". It was wrong.** The model exists and `simulate.py:1120-1136`
consumes it for both batter and pitcher:

    batter_bb_gb_rate=float(getattr(batter, "bb_gb_rate", 0.44))
    batter_bb_fb_rate=...0.25   bb_ld_rate=...0.20   bb_pu_rate=...0.11

**All four are 0% populated on 720 batters and 717 pitchers**, so every player
runs the league-average defaults and a ground-ball specialist is identical to a
fly-ball slugger.

**How I got it wrong:** I grepped
`ground_ball|fly_ball|line_drive|launch_angle|exit_velo|gb_rate`. The fields are
prefixed **`bb_`**, so every pattern missed. A negative grep became "the model is
absent" in a document that then ranked work by that belief.

**RULE: to claim a model is ABSENT, enumerate the fields of its data structures
and measure their POPULATION — do not search for names you expect.** A name
search can only prove *your vocabulary* is absent. `dataclasses.fields()` over
the profile objects took one script and found **18 zero-population fields**,
including five I had explicitly declared missing.

**Why this matters more than a wording error:** ABSENT and UNFED have opposite
remedies. Absent means design and build; unfed means populate a field that is
already consumed. I recommended a modelling project where a data pipeline was
needed, and then **built the wrong thing on top of it** — a multiplier hack on
`hr_rate`/`inplay_hit_rate` when the engine had native GB/FB/LD fields waiting.

**Companion to the 2026-08-17 rule about `.get(key, NEUTRAL)` defaults.** That
one says a populated-looking feature can be inert. This one says an
absent-looking feature can already exist. **Both are answered by the same
action: measure the population rate of every field, never reason from a grep.**

## 2026-08-17 — FOUR DEFECTS IN ONE SESSION SHARED ONE SHAPE: THE ERROR PATH RENDERED AS THE SYSTEM'S OWN "NOTHING HERE"

Not "errors were silent" — silence is common and usually harmless. In all four the
failure output was **byte-identical to a legitimate empty state that the same
system produces constantly**. That collision is what made each one survive, and in
three of the four an instrument was actively reporting health while the feature was
dead.

| # | defect | the failure rendered as | how long it hid |
|---|---|---|---|
| 1 | `poll_soccer_live_state.py:75` passed 2 args to a 3-arg `_load_team_ratings` | a league that is **not active today** | as long as the `as_of` change had been in |
| 2 | soccer's live-lens memory gate returns with no log line | a **builder that never ran** | still true; cost a hypothesis this session |
| 3 | `test_layer2_soccer_window.py` patched a renamed function under `raising=False` | a **passing test** | since `#435` |
| 4 | `#379`'s per-date `except: continue` swallowed shard read errors | a sport with **no slate** | since `#379` |

### What each one actually looked like from outside

**1.** `poll_active_leagues_for_tick` caught each league's exception into an
`errors` dict and continued with no print. That dict reaches only
`data/live/soccer_live_lens.json`, which is not in the publisher allowlist, so it
is unreadable from web. Worse, the broken call sat behind `if live_events:` — so
**only a league WITH a live match could reach it**. Silent on a quiet slate, total
on a busy one. Three instruments read healthy simultaneously: the tick reported
`ok: true` (because `validate_live_lens_snapshot` accepts an EMPTY games list),
seven leagues wrote their files successfully, and no error appeared anywhere.

**2.** MLB and WNBA both `print("[LIVE_LENS_TICK_DIAG] ... reason=low_headroom")`
when their gate trips. Soccer's returns bare (`live_lens_loop.py:524-530`). WNBA's
own comment in that same block says "a gate that fires silently cannot be told from
a builder that never ran" — soccer is the instance that comment describes and does
not cover. It cost a hypothesis a single log line would have settled.

**3.** `#435` renamed the read to `read_book_quotes_latest`. The test patched
`read_book_quotes`, which **still exists**, so nothing raised — the patch bound to
a function nobody calls. `raising=False` is what made it silent: "tolerate absent"
and "silently bind to nothing after a rename" are the same behaviour. One test kept
PASSING VACUOUSLY (`assert quote_rows == 0`, trivially true when the read is never
intercepted).

**4.** The window loop's `except Exception: continue` absorbed the exception that
used to propagate to the whole-sport handler, which records `{"error": ...}`. A
sport whose shard raised on every date reported `quote_rows: 0, grid_rows: 0` and
no error — identical to a sport with no slate.

### THE DISCRIMINATOR WAS A RATIO IN EVERY CASE, AND NOBODY WAS PRINTING IT

Each defect was invisible as an absolute and obvious as a fraction:

    1.  7 leagues written  /  10 active          <- the 3 missing were exactly the 3 live
    3.  0 interceptions    /  7 expected reads   <- patching the old name vs the new
    4.  0 quote_rows       /  7 dates asked      <- and were any of them unreadable?

**RULE: a count of successes is not a measurement until it is stated against what
was attempted.** `#379` already established this for zeros (`window_dates` exists so
"zero against seven dates" and "zero against one" differ). Extend it: emit the
denominator for *partial* success too, not only for zero. Seven successes out of
ten looks like success and is a 30% outage.

### RULE: AN ERROR PATH MUST NOT LAND ON THE SYSTEM'S EXISTING EMPTY STATE

When writing a handler, ask what the caller sees, and whether that is
distinguishable from the ordinary nothing-to-do case. If it is not, the handler is
not a handler.

- Recording into a structure nobody can read is not recording (#1, #4). Check the
  publisher allowlist / the reader's actual reach before counting it as observable.
- A neighbouring implementation that DOES log is a specification, not a style
  choice (#2). Diverging from it silently is the defect.
- In tests, `raising=False` on a monkeypatch is this same anti-pattern: it converts
  "the thing I am testing moved" into "the test passes" (#3). Default to
  `raising=True`, and assert the patched name is the one production calls.

### RULE: A GREEN/HEALTHY READING IS EVIDENCE ONLY ONCE YOU KNOW WHAT MAKES IT RED

Already a standing rule (instrument blindness); this session produced four fresh
instances in one lane, so it is not learned yet. Concretely, all of these were
compatible with total failure: `ok: true` on a tick, a passing test, `quote_rows: 0`,
and `(0 live games)`. Before trusting one, name the input that would make it fail —
and if you cannot, the instrument is not measuring what you think.

**Corollary that decided #1:** compare against a SIBLING measurement rather than a
threshold. Soccer's tick ran in 1 second where MLB's took 7, doing work that is
supposed to be 4 Monte Carlo passes per live match. Nothing was out of range; the
ratio to its neighbour was the tell.

### Fixed this session
`6bdc50de` (#1, deployed and measured 7 -> 10 leagues/tick), `9e052dfe` (#3, with a
guard asserting the patched name matches production), `ec8c3beb` (#4, `error` +
`read_errors` on both branches, including the untested partial-failure branch).
**#2 is NOT fixed** — soccer's gate still returns silently. One print, at
`live_lens_loop.py:524-530`, mirroring the two beside it.

## 2026-08-18 — RULE: a cache with a TTL can serve EMPTINESS as authoritative

**Measured:** 1,282 BVP cache files, every one `by_batter: {}`. I concluded twice
from the file COUNT — first "the data is already collected, it just needs
mapping", then "it needs a real fetch job". **Both wrong, in opposite
directions.** Computing fresh returned 117-170 batter entries for 5 of 5
pitchers.

The raw corpus was present the whole time (39 files, 2026-03-11..07-30). Some
earlier run cached an EMPTY result — corpus absent or unreachable at that moment
— and the **30-day TTL has been serving that emptiness as a valid answer ever
since.** No error, no retry, no staleness signal: a cache hit on `{}` is
indistinguishable from a cache hit on real data.

**RULE: when a cached value is empty, verify by COMPUTING IT FRESH before
concluding anything about the source.** An empty cache entry is evidence about
the moment it was written, not about the data.

**And the specific trap: a TTL turns a transient failure into a persistent one.**
The longer the TTL, the longer a single bad fetch is indistinguishable from a
genuine absence — here, 30 days. Caches of *derived* values should record
whether the input corpus was present when they were written; without that, an
empty result is unfalsifiable from the outside.

**Companion to the 2026-08-17 field-population rule.** That one says: measure
whether a MODEL FIELD is fed, never infer from code presence. This says: measure
whether a CACHE holds data, never infer from file count. Same failure, one layer
apart — and I made it four times in two days before writing it down.

## 2026-08-18 — RULE: when a claim is corrected TWICE, stop asserting and run it

**I made FOUR wrong calls about BVP in one session, alternating direction:**

1. "already collected, needs only a mapping" — from a **file count**
2. "needs a real fetch job" — from the **empty files**
3. "cheap, just invalidate the cache" — right answer, **wrong reasoning**
4. "invalidation will not help, nothing writes it" — from grepping
   **`build_roster.py`**, the wrong file

Each was a confident, specific, wrong claim, and each came from a **different
cheap proxy**: a count, a sample, an assumption, a grep of one file.

**The thing that settled it took one command:** move the cache aside, call the
applier, count the populated fields. `0 -> 6 of 9`. That was available from the
first minute.

**RULE: the second time a claim about the same object is corrected, stop
reasoning about it and EXECUTE it.** A third inference is not more likely to be
right than the first two — the failure is the method, not the attempt.

**Why this one was so persistent:** the object had FOUR independent failure modes
(no data / stale cache / no applier / wrong file grepped), and each proxy could
only see one of them. No single cheap check could have been right. **When an
object has multiple independent ways to be broken, only running it end-to-end
distinguishes them.**

**Also learned, and it belongs with this:** `build_roster.py` had no BVP
reference because BVP is applied one level up in `daily_update.py:7564`. **A
negative grep in the file you expect proves nothing about a pipeline with three
application sites.** The provenance table in
`docs/ai_context/mlb_sim_engine_reference.md` exists so the next person reads
where things ARE applied instead of guessing where they SHOULD be.

## 2026-08-18 — I ALMOST REQUESTED A DEPLOY FOR SOMETHING ALREADY LIVE, AND ONLY THE BASELINE CAUGHT IT

I reported `pct_projected: 0.0` and "goal (c) undelivered" three times in the space
of an hour. It was **53.8** and had been live since 00:29:52Z, shipped by another
session as `b4d82364`. My number was a genuine measurement — from ~19:5xZ — restated
from memory across six hours of a fast-moving tree while four other sessions
committed and deployed around me.

**What caught it was mechanical, not clever:** the deploy-request template has a
`verify:` field that demands a BEFORE value, so filing it forced one fresh read. The
discipline that saved this was writing down the before-number at the moment of
filing rather than carrying it forward.

**RULE, sharper than "re-baseline before judging":** a number you are about to put in
a request, a report, or a ledger entry must be re-read AT THAT MOMENT. Age it in
minutes, not in "this session". On a tree with concurrent sessions, a six-hour-old
production reading is not stale data — it is a different system.

**Second-order:** I had also written that same 0.0 into a lane entry as current
state. A stale number in the ledger outlives the session that wrote it and is read as
fact. State entries carry more risk of this than chat, not less, so the freshness
requirement is strictest exactly where it feels most ceremonial.

Related and NOT the same thing: `pct_projected: 53.8` still does not mean soccer is
on the board — `active_sports` excluded it and it served 0 shortlist rows at the same
instant. Fixing a join and appearing on a surface are different claims, and a metric
that moves 0 -> 53.8 is seductive enough to conflate them.

## 2026-08-18 — RULE: a bias can be the NET of two opposing errors, and fixing one is a wash

**Measured:** the MLB engine under-produced strikeouts by **27%** (K/PA 0.179 vs
0.226). The obvious cause was the pitch-outcome mix — `base_in_play` 0.23 against
a league ~0.17, `base_foul` 0.12 against ~0.18 — and correcting it lands the mix
almost exactly on the league.

**And K/PA goes to 0.284 — 26% TOO HIGH.**

The deficit was never one error. A contact rate that truncated plate appearances
(suppressing K) was **masking a strike->strikeout conversion ~26% too efficient**.
The two were within a few points of cancelling, so the engine looked like it had
a single tidy bug.

**RULE: before fixing a measured bias, check whether the fix moves the metric
PAST the target.** A correction that overshoots by roughly the amount it was
meant to close is the signature of two opposing errors, and shipping it converts
a shortfall into a surplus while looking like a fix.

**The tell that separates them:** an auxiliary metric that stays wrong after the
fix. Here `pitches/PA` remained short (3.45 vs 3.9) even with a correct call mix
— so PA STRUCTURE was a second, independent defect, and the mix was never going
to reach the target alone.

**Corollary on method:** one-at-a-time tuning cannot solve a two-error system —
each parameter looks wrong in isolation and each single fix overshoots. It needs
JOINT calibration against an outcome the errors cannot both satisfy. Here that
means the market scoreboard rather than the league mix.

**And the thing I nearly did:** ship the mix fix, see the league mix match
beautifully, and report the K deficit as closed. Every intermediate check would
have agreed with me.

## 2026-08-18 — A STRUCTURAL DEFECT AND A MARKET EDGE ARE DIFFERENT QUESTIONS

`convergence-phase7-crps`, `#440`. Measured, not argued.

The sim's single largest measured structural error was the first-pitch count cell
— real hitters take 0-0 (29.6% called strike, 11.3% in play), the sim swung at it
(13.7% / 25.9%). Correcting it landed the cell **exactly** (29.6% vs 29.6%) and
moved both global metrics the right way with no overshoot.

**The market moved by −0.00013. Two markets better, two worse.**

**RULE: "the engine is wrong here" does not imply "fixing it wins money."** A
defect can be real, large, exactly measurable, exactly correctable — and priced
in, or orthogonal to what the market pays for. **Do not present a diagnostic
improvement as a market result, and do not treat market-neutrality as proof the
diagnosis was wrong.** They are separate claims needing separate evidence.

Corollary, applied here: keeping a market-neutral change is legitimate ONLY as an
explicit judgement call, recorded as such, with the exact no-op stated
(`first_pitch_swing_damp = first_pitch_called_boost = 1.0`). It is not a result.

## 2026-08-18 — MEASURE THE COUNT MATRIX; DO NOT GRID-SEARCH IT

Three calibration attempts failed before one measurement succeeded.

- Mix-only fix: K/PA from **27% LOW to 26% HIGH**. Two opposing errors were
  cancelling — **fixing either alone is a wash or worse.** FORBIDDEN alone.
- 3-parameter joint grid over mix + two-strike terms: **target unreachable.**
  `two_strike_foul_boost` saturates before K closes.
- **`count_delta` is a single scalar** and structurally CANNOT express
  take-early / attack-middle / protect-late. No amount of search fixes a
  parameterisation that cannot represent the answer.

What worked: **PA-outcome arithmetic** to localise (per-pitch in-play rate
correct, PA share wrong ⇒ the error is progression), then **895,320 real statcast
pitches** to produce a real-vs-sim matrix by count. `scripts/measure_count_progression.py`.

**RULE: when the ground truth is directly observable, observe it.** Pitch-level
behaviour by count is in the pbp corpus. Fitting free parameters against an
aggregate to recover something you can just count is slower, and it silently
absorbs unrelated error.

**Guardrail that paid:** the script's first run produced **0 sim pitches** (the
pbp count is nested, `count.balls`, not flat). It **REFUSED** rather than
printing an empty matrix. An empty matrix reads as "no difference."

## 2026-08-18 — RULE: a session RESUME reassigns the session id, which silently stands the coordinator role down. The register must be re-verified, not assumed

**My own deploy guard blocked me.** `coordinator.id` held
`9ed7fd89-...` — correct when written at 13:36 — and the hook was being handed
`6f0980eb-...`. Nothing edited the register; **the session id changed underneath
it** when the session was resumed. The role had been silently unheld for an
unknown stretch, and the first symptom was the coordinator being unable to
deploy.

**The diagnosis cost far more than the fix**, because the block message named
neither id. I probed `lane-guard` twice (its block message DOES print the id),
and both probes returned nothing — an `Edit` whose `old_string` does not match
never reaches the `PreToolUse` hook, so that method cannot identify a session at
all. Only after adding the ids to the guard's own message did one call answer it.

**Fixed at the source:** `deploy-guard.py` now prints

    this session:           <id>
    registered coordinator: <id>

on every block. A guard that says "you are not who I expected" without naming
either party forces exactly the archaeology this rule exists to prevent.

**How to apply.**
- **Treat `coordinator.id` as verifiable state, not settled state.** Re-check it
  after any resume, and whenever the guard behaves unexpectedly.
- **The scratchpad path is a live signal:** it carries the CURRENT session id.
  Mine moved from `9ed7fd89-...` to `6f0980eb-...` and I kept using the old path
  for scratch files without noticing, because the old directory still existed.
- **This is the third distinct id problem in two days** — the roster id differing
  from the payload id, the register being unverifiable from another session, and
  now the payload id changing under a resume. The single-value register is the
  common weakness. It should hold a LIST of accepted ids; an attempt to make it
  so was blocked mid-edit and reverted, and remains the right fix.

**What this did NOT break:** the guard held correctly for every other session
throughout. The failure mode is the coordinator locking itself out, which is the
safe direction — but it is invisible until someone tries to deploy.

## 2026-08-18 — THE MARKET HARNESS HAS A NOISE FLOOR 2.4x THE EFFECTS IT WAS USED TO JUDGE

`convergence-phase7-crps`, `#440`. `scripts/measure_all_inputs_effect.py`,
45 games x 120 sims, 2,415 scored rows.

**Same configuration, two seeds, nothing else changed:**

    market                seed 1337   seed 4242    |diff|
    batter_hits             0.23786     0.23660   0.00126
    batter_rbis             0.21717     0.21495   0.00222
    batter_runs_scored      0.23674     0.23248   0.00427
    batter_total_bases      0.25460     0.24932   0.00527
    MEAN                                          0.00326   <- pure RNG

The conditional-mix effect measured at seed 1337 was **-0.00138**. **Noise /
effect = 2.4x.** At the second seed the sign flipped in **3 of 4 markets** and
the mean went from -0.00138 (better) to +0.00185 (worse).

**RULE: a single-seed run of this harness cannot resolve anything smaller than
~0.003 Brier.** Every conclusion this lane drew from ONE seed is therefore
uncertain, including ones I reported as measured:

- "fully fed: 4 of 4 better, mean +0.00478" — marginally above the floor;
- "first-pitch take term: market-neutral, -0.00013" — **far below it**; that
  claim is not supported, in either direction;
- "two mechanisms interact, -0.00331, negative in 4 of 4" — **at the floor**.

**WHY 'same seed for both arms' BUYS NOTHING.** It looks like common random
numbers, and is not. Changing the pitch mix changes *how many* RNG draws a PA
consumes, so the two arms desynchronise on the first divergent pitch and every
downstream draw differs. Paired variance reduction requires the streams to stay
aligned — separate RNG streams per decision type, or antithetic/CRN structure.
A shared seed across arms whose control flow depends on the RNG is cosmetic.

**HOW TO USE IT PROPERLY:** report the mean over k seeds WITH the across-seed
standard error, or raise sims until the floor is below the effect (variance goes
as 1/sims, so resolving ~0.001 from 120 sims needs roughly 16x). **Never report
a single-seed delta as a result again.** A run that "beats the market" at one
seed — seed 4242 showed `runs_scored` beating the market in the arm WITHOUT the
feature — is a coin flip presented as a finding.

## 2026-08-18 — RULE: a `sed` backreference that does not match writes a RAW CONTROL BYTE, and it ate three lane slugs

**Three OPEN lanes lost their names entirely.** Their headers read
`###  \x01  —  \x02  — **body` — the literal bytes `\x01` and `\x02` where the
slug and status should be. A session correcting the ASCII-hyphen headers ran a
substitution with `\1`/`\2` backreferences whose capture groups did not match,
and `sed` wrote the escape sequences as raw control characters instead of the
captured text.

**Why it was nearly invisible.** The rendered line looks like a header with two
em-dashes and a bold body — `###  —  — **stable fixture identity SHIPPED`. The
missing slug reads as spacing. It took `od -c` on the raw bytes to see it, after
a regex repair silently failed to match the line it was written for.

**The damage was not cosmetic.** With no slug:
- `lane-guard` attributed the lane's claims to nothing, so
  `wnba_fixture_identity.py`, `run_live_odds_refresh_worker.py`,
  `book_margin_model.py` and their siblings were UNGUARDED again — the exact
  state the em-dash fix was made to repair;
- a ledger sweep reads a slugless header as a closed lane and **archives it**. It
  was one command away from three live lanes being filed as history.

**How to apply.**
- **After any bulk header rewrite, grep for control bytes**:
  `grep -nP '^###.*[\x00-\x08\x0e-\x1f]'` (or `od -c` a sample). A rendered line
  that "looks right" is not evidence about its bytes.
- **Prefer a parser to a regex for structured lines.** The repair that worked
  read each header, identified the lane from its own BODY text, and rebuilt the
  header — it did not pattern-match the damage.
- **Never sweep on "has no OPEN block" alone.** That predicate cannot tell a
  closed lane from a lane whose header was destroyed. Read every candidate header
  before archiving it; this sweep found the damage precisely because it did.

Related: the em-dash-is-syntax rule, whose fix caused this; and the sweep rule
that a status surface must be advanced one item at a time against its own
evidence.


## MERGED FROM origin/main - coordinator merge cycle

## MERGED FROM origin/main - coordinator merge cycle

## MERGED FROM origin/main - coordinator merge cycle

## MERGED FROM origin/main - coordinator merge cycle

## MERGED FROM origin/main - coordinator merge cycle

## MERGED FROM origin/main - coordinator merge cycle

## MERGED FROM origin/main — 2026-08-17, by the coordinator

Block-level union. These blocks existed on `origin/main` and nowhere
on the swept side. Appended verbatim, nothing edited, nothing reordered.

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

## 2026-08-17 — CHECKPOINT 9: a green test that asserts nothing

### FOUND: `for x in collection: assert ...` is VACUOUS on an empty collection

`test_two_sided_fair_is_devigged_and_drives_ev` was **green for as long as the
bug existed**. It loops over `result["opportunities"]` and asserts three things
about each — and `opportunities` was `[]`, because the fixture's two sides came
from different books and every candidate was dropped unscored. Nine of its
neighbours failed; this one reported success while checking nothing.

**Any test whose assertions live inside a loop needs a non-emptiness assertion
first.** One line:

    assert result["opportunities"], "fixture produced no scored candidates"

The failure mode is worse than a missing test, because the green tick is
evidence *against* looking. Same family as this repo's standing rule that a null
reading is about the instrument until proven otherwise.

### REFUTED: "the fixture was repaired, so the fixture is right"

The same `_row()` fixture carried a comment from an EARLIER repair explaining
that it had been changed to two different bettable books to satisfy
`book_shortlist.DEFAULT_BOOKS`. That repair was correct about its gate and broke
the next one: with no `cells`, the fair path requires both sides from ONE book,
so the fixture satisfied gate A and failed gate B — and the tests failed for a
reason neither the comment nor the assertions mentioned.

**When a fixture carries a comment explaining a previous repair, treat it as
evidence of a gate you have not met yet, not as evidence the fixture is
current.** Production accumulates gates; a fixture only ever met the ones that
existed when it was last touched.

### THE CHECK THAT SEPARATES A REPAIR FROM A COVER-UP

Making 9 red tests green is worthless if the fixtures now simply agree with
themselves. Before committing, revert each repair IN MEMORY and re-run:

    cross-book fixture   -> 4 failures   (CAUGHT)
    missing event_id     -> 6 failures   (CAUGHT)

If a reverted repair does not reproduce failures, the test no longer tests the
gate and the repair was a cover-up. **Three lines of scripting, and it is the
difference between fixing a suite and teaching it to lie more quietly** — which
matters especially here, where one of these tests had been lying for a while.
## 2026-08-17 — CHECKPOINT 10: the kill command was the unreliable instrument

### FORBIDDEN: trusting `pkill` / `pgrep` in Git Bash on this box

They do not see or terminate Windows `python.exe` processes here, **and they exit
0 either way.** I reported a full pytest run "stopped" and a gate "killed"; a
`Get-CimInstance Win32_Process` listing showed both still alive — the pytest at
**1.6 GB** — plus my restarted gate, so **three heavy runs were competing** on a
box already at 423 processes and ~26 GB accounted.

Two costs, and the second is the expensive one: the measurement I was trying to
take was contention-contaminated, and I told the user twice that things were
stopped when they were not.

**Use `Stop-Process -Id` and verify by RE-LISTING.** A kill is not an event you
can assume; it is a state you check. Every other instrument rule in this file
says a null reading is about the instrument — this is the same rule applied to a
command that *acts* rather than reads, and it is the first one tonight where the
faulty instrument was my own write, not my own read.

### FORBIDDEN: a completion watcher that greps the process's own log text

My first waiter looked for `GATE|FAIL|PASS|Traceback` in the gate's output and
fired **while the gate was still running** — those words appear in the
diagnostic firehose. It sent a "MIGRATION GATE FINISHED" notification for a run
that had not started its write step, and I relayed it.

Compounding it: the same waiter's `pgrep` guard was the broken instrument above,
so both halves of the condition were wrong at once.

**Watch the process, not its words:** poll the pid and treat a written artifact
as the completion signal. And launch through the real interpreter
(`python.exe ...`), not the `py` launcher — otherwise the pid you watch is a
shim and its exit says nothing about the child.

### A gate that FAILs on mirror coverage is not a statement about the code

The migration gate returned FAIL on `origin/main` with **all three code steps
passing** (audit, module tracker, the archive suite CI runs). Both failures were
missing `data/**` artifacts — and CLAUDE.md already says that tree is a lossy,
per-family-scheduled mirror rather than a snapshot of production.

**Read a gate's sections before quoting its verdict.** "Migration gate: FAIL" is
true and would have been badly misleading as a headline; the useful sentence is
"the code steps pass and the local mirror is thin", which points at a mirror
refresh rather than at a bug.

## 2026-08-17 — CHECKPOINT 11: a green gate that asks less

### A gate turned green by WAIVING is not the same fact as a gate turned green by FIXING

The migration gate went FAIL → PASS tonight across three waivers and zero fixes.
Every waived finding is defensible in isolation — dev-checkout artifact coverage,
not code defects — and the three command steps genuinely pass. But **the sentence
"the gate passes" now means less than it did this morning**, and nothing in the
report says so.

What makes it survivable rather than a lie: waived findings stay in `violations`
and only `unexpected` drives `ok`, so a reader can still see what is tolerated.
That is the property to preserve. This file already contained the opposite
pattern — a bare `if slug == "wnba": publish_missing_inputs = []` that suppresses
silently — and copying it would have been faster and wrong.

**How to apply: when you waive, say in the commit message and the code comment
what the waiver COSTS, and name the check that no longer exists.** For these two
that is: nothing now verifies the MLB daily mirror has data, and NFL/NCAAF
advanced surfaces are unguarded. **The right end state is DELETING the entries
when the generators run, not widening them.**

### Build a work queue from CONTENT, never from commit subjects

Seeding the refresh-worker deploy manifest, 10 commits since the live SHA touched
worker-run code. **Seven were already present in the live SHA as cherry-picks.**
A subject-based queue would have listed four entries that need no deploy — and
one of those subjects is **verbatim the live SHA's own subject**, so it would have
looked entirely plausible on review.

The service runs a deploy branch of cherry-picks, so `git log A..B` describes
*history*, not *difference*. `git diff --name-only <LIVE> origin/main` describes
difference. **Where a service runs cherry-picks, only content answers "what still
needs shipping" — and `--is-ancestor` is actively misleading.**

### `.gitignore` does not untrack, so "I added files" and "git sees files" are different questions

I pulled 255 artifacts (186 MiB) into `data/mlb_source/source_artifacts/` and
`git status` showed **zero** changes. `.gitignore:36` ignores that whole subtree,
yet 1,977 files in it are already tracked — ignore rules never untrack what is
already in the index. So the pre-existing files are tracked and every new one is
invisible.

**Consequence I nearly reported wrongly:** I had described the pull as improving
the repo's cold-start safety net. It improves **this checkout only** and will not
survive a fresh clone. **Before claiming a data fetch helped anyone else, check
`git check-ignore` on the destination.**

### A deploy that kills work is a different decision from a deploy that costs downtime

Eight web deploys tonight each cost ~1–2 min of 502s and killed nothing — every
`check_deploy_safety.py` blocker was on a worker I was not touching. The ninth
target was refresh-worker, where the same NOT CLEAR verdict meant an **MLB sim
11 minutes in, and a board build, would die**.

Same tool, same wording, categorically different cost. **Read WHICH service the
in-flight work is on before treating a safety verdict as boilerplate** — and for
an additive change nothing reads yet, queueing beats killing. Second cost, easy
to miss: a worker deploy reboots the container and resets the memory floor that
`refresh-worker-oom-recurrence` needs deploy-free windows to measure.

## 2026-08-17 — FORBIDDEN: printing a guard's result and then acting anyway. Branch on it or it is a log line.

I deleted 52 lines of another session's work from `.syndicate/lanes.md` with a
guard that fired correctly and changed nothing.

**What happened.** I rebuilt `lanes.md` as `origin/main` + my own block, in two
separate shell invocations: block A fetched and built the merged file, block B
re-read `origin/main` and committed. **Another session pushed between A and B.**
Block B's `read-tree` used the NEW tip while the file content came from the OLD
one, so their `wnba-live-tier` entry was written out of existence. The script
printed `143 52 .syndicate/lanes.md` — the deletion count was right there — and
the `git push` on the next line ran regardless, because it was sequential, not
conditional.

**The rule.** A guard that `print`s is documentation. A guard that `exit(1)`s is
a guard. If a check is worth computing before a destructive step, the
destructive step must be INSIDE the failure branch's else — in the same process,
not the next line of the same script.

**The second rule, which is the one that actually caused it.** **A merge base
is a reading with a timestamp, exactly like a lane claim or a baseline.** Mine
went stale in the seconds between two tool calls on a repo with ~14 live
sessions. So: **read the base and write the commit in ONE process**, and make
the base the same object you `read-tree`. Two shell blocks is two readings.

**What worked, and should be copied.** The repair was done in Python with
`subprocess` returning raw bytes, a hard gate asserting every non-blank line of
the pre-damage tip still present, and `sys.exit(1)` before the push. It also
avoided a second, quieter bug: PowerShell's `Get-Content -Raw` read the UTF-8
ledger as ANSI and corrupted every em-dash, which is its own way to "delete"
lines. **Do not round-trip these ledger files through PowerShell strings.**

**Standing consequence:** `git diff --numstat <base> <commit>` before any ledger
push, and the push gated on deletions == 0 in the same process. Insertions-only
is the invariant for every append to `lanes.md`, `deploys.md`, `learnings.md`.

## 2026-08-17 — FORBIDDEN: comparing a MAX (or any summary over a set) across two runs without checking the set is the same

`scripts/ui_layout_probe.py` compared `identicalContentSpread` through
`worstGroupPx` — the largest spread over all tie groups. Both sides were single
numbers, they matched, and the check printed `unchanged (baselined)` at exit 0.

**It was comparing two different groups.** Measured on production 2026-08-17
12:37 CDT, one game live against an all-Preview baseline:

    mobile   baseline 43px came from the 45-pair group
             current  43px came from the 53-pair group
             meanwhile 53: 30->43, 49: 32->15, 45: 43->36 -- ALL of them moved

    desktop  86px "unchanged" from u=49 n=3 vs u=49 n=2,
             hiding the 45-pair group moving 28->41

A max is a function of a SET. When the set's membership moves — here a game
going live leaves the Preview pool — the max can land on a different member and
read identical. The number was stable; the thing it stood for was not.

**Why this is the bad direction.** A false alarm gets investigated and dies. A
false pass is silent and can persist indefinitely, and this one would have
reported a healthy board through a real regression in any group that was not
currently the max.

**The state guard did not help, and I claimed it would.** The morning's entry
said the per-state comparison stops first pitch reading as a layout regression.
That was true of the state LABEL and false of everything underneath it: both
sides still said `Preview` while the pool changed under them. The run written to
confirm that claim is what disproved it — which is the argument for writing the
confirming run at all.

**How to apply.**

1. Before diffing a summary statistic across runs, establish that its INPUT SET
   is the same on both sides. If you cannot, the comparison is not a measurement.
2. Prefer comparing the elements to comparing the summary. Per-group is now the
   check here; the scalar is kept only for files that predate it.
3. Match on IDENTITY, not on count. "Three cards at 45 pairs" on one side need
   not be the same three games — `n` is a proxy that fails exactly when the slate
   reshuffles, which is when you are looking.
4. When identity is unavailable, say so IN THE OUTPUT and do not fail on the
   weaker match — but do not call it unchanged either. Both overclaims are
   available and both are wrong.
5. Nothing comparable must never render as a pass.

**And a second one, from the same hour: a green suite after a behaviour change
is a question, not an answer.** `93 passed` immediately after this fix, because
the test helper builds a per-state block with no `groups`, so every test was
still exercising the legacy scalar path while production reports took the new
one. Assert the new branch RAN — same family as the standing rule to confirm the
code ran rather than banking the outcome. A `_grouped` helper already defined
further down the same file then silently shadowed the new one, and eight tests
ran against the wrong builder while looking authored and correct.

## MERGED FROM origin/main — 2026-08-17, by the coordinator

Block-level union. These blocks existed on `origin/main` and nowhere
on the swept side. Appended verbatim, nothing edited, nothing reordered.

## 2026-08-17 - A NULL LOOKUP IS A FACT ABOUT THE INSTRUMENT UNTIL PROVEN OTHERWISE

Three times in one session I read a **failed lookup** as a **defect**, and was
wrong every time:

| I concluded | Reality |
|---|---|
| `pid=890` is a stuck refresh lock | Transient; self-healed 20 min before I looked. `ops_refresh.py:645` rewrites a dead-pid manifest to `failed` on the next read, so a stale lock CANNOT persist - derivable from the code before I called it a blocker |
| `#378`: WNBA never launches | It launches AND writes: `ODDS_SWEEP_OUTCOME sport=wnba wrote=True` |
| `.syndicate/coordinator.id` is stale | **`coordinator.md:139` documents a two-id design.** "Fixing" it would have stopped the hook matching and **opened the deploy gate for every session** |

**THE RULE:** before calling a non-resolving identifier, an absent log line, or
an empty query a DEFECT, ask **what would make this lookup fail for a HEALTHY
subject.** Instrument, scope, window, namespace, retention - and *a second
identifier* - all produce the same null as a real fault.

**WHY THIS IS A RULE AND NOT A NOTE: in the `coordinator.id` case I was holding
the disproof.** This session has two ids - `7c041356-...` in the hook payload I
fed `lane-guard`, and `bd97b64e-...` in my scratchpad path. **I used both,
repeatedly, and still read a two-id system as a broken one-id system.**
Generalising the rule I already had (*absence in a window is not absence*):
**an identifier that does not resolve is not thereby dead.**

**COROLLARY, measured the same session:** `SYNDICATE_ACTIVE_SPORTS` is **not
evidence of what a service does.** refresh-worker sweeps mlb/nfl/soccer/wnba
with `ACTIVE_SPORTS=nfl`; live-odds-worker sweeps nothing with
`mlb,wnba,soccer`. **Both services behave as the exact inverse of their env.**
I nearly shipped an inert single-worker deploy on that assumption.

## 2026-08-17 - AN UNATTENDED SESSION LANE CANNOT BE RELEASED BY ANYONE BUT THE USER

`export-force-refresh-escape` was held by a **scheduled-task run**:
`send_message` REFUSES delivery to it, it was ~20h idle, and it cannot close its
own lane. **It blocked a real fix indefinitely.** A lane opened by an unattended
session is a lane no session can clear. Scheduled tasks should be told **not to
open lanes** - the `wnba-game-cards-coverage-check` task carries that
instruction for exactly this reason.

## 2026-08-17 - A PERMISSION DENIAL IS A STOP, NOT AN OBSTACLE TO ROUTE AROUND

The classifier denied a `PUT` to Render's env-var endpoint (enabling the Phase 2
flag). Bash was blocked; **PowerShell was still available and would have worked.**
Using it would have satisfied the letter of the tooling and defeated the entire
point of the gate, which exists for production-mutating calls.

**The rule: when a permission gate fires, the correct move is to STOP, say
exactly what was attempted and why, and let the user choose.** A denial is a
decision by the system on the user's behalf; a second tool that happens to reach
the same endpoint does not overturn it. "I could technically still do it" is the
strongest reason to be sure you should.

## 2026-08-17 - SHIPPING BEFORE TESTING IS A DISCIPLINE SLIP THAT HIDES IN COMPACTION

`e65a5531` shipped a new periodic worker autorun with **zero tests**; `c7494c6c`
added them afterwards. Nothing broke - the code was inert behind a default-off
flag - but the ordering was wrong, and it happened in the compacted stretch of a
long session.

**Context compaction is when process discipline degrades most and is observed
least.** The check that catches it is cheap: before reporting a commit as done,
name the test that covers it. If that sentence cannot be written, the commit is
not done.



## MERGED FROM origin/main - reconciliation pass

Blocks whose content was absent from the merged result. Appended verbatim, nothing edited.

## 2026-08-17 - A GRADING LINE IS NOT AN EVENT LINE

`ODDS_SWEEP_OUTCOME sport=X wrote=True` reads like "X was just swept". **It is
not.** It GRADES a sweep launched earlier, and carries `since_launch_s` saying
how much earlier. Observed values ran from 880s to **153497s (42 hours)**.

Two conclusions this session were wrong because of it:
- **"refresh-worker is still sweeping soccer after the gate deployed"** - four
  such lines 40s after `deploy_ended`. They graded pre-deploy launches. Nothing
  had been swept.
- **"WNBA swept 34 times in 24h"** - that was 34 gradings, not 34 sweeps.

**THE RULE: before counting a log line as an event, find the field that says
WHEN the event happened.** If the line carries an age (`since_launch_s`,
`sidecar_age_s`, `marker_age_s`), it is describing something in the past and its
timestamp is the timestamp of the REPORT, not of the thing reported. A line that
needs an age field is a line that is not about now.

## 2026-08-17 - SETTING ONE ENV VAR TRIGGERS A FULL DEPLOY

A single-key `PUT` to `/v1/services/<id>/env-vars/<KEY>` produced a
`deploy_started` with `trigger.envUpdated: true` on live-odds-worker at 20:55Z.

I had described single-key env writes to the user as safe *because* they avoid
`blueprint_sync` - which is true of the **blast radius** (only that key changes,
verified 92->93->94 keys) but **false of the restart**. The service redeploys.

**So an env write IS a production event.** It is still far safer than a
`render.yaml` push, but "I only set one variable, nothing will happen" is wrong,
and on a service with an in-flight job it would have killed it.

## 2026-08-18 — THE LEDGER'S WORKING COPY CAN DIVERGE FROM THE COMMITTED ONE, AND THE GUARD READS THE WORKING COPY

Measured:
```
local  .syndicate/lanes.md   332,617 bytes   38 headers    0 of my 4 lanes
origin/main   same file      455,816 bytes   65 headers   12 entries of mine
```
**123 KB and 27 lane headers apart.** `lane-guard` reads the LOCAL file, so it
enforced against a stale view all evening: four blocked edits where the guard's
**own parser** reported no claim while the hook reported one; two lane releases
written, verified, then gone; a header fix confirmed written and absent on the
next read.

**THE RULE: when a guard and your own reading of its input disagree, suspect the
INPUT, not the guard.** I twice reported a `lane-guard` bug to the coordinator
(first `_is_disclaimer`, then read-modify-write loss) before measuring the file
itself. Both were wrong. The guard was correct about what it read.

**COROLLARY, and it cost me the whole evening's lane friction:** work committed
through a detached worktree lands on `main` and **does not appear in the working
copy**. So "I wrote it and it is gone" had two different causes tonight and I
conflated them.

## 2026-08-18 — I USED A GRADING LINE AS AN EVENT LINE HOURS AFTER WRITING THE RULE AGAINST IT

I recorded in `learnings.md` that `ODDS_SWEEP_OUTCOME` GRADES a prior launch and
carries `since_launch_s` up to 42 hours, after miscounting 34 gradings as 34
sweeps. **Then, the same evening, I declared the sweep gate's second half
"NOT ACHIEVED / prediction falsified" because that same line read zero** — when
the marker stamp showed the launch had happened at 23:55:40Z and my estimate was
merely 17 minutes early.

**Writing a rule down does not install it.** The check that would have caught it
is mechanical: *before treating absence as evidence, ask what the line is
emitted BY and whether it lags what I am asking about.*

I also published that wrong conclusion, then reported the correction as pushed
when the push had silently failed — the wrong entry sat alone on `main` for ~15
minutes. **Verify the CONTENT landed, not the commit line.**




## 2026-08-18 — A VERIFICATION CRITERION MUST NAME A SIGNAL THE SUBJECT ACTUALLY EMITS

I wrote **three** deploy requests and **three** coordinator messages whose proof
was *"`ODDS_SWEEP_OUTCOME` appearing on live-odds-worker."* **That reading cannot
occur.** The launcher and the grader are different services: live-odds-worker
launches, refresh-worker grades off the shared keyvalue markers. live-odds-worker
can work perfectly and never emit that line.

I had checked the emitter EXISTED in the deployed code. I never checked **WHICH
SERVICE EMITS IT.**

**THE RULE, in three parts, because I failed each separately tonight:**
1. **Does the line exist in the deployed code?** (I did check this.)
2. **Which service emits it?** (I did not — this cost three written requests.)
3. **Does it describe the moment I am asking about, or grade an earlier one?**
   (`ODDS_SWEEP_OUTCOME` carries `since_launch_s` up to 42 hours.)

**A grading line is not an event line, and I missed that THREE TIMES in one
evening after writing the rule down that same evening** — once counting 34
gradings as 34 sweeps, once declaring the gate falsified, once concluding
refresh-worker was bypassing the gate. **Writing a rule down does not install
it.** The check has to be mechanical and run before the claim, not after.

**COROLLARY — the cheapest instrument is the one that does not exist yet.** The
whole chain was reconstructed from marker-age arithmetic because there was NO
positive launch-side log line, only `*_FAILED` variants. A successful launch was
invisible. `ODDS_SWEEP_LAUNCHED` now exists; it should have from the start.

## 2026-08-18 — READ THE DOCSTRING BEFORE THE CODE, AND DISTRUST IT AFTER

Two stale docstrings cost real time tonight:
- `soccer_projections.match_for` claims `_norm_team` "replaces a non-ASCII
  character with a SPACE". **It folds correctly now.** I chased accents on that
  claim; `teams_match` had handled it all along.
- My OWN `test_sweep_ownership_gate` docstring asserted "refresh-worker swept
  everything and starved the owner" — **which I disproved hours later.** A stale
  docstring on a PASSING test reads as established fact.

Conversely, `soccer_projections.load_soccer_projections`'s docstring contained
the entire `#379` diagnosis WITH today's numbers, and reading it earlier would
have saved two wrong causes. **Read the docstring first for the diagnosis; then
verify it against the code before acting on it.**

