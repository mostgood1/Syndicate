"""Tests for NCAAF's date -> (week, card keys) resolver.

THE TEST THAT MATTERS MOST IS THE REACHABILITY ONE, and the reason is the
defect's history rather than its shape.

`ncaaf_week_and_card_keys_for_date` gates `_NCAAFDataProvider.games()`: when it
returns None, NCAAF contributes ZERO chips, and zero chips is
indistinguishable from "no games today". The previous implementation read
`cfbd_lines_{season}_wk{N}.json`, an artifact with **no producer on any service,
present in git at no SHA, and absent from `HOT_ARTIFACT_PATTERNS`** -- so it
returned None on every service on every date, while passing its tests, because
the tests wrote that file into a temp dir first.

A test that provides the input is a test of the parser, not of the pipeline.
`test_resolves_with_no_cfbd_lines_file_anywhere` is the one that would have
caught the real bug: it asserts the resolver works when that artifact does not
exist at all.

The second lesson pinned here is the Central-date one. Matching the schedule's
raw UTC `startDate` prefix returned 7 of Saturday 2026-08-29's 8 games,
dropping the 9pm Central kickoff (`2026-08-30T02:00Z`). On a football Saturday
the late window is the marquee one.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.ncaaf import sources as ncaaf_sources  # noqa: E402

MODULE = "syndicate.features.football.sim_engine.smartsim2.historical_truth.ncaaf_historical_loader.load_games_season"


def _game(week, away, home, start, *, fbs=True):
    return {
        "week": week,
        "awayTeam": away,
        "homeTeam": home,
        "startDate": start,
        "homeClassification": "fbs" if fbs else "fcs",
        "awayClassification": "fbs" if fbs else "fcs",
    }


# Saturday 2026-08-29 as the schedule actually carries it: seven daytime/evening
# games on the 08-29 UTC date, plus a 9pm Central kickoff stamped 08-30 UTC.
_SLATE = [
    _game(1, "North Carolina", "TCU", "2026-08-29T16:00:00.000Z"),
    _game(1, "San Jose State", "USC", "2026-08-29T19:00:00.000Z"),
    _game(1, "NC State", "Virginia", "2026-08-29T19:30:00.000Z"),
    _game(1, "Jacksonville State", "North Dakota State", "2026-08-29T21:30:00.000Z"),
    _game(1, "Sacramento State", "Eastern Michigan", "2026-08-29T22:30:00.000Z"),
    _game(1, "Hawai'i", "Stanford", "2026-08-29T23:00:00.000Z"),
    _game(1, "New Mexico State", "Florida State", "2026-08-29T23:00:00.000Z"),
    _game(1, "Memphis", "UNLV", "2026-08-30T02:00:00.000Z"),   # 9pm CT Saturday
    _game(2, "Somebody", "Someone Else", "2026-09-05T19:00:00.000Z"),
]


def test_resolves_with_no_cfbd_lines_file_anywhere(tmp_path):
    """THE REGRESSION TEST FOR THE ACTUAL DEFECT.

    The old implementation needed `cfbd_lines_{season}_wk{N}.json`. Point the
    NCAAF source root at an empty directory -- the production condition, where
    that file has never existed -- and the resolver must still answer.
    """
    with patch(MODULE, return_value=_SLATE), \
         patch.object(ncaaf_sources, "default_ncaaf_source_root", return_value=tmp_path):
        result = ncaaf_sources.ncaaf_week_and_card_keys_for_date(2026, "2026-08-29")

    assert result is not None, "resolver returned None with no cfbd_lines present"
    week, keys = result
    assert week == 1
    assert len(keys) == 8


def test_late_central_kickoff_is_not_lost_to_the_utc_date():
    """A 9pm Central Saturday game is 02:00Z Sunday. Prefix matching drops it."""
    with patch(MODULE, return_value=_SLATE):
        week, keys = ncaaf_sources.ncaaf_week_and_card_keys_for_date(2026, "2026-08-29")
    assert "1_Memphis_UNLV" in keys
    assert len(keys) == 8
    # And it must NOT also show up on the Sunday.
    with patch(MODULE, return_value=_SLATE):
        assert ncaaf_sources.ncaaf_week_and_card_keys_for_date(2026, "2026-08-30") is None


def test_keys_use_the_card_gamepk_formula():
    """`f"{week}_{away}_{home}"` with spaces underscored -- built in cards.py."""
    with patch(MODULE, return_value=_SLATE):
        _, keys = ncaaf_sources.ncaaf_week_and_card_keys_for_date(2026, "2026-08-29")
    assert "1_North_Carolina_TCU" in keys
    assert "1_NC_State_Virginia" in keys
    # away then home, never the reverse
    assert "1_TCU_North_Carolina" not in keys


def test_non_fbs_games_are_excluded():
    """The board only builds cards for FBS-vs-FBS, so a key it never built
    would filter every game out of the chip list."""
    slate = _SLATE + [_game(1, "Some FCS School", "Another FCS School",
                            "2026-08-29T18:00:00.000Z", fbs=False)]
    with patch(MODULE, return_value=slate):
        _, keys = ncaaf_sources.ncaaf_week_and_card_keys_for_date(2026, "2026-08-29")
    assert len(keys) == 8
    assert not any("FCS" in key for key in keys)


def test_week_with_the_most_games_on_the_date_wins():
    slate = [
        _game(1, "A", "B", "2026-09-05T19:00:00.000Z"),
        _game(2, "C", "D", "2026-09-05T19:00:00.000Z"),
        _game(2, "E", "F", "2026-09-05T23:00:00.000Z"),
    ]
    with patch(MODULE, return_value=slate):
        week, keys = ncaaf_sources.ncaaf_week_and_card_keys_for_date(2026, "2026-09-05")
    assert week == 2
    assert keys == {"2_C_D", "2_E_F"}


def test_absence_is_none_not_an_empty_set():
    """None means "no slate"; an empty set would filter every card away while
    claiming the date resolved."""
    with patch(MODULE, return_value=_SLATE):
        assert ncaaf_sources.ncaaf_week_and_card_keys_for_date(2026, "2026-12-25") is None


def test_unreadable_schedule_is_none_not_a_crash():
    with patch(MODULE, side_effect=OSError("no artifact")):
        assert ncaaf_sources.ncaaf_week_and_card_keys_for_date(2026, "2026-08-29") is None


def test_malformed_date_is_rejected():
    assert ncaaf_sources.ncaaf_week_and_card_keys_for_date(2026, "") is None
    assert ncaaf_sources.ncaaf_week_and_card_keys_for_date(2026, "not-a-date") is None


def test_the_resolver_has_no_executable_cfbd_lines_dependency():
    """GUARD: `cfbd_lines_*.json` must never gate NCAAF chips again.

    This replaces `tests/test_ncaaf_date_keying.py`, deleted in the same
    commit. Every one of that file's six tests exercised the cfbd_lines join --
    they wrote the artifact into a temp dir and mocked ESPN, so they passed
    continuously while the production code path they covered returned None on
    every service on every date. Their green was the strongest single reason
    the defect survived.

    One of them, `test_espn_unreachable_is_None`, even asserted the exact
    production behaviour (`None`) -- for entirely the wrong reason.

    Asserting on source text is a blunt instrument and is used deliberately:
    the failure mode is not a wrong value, it is a REINTRODUCED DEPENDENCY on
    an artifact that no service has. There is no return value that shows that.
    """
    source = (
        REPO_ROOT / "syndicate" / "features" / "ncaaf" / "sources.py"
    ).read_text(encoding="utf-8")
    body = source[source.index("def ncaaf_week_and_card_keys_for_date("):]
    body = body[: body.index("\n    return week, keys_by_week[week]")]
    # Strip the docstring, which discusses cfbd_lines at length on purpose.
    body = body[body.index('"""', body.index('"""') + 3) + 3:]
    assert "cfbd_lines" not in body
    assert "cfbd" not in body.lower()
