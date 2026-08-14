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

## Smaller independent win, safe to do first

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
