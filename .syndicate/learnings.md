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

## Index — 406 rules `[generated]`

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

- **Believed:** the joiner's first same-book CLV, `avg_clv_pct = -5.215` over 25
- *(evidence in `learnings_evidence.md`)*

## 2026-08-14 — a control with no baseline is a guess wearing a control's clothes

- **2023-2025**), unrelated to the MLB window (2026-08-01..08-14), and they
- *(evidence in `learnings_evidence.md`)*

## 2026-08-14 — read the system's clock, not the wall clock

- The rule going forward: **before firing a pinned deploy, re-read the
- *(evidence in `learnings_evidence.md`)*

## 2026-08-15 — RULE: WEB DOES NOT RUN `main`. Parent a deploy on the LIVE SHA.

- **The rule going forward.**
- *(evidence in `learnings_evidence.md`)*

## 2026-08-15 — A CADENCE IS A DISTRIBUTION ACROSS REGIMES, NOT A CONSTANT

- **The belief.** "MLB quote capture runs on a metronomic ~121.6-minute beat." It
- *(evidence in `learnings_evidence.md`)*

## 2026-08-15 — ANCESTRY OF `origin/main` IS NOT DEPLOYMENT; READ THE DEPLOYED TREE

- **The near-miss.** Asked whether the per-sport pregame cooldown had shipped, the
- *(evidence in `learnings_evidence.md`)*

## 2026-08-15 — RULE: a "baseline" is a FILE you diffed, not a number you quoted

- **The rule going forward:** a shared stylesheet exists precisely so one class
- *(evidence in `learnings_evidence.md`)*

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

- **The rule going forward:** every memory number carries a SCOPE — container,
- *(evidence in `learnings_evidence.md`)*

## 2026-08-16 — FORBIDDEN: never deploy on `check_deploy_safety.py` alone. It said CLEAR while three jobs were running on the service.

- **Measured 2026-08-16 00:13Z on refresh-worker.** `check_deploy_safety.py`
- *(evidence in `learnings_evidence.md`)*

## 2026-08-16 — FORBIDDEN: a wait loop must gate on an AFFIRMATIVE success token, never on the absence of a failure string

- *Full working in `learnings_evidence.md` under this heading.*
- *(evidence in `learnings_evidence.md`)*

## 2026-08-15 — FORBIDDEN: never read a joiner zero as a fact about the world until the reader is shown to SEE the data

- **What happened.** The rule was written in advance, in good faith, and was
- *(evidence in `learnings_evidence.md`)*

## 2026-08-15 — FORBIDDEN: shipping a verification you have not falsified. THREE failed checks in one night, zero failed fixes

- **The rule.** Before arming any check, ask the falsification question about the
- *(evidence in `learnings_evidence.md`)*

## 2026-08-15 — FORBIDDEN: `git <cmd> <rev>:<dotpath>` in Git Bash on Windows. It silently reads the WRONG thing, and only for dot-prefixed trees

- **The part that makes it dangerous: it is selective.** Measured:
- *(evidence in `learnings_evidence.md`)*

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

- **Measured 2026-08-15/16 on live-odds-worker.** Its claim advertised
- *(evidence in `learnings_evidence.md`)*

## 2026-08-15 — RULE: merge in the object database when the shared tree is dirty

- **The rule going forward:** on this repo a reconcile does **not** need a
- *(evidence in `learnings_evidence.md`)*

## 2026-08-15 — RULE: resolve a ledger conflict by REPLACING the stale entry, never by appending

- **The rule going forward:** when both sides changed a lane, the merge is not
- *(evidence in `learnings_evidence.md`)*

## 2026-08-15 — RULE: merge in the object database when the shared tree is dirty

- **The rule going forward:** on this repo a reconcile does **not** need a
- *(evidence in `learnings_evidence.md`)*

## 2026-08-15 — RULE: resolve a ledger conflict by REPLACING the stale entry, never by appending

- **The rule going forward:** when both sides changed a lane, the merge is not
- *(evidence in `learnings_evidence.md`)*

## 2026-08-16 — FORBIDDEN: reading a git error as noise from the NEXT command when it names the file the PREVIOUS one staged

- **Git told me, in the same output as the push.** The command chained
- *(evidence in `learnings_evidence.md`)*

## 2026-08-16 — RULE: fix a bad commit MESSAGE by rebuilding the commit from its own tree, not by `--amend` and not by living with it

- **What we believed:** the shared-tree recipe offered two options for a wrong
- *(evidence in `learnings_evidence.md`)*

## 2026-08-16 — a per-row field read off ONE row and generalised to all of them

- **Overturned:** my own same-day claim that "every exercised `win_prob` run is on
- *(evidence in `learnings_evidence.md`)*

## 2026-08-16 — OVERTURNED: a pinned SHA identifies deployed CODE

- **The belief.** Two scheduled measurement tasks pinned their comparison with
- *(evidence in `learnings_evidence.md`)*

## 2026-08-16 — CORRECTED IN-SESSION: at-cap is not a kill

- *Full working in `learnings_evidence.md` under this heading.*
- *(evidence in `learnings_evidence.md`)*

## 2026-08-16 — NEAR-MISS: verifying against a ref NAME is not verifying

- **What almost shipped.** A three-file ledger commit that also silently reverted
- *(evidence in `learnings_evidence.md`)*

## 2026-08-16 — NARROWING AN INSTRUMENT TO A MEASURED DISTRIBUTION BUILDS IN A BLIND SPOT

- **What I did, and it looked like good work.** A census said **41 of 42**
- *(evidence in `learnings_evidence.md`)*

