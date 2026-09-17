"""`bet_status_nhl` -- NHL orders resolved from the NHL's own API (api-web.nhle.com).

Every `tests/fixtures/nhl_settlement/` payload is TRIMMED FROM A REAL RESPONSE fetched
2026-09-17 (keys and games removed, no value changed). The two sides of every join come from
independent sources:

    orders  built by the REAL row code (`local_nhl_odds._append_nhl_book_quotes`) from the
            OddsAPI rows the NHL collector wrote for 2026-06-06, trimmed from the tracked
            mirror blobs `data/nhl_source/data/odds/team/date=2026-06-06/oddsapi.csv` and
            `.../props/player_props_lines/date=2026-06-06/oddsapi.csv`: OddsAPI team names,
            OddsAPI player names, display market codes (SOG / GOALS / ...).
    results the NHL API: `/score/<date>`, `/gamecenter/<id>/{boxscore,right-rail,play-by-play}`.

    2025030413  CAR 4 @ VGK 5, 2OT (Stanley Cup Final G3, 2026-06-06) -- the odds rows' game.
    2025020549  PHI 4 @ NYR 5, SHOOTOUT (2025-12-20). No OddsAPI rows exist for it in the repo,
                so its orders carry OddsAPI's naming convention ("New York Rangers") typed in;
                the join still runs through the repo's alias map against the API's `abbrev`.
    2025010008  PHI 3 @ NYI 2, SHOOTOUT, PRESEASON (2025-09-21), on a slate with FLA @ NSH twice
                (split squads, 19:00Z and 23:00Z) and CGY @ EDM + EDM @ CGY both at 00:00Z.
    2026-09-19  the real upcoming preseason slate, every game FUT (MTL @ TOR and TOR @ MTL both
                23:00Z).

HAND-VERIFIED against the raw payloads before any assertion was written:
    2025030413 linescore  [P1 0-0, P2 0-4, P3 4-0, OT 0-0, OT 0-1] (away-home), totals 4-5:
               regulation 4-4 (the 3-way DRAW), final total 9, VGK by one in double OT.
    Mitch Marner (2025030413 box, playerId via rosterSpots "Mitch" "Marner"):
               goals 3, assists 1, points 4, sog 10, toi 27:00.
    Carter Hart saves 29 (toi 85:38); Adin Hill toi 00:00 (dressed, did not play).
    2025020549 score NYR 5 PHI 4, byPeriod [0-1, 4-1, 0-2, OT 0-0, SO 0-1]; NYR skaters' goals
               sum to 4; Artemi Panarin box goals 2 and he scored the shootout winner
               (`landing.summary.shootout`), so his 2 EXCLUDES the shootout goal.
"""

from __future__ import annotations

import copy
import csv
import json
import math
import pathlib
from urllib.parse import urlsplit

import pytest

from syndicate.features.shared import bet_status_nhl as nhl
from syndicate.features.shared.bet_status import STATUS_LIVE_TIED, STATUS_LOST, STATUS_WON, resolve_bet_status

FIX = pathlib.Path(__file__).resolve().parent / "fixtures" / "nhl_settlement"


class FakeNhle:
    """api-web.nhle.com from the fixtures. Records every URL; an unknown path is a failed read."""

    def __init__(self, overrides: dict | None = None) -> None:
        self.urls: list[str] = []
        self.overrides = overrides or {}

    def __call__(self, url: str):
        self.urls.append(url)
        path = urlsplit(url).path
        assert path.startswith("/v1/"), url
        name = path[len("/v1/"):].replace("/", "_") + ".json"
        if name in self.overrides:
            return copy.deepcopy(self.overrides[name])
        target = FIX / name
        return json.loads(target.read_text(encoding="utf-8")) if target.is_file() else None


def _nan_to_none(value):
    return None if isinstance(value, float) and math.isnan(value) else value


