# ~~19 REAL REGRESSIONS~~ — **RETRACTED THE SAME DAY. 15 of the 19 are a MEMORY FLOOR THE CONTAINER CANNOT REACH, not breakage.**

> **READ THIS FIRST. The title below is wrong and is kept only so the retraction
> has something to point at.** The traceback arrived after this was filed and
> falsifies the central claim. What survives is at the bottom under WHAT STILL
> STANDS.

## THE RETRACTION `[2026-09-08 ~21:30Z, substrate render]`

The 13 intelligence-layer failures are **not regressions**. Their traceback, from
the cron:

    [intelligence] OVERVIEW_STOPPED_FOR_MEMORY next_sport=mlb floor=expensive
      floor_mb=3000 sports_done=0 snapshot={'current_mb': 263.7, 'max_mb': 2048.0,
      'headroom_mb': 1915.4}
    [intelligence_state] MEMORY_GUARD_ABORT stage=pre_source_state_fingerprint
      floor_mb=1900 snapshot={'headroom_mb': 1843.3, 'min_required_mb': 1900.0}

**MLB's overview floor is 3000 MB. The cron's ENTIRE container limit is 2048 MB.**
The floor is unsatisfiable there by construction, so MLB is skipped every time and
the assertions see an empty overview — `[] != [{'slug': 'mlb'}]`, `0 != 10`,
`StopIteration`. On a developer machine headroom exceeds 3000 MB and all 13 pass.

`intelligence.py:2915-2930` ALREADY DOCUMENTS THIS, measured in production
2026-08-27: *"the expensive floor is unreachable at rest"*, eighteen consecutive
refresh-worker builds reading `BOARD_OVERVIEW_READY sports=0`. It is a known
property, not a new defect.

The same class covers the two `test_memory_headroom_snapshot_reports_insufficient_and_sufficient`
tests: they must produce a SUFFICIENT reading, which a 2048 MB box cannot give
for a high floor. **15 of 19 accounted for.**

## THE ERROR IN MY REASONING, WHICH IS THE REUSABLE PART

I qualified these as regressions on two checks — the test existed at baseline
commit `a20204dd`, and it still fails in ISOLATION on the cron. Both were true
and both were consistent with the tests never having passed on that host.

**THE MISSING PREMISE: the baseline was recorded in a DIFFERENT ENVIRONMENT, and
the cron did not exist when it was taken.** It was recorded 2026-08-26 under
`-n auto` on a machine with ordinary RAM; `ci-suite` was created 2026-09-07.
"Not in the baseline's failing set" therefore means "passed on some other box",
NEVER "passed here". I compared a set recorded on one host against a run on
another and read the difference as change over TIME. It was change over PLACE.

**A baseline is a fact about an ENVIRONMENT as much as about a commit. Comparing
across hosts requires establishing the hosts are comparable, and I did not.**

Peer session 2edf8b82 supplied the reading that broke it open: the 16 tests pass
on their machine both at merged head AND at `1eb59ce7`, so no commit of theirs
moves them in either direction — which is what a time-based regression would
have to do.

## WHAT STILL STANDS

- **The suite completes on the cron.** Chunking works; that is `#647` and is
  unaffected.
- **4 of the 19 are still unexplained** and are the only live candidates:
  `test_refresh_odds_sources.py::SoccerLeagueScopeTests` x2 and
  `test_soccer_live_gates_wiring.py` x2. Their tracebacks were truncated out of
  the run above and have NOT been read. **Do not call these regressions either
  until they are.**
- **The baseline still must not be regenerated**, but for a different reason
  than I gave. Not "it would hide 19 regressions" — it would record, as
  permanent known failures, tests that fail ONLY because the runner has 2 GB.
  That bakes a host property into a commit-level gate.
- **The real question this exposed is better than the one I filed:** should a
  16,418-test suite whose intelligence tests need 3 GB of headroom run on a
  2 GB cron at all? The tests are not wrong and the guard is not wrong; the
  RUNNER is too small for this subset. That is `#647`'s sizing question
  returning in a different costume.

---

*Everything below is the ORIGINAL filing, preserved unedited. Its evidence is
sound; its CONCLUSION is retracted by the section above.*

# (original) 19 REAL REGRESSIONS ON `main`, FOUND THE FIRST TIME THE FULL SUITE EVER RAN ON THE CRON

`#648`. Lane `render-cron-failures`, 2026-09-08. Substrate: **render** — every
number here is from a cron run, not a checkout.

## What happened

`ci-suite`'s pytest step had never completed: OOM-killed at 2Gi in every worker
configuration. Chunking fixed that (`#647`), the suite ran end to end for the
first time, and it immediately reported **25 new failures against the recorded
baseline**. This file establishes that **19 of them are genuine breakage on
`main`**, and separates them from the 6 that are not.

## Why this was invisible until now

- `ci.yml` has been billing-locked since **2026-08-22** — no workflow run has
  succeeded since, so nothing gated any of the ~420 commits that landed after.
- The `ci-suite` cron was created 2026-09-07 to replace it and **could not
  complete the pytest step**, so it never reported either.
- The archive suite that DOES run (`tests.test_archives`, 386 tests) is green
  and covers none of these.

