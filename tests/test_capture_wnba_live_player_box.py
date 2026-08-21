"""The live per-player capture, and its refusal to store an empty one.

WHY THE REFUSAL IS TESTED FIRST. `capture_wnba_pbp.py` records the failure this
guards against: a payload with `ok: True` and a complete structure carrying no
data reads as an answer to every consumer, and a persisted empty is then served
in preference to real data. A slate with no live game must leave NO artifact
rather than one asserting that nobody played.

The data itself was never missing -- `/wnba/api/live_player_boxscore` has served
live per-player lines all along. What was missing is persistence: that fetch
runs in the request path on web while the prop join runs in the board build on a
worker.
"""
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


def _load():
    root = Path(__file__).resolve().parents[1]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    name = "capture_wnba_live_player_box_mod"
    spec = importlib.util.spec_from_file_location(
        name, root / "scripts" / "capture_wnba_live_player_box.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(name, None)
        raise
    return module


def _payload(players):
    return {"ok": True, "date": "2026-08-20",
            "games": [{"event_id": "401857160", "players": players}]}


_REAL = [
    {"player": "Angel Reese", "team_tri": "ATL", "pts": 6.0, "reb": 3.0, "ast": 2.0,
     "threes_made": 0.0, "mp": "9"},
    {"player": "Allisha Gray", "team_tri": "ATL", "pts": 4.0, "reb": 1.0, "ast": 1.0,
     "threes_made": 0.0, "mp": "8"},
]
# A name with every priceable stat null -- the pbp skeleton's shape.
_HOLLOW = [
    {"player": "Someone", "team_tri": "ATL", "pts": None, "reb": None, "ast": None,
     "threes_made": None, "mp": None},
]


class SummarizeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.mod = _load()

    def test_counts_only_players_carrying_a_priceable_stat(self) -> None:
        counts = self.mod.summarize(_payload(_REAL + _HOLLOW))
        self.assertEqual(counts["games"], 1)
        self.assertEqual(counts["players_with_stats"], 2, "the hollow row must not count")
        self.assertEqual(counts["per_game"][0]["players"], 3)
        self.assertEqual(counts["per_game"][0]["players_with_stats"], 2)

    def test_a_zero_is_a_stat_and_a_None_is_not(self) -> None:
        """0 points is real data; the distinction decides whether we store."""
        zeros = [{"player": "Bench", "pts": 0.0, "reb": 0.0, "ast": 0.0,
                  "threes_made": 0.0, "mp": "2"}]
        self.assertEqual(self.mod.summarize(_payload(zeros))["players_with_stats"], 1)

    def test_shapeless_payloads_do_not_raise(self) -> None:
        for bad in (None, {}, {"games": None}, {"games": [None, 3]}):
            with self.subTest(bad=bad):
                self.assertEqual(self.mod.summarize(bad)["players_with_stats"], 0)


class MainRefusalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.mod = _load()

    def _run(self, payload):
        written: list = []
        with patch.object(self.mod, "fetch", return_value=payload), \
             patch("syndicate.features.shared.refresh_state_store.write_json_file",
                   side_effect=lambda p, r: written.append((p, r))):
            code = self.mod.main(["--date", "2026-08-20"])
        return code, written

    def test_nothing_live_writes_no_artifact_and_is_not_a_failure(self) -> None:
        code, written = self._run({"ok": True, "games": []})
        self.assertEqual(code, 1, "no live game is the normal state, not an error")
        self.assertEqual(written, [], "an absent slate must leave NO artifact")

    def test_a_games_present_but_hollow_capture_is_REFUSED(self) -> None:
        """THE GUARD. Storing this makes 'nobody has scored' read as fact."""
        code, written = self._run(_payload(_HOLLOW))
        self.assertEqual(code, 2)
        self.assertEqual(written, [], "an empty capture must never be persisted")

    def test_a_real_capture_is_written_with_its_counts(self) -> None:
        code, written = self._run(_payload(_REAL))
        self.assertEqual(code, 0)
        self.assertEqual(len(written), 1)
        path, record = written[0]
        self.assertIn("live_player_box_2026-08-20.json", str(path))
        self.assertEqual(record["counts"]["players_with_stats"], 2)
        self.assertEqual(record["date"], "2026-08-20")
        # The raw payload is kept whole: a consumer must be able to re-derive
        # anything this script chose not to summarise.
        self.assertEqual(record["payload"]["games"][0]["players"][0]["player"], "Angel Reese")

    def test_dry_run_reports_without_writing(self) -> None:
        with patch.object(self.mod, "fetch", return_value=_payload(_REAL)), \
             patch("syndicate.features.shared.refresh_state_store.write_json_file") as w:
            code = self.mod.main(["--date", "2026-08-20", "--dry-run"])
        self.assertEqual(code, 0)
        w.assert_not_called()

    def test_a_fetch_failure_is_not_reported_as_an_empty_slate(self) -> None:
        with patch.object(self.mod, "fetch", side_effect=OSError("boom")), \
             patch("syndicate.features.shared.refresh_state_store.write_json_file") as w:
            code = self.mod.main(["--date", "2026-08-20"])
        self.assertEqual(code, 2, "a failed fetch must not exit 1 like a quiet slate")
        w.assert_not_called()


# NOTE: the allowlist assertion that belongs here is DELIBERATELY ABSENT.
# `wnba_source/data/live/live_player_box_*.json` still needs a
# HOT_ARTIFACT_PATTERNS entry before the board build can read this capture, and
# that file is claimed by the OPEN lane `nfl-props-odds-allowlist`. Editing it
# across lanes is the one thing the claim exists to stop, so the entry -- and
# the `is_hot_artifact_relative_path` test that pins it -- are recorded as owed
# in `wnba-live-props-data` rather than landed here. Until then this capture
# writes an artifact the worker cannot see: written, not yet reachable.


if __name__ == "__main__":
    unittest.main()
