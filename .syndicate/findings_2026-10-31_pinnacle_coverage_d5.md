# D5 Pinnacle coverage: which missing paper-bet closes can the fetch buy, and at what cost `[2026-10-31, lane pinnacle-coverage-d5, session e32fef1a]`

**User, verbatim:** "Pinnacle coverage". That answered this session's button "Do the D5 read here: which of the missing
NBA, NFL and soccer markets Pinnacle offers through OddsAPI, and what widening would cost in credits. Read-only, no
fleet change."

This is the D5 decision of plan `#736` ("OddsAPI spend: widen sharp-book coverage ... Yes, within budget first",
adopted 2026-10-26), read against the Phase 2 edge gate's clock. The clock reading is log 2026-10-30 23:15Z:
- 300 of 414 graded paper bets have no Pinnacle close.
- Of the 279 misses, 189 are class B: Pinnacle quotes the event, but not that market or player.

**Nothing was changed.** No code, env or fleet setting changed. The probe spent 29 OddsAPI credits.

## Readings

All scripts are in session e32fef1a's scratchpad:

| Reading | Script | When | Where |
|---|---|---|---|
| Fleet env knobs | `fleet_odds_env.py` | 15:2xZ | three roles, NUL-split `/proc/<pid>/environ`; values printed only for region and bookmaker lists |
| OddsAPI probe | `pinnacle_probe.py` | 15:29:59Z | key from the refresh-worker env, never printed |
| Swap cost | `swap_cost.py` | 15:31-15:33Z | fleet `book_quotes` shards, kickoff dates 10-16..10-30, HEAD `413a08d5` |
| Paper bets in the cells | `swap_gain.py` | | `decision_policy_paper/bets.jsonl` + `grades.json` |

### 1. What we ask Pinnacle for today (code + fleet env)

| Sport | Game lines | Props call (`prop_bookmakers`, 10 books bill as 1 region) |
|---|---|---|
| NBA | ride the per-event props call | `odds_regions.py:161` has **pinnacle** (swapped in for betonlineag 10-25) |
| NFL | `SYNDICATE_NFL_GAME_LINE_REGIONS = eu` on all three roles, so Pinnacle is included | `odds_regions.py:149` shared list, **no pinnacle**; caller `fetch_nfl_oddsapi_props_local.py:302-312`; no env override on the fleet |
| Soccer | `SYNDICATE_SOCCER_GAME_LINE_REGIONS = eu`, so Pinnacle is included (BTTS and corners are not on that endpoint) | `odds_regions.py:168` soccer list, **no pinnacle**; caller `fetch_soccer_oddsapi_props_local.py:592-595`; BTTS + corners ride it (`:78`) |
| WNBA | `SYNDICATE_WNBA_ODDS_REGIONS = us_ex,eu` | season over |

The user's 2026-10-25 instruction, "Include Pinnacle for NBA/NFL/soccer/WNBA in the odds fetch", reached:
- NBA props and game lines;
- NFL, soccer and WNBA game lines.

It did **not** reach the NFL or soccer prop calls.

### 2. What Pinnacle offers through OddsAPI

The probe used `/events/{id}/markets`, then `/odds` with `bookmakers=pinnacle,draftkings,fanduel,betmgm`, on 2 upcoming events per sport.

| Sport | Pinnacle offers | Pinnacle does NOT offer | Selections priced, Pinnacle vs DK / FD |
|---|---|---|---|
| NBA (POR@UTA, PHI@CHA) | points, rebounds, assists, threes, PRA; main + alt spreads/totals incl. h1/q1/q2 | **steals, blocks**; any player alternate (one line per player) | points 11 vs 11/11 and 6 vs 5/6; rebounds 10 vs 11/11; **assists 6 vs 11/9** and 5 vs 5/6; threes 10 vs 10/10 |
| NFL (ARI@DAL, ATL@TB) | receptions, reception yds, rush yds, pass yds, pass att/comp/TDs, anytime TD, defensive INT | player alternates | receptions **11 vs 11/11** and **10 vs 10/10**; reception yds equal; rush yds equal; pass yds equal |
| Soccer EPL (CRY@TOT, FUL@AVL) | **btts, alternate_totals_corners** (5 outcomes a side, so several lines), plus double chance, DNB, cards and corners spreads, correct score | | btts 2 vs 2/2; corners 2 sides x 5 lines vs DK 5, FD 25 |

