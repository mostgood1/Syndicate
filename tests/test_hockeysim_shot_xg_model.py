"""Tests for `historical_truth.shot_xg_model` -- the play-by-play shot parser and feature
vectorizer the real xG model is built from."""
from __future__ import annotations

import unittest

from syndicate.features.nhl.sim_engine.hockeysim.historical_truth.shot_xg_model import (
    FEATURE_NAMES, build_shot_dataset, featurize, parse_play_by_play_shots,
)


def _play(type_key, *, team_id=13, x=70, y=10, shot_type="wrist", situation="1551",
          period=1, time_in_period="05:00", goalie_in_net=True, event_id=1):
    details = {"eventOwnerTeamId": team_id, "xCoord": x, "yCoord": y, "shotType": shot_type}
    if goalie_in_net:
        details["goalieInNetId"] = 8475683
    return {
        "eventId": event_id,
        "periodDescriptor": {"number": period},
        "timeInPeriod": time_in_period,
        "situationCode": situation,
        "typeDescKey": type_key,
        "details": details,
    }


def _payload(plays, *, home_id=13, home_abbr="FLA", away_id=16, away_abbr="CHI", game_id="2025020001"):
    return {
        "id": game_id,
        "homeTeam": {"id": home_id, "abbrev": home_abbr},
        "awayTeam": {"id": away_id, "abbrev": away_abbr},
        "plays": plays,
    }


class ParsePlayByPlayShotsTest(unittest.TestCase):
    def test_blocked_shots_excluded_fenwick_only(self) -> None:
        payload = _payload([_play("blocked-shot"), _play("shot-on-goal"), _play("missed-shot"), _play("goal")])
        shots = parse_play_by_play_shots(payload)
        self.assertEqual(len(shots), 3)  # blocked-shot excluded

    def test_goal_flagged_correctly(self) -> None:
        payload = _payload([_play("goal", event_id=1), _play("shot-on-goal", event_id=2)])
        shots = parse_play_by_play_shots(payload)
        self.assertEqual([s.is_goal for s in shots], [True, False])

    def test_distance_and_angle_straight_on_close_shot(self) -> None:
        # x=80 (9 feet short of the net at x=89), y=0 -> straight-on shot, distance ~9, angle ~0
        payload = _payload([_play("shot-on-goal", x=80, y=0)])
        shots = parse_play_by_play_shots(payload)
        self.assertAlmostEqual(shots[0].distance, 9.0, places=1)
        self.assertAlmostEqual(shots[0].angle, 0.0, places=1)

    def test_distance_and_angle_negative_x_net_uses_negative_net(self) -> None:
        # A shot on the OTHER side of the ice (x negative) should measure against the x=-89 net,
        # not the x=+89 net -- sign(xCoord) selects which net.
        payload = _payload([_play("shot-on-goal", x=-80, y=0)])
        shots = parse_play_by_play_shots(payload)
        self.assertAlmostEqual(shots[0].distance, 9.0, places=1)

    def test_wide_angle_shot_from_the_side(self) -> None:
        # Same distance-from-goal-line but far off to the side -> a much larger angle than the
        # straight-on case above.
        payload = _payload([_play("shot-on-goal", x=80, y=20)])
        shots = parse_play_by_play_shots(payload)
        self.assertGreater(shots[0].angle, 45.0)

    def test_strength_state_ev_pp_sh(self) -> None:
        # home team (id 13) shooting: situationCode digits are [awayGoalie][awaySkaters]
        # [homeSkaters][homeGoalie]. "1451" = away 4 skaters, home 5 -> home is on the PP.
        payload = _payload([
            _play("shot-on-goal", team_id=13, situation="1551", event_id=1),   # 5v5 EV
            _play("shot-on-goal", team_id=13, situation="1451", event_id=2),   # home PP
            _play("shot-on-goal", team_id=13, situation="1541", event_id=3),   # home SH
        ])
        shots = parse_play_by_play_shots(payload)
        self.assertEqual([s.strength_state for s in shots], ["EV", "PP", "SH"])

    def test_strength_state_symmetric_for_away_shooter(self) -> None:
        # Away team (id 16) shooting while home is on the PP -> away is SH, not PP.
        payload = _payload([_play("shot-on-goal", team_id=16, situation="1451", event_id=1)])
        shots = parse_play_by_play_shots(payload)
        self.assertEqual(shots[0].strength_state, "SH")

    def test_unparseable_situation_code_skipped(self) -> None:
        payload = _payload([_play("shot-on-goal", situation="")])
        shots = parse_play_by_play_shots(payload)
        self.assertEqual(shots, [])

    def test_rebound_within_three_seconds_same_team(self) -> None:
        payload = _payload([
            _play("shot-on-goal", team_id=13, time_in_period="10:00", event_id=1),
            _play("shot-on-goal", team_id=13, time_in_period="10:02", event_id=2),  # +2s, same team
        ])
        shots = parse_play_by_play_shots(payload)
        self.assertFalse(shots[0].is_rebound)
        self.assertTrue(shots[1].is_rebound)

    def test_no_rebound_when_other_team_shoots_between(self) -> None:
        payload = _payload([
            _play("shot-on-goal", team_id=13, time_in_period="10:00", event_id=1),
            _play("shot-on-goal", team_id=13, time_in_period="10:10", event_id=2),  # +10s, no rebound
        ])
        shots = parse_play_by_play_shots(payload)
        self.assertFalse(shots[1].is_rebound)

    def test_empty_net_flag(self) -> None:
        payload = _payload([
            _play("shot-on-goal", goalie_in_net=True, event_id=1),
            _play("shot-on-goal", goalie_in_net=False, event_id=2),
        ])
        shots = parse_play_by_play_shots(payload)
        self.assertFalse(shots[0].is_empty_net)
        self.assertTrue(shots[1].is_empty_net)

    def test_rare_shot_type_bucketed_to_other(self) -> None:
        payload = _payload([_play("shot-on-goal", shot_type="between-legs")])
        shots = parse_play_by_play_shots(payload)
        self.assertEqual(shots[0].shot_type, "other")

    def test_missing_team_ids_returns_empty(self) -> None:
        payload = {"id": "x", "plays": [_play("shot-on-goal")]}
        self.assertEqual(parse_play_by_play_shots(payload), [])

    def test_not_a_dict_returns_empty(self) -> None:
        self.assertEqual(parse_play_by_play_shots(None), [])

    def test_missing_coordinates_skipped_not_crash(self) -> None:
        play = _play("shot-on-goal")
        del play["details"]["xCoord"]
        payload = _payload([play])
        self.assertEqual(parse_play_by_play_shots(payload), [])


