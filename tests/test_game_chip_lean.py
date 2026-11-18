"""Lean chips for the book grid's game-state join (todo #790 lever (ii), lane `nba-grid-lean-chips`).

What is pinned:
- lean chips carry EXACTLY the fields `board_enrichment.attach_game_state` reads, equal to full chips';
- lean skips the NBA/WNBA bonus summary, football situation, trend, plays and intervals; full still runs them
  (off != on, on the real builder);
- lean and full never share a cache entry;
- the grid's join asks for lean chips unless SYNDICATE_BOOK_GRID_LEAN_CHIPS=off, and a builder without the keyword
  still gets the plain call;
- NBA's cards context inside `cards_context_read_only()` is returned without a copy (hit and miss), and a lean chip
  build leaves the cached context deep-equal (nothing writes into a game).
"""
from __future__ import annotations

import copy

import pytest

from syndicate.features.nba import cards
from syndicate.features.shared import board_enrichment
from syndicate.features.shared import game_chip_linescore as gcl
from syndicate.features.shared import game_chip_scoreboard as gcs

DATE = "2026-11-17"
# The fields the grid's join reads off a chip (board_enrichment.attach_game_state + _segment_score_for_row).
GRID_FIELDS = ("sport", "game_key", "matchup", "away", "home", "state", "status_token", "start_time_utc", "linescore")


def _games():
    rows = _raw_games()
    for row in rows:  # the NBA cards context reads these off every artifact game
        row.setdefault("gamePk", row["game_id"])
        row.setdefault("detail", "")
    return rows


def _raw_games():
    return [
        {  # live, clock already in the token
            "game_id": "401810001",
            "away": {"abbr": "NYK", "name": "New York Knicks", "score": 55},
            "home": {"abbr": "TOR", "name": "Toronto Raptors", "score": 50},
            "live_state": {"in_progress": True, "period": 3, "clock": "6:12"},
            "start_time_utc": "2026-11-18T00:40:00Z",
        },
        {  # live, no clock: the clock token comes from the scoreboard
            "game_id": "401810002",
            "away": {"abbr": "DET", "name": "Detroit Pistons", "score": 30},
            "home": {"abbr": "SA", "name": "San Antonio Spurs", "score": 33},
            "live_state": {"in_progress": True},
            "start_time_utc": "2026-11-18T01:10:00Z",
        },
        {  # final
            "game_id": "401810003",
            "away": {"abbr": "POR", "name": "Portland Trail Blazers", "score": 101},
            "home": {"abbr": "MIN", "name": "Minnesota Timberwolves", "score": 112},
            "status": {"abstract": "Final", "detailed": "Final"},
            "start_time_utc": "2026-11-18T01:10:00Z",
        },
        {  # pregame
            "game_id": "401810004",
            "away": {"abbr": "UTA", "name": "Utah Jazz", "score": 0},
            "home": {"abbr": "LAC", "name": "LA Clippers", "score": 0},
            "status": {"abstract": "Scheduled", "detailed": "Scheduled"},
            "start_time_utc": "2026-11-18T03:40:00Z",
        },
    ]


class _Ctx:
    context_label = DATE


class _Provider:
    def __init__(self, slug, games_fn):
        self.slug = slug
        self.games_fn = games_fn
        self.calls = 0

    def resolve_context(self, *, requested_date=None, season=None, week=None):
        return _Ctx()

    def is_active(self, *, today_value, context_label):
        return True

    def games(self, context, *, is_active_today, include_upcoming=False):
        self.calls += 1
        return self.games_fn()


_BOXES = {
    "NYK": {"kind": "periods", "labels": ["1", "2", "3"], "away": [20, 20, 15], "home": [18, 17, 15]},
    "DET": {"kind": "periods", "labels": ["1", "2"], "away": [15, 15], "home": [16, 17]},
    "POR": {"kind": "periods", "labels": ["1", "2", "3", "4"], "away": [25, 25, 25, 26], "home": [28, 28, 28, 28]},
}


