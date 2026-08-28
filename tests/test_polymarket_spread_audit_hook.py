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

    If rungs voted, a four-rung ladder would read n=4 and look four times as
    confident as it is.

    **THE FIXTURE CHANGED, AND THE ORIGINAL ONE IS WHY**
    `[2026-08-28, lane venue-join-refusal-visibility]`. This used to pass
    `neg-1pt5, neg-2pt5, pos-1pt5, pos-2pt5` and describe them as "all the same
    sign convention". They are not -- that list contains both signs, and the
    docstring asserting otherwise was the same false premise that made the
    whole sign test non-identifying. On the live slate, 12 of 12 sampled MLB
    fixture/magnitude pairs carry BOTH `pos` and `neg`.

    Under the corrected semantics that fixture is deliberately NOT scored (see
    `test_a_fixture_carrying_BOTH_signs_is_not_scored_at_all`), so asserting
    `fixtures_compared == 1` on it was asserting the bug. The ladder here is
    genuinely one-sided, which is what this test always meant to describe, and
    the one-vote property is unchanged.
    """
    slate = [
        {"slug": f"asc-mlb-sd-nyy-2026-08-25-{tok}",
         "sportsMarketTypeV2": "SPORTS_MARKET_TYPE_SPREAD"}
        for tok in ("neg-1pt5", "neg-2pt5", "neg-3pt5", "neg-4pt5")
    ]
    board = [{
        "market": "spreads", "side": "home", "line": -1.5, "sport": "mlb",
        "selected_date": "2026-08-25",
        "home_team": "New York Yankees", "away_team": "San Diego Padres",
    }]
    result = spread_sign_test(slate, board, min_sample=1)
    assert result["fixtures_compared"] == 1
    assert result["fixtures_both_signs_present"] == 0


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


# --------------------------------------------------------------------------
# THE PRODUCTION ZERO, PINNED
# --------------------------------------------------------------------------


def test_a_dateless_board_row_still_pairs_via_the_callers_date():
    """MEASURED IN PRODUCTION 2026-08-25T21:47:20Z: `fixtures=0 no_board_fixture=1167`.

    Shortlist rows carry neither `selected_date` nor `date` -- `_board_rows_for_join`
    returns them verbatim from `read_layer2_shortlist` and nothing stamps one on.
    Requiring the row to carry its own date made the board index come out empty,
    so all 1,167 spread slugs fell through as unpairable and the run reported a
    zero that said nothing about Polymarket at all.

    `join_polymarket_to_board` documents this exact trap and solves it with a
    caller-supplied fallback. This pins that the audit does the same.
    """
    slate = [{"slug": "asc-mlb-sd-nyy-2026-08-25-neg-1pt5",
              "sportsMarketTypeV2": "SPORTS_MARKET_TYPE_SPREAD"}]
    dateless = [{
        "market": "spreads", "side": "home", "line": -1.5, "sport": "mlb",
        "home_team": "New York Yankees", "away_team": "San Diego Padres",
    }]
    assert spread_sign_test(slate, dateless, min_sample=1)["fixtures_compared"] == 0
    with_fallback = spread_sign_test(
        slate, dateless, min_sample=1, selected_date="2026-08-25"
    )
    assert with_fallback["fixtures_compared"] == 1
    assert with_fallback["board_rows_unkeyable"] == 0


def test_the_rows_own_date_still_wins_over_the_callers():
    """A multi-date board must not be collapsed onto one caller's date."""
    slate = [{"slug": "asc-mlb-sd-nyy-2026-08-26-neg-1pt5",
              "sportsMarketTypeV2": "SPORTS_MARKET_TYPE_SPREAD"}]
    tomorrow = [{
        "market": "spreads", "side": "home", "line": -1.5, "sport": "mlb",
        "selected_date": "2026-08-26",
        "home_team": "New York Yankees", "away_team": "San Diego Padres",
    }]
    # The caller says the 25th; the row says the 26th; the slug is the 26th.
    result = spread_sign_test(
        slate, tomorrow, min_sample=1, selected_date="2026-08-25"
    )
    assert result["fixtures_compared"] == 1


