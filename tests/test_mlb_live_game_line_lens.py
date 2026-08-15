"""The live Monte-Carlo game lens must survive the merge onto a card row.

Lane `live-game-line-projection`. Full evidence:
`.syndicate/spec_live_game_line_projection.md`.

What these pin, and why they are written this way:

`_enhance_card_row_with_live_projection` merges the vendored live-lens payload
(which carries `estimate_live`'s live win probability) onto the card-backed row.
Before 2026-08-15 its `should_use_projection_lens` was False on *every live
game* -- the exact population it exists for -- because the card's own lens is
manufactured by `_parse_number_text`-ing display strings and therefore always
satisfies `_lens_rows_have_projection_signal`. Measured against the served
production payload: False on 5 of 5 live games.

The fixtures below are deliberately shaped like the real thing rather than
minimally: the card lens carries `first1/first3/first5` lanes with parseable
`total`/`homeMargin` and no `source` (what `_live_lens_segments_from_card`
emits), and the projection lens carries `live`/`full` lanes stamped
`source: live_mc` plus segment lanes stamped `segment_projection` (what
`_build_game_lens` emits). A fixture that omitted the card's numbers would pass
against the OLD code too and would pin nothing.
"""

from __future__ import annotations

import pytest

from syndicate.features.mlb.live_lens import _enhance_card_row_with_live_projection
from syndicate.features.mlb.live_lens import _lens_rows_have_live_state_signal
from syndicate.features.mlb.live_lens import _lens_rows_have_projection_signal


def _card_lens() -> list[dict]:
    """What `_live_lens_segments_from_card` produces: numbers, no source."""
    return [
        {"key": "first1", "label": "F1", "projection": {"total": 1.31, "homeMargin": 0.57}},
        {"key": "first3", "label": "F3", "projection": {"total": 3.90, "homeMargin": 0.44}},
        {"key": "first5", "label": "F5", "projection": {"total": 5.02, "homeMargin": 0.31}},
    ]


def _mc_lens() -> list[dict]:
    """What `_build_game_lens` produces when `estimate_live` returned."""
    return [
        {
            "key": "live",
            "label": "Top 7",
            "source": "live_mc",
            "modelHomeWinProb": 0.6842,
            "projection": {"away": 3.4, "home": 4.1, "total": 7.5, "homeMargin": 0.7},
        },
        {
            "key": "full",
            "label": "Full Game",
            "source": "live_mc",
            "modelHomeWinProb": 0.6842,
            "projection": {"away": 3.4, "home": 4.1, "total": 7.5, "homeMargin": 0.7},
        },
        {
            "key": "first5",
            "label": "F5",
            "source": "segment_projection",
            "modelHomeWinProb": 0.51,
            "projection": {"total": 5.0, "homeMargin": 0.1},
        },
    ]


def _bailed_lens() -> list[dict]:
    """What `_build_game_lens` produces when the re-sim bailed: no `live_mc`."""
    return [
        {
            "key": "first5",
            "label": "F5",
            "source": "segment_projection",
            "modelHomeWinProb": 0.51,
            "projection": {"total": 5.0, "homeMargin": 0.1},
        },
    ]


def _card_row(status_abstract: str, status_detailed: str) -> dict:
    return {
        "gamePk": 824159,
        "status": {"abstract": status_abstract, "detailed": status_detailed},
        # Non-empty so the merge's prop branch is not the thing under test.
        "liveProps": [{"player": "somebody"}],
        "gameLens": _card_lens(),
    }


def _projection_row(status_abstract: str, status_detailed: str, lens: list[dict]) -> dict:
    return {
        "gamePk": 824159,
        "status": {"abstract": status_abstract, "detailed": status_detailed},
        "gameLens": lens,
    }


