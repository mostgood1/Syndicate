"""Live soccer props allocate the remainder over the players ON THE PITCH.

Lane `soccer-live-anytime-scorer` (2026-10-13). The live props passed the whole season
squad as starters, so a player subbed off at 60' kept a full share of the rest of the
match, and a fringe player outside the matchday squad took a share too. Path under
test: espn_live_state.build_live_state (on_pitch/entered) -> live_lens._live_lineup ->
project_live_player_props -> poll_soccer_live_state._published_live_props.
"""
from __future__ import annotations

from scripts import poll_soccer_live_state as poller
from syndicate.features.soccer.features import live_lens as LL
from syndicate.features.soccer.ingestion.espn_live_state import build_live_state

_NEUTRAL = {"attack_rating": 0.0, "defense_rating": 0.0}


def _athlete(pid, name, starter, pos="Forward"):
    return {"starter": starter, "athlete": {"id": pid, "displayName": name}, "position": {"name": pos}}


def _summary():
    home = [_athlete(str(i), f"Home {i}", True) for i in range(1, 12)] + [_athlete("12", "Home Sub", False)]
    away = [_athlete(str(i), f"Away {i}", True) for i in range(21, 32)]
    return {
        "rosters": [
            {"homeAway": "home", "team": {"displayName": "Home FC"}, "roster": home},
            {"homeAway": "away", "team": {"displayName": "Away FC"}, "roster": away},
        ],
        "keyEvents": [
            {"type": {"text": "Substitution", "type": "substitution"}, "period": {"number": 2},
             "clock": {"value": 3600.0}, "team": {"displayName": "Home FC"},
             "participants": [{"athlete": {"id": "12", "displayName": "Home Sub"}},
                              {"athlete": {"id": "1", "displayName": "Home 1"}}]},
            {"type": {"text": "Red Card", "type": "red-card"}, "period": {"number": 2},
             "clock": {"value": 3900.0}, "team": {"displayName": "Home FC"},
             "participants": [{"athlete": {"id": "2", "displayName": "Home 2"}}]},
        ],
        "commentary": [],
    }


def test_on_pitch_follows_substitutions_and_red_cards_at_the_cutoff():
    before = build_live_state(_summary(), event_id="e1", as_of_seconds=3000.0)["player_stats"]
    assert before["1"]["on_pitch"] and not before["12"]["entered"] and before["2"]["on_pitch"]
    after = build_live_state(_summary(), event_id="e1", as_of_seconds=4000.0)["player_stats"]
    assert after["1"]["entered"] and not after["1"]["on_pitch"]
    assert after["12"]["entered"] and after["12"]["on_pitch"]
    assert not after["2"]["on_pitch"]


def _rows():
    rows = [{"player_id": str(i), "player_name": f"Home {i}", "team": "Home FC",
             "shots_per90": 2.0, "xg_per90": 0.3} for i in range(1, 12)]
    rows.append({"player_id": "12", "player_name": "Home Sub", "team": "Home FC", "shots_per90": 2.0, "xg_per90": 0.3})
    # In the season squad, NOT in this matchday squad.
    rows.append({"player_id": "99", "player_name": "Home Fringe", "team": "Home FC", "shots_per90": 2.0, "xg_per90": 0.3})
    return rows


def _project(state):
    return {p.player_id: p for p in LL.project_live_player_props(
        state, home_rating=_NEUTRAL, away_rating=_NEUTRAL, home_player_rows=_rows(), away_player_rows=[],
        simulations=40, seed=3)}


def test_subbed_off_and_sent_off_players_get_no_remainder_and_keep_what_is_banked():
    state = build_live_state(_summary(), event_id="e1", as_of_seconds=4000.0)
    state["player_stats"]["1"]["goals_so_far"] = 1
    props = _project(state)
    assert props["1"].lineup_basis == "on_pitch" and props["1"].on_pitch is False
    assert props["1"].projected_remainder_shots == 0.0
    assert props["1"].goals_over_probabilities["0.5"] == 1.0   # banked
    assert props["2"].goals_over_probabilities["0.5"] == 0.0   # sent off, never scored
    assert props["12"].on_pitch is True and props["12"].goals_over_probabilities["0.5"] > 0.0
    assert "99" not in props                                  # not in the matchday squad


def test_off_is_not_on_without_the_roster_flags_the_whole_squad_shares():
    """Reachability: strip `on_pitch` and the same state falls back to the squad, so the
    zeros above are the new mapping's doing, and the fringe player is priced again."""
    state = build_live_state(_summary(), event_id="e1", as_of_seconds=4000.0)
    for entry in state["player_stats"].values():
        entry.pop("on_pitch"), entry.pop("entered")
    props = _project(state)
    assert {p.lineup_basis for p in props.values()} == {"squad"}
    assert props["1"].projected_remainder_shots > 0.0
    assert "99" in props


def test_too_few_matched_ids_falls_back_to_the_squad():
    state = build_live_state(_summary(), event_id="e1", as_of_seconds=4000.0)
    rows = [dict(r, player_id="x" + r["player_id"]) for r in _rows()]
    props = LL.project_live_player_props(state, home_rating=_NEUTRAL, away_rating=_NEUTRAL,
                                         home_player_rows=rows, away_player_rows=[], simulations=20, seed=3)
    assert props and {p.lineup_basis for p in props} == {"squad"}


def test_publisher_keeps_every_lineup_row_and_caps_only_squad_fallback_rows():
    def row(pid, basis, shots):
        return LL.LivePlayerPropProjection(player_id=pid, player_name=pid, side="home", shots_so_far=0,
                                           projected_remainder_shots=shots, projected_final_shots=shots,
                                           lineup_basis=basis)
    lineup = [row(f"l{i}", "on_pitch", 0.1 * i) for i in range(20)]
    squad = [row(f"s{i}", "squad", 0.1 * i) for i in range(20)]
    published = poller._published_live_props(lineup + squad)
    ids = {r["player_id"] for r in published}
    assert {f"l{i}" for i in range(20)} <= ids
    assert len(ids - {f"l{i}" for i in range(20)}) == poller._SQUAD_FALLBACK_PROP_ROWS