## 2026-08-16 — FORBIDDEN: never test what is deployed with `git merge-base --is-ancestor`. It answers a question about HISTORY; deployment is a question about CONTENT.

- `edbbee9d` (spread-sign fix) is **NOT an ancestor** of live `97491161` — and
- *(evidence in `learnings_evidence.md`)*

## 2026-08-16 — FORBIDDEN: never use a fresh `git worktree` as a test baseline for anything that reads `data/`.

- *Full working in `learnings_evidence.md` under this heading.*
- *(evidence in `learnings_evidence.md`)*

## 2026-08-16 — the shared-index revert fired TWICE against one session, and the second time it was armed AFTER a clean push.

- *Full working in `learnings_evidence.md` under this heading.*
- *(evidence in `learnings_evidence.md`)*

## 2026-08-16 — a mirrored row set makes a wrong join look like a UNIFORM defect, which is the most convincing kind.

- **What happened.** To verify an edge-attribution fix before deploying, I fetched
- *(evidence in `learnings_evidence.md`)*

## 2026-08-16 - FORBIDDEN: never let a branch sit behind a deploy gate without re-cutting it. Waiting is itself a source of staleness.

- *Full working in `learnings_evidence.md` under this heading.*
- *(evidence in `learnings_evidence.md`)*

## 2026-08-16 - FORBIDDEN: a deploy does not race another deploy on this platform. It CANCELS it.

- *Full working in `learnings_evidence.md` under this heading.*
- *(evidence in `learnings_evidence.md`)*

## 2026-08-16 - a verification script needs the same predicate discipline as the code it verifies, and a disagreeing verifier is suspect BEFORE the fix is.

- `h2h_lay` counted with `'lay' in market` - which matches **player**
- *(evidence in `learnings_evidence.md`)*

## 2026-08-16 - `check_deploy_safety.py` can report a blocker that does not exist, and a BLIND read of it is not a CLEAR one.

- **What happened:** an isolated-index commit of 3 ledger files produced a commit of
- *(evidence in `learnings_evidence.md`)*

## 2026-08-16 — FORBIDDEN: letting a FITTED MODEL judge, when a model-free measurement of the same thing is available

- **raw group spread** failed mlb desktop at 313px while cards carrying identical
- *(evidence in `learnings_evidence.md`)*

## 2026-08-16 — FORBIDDEN: shipping a check whose FAILURE MESSAGE does not carry the evidence for the failure

- *Full working in `learnings_evidence.md` under this heading.*
- *(evidence in `learnings_evidence.md`)*

## 2026-08-16 - FORBIDDEN: a deploy-content check must return THREE verdicts, not pass/fail. "Nothing shipped" is not "shipped wrong".

- *** THE THREE FILES DID NOT TRAVEL TOGETHER. Expect cards_error / blank board. ***
- *(evidence in `learnings_evidence.md`)*

## 2026-08-16 — OVERTURNED: "my commits are safe once the guard passes and `git show --stat HEAD` looks right"

- *Full working in `learnings_evidence.md` under this heading.*
- *(evidence in `learnings_evidence.md`)*

## 2026-08-16 — FORBIDDEN: never let an UNATTENDED session fire a deploy, and do not rely on prose to stop it

- *Full working in `learnings_evidence.md` under this heading.*
- *(evidence in `learnings_evidence.md`)*

## 2026-08-16 - FORBIDDEN: never split one change across separately-deployed files and rely on TELLING the deployer. A message is not a guard.

- *Full working in `learnings_evidence.md` under this heading.*
- *(evidence in `learnings_evidence.md`)*

## 2026-08-16 - FORBIDDEN: never record a detector's zero as a pass when the data gave it no chance to fire.

- *Full working in `learnings_evidence.md` under this heading.*
- *(evidence in `learnings_evidence.md`)*

## 2026-08-16 - the third instance of the same instrumentation gap, in the file where I fixed the second.

- **not sufficient**. The counter must reach every place the payload is
- *(evidence in `learnings_evidence.md`)*

## 2026-08-16 — FORBIDDEN: curating a deploy branch BY FILE without checking the call boundary you just cut

- **A file-level diff cannot see this.** I verified content by blob, ancestry
- *(evidence in `learnings_evidence.md`)*

## 2026-08-16 — FORBIDDEN: computing a RATE or a COUNT from `scripts/render_logs.py`

- *Full working in `learnings_evidence.md` under this heading.*
- *(evidence in `learnings_evidence.md`)*

## 2026-08-16 - FORBIDDEN: never join a CHANGE metric on a key that contains the changing fields. The metric becomes conditioned on the absence of what it measures.

- *Full working in `learnings_evidence.md` under this heading.*
- *(evidence in `learnings_evidence.md`)*

## 2026-08-16 - a blob hash written into a ledger is a SNAPSHOT, not a lease.

- **re-read the blobs before cutting rather than trusting the numbers printed in
- *(evidence in `learnings_evidence.md`)*

## 2026-08-16 — ASK-ANSWER-SUBSTANCE CHECKPOINT 2: five beliefs overturned

- **Sorting orders a pool; it does not decline to publish one.** Necessary, never
- *(evidence in `learnings_evidence.md`)*

## 2026-08-16 — ASK-ANSWER-SUBSTANCE CHECKPOINT 3: two more

- **The rule: when a metric moves across your change, diff the code path the
- *(evidence in `learnings_evidence.md`)*

## 2026-08-16 - FORBIDDEN: a loose join key makes a row VISIBLE. It does not make the row's values COMPARABLE. Those are two decisions and I made only one.

- *Full working in `learnings_evidence.md` under this heading.*
- *(evidence in `learnings_evidence.md`)*

