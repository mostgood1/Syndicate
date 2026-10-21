# Venue-native live selection: mostly already live; the evidence supports a per-venue net floor (Kalshi 1.0%, Polymarket 0.5%), not 0

Lane `venue-native-selection`, session 86c84cf4, 2026-10-21 (file is dated 10-20, as the brief asked). It was started
by session 332cb014, which asked: "is this the right bet-selection process?" READ-ONLY on the fleet. Nothing on the
fleet changed: no env, cap, restart or deploy. Times are Central unless marked Z.

## Answer

1. **The brief's gap was closed 2.5 hours after it was measured.** The brief measured at 10-20 18:10Z.
   - `SYNDICATE_LIVE_EV_FLOOR=0` went live at **20:45:40Z** (lane `compounding-bankroll`, `ee87954d`, user-approved).
   - The live plans now read Suggested rows **plus every row the Suggested flag refused for EV alone**. So the
     best-book 2% no longer decides what live can see.
   - Then the venue's own price decides, via the commit's existing gates: gross ≥ 2% AND net of fee > 0.
   - **Measured today**, by scoping the WHOLE shortlist at each venue's own price with the live code path:
     - **0 venue-native candidates are excluded from the live population**, on 10-21 or 10-22, at either venue.
     - Venue-native candidates means: venue-net > 0, the non-EV Suggested gates passed, and the best side per line
       at the venue.
     - The only venue-positive rows left out fail a QUALITY gate the design keeps: `single_book_fair` 2+2+2+1,
       `suspect_stale_quote` 1.
2. **So "build venue-native selection" is mostly done. The open question is the FLOOR, and 0 is not supported.**
   - Before 10-13, the paper venue books ran this exact selection: the whole shortlist at the venue's own price,
     gross ≥ 2% and net > 0.
   - **Result: −13.8% ± 5.0** flat ROI over 826 bets, 201 events and 12 dates.
   - Most of that is MLB props (−25.3% ± 9.3 on 19 events). Without MLB it is **−6.3% ± 5.4** (500 bets, 182 events).
   - **Same-venue CLV against the venue's fee:**
     - Kalshi picks below +1% net beat the close by LESS than the fee they paid. They are net-negative at the close.
     - Polymarket picks clear their fee from 0–0.5% net.
3. **Recommendation (user decision; nothing built):**
   - Replace the live floor's effective 0% net with a **per-venue starting floor: Kalshi 1.0% net, Polymarket
     0.5% net**.
   - It is applied to the venue's own executable price.
   - It is handed to the min_ev tuner as the per-cell starting point (that lane owns moving it).
   - **This is a minimum, not evidence of edge.** No floor in this data has an ROI distinguishable from 0.
4. **A separate defect found on the way (not mine to fix; proposed as its own session):** every LIVE Kalshi
   `closing_mark.clv_pct` is about −35 points.
   - `order_clv._entry_price` (`syndicate/features/shared/order_clv.py:75`) hands the live `fill_price`, a contract
     price such as `0.65`, to `clv_pct_from_prices`, which reads American odds. `+0.65` becomes 99.4% implied.
   - Recomputed correctly, the 13 marked live rows are **+0.46 pt ± 0.35**, not −36.85.
   - The min_ev tuner reads `closing_mark.clv_pct`, and its own 14:30Z status says its evidence has moved to live.
     Once `min_clv_events` (30) live events accrue, it will read a hugely significant negative CLV. It is shadow-only
     today.

## Data (substrate: the local WSL fleet, read-only, nice 19)

