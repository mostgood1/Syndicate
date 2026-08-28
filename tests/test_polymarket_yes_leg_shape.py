"""`#595` step 1 — the log line that will decide whether Polymarket moneylines
can be re-enabled.

Team sides are currently REFUSED at the order path because the venue's YES leg
is measurably not `outcomes[0]` (3 of 8 settled moneylines bought the wrong
team, 2026-08-28) and nothing stored names it. `marketSides` does come back from
`/v1/markets` and is dropped before the order path ever sees it.

The first version of this log truncated at 400 chars and showed ONE side, which
cannot answer the question: it does not say whether the other side is
`long: False` (so `long` IS the axis) or also `long: True` (so it is not), and
it does not say WHERE in `outcomes` the long side sits — which is the rule.

`long_index` is the derived answer, and these tests pin what it must say in each
case rather than trusting the log to be read correctly later.

The `atc-boxing-...` fixture is the real 2026-08-28T15:08:05Z production row.
"""

from __future__ import annotations

import json

import pytest

from syndicate.features.shared import polymarket_us_markets as mod


def _row(outcomes, sides, slug="aec-mlb-lad-det-2026-08-28"):
    # OUTCOMES AND PRICES ARE JSON STRINGS ON THE WIRE, not lists. The first
    # version of these fixtures passed lists, so every test passed while
    # production printed `long_index=None` on all three samples -- a fixture
    # that was wrong in exactly the way that hid the bug.
    return {
        "slug": slug,
        "sportsMarketTypeV2": mod.MONEYLINE_MARKET_TYPE,
        "outcomes": json.dumps(outcomes) if isinstance(outcomes, list) else outcomes,
        "outcomePrices": json.dumps(["0.60", "0.40"]),
        "marketSides": sides,
        "question": "Who wins?",
        "gameStartTime": "2026-08-28T23:00:00Z",
        "category": "sports",
    }


def _side(desc, long, price="0.60", team_name=None):
    side = {"description": desc, "long": long, "price": price}
    if team_name:
        side["team"] = {"name": team_name, "abbreviation": "x"}
    return side


def _emit(monkeypatch, capsys, rows):
    """Run the real slate writer far enough to print, without touching a store."""
    monkeypatch.setattr(mod, "fetch_game_markets", lambda **kw: {"status": "ok", "markets": rows})
    monkeypatch.setattr(mod, "_slate_within_budget",
                        lambda fetched: {"markets": fetched, "dropped": 0,
                                         "dropped_by_date": {}, "kept_through": None})

    from syndicate.features.shared import refresh_state_store

    monkeypatch.setattr(refresh_state_store, "write_json_file", lambda *a, **k: None)
    mod.persist_game_slate()
    return capsys.readouterr().out


def test_long_index_0_says_the_YES_leg_IS_outcomes_zero(monkeypatch, capsys):
    """If this is what production prints on every market, the positional rule
    was right and the refusal can be lifted."""
    out = _emit(monkeypatch, capsys, [
        _row(["Dodgers", "Tigers"], [_side("Dodgers", True), _side("Tigers", False)])
    ])
    assert "MONEYLINE_YES_LEG_SHAPE" in out
    assert "long_index=0" in out


def test_long_index_1_is_the_MEASUREMENT_that_kills_the_positional_rule(monkeypatch, capsys):
    """The case the whole refusal exists for. `outcomes[0]` is not the YES leg
    here, and `long_index` says so in one field rather than leaving a reader to
    diff two lists by eye."""
    out = _emit(monkeypatch, capsys, [
        _row(["Dodgers", "Tigers"], [_side("Dodgers", False), _side("Tigers", True)])
    ])
    assert "long_index=1" in out


def test_BOTH_sides_are_emitted_because_one_cannot_answer_it(monkeypatch, capsys):
    """The defect in the first version. A single entry reading `long: True`
    does not establish that `long` is the yes/no axis at all."""
    out = _emit(monkeypatch, capsys, [
        _row(["Dodgers", "Tigers"], [_side("Dodgers", True), _side("Tigers", False)])
    ])
    assert "'d': 'Dodgers'" in out
    assert "'d': 'Tigers'" in out


def test_TWO_long_sides_reads_AMBIGUOUS_rather_than_taking_the_first(monkeypatch, capsys):
    """If both sides are long then `long` is not the axis, and resolving that by
    taking the first would manufacture an answer out of a refutation."""
    out = _emit(monkeypatch, capsys, [
        _row(["Dodgers", "Tigers"], [_side("Dodgers", True), _side("Tigers", True)])
    ])
    assert "AMBIGUOUS_TWO_LONG" in out
    assert "long_index=0" not in out


def test_a_long_side_absent_from_outcomes_is_REPORTED_not_swallowed(monkeypatch, capsys):
    """It would mean the two fields cannot be joined and the rule needs a
    different key. That is a finding, not a None."""
    out = _emit(monkeypatch, capsys, [
        _row(["Dodgers", "Tigers"], [_side("Los Angeles Dodgers", True), _side("Tigers", False)])
    ])
    assert "long_side_not_in_outcomes" in out