## 2026-08-16 - a test I wrote can encode the belief that production later disproves, and then it defends the bug.

- **The rule:** when a fix makes your own tests fail, check whether the test
- *(evidence in `learnings_evidence.md`)*

## 2026-08-16 — SCOPE NOTE on "blob-staging needs `--path`": true in general, WRONG for this repo

- *Full working in `learnings_evidence.md` under this heading.*
- *(evidence in `learnings_evidence.md`)*

## 2026-08-16 - FORBIDDEN: a verifier that cannot FAIL cannot PASS. State the denominator every assertion needs, or it will report an empty population as success.

- **There were ZERO moved-line rows.** `PASS if not leaked and not bad_steam` is
- *(evidence in `learnings_evidence.md`)*

## 2026-08-16 — FORBIDDEN: reading `$?` after a pipeline. TWICE IN ONE HOUR, two different tools, both times the wrong answer was the REASSURING one

- **The rule going forward:** re-run the collision check **immediately before
- *(evidence in `learnings_evidence.md`)*

## 2026-08-16 — OVERRIDE, LOGGED: an unattended session was authorised by the user to fire this deploy

- **Scope of the override:** deploy `_freeze_market_dirs` (blob `426bbd70`, on
- *(evidence in `learnings_evidence.md`)*

## 2026-08-16 — CORRECTION: the shared index CHURNS, it does not accumulate — and staged content is not the alarm

- **Extends the same-day rule about slug-level ledger checks.** That one framed
- *(evidence in `learnings_evidence.md`)*

## 2026-08-16 — ASK-ANSWER-SUBSTANCE CHECKPOINT 4: fixing a fix, and two bad inferences

- **The rule going forward:** a conditioning variable must be derivable from
- *(evidence in `learnings_evidence.md`)*

## 2026-08-17 — FORBIDDEN: deploying `main`'s TREE to a service that runs a curated deploy branch

- **The tell is per-file, and it is cheap:** for each conflicted path compute
- *(evidence in `learnings_evidence.md`)*

## 2026-08-17 — FORBIDDEN: gating a deploy on "no jobs running" for a continuously-busy worker

- **Worse, the gate measures the wrong moment.** Render BUILDS first and stops the
- *(evidence in `learnings_evidence.md`)*

## 2026-08-17 — FORBIDDEN: resolving the SAME symbolic ref in two git calls. A stale tree on a current parent is a fast-forward, and git cannot tell it from a deliberate revert.

- **The rule going forward:** before wiring a producer to a consumer on the
- *(evidence in `learnings_evidence.md`)*

## 2026-08-16 — FORBIDDEN: attributing an excursion with a field that is not THREAD-scoped. A process-global "last stage" names the last thread to speak, not the one allocating.

- **The rule going forward:** before concluding the DATA is wrong, scan the
- *(evidence in `learnings_evidence.md`)*

## 2026-08-16 — FORBIDDEN: instrumenting a WRAPPER when the hot path has siblings that reach the same work directly. Twice in one night.

- **The rule going forward — the recipe, because it worked and is reusable:**
- *(evidence in `learnings_evidence.md`)*

## 2026-08-17 — RULE: the em-dash in a lane header is SYNTAX, not punctuation. A hyphen header is an UNGUARDED lane

- **Evidence.** `wnba-fixture-identity` was opened by a live session with ASCII
- *(evidence in `learnings_evidence.md`)*

## 2026-08-17 — FORBIDDEN: diagnosing from FILTERED log projections. Six wrong attributions, one question, and the answer was in the lines I was truncating.

- **Each filter encoded the hypothesis I was trying to test.** A `text=` query
- *(evidence in `learnings_evidence.md`)*

## 2026-08-17 — RULE: committing through an ISOLATED index ARMS the shared index with a revert of that commit. Disarm after, not just before

- **The recipe is still right; it has a second half nobody had written down.**
- *(evidence in `learnings_evidence.md`)*

## 2026-08-17 — OVERTURNED: "a statistical win on a sim parameter can be graded by betting hit rate on the same sample"

- **Belief going in:** the overrides file records `starter_tto_quality_scaling`
- *(evidence in `learnings_evidence.md`)*

## 2026-08-17 — RULE: before building a fix, check whether it was already considered and REJECTED in the code you are about to edit

- **The rule going forward:** **an override is not an override until it has been
- *(evidence in `learnings_evidence.md`)*

## 2026-08-17 — RULE: score a DISTRIBUTIONAL forecast with a distributional baseline. A point test on a distribution is the wrong instrument, even when it agrees.

- **What happened.** Phase 7's whole purpose was to build a proper scoring rule for
- *(evidence in `learnings_evidence.md`)*

## 2026-08-17 — RULE: a LEAKED backtest number is an UPPER BOUND, not merely an untrustworthy one

- **Standing practice here is to mark a leaky backtest "not citable" and stop.**
- *(evidence in `learnings_evidence.md`)*

## 2026-08-17 — RULE: a PATHSPEC commit is the default; the isolated index is the FALLBACK. The latter arms a revert every time

- **Relayed by `commit-guard-blind-to-own-recipe`, owed to and written by the
- *(evidence in `learnings_evidence.md`)*

## 2026-08-17 — RULE: never close a queue item in BULK. Close each against its own evidence

- **I did this to a live deploy request within hours of documenting the same
- *(evidence in `learnings_evidence.md`)*

## 2026-08-17 — RULE: an aggregate dispersion check cannot see an UNINFORMATIVE CENTRE

- **What happened.** Phase 7's bias/dispersion decomposition reported MLB pitcher
- *(evidence in `learnings_evidence.md`)*

## 2026-08-17 — RULE: a signature change needs a CALLER CENSUS, not a spot-check of the caller you just edited

- **Evidence.** `_load_team_ratings` gained a required third parameter (`as_of`,
- *(evidence in `learnings_evidence.md`)*

## 2026-08-17 — RULE: a falsified prediction LOCALISES a bug; treat it as a measurement, not a miss

- **Three predictions were falsified today and each was worth more than the
- *(evidence in `learnings_evidence.md`)*

## 2026-08-17 — A SIGNATURE CHANGE NEEDS A CALLER CENSUS, AND THE CALLER YOU CANNOT REACH IS THE ONE THAT BREAKS

- **Why it survived â€” three independent covers, and each is a general shape:**
- *(evidence in `learnings_evidence.md`)*

## 2026-08-17 — TEST DEPLOYMENT BY CONTENT, NEVER BY ANCESTRY OR BY A SHARED SYMBOL

- **False negative.** live-odds-worker deployed `7470939b`.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-17 — RULE: the FIRST test for any flagged feature is "does enabling it change anything"

- **I built three inert things today.** Not three bugs — three pieces of work that
- *(evidence in `learnings_evidence.md`)*

## 2026-08-17 — RULE: a watcher that reports a PEAK of ZERO has not measured a peak. Zero samples is NO DATA, never "clean"

- **I wrote a memory watcher whose entire purpose was to catch an OOM I had
- *(evidence in `learnings_evidence.md`)*

## 2026-08-17 — RULE: a feature can be unfed at the DATA layer, and it looks nothing like a bug

- **Standing rules here cover code that is present-but-unreachable.** This is the
- *(evidence in `learnings_evidence.md`)*

## 2026-08-17 — RULE: rank modelling gaps by how much the dimension DISCRIMINATES, not by how complete its machinery is

- **What I did.** Researching what the MLB sim was missing, I found pitch-type
- *(evidence in `learnings_evidence.md`)*

## 2026-08-17 — RULE: you cannot add a MECHANISM to a CALIBRATED engine without re-fitting its rates

- **Measured, 2x2 factorial, 4 of 4 markets:** adding position-player substitution
- *(evidence in `learnings_evidence.md`)*

## 2026-08-17 — RULE: "the model is absent" needs a FIELD AUDIT, not a name search

- **I published a research document stating the MLB sim has "no batted-ball type
- *(evidence in `learnings_evidence.md`)*

## 2026-08-17 — FOUR DEFECTS IN ONE SESSION SHARED ONE SHAPE: THE ERROR PATH RENDERED AS THE SYSTEM'S OWN "NOTHING HERE"

- **1.** `poll_active_leagues_for_tick` caught each league's exception into an
- *(evidence in `learnings_evidence.md`)*

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

## 2026-08-18 — A DUPLICATED TERM PASSES EVERY CHECK THIS REPO HAS. A PLAUSIBILITY READ CAUGHT IT.

I wired `goals_for` into soccer's rating aggregation. `team_rows_from_match_history`
already sets `xg_for = home_goals` (goals as the xG stand-in), so the same number
entered `_attack_strength` twice:

    ((xg_for or 1.35) - 1.35) * 0.22
    ((goals  or 1.35) - 1.35) * 0.14

Every football-data league weighted goals at **0.36 instead of 0.22**, defence
identically. I committed it, pushed it, and wrote a checkpoint calling it verified.

**WHAT DID NOT CATCH IT — the full list, because that is the finding.**
The field was **CONSUMED** (the engine reads it), **POPULATED** (real data, 918
history rows), and **MOVED PUBLISHED OUTPUT** (a real A/B artifact build showed the
projection change). So it passed: the input checklist, four reachability tests,
`off != on` per side, 31 unit tests, and an end-to-end artifact diff. **Every
instrument this repo has for exactly this class of defect reported healthy**, and
each one was RIGHT — the field genuinely was consumed, populated and reachable.

**WHAT DID CATCH IT.** `total_mean` read **3.39** for an eredivisie fixture and that
looked too big for a corners-and-shots change. A number being *implausible for its
domain* — not failing a threshold, not differing from a baseline, just wrong-looking
to someone who knows what a Dutch league total is. Correcting it gave 3.32, and
`win_probability.home` moved 0.49 -> **0.46**: the duplicate had been **flipping the
direction** of the whole contribution, not merely inflating it.

**THE RULE.** Reachability answers "does this input arrive and matter". It cannot
answer "is this input's contribution CORRECTLY SIZED", because a term counted twice
arrives and matters twice. After wiring any input into a weighted sum, **read the
resulting magnitude against domain knowledge** — an expected-goals total, a win
probability, a run line — and treat a number that is merely *surprising* as a defect
until explained. That is the only check that sees this class.

**SECOND-ORDER, and the reason this is not a one-off.** `_attack_strength` is a
weighted sum whose constants were fitted when every term but the ratings was absent
and returning neutral defaults. Every field wired into it from now on — the four
still outstanding (`possession_share`, `set_piece_xg_share`, `availability_index`,
`pace_seconds_per_event`) — risks the same thing in a subtler form: not literal
duplication, but a signal the ratings were already absorbing. **Adding a mechanism to
a calibrated engine requires re-fitting the rates that absorbed it** — CLAUDE.md
already says this for MLB and it measured a NEGATIVE interaction from two mechanisms
in 4 of 4 markets. Soccer is now in the same position and has no re-fit.

**Cross-reference:** the same night produced four defects whose error path rendered
as the system's own "nothing here". This is the inverse and worse: the error path
rendered as the system WORKING. A green instrument is evidence only about the
question it asks, and "did it arrive" is not "is it right".

## 2026-08-18 — RULE: a union merge CANNOT carry a deliberate deletion. A collapse pushed through one is undone, and comes back bigger

**I collapsed `state.md` from 59 sections to 26, pushed it through the merge
cycle, and `origin/main` came out with 87.** The collapse was reverted and my new
sections were added on top, so the file ended up **larger than before I started**.

**The mechanism is the merge resolver doing exactly its job.** The ledger files
are append-only, so the cycle resolves them by UNION: take ours, then append any
block from theirs that ours lacks. A deliberate deletion is indistinguishable
from "ours is missing a block", so every collapsed section was restored from
`origin/main` — and the invariant that guards the union reported *loss* when it
saw the collapse, which is the same confusion from the other side.

**The tell was in the numbers and I nearly missed it**: I checked
`unpushed: 0` and the file list, and only caught it because the line count on
main (3,763) was larger than the pre-collapse file (3,526). **A push that
succeeds is not a push that did what you meant.**

**How to apply.**
- **A collapse or dedupe must be the LAST commit before the push, and the push
  must be a fast-forward** — or it must be re-applied on top of the merge result.
  Re-applying is what worked here: take the collapsed file, diff its sections
  against the merged one, carry forward only sections that are in neither the
  collapse nor the archive.
- **Verify a size-reducing change by SIZE after pushing**, not by exit code.
  Sections, lines, or bytes — whichever the change was measured in.
- **Teach the invariant about the archive.** The check tracks six ledger files
  and knew nothing about `state_archive_2026-08-18_full.md`, so it read 12
  collapsed lines as lost. They were all in the archive; the override was
  correct, but the checker should have known.

## 2026-08-18 — A VARIANCE-REDUCTION TRICK THAT CHANGES THE ANSWER IS NOT A VARIANCE-REDUCTION TRICK

`GameConfig.crn_pa_seeding`, built to make sim A/B tests affordable. **It is
broken and is marked BROKEN in place rather than deleted.**

Re-seeding the game RNG per plate appearance inflates run scoring by **8-35%**
across 4 games. It does not matter how much variance it removes: **a CRN scheme
must be DISTRIBUTION-PRESERVING.** If the two arms are both wrong in the same
direction, a tighter comparison between them is a more precise measurement of
the wrong thing.

**The first bug, and why finding it was NOT the end.** I keyed the seed on
`half.next_batter_index`, reasoning that "a team's Nth plate appearance is the
same logical event in both arms." **`simulate.py:3178` advances that index MODULO
the lineup length.** It holds 9 values, so the same stream replayed 4-5 times per
game — scoring inflated up to **126%**. I had even written "batter_index grows
monotonically (not modulo)" into the lane note; one line of code said otherwise.

**RULE: before seeding, hashing, or keying anything on an index, read the line
that ADVANCES it.** A name like `next_batter_index` does not tell you whether it
wraps, and the difference between monotonic and modulo-9 is the difference
between a unique key and a 9-fold collision.

**And the second rule, which cost more:** fixing the modulo bug took the
inflation from 126% to 8-35% — **a big improvement that was still a failure.** I
verified the fix did what it claimed (104 reseeds, 104 distinct seeds, in a
104-PA game) and the symptom PERSISTED. **A confirmed fix to a real bug is not
evidence that the remaining symptom is gone.** Re-measure the SYMPTOM, not the
mechanism you repaired.

**What is actually suspected:** the joint structure of early Mersenne Twister
output across many independently-seeded streams. The marginal uniforms are clean
— draws 1-5 over 40,000 fresh streams sit within 1.2 sd of 0.5 — so the naive
"biased head" hypothesis was tested and REFUTED. MT is built for one long stream,
not many short ones. **Anyone revisiting this should use a counter-based
generator with real substreams (PCG64 `.jumped(n)`, Philox), not reseed MT.**

## 2026-08-18 — RULE: a wiring gate must ask whether the payload is READ, not whether a payload is PASSED

**Lane `football-model-owner`. Caught by measurement, one step before it would
have been published as a clean result.**

Building smartsim2's input checklist, level 0 asked the obvious question of every
`SmartSim2SimulationInput(...)` construction site: *does it pass a
`feature_generation_payload`?* Five sites said no. One said **yes** —
`smartsim2/calibration/baseline_audit.py:287` — and the gate reported it **wired**.

Its payload is `{game_id, season, week, market_total, market_spread_home}`.
**The engine reads none of them.** `drive_priors._extract_block` looks for a
NESTED block named `market_features` / `market` / `betting`; a flat
`market_total` sitting beside it is invisible. The payload is passed, and it is
inert.

### Why this is the dangerous direction of error

The gate exists to catch a payload that never arrives. But the **likely shape of
a careless fix** is not "forgot to pass it" — it is "passed something plausible
that the consumer does not read." A presence check is blind to exactly the
half-fix it will be used to sign off. It would have gone from FAIL to PASS while
the engine still ran on its neutral defaults, and the PASS would have been
*produced by the gate itself*, which is worse than no gate.

This is `presence is not reachability` applied to an instrument rather than to a
deploy. The same rule that says "a deployed fix can be inert" says "a passed
argument can be inert", and the check has to reach the same depth as the claim.

**RULE:** a gate asserting that X reaches Y must compare X's own CONTENT against
what Y actually reads — structurally, from Y's call sites. `passed is not None`
is not a wiring check. Where content is not statically knowable, report
**unknown**; never let unknown render as wired.

Encoded: `scripts/football_sim_input_checklist.py::_constructor_kwargs` returns
the payload's literal keys, and level 0 emits `NO PAYLOAD` / `INERT PAYLOAD` /
`WIRED (n blocks)` / `payload (keys not static)` as four distinct verdicts.

### The sibling error the same session made, same shape

Level 2's first run reported **"0.0% populated"** on all nine blocks. That is
indistinguishable from a total data outage and was a **broken instrument**:
`season=None` let the loader fall back to a **1-game** degenerate context. The
real load is **272 games** with `team_metrics` carrying **28 keys**, and three
blocks are **100% fed**. A one-game denominator is not a rate.

Encoded as `MIN_GAMES_FOR_A_RATE = 8` → reports **UNMEASURED**, never 0%.

**Both errors are the same failure:** a reading that LOOKS like the finding you
went in expecting. The empty payload was real, so "everything reads 0%" felt
like confirmation, and "one site is wired" felt like a reasonable exception.
**A result that agrees with your hypothesis still has to survive the question of
what would make the instrument produce it spuriously.**

## 2026-08-18 — RULE: a zero from a LOCAL checkout is a statement about the mirror, never about production. I filed one as a defect

**Lane `football-model-owner`. Caught by the repo's own rule, one step after I
had already written the wrong claim into `todo.md` and a reference doc.**

`FootballSimulationAdapter(sport="ncaaf").load_features(...)` returned **0 games**
locally, on both 2025 and 2026, week 1. I recorded that as `#458`: *"NCAAF's
feature loader returns ZERO games"* — phrased as a production defect, with the
season opener eleven days out.

`GET /ncaaf/api/cards?week=1` on production serves **16 games**, all of them real
games on the CFBD 2026 wk1 slate. **The loader is fine. My checkout is empty.**

CLAUDE.md says this in as many words — *"Don't diagnose 'missing data' from the
local checkout — check production first"* — and I had read it that same session,
in the same session that also re-derived the `data/**` lossy-mirror rule for the
football artifact tree. Knowing the rule did not stop me applying it late.

### Why it slipped through, which is the transferable part

The local zero **agreed with a finding I had already confirmed by other means.**
NCAAF genuinely does produce no model output — every one of those 16 served games
carries an all-null `predictions` block. So "NCAAF returns nothing" was TRUE at
the level I cared about, and a second reading that also said "nothing" read as
corroboration rather than as a different measurement of a different thing.

**Two true statements about different subjects, collapsed into one wrong one:**
- *production serves NCAAF games with no model attached* — true, and the real bug
- *my checkout has no NCAAF game data* — true, and completely uninteresting

The wrong version named the wrong subsystem. The remedies are opposite: one is a
missing env var on refresh-worker, the other is `git`-mirror coverage on my
laptop. **A correct-sounding conclusion assembled from two correct observations
is the hardest kind to catch, because every input checks out.**

**RULE:** before any claim of the form "X produces nothing", state which
SUBSTRATE was read — served payload, worker disk, or local checkout — and say so
in the claim itself. A claim that does not name its substrate is not yet a claim.
Where the substrate is the local checkout, it can only support a statement about
the checkout.

Encoded: `scripts/football_sim_input_checklist.py` level 2 now emits
*"loader returned N games FROM THIS CHECKOUT ... `data/**` is a lossy mirror --
this says nothing about production. Check the served board: GET
/<sport>/api/cards?week=N"* instead of a bare count.

**Related and already in this file:** *a rate, not a count* and *instrument
blindness*. This is their sibling — **an instrument pointed at the wrong
substrate**, which reads perfectly and answers a question nobody asked.


## 2026-08-18 — RULE: a guard that gates on IDENTITY fails to a total block when the identity holder disappears. Gate on STATE

**The failure.** `deploy-guard.py` allowed a deploy when
`session_id in .syndicate/coordinator.id`. The coordinator was a session. The
session was archived. From that moment the allow-branch was **unreachable**, and
the guard blocked every deploy from every session — while presenting itself as a
routing rule ("file a request, carry on"). Two requests sat in
`deploy/requests/`, `deploy/grants/` was empty, and an 11-day clock ran on the
NCAAF opener. Nobody had disabled anything; the predicate simply stopped having
a true value.

**Why it is worth a rule.** This is not "the coordinator was a bad idea". The
role's own defences were well built and each fixed a real bug — the register was
a LIST because a resume reassigns the id, and that fix worked. It still died,
because every defence protected against the id CHANGING and none against the
holder CEASING TO EXIST. A liveness assumption that is never stated is never
tested.

**The tell, generalised:** ask of any guard, *what makes the allow-branch
reachable, and who has to be alive for that to be true?* If the answer names a
process, a session, or a person, the guard has an outage mode that looks exactly
like enforcement. Identity predicates have this shape. State predicates do not:
a file on disk with an expiry is readable by anyone, at any time, and frees
itself when its writer dies.

**What replaced it,** as the worked example: an unexpired `deploy_claim`
(`O_CREAT|O_EXCL`, 45-min TTL, `--force` to break a dead holder's) plus a
`deploy_preflight` receipt reading `CLEAR` within 15 min. Same invariant, no
liveness assumption.

**Three sub-rules that fell out of the rewrite, each its own near-miss:**

- **A guard must not match its own subject matter as a substring.** The old
  pattern was the bare string of the entrypoint's filename, so it refused
  `sed -n '1,22p'` on that file — and refused the heredoc that would have fixed
  it, because the replacement text quotes the name. A guard that blocks reading
  and editing itself cannot be repaired from inside the system it guards. Match
  INVOCATION (a runner token in the same command segment), never mention.
- **Aliases split a lock in two.** `deploy_claim.py` accepts both `web` and
  `syndicate` for one service. Two sessions claiming different aliases would each
  read as "unclaimed by a peer" and both proceed — the exact collision the lock
  exists to prevent. Every lookup must scan the whole alias set.
- **When several receipts could answer, take the NEWEST, not the best.** Scanning
  aliases for "any receipt that says CLEAR" lets a stale CLEAR outvote a fresh
  HOLD. Select by timestamp first, judge second. Same reason
  `deploy_preflight.py` now writes a receipt on EVERY verdict and not only on
  CLEAR: a HOLD must actively REVOKE the CLEAR before it, or the guard reads a
  world that has already changed.

**Related and already in this file:** *unknown must not default permissive* —
this is its inverse and its equal, **a guard whose unknown defaults to BLOCKING
EVERYTHING**. Both come from not asking what the predicate does when its inputs
go missing.

## 2026-08-18 — CHECK WHETHER A FIELD EXISTS BEFORE DECLARING IT

Cost: three wrong public claims in a row, in alternating directions.

I added `two_strike_whiff_boost: float = 1.0` to `PitchModelConfig`. **It already
existed at `:206` with a tuned default of 0.0409, and was already consumed at
`:639`.** Python takes the LAST definition, so 0.0409 shadowed my 1.0 — and my
new application multiplied it a second time. Passing the supposed no-op `1.0`
therefore raised two-strike whiffs **24x and squared the effect**.

**No error, no warning, no test failure.** The symptom was that an override dict
of 1.0s produced different results from an empty dict.

**RULE: grep the name before declaring a field.** One grep would have shown both
the existing field AND that the engine already had the mechanism I was about to
"add" — which also made my premise ("no scalar can express this") false.

**THE EXPENSIVE PART WAS THE INFERENCE, NOT THE BUG.** From one bad reading I
concluded the *harness* was unsound and publicly retracted a CORRECT result. The
duplicate was introduced AFTER the runs I invalidated. **When a measurement
contradicts an earlier one, suspect the thing you changed most recently before
suspecting the instrument** — I had edited the engine minutes earlier and blamed
a script I had not touched.

**Guard that now exists:** any tuning script runs an EQUIVALENCE CHECK first —
empty override dict vs a dict of explicit no-op values must agree exactly. It is
two lines and it localises this class of fault immediately.


---

## 2026-08-18 — OVERTURNED: "the ledger files were fine, just big" — session `football-model-owner`

**What was believed.** The session-start digest measured `LEDGER OVER BUDGET`
and nothing else, which encoded a belief that SIZE was the ledgers' problem.

**What is true.** Size and coherence are independent, and coherence was never
measured. Measured this session: `#447` existed in NEITHER `todo.md` nor
`todo_closed.md`; `lanes.md` had 7 slugs carrying two OPEN blocks each (two
sessions could each read themselves as the holder of the same files); `state.md`
had 5 sections stacked onto 2 subjects.

**Why it went unnoticed for so long, which is the useful part.** `state.md` had
NO DUPLICATE TITLES, and that read as health. It is trivially true when sections
are titled by their DATE. A clean reading from an instrument that cannot express
the failure is not evidence of health — the same shape as
`feedback_instrument_blindness`, recurring on a different instrument.

**Rule.** A ledger needs an IDENTITY before it can be checked. `todo.md` has ids,
`lanes.md` has slugs, `state.md` now has `## [subject-slug]`. Enforced in CI and
reported at session start.

---

## 2026-08-18 — OVERTURNED: "a guard that is present is a guard that is working" — session `football-model-owner`

**Two instances in one session, on two different hooks.**

1. **`deploy-guard.py` gated on `session_id in coordinator.id`.** Once the
   coordinator session was archived that predicate had NO TRUE VALUE, so the
   guard was not a throttle but a total block on all deploys, silently. Two
   deploy requests sat queued and `deploy/grants/` was empty.
2. **`lane-guard.py` matched only `- Files:`, never `- **Files (...):**`.** Five
   lanes declared paths that NO HOOK COULD SEE — the ledger said a file was held
   and the guard let anyone edit it. Claims went 52 -> 80 when fixed.

**The common shape.** Both guards ran, exited cleanly, and reported nothing
wrong. Presence and a zero exit are not evidence of enforcement. Ask what makes
the guard SAY NO, and construct that input.

**Applied, not just recorded:** all three ledger checkers were then run against
deliberately corrupted copies and each exits 1 before being wired into CI.

---

## 2026-08-18 — FORBIDDEN: never apply a transform to a shared file by patching the transform's own source with `str.replace` — session `football-model-owner`

**What happened.** To re-run a collapse against the WORKING copy instead of
`HEAD`, I rewrote the script's input line with `str.replace` and `exec`'d it. The
replacement DID NOT MATCH — whitespace differed — so the "worktree rebuild"
silently re-ran the HEAD version, and writing the result destroyed another
session's 31 uncommitted lines, including a deployed-and-measured NCAAF result.

**The tell that was available and that I did read, late:** both runs produced
files of EXACTLY 2202 lines. Identical output from supposedly different input is
proof the input did not change.

**Recovered** from unreachable blob `936d7e6a`, which existed only because of an
earlier accidental `git add`. An exhaustive `git fsck` sweep later confirmed it
was the ONLY other version in the object store.

**Rule.** Parameterise a script with `sys.argv` and ASSERT the input loaded
(`assert head.count("
") > 2000`). Never mutate source text to change behaviour.
A silent no-op replace is indistinguishable from success.

## 2026-08-18 — RULE: before wiring ANY feature into a model, check whether the feature is computed FROM THE THING BEING PREDICTED. Ask what WINDOW it covers, not what it is named.

**Evidence.** `smartsim2` reads 33 alias-terms out of `feature_generation_payload`
and no production entrypoint passes it. Wiring it moved **21 of 21** drive-prior
fields and **1.125 pts** of margin — a large, clean, entirely spurious effect.

`build_nflverse_game_metrics` computes `home_offensive_epa`, `success_rate`,
`pass_rate` and the rest from **the game being predicted**. `_match_game_rows`
(`nflverse_ingestion.py:151`) filters play-by-play to rows where
`home_team == home AND away_team == away` for that season and week — one game's
plays. `home_defensive_epa` is literally the opponent's offensive EPA in the
same game.

**The falsification test, stated before running it:** prior-form team strength
should correlate with a single NFL game's final margin at roughly **r = 0.3–0.5**;
in-game EPA would exceed **0.8**, because EPA accumulated during a game nearly
restates who won it. **Measured over 285 games of 2023: r = 0.988.**

### Why every other check passed

The field NAMES are perfectly reasonable — `offensive_epa`, `success_rate`,
`pass_rate_over_expectation` are exactly what a legitimate prior-form feature set
would be called. **Population was 100%.** The input checklist passed them as FED.
The reachability test passed (`off != on`). Unit tests passed. **Nothing in this
repo could distinguish "team EPA" from "team EPA in this game" — because the
distinction is not in the name, the type, the population rate, or the code that
consumes it. It is only in the WINDOW the producer selected over.**

### The rule going forward

- **For every model input, name the window explicitly**: as-of-before-kickoff,
  season-to-date-excluding-this-game, or in-game. If the answer is not written
  down next to the field, it has not been established.
- **A population checklist cannot detect leakage** — a leaked field is 100%
  populated, by construction, and looks maximally healthy.
- **Run the correlation-with-outcome test on any feature block before wiring
  it.** It is two minutes of work and it is the only check here that fires.
- **An effect that looks large and clean on first wiring is a leakage SUSPECT,
  not a win.** The 1.125-pt movement was the tell, read the wrong way round.
- Same family as *"a LEAKED backtest number is an UPPER BOUND, not merely an
  untrustworthy one"* (2026-08-17) and the soccer
  `*_backtest_*.csv` NOT-CITABLE finding — but earlier in the pipeline: this one
  would have leaked into the MODEL, not merely into a report about it.

**Cost of catching it here rather than later:** the prereg was written, the power
analysis done, and a **19,959-credit** odds backfill spent to power a
market-relative arm. All of it carries over. Had the builder not been read before
wiring, the output would have been a leaked model with a spectacular backtest.

## 2026-08-18 — A TRUNCATED READING IS NOT A COMPLETE ONE

Five wrong claims in one session, **every one from treating a partial or
authoritative-looking reading as the whole picture.** Not one came from a
measurement I took carefully.

    a dated deploy record       read as CURRENT STATE      -> told 2 sessions the ledger was stale
    `git grep -l ... | head -4` read as EXHAUSTIVE         -> "the emitter was deleted"; it was at :1952
    `pattern=<bare filename>`   read as PROOF OF ABSENCE   -> count:0 for a file that was present
    one seed at 120 sims        read as A RESULT           -> "4 of 4 better"; reversed at seed 2
    another lane's aside        read as A ROOT CAUSE       -> nearly shipped a useless `psutil` dep

**RULE: before reporting a null or an absence, prove the query can return a
non-null.** A control that must succeed. `pattern=*conditional_mix*` returns
count:1 where `pattern=conditional_mix_2026.json` returns count:0 for the SAME
file — and I ran the bad form five times and quoted it to two other sessions.

**RULE: `head` on a grep whose purpose is "does this exist anywhere" is a BUG.**
Count first, or drop the pipe.

**THE EXPENSIVE PART IS THE INFERENCE, NOT THE READING.** Three times a single
bad reading became a sweeping verdict — "the harness is unsound", "the emitter
was deleted", "no session can get a CLEAR preflight for any service" — and twice
I broadcast it before checking. **Scope a conclusion to the evidence's actual
reach: one service is not all services, one seed is not an effect, one file is
not a codebase.**

**What held:** everything I re-derived. The 403->200 cutover watched through,
the merge-base ancestry, the artifacts read back BY CONTENT. **The failures were
uniformly in what I did NOT re-derive.**

## 2026-08-18 — A STALE-BUT-"RUNNING" SESSION IS INVISIBLE TO EVERY ORPHAN CHECK

`refresh-worker-oom-recurrence` held a documented deploy hold on refresh-worker.
Its owner had not moved in **43 hours** while the roster reported
`isRunning: true`.

**It survived BOTH checks, for opposite reasons:**
- the **orphan sweep** releases lanes whose session is ARCHIVED — this one is not
  archived, so it was skipped;
- a **liveness read** shows `isRunning: true` — so it looks owned.

**Neither check asks the question that matters: WHEN DID IT LAST DO ANYTHING.**
`lanes.md:51` had already recorded "flagged running (stale 40h)" and nothing
acted on it, because no rule consumes that field.

**RULE: treat `isRunning` as a CLAIM, not a reading. Judge ownership by
`lastActivityAt`.** A hold whose owner has been silent for tens of hours is
orphaned regardless of its flag, and blocks real work until someone adjudicates
it. This is the same shape as
[[feedback_session_roster_hides_archived]] — "ended" and "never existed" look
identical — with a third state now added: **"claims to be running and is not."**

**Cost here:** I nearly deployed straight through a documented hold because the
mechanical locks were free (claim available, preflight reachable) and I read
*free locks as permission*. The policy hold lives in `lanes.md` and nothing
mechanical enforces it. **Read the lane ledger for the SERVICE before deploying,
not just the locks.**
