# Syndicate — Learnings

> **Append only.** Rules must be obeyable by a session with zero context.
> `FORBIDDEN` = never do this again. `EXONERATED` = ruled out, stop
> re-investigating.


<!-- LEARNINGS-INDEX:START -->

## Index — 128 rules `[generated]`

> Regenerate with `py -3 scripts/build_learnings_index.py` after appending.
> This block is the ONLY part of this file that is rewritten; rule bodies
> are append-only and are never touched. **FORBIDDEN** = never do this
> again. **EXONERATED** = ruled out, stop re-investigating.

**FORBIDDEN — 11**

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

**EXONERATED — 3**

- [2026-08-12 — EXONERATED: the soccer window is not the egress cause](#2026-08-12-exonerated-the-soccer-window-is-not-the-egress-cause)
- [2026-08-15 — EXONERATED: "eight hydrated sports at once cannot fit in 4GiB"](#2026-08-15-exonerated-eight-hydrated-sports-at-once-cannot-fit-in-4gib)
- [2026-08-13 — EXONERATED: `shell: "bash"` in a Windows hooks block works](#2026-08-13-exonerated-shell-bash-in-a-windows-hooks-block-works)

**Rules and corrections — 114**

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
