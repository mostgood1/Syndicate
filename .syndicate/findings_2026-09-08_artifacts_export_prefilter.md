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

---

## CORRECTION and CLOSE-OUT `[2026-09-08, same session]`

**FIXED by lane `web-oom-profiler-steady` in `a0d02297`.** They reproduced the
red test before accepting the report, and took the post-filter-backstop shape:
`patterns_that_can_match` now decides emptiness as a product-automaton
reachability search with each side running its OWN wildcard semantics, an
undecidable `[...]` class is KEPT rather than dropped, and the caller's fnmatch
post-filter still runs behind it. Their own account of the root cause is sharper
than mine: the defect was in their TEST, which asserted their assumption about
`*` instead of the caller's actual fnmatch call — *a test written from the same
misreading as the code cannot catch that code.*

### RETRACTION: "At least two sessions used it tonight" — I cannot support that

The paragraph above says the endpoint "is how most sessions verify production. At
least two sessions used it tonight." **I did not use it.** My production reads
this session were `/api/board/layer2-shortlist`, `/api/board/layer1`,
`/soccer/<league>/api/cards`, the Render deploys/env API and `render_logs.py` —
never `/api/ops/artifacts/export`. I also told the owning lane "I used it myself
earlier tonight", which was false and is corrected to them directly.

What I actually knew was that ONE lane read it. "Most sessions" was inherited
from the reporter's framing and repeated as if measured. The impact argument
does not need it and is weaker for it.

### THE BLAST RADIUS IS NARROWER STILL, and this part IS verified

Only reads passing a `?pattern=` were ever affected. **An empty subset is a
no-op** — verified by running the real function against the real pattern list on
`origin/main`:

    patterns_that_can_match(all_patterns, "") == all_patterns   -> True  (177 patterns)

So unfiltered exports returned everything they always did. Combined with the
read-only-callers finding above, the defect is: *pattern-filtered listings only,
no deletions, no unfiltered reads.*

### STILL OPEN at the time of writing

`a0d02297` is on `main` but **web was live on `3e454a75`, which carries the
bug.** The owning lane holds the web deploy claim and is redeploying. Until that
is live, a `count=0` from `/api/ops/artifacts/export` **with** a `?pattern=` is
still ambiguous.

