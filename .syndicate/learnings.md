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
     `841228d9`, `a0c5e7af`, `a3f9ed97`, `bd227fa3`, `bf8833e9`.
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
