# AUDIT — Layer 1 board coverage (the known universe)

> Lane `layer1-board-coverage`. Measured against production
> `https://syndicate-an21.onrender.com/api/board/layer1`, 2026-08-16
> 16:19–16:27Z. Every number below is a served-payload count with its
> denominator. Nothing here is quoted from the brief.

---

## 0. THE BRIEF'S PREMISES, RE-VERIFIED FIRST

| brief premise | status | evidence |
|---|---|---|
| "Layer 1 built `count=0` on 3 of 5 builds" (state.md:549) | **NOT REPRODUCED** | **5 distinct consecutive builds 16:26–16:40Z, all non-zero**, MLB/WNBA/soccer. §5a |
| "every alt-line and period row has an empty `Proj` while its base market is populated" | **FALSE for MLB, TRUE for WNBA** | MLB `game\|totals_alt` **86/86**, `game\|spreads_alt` **76/77** projected. WNBA `game\|totals_alt` **0/243**, `game\|spreads_alt` **0/176**. §2 |
| "the `Edge` column is a dot on every row … establish which term is missing" | **PARTLY FALSE.** The board serves 1,462 MLB edges. The missing term is already named on the row by `edge_unavailable_reason` — except in one producer. | §4 |
| "875 markets unprojected of 2802" | superseded; today's read is **902 of 2,843** MLB | §1 |

**The prior baseline in `docs/ai_context/betting_contract_lifecycle.md` §3a is
expired and should not be quoted again.** It recorded MLB 19.7% projected /
**0 edges** / game state 1,220 of 3,604. Today: **68.3% projected / 1,462 edges /
game state 2,843 of 2,843**. The system moved a long way; judging it against that
table would have reassigned somebody else's fix to this lane as a regression.

---

## 1. WHICH SPORTS ARE IN SEASON — DERIVED, NOT ASSUMED

`?window=slate`, one same-instant sweep 16:19:52–16:20:07Z:

| sport | games | rows | projected | rate | enrichment / empty_reason |
|---|---|---|---|---|---|
| **mlb** | 15 | 2,843 | 1,941 | **68.3%** | `enriched` |
| **soccer** | 66 | 6,453 | 1,704 | **26.4%** | `enriched` |
| **wnba** | 3 | 872 | 305 | **35.0%** | `enriched` |
| nfl | 0 | 0 | 0 | — | `grid_rows_all_for_other_dates` (1,425 rows in grid) |
| ncaaf | 0 | 0 | 0 | — | `no_precomputed_grid_artifact` |
| nba / nhl / ncaab | 0 | 0 | 0 | — | `no_precomputed_grid_artifact` (out of season, correct) |

### NFL IS IN SEASON TODAY AND ITS BOARD IS EMPTY — a real gap, two causes

`data/nfl_source/schedule_preseason_2026.csv` has **1 game on 2026-08-16**, and
**16 more in 08-21..08-24**, **16 more in 08-27..08-29**. The grid holds 1,425
rows and **zero for any of those dates**:

```
grid fixture dates present:  08-15: 179   09-13: 78   09-20: 64   09-27: 65
                             10-04: 65    10-11: 63   11-08: 63
```

1. **The whole remaining preseason is unquoted.** The grid jumps from 08-15
   (yesterday, already played) to 09-13. Not a window problem — `window=14`
   (through 08-29) still returns 0 rows and the same `other_dates` histogram.
2. **The window is forward-only and 5 days wide** (`_SLATE_WINDOW_DAYS["nfl"]`,
   `layer1_board.py:109`), so preseason week 3 on 08-21 would fall outside it
   even once quoted.

Cause 1 is upstream of this lane (capture), cause 2 is in it. Neither is the
"week self-pins to 1" issue, though `current_week.json` does still read
`{"season": 2026, "week": 1}`.

---

## 2. G1 — PROJECTION COVERAGE, PER SPORT × MARKET FAMILY

### MLB — the gap is line-shaped, not market-shaped

`game`-line families are effectively complete, **alt lines and period segments
included**:

