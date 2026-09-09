"""The Kalshi ladder's internal-consistency gate.

Polymarket has had this check since 2026-08-29; Kalshi -- the venue that
actually places the orders -- had nothing. Grepping `monoton` across
`syndicate/`, `pipeline/` and `scripts/` on 2026-09-09 matched
`polymarket_board_join.py` and `audit_polymarket_coverage.py` and no third
file.

THE TWO WAYS THIS GATE CAN BE WRONG, and both are tested here by name:

1.  **The direction rule backwards.** A spread ladder runs the OPPOSITE way
    from a total's -- P(cover) RISES with the signed line while P(over) FALLS
    -- so a single rule applied to both condemns every healthy ladder of one
    family. `test_a_healthy_spread_ladder_is_not_condemned` fails on exactly
    that mistake, and its comment states the arithmetic it would have to
    violate.

2.  **Truncation read as incoherence.** `kalshi_odds_refresh` logs a
    `KXNCAAFSPREAD` ladder arriving as 400 rungs of 1,994. A contiguous subset
    of a book is still a coherent book, so a missing rung must never be a
    finding.

The flag ships ABSENT, meaning report-only, and
`test_report_only_refuses_nothing_and_leaves_the_matches_alone` is the pin on
that: a gate that starts refusing on its first deploy produces a number nobody
can distinguish from a gate that is broken.
"""

from __future__ import annotations

import contextlib

import pytest

from syndicate.features.shared.kalshi_board_join import (
    LADDER_TOLERANCE,
    REASON_LADDER_NOT_MONOTONIC,
    join_kalshi_to_board,
    kalshi_ladder_monotonic_mode,
)


# --------------------------------------------------------------------------
# Fixtures. Titles and tickers copied from the shapes the existing join tests
# already carry -- a fixture that guesses at Kalshi's wording tests only my
# imagination.
# --------------------------------------------------------------------------


@contextlib.contextmanager
def _series_registered(mapping):
    """Add series to `SERIES_SPORT` for one test, then put the table BACK.

    RESTORE, never pop: `KXMLBSPREAD` is hand-registered in production code and
    an unconditional pop deletes it for the rest of the pytest process. Copied
    deliberately from `test_kalshi_board_join.py`, which paid for the lesson.
    """
    from syndicate.features.shared import kalshi_catalogue as cat

    absent = object()
    before = {key: cat.SERIES_SPORT.get(key, absent) for key in mapping}
    cat.SERIES_SPORT.update(mapping)
    try:
        yield
    finally:
        for key, prior in before.items():
            if prior is absent:
                cat.SERIES_SPORT.pop(key, None)
            else:
                cat.SERIES_SPORT[key] = prior


def _prop(threshold: int, yes_p: float, player: str = "Andrew Abbott"):
    """A strikeout prop stated Kalshi's way: "N+", never "N - 0.5".

    THE HALF-POINT CONVERSION IS THE POINT OF THIS HELPER. Nothing here ever
    names 6.5; the board rows do, and the ladder only forms if the join
    converts. See `test_the_ladder_is_built_on_the_converted_half_point_lines`.
    """
    return {
        "ticker": f"KXMLBKS-26AUG22ABBOTT-{threshold}",
        "series": "KXMLBKS",
        "title": f"{player}: {threshold}+ strikeouts?",
        "yes_american": -120,
        "no_american": 105,
        "yes_probability": yes_p,
        "no_probability": round(1.0 - yes_p, 6),
    }


def _prop_row(line: float, side: str = "Over", player: str = "Andrew Abbott"):
    return {
        "sport": "mlb",
        "event_id": "evt-1",
        "market": "pitcher_strikeouts",
        "player_name": player,
        "line": line,
        "side": side,
        "quote": {"bookmaker": "draftkings", "price": -110},
    }


def _total(strike: float, yes_p: float):
    return {
        "ticker": f"KXTESTTOTAL-26AUG242140MINATH-{int(strike)}",
        "series": "KXTESTTOTAL",
        "title": f"Over {strike} runs scored?",
        "yes_american": -110,
        "no_american": -110,
        "yes_probability": yes_p,
        "no_probability": round(1.0 - yes_p, 6),
    }


