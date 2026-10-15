# The venue ceiling is OURS, not the exchange's: every series is fetched, the board asks for none of them, and `KXMLBF5` exists

`[2026-10-15 13:3x–14:0xZ, session 4ab694ed, lane venue-prop-series-request-side, taking the request-side lead filed on closing venue-no-quote-attribution]`

## The question, and the binary it was filed as

Closing the previous lane I wrote: zero matches through any prop series is
consistent with *"the exchange lists them and we never request them"* (ours,
fixable, would raise the ceiling) **and** with *"they are not listed in play"*
(theirs, ceiling stands). The fan-in only sees quotes that arrived, so the
funnel cannot tell those apart.

**Neither is the answer. There is a third state and the fleet was already
printing it: requested, returned, RETAINED — and nothing asks for them.**

## 1. Every series is fetched. All of them.

Mentions in the fleet refresh logs:

| series | mentions | | series | mentions |
|---|---|---|---|---|
| `KXMLBTOTAL` | 37,192 | | `KXMLBKS` | 9,957 |
| **`KXMLBF5TOTAL`** | **20,846** | | `KXMLBOUTS` | 9,323 |
| `KXMLBGAME` | 19,431 | | `KXMLBHR` | 7,937 |
| `KXMLBSPREAD` | 16,706 | | `KXMLBERA` | 7,764 |
| `KXMLBSERIESSPREAD` | 16,427 | | **`KXMLBF5`** | **7,703** |
| **`KXMLBF5SPREAD`** | **15,068** | | **`KXMLBF7`** | **7,686** |
| `KXMLBHIT` | 13,341 | | `KXNFLREC` | 10,038 |
| `KXMLBHRR` | 13,034 | | `KXNCAAF1HSPREAD` | 8,007 |

**135 distinct MLB series are named in the logs.** Discovery reports
`prop_series=18 game_series=208 total_discovered=214`; `DEFAULT_SERIES_PER_TICK`
is 150, so 64 of 214 rotate out each tick — a real constraint, but not the
explanation, because the series in question are all named thousands of times.

**Not one of them is "never requested."** The lead's first branch is dead.

## 2. The board's demand for them is exactly ZERO

`PRECAP_SELECT` prints per-series detail including `demand_rungs` — how many
rungs of that series the board's own lines ask for:

| series | fetched | kept | `cut_in_window` | **`demand_rungs`** |
|---|---|---|---|---|
| `KXNCAAFSPREAD` (full) | 3,711,137 | 888,000 | 958,912 | **2,972,026** |
| `KXNCAAFTOTAL` (full) | 2,535,051 | 875,200 | 611,705 | **1,967,713** |
| `KXNCAAFGAME` (full) | 150,212 | 132,800 | 3,896 | 34,990 |
| `KXNFLREC` *(prop)* | 363,381 | 152,400 | 210,981 | **0** |
| `KXNCAAF1HSPREAD` *(seg)* | 326,279 | 109,200 | 87,010 | **0** |
| `KXNCAAF1HTOTAL` *(seg)* | 252,228 | 138,400 | 55,506 | **0** |
| `KXNCAAF1H` *(seg)* | 235,392 | 138,800 | 28,688 | **0** |
| `KXNCAAF2HSPREAD` *(seg)* | 76,645 | 48,000 | 25,414 | **0** |
| `KXNCAAF2HTOTAL` *(seg)* | 39,071 | 35,600 | 3,408 | **0** |
| `KXNFL1HTEAMTOTAL` *(seg)* | 938 | 800 | 0 | **0** |

**Six segment series, 930,553 markets fetched, ~470,000 retained, and the
board's demand for a rung of any of them is 0.** The full-game spread series
alone demands 2.97 million rungs.

So the board asks for full-game lines and nothing else, while **45.9% of NCAAF
live priced sides are segment markets** (measured in the previous lane). The
contracts exist, we hold them, and nothing asks.

## 3. `KXMLBF5` exists — which refutes the premise the whole chain was built on

The originating MLB lane recorded the refusal verbatim:

```
mlb|first5|h2h  <-  kalshi|full|h2h|KXMLBGAME-...
```

A first-five-innings board row was paired with a **full-game** Kalshi contract
and correctly refused. And `KXMLBF5` (7,703 mentions), `KXMLBF5TOTAL` (20,846)
and `KXMLBF5SPREAD` (15,068) **are fetched on every tick.**

