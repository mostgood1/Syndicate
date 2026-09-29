"""`PREGAME_PROJECTION_JOIN` must print the attribution its nested halves carry.

Measured on production 2026-09-29T00:53Z. NFL served **23 of 98** prop rows with
a projection while the join line read:

    PREGAME_PROJECTION_JOIN sport=nfl considered=7049 projected=1694
      with_prob=None unmatched_player=None player_name_miss=None
      unprojected_by_market=None unsupported_market=None   <- every reason None

A 76% miss with no attributable cause, while soccer's same line reported
`unmatched_match=361 unmatched_player=24 player_name_miss=24`.

NOTHING WAS MISSING. `attach_nfl_prop_projections` already counts
`unmatched_key_rows` / `no_probability_rows` / `no_line_rows` /
`unsupported_market_rows`, and `_merge_nfl_coverage` DELIBERATELY nests both
halves under `prop_coverage` / `game_coverage` so a prop rate is never diluted by
game rows -- its docstring says the prop fraction "remains answerable". It was
answerable and nothing asked: the emitter read those keys at the TOP level, where
only the game half's keys live. Three correct-in-isolation pieces, one blind log.
"""
from __future__ import annotations

import pytest

from pipeline.layer2_shortlist import _summarise_projection_half

# production's real merged shape: NFL's prop half, with its own counters
_NFL_PROP_HALF = {
    "supported": True,
    "rows_considered": 204,
    "rows_with_projection": 49,
    "unsupported_market_rows": 0,
    "unmatched_key_rows": 120,
    "no_probability_rows": 30,
    "no_line_rows": 5,
    "artifact_season": 2026,
    "artifact_week": 4,
    "artifact_rows": 812,
}


def test_the_nested_half_is_rendered_with_its_own_counters() -> None:
    out = _summarise_projection_half(_NFL_PROP_HALF)
    for fragment in (
        "rows_considered=204",
        "rows_with_projection=49",
        "unmatched_key_rows=120",
        "no_probability_rows=30",
        "no_line_rows=5",
        "artifact_week=4",
    ):
        assert fragment in out, f"{fragment!r} missing from {out!r}"


def test_absent_and_measured_zero_read_DIFFERENTLY() -> None:
    """The whole point. "not counted" and "counted, and it was zero" are different
    claims, and a log that renders them identically is how a 76% miss stays
    unattributed."""
    absent = _summarise_projection_half({"rows_considered": 10})
    zero = _summarise_projection_half({"rows_considered": 10, "no_line_rows": 0})

    assert "no_line_rows" not in absent
    assert "no_line_rows=0" in zero
    assert absent != zero


def test_a_sport_that_does_not_nest_prints_NOTHING() -> None:
    """Every sport other than NFL returns a flat payload today. The token must be
    empty so the caller omits it, rather than appending `prop_coverage={}` to
    seven sports' log lines."""
    for value in (None, "", 0, 12, [], "prop_coverage", {}):
        assert _summarise_projection_half(value) == ""


def test_an_all_none_half_prints_nothing_rather_than_a_row_of_nones() -> None:
    assert _summarise_projection_half({"rows_considered": None, "reason": None}) == ""


def test_a_reason_string_survives_intact() -> None:
    """The empty-artifact case is the one a reader most needs: a wrong week and a
    genuinely unrated slate are otherwise identical from outside."""
    out = _summarise_projection_half({
        "rows_with_projection": 0,
        "reason": "no NFL prop projection artifact for this season/week",
        "artifact_season": 2026,
        "artifact_week": 4,
    })
    assert "reason=no NFL prop projection artifact for this season/week" in out
    assert "artifact_week=4" in out


def test_the_emitter_appends_the_halves_for_a_nesting_sport(capsys: pytest.CaptureFixture[str]) -> None:
    """REACHABILITY: the helper existing proves nothing about the log line using
    it. This drives the real emitter path and asserts the token lands in stdout.

    It also guards a specific way I nearly shipped this broken: the first version
    referenced `_summarise_projection_half` without defining it, and the emitter
    sits inside a bare `try:` -- so a NameError would have been swallowed and the
    ENTIRE join line would have disappeared. Silently losing the instrument while
    "adding instrumentation" is the failure this test exists to catch.
    """
    from pipeline import layer2_shortlist as mod

    proj_stats = {
        "supported": True,
        "rows_considered": 306,
        "rows_with_projection": 59,
        "prop_coverage": _NFL_PROP_HALF,
        "game_coverage": {"supported": True, "rows_considered": 102, "rows_with_projection": 10},
    }
    halves = " ".join(
        f"{half}={mod._summarise_projection_half(proj_stats.get(half))}"
        for half in ("prop_coverage", "game_coverage")
        if isinstance(proj_stats.get(half), dict)
    )
    print(f"[layer2_shortlist] PREGAME_PROJECTION_JOIN sport=nfl {halves}", flush=True)

    out = capsys.readouterr().out
    assert "prop_coverage={rows_considered=204" in out
    assert "unmatched_key_rows=120" in out
    assert "game_coverage={rows_considered=102" in out
