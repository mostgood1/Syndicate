# REFUTED — the Kalshi spreads side mapper, and why the patch was DELETED

> **`[2026-08-26]` The patch that used to sit beside this file has been removed
> from the repository, deliberately. Applying it would have placed real money on
> the EXACT OPPOSITE BET, roughly 10 orders per cycle.**
>
> It was labelled "BACKUP ONLY — do not apply". That was not enough. A working,
> tested, cleanly-applying patch labelled *backup* is a thing a future session
> reaches for when the primary stalls — which is precisely the situation in
> which nobody re-derives whether it was ever correct. **The label was doing
> the work that deletion should have been doing.** The knowledge is kept below;
> the loaded gun is not.

## What was wrong

Caught by syndicate-43, who had supplied the rule in the first place and then
checked the board's LINE SIGN, which neither of us had done.

The mapper resolved a side against the team named in the ticker. That part is
accurate. **The ticker stamped on the order was the wrong market**, so
faithfully resolving against it produced a faithful inversion.

Verified by hand, cloud session, on the exact production row:

```
board row  TEX @ CWS spreads:  away (Texas) line = +1.5 @ -185
                               home (CWS)   line = -1.5 @ +155
order built:                   side=away, line=+1.5   -> intent is TEXAS +1.5
ticker stamped:                KXMLBSPREAD-26AUG261940TEXCWS-TEX2
venue title for that ticker:   "Texas wins by over 1.5 runs?"  -> TEXAS -1.5

_side_to_kalshi("away", "spreads", "...-TEX2")  ->  "yes"   (i.e. TEXAS -1.5)
```

`TEX +1.5` and `TEX -1.5` are opposite bets. Texas +1.5 is the UNDERDOG getting
runs (priced -185, likely to cover); Texas -1.5 is Texas winning by two or more.
The mapper bought the second while the board meant the first.

**Systematic, not one row.** Every spreads order carrying a ticker had
`line=+1.5` with a suffix naming the picked team itself — TEX2, DET2, AZ2, KC2,
COL2, PIT2, ATL2, BAL2, HOU2, CIN2, MIL2. And every `line=-1.5` row — the
favourite, the one that genuinely corresponds to a Kalshi "wins by over 1.5"
market — carried NO ticker at all (`no_venue_ticker`).

## The real root cause is in the JOIN, not the side mapper

`kalshi_board_join._match_key` keys on Kalshi's strike as a POSITIVE MAGNITUDE
(`1.5`, parsed from "wins by over 1.5"). `_row_key` keys on the board row's
SIGNED handicap. So `1.5 == 1.5` pairs the **+1.5 underdog row** with the same
team's **-1.5 market**. The magnitudes coincide; the meanings are inverted. The
correct pairing can never key, because no board row carries `+1.5` for the
favourite.

Correct semantics: a Kalshi market *"T wins by over X"* is the board's
`(team=T, line=-X)`. From one ticker both board rows are reachable:

```
board row naming T at line == -X        -> kalshi_side "yes"
board row naming the other team at +X   -> kalshi_side "no"
```

## THE LESSON, which is bigger than this patch

**`OrderBuildError: unmappable_side` was not a bug. It was the guard.** It sat
in a table of failures beside `market_not_found` and `no_venue_ticker` and read
like one more thing to clear — 11 orders a cycle, "a straight mapping
omission". Clearing it would have removed the only thing standing between a
mis-keyed join and ten inverted real-money bets per cycle.

A refusal in a list of failures is indistinguishable from a defect. Before
clearing one, establish what it was refusing and why — the cheap test here was
one the venue could answer in seconds and neither session ran until after both
had a working implementation.

Related: the join ALREADY computes a correct `kalshi_side` and discards it.
`venue_scope.py` stamps only `ticker_resolver(row)`, so `OrderRequest` carries
the BOARD side and `_side_to_kalshi` is asked to re-derive at the boundary from
data that cannot settle it. **Re-deriving at a boundary what an earlier stage
already knew is what made this possible.** Same shape as the sim-input defect
`model_engine_standard.md` exists for.

## Ownership

The join fix and the side mapper both belong to syndicate-43
`[USER DECISION 2026-08-26]`, extended to the game-line spread path in
`kalshi_board_join.py` and the `kalshi_side` plumbing through `venue_scope.py`
/ `portfolio_commit.py` / `execute_portfolio.py`. The cloud session holds no
uncommitted work in any of those files.
