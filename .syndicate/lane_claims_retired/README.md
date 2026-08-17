# Retired lane-claim markers

`.current-lane.<session-id>` files whose session **no longer exists**. Moved
here by the `ledger-sweep-2026-08-17` lane, **not deleted** — restore one by
moving it back up to `.syndicate/`.

## Why these and not others

Each was verified individually: `get_session` on the id returns *not found*.
Markers belonging to sessions that are merely ARCHIVED were deliberately left
in place, because an archived session can be resumed and would come back
holding its claim.

## What a stale marker actually does

`lane-guard.py` reads `.current-lane.<session-id>` to decide which lane the
editing session is in, falling back to the single-slot `.current-lane` when no
per-session file exists. A marker for a dead session is not dangerous on its
own — nothing reads it — but it is the ONLY machine-readable record of who
holds a lane, so a pile of them makes orphan detection a manual cross-check
against the session roster. That check took most of an hour on 2026-08-17 and
is the reason this directory exists.

## Retired 2026-08-17 (18)

| session id (short) | lane it still claimed |
|---|---|
| `2b63e226` | `layer2-board-quality` |
| `47b722b6` | `game-shape-capture` |
| `4c0eba75` | `soccer-live-game-state` |
| `59de9895` | `live-game-line-projection` |
| `5ede31a6` | `branch-overlap-manual-run-marker` |
| `834e46fb` | `quote-feed-threshold-per-sport` |
| `8769cea5` | `export-force-refresh-escape` |
| `ac41bbb1` | `clv-without-settlement` |
| `b288aa1c` | `refresh-worker-oom-recurrence` |
| `ba5733cb` | `grading-blocker-settled-zero` |
| `d55e5a54` | `ask-answer-substance` |
| `dbd61136` | `ask-sport-coverage` |
| `077e3d73`, `36b43f61`, `3de5bab6`, `5f71b4b2`, `6c60428a`, `810f0b63` | (empty — no claim) |

**Do not read this table as "these lanes are unowned."** It says these
SESSIONS are gone. Owner state per lane is in `state.md`, section
"LEDGER SWEEP 2026-08-17".