| family | projected/total |
|---|---|
| `game\|totals_alt` (first1/3/5, 18 distinct lines) | **86/86** |
| `game\|spreads_alt` (first1/3/5, 10 distinct lines) | **76/77** |
| `game\|totals` + `game\|spreads` (all segments) | **109/109** |
| `game\|h2h` (all segments) | 19/19 (`projected` is null by design — a moneyline has no stat) |
| `game\|h2h_lay` | **0/15** — the only game family with no producer at all |

The prop side is where the 902 unprojected rows live, and **the gap sits on
specific LINES, not specific markets**:

| market | line 0.5 | line 1.5 | line 2.5 |
|---|---|---|---|
| `batter_home_runs` | 240/290 (82.8%) | **1/260 (0.4%)** | **0/244 (0.0%)** |
| `batter_hits_runs_rbis` | **6/73 (8.2%)** | 205/240 (85.4%) | 10/11 (90.9%) |
| `batter_hits` | 238/296 | 51/55 | — |
| `batter_total_bases` | 139/161 | 226/259 | — |

### WNBA — the gap IS the alt lines, and it is one root cause

| family | projected/total |
|---|---|
| `game\|totals_alt\|full` | **0/243** |
| `game\|spreads_alt\|full` | **0/176** |
| every period segment (`h1`,`q1`–`q4`) | **0/~60** |
| `game\|spreads\|full`, `game\|totals\|full` | 9/9, 8/8 |

**419 of 872 WNBA board rows (48.1%) are alt game lines with no projection**,
while the base line of the same market is projected. One cause: MLB prices any
line off `total_runs_dist` / `run_margin_dist` (`prop_projections.py:615-651`,
which names this exact defect and fixed it for MLB on 2026-08-15). **The WNBA sim
publishes means, not distributions**, so there is no distribution to evaluate at
a second line. Same reason its `Edge` is `edge_vs_line` in stat units rather than
a probability.

### Soccer — 26.4%, dominated by player props with no producer

| family | projected/total |
|---|---|
| `player_shots` | **0/960** |
| `player_assists` | **0/171** |
| `player_to_receive_card` / `_red_card` | **0/162** |
| `player_goal_scorer_anytime` | 519/1,539 |
| `player_first_goal_scorer` | 506/1,516 |
| `player_shots_on_target` | 394/1,278 |
| `game\|h2h\|full` | 45/60 |

**state.md's "THE SOCCER SIM PUBLISHES ZERO PLAYER PROJECTIONS" (2026-08-15) is
no longer true** — 1,525 soccer player-prop rows now carry one. That line needs
editing, not stacking.

**17 of 66 soccer games are in state `unknown`**, holding 926 rows. Not pregame,
not final — the game-state join missed them.

---

## 3. G2 — EVERY UNPROJECTED PROP CLASSIFIED INTO THE TWO BRIEFED BUCKETS

Rule used: a row is **B (sim emits no such quantity)** if its `(market, line)`
rung has *zero* projections anywhere on the board; else **A (player dark
everywhere)** if that player has no projection on any stat; else **C (residual)**.

| sport | unprojected / prop rows | **B — sim emits no such rung** | **A — player dark everywhere** | C — residual |
|---|---|---|---|---|
| mlb | 883 / 2,680 (32.9%) | **504 (57.1%)** | 337 (38.2%), **63 players** | 42 (4.8%) |
| wnba | 80 / 365 (21.9%) | 39 (48.8%) | 41 (51.2%), 5 players | 0 |
| soccer | 4,689 / 6,214 (75.5%) | 1,293 (27.6%) | **3,128 (66.7%), 836 players** | 268 (5.7%) |

### Bucket B — and WHAT IN THE SIM MAPS TO IT

The MLB sim publishes a **threshold ladder**, `<stat>_<N>plus`, read straight off
the served `sim_basis`. The adapter maps line `L` → rung `ceil(L)`:

```
batter_hits          line 0.5 -> hits_1plus            line 1.5 -> hits_2plus            both exist
batter_total_bases   line 0.5 -> total_bases_1plus     line 1.5 -> total_bases_2plus     both exist
batter_hits_runs_rbis                                  line 1.5 -> hits_runs_rbis_2plus  exists
                     line 0.5 -> hits_runs_rbis_1plus  <- MISSING RUNG, 63 rows dark
batter_home_runs     line 0.5 -> hr_1plus              exists
                     line 1.5 -> hr_2plus              <- MISSING RUNG, 260 rows dark
                     line 2.5 -> hr_3plus              <- MISSING RUNG, 244 rows dark
```

