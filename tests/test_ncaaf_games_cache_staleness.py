"""Lane `ncaaf-kickoff-cache-staleness`: a TBD kickoff inside the firming window is STALE.

Measured on production 2026-09-22, four days before the games: the worker's
`games_2026.json.gz` still flagged `startTimeTBD` on 43 of 65 week-4 games, so
`build_ncaaf_chip_games` wrote `startTime: None`, every one fell back to noon
Central (`2026-09-26T17:00:00+00:00`) and the Layer 2 compact cards read
"Sat Sep 26 - TBD". CFBD had already firmed them -- `/games?year=2026&week=4`
returned `startTimeTBD: False` on 71 of 71, kickoffs 16:00Z/19:30Z/23:00Z/23:30Z.

Nothing refreshed the file, because `games_payload_is_stale` only asked whether
a game that kicked off more than 12 h ago was still `completed: False`, and
every week-4 game is in the future. The rule below is the second staleness
signal; the producer (`refresh_games_cache`) is unchanged and still quota-
latched, throttled and never clobbers a good file.
"""

from __future__ import annotations

import time

from syndicate.features.football.sim_engine.smartsim2.historical_truth.ncaaf_historical_loader import (
    _TBD_KICKOFF_FIRM_SECONDS,
    games_payload_is_stale,
)

NOW = time.mktime(time.strptime("2026-09-22 19:00:00", "%Y-%m-%d %H:%M:%S"))
DAY = 24 * 3600


def _game(*, kickoff_epoch, completed=False, tbd=False):
    stamp = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(kickoff_epoch))
    return {"startDate": stamp, "completed": completed, "startTimeTBD": tbd,
            "homeTeam": "Cincinnati", "awayTeam": "Kansas State"}


def test_a_tbd_kickoff_four_days_out_is_stale():
    # The production case: week 4 is Saturday, the file still says TBD.
    payload = [_game(kickoff_epoch=NOW + 4 * DAY, tbd=True)]
    assert games_payload_is_stale(payload, now=NOW) is True


def test_a_tbd_kickoff_beyond_the_firming_window_is_not_stale():
    # CFBD fills times ~2 weeks out; a November TBD is its honest answer and
    # must not put a MONTHLY-quota API into a refresh loop.
    payload = [_game(kickoff_epoch=NOW + _TBD_KICKOFF_FIRM_SECONDS + DAY, tbd=True)]
    assert games_payload_is_stale(payload, now=NOW) is False


def test_a_firm_upcoming_kickoff_is_not_stale():
    payload = [_game(kickoff_epoch=NOW + 4 * DAY, tbd=False)]
    assert games_payload_is_stale(payload, now=NOW) is False


def test_the_completed_rule_is_unchanged():
    # The original signal: kicked off long ago, still not completed.
    assert games_payload_is_stale([_game(kickoff_epoch=NOW - 2 * DAY)], now=NOW) is True
    assert games_payload_is_stale([_game(kickoff_epoch=NOW - 2 * DAY, completed=True)], now=NOW) is False


def test_a_past_tbd_game_is_judged_by_the_completed_rule_only():
    # A TBD flag left on a game that already played is not a reason to refresh
    # by itself -- but an uncompleted one still is, through the existing rule.
    assert games_payload_is_stale([_game(kickoff_epoch=NOW - 2 * DAY, tbd=True, completed=True)], now=NOW) is False
    assert games_payload_is_stale([_game(kickoff_epoch=NOW - 2 * DAY, tbd=True)], now=NOW) is True


def test_a_payload_that_is_not_a_list_is_never_stale():
    assert games_payload_is_stale({"games": []}, now=NOW) is False
    assert games_payload_is_stale(None, now=NOW) is False


def test_the_production_shape_of_week_four():
    # 65 games: 43 TBD inside the window, the rest firm. One TBD is enough.
    firm = [_game(kickoff_epoch=NOW + 4 * DAY) for _ in range(22)]
    tbd = [_game(kickoff_epoch=NOW + 4 * DAY, tbd=True) for _ in range(43)]
    assert games_payload_is_stale(firm, now=NOW) is False
    assert games_payload_is_stale(firm + tbd, now=NOW) is True
