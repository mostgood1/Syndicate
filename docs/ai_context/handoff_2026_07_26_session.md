# Session recap — 2026-07-26

Pick up at **#78** in [`todo.md`](todo.md). Everything below is context for it.

---

## Start here

**The board is empty because every cycle builds TOMORROW's date.** At 21:17 UTC —
16:17 Central — every `overview_counts` logged `context_label: "2026-07-27"`.
Tomorrow has a schedule but no odds and no sim artifacts, so all 40 candidates
are pruned `missing_projection_or_odds`, the pool is 0, nothing publishes, and
the stale board survives. That is **#78**, and it is a date-selection defect, not
a candidate-generation one.

**Before drawing any conclusion from a candidate trace, read `context_label` on
the same cycle.** `candidate_generation` traces do not carry the date;
`overview_counts` does, in the same burst. Not doing this cost a full
investigation cycle today — I filed "#68 answered", then had to retract it
(`95b51e3e`) because the reading was the rollover probe.

---

## Resolved today

**#75 — refresh-worker OOM at 4 GiB. Fixed and holding.**
`_load_jsonl_rows` did `read_text().splitlines()`, parsed every line, and only
then sliced to the last 2000 rows: the cap bounded what the caller got, never
what the read cost. Production's `odds_events/2026-07-26.jsonl` was **1.24 GB**.
Streamed into a `deque(maxlen=N)` in `5181ed3d`: **734.6 MB → 2.9 MB peak on a
135 MB file, identical output**. Last OOM 19:05:36; none since.

The comment above `_JSONL_ROWS_CACHE` had asserted the opposite — "a miss just
means one full re-read of a file already capped" — and believing it is most of
why this stayed open a day. Corrected in place.

**Then the board still would not build**, deferring 16 cycles in a row with
`reason=sim_subprocess_resident_and_no_headroom` and 726 MB free. Cause:
`apply_game_board_contract` defaulted to building `simulation_contract` whenever
not the web dyno, so the worker built it for every sport every cycle — and
**nothing reads it**. Default flipped to opt-in in `dc9fbe81`; payload
4.92 MB → 2.43 MB, and the deferrals stopped immediately. That also removes the
per-game loop that called `build_market_features`, so the odds-history reads
behind the original OOM no longer happen on that path at all.

**#77 — placeholders published as live picks. Fixed, not yet visible.**
`_unsimulated_game` (soccer/cards.py) builds a page-level empty state; those were
reaching the Layer 2 board as LIVE picks whose `pick` text was
*"Run scripts/build_soccer_artifacts.py --league mls --date … to populate this
match."*, with null odds/line/edge. Gated at the producer with an explicit
marker in `70ad2c9f`. **It cannot become visible until a cycle publishes** — a
0-candidate cycle is refused by the empty-over-good guard, so the stale
placeholder board persists. #77 and #78 are coupled that way.

---

## Shipped but unexercised

**#43 — board payload too large for the keyvalue store.** Both transport halves
are deployed and verified locally, and **neither has run in production**, because
no cycle has produced a large pool since.

- Write side (`e323d61f`, `81475c19`): oversized payloads divert to the artifact
  transport. Keyvalue is still attempted first, so small payloads are unaffected.
- Read side (`31ff3438`): keyvalue and artifact are both consulted and the
  **fresher** wins. Deployed to **web as well as the worker** — the read path
  runs on web.
- Publish capacity, measured directly: **14.70 MB publishes in 1.5 s; 19.61 MB
  drops the connection.** The payload is ~15.5 MB compact, so it fits — but only
  after catching that the fallback was writing `indent=2`, which would have
  inflated it past that limit.

⚠️ **Unverified:** the read side could let a stale `intelligence_state.json` on
disk shadow the keyvalue copy. The path resolves through `reports_root()` (the
Render disk, not the repo) so it *should* be fine, but that was never proven.

⚠️ **Correction worth keeping:** the alias dedupe in `30321a83` **never fires in
production**. It was verified against `intelligence_state_2026_07_08.json`, a
6-candidate quiet-slate payload where the lists happened to be byte-identical.
On a live board `recommendations` is an enriched superset (7 extra fields, 4
differing values) so the equality guard correctly refuses. The compact-separator
half of that commit is real and stays.

---

## Still open

- **#78** — the date-selection defect above. Start here.
- **#68** — genuinely unanswered. Needs a trace whose `context_label` is today.
- **#76** — `odds_events/<date>.jsonl` grows unbounded, 1.24 GB in a day against
  a 50 GB disk. Reading it is bounded now; nothing bounds the file.
- **Memory** — the worker plateaus near 2.7 GB even after the OOM fix. `dc9fbe81`
  should reduce it; **re-measure**. That plateau is what made a sim and a board
  build unable to coexist.
- **Admin token is `1234567890`** — live, guessable, guards `/api/ops/*`
  including data export and `full-refresh/run`. Rotate it.

## Instrumentation still deployed

`cards_context_*`, `board_contract_*`, `sim_contract_*` (first/last game only),
`ODDS_JSONL_LARGE`, and `KEYVALUE_PAYLOAD_COMPOSITION`. Keep until the memory
plateau is re-measured, then prune with #38. Two probes were removed after they
did their job — `ADV_CTX_SIZE` (~24 lines per game, it was drowning the
INTEL_TRACE rows #68 needs) and `ODDS_SHARD_SIZE` (misleading: it only printed
for files that exist, so its silence read as "this code never runs").

## Operational notes earned today

- A Render **restart does not re-inject env vars**; only a deploy does, and an
  env change does not create a deploy on its own.
- Use the **single-key** env endpoint. The full-list PUT replaces every var.
- `tracemalloc` is blind to freed-but-not-returned allocator churn. Production
  measures cgroup `memory.current`. **Measure RSS when chasing this class of
  bug** — every local measurement today disagreed with production for that
  reason.
- Local samples repeatedly failed to represent production. Three separate
  conclusions had to be corrected for it. Prefer a production reading.