@pytest.fixture
def calls(monkeypatch):
    seen = {"bonus": 0, "situation": 0, "trend": 0, "plays": 0, "intervals": 0, "linescore": 0, "clock": 0}

    def linescore(sport, game, day, *, away_abbr, home_abbr, live):
        seen["linescore"] += 1
        return copy.deepcopy(_BOXES.get(away_abbr))

    def live_clock_token(sport, game, day, *, away_abbr, home_abbr):
        seen["clock"] += 1
        return "Q2 3:04"

    def live_bonus_text(sport, game, day, *, away_abbr, home_abbr):
        seen["bonus"] += 1
        return f"{away_abbr} in the bonus"

    def football_situation(*a, **k):
        seen["situation"] += 1
        return "1st & 10"

    def trend(sport, game, chip, date_value):
        seen["trend"] += 1

    def plays(chips, date_value, sports):
        seen["plays"] += 1
        for chip in chips:
            chip["plays"] = ["a play"]

    def intervals(chips, date_value, *, live_only):
        seen["intervals"] += 1
        for chip in chips:
            chip["intervals"] = {"q1": 1}

    monkeypatch.setattr(gcl, "linescore", linescore)
    monkeypatch.setattr(gcl, "live_clock_token", live_clock_token)
    monkeypatch.setattr(gcl, "live_bonus_text", live_bonus_text)
    monkeypatch.setattr(gcl, "football_situation", football_situation)
    monkeypatch.setattr(gcs, "_attach_trend", trend)
    monkeypatch.setattr(gcs, "_attach_board_plays", plays)
    monkeypatch.setattr(gcs, "_attach_intervals", intervals)
    monkeypatch.setattr(gcs, "_ensure_sport_data_providers", lambda: None)
    monkeypatch.setattr(gcs, "_cache", {})
    return seen


def _register(monkeypatch, providers):
    monkeypatch.setattr("syndicate.features.shared.sport_data_provider.get_sport_data_provider",
                        lambda slug: providers.get(slug))


def _grid_view(chips):
    return sorted(([c.get(k) for k in GRID_FIELDS] for c in chips), key=lambda row: str(row[1]))


def test_lean_chips_equal_full_chips_on_every_field_the_grid_reads(monkeypatch, calls):
    _register(monkeypatch, {"nba": _Provider("nba", _games)})
    full = gcs.build_game_chips(DATE, ["nba"])
    lean = gcs.build_game_chips(DATE, ["nba"], lean=True)
    assert len(full) == len(lean) == 4
    assert _grid_view(lean) == _grid_view(full)
    states = sorted(c["state"] for c in lean)
    assert states == ["final", "live", "live", "pregame"]
    by_key = {c["game_key"]: c for c in lean}
    # the line score's sums and the scoreboard clock are kept: both are read by the grid
    assert by_key["401810002"]["status_token"] == "Q2 3:04"
    assert by_key["401810001"]["linescore"]["away"] == [20, 20, 15]


def test_lean_skips_the_fetches_the_grid_never_reads_and_full_still_runs_them(monkeypatch, calls):
    _register(monkeypatch, {"nba": _Provider("nba", _games)})
    gcs.build_game_chips(DATE, ["nba"], lean=True)
    assert (calls["bonus"], calls["trend"], calls["plays"], calls["intervals"]) == (0, 0, 0, 0)
    assert calls["linescore"] == 3 and calls["clock"] == 1
    lean_chips = gcs.build_game_chips(DATE, ["nba"], lean=True)
    assert all("plays" not in c and "intervals" not in c for c in lean_chips)
    assert not any("bonus" in str(c.get("situation") or "") for c in lean_chips)

    full = gcs.build_game_chips(DATE, ["nba"])  # off != on: the full build reaches every one of them
    assert calls["bonus"] == 2 and calls["trend"] == 3 and calls["plays"] == 1 and calls["intervals"] == 1
    assert all(c.get("plays") and c.get("intervals") for c in full)
    assert sum("bonus" in str(c.get("situation") or "") for c in full) == 2


