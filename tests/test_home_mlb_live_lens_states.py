"""home reads live scores from the published live lens, not from statsapi.

WHY NOT THE OBVIOUS FIX. The statsapi fan-out in `_mlb_feed_live_states` exists
only because `raw/statsapi/feed_live/**` is in none of the 175
`HOT_ARTIFACT_PATTERNS`, so the local read always misses on web. Allowlisting it
looks like the fix and is a regression: `_mlb_feed_live_payload` takes the file
if it EXISTS with no freshness check, so publishing it would freeze every game
at whatever inning it was captured. `board_enrichment.attach_live_game_state_
from_lens` measured exactly that on 2026-08-13 (`#413`) -- MIL @ SD reading
`live / TOP 9` against a lens reading Final, CLE @ DET reading `BOT 1` two hours
after first pitch. The pipeline says so about its own files too:
`vendor/mlb_bettingv2/tools/daily_update.py` re-fetches the PRIOR day because
"Prior-day reconciliation must fetch the final game feed, not a stale pregame
cache entry."

`live_lens_report_<date>.json` is already allowlisted, already republished ~60s,
and carries score, status, AND `gameLens[].progress.{inning,half,outs}` -- so
the status line is reconstructed, not degraded. Verified end to end against the
real 2026-06-01 report restamped to now: 9/9 games resolved, zero statsapi
calls, game 822974 -> `In Progress | Bottom 9th | 2 outs`, score 10-9.
"""

from __future__ import annotations

import json

from datetime import datetime, timedelta, timezone

from unittest.mock import patch

import pytest

from syndicate.blueprints import home as home_module


DATE = "2026-08-22"


def _report(games, *, generated_at=None, age_seconds=0.0):
    stamp = generated_at or (datetime.now(timezone.utc) - timedelta(seconds=age_seconds)).isoformat()
    return {"date": DATE, "generatedAt": stamp, "games": games}


def _game(game_pk, *, abstract="Live", detailed="In Progress", away=3, home=1, progress=None):
    row = {
        "gamePk": game_pk,
        "status": {"abstract": abstract, "detailed": detailed},
        "matchup": {"score": {"away": away, "home": home}},
    }
    if progress is not None:
        row["gameLens"] = [{"progress": progress}]
    return row


@pytest.fixture
def lens(tmp_path):
    """Writes a report at the real path and points home's reader at it."""
    path = tmp_path / f"live_lens_report_{DATE.replace('-', '_')}.json"

    def _write(report):
        path.write_text(json.dumps(report), encoding="utf-8")
        return path

    with patch.object(home_module, "live_lens_report_path", return_value=path):
        home_module._MLB_LIVE_LENS_STATES_CACHE.clear()
        yield _write
        home_module._MLB_LIVE_LENS_STATES_CACHE.clear()


def test_a_live_game_reconstructs_the_status_line_the_feed_would_have_built(lens):
    lens(_report([_game(1, progress={"inning": 9, "half": "bottom", "outs": 2})]))
    state = home_module._mlb_live_lens_states(DATE)[1]
    # Identical shape to `_mlb_feed_live_state`'s output, ordinal included --
    # a card served from the lens must not read differently from one served
    # from the feed. This is the half a naive lens swap would have lost.
    assert state["status"] == "In Progress | Bottom 9th | 2 outs"
    assert state == {
        "away_pts": 3,
        "home_pts": 1,
        "in_progress": True,
        "final": False,
        "status": "In Progress | Bottom 9th | 2 outs",
    }


def test_one_out_is_singular_like_the_feed_path(lens):
    lens(_report([_game(1, progress={"inning": 3, "half": "top", "outs": 1})]))
    assert home_module._mlb_live_lens_states(DATE)[1]["status"] == "In Progress | Top 3rd | 1 out"


def test_zero_outs_is_still_rendered(lens):
    # `outs == 0` is a real reading, and `if outs` would drop it.
    lens(_report([_game(1, progress={"inning": 1, "half": "top", "outs": 0})]))
    assert home_module._mlb_live_lens_states(DATE)[1]["status"] == "In Progress | Top 1st | 0 outs"


