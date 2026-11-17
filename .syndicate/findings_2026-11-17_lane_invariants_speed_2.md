# Findings 2026-11-17 — `check_lane_invariants.py` 1.8x faster again; output byte-identical

Lane `lane-invariants-speed-2`, session f60eabcb. This is the third lane today on the session-start checks,
after `lane-claims-parse-memo` (`39d144d7c`) and `lane-claims-checker-speed` (`3eacafa2a`). The change is on
main as `c90cf454e`. It is tooling only, with no fleet deploy and no betting change.

## Verdict

**Serial A/B, primary tree, 11:12 AM CST.** The old script is a copy of `2bc967e2f`, the new one is this
worktree's, both run under x64 `python`. 9 alternating pairs:

| | median | range |
|---|---:|---:|
| old | 0.84 s | 0.78-0.96 |
| new | 0.47 s | 0.36-0.94 |

That is **1.8x**, with stdout and rc identical in 9 of 9 pairs.
- `--quiet`: identical in 3 of 3.
- This worktree's own ledger: 0.62 → 0.35 s, identical in 3 of 3.
- A 10:59 AM run, under heavier load, gave 1.16 → 0.58 s (2.0x, 9 of 9 identical).
- One window, 11:10 AM, gave only 0.80 → 0.63 s (1.3x). The phase timings from the same minute showed a load spike that slowed one git call in both arms. The direct timing that followed is in the next table.

**All nine session-start checks at once (11:12 AM CST, 7 pairs).**
- `check_lane_invariants.py`: 1.21 s (1.08-1.81) old, 0.81 s (0.73-1.04) new, so 1.5x. stdout was identical
  in every pair.
- All nine done: 1.21 s old, 1.01 s new.
- **The invariants check is no longer the slowest.** In 4 more pairs, `check_lane_claims.py` was last every
  time, at 0.84-0.96 s, while invariants ran 0.66-0.77 s. The primary at `7488a568e` already had `3eacafa2a`.

**`main()` in-process, primary tree, 11:12 AM CST, 4 alternating runs.**

| phase | old ms | new ms |
|---|---:|---:|
| `upstream_lane_slugs` (1 orphaned marker) | 255-300 | 94-113 |
| `orphaned_lane_markers` | 138-192 | 57-69 |
| `contested_files` | 108-227 (11:11) | 6-9 |
| `sections_are_disjoint` | 46-62 (11:11) | 16-17 |
| **main** | **579-744** | **232-269** |

Calling `upstream_lane_slugs` directly, alternating: 206-219 ms for all four files against 92-110 ms with
`wanted`. The `wanted` form makes one batch call, for `lanes.md` alone.

## What changed (`c90cf454e`), and why each change is exact

1. **The archive headings are found in the raw bytes** (`heading_slugs_in_bytes`, `_ledger_bytes`).
   - **The cost.** Reading lanes_closed, the archive and history (8.7 MB) as text took 99-177 ms:
     - 8-22 ms reading;
     - about 40 ms decoding UTF-8;
     - 46-105 ms translating newlines. The files mix CRLF and LF: 16,509, 7,689 and 39,618 CRs.
   - **The method.** `bytes.find` locates each `###` (2,228 of them), checks the byte before it, and runs
     a tail pattern only there.
   - **The gain.** 30-37 ms for the read and the scan, against 122-157 ms, with the same 1,963 slugs.
   - **Exact, for four reasons:**
     - `\s` in a str pattern also matches 19 non-ASCII characters (NBSP, U+2028, U+3000, ...), so the tail
       lists the UTF-8 form of every one;
     - text mode turns a lone CR into a newline, so CR and LF both count as line starts there, while
       `git cat-file` output, never translated, uses LF alone;
     - slugs are ASCII, and no whitespace form starts with a continuation byte, so no match can begin
       inside a character;
     - leading BOMs are stripped per file, as `.lstrip("﻿")` did.
   - **Two side changes.** The archives are now read only when some marker names a lane that isn't in
     `lanes.md`. `_ledger_text` had no callers left and is removed.