def board_rows(monkeypatch) -> list[dict]:
    """The 2026-06-06 OddsAPI rows, shaped by the REAL quote-row code into board rows."""
    pd = pytest.importorskip("pandas")
    from syndicate import local_nhl_odds
    from syndicate.features.shared import odds_book_quotes

    captured: list[dict] = []
    monkeypatch.setattr(odds_book_quotes, "append_book_quotes", lambda **kwargs: captured.extend(kwargs["rows"]))

    with (FIX / "oddsapi_team_odds_2026-06-06.csv").open(encoding="utf-8") as handle:
        team = list(csv.DictReader(handle))
    game = team[0]
    team_frame = pd.DataFrame([
        {
            "event_id": row["event_id"], "commence_time": row["commence_time"],
            "home_team": row["home"], "away_team": row["away"], "bookmaker_key": row["bookmaker_key"],
            "market": row["market"], "outcome_name": row["outcome_name"],
            "outcome_price": float(row["outcome_price"]),
            "outcome_point": float(row["outcome_point"]) if row["outcome_point"] else None,
        }
        for row in team
    ])
    local_nhl_odds._append_nhl_book_quotes(team_frame, date="2026-06-06", kind="game")

    with (FIX / "oddsapi_props_lines_2026-06-06.csv").open(encoding="utf-8") as handle:
        lines = list(csv.DictReader(handle))
    # The collector's RAW frame (`collect_oddsapi_props`): one row per side, carrying the event.
    prop_frame = pd.DataFrame([
        {
            "market": row["market"], "player": row["player_name"], "line": float(row["line"]),
            "odds": float(row[f"{side.lower()}_price"]), "side": side, "book": row["book"],
            "event_id": game["event_id"], "commence_time": game["commence_time"],
            "home_team": game["home"], "away_team": game["away"],
        }
        for row in lines
        for side in ("OVER", "UNDER")
    ])
    local_nhl_odds._append_nhl_book_quotes(prop_frame, date="2026-06-06", kind="prop")
    assert captured, "the real row code produced nothing"
    return [
        {
            "sport": "nhl", "event_id": row["event_id"], "market": row["market"], "segment": row["segment"],
            "side": row["selection"], "line": _nan_to_none(row["line"]), "player_name": row["player_name"],
            "home_team": row["home_team"], "away_team": row["away_team"],
            "commence_time": row["commence_time"], "price": row["price"], "bookmaker": row["bookmaker"],
        }
        for row in captured
    ]


def pick(rows, *, market, side, line=None, player=None, book=None):
    found = [
        row for row in rows
        if row["market"] == market and row["side"] == side and (player is None or row["player_name"] == player)
        and (line is None or row["line"] == line) and (book is None or row["bookmaker"] == book)
    ]
    assert len(found) == 1, (market, side, line, player, book, len(found))
    return dict(found[0])


def verdict(resolved: dict, order: dict) -> str | None:
    """What `paper_settlement._our_verdict` asks `resolve_bet_status`, at the final."""
    assert not resolved.get("unavailable_reason"), resolved
    status = resolve_bet_status(
        market=order.get("market"),
        side=resolved.get("side", order.get("side")),
        line=resolved.get("line", order.get("line")),
        current_value=resolved.get("current_value"),
        is_final=bool(resolved.get("is_final")),
        started=bool(resolved.get("started", True)),
    )
    assert status["decided"], (status, resolved)
    return status["status"]


def resolver(fake=None, selected_date="2026-06-06"):
    feed = nhl.NhlFeed(fetch_json=fake or FakeNhle())
    return lambda order: nhl.resolve_nhl_order(order, feed, selected_date)


SO_GAME = {"sport": "nhl", "home_team": "New York Rangers", "away_team": "Philadelphia Flyers",
           "commence_time": "2025-12-20T17:30:00Z", "event_id": "oddsapi-hash-not-used"}
PRESEASON = {"sport": "nhl", "home_team": "New York Islanders", "away_team": "Philadelphia Flyers",
             "commence_time": "2025-09-21T23:00:00Z"}


# ---------------------------------------------------------------------------
# the feed as measured
# ---------------------------------------------------------------------------


def test_the_final_credits_the_shootout_winner_and_player_goals_do_not():
    games = nhl.parse_score_games(json.loads((FIX / "score_2025-12-20.json").read_text(encoding="utf-8")))
    so = next(game for game in games if game["game_id"] == "2025020549")
    assert (so["home_abbr"], so["home_score"], so["away_abbr"], so["away_score"]) == ("NYR", 5, "PHI", 4)
    assert so["last_period_type"] == "SO"
    box = nhl.parse_boxscore_players(json.loads((FIX / "gamecenter_2025020549_boxscore.json").read_text(encoding="utf-8")))
    nyr_goals = sum(row["goals"] for row in box["players"] if row["team_abbr"] == "NYR" and row["role"] == "skater")
    assert nyr_goals == 4
    linescore = nhl.parse_linescore(json.loads((FIX / "gamecenter_2025020549_right-rail.json").read_text(encoding="utf-8")))
    assert [(p["type"], p["away"], p["home"]) for p in linescore["periods"]] == [
        ("REG", 0, 1), ("REG", 4, 1), ("REG", 0, 2), ("OT", 0, 0), ("SO", 0, 1)]