def _total_row(line: float, side: str = "Over"):
    return {
        "sport": "mlb",
        "event_id": "evt-1",
        "market": "totals",
        "away_team": "MIN",
        "home_team": "ATH",
        "side": side,
        "line": line,
    }


def _spread(strike: float, yes_p: float, team: str = "Texas", code: str = "TEX"):
    return {
        "ticker": f"KXMLBSPREAD-26AUG241940TEXCWS-{code}{int(strike * 2)}",
        "series": "KXMLBSPREAD",
        "title": f"{team} wins by over {strike} runs?",
        "yes_american": 150,
        "no_american": -170,
        "yes_probability": yes_p,
        "no_probability": round(1.0 - yes_p, 6),
    }


def _spread_rows(strike: float):
    """TEX @ CHW at one strike, written the way a board writes a spread.

    OPPOSITE SIGNS PER SIDE. Texas favoured takes `-strike`; Chicago takes the
    points at `+strike`. A flat fixture giving both sides the same positive
    line is what once let a magnitude-only lookup pair every spread with the
    opposite bet while the tests stayed green.
    """
    return [
        {
            "sport": "mlb",
            "event_id": "e1",
            "market": "spreads",
            "line": -strike,
            "side": "away",
            "away_team": "TEX",
            "home_team": "CHW",
        },
        {
            "sport": "mlb",
            "event_id": "e1",
            "market": "spreads",
            "line": strike,
            "side": "home",
            "away_team": "TEX",
            "home_team": "CHW",
        },
    ]


def _join_props(markets, rows):
    return join_kalshi_to_board(list(markets), list(rows))


def _join_game(markets, rows, monkeypatch, series, date="2026-08-24"):
    monkeypatch.setenv("SYNDICATE_KALSHI_GAME_LINES", "1")
    with _series_registered(series):
        return join_kalshi_to_board(list(markets), list(rows), selected_date=date)


def _ladder(report):
    return report["ladder_monotonic"]


# --------------------------------------------------------------------------
# The mode flag. Reachability before correctness -- `off != on`.
# --------------------------------------------------------------------------


def test_absent_means_report_only(monkeypatch):
    """The house rule, pinned at the source. Absent is REPORT, not enforce and
    not off, because a gate that refuses on the deploy that introduces it
    cannot be told apart from one whose direction rule is backwards."""
    monkeypatch.delenv("SYNDICATE_KALSHI_LADDER_MONOTONIC", raising=False)
    assert kalshi_ladder_monotonic_mode() == "report"


@pytest.mark.parametrize("raw", ["1", "true", "yes", "on", "enforce", "ENFORCE"])
def test_the_flag_turns_the_gate_into_a_gate(monkeypatch, raw):
    monkeypatch.setenv("SYNDICATE_KALSHI_LADDER_MONOTONIC", raw)
    assert kalshi_ladder_monotonic_mode() == "enforce"


@pytest.mark.parametrize("raw", ["0", "off", "false", "no"])
def test_off_is_a_real_off_switch_and_is_not_the_same_as_absent(monkeypatch, raw):
    """Three states, not two. `off` does not run the check; absent runs it and
    reports. Collapsing them would make "we are measuring" unverifiable."""
    monkeypatch.setenv("SYNDICATE_KALSHI_LADDER_MONOTONIC", raw)
    assert kalshi_ladder_monotonic_mode() == "off"


# --------------------------------------------------------------------------
# (a) A healthy ladder passes.
# --------------------------------------------------------------------------


