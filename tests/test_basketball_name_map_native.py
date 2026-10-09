"""Lane `basketball-native-live-state`: a PREGAME game gets its ESPN name->id map from the native player checks.

Measured 2026-10-09 on the fleet: with no box score out yet, the sim's map was EMPTY for 2026-10-10 TOR v LAC,
so the rotation-history path refused with `no_espn_name_map` on every pregame NBA sim.
"""

from __future__ import annotations

from types import SimpleNamespace

import pandas as pd

from syndicate.features.shared import basketball_props_smart_sim as bss


def _module(processed):
    return SimpleNamespace(paths=SimpleNamespace(data_processed=processed, root=processed.parent.parent),
                           _clean_id_str=bss._clean_id_str_local, _norm_player_key=bss._norm_name_key)


def _checks(processed, date, rows):
    d = processed / "rotation_stints"
    d.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows, columns=["date", "team", "player_id", "player_name"]).to_csv(d / f"player_checks_{date}.csv", index=False)


def test_pregame_map_comes_from_native_player_checks(tmp_path, monkeypatch):
    processed = tmp_path / "nba_source" / "data" / "processed"
    _checks(processed, "2026-10-05", [("2026-10-05", "TOR", "111", "Scottie Barnes"), ("2026-10-05", "LAC", "222", "Kawhi Leonard"),
                                      ("2026-10-05", "BOS", "333", "Jayson Tatum")])
    _checks(processed, "2026-10-08", [("2026-10-08", "TOR", "999", "Scottie Barnes")])  # newest wins
    _checks(processed, "2026-10-11", [("2026-10-11", "TOR", "777", "Future Guy")])  # after the slate: ignored
    monkeypatch.setattr(bss, "_espn_event_id_for_matchup_local", lambda **_: "")  # pregame: nothing to look up
    out = bss._espn_name_to_id_map_for_game_local(smart_sim_module=_module(processed), date_str="2026-10-10",
                                                  home_tri="TOR", away_tri="LAC", event_id=None)
    key = lambda name: str(bss._norm_name_key(name)).upper().strip()
    assert out[("TOR", key("Scottie Barnes"))] == "999"
    assert out[("LAC", key("Kawhi Leonard"))] == "222"
    assert ("BOS", key("Jayson Tatum")) not in out and ("TOR", key("Future Guy")) not in out


def test_no_native_tables_is_still_empty_not_an_error(tmp_path, monkeypatch):
    processed = tmp_path / "nba_source" / "data" / "processed"
    processed.mkdir(parents=True)
    monkeypatch.setattr(bss, "_espn_event_id_for_matchup_local", lambda **_: "")
    assert bss._espn_name_to_id_map_for_game_local(smart_sim_module=_module(processed), date_str="2026-10-10",
                                                   home_tri="TOR", away_tri="LAC", event_id=None) == {}
