# NCAAF Card Parity Implementation Report

## Scope

This change extends the NCAAF cards surface so the shared generic card can show the same decision-support metadata that the NCAAF board already uses internally for Week 1 publication readiness.

The implementation stays out of football model math. It only exposes already-approved board metadata on the visible card surface.

## What Changed

- `syndicate/features/ncaaf/cards.py` now attaches Week 1 publication metadata to known publishable and suppressed matchup rows.
- `syndicate/templates/shared/_game_card_generic.html` now renders a compact SmartSim information box when coverage/publication fields are present.
- `tests/test_ncaaf_cards_local.py` verifies the new payload contract for both a publishable and suppressed Week 1 game.

## Visible SmartSim Fields

The NCAAF card now exposes these fields on the visible game payload when the matchup is known:

- `coverage_score`
- `coverage_tier`
- `publication_status`
- `publication_priority`

The card UI shows:

- Coverage
- Publication Tier
- Publication Status
- Publication Priority as a compact chip / note when present

## Verification Path

The verification path is:

1. `/ncaaf`
2. card payload from `syndicate/features/ncaaf/cards.py`
3. shared card renderer in `syndicate/templates/shared/_game_card_generic.html`
4. rendered card surface in the browser

The focused regression test confirms the payload now carries the new SmartSim publication metadata for both a publishable and suppressed Week 1 matchup.

## Does `/ncaaf` Have a SmartSim Box?

Yes. The generic NCAAF card now renders a compact SmartSim box when coverage/publication fields are present in the payload.

## Does NCAAF Reach MLB-Level Card Parity?

Not yet.

This change closes the visible coverage/publication gap on the generic NCAAF card, but it does not convert NCAAF into the MLB-specific rich card contract.

## Remaining UI Gaps

- NCAAF still uses the shared generic card renderer instead of the MLB-specific rich template.
- The NCAAF card does not yet have MLB-style live / final box parity.
- The NCAAF card does not yet have MLB-style sim box, props lens, or official-card section parity.
- The current metadata wiring is Week 1 board-aware, not a fully generalized NCAAF publication catalog for every historical week.

## Answer Summary

- Which SmartSim fields are now visible? `coverage_score`, `coverage_tier`, `publication_status`, and `publication_priority`.
- Does `/ncaaf` now have a SmartSim box? Yes.
- Does NCAAF achieve MLB-level card parity? No, not yet.
- What UI gaps remain? The MLB-specific rich card sections are still missing.