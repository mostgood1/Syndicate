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

## Index — 147 rules `[generated]`

> Regenerate with `py -3 scripts/build_learnings_index.py` after appending.
> This block is the ONLY part of this file that is rewritten; rule bodies
> are append-only and are never touched. **FORBIDDEN** = never do this
> again. **EXONERATED** = ruled out, stop re-investigating.

**FORBIDDEN — 13**

- [2026-08-15 — FORBIDDEN: never conclude "no OOM" from a LOG search. Kills are EVENTS, and I had this rule already](#2026-08-15-forbidden-never-conclude-no-oom-from-a-log-search-kills-are-events-and-i-had-this-rule-already)
- [2026-08-15 — FORBIDDEN: never run a heavyweight census ON the thread that is doing the measuring](#2026-08-15-forbidden-never-run-a-heavyweight-census-on-the-thread-that-is-doing-the-measuring)
- [2026-08-15 — FORBIDDEN: never put `$$` (or any per-shell value) in `GIT_INDEX_FILE`. Each Bash call is a NEW shell, and an absent index file is an EMPTY one, not an error](#2026-08-15-forbidden-never-put-or-any-per-shell-value-in-git_index_file-each-bash-call-is-a-new-shell-and-an-absent-index-file-is-an-empty-one-not-an-error)
- [2026-08-12 — FORBIDDEN: never point a worker publish URL at a public hostname](#2026-08-12-forbidden-never-point-a-worker-publish-url-at-a-public-hostname)
- [2026-08-13 — FORBIDDEN: never `cat` a ledger file into hook stdout — a hook delivers the obligation, not the content](#2026-08-13-forbidden-never-cat-a-ledger-file-into-hook-stdout-a-hook-delivers-the-obligation-not-the-content)
- [2026-08-13 — FORBIDDEN: never edit a file from a read taken earlier in the session](#2026-08-13-forbidden-never-edit-a-file-from-a-read-taken-earlier-in-the-session)
- [2026-08-15 — FORBIDDEN: never trust a CLEAR from `lane-guard.py`'s `_claims()` alone. It UNDER-reports, and that is the dangerous direction](#2026-08-15-forbidden-never-trust-a-clear-from-lane-guardpys-_claims-alone-it-under-reports-and-that-is-the-dangerous-direction)
- [2026-08-15 — FORBIDDEN: never read a background-task wrapper's `exit code 0` as "the tests passed"](#2026-08-15-forbidden-never-read-a-background-task-wrappers-exit-code-0-as-the-tests-passed)
- [2026-08-15 — FORBIDDEN: never judge a pinned deploy by ANCESTRY alone. Patch-id is the test.](#2026-08-15-forbidden-never-judge-a-pinned-deploy-by-ancestry-alone-patch-id-is-the-test)
- [2026-08-15 — FORBIDDEN: never wake many idle sessions at once. It stalls them.](#2026-08-15-forbidden-never-wake-many-idle-sessions-at-once-it-stalls-them)
- [2026-08-15 — FORBIDDEN: never gate a DEPLOY with a cross-session message. It always arrives late.](#2026-08-15-forbidden-never-gate-a-deploy-with-a-cross-session-message-it-always-arrives-late)
- [2026-08-15 — FORBIDDEN: never deploy a fix without first reading WHICH SERVICE runs the code it changes. The env decides, not the repo.](#2026-08-15-forbidden-never-deploy-a-fix-without-first-reading-which-service-runs-the-code-it-changes-the-env-decides-not-the-repo)
- [2026-08-15 — FORBIDDEN: a scratch index seeded with `git read-tree HEAD` snapshots the WHOLE TREE, and `git diff --cached --numstat` cannot see it go stale](#2026-08-15-forbidden-a-scratch-index-seeded-with-git-read-tree-head-snapshots-the-whole-tree-and-git-diff---cached---numstat-cannot-see-it-go-stale)

**EXONERATED — 3**

- [2026-08-12 — EXONERATED: the soccer window is not the egress cause](#2026-08-12-exonerated-the-soccer-window-is-not-the-egress-cause)
- [2026-08-15 — EXONERATED: "eight hydrated sports at once cannot fit in 4GiB"](#2026-08-15-exonerated-eight-hydrated-sports-at-once-cannot-fit-in-4gib)
- [2026-08-13 — EXONERATED: `shell: "bash"` in a Windows hooks block works](#2026-08-13-exonerated-shell-bash-in-a-windows-hooks-block-works)

**Rules and corrections — 131**

- [2026-08-12 — Do not batch changes during a diagnosis](#2026-08-12-do-not-batch-changes-during-a-diagnosis)
- [2026-08-12 — A rate ceiling is not a fix](#2026-08-12-a-rate-ceiling-is-not-a-fix)
- [2026-08-12 — Parallel sessions on one problem need lane discipline](#2026-08-12-parallel-sessions-on-one-problem-need-lane-discipline)
- [2026-08-13 — A grep excerpt is not the file](#2026-08-13-a-grep-excerpt-is-not-the-file)
- [2026-08-10 — a briefed premise is a hypothesis, not a starting condition](#2026-08-10-a-briefed-premise-is-a-hypothesis-not-a-starting-condition)
- [2026-08-15 — a threshold is calibrated against a SPAN; changing what the span contains invalidates it without touching the constant](#2026-08-15-a-threshold-is-calibrated-against-a-span-changing-what-the-span-contains-invalidates-it-without-touching-the-constant)
- [2026-08-15 — the kill is MLB game hydration in pid 39, not the overview pass](#2026-08-15-the-kill-is-mlb-game-hydration-in-pid-39-not-the-overview-pass)
- [2026-08-15 — Pinned deploys do not merge; they REPLACE, so they have to be stacked](#2026-08-15-pinned-deploys-do-not-merge-they-replace-so-they-have-to-be-stacked)
- [2026-08-15 — The lane marker is repo-global, so only one session can hold it](#2026-08-15-the-lane-marker-is-repo-global-so-only-one-session-can-hold-it)
- [2026-08-15 — a fix on `main` is not a fix in production: check the DEPLOYED tree](#2026-08-15-a-fix-on-main-is-not-a-fix-in-production-check-the-deployed-tree)
- [2026-08-15 — A COUNT OF DEFINITIONS IS NOT A COUNT OF PRODUCERS, and the one it missed was the live bug](#2026-08-15-a-count-of-definitions-is-not-a-count-of-producers-and-the-one-it-missed-was-the-live-bug)
- [2026-08-15 — A field nobody reads is the same as the `None` it replaced](#2026-08-15-a-field-nobody-reads-is-the-same-as-the-none-it-replaced)
- [2026-08-15 — A single-slot lock in a five-session worktree blocks the RIGHT work](#2026-08-15-a-single-slot-lock-in-a-five-session-worktree-blocks-the-right-work)
- [2026-08-15 — A PER-CLASS MEASUREMENT OVER A SHARED STYLESHEET IS A PER-SURFACE MEASUREMENT, OR IT IS WRONG](#2026-08-15-a-per-class-measurement-over-a-shared-stylesheet-is-a-per-surface-measurement-or-it-is-wrong)
- [2026-08-15 — A PROBE THAT PASSES ON AN ERROR PAGE. Attach the liveness check to the SAME fetch](#2026-08-15-a-probe-that-passes-on-an-error-page-attach-the-liveness-check-to-the-same-fetch)
- [2026-08-15 — DE-DUPLICATING A FIELD IS NOT DE-DUPLICATING THE OUTPUT. Look at what the fallback renders](#2026-08-15-de-duplicating-a-field-is-not-de-duplicating-the-output-look-at-what-the-fallback-renders)
- [2026-08-15 — `GIT_INDEX_FILE` PROTECTS YOUR COMMIT AND LEAVES THE SHARED INDEX HOLDING A REVERT OF IT](#2026-08-15-git_index_file-protects-your-commit-and-leaves-the-shared-index-holding-a-revert-of-it)
- [2026-08-15 — a scoped search answers a scoped question. I shipped a field's semantics on one, and the unscoped search later named the test that guards it](#2026-08-15-a-scoped-search-answers-a-scoped-question-i-shipped-a-fields-semantics-on-one-and-the-unscoped-search-later-named-the-test-that-guards-it)
- [2026-08-15 — COMMITTING THROUGH AN ISOLATED INDEX LEAVES THE SHARED INDEX STAGING A DELETION OF THE FILE YOU JUST COMMITTED](#2026-08-15-committing-through-an-isolated-index-leaves-the-shared-index-staging-a-deletion-of-the-file-you-just-committed)
- [2026-08-15 — A DATE TEST WRITTEN IN THE FORMAT THE CODE ALREADY HANDLES CANNOT DETECT THAT IT ONLY HANDLES THAT FORMAT](#2026-08-15-a-date-test-written-in-the-format-the-code-already-handles-cannot-detect-that-it-only-handles-that-format)
- [2026-08-15 — A GUARD'S STATED REASON IS A CLAIM ABOUT ANOTHER FUNCTION, AND IT ROTS WITHOUT TOUCHING EITHER FILE](#2026-08-15-a-guards-stated-reason-is-a-claim-about-another-function-and-it-rots-without-touching-either-file)
- [2026-08-15 — I QUOTED THE "A BRANCH CUT FOR ONE SERVICE IS A ROLLBACK FOR ANOTHER" RULE, THEN BROKE IT ONE NOTE LATER](#2026-08-15-i-quoted-the-a-branch-cut-for-one-service-is-a-rollback-for-another-rule-then-broke-it-one-note-later)
- [2026-08-13 — A guard can measure a number that moves without the system moving](#2026-08-13-a-guard-can-measure-a-number-that-moves-without-the-system-moving)
- [2026-08-13 — A criterion has a DIRECTION, and checking it is free](#2026-08-13-a-criterion-has-a-direction-and-checking-it-is-free)
- [2026-08-13 — Confirm an instrument can emit non-zero before believing its zero](#2026-08-13-confirm-an-instrument-can-emit-non-zero-before-believing-its-zero)
- [2026-08-13 — A pooled denominator can make a measurement unreadable](#2026-08-13-a-pooled-denominator-can-make-a-measurement-unreadable)
- [2026-08-13 — `git log --format=%an` is zero evidence in this repo](#2026-08-13-git-log---formatan-is-zero-evidence-in-this-repo)
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
- [2026-08-15 — A BASELINE IS A MEASUREMENT, NOT A CONSTANT. Re-measure it before you judge anything against it](#2026-08-15-a-baseline-is-a-measurement-not-a-constant-re-measure-it-before-you-judge-anything-against-it)
- [2026-08-15 — A JOB THAT ONLY FLUSHES ON COMPLETION CANNOT SURVIVE A SESSION BOUNDARY, AND I LAUNCHED TWO](#2026-08-15-a-job-that-only-flushes-on-completion-cannot-survive-a-session-boundary-and-i-launched-two)
- [2026-08-15 — A COMMITTED LEDGER FACT IS NOT A DURABLE ONE. Re-read it at archive time, or the file will quietly go back to the claim you refuted](#2026-08-15-a-committed-ledger-fact-is-not-a-durable-one-re-read-it-at-archive-time-or-the-file-will-quietly-go-back-to-the-claim-you-refuted)
- [2026-08-15 — I CONFIRMED A VALUE MY CHANGE DID NOT PRODUCE. A field with two sources verifies nothing until you know which one filled it](#2026-08-15-i-confirmed-a-value-my-change-did-not-produce-a-field-with-two-sources-verifies-nothing-until-you-know-which-one-filled-it)
- [2026-08-15 — OVERTURNED: two locks with one symptom. `JOB_CAP_THROTTLED` is not the refresh run-lock, and the difference picks the remedy](#2026-08-15-overturned-two-locks-with-one-symptom-job_cap_throttled-is-not-the-refresh-run-lock-and-the-difference-picks-the-remedy)
- [2026-08-15 — A BASELINE QUOTED IN PROSE MAY CORRESPOND TO NO RUN ON DISK](#2026-08-15-a-baseline-quoted-in-prose-may-correspond-to-no-run-on-disk)
- [2026-08-15 — A CLASS NAME IS NOT A SURFACE, and `querySelector` turned that into two wrong plan items](#2026-08-15-a-class-name-is-not-a-surface-and-queryselector-turned-that-into-two-wrong-plan-items)
- [2026-08-15 — THE INSTRUMENT THAT DROPPED A MISSING KEY, AND THE CORRECTION IT HANDED ME MID-FIX](#2026-08-15-the-instrument-that-dropped-a-missing-key-and-the-correction-it-handed-me-mid-fix)
- [2026-08-15 — ON A CONTENDED LEDGER, NEITHER COPY IS AUTHORITATIVE, AND A WHOLE-FILE COMMIT PICKS A WINNER SILENTLY](#2026-08-15-on-a-contended-ledger-neither-copy-is-authoritative-and-a-whole-file-commit-picks-a-winner-silently)
- [2026-08-15 — A FIELD MOVED INTO AN UNCONDITIONAL LOOP LOSES THE CONDITION ITS NEIGHBOURS WERE GIVEN](#2026-08-15-a-field-moved-into-an-unconditional-loop-loses-the-condition-its-neighbours-were-given)
- [2026-08-15 — MY SUCCESS CRITERION CONTAINED A TERM THE BASELINE ALREADY SATISFIED, AND MY INSTRUMENT RULE INVERTED BECAUSE OF MY OWN FIX](#2026-08-15-my-success-criterion-contained-a-term-the-baseline-already-satisfied-and-my-instrument-rule-inverted-because-of-my-own-fix)
- [2026-08-15 - A PINNED DEPLOY IS NOT ON main's LINEAGE, SO ANCESTRY ANSWERS THE WRONG QUESTION](#2026-08-15---a-pinned-deploy-is-not-on-mains-lineage-so-ancestry-answers-the-wrong-question)
- [2026-08-15 - A FIXED `GIT_INDEX_FILE` NAME COLLIDES ACROSS SESSIONS, AND A FAILED read-tree LEAVES AN EMPTY INDEX THAT STAGES THE WHOLE REPO AS DELETIONS](#2026-08-15---a-fixed-git_index_file-name-collides-across-sessions-and-a-failed-read-tree-leaves-an-empty-index-that-stages-the-whole-repo-as-deletions)
- [2026-08-15 — OVERTURNED: two throttles with the same symptom, and I named the wrong one as the mechanism](#2026-08-15-overturned-two-throttles-with-the-same-symptom-and-i-named-the-wrong-one-as-the-mechanism)
- [2026-08-15 — RULE: deploy to where the artifact is BUILT, not where it is served](#2026-08-15-rule-deploy-to-where-the-artifact-is-built-not-where-it-is-served)
- [2026-08-15 — OVERTURNED: p50 is the wrong statistic to set an alarm floor from, and my own test caught it](#2026-08-15-overturned-p50-is-the-wrong-statistic-to-set-an-alarm-floor-from-and-my-own-test-caught-it)
- [2026-08-15 — A FALLBACK ARGUMENT IS A REQUEST, NOT A GUARANTEE. `_safe_text(x, None)` RETURNS `""`, 43 TIMES OVER](#2026-08-15-a-fallback-argument-is-a-request-not-a-guarantee-_safe_textx-none-returns-43-times-over)
- [2026-08-15 — THE SHARED-INDEX REPAIR MUST RUN IN A SHELL WITH NO `GIT_INDEX_FILE`, OR IT REPAIRS THE WRONG INDEX](#2026-08-15-the-shared-index-repair-must-run-in-a-shell-with-no-git_index_file-or-it-repairs-the-wrong-index)
- [2026-08-15 - A LABEL-MATCHED LOOKUP IS NOT A SUBSTITUTE FOR THE FIELD, AND ITS FAILURE IS SILENT](#2026-08-15---a-label-matched-lookup-is-not-a-substitute-for-the-field-and-its-failure-is-silent)
- [2026-08-15 - ENUMERATE EVERY SPORT THAT REACHES A CHANGED BRANCH *BEFORE* DEPLOYING](#2026-08-15---enumerate-every-sport-that-reaches-a-changed-branch-before-deploying)
- [2026-08-15 — I PROPOSED ALLOWLISTING A READ PATH WITHOUT CHECKING THE WRITE PATH. It would have 404'd forever](#2026-08-15-i-proposed-allowlisting-a-read-path-without-checking-the-write-path-it-would-have-404d-forever)
- [2026-08-15 — A HOOK THAT BLOCKS A `Bash` CALL DISCARDS EVERY SIDE EFFECT IN IT, INCLUDING THE HEREDOCS](#2026-08-15-a-hook-that-blocks-a-bash-call-discards-every-side-effect-in-it-including-the-heredocs)
- [2026-08-15 - I APPLIED "ONE SAMPLE OF A MOVING QUANTITY" TO PRODUCTION AND NOT TO MY OWN MEASUREMENT](#2026-08-15---i-applied-one-sample-of-a-moving-quantity-to-production-and-not-to-my-own-measurement)
- [2026-08-15 — a mid-ramp reading is not a window reading; I called a 446MB difference "noise"](#2026-08-15-a-mid-ramp-reading-is-not-a-window-reading-i-called-a-446mb-difference-noise)
- [2026-08-15 — verify a deployed fix by CONTENT across every SHA that carried it](#2026-08-15-verify-a-deployed-fix-by-content-across-every-sha-that-carried-it)
- [2026-08-15 — AN OCCURRENCE COUNT IS NOT A ROW COUNT, and I published three numbers that could be read as either](#2026-08-15-an-occurrence-count-is-not-a-row-count-and-i-published-three-numbers-that-could-be-read-as-either)
- [2026-08-15 — A PINNED-DEPLOY SERVICE SILENTLY REVERTS PEERS. VERIFY YOUR COMMIT AFTER IT GOES LIVE.](#2026-08-15-a-pinned-deploy-service-silently-reverts-peers-verify-your-commit-after-it-goes-live)
- [2026-08-15 — Render's git mirror is PER SERVICE and only refreshes at build time](#2026-08-15-renders-git-mirror-is-per-service-and-only-refreshes-at-build-time)
- [2026-08-15 - `wait_for_selector` PROVES ATTACHMENT, NOT COMPLETION, AND I HAD ALREADY "FIXED" THIS ONCE](#2026-08-15---wait_for_selector-proves-attachment-not-completion-and-i-had-already-fixed-this-once)
- [2026-08-15 — TWO READS INSIDE ONE WARM-UP WINDOW ARE ONE READ. I declared a working fix dead](#2026-08-15-two-reads-inside-one-warm-up-window-are-one-read-i-declared-a-working-fix-dead)
- [2026-08-15 - A UNIT CHANGE CANNOT FIX A FIT WHEN THE UNITS ARE PROPORTIONAL, AND I ALMOST BUILT IT ANYWAY](#2026-08-15---a-unit-change-cannot-fix-a-fit-when-the-units-are-proportional-and-i-almost-built-it-anyway)
- [2026-08-15 — A TIMESTAMP WHERE A SIGNAL STOPS IS NOT WHERE THE FAULT IS](#2026-08-15-a-timestamp-where-a-signal-stops-is-not-where-the-fault-is)
- [2026-08-15 — A HARDCODED ABSOLUTE `startTime` IS A FUTURE TIMESTAMP FOR PART OF A WATCHER'S LIFE](#2026-08-15-a-hardcoded-absolute-starttime-is-a-future-timestamp-for-part-of-a-watchers-life)
- [2026-08-15 — check whether the instrument is already firing BEFORE building a way to make it fire](#2026-08-15-check-whether-the-instrument-is-already-firing-before-building-a-way-to-make-it-fire)
- [2026-08-15 — MY OWN WATCHERS FAILED THREE TIMES IN ONE EVENING. Hand-run the gate before trusting a poller.](#2026-08-15-my-own-watchers-failed-three-times-in-one-evening-hand-run-the-gate-before-trusting-a-poller)
- [2026-08-15 — THE CONFIDENCE INTERVAL BELONGS TO THE ESTIMATE, NOT TO THE THRESHOLD. My own test asserted otherwise and failed](#2026-08-15-the-confidence-interval-belongs-to-the-estimate-not-to-the-threshold-my-own-test-asserted-otherwise-and-failed)
- [2026-08-15 — ACQUIRING THE DEPLOY CLAIM BLINDS THE DEPLOY GATE. The safety mechanism disabled the safety check](#2026-08-15-acquiring-the-deploy-claim-blinds-the-deploy-gate-the-safety-mechanism-disabled-the-safety-check)
- [2026-08-15 — ANCESTRY CANNOT TELL YOU YOUR WORK IS PUBLISHED, AND A BROKEN GREP LOOKS EXACTLY LIKE A DELETION](#2026-08-15-ancestry-cannot-tell-you-your-work-is-published-and-a-broken-grep-looks-exactly-like-a-deletion)
- [2026-08-15 — a cgroup number minus a per-process number is not a difference, it is a category error](#2026-08-15-a-cgroup-number-minus-a-per-process-number-is-not-a-difference-it-is-a-category-error)
- [2026-08-15 — A DEPLOY CLAIM IS ADVISORY. It binds participants, not the fleet.](#2026-08-15-a-deploy-claim-is-advisory-it-binds-participants-not-the-fleet)
- [2026-08-15 — NEVER PIPE A COMMAND WHOSE EXIT CODE YOU DEPEND ON](#2026-08-15-never-pipe-a-command-whose-exit-code-you-depend-on)
- [2026-08-15 — THE DEPLOY CLAIM IS ADVISORY, AND IT LOST A RACE IT LOOKED LIKE IT WOULD WIN](#2026-08-15-the-deploy-claim-is-advisory-and-it-lost-a-race-it-looked-like-it-would-win)
- [2026-08-16 — THE HANDOFF THAT WORKED WAS A SCHEDULED TASK, NOT A MESSAGE](#2026-08-16-the-handoff-that-worked-was-a-scheduled-task-not-a-message)
- [2026-08-16 — A TEST THAT PROVES A DEFECT DOES NOT PROVE PRODUCTION RUNS THROUGH IT. I DEPLOYED A CORRECT FIX TO AN UNUSED PATH](#2026-08-16-a-test-that-proves-a-defect-does-not-prove-production-runs-through-it-i-deployed-a-correct-fix-to-an-unused-path)
- [2026-08-16 — COLLAPSING A LEDGER FILE WITHOUT FIXING THE WRITING HABIT JUST REGROWS IT](#2026-08-16-collapsing-a-ledger-file-without-fixing-the-writing-habit-just-regrows-it)

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

Consequence, deliberate: the guard in front of MLB keeps its full 3000MB floor.
The seven cheap sports were relaxed to 1500MB because their cost is measured
(+1.7MB for five of them); MLB's tail is not.

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

`scripts/deploy_preflight.py` prints one verdict line. Before acquiring a claim
it is `HOLD: 3 job(s) in flight` or `CLEAR`. **After I acquired the claim it
became:**

    CLAIMED: deploy claim on refresh-worker is held by live-game-line-projection.

The claim verdict **REPLACES** the job verdict rather than accompanying it, and
it does not distinguish *held by me* from *held by someone else* — the JSON even
reports `deploy_claim.yours: false` while `holder` is my own string.

**So my poll-and-fire loop, which grepped `^(HOLD|CLEAR|UNKNOWN)`, matched
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

Two failures of the same kind in one push, minutes apart: **an instrument
returned a confident answer about content while measuring something else.**

**1. `git merge-base --is-ancestor <mine> origin/main` says nothing about
content.** Nine of my commits were ancestors of `origin/main`, which reads as
"already pushed, nothing to do". Ancestry is a statement about the DAG; it
cannot tell you a later commit did not overwrite your lines — and on a contended
ledger, whole-file commits from stale copies do exactly that routinely (see
`6ccc4779`, another session repairing 30 `deploys.md` + 26 `lanes.md` lines its
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

Same deploy, one step earlier. My waiter was
`s=$(check_deploy_safety 2>/dev/null); if ! echo "$s" | grep -q "NOT CLEAR"`.
It reported **`SAFETY CLEAR after 40s`**. The real result was
`[UNKNOWN] Could not read live-refresh state: HTTPError: HTTP Error 502` —
written to **stderr**, which `2>/dev/null` discarded, leaving `$s` empty. An
empty string contains no `"NOT CLEAR"`, so absence-of-failure read as success,
and a transient 502 became a green light to deploy over a running MLB sim.

The script is explicit that this must not happen — *"Exit code 0 = clear, 1 =
something is in flight, 2 = could not determine (which is NOT the same as
clear, and is deliberately not exit 0)"* — and my loop threw away the exit code
that encoded it.

**How to apply.** Wait loops check `rc -eq 0` **and** grep for the positive
token (`^CLEAR:`), with `2>&1` so diagnostics are visible. If a poll cannot
distinguish "healthy" from "could not read", it is not a poll. This is
[[feedback_unknown_must_not_default_permissive]] recurring in a wait loop
rather than in application code, and [[feedback_instrument_blindness]]: a
healthy reading is evidence only once you know what makes it read unhealthy.

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

`git rev-parse "origin/main:.syndicate/state.md"` fails with
`ambiguous argument 'origin\main;.syndicate\state.md'`. MSYS sees `a:.b`, decides
it is a POSIX path LIST, and rewrites `:`→`;` and `/`→`\` before git ever sees it.

**The part that makes it dangerous: it is selective.** Measured:

    git rev-parse "origin/main:syndicate/features/shared/clv_join.py"   -> WORKS
    git rev-parse "origin/main:.syndicate/state.md"                     -> MANGLED
    git rev-parse "origin/main:.claude/hooks/lane-guard.py"             -> MANGLED
    MSYS_NO_PATHCONV=1 git rev-parse "origin/main:.syndicate/state.md"  -> WORKS

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

## Superseded on 2026-08-15 — the two `same_book_n` entries

Both were merged into **"never read a joiner zero as a fact about the world"**
above; full original text is in `learnings_evidence.md`. They reappeared here
once after being removed — a stale-read write on this shared file resurrected
them alongside their own replacement. If they show up a third time, delete
them again rather than assuming the merge was reverted: the merged rule and
the evidence file are the source of truth.