def test_a_zero_says_which_kind_of_zero_it_is():
    """Three different facts render as `fixtures=0`; the line must separate them."""
    slate = [{"slug": "asc-mlb-sd-nyy-2026-08-25-neg-1pt5",
              "sportsMarketTypeV2": "SPORTS_MARKET_TYPE_SPREAD"}]

    # (a) the board carries no spread rows at all
    no_spreads = spread_sign_test(
        slate, [{"market": "h2h", "side": "home", "sport": "mlb"}],
        min_sample=1, selected_date="2026-08-25",
    )
    assert no_spreads["board_spread_rows"] == 0
    assert no_spreads["board_fixtures_keyed"] == 0

    # (b) the board HAS spread rows but none can be keyed -- the production case
    unkeyable = spread_sign_test(
        slate, [{"market": "spreads", "side": "home", "line": -1.5, "sport": "mlb"}],
        min_sample=1,
    )
    assert unkeyable["board_spread_rows"] == 1
    assert unkeyable["board_rows_unkeyable"] == 1
    assert unkeyable["board_fixtures_keyed"] == 0

    # (c) the board is keyed fine and the VENUE listed nothing for it
    no_venue = spread_sign_test(
        [], [{"market": "spreads", "side": "home", "line": -1.5, "sport": "mlb",
              "home_team": "New York Yankees", "away_team": "San Diego Padres"}],
        min_sample=1, selected_date="2026-08-25",
    )
    assert no_venue["board_fixtures_keyed"] == 1
    assert no_venue["spread_slugs_with_no_board_fixture"] == 0


def test_a_first_five_innings_spread_never_votes():
    """MEASURED 2026-08-25T22:01:52Z: `fixtures=7 agree=2 disagree=5 rate=0.2857`,
    and ALL FIVE disagreements carried `-f5-`.

    The board's spread is the full game; `f5` is the first five innings. Their
    signs need not agree, so comparing them measures the instrument, not the
    venue -- and a rate of 0.2857 read as evidence against the symmetric-ladder
    finding when it was an artefact.

    It compounded with the one-vote rule: `seen_fixture` is set on the first
    match, so an `f5` slug earlier in the slate stole the fixture's only vote.
    This pins that a segment slug cannot vote even when it comes first.
    """
    board = [{
        "market": "spreads", "side": "home", "line": -1.5, "sport": "mlb",
        "selected_date": "2026-08-25",
        "home_team": "Arizona Diamondbacks", "away_team": "Chicago Cubs",
    }]
    # The f5 slug is FIRST, exactly as production ordered it.
    slate = [
        {"slug": "asc-mlb-chc-az-2026-08-25-f5-neg-1pt5",
         "sportsMarketTypeV2": "SPORTS_MARKET_TYPE_SPREAD"},
        {"slug": "asc-mlb-chc-az-2026-08-25-neg-1pt5",
         "sportsMarketTypeV2": "SPORTS_MARKET_TYPE_SPREAD"},
    ]
    result = spread_sign_test(slate, board, min_sample=1, selected_date="2026-08-25")
    assert result["segment_slugs_skipped"] == 1
    # One vote, and it is the FULL-GAME slug's.
    assert result["fixtures_compared"] == 1
    assert result["agree_with_home_sign"] == 1
    assert result["disagree"] == 0


def test_a_segment_only_fixture_casts_no_vote_at_all():
    """Silence beats a wrong vote: if the venue lists only `f5` for a fixture,
    that fixture must not appear in the denominator."""
    board = [{
        "market": "spreads", "side": "home", "line": -1.5, "sport": "mlb",
        "selected_date": "2026-08-25",
        "home_team": "Arizona Diamondbacks", "away_team": "Chicago Cubs",
    }]
    slate = [{"slug": "asc-mlb-chc-az-2026-08-25-f5-neg-1pt5",
              "sportsMarketTypeV2": "SPORTS_MARKET_TYPE_SPREAD"}]
    result = spread_sign_test(slate, board, min_sample=1, selected_date="2026-08-25")
    assert result["segment_slugs_skipped"] == 1
    assert result["fixtures_compared"] == 0
    assert result["agreement_rate"] is None