def test_a_game_with_no_progress_block_still_resolves(lens):
    lens(_report([_game(1)]))
    assert home_module._mlb_live_lens_states(DATE)[1]["status"] == "In Progress"


@pytest.mark.parametrize(
    "inning,expected",
    [(1, "1st"), (2, "2nd"), (3, "3rd"), (4, "4th"), (11, "11th"), (12, "12th"), (13, "13th"), (21, "21st")],
)
def test_inning_ordinals(inning, expected):
    assert home_module._mlb_inning_ordinal(inning) == expected


def test_warmup_is_not_live(lens):
    # `#98`/`#100`: StatsAPI reports abstract "Live" during warmup. The lens
    # copies that field, so this path has to delegate to the same canonical
    # predicate rather than reading `abstract` on its own.
    lens(_report([_game(1, abstract="Live", detailed="Warmup")]))
    state = home_module._mlb_live_lens_states(DATE)[1]
    assert state["in_progress"] is False
    assert state["final"] is False


def test_a_final_game_reads_final(lens):
    lens(_report([_game(1, abstract="Final", detailed="Final")]))
    state = home_module._mlb_live_lens_states(DATE)[1]
    assert state["final"] is True
    assert state["in_progress"] is False


def test_a_stale_report_resolves_nothing_rather_than_something_wrong(lens):
    # `#413`'s guard, reused verbatim in intent: a wedged lens must not freeze
    # home harder than the bug being fixed. {} means "fall through to the
    # network path", which is exactly today's behaviour.
    lens(_report(
        [_game(1)],
        age_seconds=home_module._MLB_LIVE_LENS_MAX_AGE_SECONDS + 60,
    ))
    assert home_module._mlb_live_lens_states(DATE) == {}


def test_a_report_just_inside_the_bound_is_used(lens):
    lens(_report([_game(1)], age_seconds=home_module._MLB_LIVE_LENS_MAX_AGE_SECONDS - 60))
    assert 1 in home_module._mlb_live_lens_states(DATE)


def test_a_missing_report_resolves_nothing(tmp_path):
    with patch.object(home_module, "live_lens_report_path", return_value=tmp_path / "nope.json"):
        home_module._MLB_LIVE_LENS_STATES_CACHE.clear()
        assert home_module._mlb_live_lens_states(DATE) == {}


def test_an_unparseable_report_resolves_nothing(lens, tmp_path):
    path = lens(_report([_game(1)]))
    path.write_text("{not json", encoding="utf-8")
    home_module._MLB_LIVE_LENS_STATES_CACHE.clear()
    assert home_module._mlb_live_lens_states(DATE) == {}


def test_the_cache_is_keyed_on_content_not_on_a_clock(lens):
    # An mtime+size key cannot serve a stale value, which is why this one needs
    # no TTL -- unlike `_MLB_FEED_LIVE_STATE_CACHE`. Rewriting the file must be
    # picked up on the very next read.
    lens(_report([_game(1, away=1, home=0)]))
    assert home_module._mlb_live_lens_states(DATE)[1]["away_pts"] == 1
    lens(_report([_game(1, away=7, home=0)]))
    assert home_module._mlb_live_lens_states(DATE)[1]["away_pts"] == 7


def test_apply_live_scores_makes_no_network_call_when_the_lens_covers_everything(lens):
    lens(_report([
        _game(1, away=4, home=2, progress={"inning": 7, "half": "top", "outs": 1}),
        _game(2, abstract="Final", detailed="Final", away=0, home=5),
    ]))

    def _must_not_run(*args, **kwargs):
        raise AssertionError("the statsapi fan-out ran despite full lens coverage")

    games = [
        {"gamePk": 1, "away": {}, "home": {}, "status": {}},
        {"gamePk": 2, "away": {}, "home": {}, "status": {}},
    ]
    with patch.object(home_module, "_mlb_feed_live_states", _must_not_run):
        enriched = home_module._apply_mlb_live_scores(games, DATE)

    assert enriched[0]["away"]["score"] == 4
    assert enriched[0]["status"]["detailed"] == "In Progress | Top 7th | 1 out"
    assert enriched[0]["status"]["is_live"] is True
    assert enriched[1]["status"]["is_final"] is True
    assert enriched[1]["home"]["score"] == 5


