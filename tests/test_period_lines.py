"""`#343` — period lines reduced from the central quote log, replacing Bovada."""

from __future__ import annotations

from syndicate.features.shared.period_lines import period_lines_by_matchup


def _q(segment, market, line, book, home="Atlanta Dream", away="Toronto Tempo"):
    return {
        "segment": segment, "market": market, "line": line, "bookmaker": book,
        "home_team": home, "away_team": away,
    }


def test_reduces_to_one_line_per_period():
    rows = [
        _q("q3", "totals", 56.5, "draftkings"),
        _q("q3", "totals", 56.0, "fanduel"),
        _q("q3", "totals", 56.5, "betmgm"),
        _q("q1", "spreads", -4.5, "draftkings"),
    ]
    out = period_lines_by_matchup(rows)
    entry = out[("Atlanta Dream", "Toronto Tempo")]
    assert entry["period_totals"]["q3"] == 56.5
    assert entry["period_spreads"]["q1"] == -4.5


def test_the_median_never_invents_a_line_no_book_offers():
    # Averaging 56 and 56.5 gives 56.25 -- a line nobody is offering and one
    # that cannot be settled against. Lower-middle instead.
    rows = [_q("q2", "totals", 56.0, "a"), _q("q2", "totals", 56.5, "b")]
    out = period_lines_by_matchup(rows)
    assert out[("Atlanta Dream", "Toronto Tempo")]["period_totals"]["q2"] == 56.0


def test_one_book_cannot_outvote_the_market_by_requoting():
    # A book that re-quotes twenty times in a live game must not get twenty
    # votes. Only its latest line counts.
    rows = [_q("q4", "totals", 99.0, "spam") for _ in range(20)]
    rows += [_q("q4", "totals", 52.5, "dk"), _q("q4", "totals", 52.5, "fd")]
    out = period_lines_by_matchup(rows)
    assert out[("Atlanta Dream", "Toronto Tempo")]["period_totals"]["q4"] == 52.5


def test_alternate_ladders_do_not_drag_the_consensus():
    # An alternate line is a DIFFERENT line by definition; folding a book's alt
    # ladder into the median would pull it toward whatever that book published.
    rows = [
        _q("q1", "totals", 56.5, "dk"),
        _q("q1", "totals_alt", 40.5, "dk"),
        _q("q1", "totals_alt", 70.5, "dk"),
    ]
    out = period_lines_by_matchup(rows)
    assert out[("Atlanta Dream", "Toronto Tempo")]["period_totals"]["q1"] == 56.5


def test_full_game_rows_are_not_period_lines():
    out = period_lines_by_matchup([_q("full", "totals", 198.5, "dk")])
    assert out == {}


def test_h2_is_carried__the_old_csv_loader_dropped_it():
    # The Bovada CSV loader read h1/q1..q4 and omitted h2, while the payload it
    # fed showed one -- the old route was already inconsistent with itself.
    out = period_lines_by_matchup([_q("h2", "totals", 105.0, "dk")])
    assert out[("Atlanta Dream", "Toronto Tempo")]["period_totals"]["h2"] == 105.0


def test_absent_periods_are_none_not_missing():
    out = period_lines_by_matchup([_q("q1", "totals", 56.5, "dk")])
    entry = out[("Atlanta Dream", "Toronto Tempo")]
    assert entry["period_totals"]["q4"] is None
    assert "q4" in entry["period_totals"]
