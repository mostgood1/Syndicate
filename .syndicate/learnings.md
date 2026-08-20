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

## Index — 428 rules `[generated]`

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

- **Believed:** the joiner's first same-book CLV, `avg_clv_pct = -5.215` over 25 rows (beat-close 9/25), was the first honest measurement of our closing-line value. It was the number the whole lane existed to produce.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-14 — a control with no baseline is a guess wearing a control's clothes

- **2023-2025**), unrelated to the MLB window (2026-08-01..08-14), and they predate the deploy. **I had baselined the MLB props before deploying and never baselined non-mlb** — so the control's expected value was assumed, not measured.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-14 — read the system's clock, not the wall clock

- The rule going forward: **before firing a pinned deploy, re-read the service's live commit AND check for an in-flight deploy; then pin onto whatever is live at that moment, not onto what was live when the branch was built.** A pinned branch is a snapshot with an expiry date, and the expiry is the next deploy by anyone. Where two lanes are shipping the same service, stack — cherry-pick onto their commit — rather than racing from a shared base.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-15 — RULE: WEB DOES NOT RUN `main`. Parent a deploy on the LIVE SHA.

- **The rule going forward.**
- *(evidence in `learnings_evidence.md`)*

## 2026-08-15 — A CADENCE IS A DISTRIBUTION ACROSS REGIMES, NOT A CONSTANT

- **The belief.** "MLB quote capture runs on a metronomic ~121.6-minute beat." It sat in `state.md` with a proper measurement behind it (seven captures in 18h, read from the artifact rather than the logs — good method), it was carried into the program plan as a hard floor on the Tier 5 measurement, and it was the premise of a standing freeze on 23 movement implementations, `movement_velocity` and the steam detector.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-15 — ANCESTRY OF `origin/main` IS NOT DEPLOYMENT; READ THE DEPLOYED TREE

- **The near-miss.** Asked whether the per-sport pregame cooldown had shipped, the first check was `git merge-base --is-ancestor ea8fad58 origin/main` → **yes**. On a repo where `autoDeploy = no`, that answer means nothing about production, and taken alone it would have reported a fix as live that is not.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-15 — RULE: a "baseline" is a FILE you diffed, not a number you quoted