def test_only_the_games_the_lens_missed_reach_the_network_path(lens):
    lens(_report([_game(1, away=4, home=2)]))
    asked: list[list[int]] = []

    def _fan_out(game_pks, selected_date, **kwargs):
        asked.append(list(game_pks))
        return {pk: None for pk in game_pks}

    games = [
        {"gamePk": 1, "away": {}, "home": {}, "status": {}},
        {"gamePk": 2, "away": {}, "home": {}, "status": {}},
        {"gamePk": 3, "away": {}, "home": {}, "status": {}},
    ]
    with patch.object(home_module, "_mlb_feed_live_states", _fan_out):
        home_module._apply_mlb_live_scores(games, DATE)

    assert asked == [[2, 3]]


def test_a_stale_lens_sends_every_game_to_the_network_path(lens):
    lens(_report([_game(1)], age_seconds=home_module._MLB_LIVE_LENS_MAX_AGE_SECONDS + 60))
    asked: list[list[int]] = []

    def _fan_out(game_pks, selected_date, **kwargs):
        asked.append(list(game_pks))
        return {pk: None for pk in game_pks}

    games = [{"gamePk": 1, "away": {}, "home": {}, "status": {}}]
    with patch.object(home_module, "_mlb_feed_live_states", _fan_out):
        home_module._apply_mlb_live_scores(games, DATE)

    assert asked == [[1]]


def test_callers_cannot_reach_into_the_cached_lens_state(lens):
    # The parsed states are held across requests on an mtime key, and
    # `_apply_mlb_live_scores` assigns one onto a game dict bound for templates.
    lens(_report([_game(1, away=4, home=2)]))
    games = [{"gamePk": 1, "away": {}, "home": {}, "status": {}}]
    with patch.object(home_module, "_mlb_feed_live_states", lambda *a, **k: {}):
        first = home_module._apply_mlb_live_scores(games, DATE)
        first[0]["live_state"]["away_pts"] = 999
        second = home_module._apply_mlb_live_scores(games, DATE)
    assert second[0]["live_state"]["away_pts"] == 4


# ---------------------------------------------------------------------------
# A SLIM ROW IS NOT COVERAGE
#
# Every row below is copied from the report production actually served on
# 2026-08-26 -- both shapes, same game (`gamePk` 823096, PHI @ SEA), 3m13s
# apart:
#
#     22:32:56-05:00  SLIM  {gamePk, startTime, status}           15 of 15 rows
#     22:36:09-05:00  FULL  20 keys incl. matchup.score/gameLens  15 of 15 rows
#
# `live_lens_report_<date>.json` has TWO writers. `live_lens_loop` writes the
# full shape; `scripts/refresh_mlb_oddsapi.py` fetches with `slim=on` and
# publishes the slim shape over the same path -- its own docstring says
# "always the slim shape ... {gamePk, startTime, status} only". They alternate,
# and the slim writer was measured putting a report generated 2m38s EARLIER
# over a newer full one.
#
# While the slim copy was current, EVERY live MLB game chip on the Layer 2
# board strip read `0-0` with a bare `LIVE`/`FINAL` token -- 6 of 8 non-pregame
# games, on both the `worker_artifact` and the `inline_artifact_stale` serve
# path. While the full copy was current, all 8 matched StatsAPI exactly.
#
# The verification behind `368c7ef0` used the real 2026-06-01 report restamped
# to now. That report was FULL. The fixture picked the path production only
# takes half the time.
# ---------------------------------------------------------------------------


SLIM_LIVE_ROW = {"gamePk": 823096, "startTime": "3:10 PM", "status": {"abstract": "Live", "detailed": "In Progress"}}
SLIM_FINAL_ROW = {"gamePk": 824234, "startTime": "12:10 PM", "status": {"abstract": "Final", "detailed": "Final"}}
SLIM_PREGAME_ROW = {"gamePk": 823506, "startTime": "6:05 PM", "status": {"abstract": "Preview", "detailed": "Pre-Game"}}


