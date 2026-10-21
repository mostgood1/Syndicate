# Full suite: 464 non-passing in a sparse worktree collapses to SEVEN on the fleet checkout — ~98.5% was missing-`data/`, and the real list is seven named tests

`[2026-10-21 01:25Z / 2026-10-20 20:25 CDT]` session `4ab694ed`
`[no outcomes used; this is a test-suite measurement]`

## The two runs

| | sparse worktree (`C:\tmp\ledger-1002`) | fleet checkout (`/home/amyn/Syndicate`) |
|---|---|---|
| scope | whole suite, 1,757 files | the 45 data-backed failing files |
| `data/` + `vendor/` | **absent** (sparse) / added `vendor` mid-run | **both present** |
| commit | current with `origin/main` | HEAD **`3567ff3bb`** |
| result | **24,583 passed · 331 failed · 133 errors · 250 skipped** | **1,656 passed · 7 failed · 3 skipped** |
| wall time | 5h 37m (`-n 4`, Idle) | minutes (`nice -n 19`) |

**So ~98.5% of the apparent failures were missing-`data/` artifacts.** The same
45 files produced ~464 non-passing without `data/` and **7** with it. Sampling
had already pointed this way — `test_archives` renders *"No stored WNBA slates
are available yet"* with `Stored slates: 0`, and the NCAAF registry returns
`None` for `'UAlbany'` / `'App State'` — and the fleet run is the confirmation.

## The seven

```
tests/test_archives.py::HomeBoardTests::test_mlb_live_lens_empty_date_does_not_inject_fake_sample_games
tests/test_intelligence.py::IntelligenceBlueprintTests::test_intelligence_blotter_view_includes_odds_projected_and_live_columns
tests/test_nba_live_resim.py::test_league_keyword_threads_through_storage_and_names
tests/test_ncaaf_team_aliases.py::test_match_event_blob_can_now_resolve_an_fbs_pairing
tests/test_probability_differential.py::test_every_converter_is_registered_or_excused
tests/test_slate_date_timezone_discipline.py::SlateDateTimezoneDisciplineTests::test_no_new_timezone_ambiguous_date_calls
tests/test_soccer_live_gates_wiring.py::test_gate3_unwired_sport_still_fails_closed
```

**None of the seven is in anything this session touched.** All ten suites I wrote
or repaired today are green.

## Against the existing triage (`#697` / `ci-suite-red-1015`)

`#697` is OPEN and says the fleet `ci-suite` "has been RED every day since at
least 2026-10-02: 21 baseline regressions ... 18 owed to their lanes". Lane
`ci-suite-red-1015`'s goal is that **every NEW FAILURE is fixed, attributed to
the lane owning its file, or recorded as a deliberate baseline**, and its
verification awaits "the next scheduled ci-suite run's NEW FAILURE list". This
is such a list, on a newer SHA. Checked against that lane's block:

- **already named there** (so possibly known baseline, not new):
  `test_archives.py`, `test_probability_differential.py`
- **new to that lane**: `test_intelligence.py`, `test_nba_live_resim.py`,
  `test_ncaaf_team_aliases.py`, `test_slate_date_timezone_discipline.py`,
  `test_soccer_live_gates_wiring.py`

## NOT ATTRIBUTED, deliberately

I ran with `--tb=no -rf`, which yields **names without causes**. So I have seven
node ids and no diagnosis, and I am not guessing at one — today already cost a
peer a debugging session because I asserted a cause ("not mine") from a control
that could not support it.

What I will say is a **hypothesis worth testing first**, because three of the
seven read as standing repo-hygiene guards rather than feature breaks:

- `test_every_converter_is_registered_or_excused`
- `test_no_new_timezone_ambiguous_date_calls`
- `test_gate3_unwired_sport_still_fails_closed`

Guards of that shape typically fail when someone adds a converter, a
timezone-ambiguous date call, or an unwired sport **without** registering it —
cheap to confirm by reading the guard's own allowlist, and each then attributes
to whichever lane added the unregistered thing. **Unverified.**

## How to reproduce, and the conditions that matter

```
# in the fleet checkout, which has data/ and vendor/
cd /home/amyn/Syndicate
nice -n 19 /home/amyn/.venvs/syndicate/bin/python -m pytest <the 45 files> \
    -q --no-header --tb=no -rf -p no:cacheprovider
```

- **Safe to run there** because the suite isolates its writes: `conftest.py`'s
  autouse `_isolate_reports_root` and `_isolate_intelligence_state` redirect to
  tmp dirs, and a guard keeps the suite out of the git-tracked `data/` mirror
  (tested by `tests/test_data_mirror_write_guard.py`). Verified before running,
  not assumed.
- **But it is the live production checkout.** The run peaked at **6.5 GB RSS**
  on a host already near **14.8 GB**, while the fleet was mid-cycle. Not
  something to repeat casually, and `nice -n 19` is not optional.
- **Drop `--tb=no`** when someone takes these: the whole gap in this finding is
  the absence of tracebacks.

## What this does NOT establish

- **No cause for any of the seven**, as above.
- Nothing about the other ~1,712 test files: the fleet run covered only the 45
  that failed for data reasons. A file green in the sparse worktree was not
  re-checked with `data/` present, so a data-dependent test that passes
  vacuously without data would not have been caught.
- The sparse-worktree run is the right instrument for "did this session break
  anything" (it did not) and the **wrong** one for "is the suite green".