def test_a_monotone_total_ladder_passes(monkeypatch):
    """P(over) falls as the line rises. Over 9.5 cannot beat over 7.5."""
    monkeypatch.delenv("SYNDICATE_KALSHI_LADDER_MONOTONIC", raising=False)
    report = _join_game(
        [_total(7.5, 0.55), _total(8.5, 0.42), _total(9.5, 0.31)],
        [_total_row(7.5), _total_row(8.5), _total_row(9.5)],
        monkeypatch,
        {"KXTESTTOTAL": "mlb"},
    )
    ladder = _ladder(report)
    assert report["matched"] == 3
    assert ladder["ladders_checked"] == 1
    assert ladder["ladders_monotonic"] == 1
    assert ladder["ladders_violating"] == 0
    assert ladder["worst_violation_points"] == 0.0


def test_the_under_side_runs_the_other_way_and_also_passes(monkeypatch):
    """P(under) RISES with the line. Checked separately because a rule written
    for `over` and applied to `under` condemns every healthy under ladder --
    the same class of mistake as spreads, one market family down."""
    monkeypatch.delenv("SYNDICATE_KALSHI_LADDER_MONOTONIC", raising=False)
    report = _join_game(
        [_total(7.5, 0.55), _total(8.5, 0.42), _total(9.5, 0.31)],
        [_total_row(l, side="Under") for l in (7.5, 8.5, 9.5)],
        monkeypatch,
        {"KXTESTTOTAL": "mlb"},
    )
    ladder = _ladder(report)
    assert report["matched"] == 3
    assert ladder["ladders_checked"] == 1
    assert ladder["ladders_violating"] == 0


def test_over_and_under_are_two_ladders_not_one(monkeypatch):
    """They run in opposite directions, so a merged ladder would be
    non-monotonic BY CONSTRUCTION -- a violation manufactured by the key rather
    than found in the book."""
    monkeypatch.delenv("SYNDICATE_KALSHI_LADDER_MONOTONIC", raising=False)
    rows = [_total_row(l) for l in (7.5, 8.5)]
    rows += [_total_row(l, side="Under") for l in (7.5, 8.5)]
    report = _join_game(
        [_total(7.5, 0.55), _total(8.5, 0.42)],
        rows,
        monkeypatch,
        {"KXTESTTOTAL": "mlb"},
    )
    ladder = _ladder(report)
    assert ladder["ladders_checked"] == 2
    assert ladder["ladders_violating"] == 0


# --------------------------------------------------------------------------
# (b) An inverted pair is caught, with the right magnitude.
# --------------------------------------------------------------------------


def test_an_inverted_pair_is_caught_with_its_magnitude(monkeypatch):
    """Over 7.5 at 0.40 beside over 6.5 at 0.55 is arithmetically impossible.

    The magnitude is asserted in PROBABILITY POINTS and to the value, not
    merely as "> 0": a gate whose finding has no size cannot be triaged, and
    two venues quoting one invariant in two units is a comparison nobody can
    make.
    """
    monkeypatch.delenv("SYNDICATE_KALSHI_LADDER_MONOTONIC", raising=False)
    report = _join_props(
        [_prop(7, 0.40), _prop(8, 0.55)],
        [_prop_row(6.5), _prop_row(7.5)],
    )
    ladder = _ladder(report)
    assert report["matched"] == 2
    assert ladder["ladders_checked"] == 1
    assert ladder["ladders_violating"] == 1
    assert ladder["worst_violation_points"] == pytest.approx(15.0)
    # `strikeouts`, not `pitcher_strikeouts`: the counter key comes off
    # `_row_market`, which canonicalises through `market_keys` -- the same
    # vocabulary the join indexes on. A second spelling here is how the two
    # would drift.
    assert ladder["violations_by_market"] == {"strikeouts|over": 1}
    assert ladder["worst_points_by_market"] == {"strikeouts|over": 15.0}


def test_a_wobble_inside_the_tolerance_is_not_a_violation(monkeypatch):
    """Two rungs quoted a tick apart are noise. The tolerance is Polymarket's
    0.02, deliberately not re-derived -- two tolerances for one arithmetic
    invariant is a difference nobody could explain later."""
    monkeypatch.delenv("SYNDICATE_KALSHI_LADDER_MONOTONIC", raising=False)
    report = _join_props(
        [_prop(7, 0.40), _prop(8, 0.40 + LADDER_TOLERANCE - 0.005)],
        [_prop_row(6.5), _prop_row(7.5)],
    )
    ladder = _ladder(report)
    assert ladder["ladders_checked"] == 1
    assert ladder["ladders_violating"] == 0


