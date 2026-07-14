# NCAAF Card Experience Design

## Goal

Create a dedicated NCAAF card surface that exposes the completed SmartSim pipeline directly to users without changing football models.

## Current Shape

The NCAAF board now emits a dedicated `ncaaf_main` card contract from `syndicate/features/ncaaf/cards.py`. The shared dispatcher routes that variant to `syndicate/templates/shared/_game_card_ncaaf.html`, while all other rows still fall back to the generic shared renderer.

## Dedicated Contract

The dedicated payload is centered on `game.ncaaf_card` and carries:

- SmartSim summary state: coverage score, coverage tier, publication status, publication priority, and publication-ready flag
- Tier badges: A, B, C, and D with an active-state marker
- Team context for both sides: returning production, coach continuity, transfer activity, and roster size
- Existing model output: the current game metrics and recommendation summary remain visible

## Visible Card Sections

The dedicated template surfaces three primary sections:

1. Game summary strip with matchup identity, slate status, and publication-ready label
2. SmartSim summary panel with coverage tier, publication state, and tier badges
3. Team context panels for both teams, plus a details section for the existing recommendation metrics

## Fallback Strategy

If the dedicated contract is missing, the shared template still falls back to `_game_card_generic.html`. That preserves safety for future rows or partial payloads while keeping the NCAAF-specialized path explicit when the contract is present.

## Design Intent

The experience is intentionally narrower than MLB's rich card template, but it now does three important things the generic card could not do well:

- Makes SmartSim publication state visible at a glance
- Presents team-level roster and continuity context directly on the card
- Separates publication readiness from the underlying model output so users can see why a card is surfaced or suppressed

## Implementation Notes

- No football model math changed.
- The new card reads published NCAAF artifact snapshots for team registry, returning production, coach continuity, transfer portal, and roster context.
- The UI contract is additive and backward-safe because generic fallback remains intact.

## Next Steps

Future work can extend the dedicated card with richer comparison tables, improved visual hierarchy, and more explicit board annotations, but the current contract already makes the SmartSim pipeline visible without changing the prediction engine.