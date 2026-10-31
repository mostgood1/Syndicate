"""`_sync_odds_history_for_refresh` holds ONE odds_history shard at a time.

Lane `live-odds-memory-spikes`, 2026-10-31. Soccer's game_odds_current.csv and
props files carry rows for ~10 game dates, and the sync used to apply rows in
file order, which keeps every touched shard loaded until the last write. On the
fleet that was 449 MB of shard JSON held as ~1.4 GB of dicts at the end of every
soccer refresh -- the live-odds-worker spike to 90%+ of its 3,072 MB cap. A
replay on a copy of the fleet's 10-31 shards: +1,542 MB peak before, +704 MB
after, all 54 output files byte-identical.

The first test is the predicate: it FAILS on the old code (three loads before
the first write). The ordering test guards what the rewrite had to put back:
the steam record keeps the newest N by list position, so lifecycle and steam
events must stay in FILE order even though rows now apply grouped by shard.
"""
from __future__ import annotations

import csv
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from syndicate.features.shared import odds_refresh_tracking as ort

_DATE = "2026-10-31"
_HEADER = ["league", "event_id", "home_team", "away_team", "commence_time", "market", "side", "line", "price", "book"]
# Interleaved game dates, so file order and shard order disagree.
_GAMES = [
    ("e1", "Spurs", "Palace", "2026-10-31T17:30:00Z"),
    ("e2", "Leeds", "Wolves", "2026-11-01T15:00:00Z"),
    ("e3", "Fulham", "Brentford", "2026-10-31T15:00:00Z"),
    ("e4", "Everton", "Villa", "2026-11-08T12:30:00Z"),
    ("e5", "Burnley", "Forest", "2026-11-01T17:30:00Z"),
]


def _write_candidate(root: Path, price_bump: int = 0) -> Path:
    path = root / "epl" / "api" / "odds" / "game_odds_current.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(_HEADER)
        for event_id, home, away, kickoff in _GAMES:
            for book, base in (("draftkings", 120), ("fanduel", 125)):
                writer.writerow(["epl", event_id, home, away, kickoff, "h2h", home, "", base + price_bump, book])
                writer.writerow(["epl", event_id, home, away, kickoff, "totals", "Over", "2.5", -110 - price_bump, book])
    return path


class _Env:
    def __init__(self, tmp: Path) -> None:
        self.source_root = tmp / "soccer_source"
        self.patches = [
            patch.dict(os.environ, {
                "SYNDICATE_REPORTS_ROOT": str(tmp / "reports"),
                "SYNDICATE_ODDS_EVENTS_ROOT": str(tmp / "odds_events"),
                "SYNDICATE_REFRESH_STATE_BACKEND": "file",
            }),
            patch("syndicate.features.shared.artifact_publisher.publish_hot_artifact", lambda *a, **k: False),
            patch.object(ort, "_utc_now", lambda: "2026-10-31T12:00:00Z"),
        ]

    def __enter__(self) -> "_Env":
        for p in self.patches:
            p.start()
        return self

    def __exit__(self, *exc: object) -> None:
        for p in reversed(self.patches):
            p.stop()

    def sync(self) -> dict:
        return ort._sync_odds_history_for_refresh(sport="soccer", source_root=self.source_root, date_str=_DATE)


class OneShardResidentAtATime(unittest.TestCase):
    def test_each_shard_is_written_before_the_next_is_loaded(self) -> None:
        calls: list[tuple[str, str]] = []
        real_load = ort._load_shard_existing_markets
        real_write = ort._write_odds_history_artifact

        def load(**kwargs):
            calls.append(("load", kwargs["shard_key"]))
            return real_load(**kwargs)

        def write(path, payload, **kwargs):
            calls.append(("write", payload["shard_key"]))
            return real_write(path, payload, **kwargs)

        with tempfile.TemporaryDirectory() as tmp, _Env(Path(tmp)) as env:
            _write_candidate(env.source_root)
            with patch.object(ort, "_load_shard_existing_markets", load), patch.object(ort, "_write_odds_history_artifact", write):
                result = env.sync()

        self.assertFalse(result.get("skipped"), result)
        self.assertEqual(set(result["shards"]), {"2026-10-31", "2026-11-01", "2026-11-08"})
        # Three copies per shard, and no load while another shard is still unwritten.
        self.assertEqual(
            calls,
            [step for shard in ("2026-10-31", "2026-11-01", "2026-11-08")
             for step in [("load", shard)] + [("write", shard)] * 3],
        )
        # First-touch order still names the primary shard.
        self.assertEqual(Path(result["history_path"]).name, "2026-10-31.json")

    def test_the_three_copies_are_the_same_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, _Env(Path(tmp)) as env:
            _write_candidate(env.source_root)
            result = env.sync()
            for shard in result["shards"].values():
                blobs = {Path(shard[key]).read_bytes() for key in ("history_path", "shared_history_path", "artifact_history_path")}
                self.assertEqual(len(blobs), 1)
                payload = json.loads(blobs.pop())
                self.assertEqual(len(payload["markets"]), shard["markets_tracked"])


class EventsStayInFileOrder(unittest.TestCase):
    def test_lifecycle_events_follow_the_csv_not_the_shards(self) -> None:
        from syndicate.features.shared.odds_lifecycle import odds_lifecycle_path

        with tempfile.TemporaryDirectory() as tmp, _Env(Path(tmp)) as env:
            _write_candidate(env.source_root)
            env.sync()
            lines = odds_lifecycle_path(_DATE).read_text(encoding="utf-8").splitlines()
        games = [json.loads(line).get("game_id") for line in lines]
        runs = [game for index, game in enumerate(games) if index == 0 or games[index - 1] != game]
        self.assertEqual(runs, ["e1", "e2", "e3", "e4", "e5"])
        # Grouped by shard it would read e1, e3 | e2, e5 | e4.
        self.assertEqual(len(games), 4 * len(_GAMES))

    def test_close_events_come_after_every_row_event(self) -> None:
        from syndicate.features.shared.odds_lifecycle import odds_lifecycle_path

        with tempfile.TemporaryDirectory() as tmp, _Env(Path(tmp)) as env:
            _write_candidate(env.source_root)
            env.sync()
            first_run_lines = len(odds_lifecycle_path(_DATE).read_text(encoding="utf-8").splitlines())
            # Second run: e3 (a 10-31 game, read before the 11-01 rows) drops
            # out, so its markets get "close" events in the 10-31 shard.
            global _GAMES
            saved = _GAMES
            _GAMES = [g for g in saved if g[0] != "e3"]
            try:
                _write_candidate(env.source_root, price_bump=5)
                env.sync()
            finally:
                _GAMES = saved
            lines = odds_lifecycle_path(_DATE).read_text(encoding="utf-8").splitlines()[first_run_lines:]
        kinds = [str(json.loads(line).get("event_type") or "") for line in lines]
        self.assertIn("close", kinds)
        first_close = kinds.index("close")
        self.assertTrue(all(kind == "close" for kind in kinds[first_close:]), kinds)


if __name__ == "__main__":
    unittest.main()
