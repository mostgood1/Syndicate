"""Kalshi soccer is never same-day, so an exact-date join matches zero of it.

MEASURED 2026-09-01T19:51:44Z on refresh-worker (`BY_GAME_DATE`,
`TRIM_BY_SPORT`): 918 soccer markets in the working set, spanning 2026-09-02
.. 09-15, and **ZERO dated that day**, while `market_is_for_another_date` was
the join's largest refusal at 3,495 of 6,000.

The fix mirrors `polymarket_board_join`, which fixed this identical defect for
this identical sport: SOCCER ONLY, FORWARD ONLY, 14-day horizon, and nothing
about fixture identity relaxed.

Both directions are asserted (off != on). A widening tested only in its ON
state cannot be told apart from a join that ignores its own switch.
"""

from __future__ import annotations

import pytest

from syndicate.features.shared.kalshi_board_join import join_kalshi_to_board


def _soccer_market(
    ticker="KXLALIGAGAME-26SEP05BARVAL-TIE",
    series="KXLALIGAGAME",
    title="Tie is the result",
    yes=120,
    no=-140,
):
    return {
        "ticker": ticker,
        "series": series,
        "title": title,
        "yes_american": yes,
        "no_american": no,
    }


def _mlb_market(ticker="KXMLBKS-26AUG26BACHAR-6", series="KXMLBKS"):
    return {
        "ticker": ticker,
        "series": series,
        "title": "Lake Bachar: 6+ strikeouts?",
        "yes_american": -120,
        "no_american": 100,
    }


def _mlb_row(player="Lake Bachar", line=5.5, side="over"):
    return {
        "sport": "mlb",
        "market": "strikeouts",
        "player_name": player,
        "line": line,
        "side": side,
        "event_id": "evt-mlb-1",
        "quote": {"price": -110},
    }


def test_a_future_soccer_fixture_is_no_longer_refused_for_its_date():
    """The whole point: Kalshi lists soccer only for future fixtures, so the
    exact-date test refused 100% of it."""
    out = join_kalshi_to_board(
        [_soccer_market()], [], selected_date="2026-09-01"
    )
    # With no board rows nothing can MATCH, but the refusal must no longer be
    # the DATE -- that is the gate this change moves.
    assert out["reasons"].get("market_is_for_another_date", 0) == 0


def test_the_same_market_IS_refused_by_date_with_the_switch_off(monkeypatch):
    """off != on. Without this the change is indistinguishable from a join that
    ignores its own switch."""
    monkeypatch.setenv("SYNDICATE_KALSHI_SOCCER_FORWARD_DATES", "off")
    out = join_kalshi_to_board(
        [_soccer_market()], [], selected_date="2026-09-01"
    )
    assert out["reasons"].get("market_is_for_another_date", 0) == 1


def test_a_soccer_fixture_PAST_the_horizon_still_refuses():
    """14 days, not unbounded. A market far enough out is a different slate."""
    far = _soccer_market(ticker="KXLALIGAGAME-26OCT05BARVAL-TIE")
    out = join_kalshi_to_board([far], [], selected_date="2026-09-01")
    assert out["reasons"].get("market_is_for_another_date", 0) == 1


def test_a_soccer_fixture_BEFORE_the_slate_still_refuses():
    """FORWARD ONLY. A past market is settled or in progress, and matching one
    would price a live board row off a resolved contract."""
    stale = _soccer_market(ticker="KXLALIGAGAME-26AUG20BARVAL-TIE")
    out = join_kalshi_to_board([stale], [], selected_date="2026-09-01")
    assert out["reasons"].get("market_is_for_another_date", 0) == 1


def test_MLB_IS_NOT_WIDENED_and_that_is_the_safety_argument():
    """MLB plays the SAME FIXTURE on consecutive days, so widening there could
    price tonight's game off tomorrow's market -- a worse bug than the one
    being fixed. This is the control: same horizon, different sport, still
    refused."""
    tomorrow = _mlb_market(ticker="KXMLBKS-26AUG27BACHAR-6")
    out = join_kalshi_to_board([tomorrow], [_mlb_row()], selected_date="2026-08-26")
    assert out["matched"] == 0
    assert (
        out["reasons"].get("market_is_for_another_date", 0)
        + out["reasons"].get("would_match_but_wrong_date", 0)
    ) == 1


def test_an_exact_date_match_is_unaffected_for_every_sport():
    out = join_kalshi_to_board([_mlb_market()], [_mlb_row()], selected_date="2026-08-26")
    assert out["matched"] == 1


def test_the_widening_does_not_relax_fixture_identity():
    """A widened soccer market still has to pair with a real board fixture; it
    cannot acquire a row just by being inside the horizon."""
    out = join_kalshi_to_board(
        [_soccer_market()], [_mlb_row()], selected_date="2026-09-01"
    )
    assert out["matched"] == 0


