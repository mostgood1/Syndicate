"""Layer 2 joins projections across the SAME dates its rows came from.

`#587`. `quote_rows` extends across `resolve_window_dates(...)` -- NCAAF's slate
window is 3 days, NFL's 5, soccer's several -- while the projection join asked
for `selected_date` alone. Every row from any other window date was therefore
unprojectable, because the index built for one date does not contain another
date's games.

NCAAF is where that is total rather than partial. Measured on production
2026-08-27:

    PREGAME_PROJECTION_JOIN sport=ncaaf considered=None projected=0
      reason=no NCAAF SmartSim2 projections for this date

    /api/board/game-chips?date=2026-08-29
      total=250  ncaaf=0  {nfl: 16, soccer: 234}

Zero NCAAF chips on its own opening Saturday, against NFL's 16 while NFL is
also out of season. NCAAF's games sit 2-3 days ahead of `selected_date`, so
NOTHING it captured could ever be joined.

This is `#569`'s defect one join later: that one widened the `last_seen` read
to the window for exactly the same reason, and its comment already said
`quote_rows` spans dates.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pipeline import layer2_shortlist as l2


@pytest.fixture()
def fake_attach(monkeypatch):
    """Stand in for `board_enrichment.attach_projections`, per date."""
    calls: list[str] = []
    by_date = {
        "2026-08-29": {"supported": True, "rows_considered": 41, "rows_with_projection": 41},
        "2026-08-30": {"supported": True, "rows_considered": 4, "rows_with_projection": 4},
        "2026-08-27": {"supported": True, "rows_considered": 0, "rows_with_projection": 0,
                       "reason": "no NCAAF SmartSim2 projections for this date"},
    }

    import syndicate.features.shared.board_enrichment as be

    def _fake(grid, *, sport, selected_date):
        calls.append(selected_date)
        return dict(by_date.get(selected_date, {"supported": True, "rows_considered": 0, "rows_with_projection": 0}))

    monkeypatch.setattr(be, "attach_projections", _fake)
    return calls


def test_every_window_date_is_joined_not_just_the_selected_one(fake_attach):
    out = l2._attach_projections_over_window(
        [], sport="ncaaf", selected_date="2026-08-27",
        window_dates=["2026-08-27", "2026-08-29", "2026-08-30"],
    )
    assert fake_attach == ["2026-08-27", "2026-08-29", "2026-08-30"]
    # 41 + 4 + 0 -- the whole window, not the last date and not the first.
    assert out["rows_with_projection"] == 45
    assert out["rows_considered"] == 45


def test_a_single_date_window_is_a_strict_no_op(fake_attach):
    """mlb/nba/wnba/nhl/ncaab resolve to one date and must be untouched."""
    out = l2._attach_projections_over_window(
        [], sport="mlb", selected_date="2026-08-29", window_dates=["2026-08-29"],
    )
    assert fake_attach == ["2026-08-29"]
    assert out["rows_with_projection"] == 41
    assert "window_dates" not in out and "per_date" not in out


def test_the_selected_date_is_joined_even_if_the_window_omits_it(fake_attach):
    out = l2._attach_projections_over_window(
        [], sport="ncaaf", selected_date="2026-08-27", window_dates=["2026-08-29"],
    )
    assert "2026-08-27" in fake_attach


def test_one_unreadable_date_does_not_lose_the_others(monkeypatch):
    """`#379`'s rule on the quote side, applied here."""
    import syndicate.features.shared.board_enrichment as be

    def _fake(grid, *, sport, selected_date):
        if selected_date == "2026-08-29":
            raise RuntimeError("shard exploded")
        return {"supported": True, "rows_considered": 4, "rows_with_projection": 4}

    monkeypatch.setattr(be, "attach_projections", _fake)
    out = l2._attach_projections_over_window(
        [], sport="ncaaf", selected_date="2026-08-27",
        window_dates=["2026-08-27", "2026-08-29", "2026-08-30"],
    )
    assert out["rows_with_projection"] == 8, "the two good dates must survive"
    assert "2026-08-29" in out["date_errors"], "and the failure must be visible"


def test_an_empty_window_does_not_inherit_one_dates_reason(monkeypatch):
    """"no projections for this date" must not describe a seven-date window.

    That phrasing is exactly what made the NCAAF zero unreadable on production
    -- it named a date when the question was about a window.
    """
    import syndicate.features.shared.board_enrichment as be

    monkeypatch.setattr(be, "attach_projections", lambda grid, *, sport, selected_date: {
        "supported": True, "rows_considered": 0, "rows_with_projection": 0,
        "reason": "no NCAAF SmartSim2 projections for this date",
    })
    out = l2._attach_projections_over_window(
        [], sport="ncaaf", selected_date="2026-08-27",
        window_dates=["2026-08-27", "2026-08-28", "2026-08-29"],
    )
    assert "window dates" in str(out.get("reason"))
    assert out.get("reasons_by_date")


def test_the_call_site_passes_the_window(monkeypatch):
    """A helper nothing calls with the window is the original bug."""
    source = (REPO_ROOT / "pipeline" / "layer2_shortlist.py").read_text(encoding="utf-8")
    assert "_attach_projections_over_window(" in source
    assert "window_dates=window_dates" in source
    assert 'attach_projections(grid, sport=sport, selected_date=selected_date)' not in source