2. **`upstream_lane_slugs(..., wanted=...)` fetches `lanes.md` first.**
   - The other three files, 9 MB of blobs to inflate, are fetched only if a wanted slug is still missing.
   - The caller asks only `slug in result` for the orphaned slugs, and that answer is unchanged.
   - A git failure in either batch still gives None, which means unknown.
   - The orphan that triggered it today, `render-config-retirement`, is a lane opened from a worktree whose
     block is on origin/main's `lanes.md`, so the second fetch was skipped.
3. **`lane_claims.claim_groups` compares only spellings that can be the same file.**
   - Two FILE spellings can match only through equality or a "/"-suffix, so their basenames are equal.
   - A DIRECTORY spelling (trailing `/`) matches by prefix, so it is still compared with everything.
   - That is the same edge set, so the same union-find components, and the result is built from the
     components in sorted order.
   - About 61,000 pairs → a few hundred.
4. **`sections_are_disjoint` reuses one cached `_claims` walk and checks fewer holders.**
   - The walk is `claims_tuple`, now shared with `check_lane_invariants.claims`.
   - It passes only the holders that can match `rel`: the same basename, or a directory claim.
   - `sections_are_disjoint_among` skips holders that don't match, and its answer doesn't depend on their
     order.

## Equivalence: how it was checked

- **Byte-identical stdout + rc in every timed pair:** 9 + 9 + 9 serial on the primary, 3 `--quiet`, 3 on the
  worktree ledger, and 7 + 4 concurrent.
- **`tests/test_check_lane_invariants_speed.py` (NEW, 43 tests, about 26 s).** Each rewrite is checked against
  a verbatim copy of the code it replaced:
  - the whitespace list, re-derived from `re` over all 1,114,112 code points;
  - 26 edge documents through real files: CRLF, lone CR, BOM, double BOM, NBSP, U+0085 as one byte and as two,
    U+2028, invalid bytes, `####`, `x###`;
  - 3,000 random byte documents through the same `TextIOWrapper` that `read_text` uses. A separate test checks
    that in-memory reader against real files;
  - LF-only mode against the old `decode().lstrip()` on 826 documents;
  - this tree's real archives;
  - marker verdicts on CRLF/CR/BOM/NBSP archives, with both outcomes populated, and on this tree;
  - laziness: no archive read when no marker needs one;
  - claim groups on 400 random spelling sets with directory claims, and on the live ledger;
  - the narrowed `sections_are_disjoint` with directory claims and a `rel` ending in `/`;
  - `wanted` on a real `git fast-import` repo: membership equal to the full fetch, with 1 batch call when
    `lanes.md` suffices and 2 otherwise, and None kept for a bogus ref and for a non-repo directory.
- **Existing tests:**
  - 306 pytest tests across `test_check_lane_invariants`, `test_lane_claims_parse_memo` (whose live-ledger
    comparison covers the narrowed holders), `test_lane_section_scope`, `test_lane_guard_*`,
    `test_check_lane_claims` and others;
  - hook scripts: `test_lane_claims_parser` 39/39, `test_lane_guard_tree_root` 72/72, `test_scope_guard`
    31/31, `test_lane_guard_hyphen` 10/10, `test_lane_postwrite_check` 34/34.

## Tried and not shipped

- **Skipping empty markers by their directory-listing size.** 186 of the 305 markers are empty, and skipping
  them would save about 20-40 ms. But on NTFS the size in a directory listing can lag the file. A stale 0
  would skip a non-empty marker, and so silently drop the orphan this check exists to report. That is not
  worth it.
- **A bytes regex with a `[\r\n]###` class start.** 69-86 ms: no literal prefix to search for.
- **A lookbehind `(?<=[\r\n])###`.** 242-272 ms.
- **An argparse fast path.** argparse adds about 30 ms, `shutil`/`bz2`/`lzma` included, because the help
  formatter imports `shutil` on every `add_argument`. Not done: invariants is no longer the critical path, so
  it would not move the all-done time.

## Leads (not followed)

- **`check_lane_claims.py` is the session-start critical path again,** at 0.84-0.96 s concurrent. Most of what
  is left there is `git ls-files`, about 0.15-0.3 s, plus Python start-up.
- **`upstream_lane_slugs` is now about one git process,** about 95-110 ms. It runs only while some marker names
  a lane the primary's `lanes.md` lacks, so a fresher primary tree removes it entirely.
- **Both checks pay x64-under-emulation start-up.** `python3` here is arm64.
