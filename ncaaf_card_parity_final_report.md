# NCAAF Card Parity Final Report

## Questions Answered

### Is `/ncaaf` still relying on the generic card renderer?

No for the dedicated NCAAF rows now. The shared dispatcher routes `card_variant == 'ncaaf_main'` to a dedicated NCAAF template. The generic renderer still exists as fallback for non-NCAAF rows or missing contracts.

### What SmartSim information was visible before this change?

Before the dedicated card, the NCAAF surface only exposed a compact SmartSim box on the generic card. The visible fields were:

- coverage score
- coverage tier
- publication status
- publication priority

### What does the dedicated NCAAF component expose?

The dedicated contract now exposes:

- SmartSim summary state with a publication-ready flag
- Tier A/B/C/D badges
- Team context for both home and away teams
- Returning production, coach continuity, transfer activity, and roster size
- Existing recommendation metrics so the card still shows the core model output

### What MLB-level gaps still remain?

NCAAF still does not fully match the MLB card experience. The remaining gaps are:

- no MLB-style live/final box parity
- no MLB-style props lens
- no MLB-style official-card section parity
- no MLB-style breadth of panels or live-status richness

## What Changed

- `syndicate/features/ncaaf/cards.py` now builds a dedicated `ncaaf_card` contract from published NCAAF artifact snapshots.
- `syndicate/templates/shared/_game_card.html` now dispatches `ncaaf_main` rows to a specialized renderer.
- `syndicate/templates/shared/_game_card_ncaaf.html` presents SmartSim summary, tier badges, publication-ready state, and team context.
- `tests/test_ncaaf_cards_local.py` now asserts the specialized card variant and contract shape.

## Validation

Focused regression coverage passed for both the publishable and suppressed Week 1 examples:

- `test_week1_publishable_game_exposes_smartsim_metadata`
- `test_week1_suppressed_game_exposes_smartsim_metadata`

That confirms the specialized NCAAF card path is wired correctly and still preserves the generic fallback contract.

## Bottom Line

The board now has a dedicated NCAAF experience instead of relying only on the generic shared card. It surfaces SmartSim status, team context, and publication readiness directly on the card, but it still stops short of full MLB parity in live and props presentation.