def test_two_players_are_two_ladders(monkeypatch):
    """A join key for a player prop that omits the player is a defect that
    looks like a working join. Abbott's rungs and Skenes's must not sort
    together -- merged, these two clean books read as one broken one."""
    monkeypatch.delenv("SYNDICATE_KALSHI_LADDER_MONOTONIC", raising=False)
    report = _join_props(
        [
            _prop(7, 0.55),
            _prop(8, 0.42),
            _prop(7, 0.70, player="Paul Skenes"),
            _prop(8, 0.60, player="Paul Skenes"),
        ],
        [
            _prop_row(6.5),
            _prop_row(7.5),
            _prop_row(6.5, player="Paul Skenes"),
            _prop_row(7.5, player="Paul Skenes"),
        ],
    )
    ladder = _ladder(report)
    assert ladder["ladders_checked"] == 2
    assert ladder["ladders_violating"] == 0


# --------------------------------------------------------------------------
# (c) Truncation is not incoherence.
# --------------------------------------------------------------------------


def test_a_contiguous_truncated_ladder_passes(monkeypatch):
    """`kalshi_odds_refresh` logs `KXNCAAFSPREAD` arriving as 400 rungs of
    1,994. A subset of a coherent book is still coherent, so the check compares
    the rungs it HAS and never reasons about a gap: 6.5 and 11.5 with four
    rungs missing between them is a pass."""
    monkeypatch.delenv("SYNDICATE_KALSHI_LADDER_MONOTONIC", raising=False)
    report = _join_props(
        [_prop(7, 0.55), _prop(12, 0.10)],
        [_prop_row(6.5), _prop_row(11.5)],
    )
    ladder = _ladder(report)
    assert report["matched"] == 2
    assert ladder["ladders_checked"] == 1
    assert ladder["ladders_violating"] == 0
    # And no counter anywhere claims a rung is missing -- there is deliberately
    # no notion of an expected rung count in the gate.
    assert ladder["worst_violation_points"] == 0.0


def test_a_single_rung_is_a_price_not_a_ladder(monkeypatch):
    """Counted apart from the checked ladders, because "0 violations" over a
    book that is ALL single rungs is a very different reading from "0
    violations" over 300 real ladders."""
    monkeypatch.delenv("SYNDICATE_KALSHI_LADDER_MONOTONIC", raising=False)
    report = _join_props([_prop(7, 0.55)], [_prop_row(6.5)])
    ladder = _ladder(report)
    assert ladder["ladders_checked"] == 0
    assert ladder["ladders_single_rung"] == 1
    assert ladder["rungs_seen"] == 1


# --------------------------------------------------------------------------
# (d) Spreads run the OTHER WAY. Getting this backwards condemns every healthy
#     spread ladder on the slate.
# --------------------------------------------------------------------------


def test_a_healthy_spread_ladder_is_not_condemned(monkeypatch):
    """THE DIRECTION TEST, and it fails loudly if the totals rule is reused.

    The board writes a spread as a SIGNED line against one club: that club's
    row at `L` pays when its margin beats `-L`. So `TEX -3.5` (win by 4+) is
    HARDER than `TEX -1.5` (win by 2+), and as the signed line RISES the bet
    gets EASIER -- P(cover) is NON-DECREASING.

    Here TEX is 0.30 at -3.5 and 0.45 at -1.5. Ordered by line that is a RISE,
    which is precisely what the `over` rule calls a violation. Under the
    correct spread rule it is the healthy direction, and both sides' ladders
    pass.
    """
    monkeypatch.delenv("SYNDICATE_KALSHI_LADDER_MONOTONIC", raising=False)
    report = _join_game(
        [_spread(1.5, 0.45), _spread(3.5, 0.30)],
        _spread_rows(1.5) + _spread_rows(3.5),
        monkeypatch,
        {"KXMLBSPREAD": "mlb"},
    )
    ladder = _ladder(report)
    assert report["matched"] == 4
    # TWO ladders from FOUR matches: the away club's two rungs (-3.5, -1.5) and
    # the home club's two (+1.5, +3.5). One market's yes and no feed opposite
    # sides, so the two strikes give each side a two-rung ladder.
    assert ladder["ladders_checked"] == 2
    assert ladder["ladders_monotonic"] == 2
    assert ladder["ladders_violating"] == 0, ladder["samples"]