- **Shortlist probe** `C:\tmp\venuenative\gap_probe.py`, run 2026-10-21 15:02:44Z.
  - Context: refresh-worker pid 3258427, fleet HEAD `77a1790d`.
  - It reads the 10-21 (4,648 rows) and 10-22 (3,503 rows) Layer 2 shortlists.
  - It builds each venue's resolvers with `pipeline.portfolio_commit._venue_price_resolver`, the live code.
  - It runs `scope_rows_to_venue` over EVERY row.
  - Env: the state-backend keys plus the five non-secret join flags (`SYNDICATE_KALSHI_FORWARD_DATE_SPORTS`,
    `..._SOCCER_FORWARD_DATES`, `..._GAME_LINES`, `..._LADDER_MONOTONIC`, `SYNDICATE_POLYMARKET_PROP_JOIN`).
  - **A first run without those flags matched 64 Kalshi rows instead of 387.** If you reproduce this, copy them.
  - Kalshi join: 387 / 213 board rows matched; Kalshi venue-quoted 382 / 211, Polymarket 134 / 74.
  - The live plans' own refusal totals (≈333 Kalshi rows on 10-21) agree with these counts.
- **Ledger** `full_history_orders()`, dumped at 15:0xZ: 11,251 rows, 2,543 of them Kalshi/Polymarket family.
- **Study** `scripts/venue_native_selection_study.py <ledger.json> <repo>`, committed with this file.
  - Returns are per $1, net of the venue fee: recorded where present, else imputed with `venue_fees`. This is the
    same as `scripts/paper_bet_optimization.py`.
  - Rows are deduped per (venue, opening_key), earliest submit.
  - ± is one event-clustered SE.
  - CLV is same-book `closing_mark.clv_pct` in **probability points** (close implied − our implied). Fees are
    converted to the same unit (fee per $1 of payout), so "CLV − fee" is the margin at the close.
- **Regimes, split by submit time at each code change on main:**

| regime | what selected it | venue | settled dates (booked) | settled bets / events |
|---|---|---|---|---|
| R1 venue-native | whole shortlist at venue price, gross ≥ 2 & net > 0 (before `2ecf7c2e`, 10-13 16:35Z) | kalshi | 12 (13), 10-02..10-13 | 524 / 165 |
| | | polymarket | 12 (13), 10-02..10-13 | 302 / 133 |
| R2 Suggested | Suggested at the BEST book, then the same venue gates | kalshi | 7 (10), 10-13..10-20 | 63 / 32 |
| | | polymarket | 6 (7), 10-13..10-18 | 29 / 22 |
| R3 ladder | EV-only-refused rows at venue price, flat $1 (from 10-20 21:29Z) | both | **1** (3) | 14 / 5 |
| R4 live 0% floor | live, from 10-20 20:45Z | both | **1** (2) | 21 / 5 |

**What this rests on:**
- The floor question rests on **12 dates** (R1).
- The R1-vs-R2 comparison rests on 12 + 7 dates in **different weeks**, so sport mix differs. MLB's postseason sits
  in R1, which is why the sport split below exists.
- R3 and R4 are **one date each** and decide nothing.

**What R1 is not:**
- It ran before the `single_book_fair` gate (10-16), so it is "venue-native minus that gate".
- The ledger row does not carry `fair_method`, `books_quoting` or the Suggested flag, so R1 cannot be re-filtered
  after the fact.

## Finding 1: the live population is now venue-native (shortlist probe, 10-21 and 10-22)

| | Kalshi 10-21 | Kalshi 10-22 | Polymarket 10-21 | Polymarket 10-22 |
|---|---|---|---|---|
| rows priced from the venue's own feed | 382 | 211 | 134 | 74 |
| venue net-of-fee > 0 | 9 | 11 | 5 | 4 |
| ... of them Suggested | 0 | 1 | 0 | 0 |
| Suggested rows quoted at the venue / positive there | 2 / 0 | 2 / 1 | 2 / 0 | 0 / 0 |
| venue-native candidates (quality gates + best side at the venue) | 7 | 9 | 3 | 3 |
| **of those, NOT in the live floor population** | **0** | **0** | **0** | **0** |
| ... and passing the commit's gross ≥ 2% | 6 | 8 | 3 | 3 |
| live plan positions (build 09:59 / 09:06 CT) | 6 | 8 | 2 | 1 |

