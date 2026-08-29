# HANDOFF — the Polymarket YES-leg evidence is shipped; the consuming edit is yours

**From:** lane `live-venue-order-placement`, session 69f9e24f
**To:** lane `unknown-submit-retry-provenance` (session 6475567d), which holds
`syndicate/features/shared/polymarket_us_orders.py`
**Date:** 2026-08-29
**Why a handoff and not a commit:** `[USER DECISION 2026-08-29]` — asked how to
handle the file conflict, the answer was "Split — I produce, they consume". I
did not edit your file.

## What is now available that was not

`#595` step 3 was blocked on this, in `polymarket_us_orders`' own words:

> WHY THIS IS A REFUSAL AND NOT A FIX. The sound rule needs the venue to say
> which outcome the YES token pays, by name. `/v1/markets` returns
> `marketSides` and `question` — both are already in
> `polymarket_us_markets._KEEP` — and `_slate_row_for_storage` drops both
> before the order path ever sees a row, so no name rule is writable today.

**That is no longer true.** `_slate_row_for_storage` now derives and persists:

    yesLegIndex    int | None   index in `outcomes` of the venue's YES leg
    yesLegReason   str | None   why it could not be derived, when it could not

Both keys are ALWAYS present, so an absent index is never confusable with a row
we never tried. `syndicate/features/shared/polymarket_us_markets.py`,
`yes_leg_index_from_market()`.

## How it is derived, and the trap it deliberately avoids

From `marketSides[].long`, which the venue states. Read live 2026-08-28 on three
NFL moneylines, `long_index` came back **0, 0, 1** — it VARIES, which is what
makes it a rule rather than a constant that agrees with position twice.

**The index comes from `outcomes`, matched BY NAME
(`description` / `team.name`), never from the position of the `marketSides`
entry.** Taking `marketSides[i]` would reintroduce the exact positional
assumption being fixed, one array over — same class of error as
`outcomes[0] == YES`, same lack of evidence.
`tests/test_polymarket_yes_leg_index.py::test_index_comes_from_outcomes_not_from_the_market_sides_position`
is the row that catches it: long side FIRST in `marketSides`, SECOND in
`outcomes`, correct answer 1.

Every ambiguity refuses with its own name and never resolves to an index:
`no_market_sides`, `market_sides_unreadable`, `no_side_marked_long`,
`two_sides_marked_long`, `long_side_has_no_name`,
`long_side_name_not_in_outcomes`, `long_side_name_matches_both_outcomes`,
`outcomes_unreadable`. Two `long: True` sides means `long` is not the yes/no
axis on that market, so the rule is void there — taking the first would be a
coin flip wearing a rule's clothes.

The `marketSides` blob itself is NOT persisted: the trimmed slate is already
4.9MB of an 8MB keyvalue ceiling. A small int and a short string cost bytes;
the blob would cost the ceiling.

17 tests, `tests/test_polymarket_yes_leg_index.py`. Existing suites green
(`test_polymarket_us_markets.py`, `test_polymarket_slate_freshness.py`,
`test_polymarket_us_orders.py` — 152 passed).

## What is EXPLICITLY NOT DONE, and must not be skipped

**I have not scored the rule against the 8 venue-settled moneylines, and
`#595` step 3 requires exactly that before the refusal comes off.** Including
the 3 that went wrong. Nothing here licenses flipping
`_resolve_outcome_side` — this supplies the input that scoring needs, not the
scoring.

Two specific cautions carried forward from `state.md
[polymarket-h2h-buys-the-wrong-side]`:

1. **A coverage number is not a correctness number.** `yesLegIndex` resolving
   on N% of rows says nothing about whether it resolves CORRECTLY. The
   discriminating test is against realized venue grades, not against
   derivation coverage.
2. **FLAGGED, NOT ASSERTED, and it scratches this rule:** on `hou-car` the long
   side's price (0.5100) matched `outcomePrices[0]` while the long side was
   `outcomes[1]` — which would mean the misalignment reaches the PRICE too. It
   rests on a ONE-CENT separation and needs a market where the long side is
   `outcomes[1]` AND the prices are far apart. If that holds, an index into
   `outcomes` is not by itself enough to price the leg, and this handoff's
   field is necessary but not sufficient. **Please resolve that before
   trading on it.**

## Why this matters beyond your lane

An arb between Kalshi and Polymarket is a MONEYLINE trade. The refusal is
correct and it currently blocks the entire cross-venue arb path, which
`findings_2026-08-29_live_venue_arb_economics.md` measures as viable at the
tails (break-even 0.52c–1.11c on in-play MLB, against 1c venue spreads). Your
lane is the choke point for that whole line of work — flagged so the priority
is visible, not to rush it. **A wrong polarity costs the bet AND pays the other
side; coverage may be traded for certainty, a side may not.**
