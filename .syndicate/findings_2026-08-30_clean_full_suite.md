# main was NOT green at `7cea63c5` — 46 real test failures `[2026-08-30, MEASURED]`

**This is the clean-control reading the session owed.** A first attempt gave 60
failures and was WORTHLESS: it ran 5h17m against the SHARED primary tree while
that tree was being fast-forwarded twice and written to by several sessions, so
it smeared across many states. At least 9 of its 60 were already explained.

## How this one was made trustworthy

| property | value |
|---|---|
| worktree | detached, `/c/tmp/cleanrun`, nobody else's path |
| sha at start | `7cea63c5d1cdd5ea93554aae0e0fc7eeea762555` |
| sha at end | **identical** — the code never moved under the run |
| `data/` present | yes (absent `data/` fabricates soccer failures — see learnings) |
| duration | 3:17:27, 06:23:48Z → 09:41:56Z |
| pytest exit | 1, captured from pytest itself, not from a trailing `tail` |

**RESULT: 46 failed, 13,056 passed, 51 skipped, 1 xfailed.**

**An integrity guard fired and was checked, not waved away.** `dirty@end` was 7,
and my own footer said that voids the result. It does not: **0 tracked `.py`
files were modified.** The dirt is test-generated — a live-lens fixture, a
kalshi_markets snapshot, two vendored WNBA schedules, plus two new output dirs.
Side finding worth someone's time: **tests write into `data/` and `vendor/`.**

## Two diagnoses CONFIRMED by absence

- **`test_deploy_preflight` — 0 failures here, 6 in the smeared run.** Those 6
  read the LIVE shared deploy claim; none was held during this run. Confirms the
  mechanism, and confirms that reverting my attempted fix (which took 6 → 8) was
  right. The defect is still open: the tests are not isolated from live state.
- **`test_artifact_publisher` / `test_home` — 0 failures.** The `beaf5533` fixes
  hold at this SHA, independently of the tree they were made in.

So 60 → 46 is fully accounted for: 3 fixed mid-run, 6 claim-dependent, 5 other
mid-run states.

## The 46, and NONE of them are this session's

They span 26 files this session never touched.

**45 named, 46 counted — and the gap is stated rather than rounded away.**
pytest's own tally says `46 failed`; its `-rf` short summary names 45 unique
ids, with no duplicates. The unnamed one is most likely a SUBTEST or teardown
failure (the run reports `434 subtests passed`), which counts toward the total
but is not emitted as a `FAILED <id>` line. So the breakdown below covers 45 of
46; one failure has no id here and would need `-rA` or a re-run to name.

```
   8  test_open_bet_live_status.py
   5  test_mlb_sim_run_reconcile.py
   4  test_ncaaf_picks_local.py
   2  test_kalshi_catalogue.py
   2  test_ncaaf_oddsapi_game_lines.py
   2  test_ops.py
   2  test_refresh_odds_sources.py
   2  test_wnba_refresh_runner.py
   1  test_lane_guard_files_forms.py
   1  test_layer2_movement_live_segment.py
   1  test_live_refresh_loop.py
   1  test_memory_watchdog.py
   1  test_nba_refresh_runner.py
   1  test_ncaaf_team_registry_reachability.py
   1  test_nfl_props.py
   1  test_nfl_props_board.py
   1  test_odds_control_plane.py
   1  test_probability_differential.py
   1  test_prop_player_keying.py
   1  test_quote_join_index_equivalence.py
   1  test_refresh_state_store.py
   1  test_smartsim2_calibration_profile.py
   1  test_soccer_board_mlb_parity.py
   1  test_soccer_fixture_pair_resolution.py
   1  test_soccer_read_scope.py
   1  test_wnba_grader_root_per_file.py
```

## Scope of the claim, stated as part of the claim

- This is **"was main green at `7cea63c5`"**, not "is main green now" — peers
  push steadily and the SHA was already behind when the run finished.
- The 46 are UNTRIAGED. Real defect vs environment-sensitive test is unknown per
  case; this session's own experience is that both exist in this repo.
- **51 skipped, against 6 in the smeared run.** Some is the roster-dependent
  gating another lane added 2026-08-30 (`needs_soccer_rosters`), but that was
  NOT verified for all 51 and a skip that should be a run is invisible.

## TRIAGE PROGRESS — 46 → 21 untriaged

Two clusters closed. **Neither was a defect in `main`, and neither was this
session's.** Both were TEST defects, and they failed in different ways, which is
the point: a raw failure count mixes kinds that need different remedies.

### `test_open_bet_live_status` (8) — FIXED `5367af5a`