- **The brief's picture, re-measured.** The Suggested set is still mostly negative at the venue (2/0, 2/1, 2/0).
  - This now costs nothing: those rows are refused at the venue price, and the venue-positive ones arrive through
    the EV-only path instead.
  - The "wrong set" problem is now a floor question, not a population question.
- **The one venue-blind gate left is the commit's GROSS 2%** (`portfolio_commit.py` `below_min_ev_pct`).
  - It is applied at the venue price, beside net > 0.
  - On 10-21 it refused 1 of 7 Kalshi candidates: NCAAF h2h, net +0.35 / gross +1.41.
  - On a fee venue, gross and net are two floors on one quantity. The design below replaces both with one net
    floor per venue.
- **The other side of a line.** The board's one-side-per-line rule runs only among Suggested rows, so
  `other_side_suggested` could in principle hide the venue-positive side. Count today: **0**.
- **Same bet on both venues.** ORE @ ILL h2h away (10-24) is a live position on Kalshi AND on Polymarket, in both
  dates' plans.
  - The venue-contract dedupe (`4ffb4e64`) is per venue by design.
  - That is lane `live-event-concentration`'s question (#711), noted here and not acted on.

## Finding 2: the floor, from settled ROI and same-venue CLV

**R1 venue-native, both venues, by net-of-fee EV floor (12 dates):**

| floor (net, at venue) | bets / events | claimed net EV | flat ROI | CLV pt (marked) | fee pt |
|---|---|---|---|---|---|
| ≥ 0 | 825 / 201 | +0.97% | **−14.0% ± 5.0** | +1.87 ± 0.57 (275) | 1.34 |
| ≥ 0.5 | 544 / 162 | +1.33% | −12.1% ± 5.5 | +2.67 ± 0.88 (166) | 1.28 |
| ≥ 1 | 309 / 111 | +1.74% | −23.4% ± 6.4 | +3.84 ± 1.67 (84) | 1.18 |
| ≥ 2 | 86 / 28 | +2.51% | −25.4% ± 12.6 | +1.28 ± 0.64 (15) | 0.91 |

**Without MLB** (MLB R1: 326 bets on **19 events**, −25.3% ± 9.3, almost all props):

| floor | Kalshi: bets / ROI | Kalshi: CLV mean / trimmed-10% / median vs fee | Polymarket: bets / ROI | Polymarket: CLV mean / trimmed / median vs fee |
|---|---|---|---|---|
| ≥ 0 | 288 / −5.9% ± 6.4 | 0.61 / **0.82** / 0.94 vs **1.60** (152 marked) | 212 / −7.0% ± 7.4 | 4.81 / **1.85** / 1.13 vs **1.50** (77) |
| ≥ 0.5 | 130 / −4.6% ± 9.2 | 1.13 / **1.12** / 0.94 vs **1.63** (75) | 159 / +3.2% ± 8.4 | 5.86 / **2.05** / 1.13 vs **1.50** (56) |
| ≥ 1 | 68 / −2.1% ± 12.0 | 1.57 / **1.65** / 1.13 vs **1.64** (43) | 61 / −8.8% ± 12.1 | 16.77 / 15.38 / 2.47 vs 1.50 (13, outliers) |
| ≥ 1.5 | 16 / −26.7% ± 18.1 | 0.41 vs 1.49 (9) | 23 / +1.5% ± 19.1 | 1.38 vs 1.50 (7) |

**How the floor is argued.**
- **CLV is the low-variance instrument here; ROI at these samples has an SE of 6–12 points and cannot separate floors.**
- A pick is break-even at the close only if it beat the close by more than it paid in fee. Both are in probability
  points of payout.
