from __future__ import annotations

import unittest

from syndicate.features.soccer.sim_engine.soccersim.situation_model import URGENCY_CLOSING_HALF
from syndicate.features.soccer.sim_engine.soccersim.situation_model import URGENCY_DESPERATION
from syndicate.features.soccer.sim_engine.soccersim.situation_model import URGENCY_NEUTRAL
from syndicate.features.soccer.sim_engine.soccersim.situation_model import URGENCY_PROTECT_LEAD
from syndicate.features.soccer.sim_engine.soccersim.situation_model import URGENCY_TRAILING_PUSH
from syndicate.features.soccer.sim_engine.soccersim.situation_model import classify_urgency


class SoccerSimSituationModelTests(unittest.TestCase):
    def test_neutral_early_match(self) -> None:
        self.assertEqual(classify_urgency(half=1, seconds_remaining=2000, score_differential=0), URGENCY_NEUTRAL)

    def test_desperation_when_trailing_late(self) -> None:
        self.assertEqual(classify_urgency(half=2, seconds_remaining=400, score_differential=-1), URGENCY_DESPERATION)

    def test_desperation_requires_catchable_deficit(self) -> None:
        self.assertEqual(classify_urgency(half=2, seconds_remaining=400, score_differential=-3), URGENCY_TRAILING_PUSH)

    def test_trailing_push_in_second_half(self) -> None:
        self.assertEqual(classify_urgency(half=2, seconds_remaining=1400, score_differential=-1), URGENCY_TRAILING_PUSH)

    def test_protect_lead_late(self) -> None:
        self.assertEqual(classify_urgency(half=2, seconds_remaining=800, score_differential=1), URGENCY_PROTECT_LEAD)

    def test_closing_first_half(self) -> None:
        self.assertEqual(classify_urgency(half=1, seconds_remaining=90, score_differential=0), URGENCY_CLOSING_HALF)


if __name__ == "__main__":
    unittest.main()