# ---------------------------------------------------------------------------
# RATES, which are not counts.
#
# A key that is not in `summable` falls to "first non-falsy wins", so a windowed
# join has been serving the FIRST date's `pct_projected` beside a SUMMED
# `rows_considered` and a SUMMED `rows_with_projection` -- three numbers from two
# different populations in one dict, and the rate is the one a reader quotes.
# Summing rates instead is not the fix; percentages do not add.
# ---------------------------------------------------------------------------


def _rate_attach(monkeypatch, by_date):
    import syndicate.features.shared.board_enrichment as be

    def _fake(grid, *, sport, selected_date):
        return dict(by_date[selected_date])

    monkeypatch.setattr(be, "attach_projections", _fake)


def test_a_windowed_rate_describes_the_WINDOW_not_its_first_date(monkeypatch):
    """First date 100%, second 0%. The window is 50%, and 100% is the bug."""
    _rate_attach(monkeypatch, {
        "2026-09-03": {"supported": True, "rows_considered": 100,
                       "rows_with_projection": 100, "pct_projected": 100.0},
        "2026-09-04": {"supported": True, "rows_considered": 100,
                       "rows_with_projection": 0, "pct_projected": 0.0},
    })
    out = l2._attach_projections_over_window(
        [], sport="ncaaf", selected_date="2026-09-03",
        window_dates=["2026-09-03", "2026-09-04"],
    )
    assert out["rows_considered"] == 200
    assert out["rows_with_projection"] == 100
    assert out["pct_projected"] == 50.0, "the rate must match the counts beside it"


def test_the_edge_rate_gets_a_summed_numerator_too(monkeypatch):
    """`rows_with_edge` was missing from `summable` while `pct_with_edge` was
    being merged -- so the numerator was one pass and the denominator was all
    of them."""
    _rate_attach(monkeypatch, {
        "2026-09-03": {"supported": True, "rows_considered": 100,
                       "rows_with_edge": 40, "pct_with_edge": 40.0},
        "2026-09-04": {"supported": True, "rows_considered": 100,
                       "rows_with_edge": 20, "pct_with_edge": 20.0},
    })
    out = l2._attach_projections_over_window(
        [], sport="mlb", selected_date="2026-09-03",
        window_dates=["2026-09-03", "2026-09-04"],
    )
    assert out["rows_with_edge"] == 60
    assert out["pct_with_edge"] == 30.0


def test_the_name_miss_rate_uses_the_player_denominator_across_the_window(monkeypatch):
    """The MLB cause split, and the denominator trap it carries.

    `player_rows` in that payload is a LEGACY ALIAS for every row, game markets
    included. 30 name misses over 60 PLAYER rows is 50%, not the 15% that
    dividing by the 200-row alias would give.
    """
    _rate_attach(monkeypatch, {
        "2026-09-03": {"supported": True, "rows_considered": 100, "player_rows": 100,
                       "player_rows_considered": 40, "player_unmatched_name": 20,
                       "player_no_projection": 5, "pct_player_name_missed": 50.0},
        "2026-09-04": {"supported": True, "rows_considered": 100, "player_rows": 100,
                       "player_rows_considered": 20, "player_unmatched_name": 10,
                       "player_no_projection": 3, "pct_player_name_missed": 50.0},
    })
    out = l2._attach_projections_over_window(
        [], sport="mlb", selected_date="2026-09-03",
        window_dates=["2026-09-03", "2026-09-04"],
    )
    assert out["player_rows_considered"] == 60, "the counts must SUM, not freeze"
    assert out["player_unmatched_name"] == 30
    assert out["player_no_projection"] == 8
    assert out["pct_player_name_missed"] == 50.0


def test_a_rate_whose_denominator_did_not_survive_is_DROPPED(monkeypatch):
    """Better absent than stale.

    A rate left holding one pass's value is indistinguishable from a current one
    at the point somebody reads it, which is the whole defect. If the counts it
    is derived from are not there, neither is the rate.
    """
    _rate_attach(monkeypatch, {
        "2026-09-03": {"supported": True, "pct_player_name_missed": 50.0},
        "2026-09-04": {"supported": True, "pct_player_name_missed": 10.0},
    })
    out = l2._attach_projections_over_window(
        [], sport="mlb", selected_date="2026-09-03",
        window_dates=["2026-09-03", "2026-09-04"],
    )
    assert "pct_player_name_missed" not in out


def test_a_single_date_window_keeps_its_rate_unchanged(monkeypatch):
    """The no-op path must stay a no-op: re-deriving from the same counts has to
    reproduce the join's own number, or the recompute is itself a rewrite."""
    _rate_attach(monkeypatch, {
        "2026-09-03": {"supported": True, "rows_considered": 143, "rows_with_projection": 37,
                       "pct_projected": 25.9},
    })
    out = l2._attach_projections_over_window(
        [], sport="mlb", selected_date="2026-09-03", window_dates=["2026-09-03"],
    )
    assert out["pct_projected"] == 25.9