- Even that is generous: the close is a vigged price, so beating it is necessary, not sufficient.
- **Kalshi:** the trimmed CLV clears the fee only from **≥ 1% net** (1.65 vs 1.64 pt).
  - At ≥ 0 every pick averages **−0.78 pt** at the close after fee. At ≥ 0.5 it is −0.51.
  - Floor 1.0 is the lowest floor at which the average Kalshi pick is not already losing at the close.
- **Polymarket:** the trimmed CLV clears the fee from ≥ 0 (+0.35 pt) and more clearly from ≥ 0.5 (+0.55).
  - The mean is outlier-driven (a +16.8 band on 13 marks), so the trimmed value is the one to use.
  - Floor 0.5 is where the margin stops being within one mark's noise.
- **The ROI does not contradict this and does not confirm it.**
  - Non-MLB Kalshi ≥ 1: −2.1% ± 12.0.
  - Polymarket ≥ 0.5: +3.2% ± 8.4.
  - With MLB, every Kalshi floor is ≥ 2 SE below zero, and HIGHER Kalshi floors do worse (≥ 1.5: −40.6% ± 10.2).
    That is the 2026-09-29 standing finding again: claimed EV does not rank.
  - So the floor removes the picks that are losing at the close. It does not create an edge the data cannot show.
- **The brief's "~+3.8% claimed".** That figure is GROSS EV. Net of the venue fee, R1's claimed EV is +0.97%, and
  ~60% of R1 sits in the 0–1% net band.
  - At the venue, almost all of the claimed edge IS the fee (as `paper-bet-optimization` found: 786 of 917 bets in
    0–2%).

## Finding 3: venue-native (R1) vs the current Suggested set (R2)

| | R1 venue-native | R2 Suggested |
|---|---|---|
| both venues | **−13.8% ± 5.0** (826 / 201 ev / 12 dates), claimed net +0.97% | **−2.0% ± 7.9** (92 / 44 ev / 7 dates), claimed net +1.70% |
| kalshi | −16.3% ± 6.1 (524), CLV +0.69 pt vs fee 1.24 | −4.5% ± 9.6 (63), CLV +0.32 (19) vs 1.19 |
| polymarket | −9.5% ± 6.9 (302), CLV +4.86 (78) vs 1.50 | +3.5% ± 15.9 (29), CLV −2.22 (12) vs 1.50 |
| ncaaf only | −6.8% ± 6.8 (353 / 116 ev) | +0.9% ± 15.3 (40 / 23 ev) |
| mlb only | −25.3% ± 9.3 (326 / **19 ev**) | −4.0% ± 4.7 (35 / 7 ev) |
| nfl only | −6.9% ± 10.7 (82) | +11.3% ± 22.1 (10) |

- R2 − R1 = +11.8 points ± 9.3: **1.3 SE, not a difference**.
- Inside NCAAF it is +7.7 ± 16.7.
- **The Suggested set selects higher venue-net EV** (+1.70% vs +0.97% claimed): the best-book 2% screen carries
  part of the same information as a venue floor.
- R2 is also the population the pre-registered forward test (`paper-bet-optimization`, H3) is collecting.
- **Verdict:**
  - The data does NOT show that venue-native selection at a 0% floor beats Suggested.
  - On point estimates it is worse by about 12 points, and on the more trustworthy CLV-minus-fee it is negative on
    Kalshi.
  - It does not show the reverse either.

## Finding 4: interaction with the stake band and compounding

- **The live chain:** Kelly at fixed $1,000, then compounding (basis `venue_total`, `floor_one_contract`), then the
  band, then the trim to the order cap.
  - Band: `stake = min($10, $5 + $5 × full_kelly / 0.05)`, with the small-edge fraction 0.001 (option C).
  - Rows with full Kelly under 0.001 skip the $5 floor and stay at about one contract.
