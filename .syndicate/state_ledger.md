# state — ledger

Split out of `state.md` by `scripts/split_state.py`. Bodies are verbatim.
The INDEX of every subject, across every part, is in `state.md`; the
one-subject-one-section rule is global and spans these files.
Same rules as state.md: when a fact changes, EDIT THE LINE.

## [segment-misgrade-regrade] 53 OF 173 SETTLED SEGMENT ORDERS WERE GRADED AGAINST THE WRONG ACTUAL — 30.6%, AND THE ERRORS NEARLY CANCEL `[measured 2026-09-05, substrate render + upstream:statsapi]`

`bet_status.segment_refusal` stopped the bug going forward. This is the answer to
"how many were already wrong", re-graded against each order's TRUE segment
actual. Manifest: `reports/segment_regrade/manifest_2026-09-05.json`, 173 rows.

**THE CONTROL IS WHAT MAKES THE NUMBER TRUSTWORTHY, and it ran first.** The
harness re-grades each order the OLD way and compares to the shipped ledger:
**172/173 (99.4%) reproduce**. So the flips below are the grading change, not
reimplementation drift — without that arm, "53 rows differ" would be
indistinguishable from a rewrite that disagrees with production about
everything.

    OUTCOME FLIPPED   53/173 = 30.6%
      won  -> lost    28
      lost -> won     22
      lost -> push     2
      lost -> None     1

    segments: first5 124, first3 42, first1 7
    settled_by: inferred 163, venue 10

**WHY NOBODY NOTICED: THE ERRORS ARE NEARLY SYMMETRIC.** 28 wrong-wins against
22 wrong-losses, so the P&L barely moved and no anomaly ever surfaced. Recorded
P&L on these 173 was **$19.20**; corrected is **$12.17** on $419.76 staked
(**+2.90% ROI**), a delta of **−$4.48**. A 30.6% grading error rate that costs
~$7 is exactly the shape that survives indefinitely — **do not let a small P&L
delta be read as a small defect.** Every downstream calibration, CLV and
model-accuracy number computed off these rows was fitted to a 30.6% mislabelled
target.

Actuals came from `upstream:statsapi` schedule+linescore, 180 games over 13
dates; all 70 games behind these orders are `status=Final` with >=9 complete
innings, so no partial-game ambiguity.

### THE VENUE ROWS ARE A DIFFERENT AND WORSE PROBLEM — DO NOT WRITE THESE BACK

Of the 10 rows settled by the VENUE rather than inferred, **our correction
disagrees with the venue on 4**. For those the venue's own settlement matched
our WHOLE-GAME grade. Two readings, and they are not equally likely:

1. our segment actual is wrong for those 4 — unlikely, the games are Final; or
2. **the order was FILLED on a full-game contract**, so the venue settled the
   instrument it actually sold us.

Reading 2 is an EXECUTION defect, not a settlement one, and `segment_refusal`
does **nothing** about it — that fix stops mis-GRADING, not mis-FILLING. Handed
to its own session. **UNVERIFIED**: the supporting ticker claim (segment orders
carrying `KXMLBTOTAL`, the full-game series) could NOT be reproduced — a walk of
`/api/portfolio/live` returned 0 ticker-carrying rows, so the population still
needs locating. Complicating context: `KXMLBTOTAL` was historically *absent*
from the catalogue and was registered on 2026-08-25 to fix a different gap,
which is a plausible mechanism for segment rows acquiring a full-game contract
to join to.

**IF ANY WRITE-BACK IS EVER DONE, EXCLUDE THE 10 VENUE-SETTLED ROWS.** For those
the venue is authoritative; overwriting an actual settlement with our inference
would repeat this exact class of bug one level down. The other 163 are safe.

## [stale-test-triage] "THE TEST IS STALE" IS A HYPOTHESIS, AND IT WAS WRONG FOR 4 OF 18 `[2026-09-05, lane stale-test-repair, commit 63c10ed5]`

All 18 red-standalone tests from `[full-suite-completes]` are now green, CI's
gate is **386 tests, OK (2 skipped)**, and 132 pass across the 12 touched
files. The durable part is not the repairs, it is the rule that governed them.

**THE RULE, pre-registered in the lane before any edit:** *name the COMMIT
that moved the behaviour, or the test is presumed RIGHT and the code presumed
WRONG.* Editing an assertion to match whatever the code now does is how a real
regression gets erased, and it looks exactly like success. **The rule fired 4
times out of 18.**

**THE `386 tests, OK` IS DATA-DEPENDENT AND MUST NOT BE READ AGAINST A
NO-DATA NUMBER.** `python -m unittest tests.test_archives` gives **386 OK** in a
worktree provisioned `--with-test-data` and **31 failed** in one without `data/`
-- and the 31 is identical with a change stashed or applied, i.e. it is absence,
not a regression `[peer lane ncaaf-live-resim-wire, 2026-09-05]`. Both numbers
are correct for their tree. Quote the provisioning with the number or the pair
reads as a regression that never happened; this is the same trap
`[ci-suite-red-test]` was corrected for.

**THREE FAILURE SHAPES THAT ARE NOT STALENESS, and each is reusable:**

1. **A FIXTURE SEAM THAT MOVED.** `test_ncaaf_picks_local`'s `setUp` forces
   the serving gate OPEN, and wrote 2-tuple keys into `_SERVING_REGISTRY`
   after its key gained a `basis` dimension `(sport, market, basis)`. With
   `clear=True` it also removed the genuine entries, so the lookup fell to
   default-deny: **the fixture that exists to force the gate open was forcing
   it shut**, and every assertion was testing the suppressed board. This is
   the `learnings.md` "pinned copy" family with a new face — the test did not
   copy a definition, it copied a KEY SHAPE.

2. **TIME ROT.** `test_market_gone_drop` and `test_soccer_read_scope` both
   pinned one end of an age/date comparison to a calendar date while the code
   reads the wall clock. They passed the day they were written and expired
   silently. **Write AGES, not DATES:** anchor fixtures to `now` whenever the
   code under test calls `datetime.now()`. The tell is a test that fails with
   no commit anywhere near it.

3. **AN UNACHIEVABLE PREMISE.** `test_no_roster_artifact_degrades_to_empty`
   could not create the absence it names: `SYNDICATE_NFL_SOURCE_ROOT` does not
   suppress the REPO-MIRROR candidate, and the git-tracked roster really does
   contain the player. **An env var that does not cover every candidate root
   cannot manufacture absence** — the same fact behind that day's NBA
   betting-card 404. Empty the seam directly instead.

**A REAL PRODUCTION BUG CAME OUT OF SHAPE 1.** `pick_gate.registry_snapshot()`
unpacks `for (sport, market), verdict` from the 3-tuple key and raises
`ValueError: too many values to unpack`. ZERO callers, so nothing broke and
nothing reported it. Fixed, `basis` surfaced. **The same incomplete migration
produced one broken test and one latent landmine; only the test was visible.**

**MUTATION-CHECKING CAUGHT A VACUOUS REPAIR OF MY OWN, and this is the part
most worth keeping.** To avoid hardcoding a value documented as drifting, the
Polymarket price assertion was DERIVED from `_polymarket_cross_ticks()` — the
same function the code calls. That is a TAUTOLOGY: flip the default and both
sides move together, so it can never fail on the thing it names. The mutation
ran GREEN and said so. **A test whose expectation is computed from the code
under test asserts nothing about that code.** Pin the arms explicitly instead
(0->0.55, 1->0.56, 2->0.57).

Second mutation lesson: a mutant that renames a function produces import
ERRORS, which prove only that the test imports the module. Kill the MECHANISM
(make the memo always miss), not the symbol.

**AND MUTATE AT RUNTIME, NOT ON DISK.** The first mutation script wrote to
`pipeline/execute_portfolio.py`, which OPEN lane `order-model-view` holds; the
lane guard caught it. Bytes were restored and the file verified clean, but a
runtime monkeypatch via a `-p` plugin does the same job and touches nobody
else's file.
## [full-suite-completes] THE FULL SUITE RAN TO COMPLETION FOR THE FIRST TIME -- 15,307 tests, 61m06s, and the 27 "NEW" failures are 6 parallel artefacts + 21 stale tests `[2026-09-05, lane full-suite-xdist-run]`

`pytest-xdist` was ALREADY declared in `requirements-dev.txt` (2026-08-25) and
merely absent from this machine. Installed 3.8.0; no file changed.

    py -3 scripts/pytest_baseline.py -- tests/ -n 6 --dist=loadscope
    32 failed, 15,224 passed, 51 skipped, 1 xfailed, 458 subtests passed
    in 3666.33s (1:01:06)      collected=15307  failing=31

