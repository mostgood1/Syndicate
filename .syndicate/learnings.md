# Syndicate — Learnings

> **Append only.** Rules must be obeyable by a session with zero context.
> `FORBIDDEN` = never do this again. `EXONERATED` = ruled out, stop
> re-investigating.

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

### 2026-08-12 — FORBIDDEN: never point a worker publish URL at a public hostname
- What we believed: the publish target was an internal detail.
- What was actually true: `SYNDICATE_WEB_PUBLISH_URL` was set to the web
  service's public URL, so every artifact was POSTed out to the public
  internet and back in — billed on the way out. ~1.79 TB of service-
  initiated egress traced to this.
- How we found out: traced service-initiated egress per service, then read
  the publish path in code.
- The rule going forward: **any service-to-service call inside Render must
  use the internal private-network hostname. Same-region private traffic
  is unbilled. Audit every URL env var against this rule before adding a
  new one.**
- Cost: a month of overage billing plus the investigation.

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

### 2026-08-13 — A guard can measure a number that moves without the system moving
- What we believed: the board was stale because building it had become
  slow (the `#414` thread — four hours of apparent slowness).
- What was actually true: builds were not running **at all**.
  `MEMORY_GUARD_ABORT stage=pre_source_state_fingerprint` fired 300
  consecutive cycles and aborted before the first stage. At ~11:02 the
  kernel promoted ~243 MB of page cache from `inactive_file` to
  `active_file`; the guard credits only `inactive_file`, so effective
  headroom fell 1877 → 1643 MB **while total memory in use fell 3120 →
  2705 MB.** `anon` drifted +18.9 MB across all 300 samples — nothing
  about the system's real memory pressure changed.
- The rule going forward: **when a threshold decides whether work runs,
  audit what moves the quantity it reads — not just the constant.** A
  stale constant is the easy half. A quantity that swings on kernel LRU
  bookkeeping makes the guard's verdict unrelated to the risk it guards.
  Guard on unreclaimable memory (`anon + shmem + slab_unreclaimable`),
  which is what an OOM kill actually responds to.
- Corollary that generalises past memory: **if usage going DOWN can make
  a guard stricter, the guard is reading the wrong quantity.** That
  inversion is a complete proof on its own — no baseline needed.
- Cost: 4h12m of a stale board served as current, and an investigation
  aimed at build duration.

### 2026-08-13 — A criterion has a DIRECTION, and checking it is free
- What we believed: `#401`'s maintenance runner was silently broken —
  "has not executed in 15 hours and I do not know why", after an earlier
  "the old shared stamp is suppressing it" was falsified.
- What was actually true: a 24h interval with 15.62h elapsed. Not due,
  short by 8.38h.
- The sharper point: **the silence itself already excluded the suspected
  cause.** A failed stamp write leaves `last = 0.0`, and `_due()` treats
  missing-or-unreadable as due — so a broken stamp runs maintenance
  **every tick**. The hypothesis and the symptom pointed in opposite
  directions. No instrumentation was needed.
- The rule going forward: before instrumenting, ask **which way the
  suspected fault would push the observable.** Extends "a criterion is an
  instrument too": an instrument has a sign as well as a denominator.

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

### 2026-08-13 — Confirm an instrument can emit non-zero before believing its zero
- What we believed: `#416` was broken, because web's `/mlb/api/live-lens`
  reported no live probability anywhere.
- What was actually true: that endpoint reports `simContextAvailable: False`
  on all 15 games and `gameLens source: ABSENT` on all 60 lanes — it
  **structurally cannot run** the Monte Carlo whose output was being read. A
  working fix was one step from being filed as broken.
- The sharper point: **a wrong number gets caught by disagreeing with
  something. A null agrees with everything.** A zero is evidence only once you
  know what would make the instrument read non-zero.
- The rule going forward: before believing a zero, produce a case that makes
  the same instrument read non-zero — or build the reading so it carries its
  own liveness proof. `snapshot_prop_keys` is populated before any filtering,
  so a zero beside a non-empty key list is a *measured* zero, not a blind one.

### 2026-08-13 — A pooled denominator can make a measurement unreadable
- What we believed: `snapshot_live_prob_seen: 0 of 67` meant the writer never
  sent the value.
- What was actually true: 13 of 15 games were final, and final props come from
  `_final_live_prop_rows_from_registry` — a path that never computes a live
  probability and **correctly** emits null. Most of that denominator was rows
  that could never have been non-zero.
- The rule going forward: when a counter pools populations with different
  eligibility, **split it by the thing that determines eligibility** before
  reading it. "The mechanism failed" and "most rows were never eligible"
  produce the identical zero. Sibling of the wrong-denominator shape recorded
  the same night, arrived at from the other direction.

### 2026-08-13 — `git log --format=%an` is zero evidence in this repo
- What was actually true: every commit is authored `github-actions[bot]`, so
  authorship confirms whatever hypothesis is brought to it. Three attributions
  in one night resolved against the lane they named; `#409` was claimed by two
  lanes and `#414` by four.
- The rule going forward: **the only working discriminator is which FILES a
  lane has touched.** Verify a ticket number against `origin/main` immediately
  before pushing, not when drafting — the gap between choosing and pushing is a
  real race.

## An instrument's SPAN is not its NAME (2026-08-13)

`SLOW_ROW_PROFILE` was written to measure per-row cost in
`_game_bet_candidates_from_game`. Its closing mark was placed at the **end of
the function**, after the entire post-loop tail, so the final delta covered
*last iteration + tail*. On `rows=1` games that single delta **was the whole
function**.

It produced `rows=1 total_s=399.40 min=p50=max=399.398` and the conclusion
"one pathological iteration takes 100–400s". The row loop was never implicated
by the data.

**Two failure modes worth separating:**

1. The number was real and the span was wrong. Nothing about the output looked
   malformed.
2. `SLOW_ROW_PROFILE` and `SLOW_GAME_CANDIDATE` agreed to six decimal places,
   which was read as two independent measurements corroborating. **They were
   the same quantity measured twice.** Agreement produced by shared
   construction is not confirmation — the same mechanism as dividing by the
   wrong denominator across seven games and reading the consistency as
   evidence.

**Rule.** When adding a timing span, state what it EXCLUDES, and place a mark
at every boundary you intend to attribute across. Name each segment by the work
it *contains*. If two instruments agree exactly, first prove they are not
reading the same clock interval.

**The sharp part:** `a span's NAME is not its COVERAGE` was already recorded in
`todo.md` earlier the same night, and the instrument written to act on it broke
it. **A rule does not protect the code that implements it.**

## Authorship cannot be read from `git blame` here (2026-08-13)

Every commit in this repo is authored `github-actions[bot]`. A lane's work was
attributed to the wrong session cross-session; they disproved it by listing the
files they had touched. **Use file-touch sets, not `%an`.** The near-miss:
had they accepted the framing to be agreeable, unfamiliarity with the code
would have been laundered into apparent endorsement, and the misattribution
would have become unfalsifiable — the one person able to deny it would already
have appeared to confirm it.

`syndicate/features/intelligence.py` and `syndicate/blueprints/intelligence.py`
are a confusable pair and were the likely source of the error.

### 2026-08-10 — a briefed premise is a hypothesis, not a starting condition
- What was believed: soccer sims were OFF by standing instruction, so the lane
  was working against a mitigated system.
- What was actually true: the autorun flag was `'true'` live, all three sim
  fixes were ancestors of the deployed commit, and a 20m13s sim was running.
  **Nothing had been mitigating it all evening.**
- The rule going forward: **verify the premise of the brief before writing code
  against it.** Checking cost one env query and one ancestry check; it changed
  the urgency of the whole lane.

### 2026-08-10 — an instrument's blind spot will be mistaken for a finding
- What was believed: the publish sweep was eliminated, because before/after
  samples showed ±20MB deltas.
- What was actually true: **a before/after pair cannot see a transient
  allocated and released between its endpoints.** In-sweep sampling later found
  lifts to **+642.6MB** the endpoints never saw. The elimination was an artifact
  of the instrument, not a property of the system.
- Then the correction was itself wrong: the retraction rested on one excursion
  landing inside a sweep, at a **16–20% duty cycle** — a 1-in-5 event reported
  as decisive.
- The rule going forward: **ask what the instrument cannot see before trusting
  what it shows, and compute the base rate before believing a coincidence.**
  Both directions of this error were made in one evening on the same candidate.

### 2026-08-10 — segment on process boundaries before any neighbour-based test
- What was believed: a `+529.5MB` excursion had been observed with no publish
  sweep running — the headline evidence for restoring an elimination.
- What was actually true: **the detector's forward neighbour was a post-reboot
  sample** (392.9MB). An ordinary sample on a rising baseline scored as a large
  excursion. The original analysis was boot-segmented; that was regressed when
  the detector was rewritten as a live watcher, and nothing in the output said
  so — a fake excursion looks exactly like a real one.
- The rule going forward: **any local/neighbour test must segment on boot
  first.** A restart is a discontinuity, not a data point.