- **Measured on today's live plans:**
  - Floor rows with net ≥ 0.6% are staked **$5.40–$8.06**.
  - One exception: UCLA +13.5 at +1.11% was $0.51 in the 10-21 build and $5.49 in the 10-22 build, presumably a
    funding-cash difference between builds. Not chased.
  - Rows at net 0.03–0.35% are staked $0.51–$0.69, at the one-contract floor.
  - Kalshi 10-21 holds 6 positions, $20.20 staked. $12.01 of it is in two rows at net +0.61% and +0.81%.
- **What that means:** for these rows the band is effectively a **flat $5–$7.60**, about 10× the Kelly stake on
  exactly the band (0–1.5% net) where Kalshi picks are net-negative at the close.
  - `paper-bet-optimization` replayed this: band $5–$10 on the venue paper set took $465 to $0, flat $5 likewise.
- **With the proposed floors (Kalshi 1.0, Polymarket 0.5) on today's plans:**
  - Kalshi 10-21 keeps 2 of 6: TROY h2h +1.30, $6.53; UCLA +13.5 +1.11, $0.51 in that build.
  - It drops ORE h2h +0.61 ($6.61), UNT/NAVY u61.5 +0.81 ($5.40), LIB/KENN u49.5 +0.35 ($0.53) and Lens o2.5 +0.03
    ($0.62).
  - Polymarket 10-21 keeps ORE h2h +1.01 ($7.60) and drops NFL u49.5 +0.17 ($0.52).
  - The floor mainly removes the band-inflated $5–$7 stakes on thin edges. Volume falls roughly by half on these
    two builds, which is two dates and only an illustration.
- **Compounding is unaffected by the floor's position.** The floor is a selection gate before sizing, so the
  compounding basis and caps see fewer rows, not different stakes.
- **The live floor's own stop rule** (≥ 100 settled live floor bets with ROI < −5% returns live to Suggested-only)
  is a good backstop. At about 5–10 live bets a day it fires in 2–3 weeks at the earliest, at band stakes.

## Design: what would be built on a yes (nothing built yet)

**Goal.** For each venue V, the live candidate set is every shortlist row that passes all of the following.
- **(a) The non-EV Suggested gates, unchanged** (venue-blind line properties):
  - opportunity lane;
  - fair method present and two-sided (not `book_margin_model`);
  - not `single_book_fair`;
  - not `suspect_stale_quote`;
  - `books_quoting` known.
- **(b) Venue pricing.** It is priced from V's own feed (`price_source = venue_feed`) and passes
  `venue_ev_implausible`.
- **(c) A net-of-fee floor at V's executable price.** `ev_pct_net_of_fee ≥ floor(V, cell)`.
  - Starting floors: Kalshi 1.0, Polymarket 0.5.
  - The cell value comes from the min_ev tuner when it is in `apply`. Otherwise it is the venue start.
- **(d) One side per line, chosen at V's price.** Today the side is chosen among Suggested rows at the best book.

**Code shape (about 40 lines; two files, both claimed by other lanes, so a loan is needed):**
- `pipeline/portfolio_commit.py`:
  - `live_ev_floor_rows` becomes "non-EV gates passed" (it already is).
  - A per-venue `_live_net_floor(venue)` read from a new key `SYNDICATE_LIVE_NET_FLOOR_<VENUE>` (absent = today's
    behaviour, so off != on is testable).
  - A venue-side one-side-per-line pass after `scope_rows_to_venue` on the live branch.
- `syndicate/features/shared/portfolio_commit.py`:
  - On a VENUE-SCOPED row (`venue_fee_basis` present), the gross `below_min_ev_pct` cut gives way to the net floor.
  - This is behind the same key, so paper2, the ladder and the main book are byte-identical.
- **Tests:** reachability (key absent → plans identical to today; key set → the floor binds); the one-side pass;
  a net floor refusal named `below_live_net_floor`.
- **Which lane owns what:**
  - The min_ev tuner (lane `min-ev-tuner-shadow`) already tunes a per-cell NET floor. This design hands it the venue
    starting point and changes none of its rules.
  - The ladder (`paper-alongside-live`) keeps recording below the floor at $1. That is how the floor stays falsifiable.

