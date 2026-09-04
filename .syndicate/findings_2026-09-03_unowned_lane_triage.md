# Unowned lane triage — 2026-09-03 `[session c38d3e5c]`

**25 OPEN lanes are flagged UNOWNED — owning sessions gone.** They hold **3 claims
between them**, and all 3 are `.syndicate/` paths `lane-guard` EXEMPTS, so closing
them frees no file and unblocks no lane.

**They are NOT closeable as-is:** 24 of 25 record owed / unverified / unproven /
unfixed work in their own text. Marking them CLOSED asserts completion their own
words deny. The real decision per lane is **ADOPT** (the owed work is still wanted)
or **ARCHIVE** (move to `lanes_closed.md`, recording the owed items as dropped).

Owed items below are recovered from `lanes_history.md`, where the 2026-09-03
compaction moved each lane's narrative — they are no longer in `lanes.md`.

| lane | session | claims | owed items |
|---|---|---|---|
| `accuracy-autorun-rearm` | `82fe0160` | .syndicate/lanes.md, .syndicate/state.md, .syndicate/deploys.md | 0 |
| `convergence-phase7-crps` | `abf487e4` | none | 1 |
| `kalshi-line-aware-rungs` | `281da8c3` | none | 0 |
| `kalshi-spread-join-sign` | `-` | none | 2 |
| `layer1-model-edge-join` | `1c88bcca` | none | 1 |
| `layer2-accuracy-audit` | `ef7e22fc` | none | 2 |
| `layer2-cap-raise` | `5611932c` | none | 1 |
| `mlb-final-zero-placeholder` | `28195565` | none | 1 |
| `mlb-live-prop-prob-merge` | `1c88bcca` | none | 1 |
| `mlb-resolver-write-side-effect` | `6475567d` | none | 0 |
| `ncaaf-pace-block` | `de363735` | none | 0 |
| `open-bet-live-status` | `-` | none | 1 |
| `polymarket-pregame-price-gate` | `6475567d` | none | 0 |
| `polymarket-yes-leg-binding` | `5611932c` | none | 1 |
| `portfolio-decision-and-execution` | `9324a3e5` | none | 1 |
| `portfolio-ledger-service-split` | `74a0966a` | none | 1 |
| `render-web-request-path` | `726ef4ff` | none | 1 |
| `soccer-board-mlb-parity` | `f98be73b` | none | 2 |
| `soccer-model-dispersion` | `-` | none | 0 |
| `venue-candidate-key-token-guard` | `764eca35` | none | 2 |
| `venue-quote-line-join` | `3515d143` | none | 2 |
| `wnba-chip-live-token` | `3dcd0fb2` | none | 2 |
| `wnba-halftime-elapsed` | `1f76348c` | none | 1 |
| `wnba-live-odds-capture-gap` | `2bffd747` | none | 0 |
| `wnba-live-props-data` | `1f76348c` | none | 2 |

---
## Owed items, verbatim

### `accuracy-autorun-rearm`
session `82fe0160` · marker last seen 09-03 13:17 · claims: `.syndicate/lanes.md`, `.syndicate/state.md`, `.syndicate/deploys.md` · 9078 B of narrative in history

- *(no owed/unverified marker found — candidate for ARCHIVE)*

### `convergence-phase7-crps`
session `abf487e4` · marker last seen - · claims: **none** · 2061 B of narrative in history

- THE ONE THING OWED:** first `sim_input_report_<date>.json` via

### `kalshi-line-aware-rungs`
session `281da8c3` · marker last seen - · claims: **none** · 1769 B of narrative in history

- *(no owed/unverified marker found — candidate for ARCHIVE)*

### `kalshi-spread-join-sign`
session `-` · marker last seen - · claims: **none** · 1782 B of narrative in history

- for what is still OWED — the history entry stays as the record.
- OWED, in priority order:

### `layer1-model-edge-join`
session `1c88bcca` · marker last seen - · claims: **none** · 3238 B of narrative in history

- STILL OWED — the only reason this lane is OPEN:** MLB, WNBA and NCAAF are

### `layer2-accuracy-audit`
session `ef7e22fc` · marker last seen - · claims: **none** · 5848 B of narrative in history

- Limb (b) CONFIRMED, and the cause is upstream of the matcher.** Settlement: 19,692 settleable, 35 settled (0.2%). `graded_rows_available` mlb = 1,2,1,1,1,7,0 per day. Independently reproduced on the WEB service from a different code path: `/mlb/api/market-accuracy?date=` returns 
- NOT MEASURED, and it is the thing I most wanted:** whether the board's own `ev_pct`/`model_edge_pct`/`score` PREDICT the outcome. The portfolio endpoints expose settlement marginals only (`by_sport`, `by_market_family`, `by_venue_family`), not per-order rows, so no edge-bucket ca

