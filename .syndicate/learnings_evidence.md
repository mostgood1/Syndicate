# Learnings — full evidence

Full bodies for entries compacted out of `learnings.md`, which is read at the
start of every session and has to stay inside the digest budget. The RULE for
each of these still lives in `learnings.md` under the same heading; this file
is the working behind it.

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

### 2026-08-14 — A guard's floor is a claim about ONE stage; refusing everything downstream of it is a separate bug

- What we believed: the Layer 2 board was stale because the intelligence
  engine had become slow, and because refresh-worker is leaking memory. Two
  sessions of work had gone into making the build cheaper (`#414`'s 21.5x
  quote-join index) and into naming the leak's allocation site (`#423`).
- What was actually true, measured over one 3h production window: **the builds
  that run are fine — 96.7% of them never start.** 146
  `MEMORY_GUARD_ABORT stage=pre_source_state_fingerprint` against 5 completed
  builds, and a 104.7-minute stretch with no shortlist rebuild at all. Making
  the build faster cannot move a number whose denominator is refusals.
- And the guard was refusing correctly. `_MIN_SAFE_MEMORY_HEADROOM_BYTES` is
  sized, in its own comment, for `build_intelligence_overview`'s ~1.9GB
  transient — a stage the Layer 2 shortlist does not run. The bug was never the
  floor's VALUE. It was that one floor gated a whole publication containing two
  stages whose costs differ by ~10x. Production proved the independence itself:
  3 of the 5 completed builds had `CANDIDATE_POOL_READY count=0` while
  `LAYER2_SHORTLIST` returned 256 rows from 13,665 opportunities on the same
  cycle.
- **The rule going forward: a memory floor is a claim about the cost of ONE
  stage. Before putting a guard in front of a span, enumerate what is inside
  the span and what each part costs. If the span contains work an order of
  magnitude cheaper than the floor, the guard is not protecting that work — it
  is deleting it.** The cheap work needs its own, measured floor, and the abort
  line needs to say WHICH floor fired or the two become indistinguishable in
  the logs.
- Second belief overturned in the same window: **the "leak" was not leaking.**
  Boot-segmented over 2.5h, `anon` went 2620.1 -> 2439.6MB — it oscillates
  ~1400-2800MB around a high plateau and did not ratchet. The 08-13 rate is a
  fact about 08-13. A plateau and a ratchet demand different fixes (find the
  retainer vs. find the allocator), and the ledger's own framing had carried
  the ratchet forward unchallenged into a new day.
- Method note that produced both: the first read of the same data said "the
  floor fell 1310MB in 3h, it is recovering." It was a deploy at 14:22:32Z
  restarting the worker. Boot-segmenting is already a rule here
  (`2026-08-10 — segment on process boundaries before any neighbour-based
  test`); it was nearly broken again because the discontinuity was somebody
  ELSE's deploy, which does not announce itself in your own session.
- Cost: none. Caught before anything was written down, and the sessions that
  optimised the build were not wasted — they are why the 5 builds that do run
  finish in 27s.

### 2026-08-14 — A CADENCE IS NOT AN OUTAGE, AND I ESCALATED ONE AS THE OTHER
- What I believed, and told the user in bold: MLB odds "have not been refetched
  since 8:09am CDT, now 2h10m and counting", framed as a capture stall worth
  chasing. I had two independent readings 78 minutes apart showing the freshest
  observation frozen at the *identical* instant, which felt decisive.
- What was actually true: `_PREGAME_SWEEP_INTERVAL_FALLBACK = 2 * 3600`. Daily
  sports drift-sample every 2h pregame by a decision dated 2026-07-27 in the
  constant's own comment. The gap measured **7,289s against an interval of
  7,200** — I had measured the constant and called it an outage.
- **The rule: before calling a gap a failure, look for the interval it equals.**
  Two identical readings prove a quantity is not advancing; they say nothing
  about whether it is *supposed* to be. "Frozen" and "sampled" are the same
  observation at any sampling rate below your polling rate — the discriminator
  is not another reading, it is the configured period. I took a third and
  fourth reading when I should have grepped for a constant.
- What did work, and is worth repeating: writing the competing explanation into
  the lane BEFORE testing. I recorded "is 2h just a long sample of the ordinary
  cadence" as a live alternative, so when `PREGAME_CADENCE_DETAIL` printed
  `interval_s=7200` the answer was already framed as a choice between two
  stated options rather than a surprise to be rationalised. The lane closed as
  an exoneration in one step.
- Corollary on null results, which I nearly got wrong in the same hour: zero
  `T_WINDOW_SWEEP_DUE` in my sample was CORRECT and carried no information —
  first pitch was 18:20Z and T-75 cannot arm before 17:05Z. I sampled
  13:00-15:30Z. **An absence measured outside the window where the thing can
  occur is not an absence.** Same shape as the entry on absence-in-a-window.
- Cost: ~20 minutes and one incorrect escalation to the user, corrected in the
  same session before anything was changed. Nothing was deployed on the wrong
  premise; the UI work it prompted stands on its own and is, if anything, more
  clearly justified — a 2h cadence is exactly the fact a board should state.

### 2026-08-14 — A CONSTANT THAT REPRODUCES EXACTLY FROM AN EMPTY INPUT IS A DATA OUTAGE, NOT A WEAK MODEL

- What we believed, twice, on two different sports: that an identical
  projection on every game meant a collapsed model. `#377` had sat OPEN and
  UNOWNED for days on that reading, framed as a product decision about what a
  skill-less model may assert. `#429` was filed with the same instinct.
- What was actually true both times: the model was fine and the INPUT was
  missing. NFL served `margin 0.96 / total 44.38 / home_win 0.5267` on 16
  games because `load_nfl_game_projections` deduped candidate files by NAME
  across source roots and opened a copy generated where the play-by-play was
  absent. MLB served `0.0` on 188 games because one composite stat was never
  passed to the accumulator its mean divides by.
- **The test that settles it in one command.** Run the real generator with the
  suspected-missing input emptied and see whether it reproduces the observed
  constant EXACTLY. NFL printed `0.960 / 44.380 / 0.5267` on all four weeks and
  any matchup — to three decimals, the served values. A weak model produces
  VARYING numbers with no predictive power; a missing input produces ONE
  number. Those are cheaply distinguishable BEFORE touching any modelling code.
- Corroborating tell, free wherever a parameter must change the output: NFL's
  four preseason weeks carry different shrinkage factors (0.92/0.80/0.55/0.92)
  and every week served the same constant. **Shrinking 0.0 by anything is still
  0.0** — when a parameter that must move the output demonstrably does not, the
  input is zero, not the parameter wrong.
- The rule going forward: **before treating "every row is identical" as a
  modelling defect, reproduce the constant from an empty input.** If it matches,
  the bug is upstream in data availability or file selection and every hour
  spent in the model is wasted.
- Second-order, and the cheaper detector: the two surfaces DISAGREED for days —
  the cards showed 16 distinct totals while the board showed one constant, from
  files of the same name — and nothing compared them. A cross-surface equality
  check on the same logical quantity finds this immediately and is now the
  closing evidence in `deploys.md` (6/6 agree).

### 2026-08-14 — A LANE LEFT OPEN AFTER ITS WORK SHIPS IS AN ACTIVE LOCK, NOT A STALE NOTE

- What we believed: that closing a lane is bookkeeping, safely deferred to
  `/checkpoint`. `projection-skill-declaration` shipped, deployed to both
  services and was verified on production hours before its header was updated.
- What was actually true: `lane-guard` returned **exit 2** for
  `projection_skill.py` and `board_enrichment.py` that entire time, locking two
  files against every other session on a shared tree, for work that was
  finished. Measured through the live hook, not inferred.
- The rule going forward: **close a lane when its measurement lands, not at
  checkpoint.** The ledger already treats an unmeasured deploy as an open
  obligation; an unclosed lane is worse, because it also blocks other people.
- Method note that nearly cost the verification: the first release check used
  `pipeline/intelligence_state.py` as its control, ASSUMING it was claimed. It
  returned 0 — making "released" and "the guard returns 0 for everything"
  indistinguishable. Re-run against files genuinely claimed by open lanes
  (`live_refresh_loop.py`, `memory_observability.py`, `layer1_board.html`) all
  returned 2. **A control you have not verified is claimed is not a control.**

### 2026-08-14 — `git add <paths>` SCOPES THE INDEX; ONLY A PATHSPEC ON `commit` SCOPES THE COMMIT

- What we believed: that staging explicitly by path was enough to keep a
  parallel session's work out of a commit. The repo's standing note says "never
  chain add and commit"; the add WAS correctly scoped.
- What was actually true: the index already held another session's staged
  files, and a bare `git commit` took all of them — 505 insertions, of which 65
  were mine. Their `deploys.md` row was a **PENDING preflight marked "HOLD on
  timing"**; pushing it would have published a deploy record for a deploy they
  had deliberately not made, under my commit message.
- How it was caught: reading the commit's own `--stat` afterwards, not by
  trusting that the `add` defined the commit. Recovered with
  `git reset --soft HEAD~1` (unpushed), then `git commit -F msg -- <paths>`,
  which leaves the other session's files staged exactly as they were.
- The rule going forward: **on a shared tree, always `git commit -- <paths>`.**
  Check `git diff --cached --name-only` BEFORE committing and the commit's
  `--stat` AFTER. And note the argument order: `-m`/`-F` must come BEFORE the
  `--`, or git reads the message as a pathspec.
- Where it is unavoidable — appending to a ledger file another session has
  staged — commit it DELIBERATELY and say so in the message, rather than
  letting it ride in silently. Done twice afterwards on `deploys.md` and
  `lanes.md`.

### 2026-08-14 — DECOMPOSE BIAS BEFORE PUBLISHING A SKILL VERDICT

- What we believed, and were one commit from writing into a constant: the MLB
  hitter-prop model has NO MEASURED SKILL. Over 2,487 player-games every single
  counting market lost to a constant baseline — `hits` MAE 0.7321 vs 0.6978,
  `tb` 1.3652 vs 1.3167, and so on for seven markets. That is exactly the
  reading `#367` published for NFL margins, and it would have gone into
  `MEASURED_SKILL` as "no skill".
- What was actually true: the model is **BIASED, NOT BLIND**. Every market also
  carried a positive correlation (0.13–0.16), and subtracting the mean error
  flipped **5 of 7** to beating the baseline. The ranking information is real;
  the LEVEL is wrong.
- **Why "no skill" would have been actively harmful, not merely incomplete:**
  the two conclusions have OPPOSITE remedies. "No skill" means suppress the
  projection (what NFL margins correctly do). "Biased" means CALIBRATE it —
  `#367`'s own totals fix, `calibrated_total`, is that remedy. Publishing the
  wrong one retires a model that needed a constant subtracted.
- The rule going forward: **before writing any skill verdict, subtract the mean
  error and re-score.** Report `mae_model`, `mae_constant_baseline` AND
  `mae_debiased` together. A model that beats the baseline only after
  de-biasing is a calibration ticket, not a dead model, and the three numbers
  side by side are what make that legible. MAE alone cannot separate them.
- Then decompose further, because the CAUSE changes the fix again. Normalising
  by opportunity (`pa_mean`) removed 55% of the count bias — real and NOT all
  of it, with +12.2% per-PA rate inflation left over. So "fix playing time" is
  the biggest single lever and is still insufficient on its own. **Report the
  PROPORTION explained, never a binary**: the first version of that check
  printed "one fix, not eight" on a threshold `rate < raw/2` that `12.2 vs
  13.5` passed by a hair — a verdict far stronger than its own data, and the
  same defect as a watcher label its exit condition does not entail.
- Cost: none. Caught because seven markets failing the same way in the same
  direction looked like one cause rather than seven faults, and that was worth
  one more test.

### 2026-08-14 — A GUARD MUST COUNT THE ROWS THE STATISTIC USES, NOT THE ROWS THE JOIN PRODUCED

- What we believed: the WNBA backtest was protected against publishing a number
  from a thin sample. It had an explicit `--min-games` gate, written from the
  ledger's own warnings about sample size, and the gate PASSED.
- What was actually true: it gated on games JOINED TO A FINAL — **361** — and
  then computed every statistic over whichever of those carried a projection —
  **9**. The guard was satisfied by a denominator forty times larger than the
  one the numbers rested on, and it printed `corr 0.5228` from nine games.
- The rule going forward: **a guard's denominator must be the denominator of
  the thing it is guarding.** If a statistic is computed over a subset, the gate
  counts the subset. Print BOTH — "361 joined, 9 with a projection" — because
  the gap between them is itself the finding: here it was the whole story
  (a column added 13 days earlier), not a footnote to a skill result.
- This is the ledger's "a pooled denominator can make a measurement unreadable"
  arriving in a new place: not a counter mixing populations, but a GUARD
  reading a different population from the statistic it protects. Same shape,
  and the script written to avoid it committed it.
- Generalises past backtests: any check of the form "enough data?" must name
  which data. `len(rows)` is almost never the right answer when the rows are
  heterogeneous.

### 2026-08-14 — THREE wrong root causes in one session, one shape: a single sample of a moving quantity

- What we believed, three times in ninety minutes, each stated to the user as a
  finding:
  1. **"MLB odds capture stopped"** — from zero `[odds_book_quotes]` lines on
     live-odds-worker. But `_append_mlb_book_quotes` returns early on
     `if not rows:` BEFORE the call that prints, and the odds refresh runs in
     detached subprocesses. **The instrument had never once been observed
     emitting non-zero**, so its zero carried no information.
  2. **"The 12MB publish ceiling blocks the transport"** — from 12 real
     `SWEEP_SKIPPED_DETAIL too_large=` lines against a 12,800,063-byte shard.
     But the ceiling is **sweep-only**; the direct path streams and never
     consults it, which `artifact_publisher.py:1007` states explicitly **twenty
     lines below the constant I quoted**. Web had the file, byte-identical.
     That same comment records THREE prior sessions misreading `{'too_large':N}`
     the same way. This was the fourth.
  3. **"Capture stopped at 15:10:44Z"** — from one read of the shard's tail.
     Ten minutes later the newest row was 16:20:38Z. Capture runs in ~2h bursts;
     the read landed in a gap.
- What was actually true: **nothing was broken.** MLB book-quote capture runs on
  a ~121.6-minute cadence because the pregame relaunch cooldown (1800s) is keyed
  by DATE ONLY — not by sport — and sports rotate across launches, so MLB rides
  every 2nd-4th one.
- **The single shape underneath all three: a quantity that MOVES, sampled ONCE,
  promoted to a conclusion.** Each sample was real. Each was reported honestly.
  Each was wrong about the system because one sample of a bursty, rotating, or
  conditionally-emitted quantity is a point, not a rate.
- **What finally worked, and it is the prescription: stop reading the
  instrument and read the STATE.** Streaming the whole artifact and extracting
  every distinct `captured_at` gave the complete cadence — 7 bursts, gaps
  515.7/121.6/121.6/122.5/121.6/69.9 — in one call, with no log-token guessing
  and no sampling. The logs are an emitter with unknown coverage; the artifact
  is the thing itself.
- The rule going forward: **before concluding from an absence or a single
  reading, ask "what is the period of this thing?" and take a span longer than
  it — or read the durable state instead of the event stream.** And when a
  finding rests on a constant, read the whole comment AND the call sites of the
  function that owns it before publishing; the disconfirming sentence was
  already written in the file all three times.
- Cost: three wrong statements to the user, all retracted the same session,
  nothing shipped on any of them. The retractions are in `state.md`. The real
  cause was found and the fix written the same session.

### 2026-08-14 — I CALLED A CORRELATION A PROOF, TWICE IN ONE SESSION
- What I believed: the soccer odds gap was step truncation. The evidence felt
  airtight — the pregame run is 50 steps grouped by kind, odds sit at #21-30
  behind ten sims, and the fresh/dark split matched the step order with **no
  exceptions**: `soccer_eredivisie_odds` #27 current, #28/#29/#30 all 3.6 days
  stale. I wrote "ROOT CAUSE PROVEN" into the lane, shipped a reorder, and told
  the user it was the fix.
- What was actually true: unknown, but **not that**. A single-league scoped run
  for `belgian_pro_league` captured nothing either — and that job is ~6 steps.
  **A 6-step job cannot die at step 27.** One four-minute test, available the
  whole time, would have killed the theory before it was deployed.
- **The rule: when a pattern implies a mechanism, test the mechanism directly
  before shipping against it.** The step-order story predicted "shrink the step
  list and it works". That prediction was cheap, decisive, and I ran it AFTER
  deploying instead of before. A correlation across ten leagues is still one
  observation of one run shape; it is not ten independent confirmations.
- Second instance the same session, same shape: a 2h odds gap measured twice at
  the identical instant read as an outage, and was `interval_s=7200` — I had
  measured a constant and called it a failure. Both times a clean pattern
  substituted for a test. Both times the test was minutes of work.
- **What I did right, and it limited the damage:** the reorder was pinned to a
  single file on the live commit rather than batched onto main's tip, so the
  wrong theory shipped ~80 lines of defensible reordering instead of 22 files
  of four lanes' unmeasured work. A wrong diagnosis with a small blast radius
  is recoverable; the same diagnosis with a batched deploy would not have been.
- Corollary I nearly missed: the odds CSVs contain today's fixtures with real
  prices, which LOOKS like proof the captures are fresh — but a CSV written
  four days ago would contain them too, because they were upcoming then. I
  caught that one before publishing it. Same class of error as the two above,
  and the only reason it did not become a third is that I asked what else could
  produce the observation.
- Cost: one unnecessary deploy, a wrong "PROVEN" in the ledger for ~90 minutes,
  and three fixtures that reached kickoff stale while I chased the wrong thing.

### 2026-08-14 — A HEALTHY-LOOKING SIBLING MASKED A PLATFORM-WIDE OUTAGE
- What we believed, for most of a session: three soccer leagues had a broken
  odds capture while eredivisie was fine. The contrast WAS the evidence — same
  script, same key, same region, one works — and it drove three successive
  hypotheses (season gate, step truncation, per-league fetch fault), two of
  which were shipped against.
- What was actually true: **soccer GAME odds were frozen for all ten leagues
  since 08-10.** Eredivisie carried 467 fresh `prop` rows from a DIFFERENT
  producer; its `game` rows stopped at 2026-08-10T20:54:06 exactly like the
  others. The "healthy" comparator was never healthy — it was masked.
- **The rule: when one member of a set looks healthy and the rest do not,
  disaggregate the healthy one before theorising about the sick ones.** A
  single `GROUP BY kind` on the artifact answered in one query what three
  hypotheses and two deploys could not. I had been comparing leagues, which is
  the axis the symptom presented; the discriminating axis was the PRODUCER
  inside each league.
- Corollary that generalises past this bug: **a comparator is a hypothesis.**
  "Eredivisie works" was load-bearing in every theory I built and was never
  itself tested. The cheapest possible check on any differential diagnosis is
  to verify the control is actually a control.
- Second-order: the same disaggregation retroactively explained two loose ends
  I had shelved — odds CSVs containing today's fixtures (written 08-10, when
  they were upcoming) and eredivisie's 99 board rows with 5 projections (mostly
  props). **Unexplained residue was pointing at the answer the whole time**;
  I had labelled both "odd, not blocking" and moved on.
- Cost: ~4 hours, two deploys against wrong causes, three fixtures to kickoff
  with 3.8-day-old odds. Blast radius stayed small only because every deploy
  was pinned to one file on its service's live commit.

### 2026-08-14 — A fallback CHAIN has a rung that fires; find it before costing the fix
- What we believed: the 2026-08-14 model audit's headline finding (2) — that
  `_fair_probability` "invents" a probability, that "a candidate with no model
  probability at all is treated as a coin flip", and that "against a plus-money
  side, a 0.5 default manufactures a large edge that then clears a threshold of
  0.0". The derived plan called this a longshot selector shipping to users
  daily and ranked it as the lane's urgent half.
- What was actually true: the `0.5` terminal is **unreachable in production**.
  The chain was `fair_probability -> model_probability -> confidence ->
  score/100 -> 0.5`, and every `filter_candidates` call site is fed
  `_score_candidates` output, whose `score_candidate` **always** assigns
  `score`. So `score/100` always fires first. Exercised on the real function: a
  typical score of 4.05 gives fair_prob 0.0405 and an edge of **-0.36**.
  Model-free candidates were not published as coin flips — they were silently
  REJECTED by a meaningless negative edge, under
  `reason: "edge_below_threshold"`, which claimed an edge had been measured
  when no model had ever run. **The sign was backwards and so was the outcome.**
- How we found out: read what writes each key in the chain, then ran the real
  function over one candidate per shape. Both steps are minutes.
- The rule going forward: **when a defect is described as "it falls back to
  X", the fix is worthless until you know which rung actually fires.** Removing
  the last rung of a chain whose third rung always fires is an inert fix that
  will be reported as shipped. Enumerate the chain, find who writes each key
  upstream, and exercise the function once per shape before estimating impact
  or urgency.
- Corollary, and the more dangerous half: **a wrong rung can invert the sign.**
  The audit predicted over-publication; the code produced silent exclusion.
  A fix costed against the wrong direction can make things worse.
- Second corollary: **a rejection reason that misreports its own cause is worse
  than no reason.** `edge_below_threshold` made the shortlist's own diagnostics
  argue the model had disagreed, on rows where no model existed. Reject by
  name.
- Cost: none — caught before any code shipped. The audit's *conclusion* (the
  chain is broken, exclude rather than invent) survived; only its mechanism,
  direction and severity were wrong.

### 2026-08-14 — A MANGLED SHELL ARGUMENT NEARLY BECAME "THE LEDGER LOST MY WORK"
- What I believed for about ninety seconds: the retraction and root cause I had
  just pushed were NOT on `origin/main`. Four greps, all returning 0, against
  files I had verified before pushing.
- What was actually true: MSYS path conversion rewrote
  `git show origin/main:.syndicate/lanes.md` into
  `origin\main;.syndicate\lanes.md`. Git never saw a revision. The content was
  on origin the whole time — `origin/main` IS the commit I pushed.
- Why it nearly stuck: the failure mode was *plausible*. This tree has
  concurrent sessions that overwrite shared ledger files, and "another session
  clobbered it" is a real thing that happens here. A believable story plus a
  zero result is enough to skip the check. The only reason I caught it is that
  one variant of the command surfaced the mangled path in its error text.
- **The rule: a zero result from a shell one-liner is a claim about the
  COMMAND before it is a claim about the world.** Re-run it a second way before
  believing it — here, `OM=$(git rev-parse origin/main)` then
  `git show "$OM:path"`, which cannot be mangled. Same discipline as validating
  the mtime probe against a control earlier the same session; the difference is
  that time I did it first and this time I nearly didn't.
- Standing note for this box: **`git show <ref>:<path>` is unsafe in bash here
  whenever `<ref>` contains a slash.** Resolve the ref to a SHA first.
- Cost: none. Caught before it was written to the ledger — which is the only
  reason it belongs here as a near-miss rather than as a retraction.

### 2026-08-14 — A watcher that compares TIMESTAMPS to identify a thing will misidentify it by microseconds

- What we believed: the 3h clean measurement window had been destroyed by
  another session's deploy. The watcher said so in plain language:
  `!! A DEPLOY INTERVENED -- the 3h clean window was reset.`