def test_default_fetch_sends_a_user_agent(monkeypatch):
    """The feed answers urllib's default agent with 403 (measured 2026-09-17)."""
    import urllib.request

    seen = {}

    def fake_urlopen(request, timeout=None):
        seen["agent"] = request.get_header("User-agent")
        seen["timeout"] = timeout
        raise OSError("offline")

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    assert nhl._default_fetch_json("https://api-web.nhle.com/v1/score/2025-12-20") is None
    assert seen["agent"] and "urllib" not in seen["agent"].lower()
    assert seen["timeout"] and seen["timeout"] <= 15


# ---------------------------------------------------------------------------
# game lines
# ---------------------------------------------------------------------------


def test_moneyline_puck_line_and_total_include_overtime(monkeypatch):
    rows = board_rows(monkeypatch)
    resolve = resolver()
    home_ml = pick(rows, market="h2h", side="home", book="draftkings")
    away_ml = pick(rows, market="h2h", side="away", book="draftkings")
    assert home_ml["home_team"] == "Vegas Golden Knights" and home_ml["line"] is None
    assert verdict(resolve(home_ml), home_ml) == STATUS_WON
    assert verdict(resolve(away_ml), away_ml) == STATUS_LOST
    resolved = resolve(home_ml)
    assert (resolved["home_score"], resolved["away_score"], resolved["nhl_game_id"]) == (5.0, 4.0, "2025030413")

    # Puck line, both directions, as the books quoted them that night. VGK won by ONE, in 2OT.
    assert verdict(resolve(o := pick(rows, market="spreads", side="away", line=-1.5)), o) == STATUS_LOST
    assert verdict(resolve(o := pick(rows, market="spreads", side="home", line=1.5)), o) == STATUS_WON
    assert verdict(resolve(o := pick(rows, market="spreads", side="away", line=1.5)), o) == STATUS_WON
    assert verdict(resolve(o := pick(rows, market="spreads", side="home", line=-1.5)), o) == STATUS_LOST
    # 9 goals, the overtime winner included.
    assert verdict(resolve(o := pick(rows, market="totals", side="over", line=5.5)), o) == STATUS_WON
    assert verdict(resolve(o := pick(rows, market="totals", side="under", line=5.5)), o) == STATUS_LOST
    assert verdict(resolve(o := pick(rows, market="totals", side="over", line=6.0)), o) == STATUS_WON


def test_shootout_winner_takes_moneyline_puck_line_and_total():
    resolve = resolver(selected_date="2025-12-20")
    # A TEAM-NAME side is translated through the NHL map (`canonical_team` knows no NHL club).
    nyr = {**SO_GAME, "market": "h2h", "side": "New York Rangers"}
    assert verdict(resolve(nyr), nyr) == STATUS_WON
    phi = {**SO_GAME, "market": "h2h", "side": "away"}
    assert verdict(resolve(phi), phi) == STATUS_LOST
    # Won by the shootout's single credited goal: +1.5 covers, -1.5 does not.
    assert verdict(resolve(o := {**SO_GAME, "market": "spreads", "side": "away", "line": 1.5}), o) == STATUS_WON
    assert verdict(resolve(o := {**SO_GAME, "market": "spreads", "side": "home", "line": -1.5}), o) == STATUS_LOST
    # 8 goals in play, 9 on the official final: the shootout goal decides an 8.5.
    assert verdict(resolve(o := {**SO_GAME, "market": "totals", "side": "over", "line": 8.5}), o) == STATUS_WON
    assert verdict(resolve(o := {**SO_GAME, "market": "totals_alt", "side": "under", "line": 9.5}), o) == STATUS_WON


