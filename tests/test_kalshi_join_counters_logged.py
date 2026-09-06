"""The counters the join RETURNS must also be PRINTED.

WHY THIS FILE EXISTS. `alt_main_collisions` shipped in `21aac548` (live in
`58302f07`) inside `join_kalshi_to_board`'s return dict and in NEITHER print
statement, so the collision rate its price tie-break decides was unmeasurable in
production for the whole of its first deploy. `segment_matched_series` /
`segment_refused_series` landed with the identical gap.

A counter that exists only in a return dict is not an instrument, and the
distinction is invisible to the obvious test: asserting `report[...]` passes on
the broken code. **Every assertion here reads the EMITTED LINE.** That is the
whole point of the file, so if a future edit weakens these to dict lookups it
has removed the only thing being checked.
"""

from __future__ import annotations

import re
from collections import Counter

import pytest

from pipeline.kalshi_odds_refresh import join_to_board


@pytest.fixture()
def _game_lines_on(monkeypatch):
    monkeypatch.setenv("SYNDICATE_KALSHI_GAME_LINES", "1")


def _board_row(**over):
    row = {
        "sport": "mlb",
        "event_id": "evt-1",
        "market": "totals",
        "segment": "first5",
        "line": 4.5,
        "side": "over",
        "player_name": None,
        "away_team": "TEX",
        "home_team": "MIL",
    }
    row.update(over)
    return row


def _emitted(capsys, markets, rows, date="2026-09-06"):
    join_to_board(list(markets), list(rows), selected_date=date)
    out = capsys.readouterr().out
    line = next((l for l in out.splitlines() if "[kalshi_odds] BOARD_JOIN" in l), None)
    assert line is not None, f"no BOARD_JOIN line emitted; got:\n{out}"
    return line


@pytest.mark.parametrize(
    "token",
    ["alt_main_collisions=", "segment_matched_series=", "segment_refused_series="],
)
def test_each_counter_appears_in_the_emitted_line(capsys, _game_lines_on, token):
    """Not in the report dict -- in the LINE. The dict passed before the fix."""
    line = _emitted(capsys, [], [_board_row()])
    assert token in line, line


def test_the_counters_are_printed_even_when_empty(capsys, _game_lines_on):
    """Zero and 'never computed' must stay distinguishable from the logs alone.

    Same argument `doubleheader_resolved` already carries: a counter that is
    omitted when empty cannot tell "nothing collided" from "the code that counts
    collisions did not run", and those need different responses.
    """
    line = _emitted(capsys, [], [_board_row()])
    assert "alt_main_collisions=0" in line, line


def test_a_real_collision_is_visible_in_the_line(capsys, _game_lines_on):
    """The main+alt pair the alt collapse creates, counted where a human sees it."""
    rows = [
        _board_row(market="totals", quote={"best_any_book": {"price": -120}}),
        _board_row(market="totals_alt", quote={"best_any_book": {"price": -110}}),
    ]
    line = _emitted(capsys, [], rows)
    assert "alt_main_collisions=1" in line, line


def test_no_field_is_emitted_twice(capsys, _game_lines_on):
    """One name, one value, once. This test exists because it happened.

    Two sessions added counters to this single print statement within minutes of
    each other on 2026-09-06. Both landed, and the merged line emitted
    `alt_main_collisions=` TWICE plus two spellings of the same segment data
    (`segment_matched` beside `segment_refused_series`), half of them stranded
    AFTER the `reasons={...}` dict repr.

    Nothing caught it: both sessions' tests asserted "the token is present", and
    a duplicate is present twice. Presence is the wrong predicate for a line
    other tools parse -- `re.search(r'alt_main_collisions=(\\d+)')` silently
    takes the first of two, which is the shape of bug this repo keeps paying for.
    """
    line = _emitted(capsys, [], [_board_row()])
    names = re.findall(r"\b([a-z_]+)=", line)
    dupes = {n: c for n, c in Counter(names).items() if c > 1}
    assert not dupes, f"emitted twice: {dupes}\n{line}"


def test_reasons_is_last_so_nothing_is_stranded_behind_a_dict_repr(capsys, _game_lines_on):
    """`reasons` is a dict repr; fields after it are harder to read and parse."""
    line = _emitted(capsys, [], [_board_row()])
    assert line.rstrip().endswith("}"), line
    assert line.index("reasons=") > line.index("alt_main_collisions="), line


def test_the_line_still_carries_what_it_carried_before(capsys, _game_lines_on):
    """Additive only -- the fields callers already grep for must survive."""
    line = _emitted(capsys, [], [_board_row()])
    for token in ("kalshi_markets=", "board_rows=", "matched=", "reasons="):
        assert token in line, (token, line)


# ---------------------------------------------------------------------------
# BOTH EMITTERS, checked at the SOURCE.
#
# There are two `KALSHI_BOARD_JOIN` prints -- `[kalshi_odds]` in
# `kalshi_odds_refresh` and `[portfolio_commit]` in `portfolio_commit`. The
# second is the one whose output becomes an ORDER, so a counter missing there
# costs more than one missing in the first. They drifted apart for a whole
# deploy and nothing noticed, because each file's tests only ever looked at its
# own line.
#
# Driving the `portfolio_commit` emitter through stdout needs the whole commit
# path stood up, so this reads the f-string from the SOURCE instead. Weaker than
# capturing output -- it proves the field is written, not that it renders -- but
# it is the check that would have caught the duplicate merge in either file, and
# the stdout tests above cover rendering for the emitter that can be driven.
# ---------------------------------------------------------------------------

_EMITTERS = {
    "kalshi_odds_refresh": ("pipeline/kalshi_odds_refresh.py", '"[kalshi_odds] BOARD_JOIN"'),
    "portfolio_commit": ("pipeline/portfolio_commit.py", '"[portfolio_commit] KALSHI_BOARD_JOIN'),
}

_REQUIRED = ("segment_matched_series", "segment_refused_series", "alt_main_collisions")


def _emitter_fields(path: str, anchor: str) -> list[str]:
    from pathlib import Path

    src = Path(__file__).resolve().parents[1] / path
    text = src.read_text(encoding="utf-8")
    start = text.index(anchor)
    end = text.index("flush=True", start)
    return re.findall(r'f"[^"]*? ([a-z_]+)=\{', text[start:end])


@pytest.mark.parametrize("name", sorted(_EMITTERS))
@pytest.mark.parametrize("field", _REQUIRED)
def test_both_emitters_print_every_counter(name, field):
    path, anchor = _EMITTERS[name]
    assert field in _emitter_fields(path, anchor), f"{name} does not print {field}"


@pytest.mark.parametrize("name", sorted(_EMITTERS))
def test_neither_emitter_prints_a_field_twice(name):
    path, anchor = _EMITTERS[name]
    fields = _emitter_fields(path, anchor)
    dupes = {f: c for f, c in Counter(fields).items() if c > 1}
    assert not dupes, f"{name} emits twice: {dupes}"


@pytest.mark.parametrize("name", sorted(_EMITTERS))
def test_reasons_is_last_in_both_emitters(name):
    path, anchor = _EMITTERS[name]
    fields = _emitter_fields(path, anchor)
    assert fields[-1] == "reasons", f"{name} field order: {fields}"