class BuildShotDatasetTest(unittest.TestCase):
    def test_flattens_across_payloads(self) -> None:
        p1 = _payload([_play("shot-on-goal", event_id=1)], game_id="g1")
        p2 = _payload([_play("goal", event_id=1), _play("shot-on-goal", event_id=2)], game_id="g2")
        shots = build_shot_dataset([p1, p2])
        self.assertEqual(len(shots), 3)
        self.assertEqual({s.game_id for s in shots}, {"g1", "g2"})


class FeaturizeTest(unittest.TestCase):
    def test_feature_vector_length_matches_feature_names(self) -> None:
        payload = _payload([_play("shot-on-goal")])
        shots = parse_play_by_play_shots(payload)
        X = featurize(shots)
        self.assertEqual(len(X[0]), len(FEATURE_NAMES))

    def test_baseline_levels_all_zero_one_hot(self) -> None:
        # wrist shot at EV -> both one-hot blocks should be all zeros (baseline levels omitted)
        payload = _payload([_play("shot-on-goal", shot_type="wrist", situation="1551")])
        shots = parse_play_by_play_shots(payload)
        X = featurize(shots)
        # distance, angle, is_rebound, is_empty_net occupy indices 0-3; everything after is one-hot
        self.assertEqual(sum(X[0][4:]), 0.0)

    def test_non_baseline_shot_type_sets_exactly_one_column(self) -> None:
        payload = _payload([_play("shot-on-goal", shot_type="slap", situation="1551")])
        shots = parse_play_by_play_shots(payload)
        X = featurize(shots)
        shot_type_block = X[0][4:4 + 6]  # 6 non-baseline shot-type columns (7 known - wrist)
        self.assertEqual(sum(shot_type_block), 1.0)

    def test_pp_strength_sets_exactly_one_strength_column(self) -> None:
        payload = _payload([_play("shot-on-goal", team_id=13, situation="1451")])  # home PP
        shots = parse_play_by_play_shots(payload)
        X = featurize(shots)
        strength_block = X[0][-2:]  # PP, SH columns (EV is baseline)
        self.assertEqual(sum(strength_block), 1.0)


if __name__ == "__main__":
    unittest.main()
