# Handoff — refresh-worker overview hydration (`#387` root cause)

Written 2026-08-14 by the memory-guard session at close. Self-contained: assume
zero context from that session.

## The one thing to fix

`build_intelligence_overview` (`syndicate/features/intelligence.py:2620`) holds
**every sport's fully hydrated overview simultaneously**. The loop's own comment
states it: *"peak is the SUM across sports, not the max."*

MLB's pass alone is **+2.9GB**, measured in production and recorded in the
comment on `_OVERVIEW_MIN_SAFE_HEADROOM_BYTES`:

```
05:10:57  post_pull_hot_artifacts    993.8MB container   478MB anon
05:10:57  OVERVIEW_SPORT_BEGIN mlb
05:12:10  mlb board_contract        3922.6MB  95.8%     <- +2.9GB in 73s
05:12:23  post_build_overview       3911.4MB container  3009MB anon
```

`handoff_refresh_worker_oom.md` measured the same call at ~3.7GB on 2026-07-26.

**The fix is architectural:** have candidate collection consume each sport's
hydrated overview and release it before the next sport hydrates, turning peak
from SUM into MAX.

## THE QUESTION IS ANSWERED. Implementable spec, 2026-08-14.

**"Which consumers need the whole list versus one sport at a time?" — traced.**

| consumer | needs | status |
|---|---|---|
| `_odds_history_payloads_by_sport(overview)` | per-sport | streamable as-is |
| `_collect_candidates` / `collect_candidates` | per-sport (`dashboard_games`, `home_rails`) | streamable as-is |
| `advanced_by_sport` (`intelligence.py:10404`) | per-sport dict comprehension | streamable as-is |
| `BOARD_OVERVIEW_READY` log | per-sport | streamable as-is |
| `pool["overview"]` | five counts per sport | **DONE — `100c9cb5`** replaced it with `overview_summary` |
| `collect_all_recommendations(overview=overview)` — EMPTY-POOL fallback (`:10399`) | WHOLE LIST | already gated off when Layer 2 is primary (`apply_empty_pool_fallback=not board_l2a_fallback_enabled()`) |
| `collect_all_recommendations(overview=overview)` — THIN-POOL merge | WHOLE LIST | **THE ONE REMAINING BLOCKER.** `apply_thin_pool_merge` defaults True and fires when `0 < len(pool) < _THIN_CANDIDATE_POOL_THRESHOLD` (20) |

**So the cutover is blocked on exactly one thing: the thin-pool merge.** Do not
start the streaming rewrite without deciding this first.

**Three options for it, in preference order:**
1. Decide the thin-pool merge is dead on the board path, the way `#385` decided
   the empty-pool fallback was, and gate it the same way. `#385` already
   measured that the fallback recovers rows the today-only slate filter then
   discards. **Measure whether the thin-pool merge has fired on the board path
   at all** before assuming either way — `collect_all_recommendations:thin_pool_merge`
   is its own `_collect_span` label, so it is directly countable in the logs.
   If it never fires, this is a two-line gate and streaming is unblocked.
2. Let the merge run against the SUMMARY rows plus per-sport candidates rather
   than the hydrated list.
3. Retain the hydrated list only when the merge is enabled — i.e. stream when
   it is off, current behaviour when on. Safest, but leaves two code paths.

**Do NOT stream the `skip_game_hydration=True` pass.** It runs all eight sports
in ~2s for a few MB and its output is a FINGERPRINT: truncating it keys the
caller's cache off a partial sport list and serves the wrong snapshot.

**Measured frequency, so the payoff is sized before the work:** the hydrated
overview runs **9 times per 5h** (72 `OVERVIEW_SPORT_BEGIN
skip_game_hydration=False` / 8 sports) against 736 cheap passes, and hydrates
all eight sports each time including four out of season. `[measured 08-14 18:5xZ]`

**Why this was not attempted in the same session that specified it:** it is a
restructure of `_build_candidate_pool`, the most OOM-sensitive function in the
repo, and starting it without room to finish and test it properly is how this
codebase got its worst incidents. The blocker above is a decision, not a
keystroke, and it wants a fresh session.

## Answer this BEFORE writing code

Which consumers need the whole list versus one sport at a time?
- `_collect_candidates` reads `dashboard_games` / `home_rails` off each sport
  dict. It is why `skip_game_hydration=True` must never be passed for an
  overview that feeds candidate collection (the docstring says so).
- The `skip_game_hydration=True` fingerprint pass runs all 8 sports in ~2s for a
  few MB and its output is a FINGERPRINT — truncating it would key the caller's
  cache off a partial sport list and serve the wrong snapshot. Do not stream
  that one.

