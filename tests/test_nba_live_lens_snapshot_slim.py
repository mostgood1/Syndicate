"""The NBA live-lens snapshot must not carry per-player SmartSim rows.

2026-10-08 (lane nba-live-lens-oversize-write): the rows (~530 KB per game)
pushed the snapshot to 9.6 MB, above the keyvalue store's 8 MB cap, so every
write was refused and web served a frozen copy.
"""
from __future__ import annotations

import json

from syndicate.features.nba import live_lens


def _game(tri_away: str, tri_home: str) -> dict:
    row = {"player_name": "P", "prop_ladders": {"pts": {"ladder": list(range(500))}}}
    return {
        "event_id": f"{tri_away}{tri_home}",
        "away_tri": tri_away,
        "home_tri": tri_home,
        "sim": {
            "score": {"total_mean": 220.0},
            "players": {"away": [row] * 15, "home": [row] * 15},
            "missing_prop_players": {"away": [{"player_name": "M"}], "home": []},
            "injuries": {"away": [], "home": [{"player_name": "I"}]},
            "players_summary": {"away": 15, "home": 15},
        },
    }


def _patch_builders(monkeypatch, games: list[dict]) -> None:
    monkeypatch.setattr(live_lens, "_run_nba_live_lens_tick", lambda date: None)
    monkeypatch.setattr(live_lens, "_compute_cards_page_context", lambda date, **kw: {"date": date, "games": games})
    monkeypatch.setattr(live_lens, "_compute_live_lens_page_context", lambda date: {"date": date, "games": games, "rank_cards": []})
    monkeypatch.setattr(live_lens, "_compute_live_lens_api_payload", lambda date: {"date": date, "games": games, "generated_at": "t"})
    monkeypatch.setattr(live_lens, "_compute_live_player_lens_payload", lambda *a, **kw: {"games": []})
    monkeypatch.setattr(live_lens, "_compute_live_lines_payload", lambda *a, **kw: {"games": []})
    monkeypatch.setattr(live_lens, "_compute_live_pbp_stats_payload", lambda *a, **kw: {"games": []})


def test_snapshot_drops_sim_player_rows_from_every_games_copy(monkeypatch):
    games = [_game("BOS", "CLE"), _game("PHI", "BKN")]
    unslimmed = len(json.dumps({"g": games}))
    _patch_builders(monkeypatch, games)

    snapshot = live_lens.build_live_lens_snapshot("2026-10-08")

    copies = [snapshot["games"], snapshot["page_context"]["games"], snapshot["api_payload"]["games"]]
    for copy in copies:
        assert len(copy) == 2
        for game in copy:
            sim = game["sim"]
            assert sim["players"] == {"away": [], "home": []}
            assert sim["missing_prop_players"] == {"away": [], "home": []}
            assert sim["injuries"] == {"away": [], "home": []}
            assert sim["players_loaded"] is False
            # Kept: the card's "N projected rows" chip and everything non-player.
            assert sim["players_summary"] == {"away": 15, "home": 15}
            assert sim["score"] == {"total_mean": 220.0}
    # The reachability check: the strip actually shrank what gets written.
    assert len(json.dumps(snapshot)) * 10 < unslimmed * 3


def test_snapshot_strip_does_not_mutate_the_source_games(monkeypatch):
    games = [_game("BOS", "CLE")]
    _patch_builders(monkeypatch, games)

    live_lens.build_live_lens_snapshot("2026-10-08")

    assert len(games[0]["sim"]["players"]["home"]) == 15
    assert "players_loaded" not in games[0]["sim"]


def test_game_without_sim_passes_through():
    games = [{"event_id": "x"}, "not-a-dict"]
    assert live_lens._without_sim_player_rows(games) == games
