"""An NBA game still live at midnight Central keeps its live PROP numbers on the board (#777, lane
nba-live-props-midnight; the game-line half is #776).

Measured 2026-11-10 on the fleet's refresh-worker logs: after the 11-05 and 11-07 rolls the carryover build of the
previous date still had its NBA rows (`LIVE_GAMELINE_JOIN sport=nba considered=403` / 396), and every
`LIVE_PROJECTION_JOIN sport=nba` read `considered=None reason=live-lens snapshot for nba carries no liveProps
(producer not wired)` until the game ended; the joins just before the roll projected 86-128 and 55-299 prop rows.

The chain below is the production one, with only ESPN, the engine's draws and the keyvalue store faked: the re-sim
tick the loop runs (`run_live_resim_tick`, no date) publishes the previous date's game with a REAL `liveProps` row;
the page lens's builder (`build_live_lens_snapshot`, the call the live-lens loop makes) carries it; the board's own
props join (`attach_live_projections_for_sport`) on the CARRYOVER date projects it; web's read-time refresh
refreshes it. The switch is the re-sim's own env, read from the ENV (off != on).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from syndicate.features.nba import live_lens as lens
from syndicate.features.nba import live_resim as lr
from tests.test_nba_live_resim_midnight import PRE_ROLL, PRIOR, ROLL_PLUS_3, TODAY, MORNING, _board, fleet  # noqa: F401

PLAYER = "H1"            # the synthetic box's home starter (`tests/basketball_pbp_fixtures.py`), 0 points banked
LINE = 15.5
# Remainder draws 10 / 20 points: P(over 15.5) = 0.5, Live proj. 15.0 -- a priced row, not a certainty refusal.
RESULT = {"sims_run": 200, "home_win_prob": 0.6, "total_mean": 228.0, "home_margin_mean": 4.0,
          "total_dist": {"228": 200}, "margin_dist": {"4": 200}, "segments": {},
          "player_remainders": {"home": {PLAYER: {"pts": {"10": 100, "20": 100}}}, "away": {}}}
TODAYS_CARDS = [{"event_id": "T1", "status": "Scheduled", "live_state": {"in_progress": False, "final": False}}]


@pytest.fixture
def chain(fleet, monkeypatch, tmp_path):  # noqa: F811 -- the imported fixture
    """`fleet` (ESPN by date, the engine's draws and the keyvalue store faked) plus the readers that bind
    `read_json_file` at import, and a clock for the lens's window check."""
    import syndicate.blueprints.intelligence as bp
    import syndicate.features.shared.refresh_state_store as store

    monkeypatch.delenv("SYNDICATE_NBA_LIVE_PRICED", raising=False)
    monkeypatch.setattr(lr, "resim_live_game", lambda *_a, **_k: json.loads(json.dumps(RESULT)))
    fleet["lines"] = {(lr.normalize_name(PLAYER), "pts"): (LINE,)}
    monkeypatch.setattr(lens, "read_json_file", store.read_json_file)
    monkeypatch.setattr(bp, "read_json_file", store.read_json_file)
    bp._LENS_PROP_INDEX_CACHE.clear()
    clock = {"now": ROLL_PLUS_3}
    real_prior_slate_date = lr.prior_slate_date
    monkeypatch.setattr(lr, "prior_slate_date",
                        lambda now=None, **k: real_prior_slate_date(now or clock["now"], **k))
    fleet.update(clock=clock, lens_key=str(tmp_path / "live" / "nba_live_lens.json"), bp=bp)
    yield fleet
    bp._LENS_PROP_INDEX_CACHE.clear()


def _games_after_merge(chain, lens_date: str = TODAY) -> tuple[list[dict], dict]:
    games = [dict(g) for g in TODAYS_CARDS]
    info = lens._attach_native_resim(games, lens_date)
    return games, info


def _publish_lens(chain, games: list[dict], lens_date: str = TODAY) -> dict:
    snapshot = {"ok": True, "date": lens_date, "generated_at": "2026-11-07T00:03:30-06:00", "games": games}
    chain["store"][chain["lens_key"]] = json.loads(json.dumps(snapshot))
    return snapshot


def _carryover_row(**overrides) -> dict:
    """A live prop row on the CARRYOVER board (the previous date), as the board join sees it."""
    row = {"kind": "prop", "game": {"state": "live"}, "player_name": PLAYER, "market": "player_points",
           "line": LINE, "side": "over", "sport": "nba"}
    row.update(overrides)
    return row


def _board_join(chain, grid: list[dict]) -> dict:
    from syndicate.features.shared.board_enrichment import attach_live_projections_for_sport

    return attach_live_projections_for_sport(grid, sport="nba", selected_date=PRIOR)


# ------------------------------------------------------------------ the producer's real row reaches the lens

def test_the_resim_publishes_a_real_priced_prop_for_the_previous_dates_game(chain):
    """Precondition, so nothing below is joining a row the producer could never emit."""
    chain["boards"]["20261106"] = _board(("P", "in"))
    chain["tick"](ROLL_PLUS_3)
    game = chain["published"]()["games"][0]
    assert game["slateDate"] == PRIOR and game["event_id"] == "P"
    # The posted line plus its neighbours (`with_neighbour_lines`), all the same player and market.
    assert {(p["playerName"], p["prop"]) for p in game["liveProps"]} == {(PLAYER, "player_points")}
    prop = next(p for p in game["liveProps"] if p["line"] == LINE)
    assert prop["liveModelProbOver"] == 0.5 and prop["liveProjection"] == 15.0 and prop["actualSoFar"] == 0.0


def _published_prop_rows(chain) -> int:
    return len(chain["published"]()["games"][0]["liveProps"])


def test_off_and_on_differ_through_the_env_at_the_lens(chain, monkeypatch, capsys):
    chain["boards"]["20261106"] = _board(("P", "in"))
    chain["tick"](ROLL_PLUS_3)

    on_games, on = _games_after_merge(chain)
    assert [g["event_id"] for g in on_games] == ["T1", "P"]          # today's order unchanged, the prior game after it
    prior = on_games[1]
    assert prior["slateDate"] == PRIOR and prior["status"] == "Live" and prior["liveProps"][0]["playerName"] == PLAYER
    assert prior["gameLens"][0]["source"] == lr.LIVE_RESIM_LENS_SOURCE
    resim_row = chain["published"]()["games"][0]
    assert {k: prior[k] for k in lens._PRIOR_SLATE_IDENTITY_KEYS} == {k: resim_row[k] for k in lens._PRIOR_SLATE_IDENTITY_KEYS}
    assert (prior["home_name"], prior["away_name"]) == ("Golden State Warriors", "New York Knicks")
    assert on["merged"] == 0 and "liveProps" not in on_games[0]
    rows = _published_prop_rows(chain)
    assert prior["liveProps"] == chain["published"]()["games"][0]["liveProps"]     # verbatim, every row
    assert on["prior_slate"] == {"date": PRIOR, "games": 1, "live": 1, "with_live_props": 1, "live_props": rows,
                                 "dropped_also_today": 0}
    line = [ln for ln in capsys.readouterr().out.splitlines() if "PRIOR_SLATE_ATTACHED" in ln]
    assert line and f"date={TODAY} prior_date={PRIOR} games=1 live=1 with_live_props=1 live_props={rows}" in line[-1]

    monkeypatch.setenv(lr.PRIOR_DATE_HOURS_ENV, "0")
    off_games, off = _games_after_merge(chain)
    assert [g["event_id"] for g in off_games] == ["T1"] and off["prior_slate"] is None
    assert "PRIOR_SLATE_ATTACHED" not in capsys.readouterr().out


def test_off_and_on_differ_through_the_env_at_the_carryover_boards_join(chain, monkeypatch):
    """The hop that read `considered=None` on the fleet: the board's own props join, on the carryover date, over the
    published lens."""
    chain["boards"]["20261106"] = _board(("P", "in"))
    chain["tick"](ROLL_PLUS_3)
    _publish_lens(chain, _games_after_merge(chain)[0])
    grid = [_carryover_row()]
    on = _board_join(chain, grid)
    assert on["rows_live_considered"] == 1 and on["rows_live_projected"] == 1
    assert on["snapshot_rows_indexed"] == _published_prop_rows(chain) and on["live_games_in_snapshot"] == 1
    assert grid[0]["projection"]["live_projected"] == 15.0

    monkeypatch.setenv(lr.PRIOR_DATE_HOURS_ENV, "0")
    _publish_lens(chain, _games_after_merge(chain)[0])
    off = _board_join(chain, [_carryover_row()])
    # Exactly what the fleet printed after the 11-05 / 11-07 rolls.
    assert off.get("rows_live_considered") is None and off["rows_live_projected"] == 0
    assert off["reason"] == "live-lens snapshot for nba carries no liveProps (producer not wired)"


def test_the_whole_lens_builder_carries_it_and_the_snapshot_still_validates(chain, monkeypatch):
    """`build_live_lens_snapshot` -- the call the live-lens loop makes for `central_today_iso()` -- with the new
    date's cards context stubbed (no prior-date cards build happens: nothing else is called)."""
    chain["boards"]["20261106"] = _board(("P", "in"))
    chain["tick"](ROLL_PLUS_3)
    calls: list[str] = []

    def cards(date, **_k):
        calls.append(date)
        return {"date": date, "games": [dict(g) for g in TODAYS_CARDS]}

    monkeypatch.setattr(lens, "_run_nba_live_lens_tick", lambda d: calls.append(f"tick:{d}"))
    monkeypatch.setattr(lens, "_compute_cards_page_context", cards)
    monkeypatch.setattr(lens, "_compute_live_lens_page_context", lambda d, **_k: {"games": [], "rank_cards": []})
    monkeypatch.setattr(lens, "_compute_live_lens_api_payload", lambda d, **_k: {"games": [], "generated_at": "g"})
    for name in ("_compute_live_player_lens_payload", "_compute_live_lines_payload", "_compute_live_pbp_stats_payload"):
        monkeypatch.setattr(lens, name, lambda d, ids, **_k: {"date": d, "games": []})
    snapshot = lens.build_live_lens_snapshot(TODAY)
    assert calls == [f"tick:{TODAY}", TODAY]                                    # the new date only
    assert lens.validate_live_lens_snapshot(snapshot)
    assert snapshot["date"] == TODAY and [g["event_id"] for g in snapshot["games"]] == ["T1", "P"]
    assert snapshot["native_resim"]["prior_slate"]["with_live_props"] == 1
    chain["store"][chain["lens_key"]] = json.loads(json.dumps(snapshot))
    assert _board_join(chain, [_carryover_row()])["rows_live_projected"] == 1


# ------------------------------------------------------------------ bounded: the window, the date, today's merge

def test_outside_the_window_nothing_is_carried_and_the_key_says_so(chain):
    chain["boards"]["20261106"] = _board(("P", "in"))
    chain["tick"](ROLL_PLUS_3)                       # a snapshot with a prior row, read after the window closed
    for now in (MORNING, datetime(2026, 11, 7, 10, 0, tzinfo=timezone.utc)):  # 9:00 AM CST, 4:00 AM CST exactly
        chain["clock"]["now"] = now
        games, info = _games_after_merge(chain)
        assert [g["event_id"] for g in games] == ["T1"] and info["prior_slate"] is None and "reason" not in info


def test_a_lens_for_any_other_date_never_takes_the_previous_dates_rows(chain):
    chain["boards"]["20261106"] = _board(("P", "in"))
    chain["tick"](ROLL_PLUS_3)
    games, info = _games_after_merge(chain, lens_date="2026-11-08")
    assert info["reason"] == "native_resim_snapshot_other_date" and [g["event_id"] for g in games] == ["T1"]
    games, info = _games_after_merge(chain, lens_date=PRIOR)   # the re-sim file is TODAY's: refused as before
    assert info["reason"] == "native_resim_snapshot_other_date"
    assert lens._prior_slate_for_lens("not-a-date") is None


def test_the_pre_midnight_resim_file_feeds_the_previous_date_until_the_resims_first_tick(chain):
    """For a few minutes after 00:00 CT the re-sim file is still the 11:59 PM one (date = the previous day, no
    `slateDate`). Every row in it is the previous date's; outside the window it is refused as before."""
    chain["boards"]["20261106"] = _board(("P", "in"))
    chain["tick"](PRE_ROLL)
    assert chain["published"]()["date"] == PRIOR and "slateDate" not in chain["published"]()["games"][0]
    games, info = _games_after_merge(chain)
    assert [g["event_id"] for g in games] == ["T1", "P"] and games[1]["slateDate"] == PRIOR
    assert info["prior_slate"]["with_live_props"] == 1
    chain["clock"]["now"] = MORNING
    assert _games_after_merge(chain)[1]["reason"] == "native_resim_snapshot_other_date"


def test_todays_merge_is_unchanged_and_a_prior_row_never_lands_on_a_todays_card(chain, monkeypatch):
    resim = {"date": TODAY, "generatedAt": "g", "refusalsByReason": {}, "games": [
        {"event_id": "T1", "status": {"detailedState": "In Progress"}, "gameLens": [{"source": "live_resim"}],
         "liveProps": [{"playerName": "Today Guy"}]},
        # An event on both dates' scoreboards: the re-sim's own merge keeps today's row, so a prior-stamped copy is
        # not expected -- but if one came, it must neither overwrite today's card nor appear twice.
        {"event_id": "T1", "slateDate": PRIOR, "status": {"detailedState": "In Progress"},
         "liveProps": [{"playerName": "Wrong Night"}]},
    ]}
    monkeypatch.setattr(lens, "read_json_file", lambda _p: resim)
    games, info = _games_after_merge(chain)
    assert [g["event_id"] for g in games] == ["T1"] and games[0]["liveProps"] == [{"playerName": "Today Guy"}]
    assert info["merged"] == 1 and info["prior_slate"]["games"] == 0 and info["prior_slate"]["dropped_also_today"] == 1


def test_a_refused_prior_row_is_carried_as_unknown_never_as_live(chain, monkeypatch):
    resim = {"date": TODAY, "generatedAt": "g", "refusalsByReason": {"no_pregame_inputs": 1}, "games": [
        {"event_id": "P", "slateDate": PRIOR, "home_name": "H", "away_name": "A",
         "status": {"detailedState": "Unknown"}, "gameLens": [{"source": "pregame_only"}]}]}
    monkeypatch.setattr(lens, "read_json_file", lambda _p: resim)
    games, info = _games_after_merge(chain)
    assert games[1]["status"] == "Unknown" and "liveProps" not in games[1]
    assert (info["prior_slate"]["live"], info["prior_slate"]["with_live_props"]) == (0, 0)


# ------------------------------------------------------------------ web's read-time refresh

def _web_row(**overrides) -> dict:
    row = {"sport": "nba", "sport_slug": "nba", "is_live": True, "game_date": PRIOR, "player_name": PLAYER,
           "market": "player_points", "line": LINE, "side": "over"}
    row.update(overrides)
    return row


def test_off_and_on_differ_through_the_env_at_webs_read_time_refresh(chain, monkeypatch):
    chain["boards"]["20261106"] = _board(("P", "in"))
    chain["tick"](ROLL_PLUS_3)
    _publish_lens(chain, _games_after_merge(chain)[0])
    payload = {"ranked_all": [_web_row(), _web_row(game_date="2026-11-05")]}
    counts = chain["bp"]._refresh_lens_prop_live_columns(payload)
    assert payload["ranked_all"][0]["live_projection"] == 15.0 and payload["ranked_all"][0]["actual"] == 0.0
    assert counts["nba"] == {"considered": 2, "matched": 1, "refreshed": 1, "no_lens_for_date": 1}

    monkeypatch.setenv(lr.PRIOR_DATE_HOURS_ENV, "0")
    chain["bp"]._LENS_PROP_INDEX_CACHE.clear()
    _publish_lens(chain, _games_after_merge(chain)[0])
    payload = {"ranked_all": [_web_row()]}
    counts = chain["bp"]._refresh_lens_prop_live_columns(payload)
    assert "live_projection" not in payload["ranked_all"][0]
    assert counts["nba"]["no_lens_for_date"] == 1 and counts["nba"]["matched"] == 0


def test_webs_index_without_slate_dates_still_matches_its_own_date(chain, monkeypatch):
    """An index built without `lens_slate_dates` (a test double, or a mid-deploy copy) keeps the old rule."""
    bp = chain["bp"]
    from syndicate.features.shared.live_projection_join import build_live_prop_index

    indexed = build_live_prop_index({"games": [{"status": "Live", "liveProps": [
        {"playerName": PLAYER, "prop": "player_points", "line": LINE, "liveProjection": 12.0,
         "liveModelProbOver": 0.4, "actualSoFar": 3.0}]}]})
    indexed["lens_date"] = TODAY
    monkeypatch.setattr(bp, "_lens_prop_index", lambda sport, **_k: indexed)
    payload = {"ranked_all": [_web_row(game_date=TODAY), _web_row()]}
    counts = bp._refresh_lens_prop_live_columns(payload)
    assert payload["ranked_all"][0]["live_projection"] == 12.0 and "live_projection" not in payload["ranked_all"][1]
    assert counts["nba"]["no_lens_for_date"] == 1
