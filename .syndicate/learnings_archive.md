# Syndicate — Learnings ARCHIVE (entries before 2026-08-20)

> Moved verbatim from `learnings.md` on 2026-09-01 to fit its size budget.
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