def test_lean_skips_the_football_situation(monkeypatch, calls):
    game = {"game_id": "9", "away": {"abbr": "KC", "score": 7}, "home": {"abbr": "BUF", "score": 3},
            "live_state": {"in_progress": True, "period": 2, "clock": "4:00"}}
    _register(monkeypatch, {"nfl": _Provider("nfl", lambda: [dict(game)])})
    gcs.build_game_chips(DATE, ["nfl"], lean=True)
    assert calls["situation"] == 0
    gcs.build_game_chips(DATE, ["nfl"])
    assert calls["situation"] == 1


def test_lean_and_full_never_share_a_cache_entry(monkeypatch, calls):
    provider = _Provider("nba", _games)
    _register(monkeypatch, {"nba": provider})
    gcs.build_game_chips(DATE, ["nba"], lean=True)
    gcs.build_game_chips(DATE, ["nba"], lean=True)  # within the TTL: a hit
    assert provider.calls == 1
    full = gcs.build_game_chips(DATE, ["nba"])  # a different key: built, not served the lean list
    assert provider.calls == 2
    assert all(c.get("plays") for c in full)
    assert sorted(map(len, gcs._cache)) == [2, 3]


def _grid_rows():
    return [
        {"home_team": "Toronto Raptors", "away_team": "New York Knicks", "commence_time": "2026-11-18T00:40:00Z",
         "segment": "full"},
        {"home_team": "San Antonio Spurs", "away_team": "Detroit Pistons", "commence_time": "2026-11-18T01:10:00Z",
         "segment": "full"},
    ]


@pytest.mark.parametrize("env, expect_lean", [(None, True), ("1", True), ("on", True), ("off", False), ("0", False)])
def test_the_grid_join_asks_for_lean_chips_unless_switched_off(monkeypatch, env, expect_lean):
    asked = []

    def builder(date, sports, *, lean=False):
        asked.append(lean)
        return []

    monkeypatch.setattr(gcs, "build_game_chips", builder)
    if env is None:
        monkeypatch.delenv(gcs.BOOK_GRID_LEAN_CHIPS_ENV, raising=False)
    else:
        monkeypatch.setenv(gcs.BOOK_GRID_LEAN_CHIPS_ENV, env)
    board_enrichment.attach_game_state(_grid_rows(), sport="nba", selected_date=DATE)
    assert asked and set(asked) == {expect_lean}


def test_a_builder_without_the_keyword_gets_the_plain_call(monkeypatch, calls):
    _register(monkeypatch, {"nba": _Provider("nba", _games)})
    real = gcs.build_game_chips
    monkeypatch.setattr(gcs, "build_game_chips", lambda date, sports: real(date, sports))
    monkeypatch.delenv(gcs.BOOK_GRID_LEAN_CHIPS_ENV, raising=False)
    out = board_enrichment.attach_game_state(_grid_rows(), sport="nba", selected_date=DATE)
    assert out.get("rows_matched") == 2


def test_the_grid_rows_game_blocks_are_identical_lean_and_full(monkeypatch, calls):
    _register(monkeypatch, {"nba": _Provider("nba", _games)})
    lean_rows, full_rows = _grid_rows(), _grid_rows()
    monkeypatch.delenv(gcs.BOOK_GRID_LEAN_CHIPS_ENV, raising=False)
    lean_out = board_enrichment.attach_game_state(lean_rows, sport="nba", selected_date=DATE)
    monkeypatch.setenv(gcs.BOOK_GRID_LEAN_CHIPS_ENV, "off")
    full_out = board_enrichment.attach_game_state(full_rows, sport="nba", selected_date=DATE)
    assert lean_out.get("rows_matched") == full_out.get("rows_matched") == 2
    assert [r.get("game") for r in lean_rows] == [r.get("game") for r in full_rows]
    assert lean_rows[0]["game"]["state"] == "live" and lean_rows[0]["game"]["away_score"] == "55"
    assert any(len(k) == 3 for k in gcs._cache) and any(len(k) == 2 for k in gcs._cache)