**Simpler alternative with no code:** set `SYNDICATE_PORTFOLIO_MIN_EV_NET_OF_FEE_PCT=1.0` in the refresh-worker env.
- This is the existing commit net floor (`_min_ev_net_of_fee_pct`).
- It is ONE number for every venue. It is also read by paper2 and the main venue books, so it moves the paper
  forward test's population too.
- So it is not recommended. It is listed because it is the one-line form of the same idea.

## BUILT 2026-10-21 (user: "Yes: build the per-venue live net floor ... No fleet env change or restart until I say so")

- **Code.** `pipeline/portfolio_commit.py`: `live_net_floor(venue)` reads `SYNDICATE_LIVE_NET_FLOOR_<VENUE>`, and `_apply_live_net_floor` runs inside `commit_live_venue_plan` after the placeable check.
  - Absent or empty key: nothing runs, so the plan is today's.
  - Refusals, each counted in the plan's `refusals` tables: `below_live_net_floor` (net < floor; the floor itself is admitted), `no_venue_net_ev`, `other_side_better_at_venue` (one side per line at the venue's price), and `live_net_floor_unreadable` (key set but not a number in [-5, 20]: every row refused).
  - Stamp `plan["live_net_floor"]` and log line `[portfolio_commit] LIVE_NET_FLOOR date=.. venue=.. {...}`.
- **Deviation from the design above:** the commit's GROSS 2% gate is kept, so `syndicate/features/shared/portfolio_commit.py` (min-ev-tuner-shadow) is untouched.
  - At net floors of 1.0 / 0.5 the gross gate is nearly redundant: on 10-21 the one row it refused had net +0.35, below both floors.
- **Tests.** `tests/test_live_net_floor.py`, 22 tests; 3 mutants (inclusive bound, the call removed, keep-last instead of keep-best) all caught.
  - Neighbours: live_ev_floor / kalshi_plan_placeable / compounding / stake band / portfolio_commit / paper_ladder 170 pass, and execute_portfolio / in_play / checklist 107 pass. The input checklist PASSED.
- **To enable (user decision, not done):** add `REFRESH_WORKER__SYNDICATE_LIVE_NET_FLOOR_KALSHI=1.0` and `REFRESH_WORKER__SYNDICATE_LIVE_NET_FLOOR_POLYMARKET=0.5` to the fleet env, then restart refresh-worker under the deploy locks, on a HEAD containing the build commit.
  - Verify with the first `LIVE_NET_FLOOR` line per venue, and with live plans with `below_live_net_floor` > 0 and no position below the floor.
  - Undo: remove the keys and restart.

## Coordination

- **`min-ev-tuner-shadow`:** owner session b98807bc is not among the linked sessions, so this is written to its lane
  block, not messaged. Two items:
  1. The proposed per-venue starting floors.
  2. **The live CLV unit defect (Answer §4). It contaminates the tuner's live evidence.**
- **`paper-alongside-live`:** the ladder's 10-26 readout grades exactly the 0–1 / 1–2 bands this floor would cut. If
  its pre-registered rule reads AGAINST a band, that agrees with this floor. If it reads CANDIDATE, the floor comes
  down per venue.
- **`compounding-bankroll` / `live-stake-band`:** Finding 4 is theirs to weigh. Applying the band only above the floor
  is an equivalent lever.

## Reproduce

1. `wsl -- bash /mnt/c/tmp/venuenative/gap.sh 2026-10-21 2026-10-22`. This runs the shortlist probe and writes
   `gap_out.json`.
2. `wsl -- bash /mnt/c/tmp/venuenative/dump.sh`. This writes the ledger dump to `ledger_venue.json`.
3. `py -3 scripts/venue_native_selection_study.py C:/tmp/venuenative/ledger_venue.json .`

The probe and dump scripts sit in `C:\tmp\venuenative\`. They are not committed: they read the fleet's process
environ.