### `layer2-cap-raise`
session `5611932c` · marker last seen - · claims: **none** · 1213 B of narrative in history

- NEXT ACTION (owed, for whoever picks this up): the 2000/sport cap and ROWS_TOTAL=6000 are STAGED on refresh-worker but UNDEPLOYED, and the 75% warn threshold `c461693e` is on main and undeployed. Both ride the next refresh-worker deploy. They are UNTESTABLE until a full multi-spo

### `mlb-final-zero-placeholder`
session `28195565` · marker last seen - · claims: **none** · 763 B of narrative in history

- THE OWED READING IS DISCHARGED — AND NOT FROM 08-26** `[2026-08-29]`.

### `mlb-live-prop-prob-merge`
session `1c88bcca` · marker last seen - · claims: **none** · 1752 B of narrative in history

- VERIFICATION OWED — FIRST LIVE MLB GAME.** `snapshot_live_prob_seen > 0` and

### `mlb-resolver-write-side-effect`
session `6475567d` · marker last seen - · claims: **none** · 2448 B of narrative in history

- *(no owed/unverified marker found — candidate for ARCHIVE)*

### `ncaaf-pace-block`
session `de363735` · marker last seen - · claims: **none** · 1735 B of narrative in history

- *(no owed/unverified marker found — candidate for ARCHIVE)*

### `open-bet-live-status`
session `-` · marker last seen - · claims: **none** · 1018 B of narrative in history

- OWED, all trigger-gated, none forceable:

### `polymarket-pregame-price-gate`
session `6475567d` · marker last seen - · claims: **none** · 1990 B of narrative in history

- *(no owed/unverified marker found — candidate for ARCHIVE)*

### `polymarket-yes-leg-binding`
session `5611932c` · marker last seen - · claims: **none** · 4435 B of narrative in history

- OWED — THE LEG CHOICE IS NOT VALIDATED.** Every reading is

### `portfolio-decision-and-execution`
session `9324a3e5` · marker last seen - · claims: **none** · 1161 B of narrative in history

- Verification OWED, and it is a one-read production check.** Stage A's

### `portfolio-ledger-service-split`
session `74a0966a` · marker last seen - · claims: **none** · 1383 B of narrative in history

- Verification owed, and it GATES the backfill:** the next `[ledger_bridge]`

### `render-web-request-path`
session `726ef4ff` · marker last seen - · claims: **none** · 634 B of narrative in history

- OWED, THE ONLY OPEN ITEM:** the card-cache idle bound is **NOT** verified.

### `soccer-board-mlb-parity`
session `f98be73b` · marker last seen - · claims: **none** · 1798 B of narrative in history

- OWED, and not claimed as done:
- 3. **The live totals lens is unproven** — harness ran n=1 with NEUTRAL ratings.

### `soccer-model-dispersion`
session `-` · marker last seen - · claims: **none** · 1812 B of narrative in history

- *(no owed/unverified marker found — candidate for ARCHIVE)*

### `venue-candidate-key-token-guard`
session `764eca35` · marker last seen - · claims: **none** · 560 B of narrative in history

- WHAT IS OWED AND IS NOT DISCHARGED: the production volume reading.
- A SECOND READING IS OWED AND IS NOT THE SAME AS THE FIRST** — the soccer

### `venue-quote-line-join`
session `3515d143` · marker last seen - · claims: **none** · 2036 B of narrative in history

- UNPROVEN: the demand-weighted trim.** Allocation IS the binding constraint,
- UNFIXED, TWO:** (1) a TOTALS key names no GAME — 672 polymarket soccer quotes

### `wnba-chip-live-token`
session `3dcd0fb2` · marker last seen - · claims: **none** · 1208 B of narrative in history

- OWED 1 — the WNBA half is owed on a MISSING SUBJECT, not a missing deploy.
- OWED 2 — the projection guard is UNIT-TESTED ONLY** and must not be recorded

### `wnba-halftime-elapsed`
session `1f76348c` · marker last seen - · claims: **none** · 1062 B of narrative in history

- ONE READING OWED — the break behaviour itself is UNOBSERVED IN PRODUCTION.

### `wnba-live-odds-capture-gap`
session `2bffd747` · marker last seen - · claims: **none** · 3366 B of narrative in history

- *(no owed/unverified marker found — candidate for ARCHIVE)*

### `wnba-live-props-data`
session `1f76348c` · marker last seen - · claims: **none** · 4517 B of narrative in history

- TWO READINGS OWED, BOTH BLOCKED ON A LIVE SLATE. DO NOT report either as
- reason — treat exit 3 as "not measured", never as a pass.
