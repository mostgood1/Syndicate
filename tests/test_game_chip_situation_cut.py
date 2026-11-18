"""The live chip's situation line is never cut mid-word (lane `chip-situation-cut`, user 2026-11-18).

`build_game_chip` capped the line with a plain slice at `_SITUATION_MAX_CHARS` (40), in every sport, in two places:
`_chip_live_detail` (the sport's own line) and `_live_situation` (the cleaned status text). ESPN's 41-character
goal-to-go line "BAL ball · 1st & Goal at LAC 2 · red zone" (MNF 2026-11-16) was served ending "red zon".
`_fit_situation` keeps whole " · " parts instead; a line within the cap is untouched.
"""

from __future__ import annotations

import random

from syndicate.features.shared import game_chip_scoreboard as chips
from syndicate.features.shared.game_chip_scoreboard import _SITUATION_MAX_CHARS, _fit_situation, _live_situation

GOAL_TO_GO = "BAL ball · 1st & Goal at LAC 2 · red zone"


def _old_cut(text):
    return text[:_SITUATION_MAX_CHARS] if text else None


def test_the_goal_to_go_line_keeps_whole_parts_where_the_slice_cut_a_word():
    assert len(GOAL_TO_GO) == 41
    assert _old_cut(GOAL_TO_GO) == "BAL ball · 1st & Goal at LAC 2 · red zon"
    assert _fit_situation(GOAL_TO_GO) == "BAL ball · 1st & Goal at LAC 2"
    assert _fit_situation(GOAL_TO_GO) != _old_cut(GOAL_TO_GO)


def test_a_line_within_the_cap_is_unchanged():
    for text in ("LAC ball · 4th & 4 at BAL 20 · red zone",   # 39
                 "UCSD on a 9–2 run · WASH in bonus",
                 "2 outs · Bases loaded · Yamamoto 102p",
                 "SOG 21–18",
                 "x" * _SITUATION_MAX_CHARS):
        assert _fit_situation(text) == text == _old_cut(text)


def test_empty_is_none_as_before():
    assert _fit_situation(None) is None
    assert _fit_situation("") is None


def test_a_lone_part_too_long_ends_at_a_whole_word_with_an_ellipsis():
    text = "Weather delay with lightning in the area near the stadium"
    got = _fit_situation(text)
    assert len(got) <= _SITUATION_MAX_CHARS
    assert got.endswith("…")
    stem = got[:-1]
    assert text.startswith(stem) and text[len(stem)] == " ", got


def test_a_lone_part_with_no_space_is_cut_hard_with_an_ellipsis():
    got = _fit_situation("y" * 60)
    assert got == "y" * (_SITUATION_MAX_CHARS - 1) + "…"


def test_every_fit_is_within_the_cap_and_ends_on_a_part_or_a_word():
    rng = random.Random(20261118)
    words = ["ball", "1st", "&", "Goal", "at", "LAC", "2", "red", "zone", "Bases", "loaded", "run", "bonus", "9–2"]
    for _ in range(2000):
        parts = [" ".join(rng.choice(words) for _ in range(rng.randint(1, 7))) for _ in range(rng.randint(1, 5))]
        text = " · ".join(parts)
        got = _fit_situation(text)
        assert got and len(got) <= _SITUATION_MAX_CHARS, (text, got)
        if len(text) <= _SITUATION_MAX_CHARS:
            assert got == text
        elif got.endswith("…"):
            assert len(parts[0]) > _SITUATION_MAX_CHARS, (text, got)
        else:
            assert text.startswith(got) and text[len(got):].startswith(" · "), (text, got)


def test_the_status_text_path_fits_the_same_way():
    game = {"live_state": {"status": "Bases loaded · 2 outs · J. Rodriguez pitching · 98 pitches"}}
    assert _live_situation(game, None) == "Bases loaded · 2 outs"


def test_the_sport_line_path_fits_the_same_way(monkeypatch):
    from syndicate.features.shared import game_chip_detail

    monkeypatch.setattr(game_chip_detail, "live_detail", lambda *a, **k: GOAL_TO_GO)
    assert chips._chip_live_detail("nfl", {"home": {}, "away": {}}) == "BAL ball · 1st & Goal at LAC 2"
