# Handoff: `/api/ops/artifacts/export` is 26 s because of the WALK

**For lane `ncaaf-live-resim-wire`**, which holds `syndicate/blueprints/ops.py`
and `syndicate/features/shared/artifact_publisher.py`. From lane
`web-oom-profiler-steady` / session `b2b5b45b`, `#632`.

**The substance is already on `main` and tested** (`b79e7eb5`:
`syndicate/features/shared/artifact_walk.py` + `tests/test_artifact_walk.py`, 12
tests). All that is left is a **small diff to `ops.py`**, below. I did not edit
your file — I applied the patch locally only to verify it, then reverted.

---

## The measurement

`/api/ops/artifacts/export` runs a **26-second median and an 87-second max** in
production. It is one of the routes starving web's thread pool: **32.5% of
requests exceed the 5-second health-check budget**, and that is what actually
restarts the instance — 35 `server_failed` events with **zero `evicted=True`**.
Web is not being OOM-killed; it is timing out.

**The cost is the directory walk, not the file bodies:**

| probe | result |
|---|---|
| `?names_only=1` (reads NO file bodies) | **timed out after 180 s** |
| `?since=<now>` (walk + stat, no reads) | 43 s |

So neither reading files nor serialising JSON is the problem.

## The cause

176 patterns, none recursive, but **every one begins with a wildcard segment**
(`*_source/...`). So each `Path.glob` expands that across every sport directory
and then lists the leaf. The patterns collapse onto only **95 distinct parents**,
and the busiest — `*_source/source_artifacts/data/processed` — is named by **18
separate patterns**. That directory is currently listed **18 times per sport per
request**, and it is one of the largest on the disk.

## The fix

`iter_pattern_matches` expands each parent once, lists it once, and matches every
pattern for that directory in memory. `patterns_that_can_match` additionally lets
a caller's `?pattern=` skip directories that provably cannot contribute (today
`pattern=` is applied only AFTER globbing everything, so narrowing to one family
still pays the full walk).

Measured on a local (thin) mirror: **125 → 51 `scandir` calls, 2.5×, with a
byte-identical file set.** The local tree understates it — the win scales with
patterns-per-directory (18× here) and with directory size, and production's
`data/` is where the file volume is.

## What I verified, and what I did not

**Verified:** 12 tests, every one comparing against the naive
`for p in patterns: root.glob(p)` loop rather than a hand-written expectation —
including de-duplication (two patterns can match one file, and the caller keys a
dict by path), directories not being returned as files, and an unreadable
directory being skipped rather than failing a read-only export. With the patch
applied, `ops.py` parses, imports resolve, the app builds, the export route is
still registered, and `tests/test_app_bootstrap.py` passes.

**NOT verified:** the endpoint's live response. It returns 503 on my machine both
with and without the patch — a pre-existing local condition, not a regression, but
it means I could not exercise the handler end to end. **Please confirm the
response is unchanged before/after on a real data root.** The equivalence proof is
the test suite, not a live call.

**One behaviour note, deliberate:** in the body loop the budget `break` now exits
ONE loop instead of two. That is the same behaviour — the old inner `break` set
`truncated` and the outer loop tested it immediately — but it is the only
control-flow change in the patch and worth your eye.

## The patch

```diff
--- a/syndicate/blueprints/ops.py
+++ b/syndicate/blueprints/ops.py
@@ imports @@
 from syndicate.features.shared.artifact_publisher import relative_to_data_root
+from syndicate.features.shared.artifact_walk import iter_pattern_matches
+from syndicate.features.shared.artifact_walk import patterns_that_can_match
```

Then, in `api_ops_artifacts_export`, the `names_only` inventory walk:

```diff
-        for pattern in HOT_ARTIFACT_PATTERNS + EXPORT_ONLY_ARTIFACT_PATTERNS:
-            for path in root.glob(pattern):
-                if not path.is_file():
-                    continue
-                relative_path = relative_to_data_root(path)
-                ... (body unchanged, dedented one level)
+        _inventory = patterns_that_can_match(
+            HOT_ARTIFACT_PATTERNS + EXPORT_ONLY_ARTIFACT_PATTERNS, subset_pattern)
+        for path in iter_pattern_matches(root, _inventory):
+            relative_path = relative_to_data_root(path)
+            ... (body unchanged, dedented one level)
```

and the body-carrying walk:

```diff
-    for pattern in _body_patterns:
-        if truncated:
-            break
-        for path in root.glob(pattern):
-            if not path.is_file():
-                continue
-            relative_path = relative_to_data_root(path)
-            ... (body unchanged, dedented one level)
+    for path in iter_pattern_matches(
+            root, patterns_that_can_match(_body_patterns, subset_pattern)):
+        relative_path = relative_to_data_root(path)
+        ... (body unchanged, dedented one level)
```

The exact, applied diff is reproduced verbatim in
`.syndicate/handoff_2026-09-07_artifacts_export_walk.patch`.

The `is_file()` checks are dropped because `iter_pattern_matches` only yields
files. Everything else in both loops is unchanged apart from one level of
dedent.

## If you would rather not take it

Say so and I will hold it — it is your file and your call. The finding stands
either way and is recorded in `state.md` `UPDATE 37`. The other two slow routes
from the same measurement, for whoever wants them: `/api/intelligence/query`
(5 s median, 18 s max, 1.5 MB responses) and `/api/board/game-chips` (11 ms
typical, 11.6 s worst — the signature of a cache miss doing real work in the
request path). And `request_path_guard` is already logging a live upstream ESPN
fetch inside a Flask handler by name:
`compute in request path (operation=wnba_has_games_for_date_espn_fetch)`.
