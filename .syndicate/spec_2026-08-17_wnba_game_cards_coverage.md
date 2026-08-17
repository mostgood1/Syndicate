# SPEC — WNBA `game_cards` fixture coverage + distribution publish

> **⚠⚠ GATE §1 FAILED 2026-08-17 - DO NOT BUILD §3.** `game_id` is UNSTABLE:
> `game_cards_2026-08-16.csv` uses `1` (sequential), `game_cards_2026-08-17.csv`
> uses `0f160b99581637ed10718a0bf90a33d38` (hash). Per §1's own instruction the
> fix is "establish a stable fixture identity first" - a different spec.
> The real writer is `scripts/refresh_wnba_oddsapi_props.py:2262`, NOT the
> vendor CLI, and this defect was already fixed once on 2026-07-07
> (`docs/fix_notes_log.md:191`) with tests that still exist. See `lanes.md`.
>
> **⚠ PREMISE FALSIFIED 2026-08-17 16:2xZ - DO NOT BUILD FROM §0 YET.**
> Every input to `export_game_cards_cmd` is ABSENT on the worker (odds,
> boxscores, and all three PBP files), so BOTH its branches would emit zero
> rows - yet the file has one. Its documented columns also do not match the
> artifact's header. **It is probably not the writer.** §1 (the gate), §2 (the
> column contract) and §3 (schedule as denominator) still stand. Identify the
> real writer by OUTPUT SHAPE first - see `lanes.md`.

> Written 2026-08-17 by the `layer1-board-coverage` session from a **partial
> read** of the target function. **§1 is a gate, not a formality:** I never
> verified the identity mapping this whole design rests on. If §1 fails, §3 is
> the wrong design — stop and re-spec rather than force it.

## 0. The defect, established

`export_game_cards_cmd` (`vendor/wnba_betting_repo/src/wnba_betting/cli.py:9581`)
emits ONE row for a THREE-fixture slate. Both row sources are
market-coverage-derived, so a fixture with neither simply does not exist:

- **primary** (`:9824`) iterates `game_odds_<date>.csv`. **That file returns
  `count=0` for ANY date on the worker** — the branch can never run there.
- **fallback** (`:9859`) unions `game_id` from `tip_winner_probs_<date>.csv`,
  `early_threes_<date>.csv`, `first_basket_probs_<date>.csv`, then calls
  `_build_row(gid, None, None, None)` — **home/away/commence_time are `None` by
  construction.** This is the only live path on that deployment.

Measured 2026-08-16: `game_cards` = 1 row (`game_id='1'`, POR@PHX) while
`smart_sim_2026-08-16_{ATL_IND,PHX_POR,SEA_CHI}.json` all exist. **The sim ran
for all three; only the card export is short.**

## 1. GATE — verify before writing any code

**The unverified assumption:** that schedule rows can be joined to the `game_id`
scheme the PBP files and downstream consumers use.

- `schedule_2026.csv` is keyed by TEAM NAMES + date.
- The PBP files are keyed by `game_id`, whose scheme I never inspected.
- The surviving card carried `game_id='1'` — **a sequential index** — which is
  evidence that at least one producer invents ids rather than carrying a stable
  one.

Run this first:

1. Read `game_id` values from whichever of the three PBP files exists for a
   **multi-game** date. ESPN numerics, sequential indices, or something else?
2. Check what `smart_sim_<date>_<AWAY>_<HOME>.json` uses as its id.
3. Check what CONSUMERS join on — `wnba_game_projections.py` reads
   `game_cards_<date>.csv`; `attach_game_state` joins the board on TEAM PAIR,
   not id.

**If the ids are unstable or absent, the fix is NOT "walk the schedule" — it is
"establish a stable fixture identity first", which is a larger job and a
different spec. Say so and stop.**

## 2. Contract that must not change

CSV header, taken from the real artifact on the worker:

```
date,game_id,home_team,visitor_team,commence_time,home_ml,away_ml,
home_spread,away_spread,total,bookmaker,home_tri,away_tri,
pred_margin,pred_total,home_spread_price,away_spread_price,total_o...
```

- **Column set and order must be preserved.** `wnba_game_projections.py` reads
  `pred_margin`/`pred_total` by name; the board reads the market columns.
- `_build_row(game_id, home, away, ctime) -> dict` is the row factory. **Do not
  change its signature** — the recap/reconciliation code further down calls it,
  and I have NOT read that code.

## 3. The change

**Make the SCHEDULE the denominator and everything else a left-join.**

1. Load fixtures for `date_str` from
   `vendor/wnba_betting_repo/data/processed/schedule_2026.csv` (git-tracked,
   complete): one entry per real fixture — home, away, commence_time.
2. Emit `_build_row(...)` per SCHEDULE fixture, populating home/away/ctime from
   the schedule instead of passing `None`.
3. Left-join, each independently and each optional:
   - `game_odds_<date>.csv` → market columns; **blank when absent**
   - PBP files → tip / first-basket / early-threes columns; blank when absent
   - `smart_sim_<date>_<AWAY>_<HOME>.json` → `pred_margin`/`pred_total`
4. **Keep both existing paths as fallbacks — do not delete them.** If the
   schedule load yields nothing, fall through to today's behaviour. A deployment
   whose schedule file is missing must not go from 1 row to 0.

**The rule:** a fixture appears because it is ON THE SCHEDULE. Market coverage
decides which COLUMNS populate, never whether the ROW exists — the "absent
renders as absent" contract the board already uses everywhere else.

## 4. Second defect, same function, same pass

`pred_margin`/`pred_total` are written as MEANS. The sim computes 2,000-sim
margin/total arrays and already exposes quantiles (`smart_sim.py`
`_summarize_period` → `margin_q`, `total_q`, `p_home_win`).

Publish a distribution the board can price any line against. **Note the
false-affordance trap** recorded in `deploys.md`: `app.py:7477-7478` already
emits `score.total_q` / `score.margin_q` under MLB's key names
(`total_runs_dist`, `run_margin_dist`) — but those are 3-point quantile
summaries `{p10,p50,p90}`, and MLB's `_dist_prob_over` treats dict KEYS as
outcome values. **Wiring them together on the matching name yields silence, not
an error.** Publish either an empirical histogram `{value: count}` matching
MLB's real contract, or mean+sigma **explicitly labelled as a normal
approximation**.

Same pass matters: verification needs a WNBA sim re-run, and splitting the work
costs two.

## 5. Tests

- schedule 3 fixtures, odds absent, PBP has 1 → **3 rows**: one fully populated,
  two with blank market columns. **This is the regression test for the defect.**
- schedule absent → falls back to current behaviour, **not** 0 rows.
- odds present for 2 of 3 → 3 rows, 2 with market columns.
- column set and order byte-identical to §2 for a fully-populated row.
- a fixture with a sim file gets `pred_margin`/`pred_total`; one without gets
  blanks, **not zeros**.

## 6. Verification — what would actually prove it

1. Re-run the WNBA export for a **multi-game past date**;
   `game_cards_<date>.csv` row count == schedule fixture count.
2. Deploy (live-odds-worker builds WNBA artifacts), re-read
   `/api/ops/artifacts/export`.
3. **Board-level proof:** WNBA grid rows with NO `game` block should collapse
   from ~69% (207 of 300, measured 2026-08-16) toward zero — the missing two
   thirds of the slate now have cards to join against.
4. For §4: re-read `live_gameline_score` for wnba. It currently reports
   `no_final_games_on_this_grid` and should begin scoring.

**A single-game slate proves nothing for §3.** 2026-08-17 had one WNBA fixture
and the pipeline correctly returned one row.