- **The rule going forward:** a shared stylesheet exists precisely so one class renders in more than one place, so **one sample per class is not a measurement of that class** — key the table by surface and report a class whose computed value differs across surfaces as CONFLATED rather than collapsing it to its first hit. `scripts/ui_layout_probe.py` now does this and the whole story is in `docs/reports/ui_audit_2026_08_14/README.md`, because the wrong number outlived the probe that produced it and got written into two plans.
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
- **Overturned belief:** that confirming a fix is present in the deployed code means the observed behaviour goes through it.
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
- I wrote a pager that walked a time window by advancing `startTime` past the last line of each page. The API does not work that way: it returns the newest `limit` lines inside `[startTime, endTime]`, presented oldest-first (`deploy_preflight. newest_log`'s own docstring says so and I did not read it). Advancing startTime re-reads the same tail and terminates.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-14 — a before/after is void if the change moved work INSIDE the measured span
- The `#387` streaming cutover was measured as "peak anon during `OVERVIEW_SPORT_BEGIN mlb` -> pass end". The change also moves per-sport candidate collection INTO that pass. So the after-span contains work the before-span did not, and "peak went UP" is partly definitional, not behavioural.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-14 — "it cannot fit" from one sample, when the same shape runs fine twice
- A handoff carried, as its single next action, a fix whose justification was one OOM: eight sports hydrated at once, "peak = SUM is sufficient on its own to cross 4GiB", "the floor plays no part". I deployed it, then measured two pre-deploy passes of the IDENTICAL shape from the same evening: 8 sports hydrated, peaks 804MB and 613MB, 15-20% of the ceiling, no death.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-15 — FORBIDDEN: never treat equality of a LABEL as identity of a BET

- **The rule going forward:** every memory number carries a SCOPE — container, process, or thread — and only same-scope numbers may be subtracted. Write the scope next to the figure. `memory.current`/`anon` and `oomKilled` are container; `smaps`, `PYMALLOC_STATS`, `HEAP_CENSUS`, `mallinfo` and `getsizeof` are process; a container with children makes them differ by hundreds of MB.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-16 — FORBIDDEN: never deploy on `check_deploy_safety.py` alone. It said CLEAR while three jobs were running on the service.

- **Measured 2026-08-16 00:13Z on refresh-worker.** `check_deploy_safety.py`
- *(evidence in `learnings_evidence.md`)*

## 2026-08-16 — FORBIDDEN: a wait loop must gate on an AFFIRMATIVE success token, never on the absence of a failure string

- *Full working in `learnings_evidence.md` under this heading.*
- *(evidence in `learnings_evidence.md`)*

## 2026-08-15 — FORBIDDEN: never read a joiner zero as a fact about the world until the reader is shown to SEE the data

- **What happened.** The rule was written in advance, in good faith, and was wrong. `same_book_n=0` came back for all 8 sports. The truth: `/api/ops/clv/report` runs on **web**, `load_openings` is a `path.exists()` on a local file, and web held **0 bytes** of the ledger while refresh-worker had **490 openings recorded for that same date**. The endpoint returned `ok: true` throughout. Shipping one allowlist line moved `same_book_n` **0 → 144** with **no change to odds history at all**. Breadth constrains `resolved` (`no_market_in_history: 172`), never `same_book_n`.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-15 — FORBIDDEN: shipping a verification you have not falsified. THREE failed checks in one night, zero failed fixes

- **The rule.** Before arming any check, ask the falsification question about the CHECK, not the fix: *what reading would this produce if the fix worked perfectly?* If that equals the failure reading, the check is broken. Then:
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

- **Measured 2026-08-15/16 on live-odds-worker.** Its claim advertised `target=49797f4b`, and `49797f4b` genuinely carried the clamp fix — verified by reading the code, not just counting a grep. I concluded twice, in writing, that the service "needs nothing".
- *(evidence in `learnings_evidence.md`)*

## 2026-08-15 — RULE: merge in the object database when the shared tree is dirty

- **The rule going forward:** on this repo a reconcile does **not** need a checkout. `git merge-tree --write-tree` + temp index + `commit-tree` + `push <sha>:main` merges with **zero** working-tree writes, so concurrent sessions' edits cannot be refused, overwritten, or staged by accident.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-15 — RULE: resolve a ledger conflict by REPLACING the stale entry, never by appending

- **The rule going forward:** when both sides changed a lane, the merge is not "keep both" — a union leaves the file **asserting two contradictory statuses** for one slug and nothing flags it. Find the slug's other occurrence and overwrite the stale header in place; demote the old body to marked history.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-15 — RULE: merge in the object database when the shared tree is dirty

- **The rule going forward:** on this repo a reconcile does **not** need a checkout. `git merge-tree --write-tree` + temp index + `commit-tree` + `push <sha>:main` merges with **zero** working-tree writes, so concurrent sessions' edits cannot be refused, overwritten, or staged by accident.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-15 — RULE: resolve a ledger conflict by REPLACING the stale entry, never by appending

- **The rule going forward:** when both sides changed a lane, the merge is not "keep both" — a union leaves the file **asserting two contradictory statuses** for one slug and nothing flags it. Find the slug's other occurrence and overwrite the stale header in place; demote the old body to marked history.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-16 — FORBIDDEN: reading a git error as noise from the NEXT command when it names the file the PREVIOUS one staged

- **Git told me, in the same output as the push.** The command chained `commit-tree`, `push`, then `git reset`, and printed:
- *(evidence in `learnings_evidence.md`)*

## 2026-08-16 — RULE: fix a bad commit MESSAGE by rebuilding the commit from its own tree, not by `--amend` and not by living with it

- **What we believed:** the shared-tree recipe offered two options for a wrong commit message — `git commit --amend -- <paths>` (dangerous: without a pathspec it commits the whole shared index, and it once swallowed another session's 22 staged files) or *"accept the message and move on."* Written as a binary, so a message defect looked like something you either risk a disaster over or simply eat.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-16 — a per-row field read off ONE row and generalised to all of them

- **Overturned:** my own same-day claim that "every exercised `win_prob` run is on an OLDER commit", which I wrote into `deploys.md` and `state.md` and pushed, along with a discriminator ("one `rows>0` on a current commit") for resolving it.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-16 — OVERTURNED: a pinned SHA identifies deployed CODE

- **The belief.** Two scheduled measurement tasks pinned their comparison with "if the live SHA is no longer `d72d670c`, the comparison is invalid — a different SHA may have reverted the fixes." That reads as rigour. It is a string equality test standing in for a question about content.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-16 — CORRECTED IN-SESSION: at-cap is not a kill

- *Full working in `learnings_evidence.md` under this heading.*
- *(evidence in `learnings_evidence.md`)*

## 2026-08-16 — NEAR-MISS: verifying against a ref NAME is not verifying

- **What almost shipped.** A three-file ledger commit that also silently reverted another session's in-flight feature: `book_shortlist.py` −129, `layer2_board.py` −172, `test_layer2_bettable_books_and_labels.py` −224, plus `deploys.md` −43 and `lanes.md` −75. It would have been a valid commit, pushed cleanly, with a message about ledger writes.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-16 — NARROWING AN INSTRUMENT TO A MEASURED DISTRIBUTION BUILDS IN A BLIND SPOT

- **What I did, and it looked like good work.** A census said **41 of 42**
- *(evidence in `learnings_evidence.md`)*

## 2026-08-16 — FORBIDDEN: never test what is deployed with `git merge-base --is-ancestor`. It answers a question about HISTORY; deployment is a question about CONTENT.

- `edbbee9d` (spread-sign fix) is **NOT an ancestor** of live `97491161` — and the fix **is running**. `git show 97491161:...layer2_board.py` returns the same 3 occurrences as `main`.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-16 — FORBIDDEN: never use a fresh `git worktree` as a test baseline for anything that reads `data/`.

- *Full working in `learnings_evidence.md` under this heading.*
- *(evidence in `learnings_evidence.md`)*

## 2026-08-16 — the shared-index revert fired TWICE against one session, and the second time it was armed AFTER a clean push.

- *Full working in `learnings_evidence.md` under this heading.*
- *(evidence in `learnings_evidence.md`)*

## 2026-08-16 — a mirrored row set makes a wrong join look like a UNIFORM defect, which is the most convincing kind.

- **What happened.** To verify an edge-attribution fix before deploying, I fetched the real served payloads, filtered to the exact rows that were serving a blank `Edge` with no reason, and ran the changed helper over them. Result: **287 of 287 attributed, 0 unattributed.** I wrote that into `deploys.md` as the verification and deployed.
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

- **What happened:** an isolated-index commit of 3 ledger files produced a commit of **14 files** that rendered every path it had not re-read as a DELETION — including this session's own `scripts/fetch_nfl_pbp.py` (0/276), `run_refresh_worker.py` (0/193) and another session's `syndicate/features/soccer/cards.py` (0/64).
- *(evidence in `learnings_evidence.md`)*

## 2026-08-16 — FORBIDDEN: letting a FITTED MODEL judge, when a model-free measurement of the same thing is available

- *(the heading states the rule; full working in `learnings_evidence.md`)*
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

- *(the heading states the rule; full working in `learnings_evidence.md`)*
- *(evidence in `learnings_evidence.md`)*

## 2026-08-16 — FORBIDDEN: curating a deploy branch BY FILE without checking the call boundary you just cut

- *(the heading states the rule; full working in `learnings_evidence.md`)*
- *(evidence in `learnings_evidence.md`)*

## 2026-08-16 — FORBIDDEN: computing a RATE or a COUNT from `scripts/render_logs.py`

- *Full working in `learnings_evidence.md` under this heading.*
- *(evidence in `learnings_evidence.md`)*

## 2026-08-16 - FORBIDDEN: never join a CHANGE metric on a key that contains the changing fields. The metric becomes conditioned on the absence of what it measures.

- *Full working in `learnings_evidence.md` under this heading.*
- *(evidence in `learnings_evidence.md`)*

## 2026-08-16 - a blob hash written into a ledger is a SNAPSHOT, not a lease.

- **re-read the blobs before cutting rather than trusting the numbers printed in it**.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-16 — ASK-ANSWER-SUBSTANCE CHECKPOINT 2: five beliefs overturned

- **Sorting orders a pool; it does not decline to publish one.** Necessary, never sufficient. **General form: a fix aimed at the ORDER of bad output does not stop the output, and the note it leaves behind reads like a closed case.** When a past note says "fixed by ranking", check whether anything filters.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-16 — ASK-ANSWER-SUBSTANCE CHECKPOINT 3: two more

- **The rule: when a metric moves across your change, diff the code path the metric actually reads before attributing it — to yourself OR to anyone else.** Both directions of misattribution are expensive. Claiming a regression you did not cause sends the next session hunting in the wrong file; claiming innocence you have not checked is worse. The check is one `git diff` scoped to the path, and it takes a minute.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-16 - FORBIDDEN: a loose join key makes a row VISIBLE. It does not make the row's values COMPARABLE. Those are two decisions and I made only one.

- *Full working in `learnings_evidence.md` under this heading.*
- *(evidence in `learnings_evidence.md`)*

## 2026-08-16 - a test I wrote can encode the belief that production later disproves, and then it defends the bug.

- *(the heading states the rule; full working in `learnings_evidence.md`)*
- *(evidence in `learnings_evidence.md`)*

## 2026-08-16 — SCOPE NOTE on "blob-staging needs `--path`": true in general, WRONG for this repo

- *Full working in `learnings_evidence.md` under this heading.*
- *(evidence in `learnings_evidence.md`)*

## 2026-08-16 - FORBIDDEN: a verifier that cannot FAIL cannot PASS. State the denominator every assertion needs, or it will report an empty population as success.

- *(the heading states the rule; full working in `learnings_evidence.md`)*
- *(evidence in `learnings_evidence.md`)*

## 2026-08-16 — FORBIDDEN: reading `$?` after a pipeline. TWICE IN ONE HOUR, two different tools, both times the wrong answer was the REASSURING one

- *(the heading states the rule; full working in `learnings_evidence.md`)*
- *(evidence in `learnings_evidence.md`)*

## 2026-08-16 — OVERRIDE, LOGGED: an unattended session was authorised by the user to fire this deploy

- *(the heading states the rule; full working in `learnings_evidence.md`)*
- *(evidence in `learnings_evidence.md`)*

## 2026-08-16 — CORRECTION: the shared index CHURNS, it does not accumulate — and staged content is not the alarm

- **Extends the same-day rule about slug-level ledger checks.** That one framed whole-file rewrites from stale in-memory copies as a `.syndicate/**` hazard. Measured three hours later: the same mechanism reverted a **source file**.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-16 — ASK-ANSWER-SUBSTANCE CHECKPOINT 4: fixing a fix, and two bad inferences

- **The rule going forward:** a conditioning variable must be derivable from observable state ALONE. When a payload mixes state and prediction, split them explicitly and say so on the record. **The test for this is cheap and worth writing:** assert the model's field names are absent from the shape.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-17 — FORBIDDEN: deploying `main`'s TREE to a service that runs a curated deploy branch

- **The tell is per-file, and it is cheap:** for each conflicted path compute `live-only` and `main-only` line counts. **`main-only == 0` means production is AHEAD there** and taking main is a revert. Measured tonight on `refresh_nba_oddsapi_props.py`, `refresh_wnba_oddsapi_props.py` and `test_win_prob_null_counter.py` — three files, on two separate services, where the obvious move was the wrong one.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-17 — FORBIDDEN: gating a deploy on "no jobs running" for a continuously-busy worker

- **Worse, the gate measures the wrong moment.** Render BUILDS first and stops the service after (`build_started 21:13:49 -> build_ended 21:18:29 -> live 21:21:05`). What dies is whatever runs at the STOP, ~5 minutes after the trigger — not what preflight saw when you fired.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-17 — FORBIDDEN: resolving the SAME symbolic ref in two git calls. A stale tree on a current parent is a fast-forward, and git cannot tell it from a deliberate revert.

- *(the heading states the rule; full working in `learnings_evidence.md`)*
- *(evidence in `learnings_evidence.md`)*

## 2026-08-16 — FORBIDDEN: attributing an excursion with a field that is not THREAD-scoped. A process-global "last stage" names the last thread to speak, not the one allocating.

- **The rule going forward:** before concluding the DATA is wrong, scan the residual against the fitted value. Structure there indicts the model.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-16 — FORBIDDEN: instrumenting a WRAPPER when the hot path has siblings that reach the same work directly. Twice in one night.

- **The rule going forward — the recipe, because it worked and is reusable:**
- *(evidence in `learnings_evidence.md`)*

## 2026-08-17 — RULE: the em-dash in a lane header is SYNTAX, not punctuation. A hyphen header is an UNGUARDED lane

- **Evidence.** `wnba-fixture-identity` was opened by a live session with ASCII hyphens: `### wnba-fixture-identity - OPEN - **...`. `lane-guard.py` parses `^###\s+(\S+)\s+—\s*([^—]*)` and requires U+2014, so the header did not parse at all. Consequences, all silent: the lane's three claimed files were unguarded (one of them contended with a lane closed minutes earlier), and the session-start digest did not list the lane as OPEN, so an arriving session saw no claim on those paths. Found 2026-08-17 12:3x CDT by the `ledger-sweep` lane while verifying something else; the hook had been printing `(1 lane header(s) have no parseable status and are NOT guarded)` and nobody had read it as naming a specific live lane.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-17 — FORBIDDEN: diagnosing from FILTERED log projections. Six wrong attributions, one question, and the answer was in the lines I was truncating.

- **Each filter encoded the hypothesis I was trying to test.** A `text=` query returns only what I already believed mattered; stripping the memory lines removed the only rows carrying `seconds_since_stage` and `climb_mb_per_s`; truncation hid the discriminating field. The phantom "third ledger pass" was a filtered window that began mid-scan and invented a caller that never existed.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-17 — RULE: committing through an ISOLATED index ARMS the shared index with a revert of that commit. Disarm after, not just before

- **The recipe is still right; it has a second half nobody had written down.**
- *(evidence in `learnings_evidence.md`)*

## 2026-08-17 — OVERTURNED: "a statistical win on a sim parameter can be graded by betting hit rate on the same sample"

- **Belief going in:** the overrides file records `starter_tto_quality_scaling`
- *(evidence in `learnings_evidence.md`)*

## 2026-08-17 — RULE: before building a fix, check whether it was already considered and REJECTED in the code you are about to edit

- **The rule going forward:** **an override is not an override until it has been exercised through the real entry point.** For a hook, that means over stdin as a payload — not by setting the variable in the test process, which is a different environment than any user of the documented recipe will ever have. Corollary: the test that would have caught this is the one that runs the guard's own printed text verbatim. If a tool prints instructions, those instructions are an interface and belong in the suite.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-17 — RULE: score a DISTRIBUTIONAL forecast with a distributional baseline. A point test on a distribution is the wrong instrument, even when it agrees.

- **What happened.** Phase 7's whole purpose was to build a proper scoring rule for projections (CRPS, bias/dispersion). I built it, used it to find a real defect — the MLB F5 starter leash, dispersion 1.002 vs a 0.7979 target — and then decided whether the model had SKILL by comparing its **mean absolute error to a constant point prediction**. That verdict went into `state.md`.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-17 — RULE: a LEAKED backtest number is an UPPER BOUND, not merely an untrustworthy one

- **Standing practice here is to mark a leaky backtest "not citable" and stop.**
- *(evidence in `learnings_evidence.md`)*

## 2026-08-17 — RULE: a PATHSPEC commit is the default; the isolated index is the FALLBACK. The latter arms a revert every time

- **Relayed by `commit-guard-blind-to-own-recipe`, owed to and written by the coordinator.** That lane measured the two forms against a repo whose index held a revert of `A.txt` and a deletion of `C.txt`:
- *(evidence in `learnings_evidence.md`)*

## 2026-08-17 — RULE: never close a queue item in BULK. Close each against its own evidence

- **I did this to a live deploy request within hours of documenting the same failure shape.** After deploying three requests I moved *everything* in `.syndicate/deploy/requests/` to `done/` and stamped it all "EXECUTED by the coordinator". A fourth request (`soccer-layer2-dates`) had been filed at 20:20Z, after that batch was scoped. It was never deployed — its commits were not even pushed — and it spent that time marked delivered.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-17 — RULE: an aggregate dispersion check cannot see an UNINFORMATIVE CENTRE

- **What happened.** Phase 7's bias/dispersion decomposition reported MLB pitcher outs at **dispersion 0.791 against a 0.798 target** — as close to perfect as that metric gets. I read it as "the shape is right, only the location is off" and went looking for a calibration fix.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-17 — RULE: a signature change needs a CALLER CENSUS, not a spot-check of the caller you just edited

- **Evidence.** `_load_team_ratings` gained a required third parameter (`as_of`, audit §7 #6). The author updated the caller inside the same module and wrote a test for it:
- *(evidence in `learnings_evidence.md`)*

## 2026-08-17 — RULE: a falsified prediction LOCALISES a bug; treat it as a measurement, not a miss

- **Three predictions were falsified today and each was worth more than the confirmation would have been.**
- *(evidence in `learnings_evidence.md`)*

## 2026-08-17 — A SIGNATURE CHANGE NEEDS A CALLER CENSUS, AND THE CALLER YOU CANNOT REACH IS THE ONE THAT BREAKS

- **Why it survived â€” three independent covers, and each is a general shape:**
- *(evidence in `learnings_evidence.md`)*

## 2026-08-17 — TEST DEPLOYMENT BY CONTENT, NEVER BY ANCESTRY OR BY A SHARED SYMBOL

- **False negative.** live-odds-worker deployed `7470939b`.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-17 — RULE: the FIRST test for any flagged feature is "does enabling it change anything"

- **I built three inert things today.** Not three bugs — three pieces of work that existed, looked complete, passed their obvious tests, and did nothing:
- *(evidence in `learnings_evidence.md`)*

## 2026-08-17 — RULE: a watcher that reports a PEAK of ZERO has not measured a peak. Zero samples is NO DATA, never "clean"

- **I wrote a memory watcher whose entire purpose was to catch an OOM I had predicted, and it reported `Window clean. Peak live-odds-worker memory 0.0% of 2048MB` while the service was at 85.3% and climbing.** Had I trusted it, the rollback would not have happened. It was caught only because the user asked me to check the number by hand.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-17 — RULE: a feature can be unfed at the DATA layer, and it looks nothing like a bug

- **Standing rules here cover code that is present-but-unreachable.** This is the same failure one level down: code that IS reached, with inputs that are empty.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-17 — RULE: rank modelling gaps by how much the dimension DISCRIMINATES, not by how complete its machinery is

- **What I did.** Researching what the MLB sim was missing, I found pitch-type effectiveness fully built — model fields, four consumption sites, a loader, a cache, a fetch tool — and **0% populated**. I ranked it "where a market beat is most likely" *because everything existed and only needed wiring*, and spent **314 network calls and ~2 hours** filling it.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-17 — RULE: you cannot add a MECHANISM to a CALIBRATED engine without re-fitting its rates

- **Measured, 2x2 factorial, 4 of 4 markets:** adding position-player substitution and pitch-type splits to the MLB sim produced a **NEGATIVE interaction, mean −0.00331**. On RBIs each feature alone helped (−0.00573, −0.00271) and together they gained almost nothing (−0.00046). **On runs, both-on was WORSE than neither.**
- *(evidence in `learnings_evidence.md`)*

## 2026-08-17 — RULE: "the model is absent" needs a FIELD AUDIT, not a name search

- **I published a research document stating the MLB sim has "no batted-ball type model — no GB/FB/LD". It was wrong.** The model exists and `simulate.py:1120-1136` consumes it for both batter and pitcher:
- *(evidence in `learnings_evidence.md`)*

## 2026-08-17 — FOUR DEFECTS IN ONE SESSION SHARED ONE SHAPE: THE ERROR PATH RENDERED AS THE SYSTEM'S OWN "NOTHING HERE"

- **1.** `poll_active_leagues_for_tick` caught each league's exception into an `errors` dict and continued with no print. That dict reaches only `data/live/soccer_live_lens.json`, which is not in the publisher allowlist, so it is unreadable from web. Worse, the broken call sat behind `if live_events:` — so **only a league WITH a live match could reach it**. Silent on a quiet slate, total on a busy one. Three instruments read healthy simultaneously: the tick reported `ok: true` (because `validate_live_lens_snapshot` accepts an EMPTY games list), seven leagues wrote their files successfully, and no error appeared anywhere.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-18 — RULE: a cache with a TTL can serve EMPTINESS as authoritative

- **Measured:** 1,282 BVP cache files, every one `by_batter: {}`. I concluded twice from the file COUNT — first "the data is already collected, it just needs mapping", then "it needs a real fetch job". **Both wrong, in opposite directions.** Computing fresh returned 117-170 batter entries for 5 of 5 pitchers.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-18 — RULE: when a claim is corrected TWICE, stop asserting and run it

- **I made FOUR wrong calls about BVP in one session, alternating direction:**
- *(evidence in `learnings_evidence.md`)*

## 2026-08-18 — I ALMOST REQUESTED A DEPLOY FOR SOMETHING ALREADY LIVE, AND ONLY THE BASELINE CAUGHT IT

- **What caught it was mechanical, not clever:** the deploy-request template has a `verify:` field that demands a BEFORE value, so filing it forced one fresh read. The discipline that saved this was writing down the before-number at the moment of filing rather than carrying it forward.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-18 — RULE: a bias can be the NET of two opposing errors, and fixing one is a wash

- **Measured:** the MLB engine under-produced strikeouts by **27%** (K/PA 0.179 vs 0.226). The obvious cause was the pitch-outcome mix — `base_in_play` 0.23 against a league ~0.17, `base_foul` 0.12 against ~0.18 — and correcting it lands the mix almost exactly on the league.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-18 — A STRUCTURAL DEFECT AND A MARKET EDGE ARE DIFFERENT QUESTIONS

- **The market moved by −0.00013. Two markets better, two worse.**
- *(evidence in `learnings_evidence.md`)*

## 2026-08-18 — MEASURE THE COUNT MATRIX; DO NOT GRID-SEARCH IT

- **`count_delta` is a single scalar** and structurally CANNOT express take-early / attack-middle / protect-late. No amount of search fixes a parameterisation that cannot represent the answer.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-18 — RULE: a session RESUME reassigns the session id, which silently stands the coordinator role down. The register must be re-verified, not assumed

- **My own deploy guard blocked me.** `coordinator.id` held `9ed7fd89-...` — correct when written at 13:36 — and the hook was being handed `6f0980eb-...`. Nothing edited the register; **the session id changed underneath it** when the session was resumed. The role had been silently unheld for an unknown stretch, and the first symptom was the coordinator being unable to deploy.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-18 — THE MARKET HARNESS HAS A NOISE FLOOR 2.4x THE EFFECTS IT WAS USED TO JUDGE

- **Same configuration, two seeds, nothing else changed:**
- *(evidence in `learnings_evidence.md`)*

## 2026-08-18 — RULE: a `sed` backreference that does not match writes a RAW CONTROL BYTE, and it ate three lane slugs

- **Three OPEN lanes lost their names entirely.** Their headers read `###  \x01  —  \x02  — **body` — the literal bytes `\x01` and `\x02` where the slug and status should be. A session correcting the ASCII-hyphen headers ran a substitution with `\1`/`\2` backreferences whose capture groups did not match, and `sed` wrote the escape sequences as raw control characters instead of the captured text.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-18 — A DUPLICATED TERM PASSES EVERY CHECK THIS REPO HAS. A PLAUSIBILITY READ CAUGHT IT.

- **WHAT DID NOT CATCH IT — the full list, because that is the finding.**
- *(evidence in `learnings_evidence.md`)*

## 2026-08-18 — RULE: a union merge CANNOT carry a deliberate deletion. A collapse pushed through one is undone, and comes back bigger

- **I collapsed `state.md` from 59 sections to 26, pushed it through the merge cycle, and `origin/main` came out with 87.** The collapse was reverted and my new sections were added on top, so the file ended up **larger than before I started**.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-18 — A VARIANCE-REDUCTION TRICK THAT CHANGES THE ANSWER IS NOT A VARIANCE-REDUCTION TRICK

- **The first bug, and why finding it was NOT the end.** I keyed the seed on `half.next_batter_index`, reasoning that "a team's Nth plate appearance is the same logical event in both arms." **`simulate.py:3178` advances that index MODULO the lineup length.** It holds 9 values, so the same stream replayed 4-5 times per game — scoring inflated up to **126%**. I had even written "batter_index grows monotonically (not modulo)" into the lane note; one line of code said otherwise.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-18 — RULE: a wiring gate must ask whether the payload is READ, not whether a payload is PASSED

- **Lane `football-model-owner`. Caught by measurement, one step before it would have been published as a clean result.**
- *(evidence in `learnings_evidence.md`)*

## 2026-08-18 — RULE: a zero from a LOCAL checkout is a statement about the mirror, never about production. I filed one as a defect

- **Lane `football-model-owner`. Caught by the repo's own rule, one step after I had already written the wrong claim into `todo.md` and a reference doc.**
- *(evidence in `learnings_evidence.md`)*

## 2026-08-18 — RULE: a guard that gates on IDENTITY fails to a total block when the identity holder disappears. Gate on STATE

- **The failure.** `deploy-guard.py` allowed a deploy when `session_id in .syndicate/coordinator.id`. The coordinator was a session. The session was archived. From that moment the allow-branch was **unreachable**, and the guard blocked every deploy from every session — while presenting itself as a routing rule ("file a request, carry on"). Two requests sat in `deploy/requests/`, `deploy/grants/` was empty, and an 11-day clock ran on the NCAAF opener. Nobody had disabled anything; the predicate simply stopped having a true value.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-18 — CHECK WHETHER A FIELD EXISTS BEFORE DECLARING IT

- **No error, no warning, no test failure.** The symptom was that an override dict of 1.0s produced different results from an empty dict.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-18 — OVERTURNED: "the ledger files were fine, just big" — session `football-model-owner`

- **What was believed.** The session-start digest measured `LEDGER OVER BUDGET`
- *(evidence in `learnings_evidence.md`)*

## 2026-08-18 — OVERTURNED: "a guard that is present is a guard that is working" — session `football-model-owner`

- **Two instances in one session, on two different hooks.**
- *(evidence in `learnings_evidence.md`)*

## 2026-08-18 — FORBIDDEN: never apply a transform to a shared file by patching the transform's own source with `str.replace` — session `football-model-owner`

- **What happened.** To re-run a collapse against the WORKING copy instead of `HEAD`, I rewrote the script's input line with `str.replace` and `exec`'d it. The replacement DID NOT MATCH — whitespace differed — so the "worktree rebuild" silently re-ran the HEAD version, and writing the result destroyed another session's 31 uncommitted lines, including a deployed-and-measured NCAAF result.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-18 — RULE: before wiring ANY feature into a model, check whether the feature is computed FROM THE THING BEING PREDICTED. Ask what WINDOW it covers, not what it is named.

- *(the heading states the rule; full working in `learnings_evidence.md`)*
- *(evidence in `learnings_evidence.md`)*

## 2026-08-18 — A TRUNCATED READING IS NOT A COMPLETE ONE

- **RULE: before reporting a null or an absence, prove the query can return a non-null.** A control that must succeed. `pattern=*conditional_mix*` returns count:1 where `pattern=conditional_mix_2026.json` returns count:0 for the SAME file — and I ran the bad form five times and quoted it to two other sessions.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-18 — A STALE-BUT-"RUNNING" SESSION IS INVISIBLE TO EVERY ORPHAN CHECK

- **It survived BOTH checks, for opposite reasons:**
- *(evidence in `learnings_evidence.md`)*

## 2026-08-18 — RULE: a session worktree protects your INDEX, not your EDIT. Shared-file carry is not absorption.

- The rule going forward: **not scoped to ledger files — confirmed 2026-08-19 on two plain hook-script docstrings.** Expect the next session that commits the shared tree to carry ANY uncommitted edit sitting in the working copy, and expect an UNCOMMITTED edit to be destroyed outright if it conflicts. Commit it with a PATHSPEC commit (`git commit <paths> -m ...`, no staging) the moment it is written, or at minimum re-check `git diff --cached` / `git log -1 -- <path>` before assuming an edit is still pending — a carried edit shows a clean diff and a commit you did not make. Attribution is not worth defending; LOSS is the only thing to check.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-18 — RULE: a check that answers a SLIGHTLY DIFFERENT question returns a confident wrong answer. Six in one session.

- The rule going forward: **before believing a surprising reading, state what the command actually compared.** Every one of these was a real command, exiting 0, returning a plausible number — and answering a question adjacent to the one asked. None failed loudly. The tell is always the same: a result that would be *convenient* or *alarming* if true, produced by a check nobody restated in words first.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-19 — RULE: no active owner, no claims. And a liveness read EXPIRES.

- The rule going forward: **a lane whose owning session is archived, absent from the roster, or silent for hours MUST NOT hold file claims.** Releasing claims is NOT closing the lane — its findings stand and it can be reopened. Audit the full claim set against the roster **including archived**, because `include_archived: false` hides exactly the evidence the question needs.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-19 — CORRECTION: the PATHSPEC commit does NOT cover a NEW file. Staging is still the race, and it bit.

- The rule going forward: **`git commit -- <paths>` only works on paths git already knows. A brand-new file MUST be `git add`ed first, and that add-to-commit window is exactly the race the pathspec form was adopted to remove.** For a new file on a shared tree, either commit it from your own worktree, or accept that it may be carried into another session's commit and verify by CONTENT afterwards.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-19 — RULE: before building a feature pipeline for an unwired input, check whether the engine has a BETTER-WIRED input already doing that job

- **Evidence.** `smartsim2` reads 33 alias-terms from `feature_generation_payload` and no production entrypoint passes it. I measured that wiring it changed the output, then spent a session building a leak-free as-of feature pipeline for it.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-19 — RULE: a population checklist CANNOT detect leakage, and a large clean first-wiring effect is a leakage SUSPECT

- **Evidence.** `build_nflverse_game_metrics` computes EPA from the game being predicted. **r = 0.988** against the final margin over 285 games.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-19 — RULE: a small-n result is not a preview of the large-n result. It is the artifact.

- **Evidence, one metric, one session:**
- *(evidence in `learnings_evidence.md`)*

## 2026-08-19 — RULE: a repair pass must be constrained to EXTEND, never SUBSTITUTE. And a mid-flight hook protects only new sessions.

- The rule going forward: **when automating a fix across N items, the safety condition is a property of the REPLACEMENT RELATIVE TO THE ORIGINAL — "the new text must START WITH the old" — not a property of the source you pulled it from.** "The evidence file has a rule line" is not "this is the SAME line, longer", and the gap between those two clobbered 18 lines that existed nowhere else.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-19 — RETRACTION: "a mid-flight hook protects only new sessions" is WRONG. Hooks fire per call. The real hole is BASH.

- The rule going forward: **hooks are evaluated on every tool call, not cached at session start — a newly registered guard IS in force immediately, including for sessions that started before it existed. But a PreToolUse guard matched on `Edit|Write|MultiEdit` is BLIND to writes made through Bash**, and in this repo that is not an edge case: `trim_lane_blocks.py`, `hoist_open_lanes.py` and `compact_learnings.py` all write ledger files from Bash by design.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-19 — VERIFY THE CHANNEL, NOT JUST THE QUERY

- **It could never appear there.** `live_refresh_loop.py:2784-2790` spawns the sim job with `popen_kwargs["stdout"] = open(log_path, "wb")` — every line the wrapper prints goes to a FILE on the worker's disk, never to the container stdout Render collects.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-19 — RULE: a guard that fails open silently is indistinguishable from a guard that works. Grep for the symbol you deleted.

- The rule going forward: **after editing a guard, prove it still FIRES — do not accept "it parses" or "it is registered" as evidence.** Every hook here wraps its work in `except Exception: return 0` so a broken guard cannot block real work, which means a broken guard is also SILENT. Those two properties are the same line of code.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-19 — RULE: a threshold raise buys HEADROOM ÷ GROWTH RATE. Compute it, or you are choosing a fix you have not measured.

- The rule going forward: **before raising a limit instead of fixing what fills it, divide the new headroom by the observed growth rate and say the answer out loud in hours.** If that number is smaller than the interval between the people who would act on it, the raise is not a fix, it is a snooze — and it costs the credibility of the threshold as well as the time.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-19 — RULE: "this cannot be automated" is a claim like any other. Name the predicate you tried.

- The rule going forward: **before concluding something is not enforceable, state the specific predicate you tested and why it fails. If you cannot name one, you have described the first idea you had, not the problem.** The useful move is almost always to narrow the target: not "detect appending", but "detect the one SHAPE of appending that causes the damage".
- *(evidence in `learnings_evidence.md`)*

## 2026-08-19 — RULE: exonerated as the CAUSE is not free of DEFECTS. Re-ask the narrower question.

- The rule going forward: **when a suspect is cleared of causing the symptom you were chasing, ask separately whether it is nonetheless broken.** An exoneration answers one question — "did this cause X" — and it is routinely read as answering a bigger one, "is this fine". Those come apart, and the second question is cheap to ask once you are already looking at the thing.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-19 — CORRECTION: shared-file carry reaches plain files too, and it reads as nothing to commit, not as loss

- The rule going forward: **`git diff --cached` (or plain `git diff`) coming back EMPTY on a file you know you just edited means the edit already landed in someone else's commit — check before concluding there is nothing to do.** Two hook-script docstrings (`.claude/hooks/ledger-commit-guard.py`, `ledger-postwrite-check.py`, not `.syndicate/*.md`) were fixed here, left uncommitted pending the user's go-ahead, then swept into a parallel `github-actions[bot]` checkpoint commit (`f5953d4c`) before this session staged them. `git log -1 -- <path>` then `git blame -L <line>,<line> <path>` named the commit and confirmed the exact content in two calls. Cost was zero — the fix is correct and already on `origin/main` — but the intended atomic, reviewable two-file commit never existed as such; it rode inside an unrelated bundle. Broadens the 2026-08-18 "shared-file carry is not absorption" rule above: the mechanism is not ledger-specific, it is anything sitting uncommitted in the one shared working tree.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-19 — RULE: read the convention off the DIRECTORY before restructuring it. The precedent is usually already on disk.

- The rule going forward: **before splitting, renaming or re-keying a set of
  files, look at how the EXISTING members are keyed and confirm your rule
  reproduces them.** If your scheme would have filed yesterday's files
  differently than they are actually filed, your scheme is wrong -- the existing
  layout is the specification.

**MEASURED, and reverted within the hour.** Asked to split an 87 KB daily log, I
moved 7 entries stamped `2026-08-19 ...Z` into a new `log/2026-08-19.md`. The
repo keys these files to the **LOCAL** date, so UTC stamps rolling past midnight
stay in the local day's file. **The proof was two directory entries away and I
read it afterwards:** `2026-08-16.md` contains 5 headings stamped 08-17,
`2026-08-17.md` contains 4 stamped 08-18. A single `grep` over a sibling file,
before the change, would have settled it.

**THE COST WAS DISCOVERABILITY, which is what a log is FOR.** A session looking
for "what happened tonight" opens the local-date file; my checkpoints would have
been missing from it while sitting in a file for a day that had not started
locally. Nothing was lost and the error was cheap only because it was caught fast.

**THE REVERT HAD ITS OWN TRAP.** Another session appended to the log between the
split and the revert, so restoring the pre-split backup would have destroyed
their work. Entries were APPENDED BACK instead, accepting approximate ordering
within the day. **On a shared file, "undo" is not "restore the backup".**

**What survived the mistake, because it was measured rather than assumed:** a
single chronological cut is unsafe here (an 08-18 entry sits after the first
08-19 one, so the file is not strictly time-ordered), and splitting on `###`
shreds entries (40 of 46 blocks are undated sub-sections of a parent). Both
findings stand; only the day-key was wrong.

## 2026-08-19 — RULE: a mass-deletion diff is not self-explaining. Compare DISTINCT lines before accepting "it was just dedupe".

- The rule going forward: **when a diff you did not intend shows large deletions,
  do not reason from the line COUNTS or from a plausible story about
  reformatting. Take the set difference of DISTINCT lines, both directions, and
  then grep the tree for a sample of what is missing.** Counts cannot separate
  "500 duplicate copies removed" from "500 unique records deleted", and those are
  the same number.

**MEASURED.** A stray `git add -A` on the shared tree swept another session's
in-progress rewrite of two day-logs into my commit: 1,087 insertions, 1,173
deletions. **My first read was "deduplication of union-merge blocks"** -- the
removed samples were generic repeated headings (`### VERIFIED`, `### Lane`),
which is exactly what dedupe looks like, and the file did contain "MERGED FROM
origin/main -- block-level union" sections. Comfortable, plausible, wrong.
Distinct-line comparison showed **498 and 440 lines gone ENTIRELY**, including
whole session records; a grep confirmed they existed nowhere on disk.

**THE DISCRIMINATOR IS CHEAP AND THE STORY IS FREE.** `set(before) - set(after)`
takes one line to write. The dedupe story took no evidence at all and would have
closed the investigation.

**RESTORING NEEDED A UNION, NOT A REVERT.** The swept version also contained
1,087 lines of genuine new work, so neither version was a superset: reverting
would have destroyed their additions, keeping would have destroyed the history.
**When both sides of an accidental overwrite contain unique content, the only
non-destructive repair is a block-level union**, verified in BOTH directions --
0 distinct lines missing from either side.

**Related:** the rule against `git add -A` on a shared tree was already recorded
and I had followed it all session, using pathspec commits specifically to avoid
this. I reached for `-A` because the change spanned three files instead of one.
**A rule you keep for the easy case and drop for the slightly harder one is not
a rule you have.**

## 2026-08-19 — RULE: when diagnosis has failed repeatedly, look for the fix that does not need the cause.

- The rule going forward: **after two or three wrong causes for one symptom, stop
  buying lottery tickets on the fourth and ask whether a fix exists that is
  correct under ALL of them.** Such a fix is available more often than it looks,
  because a symptom usually has more than one route to the same evidence — and it
  is strictly safer, since it cannot be invalidated by the answer arriving later.

**MEASURED.** `deploy_preflight.py` returned UNKNOWN for web because the service
stopped emitting the `ALL_PROCESS_MEMORY` log line it sampled. FOUR causes were
claimed for that silence and every one was wrong (broken sampler / missing psutil
/ deleted emitter / no caller on web). The fix shipped instead reads web's
process list live from its own `/api/ops/memory` — **the same processes, the same
container, a different route** — and is correct whichever cause turns out to be
real. First run: `web CLEAR` against `refresh-worker HOLD, 7 jobs`, the workers'
path untouched.

**THE TELL THAT SUCH A FIX EXISTED** was that every break-glass had ALREADY been
doing it by hand: both emergency grants that week substituted exactly this
reading and recorded it as the evidence the deploy was safe. **When people are
routinely working around a broken check with a manual step, that step is usually
the fix — promote it rather than continuing to repair the original path.**

**IT DOES NOT CLOSE THE DIAGNOSIS AND MUST NOT PRETEND TO.** The cause is still
unknown and is recorded as such, at lower priority because nothing is blocked. A
symptom fix that gets written up as a root-cause fix is how a silent defect
survives — a service that stopped emitting a diagnostic is still worth
understanding before something else comes to depend on it.

**FALSIFY IN THE BLOCKING DIRECTION.** A guard that only ever returns its
permissive verdict is worse than one that never does, so the tests that count are
the ones that must FAIL: a job present → HOLD, the untouched path still → HOLD,
and an unreachable source → UNKNOWN rather than CLEAR. An empty result must read
as a FAILED READ, never as an idle service.

## 2026-08-19 — RULE: a cause must explain the TIMING, not just the mechanism. Date the change before believing it.

- The rule going forward: **when you propose a change as the cause of a dated
  symptom, find out WHEN that change happened before asserting it.** A mechanism
  that cannot produce the observed timing is not the cause, however completely it
  explains the current state — and "explains the state" is the part that feels
  like proof.

**MEASURED, on the fifth attempt at one symptom.** Web stopped emitting
`ALL_PROCESS_MEMORY` on 2026-08-14. Having finally found the real gate — an env
flag that stops the only emitting loop from starting on web — my immediate next
move was to blame the five `render.yaml` pushes of 08-13, each of which fires
`blueprint_sync` and rewrites a service's WHOLE env block. Mechanically perfect:
a sync would overwrite exactly that kind of manual value.

**`git log -S` killed it in one command.** `render.yaml` has carried `"false"`
for web since **2026-07-25**, and the gate itself has existed since **07-04** —
both WEEKS before the last emission. A sync cannot flip a value that was already
false. Four causes for this symptom had already been wrong; that would have been
the fifth, and it would have been written up as a finding.

**THE DISCRIMINATOR IS CHEAP AND ALMOST NEVER RUN.** One `git log -S <token>`
over the file, before asserting. The temptation is strongest exactly when the
mechanism is elegant, because elegance reads as evidence.

**WHAT SURVIVES IS BETTER THAN WHAT I NEARLY CLAIMED.** The mechanism is verified
(code path + live config + web rebooting repeatedly without emitting), and the
TRIGGER is recorded as unproven and possibly unrecoverable — Render exposes no
env-var history. **"Mechanism known, trigger unknown" is a real result; "cause
found" would have been a fabrication.**

## 2026-08-19 — RULE: a flag's NAME is a hypothesis about its meaning, not its meaning. Read the setter before gating on it.

- The rule going forward: **before rejecting or filtering data on a flag found
  in a payload, find where the flag is SET and read what condition actually
  produces it — do not infer meaning from the flag's name, even when the name
  reads as self-explanatory.** A name chosen for one context (display copy,
  a UI hint) can sound like it means something load-bearing (live adjustment,
  circularity) in a different context (a backtest scoring real predictions).

**MEASURED, caught before shipping, not after.** Building NHL's market-comparison
backtest against real production data, `/nhl/api/cards`'s `lookahead_applied`
flag read as an obvious candidate for "this probability was adjusted using
information not available pregame" — exactly the circularity risk the backtest
existed to avoid. The first draft rejected every row carrying it: 23 of 24 rows
in the first test run.

**Reading the actual setter (`nba/cards.py`, the same flag) found a different,
unrelated mechanism**: `lookahead_applied = bool(resolved_date != requested_date)`
— it means "the requested date had no games, so the route served the next date
that does," not "this game's probability was live-adjusted." Confirmed against
every one of 20 cached NHL responses: `resolved_date` was always LATER than
`requested_date` when the flag was true, consistent with a forward-looking
fallback, never same-day.

**THE FIX WAS THE SAME SHAPE AS THE ORIGINAL STALE-FILE BUG THIS SAME BACKTEST
ALREADY FOUND**: don't drop the row, key it on the value the flag reveals is
actually correct (the resolved date, not the one requested) — the existing dedup
then does the rest. Two bugs, one session, same root cause: trusting a label
over what actually produced it.

**WHAT SURVIVES**: `grade_nhl_predictions_vs_market.py`'s docstring now states
the verified meaning explicitly, with the confirming evidence, so the next
reader doesn't have to re-derive it from the name a second time.

## 2026-08-19 — VERIFY WHAT THE THING YOU CHANGED *DEPENDS ON*

I added a hook that shells out to `scripts/sim_input_checklist.py`, deployed it,
and confirmed **twice, by content** that the hook was in the live SHA. **The
script it calls was never on that worker.** My earlier graft shipped the
`sim_engine` tree, `artifact_publisher.py` and the sim job — and not the
checklist. Every invocation was `FileNotFoundError`, swallowed by the hook's own
`except` and printed into a truncated log tail.

**RULE: verifying the code you wrote is present is HALF a check. Verify its
inputs, its callees and its data exist in the same environment.** "Is my change
live?" and "can my change do anything?" are different questions, and I answered
the first one twice while never asking the second.

**Corollary, and it cost an hour: DO NOT DIAGNOSE DEFECT 2 BEFORE CONFIRMING
DEFECT 1.** I found a genuine root-resolution bug in that script (it read from
`REPO/data` while writing to `SYNDICATE_DATA_ROOT`) and fixed it carefully —
while it sat downstream of a file that did not exist. The fix was correct and
irrelevant. **When a component appears broken, first establish that it RAN.**

**The same session's fifth instance of one habit** — see
[[verify-the-channel-not-just-the-query]] and
[[a-truncated-reading-is-not-a-complete-one]]. Each time: I checked the thing in
front of me, found it sound, and stopped one dependency short.

**What finally worked:** extracting the deploy TREE and executing the script
inside it — imports resolved, ran to a clean diagnosis. Not the working copy, not
the diff: **the artifact that will actually run.**

## 2026-08-19 — RULE: to find where variance is CREATED, decompose the outcome. Correlating its inputs finds what MOVES WITH it, which is a different question.

**Evidence.** NCAAF projected total SD was 1.67x the market's. I proposed three
mechanisms, each plausible, each swept, each wrong:

1. **The team-strength index clamp** was too narrow, saturating 36 of 138 teams.
   Widened it — margins got WORSE (15.97 -> 15.27) and totals worse (7.51 ->
   9.55). Reverted.
2. **The yardage weight asymmetry** (`offense*3.0 - defense*2.2`) meant a good
   offense added more than a good defense subtracted. Swept to parity and past
   it — total SD moved 7.45..7.83, and parity was the WORST row.
3. **The `scoring_environment` asymmetry** (`offense*0.18 - defense*0.08`, 2.25x)
   — found by CORRELATING every candidate against the totals, where
   `RATING net SUM` scored r=0.782 on totals and only -0.141 on margins, a
   beautifully clean separation. Swept 0.18/0.08 down to 0.06/0.06. **A 3x
   reduction moved total SD by 0.07 points.**

**The correlation was real and still useless.** `offense_index` correlates 0.628
with totals because BOTH are downstream of the ratings — it is a fellow traveller,
not a cause. Every one of those three levers damps an INPUT to a loop whose
OUTPUT compounds: `drive_success_probability` feeds four-down sequences, so a
modest prior change barely moves the converted scoring rate.

**What worked, in one run:** decompose the outcome into factors that are
EXHAUSTIVE by construction.

    total = drives x scoring_rate x points_per_scoring_drive

    game        total   drives   score%   pts/score
    LOWEST       27.5    24.4    20.8%      5.43
    HIGHEST      68.6    20.0    53.9%      6.35

Scoring rate swings **2.6x** and carries the spread; drives move slightly and in
the CORRECT direction (down, because scoring drives burn clock); points-per-score
is flat. Because the three factors multiply to the whole, the carrier MUST be one
of them — no mechanism needed to be guessed.

- **The rule:** when a distribution is wrong, write the outcome as a product or
  sum of factors that reconstruct it exactly, then measure each. That identifies
  the carrier in one pass. Correlating candidate inputs ranks them by how much
  they travel with the outcome, which is not the same thing and cost three sweeps.
- **Three failed sweeps is the signal to stop proposing mechanisms**, not to
  propose a fourth.
- **Cheap tell that a lever is the wrong one:** its effect size. A 3x parameter
  change producing a 1% output change means you are not on the causal path at
  all, rather than that the parameter needs tuning further.
- Related: the 60-seed sweeps read ~30% high on total SD versus the 300-seed
  production run (7.51 vs 5.77). Fine for RANKING settings, wrong for quoting a
  level — I nearly reported 2.17x as the model's dispersion when it was 1.67x.

## 2026-08-19 — CORRECTION: `git commit -- <paths>` fixes the shared INDEX. It is the DELIVERY MECHANISM for a shared FILE. I applied it to both and caused two more incidents.

**This corrects my own 2026-08-18 entry**, which concluded that pathspec-on-the-
commit is "the only thing that survives me being in a hurry". That is true for a
shared INDEX and false for a shared FILE, and the earlier entry says so further
down — I read the headline and not the caveat.

**Four attribution incidents in one session, in two distinct classes:**

*Shared index (pathspec DOES fix):*
1. `d46be8a0` swallowed another session's `scripts/archive_released_lanes.py`
   (169 lines) via a chained `add && commit`. Caught, split, recovered.
2. `b65e1f76` swallowed another session's `state.md` correction the same way.
   Not caught — another session committed on top before I looked.

*Shared file (pathspec does NOT fix, and is the vector):*
3. My `lanes.md` pathspec commit carried two other sessions' NEW lane blocks
   (`wnba-edge-263`, `nfl-player-props-backtest`) — because `git commit -- <path>`
   commits the WORKING-TREE version of that path, including their unstaged edits.
4. My own daily log was committed under ANOTHER session's message
   (`361d0498`), the same hazard running the other direction.

**No content was lost in any of the four.** The cost is attribution: four commits
now describe work their messages do not mention, and two lanes' entries are
recorded under a football commit.

**How to apply — pick the tool by what is SHARED, not by habit:**

| what is contended | tool |
|---|---|
| the INDEX (other sessions have things staged) | `git commit -m "..." -- <paths>` |
| the FILE (`lanes.md`, `state.md`, `todo.md`, `log/*.md`) | the BLOB recipe — rebuild from `HEAD:<file>`, `hash-object -w`, `update-index`, then commit with NO pathspec |

**The tell I ignored twice:** an insertion count far larger than what I wrote.
`lanes.md` came back `+386` on what was meant to be an in-place status edit. I
read the number, noted it, and committed anyway — a check whose result you do not
act on is not a check.

**And the honest scoreboard:** I was told once, explicitly, to stop chaining add
and commit. I stopped chaining, adopted pathspec, and then produced two NEW
incidents of a different class with it. Fixing the named instance without
understanding the category is how the same failure returns wearing different
clothes.

### 2026-08-19 — OVERTURNED: `SYNDICATE_DEPLOY_GUARD=off` works as an inline Bash prefix
- What we believed: `CLAUDE.md` documents `SYNDICATE_DEPLOY_GUARD=off` as the
  off switch for `deploy-guard.py`, presented with no caveat — the natural
  reading is `SYNDICATE_DEPLOY_GUARD=off python scripts/render_deploy.py ...`
  in one Bash call.
- What was actually true: silently inert. `deploy-guard.py` (a PreToolUse
  hook) reads its OWN process environment, and that hook evaluates the
  command string BEFORE any shell would parse and export a prefix inside it.
  Ran it twice, identical block message both times.
- How we found out: tried it to get past a genuine job-in-flight HOLD (a real
  MLB sim on refresh-worker), on explicit user instruction to force the
  deploy. Confirmed by reading `deploy-guard.py`'s source directly rather than
  retrying with variations.
- The rule going forward: **this is the SAME class of gap already documented
  for `commit-guard.py`** (2026-08-17: "all THREE documented overrides were
  unreachable... a PreToolUse hook runs BEFORE the shell") — a sibling
  instance in a different hook, not a new mechanism. Any `SYNDICATE_*_GUARD`
  off-switch mentioned in prose must be assumed unreachable from inside a
  tool call until proven otherwise; it can only be set at the harness/settings
  level, outside any session's own reach. Do not spend a second attempt
  varying the prefix syntax — go straight to reading the hook's source for
  where it actually reads the value from, or hand the decision to the user.
- Cost: two blocked deploy attempts, ~5 minutes, no production impact (the
  guard did its job correctly both times).

## `#472` — a quiet autorun is not evidence it is idle `[2026-08-19]`

**What we believed:** WNBA's pregame autorun going silent for 5+ hours after
a fresh deploy was benign — smart-sim generation is tied to actual game
slates, not a fixed interval, so a quiet stretch with no game imminent
reads as correctly-skipped, not broken.

**What was actually true:** it was failing on every tick, repeatedly, and
each failure silently cost a full 4-hour retry window. The autorun's own
except-block wrote a fresh, full-interval-resetting epoch on ANY exception,
including plain mutex contention (`launch_refresh_run`'s "already active"
ValueError) where NOTHING was actually attempted — some other job (a
legitimately in-flight MLB resim) just held the shared single-run slot.
Soccer's identical, copy-pasted autorun had the same defect.

**How we found out:** the user pushed back once ("well that tells me
there's a problem") on the "benign cadence" framing, and again ("this
should not cause a 5 hour delay") after a first, still-too-generous
explanation. Both times the fix was to actually read
`/api/ops/live-refresh/state` and the raw log stream instead of reasoning
from a plausible-sounding mechanism. The production timestamps settled it:
WNBA succeeded cleanly at ~4h intervals all day (01:24/05:24/09:29/13:35Z),
then went dark the moment it first collided with a job that was still
verifiably running (confirmed via its own pid switching mid-investigation,
not assumed).

**The rule going forward:** a scheduled job going quiet for longer than its
own stated interval is not "no trigger yet" until you have checked whether
it is actually TRYING and losing — read the live state/logs for the actual
attempt-and-failure pattern before accepting an absence as benign. And
separately: any retry/backoff logic must distinguish "we tried and
genuinely need to wait" from "we didn't get a turn" — collapsing both into
one epoch/cooldown timestamp turns ordinary resource contention into a
multi-hour outage.

**Cost:** ~1 extra investigation cycle before the user's second, sharper
pushback forced the real trace; the underlying bug (fixed in `97e85b66`)
had likely been silently starving WNBA's refresh cadence for longer than
just this session's window, unmeasured.

---

## An absent log marker is only evidence if the marker's transport actually reaches you `[2026-08-19]`

**What we believed:** repeated checks of `BOXSCORE_BOOTSTRAP_STALLED` never
appearing in Render's log collector, across many hours and multiple real
runs, was treated as inconclusive-leaning-toward-still-broken evidence
about `#469`'s ESPN fetch — the marker's own `print(..., flush=True)` had
been specifically added so it WOULD be observable, so its absence felt
like it should mean something.

**What was actually true:** it meant nothing, for a whole class of runs.
`launch_refresh_run` spawns autorun-launched children with
`stdout=DEVNULL` by explicit design (soccer's own pre-existing `#433`
code comment explains why) — so no `print()` from inside
`refresh_wnba_oddsapi_props.py`, including this exact marker, could ever
reach Render's log collector for THOSE specific runs, regardless of
whether the underlying condition it reports on ever occurred. Every
"still no STALLED marker" observation during that stretch was reading a
transport gap as a negative result.

**How we found out:** the user pushed back twice on "still frozen, still
waiting" as an answer before the actual mechanism got read rather than
assumed. Reading `launch_refresh_run`'s own code (not just its
docstring/comment, the actual spawn call) showed the DEVNULL redirect
directly. The script's own `_append_log` FILE turned out to be the one
surviving signal, but had never been allowlisted either — a second,
independent gap in the SAME diagnostic chain, only found by trying to
read that file and hitting a 403.

**The rule going forward:** before treating an expected log marker's
absence as a negative result, confirm the marker's actual transport
reaches you for the SPECIFIC invocation path being tested — a detached/
fire-and-forget subprocess, a different launch mode, or a different
service can silently sever stdout capture while the underlying code still
runs exactly as written. When in doubt, verify with a marker or file
KNOWN to exist for that exact path (a positive control) before trusting a
negative one. This is the same shape as the file-vs-stdout gap already
documented for soccer's own reporting (`#433`) — it cost real
investigation time again here specifically because the SPECIFIC launch
path (`launch_mode="web_process"` from the WNBA/soccer pregame autorun)
hadn't been checked against it before, only assumed to behave like other,
already-verified invocation paths.

**Cost:** several hours of "still no marker, still inconclusive" reporting
that was never going to resolve on its own, until the transport gap itself
was found and fixed (allowlisting `_append_log`'s own file) and a manual
trigger was used to get a real, direct answer instead.

### 2026-08-19 — a disclaimer marker must PRECEDE the path it disclaims, not follow it

- **What we believed:** adding a phrase to `lane-guard.py`'s
  `_DISCLAIMER_MARKERS` list is sufficient to make any sentence containing
  that phrase stop misreading as a claim — the same fix that worked for
  "not touch" and "not taken" earlier the same day.
- **What was actually true:** `_claimable_prefix` cuts a line AT the
  marker's position and keeps only the text BEFORE it as claimable.
  Writing a release note as "`path` claim RELEASED..." (path first, marker
  second) still left the path in the claimable prefix, because the marker
  came too late to protect it. Every marker that already worked
  ("NOT claimed: `path`", "BLOCKED, not taken: `path`", "held by") happens
  to precede the path it disclaims — the mechanism has a required word
  order this session had never had to state explicitly, because nobody had
  written a marker-after-path sentence before.
- **How we found out:** wrote a regression test for the new marker BEFORE
  trusting the fix, exactly as the two same-day precedents had — and it
  failed. Fixed the actual `lanes.md` prose to be marker-first and re-ran;
  the test passed.
- **The rule going forward:** when writing any Files-block disclaimer in
  `lanes.md`, put the marker phrase FIRST and the path AFTER — "RELEASED,
  no longer claimed: `path`", never "`path` ... RELEASED". When adding a
  new marker to `_DISCLAIMER_MARKERS`, the regression test must reproduce
  the EXACT sentence about to be committed, not a hand-simplified stand-in
  — the first version of this fix's own test used marker-first phrasing
  from the start and would have passed even if the real `lanes.md` prose
  (path-first) stayed broken, which is a different, easier trap than the
  bug itself.
- **Cost:** caught before shipping — the failing test was the whole point
  of writing it first — but it is the fourth instance of this general
  parser-gap shape in one day, and this specific sub-shape (word order,
  not just word presence) had not been named until now.

**Same session, a THIRD sub-shape found minutes later while writing a
DIFFERENT disclaimer.** `_claims()` processes each PHYSICAL LINE of a
wrapped bullet independently — `_claimable_prefix`/`_paths_in` never see
a joined logical bullet, only one line at a time. A marker phrase that
line-wraps ("... NOT\n    claimed here:** `path`") has its recognized
words split across two lines the parser reads separately: line one
("... NOT") contains no path so yields nothing; line two ("claimed
here:** `path`") contains the path but, read in isolation, no longer
contains "not claimed" — only "claimed", which matches nothing — so the
path is extracted as a claim regardless of the marker one line up.
**Verified against `_claims()` directly, not assumed**: this exact wrap
reproduced the double-claim live in `lanes.md`; moving the marker and the
path onto the SAME physical line (no line break between them) fixed it,
confirmed by re-running `_claims()` against the file afterward. **The
rule, combined with the one above: a marker must be on the SAME physical
line as the path, AND before it on that line.** Splitting either way
(wrong order, or right order but wrapped) is invisible to the parser.
This also means `check_lane_invariants.py` is currently the wrong tool to
verify a disclaimer fix with — separately discovered this session that
its own copied `FILES_RE` has drifted from `lane-guard.py`'s (caught by
`tests/test_check_lane_invariants.py`'s own pinning test, pre-existing,
not caused here) — so it can report a false double-claim independent of
whether the real, live-enforced parser agrees. Verify any lane-claim
question against `lane-guard.py`'s own `_claims()` directly (see this
session's own throwaway one-liner, or write a test in
`tests/test_lane_guard_files_forms.py`), not against the invariant
checker, until that drift is fixed.

### 2026-08-19 — NEAR-MISS: an object-database merge updates the REF, not the working tree, and a later working-tree write can silently revert real content

- **What happened.** Used the sanctioned zero-working-tree-writes merge
  recipe (`git merge-tree --write-tree` + `commit-tree` + `update-ref`) to
  push a checkpoint past a dirty shared tree — correctly, and it worked.
  Minutes later, wrote a NEW deploy measurement to `.syndicate/deploys.md`
  via a plain `cat >> .syndicate/deploys.md` against the WORKING TREE file
  — which the merge had never touched, so it still held an OLDER version
  of the file, missing a real ~80-line entry (`#473`, another session's
  NBA investigation) that had arrived via the merge into the REF only.
  `git add` + `git commit` then staged "the stale working file plus my
  append" against a parent commit that DID have `#473` — producing a diff
  that deleted their entire entry and replaced it with mine.
- **How we found out.** Read the commit's own diff before pushing (a
  `git diff --cached --stat` showing 77 deletions on what should have been
  a pure append was the tell) rather than trusting the commit message.
  Caught before the commit reached `origin` — verified with `git log
  --oneline origin/main..HEAD` first.
- **The rule going forward: after ANY object-database merge that moves
  `HEAD` via `update-ref` without touching the working tree, treat every
  file in that merge as STALE in the working tree until proven otherwise.**
  Before writing to a file with a plain shell append/edit, diff the
  working-tree copy against `HEAD`'s own copy of that exact path
  (`git diff HEAD -- <path>`) — a non-empty diff on a file you have not
  touched since the merge means the working tree is behind the ref you
  just created, and a naive append will re-base off the wrong content.
  Safer still: build any further edit to that file the SAME way the merge
  was built (read `HEAD`'s blob, edit that content, write a new blob/tree/
  commit) rather than mixing the two methods on the same file in one
  session.
- **Cost:** fully recoverable, not yet pushed when caught — rebuilt the
  correct tree from `HEAD`'s real content plus the intended addition,
  verified content on `origin/main` after pushing (both entries present,
  exactly once each) rather than trusting the push succeeding silently.


## Reachability of the call is not reachability of the data `[2026-08-19]`

**What we believed:** asked whether NBA had `#468`'s WNBA reachability
defect (a fixed function made unreachable by broken wiring), traced the
call graph and found `refresh_nba_oddsapi_props.py` genuinely reaches the
same shared, monkeypatched, `#468`-fixed function as WNBA does — same
entry point, `league_code` threading through generically, no env-var
override. Concluded "structurally identical to WNBA, should work the
same way" and reported that as the answer.

**What was actually true:** the CALL is reachable; what it needs to
compute from is not. A real reachability test (the same methodology that
had verified `#468` for WNBA — real historical data in a scratch copy,
not code-reading) showed NBA's rebuild returns nothing: the function's
own two data sources are both structurally absent for NBA (a `boxscores/`
subdirectory the vendor package expects but Syndicate's NBA pipeline
never populates, and `player_logs.csv`, also absent). The wiring question
(`#468`'s exact shape) and the "does this function have anything to work
with" question are different questions, and tracing the first does not
answer the second.

**How we found out:** the user asked the identical question twice. The
first answer rested entirely on a call-graph trace and treated symmetry
of the CALL PATH as symmetry of the OUTCOME — an assumption never tested.
Only re-running the actual verification methodology (not a repeat of the
same trace) surfaced the real difference.

**The rule going forward:** "is this reachable" and "is this reachable
AND does the destination have valid inputs" are separate claims requiring
separate evidence. A call-graph trace proves the first; only running the
function (or a faithful scratch-data reproduction of it) proves the
second. This is the same shape `model_engine_standard.md` already
enforces for model inputs (CONSUMED × POPULATED, never one dimension
alone, never a name grep) — the same discipline applies to any
"is X wired to Y" reachability question, not just input-field audits.
When a reachability answer is being extended from one instance (WNBA,
verified) to a sibling (NBA, untested) by structural analogy alone,
treat that extension as unverified until it's actually run, even when
the code paths look identical.

**Cost:** one full round of "here's the answer" that had to be walked
back and re-verified from scratch, after the user declined to accept the
first pass at face value.
---

## 2026-08-19 — I declared a deploy FAILED 60 seconds after it went live, and it had not

**What happened.** Deployed `ebf301ae` (NCAAF wk1 SP+ projections) to web. Read
the served board ~1 minute after Render reported `live`, saw the OLD values, and
reported **"STILL PPA - FAILED"**. Then spent several tool calls diagnosing
`SYNDICATE_NCAAF_SOURCE_ROOT` and concluding **"Path A cannot work"**.

**It had worked.** `_bootstrap_render_data` starts a background thread that
**sleeps 20 seconds** and then copies committed repo data onto the mounted disk
web actually reads. 90 seconds after my failure call the board read SD 12.93 /
max 50.60 — the correct SP+ signature.

**The rule already existed.** `watcher_over_spot_check`: poll until async
effects land; one early read produced two wrong conclusions in a single earlier
session. I had it, and still sampled once.

**What makes this one worth its own entry** is the shape of the error, not the
impatience. The premature read did not merely delay the answer — it sent me
building an elaborate and *internally consistent* wrong theory. The env-var
finding was REAL (web does read the mounted disk, not the checkout) and it
explained the observation perfectly. A true fact can support a false conclusion,
and a satisfying explanation for a bad reading is more dangerous than no
explanation at all, because it stops you re-reading.

**The rule going forward.** After a deploy, before drawing ANY conclusion from a
served payload, establish how the change is supposed to reach the surface and
how long that takes. If the path includes an async step — a bootstrap sync, a
cache TTL, a background worker, a CDN — the first read is not evidence and must
be a POLL, not a sample. And if a failing read leads you into a diagnosis,
re-read the payload before acting on the diagnosis: the cheapest possible test
of "is this still true?" costs one call and would have saved five here.

**Cost:** ~5 wasted tool calls, a wrong "FAILED" reported to the user, and a
recommendation ("Path A cannot work, only Path B") that was the opposite of the
truth. No production impact — the deploy was correct throughout.


## 2026-08-19 — FORBIDDEN: never treat a green local `pytest` run as evidence about CI. **CI runs `unittest`, and `conftest.py` does not exist to it.**

`tests/conftest.py` is a **pytest plugin file**. `python -m unittest` never
imports it. Both workflows in this repo run `unittest`:

    ci.yml            python -m unittest tests.test_archives
    daily-update.yml  python -m unittest <13 modules>

while `CLAUDE.md`'s documented day-to-day loop is `python -m pytest tests/`.
So every autouse fixture in `conftest.py` — cache resets, the prediction-ledger
isolation, the background-loop suppression — is **silently absent in CI**, and
a test that depends on one passes locally and fails in the gate, forever, with
no signal that the two runs were not the same run.

**Measured:** `tests/test_wnba_cards_merge_aliases` — `20 passed` under
`python -m pytest`, `FAILED (failures=2)` under `python -m unittest`, same
commit, same machine, same minute. Cause: `build_source_cards_payload`'s cache
is keyed on `(date, ...)` + a wall-clock TTL bucket, `conftest.py` had cleared
it since months ago, and under `unittest` nothing did — so the
alphabetically-first test's `("2026-07-02", True)` payload was served to the
two tests after it. **Deterministic, not a flake, and it had failed the Daily
Update workflow every single morning it was able to run.**

**The general rule, which is not about pytest:** *run the command the gate
runs.* A verification is only evidence about the thing that shares its
harness. This is the same shape as `presence != reachability` and
`a deployed fix can be inert` — the code was there, the fixture was there, and
the path that mattered never reached it.

**How to not re-introduce it:** shared setup that a CI-run module depends on
must live somewhere BOTH runners load — `tests/_cache_isolation.py` is the
pattern: plain functions plus a `TestCase` mixin, with `conftest.py`'s fixtures
delegating to the same functions. One definition, both harnesses. Adding a new
autouse fixture to `conftest.py` alone is fine ONLY for modules that no
workflow invokes through `unittest`; check `ci.yml` and `daily-update.yml`
before assuming that.

## "We don't capture that" is a claim about NAMES until you check the CACHES `[2026-08-19]`

**What we believed:** two of the four smart-sim calibration artifacts
(`intervals_band_calibration`, `intervals_time_profile`) could not be built
because they need per-3-minute-segment actual scoring, and "Syndicate
captures final box lines and quarter totals, not intra-quarter segment
scoring". Reported as `actuals_unavailable` and deferred as separate work
requiring a new play-by-play capture pipeline.

**What was actually true:** the actuals were already on disk. ESPN's summary
endpoint returns a `plays` array (~380 plays/game) carrying `period.number`,
`clock.displayValue`, and the RUNNING `homeScore`/`awayScore` — and
`_espn_summary_local` already fetches and CACHES that payload for every game
the boxscore bootstrap touches. 113 of 114 locally-cached summaries were
usable immediately. Differencing the running score across plays yields exact
per-segment scoring; verified on a real game where the 16 derived segments
summed to 179 against a final score of 179.

**How we found out:** the user declined the deferral and said "find
actuals". The search that followed was not clever — it was grepping for
play-by-play in the repo (which surfaced an entire existing
`game-shape-capture` lane), then listing the ESPN cache directory, then
opening one cached file and reading its top-level keys. Every one of those
steps was available before the wrong conclusion was published.

**The rule going forward:** an artifact that does not exist under its own
name is not the same as data that does not exist. Before concluding a
derived input cannot be built, enumerate what the pipeline already FETCHES
and CACHES — raw upstream payloads (`_espn_cache/**`, vendor caches, raw/
snapshots) routinely carry far more than the narrow field the consumer
extracted from them. Grep for the concept, list the cache directories, and
open one file. "We don't capture that" is a statement about the
transformation layer; the raw payload usually captured it anyway.

**Cost:** one wrong deferral published in a commit message and a lane block,
retracted the same session. The fix, once the data was found, was a single
builder script and no new capture infrastructure at all.

## 2026-08-19 — NEAR-MISS: a multi-step object-database commit re-resolved `origin/main` mid-construction

Landing a ledger update via `read-tree origin/main` → `hash-object` →
`update-index` → `write-tree` (one Bash call) → `commit-tree -p origin/main`
→ `push` (a LATER, separate Bash call) produced a commit whose PARENT
pointer correctly recorded the fresh tip (`f9907d0b`) but whose TREE was
built from an older cached resolution of `origin/main` (`259103d9`) from
the earlier call — because another session fetched on this SAME shared
clone in between. The push succeeded as a real fast-forward (the parent
pointer was genuinely valid), so nothing rejected it; it silently reverted
another session's already-landed lane block (`#481` daily-update backup
truncation) back out, while every other file stayed correct.

**Caught by:** `git diff-tree -r --name-status <believed-parent>
<new-commit>` run immediately after every push in this pattern, not
assumed clean because the push itself didn't error. The parent SHA a
commit records is not proof its tree matches that parent's tree plus only
your intended diff — verify both independently.

**The rule going forward:** on a shared clone, symbolic refs (`origin/main`)
can move between separate tool-call boundaries because other sessions fetch
concurrently. A multi-step object-database construction must pin one
explicit commit SHA at the start (`BASE=$(git rev-parse origin/main)`) and
use `$BASE` — never the symbolic ref — at every subsequent step
(`read-tree`, `commit-tree -p`), even across separate calls. See
[[project_shared_index_can_hold_a_revert]] and the object-database-merge
near-miss already in this file for the sibling failure modes on the same
shared-clone hazard.

**Cost:** caught and corrected with a follow-up commit before any other
session built on the bad state; content-verified restored via diff-tree
against the true prior tip.

## 2026-08-19 — A commit's own summary line overclaimed "closes to zero" while its body text said otherwise

A faceoff-calibration commit's message read "This closes the faceoff-track's
own open-items list to zero." The report it shipped alongside, in the SAME
commit, had its own "What this does NOT do" section stating plainly that
`faceoff_mult_clip_low`/`faceoff_mult_clip_high` were never touched. Both
were true at the same time: the narrower claim (the two constants actually
checked) was accurate; the summary sentence wrapped around it was not. The
gap survived one full commit-and-push cycle before being caught.

**Caught by:** treating a "we closed X" claim as a hypothesis to re-verify,
not a fact to build on — re-reading the full text of the report that made
the claim (not just its headline) surfaced the contradiction inside the
SAME document. A dedicated re-check pass (an Explore agent asked to read
every faceoff addendum end to end and confirm or refute "closed to zero")
found it directly.

**The rule going forward:** a summary sentence and the detail underneath it
can drift apart within a single piece of work, not just across sessions —
check a "fully closed" / "zero remaining" claim against the SAME document's
own caveats section before repeating it in a lane block, todo.md, or a
user-facing summary. This is a sibling to
[[feedback_retraction_is_not_innocence]] (withdrawing a claim doesn't
prove the opposite) and to [[feedback_gate_on_the_output_not_the_input]]
(check what a document actually says, not what its own headline implies it
says) — here the discrepancy was inside one document, not between two.

**Cost:** low — caught in the next work session on the same lane, before
any other session or deploy relied on the overclaim. Fixed with a
correction addendum on the record (not a silent edit) plus the actually-
open item closed with a proof.

## 2026-08-20 — An artifact can OUTGROW the publish ceiling, and the failure is silent

`daily_ladders_<date>.json` reached **13,678,982 bytes** against
`_PUBLISH_MAX_BYTES = 12,582,912`. The sweep refused it. Web went on serving the
last copy that fit — 11,716,507 bytes, generated `2026-08-18T18:20:25` — so every
MLB compact-card row carried a full sim side against an EMPTY market side for 28
hours. Measured on refresh-worker `2026-08-20T00:55:00Z`:

    SWEEP_SKIPPED_DETAIL too_large=[
      mlb_source/.../daily_ladders_2026_08_19.json(13678982),
      mlb_source/tracking/book_quotes/2026-08-19.jsonl(95051585)]

**Why it cost so much to find: every other link was CORRECT.** The worker really
did rebuild the ladder (`generatedAt 19:54:41 CT`). `is_stale()` really did
correctly answer `fresh` — the content genuinely was newer than the odds and the
sims. There was no error, no failing test, and nothing wrong anywhere near the
ladder code. I chased five successive causes, each hidden behind the last, and
three of my intermediate diagnoses were wrong.

**The general rule.** A size ceiling on a publish path is a freshness failure
mode that GROWS INTO EXISTENCE. Nothing changed on the day it broke; the file
crossed a line. The 08-18 copy was under the bound and the 08-19 copy was over
it. So:

- **"It used to work and stopped, with no deploy" should raise SIZE as a
  first-class hypothesis**, not a last one. Ask what got bigger.
- **A component being correct is not evidence the SYSTEM is.** `is_stale`
  returning `fresh` was true and useless — it described the worker's disk while
  the symptom lived on web's. When a verdict is right and the symptom persists,
  the next question is *whose copy is it describing*.
- **The fix for an over-ceiling artifact is the DIRECT streamed path, not a
  higher ceiling.** `publish_hot_artifact` streams above 4MB and never consults
  `_publish_skip_reason`; `book_grid` (12,855,903) has published that way all
  along. The bound is sweep-only by design — it exists to stop 51MB
  `odds_history` shards going up every cycle.

**Instrument note, worth fixing separately:** `SWEEP_SKIPPED_DETAIL` bounds
examples at three PER REASON but prints reasons in dict order, and
`stale_slate`'s 60 entries pushed `too_large=[...]` past the 8000-char tail the
sim-log endpoint serves. The discriminating class was the one that got cut. The
answer came from the Render logs API against the worker's own refresh loop
instead — `resource=srv-d91dpertqb8s73co8ls0&text=too_large`. **A bounded log
line is only bounded if the bound applies to the WHOLE line.**

## 2026-08-19 — OVERTURNED: "leak-free" is not "representative" -- a backtest can be methodologically clean and still measure the wrong pipeline

`backtest_soccer_h2h_calibration.py` was built and trusted on the strength of
its leak-freedom: ratings recomputed per match day with a correct `as_of`
cutoff, closing odds as an honest benchmark, per-family date coverage stated
rather than assumed. All of that was, and is, true. It was also rating 5 of
9 leagues (epl/la_liga/bundesliga/serie_a/ligue_1) via the goals-as-xG
fallback, while `build_soccer_artifacts.py` -- PRODUCTION -- reads real
Understat xG and real ppda directly from `team_history/*.csv` for exactly
those five leagues. Two entirely different code paths, both leak-free in
their own right, computing different numbers for what "this team's attack
rating" means. **The backtest's own internal correctness said nothing about
whether it was testing the thing production actually runs.**

Found while checking whether `ppda` (a CONSUMED+UNPOPULATED checklist alarm)
was a misrouted producer rather than genuinely missing data -- the
"data already exists somewhere, check before sourcing new" discipline this
session had already applied twice. It was both: the data existed, AND the
backtest script simply never read the file it lived in.

**The general rule.** A backtest's job is to measure what production does.
"Leak-free" answers "is this number honestly measured from the data it
uses" -- a completely separate question from "is this the SAME data
production uses." Passing the first says nothing about the second, and
nothing about the second's absence produces an error, a test failure, or
any signal at all -- both pipelines run, both produce plausible numbers,
both pass every existing test. The two pipelines have to be checked against
each other DIRECTLY (does the backtest's league-branching logic match
production's, field for field), not inferred from either one looking
correct in isolation.

**How to apply, going forward:** whenever a backtest and its production
counterpart both compute "the same" derived quantity (ratings, features,
whatever a sim consumes) from source data, that computation's BRANCHING
LOGIC -- which leagues/sports/entities take which code path -- must be
checked for equality between the two call sites, not just each site's
internal correctness. A named constant (`_GOALS_BASED_RATING_LEAGUES`) that
exists in two places and is never asserted equal is exactly the kind of
drift this misses. `test_backtest_matches_production_rating_source.py`'s
first test is that assertion, added specifically so this class of bug
cannot silently return.

Related: [[project_syndicate_e2e_assessment]] (the general "Render is source
of truth, git is a lossy mirror" caution is a sibling of this -- both are
"the thing that LOOKS like ground truth is not automatically the thing that
matters" traps), and this session's own earlier xG-double-count fix (a
different flavor of the same family: code that is locally correct and
globally wrong).
## 2026-08-20 — OVERTURNED: "the slate date rolled, the gate expired". It had not.

I told the user a roster-rebuild gate set for `2026-08-19` had **expired
unspent**, and separately keyed a status-artifact watcher on `2026-08-20`. Both
were wrong for the same reason: **00:xx UTC is 19:xx CT on the PREVIOUS day.**
The slate date rolls at 05:00Z, not 00:00Z. The gate was still live with ~3.5
hours to spare, and the watcher spent ~30 minutes reading a document from
`23:08:01Z` that no sim was going to update, reporting `evidence=no` each time
and looking exactly like a failed deploy.

This is the SECOND time this session pattern has cost real time (see the earlier
"report local time, not UTC" correction). The failure is not arithmetic — it is
reading a UTC clock and reasoning about a CT-keyed artifact without converting.

**How to apply:** any artifact keyed by SLATE date — ladders, sims, status
documents, rebuild gates — is on Central time. Before concluding a document is
missing, stale, or expired, convert: `slate_date = (utc - 5h).date()`. A watcher
keyed on the wrong date does not return "nothing happened", it returns a
CONFIDENT WRONG ANSWER, because the document it is polling really does exist and
really is old.

---

## 2026-08-19 — a single read of a MULTI-WORKER service is not a measurement

Distinct from the "read it 60 seconds after deploy" entry above, and it bit in
the same hour. That one was about TIMING — an async sync had not landed yet.
This one is about SAMPLING: the service genuinely returns different answers to
identical requests, and one read gives you whichever worker answered.

**Measured.** After deploying the NCAAF SP+ artifact I probed
`/ncaaf/api/cards?week=1` once, saw the SP+ signature, and reported PASS. Probing
**12 times** returned **9 PPA / 3 SP+** — the board was serving two different
models depending on which gunicorn worker handled the request. Cause:
`WEB_CONCURRENCY > 1` means several worker PROCESSES each build the app
independently and each holds its own `lru_cache` of the projection index. Workers
that read the mounted disk before `bootstrap_data_root` synced cached the OLD
artifact; workers that read after cached the new one. Both answers persist until
the workers restart.

**Why one sample is worse than useless here:** it is not noisy-but-centred, it is
BIMODAL. A single read does not give you an estimate with error bars, it gives
you one of two categorical answers, and which one is pure luck. I got the
flattering one and banked it.

**The rule going forward.** Verifying anything on a multi-worker service —
post-deploy or not — means PROBING REPEATEDLY and reporting the distribution,
not a value. If the probes disagree, that disagreement IS the finding: it means
the workers hold different state, and a deploy (which restarts them) is what
resolves it. Report "10/10" or "9 of 12", never a bare reading.

**Corollary that generalises past web:** any cache keyed per-process, per-worker
or per-container makes "what does the service return" a distribution question.
The same applies to the refresh-worker's own caches and to anything read through
a load balancer.

**Cost:** one wrong PASS reported to the user, inside the same hour as a wrong
FAIL from the timing version. Two opposite errors, one root habit — reading once
and treating the answer as the truth.
## Ancestry is the wrong test for a cherry-picked deploy `[2026-08-20]`

**Believed:** `git merge-base --is-ancestor <fix> <live_sha>` tells you whether
a fix is live.

**Actually:** a cherry-pick creates a NEW commit with a new SHA, so the
ORIGINAL commit is never an ancestor of it. Checking `#475` on web that way
returned NO for a deploy that was completely correct — the test was wrong, not
the deploy. Nearly reported a successful deploy as failed.

**Rule:** for any cherry-picked/scoped deploy — which on this repo is MOST of
them, because service live-SHAs are usually off-main — verify by CONTENT
(`git show <live_sha>:<path> | grep <the new symbol>`), never by ancestry.
Ancestry is only valid when deploying a commit that literally descends from
what is live.

## `HOT_ARTIFACT_PATTERNS` is about worker→web, not "can the sim see it" `[2026-08-20]`

**Believed:** `#474`'s and `#477`'s new artifacts were blocked from production
by the missing allowlist entries, so the work was inert until another lane
added them.

**Actually:** every consumer of those artifacts is the SIM, which runs
worker-side and reads them from its own `processed_root`.
`HOT_ARTIFACT_PATTERNS` governs PUBLISHING worker→WEB. A builder running
inside the worker refresh writes to the same disk its reader uses, so no
allowlist is involved in making it work. The allowlist buys external
auditability via `/api/ops/artifacts/export` — worth having, not blocking.

**Rule:** before treating an allowlist entry as a blocker, name the READER and
the disk it reads from. "Producer and consumer are both worker-side" and
"needs to cross to web" are different problems with different fixes, and
conflating them makes a lane wait on another lane for no reason.


## 2026-08-20 — OVERTURNED: I reported "CI is green" and closed the lane on a 16-run green streak that did not span the hours CI actually fails. **A streak is a SAMPLE. Check whether it covers the condition that breaks the thing.**

I fixed `#480`, watched **16 consecutive green runs** (2026-08-19 23:25-23:53Z),
wrote "CI green and holding" into `deploys.md`, `state.md` and the daily log,
and closed the lane. Every one of those runs was **before UTC midnight**.

From 23:57Z the next **29 consecutive runs failed**, on a cause that had been
there the whole time: 7 tests in `tests/test_archives.py` computed "today" with
`date.today()` — the runner's date, **UTC** on GHA — while every route under
test uses `central_today_iso()`. CDT is UTC-5, so **00:00-05:00Z the two
disagree** and CI is **structurally red about five hours a day, on the clock,
regardless of what anyone pushes**. Bucketed over 45 completed runs: 28 failures
inside the window, 11 successes outside.

**What I actually verified was "CI is green at 23:40Z."** I reported "CI is
green." Those differ by exactly the hours that matter, and the whole point of
the original request — *"anytime we deploy to git there are CI errors"* — was
most likely THIS defect, which I then wrote off as fixed.

**The tell I had and ignored:** the user's complaint was *"anytime"*. I found a
cause that explained a 26-hour continuous outage and stopped, without asking
whether it explained the *shape* of what they described. A cause that fits the
window you sampled is not the same as a cause that fits the report.

**Rules:**
- Before declaring a periodic gate healthy, ask **what makes it fail** and
  confirm the evidence spans that. For anything time-dependent, that means a
  run in each phase — here, one inside 00:00-05:00Z and one outside.
- **A green streak with a uniform property is one observation, not N.** Sixteen
  runs inside a 28-minute window are sixteen samples of the same minute-scale
  condition.
- **`date.today()` in a test is a latent timezone bug in any repo whose product
  is timezone-pinned.** Assert against the SAME clock the product uses. This one
  had already been found once —
  `test_wnba_cards_api_without_date_uses_today` carries a comment naming the
  cause precisely — and fixed in only that single test. **Fix the choke point
  every caller shares, not the instance in front of you.**
- **A local pass on a Central dev box is not evidence about a UTC runner**, for
  the same structural reason `conftest.py` is not evidence about `unittest`
  (2026-08-19, same session): the harness differs from the gate's harness.


## 2026-08-19 — READ THE WRITER BEFORE INSTRUMENTING THE READER. A branch that turns on a key is answered by the SCHEMA, not by a deploy.

**Overturned belief, recorded verbatim from `.syndicate/deploys.md`
(2026-08-16 04:5xZ):** the uncached odds_history shard load inside
`_enrich_games_with_tracked_market_lines` was *"the best candidate on the table"*
for the refresh-worker's ~2GB excursion, and the entry closed with *"What would
settle it: one bounded in-pass measurement around `:2294` (bytes read, parse
peak, call count per build), **which needs a deploy**."*

**It did not need a deploy, and the "candidate" was not a candidate — it was
DEAD CODE.** The load existed only to consult `doc["games"]` before adopting the
shard over another document. odds_history shards have no `games` key. That is
answerable from the repo in about three minutes:

- **one writer** — `odds_refresh_tracking._write_odds_history_artifact`, called
  three times with a single dict literal (`:1859`):
  `{schema_version, sport, shard_key, date, updated_at, history_limit, markets}`
- **every other consumer reads `markets`** — `basketball_market_board.py`,
  `soccer/market_board.py`, `odds_lifecycle.py`, and the same module's own
  `_mlb_odds_history_payload`
- **`git log -S'"games": '` over the writer** — no revision ever emitted it
- **three real shard copies on disk** — `has_games=False` on all three

So the branch could never fire, `game_lines_doc` was never replaced, and a
worker-only, every-build, uncached multi-hundred-MB read was pure cost. Three
sessions had it in view and each reached for a deploy-and-measure.

**THE RULE.** When a consumer's expensive work is gated on a key being PRESENT,
the cheapest discriminator is the WRITER's schema, not instrumentation of the
reader. Instrumentation tells you the branch did not fire on the days you
watched; the writer tells you it can never fire. **Those are different claims and
only the second one lets you delete the code.** Applies to any `if
doc.get(k): <expensive>` — read the producer before you plan a measurement, and
before you record the reader as a "candidate".

**Corollary, and it is why this hid so well:** the load changed no output, so
every behavioural test in the suite passed with it and passes without it. Dead
cost is invisible to correctness tests by construction. The guard that replaces
the deleted code must therefore assert the INVARIANT, not the behaviour —
`tests/test_mlb_cards_worker_hydration_cost.py::test_odds_history_shard_schema_has_no_games_key`
parses the writer's literal and fails if `games` is ever added, which is the only
condition under which the removal would have been wrong.

**Not a licence to delete on a hunch.** The standard met here was four
independent confirmations (single writer, literal schema, `git log -S`, real
artifacts on disk) plus an asserted invariant plus a regression guard that fails
if the read returns. Fewer than that is a belief.


## 2026-08-20 — FORBIDDEN: never repair, rebuild or optimise a scheduled job without first establishing that anything still CONSUMES it. Fixing a dead job can be worse than leaving it broken.

I found `Daily Update`'s artifact backup capturing **0.10%** of what it claimed,
measured it properly, asked the user to choose a scope, and rebuilt it to
**80.6%**. Good work on a feature the user then said they do not use:
*"we no longer use that daily update feature, everything runs on render."*

**The rebuild was not merely wasted — it was actively harmful, and nearly
shipped.** The job had not reached its commit/push step since 2026-07-15
(billing lock, then `#480`). My `#480` and `#482` fixes cleared that path, and
`#481` widened the pull. **The next scheduled run — ~3h40m away — would have
pushed ~370 files / ~51MB to `main`, every day.** A broken job pushes nothing;
the repaired one pushes 51MB/day into a repo whose owner does not read it.

**What I had and did not use.** `CLAUDE.md` says the `data/**` tree is *"a
cold-start safety net... not a snapshot of what production computed"* and that
Render is the source of truth; the workflow's own header says Render *"now
generates this data live and continuously -- this Action no longer regenerates
it."* Every one of those describes a job being hollowed out. I read them as
context for *how* to fix the backup rather than as evidence about *whether* to.

**Rules:**
- Before improving any scheduled/automated job, answer **"what reads its
  output, and when did that consumer last need it?"** If the answer is not
  concrete, ask the user before doing the work — not after.
- **A long outage is itself evidence.** Five weeks dead with nobody noticing is
  a fact about demand, not just about the bug. I treated "it has been broken
  since 2026-07-15" purely as urgency; it was equally a signal nobody depended
  on it.
- When repairing an unblocked path, **enumerate what the repair lets happen
  next.** The dangerous moment is not the broken state, it is the first
  successful run after the fix.

---

## 2026-08-20 — A STANDING INSTRUCTION BLOCK GOES STALE SILENTLY, AND STALE READS AS AUTHORITATIVE

`.syndicate/state.md` carried a block headed "STANDING RIDEALONG FOR ANY
refresh-worker DEPLOY" naming branch `deploy/worker-ladders-ridealong` /
`5c2851a4`. That branch had SHIPPED hours earlier inside `041188cb`. Any session
following the instruction would have re-cut a spent branch onto the live SHA and
believed it was carrying something.

The block even warned "it goes stale whenever the worker moves" — and the
warning did not help, because nothing makes the reader check. A note that
describes a MOVING target is a liability the moment its author stops updating it.

**How to apply.** A ledger block written as an INSTRUCTION ("cut from THIS",
"deploy X") must carry the reading that proves it is still valid, and the
instruction must be re-derived, not trusted:
- Before acting on a named branch/SHA in the ledger, check it is not already an
  ancestor of the live SHA. One command, and it is the difference between
  carrying a change and carrying nothing.
- When you SHIP the thing a standing block points at, updating that block is
  part of shipping. It is not documentation debt; it is a live instruction that
  is now false.
- Prefer blocks that say what to CARRY (file paths + a source commit) over ones
  that say what to DEPLOY (a pre-cut branch). Files stay true across worker
  moves; a pre-cut branch expires every time the service moves, and this one
  expired three times in two days.

## 2026-08-20 — "Everything upstream is correct" is a REASON TO LOOK FURTHER DOWN, not a reason to doubt the symptom

The MLB ladder was 28 hours stale on web while, on the worker: the rebuild ran on
schedule, `is_stale()` returned `fresh`, and that verdict was TRUE — the content
really was newer than the odds and sims. Five successive hypotheses died against
correct-looking components before the real one (the publish sweep refusing the
file at `_PUBLISH_MAX_BYTES`, 13,678,982 vs 12,582,912).

**The generalisable error:** I kept re-examining whether the upstream verdict was
WRONG, when the actual question was WHICH COPY it described. `is_stale()` reads
the worker's disk; the symptom lived on web's. A component can be perfectly
correct and still tell you nothing about the system, because it is answering a
question about a different machine.

**How to apply.** When a verdict is right and the symptom persists, stop
auditing the verdict. Ask: *whose state does this reading describe, and is that
the state the symptom is in?* On this repo that question has a standard answer —
worker disk vs web disk — and it should be the FIRST fork, not the last.

Corollary that cost the most time: a size ceiling makes a failure that GROWS
INTO EXISTENCE. Nothing was deployed on the day it broke; the file crossed a
line. "It used to work and stopped, with no deploy" should raise SIZE early.

## 2026-08-20 — I NAMED A VERIFICATION CHECK WITHOUT CONFIRMING THE INSTRUMENT COULD SEE

At checkpoint I wrote into `state.md`: "settle it by checking whether roster
artifact mtimes moved after 02:03Z". That check is **impossible**. `roster_objs/`
is worker-local and never published: the read-side allowlist looks like it
permits it, because `fnmatch` lets `*` cross `/`, but the publish SWEEP uses
`Path.glob`, where `*` does NOT. Export returns 0 files.

So a future session would have followed a confident instruction into a dead end,
and the instruction carried my authority because it sat in `state.md` next to
verified facts.

Then three fallback readings each failed for a DIFFERENT reason, and each looked
like a negative result rather than a blind one:
- log search for the `ROSTER_REBUILD armed` print: 0 hits — but wrapper stdout
  is redirected to disk and never reaches Render's collector.
- sim status `command`: carries the right argv, but the endpoint served an
  IN-FLIGHT run's launcher record, and completed status files are not exported.
- `ALL_PROCESS_MEMORY` cmdlines: stored TRUNCATED to the script path, so the
  flag — appended late in argv — could never appear.

**How to apply.** `fnmatch`-vs-`glob` is a real trap in this repo: they disagree
on `/`, so "it matches the allowlist" does NOT mean "it is published". Check the
SWEEP's semantics, not the reader's.

More generally: **a named verification is a claim, and it needs the same
evidence as any other.** Before writing "check X to settle it", run X once, or
say explicitly that it is untried. And when a check returns "absent", establish
what a PRESENT reading would look like on that instrument before treating the
absence as an answer — three instruments in a row here reported absence that was
about the instrument, not the world.

## 2026-08-20 — OVERTURNED (pre-registered): soccer is not under-dispersed anymore, and fixing dispersion + missing inputs did not close the gap to the market

`soccer-model-dispersion` opened 2026-08-18 on a measured, specific
hypothesis: the model's Brier loss to the closing line was because it was
UNDER-DISPERSED (mean model `stdev(P home)` 0.1575 vs market's 0.1811,
narrower in 8 of 9 leagues) -- not because its ratings were wrong, its
under-confidence itself. The lane wrote its own falsification test BEFORE
any fix was attempted: *"If the Brier gap does not close while stdev rises
to market's, under-dispersion is NOT the binding constraint and the cause is
the ratings/inputs, not the spread. That is a real outcome and must be
recorded, not retried with a bigger knob."*

Roughly 14 hours of work followed: an xG double-count fix (the model had
been silently weighting goals-as-xG at 0.36 instead of 0.22 in one term),
a falsified shots-weight shrink reverted, three genuinely missing inputs
sourced and wired end-to-end (`possession_share`, `set_piece_goal_share`,
`starters_available_share`), a fourth (`pace_seconds_per_event`) sourced,
tested, and correctly abandoned on its own cheap falsifier, a
market-confidence prior wired and disclosed as methodologically weak by
construction, and — the largest single fix — a backtest-vs-production
pipeline mismatch that had been silently rating 5 of 9 leagues from the
wrong data source since the backtest was written.

**The 2026-08-20 re-run measured exactly the falsification condition.** Mean
model stdev rose to 0.1922, past market's 0.1859 -- under-dispersion is
gone. The Brier gap did not close: still worse than market in 8 of 9
leagues, `belgian_pro_league` the same single exception as the original
diagnosis, completely unchanged by the entire session's work.

**Why this is recorded as a success for the process, not a failure of the
session.** A hypothesis that gets tested and falsified by a test written
before the work started is not a wasted session -- it is the single most
trustworthy kind of negative result available, because nobody could have
retrofit the test to fit the outcome. The alternative -- declaring the
gap "narrower" on a different match set, or quietly moving to a sixth input
field without ever checking the falsification condition -- was available and
was not taken.

**The general rule.** When a hypothesis names a SPECIFIC mechanism (here:
"the spread is too narrow"), the falsification test must isolate that
mechanism from every other plausible cause, and the fix that follows must be
checked against the SAME test that motivated it -- not just "did some
number get better." Fixing dispersion and separately improving input
completeness are BOTH good engineering, and BOTH were necessary regardless
of outcome (an under-fed engine and an under-dispersed one are real defects
on their own terms) -- but neither is evidence for the hypothesis that
motivated the work unless the specific falsification condition is checked,
not just "the model changed and something moved."

**What the next hypothesis has to be, precisely because this one is now
closed off:** not "the spread is wrong" (tested, false) and not "an input is
missing" (the checklist alarms remaining are genuine data-availability gaps,
not misrouted producers, after this session's sweep) -- the remaining
candidate is systematic BIAS in what the ratings compute, which requires a
different diagnostic (reliability-curve decomposition per league/bucket, not
a pooled regression or a stdev check) than anything this session ran.

Related: [[project_e2e_assessment_aug_2026]] (the standing note that soccer's
model accuracy was "unmeasured" before this lane existed is now further
refined -- it IS measured, repeatedly, and the measurement has converged on
a specific negative result rather than remaining an open question).

---

## 2026-08-20 — CORRECTED BELOW. FORBIDDEN: buying data before probing it exists — and NEVER diagnose a vendor from your own broken query

**I verified the COST of a purchase carefully and never verified the PREMISE.**

NFL preseason picks are served from a model measured at 4.3x under-dispersed
(margin SD 0.97 vs a market 4.21, live), and no local data could grade it —
`historical_odds/closing_lines_*.json` covers September to February only. So I
extended the backfill script with a `--preseason` mode, dry-ran it, estimated
4,048 credits, set an 8,000 ceiling with 2x headroom against the script's own
documented overrun history, and executed.

**Result: 7,528 credits spent, ZERO preseason games captured.**

    2023  257 events, earliest kickoff 2023-09-08   (preseason ran 08-02..08-28)
    2024  264 events, earliest kickoff 2024-09-07
    new events not already on disk:  2023 -> 0 of 257
                                     2024 -> 1 of 264

**~~OddsAPI does not carry NFL preseason.~~ THAT CONCLUSION WAS FALSE — see the
correction at the end of this entry.** What was true: querying the endpoint I
queried, at an August date, returned only future regular-season events, so every
credit re-bought regular-season lines already sitting in the repo.

**The error is not the estimate — the estimate was fine and the ceiling caught
the 1.86x overrun exactly as designed.** The error is that every one of those
safeguards protects against SPENDING TOO MUCH and not one of them asks WHETHER
THE DATA IS THERE. I treated "NFL is covered by OddsAPI" as implying "all NFL
phases are covered". Coverage of a sport does not imply coverage of its
preseason, its lower divisions, or any other segment.

**THE RULE.** Before any paid backfill, spend the smallest possible amount to
prove the data EXISTS — here, ONE events call at ONE in-range date, 1 credit,
and read the earliest `commence_time` that comes back. If it is outside the
window you are buying, stop. A dry run costs nothing and validates ARITHMETIC;
only a real probe validates COVERAGE, and the two are not substitutes.

**Generalises past OddsAPI:** any paid or rate-limited source. The question
"can I afford this?" and "is the thing I want in there?" are independent, and
answering the first with rigour creates a false sense of having answered both.

**Consequence that still stands:** NFL preseason CANNOT be graded against the
close — not from local data and not from OddsAPI. Any decision about serving
NFL preseason picks rests on the under-dispersion proxy plus default-deny, and
must be labelled as such rather than as a measured loss.

### CORRECTION, same day, after the user asked "are you sure you're looking correctly"

**They were right and I was wrong. OddsAPI DOES carry NFL preseason.** It lives
under a SEPARATE SPORT KEY, `americanfootball_nfl_preseason`, which
`/v4/sports?all=true` lists as active. Verified with 1-credit probes:

    /historical/sports/americanfootball_nfl_preseason/events
        2024-08-10 -> 11 events, ALL August
        2023-08-12 ->  8 events, ALL August

The real bug: this script hardcodes `SPORT = "americanfootball_nfl"`. My
`--preseason` flag changed the DATE SOURCE and **not the sport key**, so it
asked the regular-season endpoint for August and got exactly what that endpoint
correctly returns — future regular-season games. A flag that must change two
things and changes one is indistinguishable from a working flag, because the
output is well-formed either way.

**THE DEEPER ERROR, and it is worse than the wasted credits.** I concluded a
fact about the VENDOR — "OddsAPI does not carry NFL preseason" — from the output
of MY OWN BROKEN REQUEST, wrote it into this file and into a commit message as
established fact, and used it to tell the user that measuring NFL preseason was
impossible. A null result from a query you have not verified is a statement
about YOUR QUERY, not about the world. This file already carries
"absent signal is about the emitter"; I applied it to log lines and not to an
HTTP response.

**Compounding it:** while investigating I wrote two follow-up probes that read
the key only from `.env` — but `ODDS_API_KEY` lives in `os.environ`, and `.env`
is 157 bytes with no odds key at all. They sent an EMPTY key and got 401s, which
I briefly read as more evidence about the vendor. Three self-inflicted signals
in a row, all pointing at an innocent API.

**What actually holds:** probe before buying (the guard added between phase A and
phase B is right and would have caught this at 28 credits), AND before believing
any negative result about an external system, prove your request was
well-formed — ideally against a case you KNOW should return data.
## An unbiased mean hides a broken distribution `[2026-08-20]`

**What we believed:** the WNBA live win-probability path was roughly fine. Its
constants were admittedly un-backtested, but nothing pointed at them, and any
aggregate check looked clean.

**What was actually true:** it was severely UNDERCONFIDENT. Graded over 212
games / 73,878 live samples, samples it priced 0.6-0.7 actually won **91.3%**;
samples it priced 0.3-0.4 won **11.6%**. The scale was ~2.5x too wide and
compressed every probability toward 0.5. Brier 0.1896 -> 0.1644 after refit.

**Why it survived so long:** the MEAN was already right — 0.573 predicted vs
0.571 actual. Every summary statistic that averages over samples said the
model was unbiased, and it WAS unbiased. The defect was in the second moment,
not the first. A calibration table by predicted-probability bucket exposes it
in one glance; no amount of staring at aggregate accuracy ever would.

**The rule:** for any probability output, "is the average right" and "is the
distribution right" are different questions, and only the second one tells you
whether an individual price is usable. Bucket predictions and compare each
bucket's mean prediction to its realised rate. A model can be perfectly
unbiased on average while being wrong on literally every bet you place with it.

**Corollary that cost me a wrong conclusion in the same session:** when fitting
a replacement, fit INSIDE the real function's structure. My first fit used a
bare logistic while the shipped function also blends toward a pregame anchor,
so part of the apparent gain came from silently dropping the blend rather than
from the scale. Refitting within the real structure gave the honest number
(+0.0261). And the variant that scored best of all — blend removed entirely —
was an ARTIFACT of grading with a neutral 0.5 anchor, which makes blending
toward it pure noise by construction. In production that anchor is a real
estimate. A fit is only as meaningful as the harness's fidelity to production.

## 2026-08-20 — FORBIDDEN: an assertion whose subject is a TEMPLATE must not take the ambient `data/` mirror as its input. Pin the fixture, then prove the pin is load-bearing.

`test_archive_launch_links_and_tracker_copy` asserted five home-page markers
(`Live slate`, `Compact rail`, `Pregame only`, `Open Live Lens`, `Live only`).
Its own comment says these exist so that losing one fails the build — i.e. the
subject is the TEMPLATE. But `_home_sport_stack.html` renders them **per sport**,
and `Live slate` needs `sport.active_today`, so the assertions actually depended
on `build_home_overview()` finding a sport for whatever date
`central_today_iso()` resolved to. **The test's subject and the test's input were
different things.**

Measured: CI run `32331841627` at 23:28 CT 2026-08-19 rendered the sport stack
completely empty (`0 sports tracked`) and failed. The same test passed at 06:25
CT and 08:08 CT. **The page was correct at every one of those moments.**

**Rules:**
- If the thing under test is a contract (template markup, a payload shape, a
  route's wiring), **supply the data**. Ambient `data/` is an input nobody
  controls: it varies by hour, by checkout, and by whatever the mirror last
  synced — and per `CLAUDE.md` it is a lossy mirror that is never evidence about
  production anyway.
- **Pinning is only half the fix, and the dangerous half is the other one.** A
  pinned test that can no longer fail is worse than a flaky one, because it
  reads as coverage. Run the off != on probe: break the fixture and confirm the
  test fails. Here, flipping `active_today` to `False` produced
  `AssertionError: 'Live slate' not found` — that is what makes the green
  meaningful.
- **A green run proves only what its conditions covered.** `#487`'s CI greens
  all ran outside the failing window with a populated mirror, so they prove NO
  REGRESSION and nothing about the empty-slate case; the structural argument and
  the probe are what carry that. Same trap as the 2026-08-20 streak entry above.

**Incidental, and a real landmine:** Jinja's `rail['items']` on a plain dict
without an `items` key does **not** render empty. Subscript falls back to
attribute access, returns the `dict.items` METHOD, and iteration dies with
`TypeError: 'builtin_function_or_method' object is not iterable`. Any rail dict —
fixture or real — that omits `items` raises rather than degrades.


### 2026-08-20 — FORBIDDEN: never read a ledger file with `git show <rev>:<path>` from Git Bash. It returns EMPTY, and empty reads as "another session deleted it"

**What happened.** Checkpointing `#387`, I checked whether my deploy record had
survived a concurrent session's merge:

    git show "origin/main:.syndicate/deploys.md" | grep -c "d0ea983d"   -> 0
    git show "origin/main:.syndicate/lanes.md"   | grep -c "^### "      -> 0

Zero lane blocks in `lanes.md`. Fourteen lane slugs present in my copy and
absent from main. The merge commit's own message said *"deploys.md — theirs
wholesale"*. Every piece of evidence agreed, and I was one step from filing an
incident saying **another session's merge had deleted the entire lane ledger and
every lane's deploy record**.

**All of it was false.** MSYS path conversion rewrote the argument:

    origin/main:.syndicate/deploys.md   ->   origin\main;.syndicate\deploys.md

`git show` then failed (once loudly, `fatal: ambiguous argument`; thereafter
silently to an empty stream, because the failure went to stderr and only stdout
was piped into `grep -c`). Re-read in PowerShell:

    lanes.md bytes 126,326   lane blocks 14   my block 1
    deploys.md  d0ea983d x4   plays_dropped=1125 x1

**Nothing was lost. Nothing needed restoring.**

**Why this one is dangerous specifically.** The failure mode is not "an error" —
it is *a clean zero*, and a clean zero from a ledger file is indistinguishable
from deletion. Worse, it points AT A NAMED PEER. The conclusion I nearly
committed was not "my tooling is broken", it was "session X destroyed the
ledger" — a false accusation, in writing, in the shared record, about work
another session had done correctly. `#retraction-is-not-innocence` cuts both
ways: an accusation retracted later still cost the accused session's next reader
their trust in the file.

**Two independent rules, and the second is the general one:**

1. **On Windows, `<rev>:<path>` goes through PowerShell, never Git Bash.** Also
   affects `git cat-file`, `git diff <rev>:<path>`, `git log <rev> -- <path>`.
   `MSYS_NO_PATHCONV=1` works but is one forgotten prefix away from the same
   silent zero; the shell choice is the durable fix.
2. **A destructive conclusion about ANOTHER session must be reproduced with a
   second, differently-shaped instrument before it is written down.** The tell
   here was available and I walked past it: the *same* Git Bash command against
   `syndicate/features/mlb/cards.py` returned 3 and 5 — non-zero — while every
   `.syndicate/*` path returned 0. Paths with a leading dot failed; paths
   without one worked. **A "deletion" that lands exactly on the paths whose
   syntax differs is a tooling artifact, not an act.** Partition your null
   results by the shape of the query before you believe them.

**This rule already existed in personal memory
(`git_bash_mangles_rev_path_args`, from a false "file ABSENT") and I hit it
anyway** — which is why it belongs here, in the file that is read at session
start, rather than only in a memory that is recalled by relevance.

---

## 2026-08-20 — "strictly dominated" is a different diagnosis from "broken", and it changes the fix

**The NCAAF model has REAL predictive power and is still worthless for betting.
Those are compatible, and I spent a session treating them as if they were not.**

Measured on 751 clean out-of-sample games, fitting
`actual = a + b*market + w*(model - market)`:

    b (market)           +0.990   CI [+0.909, +1.076]   closing line UNBIASED
    w (model deviation)  -0.028   CI [-0.130, +0.069]   ZERO information

    r(market, actual) +0.645   R^2 41.6%
    r(model,  actual) +0.421   R^2 17.8%
    r(model,  market) +0.671

The model explains 17.8% of realised margin variance — genuine signal, not a
broken engine. But its DEVIATION from the market explains nothing, with a CI
tight enough to rule out even 10% weight. Everything it knows, the market
already knows; where they differ, it is noise.

**WHY THIS MATTERS MORE THAN THE VERDICT.** Every remedy attempted failed, and I
was treating each failure as its own puzzle: the ATS thresholds (filtering
harder made it WORSE), the blend weight, the subset search, three scalar totals
fixes, a scale sweep from 6 to 24, a 5.8-sigma returning-production feature.
**They are all the same fact.** A strictly dominated model has no threshold, no
weight and no subset that helps, because its unique variance is noise rather
than signal concentrated somewhere. Recognising domination early would have
saved most of those experiments.

**The diagnostic that distinguishes the two cases, and it is cheap:**

    BROKEN     low r(model, actual)         -> fix the engine
    DOMINATED  decent r(model, actual) BUT
               w ~ 0 on the deviation       -> the engine is fine; it is
                                               MISSING INPUTS the market has

One regression on a ledger answers it in seconds. Run it BEFORE the threshold
sweeps, not after.

**It also killed a framing I had been repeating.** I called the model
"under-dispersed" — true for NFL preseason (SD 0.97 vs a market 4.21) and FALSE
for NCAAF, where the model is OVER-dispersed (15.14 vs 13.16 vs a realised
20.33). Carrying one sport's shape onto another produced a wrong mental model of
the defect and pointed at `SP_RATING_SCALE`, which §0 had already exonerated
across every value from 6 to 24.

**The actionable number:** the gap is **23.8 points of R^2** (41.6 − 17.8). That
is the size of what the market knows and the model does not, and it only closes
with information the model currently lacks — not by re-weighting what it has.


### 2026-08-20 — FORBIDDEN: never re-apply a ledger edit with `git checkout <sha> -- <ledger-file>`. It is a REVERT of everyone else's entries, wearing the clothes of an append

**What happened.** Closing out `#387`, I needed to move one 43-line note onto a
newer `origin/main`. I ran:

    git checkout 0f9dc4d8 -- .syndicate/log/2026-08-20.md

That commit was built on an older `origin/main`. The checkout replaced the file
WHOLESALE with my stale copy. The diffstat:

    1 file changed, 41 insertions(+), 400 deletions(-)

**400 deletions — other sessions' log entries for the same day**, staged and
committed, one `git push` from landing. Caught only because the diffstat was
read before pushing. Reset, then re-done as a genuine append: `43 insertions(+),
0 deletions(-)`.

**Same root cause as the OTHER defect in the same ten minutes**, which is why
this is one rule and not two: a `str.replace(anchor, …, 1)` on `lanes.md`
anchored on `- Blocked by: none.` — a line present in several lane blocks — and
attached MLB pickup notes to the **soccer** lane. Both are *a ledger write that
was not scoped to what I actually changed*.

**The rules:**
1. **Ledger files are append-mostly and multi-writer. Never restore one from a
   revision.** To move a note across a rebase, re-append the note; do not
   re-materialise the file.
2. **`git diff --cached --numstat` before every ledger commit.** For an append,
   deletions MUST be `0`. Any non-zero deletion count on a shared log/ledger is
   a stop-and-look, not a formatting artifact.
3. **An in-place edit must be anchored on a string unique to its block, or
   bounded to that block's span** — slice the block, assert the anchor occurs
   exactly once inside it, then edit. Asserting uniqueness is what caught the
   second one.

**Why this rates a FORBIDDEN rather than a note:** the failure is SILENT and
INVERTED — the intent was "add my line", the effect was "delete four hundred of
theirs", and every command involved is one people run daily.
---
---

## 2026-08-20 — ONE ERROR IN FIVE GUISES: validating against a PROXY, not the objective

**Consolidates five entries this lane wrote on 08-19/08-20** (originals verbatim
in `learnings_archive_2026-08-20.md`). They are the same mistake wearing
different clothes, and seeing them together is the point — each looked novel
while I was inside it.

| guise | what I optimised | what it actually cost |
|---|---|---|
| **dispersion ≠ accuracy** | matched the market's margin SD (ratio 1.06) and called NCAAF "calibrated" | said nothing about being RIGHT; the model still lost to the close by +3.563 MAE, t=+17.20 |
| **a 5.8σ proxy that did not transfer** | returning production predicted SP+ MOVEMENT at r=+0.207, n=786, 6/6 seasons | against realised MARGINS: pooled ΔMAE −0.062, t=−0.89, opposite sign in season 2. Code removed. |
| **MAE ≠ playability** | point accuracy | the model beats nothing: it trails always-bet-the-underdog by 4.4 ATS pts (NCAAF, 735 bets) and 4.2 (NFL preseason, 95) |
| **a slope ≠ a bet** | regression t=−1.81 extrapolated to ~53.5% ATS | the actual bets: 54.5 / **50.0** / 58.3%, every CI spanning 52.4%, NON-MONOTONIC |
| **rows ≠ bets** | 1,075 per-book rows → t=+4.00 "MODEL_WORSE" | one row per GAME: t=+0.87. Per-book overstated significance **3.4×** |

**THE RULE.** Before building anything, ask what the number is measured
AGAINST. If it is not the quantity the model is judged on — realised outcomes,
in bets, at the unit you would actually wager — it is a screen, never a
substitute. Rigour in validating a proxy does not convert it into the target: the
5.8σ prior was multi-season and positive-controlled, and still transferred
nothing.

**AND THE CHEAP ORDERING THAT FOLLOWS.** Regress the MARKET'S OWN ERROR on a
proposed input before building it. That took two minutes and killed eight
situational factors (all |t|<2 on 1,746 games) and the injury lever (272 games,
all null); the same answer for returning production cost a build, two
full-season backtests and a revert. **Always include a positive control** — the
situational table's own residual mean (+0.983, t=+2.70) is what made its nulls
mean anything, exactly as recruiting at +0.482 validated the SP+ residual.

**Harnesses:** `grade_football_model_weight.py` (dominated vs broken),
`grade_football_playability.py` (ATS vs naive baselines),
`test_ncaaf_situational_edge.py` (market-residual screen).
---

## 2026-08-20 — A NULL HAS A SAMPLE SIZE. I called a lever dead, revived it, then buried it properly.

**The same question answered three ways as n grew, and only the third was
honest about its own power.**

    272 games (2025)       all null            -> I wrote "THE INJURY LEVER IS DEAD"
  1,083 games (2022-25)    two measures |t|>2  -> forced to correct: "UNRESOLVED"
  4,431 games (2009-25)    all null again      -> RESOLVED, with the floor stated

I had spent the whole day refusing to over-read POSITIVE results and then
over-read a NEGATIVE one. The section's own limits paragraph said n=272 could
not detect a small effect; the headline said "dead" anyway. **"No effect
detected" is a statement about the test's POWER, and dropping that turns a
provisional finding into a false certainty.**

**What the final answer looks like when done properly:** all four measures null
(best t=−1.74) AND *"at this n the test detects a slope of ~0.18 pts; the
observed is −0.146"*. That second clause is the difference between "dead" and
"dead, and here is what I could have seen".

**THE FOUR-SEASON REVIVAL WAS A FALSE POSITIVE, and the per-season table is the
only thing that caught it.** Pooled 2022-25 read t=−2.10 and −2.23. Across 17
seasons the slopes swing **+0.7291, +0.7061, −0.9451, −0.8005**, with THREE
crossing |t|=2 in BOTH directions and 12 of 17 negative against ~8.5 expected by
chance. **Pooled significance without per-season replication is one finding, not
seventeen.** Print the per-season table beside every pooled row.

**AND THE DATA I ALMOST BOUGHT WAS FREE.** The plan was ~10,000 OddsAPI credits
to backfill 2018-2021. Two probes cost 3 credits and replaced it entirely:
OddsAPI historical NFL returns **zero events for 2018/2019** (coverage starts
2020; empty responses are not billed), and **nflverse `schedules/games.csv`
already carries `spread_line` and `total_line` back to 1999** in 2.2 MB
alongside final scores.

This is the SECOND time in one day that "buy the data" was the wrong move and a
cheap probe was the right one — after 7,528 credits went on a wrong sport key.
**Before any purchase: (1) does the vendor have it, (2) does something local
already have it.** The second question is the one I skipped both times, and the
answer here had been sitting in the repo's own ingestion module the whole time.
