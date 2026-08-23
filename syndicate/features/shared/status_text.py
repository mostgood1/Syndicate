"""Whether a game's STATUS TEXT reads as live or as terminal — on word boundaries.

**THIS FILE EXISTS BECAUSE `"ft"` MATCHES `"hal[ft]ime"`.**

Measured on production 2026-08-23 during a live WNBA slate: a game AT HALFTIME
was displayed as **Final**. The chain, in four steps, entirely inside
`_normalized_game_status`:

1. ESPN publishes the status text `"Halftime"`.
2. The live check matched `"halftime"` -> `live = True`. Correct.
3. The terminal check matched `"ft"` **inside `"hal-ft-ime"`** -> `is_final = True`.
4. `if is_final: live = False`, so the label became `"Final"`.

Step 4 is not the bug and must not be reverted: it was added 2026-08-17 for a
REAL defect, a finished `"Final/OT"` game published as in-progress indefinitely,
which cost a live edge tier on a settled game. But it is what turned this
latent substring collision into a visible one. Before it, `live` stayed True
from step 2 and halftime rendered correctly **by luck** — two bugs cancelling.

**THE TOKEN LISTS WERE NEVER WRONG. THE MATCHING WAS.** `token in text` is a
substring test, so every short token is a landmine inside ordinary prose:

    "ft"  in "halftime"      -> True     (WNBA/NBA, terminal list)
    "ot"  in "shot"/"not"    -> True     (the trap `#160` recorded for soccer)
    "off" in "playoff"       -> True     (NHL, terminal list)
    "so"  in "season"        -> True     (NHL, live list)

Matching on `\\b` boundaries fixes all four at once and changes nothing else:
a token that stands alone still matches, including `"OT"` in `"Final/OT"`
(`/` is a non-word character, so the boundary holds and the 2026-08-17 fix
keeps working).

**WHY SHARED RATHER THAN FIXED IN PLACE.** The identical pair of functions was
copy-pasted into four files — `wnba/cards.py`, `nba/cards.py`, `nhl/cards.py`
and `blueprints/home.py`. Fixing only the file where the bug was REPORTED would
leave three known-broken copies.

NBA's pair is byte-identical to WNBA's, `"ft"` included, but it never received
the 2026-08-17 precedence line -- so `if live: is_final = False` still rescues
halftime there and NBA renders "Live" today. Its collision is MASKED, not
absent, and adding that precedence (which NBA wants, for the same `Final/OT`
reason) would activate it mid-season. `blueprints/home.py` is worse than
either: `_game_status_state` returns `"final"` and `get_active_games` keeps only
`{"scheduled", "live"}`, so a halftime game was DROPPED FROM THE HOME RAILS
rather than merely mislabelled.

The reference implementation was already in the repo:
`shared/game_board_contract.py:148` matches on `\b` boundaries, and the comment
above it was written about this exact class of defect for soccer (`#160`, `"ot"`
inside `"snapshot"`). That fix never reached these four copies.
"""

from __future__ import annotations

import re
from typing import Any, Iterable

# Basketball. `"halftime"` is live; the quarter tokens are the short forms ESPN
# uses in `shortDetail`.
BASKETBALL_LIVE_TOKENS = ("live", "in progress", "q1", "q2", "q3", "q4", "ot", "halftime")

# Hockey. `"intermission"` is the between-periods state, live rather than over.
HOCKEY_LIVE_TOKENS = ("live", "in progress", "1st", "2nd", "3rd", "ot", "so", "intermission")

# Terminal states. `"ft"` and `"full time"` are both kept: soccer feeds send
# either, and with boundary matching the short one is no longer a hazard.
TERMINAL_TOKENS = (
    "final", "finished", "complete", "full time", "ft",
    "postponed", "cancelled", "canceled", "suspended",
)

# Hockey's terminal list carries `"off"` where the others carry `"full time"`.
HOCKEY_TERMINAL_TOKENS = (
    "final", "finished", "complete", "off",
    "postponed", "cancelled", "canceled", "suspended",
)


def _joined(values: Iterable[Any]) -> str:
    return " ".join(
        str(value or "").strip().lower()
        for value in values
        if str(value or "").strip()
    )


def matches_any_token(text: str, tokens: Iterable[str]) -> bool:
    """True when any token appears in `text` as a WHOLE WORD.

    `re.escape` on each token because they are data, not patterns, and
    `"full time"`'s space must stay a literal.
    """
    if not text:
        return False
    for token in tokens:
        token = str(token or "").strip().lower()
        if not token:
            continue
        if re.search(rf"\b{re.escape(token)}\b", text):
            return True
    return False


def looks_live_status_text(*values: Any, tokens: Iterable[str] = BASKETBALL_LIVE_TOKENS) -> bool:
    return matches_any_token(_joined(values), tokens)


def looks_terminal_status_text(*values: Any, tokens: Iterable[str] = TERMINAL_TOKENS) -> bool:
    return matches_any_token(_joined(values), tokens)