def test_three_way_settles_on_regulation_and_a_draw_is_a_result(monkeypatch):
    resolve = resolver(selected_date="2025-12-20")
    draw = {**SO_GAME, "market": "h2h_3_way", "side": "draw"}
    resolved = resolve(draw)
    assert resolved["settled_segment"] == "regulation"
    assert (resolved["home_score"], resolved["away_score"]) == (4.0, 4.0)
    assert verdict(resolved, draw) == STATUS_WON
    assert verdict(resolve(o := {**SO_GAME, "market": "h2h_3_way", "side": "home"}), o) == STATUS_LOST
    assert verdict(resolve(o := {**SO_GAME, "market": "h2h_3_way", "side": "Philadelphia Flyers"}), o) == STATUS_LOST

    # The double-overtime final: 4-4 after sixty minutes. DERIVED from the real h2h row (market only).
    rows = board_rows(monkeypatch)
    home = {**pick(rows, market="h2h", side="home", book="draftkings"), "market": "h2h_3_way"}
    assert verdict(resolver()(home), home) == STATUS_LOST
    assert verdict(resolver()({**home, "side": "draw"}), {**home, "side": "draw"}) == STATUS_WON


def test_period_markets_use_that_period_alone():
    resolve = resolver(selected_date="2025-12-20")
    # P2: PHI 4, NYR 1.
    p2 = {**SO_GAME, "market": "totals", "segment": "p2", "side": "over", "line": 4.5}
    resolved = resolve(p2)
    assert resolved["settled_segment"] == "p2" and resolved["current_value"] == 5.0
    assert verdict(resolved, p2) == STATUS_WON
    # P3: 0 + 2, overtime and the shootout NOT included. Market-key spelling too.
    assert verdict(resolve(o := {**SO_GAME, "market": "totals_p3", "side": "under", "line": 2.5}), o) == STATUS_WON
    assert verdict(resolve(o := {**SO_GAME, "market": "spreads", "segment": "p2", "side": "away", "line": -2.5}), o) == STATUS_WON
    # P1 ended 0-1; a level period on a TWO-WAY h2h would push -- here NYR simply won it.
    assert verdict(resolve(o := {**SO_GAME, "market": "h2h", "segment": "1st period", "side": "home"}), o) == STATUS_WON


def test_a_period_closes_when_the_next_one_starts_not_before():
    """DERIVED state: the real shootout game re-stated LIVE in the 2nd period."""
    score = json.loads((FIX / "score_2025-12-20.json").read_text(encoding="utf-8"))
    live = next(game for game in score["games"] if game["id"] == 2025020549)
    live.update({"gameState": "LIVE", "periodDescriptor": {"number": 2, "periodType": "REG"},
                 "clock": {"inIntermission": False}})
    resolve = resolver(FakeNhle({"score_2025-12-20.json": score}), selected_date="2025-12-20")
    p1 = resolve({**SO_GAME, "market": "totals", "segment": "p1", "side": "under", "line": 1.5})
    assert p1["is_final"] is True and p1["current_value"] == 1.0
    p2 = resolve({**SO_GAME, "market": "totals", "segment": "p2", "side": "over", "line": 4.5})
    assert p2["is_final"] is False and p2["started"] is True
    p3 = resolve({**SO_GAME, "market": "totals", "segment": "p3", "side": "over", "line": 1.5})
    assert p3 == {"current_value": None, "is_final": False, "started": False}
    game_line = resolve({**SO_GAME, "market": "h2h", "side": "home"})
    assert game_line["is_final"] is False

    live["clock"] = {"inIntermission": True}
    resolve = resolver(FakeNhle({"score_2025-12-20.json": score}), selected_date="2025-12-20")
    assert resolve({**SO_GAME, "market": "totals", "segment": "p2", "side": "over", "line": 4.5})["is_final"] is True


# ---------------------------------------------------------------------------
# props
# ---------------------------------------------------------------------------


