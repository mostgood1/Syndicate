# Syndicate — Learnings

> **Append only.** Rules must be obeyable by a session with zero context.
> `FORBIDDEN` = never do this again. `EXONERATED` = ruled out, stop
> re-investigating.


<!-- LEARNINGS-INDEX:START -->

## Index — 82 rules `[generated]`

> Regenerate with `py -3 scripts/build_learnings_index.py` after appending.
> This block is the ONLY part of this file that is rewritten; rule bodies
> are append-only and are never touched. **FORBIDDEN** = never do this
> again. **EXONERATED** = ruled out, stop re-investigating.

**FORBIDDEN — 5**

- [2026-08-12 — FORBIDDEN: never point a worker publish URL at a public hostname](#2026-08-12-forbidden-never-point-a-worker-publish-url-at-a-public-hostname)
- [2026-08-13 — FORBIDDEN: never `cat` a ledger file into hook stdout — a hook delivers the obligation, not the content](#2026-08-13-forbidden-never-cat-a-ledger-file-into-hook-stdout-a-hook-delivers-the-obligation-not-the-content)
- [2026-08-13 — FORBIDDEN: never edit a file from a read taken earlier in the session](#2026-08-13-forbidden-never-edit-a-file-from-a-read-taken-earlier-in-the-session)
- [2026-08-15 — FORBIDDEN: never conclude "no OOM" from a LOG search. Kills are EVENTS, and I had this rule already](#2026-08-15-forbidden-never-conclude-no-oom-from-a-log-search-kills-are-events-and-i-had-this-rule-already)
- [2026-08-15 — FORBIDDEN: never run a heavyweight census ON the thread that is doing the measuring](#2026-08-15-forbidden-never-run-a-heavyweight-census-on-the-thread-that-is-doing-the-measuring)

**EXONERATED — 3**

- [2026-08-12 — EXONERATED: the soccer window is not the egress cause](#2026-08-12-exonerated-the-soccer-window-is-not-the-egress-cause)
- [2026-08-13 — EXONERATED: `shell: "bash"` in a Windows hooks block works](#2026-08-13-exonerated-shell-bash-in-a-windows-hooks-block-works)
- [2026-08-15 — EXONERATED: "eight hydrated sports at once cannot fit in 4GiB"](#2026-08-15-exonerated-eight-hydrated-sports-at-once-cannot-fit-in-4gib)

**Rules and corrections — 74**

- [2026-08-12 — Do not batch changes during a diagnosis](#2026-08-12-do-not-batch-changes-during-a-diagnosis)
- [2026-08-12 — A rate ceiling is not a fix](#2026-08-12-a-rate-ceiling-is-not-a-fix)
- [2026-08-12 — Parallel sessions on one problem need lane discipline](#2026-08-12-parallel-sessions-on-one-problem-need-lane-discipline)
- [2026-08-13 — A guard can measure a number that moves without the system moving](#2026-08-13-a-guard-can-measure-a-number-that-moves-without-the-system-moving)
- [2026-08-13 — A criterion has a DIRECTION, and checking it is free](#2026-08-13-a-criterion-has-a-direction-and-checking-it-is-free)
- [2026-08-13 — A grep excerpt is not the file](#2026-08-13-a-grep-excerpt-is-not-the-file)
- [2026-08-13 — Confirm an instrument can emit non-zero before believing its zero](#2026-08-13-confirm-an-instrument-can-emit-non-zero-before-believing-its-zero)
- [2026-08-13 — A pooled denominator can make a measurement unreadable](#2026-08-13-a-pooled-denominator-can-make-a-measurement-unreadable)
- [2026-08-13 — `git log --format=%an` is zero evidence in this repo](#2026-08-13-git-log---formatan-is-zero-evidence-in-this-repo)
- [2026-08-10 — a briefed premise is a hypothesis, not a starting condition](#2026-08-10-a-briefed-premise-is-a-hypothesis-not-a-starting-condition)
- [2026-08-10 — an instrument's blind spot will be mistaken for a finding](#2026-08-10-an-instruments-blind-spot-will-be-mistaken-for-a-finding)
- [2026-08-10 — segment on process boundaries before any neighbour-based test](#2026-08-10-segment-on-process-boundaries-before-any-neighbour-based-test)
- [2026-08-10 — counts are the wrong denominator when the cost is bytes](#2026-08-10-counts-are-the-wrong-denominator-when-the-cost-is-bytes)
- [2026-08-13 — Presence is not reachability: verify the PATH, not the symbol](#2026-08-13-presence-is-not-reachability-verify-the-path-not-the-symbol)
- [2026-08-13 — A safety gate answers ITS question, not the one you were asked](#2026-08-13-a-safety-gate-answers-its-question-not-the-one-you-were-asked)
- [2026-08-13 — "Identical to origin" does not mean "absent from the commit"](#2026-08-13-identical-to-origin-does-not-mean-absent-from-the-commit)
- [2026-08-13 — "Who reads this env var" is a grep question; "does this service read it" is not](#2026-08-13-who-reads-this-env-var-is-a-grep-question-does-this-service-read-it-is-not)
- [2026-08-13 — A guard that has never once PASSED is not a guard](#2026-08-13-a-guard-that-has-never-once-passed-is-not-a-guard)
- [2026-08-13 — A discriminator that is only emitted on FAILURE cannot confirm a fix](#2026-08-13-a-discriminator-that-is-only-emitted-on-failure-cannot-confirm-a-fix)
- [2026-08-13 — A watcher's headline can contradict its own body](#2026-08-13-a-watchers-headline-can-contradict-its-own-body)
- [2026-08-13 — A guard's "is this mine" input must not default to the locked state](#2026-08-13-a-guards-is-this-mine-input-must-not-default-to-the-locked-state)
- [2026-08-13 — A path one toolchain resolves and another cannot makes a guard pass silently](#2026-08-13-a-path-one-toolchain-resolves-and-another-cannot-makes-a-guard-pass-silently)
- [2026-08-13 — A free-text status field cannot be a predicate; test guards against the ledger, not against synthetics](#2026-08-13-a-free-text-status-field-cannot-be-a-predicate-test-guards-against-the-ledger-not-against-synthetics)
- [2026-08-13 — A discriminator that only emits on FAILURE cannot confirm success](#2026-08-13-a-discriminator-that-only-emits-on-failure-cannot-confirm-success)
- [2026-08-13 — A watcher's LABEL must be entailed by its exit CONDITION](#2026-08-13-a-watchers-label-must-be-entailed-by-its-exit-condition)
- [2026-08-13 — "Pushed to origin" is not "applied to production"](#2026-08-13-pushed-to-origin-is-not-applied-to-production)
- [2026-08-13 — The enforcement layer cannot protect itself, and a lane is one deletable line](#2026-08-13-the-enforcement-layer-cannot-protect-itself-and-a-lane-is-one-deletable-line)
- [2026-08-13 — A FAILED READ RENDERS AS A RESULT. Five instances, one session, five different tools](#2026-08-13-a-failed-read-renders-as-a-result-five-instances-one-session-five-different-tools)
- [2026-08-13 — The stale-read rule failed on its second application, in a form it did not cover](#2026-08-13-the-stale-read-rule-failed-on-its-second-application-in-a-form-it-did-not-cover)
- [2026-08-13 — A guard has TWO failure directions, and fixing the loud one is where the silent one survives](#2026-08-13-a-guard-has-two-failure-directions-and-fixing-the-loud-one-is-where-the-silent-one-survives)
- [2026-08-13 — Cite the SHA that will exist on origin, not the one your clone minted](#2026-08-13-cite-the-sha-that-will-exist-on-origin-not-the-one-your-clone-minted)
- [2026-08-13 — MY OWN DISPLAY TRUNCATION BECAME A FINDING, AND THEN A LANE'S PREMISE](#2026-08-13-my-own-display-truncation-became-a-finding-and-then-a-lanes-premise)
- [2026-08-13 — A BROKEN GUARD CAN MASK THE REAL PROBLEM. Fixing it is how you find out](#2026-08-13-a-broken-guard-can-mask-the-real-problem-fixing-it-is-how-you-find-out)
- [2026-08-13 — Symptom relief resets the clock that would have proved the cause](#2026-08-13-symptom-relief-resets-the-clock-that-would-have-proved-the-cause)
- [2026-08-13 — Check whether the obvious fix was already tried, BEFORE building an instrument](#2026-08-13-check-whether-the-obvious-fix-was-already-tried-before-building-an-instrument)
- [2026-08-13 — I RETRACTED POINT-SAMPLING, THEN BUILT A HEADLINE ON IT ANYWAY](#2026-08-13-i-retracted-point-sampling-then-built-a-headline-on-it-anyway)
- [2026-08-13 — A habit that fails silently needs a tool, not more care](#2026-08-13-a-habit-that-fails-silently-needs-a-tool-not-more-care)
- [2026-08-14 — A TROUGH THAT CLEARS AN EARLIER PEAK IS A RATCHET. That is the test](#2026-08-14-a-trough-that-clears-an-earlier-peak-is-a-ratchet-that-is-the-test)
- [2026-08-14 — I RE-READ THE DEPLOYED SHA BEFORE EVERY *READ* AND SKIPPED IT BEFORE A *WRITE*](#2026-08-14-i-re-read-the-deployed-sha-before-every-read-and-skipped-it-before-a-write)
- [2026-08-13 — A "PURE READ" endpoint is a reader you will not find by grepping the attach](#2026-08-13-a-pure-read-endpoint-is-a-reader-you-will-not-find-by-grepping-the-attach)
- [2026-08-13 — A CONSTANT that reproduces exactly is a data outage, not a weak model](#2026-08-13-a-constant-that-reproduces-exactly-is-a-data-outage-not-a-weak-model)
- [2026-08-13 — A FIXTURE THAT OMITS A MARKER FILE TESTS A DIFFERENT DIRECTORY, AND SCORES IT AS A DEFECT](#2026-08-13-a-fixture-that-omits-a-marker-file-tests-a-different-directory-and-scores-it-as-a-defect)
- [2026-08-13 — CLOSING A TICKET IS A SCOPE DECISION, AND WHOLESALE CLOSURE SILENTLY RETIRES THE PART NOBODY WORKED](#2026-08-13-closing-a-ticket-is-a-scope-decision-and-wholesale-closure-silently-retires-the-part-nobody-worked)
- [2026-08-14 — A PLATEAU IS A STRONGER SIGNAL THAN A PERCENTAGE](#2026-08-14-a-plateau-is-a-stronger-signal-than-a-percentage)
- [2026-08-14 — I MEASURED A STAGE WITHOUT THE THING THAT DOMINATES IT, AND ALMOST SHIPPED THE FIX](#2026-08-14-i-measured-a-stage-without-the-thing-that-dominates-it-and-almost-shipped-the-fix)
- [2026-08-14 — A guard's floor is a claim about ONE stage; refusing everything downstream of it is a separate bug](#2026-08-14-a-guards-floor-is-a-claim-about-one-stage-refusing-everything-downstream-of-it-is-a-separate-bug)
- [2026-08-14 — A CADENCE IS NOT AN OUTAGE, AND I ESCALATED ONE AS THE OTHER](#2026-08-14-a-cadence-is-not-an-outage-and-i-escalated-one-as-the-other)
- [2026-08-14 — A CONSTANT THAT REPRODUCES EXACTLY FROM AN EMPTY INPUT IS A DATA OUTAGE, NOT A WEAK MODEL](#2026-08-14-a-constant-that-reproduces-exactly-from-an-empty-input-is-a-data-outage-not-a-weak-model)
- [2026-08-14 — A LANE LEFT OPEN AFTER ITS WORK SHIPS IS AN ACTIVE LOCK, NOT A STALE NOTE](#2026-08-14-a-lane-left-open-after-its-work-ships-is-an-active-lock-not-a-stale-note)
- [2026-08-14 — `git add <paths>` SCOPES THE INDEX; ONLY A PATHSPEC ON `commit` SCOPES THE COMMIT](#2026-08-14-git-add-paths-scopes-the-index-only-a-pathspec-on-commit-scopes-the-commit)
- [2026-08-14 — DECOMPOSE BIAS BEFORE PUBLISHING A SKILL VERDICT](#2026-08-14-decompose-bias-before-publishing-a-skill-verdict)
- [2026-08-14 — A GUARD MUST COUNT THE ROWS THE STATISTIC USES, NOT THE ROWS THE JOIN PRODUCED](#2026-08-14-a-guard-must-count-the-rows-the-statistic-uses-not-the-rows-the-join-produced)
- [2026-08-14 — THREE wrong root causes in one session, one shape: a single sample of a moving quantity](#2026-08-14-three-wrong-root-causes-in-one-session-one-shape-a-single-sample-of-a-moving-quantity)
- [2026-08-14 — I CALLED A CORRELATION A PROOF, TWICE IN ONE SESSION](#2026-08-14-i-called-a-correlation-a-proof-twice-in-one-session)
- [2026-08-14 — A HEALTHY-LOOKING SIBLING MASKED A PLATFORM-WIDE OUTAGE](#2026-08-14-a-healthy-looking-sibling-masked-a-platform-wide-outage)
- [2026-08-14 — A fallback CHAIN has a rung that fires; find it before costing the fix](#2026-08-14-a-fallback-chain-has-a-rung-that-fires-find-it-before-costing-the-fix)
- [2026-08-14 — A MANGLED SHELL ARGUMENT NEARLY BECAME "THE LEDGER LOST MY WORK"](#2026-08-14-a-mangled-shell-argument-nearly-became-the-ledger-lost-my-work)
- [2026-08-14 — A watcher that compares TIMESTAMPS to identify a thing will misidentify it by microseconds](#2026-08-14-a-watcher-that-compares-timestamps-to-identify-a-thing-will-misidentify-it-by-microseconds)
- [2026-08-14 — I PREDICTED FILE OWNERSHIP INSTEAD OF PROBING IT, TWICE](#2026-08-14-i-predicted-file-ownership-instead-of-probing-it-twice)
- [2026-08-14 — PINNED DEPLOYS PUT CODE IN PRODUCTION THAT WAS NEVER ON MAIN](#2026-08-14-pinned-deploys-put-code-in-production-that-was-never-on-main)
- [2026-08-14 — Separating `add` from `commit` is not enough if you chain them with `&&`](#2026-08-14-separating-add-from-commit-is-not-enough-if-you-chain-them-with)
- [2026-08-14 — A saturated log window proves nothing, and the untouched sibling is the control](#2026-08-14-a-saturated-log-window-proves-nothing-and-the-untouched-sibling-is-the-control)
- [2026-08-14 — A regex over a hand-written ledger inverts "NOT claimed" into "claimed"](#2026-08-14-a-regex-over-a-hand-written-ledger-inverts-not-claimed-into-claimed)
- [2026-08-14 — An audit's CAUSAL claim is a hypothesis; its MEASUREMENT is evidence](#2026-08-14-an-audits-causal-claim-is-a-hypothesis-its-measurement-is-evidence)
- [2026-08-14 — A COUNT can rise because the population grew, not because the property got worse](#2026-08-14-a-count-can-rise-because-the-population-grew-not-because-the-property-got-worse)
- [2026-08-14 — An audit brief's "known already" inputs are claims, not axioms](#2026-08-14-an-audit-briefs-known-already-inputs-are-claims-not-axioms)
- [2026-08-14 — the Render logs API returns the NEWEST N in a window; paging forward silently reports a peak over a sliver](#2026-08-14-the-render-logs-api-returns-the-newest-n-in-a-window-paging-forward-silently-reports-a-peak-over-a-sliver)
- [2026-08-14 — a before/after is void if the change moved work INSIDE the measured span](#2026-08-14-a-beforeafter-is-void-if-the-change-moved-work-inside-the-measured-span)
- [2026-08-14 — "it cannot fit" from one sample, when the same shape runs fine twice](#2026-08-14-it-cannot-fit-from-one-sample-when-the-same-shape-runs-fine-twice)
- [2026-08-15 — a threshold is calibrated against a SPAN; changing what the span contains invalidates it without touching the constant](#2026-08-15-a-threshold-is-calibrated-against-a-span-changing-what-the-span-contains-invalidates-it-without-touching-the-constant)
- [2026-08-15 — the kill is MLB game hydration in pid 39, not the overview pass](#2026-08-15-the-kill-is-mlb-game-hydration-in-pid-39-not-the-overview-pass)
- [2026-08-15 — Pinned deploys do not merge; they REPLACE, so they have to be stacked](#2026-08-15-pinned-deploys-do-not-merge-they-replace-so-they-have-to-be-stacked)
- [2026-08-15 — The lane marker is repo-global, so only one session can hold it](#2026-08-15-the-lane-marker-is-repo-global-so-only-one-session-can-hold-it)
- [2026-08-15 — a fix on `main` is not a fix in production: check the DEPLOYED tree](#2026-08-15-a-fix-on-main-is-not-a-fix-in-production-check-the-deployed-tree)

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