ONE stale stub, shared by all 8 via the `_render` helper. It pinned
`_live_portfolio_payload`'s signature before the `?venue=` filter existed
(2026-08-28), so the route's `venue=venue` raised `TypeError`, Flask returned
**500**, and the assertions failed on absent team names rather than on anything
they test.

TEST-ONLY, verified: production really does pass `venue=venue`
(`intelligence.py:4728`), so the stub was the wrong half. Fixed with `**kwargs`
rather than re-listing the signature — naming the kwargs just schedules the next
occurrence for the next filter added. 21 pass in the file, 139 across the
portfolio suites.

**The same defect was fixed in `test_venue_balances.py` the day before and not
grepped for**, which is why these survived. One command finds every instance:

    grep -rn "lambda date, show_all=False, on_date=None:" tests/

Checked and deliberately NOT changed: the sibling stub at line 151 takes only
`date` because it stubs `read_portfolio_plan`, which really does take only that.

### `test_mlb_sim_run_reconcile` (5) — DIAGNOSED, NOT FIXED

**Test pollution. The code is fine.** Three readings at the SAME SHA:

| how run | result |
|---|---|
| the file alone, at `7cea63c5` | **12 passed** |
| the file inside the full suite, `7cea63c5` | **5 failed** |
| `test_live_refresh_loop.py` → this file | **1 failed** (`test_restart_orphan_is_recorded_not_silently_cleared`) |

So `test_live_refresh_loop.py` is *a* polluter; the full run failed 5, so there
are likely others.

**Mechanism, and the polluter's own comment states it:** *"only state this test
itself created gets cleaned up, so running the suite while a REAL local sim is
in flight doesn't delete that sim's live pointer."*
`_mlb_sim_active_pointer_path()` resolves through `_mlb_sim_runs_state_dir()` —
a REAL on-disk path, not a tmp dir. `test_mlb_sim_run_reconcile` patches
`live_refresh_loop.reports_root` to a `TemporaryDirectory` and seeds its own
pointer via `_seed_pointer`, but the pointer path is not covered by that patch.
Two files reading and writing one real file.

**NOT FIXED ON PURPOSE.** Unlike the stub above, the remedy is a judgement call
on the MLB sim reconciliation path: either isolate `_mlb_sim_runs_state_dir` in
these tests, or make the reconcile tests independent of pre-existing pointer
state. Both change what the tests assert — and the polluter's shared-path
behaviour is DELIBERATE, so that a suite run does not delete a live sim's
pointer on a developer's machine. That trade-off belongs to whoever owns the sim
path, not to a triage pass.

### `test_ncaaf_picks_local` (4) — STALE TESTS, deliberately NOT touched

**Not pollution, and not fixed-since.** These fail IN ISOLATION at both
`7cea63c5` and current `main`, which is what separates this cluster from the
one above.

    AssertionError: 'NCAAF pick serving gate'
                 != 'NCAAF Enhanced Totals Engine picks runtime'

`syndicate/features/ncaaf/picks.py:634` returns that title because **`95602d2a`
(2026-08-19) deliberately SUPPRESSED NCAAF picks.** That commit is one of the
better-evidenced in this repo: leak-free, prior-season SP+ against realised 2025
margins, n=220, 40 seeds — model MAE 13.763 vs market 11.586, paired dMAE
**+2.176, SE 0.518, t = +4.20**. Every scale 6..24 loses, which is why the
response was a serving GATE rather than another parameter sweep. `pick_gate.py`
is DEFAULT-DENY on the stated ground that "a gate that maps 'never measured'
onto its permissive branch fires only for failures someone already went looking
for".

**The tests assert the PRE-suppression contract** — that NCAAF picks are served.
They were left behind when the gate landed, the same shape as the `?venue=`
stub: one lane changed a contract, a sibling test file did not follow.

**NOT REWRITTEN, and the reason is stronger than for the cluster above.** Making
these pass means asserting the current gated behaviour on a live money surface
that was suppressed on a significance test. Whoever owns `pick_gate.py` should
decide per test whether it becomes "the gate DENIES" or is deleted as testing a
retired path. A triage pass rewriting them risks encoding "picks are served"
back into the suite — exactly what the gate exists to prevent.

**A GAP IN THE OTHER DIRECTION, and it is the more important half:** the
suppression has been live 11 days and its tests were never updated, so **nothing
in the suite currently pins the gate's behaviour on this surface.** The
protective behaviour is unasserted. That is worth more attention than the four
red lines.

### Group B (2) — FIXED `7c1e842c`: tests that could never pass HERE

