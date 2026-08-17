# Deploy request — soccer-layer2-dates (live lens)

- **service:** the worker running the live-lens loop. `SYNDICATE_ENABLE_LIVE_LENS_LOOP`
  is `true` on **both** `refresh-worker` and `live-odds-worker`; the observed soccer
  tick logs came from **live-odds-worker** (`srv-d91dpertqb8s73co8lt0`), which also
  carries `MLB_ENABLE_LIVE_LENS_LOOP=true`. **Confirm the owner before deploying** —
  if both genuinely run it, both need this or the fix is half-applied.
- **sha:** `6bdc50de` (local `main`, **not pushed**)
- **NOT web.** Independent of the two web commits already queued (`cd46b403`,
  `6aaa11af`). Different services; they do not have to travel together.
- **urgency:** LOW / next natural worker window. **A deploy went out shortly before
  this was filed** — do not stack another on top for this. The soccer live lens has
  been dead for as long as the as-of change has been in; a few more hours is fine.

## reason

One line. `scripts/poll_soccer_live_state.py:75` called
`_load_team_ratings(league, source_root)` against a signature that has required
`(league, source_root, as_of)` since the audit §7 #6 as-of work. It raised

    TypeError: _load_team_ratings() missing 1 required positional argument: 'as_of'

Measured on production 20:1x–20:3xZ: the tick wrote `(0 live games)` for **seven**
leagues every ~70s while `active_leagues_for_date` returned **ten**. The three that
never appeared — la_liga, primeira_liga, championship — were **exactly and only the
three with matches in play**. All three live-lens boards read "Live matches: 0 /
Source: No data" while those matches were being played and scoring.

The call sits behind `if live_events:`, so it can only fire for a league with a live
match: silent on a quiet slate, total on a busy one.

## verify

**Cheapest reading first.** On the worker's logs after deploy, during a window with a
soccer match in play:

1. `text=live games` on the deployed worker should show **ten** `wrote ...
   (N live games)` lines per tick, not seven. **before: 7. PASS: 10.**
   The three new ones are la_liga, primeira_liga, championship.
2. At least one of those three carries **`count > 0`** while a match is actually in
   play. **before: those leagues logged nothing at all.**
3. `GET /soccer/<league>/api/live-lens` for a league with a live match moves off
   `header_stats: [{"Live matches": "0"}, ..., {"Source": "No data"}]` and returns
   non-empty `card_sections`. **before: 0 cards, "No data", with 3 matches live.**

**GUARD AGAINST MISREADING IT:** a league with nothing in play still writes
`(0 live games)`, and that is CORRECT. The pass condition is that the three missing
leagues APPEAR, not that every count is non-zero. Verifying this needs a live soccer
match — if the slate is empty, the deploy is unverifiable and should be marked so
rather than recorded as passing.

Already verified as far as is possible without a deploy: the real poll path was run
against the live ESPN feed for all three failing leagues and each wrote
`(1 live games)` where production wrote nothing. la_liga's payload carried Elche 1-1
Deportivo, 2nd half, 7/11 shots, 2/7 corners, 12 live player props.

## rollback

`git revert 6bdc50de`. One line in one file, worker-side, no schema or artifact
coupling. Reverting restores the swallowed TypeError.

## not fixed here, flagged

- `scripts/validate_soccer_vs_market.py:316` and `:449` call a local
  `_load_team_ratings(league, as_of)` with **one** argument — same class of miss from
  the same change. Offline validation scripts, `soccer-model-coverage`'s territory,
  not taken.
- `tests/test_soccer_team_ratings_as_of.py:117` asserts the literal call-site TEXT in
  `build_soccer_artifacts` alone, which is why CI stayed green through all of this. A
  caller-census assertion would have caught it. Worth someone's time; not this commit.
- The silent handler at `poll_soccer_live_state.py:179-181` still swallows every
  per-league exception with no log line. **The user is adding that diagnostic print
  separately** — it is independent of this fix and worth landing, because it is what
  stops cover #2 hiding the next fault.


---

## CLOSED by the coordinator 2026-08-17 21:40Z — STEP 1 PASS

Deployed to BOTH workers as you asked once the owner question resolved to `true`/`true`: live-odds-worker `7470939b`, refresh-worker `c6eb35c9`, each cut on its own live SHA.

**Step 1 PASS: 7 leagues -> 10**, and the three that reappeared are exactly la_liga, primeira_liga and championship.

**Step 2 INCONCLUSIVE, not failed** — every league reads `(0 live games)` because no match is in play. Owed on the next slate with soccer live.

**Open, and not something I will assert:** refresh-worker emitted no soccer poll lines at all in the same window despite carrying the lens flag. The fix is PROVEN on one worker and merely PRESENT on the other.