def test_the_fixture_reproduces_the_condition_that_caused_the_bug():
    """Guard the guard: if this stops holding, the tests below pin nothing.

    The whole defect rests on the card's text-derived lens counting as
    "projection signal" while carrying no live-state signal. A future change to
    `_live_lens_segments_from_card` could make that false and quietly turn every
    assertion below into a tautology.
    """
    assert _lens_rows_have_projection_signal(_card_lens()) is True
    assert _lens_rows_have_live_state_signal(_card_lens()) is False


def test_live_game_keeps_the_monte_carlo_lens():
    """THE REGRESSION. Delete the `projection_lens_is_live_state` disjunct and
    only this test and its `final` sibling go red."""
    merged = _enhance_card_row_with_live_projection(
        _card_row("Live", "In Progress"),
        _projection_row("Live", "In Progress", _mc_lens()),
    )

    lens = merged["gameLens"]
    assert _lens_rows_have_live_state_signal(lens) is True
    assert [row["key"] for row in lens] == ["live", "full", "first5"]
    live_lane = next(row for row in lens if row["key"] == "live")
    assert live_lane["modelHomeWinProb"] == pytest.approx(0.6842)
    assert live_lane["source"] == "live_mc"


def test_final_game_keeps_the_monte_carlo_lens():
    """`card_is_live_or_final` covers final too, so final had the same defect."""
    merged = _enhance_card_row_with_live_projection(
        _card_row("Final", "Game Over"),
        _projection_row("Final", "Game Over", _mc_lens()),
    )
    assert _lens_rows_have_live_state_signal(merged["gameLens"]) is True


def test_live_game_keeps_the_card_lens_when_the_resim_bailed():
    """The fix must not clobber the card lens with a segment interpolation.

    `_live_mc_projection` has seven instrumented bail exits. When it takes one,
    `_build_game_lens` still returns lanes -- just `segment_projection` ones.
    Preferring those over the card's would be a silent downgrade, and it is the
    failure mode a naive `modelHomeWinProb is not None` discriminator would have
    shipped, since the bailed lens carries one.
    """
    merged = _enhance_card_row_with_live_projection(
        _card_row("Live", "In Progress"),
        _projection_row("Live", "In Progress", _bailed_lens()),
    )
    assert merged["gameLens"] == _card_lens()


def test_pregame_row_is_unchanged_by_the_new_clause():
    """Pregame already took `not card_is_live_or_final`; the change is additive.

    Pinned because "additive" is a claim about the boolean, and the whole point
    of the fix is that a disjunct nobody re-derived was doing the opposite of
    what its comment said.
    """
    projection_lens = [
        {"key": "full", "label": "Full Game", "source": "segment_projection",
         "projection": {"total": 8.5, "homeMargin": 0.2}},
    ]
    merged = _enhance_card_row_with_live_projection(
        _card_row("Preview", "Scheduled"),
        _projection_row("Preview", "Scheduled", projection_lens),
    )
    assert merged["gameLens"] == projection_lens


def test_empty_projection_lens_never_replaces_a_card_lens():
    """`_build_game_lens` returns [] for a final game with no snapshot."""
    merged = _enhance_card_row_with_live_projection(
        _card_row("Live", "In Progress"),
        _projection_row("Live", "In Progress", []),
    )
    assert merged["gameLens"] == _card_lens()


class TestLiveStateSignalDiscriminator:
    """`source == "live_mc"` is load-bearing; `modelHomeWinProb` is not enough."""

    def test_segment_lane_with_a_probability_is_not_live_state(self):
        rows = [{"key": "first3", "source": "segment_projection", "modelHomeWinProb": 0.55}]
        assert _lens_rows_have_projection_signal(rows) is True
        assert _lens_rows_have_live_state_signal(rows) is False

    def test_source_match_is_case_and_whitespace_insensitive(self):
        assert _lens_rows_have_live_state_signal([{"source": " Live_MC "}]) is True

    @pytest.mark.parametrize("rows", [None, "live_mc", [], [None], [{}], [{"source": None}]])
    def test_malformed_input_is_false_not_an_exception(self, rows):
        assert _lens_rows_have_live_state_signal(rows) is False
