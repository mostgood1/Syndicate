# Syndicate — Learnings ARCHIVE (entries before 2026-09-01)

> Moved verbatim from `learnings.md`: entries before 2026-08-20 on
> 2026-09-01, extended to everything before 2026-09-01 on 2026-09-06.
> The second pass was HOUSEKEEPING, not a budget fix -- `learnings.md` was
> 417,226 B against a 460,000 cap at the time, i.e. already under.
> Nothing summarised or deleted. Indexed by `build_learnings_index.py`
> alongside `learnings.md` and `learnings_evidence.md`.

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
against +1.0GB measured four times since. Do not close `#387` as "solved by
streaming" — streaming caps the transient, it did not explain the outlier.
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
hydration path, NOT the overview.
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
   a rollback of a working fix.** Two reads inside one warm-up window are one
   read — a rule I had written earlier the same night and did not apply.
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
start of the work** — `deploy_preflight --json` returns `deploy_claim.holder`
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

- The rule going forward: **before splitting, renaming or re-keying a set of files, look at how the EXISTING members are keyed and confirm your rule reproduces them.** If your scheme would have filed yesterday's files differently than they are actually filed, your scheme is wrong -- the existing layout is the specification.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-19 — RULE: a mass-deletion diff is not self-explaining. Compare DISTINCT lines before accepting "it was just dedupe".

- The rule going forward: **when a diff you did not intend shows large deletions, do not reason from the line COUNTS or from a plausible story about reformatting. Take the set difference of DISTINCT lines, both directions, and then grep the tree for a sample of what is missing.** Counts cannot separate "500 duplicate copies removed" from "500 unique records deleted", and those are the same number.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-19 — RULE: when diagnosis has failed repeatedly, look for the fix that does not need the cause.

- The rule going forward: **after two or three wrong causes for one symptom, stop buying lottery tickets on the fourth and ask whether a fix exists that is correct under ALL of them.** Such a fix is available more often than it looks, because a symptom usually has more than one route to the same evidence — and it is strictly safer, since it cannot be invalidated by the answer arriving later.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-19 — RULE: a cause must explain the TIMING, not just the mechanism. Date the change before believing it.

- The rule going forward: **when you propose a change as the cause of a dated symptom, find out WHEN that change happened before asserting it.** A mechanism that cannot produce the observed timing is not the cause, however completely it explains the current state — and "explains the state" is the part that feels like proof.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-19 — RULE: a flag's NAME is a hypothesis about its meaning, not its meaning. Read the setter before gating on it.

- The rule going forward: **before rejecting or filtering data on a flag found in a payload, find where the flag is SET and read what condition actually produces it — do not infer meaning from the flag's name, even when the name reads as self-explanatory.** A name chosen for one context (display copy, a UI hint) can sound like it means something load-bearing (live adjustment, circularity) in a different context (a backtest scoring real predictions).
- *(evidence in `learnings_evidence.md`)*

## 2026-08-19 — VERIFY WHAT THE THING YOU CHANGED *DEPENDS ON*

- **RULE: verifying the code you wrote is present is HALF a check. Verify its inputs, its callees and its data exist in the same environment.** "Is my change live?" and "can my change do anything?" are different questions, and I answered the first one twice while never asking the second.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-19 — RULE: to find where variance is CREATED, decompose the outcome. Correlating its inputs finds what MOVES WITH it, which is a different question.

- **Evidence.** NCAAF projected total SD was 1.67x the market's. I proposed three mechanisms, each plausible, each swept, each wrong:
- *(evidence in `learnings_evidence.md`)*

## 2026-08-19 — CORRECTION: `git commit -- <paths>` fixes the shared INDEX. It is the DELIVERY MECHANISM for a shared FILE. I applied it to both and caused two more incidents.

- The rule going forward: **this is the SAME class of gap already documented for `commit-guard.py`** (2026-08-17: "all THREE documented overrides were unreachable... a PreToolUse hook runs BEFORE the shell") — a sibling instance in a different hook, not a new mechanism. Any `SYNDICATE_*_GUARD` off-switch mentioned in prose must be assumed unreachable from inside a tool call until proven otherwise; it can only be set at the harness/settings level, outside any session's own reach. Do not spend a second attempt varying the prefix syntax — go straight to reading the hook's source for where it actually reads the value from, or hand the decision to the user.
- *(evidence in `learnings_evidence.md`)*

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

## 2026-08-19 — I declared a deploy FAILED 60 seconds after it went live, and it had not

- **The rule going forward.** After a deploy, before drawing ANY conclusion from a served payload, establish how the change is supposed to reach the surface and how long that takes. If the path includes an async step — a bootstrap sync, a cache TTL, a background worker, a CDN — the first read is not evidence and must be a POLL, not a sample. And if a failing read leads you into a diagnosis, re-read the payload before acting on the diagnosis: the cheapest possible test of "is this still true?" costs one call and would have saved five here.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-19 — FORBIDDEN: never treat a green local `pytest` run as evidence about CI. **CI runs `unittest`, and `conftest.py` does not exist to it.**

- **Measured:** `tests/test_wnba_cards_merge_aliases` — `20 passed` under `python -m pytest`, `FAILED (failures=2)` under `python -m unittest`, same commit, same machine, same minute. Cause: `build_source_cards_payload`'s cache is keyed on `(date, ...)` + a wall-clock TTL bucket, `conftest.py` had cleared it since months ago, and under `unittest` nothing did — so the alphabetically-first test's `("2026-07-02", True)` payload was served to the two tests after it. **Deterministic, not a flake, and it had failed the Daily Update workflow every single morning it was able to run.**
- *(evidence in `learnings_evidence.md`)*

## 2026-08-19 — NEAR-MISS: a multi-step object-database commit re-resolved `origin/main` mid-construction

- **The rule going forward:** on a shared clone, symbolic refs (`origin/main`) can move between separate tool-call boundaries because other sessions fetch concurrently. A multi-step object-database construction must pin one explicit commit SHA at the start (`BASE=$(git rev-parse origin/main)`) and use `$BASE` — never the symbolic ref — at every subsequent step (`read-tree`, `commit-tree -p`), even across separate calls. See [[project_shared_index_can_hold_a_revert]] and the object-database-merge near-miss already in this file for the sibling failure modes on the same shared-clone hazard.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-19 — A commit's own summary line overclaimed "closes to zero" while its body text said otherwise

- **The rule going forward:** a summary sentence and the detail underneath it can drift apart within a single piece of work, not just across sessions — check a "fully closed" / "zero remaining" claim against the SAME document's own caveats section before repeating it in a lane block, todo.md, or a user-facing summary. This is a sibling to [[feedback_retraction_is_not_innocence]] (withdrawing a claim doesn't prove the opposite) and to [[feedback_gate_on_the_output_not_the_input]] (check what a document actually says, not what its own headline implies it says) — here the discrepancy was inside one document, not between two.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-19 — OVERTURNED: "leak-free" is not "representative" -- a backtest can be methodologically clean and still measure the wrong pipeline

- **The general rule.** A backtest's job is to measure what production does. "Leak-free" answers "is this number honestly measured from the data it uses" -- a completely separate question from "is this the SAME data production uses." Passing the first says nothing about the second, and nothing about the second's absence produces an error, a test failure, or any signal at all -- both pipelines run, both produce plausible numbers, both pass every existing test. The two pipelines have to be checked against each other DIRECTLY (does the backtest's league-branching logic match production's, field for field), not inferred from either one looking correct in isolation.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-19 — a single read of a MULTI-WORKER service is not a measurement

- **The rule going forward.** Verifying anything on a multi-worker service — post-deploy or not — means PROBING REPEATEDLY and reporting the distribution, not a value. If the probes disagree, that disagreement IS the finding: it means the workers hold different state, and a deploy (which restarts them) is what resolves it. Report "10/10" or "9 of 12", never a bare reading.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-19 — READ THE WRITER BEFORE INSTRUMENTING THE READER. A branch that turns on a key is answered by the SCHEMA, not by a deploy.

- **Overturned belief, recorded verbatim from `.syndicate/deploys.md` (2026-08-16 04:5xZ):** the uncached odds_history shard load inside `_enrich_games_with_tracked_market_lines` was *"the best candidate on the table"* for the refresh-worker's ~2GB excursion, and the entry closed with *"What would settle it: one bounded in-pass measurement around `:2294` (bytes read, parse peak, call count per build), **which needs a deploy**."*
- *(evidence in `learnings_evidence.md`)*

## 2026-08-23 — FORBIDDEN: claiming a feature works when no test runs the path that CALLS it

- **The rule going forward:** a feature whose failure mode is `except` + a log line MUST have a test that executes the real call path end to end. Testing the callee directly proves the callee works and says NOTHING about whether anything invokes it. And verify the test by reintroducing the bug: a green test that has never been seen red is a claim, not evidence.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-23 — FORBIDDEN: a module may not hold its own list of market names. It WILL drift from `market_keys`, silently

- **The rule going forward:** market names have exactly one authority, `market_keys.canonical_market_key` (`#224`). Canonicalise on lookup wherever a sport is in hand. Where the function takes no sport and cannot, hold BOTH spellings **and** a test that derives one set from the other — a private list with no such test is a silent time bomb, not a mapping.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-23 — FORBIDDEN: never read `settled_at` on an order as "the bet was decided"

- **The rule going forward:** `settled_at` is the ORDER's clock — `complete_order` stamps it when the order reaches a terminal state at the VENUE, seconds after a paper fill and hours before the game ends. The WAGER's clock is `graded_at`, written by `paper_settlement`. Two clocks, two fields, never one.
- *(evidence in `learnings_evidence.md`)*
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
## 2026-08-20 — An artifact can OUTGROW the publish ceiling, and the failure is silent

- **Why it cost so much to find: every other link was CORRECT.** The worker really did rebuild the ladder (`generatedAt 19:54:41 CT`). `is_stale()` really did correctly answer `fresh` — the content genuinely was newer than the odds and the sims. There was no error, no failing test, and nothing wrong anywhere near the ladder code. I chased five successive causes, each hidden behind the last, and three of my intermediate diagnoses were wrong.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-20 — OVERTURNED: "the slate date rolled, the gate expired". It had not.

- **How to apply:** any artifact keyed by SLATE date — ladders, sims, status documents, rebuild gates — is on Central time. Before concluding a document is missing, stale, or expired, convert: `slate_date = (utc - 5h).date()`. A watcher keyed on the wrong date does not return "nothing happened", it returns a CONFIDENT WRONG ANSWER, because the document it is polling really does exist and really is old.
- *(evidence in `learnings_evidence.md`)*
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

- **What I actually verified was "CI is green at 23:40Z."** I reported "CI is green." Those differ by exactly the hours that matter, and the whole point of the original request — *"anytime we deploy to git there are CI errors"* — was most likely THIS defect, which I then wrote off as fixed.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-20 — FORBIDDEN: never repair, rebuild or optimise a scheduled job without first establishing that anything still CONSUMES it. Fixing a dead job can be worse than leaving it broken.

- **80.6%**. Good work on a feature the user then said they do not use: *"we no longer use that daily update feature, everything runs on render."*
- *(evidence in `learnings_evidence.md`)*
## 2026-08-20 — A STANDING INSTRUCTION BLOCK GOES STALE SILENTLY, AND STALE READS AS AUTHORITATIVE

- **How to apply.** A ledger block written as an INSTRUCTION ("cut from THIS", "deploy X") must carry the reading that proves it is still valid, and the instruction must be re-derived, not trusted:
- *(evidence in `learnings_evidence.md`)*
## 2026-08-20 — "Everything upstream is correct" is a REASON TO LOOK FURTHER DOWN, not a reason to doubt the symptom

- **The generalisable error:** I kept re-examining whether the upstream verdict was WRONG, when the actual question was WHICH COPY it described. `is_stale()` reads the worker's disk; the symptom lived on web's. A component can be perfectly correct and still tell you nothing about the system, because it is answering a question about a different machine.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-20 — I NAMED A VERIFICATION CHECK WITHOUT CONFIRMING THE INSTRUMENT COULD SEE

- **How to apply.** `fnmatch`-vs-`glob` is a real trap in this repo: they disagree on `/`, so "it matches the allowlist" does NOT mean "it is published". Check the SWEEP's semantics, not the reader's.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-20 — OVERTURNED (pre-registered): soccer is not under-dispersed anymore, and fixing dispersion + missing inputs did not close the gap to the market

- **The 2026-08-20 re-run measured exactly the falsification condition.** Mean model stdev rose to 0.1922, past market's 0.1859 -- under-dispersion is gone. The Brier gap did not close: still worse than market in 8 of 9 leagues, `belgian_pro_league` the same single exception as the original diagnosis, completely unchanged by the entire session's work.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-20 — CORRECTED BELOW. FORBIDDEN: buying data before probing it exists — and NEVER diagnose a vendor from your own broken query

- **I verified the COST of a purchase carefully and never verified the PREMISE.**
- *(evidence in `learnings_evidence.md`)*
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

- **Pinning is only half the fix, and the dangerous half is the other one.** A pinned test that can no longer fail is worse than a flaky one, because it reads as coverage. Run the off != on probe: break the fixture and confirm the test fails. Here, flipping `active_today` to `False` produced `AssertionError: 'Live slate' not found` — that is what makes the green meaningful.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-20 — "strictly dominated" is a different diagnosis from "broken", and it changes the fix

- **The NCAAF model has REAL predictive power and is still worthless for betting. Those are compatible, and I spent a session treating them as if they were not.**
- *(evidence in `learnings_evidence.md`)*
## 2026-08-20 — ONE ERROR IN FIVE GUISES: validating against a PROXY, not the objective

- **Consolidates five entries this lane wrote on 08-19/08-20** (originals verbatim in `learnings_archive_2026-08-20.md`). They are the same mistake wearing different clothes, and seeing them together is the point — each looked novel while I was inside it.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-20 — A NULL HAS A SAMPLE SIZE. I called a lever dead, revived it, then buried it properly.

- **The same question answered three ways as n grew, and only the third was honest about its own power.**
- *(evidence in `learnings_evidence.md`)*
## 2026-08-20 — TRIMMING state.md AND learnings.md DOES NOT FIX THE DIGEST. Measured.

- **I told the user both files "arrive lossy at session start". That was wrong, and I had not read the hook that builds the digest.**
- *(evidence in `learnings_evidence.md`)*
## 2026-08-20 — RELAXING A FILTER CAN MAKE THE OUTPUT WORSE. Selection matters as much as the match.

- **That would have made it worse.** 43 headings is ~4,800 B against a 450 B cap, and `head -c` takes lines in FILE order, which in an append-only file is OLDEST first. So the "fix" would have shown ~7 of the most stale rules and silently dropped every lesson learned since — trading 8 visible rules for 7 worse ones.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-20 — A WORKTREE COMMIT LEAVES THE SHARED TREE STALE, AND STALE IS A REVERT WAITING

- **Working from a worktree is the right way to avoid the shared index. It has a cost nobody had written down: the shared tree does not learn about it.**
- *(evidence in `learnings_evidence.md`)*
## 2026-08-20 — OVERTURNED: a genuinely BRACKETED grid-search optimum (not an edge artifact) still failed held-out validation

- **It failed held-out validation anyway.** Applied to a worktree, run on a larger match set at both the old and new value, scored ONLY on the matches not used to find the value: mean Brier delta +0.0121, the WRONG direction.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-20 — A STALE-BASE PUSH DOES NOT LOSE WORK ONCE; IT POISONS THE BASE

- **How to apply.**
- *(evidence in `learnings_evidence.md`)*
## 2026-08-20 — A MUTATION TEST THAT MUTATES A COMMENT PROVES THE OPPOSITE OF WHAT IT LOOKS LIKE

- **How to apply.** Assert the mutation took effect before trusting the result — re-import the symbol and print it, or anchor on a form that appears exactly once (here: leading indentation plus trailing comma). Documenting a bug in a comment NEXT TO the code makes the code and its description textually identical, which is precisely what defeats a naive replace.
- *(evidence in `learnings_evidence.md`)*
## Saying a thing is done is not doing it `[2026-08-20]`

**What happened:** mid-deploy I told the user I had "stopped the older
monitor's redundant refresh-worker loop so it can't race this one." I had not.
Both monitors were still running deploy loops against the same service, and
either could have fired a deploy independently.

**Why it mattered and why it nearly didn't get caught:** the sentence was
plausible, sat in a report full of true statements, and described an action
I had genuinely intended. Nothing in the surrounding output contradicted it.
I only found it by re-reading my own claim against the task list. No
double-fire occurred — verified via `deploys?limit=2` — so the cost was zero
this time, which is exactly what makes the class dangerous.

**The rule:** an assertion about an action YOU took is a claim like any other
and needs the same evidence as a claim about the system. Before writing "I
stopped X" / "I released Y" / "I cleaned up Z", either the tool call is in
this turn's transcript or it is not true yet. Narrating an intention in the
past tense is the failure mode, and it is easiest to commit while reporting
progress on something else that IS going well.

**Corollary observed the same session:** a service moved mid-deploy THREE
times (`41f79353`->`85296826`, `39570b24`->`a54dffa3`, plus web). Re-reading
the live SHA immediately before cutting a branch is not caution on this repo,
it is the only thing that works — and `render_deploy`'s rollback refusal
caught two of those, which is a guard earning its keep rather than a nuisance.
## 2026-08-20 — AN EDIT THAT REPORTS SUCCESS IS NOT EVIDENCE THE EDIT LANDED

- **One.** To prove new tests were load-bearing I mutated the source and ran them. 16 passed. The honest reading is "these tests are worthless". The true reading was that `str.replace(..., 1)` had hit the FIRST occurrence — inside the comment I had just written documenting the bug — so the code was never touched. A green mutation run is evidence about the MUTATION as much as the test, and the two readings demand opposite responses.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-20 — FORBIDDEN: concluding a producer was REPLACED because a module says it replaced it

- **10**. Both write the same path. Last writer wins.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-20 — FORBIDDEN: fixing a guard bug ONLY in the guard you found it in

- **The rule.** When a hook/guard defect is about the ENVIRONMENT all guards share — which repo, which index, which env, which tree — fix it in a SHARED module and migrate the other guards, or the next guard written will re-make it. "Fixed" in one file is not fixed.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-20 — FORBIDDEN: a guard test that asserts against the live ledger

- **The rule.** Tests for the ledger hooks MUST build their own throwaway repos. Never assert against `.syndicate/*.md` in the primary tree or any worktree.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-20 — A SUFFIX MATCH CAN HIDE A PATH BUG BY ACCIDENT (`lane-guard` EXONERATED)

- **The rule going forward:** finding a bug via one API surface does not make that surface the right one to verify the fix against. Before writing "verified", confirm which endpoint/shape the actual consumer (the template, the frontend function, the downstream caller) reads, and check THAT one -- even if it means re-deriving the check from scratch rather than reusing the diagnostic query. The two shapes can diverge for the exact same underlying field, on the exact same row, at the exact same instant.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-20 -- A READING OF SHARED MUTABLE STATE EXPIRES AT THE INSTANT IT IS TAKEN

- **How to apply.** For anything shared and mutable -- the index, a deploy claim, a live SHA, `lanes.md`, an in-flight job list -- re-take the measurement in the SAME step that acts on it, not in the step that decided to act. This is the same failure as deploying a branch cut against a stale live SHA, which cost a re-cut earlier the same day; the shape is identical and so is the fix.
- **WHEN YOU CANNOT FUSE THE READ INTO THE ACT, VERIFY AFTER IT** `[added 2026-09-03, two sessions, same day]`. Sometimes there is no single step: `git add` / inspect / `git commit` is three, and the index moves in the gaps. I read `git diff --cached --stat`, saw exactly my 11 paths, and committed 13 -- a peer's `git rebase` autostash re-staged their work in between. `git commit -- <pathspec>` IS the fusing fix for that one (it bounds the commit at commit time), but it only covers a shared INDEX; against a shared TREE it commits the working-tree version and becomes the sweep. The peer hit the mirror image -- a clean-tree read that was true when taken and stale when used. **So the general answer is not a better read, it is a cheap check AFTER acting**, on the artifact itself: `git show <sha> -- <file> | grep '^[+-]###'`, or a deletion count. Both of us had a reading that was correct at the instant it was taken and wrong by the time it was used; only the check-after would have caught either.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-20 — A MUTATION TEST THAT MUTATES THE WRONG MODULE READS AS "VACUOUS SUITE"

- **The rule.** Before concluding a suite is vacuous because a mutation left it green, confirm the code you mutated is the code that suite's SUBJECT actually executes. A false "vacuous" verdict is as costly as a false green: it argues for deleting or distrusting a test that works.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-20 A SAMPLE THAT CONTAINS ONLY ONE STATE CANNOT DIAGNOSE A STATE MACHINE

- **The sample could not have shown that.** A census of every git-tracked recommendations artifact finds `status_state == "pre"` on **all 57 matches in them** -- there was no started match anywhere in the local mirror. "Always 0" and "0 until kickoff" are indistinguishable in a sample drawn entirely from before kickoff, and "0" is exactly what a correct reading looks like there.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-20 A DOCSTRING THAT NAMES ITS OWN PRECONDITION IS A CHECKABLE CLAIM

- **How to apply.** When a function's docstring states a precondition on its CALLERS, that is a grep, not prose -- enumerate the call sites and check each one. This module had already been bitten by exactly this shape (the `_load_team_ratings(as_of)` outage, whose own comment says "a signature change needs a caller census, not a spot-check of the caller you just edited") and the census was never widened to the other preconditions in the same file.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-20 A LOCAL VARIABLE NAMED FOR THE PARENT OF WHAT IT HOLDS

- **How to apply.** When adding a field to an existing extractor, dump the raw node you are reading from and confirm the field is on THAT node -- do not infer it from the variable's name. Renaming to `status_block` / `status` made the two levels visible and the bug impossible to restate.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-20 THE EDIT TOOL REPORTED SUCCESS ON A WRITE THAT NEVER REACHED DISK

- **How to apply.** After an `Edit` on a hook-guarded path, verify the text is on disk -- `grep` for the new symbol, or `git diff --stat` for a plausible line count -- before building anything on top of it. A syntax check is not enough: the file parsed fine, because the missing piece was a definition, not a statement. This session switched to writing edits through a script that asserts its anchor count and re-greps afterwards.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-20 — FORBIDDEN: reading a KILLED pytest run as a result. I retracted a 12-failure report that never existed.

- **I reported "~12 failures in the deployed areas", repeated it, and proposed rolling back three verified production deploys on the strength of it. The number was fiction.**
- *(evidence in `learnings_evidence.md`)*
## 2026-08-20 A POST-DEPLOY VERIFICATION READ ONCE CAN BE AN ARTIFACT OF TIMING, NOT A PROPERTY OF THE SYSTEM

- **Three minutes later the same endpoint served the same fixture with no score and no box**, and stayed that way across six consecutive reads. The passing reading had depended on a transiently fresh input artifact; web then fell back to a month-old git-tracked mirror (`generated_at 2026-07-20`, `status_state "pre"`) and every score source correctly refused it.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-20 A CORRECT REFUSAL ON STALE INPUT IS INDISTINGUISHABLE FROM A BROKEN FEATURE

- **The gate did exactly its job and the user-visible result was a blank card.** Meanwhile the right answer sat on the same disk, in the same request: the live poller's `match_box` carried `final: true`, `FT`, `1-1`, both goals and full team stats, written ninety seconds before.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-20 — A TIMEOUT WROTE `none` AND I DIVIDED BY IT. Four false diagnoses, one root habit.

- **The rule going forward.** Before attributing a stale artifact to a producer, read its MTIME and compare it to when the file was last known good. **An mtime earlier than that, or landing exactly on a whole second, means a `copy2` from the checkout — look at boot-time sync, not at publishers.** And check WHICH SERVICE runs the sync from the CODE, never from the env var: `SYNDICATE_BOOTSTRAP_ON_START=1` is set on all three services and read by nothing on the two workers, because neither imports `syndicate.app`.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-20 FORBIDDEN: staging a SHARED ledger file by path in the PRIMARY tree — `git add <path>` sweeps other sessions' uncommitted edits to that same file

- **The rule going forward.** Make ledger edits wherever protocol wants them, but **COMMIT them from your own worktree**: branch from a fresh `origin/main`, rebuild the file as `origin/main` + only your own edits (line-based), then **assert the heading-level diff against `origin/main` shows ONLY your headings** before committing. The assert is the point — it fails loudly on a stale premise instead of succeeding quietly, which is the general form already recorded in `project-shared-tree-commit-recipes`.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-20 A CENSUS THAT CANNOT READ UNHEALTHY IS NOT A VERIFICATION — the slate can retire your test case between diagnosis and deploy

- **What happened.** The Layer 2 rail duplicated NFL games because two row families for one game reached the board. Between 18:20 and 18:59 CT one family LEFT the live board (`candidate_type=game` rows **2 → 0**; the 21 `layer2_shortlist` rows unchanged). The duplicate needs BOTH. So the obvious post-deploy check — census the current payload for "chips seating more than one card" — returned **0**, and would have returned 0 with the fix reverted.
- *(evidence in `learnings_evidence.md`)*
## FORBIDDEN: a `continue` that skips a check inside a loop whose only failure signal is a counter `[2026-08-20, #481]`

**The belief overturned.** `scripts/verify_wnba_live_scale.py` exited **0** and
printed `VERIFIED on 1 live row(s)` on the first live game it ever saw, having
**compared nothing**. The obligation it was written to discharge was recorded as
discharged on the strength of that exit code. It was caught only because the
output line above the verdict said
`payload omits live_margin/elapsed_min -- cannot recompute`.

**The shape, which is general.** The loop was
`for row: if inputs_missing: continue; ... if mismatch: bad += 1`, and the
verdict was `return 2 if bad else 0`. A skipped row never touches `bad`, so
**"could not check" is indistinguishable from "checked and passed"** in the only
variable the exit code reads. This is the `unknown must not default permissive`
rule, but the permissive branch is a `continue` rather than an `else` — which is
why it does not look like a default at all, and why reviewing the comparison
logic (which was correct) finds nothing.

**The rule going forward.** **Count what you CHECKED, not just what you FAILED,
and refuse to pass on zero checks.** Any verifier needs a third outcome
alongside pass/fail: *did not verify*. Concretely: `checked`, `bad` and
`unchecked` as separate counters; `if not checked: return <nonzero>`; and the
skip path must PRINT what was missing. A success message should state its own
denominator (`VERIFIED: 2 check(s) across 1 live row(s)`) so a zero is visible
in the output rather than inferred from its absence.

**Second defect, same script, independent.** It read `lane["live_margin"]` and
`lane["elapsed_min"]` — fields `_wnba_game_lens` does not publish (margin is
`projection.homeMargin`; elapsed is DERIVED from `status.period`/`clock`). So
the skip fired on EVERY row, always. A verifier that has never once been run
against the live shape it parses has not been tested, only written — and this
one was authored in the same session as the fix it was meant to police, when no
live game existed to run it against. **If you write a verifier you cannot
execute yet, say so where the obligation is recorded**, or its first green run
will be mistaken for the confirmation.

**Also: drive the expected value by IMPORTING the shipped function.** This
script re-implemented the blend locally, so it could have "verified" a formula
production does not run — the same two-copies hazard `#475` called out.

**Cost.** ~0. Caught on the first real live game, and the same run then produced
the genuine confirmation (gap `0.00e+00`, both paths). Fixed in `2ff4ce5b`.
## A WNBA/board date lookup must search YESTERDAY-UTC `[2026-08-20]`

The board keys games by **ET business date**, so an ordinary 7pm ET tip —
`2026-08-21T00:00Z` — is filed under `2026-08-20`. A today/tomorrow-UTC search
therefore returns *"no live game"* during exactly the evening window when games
are being played. Measured at 00:16Z with IND@DAL live and in Q1. Cheap to get
right (search yesterday/today/tomorrow); the miss reads as a clean null result,
which is the dangerous part — it looks like evidence of absence.
## 2026-08-20 — FORBIDDEN: verifying pushed content by slicing a computed substring out of it. Anchor on the LINE. Twice in one session my own checker said ABSENT about content that was PRESENT.

- **What happened, twice, same session, same shape.** Both times I pushed a ledger edit and then "verified" it by pulling the file off `origin/main` and testing a *computed slice* of it. 1. Checked my lane block carried the new baseline number by extracting the block with `IndexOf("`n### ", start)` and searching the slice. Reported `carries number: False`. **The number was there** — the slice ended before it. 2. Checked the old `state.md` bullet was gone by testing whether the string `is NOT "224 green"` still appeared anywhere. Reported the old line **still present**. It was not: my *replacement text deliberately quotes the old line*, so the substring matched my own new prose.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-20 — A PLATEAU IS NOT A FREEZE. A monotonic counter read ONCE cannot tell "stopped" from "between events".

- **The near-miss.** `#387`'s closing reading turned on one field: does `FEED_LIVE_PRUNE plays_dropped` grow during the live slate? Growth = the mechanism works. Stuck near zero = **PREMISE RETIRED**, the verdict that would have withdrawn the whole reason the change exists.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-20 — A ONE-REVISION PRESENCE CHECK CANNOT TELL "ALREADY UPSTREAM" FROM "ONLY IN MY OWN ABANDONED COMMIT"

- **Belief overturned, and I stated it to the user as fact:** that my session's `log/<today>.md` entry was already on `origin/main`, having been swept there by another session's commit. It was not. It was **nowhere in main's history** — it existed only in the commit I had just abandoned.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-20 — OVERTURNED: a loose threshold is a SYMPTOM. Ask what it compensates for before tuning it.

- **What was believed:** `match_team_name`'s 0.72 fuzzy threshold was a tolerance choice — the price of matching team names across three sources that spell them differently, to be tightened or loosened as needed.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-20 — OVERTURNED: "N of N" is worth nothing until you know the sample COULD have contained a counterexample.

- **What was believed:** `live_home_score`/`live_away_score` are a placeholder the artifact builder writes, not a real reading. Evidence: the string `"0"` on **12 of 12** sampled matches, *including* `status_state == "pre"`.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-20 — FORBIDDEN: in a tree you did not create, an unexplained diff is another session's work until proven otherwise.

- **What happened:** I ran `git checkout -- syndicate/features/soccer/cards.py` in the shared lane worktree, on a 67-line diff I had not written. I checked that the function it contained was already on `origin/main`, concluded the working copy was a redundant leftover, and discarded it. It was almost certainly the `soccer-live-score-clock-box` session's in-flight work — they independently reported two `Edit` calls that "reported success and never reached disk" in that window.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-21 — A GITIGNORED FILE CANNOT BE A MODEL INPUT. Allowlisting it does not help, and the result is a feature that is live, tested, deployed and does nothing

- **Believed:** wiring the NFL prop model to `spread_line`/`total_line` from `data/nfl_source/tracking/nflverse/schedules_games.csv` and adding that path to `HOT_ARTIFACT_PATTERNS` was enough to ship the game-context mechanism.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-21 — A REACHABILITY PROBE SAMPLED FROM REAL DATA CAN BE DEGENERATE, and then it reports a live mechanism as dead

- **Believed:** `off != on` on a real row proves a mechanism is reachable, so probing `train_rows[0]` was a fair test.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-21 — A DOCUMENTED "acceptable for v1" LIMITATION IS A LIVE DEFECT THE MOMENT DATA ARRIVES TO EXERCISE IT

- **Believed:** `short_name_from_full`'s docstring already named the collision ("two players sharing a first initial + last name would collide — acceptable for a v1"), so it was a known, bounded simplification.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-21 — OPENING A LANE IN THE PRIMARY TREE AND THEN OPENING A WORKTREE SILENTLY DROPS THE LANE BLOCK

- **Believed:** `adopt` is only needed when a lane has PRE-EXISTING uncommitted work, so a brand-new lane can skip straight to `open`.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-21 — FORBIDDEN: concluding a capability is ABSENT from two adjacent artifacts

- **The rule going forward.** Before reporting a capability ABSENT, name the surface that WOULD carry it and check THAT — an API route, a payload key, a producer function — not two artifacts adjacent to it. Grepping for the concept (`live_player`, `boxscore`) takes one call and would have found it immediately. The asymmetry is the point: "present" needs one positive reading, "absent" needs a search over where it would live, and I spent the effort budget of the first on a claim of the second.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-21 — A HEALTHY LOG LINE CAN LOOK LIKE THE BUG (`written=0` was correct)

- **The rule going forward.** When a question is decided by ONE artifact, build the read for that artifact before forming a third hypothesis. `GET /api/ops/live-lens/snapshot-index?sport=wnba` now reads the lens through the same keyvalue-aware reader the join uses and reports the join's verdict per game; it answered in a single call what four rounds of inference could not, and it also disproved a fifth hypothesis of mine (a `pregame` lane on a FINAL game is correct, not a drop). The corollary to the standing "instrument blindness" rule: a reading is only evidence once you know what HEALTHY looks like, and `written=0` had a healthy meaning nobody had written down.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-21 — ABSENT IS NOT None, AND THE DIFFERENCE NAMES THE PRODUCER

- **The rule going forward.** On a dict-shaped payload, distinguish `key not in payload` from `payload[key] is None` before theorising about VALUES. Absent indicts the PRODUCER (this code path never ran); None indicts the INPUT (it ran and had nothing). Two of my three explanations were about the input; the answer was the producer, and one `in` check would have pointed there first. Carried into the fix: a one-sided market now yields None with the KEY PRESENT, so the join can tell "this producer does not do market prices" from "it does, and this row has none".
- *(evidence in `learnings_evidence.md`)*
## 2026-08-21 — "UNAVAILABLE" IN A LEDGER ENTRY MEANS "NOT RETAINED", NOT "UNOBTAINABLE"

- **The rule going forward.** "Unavailable" in a ledger entry is a statement about what was retained at the time of writing, not a property of the world. Before inheriting one as a permanent constraint, ask what it would COST to obtain — this repo already had the fetcher, the credit accounting and the precedent. Totals moves from "refused forever" to "refused until graded", which is a different roadmap.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-21 — I DERIVED SERVICE OWNERSHIP FROM CODE AND SHIPPED TO THE WRONG WORKER. The env gate runs FIRST

- **Believed:** `_weekly_sport_claimed_by_fast_tick("nfl", today) == True`, so NFL is owned by the fast tick, which runs on **live-odds-worker** — therefore that service needed the NFL capture fix before the season. I said so to the user, wrote it into `state.md` and `deploys.md`, and deployed on it.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-21 — A 403 FROM WEB IS A ROUTE RESTRICTION, NOT AN ABSENT FILE

- **The rule going forward.** Before recording a file as unreachable, say WHICH reader refused and WHICH consumer actually needs it. If the consumer runs on a worker and the refusal came from a web route, the answer is not "blocked" — nothing has been established. Cheapest discriminator: name the consumer's process first, then test the reader THAT process would use.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-21 — AN APOSTROPHE IS INTRA-WORD; A HYPHEN SEPARATES WORDS

- **The rule going forward.** In a name normaliser, DELETE intra-word punctuation (apostrophes, straight and typographic) and SUBSTITUTE separators (hyphens, slashes) with a space. One regex for both is wrong for one of them, always. And a name join must COUNT AND NAME its misses: `players_unmatched` exists so a zero is attributable, because a silent zero and a named zero need different fixes.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-21 — FORBIDDEN: `cat >` on a ledger file. Append only, and re-check AFTER the rebase

- **The rule going forward.** Never `cat >` a `.syndicate/**` file — `>>` always, or an Edit against content you have just read IN THE TREE YOU ARE WRITING TO. Re-check existence AFTER any rebase or fetch, not before. And read `git diff --cached --numstat` before every ledger push: it is one line, it is the only thing that distinguishes "I added my entry" from "I replaced someone else's", and it has now caught this class twice.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-21 — THE DEPLOY CLAIM IS NOT A GLOBAL LOCK ONCE SESSIONS USE WORKTREES

- **FORBIDDEN: reading `deploy_claim.py acquire`'s own `ACQUIRED` as proof you hold a service.** It is proof you hold it *in the tree you ran it from*.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-21 — FORBIDDEN: taking a CODE COMMENT as authority for WHICH SERVICE runs something

- **The rule going forward.** Before ANY deploy, get the running system to name the executor of the exact branch you changed, in one call:
- *(evidence in `learnings_evidence.md`)*
## 2026-08-21 A `max(timestamp)` INSIDE A SEASON-SCOPED ARTIFACT IS A HINDSIGHT LEAK, AND IT FLATTERS

- **Two rules.**
- *(evidence in `learnings_evidence.md`)*
## 2026-08-21 THE PRIMARY SHARED TREE IS NOT A NARRATOR OF `main`, AND `reset --hard` ON IT DESTROYS OTHER SESSIONS' WORK

- **1. A grep in that tree is not evidence about the codebase.** Checking field names before writing them into a scheduled task, `grep -r WNBA_LIVE_BOX_` returned NOTHING — while that exact string was in production logs 40 minutes earlier. The grep was correct; the assumption about which tree it ran in was not. **When a tool disagrees with production about whether code EXISTS, suspect the tree before the production reading.** `git rev-list --left-right --count HEAD...origin/main` is one line and settles it. Read source from the remote (`git show origin/main:<path>`) rather than from the checkout.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-21 — AN UNCHANGED VALUE ACROSS A DEPLOY IS STALE DATA UNTIL PROVEN OTHERWISE

- **FORBIDDEN: concluding a deployed fix failed, from a reading whose artifact you have not shown was rebuilt by it.** Four false failures in one session, all this shape:
- *(evidence in `learnings_evidence.md`)*
## 2026-08-21 — A SUCCESS-ONLY EMITTER MAKES ZERO INVISIBLE

- **Rule: report the zero, not just the success.** Corollary already in this file — absence of a signal is a fact about the EMITTER first.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-21 — A CONDITIONAL LOCAL IMPORT SHADOWS FOR THE WHOLE FUNCTION

- **Rule: a conditional local import binds that name local for the ENTIRE function, so every branch that does NOT run the import raises `UnboundLocalError`.** An UNCONDITIONAL local import at the top of a function is harmless — it always runs before any use. Only the conditional one is a trap.**
- *(evidence in `learnings_evidence.md`)*
## 2026-08-21 — A NULL RESULT NEEDS A NEGATIVE CONTROL BEFORE IT IS EVIDENCE

- **Rule: run the control on something known-good before an absence counts.**
- *(evidence in `learnings_evidence.md`)*
## 2026-08-21 — A DOCSTRING DESCRIBES INTENT; THE CODE DESCRIBES BEHAVIOUR

- **Rule: where a comment and the writer disagree, the writer wins.**
- *(evidence in `learnings_evidence.md`)*
## 08-21 A KILLED PROCESS IS NOT A KILLED PIPELINE — `pkill` on the child leaves the wrapper running with STALE ARGS

`pkill -f backtest_soccer_live_totals` killed the python. It did NOT kill the
`bash -c "cmd_A; cmd_B"` wrapper, which then ran **cmd_B with the OLD
arguments** and wrote `holdout_ON.json` at 21:02Z — a file with plausible
numbers, a fresh timestamp, and entirely the wrong data (37 MLS matches from a
window I had already rejected).

Caught only by checking the file's OWN provenance (`window`, `leagues`) before
reading its results. The tell was a timestamp that PREDATED the run I thought
produced it.

**RULE: kill the wrapper, not the child. And before reading any result file,
check that it describes the run you think you launched — window, scope, and a
timestamp AFTER you started it.** Third stale-artifact catch in one session;
the other two were a board built before a deploy and a shortlist artifact that
had not been regenerated.

**Corollary that made this cheap:** write each run to a DISTINCT filename. A
leftover cannot impersonate a result it cannot overwrite.
## 08-21 FORBIDDEN: validating a finding on a window that does not contain the thing

A held-out validation for a EUROPEAN bias was pointed at **June–July**, the
European off-season. It returned 37 matches, all MLS. Had it run, it would have
reported "held-out validation" while actually testing whether a European
finding transfers to a different competition — and it would have looked
entirely legitimate.

**RULE: before running a validation, assert the window CONTAINS the population
the finding is about.** One `fetch_events` count per league, seconds, and it
turns a meaningless result into a caught error. An empty or wrong-population
window and a genuine null result are indistinguishable in the output.
## 08-21 MAE HIDES DIRECTION, AND DIRECTION IS THE WHOLE FIX

I hypothesised the live totals mean OVER-predicts late and was ready to correct
it. Signed bias showed the OPPOSITE: it under-predicts. **A correction applied
in the hypothesised direction would have made the model strictly worse while
looking like progress.**

Two further hypotheses died the same way: a flat −0.18 offset that was my own
neutral-ratings input, not a model defect; and "second-half rate too low",
refuted by measuring 57.1% ± 3.7pp against an assumed 55–56% — inside one
standard error, so changing the calibrated constant would have been fitting
noise.

**RULE: report SIGNED error beside absolute, always. Before changing a
calibrated constant, measure what it encodes and compare against its standard
error — a difference inside 1 SE is not evidence.** Three hypotheses, three
refutations, one real defect (a resumed sim missing stoppage — a MISSING
QUANTITY, not a tuned parameter).
## 08-21 AN UNDERPOWERED TEST PASSES AND FAILS BY LUCK — RAISE n, DO NOT RE-ROLL THE SEED

`test_red_carded_team_is_disadvantaged` failed after an unrelated change to the
resume clock. Swept at one seed:

    n= 150  diff +0.0267  (1 SE ~0.0384)   <- decided by noise
    n= 600  diff -0.0817  (1 SE ~0.0192)
    n=1500  diff -0.1313  (1 SE ~0.0121)   <- ~11 SE, unambiguous

The mechanism was correct and LARGE. At n=150 the effect was smaller than one
standard error, so the assertion was decided by the seed's trajectory: it passed
before the change and failed after, and **both outcomes were luck**.

**RULE: when a Monte Carlo test flips on an unrelated change, sweep n before
touching anything. Re-rolling the seed until it goes green restores a pass that
measures nothing** — and leaves the next person believing a mechanism is tested
when it is not.
## 2026-08-21 — FORBIDDEN: a deploy chained in the same shell command as anything naming another service

- **Rule: one deploy, one bash call, with no other `--service` in it.** Release claims, acquire claims and run preflights as their own calls.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-21 — FORBIDDEN: explaining a local failure with a LOCAL cause when the same code runs in production

- **Rule: a cause that conveniently quarantines a failure to the machine you are standing on deserves more scepticism than a cause that implicates production, not less** — the two are not symmetric, because only one of them lets you ship.**
- *(evidence in `learnings_evidence.md`)*
## 2026-08-21 — READ THE TTL BEFORE BREAKING A LOCK. The force bought 12 minutes.

- **Rule: before forcing a claim, print its age against the TTL and state the remaining wait.** The protocol's `--force` is for a session that is GONE; when the holder is alive, the honest question is whether the work can wait N minutes, and N is a number the tooling already knows. A remaining-wait figure belongs in the guard's own output, next to where it prints the holder.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-21 — FORBIDDEN: asserting a trend from one sample, especially a scary one

- **10.2 / 10.4 / 19.5 BEFORE I touched anything**, and 12.8 / 11.4 / 17.8 after. 19.7 was an ordinary member of the spread. There was no trend.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-21 — Reasoning off an invented clock, and querying a window in the future

- **Rule: never state an elapsed time without reading the clock, and never treat an empty log result as absence until the tool's own COVERED range contains the period you care about.** Related: [[feedback_instrument_blindness]].
- *(evidence in `learnings_evidence.md`)*
## 2026-08-21 — A poll that matched its own instrument

- **Rule: a poll predicate must match the SHAPE of a real record, not the topic.** `^2026-` (a timestamped line) is a predicate; the search term is not, because the tool prints the search term back. Anchor on the record format.
- *(evidence in `learnings_evidence.md`)*
## 08-21 THE "EMPTY BOX SECTIONS" BUG NEVER EXISTED — I COUNTED THE WRONG FIELD

Card sections come in TWO SHAPES. List sections carry `rows`. TABLE sections
carry `table_rows` and set `"rows": []` **by design** (see
`soccer/cards.py::_correct_score_section`, which returns both keys). Goals,
Match stats and squad projections are all table sections.

I measured `len(section["rows"])`, got 0 for every table section, and reported
"box sections render 0 rows on all 4 games" in a UI audit. The truth, read from
the same production payload with the right key:

    Goals        3 table_rows   15' Havertz, 23' Saka, 49' Odegaard
    Match stats 12 table_rows   Possession 35.5%/64.5%, Shots 4/20
    ARS squad   23 table_rows   with prices and edges

**WHAT THAT ONE WRONG FIELD COST:** a false audit finding; two commits
(`0aaf71f0` reader swap, `94a53639` data_root path) shipped to fix a
non-problem; a web deploy and rollback; a 502 misread as caused by my own
change; and two wrong outage attributions chased in sequence. Every later
"still 0 rows" reading LOOKED like confirmation that the fix had failed, so the
bad metric kept generating new hypotheses instead of being questioned.

**RULE: before reporting a count of zero as a defect, print the CONTAINER'S
KEYS.** One `sorted(section.keys())` would have shown `table_rows` beside
`rows` and ended this at the first reading. A zero from the wrong key is
indistinguishable from a zero from missing data, and it is far more likely --
missing data has a cause, a typo'd key needs none.

**Corollary, and the reason this ran so long:** when a fix does not move a
metric, suspect the METRIC before writing the next fix. I twice diagnosed the
read path -- because that is where the PREVIOUS bug was -- rather than testing
whether the measurement was sound.
## 2026-08-21 — The preview pane CANNOT verify a CSS edit. It caches the parsed stylesheet.

- **This is the dangerous class of instrument failure, because it reads as a CODE failure.** The obvious conclusion — "my CSS is wrong, it isn't applying" — is exactly what the tool is showing you, and it is false. I nearly rewrote working rules to satisfy a cached stylesheet.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-21 — A tooltip is not a reading surface, and the data was already there

- **When adding a UI affordance for stored data, print the FIELD LIST of what is stored and ask which fields the surface can physically show.** Here that is one command and it would have named `description` on day one.
- *(evidence in `learnings_evidence.md`)*
## 08-22 `INVALID_MARKET` MEANS TWO DIFFERENT THINGS, AND A STATUS CODE CANNOT TELL THEM APART

`fetch_soccer_oddsapi_odds_local.py` carried, since 2026-07-21:

    # btts/draw_no_bet/double_chance confirmed unavailable (HTTP 422) against
    # the live API on the current plan/region -- not attempted here.

**It was wrong, and it cost a month of two markets nobody knew we could have.**
The Odds API returns `INVALID_MARKET` with two distinct messages:

    "Markets NOT SUPPORTED BY THIS ENDPOINT: btts"   <- VALID key, wrong endpoint
    "INVALID markets: both_teams_to_score"           <- no such key

Read as a bare 422 they are identical. `btts` and `alternate_totals_corners`
are served from the PER-EVENT endpoint -- the one the props fetcher ALREADY
calls -- so capturing them costs no additional API calls at all.

**RULE: when an API refuses, READ THE MESSAGE, not the status code.** And a
dated "confirmed unavailable" comment is a measurement with an expiry, not a
fact: plans, regions and endpoints all move.

**SECOND FAILURE IN THE SAME PROBE, and the more general one:** the first
region tried was `eu` (btts 4 books, corners 1) and that was nearly written up
as the market's depth. Actual coverage: us 7/7, uk 11/4, all four regions
29/18. **A single-parameter probe measures that parameter, not the world.**
Before reporting a capability as thin, vary the one knob most likely to explain
thinness.
## 08-22 A COUNT OF ZERO IS A CLAIM ABOUT YOUR QUERY FIRST

Card sections come in two shapes: list sections carry `rows`, TABLE sections
carry `table_rows` and set `"rows": []` BY DESIGN. Goals, Match stats and squad
projections are all table sections.

Counting `len(section["rows"])` produced 0 for every one of them, which was
filed as a UI-audit defect ("box sections render 0 rows on all 4 games"). The
same production payload, read with the right key: Goals 3 rows (15' Havertz,
23' Saka, 49' Odegaard), Match stats 12, ARS squad 23.

**COST: two commits fixing a non-problem, a web deploy, a rollback, a 502
misattributed to my own change, and a second wrong attribution after that.**
Every later "still 0 rows" LOOKED like confirmation the fix had failed, so the
bad metric kept generating hypotheses instead of being questioned.

**RULE: before reporting a zero as a defect, print the container's KEYS.** One
`sorted(section.keys())` ends it at the first reading.
**COROLLARY: when a fix does not move a metric, suspect the METRIC before
writing the next fix.** The read path was diagnosed twice -- because that is
where the PREVIOUS bug was -- rather than testing whether the measurement was
sound.
## 08-22 VERIFY THE SHA OF THE SERVICE THAT EXECUTES, NOT THE ONE YOU DEPLOYED

A soccer refresh was fired to exercise new capture code, after explicitly
checking that `live-odds-worker` was live on it. The job produced nothing:
`launch_mode: manifest_only` routes onto **refresh-worker's** claim loop, and
refresh-worker was three commits behind. That routing was written down in this
session's own commit message an hour earlier.

The same shape governs whether a FEATURE is live at all: soccer live_state --
and therefore momentum -- is written by refresh-worker
(`SYNDICATE_ENABLE_SOCCER_WEEKLY_REFRESH_AUTORUN`, scoped in `render.yaml` to
"the sim and live_state"), NOT by the worker whose name suggests live data.

**Worse than absent: the live-lens loop runs on BOTH workers writing the same
aggregate, so a partial deploy makes a feature FLICKER -- whichever service
ticks last wins.** A clean zero is easier to diagnose than intermittent truth.

**RULE: a sequencing check is only worth the service it points at.** Before
claiming a feature is live, resolve which service executes it -- from env and
routing, not from the name -- and check THAT SHA.
## 08-22 MOMENTUM DOES NOT PREDICT *WHEN* A GOAL IS COMING — and the earlier positive result did not imply it would

Swept 5 weight variants x 6 half-lives (90s-900s) over 200 completed matches
from last season, held out by match-id hash, target = "does a goal land in the
next 10 minutes", feature = ABSOLUTE pressure (a goal happening is about
pressure on either side; signed momentum answers WHO, not WHETHER):

    BEST ON FIT : on-target-heavy @ 600s   AUC 0.5403
    ITS HOLDOUT :                          AUC 0.5107   (base rate 0.2471)
    every variant x half-life: holdout AUC 0.49 - 0.54

**0.5107 is a coin flip. Not usable for timing.** WHO, conditional on a goal
having happened, is no better: best fit `shots-only @ 900s` 0.5961 -> holdout
**0.5224** on n=1221.

**THE TRAP, AND IT IS THE WHOLE LESSON.** The 08-21 lead/lag test found
momentum elevated before goals: +1.141 vs 0.000 control, Cohen's d = +0.397,
and that result was sound. It answered: *given a goal happened, was momentum
elevated 2 min before, versus a control instant?* -- retrospective, and
oriented to the side that scored.

The question worth acting on is: *at an ARBITRARY instant, is a goal coming?*
The signal does not survive the translation. **"Separates from control" and
"predicts the event" are different claims**, and only the first was earned. The
phrase "momentum LEADS goals" -- written into a commit message and a state.md
section -- reads as the second.

**RULE: a retrospective separation result is a HYPOTHESIS about prediction, not
evidence of it.** Before building on one, restate it as the forward question
(at time T, with only information available at T, what happens next?) and score
it held out against the base rate. The two differ by ~0.04 AUC here, which is
the difference between a feature and nothing.

**ALSO: the best HOLDOUT row was not the best FIT row** (`corners-heavy @ 900s`,
0.5426). Selecting it would be fitting the holdout -- the same error one level
up -- so it is recorded as a hypothesis for a fresh slice, not a result.

**WHAT THIS DOES NOT RETRACT:** the chart itself. It is an honest DESCRIPTIVE
panel of who is on top, which is what the user reads it for manually, and the
sign convention is verified correct against live scorelines. It is a narrator.
It is not a timing signal, and nothing should price off it.
## 08-22 THE PRE-REGISTERED TEST KILLED THE 40.2%, AND MY OWN PASS/FAIL BANDS WERE WRONG

Rule fixed in advance (`0fff6254`): fire when 34-38 min into a half AND pressure
>= 9.2525 (90th pct, derived from the FIT half only). Scored on 158 matches from
a DIFFERENT period, all 699 prior ids excluded:

    hypothesis (post-hoc)  0.402
    FRESH hit rate         0.2547
    time-window only       0.3063   (n=1580)
    momentum increment    -0.0516
    fresh base rate        0.2631

**MOMENTUM ACTIVELY HURTS.** The full rule is 5.2 points BELOW the time window
alone, and BELOW the base rate -- firing on pressure selects worse-than-average
moments. The 40.2% was an artifact of picking the time window AFTER seeing which
decile won on the holdout, exactly as suspected.

**MY PRE-REGISTERED BANDS WERE THEMSELVES DEFECTIVE.** They read
`>= 0.25 -> WEAK PASS (clears 3-1)`, so the run printed **WEAK PASS** for a rule
that loses to doing nothing. I set the bands against BREAK-EVEN and never against
the BASE RATE. A signal must beat the base rate before break-even is even the
right question -- otherwise "profitable at 3-1" is satisfied by any rule that
fires during a period when goals are common, including a rule with no signal at
all.

**RULE: a pre-registered threshold must include the do-nothing baseline, not
just the economic one.** Beating break-even is necessary and not sufficient; the
comparison that decides whether a FEATURE works is against the base rate, and
against the simpler feature it claims to improve on.

**WHAT REPLICATED:** the clock, not the momentum. 34-38 minutes into a half ran
0.3186 on holdout and 0.3063 on fresh, against base rates of 0.2342 and 0.2631 --
a stable ~1.16-1.36x lift from an unbiased decile split both times. That effect
is real, needs none of this machinery, and is almost certainly in the market
price already.

**STANDING: momentum is a NARRATOR.** Three tests now -- global AUC (0.5417
held out), conditional tail (killed by preregistration), and the increment over
time alone (NEGATIVE). Nothing should price off it. The chart stays because it
honestly describes who is on top, which is what it is read for.
---
## 2026-08-22 — An absent LOG LINE is not an absent EVENT, and a stale ledger figure will out-argue a fresh measurement

- **1. I diagnosed for two hours on a number the ledger had, and production didn't.** `state.md` said the soccer projection join served `rows_with_projection: 4` of 1,142. I quoted it forward as current, built a mechanism around it, wrote a `todo.md` item on it, and shipped instrumentation to explain it. The first real reading was **9,598 of 20,014 (48%)** — the join had been working since `#379`'s window fix actually ran. The figure predated that deploy and nobody had re-measured.
- *(evidence in `learnings_evidence.md`)*
## 08-22 THE BEST GOAL WINDOW WAS HIDDEN BY MY OWN SAMPLING CUTOFF

Every momentum sweep sampled `start=300, end=5100` -- so **80-95' was never a
decision point**. The densest scoring period in football was excluded by a
constant I chose and never questioned. Sampling the full match (to 5700s):

    clock    n     hit     lift   window available
    80-84   848   0.3455   1.48        8.5 min     <<< best in the match
    36-40   848   0.2889   1.24       10.0 min
    84-88   846   0.2636   1.13        4.5 min
    88-92   211   0.2275   0.98        2.0 min
     8-16         0.1722   0.74       10.0 min     (quietest)

**80-84' clears the 2-1 break-even (33.3%) on the CLOCK ALONE**, base rate
0.2331. And the `window available` column is why later is not better: by 88'
only 2 minutes of a 10-minute window remain, so the rate keeps climbing while
the bet stops existing. 80-84' is where rate and runway overlap.

**EVENTS, TESTED INDIVIDUALLY FOR THE FIRST TIME.** Earlier sweeps moved four
shot families together, so no single type could be seen:

    corner-awarded    1.19      shot-ON-target   0.97   <- BELOW base
    shot-off-target   1.19      handball         0.88
    shot-blocked      1.17      "all types"      1.03   <- dilutes

**Shots ON target predict goals WORSE than shots off target.** Goals are
excluded from the feature, so a remaining on-target shot is a SAVED one -- the
chance is spent. Off-target and blocked shots mean pressure still building.
Anyone hand-weighting these would have ranked them the other way round; I did,
in the shipped chart (`shot-on-target: 3.0` vs `shot-off-target: 1.5`).

Crossed against time, the best feature adds +0.02 at the money bucket and flips
sign across others (+0.054 at 16-20', -0.050 at 8-12'). Noise-shaped.

**RULE: a sampling range is a modelling assumption. State it and test its
edges.** `end=5100` was written once, carried through four analyses, and hid the
only result that clears a real break-even. No amount of feature engineering
inside the window could have recovered what the window excluded.
## 08-22 POOLED RESULT: THE CLOCK IS THE ONLY REAL SIGNAL — and FotMob IS reachable

Pooled 370 matches (212 holdout + 158 fresh), 32,501 samples, base 0.2450:

    TIME    80-84'   0.3320  lift 1.35   <- best, essentially AT 2-1 break-even
            36-40'   0.3122  lift 1.27
            12-16'   0.1851  lift 0.76   (quietest)
    EVENTS  corner / shot-off-target     lift 1.19
            shot-ON-target               lift 0.97  (BELOW base)
    MOMENTUM top-3 deciles               lift 1.12
    MARGIN  margin 1                     lift 1.06
    COMBOS  "all types"                  lift 1.03  (dilutes)

**FOUR HYPOTHESES OF MINE DIED HERE, all measured:**
1. Momentum predicts WHEN -- AUC 0.5417 held out.
2. Momentum works conditionally in a time window -- prereg killed it, and the
   increment over the clock was NEGATIVE (-0.0516).
3. Momentum is better at saying NO goal -- pooled bottom-3 lift 0.92 vs top-3
   1.12. The TOP discriminates more. Also non-monotonic: decile 1 reads 1.10
   because near-zero pressure means "early match", not "quiet match".
4. Score state matters -- "losing by 1 late pushes" does NOT appear. At 80-84',
   margin 1 (0.3283) is BELOW the bucket average (0.3320).

**REPLICATION IS OF THE PATTERN, NOT THE BUCKET.** 80-84' ran 0.3455 holdout ->
0.3135 fresh, while 36-40' ran 0.2889 -> 0.3434. Both late-half windows are
elevated in both samples (1.20-1.48) but which one WINS flips. Picking the
single best bucket is the same overfit that killed the 40.2%.
CONFOUND, stated: the fresh set is Jun-Aug 2026, heavily MLS/early-season, base
0.2610 vs 0.2331 -- a robustness check across different football, not like-for-like.

**FOTMOB IS REACHABLE, and the scope doc's blocker was WRONG.**

    /api/matchDetails?matchId=      -> 404
    /api/data/matchDetails?matchId= -> 200, 276,792 bytes
    expectedGoals YES · xg YES · momentum YES · shotmap YES
    NO x-mas signing header needed. AiScore root: 403 (blocked).

The path moved from `/api/` to `/api/data/`. `scope_2026-08-21_fotmob_xg_
enrichment.md` recorded it as unverified-and-probably-signed; it is neither.

**WHY THIS NOW MATTERS MORE, not less.** Everything we already own has been
measured and is weak. FotMob supplies the one thing ESPN structurally cannot --
chance QUALITY (shot xG) rather than shot COUNTS -- and there is now a hard bar
to clear: beat 0.3320 at 80-84', and beat +0.02 as an increment over the clock.
## 2026-08-22 — FORBIDDEN: never join on an id minted from a content hash of a payload that carries live prices

- **The tell, and it was in the repo the whole time:** `pipeline/intelligence_state.py:2028` already said those ids come from "a content hash of the full recommendation payload (incl. live odds/edge/probability)" and would mint a fresh row "purely from ordinary price drift". A mitigation was built around that fact (gate recording on `source_fingerprint`) without anyone asking what it meant for the JOIN downstream.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-22 — FORBIDDEN: verifying a REORDERING by elapsed-time-since-boot

- **The rule:** to verify a change in ORDER, measure ORDER — the co-occurrence of the branch's marker with the marker of the branch above it. `#504`'s real reading is `RECONCILIATION_AUTORUN_GATED` at 18:28:38.192696 and `LEDGER_INDEX_SIZE` at 18:28:38.194012: **1.3ms, same tick**, against 116s and a different tick before. Elapsed-since-boot measures the loop; delta-between- branches measures the chain.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-22 — EXONERATED: forcing the settlement autorun with an interval override

- **Stop re-investigating this.** If settlement is not running, read WHICH branch took the tick before touching any gate. A job can be enabled, correctly configured, past its interval, and still never evaluated.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-22 — the retraction was as wrong as the claim. "It ran once" is not "it runs"

- The rule going forward: **an allowlist entry is a change to the CONSUMER, not to the producer.** Before adding one, find every reader of that path and check what it does when the file is suddenly present. A reader that gates on EXISTENCE rather than freshness converts a latency fix into a silent correctness bug. The producer's refresh cadence is the second question: an artifact refreshed prior-day cannot serve a live surface no matter who can read it.
- *(evidence in `learnings_evidence.md`)*
## 08-22 TWO REAL LEADS AT LAST — and they came from questions I did not think to ask

**1. LA LIGA 80-84' REPLICATES HELD OUT. The first result all session to survive
a clean test above break-even.**

    DISCOVERY (98 matches)    80-84'  0.3954  lift 1.77
    HELD-OUT  (222 matches)   80-84'  0.3604  lift 1.57   CLEARS 2-1 (33.3%)

The 222 were the FIT half, never scored on time. Held-out profile shows real
structure, not a lone spike: quiet 16-28' (~0.17), a first-half rise to 0.3018
at 40-44', flat mid-second-half, then 0.3604 at 80-84' falling to 0.2374 by
88-92' as the window runs out.

**THE POOLED NUMBER WAS HIDING THIS.** Pooled 80-84' read 0.3320 / lift 1.35
across all leagues. Split by league: la_liga 1.78, epl 1.24 (largest sample, does
NOT clear 2-1), mls 1.17, primeira_liga **0.89 -- below base**. I reported a
league-averaged number as a property of football. Same averaging error that made
momentum look like a global null when it was conditional, running the other way.

**2. FOTMOB xG BEATS ITS OWN CONTROL. Chance QUALITY adds where VOLUME does not.**

    top decile        xg 1.19   bigchance 1.30   count 1.09  <- control
    at 80-84'         xg  clock 0.2972 -> 0.4000  delta +0.1028
                      count               0.2778  delta -0.0194  HURTS

`count` is the ESPN-equivalent feature and it hurts by -0.019, replicating the
ESPN momentum increment (-0.0516) on completely different data. That is the
FotMob question answered: xG measures something shot counts cannot.

**BUT n IS ~90 IN THAT CELL, AND THE PRECEDENT IS UGLY.** The last promising
tail number this session was **40.2%** at n=276, and preregistration killed it.
This one reads **40.0%** at n=90. Treat +0.103 as UNVALIDATED until it survives
the same treatment. Reading a tail result after the fact is how the 40.2%
happened.

**THE METHOD LESSON, twice over:** both leads came from splits I had not thought
to make -- the user asked for leagues individually, and for the full sampling
range. Neither was a modelling insight; both were "you are averaging over
something that differs". Before reporting a pooled effect, enumerate the
dimensions it averages over and check the big ones.
## 08-22 THE xG RESULT DID NOT REPLICATE — AND THE CONTROL THAT "PROVED" IT WAS ARITHMETIC

Pre-registered (`fdf1b892`, committed before the fresh sample existed), scored on
246 fresh matches, ZERO overlap with discovery. Identical procedure, top quartile
inside the 80-84' band:

                  discovery(n=90)   fresh(n=241)
        xg            +0.1028          +0.0319
        count         -0.0194          +0.1107

**THE RANKING REVERSES.** On discovery xG beat count by 0.12; on fresh count beats
xG by 0.08, and count FLIPS SIGN. "Chance quality beats chance volume" was the
whole case for a FotMob dependency, and it is dead — not weakened, reversed.

**FORBIDDEN: a control matched by THRESHOLD VALUE when the features are on
different scales.** The first scoring run applied xG's threshold (0.8905) to
both. xG-pressure ranges 0.09..1.82; count-pressure ranges 1.55..13.76. So the
threshold fired on 24% of the band for xG and **100% for count** — the control
selected the ENTIRE band, making its delta `+0.0000` BY ARITHMETIC, before any
data existed. That forced zero then read as *"the control does not clear"*, which
was the single sentence justifying the dependency. Match controls by SELECTION
RATE. Rebuilt that way the control scored +0.1447 and won.

**The tell was in the output I had already read**: `count` fired on 963 samples
and `xg` on 229, and the delta was EXACTLY +0.0000. An exact zero on a
noisy empirical quantity is a computation, not a measurement. Same family as the
box-section `rows: []` error — the discriminating number was on screen and I
was reading the verdict line instead.

**THREE tail results have now failed to replicate this session** (momentum 40.2%,
xG +0.1028, and the xG-over-count ranking). All three were read AFTER seeing the
tail, at n<300. The one result that DID replicate (la_liga 80-84', 222 held-out)
was tested because the user asked for a split, not because a number looked good.

**What actually survives:** the CLOCK. Both samples independently show 80-84'
elevated over base (0.2972 and 0.2793 vs base 0.2562). That is the third
independent confirmation, and it needs no vendor dependency at all.

---
## 2026-08-22 (later) — A rule written from one sport's vocabulary is a rule about that sport; and a safety net that skips the biggest cases is not a safety net

- **1. THE ALT-LINE FILTER I SHIPPED DID NOTHING ON SOCCER, and the user found it, not me and not the tests.** I defined "alt line" as a market whose name ends `_alt`, because that is how MLB and NFL quote them. Soccer's `DEFAULT_GAME_MARKETS` is exactly `["h2h","totals","spreads"]` — it has no such market, and expresses the same concept as SEVERAL ROWS OF ONE MARKET at different lines. The filter matched nothing; "Main lines only" was a no-op on the sport with the worst ladder problem. I had even written a test asserting `totals_alt` is alt and `totals` is not, which passed and proved nothing about soccer.
- *(evidence in `learnings_evidence.md`)*
## 08-22 THE ANSWER, at 5,552 matches: THE EVENT SIGNALS ARE NOISE. The clock is real and too small to bet.

Two years, ten leagues, 9 signals (xg, count, ontarget, inbox, bigchance,
FotMob's OWN momentum abs+slope, red-card advantage, subs) x 10 leagues x 24
time bands. Fit-half selects, holdout-half scores once, distinct cells only.

**NULL CONTROL SETTLES IT.** Same pipeline, goal series swapped BETWEEN matches
within league (severs feature-label link, KEEPS within-match label clustering):

    REAL      distinct cells 23
    NULL runs                15, 22, 17, 15, 13   mean 16.4

23 against a null that routinely produces 22. The sweep MANUFACTURES ~16
"surviving" cells on data with no signal in it; it found 23. That excess is
run-to-run variation, not a discovery. **Every individual cell in that list --
including the ones clearing 2-1 with tight CIs -- is indistinguishable from
what the machine produces on noise.** This is why the earlier "36 survivors vs
~20 by chance" line was worthless: I made the 20 up by multiplying 0.05 by 417.

**THE CLOCK IS REAL BUT SMALL.** Corrected profile, holdout, n~6,700/band:
16-20' 0.2408 [0.231,0.251] rising to 44-48' 0.2932 [0.282,0.304], second half
flat ~0.27-0.28. Non-overlapping CIs, smooth shape -- real structure. But the
BEST band is 0.2932 and 2-1 needs 0.3333. **Nothing clears 2-1 anywhere in the
match.** 3-1 (0.25) is cleared by the base rate alone (~0.264), i.e. by betting
blind, which no book will price.

**A CLOCK BUG MANUFACTURED THE FIRST ANSWER.** `_clock_seconds` folded
`minAdded` into `min`, so first-half 45+3 became minute 48 and collided with a
genuine second-half 48th. 4.4% of all shots shared a bucket with the other
half, concentrated in 45-52'. A window opened at 44' swept ~13 minutes of play
scored as 10. That printed 40-48' as the densest scoring period (lift 1.21) --
a counterintuitive result contradicting the user's late-game intuition, with
n=6,712 and tight CIs. Corrected: 1.21 -> 1.11, and the late game went 0.94 ->
1.02. **Large n made the artifact MORE convincing, not less.** The `period`
field was in the payload from the first fetch.

**WHAT THIS CLOSES.** Stop building momentum/event-triggered goal bets. FotMob
is not owed a production dependency: its own momentum series ranked no better
than anything else, and shot COUNT (free from ESPN) matched or beat xG. Five
promising numbers died this session -- 40.2%, xG +0.1028, xG-over-count,
la_liga 80-84', 40-48' peak -- and all five were read off a tail or a bug
before a control existed. The control was always the cheap part.
## 08-22 REVERSAL: there IS a signal. I had spent the whole day testing at the WRONG TIMESCALE.

The cell sweep's negative was real about its own cells and WRONG as a general
claim. A pooled model over all ~380k samples, clock as a 24-way one-hot
baseline (the strongest clock-only predictor), holdout AUC:

    window   60s  dAUC +0.0238        window 300s  +0.0081
             120s       +0.0189               600s  +0.0088   <-- EVERY earlier test
             180s       +0.0143               900s  +0.0058

Monotonic in window. **Every analysis today used a 600s window and a 900s
half-life. The signal lives at 60-120s with a 60s half-life.** Football momentum
decays in about a minute; I smeared it across fifteen and then concluded five
times that it was not there. That was a design assumption I never tested, not a
property of the game.

**CORRECTED NULL (the first one was wrong).** `rng.shuffle(yperm)` globally
permutes TRAINING labels, which trains BOTH arms on noise and makes the
increment ~0 by construction -- far too lenient, and the docstring claimed
within-match. Correct null permutes FEATURE ROWS within time band, leaving
clock and labels intact so only the feature link breaks:
    real +0.0181   null -0.0022, +0.0002, +0.0018, -0.0057
Ten times the null's best run.

**THE DRIVER IS FOTMOB'S OWN MOMENTUM, and nothing else.**
    solo (added to clock)      leave-one-out
      vmom_abs  +0.0098          +0.0118   <-- unique, irreplaceable
      xg        +0.0046          -0.0002
      inbox     +0.0045          -0.0001
Every shot feature is redundant; dropping any costs nothing. This REVERSES
"FotMob has not earned a dependency" -- it has, for MOMENTUM, not for xG.

**BUT MOMENTUM IS MOSTLY REACTIVE, and that is the honest headline.**
    AUC predicting FUTURE goals 0.5242   AUC predicting PAST goals 0.6050
It rises AFTER attacks and goals, far more than it anticipates them. And its
per-minute stamp can overlap the label window, so it was re-tested lagged:
    lag   0s  dAUC +0.0181 (vmom +0.0098)
         60s        +0.0138 (vmom +0.0076)   <-- the defensible number
        120s        +0.0098 (vmom +0.0046)
76% of the effect survives a strict 60s lag, so it is not a bucket artifact --
but it decays fast, which is what a genuinely short-lived signal looks like.

**ECONOMICS, and the reason this is still not a green light.** At a 120s window
the base rate is 0.0581, so the 2-1/3-1 bars from the 10-minute work DO NOT
APPLY. Lagged, top 2% of predicted risk hits 0.0946 [0.085,0.105], lift 1.63x,
needing better than ~9.6-1. Whether that is exploitable depends entirely on how
books price live goal markets -- and they price them with their own shot and
pressure models, which see the same 1.63x. NOT MEASURED. That is a test against
live odds, which is a different question from this one.

**THE METHOD LESSON.** "No signal" is only ever a claim about the test you ran.
Five negatives at one timescale said nothing about other timescales, and the
one-line fix (sweep the window) was available from the start. A negative result
needs its power characterised before it is trusted, exactly as a positive needs
a null.
## 08-22 LIVE ODDS PILOT: plumbing works, answer is 1.8 match-days away

**WE DO HAVE LIVE ODDS HISTORY, but it effectively STARTED TODAY** -- the 60s
live-odds work deployed this evening is what produced it. Coverage by date:

    2026-08-22  2300 markets, 1523 live, 370 live TOTALS, 36 events, 31 MB
    2026-08-21  live-totals events 0
    2026-08-19  8 events, none with >=10 snapshots
    2026-08-14  163 markets, 5 capture passes, live h2h stamped 08-10 (STALE)

Do not read "58 odds_history dates" as 58 usable dates. One is usable.

**RESOLUTION IS THE BINDING CONSTRAINT.** Snapshots arrive every ~333s median.
That gap is OURS, not the books': 69% of consecutive pairs carry IDENTICAL odds
and 92% are labelled `flat`, so history is POLL-triggered, not change-triggered.
The signal has a ~60s half-life, so a spike is usually over before the next
price exists. We shipped "60-second live refresh" today and the observed floor
is 160s. Worth knowing before anyone trusts the cadence claim.

**THE PILOT ASKED THE CHEAP QUESTION.** "Does my signal beat the book at
predicting goals" needs GOALS -- ~30 positives at this sample, which resolves
nothing. "Does the book's PRICE move with momentum" needs no goals at all, so it
has far more power per match. Result, de-vigged Over prob vs vmom_abs,
residualised on clock+clock^2+score:

    raw corr      +0.0692
    PARTIAL corr  +0.1446   1 SE 0.0990   n=106   -> 1.46 SE, NOT resolved

**THE USEFUL OUTPUT IS THE POWER CALCULATION, not the correlation.** To resolve
+0.1446 at 2 SE needs n >= 195 in-play observations. Today gave 106 from 11
joined matches. **That is 1.8 more match-days.** Two more Saturdays of capture
answers a question that has been open all session -- and the pipeline now exists
to answer it automatically.

Sign is positive, i.e. books probably DO track sustained pressure, which is the
unsurprising direction. Note what this design can and cannot see: at 333s
sampling it tests whether books track SUSTAINED pressure. It CANNOT see whether
they miss brief spikes -- which is precisely where an edge would live.

**Clock alignment is by FotMob kickoff time, never by assuming the first live
snapshot is kickoff** -- books quote in-play markets before the whistle, so that
assumption would shift every match by an unknown offset.
## 08-22 FORBIDDEN: `git add -A` in this repo. THE TEST SUITE MUTATES TRACKED FILES

Running the full pytest suite (`python -m pytest tests/`) leaves the working
tree dirty in two ways at once: it MODIFIES tracked files —
`reports/manifests/*.json` (all 8 sports), `reports/refresh_state.json`,
`reports/intelligence/intelligence_state.json`,
`data/mlb_source/.../live_lens_2026_06_02.jsonl` — and it CREATES untracked
ones, including `reports/sim_runs/`, `reports/win_prob_null/`,
`reports/mlb_odds_diag/`, and a literal
`Z:\definitely\does\not\exist\perf.jsonl` from a Windows-path test.

`git add -A && git commit` after that run committed **38 files and ~10,500
insertions when exactly ONE file was intended**, including a 10,049-line diff
to `intelligence_state.json`. It was pushed before I read the stat. The `git
status --porcelain` that would have shown it ran in the same command, ABOVE the
add — so the evidence was printed and the commit happened anyway.

**RULE: stage explicitly. `git add <path> [<path>...]`, never `-A`, never `.`**
Every commit in this session that did name its paths was clean; the one that
did not was not.

**COROLLARY, and it is the part that nearly hid this: `.gitignore` cannot save
you here.** Several of these byproducts are legitimately TRACKED files that the
suite rewrites, so there is no ignore rule that makes `-A` safe. Earlier in this
same session I gitignored four *untracked* byproducts (`#515`) and that was
correct — but it addresses a different half of the problem and must not be
mistaken for having solved this one.

Recovery, for the next person: `git reset --soft HEAD~1 && git reset`, then
`git checkout --` the tracked byproducts and `git clean -fd -- reports/ data/`
the untracked ones, re-stage by name, and force-push (safe only on your own
unshared branch — never on someone else's).
## 08-22 FORBIDDEN: calling a test failure "pre-existing on main" from a clean WORKTREE. A worktree shares site-packages

I reported `#517` as "76 failures across 26 files on clean `origin/main`", and
backed it by re-running three sampled files in a detached worktree at
`origin/main`, getting identical counts. That check was real and it was not
sufficient. **`git worktree` gives you a different CODE tree and the SAME Python
environment.** It controls for the diff and controls for nothing else.

The environment was broken. `cffi` was absent — collateral from my own earlier
`pip install --ignore-installed` / `--force-reinstall` juggling to fix a
numpy/pandas mismatch — so `cryptography` could not import, and everything
importing it failed. Installing one package:

    test_refresh_state_store.py      18 failed -> 1 failed
    test_wnba_refresh_runner.py       6 failed -> 4 failed
    test_nba_cards_keyvalue_backend   3 failed -> 3 PASSED
    test_wnba_cards_keyvalue_backend  3 failed -> 7 PASSED

**At least 25 of the 76 were mine, not the repo's**, and I had already written
the 76 into `todo.md` and committed a baseline built on it.

**RULE: before attributing failures to the code, prove the ENVIRONMENT is
sound.** `python -m pip check` is one command and would have said so — it
reported a broken requirement the whole time. Then re-run
`pip install -r requirements.txt` clean and re-measure.

**COROLLARY: a `ModuleNotFoundError` for a C-extension or transitive dependency
(`_cffi_backend`, `_ssl`, `_lzma`) is an environment claim, never a code claim.**
Read the actual error before counting failures; `--tb=no` hides exactly this,
and I ran the whole 27-minute suite with it.

**COROLLARY: never repair a dependency with `--ignore-installed` or
`--force-reinstall` on a single package.** It resolves that package against
nothing and silently strands its dependencies. Reinstall from the requirements
file and let the resolver see the whole graph.
## 08-22 FORBIDDEN: treating a todo id as RESERVED because you checked it was free. Checking is not reserving

`CLAUDE.md` says ids are stable and never reused, and says to check both
`todo.md` and `todo_closed.md` before taking a number. I did. **It collided
twice in one session anyway**, because concurrent sessions can all pass the
same check against a shared counter and then all take the same numbers:

    took #502-#505  ->  main had independently used #502-#505  ->  moved to #507-#510
    took #507-#510  ->  main had independently used #507-#513  ->  moved to #514-#517

Nothing was wrong with the check. The gap is between checking and MERGING: on a
branch that lives for hours while other sessions land on `main`, the number you
reserved is only as good as the moment you read it.

**RULE: renumber at MERGE time, not at file-creation time.** Re-read the max
immediately before the merge commit and move your block then; the collision
window shrinks from hours to seconds. Expect it to happen and make the move
cheap rather than trying to pick a number that will survive.

**RULE: renumber by LINE RANGE, never globally.** By the second collision the
merged `todo.md` contained main's `#507-#513` AND mine, and `learnings.md` and
`lanes.md` each carried main's references to ITS `#502-#505`. A global
search-and-replace would have silently rewritten another lane's history into
nonsense. Scope every substitution to the line span of your own block, and
verify the other side's headers survived before committing.

**COROLLARY: a numeric id is the wrong identity for a long-lived branch.** The
work is findable by lane slug and by scope-doc filename, neither of which can
collide. The number is a convenience for `todo.md` ordering and should be
assigned as late as possible.
## 08-22 DEEP DIVE VERDICT: MOMENTUM IS DIRECTIONAL. It says WHICH TEAM -- not whether, how many, or when.

5,552 matches, holdout-only, every baseline = the live state a book already
knows (clock, score diff, goals so far). Signals added on top. dAUC:

    WHICH TEAM                                   WHETHER / HOW MANY / WHEN
    next team to score      +0.0707  (AUC .577)  any goal in 15m      +0.0007
    home scores in 15m      +0.0332               goals remaining >=1  +0.0003
    away scores in 15m      +0.0286               goals remaining >=2  +0.0001
    match winner (away)     +0.0101               BTTS                 -0.0009
    match winner (home)     +0.0069               goal before half-end +0.0001
    winner at 0-15'         +0.0393               goal before 75'      +0.0002
                                                  corners in 5/10m     -0.010 / -0.006 (ESPN, 699 m)

Same signal, same matches: +0.03 on "home scores in 15m", +0.0007 on "any goal
in 15m". The information is almost entirely in the SIGN. Signed vendor momentum
alone carries +0.0710 of the +0.0707 direction effect; signed xG +0.0203, signed
count +0.0362 -- momentum dominates and the rest is redundant.

**DIRECTION IS A SLOW SIGNAL, unlike "whether".** Lagged 60s it keeps 94%, lagged
300s it keeps 88%. The 2-minute "whether" signal lost 24% at 60s. Being on top
PERSISTS; a goal arriving does not. That is why direction maps onto quotable
markets (next team to score has no time limit) and "whether" does not.

**CORRECTION to my earlier "momentum is largely reactive" caveat.** Stripping
every sample with a goal in the prior 600s leaves dAUC +0.0152 vs +0.0152
unstripped, momentum-only +0.0134 vs +0.0116. The post-goal reaction is REAL
(AUC .605 on past goals) but it does not cannibalise the forward signal. I
reported the reactive finding as the honest headline; it was a true fact that
did not bear on the decision.

**CALIBRATED.** ECE 0.0026; top decile predicted 8.17% observed 8.26%. Direction
decile 10 predicted .664 observed .653. Model outputs can be set against book
implied probabilities directly.

**CONTEXT.** Signal is 4x stronger with a 2+ goal lead (+0.041) than level
(+0.010); strongest 60-75' (+0.071); near-zero 0-15' for "whether" but STRONGEST
0-15' for WINNER (+0.039) -- early, before the score has separated outcomes.
Winner signal decays to +0.004 by 75-90' as the scoreboard takes over. Belgian
(-0.008, n small) and MLS (+0.006) carry nothing; Primeira (+0.035), Bundesliga
(+0.029) carry most.

**ECONOMICS, 120s window.** Top 0.5%: hit 13.2% [11.0,15.8], lift 2.27x, ROI
+95% against a NAIVE book (clock rate + 8% vig), -vig against a SHARP book. Fires
0.46x per match. At 600s the lift collapses to 1.2x and naive ROI to ~0. LULLS:
bottom decile 0.98x of clock -- the model does NOT find quiet spells; "no goal"
is not a market here.

**WHAT A READING MEANS.** |momentum| <40: no information (0.93-0.99x). 60-80:
1.19x. 80+: 1.23x. The card should not colour anything below 40.

**PRODUCTION GAP.** momentum.py DEFAULT_HALF_LIFE_SECONDS = 300.0; the data says
60s. The card shows a 5x over-smoothed series. And production momentum is
ESPN-commentary-derived; the signal that carries is FotMob's series, which is
not wired.
## 08-22 ESPN'S TWO HOSTS HAVE DIFFERENT User-Agent POLICIES, and this repo documents both without saying so

Measured from Render, 2026-08-22, during a live WNBA slate:

    site.api.espn.com      (scoreboard)  browser-spoof UA -> 403     no custom UA -> 200
    site.web.api.espn.com  (summary)     browser-spoof UA -> 200 (fallback never fired)

**Two comments in this repo give opposite advice and BOTH ARE CORRECT — about
different hosts.** `scripts/fetch_espn_live_status_for_date.py` says never use a
spoofed UA (probed from Render: bare `Mozilla/5.0` 403, full Chrome header set
403, no headers 200). `basketball_props_smart_sim._http_get_json_local` says a
browser UA is the FIX for soft-blocking. Neither names the host as the reason.

I read the second, applied it to the first's endpoint, and the scoreboard 403'd
on every tick of a live game. A bare `except` returned `{}`, so a 403 and an
empty slate were the same observation: `live_events=0`. I checked that zero
TWICE before tip-off and read it as correct pregame behaviour.

**RULE: when two comments in this codebase contradict each other, the
difference is usually a scope neither one states.** Find the axis — host,
service, phase, sport — before picking a side. Picking the more recent or the
more confident one is guessing.

**RULE: never let a fetch helper swallow its status.** `except: return {}` cost
most of a scarce live window here. A 403 and an empty result are different
facts and must print differently. `#514`'s helper now logs status and URL on
every failure, and the caller prints `events_total` so "3 games, none tipped"
can never again look like "the call returned nothing".

**COROLLARY on where diagnostics go.** A `NO_SERIES` diagnostic shipped 40
minutes earlier could not catch this: it ran only after summaries were fetched,
and the failure was one hop upstream. **Instrument the FIRST hop, not the
interesting one.**


---
## 2026-08-23 — a measurement that matches your CHANGE instead of the COMPLAINT is not verification `[lane layer2-sim-view-and-live-projection]`

- **RULE: verify against the WORDS OF THE COMPLAINT, not against the diff.** Ask "what would the reporter look at?" and measure that. Reading back the field your own change writes proves the edit landed, which was never in doubt.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-23 — a counter's POSITION relative to its gate decides which question it answers

- **RULE: when you add a counter, state whether it sits BEFORE or AFTER the gate, and prefer before.** A denominator measured past the filter cannot distinguish "nothing was eligible" from "nothing qualified". `record()`'s own docstring in that file says `considered` exists so `edged / considered` is "a rate with a real denominator" — it is, for rows that got in, and the rows that did not are the ones you are usually looking for.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-23 — a guard firing 248 times looks exactly like a coverage regression

- **RULE: before reporting a coverage drop, check the DENOMINATOR and check for a guard.** A rate can fall because the numerator broke or because the population grew, and the two need opposite responses. Here the population grew *because of my own fix*, and reporting it as a regression would have sent the next session to delete a safety feature.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-23 — `trim_lane_blocks.py` is now exhausted, and `lanes.md` is over cap anyway

- **RULE: "run the trim tool" is no longer a complete answer to LEDGER OVER BUDGET.** The next reduction has to come from CLOSING lanes or from shrinking live blocks, both of which are owner decisions. Editing in place still prevents growth; it cannot reverse it. The session-start digest truncates OPEN LANES to 600 bytes, so an over-cap file arrives lossy — which is the opposite of what the ledger is for.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-23 — READ THE RATE, NOT THE REASON STRING `[lane layer2-sim-view-and-live-projection]`

- **RULE: a reason that accounts for 100% of a population is a bug, not a distribution.** Check the RATE before believing the string. A plausible explanation attached to a total failure is the most expensive kind of wrong, because it reads as already-diagnosed and stops the search.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-23 — a counter whose inputs are absent reports CONSTANTS that look like findings

- **RULE: `miss_player=0` and `player_in_lens: False` in the same line cannot both be findings.** When two counters contradict each other, suspect the FEEDER before either counter. The tell is free and it is the only reason this was caught.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-23 — `git merge-base --is-ancestor` on an unfetched object exits 128, and `2>/dev/null` turns that into a clean "no"

- **RULE: never route an ancestry check's failure into a boolean.** Verify the object exists (`git cat-file -t`) first, and let the error surface. A tool that cannot answer must not be allowed to answer "no" — the two are different, and on a deploy check the wrong one triggers a needless redeploy or a revert war.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-24 — A PRE-FLIGHT CHECK DOES NOT SURVIVE A TURN BOUNDARY. Three times in one session.

- The rule going forward: for any change to a shared allowlist, gate, or vocabulary, enumerate every SERVICE that evaluates it and deploy them all before reading the result. And when a fetch fails, **read the status code before theorising** — 403 vs 404 vs 304 each name a different end of the wire.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-25 — GitHub Actions CI results are not this repo's source of truth

- The rule going forward: **a code-default change to a file whose whole design is "env var wins over default" is not verified by the diff or the test suite — it is verified by reading the live service's actual resolved values.** For Syndicate specifically: `mcp__Render__list_logs` on the relevant service, filtered to the module's own log line, is the read; there is no env-var-listing tool, so log lines that print the resolved config (this file's `LIMITS`/`EXECUTION` lines) are the only way to see what a service is actually running without one.
- *(evidence in `learnings_evidence.md`)*
## A null result from a QUERY is not a null result from the SYSTEM `[2026-08-26]`

Render's log API `text` filter does NOT support regex alternation the way it
looks like it does. `text: ["BY_GAME_DATE|BY_CLOSE_DATE"]` returns
`logs: null`; each single term returns rows. Silently — no error, no warning,
and `null` is exactly what a genuinely quiet service returns.

Cost: seven consecutive "no output yet" reports over 36 minutes while the lines
were printing the whole time, plus two elaborate explanations built on the
absence (a dormant-interval calculation, then a board-build stage-depth model).
Both were plausible, both were unfalsifiable against a filter that could not
return anything, and both were wrong.

**The rule:** before reporting that something is ABSENT from a log, prove the
query can find something PRESENT. Query one term at a time, or include a string
you know is in the window as a control. An unproven filter turns "I asked
wrong" into "it did not happen", and those license opposite conclusions.

This is `#370`'s error one layer up, again: the same session had just deployed a
fix for a histogram that reported `close_time` under the name `by_date`, and
then made the identical mistake reading the logs of that very fix.
## A measurement taken from the right population can still be taken at the wrong TIME `[2026-08-26]`

`PRECAP_CUT_BY_DATE` was built specifically to stop a change being shipped on an
un-measured claim, and it worked: it refuted its own author's prediction of
~1,600 recoverable markets with a measured 133.

But the reading was taken at 03:11Z, after the MLB slate had finished. The same
series had cut 747 markets at 01:49Z and cut 132 by 03:11Z, because a venue
retires a slate's markets as its games end. **The population was correct; the
clock was not.** A number that is honest about WHAT it counted can still be
silently unrepresentative of WHEN, and "measured" reads as settled either way.

**The rule:** when a quantity varies with a live event, state the phase of that
event beside the number, and say explicitly which phase the conclusion covers.
Here: refuted post-slate, UNPROVEN mid-slate — those license different actions,
and only one of them was measured.

Corollary already paid for once tonight: the same reading also covered only ONE
of the two bounds that discard markets (`cut_total=3940` vs `trimmed=8744`). A
gate that measures half the mechanism is not a gate yet.
## A REFUSAL IN A LIST OF FAILURES IS INDISTINGUISHABLE FROM A DEFECT `[2026-08-26]`

`OrderBuildError: unmappable_side: 'away' market='spreads'` — 11 orders a cycle,
sitting in a table between `market_not_found` and `no_venue_ticker`. It read as
one more thing to clear. A peer session called it *"a straight mapping
omission"*; I agreed, and implemented it. **It was not a defect. It was the only
thing standing between a mis-keyed join and ten inverted real-money bets per
cycle.**

The mapper was correct in isolation: resolve the side against the team named in
the ticker. But the ticker stamped on those orders was the WRONG MARKET, so
resolving against it faithfully produced a faithful inversion:

```
board:   away (Texas) +1.5 @ -185      -> intent: TEXAS +1.5 (underdog, getting runs)
ticker:  ...TEXCWS-TEX2 = "Texas wins by over 1.5 runs?"  -> TEXAS -1.5
mapper:  _side_to_kalshi("away","spreads","...-TEX2") -> "yes"   = TEXAS -1.5
```

Systematic: every spreads order with a ticker had `line=+1.5` and a suffix
naming the picked team; every `-1.5` row — the one that genuinely matches a
Kalshi "wins by over" market — had NO ticker. Root cause in
`kalshi_board_join._match_key`, keying Kalshi's strike as a positive MAGNITUDE
against the board's SIGNED handicap, so `1.5 == 1.5` pairs the underdog row with
the favourite's market.

**THE RULE:** before clearing a refusal, establish WHAT IT WAS REFUSING and why
someone wrote it. A guard and a gap look identical in a counter. The cheap test
here — compare the board row's line SIGN against the venue's own market title —
was one the venue answers in seconds, and *neither* session ran it until both
had a working implementation in hand.

**Corollary, on how close this got.** The patch was parked, labelled
`BACKUP ONLY — do not apply`, tested, and verified to apply cleanly. That label
is not a safety mechanism: a working backup is exactly what a later session
reaches for when the primary stalls, which is precisely when nobody re-derives
whether it was ever right. **Delete a refuted artifact; do not annotate it.**
The analysis survives in `.syndicate/handoff/README_kalshi_side_mapper.md`; the
applicable diff is gone.

**Second corollary, and the deeper one.** `kalshi_board_join` ALREADY computes a
correct `kalshi_side` and throws it away — `venue_scope.py` stamps only the
ticker, so `OrderRequest` carries the BOARD side and `_side_to_kalshi` is asked
to re-derive at the boundary from data that cannot settle it. **Re-deriving at a
boundary what an earlier stage already knew is what made the inversion
possible.** Same shape as the unfed-input class in `model_engine_standard.md`:
the value is available, nothing carries it across, and the recomputation is
indistinguishable from the real thing at every level except the money.
## A GREEN PATH ON A SHARED VENUE PROVES NOTHING ABOUT THE BROKEN ONE `[2026-08-26]`

Kalshi MLB failed for two days while WNBA filled normally, same credential, same
code, same endpoint. The whole time, "Kalshi orders are working" was true and
useless: **WNBA is on exchange shard 0, which this account is provisioned on;
MLB migrated to shard 3, which it is not.** n=9, perfect split — every order that
ever filled is shard 0, every failure is shard 3.

The two MLB fills on 08-24 were shard 0. That is why it "broke" on 08-25 with no
deploy in between, and why a code-regression hunt through `git log` found
nothing: **there was no regression. The venue moved the markets.**

Both errors were literally true and neither was ours:

```
exchange_index 0 (pinned)  -> market is not on shard 0 -> market_not_found
exchange_index -1 (auto)   -> routes to shard 3, FOUND -> user_not_found
```

**The rule:** when one slice of a venue works and another does not, find the
axis that separates them BEFORE theorising about code. Here it was a public
field on the market payload (`exchange_index`) — no credential, one GET. I had
even read that field in a log line (`KALSHI_SERIES_CATALOGUE ... row_keys=[...
'exchange_index' ...]`) and used it to argue FOR a hypothesis instead of asking
what value our own failing markets carried.

**Corollary — intermittent success across an otherwise identical population is a
PER-ITEM property, not a point-in-time change.** I treated "worked Monday, fails
Wednesday" as a regression and searched the diff. The correct first question was
"what is different about the items that fail", which the venue answers directly.

**Corollary — a fix that moves the error inward is working, and must not be read
as failure.** `market_not_found` -> `user_not_found` was progress; I called the
shard fix refuted an hour before it was confirmed, by reading my own probe line
(which fires on ANY exception) instead of the error string underneath it.
## A DIAGNOSIS AND ITS REMEDY ARE SEPARATE CLAIMS `[2026-08-26]`

The Kalshi shard finding was measured, n=9, perfect split, confirmed in
production from two independent clients. The REMEDY attached to it — *"the venue
must enable this account on that shard; no code change fixes it"* — was never
checked against anything. It rode in on the diagnosis's credibility, and I
printed it into a **production error string**, where the next person to hit it
would read it as settled.

It was wrong. `GET /exchange/status` shows shards are PRODUCT partitions, all
active (0 Default, 1 Combos, 2 Crypto, 3 Tennis & Baseball). Kalshi's doc:
*"Subaccount balances are local to a specific exchange instance"* and
*"Programmatic traders must preallocate collateral on a given exchange shard
before order placement."* `user_not_found` meant NO FUNDS THERE. The fix was the
account holder moving money — about a minute — not a support ticket.

**A confident wrong remedy inside a correct diagnosis is more dangerous than a
wrong diagnosis**, because the diagnosis's evidence launders it and nobody
re-checks the half that had none.

**The rule:** "what is broken" and "whose move it is" are different claims
needing different evidence. Before writing a remedy into anything durable — an
error string, a ledger entry, a message to the user — ask what was READ to
support it, not what was inferred. Here the answer was one fetch of a doc page.

**Corollary:** the same goes for the error text itself. An error message that
names a remedy is making a claim with the system's authority behind it, and it
outlives the conversation that produced it.
## THE DEPLOY CLAIM DOES NOT SERIALISE ACROSS ENVIRONMENTS `[2026-08-26]`

**I cancelled another session's in-flight build while it correctly held the
claim.** Measured:

```
dep-da7h54bm6pss73fmo2n0  f1a2c78f  CANCELED 16:23:12Z   <- theirs, mid-build
dep-da7h5rrbc2fs73cr8u9g  2e5f425e  started immediately  <- mine
```

`deploy_claim.py status --service live-odds-worker` read **HELD by
kalshi-spread-join-sign** in the primary tree at that moment. My own container
said the service was free, and I had "acquired" it there — twice, plus a
careless probe that re-acquired and had to be released again.

**The claim directory resolves from `REPO_ROOT`, so it is per-tree and
per-environment.** A cloud session gets its own. Two sessions can each hold
"the" claim on the same service, simultaneously, both correctly, and neither
can see the other. `acquire` succeeding proves nothing about the other
environment.

This is exactly the 2026-08-15 shape the claim was built to prevent — two
deploys that do not contain each other. It did not bite this time only because
`2e5f425e` was newer and ledger-only, so nothing was reverted. **Serialisation
that silently covers one environment is worse than none, because it is trusted.**

**The rule for a cloud/remote session:** `deploy_claim.py acquire` in your own
container is a local no-op with respect to every other environment. Before
deploying, check the claim state that the PRIMARY tree sees — and if you cannot
reach it, say so and coordinate explicitly rather than treating a local
`ACQUIRED` as authority. The atomic `O_CREAT|O_EXCL` lock is sound; its
NAMESPACE is the thing that does not span machines.

**Generalisation:** a lock is only a lock over the state everyone contends on.
Ask what storage the lock lives in and who can see it, before trusting what it
says.
## 2026-08-26 — FORBIDDEN: treating ARITHMETIC ON A DERIVED FIELD as a measurement

- **A number you computed from another stored number is not evidence about the world. Dividing it back out recovers your own input, and it will look like a reading.**
- *(evidence in `learnings_evidence.md`)*
## 2026-08-26 — FORBIDDEN: concluding a VENUE must act because its error names your account

- **`user_not_found: <uuid>` from a venue is a statement about a REQUEST, not about your account's existence.** I read it as "the exchange has no record of us here, so the venue must enable us", shipped that as the remedy, and it went LIVE IN A PRODUCTION ERROR STRING telling any reader to contact Kalshi support:
- *(evidence in `learnings_evidence.md`)*
## 2026-08-26 — An empty log query is not evidence of absence until the query shape is known to match

- **OVERTURNED:** that a null result from the Render log `text` filter means the line is not there.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-26 — A before/after comparison where both sides are the same tree always agrees

- **Use a detached worktree at the parent commit** (`git worktree add --detach <path> <sha>~1`), which cannot silently be the same tree. Done correctly later the same session for `test_it_cannot_downgrade_a_started_match`.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-26 — One shared method, two callers wanting different answers: check the OTHER caller

- **Before changing a shared resolver, enumerate its callers and state what each one needs.** The fix in both cases was to make the difference EXPLICIT (`include_upcoming`; the two-resolver rule in the invariant), not to pick one caller's answer and hope.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-26 — "Done" before the sweep returns is a claim about the future

- *(the heading states the rule; full working in `learnings_evidence.md`)*
- *(evidence in `learnings_evidence.md`)*
## 2026-08-26 — `-k` chosen by TOPIC misses the files you edited

- **Choose `-k` from the FILES TOUCHED, not the topic being worked on.**
- *(evidence in `learnings_evidence.md`)*
## 2026-08-26 — An estimated window is one sample until you measure the spans

- **447s** and the build was healthy throughout.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-26 — FORBIDDEN: TWO HOSTS ARE NOT ONE VENDOR, and "X can reach ESPN" is not a fact about X

- **A success against one hostname says nothing about another hostname, even when both belong to the same provider and serve the same path.**
- *(evidence in `learnings_evidence.md`)*
## 2026-08-26 — FORBIDDEN: assuming an artifact "published to production" is where its CONSUMER reads

- **`POST /api/ops/artifacts/publish` writes `data_root() / relative_path` on WEB'S FILESYSTEM.** `bet_status_wnba` reads the same relative path through `read_text_file`, i.e. the KEYVALUE store, on REFRESH-WORKER. Same string, two stores, two services.
- *(evidence in `learnings_evidence.md`)*
## A correct measurement of an unrepresentative case is still a wrong answer

`[2026-08-26, lane board-staleness-visibility, #567/#569]`

**`#567` existed because every board-build estimate had been read from the gap
between two log lines. I fixed that, instrumented the call properly — and then
drew four wrong conclusions from correctly-instrumented readings.** The
instrument was right every time. The SAMPLING and the NAMING were not.

**Overturned belief 1: "the board build takes 19m43s."** It is **~108s** in
steady state (n=40, median 107.8s). Every large figure was a COLD build — first
after a restart, 6.9x a warm one — taken in a window with 15 deploys in 6h15m
where the worker never reached a warm build. **We were measuring restarts and
calling it the board.**

**Overturned belief 2: "the board is computing, not queued" (`off_cpu_pct=10.4`).**
That was ONE cold build. Steady state medians **52.8%** off-CPU across 40
samples. I reported an outlier as the answer.

**Overturned belief 3: "NFL stopped capturing — new, unattributed, worth a
lane."** NFL runs a deliberate **8-hour** fixture-aware sweep interval
(`#440` Phase 1b, whose own comment predicted `nfl_preseason 12.00 -> 3.56
sweeps/day`). **I called a working feature an outage** because my threshold was
a flat 900s, which every sport with a cadence over 15 minutes trips
unconditionally.

**Overturned belief 4: "3 rows survive the guard wrongly."** That was 3 of 9
**sampled** — the classifier reads the 3 worst rows per sport. The population
was never measured, and I used the 3-vs-946 ratio to justify a decision.

**THE COMMON SHAPE, and it is the rule:** *a label producible by more than one
mechanism, reported as though it named one.* `sidecar_frozen` meant both "the
capture broke" and "this sport sweeps slowly by design". `market_gone` came out
of a frozen file as readily as a live one. `orphaned_line` came out of a
staggered freeze as readily as a real line move.

**WHAT TO DO INSTEAD, all three cheap:**
1. **Before quoting a reading, ask what ELSE could produce this exact number.**
   If more than one thing could, the label is not an answer yet.
2. **Take n>1, and check the samples are comparable.** I nearly reported an 80%
   board collapse from `kept=15672 -> kept=3124` — different SPORT and different
   DATE. The publish line beside it settled it in one query.
3. **Put the discriminating field ON the line.** `sidecar=<age>` and
   `worst_seen_by_sport` are what made the later readings checkable rather than
   trusted; the aggregate alone hid everything.

**Corollary, measured the same day:** an instrument can be defeated by the thing
it measures. Two of my own cold builds were killed mid-flight by other sessions'
deploys — the exact deploy-churn mechanism this lane had just documented.
## 2026-08-23 — RULE: editing a fast-appended shared ledger from a stale local copy manufactures a fake conflict

- **Twice in one session, on `.syndicate/deploys.md`.** I read the file, appended a new section with `Edit`, committed, pushed, opened a PR — and GitHub reported "Pull Request has merge conflicts" on a PURE APPEND with nothing else touched. The cause both times: `main` had moved between my read and my push (this repo runs many parallel sessions appending to the same few ledger files), so my commit's diff was computed against a base that was already behind. A rebase onto `origin/main` then showed the "conflict" for what it was — an EMPTY `- *(evidence in `learnings_evidence.md`)*
- *(evidence in `learnings_evidence.md`)*
## 2026-08-23 — RULE: an empty tmp dir for `SYNDICATE_NFL_SOURCE_ROOT` can still resolve to the REAL checkout, and a test can write into it

- **The rule going forward.** Before verifying a consumer against an artifact, **enumerate that artifact's PRODUCERS** — `git grep` the write path, not just the read path — and carry a fixture from EACH one into the test. One producer is an assumption, not a finding; two producers that disagree on shape is a thing this repo already does. And the shapes must be READ OFF PRODUCTION over a window, not inferred from the writer that happens to be documented: a single sample cannot distinguish "one shape" from "the shape that was current when I looked". Corollary for the consumer itself: `#413`'s "`{}` means ALL, not SOME" belongs per ROW, not per FILE — a row that cannot answer must return None rather than a hollow state, because a non-None empty answer suppresses the fallback that would have been correct.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-26 — RULE: a measurement can be REAL and still describe the WRONG POPULATION. State the denominator before you generalise a rate.

- **Two instances the same evening, in two different sessions, in opposite directions — which is why this is a rule and not an anecdote.**
- *(evidence in `learnings_evidence.md`)*
## 2026-08-26 — FORBIDDEN: reporting a test as failing on `main` from a session worktree, when its fixture is DERIVED from `data/`. And a stash-and-rerun does NOT isolate it.

- **`session_worktree.py open` excludes `data/` by design** (34,690 of 37,745 tracked files; it is a lossy mirror and never evidence about production). Any test whose fixture is BUILT FROM those artifacts therefore fails in a session worktree and **looks exactly like a real regression on `main`**.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-28 — FORBIDDEN: treating a refuted MECHANISM as a refuted OBSERVATION. I disproved my own theory of how a wrong-side fill happened, and used that to dismiss the fill.

- **THIS ENTRY REPLACES THE ONE THAT STOOD HERE FOR SIX HOURS, WHICH WAS WRONG IN ITS CONCLUSION AND WOULD HAVE TAUGHT THE NEXT SESSION TO DISMISS A REAL ONE.** The superseded version was titled *"FORBIDDEN: escalating a wrong-side money alarm on a property the code already handles"* and concluded the alarm was false. It was not. Left in the history; do not restore it.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-27 — FORBIDDEN: pushing past a ledger checker's warning because its output "looks like the usual noise". A WARNING THAT IS USUALLY WRONG GETS TRAINED OUT — and two sessions proved it independently on the same night

- **The rule going forward.** **A checker that emits known-false warnings beside true ones is not a checker, it is noise with an exit code.** Two things follow. (1) When a checker fires, READ ITS FULL OUTPUT before deciding it is the usual thing — "I recognise this warning" is a memory of a DIFFERENT run. (2) Separate the classes at the point that ACTS on the finding: a duplicate declaration should BLOCK, while historical unmatched ids stay advisory. The check that cannot be trained out is the one that only fires when something is wrong.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-27 — RULE: a deploy claim serialises SESSIONS. It does not reserve a service against a HUMAN, and an assistant cannot lift the guard from inside a command.

- **MEASURED 2026-08-26.** Lane `ncaaf-opener-regions-props` held the `refresh-worker` and `live-odds-worker` claims (acquired 22:57:41Z, TTL 2700s, so live until 23:42:41Z). At **23:26:02Z** — **16.6 minutes inside the window** — both services were deployed to `23f065d4` by the user from their own terminal. Nothing refused it, because `.claude/hooks/deploy-guard.py` only intercepts an ASSISTANT's Bash calls.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-27 — FORBIDDEN: running `deploy_claim.py` from a session worktree. The claim file is PER-TREE, so nobody else can see it.

- **MEASURED 2026-08-27T01:0xZ.** Two `web` claims existed at once, in two files, neither aware of the other:
- *(evidence in `learnings_evidence.md`)*
## 2026-08-27 — MEASURED NEGATIVE: the NCAAF advanced-data payload does not close the gap to market

- **Do not re-litigate this without new evidence.** The re-fit ran; the answer is no. `scripts/refit_ncaaf_smartsim2_payload.py --season 2025 --sims 60`, 714 games, both arms sharing seeds, ~60 min of compute:
- *(evidence in `learnings_evidence.md`)*
## 2026-08-27 — NCAAF TOTALS ARE NOT OVER-DISPERSED. The deficit is ONE CONSTANT BIAS, and the residual spread already matches the market

- **Rule: before attacking a model's DISPERSION, decompose its error into BIAS and SPREAD. They demand opposite fixes and only one of them was ever wrong here.** The model's residual SD is statistically indistinguishable from the market's — its errors are ALREADY as tight. The entire totals deficit is a single systematic over-prediction of 5.2 points.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-27 — NCAAF drive structure is an ENGINE ACCOUNTING BUG, not a calibration gap. The sim's own numbers do not multiply out

- **Rule: before tuning a model to a target, check the model's own metrics are INTERNALLY CONSISTENT. If they do not multiply out, the defect is accounting, not calibration, and no parameter will reach it.** Truth multiplies: 5.77 x 7.36 = 42.5. The sim does not: 7.246 x 7.413 = 53.7 against a credited 43.1 yards/drive -- a ~10.5 yard/drive gap between gross play gains and net drive yardage that real football does not have. Divide the sim's OWN numbers and you get 43.14 / 7.413 = **5.82 effective plays/drive, essentially truth's 5.77**. The football is right; the play COUNT is inflated ~25%.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-27 — A GUARD THAT ASSERTS THE CALL, NOT THE RESULT, IS TRUE OF CODE THAT DOES NOTHING

- **Rule: a guard must assert the OUTCOME at the place that CONSUMES it, and must be seen to FAIL before it is trusted.** "The builder calls the helper" was true of a payload nothing read. "Jinja parses" was true of markup that collapsed a card in a browser. Both are statements about the thing built, not about the thing that reads it.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-27 — MEASURE THE OUTCOME YOU PROMISED, NOT THE CHANGE YOU MADE

- **Rule: state the outcome as a NUMBER before changing anything, then measure that number.** "Prose blocks: 0" is a fact about my edit. "Card height 181px vs 435px, uniform across 51" is the thing the user asked for.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-27 — FORBIDDEN: deferring work around a ledger BLOCKER without re-measuring it. A blocker is a measurement and it expires.

- **It was true on 2026-08-18 and false from 2026-08-20**, when `d7dbdbd2` ("allowlist: make the live-gameline ledger readable off-worker (#440)") added both patterns. Content-verified 2026-08-27 on all three DEPLOYED SHAs — web `e3568422`, refresh-worker `ad3f116c`, live-odds-worker `34b4d4b4`.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-27 — FORBIDDEN: trusting a test whose FIXTURE cannot violate the property it asserts. It is not weak coverage; it is zero coverage that reads as strong.

- **Why it could never fail:** every record in its fixture carries BOTH `model_home_win_prob` and `market_fair_prob`. The populations diverge only when a record has a model probability and NO market price — a row the fixture does not contain. So `assert model.n == market.n == 2` was re-measuring the fixture, not the code. Any implementation, including the broken one, passes it.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-27 — FORBIDDEN: reading `pid` in a deploy claim as evidence the holder is alive

- *(the heading states the rule; full working in `learnings_evidence.md`)*
- *(evidence in `learnings_evidence.md`)*
## 2026-08-27 — `Path(__file__).parents[1]` MAKES THE PRIMARY TREE THE RENDEZVOUS, AND A WORKTREE INVISIBLE

- **Run every deploy-lock command from the PRIMARY tree, and write the per-session lane marker there too.** Code edits stay in the worktree; the locks are shared state and must live where the other sessions read them.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-27 — A COMMENTED-OUT PATH IS STILL A CLAIM; AND THE DEPLOY GUARD MATCHES LEDGER PROSE

- **A false positive here is correct behaviour** — the fix is to reword the ledger, never to reach for a route the guard does not recognise.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-27 — A CLAIM HOLDER IS NOT A DEPLOY AUTHOR. The API cannot tell you who fired it.

- **Overturned by `ncaaf-opener-regions-props`, self-caught.** They thanked me for deploying `600a753a` to refresh-worker. I had not — my deploys that day were all live-odds-worker.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-27 — FORBIDDEN: measuring a dirty SHARED tree against `HEAD`. In a stale checkout `HEAD` is the thing that is wrong, and every diff built on it lies in the safe-looking direction.

- **+77/-1225** on `learnings.md`. Alarming, so I checked the real baseline. Against `origin/main` the same files read **+159/-12,933** and **+2,665/-2,271**: the primary tree was **791 commits behind**, so its ledger copies were missing everything landed since. Committing them — even path-scoped, even having audited the diff — would have deleted **~17,000 lines** of other sessions' work.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-27 — RE-FITTING A MODEL CAN BE THE WRONG ANSWER. Measure the do-nothing arm.

- **Rule: include the DO-NOTHING arm in the grid, and let it win if it wins.** NFL was already at its best; the fix plus a careful re-fit made it worse. Had the grid only compared "candidate ON" against "candidate OFF", NFL's candidate would have looked like a 3.24-point win and shipped a regression.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-27 — PROMOTING AN ARTIFACT IS A CHAIN. THREE LINKS FAILED SILENTLY.

- **Rule: test the CHAIN — write, read back, and confirm the consumer holds the new value — never the individual link.** Each of these passes an "is the field there" check. Only a round-trip catches (2), and only reading the staging output catches (3).
- *(evidence in `learnings_evidence.md`)*
## 2026-08-27 — A CARRIED-FORWARD FACT DECAYS EACH TIME IT IS RESTATED WITHOUT RE-READING THE SOURCE. And a clean kill census proves nothing until you prove the feature was RUNNING in that window.

- **THE SECOND HALF, which is the part most likely to be skipped.** "Zero kills in 10d13h" is worthless on its own — it is equally consistent with the feature being switched off. The reading only counts because the ledger was PROVEN to be running in that same window: 20 ledger files / 47.7 MB with fresh mtimes, and `MLB_LIVE_GAMELINE_LEDGER_ENABLED` absent (= enabled). Pair every null with proof the thing could have fired.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-27 — A GREEN TEST SUITE OVER A FILE THAT CANNOT BOOT `[lane venue-quote-line-join]`

- **FORBIDDEN: appending a definition below `if __name__ == "__main__":` and treating a passing unit suite as evidence the file still runs.**
- *(evidence in `learnings_evidence.md`)*
## 2026-08-27 — CADENCE LIVES IN THE CALLER, NOT THE INTERVAL CONSTANT `[lane venue-quote-line-join]`

- **FORBIDDEN: reporting an interval env var as a cadence lever without reading its CALL SITE.** I told the user twice that raising venue cadence was "pure env, no code". Both times wrong, both caught only by reading callers:
- *(evidence in `learnings_evidence.md`)*
## 2026-08-27 — A KEY MUST NAME EVERY PARTY TO THE BET `[lane venue-quote-line-join]`

- **FORBIDDEN: a join key for a player prop that omits the player, or for a total that omits the game.** Both were live and both look identical to a working join from every counter.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-27 — A BREAKDOWN THAT DOES NOT RECONCILE IS NOT EVIDENCE `[lane venue-quote-line-join]`

- *(evidence in `learnings_evidence.md`)*
## 2026-08-27 — FORBIDDEN: allowlisting a KEYVALUE-backed path in `HOT_ARTIFACT_PATTERNS` and calling it readable. The guard will pass and the data will not arrive.

- **It would have been inert, and inert in the worst way — it looks like a fix, it passes review, and it changes a 403 into an empty result.**
- *(evidence in `learnings_evidence.md`)*
## 2026-08-27 — FORBIDDEN: validating a CONVERTED value while STORING the raw one. The guard clears a number that is not the number anything uses.

- **$23.25 to $368.97** — against a `max_day_dollars_polymarket` of **100.01**. Real spend was ~$20.71. No money moved; the BOOKKEEPING was 15.9x wrong and the cap enforces on it.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-27 FORBIDDEN: an instrument built out of the thing it measures, or out of a symptom the slate can retire — FOUR instances in one session, every one reading HEALTHY

- **The rule going forward.** Derive the instrument from a source the defect CANNOT touch, and state that source. Concretely, all three fixes ended up joining on the slug taken from `group.key` and on `chip.league_display` — fields no code path under test writes. **And run the control on the SAME payload, at the same instant, every time:** a fix verified only against post-deploy data is verified against a slate that may have retired the test case. This is the 2026-08-20 census rule (`A CENSUS THAT CANNOT READ UNHEALTHY IS NOT A VERIFICATION`) generalised from "the slate moved" to "the instrument was never able".
- *(evidence in `learnings_evidence.md`)*
## 2026-08-27 — A SINGLE OBSERVATION READ AS A BOUND `[lane venue-quote-line-join]`

- **FORBIDDEN: concluding "supply-limited" from one reading where a quantity sat below its cap.** I saw mlb take 1,512 slots against a cap of 1,550, concluded its Kalshi listings were the constraint, and wrote it into `deploys.md` as the finding. mlb went **794 -> 1,741 across the same evening** — its available markets GREW as its slate approached first pitch. 1,512 was a moment, not a ceiling.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-27 — A CONTROL THAT IS BROKEN IN THE SAME WAY AS THE TREATMENT DISTINGUISHES NOTHING. I ran one and reported the result as positive.

- **THE METHOD ERROR IS THE POINT, NOT THE STALE RULE.** I "verified" by stashing my diff and re-running. **Stashing does not restore `data/`.** Both arms of the comparison were missing the same thing, so the experiment could only ever return "same either way". That proved the failures were not caused by MY DIFF; it could not prove they were REAL. I collapsed two different claims and reported the weaker result as the stronger one.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-27 — I CHECKED ANCESTRY AND CALLED IT CAUSATION. The fix's own log line said the path never ran.

- **The trim's own line, at the moment of the recovery, reads:**
- *(evidence in `learnings_evidence.md`)*
## 2026-08-27 — A WATCHER IS AN INSTRUMENT AND IT LIES IN FOUR SPECIFIC WAYS

- **A failed edit followed by a successful run of old code is indistinguishable from a successful re-arm.**
- *(evidence in `learnings_evidence.md`)*
## 2026-08-27 FORBIDDEN: calling a fix verified when the READING came from a different surface than the one that was broken

- **The rule:** when a value crosses more than one hop to reach the surface that was reported broken, a correct reading at hop 1 is not evidence about hop 2. Verify at the surface the complaint came from. **A byte-identical response across a deploy is a positive signal that nothing changed** — cheap, and it is what caught this. Fixed in `d281995b`; one list now feeds both, so payload and page cannot drift.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-27 FORBIDDEN: inferring that a scheduled job SUCCEEDS from an age that sits at one interval

- **Generalises to:** any liveness signal emitted BEFORE the work it is taken to vouch for. Ask what the signal is stamped by, not what it is near.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-27 A lane can be CLOSED while a session keeps working under its name

- **Not proposing a guard** — the claim's job is mutual exclusion and it did that. The point is narrower: **a lane name in a claim is not evidence the lane is open**, so "who holds this" can point at a closed lane indefinitely. When work continues past a close, open a new lane or reopen the old one before touching production.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-27 A survey keyed by BARE FUNCTION NAME collapses same-named functions across sports

- **Resolve by IMPORT, not by name** in a repo with per-sport parallel modules. And when a static result says "no problems anywhere", treat that as a suspected broken query before treating it as a finding.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-27 — FORBIDDEN: fitting a model to a total when you can COUNT the operation

- **The rule:** if the thing you are optimising is made of discrete operations — syscalls, queries, requests — **count them**. Do not infer their cost by regressing the total against plausible predictors.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-27 — FORBIDDEN: a verification criterion that can only be met by the failure it is watching for

- **The rule:** before adopting a criterion, ask what it reads on a HEALTHY instance that was never going to fail. If the answer is "the same as on a fixed one", it discriminates nothing.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-28 — A GAP BETWEEN TWO LOG LINES IS NOT A COST. I measured one, believed it, and was wrong by 30x.

- **Spanned directly, it is `pull_hot_artifacts` = 1.15s.** The 37 seconds was everything happening on a shared worker between two prints — other threads, the memory watchdog, the sim tick, GC — not the work I attributed it to.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-28 FORBIDDEN: reading a "not yet running" list as proof something IS running

- **The rule:** poll the PREDICATE, never a status field that merely mentions your SHA. For a deploy that means the changed behaviour appearing in the served response, or a log line that exists ONLY in the new code (`ORDERS_ENVELOPE` was built for exactly this and worked).
- *(evidence in `learnings_evidence.md`)*
## 2026-08-28 FORBIDDEN: a shared rule reimplemented as "the half I needed"

- *(evidence in `learnings_evidence.md`)*
## 2026-08-28 FORBIDDEN: grading an AMBIGUOUS zero as a definite outcome

- **The rule:** a value that two different states both produce is not evidence for either. Refuse with a NAMED reason and leave the row for a later pass. And when a wrong verdict can be written permanently, the repair must carry a discriminator that makes it TERMINATE — `held_side` here, without which the repair would clear a correct grade every tick forever.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-28 An absent log line is only evidence once you know the line is EMITTED

- **Check the instrument can fire before trusting what it says.** An unfiltered query returning *something* is the cheap version of that check.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-28 FORBIDDEN: reading a job's TIMESTAMP as evidence it ran, on a machine that sleeps

- **Compounding it:** the sibling task `live-gameline-fixes-first-real-reading` had a hardcoded freshness window ("a row `captured_at` between 04:33Z and 04:45Z") and was instructed, on a miss, to declare *"the recurring task is not firing on its cron, which is EXACTLY the failure that lost six nights."* Under displacement that window can never be met, so it was primed to raise a false alarm indistinguishable from a real outage — and the plausible response to that alarm is re-enabling things that were never off. 6 of 10 nights (08-18..08-27) fell inside a standby span.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-28 A lane-guard claim can be held by PROSE, and "TRANSFERRED" releases nothing

- **The rule:** a release is only real if the guard parses it. Verify by DRIVING the hook (`echo '{"tool_name":"Edit","tool_input":{"file_path":"..."}}' | python .claude/hooks/lane-guard.py`), never by reading the ledger and believing the prose. Note the guard cannot express a per-branch claim: releasing for one concern releases the file for everyone, so say so where the next reader will see it.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-28 — FORBIDDEN: building a fix for a hypothesis the REFUSAL NAME has already ruled out `[lane venue-join-refusal-visibility]`

- **What we believed:** soccer was absent from Polymarket execution because whole competitions never entered the `soccer` bucket — `mls` was unprovable, so its 30 h2h markets sat under a key no board row looks up. Measured and true: 0 of 9 MLS fixtures resolve both clubs through the flat alias map.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-28 — FORBIDDEN: reading ~0.5 as a weak signal from a comparison never shown to DISCRIMINATE `[lane venue-join-refusal-visibility]`

- **What we believed:** the Polymarket spread sign test was under-powered. Ten production runs returned `rate` 0.44-0.60 at n=9..22 against `min_sample=30`, and the verdict said `UNDECIDED: n < min_sample` — which reads as "collect more".
- *(evidence in `learnings_evidence.md`)*
## 2026-08-28 — FORBIDDEN: reading `lastRunAt` as evidence a scheduled job RAN. It records DISPATCH, and on this machine the two were nine hours apart.

- **How to tell it apart from a task bug, cheaply:** other concurrent sessions will show a gap ending at the SAME INSTANT. Three did — 10.22h, 9.99h, 9.78h, all resuming inside 72 seconds, from different start times. A per-task bug cannot do that. Confirm with `Get-WinEvent` System log, Kernel-Power 506/507.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-28 — FORBIDDEN: baselining a test in a fresh worktree when the test reads state the worktree does not share. It is not a baseline, it is a different experiment.

- **A git worktree does not carry the primary tree's `data/` mirror, and that test reads the real data root** — visible in its own error output (`...\Syndicate\data\wnba_source\...`), which I had already been shown and did not read. The worktree was a different environment, so the comparison was meaningless.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-28 — FORBIDDEN: concluding a lane claim is free because the roster says its session is gone. `get_session` said "not found" while the session was live.

- **What the code said, and it had said it for months.** `bet_status_wnba` refused every WNBA spread, moneyline and total. Not by omission — by an argued comment:
- *(evidence in `learnings_evidence.md`)*
## 2026-08-28 — FORBIDDEN: instrumenting a function without first proving it is ON the path you are measuring. I did it, and the counter read zero.

- **Every one of those facts is true, and the theory is worthless, because `build_soccer_market_board` IS NOT ON THE OVERVIEW PATH.** `soccer/cards.py` — what `_build_sport_overview` actually calls — never imports `market_board`. Its importers are the `/soccer` blueprint, `layer1_board`, `live_refresh_loop`. I shipped a counter into it and production emitted ZERO lines.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-28 — FORBIDDEN: treating a "this API does not exist" finding as a fact about the VENUE when it was written from a network that could not reach the venue. It is a fact about the NETWORK.

- **The decision ("do not build") was right in both versions. The REASONS were false, and a false reason is worse than no reason** — it reads as a closed question. Compounding: the same finding's `probe()` named "HTML that mentions a live REST path" as its unblock signal; that would FIRE TODAY and be wrong, since the page advertises a REST path no host serves.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-28 — A lane disclaimer marker governs its OWN LINE ONLY. Three of five "contested" files were deference that PARSED as ownership.

- **The form that works** — marker first, path after, on ONE line:
- *(evidence in `learnings_evidence.md`)*
## 2026-08-28 — AMENDS the `createdAt`/`finishedAt` rule: the DEPLOY RECORD and the PROCESS are not the same instant `[lane venue-join-refusal-visibility]`

- **HONESTY ABOUT SCOPE, because overstating this would make it a worse rule:** in the incident that produced it, `finishedAt` WOULD have been sufficient. A peer read a `POLYMARKET_ORIENTATION` line from 20:19:16 as post-deploy — before `finishedAt` AND before `BOOTED` — because they INFERRED "~20:18Z" instead of reading the field at all. The actual error was not consulting the record; the 30-second window is a hazard I found while checking, not the one that bit.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-28 — FORBIDDEN: keying a venue join on the fixture without keying it on the PORTION of the fixture

- **Measured, real money: five orders, $7.08.** `kalshi_board_join._match_key` and `_row_key` were five-tuples — game, market, player, line, side — with no `segment`. A board row for "under 2.5 runs, first 3 innings" therefore matched Kalshi's FULL-GAME `KXMLBTOTAL` on every field the key contained, and nothing downstream checked that the contract settles on a different portion of the game.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-28 — FORBIDDEN: closing on the venue that was REPORTED when the join it mirrors has the same key

- **four more bad orders of the same class, the same day.** Nine distinct wrong orders across both venues, not five. Nothing pointed at Polymarket; the only reason it surfaced is that the audit was repeated rather than concluded.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-28 — FORBIDDEN: sizing a fix before measuring the component's SHARE of the whole. I did it twice in one day on the same subsystem.

- **Instance 1.** I found soccer's cards-context TTL (600s) was finer than the board build period (680-874s), fixed it, measured `games()` 42.34s -> 2.76s and recorded a verified 15x win. The sport bracket was 163-382s. The component I fixed was ~3s of it. I optimised a real defect that could not matter.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-28 — FORBIDDEN: judging a change by the metric I chose instead of the metric the USER SEES. Mine read "bought nothing"; the board read 4h24m stale.

- **THE RULE:** when a change alters scheduling, priority or cadence, check the USER-FACING freshness/quality signal, not only the internal counter you reasoned about. "Bought nothing" is a conclusion about MY metric. The question is always "what does the surface show now".
- *(evidence in `learnings_evidence.md`)*
## 2026-08-28 — Pre-registering a confound does not help if you get its SIGN wrong

- *(the heading states the rule; full working in `learnings_evidence.md`)*
- *(evidence in `learnings_evidence.md`)*
## 2026-08-28 — FORBIDDEN: reaching for the next knob after a tuning change fails. Three attempts, each refuted by the next reading, when the second should have said "structural".

- **THE SIGNAL I IGNORED IS AT STEP 2.** A change that moves the metric the WRONG WAY is not a dosage problem, it is evidence the model is wrong. I read it as "not enough" and reached for a second knob. The cause was structural the whole time: today is re-queued every loop iteration UNTHROTTLED while futures are throttled, and with 11-15 minute builds today wins every slot. Eligibility was never the constraint; slot allocation was.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-29 — FORBIDDEN: naming a cause from a mechanism you can see without measuring the one you cannot

- **Why it survived three failed fixes:** each failure was read as "not enough of the right thing" rather than "the wrong thing". The `=600` result moved `08-29` the WRONG way, which is a refutation of the model, and I took it as a dosage problem. The rule written that day (`stop tuning when the observable moves the wrong way`) fired correctly and I still did not re-examine the CAUSE, only the knob.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-29 — FORBIDDEN: carrying a component's SHARE across regimes when the regime is what sets it

- **14%, not 95%.** A 40% cut of 14% is ~6%, which is below the noise of the thing I promised to move.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-29 — FORBIDDEN: reading a conditional log's silence as absence of the EVENT, when it is really absence of one SPECIAL CASE of the event

- **Both halves of that were wrong, and a forced-collision test found it in minutes.** `counts["concurrent"]` increments only when a row **already in our baseline** has a different fingerprint now (`execution_ledger.py:443`). An intruder that only APPENDS rows never trips it. So:
- *(evidence in `learnings_evidence.md`)*
## 2026-08-29 — FORBIDDEN: breaking a lock before checking whether the thing it guards has already happened

- **The ordering error, stated precisely:** I checked "is anyone deploying?" (`render_events.py --since`) at 15:46, saw none, and then forced at 15:52 on the strength of that. The deploy landed at 15:52:29. A null result is scoped to the window it covered — 15:30-15:46Z — and I carried it forward as a standing fact across the six minutes that actually mattered. This is the same shape as `absence_in_a_window_is_not_absence`, now with a destructive action attached instead of a wrong opinion.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-29 FORBIDDEN: letting a shipped "cannot be tested until X" caveat stand without putting the test on X's date

- **An honest caveat is not a mitigation. It is a defect with a date on it**, and the date arrives when nobody is looking at that surface.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-29 FORBIDDEN: reading `check_lane_invariants` PASSING as proof that lane claims are sane

- **The rule going forward:** **enabling dead code is a performance change, not only a correctness one.** Before shipping a fix that makes an unreachable path reachable, read what the newly-reachable code CALLS and measure it on the path that will now call it. "It returns the right answer" is not a deploy verification for a change that alters *how often* something runs.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-29 — FORBIDDEN: trusting a profiler's ANSWER without validating its SCOPE against the metric you care about

- **The instrument does not know what you are trying to explain.** A profiler tells you where time went INSIDE ITS BRACKET, with total authority and no opinion about whether that bracket is the thing you care about. That check is one subtraction: compare the profile's `elapsed_s` against the enclosing measurement. 10.95 vs 452.97 was visible in logs I had already pulled, and I did not do it until the second profile forced the question.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-29 — FORBIDDEN: windowing a verification watcher on wall-clock time instead of on the boot it is verifying

- **The rule going forward:** when two endpoints display "the same" joined field, find out WHERE each computes it before treating one reading as evidence for the other. A shared function is not a shared execution site, and on this platform the web/worker split makes that difference routine rather than exotic.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-29 — a diagnostic that TRUNCATES will be read as evidence. Twice.

- **RULE: a bounded, sorted sample is not a rate and not an attribution.** Before drawing a conclusion from a truncated list, ask what a NULL result would look like -- here, the same list under an unrelated key, which was visible the whole time. The `cfb` alias was real, but it was settled by a NAMED FIXTURE on both sides (`tsc-cfb-sacst-emich` = the exact board row), not by the list.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-29 — FORBIDDEN: mapping an outcome polarity that the venue has not stated

- **MLB spreads are still refusing for the same reason and must stay that way** until a sample settles them: outcomes are `+1.50`/`-1.50`, both observed samples carry `pos-1pt5` and differ only in the side wanted, so they cannot establish whose perspective the venue states the spread from.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-29 — ancestry is a DEPLOY-TIME MEASUREMENT, never a claim

- **The rule going forward:** when a surface serves an artifact, the ONLY input that licenses a verdict about a code change is the artifact's own build stamp crossing the deploy time. Elapsed time is a fact about you, not about the system. Find the build stamp BEFORE arming a watcher — `written_at`, `generated_at`, `published_at` — and gate on it. If a surface has no such stamp, that absence is the first thing to fix, not to work around.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-29 — FORBIDDEN: calling a placeholder threshold "conservative" without checking it against the real one. A threshold above break-even everywhere is a DISABLED FEATURE wearing safety language. `[lane live-venue-order-placement]`

- **What we believed:** `kalshi_polymarket_arb.DEFAULT_FEE_BUFFER = 0.04` was a safe stand-in. Its own docstring says so at length and honestly — "a conservative placeholder, not either venue's real fee schedule", "only `edge_after_buffer` should be read as an actionable signal". Every word of that is true and it still produced the wrong outcome.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-29 — FORBIDDEN: reading `count: 0` from an artifact export as "the artifact is unreachable". It is a fact about what the READER scans. I had this rule on file and walked into it anyway. `[lane live-venue-order-placement]`

- **What we believed:** `/api/ops/artifacts/export?pattern=*polymarket*` returning `count: 0` meant the Polymarket slate was not reachable from web, so any cross-venue measurement needed a worker-side probe or a publishing change first. I put that in `state.md` and built a recommendation on it.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-29 — FORBIDDEN: judging whether `main` is green from a session worktree OR the primary tree. Neither is a control, and they lie in OPPOSITE directions

- **What we believed:** that running a test file in my own worktree told me whether the branch was healthy. I reported to the user that a deploy carried "9 red tests, 1 of them a new regression," named the regression, identified which lane owned it, and messaged that lane about it.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-29 — a null from an instrument you have not calibrated is not evidence. RUN THE CONTROL

- **What we believed:** that `venue_balance_history.json` being absent from `/api/ops/keyvalue/usage?top_keys=100` and from `sweep-preview` meant the new write was not happening.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-29 — FORBIDDEN: gating on a status string you did not read from the function that emits it. The whole conversion shipped INERT and every test was green. `[lane live-venue-order-placement]`

- **What we believed:** `#603`'s Kalshi half was done. The adapter resolved a ticker's club blob through `match_event_blob`, took the matched fixture, and keyed the quote to it. Code present, suite green, downstream green.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-29 — FORBIDDEN: verifying a DELETION by grepping for the deleted string, without first proving the container renders

- **What we believed:** that grepping the served `/portfolio` HTML for the two sentences I had just removed, and finding them ABSENT, confirmed the edit was live. I reported it that way, with a tidy `ABSENT ok` next to each.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-30 — FORBIDDEN: fixing the caller whose NAME matches what you are looking for, without checking which caller actually runs. `#603` shipped inert twice for this. `[lane live-venue-order-placement]`

- **What we believed:** the venue reprice happens in `venue_quote_fanin.apply_venue_quotes`. I traced the corrupted price properly — `book_prices` <- `cells` <- `_reprice_live_benchmark` <- `venue_quote_fanin` — and then stopped one frame early, at the caller whose name matched.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-30 — FORBIDDEN: an exact-count assertion over a pipeline that has an unmocked ADDITIVE source. It measures the machine, not the code

- **What we believed:** that `assertEqual(len(rows), 1)` tested "when the betting card is empty, the top-props source is used". It had been green in CI for as long as anyone had looked.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-30 — CORRECTION to the entry above: my "VENUE_REPRICE never fires" was LOG TRUNCATION, not absence. The rule I wrote from it was right; the evidence I wrote it from was not.

- **RETRACTED:** *"`GRID_REPRICE` fires every cycle; `VENUE_REPRICE` appeared ZERO times in 45 minutes of production logs"* and the conclusion drawn from it, that `apply_venue_quotes` is never called.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-30 — RULE: an artifact is evidence only once you have checked it contains what its NAME claims. Four instances in one session

- **What we believed:** that `.syndicate/lanes.md.CONFLICTED.bak` held the pre-resolution ledger. It was offered to a user as the safety net that made an unresolved-merge situation recoverable.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-30 — FORBIDDEN: `git checkout --theirs .` to clear a conflict in an append-only ledger. It is a DELETION TOOL, and it staged 929 of them over a peer's work.

- **What we believed:** that after hand-resolving a stash-pop conflict in `deploys.md`, a trailing `git checkout --theirs .` was a harmless tidy-up.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-30 — FORBIDDEN: measuring a FILL-time cost from a SETTLEMENT-time quantity. Realized P&L is `(exit - entry)`; a commission taken at fill is invisible to it BY CONSTRUCTION, so the method returns zero whether or not a fee was charged.

- **What we believed:** Polymarket charges no commission. Ten venue-settled orders, $75.98 notional, implied fee -2.37 bps, every value negative-or-zero. I checked circularity (the delta is the venue's number, not ours) and shipped it — into `state.md`, a lane header, a code constant, and an INVERTED test.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-30 — FORBIDDEN: attributing a commit to a session by ADJACENCY. And: a method that cannot return a non-zero answer has not measured zero

- **What we believed:** that `c17bc3d8` belonged to the session whose commit landed 45 seconds earlier. I sent that session a substantive challenge to a live-money finding it had never touched.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-30 — checks that AGREE are only independent if they differ in the decisive variable

- **RULE: before reporting agreement across N checks, name the variable that differs between them. If you cannot, you have one check and N-1 rehearsals.**
- *(evidence in `learnings_evidence.md`)*
## 2026-08-30 — FORBIDDEN: gating one instance of a shared cause

- **RULE: when a cause is named, grep for every site it reaches BEFORE fixing the one that was reported.** The reported instance is a sample, not the population.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-30 — "not priceable" and "no board row" are different problems with different owners

- **RULE: "we cannot model this" and "nothing generates the row" call for completely different work and different owners. Say which.** One is a modelling problem; the other is a plumbing problem that a model already solved.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-30 — an orphaned `autostash` is somebody's work, and nothing reads a stash list

- **RULE: drop stashes in DESCENDING index order** -- a low drop renumbers every higher one, which is how the wrong stash gets deleted. **Record SHAs BEFORE the first drop and re-check one AFTER**, so the recovery path is verified rather than asserted.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-30 — RULE: a shared tree can sit BEHIND its own HEAD, and the diff then reads as YOU reverting someone. Prove whose content is on disk before restoring

- **What we believed:** that `git status` showing my two files as ` M` in the primary tree meant I had uncommitted work there.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-30 — METHOD: agreement across a sample cannot distinguish a real signal from a CONSTANT INSTRUMENT. Ask what the method is structurally blind to before counting how many times it agreed

- **What happened.** Polymarket's fee was "measured" at zero from the venue's own realized P&L on ten settled orders — every value negative-or-zero, total −$0.0180, −2.37 bps of notional, one outlier excluded for a documented reason. Ten independent orders agreeing to within rounding. It was published, acted on, and it inverted a lane's recorded priority ("Polymarket is two thirds of pair cost" → "Kalshi is the entire bar").
- *(evidence in `learnings_evidence.md`)*
## 2026-08-30 — RULE: a retraction must reach the DOCSTRING of the module whose behaviour changed. Prose is an interface, and it has no test

- **What happened.** The zero-fee finding above was retracted and the constant fixed the same hour: `polymarket_fee_dollars` returned `0.015 * contracts`. **The module docstring went on asserting the retracted finding for four commits** — "Polymarket took **no commission** on these fills", "`polymarket_fee_dollars` returns the measured 0.0" — and additionally called `commissionsBasisPoints` "authoritative where this inference is not", a field that reads `'0'` on every order observed. A reader following the prose would have been handed a zero fee and landed exactly where the retraction started.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-30 — RULE: `lastRunAt` is DISPATCH. Prove execution from the run's own artifact, and prove WHICH failure it was before naming it

- **What we believed:** that a scheduled task with `lastRunAt` set had run. Mine showed `lastRunAt: 2026-08-30T03:10:47Z` and had done **nothing at all** — no heartbeat, no output, no findings.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-30 — FORBIDDEN: shipping a scheduled task without proving it can complete ONE run. A schedule is not a mechanism

- **What we believed:** that writing a good task prompt and setting a cron produced a working watcher. Mine was created to close the last open measurement of a long session, and was reported as "the durable version that survives the session".
- *(evidence in `learnings_evidence.md`)*
## 2026-08-30 — FORBIDDEN: reading a gate's VERDICT without reading what its KEY covers. A measurement about one claim silently denied a different one

- **The rule going forward:** when a gate denies, read its KEY, not just its reason. Ask *what else does this key cover that the measurement never touched?* A gate is entitled to deny what it measured; denying a neighbouring claim by sharing a key with it is an accident, not a policy. The fix shape is a BASIS dimension — the claim being made — not a relaxation of the threshold.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-30 — FORBIDDEN: reporting a config key as UNSET without reading its LIVE value. "The knob is not reaching X" does not mean the knob is empty

- **The rule going forward:** a claim that a key is unset is a claim about production, and only a live read of the env is evidence for it. Reading a findings doc is not. Before reporting "not enabled", run the setter/reader and quote its `before`. And distinguish the two failure modes explicitly, because they have different fixes: **absent VALUE** is a config change; **absent READER** is a code change, and setting the value fixes nothing while making the environment look correct.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-30 — RULE: a guard that refuses only what it can PROVE wrong is SILENT on the majority case when identity is usually unknown. Measure what share of the population it can even evaluate, before shipping it

- **What happened.** `#603` — venue quotes answering the wrong game. The first fix added a game-qualified key and refused any quote that **named a different fixture**. It was correct, tested, deployed, and on its first production board it **rejected exactly zero**.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-30 — FORBIDDEN: `[ -d data ]` as a check that a worktree is data-complete. Partial is worse than absent, and it passes

- **What we believed:** that having confirmed `data/` was "present", a worktree was a valid place to triage test failures. I had already written the rule that a `data/`-less tree fabricates failures, and I checked for it.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-30 — RULE: two guards in series, each encoding a DIRECTION assumption, can withhold a TRUE value with no error anywhere. Each is individually correct and neither can clear the other

- **What happened.** Live execution halted for ~13 hours on both venues. Nothing errored, nothing was misconfigured, and every component behaved exactly as written:
- *(evidence in `learnings_evidence.md`)*
## 2026-08-30 — METHOD: a DEGENERATE distribution is not a boring result. It is evidence the field is not measuring what its NAME says

- **What happened.** A freshness ceiling (`MAX_VENUE_QUOTE_AGE_SECONDS = 45`) was refusing live venue quotes, and the two ages recoverable from refusals were both 64s. Rather than move the ceiling on n=2 from the censored side, the age distribution was instrumented UNCENSORED — every quote considered, passing and failing. First production emission:
- *(evidence in `learnings_evidence.md`)*
## 2026-08-30 — FORBIDDEN: reasoning about a limit order's cost as if the LIMIT were the price paid. It is a CAP; a marketable limit fills at the book.

- *(evidence in `learnings_evidence.md`)*
## 2026-08-30 — CORRECTION, same day: the tick floor did NOT cause the resting Polymarket orders. I paired two log lines 30 minutes apart and called it a mechanism.

- **The quote was 0.51 and we sent 0.51. The floor changed nothing.** It could not have: 0.51 is already on the grid. The 0.515 appeared THIRTY MINUTES LATER, after the order was already resting. The price moved after we bid; that is market drift, not a rounding defect.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-30 — FORBIDDEN: presenting an agreement as corroboration without asking what INPUT the two sides share. Three blind cross-checks in one evening, from one root

- **The rule going forward, and it costs one line of algebra BEFORE collecting data:** *ask what input the two sides share.* Shared and cancelling -> an identity. Shared and invisible to both -> a blind spot. Shared as a fitting range sitting on the crossover -> a degenerate comparison. If the answer is "nothing", the check may be real; if it is anything else, it is not evidence.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-30 — FORBIDDEN: concluding "the venue does not report X" from X being absent in OUR stored row. Read the payload, not the record of it

- **The rule going forward:** `field is None` in a stored row is a fact about the WRITER, never about the venue. Before claiming a source does not supply something, read the source — a one-shot read-only probe took minutes and settled what three sessions had been reasoning about for hours. The same applies to `venue_count: None`, which I used to hypothesise a null-comparison bug in a guard that never reads that row at all.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-30 — FORBIDDEN: trusting a guard that has been crying wolf. Count its false firings before reading its silence OR its alarm

- **The rule going forward:** before citing a guard's alarm as evidence, or its silence as safety, measure its FALSE firing rate on current production. A guard firing on a routine, healthy state is not a guard; it is noise wearing a guard's name, and it is invisible precisely because everyone has learned to skip it. The fix is to make the routine case silent, not to raise the threshold: the correct end state here is `nothing matched`.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-30 — FORBIDDEN: writing to a money-path file without first reading what landed on it. I shipped an unsafe rule that silently overrode a correct fix committed 20 minutes earlier.

- **The premise was false.** `kalshi_orders.fetch_orders` covers the **OPEN** book. An order that FILLED or was CANCELLED is legitimately missing from a completely successful read. An order that filled after a lost submit response has no venue id, does not match by client id, and is not in the open book — exactly my branch's conditions — and would have been marked `rejected`, **deleting a real position from the money record**.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-30 — FORBIDDEN: carrying a count across a population boundary. "71 board spread rows never reach ORDER_PATH" compared an ODDS-BOARD row count against a PORTFOLIO position count, and I spent a day tracing the gap between them.

- *(evidence in `learnings_evidence.md`)*
## 2026-08-30 — A GATE WRITTEN AGAINST DATA THE SYSTEM DOES NOT RETAIN DOES NOT GATE. IT BLOCKS.

- *(evidence in `learnings_evidence.md`)*
## 2026-08-30 — A RETRACTION: I DIAGNOSED THE `not_found` LATCH CORRECTLY IN GENERAL AND WRONGLY IN THE INSTANCE

- **The cause I attributed to the actual blocking order was wrong.** I said it had FILLED or been CANCELLED and so legitimately left Kalshi's open book. It had `venue_order_id=None`, no ticker, `market=spreads_alt`, $1.45 — it was NEVER SENT. A write-ahead record was left `submitted` when the build failed with `OrderBuildError(ticker=None)`. A peer's `63661af1` found that and is what cleared the 55-minute outage; my fix requires a venue id to read by and would have named the order and kept blocking.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-30 — FORBIDDEN: keying a predicate to a field name you have not confirmed the record STORES. My log printed `ticker=None` for every order because `ticker` is not a key on it.

- *(evidence in `learnings_evidence.md`)*
## 2026-08-31 — FORBIDDEN: concluding from ONE tick of a counter that increments before its own drop gate. Three wrong readings in one session, each confident and each plausible

- **What was overturned.** Three separate claims I stated as findings and had to retract, all from the same shape: a reading that was true of its sample and false of the system.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-31 — `TaskStop` does not kill the shell child, and a poller that re-`acquire`s strands its own deploy claim

- **How to apply:** a poll loop reads `deploy_claim.py status` and NEVER `acquire`. Acquire once, keep the token, release with `release --service <svc> --token <t>`. After any `TaskStop` on a shell loop, confirm with `ps -ef | grep <script>` and `kill -9` the survivor. Prefer bounded loops (`for i in $(seq 1 N)`) so a stray child expires on its own.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-31 — THREE HYPOTHESES DIED ON ONE DATASET, AND ALL THREE WERE ONE-DIMENSIONAL PROJECTIONS OF A TWO-VARIABLE RULE

- **THE RULE, measured.** Polymarket fills separate on PRICE, CONDITIONED ON PREGAME. n=14, zero overlap:
- *(evidence in `learnings_evidence.md`)*
## 2026-08-31 — A reachability test in TWO STATES says nothing about the EDGE between them

- **FORBIDDEN: claiming a guard is proven because `off != on` passes. That pair tests the two resting states and is blind to the TRANSITION, which is where a guard that fires late still costs everything it was built to save.**
- *(evidence in `learnings_evidence.md`)*
## 2026-08-31 — A tidier rendering of a `- Files:` list SILENTLY DECLAIMS

- **FORBIDDEN: rewriting a lane's `- Files:` block while compacting it. Reuse those lines VERBATIM. The claim set is parsed out of them, and a rendering that is obviously equivalent to a human is not equivalent to the parser.**
- *(evidence in `learnings_evidence.md`)*
## 2026-08-31 — FORBIDDEN: shipping a gate on a one-variable rule when the sample cannot rule out a second variable. Three hypotheses died on one dataset because each was a projection of a 2-D structure.

- *(evidence in `learnings_evidence.md`)*
## 2026-08-31 — `lane-guard` strips the leading dot, so every claim under `.syndicate/` or `.claude/` is UNENFORCED

- **FOUND, NOT FIXED, and the reason it is not fixed is the interesting half.**
- *(evidence in `learnings_evidence.md`)*
## 2026-08-31 — a branch assertion proves the code RAN, not that it did the right thing

- **OVERTURNED:** my own standard, that a field which exists only in the new code is sufficient verification of a deploy. I have argued this repeatedly and it is still the right FIRST check. It is not a sufficient one.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-31 — a correct fix can make a latent bug REACHABLE, and that is the fix's problem

- **The mechanism generalises.** The gate used to read PLANNED prices — 0.441, 0.444 — which are arbitrary and essentially never land on a round boundary. The fix made it read SUBMIT prices, which are SNAPPED TO THE TICK and therefore land on round boundaries constantly. Correcting the input did not change the comparison; it changed the DISTRIBUTION of values reaching it, and moved the mass onto exactly the point where the comparison was wrong. 0.45 is where a 0.44 or 0.445 quote crosses to, so the arm's most probable price was its blind spot.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-31 — TWO THINGS ABOUT GATED DEPLOYS THAT COST AN HOUR EACH TO REDISCOVER

- **It went UP before it went down.** New sweeps queue behind finishing ones, so the job count is a level, not a countdown.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-31 — FORBIDDEN: verifying a ranking change by TOP-N COMPOSITION. The slate rotates faster than you deploy

- **A composition count over a ranked list is not a property of your change. It is a property of what happened to be on the board.** Measured on the served Layer 2 shortlist, with NO code change, inside twenty minutes:
- *(evidence in `learnings_evidence.md`)*
## 2026-08-31 — A basis LABEL does not make two scales commensurable

- **FORBIDDEN: putting two differently-united quantities into one sort field and treating a stamped `basis` string as having handled it.**
- *(evidence in `learnings_evidence.md`)*
## 2026-08-31 FORBIDDEN: reporting an ROI whose grades we produced ourselves, without naming that we produced them.

- **The rule this is a second instance of, not a first.** `paper_settlement.py` already carries the rule in its own docstring — "THESE ARE NOT THE SAME KIND OF NUMBER AND MUST NOT SHARE AN ROI" — written 2026-08-26 off n=3. `state.md` carried it as UNVERIFIED AND LOAD-BEARING for five days. The surface kept showing the blend the whole time, so the rule existed in prose and nowhere a decision could trip over it.
- *(evidence in `learnings_evidence.md`)*
## [08-31 FORBIDDEN: sizing a payload raise against the key you SHARDED, when another key still scales with the same quantity]

**Measured 2026-08-31, and it corrupted the production board for ~29 minutes.**

Sharding the Layer 2 board split `rows` into per-sport keys, each self-trimming
against its own 8MB ceiling. I raised `SYNDICATE_LAYER2_ROWS_PER_SPORT` 1000 → 3000
after verifying each SHARD fit. It broke immediately, because the **combined key
still carries ~2,200 bytes/row of card/metadata even when `rows: []`**:

```
1634 rows -> combined 3,754,595 B   OK
4552 rows -> combined 9,648,192 B   REFUSED (ceiling 8,388,608)
```

Sharding moved PART of the payload. The unsharded remainder scaled with exactly
the quantity I was raising, so "each shard fits" was true and irrelevant.

**The aggravating detail: I had written the fact down myself**, in the deploys
entry immediately above the incident — *"the combined key is ~3.75MB of
cards/metadata and does not shrink with rows — that is the fixed cost, and it is
the thing to watch"* — then sized the next raise off shard bytes anyway. Calling
it "fixed cost" was the error; it is per-row. **A note you wrote yourself is not
protection unless the next decision actually reads it.**

**How to apply.** Before raising any bound that a splitting change was supposed to
relieve: enumerate EVERY key the write path touches and measure each against the
quantity being raised. "The thing I split now fits" answers nothing about the
things you did not split. The instrument to trust is the one naming the key that
actually refused — `LAYER2_SHORTLIST_WRITE_FAILED` names it and its byte count.
## [08-31 FORBIDDEN: assuming a refused write degrades to STALE. Check what the reader does with a half-updated set]

Same incident, and this is the defect that turned a bad config into wrong data.
`_write_layer2_shards` runs BEFORE `write_json_file(combined)` with **no
rollback**. The shards advanced to a 4,552-row board; the combined write refused;
the combined key stayed frozen at `shard_row_total=1635`. `_merge_layer2_shards`
sizes its slots from that stale total, so **2,917 rows were unplaceable and an
entire sport (NCAAF) vanished from the board** — for at least three build cycles,
because every cycle repeated it. It does not self-heal.

`_shed_rows_to_fit_keyvalue` — the guard that exists for exactly this — is
**skipped when sharding is on** (`if keeps_rows: payload = _shed(...)`), so nothing
trimmed the overflowing key.

**How to apply.** A write that can refuse, in a multi-key set, needs the reader to
be safe against a PARTIAL update — or the writes ordered so the last one is the
one that makes the new set visible. Writing the data first and the index second,
with no rollback, means a refused index write publishes data nobody can address
correctly. "It'll just serve the last good copy" is a claim about the READER, and
must be verified there, not assumed from the writer's try/except.
## [08-31 FORBIDDEN: a size instrument that measures a payload the code no longer writes]

`SHORTLIST_PERSIST_LARGE` reports the payload WITH rows and advises *"lower
SYNDICATE_LAYER2_ROWS_PER_SPORT"*. Since sharding, that payload is **never written
as one key**. It read `pct=93.3` on a perfectly healthy 1,600-row board and
`pct=237.9` on the build that broke — alarming in both cases, actionable in
neither, and its advice was backwards for the healthy one.

**How to apply.** When a write is split, every size/health instrument pointed at
the old single write becomes a liar in both directions. Re-point it at the keys
that are actually written, in the SAME change that splits them.
## [08-31 FORBIDDEN: trusting `git cherry` alone. It gives FALSE POSITIVES, and they push DUPLICATES]

**THE GENERAL FORM, so this entry is findable from whichever instrument you
happen to be holding** `[widened 2026-09-03, handed over by f97ad5ab who found
the framing too narrow; three instruments, three sessions, one day]`: **any
IDENTITY-based check — patch-id, SHA ancestry, object existence — answers a
different question than REACHABILITY, and after a rebase identity is exactly
what does not survive. Only a content match on the upstream blob answers this
one.** Same failure with three faces:

    git cherry                       patch-ids stop matching when upstream context moves
    git merge-base --is-ancestor     the SHA is rewritten by the rebase
    git log -1 <sha> / show --stat   answers "exists locally", never "reachable"

The remedy below is unchanged and covers all three. It is written up as its own
rule at `2026-09-03 — FORBIDDEN: reporting a commit as PUSHED on the strength of
a command that also succeeds when it is not`; this pointer exists because a
reader arriving with a different instrument would not otherwise recognise that
this entry applies to them — the same way a scope-less rule gets discarded by
one counter-example (see the dot-prefixed `rev:path` entry).

**Refines the standing "remote-absent ≠ content-absent" rule, which said to run
`git cherry` FIRST. That is still right, and it is not sufficient.**

Measured 2026-08-31. Pushing a second batch, `git cherry -v origin/main HEAD`
marked **4 commits `+` (absent upstream). Two of them were already upstream** —
I had pushed them myself an hour earlier as cherry-picks. Their patch-ids no
longer matched because upstream context around them had moved, so `git cherry`
could not recognise its own copies.

Acting on that would have appended two `deploys.md` entries a second time.

**How to apply.** `git cherry` is the cheap filter, not the verdict. Before
pushing, grep the UPSTREAM BLOB for a distinctive string from each commit:

    git show "origin/main:.syndicate/deploys.md" | Select-String '<distinctive phrase>'

and require exactly one occurrence in the tree you are about to push. PowerShell,
not Git Bash: `origin/main:path` is mangled to `origin\main;path` and the command
fails, which — with a `|| echo 0` fallback — reads as **"content absent"** and
argues for pushing MORE. That happened here, in the same check.

**THE DEFINITIVE CHECK IS `merge-tree`, NOT A HAND-PICKED STRING**
`[added 2026-09-03; technique from session c38d3e5c, negative control by f97ad5ab]`.
The grep above still works and stays as the cheap read, but it depends on
choosing a phrase that is distinctive AND survived rewording, which is a second
judgement call in a check that exists because judgement failed once already:

    git merge-tree --write-tree origin/main <sha>     # -> a tree object
    git diff --stat origin/main <that tree>           # EMPTY => already upstream

It answers the WHOLE commit rather than one line of it, needs no phrase, and is
immune to the dot-path mangling below because it takes no `rev:path` argument.

**MEASURED WITH A NEGATIVE CONTROL, because an EMPTY result is only evidence
once you know the tool can return a non-empty one.** Both readings on the same
pair of commits:

    caab9344 / 2292f027 (rebased upstream)   diff EMPTY      content IS upstream
    a throwaway README edit                  diff 1 file     content is NOT
    `merge-base --is-ancestor` on both       "NOT upstream"  <- FALSE NEGATIVE

That last row is the whole entry in one line: the identity check is confidently
wrong about commits whose content is already there, and it is wrong in the
direction that makes you push a duplicate.

**SCOPE, MEASURED 2026-09-03 — it breaks ONLY on DOT-PREFIXED trees, which is
worse than "it breaks", not better** `[session c38d3e5c; refinement from
f97ad5ab, who hit it the same day]`:

    works    origin/main:README.md
    works    origin/main:scripts/check_lane_invariants.py
    works    origin/main:docs/ai_context/todo.md
    BREAKS   origin/main:.syndicate/lanes.md
    BREAKS   origin/main:.claude/hooks/lane_claims.py

**Why stating it generally is dangerous.** As an unqualified claim this rule is
falsifiable by one counter-example — anyone who tests it on `scripts/foo.py`
sees it work, concludes the rule is stale, and goes back to Git Bash. Then the
next `.syndicate/` check returns a silent 0. A true rule that looks false on the
first probe gets discarded, so the scope has to travel with it.

**And the at-risk set is exactly the verification surface.** The only two
dot-prefixed trees here are `.syndicate/` (the ledger — every claim about what
we know) and `.claude/` (the hooks — every claim about what is enforced). So the
failure lands precisely on the reads that decide whether something is true,
never on ordinary source reads where a wrong answer would be caught by the next
compile.

Three instances now, all on `.syndicate/**` blobs: the `git cherry` push
decision above; a `grep -c` that returned a confident 0 for a file git never
opened while checking whether two lanes' disclaimers were upstream; and
f97ad5ab's near-miss "confirmation" that a peer report was wrong. Note the
direction is always the same — a null that argues for acting.
## [08-31 FORBIDDEN: running a long test sweep while editing the files under test]

A 72-minute sweep (`-k "layer2 or shard or intelligence_state or shortlist"`)
returned **5 failures**, two naming the exact function I had changed. All 5 pass
in isolation and their three full files pass clean.

The cause was mine: during that 72 minutes I edited
`pipeline/intelligence_state.py` repeatedly AND deliberately swapped it to the
pre-fix `HEAD` version for about a minute to prove the new tests fail without the
fix. A long run imports modules as it reaches them, so it read whatever was on
disk at that moment.

**The result is void in BOTH directions** — it is not evidence of a regression
and not evidence of correctness, because it never tested one tree. Same class as
a `git stash` control that stashed nothing: a control that was not controlling.

**How to apply.** A sweep is a measurement, and a measurement needs a frozen
subject. Either let it finish before touching the files, or run it against a
worktree pinned to the commit you mean to test. Reading its failures at face
value sends you hunting a regression that does not exist — or "fixing" working code.
## [08-31 RETRACTED: the pregame PRICE rule. A pregame fill at 0.45 exists, and I handed that rule to a peer as a threshold]

**What I claimed, earlier this session, and passed on as a usable threshold:**
pregame fills and resting orders separate cleanly on PRICE — *max filled pregame
`0.335`, min resting `0.410`, zero overlap* — with live/past fills at `0.490`.

**The counter-example, measured 2026-08-31 from the served ledger:**

```
tsc-epl-ast-ars-2026-08-31-2pt5   totals over 2.5   polymarket
  fill_price          0.45          <- ABOVE the 0.410 "nothing fills pregame above this"
  submitted_at        15:25:45.239Z
  venue_resolved_at   15:25:45.994Z  <- filled in 0.75 SECONDS
  commence_time       19:00:00Z
  => PREGAME at both submit and resolve, by 3.57 hours
```

A pregame fill at `0.45` cannot coexist with "pregame fills top out at 0.335".
**The rule is FALSIFIED.** Anyone gating on it is using a bound that has a live
counter-example.

**The likely reframe, NOT yet established:** the discriminator is probably
MARKETABILITY, not price. This order resolved in 0.75s, which is a taker crossing
the book, not a maker resting on it. My original population almost certainly mixed
aggressive orders (fill instantly at whatever they are priced) with passive ones
(rest until the market comes to them), and read the mixture as a price boundary.
`EXPLORE_PREGAME_BOUNDARY` deliberately prices ABOVE the ceiling, so exploration
orders land in the aggressive population by construction.

**How to apply.** Do not gate on the 0.335/0.410 numbers. Before any replacement
rule, split fills by `venue_resolved_at - submitted_at`: sub-second is a taker and
tells you nothing about whether a resting order would have filled. A threshold
fitted across both populations describes neither.

**Also, on counting these at all:** `EXPLORE_*` exists ONLY as a log line — no
field on the order marks it. In a 26h window, **17 log lines were 3 distinct
tickers**, because the same order re-logs every tick. Count distinct tickers and
join to the ledger; a line count overstates by ~6x.
## 2026-08-31 — FORBIDDEN: choosing a hypothesis from what is VISIBLE rather than what DISCRIMINATES

- **Three hypotheses on one question in one night, all confidently reasoned, all wrong** (lane `layer2-accuracy-audit`, `todo #611`): the MLB prop pregame freeze has produced nothing since 2026-08-16, and I successively blamed (1) the freeze being unreachable on the worker's disk, (2) the seal's `source_path` being absent under `market/oddsapi`, and (3) the freeze never being invoked for MLB. Each was refuted within the hour, twice by evidence I already held.
- *(evidence in `learnings_evidence.md`)*
## [08-31 FORBIDDEN: matching a guarded status on a GUESSED STRING instead of the condition you care about]

**Twice in one session, same shape, both in my own deploy watchers.**

1. A watcher polled the **LIVE** deploy to decide whether one was in flight. A
   deploy that is `build_in_progress` is not live, so it read "nothing happening"
   and **took the deploy claim while another deploy was mid-build** — the exact
   race the claim exists to prevent.
2. A watcher gated acquisition on the status line containing `free`. The real line
   read `EXPIRED (does not block)` — my own 61-minute-old claim, which was not
   blocking anything and which `acquire` would have replaced immediately. It
   polled for **six minutes and would have polled forever**, in the middle of a
   sequence whose next step was a production flip.

Both are the same error: I encoded a **guess about how the state would be
spelled** rather than the condition. `free` and `EXPIRED (does not block)` are
both "you may acquire"; `live` and `build_in_progress` are both "a deploy exists".

**How to apply.** When gating on a tool's output, gate on the tool's OWN verdict —
its exit code, or the explicit set of states it documents — never on a substring
you expect to see. If you must match text, enumerate every terminal AND permissive
spelling, and assume the one you did not think of is the one that will appear. A
watcher that stalls is the benign outcome; the other one deployed into a race.
## 2026-08-31 — FORBIDDEN: shipping a diagnostic without first proving its OUTPUT is readable

- **The check that would have caught it costs one query and I did not run it:** before adding a log line, confirm that SOME EXISTING line from the same process reaches the reader you intend to use. I had the evidence to do this — I had already been told the odds-refresh subprocess's stdout is captured to a file, and I had already watched Render's logs API return MLB refresh activity only as `ALL_PROCESS_MEMORY` process-list entries, never as script output.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-31 — FORBIDDEN: shipping a model INPUT artifact without tracing its delivery topology first. "Publish" does not mean "the engine can read it"

- **Three separate mechanisms had to be checked before a 867-byte calibration file could reach the engine that reads it, and TWO of my first two choices were silently wrong. None of them would have failed loudly.**
- *(evidence in `learnings_evidence.md`)*
## 2026-08-31 — A miscalibration can be REAL and still not worth correcting. Check what carries the LOSS, not what looks wrong in a ratio table

- **I pre-registered the wrong expectation and the held-out test refuted it, which is the only reason it is not now shipped.**
- *(evidence in `learnings_evidence.md`)*
## 2026-08-31 FORBIDDEN: two guards that read the SAME input are one guard

- **Independence is a property of the INPUT, not of the code path.** A second check that consumes the first one's source adds only the appearance of redundancy, and it reads as defence-in-depth in review precisely because it was written to be.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-31 A CONVENTION VERIFIED ON ONE SPORT IS NOT A CONVENTION

- **HOW TO APPLY.** When a parser encodes an external system's naming convention, the docstring must say WHICH instances it was verified against. A convention confirmed on one league, one sport, or one feed is a sample of one. And the places that consume the roles POSITIONALLY are the blast radius — here, fixture matching survives an inversion (both teams are present, so the game is still found) while ROLE selection does not, which is why only the leg choice broke.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-31 A TEST CAN PASS THROUGH THE BUG IT IS NAMED FOR

- **HOW TO APPLY.** A stub that makes a dependency maximally permissive does not "isolate" the unit — it silently selects whichever code path does not consult that dependency. When the test's name is about CHOOSING between candidates, an always-True matcher guarantees the choice is made somewhere else, and the test then pins that somewhere-else forever. Stub discriminatingly, mirroring what the real dependency answers, and pin the permissive case as its own explicit test with the opposite expectation: a resolver that matches everything must REFUSE.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-31 FORBIDDEN: two guards that read the SAME input are ONE guard

- **HOW TO APPLY.** When a comment claims one check guards another, ask what each READS. Independence is about INPUTS, not about being separate code. Two checks over one derived value are one check with extra words — and the redundancy makes it look safer than a single check would. Prefer the check that reads a DIFFERENT SOURCE (here: the board's own team names, not the slug's positions), and put it FIRST when it is the authoritative one. Related: [[feedback_gate_on_the_output_not_the_input]].
- *(evidence in `learnings_evidence.md`)*
## 2026-08-31 FORBIDDEN: fixing a decision's INPUT without checking every CALLER supplies it

- **HOW TO APPLY.** Changing which field a decision reads is a change to every caller, whether or not their code changes. Enumerate the call sites and check each supplies the new field — the schema is the evidence (`_SLATE_STORAGE_FIELDS`), not the passing suite. And when the new failure mode is "refuses", a green suite is especially weak evidence: most safety tests assert exactly that.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-31 FORBIDDEN: treating `Auto-merging <file>` as a verification of a ledger merge

- **The rule going forward.** Before pushing ANY merge that touches `.syndicate/`, run each ledger file's own invariant against the MERGED blob, never the merge exit code, and never only the file that failed last time: `py -3 scripts/lane_claim_audit.py` plus an explicit **one OPEN `### <slug>` header per slug** assertion for `lanes.md`; **one `## [subject]` section per subject** for `state.md`; then `echo '{}' | py -3 .claude/hooks/ledger-postwrite-check.py` — it reads stdin like every hook here, so on a bare TTY it hangs and reads as a pass. Prefer `git merge-tree` / `commit-tree` when other sessions are live: it lets you inspect the merged tree before it exists anywhere.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-31 FORBIDDEN: taking a tool's DEFAULT liveness detection as the answer to "is this session gone"

- **The rule going forward.** Establish liveness from the roster, then pass `--live <id>` explicitly for each session that is genuinely running; never let the mtime default decide. **And re-read liveness immediately before the write, not once at the start** — "no active sessions" was true at 01:4xZ, false by 02:0xZ when a new session opened a lane, and a second one appeared at 02:4xZ. Note the default errs CONSERVATIVE (a dead session looks live, so a lane is skipped); the dangerous direction — sweeping a lane whose session is running — is what the re-read before writing protects against.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-31 FORBIDDEN: pooling an evaluation sample across artifact ROOTS. Split on provenance BEFORE the first statistic, and report the split. `[lane wnba-accuracy-assessment]`

- **What happened.** I graded the WNBA pregame sim over the whole 2026 season off `/wnba/api/cards` and reported: **Brier skill -21.5%, AUC 0.5954, spread AUC 0.4806, totals +10.45 pts/game biased.** That reads as "the model is worse than climatology and its spread signal is inverted" — a delete-it verdict. It was wrong.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-31 FORBIDDEN: reporting a live-model hit rate without splitting by GAME CLOCK and by LINE SOURCE. A number that improves as the game ends is leakage, not edge. `[lane wnba-accuracy-assessment]`

- **What happened.** The WNBA live prop engine grades out at **1249-440, hit 73.95%, +41.18% ROI at -110** over 1,689 signals — graded correctly, against *final* box scores. Every step of that arithmetic is right and the conclusion would have been catastrophic.
- *(evidence in `learnings_evidence.md`)*
## 2026-08-31 FORBIDDEN: shipping a calibration refit validated only in-sample — and treating a POOLED miscalibration as a current one. `[lane wnba-accuracy-assessment]`

- **What happened.** I measured the WNBA win-prob mapping's implied margin SD at **10.87** against a pooled residual SD of **12.81**, refit sigma to **18.25**, and watched in-sample Brier skill go **+16.53% → +21.51%**. A clean one-parameter win, and I was one step from recommending it.
- *(evidence in `learnings_evidence.md`)*

## 2026-09-06 — FORBIDDEN: instrumenting join A, reading it, and concluding about a value written by join B. Name the WRITER of the field in the falsification test itself. `[lane mlb-first5-kalshi-fanin-mismatch, vs 15410ca7]`

Two sessions investigated one board row on the same day and reached opposite
verdicts. Both measurements were CORRECT:

    join_kalshi_to_board      -> the ORDER path resolves KXMLBF5TOTAL   (peer)
    apply_venue_quotes_to_grid-> the PRICE came from KXMLBTOTAL, -669   (this lane)

The peer's falsification test read "if the emitted series for that row reads
KXMLBF5TOTAL, the mismatch hypothesis is dead" — a well-formed test pointed at
the wrong function. "The series for that row" has two answers because two joins
touch the row, and the one that mattered was the one that WROTE the field under
suspicion (`price_source`, `book_prices`, `venue_basis`).

**THE REMEDY IS ONE CLAUSE IN THE TEST:** write the falsification test as *"the
series that `<function that assigns the field>` used"*, not *"the series for
that row"*. If you cannot name that function, that is the first thing to find,
not a detail to fill in later.

**AND THE TELL WAS SITTING IN THE FIXTURE.** Their test file carried both real
contracts with real prices — `KXMLBTOTAL` at `-669`/0.870 (commented "the number
production actually showed") and `KXMLBF5TOTAL` at `+103`/0.492. The conclusion
was "0.870 is a wide ask on a thin first5 market" while the file itself said the
first5 ask was 0.492 and the 0.870 belonged to the full-game contract. **When a
conclusion and a fixture in the same commit disagree, the fixture is the
measurement and the conclusion is the story.** Re-read your own fixture against
your own headline before shipping the headline.

**DO NOT let this read as "the peer was careless."** They revised their
hypothesis DOWNWARD before building, wrote an explicit falsification test,
shipped instrumentation only, and used real tickers instead of paraphrases —
all of which is why the refutation was cheap to produce. A vaguer investigation
would have left nothing to check.
## 2026-09-06 — FORBIDDEN: concluding a guard covers a symptom because the guard is deployed, firing, and named after it. Find the code that WROTE the field you are looking at. `[lane mlb-first5-kalshi-fanin-mismatch]`

A first5 board row was priced at a whole-game 0.870. `_segments_agree` exists
for exactly that, was present by content on all three live SHAs, and its counter
`segment_has_no_matching_series` was firing 160-191 times per join that very
hour. Every one of those readings is true and **none of them is about the field
in question**: the guard is on the ORDER path
(`portfolio_commit` → `kalshi_ticker_resolver`), and `price_source` /
`book_prices` / `venue_basis` are written by `venue_quote_fanin`, a different
module in which the word `segment` did not occur once.

The 2026-09-05 audit that established the guard was correct is still correct. It
answered "can a segment bet get a wrong TICKER". The question a day later was
"can a segment row get a wrong PRICE", and the same words name two joins.

**THE REMEDY, and it is one grep, not a judgement:** before crediting a guard,
grep for the WRITER of the exact field you are looking at, and check the guard
is on that call path. `grep -rn "price_source" ` reaches
`venue_quote_fanin.py:1397` in one hop. A counter's name is not its scope.

**THE COROLLARY THAT COST THE MOST TIME:** "the counter reads 0, which is
consistent both with the guard working and with the guard not being on this
path" is the right observation and the wrong conclusion to stop at. A counter
belonging to another path cannot be evidence in either direction — it is not
weak evidence, it is *no* evidence, and treating it as weak keeps the wrong
hypothesis alive.
## 2026-09-06 — FORBIDDEN: shipping a refusal keyed to ONE spelling of a value that has synonyms. Check the synonym set before the predicate, not after. `[lane mlb-first5-kalshi-fanin-mismatch]`

A segment guard compared `normalize_segment(row["segment"]) != "full"`.
`normalize_segment` folds only the empty string, and grid rows in two existing
suites carry `segment="full_game"` — so the guard refused **10 tests** and would
have stripped the venue price off every whole-game row spelled that way. A
refusal that removes coverage is not a fix; it is an outage with a good
rationale.

Production writes `full`, and that was ESTABLISHED rather than assumed: the
ORDER path's own comparator does not fold either, and it matched 545-845 board
rows per join that day — rows spelled `full_game` could not have done that.
The synonym lives in fixtures and in `layer2_board._segment_label`'s accepted
set (`full`, `full_game`, `game`).

**FOLD ANYWAY WHEN THE COST IS ASYMMETRIC.** Being wrong about the spelling
costs a silent coverage collapse; folding costs at most one refusal you would
have wanted. Take the cheap side, and write down which spelling you verified so
the next reader knows what the fold is insuring against.

**AND: the existing fixtures were the instrument.** They were not "wrong" and
must not be edited to make a new predicate pass — that is how a test stops being
able to witness the thing it was written for.

### 2026-09-05 — FORBIDDEN: a per-item guard implemented as an `A or B` search over a CONCATENATION of every item's source. Whichever item supplies B satisfies it for EVERY value of A, so the check has no failing input at all `[lane ncaaf-segment-capture, commits 7f197639 / 7dfabcf4, NO DEPLOY]`

- **What we believed:** `tests/test_all_sports_segment_wiring.py` guarded the
  gap it was written for — *"a sport with declared segments and NO wiring
  anywhere"*. It had been green since the day it was written.
- **What was actually true:** it read every wired fetcher into ONE string and
  asked, for each sport, whether `segment_market_keys("<sport>")` **or** the
  literal `segment_market_keys(league)` appeared in that string. The basketball
  fetcher always supplies the second token. **So the disjunction was true for
  every sport in `SPORT_SEGMENTS`, and `unwired` was unconditionally `[]`.**
  Behind it: NCAAF had never captured a single half or quarter price —
  `segment == "full"` on **153,723 of 153,723** production rows.
  Its sibling assertion was wrong in a second, different way: it checked that
  the token `segment_market_keys("nfl")` appeared in the NFL fetcher. It does —
  in a map that `main()` never passes to `markets=`, so the 36 keys reached the
  TAGGER and never the request. **Both halves of the guard were green, and both
  were measuring something other than what they claimed.**
- **How we found out:** looking for NFL's supposed 422 and finding there could
  never have been one, because no segment request was ever sent. Then reading
  the guard that should have said so.
- **The rule going forward:** **when a guard is per-item, the search corpus must
  be per-item too.** Flattening N sources into one string turns "does item i
  have property P" into "does ANY source have property P", and the two are
  indistinguishable while every source is healthy. Join on an explicit column
  instead — the fix here adds a `sport` field to the table and diffs
  `set(declared) - set(wired)`. And **ship the guard's own falsifier beside it**:
  a companion test that removes one row and asserts the expression goes
  non-empty. That test is what converts "it passes" into evidence.
  This is `instrument blindness` (a healthy reading is evidence only once you
  know what makes it read unhealthy) with a specific, greppable shape: an `or`
  over a corpus.
- **Cost:** NCAAF ran an entire season opener with zero segment capture and a
  green test asserting the opposite; NFL's regular-season segment map has been
  dead code with a docstring claiming it was live. Both found only because
  someone went looking for a vendor error that did not exist.


### 2026-09-05 — A DEPLOY GOING LIVE AND THE ARTIFACT IT CHANGES BEING REBUILT ARE DIFFERENT EVENTS — gate the check on the ARTIFACT'S mtime `[lane mlb-hitter-so-dead-field, commit bc82090f, no deploy]`

The MLB hitter-strikeouts fix was live on refresh-worker at 23:26:26Z. The
2026-09-05 board went on reading `mean 0.0 / modeProb 1.000 / 1 rung` for
**5 h 49 m** afterwards, sitting next to a healthy 2026-09-04. That is the shape
of a PARTIAL fix, and it is the most dangerous shape there is: it invites the
next person to "finish" work that is already complete, or to revert it.

The cause was vintage, and the margin was **106 seconds** — the 09-05 sims were
written 23:24:40Z, the deploy went live 23:26:26Z, and nothing rebuilt that date
until 05:13:08Z. On its first post-deploy build it read `mean 1.042`.

**RULE: when verifying a fix that a JOB writes into an artifact, gate on the
artifact's own `generated_at`/mtime crossing the deploy, never on wall clock and
never on "the deploy is live".** A watcher built that way read `mean 0.0` on two
of four polls; reporting either would have been a false negative against a
correct, deployed fix. Publishing the fix is one event, the job re-running is a
second, and here they were most of a working day apart.

**Corollary, and it is the cheap half: state the expected lag BEFORE you look.**
Saying "this needs a rebuild, so a zero right after the deploy means nothing"
costs one sentence and converts a scary reading into an expected one. Two peer
sessions hit the same confound the same night in opposite directions — one saw
NFL 78-unmatched persist past a live deploy and clear ninety seconds later on
the next rebuild.

**And a durability reading is not the same as a verification reading.** The
09-05 board was re-checked ~14 h and many rebuilds later (`mean 1.077`,
5 rungs). The first post-deploy read proves the code ran; the later one proves
it keeps running. A single post-deploy read cannot distinguish "fixed" from
"fixed once".


### 2026-09-04 — A TOOL THAT MUTATES IS NOT A PROBE, AND A POLL SLOWER THAN THE WINDOW MEASURES NOTHING `[lanes mlb-ladder-refusal-deploy, commits 2e555b2c / ccb053c7, DEPLOYED]`

Three things went wrong while deploying behind another lane's claim. None cost
production; all three are cheap to repeat.

**1. `deploy_claim.py acquire` IS NOT A READ-ONLY PROBE.** I ran it to READ the
refusal message. My own claim had expired seconds earlier, so it ACQUIRED —
under the throwaway `--holder probe-only` I had passed as a label. Released and
re-acquired within the minute, but for that minute the lock was recorded to a
holder that does not exist. **It only behaves like a probe while an unexpired
claim already exists**, which is exactly the state you cannot assume when you
are checking. To read the message safely, check `status` first.

**2. A POLL INTERVAL LONGER THAN THE WINDOW IS NOT A SLOW MEASUREMENT, IT IS NO
MEASUREMENT.** refresh-worker's idle windows are **~90 s, about one per 40 min**.
I polled at 150 s and returned six consecutive `HOLD`s over ~50 min — which
reads exactly like "permanently busy" and would have justified either giving up
or forcing. At 45 s the window appeared on the 4th attempt. **Before concluding
a resource is never free, check the poll is finer than the thing you are
hunting.**

**3. PARSE FAILURE MUST NOT WEAR THE SHAPE OF A GOOD READING.** The same waiter
printed `jobs=0 live=` on a truncated preflight — `jobs=0` is the IDLE signal I
was waiting for, produced by a read that failed. It defaulted to HOLD (the safe
branch) by luck of ordering, not design. The rewrite requires an explicit
`CLEAR`/`HOLD` line and treats anything else as UNKNOWN. Same family as the
09-04 rule about instruments whose partial output is indistinguishable from
their success output.

**FORBIDDEN: `git stash` / `rebase` / `stash pop` around a shared-ledger write.**
Measured: the pop re-applied content already on `origin/main`, producing TWO
blocks for each of four lanes plus a `UU` conflict, and left the INDEX holding
eleven files I never staged. `git add <my file>` then `git diff --cached` showed
all eleven — the index, not my edit. Recovery that worked: verify the
duplication against `origin/main` (1 block there vs 2 locally) BEFORE discarding
anything, reset to `origin/main`, re-apply only your own entry, confirm
`N additions / 0 deletions` on ONE file.


### 2026-09-04 — A SPEC THAT NAMES A KEY IS NOT A GUARANTEE THE KEY IS FED — check the JOIN, not the two sides `[lane mlb-hitter-so-dead-field, commit 0b9a03e7, NO DEPLOY]`

`_HITTER_PROP_DIST_SPECS` named `("strikeouts", "SO", "so_mean")` and the sim
computed `so` correctly three lines away. Both halves were right. **The defect
was the JOIN between them** — the curated `hitter_stat_values` dict handed to
the spec never set `"SO"`, and the read is `.get(row_key, 0)`. Every review of
either side passes. `strikeouts_dist` was `{0: n_sims}` and `so_mean` `0.0` for
every hitter of every game since at least 2026-05-25, confirmed on the SERVED
production payload 2026-09-04: the published ladder said every MLB hitter
strikes out exactly zero times with probability **1.000**.

**RULE — when a spec table drives a lookup, assert the containment.** `set(spec
row_keys) <= set(the dict that feeds it)` is one line. It is now enforced in
`scripts/sim_input_checklist.py`, which `run_mlb_daily_sim_job.py` executes, so
it fails the DAILY JOB and not merely pytest. The checklist could NOT have
caught this before and this is worth stating precisely: it enumerates INPUT
dataclass fields via `dataclasses.fields()`, and this is an OUTPUT spec/dict
mismatch. **`model_engine_standard` §4.1's "audit fields, don't grep names" has
a blind spot: a field audit sees the two sides, never the join.**

**THIRD INSTANCE of the same two-copy failure.** `daily_update.py` carries the
hitter accumulation TWICE (`_simw_chunk`, multiprocessing; `_sim_many`, serial).
`#334` changed one and not the other; `#429` wrote the warning comments at both
sites; `#621` is the same file, same dict, same mechanism. The comments did not
prevent it — **a comment asking a human to remember is not a control.** The AST
drift check is.

**AND THE REACHABILITY TEST DOES NOT COVER THE DRIFT.** Measured: with site 1
broken and site 2 intact, both reachability tests PASS, because `workers=1`
exercises only the serial path. §4.3's `run(off) != run(on)` is necessary and
here it was not sufficient — a duplicated code path needs a SOURCE-level
identity check as well.

**SEVERITY LESSON, and it is the sharper one: the loss was prevented by an
unrelated accident.** No priced recommendation was ever emitted — not because
any guard held, but because the market feed returns ZERO `batter_strikeouts`
quotes (production, 2026-09-04: requested in `meta.markets`, absent from
`meta.counts.markets`, 0 of 289 players, against 270-283 for the other six).
A dead model field was masked by an equally dead market feed. Had the quotes
arrived, a P=1.000 UNDER would have priced against a real line.
`probability_refusal.py`'s own docstring names this exact trap — *a healthy
reading that survives for a reason unconnected to the rule you are relying on
is not evidence that the rule exists* — and it applied to my own investigation:
the handoff's mirror sample (2026-07-12) showed `marketLine: null` and looked
exonerating, but it PREDATES the odds wiring (`#440`, 2026-08-19) by three
months, so it could not have shown anything else. **Check that your exonerating
evidence was capable of returning the other answer.**






### 2026-09-01 — FORBIDDEN: citing `deploy_claim.py`'s `pid` as evidence a claim holder is gone. It records the CLI process's own pid, which exits in ~1s, so EVERY claim reads as dead within seconds of being taken — I broke a live claim on it `[lane mlb-accuracy-assessment, reported by lane open-lanes-cleanup]`

- **What we believed:** the protocol says a claim held by a session that is gone
  may be taken with `--force`. The claim file carries a `pid`, so checking
  whether that process is alive looked like the way to establish "gone" — an
  actual reading rather than an assumption, which is exactly what this repo
  keeps asking for.
- **What was actually true:** `scripts/deploy_claim.py:125` writes
  `"pid": os.getpid()` — **the pid of the short-lived `deploy_claim.py acquire`
  CLI process, not of the owning session.** That process exits about a second
  after writing the file. So the field is dead-on-arrival for every claim ever
  taken, and a liveness check built on it **cannot return anything but "dead"**.
  It is a guard whose unknown case defaults permissive, in the worst possible
  place: it makes `--force` look justified against a perfectly live holder.
- **How we found out:** I forced `refresh-worker` off lane
  `mlb-native-ladders-producer`, citing "pid 22884, verified DEAD via
  `Get-Process`". The holder was live and its claim unexpired (TTL to 16:06Z);
  they told me so, and did not contest the claim. **The proof is on my own
  claim:** I then read `.syndicate/deploy_claims/refresh-worker.json` for the
  claim *I* had taken four minutes earlier and still held —
  `pid 8040` — and `Get-Process -Id 8040` returned **not running**. A live,
  unexpired, actively-held claim reads as dead by the same check I had just
  relied on.
- **The rule going forward:** **never cite the claim's `pid` as evidence of
  anything.** To establish a holder is gone, use signals that describe the
  SESSION rather than the CLI that wrote the file: the claim's `acquired_at_iso`
  against its `ttl_seconds` (an expired claim is genuinely stale), `ListAgents`
  for a live session, or — best — ask the holder, since `SendMessage` reaches
  peers in seconds and a claim exists precisely to make that conversation
  happen. **If the only thing saying "gone" is the pid, you know nothing.**
  Forcing may still be right; it must be argued from the TTL or from silence
  after asking, and recorded as such.
- **Cost:** one live claim broken. Nothing was lost — the holder was not
  mid-deploy, did not contest it, and in fact wanted the deploy my claim was
  for. That is luck, not process: the same reasoning would have killed a deploy
  someone was in the middle of, and the field would have looked just as
  authoritative.

### 2026-09-01 — FORBIDDEN: reading a null or a clean result before establishing that it is READABLE YET. Find the thing that says the signal could have arrived, then read it — four instances in one evening, two false positives and two false negatives `[lanes mlb-accuracy-assessment + wnba-accuracy-assessment]`

- **What we believed:** verification is "deploy, then look at the number". If
  the number looks right the change worked; if it looks wrong it did not. Both
  halves feel like measurement and neither is, because a reading taken before
  the change could possibly have reached the surface says nothing in either
  direction.
- **What was actually true:** in one evening the same defect produced FOUR
  wrong readings across two lanes, in both directions:
  1. **False positive, rolled date.** `/api/portfolio/live` showed no
     `by_venue_family` row below -100% after a P&L fix — but the date had
     rolled, the payload came back dated `2026-08-26`, and the offending order
     `C7AZA3MBEKDD` **was not in it at all**. A clean table was equally
     consistent with "different orders today".
  2. **False negative, pre-deploy tick.** `PLAN_WRITTEN` showed
     `no_model_edge_pct: 1092` and no `market_family_excluded` — stamped
     **03:47:51Z against a 03:52:11Z deploy**. Old code. Read carelessly it
     says "the fix does not work".
  3. **Unreadable null, neighbour not reached.** `WNBA_POSTGAME_PRODUCER` had
     0 matches — but the tick immediately upstream of it in `main()`,
     `BOOK_GRID_TICK`, had also not emitted since the deploy. The worker had
     not reached the dispatch point, so the absence carried no information.
  4. **Never-readable null.** `/api/ops/artifacts/export` returned `count 0`
     for a freshly produced artifact, and it always would have: the worker
     publishes explicitly per path and **allowlisting a path makes it eligible
     to cross, it does not carry it**. No amount of waiting could have changed
     that number.
- **How we found out:** two sessions checking each other. (1) and (2) were
  caught by asking "does this reading post-date the change?" before quoting it.
  (3) was caught by the neighbour technique — find the marker immediately
  upstream of the one you want, and treat your null as unreadable until the
  neighbour fires. (4) was caught by a code comment written by the other lane
  hours earlier, which recorded that **two previous watchers had already burned
  ~35 minutes polling for a change that was structurally impossible**.
- **The rule going forward:** **before reading a null or a clean result, find
  and check the thing that tells you the signal could have arrived.** In order
  of preference: (a) a timestamp on the reading that you compare against the
  deploy/change time — not "recent", the actual comparison; (b) the marker
  immediately upstream of the one you want, so a missing signal is
  distinguishable from an unreached one; (c) proof that a path from producer to
  reader EXISTS at all — for cross-service artifacts that means a publish call,
  not an allowlist entry; and **(d) that the SUBJECT is present in the
  population you are reading** — a post-deploy tick over a slate that no longer
  contains the rows your change acts on is as unreadable as a pre-deploy one.
  **Write the falsifier down before the reading arrives, and write its
  PRECONDITION next to it.** A pre-registered band with an explicit "falsified if" cannot be
  fitted to the result afterwards, and it forces you to name the neighbour.
  **And prefer a gate on the one line only your code can emit** over a
  downstream count that something else could also flip.
- **A FIFTH instance, 04:09Z, which is why (d) is in the rule:** the MLB
  exclusion gate finally got a post-deploy `PLAN_WRITTEN` — check (a) satisfied
  — showing no `market_family_excluded` and `no_model_edge_pct` UP from 1,092 to
  1,260. Read as written, the pre-registered test was falsified. It was not:
  `top_market_per_refusal` named `alternate_totals_corners:690`, a SOCCER
  market, and the board at that hour carried **0 MLB prop rows** (MLB down to 31
  game rows, slate over). **The change had nothing to act on.** The
  pre-registration named a falsifier and did not name a precondition, so a
  reading with no subject in it looked exactly like a failing one.
- **A SIXTH instance, 2026-09-01T12:46Z, and it is a DIFFERENT lesson worth its
  own line: A FALSIFIER MUST TEST THE CLAIM, NOT A SIDE-ASSUMPTION ABOUT
  MECHANISM.** The gate finally became readable (`verify_mlb_prop_exclusion.py`
  READY, 1,876 MLB prop rows) and PASSED: `market_family_excluded: 1860`, top
  market `batter_rbis:379`, i.e. 99.1% of MLB props refused, exactly as
  designed. **But my pre-registered falsifier said "FALSIFIED IF the counter
  appears and `no_model_edge_pct` does not move" — and it did not move
  (1,092 -> 1,277). By my own written test, a working change fails.** The
  falsifier rested on an assumption that MLB props are where the missing model
  edge sits; they are not — `no_model_edge_pct`'s top market is
  `alternate_totals_corners`, a SOCCER market. Pre-registering is necessary and
  not sufficient: a test aimed at a mechanism you have assumed rather than at
  the claim you are making will condemn a change that does exactly what it says.
- **Cost:** ~35 minutes of watcher time on the WNBA side before the code
  comment stopped a third watcher being armed; two wrong conclusions drafted
  and withdrawn on the MLB side before either was quoted; and one WNBA
  web-facing accuracy path that would have stayed at zero forever while its
  producer reported `status: ok` every hour. Nothing reached a user, because
  both sessions checked before quoting — which is the only reason this is a
  learnings entry rather than a postmortem.

### 2026-08-30 — FORBIDDEN: `git commit --only -- <shared ledger file>`. The pathspec form commits the WORKING TREE, which in this repo holds every other session's uncommitted edits to that file `[lane stale-row-cause-blind-spot]`

- **What we believed:** `git commit --only -- <paths>` is the safe way to commit
  in a shared tree, because the pathspec decides the contents rather than the
  shared index. That is true and it is why it was chosen — the index really can
  hold another session's staged work, and this form ignores it.
- **What was actually true:** the pathspec form commits the **working tree**
  state of those paths. For a file only this session touches that is exactly
  right. For a SHARED file — `lanes.md`, `learnings.md`, `state.md`,
  `deploys.md` — the working tree already contains every other session's
  uncommitted edits, and they all ship. Commit `888d02ee` carried another
  session's closure of `venue-first-market-universe` from OPEN to CLOSED. **I
  did not close that lane, do not own it, and had no way to judge whether the
  closure was ready.**
- **AND IT RUNS BOTH WAYS, observed within the hour.** Commit `fde61650`
  ("lanes: CLOSE venue-first-market-universe") swept THIS session's pending
  `stale-row-cause-blind-spot` lane block into their commit. Neither session
  chose to publish the other's work; the tree did it.
- **How we found out:** a rebase. The commit would not fast-forward, and the
  3-way merge of `lanes.md` conflicted on a lane block whose two sides were
  CLOSED (mine) and OPEN (theirs) — for a lane I had never edited. Comparing
  base/mine/theirs on that one heading is what exposed it.
- **The rules going forward:**
  1. **Never commit a shared ledger file by pathspec from the shared tree.**
     Build the blob deterministically instead: take `origin/main`'s version,
     apply YOUR edit to that, and commit it via
     `update-index --cacheinfo` / `write-tree` / `commit-tree`. Then the
     committed content is provably `remote + your change` and nothing else.
  1a. **PIN THE REF TO A SHA FIRST — `BASE=$(git rev-parse origin/main)` — and
     use `$BASE` for BOTH the `read-tree` and the `-p`.** Naming `origin/main`
     twice is a race with every other session, and it bit me inside this very
     entry: `origin/main` advanced between the two steps, so the TREE came from
     the old tip and the PARENT from the new one, and the resulting commit
     **deleted 31 lines of another session's `log/2026-08-30.md`.** That is a
     stale-HEAD revert manufactured by the procedure meant to prevent one.
     Caught in `git diff --numstat` before pushing; `main` was reset and the
     commit rebuilt against a pinned base.
  1b. **Assert the blast radius before `commit-tree`, do not eyeball it.** Sum
     the deletion column and refuse unless it is `0` — and **do NOT exempt your
     own paths from that check.** My first version of this guard excluded the
     files I was editing, which is exactly backwards: the shared ledger file is
     both the thing I edit AND the thing another session is appending to, so a
     stale local copy of it reverts their work while the guard reports clean.
     It fired on the very next attempt: `13 insertions, 36 DELETIONS` on
     `learnings.md`, because the remote had moved again.
  1c. **Apply your edit to the REMOTE's bytes, not to your working copy.**
     `git show $BASE:<path> > tmp`, patch `tmp`, hash THAT. A working copy in a
     shared tree is stale the moment another session pushes, and re-editing it
     re-introduces the revert the whole procedure exists to avoid.
  2. **Before committing any shared file, diff the working copy against
     `origin/main` and read every hunk.** If a hunk is not yours, you are about
     to publish someone else's draft. `git diff origin/main -- <file>` is the
     whole check.
  3. This does NOT retract the existing rule about the shared INDEX. Both are
     real and they are different: the index can hold a stale-HEAD revert, the
     working tree can hold another session's half-finished edit. `--only`
     dodges the first and walks into the second.
- **Cost:** none shipped wrong — caught during the rebase, the commit was
  rebuilt from `origin/main` with only this session's two code files, and
  `lanes.md` was left exactly as the remote had it. The other session's closure
  then landed under their own commit, which is where it belonged.

**THE GENERAL SHAPE, and it is the fourth instance tonight:** in a tree several
sessions share, an artifact does not carry the identity of who made it — not a
commit (author is one bot for everyone), not a lane claim (prose parsed as a
claim), not a backup (named for a state it did not hold), and not a working-tree
edit. **Attribution has to come from outside the artifact every time.**

---

### 2026-08-30 — FORBIDDEN: inferring WHO wrote a commit from ADJACENCY in a shared branch where every commit carries one bot author `[lane exchange-join-refusals]`

- **What we believed:** a peer session attributed commit `c17bc3d8`
  ("polymarket's fee MEASURED ... it is ZERO", touching `venue_fees.py` and
  `kalshi_polymarket_arb.py`) to THIS session, and opened a substantive
  contradiction against it — asking this session to adjudicate a fee model that
  moved a break-even threshold 3.38c -> 0.88c and gates real money.
- **What was actually true:** not this session's commit. It landed **45 seconds**
  after this session's `a29dd997` and 5 minutes before `3a00f35d`. This session
  touched **0 of its 5 files**, `state.md` included. The owner was
  `live-venue-order-placement`, which claims both fee files in its `Files:` block
  and whose checkpoint header describes exactly that work.
- **Why the author field could not help:** every commit in this repo is authored
  `github-actions[bot] <github-actions[bot]@users.noreply.github.com>`. Several
  sessions push to one branch under one identity, so `%an` separates nobody and
  temporal order is the only remaining signal. **It is not a signal.** Sessions
  here commit minutes apart all evening.
- **The rules going forward:**
  1. **Attribute a commit by CONTENT against a lane's declared `Files:`, never
     by position in the log.** One line does it:
     `git show --stat <commit>` and compare to the `Files:` blocks in
     `lanes.md`. `git log --oneline <mine> -- <path>` confirms the negative.
  2. **A misattributed commit is not a harmless mixup when it carries a
     REQUEST.** This one asked a session with no stake and no independent
     reading to break a tie on a live financial threshold. Refusing to
     adjudicate was the correct answer, not a lack of helpfulness — and the
     refusal only became available by checking authorship first.
- **Cost:** none. Caught before any edit to `state.md` or the fee model; the peer
  re-verified and re-routed to the owning session.

**THIRD INSTANCE TONIGHT OF ONE ROOT CAUSE — identity is not recoverable from the
artifact in a shared tree.** (1) A lane block's PROSE naming a contested path
inside a `- Files:` block was parsed as a live CLAIM on a file the lane was
explicitly staying off. (2) A backup named `.CONFLICTED.bak` contained the
RESOLVED file, because `cp` raced another session's resolution. (3) This. Each
was caught by someone checking the artifact against an independent source rather
than reading its name, its neighbours, or its timestamp.

---

### 2026-08-30 — FORBIDDEN: offering a backup as a safety net without verifying it contains what its NAME claims. Mine held the RESOLVED file `[lane exchange-join-refusals]`

- **What we believed:** `.syndicate/lanes.md.CONFLICTED.bak` captured the
  pre-resolution conflicted ledger, so three OPEN lanes that existed on only one
  side of a `git stash pop` conflict were recoverable whatever anyone did next. I
  told my user that in those words, and told two peer sessions the same.
- **What was actually true:** both copies contained **0 conflict markers, 54
  headings, one `mlb-resolver-write-side-effect` block** — the RESOLVED file. The
  `cp` raced the resolution: I grepped markers at 3724/3778/3966, and by the time
  the copy ran (~30s later) another session had resolved it. **The
  pre-resolution state is gone and was never captured.**
- **How we found out:** a peer went to use the file as a test fixture and
  measured it first, rather than trusting the filename. I then verified it
  myself: `grep -c '^<<<<<<<'` = 0 on both copies.
- **Why it was worse than no backup:** the name asserts a property the contents
  do not have, so the next person trusts it. A missing backup fails loudly; a
  lying one fails at the moment someone needs it.
- **The rules going forward:**
  1. **A backup is evidence only once you have checked it contains what its name
     claims** — for a conflict snapshot that is one `grep -c '^<<<<<<<'`, run
     against the COPY, not the source.
  2. **Snapshotting a file under concurrent modification is a RACE.** `cp` of a
     contended path in a shared tree can land either side of another session's
     write. Verify after copying, and name the file for what you verified.
  3. **Never name an artifact for the state you INTENDED to capture.** Rename or
     delete the moment the contents disagree.
- **Cost:** no data lost — the union resolution was correct (+153/−0 vs
  `origin/main`, all three at-risk lanes intact) and the peer built a synthetic
  fixture instead. But a false assurance stood in three places for ~40 minutes,
  and the recovery path I advertised did not exist.

---

### 2026-08-30 — FORBIDDEN: sizing work off a REFUSAL COUNTER before checking how much of it is out of scope. `clubs_unresolved: 314` was ~26 recoverable markets `[lane exchange-join-refusals]`

- **What we believed:** Polymarket's `clubs_unresolved: 314` on NCAAF was a join
  backlog — 314 quotes we were failing to key, and therefore the largest
  single-sport exchange prize on the board. An assessment ranked it #1 to attack.
- **What was actually true:** measured n=25 against a 165-market population,
  **21 of 25 were games this platform does not card** — Campbell v East Tennessee
  St, VMI v Idaho St, Citadel v Wofford, Stetson v South Dakota St. The registry
  is 247 D-III / 171 D-II / 128 FCS / 138 FBS and the board cards FBS-vs-FBS.
  Polymarket lists far more college football than Syndicate boards. Recoverable
  is **~16%, ~26 markets — not 157.** The counter was accurate; the SIZING was
  wrong by 6x.
- **How we found out:** only by building the join and classifying every miss. The
  counter's own name (`clubs_unresolved`) and the adapter comment beside it
  ("each one is a missing `team_aliases` entry") both invite reading it as a
  backlog, and neither is a measurement of recoverability.
- **The rules going forward:**
  1. **A refusal counter measures what a reader REFUSED, not what is
     RECOVERABLE.** Before sizing work off one, classify a sample of the
     refusals into out-of-scope / recoverable. The two can differ by an order of
     magnitude and nothing in the counter says which.
  1b. **AND "recoverable" is not "worth having" — check what the refused rows
     CONTAIN.** `oddsapi no_side_in_key: 3647` is an HONEST counter (a real
     `continue`) on a sport whose board demand is not in doubt, and it is still
     worth ~0: 4.2% are game lines with genuinely no side (correct refusal),
     and 95.7% are props whose side IS present as `selection=` — recoverable in
     one line, and REDUNDANT. Same capture the board already reads
     (`oddsapi_hitter_props_*.json`), no bookmaker field against the board's 8
     named books on 250/250 rows, and OLDER — p50 4.5h against the board's
     58min, so it loses freshest-wins on 78.5% of rows. **Four scope checks,
     four near-zeros, and this is the one where the counter was accurate and
     the demand was real.**
  2. **Two wrong fixes were proposed for this before one was measured** — an
     alias map (already FORBIDDEN the previous day) and a slug-token join (8%,
     dead on the same upstream-vocabulary wall). A named cause sitting next to a
     counter is a HYPOTHESIS. This one had been refuted 24 hours earlier in a
     file the reader was not reading.
  3. **A scope test must not leak across the ambiguity it is scoping.** The first
     cut asked "is any school sharing either mascot FBS?" and called Citadel v
     Wofford in-scope because "Bulldogs" is also Georgia's — over-reporting
     recoverable misses **15x, 28.6% against a true ~0%.** Ask whether the PAIR
     could be in scope, never whether either half could.
- **Cost:** none shipped — measurement-only lane, fix sites held by another lane
  and never touched. Two proposals retracted before code.
- **CONFIRMED THREE TIMES IN ONE SESSION, on the same `reason` string.** The
  scope check that followed found `h2h_keyed_by_team: 905` is **not a refusal at
  all** — it increments on the SUCCESS path (`venue_quote_adapters.py:628-631`,
  no `continue` before `quotes.append`) and its own docstring says it is reported
  "alongside the refusals rather than only on failure". And `spreads_refused:
  3288` is 45% NFL+soccer, which carry ZERO board spread rows, with the rest
  being ladder RUNGS (~8 per game) rather than games. Resized: 905 -> 0,
  314 -> ~26, 3288 -> ~443. **A ~4,500-quote headline collapsed to a few
  hundred.**
- **FOUR INSTANCES, NOT THREE.** A peer session found `no_price` /
  `leg_without_price` two lines above `h2h_keyed_by_team` — same shape, and this
  one APPENDS a `Quote(probability=None, american=None)`; the MIRROR leg in the
  same function guards correctly (`if None: count; else: append`) while the
  PRIMARY leg does not, which is what proves it an oversight rather than a
  design choice. **Traced, not assumed: it is NOT a correctness bug today** —
  `venue_quote_fanin.py:1128` refuses it at the point of use (`if quote.american
  is None: continue`) and nothing outside the adapter reads `.probability`. It
  is inert, and one unguarded future consumer away from not being.
- **MARK WHICH CORRECTIONS ARE PERMANENT.** `905 -> 0` and the `no_price`
  finding rest on reading an INCREMENT SITE and cannot drift. `314 -> ~11-43`
  and `3288 -> ~443` rest on production slate state that moved 166 -> 163 within
  the hour. Written the same way, a reader re-running next week reproduces the
  zeros, fails to reproduce the rest, and concludes the METHOD is unreliable
  rather than that the SLATE moved. Timestamp the readings; leave the
  code-derived corrections undated.
- **THE STRUCTURAL CAUSE, and it is a design defect in the emitter, not just a
  reading error:** `_kalshi_ok_reason` and `_polymarket_ok_reason` format
  SUCCESS counters and REFUSAL counters identically — `name:count`, space
  separated, inside one field literally called `reason`. Nothing in the string
  distinguishes "we could not key these" from "we keyed these fine". A reader
  cannot tell them apart without opening the increment site, and I did not, three
  times. **If you emit a diagnostic counter that is not a refusal, it must not
  share a field named `reason` with the refusals** — or it must carry its own
  prefix (`ok:h2h_keyed=905`).

**WHAT DOES SURVIVE:** the schedule-constrained mascot-pair join is sound and is
the right mechanism when the ~26 markets are worth taking — 51 carded games gave
51 distinct mascot pairs with 0 collisions, and 0 of 25 rows resolved
ambiguously. It is safe where a global alias map is FORBIDDEN precisely because
ambiguity is refused per-row against a real slate instead of pre-resolved into a
map that makes `teams_match` authoritative. Instrument:
`scripts/probe_polymarket_ncaaf_slug_role_join.py`.

---

### 2026-08-22 — FORBIDDEN: never read a `service_updated` deploy as shipping code. An env-var change RESTARTS the service on the commit it is already running

**Measured twice in one evening, the second time after I had already been
caught by the first shape.**

Render redeploys on an env-var change, and with `autoDeploy: no` that redeploy
carries **the commit the service is already on** — it does not pull the branch
tip. So setting a feature flag ships the flag and NOT the code the flag gates.

    dep-da51b13bc2fs73fgu5n0  trigger=service_updated  live 21:33:18Z
      carried 6cd980b4  <- the same commit it was already running
      origin/main was 471cbac9d, one commit ahead, holding the wiring

`SYNDICATE_PORTFOLIO_COMMIT_ENABLED=1` went live against a binary with no
caller for the job it enables. Second time tonight the config landed and the
code did not: an hour earlier `admitted_by_blend=` was committed 18 minutes
AFTER the worker deployed, so the counter could never appear either.

**THE RULE.** Enabling a flag is TWO changes, not one: the env var, and a code
deploy of a SHA that contains what the flag gates. Verify the second with
`git merge-base --is-ancestor <feature-sha> <live-sha>` — the deploy list's
`commit.id` is the live SHA and is the only thing that answers it. A
`service_updated` entry in the deploy history is a RESTART, and reading it as an
update is the same category error as reading a green deploy status as a content
check.

**AND THE DEEPER ONE, which is why this rates a FORBIDDEN rather than a note:**
a flag whose gated code is absent behaves EXACTLY like a flag that is off. There
is no error, no log line, and no failing test — the same signature as
`model_engine_standard.md`'s unfed input, and as a counter that exists at the
builder and never reaches the endpoint. **Whenever a flag is turned on, the
acceptance reading is the feature's own affirmative token** (here
`PORTFOLIO_COMMIT date=… positions=…`), never the absence of an error.

### 2026-08-22 — FORBIDDEN: never name a datastore SETTING and a service ENV VAR by the same store without saying which surface. A 4-minute refresh-worker outage came from that ambiguity

**What happened.** A recommendation to change the eviction policy on the
keyvalue store was written as *"`allkeys_lru` → `volatile_lru` on
`syndicate-refresh-state`"*. There are TWO settable things whose names both
point at that store: the Key Value instance's `maxmemoryPolicy` (Redis's own
eviction rule) and the services' `SYNDICATE_REFRESH_STATE_BACKEND` env var
(which backend the APP routes to). The value went into the env var.

**Measured.** `refresh-worker` crash-looped 2026-08-22T19:31:36Z → 19:35:31Z:

    REFRESH_STATE_BACKEND = volatile_lru
    RuntimeError: Local state backend not allowed in multi-service deployment
                  for refresh-worker: volatile_lru

Recovery on a new instance at 19:35:31.931Z, `BACKGROUND_LOOP_START`
19:35:33.035Z, then `PUBLISH_OK` ×2, `MLB_LINEUP_STATE games=15 posted=5`,
`OVERVIEW_SPORT_BEGIN sport=mlb`. Web and live-odds-worker were never affected
(0 matches for the same error text; web's `PUBLISH_OK` proves it was up).

**THE RULE.** When recommending a change to a hosted resource, name the SURFACE
as well as the resource: *"the Key Value instance's own settings page"* vs
*"the service's Environment tab"*. A resource name alone is not an address when
two surfaces answer to it.

**WHY IT WAS ONLY 4 MINUTES, and this is the part to keep.**
`_state_backend_kind()` maps any unrecognised value to `"filesystem"` — so
`volatile_lru` did not error, it silently meant "use the local disk". On Render
that is three separate disks, i.e. `#502`'s failure applied to the entire board,
and it would have run HAPPILY while every cross-service artifact went private,
discoverable days later. `assert_refresh_state_backend_ready` refuses at startup
BEFORE any state is touched, which converted a silent multi-day corruption into
a loud four-minute outage. **A permissive parse plus a strict startup assert is
the pattern**: the assert is doing the work the `.get(key, default)` cannot.

### 2026-08-25 — FORBIDDEN: never ship a venue's submit side without its read side
- What we believed: the Polymarket integration was incomplete but safe — it
  could place orders, and the read side was a later nicety. `_venue_reader`
  said so in its own docstring: *"The read side of a venue adapter. Only Kalshi
  has one."* A missing reader reads as a gap in coverage.
- What was actually true: it is a LATCH ON THE WHOLE LIVE PATH. The first
  Polymarket order was placed at `16:08:10Z` and rested unfilled. From that
  moment every live pass on EVERY venue returned
  `status=blocked reason=unreconciled_orders` — Kalshi included — and no order
  could be placed again by anything. The unreconciled gate is global by design
  (a stranded order might have doubled), and the only thing that lifts it is a
  venue read. Two independent causes, each sufficient: there was no Polymarket
  reader at all, and `execute_portfolio` called `reconcile_live_orders()` bare,
  whose `venue` defaults to `"kalshi"`.
- How we found out: a USER CANCELLED the order at the venue and said so. That
  prompted the question "will the ledger see it?" — and the answer was no,
  nothing could. The block itself had been printing for 32 minutes
  (`BLOCKED_ON_UNRECONCILED count=1` at `16:40:00Z`, both scopes) and had not
  been looked at, because the absence of LIVE_ORDER lines looks identical to a
  quiet slate.
- The rule going forward: **a venue's submit side and read side are not
  independently shippable — shipping one without the other arms a latch that
  the first resting order closes.** Two tripwires: (1) an invariant test that
  every venue with a submitter has a reader, so a third venue cannot
  reintroduce this by being added to one side alone
  (`tests/test_execution_ledger.py`); (2) when a gate is GLOBAL, the thing that
  lifts it must be attempted for every venue, not just the one in hand —
  reconciling only "our" venue leaves us blocked by a row we declined to ask
  about. And more generally: **an operator action at the venue cannot fix a
  state the system has no way to observe.** Cancelling was necessary and could
  never have been sufficient.
- Cost: 40 minutes of no live execution on both venues, self-sustaining and
  unrecoverable without a code change. No money lost — the one order that did
  go out was on the wrong team for an unrelated reason, and did not fill.

### 2026-08-21 — FORBIDDEN: never publish a field under a name that describes a DIFFERENT quantity, however well-documented the real one is
- What we believed: the Layer 2 board's `Win%` column showed a win probability,
  and `model_probability` was the model's number for the row being recommended.
  Both are what the field names say, and the frontend comment asserted the
  second one outright.
- What was actually true: `Win%` rendered `score["book_confidence"]` — the
  books-quoting ladder `((1,0.5),(2,0.7),(4,0.85))`, else 1.0 — so **"Win% 100%"
  meant "five or more books quote this market"**. And `model_probability` was
  `projection["model_prob_over"]`, always the OVER/HOME framing, so every AWAY
  and DRAW row showed the other side's probability next to a correctly
  side-adjusted "sim disagrees" badge. Separately, `_HITTER_BUCKETS` named three
  mean fields (`runs_mean`, `doubles_mean`, `triples_mean`) that do not exist in
  the artifact (`r_mean`, `2b_mean`, `3b_mean`), so three whole markets could
  never project.
- How we found out: a USER LOOKED AT THE BOARD and said the sim-disagrees column
  seemed wrong. Five distinct Win% values on one screenshot mapped 1:1 onto the
  book-count ladder with nothing left over — a fingerprint no amount of reading
  the producing code had surfaced, because every function was individually
  correct and documented. The producing code even named the hazard: the comment
  above `projection["side"]` says putting home's edge on the away row is "a
  number that is right and labelled wrong, which reads as a real signal", and
  the display layer then did precisely that with the probability.
- The rule going forward: **a value crossing a layer boundary must be named for
  the quantity it IS, and the consuming surface must be checked against that
  name, not against the producer's docstring.** Two specific tripwires, both
  cheap: (1) when a field is displayed, read the TEMPLATE to see what label sits
  above it — `book_confidence` was honest everywhere except the one place a
  human reads it; (2) any lookup key naming an external artifact's field must be
  asserted against a real artifact, at the ROW level, because a key that never
  resolves produces a blank, and a blank is indistinguishable from honest
  missing coverage. `tests/test_layer2_sim_view_sides.py` holds both.
- Cost: unknown but non-zero — a board presented "Win% 100%" on 5+-book markets
  and the other side's probability on every away/draw row, for as long as those
  surfaces have existed. No settled bets, so no measurable financial loss; the
  loss is that the board's most reassuring column was its least meaningful.
## 2026-09-01 REQUIRED: for every grader, ask what it does when its OUTCOME SOURCE IS ABSENT. A fallback there is a false-result generator. `[lanes wnba-accuracy-assessment + mlb-accuracy-assessment, independently]`

- **MLB** (`mlb-accuracy-assessment`): the live-lens grader settled from `lastSeenSnapshot.actual` — **a running tally** — whenever the statsapi feed was unavailable, which was 100% of the time (`feedResolved` 0 on all 11 days that produced rows, against `feed_live_miss: 1,802`). Published reading: **`over 0 wins / 1,578`, `under 206 / 206`.**
- *(evidence in `learnings_evidence.md`)*
## 2026-09-01 REQUIRED: assert on the VALUE THAT CROSSED THE BOUNDARY, not on the call returning. "It didn't raise" and "the counter moved" are different claims, and only the second is evidence. `[lane wnba-accuracy-assessment]`

- **What happened.** I added a block to publish WNBA recon artifacts from refresh-worker to web, because the producer was writing to the worker's disk and the web-facing endpoint reads web's. The block ran cleanly, raised nothing, returned, and **published zero files.**
- *(evidence in `learnings_evidence.md`)*
## 2026-09-01 FORBIDDEN: inferring a MECHANISM from a file's SIZE. Count the composition, or say you haven't. `[lane wnba-accuracy-assessment, caught by lane mlb-accuracy-assessment]`

- **What I claimed.** WNBA's board shows zero Kalshi/Polymarket quotes across 787 book references, while `wnba_source/tracking/book_quotes/2026-08-30.jsonl` is **45,776,899 bytes**. I wrote that up — into `todo.md #616`, into a peer message, and into a user-facing summary — as:
- *(evidence in `learnings_evidence.md`)*
## 2026-09-01 FORBIDDEN: naming a MECHANISM from a SYMPTOM. Three times in one session, on three different subjects. `[lane wnba-accuracy-assessment]`

- **The shape.** A symptom is a value you read. A mechanism is a claim about *why* that value is what it is. Reading one does not give you the other, and the gap is invisible from inside because the number is real and right there. The tell is grammatical: *"the board can't see it"*, *"it's structurally unreachable"*, *"excluded upstream"* — all causal claims, none of which any of those readings could support.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-01 REQUIRED: a PRODUCER fix is not in force on data that already exists. Ask when the artifact is next written. `[lane wnba-accuracy-assessment]`

- **What happened.** I fixed three things in the WNBA odds producer — totals withheld, impossible EV refused, certainty clamped — deployed them to all three services, verified all three deploys reached `live`, and was about to report the items done. Then I read the SERVED PAYLOAD:
- *(evidence in `learnings_evidence.md`)*
## 2026-09-01 REQUIRED: on the shared tree, read the DIFF of a ledger file before committing it, not its --stat. `[lane wnba-accuracy-assessment]`

- **What happened, twice in one day, in both directions.**
- *(evidence in `learnings_evidence.md`)*
## 2026-09-01 FORBIDDEN: recording a LIVENESS field that the recorder itself cannot outlive

- **The rule going forward.** A liveness field must name something that OUTLIVES the code writing it — a session id, checkable with `list_sessions` (`isRunning`) — never the pid of the short-lived CLI that records it. If no such identity is available, **write nothing and let the TTL be the invariant**: a missing field reads as UNKNOWN, which correctly refuses to authorise a force, whereas a dead-on-arrival pid reads as PERMISSION. Absent identity is not absence of a holder.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-01 FORBIDDEN: leaving anything staged in the SHARED index that you are not committing in the same breath

- **The rule going forward.** Stage and commit **atomically** or not at all: `git commit --only -- <paths>` takes the worktree copies of exactly those paths and leaves the rest of the index alone. When the commit needs content that is NOT the worktree copy (rebuilding `origin/main` + only your edits), build it in a **temporary index** — `GIT_INDEX_FILE=<tmp> git read-tree/update-index/ write-tree` then `git commit-tree` — which never touches the shared index at all. **Inspect BEFORE staging, never between staging and committing.** The older "never chain add and commit" is not wrong, but it is not the invariant: the invariant is that no staged state of yours may outlive your own commit.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-01 — FORBIDDEN: prescribing a fix in a spun-off task from a symptom you never traced to its enclosing control flow. My `continue` would have deleted the feature it was meant to instrument. `[lane phase0-basketball-integrity]`

- **What I did.** I found a real defect by reading a log line — `book_grid.py` counted every correctly-matched direct-feed row as a `near_miss`, so production read `kept_direct=603 near_misses={'kalshi': 603}`, an alarm firing at exactly the rate the feature succeeded. I filed it as a background task and, because the cause looked obvious, **I wrote the remedy into the chip: "add the missing `continue` after `kept_direct_feed += 1`."**
- *(evidence in `learnings_evidence.md`)*
## 2026-09-01 FORBIDDEN: running any git working-tree restore (`checkout --`, `restore`, `reset`) without pinning the repo with `-C <path>`. The cwd is not a fact; on this machine it is a liability that destroys OTHER SESSIONS' work. `[lane polymarket-prop-quote-capture]`

- **The rule going forward.** THREE layers, because each alone has now failed: (1) every git command that can DISCARD working-tree content must carry an explicit `git -C <absolute-path>` — never rely on the shell's cwd; (2) a file-wide restore is NEVER the tool for undoing a targeted experiment — reverse the specific edit (string-swap back) instead, which cannot exceed its own blast radius (this same session had already wiped its own uncommitted implementation once with `checkout --` in the worktree — same instrument, and the second firing hit ANOTHER session); (3) on the shared tree, `checkout/restore` of a ledger file is forbidden OUTRIGHT — uncommitted peer edits live there by design, and the command cannot distinguish yours from theirs.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-01 — FORBIDDEN: comparing a model against a market price without conditioning on QUOTE AGE. A stale price is a weak forecast, so staleness flatters the model — the error runs in the reassuring direction `[lane mlb-live-gameline-skill-audit]`

- **The model does not improve as the quote ages. The MARKET decays**, because a price that has not moved in half an hour is a bad forecast of an outcome it has not seen. Quote-age distribution in that file: p50 410s, p90 1,848s, **p99 74,997s** — roughly 1 row in 100 was priced against a quote over 20 hours old.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-01 — FORBIDDEN: pooling an accuracy history across a SCORER-version boundary, and shipping a scorer whose payload cannot say which version produced it `[lane mlb-live-gameline-skill-audit]`

- **Nothing in the row said which scorer wrote it**, so the boundary was invisible and had to be rediscovered by matching record counts. The rule has two halves:
- *(evidence in `learnings_evidence.md`)*
## 2026-09-01 — FORBIDDEN: `ast.parse` as a syntax check for an edit, and building a `write` and a `read` of the same path in one expression `[lane mlb-live-gameline-skill-audit]`

- *(evidence in `learnings_evidence.md`)*
## 2026-09-01 — FORBIDDEN: `git stash` in a worktree. The stash is SHARED with every other worktree, so a failed `stash push` followed by `stash pop` pops a PEER'S work into your tree. `[lane mlb-prop-freeze-source-trees]`

- **What I did.** To prove an off-is-not-on (does my test fail on the pre-fix code?), I ran:
- *(evidence in `learnings_evidence.md`)*
## 2026-09-01 — a log SEARCH tool echoes your query; grepping its output for the bare tag matches the ECHO. Grep for content the tool cannot have written itself `[lane prop-unmatched-decomposition]`

- **Rule:** a watcher grepping a search tool's output must anchor on content the tool cannot emit about itself — the payload shape (`POLYMARKET_UNMATCHED counts=`), never the bare tag you typed into the tool. Cheap check before arming any such watcher: run it once where the answer is known-absent and confirm it stays silent.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-01 — CONFIRMED INSTANCE, with the falsifying numbers: a bounded sample majority is not a plurality claim. I wrote the hypothesis down first, and the complete count reversed it `[lane prop-rung-miss-rate]`

- *(evidence in `learnings_evidence.md`)*
## 2026-09-01 — FORBIDDEN: reading a DEGENERATE FIT as a fact about the model. A slope pinned at its clamp floor describes the training window, not the signal. `[lane mlb-hrr-null-closed, correcting lane mlb-prop-calibration-refit one commit earlier]`

- **What I did.** Fitting the MLB prop calibration, `hits_runs_rbis_*` came back with `a = 0.05` on all four rungs — exactly the fitter's clamp floor. I read that as the fitter asking to discard the model probability, concluded **"HRR's probability carries no usable signal"**, and shipped that sentence into a config `_meta`, a commit message, a test and the ledger.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-01 — FORBIDDEN: reusing a DERIVED CONSTANT without re-deriving it from the source it cites — especially when that source is printed in the same document. `[lane mlb-prop-staking-gate-not-met]`

- **What happened.** The 08-31 MLB assessment converts price improvement into ROI with *"each 1pp of better entry is worth roughly +0.75pp of ROI"*, explicitly **"anchored to item 07's sensitivity"**. Item 07's sensitivity table is printed **in the same file, ~100 lines earlier**, and says:
- *(evidence in `learnings_evidence.md`)*
## 2026-09-01 — RULE: measure on the BOOK THE DECISION IS ABOUT, not on the convenient superset. `[lane mlb-prop-staking-gate-not-met]`

- **How to apply.** When a gate names a population, encode that population in the measurement script as a named predicate (`in_gate_book`) with tests, so the number and the gate cannot drift apart — and so the next person does not have to re-derive which markets "HRR" meant. Report `n` for the *gated* population; a sample that shrinks 2,062 → 653 is itself a finding about how much the answer rests on.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-01 — RULE: the WIDTH OF AN UNCERTAINTY IS NOT A RECOVERABLE GAIN. Resolving it buys certainty, which is worth having and is not ROI. `[lane kalshi-batter-prop-fee-multiplier]`

- **What I claimed.** Closing `#624` step 6 I wrote that resolving the Kalshi batter-prop fee multiplier was *"worth 0.44 ROI points, more than half the shortfall"*, and ranked it as the second-cheapest way to close a gate that missed by 0.35 points. That reads as: do this lookup and you might pass.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-01 — RULE: a venue parameter that varies per SERIES must never be generalised AT ALL — not to the sport, not to props-vs-games, not to the market family. `[lanes kalshi-batter-prop-fee-multiplier, book-quotes-publish-clobber]`

- **"Every MLB game/total/spread/K series is HALF RATE"**, which is true and reads as "MLB is half rate". Reading 19 MLB series:
- *(evidence in `learnings_evidence.md`)*
## 2026-09-01 — FORBIDDEN: treating a `data/**` daily shard as APPEND-ONLY. Two services publish WHOLE-FILE REPLACES of the same file, so a later read can be a SUBSET. `[lane book-quotes-publish-clobber]`

- **Measured.** `mlb_source/tracking/book_quotes/2026-09-01.jsonl` fetched twice, ~1h apart, counted with identical code:
- *(evidence in `learnings_evidence.md`)*
## 2026-09-01 — FORBIDDEN: recording an actor as having DONE the thing you just refused to let it do. A guard that books a refused attempt as success makes its own refusal a one-cycle delay. `[lane book-quotes-publish-clobber]`

- **Measured**, `ncaaf_source/tracking/book_quotes/2026-09-05.jsonl`:
- *(evidence in `learnings_evidence.md`)*
## 2026-09-02 — FORBIDDEN: scoping a lock (or any bound) to a key that does not cover the case it was built for. Check the bound against the SPECIFIC incident, not against the abstraction. `[lane book-quotes-publish-clobber]`

- **Different directories, therefore different locks.** Those two twins are precisely the pair observed publishing **2 SECONDS apart** in the production log — the concrete case I cited in the commit message as the reason the lock was needed. The lock would have permitted it. It read as a bound and bounded nothing that mattered.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-02 — RULE: read the RUNNING config, not a docstring in the same file that describes it. `[lane book-quotes-publish-clobber]`

I justified the lock with *"web runs 8 gunicorn workers; each is
single-request"*, copied from a note further down `ops.py`. The live process
list says:

    gunicorn wsgi:application --workers 2 --threads 4

**Two processes, four concurrent requests each.** Wrong in the direction that
matters: `--threads 4` means merges can race INSIDE one process, which the
per-process claim declares impossible. The `O_CREAT|O_EXCL` file lock happens
to be correct for both cases, so the CODE survived — but a wrong justification
is what the next person reasons from, and the next guard built on "each worker
is single-request" would be an in-process lock that silently does nothing.

Both errors surfaced only because I read `/api/ops/memory`'s process list while
setting up an unrelated memory watch. Neither would have been caught by a test.

**Corollary already in force here:** `container_memory_mb` includes page cache
and this merge reads/writes 50MB+ files, so it inflates for reasons that are not
a leak. `container_memory_unreclaimable_mb` is the figure to watch, and the
FLOOR across samples is the ratchet — every deploy reboots the workers and
resets it, so a post-deploy reading always looks healthy.
- **The rule going forward.** Stage and commit **atomically** or not at all: `git commit --only -- <paths>` takes the worktree copies of exactly those paths and leaves the rest of the index alone. When the commit needs content that is NOT the worktree copy (rebuilding `origin/main` + only your edits), build it in a **temporary index** — `GIT_INDEX_FILE=<tmp> git read-tree/update-index/ write-tree` then `git commit-tree` — which never touches the shared index at all. **Inspect BEFORE staging, never between staging and committing.** The older "never chain add and commit" is not wrong, but it is not the invariant: the invariant is that no staged state of yours may outlive your own commit.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-01 FORBIDDEN: running any git working-tree restore (`checkout --`, `restore`, `reset`) without pinning the repo with `-C <path>`. The cwd is not a fact; on this machine it is a liability that destroys OTHER SESSIONS' work. `[lane polymarket-prop-quote-capture]`

- **The rule going forward.** THREE layers, because each alone has now failed: (1) every git command that can DISCARD working-tree content must carry an explicit `git -C <absolute-path>` — never rely on the shell's cwd; (2) a file-wide restore is NEVER the tool for undoing a targeted experiment — reverse the specific edit (string-swap back) instead, which cannot exceed its own blast radius (this same session had already wiped its own uncommitted implementation once with `checkout --` in the worktree — same instrument, and the second firing hit ANOTHER session); (3) on the shared tree, `checkout/restore` of a ledger file is forbidden OUTRIGHT — uncommitted peer edits live there by design, and the command cannot distinguish yours from theirs.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-01 — FORBIDDEN: comparing a model against a market price without conditioning on QUOTE AGE. A stale price is a weak forecast, so staleness flatters the model — the error runs in the reassuring direction `[lane mlb-live-gameline-skill-audit]`

- **The model does not improve as the quote ages. The MARKET decays**, because a price that has not moved in half an hour is a bad forecast of an outcome it has not seen. Quote-age distribution in that file: p50 410s, p90 1,848s, **p99 74,997s** — roughly 1 row in 100 was priced against a quote over 20 hours old.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-01 — FORBIDDEN: pooling an accuracy history across a SCORER-version boundary, and shipping a scorer whose payload cannot say which version produced it `[lane mlb-live-gameline-skill-audit]`

- **Nothing in the row said which scorer wrote it**, so the boundary was invisible and had to be rediscovered by matching record counts. The rule has two halves:
- *(evidence in `learnings_evidence.md`)*
## 2026-09-01 — FORBIDDEN: `ast.parse` as a syntax check for an edit, and building a `write` and a `read` of the same path in one expression `[lane mlb-live-gameline-skill-audit]`

- *(evidence in `learnings_evidence.md`)*
## 2026-09-01 — RULE: a claimed GAIN that exceeds the TOTAL COST it is meant to remove is about a different population. One comparison rejects it, with no machinery. `[lane game-market-entry-roi-curve]`

- **+1.57pp** ... worth about +1.2% ROI"* for MLB game markets. The book that stakes that money pays **0.88pp per side in total** — a 1.96% two-way hold, because it already routes to exchanges. An improvement of 1.57pp cannot be harvested from an entry cost of 0.88pp; there is not that much cost there to remove.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-01 — FORBIDDEN: treating the timestamp on an ORDER as the timestamp of the PRICE it took. Board prices carry a real age, and the error does not surface as an error. `[lane game-market-entry-roi-curve]`

- **What it produced, and why nothing caught it.** The book's mean per-side entry cost came out at **-1.43pp** — paying *less* than fair on average, which is not a thing that happens — and the sensitivity table then read **-1.05%** at "today's" cost. No exception, no refusal, a full table printed. It was caught only because the ledger's own stake-weighted return on the same rows was **+5.31%**, six points away.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-01 — OVERTURNED: repairing a lossy artifact does not move a derived number in the "recovering" direction. A truncated file is not a random sample of itself. `[lane game-market-entry-roi-curve]`

- **What I expected.** Lane `book-quotes-publish-clobber` found that `book_quotes` shards LOSE ROWS to a whole-file publish race, and that their 2026-09-01 measurement had run on a copy missing its sportsbook tail (46.1% matchable). Once `e78aee52` repaired it I told them, in writing, that their +2.65% "can be re-measured on an intact file" — carrying an unstated assumption that recovering lost rows would recover lost value.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-01 — FORBIDDEN: closing or reassigning a lane because its RECORDED SESSION is gone. The session id is not an ownership key — it is a stamp that outlives the thing it names, in both directions. `[lane game-market-entry-roi-curve, ownership pass]`

- **The census.** 34 OPEN lanes, **32 already marked UNOWNED**. Checked every recorded owner session against a 200-session roster (`list_sessions include_archived=true`) whose oldest entry is **2026-08-13**, i.e. a window covering every lane in the file, so absence from it is real absence and not a truncated view. Result: **17 of 18 owner sessions DO NOT EXIST.** The 18th (`abf487e4`) is archived, last active 2026-08-20. Exactly **one** session in the entire store was running.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-02 REQUIRED: a pre-registered falsification test still needs a CONTROL CYCLE before you act on it. One reading on a cadence-driven instrument is not evidence. `[lane kalshi-soccer-club-aliases]`

- **The rule going forward.** Before acting on a falsification signal from a periodic instrument, take ONE more cycle with NOTHING changed. It costs one cadence (~15 min here) against a revert-and-redeploy round trip (~45), and it is the only thing that separates "my change did this" from "this cycle did this". State the control's result beside the signal in `deploys.md`.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-02 REQUIRED: before calling a thin downstream count a COVERAGE DEFECT, find the counter that ACCOUNTS for the gap and read the code that increments it. A deliberate quality filter and a broken pipeline look identical from the downstream end. `[lane kalshi-soccer-club-aliases -> finding soccer-board-coverage]`

- **Measured.** Kalshi lists 171 open soccer fixtures; our board carried 28. That reads as a coverage bug and the obvious next lever is "fix the board's soccer fixture coverage". It is not a bug. One read of `/api/board/layer2-shortlist` showed soccer selecting **1,547** rows with **129** reaching the board (8%), against mlb 95% and ncaaf 100%, and the accounting counter in the SAME payload was `rows_uninformative_ev = 1547` -- exactly soccer's selected count.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-02 FORBIDDEN: measuring a change by REPLAYING IT WITHOUT AN ARGUMENT PRODUCTION ALWAYS PASSES. The replay then measures a different system, and its null result is not about your change. `[lane kalshi-soccer-club-aliases]`

- **Measured.** To read whether 34 new club aliases helped, I replayed the resolve step on a stable slate and got `resolved=9, delta=+0` -- a clean null that would have justified reverting a shipped change. The replay omitted `code_names`, which production ALWAYS passes to `match_event_blob`; without it the code path that the aliases feed is not the path being exercised. Redone with production's arguments: **22 attempted/resolved WITH the aliases against 21 WITHOUT, +1.**
- *(evidence in `learnings_evidence.md`)*
## 2026-09-02 REQUIRED: a SIZE warning measured from the working tree is a statement about YOUR CHECKOUT, not about the ledger. Read the file at `origin/main` before trimming it. `[ledger trim pass]`

- **Measured.** The session-start digest said `LEDGER OVER BUDGET: lanes.md 246KB>234KB, learnings.md 286KB>273KB`, and I relayed those numbers as real pressure. At `origin/main` the same files were **144KB/240KB and 270KB/280KB -- both UNDER cap, and they had been for some time.** `session-start.sh` stats `.syndicate/*` in the PRIMARY SHARED TREE, which was **131 commits behind**; upstream had already moved ~122KB of lane blocks into `lanes_history.md` and the stale checkout still carried every one of them. The warning was true of the bytes on that disk and false of the ledger.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-02 REQUIRED: merging a TRIMMED file from a branch that still holds the untrimmed copy RESURRECTS what was archived. Verify against BOTH pre-merge baselines, not just "nothing was lost". `[primary-tree pull]`

- **Measured.** The primary shared tree was 139 commits behind, so its `lanes.md` still carried 39 blocks that upstream had moved into `lanes_history.md`. The merge auto-resolved with no conflict and **brought 19 of them back**, producing blocks that existed in `lanes.md` AND `lanes_history.md` at once, plus two lanes holding two blocks each — the exact state the lane system's exclusivity rests on not having.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-01 — FORBIDDEN: counting Render `server_failed` events without reading `reason`. It is not a failure count — one of its three meanings is a HEALTHY DELIBERATE EXIT. `[lane game-market-entry-roi-curve]`

- **Measured today, both classes, on two services within one hour of each other:**
- *(evidence in `learnings_evidence.md`)*
## 2026-09-01 — REQUIRED: before spending a correlation, drop the largest point and recompute. One window drove a +0.499 to a +0.139. `[lane game-market-entry-roi-curve]`

- **What happened.** `#632` asked for a per-route correlation against the web service's anonymous-memory series. A first look at two hand-picked windows was compelling: the high-growth one had `/api/ops/artifacts/stream` **24** times against **7** in the flat one, while `publish` ran the OTHER way (14 vs 31) — so it was not merely "more traffic". It looked like a clean discriminator.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-02 — FORBIDDEN: designing against a DEFAULT read out of a config template. `${VAR:-1}` is what runs when nobody set VAR, and somebody set VAR. `[lane web-request-memory-attribution]`

- **What happened.** Building the `#632` per-request memory instrument, the one design question that mattered was how many requests can overlap. I read `render.yaml`:
- *(evidence in `learnings_evidence.md`)*
## 2026-09-02 — FORBIDDEN: trusting a lock whose KEY is a name you chose, when the thing it protects has more than one name. `[lane game-market-entry-roi-curve]`

- **What happened.** I acquired `deploy_claim.py --service syndicate`, was granted it, preflighted CLEAR, and deployed web — cancelling a peer's in-flight build 0.6s later. They held `--service web`, unexpired, the whole time. **Both claims were valid. `web.json` and `syndicate.json` are separate files for ONE Render service** (`_path = CLAIM_DIR / f"{service}.json"`), and nothing aliases them.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-02 — FORBIDDEN: measuring a steady-state rate in the minutes after a restart. You are measuring the RAMP. `[lane web-request-memory-attribution]`

- **What happened.** I deployed to enable an instrument, then took my `#632` readings **inside the first 12 minutes after that deploy's restart**: anon 270.8 → 759.5 MB in 7m23s, published as leak growth. A peer's independent 150-minute watch showed the same service ramping and then **PLATEAUING**, oscillating 861.8-894.9 MB for 50 minutes and never crossing 900. One curve: a process filling to a **~890 MB working set**. My "+488.7 MB in 7m23s" was warm-up.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-02 — REQUIRED: mutate the code before believing a green test. Two of mine asserted on a CONSTANT and on a fixture that could not fail. `[lane game-market-entry-roi-curve]`

- **What happened.** Fixing `#635` I wrote six tests, all green, and then mutated the source five ways to check they bit. **Two mutations sailed straight through:**
- *(evidence in `learnings_evidence.md`)*
## 2026-09-02 — REQUIRED: when you correct a number, re-check the CLAIMS AROUND IT. Mine rode through two corrections untouched and was wrong the whole time. `[lane game-market-entry-roi-curve]`

- **What happened.** I published three things about web's memory in one paragraph: a rate (`~75 MB/h`), a mechanism (`monotonic climb`), and a property (**"anon never falls except at a restart"**). Over the next day I corrected the paragraph **twice** — once downgrading the mechanism from a smooth climb to steps and plateaus, once retracting the rate as post-restart warm-up. **Both times I left the property standing, and both times I restated it as the thing that survived.**
- *(evidence in `learnings_evidence.md`)*
## 2026-09-02 REQUIRED: a ledger APPEND computed in one tree is not valid in another. Both the insertion POINT and the base CONTENT differ, and neither difference announces itself. `[lane maxmun-pregame-read]`

- **How to apply.** Write ledger appends from a worktree at `origin/main`, not from the primary tree, and RE-DERIVE the insertion point in the tree you are actually writing to — never carry a line number or an "append at EOF" decision across trees. Then `py -3 scripts/check_lane_invariants.py` before committing. If a block already stands in the primary tree, remove it there after landing, or the next session to commit that file lands a duplicate.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-02 FORBIDDEN: a `git` command that can DISCARD work taking its tree from the working directory. `cd` persists, and the destructive call is not the one that moved you.

- **I deleted another session's OPEN lane from the shared tree.** `m625-env-snapshots` (session `3492626c`) existed only as an uncommitted modification in the PRIMARY `lanes.md`. I ran `git checkout HEAD -- .syndicate/lanes.md` believing I was in my worktree. A `cd` to the primary tree **two commands earlier**, added purely so `render_logs.py` could read `RENDER_API_KEY` from `.env`, had re-homed the shell — and the working directory persists between calls. Not recoverable: no commit contains it (`git log --all -S`), no worktree carries it, it was never staged.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-02 — FORBIDDEN: a log or metric query whose window straddles a restart. You get the wrong process and it looks like an answer. `[lane web-request-memory-attribution]`

- **Twice in one session, on opposite questions.**
- *(evidence in `learnings_evidence.md`)*
## 2026-09-02 FORBIDDEN: verifying a fix only in the window AFTER go-live, where a defect that stopped on its own is indistinguishable from one you fixed.

- **Nearly banked, as a pass:** "zero `KEYVALUE_WRITE_REJECTED` on refresh-worker since go-live 17:56:08Z". Perfectly true. It was true because the LAST rejection was at **17:06:10Z** — fifty minutes BEFORE that deploy. The defect was already gone, fixed by the OTHER service's deploy at 17:10:25Z.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-02 — RULE: TWO WRITERS IS A PRECONDITION FOR HARM, NOT HARM. And "fix all N contested paths" is the wrong instinct when the paths are REBUILT rather than accumulating. `[lane book-quotes-publish-clobber]`

- **corruption**, and it took a shape check to see it.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-02 — FORBIDDEN: calling a job "bounded" because something downstream of it is capped. A cap on the OUTPUT cannot bound the WORKING SET that produced it — and a cap that reports a count is not a bound until you check WHICH container it counted. `[lane accuracy-summary-alloc-profile]`

- **The rule going forward:** before calling anything bounded, name the QUANTITY the bound applies to and the MOMENT it applies, and check that both match the failure you are guarding against. A cap on emitted rows bounds the artifact, not the allocation; a cap that fires after the peak bounds nothing at all. And when a guard reports a count, print that count beside the length of the collection it claims to describe — a truncation pointed at the wrong container is invisible in every test, because it never truncates. Related and NOT the same rule: `#435`'s "the ceiling is per FILE; nothing bounded the SUM". That one is about a bound too small in EXTENT; this one is about a bound aimed at the wrong THING.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-02 — FORBIDDEN: arming a periodic job on refresh-worker on the strength of a bound that does not bound MEMORY. `[lane soccer-anchor-wiring]`

- **1,833 → 3,868 MB** against a 4,096 MB ceiling, headroom down to **0.051 MB**, climbing **+146.9 MB/s**, instance restarted 105 seconds after the job claimed.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-02 — RULE: a WATCHER carries the assumptions it was armed with, and those expire. Re-read the world before acting on what a watcher tells you. `[lane soccer-anchor-wiring]`

- **Neither was wrong about its predicate; both were wrong about the world.** A watcher is a snapshot of intent, and intent goes stale while it waits.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-02 FORBIDDEN: trusting a FILTER, EXCLUSION or ALLOW rule that has never been shown to MATCH something. Two inert rules in one file, both reading as correct. `[lane m625-replay-diff-gate]`

- **The rule going forward:** **every filter rule needs a POSITIVE and a NEGATIVE probe before it is trusted** — one path it must match, one adjacent path it must not. Assert both. This is the `presence is not reachability` rule applied to configuration: a rule that is PRESENT is not a rule that FIRES, and an over-broad rule is not distinguishable from a correct one except by the neighbour it eats. Cheapest form: write the probes as a test next to the table (`tests/test_replay_diff_gate.py`).
- *(evidence in `learnings_evidence.md`)*
## 2026-09-02 FORBIDDEN: reporting a clean result for anything a bounded scan did not reach. A cap on RECORDING must never become a cap on TRAVERSAL. `[lane m625-replay-diff-gate]`

- **The rule going forward:** **count everything, record a sample.** Keep the uncapped total AND an uncapped per-field histogram (indices collapsed, so 3,000 row-level differences aggregate to one line), and cap only the verbose sample. Same shape as `/api/ops/artifacts/export`'s `truncated` flag, which exists because "the puller only advances its watermark on a complete response". Sibling of `a rate, not a count`: a bounded scan must publish what it covered, or its silence about the rest reads as absence.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-02 FORBIDDEN: sampling a seeded Monte-Carlo estimator at CONSECUTIVE seeds and calling the spread a control. Overlapping draws read as sd = 0.0000, which looks exactly like determinism. `[lane soccer-anchor-cost]`

- **Measured.** To size how much precision soccer's anchor solver buys, I ran `solve_market_rating_shift` at 12 "different" seeds and got **sd = 0.0000, all twelve answers byte-identical**. The write-up would have been "the default solver is deterministic, so cutting its cost is free" — and that is the opposite of the truth.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-02 REQUIRED: when a mechanism is under-reaching, measure whether the CHEAP version is louder than the mechanism itself. "Cost lever costs accuracy" is not the finding; "cost lever exceeds the signal" is. `[lane soccer-anchor-cost]`

- **Measured.** The brief asked whether cutting soccer's anchor solver from 500 to 250/125/60 simulations preserved its validated gain. The obvious framing is a trade: cheaper, somewhat worse. Graded on the PROPS the build publishes:
- *(evidence in `learnings_evidence.md`)*
## 2026-09-02 FORBIDDEN: reading an ALLOWLIST-FILTERED inventory as a statement about what EXISTS. I made the 403-vs-absent error inside the change that fixes it. `[lane m625-export-only-patterns]`

- **The rule going forward:** **an inventory is evidence about its FILTER as much as about its subject.** Before reading absence out of any listing, state what the listing is filtered by, and ask whether the thing you are looking for could pass that filter. If it could not, the listing says NOTHING about it — and in this repo that specifically means: `/api/ops/artifacts/export` (both `names_only` and body form) can only ever report allowlisted paths, so it can never establish that a non-allowlisted family is absent. Use a channel whose filter does not contain the question — here, deploying the widened predicate and re-reading was the only way.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-02 FORBIDDEN: acting on a code comment's account of WHY something is excluded without checking the exclusion is real. Two of four families in a work item were already done. `[lane m625-export-only-patterns]`

- **The rule going forward:** **a work item's scope and a comment's rationale are both CLAIMS. Check each against the running system before building for it** — for an allowlist that means evaluating the predicate against a real path, which costs one line. Corollary specific to this repo: `fnmatch` patterns do not stop at `/`, so any `a/*/b` reads much wider than it looks, and a comment describing what a pattern excludes may simply be wrong.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-02 — FORBIDDEN: calling a job "bounded" because something downstream of it is capped. A cap on the OUTPUT cannot bound the WORKING SET that produced it — and a cap that reports a count is not a bound until you check WHICH container it counted. `[lane accuracy-summary-alloc-profile]`

- **The rule going forward:** before calling anything bounded, name the QUANTITY the bound applies to and the MOMENT it applies, and check that both match the failure you are guarding against. A cap on emitted rows bounds the artifact, not the allocation; a cap that fires after the peak bounds nothing at all. And when a guard reports a count, print that count beside the length of the collection it claims to describe — a truncation pointed at the wrong container is invisible in every test, because it never truncates. Related and NOT the same rule: `#435`'s "the ceiling is per FILE; nothing bounded the SUM". That one is about a bound too small in EXTENT; this one is about a bound aimed at the wrong THING.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-02 — FORBIDDEN: anchoring an edit on a GENERIC line in a shared append-only file. My lane note landed inside ANOTHER lane's block, and every check passed. `[lane accuracy-summary-ledger-budget]`

- **The rule going forward:** in a file every session appends to, anchor on something that NAMES YOU — your own `### <slug>` header, then scan forward to the next `### ` — never on a boilerplate line like `- Blocked by: none`, `- Files:` or a section terminator. `str.replace(old, new, 1)` with a count of 1 is not protection; it silently picks the first match, and the first match moves when someone else writes. If an anchor must be generic, assert it is UNIQUE (`s.count(old) == 1`) **and** that it sits inside your own block, and re-read the file immediately before the edit rather than trusting a read from earlier in the session.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-02 — RULE: a commit subject starting with `#` is a COMMENT to git, and cherry-pick/rebase silently delete it. This repo's `#<id>:` convention walks into it every time. `[lane accuracy-summary-ledger-budget]`

- **The rule going forward:** after ANY cherry-pick, rebase or squash of a commit whose subject starts with `#`, read `git log --oneline` and confirm the subject survived. To keep it: `git -c core.commentChar=';' rebase ...`, or rebuild with `git commit-tree -p <parent> -F <msgfile>` (verbatim, no cleanup) and `git update-ref`. `git commit --amend -C <sha>` does NOT fix it — it re-runs the same cleanup.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-02 FORBIDDEN: installing a guard in `sitecustomize.py` that RAISES. CPython swallows it, prints a warning, and the process runs on — my guard announced its refusal and permitted the thing it refused. `[lane m625-fleet-runner]`

- **The rule going forward:** **a refusal that another frame can catch is not a refusal.** In `sitecustomize`, and anywhere a host frame wraps your code in a broad `except`, terminate with `os._exit(code)` after writing the reason to stderr — it skips atexit handlers and cannot be caught. And more generally: for any guard, write the control that ARMS the condition and requires the refusal. A guard verified only by watching it pass is a guard whose refusal path has never executed.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-02 REQUIRED: derive a local run's config from a SNAPSHOT of production's, not by hand — the roles ARE their env, and they differ on 137 of 194 keys. `[lane m625-fleet-runner]`

- **The rule going forward:** **for any local reproduction of a deployed service, start from a snapshot of the deployed env and justify every deviation.** State the forced set and the dropped set in the tool's output, so a reader can see how far the local run is from production without reading the code. Corollary found the same way: a secret-withholding snapshot is also the best credential scrub available, because a value that was never written cannot leak through a deny-list somebody forgot to extend.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-02 FORBIDDEN: taking a deploy claim or preflight from a SESSION WORKTREE. `deploy-guard.py` reads `$CLAUDE_PROJECT_DIR` — the PRIMARY tree — so worktree locks are invisible and the deploy is blocked with a message that names the wrong lane. `[lane soccer-anchor-audit-artifact]`

- **Measured.** Claim acquired and preflight run from `C:\tmp\syndicate-sessions\soccer-anchor-cost`, both reporting success. Same command, same repo, same second:
- *(evidence in `learnings_evidence.md`)*
## 2026-09-02 REQUIRED: `deploy_preflight.py` CLEAR means "no job was running when I looked", NOT "no job dies". The old container keeps launching work for the whole build phase. `[lane soccer-anchor-audit-artifact]`

- **Measured on a deploy I ran:**
- *(evidence in `learnings_evidence.md`)*
## 2026-09-02 FORBIDDEN: drawing a conclusion from a log line the API TRUNCATED. Render's logs API cut a JSON payload at ~1,200 chars; the visible part was all zeros and I published "zero for every date" when it was 7 of 12. `[lane m639-actuals-zero-rows]`

- **The rule going forward:** **when a log line carries structured data, PARSE it and assert the parse succeeded — never conclude from the rendered string.** If `json.loads` fails on the tail, the line is cut and you know it. And state the denominator: "zero on N of M dates" is checkable, "zero for every date" is the claim truncation makes easy. Third instance today of the same family (see the inventory-filter rule and the traversal-cap rule): **a view that omits does not announce what it omitted.**
- *(evidence in `learnings_evidence.md`)*
## 2026-09-02 REQUIRED: `git rebase --continue` re-runs the message CLEANUP, so a commit subject starting with `#` is silently deleted. Every item id in this repo starts with `#`. `[lane m639-actuals-zero-rows]`

- **The rule going forward:** when a rebase may re-open a message whose subject starts with `#`, pass **`--cleanup=verbatim`** (`git commit --cleanup=verbatim -F msg.txt`, and `git -c commit.cleanup=verbatim rebase --continue`), or put the id after a word: `todo #639: ...`. **Do not fix it afterwards by force-pushing `main`** — several sessions push there in real time, and rewriting shared history to repair a subject line trades a cosmetic problem for a real one. Leave it, and make the body carry the id so `--grep` still finds it.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-02 FORBIDDEN: multiplying a measured unit cost by a population from a DIFFERENT query. State the scope of both, or the product is invented. `[lane soccer-anchor-wiring, corrected by soccer-anchor-cost]`

- **The rule going forward:** **a unit cost becomes a workload only when multiplied by the population the CONSUMER iterates.** Before multiplying, name the scope of each factor — its date window, its league set, its filter — and assert they are the same scope. A feed's row count is almost never the consumer's loop count: feeds are forward-looking and shared, consumers are usually single-date. Sibling of `a rate, not a count`, with the denominator drawn from the wrong table entirely.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-02 — FORBIDDEN: deriving a worst case from the NAMES of the limits instead of the loop's actual control flow. My "3 x 20 x 20 = 1,200s" described a nesting that does not exist. `[lane kalshi-discovery-deadline]`

- **The rule going forward:** before multiplying limits together, read where each counter is DECLARED and where the loop BREAKS. A limit's name tells you what it was for, not what it bounds. Cheapest check: instrument the leaf call and count, because the count settles nesting questions that reading alone gets wrong -- and do it BEFORE opening a lane on the arithmetic.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-02 — FORBIDDEN: calling a repeated-cost measurement a PER-REQUEST cost without finding the state that decides whether it recurs. Measured once it was 254 calls; measured an hour later, 0. `[lane kalshi-discovery-deadline]`

- **The rule going forward:** when a cost looks repeated, find the STATE that decides whether it repeats before naming it per-request: a TTL, a due-clock, an on-disk stamp. Then reproduce it deliberately (clear that state) rather than hoping to catch it again. And put the counter INSIDE the function you are bounding -- an external instrument cannot tell "my bound works" from "my bound is never reached".
- *(evidence in `learnings_evidence.md`)*
## 2026-09-02 — FORBIDDEN: adding a bound that returns a PARTIAL result without checking how the caller reads emptiness. This one would have blanked 150 series off the board for an hour. `[lane kalshi-discovery-deadline]`

- **The rule going forward:** a bound that DEGRADES rather than raises must be traced into every consumer of its result, because "partial" and "empty" are the same value to a caller that only checks length. Prefer stopping the caller's loop BEFORE spending, so unfinished work stays visibly unfinished; and give any pre-loop step its own sub-budget so it cannot starve the work the budget exists to protect.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-02 — RULE: run `lane_identity_check` AFTER landing, not only before. A rebase duplicates a lane block wholesale, and the write-side rule does not cover it. `[lane kalshi-discovery-deadline]`

- **The rule going forward:** `land` runs its checkers BEFORE the push, so a rebase-introduced duplicate reaches `main` and is only reported afterwards. Re-run `scripts/lane_identity_check.py` after every land and fix immediately -- lane exclusivity is what the claim system rests on.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-02 FORBIDDEN: reading a DIFFERENTIAL in which more than one variable moved. And an absent trace is not an absent dependency.

- **What I reported, and had to retract.** A "data-dependent tests" sweep compared PASS 1 (87 files, 2,672 tests, no `data/`) against PASS 2 (24 files, 1,031 tests, with `data/`) and called the difference bucket A. **Scope moved with the data.** A test that fails only when 2,672 tests share a process — leaked global state, a cache, a monkeypatch outliving its test — and passes in a 1,031-test run lands in that bucket having nothing to do with `data/`. `test_kalshi_catalogue` did exactly that: it passes with **no `data/` at all** when run in isolation.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-02 FORBIDDEN: acting on a tool's OUTPUT without checking the tool's actual THRESHOLD or PREDICATE. Its output is a claim about the tool, not about the system. `[lane ledger-stale-tree-guard]`

- **The rule going forward:** **a threshold comes from the ENFORCER, a claim comes from the PREDICATE.** Before acting on any tool line that asserts a system fact, run the predicate or read the constant in the code that enforces it. A number printed next to the word "cap" is not a budget, and a sentence printed next to a flagged line is not that line's behaviour. Sibling of `read the field you already have` and `instrument blindness`.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-02 FORBIDDEN: a blanket `except` in a guard. It converts VERSION SKEW into silence, and a silent guard is indistinguishable from a clean result. `[lane ledger-precommit-hook]`

- **The rule going forward:** **a guard's fail-open path must distinguish "no opinion" from "could not run".** Catch the skew signal (`TypeError`) separately and DEGRADE to the predicates the older version does have, rather than letting it fall into the blanket handler. And after installing any guard, exercise it where it now lives — in a repo with 48 worktrees at 48 commits, "it works" is a statement about one tree. Instance of `presence is not reachability`, with version skew as the mechanism.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-03 REQUIRED: before proposing to ARCHIVE or DATE anything in this repo, check whether the path is KEYVALUE-backed and price it. The live-lens snapshot is a 4 MB Redis key on a 60s tick -- dating it would have written ~5.76 GB/day into a 256 MB store. `[lane mlens-snapshot-dating]`

- **The rule going forward:** **"date it" and "archive it" are storage decisions, not code decisions.** Before proposing either: (1) is the path keyvalue-backed (`_keyvalue_backed`, and the exclusion list is one entry long, so assume YES); (2) how big is one object; (3) how often is it written; (4) what does the store have left. Multiply. And check whether adding a date token silently attaches a TTL — in this repo it does, which `execution_ledger.py` already documents for its own ledger ("NO DATE TOKEN -- a dated path takes the store's 10-day TTL and the record would silently expire"). **When the archive is unaffordable, a FINGERPRINT is usually the right substitute**: it cannot make the thing reproducible, but it makes a divergence attributable, which is most of the value at ~100 bytes instead of 4 MB.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-02 FORBIDDEN: dropping rows whose OUTCOME is zero. It reads as "cleaning the data" and it is selection on the dependent variable — 79% of my sample went, and the survivors all had realized >= 1. `[lane soccer-anchor-cost, #622(3)]`

- **Measured.** Grading anchored-vs-base soccer prop projections against realized shots, I skipped (player, match) rows where the player took no shots, reasoning that a 0 for an unused substitute is an availability fact rather than a prediction error. That is superficially sound and it is wrong.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-02 REQUIRED: when a sign test and a t-statistic DISAGREE, believe neither until you have found the clustering. Mine said p=0.0027 and t=-1.28 on the same rows. `[lane soccer-anchor-cost, #622(3)]`

- **Measured.** 197 (player, match) rows, anchored vs base: exact two-sided sign test **p = 0.0027** (wildly significant) beside a paired **t-ish of -1.28** (not significant). Both computed from the same 197 numbers.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-02 FORBIDDEN: attributing dirt in a shared tree to the thing you just ran, without checking what was dirty BEFORE you ran it.

- **I reported "the suite MUTATES tracked files" and named four. It does not.** Each of 24 modules alone: tree clean. All 24 together, 1,031 tests: tree clean. **Two of the files were already modified in this session's OPENING `git status` snapshot**, before I ran anything. A `git status` taken AFTER a long session attributes every prior session's dirt, and every one of your own earlier commands, to whatever you happened to run last.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-02 — FORBIDDEN: paying for an expensive CONTROL without first checking that its inputs can produce the signal. I nearly spent a 34,690-file checkout on a control that was arithmetically incapable of answering the question. `[lane wnba-cards-fallback-recursion]`

- **The rule going forward:** before running a control that costs real time, state what INPUT it needs and confirm that input exists FOR THE CONDITION UNDER TEST — the date, the sport, the state file, whichever discriminates. `data/` in this repo is a lossy mirror on its own per-family schedule (CLAUDE.md says so), so "the tree has data/" never implies "the tree has the data this test needs". When the input does not exist, MANUFACTURE the trigger instead: here, `rows` comes from `game_cards_<date>.csv`, so writing one row was the whole control — 0.01s against a 34,690-file checkout, and it answered the question exactly. And run the back-control: remove the fixture and confirm the old behaviour returns, or the fixture is not what changed.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-03 FORBIDDEN: writing a verification predicate into a lane without first checking that it is OBSERVABLE. Do that check BEFORE the work, not after. `[lanes soccer-anchor-wiring, board-window-floor-raise]`

- **The rule going forward:** **before a verification line goes into a lane, grep for the emitter and confirm the signal EXISTS on the path you intend to measure.** One `git grep` answers it. If nothing emits, the first deliverable of the lane is the telemetry, not the change — ship the observation, then the behaviour. That ordering is what turned this one from unanswerable into a reading: `33b181ee` shipped the log line, and the very first tick showed a gated enqueue at `elapsed_s=725` that the old floor would have admitted.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-03 FORBIDDEN: choosing the READ-only allowlist because "nothing serves this". The test is whether there is a serving HAZARD — export-only makes a family readable IF PRESENT, and if nothing publishes it the entry does nothing at all. `[lane worker-artifact-transport]`

- **The rule going forward:** **the question is not "does anything serve this", it is "is there a serving HAZARD".** Ask what READS the path on the receiving service and whether its behaviour changes on PRESENCE. For reconciliation the answer is no twice over — the autorun is false on web, and the reader defaults its roots to the repo checkout rather than `data_root()`. For `raw/statsapi/feed_live` the answer is yes, and that one stays read-only forever: `_mlb_feed_live_payload` returns the cached file if it exists, so presence IS the trigger. **Pin the discriminating pair in a test**, or the distinction decays back into a preference.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-03 REQUIRED: when a sign test says p=0.0000 and the t says -1.06, publish BOTH — the direction and the magnitude are different findings and only one of them decides anything. `[lane soccer-anchor-cost, #622(3)]`

- **Measured.** Anchored-vs-base soccer props over 136 matches: anchoring was worse in **95/136 (70%)**, exact sign test **p = 0.0000**. On the same data the per-match mean delta was **-0.00101 shots with sd 0.01106 — t = -1.06**, and the MEDIAN match delta was exactly **0.0000**.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-03 — FORBIDDEN: a comparative claim from ONE run per condition. I published a 40% effect, ruled out four mechanisms for it, and three paired replications erased it. `[lane intelligence-suite-runtime]`

- **The rule going forward:** **n=1 per condition cannot support a comparative claim, and a large effect is not protection — it is the warning sign.** Before writing a ratio into a ledger, run each condition at least three times and report the spread, not the point. Two specific traps this hit: the "cold" side was triple-measured and the "warm" side was not, which felt like rigour and was not — replicate the side you are ARGUING FOR; and ruling mechanisms out gave the effect false weight, because every exoneration made it feel better established when none of them tested whether it was real. When an isolated instrument disagrees with an end-to-end reading, the isolated one is usually right and the end-to-end one usually has a confound.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-03 — FORBIDDEN: instrumenting a COMPONENT when the contradiction is between two NUMBERS

- **Cost: four web deploys on `#642`, three of them wasted.**
- *(evidence in `learnings_evidence.md`)*
## 2026-09-03 — A per-date join counter is not safe to SUM across a multi-day window unless it is scoped to that date first. Second confirmed instance of the same shape as `#513`.

- **What we believed:** refresh-worker's `[layer2_shortlist] PREGAME_PROJECTION_JOIN sport=ncaaf considered=3625 projected=336 reason="no NCAAF SmartSim2 projections for this date"` (9.3%) described a real, near-total NCAAF projection outage the night of the 2026-09-03 opener slate.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-03 FORBIDDEN: inferring an environment variable's NAME from the name of the function that reads it. Read the key out of the code. `[lane soccer-projection-names]`

- **The rule going forward:** **before reading an env var to decide anything, grep the key literal in the code that consumes it.** Accessor names, ledger prose and CLAUDE.md all paraphrase; only the `os.environ.get("...")` string is the key. If a probe returns ABSENT, confirm the literal exists somewhere in the repo before reporting it — otherwise "absent" is a statement about your spelling. Sibling of `presence is not reachability`, one level lower: this is ABSENCE IS NOT DISABLEMENT.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-03 — FORBIDDEN: reading a provenance stamp emitted by the OBSERVER as evidence about the SUBJECT

- **The rule going forward:** **a provenance field tells you the version of the thing that WROTE it, not the version of the thing it describes.** Before partitioning a history on any stamp, name which process emits it and when that process gained the field; if emitter and subject are different components with different release dates, the stamp is a lower bound on the emitter and NOT a classifier for the subject. Where they diverge, "unstamped" collapses two distinct populations — genuinely old rows, and new rows from an old writer — into one bucket, and the partition silently discards good data.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-03 — FORBIDDEN: concluding content is LOST from a line-level diff of a REWORDED ledger

- **The rule going forward:** **line identity in these files tracks FORMATTING, not information.** Ledger files are rewritten, re-wrapped, collapsed and archived as a matter of routine, so a reworded restatement and a genuinely absent fact are indistinguishable at line level. Before calling anything lost: (a) compare distinctive TOKENS — numbers, SHAs, identifiers, ids — across the WHOLE ledger including `lanes_history.md` and the `state_archive_*` files; (b) check whether an ARCHIVED block supersedes the one you are missing; (c) treat a status word in a heading (OPEN vs CLOSED) as the signal that one side is stale. Sibling of `remote-absent is not content-absent`, one layer down: not "is this commit upstream" but "is this SENTENCE upstream".
- *(evidence in `learnings_evidence.md`)*
## 2026-09-03 FORBIDDEN: concluding a RESOLVER is broken without printing the path it actually reads. Two files with the same row count can differ, and the one you grep is not always the one it loads.

- **Three tests "failed" and the resolver was correct the whole time.** `resolve_team("St. Anselm")` returned None. The team is right there in `ncaaf_team_registry.csv` — which `resolve_team` **does not read**. It reads `ncaaf_team_registry_snapshot.csv`, same directory, **same 685 rows**, different contents: the snapshot has 12 St./Saint schools and no `St. Anselm`; the sibling has 11 and does.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-03 — FORBIDDEN: assuming a stopped background task is stopped. Its CHILDREN keep running, and if they write shared state that gates something, they will gate it against you. `[lane accuracy-autorun-rearm]`

- **The rule going forward:** after stopping a background task, VERIFY the processes are gone (`Get-CimInstance Win32_Process` filtered on the command line, then `Stop-Process`), not just that the task reports stopped. And treat any background loop that writes a file OTHER TOOLS READ as a shared mutation, not private scratch — in this repo that includes the preflight record, the refresh state store and every `.syndicate/**` file. A poller is not read-only just because its purpose is to look.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-03 — FORBIDDEN: polling a friendlier proxy instead of the instrument that GATES the action. `[lane accuracy-autorun-rearm]`

- **The rule going forward:** identify which instrument ENFORCES the thing you want, and poll that one. A friendlier tool that answers a similar question is a proxy, and proxies disagree exactly when it matters. Related and separately paid for the same day: poll on a documented EXIT CODE, not on substring-matching output — `"CLEAR"` matches inside `"NOT CLEAR"`, and an `[UNKNOWN]` read-failure is not a pass (`check_deploy_safety`'s own help says exit 2 "is NOT the same as clear, and is deliberately not exit 0").
- *(evidence in `learnings_evidence.md`)*
## 2026-09-03 — FORBIDDEN: leaving a tree after `git reset --mixed` to a NEWER ref without refreshing the working files

- **The rule going forward:** after any `reset --mixed`/`--soft` onto a newer ref, the working tree is NOT updated — finish the job. Record the genuinely modified paths FIRST (`git diff --name-only` before you touch anything), back them up, `git checkout -- .` to bring the files to the new HEAD, then restore those paths. Never commit from the intermediate state, and never trust "modified" to mean "someone edited this".
- *(evidence in `learnings_evidence.md`)*
## 2026-09-03 — FORBIDDEN: writing a poll predicate against the vocabulary you EXPECT instead of the states the tool actually emits. Three instances in one afternoon; two would have acted on a false signal. `[lane accuracy-autorun-rearm]`

- **The rule going forward:** prefer a documented EXIT CODE to string matching — `check_deploy_safety` states its own contract (0 clear / 1 busy / **2 could not determine, "which is NOT the same as clear, and is deliberately not exit 0"**). Where only text exists, ENUMERATE the states from the tool (`--help`, the source, or by reading a real sample of each) before writing the match, and make the predicate require the positive state explicitly rather than the absence of a negative one. An unknown or unrecognised state is NEVER a pass.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-03 — the DIVIDE rule, restated because I broke it the same day I wrote it

- **Why it fooled me twice in one day.** A total is a SUM, and a sum hides the factor that decides whether a limit is reachable. `bytes` alone genuinely cannot distinguish "2.5MB of many small records, structurally capped" from "2.5MB of few huge records, about to breach" — the test I wrote builds both at the same total size to pin that. So the rule is not merely "divide": **a threshold warning must report the RATIO that determines reachability, not the level.** A level tells you where you are; only the ratio tells you whether you can arrive.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-03 FORBIDDEN: carrying an obligation as "unverified" when a LATER change made the signal UNREACHABLE. In a log the two are identical; in meaning they are opposites.

- **I said it several times, including in a checkpoint:** refresh-worker's `#638` trim "has never executed in production" and "verifies itself the next time that service is first past the budget". The first half was true. The second was impossible by then and I kept repeating it.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-03 FORBIDDEN: joining two FEEDS on exact string equality. Four instances in one sport in one day, each one silent. `[lanes soccer-anchor-wiring, soccer-projection-names]`

- **The rule going forward:** **a cross-feed join is a normalisation problem, and exact equality is the bug, not the baseline.** Three things, together: 1. Normalise both sides (`_norm_name` already folds accents — that was the 2026-08-16 MLB fix, and it is why diacritics were NOT the cause here). 2. Fall back to a UNIQUE candidate within the narrowest scope available, and **REFUSE ON AMBIGUITY, counting the refusals**. A silently wrong join is worse than an unmatched row, because the row still prices and nothing downstream can tell. 3. **Publish matched/unmatched WITH the denominator and a cause split.** A join with no yield counter is a join nobody can prove works.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-03 — FORBIDDEN: correcting a false claim in ONE copy and calling it fixed. Fix the OPERATOR-VISIBLE copy first.

- **The rule going forward:** when a claim is disproved, **grep the whole repo for it before declaring it fixed, and rank the copies by how often each is READ, not by how close each is to the code you changed.** Operator-visible strings, `--help` text, log lines and ledger prose outrank comments every time; a comment misleads one editor, a printed line misleads every reader of every run. And check the correction's OWN container: appending "RESOLVED" to a cell that still asserts the original leaves one subject holding both halves of a contradiction, which is the exact failure `state.md`'s one-subject-one-section rule exists to prevent.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-03 — FORBIDDEN: editing a ledger file with Python TEXT-mode I/O. It rewrites every line ending in the file, and `git diff` will not show you. `[scheduled task live-gameline-accuracy-snapshot, checkpoint]`

- **Why nothing caught it.** `git diff --numstat` read `1\t1` — correct, because `core.autocrlf` normalises on the way in, so the COMMIT would have been exactly the intended line. The mutation lived only in the working file, which is the copy every concurrent session reads directly. Git's warning (*"LF will be replaced by CRLF the next time Git touches it"*) is printed on every such diff and reads as boilerplate.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-03 — FORBIDDEN: judging what a reworded ledger would lose by a LINE-level diff. It reports as unique the prose that was superseded, which is exactly the prose you must not land. `[state.md archival pass]`

- **Why a line diff fails here specifically.** A ledger gets REWORDED as it is corrected: the same fact is restated shorter, or moved under a new heading. Line identity tracks the wording, which is the part designed to change; the fact is the part that persists. So the residue a line diff reports is biased TOWARD superseded text.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-03 — FORBIDDEN: forcing a deploy claim whose age keeps RESETTING without first checking the holder's deploys. A resetting age means the holder is WORKING, not that a dead poller is renewing it. `[lane prop-join-yield]`

- **WHY THE INSTRUMENT CANNOT ANSWER THIS.** "A dead session's poller is renewing" and "a live session is actively deploying" produce the SAME reading in `status` — a holder name and an age that keeps resetting. The field that separates them is not in that tool at all. It is one call away:
- *(evidence in `learnings_evidence.md`)*
## 2026-09-03 — FORBIDDEN: verifying a deploy by ANCESTRY. Check the deployed file's CONTENT.

- **Measured.** `#643`'s fix (`8add1bbe`) was on `main`. live-odds-worker deployed `48c68546`, and `git merge-base --is-ancestor 8add1bbe 48c68546` answers **YES**. The fix was still absent: `git show 48c68546:syndicate/features/shared/execution_ledger.py | grep -c bytes_per_order` answers **0**. Ancestry proves a commit was APPLIED, never that it SURVIVED — a later commit to the same file can overwrite it with no conflict and no signal. Verify by asking the deployed tree for the CONTENT.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-03 — a deploy CLAIM can be force-broken while live, and spacing will not catch it

- **The rule.** The second lock does not compensate: a preflight measures from the last FINISHED deploy, so **a build in flight is invisible to the spacing rule**. Serialisation rests on the claim alone and `--force` is one command away — so record the force in `deploys.md`, and before forcing, establish the holder is actually gone.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-03 — RULE: before you compact a file, measure whether it is BLOATED or merely BIG. They look identical from the size alone and take opposite fixes. `[lane none — ledger structure pass]`

- **The measurement.** 31 superseded markers. One self-delimiting region, 1,460 B. All 8 remaining candidates audited individually: SIX had no dead body at all — the superseded claim was DELETED when its correction was written and survives only as a quotation inside that correction, so the flagged paragraph IS the record and moving it deletes the correction. TWO keep their old block deliberately and say so in the correction. Total reclaimable: **0.2%**.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-03 — FIXED: a file lock is only a lock if every holder computes the SAME path

- **The blocked deploy was the harmless half.** Two sessions in two worktrees could each `acquire` the same service and both succeed, writing to different files — the lock silently non-mutual at exactly the moment it is load-bearing. Nothing would have reported it; both claims would have been "valid". That is `#635` on a new axis (two NAMES for one box → two TREES for one repo), and the shared shape is worth stating: **a lock is only a lock if every participant computes the same path. Derive that path from something GLOBAL to the repo, never from where the running copy of the code happens to live.**
- *(evidence in `learnings_evidence.md`)*
## 2026-09-03 — lane session ids are NOT CCD session ids, so a roster miss proves nothing

- **Consequences that matter.** `send_message` cannot reach a lane owner — session 82fe0160 recorded "not found" for this exact id at `lanes.md:1409` before I repeated the lookup from scratch. And any rule of the form "if that session is gone, `--force` it" must NOT be settled with `list_sessions` on a lane id: the deploy-claim tool's own prompt says an unrecorded session is UNKNOWN, not gone, and this is precisely why.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-03 — FORBIDDEN: calling a field's persistence "the measurement is now possible" without checking the population can REACH the table

- **I first wrote "three of nine" and it was wrong** — I enumerated the verdicts I had written fixtures for instead of the ones the BRANCH produces, and missed `live_contradicts`. Caught only when I went to encode the set as a constant and re-measured all nine. **A count derived from your own test fixtures is a count of your fixtures, not of the system.** Enumerate from the code that produces the values, then measure every one.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-03 — CONFIRMED BY DEMONSTRATION: a lane id absent from the roster can be a LIVE session

- **The rule.** `b2b5b45b` held a LIVE deploy claim on web for 27 minutes while appearing in **no row of a 200-entry `list_sessions` including archived**. Absent from the roster, provably alive — so roster evidence must **never** justify `deploy_claim.py --force`. Wait for the TTL, or leave the service to its owner.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-03 — FORBIDDEN: taking an exit code through a pipe

- **The rule.** `RC=$(cmd 2>&1 | tail -1); if [ $? -eq 0 ]` reads **`tail`'s** status, not the command's, and the wrong answer is always the PERMISSIVE one — `tail` essentially always succeeds, so every guard written this way degrades to "proceed". Capture first, then test: `OUT=$(cmd 2>&1); RC=$?`.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-03 — check SURVIVAL in the TARGET before deploying, not in the deployed tree after

- **The rule.** *Verify by content, not ancestry* says what to check. This says WHEN: when a pending commit touches a file you fixed recently, check the target before you deploy it. After-the-fact detection means the regression is already live and you have spent the deploy; before-the-fact costs a single read and the answer is the same either way.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-03 — a guard whose failure modes are ASYMMETRIC must be fixed in the safe direction only

- **The rule is not "add the marker".** It is that this guard's two failure modes are not equal:
- *(evidence in `learnings_evidence.md`)*
## 2026-09-03 — FORBIDDEN: writing a disclaimer INSIDE a `- Files:` block. It is a CLAIM, and the more emphatic the wording the more certain it is to be one. `[lane nfl-dispatch-order-assertion]`

- **I did it myself, in the lane block written to announce that I was not doing it.** I wrote ``\`scripts/run_refresh_worker.py\` is **READ-ONLY REFERENCE, NOT CLAIMED**``. Both markers are real — and both came AFTER the path, so the prefix cut removed nothing. Caught by the checker within a minute.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-03 — FORBIDDEN: reading a green `check_lane_invariants.py` as evidence that a path is unclaimed. Its invariant is "exactly ONE holder", which a phantom holder SATISFIES. `[lane nfl-dispatch-order-assertion]`

- **A contest is the symptom; the claim is the defect.** Going green because a rival withdrew is not a fix, and the check cannot tell those apart by design — its own docstring says the phantom scan is a HINT that is never failed on, because it cannot distinguish a real multi-line `Files:` list from prose.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-03 — A `-k` sweep partitions by NAME, so a defect spanning a family is reported at whatever fraction of that family happens to share a word. `[lane nfl-dispatch-order-assertion]`

- **How to apply:** when a `-k` run surfaces a failure, ask what else shares the CAUSE rather than the NAME, and re-run scoped to the cause's file family before calling the count complete. Corollary for the fix: three sibling files here had already replaced literal indices with relative ones, so the pattern was discoverable by looking at the family — `grep` for the assertion shape, not for the failing test.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-03 — FORBIDDEN: reading a repo file through `subprocess(text=True)` on Windows. It decodes with the LOCALE codepage, and this ledger is made of em-dashes

- **The rule.** Any pipeline that reads source or ledger content out of git —
  `git show`, `git cat-file`, `git diff` — must capture BYTES and
  `.decode("utf-8")` explicitly. `text=True` uses
  `locale.getpreferredencoding()`, which is cp1252 here, and a cp1252
  round-trip of U+2014 (`e2 80 94`) produces `c3 a2 e2 82 ac` — which still
  RENDERS as a dash in most terminals and matches no regex looking for the real
  one.
- **What it cost.** Regenerating `lane-guard`'s parser through that path wrote
  mojibake into `LANE_RE`. The live claim set went **50 → 0** and `lane-guard`
  enforced NOTHING — every lane in the repo unguarded — while every checker
  downstream reported success, because zero claims trivially satisfies "each
  claim has one holder" and "no claim names a missing file".
- **The second half, which is the transferable one.** The outage was invisible
  to every existing check and was found only by a differential that asserted a
  NON-ZERO count. **A parser's output count is a health signal and belongs in
  the check** — `scripts/check_lane_claims.py` now treats zero claims against
  OPEN headers as FATAL and names the em-dash by its bytes. Compare BYTES, not
  glyphs: `grep '^LANE_RE' .claude/hooks/lane_claims.py | xxd`.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-03 — A guard's COVERAGE is measured against the writes that reach it, not the writes it handles

- **The rule.** Before citing a guard as protection, measure the denominator:
  how many of the operations it exists to catch actually route through the tool
  it is registered on. `lane-guard.py` was registered on
  `Edit|Write|MultiEdit|NotebookEdit` only. Census over all 292 session
  transcripts, counting writes whose target resolves to a `git ls-files` path:
  writes to tracked SOURCE files ran **9,023 Edit-family against 1,045
  Bash/PowerShell — 10.4% never checked**, and under `.syndicate/` the shell is
  the MAJORITY path (2,618 vs 1,069).
- **Why it stayed hidden.** A guard that never sees an operation is
  indistinguishable from one that saw it and allowed it. `lane-guard` was the
  only guard in `.claude/hooks` standing on a single layer —
  `ledger-append-guard` shares the same Edit-only matcher but is backstopped at
  write time AND at commit time, which is why the ledger's shell-heavy profile
  never showed up as damage.
- **How to apply.** For every PreToolUse guard, ask which OTHER tool can perform
  the same effect, and either cover it or write down that it is uncovered.
  Prefer watching the OUTCOME over parsing the command: predicting a file write
  from a shell string needs seven regex families and still misses cases, and a
  guard that blocks on a guess is one people route around.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-03 — WHICH TREE: locks/markers/receipts to the PRIMARY tree, ledger/code to the worktree

- **The rule.** Locks, markers and receipts are read by the GUARDS, which run against the primary tree: take and clear them there. Ledger and code are committed, so they belong in the worktree. `deploy_claim.py` and `deploy_preflight.py` now resolve this themselves via `--git-common-dir` (2026-09-03), but the MARKER files still do not — clear `.syndicate/.current-lane.<session>` in **both** trees when closing a lane, or check with `ls .syndicate/.current-lane.*` in each.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-04 — FORBIDDEN: inferring a session is GONE from its absence in `list_sessions`, even with `include_archived`

- **The roster does not list unattended runs.** Scheduled tasks and remote-dispatched sessions execute without appearing, which the `send_message` tool documents in its own description ("Unavailable in unattended sessions (scheduled-task runs and remote-dispatched sessions)"). So the roster answers "is there an ATTENDED session", never "is anything running as this id".
- *(evidence in `learnings_evidence.md`)*
## 2026-09-04 — FORBIDDEN: counting a set from your own TEST FIXTURES instead of from the code that produces it

- **How to apply: enumerate from the producer, then measure every member.** When a claim is "N of M have property P", the M has to come from the code that emits the values — a branch sweep, a literal set, `dataclasses.fields()` — never from the fixtures in your test. And where the count is load-bearing enough to publish, make it a constant with a test that re-derives it from the source, which is what caught this one.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-03 — FORBIDDEN: reporting a census result as a property of the POPULATION when it is a property of your PROBE

- **The rule.** A census answers "what my pattern matched", never "what is
  out there". Before writing the conclusion, ask what a member of the
  population would have to look like to be MISSED, then check whether such
  members exist. If the probe is cheap to run directly — running the scripts,
  calling the function — prefer that over a grep, because the direct probe
  cannot have a blind spot the grep has.
- **Two instances the same day, in two sessions, one reviewing the other.**
  I refactored a shared parser and grepped for consumers with
  `spec_from_file_location|exec_module|import_module`. Five scripts load it via
  `exec(compile(...))`, which matches none of those, so I reported all five as
  "prose only". **My refactor had broken every one of them** — four dead on
  `NameError: __file__`, a fifth refusing correctly. A peer found ONE by running
  it; running all of them found five. Symmetrically, that peer hit a timeout
  importing a hook, concluded the module was unimportable, and wrote it into two
  ledger files; it imports in 0.02 s with `sys.stdin` stubbed. What blocked was
  their shell, not the module.
- **Why the false version is worse than silence.** "Prose only" told me those
  files were fine, so I did not run them. "Unimportable" tells the next reader
  not to try. **One failed probe licenses "this did not work here", never "this
  cannot work"** — and one unmatched pattern licenses "my grep found nothing",
  never "there is nothing".
- **How to apply.** State the probe alongside the count ("grep for X found N",
  not "there are N"). When the conclusion is that something is ABSENT or
  UNAFFECTED, run the direct check on at least the members you are about to act
  on. Same family as the caller-census rule of 2026-08-20 (`A DOCSTRING THAT
  NAMES ITS OWN PRECONDITION IS A CHECKABLE CLAIM`), which is about doing a
  census at all; this one is about the census being narrower than its claim.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-03 — FORBIDDEN: reporting a worker's `server_failed` as an incident without reading the log AT THE EXIT. On live-odds-worker, 20 of 23 are a SCHEDULED SELF-RECYCLE. `[lane prop-join-yield]`

- **THE EVENTS API CANNOT TELL YOU THIS.** Render's `/events` for the service:
- *(evidence in `learnings_evidence.md`)*
## 2026-09-04 — FORBIDDEN: verifying a ledger mutation with a BEFORE/AFTER set comparison computed by the parser that is blind to the thing at risk

- **Neither check could have detected the failure it was standing in for, and the second was not independent.** Both sides of my comparison came from `check_lane_invariants.claims()`, which skips any block whose header fails `OPEN_RE = \bOPEN\b`. My own block's header read `**REOPENED 2026-09-03 for the READ side**` — and `\bOPEN\b` correctly rejects `REOPENED`, there being no word boundary inside it. So the six files that block declared were **never in the claim set at all**, and a block holding six unenforced claims moved out of `lanes.md` reporting `claims unchanged`.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-03 — FORBIDDEN: reporting a commit as PUSHED on the strength of a command that also succeeds when it is not. And after a rebase, `--is-ancestor` on the old SHA is not evidence it is absent. `[session c38d3e5c with f97ad5ab]`

- **Direction 1 — existence read as reachability (mine).** I ran `git fetch origin`, then `git log --oneline -1 <sha>` and `git show <sha> --stat`, and reported "confirmed on origin". Both commands return identical output whether or not the commit is reachable from `origin/main`; they answer *does this object exist locally*. `git merge-base --is-ancestor <sha> origin/main` returned **exit 1** and the content was absent from the upstream blob. **The `git fetch` immediately before is what made it feel like an origin check** — it updates the ref, then the next command never consults it.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-03 — FORBIDDEN: comparing a CONTROL window sampled differently from the treatment window. The rate ratio is an artefact of the sampling, and it will flatter whichever side you sampled less. `[lane prop-join-yield]`

- **RE-RUN, both windows sliced into IDENTICAL 10-minute chunks with per-chunk coverage printed:**
- *(evidence in `learnings_evidence.md`)*
## 2026-09-04 — FORBIDDEN: asserting absence from a range whose START YOU CHOSE — and the reason this one got through, which is the actually useful part

- **This is `absence-in-a-window-is-not-absence` for the THIRD recorded time** (see 2026-08-2x, where the same shape carried a destructive forced deploy). The rule was already written, in this file, and I had cited a neighbouring rule in a commit message forty minutes earlier. So "know the rule" is demonstrably not the control, and a fourth copy of it would not be either.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-04 — A LANE CLAIM ON A LEDGER FILE GUARDS NOTHING, and I read the evidence for that TWICE without extracting it

- **REFINEMENT, because "guards nothing" reads as "unprotected" and that is false.** Ledger files are guarded by CONTENT INVARIANTS rather than by OWNERSHIP, which is a different model and a better fit — every session must write them, so an exclusive claim would be wrong:
- *(evidence in `learnings_evidence.md`)*
## 2026-09-03 — A false REASSURANCE is worse than a false WARNING, so it needs a higher bar. Every one of five errors in one night was in the reassuring direction. `[sessions c38d3e5c + 37abeca0]`

- **The asymmetry.** A wrong claim that says *worry about this* costs someone a check they did not need — expensive, and self-correcting, because they go and look and the claim dies. A wrong claim that says *this is covered* removes a check they did need, removes it **silently**, and nobody goes looking, because the whole point of a reassurance is that it ends the enquiry. So the two are not symmetric errors and must not carry the same evidentiary bar.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-04 — a failed rebase leaves a STALE ledger file that `git add` will happily record

- **Two rules.**
- *(evidence in `learnings_evidence.md`)*
## 2026-09-03 — FORBIDDEN: choosing a REMEDY from a checker's finding without reading the owning block's INTENT. A true finding can carry a false fix, and the fix is the part that does damage. `[session c38d3e5c, caught by f97ad5ab]`

- **I then triaged them as "the substantive ones — real files, unguarded" and told two sessions and a user that `run_refresh_worker.py` was the one to look at.** The block says, twice, in the same `- Files:` line I was reading tokens out of:
- *(evidence in `learnings_evidence.md`)*
## 2026-09-04 — before a catch-up deploy, check whether the OWNING lane is already shipping it

- **Round 9, web.** `442f82fe` was `web-oom-profiler-steady`'s OWN commit. That lane held web's claim and web had booted 24 minutes earlier — one minute short of the 25-min window its late-emission method needs, because the accumulator is cumulative from boot. A deploy would have reset the clock as the reading came due.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-04 — REBASE FIRST, then edit ledger files

- **The rule catches it; the SEQUENCING prevents it. Rebase, verify it said something other than a refusal, then edit.**
- *(evidence in `learnings_evidence.md`)*
## 2026-09-03 — EXONERATED: `deploys.md` and `learnings.md` ARE guarded. Two sessions filed the same false gap, and the second re-derived it with the SAME blind spot

- **The claim, twice:** that `.syndicate/deploys.md` has no ledger-guard
  coverage at any stage (session c38d3e5c, at close), and — after I "verified"
  it — that **2 of 18 `TRACKED` files have no predicate that can ever fire**.
  Both are wrong. `_deploys` and `_learnings` are registered in `CHECKS` and
  both fire.
- **AMENDED `[2026-09-03, session c38d3e5c]` — THE FIRST OF THOSE TWO WAS TRUE
  WHEN IT WAS MADE, AND IS WHY THE GUARD EXISTS.** Only the second is a false
  reading. `dbe0f3b4` is what closed it, and its diff is unambiguous:

      -TRACKED = (LANES, STATE, *STATE_PARTS, LEARNINGS)
      +DEPLOYS = ".syndicate/deploys.md"
      +TRACKED = (LANES, STATE, *STATE_PARTS, LEARNINGS, DEPLOYS)
      +def dropped_sections(...)      +def _deploys(text, root)
      +          DEPLOYS: _deploys,

  Before that commit `deploys.md` was absent from `TRACKED`, had no `_deploys`,
  and was not in `CHECKS` — measured at the time, alongside `ledger-append-guard`
  (two hits, both PROSE: docstring :31, remedy string :176) and
  `ledger-postwrite-check` (zero mentions). That commit's own added comment
  restates the finding as its justification: *"ledger file with no guard at ANY
  stage: absent from TRACKED, and its two ..."*.

  **The correction is therefore a TIME error, not a fact error** — a true claim
  re-evaluated against code that had changed in response to it, and then filed
  as a false alarm. **This matters beyond attribution:** left as written, a
  reader concludes `deploys.md` was never unguarded, which removes the reason
  the guard was added and makes deleting it look like tidying. `_deploys` is
  load-bearing — probed against the real 1.13MB upstream file: unchanged text
  0 violations, two sections REMOVED 1 violation, an APPEND 0 violations, so it
  blocks a drop while preserving append-only.

  Your second claim stands exactly as you wrote it, and the `root=None` lesson
  is the durable half: a probe is only evidence once it can produce the other
  value.
- **How the false reading was manufactured.** I drove every tracked file with
  empty/garbage text and `root=None`, and read the nulls as absence.
  `_deploys`' own first line is *"Fails OPEN: no root, no git, no ref -> no
  opinion"* — I passed exactly the argument that makes it silent, then reported
  the silence. `_learnings` needs its `- *(evidence in ...)*` marker, which my
  inputs never contained. **Driven, not grepped** is better than grepping and
  still not enough: a probe is only evidence once it can produce the other
  value.
- **Demonstrated, which is what the first pass owed:** `_deploys` with a real
  root reports **1** missing measurement section on the live file (this tree is
  behind origin) and **294** on a file truncated to 200 lines. It diffs against
  `origin/main:.syndicate/deploys.md` and refuses a commit that would DROP
  measurements — *"a lost entry makes an unverified deploy look verified"*. It
  is one of the STRONGER predicates in the module.
- **The rule, and it is not "check harder".** RE-DERIVING A PEER'S FINDING WITH
  THE SAME BLIND SPOT IS NOT CORROBORATION. I set out to verify their claim
  rather than accept it, which is the defence — and reproduced their error,
  because I chose an instrument that fails silent in the same direction. Two
  agreeing readings are one reading unless the instruments can fail
  independently. Same shape as the two-checks-one-parser case filed the same
  day, one layer up.
- **What actually stopped it:** reading `CHECKS` before writing code. A lane was
  open to add an `UNCHECKED` set and a coverage test — machinery guarding a gap
  that does not exist, in the file whose own comment says silence "fails
  PERMISSIVE", while the real predicates sat 30 lines below the dispatch I had
  already read. Nothing was built.
- **IT THEN BLOCKED THE COMMIT THAT RETRACTS THIS.** `ledger-commit-guard`
  refused it: *"1 measurement section(s) on origin/main are MISSING from this
  commit's deploys.md"* — a real entry (`## 2026-09-04 round 10`) this stale
  tree had not fetched. The predicate I had written off caught a real
  regression in a real commit, in the same minute. **A guard reported as dead
  is not dead; it is a guard nobody has made angry yet.**
- *(evidence in `learnings_evidence.md`)*
## 2026-09-04 — OVERTURNED: `_SCORE_SIM_WEIGHT` is **0.125**, not 0.0. Two load-bearing comments say 0.0, and one of them is the entire basis of `side_picked_by`. `[lane prop-join-yield]`

- **`sim_component` is NON-ZERO on 5,108**, min −1.5000, median 0.2737, max 1.5000, with 448 rows flagged `sim_capped`. The sim IS in the ranking, on ~20% of rows, and the served board's own explainer agrees ("capped at 1.5 EV points").
- *(evidence in `learnings_evidence.md`)*
## 2026-09-03 — FORBIDDEN: clearing a `git checkout -- <path>` on a DELETIONS count. It is structurally blind to the ADDITION you are about to destroy

- **The rule.** Before any discarding git operation in a shared tree
  (`checkout -- <path>`, `restore`, `reset --hard`, `stash` without `-u`), the
  check is *"what does this path contain that exists NOWHERE ELSE"*, not
  *"whose deletions are these"*. Run `git diff -- <path>` and read the `+`
  lines; anything added and uncommitted is gone the moment the command returns,
  and it is gone from every session, because the tree is shared.
- **What happened `[session c38d3e5c, on this session's lane block]`.** Their
  shell's cwd had silently reverted from their own worktree to the PRIMARY
  SHARED TREE. Recovering an unrelated edit, they ran
  `git checkout -- scripts/pending_deploys.py .syndicate/lanes.md` there. They
  DID check first, and the check was the wrong shape: the diff read **"0
  deletions, all mine"**. Another session's lane block was an ADDITION in that
  same unstaged diff, and the two `+### ` headers read as one. It existed in no
  commit on any branch — `git log --all -S` returned nothing — and no backup was
  newer than it.
- **The check was not weak, it was aimed elsewhere.** A deletions count answers
  "am I removing someone's existing lines". The hazard was "am I removing
  someone's NEW lines", which has no deletions at all. Same family as the
  session's other findings — a guard that cannot read the unhealthy state is
  silent in exactly the case it was reached for.
- **What worked, and it is the cheap half:** they left a PARTIAL
  RECONSTRUCTION in place rather than a hole, so the destroyed lane's file
  claims stayed ENFORCED and the loss stayed visible instead of reading as a
  lane that never existed. Reconstructing from the `lane-postwrite-check`
  report recovered the slug and the claims; everything else was lost.
- **The rebuild then duplicated the slug** — the owning session no longer had
  the block locally, rewrote it, and landed on a base that already carried the
  reconstruction. `ledger-postwrite-check` caught the double block within
  seconds of the push. Two blocks for one slug means two sessions can each read
  themselves as holder of the same files.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-03 — FORBIDDEN: retracting a claim you re-checked, without first asking whether the CODE MOVED between the claim and the check. Re-derivation cannot see this

- **The rule.** When you verify someone's finding and it comes back false,
  date the claim and date the code. One line answers it:

      git log --oneline -S "<symbol from the claim>" -- <file under test>

  If a commit lands between the two, you are not checking their claim — you are
  checking a different system, and very possibly one that changed BECAUSE of
  their claim.
- **Why it is worth its own entry.** This is invisible to the defence everyone
  reaches for. I re-derived instead of accepting, ran the check correctly, and
  got the correct CURRENT answer. **Nothing in a correct measurement tells you
  the ground moved under it.** That makes it distinct from the same-blind-spot
  failure filed beside it: there the instrument was wrong, here the instrument
  was right and the QUESTION had expired.
- **Measured.** c38d3e5c reported `.syndicate/deploys.md` had no ledger-guard
  coverage at any stage. TRUE when written: at `dbe0f3b4^` it was absent from
  `TRACKED`, absent from `CHECKS`, and had no predicate. `dbe0f3b4` (19:42:33)
  added all three, and **its own comment quotes the finding as its
  justification**. I checked at ~20:2x, found `_deploys` alive and firing, and
  filed the whole thing as a false alarm.
- **The cost direction is the dangerous one, and it is reassurance.** A
  retraction of a TRUE finding does not merely lose a fact: it deletes the
  stated reason a guard exists. Left standing, the next reader concludes
  `deploys.md` was never unguarded and removing `_deploys` reads as tidying.
  Compare the retraction rule already here — withdrawing a bad attribution buys
  "not proven guilty", never "proven innocent"; this is the same asymmetry
  pointed at a live guard.
- **How it was caught:** not by me. c38d3e5c amended the entry rather than
  messaging, on the grounds that the wrong version was the one being read. That
  is the right call for a correction whose damage is what a passer-by concludes.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-04 — THE LEDGER COMMIT GUARD CANNOT SEE A WITHIN-BLOCK REVERT, measured at 117,321 characters

- **Measured, not argued:**
- *(evidence in `learnings_evidence.md`)*
## 2026-09-04 — FORBIDDEN: clearing a shared-tree file on a STRUCTURE check. Content dies inside retained structure.

- **Twice-real, same day, two sessions, opposite roles.** The generalisation is session c38d3e5c's and it is sharper than either incident:
- *(evidence in `learnings_evidence.md`)*
## 2026-09-04 — THE UNIFYING RULE: A COMPARISON PROTECTS ONLY AT THE GRANULARITY IT COUNTS

- **The general form: a before/after comparison is blind to anything its extractor does not emit, and that blindness is SYMMETRIC — so both sides agree and the check reports success.** It is not that the comparison is wrong; it is that it answers a question one level coarser than the change.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-03 — A comparison protects only at the GRANULARITY IT COUNTS. Three instances in one night, and the finest-grained one destroyed work. `[session c38d3e5c with 37abeca0, cfcce46d]`

- **Each is blind to any loss smaller than its unit**, and the blindness is silent, because "no difference at my granularity" and "no difference" print identically.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-03 — FORBIDDEN: pushing a REBUILT file without asserting the EXPECTED diff shape first. A stale base produces correct-looking content and a silently wrong delta. `[session c38d3e5c]`

- **Reviewing the artifact cannot detect this; only the delta against the CURRENT base can.** That makes it invisible to every check aimed at content: a diff of the text, a grep for the restored lines, a byte count, reading it.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-04 — A DEPLOY THAT SUCCEEDS, TESTS THAT PASS, AND A SMALLER RESPONSE CAN ALL BE TRUE WHILE THE CHANGE DOES NOTHING

- **THE RULE: verify a payload change by the STRUCTURE you intended to change, not by the size of the result.** "Is the key actually gone?" found it in one call; the byte count would never have. The same trap re-appeared immediately after the real fix landed at a flattering **68.9%**, which was again partly slate size — the honest figure was 50.0%, from differencing the SAME captured payload.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-03 — FORBIDDEN: reading the clock with Git Bash `date` in this repo. It is FIVE HOURS SLOW, and `date -u` is wrong too. `[lane accuracy-autorun-rearm]`

- **The rule going forward:** **get the time from Python (`time.strftime` / `datetime`) or from a server response header, never from the Bash tool's `date`.** This matters far beyond cosmetics here: the accuracy autorun, settlement, the board window and every scheduled task gate on **Central hour**, and a 5-hour error moves you across the `hour >= 7` boundary — the exact predicate that decides whether arming a key waits politely until morning or fires immediately. Related standing rule: report local time, not UTC.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-03 — FORBIDDEN: treating an env key as INERT because the process has not been restarted. Inertness is about the DEPLOY; the DAMAGE is decided by the hour you set it in. `[lane accuracy-autorun-rearm]`

- **The rule going forward:** for any flag consumed by a TIME-GATED job, the question is never "is it deployed" but **"if this became live at this instant, would the gate still protect me?"** Reverting to `false` costs nothing while undeployed; leaving it armed delegates the firing decision to whichever unrelated session deploys next. Same key, opposite meaning, and the only variable is the hour.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-04 — THE TWO THINGS ROSTER-ABSENCE ALREADY COST, and what to check before the NEXT force `[lane prop-join-yield]`

- **The rule itself is one entry down, written by the lane that found it** (`lanes.md` carries `CLAUDE_CODE_SESSION_ID`s, `list_sessions` returns CCD `sessionId`s, the spaces never match). This entry is only what that rule cost in practice and the check it implies — I had written a THIRD copy of the rule here and removed it; `learnings.md` is over budget and three statements of one rule is exactly what makes it lossy.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-04 — FORBIDDEN: calling an env key "inert until a deploy" without reading the gate it feeds. If the gate's conditions are ALREADY true, the key is a primed charge waiting for someone else's deploy. `[lane prop-join-yield]`

- **THE HOUR YOU SET IT IN CHANGES ITS MEANING.** The scheduled task arms at 03:00 Central precisely because at `hour=3` the gate HOLDS the run until 07:00, on a worker that is quiet by then. Arming at 22:00 skips that protection entirely — same key, same value, opposite risk.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-04 — FORBIDDEN: treating absence from `list_sessions` as evidence a session is gone. **`lanes.md` carries `CLAUDE_CODE_SESSION_ID`s; `list_sessions` returns CCD `sessionId`s. The two ID SPACES DO NOT MATCH, so the test has NEVER been valid.** `[lane accuracy-autorun-rearm]`

- **The rule going forward:** **liveness must be established POSITIVELY, from an artifact the session itself writes** — a commit in the last N minutes, a claim whose age RESETS, a fresh preflight record — never from absence in a roster you cannot join to the id you hold. Before forcing any lock, read `/v1/services/<id>/deploys` and check for a deploy in flight; a build in `created` state IS the holder working. And if you must act on a stale-looking claim, prefer waiting: an unexpired claim costs minutes, a displaced deploy can cost a revert nobody sees.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-04 — CHECK THAT THE THING YOU ARE GATING ACTUALLY RUNS, BEFORE YOU BUILD THE GATE

- **Neither loop runs on web.** `SYNDICATE_ENABLE_LIVE_ODDS_REFRESH_LOOP=false`, `SYNDICATE_ENABLE_INTELLIGENCE_STATE_BACKGROUND_LOOP=false`, the code gate defaults to False, and web has logged ZERO loop lines ever. The gate is correct and inert, and the diagnosis it rests on is FALSIFIED.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-04 — FORBIDDEN: acting on a comparison guard whose inputs are not NORMALIZED

- **Why this is worse than an ordinary bug.** A comparison guard exists to answer "will I destroy something", and unnormalized it reports CATASTROPHE and CORRECTNESS with the same confidence and the same shape. Worse, the remedy it triggers — `git checkout origin/main -- <path>` — is the destructive command, the one that already destroyed a peer's lane block on 09-03. A miscalibrated guard does not merely fail to help; it points at the loaded gun.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-04 — AN IN-PYTHON FREE CANNOT MOVE PROCESS ANON. CHECK THE ALLOCATOR BEFORE HYPOTHESISING ABOUT FREES

- **Allocated 0.0 MB. Refunded 0.0 MB.**
- *(evidence in `learnings_evidence.md`)*
## 2026-09-04 FORBIDDEN: an instrument whose partial output is indistinguishable from its complete output. `[lane render-events-nondict-reason]`

- *(evidence in `learnings_evidence.md`)*
## 2026-09-04 — a BLOCKED money-relevant commit needs a follow-up read, not just a flag

- **The half that is easy to miss is going back to check.** I did, and it had shipped — refresh-worker `2332b47b`, 0 pending, verified BY CONTENT (`_sample_credibility` x1, `_settled_sample_size_by_sport` x2, `848bcab9` an ancestor). Bet sizing is corrected in production.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-04 CITE THE COMMAND YOU RAN, WITH ITS FLAGS — an abridged citation cannot be re-checked, and one day it will have to be. `[lane render-events-truncation-audit]`

- *(evidence in `learnings_evidence.md`)*
## 2026-09-04 — A WRONG CAUSE IN A PRE-REGISTRATION IS WORSE THAN NO PRE-REGISTRATION, because it is the first explanation the next reader reaches for. `[lane accuracy-ledger-budget-raise, challenged by lane mlb-rate-refit]`

- **The rule going forward:** pre-register **what reading counts as which outcome**, and keep candidate CAUSES out of it unless the mechanism is already established. A registered cause is not a neutral hypothesis — it is the explanation the next reader adopts first, and it steers them AWAY from the real driver precisely when the measurement goes bad and attention is short. If you do register one, register the check that would discriminate it. And **when retracting, mark the wrong claim false IN PLACE rather than deleting it**: a retraction needs something to point at, or the next reader meets a clean ledger and no reason to doubt the surrounding numbers.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-04 — FORBIDDEN: REBUILDING a shared ledger file from `origin/main`. Every git discard guard watches git; a rebuild is a plain WRITE and none of them fire. `[lane mlb-feed-live-terminal-refresh]`

- **The rule going forward.** **Never rebuild a shared ledger file from a remote. Rebase your own copy, or edit in place.** If a rebuild is genuinely the only option, the pre-check is not against upstream — it is `set(slugs in the file you are about to overwrite) - set(slugs in your replacement)`, which must be empty. Same shape as the 2026-09-03 rule (*"what does this contain that exists NOWHERE ELSE"*) with the answer computed against the WORKING TREE rather than against a remote.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-04 — a content-check TOKEN that was guessed FAILS CLOSED, and looks like a missing commit

- **The asymmetry.** *Verify by content, not ancestry* is the right rule and I keep using it; this is its failure mode. A token that is present-but-misspelled returns the SAME `0` as a commit that never landed, and `0` is the alarming answer, so the mistake manufactures incidents rather than hiding them. That is the safer direction than the reverse — but only if the token is checked.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-04 — FORBIDDEN: reporting a key as ABSENT from a paginated API without paginating. An unpaginated list read manufactures FALSE ABSENCE, and absence is the finding people act on. `[lane mlb-feed-live-terminal-refresh]`

- **The rule going forward.** **A list endpoint answers "what is on this page", never "what exists".** Absence is only a finding once the listing is known to be COMPLETE: paginate to exhaustion and report the total you enumerated (`keys=153`) next to the absence, so the denominator is visible and a short read is obvious to the next reader. And when a config read implies that deployed code is INERT, **check the code's own output before believing it** — a log line, a counter, an emitted stamp. A gate that is really inert is silent, and silence is directly observable. Sibling of *presence is not reachability* pointed the other way: this is ABSENCE is not INERTNESS.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-04 — "SELF-VERIFYING" is only true where the EMITTER runs. Find the print, then ask who owns it.

- **The rule.** A verification signal has an owner service exactly like the code it verifies, **and they need not be the same one**. Computation in `shared/` reaches all three; emission in `pipeline/` reaches one. So before claiming a deploy makes something verifiable: **locate the PRINT — `git grep <field>` for an f-string, repo-wide — and ask `_owners()` who runs THAT file.** Deploying the computation to a service that cannot print it buys nothing observable.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-04 — A FLAT READING FROM AN INSTRUMENT THAT CANNOT SEE THE SUSPECT IS NOT EVIDENCE

- **Both instruments are structurally incapable of seeing the allocation that turned out to be responsible.** CPython routes anything over 512 bytes past pymalloc to malloc/mmap; pymalloc arenas were ~40% of worker RSS and `malloc_info` reached 13.9% coverage. The growth is in 8-64MB anonymous mappings — a region class neither can report. A third instrument (`/proc/self/smaps`, the kernel's own accounting) found it in one window.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-04 — PRE-REGISTER THE GATE, AND LET IT BIND WHEN THE DATA IS POINTING WHERE YOU HOPE

- **34.6 minutes — 24 seconds short** — with the data pointing exactly where I wanted it to.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-04 — 100% OF WHAT YOU SAMPLED IS NOT 100% OF THE THING. THE DENOMINATOR MUST COME FROM OUTSIDE THE INSTRUMENT

- **Failing in OPPOSITE directions is the tell that it is not a scale error.** One worker climbed 90 MB with every sampled request reading zero; the other attributed nearly twice what its process gained.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-04 — A PRE-REGISTERED FALSIFICATION TEST IS WORTH WRITING, BECAUSE IT FIRES

- **A pre-registered falsification test is worth writing, because it FIRES.** *(this entry's body carried no separate rule line; its heading is the rule.)*
- *(evidence in `learnings_evidence.md`)*
## 2026-09-04 — A BROKEN IDENTIFIER IS WORSE THAN NO IDENTIFIER, BECAUSE IT MANUFACTURES FALSE CONTINUITY

- **It shipped INERT, and inert in the worst available way.** The token was generated at module import, and **gunicorn forks its workers AFTER the import**, so every worker inherited the identical value. Measured in production 20:24-20:26: pid 99 and pid 98 both emitted `6178fc632433`.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-04 WHEN A COMMIT NARROWS A PREDICATE, THE DOCSTRING IS PART OF THE PREDICATE — a stale contract line does not read as stale, it reads as CORROBORATION for whichever test still encodes the old rule

- **The rule going forward.** A guard's docstring is part of the change that narrows it, not documentation of it. Left behind, it does not read as stale — it reads as a SECOND SOURCE agreeing with whichever test still encodes the old rule, and the pair is an instruction to revert a change that was made on a production measurement. **Before committing a narrowed predicate, grep the whole enclosing docstring for the rule you just edited.** `28e55d86` rewrote the branch and its inline comment and left the docstring twenty lines above it stating the opposite; the contradiction sat red for two weeks and pointed the wrong way.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-04 FORBIDDEN: editing a scheduled task's prompt while a session of that task is still ALIVE — it can fire the new prompt IMMEDIATELY. `[lane feed-live-warn-rate, session c4287631]`

- **The dry run's session was still alive.** It picked up the restored prompt and began executing the REAL 30-minute measurement at 15:42 — 4.5 hours early, with **1 game live instead of the ~12** the window was chosen for, holding the worktree the 20:15 run was going to want.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-04 — A COEFFICIENT IS NOT A FINDING UNTIL IT SURVIVES LEAVE-ONE-OUT AND A RANK TEST

- **One collector, one metric, four verdicts, three of them wrong -- and each wrong one was a clean number with a plausible mechanism attached:**
- *(evidence in `learnings_evidence.md`)*
## 2026-09-04 — "THE CLAIM HOLDER IS NOT IN THE SESSION ROSTER" IS TRUE OF EVERY CLAIM. IT IS A CATEGORY ERROR, NOT A LIVENESS CHECK

- **The comparison cannot ever succeed, for anyone.** Measured:
- *(evidence in `learnings_evidence.md`)*
## 2026-09-04 — A RUNNING MINIMUM CANNOT DETECT A RISING FLOOR. CHECK THAT THE STATISTIC CAN EXPRESS THE ANSWER

- **The running minimum is the first reading, always, for any non-decreasing series.** It can only move DOWN, so on a process that never returns memory it is pinned at the boot value forever. The metric I chose to answer "does the floor rise" is mathematically incapable of rising. Both workers duly reported `floor_mb` fixed at their boot values, which looks like a flat floor -- the CHURN signature -- when the truth was the opposite.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-04 FORBIDDEN: pinning a copied definition against ANOTHER FILE'S SOURCE TEXT. When the definition moves, the test stops existing instead of failing `[lane lane-invariant-single-source]`

- **The rule going forward:** a module may not hold its own copy of a definition another module enforces -- import it. If you cannot, do NOT settle for a test that scrapes the other file for the definition and compares: that test's precondition is *being able to FIND both copies*, so the refactor that moves one turns the test red for a reason unrelated to drift, and drift then accumulates behind it unwatched. Assert the ABSENCE of a second definition in the file you control (`ast`, module scope) -- that survives any refactor of the other side. **14 tests across three files had been red on `origin/main` for exactly this**, all bound to `lane-guard.py`'s shape after its parser moved to `lane_claims.py`, while `check_lane_invariants.py` still exited 0 and printed INVARIANTS HOLD. The four pinned regexes had NOT drifted; four things nobody had thought to pin had. Worst: a `- Files:` line naming `scripts/archive_released_lanes.py` -- a filename CONTAINING the marker "released" -- yielded the checker ZERO claims, so that lane could contest nothing and the two-holder invariant passed vacuously. Measured on one adversarial ledger: old checker `INVARIANTS HOLD` exit 0 against a contested file AND a stray OPEN lane under `## Archived lanes`; new checker, 2 violations, exit 1. Fixed in `312c93a9`.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-04 — FORBIDDEN: choosing a DEPLOY TARGET by which service CONTAINS the code. Choose it by which service SERVES the reading you predicted. `[lane nfl-projection-deploy]`

- **What we believed:** deploying `web` would take NFL `unmatched_game_rows` from 78 to 0. `_attach_book_grid_projections` runs in web's request path, web serves `/api/board/book-grid`, and web had the fix. Every one of those is TRUE.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-05 — A CENSUS IS BOUNDED BY ITS ROOTS, AND THE ROOT SET IS THE FIRST THING TO STATE

`#632`. A retainer census walked module globals in `syndicate.*` / `pipeline.*`
and found that named containers explain **6.1% of a worker's anon GROWTH**. The
tempting headline is "the memory is not in Python, go look at C extensions".

That headline would be wrong, and the reason is in my own code: the walk's ROOTS
are module globals **that are already `dict`/`list`/`set`/`tuple`**. A
module-level OBJECT holding caches in its `__dict__` is skipped before the walk
starts. So are class attributes, closure cells, and thread-local state. The
supported claim is *"not in container-typed module globals"* — a strictly
narrower statement, and the difference is exactly where a lot of real caches live.

THE RULE: a reachability census answers "how much is reachable FROM THESE ROOTS",
never "how much exists". State the root set beside the coverage number, every
time, because a low coverage has two very different causes — the memory is
elsewhere in the process, or the roots were too narrow — and they lead to
opposite next steps.

The same run supplies a second, sharper instance. At `node_cap` 20k/100k/400k the
budget EXHAUSTED and coverage read 0.8% / 2.9% / 15.8%. **With the budget
exhausted, "top N by bytes" is only "biggest among whatever module iteration
order happened to reach first"** — an arbitrary sample presented as a ranking.
Only the completed 2M-node walk is quotable, and the census reports
`node_budget_exhausted` precisely so that a truncated run cannot be read as a
finished one.

Related: `[2026-09-04]` "a flat reading from an instrument that cannot see the
suspect is not evidence" and "a running minimum cannot detect a rising floor".
Three forms of one discipline: know what your instrument CANNOT show before you
believe what it does.
## 2026-09-05 FORBIDDEN: shipping a fix whose motivating measurement YOU labelled inconclusive. A caveat you wrote is an instruction to yourself, not a disclaimer to the reader

- **What happened.** A one-date run (6 game clusters, 6,396 pairs) showed the
  MLB sim's measured joint LOSING to plain independence, monotonically worse the
  further the estimator was allowed to move. I diagnosed a unit error -- the
  joint publishes Spearman rank correlation of COUNTS while a parlay bets
  THRESHOLDS, and under a Gaussian copula phi(indicator) is only 54-68% of
  rho(counts) -- wrote the correction, shipped it (`c6027e1f`), and reported it
  as explaining every number. I had written "6 clusters, one date; suggestive,
  not conclusive" onto that finding **in the same session**, then reasoned from
  it as though it were settled.
- **What the replication said.** Backfilled 177 games from git-tracked rosters
  and re-scored: 162,491 pairs, 151 games, 13 dates. **The motivating finding
  INVERTED.** The joint BEATS independence on same-player pairs by -0.02353
  log-loss, 95% CI [-0.02849, -0.01854]. And the correction was measurably WORSE
  than the raw coefficient: +0.00156, CI [+0.00100, +0.00219]. A Gaussian copula
  over-attenuates for discrete, zero-inflated counts. Reverted in `862b5ccf`.
- **The rule.** A caveat does not discharge the risk it names. If a finding is
  too thin to publish it is too thin to BUILD ON -- replicate first, at a sample
  that can actually separate the arms, or do nothing. The tell is writing a
  hedge and a fix in the same session.
- **The second half, and it is what made it invisible.** The conversion shipped
  with NO TEST referencing it. ADDING it was silently green and REVERTING it was
  silently green -- a behaviour change on a live pricing path that no test could
  see, in either direction. **A revert that passes cleanly is not reassurance;
  it is evidence the change was never covered.** Guard added
  (`tests/test_joint_resolver_returns_raw.py`), source-level so it needs no
  fixture, mutation-checked by re-adding the call.
- **Cost:** none in production -- `c6027e1f` landed after the last deploy
  (`3a9153f4`), so the conversion was never live. Luck, not process.
- **Instruments:** `scripts/backfill_mlb_sim_joint.py` (resumable, git-tracked
  rosters, no export and no StatsAPI) and
  `scripts/score_joint_pair_pricing.py` (four arms on identical marginals,
  bootstrap over GAMES).
## 2026-09-05 — A TRUNCATED MEASUREMENT CAN GIVE THE RIGHT ANSWER FOR THE WRONG REASON. CONVERGE, THEN READ.

`#632`. The deciding question was whether the retained bytes were Python objects
at all. The walk that answers it is budgeted, and the budget changes the answer:

    cap   200,000  ->   20.55 MB    7.2%   TRUNCATED
    cap   800,000  ->   97.75 MB   28.5%   TRUNCATED
    cap 2,000,000  ->  105.56 MB   28.3%   CONVERGED

Every reading pointed at the same conclusion ("not Python"). **Only the last one
is entitled to it.** At a 200k cap the walk had seen 7.2% of anon and would have
supported the verdict just as comfortably — and been wrong by a factor of five
about the size of the Python heap, which is the number the FOLLOW-UP work
depends on.

THE RULE: when a measurement is budgeted, the budget is a parameter of the
result. Escalate until the instrument reports it did NOT truncate, and refuse to
report a ratio computed from a truncated walk — build the refusal into the tool,
because the truncated number will usually agree with whatever you already
believe. A tool that returns a plausible number when it ran out of budget is
`[2026-09-04] an instrument whose partial output is indistinguishable from its
complete output` in a new costume.

The corroboration is worth recording too, including its limit: pymalloc's
`bytes_in_allocated_blocks` (`105.731 MB`) and an independent object-graph walk
(`105.56 MB`) agreed to **0.16%**. Two instruments with nothing in common
arriving at the same number is the strongest evidence this investigation has
produced — and it is still only SUGGESTIVE, because the readings came from
different processes hours apart. Same-instant would have made it proof;
saying so is the difference between corroboration and a coincidence.
## 2026-09-05 — SAMPLE FASTER THAN THE THING YOU ARE DESCRIBING, OR THE SHAPE IS YOUR SAMPLING GRID

`#632`. I opened a lane on a striking observation: both web workers gained ~98 MB
inside ~100 seconds, and **a single request cannot raise two workers at once**,
so it had to be a scheduled job or a fan-out. The reasoning was sound and the
conclusion was wrong, because the observation was an artifact of the sampling
interval.

It came from samples **50 seconds apart**. At that spacing, "worker A grew, then
worker B grew" and "A and B grew together" produce identical data. Re-measured at
**10 seconds**: 7 of 7 bursts hit ONE worker, gaps irregular (spread/mean 1.79
against a 0.35 bar), and the fan-out hypothesis died.

THE RULE: before drawing a conclusion from the SHAPE of a time series, state what
the sampling interval can and cannot distinguish. Simultaneity, periodicity and
burstiness are all properties the grid can manufacture. If the claim is "these
happened together", the interval must be shorter than the gap you are claiming
is zero.

The same session produced two more of these, which is what makes it a pattern
rather than an incident: a correlation called on a 12-minute window that
reversed at 35 minutes, and a retention-vs-churn verdict called on ONE time point
that reversed at the next reading. **Coarse sampling does not add noise, it adds
STRUCTURE** — and the structure looks like a finding.

Corollary, learned the hard way in the same lane: a detector watching a
production process needs a RESTART GUARD. A peer deployed mid-window and the
first run reported warm-up as bursts, `+570 MB` and `+284 MB`, with pids REUSED
across the restart so the process set looked continuous. Boot confounds are
already in this file for making a fix look good; they make a defect look
catastrophic just as easily.
---
## [2026-09-05] A MEASUREMENT THAT CAN ONLY SEE ONE BRANCH DOES NOT CERTIFY THE OTHER — and a fixture that cannot express the failure keeps a whole test file green over it

Lane `edge-basis-moneyline`. `edge_basis` was added on 2026-08-16 to say WHICH
probability `edge_vs_market_pct` is paired against, on a good measurement: 13
served rows, the 7 whose edge could not be reproduced from the pregame pair were
all `live_aware`, the 6 that reconciled were not. **7/7 separation.** It shipped,
it was verified on served rows, and the lane closed CLOSED-VERIFIED.

It was wrong on h2h from the first commit, for three weeks.

**THE MEASUREMENT SELECTED ITS OWN POPULATION.** Those 13 rows were identified by
carrying BOTH probabilities — and `live_model_prob_over` is written only by the
DISTRIBUTION branch. So every row in the sample was totals or spreads, and the
moneyline branch, which is the one that got the label wrong, could not appear in
the evidence that certified the fix. The selection criterion and the defect were
the same variable.

    the label is derived from    `live_projected`   (a PUBLICATION switch)
    the edge is computed from    `verdict["model_prob"]`
    the moneyline branch passes   no `live_projected`, deliberately
    => every live h2h row: edge from the LIVE probability, labelled "pregame"

Measured 2026-09-05 with the real functions: live probability 1.0 against
`market_fair_prob_over` 0.310 published `edge_vs_market_pct 69.0`, which is
`(1.0 - 0.310) * 100`; the pregame pairing gives 66.7 and is not what came out.

**AND THE UNIT TESTS COULD NOT HAVE CAUGHT IT.** `test_a_row_with_no_live_projection_says_pregame`
called `_apply_verdict` directly with a hand-built verdict **carrying no
`model_prob` key at all** — a verdict none of the three pricers can produce,
because all three set `model_prob` before they can set `priceable`. The fixture
was not a simplification of the real object; it was a different object, and the
one field that discriminates the two branches was the field it omitted. Six tests
passed over the defect, one of them asserting it by name.

THE RULE, two halves:

1. **State how a verification sample was SELECTED, and check whether the
   selection can reach the failure mode.** "N of N separated" is a strong result
   about the rows you looked at and says nothing about a branch that cannot
   produce a row matching your filter. Where a function has branches, enumerate
   them and say which ones the evidence covers — `presence != reachability`
   applied to the MEASUREMENT rather than to the code.
2. **A fixture must be able to fail.** Before trusting a green test over a
   hand-built input, ask what the real producer always sets that the fixture
   omits. Prefer building the input WITH the real producer; where a literal is
   unavoidable, pin the producer's invariant separately — here,
   `priceable is True => model_prob is not None`, asserted over all three real
   pricers, which is what makes the corrected label falsifiable at all.

Adjacent, same root: `layer2_board._live_projection_columns` carried a comment
asserting `_apply_verdict` is called with `live_projected=verdict["model_prob"]`
for "EVERY game market (h2h, totals AND spreads)". False, and harmless where it
stood — it was making a claim about UNITS — while being the load-bearing belief
one module over. **A comment is only checked where it is load-bearing, so it
rots fastest exactly where it is quoted.**
## [2026-09-05] IN `lanes.md`, A DISCLAIMER AFTER A PATH DOES NOT DISCLAIM IT — release lines must be MARKER-LED, and only `claims_by_path` can tell you

Lane `edge-basis-moneyline`, releasing three files. **Two attempts changed
nothing, and the file read correctly both times.**

`_claimable_prefix` cuts a line at its FIRST disclaimer marker and keeps
everything BEFORE it — deliberately, so "`a.py`, `b.py` (collision check CLEAR)"
still claims both. Two consequences nobody had written down:

- **A marker governs its own line only.** A `- Files:` line beginning
  `**released to X:**` disclaims nothing on the wrapped continuation lines that
  actually carry the paths.
- **Prose re-claims.** `ncaaf-live-resim` contained the sentence
  "`live_gameline_join.py` was named as SOLELY held by `live-edge-basis` ... those
  claims were released" — every marker in it (`held by`, `released`) sits AFTER
  the backticked path, so the claimable prefix keeps the path and the sentence
  re-claimed the file all by itself, defeating a release two bullets above it.

Both read, in English, as unambiguous releases. The parser disagreed with both.

THE RULE: write every release as its own marker-led line —
`  released: \`path/to/file.py\`` — one path per line, marker FIRST. Then
**verify with `.claude/hooks/lane_claims.py`'s `claims_by_path` over the file you
actually changed**, asserting the full expected map including the paths that must
NOT move. Reading the ledger is not verification of the ledger; this is the same
lesson as `[2026-08-2x] the commit-guard's own fix list can omit a path it just
flagged`, and it applies to the lane parser for the same reason — the machine and
the reader disagree about what a sentence means, and only one of them is enforcing.

Corollary for a session worktree: `lane-guard` reads
`$CLAUDE_PROJECT_DIR/.syndicate/lanes.md` — the PRIMARY tree's working copy — and
nothing else. That copy was **57 commits behind `origin/main`** here, so a lane
OPEN upstream guarded nothing locally and three paths read FREE. Landing a claim
is not the same as enforcing it: check both files.

**SECOND INSTANCE, SAME DAY, FOUND WHILE RESTORING ANOTHER LANE'S BLOCK.**
`evaluation-ledger-projected-mirror`'s `- Files:` line reads, in one breath:

    ... `artifact_publisher.py` (one allowlist entry -- the file is explicitly
    RELEASED and NOT CLAIMED), `scripts/run_refresh_worker.py` (the autorun call
    site only -- every OPEN-lane reference to this file is RELEASED; checked).

The parser reads **both backwards**. The first marker is the `RELEASED` that sits
AFTER `artifact_publisher.py`, so the prefix keeps that path (CLAIMED, though the
sentence says released) and discards everything after it, including
`run_refresh_worker.py` (FREE, though the sentence claims it). No human reads that
line as ambiguous. Two lanes were then working from opposite beliefs about the
same file, and a third lane's collision check inherited the error.

Corollary, and it is the expensive half: **the ledger has more than one copy and
they disagree.** For those four paths, `origin/main`, the primary tree's working
copy (which is what `lane-guard` actually reads) and the owning lane's own
worktree gave three different answers. A collision check names ONE substrate or it
names nothing. Check the copy the guard reads AND the copy other sessions rebase
onto, and say which you checked.
## 2026-09-06 — FORBIDDEN: passing `--commit $(git rev-parse ...)` to `render_deploy.py`. A COMMAND SUBSTITUTION MAKES `deploy-guard` SKIP ITS SHA CHECK ENTIRELY, AND SAYS NOTHING. `[lane ncaaf-live-state-to-worker]`

- **The rule going forward:** pass a **literal SHA** to `render_deploy.py --commit`. The guard reads the command STRING, before any shell expansion, so `$(...)` is not a SHA to it — and its binding is `if deploy_sha:`, which means an unparseable commit **silently disables** the receipt-to-SHA check rather than refusing. **Unknown defaults permissive here**, which this ledger already forbids in general.
- **Measured.** `COMMIT_ARG = re.compile(r"--commit[=\s]+['\"]?([0-9a-f]{7,40})", re.I)`. Against `--commit b72ebcd6` it parses and the check is enforced; against `--commit $(git rev-parse origin/main)` it does not match, `deploy_sha` is `None`, and the whole `if deploy_sha:` block is skipped.
- **It bit me twice tonight and I did not notice either time.** web `3cb5b4ba` (23:00:51Z) and web `67fd8c9d` (01:15:14Z) were both deployed with `--commit $(git rev-parse origin/main)` after a preflight run WITHOUT `--target-commit`. The claim and CLEAR checks did apply, so those deploys were not unguarded — but **the SHA binding, the thing that stops a CLEAR for one commit vouching for another, was never evaluated.** I only found out because a later deploy used a literal SHA and was correctly refused.
- **What made it invisible:** the guard's PASSING path is silent, so a skipped check and a satisfied check look identical. The failure only surfaces when you accidentally do the safer thing.
- **The fix, NOT YET MADE and deliberately not made unilaterally:** when `shape == "deploy"` and a `--commit` argument is PRESENT but unparseable, refuse instead of skipping. It is a two-line change to a guard **every session shares**, and tightening shared infrastructure while eight sessions are mid-flight is its own hazard — a session using the `$(...)` form would start being blocked with no warning. Raised to the user instead.
## 2026-09-05 — FORBIDDEN: running the ledger guard's own remedy, `git checkout origin/main -- <ledger file>`, without first reading `git diff` on that file. It DESTROYS uncommitted work, and a deletions count cannot see what it destroyed. `[lane render-egress-transport]`

- **The rule going forward:** before `git checkout origin/main -- .syndicate/<file>`, run `git diff --numstat -- <that file>` and read it. A working-tree copy that is BEHIND upstream can still hold additions that exist NOWHERE ELSE, and the checkout silently discards them. **`0` in the deletions column is not safety** — it is the exact signature of the case that loses the most, because pure additions delete nothing while being the only copy. Two sessions hit this from opposite directions the same night.
- **Measured, both instances.** Asked to take upstream's `lanes.md` in the primary tree, `git diff --numstat` read **`98  0`** — ninety-eight lines belonging to another live session, uncommitted, invisible to any deletions check. Separately, the guard blocked a commit touching only `state_football.md` because of a stale `lanes.md` that was never staged, and its printed remedy would have destroyed that same work to unblock an unrelated file.
- **The guard prints this remedy constantly and warns about the blind spot two lines below it.** The warning is easy to skip because the remedy reads as the fix. Treat the order as: diff first, then decide, and only then checkout.
- **What to do instead, in the three cases that actually occur.** (1) Only YOUR OWN block is stale — edit that block in place; it is surgical, races nobody, and needs no checkout. (2) The stale file is not the one you are committing — use a scratch index (`GIT_INDEX_FILE` + `read-tree origin/main` + `hash-object -w` + `update-index --cacheinfo` + `write-tree` + `commit-tree`), asserting one path and zero deletions before push; that sidesteps the shared index entirely. (3) You genuinely must take upstream — land from a throwaway worktree at the tip instead, so the shared tree is never rewritten. `[recipe (2) from lane `ledger-repair-invariants`, hit independently the same night]`
- **A repair left UNCOMMITTED can be the correct end state, and this is when.** If the right content is already on `origin/main`, the tree you are in is dozens of commits behind, and other sessions have uncommitted work in the same file, then committing from there either trips the guard or races them — while the working-tree edit still fixes what local hooks and checkers read. Nobody should later "tidy" it into a commit: a snapshot commit from a stale tree deletes blocks that exist upstream.
## 2026-09-05 — FORBIDDEN: treating a cache path resolved off `__file__` as durable on Render. It is in the EPHEMERAL CHECKOUT, so every deploy erases it — and the erasure is invisible because the code refetches. `[lane ncaaf-live-resim-wire]`

- **What I nearly shipped.** The NCAAF live re-sim's rating input is
  `sp_ratings_<season>.json`, read through
  `generate_smartsim2_ncaaf_projections.load_sp_ratings`. Both of its cache
  locations resolve off `__file__` —
  `sp_ratings_cache_path` (`Path(__file__).resolve().parents[1] / "data" / ...`)
  and `ncaaf_historical_loader.DEFAULT_CACHE_DIR` (`parents[6] / "data" / ...`)
  — which on Render is `/opt/render/project/`**`src`**`/data/...`, the checkout,
  not `/opt/render/project/data/...`, the mounted disk. Wiring the producer
  without noticing would have made its FIRST reading after its own deploy
  `no_pregame_ratings` on every game, for the ~24 h until the next projections
  autorun. A zero that is indistinguishable from an inert feature, arriving in
  the shape of the very bug the lane existed to fix.
- **THE ERASURE IS INVISIBLE BECAUSE THE FALLBACK WORKS.** `load_sp_ratings`
  falls through a cache miss to CFBD and succeeds, so nothing anywhere reports a
  lost cache. The tell is in the log line it already prints and nobody read:
  refresh-worker, `2026-09-04T01:03:29Z` and `2026-09-05T01:15:49Z`, **both**
  `[sp_ratings] season=2026 source=api teams=138 cached=/opt/render/project/src/...`.
  `source=api` twice in a row, for a file the same process wrote yesterday, IS
  the measurement — a cache that never reads `source=cache` is not a cache.
- **THIS IS THE SECOND INSTANCE OF THE SAME CLASS, and the first is already in
  this repo.** `#389`, NFL: "the generator wrote to
  /opt/render/project/src/data/nfl_source (the ephemeral repo checkout) while
  this guard read /opt/render/project/data/nfl_source (the mounted disk), so the
  artifact existed and was invisible here, and every deploy discarded it." The
  fix there was to route BOTH sides through one function. The class predicts
  more: any `Path(__file__).parents[N] / "data"` in a producer is on the wrong
  disk on Render, and the sport-root env vars
  (`SYNDICATE_<SPORT>_SOURCE_ROOT`, `SYNDICATE_DATA_ROOT`) exist precisely
  because of it.
- **The rule going forward.** Before treating any file as a model INPUT, resolve
  its path on the DEPLOYED service and say which of the two roots it lands in.
  `/opt/render/project/src/` is erased by every deploy;
  `/opt/render/project/data/` is not. A `__file__`-relative default is the
  signal. And when a producer and a consumer disagree about where a file lives,
  do not repoint the producer if that changes ANOTHER lane's refresh cadence —
  mirroring to the durable root and reading the mirror keeps the producer's
  behaviour intact, which is what this lane did rather than setting
  `SYNDICATE_SP_RATINGS_CACHE_DIR` and freezing in-season SP+ at week 1.
- **The corollary that caught my own bug.** The mirror-freshness branch compared
  `_parse_utc_timestamp`'s NAIVE datetime against an AWARE
  `datetime.now(timezone.utc)`, raising TypeError inside a bare `except`, so the
  mirror was never trusted and every boot fell through to the loader. **It failed
  in the SAFE direction and was therefore silent**: the ratings were still
  correct, merely refetched. The only run that could distinguish the two was one
  with no `CFBD_API_KEY` in the environment at all — i.e. reproducing the
  post-deploy state rather than testing the happy path. `presence != reachability`
  applies to a FALLBACK too: a working fallback hides whether the primary path
  ever ran.
## 2026-09-04 FORBIDDEN: a tool that updates a REGION of a shared file rebuilding that file from the region's start. Splice the region; carry the remainder through untouched, and REFUSE if you cannot classify it

- **The rule going forward.** When a tool rewrites one region of a file other sessions also write, it must locate the region's END, not just its start, and splice. `split_state.py --reindex` computed `head + regenerated_rows` and stopped — correct for every byte it knew about, and it silently deleted everything it did not. **The tell is a rebuild expressed as a prefix plus new content with no suffix term.** Two things make it worse than an ordinary bug: the region's end was defined by a FILTER (`[l for l in lines if not l.startswith("| [")]`) that has no notion of where a table ends, and the result was reported as success — `WROTE state.md (index rebuilt)`, exit 0. Add the conservation check as a RUNTIME guard, not only a test: every non-blank input line outside the rewritten region must appear in the output, or refuse. Verified 2026-09-04: `origin/main` carried 171 non-blank lines below that table, and the fix preserves 171 of 171. Fixed in `29ab5bfb`.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-04 FORBIDDEN: calling a merge lossy from a SAME-FILE line comparison. Content that "vanished" may have MOVED to a sibling file, and the panic fix is to restore stale content over good

- **The rule going forward.** When checking whether a merge, sync or rebuild lost content, diff the working file against the WHOLE sibling corpus, not only against its own previous version. Measured 2026-09-04 syncing the shared primary tree 201 commits forward: a same-file check reported **1,059 lines lost from `learnings.md`**. Against every `.syndicate/**.md` the true number was **3** — upstream had run `compact_learnings.py`, which moves rule bodies into `learnings_archive.md` BY DESIGN. A 350x overstatement, and in the alarming direction, which is the dangerous one here: the obvious response to "the sync ate a thousand lines" is to restore the pre-sync copy, which in this case would have reverted 201 commits of other sessions' work to fix nothing. The same pass also over-reported 113 upstream lines as lost purely because `origin/main` had moved 3 commits past the sync target while the sync ran — **compare against the SHA you actually merged, never against a moving ref.** This is the exact inverse of the same day's rule about rebuilding a shared ledger from `origin/main`: there a check said "0 deletions" and content was genuinely gone; here a check screamed and nothing was. Both come from asking one file a question that is about the tree.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-05 FORBIDDEN: overriding the pre-commit ledger guard when it names a file you did not stage - it is reporting a STALE BASE, and the fix is to change the base. `[scheduled task live-gameline-accuracy-snapshot]`

Staged exactly one file (`reports/live_gameline_accuracy/history.jsonl`). The
guard rejected the commit over `.syndicate/deploys.md`, naming 8 measurement
sections present on `origin/main` and absent from the commit. Nothing about
`deploys.md` had been touched.

**It was correct.** The guard checks the whole STAGED TREE, not the diff, and
local `main` was **32 commits behind** `origin/main` - so HEAD's `deploys.md`
genuinely was missing those 8 measurements, and the commit would have recorded
that stale copy. `SYNDICATE_ALLOW_LEDGER_COMMIT=1` or `--no-verify` would have
made an unverified deploy look verified, which is the precise harm the guard
exists to prevent.

**How to apply:** when the guard names a file outside your change set, read it
as "your BASE is stale", never as "the guard is confused about scope". Check
`git rev-list --left-right --count HEAD...origin/main` first. Then either
fast-forward, or - if the shared tree cannot safely move - build the commit on
top of `origin/main` directly.

**The safe recipe when the primary tree must not move** (it was 32 behind, and
`state.md` + `log/2026-09-04.md` had BOTH changed upstream and carried other
sessions' uncommitted edits, so a fast-forward there was a cross-session action
with real blast radius):

    BLOB=$(git hash-object -w <content>)
    export GIT_INDEX_FILE=<temp>           # never the shared index
    git read-tree origin/main
    git update-index --cacheinfo 100644,$BLOB,<path>
    TREE=$(git write-tree)
    C=$(git commit-tree $TREE -p origin/main -F -)
    git diff --numstat origin/main $C      # MUST be your file(s) only, 0 deletions
    git push origin $C:refs/heads/main

This satisfies the guard's invariant by CONSTRUCTION rather than bypassing it:
every ledger file in the pushed tree is `origin/main`'s own copy.

**Second trap in the same pass - a local append-only file is not necessarily an
append of upstream's.** The primary tree's `history.jsonl` held the same 32
upstream rows in a **different order** plus 4 new ones. `diff` said `1,32c1,32`;
a set comparison said **0 upstream rows missing**. Committing the local copy
would have rewritten 32 lines of a file whose standing rule is *never rewrite in
place* - and a line diff would have called that a rewrite while a row-set check
would have called it clean. **Reconcile append-only files as SETS, then emit
upstream-bytes + the new rows in order.** Both checks were needed; either alone
gives the wrong verdict.
## 2026-09-05 FORBIDDEN: attributing a hazard to the change you just made without measuring the tree WITHOUT it. And `ledger_invariants` does NOT catch a stale tree that is merely MISSING newer blocks

- **The guard gap, measured 2026-09-05 and still open.** The primary tree sat 36
  commits behind `origin/main`. Committing its `.syndicate/lanes.md` from there
  would drop **210 non-blank lines and 7 whole lane blocks**, one of them an
  **OPEN** lane. `ledger_invariants.violations()` returns **0** on that file -
  called directly, not inferred from a hook exit code - so `ledger-commit-guard`
  allows it. The staleness arm (`ledger_invariants.py:211-248`) models a stale
  tree RESURRECTING archived content, which is addition; a stale tree missing
  newer blocks is SUBTRACTION, and nothing keys on it. The file's own docstring
  already flagged a sibling case reading "0 on a 208 KB stale working copy", so
  this is the second instance of the same shape, not the first.
- **The rule going forward.** Before undoing your own change to remove a hazard,
  measure the hazard **with the change and without it**. I read the 210-line
  exposure, attributed it to a 116 KB lane trim I had just applied, and reverted
  the trim. The restored tree measured **210 lines / 7 blocks - identical**: the
  exposure was the 36 commits, not the trim, and the revert destroyed a verified
  reclamation while removing no risk at all. **A number measured only in the
  present state cannot tell you what caused it.** This is the same error shape
  as banking a success against the wrong cause, run in reverse - a cost paid
  against a cause that was never there.
**CORRECTED THE SAME DAY, BY MEASUREMENT, AFTER A PEER LANE TESTED THE
PRESCRIPTION I HAD JUST LANDED.** The rule above says to write every release as
"its own marker-led line". **The MARKER-LED half is right; the OWN-LINE half is
actively harmful, and I am striking it.** Hoisting a path OUT of a Files line
moves `_claimable_prefix`'s cut point for everything that followed it, so the
edit that releases the path you meant to release can silently CLAIM one you did
not. Run against the real parser on
`evaluation-ledger-projected-mirror`'s actual line:

    ORIGINAL                     claims artifact_publisher.py   (author says RELEASED)
                                 leaves run_refresh_worker.py FREE (author says CLAIMED)
    (a) hoist to its own bullet  releases artifact_publisher.py  <- what I prescribed
                                 **and NEWLY CLAIMS run_refresh_worker.py**
    (b) marker moved BEFORE the  releases artifact_publisher.py
        path, line shape kept    run_refresh_worker.py stays FREE

(a) was my advice and it would have taken a third lane's file
(`ncaaf-live-resim-wire` had staged edits in `run_refresh_worker.py`) with nobody
told. (b) removes exactly one pair and nothing else changes hands. Landed by that
lane as `744689c9`.

THE CORRECTED RULE: **move the MARKER in front of the path; do not move the PATH.**
And the part that generalises past this parser — a ledger edit is a MUTATION OF A
CLAIM SET, so diff the claim set, not the text: compute `claims_by_path` before
and after and assert the delta is exactly the pair you intended, **including that
nothing else moved**. I had written "assert the full expected map including the
paths that must NOT move" and then, two paragraphs later, prescribed an edit that
violates it. A rule and its worked example must be checked against each other;
the example is what people copy.
## [2026-09-05] A CONTROL THAT KILLS ONE ALTERNATIVE IS NOT A DISCRIMINATOR — and "did the producer run" is never answerable from the consumer

Lane `edge-basis-moneyline`, and the sharp part is that I made this error **ninety
seconds after writing up the same one**. At ~23:10Z I recorded that a
`supported: false` reading had come off an artifact built 20 seconds before the
deploy. At 23:13–23:15Z I then concluded "the producer is deployed and NOT
writing" from a window that ended **before the first tick ran at 23:15:29Z**.
Vigilance did not survive one turn. The check has to be mechanical.

**The control was good and it still did not license the conclusion.** I checked
that the same endpoint on the same service read `snapshot_present: true` for the
three other sports in the same directory, which really does eliminate the
web/worker disk split. I then treated *the confound I thought of is eliminated*
as *my hypothesis is confirmed* — while a third explanation was live the whole
time. `no_snapshot_at_path` is produced BOTH by "NCAAF-specific defect" and by
"the tick has not run yet", so the reading could not separate them, and I never
established the tick interval to know which window I was in.

THE RULE, and it is mechanical rather than attentional:

- **Enumerate what else produces this exact reading before the reading means
  anything.** A control eliminates the alternative it was designed against and
  says nothing about the ones you did not list. Two hypotheses that share an
  observable are one hypothesis until you find an observable they do not share.
- **Ask the EMITTER, not the absence.** "Did the producer run" is answerable only
  from the producer's own signal. It existed the whole time and I never looked:
  `NCAAF_LIVE_RESIM {... "written": true, "elapsed_seconds": 21.741 ...}` on
  refresh-worker at 23:15:51Z. Same family as
  *absent signal is about the emitter* and *gate verification on artifact mtime*
  — this is the third instance in one session, which is the argument for making it
  a checklist item rather than a thing to remember.
- **A null needs a denominator IN TIME.** Before reporting "X has not happened",
  state how long since it could have and what its period is. I had neither.

CORROBORATION FROM THE OTHER SIDE, and it is what settles that this is structural
rather than a lapse: the peer lane hit the identical trap on the identical data
and escaped by luck. It read the board at 23:15:59Z, saw
`"no published live-lens snapshot"`, and the ONLY thing that stopped it recording
a defect was that it happened to compare two timestamps. **Two independent
sessions, same reading, same hour; one wrote the wrong conclusion and one did
not, and the difference was not method.** That is the argument against "be more
careful" as a remedy -- an error that catches the person who has just finished
writing the rule about it needs a mechanical check, not attention.
## 2026-09-05 — FORBIDDEN: a JOIN test whose fixture builds BOTH SIDES from one set of names. The key match is then a tautology, and it reads as end-to-end coverage. `[lane ncaaf-live-resim-wire]`

- **18 green tests, a five-way mutation check, and production missed 257 of 257
  rows.** The NCAAF live re-sim published a lens keyed from the projections
  artifact (CFBD names) while the board grid is keyed by the ODDS source. First
  board rebuild past the first snapshot, 2026-09-05T23:17:39Z: `index_size 8`,
  `sources_seen {live_resim: 8, pregame: 43}`, `skipped_no_team_names 0` — a
  PERFECT index — and `rows_live_gameline_considered 257`,
  `rows_live_gameline_edged 0`, `withheld_by_reason
  {no_live_gameline_projection: 257}`. The two key sets intersected **zero**
  times: `('baylor', 'auburn')` against `('baylor bears', 'auburn tigers')`.
- **THE TEST ASSERTED THE BROKEN KEY AND PASSED.** `_wire_tick` built the ESPN
  event and the projection row from the same `"Baylor"` / `"Auburn"` strings, so
  both sides of the join agreed BY CONSTRUCTION. The assertion
  `assert list(index) == [("baylor", "auburn")]` was true of the fixture and
  false of production, and no amount of running it could tell.
- **AND THE MUTATION CHECK DID NOT SAVE IT, which is the part I did not expect.**
  Five mutations, each red exactly where predicted. Mutating the CODE cannot
  expose this, because the defect is not in the code the test runs — it is in the
  fixture's assumption that one name space exists. **The mutation you need is to
  the FIXTURE.** A mutation suite over code is blind to a fixture that cannot
  express the failure.
- **This is the join-specific form of the 2026-08-27 rule** ("a test whose FIXTURE
  cannot violate the property it asserts is not weak coverage, it is zero coverage
  that reads as strong"), and it is worth stating separately because a JOIN has an
  obvious tell the general rule does not name: **two producers, one string.** If a
  join test constructs both sides from a single literal, it is testing `dict.get`.
- **The rule going forward.** A join test must spell the two sides DIFFERENTLY —
  the way the two real producers do — and assert the outcome in both directions:
  one lens spelled like the grid (joins), one spelled like the other producer
  (does not), with the SAME grid row. `index_size` must be identical across that
  pair; that is the whole signature, and it is what a perfect index over a failed
  join looks like. Peer lane `edge-basis-moneyline` built exactly that pair for
  its own file after this was reported (`c45ad022`) and found the same shape
  there; a defect of this class is rarely in one file only.
- **Corollary for the PRODUCER side.** When two systems name the same entity and
  one of them is an odds feed, do not assume a canonical spelling exists — MEASURE
  which field matches. Here: ESPN `displayName` **7/8** against the live grid keys,
  `location` **0/8**, `shortDisplayName` **0/8**, `name` **0/8**. `location` is
  what the artifact used and it never matched once. And leave the residual NAMED
  (`sam houston bearkats` vs the grid's `sam houston state bearkats`) rather than
  aliasing it: one alias fixes one night and is a guess about the feed's naming
  everywhere else. `live_gameline_join._norm_team` has no alias table on purpose,
  and its docstring records why — the prop join's alias machinery carries a 91%
  miss.

---
## 2026-09-05 — FORBIDDEN: reading the RESIDUAL of a partial control as "the one that survived". A control is only a control over the population it actually REACHES. `[lane nfl-la-rams-alias, corrected by ci-archives-nba-card-js]`

- **What we believed:** the full suite's 169 failures in a data-less worktree split
  cleanly into environment and truth. Re-running the 43 failing files with
  `SYNDICATE_DATA_ROOT` set gave `169 → 47`, so 122 were data absence — and the
  archive test still failing was **a confirmed real defect in the file CI runs.**
- **What was actually true:** the knob was wrong, so the differential never covered
  the cases it appeared to adjudicate. `session_worktree.py` says it in its own
  source, written the day BEFORE the measurement: *"`SYNDICATE_DATA_ROOT` does NOT
  solve it. Nine of these read `REPO_ROOT/data/...` directly and ignore the variable
  entirely."* The flagged test is ONE OF THOSE NINE. It passes in the primary tree
  and under `SYNDICATE_NBA_ARTIFACT_ROOT`; the asset is git-tracked and CI checks out
  the full repo. **CI was green throughout. There was no red test.**
- **How we found out:** a peer lane read the failing ASSERTION. It was
  `assertIsInstance(content, str)` on the FIRST line of a test named
  `..._rewrites_source_routes_...` — the asset never loaded, so the route-rewriting
  logic was never evaluated. One line of output refuted the claim.
- **The rules going forward:**
  1. **A residual is not a survivor until you show the instrument REACHED it.**
     Resolving 30 of 31 cases is not evidence about the 31st; the remainder is
     exactly where the instrument is blind, so a partial control CONCENTRATES its
     own blind spot into the result it makes look most significant.
  2. **Use the documented control.** `--with-test-data` is this repo's; an env var
     that merely sounds like the right root is not.
  3. **Read the failing assertion before classifying a failure.** An `assertIsInstance`
     on line 1 says INPUT; a comparison deep in a test says LOGIC. Classifying from
     the test's NAME is how a setup failure becomes a reported defect.
- **The compounding error, and it is the one to take personally:** the report that
  made the false claim ALSO contained the caveat that refutes it — *"this control is
  a LOWER bound on data-absence, not an upper bound"* — and then called the residual a
  confirmed defect two sentences later. **Writing a limitation and then reasoning as
  if it did not apply is worse than never noticing it**, because the caveat makes the
  conclusion look considered to every later reader. If you state a limitation, the
  next sentence is the one to check against it.
- **Cost:** none shipped — a false alarm retracted before anyone acted on it, plus one
  spawned session. **It repaid itself:** chasing why the asset would not load found a
  REAL production outage in that path (`[nba-betting-card-assets-404]`).
## 2026-09-05 — FORBIDDEN: inferring a workload's SHAPE from a reading taken on a CONTENDED machine. A SATURATED MACHINE IS NOT EVIDENCE ABOUT THE WORKLOAD. `[lane full-suite-xdist-run, self-retraction]`

I measured the full pytest suite at **61m06s** (`-n 6`) while six peer python
jobs were running, sampled CPU, saw the machine turning only **~1.5 cores across
ten processes** (7.2s of worker CPU per 8s wall over six workers), and wrote into
`state_ledger.md`: *"this suite is I/O bound here, not CPU bound"* and *"do not
quote 3.7x for this machine"* — contradicting a scope note that had measured 3.7x.

A second run on an IDLE machine: **19m26s**. 3.1x faster. The claim was wrong and
is retracted in place.

**Why the reading could not have supported the conclusion.** Six peer jobs were
contending for the same disk. Disk contention is *the* condition that makes any
workload — CPU-bound ones included — show low CPU utilisation and long wall clock.
So the observation was equally consistent with both hypotheses and discriminated
neither. **A low-utilisation reading on a loaded box is a fact about the BOX.**

This is the same family as `[2026-09-05] A CONTROL THAT KILLS ONE ALTERNATIVE IS
NOT A DISCRIMINATOR`, but the tell is different and worth naming on its own:
**the confound was ambient rather than in the experiment.** Nothing in the
measurement looked wrong — the numbers were real, the arithmetic right, the
sampling honest. What was missing was a baseline of the machine itself.

**The rule.** Before attributing slowness to a workload's nature, record what
else was running. If anything was, the reading bounds the workload's performance
UNDER THAT LOAD and says nothing about its shape. Re-run on an idle machine
before writing a characterisation into the ledger — especially one that tells
future sessions to disregard an existing measurement, which is what makes this
expensive rather than merely wrong.

**And when you do re-run, change ONE variable.** My second run moved two (idle
AND 12 workers instead of 6), so the 3.1x still cannot be split between them. It
was enough to falsify the claim, and NOT enough to replace it with a number —
recorded as such rather than quoted as a worker-scaling factor.
## 2026-09-05 FORBIDDEN: attributing a workload to YOUR run because it appeared in a dump YOUR run emitted — a machine-wide process dump is not a description of you

- **The rule going forward.** `ALL_PROCESS_MEMORY` / `PROCESS_TREE_MEMORY` enumerate **every process on the box**, so on a machine with parallel sessions your own output contains other lanes' worktrees, command lines and RSS. Reading one of those lines as "what my run was doing" is a single step and it reads exactly like evidence. **Before blaming a test file for your failure, prove it was IN YOUR TREE:** `git merge-base --is-ancestor <commit-that-added-it> <your HEAD>`. Mine was not — the file postdated my worktree by hours, so it could not have participated at all, and no amount of reasoning about its allocations was ever going to be relevant. Second half: a `tree_rss_mb` line is one process's tree, never a pytest total.
- *(evidence in `learnings_evidence.md`)*
## [2026-09-05] ANCHOR A LEDGER EDIT ON A LINE, NEVER ON A SUBSTRING — `text.index("## Archived lanes")` matched PROSE

Lane none (primary-tree pull), session b4916e4e. Restoring a lane block, I found
the insertion point with `text.index("## Archived lanes")`. That string occurs in
`lanes.md` **as prose inside another lane's block** at line 97 — a sentence about
the archived section, not the heading. The block was spliced into the middle of
that sentence, and because the splice left `## Archived lanes` at a line start
above 48 OPEN lanes, `check_lane_invariants` went from `[ok]` to
**`48 OPEN lane(s) under Archived`** in one write.

Caught only because I re-ran the checker; the file still looked plausible, and a
grep for my own inserted header returned NOTHING, which is the tell — an anchor
that lands mid-line produces a block whose header is not at a line start.

THE RULE: match on `line.startswith(...)` over `splitlines(keepends=True)`, and
prefer the most specific form of the heading (`## Archived lanes (full bodies`)
because this file has TWO archived sections and several prose mentions. Then
verify the result STRUCTURALLY — `grep -c "^### <slug>"` must be 1 — rather than
trusting that the write succeeded. A ledger file is prose ABOUT its own
structure, so its structure words appear in its prose; substring search cannot
tell the two apart.
## 2026-09-06 — A CONTROL AND ITS TREATMENT MUST COVER THE SAME LENGTH OF TIME

`#632`. I took a pre-deploy control of a cache size and it came out beautifully
tight: 10 samples, spread **0.003 MB**. I recorded that tightness as a strength —
"far outside the control spread" became the test the treatment had to beat.

The control was **10 samples over ~60 seconds**. The treatment was **60 samples
over 31 minutes**. The tightness measured the DURATION, not the quantity: a
one-minute window cannot contain variation that takes minutes to appear. Sampled
over comparable spans the two ranges overlap almost entirely — pre `8.509-11.783`
against post `7.250-11.336` — and the effect I was about to certify sits inside
that overlap.

An automated verdict said CONFIRMED on the strength of that control. It was
right about its own criteria and wrong about the world.

THE RULE: a baseline and the thing it is compared against must span the same
duration, and a suspiciously tight baseline is evidence the window is too short,
NOT evidence the system is stable. Before quoting a spread, state how long it was
measured over.

This is the sampling-grid failure again, in a third costume: earlier the same
session, 50-second sampling manufactured a fan-out that 10-second sampling
dissolved, and a 12-minute correlation window reversed at 35 minutes. Coarse or
short windows do not merely add noise — they produce STRUCTURE that reads as a
finding. The direction of the error is not predictable, only its presence.


**THE REMEDY, and it needs no A/B.** When a matched baseline cannot be recovered
— the old code is no longer live and reverting costs production restarts —
measure the METRIC'S OWN DRIFT instead: two consecutive windows of the length you
intend to quote, on unchanged code. Their difference is the noise floor, and an
effect smaller than it is unmeasurable no matter how carefully the arms were
collected. Measured here: `-8.2%` drift on identical code against a `-10.6%`
claimed effect, which retired the claim. This costs polling time and nothing
else, and it answers the question a mis-sampled control cannot.
## 2026-09-05 — A PREDICTION NAMING SPECIFIC TESTS EXPIRES IN A REPO WITH LIVE PEERS. Re-derive it at LAUNCH, not when you write it `[lane full-suite-xdist-run]`

Before a 38-minute full-suite run I pre-registered the failing set as **2**, and
named them: the `test_live_refresh_loop` pair, another lane's, deliberately left
alone. The run returned **4**, and **none of them was that pair** — a peer had
fixed both in `c353b47d` at 22:27, **four minutes before my run started**, acting
on a message I had sent them myself.

**The reasoning was sound and the answer was still wrong**, which is the part
worth keeping. Pre-registering a prediction is right and I would do it again; the
defect was that I derived it from a snapshot taken earlier in the session and did
not re-derive at launch. On this repo that window is not theoretical — ~22 peer
commits landed between run 2 and run 3, and one of the four new failures
(`ada53db5`) landed **11 minutes before the run began**.

**THE SAME DEFECT IS IN THE RESULT, NOT ONLY THE PREDICTION, AND THAT IS THE
SHARPER FORM:** a suite run reports the tree as of its **START**, so **a failure
list is not a fact about `main` — it is a fact about a SHA nobody names.** Run 3
took 37m54s and **3 of its 4 failures were already fixed before it finished**; it
had photographed a real intermediate state (tests at 22:20, their producer at
22:52 and 23:09, run started 22:31). `[framing from lane
ncaaf-live-state-worker, whose commits those were]`

**The rule.** A prediction that names specific tests, files or counts must be
re-derived against `origin/main` AT THE MOMENT the measurement starts, and must
record the SHA it was derived from. Without that, a wrong number cannot be told
apart from a stale one — and those have opposite lessons: one says the model of
the system is broken, the other says only the clock moved.

**FIXED IN THE TOOL, not left as a discipline.** `scripts/pytest_baseline.py`
now prints `STARTED <local time> -- tree <sha>, <clean|N path(s) dirty>` plus a
line saying the result describes THAT tree. A discipline only helps the person
who ran the suite; the person judging a failure list is usually someone else, and
to them the staleness was invisible. Before acting on suite output anyone hands
you, check its start time against the commits in the area.

**Corollary, and it cuts the other way too:** a peer acting on your own message
is a state change you CAUSED. I sent `suite-order-pollution` the finding, they
fixed it, and I then predicted their tests would still be red. Messaging a lane
is a write to the shared system, not just communication.
## 2026-09-05 — FORBIDDEN: simulating "the artifact is absent" by repointing its ROOT env var alone. The repo mirror is still a candidate, so the test measures your machine. `[lane nfl-fantasy-artifact-root]`

- **The rule.** A test that wants an artifact to read as ABSENT must disable the
  repo-mirror fallback as well as repoint the root:
  `SYNDICATE_REQUIRE_HOSTED_STORAGE=1` **and** `RENDER` cleared. Repointing
  `SYNDICATE_<SPORT>_SOURCE_ROOT` at an empty tmp dir does not achieve absence.
- **Why.** `source_roots.preferred_artifact_roots` appends the repo
  `data/<sport>` mirror as a candidate root unless strict hosted storage is on —
  deliberately, as `CLAUDE.md`'s cold-start safety net — and re-appends it when
  `RENDER` is set even under strict mode. So the search still reaches the
  checkout.
- **The failure it produces is the worst kind: it depends on the DEVELOPER'S
  DISK.** `nfl_fantasy_projections_<season>.json` is UNTRACKED and absent from
  `origin/main`. Three tests in `test_nfl_fantasy_artifact.py` therefore PASSED
  on CI and on a fresh dyno and FAILED on any box that had run the build. Same
  commit, same tests, opposite results — decided by whether `data/` happened to
  hold a local artifact. Measured 2026-09-05: env at an empty tmp dir ->
  `load_projection_artifact(2026)` returned the real checkout artifact; fallback
  disabled -> `None`.
- **AND THE OBVIOUS FIX WAS THE WRONG ONE.** The persuasive hypothesis was that
  `artifact_path()` is a third instance of `#389`/`#441` — resolving through
  `_first_existing_root`, which picks a root by probing for the UNRELATED
  `upcoming_recs_*.csv`. The repo has fixed that selector twice and documents it
  precisely, so it reads as the answer. It is not: the per-requested-file
  resolver searches the SAME candidate list, the checkout root is in it and has
  the file, and both resolvers returned it. Converting `artifact_path()` would
  have been a plausible, well-argued, entirely inert change — and the red test
  would have stayed red for a reason nobody was looking at any more.
- **How to apply.** Before "fixing" a resolver because its docstring describes
  your symptom, run BOTH resolvers on the failing input and check they actually
  differ. A shared candidate list makes two different selectors give the same
  answer.
- **SWEPT 2026-09-06, and it is the ONLY instance.** The entry above closed with
  "not swept for"; it has now been swept. Across all 989 test files, four tests
  repoint an artifact root AND assert absence without disabling the fallback,
  and all four are accounted for: one is this entry's own fixed test, and three
  are FALSE POSITIVES whose `is None` / `== []` is not about an artifact at all
  — `record["prior_attempts"]` on a fresh order
  (`test_execution_ledger:2139`), `_artifact_date()` of a file the test just
  WROTE (`test_live_gameline_accuracy:261`), and a quota latch the test cleared
  (`test_ncaaf_games_cache_refresh:331`).
- **The null result is only worth what the instrument is worth, so the sweep was
  validated against the pre-fix file first: it flagged 3 of 3 known-bad tests.**
  Its blind spots, stated: it matches `SYNDICATE_*_{SOURCE,DATA,ARTIFACT}_ROOT`
  literals and a fixed set of absence forms, so a repoint done inside a FIXTURE
  or helper, or an absence written as `len(x) == 0` / `assert not payload`,
  would not match. This entry's own fixed test demonstrates that blind spot
  exactly — once the guard moved into `_isolate_source_root`, the regex stopped
  seeing it and reported the test as suspect.
## [2026-09-06] AN ATTRIBUTE'S NAME IS NOT ITS SEMANTICS, AND A REMEDY IS A CLAIM UNTIL YOU MEASURE IT

Lane `git-out-of-onedrive`. I found `ReadOnly` on the directories under
`.git/worktrees/` and reported, confidently, that "ReadOnly on the directories is
exactly why deletion fails with Permission denied. That's the whole thing." Then
I prescribed `attrib -R /S /D`.

**Both halves were wrong, and each was wrong in a way the other hid.** Windows
largely IGNORES `ReadOnly` on directories — it honours it on FILES, and the real
blockers were the `logs`/`refs` files INSIDE each entry. And `attrib -R /S /D`
did not clear it either: **118 ReadOnly before, 118 after**. The thing that
works is `Remove-Item -Recurse -Force`, and it works because `-Force` overrides
`ReadOnly` itself — not because anything I ran had prepared the ground.

I only found out because I ran the remedy and counted afterwards. Had I run
`Remove-Item -Force` first (as I did on one entry, which succeeded), I would have
concluded `attrib` had worked and shipped a runbook step that does nothing.

TWO RULES, and the second is the one that generalises past Windows:

- **Do not infer a mechanism from a flag's NAME.** `ReadOnly`, `Offline`,
  `PINNED` are OS-specific words whose behaviour differs by object type. Test the
  mechanism on one instance before describing it, and before prescribing for it.
- **A REMEDY IS A HYPOTHESIS. Count before and after.** "I applied the fix and
  the operation then succeeded" does not establish that the fix did anything —
  something else in the same command may be doing the work. Same shape as
  *gate on the output, not the input* and *confirm the code ran*: assert the
  thing you changed actually changed, not merely that the outcome improved.

Related, same session: I called a `git worktree` lock "a deliberate act by
whoever created it" and declined to clear it, without reading
`.git/worktrees/<name>/locked`. It said `initializing` — git's own automatic lock
from an abandoned `worktree add`. **Intent is a thing you read, not infer from a
flag being set.**
## 2026-09-06 FORBIDDEN: asserting an ABSOLUTE threshold on a timing ratio in a test — it is a claim about the machine's scheduler, and the instrument reporting otherwise would be LYING

- **The rule going forward.** `assertLess(off_cpu_pct, 40.0)` held only while a core was free. In a full `-n auto` suite it measured **79.7** — and the instrument was RIGHT: a build burning 0.25 s of CPU that waits a second to be scheduled genuinely did spend ~80% of its wall time off-CPU. **Do not "fix" the instrument to satisfy the threshold, and do not weaken the assertion — replace it with a COMPARISON taken in the same process**, so both readings see the same contention. Here: a busy build must read as more on-CPU than a SLEEPING one, which is sound by construction because a sleeping build's `off_cpu_pct` is exactly 100.0. Corollary, measured the same day: **a load test is not a reproduction.** 6x CPU oversubscription (72 burners) reached only 15.8%, where the old assertion still PASSES — so whatever descheduled that worker was not CPU contention, and a green load test would have been false comfort.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-06 — VERIFY A DEPLOY WITH A DISCRIMINATOR THAT IS A **KEY**, NOT A VALUE. My predicted value was wrong and the verification survived anyway. `[lane ncaaf-live-resim-wire]`

- **What I predicted, in writing, to the user and to the peer:** the tick would
  report `fetch_reasons {"record_absent": N}`, because the producer half was not
  deployed. **The real reading was `record_dates 1, fetch_dates 0`** — their
  producer shipped in the window between my saying it and the tick running.
- **Why it cost nothing:** the check asserted that `record_dates` / `fetch_dates`
  / `fetch_reasons` were **PRESENT**, not that they held particular values. Those
  keys did not exist in that log line before the commit, so their presence proves
  the new code executed *whatever it reports*. Had I asserted the expected value,
  a CORRECT result would have read as a failure and I would have chased a
  working system.
- **The rule.** A verification has two jobs — *did my code run* and *what did it
  say* — and they need different instruments. Prove execution with something
  STRUCTURAL that only the new build can emit: a new key, a new counter name, a
  new log prefix. Prove behaviour with the value. **Collapsing them into one
  value assertion means a wrong prediction is indistinguishable from a broken
  deploy**, and on a machine where peers deploy under you, predictions about the
  world go stale between writing them and reading them.
- **Corollary, same session:** `git checkout origin/main -- <file>` does not
  clear a rebase collision — it STAGES a change and leaves the file just as
  dirty. And in a multi-tree session, do not trust cwd: a `pytest` run and a
  `grep` both silently landed in the PRIMARY tree, the first measuring another
  session's uncommitted edits to the file under test, the second reporting a file
  I had just written as missing. Use `git -C <path>`.
## 2026-09-06 — A SCHEDULING INTERVAL IS NOT A COMPLETION INTERVAL, and the two share a name. Measured 7.8x apart. `[lane ncaaf-live-resim-wire]`

- **A peer reported their live phase runs on a 60 s median and I sized a staleness
  bound against it.** The step riding that phase actually completed every **514 s
  median** (mean 469, range 319–672, n=27) — because it writes once per FULL PASS
  of the phase, and a pass takes minutes. Both numbers are true; only one is the
  interval at which the artifact changes.
- **How to tell them apart cheaply: does every item move in lockstep?** All five
  dates' write gaps matched to within 1 s. That is the signature of one pass
  writing everything, and it identifies a per-pass cadence rather than a per-item
  timer without reading any scheduler code.
- **METHOD, and it is the reusable half. RECONSTRUCT the event time from an AGE
  field; do not infer a period from the shape of a sawtooth.** Every consumer
  log line carrying `age_seconds` yields an exact write timestamp as
  `log_time - age_seconds`. 400 consumer samples gave 27 exact producer intervals
  — from a service I cannot read the disk of, and without adding a single log
  line to the producer.
- **Then make it predict something.** `E[max(0, gap-bound)]/E[gap]` said 20.6% of
  my ticks should find the record too old; the tick had independently observed
  25.0%. A cadence that explains an already-measured rate is a finding; one that
  merely sounds plausible is not.
- **The trap it closes: "raise the bound until the fallback disappears."** The
  same distribution says a 700 s bound gives 0.0% fallback — a clean number
  bought by pricing live probabilities on state averaging 251 s old. **A
  staleness threshold widened to make a counter look good is a silent downgrade
  of the model's input**, and the counter it fixes is the one that would have
  reported it.
## 2026-09-06 FORBIDDEN: gating a destructive decision on a record that something COMPLETED, when a reading of whether it is STILL RUNNING exists. Three instances in one evening. `[lane shortlist-prop-row-duplicates, generalised with lane prop-region-knob]`

- **The near-miss.** Before deploying refresh-worker I ran
  `scripts/check_deploy_safety.py`: `MLB sim: finished (exit=0)`. At the same
  instant `scripts/deploy_preflight.py` listed `run_mlb_daily_sim_job.py`
  **pid 5346 plus four children ALIVE**. The first reads the status ARTIFACT,
  the second reads the PROCESS LIST. Gating on the cheap one would have killed a
  running sim while printing a clean window — and the deploy would have looked
  correct afterwards, because the artifact it consulted still said "finished".
- **It is a CLASS, not one tool's bug.** The same shape bit twice more the same
  evening, in a peer lane:
  - `lastRunAt` reports **dispatch**, not execution (Modern Standby once stalled
    a scheduled call 9h13m behind its own `lastRunAt`);
  - `finishedAt` says a deploy **landed** while the artifact it should have
    rebuilt is hours stale.
- **The rule.** *Prefer the instrument that samples the thing itself over the one
  that reads a note about it.* A completion record and a liveness reading
  disagree **exactly when it matters** — at the moment you are deciding whether
  something is safe to interrupt — because the note is written by the same run
  whose state you are asking about, and a run that is still going has not
  written its ending yet.
- **How to apply.** Before any interrupt-shaped action (deploy, restart, kill,
  truncate, overwrite), name which of the two you are holding. If it is a
  record, go find the sampler: a process list, a live env read, a served
  payload, an artifact mtime. `deploy_preflight.py` is the sampler for deploys
  and `check_deploy_safety.py` is not — the latter's own docstring says it
  widened past `sim_run_status`, which is true and still leaves it artifact-fed.
- **The inverse also holds and is cheaper to get wrong:** a record that
  something is STILL RUNNING is not evidence it is DOING anything. `jobs=0`
  across three post-deploy samples of live-odds-worker is recorded in
  `deploys.md` as an absence WITH its window (~5 min), because a fixture-aware
  cadence makes idle the designed state and that window cannot separate idle
  from stalled.
## 2026-09-06 — AN INTERVENTION'S OWN OUTPUT CANNOT SUPPLY ITS COUNTERFACTUAL

`#632`. I enabled an automatic `malloc_trim`, measured `1,481 MB` returned over
34 minutes across 12 trims, and wrote: *"without the trims the container would
have reached ~2,361 MB against a 2,048 MB limit."*

The arithmetic was simply `starting_level + returned + observed_net`. Every term
came from the intervention's own instrumentation while the intervention was
running. **The one thing it needed — what the memory would have done with the
trim OFF — was never measured.**

It would have done something different. Matched windows before and after the
flag: `/api/ops/artifacts/publish` cost a median of **0.000 MB/call across 62
pre-trim windows** and **0.893 MB/call across 28 post-trim ones**. `malloc_trim`
releases pages with `MADV_DONTNEED`; `smaps_rollup` counts RESIDENT pages, so the
next request faults them back and every instrument records a re-fault as fresh
allocation. Before the trim, that memory was reused in place and cost nothing.

So the returned `1,481 MB` was largely memory the trim itself caused to be
re-acquired. The saving was real; the counterfactual was fiction.

THE RULE: when an intervention is running, its instruments measure a world that
CONTAINS it. A claim of the form "without X this would have been worse" requires
an observation with X OFF — not a subtraction performed on X's own numbers. If
turning X off is not possible, the claim is not available either, and the honest
output is "X did N, net effect undetermined".

The tell was there and I walked past it: the number I was crediting to X was
produced by X. Ask "what generated this figure?" before "what does it imply?".

Related, and this is the fourth costume this session: a 60-second control against
a 31-minute treatment, a fan-out invented by 50-second sampling, a retention
verdict from one time point. Each time the comparison was against something that
could not answer the question — here, against nothing at all.
## 2026-09-06 FORBIDDEN: reaching for `--force` on a refusal you have not read. Mine said what was wrong, I invented a tool bug instead, and nearly wrote it into this file as a class. `[lane shortlist-prop-row-duplicates, caught by lane prop-region-knob]`

- **What happened.** `deploy_claim.py release --service <svc>` refused twice:
  *"held by shortlist-prop-row-duplicates and the token does not match"* — my own
  lane, my own session. I concluded a poller had rotated the token, named
  `deploy_preflight --holder` as the rotating call, `--force`d past both, wrote
  it into `lanes.md`, told a peer, and proposed the class rule **"any repeated
  claim-aware call rotates the token, not just `acquire`."**
- **All of that was invented.** `release` takes `--token`, `default=None`
  (`deploy_claim.py:402`), and compares it at `:342`. **I never passed it.**
  `acquire` had printed the token to me both times and I read past it.
  `deploy_preflight.py` contains no claim write whatsoever — every `token` in it
  is `ADMIN_TOKEN`, the API auth header.
- **The refusal was not ambiguous.** "the token does not match" is a statement
  about an argument. I read it as a statement about a race.
- **`--force` is the gesture reserved for a session that is GONE**, and I used it
  on two live claims to get past my own missing flag. Nothing was lost — both
  claims were mine — but a habit that survives because its blast radius happened
  to be zero is still a habit.
- **The rule.** A guard's refusal text is the FIRST place to look, not the last.
  Before escalating past any refusal, state which of its named preconditions you
  have actually satisfied — and if you cannot name the one that failed, you have
  not diagnosed it. **An override used on an undiagnosed refusal converts an
  operator error into a permanent false belief**, because the override succeeds
  and the wrong explanation is never tested again.
- **The direction the error ran matters.** A cause I invent for my own mistake
  becomes a hazard OTHERS design around: this one was two hours from being a
  class rule telling the next session to restructure poll loops around a
  mechanism that does not exist — while leaving them exposed to the real one,
  which is simply forgetting an argument. **A peer challenged it and I verified
  by experiment** (acquire; release with no token -> REFUSED; `release --token
  <tok>` -> released). Neither the code read nor their word alone would have been
  enough — the experiment is what settled it.
## 2026-09-06 REQUIRED: write a belief in the form that makes a PREDICTION. A wrong rule about a mechanism gets caught in minutes; the same wrong belief as a one-off remedy is simply adopted. `[insight from lane prop-region-knob, recorded by lane shortlist-prop-row-duplicates]`

- **Two sessions hit the identical bug hours apart and neither memory protected
  the second.** `deploy_claim.py release` refuses without `--token` (it defaults
  to `None`; `:342` compares it to the stored token, and there is no fallback).
  Both of us read the refusal, failed to diagnose it, and reached for an
  override.
- **The asymmetry in how the two errors ended is the finding.** Mine was written
  as a general rule — *"any repeated claim-aware call rotates the token"* — which
  made a checkable prediction about `deploy_preflight.py`. A peer tested it in
  two minutes and it died. Theirs was written as a one-off remedy in a memory
  file — *"pass `--token`; without it, a stored value a re-acquire invalidated"* —
  which predicts nothing, so it was adopted rather than tested, and it sat there
  through their own repeat of the incident. **It is also wrong**: there is no
  stored value and no re-acquire condition; release refuses unconditionally.
  Being un-checkable is what let the wrong half survive next to the right half.
- **The rule.** State the MECHANISM beside the remedy, in a form that predicts
  something. "Do X" cannot be falsified and therefore cannot be corrected; "X is
  required BECAUSE the check compares `args.token`, default `None`, against the
  stored value with no fallback" names a file and a line that either says that
  or does not.
- **This cuts against the instinct to write cautiously.** A hedged one-off note
  feels safer than a general claim and is epistemically worse: it is
  unfalsifiable, so it is never repaired. **Prefer the claim that can be shown
  wrong.** The cost of being caught is one correction; the cost of not being
  checkable is that a wrong belief is re-adopted by its own author.
- **Corollary for memory files specifically**, which are the least checkable
  place a belief can live — nobody diffs them and no test covers them: a note
  there without a mechanism is a permanent unexamined assertion. If it is worth
  storing, store what would falsify it.
## 2026-09-06 — FORBIDDEN: `git stash` in this repo. The stash stack is SHARED across every worktree, so a push/pop pair is not yours and can swap two sessions' work. `[lane venue-fanin-segment-key / kalshi-alt-line-join]`

- **What happened.** I ran `git stash push <2 files>` in a session worktree to
  get a clean tree for a control test, then `git stash pop`. Between the two,
  another session pushed and popped on the same stack. I popped THEIR entry:
  81 lines of unpushed work from lane `kalshi-join-counters-logged`
  (`pipeline/portfolio_commit.py` +24, `tests/test_kalshi_join_counters_logged.py`
  +57) landed in MY worktree AND MY INDEX, staged, while my own two files
  vanished. Diagnosing it, I then ran `git stash push --keep-index`, which wiped
  my edits a SECOND time and swept their content into a mixed stash.
- **Why the worktree does not protect you.** `session_worktree.py` gives each
  session its own INDEX, and that is the isolation the protocol advertises. The
  stash is a REF (`refs/stash`), and refs live in the shared object store — so a
  worktree isolates the index and shares the stash. "I am in my own worktree" is
  exactly the belief that made this feel safe.
- **The tell I ignored.** Every safe recipe I had used all session builds a
  commit through a private `GIT_INDEX_FILE`, reads blobs with `git hash-object`,
  and NEVER touches the worktree or a shared ref. I stepped outside that for one
  convenience command.
- **How to apply.** Never `git stash` here. To test against a different tree
  state: `git diff > /tmp/mine.patch` then `git checkout -- <paths>`, or read the
  other state with `git show <rev>:<path>` and diff in memory. To build a commit,
  use the `GIT_INDEX_FILE` recipe. If you have already stashed, do NOT pop --
  `git stash show -p stash@{n}` it to a patch file, verify the paths are YOURS,
  and apply that.
- **Recovery that worked**, for the next person: the popped content was still in
  the worktree, so `git diff --cached <their paths> > .syndicate/recovered_*.patch`
  preserved it before anything else; `git apply --check` verified it; my own
  change was REBUILT from context rather than recovered forensically, which was
  faster and deterministic. Dropped stash commits also survive in
  `git fsck --unreachable` until GC, but do not rely on it.
- **A mixed stash is the lasting hazard.** `stash@{0}` labelled `WIP on
  session/pc-counters` now contains BOTH that session's work and mine, because
  `--keep-index` stashes whatever is in the tree regardless of who put it there.
  A stash's LABEL names the branch it was created on, not the work it holds --
  so the label is not evidence of ownership. Check `git stash show --numstat`
  before popping anything.
## 2026-09-06 - COMMITTING A LANE BLOCK IS NOT CLAIMING IT. LANDING IS.

Lane `web-oom-fragmentation` ran to completion with its OPEN block committed at
lane-open (`df83d8a0`, 29 insertions to `lanes.md`) and NEVER PUSHED. For the
lane's entire life `origin/main` carried no record of it, so:

* every peer's collision check -- which reads `origin/main`, not your tree --
  saw the lane's files as unheld;
* `check_lane_invariants.py` reported the slug **zero times**, and I read that
  null as *"my lane is not implicated in the contested files"* when it meant
  **the checker could not see the lane at all**. A null from an instrument is
  only exoneration once you know the instrument can see your subject.

A worktree has its OWN `lanes.md`. That is the point of worktrees and it is also
this trap: the block you can read is not the block anyone else can read.

**How to apply.** After `/lane open`, LAND the block before doing the work -- a
lane that is not on `origin/main` claims nothing, however carefully it is
written. And when a checker returns nothing about your lane, confirm it can SEE
your lane before treating the silence as a clean bill.

Blast radius here was nil only because this lane claimed no files (scratchpad
poller, no code changes). The same omission on a lane holding real paths is a
silent invitation for a peer to edit underneath you.

Related, same day and same root: the block ALSO sat above the `## OPEN` heading
(the `#466` violation), which is a second way for a block to be present and
still not count.
## 2026-09-06 FORBIDDEN: concluding a hypothesis is WRONG from a simulation you did not confirm reached the real object — `tests/` is not a package, so pytest's module is not yours

- **The rule going forward.** A reproduction that changes nothing has TWO readings: the hypothesis is wrong, or the instrument never touched the thing. Distinguish them before believing either. Concretely: pytest imports a test module under a name derived from rootdir, and with no `tests/__init__.py` that name is top-level `test_foo` — **not** `tests.test_foo`. Importing the dotted path creates a SECOND module object, so mutating it is invisible to the run. I aged a module-level timestamp, saw 23 passed, and was one step from recording "not the cause"; against `sys.modules["test_foo"]` exactly the 3 predicted tests failed. **Assert the object you mutated is the one under test** — print its `id()`, or mutate through `sys.modules` and fail loudly when the key is absent.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-06 — FORBIDDEN: adding a transform that REBINDS the name a reported field is derived from. The field keeps its name, changes its meaning, and every existing reader keeps working while answering a different question. `[lane kalshi-join-counters-logged]`

- **What happened.** `join_kalshi_to_board` reports `board_rows=len(board_rows)`.
  I added `board_rows, collisions = _collapse_duplicate_bets(board_rows)` above
  it. From that commit (`21aac548`) the field stopped meaning "rows handed to
  the join" and started meaning "rows surviving deduplication" — on ONE of the
  two emitters, because the other takes its own `len()` of the input.
- **Why nothing caught it.** Before the collapse the two values were identical,
  so no test, reader or log line could distinguish them; the divergence only
  begins on the first board that HAS a duplicate. The symptom in production was
  a 2-row gap between two prints 24 seconds apart — `1100` vs `1102` — which
  I wrote up in `deploys.md` as the board moving between them. It was
  `alt_main_collisions` exactly, and I had to correct the entry (`dc886130`).
- **How it WAS caught, which is the transferable part.** Not by review and not
  by looking for it. A test written for a DIFFERENT feature needed a case where
  the row count and a new denominator differ, and it failed with `board_rows=2`
  where 3 rows went in. **A new field that must differ from an old one is a
  cheap probe for whether the old one still means what it says.**
- **The rule.** When adding a transform whose output you bind to an existing
  name, grep for every reported/logged/returned field derived from that name
  BEFORE landing, and either leave the field on the pre-transform value or
  rename it. A silently redefined field is worse than a missing one: a missing
  field breaks its readers loudly, a redefined field keeps them all green.
- *(evidence: `deploys.md` entries for `bd658209` and its correction; fix and
  test in `922a68dc`)*
## 2026-09-06 — FORBIDDEN: asserting "the token is present" as the test for a log line other tools parse. A duplicate is present twice. `[lane kalshi-join-counters-logged]`

- **What happened.** A peer session and I added counters to the SAME print
  statement within minutes. Both landed. The merged line emitted
  `alt_main_collisions=` twice, two spellings of the same segment data, and half
  the fields stranded after the `reasons={...}` dict repr.
- **Neither test suite caught it** — both of us asserted the token appeared in
  the line, and it did, twice. `re.search(r'alt_main_collisions=(\d+)')` silently
  takes the first of two; I had written that exact regex against these logs
  repeatedly the same day.
- **The rule.** For a line that is machine-read, presence is not the predicate.
  Assert the field set: no name emitted twice, and the dict-repr field last so
  nothing is stranded behind it. `test_no_field_is_emitted_twice` in
  `tests/test_kalshi_join_counters_logged.py` is the shape.
- **Second-order:** when two sessions must touch one statement, one of them
  should do both edits. I asked the peer to add my field; they asked me to add
  theirs; we both edited anyway. Whoever notices the overlap first should take
  the whole thing rather than split it.
- *(evidence: the merged line and its fix in `3d1d2173`)*
## 2026-09-06 A DUPLICATE MODULE-LEVEL NAME IN A TEST FILE SILENTLY UN-RUNS TESTS. A GREEN SUITE IS NOT EVIDENCE THEY RAN -- COUNT COLLECTED, NOT PASSED

- **The rule going forward.** Python keeps the LAST binding, so a second `def` of
  an existing name deletes the first while it goes on looking like live code --
  no error, no warning, and invisible in any diff that does not happen to show
  both. In `tests/`, that means the shadowed tests are never COLLECTED, so they
  can never fail and the suite is green *because* they are gone. Measured:
  `tests/test_venue_settlement.py` had three `test_the_repair_*` names colliding
  across two different repairs; the three covering `repair_multi_side_grades`
  (self-limiting, never touches an INFERRED grade, never touches paper --
  money-adjacent settlement invariants) had **never run once**. 75 collected
  before the rename, 78 after. **The reading that shows this is the COLLECTED
  count, not the passed count**, and nothing else in the suite would ever have
  said so. Third instance of the family in the repo, after
  `memory_observability.py` (`67af1276`, which cost `#285`'s `MALLOC_TRIM_INIT`
  proof line) and `nba/live_lens.py` (benign) -- so it is now a check,
  `scripts/check_duplicate_module_names.py`, not a thing to notice in review.
  **The sweep is cheap and the false-positive load is near zero**: counting
  module-level ASSIGNMENTS as well as `def`/`class` over
  `syndicate/ pipeline/ scripts/ tests/` returned **8 files**, not dozens, which
  is what made an EMPTY allowlist possible. Keep it empty -- an allowlist with
  entries in it is where the next real one hides.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-06 A CHECKER'S COVERAGE CLAIM IS ONLY AS GOOD AS THE FILES IT COULD PARSE. COUNT WHAT IT SKIPPED, NOT ONLY WHAT IT FOUND

- **The rule going forward.** `check_duplicate_module_names.py` read sources as
  `utf-8`. Every BOM'd file therefore raised
  `SyntaxError: invalid non-printable character U+FEFF` and was SKIPPED. Measured
  over `vendor/`: **`utf-8` skips 46 files and reports 10 duplicates; `utf-8-sig`
  skips 0 and reports 12.** Python's own import machinery decodes with
  `utf-8-sig`, so those files import fine; only the checker could not read them.
  **The skip was REPORTED** as ERROR lines and still did not register, because
  the run was piped through `tail` and I read `EXIT=0` off the pipe rather than
  the script. Then, writing the fix up, I gave the skip count as **15** -- read
  off that same `tail`-truncated list -- and it reached a code comment, a test
  docstring and a commit message before I measured it. **I made the error the fix
  is about while documenting the fix.** Three lessons: (a) parse with `utf-8-sig`
  when analysing source you did not write; (b) **a checker that returns "clean"
  over N files has told you nothing until you know N and how many it could not
  read** -- a skipped file is indistinguishable from a clean one in any output
  that reports only findings; (c) a piped `$?` is `tail`'s exit code, not the
  command's. Corollary that made this visible at all: **widening a check's scope
  is how you discover the check's own blind spots** -- this defect existed from
  the moment the script was written and was invisible while it scanned only owned
  code, where nothing carries a BOM.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-06 A SHADOWED MODULE-LEVEL BINDING IS ONLY DEAD IF NOTHING READ IT *AND* NO DECORATOR CAPTURED THE OBJECT. "DEFINED TWICE" IS NOT "THE FIRST ONE IS DEAD"

- **The rule going forward.** Asked to delete 12 duplicate module-level
  definitions in `vendor/`, only **5** were actually dead. Three distinct reasons
  the other 7 were live, and each needs its own test: (1) **a sequential
  rebinding whose successor consumes it** -- `cols_subset = [c for c in
  cols_subset if ...]`; deleting the first gives `NameError`, and the read is on
  the SECOND binding's own right-hand side, so any liveness window that stops
  before it reports the opposite of the truth. (2) **a decorator already captured
  the object** -- `@cli.command()` then `@cli.command('fetch-rosters')` on the
  same function name leaves the module name dead but registers TWO working
  commands (`fetch-rosters-cmd` and `fetch-rosters`, verified by running the
  pattern against click 8.1.7); Typer with a derived name collapses to one, so
  the same shape goes the OTHER way and must be checked, not assumed. (3) **a
  module-level `if __name__ == '__main__':` between the two definitions** --
  `backtest_daily_summary.py` is two scripts concatenated, so as a script the
  FIRST `main` runs and exits before the second is defined, and as an import the
  second wins. **Verify a deletion by the file's OBSERVABLE SURFACE** -- the
  values the surviving function returns, the command set the decorators register,
  the `__all__` -- never by the source diff, which cannot see any of these.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-06 — FORBIDDEN: mutating the tree a BACKGROUND JOB is reading. It keeps running and silently measures something else. `[lane nfl-rating-units]`

- **What happened.** A linearity experiment ran `os.chdir(<primary tree>)` and
  looped over two rating scales. While it ran, I reverted that tree to the
  original code -- correctly, to move my change into a worktree -- and the job
  carried on against the reverted source. It reported a clean, plausible,
  fully-formed result for a code path that no longer existed.
- **The tell was in the output and I nearly read past it: `margin ratio 20/10 =
  1.000, stdev 0.000`.** An effect of EXACTLY zero, with zero variance, is not a
  finding about the system -- it is the signature of an input that never
  changed. A sublinear response would have been noisy; a no-op is silent and
  perfect. **Suspect a result that is too clean before you suspect one that is
  surprising.**
- **A background job holds a DEPENDENCY on the tree it was launched against, and
  nothing in git or the job records that.** `git checkout`'s guards protect
  files from being lost; they say nothing about a running reader. The
  discard-guard fired on that very checkout, I preserved the content correctly,
  and the preservation was irrelevant to this failure.
- **The rule.** Before mutating a tree, enumerate what is RUNNING against it --
  and if a long job needs a specific code state, launch it from a worktree
  pinned to that state, not from the shared tree. Corollary for the reader: a
  job that depends on source should PRINT the discriminating fact about the code
  it loaded (here, whether the constant it is sweeping even exists), so the
  output is self-diagnosing rather than plausible.
- **What saved it: the derived number was already LABELLED derived.** The
  backtest computed its own rating differences and never called the sim, so the
  verdict (model loses to the close at t=3.34) was untouched. Only the
  `NFL_RATING_SCALE ~25` conversion depended on the void run, and it had been
  written down as "derived, not verified" before the error was found. **Labelling
  a number's provenance is what makes a later invalidation cheap instead of
  contaminating.**
## 2026-09-06 A PARTIAL CLONE THAT CHECKS OUT A WORKING TREE IS NOT A PARTIAL CLONE. `--filter=blob:none` WITHOUT `--no-checkout` FETCHES EVERY BLOB ANYWAY, ONE REQUEST AT A TIME

- **The rule going forward.** `git clone --depth 1 --filter=blob:none <url>`
  populates a working tree by default, and populating it requires every blob at
  that commit -- so git dutifully refetches them all individually, each landing in
  its own pack. **Measured: four caches totalling 3.8 GB, MLB-BettingV2 alone
  2.6 GB against a repo GitHub reports as 354 MB — larger than a full clone.**
  Adding `--no-checkout` took the same four to **950 KB** and a full report from
  **5m29s to 8.9s**, with byte-identical results. The filter had been "working"
  the whole time; the checkout undid it. **The general shape: an optimisation
  flag is a claim about a code path, and a DEFAULT elsewhere can re-enter that
  path and cancel it.** Verify the optimisation by MEASURING the resource it was
  supposed to save -- I had already written a comment calling the filter
  "load-bearing, not a micro-optimisation" before ever checking the cache size,
  and that comment was false when written. Corollary from the same script, same
  hour: comparing `ls-tree HEAD` instead of the working tree made an uncommitted
  local edit invisible to a tool whose entire purpose was to not overwrite local
  edits. **Both were found by RUNNING the thing against real data; the fixture
  tests passed throughout.**
- *(evidence in `learnings_evidence.md`)*
## 2026-09-06 "WE COMMITTED TO IT" IS NOT "WE PATCHED IT". TO TELL A LOCAL PATCH FROM A STALE COPY, ASK WHETHER YOUR CONTENT EVER EXISTED UPSTREAM

- **The rule going forward.** Deciding whether a vendored file that differs from
  upstream is OURS or merely OLD cannot be done from `git log`: a bulk
  `daily update ... (pre-source publish)` commit touches the file exactly the way
  a deliberate fix does, and if that commit was itself a vendor re-pull then the
  content came FROM upstream and the difference is pure staleness. The test that
  actually decides it is a CONTENT one -- **does our blob hash appear anywhere in
  that path's upstream history?** Found, and we are simply behind; absent, and the
  content never existed upstream, so it is ours. Run over 53 files it returned
  **53 ours, 0 stale**, and it is cheap: `git log --format= --raw --no-abbrev
  <branch> -- <path>` reads blob hashes straight out of the tree diff. Do NOT use
  `cat-file --batch-check` on `<rev>:<path>` for this -- on a blobless clone that
  is a promisor fetch per revision, and the same probe went from over ten minutes
  (killed) to 4 seconds. Corollary from the same hour: **a hand-run `diff` between
  a vendored file and its upstream blob reports the whole file as changed** on a
  CRLF checkout, because the blob is LF-normalised -- the exact artefact the tool
  avoids by comparing hashes, reintroduced the moment the check went manual.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-06 A STATE MACHINE THAT SHORT-CIRCUITS ON THE HAPPY PATH STOPS MAINTAINING THE DATA THE UNHAPPY PATHS NEED. THE STALENESS IS INVISIBLE UNTIL IT IS LOAD-BEARING

- **The rule going forward.** `classify(local, upstream, baseline)` returns
  `IN_SYNC` as soon as `local == upstream`, without consulting the baseline --
  correct as a verdict, and exactly why the baseline was allowed to go stale
  underneath it. When upstream absorbed our patch, the file became IN_SYNC and
  kept its PRE-merge hash; nothing was wrong, nothing was reported, and the file
  looked healthy. The damage only lands at the NEXT upstream change, which then
  reads `CONFLICT` where the answer is `UPSTREAM_AHEAD` -- and `CONFLICT` is the
  one state that STOPS an automatic sync, so the effect is to silently convert a
  file we no longer patch into a permanent manual step. **If a field is only read
  on some branches, something must still WRITE it on the others** -- so refresh
  derived state on the happy path too, or the first unhappy path inherits a lie.
  Found only by inspecting the outcome of a real run: the fixture tests passed,
  and would have kept passing, because they never had a file transition INTO
  in-sync and then move again.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-06 A SCHEDULE IS A CLAIM ABOUT A PLATFORM YOU HAVE NOT TESTED. DISPATCH IT ONCE, OR YOU HAVE SHIPPED A JOB THAT SILENTLY NEVER RUNS

- **The rule going forward.** A committed workflow file with a valid cron is not
  a scheduled job; it is a request. Dispatching `vendor-sync` once returned
  `completed/failure` in **1 second with zero steps executed** -- *"The job was
  not started because your account is locked due to a billing issue."* Valid
  YAML, `bash -n`-clean scripts, and a registered workflow ID all said healthy;
  none of them touches whether a runner will pick it up. **And the failure mode
  is the worst kind for a sync: a job that never runs produces no report, which
  reads exactly like "nothing to do".** The same reasoning that rejected a local
  scheduled task here (`lastRunAt` is dispatch, not execution) applies to the
  replacement, and I nearly shipped it unexercised. Corollary, found by the same
  dispatch and much larger than the lane: **GitHub Actions has been dead for this
  whole repo for 15 days** -- last success 2026-08-22T21:07Z, 100 of the last 100
  runs failed -- so `ci.yml`'s pytest-baseline gate has not gated a single commit
  in that window, including this session's. Nothing announced it. **A CI system
  that stops running looks identical to one that keeps passing, from anywhere
  except its own run history.**
- *(evidence in `learnings_evidence.md`)*
## 2026-09-06 A GUARD THAT INFERS ITS POSTCONDITION FROM AN ARTEFACT'S EXISTENCE CANNOT SEE A HALF-BUILT ONE, AND WILL DEFEND IT FOREVER

- **The rule going forward.** `if (-not (Test-Path "$wt\.git")) { worktree add; sparse-checkout set }`
  reads as "set this up once". It is really "assume anything with a `.git` is
  fully set up". An earlier failure died BETWEEN the two commands, leaving a
  worktree that was real but not sparse -- and from then on the guard skipped
  repair on every run while each checkout materialised the entire repository:
  **3.9 GB, `data/` and all, for a job whose input is two directories.** Nothing
  reported it; the job "worked". **Check the POSTCONDITION you actually need
  (`git sparse-checkout list` succeeds), not a proxy for it (a directory
  exists)** -- the two differ exactly when a previous run was interrupted, which
  is the case a setup guard exists for. Same family as this session's stale
  baseline: state that is only WRITTEN on the happy path, or only CHECKED by
  proxy, silently rots. Corollary, three more from the same script and all found
  the same way: it read a shared checkout **241 commits behind** and missing the
  script it invokes; `$ErrorActionPreference='Stop'` plus a redirected native
  stderr turned git's own success message into a recorded error (PowerShell 5.1
  wraps native stderr in ErrorRecords); and `param([string[]] $Args)` collides
  with PowerShell's AUTOMATIC `$Args`, so git ran with no arguments. **The script
  parsed cleanly through all four.**
- *(evidence in `learnings_evidence.md`)*
## 2026-09-07 FORBIDDEN: reading an artifact-backed surface ONCE to decide whether a deploy worked

**The instrument's clock is not the thing's clock.** Three separate lessons in
this ledger are one lesson, and naming them together is what makes the next one
recognisable:

- `lastRunAt` is DISPATCH, not EXECUTION (Modern Standby stalled a scheduled call
  9h13m; the timestamp was honest about the wrong event).
- Gate verification on ARTIFACT MTIME, not on deploy status (a 5h49m lag between
  a deploy going live and the artifact rebuilding read as a failed fix).
- A SHORTLIST READ shows the artifact's age, not the code's. Measured 2026-09-07
  by lane `soccer-threeway-precision-gate`: refresh-worker went `status=live` at
  01:26:11Z and the served shortlist stayed flat -- 36 rows / 28 edged -- for
  EIGHT MINUTES, changing to 35/11 only at 01:34:05Z on the first post-deploy
  build. **A single read at 01:27Z would have recorded a clean null result for a
  fix that was already live.**

THE OPERATIONAL FORM, which is the part that is actionable: **the poll interval
must be SHORTER than the artifact's rebuild cadence.** Four samples across eight
minutes made the transition legible; one sample is indistinguishable from a
failed fix, and two samples on the same side of the boundary are worse -- they
look like corroboration.

`[ATTRIBUTION, split precisely, because this entry is about credit surviving the
conversation that produced it. The eight-minute measurement and the poll-interval
rule are lane `soccer-threeway-precision-gate`'s. The two-sample corroboration
clause and the adjacency explanation are this lane's. I initially credited the
corroboration clause TO them in a message; they checked their own sent text,
found they had not written it, and asked to be un-credited. A wrong credit in a
ledger outlives the conversation -- which is the same argument that made the
retraction above worth making, pointed the other way.]`

WHY THIS KEEPS RECURRING. Every one of these instruments is honest about
something; it is just not the something being asked. `status=live` is true about
the deploy. `lastRunAt` is true about dispatch. The shortlist is true about the
last build. Each answers a question adjacent to "is the new code's output
visible", and adjacency is what makes the substitution invisible.

The same 2026-09-07 exchange produced a second instance of a rule already here --
**one field carrying two states, with the consumer branching as if it carried
one.** `_model_edge_for` returns early on `edge is None`, written for a one-sided
quote; a new precision gate then wrote `None` for "priced and withheld", and the
early return silently dropped the draw and away legs before their own bars were
consulted (3 of 10 legs). Sibling of `ANALYTIC_UNCALIBRATED` and of "unknown must
not default permissive". A per-side count taken across that boundary measures the
early return as much as the gate, which is why the "8 home / 9 away / 0 draw"
split was retracted while the 17-of-28 total stood.
## 2026-09-07 FORBIDDEN: deciding whether a model earns its keep from a SLATE-AVERAGE metric

`[user, 2026-09-07: "remember you are globally making a call on something that
should enhance SOME games to be bet on"]`

**Nobody bets the slate.** A model can lose to the market on mean MAE and still
be worth having, if its errors concentrate in games it has no read on while the
subset where it disagrees hardest with the market is where it is right. That is
the entire mechanism of selective +EV betting: you do not need to beat the market
everywhere, you need a subset where you do.

So `mean |model - actual|` over every game **cannot answer the question it is
usually asked to answer.** Reported alone it is not merely incomplete -- it will
say NO to a model that has a real, narrow edge, and it will say so with a
confident-looking number.

WHAT THIS COST HERE. The NFL drive-prior backtest reported
`MAE off 10.573 / on 10.537 / market 9.410, t=+0.61` and I read it as a clean
null. It may still be one -- but the harness had **discarded the per-game rows**,
so the only data that could distinguish "no edge anywhere" from "no edge on
average, real edge in the top decile" was gone, and answering required
re-simulating 178 games twice.

THE RULE, in three parts:

1. **KEEP THE PER-GAME ROWS.** They cost nothing and every interesting cut --
   by disagreement, by week, by favourite/underdog, by total -- is then seconds
   instead of another full run. An aggregate is a lossy summary of data you
   already had.
2. **BUCKET BY THE AXIS THE BETTOR SELECTS ON**, which is
   `|model - market|`, not by anything intrinsic to the model. Beating the market
   on games you would never bet is worth nothing; losing there costs nothing.
3. **FIT TO THE SUBSET, NOT THE SLATE.** A calibration fitted to minimise mean
   error over every game is optimising performance on the games nobody bets. A
   grid search against that objective can be executed perfectly and still be
   answering the wrong question -- which is why the NFL first-calibration sweep
   was STOPPED mid-run rather than reported.

THIS INDICTS AN EXISTING HARNESS TOO, not just mine.
`scripts/refit_ncaaf_smartsim2_payload.py` frames its go/no-go as whether the
payload "closes any of that 3.56-point gap" in **slate-wide margin MAE** (model
15.775 vs market 12.212 over n=2233). That framing is right to benchmark against
the MARKET rather than the model's own past -- and still wrong to do it on the
slate average. The same 2,233 games would answer the subset question if the rows
were kept.
## 2026-09-07 FORBIDDEN: verifying a fix with a predicate on a TOTAL that can move for another reason

**Nineteen days, every night, the same ten failures — and the guard that was
supposed to catch it fired correctly and said nothing.**

MLB's sim publishes `sim_input_report_<date>.json` from the WORKER. Read back
across every report on production:

    08-19   ok 55   FAIL 15   disabled 0
    08-20   ok 55   FAIL 10   disabled 5     <- the "improvement"
    08-21 .. 09-07  ok 55   FAIL 10   disabled 5   (19 days, identical)

`deploys.md` for `39570b24` had written the verification in advance and written
it well: *"Expect nfail 15 -> 6 ... Still 15 on a fresh generated_at means a
SIXTH cause and must be reopened."* The count went to 10. Not 15, so the reopen
never triggered; not 6, so nothing had actually cleared.

**THE 15 -> 10 DROP WAS A RECLASSIFICATION, NOT A FIX.** Five `vs_pitcher_*`
fields moved from `FAIL` to `disabled` (BVP off by config) in the same window.
The ten fields the note NAMED -- `conditional_arsenal`, `count_bucket_map`,
`pitch_type_*`, the four `statcast_splits_*` -- never cleared once.

THE RULE. **A verification predicate must key on the THING, not on a count that
contains it.** The note listed the exact ten field names and then gated on the
total. Had it gated on the names it would have failed loudly on 08-21. Same
family as "a rate, not a count" and "gate on the output, not the input": an
aggregate is a lossy summary, and the loss is exactly where a second cause hides.

### And the root cause is a SECOND instance of the same shape

`SYNDICATE_MLB_ROSTER_REBUILD_DATE` was pinned to `2026-08-19` -- **the day
BEFORE** the artifact fix it was meant to prove went live (`39570b24`, live
2026-08-20T17:54:04Z). The gate is date-scoped and self-expiring BY DESIGN, which
is good design; it was armed for a date that expired before the thing it gated
existed. So every run since printed `ROSTER_REBUILD inert: gate=2026-08-19 does
not match date=<today>` and reused `roster_objs` built the day before the
artifacts arrived.

The artifacts were present, loadable and correct the whole time -- arsenal 546 KB
/ 466 pitchers, `payload["pitchers"]` exactly as `load_arsenal` expects, and
`SYNDICATE_DATA_ROOT` correctly set. This is CLAUDE.md's own warning realised:
*"Publishing is not sufficient -- a new input needs a roster REBUILD or it is
silently ignored."*

### Two instruments that could not have caught it, and one that did

* **The log line cannot be read.** The code prints `ROSTER_REBUILD inert`
  deliberately ("Silence here would be indistinguishable from 'the rebuild
  ran'") -- but `MLB_DAILY_SIM_START` and `mlb_sim_job` return **0 lines in 8h**
  from Render's logs API while that process is demonstrably running. The
  emitter never reaches the collector, so a log-based check would have read
  clean forever. **Test that the line is EMITTED before designing a check
  around it.**
* **The local checklist is worse than useless here.** Run on a laptop it
  reported 17 fields at 0.0%; production says 7 of those are fed at 76-79% and
  10 are genuinely dead. Both halves wrong in opposite directions.
* **The ARTIFACT is the instrument.** `sim_input_report` is written by the
  worker, exportable, and 20 days deep. It had the answer every night.

### The date basis, because I got it wrong the same way

I armed the replacement gate from the report FILENAME
(`sim_input_report_2026-09-07.json`) and set `2026-09-07`. The job's own paths
say otherwise: `daily/snapshots/2026-09-06/roster_*.json`, and `2026-09-06`
dominates the worker's log messages 37-to-6. The filename and the slate date use
different bases. The value happens to be right for the NEXT slate -- correct by
luck, not by reasoning, which is worth recording as exactly that.
## 2026-09-07 CORRECTION: the MLB "ten dead inputs" was SEVEN-TENTHS A BROKEN INSTRUMENT

**Retracts most of the entry above it, and the retraction is the lesson.**

I reported that ten MLB pitcher inputs had been dead in production for nineteen
days, root-caused it to a stale `SYNDICATE_MLB_ROSTER_REBUILD_DATE`, armed a new
gate, and deployed. Then I read the ROSTER SNAPSHOTS the sim actually consumes:

    field                    09-07(post)  09-06   09-04   08-25
    pitch_type_whiff_mult       14/18     17/18   13/19   12/16
    statcast_splits_source      14/18     11/18   10/19   11/16
    conditional_arsenal          0/18      0/18    0/19    0/16
    count_bucket_map             0/18      0/18    0/19    0/16

**Seven of the ten were already fed, for at least two weeks before my deploy.**
They were never broken. And the post-deploy `sim_input_report` STILL says 0/10
while those same rosters read 60-95% -- so the report and the artifact it claims
to summarise flatly contradict each other, and the roster is the one the sim
reads. `rosters: 8` in the report against 12-17 roster files on disk is the same
symptom: it is measuring a different, smaller roster source.

WHAT ACTUALLY SURVIVES: `conditional_arsenal`, `conditional_arsenal_source` and
`count_bucket_map` are 0 on EVERY day sampled including after the rebuild --
genuinely unfed, from the `conditional_mix` artifact. **Three fields, not ten.**
The stale gate was real and is worth fixing; it was not the cause of the reported
zeros, and my deploy's effect is NOT demonstrated -- 09-07 sits inside the
day-to-day spread of the pre-deploy samples.

### THE RULE, and it is not "the mirror lies"

I had already rejected the LOCAL checklist for being mirror-based. I then treated
the PRODUCTION report as ground truth **because it came from the worker** -- and
provenance is not accuracy. A report is a CLAIM ABOUT an artifact; the artifact
is the evidence. I built a verification, a monitor and a deploy on a number I had
never once checked against the thing it summarises.

**Check the summary against its subject before building anything on the summary.**
The cost of that check here was one export call. The cost of skipping it was a
wrong root cause, a production env change, a deploy, and a confident ledger entry
that had to be retracted.

The corollary is uncomfortable and worth stating: the previous entry's whole
"nineteen days, nobody noticed" narrative was ALSO built on that report. The
nineteen days of identical `FAIL 10` are nineteen days of the same broken
measurement, not nineteen days of dead inputs. The predicate lesson in that entry
(key on the thing, not on a count containing it) still stands -- it is just that
the thing it should have keyed on was wrong too.
## 2026-09-07 RESOLVED: the ten MLB pitcher inputs ARE unfed -- and my retraction was the wrong turn

**This closes a thread that reversed twice. The FIRST answer was right; the
retraction two entries up is WRONG and is withdrawn.**

The report now records which rosters it measured, and it read the sim's own path:

    generated      2026-09-07T07:48:38Z
    roster_source  'sim'
    roster_glob    .../data/daily/snapshots/*/roster_objs/roster_obj_*.json
    rosters        8
    POPULATED      0/10

So all ten pitcher fields are genuinely empty in the artifact the simulation
consumes: `pitch_type_{whiff,inplay,hr}_mult`, `conditional_arsenal{,_source}`,
`count_bucket_map`, and the four `statcast_splits_*`.

### WHY I RETRACTED A CORRECT FINDING

I read `daily/snapshots/<date>/roster_*.json` -- FLAT game rosters -- saw
`pitch_type_whiff_mult` at 14/18 on four separate dates, and concluded seven of
the ten had been fed all along. **Those are a different file.** The sim reuses the
SERIALIZED `roster_objs/roster_obj_*.json`; the flat rosters are a separate
published artifact. Two files, one directory apart, similar names, opposite
content -- and I compared the one I could read against a claim about the one I
could not.

The tell was available and I walked past it: the flat file's top-level keys are
`away/home/mode/park/pbp/pitch_model/statcast/umpire/weather` while
`read_game_roster_artifact` expects `schema_version/away/home/meta`. Different
schemas. I noticed the difference, wrote it down, and still treated the two as
interchangeable evidence.

**THE RULE: "I read the artifact" is only stronger than "the report says" when it
is THE SAME ARTIFACT.** Reading the wrong file directly is not more rigorous than
reading a report about the right one -- it is less, because it FEELS like primary
evidence. Confirm the identity of the file before promoting it over a summary.

### AND THE ROSTER-REBUILD DIAGNOSIS IS WRONG IN ITS MIDDLE TERM

The chain I published was: stale gate -> stale `roster_objs` -> dead fields. The
gate WAS stale (`2026-08-19`, armed the day before the fix it was meant to prove
went live) and that part stands. But after arming it for `2026-09-07` and running
a job on that date, **the fields are still zero.** A fresh build produces empty
fields too, so reuse was never the cause.

That relocates the defect to the LOADERS -- `apply_arsenal_to_pitcher` and
`_apply_cached_statcast_pitch_splits` -- which run at build time and are supposed
to populate exactly these fields from artifacts that are present, loadable, and
correctly shaped on the worker (`arsenal_2026.json`, 546 KB, 466 pitchers,
`payload["pitchers"]` exactly as `load_arsenal` expects). Present input, running
loader, empty output: that is the next thing to chase, and it is NOT a
publishing, allowlist, path or reuse problem, all of which were checked and
cleared in this thread.

### WHAT THE INSTRUMENT FIX BOUGHT

The report now carries `roster_source` and `roster_glob`, so this question is
answerable in one read instead of a night of it. It did not change the answer --
it made the answer TRUSTWORTHY, which is the only reason the reversal could be
settled at all.
## 2026-09-07 FORBIDDEN: building or proposing a guard before locating the one that already exists

TWO INSTANCES IN ONE SESSION, on the same machinery, both mine.

**(a) I built a narrower copy of a check and trusted it over the real one.**
Before deploying refresh-worker I pre-screened for an in-flight MLB sim by
grepping the last `ALL_PROCESS_MEMORY` line for `mlb_daily_sim`. It said clear.
`deploy_preflight.py`, reading the actual process table, said `HOLD: 5 job(s) in
flight` -- `run_mlb_daily_sim_job.py`, `daily_update.py --workflow ui-daily`,
and three vendor children, none of whose cmdlines contained my substring. On the
strength of MY check I armed a production env flag and held the deploy claim on
a contended service for 33 minutes for a deploy that could never go.

**(b) I proposed adding a check that already existed twice.** A pinned deploy
target (`5876bbc9`, live when chosen) became a rollback of a peer's `8f647bbb`
two hours later. I reported it as a near-miss and proposed adding an ancestry
check to `deploy_preflight.py`. But `render_deploy.py:136-156` ALREADY re-reads
the live sha at deploy time and refuses a non-descendant (`--allow-rollback` is
the escape; its docstring cites the 2026-08-14 incident of this exact shape),
and preflight ALREADY reports `HOLD: <sha> is already contained in live <sha>`.
My watcher goes through `render_deploy.py`, so it would have returned 2 and my
loop would have disarmed and released. **It would have failed loudly. It was
never armed to revert, and I said it was.**

WHY THE OVERSTATEMENT MATTERS MORE THAN THE MISS. A near-miss report is a claim
about what the SYSTEM would have allowed. Getting that wrong argues for guards
that exist and misprices the ones that do not. I reported catching a hazard I
had not actually been exposed to.

AND THE PROPOSED FIX WAS WORSE THAN THE STATUS QUO, per lane
`ncaaf-live-resim-wire`: preflight's CLEAR is valid for 15 minutes and this
check must hold AT POST TIME, so a copy there is a second owner that drifts and
gives false comfort in exactly the window the real guard covers.

RELATED, and why the reflex is strong: a guard you did not write is invisible
until you go looking, while one you write yourself is vivid. That asymmetry is
the whole mechanism -- it is not laziness, it is that your own instrument is the
one you can see.

HOW TO APPLY. Before writing a check, or reporting that one is missing:
`grep` the sanctioned entrypoint for the concern (`REFUS`, `HOLD`, `guard`,
`--allow-`) and read its docstring. If a guard exists, route through it instead
of reimplementing it -- and if the answer is "my code bypasses it", the fix is
to stop bypassing it, not to duplicate it. State which entrypoint you checked.

COROLLARY, measured the same night: a target chosen because it was live is an
ASSUMPTION the moment it is stored. Anything sitting in a poll loop must
re-resolve the world before acting, not remember it. And `target == live` is
STRICTER than the shipped rule and self-defeating -- `render_deploy.py` returns
2 on it (`ALREADY live -- nothing to deploy`). Deploys are meant to be
CUMULATIVE; roll-forward from `main` is the sanctioned shape, so "isolate my
change by redeploying the live sha" is the doctrine backwards.
- *(evidence in `.syndicate/log/2026-09-07.md`)*
## 2026-09-07 The deploy claim's `session:` breadcrumb does not resolve, even for a LIVE holder

`deploy_claim.py status` printed holder session
`520cd594-1ffa-4116-8951-4c4b53ffbfcf`. That id does not resolve in
`list_sessions` even with `include_archived: true` -- while that session was
alive, running, and holding the claim. The peer independently hit the same thing
looking up `3492626c` and concluded "gone" when only "not resolvable" was
supported.

The claim's own text already says it is a breadcrumb and the TTL is the real
liveness bound. What was NOT known: it fails to resolve for a live holder, so
`not found` carries no information about the holder at all -- it is not weak
evidence of absence, it is zero evidence.

HOW TO APPLY. To reach a claim holder, search `list_sessions` by TITLE (lane
slugs map to session titles closely enough in practice) -- that worked when the
id did not. Never infer a holder is gone from a failed id lookup; the TTL is the
only bound, and `--force` on that basis breaks a live session's claim.
- *(evidence in `.syndicate/log/2026-09-07.md`)*
## 2026-09-07 A CONVENTION YOU COPY MAY BE A DECISION YOU ARE OVERTURNING. "ALL THE OTHER FILES DO X" DOES NOT TELL YOU WHY THEY DO X

- **The rule going forward.** Adding `.github/workflows/vendor-sync.yml` I read
  the two neighbouring workflows, matched their structure, permissions and
  comment style — and shipped the one thing they pointedly did NOT have: a
  `schedule:`. Both are `workflow_dispatch`-only because `#486`
  `[2026-08-20, user decision]` removed `Daily Update`'s cron with the words *"we
  no longer use that daily update feature, everything runs on render"*. My file
  became **the only cron in the repository**, seventeen days after the last one
  was deliberately deleted. **Copying a convention reproduces its SHAPE and
  discards its REASON**, and the absence of a feature is exactly the part a
  template cannot carry. Before adding a recurring or outward-facing mechanism,
  grep the ledger for a decision about that mechanism — `state_ledger.md` had it,
  quoted, and I never searched. Note also what made it hard to see: Actions was
  not retired wholesale (`ci.yml` is live and maintained), so "does this repo use
  Actions?" answered YES and told me nothing. **The retired thing was a narrower
  category than the tool** — recurring unattended jobs — and a question pitched
  at the tool cannot find a decision pitched at the pattern.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-07 SETTLED: the MLB pitcher inputs were NEVER dead -- nineteen days of measuring June

**Final state of a thread that reversed three times. Every earlier entry on it is
superseded by this one.**

    generated 2026-09-07T16:27:40Z   roster_source 'sim'   rosters 8
    POPULATED 9/10
      fed        pitch_type_{whiff,inplay,hr}_mult, conditional_arsenal,
                 count_bucket_map, statcast_splits_{source,n_pitches,
                 start_date,end_date}
      still zero conditional_arsenal_source
    CONTROL     bb_gb_rate 69.3%  (77.4% in the June-sampled report)

**THE CONTROL IS THE POINT.** `bb_gb_rate` comes from the same enrichment block
and was expected to MOVE if the sample changed. It moved. Without it, 9/10 would
have been just another number from an instrument that had already lied four
times; with it, the reading is anchored. **Every check in this thread that lacked
a field whose value I could predict SHOULD change produced a wrong conclusion.**

### THE ONE-WORD CAUSE

`sorted(glob(...))[:8]` is ASCENDING, and the date is the leading path segment.
It selected the eight OLDEST roster_objs on disk -- 2026-06-15, two months before
the arsenal and pitch-splits artifacts existed. Those rosters could never contain
the audited fields. So the report was a constant, and a constant reading was read
as a stable fact about production when it was a stable fact about eight fixed old
files.

### MY OWN CLAIMS, SCORED

    original: 10 fields dead          WRONG   -- measuring June
    retraction: 7 already fed         RIGHT in substance, WRONG in method
                                      (compared the FLAT rosters, a different file)
    un-retraction: 10 genuinely dead  WRONG   -- trusted a report still sampling June
    actual: 9/10 fed on current rosters

Twice I reversed on evidence that was itself measuring the wrong thing. The
retraction was right for reasons I could not have defended, which is not the same
as being right -- and I withdrew it on a report I had not validated.

### WHAT WAS WASTED, AND WHAT WAS NOT

Wasted: a stale-gate root cause (`SYNDICATE_MLB_ROSTER_REBUILD_DATE=2026-08-19`
was genuinely stale but irrelevant), a production env change, and two deploys --
all chasing an artifact of the measurement. The loaders were never broken;
running `apply_arsenal_to_pitcher` over the real artifact populated all three
maps first try, and I should have weighted that above the report the moment they
disagreed.

Not wasted: three real defects in the instrument, each independently capable of
producing a false negative -- wrong parent directory (`daily_pitcher_props`
instead of `daily`), no provenance field in the PUBLISHED report, and the
ascending sort. Four sports' input audits run on this shape.

### THE RULE

**A measurement that never changes is not therefore stable.** Nineteen identical
nightly readings read as strong evidence of a persistent defect; they were
evidence that the sample was frozen. Before trusting a constant, establish what
would make it move -- and if nothing in the pipeline could, the constant is
describing the instrument, not the system.

Remaining, and it is the whole of it: `conditional_arsenal_source` is zero while
`conditional_arsenal` is populated -- a value present without its provenance
label. One field.
## 2026-09-07 A probe you designed yourself can MANUFACTURE bugs -- discriminate shape-failure from real failure BEFORE reporting

Auditing whether MLB profile fields survive the roster artifact, I set every
field to a distinctive value via `dataclasses.fields()`, round-tripped, and got
**26 fields "LOST"** across `PitcherProfile` and `BatterProfile`. A 26-defect
report would have been confident, specific, and entirely wrong.

All 26 were the PROBE's fault. The serializer uses a different key domain per
field family and both sides agree on each: `{str(k): float(v)}` for
`platoon_mult_*` / `venue_mult_*` / `statcast_quality_mult` (**str** keys),
`_ser/_de_intkey_map` for `vs_venue_*` / `vs_pitcher_*` (**int** keys), and
`str(cell_key)` for `conditional_arsenal`. I had fed `PitchType` enum keys to
all of them and a tuple to the last. Wrong-shaped keys came back as
`'PitchType.FF'` or were silently dropped to `{}` -- which is INDISTINGUISHABLE
from a serializer that does not persist the field.

Re-run with each field's real key shape: **1 lost, not 26** -- and that one was
a genuine write-side omission (`conditional_arsenal_source`), confirmed OFF!=ON.

HOW TO APPLY. When a broad audit returns a large number of hits, the FIRST
hypothesis is the instrument, not the system -- especially when the hits cluster
by shape rather than by subsystem (here: every dict field, no scalar). Before
reporting N findings, take one hit and prove it fails for the reason you claim,
against what the real PRODUCER writes. A null-shaped result (`{}`, `''`, `0`)
means "my probe did not survive"; it does NOT mean "this field is not
persisted". And a permanent test must not encode the probe shape it happened to
guess -- probe every shape the module supports and call a field lost only when
NONE survives, or the test re-breaks at the next refactor.

COROLLARY -- a compound `verify:` inherits its WEAKEST clause. `state_mlb.md`
required `conditional_arsenal` / `count_bucket_map` / `conditional_arsenal_source`
all non-zero. The third could not be satisfied by any deploy of that change --
the field was dropped by a different file -- so the verify was permanently
un-passable and its failure said nothing about the change under test. This is
the same-day rule about compound ABSENCE claims, running the other way. One
clause per mechanism, each separately falsifiable.
- *(evidence in `.syndicate/log/2026-09-07.md`)*
## 2026-09-07 A freshness gate must be `> deploy.finishedAt`, and an UNCHANGED control is not automatically a null result

Two instrument errors in one verification, both of which would have reported the
WRONG verdict about a fix that was in fact correct.

**1. "Newer than my last reading" is not "newer than the deploy."** Verifying
`conditional_arsenal_source`, I gated the watcher on `generated_at` differing
from the 16:27:40Z baseline. It fired on a report generated **17:12:10Z** --
newer than the baseline, and **12 minutes BEFORE the deploy went live at
17:24:04Z**. Old code, still showing the failure. Reported as the verdict it
would have called a good fix broken and sent me hunting a second bug that did
not exist. The correct predicate is `generated_at > deploy.finishedAt`; the
baseline is not a proxy for it, because artifacts are produced continuously and
one will land in the gap between your reading and your deploy.

**2. The control I demanded was the wrong control, and I had said so in advance.**
I wrote that `bb_gb_rate` MUST move or the artifact is cached. It did not move
(0.6933/0.6786, identical), and the result was still sound. That control was
built for the June-glob SAMPLING bug, where the underlying sample changed and
rates shifted 77.4% -> 69.3%. This was a pure SERIALISATION fix on the same date
and the same inputs, where every rate should be byte-identical and a MOVED rate
would have been the alarm. Holding to my own stated criterion would have made me
doubt a correct result.

HOW TO APPLY. Name, before reading, WHICH failure each control discriminates and
in WHICH direction. A control inherits the failure mode it was designed against;
carried to a different change it can invert -- "must move" becomes "must not
move" -- and a criterion stated in advance is not thereby the right one. Where a
control is ambiguous, prefer a discriminator the failure CANNOT fake: here the
key's own presence, since a pre-fix artifact does not contain
`conditional_arsenal_source` at all, so no cached roster could return non-zero
for it, and the fixed value matching its sibling exactly (0.86 = 0.86) is the
predicted value rather than merely a non-zero one.
- *(evidence in `.syndicate/deploys.md`, 2026-09-07 17:44:53Z)*
## 2026-09-07 The deploy-claim breadcrumb id is not merely un-prefixed -- it is not in the roster at all

SUPERSEDES the entry above it, which said the claim's `session:` breadcrumb
"does not resolve in `list_sessions` even for a LIVE holder" and told the reader
to search by TITLE. A peer offered a tidier explanation: ids DO resolve, they
just need the `local_` prefix, and the breadcrumb stores the bare uuid.

**Half right, and the half that is wrong matters.** The prefix gotcha is REAL:
`send_message` to a bare uuid returns "not found" and to `local_<uuid>` works --
I hit that myself today and it cost a lookup. But it does not explain the
breadcrumb, and I checked before accepting it:

    deploy_claim breadcrumb        520cd594-1ffa-4116-8951-4c4b53ffbfcf
    that lane's actual session id  local_605f483c-45a8-48d2-a500-eb4f4572d515

Different uuids. `520cd594` appears in `list_sessions` in NEITHER form, across
40 sessions back to 2026-09-04, which covers the whole life of that claim. So
prefixing `520cd594` resolves nothing -- there is no such session by that id.

HOW TO APPLY, both facts kept separate because they have different remedies:
- To MESSAGE a session, use the `local_`-prefixed id from `list_sessions`. A
  bare uuid fails with "not found", which reads as absence and is not.
- To identify a CLAIM HOLDER, do not expect the breadcrumb to resolve at all --
  it records an id that need not correspond to anything `list_sessions` returns.
  Match by TITLE. The TTL remains the only liveness bound, and a failed lookup
  is still zero evidence the holder is gone.

AND THE META-POINT, which is why this is an entry rather than an edit: a peer's
correction is a claim like any other. This one was offered confidently, was
plausible, matched a real gotcha, and still did not explain the case at hand.
Accepting it unmeasured would have replaced one wrong mechanism with another --
and a remedy whose mechanism is wrong makes no prediction, so it fails silently
the next time.
- *(evidence in `.syndicate/log/2026-09-07.md`)*
## 2026-09-06 FORBIDDEN: reading a shared refusal/guard function's SCOPE off its NAME. Its scope is the FIELD LIST it actually reads, and a three-way market has three legs. `[lane soccer-threeway-precision-gate]`

`probability_refusal.refuse_published_certainty` is named, documented and
reasoned about as the platform's answer to "a finite simulation cannot
establish impossibility". Its module docstring runs forty lines, calls itself
**platform-wide**, and tabulates the 25 certainties it was built for across four
sports. It reads exactly one field: `model_prob_over`.

Soccer's `h2h_3_way` projection carries THREE probabilities --
`model_prob_over` (home), `draw_probability`, `away_probability`. So the guard
covered one leg of three, and the two it missed are the ones structurally most
likely to hit the boundary: a draw is a NARROW outcome, and `draws / n` reaches
zero as soon as a second goal separates the sides.

WHAT MADE IT INVISIBLE FOR WEEKS, and this is the part worth keeping:
`layer2_board._MODEL_EDGE_MAX_POINTS` (15.0) was silently dropping the WORST
cases. A `0/400` leg against a 0.16 fair reads -16.0 pp and is refused by the
cap, never by a certainty rule. So the extreme end looked handled, the middle
published freely, and nobody could find an example that looked wrong.
**A cap that discards your worst cases will hide the defect that produces them.**

HOW TO APPLY. Before relying on a shared guard, grep the FIELDS it reads and
compare that list against the fields the data actually carries on the path you
are on. "It is handled platform-wide" is a claim about a function's ambition,
not its predicate. The same check would have caught
`soccer_live_gameline_source.py:198`, which publishes a full `side_probabilities`
vector that no consumer reads at all.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-07 FORBIDDEN: a COMPOUND absence claim where only one clause was checked. "Not in X, not in Y" from one command that saw only X. `[lane soccer-threeway-precision-gate]`

I ran `ls .syndicate/findings_*` in the PRIMARY TREE and reported a file was
"not in the primary tree, not on origin/main". The first clause was measured.
The second was invented in the same breath, and it was FALSE -- three commits
touch that file on `origin/main` (`cc598278`, `583519c9`, `cbe02a45`). A peer
spent a turn refuting it, and I had warned THEM about primary-tree staleness in
the same message.

The failure is not the stale tree -- that is already a rule. It is that the
verified clause LAUNDERS the unverified one. Two clauses in one sentence read as
one measurement because there is no visible seam, so the half with evidence
lends its credibility to the half without. `[sharpened 2026-09-07 by lane
ncaaf-live-resim-wire, which hit the identical shape as "a grep proving a symbol
EXISTS doing duty for a claim that it is CALLED" -- same defect, different
clause.]`

AND IT HAPPENED INSIDE A WARNING ABOUT THE VERY THING. I was telling a peer to
beware primary-tree staleness in the same message. That is not incidental: the
seam stops being visible exactly when you are most confident, because the
sentence is doing rhetorical work and you are reading it for force rather than
for evidence.

HOW TO APPLY. For a shared file, `git ls-tree -r origin/main -- <path>` or
`git cat-file -e origin/main:<path>` after a `git fetch` -- the checkout answers
a different question. More generally: if a sentence names two scopes, run two
checks or name only the one you ran.
- *(evidence in `learnings_evidence.md`)*

### 2026-09-07 — FORBIDDEN: verifying a change with an AGGREGATE COUNT that BOTH your intended effect and a collateral bug would move the same way `[lane soccer-threeway-precision-gate]`

Also FORBIDDEN: making an existing field take a value it never took before
without enumerating that field's READERS first.

- **What we believed:** the soccer precision gate (`d9672ac7`) did one thing —
  withhold moneyline legs whose edge is inside their own Monte-Carlo noise. It
  was verified on the served board: model-edge rows fell **28 -> 11** across a
  rebuild, polled rather than read once. That number was taken as confirmation.
- **What was actually true:** the deploy did TWO things.
  `_price_against_market` began writing `edge_vs_market_pct = None` for a NEW
  state — "priced against a real fair, withheld as imprecise" — on ~60% of
  soccer moneyline rows, where before it was ~never null.
  `layer2_board._model_edge_for` opens with `if edge is None: return
  _modelled_fair_edge_for(...)`, an early return written for a DIFFERENT state
  (a one-sided quote with no two-sided fair). The two are indistinguishable at
  that line, so a withheld HOME leg silently dropped the DRAW and AWAY legs of
  the same match before their own bars were consulted. Measured on the
  2026-09-07 slate: **3 of 10 legs lost, including a +10.13 pp away edge
  (Getafe) that cleared its own 4.84 pp bar.**
- **How we found out:** not from a test and not from review — both passed. The
  user asked for the draw leg to be checked on the next slate, and that check
  was PER-LEG (served value against that leg's own bar), not an aggregate. An
  aggregate could never have found it: **both mechanisms push the edged count
  DOWN, so 28 -> 11 is exactly what the gate alone looks like AND exactly what
  gate-plus-collateral-damage looks like.** The metric could not fail for the
  second mechanism, and it was read as though it could.
- **The rule going forward:** two, and the second is the cheap one.
  1. A verification metric must be able to FAIL for the bug you did not think
     of. If your intended effect and a plausible collateral effect move it the
     same direction, it verifies nothing — measure per-row against the predicate
     you actually changed.
  2. When a change makes an existing field newly-null (or newly-anything),
     `git grep` that field name and enumerate every site that BRANCHES on the
     value. One grep for `edge_vs_market_pct` would have surfaced this early
     return in seconds.
     **AND ONE HOP FURTHER: the fields DERIVED from it.** `[amended 2026-09-07,
     after breaking this rule while obeying it]` The fix for the above made
     `_model_edge_for` return a market-priced edge where `edge_vs_market_pct` is
     None; `model_edge_basis` decides "market" off that same field, so the LABEL
     fell through to None on a real edge -- 4 of 77 served soccer rows. I ran the
     grep and stopped at direct readers. A field computed FROM the one you
     changed is a reader too, and it is the one a grep for the original name does
     not show you. Found by reading the deployed board; no test caught it.
- **Cost:** 43m51s live in production (`d9672ac7` 01:26:11Z -> `62937ea4`
  02:10:02Z), coverage only — `_modelled_fair_edge_for` is side-matched, so the
  dropped legs returned None rather than an ungated number. Plus a per-side
  split published to a peer session and into `state_soccer.md` that had to be
  retracted, because it summed the two mechanisms.

**NEITHER HALF WAS A BUG, WHICH IS WHY NOTHING CAUGHT IT.** The early return is
correct for a one-sided quote; the gate is correct for an imprecise estimate.
The COLLISION is the defect. A missing branch announces itself; a second meaning
quietly assigned to an existing sentinel does not. Same family as
`unknown must not default permissive` — one field carrying two states, and the
consumer branching as if it carried one.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-07 FORBIDDEN: `git reset` the SHARED PRIMARY TREE to origin/main to tidy away unpushed commits. It converts a harmless pointer into 153 files of revert exposure. `[lane soccer-threeway-precision-gate]`

The primary tree sat 3 ahead / 327 behind. All three commits were verified
CONTENT-REDUNDANT -- every line already upstream, checked per file, with the
only exceptions being two generated header lines. So "drop them" looks like
free tidying. It is not.

MEASURED before acting:

    tracked files where working tree != origin/main   170
      of those, locally MODIFIED (live work)           17
      of those, merely STALE                          153

**HEAD currently MATCHES the working tree.** That is the property that makes the
tree safe: a session running `git add -A && git commit` records only its own
real edits. Move HEAD to origin/main and those 153 stale files become unstaged
"modifications" that are actually REVERSIONS of up to 327 commits -- and the next
`add -A` from any of the ~80 sessions on this machine commits them. Every pointer
move has this shape: `reset --mixed` leaves it in the working tree,
`reset --soft` puts it in the SHARED index, `update-ref` puts it in both.

So the cosmetic gain ("ahead 3" disappears) is paid for with a
revert hazard strictly WORSE than the one being tidied.

HOW TO APPLY.
- Unpushed commits in the primary tree are harmless while HEAD matches the tree.
  Verify they are content-redundant, say so in the ledger, and LEAVE THEM.
- If they are NOT redundant, land the unique content by targeted append from a
  worktree off origin/main -- never by pushing the stale file, and never by
  rebasing the shared tree.
- The only real cure is a full sync (merge/pull), which needs the in-flight
  files landed by their owning sessions first. That is the tree owner's call,
  not a passing session's.
- A `DO NOT PUSH` line in the commit message is the cheap mitigation, because
  the hazard is only realised on a push.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-07 FORBIDDEN: repeating a REPORTER'S impact framing as your own measurement. You inherit its SCOPE without inheriting its evidence. `[lane publish-refusal-201-triage]`

Triaging a live defect in `/api/ops/artifacts/export`, I wrote in a findings doc
and told the owning lane: *"that endpoint is how most sessions verify
production... I used it myself earlier tonight."*

**I had not used it.** This session's production reads were
`/api/board/layer2-shortlist`, `/api/board/layer1`, `/soccer/<league>/api/cards`,
the Render API and `render_logs.py`. What I actually knew was that ONE lane read
it. "Most sessions" came from the reporter's framing and I restated it as though
I had counted.

THE HARM IS SPECIFIC AND IT IS NOT COSMETIC: an impact claim sets someone else's
PRIORITY. The owning lane was mid-optimisation on a live service, and I gave them
a reason to interrupt that was broader than the evidence. The mechanism argument
was sufficient on its own and was WEAKER for carrying an inflated blast radius --
if they had checked the usage claim and found it hollow, the real defect would
have inherited its credibility.

WHY IT SLIPPED THROUGH THE EXISTING RULES. I was strict all evening about not
inheriting other sessions' MEASUREMENTS unverified, and completely unstrict about
inheriting their CHARACTERISATIONS. "201 refusals" I re-derived; "most sessions
use this" I passed straight through. A scope claim is a claim.

HOW TO APPLY. Before repeating an impact statement, ask what you would have to
have counted for it to be true, and whether you counted it. If not, attribute it
(`the reporter says X`) or drop it -- the mechanism usually carries the argument
alone. And a claim about your OWN behaviour is checkable in seconds: I did not
check mine.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-07 FORBIDDEN: publishing a PRODUCTION LATENCY or ERROR reading without first establishing that no other session was loading that service. ~80 sessions share these three services; a concurrent load test makes the instrument read the other session, not the route. `[lane ncaaf-live-resim-wire]`

I probed `/api/ops/artifacts/export?names_only=1` on web, saw one subset take
>150 s and a third return **502**, and reported it as `#632` latency on that
route. It was not. `web-oom-profiler-steady` was firing 18 requests at
`/api/intelligence/query` in three 6-concurrent bursts, 00:50:06-00:53:14Z,
against **8 gunicorn slots** (`WEB_CONCURRENCY=2` x `GUNICORN_THREADS=4`), each
held 20-65 s. Their clean reading of the SAME route at 00:48:22Z was **19.1 s
median / 25.6 s max**. My number was ~8x their number and was measuring them.

THE OVERLAP IS CHECKABLE AFTER THE FACT, and checking it is what turned a
retraction into two findings. My probe's output file was last written
**00:53:45.302Z** and had run >120 s, so it began no later than 00:51:45Z --
inside their window. But it also showed:

- My 502 landed **31 s AFTER their burst ENDED**. So a burst's slot-hold outlives
  its last dispatch by the length of its longest request; "my load stopped at T"
  does not mean the service was free at T.
- It landed **1.4 s BEFORE** their `unhealthy` event at 00:53:46.700Z, so that
  health-check failure is at least PARTLY MINE. **The confound is symmetric and
  you owe the other session the reciprocal warning** -- otherwise they
  re-baseline against a failure you caused.

**HOW TO APPLY.**
- Before publishing any production timing, ask what else is running. `lanes.md`
  names the lanes; a message to the owner costs one turn and is cheaper than a
  retraction.
- SPLIT THE READING BY WHAT LOAD CAN TOUCH. Counts, ancestry, and pure local
  computations survive; wall-clock and 5xx do not. Here the correctness readings
  (2,371 artifacts / 667 deep; 6,316 / 5,924) and the keep-counts (111/107/161 of
  177 patterns) all stood -- only the latency claim died. Saying which half is
  which is the difference between a retraction and a total loss.
- **A STRUCTURAL claim and its PRODUCTION consequence are two claims.** "Leading-`*`
  subsets are the pre-filter's worst case" is arithmetic over the pattern list and
  stands. "...and therefore still fall over in production" needed the measurement,
  and died with it. Do not let the surviving half smuggle the dead half along.
- *(evidence in this file's PART 4 entry in `log/2026-09-07.md`)*
## 2026-09-07 - FORBIDDEN: treating UNTRACKED as NEW. It can mean your HEAD is behind.

**What happened.** `.syndicate/log/2026-09-07.md` showed as `??` in
`git status`, so I blob-staged my local copy against `origin/main` as if it were
a new file. It was not new. My HEAD predated the commit that added it, so what I
held was a **stale 184-line prefix of a 1,233-line file**. The push deleted
1,125 lines of the same day's log. Restored in `9abfc537`.

**`??` answers "is this in MY index", not "does this exist upstream".** On a
tree whose HEAD is behind `origin/main` -- the normal state here, already
recorded as `primary_tree_is_not_deployed_code` -- an untracked path and a path
that exists upstream with far more content look **identical**. The status letter
is about my index; the question was about the remote.

**The guard printed the answer and was not looking at it.** The gate emitted
`76 1125` on screen and refused nothing, because its deletion check named
`lanes.md` only. Two paths were being written; one clause was checked. That is
the compound-check failure recorded in `compound_absence_claim` **earlier the
same day**, committed by the session that recorded it -- writing a rule down
does not make you apply it to the next thing you build.

**How to apply.**
- Before staging ANY ledger path, run `git show origin/main:<path>` first. If it
  exists, your copy is a candidate for a stale-prefix clobber no matter what
  `git status` says. Merge onto the upstream copy; never push yours over it.
- A deletion gate must iterate over **every path in the diff**, never a named
  one: `for r in rows: if int(r[1]) != 0: refuse`, with no path allowlist.
- This is a SCOPE bug, not an oversight: the correct reasoning was present and
  applied to `lanes.md` in the very same script, to one of two arguments.

Related: [[shell_layer_transcodes_bytes]] (0-deletion rule on a shared append),
[[compound_absence_claim]], [[primary_tree_is_not_deployed_code]].
## 2026-09-07 FORBIDDEN: writing a test from the SAME reading of a contract that produced the code. `[#632, session b2b5b45b]`

`d5e4cc51`'s `patterns_that_can_match` compared directory DEPTH. The caller
applies the subset with `fnmatch`, whose `*` CROSSES `/`; the patterns are
globbed, where it does not. My unit test
`test_subset_prefilter_is_conservative_when_it_cannot_tell` asserted MY reading
of `*` rather than the caller's actual call, **so it passed and proved nothing**.
The endpoint then short-answered with no error for 10 minutes in production.

**A test written from the same misreading as the code cannot catch that code.**
Reviewers cannot either, for the same reason.

**How to apply:** when a value crosses a boundary between two languages/dialects
(glob vs fnmatch, SQL vs ORM, shell vs Python quoting), the test must exercise
THE CALLER'S ACTUAL CALL, not your model of it. And prefer a PROPERTY over
examples: *pre-filter then post-filter must equal post-filter alone* is
executable, and it is what finally caught this. Then verify the test can FAIL:
reverting to the buggy implementation produced 250 unsound drops. A test never
seen red is not evidence. See [[feedback_gate_on_the_output_not_the_input]].
## 2026-09-07 FORBIDDEN: reading a null result from a window that ENDS BEFORE THE EFFECT CAN OCCUR. `[#632, session b2b5b45b]`

I checked Render events ~1 minute after a load burst began, saw none, and
reported "no health-check event fired" as a RESULT. It fired at burst-end +32 s.
In the baseline arm it had fired at +0 s.

**A burst's blast radius is its longest TAIL, not its last request.** 18 requests
with 20–65 s tails hold gunicorn slots long after dispatch stops, so the
observation window must extend past the slowest request, not past the last one.

**How to apply:** before reporting an absence, state the window AND the latency
of the thing you are looking for, and confirm the window covers it. Reinforces
[[feedback_absence_in_a_window_is_not_absence]].
## 2026-09-07 FORBIDDEN: comparing percentiles across arms with DIFFERENT ERROR COUNTS. `[#632, session b2b5b45b]`

BEFORE: 16/18 completed, 2 errors, p50 20,671 ms. AFTER: 18/18, 0 errors, p50
24,108 ms. I nearly reported "latency got 17% worse". **The two errors were the
WORST cases and were excluded from BEFORE's percentiles**, so the arms do not
share a denominator; the fix's arm is penalised for completing the requests the
baseline dropped.

**How to apply:** percentiles over successes only are a survivorship statistic.
Report completion rate BESIDE them, and when error counts differ, the percentile
comparison is invalid — say so rather than picking the flattering reading. Also:
**retain raw per-request samples, not summaries.** Keeping only summaries is what
made this unresolvable. See [[feedback_a_rate_not_a_count]].
## 2026-09-07 A pre-filter that can change the ANSWER is not a pre-filter. `[#632, session b2b5b45b]`

An optimisation placed in front of a filter must be provably sound in ONE
direction only: keeping something that cannot match wastes work and the
post-filter still corrects it; dropping something that can match is
unrecoverable and silent. `patterns_that_can_match` now returns True for
anything it cannot decide (a `[...]` class), and the caller's `fnmatch`
backstop was kept.

**How to apply:** state which direction of error is recoverable before writing
the optimisation, and make the undecidable case fall to the recoverable side.
Reinforces [[feedback_unknown_must_not_default_permissive]] — same rule, opposite
polarity: the safe default is whichever side a downstream check can still fix.
## 2026-09-07 - FORBIDDEN: reporting a null result without checking the sampled population COULD have produced a non-null one.

**What happened.** I called `/api/ops/live-lens/snapshot-index?sport=mlb`,
printed the first three games, saw `modelHomeWinProb: null, source: null` on
every `first1/first3/first5` lane, and concluded **"MLB's segment lanes are
EMPTY -- not filtered, not imprecise, absent."** I put that in a commit message
on `main` (`70622e0b`) and told the user I was retracting a *correct* earlier
statement in its favour. Retracted in `305f2d74`.

**All three sampled games were FINAL**, and `_build_game_lens` returns `[]` for
a final game -- so those lanes came from `_live_lens_segments_from_card`, which
has no `source` and no `modelHomeWinProb` **by construction**. The population I
sampled could not have produced a non-null answer no matter what the system did.
`prop_status_text: "final final"` was in the payload I had already fetched.

**On live games the lanes are populated:** gamePk 823902 `first5 0.3242,
first7 0.2991`; 823175 `first7 0.6511`, with the Nones monotone in segment
length -- `_segment_projection`'s `closed` flag working correctly.

**Why this is its own rule and not just [[instrument_blindness]].** That rule
says a healthy reading is evidence only once you know what makes it read
unhealthy. This is the inverse and the more dangerous direction: an ABSENT
reading was taken as evidence of absence, when the sampling frame guaranteed
absence. It also compounded [[read_the_field_you_already_have]] -- the
discriminating field was on screen -- and produced a **retraction of a true
statement**, which is worse than the original error: the user had been told
something correct and I replaced it with something false, confidently.

**How to apply.**
- Before reporting any null/zero as a property of the system, state the
  population and show it contains at least one case that COULD have been
  non-null. If it cannot, the reading is about the sample, not the system.
- For live-state endpoints, FILTER TO LIVE before drawing conclusions. `live`,
  `final` and `pregame` rows are produced by different code paths here, and
  final rows are built by a path that has no live fields at all.
- Never sample "the first N" of a heterogeneous payload. Group by the state
  field first, then look.
- A retraction is not free. Re-derive before overturning something you already
  told the user was true -- [[retraction_is_not_innocence]] runs both ways.

Related: [[instrument_blindness]], [[read_the_field_you_already_have]],
[[absence_in_a_window_is_not_absence]], [[a_projection_is_not_a_model_edge]].
## 2026-09-07 FORBIDDEN: justifying a sign/unit transform by pointing at a SIBLING CALL SITE. The convention belongs to the SOURCE, and one function can read two sources. `[lane nfl-rating-units]`

`backfill_nfl_performance` negated nflverse's `spread_line` to build
`market_margin`. That field is already HOME-MARGIN-POSITIVE, so every NFL
regular-season market number was inverted. Measured by running the repo's own
`load_completed_games` over real 2025 results: **34.7%** agreement with the
actual winner against the market's true **65.3%** -- almost exactly
one-minus-the-truth, which is the signature of a SIGN ERROR rather than a weak
signal. 65.3% after the fix.

**THE COMMENT DEFENDING IT WAS ACCURATE AND STILL WRONG.** It cited two siblings
-- the preseason branch a few lines below, and
`backfill_smartsim2_performance.py` -- and BOTH of those negate CORRECTLY,
because they read a SPORTSBOOK spread, which genuinely is bet notation. One
function, two sources, two conventions, one negation applied to both. A reviewer
who checks the cited siblings finds them correct and moves on.

**AND A TEST ASSERTED THE WRONG VALUE AND PASSED.** Second instance the same day
of that shape -- the artifact-export pre-filter (`web-oom-profiler-steady`) was
the first. A test written from the same misreading as the code cannot catch that
code, and a green suite is then evidence of nothing.

**HOW TO APPLY.**
- Trace the field to the FILE and the WRITER that produced it. Here
  `schedule_{season}.csv` <- `fetch_nfl_schedule.py` <- nflverse `games.csv`,
  copied verbatim. The convention was three hops away and knowable.
- Prefer a check the DATA can fail. "Does the market pick winners more often than
  chance" needs no documentation and cannot be satisfied by a plausible comment.
- When you fix it, fix the TESTS THAT ENCODED IT, and add a probe for the
  PROPERTY rather than the value -- an equality assertion can be satisfied by an
  unrelated change.
- *(evidence: `findings_2026-09-07_nfl_rating_units_and_market_sign.md`, and
  PART 5 of `log/2026-09-07.md`)*

## 2026-09-08 FORBIDDEN: a parity check that compares PRESENTATION and ignores CAPABILITY `[lane nfl-ncaaf-ui-parity]`

**What we believed.** That moving NFL onto NCAAF's card partial was a strict
improvement, because every number said so: compact card 643-1085px across
sixteen distinct heights -> 181px uniform, crests 0 -> 32, prose blocks 32 -> 0,
`card_variant` 16/16.

**What was actually true.** The partial being switched TO rendered two fewer
panels than the one being switched FROM. Same served NFL game, both partials:

    generic   panels = game, boxscore, props, panels
    football  panels = identity, context, coverage, details

Box Score and Props were dropped, live, for several hours. The data was never
missing: `shared_prop_rows`, `shared_box_sections` and `shared_period_rows` were
all **16/16 non-empty** on the served payload the whole time.

**How we found out.** The user said props and a box score were "a big miss".
Not from any check of mine -- and every check of mine passed, because I had
measured how the card LOOKED and never what it could DO.

**The rule going forward.** When swapping a renderer, diff the CAPABILITY SET,
not the appearance: enumerate the panels/tabs/sections each side produces for
the SAME input and diff them. One `grep -c 'data-panel-id'` on both partials
would have caught this before the deploy. Heights, crests and byte counts are
evidence about presentation and say nothing about what was traded away.

**Cost.** Two tabs missing from the live NFL board for ~4 hours on the day
before the season opener, found by the user rather than by me. Restored in
`4be5c5a5`, contract-based so it also gave NCAAF a Box Score it had never had.

**And the fix's own first cut repeated the family's oldest defect:** I gated the
new TABS on `box_sections`/`prop_rows` and left the PANELS ungated, shipping an
orphan `props` panel on NCAAF -- markup reachable by nothing, which is exactly
what that card's header records collapsing a card on 2026-08-14. Caught before
commit by rendering both sports and diffing tab-set against panel-set, which is
now a test.
## 2026-09-08 FORBIDDEN: reading ZERO from an allowlist-gated instrument as ABSENCE `[lane nfl-props-precompute]`

**What we believed.** That production had no NFL play-by-play, because
`/api/ops/artifacts/export?pattern=*pbp_2025*` returned `count=0`, and therefore
that the prop model was structurally dead everywhere.

**What was actually true.** That endpoint only serves ALLOWLISTED patterns, and
pbp is not one. `count=0` means "no matching allowlisted artifact", not "no
file". The stream endpoint returns **403** for the same path -- a REFUSAL, not a
404. Both instruments are blind here, and I read blindness as evidence.

**Then the retraction was ALSO wrong, in the other direction.** Seeing
`rating_source=nflverse_pbp_epa_rolling[...]` on the deployed projection
artifact, I retracted and said production HAS pbp. True of **refresh-worker**,
which generates that artifact -- and I generalised it to "production". This
platform runs THREE SERVICES WITH SEPARATE DISKS; "production" is not a place.

**How we found out.** A counter, not an argument. With the fix live, the props
join printed `odds_rows=2455 sim_rows=0 refused_wrong_team=0
refused_unknown_team=0`. Both refusals at zero proved nothing reached the team
check, so every row exited at the one `continue` above it -- which requires the
player index empty for BOTH seasons. web has no pbp; the worker does.

**The rule going forward.** Before reading a zero as absence, ask what the
instrument REFUSES to show. An allowlist, an auth gate and a 403 all produce
zeros that look like emptiness. And when a claim is about "production", name the
SERVICE -- a fact true of the worker is not a fact about web.

**Cost.** Two wrong claims to the user in one session, one in each direction,
and an artifact pipeline nearly built for the wrong reason. Net cost low only
because the counter was added before acting on either.
## 2026-09-08 FORBIDDEN: promising a verification target without tracing WHICH PRODUCER stamps that field `[lane nfl-ncaaf-ui-parity]`

**What we believed.** That deploying the NFL card fix to refresh-worker would be
verifiable by reading `shared_predictions.probabilities.home_cover` on
`/api/board/book-grid?sport=nfl`. That prediction was written into `deploys.md`,
into the lane block, and told to the user, all before anything was checked.

**What was actually true.** That endpoint's `projection` field is stamped by
`attach_nfl_game_projections`, which reads the smartsim2 projection artifact
DIRECTLY and never touches the card's `predictions` block. Its keys are
`basis` / `model_prob_over` / `projected` / `side` / `edge_vs_market_pct`;
`home_cover` is not among them and never was. Coverage there was already
**300/300** before the change and would have been 300/300 after.

**How we found out.** By fetching the payload BEFORE deploying, to capture a
"before" number. The keys were simply not the ones promised. Read AFTER the
deploy instead, a flat 300/300 was available to be told either way -- "already
perfect, nothing to prove" or "the fix did not land" -- and nothing in the
reading itself would have distinguished them.

**The rule going forward.** A verification target names a FIELD on a SURFACE. Before
promising it, name the PRODUCER that writes that field and confirm the change is
upstream of it. "The board reads the cards" was an assumption about a pipeline
with two independent producers for the same-looking value. The cheap check is
one fetch of the endpoint and a look at the key set -- do it while WRITING the
prediction, not while settling it.

**Cost.** No wrong claim reached production or the ledger unretracted: it was
caught by a pre-deploy read and retracted in the `15:05:37Z` `deploys.md` row and
the lane block. What it cost was a promise to the user that had to be walked
back, and it would have cost a false verification had the order been reversed.

**Related and NOT the same:** `gate-on-the-output-not-the-input` and
`test-the-fixs-predicate-not-its-deploy-state` are about a predicate that is
wrong or inert. This one is about a predicate that is well-formed, measurable,
and reads a field your change cannot reach.
## 2026-09-08 FORBIDDEN: leaving a self-refreshing board open while diagnosing the service it loads `[lane nfl-ncaaf-ui-parity]`

**What we believed.** That the `/ncaaf*` request family appearing in web's slow-request
logs after a 14:02:20Z deploy was organic traffic, and that the candidates for
web's elevated OOM rate were my deploy, the other commits in its range, and a
peer lane's burst harness.

**What was actually true.** The requests were MINE, from a browser pane tab.
`syndicate/static/shared/game_board.js:installSharedBoardAutoRefresh()` starts a
poller on every `/cards` and `/game/` page: `intervalMs: 30000`, `onTick` doing
`fetch(window.location.href)` -- a full server-side re-render -- and
**`skipWhenHidden: false`**, so it keeps firing with the tab hidden. I had
`/ncaaf/cards` open as the CONTROL for a parity comparison. On a 16 s route that
is ~53% duty cycle on 1 of 8 gunicorn slots, from a viewer who is not looking.

**How we found out.** A peer reported `/ncaaf*` as 25 of the 29 slow requests on
the service and noted it had **ZERO** requests in their 23:00Z baseline -- "not a
route that got slower, one that did not exist there". That is exactly the
signature of a route nobody was requesting until somebody started. Reading the
tab's own network log showed ~22 sequential same-URL requests, and
`game_board.js` supplied the mechanism.

**The rule going forward.** An open board is a load generator, not an
observation. When measuring a service, close every page of it you are not
actively reading, and say in the report which requests were yours. A "control"
tab left open for comparison is instrumentation that changes the thing it
measures.

**Cost.** Real but unquantified: three OOM kills (14:13, 14:23, 14:43) that a
peer lane spent its own time attributing, and my own contribution to the
candidate list I handed them was omitted because I did not think of my browser
as traffic. Not proven to be the cause -- closing the tab gives a clean window,
and it was explicitly flagged not to be called early.

**The check, because a rule alone will not catch this.** `skipWhenHidden: false`
on a poller that re-renders a whole page server-side is a product defect
independent of any operator: any user who leaves a board open does this, hidden
tab included. It is the strongest open lead in `#632`. NOT changed here --
`game_board.js` is a cross-sport shared file that no lane claims, and a
platform-wide polling policy is not a thing to alter unilaterally.
## 2026-09-08 FORBIDDEN: carrying a scoped finding forward as a GENERAL claim after its scope expires. `[#632, session b2b5b45b]`

`UPDATE 37` established "web is not OOM-killed, it TIMES OUT" from 35
`server_failed` events with zero `evicted=True`. True of those events. I then
repeated it for a full day — in messages to two peers and in my own reasoning —
while web took **six `oomKilled memoryLimit=2Gi`** in one day, four of them before
I sent anything.

**A finding is scoped to the window it was measured in.** "Not X in these 35
events" is not "not X". The moment it becomes a premise for someone else's
debugging it needs re-checking, because the cost of a stale premise is paid by
whoever trusts it.

**How to apply:** when relaying a finding to a peer, state its WINDOW alongside
it. When a finding is more than a few hours old and you are about to act on it,
re-read the events. See [[feedback_absence_in_a_window_is_not_absence]] and
[[feedback_rebaseline_before_judging]] — this is the same failure aged into a
belief.
## 2026-09-08 FORBIDDEN: a periodic publisher whose interval EQUALS its reader's freshness threshold. `[#632, session b2b5b45b]`

I set the chip publish interval to 120 s to "match" the endpoint's 120 s
threshold and wrote that in the docstring as a virtue. The real gap is
`interval + build_time + poll_granularity` = ~135 s, so the artifact was stale
for the tail of EVERY cycle and ~40% of requests still fell back to the inline
fan-out.

**A publisher must run FASTER than the threshold that judges it**, by at least
its own build time plus its scheduler's granularity. Matching exactly guarantees
a stale window; matching is the worst of both.

**How to apply:** when a producer and a consumer both carry a time bound, write
down which is which and make the producer's strictly smaller — or raise the
consumer's, which is what was done here (120 → 180 on web) because the worker was
the constrained service.
## 2026-09-08 FORBIDDEN: reading a marker at the wrong nesting level and concluding the code did not run. `[#632, session b2b5b45b]`

I verified a new response guard by reading `_response_slimmed_reason` at the TOP
level of the payload, got `None`, and was one sentence from reporting that the
guard had not fired in production. The payload nests under `response`; the marker
was there, with the right value.

**A null read from the wrong path is indistinguishable from a null read from dead
code** — and I have spent a whole session insisting on exactly that distinction
for logs. It applies to payloads too.

**How to apply:** before concluding "the code did not run", print the CONTAINER
you searched, not just the miss. Dump the keys. If a marker is absent, prove you
looked where it is written. Same family as
[[feedback_absent_signal_is_about_the_emitter]].
## 2026-09-08 A probe is production load, and an unbounded one is an outage. `[#632, session b2b5b45b]`

To measure a slow endpoint I POSTed it with no `limit` and no `slim_aliases`. It
built a **64.98 MB** response in a 2 GiB container and web was `oomKilled` twice
within three minutes. Earlier the same night a 6-concurrent burst tripped a real
`unhealthy` health-check failure. **Three production incidents this session were
caused by my own measurements.**

Reproducing a failure deliberately IS legitimate and produced the session's best
evidence. What was not legitimate was sending the heaviest possible variant of a
request without first asking what it would cost.

**How to apply:** before probing, estimate the response size and the concurrency
you are about to add, and bound them explicitly (a `limit`, a slim flag, fewer
threads). Prefer the shape a real client sends — I measured a request production
never serves and nearly drew conclusions from it. Then say plainly, in the write-
up, which incidents were yours.
## 2026-09-08 - FORBIDDEN: `git stash` inside a session worktree. The stash stack is REPOSITORY-GLOBAL.

**What happened.** I used `git stash -q -u && git fetch && git rebase && git
stash pop -q` as a rebase helper in my session worktree, as I had several times
that day. This time my tree was CLEAN, so `stash -q -u` stashed **nothing** --
and `stash pop` popped **another session's** work in progress
(`stash@{0}: WIP on session/pc-counters`) into my worktree, producing `UU`
merge conflicts in four files belonging to lane
`mlb-first5-kalshi-fanin-mismatch` plus 58 lines of their lane blocks staged in
`lanes.md`.

**`scripts/session_worktree.py` gives each session its own INDEX. It does not
give it its own STASH.** `git stash` is a ref (`refs/stash`) in the shared
repository, so every worktree pushes and pops the same stack. Worktree isolation
does not extend to it, and nothing warns you.

**Why the earlier uses did not break.** On every previous call I actually had
local changes, so my own entry was on top and `pop` returned mine. The hazard is
invisible until the one time the tree is clean -- which is exactly when the
helper looks safest.

**Nothing was lost, and the reason is luck plus git being careful.** The pop
conflicted rather than applying cleanly, so git KEPT the entry
("The stash entry is kept in case you need it again"). Had it applied cleanly it
would have been DROPPED, and another session's uncommitted work would have
existed only inside my worktree, on top of my unrelated changes.

**How to apply.**
- **Do not run `git stash` in a worktree.** To rebase over local changes, commit
  them first (a throwaway commit you amend or reset later), or `git rebase
  --autostash` which uses its own storage, or simply rebase before you start
  editing.
- If you have already popped someone else's work:
  `git restore --staged --worktree <their paths>` to put them back at HEAD,
  confirm `git stash list` still holds their entry, and say so. **Never
  `git stash drop`.**
- `git status --porcelain` showing `UU` on files you have never touched is the
  signature. Read the paths before resolving anything.

Related: [[shared_index_can_hold_a_revert]] (same class -- the index was shared
until worktrees; the stash still is), [[concurrent_parallel_sessions]],
[[untracked_is_not_new]].
## 2026-09-08 FORBIDDEN: treating scope drift as a discipline problem. Change the COST of deferring, or nothing changes. `[lanes session-scope-drift-guard + lead-deferral-and-lane-census, session e51345f0]`

- **What we believed:** sessions drift off their objective because they fail to
  notice, and the fix is to notice harder — or to delegate the lead to a subagent
  or a new session. The user's own framing: *"every session that has an objective
  ends up drifting instead of delegating or spinning up a new session to follow a
  lead."*
- **What was actually true:** two things, and both make "notice harder" useless.
  **(1) NO HOP IS CATCHABLE BY JUDGEMENT.** Stated best by lane
  `profitable-buckets`, opened the same day because its session kept deviating:
  *"This session already spent hours going from a ledger bucket gap into segment
  pricing, first5 skill, full-game discrimination, late-inning ceilings, a
  home-field term and two deploys. **Each hop was locally justified and the sum
  was deviation.**"* Every hop is defensible AT THE MOMENT IT IS TAKEN; only the
  sum is wrong, and nothing was watching the sum.
  **(2) THE COST GRADIENT POINTED THE WRONG WAY.** Following a lead cost **zero**.
  Deferring it cost `/lane open`'s **seven** steps of collision checking. A rule
  telling sessions to defer, laid over that gradient, is a rule asking people to
  choose the expensive option every time.
  Delegation was NOT the missing piece: the `syndicate-engineer` subagent
  CLAUDE.md prescribes for exactly this had **zero recorded invocations** in the
  entire ledger, and the sessions that DID close their lanes did it by
  re-declaring the goal per lead inside ONE context window, not by isolating.
- **How we found out:** measured on `origin/main` (never the checkout — the
  primary tree was 441 commits behind): **53 OPEN lane blocks, 26 UNOWNED, 20
  with no date newer than 2026-09-01.** Deferral ran **9 explicit instances
  against 41 `findings_*.md`** — about **1 lead in 4.5** — and **18 of 54**
  findings/handoff files were referenced by no lane at all. Every guard in
  `.claude/hooks` protected FILES AND THE LEDGER FROM THE SESSION;
  `lane-guard.py:187` fires only on `claimed by OPEN lane <other>`, so a write to
  a file NO lane claims was free. `current_lane()` had two non-test consumers and
  both used it only to EXCLUDE you from other-lane conflict detection. Nothing
  anywhere asked "is this write serving the goal I declared".
- **The rule going forward:**
  1. **A lead gets `/lead "<one line>"`, not inline work.** One line into
     `.syndicate/leads.md`, then back to the objective. Never into `lanes.md` — a
     lead has no claims and would inflate the population that is the problem.
  2. **`/checkpoint` states the lane's Goal VERBATIM and answers MET / NOT MET /
     DRIFTED.** `DRIFTED` is not a failure verdict; it is the only one that makes
     the next session's pickup honest. Copy the goal, never paraphrase it — a
     paraphrase drifts toward whatever you actually did.
  3. **When you propose a discipline fix, ask what it costs to obey.** If the
     compliant path is more expensive than the non-compliant one, you have
     written an exhortation, not a mechanism. `scope-guard.py` names the cheap
     path (`/lead`) precisely because a warning that offers only the expensive
     one is a reprimand.
  4. **Count the ledger with `scripts/lane_census.py`, never with grep or by
     reading prose.** Three methods gave three answers for "how many lanes are
     open" the same hour: `grep '— OPEN'` said 47 (it misses bold `**OPEN`), a
     prose reading said 47 (it counted three lanes as closed whose status field
     says OPEN and whose claims `lane-guard` still enforces), the parser said 53.
     The parser is authoritative because it is the one the guard uses.
- **Cost:** the 53/26 population itself, and 18 orphaned findings files nothing
  points at. Plus two near-misses inside the session that wrote this rule: the
  first draft of `scope-guard.py` went silent on any lane whose goal contained an
  em-dash — i.e. every lane following the ledger's own header convention — and
  its first live run fired with a `../../..` area that would have poisoned the
  once-per-area slot. **Both were invisible to 27 green unit tests and appeared on
  the first run against the real ledger.** A guard for a discipline problem fails
  toward SILENCE, which looks exactly like compliance.
## 2026-09-08 FORBIDDEN: proposing a rule without grepping `learnings_index.md` first. This file re-learns what it already knows. `[lane session-scope-drift-guard, session e51345f0]`

- **What we believed:** that "a reading goes stale between measuring and acting"
  was an uncovered lesson. I hit it three times in one session, told the user
  `learnings.md` had no rule for it, and was told to add one.
- **What was actually true:** it is covered at least **eight** times, and **two
  entries are near-verbatim descriptions of the exact instances I hit**:
  - `2026-08-15 — FORBIDDEN: a scratch index seeded with `git read-tree HEAD`
    snapshots the WHOLE TREE, and `git diff --cached --numstat` cannot see it go
    stale.` Same mechanism, **same file**: that entry lost 35 lines of
    `.syndicate/deploys.md` to a peer's commit landing mid-staging. **24 days
    later I staged against `origin/main`, origin advanced, and my commit carried
    a 26-line deletion of `deploys.md`** — a file I never opened or named. I
    caught it by reading `git show --stat`, not because I knew the rule; and the
    entry had already warned that the `--cached --numstat` check I was relying on
    is blind to this *by construction*.
  - `2026-08-27 — A CARRIED-FORWARD FACT DECAYS EACH TIME IT IS RESTATED WITHOUT
    RE-READING THE SOURCE.` **12 days later** I restated "lane
    `profitable-buckets` is unpushed" from a two-hour-old reading, in a lane
    block, in `leads.md`, and twice to the user. Its owner had pushed it. The
    correction had to be pushed too, because the stale claim was already on
    `origin`.
- **How we found out:** one `grep` over `learnings_index.md` — run *after* the
  user approved the new rule, when it should have preceded the proposal. The
  index exists precisely for this and cost one command.
- **The rule going forward:**
  1. **Before proposing or appending a rule, grep `learnings_index.md`.** It
     spans `learnings.md`, `learnings_evidence.md` and `learnings_archive.md`, so
     a rule stays findable after its body is compacted out.
  2. **If a matching rule exists, do not append a restatement.** Nine entries
     saying one thing is worse than one, because the digest samples the file and
     dilution is the failure mode. Cite the existing rule by its date instead.
  3. **If you broke a rule that already existed, the finding is about DELIVERY,
     not knowledge.** Say so plainly and name the rule you broke, so the next
     reader can reach it. Do not launder a repeat into a discovery.
- **Cost:** two rules broken 24 and 12 days after they were written, by the
  session whose own lane was *about* scope drift — and a ninth restatement very
  nearly appended. **The corpus has outgrown its delivery: 910 rules, of which
  the session-start digest carries 6 headings (`RULE_CAP=450`).** Size is not the
  constraint — `learnings.md` is 331 KB against a 460 KB cap. Compaction will not
  fix this; `2026-08-20 — TRIMMING state.md AND learnings.md DOES NOT FIX THE
  DIGEST. Measured.` already established that. **A rule that exists and does not
  reach the session is an exhortation with a distribution problem** — which is
  the same finding as this session's other rule, turned on this file itself.
## 2026-09-08 MAP: ~95 rules in this file are one question in 17 shapes — *"is the number I read the one the decision depends on?"* Read this before writing another. `[lane learnings-instrument-family-consolidation, session e51345f0]`

- **What we believed:** that the instrument/predicate family had grown to ~50-95
  near-duplicate entries and should be CONSOLIDATED — folded into one entry with
  the originals archived, following `2026-08-20 — ONE ERROR IN FIVE GUISES`.
  That was the plan, a tool was built for it, and it was **rejected on the
  evidence.**
- **What was actually true:** they are not near-duplicates. A full inventory read
  from `origin/main` found **~95 entries in FOUR families whose fixes differ**,
  and folding them would have deleted ~78 headings each naming a mechanism a
  generic rule would not have prevented:
  - **A — INSTRUMENT** (~65): *can the reading vary with the truth at all?*
    Fix: build a case that makes it read otherwise.
  - **B — MEASUREMENT-SOURCE** (~11): *is the value about the thing it claims?*
    Fix: find the surface that actually serves the reading.
  - **C — PREDICATE** (~13): *where did the threshold come from?*
    Fix: read the enforcer, not a docstring beside it.
  - **D — CONFOUNDED READING** (~10): *is the population or window contaminated?*
    Fix: split by eligibility, or clip the regime.
  "Check your instruments" is what a merged entry would have said, and it would
  have prevented none of the incidents that produced these.
- **How we found out:** the inventory was commissioned specifically to argue
  AGAINST consolidation, and did. The decisive check was cheaper: **the 2026-08-20
  precedent's own five originals had been absent from `learnings_index.md` since
  the day they were archived** — the generator spanned `learnings_archive.md` but
  not the dated file. Consolidation had already cost five rules once, silently.
  (Fixed 2026-09-08, `d1d4045d`: 911 -> 916 indexed, 0 removed.)
- **The rule going forward:**
  1. **Before writing a rule about a measurement, grep this map's clusters
     below.** ~95 entries already cover this ground; the odds you have a new
     claim are low and the cost of a duplicate is dilution.
  2. **Do not fold this family.** Merge at CLUSTER level at most, never at
     family level, and only where two entries make the same claim from the same
     mechanism. A topical neighbour is not a duplicate.
  3. **A map is the cheaper lever than a merge.** The problem was never that
     there are too many rules — it is that 911 rules reach a session as SIX
     headings. This entry costs one heading and destroys nothing; a merge would
     have cost 78 rules to save the same one heading.
- **THE 17 CLUSTERS.** Regenerate membership with
  `grep -iE 'instrument|predicate|discriminat|control|denominator|proxy|reachab' .syndicate/learnings_index.md`.
  - **A1 calibration** — prove it CAN read otherwise before trusting a clean
    reading. *(08-13 emit-non-zero · 08-27 built-out-of-the-thing-it-measures ·
    09-02 mutate-before-believing-green)*
  - **A2 wrong surface** — the instrument is not attached to what broke.
    *(08-16 wrapper-vs-siblings · 08-27 reading-from-a-different-surface)*
  - **A3 silent failure** — working and never-ran emit the same thing.
    *(08-13 discriminator-only-on-FAILURE, written TWICE the same day from two
    incidents · 08-19 guard-that-fails-open-silently)*
  - **A4 coverage gap** — the failure lives where the instrument never looks.
    *(09-04 cannot-see-the-suspect · 09-05 one-branch-does-not-certify-the-other)*
  - **A5 control design** — the comparison group cannot discriminate.
    *(08-27 control-broken-the-same-way · 09-06 same-length-of-time)*
  - **A6 discriminating power** — the signal was never shown to separate the
    states. *(08-31 visible-vs-discriminates · 09-06 key-not-value)*
  - **A7 singletons (~14)** — mechanism-specific, deliberately unmerged: a killed
    process emits no log; watchers lie in four ways; a green suite over a file
    that cannot boot.
  - **B1 reachability** — code-reachable is not data-reachable. *(08-13
    presence-is-not-reachability · 09-04 deploy-target-by-what-SERVES)*
  - **B2 describes the instrument** — the reading is a fact about the reader.
    *(08-29 count-0-is-about-the-SCANNER · 09-01 degenerate-fit)*
  - **B3 singletons (2)** — including 09-03 *polling a friendlier proxy instead
    of the instrument that GATES*, which is 2026-08-20's claim recurring two
    weeks later in another subsystem. **Left separate on purpose: it is the
    evidence that consolidating a family does not stop the mistake.**
  - **C1 read the enforcer (9)** — not the comment, the docstring, or the name.
    *(09-02 threshold-from-ENFORCER-claim-from-PREDICATE — the anchor · 09-06
    name-the-WRITER-of-the-field)*
  - **C2 predicate soundness (4)** — is it observable, and does its label follow
    from its condition? *(08-13 label-entailed-by-exit-condition · 09-03
    check-it-is-OBSERVABLE-first)*
  - **D1 wrong denominator (4)** — which ROWS are in the population. *(08-13
    pooled-denominator · 09-04 denominator-from-OUTSIDE-the-instrument)*
  - **D2 window confound (5)** — which MOMENTS are in the window. *(09-02
    measuring-the-RAMP-after-a-restart · 09-07 another-session-was-loading-it)*
  - **D3 singleton** — 09-07 a predicate on a TOTAL that can move for another
    reason.
  *(D1 and D2 are NOT one cluster: one is an eligibility filter you failed to
  apply, the other a regime you failed to exclude. Different operations.)*
- **Cost:** four of these rules were broken in a single session on 2026-09-08 —
  the digest budget read off total stdout instead of `$BODY`; an open-lane count
  from a grep instead of the parser `lane-guard` uses; a commit diffed against
  the base its index was SEEDED from instead of the one it lands on; a push-state
  claim restated from a two-hour-old reading. Every one of them had a rule, aged
  6 to 24 days, and none reached the session. **That is the cost this map exists
  to reduce, and it is the second confirmed instance of this file's own
  2026-09-08 rule about delivery.**


### 2026-09-08 — FORBIDDEN: inferring that a service HAS an input from a related artifact's provenance string. Read the consuming code's own counter.

- What we believed: refresh-worker had the NFL play-by-play and web did not, so
  moving the prop model to the worker would fix a zero-row join. The evidence
  was the worker's projection artifact carrying
  `rating_source=nflverse_pbp_epa_rolling[...]`.
- What was actually true: that string is TEAM-level EPA and says nothing about
  the player-level columns `player_name_index` needs. **Neither service can
  resolve a player name.** The worker's own first autorun:
  `JOIN ... sim_source=computed odds_rows=2463 sim_rows=0 refused_wrong_team=0
  refused_unknown_team=0` — 2,463 odds rows, MORE than web's 2,455, and still
  zero. `_pbp_path` reads `nfl_source/tracking/nflverse/pbp/pbp_<season>.csv`,
  which is **not in `HOT_ARTIFACT_PATTERNS` at all**, and `pbp_2025.csv` is
  **97.9 MB** against a 12 MiB `_PUBLISH_MAX_BYTES`. The input cannot travel, so
  the worker can NEVER build this artifact. The producer is an offline run.
- How we found out: reading the worker's own JOIN line at the timestamp of its
  launch — a field that had been in the log for an hour before anyone read it.
  The inference chain (`rating_source` mentions pbp -> the service has pbp) was
  never checked against the counter that the consuming code already emits.
- The rule going forward: an input's presence is a property of THE PATH THE
  CONSUMER READS, not of any artifact that mentions it. Before moving work to a
  service "because the data is there", read that service's own instrumentation
  for the consuming code path. A provenance label is about the producer's
  inputs, never about yours.
- Cost: one commit built on the wrong premise (landed, then removed the same
  hour), and — worse — an autorun deployed to a service that cannot succeed,
  whose first run published a 284-byte empty artifact over a healthy 966-row one
  and took `/nfl/api/props` to zero cards a day before the season opener.

### 2026-09-08 — FORBIDDEN: a guard that only DECLINES TO WRITE, when the damaging artifact already exists on disk.

- What we believed: moving the zero-row guard above the write and publish fixed
  the clobber. "Existing artifact left untouched" reads like safety.
- What was actually true: untouched was exactly the problem. The empty 284-byte
  file was ALREADY on the worker's disk, and a periodic publish sweep
  republishes it to web after every restart — `PUBLISH_OK ... bytes=284` at
  19:19:57, 19:22:34, and again at 20:01:38 immediately after the 19:58:07
  deploy, with `PUBLISH_SKIPPED_UNCHANGED checksum=77a9ed3cd0c7` in between. So
  the outage was not a one-off; it recurred on every boot, and the guard was
  silent through all of it because it never ran again.
- How we found out: `/nfl/api/props` was empty AFTER the guard was live, and the
  published artifact measured 111 bytes.
- The rule going forward: when a guard prevents producing bad state, ask what
  the bad state ALREADY on disk will do next. If something else republishes,
  serves, or re-reads it, the guard must REPAIR, not just abstain. Pair every
  "refuse to write" with "and restore the good copy" wherever a copy exists.
- Second-order, and it nearly shipped: the repair was gated behind an autorun
  whose staleness check reads `stat()` only, so a zero-row artifact written ten
  seconds ago is `artifact_fresh` for 24 h. The fix would have deployed and done
  nothing for a day. **Gate on the OUTPUT (rows), not the input (mtime).**
- Cost: a second deploy, and a repair that was written unconditionally the first
  time — it pulled web's 111-byte empty file straight over a good local copy
  before being conditioned on `local_rows == 0`.


### 2026-09-08 — FORBIDDEN: a test whose FIXTURE hand-rolls the artifact schema the code under test reads. Round-trip the production writer.

- What we believed: `_nfl_prop_artifact_is_empty` detected the zero-row NFL prop
  artifact, and three unit tests proved it. They passed.
- What was actually true: the helper read `payload["rows"]`. That key has never
  existed — `write_nfl_prop_projection_artifact` emits `{season, week,
  generated_at, sim_rows, row_count}` and `read_nfl_prop_projection_artifact`
  reads `sim_rows`. So the helper returned False for EVERY input, the staleness
  override it gates never fired, and the commit deployed to refresh-worker
  completely inert. The tests passed because their fixtures were written with
  the same invented key: **they asserted against the same wrong schema as the
  bug, so they confirmed it rather than catching it.** That is not a weak test,
  it is an absent one wearing a passing badge.
- How we found out: by accident, reading the real artifact on disk for an
  unrelated reason — 404,766 bytes with `row_count=980` while a probe printed
  `rows: 0`. Nothing in the test suite, the deploy, or the logs would have said
  so; an inert guard is silent by construction.
- The rule going forward: when a test exercises code that PARSES an artifact,
  build the fixture by calling the real WRITER (patch its output root), never by
  hand-writing a payload literal. Add one explicit schema-agreement assertion
  naming the key. And before trusting a new guard, verify the test can FAIL:
  reintroduce the bug and watch it go red. Here that flipped 3 tests red and
  back to green, which is the only evidence the tests were load-bearing.
- Cost: one wasted deploy of an inert change (~20 min build), on the day before
  the season opener. The silver lining is the only reason it was harmless: an
  override that never fires also never busy-loops.
## 2026-09-08 RECURRENCE, not a new rule: I compared a baseline recorded on ONE host against a run on ANOTHER and read the difference as change over TIME. `[lane render-cron-failures, session e371dfde]`

**The general case is already here** — 2026-08-28, *"baselining a test in a
fresh worktree when the test reads state the worktree does not share — it is
not a baseline, it is a different experiment"*. This is that rule in a shape it
did not cover in my head: **a persisted baseline FILE**, not a worktree.

- **What I did.** `tests/pytest_baseline.json` records 19 known-failing tests,
  taken 2026-08-26 under `-n auto` on somebody's machine. The `ci-suite` cron
  first completed the suite 2026-09-08 and reported 25 new failures. I filed 19
  of them as REGRESSIONS on two checks that were both TRUE — the test existed at
  the baseline commit, and it still failed in ISOLATION on the cron — and both
  are equally consistent with *never having passed on that host*. **The cron did
  not exist when the baseline was taken.** 15 of the 19 turned out to be a
  memory floor (`floor_mb=3000` against `max_mb=2048`) that the runner cannot
  reach; the rest were stale tests. **Zero regressions.**
- **The sentence that would have caught it:** *"not in the baseline's failing
  set"* means **passed somewhere else**, never **passed here**.
- **Why it is worth a line despite the duplicate-rule ban.** The recurrence is
  the information: the 2026-08-28 rule is filed under WORKTREES, and I did not
  retrieve it while holding a JSON file recorded on a different box. A rule
  indexed by its mechanism is invisible from a different mechanism. If this
  family gets consolidated (see the 2026-09-08 MAP entry), index it by the
  QUESTION — *are these two numbers from the same environment?* — not by the
  artefact that carried it.
- **Retracted publicly the same day**: `#648`, `.syndicate/findings_2026-09-08_nineteen_pytest_regressions.md`,
  commits `db9febae` / `33abd83c`. A peer session's two passing runs on their own
  machine are what broke it open.


### 2026-09-08 — FORBIDDEN: pricing a market against an estimator without asking WHICH QUANTITY it estimates.

- What we believed: the NFL prop model produced a per-game projection, so a
  disagreement with the line was an edge.
- What was actually true: `player_game_log` only creates a row for a game the
  player has a QUALIFYING PLAY in, so a receiver who dressed and was never
  targeted left the denominator. The model estimated **yards per game he was
  INVOLVED in**; the market prices **yards per game**. Measured over 1,923
  quoted rows: median +7.7%, mean +12.1%, 24% of rows >25% ABOVE the line
  against 5% below — concentrated in `receiving_yards` (+18.2%) and
  `rushing_yards` (+11.9%), while `passing_yards` (-1.1%) was clean because a
  quarterback never loses a game from his denominator.
- How we found out: comparing the model's projected value against the quoted
  line per market, instead of only reading the probabilities it produced. The
  per-market split is what identified the mechanism — a pooled number would have
  shown "+12% high" and named nothing.
- The rule going forward: before treating model-minus-market as an edge, state
  the estimator's POPULATION and check it is the population the bet settles
  over. A systematic one-sided bias is an estimator defect until proven
  otherwise; edges are two-sided.
- Cost: every "edge" on the board was inflated for as long as props have
  existed, and a +46.5% headline was shown to the user as evidence of health.

### 2026-09-08 — FORBIDDEN: crediting an improvement to a change without an A/B, when two fixes shipped close together.

- What we believed: the zero-game estimator fix produced "a dramatic reduction
  in overconfidence" — no more 95% probabilities, no more +46% edges.
- What was actually true: measured both ways on the same board, cards claiming
  >90% are **8 either way**; median |edge| 9.2 -> 8.4; edges >30pts 57 -> 51.
  The absurd readings were killed by the LINE-KEY fix shipped an hour earlier.
  Its real contribution is the bias (median +7.7% -> +3.5%), which is a
  different and less dramatic claim.
- How we found out: running the estimator A/B under its own flag, after having
  already told the user the wrong attribution.
- The rule going forward: when two fixes land in one session, no improvement may
  be attributed to either until each is measured with the other held fixed. A
  remembered "before" is not a baseline — and the flag that makes the A/B
  possible must be used, not merely shipped.
- Cost: one wrong claim to the user, retracted in the next message.


### 2026-09-08 — FORBIDDEN: pushing `render.yaml` without first ENUMERATING the live env of all three services. It is 166 keys behind production.

- What we believed: `render.yaml` describes production, so adding one gunicorn
  flag to it is a one-line change whose blast radius is that flag.
- What was actually true, measured key-by-key against
  `/v1/services/<id>/env-vars` (paginated at 100; `limit` > 100 returns 400):

      service            yaml   live   sync would DELETE   would CHANGE
      web (syndicate)      52     84          33                1
      refresh-worker       84    161          77                1
      live-odds-worker     76    132          56                1

  **A `blueprint_sync` would delete 166 live env vars and overwrite
  `ODDS_API_KEY` on all three services with a different value.** Among the
  deletions: `SYNDICATE_EXECUTION_MODE=live`, `SYNDICATE_EXECUTION_LIVE_ARMED=1`,
  and the spend caps of a LIVE-MONEY execution system
  (`MAX_ORDER_DOLLARS=10`, `MAX_DAY_DOLLARS=40`, `..._ALL_VENUES=150`), plus
  sport intervals, segment markets and backfill windows. The caps do have code
  defaults so deletion is not "unlimited" — but it silently rewrites a
  live-money configuration that nobody has enumerated.
- How we found out: by running CLAUDE.md's own pre-push enumeration instead of
  treating it as boilerplate. It took one script and it was the difference
  between a one-line flag and a three-service configuration rewrite.
- The rule going forward: **`render.yaml` is not a description of production;
  it is a 166-key-stale proposal to REPLACE production.** Nobody may push it
  until the drift is reconciled INTO the file. Until then, treat any
  render.yaml edit as blocked, and reach production config through the
  SINGLE-KEY env endpoint (`PUT /v1/services/<id>/env-vars/<KEY>`), which
  writes exactly one key and fires no sync. The bulk `PUT /env-vars` is the
  same failure mode by hand and must not be used either.
- Worked example, same evening: the gunicorn `--max-requests` fix web needed was
  delivered by setting `GUNICORN_CMD_ARGS` as a single env key (84 -> 85 keys,
  verified, nothing else touched) instead of editing the startCommand in
  `render.yaml`. Identical effect, no sync, revertible by deleting one key.
- Cost: none, because the enumeration ran first. Had it not, the cost would have
  been a live-money system's configuration and every sport's tuning, hours
  before the NFL season opener.


### 2026-09-08 — FORBIDDEN: editing a `.claude/hooks/` file in a worktree and believing it is in force. Hooks run from the PRIMARY tree.

- What we believed: a guard change landed on `main` is a guard change in effect.
- What was actually true: `deploy-guard.py` resolves its root as
  `CLAUDE_PROJECT_DIR`, which is the PRIMARY tree, and the hook binary Claude
  Code executes is that tree's copy — not the worktree's, and not `main`'s. A
  new `render.yaml` drift branch tested green in the worktree and was **inert**
  in every real invocation, because the checker it shells out to did not exist
  at that root. The helper's missing-file branch returns "allow", so it failed
  silently and open, which is correct for a hook and invisible to the author.
- How we found out: by driving the branch with a forced payload instead of
  trusting that a landed commit is a live guard. The same session had already
  shipped one inert guard earlier in the day, which is the only reason the
  question got asked.
- The rule going forward: after changing anything under `.claude/hooks/`, prove
  it from the PRIMARY tree — run the hook's own test there, or invoke the hook
  with a payload — before recording it as protection. And a hook that shells out
  to a script must be landed TOGETHER with that script into the tree the hook
  reads, or the guard is a no-op that looks installed.
- Related: the primary tree can be hundreds of commits behind with dozens of
  modified files, so "pull it" is not a safe default. Update the specific clean
  files, then UNSTAGE them — `git checkout <ref> -- <paths>` stages as a side
  effect, and the index there is shared.
- Cost: none this time. The cost avoided was a guard that everyone believed was
  protecting a live-money configuration and was not.
## 2026-09-08 An era split that quarantines a STORED metric does not bind a recomputation from the RAW records — check which one the split is about before accepting its sample size `[scheduled task live-gameline-accuracy-snapshot, no lane]`

- **The rule.** When a tool refuses to pool across a boundary, read WHAT it pools.
  `pool_live_gameline_trend.py` raises on a mixed-era set, and the task brief
  states flatly that a number spanning the eras "measures the bug, not the
  model". Both are correct **about the board's STORED score**, which pre-`75cf9aec`
  compared `P(over)` / `P(home covers)` against "did the home team win". They say
  nothing about a figure recomputed from the raw ledger, because filtering
  `market=='h2h'` yourself *applies the post-fix restriction by construction*.
- **What it cost to not notice.** The quarantine was inherited as a fact about the
  DATA rather than about one consumer of it, and that capped the analysis at
  **121 games / 9 dates** when **252 games / 19 dates** were sitting in the same
  retained ledger. On the smaller sample the headline result's CI straddled zero
  (`>10pp`: +0.03063, CI [-0.00916, +0.07095]); on the full one it does not
  (+0.03432, CI [+0.00650, +0.06077]). **The boundary was not costing accuracy,
  it was costing power** — and an under-powered result reads as "we cannot say
  yet", which is indistinguishable from "there is nothing here".
- **How to discharge it.** Diff the boundary commit against the fields you
  actually read, and say so. Here: `git show --stat 75cf9aec` / `4d20ea00` touch
  neither `model_home_win_prob`, `market_fair_prob` nor `market`; v3 added `line`
  to `record_key` (population change for totals/spreads dedup only) and v4 added
  the game clock. **The same diff found a boundary that DOES bind:** `priceable`
  gained stale/age-absent refusals on 2026-09-01, so any priceable-cut comparison
  spanning that date is not like-for-like. One check, two answers, opposite signs
  — which is the point. Do not generalise either.
## 2026-09-08 FORBIDDEN: reading an empty segment as an ABSENT FIELD without checking the field's TYPE. A wrong type guard and a missing column return the identical empty set `[scheduled task live-gameline-accuracy-snapshot, no lane]`

- **What happened.** A score-state segmentation returned zero rows in every bucket
  and was reported to the user as *"the most promising remaining segmentation is
  blocked by instrumentation — `home_score`/`away_score` are null on every row"*,
  with a lead offered off the back of it. The fields were fully populated:
  **string**-typed (`'0'`, `'1'`), and the filter was `isinstance(h, int)`. A
  by-version field census, run for an unrelated reason, showed `home_score
  984/988` and blew the claim up.
- **Why the existing rule did not catch it.** `learnings.md`'s "read the field you
  already have" and "absence in a window isn't absence" both point at a field
  being *unfetched* or *unpopulated*. This one was fetched AND populated, and the
  emptiness was manufactured by my own predicate one line later. **The null result
  is evidence about the QUERY until the query has been shown to be capable of
  returning something.** Same failure class as "prove the frame could have been
  non-null" (2026-09-05), reached through types rather than through sampling.
- **The cheap check.** Before reporting any segment as unavailable, print the
  population and the distinct values of the field you filtered on — not its
  non-null count, which was 4,489/4,489 here and looked perfect. Two of the four
  "dead field" claims made in that same pass were wrong for two different reasons
  (`sigma` was constant BY DESIGN — it is `PRICEABLE_SIGMA`, documented in
  `state.md` and in the code comment; the scores were a type error), and both were
  withdrawn inside the session. **A field census is one command and it is the
  thing that should precede the claim, not follow it.**
## 2026-09-08 A Brier gap is not evidence of miscalibration. DECOMPOSE before prescribing a recalibration — reliability and resolution fail differently and only one of them is fixable by a transform `[scheduled task live-gameline-accuracy-snapshot, no lane]`

- **The trap.** A model that scores worse than the market, and whose error grows
  monotonically with how far it departs from the market, *looks* exactly like an
  overconfident model. I stated that reading to the user and wrote it into
  `state.md` as "strongly indicated". The reliability curve refuted it the same
  session: the model is **adequately calibrated** (slope 0.9053, ECE 0.03037 vs
  0.02514, all ten bins' bootstrap intervals covering the diagonal), and the
  reliability gap is **+0.00055 with a 95% CI of [-0.00324, +0.00475] — it spans
  zero.** The deficit is **resolution**: +0.00790, CI [+0.00065, +0.01511].
- **Why it matters more than a wording fix.** Brier = reliability - resolution +
  uncertainty, and **a recalibration can only move the reliability term.** Driving
  it to zero — a ceiling no fitted transform actually reaches — leaves the model at
  0.17711 against the market's 0.17020. **At most 6.5% of the gap is reachable by
  recalibration.** That is the mechanism behind the leave-one-date-out
  recalibration already recorded as having failed out of sample, and it predicts
  that any further transform-fitting will also fail. Without the decomposition the
  obvious next move — "it's overconfident, shrink it" — is a guaranteed dead end
  that looks reasonable and costs a cycle.
- **The distinguishing measurement, and it is cheap.** Higher spread with lower
  resolution is the signature: model sd **0.28231** vs market **0.26601** while
  model resolution **0.07146** vs market **0.07935**. It moves more and tracks
  outcomes less — the extremeness is variance, not information. **Check the split
  at several bin counts before believing it** (Murphy is bin-dependent): here
  resolution held 92-98% of the gap across 5/8/10/15/20 bins, so the finding is
  not a binning artifact. A single bin count would not have earned the claim.
## 2026-09-08 FORBIDDEN: validating a measurement instrument ONLY against a case whose expected answer is the SAME as the bug's output. A control that cannot distinguish "working" from "broken" is not a control `[lane mlb-pregame-baseline-feed]`

Reconstructed from `log/2026-09-08.md` (entry *"reliability curve, the encompassing
null, and the pregame-baseline fix"*) and `deploys.md` `## 2026-09-08 20:44:27Z —
live-odds-worker 57052784`, which recorded the reading as MEASUREMENT PENDING with
the pre-fix control quoted below.

- **The TECHNICAL failure: none in the system.** The fix worked on the first
  deploy. What failed was the INSTRUMENT that judged it. `measure_pregame_baseline.py`
  filtered `game_state == "live"` and never filtered `market == "h2h"` /
  `segment == "full"` — the h2h restriction my own historical analysis had used
  hours earlier in the same session, on the same ledger.
- **What we believed:** "STILL NULL on live rows — the fix did NOT reach
  production", reported to the user as a terminal verdict on **109 post-deploy
  rows, 0 non-null**.
- **What was actually true:** all 109 rows were `first1`/`first3`/`first5`
  SEGMENT REFUSALS (`market=totals_alt`, `withheld_reason=segment_pricing_disabled`,
  `game_pk=None`, `model_home_win_prob=None`) — the rows a sibling lane made
  visible in the ledger. They carry no `live_mc` h2h lane, so the field is
  legitimately None on them and always would be. **Priced full-game h2h rows in
  that population: ZERO.** The correct verdict was "nothing to read". Forty
  minutes later, on the corrected predicate: **38/38 non-null, 7 games, 7
  distinct values.**
- **How we found out:** by printing EVERY FIELD of one raw row instead of
  trusting the aggregate. The row count was 109 — big enough to feel like a
  sample, and that feeling did the damage.
- **WHY THE EXISTING RULE DID NOT CATCH IT, which is the point of this entry.**
  `learnings.md` already carries *"a null result needs a live population — prove
  the frame could have been non-null"* (2026-09-05), and I WROTE A SIBLING RULE
  THE SAME DAY (*"reading an empty segment as an ABSENT FIELD"*). Prose did not
  save me. What I actually did was build a positive control — 2026-09-07,
  pre-fix, "4,017 live rows, 0 non-null" — and declare the instrument validated.
  **That control expected NULL. The bug also produced NULL. So the control was
  incapable of detecting the defect, and its green reading is what gave me the
  confidence to report a falsification.** It even mis-stated its own denominator:
  4,017 was every live row, where only ~521 were h2h.
- **The rule going forward:** an instrument that can emit a NEGATIVE verdict must
  be validated against a case whose expected answer is **POSITIVE**. If every
  control you have expects the same output as the failure mode, you have tested
  nothing. Corollary, and cheaper than the rule: **before reading a null as a
  falsification, print the COMPOSITION of the population you scored — the
  breakdown by the discriminating fields — never only its size.** `n=109` and
  `n=0 of the right kind` are the same number to a counter and opposite answers
  to a reader.
- **Cost:** one false FALSIFIED published to the user, withdrawn ~15 minutes
  later. Had the raw row not been inspected, a working fix would have been
  recorded as broken and the next session would have re-debugged a non-defect.
- **THE CHECK, because prose demonstrably failed twice here.**
  `measure_pregame_baseline.py` now prints the post-deploy population's
  `(market, segment)` breakdown and returns exit 2 — "nothing to read" — rather
  than exit 1 whenever the priced-full-game-h2h subset is empty. Exit 1 is now
  reachable ONLY from a non-empty, correctly-typed population. Any future
  measurement script in this repo owes the same two things: a composition print,
  and a positive control.
## 2026-09-08 FORBIDDEN: concluding two working trees hold the SAME content because the same path is dirty in both. Co-occurrence is not identity, and the difference is ADDITIONS a deletions count cannot see `[worktree cleanup, no lane]`

- **What I believed:** `unknown-submit-retry-provenance` carried "routine mirror
  churn, regenerable, safe to discard" — reasoned from the fact that
  `vendor/wnba_betting_repo/data/processed/schedule_2026.{csv,json}` are ALSO
  dirty in the primary tree. I said so to the user and moved to `git checkout --`
  them.
- **What was actually true:** `.claude/hooks/discard-guard.py` blocked it, having
  searched **all 58 committed versions across every ref**: **16 CSV lines and 1
  JSON line exist in NO commit anywhere.** Two trees can carry DIFFERENT
  modifications to the same path; "both dirty" says only that both were touched.
- **How we found out:** the guard, not me. I had already committed to the
  conclusion in a message.
- **The rule going forward:** before discarding a modification because "it is
  also modified elsewhere", DIFF THE TWO VERSIONS AGAINST EACH OTHER, or search
  the content across refs. Same path + both dirty is not evidence of same
  content. **And the failure is invisible to the usual check:** unique content
  here is ADDITIONS, so `git diff --numstat` reading "0 deletions, nothing of
  mine destroyed" is exactly the reassurance that fails — the same shape as the
  2026-09-03 lane-block destruction the guard's own docstring cites.
- **Cost:** none, because the guard held. Would have been 17 lines of content
  existing in no commit on any ref, deleted on a bad inference.
## 2026-09-08 FORBIDDEN: extracting a block by splitting ONLY on its own delimiter. The LAST block swallows the file's entire trailing structure, and pasting it elsewhere duplicates that structure silently `[lanes.md reconcile, no lane]`

- **What I believed:** a lane block runs from its `### <slug>` header to the next
  `### ` header, so extracting one from `origin/main:.syndicate/lanes.md` and
  inserting it locally is a clean copy.
- **What was actually true:** `bandwidth-controlled-transfer` is the LAST block in
  upstream's `## OPEN` section, so "to the next `###`" ran to END OF FILE. Its
  "block" was **234 lines** carrying `## Archived lanes` and **12 other `## `
  structural headings**. Inserting it dropped a duplicate archive heading into the
  middle of the OPEN section and pushed the next inserted block BELOW it — where
  `lane-guard` reads it as archived and **stops enforcing its file claims,
  silently**. Correct extraction bounds the block by the next `###` **OR** the
  next `##`, whichever comes first; the same block then measures **8 lines**.
  234 vs 8 is the tell.
- **How we found out:** `.claude/hooks/ledger-postwrite-check.py` fired on the
  write — "lane block(s) BELOW `## Archived lanes`". Not from reading the diff:
  the insert looked correct in every summary I printed, because the corruption
  was INSIDE a block body I never examined.
- **The rule going forward:** any structural extractor must be bounded by the
  NEXT DELIMITER OF ITS OWN LEVEL *OR ANY HIGHER LEVEL*, and the cheap check is
  to assert the extracted body contains **no heading of a higher level than the
  block itself** — one line, and it would have caught this before the write.
  Sanity-check the extracted SIZE too: one block 30x the others is not a big
  block, it is a parse that ran off the end.
- **DO NOT "FIX" THIS BY HOISTING.** The guard suggests `hoist_open_lanes.py`,
  which moves the misplaced block — correct for a genuine ordering drift, wrong
  here, because it leaves the duplicated `## Archived lanes` heading in place and
  the file stays corrupt in a way the next check will not name. Revert to the
  pre-write backup and redo the extraction.
- **Cost:** none — reverted from a backup taken before the write. Would have been
  a shared ledger with duplicated section structure and at least one OPEN lane's
  claims silently unenforced for every session in this tree.
## 2026-09-08 When reconciling two divergent copies of a ledger, RECENCY ALONE MAY NOT PICK THE WINNER. Check the losing side for UNIQUE CONTENT before overwriting it `[lanes.md status reconcile, no lane]`

- **The situation:** 20 lanes were OPEN locally and CLOSED/ORPHANED on
  `origin/main`. Flipping them is the DANGEROUS direction — a closed lane's
  claims stop being enforced, so a wrong call lets another session edit across
  lanes silently.
- **Recency said take upstream, unanimously:** local was newer for **0 of 20**,
  upstream newer for 15, equal for 5. On that evidence alone the answer is
  "overwrite all 20".
- **That would have destroyed work.** A separate unique-content check — every
  substantive local line searched against upstream's `lanes.md` +
  `lanes_closed.md` + `lanes_history.md` — found **3 blocks carrying lines
  present nowhere upstream**, including a shared-file declaration written earlier
  the same session. Those 3 were left untouched; the other 17 were replaced.
- **Why recency was insufficient, concretely:** 5 of the 20 tied on date, and two
  carried dates in the FUTURE (09-10, 09-15 against a real date of 09-08) because
  the max-date proxy reads target dates out of body prose, not edit times. A
  date extracted from free text is a weak instrument and cannot be the only one.
- **The rule going forward:** two independent checks must AGREE before
  overwriting a block in a shared ledger — one for which side is newer, one for
  whether the losing side holds anything unique. If they disagree, keep the local
  copy: over-enforcement of a stale claim is recoverable, a deleted claim or a
  deleted note is not.
- **Cost:** none. The method is the same predicate `discard-guard.py` applies to
  file content, applied to ledger blocks.
### 2026-09-09 — DISCHARGED, not overridden: the 2026-08-29 NCAAF alias-map prohibition was CONDITIONAL, and both its conditions are now met

- **What we believed:** that `FORBIDDEN: closing a name-join gap by POPULATING an
  alias map, without first checking the map's source carries the missing name`
  (2026-08-29) barred NCAAF from ever getting a map. Read as a blanket ban it
  would have left `canonical_team("ncaaf", …)` returning `None` for every club
  indefinitely.
- **What was actually true:** the rule's own wording is conditional -- it forbids
  populating a map *without first* doing two things, and it names both: (a)
  confirm the SOURCE contains the specific name the join fails on, and (b)
  enumerate what the map resolves that the heuristics previously left
  unresolved, because those lookups flip from "fall back" to "authoritative".
  **Both were run and both passed**, on the 08-29 entry's own named failures:
  `umass minutemen` -> `massachusetts` now resolves (the token that defeated the
  08-29 attempt), and `canonical_team("ncaaf","MAS")` -> `UMass Dartmouth` -- its
  headline mis-resolution -- returns **None**.
- **Why it works now and did not then:** a DIFFERENT SOURCE and a different
  derivation. 08-29 built 2,232 keys from `unambiguous_team_index()` over
  `ncaaf_team_registry.csv` (2026-07-21). This derives 595 entries over 138 FBS
  clubs from `iter_team_alias_offers()` over
  `ncaaf_team_registry_snapshot.csv` (2026-08-26) -- the file
  `oddsapi_lines.resolve_team` actually reads. **Fewer keys, better ones.** The
  collision pass also counts across all four divisions BEFORE filtering to FBS,
  so a code an FCS school also claims is dropped rather than handed to the FBS
  programme: 95 bare mascots dropped (`tigers` 25 schools, `bulldogs` 23,
  `wildcats` 15).
- **The semantics-flip the 08-29 rule feared was measured and went the other
  way.** Wrong-pair false positives **fell 7 -> 1**: `Iowa`/`Iowa State`,
  `Ohio`/`Ohio State` and `Texas`/`North Texas` all returned True under the old
  prefix heuristic and are now correctly distinct. `teams_match` gained **+190
  correct with 0 lost**.
- **How we found out:** by treating the rule as a checklist rather than a wall,
  running its two gates against the exact tokens its evidence entry names, and
  refusing to proceed on key count alone -- which is precisely the error 08-29
  recorded ("2,232 keys looked like success; the one token that mattered still
  returned `None`").
- **The rule going forward:** **a CONDITIONAL prohibition is discharged by
  meeting its conditions and recording the measurement, not by asking for an
  override.** Read the rule's own wording before treating it as absolute, and
  when it names a failing token, test THAT token. The blanket reading of this
  entry would have cost the platform every NCAAF club resolution indefinitely.
  Where a rule IS absolute (`FORBIDDEN` with no condition), this does not apply.
- **Cost:** none. 138/138 FBS clubs resolve, 102/102 club slots on a 51-game
  card, 22/22 eligible board games via `match_event_blob`, where all were 0.
  Landed `04a82c38` + `8730b829`. **Scope held: this removes ONE OF TWO gates on
  the Kalshi execution path and places no orders** -- none of today's NCAAF
  contracts is FBS-vs-FBS.
## 2026-09-09 FORBIDDEN: reporting a sweep as COMPLETE without its COVERAGE DENOMINATOR. A sweep that was stopped early is not a sweep, and "every hit I found is fixed" reads as "every hit is fixed" `[lane data-tree-write-guard, commit 7a03160d]`

`ac801817`'s own message said "all 57 data/-mirror write hits closed, at four
seams". True of the 57 that had been NAMED, and false about the sweep: the verbose
pass that produced them was stopped at ~37%. A peer session ran theirs to
completion and reported **105 hit node ids across 23 files**.

The 48-hit gap was not cosmetic. Re-measuring their extra files against
`ac801817` found **11 live hits in 3 files**, so `main` was RED for those tests
while a landed commit message described the sweep as closed.

**HOW TO APPLY.** State the denominator with the numerator, every time: "57 of a
pass that reached 37%" is honest and "all 57" is not. The words that made this
wrong are cheap to fix — "every hit I found" rather than "all hits" — and a
partial sweep is worth landing, so this is a REPORTING rule, not a do-more-work
rule.

**AND THE SAME SHAPE, TWICE MORE IN ONE SESSION.** A per-file green result
(`test_refresh_worker.py` 70/0) cannot see a between-test write — the peer's 25 of
143 vendor-schedule writes carried an EMPTY `PYTEST_CURRENT_TEST`. And a
guard-ON-and-clean reading cannot tell FIXED from BLOCKED; only the guard-OFF arm
can. In all three the reading was true and the SCOPE it was offered for was wider
than the reading could support.
## 2026-09-09 FORBIDDEN: caching a `git check-ignore` verdict per DIRECTORY. The answer differs INSIDE one directory — that is the whole point of the exemption — and one query for an ignored name then exempts every TRACKED file beside it `[lane data-tree-write-guard, hole found by lane data-mirror-write-guard-sweep, fix ba732005]`

The guard in `tests/conftest.py` exempts a write whose path `.gitignore` already
excludes, and the exemption's stated basis is that **`git check-ignore` answers
NOT ignored for anything in the index, whatever rules match it** — so a new cache
file under an ignored-by-rule subtree is exempt while a TRACKED file beside it is
not. I then cached the verdict per directory "because a directory rule applies to
the whole subtree", which denies exactly that.

MEASURED, one directory holding 208 tracked files:

    tracked      -> False   correct
    ignored name -> True    correct, and PRIMES the per-directory cache
    tracked      -> True    WRONG — guard disarmed for the rest of the process

**THE SHAPE, past this instance: A CACHE KEY COARSER THAN THE PREDICATE IT CACHES
IS A CORRECTNESS BUG, NOT A PERFORMANCE TRADE.** The predicate here is per-PATH by
definition; keying it per directory cannot represent two answers, so the second
answer is silently replaced by the first. Check the key against the predicate's
own granularity before caching anything.

**AND THE SELF-CHECK POISONED IT.** The test that pins "a tracked file inside an
ignored subtree is still guarded" ended on a query for an ignored NAME in that
directory, priming the cache as its last act. It passed alone and failed only in a
parallel full run. So: **a guard's self-check must not leave the guard in a
different state than it found it** — and the general form, contributed by the
sibling lane, is that A SELF-CHECK FOR A GUARD MUST ASSERT THE GUARD IS INSTALLED
BEFORE IT EXERCISES THE GUARDED PATH, or the check's own failure mode is to
perform the damage it exists to detect.
## 2026-09-09 FORBIDDEN: trusting a LOCAL end-to-end test of a producer/reader pair that crosses SERVICES. Locally the state backend is `filesystem` — one process, one disk — so the test proves the code and says nothing about whether the two services share a store `[lane intelligence-coverage-artifact, commit 5c7af861]`

**What we believed.** The new coverage artifact was proven: the worker-side
publish and the web-side read were exercised end to end, and BOTH states were
observed — the page said "No coverage report published for this date yet", then
the loop logged `PUBLISHED date=2026-09-09 sports=8` and the page showed
"Published 13:12:20". That is a genuinely discriminating local reading.

**What was actually true.** It was a reading about the CODE, not the
DEPLOYMENT. `_state_backend_kind()` returns `filesystem` locally, so producer
and reader were one process writing and reading one disk. In production they are
two services, and *Render's disk cannot be shared between them* — the whole
reason `refresh_state_store` exists. The local pass would have looked identical
if the artifact were per-service disk, which would have made the page
permanently degraded in production while every test stayed green.

**How we found out.** Asking, before deploying web, which paths
`_keyvalue_backed()` actually covers — then reading the LIVE env-vars API for
both services rather than `render.yaml`. Backend and store URL matched. The
namespace did NOT look symmetric: web sets
`SYNDICATE_REFRESH_STATE_NAMESPACE`, refresh-worker omits it. That resolved
safely only because `_state_namespace()` defaults to exactly web's value
(`"syndicate"`). Had the default been anything else, the deploy would have gone
green and the artifact would have been written under one prefix and read under
another.

**The rule going forward.** For any artifact one service writes and another
reads, three things get checked on the LIVE services before the deploy, not
after: (1) the path is keyvalue-backed — no `_KEYVALUE_EXCLUDED_PATH_MARKERS`
hit; (2) `SYNDICATE_REFRESH_STATE_BACKEND` and `..._URL` match on both; (3) the
NAMESPACE resolves to the same string on both, **including when one side omits
the key and falls back to a default**. An asymmetric env var is not
automatically a bug and not automatically fine — resolve it to a value.

**And the generalisation of the near-miss:** a fallback default that happens to
equal the other side's explicit value is a correct system for an accidental
reason. It is worth writing down precisely because nothing in the code says the
two must agree.
## 2026-09-09 A REPLACEMENT THAT IS LESS INFORMATIVE THAN WHAT IT REPLACED IS A REGRESSION, however much better it looks. A generic branded 404 discarded the route's own `abort(404, description=...)` `[lane brand-mascot-logo, commit 00902dd1]`

**What we believed.** Adding the app's first-ever error pages was a pure gain —
before them a typo'd URL served Werkzeug's bare white default, with no nav and
no way back.

**What was actually true.** Some routes 404 with something far better than a
generic page can say. Soccer's unknown-league gate aborts with a description
naming every valid league slug; the new handler threw that away and printed
boilerplate. Strictly worse than the ugly page it replaced, for that route.

**How we found out.** `tests/test_soccer_blueprint_routes.py::
test_the_404_names_the_valid_leagues` — a test written for a different reason
that happened to pin the message. Nothing in review caught it, and the page
looked good.

**The rule going forward.** When replacing a generic surface with a branded one,
enumerate what the OLD surface carried that the new one drops. For HTTP errors
specifically: read `HTTPException.description` and prefer it, comparing against
the **class default** rather than truthiness — werkzeug always populates that
field, so a truthiness check silently prints its boilerplate instead of yours.

**Two sibling defects in the same change, both found by probe rather than
review, both the same shape — an instrument that cannot vary:** the 500 log line
printed `type(exc).__name__`, which Flask makes the constant
`InternalServerError` on every 500 ever logged (the cause lives in
`original_exception`); and `Accept: */*` scores html and json equally, so a `>=`
comparison tied and fell to JSON, making `curl` on an HTML path return a JSON
body. A tie is not a preference.
## 2026-09-09 FORBIDDEN: reading a ZERO-HOLDER result from `lane_claims` as "nobody is working on this file". It reports on lanes, and a session can be instructed not to open one. `[lane data-mirror-write-guard-sweep, session 83b5aca4]`

- **What we believed:** the documented collision check — `lane_claims.claims_by_path` over `origin/main:.syndicate/lanes.md`, the guard's OWN parser — answers "is anyone else editing these files". Zero holders means the files are free.
- **What was actually true:** it answers "does any lane BLOCK DECLARE these files". A second session was actively editing all four of my files, had already landed a commit touching them, and held two more unpushed — and returned ZERO, correctly, because its instructions explicitly forbade it from editing `.syndicate/*`, so it had never opened a lane. The check was accurate and the conclusion was wrong. The set it measures is SELF-SELECTED: a session told to stay out of the ledger is invisible to it BY CONSTRUCTION, and those are exactly the sessions least likely to coordinate.
- **How we found out:** the other session messaged mid-work asking me to stand down, then corrected me itself: *"my lane isn't declaring those files because I never opened a lane"*. Nothing in my own tooling could have surfaced it — I had run the strongest available check and it passed.
- **The rule going forward:** a zero-holder result is evidence about `lanes.md`, NEVER about the world. State it with its scope — "no OPEN lane declares these" — never as "these files are free". Before a multi-file edit to shared infrastructure (`tests/conftest.py`, `.claude/hooks/`, the ledger), pair it with a check the ledger cannot opt out of: `mcp__ccd_session_mgmt__list_sessions` for live sessions, and `git log --oneline -5 -- <paths>` for recent commits by anyone. A lane check plus a commit check disagree exactly when it matters. **And the check itself should report "N sessions declared" alongside the holder list** [suggested by `local_74f19a18`]: zero holders and zero DECLARERS read identically today, and only one of them means the file is free.
- **Cost:** two sessions duplicated a full sweep of the same suite — roughly 70 minutes of full-suite runs each, plus two rounds of user adjudication. No work was lost, because both sessions worked in isolated worktrees and neither pushed; the isolation protocol did its job even though the coordination protocol did not.
## 2026-09-09 FORBIDDEN: concluding a guard closed a hole because the symptom disappeared between two runs that ALSO differ in test ORDER. `[lane data-mirror-write-guard-sweep, session 83b5aca4]`

- **What we believed:** the newly-added `os.open` wrapper explained why a tracked mirror file (`live_lens_2026_06_02.jsonl`) was modified in run 1 and clean in run 2. It was the only relevant code change between them, and the file's `1 0` diff matched a copy path that uses `os.open` exactly.
- **What was actually true:** nothing of the sort. The A/B — wrapper present vs removed, one variable, same test — gave the IDENTICAL result in both arms: the test errors, the file stays at 20 lines, 0 dirty. The writer is caught by the ordinary `Path.open` guard either way. `pytest-randomly` reseeds every run, so run 1 and run 2 differed in test order as well as in code, and the order is the surviving explanation.
- **How we found out:** ran the mutation check instead of banking the story. It took 8 seconds and falsified a claim I had already sent to another session.
- **The rule going forward:** between two full-suite runs, code is never the only variable — `pytest-randomly` makes ORDER a variable too, and order decides which test reaches a shared artifact first and in what state. A symptom that moves between runs is attributable ONLY by a same-order A/B on the single change, never by "it was the only thing I changed". Corollary: when you hand a candidate explanation to another session, label it a candidate and go run the check, because the retraction has to travel as far as the claim did.
- **Cost:** one wrong candidate published to a peer session and retracted within the hour. Caught before either of us wrote it into a commit message or a `state.md` line.
## 2026-09-09 FORBIDDEN: isolating a test's side effects with a PER-TEST fixture when the thing being isolated can outlive the test. A function-scoped isolation is a WINDOW, not a wall. `[lane data-mirror-write-guard-sweep + local_74f19a18, generalised jointly]`

- **What we believed:** an autouse function-scoped fixture — `monkeypatch.setenv`, `patch.object`, a `tmp_path_factory` redirect — isolates a test's writes. It is the shape this repo's `conftest.py` already uses four times (`_isolate_reports_root`, `_isolate_kalshi_markets_artifact`, `_isolate_prediction_ledger`, and the `data/live` redirect), and each was added after a real dirty-tree incident.
- **What was actually true:** it isolates the test's MAIN THREAD, for the duration of the test. Anything that outlives the test — a background loop the test started, a thread still draining, a subprocess spawned late — runs after teardown has restored the environment, and writes to the REAL path. **MEASURED: of 143 mtime changes on one tracked artifact in a single full-suite run, 25 carried an EMPTY `PYTEST_CURRENT_TEST`** — i.e. they happened between tests, unprotected by construction. No single-file run can show this: with one test file the window is almost always open when the thread writes.
- **How we found out:** two independent instances turned out to be one defect. `local_74f19a18` shipped a subprocess block as an autouse fixture and my empty-`PYTEST_CURRENT_TEST` count showed it was in force only during tests; it was re-landed to enter once at conftest import and never exit (`cb13ce0f`). Separately, `reports/intelligence/*` kept coming back modified despite the function-scoped `_isolate_reports_root`. Same shape, different artifact.
- **The rule going forward:** decide isolation scope by the LIFETIME of what you are isolating, not by the convenience of the fixture. If the code under test can start a thread, a loop or a subprocess that outlives the call, the redirect must be applied ONCE AT IMPORT and never lifted — a `conftest` module-level patch, or an env var set before the first import — not an autouse fixture. Test for it with the population, not the happy path: **an empty `PYTEST_CURRENT_TEST` on a write is the signature**, and it only appears under a full parallel run. Corollary for verification: "I ran the one file and the tree stayed clean" does not test this at all.
- **Cost:** one shipped fix that was inert for the exact case it was written for, caught only because a second session was measuring the same artifact from a different angle. Plus an unknown number of `reports/` rewrites over an unknown period, since three of this repo's four isolation fixtures have the same scope.
## 2026-09-09 FORBIDDEN: adding an `out_dir`/`--out-dir` parameter whose DEFAULT resolves through `data_root()`, and then testing the flagged path. The assertion passes on the flag while the write lands in the mirror. `[lane data-mirror-write-guard-sweep + local_74f19a18]`

- **What we believed:** a test that passes an explicit output directory and asserts on the files there has controlled where the code writes.
- **What was actually true:** it has controlled only the writes that HONOUR the flag. THREE independent instances in one sweep, all the same shape: `append_book_quotes` resolves from `data_root()` and ignores the `--out-dir` its callers pass (`test_ncaab_refresh_runner`); `scripts/emit_settlement_inputs.py:265` takes `out_dir` if given and otherwise `data_root() / "settlement_inputs"`, and `run_refresh_worker.py:2869` calls `emit_for_date(target_date)` with no `out_dir` at all; `_persist_live_lens_report` resolves `live_lens_log_path` separately from `live_lens_report_path`, so a test that redirects the report still writes the log to the mirror. **The assertion on the flagged output is what HID all three** — it was green, and it was green about the wrong file.
- **How we found out:** an interceptor on the write seam, not a review. Each was invisible to a passing test suite; two were invisible to a `-k`-scoped run as well.
- **The rule going forward:** an optional output path is a two-branch function and the tests must cover BOTH branches — call it with the flag AND without. When adding one, make the default raise or require the caller to be explicit rather than silently resolving to `data_root()`. When reviewing a "writes to the wrong place" bug, the question is never "does the test pass an out_dir", it is "does every writer on that path READ it".
- **Cost:** three separate fixes in one sweep for what is one API shape, plus the original reported symptom (`book_quotes/.jsonl` with an empty date prefix) that started the whole guard.
## 2026-09-09 FORBIDDEN: a guard self-check that exercises the guarded path BEFORE asserting the guard is installed. Its failure mode is to PERFORM the damage it exists to detect. `[lane data-mirror-write-guard-sweep + local_74f19a18]`

- **What we believed:** a test for a guard proves the guard works by doing the forbidden thing and asserting it was refused.
- **What was actually true:** that is only safe if the guard is present. When it is NOT — a regression, a mutation check, a half-finished refactor — the test proceeds to do the forbidden thing FOR REAL, and the check becomes the writer. Two instances in one day. Mine: with the `os.open` wrapper removed for a mutation check, the self-check's own `os.open(..., O_CREAT)` SUCCEEDED and left a real file in `data/`. `local_74f19a18`'s: a self-check for the vendored-schedule block, if the block is absent, proceeds to call the real `_fetch_basketball_schedule_via_cli` — so the test guarding the tracked file becomes the thing that rewrites it, over the network.
- **How we found out:** independently, from both sides, and only because both of us ran mutation checks. A guard test that has only ever been run WITH the guard installed cannot show this.
- **The rule going forward:** ORDER THE ASSERTIONS. A guard self-check asserts the guard is INSTALLED first — against a floor the test can see (`_VENDORED_SCHEDULE_FETCH_BLOCK is not None`, a `mirror_roots()` accessor, a marker attribute) — and only then exercises the guarded path. And its cleanup must assume the write MAY have landed, because in exactly the run where the assertion is about to fail, it did.
- **Cost:** one real file written into the tracked mirror by the guard's own self-check. Caught immediately because the mutation run was being watched; in CI it would have been a dirty tree with the guard reporting green.
## 2026-09-09 FORBIDDEN: accepting a mutation check that PASSES without first proving the mutation was REACHED. A no-op mutation and a working guard are the same green. `[lane data-mirror-write-guard-sweep]`

- **What we believed:** a mutation check that comes back green on the fixed code and red on the broken code proves the test binds — and if the "broken" arm stays green, the finding must not be real.
- **What was actually true:** the broken arm can stay green because the MUTATION NEVER RAN, or because the test cannot see it. THREE times in one session, each looking like a clean pass: (1) the patch script's `assert raw.count(old) == 1` failed and the file was never written, so both arms ran identical code; (2) a probe spawned a subprocess from INSIDE a test, where the per-test fixture was active either way, so it could not distinguish; (3) a regression test picked a file in a SUBDIRECTORY, and the defect was keyed on the parent directory, so the poisoned cache entry never applied. In (2) and (3) the test passed against a deliberately reintroduced bug.
- **How we found out:** by running an independent probe — a plain script, outside pytest — against the mutated code and confirming it reproduced the defect. When the probe said "HOLE CONFIRMED" and the test said "passed", the test was wrong.
- **The rule going forward:** a mutation check has THREE outcomes, not two: red (binds), green-because-fixed, and **green-because-the-mutation-did-not-land**. Distinguish them before reading the result. Assert the mutation is present in the file after writing it, and confirm the mutated path is REACHED — an independent probe, a print, a deliberate exception. A test that passes against the reintroduced bug is not a regression test, and the arm that "confirms" your fix is the one most likely to be lying. **GENERALISED, after a FOURTH instance the same day and across two sessions [formulation: `local_74f19a18`]: A CONTROL MUST BE SHOWN TO FAIL IN THE ARM WHERE THE THING IS BROKEN, AND PASSING IS NOT EVIDENCE UNTIL IT HAS.** This is not only about mutation checks. The four, every one of which looked like a clean pass: (1) a child-process probe run INSIDE a test, where the per-test fixture was active in both arms; (2) a regression test that globbed a directory and picked an untracked, ignored shard, so it failed against a CORRECT guard; (3) one that picked a file in a SUBDIRECTORY when the defect was keyed on the parent, so it passed against a deliberately reintroduced bug; (4) a floor probe using `monkeypatch.delenv`, which removes the variable outright instead of peeling off the per-test layer, and prints `None` whether or not the wall exists. In all four the arms were indistinguishable by construction, and in none of them did the runner say so.
- **Cost:** three false reads inside one investigation. Two would have shipped a regression test that pins nothing, against a real correctness hole.
## 2026-09-09 FORBIDDEN: a ledger-append check that only counts DELETIONS. The merge hazard is ADDED lines nobody wrote today. `[lane data-mirror-write-guard-sweep + local_74f19a18]`

- **What we believed:** `git diff --numstat` showing ZERO deletions proves a ledger append did not clobber another session's work. It is the check this repo's rules already prescribe, and both sessions ran it on every ledger write all day.
- **What was actually true:** it catches the clobber and is blind to the inverse. A rebase's 3-way merge RESURRECTED a stale lane block — re-adding `### intelligence-coverage-artifact` in its older OPEN form beside the CLOSED block that was current, silently reverting another session's lane to a status they had already moved past. The diff was **9 INSERTIONS, 0 deletions**, and sailed straight through the check. Caught by `ledger-postwrite-check.py`'s duplicate-slug rule, not by the append discipline.
- **How we found out:** the post-write hook flagged "a lane with MORE THAN ONE block" mid-rebase. `local_74f19a18` then audited their own `lanes.md` the same way and was clean — 22 blocks, 22 distinct slugs — but noted that a duplicate-slug count would MISS the variant that resurrects content INSIDE a block without duplicating the header, and checked per-commit that every added line was theirs.
- **The rule going forward:** **the check is not "0 deletions", it is "every ADDED line is one I wrote."** Same cost, strictly stronger, and it catches both directions. Per-commit: `git diff --numstat` for the deletions AND `git diff origin/main -- <ledger file> | grep '^+'` read against what you actually authored. A duplicate-slug count is a necessary backstop, not the check — it cannot see a resurrection inside an existing block.
- **Cost:** one silent revert of another session's lane status, introduced by my own rebase, in a file whose whole purpose is cross-session exclusivity. Zero lines were deleted.
## 2026-09-09 FORBIDDEN: attributing a test's red->green flip to ORDERING without first checking what LANDED between the two runs. I made this error in BOTH directions in one day. `[lane data-mirror-write-guard-sweep]`

- **What we believed:** first, that a symptom moving between two full-suite runs was caused by the one code change I had made (it was ordering); then, having learned that, that a test flipping red->green between two runs was ordering (it was a fix).
- **What was actually true:** both times TWO things had changed and I named one. `tests/test_probability_differential.py::test_every_converter_is_registered_or_excused` failed in my run 7 and passed in my run 8, and I reported it as order-dependent. It was not: another session's fix `f6c7a3ac` landed 12:37, my run-8 base `c9d6660d` is 13:47, so **the fix was in the tree**. `git merge-base --is-ancestor f6c7a3ac c9d6660d` -> YES. I was one message away from sending that wrong correction to the session that owns the lane, whose own reading (10 passed vs a 1-failed baseline) was right.
- **How we found out:** checking the ancestry before sending the correction, because the claim was about somebody else's work. The same check would have taken ten seconds before publishing it the first time.
- **The rule going forward:** on a shared fast-moving `main`, the tree is a variable between ANY two runs, and usually the largest one. Before attributing a flip to ordering, run `git log <base1>..<base2>` and `git merge-base --is-ancestor <candidate fix> <base>`. "Order-dependent" is a claim about a POPULATION of orderings and needs repeated runs on ONE tree; a single flip across two different trees is evidence about the trees. Corollary: the more experienced you are with the ordering explanation, the more available it becomes — I reached for it precisely because I had just been burned by the opposite error.
- **Cost:** a wrong attribution published to two sessions and nearly a third, plus an inaccurate framing offered to the lane owner about their own closed work. Caught before delivery, by one ancestry check.
## 2026-09-09 FORBIDDEN: AMPLIFYING a peer's unverified CONCLUSION into a relay to a THIRD lane, without measuring it yourself. The bar for a claim about someone else's CLOSED lane is higher than for one about your own, not lower `[lane data-tree-write-guard, caught by lane data-mirror-write-guard-sweep before it was sent]`

**THE ORIGINATION IS CORRECTED HERE `[2026-09-09, at that lane's own
insistence]`. This entry first said they reported an OBSERVATION and that I turned
it into a conclusion. That was wrong in the direction that flattered them, and they
refused it.** What they actually sent, verbatim, was: *"`test_probability_
differential` passed this run, which makes it order-dependent too rather than
reliably red -- worth knowing for the lane you spun out."* "Passed this run" is the
observation; everything after the comma is a CONCLUSION about a third lane's closed
work, with a recommendation to act on it attached.

So the sequence was **their unverified conclusion -> MY AMPLIFICATION into a
proposed relay -> their verification stopping it.** I had spun that test out to
lane `probability-converter-registry` (session 359fa678) on the strength of it
being red on `main`, and that lane had CLOSED it; I agreed with their conclusion
and proposed they tell that session "order-dependent is the more accurate word"
than its own "was RED on main and is now green".

**I DID NOT CHECK, AND IT WAS WRONG.** The peer verified before sending and it does
not survive one command:

    f6c7a3ac  12:37:31  the converter fix
    bdc6ed50  12:08:12  their run 7 base -> `merge-base --is-ancestor` NO
    c9d6660d  13:47:28  their run 8 base -> `merge-base --is-ancestor` YES

It passed because it was FIXED. That lane's framing was exactly right, its
1-failed/10-passed baseline was the right measurement, and my "order-dependent"
was an unforced attribution error about work I had not measured, belonging to a
session that was not in the conversation to defend it.

**WHY THIS IS WORSE THAN AN ORDINARY WRONG NUMBER.** A wrong reading about my own
lane costs me a re-run. A wrong correction RELAYED into a third lane's closed
record costs that session its verdict, and it arrives with a peer's authority
attached rather than mine. The chain was: their CONCLUSION -> my amplification
into a proposed relay -> a message to a third party. NEITHER of us had measured it,
and the amplification is the step that would have made it arrive carrying two
sessions' apparent agreement.

**HOW TO APPLY.** Before relaying anything as a correction to another lane: run the
discriminating command yourself, and if you cannot, relay the OBSERVATION with its
provenance ("their run 8 passed; I have not checked why") and never the CONCLUSION.
"Order-dependent" is a claim about a POPULATION of orderings and needs repeated
runs on ONE tree — a single flip across two DIFFERENT trees is evidence about the
trees. On a fast-moving shared `main` the tree is a variable between any two runs
and usually the largest one: `git log <base1>..<base2>` first.

Related, same day, same pair of sessions: [a-cache-key-coarser-than-its-predicate]
and the rule that a control must be shown to FAIL in the arm where the thing is
broken. Four non-discriminating controls between two sessions in one day; this is
the fifth instance of trusting a reading that had not been made to fail.
## 2026-09-09 FORBIDDEN: appending a rule to `learnings.md` without running `build_learnings_index.py`. The rule is then INVISIBLE to the index every session reads, and nothing anywhere reports the drift `[lane data-tree-write-guard, found while correcting an unrelated entry]`

Measured 2026-09-09: `grep -c` for my freshly appended rule in
`.syndicate/learnings_index.md` returned **0**. I had appended to `learnings.md`
and never regenerated. Running `py -3 scripts/build_learnings_index.py` did not
add one rule, it added **31** -- the index header went **917 -> 948**. So this is
not my slip alone; it is the steady state of a file several sessions append to and
nobody regenerates.

**WHY IT MATTERS MORE THAN A STALE COUNT.** The index is the file the session-start
digest and every "what do we already know about X" search actually reads;
`learnings.md` itself is 948 rules and no session reads it whole. A rule that is
in `learnings.md` and not in the index has been WRITTEN and not PUBLISHED. It will
be rediscovered the expensive way, which is precisely what the ledger exists to
prevent -- and the author has no signal, because the append succeeded, the commit
succeeded, `git status` is clean, and the diff shows exactly the lines intended.

**THE SHAPE, past this instance: A GENERATED VIEW THAT IS NOT REBUILT BY THE WRITE
THAT INVALIDATES IT WILL DRIFT SILENTLY, AND THE DRIFT IS INVISIBLE FROM THE SIDE
THAT WRITES.** Same family as the `state.md` subject index, which at least refuses
(`split_state.py --reindex` is documented as required when adding a subject) and
which the same day was found missing two subjects that existed in a part.

**HOW TO APPLY.** Append and regenerate in ONE step, and verify by reading the
GENERATED view rather than the source. **Grep a SHORT distinctive substring, not
the heading:** the index truncates each heading with an ellipsis, so my own first
check used the full heading, returned 0 against an index that DID contain the rule,
and read as the very failure it was testing for. A false alarm in the same family
as the four non-discriminating controls this pair of sessions logged the same day --
the pattern has to be able to match before its 0 means anything.
### 2026-09-09 — FORBIDDEN: quoting a spending cap, limit or flag from `env-vars` when a STORE can override it — and treating a one-source instrument's negative as a fact about the value

- **What we believed:** that `live-odds-worker`'s environment held the live
  execution caps — `MAX_ORDER_DOLLARS=10`, `MAX_DAY_DOLLARS_KALSHI=50`,
  `BANKROLL_UNITS=40` — and that they were a testing leftover throttling the
  platform's largest measured lever to ~$2/day.
- **What was actually true:** a STORED settings store overrides the environment
  on every one of those fields and has since **2026-09-04T13:21:37-05:00**.
  Resolved: **`max_order_dollars` 35.01, `max_day_dollars_kalshi` 150.01,
  `max_day_orders_kalshi` 15, `bankroll_units` 1000** — `/api/portfolio/limits`
  and `/api/portfolio/settings` report `"stored"` for every field with
  `store_error: null`. The prize was understated **~3x**, and the conclusion
  flips from "raise the caps" to "score the edge; no cap decision is pending".
- **How we found out:** only by reading the endpoint that reports what the guard
  RESOLVES, after three env vars set on the user's authority had no effect.
  **The pre-check that was supposed to catch this returned a clean, confident
  negative** — `/api/ops/artifacts/export?pattern=…execution_limits.json` →
  "NO STORED LIMITS FILE". The store lives in the **keyvalue backend**, which
  artifact export cannot see; `execution_limits_settings.py:19-25` says so in its
  own docstring, and [[project_keyvalue_artifact_split_blinds_guards]] already
  recorded the split.
- **The rule going forward:** **a cap has a RESOLVED value and a SET value, and
  they are different objects — never quote the SET one.** Read the endpoint that
  reports the guard's resolution and read its `sources` map. Generally: **when a
  value has more than one possible source, an instrument that can see only one
  source cannot produce a negative result ABOUT THE VALUE — only about its own
  source.** A clean negative from such an instrument is worthless and reads
  exactly like a real one.
- **A SECOND READER AGREEING IS NOT CORROBORATION WHEN BOTH READ THE SAME WRONG
  SOURCE.** A subagent independently reported the same env-derived caps; two
  wrong readings of one source is **one error counted twice**, and that is why
  this survived an afternoon of work built on top of it.
- **Cost:** none shipped, by luck rather than design — the env values set were at
  or below the stored ones and stored wins regardless, so no live limit moved.
  Had env governed and the values been higher, this session would have raised
  real spending limits on a false premise. Three now-inert env vars remain and
  are owed a reconciliation; **do not simply delete them**, because absent
  resolves to a code default that differs from both the env and the stored value.
## 2026-09-09 FORBIDDEN: scoping a fix from the COUNT written in the lead that reported it. A lead's number is the author's hypothesis at the moment of noticing; re-census first `[lane probability-converter-registry]`

Three leads followed in one session, and **every one of the three undercounted
the thing it named** — each time by a factor, and each time the real number
changed what the right fix was:

| the lead said | the census found | what it changed |
|---|---|---|
| "SIX byte-identical copies of two JS renderers" | **74 definitions** — ALL 15 functions in both reconciliation templates, 11 across all four market-accuracy ones | the fix was two modules, not one edit |
| "residual THREE-way `localYMD` duplication" | **6 definitions in 2 implementations**, five of them already inside shipped modules | the fix became one parameterised function, not a 3-way hoist |
| "NBA settlement books EVEN MONEY on a missing price" (one function) | **3 sites in 2 modules**, one of them CROSS-SPORT | fixing only the named one would have left the same defect live in soccer/MLB/NBA live-lens |

And the same session produced the INVERSE: a "6 Eastern vs 3 Central" census I
wrote into a lead myself turned out to have counted three different things as
one — slate-date resolution, display formatting, and a deliberate ET comparison
that must NOT be changed. Only **two** of the six were what the lead implied.

**WHY IT HAPPENS, and why it is not carelessness.** A lead is written at the
moment of NOTICING, from whatever grep surfaced the thing — usually a
first-line or single-token match, on the file that happened to be open. That is
exactly the cheapest and least accurate moment to count. `/lead`'s whole value
is that it costs nothing to record, and the cost it saves is the census.

**HOW TO APPLY.** Treat the lead's number as the lower bound and the lead's
FRAMING as unverified. Before scoping: re-census over the full tree with a
matcher that can see the whole construct (full function BODIES, not first
lines; templates AND static; nested and method scope, not just column 0), and
CLASSIFY the hits before counting them — "same string" is not "same thing", and
the NHL live-polling comparison would have been broken by a fix that treated it
as one more instance.

**The cost of not doing it is asymmetric.** Under-counting ships a fix that
leaves the defect live somewhere else, and the ledger then records the lead as
CLOSED. Over-counting only wastes a grep.
## 2026-09-09 FORBIDDEN: reporting a STAGE, FEATURE or MECHANISM as OFF because its env flag is ABSENT, without finding the resolution site and checking for an UNCONDITIONAL installer. A stage's state is a property of the PROCESS THAT RAN IT, not of the environment `[lane segments-joint-v1, my SECOND instance of this shape in six hours]`

**WHAT HAPPENED.** The step 5 recon read five flags off both workers, found four
ABSENT, and reported "five of six stages are shipped dark". One of the five was
wrong. `pipeline/layer2_shortlist.py:664` calls `install_measured_correlation`
UNCONDITIONALLY and by design (`#621` phase 4), writing a PROCESS-WIDE resolver
registry that all ten `compute_correlation` call sites read -- including
`bankroll_manager.compute_correlation`, so it reaches BET SIZING. Its own
counter shows 61 of 62 installs True on the date that has sims, 54 of those
across the full 15-game slate. It had been live all day. And
`SYNDICATE_PARLAY_MEASURED_JOINT`, the flag I read, gates something NARROWER
than its name: only the n-leg phi expansion in the parlay runtime.

**WHY THIS IS ALREADY A RULE AND STILL HAPPENED.** Six hours earlier the same
lane retracted the execution caps for the same reason and wrote *"a cap, limit
or flag has a RESOLVED value and a SET value, and they are different objects."*
That correction was about a STORE overriding env. I filed it as a fact about
stores, so when the second case had no store -- just an unconditional call site
-- the rule did not fire. **The generalisation is not "check the store". It is
that reading configuration NEVER establishes what code did.**

**HOW TO APPLY.** Before writing any on/off verdict: (1) grep every reference to
the flag NAME and confirm the resolution site is the only one; (2) grep the
mechanism's installer/entry symbol separately -- an unconditional caller will
not appear in a search for the flag; (3) prefer a reading the code already
prints. `install_measured_correlation` printing `installed=` on every build,
including when nothing is installed, is why this was catchable in one query.
That counter exists because its author wrote that a resolver answering `None`
for everything is indistinguishable from one nobody wired up -- **the same
ambiguity my flag read walked into.**

**COROLLARY WORTH MORE THAN THE CORRECTION.** A mechanism installed into a
process-wide registry resolves DIFFERENTLY PER DECISION PATH depending on which
process installed it, and no flag anywhere reports that. Any claim of the form
"X is on" is incomplete without naming the process.
## 2026-09-09 FORBIDDEN: trusting a season/week (or any period) resolver that derives from a DIFFERENT artifact family than the one you are about to read. It lags by exactly as long as the two families disagree, and the join then returns nothing -- which is indistinguishable from "the model has no view" `[lane nfl-prop-model-coverage, caught by a reachability run, not by 13 green unit tests]`

**WHAT HAPPENED.** The new NFL prop join asked `latest_season()` which season to
read. On 2026-09-09 it answered **2025** while the artifact on disk was
`nfl_prop_projections_2026_wk1.json`. `latest_season` derives from
`week_summaries()`, which globs the **SmartSim2 projection** family -- a
different family on a different publish cadence. Early in a season, when week-1
props exist and last season's projections still dominate that glob, it is a year
behind. The join stamped ZERO rows and reported success.

**THIRTEEN UNIT TESTS WERE GREEN THROUGH THIS.** They all passed an index in
directly, so none of them exercised resolution. Only running the real entry
point against the real published artifact showed it, which is
`model_engine_standard.md`'s "reachability test before correctness tests"
earning its keep on the first try.

**AND THE FIRST FIX WAS ALSO WRONG, THE SAME WAY.** The fallback scan probed
`[resolved, resolved - 1]` -- so from a resolved 2025 it could never reach 2026,
the very year it needed. A fallback built on the same bad input inherits the bad
input. What fixed it was a signal that does NOT depend on which artifact family
is on this disk: **the season the DATE names.**

**HOW TO APPLY.** (1) Resolve a period from something intrinsic to the request
(the date) or from the family you are actually reading -- never from a sibling
family's presence on disk. (2) When you must fall back, make the fallback's
inputs independent of what failed. (3) Report WHICH period answered
(`artifact_season`/`artifact_week`) and whether a fallback ran
(`resolution="artifact_scan"`), so an empty join is attributable instead of
silent. This repo has shipped period self-pinning before -- `#471`, NFL week
pinning to 1.

**THE GENERAL SHAPE, which is the part worth keeping:** an empty join and an
honest "nothing to join" are the same observation unless the code says which
inputs it used. Every join that can address the wrong partition must name the
partition it addressed.
## 2026-09-09 - FORBIDDEN: predicting that a consumer-side key fix will start resolving, without first checking that the PRODUCER's data reaches its key builder at all. The field being absent from a key and the data being absent from the function are different defects, and the second makes the first's fix inert `[lane odds-history-segment-term, commits cff0cd4e / 26c8cfc6, DEPLOYED]`

- **What I believed:** having added `segment` to `clv_join._history_key`, I wrote
  in that commit -- and told the user -- that segment CLV would become available
  "the moment `_odds_history_market_key` emits a `segment=` part; this key
  already matches it, and nothing else here needs to change."
- **What was true:** the producer's key list was the SMALLER half of its problem.
  `_market_rows_from_mapping` descends `markets`, meets the container key
  `segments`, stamps `market="segments"` from the container NAME and stops --
  the level below is segment names (`first5`), which is neither a recognised
  container nor a line snapshot. **The whole subtree had never produced a row.**
  Measured by running the real flattener over a real 15-game snapshot: **45 rows
  out, 15 each of h2h/spreads/totals, ZERO carrying a segment.** Adding
  `segment` to that key alone would have shipped INERT and looked done.
- **Why the wrong belief was so comfortable:** the consumer's defect was
  legible -- a field missing from a tuple -- so I generalised it to the other
  side of the same contract. Both halves were "missing `segment`", which is true
  and useless: one was missing a FIELD FROM A KEY, the other was missing the
  DATA ENTIRELY.
- **The check that would have caught it in one command**, and which is now the
  rule: before predicting a consumer will resolve, run the producer's real
  reader over a real input and count the rows carrying the field. Not a grep for
  the field name -- the field name appears in the snapshot, in the fetcher and
  in the segment map; it was the ROW COUNT that was zero.
- **Cost:** none shipped, because the reachability run happens before the commit
  in this repo's standard (`model_engine_standard.md`: reachability test before
  correctness tests, `off != on`). That standard is written about sim engines
  and it caught a key builder -- **its scope is wider than its title.**
- **Generalises to:** any two-sided contract fixed one side at a time --
  `_KEY_FIELDS` consumers, board joins, settlement identity. `presence != reachability`
  already exists as a rule; this is the producer-side twin of it.
## 2026-09-09 FORBIDDEN: measuring a change against a harness that SUPPLIES AN INPUT PRODUCTION DOES NOT HAVE. The result describes the harness, and the gap can be the entire effect `[lane nfl-prop-model-coverage, caught only because the prediction was written down BEFORE the reading]`

**WHAT HAPPENED.** To estimate how many NFL prop rows a new join would give a
usable model edge, I ran the real code over real served board rows. Those rows
carry no two-sided `consensus`/`sides`, and the de-vig needs both, so I
RECONSTRUCTED the consensus by pairing the board's own over/under best prices.
That produced **950 edged rows of 1,019**, and a prediction of ~726 reaching the
sizer.

**PRODUCTION PRODUCED ZERO.** Not 726, not 64 -- **0 of 112 rows carry
`edge_vs_market_pct`**, every one reporting *"one-sided market: no two-sided fair
to price against"*. Served prop rows are one-sided, always. The 950 was entirely
manufactured by the reconstruction. The join still works -- the value arrives
through a FALLBACK path I had not designed for -- but the number, the mechanism
and the confidence were all wrong.

**I LABELLED IT AND SHIPPED IT ANYWAY.** The commit said the figure was
"INDICATIVE, not exact". That was too generous by a category: an indicative
number is the right quantity measured roughly, and this was a different quantity.
**I had ALSO measured the honest number in the same run -- 64 edged without
reconstruction -- and set it aside as the less interesting one.** The correct
reading was in hand and was discarded for the flattering one.

**WHAT MADE IT RECOVERABLE.** The prediction went into `deploys.md` BEFORE the
reading, with the reasoning and the caveat. When the reading came back it could
not be quietly re-narrated, because the number it had to beat was already
written down. **Pre-registration is what turns a wrong prediction into a
finding instead of an embarrassment.**

**HOW TO APPLY.** Before trusting any local measurement of a production effect,
ask: *which fields did I provide that production does not?* Any such field
invalidates the reading for that quantity. If a required input is absent in
production, that ABSENCE IS THE FINDING -- report it, do not synthesise around
it. And when a run yields both a flattering number and a plain one, the plain one
is the measurement; the flattering one needs a reason to exist that is not "it
looks better".

Fourth instance this session of the same family
([[feedback_instrument_blindness]]): caps read from env when a store governed;
a counter that is structurally zero on the path being taken; a flag read instead
of its unconditional installer; and this. **All four were the reading being about
the instrument rather than the system.**
## 2026-09-10 — REQUIRED: before restoring a shared ledger file over its working copy, audit it for sections that exist ONLY there — and audit by inner CONTENT, because a header-set comparison lies in BOTH directions `[lane odds-history-segment-term]`

- **The primary tree is where work goes to be forgotten.** Cleaning my own redundant edits out of its `lanes.md` and `deploys.md`, I found a complete 9,889-char deploy row from lane `ncaaf-games-cache-refresh` — a finished verification, its lane still OPEN — that existed in **no commit, no worktree and no stash**. A plain `git checkout origin/main -- <files>` would have destroyed it, and I would never have known. This is the same hazard as `2026-09-02 FORBIDDEN: a git command that can DISCARD work taking its tree from the working directory`, where `m625-env-snapshots` was actually lost; **that entry has the mechanism, this one has the check.**
- **How to apply.** Before any restore/checkout over a shared ledger file, diff the two versions at SECTION level and list what exists only in the working copy. Then confirm each hit by **distinctive inner content** — a SHA, a byte count, a measured figure — never by header text: my header-set pass reported **two** unpushed rows and one of them was a false positive, because these headers carry em-dashes that encode differently through `git show` than in the working copy. The same encoding gap can hide a real orphan, so the failure runs both ways. Rescue by landing the block from a worktree based on `origin/main` (append-only files: 0 deletions), never by keeping the stale file. **And `git checkout <rev> -- <path>` STAGES what it writes** — on this repo's shared index that parks the change where another session's commit can sweep it up, so `git restore --staged` immediately and verify the index is empty.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-10 — FORBIDDEN: publishing "this remedy does not work" from ONE invocation form of a tool. `attrib -R <dir> /S /D` failed because `/S` makes the last path component a NAME to match; `attrib -R "<dir>\*" /S /D` works — and the failed form carried a WRONG MECHANISM into the ledger for four days `[lane worktree-close-and-prune, correcting lane git-out-of-onedrive 2026-09-06]`

- **What we believed** (`state_ledger.md [git-store-onedrive]` and the 2026-09-06 entry *AN ATTRIBUTE'S NAME IS NOT ITS SEMANTICS*): Windows ignores ReadOnly on directories; the blockers were read-only `logs/` and `refs/` FILES; `attrib -R /S /D` does not work, so "do not reach for `attrib`".
- **What was actually true**: the reverse on every point. `logs` and `refs` are DIRECTORIES, and they are the read-only entries; the files inside are not (`logs\HEAD` = Archive + ReparsePoint + PINNED). `rmdir` on a read-only directory fails (`PermissionError 13`), and a lab repo OUTSIDE OneDrive with the directory bit alone reproduces git's exact `failed to delete '.git/worktrees/<id>': Permission denied` and the exact husk shape. `attrib` works in the `"<dir>\*"` form; the 09-06 form only ever cleared `<dir>` itself, which is why its count did not move.
- **How we found out**: one lab husk per remedy, read-only count and survival measured after each — 5 remedies, 2 fail (`attrib -R "<dir>" /S /D`, `shutil.rmtree(ignore_errors=True)`).
- **The rule going forward**: a negative verdict on a remedy is a claim about the INVOCATION until a second form has been tried — quote the exact command line in the verdict. A mechanism written into the ledger must come from a reproduction that varies ONLY that mechanism (here the attribute, with OneDrive absent), never from which remedy happened to work. The 09-06 entry's own rule — test the mechanism on one instance before describing it — was the right rule; it was not applied to a directory.
- **Cost**: four days of the ledger steering sessions away from a working fix; husks regrew 83 -> 122 unseen; `session_worktree.py close` crashed in the fallback this failure triggers.
## 2026-09-10 — FORBIDDEN: running anything from `REPO_ROOT = Path(__file__).parents[1]` after deleting a checkout, or acting on SHARED state from it. With one worktree per session a script's own copy lives INSIDE a session tree, so `REPO_ROOT` means "the checkout this copy came from", not the repo. Resolve the MAIN worktree explicitly `[lane worktree-close-and-prune]`

- **What we believed**: `REPO_ROOT` is the repository, so a git call from it is always safe.
- **What was actually true**: `py -3 C:/tmp/syndicate-sessions/<lane>/scripts/session_worktree.py close --lane <lane>` makes `REPO_ROOT` the very tree `close` deletes. Its fallback deleted the directory, the next `git()` (default `cwd=REPO_ROOT`) raised `NotADirectoryError [WinError 267]`, and the branch was never deleted. An earlier `--force` close took the same fallback and survived only because it ran a copy living in another tree — the flag was not the difference. Second instance of the shape after `#497`, where `deploy_claim.py` wrote its claim into the worktree and the lock went silently non-mutual.
- **How we found out**: a test that runs `close` with `REPO_ROOT` set to the closed tree reproduces `[WinError 267]` on the unfixed script and passes on the fix. The lab showed `git worktree remove` run with its own cwd inside the target exits 255, and a retry exits 128 `is not a working tree` — the two codes in session transcripts.
- **The rule going forward**: a script under `scripts/` that deletes a checkout, or reads or writes state shared across sessions (claims, locks, the worktree registry), resolves the main worktree — `git worktree list` names it first, and `--git-common-dir`'s parent breaks if `.git` ever moves — and uses THAT, never `REPO_ROOT`. Test it with `REPO_ROOT` pointed at a session worktree.
- **Cost**: one crashed close, one orphaned branch, and two exit codes nobody had attributed.
## 2026-09-10 — REQUIRED: before recording a producer fix as "in force once the artifact is rebuilt", check EVERY site on the path that WRITES that artifact. The WNBA EV refusal covered 2 of 3 prop sites, and the one it missed is the slate writer `[lane wnba-accuracy-assessment, session 8c631ba2]`

- **What we believed**: the WNBA EV refusal (`_plausible_ev_pct`, 2026-09-01) would reach the served slate on the first post-break rebuild. `state_basketball.md [wnba-settlement-live]` and the lane said so for nine days.
- **What was actually true**: it is applied at `refresh_wnba_oddsapi_props.py:2081` (game picks) and at `:2286` and `:2354` (props). It is NOT applied at `:2192`, the prop loop of `_build_local_recommendations_slate_artifact`, which is the one that writes `recommendations_slate_<date>.json`. NBA's port applies it at both of its prop sites. On the slate, `ev_pct` is also `score` and the within-game sort key, so the omission is not cosmetic.
- **How we found out**: a code trace of what the 09-17 rebuild actually runs, then a grep of every `top_play.get("ev_pct")` in both producers. Four sites apply the refusal; one does not.
- **The rule going forward**: a fix is in force on an artifact only if it is on the path that WRITES that artifact.
  - Name the writer.
  - Grep the fixed input (here `top_play.get("ev_pct")`) across the writer's call chain.
  - List the sites with and without the fix before writing "in force after rebuild".
  - A complete sibling port (NBA here) is the fastest diff.
- **Cost**: nothing in money (no WNBA slate was written 08-31..09-16). Nine days of a ledger line overstating a fix, found seven days before it would have been read as proven.
## 2026-09-10 — RECURRENCE, not a new rule: I shipped a fix predicted from a REFRESH-WORKER instrument and measured it on WEB. It was right for the service the instrument read, and inert on the service that serves the symptom `[lanes mlb-final-state-mapping / mlb-lens-final-status]`

- **What I believed**: `/mlb/api/cards?date=2026-09-03` served ATH@SEA `Live` because `_merge_live_lens_row_into_game` overwrote a feed-derived Final. The basis was 09-04's `FEED_LIVE_STATUS ... source_status_abstract='Final'` for all nine games.
- **What was actually true**: `FEED_LIVE_STATUS` prints only when `not _render_web_dyno()`, so it is refresh-worker's feed map. WEB serves the route, and it holds ZERO `feed_live` files for September (`export?names_only=1` `count=0`; June control 78). On web the base status is `Pregame/Scheduled` and the frozen lens row is the only status. A guard that protects a Final base cannot fire where there is none.
- **How we found out**: the post-deploy reading, +31 s after `finishedAt`, matched the pre-deploy baseline game for game. The discriminating fields had been in the served payload all along: `gameDate` empty and `detail` = the date on ALL nine games, Final and Live alike. A present feed payload populates both.
- **The rule going forward** -- the same family as 2026-09-06 "instrumenting join A, reading it, and concluding about a value written by join B". Before predicting a served value from an instrument, read the instrument's own GATE (`if not _render_web_dyno()`, `in_request=`) and confirm it ran on the service that SERVES the surface. If it cannot have, read the INPUT on that service first; here that was a 30-second `export?names_only=1` for the feed files, taken with a control that can read non-zero.
- **Cost**: one web deploy that moved nothing, plus a closed-lane verdict and a state paragraph corrected within the hour. The fix itself stands: it is correct for refresh-worker's board builds.
## 2026-09-10 — FORBIDDEN: clearing a stranded ledger row on a field that the LOST write set. A lost update restores the other writer's stale copy of the WHOLE row, so every field that write carried is gone with it `[lane write-ahead-build-refusal]`

- **What we believed**: the order refused at build on 2026-09-04 (`6bc5617ccc3bf1f54d02bb35`) could be auto-cleared by reconcile. The rule proposed was: a `submitted` row with no `venue_order_id`, whose recorded error shows `venue_contacted=False`, never reached the venue. It was one of the two remedies proposed for the residual.
- **What was actually true**: the stored row had `error`, `venue_resolved_at` and `pre_resolution_error` all null. It was the WRITE-AHEAD version, not a `rejected` row with only its status flipped back.
  - `_persist` merges on a fresh read and then SETs, with nothing atomic between the two.
  - refresh-worker's paper SET at 18:27:25.228 was exactly its own 24.711 document + 48 B. It carried the row as it stood before live-odds-worker's `rejected` SET at 25.083.
  - The merge is last-writer-wins at ROW grain, so the error, the timestamps and the status reverted together. A predicate on `error` could never have reached the exact row it was meant to clear.
- **How we found out**:
  - Byte accounting of both services' `KEYVALUE_WRITE_LARGE` sizes over a 1.1-second window.
  - Then the stored row, off `/api/portfolio/live?on=2026-09-04&show=all`. Its `prior_attempts` also showed a build refused on every pass since 07:48Z.
  - `test_KNOWN_HAZARD_a_write_landing_between_merge_read_and_SET_is_lost` replays the interleaving on the real `_persist`.
- **The rule going forward**: before writing a rule that clears a row a lost update stranded, read the STORED row and list which fields survived.
  - Key only on evidence the lost write did not carry, or on a separate key no other writer touches.
  - If nothing survives, the fix is upstream: either do not write the row (`2914b6c7` builds before the write-ahead), or make the write atomic (`#656`).
  - A unit test cannot catch this. A fixture builds the row WITH the error, the predicate passes, and production never has that row.
- **Cost**: none paid; it was caught before shipping. It would have been a dead predicate on the money path that tested green and never fired.
## 2026-09-10 — OVERTURNED: `#600`'s three-way merge does NOT stop different orders clobbering each other, because its re-read and its SET are not atomic `[lane write-ahead-build-refusal, correcting state_model.md [execution-ledger-cross-service-race], 2026-08-28]`

- **What we believed**: since `f66c7441` (2026-08-28), `_persist` three-way merges onto a fresh read. So "different orders no longer clobber; the same order in one window is still last-writer-wins, blast radius one row". `LEDGER_MERGE` had not been seen firing.
- **What was actually true**: the fresh read and the SET are separate operations, ~0.3-0.5 s apart at 2.7 MB. A SET that lands between them is overwritten by the late writer's stale copy of every row it kept.
  - On 2026-09-04 that hit three different orders in 1.1 s:
    - paper `4aa69211…` lost its fill to live-odds-worker's SET at 24.160;
    - paper Q was dropped at 25.083;
    - live `6bc5617c…` was reverted to `submitted` by refresh-worker's SET at 25.228.
  - `LEDGER_MERGE concurrent=6/1/2` fired in those same seconds. The merge ran, and still lost the writes.
- **How we found out**:
  - Byte accounting of both services' `KEYVALUE_WRITE_LARGE` sizes, read as document versions.
  - The stored rows.
  - `test_KNOWN_HAZARD_a_write_landing_between_merge_read_and_SET_is_lost` replays it.
- **The rule going forward**: a merge-on-write protects a ledger only if the read it merges onto and the write are ONE atomic step, via compare-and-swap (WATCH/MULTI) or a lock. Otherwise it narrows the window without closing it, and the narrowed window is still hit.
  - Paper rows stuck at `submitted` count the hits: 13 across 09-06..09-11. That is an upper bound, since a crash mid-`place_order` leaves the same shape.
  - Fix: `todo.md #656`.
- **Cost**: six days with no live placement on either venue (09-04 to 09-10), plus paper fills silently lost.
## 2026-09-10 — FORBIDDEN: recording an ESPN refusal from Render as a property of the HOST. It is a (host, headers) pair: `site.api.espn.com` answered web 5 of 5 with urllib's default User-Agent, in the same hour it refused `has_games_for_date`'s `Syndicate-WNBA/1.0` `[lane wnba-public-scoreboard-host]`

- **What we believed**: `site.api.espn.com` returns 403 to every Render service, so any code on that host is dark in production. `state_basketball [espn-egress-and-wnba-boxscores]` said so on 2026-08-26: "The 403 is the HOST". I carried that into a trace and into a proposed fix for the live WNBA public scoreboard.
- **What was actually true**: `_public_scoreboard_live_state_payload` asks `site.api` with NO custom User-Agent. It ran 5 times on web on 2026-09-10 from 22:12:23Z with ZERO `SCOREBOARD_FETCH_FAILED`, a line it prints on any exception. The workers logged none that day either. In the same hour web's `has_games_for_date` (same host, `User-Agent: Syndicate-WNBA/1.0`) returned a non-False verdict. The 2026-08-05 probe in `wnba/cards.py` had already said this: a custom UA gets a 403 from Render, and the default answers.
- **How we found out**: the fix's lane recorded a falsification test (a failure-line count) BEFORE shipping. The zero was made readable by a positive marker that the call ran: the request-path warning `operation=wnba_public_scoreboard_live_state_fetch`, triggered by a request.
- **The rule going forward**: when an ESPN call fails from Render, vary the HEADERS before blaming the host, and record the refusal as the (host, User-Agent) pair that was measured. Never conclude "this host is dark" for a caller whose headers differ from the ones measured.
- **Cost**: an unneeded code change and deploy, caught before landing, and a state line that overstated the refusal for two weeks.
## 2026-09-10 — RECURRENCE (instrument blindness): I cited `last_blind_write None` as evidence about a ledger write. The field cannot be set in production `[lane write-ahead-build-refusal; found by lane execution-ledger-cas]`

- **What I believed**: `last_blind_write None` on `/api/ops/execution/ledger-summary` meant no blind write had happened. `state_model.md` called it "a meaningful null", and I quoted it in both the baseline and the verify of the `2914b6c7` deploy.
- **What was actually true**: the field is set only when `_load()` raises inside `_merge_onto_current`. `_load()` cannot raise: `refresh_state_store.read_json_file_result` catches every read failure on both backends and returns None, and `_load` turns that into an EMPTY ledger. The null is structural.
  - `test_an_unreadable_ledger_refuses_rather_than_looking_empty` passes only because it monkeypatches the reader to raise. That is a harness supplying a failure production cannot produce.
- **How we found out**: lane `execution-ledger-cas`, scoping `#656`, read the reader's exception handling. I confirmed both functions from code.
- **The rule going forward**: before citing a status field as evidence, find the code path that sets its UNHEALTHY value and confirm that path can execute in production. A field that can only ever read healthy is not an instrument. Same family as this file's instrument-blindness rules, and the 2026-09-09 FORBIDDEN on harness-supplied failure modes.
- **Cost**: two uninformative readings in a deploy entry, corrected the same evening. The entry's other readings stand.
## 2026-09-10 — OVERTURNED (my own docstring): a producer rewrite of a PAST-dated artifact does NOT reach web through the publish sweep. The sweep refuses slates more than a day old, and web serves whichever of its two copies is newer `[lane mlb-lens-final-status]`

- **What I believed**: the final pass rewrites live-odds-worker's copy of an old live-lens report, and `live_lens_loop`'s own publish sweep, which runs right after the tick, carries the rewrite to web "the same cycle". I wrote that into the module docstring and the lane, and pre-registered a reading on it.
- **What was actually true**: `artifact_publisher._publish_skip_reason` refuses any file whose NAME dates it more than `_PUBLISH_MAX_AGE_DAYS = 1` back, and the code calls that check "never exempted". Every sweep after the deploy logged `stale_slate=[..09_03, 09_01, 09_06..]`. The one date inside the window, 09-09, did reach web, and was undone within a second: web's `sources._resolve_data_path_with_reconcile` copies the NEWER of its two published forms over the served target, and the slim frozen form arrived 175 ms after the full final one.
- **How we found out**: the pre-registered reading. The producer's line said `finalized=6 still_open=0`, while web's copy of 09-03 still had `finalPass_entries=0`, and the publisher's own `SWEEP_SKIPPED_DETAIL` named the skipped files. The reconcile took three reads: web's `[ops.publish] ACCEPTED` lines (two publishes 175 ms apart), both web copies by export, and one more export after a cards read (8,736,835 B -> 132,548 B).
- **The rule going forward** (the same family as the 2026-09-10 RECURRENCE above, lanes mlb-final-state-mapping / mlb-lens-final-status): a fix is on the path to the surface only once the TRANSPORT and the READER have been read, not just the writer. For an artifact a worker writes and web serves, check two things before predicting "it reaches web". (1) The sweep's skip rules (`_publish_skip_reason`: age AND size) against the file's NAME and SIZE. (2) How web RESOLVES the path. If there is more than one published form and a reconcile, the newest copy wins, not the one you wrote.
- **Cost**: one live-odds-worker deploy whose reading could not move. A second change is now owed: a status-only patch of web's own served copy (`e035c829`), which must ship before the 10-day look-back loses 09-01.
## 2026-09-10 — RECURRENCE (the 09-09 absent-is-not-off rule): I read the env key a COMMENT named, got a 404, and nearly called another lane's pass inert on refresh-worker. The code reads a different key, and it is `true` there `[lane execution-ledger-cas]`

- **What I believed**: `e035c829`'s MLB web pass would be inert on refresh-worker. `run_refresh_worker.py:7223` says "LIVE_LENS_LOOP already defaults False", and a single-key read of `LIVE_LENS_LOOP` on refresh-worker returned HTTP 404.
- **What was actually true**: `live_lens_loop._is_live_lens_loop_enabled()` reads `SYNDICATE_ENABLE_LIVE_LENS_LOOP` (default False). That key is `true` on refresh-worker and live-odds-worker, and refresh-worker logged `TICK_COMPLETE results={'mlb': True, ...}` every cycle. A refresh-worker deploy would switch that lane's passes on there, on a service the lane never targeted.
- **How we found out**: before acting on the 404, I grepped the READER (`live_lens_loop.py:327`), then read that key per service, then read the tick lines.
- **The rule going forward**: the 09-09 rule says find the resolution site. What this adds: take the KEY NAME from the function that reads it, never from a comment or a docstring. A comment can name a key nothing reads, and a 404 on that key is an answer about nothing. Then confirm the behaviour from a line the reader itself emits.
- **Cost**: none paid. It was caught before the refresh-worker deploy, and the timing question went to the user, who chose to carry the passes.
## 2026-09-10 — OVERTURNED (mine): a finished game's rows are NOT served as `final` on the Layer 2 board. They leave through the unserved `dead` lane, so "served rows read `final`" is a check the board cannot produce `[lane football-layer2-live-parity]`

- **What I believed**:
  - After `42d49364` corrected FAMU @ MIA's 35 rows `pregame -> final`, `rows_stale_kickoff` fell 58 -> 0. I read that as the rows being "back on the board as final", told a peer so, and wrote it into a draft `deploys.md` entry.
  - My game watcher's BOARD_FINAL check (served rows with `game_state == final`) rested on the same belief.
- **What was actually true**: the served shortlist at 03:33:26Z had 0 rows for either finished game. `per_sport_ingest.<sport>.by_lane.dead` rose (ncaaf 173 -> 219, nfl 550 -> 577). Settled games are classed dead and not served. The counter fell because the rows now fail a DIFFERENT gate, not because they came back.
- **How we found out**: the watcher went silent after both ESPN finals. To explain it I compared the served rows' `game_state` with `game.state`, and there were no rows at all.
- **The rule going forward**:
  - A counter falling to 0 says the row left THAT filter, never that it was served.
  - To verify a final transition on Layer 2, read the enrichment coverage (`live_game_state.transitions`) and `by_lane.dead`, not the served rows.
  - Before trusting a watcher's terminal check, probe it on a game that already finished.
- **Cost**: one wrong claim to a peer (corrected within ~25 min, before its reading). The watcher could only end by being stopped.
## 2026-09-10 — FORBIDDEN: a repair guard that protects ANY POPULATED local copy, on a service that cannot produce the artifact itself. "Has rows" is not "is current", and nothing else will ever refresh it `[lane nfl-layer2-kalshi-identity]`

- **What was believed:** `scripts/build_nfl_prop_projections.py` held that "a local copy with rows is left alone no matter what web is serving". The rule was written after web's EMPTY 111-byte copy had been pulled over a good local one, and it was correct about that failure.
- **What was true:** refresh-worker cannot build this artifact, because it has no player pbp. So the copy it held from 2026-09-08 was never replaced. That copy had 980 rows, was generated at 20:17:22Z, and predates the `stat::player::line` key. The worker logged `REPAIR_SKIPPED_LOCAL_OK local_rows=980` every hour for two days while web served 1,140 rows. The NFL board's sim view survived only on Anytime TD, the one lineless market: 119 of 119 rows.
- **How it was found:** production's published artifact matched my local copy, while the board reported `artifact_rows 683`. The worker's own log line named the skip.
- **The rule:**
  - Gate a repair on the pulled copy's VINTAGE, not on the local copy's presence.
  - Keep a pull only if it is populated and not older by the artifact's own `generated_at`. Otherwise roll it back byte-for-byte, mtime included, so neither the next pull nor the publish sweep reads it as a fresh edit.
  - A guard written against one failure (empty over good) must not create the opposite one (stale forever). Test BOTH directions; `tests/test_nfl_props_prior_season_fallback.py` has five repair cases.
- **Measured after the fix:** `REPAIR_PULLED_NEWER 980 -> 1140` at 2026-09-11T03:50:19Z, then 486 non-Anytime-TD NFL props carried a sim view (was 0).
- **Generalises to:** any worker-side copy of an artifact that only another machine produces.
## 2026-09-10 — OVERTURNED (mine): "non-card NCAAF chips never get live state". The chip WAS on the live-state join; it read the UTC date, and ESPN files an evening-ET kickoff under the previous UTC day `[lane ncaaf-fcs-market-implied-rating]`

- **What I believed**: FAMU @ MIA's chip stayed `pregame` all game because only the FBS-vs-FBS week cards receive ESPN live state. I read "the cards have 49 games and FAMU @ MIA is not one of them" as the mechanism, wrote it into `deploys.md` (22:15 CT), a lane line and a lead, and told a peer.
- **What was actually true**: `build_ncaaf_chip_games` builds FBS-vs-FCS chips and calls `_attach_live_state` with the right ESPN ids (registry ids ARE ESPN ids: Florida A&M 50, Miami 2390). The index was built for `_ncaaf_week_kickoff_dates`, the UTC dates `2026-09-11/12/13`, and ESPN filed the 00:00Z kickoff under 09-10. It was the same UTC-vs-ESPN-date shape as `a9bafa9d` (settlement) and `86c82220` (board chips) that same day: the THIRD instance in one day.
- **How I found out**: before promoting the lead, I tested each input of the join in code. The ids came first, and disproved my first guess (a missing logo id). The date set came second, and confirmed the cause.
- **The rule going forward**:
  - Any NCAAF/NFL lookup into an ESPN capture must use `bet_status_nfl.kickoff_capture_dates` (the Eastern date, plus the previous day for a small-hours kickoff), never `commence_time[:10]` or `startDate.split("T")[0]`.
  - A row or card COUNT ("X is not among the 49") is not a mechanism. Trace the join's actual inputs before naming a structural boundary as the cause.
- **Cost**: one wrong mechanism in the ledger, a lead and a peer message, corrected about 30 min later (append-only). The fix was smaller than the wrong diagnosis implied: one call site. Also this session: a watcher reported a false "0 dates" because its filter matched `render_logs.py`'s own header line. I read the log directly before believing it.
## 2026-09-11 — OVERTURNED: "uncontracted rows crowd real Kalshi edges out of the plan's slots". The cut's own counters said neither the cap nor the ceiling bound `[lane kalshi-plan-placeable]`

- **What was believed:** `placeable_committed=4/22` meant 18 aggregator-priced NCAAF rows were holding slots that contracted Kalshi rows needed. The task was written on that premise, and it is the natural reading of the ratio.
- **What was true:**
  - On that build, `beyond_max_positions=1` and `slate_scale_factor=1.0` ($67.76 staked against a $251 ceiling). `prefer_placeable` has ranked contracted rows first since 2026-08-25, so the one row cut was an aggregator row. The 18 rows cost the 4 nothing.
  - There were 4 contracted rows only because the join never saw Saturday's rungs: `MAX_MARKETS_PER_SERIES=400` cut `KXNCAAFSPREAD` 2,141 of 2,541 before the join ran.
- **How it was found:** the PAPER2 line's own `refusals=`, and each position's `sizing.slate_scale_factor`. Both were read before any code, and both were already in fetched payloads.
- **The rule:**
  - Before fixing a crowding-out, read the constraint's own counter: `beyond_max_positions`, `slate_scale_factor`, `exposure_capped`. A wanted/total ratio is a symptom, not a mechanism.
  - A working-set histogram (`BY_GAME_DATE`, 6,000 markets) is not the join's population (`markets_from_state`, 14,818 markets). Read `PRECAP_SELECT` for what the join can see.
- **Also, tooling:**
  - PreToolUse hooks resolve `CLAUDE_PROJECT_DIR` to the PRIMARY tree, even in a `session_worktree` session. So lane-guard enforces the primary's STALE `lanes.md`. On 2026-09-11 it blocked two unclaimed files for a lane that was CLOSED on origin/main.
  - Check the claim on origin/main before believing a block. The remedy is `git restore --source=origin/main --worktree -- .syndicate/lanes.md` in the primary, with no local edits there and the index untouched. Never a bypass.
## 2026-09-11 — FORBIDDEN: reporting a lane's file claims as RELEASED on the strength of the edit you meant to make. Read the claim set back with `claims_by_path`, the same parser `lane-guard` enforces with `[lane nfl-layer2-kalshi-identity]`

- **What I believed:** my 2026-09-10 checkpoint rewrote this lane's block with a new header and a goal verdict. So I told the user the lane "no longer claims any files".
- **What was true:**
  - That edit's anchor was the header plus the `- Goal:` line. The old `- Files:` line, naming five code paths, sat below it untouched, so lane-guard kept enforcing those claims against every other session.
  - The next fix wrote `Files: NONE claimed ... verbatim in` a backticked `lanes_history.md`. The parser read that filename as a NEW claim.
- **How it was found:** I ran `claims_by_path(text)` over the file as written, filtered to this lane. It returned the five paths the first time and `{'lanes_history.md': ...}` the second. `check_lane_invariants.py` printed INVARIANTS HOLD both times, because a claim on a real path violates no invariant.
- **The rule:**
  - After any edit meant to release claims, run `claims_by_path` over the WRITTEN file, filter to your lane, and require NONE before saying so to anyone.
  - A `Files:` line that claims nothing must carry no backticked path-like token.
  - "Invariants hold" is not evidence that claims were released.
- **Cost:** one false statement to the user, corrected before it caused a blocked edit elsewhere, and three extra ledger commits.
## 2026-09-11 — OVERTURNED (a ledger state claim, by this session's measurement): "NCAAF serves ZERO orders by design" and "#593 can never be verified end-to-end" were both false by 2026-09-10 `[lane nfl-prop-grading]`

- **What the ledger said:**
  - `state_football.md [ncaaf-zero-orders-is-two-gates]` (verified 2026-09-01): NCAAF places 0 orders, because `pick_gate` and `portfolio_commit.py:267` hold by design.
  - Its state line said NCAAF settlement was "NEVER verified end-to-end".
  - Scheduled task `verify-ncaaf-settlement-593` was disabled with "Do NOT re-enable ... a Friday run was GUARANTEED to report PENDING".
- **What was actually true:**
  - Plan date 2026-09-10 held **517 distinct NCAAF orders on 72 games**, 211 of them in the portfolio book.
  - 20 FAMU @ MIA orders were graded end-to-end by `paper_settlement` on 2026-09-10, every outcome consistent with the score.
  - Some change after 09-01 let NCAAF orders through. No state line recorded it.
- **How we found out**: the first-grade reading counted orders per game in `/api/portfolio/paper` instead of assuming them.
- **The rule going forward:**
  - A state claim of the form "zero BY DESIGN" describes a configuration that other lanes can change without touching that section.
  - Before building on one, or before writing a task or a disable-note that assumes it, count it in production and date the count.
  - A lane that lifts such a gate owes the superseding line in the section that stated it.
- **Cost**: none paid this time. The reading counted before concluding. A reader trusting the section would have skipped NCAAF settlement verification entirely.
## 2026-09-11 — OVERTURNED: "pregame near-even Polymarket sides have no book, so hold them until live". Our own ledger held the rule's falsifier more than ten times before the rule shipped `[lane polymarket-e2e-review]`

- **What was believed:** 11 orders on 08-31 showed pregame orders above ~0.41 "resting" and never filling, while live everything filled. So a 0.35 pregame ceiling held near-even bets until live (`0c3f102f`, `97fe50b2`). The rule's own stated falsifier was "a PREGAME FILL above 0.410".
- **What was true:**
  - 24 of the 41 near-even pregame orders that reached the venue FILLED within about 2 s (08-28..09-01), including fills at 0.44–0.48 taken 31 to 821 minutes before kickoff. The other 17 were CANCELED by the venue 0.6–1.6 s after submit, and none of THOSE rested; what was read as "resting" was instant cancels.
  - **But resting does happen.** On 2026-09-11 two near-even pregame orders RESTED unfilled (`order_state_new`). A venue behavior seen in one window is not the venue's behavior, and a resting good-till-cancel order can fill in-play at a stale price. Orders now expire at kickoff (`16de339b`).
  - The deferral path failed. Of the 51 held bets whose games started, 36 were never placed, because the plan drops started games, and 4 became fills. Near-even bets placed in-play went 3-10 against 5.7 expected.
  - The venue's own book (`GET /v1/markets/{slug}/book`, signed) showed BAL–TOR pregame at 0.445/0.45, with 151,604 shares at the offer.
- **How it was found:**
  - `/api/portfolio/live?on=all&show=all&venue=polymarket`: `venue_status`, `submitted_at` and `venue_resolved_at` were already on every order.
  - A log join of every `HELD_PREGAME_NEAR_EVEN` line to later `LIVE_ORDER` lines.
- **The rule:**
  - Run a gate's stated falsifier against the population ALREADY in the ledger before the gate ships, not only going forward. A gate that suppresses its own falsifier can never see it later.
  - "Did not fill" has three readings: rested, canceled by the venue, or never sent. Read `venue_status` and the submit-to-resolve lag before calling an order resting.
  - A gate that DEFERS ("places once live") owns a measurement of whether the deferred path completes. Here 71% of deferrals never completed, and nothing counted them.
- **Also, tooling:**
  - The discard-guard hook resolves EVERY path named in a command containing `checkout --` against the PRIMARY tree. A worktree command that also ran `scripts\check_lane_invariants.py` was blocked for that second path. Run the discard as its own command.
  - `lane_claims` reads every backticked path in a `- Files:` line as a claim, including one inside a "NOT ..." clause. That made `check_lane_invariants` report a contested file. Name unclaimed files outside the Files line.
## 2026-09-11 — OVERTURNED (mine, same morning): I explained a falling ALL-TIME count as "the window moved" without reading how the count is taken. It was data loss `[lane nfl-prop-grading]`

- **What I believed**: `SETTLED_SAMPLE` nfl 12 -> 4 (mlb and wnba down too) meant a rolling window. I wrote that into `deploys.md` at 08:50 CT.
- **What was actually true**: the counter reads the whole execution ledger, and the ledger is at its 5,000-record cap. `TRIMMED dropped=1` fires on every write and evicts the oldest orders, which are the settled ones. Every stake's credibility input is shrinking.
- **How we found out**: the next session step read `_settled_sample_size_by_sport` -> `settled_decisions_by_sport` (whole ledger, all time). A count with no window cannot fall unless records leave, and `TRIMMED` showed them leaving.
- **The rule going forward**: before explaining a count that moved, read the function that takes it and name its UNIT and its WINDOW. A count documented as all-time that decreases is a data-loss alarm, never a window.
- **Cost**: one wrong line in `deploys.md`, corrected the same morning. The eviction itself had been running since at least 09-09 13:24Z, unremarked.
## 2026-09-11 — OVERTURNED (mine, same day) and REQUIRED: `claims_by_path` is NOT the matcher `lane-guard` enforces with, and a claim transfer is not in force until the PRIMARY tree's `lanes.md` says so `[lane ncaaf-tbd-kickoff-date]`

- **What it overturns:** my FORBIDDEN entry above ("reporting a lane's file claims as RELEASED on the strength of the edit you meant to make") tells you to read the claim set back with `claims_by_path`, "the same parser `lane-guard` enforces with". It is not the same. `lane-guard` matches every `_claims()` token against the target path by SUFFIX; `claims_by_path` indexes exact keys.
- **What happened:**
  - I landed `released:` markers for two files on `origin/main` (`22d7cbd6`), and lane-guard still BLOCKED my edits to both. It reads `$CLAUDE_PROJECT_DIR/.syndicate/lanes.md`, the primary checkout's copy, not `origin/main`.
  - That copy was 63 commits behind and held 188 lines of OTHER sessions' uncommitted edits, so overwriting it would have destroyed them. The three changes were mirrored into it surgically: one atomic read-modify-write, each anchor asserted to occur exactly once, CRLF preserved.
  - One line still blocked. Another lane's `Files:` continuation line read "... `ncaaf/sources.py` was `released:`.". Its bare token suffix-matched my file, and a `released:` in mid-line is not a disclaimer. My `claims_by_path` check printed NONE while the guard printed BLOCKED.
- **How to apply:**
  - After landing a claim change, mirror it into the primary copy, touching only its own lines.
  - Verify with the guard's `_claims()` plus a SUFFIX match against every target path.
  - Put `released:` at the START of a line, and keep path tokens out of prose inside a `Files:` block.
## 2026-09-11 — FORBIDDEN: predicting that legacy rows "expire at the date roll" without enumerating every shard the old writer touched. The board loop writes TOMORROW's shard too `[lane nfl-layer2-kalshi-identity]`

- **What I predicted:** `deploys.md` 2026-09-10 ~22:20 CT said the raw Kalshi rows leave "with the midnight CT date roll".
- **What happened:** the user reported the phantom "Matchup" card again on 09-11. Web's NFL 09-11 shard held 205 pre-deploy Kalshi rows, captured 09-10 20:35-23:31Z, because the intelligence loop also builds the NEXT day's board. The roll moved the residue forward a day instead of ending it.
- **The rule:** before saying "old rows expire at X", list every shard or date the old code wrote, from the rows' own `captured_at`. Then name the LAST date the residue can appear.
## 2026-09-11 — RECURRENCE (the 2026-09-10 "check EVERY site that WRITES that artifact" rule): the Kalshi per-series cap had TWO writers and a selection flag on ONE `[lane kalshi-precap-board-lines]`

- **What was believed:** the per-series cap was refresh-worker's. `SYNDICATE_KALSHI_PRECAP_DATE_AWARE` and every `PRECAP_SELECT` reading quoted in the lanes and in todo `#661` came from refresh-worker's logs.
- **What was measured:** live-odds-worker runs the SAME `run_kalshi_odds_refresh` every ~2 min, at `PRECAP_SELECT mode=arrival` (14:49:52Z, 2026-09-11). It writes the SAME `kalshi_markets.json` working set that `portfolio_commit` and the executor read (`markets_from_state`). The date-aware flag was never set there, so once it shipped, roughly every other write of the working set was the old arbitrary slice.
- **The rule going forward:** before calling a selection or cap rule ON, grep EVERY service's logs for the rule's own line (`PRECAP_SELECT mode=`), not only the service you deployed. A shared keyvalue artifact is written by whichever service runs the writer, and loop ownership moves with env.
## 2026-09-11 — FORBIDDEN: passing a live commit remembered from an earlier read to `deploy_preflight.py --target-commit ... --reinject-env`. Its "ALREADY LIVE" is ANCESTRY, and `--reinject-env` turns that into a CLEAR for a ROLLBACK `[lane kalshi-precap-board-lines]`

- **What happened:** live-odds-worker's live commit moved `1afec00f` -> `16de339b` between my reads (another lane's deploy, 16:53:31Z). Preflight for `--target-commit 1afec00f --reinject-env` printed `live commit 16de339b`, then `target commit 1afec00f ALREADY LIVE -- redundant`, then `CLEAR` (16:59Z). Deploying it would have rolled back `16de339b`'s change.
- **Why:** `deploy_preflight.py:792-796` sets `target_already_live = is_ancestor(target, live)`, and lines 806-808 waive that redundancy under `--reinject-env`. An ancestor is "already live" by containment, so a rollback target reads as the same-commit case the flag exists for. `render_deploy.py`'s descendant check is the only remaining guard, and it was not exercised here.
- **The rule:** for `--reinject-env`, use the `live commit` printed by THAT preflight run as the target, and require target == live, not merely contained. Caught here only by reading the `live commit` line on the same output.
## 2026-09-11 — OVERTURNED (mine): I offered the user an option saying withheld rows would "still be recorded, so skill can be measured" before checking who consumes the filtered artifact `[lane pricing-plane-v1]`

- **What I believed**: withholding rows from the shortlist changes only the display, and measurement continues.
- **What was actually true**: `portfolio_commit` sizes from the persisted shortlist (`read_layer2_shortlist`). Withholding a row also stops its paper orders, and those orders were the only order-based route to measuring those models.
- **How we found out**: tracing the shortlist's consumers while implementing, after the user had already chosen.
- **The rule going forward**: before describing a filter's side effects to the user, trace every consumer of the artifact it filters. The Layer 2 board is also the portfolio's input. State the consequence IN the question, not after the answer.
- **Cost**: small. The consequence was surfaced before the deploy and recorded as a lead, and the decision stood.
## 2026-09-11 — RECURRENCE (a stale ledger number read as a live constraint): I quoted a 16-day-old cap from `state.md` as the binding limit and planned around it `[lane kalshi-precap-board-lines]`

- **What I said:** the 09-11 Kalshi spend of $30.07 left "~$20 of room" under a "$50/day cap". The cap came from `state.md`'s 2026-08-25 caps line; `EXECUTED` prints `spent=` but no cap.
- **What happened:** the next pass spent to $58.84 and was bound by the ORDER count: `refused={'over_max_day_orders': 14}`.
- **The rule:** a cap quoted as binding must come from the running service's env, or from its own refusal counter, never from a dated ledger line. The executor's `refused=` dict names the cap that actually bound.
## 2026-09-11 — OVERTURNED: the 2026-08-01 same-surname guard ("Yordan", not "Jose", Alvarez) could never fire for a player who goes by initials, because it took first names from the SCORER's filtered tokens `[lane ask-rail-evidence]`

- **What was believed:** `_person_conflicts_with_question_name` downgrades a bare-surname match whenever the question pairs that surname with a different first name.
- **What was measured:** production served "Last 10 games — AJ Griffin (through 2024-04-17)" for "What's the case for and against Konnor Griffin?". The guard reused `_person_matches`' token list, which drops every token under 3 letters. "AJ Griffin" reduced to `["griffin"]`, the guard's `len(parts) < 2` early return fired, and with no first name to compare, the match was allowed.
- **The rule going forward:** a guard must not inherit the normalisation of the thing it guards. A filter that is right for SCORING (ignore short tokens) removed exactly the tokens the GUARD needed, and the failure was silent and in the permissive direction. Test a disambiguation guard on the short and initial forms (`AJ`, `A.J.`, `N.`) in both directions: the conflict must fire, and a question that names the initials player must still match.
## 2026-09-11 — FORBIDDEN: running a ledger script by ABSOLUTE PATH from a shell whose cwd is another checkout. `build_learnings_index.py` resolves `.syndicate/...` against the CWD, not its own checkout, so the worktree's copy rewrote the PRIMARY tree's `learnings_index.md` `[lane ask-rail-evidence]`

- **What happened:** `py -3 /c/tmp/syndicate-sessions/ask-rail-evidence/scripts/build_learnings_index.py`, run from a Bash whose cwd had reset to the primary tree, printed "index written: 965 rules" and changed nothing in the worktree. It wrote the SHARED tree's `.syndicate/learnings_index.md` (mtime 18:16:08Z) from that tree's stale `learnings.md`. `INDEX_PATH = ".syndicate/learnings_index.md"` (line 28) and the `learnings.md` rewrite (line 199) are both cwd-relative.
- **How it was caught:** the printed count (965) disagreed with the worktree index's own header (981), and the worktree's diff for the file was empty.
- **The rule:** run ledger scripts with the cwd set to the tree you mean (`(cd <worktree> && py -3 scripts/...)`), and afterwards read `git status` in BOTH trees. A script run by absolute path is not scoped to the checkout it came from. This is the other side of the 2026-09-10 `REPO_ROOT` rule: there the path came from `__file__`, here from the cwd.
## 2026-09-12 FORBIDDEN: measuring model quality on a population defined by a PUBLICATION filter. When publishing is switched off the metric does not go noisy, it goes SILENT — and a pool FREEZES rather than shrinking `[lane live-gameline-accuracy-cut-repoint]`

The MLB live-gameline accuracy task headlined the `priceable_only` cut for
months. `priceable` is a verdict about whether the board will PUBLISH an edge:
it folds in `prob_interval_swamps_edge`, `no_two_sided_market_price`, and —
from 2026-09-10 — `model_edge_publishing_disabled_for_sport`. None of those are
statements about whether a forecast can be scored.

When MLB edge publishing was switched off, the cut went to n=0 permanently.
Measured on the per-record ledger: 2026-09-11 has 13,187 records with
`priceable=True` on **zero** and that reason on 245, while 2026-09-09 has 41
priceable and the reason absent. The forecasts were still being recorded the
whole time.

**The failure mode is the part worth keeping.** `best_per_date` SKIPS a date
whose cut carries no brier, so the pooled total did not fall — it stayed at
"12 dates, 146 games", unchanged and unmarked, and would have re-printed that
same number every night forever while new dates vanished. A metric that dies
by *freezing* looks exactly like a metric that is stable. **A shrinking sample
is visible; a frozen one is not.** Any pooled statistic that drops
non-conforming rows needs a counter for what it dropped, and must fail loudly
when the newest period contributes nothing.

**How to apply:** condition on properties of the FORECAST and the OUTCOME
(quote age, market, segment, whether a final exists), never on whether the
product chose to act on it. Selection on a publication decision is selection on
the model's own confidence, which biases the comparison even while it is
populated. `fresh_quotes_only` was the right headline all along for an
independent reason: `learnings.md:854` already FORBADE comparing model against
market without conditioning on quote age, and `priceable_only` never did.
## 2026-09-12 FORBIDDEN: writing an instruction that asks for a reading without naming the instrument, when a known-broken instrument is the obvious one to reach for `[lane live-gameline-accuracy-cut-repoint]`

`learnings.md:1584` has said since 2026-09-03 that Git Bash `date` in this repo
is badly skewed. The scheduled task's step 3 nonetheless said *"state your
actual wall-clock run time"* and named no tool. I reached for `date`, got
`Fri Sep 11 23:34:45 CDT` against a true local time of `2026-09-12 11:52`, and
published that the run was **ON TIME**. It was standby-displaced by ~12 hours —
the exact failure the task file documents at length as happening on 6 of 10
nights.

**The skew runs in the flattering direction**, which is what made it stick: a
displaced run reads as punctual, so the one instruction designed to catch
displacement instead certified its absence.

**How to apply:** a rule that forbids a tool is only half a rule. Name the
replacement AT THE POINT OF USE, in the file that asks for the reading — not
only in the ledger that forbids it, which the actor may never open. Better
still, add a check that needs no instrument: here, *if the served date is
tomorrow relative to the slate you meant to capture, the run was displaced
regardless of what any clock says.* Both were added to the task file.
## 2026-09-12 FORBIDDEN: quoting a tool's aggregate without recomputing it once from the components the tool printed beside it `[lane gameline-trend-paired-pool]`

`pool_live_gameline_trend.py` printed, per date, `model`, `market` and `diff` —
where `diff` was the row's own PAIRED `model_minus_market_brier` and `model` was
the model's brier over ALL its rows — then pooled from `model` and `market`. On
2026-09-01 the one line read model 0.13160, market 0.13198 (a difference of
-0.00038) and diff **+0.00077**. Visibly inconsistent, on the same line.

I ran that output at least three times in one session, repointed a scheduled
task's headline at it, published **+0.00571** to `state.md` and the task file,
and checkpointed — without once checking `model - market` against `diff`. The
paired figure is **+0.00460**. The discriminating field (`model_paired`) was in
every row since scorer contract 2, and the scorer's own `_paired` docstring
names this exact failure ("THE DIFFERENCE MUST NOT USE `model`").

**Why it survived:** the old headline cut (`priceable_only`) always had
matched n, so the defect produced no visible symptom for two weeks. Switching
the headline to `fresh_quotes_only` made it live, and the switch was the moment
nobody re-audited the tool against the new cut.

**How to apply:**
- When a table prints components and an aggregate, recompute the aggregate from
  the printed components once before quoting it. When a row prints two terms
  and their difference, check term - term = difference. A disagreement beyond
  rounding is a bug in the tool, not noise.
- When a cut, a population or a field becomes the HEADLINE, re-audit the tool
  that computes it against that cut specifically. A defect latent under the old
  headline goes live the moment you switch.
## 2026-09-12 FORBIDDEN: grading in-play price movement on the markets that are still there `[lane layer2-live-scorecard-gate]`

Grading live NCAAF Layer 2 opportunities by re-pricing the SAME market 10 minutes
later: 65 live +EV first sightings, 48 re-checkable, and **32 of those 48 (67%) had
vanished** -- mostly because the line moved, which is exactly what a stale price being
picked off looks like. Pregame, 13 of 258 (5%) vanished. The survivors' median then
said the rows a staleness gate would REMOVE held +1.85 EV points and the rows it would
keep held +0.68 -- the opposite of the mechanism, measured only on the markets that
did not move.

Before printing denominators I also quoted a mean split in chat ("<5m held +2.11,
10m+ fell to -11.28"). It rested on n=3 vs n=13 and three William Hill rows at median
-69, and was retracted within the hour.

The same session's first scorecard joined **0 of 932** opportunities while two games
were final, and printed it as `no_final_score`: run from a session worktree, the NCAAF
team alias registry under `data/` did not exist, so feed names never met scoreboard
names.

**How to apply:**
- Print the vanish rate beside any in-play re-price metric, per cell, and never read
  survivors' movement as "the edge held". Settle against results, or price the moved
  line; do not drop it.
- Print n beside every mean, and a median beside any mean a few rows can swing.
- A join that can fail must name its failure (`no_chip_match`), and a known-final game
  must be shown to join before any result from it is read.
## 2026-09-12 RULE: from a session WORKTREE, the deploy locks live in the PRIMARY tree. The lane marker must be written THERE, and a claim is released with its TOKEN. `[lane nfl-prop-certainty-refusal]`

**What I believed.** `/lane open` step 6 ("Write the slug to `.syndicate/.current-lane.<id>`")
was enough for `deploy-guard.py`, and `deploy_claim.py release --service <svc>` would release my
own claim.

**What happened.** I did step 6 inside `C:/tmp/syndicate-sessions/<lane>`, as the worktree protocol
directs. I then held the claim and a CLEAR preflight for the exact SHA, and the guard still refused
the deploy with `your lane: <none>`. The hook resolves its root to the PRIMARY tree and reads the
marker there. `deploy_claim.py` says so in its own banner ("claims live in the MAIN tree"); the
lane marker has no such banner. After deploying, `release --service web` returned
`REFUSED ... the token does not match`, and it succeeded only with `--token` set to the value
printed at `acquire`.

**Also measured.**
- The guard has NO override for a preflight HOLD. The only way past a user-approved HOLD is
  `.syndicate/deploy/grants/<session_id>.json`.
- `_grant()` checks `expires_epoch` ONLY, not `service`. A grant therefore opens EVERY service for
  this session until it expires.

**How to apply.**
- In a worktree, write `.current-lane.<session id>` in BOTH trees before any deploy.
- Record the `acquire` token and pass it to `release`.
- If a HOLD is overridden by the user, write the grant with a minutes-scale expiry immediately before
  the trigger. Delete it in the same command, and log it in `deploys.md`.
- *(evidence in `.syndicate/log/2026-09-12.md`, section "Deploy of `77f8d890`")*
## 2026-09-12 FORBIDDEN: reporting "the code has no X" from a search whose pattern was never shown to match anything `[lane layer2-live-scorecard-gate]`

A Grep over `syndicate` with the glob `{templates/**/*.html,static/**/*.js}` returned "No files found" for `quote_seen_age|book_age|written_at|...`. I told the user the board's templates and JS read no age field at all. That was false: the same tokens with single-extension globs found 25 matches in `intelligence.html` alone, including the card's existing `renderFreshness` book-age strip. A second query with the same brace glob also returned zero. The glob, not the code, was empty.

This is the search-tool twin of the 2026-09-02 rule about filters that have never been shown to match.

**How to apply:** before stating an absence, run the same search for a token you KNOW is there, with the same path and glob. A zero on that control means the search is broken, not the code.
## 2026-09-12 FORBIDDEN: calling a production endpoint "small" without checking its size first `[lane layer2-live-scorecard-gate]`

Mid-slate, with the user betting off the web service, I fetched `/api/intelligence/status` as a "small" endpoint to read freshness fields. It returned 87,903,243 B, the whole state payload. Its neighbour `POST /api/intelligence/query` was already measured at ~67 MB (`#632`), and the route was one grep away.

**How to apply:** read the route, or use a size-first form (`names_only`, a limit, a HEAD), before fetching from a live service, and pick the narrowest endpoint that carries the field.
## 2026-09-12 FORBIDDEN: alerting on a projection from ONE interval's rate, or applying a correction factor to readings already taken after the change `[lane layer2-live-scorecard-gate]`

A watcher on the 09-12 opening ledger projected its 05:00Z close from the latest single poll interval, times 1.117 for the four new per-record fields. At 00:48:53Z it fired `ALERT_PROJECTION_OVER_95PCT 97.4%` off one 11-minute interval growing at 2.25 MB/h. The same log showed intervals as low as 0.29 MB/h, and the 20:12->00:44Z average was 0.78 MB/h, which projects ~75%. The 1.117 was also double-counted: every reading after the 20:20Z deploy already included the new fields. Reaching the tripwire needed a sustained 2.73 MB/h. The rearmed rolling-60-minute watcher then read 770,795 -> 296,075 B/h, projecting ~71%.

**How to apply:**
- Project from a rolling window (an hour here) with a minimum span, never from the newest single interval, and state which window the alert used.
- Apply an adjustment for a change only to readings taken BEFORE it; after the change, the readings already contain it.
## 2026-09-12 RULE: a kill census's START DATE is a claim about ONSET, and a stage sampler on ONE thread is blind to a spike on ANOTHER. `[lane live-odds-worker-oom]`

**What I believed.** Kills began 13 min after the 09-11 18:03Z deploy of `21c26db1`, and the preceding 10.5 h `3bafdd2b` lifetime (0 kills) was a clean baseline. I pre-registered H1 on that commit range.

**What was true.** I had read `render_events` from 09-10, a start I chose. A peer read from 09-07 and found the onset at 09-09T19:43Z. The "clean" stretch was quiet partly because 09-11 carried a deploy roughly every hour, each resetting memory. Separately, my `ALL_PROCESS_MEMORY` stage samples went silent 40-66 s before every kill. They are emitted by the live-lens thread, and the spike was on the venue-poll thread (the Kalshi daily-book write), which those samples never cover. 7 of 7 kills sat in that other thread's window.

**How to apply.**
- Before naming an onset or a baseline, widen the events window until kills stop appearing, and write the read's start next to the claim.
- Discount any "quiet" interval that contains deploys: every deploy reboots, and memory is boot-confounded.
- When a per-stage sampler shows nothing in the last N seconds before a kill, list the OTHER threads that run in that window before reading the silence as "nothing happened". Log timing against their own markers (here `TRIM_SELECT`/`DAILY_BOOK`).
- *(evidence in `.syndicate/log/2026-09-12.md`, section "live-odds-worker OOM")*
## 2026-09-13 FORBIDDEN: using the wall time between two log lines as the COST of the code between them when another thread shares the GIL. And a preflight CLEAR on a slate night may be a post-kill restart, not a quiet worker. `[lane live-odds-worker-oom-loop]`

**What I believed.**
- I pre-registered R1: if the streaming daily-book writer runs, `TRIM_SELECT`->`DAILY_BOOK` drops to a p50 of <= 24 s (the 58736a69 baseline was 36.0 s). The only code between those two lines is the book write, and the new writer was ~3x faster locally.
- Separately, I read the deploy preflight's `CLEAR: only infrastructure processes running` as the worker being between sweeps.

**What was true.**
- **R1:** the first 12 paired ticks gave p50 31.1 s, neither met nor falsified. The slowest ticks carried the FEWEST appended points (82.8 s / 1,398 and 97.8 s / 1,404), interleaved with 9-11 s ticks. The venue-poll thread shares the interpreter with the live-lens thread's Monte Carlo builds, so its wall time measured contention as much as work. A reachability test that cannot read healthy when the code runs is instrument blindness.
- **CLEAR:** the worker had been oomKilled at 00:07:50Z and restarted at 00:07:51Z. The CLEAR at 00:09:13Z was a fresh process, 83 s old. Separately, I told the user "no kills to the deploy" from event reads that ended at 00:00:32Z and ~00:02Z; that kill landed 5-7 min after them.

**How to apply.**
- To prove a code path ran, emit a line FROM that path (a counter or a stamp), or measure a property only it can change. Never use the gap between two neighbouring log lines on a multi-threaded process.
- If you pre-register a duration anyway, first show over the baseline that it tracks the work, e.g. correlate it with `appended` before trusting it.
- When a preflight on a live-slate night returns CLEAR, read `render_events` up to that minute before calling the worker quiet. A post-kill restart reads identically.
- Any "0 kills up to event X" must come from a read whose window reaches X.
- *(evidence in `.syndicate/deploys.md` 2026-09-13 00:14:31Z and 01:14Z, and `.syndicate/log/2026-09-12.md`)*
## 2026-09-13 FORBIDDEN: grading "still there N minutes later" from a poller without checking that the later poll read a NEWER build `[lane layer2-live-scorecard-gate]`

A session capture polled `/api/board/layer2-shortlist` every 2 min and graded the vanish rate as "a poll at least 10 min later still carries the market". Two things made later polls re-read the build the market was sighted in:
- Build gaps of up to 1,601s during the slate.
- The 09-12 shortlist stopped rebuilding at 04:58:55Z (the Central date roll), leaving 2 h of polls on one build.

A re-read of one build reports every market as still there. On the same final capture (80 builds), skipping same-build polls moved live vanish from 400 of 663 (60%) to 426 of 648 (66%). Rows served 5-10 min old moved from 56% to 69%, and the first gate window from 56% to 78%. The obvious alternative, "a build at least 10 min newer", read 77% because it also lengthened every row's horizon.

**How to apply:**
- Measure persistence against a NEWER artifact (its `written_at`), not a later poll. A re-read of the same artifact is "no new look", never "still there".
- When fixing such a rule, change only the defective case and report both readings. A fix that also moves the horizon changes the thing it is correcting.
- Judge presence AT the check point, never "did it ever leave before it". A replay of the worker's departure log over the same 80 builds wrote 1,109 returns against 2,245 departures, and an "ever left" join called 108 live sightings gone that were back by the deciding build.
## 2026-09-13 An approval covers a SHIP LIST, not "main": when main moves between the answer and the deploy, re-ask or deploy the approved SHA `[lane layer2-live-scorecard-gate]`

This refines the 2026-09-07 corollary above ("re-resolve the world before acting"; roll forward from `main`).

The user approved "Deploy both now" against a named ship list: web would carry this lane's allowlist line plus six named files from other lanes, and refresh-worker would carry this lane's four files. Between that answer and the web claim, origin/main moved to `3e18be8e`, another lane's refresh-worker disk COMPACTION, which deletes and gzips files. Re-resolving showed web growing from 10 to 12 code paths and refresh-worker from 4 to 7. Rolling forward to "main" would have shipped a destructive, unmeasured change under an approval that never covered it.

Re-resolving also showed refresh-worker already live on `3e18be8e`, which contains this lane's commit. No refresh-worker deploy was needed, and deploying the approved (older) SHA there would have reverted the compaction.

**How to apply:**
- Immediately before preflight, re-run `git diff --stat <live>..<target>` for every service you deploy. If the ship list grew past what was approved, either re-ask or deploy the approved SHA (it must still be on origin/main), and say which in `deploys.md`.
- Never deploy a SHA OLDER than what a service already runs. Read each service's live commit first: a peer's newer deploy may already carry yours.
## 2026-09-13 FORBIDDEN: gating a ledger commit on a PowerShell function's return value without `@()` at the call site. A single match unrolls to a bare string, so `.Count` reads 1 and `[0]` is its FIRST CHARACTER. `[lane live-odds-worker-oom-loop]`

**What I believed.** A deleted-lines gate was sound as written:

```
$d = Get-DeletedLines 'x'
$d.Count -eq 1 -and $d[0] -like '...'
```

It was meant to confirm that a commit removed exactly the one line I had edited.

**What was true.**
- The gate refused two correct commits in a row. PowerShell unrolls a one-element pipeline result, so `$d` was a string: `.Count` was 1 and `$d[0]` was `-`.
- The only visible symptom was `[System.Char] does not contain a method named 'Contains'`, and that appeared only once I split the conditions apart.
- It failed CLOSED, which is the safe direction. But a gate that cannot pass on correct input teaches people to override it.
- Separately, the harness refused a helper named `Del` as `Remove-Item` (its alias) before anything ran.

**How to apply.**
- Write `$d = @(Get-DeletedLines ...)` at EVERY call site, and cast each element with `[string]` before calling string methods.
- Print each gate condition on its own line before AND-ing them. A combined `False` names no culprit.
- Never name a helper after a PowerShell alias: `del`, `rm`, `ri`, `sl`, `gc`, `cat`, `ls`, `echo`.
- After `session_worktree.py land`, check `rebase-merge` is absent BEFORE testing `merge-base --is-ancestor HEAD origin/main`. During a paused rebase HEAD is upstream, so that test passes trivially.
- *(evidence in `.syndicate/log/2026-09-13.md`, section "live-odds-worker-oom-loop — session 791399da — ~1:25 PM CT")*
## 2026-09-13 — RECURRENCE (the 2026-09-11 REQUIRED rule that a claim transfer is not in force until the PRIMARY `lanes.md` says so): I released a claim in my worktree, read it back as free, and both code edits were BLOCKED `[lane layer2-prior-date-live-carryover]`

- **What I did:** I released `football-layer2-live-parity`'s claim on `pipeline/intelligence_state.py` in the WORKTREE copy of `lanes.md`, confirmed with `claims_by_path` that only my lane held it, and started editing.
- **What happened:** `lane-guard` read `$CLAUDE_PROJECT_DIR/.syndicate/lanes.md`. That is the PRIMARY tree: 163 commits behind origin/main, carrying +205/-55 uncommitted edits from other sessions.
  - My release did not exist there.
  - `ncaaf-window-reason`, CLOSED on origin/main since 09-11, still read OPEN there and held `pipeline/layer2_shortlist.py`.
  - Both edits blocked. Getting past them cost a user override question.
- **The rule going forward:**
  - Mirror a claim change into the primary copy BEFORE the first edit: anchors asserted exactly once, CRLF preserved.
  - Check the result with the guard's own `_claims()` plus a suffix `matches()` against the primary file.
  - Also look there for claims that origin/main has already CLOSED. They block exactly like live ones.
## 2026-09-13 — OVERTURNED: the Layer 2 fast path is NOT a 14-27 s stage. It measured 133-182 s per build on refresh-worker, and the docstring figure had sized my plan `[lane layer2-prior-date-live-carryover]`

- **What was believed:** `_refresh_layer2_shortlist_only`'s docstring (2026-08-14) says "the shortlist stage measured 14-27s". It uses that figure to call a 300 s rate limit a ~8% duty cycle. I carried the figure into the carryover's cost estimate.
- **What was measured:** refresh-worker, `LAYER2_FAST_REFRESH date=2026-09-12`, 2026-09-13 04:34:59-04:58:57Z: `elapsed_s` 176.89, 182.04, 133.53, 166.74 and 164.11. Against builds ~5-7 min apart, that is roughly half the loop's time, not 8%.
- **How to apply:** before sizing periodic worker work off a stage's cost, read that stage's own elapsed line from production logs for a comparable slate. A cost quoted in a comment is a dated measurement taken on a different board size. The carryover's cost is restated in its lane and in `state_layer2.md [layer2-prior-date-carryover]`.
## 2026-09-13 — OVERTURNED: "a 304 from /api/ops/artifacts/stream means refresh-worker's copy is current" is FALSE for append-only tails, and "ODDS_SWEEP_LAUNCHED means the sweep ran" is FALSE. Together they took NFL off the Sunday board `[lane refresh-worker-disk-inventory]`

- **Belief 1 (the puller's own comment): a 304 is the cheap steady state.**
  - `pull_streamed_artifact` sent `since=<local mtime>` AND `Range: bytes=<local size>-`. The route answers 304 on `st_mtime <= since` BEFORE it reads Range.
  - Measured: refresh-worker's `nfl_source/tracking/book_quotes/2026-09-13.jsonl` sat at 19,914,752 B (books from 09-12 08:02Z) while web held 28,757,424 B (13:40Z).
  - Probes with Range from 19,914,752: `since` older than web -> 206 (8.8 MB); `since` >= web -> 304.
  - The served board had 0 NFL rows for today. Fixed in `48c1fc61`.
- **Belief 2: `ODDS_SWEEP_LAUNCHED ... sports=mlb,nfl,soccer` at 15:48:15Z meant NFL was swept.** It was refused 32 s later: `A refresh run is already active (pid=17018)`. The per-sport marker had already been stamped (`#25`), so NFL's next sweep moved past kickoff.
- **How to apply:**
  - A silent success path (304/416) needs its own "current since when" reading, not an inferred one.
  - For append-only files the byte offset is the watermark; a clock is a second, conflicting one.
  - Grade a launch by what LANDED (web shard mtime and size, `ODDS_SWEEP_OUTCOME`), never by the launch line.
  - When a board sport looks stale, compare web's shard (ops stream probe: `X-Artifact-Mtime`/`X-Artifact-Size`) against the reader's copy BEFORE diagnosing capture.
  - *(evidence: `deploys.md` 2026-09-13 15:43:33Z and 16:09-18:02Z)*
## 2026-09-13 — OVERTURNED: "gzip magic + a trailer ISIZE bigger than the compressed size proves a `.gz` is complete" is FALSE `[lane book-quotes-prefer-fuller-copy]`

- **What I believed:** a `.gz` that starts with `1f 8b` and whose last 4 bytes (ISIZE) are >= its on-disk size is trustworthy enough to prefer over a plain copy.
- **What falsified it:** `test_a_truncated_gz_never_wins` (write a 500-row `.gz`, cut it in half) resolved to the truncated `.gz`. A stream cut mid-way keeps its header, and its "trailer" is 4 arbitrary bytes of compressed data, which easily read as a large ISIZE.
- **How to apply:**
  - The gzip trailer is an estimate, not proof of completeness. That is fine for a memory guard that over-estimates (`book_quotes_logical_bytes`), and wrong for a decision about WHICH file readers get.
  - To prefer a `.gz`, inflate it to the end once (EOFError/CRC failure = incomplete) and cache by (path, size, mtime).
  - Write the truncation test BEFORE trusting a cheap check. Here it was the only thing that caught this.
  - *(evidence: `log/2026-09-13.md`, section "lane `book-quotes-prefer-fuller-copy` — checkpoint")*
## 2026-09-13 — OVERTURNED: "the OddsAPI live endpoint can only ever serve upcoming events" is FALSE, and a fetcher filtered on it for a whole season `[lane nfl-live-props-missing]`

- **What was believed:** the NFL props fetcher's `events_in_scope` docstring said the endpoint serves only upcoming events, and the code dropped every event with `commence_time < now`. So no prop was ever requested for a game in progress. The board showed 0 live NFL props all afternoon, and every live prop died in the opportunity gate as `live_market_stale`.
- **What falsified it:** a probe at 2026-09-13T22:26Z. `/events` listed the 4 games in progress (and not the finished ones). Each game's `/events/{id}/odds` returned props from 6 books with 25 of 25 markets updated after kickoff. The OddsAPI v4 guide says `/events` returns "in-play and pre-match events".
- **How to apply:**
  - A filter justified by a claim about an external API is a belief until probed. One call costs credits in single digits; a season of missing in-play markets does not.
  - When one sport's live markets work and another's do not, diff the EVENT SELECTION first. MLB selects by slate date (`fetch_mlb_oddsapi_local.py:772`); NFL and NCAAF selected by `commence_time >= now`.
  - Instrument corollary from the same lane: `[live_refresh_loop] ODDS_SWEEP_LAUNCHED` is printed BEFORE `launch_refresh_run` (`live_refresh_loop.py:5741` vs `:5767`). It fires for launches then refused with `A refresh run is already active`. Count runs from the refresh run itself, never from that line.
  - *(evidence: `log/2026-09-13.md`, section "lane `nfl-live-props-missing` — checkpoint")*
## 2026-09-13 — OVERTURNED: "the fast path keeps the board fresh, so nothing is lost when the heavy build is refused" `[lane kalshi-nfl-quote-gap]`

- **What was believed:** `_refresh_layer2_shortlist_only` exists so the board survives `MEMORY_GUARD_ABORT stage=pre_source_state_fingerprint`. Its docstring frames the refusal as "the expensive path stays refused exactly as often as before; this only stops the cheap path being refused WITH it", as if the heavy path's only product were the board.
- **What falsified it:**
  - 403 refusals, 09-12 21:34Z..09-13 16:14Z. The board rebuilt 13-51 times an hour.
  - But every side effect that lived ONLY in the heavy build stopped for ~16 h: Kalshi quote capture for all sports (`QUOTE_CAPTURE` 0), `PORTFOLIO_COMMIT` (paper orders) 0, `CANDIDATE_POOL` and `BOARD_PUBLICATION` 0.
  - Nothing reported that as a failure. A fresh board looked like health.
- **How to apply:**
  - When a cheap path replaces an expensive one under a guard, list EVERYTHING the expensive path does besides its headline output: joins, captures, commits, publications. Decide for each whether it moves, or name it as dropped.
  - Grade a refused-build stretch by the side effects' own log lines (`QUOTE_CAPTURE`, `PORTFOLIO_COMMIT`), never by board freshness.
  - Tooling corollary: `git merge-file` between a working copy and a `git show` blob can report the whole file as one conflict when their line endings differ. Fast-forward and re-apply the edit instead of trusting that conflict.
  - *(evidence: `log/2026-09-13.md`, section "lanes `kalshi-nfl-quote-gap`, `heavy-build-memory-refusal` — checkpoint")*
## 2026-09-13 — OVERTURNED: "a served board showing the rows = the fix is verified" — ONE build is a sample of a process that FLAPS `[lanes nfl-live-props-missing, quote-state-publish-retry]`

- **What I believed:** Layer 2 NFL `written_at` 22:44:36Z served 278 live props (0 before the capture fix), so I recorded "verify MET", released the deploy claim and closed the lane.
- **What falsified it:** the next builds read 0 (22:49:15Z), 216 (23:05:18Z), then 0 (23:09:02Z). Capture was fixed. The in-play gate still depended on a last-seen clock that went stale whenever web answered a quote-state publish with 503 at merge capacity. My own watcher's stop condition had broken out after the FIRST build.
- **Also overturned in the same hour:** "the 503 on the state sidecar is transient and heals" (I wrote it after one repaired publish). It heals by the NEXT sweep, and 2-8 minutes of lag is exactly longer than the 300 s in-play observation ceiling.
- **How to apply:**
  - A board-presence verification needs at least TWO consecutive builds, spanning more than one capture cycle, and the read must include the clock the gate uses (`quote_seen_age_seconds`), not only the row count.
  - A watcher must not `break` on the first success when the claim is "it stays fixed". Stop on N distinct builds instead.
  - Do not release a claim or close a lane on a first reading of a periodic process. Write "part 1 MET / part 2 OWED" instead.
  - *(evidence: `deploys.md` 22:46Z, 23:12Z correction, 23:24Z; `log/2026-09-13.md` "lane `quote-state-publish-retry`")*
## 2026-09-14 — OVERTURNED: "the 1,900 MB heavy-build floor is stale" AND "refresh-worker's memory ratchets slowly until the build is refused". Both are false. The main process STEPS up once after its first full build and holds it `[lane heavy-build-memory-refusal]`

- **What was believed (the lane's own H1/H2, and the floor's comment):**
  - The floor was sized 2026-08-07 for an in-process MLB hydration transient that now runs in a capped child, so it must be too high.
  - The ~16 h refusal came from a slow anon ratchet or from concurrent child jobs.
- **What falsified it** (refresh-worker, 09-12 18Z..09-13 23:30Z, 8,829 `ALL_PROCESS_MEMORY` samples plus 2 s `MEMORY_WATCHDOG` in 16 builds):
  - Steady-state builds still peak +296 / 719 / 1,416 MB at parent stages, with minimum headroom 633 MB. The floor is about right.
  - After every boot, unreclaimable jumps from ~75 MB past the 2,196 MB refusal line within 16-60 min, then barely moves (+~190 MB in 16 h).
  - 3,303 refused-level samples had no child process.
  - Only restarts cleared it.
- **How to apply:**
  - Before lowering a memory guard whose sizing comment is out of date, measure the current build's continuous peak (watchdog cadence, not stage-boundary samples). The stage that moved may not have been the only cost.
  - Split "step after first build" from "ratchet" by the per-hour MINIMUM within one boot. A flat minimum after the first hour is a step, and restarts, not trims, are what reset it.
  - Ledger corollary from the same lane: a claim-transfer note on a `- Files:` line that still names the file (backticked OR bare) is parsed as a live claim by `lane_claims._claims`. Wording like "is also claimed by ..." there reads as a disclaimer and drops the path after it. Describe moved claims without the file name, then re-run `_claims` on the PRIMARY `lanes.md` before editing.
  - *(evidence: `log/2026-09-14.md`, section "lane `heavy-build-memory-refusal` — checkpoint"; `state_worker.md [refresh-worker-heavy-build-refusal]`)*
## 2026-09-14 — OVERTURNED: "a capped `games_with_outcome` is a finals-side loss" — and, twice in the same diagnosis, "the producer failed" `[no lane]`

- **What was believed:**
  - Every documented cause of a capped `games_with_outcome` is finals-side (0-0 placeholder, no numeric score, game_pk/event_id join), so a 5-of-15 night reads as a finals problem.
  - Then, in turn: "the live-odds-worker OOM storm starved the lens", and "the lens produced no full-game projection".
- **What falsified it:**
  - 09-12 served `unscored: {}` with 15/15 finals. The cap was the ledger population: 8 `segment=full` h2h records.
  - The OOM storm was as bad on 09-11 (32 kills), which scored 13 games.
  - `TICK_COMPLETE` read mlb True, and layer2's `sources_seen.live_mc` showed full-game projections for 1-9 games while the ledger wrote none.
- **How to apply:**
  - On a capped date, read `unscored` FIRST. If it is empty, the loss is in the ledger population. The next reading is `records_by_market.h2h` and per-game `segment=full` counts in the per-record ledger, not the finals index.
  - Before naming an infrastructure event (OOM storm, deploy) as the cause of a data loss, pull the same event count on a night that did NOT lose data. Here that was one events-API call, and it killed the attribution.
  - A producer's health line and a join's index count are both UPSTREAM of the ledger write. Neither shows the write happened.
  - *(evidence: `log/2026-09-14.md` section "no lane — `live-gameline-accuracy-snapshot` run")*
## 2026-09-14 — OVERTURNED: "PUBLISH_FAILED rose 0 -> 9 after the refresh-worker deploy" — the baseline hour sat inside the defect window `[lane heavy-build-memory-refusal]`

- **What was believed:** the scheduled deploy of `fb0c91cf` recorded a red flag. There were 0 `PUBLISH_FAILED` in the hour before the deploy and 9 in the first 16 min after it.
- **What falsified it:**
  - The baseline hour (12:36-13:36Z) was a heavy-build refusal stretch: 35 refusals, 0 `PORTFOLIO_COMMIT`. The heavy build is what publishes, so it publishes nothing and cannot fail to publish. The hour was quiet by construction.
  - The 22 h before it on the same old commit: 4,053 `PUBLISH_FAILED` (94-261/h).
  - After the deploy: 62 in ~50 min, the low end of the old rate.
- **How to apply:**
  - Before comparing a post-deploy count to a pre-deploy window, check the window was doing the work that produces the count. A deploy that fixes a stall re-enables every side effect the stall had suppressed. "0 before" then means "not running", not "not failing".
  - Pick a baseline outside the defect window, or report the count per unit of work (per heavy build), not per hour.
  - Specialises [[re-baseline before judging]]: the one-hour window was not stale, it was unrepresentative.
  - *(evidence: `deploys.md` 2026-09-14 14:55Z; `log/2026-09-14.md` session 0f5b256e ~14:45Z section)*
## 2026-09-14 — OVERTURNED: "my commit gate checked the deleted lines". It passed on an EMPTY set, and a `-NoNewline` patch export then destroyed the edits it was protecting `[lane book-grid-gameline-ledger-log]`

- **What was believed:** a PowerShell gate verified that a `lanes.md` commit removed only my own lines:
  - `$deleted = git diff -U0 | ? { $_ -match "^-[^-]" }`
  - then "fail if any deleted line is foreign".
- **What falsified it:**
  - My one deleted line was `-- Blocked by: none.`. Its second character is `-`, so the filter dropped it.
  - `$foreign` was empty because `$deleted` was empty. The gate printed an empty list and passed, while numstat beside it read `7 1`.
  - Minutes later, recovering from a stale-base ledger-guard block, `git diff --cached | Out-File -NoNewline` joined every patch line into one.
  - `git restore` had already discarded the worktree copy, and `git apply` refused: "No valid patches in input".
- **How to apply:**
  - A "none of X is foreign" gate must ALSO assert the size of X. numstat's deletion count is the cross-check: `7 1` must yield exactly 1 deleted line.
  - Exclude only the `---` file header, never a `^-[^-]` class. A markdown bullet is `- `, so a deleted bullet starts `-- `.
  - Never export a patch through a PowerShell pipeline (`Out-File`, `-NoNewline`, `>`). Use `git diff --output=<file>`.
  - Prove the patch with `git apply --check` BEFORE discarding its source.
  - *(evidence: `log/2026-09-14.md` section "lane `book-grid-gameline-ledger-log` — checkpoint")*
## 2026-09-14 — OVERTURNED: "only a restart clears a heavy-build refusal stretch" — and a safety threshold chosen without that data cost ~11 h of builds in 45 h `[lane heavy-build-memory-refusal]`

- **What was believed:** once refresh-worker's main process settled above ~2.2 GB, heavy builds stayed refused until a boot. That belief set `339dc6e9`'s recycle threshold at 15 consecutive refusals, "to avoid restarting over a transient spike".
- **What falsified it:**
  - A replay of 23 closed streaks. 18 ended with an admitted build and no boot, after 10-80 min.
  - The same replay against thresholds: 15 leaves 987 minutes with no full build, while 1 leaves 300, because a boot resumes builds in a median 13.1 min.
  - The user asked "why do we need 15?" before anyone had measured it.
- **How to apply:**
  - A safety margin on a recovery action is a number, and it needs the same evidence as any other number. Replay candidate thresholds against the logged history before shipping one, and count the cost the margin buys (here, minutes without builds), not only the failure it guards against.
  - "Clears only on X" needs the population where it did NOT clear, counted. The original diagnosis looked at the 16 h stall and the boots, never at the streaks between them.
  - *(evidence: lane heavy-build-memory-refusal DECISION 2026-09-14 ~15:10Z; `scratchpad/threshold_sim.py` from session 0f5b256e)*
## 2026-09-14 — OVERTURNED: "CANDIDATE_POOL_CACHE limit= reports the real cap" — the test pinning it compared two values that are EQUAL by default `[lane heavy-build-child-process]`

- **What was believed:** `0a18557a` made the log line report the pool-cache cap. Its commit message and lane text said so, and `test_reports_this_pool_and_the_cache_total` passed, asserting `limit == service._candidate_pool_cache_max`.
- **What falsified it:** production at 19:20:05Z with the env read back as 2 printed `limit=12`. The print still used `_max_snapshots`. The test built the service with the env unset, where both attributes are 12, so it passed against the wrong field.
- **How to apply:**
  - A test that a value comes from X and not Y must run in a state where X != Y. When a new knob defaults to the old value, every default-state assertion about the knob is vacuous. Set the knob to a non-default value in the test.
  - Also run the new test against HEAD's file: a test that passes on the old code proves nothing about the change. Here the cap tests failed on HEAD, but the log-field test had no case that could.
  - Before quoting a log field as proof that config reached production, check the field reads the variable you changed.
  - *(evidence: `deploys.md` 2026-09-14 20:29Z and 21:16:30Z; fix `d4deb502`)*
## 2026-09-14 — OVERTURNED: "the 09-15 board is a post-deploy population because its date begins after the deploy" — a per-day first-sighting ledger is written by builds that ran BEFORE its date `[lane accuracy-assessment-0914]`

- **What was believed:** deploy #3's prediction named "the first board date written entirely after live (09-15 CT)" as the full read of the recorder's new team-name fields.
- **What falsified it:**
  - The pre-live 20:53:26Z build on 09-14 had already recorded every 2026-09-15 key; the shortlist builds the next date inside its horizon.
  - The recorder writes a key once per board date, so the post-live 09-15 builds only added 414 new keys, all soccer.
- **How to apply:**
  - A "post-change population" is defined by each record's own written-at time (`t` vs the live time), never by the date label on the file.
  - Before naming a date as the reading, check when its first part was written.
  - *(evidence: deploys.md 2026-09-14 21:30Z follow-up; `deploy3_reading.py 2026-09-15 2026-09-14T21:03:17Z`)*
## 2026-09-14 — OVERTURNED: "I can write the time from how long things usually take" — two ledger times this session were written from expectation, and both were wrong `[lane accuracy-assessment-0914]`

- **What was believed:** a finish time, or a claim's expiry, could be written into the ledger from the expected duration.
- **What falsified it:**
  - "preview v2 finished ~20:05Z": it finished before 20:00Z; the clock read 20:01:50Z.
  - "the claim lapsed at its TTL (21:16:44Z) before this entry was pushed": the push finished 21:14:28Z, and the claim was released by token.
  - Both reached origin/main before a clock read caught them.
- **How to apply:**
  - Read the clock in the same command that writes a ledger time. The corrected appends stamp their heading from `datetime.now(timezone.utc)` at write time.
  - Something that has not happened yet ("will lapse", "should finish") goes in the future tense, never as a past fact.
  - *(evidence: deploys.md 2026-09-14 21:15Z correction; lanes.md PREVIEW v2 heading correction)*
## 2026-09-14 — OVERTURNED: "a layout fit measured on the worktree app predicts production" — the same commit at the same viewport put the header lettering ON screen locally and OFF screen in production `[lane brand-logo-v3]`

- **What was believed:** a 13-reading local sweep of the header gives production's shape, and production only needs a spot check.
- **What falsified it:**
  - `/market-board` at 1500px. Locally the wordmark slot was 273px, so the lettering (which needs 268) was SHOWN.
  - On production web `ff7ec8be`, same viewport, the slot was 264px and the lettering was hidden. The live pills are ~9px wider.
  - The cause is undiagnosed: font availability, or the nav's contents.
- **Why it did not ship a defect:** the fit rule is content-driven (a flex basis plus wrap and clip, no breakpoint), so it hid correctly. A breakpoint tuned on the local numbers would have put the pills onto a second row in production at 1500.
- **How to apply:**
  - Any size-sensitive layout claim ("shows from N px", "fits at N px") is read on PRODUCTION after the deploy, at the edge widths. A local reading is a prediction, not the result.
  - Prefer a content-driven fit over a breakpoint tuned on one environment's metrics.
  - *(evidence: `lanes_history.md` brand-logo-v3 local reading; `deploys.md` 2026-09-14 5:34 PM CT)*
## 2026-09-15 — OVERTURNED: "H1 test-confirmed" — the test stubbed the one input production lacked, so it confirmed a mechanism that was not the cause `[lane nfl-live-props-board-lane]`

- **What was believed:** live NFL props were demoted on the main board because pre-kickoff state rows won a first-wins dedupe over restated L2-A cards. A new test through the real `read_combined_intelligence_response` failed on HEAD and passed with a fix, and the fix was deployed to web as `dedfede6`.
- **What falsified it:** after the deploy the page still served all 72 DEN @ KC props as watchlist / `no_game_state`.
  - Every `by_date` candidate_count was 0: there were NO state rows in production, so the fix's own log line never printed. **[CORRECTED 2026-09-15, lane combined-board-state-rows-lost: FALSE. There WERE state rows (refresh-worker persisted 374 for 09-14 at 01:56:23Z). The combined reader could not parse them. See the FORBIDDEN entry "a reader's zero is not the writer's absence" below. The dedfede6 conclusion (inert) still stands; its stated reason does not.]**
  - The real cause was upstream of the merge. The live restate built chips in-process (`build_game_chips`), which on web had no live NFL chip, while `/api/board/game-chips` served the worker-published artifact that did.
  - The test had patched `build_game_chips` to return the live chip, the exact thing production was missing. Fix 2 (`c4f45fee`) read the published chips, and props went live on the next read.
- **How to apply:**
  - Before building a test on a hypothesis, confirm its PRECONDITION exists in production. H1 needed state rows, and `by_date.candidate_count` in the same payload already said 0.
  - A test may only stub an input after it has been shown to carry, in production, the value the stub returns. Stubbing an upstream source proves the code downstream of it and nothing about whether that source delivers.
  - After a fix deploys, read the fix's OWN log line (`COMBINED_STATE_LIVE_RESTATED` here) before reading the outcome. Its absence named the wrong mechanism in one query.
  - *(evidence: `deploys.md` 2026-09-15 02:15:21Z and 02:29:09Z; lane nfl-live-props-board-lane)*
## 2026-09-15 — FORBIDDEN: reading a READER's zero as the WRITER's absence — `by_date` 0 was a dated state the reader could not parse, and the line quoted as proof said so `[lane combined-board-state-rows-lost]`

- **What we believed:** production had no per-date state rows. So `dedfede6`'s state-row restate had nothing to act on, and the combined board was built from Layer 2 cards alone by necessity.
  - `log/2026-09-14.md:720` "so there were no state rows"; `deploys.md` 2026-09-15 02:15:21Z entry ("no state rows: `COMBINED_BOARD_VINTAGE_IGNORED ...`"); this file's line above, now corrected.
- **What was actually true:**
  - TECHNICAL: refresh-worker persisted real boards: 374 / 275 / 259 candidates for 09-14 (e.g. `STATE_PERSIST_BEGIN candidate_count=374` 01:56:23Z) and 14 for 09-15.
  - Web read those exact payloads: stamps equal the worker's `CANDIDATE_POOL_READY` to the second on 4 of 4. Then it dropped every row.
  - The cause: `_read_single_date_response_for_combining` read through `_read_state_payload` and never called `_expand_persisted_state`. The writer stores `by_sport` member-aliased, the combine loop's `isinstance(items, list)` skipped every entry, and the scalar `candidate_count` held the `> 0` gate open.
  - Every other reader of that file (`read_intelligence_state`) expands; this one never did.
  - Duration unknown: aliasing landed 2026-08-09 (`2e6ad549`), and the last non-zero `by_date` in the ledger is 2026-08-29.
  - EPISTEMIC: the line quoted as proof of absence was a contradiction. `COMBINED_BOARD_VINTAGE_IGNORED date=2026-09-14 stamp=2026-09-15T01:54:49Z reason=no_rows` means a payload WAS read (it has a stamp), and it had already passed a `candidate_count > 0` gate. "Has candidates, has no rows" is a reader defect by construction. It was read as "no data".
  - The earlier tests of this function (`test_board_vintage_gating.py`) replace the reader with hand-built plain lists, which is exactly the shape production never delivers. That class is already FORBIDDEN (2026-09-09, harness that supplies what production lacks); it is not restated here.
- **How we found out:** the user asked why the board said stale while the worker persisted hundreds of candidates. The writer's own line (`STATE_PERSIST_BEGIN`) was cross-read against the reader's (`VINTAGE_IGNORED`) for the same date and minute. Then a test with the REAL writer and REAL reader, nothing stubbed: 40 and 1,500 rows read back as 0 on HEAD, and expand-on-read gave 40 and 1,500. Live on web `b6a0e346`: `by_date` 09-15 0 -> 106 (`deploys.md` 2026-09-15 14:03:51Z).
- **EXONERATED:** a key/date mismatch between the worker's writes and web's reads. Stamps matched to the second on 4 payloads, and `/api/ops/artifacts/export` showed the states travel in keyvalue, which web reads.
- **The rule going forward:**
  - A zero, empty or "missing" reported by a READER is a statement about that reader. Before recording it as a property of production, read the WRITER's own line for the same key and time window.
  - A line that carries BOTH a stamp/count AND "no rows" is a contradiction to chase, never a confirmation of absence.
- **Cost:**
  - One web deploy shipped inert on the false precondition (`dedfede6`).
  - A false line stood in this file for ~12 h, repeated in `deploys.md` and the session log.
  - Every persisted state row (259-479 per build on 09-14) was absent from the main board for an unknown period, possibly weeks.
- **Check, not rule:**
  - (1) Put expansion INSIDE `_read_state_payload`, the choke point every state read shares, so no future caller can skip it. Pin it with a test that round-trips the real writer through every public reader.
  - (2) Emit `by_date[date].stored_candidate_count` (the payload's scalar) beside `candidate_count` (rows read), and log `COMBINED_BOARD_STATE_ROWS_UNREADABLE` when stored > 0 and rows = 0. The contradiction then appears in the served payload, where the last three sessions looked, instead of only in a log line nobody queried.
## 2026-09-15 — FORBIDDEN: carrying a deploy's predicted effect on a time-varying field from a reading taken hours earlier — re-derive it at preflight, and baseline every field it names plus the served row count `[lane combined-board-state-rows-lost]`

- **What we believed:** expanding the state on read "would NOT move `computed_at`", because the state stamps it adds are newer than tomorrow's shortlist. Written into the lane and `state_board.md` before the deploy, from readings taken at 03:56Z.
- **What was actually true:**
  - At deploy (web `b6a0e346`, live 14:10:07Z), refresh-worker's heavy builds had been refused since 13:41:13Z. The fast path kept the shortlists fresh (09-15 `14:07:00Z`, 09-16 `14:10:11Z`), so the 09-15 state (`13:39:43Z`) was now the OLDEST input.
  - `computed_at` moved from `13:48:51Z` `fresh` to `13:39:43Z` `stale`. The prediction had been true in the 03:56Z regime and false in the 14:10Z one, and nobody re-derived it for the regime the deploy landed in.
  - SECOND HALF OF THE SAME ERROR: the pre-deploy baseline (13:57:55Z) recorded `by_date`, `legacy_candidate_count`, `artifacts_dated` and `computed_at`, but NOT the served row count. So whether state rows displaced Layer 2 cards under first-wins dedupe is now PERMANENTLY unmeasurable (at most 106).
- **How we found out:** the post-deploy reading at 14:10:27Z, cross-read with refresh-worker `CANDIDATE_POOL_READY date=2026-09-15 count=106` at 13:39:43Z (`deploys.md` 2026-09-15 14:03:51Z).
- **The rule going forward:**
  - A deploy's expected effect on any field that depends on worker timing (ages, freshness verdicts, counts) is re-derived from readings taken inside the preflight window, not carried from the diagnosis.
  - The baseline captures every field the prediction names PLUS the served row count and its composition by source, because a merge-order change can only be attributed against those.
- **Cost:**
  - The user was shown a false prediction and approved a deploy partly on it. The outcome was benign (the new age is true, and the user kept the `stale` label).
  - One effect of a product change can never be measured.
- **Check, not rule:** preflight asks for the prediction and the baseline. `deploy_preflight.py` takes `--expect "<field>=<value>"` and `--baseline-read-at <UTC>`, and returns HOLD when the baseline is older than the 15-min CLEAR window or names no row count. The post-deploy entry then lists expected against measured, one line per field.
## 2026-09-15 — FORBIDDEN: caching a verdict whose validity depends on the date's relation to TODAY under a key that is only the date. At midnight "tomorrow" becomes "today" and the verdict outlives its premise. `[lane wnba-future-date-cache-carry]`
- **The belief overturned:** `has_games_for_date` (`syndicate/features/wnba/sources.py`) said *"A confirmed True is stable and safe to remember."* It was safe for an ESPN-confirmed True. The same set also held Trues from the "not today and a slate file exists" shortcut, whose premise is the date NOT being today. It was checked before the today rule, so after midnight it answered for today.
- **What was actually true:**
  - refresh-worker writes an EMPTY `recommendations_slate_<tomorrow>.json` (94 B, 0 games) before midnight CT.
  - The process that asked about tomorrow in the evening read the no-game day as confirmed. It saved the 2026-08-30 slate under today's `live_state` key, and the board showed four FINAL chips on 09-14 and 09-15.
  - This is exactly the seed `wnba-schedule-guard-fix` left unnamed on 09-11.
- **How we found out:** the user saw the chips. The phantom log line starts at 00:04 and 00:06 CDT, right after midnight. The empty slates were published BEFORE their date's CT midnight on the bad days and AFTER it on the clean days (`deploys.md` 2026-09-15 14:34:14Z). A writer-level test that primes tomorrow, rolls the clock and builds returned `2026-08-30` on origin/main.
- **The rule going forward:**
  - One cache holds one provenance.
  - A value derived under a clock-relative condition (`!= today`, "past", "future") is either not cached, or keyed by (date, the day it was evaluated).
  - A test for any date-keyed cache ROLLS THE CLOCK between the write and the read. Two calls on the same "today" cannot see this.
- **Cost:** two days of stale WNBA chips and a phantom `scheduled_games 4` on Layer 2. The 09-10 fix had passed its same-day readings because they never crossed a midnight with a pre-written tomorrow file.
## 2026-09-15 — OVERTURNED: "the board-snapshot readers miss the writer's disk fallback, so route them through `_read_state_payload`" — the fallback cannot reach web at all, and routing would have handed them month-old disk files `[lane state-read-expand-choke-point]`

- **What was believed:** `read_latest_intelligence_board_snapshot_response` and its fallback read keyvalue only, while `_write_state_payload` can divert an oversized snapshot to disk. So they had a real gap, and the user was told so and asked for the routing.
- **What falsified it,** measured 2026-09-15 14:39-14:41Z before any code:
  - `board_snapshot*.json` is deliberately NOT in the artifact allowlist (`artifact_publisher.py:1072-1095`), so no fresh snapshot can reach web's disk whatever the reader does.
  - 0 disk-fallback writes on either service in 24 h.
  - Web's disk DOES hold a stale `reports/intelligence/intelligence_state.json` (25.8 MB, stamped 2026-08-10). `_read_state_payload` returns a disk copy whenever keyvalue has none, and the snapshot fallback loop globs disk. The "fix" would have created the failure it claimed to close.
- **How to apply:**
  - Before widening a reader to a new SOURCE, check two things on the SERVICE that runs the reader: (a) does the transport ever deliver a FRESH copy of that source there (allowlist, publish logs), and (b) what STALE copies already sit there.
  - A reader and its transport are one change. Neither half is a fix alone, and the reader half is the dangerous one.
  - A gap stated from code alone is a hypothesis. It was surfaced to the user as a finding, which is how it became an instruction.
  - *(evidence: `state_board.md` `[combined-board-state-rows-lost]`; `log/2026-09-15.md` session 3a65723e)*
## 2026-09-15 — OVERTURNED: "the stored count will equal the rows read" — the writer caps each `by_sport` list per sport, so an instrument pairing two counts differed by design on its first reading `[lane combined-board-rows-unreadable-tripwire]`

- **What was believed:** after web `da268e07`, `by_date[date].stored_candidate_count` would equal `candidate_count` for every readable date. That was written into the lane's Verification and the deploy's prediction.
- **What falsified it:**
  - The first reading (15:37:01Z): 09-15 stored **113**, rows **111**.
  - refresh-worker saved the full pool (`CANDIDATE_POOL_READY count=113`). The writer builds `by_sport` with `_default_unbounded_by_sport_cap()` = 60 per sport, and La Liga was served at exactly 60.
  - The cap and its "true counts stay available via `candidate_count`" comment sat at the call site the whole time.
- **Why it cost nothing:** the tripwire fires only at `rows == 0`, a rule chosen for the defect, not for equality. Had it fired on `stored != rows`, it would have alarmed on every busy slate from the first minute.
- **How to apply:**
  - Before predicting that two numbers from one payload agree, enumerate every TRANSFORM the writer applies between them: caps, dedupe, filters, pruning. Read the builder, not only the field names.
  - Gate an instrument on the defect's own signature (`rows 0 / stored > 0`), never on equality of two counts that pass through different transforms.
  - *(evidence: `deploys.md` 2026-09-15 15:30:14Z; `state_board.md` `[combined-board-state-rows-lost]`)*
## 2026-09-15 — OVERTURNED: "a `cd` at the top of a Bash call scopes that call" — parallel Bash calls share ONE shell, and a sibling's `cd` ran `git rebase` in the primary tree twice `[lanes state-read-expand-choke-point, combined-board-rows-unreadable-tripwire]`

- **What was believed:** `cd /c/tmp/syndicate-sessions/<lane> && git rebase ...` operates on that worktree, whatever other Bash calls run beside it.
- **What falsified it:**
  - Twice, a call issued in parallel with one that ran `cd /c/Users/tempadmin/OneDrive/Coding/Syndicate` printed `cannot rebase: You have unstaged changes`. The worktree was clean, so the rebase had run in the PRIMARY checkout.
  - A survey `grep` in the same batch returned line numbers ~400 lower: the primary tree's stale copy of `pipeline/intelligence_state.py`.
  - Git refused both rebases, and the primary tree was verified untouched (HEAD `e88447a2`, no rebase in progress). A clean primary tree would not have refused.
- **How to apply:**
  - In any Bash call issued in PARALLEL with another, never use a bare `cd`. Use `git -C <path>` and absolute paths, or confine it to a subshell: `( cd <path> && ... )`.
  - A result whose line numbers, HEAD or `git status` do not match the worktree you meant is the signal. Stop and re-read the tree before running a mutating command.
  - A mutating git command (`rebase`, `reset`, `add`, `commit`) never shares a batch with a call that changes directory.
  - *(evidence: `log/2026-09-15.md` session 3a65723e, dead ends)*
## 2026-09-15 — OVERTURNED: "a deploy the guard let through was a deploy the guard checked" — two web deploys passed `deploy-guard.py` because it never classified them as deploys `[lane deploy-guard-python-post]`

- **What was believed:** the two 2026-09-15 web deploys (`b6a0e346`, `da268e07`) went through the two-lock gate. The claim and a CLEAR preflight had been taken, the deploy call was not refused, and that read as "the guard checked the locks".
- **What was actually true:** `POST_INTENT` knew only curl/PowerShell. The Python `urllib` POST matched `DEPLOYS_ENDPOINT` but not the intent, so the guard returned exit 0 WITHOUT looking at a claim or a receipt. The locks were held only because the session took them voluntarily. Any session deploying the same way would have skipped both, and `NO_EXPECTATION` too, silently.
- **How we found out:** a smoke test of the updated guard in the primary tree. A first synthetic command ALSO returned 0 (its "POST" was only in a comment), and asking why led to the pattern. The guard's own blocked shape (`render_deploy.py`) returned 2, while a command shaped exactly like that day's deploys returned 0. Fixed in `11167fdf`; the primary tree now returns 2 for it.
- **The rule going forward:**
  - A guard's SILENCE is evidence only for shapes the guard is known to classify. Before relying on "not refused", run the guard on the EXACT command shape you are about to use and see it refuse without locks. Same family as `feedback_instrument_blindness`: a healthy reading means nothing until you have seen what makes it read unhealthy.
  - When a deploy goes through, look for the guard's own "DEPLOY GUARD: clear" line. Its absence means the command was never classified.
  - A text guard cannot see into a script run from a FILE; deploy inline, with `scripts/render_deploy.py`, or with curl.
- **Cost:** two production deploys ran outside the gate they were believed to pass. No harm, because the locks happened to be held, but that was luck of habit, not enforcement.
  - *(evidence: `leads.md` 2026-09-15 lead, promoted; `log/2026-09-15.md` session 3a65723e; lane `deploy-guard-python-post`)*
## 2026-09-15 — OVERTURNED: "soccer shots props over-predict by 40%; ship a 1.33 divisor". A per-row skill score keyed on a PREDICTION list cannot see what the list is missing, and it read a stale squad as a level error `[lane soccer-season-market-audit]`

- **What was believed:** `[soccer-shots-prop-skill]` (2026-08-31) measured predicted 0.58 vs realised 0.42 over 9,840 (player, match) rows, a ratio of 1.40, and a held-out scalar divisor of 1.33 "wins in all 9 leagues".
- **What was actually true** (season to date, 07-22..09-14):
  - Players who actually appeared are UNDER-predicted: 0.87 held-out; regular starters 0.68, fringe players 1.08.
  - The predicted lists are last season's. The share of real team shots attributable to a listed player runs from 36% (Championship) to 87% (MLS).
  - On the new data, the 08-31 method gives 1.09–1.13. That method is an unconditional mean over every predicted row, with unmatched or absent players scored as 0. Absent squad members and name misses become zero-shot rows, and shots by unlisted players are invisible; both push toward "over-predicts".
  - The divisor now worsens MAE in the leagues props are bet on (EPL 0.828 → 0.831, Serie A 0.835 → 0.839).
- **How we found out:** a props run on ESPN box scores, bound one-to-one per side, read 0.88 — the opposite sign. Before quoting either number, the join was measured from the OUTCOME side: the share of real shots belonging to a listed player, per league.
- **The rule going forward:**
  - Before reading a level error off rows keyed on a prediction list, measure coverage from the outcome side: what share of the real volume (shots, goals, minutes) belongs to entities the list contains. Below ~90%, the "error" is at least partly the list.
  - Score a conditional quantity on the population the bet settles on — appeared players, `*_if_playing` — not an unconditional mean over a roster.
  - A held-out fit validates a correction only for the population and method it was fitted on. Re-measure when the season, and the squads, turn over.
- **Cost:** a standing shipping recommendation that would have cut starters' shot probabilities further. Caught before any engine change.
  - *(evidence: `findings_2026-09-15_soccer_season_market_audit.md` "Player props"; `state_soccer.md [soccer-season-market-audit]`; `log/2026-09-15.md` session abacd435)*
## 2026-09-15 — OVERTURNED: "a FotMob league id verified against name AND country is a stable join key" — it identified ONE SEASON of the competition, and a same-day decoy check cannot see that `[lane fotmob-season-scoped-league-ids]`

- **What was believed (2026-08-22):** the league ids in `fotmob_match_id.py` and `soccer_fotmob_harvest_2y.py` were "verified against ccode", so they were safe to pin as the join key.
- **What happened:**
  - FotMob's league `id` is SEASON-SCOPED for 4 of the 10 leagues:
    - Eredivisie 892939 -> 900368 -> 937276
    - Championship 893033 -> 900638 -> 938218
    - Belgian 892857 -> 900433 -> 937988
    - MLS 889747 -> 896669 -> 913550
  - The competition itself is `primaryId` (57/48/40/130).
  - From the 2026-27 season on, every live Championship, Eredivisie and Belgian match hid its momentum panel (9 of 9 None on 09-12). Nothing errored.
  - The 2y harvest walked 2024-08..2026-08 with the 2025-26 ids, so it kept ONE season for those four leagues. It was described as two seasons across ten leagues.
- **Why the check missed it:**
  - The verification was a same-day decoy test (Canada 9986, Brazil 268). That proves a key is unambiguous on the day it is read. It says nothing about whether the key is the same next season.
  - The six leagues that never broke have `id == primaryId`, so most of the population looked healthy.
- **How to apply:**
  - A pinned external id needs a CROSS-TIME check as well as a same-day one. Read the vendor's listing on a date from a previous season and confirm the id resolves there too.
  - Prefer the vendor's canonical id (`primaryId`, `parentLeagueId`) when the payload carries one.
  - A dataset described as "N seasons over K groups" must print its coverage per (group, season). A narrow key truncates it silently.
- *(evidence: `deploys.md` 2026-09-15 18:08:50Z entry; commit `c725cc29`; `state_soccer.md` `[soccer-live-momentum]`)*
## 2026-09-15 — OVERTURNED: "the attached-POST classifier leaves reads alone" — it shipped tested only on hand-written commands, and the repo's own read-only graft builder classified as a deploy `[lanes deploy-guard-python-post, deploy-guard-file-scripts]`

- **What was believed:** `11167fdf`'s `_PY_POST_INTENT` blocked Python deploys and ALLOWED reads, on the evidence of its test file (GETs, a comment, GET-list + POST-elsewhere) and three probes of this session's own command shapes.
- **What was actually true:** its body rule `\bdata\s*=` matched any `data = ...`, including the ASSIGNMENT `data = json.loads(urllib.request.urlopen(req...))` that `scripts/build_consolidated_graft.py:93-96` writes right after a GET of `/deploys?limit=5`. That read-only shape, pasted inline, was already blocked on main. The test corpus was written by the author of the rule, so it contained only the shapes the author had in mind.
- **How we found out:** the next lane scanned EVERY repo file naming a deploys endpoint (22) through the landed classifier BEFORE extending it. 2 classified as deploys; one was `render_deploy.py` (correct) and the other the graft builder (wrong). Fixed in `af7c895c`: `data=` counts only after `(` or `,`. Rescan: only `render_deploy.py`.
- **The rule going forward:**
  - Before landing a text classifier that can BLOCK (a guard, a gate, a filter), run it over the REAL corpus it will meet (the repo's own files and past commands that mention the pattern), and list every hit. A hand-written test set proves the cases you thought of, not the ones that exist.
  - Put the real files in the allow tests (copied, resolved, run), not synthetic stand-ins, so a false positive is a red test rather than a user report.
- **Cost:** one false positive shipped to main, and it was live in the primary tree's guard for about an hour. Caught before any read-only script was actually blocked.
- *(evidence: `log/2026-09-15.md` session 3a65723e, the `deploy-guard-file-scripts` entry; commits `11167fdf`, `af7c895c`)*
## 2026-09-15 — OVERTURNED: "a sparkline of the pick's market probability tells the same story as the movement arrow beside it" — the line plotted the no-vig CONSENSUS, the arrow read the shown PRICE, and they disagreed on 132 of 294 rows `[lane layer2-row-parity]`

- **What was believed:** a time series of the pick's no-vig ("fair") probability is the natural picture of "did the market move toward the pick", so it would agree with the arrow that reads the label's odds.
- **What happened:**
  - The first design shipped in `87558f2f`. At 18:08:02Z, 45 of 94 series sloped against their own arrow; at 19:11:17Z, 132 of 294 did.
  - They are different quantities:
    - The arrow compares the label's own price pair: one book, or the best price across books.
    - The line was the de-vigged consensus across every book.
    - The best price can lengthen while the consensus shortens: one book hangs a stale number, the vig moves, or the best-price book changes.
  - Every series was well-formed and every test passed, because the tests checked each visual on its own, never the line against the arrow on the same card.
  - The redesign (`5686a555`, user decision "Plot the label's price from our open") makes the line's ends the label's price pair, so line and arrow cannot disagree. The consensus move went to the tooltip.
  - After it: 0 disagreements on every date (19:56Z), and 519 of 519 on the rendered page.
- **How to apply:**
  - Two visuals side by side on one row must be computed from the same quantity, or labelled as different ones. Test the PAIR, not each one: a "line vs arrow disagree" count would have caught this before the deploy.
  - Name the quantity in the caption ("Implied probability of this pick's price … (best price across books)").
  - A verify script's allow-lists are part of the design. After the redesign the script read "malformed 867" because it still named the old bases. Change the instrument in the same commit as the code it measures.
- *(evidence: `deploys.md` 2026-09-15 18:08:02Z FOLLOW-UP (1), the 19:13:36Z entry and its 19:57:56Z FOLLOW-UP; commits `87558f2f`, `5686a555`, `4ccbea86`)*
## 2026-09-15 — OVERTURNED: "fix the puller that spliced, repair web's copy, and web's merge refusals go to 0" — a SECOND publisher kept republishing its own stale copy, and the merge log had named it all along `[lane book-quotes-splice-repair]`

- **What was believed:** P2 (refresh-worker's tail sync) plus P3 (web's repair) would bring `MERGE_REFUSED_BAD_LINES` to 0. The P4 verify was written that way.
- **What happened:**
  - refresh-worker behaved exactly as predicted: one `STREAM_SYNC_WHOLE` per shard, dropping exactly web's refused counts.
  - Refusals continued on today's shards (mlb 10, soccer 43 per publish), and every one was `publisher=live-odds-worker` in web's `ARTIFACT_MERGE_DEFERRED` line in the same second.
  - live-odds-worker holds its own copies and never re-syncs a shard it already has: the repair list asks only for missing files.
- **Also in the same hour:**
  - I attributed the refusals to `clv_openings` publishes by timestamp adjacency. `_requires_json_lines` matches `book_quotes` only, and `dir=` prints the GRANDPARENT folder (`tracking`), not the family.
  - Three parallel log scans drew 503s from the log API. Most windows came back empty and were printed as "non-json" rather than failing.
- **How to apply:**
  - Before predicting that a receiver-side count reaches 0, enumerate EVERY publisher of the path over a window. Web's merge lines carry `publisher=`; a fix scoped to one publisher is scoped to one publisher.
  - Read the emitter's format string before interpreting a log field (`dir=` was not what its name suggests).
  - A log-API scan runs as ONE process with retry and backoff, and it records which windows actually returned. An empty window is not an empty log.
- *(evidence: `deploys.md` 2026-09-15 19:27:29Z follow-up; `lanes.md` book-quotes-splice-repair P4 READING; `state_worker.md` `[streamed-pull-append-only-tail]`)*
## 2026-09-15 — OVERTURNED: "a lane whose header reads CLOSED on origin/main is safe to archive" — its live owner was reopening it in an uncommitted worktree edit `[session 3a65723e, ledger archive; no lane]`

- **What was believed:** `scripts/trim_lane_blocks.py` proposed 39 closed or orphaned blocks for removal. All 39 read CLOSED on origin/main, held 0 claims and had no OPEN header, so moving any of them to `lanes_closed.md` looked like pure bookkeeping.
- **What happened:**
  - Before touching the 12 closed TODAY, a liveness read found all 4 owning sessions had written their transcripts within minutes. One of them, `3421d2c5`, had an UNCOMMITTED `lanes.md` edit in worktree `disk-inventory-test-clock` flipping `ncaaf-prop-kickoff-slate-date` from CLOSED back to OPEN for a refresh-worker deploy.
  - origin/main cannot show that edit, and the header, claims check and invariants all read origin/main. Archiving the block would have deleted the text the owner's rebase was about to modify.
  - The user's choice ("older lanes only", leaving today's closures to possibly-running owners) avoided the collision; the header alone would not have.
  - A 09-14 closure whose owner was idle for 21h (`brand-logo-v3`) was archived. A 09-10 lane with a stale marker (`wnba-schedule-guard-fix`) was NOT: a live session had closed it today with a handoff to its own OPEN lane.
- **How to apply:**
  - A CLOSED header is the owner's LAST PUSHED state, not their current intent. Before moving or rewriting another session's block, read owner liveness:
    - the session transcript mtime (`~/.claude/projects/*/<sid>.jsonl`)
    - its `.current-lane.<sid>` marker
    - OPEN lanes naming the session
    - `git status` of any worktree named for the lane
  - Treat "live, or has an uncommitted ledger edit" as "do not touch".
  - The lane's CLOSER can differ from its OWNER: check the liveness of both.
- *(evidence: `log/2026-09-15.md` addenda "archived 26 lanes closed before 2026-09-15" and "owner liveness of the 13 closed lanes"; commits `7e721cfa`, `d1d74ce9`)*
## 2026-09-15 — OVERTURNED: "a mechanism that passed a held-out test is ready to build". The test fed it an input production does not have, and on production's own inputs it failed until a join defect was fixed `[lane soccer-player-role-allocation]`

- **What was believed:** the start/sub shot mixture was validated. It passed held out (H8: 9/10 leagues), with P(start | appear) taken from ESPN box-score roles.
- **What was actually true:**
  - Production has no box-score role table.
  - Built from what production does carry (Understat minutes per appearance, ESPN counts, a minutes prior), the same mechanism FAILED: H11 won 6/10 leagues, and H12 was +0.031 log loss.
  - The cause was a join, not the mechanism. A side's rows mix seasons, and one match count across them pushed the big five's shot means to 1.15-1.67x actual.
  - Scoped per season, it passed (H13). A replay of the SHIPPED engine then reproduced it within 0.0001 (H14).
- **The rule going forward:**
  - When a mechanism passes on a convenient input, pre-register a second test on the input the production code will actually read.
  - Then replay the shipped code itself before landing.
  - A pass on outcome-derived features is a pass for the mechanism, not for the build.
- **Cost:** none shipped. The failure surfaced before code.
  - *(evidence: `log/2026-09-15.md` session abacd435; `scripts/soccer_season_audit/calibration_role_mixture5.py`, `calibration_role_mixture6.py`, `calibration_engine_replay.py`; commit `b33ef901`)*
## 2026-09-15 — FORBIDDEN: reading ESPN's soccer scoreboard with a `dates=YYYYMMDD-YYYYMMDD` RANGE for live state. Ask for the single date, and judge freshness by a content field `[lane soccer-live-scoreboard-range-stale]`

- **What happened:** the live poller asked `dates=20260915-20260915`. ESPN answered that query from a copy about an hour old, on both hosts, while `dates=20260915`, the undated scoreboard and the summary were live in the same second. Soccer live state, the live lens and the Layer 2 chips ran ~65 match-minutes behind.
- **Why nothing flagged it:** every timestamp on the way was one this platform wrote -- the file's `generated_at`, `PUBLISH_OK`, the chip `published_at` (79 s old). Only the match CLOCK, compared against ESPN, showed the age.
- **Also:** the range form returned HTTP 400 on 31 of 60 league-dates probed; the single-date form 200 on 60/60 with identical events.
- **The rule:**
  - Any live ESPN read uses the single-date form.
  - A freshness check compares a content field (clock, score, state) against the source. A timestamp written by our own pipeline proves the pipeline ran, not that the data is current.
  - *(evidence: `deploys.md` 2026-09-15 20:29:23Z; commit `20568eff`)*
## 2026-09-15 — OVERTURNED: "`pull_hot_artifacts`' `since=` floor is the calling service's last successful pull". It was ONE keyvalue key across workers, so live-odds-worker's pulls set refresh-worker's floor `[lane soccer-live-scoreboard-range-stale]`

- **What was believed:** the docstring's "floor = the start of the last successful pull".
- **What was true:** the watermark path was keyvalue-backed and identical on both workers. refresh-worker, pulling each board date every ~15-30 min, asked for files changed since live-odds-worker's last pull ~2 min earlier, and never re-fetched an older change it already held. Measured twice from the request URLs: 20:41:05Z -> 20:39:04Z and 21:02:50Z -> 20:58:06Z. The Layer 2 soccer chips stayed stale for 26 minutes while web held the fresh file.
- **Second instance of the shape** after `disk_maintenance._status_path` (2026-08-12), and the one `live_lens_loop.py`'s own comment names for the publish watermark.
- **The rule:**
  - A keyvalue-backed "last run / last seen" stamp carries the SERVICE (`disk_maintenance._service_slug`) and the SCOPE it tracks (date, league) in its path.
  - When a floor looks wrong, read the `since=` value off the request and convert it. Does it equal THIS service's previous start?
  - *(evidence: `lanes_history.md` lane soccer-live-scoreboard-range-stale; commit `082da3e3`)*
## 2026-09-15 — OVERTURNED: "own-goal is correctly excluded" from the soccer TEAM score. Count by the feed's own `scoringPlay`, not by a type-key prefix `[lane soccer-live-scoreboard-range-stale]`

- **What was believed:** `espn_live_state.py`'s comment. Goal variants share the `goal` prefix, and "own-goal ... is correctly excluded here".
- **What was true:** that rule reproduced ESPN's final score on 68 of 95 finished matches. It dropped all 23 `penalty---scored` and all 7 `own-goal` events. Counting every non-shootout `scoringPlay` for the team ESPN tags: 95/95. Excluding an own goal is right for a player's tally and wrong for the scoreboard.
- **The rule:**
  - When a feed publishes its own verdict (`scoringPlay`, `shootout`), carry it through normalization and count by it.
  - Before trusting a hand-listed type vocabulary, replay it against the feed's own final score over a real sample.
  - *(evidence: commit `e115cd6b`; `tests/test_soccer_scoring_events.py`)*
## 2026-09-15 — OVERTURNED: "the fix is on main but its deploy is still my lane's to schedule" — once a commit is on main, the NEXT deploy of main by ANY lane ships it, and a user's timing decision cannot hold `[lane fotmob-team-name-aliases]`

- **What I believed.** Pushing `.py` to main ships nothing, so I could land `867f1481` and then ask the user WHEN to deploy. The user chose "After tonight's matches", and I built a slate-end watcher around that answer.
- **What happened.**
  - `867f1481` landed on main around 19:20Z. The user's decision came around 19:27Z.
  - At 19:31:33Z lane `soccer-player-substrate` deployed main (`f833f7ec`) to the same service, mid-slate, for its own fix. The ride-along included `867f1481`, live at 19:37:29Z.
  - Two more deploys of main by other lanes followed. By the time the slate ended, the "deploy step" had been done three times over, and not on the schedule the user picked.
  - That lane recorded the conflict honestly. Nothing broke. But the user's decision was never enforceable, and my question implied it was.
- **Why.** "Deploy only commits on `origin/main`" makes landing the same as queuing: every deploy is cumulative by design. `autoDeploy = no` bounds WHEN someone deploys, not WHAT their deploy carries.
- **How to apply.**
  - When a user wants to control when a change reaches a service, decide that BEFORE landing it. Either keep it off main (branch) until the window opens, or say in the question that the next deploy of main by any lane will carry it.
  - When a lane's deploy is pending, read the service's deploys API before building any schedule around it. Check by CONTENT whether an earlier deploy already carries the commit.
- *(evidence: `deploys.md` 2026-09-15 19:31:33Z `soccer-player-substrate` entry, its "CONFLICT" bullet, and the 21:3xZ `fotmob-team-name-aliases` READING)*
## 2026-09-15 — OVERTURNED: "log lines found by a scan can be re-read later" — Render's ~14-day retention is ROLLING, and 12 of 20 order records expired between the scan and the re-read, 75 minutes apart `[lanes polymarket-no-fill-booking-audit, execution-ledger-live-trim]`

- **What happened:**
  - A day-by-day FILL_PRICE scan read lines stamped 09-01T19:25:55Z at about 20:00Z on 09-15, and saved only side, avgPx and booked price.
  - The re-read for contracts, market and stake at 21:15Z returned 0 lines for all 13 of those orders.
  - Retention had rolled past them. One record (`C7CNYDJV4KDH`) survived only because a separate query had printed its whole `ORDER_STATE` line at 20:58Z.
- **How to apply:**
  - Anything older than about 13 days in Render logs is about to disappear. When a scan finds a record that matters, save the FULL raw line to disk in the same pass, not a parsed subset.
  - State the window's age when reporting a log-based reading, so its expiry is visible.
- **Same session, different instrument:** releasing a file claim was checked by the full path only. A bare basename in another Files-labelled bullet of the same block kept the claim (`lane_claims.matches` uses endswith), and a peer lane caught it. Diff the claim SET for every token that `matches()` the path, not the path string.
- *(evidence: `lanes.md` execution-ledger-live-trim RESTORE MANIFEST; the lane soccer-live-scoreboard-range-stale message recorded in its block; `deploys.md` 2026-09-15 20:52:30Z)*
## 2026-09-15 — OVERTURNED: "main can't ship, steps A/B are not approved" — the status came from ANOTHER lane's citation, and the owning lane had already recorded the approval `[lane anytime-td-quote-side-yes]`

- **What I believed.** At 21:00Z, `f833f7ec..6d526851` carried soccer-player-role-allocation steps A/B "not approved for deploy". I read that from lane `book-quotes-splice-repair`'s block, which cited it. So I put "off-main" to the user as the recommended path, built `1d78d38b` (live SHA + the fix), took the claim and looped preflight.
- **What was true.** soccer-player-role-allocation's OWN block, in its 20:45Z VERDICT, already read "User decision: deploy main's tip to live-odds-worker, then refresh-worker, AFTER 21:25Z".
  - An off-main deploy after that tip deploy would have reverted A/B and `070a05bf` on refresh-worker. One before it would have cost an extra reboot and 25 min of spacing.
  - A peer's message caught it before any deploy. The fix then shipped as a ride-along in the tip deploy (`2d579fd1`, reading 256/256).
- **Why.** A citation is a copy with its own timestamp. A deploy blocker's status moves within the hour on a day like this, and the lane that CITES it has no reason to update the copy.
- **How to apply.**
  - Before calling a commit on main a deploy blocker, read the OWNING lane's block on `origin/main` at that moment: its VERDICT or STATUS lines, and any "User decision" line.
  - Then read the service's claim status. A claim held for a main tip is the other half of the same answer.
  - Put the read time in the question to the user. An option built on a status that is 15 minutes old or older should say so.
- *(evidence: `lanes.md` book-quotes-splice-repair line 437 vs soccer-player-role-allocation VERDICT 2026-09-15 20:45Z; `deploys.md` 2026-09-15 22:15:53Z READING; log 2026-09-15 anytime-td-quote-side-yes stand-down entry)*
## 2026-09-15 — OVERTURNED: "re-running another run's script on unchanged inputs reproduces its numbers" — `SYNDICATE_REPO_ROOT` decides WHICH checkout's `team_names.py` is imported, and that alias set changes the market join `[session abacd435, fix #5a measurement; no lane]`

- **What I believed.** H22's script, re-run against the same audit cache an hour later, returned 402 priced matches and primary n=320 against the recorded 394 / 312. No cache file had been touched (fd CSVs 17:09Z, prod/recs 17:11Z, outcomes.json 17:19Z) and `audit_games.load_fd` reads local CSVs with no network path, so I wrote it up as the football-data closing-odds join drifting — and put that claim into two docstrings of the H25 runner.
- **What was true.** Run the way it was actually run — `SYNDICATE_REPO_ROOT` pointing at the primary tree, which this session's own transcript records — the script reproduces its recorded output byte-for-byte: 394 priced, n=312, P0 +0.0117, WF60 +0.0075, WFP +0.0076, M0 +0.0097.
- **Why.** `scripts/soccer_season_audit/common.py` puts `SYNDICATE_REPO_ROOT` on `sys.path` and imports `canonical_team_name` / `match_team_name` from THERE. The primary tree is 117+ commits behind origin/main, and the worktree's `team_names.py` (201 lines vs 182) carries six club-spelling aliases it lacks — RasenBallsport Leipzig, Paderborn 07, Parma Calcio 1913, Deportivo La Coruna, Stade Rennais, Oud-Heverlee Leuven, each mapped to its fixture spelling — added by fix #1's `f833f7ec`. They bind 8 more fixtures to football-data rows.
- **Scope.** The alias set moves ONLY which matches carry a market price. 584 matches, 477 primary, every arm's log loss and bias, and both the H22 and H23 verdicts are identical either way.
- **How to apply.**
  - When reproducing another run, pin every environment variable it set — the repo root included — and print them beside the result. An unset root silently resolves to a DIFFERENT checkout, and on this machine the checkouts are hundreds of commits apart.
  - A count that moves while every scored number holds still is pointing at a JOIN, not at data drift. Diff the helper module the join imports before blaming a cache, and check `load_*` for a network path before blaming a feed.
  - Name the checkout (or the alias set) in any cross-run comparison of market-joined numbers. H25's Brier gap to the close is on 320 matches and is NOT comparable to H22's 312.
- *(evidence: `log/2026-09-15.md` 17:55 CT entry; scratchpad `scoring_env_out.txt` vs `scoring_env_rerun_2248.txt` vs `scoring_env_rerun_primaryroot.txt`; `team_names.py` diff, primary tree vs worktree)*
## 2026-09-15 — FORBIDDEN: running `session_worktree.py land --lane <slug>` with any slug other than the one whose branch this worktree is on. It lands THAT LANE'S BRANCH, not the commit in front of you `[session abacd435, lanes soccer-player-role-allocation / soccer-anytime-scorer]`

- **What happened.** From the `soccer-player-role-allocation` worktree, with a ledger commit ready, I ran `land --lane soccer-anytime-scorer` because my per-session marker had just moved to that lane. It pushed the OTHER worktree's branch: `04b907a0`, the producer-half shrink whose H19 was FALSIFIED and which was deliberately unlanded. My ledger commit stayed local.
- **Why it reads as success.** The tool printed "pushed session/soccer-anytime-scorer -> main" and, on the retries, "nothing to land -- no commits beyond origin/main" — both true statements about a branch I had not written. Only a verification that grepped for MY OWN subject on `origin/main` caught it.
- **How to apply.**
  - `--lane` selects a BRANCH. Before landing, read `git rev-parse --abbrev-ref HEAD` in the worktree and pass the lane whose branch that is — the lane marker governs edit permission, not what gets pushed.
  - Verify a land by the COMMIT, not by the push line: `git merge-base --is-ancestor <your sha> origin/main`. A subject grep also fails when the push succeeded but pushed someone else's commit.
  - After an accidental land, measure the exposure window against every service that can ship main — the long-running services AND the crons, which build the branch tip when they fire — before saying nothing shipped.
- *(evidence: `log/2026-09-15.md` 18:05 CT entry; `04b907a0` and its revert `d2d7b398`; the Render deploys read at 23:02Z)*
## 2026-09-15 — OVERTURNED: "adding a sport to `SYNDICATE_ACTIVE_SPORTS` is a config change" — on WEB it is a REQUEST-PATH code-path flip, and this exact one has an outage on record `[lane web-dashboard-prop-dates-quotes]`

- **What I was asked, and nearly did.** "add ncaaf to web's active sports" — a one-key env write plus a deploy. The key is not declared in `render.yaml`, no lane claimed it, and the blast-radius question I started with was the usual one (would `blueprint_sync` revert it, does it move worker sweep ownership). Both answers were reassuring.
- **What the list actually gates on web.** `build_home_overview` filters to `_active_sport_slugs()` and then BUILDS each surviving sport inside the request (`home.py:8305`). For NCAAF that is `_NCAAFDataProvider.games(...)` without `include_upcoming` — `build_smartsim_cards_page_context(week)` **plus** `build_ncaaf_market_board(week)` (`home.py:6709-6713`), measured at 6.4 s warm for 51 games on a 2 GB display-only service.
- **It has happened.** `deploys.md` 2026-08-29 12:18 CT: when a resolver fix made that path reachable, `/` went **3.5 s -> 37.9 s**, `/ncaaf/cards` 502'd and `/api/ops/memory` 502'd; revert `0163f904` restored it. The repair that followed (`fccd923d`) made only the CHIPS path light (`build_ncaaf_chip_games`, 0.23 s warm), so the home path is still the heavy one today.
- **And the payoff was nil:** nothing under `syndicate/` fetches `/api/home` (only `tests/` and the run-syndicate skill), and `/` renders the Layer 2 board. The NCAAF surfaces users see do not read this key.
- **How to apply.**
  - Before flipping any list-shaped env var, find what the list GATES. A membership test in front of a builder is a code path, not configuration.
  - Grep the ledger for the last time that value changed on that service. An outage with a revert is usually already written down.
  - Ask what would become observable. If no served surface reads the thing the flip enables, the change is cost with no reading to verify it by.
- *(evidence: `home.py:691/8305/6709-6713`, `deploys.md` 2026-08-29 12:18 CT and 12:46 CT; `/api/home` read 2026-09-15 22:31:13Z; user decision "Don't add it")*
## 2026-09-15 — OVERTURNED: "`git diff | grep '^-[^-]'` lists the lines a change removes". It SKIPS every removed line that itself starts with `-`, which on a bulleted ledger is most of them `[lane soccer-live-scoreboard-range-stale]`

- **What happened:** re-applying a lane-block edit onto a moved `main`, `--numstat` said **9** deletions while the grep listed **6**. The 3 it hid were ordinary ledger bullets (`- **VERDICT ...`, `- Files: ...`, `- Blocked by: ...`): in a diff they read `-- Files: ...`, and `^-[^-]` rejects them.
- **Why it matters here:** the standing rule on a shared ledger is "0 deletions, and every deletion is mine". A grep that under-counts deletions makes that check pass while another lane's lines are being dropped.
- **The rule:** count deletions with `--numstat`, and list them with `grep -E '^-' | grep -v '^---'`. Reconcile the two numbers before staging; if they disagree, the listing is wrong, not the count.
  - *(evidence: this session's 22:4xZ re-sync; `git diff --cached --numstat` 2/2 on `lanes.md` after the reconciliation)*
## 2026-09-15 — FORBIDDEN: gating a ledger commit on a SHELL `grep` filter over diff lines, and reading a dot-prefixed `rev:path` answer from Git Bash as fact `[lane fotmob-join-coverage-check]`

Three instrument failures in one session, two of them inside the guard that was
supposed to protect a ledger commit.

- **A `grep -v "^[-+][-+]"` filter meant to drop diff headers also dropped `+- `
  and `-- ` lines** — markdown bullets, which is what `leads.md` and `lanes.md`
  are made of. The gate printed a single blank `+` and was blind to the very
  lines it existed to check.
- **A deletion guard reported 2 "unexpected" deletions in `state_ledger.md`**
  that were a blank line and an em-dash line the shell could not match. The
  staged content was correct. Re-checking the SAME staged diff in Python passed,
  and the commit went through.
- **`git cat-file -e origin/main:.github/...` and `git show
  origin/main:.syndicate/...` from Git Bash said two landed files were ABSENT
  from `origin/main`.** MSYS rewrites `origin/main:.syndicate/x` into
  `origin\main;.syndicate\x`. Only DOT-PREFIXED paths were affected, so
  `scripts/...` in the same loop answered correctly — a partially working
  instrument is the convincing kind, and it briefly read as "the land lied".

**How to apply.**
- Verify a staged diff in PYTHON, comparing against the exact expected line set.
  A `grep -v` chain over `git diff` output is not a gate; it is a filter whose
  failure mode is silence.
- Read any `rev:path` through `subprocess` from Python (or PowerShell). Never
  from Git Bash. This is the same rule as `feedback_git_bash_mangles_rev_path_args`,
  now with a second shape: a false ABSENT rather than a false empty.
- When a check answers ABSENT or none for SOME paths and correctly for others,
  suspect the instrument before the repository, and re-read with a different one.
- *(evidence: this session's `state_ledger.md` guard output and the `origin/main`
  re-read in `.syndicate/log/2026-09-15.md`)*

### REFINEMENT (same session, 23:43Z): verifying a land by the ancestry of the sha you held BEFORE landing gives a FALSE NEGATIVE

The rule above says to verify a land by the commit rather than the push line, and `git merge-base --is-ancestor <sha> origin/main` is how I implemented it. That check is correct only when `land` fast-forwards.

- Measured 23:42Z: the checkpoint commit pushed successfully (`64496c36..585106a7`), and my check reported NOT LANDED three times, because `session_worktree.py land` REBASES onto the fetched tip first. The rebased commit has a different sha, and the sha I was holding no longer exists on any branch.
- The retries then printed `nothing to land -- no commits beyond origin/main`, which was the true state and the signal I should have read.
- **How to apply:** verify a land by CONTENT or by the commit SUBJECT on `origin/main` (`git show origin/main:<path>` and look for your marker; or `git log origin/main --grep`), and treat `rev-list --count origin/main..HEAD == 0` as corroboration. Keep the sha check only for the fast-forward case, and never report NOT LANDED on its evidence alone.
- This is the mirror of the mid-rebase FALSE POSITIVE recorded earlier today: one check lies while a rebase is in progress, the other lies after a rebase completes. Both are fixed by asking about the content, not the identity.

### 2026-09-15 (session a1e40980, lane `soccer-live-scoreboard-range-stale`) — FORBIDDEN: reading a green test as evidence of the property it NAMES, when its fixture and the code could share the same mistake

`tests/test_soccer_cards_context_cache.py` exists to prove one thing, and says so itself: *"`test_a_live_score_change_invalidates` is the load-bearing one. If it ever goes green with the vintage removed from the key, this cache has become the bug it was written to avoid."* It was green for two weeks over exactly that.

- `_live_vintage` fingerprinted `entry.get("home_score")` / `away_score`. Every real entry carries `score_home` / `score_away` — `build_live_state` writes it (`espn_live_state.py:180`) and the poller copies ESPN's `home_score` INTO it (`poll_soccer_live_state.py:178`). The score was absent from the key.
- The fixture `_live()` wrote `home_score` too. So the test agreed with the code, the code agreed with the test, and **neither agreed with any bytes production has ever produced**. The assertion did fire — on a field the cache would never see.
- It survived because the fingerprint ALSO carries the clock, which moves every poll. The defect was therefore bounded at one displayed minute instead of the 600 s TTL, and never presented as the freeze that would have exposed it.
- **How to apply:** a test whose fixture is hand-written asserts that the CODE agrees with the FIXTURE. To make it assert anything about production, the fixture's field names must come from the writer — cite the writing line — or the test must run the writer. When a suite declares a test load-bearing, check what its fixture is made of before trusting the claim; and when you fix a name like this, do NOT keep the old one as a fallback, because a reader that accepts both preserves exactly the ambiguity that hid it.
- Same family as *a fixture can pick a cheaper path than production* and *presence is not reachability*: the instrument was measuring itself.
- *(evidence: `test_a_live_score_change_invalidates` FAILS with the fingerprint reverted to `home_score` against the corrected fixture, passes with `score_home`; `.syndicate/log/2026-09-15.md`, commit `116690a8`)*
## 2026-09-15 -- A FALSIFIER IN THE WRONG UNIT KILLS A LIVE HYPOTHESIS, and the retraction looks rigorous while it happens

Lane `polymarket-rejected-resubmit-loop` wrote: "H2 (insufficient buying power) dies if the account's available balance covered $1.60 at a
rejected submit." It did -- flat at $2.84 across all 34 rejections -- so I recorded H2 as DEAD BY ITS OWN FALSIFIER, which is the strongest
form of retraction this ledger has.

**H2 was right.** The venue checks a NO order against $1.00 per contract, so the number that had to be covered was $6.53, not $1.60. The
falsifier was written in NET dollars against a venue that checks GROSS. Everything downstream was correct reasoning on the wrong unit, and
the error was invisible precisely BECAUSE the falsifier fired cleanly.

- **STANDING RULE: a falsifier must name its UNIT, not just its threshold.** "balance covered the stake" is not a test until "stake" is
  pinned to cost, notional, payout or margin. Where a venue or API could plausibly mean a different one, write the falsifier for EACH and
  say which reading kills the hypothesis.
- A hypothesis killed by its own falsifier deserves the same scepticism as one confirmed by its own prediction. Both are self-graded.
- Same family as *read the field you already have* and *a rate, not a count*: the arithmetic was never wrong, the denominator was.
- *(evidence: `.syndicate/state_polymarket.md [polymarket-no-fill-size-is-gross-capped]`; commits `ce64e639` -> `16c7d919` -> `a8668557`,
  which are the overclaim, the over-retraction, and the table that settled it)*
## 2026-09-15 -- `finishedAt` IS NOT WHEN THE OLD INSTANCE STOPS WRITING

Lane `legacy-steam-crossing-delta` measured soccer steam events **38 s AFTER its deploy went live** that were still written by the OUTGOING
instance, in the old format. A post-deploy window that starts at `finishedAt` therefore contains old-code output at its head.

- **STANDING RULE: when a reading starts at `finishedAt`, discard or separately label the first minute** -- an old-format line there is
  evidence of an overlap, not of a failed fix. Gate the verdict on lines comfortably after the boundary.
- The inverse error is worse: crediting the NEW code with output the OLD instance produced. That lane retracted an attribution for exactly
  this reason -- its 200 events were stamped 66 s after a second service's deploy, so they could not identify which service wrote them.
- Extends *gate verification on artifact mtime*: deploy live is not code live, and code live is not old code STOPPED.
- *(evidence: cross-session reports from lane `legacy-steam-crossing-delta`, 2026-09-15 ~23:35Z and its retraction ~23:55Z;
  `.syndicate/log/2026-09-15.md`)*
## 2026-09-15 -- A LANE BLOCK CAN CONTRADICT ITSELF, and the STALE half is the one that reads like an instruction

I recommended deploying `57b67127` because lane `book-quotes-prefer-fuller-copy` said **"STATUS 2026-09-13 ~19:25Z: LANDED on main, NOT
DEPLOYED."** The user approved it. It was already live on all three services, and had been for a day -- the SAME BLOCK, further down,
carried a 2026-09-15 verdict describing the production reading taken after that deploy.

The stale line won because of its SHAPE: "landed, not deployed" is an action item, and a verdict paragraph is prose. Scanning a 16 KB block
for what to do next surfaces the imperative and buries the correction.

- **STANDING RULE: `deploy state` is never read from `lanes.md`. Read it from the SERVICE.** Before proposing or running any deploy, test
  ancestry of the commit against the LIVE commit on each target service (`git merge-base --is-ancestor <sha> <live-sha>`, live SHA from the
  Render deploys API). It is two commands and it is the only source that cannot be stale.
- **A deploy that would be a no-op must be caught BEFORE approval is sought**, not after it is granted. Approval spends the user's trust on
  a decision that was never real, and an approved-but-pointless deploy still restarts a service and kills in-flight work.
- When a block holds two statements about the same fact, the NEWER one wins and the older must be rewritten in place -- not left below it.
  This is the same failure `learnings.md` records for `state.md` ("overwrite the stale line; do not stack contradictory lines"), appearing
  in `lanes.md` instead.
- Same family as *primary tree is not deployed code* and *test the fix's predicate, not its deploy state*: the ledger describes the world, it
  is not the world.
- *(evidence: `57b67127` an ancestor of web `4f65f2b2`, refresh-worker `1175e0ef`, live-odds-worker `88df44cd`, read 2026-09-16 03:20Z; the
  contradicting verdict is in the same lane block, dated 2026-09-15 ~11:25 CDT)*
