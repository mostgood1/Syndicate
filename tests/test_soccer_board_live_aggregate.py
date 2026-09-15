"""The board's soccer cards must read the CROSS-SERVICE aggregate, not a disk hop.

MEASURED 2026-09-15 (lane `soccer-live-scoreboard-range-stale`). The Layer 2
compact chips served pre-deploy soccer state for ELEVEN consecutive publishes
(20:38:19-21:01:41Z) while web held the correct file, and went fresh on the
first publish after refresh-worker's next successful hot-artifact pull
(21:02:50Z -> 21:04:02Z). The chips are built on refresh-worker; the per-league
`live_state_<date>.json` is a filesystem write on live-odds-worker, and the only
thing that moves it across is `pull_hot_artifacts` inside the heavy board build
-- one date per build, and ~1 in 6 of those requests timed out that day.

`live/soccer_live_lens.json` crosses services with no hop at all: it goes
through `refresh_state_store.write_json_file`, i.e. the keyvalue backend that
all three services share. These tests pin the card reader to it.

EVERY TEST HERE FAILS ON THE PRE-CHANGE CODE, where `_live_state_entry` and
`_live_vintage` read `live_state_payload` (the per-league file) alone.
"""
from __future__ import annotations

import json

import pytest

from syndicate.features.soccer import cards
from syndicate.features.soccer import sources as S
from syndicate.features.shared.timezone import central_today_iso


LEAGUE = "epl"
EVENT = "401879301"


@pytest.fixture
def root(tmp_path, monkeypatch):
    """`data_root()` is what BOTH reads derive their path (and keyvalue key) from."""
    monkeypatch.setattr(
        "syndicate.features.shared.refresh_state_store.data_root", lambda: tmp_path
    )
    return tmp_path


def _today() -> str:
    # `_live_vintage` asks for `central_today_iso()` and nothing else, so a
    # fixture dated anything but today tests a code path no chip build takes.
    return central_today_iso()


def _write_per_league(root, *, generated_at, games=None, match_box=None, date=None):
    date = date or _today()
    directory = root / "soccer_source" / LEAGUE / "api" / "live_state"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"live_state_{date}.json").write_text(
        json.dumps(
            {
                "league": LEAGUE,
                "date": date,
                "generated_at": generated_at,
                "count": len(games or {}),
                "games": games or {},
                "match_box": match_box or {},
                "match_box_count": len(match_box or {}),
            }
        ),
        encoding="utf-8",
    )


def _write_aggregate(
    root,
    *,
    generated_at,
    games=(),
    finals=(),
    date=None,
    leagues_checked=(LEAGUE,),
    errors=None,
):
    date = date or _today()
    directory = root / "live"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "soccer_live_lens.json").write_text(
        json.dumps(
            {
                "date": date,
                "generated_at": generated_at,
                "leagues_checked": list(leagues_checked),
                "leagues_with_games": sorted({str(g.get("league")) for g in games}),
                "count": len(games),
                "games": list(games),
                "finals": list(finals),
                "errors": errors if errors is not None else {},
            }
        ),
        encoding="utf-8",
    )


def _live_row(*, score_home, score_away, clock):
    return {
        "league": LEAGUE,
        "event_id": EVENT,
        "home_team": "Arsenal",
        "away_team": "Coventry City",
        "score_home": score_home,
        "score_away": score_away,
        "status_state": "in",
        "status_display_clock": clock,
    }


def test_a_newer_aggregate_supplies_the_live_score(root):
    """THE PRODUCTION READING: the disk copy is an hour behind, the store is not."""
    _write_per_league(
        root,
        generated_at="2026-09-15T20:07:50+00:00",
        games={EVENT: {"event_id": EVENT, "score_home": 0, "score_away": 0,
                       "status_state": "in", "status_display_clock": "1'"}},
    )
    _write_aggregate(
        root,
        generated_at="2026-09-15T21:04:02+00:00",
        games=[_live_row(score_home=2, score_away=0, clock="67'")],
    )
    entry = cards._live_state_entry(LEAGUE, _today(), EVENT, "games")
    assert entry is not None, "the card read no live entry at all"
    assert entry["score_home"] == 2
    assert entry["status_display_clock"] == "67'"