**504 MLB rows are dark because three rungs of an existing ladder are not
published.** The sim is a Monte Carlo over plate appearances — P(HR≥2) and
P(HR≥3) exist in the same simulated distribution that already yields P(HR≥1);
what is missing is the emitter's key table, not the model. This is the identical
defect `prop_projections.py:620` already names for `batter_hits_runs_rbis`
("sitting in the prop dist config while absent from the emitter's key table: the
model could price it and no one asked").

| sport | bucket-B rung | rows | what maps to it |
|---|---|---|---|
| mlb | `batter_home_runs` @ 1.5, 2.5 | 504 | `hr_2plus` / `hr_3plus` off the same PA distribution as `hr_1plus` |
| wnba | `player_double_double`, `player_triple_double` | 38 | derivable from joint pts/reb/ast — but WNBA has **means only**, so it needs the distribution first |
| wnba | `game\|totals_alt`, `game\|spreads_alt` (game rows, not counted above) | 419 | a score/margin distribution, the artifact MLB already has |
| soccer | `player_shots` @ 0.5–5.5 | 960 | the sim emits `player_shots_on_target` (394 projected) — shots ⊃ shots-on-target, same shot model one step earlier |
| soccer | `player_assists` @ 0.5 | 171 | no producer |
| soccer | `player_to_receive_card` / `_red_card` | 162 | no producer (discipline is not modelled) |

### Bucket A — the stale-fingerprint signal

**MLB: 63 players carry no projection on any stat, holding 337 rows.** These are
not fringe names — the list includes Christian Yelich, Eugenio Suárez, Francisco
Álvarez, Andrés Giménez. That is the lineup/injury fingerprint signal the brief
asked for, and it is **reported to the sim-engine session rather than chased
here** (sim internals are that lane's).

**Soccer: 836 players / 3,128 rows.** Different in kind from MLB's — soccer's
board spans 66 fixtures over a 7-day window and 17 of them have `unknown` game
state, so a large share of bucket A is likely fixtures the sim has not run at
all rather than lineups it ran stale. Not yet separated.

---

## 4. G4 — THE EDGE, AND WHICH TERM IS ACTUALLY MISSING

MLB serves **1,462 edges on 1,941 projected rows (75.3%)**. The remaining 479
split by the row's own `edge_unavailable_reason`:

```
285  <NO REASON FIELD AT ALL>                                       <- the finding
128  "live re-sim produced no probability for this market…"
 65  "game is live: a pregame projection cannot be priced…"
  1  "prob_interval_swamps_edge"
```

Soccer, by contrast, attributes **1,176 of 1,176**:
`one-sided market: no two-sided fair to price against` (1,131) and
`3-way market: two-leg de-vig would drop the draw` (45).

### 4a. THE SAME REFUSAL, EXPLAINED IN ONE PRODUCER AND SILENT IN THE OTHER

Two sibling copies of one computation:

- `soccer_projections.py:407-421` — when `_no_vig_over_probability` returns
  `None`, sets `edge_vs_market_pct = None` **and** `edge_unavailable_reason`.
- `prop_projections.py:817-821` (MLB, WNBA) — when the same call returns `None`,
  sets `edge_vs_market_pct = None` **and nothing else**. The key is not merely
  null; it is **absent** (checked: `key_absent` on 284 of 284).

The refusal itself is correct and deliberate (`#238`: de-vig needs both sides;
returning `None` "rather than pretending"). Only the attribution is missing, and
it violates the standard this repo already wrote down two files away:
`live_gameline_join.py:76` — *"Every zero must be diagnosable by reason."*

**Which rows:** 223 `batter_home_runs`, 34 `batter_total_bases`,
26 `batter_hits`, 1 `outs` — all one-sided (`sides: ["over"]`) with
`model_prob_over` populated and `market_fair_prob_over: null`.

### 4b. 1,416 ROWS CARRY BOTH TERMS OF AN EV AND SERVE NO EDGE — a decision, not a bug

| sport | no-edge rows | have `model_prob_over` | have `modelled_fair.*.fair_probability` | **both present** |
|---|---|---|---|---|
| mlb | 477 | 349 | 307 | **285** |
| soccer | 1,176 | 1,176 | 1,131 | **1,131** |
| wnba | 3 | 3 | 0 | 0 |

Example (MLB, Matt Olson, `batter_home_runs` 0.5): `model_prob_over` **0.2087**
against `modelled_fair.over.fair_probability` **0.2334** — a −2.5 pp read that is
computable from two fields on the same served row.

**This is NOT a missing-term bug and must not be shipped as one.** `modelled_fair`
is an *estimate* from one book's measured hold (`fair_method:
"book_margin_model"`, e.g. `betrivers` at 6.636%), not a de-vig against a real
opposing price. Pricing against it is a weaker claim than `edge_vs_market_pct`
and would put 1,416 new edges on the board at a confidence the column does not
currently signal. **That is a product decision and it is being surfaced, not
taken** — see Recommendations.

### 4c. ON A LIVE GAME THE BOARD SERVES ZERO EDGES

BAL @ TB, `BOT 1`, 255 rows / 201 projected / **0 edges**, every family.
Reasons are stated and each is defensible in isolation; the aggregate is that a
live game is unplayable on Layer 1.

The one `live_gameline` row: `sims_run: 120`, `prob_std_err: 0.0448`,
`edge_pp: -3.85`, `priceable: false`, `withheld_reason: prob_interval_swamps_edge`.
With `PRICEABLE_SIGMA = 2.0` at n=120, **an edge must exceed ~9.1 pp to be
released**. This is a recorded user decision (spec §8.1, *publish, refuse to
price*) and the module states the lever explicitly: raising
`MLB_LIVE_GAME_MC_SIMS` narrows the interval and turns pricing on with no code
change. `MLB_LIVE_GAME_MC_SIMS` is **not set in `render.yaml`**, so the 120
default is what production runs. Reaching a 2 pp detectable edge needs
n ≈ 2,500.

---

## 5a. AVAILABILITY ACROSS BUILDS — the briefed premise, settled

Five distinct MLB artifact builds, polled at 3-minute intervals:

| poll | MLB `generated_at` | rows | projected | WNBA | soccer |
|---|---|---|---|---|---|
| 16:27:49 | 16:26:31 | 3,006 | 2,107 | 872/305 | 6,453/1,704 |
| 16:30:53 | 16:30:45 | 3,006 | 2,107 | 872/305 | 6,453/1,704 |
| 16:33:58 | 16:33:49 | 3,006 | 2,107 | 872/305 | 6,453/1,704 |
| 16:37:01 | 16:35:06 | 3,006 | **1,935** | 872/305 | 6,453/1,704 |
| 16:40:07 | 16:38:53 | 3,245 | 2,169 | 872/305 | 6,453/1,704 |

**5 of 5 non-zero.** The "dark on ~3 of 5 builds" behaviour is not what the
surface does now. Rebuild cadence ~3–4 min.

**But coverage moves between builds and nothing on the board says so:** projected
fell 2,107 → 1,935 (−172) across one rebuild with `rows` flat at 3,006. Any
future availability or coverage claim must carry the `generated_at` it was read
from — a single read of this surface is not a property of the surface.

---

## 5. G3 — LIVE LENS

One live game in the window (MLB BAL @ TB). WNBA and soccer had none, so
**cross-sport A/B on a live slate is not yet possible** — that half is deferred,
not concluded.

**MLB player props: the contract is met.** Of 145 projected prop rows on the live
game, **128 carry all four** of `basis: "live_resim"`, `live_projected`,
`actual_so_far`, `live_aware`, alongside the retained pregame values
(`sim_projected`, `sim_model_prob_over`, `sim_basis`) — the live projection and
the actual live stat side by side, which is exactly G3's requirement.

**MLB game lines: the contract is not met.** Every `game|*` family on the live
game reads `live_resim 0 / live_projected 0 / actual_so_far 0`:

| family on the live game | rows | live-aware |
|---|---|---|
| `game\|totals_alt\|first5` | 17 | 0 |
| `game\|spreads_alt\|first5` | 10 | 0 |
| `game\|totals\|full` | 4 | 0 |
| `game\|h2h\|full` | 1 | **1** (the only one; carries `live_gameline`) |

So a live game's totals and spreads render a **pregame** projection with no live
counterpart and no actual-so-far, while the moneyline has one that is withheld
for precision. `REASON_TOTALS_MEAN = "totals_mean_not_distribution"` exists in
`live_gameline_join.py:81`, so the live path knows it has no total distribution.

### The prop lens genuinely updates — measured, not inferred

Two snapshots of the same live game, 16:26:31 → 16:30:45 (`BOT 1` → `TOP 2`),
201 projected rows common to both:

```
live_projected CHANGED   27
live_projected unchanged 174
actual_so_far  CHANGED    3
```

Direction is sensible — e.g. Junior Caminero `batter_total_bases` 1.5 fell
**2.024 → 1.485** as the first inning resolved. So MLB's live lens is a working
reference implementation for props: the projection re-sims and the actual stat
advances alongside it. G3's requirement is met for props and **not met for game
lines**, on the same live game, in the same payload.

---

## 6. RECOMMENDATIONS — ordered, with owner

1. **Attribute MLB's silent edge refusal.** `prop_projections.py:817-821` gains
   the reason string its soccer sibling already has. ~3 lines, no behaviour
   change, 284 rows stop rendering an unexplained blank. **This lane; file is
   unclaimed.**
2. **Publish the missing rungs `hr_2plus`, `hr_3plus`, `hits_runs_rbis_1plus`.**
   504 MLB rows, no new model — an emitter key-table gap. **Sim-engine lane.**
3. **Report the 63 dark MLB players.** Lineup/injury fingerprint vintage.
   **Sim-engine lane, via `send_message`.**
4. **Decide, don't infer: should a `book_margin_model` fair price an edge?**
   1,416 rows turn on this. If yes, it needs its own labelled column or a
   confidence marker — it is not the same quantity as `edge_vs_market_pct`.
   **User decision.**
5. **WNBA needs a score/margin distribution.** It is the single root cause of
   419 unprojected alt-line rows, 38 dark double/triple-double props, and the
   absent probability-space edge. **Sim-engine lane.**
6. **NFL preseason 08-16..08-29 is unquoted.** Capture gap, upstream of Layer 1.
7. **Raising `MLB_LIVE_GAME_MC_SIMS` is the lever for live pricing** — costed by
   the worker's memory budget, so it belongs to the OOM lane's window.

---

## 7. WHAT WAS SHIPPED, AND WHAT IS STILL OPEN

**Shipped to local `main`, NOT deployed** (`autoDeploy = no` for code, so
production still serves the pre-change payload):

- `e543e8dd` — `prop_projections.py` + `tests/test_prop_projections_edge_attribution.py`.
  Recommendation 1 only. Attribution, no behaviour change. Verified by replaying
  the real served payloads through the changed code: **287 of 287 previously
  silent rows emit a reason, 0 unattributed.** 11 new tests pass; 41 existing
  tests over the same file pass.
- `ac307bca` — `state.md` (two stale lines edited, not contradicted) and
  `deploys.md` (the measurement, plus the falsification test to run after a
  deploy: re-sweep and count rows with a projection, no edge, and no reason —
  expected 0).

**Open, and deliberately not taken here:**

- Recommendations 2, 3, 5 are the sim-engine lane's — sent via `send_message`.
- Recommendation 4 (`book_margin_model` as an edge denominator, 1,416 rows) is a
  user decision and is sent to the Layer 2 session, since those rows would
  become rankable the moment they exist.
- The WNBA `wnba_game_cards` finding could not be delivered — the
  "Wnba win prob counter read" session is unattended and rejects messages. It is
  written up in §4b and in the `e543e8dd` commit message instead.

**Still not measured:**

- Cross-sport live A/B — needs a slate with two sports live at once. MLB was the
  only live sport in this window, so the "audit each other in-season sport
  against MLB" half of G3 is **deferred, not concluded**.
- Whether soccer's 3,128 bucket-A rows are stale lineups or fixtures the sim
  never ran. 17 of 66 soccer games carry `state: unknown`, which points at the
  second, but that is a guess until measured.
- Whether NFL's 08-16..08-29 hole is a capture failure or an upstream feed that
  does not quote preseason week 3+. Only the absence is established.