# ---- NBA's cards context: no copies inside the read-only scope ------------------------------------------------


@pytest.fixture
def cards_key(monkeypatch):
    monkeypatch.setattr(cards, "available_dates", lambda: [DATE])
    monkeypatch.setattr(cards, "_artifact_paths", lambda d: {"cards": "c", "recommendations": "r", "sim": "s", "props": "p"})
    monkeypatch.setattr(cards, "_path_cache_signature", lambda p: None)
    monkeypatch.setattr(cards, "live_snapshot_path", lambda name: name)
    monkeypatch.setattr(cards, "_live_snapshot_or_state_signature", lambda p: None)
    monkeypatch.setattr(cards, "_live_state_merge_signature", lambda d: 7)


def test_read_only_scope_returns_the_cached_context_itself(monkeypatch, cards_key):
    cached = {"games": _games(), "title": "x"}
    monkeypatch.setattr(cards, "_cache_get_context", lambda key, sig: cached)
    outside = cards.build_cards_page_context(DATE)
    assert outside == cached and outside is not cached and outside["games"][0] is not cached["games"][0]
    with cards.cards_context_read_only():
        inside = cards.build_cards_page_context(DATE)
    assert inside is cached
    again = cards.build_cards_page_context(DATE)  # the scope is gone: a copy again
    assert again is not cached


def test_read_only_miss_returns_the_result_uncopied_and_caches_its_own_copy(monkeypatch, cards_key):
    put = {}
    monkeypatch.setattr(cards, "_cache_get_context", lambda key, sig: None)
    monkeypatch.setattr(cards, "_cache_put_context", lambda key, result, sig=None: put.setdefault("v", result))
    monkeypatch.setattr(cards, "_games_from_artifacts", lambda d: (_games(), "cards.csv", "recs.csv"))
    monkeypatch.setattr(cards, "_is_web_role", lambda: True)
    with cards.cards_context_read_only():
        got = cards.build_cards_page_context(DATE)
    assert got is not put["v"] and got == put["v"]  # the cache's copy is still its own
    assert len(got["games"]) == 4
    copies = []
    real_deepcopy = cards.deepcopy
    monkeypatch.setattr(cards, "deepcopy", lambda obj: copies.append(1) or real_deepcopy(obj))
    put.clear()
    with cards.cards_context_read_only():
        cards.build_cards_page_context(DATE)
    assert len(copies) == 1  # the cache put only
    copies.clear()
    put.clear()
    cards.build_cards_page_context(DATE)
    assert len(copies) == 2  # outside the scope: put + return, as before


def test_a_lean_chip_build_leaves_the_cached_cards_context_unchanged(monkeypatch, calls, cards_key):
    cached = {"games": _games(), "title": "x"}
    before = copy.deepcopy(cached)
    monkeypatch.setattr(cards, "_cache_get_context", lambda key, sig: cached)
    seen = []

    def nba_games():
        payload = cards.build_cards_page_context(DATE)
        seen.append(payload is cached)
        return list(payload.get("games") or [])

    _register(monkeypatch, {"nba": _Provider("nba", nba_games)})
    lean = gcs.build_game_chips(DATE, ["nba"], lean=True)
    assert seen == [True]  # read, not copied
    assert len(lean) == 4
    # the chip build rewrote scores from the line score sums and set clock tokens -- on the CHIPS, not the games
    assert cached == before
    gcs.build_game_chips(DATE, ["nba"])
    assert seen == [True, False]  # the full build still copies
    assert cached == before