**NOT `-n auto`, ON PURPOSE.** `auto` is 12 workers here. `suite-order-pollution`
named two causes for its own `MemoryError` death at 26 GB RSS; only one had
changed. Pagefile **4,864 MB -> 19,406 MB** (4.0x) -- changed. Peer load -- NOT
changed: at 15:49 CDT six peer python jobs were actively burning CPU (including
someone else's full `pytest tests/` 34.9 min in) with 10.9 of 31.6 GB free.
That lane declined to start a third suite "rather than degrade theirs"; `-n 6`
honours that and still finished.

**CORRECTION 2026-09-05 21:2xZ — THE PAGEFILE IS AUTO-MANAGED, SO "THE
CONSTRAINT CHANGED" WAS WRONG, AND IT WAS MY CLAIM.** I recorded the pagefile
moving **4,864 MB -> 19,406 MB (4.0x)** as the condition that had changed since
`suite-order-pollution`'s death. `AutomaticManagedPagefile = True`: Windows
grows and shrinks it on demand. Three readings, ONE box, ONE configuration:

    suite-order-pollution   4,864 MB   (its run dying)
    me, 15:49, 6 peers      19,406 MB  (already inflated by the load)
    me, 21:2x, near-idle    5,120 MB allocated, 54 MB in use

**4,864 and 19,406 are the same setting in different states, not a settings
change.** Nothing was reconfigured between their run and mine, so it cannot be
why mine completed. A DEMAND-DRIVEN quantity read once is not a constraint.

**AND THIS WEAKENS THE CAUSAL CLAIM BELOW, WHICH IS THE PART THAT MATTERS.** I
argued the suite has no intrinsic 26 GB need because my run peaked at 7.05 GB
with flat pagefile use. But `test_heap_roots`/`test_retainer_census` are the
tests that allocate ~20 GB, **and they FAILED in both my runs** — so a low
total is exactly what a run produces when the big allocators die early instead
of allocating. The low peak may be a CONSEQUENCE of those failures rather than
evidence against the need. `[peer lane ncaaf-live-resim-wire raised the
competing hypothesis; the pagefile reading is mine]`

**RESOLVED 2026-09-05 ~22:0xZ. IT IS NEITHER HYPOTHESIS, THE `~20 GB` IS FICTION,
AND MY "PARALLEL-ONLY ARTEFACT" LABEL WAS ALSO WRONG.**

`~20 GB` never had a source. Read off both files statically: `test_heap_roots`
allocates 20x8000 at three sites plus 60,000 (sub-MB); `test_retainer_census`
~2 MB. **Low single-digit MB.** The figure travelled as prose through
`suite-order-pollution`, through me, and through a peer lane, and nobody had
checked it. `[peer lane ncaaf-live-resim-wire found it and retracted its own
pressure hypothesis on it; sizes confirmed independently here]`

**THE REAL MECHANISM: A FIXED NODE BUDGET AGAINST A VARIABLE AMBIENT HEAP.** The
census TRAVERSES `gc.get_objects()`; its cost is a function of the heap the
process already has, not of what these tests allocate. `NODE_CAP = 40000` is a
budget the walk decrements. Measured inside a real pytest process holding 40
other test modules:

    cap=   40,000   nodes_used=  40,000   TRUNCATED   probe=['_PLAIN_CACHE']  0.07s
    cap=  400,000   nodes_used=  74,925   complete    probe=all three         0.21s
    cap=2,000,000   nodes_used=  74,925   complete    probe=all three         0.19s

The requirement is **74,925 nodes, 1.87x the cap**. The walk stops on its own
there, so the ceiling costs 0.14 s and not more.

**REPRODUCED WITH ZERO PARALLELISM** -- 40 modules then `test_heap_roots` in ONE
process, no xdist: 2 failed. So "parallel-only artefact" was my label and it was
wrong; xdist only MANIFESTS it, because a `--dist=loadscope` worker accumulates
whole modules. Standalone-passes-therefore-parallelism was the inference, and it
was the same non-discriminating control as everything else in this subject.

**THE IRONY IS THE LESSON.** The cap's own comment says it exists so these tests
"exercise behaviour, not the size of whatever process happens to be running
them", and a sibling docstring states the principle outright: *"A test must not
be a function of its runner."* **The cap was the fix for runner-dependence and
it reintroduced runner-dependence in the opposite direction** -- too small a
budget rather than too large a walk.

FIXED: `CENSUS_NODE_CAP = 400_000` for the census tests (`NODE_CAP` unchanged for
`PythonHeapTotalTests`, whose ratio/identity assertions need no complete walk),
and `_rows()` now asserts the census's OWN `node_budget_exhausted` flag -- which
the payload has always carried and no test read. Every assertion there is
`assertIn`, so a truncated walk turned "the census does not reach this root" into
"the census stopped early" while reading identically. Mutation (cap back to
40,000): **6 failed**, naming the truncation and `nodes_used=40000`, where the old
code produced a silent `'Holder' not found` on only 2.

**AN OPEN INCIDENT NOW HAS NO CAUSE ATTACHED — this is the consequence, and it
is bigger than a stale sentence.** `suite-order-pollution`'s OPEN block presents
its own `MemoryError` as SOLVED: a 4,864 MB pagefile against tests that
*"legitimately allocate ~20 GB"*. **Both halves are now gone** — the pagefile is
auto-managed and was never a precondition (retracted above), and the ~20 GB is
fiction (measured above). What remains is a full suite that died at **26 GB RSS
emitting zero test-status lines, with no account of why.**

**A LANE THAT BELIEVES IT KNOWS THE CAUSE WILL NOT INVESTIGATE.** The sentence is
not merely wrong, it is load-bearing in the direction of NOT LOOKING: if that
`MemoryError` recurs, the block tells the next reader it is understood. So the
correction to carry is **not "the 20 GB was wrong" but "their 26 GB has no
explanation any more"** — a correction versus an open question whose owner does
not know it is open. `[framing from peer lane ncaaf-live-resim-wire]`

The 26 GB itself is unexplained but not mysterious in kind: it was the PARALLEL
suite's total across workers, and attributing it to these four tests was a step
nobody took deliberately. What no longer exists is any reason to think those
tests are the ones to look at.

**NOT EDITED — their block, their lane.** Owner located by transcript search
rather than by title guess: session `local_8498f6de` prints
`=== lane marker === suite-order-pollution`, and a session whose `.current-lane`
marker names the slug is the holder. Messaged there.

**SO THE `test_heap_roots` MECHANISM IS STILL OPEN, AND MY "CONTAMINATION"
READ IS NOT THE FAVOURITE ANY MORE.** Two hypotheses with DIFFERENT FIXES:
*contamination* (they census every object in the interpreter, so a parallel
worker's objects pollute the count) -> isolate them with a marker or
`--dist=loadgroup`; *memory pressure* (~20 GB of allocation on a pagefile that
sits at ~5 GB when idle) -> the box cannot run them in parallel at all and the
pagefile is the defect. **A standalone PASS is consistent with both, so the
check I reached for cannot discriminate** — the same shape as
`[2026-09-05] A CONTROL THAT KILLS ONE ALTERNATIVE IS NOT A DISCRIMINATOR`.
The discriminating measurement is their peak RSS run STANDALONE: a single-
process peak near the ceiling means pressure. **NOT TAKEN, deliberately** — a
peer pytest run was in flight at 21:2x and this is the experiment that already
took one full suite down. It belongs on a genuinely idle box.

**THE MEMORY RISK DID NOT MATERIALISE, and the number says which cause it was:**
peak python RSS across the WHOLE machine **7.05 GB**, and pagefile usage FLAT at
1,056-1,228 MB for the entire hour -- it never climbed once. So the earlier death
was the PAGEFILE, not the suite's intrinsic need. The heaviest single worker hit
2,112 MB, nowhere near the ~20 GB `test_heap_roots`/`test_retainer_census`
allocate serially.

**~~THIS SUITE IS I/O BOUND HERE, NOT CPU BOUND~~ -- RETRACTED 2026-09-05 20:06Z,
AND IT WAS MY OWN CLAIM.** Run 1 took 61m06s at `-n 6` on a machine carrying six
peer jobs, and I inferred I/O-bound from "the machine only turned ~1.5 cores of
Python work across ten processes" (7.2s of worker CPU per 8s wall). **A SECOND
RUN ON AN IDLE MACHINE REFUTES IT:**

    run 1   -n 6      6 peer jobs, 10.9 GB free    15,307 tests   3666.33s  (61m06s)
    run 2   -n auto   idle, 18.9 GB free           15,468 tests   1166.83s  (19m26s)

**3.1x faster.** The reading that produced "I/O bound" was taken WHILE SIX PEER
JOBS CONTENDED FOR THE SAME DISK -- which is precisely the condition that makes
any workload look I/O bound, so it could not have distinguished the two. **A
saturated machine is not evidence about the workload's own shape.** The scope
note's 3.7x is closer to right than my correction to it was; "do not quote 3.7x
for this machine" was wrong and is withdrawn.

**WHAT IS STILL NOT ESTABLISHED:** run 2 changed TWO variables at once (idle
machine AND 12 workers instead of 6), so 3.1x cannot be split between them. Nobody
should quote a worker-scaling factor from this pair. The one thing it does settle
is that the suite finishes in ~20 minutes on an idle box, which makes a full run
an ordinary thing to do rather than an event.

**THE GATE SAID `27 NEW FAILURE(S)`. THAT IS A RAW SET DIFF AND IT IS NOT 27
REGRESSIONS.** Every failure was re-run STANDALONE, one test per process with
xdist absent -- the discriminating method the scope note used:

    6 of 27  PASS ALONE -> parallel-only artefact, NOT a code regression
   21 of 27  FAIL ALONE -> real in this environment, and then triaged by REASON

The 6 are all four `test_heap_roots::WiderRootTests` cases plus
`test_quote_join_index_equivalence` and `test_ncaaf_returning_production_builder`.
`test_heap_roots` measures every object in the interpreter, so six concurrent
workers contaminate it BY CONSTRUCTION. **`--dist=loadscope` does not protect
process-wide-measurement tests** -- the scope note's own §2 said it would not,
and this is the first measurement of that.

**OF THE 21 THAT FAIL ALONE, ZERO ARE MISSING-DATA ERRORS.** That contradicted
the expectation going in (the scope note's NFL-PBP class), and the reasons say
so plainly -- they are assertion mismatches about BEHAVIOUR:

- **2 pre-existing test-harness**: `test_live_refresh_loop` x2,
  `RuntimeError: Working outside of application context` -- verbatim what
  `suite-order-pollution` already recorded as pre-existing and unrelated to
  ordering. CONFIRMED standalone here, not inferred.
- **1 data-shaped**: `test_nfl_props` `[6, 22] != [6]` -- this tree's mirror
  carries a week 22.
- **18 tests left STALE by deliberately shipped changes**, clustered by
  subsystem, which is the tell: 4 `test_ncaaf_picks_local` + 1
  `test_smartsim2_calibration_profile` (NCAAF calibration was re-fitted and
  PROMOTED by `ncaaf-pace-block`); 3 `test_soccer_live_gates_wiring`
  (`KeyError: 'live_gameline'`); 2 `test_soccersim_player_props` (numeric,
  9.3324 vs 13.0); 2 `test_market_gone_drop` (soccer now included);
  `test_prop_player_keying` (the totals key is now TEAM-QUALIFIED, which is
  `venue-quote-line-join`'s recorded fix for "a TOTALS key names no GAME");
  plus polymarket, nfl_props_board and soccer_read_scope.

**THE ONE THAT LOOKED LIKE A LIVE RISK IS NOT ONE, AND WAS CHECKED RATHER THAN
REPORTED.** `test_mlb_position_substitutions::test_absent_flag_is_a_no_op` fails
with *"True is not false : the feature must be dark-launched OFF"*, which reads
exactly like CLAUDE.md's "absent != off" trap. It is not:
`models.py:576` declares `position_substitutions: bool = True` and `e3bdbc8b`
(`#624 step 3: enable in-sim position-player substitution`) flipped it
deliberately. The TEST is stale against an intentional promotion.

**`--update` WAS NOT RUN, deliberately.** It would overwrite a CI-relevant
baseline with Windows-local results. Note also that the baseline is already
stale as a comparand: it records `total_testcases: 11745` against this tree's
**15,307** (~3,500 tests newer) and was recorded on 4-core Linux CI with a
different `data/` mirror. Its 19-failure set is NOT like-for-like, which is
most of why the raw diff read as 27.

**RUN 4 (2026-09-06 09:51-10:25, tree `58302f07`): 5 failing, AND THEY ARE NOT
STALE — the first suite-SCALE defect this sequence has isolated.**

    5 failed, 15,510 passed, 51 skipped, 1 xfailed, 459 subtests passed
    in 2048.09s (0:34:08)      collected=15567  failing=5

**THE REPRODUCTION, ALL AT ONE TREE — this is the whole finding:**

    30 passed      the two files ALONE at `58302f07`
    2,334 passed   192 files (`test_b*`+`test_n*`) under -n auto --dist=loadscope
    5 failed       the full 15,567-test run, same SHA, same invocation

Not order-within-a-file, not parallelism as such, and NOT the tree moving: the
run's own header printed `tree 58302f07, clean` and the files had been run green
at that SHA minutes before launch. **It requires full-suite SCALE** — 192 files
in parallel does not trigger it.

    3x tests/test_ncaaf_live_state_worker.py   (lane: session local_801e0e46)
    2x tests/test_board_build_timing.py        (lane suite-order-pollution)

**THE NCAAF THREE ARE THE SAME TESTS AS RUN 3 AND A DIFFERENT CAUSE.** In run 3
they failed because the tree predated their producer (genuinely stale). Here the
producer exists, they pass standalone, and only scale breaks them. Same names,
opposite diagnosis — which is precisely why a failure list must be re-derived
rather than remembered.

**`test_board_build_timing` PASSED in run 3, then `51f60573` (23:18, "two
clock/scheduler races") landed, and it fails at scale now.** Two readings, not
separable from here: the fix is incomplete and a third race shows only at scale,
or the fix introduced this. Surfaced to that lane as both, asserted as neither.

**MECHANISM NOT ESTABLISHED, and recorded as a LEAD not a finding:** process AGE
— a `--dist=loadscope` worker alive 34 minutes is not a fresh one, and that is the
first of the five mechanisms `suite-order-pollution` already catalogues. A
34-minute reproduction is expensive; nobody should treat this paragraph as a
diagnosis.

**THE PROVENANCE HEADER (`ad2ee32e`) EARNED ITSELF ON ITS FIRST REAL RUN.** Being
able to say *same SHA, opposite result* in one step is the entire reason this is
a real finding instead of a fourth staleness false alarm — which is exactly what
it would have looked like the day before.

**Non-hermetic writes: FOURTH observation, stable at 8 paths** (the 6 tracked
plus `data/settlement_inputs/` and a date-stamped
`reports/intelligence/game_chips_<date>.json`). Preserved, never discarded.

**RUN 3 (2026-09-05 22:31-23:09, HEAD `0ad1480d`, idle, `-n auto`): 31 -> 12 -> 4.**

    4 failed, 15,455 passed, 51 skipped, 1 xfailed, 459 subtests passed
    in 2274.54s (0:37:54)      collected=15511  failing=4

**EVERY REPAIR HELD. None of the 22 appears** -- not the four `test_heap_roots`,
not `nfl_props` / `odds_control_plane` / the two `wnba_refresh_runner` /
`probability_differential`, and the seven converter fixes stayed 5/5 with
`KNOWN_FAILING` shrunk. The `test_heap_roots` cap concern did NOT fire: I had
flagged that a full `-n auto` worker holds far more than the 40 modules measured
at 74,925 nodes, so 400,000 might not suffice. It sufficed, and the guard would
have NAMED the truncation if not.

**THE PREDICTION WAS WRONG BY BEING STALE, NOT BY BEING MISREASONED.** I
pre-registered **2**, naming the `test_live_refresh_loop` pair as another lane's.
`c353b47d` (22:27) fixed them **four minutes before this run started** --
`suite-order-pollution` acting on the message sent it. All 4 actual failures are
different tests and all belong to other lanes, dated not assumed:

    ada53db5  09-05 22:20  ncaaf serving-path visibility   -> 3 of the 4
    16c9ee70  09-04 10:28  kalshi doubleheader placeholder -> 1 of the 4

`ada53db5` landed **11 minutes before the run** -- the same mid-flight arrival as
`4ffba395` earlier in the day.

**THE 37m54s IS UNEXPLAINED AND IS RECORDED AS UNEXPLAINED.** Run 2 was 19m26s,
also `-n auto`, also a nominally idle box; run 3 carried 204 more tests. I do not
have the instrumentation to separate ambient load from test count, and inventing
a cause here is precisely what the retraction above was for. **Do not quote a
per-run wall clock for this suite as if it were a property of the suite.**

**THE NON-HERMETIC WRITE SET GREW -- third observation, and bigger.** Run 3 left
**8** paths dirty against the 5 seen before: the previous four plus
`reports/intelligence/{intelligence_state.json,intelligence_state_history.jsonl}`
and a new untracked `reports/intelligence/game_chips_2026_09_05.json`. So the
footprint is a function of WHICH tests run, not a fixed list -- do not treat the
recorded set as complete. Preserved (stash + scratchpad), never discarded.

**RUN 2 CONFIRMS THE 18 REPAIRS AND THE PREDICTION WAS PRE-REGISTERED.** After
`63c10ed5`, on an idle machine at `-n auto`:

    12 failed, 15,404 passed, 51 skipped, 1 xfailed, 459 subtests passed
    in 1166.83s (0:19:26)      collected=15468  failing=12

Predicted **13** before the run (31 - 18) and named all thirteen. Got **12**, and
the arithmetic reconciles exactly: 11 of the 13 appeared, **none of the 18
repairs did**, and 1 unpredicted failure arrived. The two absent ones are
`test_quote_join_index_equivalence` and `test_ncaaf_returning_production_builder`
-- both from the parallel-only set, which **I flagged in advance as worker-count
dependent by construction**; they passed at 12 workers having failed at 6. The
four `test_heap_roots` cases still fail, so that subset is real but not stable.

**THE UNPREDICTED ONE IS NOT MINE AND IS DATED, NOT ASSUMED.**
`test_ops_execution_ledger_summary::test_the_bucket_carries_only_the_declared_fields`
-- `by_segment` is in the bucket and not in `_LEDGER_SUMMARY_FIELDS`
(`ops.py:331`). Commit `4ffba395` landed **16:03:00**, ten minutes AFTER run 1
started (15:53:22) on a worktree pinned at provisioning-time `origin/main`, so
run 1 could not have seen it. My commits touch neither that file nor its subject.

**DO NOT SILENCE IT BY APPENDING THE FIELD.** That constant's own comment is the
reason: *"the natural way to answer the next question is to add one more field,
and three of those turn a counter into a money record over HTTP."* The guard
fired for exactly the case it was written for, and appending `by_segment` is the
decay it exists to stop -- it needs a decision, not a green test.
**RESOLVED BY THAT LANE, `782a057b`, AND VERIFIED HERE AT THE SOURCE RATHER
THAN FROM THEIR SUMMARY.** `by_segment` IS a counter and does belong:
`ops.py:458` reads `bucket["by_segment"].setdefault(segment, {"orders": 0,
"settled": 0})` -- two integers by `+= 1`, keyed by a bounded segment
vocabulary. Same risk class as `by_status`. File now 15 passed. **This
discharges the "believed but unverified" item logged at session close.**
They also replaced the weak half: the tuple test is a list equality whose
cheapest green is typing a name into it, so a STRUCTURAL test now walks the
bucket and permits a number or a dict nesting to numbers and nothing else --
with `bool` rejected BEFORE the numeric branch (it is an `int` subclass) and an
explicit anti-vacuity assert that the recursion is reached. Their mutation:
make a DECLARED field carry a string, so every NAME is unchanged -- tuple test
GREEN, property test RED.

**`syndicate/blueprints/ops.py` is held by OPEN lane `ncaaf-live-resim-wire`,**
so it is theirs; surfaced here rather than edited.

**THE NON-HERMETIC WRITES REPRODUCED EXACTLY** -- same four tracked files, same
new `data/settlement_inputs/`, a fresh live Kalshi fetch. Second observation, so
it is a property of the suite and not a one-off. This time the DISCARD GUARD
blocked the revert (those lines exist in no commit on any ref) and it was right
to: they were `git stash`ed instead, restorable, rather than destroyed.

**THE SUITE IS NOT HERMETIC: IT MAKES LIVE NETWORK CALLS AND WRITES TRACKED
FILES.** Found by `git status` after the run, not looked for. Four tracked
files were modified and one untracked directory created:

    reports/intelligence/kalshi_markets.json      +65,028 / -12
    vendor/wnba_betting_repo/.../schedule_2026.csv    104 / 104
    vendor/wnba_betting_repo/.../schedule_2026.json     1 / 1
    data/mlb_source/.../live_lens_2026_06_02.jsonl     +1 / 0
    data/settlement_inputs/                        NEW, untracked

`kalshi_markets.json` gained `count`, `fetched_at` and `staleness_seconds`, and
its `fetched_at` reads **2026-09-05T21:53:38Z** -- 16:53 CDT, DURING the run that
ended 16:54:41. So a test reached the live Kalshi API and persisted the result.

**WHY THIS MATTERS BEYOND TIDINESS: the protocol tells sessions to run tests,
and the PRIMARY tree is shared.** A full run there silently rewrites those files
under every other session -- a 65,000-line change to a tracked artifact that
nobody edited and that `git add -A` would sweep straight into someone's commit.
In a per-session worktree it is contained, which is one more reason the worktree
protocol is load-bearing rather than hygiene. Reverted here; nothing committed.

**OFFERED TO `suite-order-pollution` (OPEN), WHOSE OWED READING THIS IS.** Its
verification is "a full `pytest tests/` run ends with the 12 passing and the
pre-existing 37 unchanged". This run completed and **none of its 12 files'
fixed tests appear in any failure list**. I did not edit that lane's block.
## [ci-suite-red-test] CI'S OWN SUITE IS GREEN. THE "ONE RED TEST" WAS THE 31st DATA-ABSENCE FAILURE, NOT A SURVIVOR OF THEM `[corrected 2026-09-05, lane ci-archives-nba-card-js, commit ba84b331]`

**The claim this section used to make was WRONG, and it is preserved here
because the way it went wrong is the reusable part:**

> CI's own suite has one red test, with data present. [...] CONTROLLED, not
> assumed. Same file, same worktree, only `SYNDICATE_DATA_ROOT` moved:
> without data 31 failed / with data 1 failed, 380 passed. So 30 of the 31
> were `data/` absence and **one survives with data present** -- it is not a
> worktree artifact.

**`SYNDICATE_DATA_ROOT` WAS THE WRONG KNOB, so the differential built on it
could not separate the two populations it was built to separate.**
`session_worktree.py` says so in its own source, written the day before that
measurement: *"`SYNDICATE_DATA_ROOT` does NOT solve it. Nine of these read
`REPO_ROOT/data/...` directly and ignore the variable entirely, which is why
they stayed invisible to a differential built on that env var."*
`test_nba_betting_card_js_rewrites_source_routes_to_syndicate_paths` was one
of those nine. Its residual failure was not a survivor of the control; it was
a test the control never reached.

MEASURED, this lane, all four readings in the same worktree:

    primary tree (has `data/`)                        1 passed
    worktree + SYNDICATE_DATA_ROOT     the assertion is `assertIsInstance(
                                       content, str)` -- `content is None`
    worktree + SYNDICATE_NBA_ARTIFACT_ROOT            1 passed
    worktree + SYNDICATE_DATA_ROOT, after `ba84b331`  1 passed

The failing assertion was the FIRST line of the test -- the asset never
loaded -- so no route-rewriting assertion was ever reached. **CI checks out
the full repo, `data/nba_source/web/betting-card-v2.js` is git-tracked, and
the file CI runs was green throughout.** Nothing was red in CI.

**THE RULE, and it is the one that pays for this section.** A control is only
a control over the population it actually reaches. A differential that
resolves 30 of 31 cases is not thereby evidence about the 31st: the residual
is the population the instrument was blind to, and reading it as "the one
that survived" inverts what a null result means. Before calling any archive
failure real, check the failing ASSERTION -- `assertIsInstance(content, str)`
on line 1 of a test named `..._rewrites_source_routes_...` says "input",
not "logic". `--with-test-data` is the documented control; `SYNDICATE_DATA_ROOT`
is not, for these nine.

**WHAT THE FALSE ALARM WAS WORTH ANYWAY: a real production outage, in the
code path it pointed at.** See `[nba-betting-card-assets-404]` in
`state_basketball.md`. Chasing why a test could not load that asset is what
found that production could not load it either.
## [state-file-split] state.md IS AN INDEX PLUS NINE PARTS `[2026-09-03, scripts/split_state.py, commit 23bf6bc7]`

**Read `state.md` first, then open only the part your work touches.** It holds
the cross-cutting subjects and the `[subject-index]` table naming every subject
and its file. Bodies live in `state_<domain>.md`: mlb, soccer, football,
basketball, venues, polymarket, kalshi, board, ui, layer2, portfolio, worker,
model, ledger.

    state.md   746,526 -> 62,510 B      largest part  state_venues.md 152,212
    total across ten files  774,933 B   -- the split ADDED ~28 KB of part
                                           headers and index rows

**COMPACTION WAS MEASURED FIRST AND REJECTED ON THE NUMBERS.** Of ~746,500
chars only **1,460 (0.2%)** was reclaimable superseded prose, and all 8
remaining candidates were audited by hand and found NOT archivable -- six had
no dead body (the superseded claim was deleted when its correction was written
and survives only as a quotation inside it), two keep their old block on
purpose and say so. This file is not bloated, it is BIG, because it is live
current truth. Do not send anyone hunting fat here again.

**ONE SUBJECT, ONE SECTION IS NOW GLOBAL.** `state_key_check.py` pools slugs
across state.md + every part (archives excluded, they legitimately repeat a
slug). The commit guard `ledger_invariants.py` checks each file SEPARATELY and
**cannot see a cross-file stack** -- that gap is covered only by
`state_key_check.py` in session-start's coherence loop.

**Adding a subject to a part means adding its index row:**
`py -3 scripts/split_state.py --reindex --apply`. Plain `--apply` REFUSES once
the index exists -- re-splitting would rewrite the index to cover only what is
left in state.md and orphan the parts.

Budget alarms are three now, not one (`session-start.sh`): index 120,000,
per-part 250,000, total 1,100,000. The old single 920,000 cap could not fire
after the split -- state.md would sit at 7% of it forever while a part grew
unbounded.

## [session-harness] SESSION HARNESS — what the hooks actually enforce

- **`lane-guard` STRIPPED THE LEADING DOT until 2026-08-31, so every claim under
  `.syndicate/` or `.claude/` guarded NOTHING** — `.syndicate/x.md` parsed to
  `syndicate/x.md` and matching is `rel.endswith("/" + f)`, which can never
  match. Fixed asymmetrically (right side keeps the original strip set, left
  side drops the dot). Audited before applying: no shared ledger among the
  affected claims, so no session newly blocks on ledger writes.
- **`py -3 scripts/lane_claim_audit.py` is the one tool for "what does the guard
  actually claim".** It loads the hook by AST (running it blocks on stdin) and
  applies BOTH checks, because either alone misses half: a token that does not
  look like a path (prose written inside a `- Files:` block becomes a claim —
  `1/p`, `15.0` and a bare `/` all did this in one day), and a path absent from
  `git ls-files` (the dot-strip class, which looks well-formed). **Run it from a
  worktree pinned to `origin/main`** — the shared primary tree drifts behind and
  reports live files as phantom. `check_lane_invariants` catches neither: one
  holder per claim is true of a claim that guards nothing.

- **THE CLAIM PARSER HAS ONE DEFINITION: `.claude/hooks/lane_claims.py`**
  `[verified 2026-09-04, lane lane-invariant-single-source, 312c93a9, NO DEPLOY]`.
  `lane-guard.py` imports it, and `scripts/check_lane_invariants.py` now does
  too -- it used to carry frozen copies of four regexes and the 14-marker tuple,
  pinned against `lane-guard.py`'s SOURCE TEXT by a test. **That test had been
  silently red since the parser was extracted** (it searched the hook for
  definitions that had moved), and with it 8 more in
  `test_lane_guard_dot_directory_claim.py` and 1 in
  `test_lane_guard_prohibition_marker.py` -- **14 across three files, all bound
  to the hook's pre-extraction shape**, while the checker still exited 0 and
  printed INVARIANTS HOLD.
  **The regexes had NOT drifted; four unpinned behaviours had.** Measured on one
  adversarial ledger: the OLD checker read **1 OPEN lane / 1 claim** and printed
  `INVARIANTS HOLD` exit 0 against a file that held a CONTESTED path AND a stray
  OPEN lane under `## Archived lanes`; the new one reads **3 lanes / 4 claims**
  and reports both, exit 1. The severe case is a `- Files:` line naming
  `scripts/archive_released_lanes.py` -- a filename CONTAINING the marker
  "released" -- which yielded the checker ZERO claims for that lane, so it could
  contest nothing and the one-holder invariant passed vacuously.
  Consequence to hold onto: **`is` does not prove a regex was not copied.**
  `re.compile` memoises, so a re-pasted pattern returns the other module's own
  object and an identity assertion passes -- verified by mutation, the copy went
  in and all 30 tests stayed green. `test_the_checker_defines_none_of_them_itself`
  asks the AST for the ABSENCE of a second definition, which is the form that
  survives the next refactor of the hook.

- **THE LEDGERS ARE KEYED AND CHECKED** `[verified 2026-08-18]`. One checker per
  ledger, all three ENFORCED in CI and reported at session start as
  `LEDGER INCOHERENT`: `scripts/lane_identity_check.py` (slug, one OPEN block,
  one home), `scripts/todo_id_reconcile.py` (numeric id in exactly one of
  `todo.md`/`todo_closed.md`), `scripts/state_key_check.py` (every `## [slug]`
  unique). All three verified to EXIT 1 on deliberately corrupted copies before
  being wired in — the gate is not vacuous. Green at checkpoint: lanes 54 blocks
  coherent, state 35 sections/35 subjects, todo 166 ids.
- **`state.md` sections carry a subject key** `## [subject-slug] TITLE`. One
  subject, one section; a shared slug IS the stacking failure. Added because "no
  duplicate titles" was trivially true while sections were titled by date.
- **`lane-guard.py` reads BOTH Files forms and wrapped continuation lines**
  `[verified 2026-08-18: file-like claims 52 -> 80]`. It previously matched only
  `- Files:`, so 5 lanes using `- **Files (...):**` declared paths NO HOOK COULD
  SEE. A disclaimer now governs only what FOLLOWS it, not the whole line.
  `_DISCLAIMER_MARKERS` gained `"not touch"` (covers "does not touch"/"not
  touch"/"not touched" — subsumes the prior "not touched" entry),
  `"read-only reference"`, and `"not taken"` `[verified 2026-08-19, commits
  0a7fdbeb + f52fc91b + a1cbcde1, all on origin/main]`; each closed a real
  false-positive that had blocked a lane from a file its own ledger text
  explicitly disclaimed. `"not taken"` is a NEW failure shape, not a repeat:
  a lane correctly got blocked from a file it did not own, recorded that
  block as its own disclaimer ("BLOCKED, not taken: ..."), and THAT SENTENCE
  then re-read as a phantom counter-claim, blocking the file's actual,
  correctly-enforced owner from editing their own file — a disclaimer about
  the guard's own prior correct enforcement, not about a file the writer
  never touched.
  Claim matching is exact-or-suffix (`rel == f or rel.endswith("/"+f) or
  f.endswith("/"+rel)`), never a directory prefix — so a non-path token claimed
  out of prose is INERT.
- **`lane-guard.py` (PreToolUse) enforces.** Blocks `Edit`/`Write` against a file
  claimed by another OPEN lane (exit 2); allows it when `.syndicate/.current-lane`
  names the claiming lane. **With the marker empty it blocks your OWN lane's
  files**, reporting `Current lane: 'none'` — so a session that hand-edits
  `lanes.md` instead of running `/lane` locks itself out.
- **`Bash` is not BLOCKED, but is no longer UNSEEN** `[updated 2026-09-04,
  verified, session f97ad5ab]`. `lane-guard`'s matcher is still
  `Edit|Write|MultiEdit|NotebookEdit`, so a shell write cannot be REFUSED —
  predicting a file write from a command STRING is not reliably possible, and a
  guard that blocks on a guess gets routed around. `lane-postwrite-check.py`
  (Pre+PostToolUse on `Bash|PowerShell`) DETECTS it instead: it snapshots
  `(mtime,size)` of paths claimed by OTHER open lanes before the command and
  compares after, so the window is ONE TOOL CALL. It WARNS, never blocks.
  **Scale of the gap, measured over all 292 session transcripts:** writes to
  tracked SOURCE files ran 9,023 Edit-family vs **1,045 Bash/PowerShell
  (10.4%)**; under `.syndicate/` the shell is the MAJORITY path (2,618 vs 1,069).
  **Two limits, both real:** a `git rebase`/`checkout` is suppressed by a
  HEAD-move check, but a concurrent session's UNCOMMITTED write to a claimed file
  is indistinguishable from your own — observed once, live — so it names no
  author.
- **A COMMIT CANNOT REVERT A LEDGER COMPACTION** `[2026-09-04, verified]`.
  `ledger_invariants.resurrected_lines()` refuses a `lanes.md` carrying lines
  upstream moved to `lanes_history.md`. `resurrected_blocks` was blind to it --
  `a8000faf` compacted WITHIN blocks (203,047 -> 84,956 B), so no block read as
  resurrected and `violations()` returned 0 on a stale copy whose commit would
  have restored 1,308 lines. Same shape `_deploys` already refused on its file.
- **A DESTRUCTIVE `git checkout` IS NOW GATED** `[2026-09-04, verified]`.
  `discard-guard.py` (PreToolUse `Bash|PowerShell`) refuses `checkout -- <path>`,
  `restore` and `reset --hard` when the working file holds non-blank lines in
  neither the incoming version nor `HEAD` -- i.e. content with no other copy.
  Before it, that command was allowed by EVERY hook here and had destroyed an
  uncommitted lane block once and nearly a second time. The predicate is
  "exists nowhere else", NOT "has deletions": a deletions count is structurally
  blind to an uncommitted ADDITION, which is what both incidents lost.
- **A CLAIM OUTLIVES ITS SESSION FOREVER — the guard has NO liveness notion**
  `[verified 2026-08-29T23:2xZ, lane lane-claim-phantom-sweep]`. Nothing released
  a claim when a session ended, so they accumulated: **26 OPEN lanes holding 133
  claims while 3 sessions were alive**, 121 of them (91%) enforced on behalf of
  sessions that no longer existed, plus 56 `.current-lane.<session>` markers for
  4 live sessions. Already paid for once the same day — `live-venue-order-placement`
  needed a USER OVERRIDE to take `venue_quote_adapters.py` off `kalshi-line-aware-rungs`,
  whose session was gone. **A header reading "OPEN, UNOWNED" or "CLAIMS RELEASED"
  releases NOTHING**: the guard parses the `- Files:` block and never the
  header's prose. Sweep with `py -3 scripts/release_phantom_lane_claims.py`
  (dry run by default; verifies against `lane-guard._claims()`, keeps every path
  as a record). Post-sweep state: claims held ONLY by live sessions' lanes.
  Verified off != on against the hook itself, not against a claim count —
  `scripts/build_soccer_artifacts.py` and `syndicate/features/ncaaf/sources.py`
  went exit 2 -> exit 0 while a live lane's `venue_quote_adapters.py` stayed
  exit 2.
- **A HOOK THAT RESOLVES PATHS AGAINST `CLAUDE_PROJECT_DIR` IS ANSWERING ABOUT
  THE WRONG REPOSITORY** `[verified 2026-08-20, shipped 58c63b62]`. Every session
  works in its own linked worktree, so `CLAUDE_PROJECT_DIR` is the PRIMARY
  checkout while the tool call targets the worktree. Both failure directions were
  MEASURED: `ledger-commit-guard.py` blocked a `soccer-board-mlb-parity` commit
  over duplicate lane blocks that existed only in the primary tree (its own
  `lanes.md` was clean, `check_lane_invariants.py` said INVARIANTS HOLD), and it
  had never once examined a broken `lanes.md` in the committing worktree.
  `ledger-append-guard.py` was worse — **fully INERT in every worktree**:
  identical violating edit gave `primary exit=2 BLOCKED` / `worktree exit=0
  ALLOWED`, because `relpath(file, PRIMARY)` is `../../../../../tmp/...` and
  matched neither ledger name. **An inert guard and a satisfied guard are
  indistinguishable from outside**, which is why it survived unnoticed.
  `commit-guard.py` had already been fixed for this on 2026-08-16; the fix was
  local to that file, so the next guard written re-made it. Shared resolver now
  in `.claude/hooks/commit_context.py`.
- **A `VAR=1 <cmd>` OVERRIDE PRINTED BY A PreToolUse HOOK IS UNREACHABLE UNLESS
  THE HOOK PARSES THE COMMAND STRING** `[verified 2026-08-20]`. The hook runs
  BEFORE the shell assigns it, so `os.environ` never sees it. Same defect
  `commit-guard.py` fixed 2026-08-17; `ledger-commit-guard.py` shipped with the
  broken form and printed an escape hatch that did not exist. A real exported
  environment variable always worked.
- **`lane-guard.py` is NOT affected, and the reason is accidental**
  `[verified 2026-08-20]`. A worktree path yields the same mangled relpath, but
  claim matching is exact-or-suffix (`rel.endswith("/" + f)`), which matches it
  anyway. It blocks correctly; only its refusal MESSAGE prints the
  `../../../../../tmp/...` form. Do not "fix" it by changing `root` — for
  lane-guard the PRIMARY `lanes.md` is the CORRECT source, because cross-session
  claim exclusivity is inherently global. That is the opposite of
  `ledger-commit-guard`, which must read the tree being committed.
- **`ledger-postwrite-check.py` FIXED** `[verified 2026-08-20, `f73d163e`]`. It
  now watches the worktree the command ran in AND the primary checkout, deduped
  to one scan when they are the same, with per-tree state so neither silences
  the other. It had been blind to worktree Bash writes — **the one thing it
  exists to catch** — and it blamed whichever session happened to observe the
  change (seen firing at a `grep`). It reports that a file CHANGED and is
  broken, says it may be another session, and NAMES THE TREE. Two things the
  work turned up, both measured: `abspath` does not expand Windows 8.3 short
  names, so the same tree deduped as two and was reported twice (caught by a
  "reported exactly once" assertion, not by inspection); and finding the root
  via `git rev-parse` costs **41ms on EVERY Bash call** vs **0.0ms** for a
  filesystem walk to the directory holding `.syndicate/lanes.md` — same answer,
  so the walk is used. End-to-end 162ms → 106ms, ~100ms of it Python booting.
- **ALL FOUR HOOK SUITES ARE ENFORCED IN CI** `[verified 2026-08-20 on the
  Linux runner, `86ec6b42`, run 32415246596 green in 3m18s]`: 16/16, 17/17,
  16/16, 10/10. Enforced, not `continue-on-error`, because each was
  **mutation-tested** first — disable the predicate under test and every suite
  goes red, so a green run means the guards work rather than that the suite is
  vacuous. All four build throwaway repos under the OS temp dir; they are
  stdlib-only, shell-free and need no repo history, so CI's shallow clone cannot
  bite them the way it does `todo_id_reconcile`. **They never read the live
  ledger** — the first version did, and a parallel session trimming real
  duplicates mid-run flipped three cases from pass to fail.
- **`lane-guard` is blind to `.claude/**` AND `.syndicate/**` by design**
  (`lane-guard.py:244`, one `rel.startswith` test covering both), so the
  enforcement layer cannot protect the directory it lives in — and every real
  collision has happened there. **The `.syndicate/**` half matters just as much
  and was missing from this line until 2026-08-18:** no lane claim can ever
  guard `lanes.md`, `state.md`, `deploys.md` or `learnings.md`, so concurrent
  ledger writes are unprotected by design and a phantom claim on a ledger file
  is inert rather than a lock. Measured during the 2026-08-18 orphan sweep:
  `basketball-model-owner`'s Files block claims bare `lanes.md` (a prose
  collision-check sentence the parser reads as a claim) and it blocks nobody —
  while an unrelated session's write to `lanes.md` landed **between** two of
  that sweep's own edits, reported by the Edit tool as "modified on disk since
  you last read it". Anchor ledger edits on unique strings, never on line
  numbers, and re-read before any edit that depends on surrounding content.
- **`commit-guard.py` (PreToolUse) reads the index the COMMIT will use, fixed
  `a52a2b64` 2026-08-16.** It previously evaluated both predicates against
  `CLAUDE_PROJECT_DIR` — the MAIN worktree — while the commit runs wherever the
  shell is, which for this repo's own contended-tree recipe is a LINKED worktree
  with its own index and its own HEAD. **It blocked three clean commits in one
  session**, and, the half that matters, **would have passed a stale index in the
  worktree actually being committed from without a word.** Now resolves
  `cd` → `-C` → payload `cwd` → project dir, then `rev-parse --show-toplevel`.
  `git -C <dir> commit` is CHECKED (it was skipped for "has its own index";
  having your own index is not having a fresh one). **`--git-dir` /
  `--work-tree` remain a KNOWN GAP** — index and tree decouple, so "is it still
  on disk" has no single correct base. 13 tests on real repos
  (`tests/test_commit_guard_worktree_index.py`); pre-fix 7 fail, post-fix 13 pass.
- **`commit-guard.py` reads the COMMAND, not a proxy for it, fixed `5fb52342`
  2026-08-17.** Two exemptions, both measured:
  (a) **all THREE documented overrides were unreachable.** They were
  `os.environ.get(...)` — the HOOK's env — but a PreToolUse hook runs BEFORE the
  shell, so the `export GIT_INDEX_FILE=…` in the recipe the guard PRINTS, and
  the `SYNDICATE_ALLOW_STAGED_*=1 git commit` prefix it prints as the override,
  were both invisible to it. A session that followed the refusal message was
  refused again. Assignments are now parsed out of the command string,
  last-write-wins against `unset`.
  (b) **a pathspec-limited commit is exempt whole.** MEASURED 2026-08-17 against
  an index holding a revert of `A.txt` plus a `D` of on-disk `C.txt`:
  `git commit -m x -- C.txt` produced a tree keeping BOTH, `--stat` 1 file;
  `--pathspec-from-file=` and `--amend -- <paths>` likewise. A partial commit
  builds from HEAD plus the WORKING TREE content of the named paths and never
  consults the index — not even for the named paths — so there is no path left
  to evaluate. **`-i`/`--include` NOT exempt** (the revert landed).
  **`-a` NOT exempt** (it kept the line but COMMITTED the deletion, so predicate
  1 is live under it); `-a` remains a known false positive for predicate 2,
  left alone because `-a` does not refresh `skip-worktree`/`assume-unchanged`
  and that case is unmeasured. Unrecognised options fall through to "keep
  guarding" — false positive, never false negative. Verified by running 19 cases
  through the pre-fix and post-fix guards together: 10 flip 2→0, 8 hold at 2.
  **62 tests in `tests/test_commit_guard_worktree_index.py`** (69 for the
  two-file run that also covers `test_checkpoint_guard_hook.py` — cite the 62 if
  you mean this guard); exemption path 81 ms, short-circuiting before any git
  call.
- **A PATHSPEC COMMIT NEEDS NO REPAIR STEP; THE ISOLATED-INDEX RECIPE DOES.**
  Measured on `5fb52342`: the partial commit UPDATED the shared index for the
  three paths it committed (`git diff --cached` for them empty afterwards) and
  left another session's staged work untouched. The isolated-index route, by
  contrast, is recorded in `learnings.md` 2026-08-15 as arming a revert of the
  file you just committed, every time, requiring a follow-up
  `git restore --staged`. The guard's refusal message now leads with the
  pathspec form for this reason.
- **`commit-guard` matches the COMMAND STRING**, so bundling a file write or a
  `git reset` into the same command as `git commit` blocks the whole thing.
  Separate them. `[recorded by another lane 2026-08-16]`
- **THE ARCHIVE PASS ITSELF CREATES ORPHANS, and that is a second mechanism, not
  a repeat of the one below.** Moving a CLOSED lane to `lanes_closed.md` takes
  the header and whatever body existed AT THAT MOMENT; any bullet the owning
  session appends afterwards lands in `lanes.md` with no header above it and is
  silently adopted by whichever lane precedes it. Measured 2026-08-15: two
  blocks of `model-audit-devig-and-hygiene` ended up under
  `nfl-live-edge-suppression` and `live-game-line-projection`, and **a later
  collision check therefore reported a FALSE claim on
  `scripts/backtest_mlb_props.py`** — the guard reading a real file claim that
  belonged to nobody. Reconciled 2026-08-15; line arithmetic verified exact.
  **When archiving, re-check the source lane for appends made after the move,
  and when a collision check names a file, read the matched text before trusting
  the slug it is attributed to.**
- **A lane's guard state hangs on ONE header line in a hand-edited shared file,
  and its deletion is silent.** A header once vanished while its body stayed, and
  all 4 of that lane's claimed files went to exit 0. Nothing detected it; it was
  found by reading a diff. Both hooks now take the field between the 1st and 2nd
  em-dash and match the WORD `OPEN` in it.
- **`checkpoint-guard.py`'s witness is this session's OWN transcript;
  `.last-checkpoint`'s mtime is never read.** The marker is repo-global, so its
  mtime answers "did somebody checkpoint", not "did I" — reading it let session
  A's checkpoint silence session B's warning, losing B's work silently.
  `.syndicate/**` is excluded from work-at-risk: it is the persistence, not the
  thing persisted. **Exit 1 on Stop is advisory**, not a gate.
- **The 3-lane cap in policy has no enforcement** — `/lane open` checks file
  collisions only and never counts. Eight lanes are open today.

---

## [worktree-test-data] THE 92 RED TESTS IN A SESSION WORKTREE ARE THE ENVIRONMENT, NOT DEFECTS `[measured + shipped 2026-09-03]`

A default session worktree excludes `data/`, and **92 tests fail for that alone**
— established by holding the code constant and varying only the mirror's
presence, then re-checking each candidate IN ISOLATION (2 of the original 103
were test-pollution, not data-dependence).

**They must not be stubbed or skipped.** Their SUBJECT is the data;
`test_ncaaf_team_registry_reachability` states it — *"a value assertion over a
fixture cannot catch either; the fixture is the thing that lied"*. Skipping their
modules would drop **601 PASSING tests**, 353 in `test_archives.py`, the file CI
runs.

**`SYNDICATE_DATA_ROOT` does NOT reach them.** Nine read `REPO_ROOT/data`
directly and ignore the variable — which is why a differential built on that env
var could not see them. Only a real checkout does.

    python scripts/session_worktree.py open --lane <slug> --with-test-data

|  | files | MB |
|---|---|---|
| `--with-data` (full mirror) | 34,690 | 3,547.5 |
| `--with-test-data` | 6,013 | 2,071.2 |

Verified in a FRESH worktree: the 24 files carrying all 118 sweep failures run
**1,031 passed / 0 failed**. Opt-in, because 2 GB across 20+ worktrees is real
disk.

**A METHOD TRAP:** with `data/` present the TEST IDS THEMSELVES CHANGE — several
parametrized tests derive params from the alias map, so an id list captured
without `data/` returns `no tests ran` with it. **Compare by FILE, never by node
id.**

## [test-baselines] TEST BASELINES

- **`tests/test_intelligence_state.py` — `224 passed, 10 subtests passed, 0
  failed in 1361.70s`** `[measured 2026-08-20, lane intel-empty-pool-fallback-test,
  todo.md #495]`. **It costs ~23 minutes, NOT the ~15 this line used to say.**
- **READ THE NEXT TWO BULLETS BEFORE QUOTING THAT NUMBER.** This entry said, for
  six days and in bold, that the file *is NOT "224 green" — that line was wrong
  and is corrected here.* It is now 224 green again. **That is not a reverted
  correction and must not be tidied into one** (`learnings.md` 08-20 forbids
  re-applying a ledger edit by restoring an old revision). The 08-14/15 refutation
  was RIGHT when written; both failures it named have since been resolved on their
  merits:
  - `..._fallback_merge_falls_back_on_empty_pool` — **fixed 2026-08-20**. The TEST
    was the stale side: it asserted a `force_refresh` kwarg `#387` deliberately
    removed from the `collect_all_recommendations:empty_fallback` call site. The
    branch under test had been behaving correctly the whole time. `todo.md` `#495`.
  - `..._recomputes_when_cached_snapshot_is_stale` — **passes on `main`**,
    re-measured 2026-08-20 (72s), individually, not inferred from a suite total.
    Cause of its recovery not investigated.
- **LINEAGE CAVEAT DISCHARGED — this number IS a tip-of-`main` reading.**
  Re-measured at `56b4dd41` (tip): **`224 passed, 10 subtests passed, 0 failed in
  1668.24s`**, identical pass/fail to the first run, which was taken on the primary
  tree's lineage (`d2222426` + the fix), 30 commits behind. **The 34 commits of
  product code between them change nothing for this file.**
- **The COST figure is the one thing that moved: 22:41 then, 27:48 now.** Read
  **~25-30 min**, not ~23. Other sessions were writing the shared `data/`
  throughout both runs, so load is the likely cause — **not isolated, not
  claimed.**
- **HOW the tip run was taken, because a naive re-run would NOT have been valid.**
  `learnings.md` 08-16 forbids a fresh `git worktree` as a baseline for anything
  that reads `data/`, and this suite DOES reach the real disk (`tests/conftest.py`
  isolates `data/prediction_ledger.json` precisely because tests were writing it
  through `data_root()`). So: worktree at tip, sparse-checkout of every top-level
  dir EXCEPT `data/`, and `data/` supplied as a **junction to the primary tree's
  `data/`** — the same bytes the first run used, making the product code the only
  delta. **`SYNDICATE_DATA_ROOT` alone would have been WRONG:** `data_root()`
  honours it, but `REPO_ROOT / "data"` and the per-sport path helpers do not, so
  those reads would have silently fallen back to the worktree's own lossy copy —
  the inert-redirect failure that rule was written about.
- **Neither run is hermetic.** The junction shares a LIVE directory that other
  sessions write, and the suite writes into it. Same exposure both times, so the
  comparison holds; a sealed number is still untaken.
- **Gate against the lineage you are shipping, not against `main`** — the rule
  that made the old `218 passed / 6 failed` at `2b14fbeb` worth recording. It is
  satisfied here, not waived.
- **`tests/test_intelligence.py` is 218 passed / 0 failed on committed `main`**
  `[measured 08-15 ~21:5xZ, lane red-intelligence-tests]`. It was **216/2** at
  the start of that session and 217/1 mid-way. All three reds were real, and
  **two of the three were product defects, not stale tests** — see
  `todo_closed.md` `#436`/`#438`. **It costs ~37 minutes**, single-threaded;
  `pytest-xdist` is NOT installed, so there is no faster path today.
- **The "526 passed, 0 failed" line below is NOT contradicted by that, but it is
  narrower than it reads.** Three `test_intelligence.py` failures existed on
  committed code at 08-15 21:00Z, so whatever that full-suite run covered, it
  either predates them or did not include this file. Treat it as unverified for
  `test_intelligence.py` specifically; the line above is the direct measurement.
- Full suite: **526 passed, 0 failed** after the soccer `as_of` fix `[08-15]`.
- `tests.test_archives` (what CI runs) — **383 pass, 2 skipped, ~6 min**
  `[re-measured 2026-08-19, lane ci-green]` — **but only OUTSIDE 00:00-05:00Z,
  and only on a Central machine.** See the next line; the unqualified version of
  this line was wrong.
- **CI WAS TIME-DEPENDENT — structurally RED ~5 HOURS EVERY DAY — NOW FIXED AND
  VERIFIED INSIDE THE WINDOW** `[run 32323646103, `df8aec91`, 02:09Z, 2026-08-20,
  #482]`. 11 consecutive failures 01:24-01:53Z in the same UTC band without the
  fix, then green with it. **Held overnight: 18 of 19 runs inside 00:00-05:00Z
  green**, a band that was previously 100% red.
- **Test assertions must not depend on the ambient `data/` mirror**
  `[#487, 2026-08-20]`. The one remaining overnight failure was
  `test_archive_launch_links_and_tracker_copy` asserting home-page markers that
  `_home_sport_stack.html` only renders when a sport is present and
  `active_today` — i.e. a function of what the mirror held for
  `central_today_iso()`, not of the page. `build_home_overview` is now pinned to
  a fixture there. **`#480`, `#482` and `#487` are all closed; CI is green in
  both time windows.**
- **`Daily Update`'s cron is REMOVED** `[#486, 2026-08-20, user decision]` —
  "we no longer use that daily update feature, everything runs on render."
  `workflow_dispatch` kept for manual backfill/recovery. Confirmed it did not
  fire on 08-20. Its steps 12-13 have not executed since 2026-07-15 and were
  never proven end to end. 7 `test_archives` tests computed "today" with
  `date.today()` — the runner's date, **UTC** on GHA — while the routes use
  `central_today_iso()`. CDT is UTC-5, so **00:00-05:00Z they disagree** and the
  suite fails no matter what was pushed. Evidence is a clock, not a diff: 16
  consecutive greens 2026-08-19 23:25-23:53Z, then 29 consecutive reds from
  23:57Z; across 45 runs, 28 failures inside the window vs 11 successes outside.
  **Fix applied (assert `central_today_iso()`); a Central dev box CANNOT
  reproduce it, so only a CI run inside the window proves it.** `Daily Update`
  runs 06:00Z and is outside the window.
- **CI RUNS `unittest`, NOT `pytest`, AND `conftest.py` DOES NOT EXIST TO IT**
  `[verified 2026-08-19]`. `ci.yml` runs `python -m unittest tests.test_archives`
  and `daily-update.yml` runs 13 modules the same way, while the documented
  local loop is `python -m pytest tests/`. `tests/conftest.py` is a pytest
  plugin file, so **every autouse fixture in it is absent in CI**. Measured on
  one commit, one machine, one minute: `tests/test_wnba_cards_merge_aliases` was
  `20 passed` under pytest and `FAILED (failures=2)` under unittest. **A green
  local pytest run is not evidence about CI.** Shared setup a CI-run module
  needs belongs in `tests/_cache_isolation.py` (plain functions + a `TestCase`
  mixin, which `conftest.py` now delegates to), not in `conftest.py` alone.
- `daily-update.yml`'s 13-module contract list — **55 pass**
  `[measured 2026-08-19]`, the same count CI reports.

---

## [lane-state-carried] LANE STATE RECORDS CARRIED THROUGH THE 2026-08-18 COLLAPSE — **ARCHIVED 2026-08-19 to `state_archive_2026-08-19.md`, verbatim.**

## [lane-guard-disclaimer-and-worktree-exemption-bugs] TWO REAL BUGS FOUND IN `lane-guard.py`, NEITHER FIXED `[found 2026-08-18]` — **ARCHIVED 2026-08-19 to `state_archive_2026-08-19.md`, verbatim.**

## [split-state-reindex-truncation] `split_state.py --reindex --apply` DELETED EVERYTHING BELOW THE `[subject-index]` TABLE — **FIXED, ON MAIN (`29ab5bfb`), AND NOW IN THE PRIMARY TREE TOO** `[2026-09-04, lane split-state-reindex-truncation]`

`reindex()` rebuilt `state.md` as `head + body[:hdr+1] + rows + [""]` and never
re-emitted `body[hdr+1:]`. Every byte below the table was dropped — silently:
`reindex: 179 subject(s) across 15 file(s)` / `WROTE state.md (index rebuilt)`,
exit **0**. Found by lane `sim-clv-decomposition` when it deleted 55 lines of a
`### [web-oom-leak]` UPDATE block that existed in no commit on any branch.

**The exposure was live and larger than the report.** `origin/main`'s `state.md`
carried **171 non-blank lines** below the table when the fix landed.

**FIXED.** `table_span()` bounds the table as the `|---` separator plus the
CONTIGUOUS run of `| [` rows; the rows are spliced in place and head and tail
carry through untouched. An unclassifiable post-table region — index-shaped rows
separated from the table by other content — **REFUSES with exit 1 and writes
nothing**. A runtime guard refuses if any non-blank, non-row input line would be
lost. Measured on a copy of the real `origin/main` corpus: **171 of 171 tail
lines preserved**, `state_key_check.py` "coherent". 9 new tests, 8 of which FAIL
on the pre-fix code.

**THE PRIMARY TREE NOW HAS THE FIX** `[2026-09-04, later the same day]`. A full
`git pull` was NOT possible and was not forced: the tree is 183 commits behind
and **11 of its 14 modified files collide** with upstream — other sessions' live
uncommitted work (`deploys.md`, `lanes.md`, `learnings.md`, `state.md`,
`render_events.py`, `intelligence_evaluation.py`, two test files, ...). Git
refuses such a merge outright, and stashing a shared tree would yank four
sessions' work mid-turn.

Instead, only the two fixed paths were taken:
`git checkout origin/main -- scripts/split_state.py tests/test_split_state.py`.
Safe because both were byte-identical to HEAD first, so nothing uncommitted was
discarded. **Verified in the primary tree:** 31/31 tests pass, and a DRY RUN on
its real `state.md` reports `post-table region: 56 line(s) PRESERVED (48
non-blank)` and wrote nothing. The rest of the tree is still 183 behind.

**A worktree cut before `29ab5bfb` still has the old script.** Pull first.

**THAT EXPOSED TWO REAL DEFECTS IN `discard-guard.py`, NOW FIXED (`e3a5154f`)
AND LIVE IN THE PRIMARY TREE** — see `[discard-guard-origin-blindness]`.

**Preservation is of CONTENT, not BYTES.** The live `state.md` is MIXED-ending —
580 CRLF lines and a 55-line bare-LF tail written by the appending session's
tool. `load()` + the write have always normalised endings whole-file, so a
reindex shows the whole tail in a diff. That is not a content loss.



## [discard-guard-origin-blindness] `discard-guard.py` CALLED PUSHED CONTENT "NOWHERE ELSE", AND BLOCKED `git restore --staged` — **FIXED (`e3a5154f`) THEN WIDENED TO ALL 610 REFS (`5641ca08`), BUDGET 30s WITH A REAL CEILING (`c56c48a2`); ALL LIVE** `[2026-09-04, lane discard-guard-sees-origin]`

Two defects, both in the OVER-BLOCKING direction — which the hook's own
`reset --hard` comment already names as the dangerous one, because a guard that
cries wolf teaches sessions to override it reflexively.

1. **The predicate consulted only `src` and `HEAD`.** A shared tree runs behind
   routinely — the primary tree was **183 commits behind** — so pushed content
   read as existing nowhere. `git restore --staged scripts/split_state.py` was
   BLOCKED with *"201 uncommitted line(s) in neither HEAD nor HEAD"* while the
   working file was the SAME BLOB as `origin/main` (`363b5528`). Nothing could
   have been lost. `_safe_revs()` now yields src, HEAD, `origin/main` and the
   branch upstream, dropping unresolvable ones so it never fetches. The
   comparison stays PER PATH, so a line is only excused by a copy of the SAME
   file. The message names the revs it checked.
2. **`git restore --staged` was matched though the docstring said it was not.**
   The exemption was documented from day one and never implemented — an
   index-only command that cannot touch a working file was blocked as a
   discard. `_index_only()` implements it: `--staged`/`-S` alone is index-only;
   `--worktree`/`-W`, `-SW`, or neither flag (restore defaults to `--worktree`)
   all reach the file and still refuse.

**VERIFIED LIVE on the primary tree**, hook driven directly so no real checkout
ran: `checkout HEAD -- scripts/split_state.py` → **exit 0 (was 2)**;
`checkout HEAD -- .syndicate/lanes.md` → **exit 2**, "128 uncommitted line(s),
on none of HEAD, origin/main". 5 new tests FAIL on the pre-fix hook, all
over-blocks; **every must-refuse case passes on BOTH versions**, which is what
shows the guard was not weakened. 29/29.


**WIDENED TO ALL REFS `[user request, same day]`.** Four revs is still only four;
content can sit on a branch nobody named, and this repo has **610 refs**, ~170
of them stale `origin/deploy/*`. `_deep_lines` now searches EVERY committed
version of the path across every ref.

**The cost was MEASURED, not assumed** — it had been the stated reason to defer:

| path | commits (all refs) | distinct blobs | unique bytes | exhaustive |
|---|---|---|---|---|
| `.syndicate/lanes.md` | 1,322 | 1,301 | 246 MB | 11.6s / 13.4s |
| `.syndicate/learnings.md` | 660 | 654 | 177 MB | ~7s |
| an ordinary code file | 3-4 | 3-4 | ~30 KB | <0.5s |

Early exit when the line IS found: 3.9s, 120 of 1,301 blobs. `git log --all -S`
(pickaxe) was rejected on measurement, not taste: **5.9s PER LINE**, so three
residual lines cost ~18s where the chunked scan resolves all of them in one
pass. Three git processes regardless of ref count — `rev-list`, one `cat-file
--batch-check` mapping commits to blobs, then chunked `cat-file --batch`.

**THE SWEEP IS NOT UNCONDITIONAL:** it runs only after the cheap revs fail, i.e.
only when the hook is about to BLOCK anyway. Allow-path measured **0.59s ->
0.60s**. **The budget is ONE deadline for the invocation, not one per path** —
per-path let `checkout -- a b c` cost three budgets, and a hook that can stall a
shell for an unbounded multiple of its own limit has no limit. 20s keeps this
repo's worst real case exhaustive: both big ledger files in ONE command measured
**18.7s, both answers complete**.

**A TRUNCATED SEARCH BLOCKS AND SAYS SO.** It claims "all N committed version(s)
across every ref" only when it read all of them; otherwise SEARCH TRUNCATED plus
the knob to raise. A partial search must not be reported as an exhaustive one.

**END-TO-END PROOF, unplanned and better than the tests:** installing the new
hook was itself BLOCKED by the old one over 6 lines "on none of HEAD,
origin/main" — every one of which was in pushed commit `e3a5154f`. The identical
command under the new hook exits **0 in 0.58s**, while `.syndicate/lanes.md`
with 143 truly unreachable lines still refuses in 11.2s. Same-instant A/B on the
live tree: **147 flagged -> 143**. 40/40 tests; 8 fail on `e3a5154f`.


**BUDGET RAISED TO 30s, AND MADE A REAL CEILING `[user request, c56c48a2]`.**
Raising it exposed that it was not a ceiling at all: `_git` used a FIXED 30s
per-call timeout, and `_blob_ids`' `rev-list --all` — the slowest call, 3-5s and
growing with history — runs BEFORE the chunk loop's deadline check. True bound
was budget + timeout, **60s for a 30s budget** — the "unbounded multiple of its
own limit" the constant's own comment rejects one function above. Every git call
in the sweep now takes its timeout from the time LEFT on the shared deadline.
Measured same-instant on the live tree with the budget forced to 1s:

| version | elapsed | multiple of budget |
|---|---|---|
| `5641ca08` fixed per-call timeout | 6.23s | **6.2x** |
| `c56c48a2` deadline-derived | 1.30s | 1.3x |

**The subtle half:** when the deadline kills the blob LISTING, `_blob_ids`
returns empty — indistinguishable from "this path has no committed version at
all". The first means UNKNOWN, the second NOWHERE. It now reports INCOMPLETE
there, while a path that genuinely has no history is still NOT labelled
truncated.

**Why 30 and not 20:** worst real case (both big ledger files, one command,
content genuinely nowhere) is **18.7s cold / 14.6s warm**. Against 20 that is a
1.3s margin, which is not headroom; against 30 it is ~11s.

**44 tests, and an HONEST NOTE: all 44 pass on `5641ca08` too.** They are
REGRESSION GUARDS, not proof of this change — a fixed-vs-derived timeout cannot
be distinguished in a throwaway repo where every git call is instant. The
evidence for the ceiling is the measurement above, not the suite.

**THE WIDENING PAID OFF TWICE IN REAL USE.** Installing `5641ca08` was BLOCKED
by its predecessor and needed `SYNDICATE_ALLOW_DISCARD=1`; installing
`c56c48a2` needed **no override**, because the deep sweep found the outgoing
version in history by itself. Separately, a later run on `lanes.md` returned
exit 0 in 7.2s with **122 lines still unaccounted for by the cheap revs** — all
found in OLDER commits. A line can sit in an older `origin/main` commit and not
at its tip; only the all-refs sweep sees that.

## [git-store-onedrive] ONEDRIVE MANAGES `.git` AND `.syndicate`, AND IT SILENTLY BREAKS `git worktree remove` `[2026-09-06, lane git-out-of-onedrive, commits cef79cf9 + 28ae6b5c, NO DEPLOY]`

The repo is at `C:\Users\<user>\OneDrive\Coding\Syndicate`, so OneDrive's Cloud
Files filter manages the working tree AND the git store. **The store is 5.9 GB**
and is being synced to the cloud continuously. Measured attributes:

    .git                    Directory + ReparsePoint + PINNED
    .git\worktrees\<entry>  ReadOnly + Directory + Archive + ReparsePoint + PINNED
                            and the logs/ + refs/ FILES inside each are ReadOnly
    .syndicate              ReadOnly + Directory + Archive + ReparsePoint + PINNED

**WHAT THIS BREAKS, and it fails half-way rather than loudly.** Windows honours
`ReadOnly` on FILES, not directories. So `git worktree remove` deletes the
worktree contents, then cannot delete `.git/worktrees/<name>` — leaving BOTH a
stale registration and an empty husk directory. **Three occurrences in one
session**, including on the cleanup's own worktrees.

**AND THE STALE REGISTRATIONS ARE INVISIBLE.** A registration whose `gitdir`
file is missing is hidden from `git worktree list` while still occupying
`.git/worktrees/`. Measured 2026-09-06: `list` said **83** while the directory
held **118**. 36 dead entries had accumulated unseen. Cleaned to 83/83/0.

**THE OBVIOUS REMEDY DOES NOT WORK.** `attrib -R /S /D` left the count unchanged
(118 ReadOnly before, 118 after). What works is PowerShell
`Remove-Item -Recurse -Force`, because `-Force` overrides `ReadOnly` itself.
Do not reach for `attrib`.

**Relocation tooling exists and has NOT been run:** `scripts/move_git_store.py`
(dry run by default, refuses on a dirty tree — it correctly returned
`REFUSE: 10 tracked file(s) modified`), `tests/test_move_git_store.py`, runbook
`docs/ai_context/git_store_relocation.md`. Worktree pointers are ABSOLUTE, so
84 of them need rewriting; same-volume only, because 5.9 GB across volumes is a
non-atomic copy+delete.

**MOVING `.git` WOULD NOT FIX THE LEDGER.** `.syndicate/` carries the same
attributes and is in the WORKING tree, so the CRLF-rewrite warning on every
ledger append and OneDrive arbitrating ledger writes are unchanged by it.
Ending that class means moving the repo, not the store.

## [full-suite-run-method] RUNNING THE FULL SUITE ON THIS MACHINE NEEDS BATCHING, AN ISOLATION RETRY AND A PINNED MANIFEST — and the failure LIST expires within hours `[2026-09-05/06, lane nfl-fantasy-artifact-root]`

**`py -3 -m pytest tests/` IN ONE PROCESS CANNOT FINISH.** 989 files / ~15.7k
tests died at 31% with `OSError [WinError 1450] Insufficient system resources`
creating a tmp_path, then INTERNALERROR/MemoryError formatting that error. Not a
test defect: 4,866 tests had passed with 0 failures at that point.

**A LONG-LIVED PARENT IS NOT ENOUGH EITHER.** Batching into 25 pytest processes
ran batches 1-3 clean then failed EVERY batch from 4 on — WinError 1450 now on
`stat()` of ordinary repo files, plus rc=3221225626 and conftest ImportErrors.
Proof it was the environment: batch 4 re-run ALONE returned **489 passed**, and
batch 3 went "5 failed, 2 errors" -> "375 passed" between runs. **A batch result
is not trustworthy until reproduced in isolation.** Cause is contention — other
sessions running pytest concurrently, one holding 16.7 GB.

**THE CERTIFIED PASS (method that worked):** 25 batches of 40, one process each,
**manifest PINNED** (a fresh glob re-slices every boundary — measured 987 -> 989
files inside one hour, so a batch index stops naming the same files between
restarts and a file can run twice or never), per-batch audit trail, isolation
retry only for environmental signatures or NO SUMMARY, and a `settled` rule so a
recorded failure is never re-run. Result: **989/989 files covered exactly once,
0 skipped, 15,256 passed / 16 failed.**

**THE FAILURE LIST FROM THAT PASS IS DEAD — DO NOT QUOTE IT.** Re-checked hours
later against current `origin/main`: **all 16 green**. Peers had landed the
fixes while the run was in flight (`0ad1480d`, `c353b47d`, `ff022d5d`,
`782a057b`). The COVERAGE method holds; the failure list expires within hours on
a repo with this many concurrent sessions. **Re-baseline against `origin/main`
before offering any suite failure as work.**

**AND A WORKTREE WITHOUT `data/` CANNOT ANSWER THE QUESTION.** The same re-check
read "369 passed, 32 skipped" and looked green; the 32 skips WERE the
data-dependent tests. Reading a skip count as a pass is how a real failure hides.