class TestTheResolverGate:
    """Soccer matches feed the QUOTE CAPTURE; the money path stays closed.

    Measured precondition that forced this: `no_model_edge_pct` does NOT keep
    soccer out of positions -- 4 soccer positions in the 7 days to 2026-09-01,
    soccer absent from `DEFAULT_EXCLUDED_FAMILIES`, `SYNDICATE_EXECUTION_ENABLED=1`.
    """

    @staticmethod
    def _match(series):
        return {
            "series": series,
            "ticker": f"{series}-26SEP05X-TIE",
            "market": "h2h",
            "board_side": "home",
            "kalshi_american": 120,
            "board_event_id": "evt-1",
            "line": None,
            "player_name": None,
        }

    def test_a_kalshi_match_carries_no_sport_field(self):
        """The gate reads `series` through `sport_for_series` BECAUSE of this.
        A gate keyed on `m.get("sport")` would read None for every row, withhold
        nothing, and print `withheld=0` -- indistinguishable from armed."""
        assert "sport" not in self._match("KXLALIGAGAME")

    def test_sport_for_series_identifies_soccer_from_the_series(self):
        from syndicate.features.shared.kalshi_catalogue import sport_for_series

        assert sport_for_series("KXLALIGAGAME") == "soccer"
        assert sport_for_series("KXMLBKS") != "soccer"


class TestTheResolverGateWithholdsForReal:
    """The gate itself, exercised through `_resolvers_from_markets`.

    THE JOIN IS STUBBED, DELIBERATELY. A first version of these tests fed a
    real soccer market through the real join and asserted the gate's log line.
    It passed -- with `soccer_matches=0`, because the fixture's club blob
    (`BARVAL`) does not resolve against a hand-built board row, so the gate was
    never reached and the test proved nothing about withholding. That is the
    "fixture cannot violate the property" shape: zero coverage reading as
    green. Stubbing the join makes these tests about the GATE and nothing else;
    the join's own behaviour is covered by the tests above.
    """

    @staticmethod
    def _wire(monkeypatch, matches):
        import pipeline.portfolio_commit as pc
        from syndicate.features.shared import kalshi_board_join as kbj

        monkeypatch.setattr(pc, "_board_rows_for_join", lambda selected_date: [{}])
        monkeypatch.setattr(
            kbj, "join_kalshi_to_board",
            lambda markets, board_rows, selected_date="": {
                "matches": list(matches), "reasons": {}, "kalshi_markets": len(markets),
            },
        )
        return pc

    @staticmethod
    def _match(series, ticker="X-26SEP05Y-TIE"):
        return {
            "series": series, "ticker": ticker, "market": "h2h",
            "board_side": "home", "kalshi_american": 120,
            "board_event_id": "evt-1", "line": None, "player_name": None,
        }

    def _line(self, capsys):
        rows = [
            l for l in capsys.readouterr().out.splitlines()
            if "KALSHI_SOCCER_RESOLVERS" in l
        ]
        assert rows, "the gate must print on every build, zeroes included"
        return rows[0]

    def test_soccer_matches_are_WITHHELD_and_the_count_is_non_zero(
        self, monkeypatch, capsys
    ):
        """The assertion that has teeth: `withheld` must equal the soccer count,
        and that count must be > 0 -- otherwise the filter read a field that
        does not exist and withheld nothing."""
        monkeypatch.delenv("SYNDICATE_KALSHI_SOCCER_RESOLVERS", raising=False)
        pc = self._wire(monkeypatch, [self._match("KXLALIGAGAME"), self._match("KXMLBKS")])
        price, ticker = pc._resolvers_from_markets([{}], "2026-09-01")
        line = self._line(capsys)
        assert "armed=False" in line
        assert "soccer_matches=1" in line and "withheld=1" in line
        # The MLB match survives, so the venue keeps its book.
        assert price is not None and ticker is not None

    def test_an_all_soccer_slate_returns_no_resolvers_rather_than_empty_ones(
        self, monkeypatch, capsys
    ):
        monkeypatch.delenv("SYNDICATE_KALSHI_SOCCER_RESOLVERS", raising=False)
        pc = self._wire(monkeypatch, [self._match("KXLALIGAGAME")])
        assert pc._resolvers_from_markets([{}], "2026-09-01") == (None, None)
        assert "withheld=1" in self._line(capsys)

    def test_the_gate_prints_even_when_it_withholds_nothing(
        self, monkeypatch, capsys
    ):
        """`withheld=0` on an MLB-only slate is a RESULT; no line at all is an
        ambiguity -- the lesson POLYMARKET_ORIENTATION already learned."""
        monkeypatch.delenv("SYNDICATE_KALSHI_SOCCER_RESOLVERS", raising=False)
        pc = self._wire(monkeypatch, [self._match("KXMLBKS")])
        pc._resolvers_from_markets([{}], "2026-08-26")
        line = self._line(capsys)
        assert "soccer_matches=0" in line and "withheld=0" in line

    def test_arming_the_switch_stops_withholding(self, monkeypatch, capsys):
        monkeypatch.setenv("SYNDICATE_KALSHI_SOCCER_RESOLVERS", "1")
        pc = self._wire(monkeypatch, [self._match("KXLALIGAGAME")])
        price, _ticker = pc._resolvers_from_markets([{}], "2026-09-01")
        line = self._line(capsys)
        assert "armed=True" in line and "soccer_matches=1" in line and "withheld=0" in line
        assert price is not None, "armed means the soccer match reaches the resolvers"