- What was actually true: **no deploy intervened.** The watcher was comparing
  the live deploy's `finishedAt` against the window-start constant:

      window start (my constant)   2026-08-14T16:16:56
      "intervening" deploy          2026-08-14T16:16:56.066938

  The same deploy. I had written the constant without fractional seconds, so
  `fin > DEPLOY` was true by **66 milliseconds**. The window was clean the whole
  time and the measurement simply never ran.
- Cost if accepted: the lane would have closed on a 103.9-min partial reading
  with its span shortfall unresolved, and the 3h criterion I had explicitly
  refused to retro-fit would have been quietly abandoned on a false alarm.
  Re-running it gave 37 refreshes / 187.3 min with a max gap of 11.8 min —
  a stronger result than the partial, on a span that finally exceeded the
  180-min baseline and so made the max-gap comparison sound.
- The rule going forward: **to answer "is this still the same thing", compare
  the IDENTITY, not a timestamp derived from it.** The fix was one line — check
  the deploy's commit SHA against the SHA the window opened on. A timestamp is a
  measurement of an event; the SHA IS the event. Identity comparisons do not
  have precision, and precision is where this class of bug lives.
- Sibling of `A FAILED READ RENDERS AS A RESULT` (2026-08-13), with the failure
  moved from a broken probe to a correct probe compared wrongly. Both produce a
  confident, well-formatted, wrong verdict — and this one produced it in the
  *pessimistic* direction, which is the one that gets believed because it sounds
  appropriately cautious.
- Also worth keeping: the watcher printed its reasoning (`live now: <sha>
  finished <ts>`) on the line above its verdict. That is the only reason the
  contradiction was visible at all. **A verdict line should always carry the
  values it was computed from.**

### 2026-08-14 — I PREDICTED FILE OWNERSHIP INSTEAD OF PROBING IT, TWICE
- What I believed, twice, and wrote into a checkpoint as a blocker: that
  `scripts/refresh_odds_sources.py` and then
  `scripts/run_live_odds_refresh_worker.py` were claimed by other OPEN lanes
  and would need a reassignment before I could touch them. The second one was
  handed to the next session as "needs a lane reassignment or their owner".
- What was actually true: **both returned exit 0 from `lane-guard.py`.** The
  other lanes mention those paths in PROSE — inside hypotheses and measurement
  notes — not in a `Files:` block, and the guard only parses the Files block. No
  reassignment was ever needed for either.
- Why I got it wrong: I grepped the ledger for the filename and treated any hit
  as a claim. That is not what the guard does, and the guard is the thing that
  actually blocks. **I was modelling the mechanism instead of running it**, on a
  mechanism that takes one stdin probe to run.
- **The rule: file ownership is answered by the GUARD, not by reading the
  ledger.** Pipe the path into `.claude/hooks/lane-guard.py` and read the exit
  code. A grep over `lanes.md` over-reports, because lane bodies legitimately
  discuss files they do not claim.
- Cost, and it is not zero even though nothing broke: one checkpoint handed the
  next session a false blocker on the single highest-value next action. Someone
  picking that up cold would have gone looking for a lane owner who did not
  need to exist.

### 2026-08-14 — PINNED DEPLOYS PUT CODE IN PRODUCTION THAT WAS NEVER ON MAIN
- What I believed at three consecutive checkpoints: everything I had shipped
  was on `origin/main`. I had verified the ledger content each time, and the
  reorder commit, and reported "all content is on origin".
- What was actually true: **two production changes on web — the ops league
  scoping and the `/api/ops/oddsapi/sports` route — existed ONLY on their
  deploy branches and on the running service.** `origin/main` had neither. The
  next web deploy from main would have silently removed both.
- How it happened, and it is structural rather than careless: to keep blast
  radius to one file I cherry-picked each change onto its SERVICE's live commit
  and pushed that to a `deploy/*` branch. That is the right call and I would
  make it again — but it creates **two** destinations, and only one of them is
  the one everyone else reads. One push to main was rejected non-fast-forward
  (origin had moved), I noted "I'll rebase and land it", and the thread was
  never picked up. A rejected push leaves no artifact; nothing reminds you.
- **The rule: a pinned deploy is TWO pushes, and the branch one is the one
  that lies to you.** The service is running, the feature works, every
  functional check passes — and main does not have it. Deploy-branch success
  actively masks main-branch absence.
- **The check that caught it, worth institutionalising: before archiving, diff
  each DEPLOYED file against `origin/main` by content, per service.** Not
  ancestry — the deploy SHAs are never ancestors of main by construction here,
  so `merge-base --is-ancestor` says "NOT_on_main" for both the real gap and
  the harmless case, and is useless as a discriminator. Content diff separates
  them in one line.
- Cost: none, caught at the archive check. Had it not been, the loss would have
  been invisible until someone deployed web from main and wondered where the
  ops routes went — with the deploy branches still green and a ledger that
  said "landed".

### 2026-08-14 — Separating `add` from `commit` is not enough if you chain them with `&&`

- What we believed: the standing rule "never chain add and commit" was being
  followed. The command was `git add <my two files> && git diff --cached --stat
  && git commit ...` — three separate commands, with an inspection step in the
  middle.
- What was actually true: **~32 files from other sessions were ALREADY in the
  index** before `git add` ran. The `git diff --cached --stat` printed all of
  them, exactly as designed — and then `git commit` ran anyway, in the same
  chain, before a human or the model could read the output. The commit swept in
  another session's entire audit output, screenshots, a new blueprint and a new
  script.
- The rule's INTENT is an inspection gate. `&&` removes the gate while leaving
  the appearance of one: the diagnostic is emitted and immediately obsoleted by
  the next command in the chain. A printed check nobody can act on before the
  action fires is decoration.
- The rule going forward: **the inspection must be its own tool call, with the
  commit in a LATER call.** And prefer the pathspec form, which makes the index
  state irrelevant:

      git commit -F - -- path/one.py path/two.py

  That commits only those paths and leaves everything else staged, so a shared
  index cannot leak into your commit no matter what another session has queued.
- Recovery, for the next person who does this: `git reset --soft HEAD~1`
  restores the index exactly as it was (all 32 still staged), then re-commit
  with the pathspec form. Nothing was lost and nothing was pushed.
- Why this is worth an entry when a memory already said "never chain add and
  commit": the memory names the two commands. The failure was in the THIRD
  command that was supposed to be the safeguard. A rule stated as "do not chain
  A and B" does not cover "chain A, a check, and B".

### 2026-08-14 — A saturated log window proves nothing, and the untouched sibling is the control
- What we believed: worker→web file publishing was broken by a wrong internal
  hostname (`SYNDICATE_WEB_PUBLISH_URL = http://syndicate-an21:10000` while
  `render.yaml` names the web service `syndicate`), that it was NOT caused by
  the A3 deploy, and that it was plausibly the missing cause under the OPEN
  soccer lanes ("odds frozen platform-wide"). Written into `state.md` AND as a
  lead on another lane.
- What was actually true: **`syndicate-an21` resolves fine.** refresh-worker
  logged `PUBLISH_OK` to that exact URL at 19:54:40Z and 20:03:16Z, and
  live-odds-worker logged 14/18/13 `PUBLISH_OK` across three windows. The
  failures were a **transient burst** — OK → 11 FAILED at 19:59:36 → OK — not a
  standing outage, and no explanation for a days-long soccer freeze.
- How the error was made: I read "0 FAILED before / 11 after" off windows that
  each returned exactly **100 lines, the API cap**. This logs API returns the
  **TAIL** of a window regardless of `startTime`, so a saturated window is
  silent about anything earlier in it. I already knew this — it is written in
  this session's own log — and used it as evidence anyway.
- How we found out: the user asked "are you sure this isn't due to a deploy?"
  The right control took ONE query: **live-odds-worker has the same env var and
  I never deployed it.** It was publishing successfully the whole time.
- The rule going forward: **when you suspect a change caused a symptom, find the
  sibling that did NOT get the change and look there first.** A same-config,
  same-moment, untouched service settles causation in one query, while
  before/after windows on the affected service can be silently truncated.
  Corollary: **a log window that returns exactly `limit` rows is evidence of
  nothing absent** — re-query narrower until it comes back under the cap, or
  count POSITIVE markers (`PUBLISH_OK`) instead, which a tail cannot hide.
- Second rule: **do not write a lead into another lane's ledger at higher
  confidence than the weakest link in it.** I labelled the hostname half
  "inferred, not tested" and still wrote the conclusion as a probable cause of
  their open bug. Retracted in place before anyone acted on it, but the next one
  may not be caught in time.
- Cost: none externally — nothing was changed on the strength of it, and both
  writes were retracted within ~15 minutes. The A3 deploy measurement is
  unaffected; it was verified by prediction plus an unchanged control.

### 2026-08-14 — A regex over a hand-written ledger inverts "NOT claimed" into "claimed"

- What we believed: `recommendation-lane-correctness` had grown from 4 claimed
  files to 13 and was squatting on four other lanes' files, including
  `pipeline/intelligence_state.py` and `layer1_board.py`. It was one sentence
  from being reported to the user as cross-lane sprawl.
- What was actually true: that lane claims SIX things and documents a collision
  check for every expansion. The extra paths came from two lines the extractor
  could not distinguish from claims:
  - `- NOT claimed, deliberately: <path> is held by <other lane>`
  - `- Collision check: ... Claimed elsewhere are <paths> (<lanes>)`
  **Both lines exist precisely to record that those files are SOMEBODY ELSE'S.**
  A pattern match for backticked `.py` paths inside the Files block read them
  with the opposite meaning.
- The rule going forward: **`lanes.md` is prose written for humans, and the
  negations are load-bearing. Do not derive a claim set from a regex over it.**
  If a lane's claims matter — for a collision check, a census, or an
  accusation — read the block. The cheap guard: any extracted claim list should
  be re-checked against the lines containing `NOT claimed`, `Collision`,
  `elsewhere`, or `held by` before it is used.
- Direct sibling of `2026-08-13 — A grep excerpt is not the file` and of the
  stale-`LANE_RE` incident: the third time in this ledger that reimplementing a
  parse over ledger text produced a confident wrong statement about another
  lane's work. The pattern is not "grep is unreliable" — it is **deriving a
  claim about someone else's work from a machine read of their prose.**
- Cost: none. Caught by reading the block before reporting. The direction of the
  error is what makes it worth recording — it manufactured an accusation
  against a lane that had done the collision checks correctly.

### 2026-08-14 — An audit's CAUSAL claim is a hypothesis; its MEASUREMENT is evidence
- What we believed: `plan_2026-08-14_ui.md` E3 and the audit behind it both
  said NFL/NCAAF cards break team names mid-word at 390px because "the mobile
  card grid does not stack — cards stay in a ~250px scrolling row".
- What was actually true: `.cards-grid` is `grid-template-columns: 1fr` and
  always has been. The scrolling row is `.cards-scoreboard`, the summary
  STRIP, which kept `grid-auto-flow: column` at every width. And it was only
  half the defect: `.cards-strip-head` also kept the matchup and the
  kickoff cluster side by side, splitting a 328px head 189/129 so each team
  block got 68px and the name inside it **30px**. No wrapping rule renders
  "North Carolina" in 30px.
- How we found out: measured the boxes before editing anything —
  `getBoundingClientRect()` on the element that was actually narrow, rather
  than on the element the plan named.
- The rule going forward: **an audit's measurements and its explanations have
  different evidentiary status.** "28px of overflow at 1440" is a reading and
  survives being handed on; "because the grid does not stack" is the auditor's
  inference and must be re-derived by whoever acts on it. Before editing the
  rule an audit names, confirm that rule currently produces the symptom — the
  cheap version is one `getComputedStyle`/`getBoundingClientRect` on the
  element, which takes a minute and would have caught this.
- Cost: none — caught before editing. Recorded because following it would
  have "fixed" a rule that was already correct, measured no change, and left
  a real defect standing with a lane closed on top of it.
- Corollary observed the same hour: the same audit's E2 diagnosis (a missing
  `box-sizing` reset) was CORRECT but INCOMPLETE — it took 28px to 2px, and
  the residual was `100vw` counting the scrollbar gutter. A correct cause is
  not necessarily the whole cause. Re-measure after the fix, not just before.

## 2026-08-14 — OVERTURNED: a stale snapshot is not a dead loop

**Believed:** the intelligence-state background loop had stopped, because
`/api/intelligence/status` reported `snapshot_generated_at` 34–53 minutes old
against a configured 60-second interval, while refresh-worker was visibly
crashing in `generate_smartsim2_nfl_projections.py`. The hypothesis was that
the crashing NFL job was starving the loop.

**Measured:** FALSE, on both halves.
- The season projection launches via `subprocess.Popen` — **non-blocking** —
  and `start_intelligence_state_background_loop()` runs on its own thread.
- The loop was running the whole time:
  `21:22:58 [intelligence_state] LAYER2_SHORTLIST rows=150 considered=14062
  sports=['mlb','nfl','wnba']`, 140 `PUBLISH_OK`, **0 publish failures**.

**Why it matters:** `/api/intelligence/status`'s snapshot and the layer2
shortlist are DIFFERENT ARTIFACTS on different cadences. Reading one and
concluding about the other produced a confident, wrong diagnosis that pointed
at another session's lane. **Name the artifact before naming the failure.**

**How to apply:** before declaring a loop dead, find a line the loop itself
emits. A consumer-side staleness reading tells you a consumer is stale; it does
not tell you the producer stopped.

## 2026-08-14 — a control is only as good as the premise under it

**Believed:** the A3 uninformative-EV rule could not touch MLB, "because every
MLB row is `consensus`". That premise was read off the SERVED rows — the
survivors — and generalised to the pool.

**Measured:** MLB carries **357 one-sided rows with a modelled fair** (wnba 42,
nfl 0). The rule CAN reach MLB. It doesn't, for a different and better reason:
mlb has `rows_with_model_edge = 2256`, and the rule keeps any row with a model
view. The control held **on the narrowness clause**, not on MLB's pricing.

**Why it matters:** the control passed, so nothing broke — but it passed for a
reason I could not have defended if asked. A control that holds by luck is
indistinguishable from one that holds by mechanism until someone checks, and
the check is what makes it evidence.

**How to apply:** when writing a control, state the MECHANISM that makes it
immune, then verify that mechanism against the pool the rule actually filters —
never against the rows that survived it. Related: [[feedback_a_rate_not_count]],
[[feedback_read_the_field_you_already_have]].

## 2026-08-14 — re-read the post-deploy measurement before blaming the deploy

Observed mlb `selected` at 84 → 78 and concluded a pre-registered control had
failed. It had not: the earlier entry in `deploys.md` recorded 84/60/12
UNCHANGED at 19:58Z, immediately post-deploy. The 78 was read at 21:22Z — 1.4
hours and two unrelated deploys later. `total_rows` (156→150) and
`rows_uninformative_ev` (4003→3842) drifted identically, which is the signature
of slate movement, not of a rule.

**How to apply:** a delta is only attributable to a change if it is measured
against the reading taken closest to that change. The ledger already held the
right number; I compared against memory instead of against the ledger.

### 2026-08-14 — A COUNT can rise because the population grew, not because the property got worse
- What we believed, for about a minute while reading the post-deploy numbers:
  the mobile touch-target fix had regressed something on desktop. NCAAF's
  count of sub-44px tabs went **48 -> 64** across the deploy.
- What was actually true: the fix applied a 44px floor at `<=767px` only, and
  desktop tabs are unchanged at 28px — they were never counted as passing. The
  count rose because the same fix made a previously UNREACHABLE panel
  reachable, so every card now renders four tabs where it rendered three.
  16 cards x 4 = 64. The property did not move; the population did.
- The rule going forward: **when a count changes across a fix, check whether
  the fix changed what is being counted.** A raw count carries an implicit
  denominator — here "tabs that exist" — and a change that adds members makes
  the count move on its own. Report it as a rate, or report the denominator
  beside it, or the next reader files a regression that does not exist.
- Sibling of the rate-not-count and pooled-denominator entries above, arrived
  at from a third direction: those were about a number that stayed still while
  the system moved. This is a number that moved while the property stood still.
- Cost: none — caught in the same reading, and written into `deploys.md` next
  to the number so it cannot be re-derived as a defect later.

### 2026-08-14 — An audit brief's "known already" inputs are claims, not axioms

- What we believed: the board-engine brief supplies prior findings as inputs
  "not to be re-derived", so they could be built on directly.
- What was actually true: **three of them did not survive first contact.**
  `static/mlb/board.js` — cited twice, as a byte-identical duplicate AND as
  confirmed dead code — **does not exist**. The devig count of 5 is not
  reproducible: a name-shaped pattern finds 4, and a widened grep finds
  per-sport `market_anchoring.py` the narrow one misses entirely. And the brief's
  own environment is a hazard: `.claude/worktrees/` holds full repo copies, so
  any unscoped census triple-counts and manufactures duplication findings.
- The rule going forward: **spend the first ten minutes of any audit
  re-verifying the inputs it tells you not to re-derive.** An input marked
  "known" is the one nobody will check, which is exactly why a stale one
  propagates. Cheap to test, and a single dead citation invalidates every
  downstream count that assumed it.
- Sharper: the brief was internally consistent — it cited `board.js` in two
  different sections, which READS as corroboration and is actually one stale
  fact counted twice. Two citations of the same source are not two sources.
- Cost: none. Caught in Pass 1 because the census returned 1 byte-identical
  group where the brief implied 2, and the discrepancy was chased rather than
  explained away.

### 2026-08-14 — the Render logs API returns the NEWEST N in a window; paging forward silently reports a peak over a sliver