def test_a_slim_live_row_is_not_treated_as_coverage(lens):
    # The defect. This used to resolve to a state that was non-None and empty
    # of everything that matters -- `away_pts`/`home_pts` None, no inning --
    # which the consumer contract reads as "the lens covers this game".
    lens(_report([SLIM_LIVE_ROW]))
    assert home_module._mlb_live_lens_states(DATE) == {}


def test_a_slim_final_row_is_not_treated_as_coverage(lens):
    lens(_report([SLIM_FINAL_ROW]))
    assert home_module._mlb_live_lens_states(DATE) == {}


def test_a_slim_pregame_row_is_still_coverage(lens):
    # A pregame row has nothing to report and the lens genuinely covers it.
    # Refusing these as well would send a full evening's pregame slate to
    # statsapi for an answer that is already correct.
    lens(_report([SLIM_PREGAME_ROW]))
    state = home_module._mlb_live_lens_states(DATE)[823506]
    assert state["in_progress"] is False
    assert state["final"] is False


def test_a_live_row_carrying_only_a_score_is_still_coverage(lens):
    # `test_a_game_with_no_progress_block_still_resolves` above, restated as
    # the boundary this refusal must not cross: a score alone is an answer.
    lens(_report([_game(1, away=0, home=0)]))
    assert home_module._mlb_live_lens_states(DATE)[1]["away_pts"] == 0


def test_a_slim_slate_sends_every_live_game_to_the_network_path(lens):
    # End to end, on the measured symptom: score and inning back on the game
    # dict the chip strip is built from.
    lens(_report([SLIM_LIVE_ROW]))
    seen = {}

    def _fan_out(game_pks, selected_date, **kwargs):
        seen["pks"] = list(game_pks)
        return {
            823096: {
                "away_pts": 6,
                "home_pts": 0,
                "in_progress": True,
                "final": False,
                "status": "In Progress | Bottom 9th | 0 outs",
            }
        }

    games = [{"gamePk": 823096, "away": {}, "home": {}, "status": {}}]
    with patch.object(home_module, "_mlb_feed_live_states", _fan_out):
        enriched = home_module._apply_mlb_live_scores(games, DATE)

    # Before the fix this list was empty -- the slim row counted as coverage,
    # so the fan-out was never entered for any game on the slate.
    assert seen["pks"] == [823096]
    assert enriched[0]["away"]["score"] == 6
    assert enriched[0]["home"]["score"] == 0
    assert enriched[0]["status"]["detailed"] == "In Progress | Bottom 9th | 0 outs"


def test_a_live_game_with_neither_score_reported_is_not_rendered_as_nil_nil(lens):
    # Belt-and-braces behind the row-level refusal, and the general rule: the
    # zero-fill is sound only while the OTHER side proves the source actually
    # reported this game. With nothing reported, `0-0` is a fabrication; an
    # unset score renders "-", which is honestly "unknown".
    state = {"away_pts": None, "home_pts": None, "in_progress": True, "final": False, "status": "In Progress"}
    games = [{"gamePk": 7, "away": {}, "home": {}, "status": {}}]
    with patch.object(home_module, "_mlb_live_lens_states", return_value={7: state}), patch.object(
        home_module, "_mlb_feed_live_states", return_value={}
    ):
        enriched = home_module._apply_mlb_live_scores(games, DATE)
    assert "score" not in enriched[0]["away"]
    assert "score" not in enriched[0]["home"]


def test_one_side_reported_still_zero_fills_the_other(lens):
    # The case the zero-fill was written for, which must keep working:
    # StatsAPI returns a real number for one side and null for the other.
    state = {"away_pts": 4, "home_pts": None, "in_progress": True, "final": False, "status": "In Progress"}
    games = [{"gamePk": 7, "away": {}, "home": {}, "status": {}}]
    with patch.object(home_module, "_mlb_live_lens_states", return_value={7: state}), patch.object(
        home_module, "_mlb_feed_live_states", return_value={}
    ):
        enriched = home_module._apply_mlb_live_scores(games, DATE)
    assert enriched[0]["away"]["score"] == 4
    assert enriched[0]["home"]["score"] == 0