## Do NOT do these

- **Do not lower `_OVERVIEW_MIN_SAFE_HEADROOM_BYTES` (3000MB).** It is a circuit
  breaker sized to the +2.9GB spike, not a stale constant. A session measured
  the stage at 127MB and nearly shipped a reduction — that run had **no MLB
  games in its mirror**, i.e. it measured the overview without the sport that IS
  the cost. The comment predicts the failure: *"A 1000MB floor waves MLB through
  every time."* See the `#387` retraction in `todo.md`.
- **Do not chase `force_refresh=True`.** Already spent. Both call sites pass
  `overview=`, so the flag never reached its branch; the dead literals were
  removed in `6a1cc3f2`.
- **Do not re-open the quote-join full-shard scan.** `#414` fixed it (21.5x,
  6.3% of shard scanned). Its remaining lever is documented in the
  `quote-join-enrich-cost` lane and needs a product decision about the market
  fallback first.

## RETRACTED — the "smaller independent win" is NOT free. DO NOT DO IT.

**Measured on refresh-worker 2026-08-14, 5h window, live `294f9ca9`:**

    cards_context_begin      398
      page_cache_hit          91     <-- 22.9% HIT RATE
      full build (end)       307
      91 + 307 = 398                 arithmetic reconciles exactly

The section below claims `_MLB_CARDS_CONTEXT_CACHE` has a "mathematically zero
hit rate" on the worker and that setting the worker limit to 0 costs nothing.
**Both are false.** It hits 22.9% of the time and saves 91 full MLB
cards-context builds every five hours. Zeroing it would delete that.

**Where the "zero hit rate" belief came from, and why it looked right.** `#253`
established that `_MLB_TODAY_CACHE` could never be read back on a worker before
eviction, and fixed it by making `_today_cache_put` a no-op there. That finding
is correct and is about a DIFFERENT cache. It was carried across to
`_MLB_CARDS_CONTEXT_CACHE`, which has its own key and does hit.
`CONTEXT_CACHE_EVICTED` firing 293 times in the same window looks like
confirmation of thrashing, but evictions and hits are not exclusive: at limit=2
a cache can evict constantly AND still serve ~23% of reads.

**The instrument that settles it already existed**: `cards_context_page_cache_hit`
is emitted on the hit path by `_log_cards_context_memory`, so the hit rate is
directly countable and never needed to be inferred from eviction counts.

**Still true from the section below**: the cache retains up to 2 full page
contexts on the worker (`_MLB_CARDS_CONTEXT_CACHE_MAX_ENTRIES_WORKER = 2`) and
that retention is real. It is simply not free to remove. If it must shrink,
measure what a context actually costs and what 22.9% of 398 builds is worth
first — do not treat it as a no-op.

## (SUPERSEDED, kept for the reasoning trail) Smaller independent win, safe to do first

`_MLB_CARDS_CONTEXT_CACHE` on the worker has a **mathematically zero hit rate** —
`#253` documents that its key includes a per-cycle signature — yet still retains
2 entries. Setting the worker limit to 0 releases that retention with no cache
benefit lost. ~60MB, testable without a deploy.

## Current production state at handoff

- refresh-worker `75b8aae6`, live since 04:26:55Z. This is a ROLLBACK: it has
  `#417`'s guard fix and `#414`'s index, and does NOT have the `#423`
  tracemalloc/arena instruments.
- 4 OOM kills 03:20-04:04 (`memoryLimit 4G`), none since. **The kills stopped 22
  min BEFORE the rollback landed**, so the instruments are neither convicted nor
  exonerated. `15f1739e` carries `nframe=3` + a pid fix if you re-deploy them.
- Board builds intermittently between two guards (`#417`'s 1900MB and `#387`'s
  3000MB). `anon` returns to ~3400MB within ~35 min of a restart.
- `#423`: the leak is real and is NOT arena fragmentation. Largest visible
  allocator is `json.loads` (491MB / 7.17M objects) = `_BOOK_QUOTES_CACHE` at
  its 500MB budget, i.e. bounded by design. **~76% of `anon` is unattributed.**

## Method notes that cost this session real time

- **Read the whole comment before overriding a number in it.** Four
  comment-sourced figures were challenged; three were stale, one was a real
  measurement — and that one nearly took production down.
- **A partial measurement is a different answer, not a smaller one.** State
  coverage in the sentence that states the number, not in a footnote.
- **Re-read the live SHA inside the step that deploys.** It moved five times in
  one evening; a stale one nearly shipped a rollback of another lane's work.