def test_an_inverted_spread_ladder_is_caught(monkeypatch):
    """The same fixture with TEX likelier to win by 4+ than by 2+ -- impossible,
    and caught at 15 points. Paired with the test above this proves the rule
    discriminates rather than merely passing everything."""
    monkeypatch.delenv("SYNDICATE_KALSHI_LADDER_MONOTONIC", raising=False)
    report = _join_game(
        [_spread(1.5, 0.45), _spread(3.5, 0.60)],
        _spread_rows(1.5) + _spread_rows(3.5),
        monkeypatch,
        {"KXMLBSPREAD": "mlb"},
    )
    ladder = _ladder(report)
    # BOTH sides are incoherent here, and necessarily so: the home rows carry
    # the same markets' NO prices, so an impossible yes ladder is an impossible
    # no ladder. Two ladders, not one.
    assert ladder["ladders_violating"] == 2
    assert ladder["worst_violation_points"] == pytest.approx(15.0)
    assert ladder["violations_by_market"] == {"spreads|away": 1, "spreads|home": 1}


# --------------------------------------------------------------------------
# (e) Report-only refuses nothing, and enforce does. `off != on`, both ways.
# --------------------------------------------------------------------------


def _inverted_prop_case(monkeypatch):
    return _join_props(
        [_prop(7, 0.40), _prop(8, 0.55)],
        [_prop_row(6.5), _prop_row(7.5)],
    )


def test_report_only_refuses_nothing_and_leaves_the_matches_alone(monkeypatch):
    """With the flag ABSENT the board is byte-identical to a build with the
    check switched off entirely: same matches, same order, same values, and
    `reasons` gains no key. The finding is still counted -- that is the whole
    purpose of the mode."""
    monkeypatch.setenv("SYNDICATE_KALSHI_LADDER_MONOTONIC", "off")
    disabled = _inverted_prop_case(monkeypatch)
    monkeypatch.delenv("SYNDICATE_KALSHI_LADDER_MONOTONIC", raising=False)
    reporting = _inverted_prop_case(monkeypatch)

    assert reporting["matches"] == disabled["matches"]
    assert reporting["matched"] == disabled["matched"] == 2
    assert REASON_LADDER_NOT_MONOTONIC not in reporting["reasons"]
    assert reporting["reasons"] == disabled["reasons"]

    ladder = _ladder(reporting)
    assert ladder["mode"] == "report"
    assert ladder["ladders_violating"] == 1
    # What it FOUND and what it DID are held apart. They are the same number
    # only once the flag is on.
    assert ladder["ladders_refused"] == 0
    assert ladder["matches_refused"] == 0
    assert _ladder(disabled)["mode"] == "off"
    assert _ladder(disabled)["ladders_checked"] == 0


def test_enforce_condemns_the_whole_ladder_by_name(monkeypatch):
    """A violation condemns EVERY rung of the ladder, not the pair that trips
    it: if two rungs contradict each other the pairing is untrustworthy at both,
    and choosing a winner would be the guess this file refuses everywhere. The
    refusal is a NAMED reason -- never a silent drop."""
    monkeypatch.setenv("SYNDICATE_KALSHI_LADDER_MONOTONIC", "1")
    report = _inverted_prop_case(monkeypatch)

    assert report["matched"] == 0
    assert report["matches"] == []
    assert report["reasons"][REASON_LADDER_NOT_MONOTONIC] == 2
    ladder = _ladder(report)
    assert ladder["mode"] == "enforce"
    assert ladder["ladders_refused"] == 1
    assert ladder["matches_refused"] == 2


