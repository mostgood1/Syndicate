# 09-04's live-gameline outlier, decomposed to the GAME — and the retrieval route that made it possible

`[2026-09-08, scheduled task `live-gameline-accuracy-snapshot` + follow-up question]`
No lane. Read-only against production; nothing deployed, no claim taken.

## What this closes

`state.md` (MLB live game-line model) carried: *"NOT ESTABLISHED: which of the 13
games 09-04's 110 priceable records concentrate in -- `history.jsonl` keeps
aggregates only and the per-record ledger is on the refresh-worker disk (nothing
under `data/` locally, checked)."*

The local half of that is true and the reachability half is not. **The WEB
service serves the per-record ledger for a past date:**

    GET /api/ops/artifacts/stream?path=mlb_source/data/live_gameline_ledger/live_gameline_ledger_<YYYY-MM-DD>.jsonl
    Authorization: Bearer $ADMIN_TOKEN

Verified on 5 of 5 dates tried, from `https://syndicate-an21.onrender.com`:
08-30 4,841,951 B / 08-31 6,662,470 B / 09-01 6,875,204 B / 09-04 2,911,251 B
(3,041 records) / 09-06 2,385,553 B. Path shape is `live_gameline_ledger.py:82`.
Which disk(s) hold the file was NOT checked — only that the web service serves it.

## Finals do NOT come from the board payload

`/api/board/book-grid?sport=mlb&date=...` returns 300 of 3,336 rows and no score
fields; `game_state` is `{chips: 31, rows_matched: 3248}`, i.e. counts. Running
`build_finals_index` over the served doc returns **0 entries** while the server's
own `finals_index` diag for the same build says `finals_seen: 2598`. So a local
re-score needs finals from elsewhere — used
`statsapi.mlb.com/api/v1/schedule?sportId=1&date=<d>` (16 finals for 09-04).

**Trap:** ledger `home_score`/`away_score` are **strings** (`'4'`, `'0'`), not
ints. An `isinstance(x, int)` split returns n=0 silently. Coerce.

## The reconstruction is CLOSE, NOT IDENTICAL — read magnitudes as approximate

| | rows | games | model | market | diff |
|---|---|---|---|---|---|
| served (history.jsonl, captured 09-05) | 110 | 13 | 0.23309 | 0.15482 | **+0.07827** |
| this re-derivation (same ledger, StatsAPI finals) | 154 | 15 | 0.21891 | 0.15539 | **+0.06352** |

My finals index resolves 2 more games than the board's did. Direction and
structure match; do not quote my numbers as the board's.

## Where 09-04's gap sits — the answer to "which games"

Priceable h2h rows, split by whether the side leading at snapshot time went on to win:

| snapshot situation | rows | share | model-market | contribution to +0.0635 |
|---|---|---|---|---|
| leader eventually WON | 91 | 59% | +0.0081 | +0.005 |
| leader eventually **LOST** | 23 | 15% | **+0.2652** | **+0.040** |
| tied at snapshot | 40 | 26% | +0.0735 | +0.019 |

**62% of the excess comes from 15% of the rows.** Leader-lost rows by game:
DET@CLE 13, MIL@CIN 7, STL@COL 2, ATH@SEA 1.

**One game is ~half the date.** `game_pk 824424` DET @ CLE (CLE won 7-6):
23 of 154 rows, model 0.5211 vs market 0.3049 (+0.2162), contributing +0.0323 of
the +0.0635. **Excluding it the date reads +0.0367.**
Its trajectory: CLE 4-0 down in the 1st, 6-1 down by the 3rd. Model home-win prob
0.400 -> 0.150 -> 0.067 -> 0.133 while the market sat ~0.54-0.57. CLE came back.

## Staleness is NOT the explanation — hypothesis raised and REJECTED

The obvious story (market quotes frozen near the pregame price, accidentally right
on a comeback) does not survive the split. On 09-04 priceable rows:

- quote_age <= 120s: n=27, **+0.1048**  (model deficit LARGER)
- quote_age >  120s: n=127, +0.0547
- quote_age median 278s, p90 534s

## Is it a model change? No — the same split across five post-fix dates

| date | rows | total diff | leader-LOST diff | leader-LOST share | mean abs(p-0.5) model vs market |
|---|---|---|---|---|---|
| 08-30 | 259 | -0.0603 | **-0.1220** | 16.2% | 0.251 vs 0.216 |
| 08-31 | 200 | +0.0771 | +0.1477 | 11.5% | 0.269 vs 0.215 |
| 09-01 | 365 | -0.0050 | +0.0319 | 4.9% | 0.304 vs 0.251 |
| 09-04 | 154 | +0.0635 | +0.2652 | 14.9% | 0.246 vs 0.211 |
| 09-06 | 121 | -0.0098 | -0.0170 | 24.8% | 0.263 vs 0.237 |

Comeback rows are **not** systematically bad for the model — it beat the market on
exactly those rows on 08-30 and 09-06. The one invariant across all five dates:
**the model prices further from 0.5 than the market does.** A more confident
forecaster has higher Brier variance, so a date's sign is set by which way its
confident calls landed. 09-04 is a variance event, not a detectable model change.

**This is COMPATIBLE WITH, not a replacement for, the selection-effect finding**
recorded in `state.md`/`learnings.md` the same day (`priceable_only` gates on
`abs(edge) >= 2 SE`, so it selects rows where the model disagrees most). Same
phenomenon from two directions: the gate selects disagreement rows, and on 09-04
the biggest disagreement was a comeback game that went against the model.

## NOT established

- Whether the model's greater extremeness is genuine skill or miscalibration.
  That needs a reliability curve over a full post-fix sample, not one date.
- Nothing here was re-checked against the board's own 13-game population.