def test_skater_props_from_the_final_box(monkeypatch):
    rows = board_rows(monkeypatch)
    resolve = resolver()
    marner_sog = pick(rows, market="SOG", side="over", player="Mitch Marner")
    resolved = resolve(marner_sog)
    assert resolved["current_value"] == 10.0 and resolved["is_final"] is True
    assert verdict(resolved, marner_sog) == STATUS_WON
    assert verdict(resolve(o := pick(rows, market="GOALS", side="over", player="Mitch Marner")), o) == STATUS_WON
    assert verdict(resolve(o := pick(rows, market="POINTS", side="over", player="Mitch Marner")), o) == STATUS_WON
    assert verdict(resolve(o := pick(rows, market="SOG", side="over", player="Jack Eichel")), o) == STATUS_LOST
    assert verdict(resolve(o := pick(rows, market="SOG", side="under", player="Jack Eichel")), o) == STATUS_WON
    assert verdict(resolve(o := pick(rows, market="GOALS", side="under", player="Jack Eichel")), o) == STATUS_WON
    assert verdict(resolve(o := pick(rows, market="POINTS", side="over", player="Jordan Staal")), o) == STATUS_WON
    assert verdict(resolve(o := pick(rows, market="SOG", side="over", player="Jalen Chatfield")), o) == STATUS_WON
    assert verdict(resolve(o := pick(rows, market="ASSISTS", side="under", player="Shea Theodore")), o) == STATUS_LOST
    # DERIVED line only: Staal took 5 shots, and no priced row sat on a whole number.
    push = {**pick(rows, market="SOG", side="over", player="Jordan Staal"), "line": 5.0}
    assert verdict(resolve(push), push) == STATUS_LIVE_TIED


def test_other_market_spellings_reach_the_same_stat(monkeypatch):
    """The recorder lowercases the key; Kalshi capture files `player_points`; alternates keep a suffix."""
    rows = board_rows(monkeypatch)
    resolve = resolver()
    base = pick(rows, market="SOG", side="over", player="Mitch Marner")
    for market in ("sog", "player_shots_on_goal", "player_shots_on_goal_alternate", "Shots on Goal"):
        assert resolve({**base, "market": market})["current_value"] == 10.0, market
    for market in ("POINTS", "points", "player_points", "player_points_alternate"):
        assert resolve({**base, "market": market})["current_value"] == 4.0, market
    anytime = {**base, "market": "player_goal_scorer_anytime", "side": "yes", "line": None}
    resolved = resolve(anytime)
    assert resolved["line"] == 0.5 and verdict(resolved, anytime) == STATUS_WON
    eichel = {**anytime, "player_name": "Jack Eichel"}
    assert verdict(resolve(eichel), eichel) == STATUS_LOST
    # BLOCKS is in the collector's map but never requested; DERIVED row. Eichel blocked 4.
    blocks = {**base, "market": "BLOCKS", "player_name": "Jack Eichel", "line": 3.5}
    assert verdict(resolve(blocks), blocks) == STATUS_WON


def test_goalie_saves_only_for_a_goalie_who_played(monkeypatch):
    """DERIVED rows (no saves line was collected): goalie names from the game's own roster."""
    rows = board_rows(monkeypatch)
    resolve = resolver()
    base = pick(rows, market="SOG", side="over", player="Mitch Marner")
    hart = {**base, "market": "player_saves", "player_name": "Carter Hart", "line": 27.5}
    assert resolve(hart)["current_value"] == 29.0
    assert verdict(resolve(hart), hart) == STATUS_WON
    assert resolve({**hart, "player_name": "Adin Hill"}) == {"unavailable_reason": "dnp_void"}
    # Shots on goal for a goalie, saves for a skater: not a box stat, never a zero.
    assert resolve({**base, "player_name": "Carter Hart"}) == {"unavailable_reason": "nhl_stat_not_in_box"}
    assert resolve({**hart, "player_name": "Mitch Marner"}) == {"unavailable_reason": "nhl_stat_not_in_box"}


def test_a_player_who_did_not_dress_is_void_not_zero(monkeypatch):
    """Alexander Holtz: on Vegas's 2025-26 roster (`/v1/roster/VGK/20252026`), not in G3's rosterSpots."""
    roster = json.loads((FIX / "roster_VGK_20252026.json").read_text(encoding="utf-8"))
    holtz = next(p for p in roster["players"] if p["lastName"]["default"] == "Holtz")
    name = f"{holtz['firstName']['default']} {holtz['lastName']['default']}"
    rows = board_rows(monkeypatch)
    order = {**pick(rows, market="SOG", side="under", player="Jack Eichel"), "player_name": name}
    assert resolver()(order) == {"unavailable_reason": "dnp_void"}


def test_shootout_goals_do_not_count_for_the_player():
    """Panarin scored twice in play and the shootout winner; the box says 2, and so do books."""
    resolve = resolver(selected_date="2025-12-20")
    order = {**SO_GAME, "market": "GOALS", "player_name": "Artemi Panarin", "side": "over", "line": 2.5}
    resolved = resolve(order)
    assert resolved["current_value"] == 2.0
    assert verdict(resolved, order) == STATUS_LOST


