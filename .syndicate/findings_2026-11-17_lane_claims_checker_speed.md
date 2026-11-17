# Findings 2026-11-17 — `check_lane_claims.py` 2.2x faster; output byte-identical

Lane `lane-claims-checker-speed`, session f60eabcb. This follows lane `lane-claims-parse-memo`
(`findings_2026-11-17_lane_claims_parse_memo.md`), which left this check as the session-start hook's
critical path. On main as `3eacafa2a`. It is tooling only: no fleet deploy and no betting change.

## Verdict

**Serial, alternating old/new pairs.** The old script is a copy of `8c2f131cc`. Both arms use x64
`python`, the interpreter `session-start.sh` uses. `CLAUDE_PROJECT_DIR` points at the tree under test.

| tree | window (CST) | pairs | old median | new median | ratio | stdout + rc identical |
|---|---|---:|---:|---:|---:|---|
| primary | 10:23 AM | 9 | 1.21 s (1.09-2.36) | 0.70 s (0.57-1.42) | 1.7x | 9/9 (first cut, no length index) |
| primary | 10:27 AM | 9 | 1.29 s (0.87-2.50) | 0.59 s (0.44-1.17) | 2.2x | 9/9 |
| this worktree | 10:27 AM | 3 | 0.95 s (0.88-1.04) | 0.44 s (0.44-0.53) | 2.2x | 3/3 |

**Alongside the other eight session-start checks.** All nine start at once from the primary tree, as
`scripts/session_start_jobs.py` starts them. Only `check_lane_claims.py` differs between the two arms.
There were 7 pairs at 10:28 AM CST.
- `check_lane_claims.py`: 1.85 s median (1.51-2.57) old, 0.94 s (0.93-1.51) new, so 2.0x. stdout was
  identical in 7 of 7 pairs.
- All nine done: 1.85 s old, 1.04 s new.
- **`check_lane_invariants.py` is the slowest check again**, at about 1.0 s. The primary tree already ran
  the cut version of it: `39d144d7c` is an ancestor of its HEAD `0a60d9e0a`.
- So the two lanes together moved all nine from 2.35 s (11-17 9:53 AM) to 1.04 s, under different load.

**In-process `main()`, primary tree, 3 runs each, alternating.** The host load moved between the two
windows, so compare old with new within one window only.

| phase | old, 10:20 AM | first cut, 10:20 AM | old, 10:31 AM | final, 10:31 AM |
|---|---:|---:|---:|---:|
| `_near_miss` (19 calls) | 677-739 | 193-204 | 792-1,068 | 154-234 |
| `_tracked` (`git ls-files` + index) | 200-226 | 202-230 | 243-406 | 241-530 |
| **main** | **924-1,017** | **450-483** | **1,094-1,486** | **449-836** |

The first cut had no length index. The prototype on the live tree put the index's own saving at about
90 ms of the near-miss stage.

## What the cost was

- **19 claims name no file on the primary.** For each one, `_near_miss` called
  `difflib.get_close_matches(base, list(by_base), n=1, cutoff=0.85)` over all 21,556 tracked basenames. That
  is 409,564 candidates.
- **`get_close_matches` scores each candidate up to three times:**
  - `real_quick_ratio`, which depends on the lengths only;
  - `quick_ratio`, the size of the multiset intersection, in a Python loop;
  - `ratio`, only for survivors. On the live tree that was 23.
- About 51,700 candidates reached `quick_ratio`, and that loop was most of the cost.
- **`git ls-files` is near its process floor.** It takes 142-312 ms for 4.5 MB, while `git rev-parse` alone
  took 244 ms under load. Building the index takes another 81 ms. Both are untouched.

## The change (`3eacafa2a`)

`_close_basename(base, names, cutoff, by_len=None)` drops, before difflib sees them, only candidates difflib
would drop itself. Both tests use difflib's own formula, `2.0 * matches / (len(a) + len(b))`:

1. **The length window.** This is `real_quick_ratio` itself, with matches = `min(len(a), len(b))`. It is read
   from `_names_by_length`, an index built once per run in `main`, and only when some claim does not resolve.
   Scanning every name for each claim cost about 90 ms.
2. **The absent-character bound.**
   - matches = the characters of `a` that occur anywhere in `base`, counted with `str.translate`.
   - This can never be lower than `quick_ratio`'s multiset intersection, so every candidate it drops would
     have failed `quick_ratio`.
   - It cuts the pool from about 51,700 to 8,288.

Every survivor is then scored by `get_close_matches` itself. Its answer is the max of (ratio, name) over the
candidates that pass, and that cannot depend on which candidates it never had to drop, or on their order.
`_near_miss(claim, by_base, by_len=None)` keeps its old call form working.

## Equivalence: how it was checked

- **Byte-identical stdout and rc in every timed pair.** That is 9 + 9 serial pairs on the primary, 3 on the
  worktree, and 7 concurrent.
- **`tests/test_check_lane_claims_speed.py`** (NEW, 8 tests, about 30 s). It compares `_close_basename` with
  the unfiltered call:
  - on 165 synthetic typos plus 9 edge bases (unicode, 120 characters, 1 character, `test_` forms), at
    cutoffs 0.75, 0.85, 0.95 and 1.0;
  - on this checkout's real tracked basenames, with 13 bases;
  - with and without the prebuilt length index;
  - with a reachability spy proving `_near_miss` goes through the new path.
  - Each population must produce real matches: 75-166 per cutoff.
  - Cutoffs 0.0 and 0.6 also passed once, but took 81 s and 30 s because difflib's full `ratio()` then runs on
    nearly everything. They were dropped for time, not for failing.
- **Prototypes on the live tree:** all 19 unresolved claims gave equal answers in every rep, for each variant
  tried.
- **Existing tests:** `tests/test_check_lane_claims.py` + `test_lane_claim_audit.py` passed 33/33, and the
  hook scripts `test_lane_claims_parser.py` 39/39 (which drives this checker end to end) and
  `test_scope_guard.py` 31/31.

## Tried and not shipped

- **Exact `quick_ratio` from `str.count`.** It cut the pool 8,288 → 23 but saved only about 10 ms of about 140.
- **`bytes.translate(None, delete)` for ASCII names.** All 21,556 are ASCII. It saved about 20 ms, for
  a second code path.

## Leads (not followed)

- **`check_lane_invariants.py` is the critical path again,** at about 1.0 s concurrent. Its largest phase is
  `upstream_lane_slugs` (one `git cat-file --batch`, about 150 ms), and that phase runs only when a lane marker
  names a block that is missing from the working copy.
- **Both checks still pay x64-under-emulation python start-up.** `python3` is the arm64 interpreter here, and a
  parser walk is about 1.7x faster on it. Unmeasured end to end.
