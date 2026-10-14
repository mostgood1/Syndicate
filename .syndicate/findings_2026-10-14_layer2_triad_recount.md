# Layer 2 triad, re-measured: the pregame half of the lead is STALE, the live half HOLDS

`[2026-10-14 22:20:37Z, session 4ab694ed, lane layer2-triad-recount, taking the lead filed on closing layer2-triad-alignment]`

## Why re-measure before acting

The lead said: *"live-projection and actual-so-far keys are ABSENT FROM THE LAYER 2
SCHEMA, not merely null… `projection` 23/98 prop rows (3/13 live) and
`model_edge_pct` 5/98 (0/13 live) while `score`/`score_v2` covered 98/98 — every
row is SCORED while the model reaches 5 of 98 and none of the live ones."*

That reading is from **2026-09-28**, on one live NFL game (PHI @ CHI), over **98
rows**. Sixteen days is long enough for it to stop describing the board, and the
lane's falsification clause said so: if coverage is materially higher now, the
lead must be restated before anyone acts on it.

## Measured, 2026-10-14 22:20:37Z

`/api/board/layer2-shortlist?sport=<s>&limit=5000`, **row cap defeated** — every
sport returned `rows == total_rows`, so no share is computed over a truncated
page.

| sport | rows | `projection` | `model_edge_pct` | `score_v2` | props | live |
|---|---|---|---|---|---|---|
| mlb | 119 | 115 (96.6%) | 107 (89.9%) | 100% | 95 | 0 |
| nba | 21 | 21 (100%) | 21 (100%) | 100% | 0 | 0 |
| nhl | 238 | 238 (100%) | 230 (96.6%) | 100% | 233 | 0 |
| nfl | 1,169 | 1,162 (99.4%) | 895 (**76.6%**) | 100% | 1,099 | 0 |
| ncaaf | 439 | 427 (97.3%) | 287 (**65.4%**) | 100% | 195 | 0 |
| soccer | 1,953 | 1,946 (99.6%) | 1,549 (79.3%) | 100% | 1,308 | 0 |
| ncaab / wnba | 0 | — | — | — | — | — (out of season) |
| **pooled** | **3,939** | **3,909 (99.2%)** | **3,089 (78.4%)** | **3,939 (100%)** | 2,930 | **0** |

### The pregame half of the lead is STALE by a wide margin

- `projection`: **23% → 99.2%**
- `model_edge_pct`: **5% → 78.4%**

So "every row is scored while the model reaches 5 of 98" **no longer describes
the board**. The hypothesis that the 09-28 numbers still held is **FALSIFIED**.
Anyone acting on the lead as filed would have been working a gap that has
largely closed.

**What is still worth attention, with denominators:** `model_edge_pct` is the
weak leg, and unevenly — **ncaaf 65.4%** (287 of 439) and **nfl 76.6%** (895 of
1,169) against nba 100% and nhl 96.6%. That is ~426 rows carrying a projection
but no model edge, concentrated in two sports.

### The live half of the lead HOLDS, with one honest limit

Top-level keys matching `live|actual|current|so_far`: **only `is_live`**. One
nesting level down, across `game`, `gate`, `likelihood`, `movement`,
`projection`, `quote`, `score`, `score_v2`: **NONE**.

So there is still no live-projection key and no actual-so-far key in the served
schema. **The limit:** this was measured over a **0-live-row** population (no
game was in play at 22:2xZ — see the sibling findings file for the three-way
proof). A key that only materialises on live rows would not appear here. The
09-28 reading found them absent *with 13 live rows present*, which is the
stronger evidence; this run is consistent with it but cannot independently
confirm it.

### What has visibly landed since 09-28

Keys present now that the old reading did not mention, which is where the
coverage gain came from: `calibration_cell`, `calibration_method`,
`calibration_version`, `model_probability_cal`, `model_probability_raw`,
`model_edge_pct_raw`, `likelihood` (with `p`, `p_market`, `ev_pct`, `mode`,
`adjustments`), `score_fee_net`, `price_source`, `venue_ref`, `suggested`,
`suggested_reasons`.

## The lead, restated

**Supersedes the 2026-10-14 filing.** Not "the board carries no model opinion" —
it carries one on 78.4% of rows and a projection on 99.2%. What remains:

1. **`model_edge_pct` is missing on ~21.6% of rows, concentrated in ncaaf
   (65.4%) and nfl (76.6%).** Worth attributing per sport: the board already
   prints `edge_unavailable_reason` inside `projection`, so the reason is
   probably already being recorded and simply not counted.
2. **No live-projection or actual-so-far key exists in the served schema.** The
   live tier is still absent for NFL/NCAAF/NBA/NHL/NCAAB, which is the original
   lane's finding and is unaffected by this recount. Re-confirm it on a live
   population rather than this pregame one; tonight's NHL slate provides one.

## Method note

Measured with the row cap defeated and `rows == total_rows` asserted per sport.
No share is reported over zero rows: the live column reads 0 because nothing was
in play, which is stated rather than presented as a finding.