# --------------------------------------------------------------------------
# THE OFFSET BOUNDARY PROBE
# --------------------------------------------------------------------------

from scripts.audit_polymarket_coverage import run_offset_probe_if_enabled  # noqa: E402

_PROBE = "SYNDICATE_POLYMARKET_OFFSET_PROBE_ON_BOOT"


@pytest.fixture(autouse=True)
def _clear_probe_flag(monkeypatch):
    monkeypatch.delenv(_PROBE, raising=False)


def _patch(monkeypatch, *, boundary, samples):
    monkeypatch.setattr(
        "syndicate.features.shared.polymarket_us_markets.find_first_game_offset",
        lambda: {"status": "ok", "first_game_offset": boundary, "probes": 16, "monotonic": True},
    )
    monkeypatch.setattr(
        "syndicate.features.shared.polymarket_us_markets.probe_offset_landscape",
        lambda **kw: {"status": "ok", "samples": samples},
    )


def test_probe_is_off_unless_switched_on():
    assert run_offset_probe_if_enabled() is None


def test_a_game_row_below_the_boundary_convicts_the_scan(monkeypatch, capsys):
    """The whole point: games below the boundary mean WE cannot see part of the
    slate, which is the opposite conclusion from 'the venue delisted them'."""
    monkeypatch.setenv(_PROBE, "1")
    _patch(monkeypatch, boundary=20987, samples={
        "4197": {"status": "ok", "games": 0, "types": ["SPORTS_MARKET_TYPE_FUTURE"]},
        "18888": {"status": "ok", "games": 3, "types": ["SPORTS_MARKET_TYPE_SPREAD"]},
        "20987": {"status": "ok", "games": 5, "types": ["SPORTS_MARKET_TYPE_TOTAL"]},
    })
    result = run_offset_probe_if_enabled()
    assert result["status"] == "ok"
    assert "BOUNDARY TOO HIGH" in result["verdict"]
    assert "18888" in capsys.readouterr().out


def test_all_futures_below_exonerates_the_scan(monkeypatch):
    monkeypatch.setenv(_PROBE, "1")
    _patch(monkeypatch, boundary=20987, samples={
        "4197": {"status": "ok", "games": 0, "types": ["SPORTS_MARKET_TYPE_FUTURE"]},
        "18888": {"status": "ok", "games": 0, "types": ["SPORTS_MARKET_TYPE_FUTURE"]},
        "20987": {"status": "ok", "games": 5, "types": ["SPORTS_MARKET_TYPE_SPREAD"]},
    })
    assert "BOUNDARY SOUND" in run_offset_probe_if_enabled()["verdict"]


def test_a_failed_control_is_inconclusive_not_sound(monkeypatch):
    """If the boundary itself shows no games the probe proved nothing, and
    saying 'sound' there would be the permissive-default failure this repo
    keeps paying for."""
    monkeypatch.setenv(_PROBE, "1")
    _patch(monkeypatch, boundary=20987, samples={
        "18888": {"status": "ok", "games": 0, "types": ["SPORTS_MARKET_TYPE_FUTURE"]},
        "20987": {"status": "empty", "note": "past_end_of_collection"},
    })
    assert "INCONCLUSIVE" in run_offset_probe_if_enabled()["verdict"]


def test_no_boundary_refuses_by_name(monkeypatch):
    monkeypatch.setenv(_PROBE, "1")
    monkeypatch.setattr(
        "syndicate.features.shared.polymarket_us_markets.find_first_game_offset",
        lambda: {"status": "error", "first_game_offset": None},
    )
    assert run_offset_probe_if_enabled()["reason"] == "no_boundary"


def test_the_probe_cannot_raise_into_the_boot_loop(monkeypatch, capsys):
    monkeypatch.setenv(_PROBE, "1")

    def _boom():
        raise RuntimeError("venue unreachable")

    monkeypatch.setattr(
        "syndicate.features.shared.polymarket_us_markets.find_first_game_offset", _boom
    )
    assert run_offset_probe_if_enabled()["status"] == "error"
    assert "OFFSET_BOUNDARY_PROBE_FAILED RuntimeError" in capsys.readouterr().out
