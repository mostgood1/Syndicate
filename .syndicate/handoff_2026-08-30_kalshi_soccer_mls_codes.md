# HANDOFF — Kalshi SOCCER blob resolution: four missing MLS codes, patch VERIFIED, file contested

**From** lane `live-venue-order-placement`, session 69f9e24f, 2026-08-30 ~01:4xZ.
**To** whoever holds `syndicate/features/shared/team_aliases.py` — currently
claimed by **`open-bet-live-status`** AND **`ncaaf-settlement-resolver`**, and
lane `exchange-join-refusals` (session 5611932c) has just announced it intends
to work there too. **Three claimants is why I did not take it**, not doubt about
the fix.

## The defect, measured on production after `0c5243b4`

`/api/board/layer2-shortlist` `written_at 01:38:12Z` (post-deploy):

    kalshi soccer   live totals = 8   SHARING ONE PRICE ACROSS GAMES = 4
        over  1.5 @ -900  -> Los Angeles FC@D.C. United AND New York City FC@Toronto
        under 1.5 @ +669  -> the same two

This is the ONLY population that still shares after `#603`. MLB and NCAAF showed
0, but both were NOT COLLIDABLE (no two live games shared a `(side,line)`), so
those zeros prove nothing. Soccer is the one real reading.

## Root cause, and it is a four-row data gap

`_kalshi_game_token` -> `match_event_blob`, which splits Kalshi's blob and
requires **both** halves to resolve through `canonical_team(sport, ...)`. Four
MLS codes are absent from the soccer map, so the split never completes, the key
stays bare, `quote.game` stays None, the rejection cannot fire, and one quote
answers every soccer row sharing that line.

Read live from Kalshi (paginated, 367 markets — an unpaginated pull would have
under-reported this):

    NYRBPHI   unresolved half NYRB
    PORATX    unresolved half POR
    SDLAG     unresolved half LAG
    STLDAL    unresolved half STL

Confirmed against the real ESPN MLS fixtures for 08-29/30, not guessed.

## The patch, and it is VERIFIED, not proposed

Sport-scoped overlay following the `_WNBA_EXTRA_ALIASES` precedent that already
exists in this file — the comment there explains the reasoning: it lives in
`team_aliases` specifically so it cannot reach a merged map and reassign another
league's codes.

    nyrb -> red bull new york
    por  -> portland timbers
    lag  -> la galaxy
    stl  -> st. louis city sc

Measured by monkeypatching `canonical_team` with exactly these four:

    BEFORE   NYRBPHI/PORATX/SDLAG/STLDAL  ->  no_match  (4/4)
    AFTER    all four  ->  ok, with the CORRECT teams:
             NYRBPHI -> Red Bull New York @ Philadelphia Union
             PORATX  -> Portland Timbers  @ Austin FC
             SDLAG   -> San Diego FC      @ LA Galaxy
             STLDAL  -> St. Louis CITY SC @ FC Dallas

**COLLISION CHECK PASSED — this is the bit that matters for your lanes.**
`STL` and `POR` collide with other leagues (Cardinals, Blues, Trail Blazers), so
the overlay MUST stay sport-scoped:

    patched('mlb','STL')   -> 'st. louis cardinals'   (unchanged)
    patched('nhl','STL')   -> None                    (unchanged)
    patched('ncaaf','STL') -> None                    (unchanged)

A merged map here would reassign another league's code, which is precisely the
failure `_WNBA_EXTRA_ALIASES`' comment was written about.

## Why it fixes rows whose own game Kalshi does not even list

LAFC@DC United and NYCFC@Toronto have **no Kalshi MLS market at all** — I
checked all 367. The `-900` they share therefore belongs to some OTHER soccer
fixture and reaches them through the bare key. Qualifying the resolvable blobs
stops those quotes answering rows they do not belong to, which is the whole
mechanism.

## How to verify after deploying

1. `/api/board/layer2-shortlist?date=<d>&limit=2000`, on a pool whose
   `written_at` is LATER than your deploy — that endpoint is a pure read and I
   nearly reported a working fix as broken by ignoring this.
2. Count live soccer totals rows sharing one price across games. **4 -> 0.**
3. **FIRST check the population is COLLIDABLE** (≥2 live games sharing a
   `(side,line)`). A zero on a non-collidable slate proves nothing — that trap
   ate my MLB and NCAAF readings tonight.
4. `[venue_quote_fanin] CROSS_GAME_REJECTED_GRID` may appear; it is a backstop,
   so 0 is consistent with success once keys resolve.

## Not fixed by this

Soccer blobs whose codes are still absent beyond these four, and any fixture
Kalshi orders differently from our board — `match_event_blob` checks
`left==away, right==home` only and does not try the reverse. Neither is
diagnosed; both are separate from this data gap.
