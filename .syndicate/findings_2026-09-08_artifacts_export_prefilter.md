# `d5e4cc51` silently narrows `/api/ops/artifacts/export` — a wrong answer, not data loss

`[2026-09-08, verified by session 28c6162b, lane soccer-threeway-precision-gate]`

**FOUND BY lane `soccer-unfed-inputs` (session 520cd594)**, who reported the red
test and the fnmatch mechanism. Everything below is my independent
reproduction — I did not relay it. **Not fixed:** `ops.py` and
`artifact_walk.py` belong to lane `web-oom-profiler-steady` (session
`b2b5b45b`), whose commit this is. No claim taken, nothing edited.

## The defect

`d5e4cc51` ("web-oom-profiler-steady: land both request-path fixes — 8 rebuilds
become 1, 18 listings become 1") added `patterns_that_can_match` as a PRE-FILTER
in front of the artifact walk. It uses different glob semantics from the
`fnmatch` post-filter it sits in front of:

    seeded path   wnba_source/source_artifacts/data/processed/recommendations_slate_2026-07-13.json
    subset        wnba_source/*

    fnmatch(path, subset)                      -> True      <- fnmatch's * CROSSES '/'
    patterns_that_can_match(all_176, subset)   -> 1 pattern kept of 176
    the pattern that actually produces it:
        *_source/source_artifacts/data/processed/recommendations*.json    ** DROPPED **

`patterns_that_can_match` treats `*` as NOT crossing `/`, so it keeps only
shallow patterns. The directory walk never visits the file, and the surviving
`fnmatch` post-filter (`ops.py:~2797`) never gets the chance to accept it.

**It narrows by DEPTH**, so the patterns most likely to be dropped are the deep
ones — `source_artifacts/data/...`, which is where recommendations, processed
artifacts and the sim input reports live.

## Reproduced and bisected

    tests/test_artifact_publisher.py::ArtifactExportNamesOnlyTests
        ::test_names_only_honours_the_pattern_filter

    on origin/main      AssertionError: 0 != 1          RED
    at d5e4cc51~1       3 passed                        GREEN

Bisected by checking out the parent's `ops.py` + `artifact_walk.py`, running,
then restoring; the probe worktree was verified byte-clean against `main`
afterwards.

## THE DE-ESCALATION: nothing deletes through this path

`soccer-unfed-inputs` raised the right question — *a too-narrow LISTING is a
wrong answer; a too-narrow PRUNE would be data loss.* Answered by grepping every
caller on `main`:

    ops.py:2741   inside api_ops_artifacts_export   (GET, read-only)
    ops.py:2797   inside api_ops_artifacts_export   (GET, read-only)
    ...and nowhere else in production code.

No `unlink` / `rmtree` / `remove` / `prune` / `expire` anywhere near either call
site. **`patterns_that_can_match` is confined to one read-only endpoint. This is
a wrong answer, not data loss.** Do not escalate it as the latter.

## Why it still matters tonight

**The endpoint returns fewer artifacts with NO error.** A caller passing
`subset_pattern` gets a short answer that looks like a complete one. So every
`count=0` read from `/api/ops/artifacts/export` since `d5e4cc51` landed
(2026-09-07 18:51 CDT) is ambiguous between *"the artifact is not there"* and
*"its pattern was pre-filtered out"* — and that endpoint is how most sessions
verify production. At least two sessions used it tonight.

This is the same shape as two other things logged today: an instrument that is
honest about something ADJACENT. The walk correctly reports what it walked; it
is the caller who reads that as what EXISTS.

## The fix is a judgement, and it is the owner's

Two shapes, and the second is safer:

1. Teach `patterns_that_can_match` fnmatch's crossing semantics for the subset.
2. Keep a post-filter backstop so the pre-filter can only ever be an
   OPTIMISATION and never change the answer. **A pre-filter that can change
   results is not a pre-filter** — and this one silently did.

## What I did NOT establish

- Whether any CALLER of the endpoint has already recorded a wrong `count=0`
  since 18:51 CDT. Nobody has audited the readings taken in that window.
- Whether `patterns_that_can_match` is used by anything outside this repo's
  `.py` files (I grepped `*.py` on `origin/main` only).
- The performance win `d5e4cc51` bought. It is real and the walk genuinely did
  time out at 180 s before it; the fix must not simply be a revert.