So the gap is not "a test started failing today". It is: **for 17 days nothing
was watching, and this is the first look.**

## The discrimination, and it took three runs to get right

A failure list from a chunked run is ambiguous three ways — real breakage,
chunking artifact, or an unrecorded new test. Each was ruled out separately.

**1. Did the test exist when the baseline was recorded?** `git show
a20204dd:<path>` per failing test, checking for `def <name>(`. The baseline was
recorded 2026-08-26 and the suite has since grown **11,745 → 16,418** tests, so
"new test, never recorded" was a live explanation. It accounts for 5 of 25.

**2. Does it fail in isolation on the SAME host?** The 9 affected files, alone,
on the cron: `21 failed, 790 passed`. Failures that survive maximum isolation
are not chunking artifacts.

**3. THE FIRST ISOLATION RUN WAS INVALID AND IS RECORDED HERE SO NOBODY REPEATS
IT.** It pointed the cron's start command straight at `python -m pytest`, which
bypasses `run_ci_suite._step_env()` — the scrub that removes Render's own
environment variables. Result: **116 failed / 698 passed**, dominated by
`RuntimeError: SYNDICATE_DATA_ROOT must be set when hosted storage is required`
and `Local state backend not allowed in multi-service deployment`. The suite was
measuring its host again. Re-run with `env -u RENDER -u RENDER_SERVICE_ID …` it
gives the 21 above.

    **The scrub lives inside `run_ci_suite` only. Anything that runs this
    suite on Render by another entry point inherits the original bug**, and
    116-vs-20 is the size of that effect on 9 files.

## The 19

| file | n | tests |
|---|---|---|
| `test_intelligence_state.py` | 8 | `board_publication_*` ×4, `build_candidate_pool_does_not_embed_full_odds_history_payload`, `compute_board_publication_response_caps_unbounded_default_candidate_count`, `compute_response_recomputes_when_cached_snapshot_is_stale`, `default_candidate_cap_is_env_tunable` |
| `test_intelligence.py` | 5 | `build_intelligence_overview_*` ×3, `OverviewCountsTraceCoverageTests` ×2 |
| `test_refresh_odds_sources.py` | 2 | `SoccerLeagueScopeTests` ×2 |
| `test_soccer_live_gates_wiring.py` | 2 | `test_gate3_prices_off_soccers_real_sim_count`, `test_gate3_home_framing_matches_the_market_term` |
| `test_live_refresh_loop.py` | 1 | `test_odds_refresh_memory_headroom_snapshot_reports_insufficient_and_sufficient` |
| `test_memory_observability.py` | 1 | `test_memory_headroom_snapshot_reports_insufficient_and_sufficient` |

**13 of 19 are the intelligence layer, across two files.** That concentration
suggests ONE root cause rather than thirteen, and is the cheapest place to start.

## The 6 that are NOT regressions, and why each is excluded

| test | verdict |
|---|---|
| `test_heap_roots.py::WiderRootTests` ×4 | file added 2026-09-05, after the baseline; **and** passes in isolation. New test, chunk-order sensitive. |
| `test_evaluation_ledger_projection::test_max_chunks_bounds_a_run…` | file added 2026-09-04, never in a baseline. Fails in isolation too, so it is a genuinely failing NEW test — worth fixing, not a regression. |
| `test_home_mlb_live_lens_states::test_the_cache_is_keyed_on_content_not_on_a_clock` | existed at baseline, but **passes in isolation** — a chunking artifact. |
| `test_memory_observability::test_malloc_arena_snapshot_degrades_quietly_off_glibc` | the inverse: fails ALONE, passes chunked. Asserts a snapshot `is None` off glibc; Render is glibc. Host-dependent by construction. |

## Two things I got wrong, recorded because the reasoning was tempting

**"The memory-headroom failures are casualties of the container being at 98%."**
The full run ended with `memory_current 2004 / 2048 MB, headroom 43 MB`, so a
test asserting on headroom failing looked explained. It is not: both persist in
the isolated run, which had 790 tests instead of 16,418 and nothing like that
pressure. **A plausible mechanism that survives no test of itself is a story.**

**"`test_intelligence_state.py` passes 228/228, so its 8 failures are an
isolation artifact."** That run was a Windows worktree with no `data/`. All 8
fail on the cron in isolation. This is exactly the standing FORBIDDEN rule
(`learnings.md` 2026-08-19) — a green local pytest run is not evidence about CI —
and the confound was the ENVIRONMENT, which is the half that rule is about.

## What is NOT established

- **No root cause.** Nobody has read a traceback yet; `--tb=line` gave names and
  assertion lines, not diagnoses.
- **Not attributed to a commit.** 420+ commits landed unwatched; no bisect ran.
- **Not "19 distinct bugs".** 13 share a subsystem and may share one cause.
- **The baseline is NOT regenerated, deliberately.** Doing so absorbs all 19 into
  "known" and blinds the gate to them in the same commit meant to make it
  trustworthy — `pytest_baseline.py`'s own docstring: *"a permanently-tolerated
  failure is how a gate becomes decoration."* Regenerate only after these are
  fixed or consciously accepted.
