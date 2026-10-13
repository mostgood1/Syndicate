"""The live poller simulates with the LEAGUE's calibrated profile (lane soccer-live-anytime-scorer, 2026-10-13).

Every league ran SOCCER_CALIBRATION_PROFILE live; replaying 588 points of 98 final matches with
`get_league_profile(league)` cut the weighted |per-league bias| in projected remaining goals 0.516 -> 0.372.
Reachability, not presence: count the profile `simulate_match` actually receives at the production call site,
and that the props still share the projection's paths (one simulation set per match, not two).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import poll_soccer_live_state as poller  # noqa: E402
from syndicate.features.soccer.features import live_lens as ll  # noqa: E402
from syndicate.features.soccer.sim_engine.soccersim.calibration_profile import SOCCER_CALIBRATION_PROFILE  # noqa: E402
from syndicate.features.soccer.sim_engine.soccersim.league_profiles import get_league_profile  # noqa: E402

_STATE = {"event_id": "401900001", "home_team": "Home FC", "away_team": "Away FC", "half": 2, "clock_remaining": 1500.0,
          "score_home": 1, "score_away": 1, "home_red_cards": 0, "away_red_cards": 0, "home_corners_so_far": 4,
          "away_corners_so_far": 3, "home_shots_so_far": 8, "away_shots_so_far": 4, "home_shots_on_target_so_far": 3,
          "away_shots_on_target_so_far": 1, "player_stats": {}}
_ROWS = [{"player_id": "h1", "player_name": "Home Striker", "team": "Home FC", "shots_per90": 3.0, "xg_per90": 0.5},
         {"player_id": "a1", "player_name": "Away Striker", "team": "Away FC", "shots_per90": 2.0, "xg_per90": 0.3}]


def _poll(monkeypatch, tmp_path, league):
    monkeypatch.setattr(poller, "fetch_events", lambda *a, **k: [
        {"event_id": "401900001", "home_team": "Home FC", "away_team": "Away FC",
         "status_display_clock": "65'", "status_period": 2, "status_detail": "2nd Half"}])
    monkeypatch.setattr(poller, "build_live_state", lambda *a, **k: dict(_STATE))
    monkeypatch.setattr(poller, "fetch_match_summary", lambda *a, **k: {})
    monkeypatch.setattr(poller, "_load_team_ratings", lambda *a, **k: {})
    monkeypatch.setattr(poller, "_fill_promoted", lambda *a, **k: None)
    monkeypatch.setattr(poller, "_load_player_rows", lambda *a, **k: list(_ROWS))
    monkeypatch.setattr(poller, "_rating_for", lambda *a, **k: {"attack_rating": 0.0, "defense_rating": 0.0})
    monkeypatch.setattr(poller, "fotmob_momentum_block", lambda *a, **k: {"supported": False})
    monkeypatch.setattr(poller, "_build_match_boxes", lambda *a, **k: {})
    seen = []
    real = ll.simulate_match

    def recording(*a, **k):
        seen.append(k.get("profile"))
        return real(*a, **k)

    monkeypatch.setattr(ll, "simulate_match", recording)
    poller.poll_league(league, "2026-10-13", source_root=tmp_path / "src", out_root=tmp_path / "out", simulations=4)
    return seen


def test_the_poller_simulates_with_the_leagues_profile_and_shares_the_paths(monkeypatch, tmp_path, capsys):
    seen = _poll(monkeypatch, tmp_path, "bundesliga")
    assert len(seen) == 4                                            # one set of paths for projection + props
    assert {p.name for p in seen} == {"bundesliga"}
    assert "SHARED_PATHS_MISMATCH" not in capsys.readouterr().out


def test_off_is_not_on_the_league_profile_is_not_the_default():
    """The league profiles differ from the default, so passing one changes what is simulated."""
    for league in ("bundesliga", "mls", "serie_a", "championship", "epl"):
        assert get_league_profile(league) is not SOCCER_CALIBRATION_PROFILE
        assert get_league_profile(league) != SOCCER_CALIBRATION_PROFILE
