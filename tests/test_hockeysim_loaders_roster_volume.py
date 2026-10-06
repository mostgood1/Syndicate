"""Team shot volume blended with the dressed roster's shot rates (lane nhl-early-season-shot-volume)."""

from __future__ import annotations

from syndicate.features.nhl.sim_engine.hockeysim.contracts import HockeyPlayerFeatures, HockeyTeamFeatures
from syndicate.features.nhl.sim_engine.hockeysim.features import loaders


def _roster(shot_weight: float, n_f: int = 12, n_d: int = 6, slotted: bool = True):
    out = []
    for i in range(n_f):
        out.append(HockeyPlayerFeatures(player_id=i, full_name=f"F{i}", position="F", shot_weight=shot_weight,
                                        line_slot=f"L{i // 3 + 1}" if slotted else None))
    for i in range(n_d):
        out.append(HockeyPlayerFeatures(player_id=100 + i, full_name=f"D{i}", position="D", shot_weight=shot_weight,
                                        line_slot=f"D{i // 2 + 1}" if slotted else None))
    out.append(HockeyPlayerFeatures(player_id=999, full_name="G", position="G", is_starting_goalie=True))
    return tuple(out)


def test_team_rate_moves_toward_the_dressed_rosters_shot_rates(monkeypatch):
    monkeypatch.delenv("SYNDICATE_NHL_ROSTER_SHOT_WEIGHT", raising=False)
    team = HockeyTeamFeatures(name="T", shots_per_60=26.0)
    out = loaders.apply_roster_shot_volume(team, _roster(2.0))          # roster sum 18 * 2.0 = 36
    a = loaders.ROSTER_SHOT_VOLUME_WEIGHT
    assert out.shots_per_60 == round((1 - a) * 26.0 + a * 36.0, 4)
    assert out.goals_per_60 == team.goals_per_60                          # goals untouched


def test_unrated_skaters_count_at_replacement_and_unslotted_do_not(monkeypatch):
    monkeypatch.delenv("SYNDICATE_NHL_ROSTER_SHOT_WEIGHT", raising=False)
    team = HockeyTeamFeatures(name="T", shots_per_60=30.0)
    players = tuple(p if p.position == "G" else HockeyPlayerFeatures(
        player_id=p.player_id, full_name=p.full_name, position=p.position, shot_weight=None, line_slot=p.line_slot)
        for p in _roster(1.0))
    roster = 12 * loaders._ROSTER_REPLACEMENT_SOG["F"] + 6 * loaders._ROSTER_REPLACEMENT_SOG["D"]
    a = loaders.ROSTER_SHOT_VOLUME_WEIGHT
    assert loaders.apply_roster_shot_volume(team, players).shots_per_60 == round((1 - a) * 30.0 + a * roster, 4)
    # no lineup (nobody slotted): the team rate is left alone
    assert loaders.apply_roster_shot_volume(team, _roster(3.0, slotted=False)).shots_per_60 == 30.0


def test_env_override_disables(monkeypatch):
    monkeypatch.setenv("SYNDICATE_NHL_ROSTER_SHOT_WEIGHT", "0")
    team = HockeyTeamFeatures(name="T", shots_per_60=26.0)
    assert loaders.apply_roster_shot_volume(team, _roster(3.0)).shots_per_60 == 26.0




def test_blend_still_runs_once_the_in_season_team_rates_file_exists(tmp_path, monkeypatch):
    """Reachability (H28): f88c9453 skipped the blend once `team_rates_<season>.csv` existed (2026-11-01);
    it now runs all season."""
    proc = loaders._processed_dir(tmp_path)
    proc.mkdir(parents=True, exist_ok=True)
    (proc / "team_rates_latest.csv").write_text("abbr,shots_per_60,faceoff_win_pct\nTOR,26.3,0.5\n", encoding="utf-8")
    (proc / "team_rates_2026-2027.csv").write_text("abbr,shots_per_60,faceoff_win_pct\nTOR,28.0,0.5\nBOS,30.0,0.5\n", encoding="utf-8")
    seen = []
    real = loaders.apply_roster_shot_volume
    monkeypatch.setattr(loaders, "apply_roster_shot_volume", lambda team, players: seen.append(team.abbrev) or real(team, players))
    loaders.build_game_features("1", "2026-11-05", "Toronto Maple Leafs", "Boston Bruins", root=tmp_path, project=False)
    assert sorted(seen) == ["BOS", "TOR"]