**The right contract was in hand and the matcher never offered it.** That is not
a coverage ceiling, not a listing ceiling and not eviction — it is a **matching
defect**, and `SEGMENT_MISMATCH_GRID` was doing its job: refusing a wrong pairing
while the correct pairing was never attempted.

## 4. And the two budget gates disagree with each other

| gate | mode on the fleet | ticks | behaviour |
|---|---|---|---|
| `PRECAP_SELECT` (per-series cap, 400) | **`board_lines`**, `fill=date_aware` | 254 | `kept_at_line_total=271`, **`cut_at_line_total=0`** — never cuts a rung at a board line |
| `TRIM_SELECT` (storage bound, 6,000) | **`arrival`** | **2,250 — all of them** | date-blind, line-blind `markets[:room]` |

`SYNDICATE_KALSHI_TRIM_DATE_AWARE` is **absent from the fleet env**, and
`trim_date_aware_enabled()` returns False when absent. Over 2,250 ticks
(2026-10-10 → 10-15) the mode has been `arrival` **every single time** — the
date-aware fix has never run.

`cut_in_window` is the field the emitter's own comment calls the point of the
line: *"It counts rungs the join could have priced and now cannot."*

- **median 2,403 per tick**, min 12, max 6,940
- as a share of in-window markets: **median 32.4%**, max 56.9%, currently 52–55%
- the code's own 2026-09-09 baseline was **~800 per tick** — so it is now **3x
  the median and 7.5x at the peak**
- pooled by sport: ncaaf 3,867,460 · nfl 2,750,924 · nhl 175,563 · mlb 70,940 ·
  nba 41,058 · soccer 305

The composition rotates between consecutive ticks ~1 minute apart (ncaaf
3,806 → 4,919 → 4,068 while nfl moves inversely 2,037 → 1,137 → 2,102) with the
total near-constant — exactly the pathology the code documented.

**So the lower gate carefully keeps every rung at a board line, and the upper
gate then truncates 12,383 → 6,000 in arrival order.** The comment at
`kalshi_odds_refresh.py:703` predicted this in advance: *"THE SAME FIX, ONE
LEVEL UP… `_trim_to_storage_bounds` immediately re-applied the identical
date-blind slice."* It was written, shipped behind a flag, and the flag was
never turned on.

## What this does to the 8.6% ceiling I published at 03:0xZ

**It is not an exchange ceiling and should not be quoted as one.** It was
computed as "full-game h2h + full-game totals", on the evidence that only those
ever appear in `matched`. The reason only those appear is that only those are
demanded. Three distinct losses sit above the exchange's actual inventory:

1. **Demand**: `demand_rungs = 0` for every segment and prop series. Ours.
2. **Matching**: a first5 board row offered a full-game contract when `KXMLBF5`
   is in hand. Ours.
3. **Eviction**: a median 2,403 in-window markets per tick cut in arrival order
   while the gate below never cuts a rung at a board line. Ours, and behind an
   existing flag.

## What is NOT established here

- **That fixing any of the three yields N more matched sides.** I have not traced
  the matcher's key construction, and a segment contract existing is not the same
  as it being priceable against the board's rung. The size of the win is unmeasured.
- **Which of the three dominates.** They compose, and MLB's eviction is small
  (70,940 pooled ≈ 32/tick) while NCAAF's is enormous (≈1,719/tick) — so the mix
  is per sport.
- **Whether turning on `SYNDICATE_KALSHI_TRIM_DATE_AWARE` is safe now.**
  `deploys.md` records a `date_aware` run measured at `kept_in_window 931 /
  cut_in_window 379` and a later `board_lines` mode, so this has history that
  belongs to whoever owns that lane. **Not touched here, and no deploy made.**

## Method note

Everything above is read from counters the fleet already prints; nothing was
instrumented and no code changed. Shell variables did not survive into
`wsl -- bash -lc` four separate times tonight, each failure producing empty names
and a column of zeros that read exactly like a real negative result — so every
per-series count here comes from a Python script, not a shell loop. **And I
first read `TRIM_SELECT` truncated at 220 characters, which sliced
`kept_in_window=5149` into `kept_in_window=53` and briefly had me believing
0.88% of retained markets were in window.** Cutting a log line does not only
hide fields, it silently alters values; whole lines only. Analysis at
`nice -n 19`.
