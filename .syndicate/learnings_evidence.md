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