### 2026-08-10 — counts are the wrong denominator when the cost is bytes
- What was believed: a marginal cost of `−1.60 MB per artifact` showed the
  publish sweep was cheap.
- What was actually true: `published_count` counts files *published* and
  `pulled_count` counts files *written*; **neither counts bytes held.** Sweeps
  with `pub=0` still cost `+488.6MB`, and pulls with `pulled=0` cost `+575.7MB`.
  The rate was fitted against a denominator that does not measure the cost —
  and over a 15–34 population when the range of interest was 73–103.
- The rule going forward: **before quoting a rate, check the denominator
  actually measures the thing being paid for, and that it spans the population
  of interest.**

### 2026-08-13 — Presence is not reachability: verify the PATH, not the symbol

**Overturned belief:** that confirming a fix is present in the deployed code
means the observed behaviour goes through it.

Five failures in one lane, same root. A commit range read as a call path
(`#331` — primitives shipped, call site uncommitted, reported as landed). Two
identically-named memory emitters unified when there were three (`#327` — the
third called the stderr-only logger directly). Three real code paths patched for
`#334`, none of which the serving route takes — the endpoint had **four**
readers. One of two copy-pasted trace blocks fixed (`#338`). And finally the
reporting script that skipped dict-valued keys, so the "still broken" reading was
the tool, not the endpoint.

**What actually works:** enumerate the callers and fix the choke point they all
share. The `#334` fix that finally held touched **zero call sites** — the logic
went *inside* the shared function, which is what made it unmissable. A grep, a
commit range, and a name match all answer "is this symbol here"; none answers
"does the path that produces this observation execute this code".

**State a falsifiable discriminator before deploying.** Ours was "three
microsecond-apart sub-values means the recompute never ran; one consistent value
means it did." It read 3 after each of three targeted fixes and 1 after the
enumerated one — so the deploy that worked was distinguishable from the three
that did not, without argument.

**Corollary — retracting a caveat matters as much as retracting a finding.** I
published "the Render logs `text` filter is unreliable", which was false: it is a
correct case-insensitive substring match and I had judged absence from a 150-char
truncation of a 1500-char line. Two other lanes had conclusions resting on zeros
from that API. A false warning about an instrument silently devalues every
correct reading anyone takes with it. Trust absence (a nonsense token returns 0),
verify presence (counts inflate on substring containment), and note results come
back **oldest-first regardless of `direction`**.


### 2026-08-13 — A safety gate answers ITS question, not the one you were asked

- What we believed: `scripts/deploy_preflight.py` returning `CLEAR` meant it
  was time to deploy `#419`. A monitor was armed on exactly that.
- What was actually true: the user's condition was **"after tonight's slate
  clears."** The gate's condition is **"would a deploy kill a job right now."**
  Those are different, and the gap is most of a day. It fired `CLEAR` at
  **13:07 CDT, mid-slate**, with games at 14:08 / 15:06 / 18:30 / 21:08 / 21:10
  still to come — it had simply caught a lull between sims, `in_flight: 0`.
  Acting on it would have restarted refresh-worker during live games.
- The rule going forward: **when a human states a condition, encode THAT
  condition, not the nearest existing check.** A pre-built guard is evidence
  about its own predicate only. Before arming any watcher, write down the
  instruction's condition and the instrument's condition as two separate
  sentences; if they are not the same sentence, the instrument is not
  sufficient and needs the missing clause added explicitly.
- Sibling of "a criterion has a DIRECTION": there the fault was not asking
  which way a check pushes; here it is not asking what the check is *about*.
- Cost: none — caught by reading the clock in the gate output before acting.
  The scheduled-task version had the right condition (00:00–04:59 window) only
  because the window was written from the instruction rather than the tool.

### 2026-08-13 — "Identical to origin" does not mean "absent from the commit"

- What we believed: a cherry-picked deploy candidate excluded another lane's
  undeployed `#417` fix, because `memory_observability.py` was byte-identical
  to `origin/main`.
- What was actually true: `#417` was **already on `origin/main`** via an
  earlier commit, so identical meant "my commit did not touch this file" —
  the fix was present the whole time. The candidate contained it.
- The sharper point: a diff against a base is a statement about the DELTA, and
  it was read as a statement about the CONTENT. Two different questions:
  "did I change this file" (`git diff base..target`) versus "what is in this
  file" (`git rev-parse target:path`, or read it).
- Direction of the error matters here: the wrong inference was *pessimistic*
  and got written into a lane as reassurance about scope, which is the shape
  that survives review. It was only caught because the live commit moved and
  forced a re-measure.
- The rule going forward: **to claim a change is ABSENT from a deploy, compare
  the target against what is LIVE, not against the branch you built on.** The
  live commit is the only baseline the deploy actually acts on, and it moves
  under you while you work.

### 2026-08-13 — "Who reads this env var" is a grep question; "does this service read it" is not
- What we believed: an env key whose only readers live in `scripts/` or
  `vendor/` is dead on the web service, because web's startCommand is gunicorn.
  A repo-wide grep for the key name settles it.
- What was actually true: `MLB_LIVE_LENS_DIR`'s only reader is
  `_resolve_mlb_live_lens_dir()` in a vendored module — and
  `flask_frontend.py:135` **calls that function at module scope**, so the read
  executes on import, and `syndicate/features/mlb/live_lens.py` imports it.
  Deleting the key would have broken MLB live-lens on web. The grep was right
  about the file and wrong about the service.
- How we found out: only by building a call graph and asking what is reachable
  from the *specific symbols* web imports. Three attempts were needed:
  1. Enclosing-function analysis alone — said "not reachable" for a key that is
     read on every import. **Wrong in the dangerous direction.**
  2. Adding module-level calls — swept in a call inside
     `if __name__ == "__main__"`, and briefly implied that importing a vendor
     module starts a background loop on the web service. **Wrong in the
     alarming direction.**
  3. Excluding `__main__` blocks and following `threading.Thread(target=fn)`
     as a graph edge — `target=` is a Name, not a Call, so a naive walker never
     traverses the thread body and every key read inside it reads as dead.
- The rule going forward: **reachability has three entry classes, and a trace
  that omits any one of them is not evidence. (1) module-level statements,
  including calls to functions defined elsewhere in the file; (2) the specific
  symbols another module imports — not the module as a whole; (3) indirect
  targets: thread/process `target=`, callbacks, registries, decorators.**
  Exclude `if __name__ == "__main__"`. A negative result from an incomplete
  trace is indistinguishable from a real one, so state which classes were
  covered whenever the conclusion is "unreachable, safe to delete."
- Also: an audit that excludes `vendor/` is not an audit of this repo. Vendored
  code is executed in production. The first pass excluded it and reported seven
  keys with "no reader anywhere" — all seven were artifacts of the exclusion.
- Cost: caught before anything was deleted. Would have been a production
  breakage on the next web deploy had the first pass been applied.

### 2026-08-13 — FORBIDDEN: never `cat` a ledger file into hook stdout — a hook delivers the obligation, not the content

- What we believed: that `session-start.sh` exiting 0 with all five section
  headers present in its stdout meant the ledger reached the session.
  `HOOKS.md` verification step 4 — "`bash .claude/hooks/session-start.sh`
  prints the ledger" — was accepted as proof and reported as PASS.
- What was actually true: the harness caps hook stdout at ~2KB of injected
  context and persists the remainder to a file. v1 emitted **39,924 B**
  (session `ac67a9f1`, `hookName=SessionStart:startup`, `exitCode=0`,
  `durationMs=459`, `type=hook_success`). About **5%** reached context, and it
  was the least operational 5%. Byte offsets on a 42,836 B run:
  `VERIFIED STATE` 40 (in), `OPEN LANES` 12,693 (cut), `STANDING RULES` 42,345
  (cut), `OPEN OBLIGATIONS` 42,551 (cut), the `/lane /preflight /checkpoint`
  line 42,709 (cut). **Every section the hook existed to deliver was past the
  cut.** The hook fired perfectly and delivered nothing that mattered.
- How we found out: the CLI could not be driven headlessly (OAuth expired), so
  we read the transcript of a session that had already started —
  `~/.claude/projects/<project>/ac67a9f1-*.jsonl`, line 3, an `attachment`
  record carrying `stdout`, `exitCode`, `durationMs`, `hookEvent`. The
  truncation was stated there in plain text: "Output too large (38.7KB) ...
  Preview (first 2KB)". It was legible the entire time. Nobody had looked at
  the delivery side.
- The rule going forward: **a hook is a channel with a budget, and the only
  measurement that counts is what ARRIVES, not what was emitted.** Verify a
  hook by reading the `attachment` record in the consuming session's
  transcript (`stdout` length, `exitCode`, `type`), never by running the script
  in a terminal — a terminal has no cap, so it can only ever confirm the
  emitter. Keep hook stdout under **2,000 B**. A hook's job is to deliver the
  OBLIGATION to read the ledger plus the few facts too costly to miss; the
  ledger itself gets read from disk by the session. Direct sibling of
  `2026-08-13 — Presence is not reachability`: the content was present at the
  emitter and unreachable at the destination.
