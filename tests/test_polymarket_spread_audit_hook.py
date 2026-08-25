"""The spread-sign audit hook: OFF by default, and PROVABLY ON when switched on.

WHY BOTH DIRECTIONS ARE TESTED
--------------------------------------------------------------------------
`learnings.md`: "a guard that has never once PASSED is not a guard", and
`CLAUDE.md`'s engine standard requires a REACHABILITY test (`off != on`) for
anything behind a flag -- four inert features in one session were caught by
that and by nothing else. A hook asserted only in its off state is
indistinguishable from a hook that is wired up wrong.

The hook only READS: no venue call, no file written, no order. These tests
assert that too, by giving it a slate and a board in memory and checking the
verdict it derives from them.
"""

from __future__ import annotations

import pytest

from scripts.audit_polymarket_coverage import run_spread_audit_if_enabled, spread_sign_test

_FLAG = "SYNDICATE_POLYMARKET_SPREAD_AUDIT_ON_BOOT"
_DATE = "SYNDICATE_POLYMARKET_SPREAD_AUDIT_DATE"
_MIN = "SYNDICATE_POLYMARKET_SPREAD_AUDIT_MIN_SAMPLE"


@pytest.fixture(autouse=True)
def _clear_flags(monkeypatch):
    for key in (_FLAG, _DATE, _MIN):
        monkeypatch.delenv(key, raising=False)


def test_absent_flag_means_off(monkeypatch):
    """ABSENT != OFF is a real trap in this repo, so the default is pinned."""
    assert run_spread_audit_if_enabled() is None


@pytest.mark.parametrize("raw", ["0", "false", "no", "off", ""])
def test_falsey_flag_values_stay_off(monkeypatch, raw):
    monkeypatch.setenv(_FLAG, raw)
    assert run_spread_audit_if_enabled() is None


def test_flag_on_actually_runs_and_reports_by_name(monkeypatch, capsys):
    """ON must differ from OFF observably -- and refuse BY NAME, never with a zero.

    With no slate artifact reachable the honest answer is `no_slate_artifact`.
    A zero here would be indistinguishable from a venue listing no spreads,
    which is the confusion the whole audit exists to prevent.
    """
    monkeypatch.setenv(_FLAG, "1")
    monkeypatch.setattr(
        "scripts.audit_polymarket_coverage._load_slate",
        lambda: ([], None, "no_slate_artifact"),
    )
    result = run_spread_audit_if_enabled()
    assert result == {"status": "refused", "reason": "no_slate_artifact"}
    assert "SPREAD_SIGN_AUDIT status=refused reason=no_slate_artifact" in capsys.readouterr().out


def test_flag_on_reaches_the_test_and_prints_a_verdict(monkeypatch, capsys):
    """The reachability test proper: switched on, it produces a real verdict."""
    monkeypatch.setenv(_FLAG, "1")
    monkeypatch.setenv(_DATE, "2026-08-25")
    monkeypatch.setenv(_MIN, "1")
    slate = [{
        "slug": "asc-mlb-sd-nyy-2026-08-25-neg-1pt5",
        "sportsMarketTypeV2": "SPORTS_MARKET_TYPE_SPREAD",
    }]
    board = [{
        "market": "spreads", "side": "home", "line": -1.5, "sport": "mlb",
        "selected_date": "2026-08-25",
        "home_team": "New York Yankees", "away_team": "San Diego Padres",
    }]
    monkeypatch.setattr(
        "scripts.audit_polymarket_coverage._load_slate", lambda: (slate, 1.0, None)
    )
    monkeypatch.setattr(
        "scripts.audit_polymarket_coverage._load_board", lambda date: (board, None)
    )
    result = run_spread_audit_if_enabled()
    assert result["status"] == "ok"
    assert result["fixtures_compared"] == 1
    assert "SPREAD_SIGN_AUDIT status=ok" in capsys.readouterr().out


def test_a_diagnostic_never_kills_the_worker(monkeypatch, capsys):
    """It runs inside the live-odds boot sequence. It must not be able to raise."""
    monkeypatch.setenv(_FLAG, "1")

    def _boom():
        raise RuntimeError("artifact store exploded")

    monkeypatch.setattr("scripts.audit_polymarket_coverage._load_slate", _boom)
    result = run_spread_audit_if_enabled()
    assert result["status"] == "error"
    assert "SPREAD_SIGN_AUDIT_FAILED RuntimeError" in capsys.readouterr().out


def test_one_vote_per_fixture_not_one_per_rung():
    """A deep ladder must not let one fixture decide the answer.

    Four rungs of the same fixture, all the same sign convention: if rungs
    voted, this would read n=4 and look four times as confident as it is.
    """
    slate = [
        {"slug": f"asc-mlb-sd-nyy-2026-08-25-{tok}",
         "sportsMarketTypeV2": "SPORTS_MARKET_TYPE_SPREAD"}
        for tok in ("neg-1pt5", "neg-2pt5", "pos-1pt5", "pos-2pt5")
    ]
    board = [{
        "market": "spreads", "side": "home", "line": -1.5, "sport": "mlb",
        "selected_date": "2026-08-25",
        "home_team": "New York Yankees", "away_team": "San Diego Padres",
    }]
    assert spread_sign_test(slate, board, min_sample=1)["fixtures_compared"] == 1


def test_verdict_refuses_below_min_sample():
    """A mapping this expensive to get wrong is not decided on a handful."""
    slate = [{"slug": "asc-mlb-sd-nyy-2026-08-25-neg-1pt5",
              "sportsMarketTypeV2": "SPORTS_MARKET_TYPE_SPREAD"}]
    board = [{
        "market": "spreads", "side": "home", "line": -1.5, "sport": "mlb",
        "selected_date": "2026-08-25",
        "home_team": "New York Yankees", "away_team": "San Diego Padres",
    }]
    assert spread_sign_test(slate, board, min_sample=30)["verdict"].startswith("UNDECIDED")


def test_an_away_board_row_is_normalised_to_home_before_comparing():
    """`spreads|away|+1.5` and `spreads|home|-1.5` are the same fact.

    Comparing the raw board sign without normalising would score identical
    fixtures as agreeing or disagreeing purely by which side the board happened
    to list -- a coin flip wearing a measurement's clothes.
    """
    slate = [{"slug": "asc-mlb-sd-nyy-2026-08-25-neg-1pt5",
              "sportsMarketTypeV2": "SPORTS_MARKET_TYPE_SPREAD"}]
    away_row = [{
        "market": "spreads", "side": "away", "line": 1.5, "sport": "mlb",
        "selected_date": "2026-08-25",
        "home_team": "New York Yankees", "away_team": "San Diego Padres",
    }]
    home_row = [dict(away_row[0], side="home", line=-1.5)]
    assert (
        spread_sign_test(slate, away_row, min_sample=1)["agreement_rate"]
        == spread_sign_test(slate, home_row, min_sample=1)["agreement_rate"]
    )
