"""A Kalshi doubleheader resolves to the right half, or to nothing.

MEASURED ON PRODUCTION 2026-09-04:

    DETCLE     -> ambiguous   both halves share the team pair
    DETCLEG1   -> no_match    the suffix was not parsed
    DETCLEG2   -> no_match

`KXMLBF5SPREAD-26SEP041915DETCLEG2-DET3` and its game-1 twin sat in
`KALSHI_UNMATCHED.unmatched_events` for exactly this reason, so both halves of
every doubleheader were invisible to the order path -- in September, which is
makeup-game season.

**THE FIRST FIX SHIPPED INERT, AND THAT IS WHY `test_the_JOIN_supplies...`
EXISTS.** It selected on `game_number`; `kalshi_board_join` builds its games as
`{event_id, home_team, away_team}` and supplies no such field, so every
candidate scored None and the retry refused. It was deployed, live, correct in
isolation, and did nothing. A helper-only suite could not see that -- so this
file tests the CALLER too, against the same failure the credibility hook had.

The discriminator is `commence_time`, which the board does carry. Kalshi's
ticker stamps the start in Eastern:

    26SEP04-1410-DETCLEG1  -> 18:10Z   board 18:11Z   (+1 min)
    26SEP04-1915-DETCLEG2  -> 23:15Z   board 23:16Z   (+1 min)
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.shared.kalshi_board_join import _resolve_event  # noqa: E402
from syndicate.features.shared.kalshi_catalogue import (  # noqa: E402
    _split_doubleheader,
    event_start_from_ticker,
    match_event_blob,
)

# FULL-GAME series on purpose. `KXMLBF5SPREAD` is the ticker that exposed this
# in production, but `sport_for_series("KXMLBF5SPREAD")` is None -- the segment
# series are not registered to a sport, so they cannot resolve for a SECOND and
# independent reason. Enabling that family is its own decision (`#563`: five
# orders, $7.08, from segment/full-game confusion). This fix covers the
# doubleheaders we can already trade, and `test_a_segment_series_is_still_
# unmapped` pins the remaining gap so it is not mistaken for closed.
G1 = "KXMLBGAME-26SEP041410DETCLEG1-DET"
G2 = "KXMLBGAME-26SEP041915DETCLEG2-DET"


def _games():
    return [
        {"event_id": "early", "away_team": "Detroit Tigers",
         "home_team": "Cleveland Guardians", "commence_time": "2026-09-04T18:11:00Z",
         "away_code": "DET", "home_code": "CLE"},
        {"event_id": "late", "away_team": "Detroit Tigers",
         "home_team": "Cleveland Guardians", "commence_time": "2026-09-04T23:16:00Z",
         "away_code": "DET", "home_code": "CLE"},
        {"event_id": "other", "away_team": "Athletics",
         "home_team": "Seattle Mariners", "commence_time": "2026-09-05T02:11:00Z",
         "away_code": "ATH", "home_code": "SEA"},
    ]


def _rows():
    """Board rows in the shape `_resolve_event` consumes."""
    return [dict(g, market="h2h") for g in _games()]


# --- THE WIRING. The half that was missing last time. ------------------------


def test_the_JOIN_supplies_commence_time_and_resolves_both_halves():
    """End-to-end through `_resolve_event`, which is what production calls.

    The previous fix passed every unit test in this file and did nothing in
    production, because the caller handed the matcher no field to decide on.
    """
    rows = _rows()
    first = _resolve_event({"ticker": G1, "series": "KXMLBGAME"}, rows)
    second = _resolve_event({"ticker": G2, "series": "KXMLBGAME"}, rows)
    assert first["status"] == "ok", first
    assert second["status"] == "ok", second
    assert first["event_id"] == "early"
    assert second["event_id"] == "late"
    assert first["event_id"] != second["event_id"], (
        "the whole point is that the halves are DIFFERENT games")


def test_the_join_still_refuses_when_the_board_has_no_commence_time():
    """Strip the field the caller supplies and the match must REFUSE, not guess.
    This is the inert-fix scenario, asserted rather than remembered."""
    rows = [{k: v for k, v in row.items() if k != "commence_time"} for row in _rows()]
    got = _resolve_event({"ticker": G2, "series": "KXMLBGAME"}, rows)
    assert got["status"] in ("ambiguous", "no_match"), got
    assert got.get("event_id") is None


# --- the matcher -------------------------------------------------------------


def test_each_half_resolves_by_commence_time():
    games = _games()
    first = match_event_blob("DETCLEG1", games, sport="mlb",
                             commence_hint=event_start_from_ticker(G1))
    second = match_event_blob("DETCLEG2", games, sport="mlb",
                              commence_hint=event_start_from_ticker(G2))
    assert first["status"] == "ok" and first["event_id"] == "early"
    assert second["status"] == "ok" and second["event_id"] == "late"
    assert first["matched_by"] == "commence_time"
    assert first["doubleheader_game"] == 1 and second["doubleheader_game"] == 2


def test_the_bare_pair_is_still_ambiguous():
    """WITHOUT the suffix we genuinely cannot tell, and a coin flip between two
    real games is worse than no bet because it looks like a bet."""
    got = match_event_blob("DETCLE", _games(), sport="mlb")
    assert got["status"] == "ambiguous" and got.get("count") == 2


def test_no_hint_refuses_rather_than_picking_one():
    got = match_event_blob("DETCLEG2", _games(), sport="mlb", commence_hint=None)
    assert got["status"] == "ambiguous"
    assert got["reason"] == "doubleheader_not_separable_on_commence_time"


def test_a_hint_nowhere_near_either_game_refuses():
    """Beyond tolerance is not "the closest one wins"."""
    got = match_event_blob(
        "DETCLEG2", _games(), sport="mlb",
        commence_hint=datetime(2026, 9, 4, 6, 0, tzinfo=timezone.utc))
    assert got["status"] == "ambiguous"


def test_two_games_too_close_to_separate_stay_ambiguous():
    """A split-doubleheader 20 minutes apart is not separable at this
    resolution, and the margin rule is what stops a 1-minute edge deciding it."""
    close = [
        dict(_games()[0], commence_time="2026-09-04T18:11:00Z"),
        dict(_games()[1], commence_time="2026-09-04T18:31:00Z"),
    ]
    got = match_event_blob("DETCLEG2", close, sport="mlb",
                           commence_hint=event_start_from_ticker(G2))
    assert got["status"] in ("ambiguous", "no_match")


def test_a_blob_that_already_matched_is_untouched():
    """The retry runs only after the as-is match finds nothing, so this can only
    ADD resolutions."""
    got = match_event_blob("ATHSEA", _games(), sport="mlb")
    assert got["status"] == "ok" and got["event_id"] == "other"
    assert "doubleheader_game" not in got


# --- the ticker clock --------------------------------------------------------


def test_event_start_reads_eastern_and_returns_utc():
    assert event_start_from_ticker(G1) == datetime(2026, 9, 4, 18, 10, tzinfo=timezone.utc)
    assert event_start_from_ticker(G2) == datetime(2026, 9, 4, 23, 15, tzinfo=timezone.utc)


def test_the_offset_follows_DST_rather_than_being_hardcoded():
    """September is EDT (UTC-4), January is EST (UTC-5). A fixed +4 would shift
    every winter match by an hour -- more than enough to pick the wrong half."""
    summer = event_start_from_ticker("KXMLBGAME-26SEP041915AAABBB-AAA")
    winter = event_start_from_ticker("KXNFLGAME-26JAN041915AAABBB-AAA")
    assert summer.hour == 23, "EDT: 19:15 -> 23:15Z"
    assert winter.hour == 0, "EST: 19:15 -> 00:15Z next day"


def test_event_start_returns_None_on_anything_it_cannot_establish():
    for bad in (None, "", "NOTATICKER", "KXMLBGAME", "KXMLBGAME-notadate-X",
                "KXMLBGAME-26XXX041915AAABBB-A", "KXMLBGAME-26SEP991915AAABBB-A"):
        assert event_start_from_ticker(bad) is None, bad


def test_split_doubleheader_refuses_shapes_that_are_not_one():
    assert _split_doubleheader("DETCLEG2") == ("DETCLE", 2)
    assert _split_doubleheader("ATHSEA") == (None, None)
    assert _split_doubleheader("DETCLEG0") == (None, None), "games are numbered from 1"
    assert _split_doubleheader("DETCLEG12") == (None, None), "one digit, within a day"
    assert _split_doubleheader("ABCG1") == (None, None), "needs 4+ leading letters"


def test_a_segment_series_is_still_unmapped_and_that_is_KNOWN():
    """The F5/1H/1Q series carry no sport, so they cannot resolve at all -- a
    gap this fix does NOT close. Pinned so a future reader does not assume the
    doubleheader work made Kalshi's segment inventory reachable."""
    import syndicate.features.shared.kalshi_catalogue as kc

    for series in ("KXMLBF5SPREAD", "KXMLBF5TOTAL", "KXNCAAF1QSPREAD"):
        assert kc.sport_for_series(series) is None, (
            "%s now resolves to a sport -- if that was deliberate, this test "
            "should be updated ALONG WITH a decision about segment pricing, "
            "not deleted" % series)
    assert kc.sport_for_series("KXMLBGAME") == "mlb", "the full-game series still works"
