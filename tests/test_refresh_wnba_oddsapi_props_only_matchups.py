from __future__ import annotations

import sys
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from refresh_wnba_oddsapi_props import _parse_only_matchups_arg


class ParseOnlyMatchupsArgTests(unittest.TestCase):
    def test_parses_normal_comma_separated_pairs(self) -> None:
        self.assertEqual(
            _parse_only_matchups_arg("LVA-NYL,SEA-CHI"),
            {("LVA", "NYL"), ("SEA", "CHI")},
        )

    def test_empty_string_returns_none(self) -> None:
        self.assertIsNone(_parse_only_matchups_arg(""))
        self.assertIsNone(_parse_only_matchups_arg(None))

    def test_malformed_token_is_dropped_without_poisoning_the_rest(self) -> None:
        self.assertEqual(
            _parse_only_matchups_arg("LVA-NYL,garbage,SEA-CHI"),
            {("LVA", "NYL"), ("SEA", "CHI")},
        )

    def test_all_malformed_returns_none(self) -> None:
        self.assertIsNone(_parse_only_matchups_arg("garbage,alsobad"))

    def test_lowercase_input_normalized_to_uppercase(self) -> None:
        self.assertEqual(_parse_only_matchups_arg("lva-nyl"), {("LVA", "NYL")})

    def test_whitespace_around_tokens_and_tricodes_is_stripped(self) -> None:
        self.assertEqual(_parse_only_matchups_arg(" LVA - NYL , SEA-CHI "), {("LVA", "NYL"), ("SEA", "CHI")})


if __name__ == "__main__":
    unittest.main()
