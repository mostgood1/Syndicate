# In-Season Full Completion Checklist - 2026-05-19

This checklist turns the in-season lane into execution work by sport. "Full completion" here means all three layers are closed for the active season workflow: frontend parity, artifact maturity, and sim or analytics ownership.

## MLB

1. Expand local mirror breadth beyond current-date files into the broader daily, live, eval, and recap families.
2. Ensure live-lens support is local-first for report, registry, observation log, recap, raw feed, and OddsAPI snapshot artifacts.
3. Verify season betting-card and evaluation surfaces can launch from mirrored season manifest plus day payload and recap families.
4. Add migration-gate coverage for missing MLB mirror artifacts that should now be considered required.
5. Keep the reference UI stable while extracting only abstractions already proven in NBA, WNBA, or NHL.

## NBA

1. Mirror the live-lens artifact family needed for audit and accuracy surfaces, including projections, signals, recon, boxscores, and tuning artifacts.
2. Replace thin source-route proxies with local-first payload builders, starting with live player-prop audit and then the remaining live accuracy families.
3. Keep the season betting-card, archive, recap, and live-lens routes on one canonical date and profile contract.
4. Add regression coverage that proves the live analytics family can render from local mirrors without a sibling source app.
5. Document the minimum NBA artifact set required for daily cards, live lens, recap, and season-family operation.

## WNBA

1. Mirror the live analytics artifact family rather than relying on source API proxy routes for game and prop audit behavior.
2. Close remaining home and live-shell parity gaps using the same compact-card and live-rail grammar proven in MLB and NBA.
3. Normalize source-backed helper routes into explicit local-first artifact readers where the source app already persists usable files.
4. Add artifact-presence checks for cards, live lens, source cards shell support, and prop audit families.
5. Keep stored-date archive and live entry lanes honest when artifacts are absent.

## NHL

1. Document and mirror the sim and evaluation artifact families required for full cards, props, archive, and live-lens operation.
2. Preserve the current strong live contract while moving any remaining source-owned dependencies into mirrored processed artifacts where possible.
3. Ensure scoreboard, live guidance, and props surfaces all have local-first behavior for stored dates.
4. Add migration-gate checks for the minimum NHL artifact set.
5. Keep NHL aligned to the shared board and archive contracts without flattening the sport-specific live monitor behavior.

## Shared In-Season Work

1. Define a cross-sport artifact manifest schema that records raw inputs, processed outputs, live-support artifacts, sim outputs, evaluation bundles, and fallback state.
2. Add an ownership score to the module tracker so surface parity and source independence are tracked separately.
3. Add gates that fail when a supposedly mirror-backed in-season surface still falls back to a sibling source app.
4. Keep home rails aligned to the true per-sport live contracts instead of regressing into lossy generic summary boards.
5. Use MLB as the reference contract, but do not mark any in-season sport complete until the lower-layer dependencies are also local-first.