**Cost check:**
- Each `/odds` call with Pinnacle in a list of 4 or fewer books billed exactly one credit per market: NBA 6 and 5, NFL 4, soccer 2.
- A Pinnacle **swap** into a 10-book list therefore costs **0 credits**; an 11th book would bill a second region.
- **Budget:** at 15:29:59Z, `x-requests-used` was 4,250,291 and `remaining` was 749,709, which sums to 5,000,000.

### 3. What the swap would cost in lines

The book to drop is the one that is the SOLE list book on the fewest lines, over kickoff dates 10-16..10-30.

| List | Lines | Drop candidate | Its quote share | Sole on |
|---|---|---|---|---|
| NFL props (6 shard-days) | 21,879 | **betonlineag** (the NBA precedent's book) | 7.8% | **34 lines (0.16%)** |
| Soccer props (15 shard-days) | 77,744 | **williamhill_us** | 0.6% | **0 lines** (0 of 2,916 BTTS/corners lines too) |

- Next cheapest NFL books: fanatics 91 (0.42%), williamhill_us 93.
- Next cheapest soccer book: betparx 4.

### 4. Paper bets in these cells (10-27..10-30), and the gate

| Strategy | NFL props: booked / graded with no sharp close | Soccer BTTS+corners: booked / graded with no sharp close |
|---|---|---|
| `ev_lb` (P1) | 4 / 1 | 1 / 1 |
| `net_floor_719` (P2) | 11 / 4 | 9 / 7 |
| `suggested_2pct` (C0) | 8 / 4 | 28 / 18 |

- NFL prop bets are Receptions 21, Passing TDs 2.
- **Upper bound for P2:** about 20 bets in 4 days, about +5 sharp-graded a day on a pace of about 11.
- **Expected: less.** Pinnacle prices one line per player. NFL receptions bets on another Kalshi rung become class C ("Pinnacle has the market, only at another line"), not graded. Soccer corners keep several lines. So about +2 to +4 a day.
  - This moves P2's first look (400 sharp-graded) by roughly a week from the early-December estimate.
- **The gain grows with the NFL slate**, and it also gives the DecisionRecord a sharp anchor on these lines (plan §9 model health: "the share of lines with a sharp-anchored fair").

## What is NOT fixable by fetch (no spend helps)

- **NBA class B (42 misses):**
  - Steals (5) and blocks (3) are not offered by Pinnacle.
  - Assists (15) and some rebounds (4) are players Pinnacle does not price; it prices fewer assists players.
  - Threes (15): Pinnacle priced 10 of 10 and 5 of 6 players on the probe events. The misses may be players or timing that this probe cannot separate. **Unresolved.**
- **Class C (78) is structural:**
  - Pinnacle quotes one line per player and no player alternates on any probed sport.
  - E3 (`#741`) found Pinnacle-anchored surfaces lose to Kalshi's own mid on derived rungs, so a derived "sharp close" would be a new registration, not a fix.
- **MLB props (114):** the season is over.

## Recommendation

Make the 0-credit swap.

**Change:**
- `PROP_BOOKMAKERS["nfl"]`: betonlineag -> **pinnacle**. Its own entry, like NBA's. NCAAF and MLB keep the shared list.
- `PROP_BOOKMAKERS["soccer"]`: williamhill_us -> **pinnacle**.
- Tests: `tests/test_prop_bookmakers.py` holds the 10-book ceiling.

**How it goes live:**
- Both fetchers run as fresh processes: `refresh_odds_sources.py:1103` runs `scripts/refresh_nfl_oddsapi.py`, and `:2195` / `:2349` run `scripts/fetch_soccer_oddsapi_props_local.py`.
- So a fleet fast-forward makes the change live at the next refresh, with no restart (to be confirmed on the fleet at the ff).

**Verify reading:**
- Pinnacle prop quotes appear in the NFL and soccer `book_quotes` shards after the ff.
- `x-requests-last` is unchanged per NFL and soccer prop call.
- New P2 bets in those cells grade with `sharp_close`.

This completes the user's 2026-10-25 instruction for NFL and soccer. It touches no staked probability, so it is safe before the 11-02 `#704` keep/revert.

**Owner of `odds_regions.py`:** lane `live-cell-scorecard` made the 10-25 NBA swap. The swap is a two-line data change in a shared file, so check the lane claims before editing.