def test_a_match_that_ENDED_leaves_games(root):
    """`games` means IN PLAY. Carrying a stale entry presents a settled result as live."""
    _write_per_league(
        root,
        generated_at="2026-09-15T20:07:50+00:00",
        games={EVENT: _live_row(score_home=1, score_away=0, clock="88'")},
    )
    _write_aggregate(root, generated_at="2026-09-15T21:04:02+00:00", games=[])
    assert cards._live_state_entry(LEAGUE, _today(), EVENT, "games") is None


def test_an_UNPOLLED_league_is_not_read_as_nothing_live(root):
    """`poll_active_leagues_for_tick` only polls `active_leagues_for_date`.

    A league it never checked is absent from `games` for a reason that has
    nothing to do with whether a match is running. Reading that absence as a
    deletion is the permissive-default failure `learnings.md` names.
    """
    _write_per_league(
        root,
        generated_at="2026-09-15T20:07:50+00:00",
        games={EVENT: _live_row(score_home=1, score_away=0, clock="88'")},
    )
    _write_aggregate(
        root,
        generated_at="2026-09-15T21:04:02+00:00",
        games=[],
        leagues_checked=["la_liga", "mls"],
    )
    entry = cards._live_state_entry(LEAGUE, _today(), EVENT, "games")
    assert entry is not None, "an unpolled league's live match was deleted by an absence"
    assert entry["score_home"] == 1


def test_a_FAILED_league_poll_is_not_read_as_nothing_live(root):
    """A league whose poll RAISED is recorded in `errors` and omitted from `games`.

    That is the 2026-08-17 shape: seven leagues wrote `(0 live games)` while the
    three with matches in play were exactly the three that threw.
    """
    _write_per_league(
        root,
        generated_at="2026-09-15T20:07:50+00:00",
        games={EVENT: _live_row(score_home=1, score_away=0, clock="88'")},
    )
    _write_aggregate(
        root,
        generated_at="2026-09-15T21:04:02+00:00",
        games=[],
        errors={LEAGUE: "ReadTimeout: ESPN"},
    )
    entry = cards._live_state_entry(LEAGUE, _today(), EVENT, "games")
    assert entry is not None, "a FAILED poll was read as 'no matches in play'"
    assert entry["score_home"] == 1


def test_finals_are_written_OVER_the_rich_box_not_instead_of_it(root):
    """`finals` is six settlement scalars; `match_box` carries the goal list.

    Replacing the record would fix the score by deleting the card's content.
    """
    _write_per_league(
        root,
        generated_at="2026-09-15T20:07:50+00:00",
        match_box={
            EVENT: {
                "event_id": EVENT,
                "score_home": 1,
                "score_away": 0,
                "status_state": "in",
                "goals": [{"scorer": "Havertz", "clock": "12'"}],
                "players": [{"player_name": "Havertz", "shots": 3}],
            }
        },
    )
    _write_aggregate(
        root,
        generated_at="2026-09-15T21:04:02+00:00",
        finals=[{
            "league": LEAGUE,
            "event_id": EVENT,
            "home_team": "Arsenal",
            "away_team": "Coventry City",
            "score_home": 2,
            "score_away": 0,
            "home_linescores": [1, 1],
            "away_linescores": [0, 0],
            "status_state": "post",
            "final": True,
        }],
    )
    box = cards._live_state_entry(LEAGUE, _today(), EVENT, "match_box")
    assert box is not None
    assert box["score_home"] == 2, "the final score never reached the box"
    assert box["status_state"] == "post"
    assert box["final"] is True
    assert box["goals"] == [{"scorer": "Havertz", "clock": "12'"}], "the goal list was dropped"
    assert box["players"], "the player box was dropped"


def test_a_box_the_per_league_file_never_had_is_still_reachable(root):
    """On refresh-worker the file can be missing the match entirely."""
    _write_per_league(root, generated_at="2026-09-15T20:07:50+00:00")
    _write_aggregate(
        root,
        generated_at="2026-09-15T21:04:02+00:00",
        finals=[{"league": LEAGUE, "event_id": EVENT, "score_home": 3,
                 "score_away": 1, "status_state": "post", "final": True}],
    )
    box = cards._live_state_entry(LEAGUE, _today(), EVENT, "match_box")
    assert box is not None and box["score_home"] == 3


