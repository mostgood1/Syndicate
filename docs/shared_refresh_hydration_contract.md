# Shared Refresh And Hydration Contract

This document is the canonical browser refresh and hydration contract for Syndicate's cards, live-lens, and rank-board surfaces. The goal is one consistent model for how the UI refreshes odds, lines, live box scores, scores, and prop state across sports without forcing a reload or jumping the user away from the current view.

## Contract goal

The UI should hydrate from a shared refresh policy, not from sport-specific timers.

The contract is designed to:

- keep MLB, NBA, and WNBA cards on the same browser refresh behavior
- preserve the current date, filters, and page position while data refreshes
- let the server describe refresh behavior once and let the browser start from that description
- make room for the same policy shape on live-lens and rank-board surfaces

## Policy shape

The shared refresh policy is exposed from the server as a `refresh_policy` object and passed through the browser bootstrap as `refreshPolicy`.

Current policy fields:

- `enabled`: whether polling should run
- `intervalMs`: polling cadence in milliseconds, typically `30000`
- `refreshOnVisible`: refresh when the tab is visible
- `refreshOnFocus`: refresh when the tab regains focus
- `stopOnPageHide`: stop the loop when the page is hidden
- `preventOverlap`: skip a tick if a prior refresh is still in flight
- `skipWhenHidden`: avoid background refresh when the tab is hidden
- `poller`: identifies the shared client helper, currently `shared.polling`

If a page does not provide a policy, the client helper falls back to the default cadence and conservative browser refresh behavior.

## Server-side contract

Server builders are responsible for emitting the policy once in the payload they already own.

Cards pages currently emit the policy from:

- [syndicate/features/mlb/cards.py](../syndicate/features/mlb/cards.py)
- [syndicate/features/nba/cards.py](../syndicate/features/nba/cards.py)
- [syndicate/features/wnba/cards.py](../syndicate/features/wnba/cards.py)

Shared payload builders already understand the same shape when it is present:

- [syndicate/features/shared/game_board_contract.py](../syndicate/features/shared/game_board_contract.py)
- [syndicate/features/shared/live_lens_contract.py](../syndicate/features/shared/live_lens_contract.py)
- [syndicate/features/shared/rank_board.py](../syndicate/features/shared/rank_board.py)

The contract principle is simple: the feature layer decides what refresh behavior is appropriate, and the browser consumes that policy without re-deriving it from route-specific logic.

## Browser-side contract

The browser bootstrap passes the policy to the shared polling helper and lets the helper manage the refresh loop.

Shared polling entrypoints live in:

- [syndicate/static/shared/polling.js](../syndicate/static/shared/polling.js)

The helper normalizes the policy, resolves a fallback when needed, and starts the loop through `startFromPolicy(...)`.

Current consumer scripts:

- [syndicate/static/mlb/cards_source.js](../syndicate/static/mlb/cards_source.js)
- [syndicate/static/mlb/live_lens.js](../syndicate/static/mlb/live_lens.js)
- [syndicate/static/nba/cards_source.js](../syndicate/static/nba/cards_source.js)
- [syndicate/static/wnba/cards-parity.js](../syndicate/static/wnba/cards-parity.js)

Templates expose the bootstrap object that carries the policy into the browser:

- [syndicate/templates/mlb/cards.html](../syndicate/templates/mlb/cards.html)
- [syndicate/templates/mlb/cards_embed.html](../syndicate/templates/mlb/cards_embed.html)
- [syndicate/templates/nba/cards_source.html](../syndicate/templates/nba/cards_source.html)
- [syndicate/templates/wnba/cards_source.html](../syndicate/templates/wnba/cards_source.html)

## Behavior rules

The shared contract follows these rules:

1. Refresh should update the live data in place.
2. Refresh should not reset the selected slate date unless the route explicitly changes it.
3. Refresh should not jump the user away from the current game card or tab state.
4. Refresh should preserve the browser view while live data, odds, or box scores hydrate in the background.
5. Hidden or backgrounded tabs should not hammer the backend unless the policy explicitly allows it.

That means the UI can refresh odds, lines, live box score rows, live scores, and props while still behaving like the same page the user was already reading.

## Sports covered today

The shared policy contract is now in place for:

- MLB cards
- NBA cards
- WNBA cards

The shared payload schema also supports live-lens and rank-board consumers, but those surfaces still need to be wired deliberately wherever they should adopt the same browser behavior.

## Verification checklist

When validating the contract, confirm the following:

1. The server payload includes `refresh_policy` or `refreshPolicy`.
2. The browser starts via `shared.polling` rather than an ad hoc timer.
3. The page refreshes without a full reload or navigation jump.
4. The selected slate date remains stable during refresh.
5. Scores, odds, live box data, and props hydrate from the latest payload.
6. The visible page remains usable while refresh is active.

## Related docs

- [Daily Update Control Plane](daily_update_control_plane.md)
- [NBA and WNBA source fallback runbook](nba_wnba_source_fallback_runbook.md)
- [Render Data Authority](render_data_authority.md)
- [Fix Notes Log](fix_notes_log.md)