I wrote a pager that walked a time window by advancing `startTime` past the last
line of each page. The API does not work that way: it returns the newest `limit`
lines inside `[startTime, endTime]`, presented oldest-first (`deploy_preflight.
newest_log`'s own docstring says so and I did not read it). Advancing startTime
re-reads the same tail and terminates.

Result: it printed `PEAK 606.2 MB ... samples 99` for a 51-second pass while
having covered **1.2 seconds** of it. The number was plausible, labelled with a
sample count, and wrong. Re-run paging BACKWARD (lower `endTime` to the oldest
line seen) over the same window: 267 samples, peak 613.1MB — and for the other
pass 198 samples and 804.2MB, not the 792.8MB the truncated read gave.

**How to apply:** page backward, and make the tool print the window it ACTUALLY
covered next to the window it was asked for. A peak over an unstated span is not
a measurement. The sample count did not reveal the truncation — 99 samples looks
like coverage; 99 samples inside 1.2s of a 51s window is the tell, and only
printing both makes it visible.

### 2026-08-14 — a before/after is void if the change moved work INSIDE the measured span

The `#387` streaming cutover was measured as "peak anon during
`OVERVIEW_SPORT_BEGIN mlb` -> pass end". The change also moves per-sport
candidate collection INTO that pass. So the after-span contains work the
before-span did not, and "peak went UP" is partly definitional, not behavioural.

Worse, a memory GUARD samples inside that same span (`_overview_headroom_
exhausted`, 3000MB, sized 2026-08-07). Moving work inside the span changed what
the guard sees without anyone editing the guard: it now trips after sport 1 of 8
(`BOARD_OVERVIEW_READY sports=1`, where every build in the preceding 3h read
`sports=8`).

**How to apply:** before deploying, ask what else reads the window you are
changing the contents of. A threshold calibrated against a span is invalidated by
a change to that span's definition, and nothing in the diff mentions the
threshold. State the before/after spans explicitly and confirm they contain the
same work; if they cannot, say the comparison is void rather than reporting a
delta.

### 2026-08-14 — "it cannot fit" from one sample, when the same shape runs fine twice

A handoff carried, as its single next action, a fix whose justification was one
OOM: eight sports hydrated at once, "peak = SUM is sufficient on its own to
cross 4GiB", "the floor plays no part". I deployed it, then measured two
pre-deploy passes of the IDENTICAL shape from the same evening: 8 sports
hydrated, peaks 804MB and 613MB, 15-20% of the ceiling, no death.

The 25-second kill was real; "the pass alone crosses 4GiB" was an inference from
it that the surrounding data contradicts. The floor was excluded by an argument
about elapsed time (13 minutes uptime), not by measuring it.

**How to apply:** the cheapest possible check on an incident diagnosis is to find
the same event shape that did NOT fail and compare. It costs one log query. Do it
BEFORE the deploy, not after — I had the whole evening's logs available and
queried them only when the post-deploy number looked wrong.

### 2026-08-15 — a threshold is calibrated against a SPAN; changing what the span contains invalidates it without touching the constant

- **What we believed:** `#387`'s streaming cutover was a self-contained memory
  change. Its diff touches `pipeline/intelligence_state.py` and
  `syndicate/features/intelligence.py`; its risk, per its own commit message,
  was an EMPTY board via `OVERVIEW_STREAM_FELL_BACK_TO_LIST`. That marker read 0
  in production, so the change looked clean.
- **What was actually true:** the cutover moved per-sport candidate collection
  INSIDE the window `_overview_headroom_exhausted` samples. That guard's 3000MB
  floor was sized 2026-08-07 against a different question ("does the NEXT sport
  fit ON TOP of every sport already held"). Same constant, same code, new
  meaning — and it began refusing the seven cheap sports on a number sized for
  MLB, AFTER MLB had already been paid for. Five consecutive builds returned
  `BOARD_OVERVIEW_READY sports=1` where the preceding three hours read
  `sports=8`. A coverage outage presenting as a successful memory fix.
- **How we found out:** by reading `BOARD_OVERVIEW_READY` before AND after,
  rather than only checking the failure mode the commit message named. The
  deploy's own success criteria (no OOM, marker 0, worker healthy) were ALL MET
  while the board was serving one sport of eight.
- **The rule going forward:** before deploying, ask what else READS the window
  whose contents you are changing — thresholds, guards, timeouts, caches sized
  against "a pass". Grep the span's own markers for constants that mention it. A
  threshold invalidated this way appears in NO diff, so review cannot catch it;
  only asking the question can.
- **Cost:** ~80 minutes of a one-sport board (22:57Z-00:15Z), a second
  deploy+measurement cycle, and it came within one ledger entry of being
  recorded as a clean fix. Both halves are now shipped and verified
  (`deploys.md` 00:36Z: `sports=8`, peak 1404.5MB = 34.3% of ceiling).

### 2026-08-15 — FORBIDDEN: never conclude "no OOM" from a LOG search. Kills are EVENTS, and I had this rule already

- **What we believed:** I reported "`oomKilled` 0 since 22:55Z" three times, and
  put it in `deploys.md`, `state.md` and a lane closure as verification that the
  `#387` work was holding.
- **What was actually true:** refresh-worker was OOM-killed **16 times on
  2026-08-14**, including FIVE times inside the window I called clean —
  23:11:56, 23:34:15, 23:51:04, 00:04:47 and **00:41:16, twenty-six minutes
  after my own fix went live.**
- **How we found out:** `/v1/services/<id>/events` returns
  `server_failed {'reason': {'oomKilled': {'memoryLimit': '4Gi'}}}`. Grepping
  the LOGS for the string "oomKilled" returns 0 matches because the container
  runtime records the kill, not the process — the process is dead and cannot log
  its own death. **`learnings.md` already carried this exact rule** ("OOM kills
  live in the Render events API, not logs"). I had it, quoted the adjacent rule
  about env changes earlier in the same session, and still ran the log grep.
- **The rule going forward:** a negative result about process death MUST come
  from the events API. `scripts/render_logs.py` cannot answer this question and
  a 0-match result from it is not evidence. Absence of a log line is evidence
  about the EMITTER, and a killed process emits nothing.
- **Cost:** a false all-clear on the headline claim of the session. The coverage
  result (`sports=8`) was real and independently sourced; the memory result was
  not, and I would have handed over "the OOM is fixed" if the checkpoint had not
  re-read production.

### 2026-08-15 — Pinned deploys do not merge; they REPLACE, so they have to be stacked
- What we believed: pinning a deploy branch to the service's own live commit
  is the safe pattern, full stop. It is what this repo does to avoid shipping
  four other lanes' code, and it works — as long as only one lane deploys.
- What was actually true: two lanes deploying the same service within minutes
  is enough to break it. My branch was pinned to `932a1f71`; another session
  was mid-deploy with `d9a39ce8`, its own commit stacked on that same base.
  Firing mine after theirs would have served a tree that never contained
  their route — a silent revert with a green deploy, no conflict, no warning.
- How we found out: a pre-flight check that listed in-flight deploys before
  POSTing and refused when one was running. It cost one API call.
- The rule going forward: **before firing a pinned deploy, re-read the
  service's live commit AND check for an in-flight deploy; then pin onto
  whatever is live at that moment, not onto what was live when the branch was
  built.** A pinned branch is a snapshot with an expiry date, and the expiry
  is the next deploy by anyone. Where two lanes are shipping the same service,
  stack — cherry-pick onto their commit — rather than racing from a shared
  base.
- Cost: none, caught pre-flight. Recorded because the failure is invisible
  after the fact: the deploy succeeds, the service is healthy, and the only
  symptom is a feature quietly missing.

### 2026-08-15 — The lane marker is repo-global, so only one session can hold it
- What we believed: `.syndicate/.current-lane` identifies "the lane I am
  working". The `/lane open` flow writes it and the guard reads it.
- What was actually true: it is ONE file in a tree shared by many sessions.
  Another session overwrote it with `memory-watchdog-435` while my lane was
  open, and the guard then blocked me from a file **my own OPEN lane
  claims** — reporting it as a cross-lane violation, which is exactly
  backwards. Whoever wrote the marker last can work; everyone else is
  blocked out of their own files.
- How we found out: a PreToolUse BLOCK on `game_board_contract.py` naming my
  own lane as the claimant and `memory-watchdog-435` as "current".
- The rule going forward, until the marker is per-session: **if the guard
  blocks a file your own lane claims, read `.current-lane` before assuming a
  real collision.** Take the marker, make the edit, and put back the value
  you found — and tell the session whose slug it was, because their next edit
  will be blocked by yours. Do not "fix" it by closing their lane.
- Cost: one blocked edit, plus the risk of a session concluding it had a lane
  conflict it did not have and working around a file it legitimately owns.

## 2026-08-14 — a "targeted regression" that omits the changed function's own test file is not a regression run

Changed `compute_team_ratings` (required `as_of`). Ran what I called a targeted
regression — `test_build_soccer_artifacts`, `test_soccer_adapter`,
`test_soccer_projections`, plus my new file — got **19 green**, reported "no
regressions", and committed and pushed.

**`tests/test_soccer_feature_loaders.py` was not in that list. It is the file
that directly tests `compute_team_ratings`.** A full `-k soccer` run, which I
had started earlier and let go to background, came back **4 failed, 519
passed** — all four in that file, all `TypeError: missing keyword-only argument
'as_of'`.

I picked the targeted set by *topic* ("soccer artifacts", "adapter") instead of
by *blast radius* (who calls the symbol I changed). `grep -rn compute_team_ratings`
would have named the file in one command, and I had already run that grep
earlier in the same task to find the CALL SITES — I just never turned it on the
tests.

**How to apply:** before running a subset, enumerate callers of every symbol
whose signature changed and make sure a test file for each is in the subset.
When a signature becomes stricter (a new required argument), the failure mode is
a hard `TypeError` at import/call time, so it is cheap to find and inexcusable
to miss. If a full suite is too slow to run before committing, say the run was
partial rather than saying "no regressions".

**The second-order cost is what makes this worth writing down.** The 4 failures
were not just stale tests. Chasing them exposed that
`fetch_asa_mls_team_history` returns **undated season aggregates**, so the
change silently emptied MLS ratings in PRODUCTION — and, worse, that MLS cannot
be backtested from that source at all, because a season average is contaminated
by construction and no as-of date can repair it. **A test I dismissed as
"fixture predates the parameter" was reporting a real production regression and
a real modelling limit.** Related: [[feedback_confirm_the_code_ran]],
[[feedback_gate_on_the_output_not_the_input]].

## 2026-08-15 — RULE: a session census MUST pass `include_archived: true`

**What went wrong.** `state.md`'s 20:4xZ census concluded "only
`recommendation-lane-correctness` has a live session". It was wrong about
`memory-cutover-ship`, which was live and shipping the whole time. The census was
built from a default `list_sessions` call, which **silently omits archived
sessions**. A session that ENDED and a session that NEVER EXISTED both read as
"absent", and the census could not tell them apart — so it under-counted the live
owners and over-counted the orphans in the same pass.

**The sharper half.** Liveness is not a property you can read once. During the
2026-08-15 02:0x cleanup, `board-ui-defects` was present and running at 02:07Z and
archived by 02:10Z — it archived *between two calls in the same census*, four
minutes after being asked to confirm its holdings, without answering. A census
taken at 02:07 and acted on at 02:15 would have been wrong in the other direction.

**How to apply.**
- Never take a session roster without `include_archived: true`, and read
  `isRunning` and `isArchived` as two separate facts. Absent-from-default is
  three states collapsed into one.
- Re-read the roster IMMEDIATELY before you act on it, not once at the start.
- Do not infer lane ownership from session TITLES. `board-ui` and
  `board-ui-defects` are different sessions with near-identical titles and
  disjoint lanes; the only reliable link found was the literal
  `/lane open <slug>` request in the owning session's transcript.
- Asking the owner is not a substitute for measuring: two of three sessions
  messaged during this cleanup never replied, and one of those had archived.

**Related:** this is the session-roster instance of the standing rule that a null
result must carry its window. "Not in the list" is a statement about the LIST.

## 2026-08-15 — RULE: `git status` is not `git diff --cached`

A staged revert is invisible in the working tree. Found 2026-08-15 02:0xZ: the
shared index held **6 files / 4993 deletions** undoing `b16eb1f7`, while every
one of those files was present on disk and byte-identical to `HEAD`. Nothing in
the tree, nothing in a file read, and nothing in a test run would show it — only
`git diff --cached`. Any session running a bare `git commit` would have shipped
the revert while believing it was committing its own work.

**How to apply.** Before ANY commit in this repo, run `git diff --cached --stat`
and confirm every path listed is yours. This is the same failure family as
"never chain `git add` and `git commit`" — with N sessions the index is shared
mutable state, and it can hold a change nobody in the room authored.

### 2026-08-15 — FORBIDDEN: never run a heavyweight census ON the thread that is doing the measuring

- **What we believed:** wiring the existing `allocation_snapshot()` to fire from
  the memory watchdog would name the allocator at the next excursion. The dump
  already existed; only the trigger was new.
- **What was actually true:** `tracemalloc.take_snapshot()` walks every live
  traced allocation in C **holding the GIL**. On this heap that is millions of
  objects, so the single call the trigger makes blocked the sampler thread
  outright. Measured:

      01:18-01:38  tracing OFF   567 MEMORY_WATCHDOG samples
      02:11-02:16  tracing ON    ZERO samples after the START line, then dead
      kill cadence ~16-22 min -> 02:03:48, 02:06:54, 02:16:41

- **How we found out:** the absence of samples, not the presence of an error.
  The dump prints AFTER the snapshot returns, so a dump still running looks
  EXACTLY like a trigger that never fired. I read it as "the trigger missed" and
  went looking for a threshold bug.
- **The rule going forward:** a diagnostic that can block must run off the
  thread that observes, as a daemon, so that never finishing is survivable. And
  when an instrument goes quiet, the first hypothesis is that the instrument is
  stuck -- not that there was nothing to report. Silence is a state of the
  EMITTER.
- **Cost:** ~25 minutes of production made materially worse (kill cadence 3-10
  min against 16-22), one wasted diagnostic window, and a false read of my own
  trigger logic. Reverted by env + a deploy; `548ded38` moves the dump
  off-thread with a test that fails if it is ever moved back.

### 2026-08-15 — A COUNT OF DEFINITIONS IS NOT A COUNT OF PRODUCERS, and the one it missed was the live bug

- **What we believed.** The board-engine audit's "**42 sites define or convert a
  probability** — 18 prob↔odds, 9 `implied_probability`, 11 `confidence`, 4
  `fair_probability`" was the surface. Tier 3a was scoped to differential-test
  *those*.
- **What was actually true.** The 42 came from grepping for **definitions**
  (`^def <name>`). The single confirmed **live** misprice was produced by code
  that has no definition to grep for: `pipeline/intelligence_state.py:1816`
  carries the prob→american formula **inline**, inside
  `_backfill_layer2_board_columns`. It was not in the 42, and it publishes the
  `fair_price` the board renders. Two other module-level converters are nested
  **inside function bodies**, so they are invisible to a `^def` sweep as well.
- **How we found out.** Not by grepping harder. By taking the **user-visible
  field** (`fair_price`) and asking who writes it — which returned **four**
  producers where the definition count had three, one unclamped and correct and
  three clamped.
- **The second half, and it is the more surprising one.** A duplication count
  reads like a defect count and is not. **All 26 `american→probability`
  implementations agree to ten decimal places on every VALID American price.**
  The odds arithmetic is not wrong anywhere. **100% of the divergence is at the
  boundary** — `0`, `None`, `""`, a string price, a float price — which is
  exactly what a missing or malformed quote looks like. Had the pass been costed
  as "26 copies of one formula, consolidate them", it would have found nothing;
  the value was entirely in the inputs nobody's caller happens to send.
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
- **Cost:** none this time — the pass was scoped to test-and-measure and the
  inline copy was found before any consolidation was proposed. Had Tier 3a gone
  straight to "consolidate the 42", the clamp would have survived the cleanup
  untouched and looked fixed. Related: [[feedback_read_the_field_you_already_have]],
  [[feedback_presence_is_not_reachability]], [[feedback_rate_not_count]].

### 2026-08-15 — A PER-CLASS MEASUREMENT OVER A SHARED STYLESHEET IS A PER-SURFACE MEASUREMENT, OR IT IS WRONG

- **What we believed:** soccer renders team names at 13px where NFL renders
  them at 16px. It was in the audit as a measured defect, and it became plan
  item **G1**: "raise 13px to match the 16px used elsewhere." Lane E then
  recorded it as a CONFLICT, because 13px + `nowrap` + ellipsis is the
  *deliberate* fix it had just documented for club names breaking mid-word in a
  ~52px box. Two lanes, one flagged contradiction, an explicit instruction to
  "decide deliberately."
- **What was actually true:** there was nothing to decide. The two lanes were
  describing **two different elements that share one class**. Measured on
  production, all four `.cards-head-team-name` on the page:

      strip  <div>  13px  rgb(237,244,251) = --cards-text  no underline
      strip  <div>  13px  rgb(237,244,251)                 no underline
      card   <a>    16px  rgb(0,0,238)                     underline

  The card head had been 16px the whole time. The 13px belongs to
  `.cards-strip-card--soccer` and is correct. The real defect was a COLOUR one
  the audit had noted separately and never connected: an anchor with no colour
  rule, falling through to the user agent's default link blue.
- **How we found out:** the probe's type table used
  `document.querySelector(selector)` — the **first** match on the page. Soccer
  ships a bespoke scoreboard strip and every other sport ships the generic one,
  so "the first `.cards-head-team-name`" is a *different surface per sport*.
  The comparison was never between sports; it was between a strip and a card.
- **The rule going forward:** a shared stylesheet exists precisely so one class
  renders in more than one place, so **one sample per class is not a
  measurement of that class** — key the table by surface and report a class
  whose computed value differs across surfaces as CONFLATED rather than
  collapsing it to its first hit. `scripts/ui_layout_probe.py` now does this
  and the whole story is in `docs/reports/ui_audit_2026_08_14/README.md`,
  because the wrong number outlived the probe that produced it and got written
  into two plans.
- **Cost:** one plan item specified backwards, and it would have been shipped
  as an instruction to undo a correct fix — the "conflict" existed only because
  both sides were right about different elements. Second retraction from this
  audit's probes; the first was the synthetic `el.click()` that reported WNBA's
  working tabs as broken.

### 2026-08-15 — A PROBE THAT PASSES ON AN ERROR PAGE. Attach the liveness check to the SAME fetch

- **What we believed:** `scripts/ui_layout_probe.py` printing a full table of
  `0px overflow` and exit code **0** meant the pages were clean.
- **What was actually true:** every route on production was returning **HTTP
  502** — a 223KB Render error page. It has no cards, so `cards: 0`; it does not
  overflow, so `overflowPx: 0`. Every single metric read healthy *because* the
  app was down. The script's own docstring said "0 cards is NOT a pass" and its
  exit code said pass anyway.
- **How we found out:** three sports going from 16, 16 and 1 cards to zero
  simultaneously — a coincidence too large to be data. `curl -w "%{http_code}"`
  settled it in one call. The probe had the `Response` object in its hand the
  whole time and never looked at `.status`.
- **The rule going forward:** an instrument that derives its numbers from a
  fetched document must assert the FETCH before it reads the document, in the
  same call — not in a separate health check that can pass at a different
  instant. And a "not present" count needs a named reason to be allowed: the
  probe now fails on `>= 400`, and fails on 0 cards unless the sport is in an
  explicit `OUT_OF_SEASON` set that carries a review date. An exemption with a
  name is auditable; a tolerated zero is not.
- **Cost:** one wasted before/after window, and about ten minutes spent
  believing production had lost every card on the platform. Note the deploy
  history explained it exactly — the 502s sat inside another session's
  02:53-03:00 deploy — which is the second time this week that "read the events
  API, not the symptom" was the shortest path.

### 2026-08-15 — DE-DUPLICATING A FIELD IS NOT DE-DUPLICATING THE OUTPUT. Look at what the fallback renders

- **What we believed:** the card repeated one sentence because the contract
  stamped `panel.body` onto every item of a panel. Remove that and the
  repetition goes away.
- **What was actually true:** the template renders `row.detail or row.heading`.
  Emptying `detail` handed the fallback the wheel, and `heading` is the panel
  TITLE — also a constant across the list, and also rendered in the panel's own
  head. The measured worst-repeat went **6x to 11x**. I made the metric worse
  with a change I was confident about, and only knew because the metric was
  being read on every iteration.
- **How we found out:** the harness number moved the wrong way. Nothing in the
  code review would have caught it — the diff removes a duplicated string.
- **The rule going forward:** when you remove a value that was being repeated,
  render the result before believing it. `a or b` means deleting `a` PROMOTES
  `b`, and in a list `b` is usually the more constant of the two. The real fix
  was structural: the section repeating the data had nothing of its own to say,
  so it was gated out entirely rather than fed a different string.
- **Cost:** one wrong iteration, caught in minutes because the before/after
  probe was already wired. Worth stating plainly: the reason this is a cheap
  lesson and not a shipped regression is that the instrument came first.

### 2026-08-15 — `GIT_INDEX_FILE` PROTECTS YOUR COMMIT AND LEAVES THE SHARED INDEX HOLDING A REVERT OF IT

- **What we believed:** committing through an isolated index is the safe recipe
  on this tree. It is — for the commit. We treated that as the end of the
  obligation.
- **What was actually true:** the isolated index is the only one that learns
  about your commit. The SHARED index still holds the pre-commit blobs for
  those paths, and the moment `HEAD` advances past your commit, those stale
  entries stop being "nothing staged" and become **a staged revert of your own
  work**. Found at checkpoint, 30 minutes after the deploy:

      git diff --cached --name-only   ->  exactly my 7 files, nothing else
      git diff --cached --stat        ->  30 insertions, 710 deletions
                                          (my commit was 710 / 30)
      git status (worktree)           ->  clean for those paths

  Two of the seven were NEW files, so they were staged as **deletions** while
  sitting on disk as `??`. Any session running a bare `git commit` would have
  shipped the removal of a lane that was live in production.
- **How we found out:** `git status -sb` at checkpoint, which the skill demands
  before writing anything. It would not have shown up in a file read, a test
  run, a probe, or the deployed service — all of which were green.
- **The rule going forward:** the isolated-index recipe has a second half.
  After committing with `GIT_INDEX_FILE`, run
  `git reset -- <the same paths>` against the SHARED index so it matches the
  new `HEAD`. Check `git diff --cached --name-only` first: if other paths are
  staged, they are someone else's and a path-scoped reset is the only safe
  form. This is the same family as "`git status` is not `git diff --cached`",
  but the causal direction is the part that was missing — **we generated the
  revert ourselves, by following the recipe.**
- **Cost:** none this time, caught at checkpoint. The exposure window was ~30
  minutes across a tree with nine live sessions, and the loss would have been
  silent: the files exist, the tests pass, production is correct, and only the
  index disagrees.

### 2026-08-15 — a scoped search answers a scoped question. I shipped a field's semantics on one, and the unscoped search later named the test that guards it

- **What we believed:** I had found every consumer of `edge_vs_consensus_pct`.
  I ran a scoped `Grep` over `syndicate/`, got two hits, both of them producers,
  and concluded the field had no external readers. The unscoped repo-wide search
  had timed out at 120s and I moved on without it.
- **What was actually true:** `tests/test_quote_ref.py` asserts that exact field
  in both directions (`< 0` and `> 0`). It was never in my test run. I changed
  the field from always-numeric to absent-when-the-consensus-refuses and
  committed (`2ac3c6bc`) without ever executing its guard. A second consumer,
  `nfl/preseason_cards.py`, reads `book_grid`'s `consensus` through
  `read_book_grid_artifact` — an ARTIFACT hop, which is why a search for
  `book_grid` importers did not surface it.
- **How we found out:** the background search finished after the checkpoint. The
  change turned out to be safe — 92 further tests green, and `consensus[side] =
  None` was already reachable through the empty-prices branch, so the consumer
  already tolerated it. **But safety was established after shipping, not
  before.** A null result from a timed-out search is not a null result.
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
- **Cost:** none in production (nothing deployed) and none in correctness. The
  cost was epistemic: for about an hour the ledger recorded a verified-safe
  change that had not been verified.

### 2026-08-15 — FORBIDDEN: never put `$$` (or any per-shell value) in `GIT_INDEX_FILE`. Each Bash call is a NEW shell, and an absent index file is an EMPTY one, not an error

- **What we believed:** `export GIT_INDEX_FILE=/c/tmp/idx-lane-$$` is the
  isolated-index recipe `state.md` mandates for this shared worktree. It looked
  right, and the staging call it was used in behaved perfectly — `git diff
  --cached --numstat` showed exactly the 10 intended files.
- **What was actually true:** `$$` is the shell's PID, and **every Bash tool
  call is a different shell**. The staging call and the commit call therefore
  pointed `GIT_INDEX_FILE` at two DIFFERENT paths. The commit's path did not
  exist — and git treats a missing index file as an **empty index**, silently,
  with no error. So `git commit` recorded the empty tree:
  **`37448 files changed, 73368097 deletions(-)`**, deleting the entire
  repository including `.claude/hooks/`, on `main`.
- **How we found out:** the commit output was 5.1 MB of `delete mode` lines. It
  announced itself only because it was catastrophic. **A partial version of this
  — a stale index holding a subset — would have printed a plausible stat line
  and been indistinguishable from a correct commit.**
- **Why it was recoverable:** it was never pushed (`origin/main` was
  `3a4de87b`), so `git reset --soft HEAD~1` restored the branch pointer without
  touching the index or the working tree. **`--soft`, never `--hard`:** seven
  sessions' uncommitted work was in that tree, including one deliberately
  held-back change. A reflex `--hard` here would have destroyed all of it and
  would NOT have been recoverable.
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
- **Cost:** one bad commit on local `main`, ~10 minutes, no lost work.

### 2026-08-15 — A DATE TEST WRITTEN IN THE FORMAT THE CODE ALREADY HANDLES CANNOT DETECT THAT IT ONLY HANDLES THAT FORMAT

- What we believed: `soccer-backtest-leakage` was CLOSED-VERIFIED. It made
  `as_of` required, was double-mutation tested, and ran 526 green.
- What was actually true: **the filter was inert for nine of ten leagues**,
  including all four in season. `compute_team_ratings` compared
  `str(row["date"])[:10] >= cutoff` as raw TEXT, and `history/*.csv` is
  `DD/MM/YYYY` for every non-MLS league. `'17/05/2026' >= '2026-08-14'` is
  **False** because '1' sorts before '2', so no row was ever excluded.
  eredivisie returned an identical **923 match-rows** at every as-of from 2023
  to 2026 — a September 2023 rating built from May 2026 results.
- How we found out: not by reading the code — by asserting a PROPERTY over the
  real committed files. Ratings as-of an early date must select FEWER rows than
  as-of a late one. They selected the same, at every date.
- Why the tests could not have caught it: `tests/test_soccer_team_ratings_as_of.py`
  builds its fixtures in ISO, which is the one format the comparison handles.
  It tested the branch, not the parse. **The fixture format WAS the assumption
  under test, and it was supplied as a given.**
- The rule going forward: **when a test exercises parsing or comparison of an
  external format, write the fixture in the format the SOURCE ships, not the
  format the code prefers — and confirm what the source ships by reading it.**
  One `head -1` of each committed file would have shown two formats. Also:
  a same-shape bug hid two more (30th/31st dropped as "future"; the text sort
  behind `rows[-window:]` selecting "latest in the month" rather than "most
  recent"), so a format mismatch is rarely one bug.
- Cost: a closed lane's central claim was false for a day, its successor lane
  nearly published a backtest number off leaked ratings, and every rating for
  the four in-season leagues was built from a biased sample of the season.

### 2026-08-15 — A GUARD'S STATED REASON IS A CLAIM ABOUT ANOTHER FUNCTION, AND IT ROTS WITHOUT TOUCHING EITHER FILE

- What we believed: soccer refused an edge on all 3-way markets because
  "`_no_vig_over_probability` pairs home against away and would silently drop
  the draw". That reads as a safety property and had stood since `#263`.
- What was actually true: that function learned the draw leg in `95305cab` at
  **13:13 CDT on 2026-08-07**, and the refusal was written at **23:43 the same
  day** — false when it was written, and `git merge-base --is-ancestor`
  confirms the ordering. It suppressed every h2h edge soccer had, on its
  flagship market, for a week.
- How we found out: by calling the real `_no_vig_over_probability` on the live
  board's four h2h rows instead of trusting the comment. It returned a correct
  three-leg de-vig (Telstar 133/255/183 -> .4292/.2817/.3534, sum 1.0643, fair
  .4033).
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

### 2026-08-15 — I QUOTED THE "A BRANCH CUT FOR ONE SERVICE IS A ROLLBACK FOR ANOTHER" RULE, THEN BROKE IT ONE NOTE LATER

- What we believed: my change stacks on the unmerged `as_of` work, so the
  commit should branch from `fix/soccer-backtest-leakage`. I wrote that into
  the lane as a recipe.
- What was actually true: `git diff --stat origin/main fix/soccer-backtest-leakage`
  is **127 files, 3,618 insertions, 33,673 DELETIONS**. The branch predates a
  full day of many sessions' work, and is 114 lines behind `origin/main` on
  `run_live_odds_refresh_worker.py` — the very file I had just edited.
- How we found out: the checkpoint's own `git diff --stat` step, which is there
  precisely to ground the summary in reality rather than memory.
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

### 2026-08-15 — A JOB THAT ONLY FLUSHES ON COMPLETION CANNOT SURVIVE A SESSION BOUNDARY, AND I LAUNCHED TWO

- What we believed: a ~100-minute backtest running in the background was
  progress being made. It had been launched detached, so the session was free
  to do other work while it ran.
- What was actually true: it wrote its output **only at the end**. The session
  ended while it was still simulating, the process was killed, and it left
  **zero** bytes — no partial dump, no resumable state, no way to tell how far
  it got. ~70 minutes of compute produced nothing. The first, shorter run of
  the same script had already survived only by luck of timing.
- How we found out: the reconciliation pass at session end. `ls` showed the
  per-match JSONL simply absent, and the summary file's mtime proved it was the
  EARLIER run's output, untouched.
- The rule going forward: **before launching a long job, ask what it writes if
  it is killed at the 90% mark.** If the answer is "nothing", that is a defect
  in the job, not a risk to accept — append per unit of work (per league, per
  day) so the run is resumable and partial results are still results. A
  progress-free, output-free job is indistinguishable from a hung one while it
  runs and from a job never launched after it dies.
- The second-order error, which is the more useful one: I let the *answer to a
  question the session needed* depend on a job the session could not outlive. A
  detached job is the right tool for work whose result the NEXT session can
  pick up; it is the wrong tool when the current session must reason about the
  output. Sequence it accordingly, or scope it down to something that finishes.
- Cost: the dispersion-vs-discrimination question stayed open, and the fitter
  and AUC diagnostic built to answer it have still never run on real data —
  code that exists but has never been executed against production data, which
  is exactly the kind of thing a later reader mistakes for a finished result.

### 2026-08-15 — FORBIDDEN: never trust a CLEAR from `lane-guard.py`'s `_claims()` alone. It UNDER-reports, and that is the dangerous direction

- **What we believed.** The protocol says to collision-check "via `lane-guard.py`'s
  own `_claims()`, not by grep". Several lanes, mine included, recorded their
  collision check as CLEAR on that basis and treated it as authoritative.
- **What is actually true.** `_claims()` only continues a `Files:` block on lines
  whose stripped text starts with `-`. A block written with **comma
  continuation** loses every path after the first line:

  ```
  - Files: `syndicate/features/shared/odds_book_quotes.py`,
    `pipeline/layer2_shortlist.py`, `tests/test_odds_book_quotes*.py`.
  ```

  Measured directly against the live ledger: `guard sees odds_book_quotes: True`,
  `guard sees layer2_shortlist: False`. The `quote-shard-latest-index` lane
  (OPEN) has claimed `pipeline/layer2_shortlist.py` since it opened, and the
  guard has never protected it.
- **Why this is the bad direction.** The 2026-08-14 learning was about a regex
  inverting "NOT claimed" into "claimed" — noisy, but it fails toward refusing.
  **This one fails toward permitting.** A claimed file reports CLEAR, the guard
  raises no PreToolUse block, and a second session edits a file another lane
  owns believing it did the check correctly. Related:
  [[feedback_unknown_must_not_default_permissive]].
- **How we found out.** Not from the guard. From running a blast-radius test set,
  finding 6 failures, bisecting them on a clean control worktree to another
  session's uncommitted `pipeline/layer2_shortlist.py`, then going to read WHO
  owns that file — and discovering a lane claimed it while `_claims()` returned
  False for it.
- **The rule going forward.**
  1. **A CLEAR from `_claims()` is necessary, not sufficient.** Confirm every
     file you intend to edit by READING each OPEN lane's `Files:` block, and
     distinguish a claim from prose — "read-only dependency", "NOT this lane's
     files", and "Files: none claimed yet, deliberately" are all non-claims that
     look like hits to a grep.
  2. **Write your own `Files:` block as nested bullets, one path per `-` line.**
     That is the only format the parser handles, and it is what 7 of 8 lanes
     already use. A comma-continuation block silently leaves your work
     unguarded.
  3. Until the parser is fixed, **the guard's silence is not evidence.**
- **Cost:** none realised yet — my two files were genuinely unclaimed when
  re-checked textually, so commit `7bb74c95` is safe. But the lane whose claim
  was dropped had its files unprotected for the whole day, and the protocol was
  actively recommending the method that missed it.

### 2026-08-15 — FORBIDDEN: never judge a pinned deploy by ANCESTRY alone. Patch-id is the test.

- What we believed: `git merge-base --is-ancestor <live> <my-tip>` returning
  false means the deploy would revert live work, and is a stop condition.
- What was actually true: with several sessions cherry-picking the SAME patches
  onto each service's own live SHA, identical content carries different SHAs.
  On 2026-08-15 the web train cut from `c774fe1a`; by the time CI finished, live
  was `0bf866c3`. Ancestry said **"my deploy would drop it."** `git cherry` said
  both live commits were already present **by patch-id** (`-` for both), and the
  only production delta was the train's own two additions. The deploy was
  strictly additive.
- How we found out: ran `git cherry <my-tip> <live>` and diffed
  `syndicate/ pipeline/ app.py` between the two, instead of trusting the
  ancestry verdict in either direction.
- The rule going forward: **on a pinned-deploy service, ancestry is necessary
  evidence of safety but its ABSENCE is not evidence of danger.** A false
  ancestry result must be escalated to a patch-id + content diff before either
  deploying or aborting. The same trap in mirror image is already recorded:
  `deactivated` means superseded, not reverted.
- Cost: nearly aborted a green, fully-gated deploy; and in the other direction,
  this is exactly how a session silently reverts a peer.

### 2026-08-15 — FORBIDDEN: never wake many idle sessions at once. It stalls them.

- What we believed: sending a coordination check-in to every live session is a
  cheap way to build a status map.
- What was actually true: eight idle Opus sessions were messaged inside ~90
  seconds. **Six stalled**, each frozen at the exact second the message landed
  (16:18:09 / 16:18:21 / 16:18:33 / 16:18:44 / 16:19:00 / 16:19:26), transcripts
  ending with the message and no assistant turn after it. Only the ones already
  mid-turn survived. The messages were also far longer than they needed to be.
- How we found out: `list_sessions` showed `lastActivityAt` frozen at those
  timestamps; `list_events` showed the message as the terminal event.
- The rule going forward: **read the other session's transcript instead of
  asking it.** `list_events` costs nothing on their side, returns more than a
  reply would, and cannot stall them. If a session must be messaged, do it ONE
  at a time and keep it short. Recovery is just delivering a new turn —
  "continue" is enough — but only the owner can spend it.
- Cost: six stalled sessions and a coordination round that returned less than
  reading would have.

### 2026-08-15 — A BASELINE QUOTED IN PROSE MAY CORRESPOND TO NO RUN ON DISK

- What we believed: the ask regression baseline was **23/52**, and three
  briefs told sessions to judge their work against it.
- What was actually true: `post_m1_fixed_2026_08_14.json` is a **ranking-only
  run with `total: 10`**. The 23/52 figure existed only in prose. The real
  pre-deploy control was **25/52** (`prebaseline_c774fe1a_2026_08_15.json`).
- How we found out: another session opened the artifact instead of citing the
  number, then said so.
- The rule going forward: **before handing anyone a baseline, open the file and
  check `total` matches the suite size.** A number that has been repeated
  between sessions is not thereby measured — repetition is not evidence, and a
  baseline is the one input that silently invalidates every comparison built on
  it.
- Cost: three briefs carried a wrong predicate; caught before any lane was
  judged against it.

### 2026-08-15 — A CLASS NAME IS NOT A SURFACE, and `querySelector` turned that into two wrong plan items

- **What we believed:** the UI audit's per-class type table described "soccer's
  team names" — 13px against 16px elsewhere — and that a closed lane's 13px
  ellipsis fix therefore CONFLICTED with the plan's instruction to raise them.
  Two lanes, both confident, apparently contradicting each other.
- **What was actually true:** `.cards-head-team-name` lives on TWO surfaces. The
  13px rule is scoped to `.cards-strip-card--soccer` — the scoreboard strip,
  where the names are `<div>`s in a ~52px box and truncation is correct. The
  link-blue anchors are on the CARD head, which was already 16px. The audit's
  table was built with `document.querySelector(selector)`, which returns the
  FIRST match, so one surface's number was published as the class's number.
  **There was never a conflict.** Both lanes were right about different
  elements, and executing the plan literally would have undone a correct fix.
- **How we found out:** grepping for every rule that sets the class, after the
  brief flagged the "conflict" as something to resolve rather than obey.
- **The rule going forward:** on a SHARED stylesheet, a per-class measurement
  must enumerate every matching element and report a class rendering at two
  sizes as *conflated*, never collapse it to its first hit. The whole point of a
  shared stylesheet is that one class renders in more than one place. The probe
  now does this and flags `type conflated:` per sport.
- **Cost:** two plan items specified from a wrong number, one of which would
  have caused a regression. Caught before any edit.

### 2026-08-15 — THE INSTRUMENT THAT DROPPED A MISSING KEY, AND THE CORRECTION IT HANDED ME MID-FIX

- **What we believed:** the tabular-figures check had never measured MLB — all
  three numeric classes matched zero elements, so the platform's biggest sport
  had passed a check that never ran on it.
- **What was actually true:** MLB has 495 / 60 / 30 of those classes and every
  one computes `tabular-nums`. The earlier fix landed exactly as claimed. My
  `{}` came from a one-off that read the DOM **600ms after load** — and MLB is
  the single sport that renders through `cards_source.js`, so the elements did
  not exist yet. I had a rule for this already (*watcher over spot check*) and
  applied it to async production effects but not to a page render.
- **What was REAL underneath it:** the probe genuinely did drop a missing key —
  `querySelector(sel); if (!el) return;` — and `summarize()` had no branch for
  an absent key. NCAAF serves 16 cards and matches ZERO `.cards-market-main`.
  That read as clean. So the defect existed; my attribution of it did not.
- **How we found out:** the fixed probe, run against production, contradicted
  the claim that motivated fixing it.
- **The rule going forward:** two rules, and they are separable. (1) A value
  meaning *"not measured"* — missing element, dropped key, error page,
  first-of-many match, render not yet happened — must never share a code path
  with *"fine"*. (2) **Never read MLB's DOM on a fixed delay.** Every other
  sport is server-rendered and stable at load; MLB is not.
- **Cost:** one wrong claim stated to the user and written into a lane, both
  corrected within the session. The underlying instrument bug was real and is
  fixed in `33e7d7a8`.

### 2026-08-15 — ON A CONTENDED LEDGER, NEITHER COPY IS AUTHORITATIVE, AND A WHOLE-FILE COMMIT PICKS A WINNER SILENTLY

- **What we believed:** the rule "check `git diff --cached` before committing"
  plus "my worktree copy is additive (+146/-0)" was enough to commit
  `.syndicate/lanes.md` safely.
- **What was actually true:** that `+146/-0` expired. Minutes later the same
  diff showed **3 deletions, two of which were other sessions' lines** — an
  `ask-sport-coverage` status header and a soccer-model result line that had
  landed on `origin/main` while I worked. Committing my copy would have reverted
  both. Rebuilding my edits on `origin/main`'s copy fixed that and immediately
  caused the MIRROR failure: `ask-sport-coverage`'s header was NEWER in the
  worktree — an uncommitted edit by a live session — and basing on origin
  destroyed it on disk.
- **How we found out:** re-running `git diff origin/main -- <file>` and reading
  the `-` lines individually instead of trusting the earlier numstat.
- **The rule going forward:** for a file many sessions append to, **diff for
  deletions immediately before the commit, and read each one.** A file where
  both copies contain something the other lacks cannot be resolved by choosing a
  base — splice your own block onto the freshest copy and leave every other line
  untouched. If you do clobber someone, say so and tell them it is a
  reconstruction, not their text.
- **Cost:** none shipped. One session's ledger line destroyed and restored by
  hand; that session was notified and has since corrected it themselves.

### 2026-08-15 - A PINNED DEPLOY IS NOT ON main's LINEAGE, SO ANCESTRY ANSWERS THE WRONG QUESTION

- **What we believed:** `git merge-base --is-ancestor <my commit> <live SHA>` is
  the check for "did my work survive the next session's deploy". It had worked
  three times today for Lane G.
- **What was actually true:** it works only while the deploys share a lineage.
  My two CSS commits live on `origin/main`; the deploys that shipped them were
  PINNED commits parented on web's live SHA, so they are a different lineage
  carrying identical trees. When the next session deployed `7abd8e12`, ancestry
  reported **NO** for both my commits - and all four CSS blobs were
  **byte-identical**. Read literally, ancestry said my work had been dropped
  while it was in fact live.
- **How we found out:** checking ancestry at checkpoint, getting NO, and not
  believing it - because the same probe had measured zero non-tabular digits
  minutes earlier.
- **The rule going forward:** **test deployment by CONTENT.** Compare
  `git rev-parse <deploy>:<path>` against your own commit's blob for every file
  you shipped. Ancestry is a cheap positive signal (YES means yes) but its NO is
  uninformative on a tree where deploys are pinned. This is the second form of
  the trap already in state.md ("web runs a deploy branch, not main").
- **Cost:** none - caught in the same breath. But a session that trusted the NO
  would have re-deployed work that was already live, superseding whatever the
  other session had just shipped.

### 2026-08-15 - A FIXED `GIT_INDEX_FILE` NAME COLLIDES ACROSS SESSIONS, AND A FAILED read-tree LEAVES AN EMPTY INDEX THAT STAGES THE WHOLE REPO AS DELETIONS

- **What we believed:** the existing rule - never put `$$` in `GIT_INDEX_FILE`,
  because each Bash call is a new shell - was fully discharged by using a fixed
  name like `/c/tmp/idx-final`.
- **What was actually true:** a fixed name is shared mutable state on a tree
  with nine sessions, exactly like the shared index it was invented to avoid.
  A stale `/c/tmp/idx-final.lock` made `git read-tree origin/main` fail with
  exit 128; `GIT_INDEX_FILE` then pointed at a file that did not exist, **which
  git treats as an EMPTY index, not an error** - and the next
  `git diff-index --cached --stat origin/main` listed **~37,000 files as
  deletions**. `/c/tmp/idx-final2` was sitting there too, and is not mine.
- **How we found out:** the deletion list scrolled past instead of the expected
  one-file diff. Nothing was pushed only because the `&&` chain broke on the
  failed `write-tree`, not because anything checked.
- **The rule going forward:** scope the index file to the SESSION
  (`/c/tmp/idx-<session-id>-<purpose>`), remove both it and its `.lock` first,
  and **assert the index is non-empty after `read-tree`**
  (`git ls-files --cached | wc -l` > 100) before staging anything. The empty
  index is the dangerous state precisely because it looks like a successful
  setup - same family as "a value meaning not-measured must not share a path
  with fine".
- **Cost:** none shipped, one aborted commit. The exposure was a push that would
  have deleted the repository from `main`.

### 2026-08-15 — FORBIDDEN: never gate a DEPLOY with a cross-session message. It always arrives late.

- What we believed: telling the other live sessions "hold, do not fire a web
  deploy" would serialise deploys well enough to assemble one train.
- What was actually true: **web took five deploys in twenty-one minutes from
  four different sessions** (19:15 ask K6 -> 19:20 quote-age alarm -> 19:28 CLV
  allowlist -> 19:36 tabular digits -> 19:47/19:54/20:22 more). The 19:20 deploy
  **cancelled the 19:15 one mid-build**, and its owner did not know. Every hold
  message sent arrived AFTER the deploy it was meant to prevent, because a
  message waits for the target's current turn to end while firing a deploy takes
  seconds. Holding politely, per the documented rule, meant never getting a slot
  at all: two attempts, both blocked by an in-flight build.
- How we found out: polled `/v1/services/<id>/deploys` around each attempt and
  read `createdAt` against the cancellation.
- The rule going forward: **deploy serialisation needs a LOCK, not an
  announcement.** A message is advisory and asynchronous; a deploy is immediate
  and destructive to whatever is building. Until a real mutex exists (a claim
  file checked by the deploy path, or one session designated as the only one
  that may POST), assume any web deploy may be cancelled by a peer at any moment
  — so **re-read the live SHA after your deploy reports live, and verify your
  own commit is present by patch-id** rather than trusting that it landed.
  `3ba1c2cf` was cancelled at 19:20 and was still absent from live at 20:22.
- Cost: one fix (ask K6) cancelled and still unshipped; two coordinated trains
  built, tested and abandoned.

### 2026-08-15 - A LABEL-MATCHED LOOKUP IS NOT A SUBSTITUTE FOR THE FIELD, AND ITS FAILURE IS SILENT

- **What we believed:** soccer's card losing its `.cards-data-pair` rows was
  either the producer publishing less or my own G3 suppression gate misfiring.
  I asserted both, in that order, and both were wrong.
- **What was actually true:** `sim.periods` is `{}`, so the board contract
  builds a stand-in Full Game row, and that row sourced its market and edge via
  `_metric_lookup(metrics, "Spread") or _metric_lookup(metrics, "Total")`.
  Soccer publishes `Home win`, `Draw`, `Away win`, `Total goals`, `BTTS`,
  `Over 2.5`. **Nothing matched**, both fields became the null placeholder, and
  the G3 gate then correctly dropped a row on which every value was a
  placeholder or a restatement. Meanwhile `betting.home_spread` (-1.5),
  `betting.total` (2.5) and `sim.score` sat on the same game, and the branch 90
  lines above already built `ATS ... | Total ...` from exactly those fields.
  **The card displayed its market line and its edge nowhere, on a game that had
  both.**
- **How we found out:** fetching the served JSON and reading `metrics` next to
  `betting`, instead of reasoning about which of my two suspects it was.
- **The rule going forward:** when a value can be read from a FIELD, read the
  field; a lookup keyed on a human-facing label is a guess about another
  team's vocabulary and it fails silently, producing a placeholder that looks
  exactly like genuinely-absent data. If a label lookup must exist, it is the
  fallback, never the primary. And: **a suppression gate doing its job is not
  evidence its input is healthy** - the gate was right, its input was starved,
  and the visible symptom was identical either way.
- **Cost:** two wrong public attributions; a week of soccer cards with no
  market line. The fix was 30 lines and the data was always there.

### 2026-08-15 - ENUMERATE EVERY SPORT THAT REACHES A CHANGED BRANCH *BEFORE* DEPLOYING

- **What we believed:** stating a blast radius of "nfl does not reach this
  branch (0/16), ncaaf reaches it but is inert (0/16 rows changed)" was a
  measured blast radius. It was measured - it just was not complete.
- **What was actually true:** **MLB reaches the same branch on 15/15 games**
  and was never checked. It is inert there too (0/15 rows changed), so nothing
  broke, but that was luck rather than method: the check happened AFTER the
  deploy was live.
- **How we found out:** the probe's MLB card-height spread moved in the
  post-deploy run, which forced the question "does MLB even reach this code?"
  - a question that should have been asked while the change was still local.
- **The rule going forward:** when changing a shared contract, enumerate the
  branch predicate across **every** sport that calls it and write the counts
  down, before the deploy. "The two I thought of" is not an enumeration. The
  cheap form is one loop over each sport's served payload testing the
  predicate - it took under a minute afterwards and would have cost the same
  before.
- **Cost:** none realised. The exposure was a shared-contract change reaching
  production with a third of its blast radius unexamined.

### 2026-08-15 - I APPLIED "ONE SAMPLE OF A MOVING QUANTITY" TO PRODUCTION AND NOT TO MY OWN MEASUREMENT

- **What we believed:** MLB's card-height spread was fully explained by game
  state. Measured once: Preview n=10 spread **80px**, Final n=2 spread 82px,
  Live n=3 spread 1393px. Clean story - the layout is tight inside a state and
  the whole number is live-game content. I wrote it into a lane as the finding.
- **What was actually true:** the same page, 20 minutes later, no code change:
  Preview spread **797px** (3020-3817px). The tightness was an artifact of the
  moment. Measured properly across all 10 Preview cards at once, height tracks
  `.cards-data-pair` count at ~62px per pair, 20-57 pairs per card - the spread
  is CONTENT VOLUME, and grouping by state does not remove it because content
  varies inside a state too.
- **How we found out:** re-running the probe after changing it, and noticing
  the number I had just explained had moved.
- **The rule going forward:** I already hold this rule for production
  quantities (`learnings.md`, three wrong root causes in one session from a
  single sample). It applies with equal force to a measurement I take MYSELF to
  explain something. Before writing "X explains Y", take the reading twice, or
  measure the whole population once - here, ten cards against their content
  counts settled in one pass what two timed samples could not.
- **Second-order rule, and the useful one:** when a metric cannot separate the
  thing you care about (layout) from a confound (content volume), report the
  confound alongside it rather than refining the metric. `content varies 20-57
  pairs/card` next to a 1583px spread is interpretable; the spread alone is
  not, and no amount of grouping was going to make it so.
- **Cost:** one wrong explanation written into a lane and reported to the user,
  corrected within the hour. The EXONERATION it accompanied was and remains
  correct.

### 2026-08-15 — a mid-ramp reading is not a window reading; I called a 446MB difference "noise"

- **What we believed:** at 19:51Z I told the owner the most likely outcome was
  that kills would land and the quote shard was not the cause. The evidence was
  peak anon 2,839 MB tonight against 2,897 MB last night in the same clock slot
  — a 2% gap I called noise.
- **What was actually true:** peak across the FULL window was 3,572 MB against
  4,018 MB, a 446 MB gap, and the kill count went 5 -> 0. The fix worked.
- **How we found out:** by re-measuring at window close instead of standing on
  the earlier number. The 19:51 reading was taken before the shard ramp bit, so
  it compared two processes that had not yet done the expensive thing.
- **The rule going forward:** a peak is only comparable across windows that
  contain the same WORK, not the same clock span. Before comparing peaks, check
  that the expensive stage has actually run in both — otherwise the comparison
  is of two warm-ups. State the window's work content, not just its start and
  end times.
- **Cost:** none to production — I held for the measurement instead of acting on
  the prediction, which is the only reason this reads as a caught error rather
  than a shipped one. But the wrong call was stated to the owner with a
  confidence it had not earned.

### 2026-08-15 — AN OCCURRENCE COUNT IS NOT A ROW COUNT, and I published three numbers that could be read as either

- **What we believed.** `served_at_clamp_price: 14` and "1346 `fair_price`
  values served, 24 of them sitting exactly on ±4900" were counts of broken
  markets. I said so in the ledger, and when I first noticed the duplication I
  called it "cosmetic" and asserted "the count 14 is correct".
- **What was actually true.** They are counts of OCCURRENCES in a served
  payload that echoes one logical row into several sections. The 14 were **one**
  mispriced market (`out_of_clamp_count: 1`); the 24 were **two** market sides.
  The finding itself was never wrong — the join was always per-row — but the
  magnitude was inflated ~14x for anyone who quoted the headline instead of
  reading the table.
- **How we found out.** Not from the instrument. From reading its own evidence
  array and noticing the same row printed 14 times. The array was the honest
  signal; the scalar counts beside it were the misleading ones.
- **Why "cosmetic" was the wrong call.** A number in a ledger outlives the
  session that wrote it and gets quoted without its table. "14 mispriced rows"
  would have been a defensible read of what I wrote.
- **The rule going forward.** When counting anything extracted by walking a
  nested payload, **report the occurrence count and the distinct-entity count as
  separate, explicitly-named fields.** Never publish one scalar that could be
  read as either. If deduping, the key must include entity identity — deduping
  on value alone collapses two genuinely different entities that share a value,
  which UNDER-reports and is the more dangerous direction.
- **Second-order, and worth keeping:** the fix required identity to flow down
  the walk to the node holding the number. Identity is safe to inherit;
  **the numbers are not** — inheriting a probability downward would pair it with
  an unrelated nested price and manufacture a finding. That asymmetry is now
  pinned by a test that fails if someone "simplifies" it.
- **Cost:** none realised — caught before anyone quoted it, and corrected in
  `audit_2026-08-15_probability_differential.md` and `deploys.md`. Related:
  [[feedback_rate_not_count]], [[feedback_read_the_field_you_already_have]].

### 2026-08-15 — A PINNED-DEPLOY SERVICE SILENTLY REVERTS PEERS. VERIFY YOUR COMMIT AFTER IT GOES LIVE.

- What we believed: a deploy reporting `live` with your commit means your change
  is in production and stays there.
- What was actually true: the prop `0.5` fix went live on refresh-worker at
  21:36:59Z as `0fa44322`, verified additive and content-checked. **Eight
  minutes later refresh-worker was `846bb74e`**, which does NOT have `0fa44322`
  as an ancestor, and the deployed prop scripts were back to **7 and 8 reachable
  `... or 0.5` sites**. A peer session had cut its branch from an earlier live
  SHA, so its deploy silently undid mine. Nothing failed, nothing warned, and
  the deploy history shows two successes.
- How we found out: re-read the live SHA at checkpoint time and tested ancestry
  plus FILE CONTENT, rather than trusting the deploy that had reported `live`.
- The rule going forward: **on a service whose deploys are pinned cherry-picks,
  "live" is a lease, not a fact.** Every session cutting from "the current live
  SHA" is cutting from a moving target, so the last writer wins and the loser is
  never told. Re-verify your change by content minutes AFTER it lands, not just
  at the moment it lands — and when a peer is active on the same service,
  expect to re-deploy. The durable fix is one deployer per service, or trains,
  not per-lane deploys.
- Cost: a verified production fix silently reverted within 8 minutes; production
  fabricates a 0.5 on price-missing prop rows again.

### 2026-08-15 — Render's git mirror is PER SERVICE and only refreshes at build time

- What we believed: pushing a branch to origin makes its commits deployable on
  any service in that repo.
- What was actually true: `POST /v1/services/<id>/deploys` with a commit pushed
  AFTER that service's last deploy returns **404 "service does not have a
  commit"**, persistently — 3 attempts, ~20 minutes apart. Web was immune only
  because it had deployed six times that day, keeping its mirror warm. The
  workers, last deployed hours earlier, could not see the branch at all.
- How we found out: read the 404 BODY instead of the status code; it names the
  service and the sha explicitly.
- The rule going forward: **"route one" — warm the mirror first.** Deploy the
  service's own current live commit (a no-op in code), which forces a fetch,
  then deploy the target. Measured: the same sha that 404'd three times fired
  41 seconds after the warm deploy landed. Cost is two restarts, so take both
  inside detected lulls. This has probably been silently blocking worker deploys
  from fresh branches for some time.

### 2026-08-15 - `wait_for_selector` PROVES ATTACHMENT, NOT COMPLETION, AND I HAD ALREADY "FIXED" THIS ONCE

- **What we believed:** the MLB render race was closed. Earlier today I replaced
  a fixed 400ms delay with `wait_for_selector('.cards-game-card')`, measured
  15 cards on 10 consecutive readings, and wrote the rule down as "wait on
  CONTENT, not a timer".
- **What was actually true:** waiting on the first card only proves the first
  card exists. MLB keeps populating for **seconds** afterwards. Total
  `.cards-data-pair` across 15 cards at 390px:

      +0ms 482   +600ms 530   +1200ms 590   +2000ms 683   +3000ms 719   +4500ms 719

  The 600ms settle I added measured MLB at **74% of its final content**, so
  every MLB height, spread, content-unit and model figure produced today came
  off a partially-rendered page -- including the numbers I used to argue that
  the spread was content rather than layout. That conclusion survived
  re-measurement; it was not entitled to.
- **How we found out:** the height model reported MLB mobile Preview as
  unfittable while a hand check at 2500ms showed 10 cards with 5 distinct
  content counts. The instrument disagreeing with a manual check is what
  exposed it -- not any failure in the output, which looked entirely healthy.
- **The rule going forward:** for a page that renders progressively, wait for
  the DOM to STOP CHANGING -- poll a cheap fingerprint until it is stable
  across two consecutive samples, cap it, and FAIL if it never stabilises. A
  render still growing when you measure it makes every figure on that row
  provisional, so it is a failure, not a footnote. And the meta-rule: "I fixed
  the timing bug" is a claim about a threshold, and the next threshold is
  usually also wrong. Verify by watching the quantity settle, not by getting a
  plausible number once.
- **Cost:** a day of MLB probe figures that were directionally right and
  numerically wrong, and one conclusion that was lucky rather than earned.

### 2026-08-15 - A UNIT CHANGE CANNOT FIX A FIT WHEN THE UNITS ARE PROPORTIONAL, AND I ALMOST BUILT IT ANYWAY

- **What we believed:** the height model reported UNRELIABLE at 1440 because
  the unit was wrong — desktop's summary grid wraps into columns, so height
  should be linear in ROWS (`ceil(pairs/columns)`) rather than in pairs. It was
  written into a lane as carried-forward work and into a checkpoint as the next
  action.
- **What was actually true:** within any one group, rows are proportional to
  pairs, so fitting in rows is the same regression reparametrized. Measured
  both ways on the same cards at the same instant: residuals **11/11, 139/139,
  52/52 px** — identical to the pixel, with only the slope rescaling. The
  change could not have moved the number it was supposed to fix.
- **How we found out:** measuring both fits BEFORE editing, because the lane
  demanded a falsification test. Ten minutes of probing killed an hour of
  building.
- **The rule going forward:** before changing the unit of a regression, ask
  whether the new unit is an affine function of the old one. If it is, the fit
  is identical and the problem is elsewhere — in the model's form, the grouping,
  or the sample size. This generalises: re-expressing a variable never improves
  a linear fit, so "use a better unit" is only ever a fix when the relationship
  to the outcome changes SHAPE.
- **Second finding, from the same session:** the deeper problem was sample
  size and slate churn, not units. n=3 groups (2 fitted parameters, 1 degree of
  freedom) produced fit ratios of 0.59 and 1.29 while an n=9 group on the same
  page produced 0.09. Four readings of the metric across one evening went
  reliable -> unreliable -> unreliable -> unfittable. **Tuning a model against a
  target that moves every 20 minutes is not measurement.** I stopped and
  reported the negative result.
- **Cost:** none shipped wrong. The lane closed NEGATIVE with the goal unmet,
  which is the honest outcome, and three real defects found on the way were
  fixed.

### 2026-08-15 — check whether the instrument is already firing BEFORE building a way to make it fire

- **What we believed:** the floor could not be measured because all three
  censuses trigger on a rising `anon`, so none had ever sampled the quiet state.
  I opened a lane on that premise and was about to change the trigger and deploy.
- **What was actually true:** `watchdog_should_heap_census` gates on
  `anon_mb >= 1500` and nothing else. No climb term. Only the tracemalloc dump
  required a climb, and I generalised from it to all three. The rest-state
  census had been firing in production for hours — 12 `HEAP_CENSUS` lines since
  18:11 — and the answer was already sitting in the logs.
- **How we found out:** by grepping production for the census output before
  editing the gate, rather than after.
- **The rule going forward:** before building a way to make an instrument fire,
  grep for its output. This is the mirror image of the rule this same
  investigation already learned twice — an absent signal is a fact about the
  EMITTER — and it fails the same way in reverse: assuming silence when the
  thing is talking. One grep answers it.
- **Cost:** none, because the check came first. It would have been one
  unnecessary deploy to a worker whose deploys kill in-flight sims, plus a
  measurement window spent proving something already proven.

### 2026-08-15 — MY OWN WATCHERS FAILED THREE TIMES IN ONE EVENING. Hand-run the gate before trusting a poller.

- What we believed: automating "wait for a lull, then fire" is strictly better
  than doing it by hand, because the lull is 60-90s and easy to miss.
- What was actually true: three consecutive automated watchers failed, each
  differently. (1) An unhandled `HTTPError` on the deploy POST killed the
  process, discarding a lull it had waited 8 minutes to find. (2) The rewrite
  timed out after 55 minutes without ever firing. (3) The third sat in "waiting
  for lull" while `deploy_preflight.py`, run by hand in the same seconds,
  returned **CLEAR** — it was blind to an open window. Firing the two steps
  manually took 11 minutes and worked first time.
- How we found out: ran the gate by hand instead of believing the watcher's
  silence, and the two answers disagreed.
- The rule going forward: **a watcher's silence is not evidence the condition is
  absent — it is evidence about the watcher.** Before waiting on any poller,
  run the same check by hand once and confirm the two agree. If a window is
  confirmed open and the automation has not fired, stop the automation and act
  manually. This is the same shape as the standing rule about absent log lines,
  and it cost roughly 90 minutes of a production regression staying live.
- Cost: the prop `0.5` fix sat reverted on refresh-worker for ~45 extra minutes
  while a poller waited for a lull that was already there.

### 2026-08-15 — a cgroup number minus a per-process number is not a difference, it is a category error

- **What we believed:** 673MB of the refresh-worker's anon was memory pymalloc
  never allocated — computed as cgroup `anon` 1,607.1MB minus pymalloc arenas
  934.0MB. It was reported as the largest component of the floor and became the
  next investigation target.
- **What was actually true:** cgroup `anon` counts the CONTAINER — parent plus
  every child process. `PYMALLOC_STATS` reports the calling process only. The
  worker runs 8-10 children (`daily_update.py`, odds jobs, multiprocessing
  spawns) holding ~504MB. Subtracting one from the other measures nothing.
  Per-process the residue is **~173MB**, not 673MB.
- **How we found out:** the smaps reader's own reconciliation check refused the
  reading — `reconciles: false`, 27.0% apart — because it compared a
  per-process total against the cgroup. That refusal was the finding.
  `ALL_PROCESS_MEMORY` then confirmed it independently: pid 39 at 1,140.8MB with
  ~504MB in children, against a smaps per-process anon of 1,106.9MB.
- **The rule going forward:** every memory number carries a SCOPE — container,
  process, or thread — and only same-scope numbers may be subtracted. Write the
  scope next to the figure. `memory.current`/`anon` and `oomKilled` are
  container; `smaps`, `PYMALLOC_STATS`, `HEAP_CENSUS`, `mallinfo` and
  `getsizeof` are process; a container with children makes them differ by
  hundreds of MB.
- **Cost:** one wrong headline figure that stood for about an hour and set the
  next target. Caught before any code was written against it, and caught by a
  guard written into the instrument rather than by review.

## 2026-08-15 — FORBIDDEN: never treat "the code is deployed" as "the artifact is fixed", for any producer

Both worker fixes went live at 23:16:39Z / 23:17:42Z with zero tracebacks after
the boundary (3 before, 0 after). Nothing on disk changed. `layer2_board` and
`odds_refresh_tracking` are artifact PRODUCERS: the last `LAYER2_SHORTLIST` ran
at 23:12:20Z, four minutes BEFORE the deploy, so every row a consumer could read
was still old-code output. A verification run in that window would have reported
the old numbers and been read as "the fix did not work" — or, worse, a
`no-change` result would have been banked as a measurement.

**The rule:** for a producer, the deploy is the START of the wait, not the end.
Verify against an artifact whose BUILD began after the deploy went live, and
prove that by its own timestamp (`written_at`/`generated_at`), not by the clock
on your request.

**Corollary that bit the same session twice:** "no errors in the logs" is not
evidence a fix works. It is evidence nothing crashed. Those are different
claims, and only one of them was measured here.

## 2026-08-15 — CORRECTION: a chain of three wrong attributions on one number, and what actually ended it

The `-29.90` CLV row was attributed, in order:
1. "an in-play price" — WRONG; the write site deliberately records the previous
   tick's price.
2. "the odds-history feed transposed its labels" — WRONG; each history point is
   internally consistent (`home_line = -away_line`).
3. "books disagree, so `book_prices` mixes signs" — WRONG; 525/525 cells agreed
   with each other.
4. **RIGHT:** the grid ROW's `line` is the away handicap, and home candidates
   inherited it — `cell.home.line == -row["line"]` on 525 of 525.

Each of 1-3 was plausible, cited real code or a real prior incident, and was
stated with more confidence than the evidence carried. What ended it was not
more reasoning but a **labelling-independent invariant**: for one team, `-1.5`
is strictly harder than `+1.5`, so `implied(-1.5) < implied(+1.5)` must hold
whatever anyone's naming convention is.

**How to apply:** when two sources disagree about a label, stop comparing labels.
Find the physical constraint the data must satisfy regardless of naming — a
no-arbitrage relation, a conservation law, a sum-to-one — and test that. And
**note that an aggregate can hide it**: these errors arrived as a mirror pair
(`+30.428` / `-29.900`) that nearly cancelled, leaving a mean of `+0.515` on a
median of exactly `0.000`. A median of exactly zero on a noisy quantity is a
tell, not a comfort.

## 2026-08-15 — FORBIDDEN: never verify a fix by measuring the INPUT it was never meant to change

Armed a watcher to confirm the `layer2_board` line fix in production. Its
predicate compared `row["line"]` against `cell.home.line` on
`/api/board/book-grid` and would PASS only when they stopped being opposite.

**That could never happen, and not because the fix failed.** The grid row's
`line` IS the away handicap and the cells carry their own — that opposition is
the INPUT SHAPE, correct and untouched by the fix. The fix changes what the
SHORTLIST CANDIDATE records. The watcher was pointed at the wrong artifact
entirely, and would have reported `opposite=573 / FAIL` forever.

**Why it is worth a rule and not just a correction:** the failure is
self-confirming in the dangerous direction. A never-passing check produces
exactly the output a genuinely broken fix produces, so the natural next move is
to go debug working code — or to roll back a correct change. The `-29.90` chain
in the entry above cost three wrong attributions; this would have added a
fourth, against my own fix.

**How to apply:**
- Before arming any verification, state which artifact the change WRITES, and
  measure that one. "Related endpoint that shows the same concept" is not it.
- Ask the falsification question about the CHECK, not just the fix: *what
  reading would this produce if the fix worked perfectly?* If the answer is the
  same as the failure reading, the check is broken.
- Gate on the artifact's own `written_at` against the deploy time, so "not
  rebuilt yet" and "rebuilt and wrong" can never be confused. The first version
  conflated them too.

**This is the same rule as "gate on the output, not the input" (2026-08-xx),
arrived at from the opposite direction — there the guard encoded an assumption
about HOW something fails; here the check measured something the fix does not
touch. Both produce a signal that cannot move.**

### 2026-08-15 — A DEPLOY CLAIM IS ADVISORY. It binds participants, not the fleet.

- What we believed: a claim file checked by `/preflight` would serialise deploys.
- What was actually true: both outcomes happened within one hour on the same
  service. It WORKED once -- `live-game-line-projection` held refresh-worker, an
  acquire was refused, and no collision occurred, the first time all evening two
  sessions wanted one service and neither clobbered the other. It was IGNORED
  once -- a peer fired `129395cc` over a held claim at 23:09:54, because the
  claim only binds a session that has PULLED the tool and RUNS
  `/preflight --holder` before deploying.
- How we found out: held the claim, watched a peer deploy appear anyway, and
  aborted rather than firing into their build.
- The rule going forward: **treat the claim as a courtesy that makes collisions
  VISIBLE, never as a lock that makes them impossible.** Concretely: still cut
  from the service's CURRENT live SHA, still re-verify by content after landing,
  and never fire into an in-flight deploy even when you hold the claim -- holding
  a token is not a licence to cancel a peer's build. The durable fix remains one
  deployer per service; the claim only shortens the argument about who that is.
- Cost: none this time, because the abort was correct. The value was real: the
  same mechanism stopped ME taking a service while a peer was mid-measurement.

### 2026-08-15 — NEVER PIPE A COMMAND WHOSE EXIT CODE YOU DEPEND ON

- What we believed: `git cherry-pick X 2>&1 | tail -1 && next-step` is a tidy way
  to keep output short in a chained command.
- What was actually true: a pipeline's exit status is the LAST stage's, so
  `tail` returning 0 made a FAILED cherry-pick read as success and the `&&`
  chain continued. Compounded by `git worktree add` failing in the same command,
  which made `cd` fail silently, so every later step ran **in the shared repo
  working tree on local `main`** -- whose HEAD was another session's commit. The
  result was a branch pushed under my name containing THEIR commit, and a test
  run that measured their tree while reporting my change was green.
- How we found out: the pushed tip did not match the expected diff -- 54 files
  instead of 2 -- so the content, not the exit codes, exposed it.
- The rule going forward: **check `rc=$?` directly on any command whose failure
  should stop the chain, and assert the postcondition** -- the worktree exists,
  HEAD actually moved, the diff is the size you expect. Cheap asserts turn a
  silent wrong-tree operation into an immediate stop.
- Cost: a misleading branch pushed and deleted, a meaningless test run, and ~10
  minutes; no production impact, and the shared tree was verified undamaged.

### 2026-08-16 — THE HANDOFF THAT WORKED WAS A SCHEDULED TASK, NOT A MESSAGE

- What we believed: parallel sessions coordinate by messaging each other, and a
  session ending is a handoff problem to be solved with better handoff prose.
- What was actually true, measured across one evening: **every cross-session
  message arrived after the event it was meant to affect.** Holds landed after
  the deploys they meant to stop; a broadcast to eight idle sessions STALLED SIX
  of them; three lane-owning sessions ARCHIVED mid-coordination; and at least one
  session (`local_56dce69c`) sends messages while appearing in no roster listing,
  archived included, so it cannot be messaged at all. Meanwhile four SCHEDULED
  TASKS quietly did the thing messaging could not: each owns one open question,
  fires without any session being awake, and survives the session that created
  it. The claim file worked for the same reason -- it is state on disk, not a
  message in a queue.
- How we found out: listing scheduled tasks turned up two watches created by
  OTHER sessions for questions this session had been treating as unowned (the
  +/-4900 clamp, the settled CLV read).
- The rule going forward: **for anything that must outlive a session -- a
  measurement owed, a deploy window, a follow-up read -- write it to disk as a
  scheduled task or a claim, not into another session's inbox.** Reserve
  messages for things that are only useful if read within the minute, and expect
  even those to be late. When you need another session's STATE, read its
  transcript with `list_events`: it costs them nothing, cannot stall them, and
  returns more than a reply would.
- Cost: roughly a dozen messages sent for one unprompted reply, six stalled
  sessions, and a production regression that stayed live 45 minutes because the
  hold telling a peer to stop arrived after they had already deployed.

## 2026-08-15 — FORBIDDEN: never read `same_book_n=0` (or any joiner zero) as a data-quality verdict until the reader has been shown to SEE the data

`clv-without-settlement`'s next action said, in advance and in good faith: "If
`same_book_n` is still 0, the blocker is odds-history breadth, not the joiner."
Run as written on 2026-08-15 it returned `same_book_n=0, avg_clv_pct=None` for
all 8 sports, and that rule would have converted a blind instrument into a
finding about the odds market.

**The truth at that instant:** refresh-worker had **490 openings recorded for
that same date** (`[clv_opening_ledger] OPENINGS ... already=490`, 20 log lines
in 14h). `/api/ops/clv/report` runs on **web**; `load_openings` is a
`path.exists()` on a local file; web's disk held **0 bytes** of
`reports/intelligence/clv_openings/*.jsonl`. The endpoint returned `ok: true`
the whole time.

**Why this is its own rule and not just another instance of instrument
blindness:** the zero was PREDICTED IN ADVANCE and assigned a meaning in
advance. A pre-registered decision rule feels like rigour, and it is — but only
for the branch it anticipated. This one had no branch for "the reader is on the
wrong side of a disk boundary", so the unanticipated failure was silently
routed into the anticipated explanation. **A decision rule that maps every zero
onto a substantive cause is a rule with no null branch.**

**How to apply:**
- Before believing a zero, demand a NON-ZERO reading from the same instrument on
  some input. Here that took one call: the same endpoint for 2026-08-14, a date
  the lane itself measured at 150 openings, also returned 0. Two dates, both
  known non-empty, both 0 — the instrument, not the data.
- Read the SIBLING fields before the headline. `unresolved_reasons: {}` and
  `by_book_scope: {}` were empty in the very first payload. Under the breadth
  hypothesis they are necessarily NON-empty (that is what breadth failures look
  like). The refutation was already on screen.
- **Cross-service reads: name the service that runs the code and the service
  that owns the file, every time.** Deployed and reachable is not the same as
  able to read. `#208`'s lesson again: an allowlisted pattern PERMITS a
  transfer, it does not make one happen.
- A read-only report whose "no data" and "cannot see data" look identical is a
  defect in the report. Zero openings and 490 openings must not share a
  response shape.

**Standing until:** the join is run from a service that can read the ledger, or
the ledger is published where the endpoint can reach it. Until then
`same_book_n` from `/api/ops/clv/report` carries no information about breadth.

### 2026-08-15 — A BASELINE IS A MEASUREMENT, NOT A CONSTANT. Re-measure it before you judge anything against it

**The belief:** the number handed to me in the brief — "post-M1 baseline 23/52,
that is the number every change is judged against" — was a fact about the system.

**What was true.** Live production measured **25/52**, not 23/52. Two deploys had
landed in between (`7e334509`, `c774fe1a`), and one of them had moved `refusal`
**6/8 → 4/8**. The brief's per-class table was wrong in four of seven classes.

**Why it matters more than the arithmetic.** Had I trusted it, I would have
deployed onto a board that already carried someone else's regression, then
diffed against a number that never described the tree I was changing. `refusal`
would have read as 4/8 "after my change" against 6/8 "before", and I would have
reported — and believed — that I broke it. The stale baseline does not just
mis-score the work; **it silently reassigns another lane's regression to you**,
and there is no signal in the diff that says so.

**Why a stale baseline is especially dangerous in THIS repo.** Deployed SHAs move
several times an evening across parallel sessions, and `state.md` already records
that. A baseline written at 20:45Z on 08-14 and used at 03:2xZ on 08-15 spans an
unknown number of other people's deploys.

**The rule.** Before judging a change against a baseline, RE-RUN the baseline
against the currently-live commit, and record which commit it was measured on.
A baseline without a SHA attached is an anecdote. If re-running is impossible,
say the comparison is confounded rather than reporting the diff as attribution.

**The corollary that paid off here.** Also control for the DATA the measurement
ran on. ~13h of wall clock separated the two runs, which would normally void the
comparison; it survived only because the board was independently checked at both
instants and was identical (150 rows, wnba 18 / nfl 42 / mlb 90). **Check the
slate, or the diff is not attribution.** And where the data was ABSENT — soccer,
ncaab and nhl had zero rows both times — the passing cases prove ROUTING and
nothing else. Record that as unproven rather than banking it as coverage.

**Related:** `feedback_measure_same_instant`, `feedback_rate_not_count`,
`feedback_confirm_the_code_ran` (the code was verified to have run here:
`routed_sport: 'soccer'`, previously `None` on 52/52).

### 2026-08-15 — A JOB THAT ONLY FLUSHES ON COMPLETION CANNOT SURVIVE A SESSION BOUNDARY, AND I LAUNCHED TWO
- The rule going forward: **before launching a long job, ask what it writes if
  it is killed at the 90% mark.** If the answer is "nothing", that is a defect
  in the job, not a risk to accept — append per unit of work (per league, per
  day) so the run is resumable and partial results are still results. A
  progress-free, output-free job is indistinguishable from a hung one while it
  runs and from a job never launched after it dies.
- The second-order error, which is the more useful one: I let the *answer to a
  question the session needed* depend on a job the session could not outlive. A
  detached job is the right tool for work whose result the NEXT session can
  pick up; it is the wrong tool when the current session must reason about the
  output. Sequence it accordingly, or scope it down to something that finishes.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-15 — FORBIDDEN: never trust a CLEAR from `lane-guard.py`'s `_claims()` alone. It UNDER-reports, and that is the dangerous direction
- **The rule going forward.**
  1. **A CLEAR from `_claims()` is necessary, not sufficient.** Confirm every
     file you intend to edit by READING each OPEN lane's `Files:` block, and
     distinguish a claim from prose — "read-only dependency", "NOT this lane's
     files", and "Files: none claimed yet, deliberately" are all non-claims that
     look like hits to a grep.
  2. **Write your own `Files:` block as nested bullets, one path per `-` line.**
     That is the only format the parser handles, and it is what 7 of 8 lanes
     already use. A comma-continuation block silently leaves your work
     unguarded.
  3. Until the parser is fixed, **the guard's silence is not evidence.**
- *(evidence in `learnings_evidence.md`)*

### 2026-08-15 — A COMMITTED LEDGER FACT IS NOT A DURABLE ONE. Re-read it at archive time, or the file will quietly go back to the claim you refuted

Two ledger losses in one session, both silent, both found only by re-reading:

1. `fd23c6bc` wrote 36 measured lines into `state.md`'s Tier 5 section. Another
   session's housekeeping commit `7f7d8d88` ("archive the two sections that are
   not live state — 74KB → 64KB") dropped them. The section was left asserting
   **"No live GAME-LINE projection exists"** — precisely the claim those 36 lines
   had refuted with production evidence (`estimate_live` running 120 sims per
   live game, 9 bails/tick across 11 ticks against 9 Final / 5 Live).
2. An append to `lanes.md` vanished from a **clean working tree** — a concurrent
   session rewrote the file from a stale copy. `git status` showed nothing,
   because after the overwrite the worktree matched HEAD.

**Why the usual defences do not catch this.** The isolated-index discipline
protects the COMMIT. It says nothing about whether the content survives the next
session's edit of the same shared file. A checkpoint that ends "committed as
`<sha>`" is true and is not evidence the fact is still readable. And a
size-reducing collapse is the single most dangerous edit shape on these files:
it is authored by someone optimising for bytes, who has not read what the bytes
say, against a file whose whole purpose is to be read.

**The asymmetry that makes it expensive.** Losing an append leaves NO trace. But
`state.md`'s job is to hold the current truth, so a lost correction does not
degrade to silence — it **reverts to the superseded claim**, which then reads as
current and carries the ledger's authority. Loss and misinformation are the same
event here.

**How to apply.**
- At archive/checkpoint time, **grep the ledger for your own load-bearing strings
  and confirm they are still there.** Not `git log` — the file. A commit is proof
  you wrote it, never proof it is still readable.
- When restoring a dropped fact, restore the **current** version, not the one you
  originally committed. Mine had been re-scoped in between (`428fbb6e`); replaying
  the commit verbatim would have re-introduced a wrong artifact reference under a
  "restored" label — a correction that reintroduces an error is worse than the gap.
- Leave a note at the restore site naming the commit that dropped it, so the next
  collapse re-reads instead of repeating.
- **Never `cat >` a shared ledger file.** Append, or edit the specific lines.

### 2026-08-15 — I CONFIRMED A VALUE MY CHANGE DID NOT PRODUCE. A field with two sources verifies nothing until you know which one filled it

**The belief:** "K6 shipped — I checked production and `visuals.as_of` came back
`'2026-08-15'`."

**What was true.** The line is
`_evidence.get("as_of") or _snapshot_as_of or None`. The question I probed (B03,
a ranking question) had board evidence, so `as_of` was filled by the FIRST term —
the pre-existing evidence path. **My new fallback (`_snapshot_as_of`) never
executed.** The identical string would have come back from the OLD code. I read a
populated field, attributed it to my change, and called the item shipped.

The harness had been telling me otherwise the whole time: `as_of` populated
**28/52 before and 28/52 after — literally unchanged**. I explained that number
away with a second wrong claim (that the harness warns on the answer TEXT) rather
than treating "unchanged" as the refutation it was. The harness checks the FIELD
first (`if not as_of and not re.search(...)`).

**The rule.** When a field has FALLBACK SOURCES, observing it populated proves
nothing about which source filled it. Verify by picking an input where **every
other source is empty** — here, a question with no evidence (A04). That isolates
your term. Under isolation the fix was plainly inert: A04 returns `None` on
production and a real timestamp locally, on identical code.

**The trap underneath:** the local box took a snapshot read path carrying
top-level `freshness`; production takes one that does not. So the fix worked
perfectly on the machine I tested on and did nothing where it mattered — the
"fixture picks a cheaper path than production" failure I already have a rule for.
A local pass is not evidence for a code path whose INPUT SHAPE differs by
environment.

**Corollary — a null result deserves the same scrutiny as a positive one.** "24 →
24, unmoved" was the measurement that was right. I spent my effort explaining it
away instead of trusting it, because the single production probe had already
convinced me.

**Related:** `feedback_confirm_the_code_ran` (assert the BRANCH, not the
outcome), `feedback_gate_on_the_output_not_the_input`,
`feedback_presence_is_not_reachability`.

### 2026-08-15 — OVERTURNED: two locks with one symptom. `JOB_CAP_THROTTLED` is not the refresh run-lock, and the difference picks the remedy

- **What I believed and wrote into a findings file:** the mechanism starving MLB
  quote capture was `refresh_worker JOB_CAP_THROTTLED active=1 max=1`.
- **What is true:** there are TWO independent locks, and they co-occur because
  both sit downstream of one long-running job.
  | | what it is | where |
  |---|---|---|
  | refused every live-odds-worker tick | per-lane refresh-**run** lock: lane manifest non-terminal AND its pid still alive | `shared/ops_refresh.py:669` (`_assert_no_active_refresh_run`) |
  | `JOB_CAP_THROTTLED` | separate throttle in the worker job loop, `SYNDICATE_REFRESH_WORKER_MAX_ACTIVE_JOBS`, unset → default 1 | `scripts/run_refresh_worker.py:3496` |
- **Why it matters, and it is not pedantry:** the obvious remedy for a job cap is
  to raise it. That would **not** have fixed the capture starvation at all, and
  raising concurrent jobs on a 4 GiB worker in the middle of an OOM
  investigation (`#435`) is actively harmful. **A wrong mechanism produces a
  confident, plausible, harmful fix.**
- **How it was caught:** grepping for the literal log text before recommending
  anything. `JOB_CAP_THROTTLED` and `A refresh run is already active (pid=...)`
  live in different files with different owners.
- **The rule:** when two signals co-occur in one incident, find each one's
  EMITTER before naming either as the cause. Co-occurrence downstream of a
  common cause is the normal case, not the exception.
- Related: `ops_refresh.py:654-665` already records that this run-lock has a
  known false-positive mode — a lingering wrapper process past a terminal
  manifest state. Worth reading before anyone tries to fix the chain.

### 2026-08-15 — FORBIDDEN: never read a background-task wrapper's `exit code 0` as "the tests passed"

- **Measured twice in one session.** The background-task harness reported
  `completed (exit code 0)` for (a) a pytest run whose output contained `1 failed`
  and (b) a run truncated mid-progress with **no summary line at all**.
- Pytest itself exits non-zero on failure, so this is the wrapper's exit code,
  not pytest's. Reading it as a pass would have shipped "regression net green".
- **The rule: read the summary line (`N passed`, `N failed`). If there is no
  summary line, the run did not finish — it is not a pass and not a failure, it
  is no measurement.** Same family as `confirm_the_code_ran`: assert the thing
  you care about, never a proxy that a wrapper is free to fake.

### 2026-08-15 — FORBIDDEN: never judge a pinned deploy by ANCESTRY alone. Patch-id is the test.
- The rule going forward: **on a pinned-deploy service, ancestry is necessary
  evidence of safety but its ABSENCE is not evidence of danger.** A false
  ancestry result must be escalated to a patch-id + content diff before either
  deploying or aborting. The same trap in mirror image is already recorded:
  `deactivated` means superseded, not reverted.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-15 — FORBIDDEN: never wake many idle sessions at once. It stalls them.
- The rule going forward: **read the other session's transcript instead of
  asking it.** `list_events` costs nothing on their side, returns more than a
  reply would, and cannot stall them. If a session must be messaged, do it ONE
  at a time and keep it short. Recovery is just delivering a new turn —
  "continue" is enough — but only the owner can spend it.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-15 — A BASELINE QUOTED IN PROSE MAY CORRESPOND TO NO RUN ON DISK
- The rule going forward: **before handing anyone a baseline, open the file and
  check `total` matches the suite size.** A number that has been repeated
  between sessions is not thereby measured — repetition is not evidence, and a
  baseline is the one input that silently invalidates every comparison built on
  it.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-15 — A CLASS NAME IS NOT A SURFACE, and `querySelector` turned that into two wrong plan items
- **The rule going forward:** on a SHARED stylesheet, a per-class measurement
  must enumerate every matching element and report a class rendering at two
  sizes as *conflated*, never collapse it to its first hit. The whole point of a
  shared stylesheet is that one class renders in more than one place. The probe
  now does this and flags `type conflated:` per sport.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-15 — THE INSTRUMENT THAT DROPPED A MISSING KEY, AND THE CORRECTION IT HANDED ME MID-FIX
- **The rule going forward:** two rules, and they are separable. (1) A value
  meaning *"not measured"* — missing element, dropped key, error page,
  first-of-many match, render not yet happened — must never share a code path
  with *"fine"*. (2) **Never read MLB's DOM on a fixed delay.** Every other
  sport is server-rendered and stable at load; MLB is not.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-15 — ON A CONTENDED LEDGER, NEITHER COPY IS AUTHORITATIVE, AND A WHOLE-FILE COMMIT PICKS A WINNER SILENTLY
- **The rule going forward:** for a file many sessions append to, **diff for
  deletions immediately before the commit, and read each one.** A file where
  both copies contain something the other lacks cannot be resolved by choosing a
  base — splice your own block onto the freshest copy and leave every other line
  untouched. If you do clobber someone, say so and tell them it is a
  reconstruction, not their text.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-15 — A FIELD MOVED INTO AN UNCONDITIONAL LOOP LOSES THE CONDITION ITS NEIGHBOURS WERE GIVEN

`UniversalCandidate.to_dict` writes the contract's normalised values back onto
the candidate payload. On 2026-07-28 (`1f47b2d6`, "Fix candidate field
corruption") `odds` was found flattening the display text `"+124"` to the float
`124.0` on every candidate, and was given a condition plus an eleven-line
comment stating the rule: **the normalised number is for maths, the payload slot
is the producer's display text, do not overwrite it.**

On 2026-08-06 `1f6c27b9` added `line` — a second numeric field — to the
`for field_name in (...)` loop **twelve lines below that comment**. The loop
writes unconditionally. So `line` was flattened from `"4.5"` to `4.5` platform-
wide, and the identical defect shipped nine days after its own fix.

**Why it survived nine days.** Nothing tested the rule at the contract layer.
The only red was `test_intelligence.py::...mlb_top_props_artifact...`, an MLB
blueprint test three layers away asserting `line == "4.5"` — read as "a stale
MLB test", not as "the contract is corrupting a field". The failure it actually
predicts: the board's `displayLine()` does a bare `String(line)`, so a JSON
`2.0` renders as **`2`** and the half-point precision the column exists to carry
is gone on every whole-numbered line.

**How to apply.**
- A loop that writes a list of field names back onto a payload is a place where
  per-field conditions go to die. Before adding a name to one, check whether any
  neighbour was pulled OUT of it, and why — the comment explaining the rule will
  be attached to the field that escaped, not to the loop.
- The condition to use is "is the slot already carrying this value in the
  producer's own form", not "is the slot truthy": `"-"` is truthy and is not a
  value. `_parse_float(payload.get(k)) is None` says it exactly for a number.
- A contract that normalises types needs its tests AT the contract, not only at
  a consumer. A consumer test names the wrong defendant.
## 2026-08-15 — REFUTED: "if `same_book_n` is 0, the blocker is odds-history breadth". It was the READER, and the same zero had two candidate causes nobody separated

`clv-without-settlement` pre-registered that rule. Run on 2026-08-15 it returned
`same_book_n=0` for all 8 sports. Applying the rule would have written "breadth"
into the ledger as a measured cause.

**What actually happened:** `/api/ops/clv/report` runs on **web**;
`load_openings` is a `path.exists()` on a local file; refresh-worker was
publishing that file and web was answering **`HTTP Error 403: FORBIDDEN`**,
because web's `HOT_ARTIFACT_PATTERNS` had no `clv_openings` entry while the
worker's did. Shipping one allowlist line to web moved
`same_book_n` **0 → 144** and `openings` **0 → 520**, with **no change to odds
history at all**. Breadth was never the blocker for that number.

**The generalisable trap — a zero with two sufficient causes.** "No same-book
pairs" is produced BOTH by a thin market AND by an empty input. The rule named
one and never checked the other, so the unanticipated cause was silently routed
into the anticipated explanation. **Before attributing a zero, enumerate every
cause sufficient to produce it, then discriminate.** Here one call did it: the
same endpoint on 2026-08-14, a date with 150 known openings, also returned 0.

**Cross-service version skew is a first-class failure mode here, and it is
invisible from either side alone.** Sender and receiver each validate against
their OWN copy of a shared constant. The worker logged that it tried; the web
logged nothing a caller could see; the endpoint answered `ok: true`. Diff the
constant between the two DEPLOYED commits — not against `main`, which was
*also* missing it (blob `aff59302` on both web and main, `ee94fe6b` on the
worker). **A shared constant that only one service has is a skew, and `main` is
not evidence of what either service runs.**

**And the finding that came out the other side, which is the reason this
mattered:** with the reader fixed, the honest same-book CLV is **-0.07% at a
27.1% beat-close rate (n=144)**, while the biased scopes read **+2.73% at 82.5%
(n=143)**. The selection effect is real and large enough to invert the sign.
**Never quote a book-agnostic or different-book CLV as CLV.**

**How to apply:**
- A read-only report whose "no data" and "cannot see data" are the same response
  is a defect in the report. `openings: 0` and `openings: 520` must not both
  arrive as `ok: true` with nothing distinguishing them.
- Verify a publish PATH end to end by its log pair (`PUBLISH_OK` /
  `PUBLISH_FAILED`) on the SENDER, not by the presence of a pattern in a file.
- Timing is part of a CLV reading: `-0.0711` was taken at 14:38 CDT, before
  first pitch, so most "closes" were not closes. State the clock or the number
  is not interpretable.

### 2026-08-15 — MY SUCCESS CRITERION CONTAINED A TERM THE BASELINE ALREADY SATISFIED, AND MY INSTRUMENT RULE INVERTED BECAUSE OF MY OWN FIX

Two errors in one verification design, both caught only by taking a **pre-deploy
baseline**, both of which would have produced a confident wrong verdict.

**1. A vacuous conjunct.** I wrote the pass condition as *"`source: live_mc` AND
a non-null `modelHomeWinProb`"*. Measured at baseline: **60 of 60 rows already
carried a non-null `modelHomeWinProb`** — `_build_game_lens` stamps one on the
`first1/3/5` lanes from `_live_margin_win_prob` over a segment interpolation.

The galling part: I had *already* identified this trap. The code deliberately
discriminates on `source == "live_mc"` **because** `modelHomeWinProb` does not
separate the two, there is a test named for it, and the commit message explains
it. I then wrote the useless half into the criterion anyway. **Knowing a field is
non-discriminating in the CODE does not stop you putting it in the CRITERION.**

**2. An instrument rule that my own change inverted.** I wrote, repeatedly and in
`deploys.md`, *"read the published artifact, NEVER `/mlb/api/live-lens`, it is
structurally blind."* True when written — it was blind precisely because web's
rebuild DESTROYED the lens. **Drop 2 fixed exactly that, so the moment it
deployed, the forbidden instrument became the correct one and the recommended one
became useless** — the published artifact is the slim shape and has no `gameLens`
key at all, so it reads 0 forever.

**How to apply.**
- **Take the baseline BEFORE the deploy, and read every term of your criterion
  against it.** Any term already satisfied at baseline is decoration; delete it.
  A criterion is only worth what its *discriminating* terms are worth.
- **After a fix that changes how data flows, re-derive which instrument is
  valid.** An instrument rule is a claim about the system's CURRENT plumbing. A
  fix to the plumbing can silently promote a blind instrument to a good one, or
  demote a good one — and the rule will still be sitting in the ledger, phrased
  as timeless.
- **A "never use X" rule inherited from before your change is a hypothesis, not a
  constraint.** Check whether the thing that made X blind is the thing you fixed.

### 2026-08-15 - A PINNED DEPLOY IS NOT ON main's LINEAGE, SO ANCESTRY ANSWERS THE WRONG QUESTION
- **The rule going forward:** **test deployment by CONTENT.** Compare
  `git rev-parse <deploy>:<path>` against your own commit's blob for every file
  you shipped. Ancestry is a cheap positive signal (YES means yes) but its NO is
  uninformative on a tree where deploys are pinned. This is the second form of
  the trap already in state.md ("web runs a deploy branch, not main").
- *(evidence in `learnings_evidence.md`)*

### 2026-08-15 - A FIXED `GIT_INDEX_FILE` NAME COLLIDES ACROSS SESSIONS, AND A FAILED read-tree LEAVES AN EMPTY INDEX THAT STAGES THE WHOLE REPO AS DELETIONS
- **The rule going forward:** scope the index file to the SESSION
  (`/c/tmp/idx-<session-id>-<purpose>`), remove both it and its `.lock` first,
  and **assert the index is non-empty after `read-tree`**
  (`git ls-files --cached | wc -l` > 100) before staging anything. The empty
  index is the dangerous state precisely because it looks like a successful
  setup - same family as "a value meaning not-measured must not share a path
  with fine".
- *(evidence in `learnings_evidence.md`)*

### 2026-08-15 — OVERTURNED: two throttles with the same symptom, and I named the wrong one as the mechanism

- **What I believed and wrote down:** the MLB quote-capture starvation was caused
  by `JOB_CAP_THROTTLED active=1 max=1` (`scripts/run_refresh_worker.py:3496`,
  `SYNDICATE_REFRESH_WORKER_MAX_ACTIVE_JOBS`, unset → default 1). I published
  that in `tier5_quote_to_ui_WINDOW2` before tracing it.
- **What is true:** the lock that refused all 17 ticks is a *different* one — the
  per-lane refresh-run lock at `shared/ops_refresh.py:669`
  (`_assert_no_active_refresh_run`), raised when the lane manifest is
  non-terminal and its recorded pid is still alive. `JOB_CAP_THROTTLED` was
  co-occurring noise. Both are downstream of one long-running job, which is
  exactly why they were easy to conflate.
- **Why it mattered, and this is the whole point:** the two point at OPPOSITE
  remedies. "Raise `MAX_ACTIVE_JOBS`" follows from the wrong one — and that
  would have doubled concurrent memory on a worker sitting at **91% of 4 GiB
  with 7 confirmed `oomKilled` events the same morning.** A misattributed
  mechanism is not a cosmetic error; it generates a dangerous fix.
- **The rule:** when two throttles can produce the same symptom, find the code
  that emits the EXACT string you observed before naming a mechanism. Symptom
  co-occurrence is not identification. `grep` the literal message, not the
  concept.
- Related and already recorded: `absent signal is about the emitter` — the same
  session, I counted `PREGAME_RELAUNCH_COOLDOWN_SKIPPED` on refresh-worker and
  got 0, which was meaningless because live-odds-worker emits it. Both errors
  are the same shape: **reasoning about a log line without locating its emitter.**

### 2026-08-15 — RULE: deploy to where the artifact is BUILT, not where it is served

- **The near-miss:** the NFL live-edge fix was about to go to `web`, because the
  defect was observed on `/api/board/layer2-shortlist`, which web serves. That
  would have been an **inert deploy**. The shortlist is a plain artifact read;
  the edges are baked in at build time by
  `book_grid_artifact.py:221 → board_enrichment.attach_projections`, which runs
  on **refresh-worker**. Deployed to the worker, the fix measured 5 → 0 live NFL
  edges on the first build.
- **The rule:** for any artifact-backed surface, the service that SERVES the
  symptom is usually not the service that must receive the fix. Trace
  symptom → artifact → builder, and deploy to the builder. Then check whether
  the serving service has its own compute path for the same data — here web's
  `intelligence.py:2383` did, so it needed the commit too, as insurance.
- **This is the deploy-time twin of `presence is not reachability`.** Presence in
  the repo, presence on `main`, and presence on the service that shows the bug
  are three different things, and only the third-from-last is usually checked.

### 2026-08-15 — FORBIDDEN: never gate a DEPLOY with a cross-session message. It always arrives late.
- The rule going forward: **deploy serialisation needs a LOCK, not an
  announcement.** A message is advisory and asynchronous; a deploy is immediate
  and destructive to whatever is building. Until a real mutex exists (a claim
  file checked by the deploy path, or one session designated as the only one
  that may POST), assume any web deploy may be cancelled by a peer at any moment
  — so **re-read the live SHA after your deploy reports live, and verify your
  own commit is present by patch-id** rather than trusting that it landed.
  `3ba1c2cf` was cancelled at 19:20 and was still absent from live at 20:22.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-15 — OVERTURNED: p50 is the wrong statistic to set an alarm floor from, and my own test caught it

- **What I believed:** having measured each quote feed's cadence, ~3x the p50
  gap was a principled per-sport stale threshold. It is defensible-sounding and
  I wrote the constants that way.
- **What refuted it, immediately:** `test_healthy_pregame_gap_does_not_false_alarm`,
  which I had written HOURS EARLIER, went red. It pins the real 123-min MLB
  pregame gap (09:06->11:07Z, measured). MLB's p50 is 31 min, so 3x p50 = 93 min
  fires on a gap that is known-healthy.
- **The general rule:** p50 describes the middle; an alarm floor lives in the
  TAIL. These feeds have long quiet tails (overnight, between-slate), so a
  threshold must clear the largest HEALTHY gap, not a multiple of the typical
  one. **p50 is the right statistic for comparing feeds and the wrong one for
  setting a floor.**
- **Why the test existed to catch it:** it was written to make a tradeoff
  visible rather than to assert a comfortable answer — "if someone lowers the
  default, this goes red and the tradeoff is visible instead of silent." The
  someone was me, four hours later. A test that pins a MEASURED healthy extreme
  is worth more than one that pins the current behaviour.
- **Second-order correction it forced:** the `0c65a832` deploy note credits the
  alarm with "catching soccer STALE at 340.9 min". Soccer's p50 is 173 min, so
  the old 180 min global flagged that feed on roughly HALF of normal operation.
  The catch was substantially a threshold artifact. **A first-read success is
  exactly when to check the false-positive rate**, because that is the reading
  most likely to be mistaken for validation.
- **Still unsolved, and named so nobody thinks per-sport finished it:** an
  age-only alarm cannot distinguish "quiet" from "broken". Clearing the
  overnight tails is what keeps all four thresholds in hours rather than
  minutes. The real fix gates on whether the sport has games scheduled.

### 2026-08-15 — A FALLBACK ARGUMENT IS A REQUEST, NOT A GUARANTEE. `_safe_text(x, None)` RETURNS `""`, 43 TIMES OVER

`_safe_text(value, fallback="-", *fallbacks)` ends `return ""`. Every return
path is a `str`. So `_safe_text(x, None)` **cannot** produce `None` — it
produces `""`, and the call site reads as though it asked for and received
`None`.

`_build_prop_dashboard_row` (home.py) used it for `market_key`, directly under a
comment saying "the canonical key WHERE THE SOURCE HAS ONE". A source with none
shipped `market_key: ""`. Downstream,
`_attach_intelligence_response_aliases` tested `if payload.get("market_key") is
None` before deriving one, `""` is not `None`, so the derivation never ran —
while `market_focuses` on the same row already held the right answer. **A blank
took the permissive branch and the row went out claiming an empty key.**

**43 other `_safe_text(..., None)` call sites exist** (`grep "_safe_text(" |
grep ", *None)"`). The count is the point: this is not one slip, it is a helper
whose signature invites a value it cannot return.

**How to apply.**
- Before passing a default to a text helper, read its LAST line. If every return
  is a `str`, `None` is not reachable and `... or None` is what you meant.
- The two halves are separate bugs and both need fixing. A producer emitting
  `""` for absent is one; a consumer testing `is None` for absence is the other.
  Fixing only the consumer leaves the next producer free to reintroduce it, and
  fixing only the producer leaves the next `""` from anywhere else unhandled.
- **Do not sweep the other 42 on this reasoning alone.** Consumer semantics
  differ per field, and `player_name: null` cards were a defect the same
  function was fixed for once already — an "obviously correct" blanket change
  there resurrects it. Filed as `#438a`.
- Related, same day, same shape one layer over: `line` flattened by an
  unconditional write-back loop. Both are "unknown rendered as a value that
  reads like an answer".

### 2026-08-15 — THE SHARED-INDEX REPAIR MUST RUN IN A SHELL WITH NO `GIT_INDEX_FILE`, OR IT REPAIRS THE WRONG INDEX

`learnings.md` already says: after an isolated-index commit, run
`git restore --staged <paths>` or the shared index is left staging a deletion of
what you just committed. That rule is right and I followed it. **It is not
enough, and the way it fails is silent.**

`GIT_INDEX_FILE` is exported for the whole shell. Chaining the repair onto the
end of the same Bash call —

    export GIT_INDEX_FILE=C:/tmp/idx-x && git read-tree HEAD && git add -- P \
      && git commit ... ; git restore --staged P     # <-- STILL isolated

— points `restore` at the **isolated** index. It succeeds, prints nothing
alarming, and the shared index keeps the pre-commit blob. Measured today: my
`#438` commit added 34 lines to `todo_closed.md`, the chained repair "ran", and
the shared index sat staging **0 insertions / 34 deletions** of exactly that
commit, with `HEAD == worktree` at 2092 lines. Two earlier commits the same
session were repaired correctly — because their repair happened to be a
SEPARATE Bash call, which is a new shell with no export. **The habit worked by
accident and failed the moment I tidied it into one call.**

**How to apply.**
- Run the repair as its own Bash call, and **prove the shell is clean** first:
  `echo "${GIT_INDEX_FILE:-<unset>}"` must print `<unset>`.
- Then verify the outcome rather than the command's exit code:
  `git diff --cached --numstat | awk '$1==0 && $2>0'` must print nothing.
  A `git restore` that targeted the wrong index still exits 0.
- Generalises past git: **any repair chained into the shell that set the
  hazardous variable inherits it.** The verification has to read the shared
  state, not the command's return.

### 2026-08-15 - A LABEL-MATCHED LOOKUP IS NOT A SUBSTITUTE FOR THE FIELD, AND ITS FAILURE IS SILENT
- **The rule going forward:** when a value can be read from a FIELD, read the
  field; a lookup keyed on a human-facing label is a guess about another
  team's vocabulary and it fails silently, producing a placeholder that looks
  exactly like genuinely-absent data. If a label lookup must exist, it is the
  fallback, never the primary. And: **a suppression gate doing its job is not
  evidence its input is healthy** - the gate was right, its input was starved,
  and the visible symptom was identical either way.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-15 - ENUMERATE EVERY SPORT THAT REACHES A CHANGED BRANCH *BEFORE* DEPLOYING
- **The rule going forward:** when changing a shared contract, enumerate the
  branch predicate across **every** sport that calls it and write the counts
  down, before the deploy. "The two I thought of" is not an enumeration. The
  cheap form is one loop over each sport's served payload testing the
  predicate - it took under a minute afterwards and would have cost the same
  before.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-15 — I PROPOSED ALLOWLISTING A READ PATH WITHOUT CHECKING THE WRITE PATH. It would have 404'd forever

Near-miss, caught one step before shipping. The tally I needed
(`meta["liveMcSources"]`) lives in
`reports/live_lens_loop/latest_live_lens_tick.json`.
`/api/ops/artifacts/stream` returned **403 not-allowlisted**, so the fix looked
obvious and one line: add the path to the allowlist. I proposed exactly that,
and was told to do it.

**It would have been inert.** `_KEYVALUE_EXCLUDED_PATH_MARKERS` is only
`("migration_runs/",)`, so on any service with the keyvalue backend — all three —
that path is keyvalue-backed, and `write_json_file` writes to Redis and
**returns before any disk write**. `/api/ops/artifacts/stream` gates on
`target.is_file()`. The file exists on no disk. Allowlisting turns a 403 into a
404 and nothing else.

**Why the 403 was so misleading.** It is a *permission-shaped* error for an
*existence-shaped* problem. "This path is not allowed" invites "then allow it" —
and the allowlist check runs BEFORE the file check, so the more informative
error is unreachable while the path is unlisted. The endpoint cannot tell you
the thing it already knows.

**The general shape: an allowlist governs the READ path; whether the bytes exist
is a property of the WRITE path.** Different code, usually different files,
often different services. A 403 tells you nothing about the second.

**How to apply.**
- Before exposing any path, **find its writer** and confirm the bytes land where
  the reader looks. Here: `write_json_file` → `_keyvalue_backed()` → the
  exclusion tuple. Three greps, versus a deploy that proves nothing.
- **Keyvalue-backed and disk-backed are different worlds here and the path
  string looks identical in both.** `reports/**` is keyvalue unless excluded;
  `data/**` is disk. Reading one with the other's API returns "missing", never
  "wrong backend".
- Prefer a route using `read_json_file` (backend-aware) over widening the
  artifact allowlist whenever the payload is *state* rather than a data artifact.
- Pin the reasoning in a test. `TestTheAllowlistFixWouldHaveBeenInert` asserts
  the exclusion tuple and the backing, so if the path ever becomes disk-backed
  the cheaper fix surfaces loudly instead of never.

### 2026-08-15 — A HOOK THAT BLOCKS A `Bash` CALL DISCARDS EVERY SIDE EFFECT IN IT, INCLUDING THE HEREDOCS

Compound cost, twice in one checkpoint. I wrote ledger prose with
`cat >> file <<'EOF'` and the commit in the SAME `Bash` call. `commit-guard`
blocked the call. **Nothing in it ran** — not the append, not the `cat > $MSG`
that wrote the commit message.

Two failures followed, and neither pointed at the cause:
1. Every retry printed "lost race" because my loop had `2>/dev/null` on the
   commit; the real error was `fatal: could not read log file ... No such file`.
   **An error handler that assumes one failure mode reports that mode for all of
   them.**
2. The learnings entry was silently absent. The *next* commit still showed
   `learnings.md | 50 +++++`, because another session's edits were sitting in the
   worktree — **so the stat line looked like my content landing and was somebody
   else's.** I only caught it by grepping HEAD for my own string at checkpoint.

**How to apply.**
- **Never put a file write and a guarded git operation in one `Bash` call.**
  Write the content, verify it, then commit in a separate call.
- **Do not suppress stderr on a commit inside a retry loop.** Print it, and
  distinguish "guard blocked", "missing message file", and "index race".
- **A `--stat` line is not proof your content committed** on a shared worktree.
  Grep HEAD for a string only you wrote. That check is the entire reason this
  was caught rather than shipped as a checkpoint that silently lost its lesson.

### 2026-08-15 - I APPLIED "ONE SAMPLE OF A MOVING QUANTITY" TO PRODUCTION AND NOT TO MY OWN MEASUREMENT
- **The rule going forward:** I already hold this rule for production
  quantities (`learnings.md`, three wrong root causes in one session from a
  single sample). It applies with equal force to a measurement I take MYSELF to
  explain something. Before writing "X explains Y", take the reading twice, or
  measure the whole population once - here, ten cards against their content
  counts settled in one pass what two timed samples could not.
- **Second-order rule, and the useful one:** when a metric cannot separate the
  thing you care about (layout) from a confound (content volume), report the
  confound alongside it rather than refining the metric. `content varies 20-57
  pairs/card` next to a 1583px spread is interpretable; the spread alone is
  not, and no amount of grouping was going to make it so.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-15 — a mid-ramp reading is not a window reading; I called a 446MB difference "noise"
- **The rule going forward:** a peak is only comparable across windows that
  contain the same WORK, not the same clock span. Before comparing peaks, check
  that the expensive stage has actually run in both — otherwise the comparison
  is of two warm-ups. State the window's work content, not just its start and
  end times.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-15 — verify a deployed fix by CONTENT across every SHA that carried it

The `#435` result rests on the fix being live for the whole window, and it was
carried by THREE different deploys from two sessions: `c67f7373` (mine, 18:11),
`dca39fad` (20:00), `0fa44322` (21:31). Attribution would have been worthless
without confirming each one contained the change.

Ancestry alone is not sufficient in this repo — `state.md` already records a live
SHA that was not an ancestor of `main`. Both checks together are:

    git merge-base --is-ancestor <fix-sha> <live-sha>
    git grep -c "<distinctive token>" <live-sha> -- <path>

Use `MSYS_NO_PATHCONV=1` on Windows or git mangles `rev:path` into a filename.

### 2026-08-15 — AN OCCURRENCE COUNT IS NOT A ROW COUNT, and I published three numbers that could be read as either
- **The rule going forward.** When counting anything extracted by walking a
  nested payload, **report the occurrence count and the distinct-entity count as
  separate, explicitly-named fields.** Never publish one scalar that could be
  read as either. If deduping, the key must include entity identity — deduping
  on value alone collapses two genuinely different entities that share a value,
  which UNDER-reports and is the more dangerous direction.
- **Second-order, and worth keeping:** the fix required identity to flow down
  the walk to the node holding the number. Identity is safe to inherit;
  **the numbers are not** — inheriting a probability downward would pair it with
  an unrelated nested price and manufacture a finding. That asymmetry is now
  pinned by a test that fails if someone "simplifies" it.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-15 — A PINNED-DEPLOY SERVICE SILENTLY REVERTS PEERS. VERIFY YOUR COMMIT AFTER IT GOES LIVE.
- The rule going forward: **on a service whose deploys are pinned cherry-picks,
  "live" is a lease, not a fact.** Every session cutting from "the current live
  SHA" is cutting from a moving target, so the last writer wins and the loser is
  never told. Re-verify your change by content minutes AFTER it lands, not just
  at the moment it lands — and when a peer is active on the same service,
  expect to re-deploy. The durable fix is one deployer per service, or trains,
  not per-lane deploys.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-15 — Render's git mirror is PER SERVICE and only refreshes at build time
- The rule going forward: **"route one" — warm the mirror first.** Deploy the
  service's own current live commit (a no-op in code), which forces a fetch,
  then deploy the target. Measured: the same sha that 404'd three times fired
  41 seconds after the warm deploy landed. Cost is two restarts, so take both
  inside detected lulls. This has probably been silently blocking worker deploys
  from fresh branches for some time.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-15 - `wait_for_selector` PROVES ATTACHMENT, NOT COMPLETION, AND I HAD ALREADY "FIXED" THIS ONCE
- **The rule going forward:** for a page that renders progressively, wait for
  the DOM to STOP CHANGING -- poll a cheap fingerprint until it is stable
  across two consecutive samples, cap it, and FAIL if it never stabilises. A
  render still growing when you measure it makes every figure on that row
  provisional, so it is a failure, not a footnote. And the meta-rule: "I fixed
  the timing bug" is a claim about a threshold, and the next threshold is
  usually also wrong. Verify by watching the quantity settle, not by getting a
  plausible number once.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-15 — TWO READS INSIDE ONE WARM-UP WINDOW ARE ONE READ. I declared a working fix dead

The worst call I made this session, and it survived into three ledger files
before a later reading overturned it.

live-odds-worker landed the fix at **20:56:07Z**. I measured `/mlb/api/live-lens`
at ~20:59 and ~21:04, got `live_mc=0` both times, and wrote **"a clean negative
result — the fix is correct and was not the binding constraint."** At 21:49,
with no further change from me, the same endpoint read `live_mc=6`, matching the
worker's own tally exactly. **The fix had always worked. It had not been given a
tick to run.**

**The reasoning error, precisely.** I treated two samples as independent evidence
because the *system* changed between them — the slate moved, live 4→3, final
1→2. That proves the reads were independent **of each other**. It says nothing
about whether they were independent **of the transient I was sitting inside**.
Both were drawn from the same restart warm-up, so they are one observation
repeated, and repeating an observation inside a transient increases confidence
without increasing information.

**I had already written the guard and then ignored it.** My own words minutes
earlier: *"the worker needs a tick or two after restart to rebuild the snapshot,
which is why there are two passes — I'd treat a single zero as inconclusive."*
Then a *double* zero read as conclusive, purely because there were two of them.
**A stated caveat does not discharge itself by being stated. Two of an
inconclusive reading is not a conclusive one.**

**Why it was expensive.** A false negative on a working fix is worse than no
measurement: it sends the next session hunting a defect that does not exist, and
it discredits a change that should have been banked. I had already spent the
deploy cost — including killing another lane's soccer run — and then threw the
result away by reading it too early.

**How to apply.**
- **After any restart, deploy, or cache flush, establish WHEN the system is
  warm before treating any reading as evidence.** For a loop, that is at least
  one full tick observed to have completed — not a guessed sleep.
- **Prefer a producer-side counter to a served-side one for the first read.**
  The tally that settled this (`liveMcSources`) is stamped by the loop itself,
  so it cannot be read before the work exists. A serving endpoint happily
  returns a stale-but-valid payload and looks like an answer.
- **State the warm-up window as a timestamp in the ledger row**, so a later
  reader can see whether a null result fell inside it. My rows said "measured
  20:56 and ~21:04" without saying the worker restarted at 20:56:07 — the two
  facts were in different files.
- **A negative result taken near a deploy is provisional until re-read cold.**
  Re-read before writing it into `state.md`; that file is where wrong facts do
  the most damage.

### 2026-08-15 - A UNIT CHANGE CANNOT FIX A FIT WHEN THE UNITS ARE PROPORTIONAL, AND I ALMOST BUILT IT ANYWAY
- **The rule going forward:** before changing the unit of a regression, ask
  whether the new unit is an affine function of the old one. If it is, the fit
  is identical and the problem is elsewhere — in the model's form, the grouping,
  or the sample size. This generalises: re-expressing a variable never improves
  a linear fit, so "use a better unit" is only ever a fix when the relationship
  to the outcome changes SHAPE.
- **Second finding, from the same session:** the deeper problem was sample
  size and slate churn, not units. n=3 groups (2 fitted parameters, 1 degree of
  freedom) produced fit ratios of 0.59 and 1.29 while an n=9 group on the same
  page produced 0.09. Four readings of the metric across one evening went
  reliable -> unreliable -> unreliable -> unfittable. **Tuning a model against a
  target that moves every 20 minutes is not measurement.** I stopped and
  reported the negative result.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-15 — FORBIDDEN: never deploy a fix without first reading WHICH SERVICE runs the code it changes. The env decides, not the repo.

One commit carried two files. `live_projection_join.py` runs during the board
build on **refresh-worker**; `cards.py`'s live-prop emitter runs inside
`live_lens_loop`, and `MLB_ENABLE_LIVE_LENS_LOOP` is **false on refresh-worker
and true on live-odds-worker**. I shipped both to refresh-worker, wrote one
predicate for each half, and **the coverage predicate could not have been
satisfied by the service I deployed to.** The probability half passed; the
coverage half was inert and read as a failed fix.

**Nothing in the code says where it runs.** Both workers import
`start_live_lens_loop`; only the env var separates them, and it is per-sport
(`MLB_ENABLE_LIVE_LENS_LOOP`), not the service-level
`SYNDICATE_ENABLE_LIVE_LENS_LOOP` which is `true` on both. Reading the imports
would have told me the opposite of the truth.

**How to apply:** before writing a deploy predicate, resolve the owning service
for EACH changed file — `render.yaml` startCommand for the entrypoint, then the
env vars on every candidate service for the gate. Then state the predicate as
"on service X". A predicate that does not name a service is not falsifiable.
Same family as [[which-service-runs-the-code]] and the `#414`-inert finding.

### 2026-08-15 — FORBIDDEN: a scratch index seeded with `git read-tree HEAD` snapshots the WHOLE TREE, and `git diff --cached --numstat` cannot see it go stale

The isolated-`GIT_INDEX_FILE` recipe is correct and I still lost 35 lines with
it. `git read-tree HEAD` snapshots **every path in the repo**, not just the ones
being staged. HEAD advanced during staging (six live sessions), another session
had committed 35 lines to `.syndicate/deploys.md` in that window, and the commit
wrote them back out as a deletion — in a file never opened, never named in a
pathspec, and absent from every diff I ran.

**`git diff --cached --numstat` read perfectly clean: 4 deletions, all mine, all
predicted.** It compares the index to the HEAD it was SEEDED FROM, not the HEAD
the commit will land on. It is blind to this by construction. This is the same
instrument-blindness family as the rest of this file: a healthy reading produced
by something unrelated to what is being measured.

Recovery was free (`git show HEAD~1:<file>`; the working tree never lost them)
and was committed as its own repair, `6da01dd3`, rather than amended away.

**Second half, same incident:** after that commit the SHARED index held a
complete revert of it — my four files at `3/95`, `1/46`, `0/19`, `24/85`, plus a
**deletion of a new test file while it sat on disk**. `commit-guard.py` caught
the deletion. `git reset HEAD -- <only your paths>` disarms it index-only and
leaves every other session's staged work intact.

**How to apply:**
- Re-read `git rev-parse HEAD` immediately before `git commit` and ABORT if it
  moved since `read-tree`. **Git's own ref lock is the real backstop** — a later
  commit this session failed with `cannot lock ref 'HEAD': is at X but expected
  Y`, which is this exact race refusing instead of silently reverting.
- After ANY scratch-index commit: `git reset HEAD -- <your paths>`, then confirm
  `git diff --cached --diff-filter=D --name-only` is empty.
- `git show --stat HEAD` right after committing. **A file you never touched
  appearing in the list is the signature.**
- Extract hunks in BYTES, never text mode: cp1252 mojibaked every UTF-8 em-dash
  inside a patch, which then applied cleanly and corrupted 8 lines of `lanes.md`.
  Select hunks by a content MARKER, not by `@@` line numbers — those renumber
  under an isolated index and `replace(..., 1)` will silently hit the wrong one
  (a mutation test read green for exactly that reason and was redone, not banked).

### 2026-08-15 — A TIMESTAMP WHERE A SIGNAL STOPS IS NOT WHERE THE FAULT IS

- **What I believed:** soccer's quote feed stopped at 13:47:17Z, so something
  happened at 13:47:17Z. I wrote four hypotheses, all aimed at that instant, and
  the user reasonably asked me to investigate it.
- **What is true:** 13:47:17 is where the **10:21 autorun's run finished
  writing** — a successful run ending normally. The fault is at **14:22:29**,
  the next scheduled attempt, refused by a lock. Nothing happened at 13:47.
- **The rule:** for a POLLED producer, the last-output timestamp marks the end of
  the last SUCCESS, not the onset of failure. The fault lives at the next
  scheduled attempt. Before investigating the stop time, find the producer's
  cadence and look at the first attempt AFTER it — `02:14 / 06:17 / 10:21 /
  14:22 / 18:22` made the answer obvious and took one log query.
- **What made it findable:** enumerating every `SOCCER_PREGAME_AUTORUN` line for
  the whole day rather than reading a window around the stop. The window around
  13:47 contained nothing, correctly, and four hypotheses died there.
- **Cost of the wrong frame:** four hypotheses and several log queries aimed at
  an instant where, by construction, there was nothing to find.

### 2026-08-15 — A HARDCODED ABSOLUTE `startTime` IS A FUTURE TIMESTAMP FOR PART OF A WATCHER'S LIFE

- A watcher hardcoding `startTime=2026-08-15T21:30:00Z` began polling at 21:23.
  For four polls the window START WAS IN THE FUTURE; Render's logs API returned
  **HTTP 400**, and the script reported `autorun_events=0`.
- **A broken query and a quiet system are the same reading.** The zeros were
  indistinguishable from "no attempt yet".
- **What caught it:** running the identical query shape against a window
  containing a KNOWN log line and confirming it returned that line. Do this
  before trusting any watcher's zeros — a control on the instrument, not on the
  system.
- Derive a watcher's window from the poll's own clock. Related: the same fixed
  `startTime` is why later 429s only DELAYED detection instead of losing the
  event — each poll re-scans the whole window. Cumulative windows are the right
  design; just don't let them start in the future.

### 2026-08-15 — check whether the instrument is already firing BEFORE building a way to make it fire
- **The rule going forward:** before building a way to make an instrument fire,
  grep for its output. This is the mirror image of the rule this same
  investigation already learned twice — an absent signal is a fact about the
  EMITTER — and it fails the same way in reverse: assuming silence when the
  thing is talking. One grep answers it.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-15 — MY OWN WATCHERS FAILED THREE TIMES IN ONE EVENING. Hand-run the gate before trusting a poller.
- The rule going forward: **a watcher's silence is not evidence the condition is
  absent — it is evidence about the watcher.** Before waiting on any poller,
  run the same check by hand once and confirm the two agree. If a window is
  confirmed open and the automation has not fired, stop the automation and act
  manually. This is the same shape as the standing rule about absent log lines,
  and it cost roughly 90 minutes of a production regression staying live.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-15 — THE CONFIDENCE INTERVAL BELONGS TO THE ESTIMATE, NOT TO THE THRESHOLD. My own test asserted otherwise and failed

Building Drop 3's precision gate, I wrote a test that varied the MODEL
probability while holding the edge fixed, and asserted a constant "bar". It
failed, and it was right to.

`sqrt(p(1-p)/n)` is widest at p=0.5 and narrows toward the tails. At n=120 the
2-sigma bar is **9.13 pp at p=0.5** and **5.48 pp at p=0.90**. So a 7-point edge
is REFUSED on a coin-flip game and PUBLISHED on a lopsided one — from the same
sim count, the same gate, the same code. That looks inconsistent and is correct:
the interval is a property of the estimate being published, so moving `p` moves
the bar underneath any assertion that treats it as a constant.

**The test was wrong in the informative direction.** It encoded "a threshold is
a number" when the threshold is a function of the thing being tested. Had I
"fixed" it by pinning the SE at 0.5, the gate would have published tail edges it
should refuse and refused centre edges it should allow — and every unit test
would have been green.

**How to apply.**
- When a gate compares a quantity to its own uncertainty, **hold the quantity
  fixed and vary the other side.** I now vary the MARKET price with the model
  pinned; that makes "the bar" meaningful.
- **A surprising test failure in a statistical gate is evidence about the
  statistics before it is evidence about the test.** Ask what the estimator's
  variance actually depends on before touching the assertion.
- Pin the counter-intuitive behaviour explicitly so a future reader does not
  "fix" it: `test_the_bar_moves_with_the_model_probability` asserts the p=0.5
  refusal and the p=0.90 publication side by side, with the two bars named.
- **State it in the module docstring too.** A reader comparing two live rows
  will see a 7-point edge published on one game and withheld on another and
  reasonably suspect a bug; the docstring is where that stops being a ticket.


## COMPACTED FROM `learnings.md` — 2026-08-18 (coordinator)

Bodies moved out of the file every session reads at startup. The RULE for
each still lives in `learnings.md` under the same heading, with the opening
lines intact; this is the working behind it. 103 entries, 1624 lines.

### 2026-08-12 — EXONERATED: the soccer window is not the egress cause
  Same-day coincidence is the weakest possible evidence.
- Cost: a day of investigation aimed at the wrong subsystem.

### 2026-08-15 — EXONERATED: "eight hydrated sports at once cannot fit in 4GiB"
against +1.0GB measured four times since. Do not close `#387` as "solved by
streaming" — streaming caps the transient, it did not explain the outlier.

Consequence, deliberate: the guard in front of MLB keeps its full 3000MB floor.
The seven cheap sports were relaxed to 1500MB because their cost is measured
(+1.7MB for five of them); MLB's tail is not.

### 2026-08-15 — the kill is MLB game hydration in pid 39, not the overview pass
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

**How to apply:** a control needs a PRE-CHANGE READING, not an intuition about
what "should" be true. An unbaselined control fails in both directions: it
raises false alarms, and it would have waved a real regression through just as
easily. Related: [[feedback_a_rate_not_count]].

### 2026-08-15 — a fix on `main` is not a fix in production: check the DEPLOYED tree
lineage have diverged by 149/121 commits.

So the dump would have produced the one answer already known to be worthless,
and it would have been reported as a result.

**How to apply:** before relying on a fix, grep the tree at the LIVE SHA, not the
working copy. `git grep <token> <live-sha> -- <path>` costs one command. This
repo has now been bitten in both directions -- changes live in production and
absent from `main` (2026-08-14 `333af428`), and changes in `main` and absent from
production (this one).

## 2026-08-15 — RULE: WEB DOES NOT RUN `main`. Parent a deploy on the LIVE SHA.
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

### 2026-08-15 — A field nobody reads is the same as the `None` it replaced

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

### 2026-08-15 — COMMITTING THROUGH AN ISOLATED INDEX LEAVES THE SHARED INDEX STAGING A DELETION OF THE FILE YOU JUST COMMITTED
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

## 2026-08-15 — FORBIDDEN: never treat equality of a LABEL as identity of a BET
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

### 2026-08-15 — THE DEPLOY CLAIM IS ADVISORY, AND IT LOST A RACE IT LOOKED LIKE IT WOULD WIN
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

## 2026-08-16 — FORBIDDEN: never deploy on `check_deploy_safety.py` alone. It said CLEAR while three jobs were running on the service.
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
something is in flight, 2 = could not determine (which is NOT the same as
clear, and is deliberately not exit 0)"* — and my loop threw away the exit code
that encoded it.

**How to apply.** Wait loops check `rc -eq 0` **and** grep for the positive
token (`^CLEAR:`), with `2>&1` so diagnostics are visible. If a poll cannot
distinguish "healthy" from "could not read", it is not a poll. This is
[[feedback_unknown_must_not_default_permissive]] recurring in a wait loop
rather than in application code, and [[feedback_instrument_blindness]]: a
healthy reading is evidence only once you know what makes it read unhealthy.

### 2026-08-16 — A TEST THAT PROVES A DEFECT DOES NOT PROVE PRODUCTION RUNS THROUGH IT. I DEPLOYED A CORRECT FIX TO AN UNUSED PATH
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

### 2026-08-16 — COLLAPSING A LEDGER FILE WITHOUT FIXING THE WRITING HABIT JUST REGROWS IT
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

### 2026-08-16 — verify a watcher's FIRST line, or it will report failure as patience
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
  `render_deploy.py` would have caught it too, but only after the attempt.
- **The rule going forward:** rebase onto what IS live, never onto what someone
  intends to deploy. A declared target is a plan, and plans change without
  telling you. Re-check ancestry against the CURRENT live sha immediately before
  every deploy, however recently the branch was rebased.
- **Cost:** none — caught before firing. It took five rebases across five live
  SHAs to land a two-file commit, which is the real signal: on a worker with five
  sessions deploying, a small change should ride along rather than chase.

### 2026-08-16 — A DEPLOY HAS TWO LAGS IN SERIES. I GUARDED ONE AND MISREAD THE SYSTEM THREE TIMES
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
start of the work** — `deploy_preflight --json` returns `deploy_claim.holder`
for free on the same call that gates the jobs, so there is no excuse of cost.

Corollary: **you cannot release a claim you no longer hold**, and `--force`
against a live claim breaks another session's lock. Mine was gone; I left it.

## 2026-08-16 — FORBIDDEN: never read a deploy claim's `target` as a statement about what is running

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
- How we found out: read the competing implementation's CALL SITES rather than
  its diff stat — one call, inside the exit path, which answered the whole
  question in a line.
- The rule going forward: **before reverting your own work in favour of a peer's,
  find what each one measures that the other does not.** Read call sites, not
  line counts. If they are complementary, merge and pin the merge with a test —
  ours fails if `record` is ever rewired to exit-only, because the two channels
  would then silently disagree, which is worse than either alone.
- Cost: none — the check took one command and saved a good half of the work.

## 2026-08-15 — RULE: resolve a ledger conflict by REPLACING the stale entry, never by appending
  still read "Lane stays OPEN".
- How we found out: counted headers per slug and re-ran the hook's own grep
  after resolving, instead of trusting that no conflict markers meant no defect.
- Cost: caught pre-push; the second-order bug was live for about a minute.

### 2026-08-16 — A RECORDER GATED ON THE PUBLISH DECISION CANNOT EVALUATE THE PUBLISHER
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
- How we found out: read the competing implementation's CALL SITES rather than
  its diff stat — one call, inside the exit path, which answered the whole
  question in a line.
- The rule going forward: **before reverting your own work in favour of a peer's,
  find what each one measures that the other does not.** Read call sites, not
  line counts. If they are complementary, merge and pin the merge with a test —
  ours fails if `record` is ever rewired to exit-only, because the two channels
  would then silently disagree, which is worse than either alone.
- Cost: none — the check took one command and saved a good half of the work.

## 2026-08-15 — RULE: resolve a ledger conflict by REPLACING the stale entry, never by appending
  still read "Lane stays OPEN".
- How we found out: counted headers per slug and re-ran the hook's own grep
  after resolving, instead of trusting that no conflict markers meant no defect.
- Cost: caught pre-push; the second-order bug was live for about a minute.

### 2026-08-16 — a "regression" that was a SCOPE ERROR: the two numbers were never the same quantity
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
wrote that caveat into my own report and then still led with the number as
alarming. **A caveat stated is not a caveat applied.**

Second-order, and the more useful half: the sampling schedule was aimed at the
wrong hours. Two of three baseline records covered morning. A baseline that
never covers the failure window measures the wrong distribution no matter how
many samples it has. Cron moved `15 */4 * * *` → `45 19,22,1 * * *`.

---

## 2026-08-16 — NEAR-MISS: verifying against a ref NAME is not verifying
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
fixture was inert and the tests were reading the real disk** — they passed or
failed on what the machine happened to have, not on the code. A green run was
evidence about the checkout.

**The rule:** a baseline is only valid for tests whose inputs it actually
shares. For data-touching tests, establish the baseline IN THE SAME TREE, or
prove the test cannot reach the disk. And `raising=False` on a monkeypatch
turns a typo into a silent no-op — pair it with an assertion that the patch
took, or name the function the code actually calls.

## 2026-08-16 — the shared-index revert fired TWICE against one session, and the second time it was armed AFTER a clean push.
does not end the exposure** — the index re-armed after it, so the check belongs
immediately before EVERY commit, not once per session. Read
`git diff --cached --numstat HEAD` and look at the DELETION column, scoped to
your own paths, so you disarm your revert without touching another lane's
staged work.

## 2026-08-16 — a mirrored row set makes a wrong join look like a UNIFORM defect, which is the most convincing kind.
identifies exactly one source row — and against it the answer is 12 of 12
CORRECT.

**The rule:** uniformity is not evidence of a real defect; a wrong join is
uniform too. Before believing a 100%-consistent finding, ask what the join key
would do if two rows could both match it. Prefer a key that cannot collide
(here: the prices, which the row already carried).

### 2026-08-16 — I REPLAYED THE HELPER OVER REAL PRODUCTION ROWS, CALLED IT VERIFIED, AND SHIPPED A FIX THAT COULD NOT REACH 3 OF THEM. A replay proves the FUNCTION; only the call path proves the FIX
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

**The rule:** re-read the live SHA immediately before firing (already a rule) AND
re-cut if it moved. The longer a branch is gated, the more likely it has silently
become a revert. On a tree with five sessions deploying, "live" has a lifetime of
minutes.

## 2026-08-16 - FORBIDDEN: a deploy does not race another deploy on this platform. It CANCELS it.

**Re-reading the live SHA protects you from shipping a revert. It does NOT
protect the other session's in-flight deploy.** These are different failures with
different fixes. After every deploy, read the deploys list for a `canceled` entry
inside your window, and own the re-ship if one appears.

## 2026-08-16 - a verification script needs the same predicate discipline as the code it verifies, and a disagreeing verifier is suspect BEFORE the fix is.

Both would have been written up as "the fix did not work". **When a measurement
disagrees with a well-founded expectation, check the measurement first** - it is
newer, less reviewed, and was usually written in a hurry at the end.

## 2026-08-16 - `check_deploy_safety.py` can report a blocker that does not exist, and a BLIND read of it is not a CLEAR one.
   `NOT CLEAR` nor `CLEAR:`, so a watcher testing `'NOT CLEAR' not in out`
   declares the gate clear **precisely while it cannot see**. I wrote that
   watcher and caught it before it reported.

**The rule:** gate on an explicit positive (`CLEAR:` present) AND the absence of
`[UNKNOWN]` - never on the absence of a negative. Cross-check any "build in
flight" claim against the artifact's `written_at`, which is the output rather
than the marker.

### 2026-08-16 — FORBIDDEN: trusting a commit you verified only BEFORE `git commit`. Guards cannot see corruption that happens DURING it
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
`RENDER_API_KEY` is readable and `deploy_claim.py acquire` would have granted both claims.

Secondary discovery, and it is the tell: **`send_message` is unavailable in unattended
sessions**, in both directions. So the one session that most needs to coordinate before a
deploy is the one that structurally cannot. If a run cannot message its peers, it must not
take an action that requires coordinating with them.

## 2026-08-16 - FORBIDDEN: never split one change across separately-deployed files and rely on TELLING the deployer. A message is not a guard.
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

**The rule:** before recording a detector's null result, state its DENOMINATOR
and its threshold. "0 steam from 4 eligible rows at +/-15 points" is a
measurement; "0 steam" is a guess wearing a number.

## 2026-08-16 - the third instance of the same instrumentation gap, in the file where I fixed the second.
ASSEMBLED, which on this path is three: the producer's return, the per-sport
stats dict, and the endpoint's key list. **Knowing the rule did not stop me
reproducing the defect within two hours.** Check the assembly sites, not the
commit.

## 2026-08-16 — FORBIDDEN: curating a deploy branch BY FILE without checking the call boundary you just cut
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

It caps at ~2 pages and returns an arbitrary slice, so there is no denominator.
**Presence is evidence; absence and frequency are not.** What actually proved the
fix was the ORDER of two lines inside ONE covered tick — `RECONCILIATION_AUTORUN_GATED`
then `NFL_PBP_FETCH_SKIPPED`, 63 ms apart. Read ordering within a covered window,
never counts across one.

## 2026-08-16 - FORBIDDEN: never join a CHANGE metric on a key that contains the changing fields. The metric becomes conditioned on the absence of what it measures.
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

**The rule:** in a repo where files move several times an evening, a ledger may
record a hash as EVIDENCE of what was true, but must never present one as an
INSTRUCTION to be followed later without re-reading. Name the branch and the
files; let the reader resolve the hashes at cut time.

## 2026-08-16 - FORBIDDEN: a loose join key makes a row VISIBLE. It does not make the row's values COMPARABLE. Those are two decisions and I made only one.
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
encodes an assumption the fix is correcting before you touch either. Rewrite the
test and say WHY in its docstring, so the next reader sees the fixture changed
because reality did -- not because it was inconvenient.

## 2026-08-16 — SCOPE NOTE on "blob-staging needs `--path`": true in general, WRONG for this repo
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

## 2026-08-16 — FORBIDDEN: reading `$?` after a pipeline. TWICE IN ONE HOUR, two different tools, both times the wrong answer was the REASSURING one
   the exact work the change being deployed exists to protect.

**Why this one is dangerous rather than merely wrong:** the failure is silent and
always optimistic. A broken guard that reports HOLD gets noticed in minutes; one
that reports CLEAR gets acted on.

**THE RULE.** Capture the status on the command itself, never through a filter:

    OUT=$(cmd 2>&1); CODE=$?          # correct
    OUT=$(printf '%s' "$OUT" | tr ...)  # filter AFTER
    cmd > file 2>&1; CODE=$?; grep ... file   # also correct

**And the tell:** instance 2 printed `CLEAR` on a line that also carried
`jobs=3 claim=<someone>`. **A verdict that contradicts the fields printed beside
it is the instrument lying, not the system behaving oddly.** Read the fields, not
the verdict -- the same lesson as `feedback_read_the_field_you_already_have`.

### 2026-08-16 — AN ISOLATED-INDEX COMMIT IS PROTECTED FROM THE SHARED INDEX AND NOT FROM A HEAD MOVE. Mine was orphaned within minutes, and so was another lane's
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
  itself a claim that can be withdrawn, and withdrawal is exactly what a failed
  verification produces. Corollary: when a guard contradicts your own recorded
  check, **the guard is reading now and you read earlier** — believe it and
  re-read before arguing.
- Same session, same mechanism: my first `lanes.md` lane block was **overwritten
  wholesale** by a parallel session's write and had to be re-appended.

### 2026-08-16 — `commit-guard`'s suggested fix list was INCOMPLETE on all THREE occurrences in one session
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

### 2026-08-16 — a stale-copy commit can keep the DOC and drop the CODE, and every cheap check still passes
- **Why nothing caught it.** The file existed. The tool ran. The todo entry
  describing the fix existed and read as evidence the fix was in. `git status`
  showed the difference as a normal working-tree modification — indistinguishable
  from work in progress. Two of my own commits were **orphaned**, which
  `git log <sha>` still resolves happily because the objects remain reachable
  from the reflog.
- **The rule going forward:** after committing on a tree with concurrent
  sessions, verify by **ancestry and content**, not by the commit succeeding:

    git merge-base --is-ancestor <sha> HEAD   # orphaned if this fails
    git show HEAD:<path> | grep -c <a token unique to the change>

  A commit that returned a SHA is not a commit that is still in the history, and
  a doc entry describing a fix is not the fix. Same family as
  `presence-is-not-reachability` and
  `test-the-fixs-predicate-not-its-deploy-state`.


<!-- RESTORED 2026-08-16 18:3xZ by session branch-overlap-baseline-watch: present in HEAD, absent from this working copy. Same stale-copy mechanism documented in this file today. Content is byte-identical to HEAD. -->

### 2026-08-16 — A PLAN'S FIELD LIST WRITTEN FROM GREPS WAS WRONG FOR ALL FOUR SPORTS. Greps find NAMES; only the payload has the data
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
- No other sport's live_state carries its projection, so nothing else in the
  module guards it — a trap that exists in exactly one place is the kind that
  survives review.

### 2026-08-16 — A RESERVATION IS A READING WITH A TIMESTAMP. Three different kinds went stale in ONE session
3. **Todo IDs** — this session's plan reserved `#447`/`#448`; other sessions
   filed unrelated items under both before it was filed.

- **The rule going forward:** re-read the authority immediately before the
  action that depends on it — the claim before the edit, the index before the
  commit, the ID before filing. Never carry a reading across a turn boundary.

### 2026-08-16 — A DIRECTORY NAMED `pbp` CAN CONTAIN MODELS, NOT PLAY-BY-PLAY
  finding in itself rather than a coincidence.

### 2026-08-16 — A KEY NAME THAT MATCHES ANOTHER SPORT'S CONTRACT IS NOT A CONTRACT. WNBA publishes `run_margin_dist` and `total_runs_dist` — the exact keys MLB prices from — carrying a three-point quantile summary MLB's reader cannot parse, and the failure is SILENT
  why.** The matching name is worse than a mismatched one: it invites the wiring
  and then swallows the result.
- *(evidence: `.syndicate/deploys.md`, "outstanding #3, WNBA distribution")*

### 2026-08-16 — "THE ONLY OPEN WORK IS VERIFICATION" WAS FALSE, AND A CONTENT CENSUS ACROSS ALL THREE SERVICES IS WHAT CAUGHT IT
  `SYNDICATE_ENABLE_INTELLIGENCE_STATE_BACKGROUND_LOOP=false` on that service.
  **Dormant is not fixed** — loop ownership is an env flag that moves with no
  diff, so a clamp behind a flag is a latent re-arm, not an absence.
- *(evidence: `.syndicate/deploys.md`, clamp census 2026-08-16 23:5xZ / 00:0xZ)*

## 2026-08-16 — FORBIDDEN: attributing an excursion with a field that is not THREAD-scoped. A process-global "last stage" names the last thread to speak, not the one allocating.

The refutation took one covered window: inside the excursion there was **no
`OVERVIEW_SPORT_BEGIN` or `OVERVIEW_SPORT_END` at all**. The loop I had blamed
was not running.

**Two rules.**

1. **Before attributing anything to an instrument's field, ask what its SCOPE
   is** — per-thread, per-process, per-request. A global read as if it were
   local is not a weak signal, it is a *wrong* one, and it is wrong in a way
   that looks precise. `feedback_read_the_field_you_already_have` says read the
   field; this says **know what the field is scoped to.**

2. **`state.md` ALREADY SAID THIS.** Line 462 records that the climb has "no
   stage marker, so `last_stage` structurally cannot name it", and line 502 says
   the allocation is "STILL UNNAMED". I never read that section — I entered from
   a user's log paste, re-took the lane, and started measuring. The session
   protocol's "read `state.md` first" is not ceremony; it is the step that would
   have made an hour of work unnecessary and stopped a false verdict being
   written into the deploy ledger. **When you re-take an OPEN lane, read what
   that lane already concluded before you measure anything.**

**Also worth keeping: the control arm is what actually killed the follow-up
hypothesis.** After the retraction I suspected the artifact-pull path, on a
+537MB jump right after `pulled_hot_artifacts count=17`. Presence in 7 excursion
windows looked convincing until I ran 6 matched control windows: same rate in
both arms (1/7 vs 1/6). **A correlation study without a control arm is a
coincidence generator.**

### 2026-08-16 — A "NEVER DEFAULTS" TEST THAT ONLY EXERCISES GUARD CLAUSES IS VACUOUS. Three times in one session
3. `game_shape.mlb_leverage_index` — `.get(key, 1.0)` passed, because every input
   in the test was rejected by a guard clause before the dict was touched.

- **The rule going forward:** a test for "does not default" must use an input
  that **reaches the defaulting line** — valid in every other respect and missing
  only the thing under test. For a lookup that means a key passing all validation
  and genuinely absent from the table (here: `1-3` with 0 outs, the one base-out
  combination below the n>=100 floor). If no such input can be named, the
  fallback may be unreachable — also worth knowing.
- **Mutation testing caught all three**, including the third AFTER I had written
  the rule for the first. Run it against the guard you care most about, not only
  the code you are least sure of.

### 2026-08-16 — A RESIDUAL THAT CORRELATES WITH THE FITTED VALUE MEANS THE MODEL IS WRONG, NOT THE DATA
- Same session, same shape: a leverage normalisation weighted by state frequency
  alone made start-of-game read 1.14 when an average plate appearance is 1.00
  **by definition**. That definition was the check that caught it. **Prefer a
  quantity whose correct value is known a priori as the sanity check.**

## 2026-08-16 — FORBIDDEN: instrumenting a WRAPPER when the hot path has siblings that reach the same work directly. Twice in one night.
   `_load_chunk_records_for_window` (:2042) and `load_recent_evaluation_records`
   (:2088), which default to a DIFFERENT constant and call it DIRECTLY. One of
   three entry points instrumented, and the one wired to a missing file.

**The rule: before instrumenting a function, grep for other callers of what it
calls.** If the callee has siblings reaching it by another route, instrument the
CALLEE. The choke point every caller must pass is the only placement that cannot
be routed around. Both fixes tonight were the same move.

**The tell is available in advance and costs one grep.** In both cases the
function I first chose had "wrapper" or "materialising wrapper" in its own
docstring.

### 2026-08-16 — SCOPING A DEPLOY WHEN `main` CARRIES OTHER LANES' WORK: parent on the LIVE SHA, not on `main`
     twice in the hours before this deploy).
  2. Confirm the live SHA is **not** assumed to be on `main`. Web's configured
     branch IS `main`, yet the live SHA was not an ancestor of it —
     previously-deployed commits fall out of `main`'s history when sessions
     rewrite it. **Do not infer the deploy base from the branch setting.**
  3. `git log LIVE..origin/main -- <your files>` and confirm **only your
     commits** touch them. That is what makes the next step safe.
  4. Build with plumbing into an isolated index: `read-tree LIVE`,
     `update-index` your files to `origin/main`'s blobs, `commit-tree -p LIVE`.
     Never touches the working tree or the shared index.
  5. Assert the result is exactly N files and each blob is **identical to
     `origin/main`'s** — that proves you shipped your fix and not a hand-merge.
  6. Push it to a branch so it cannot be orphaned, then deploy that SHA.
- Cost: about ten minutes. It bought unambiguous attribution and left five other
  lanes their own deploy decisions.

### 2026-08-16 — A RESTART CONFOUNDS ANY FIX WHOSE CLAIM IS ABOUT STATE PERSISTING
  stickiness, caching, leaks, accumulation — the first minutes after a restart
  can only ever look healthy, so a reading taken there is worthless. The
  measurement must span the condition that produced the bug: for `#455`, a live
  slate where `generated_at` must ADVANCE across ticks rather than freeze.
- Same family as the existing rule that a healthy reading is evidence only once
  you know what makes it read unhealthy — but sharper: **here the restart
  GUARANTEES the healthy reading**, so the observation carries no information at
  all.



## EVIDENCE COMPACTED OUT OF `learnings.md` — 2026-08-18

Moved verbatim by `scripts/compact_learnings.py --keep-from 2026-08-18`.
Nothing summarised or deleted. Each entry keeps its heading AND its rule in
`learnings.md`; this is the full working. `learnings_index.md` spans both
files — regenerate with `py -3 scripts/build_learnings_index.py`.

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
