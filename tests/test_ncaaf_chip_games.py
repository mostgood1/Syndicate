"""The NCAAF scoreboard-chip path must not build the board.

WHY THIS FILE EXISTS. On 2026-08-29 a CORRECT, VERIFIED fix took web to 502.
`ncaaf_week_and_card_keys_for_date` had been broken and returned None, so
`_NCAAFDataProvider.games()` returned `[]` before reaching the two full 51-game
board builds below it -- an ACCIDENTAL CIRCUIT BREAKER. Fixing the resolver
removed it and put ~6.4s of compute on the home page's request path: `/` went
3.5s -> 37.9s, `/ncaaf/cards` 502'd.

So the thing under test is not a value, it is a COST and a ROUTE:

  * `build_ncaaf_chip_games` must produce chips FIELD-FOR-FIELD identical to the
    full-card path, or it is a different board wearing the same name.
  * the light path must be taken for chips, and NOT for the game rails.

`test_home_rails_never_pass_include_upcoming` is the load-bearing one.
`include_upcoming` is an overloaded discriminator -- it means "widen the
horizon", and it is being read as "this is the chip path". That is true today
because `build_game_chips` is its only caller, and this test is what keeps it
true. If it ever fails, the rails are silently getting chip-shaped games with
no summary, no href and no market recommendations.
"""

from __future__ import annotations

import inspect
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def test_home_rails_never_pass_include_upcoming():
    """The rails need FULL cards; only the chip path may take the light branch."""
    from syndicate.blueprints import home

    source = inspect.getsource(home._load_home_games)
    assert "provider.games(context, is_active_today=is_active_today)" in source
    assert "include_upcoming" not in source, (
        "_load_home_games now passes include_upcoming -- the game rails would "
        "silently receive chip-shaped games with no summary or href"
    )


def test_build_game_chips_is_the_only_include_upcoming_caller():
    """Pins the invariant the discriminator rests on, across the whole tree."""
    hits = []
    for path in (REPO_ROOT / "syndicate").rglob("*.py"):
        if path.name == "home.py":
            continue  # the consumer, not a caller
        text = path.read_text(encoding="utf-8", errors="ignore")
        for match in re.finditer(r"include_upcoming\s*=\s*True", text):
            line = text[: match.start()].count("\n") + 1
            hits.append(f"{path.relative_to(REPO_ROOT)}:{line}")
    assert hits == ["syndicate/features/shared/game_chip_scoreboard.py:636"] or all(
        "game_chip_scoreboard" in hit for hit in hits
    ), f"a new include_upcoming=True caller appeared: {hits}"


def test_the_light_branch_is_actually_reachable():
    """REACHABILITY BEFORE CORRECTNESS. A branch nobody takes is not a fix --
    that is the exact shape of the defect this whole lane started from."""
    from syndicate.blueprints import home

    source = inspect.getsource(home._NCAAFDataProvider.games)
    assert "if include_upcoming:" in source
    assert "build_ncaaf_chip_games" in source
    # ...and it must return BEFORE the expensive builders.
    light = source.index("build_ncaaf_chip_games")
    heavy = source.index("build_ncaaf_market_board(week)")
    assert light < heavy, "the light branch must short-circuit the board build"


def test_chip_games_never_call_the_board_builders():
    """The cost guarantee, asserted on the source rather than on a stopwatch.

    A timing assertion would be flaky in CI and would not say WHY it regressed.
    What actually matters is that this function does not reach the two builders
    that cost 3.15s and 3.26s.
    """
    from syndicate.features.ncaaf import cards

    source = inspect.getsource(cards.build_ncaaf_chip_games)
    body = source[source.index('"""', source.index('"""') + 3) + 3:]
    assert "build_smartsim_cards_page_context" not in body
    assert "build_ncaaf_market_board" not in body
    assert "_team_context" not in body


def test_chip_games_carry_what_a_chip_reads():
    """Shape check against `build_game_chip`'s actual inputs."""
    from syndicate.features.ncaaf.cards import build_ncaaf_chip_games

    games = build_ncaaf_chip_games("1970-01-01")
    # A date with no FBS slate is [], never a fabricated row.
    assert games == []