- Also — the size was seen and misread. The v1 output was reported as "524
  lines injected at every session start ... a real context cost worth knowing
  about." The number was in hand and was filed as an *expense* rather than as
  *evidence of a defect*. A quantity that exceeds a limit is not a cost, it is
  a failure. When a measurement is large, establish what it is large relative
  to before describing it.
- Cost: ~1 hour, self-inflicted, caught before any session relied on the
  digest. `f6fec4f1` (pushed as `f6fec4f1`) shipped a hook reported as working
  that was ~5% functional.

### 2026-08-13 — EXONERATED: `shell: "bash"` in a Windows hooks block works

- Named as the likely culprit when SessionStart could not be verified ("if the
  ledger doesn't appear, the likely culprit is `shell: "bash"` not being
  honored"). Measured working: session `ac67a9f1`, Claude Code **2.1.227**,
  `hookName=SessionStart:startup`, `exitCode=0`, `durationMs=459`, `stderr`
  empty, `type=hook_success`, on a `.sh` script invoked as
  `"$CLAUDE_PROJECT_DIR"/.claude/hooks/session-start.sh`.
- Do not re-litigate the shell. Note that `bash` is **not** on the Windows
  system PATH here (`which bash` fails from PowerShell) — the `shell: "bash"`
  field is what resolves it, so the exec form `{"command":"bash","args":[...]}`
  would have failed where this succeeded.
- The real failure was truncation, above. A guess about a failure mode is not a
  finding; this one was wrong while the data to predict the right one was
  already in hand.

### 2026-08-13 — A guard that has never once PASSED is not a guard

- What we believed: `checkpoint-guard.sh` enforces the `/checkpoint`
  obligation that `CLAUDE.md` states in the strongest terms — "if the session
  ends without a checkpoint, the work is considered lost."
- What was actually true, measured across every transcript in this project:
  **27 Stop-hook deliveries, 5 sessions, `exitCode 1` on all 27. Zero exit 0.**
  `.syndicate/.last-checkpoint` had never been created, so the pass branch at
  line 17 was unreachable. Sessions that *did* checkpoint were told they had
  not. And the delivered stderr is prefixed **"Failed with non-blocking status
  code"** — exit 1 on `Stop` informs, it does not hold the session. The
  obligation was enforced by a log line that was wrong every time it fired.
- The rule going forward: **a guard's pass branch needs a witness too.** The
  ledger already says "before believing a zero, produce a case that makes the
  instrument read non-zero" — this is the same rule pointed at the other
  branch. An alarm that has never been silent is indistinguishable from an
  alarm wired to a constant. Check the distribution of a guard's outcomes
  before quoting any single one: all-fire and all-pass are both evidence of
  a broken predicate, not of a system state.
- Corollary on denominators, third instance in this ledger: the guard counts
  the **whole dirty worktree** (64 files at the checkpoint that found this;
  exactly 1 was the session's). In a repo where pipeline output is
  permanently dirty, its condition is ~always true.
- Also: **exit code is the enforcement contract, and it differs by event.**
  `PreToolUse` exit 2 genuinely blocked a cross-lane `Edit` in the same
  session's testing. `Stop` exit 1 did not. Do not infer that a hook enforces
  from the fact that it runs, exits non-zero, and prints the right words.
- How we found out: a lane opened for no purpose but to test the enforcement,
  with probes run through the harness and results read from `attachment`
  records — never from running a hook in a terminal. Direct application of the
  08-13 FORBIDDEN entry, which was written after the emitter-vs-destination
  distinction cost an hour.
- Cost: none yet. The exposure is every session since the hooks landed
  believing its checkpoint state had been checked.

### 2026-08-13 — A discriminator that is only emitted on FAILURE cannot confirm a fix

- What we believed: `/preflight`'s falsifiable-discriminator requirement was
  satisfied. The plan said, in the lane and in `deploys.md`, "read `basis`
  FIRST — `basis=unreclaimable` proves the new path executed."
- What was actually true: `memory_headroom_snapshot`'s dict is printed only
  inside the abort branch (`pipeline/intelligence_state.py:3215`), and the
  other call site (`:516-527`) logs nothing at all. So `basis` is emitted
  **only when the guard refuses.** A working fix leaves it permanently
  silent. The discriminator was readable only in the world where the fix had
  failed.
- The rule going forward: **when choosing a signal to prove a fix ran, check
  which BRANCH emits it.** A signal on the failure path proves the failure
  path; it can never prove the success path. Before deploying, ask "if this
  works perfectly, what line appears?" If the answer is "none", there is no
  liveness proof and the deploy ships blind, however green the tests were.
- Sharper: this is the mirror of `confirm an instrument can emit non-zero
  before believing its zero` (2026-08-13). That entry covers a zero from an
  instrument that never ran. This one covers a *silence that is indexed to
  success* — the observation and the desired outcome are the same event, so
  the measurement carries no information.
- Cost: a production deploy with no way to confirm reachability, on a lane
  whose own ledger already carried `presence is not reachability`.

### 2026-08-13 — A watcher's headline can contradict its own body

- What we believed: the re-warm test had passed. The watcher printed
  `RESULT: RE-WARMED TO PRE-FIX LEVELS AND HELD`.
- What was actually true: the same output block reported
  `builds after peak=0`. The exit condition was `peak_memory >= 3500MB` with
  **no requirement that a build occur after the peak** — so "HELD" was a word
  in a format string, not a measured property. The peak itself (4042.6MB)
  was a transient intra-build spike, at which the NEW formula would also have
  refused (996MB available vs a 1900 floor).
- The rule going forward: **the label a script prints is an assertion, and it
  must be entailed by the condition that triggered it.** When writing a
  watcher, state the exit condition in the output next to the verdict, so a
  reader can check the inference rather than trust the adjective. Sibling of
  `an instrument's SPAN is not its NAME` — same failure, moved from a timing
  mark to a boolean.
- Also recorded: a 100-line Render log query on refresh-worker spans **~35
  seconds**. Any "n samples above X" from one query is a statement about that
  window. A count of 0 there sat beside a 4042.6MB sample from six minutes
  earlier.

### 2026-08-13 — A guard's "is this mine" input must not default to the locked state

- What we believed: `lane-guard`'s own-lane exemption was working, and probe C
  (`.current-lane` empty -> the guard blocks your own files) was a synthetic
  condition constructed to test the branch.
- What was actually true: `.syndicate/.current-lane` **did not exist anywhere
  in the repo** before it was created on 08-13, so `Current lane: 'none'` was
  the baseline for every session that ever ran. It has already bitten:
  session `ab30bcc8` was refused `tests/test_intelligence_state.py`, claimed
  by `intelligence-state-red-baseline` — the lane it was working. And
  `/lane close` step 4 *empties* the marker, so finishing a lane restores the
  locked state for whoever comes next.
- The rule going forward: **when a guard reads an identity token to decide
  "yours vs theirs", the absent case must default to PERMISSIVE-with-a-reason,
  not to deny.** Absent identity is not a hostile identity, it is a missing
  input, and the failure surfaces as a confusing cross-lane collision message
  rather than as "the marker is missing". Same shape as the ledger's
  `unknown must not default permissive`, inverted: there the danger was a
  failed join relaxing a rule, here it is a failed join inventing a conflict.
- Method note, third instance: counting these blocks by grepping `BLOCKED:`
  across transcripts returned **11**. The hook's own source and the counting
  scripts contain the string. Real blocks, filtered to records carrying a
  `tool_result`/`is_error` payload: **4**. Verify presence, trust absence.

### 2026-08-13 — A path one toolchain resolves and another cannot makes a guard pass silently

- What we believed: that a fixture repo built at `/tmp/cgtest` from the Bash
  tool exercised `checkpoint-guard.py`. All four branches returned exit 0,
  including the two that must return 1, and the reading was briefly taken as
  "the guard is inert."
- What was actually true: the guard was fine. `/tmp` is a Git Bash mount that
  **native Windows Python cannot resolve**, so `os.path.isdir(root +
  "/.syndicate")` was false and the script fail-opened at its first check —
  before reaching any logic under test. Rebuilt at `C:/tmp/cgtest`, all four
  branches discriminated correctly, including the pass branch.
- How we found out: the run printed nothing at all — no stderr from any of the
  four cases. A guard that is genuinely inert still reaches its own logic; one
  that is silent across every input is usually not being reached.
- The rule going forward: **this machine has two path universes, and a value
  that crosses between them fails open rather than erroring.** Bash-tool paths
  (`/tmp`, `/c/...`) are invisible to native Windows Python and to `python3`
  invoked from PowerShell; `git cat-file blob origin/main:path` is mangled by
  MSYS arg conversion into `origin\main;path` and returns an empty pipe, not an
  error. Fixtures and payloads handed to a Windows interpreter must use
  `C:/...`. When a check produces no output at all, verify it reached its own
  code before believing its verdict — extends
  `2026-08-13 — Confirm an instrument can emit non-zero before believing its zero`.
- Three instruments failed clean in this one session — the `/tmp` fixture, the
  MSYS-mangled `git cat-file`, and `grep -c $'\r'` inside a `for` loop, where
  the pattern degenerated and matched every line, reporting CRLF in files that
  `od` showed were pure LF. Every one of them read as a *good* result.
- Cost: ~10 minutes and one wrong statement to the user, retracted in the same
  turn. Nothing shipped on it.

### 2026-08-13 — A free-text status field cannot be a predicate; test guards against the ledger, not against synthetics

- What we believed: that tightening the lane test from the substring `/OPEN/`
  to a literal `/ — OPEN/` was correct and complete. It was verified against
  hand-written headers covering `OPEN`, `OPENED`, `REOPENED`, `CLOSED`, `DONE`.
- What was actually true: the synthetics encoded the same assumption as the
  code — that status is one word. Within the hour a real session relabelled its
  lane `— DEPLOYED, MEASUREMENT OPEN —`, which the strict test rejects and the
  old substring test accepted. The lane sits under `## OPEN`, its owner
  considers it open, and `lane-guard.py` returns exit 0 for its files.
- How we found out: a routine `git diff` during `/checkpoint`, not a test. The
  hole existed for roughly 20 minutes with nothing reporting it.
- The rule going forward: **a guard whose input humans hand-write must be
  tested against the actual file, not against examples written by the same
  person who wrote the guard.** Re-run guards over the live ledger after any
  parsing change, and diff the set they classify as open against the lanes
  physically under `## OPEN` — a mismatch is the whole test. Where a field is
  free text, match a word (`\bOPEN\b`), never the whole field, and never a bare
  substring.
- Cost: no bad edit landed. The window was open ~20 minutes and was found by
  accident, which is the part worth fixing.

### 2026-08-13 — A discriminator that only emits on FAILURE cannot confirm success
- What we believed: `#417`'s deploy could be verified by reading a `basis`
  field added to the memory snapshot — `basis=unreclaimable` proving the new
  code path ran, `basis=reclaimable_cache` proving it degraded. This was chosen
  deliberately, to avoid trusting a bare zero.
- What was actually true: the snapshot is printed only inside the abort branch
  (`intelligence_state.py:3215`), and the other call site
  (`_board_build_has_memory_headroom`) logs nothing at all. So `basis` is
  emitted **only when the guard refuses** — i.e. only when the fix has failed.
  A working fix leaves it silent forever, and its absence is a fact about the
  emitter, not about the code.
- The rule going forward: **when choosing a liveness signal, ask which branch
  emits it. If the only emitter is the failure path, the signal cannot
  distinguish "working" from "never ran" — the two produce identical silence.**
  Put the proof on the path you expect to take, not on the one you are trying
  to eliminate. Direct sibling of "confirm an instrument can emit non-zero
  before believing its zero"; that entry covered a zero, this one covers a
  total absence, which is worse because nothing appears at all.
- Cost: none yet — caught before it was quoted as evidence. The deploy is
  consequently unverifiable by its own designed check, and rests on the 24h
  outcome read instead.

### 2026-08-13 — A watcher's LABEL must be entailed by its exit CONDITION
- What we believed: a background watcher reported
  `RESULT: RE-WARMED TO PRE-FIX LEVELS AND HELD`, which was read as the deploy
  surviving load.
- What was actually true: its exit condition was only `peak_memory >= 3500MB`.
  It never tested "held". Its own output line two rows down said
  `builds after peak=0` — the label and the data contradicted each other in the
  same four-line report.
- The rule going forward: **the words a monitor prints are a claim; write them
  from the condition that fired, not from the outcome you are hoping for.**
  Before trusting a watcher's verdict, re-read the branch that produced it. Any
  word in the label that does not correspond to a term in the predicate is
  editorial.
- Generalises the `SLOW_ROW_PROFILE` lesson from spans to verdicts: there the
  instrument measured the wrong interval, here it measured the right thing and
  then overstated what it meant. Both were believed because the headline read
  cleanly.

### 2026-08-13 — "Pushed to origin" is not "applied to production"
- What we believed: `571f774b` recorded the render.yaml push obligation as
  closed because "all three are on origin", and the web env-block audit
  (62 -> 52 keys) was treated as done.
- What was actually true: web's LIVE service carries **73** env keys while
  `render.yaml` on origin declares **52**. `blueprint_sync` had not applied.
  The audit is on GitHub and absent from production, and a future sync carries
  a queued, unannounced 21-key reduction.
- The rule going forward: **for `render.yaml`, "on origin" and "in effect" are
  two different measurements, and only the second one matters. Read the live
  service's `/v1/services/<id>/env-vars` and compare counts before recording a
  config change as shipped.** The CLAUDE.md warning that a push applies to
  production is about the *risk* that a sync fires; it is not a guarantee that
  one *has*. Both errors are available, in opposite directions.
- Cost: none yet. Caught while preflighting an unrelated web deploy.

### 2026-08-13 — FORBIDDEN: never edit a file from a read taken earlier in the session

- What we believed: `checkpoint-guard.sh` was the Stop hook, with the two
  defects measured earlier in the session (unreachable pass branch, worktree
  denominator). A rewrite was written, tested four ways, and all four passed.
- What was actually true: **the file had been deleted**. `5cdf45b6` — HEAD at
  this session's start, sitting in plain sight in the session's own
  environment block — deleted `checkpoint-guard.sh`, added
  `checkpoint-guard.py`, and repointed `settings.json`. A parallel session had
  already fixed both defects, better. The rewrite `Write`-created a file that
  had been removed; it sat untracked, invoked by nothing, and the four green
  tests were run against it. The live hook was never executed once.
- How it survived so long: every check was internally consistent. The file
  read fine (a 90-minute-old snapshot), `git status -- .claude` was clean
  (correct — the orphan did not exist yet), and the tests genuinely exercised
  the logic. Nothing disagreed with anything, because everything was measuring
  the same stale object. **The contradiction was only visible in a file nobody
  re-read: `settings.json`, which names the hook that actually runs.**
- The rule going forward: **before editing any file, re-read it, and read the
  config that dispatches to it.** A hook, handler or entrypoint is defined by
  what invokes it, not by its filename. On a shared tree the gap between
  reading and editing is a race, and `Write` silently resurrects a deletion
  rather than failing — a deleted file and a file you have not re-read are
  indistinguishable from the editor's side.
- Corollary: **passing tests are not evidence the right artifact was tested.**
  Four tests, four branches, all green, zero coverage of the running code.
  This is `presence is not reachability` inverted: there the code was present
  and unreachable; here the tests were reachable and the code was absent.
- Cost: ~40 minutes and one resurrected file, caught only because the ledger
  entry a parallel session wrote about their own fix contradicted the plan.
  Read `state.md` before starting a lane, not just at session start — it moves.

### 2026-08-13 — The enforcement layer cannot protect itself, and a lane is one deletable line

- What we believed: that with `lane-guard` wired, concurrent sessions could
  not collide on the same file, and that a lane under `## OPEN` is guarded.
- What was actually true, twice in one hour and by two different mechanisms:
  1. `lane-guard` returns 0 for anything under `.claude/**` before consulting
     any lane (`rel.startswith(".claude")`). Two sessions independently
     root-caused and rewrote `checkpoint-guard` inside the same hour; the
     guard was structurally incapable of noticing. **Three sessions worked
     `.claude/**` with no lane on 08-13**, each privately concluding harness
     work is exempt. The protocol never says so.
  2. A lane's entire protection is one `### slug — STATUS —` line in a file
     several sessions hand-edit concurrently. Deleting that line orphans the
     body into the preceding lane's block: `memory-guard-reclaimable` lost its
     header at ~14:5x and all 4 of its claimed files silently went to exit 0,
     40 minutes after `559d353d` closed the identical hole via the status
     regex. Found by reading a `git diff`, not by any check.
- The rule going forward: **`lanes.md` is executable configuration, not
  documentation, and it is edited by hand by several sessions at once.** After
  ANY concurrent-session ledger edit, re-run the guard over the files that
  matter rather than trusting the file to still say what it said. The cheap
  check is one line: `awk '/^### /{h=$0} /<path>/{print h}' .syndicate/lanes.md`
  — if a file's nearest preceding header is not the lane you expect, the block
  is orphaned. And harness work needs either a stated exemption in the
  protocol or a real lane; three sessions deciding it individually is how the
  one collision that mattered happened.
- Cost: no bad edit landed either time, both caught by reading diffs rather
  than by instrumentation. Roughly an hour of duplicated work on
  `checkpoint-guard` before the collision surfaced.

### 2026-08-13 — A FAILED READ RENDERS AS A RESULT. Five instances, one session, five different tools
- What we believed, five separate times: that a check had returned a
  measurement. Each time it had returned a **failure**, typed identically to a
  real answer, and each was acted on as evidence.
- The five, all inside one session, all in ad-hoc verification written to check
  something else:
  1. `git show "origin/main:.syndicate/learnings.md" | grep -c` returned **0**.
     Git Bash had mangled `rev:path` into `origin\main;.syndicate\...`; git
     errored, `grep -c` counted the empty stream. Read as "the content did not
     reach origin" — it had.
  2. `[ -d "$(dirname "$gd")" ]` where `$gd` was unreadable: `dirname ""` is
     `.`, and `.` always exists. **Ten stale worktree entries printed `LIVE`.**
     The test could not return false.
  3. Unreadable worktree `HEAD` files → "*** NOT reachable, would orphan
     commits ***". The files were not locked, they were already deleted. The
     alarm was raised by the absence of the input, not by the state.
  4. A "did this content survive?" check grepped the **commit message** against
     the file and found nothing, reading as "unique content, do not delete".
     The diff was present verbatim, 108 of 108 lines.
  5. `MEMORY_GUARD_ABORT` "0 samples above 3903MB" from one log query — that
     query spanned **35 seconds**. A 4042.6MB peak had already been seen.
- The shape: **a probe has three outcomes — present, absent, and I-could-not-
  tell — and shell/grep/git idioms collapse the third into one of the first
  two silently.** Which one it collapses into decides whether you get a false
  alarm (3) or a false all-clear (1, 2, 5). Both directions occurred here.
- The rule going forward: **before believing a negative result from a one-off
  check, run the positive control.** Grep for something you KNOW is in the
  file; if that also returns 0, the probe is broken, not the world. It costs
  one command and it caught nothing this session only because it was skipped.
  Corollary: `grep -c` on a pipeline whose upstream can fail is not a count,
  it is a count-or-zero. Check the upstream exit status, or query a way that
  cannot silently produce an empty stream.
- Why this is recorded despite four neighbouring entries already covering
  pieces of it (`a grep excerpt is not the file`, `confirm an instrument can
  emit non-zero`, `unknown must not default permissive`, `absent signal is
  about the emitter`): those are each about a *specific instrument*. This is
  about the **throwaway checks written while verifying something else**, which
  get no error handling precisely because they are not the thing under test.
  Production code that swallowed errors this way would be a defect; in a
  verification one-liner it is the default.
- Cost: none directly — every instance was caught by re-reading. But instance
  (3) argued for preserving a commit that did not need preserving, and
  instances (1) and (2) each briefly produced a confident wrong statement to
  the user.

### 2026-08-13 — The stale-read rule failed on its second application, in a form it did not cover

- The FORBIDDEN entry above ("never edit a file from a read taken earlier in
  the session") was written after a rewrite of a file that had been deleted.
  **Within the same session it was broken again**, differently: a defect was
  REPORTED against `lane-guard.py` — "`memory-guard-reclaimable` is unguarded,
  its status parses as DEPLOYED" — derived by running a copy of `LANE_RE`
  lifted from a read taken ~2h earlier. `559d353d` had already replaced that
  regex, and its comment names that lane as the motivating case. The claim was
  false when written, and it was published to `state.md`, where a parallel
  session could have acted on it.
- Why the existing rule did not catch it: it says do not EDIT from a stale
  read. This was not an edit. A stale read is equally dangerous when it is
  used to MEASURE — and worse, because an edit gets a conflict warning from
  the tooling while a measurement returns a clean, confident, wrong number.
- The generalised rule: **a copy of code in your context is not the code. Do
  not reimplement, reconstruct, or re-run a program's logic to predict what it
  does — run the program.** Here the correct instrument was three lines:
  feed the real payload to the real hook on stdin and read the exit code, the
  only thing the harness acts on. It took one command and gave 5/5 against
  five cases, including the two that mattered.
- Corollary on retraction: the wrong finding was written into `state.md` as
  measured. Retracting it required naming the commit that had already fixed
  it, because "I was wrong" leaves the next session unable to tell whether the
  hole is open. Sibling of `retraction is not innocence` — a retraction has to
  say what IS true, not only what is not.
- Cost: none to the system; the guard was correct throughout. ~15 minutes, and
  one false line live in the shared ledger for ~20 minutes.

### 2026-08-13 — A guard has TWO failure directions, and fixing the loud one is where the silent one survives

- What we believed: that `checkpoint-guard` was fixed. Its denominator was
  scoped to the session (`5cdf45b6`), then a second witness was added so a
  session that wrote the ledger but skipped `/checkpoint` step 7 was no longer
  told it had lost work (`3042c5bc`). Eight fixture cases, all green.
- What was actually true: **every one of those eight cases tested the same
  direction.** They all asked "does this session get the right verdict for its
  own actions". Not one asked "can a DIFFERENT session's action change my
  verdict". The denominator had been made per-session while the witness,
  `.syndicate/.last-checkpoint`, stayed repo-global and untracked. So:
  - **FALSE WARN** — loud, annoying, noticed immediately, fixed first.
  - **FALSE PASS** — silent. Session A checkpoints at 15:10 and touches the
    shared marker. Session B edited code at 15:05 and stops without
    checkpointing. B's newest work predates the marker, so **B passes** and its
    work is lost — the exact outcome the hook exists to prevent, caused by
    another session doing the right thing.
  Reproduced against `3042c5bc`: B edits, never checkpoints, A touches the
  marker → **exit 0**. Positive control with the marker removed → exit 1, so
  the probe discriminates and the 0 is a verdict, not a broken instrument.
- How we found out: the `hooks-test` session derived it from the design and
  said so; it was reproduced here rather than accepted. Worth noting the
  control is what made the result trustworthy — the prescription in
  `A FAILED READ RENDERS AS A RESULT` working the first time it was actually
  applied, after two bogus readings in the same investigation (a `/tmp` path
  native Python could not resolve, then `${PIPESTATUS[0]}` reporting `echo`'s
  exit status rather than the guard's). Both printed plausible numbers.
- The rule going forward: **a guard's scope and its witness must have the same
  granularity.** Per-session denominator + global witness is not a fix, it is
  the same hole rotated — and rotated toward the silent direction. Whenever a
  guard is narrowed, ask what else can satisfy it, not just what it now counts.
  Concretely: **when fixing a guard that fails in one direction, write the test
  for the opposite direction in the same pass**, and for anything on a shared
  tree that means a two-actor test — one fixture where a second session's
  action is what changes your verdict. A single-actor fixture suite cannot
  express the failure that matters here, however many cases it has.
- Cost: nothing shipped. `3042c5bc` was held unpushed once the gap was
  confirmed, and the version on origin already has both defects, so nothing
  regressed. Roughly one round of duplicated design work across two sessions.

### 2026-08-13 — Cite the SHA that will exist on origin, not the one your clone minted

- What we believed: that a SHA in backticks is a verifiable evidence pointer,
  and that `state.md`'s rule "every line carries an evidence tag" was being met.
- What was actually true: this repo's standard push path is **cherry-pick onto
  `origin/main` in a throwaway worktree** — `state.md` records three uses on
  08-13 alone — and a cherry-pick **mints a new SHA**. Every SHA written before
  its push therefore names a commit that exists only in the author's clone.
  Measured across `.syndicate/**`: 64 distinct SHA-like refs, **19 local-only
  spanning 69 references**, from several sessions. `git show 363743d0` returns
  nothing on a fresh clone; the same change is there as `559d353d`.
- Worse, and found in the same pass: **one fabricated SHA**, `f2ba6c1`,
  written into `state.md` as if it were evidence for a repair. It resolved
  nowhere — not local, not origin. Nothing in the system catches that. The
  ledger asserts referential integrity and has never checked it.
- The rule going forward: **write the SHA after the push, and write the one
  that is on `origin`.** If a commit must be referenced before it is pushed,
  cite the commit SUBJECT — the subject survives cherry-pick, the SHA does not.
  Deploy SHAs read from the Render API are already origin SHAs and are fine as
  they are. Session ids are visually identical to short SHAs; always prefix
  them with `session`.
- The check, cheap enough to run at any checkpoint — anything it prints is
  either unpushed or invented:

      grep -rhoE '`[0-9a-f]{7,40}`' .syndicate/ | tr -d '`' | sort -u |
        while read s; do git merge-base --is-ancestor $s origin/main 2>/dev/null ||
        echo "UNRESOLVABLE: $s"; done

- **Known baseline, or this check will be ignored within a day.** It prints
  three classes it cannot distinguish, and only the first is a finding:
  1. genuinely unpushed commits — the signal. As of 08-13: `3042c5bc`,
     `d4bb29b5`, `a0c5e7af`, `a3f9ed97`, `bd227fa3`, `8a0d49d8`.
  2. session ids, which are 8 hex chars and look identical to short SHAs —
     `2e6476cd`, `ab30bcc8`, `ac67a9f1`. All are prefixed `session` in the
     text; that prefix is the only thing separating them.
  3. SHAs quoted as examples, including `f2ba6c1` inside this very entry.
  So the clean state is **not 0.** Compare against that list, never read a
  non-empty result as failure — a check whose normal output is ten warnings
  gets scrolled past, which is how `checkpoint-guard` spent its entire life
  warning 28 times out of 28.
- **The baseline is not one number, because the check has TWO inputs**: the
  ledger text you scan, and the `origin` you resolve against. Measured 08-13
  within minutes of each other: **local working tree 10, origin's content
  15.** Both correct. The extra five (054b2306, 0642cdf7, 5b2ca320, cc2e1803,
  e8611888 — deliberately unbackticked here so this entry does not inflate the
  count) sit in a `state.md` block that local has already superseded and
  nobody has pushed yet. Any ledger line quoting a bare baseline number is
  wrong somewhere; say which tree and which origin, or give the list.
- **Scanning origin's content needs `MSYS2_ARG_CONV_EXCL='*'` on this
  machine.** Without it Git Bash mangles `origin/main:path` into
  `origin\main;path`, `git show` errors, and the scan returns **zero tokens**
  — which reads as a perfectly clean ledger. That exact false all-clear
  happened while writing this entry. Always run the control first:

      # must print a large number; 0 means the scan failed, not that you are clean
      ... | grep -ohE '`[0-9a-f]{7,40}`' | wc -l
- Cost: nothing shipped wrong, but for most of 08-13 the ledger's evidence
  pointers did not resolve for anyone reading it from a clean checkout, which
  is the only way a reader who was not present would read it.

### 2026-08-13 — MY OWN DISPLAY TRUNCATION BECAME A FINDING, AND THEN A LANE'S PREMISE
- What we believed: that the MLB board-build cost could NOT be the quote-join
  scan, because two samples showed **1,718,960 rows walked in 33.32s** and
  **1 row walked in 34.28s** — near-identical time, six orders of magnitude
  apart in work. That paradox was written into `quote-join-enrich-cost` as its
  falsification test, with an explicit instruction not to optimise the scan
  until it was resolved.
- What was actually true: the log line is **216 characters** and the printout
  that produced it cut messages at **210**. `rows_walked=1633012` was rendered
  as `rows_walked=1`. **The paradox never existed.** Pulled untruncated, eight
  samples fit `total_s = 19.86 s per million rows walked` with intercept
  −1.07s and R² = 0.918. The scan was the cause all along.
- The sharper point: the truncation did not corrupt the number into something
  obviously broken. It produced **a smaller, perfectly plausible integer** —
  `1` is a legal value for `rows_walked`, and it told a *more interesting*
  story than the truth. A mangled value that looks like data and contradicts
  the obvious hypothesis is far more dangerous than one that looks wrong,
  because it gets promoted to a finding on the strength of being surprising.
- The rule going forward: **a slice width is a property of your printout, not
  of the record. Never read a numeric field out of a truncated line.** When a
  value is load-bearing, re-fetch it untruncated and print the field, not a
  prefix of the message. Corollary for surprise: **the more a datum overturns
  the expected answer, the more it must be re-read at full width before being
  written down** — surprise is the signal to verify, not to publish.
- Sibling of "A grep excerpt is not the file" (2026-08-13), which caught the
  same class BEFORE a defect was filed. This one got all the way into a lane's
  falsification test and an instrument built to resolve it. Same lesson, one
  stage later, and it cost more.
- Cost: a falsification test aimed at a non-existent paradox, and a lane opened
  with an inverted premise. The instrument written for it is still useful, but
  as confirmation rather than discovery. Caught only because a routine status
  question prompted re-pulling the samples.

### 2026-08-13 — A BROKEN GUARD CAN MASK THE REAL PROBLEM. Fixing it is how you find out
- What we believed: `#417` was the whole story. The memory guard credited only
  `inactive_file`, so a kernel LRU promotion moved its verdict ~243MB while
  nothing real changed, and the board froze 4h12m. Fix the quantity, unfreeze
  the board.
- What was actually true: the fix is CORRECT and the board froze again 4.7
  hours later anyway. The live abort line proves both halves at once —
  `'basis': 'unreclaimable'` (the new path is executing), `active_file: 891.7`
  and `inactive_file: 229.8` now credited as reclaimable (it is not refusing
  over bookkeeping), and `anon: 2522.7` (it is refusing because the memory is
  genuinely gone). `anon` went **1163 -> 2603MB in 4.5 hours**. In `#417`
  itself `anon` was FLAT: +18.9MB over 5.4h.
- **So the old guard was hiding a ~300MB/hour leak by failing for the wrong
  reason.** Both the broken guard and the fixed guard refuse; only the fixed
  one refuses for a true reason. A right answer reached by a wrong method
  looked exactly like a healthy system, and the freeze it caused was blamed on
  the method — correctly, but incompletely.
- The rule going forward: **when a guard is found to be reading the wrong
  quantity, do not assume the alarms it raised were all false. Re-derive what
  the CORRECT quantity was doing over the same window.** Had `anon` been read
  on the `#417` samples with the same care as `inactive_file`, the flat +18.9MB
  would have been noticed as the thing that made `#417` bookkeeping — and its
  later non-flatness would have been the leak, visible hours earlier.
- Corollary for verification: **the liveness proof this deploy "could not have"
  arrived exactly when the fix stopped succeeding.** `basis` is emitted only on
  the abort branch, which was written up as an unfixable gap — a signal
  readable only on failure is not useless, it is a signal you cannot use to
  confirm success. State which of the two you need before calling a probe
  inadequate.
- Cost: none from the fix, which stays. ~2h20m of stale board while the real
  cause was diagnosed, and a 24h measurement plan that was measuring the wrong
  thing and had to be cancelled at T+4.71h.

### 2026-08-13 — Symptom relief resets the clock that would have proved the cause
- What was actually true: restarting refresh-worker drops `anon` 2603 -> 980MB
  and the board rebuilds — as it did at 14:56, 18:05, and 22:59. Three
  restarts, three recoveries, and each one destroyed the evidence window for
  the growth that caused it.
- The rule going forward: **before restarting to clear a symptom, capture the
  series that proves the cause** — here, `anon` over time, which is one log
  query. A restart is not neutral: it is the deletion of the measurement.
  Record the pre-restart numbers in the row, not just "restarted, recovered".
- And say so in the ledger explicitly, because **a recovered board reads as a
  fixed system.** If nobody writes "this was relief, expect recurrence in ~4-5
  hours on the measured trajectory", the next session sees a healthy board and
  a closed row.

### 2026-08-13 — Check whether the obvious fix was already tried, BEFORE building an instrument
- What we believed: refresh-worker's memory growth needed a flush, and the
  absence of `malloc_trim` in `run_refresh_worker.py` was the lead. A sampler
  was built and a lane opened on that basis.
- What was actually true: **both flushes already existed, ran in production,
  and had already been measured under `#285`.** `malloc_trim` returned
  1109.6MB across 24 calls in 46 minutes (`gc.collect()` returned −104.3MB —
  anon ROSE during collection); `configure_malloc_arenas(2)` is called at
  `run_refresh_worker.py:3156`, deliberately before threads spawn. The trim
  halved the ratchet and did not stop it, and by guard time returns 0.0–2.9MB.
  The conclusion — that the residual is live-or-fragmented, not
  free-but-unreturned — was already written in a code comment.
- The rule going forward: **before instrumenting a known-hard problem, read
  what the codebase already says about it.** The answer to "don't we need a
  flush" was 50 lines of measured prose in `memory_observability.py`. An hour
  of sampler-building preceded finding it.
- Two search errors made it worse, both of the same family: a case-SENSITIVE
  `grep malloc_trim` missed `MALLOC_TRIM_FAILED`, and a caller search used
  patterns (`arena_max`, `cap_arenas`) that could not match the real name
  `configure_malloc_arenas`. **When a search for a mechanism returns nothing,
  suspect the pattern before concluding the mechanism is absent** — especially
  when about to build something on that absence.
- Cost: an hour, and a lane opened on a lead that was already closed. The
  measurement still has value — the arena cap being live is exactly what makes
  the floor series discriminating — but that was luck, not design.

### 2026-08-13 — I RETRACTED POINT-SAMPLING, THEN BUILT A HEADLINE ON IT ANYWAY
- What we believed, and published to the ledger as measured fact: refresh-worker
  leaks ~300MB/hour of anonymous memory, derived from `anon` 1163 → 2603MB
  across 18:05–22:48Z.
- What was actually true: **those were two point samples**, and `anon` is now
  measured to swing **~1650 ↔ 3200MB within minutes** (floor 1652, p50 2518,
  max 3203.7 in a single 5-minute window). Two readings of a quantity with a
  1550MB oscillation cannot distinguish a ratchet from two phases of the same
  swing. The floor series — the honest one — reads 1670 / 1652 / 1763, roughly
  flat.
- **The sharp part: I had retracted this exact method three hours earlier, in
  this same lane.** The v2 sampler's `+2418 MB/hour` was thrown out precisely
  because point-sampling a spiky process measures phase, not trend. Then the
  headline finding — the one that closed `#417`'s row, opened a new lane, and
  justified an incident deploy — rested on two points taken the same way.
- The rule going forward: **when you retract a METHOD, re-audit every live
  conclusion that used it, not just the instrument that exposed it.** A
  retraction is not local to the tool that failed; it is a statement about a
  class of evidence. Grep your own ledger for numbers derived the same way
  before the retraction goes in.
- Corollary on prediction: the falsified prediction (re-freeze at 4-5h; actual
  34 minutes) is what forced the re-audit. **A written prediction is cheap and
  it is the only thing that reliably catches a wrong model** — the numbers
  themselves looked fine right up until the clock disagreed.
- What survives, and is worth keeping: `#417`'s guard fix is still verified and
  still correct. What it did NOT fix is that ONE READING of the right quantity
  is still not enough when that quantity swings 1550MB. That is the real defect
  and it was invisible until the leak framing collapsed.
- Cost: a ledger that stated a leak as measured fact for ~45 minutes, a lane
  opened on it, and an hour of allocator investigation aimed at a number that
  may not describe anything.

### 2026-08-13 — A habit that fails silently needs a tool, not more care
- What kept happening: publishing a commit means cherry-picking onto
  `origin/main` in a throwaway worktree (local `main` carries other sessions'
  commits, so `git push` is never scoped). Done by hand it failed **four times
  in one session**, identically:
  ```
  cd /tmp/wt && git cherry-pick $(git rev-parse HEAD)
  ```
  The substitution evaluates AFTER the `cd`, resolving the WORKTREE's head and
  cherry-picking a commit onto itself. **Git reports success, the payload is
  empty, and `git push` says "Everything up-to-date."**
- Why it survived four repetitions: every failure mode looks like the success
  mode. There is no error, no conflict, no non-zero exit — only a payload that
  is empty, and only if you happen to print it. It was caught each time by a
  manual `git diff --stat origin/main..HEAD`, i.e. by vigilance, which is
  exactly the thing that does not scale across a long session.
- The rule going forward: **when the same mistake recurs and its signature is
  indistinguishable from success, stop resolving to be careful and change the
  shape of the operation.** `scripts/push_via_worktree.py` resolves every SHA
  in the main repo BEFORE a worktree exists, and treats an empty payload as a
  hard error naming that exact cause. The class of bug is now unreachable
  rather than merely watched for.
- Generalises past git: a silent no-op is worse than a loud failure, and a
  procedure whose failure is silent should be encoded, not remembered. The
  same logic is why the deploy path became `scripts/render_deploy.py` the same
  evening.
- The script also refuses to auto-resolve a cherry-pick conflict, deliberately:
  a union-merge is how a NEWER upstream note gets silently reverted, which
  nearly happened tonight when origin held a corrected "obligation CLOSED"
  line and the local side still said "unpushed".

### 2026-08-14 — A TROUGH THAT CLEARS AN EARLIER PEAK IS A RATCHET. That is the test
- What we believed, three times in one evening, each time on the evidence
  available: (1) refresh-worker leaks ~300MB/hour [from two point samples];
  (2) no leak is established, it may be a 1550MB oscillation [after measuring
  the within-window spread]; (3) the leak is real at ~+1200MB/hour [after 45
  minutes of floor series].
- What was actually true: (3). But (2) was the correct call **on the evidence
  then available**, and (1) was not — it asserted a rate two points could not
  support.
- **The test that settles ratchet-vs-oscillation, and it is not a slope:**
  compare the LATEST TROUGH against an EARLIER PEAK. At 00:06 the floor was
  2588.9 against a 23:19 peak of 1877.9. A trough above an earlier peak cannot
  be produced by any oscillation, however wide — no averaging, no regression,
  no minimum sample count. A slope over a noisy series proves nothing and cost
  two retractions to learn.
- **Why the instrument seemed to change its mind: the SYSTEM changed, not the
  measurement.** Early windows spread 1650<->3200 (1550MB); late windows
  2589<->2651 (60MB). As memory filled there was less headroom to swing in, so
  the floor became legible. **An instrument that is inconclusive early can
  become decisive later without being fixed** — do not discard it, and do not
  read its early silence as a verdict.
- Corollary on predictions: predicted re-freeze at 4-5h; first aborts at 34
  min; sustained freeze at 1.13h. The 34-minute aborts looked like
  falsification and were a DIFFERENT mechanism — peaks crossing the threshold —
  while the real onset was the floor crossing it. **Two mechanisms, one log
  line.** Before calling a prediction falsified, check whether the observable
  has more than one cause.
- Cost: two retractions and ~90 minutes. Cheap for the outcome — the leak is
  now established with a test that will not need re-litigating.

### 2026-08-14 — I RE-READ THE DEPLOYED SHA BEFORE EVERY *READ* AND SKIPPED IT BEFORE A *WRITE*
- What we believed: deploying `d4bb29b5` to refresh-worker was a pure restart
  with no new code — verified, and true when checked.
- What was actually true: another session deployed **`111a5000` at 00:16:53Z,
  ninety seconds before I fired at 00:18:06Z.** By the time my deploy ran, that
  "restart only" target was a **rollback of 850 lines** of their NFL work
  (`live_game_state.py` +298, `preseason_cards.py` +147,
  `nfl_game_projections.py` +96, `game_chip_scoreboard.py` +13). Cancelled
  mid-build; `111a5000` stayed live and nothing was reverted.
- **The rule I broke is one I had been applying correctly all evening.**
  `state.md` says deployed SHAs "go stale in minutes, not days — re-read before
  use." I re-read before every *diagnostic* read and did not re-read in the
  seconds before a *write*. A stale SHA makes a read wrong; it makes a deploy
  destructive.
- The rule going forward: **re-read the live SHA inside the same step that
  deploys, and assert the target is a descendant of it.** "I checked a few
  minutes ago" is not a check on a repo with concurrent sessions. A deploy
  tool should refuse when `merge-base --is-ancestor <live> <target>` fails —
  that single assertion turns this class of accident into an error message.
- Second failure in the same episode: **the restart I wanted had already
  happened.** `111a5000` going live at 00:16:53 restarted the worker and reset
  `anon` to ~472MB. My deploy was redundant as well as harmful — checking the
  live SHA would have shown both.
- Caught only because I asked what `111a5000` was instead of assuming my own
  deploy was the newest thing on the service.

### 2026-08-13 — A "PURE READ" endpoint is a reader you will not find by grepping the attach

- What we believed: that deploying web alone would move every NFL game-state
  observable, because `attach_game_state` runs at serve time. Two call sites
  were enumerated to support it — `/api/board/book-grid`
  (`intelligence.py:2378`) and the cross-book route (`:2838`) — and both
  genuinely do call it on every request.
- What was actually true: `/api/board/layer1` is a THIRD reader and calls it
  **never**. Its own docstring says so in the first line — "A PURE READ of the
  precomputed grid" — and its game state is whatever
  `build_book_grid_artifact` stamped on **refresh-worker**
  (`book_grid_artifact.py:214`). The web deploy passed 3 of its 4 observables
  and could not have passed the fourth.
- Why the usual method missed it: grepping `_attach_book_grid_game_state`
  finds the callers, and a route that deliberately does NOT call it is
  invisible to that search. **The dangerous reader is the one defined by
  absence.** The same grep that proves "these three call it" says nothing
  about how many routes serve the same data without calling it.
- The rule going forward: **when a fix's observable is served by an endpoint,
  ask what BUILDS the payload that endpoint returns, not which functions
  mutate it.** For anything artifact-backed the answer is usually a different
  service, and "the code is deployed" then says nothing about the reading. Find
  the readers from the DATA (who writes this artifact, who reads it) rather
  than from the function name.
- Direct descendant of `presence is not reachability` (2026-08-13, same repo,
  same day, four-reader endpoint) — and it was made with that entry already
  in context. A rule that names a specific symbol does not generalise itself
  to the next symbol. What transferred was the *shape*; what did not was the
  discipline of enumerating readers before claiming blast radius.
- Cost: one web deploy that delivered 3 of 4 effects and a confident wrong
  statement in preflight answer 4. No production harm — the deploy was correct
  as far as it went, and the failure was caught by measuring rather than by
  assuming.

### 2026-08-13 — A CONSTANT that reproduces exactly is a data outage, not a weak model

- What we believed: the NFL board's identical projections on all 16 preseason
  games (`margin 0.96`, `total 44.38`, `home_win 0.5267`) were `#377`'s
  degenerate model — a model measured at ~zero skill finally collapsing.
- What was actually true: the model was fine. Production `rating_source` read
  `prior_season_fallback` on nearly every club and the CARDS surface served 16
  DISTINCT totals from a file of the same name. Two copies existed; the board's
  reader picked the one built where the play-by-play was missing.
- **The test that settled it in one command, and generalises.** Run the real
  generator with the suspected-missing input emptied, and see whether it
  reproduces the observed constant EXACTLY. It printed
  `0.960 / 44.380 / 0.5267` on all four weeks and on any matchup — to three
  decimals, the served values. A weak model produces *varying* numbers with no
  predictive power; a missing input produces *one* number. **Those are
  distinguishable, cheaply, before touching any modelling code.**
- The corroborating tell, worth naming because it is free: the four preseason
  weeks carry DIFFERENT shrinkage factors (0.92/0.80/0.55/0.92), yet every week
  served the same constant. Shrinking 0.0 by any factor is still 0.0 — so **a
  degenerate input silently makes a week-specific adjustment a no-op.** When a
  parameter that must change the output demonstrably does not, the input is
  zero, not the parameter wrong.
- The rule going forward: **before treating "every row is identical" as a
  modelling defect, reproduce the constant from an empty input.** If it matches
  exactly, the bug is upstream in data availability or file selection, and
  every hour spent in the model is wasted. `#377` sat OPEN and UNOWNED for days
  as a product decision about what a board may assert; it was a file-selection
  bug the whole time.
- Second-order: the two surfaces DISAGREED for days (board constant, cards
  per-game) and nothing compared them. A cheap cross-surface equality check on
  the same logical quantity would have found this immediately, and is now the
  closing evidence in `deploys.md` (6/6 agree).

### 2026-08-13 — A FIXTURE THAT OMITS A MARKER FILE TESTS A DIFFERENT DIRECTORY, AND SCORES IT AS A DEFECT

- What we believed: that an end-to-end harness had proven the new
  degenerate-writer guard did not work. It reported, in its own words,
  `exit_non_zero=FAIL  artifact_byte_identical=FAIL  names_the_cause=FAIL` --
  three independent-looking failures, which is exactly the shape that reads as
  conclusive.
- What was actually true: the fixture built a temp root with no play-by-play,
  but `default_nfl_source_root()` -> `_first_existing_root()` selects a
  candidate ONLY if it contains `upcoming_recs_*.csv`. The temp root had no
  such marker, so the resolver **skipped it and fell through to the real repo
  data dir**, which holds `pbp_2025.csv` with 32,937 plays. There was no outage
  to catch. The guard was correct and silent, and the harness scored correct
  silence as three failures.
- Why it survived a moment's thought: every FAIL was consistent with every
  other FAIL, because they were all downstream of the same wrong directory.
  Internal agreement across a harness's checks is worth nothing when the checks
  share an input -- the same mechanism as two instruments reading one clock.
- The rule going forward: **a fixture that selects a resource by CONVENTION
  must assert which resource it actually selected, before it is allowed to
  render a verdict.** Concretely: print the resolved root/path/connection and
  compare it to the intended one, and abort if they differ. v2 does exactly
  that (`if resolved -ne $root { ABORT: this fixture tests nothing }`) and the
  guard then passed all three checks plus a positive control.
- Sibling of `A path one toolchain resolves and another cannot makes a guard
  pass silently` (2026-08-13). That entry covers a path a tool CANNOT resolve;
  this covers one it resolves to something ELSE, which is worse -- there is no
  error anywhere, and the wrong answer is fully formed.
- Cost: ~10 minutes, and one moment of believing a just-written guard was
  broken. Nothing shipped on it.

### 2026-08-13 — CLOSING A TICKET IS A SCOPE DECISION, AND WHOLESALE CLOSURE SILENTLY RETIRES THE PART NOBODY WORKED

- What we believed: that `#377` ("PROJECTED is a CONSTANT") could be closed,
  because the constant was gone -- `projected` distinct 1 -> 6 on the same
  34-card board it was filed against.
- What was actually true: `#377` contained THREE claims, and only two were
  addressed.
  1. the constant -- fixed this session (`98950c6d`, `c7cff28c`);
  2. the product decision about what a skill-less model may assert -- already
     answered months-earlier by `7c854234`, and BOTH its offered options were
     taken (41 rows carry `projection_unavailable_reason`, 75 carry
     `model_skill`). Verified live rather than assumed;
  3. **`skill_note` is called in exactly one of seven projection builders** --
     never worked, never owned, and the ticket itself called this *"THE
     SYSTEMIC EXPOSURE… NOT THE MODEL"*.
  Stamping CLOSED would have retired (3) with no successor.
- The rule going forward: **before closing a ticket, enumerate its distinct
  claims and resolve each one separately. Any claim without evidence gets
  carved out into its own ticket, with a forward reference from the closure,
  BEFORE the parent is marked closed.** A ticket is not an atom; long entries
  in this repo routinely accrete a second and third finding under the original
  headline, and the accreted ones are the least likely to have an owner.
- Corollary, and the reason this is worth a rule rather than care: the part
  most likely to be orphaned is the part written LAST, which is usually the
  most general -- the specific bug gets fixed and the systemic observation it
  provoked dies with it. Here (3) was strictly better evidenced at closure than
  when filed: `#377` argued it from a model with no skill, while the actual
  2026-08-13 failure was a projection collapsing to one value across 16 games
  with nothing reporting it. Carved out as `#425`.
- Also recorded: `#377` DIAGNOSED ITSELF WRONG and that error was load-bearing.
  It concluded *"the constant is in the SOURCE… a model collapsed to the league
  average"*, which framed the whole thing as a product decision and is why it
  sat OPEN and UNOWNED for days. It was file selection. See the neighbouring
  entry on reproducing a constant from an empty input.

### 2026-08-14 — A PLATEAU IS A STRONGER SIGNAL THAN A PERCENTAGE
- What we believed, on one reading: the arena verdict said `fragmentation` at
  60.9% free-held, so allocator fragmentation was the live candidate for
  `#423`.
- What was actually true: across ten readings the arena held only **11-24%** of
  `anon`, and — the decisive part — **`system_current` PLATEAUED at ~393MB
  across three consecutive readings while `anon` kept climbing.** A bounded
  quantity cannot be the source of an unbounded one. Fragmentation is dead as
  an explanation, and the same fact explains why `malloc_trim` returned
  0.0-2.9MB at guard time: there was never much there to return.
- **The rule going forward: when attributing growth, look for what STOPS
  growing, not for what is large.** A percentage describes one instant and can
  be high for uninteresting reasons; a plateau against a rising total is a
  structural statement and needs no threshold to interpret. Same shape as the
  trough-vs-earlier-peak test recorded hours earlier — both replace "how big is
  it" with "what does it do over time", and both settled a question that a
  single number had left ambiguous twice.
- Corollary that cost real time: **a verdict computed over a subset must state
  its coverage.** `reads_as` printed `fragmentation` four times off 211-343MB
  of arena while `anon` sat at 1400-1900MB — true statements about 15-25% of
  the process, presented as statements about the process. The instrument built
  to resolve `#423` reproduced `#423`'s own failure mode on its first
  production line, and I shipped it. Any derived verdict now carries
  `arena_coverage_pct` and refuses below 50%.
- Cost: ~90 minutes chasing an allocator that was never growing, and one
  deploy to correct an instrument I had written the same evening.

### 2026-08-14 — I MEASURED A STAGE WITHOUT THE THING THAT DOMINATES IT, AND ALMOST SHIPPED THE FIX
- What we believed: `_OVERVIEW_MIN_SAFE_HEADROOM_BYTES = 3000MB` was a 23x
  over-reservation against a stage measured at 127MB, and the floor should come
  down. Written into `#387` as a measurement, with a recommended next action.
- What was actually true: the local run hydrated **4 of 8 sports**, and the four
  that returned zero games (mlb, nba, ncaab, nhl) include the one that IS the
  cost. The guard's own comment carries the production numbers: MLB alone takes
  the container 993.8MB -> 3922.6MB, **+2.9GB in 73 seconds**, and `anon` does
  not come back down. The comment even names the change I was about to make and
  rejects it: *"A 1000MB floor waves MLB through every time."*
- **The coverage caveat WAS in my write-up.** I recorded "4 of 8 hydrated,
  the others are unmeasured" as a footnote and then quoted 127MB as the stage
  cost in the headline, the commit subject, and the recommendation. **A caveat
  that does not change the headline is decoration.** If the unmeasured part can
  invalidate the conclusion, it belongs in the sentence that states it.
- The rule going forward: **before quoting a measurement, ask which input
  dominates and whether the run contained it.** A partial run does not produce a
  smaller version of the answer — it produces a different answer wearing the
  same units. Coverage is not a confidence interval on the number; it decides
  whether the number is about the thing at all.
- Corollary, and it cuts against a habit this session built: **"it came from a
  comment" is not evidence against a number.** Four comment-sourced figures were
  challenged tonight — 1,479MB stage, ~23min build, `#417`'s basis, and this
  floor. Three were stale or unsourced. This one was a real measurement with its
  inputs written down, and treating the pattern as a rule nearly took production
  down. Read the comment before overriding it.
- Cost: none in production — the change was not shipped. A ticket carried a
  recommendation that would have restored an OOM loop, for about an hour.