def test_player_name_matching_is_exact_then_prefix_then_refuses():
    players = [
        {"player_name": "Mitch Marner", "first": "Mitch", "last": "Marner"},
        {"player_name": "Nicholas Paul", "first": "Nicholas", "last": "Paul"},
        {"player_name": "Alex Ovechkin", "first": "Alex", "last": "Ovechkin"},
    ]
    assert nhl.match_player(players, "mitch marner")[0]["last"] == "Marner"
    assert nhl.match_player(players, "Mitchell Marner")[0]["last"] == "Marner"
    assert nhl.match_player(players, "Alexander Ovechkin")[0]["last"] == "Ovechkin"
    # Same last name and initial, first name not a prefix: not provably absent.
    assert nhl.match_player(players, "Nick Paul") == (None, "nhl_player_name_unmatched")
    assert nhl.match_player(players, "Quinn Hughes") == (None, "absent")


# ---------------------------------------------------------------------------
# preseason
# ---------------------------------------------------------------------------


def test_preseason_box_and_shootout_grade():
    resolve = resolver(selected_date="2025-09-21")
    assert verdict(resolve(o := {**PRESEASON, "market": "h2h", "side": "away"}), o) == STATUS_WON
    assert verdict(resolve(o := {**PRESEASON, "market": "totals", "side": "over", "line": 4.5}), o) == STATUS_WON
    assert verdict(resolve(o := {**PRESEASON, "market": "h2h_3_way", "side": "draw"}), o) == STATUS_WON
    # The preseason box carries skater lines: Michkov 1 goal, 6 shots (name typed, OddsAPI style).
    sog = {**PRESEASON, "market": "SOG", "player_name": "Matvei Michkov", "side": "over", "line": 4.5}
    assert verdict(resolve(sog), sog) == STATUS_WON
    # Split goalies: Kolosov 15 saves in 39:56.
    saves = {**PRESEASON, "market": "SAVES", "player_name": "Aleksei Kolosov", "side": "under", "line": 20.5}
    assert verdict(resolve(saves), saves) == STATUS_WON


def test_split_squads_are_separated_by_kickoff_or_refused():
    """FLA @ NSH twice on 2025-09-21: 0-5 at 19:00Z, 3-5 at 23:00Z."""
    resolve = resolver(selected_date="2025-09-21")
    base = {"sport": "nhl", "home_team": "Nashville Predators", "away_team": "Florida Panthers",
            "market": "totals", "side": "over", "line": 6.5}
    late = {**base, "commence_time": "2025-09-21T23:00:00Z"}
    early = {**base, "commence_time": "2025-09-21T19:05:00Z"}
    assert verdict(resolve(late), late) == STATUS_WON
    assert verdict(resolve(early), early) == STATUS_LOST
    assert resolve({**base, "commence_time": "2025-09-21T21:00:00Z"}) == {"unavailable_reason": "nhl_game_ambiguous"}
    assert resolve({**base, "commence_time": None}) == {"unavailable_reason": "nhl_game_ambiguous"}

    # CGY @ EDM (3-2 OT) and EDM @ CGY (3-0), same 00:00Z start: home against home decides.
    at_edm = {"sport": "nhl", "home_team": "Edmonton Oilers", "away_team": "Calgary Flames",
              "commence_time": "2025-09-22T00:00:00Z", "market": "totals", "side": "over", "line": 3.5}
    at_cgy = {**at_edm, "home_team": "Calgary Flames", "away_team": "Edmonton Oilers"}
    assert verdict(resolve(at_edm), at_edm) == STATUS_WON
    assert verdict(resolve(at_cgy), at_cgy) == STATUS_LOST


# ---------------------------------------------------------------------------
# refusals
# ---------------------------------------------------------------------------


def test_not_started_game_is_not_a_refusal():
    resolve = resolver(selected_date="2026-09-19")
    order = {"sport": "nhl", "home_team": "Toronto Maple Leafs", "away_team": "Montréal Canadiens",
             "commence_time": "2026-09-19T23:00:00Z", "market": "h2h", "side": "home"}
    assert resolve(order) == {"current_value": None, "is_final": False, "started": False}
    game, why = nhl.locate_nhl_game(order, nhl.NhlFeed(fetch_json=FakeNhle()), "2026-09-19")
    assert why is None and game["game_id"] == "2026010006"
    reverse, _ = nhl.locate_nhl_game({**order, "home_team": "Montreal Canadiens", "away_team": "Toronto Maple Leafs"},
                                     nhl.NhlFeed(fetch_json=FakeNhle()), "2026-09-19")
    assert reverse["game_id"] == "2026010007"