def test_enforce_leaves_a_healthy_ladder_completely_alone(monkeypatch):
    """The other half of `off != on`: turning the gate ON must not change what
    a healthy ladder produces. A gate that also moves the clean rows is a
    pricing change wearing an integrity gate's name."""
    monkeypatch.delenv("SYNDICATE_KALSHI_LADDER_MONOTONIC", raising=False)
    healthy = [_prop(7, 0.55), _prop(8, 0.42)]
    rows = [_prop_row(6.5), _prop_row(7.5)]
    before = _join_props(healthy, rows)
    monkeypatch.setenv("SYNDICATE_KALSHI_LADDER_MONOTONIC", "1")
    after = _join_props(healthy, rows)

    assert after["matches"] == before["matches"]
    assert after["reasons"] == before["reasons"]
    assert REASON_LADDER_NOT_MONOTONIC not in after["reasons"]


# --------------------------------------------------------------------------
# (f) The half-point conversion, exercised rather than assumed.
# --------------------------------------------------------------------------


def test_the_ladder_is_built_on_the_converted_half_point_lines(monkeypatch):
    """Nothing in the Kalshi fixture names 6.5 or 7.5; the titles say "7+" and
    "8+". The rungs only sort into one ladder, and only sort in the right
    order, if the join's `N -> N - 0.5` conversion fed them -- so the sampled
    ladder is asserted to BE the converted lines.

    Matching "7+" against 7.0 finds nothing; matching it against Over 7.5 finds
    a DIFFERENT BET and prices it confidently. An ordering check running on
    unconverted thresholds would be ordering the wrong numbers.
    """
    monkeypatch.delenv("SYNDICATE_KALSHI_LADDER_MONOTONIC", raising=False)
    report = _join_props(
        [_prop(7, 0.40), _prop(8, 0.55)],
        [_prop_row(6.5), _prop_row(7.5)],
    )
    assert sorted(m["line"] for m in report["matches"]) == [6.5, 7.5]

    ladder = _ladder(report)
    assert ladder["rungs_seen"] == 2
    sample = ladder["samples"][0]
    assert [line for line, _p in sample["ladder"]] == [6.5, 7.5]
    assert sample["worst_between_lines"] == (6.5, 7.5)
    assert sample["player"] == "andrew abbott"


# --------------------------------------------------------------------------
# The counters have to reach production, or the report mode buys nothing.
# --------------------------------------------------------------------------


def test_the_gate_is_readable_from_the_emitted_log_line(capsys, monkeypatch):
    """A counter that exists only in a return dict is not an instrument.

    The gate ships in report-only, so this line is the ONLY evidence that will
    say whether it works. It carries the mode, the DENOMINATOR, the finding,
    what the gate actually did, and the size of the worst violation.
    """
    from pipeline.kalshi_odds_refresh import join_to_board

    monkeypatch.delenv("SYNDICATE_KALSHI_LADDER_MONOTONIC", raising=False)
    join_to_board(
        [_prop(7, 0.40), _prop(8, 0.55)],
        [_prop_row(6.5), _prop_row(7.5)],
        selected_date=None,
    )
    out = capsys.readouterr().out
    line = next(l for l in out.splitlines() if "[kalshi_odds] BOARD_JOIN" in l)
    assert "ladder_monotonic=" in line, line
    for token in ("'mode': 'report'", "'ladders_checked': 1", "'ladders_violating': 1"):
        assert token in line, line
    assert "'worst_violation_points': 15.0" in line, line
    # `reasons` is a dict repr and everything after it is harder to parse, so
    # the new field goes BEFORE it -- the rule the sibling test file pins.
    assert line.index("ladder_monotonic=") < line.index("reasons="), line


def test_an_older_report_says_absent_rather_than_printing_zeros():
    """A zero and a missing instrument read identically, and that confusion has
    its own entry in `learnings.md`. A report with no ladder block says so."""
    from pipeline.kalshi_odds_refresh import _ladder_summary

    assert _ladder_summary({})["mode"] == "absent"
