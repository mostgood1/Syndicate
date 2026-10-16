# Props book coverage — why spots show 3-5 books (lane `props-book-coverage`, session 9e18a0e7, 2026-10-16)

User, 2026-10-16: "we have a lot of spots that say only 3-5 books. but we should be pulling a pretty large set of books.
is it possible they just arent being mapped right?" and "the layer 1 board should be pulling all of these already (i
thought)".

## Verdict

**Not a mapping bug.** The sheet's `books_quoting` equals the raw capture's exact-line book count on **1,024 of 1,031**
prop rows (99.3%); nothing between capture and sheet allowlists or renames a book (`odds_book_quotes._normalize` only
lower-cases). The FIRST drop is the **fetch** — Layer 1's own request — and Layer 2 can only show what Layer 1 fetched:

- Layer 1's own NHL props files hold exactly **3 books** (`nhl_source/tracking/odds_nhl_player_props_opening_2026-10-1[56].csv`:
  draftkings, fanduel, pinnacle) — the `PROPS_ODDSAPI_BOOKMAKERS` default in `syndicate/local_nhl_odds.py`.
- Every other sport's props ask `regions=us` only (soccer's Layer 1 file: the 8 `us` books). The `us2` region's books
  are in no shard of any sport since 09-30.

Further down (ranked, from the read-only survey): within `us` not every book prices every player (NFL median 6 of 8,
NCAAF 3 of 6, MLB FanDuel ~1% of DraftKings' rows, soccer O/U 2 books); the board withholds one-sided markets with no
model view (Anytime TD, goal scorer — the widest markets); alternate lines split the count; the board/picks count FRESH
books only (NFL props 3 fresh of 5).

## The probe (8 credits, 2026-10-16 17:12Z / 12:12 PM CT; user "One probe call (Recommended)")

One market, one event per call; cost from each response's `x-requests-last` (the account's `used` counter moved more
in the window — the fleet was fetching too):

| sport | market | event | `us2` adds | cost |
|---|---|---|---|---|
| NFL | player_receptions | HOU @ JAX 10-18 | ballybet, betparx, espnbet, fliff, hardrockbet, hardrockbet_fl | 1 |
| NCAAF | player_pass_yds | Memphis @ Tulane 10-16 | espnbet, hardrockbet | 1 |
| NHL | player_shots_on_goal | PIT @ COL 10-16 | ballybet, courtside, espnbet, fliff, hardrockbet | 1 |
| MLB | batter_hits | TB @ CLE 10-16 | ballybet, betparx, espnbet, fliff, hardrockbet | 1 |
| Soccer (EPL) | player_shots_on_target | CHE @ EVE 10-17 | ballybet, betparx | 1 |

**NHL billing, same event + market:** old 3-book list → 1 credit, 3 books; `regions=us` → 1 credit, 5 books
(betmgm, betonlineag, bovada, draftkings, fanduel) — **Pinnacle dropped**, it is not a `us` book; a **10-book list across
regions** (draftkings, fanduel, betmgm, williamhill_us, betrivers, fanatics, espnbet, hardrockbet, pinnacle,
betonlineag) → **1 credit, 7 books** (betmgm, betonlineag, draftkings, espnbet, fanduel, hardrockbet, pinnacle).

## What follows

- **Shipped:** NHL props default to that 10-book list (`NHL_PROP_BOOKMAKERS`, `syndicate/local_nhl_odds.py`); the env
  knob still overrides. Reading owed: the next fleet NHL props run's distinct books per event, and its credits per
  event against the 3-book baseline.
- **For the user to price:** adding `us2` to prop fetches DOUBLES every prop call's credits (2 regions). A curated
  10-book list per sport gets the most-wanted `us2` books (ESPN Bet, Hard Rock) and Pinnacle at ONE region's price, at
  the cost of dropping the least useful `us` books for that sport. Not done for the other sports — that is a per-sport
  choice of which ten.
- UNVERIFIED: why FanDuel is near-absent on MLB props (the provider's response); what `us2` adds on a busier slate.
