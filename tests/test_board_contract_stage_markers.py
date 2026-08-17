"""The shared board builder must mark its RETURN, for every sport.

Why this file exists, rather than an assertion tacked onto an existing board
test: the marker it guards is not a feature, it is the only thing that will
distinguish two hypotheses on the next refresh-worker `oomKilled`.

Measured on refresh-worker 2026-08-16, the clean 23:16:51Z kill: the watchdog's
`last_stage` sat at `board_contract_games_normalized` while anon climbed
1746 -> 3935MB over ~41s, and the excursion did not start until ~13s AFTER that
marker. Without a marker at the return there is nothing to separate "still
inside the tail of apply_game_board_contract" from "returned, and the allocator
is in the caller" -- and the tail is scalar `setdefault` work that cannot hold
2.2GB, so the label was actively misleading about where to look.

The MLB-only point is the load-bearing one. `_log_cards_context_memory`
(`syndicate/features/mlb/cards.py:182`) exists for MLB and nowhere else, so the
other seven sports hydrate with no stage markers at all. `apply_game_board_contract`
is the one function all eight already converge on, which is why the marker lives
there -- and why the test below runs a NON-MLB sport. A regression that quietly
scoped this to MLB would restore exactly the blind spot it was added to remove,
and an MLB-only test would pass while it happened.
"""

from __future__ import annotations

import io
import json
import contextlib

from syndicate.features.shared import memory_observability as mo
from syndicate.features.shared.game_board_contract import apply_game_board_contract


def _stages_for(sport: str) -> list[str]:
    """Stage labels emitted by one board build, in order."""
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        apply_game_board_contract(
            {"date": "2026-08-16", "games": [{"game_pk": 1}, {"game_pk": 2}]},
            sport=sport,
            module="cards",
        )
    stages: list[str] = []
    for line in err.getvalue().splitlines():
        if "CONTAINER_MEMORY" not in line:
            continue
        try:
            stages.append(json.loads(line[line.find("{") :]).get("stage"))
        except Exception:
            continue
    return [s for s in stages if isinstance(s, str) and s.startswith("board_contract_")]


def test_return_is_marked_and_is_the_last_stage():
    stages = _stages_for("nhl")
    assert "board_contract_end" in stages, (
        "the return of apply_game_board_contract is unmarked; a kill in the "
        "caller will be attributed to board_contract_games_normalized again"
    )
    assert stages[-1] == "board_contract_end", (
        f"board_contract_end must be the LAST stage on the path, got {stages}"
    )
    assert stages.index("board_contract_games_normalized") < stages.index("board_contract_end")


def test_marker_is_not_mlb_only():
    """The blind spot this closes is the seven sports MLB's instruments miss."""
    for sport in ("nhl", "nba", "soccer", "wnba", "nfl", "ncaab", "ncaaf"):
        assert "board_contract_end" in _stages_for(sport), (
            f"{sport} board builds return unmarked -- this is the MLB-only "
            "instrumentation gap the marker exists to close"
        )


def test_marker_updates_watchdog_last_stage():
    """Emitting the line is not enough; the watchdog must be able to attribute to it.

    `log_container_memory` feeds `_note_stage_seen` (memory_observability.py:694).
    If that wiring is ever broken the log line would still appear and the
    MEMORY_WATCHDOG lines -- the ones that actually name the stage during an
    excursion -- would go on reporting the previous stage, which is the failure
    this whole marker exists to prevent. A test that only grepped stderr would
    pass through that regression.
    """
    _stages_for("soccer")
    assert mo._WATCHDOG_STATE.get("last_stage") == "board_contract_end"
    assert mo._WATCHDOG_STATE.get("last_stage_at") is not None