def test_postponed_game_refuses_by_name():
    """DERIVED: the real 2026-09-19 slate with DAL @ STL's `gameScheduleState` set to PPD."""
    score = json.loads((FIX / "score_2026-09-19.json").read_text(encoding="utf-8"))
    next(game for game in score["games"] if game["id"] == 2026010001)["gameScheduleState"] = "PPD"
    resolve = resolver(FakeNhle({"score_2026-09-19.json": score}), selected_date="2026-09-19")
    order = {"sport": "nhl", "home_team": "St. Louis Blues", "away_team": "Dallas Stars",
             "commence_time": "2026-09-19T23:00:00Z", "market": "totals", "side": "over", "line": 5.5}
    assert resolve(order) == {"unavailable_reason": "nhl_game_postponed_or_cancelled"}


def test_permanent_refusals_are_named_before_any_read():
    fake = FakeNhle()
    resolve = resolver(fake)
    base = {**SO_GAME}
    assert resolve({"sport": "nhl"}) == {"unavailable_reason": "unmapped_market"}
    assert resolve({**base, "market": "first_10_minutes_goal", "side": "yes"}) == {"unavailable_reason": "unmapped_market"}
    assert resolve({**base, "market": "team_totals", "side": "over", "line": 2.5}) == {
        "unavailable_reason": "team_totals_needs_a_per_team_score"}
    assert resolve({**base, "market": "player_hits", "player_name": "Artemi Panarin", "side": "over", "line": 1.5}) == {
        "unavailable_reason": "nhl_prop_market_not_mapped"}
    assert resolve({**base, "market": "SOG", "segment": "p1", "player_name": "Artemi Panarin", "side": "over",
                    "line": 0.5}) == {"unavailable_reason": "nhl_prop_needs_full_game"}
    assert resolve({**base, "market": "totals", "segment": "q1", "side": "over", "line": 0.5}) == {
        "unavailable_reason": "unsupported_segment:q1"}
    assert resolve({**base, "sport": "nba", "market": "h2h"}) == {"unavailable_reason": "not_an_nhl_order"}
    assert fake.urls == []


def test_join_refusals_are_named():
    resolve = resolver(selected_date="2025-12-20")
    swapped = {**SO_GAME, "home_team": "Philadelphia Flyers", "away_team": "New York Rangers", "market": "h2h",
               "side": "home"}
    assert resolve(swapped) == {"unavailable_reason": "home_away_disagree_between_sources"}
    assert resolve({**SO_GAME, "home_team": "Kolner Haie", "market": "h2h", "side": "home"}) == {
        "unavailable_reason": "nhl_team_unresolved"}
    assert resolve({**SO_GAME, "home_team": None, "market": "h2h", "side": "home"}) == {
        "unavailable_reason": "no_home_away_teams_on_order"}
    moved = {**SO_GAME, "commence_time": "2025-12-20T09:00:00Z", "market": "h2h", "side": "home"}
    assert resolve(moved) == {"unavailable_reason": "nhl_game_start_time_mismatch"}
    offline = resolver(lambda url: None, selected_date="2025-12-20")
    assert offline({**SO_GAME, "market": "h2h", "side": "home"}) == {"unavailable_reason": "nhl_schedule_unavailable"}


def test_one_read_per_path_per_resolver(monkeypatch):
    rows = board_rows(monkeypatch)
    fake = FakeNhle()
    resolve = resolver(fake)
    for row in rows:
        resolve(row)
    paths = [urlsplit(url).path for url in fake.urls]
    assert len(paths) == len(set(paths))
    assert set(paths) == {"/v1/score/2026-06-06", "/v1/gamecenter/2025030413/boxscore",
                          "/v1/gamecenter/2025030413/play-by-play"}


# ---------------------------------------------------------------------------
# reachability: paper settlement dispatches an NHL order here and grades it
# ---------------------------------------------------------------------------


