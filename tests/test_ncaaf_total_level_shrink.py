"""NCAAF total-level shrink: the level shrinks, every difference survives, and
`1` is an exact kill switch (the NFL `[nfl-total-level-gain]` contract)."""
from __future__ import annotations

import pytest

import scripts.generate_smartsim2_ncaaf_projections as gen


def test_shrink_scales_the_common_level_and_keeps_every_difference():
    h_off, h_def, a_off, a_def = 0.30, -0.10, 0.10, 0.20
    s_h_off, s_h_def, s_a_off, s_a_def = gen.shrink_rating_level(h_off, h_def, a_off, a_def, 0.3)
    assert s_h_off - s_a_off == pytest.approx(h_off - a_off)
    assert s_h_def - s_a_def == pytest.approx(h_def - a_def)
    assert (s_h_off + s_a_off) / 2 == pytest.approx(0.3 * (h_off + a_off) / 2)
    assert (s_h_def + s_a_def) / 2 == pytest.approx(0.3 * (h_def + a_def) / 2)


def test_one_returns_the_inputs_untouched():
    args = (0.31, -0.12, 0.07, 0.22)
    assert gen.shrink_rating_level(*args, 1.0) == args


@pytest.mark.parametrize("raw, expected", [
    (None, None),          # absent -> the module constant
    ("1", 1.0),            # kill switch
    ("0.5", 0.5),
    ("nope", None),        # unparseable -> the constant, never "off"
    ("-2", 0.0),           # clamped
])
def test_env_override(monkeypatch, raw, expected):
    if raw is None:
        monkeypatch.delenv("SYNDICATE_NCAAF_TOTAL_LEVEL_SHRINK", raising=False)
    else:
        monkeypatch.setenv("SYNDICATE_NCAAF_TOTAL_LEVEL_SHRINK", raw)
    want = gen.NCAAF_TOTAL_LEVEL_SHRINK if expected is None else expected
    assert gen._total_level_shrink() == want


def _project(monkeypatch, shrink: str):
    monkeypatch.setenv("SYNDICATE_NCAAF_TOTAL_LEVEL_SHRINK", shrink)
    monkeypatch.delenv("SYNDICATE_NCAAF_DRIVE_PRIORS", raising=False)
    index = {"alpha": (38.0, 14.0), "beta": (34.0, 18.0), "gamma": (22.0, 30.0)}
    return gen.build_projection(
        season=2025, week=6, home_team="Alpha", away_team="Beta", game_id="1", ppa_index={},
        rating_source="t", seeds=6, sp_index=index, sp_means=gen.sp_league_means(index),
    )


def test_reachability_off_differs_from_on_and_one_is_unstamped(monkeypatch):
    off = _project(monkeypatch, "1")
    on = _project(monkeypatch, "0.3")
    # two high-level teams: shrinking the level must move the total
    assert on.total_mean != off.total_mean
    assert off.rating_source == "t"
    assert on.rating_source == "t+level_shrink_0.3"


def test_kill_switch_is_exact(monkeypatch):
    a = _project(monkeypatch, "1")
    b = _project(monkeypatch, "1.0")
    assert (a.margin_mean, a.total_mean, a.home_win_rate) == (b.margin_mean, b.total_mean, b.home_win_rate)