def test_the_team_name_is_used_when_description_is_absent(monkeypatch, capsys):
    """The real production row carries both; a row with only `team.name` must
    still resolve rather than reading as a missing side."""
    out = _emit(monkeypatch, capsys, [
        _row(["Canelo Alvarez", "Christian Mbilli"],
             [{"long": True, "price": "0.69", "team": {"name": "Canelo Alvarez"}},
              {"description": "Christian Mbilli", "long": False, "price": "0.34"}])
    ])
    assert "long_index=0" in out


def test_three_markets_are_sampled_because_one_cannot_show_CONSISTENCY(monkeypatch, capsys):
    """Whether `long` behaves the same way across markets is the actual question;
    a single sample cannot show it."""
    rows = [
        _row(["A", "B"], [_side("A", True), _side("B", False)], slug=f"aec-mlb-s{i}")
        for i in range(5)
    ]
    out = _emit(monkeypatch, capsys, rows)
    assert out.count("MONEYLINE_YES_LEG_SHAPE") == 3


def test_no_moneyline_prints_a_NAMED_zero(monkeypatch, capsys):
    """"No moneyline in the slate" and "the fields are absent from every
    moneyline" are different findings and must not both render as silence."""
    out = _emit(monkeypatch, capsys, [])
    assert "MONEYLINE_YES_LEG_SHAPE none" in out
    assert "moneylines=0" in out


def test_a_row_with_no_marketSides_still_prints_and_says_sides_None(monkeypatch, capsys):
    """`question` alone is enough to sample a row -- the point is to learn
    whether the field is there at all."""
    row = _row(["A", "B"], None)
    out = _emit(monkeypatch, capsys, [row])
    assert "MONEYLINE_YES_LEG_SHAPE" in out
    assert "sides=None" in out


# ---------------------------------------------------------------------------
# The two defects the FIRST production run exposed, 2026-08-28T19:37:42Z.
# ---------------------------------------------------------------------------


def test_outcomes_arriving_as_a_JSON_STRING_still_yields_a_long_index(monkeypatch, capsys):
    """THE BUG THE FIRST RUN FOUND. `outcomes` is a JSON string on the wire and
    `_long_index` guarded on `isinstance(list)`, so it returned None for every
    real market -- an instrument that could only ever answer None, shipped to
    answer a question.

    Verbatim from production:
        outcomes='["Canelo Alvarez","Christian Mbilli"]'   long_index=None
    """
    row = _row(None, [_side("Canelo Alvarez", True), _side("Christian Mbilli", False)],
               slug="aec-boxing-canalv-chrmbi-2026-10-31")
    row["outcomes"] = '["Canelo Alvarez","Christian Mbilli"]'   # the literal wire value
    out = _emit(monkeypatch, capsys, [row])
    assert "long_index=0" in out
    assert "long_index=None" not in out


def test_unparseable_outcomes_says_so_rather_than_reading_as_None(monkeypatch, capsys):
    """`None` conflated "could not parse" with "no long side". Different jobs."""
    row = _row(None, [_side("A", True), _side("B", False)])
    row["outcomes"] = "{not json"
    out = _emit(monkeypatch, capsys, [row])
    assert "outcomes_unparseable" in out


def test_a_bettable_sport_is_PREFERRED_over_whatever_sorts_first(monkeypatch, capsys):
    """THE SECOND DEFECT. The first run sampled one boxing and two UFC markets.
    Every wrong-team order was MLB, and an individual-competitor market's
    convention says nothing about a team moneyline's -- so those samples could
    not have settled it even with `long_index` working."""
    rows = [
        _row(["A", "B"], [_side("A", True), _side("B", False)], slug="aec-boxing-x-y-2026-10-31"),
        _row(["C", "D"], [_side("C", True), _side("D", False)], slug="aec-ufc-p-q-2026-08-29"),
        _row(["E", "F"], [_side("E", True), _side("F", False)], slug="aec-ufc-r-s-2026-08-29"),
        _row(["Dodgers", "Tigers"], [_side("Dodgers", True), _side("Tigers", False)],
             slug="aec-mlb-lad-det-2026-08-28"),
    ]
    out = _emit(monkeypatch, capsys, rows)
    assert "aec-mlb-lad-det-2026-08-28" in out
    assert "league='mlb'" in out
    assert "bettable=True" in out


def test_a_slate_with_NO_bettable_moneyline_says_so_before_the_samples(monkeypatch, capsys):
    """Three boxing markets reading `long_index=0` would otherwise look like an
    answer about the population that actually bought the wrong team."""
    rows = [
        _row(["A", "B"], [_side("A", True), _side("B", False)], slug="aec-boxing-x-y-2026-10-31"),
        _row(["C", "D"], [_side("C", True), _side("D", False)], slug="aec-ufc-p-q-2026-08-29"),
    ]
    out = _emit(monkeypatch, capsys, rows)
    assert "no_bettable_moneyline" in out
    assert "bettable=False" in out
