# Layer 2 OUT-player gate: the 5 failing tests are the END-TO-END tier, and the gate itself is fine

Re-baselined 2026-10-12 on `origin/main` (worktree `dd33429a`), 3 days after the
2026-10-09 primary-tree run. Lane: none taken -- recorded, not fixed.

## The re-baseline holds, unlike the NFL cluster

`tests/test_layer2_out_player_gate.py`: **5 failed, 5 passed** -- the SAME five
tests as 10-09. (For contrast, `test_nfl_player_stats.py` went 14 -> 2 -> 0 over
the same period, so a handed-down list is not reliable either way; it has to be
re-run.)

They also fail in a SPARSE worktree with no `data/` and no `vendor/`, where the
10-09 measurement was a complete checkout. Failing in both means these are **not
data-dependent**.

## What is actually wrong -- two earlier framings of mine were WRONG

I had described this as "an OUT-player gate that may not be gating", and as a
possible inert feature on the strength of a failing `off_is_not_on` name. Both are
wrong. The file has two tiers:

| tier | calls | result |
|---|---|---|
| 5 DIRECT tests | `select_shortlist(rows)` | **PASS** -- including `test_off_is_not_on_the_same_row_seats_without_the_flag`, the gate's own reachability test |
| 5 END-TO-END tests | `build_layer2_rows` -> `select_shortlist` | **FAIL** |

So the gate's logic is verified and reachable. What is unverified is the path the
fleet actually runs, which is why those end-to-end tests exist -- the file's own
comment says so: *"The tests above hand rows straight to select_shortlist.
Production does not: build_layer2_rows rebuilds every candidate from
_IDENTITY_FIELDS plus explicit [fields] ... These go grid row -> build_layer2_rows
-> select_shortlist, the path the fleet runs."*

**One test passes VACUOUSLY.** `test_the_sample_is_empty_when_nothing_is_gated` is
green because there are zero candidates -- the same reason the other five are red.
A green that depends on an empty frame is not evidence.

## Root cause, as far as it can be taken from a sparse worktree

`build_layer2_rows([_grid_prop(...)])` returns:

    rows_in 1   sides_priced 2   candidates 2   scored 2
    no_bettable_book 0   stale_book_skipped 0
    by_lane = {'watchlist': 2}        opportunities: 0

Nothing is dropped -- both candidates are built and scored, then classified to
`watchlist`. `opportunity_gate.evaluate(row)` gives:

    lane='watchlist'  market_state='pregame'  reasons=('no_market_posted',)

`opportunity_gate.py` reaches that at the `price = _number(quote.get("price"))`
test: no `quote`, or no price in it, means "books have not posted yet", which the
code is explicit is **not a defect** (63% of the board was in that state).

And the state resolves fine -- `game_state_of(row)` is `'pregame'`, so the
`no_game_state` demotion is NOT the cause. (That was my first hypothesis and it
was wrong.)

The grid fixture `_grid_prop` carries `best: {over: {price: 118, ...}, under:
{...}}` and NO `quote` key, while the direct fixture `_prop` carries `quote:
{price: 118, ...}`. **Adding a row-level `quote` to the grid row does NOT flip the
lane** -- still `{'watchlist': 2}`. So the rebuild owns the gap: it reports
`sides_priced=2` from `best`, but the candidate it emits does not carry the
`quote.price` the gate reads.

## The discriminator, NOT settled here

Either:

- **(a) the fixture is stale** -- real grid rows carry a field `_grid_prop` lacks,
  and `build_layer2_rows` passes the price through for them; or
- **(b) `build_layer2_rows` does not pass the price through for props**, in which
  case production prop rows demote to `watchlist` too and the board under-seats.

(b) would be a live board defect. Against it: peers report boards seating rows. For
it: nothing in this worktree. Settling it needs a real grid row -- the primary tree
or a captured `book_grid` payload -- not a hand-built fixture, because a fixture is
exactly what is in question.

## If someone picks this up

`syndicate/features/shared/layer2_board.py`, `opportunity_gate.py` and this test
file are all UNCLAIMED as of 2026-10-12. `board_enrichment.py` is held by
`web-restart-healthz`. Start from a REAL grid row and compare its keys against
`_grid_prop`'s; do not change the gate or the rebuild until (a) vs (b) is decided,
because both fixes move board behaviour.
