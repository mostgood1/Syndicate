# Findings 2026-11-17 — `check_lane_invariants.py` 3x faster; the output is byte-identical

Lane `lane-claims-parse-memo`, session f60eabcb. It follows up todo `#822` (lane `session-start-hook-runtime`,
`.syndicate/findings_2026-11-16_session_start_runtime.md`, whose "Leads" section named this). The change is on
main as `39d144d7c`. It reaches the primary tree at its next fast-forward, and no fleet deploy is involved.

## Verdict

- **Serial A/B on the primary tree.** The old script is a copy of `689720915`, and the new one is this
  worktree's. Both read the primary's `.syndicate/lanes.md` (563 KB) with x64 `python`, the interpreter
  `session-start.sh` uses. Pairs alternate their order, and the input's sha1 was read before and after each
  pair; it did not move in any pair.

  | window (CST) | pairs | old median | new median | ratio | stdout + rc identical |
  |---|---:|---:|---:|---:|---|
  | 9:39 AM, heavy load | 9 | 4.21 s (2.11-5.57) | 0.97 s (0.77-2.45) | 4.3x | 9/9 |
  | 9:53 AM | 7 | 1.91 s (1.71-2.05) | 0.63 s (0.57-0.69) | 3.0x | 7/7 |
  | 9:57 AM, quiet | 7 | 1.39 s (1.30-1.83) | 0.44 s (0.43-0.64) | 3.2x | 7/7 |

- **The session-start critical path.** The run starts all nine python checks at once from the primary tree,
  as `scripts/session_start_jobs.py` does. Only the invariants script differs between old and new. There were
  7 pairs at 9:53 AM CST.
  - `check_lane_invariants.py`: old 2.35 s median (2.30-2.53), new 0.96 s (0.94-1.04), so 2.45x.
  - All nine done: old 2.35 s, new 1.25 s.
  - **`check_lane_claims.py` is now the slowest check, at 1.19-1.29 s.** Before the change, the invariants
    script was the slowest in 7 of 7 old runs.
- **Byte-identical output.** Each tool ran old against new, alternating, on the primary tree:
  - `check_lane_invariants.py`, default and `--quiet`: identical in every pair above.
  - `check_lane_claims.py` (`CLAUDE_PROJECT_DIR`=primary): identical in 3 of 3 pairs.
  - `lane_claim_audit.py`, text and `--json`: identical in 3 of 3 pairs. This ran through a harness that points
    its `REPO`/`LANES` at the primary and leaves `HOOK` on each tree's own parser.
- **The claim SET is unchanged.** 60 `lanes.md` revisions were sampled evenly from 4,000 commits of its history.
  Across them, old and new gave equal `_claims`, `_section_entries` and `_loan_entries` sets. They also agreed
  on every one of 21,939 `sections_are_disjoint` calls (each holder of each claimed path) and on all 123,327
  `_mask_backticked` lines: **0 differences**.
- **Tests.**
  - 264 passed: `tests/test_lane_*`, `test_check_lane_*`, `test_hoist_*`, `test_lane_archive_tools`,
    `test_lane_open` and `test_session_start_jobs`.
  - The hook scripts passed too: `test_lane_claims_parser` 39/39, `test_lane_guard_tree_root` 72/72,
    `test_scope_guard` 31/31, `test_lane_guard_hyphen` 10/10 and `test_lane_postwrite_check` 34/34.
  - `tests/test_lane_claims_parse_memo.py` (NEW) pins each rewrite against a verbatim copy of the code it
    replaced. It includes a real `git fast-import` repo for the `cat-file` path.

## Does `lane-guard.py` pay this cost? Barely: about 25 ms of a 0.44-0.68 s Edit

Measured BEFORE any change, at 9:32 AM CST, with `python3` (the arm64 interpreter the hook uses), `CLAUDE_PROJECT_DIR`=primary, and 7 pairs per row:

| Edit payload | median | range |
|---|---:|---:|
| unclaimed file (`scripts/lane_open.py`) | 0.44 s | 0.43-0.54 |
| `python3 -c pass`, the floor | 0.23 s | 0.22-0.28 |
| claimed by other lanes, with my lane as current (BLOCKED, loans + sections path) | 0.65-0.68 s | 0.60-0.77 |

- **It never calls `sections_are_disjoint(text, ...)`.** It calls `sections_are_disjoint_among` once, and only
  on a conflict with a current lane. That call runs over entries `lane_claims_source` already derived.
- **Its parser cost is one walk per Edit.** That walk is `_claims` over the primary text: 7.7 ms on arm64 and
  12.8 ms on x64, uninstrumented. On the conflict path it adds one `_loan_entries` walk and one
  `_section_entries` walk, each 5-11 ms.
- **The rest of the run is process start and git.** The no-conflict path makes 2 git calls (`rev-parse` +
  `merge-base`), and the conflict path makes 6, because `_effective` re-runs both for each of claims, loans and
  sections. The extra 0.2 s on the conflict path is those 4 calls, not the parser.