@pytest.fixture
def isolated_ledger(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNDICATE_REPORTS_ROOT", str(tmp_path))
    monkeypatch.setenv("SYNDICATE_REFRESH_STATE_BACKEND", "file")
    monkeypatch.setenv("SYNDICATE_EXECUTION_MODE", "paper")
    (tmp_path / "intelligence").mkdir(parents=True, exist_ok=True)
    yield


def test_an_nhl_bet_now_grades_end_to_end(monkeypatch, isolated_ledger):
    """off != on: before this resolver every NHL order read `no_resolver_for_nhl`."""
    from syndicate.features.shared import paper_settlement as settle
    from syndicate.features.shared.execution_ledger import OrderRequest, place_order

    rows = board_rows(monkeypatch)
    fake = FakeNhle()
    monkeypatch.setattr(nhl, "_default_fetch_json", fake)

    def place(row, key):
        place_order(OrderRequest(
            position_key=key, selected_date="2026-06-06", venue="paper", sport="nhl",
            event_id=row["event_id"], market=row["market"], side=row["side"],
            requested_price=float(row["price"]), requested_stake_dollars=10.0, line=row["line"],
            player_name=row["player_name"], segment=row["segment"], home_team=row["home_team"],
            away_team=row["away_team"], commence_time=row["commence_time"],
        ))

    place(pick(rows, market="SOG", side="over", player="Mitch Marner"), "n1")
    place(pick(rows, market="h2h", side="away", book="draftkings"), "n2")
    place(pick(rows, market="totals", side="over", line=5.5), "n3")

    probe = settle._default_resolver("2026-06-06")({"sport": "nhl"})
    assert probe["unavailable_reason"] != "no_resolver_for_nhl"

    result = settle.settle_orders("2026-06-06")
    assert result["outcomes"] == {"won": 2, "lost": 1}, result
    assert result["ungraded"] == {}
    assert any("/v1/gamecenter/2025030413/boxscore" in url for url in fake.urls)


# ---------------------------------------------------------------------------
# the process-wide cache: portfolio_commit builds a new resolver every cycle
# ---------------------------------------------------------------------------


def test_a_final_date_is_read_once_across_feeds_that_share_the_cache():
    fake, shared = FakeNhle(), {}
    first = nhl.NhlFeed(fetch_json=fake, shared_cache=shared).games_on("2025-12-20")
    second = nhl.NhlFeed(fetch_json=fake, shared_cache=shared).games_on("2025-12-20")
    assert first and second == first
    assert len(fake.urls) == 1, "off != on: without the shared cache the second feed reads again"
    assert len(nhl.NhlFeed(fetch_json=fake).games_on("2025-12-20")) == len(first) and len(fake.urls) == 2


def test_a_not_final_date_is_reused_only_within_the_live_ttl(monkeypatch):
    fake, shared, clock = FakeNhle(), {}, [1000.0]
    monkeypatch.setattr(nhl.time, "monotonic", lambda: clock[0])
    nhl.NhlFeed(fetch_json=fake, shared_cache=shared).games_on("2026-09-19")
    nhl.NhlFeed(fetch_json=fake, shared_cache=shared).games_on("2026-09-19")
    assert len(fake.urls) == 1
    clock[0] += nhl.LIVE_TTL_SECONDS + 1
    nhl.NhlFeed(fetch_json=fake, shared_cache=shared).games_on("2026-09-19")
    assert len(fake.urls) == 2


def test_a_failed_read_is_never_cached():
    fake, shared = FakeNhle(), {}
    assert nhl.NhlFeed(fetch_json=fake, shared_cache=shared).games_on("1999-01-01") is None
    nhl.NhlFeed(fetch_json=fake, shared_cache=shared).games_on("1999-01-01")
    assert len(fake.urls) == 2 and shared == {}


def test_the_shared_cache_is_bounded(monkeypatch):
    monkeypatch.setattr(nhl, "SHARED_CACHE_MAX", 2)
    fake, shared = FakeNhle(), {}
    for day in ("2025-09-21", "2025-12-20", "2026-06-06"):
        nhl.NhlFeed(fetch_json=fake, shared_cache=shared).games_on(day)
    assert list(shared) == ["/score/2025-12-20", "/score/2026-06-06"]


def test_the_paper_settlement_resolver_uses_the_process_cache(monkeypatch):
    built = []
    real = nhl.NhlFeed

    def spy(**kwargs):
        built.append(kwargs)
        return real(**kwargs)

    monkeypatch.setattr(nhl, "NhlFeed", spy)
    nhl.nhl_status_resolver("2026-09-19")
    assert built and built[0].get("shared_cache") is nhl._SHARED_CACHE