- `test_source_root_helpers_prefer_render_disk` compared an UNRESOLVED expected
  path against production's `.resolve()`d one. A no-op on POSIX for
  `/opt/render/...`; on Windows `.resolve()` prepends the drive, giving
  `WindowsPath('C:/opt/...')` vs `WindowsPath('/opt/...')`. Resolving the
  expected side is symmetric with production and cannot mask a real mismatch.
- `test_the_real_ledger_parses_and_claims_something` asserted `> 50` claims and
  hit **22 — because the LEDGER shrank legitimately**: lanes closed, and a
  phantom sweep released 121 of 133 claims held by dead sessions. A floor on
  total claims measures how much work is open, not whether the parser works.
  Replaced with a distinct-lane floor and CALIBRATED: verified it still rejects
  returns-nothing, reads-one-block and only-two-lanes.

### Group D (6) — the unexamined tail, now examined

| test | verdict |
|---|---|
| `test_soccer_fixture_pair_resolution` | **deliberate semantics** — see below |
| `test_smartsim2_calibration_profile` | contract drift: NCAAF profile gained `goal_line_touchdown`, `field_goal_attempt_base_probability` |
| `test_ncaaf_team_registry_reachability` | `resolve_team('Albany State GA')` -> `None`; alias gap `exchange-join-refusals` is actively working |
| `test_wnba_refresh_runner` (2) | *"cli refresh path should not load"* — UNEXAMINED |
| `test_live_refresh_loop` | sleep called 6x (`0.15`x5 then `900`), test expects once — a poll loop was added |

#### The one that matters: a red test is the only thing that WAS pinning side-order

`test_the_join_refuses_when_the_sides_are_swapped` fails because
`_teams_match` now returns **True** for a swapped fixture. That is INTENDED:
`c5a89b44` made the pair resolver authoritative and compares the fixture as an
UNORDERED pair, explicitly because *"a wrong-GAME check must not be entangled
with a wrong-SIDE one"*. The split is right.

**But nothing replaced the assertion.** Its docstring is the hazard verbatim:
*"Matching a swapped fixture would pair our row with the opposite side of the
same game."*

**WHY IT IS NOT BITING TODAY, and it is NOT orientation.**
`orientation_flip_counts` in `polymarket_board_join` is *"Diagnostic only; the
flip is never applied."* The protection is a REFUSAL one layer down:
`_resolve_outcome_side` raises `team_side_needs_verified_yes_leg` for any
positional home/away side unless `SYNDICATE_POLYMARKET_ALLOW_TEAM_SIDE=1`,
which is **NOT in `render.yaml`** — off in production, and observed firing live
2026-08-29. So for soccer: totals are orientation-insensitive, spreads are not
carded, h2h is refused outright.

**THE SEQUENCING RISK.** `live-venue-order-placement` lists that same refusal as
gate #1 blocking execution and states *"an arb IS a moneyline trade"*. **The
moment h2h is unblocked, orientation becomes load-bearing on a live-money path,
and the suite will not catch a swapped-fixture bet** — because the test that
would have is red. The protection today is a gate someone is actively trying to
lift. Flagged to that lane 2026-08-30; NOT fixed here (claimed file, semantics
call on their path).

### What this says about the remaining 21

Five causes now, still **zero CONFIRMED production defects** — though "zero
confirmed" is a statement about what has been examined, and 2 tests
(`test_wnba_refresh_runner`) remain unexamined rather than exonerated.

| cause | count | shape |
|---|---|---|
| a lane changed a contract, siblings did not follow | ~11 | fails everywhere |
| pollution (real on-disk state shared between files) | ~8 | passes alone, fails in suite |
| environment-dependent (POSIX paths, live ledger) | 2 | can never pass here — FIXED |
| deliberate behaviour the test predates | 5 | fails everywhere, code is right |
| unexamined | 2 | — |

**A raw count from this file remains an UPPER BOUND on real defects.** The
dominant cause is contract drift between lanes, which is a coordination
signal, not a code-quality one. Triage in isolation FIRST: the
isolation-vs-suite comparison at one SHA separated every cluster in minutes,
and it is the only step that tells pollution from a real contract change.

## For whoever picks this up

Start with the clusters — `test_open_bet_live_status` (8),
`test_mlb_sim_run_reconcile` (5), `test_ncaaf_picks_local` (4) — and for each,
reproduce in a CLEAN detached worktree at `origin/main` with `data/` present
before attributing anything to a commit. Full output: the run wrote
`CLEAN_RUN_RESULT.txt` into `/c/tmp/cleanrun`, which is a throwaway worktree and
will not survive a prune; the per-file counts above are the durable record.