- **cProfile is misleading here.** It put 0.97 s in `_section_entries` on the conflict path, but that function
  walks once, in 6-11 ms. The per-character loop in `_mask_backticked` (one profiled `list.append` per
  character) is what cProfile inflated.

## Where the time went: `main()` in-process, x64 python, primary tree

Each phase is wrapped with `perf_counter`, and the first column is the median of 3 runs. 9:57 AM CST, a quiet host:

| phase | old ms | new ms | what changed |
|---|---:|---:|---|
| `sections_are_disjoint` (43 calls) | 648-662 | 21 | parsed once per text |
| `upstream_lane_slugs` | 372-374 | 151-154 | 1 `git cat-file --batch` in place of 4 `git show` calls, and a prefix regex |
| `orphaned_lane_markers` | 141-150 | 82-86 | prefix regex over ~9 MB of ledger |
| `contested_files` | 57-63 | 58 | unchanged (`claim_groups`) |
| `claims` | 9 | 7 | `_mask_backticked` split/join |
| **main total** | **1,262-1,270** | **343-353** | **3.6x** |

Under load (9:36-9:39 AM CST) the old `sections_are_disjoint` took 1,175-2,337 ms. With only the parse memo
in place, the A/B came to 1.5x (old 2.74 s, new 1.79 s, pairs 1.16-2.37x), short of 2x. The git and regex
work in `upstream_lane_slugs` was then the largest phase, and that is why the brief's lever alone was not
enough.

## The change (`39d144d7c`)

- **`lane_claims._section_view(text)`** is an `lru_cache(maxsize=4)` that returns
  `(tuple(_section_entries), tuple(_claims))`. `sections_are_disjoint` reads it.
  - Safe to cache because both walkers are pure: they read only `text` and module constants.
  - An edited `lanes.md` is a different key. A test checks that disjoint, same-section and undeclared variants
    each get their own verdict, in any order.
  - The values are tuples, so no caller can mutate the cached copy.
  - `lane_claim_audit.py`'s AST loader and the two full-source `exec` loaders still load the module. Their
    tests pass.
- **`lane_claims._mask_backticked`** now splits on the backtick and blanks the odd pieces. An unclosed quote is
  the last odd piece, which is the per-character toggle exactly.
- **`check_lane_invariants.upstream_lane_slugs`** runs one `git cat-file --batch`.
  - **Same bytes:** the batch returned exactly what `git show` printed, for all four files on origin/main, and
    neither file has a `.gitattributes` textconv.
  - **Same semantics:**
    - a `missing` path is skipped, as a non-zero `git show` was;
    - no answering file gives None;
    - a git failure or non-zero exit gives None.
  - **Checked against the old function:** equal on the primary, the worktree, a non-repo directory (None), a
    bogus ref (None) and `HEAD~400`. The test repo adds partial refs, a BOM, a file with no trailing newline,
    and a ref with no ledger files (None).
  - `tests/test_check_lane_invariants.py`'s `_fake_git` now answers the batch protocol. Its `git show` arm is
    kept.
- **`check_lane_invariants.heading_slugs(text)`** is `re.findall(r"\n###\s+...", "\n" + text)`, and returns
  the same list as `(?m)^###\s+...`.
  - `(?m)^` matches only at the start or after `\n`.
  - No match can swallow the next `\n###`, because `#` is in neither `\s` nor the slug class.
  - The two forms were checked equal on all four ledger files, their concatenation, and 15 edge cases (`\r`,
    `\x0b`, BOM, tabs, `####`).

## Leads (not followed)

- **`check_lane_claims.py` is now the session-start critical path,** at 1.19-1.29 s concurrent and 1.0-1.9 s
  serial. Its time has not been split yet. It makes one `git ls-files` (`_tracked`) and one `_claims` walk.
- **`lane_claims_source._effective` re-runs `git rev-parse` + `git merge-base` once per kind.** On lane-guard's
  conflict path that is 6 git calls instead of 2, about +0.2 s on each blocked, loaned or section-scoped Edit.
  Computing `(main_sha, base_sha)` once per process would remove 4 of them. That file is lane-guard's claim
  source, so this needs its own lane.
- **The hooks run two different interpreters.** `session-start.sh` uses `python`, which is x64 Python 3.11
  running under emulation on this ARM64 host, and `py -3` resolves there too. `lane-guard.py` uses `python3`,
  the arm64 WindowsApps alias. One parser walk takes 12.8 ms on x64 and 7.7 ms on arm64, so x64 is about 1.7x
  slower. Pointing the session-start hook at the arm64 interpreter might cut every check by that factor.
  Unmeasured end to end.
- **`claim_groups` (`contested_files`) is O(n^2) in `same_file`,** at 58 ms. Not worth a lane at today's 390
  claims.
