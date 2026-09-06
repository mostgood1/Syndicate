# `venue_quote_fanin` HAS NO `segment` — the 2026-08-28 defect survives in a second module

`[found 2026-09-06 ~18:4xZ, lane kalshi-alt-line-join (incidental), substrate: render]`

**Found while taking an unrelated reading. Not fixed. Not mine to fix silently —
recorded so it cannot be lost, and flagged because it is the same class as a
defect that already cost real money.**

## The finding, in one reading

Production `/api/board/layer2-shortlist?date=2026-09-06&sport=mlb`, SF@NYM,
`totals / 4.5 / over`:

    segment=first5   kalshi = -213
    segment=full     kalshi = -213      <- IDENTICAL. One venue quote, two different bets.

A first-five-innings over 4.5 and a full-game over 4.5 are not the same wager and
cannot share a price. `-213` is ~68%, which is a plausible FULL-GAME number and
an implausible first-five one.

## Why it happens — the key has no segment dimension

`syndicate/features/shared/venue_quote_fanin.py` is 1,700 lines and the token
`segment` appears in it **zero times**. `_candidate_keys()` (`:870`) builds the
key from `(sport, market, side, line)` plus player/team tokens. So

    first3 | totals | over | 2.5      and      full | totals | over | 2.5

are the SAME KEY for the same game, and the first venue quote to arrive wins.

**This is exactly `[kalshi-segment-on-full-game]` (`state_kalshi.md`), which cost
$7.08 of real money on 2026-08-28 and was fixed by putting `segment` into
`_match_key`/`_row_key` and adding `_segments_agree`.** Those live in
`kalshi_board_join.py`. **`venue_quote_fanin.py` has its own key and the fix
never reached it.** `_segments_agree` fires 257 times a tick in the join and is
completely bypassed on this path.

This is the standing rule "fix the choke point all callers share, not the one you
can see" — and it was not followed, by me or by the original fix.

## Scale, with the denominator

13 of the segment rows on today's MLB slate carry a NATIVE kalshi venue quote
(`book_prices == {'kalshi': ...}` alone, with a `venue_basis` block naming
`venue: kalshi`). The magnitudes confirm they are full-game prices worn by
segment bets:

| row | kalshi | implied | plausible as |
|---|---|---|---|
| `first3 totals 2.5 over` (TB@TEX) | **-2400** | ~96% | full game (a first-3 over 2.5 is ~35%) |
| `first1 totals 2.5 over` (ATL@PHI) | **-1900** | ~95% | full game (a first-INNING over 2.5 is ~10%) |
| `first5 totals 7.5 over` (DET@CLE) | -144 | ~59% | full game (a first-5 over 7.5 is ~10%) |
| `first3 totals 3.5 over` (ATL@PHI) | -525 | ~84% | full game |

## What is currently holding it back, and it is NOT a guard

All 13 read `servable: False, displayable: False`. **That is staleness, not
safety.** The `venue_basis.reason` on every one of them is:

> *"venue quote is 59s old against a 45s ceiling: on a live market that is a
> different game state, not a stale price"*

**A fresher quote removes the only thing standing between these rows and the
board.** Nothing on this path is checking segment at all, so the protection is
incidental and expires the moment the venue refreshes inside 45s. Today's EVs are
also negative (-0.94 to -1.97), which is luck of which side the mispricing
favours, not a control.

## What I did NOT establish

- Whether any order has ever been PLACED off a `venue_basis` quote that crossed a
  segment. I checked the board, not the order path. `0 of 597` live orders carry
  a `KXMLBF5*` ticker, but these quotes carry no ticker at all, so that count
  does not answer it.
- Whether the same key collision affects Polymarket on this path. The module is
  venue-agnostic, so it probably does, and that is unmeasured.
- Whether `first1`/`first3` rows can reach a stakeable state at all, or are
  filtered earlier for another reason.

## The fix shape, when someone takes it

Put `segment` in `_candidate_keys` and refuse a cross-segment pairing by NAMED
reason, mirroring `_segments_agree`. Do **not** rely on the staleness ceiling.
The reachability test must be `off != on` on a real segment row, and the guard
must be shown FIRING, not merely present — the 08-28 entry's own lesson is that
"deployed and plausible" is not enough.

---

## Separate, smaller, and mine: a counter I shipped that nobody can read

`alt_main_collisions` was added to the `join_kalshi_to_board` **return dict**
today (`21aac548`), but the `[kalshi_odds] BOARD_JOIN` / `[portfolio_commit]
KALSHI_BOARD_JOIN` log lines print only `kalshi_markets`, `board_rows`,
`matched` and `reasons`. **The counter is therefore invisible in production** —
confirmed over 8 join ticks, none of which carry the token.

I wrote in its own comment that "a tie-break nobody can see the frequency of is
one nobody will revisit", and then shipped it unreadable. It needs adding to the
print in `pipeline/kalshi_odds_refresh.py:join_to_board` before the tie-break can
be said to be observable. No behaviour is wrong; the instrument is missing.