def test_a_FRESHER_disk_copy_wins(root):
    """On live-odds-worker and on a dev box the per-league file IS the freshest.

    The overlay must be strictly-newer, or the service that WRITES the file
    would start reading its own stale echo.
    """
    _write_per_league(
        root,
        generated_at="2026-09-15T21:10:00+00:00",
        games={EVENT: _live_row(score_home=3, score_away=1, clock="90'")},
    )
    _write_aggregate(
        root,
        generated_at="2026-09-15T21:04:02+00:00",
        games=[_live_row(score_home=2, score_away=0, clock="67'")],
    )
    entry = cards._live_state_entry(LEAGUE, _today(), EVENT, "games")
    assert entry["score_home"] == 3, "an OLDER aggregate overwrote a fresher disk copy"


def test_a_CENTRAL_stamped_aggregate_is_not_read_as_stale(root):
    """The two stamps are not the same string for the same moment.

    `poll_league` writes the per-league file with a plain `write_text`, keeping
    UTC; the aggregate goes through `write_json_file` ->
    `normalize_timestamped_payload`, which rewrites `generated_at` into CENTRAL.
    A text comparison ranks `16:04:02-05:00` BELOW `20:07:50+00:00` while it is
    in fact 56 minutes later.
    """
    _write_per_league(
        root,
        generated_at="2026-09-15T20:07:50+00:00",
        games={EVENT: _live_row(score_home=0, score_away=0, clock="1'")},
    )
    _write_aggregate(
        root,
        generated_at="2026-09-15T16:04:02-05:00",
        games=[_live_row(score_home=2, score_away=0, clock="67'")],
    )
    entry = cards._live_state_entry(LEAGUE, _today(), EVENT, "games")
    assert entry["score_home"] == 2, "a Central-stamped aggregate was compared as text"


def test_a_snapshot_for_ANOTHER_DATE_is_refused(root):
    _write_per_league(
        root,
        generated_at="2026-09-15T20:07:50+00:00",
        games={EVENT: _live_row(score_home=1, score_away=0, clock="30'")},
    )
    _write_aggregate(
        root,
        generated_at="2026-09-15T21:04:02+00:00",
        games=[_live_row(score_home=2, score_away=0, clock="67'")],
        date="1999-01-01",
    )
    entry = cards._live_state_entry(LEAGUE, _today(), EVENT, "games")
    assert entry["score_home"] == 1, "yesterday's snapshot priced today's board"


def test_the_VINTAGE_moves_when_only_the_aggregate_moves(root):
    """The 600s cards cache is keyed on this. A vintage read from the per-league
    file while the entries come from the aggregate holds the cache closed over
    data that has already moved."""
    _write_per_league(
        root,
        generated_at="2026-09-15T20:07:50+00:00",
        games={EVENT: _live_row(score_home=0, score_away=0, clock="1'")},
    )
    _write_aggregate(
        root,
        generated_at="2026-09-15T21:04:02+00:00",
        games=[_live_row(score_home=1, score_away=0, clock="45'")],
    )
    first = cards._live_vintage(LEAGUE)
    _write_aggregate(
        root,
        generated_at="2026-09-15T21:06:02+00:00",
        games=[_live_row(score_home=2, score_away=0, clock="67'")],
    )
    second = cards._live_vintage(LEAGUE)
    assert first != second, "the chip cache key never saw the aggregate move"


def test_the_vintage_fingerprints_the_SCORE(root):
    """`score_home`/`score_away` are the only names a real entry carries.

    The fingerprint read `home_score`/`away_score` -- which `build_live_state`
    never writes -- so a goal inside one displayed minute changed nothing in the
    key whose entire job is to notice that the score moved.
    """
    _write_per_league(
        root,
        generated_at="2026-09-15T20:07:50+00:00",
        games={EVENT: _live_row(score_home=0, score_away=0, clock="45'")},
    )
    before = cards._live_vintage(LEAGUE)
    _write_per_league(
        root,
        generated_at="2026-09-15T20:08:50+00:00",
        games={EVENT: _live_row(score_home=1, score_away=0, clock="45'")},
    )
    after = cards._live_vintage(LEAGUE)
    assert before != after, "a goal at the same displayed clock left the key unchanged"


def test_no_aggregate_at_all_is_exactly_the_old_behaviour(root):
    """The aggregate is absent on a dev box and on a cold store. That must read
    as the per-league file, not as an empty board."""
    _write_per_league(
        root,
        generated_at="2026-09-15T20:07:50+00:00",
        games={EVENT: _live_row(score_home=1, score_away=1, clock="70'")},
    )
    payload = S.board_live_state_payload(LEAGUE, _today())
    assert payload is not None
    assert payload["games"][EVENT]["score_home"] == 1
    assert "source" not in payload, "an absent aggregate still claimed to be one"
