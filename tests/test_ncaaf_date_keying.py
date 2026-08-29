"""NCAAF contributed ZERO chips on every date, forever.

`_NCAAFDataProvider.games()` opened with `if context.week is None: return []`,
and `build_game_chips` (`game_chip_scoreboard.py:442`) resolves context with NO
week -- so the guard fired on every single request. MEASURED on production
2026-08-08 against ESPN truth:

    09-05   prod chips 0   ESPN 68
    09-12   prod chips 0   ESPN 80

0 of 148 real games. It stayed invisible because zero chips is
indistinguishable from "no slate" -- see todo #273.

The resolver here is deliberately NOT a copy of either NFL resolver. NCAAF's
cards carry a synthetic `{week}_{away}_{home}` key (built in three places in
cards.py), no date field at all, and the card set is a CURATED SUBSET -- cfbd
lists 99 week-1 games and the board builds 16 cards. `cfbd_lines_*.json` is the
bridge: it carries an ESPN-compatible numeric `id`, the `week`, and both team
names, so ESPN ids join to cfbd rows and cfbd rows reconstruct the card key.

A correct answer is therefore "the cards whose games fall on this date", never
"every game ESPN lists".
"""

from __future__ import annotations

import json

import pytest

from syndicate.features.ncaaf import sources


def _cfbd(tmp_path, monkeypatch, by_week):
    root = tmp_path / "ncaaf"
    (root / "data").mkdir(parents=True)
    for week, rows in by_week.items():
        (root / "data" / f"cfbd_lines_2026_wk{week}.json").write_text(
            json.dumps(rows), encoding="utf-8"
        )
    monkeypatch.setattr(sources, "default_ncaaf_source_root", lambda: root)
    return sources


def _row(event_id, week, away, home):
    return {"id": event_id, "week": week, "awayTeam": away, "homeTeam": home,
            "startDate": "2026-09-05T16:00:00.000Z"}


_BY_WEEK = {
    1: [_row(401856766, 1, "North Carolina", "TCU"), _row(401856767, 1, "Ohio State", "Texas")],
    2: [_row(401856800, 2, "Alabama", "Kentucky")],
}


def _fake_events(monkeypatch, ids):
    class _E:
        def __init__(self, event_id):
            self.event_id = event_id

    monkeypatch.setattr(
        "syndicate.features.shared.schedule_adapter.fetch_schedule_for_date",
        lambda sport, date_str, **_k: [_E(i) for i in ids],
    )


def test_a_date_resolves_its_week_and_its_card_keys(tmp_path, monkeypatch):
    s = _cfbd(tmp_path, monkeypatch, _BY_WEEK)
    _fake_events(monkeypatch, ["401856766"])
    assert s.ncaaf_week_and_card_keys_for_date(2026, "2026-09-05") == (1, {"1_North_Carolina_TCU"})


def test_the_card_key_reconstructs_the_builders_format(tmp_path, monkeypatch):
    """cards.py builds `f"{week}_{away}_{home}".replace(" ", "_")` in three
    places. If that format ever changes, this join silently returns nothing --
    which would look exactly like the zero-chips bug it fixes."""
    s = _cfbd(tmp_path, monkeypatch, _BY_WEEK)
    _fake_events(monkeypatch, ["401856767"])
    week, keys = s.ncaaf_week_and_card_keys_for_date(2026, "2026-09-05")
    assert keys == {"1_Ohio_State_Texas"}


def test_a_later_week_resolves_to_that_week(tmp_path, monkeypatch):
    s = _cfbd(tmp_path, monkeypatch, _BY_WEEK)
    _fake_events(monkeypatch, ["401856800"])
    assert s.ncaaf_week_and_card_keys_for_date(2026, "2026-09-12") == (2, {"2_Alabama_Kentucky"})


def test_the_week_with_the_MOST_matches_wins(tmp_path, monkeypatch):
    """Not the first file that happens to match one id."""
    s = _cfbd(tmp_path, monkeypatch, _BY_WEEK)
    _fake_events(monkeypatch, ["401856766", "401856767", "401856800"])
    week, keys = s.ncaaf_week_and_card_keys_for_date(2026, "2026-09-05")
    assert week == 1
    assert keys == {"1_North_Carolina_TCU", "1_Ohio_State_Texas"}


def test_a_date_with_no_games_is_None(tmp_path, monkeypatch):
    s = _cfbd(tmp_path, monkeypatch, _BY_WEEK)
    _fake_events(monkeypatch, [])
    assert s.ncaaf_week_and_card_keys_for_date(2026, "2026-08-22") is None


def test_ids_absent_from_cfbd_are_None(tmp_path, monkeypatch):
    s = _cfbd(tmp_path, monkeypatch, _BY_WEEK)
    _fake_events(monkeypatch, ["999999999"])
    assert s.ncaaf_week_and_card_keys_for_date(2026, "2026-09-05") is None


def test_espn_unreachable_is_None(tmp_path, monkeypatch):
    s = _cfbd(tmp_path, monkeypatch, _BY_WEEK)

    def _boom(*_a, **_k):
        raise RuntimeError("espn unreachable")

    monkeypatch.setattr("syndicate.features.shared.schedule_adapter.fetch_schedule_for_date", _boom)
    assert s.ncaaf_week_and_card_keys_for_date(2026, "2026-09-05") is None


@pytest.mark.parametrize("date_value", ["", None, "   "])
def test_no_date_is_None(tmp_path, monkeypatch, date_value):
    s = _cfbd(tmp_path, monkeypatch, _BY_WEEK)
    _fake_events(monkeypatch, ["401856766"])
    assert s.ncaaf_week_and_card_keys_for_date(2026, date_value) is None


def test_an_explicit_week_still_bypasses_date_resolution(monkeypatch):
    """The page routes pass a real week and must keep the unfiltered card set --
    only the chips path (week=None) resolves by date."""
    from syndicate.blueprints.home import _NCAAFDataProvider
    from syndicate.features.ncaaf import cards as ncaaf_cards

    monkeypatch.setattr(
        ncaaf_cards, "build_smartsim_cards_page_context",
        lambda week: {"games": [{"gamePk": "3_A_B"}, {"gamePk": "3_C_D"}]},
    )
    monkeypatch.setattr(ncaaf_cards, "build_ncaaf_market_board", lambda week: {"games": []})
    provider = _NCAAFDataProvider()
    context = provider.resolve_context(requested_date="2026-09-19", week=3)
    assert len(provider.games(context, is_active_today=True)) == 2
