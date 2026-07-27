"""#76. The odds-events log grew unbounded -- 1,238,217,572 bytes in one day.

Nothing read that. `_load_jsonl_rows` streams into a
`deque(maxlen=_MAX_JSONL_ROWS_PER_FILE)` and is the only production reader, so
everything before the last 2000 rows of a day was already dead weight -- while
still costing a 50GB volume ~8GB at steady state, and filling the cgroup page
cache that `memory.current` counts (measured on refresh-worker after #79:
container 2842MB with 381MB owned by any process).
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import syndicate.features.shared.odds_lifecycle as odds_lifecycle


def _event(seq: int, *, padding: int = 300) -> dict:
    return {
        "market_id": "mlb:123:h2h",
        "event_id": "123",
        "market_key": "h2h",
        "sport": "mlb",
        "price": -110,
        "seq": seq,
        "padding": "x" * padding,
    }


class OddsEventCompactionTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        odds_lifecycle._COMPACTION_NEXT_THRESHOLD.clear()
        odds_lifecycle._JSONL_ROWS_CACHE.clear()
        patcher = patch.dict(
            os.environ,
            {
                "SYNDICATE_DATA_ROOT": self._tmp.name,
                # Small trigger so a test can cross it without writing 64MB.
                "SYNDICATE_ODDS_EVENTS_COMPACT_BYTES": str(1024 * 1024),
            },
            clear=False,
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def _append(self, count: int, *, start: int = 0, batch: int = 200) -> Path:
        path = None
        for offset in range(0, count, batch):
            rows = [_event(start + offset + i) for i in range(min(batch, count - offset))]
            path = odds_lifecycle.append_odds_lifecycle_events("2026-07-26", rows)
        assert path is not None
        return path

    def _row_count(self, path: Path) -> int:
        with path.open(encoding="utf-8") as handle:
            return sum(1 for line in handle if line.strip())

    def test_file_stays_bounded_instead_of_growing_without_limit(self) -> None:
        path = self._append(60_000)
        self.assertLessEqual(
            self._row_count(path),
            odds_lifecycle._MAX_PERSISTED_ROWS_PER_FILE + 5_000,
            "compaction should hold the file near its retention target",
        )

    def test_the_newest_rows_survive_and_stay_contiguous(self) -> None:
        # The whole safety argument: readers only ever see the tail, so
        # compaction is only safe if the tail is exactly what is kept.
        path = self._append(60_000)
        rows = odds_lifecycle._load_jsonl_rows(path)
        self.assertEqual(len(rows), odds_lifecycle._MAX_JSONL_ROWS_PER_FILE)
        seqs = [row["seq"] for row in rows]
        self.assertEqual(seqs[-1], 59_999)
        self.assertEqual(seqs, list(range(60_000 - len(seqs), 60_000)))

    def test_retention_is_far_larger_than_any_reader_can_consume(self) -> None:
        # A reader cannot be starved by compaction even if the read cap is
        # raised substantially later.
        self.assertGreaterEqual(
            odds_lifecycle._MAX_PERSISTED_ROWS_PER_FILE,
            odds_lifecycle._MAX_JSONL_ROWS_PER_FILE * 10,
        )

    def test_compaction_is_amortised_not_per_append(self) -> None:
        # Regression guard for a flaw found by measuring rather than reading:
        # with an ABSOLUTE size ceiling, a retained set larger than the ceiling
        # puts every append over it, so compaction runs on every append and
        # rewrites the whole retained set each time -- 300 compactions for
        # 80,000 rows locally. The trigger is growth-since-last-compaction for
        # that reason, which makes it O(1) compactions per trigger of bytes
        # written whatever the row size.
        #
        # Rows here are ~2KB, so the retained 20k rows (~42MB) FAR exceed the
        # trigger -- exactly the shape that produced the pathological case.
        appends = 120
        with patch.dict(os.environ, {"SYNDICATE_ODDS_EVENTS_COMPACT_BYTES": str(8 * 1024 * 1024)}, clear=False):
            with patch.object(
                odds_lifecycle,
                "_compact_odds_lifecycle_file",
                wraps=odds_lifecycle._compact_odds_lifecycle_file,
            ) as spy:
                path = None
                for offset in range(appends):
                    rows = [_event(offset * 200 + i, padding=2000) for i in range(200)]
                    path = odds_lifecycle.append_odds_lifecycle_events("2026-07-26", rows)
        self.assertIsNotNone(path)
        # ~420KB per append against an 8MB trigger, so the growth rule allows
        # roughly one compaction per 19 appends. The ABSOLUTE-ceiling version
        # compacted on every append once the retained set passed the ceiling,
        # i.e. ~`appends` times. Assert the order of magnitude, not a
        # hand-tuned count.
        self.assertLess(
            spy.call_count,
            appends // 4,
            f"compaction ran {spy.call_count} times across {appends} appends -- "
            "that is per-append behaviour, not amortised",
        )

    def test_compaction_can_be_disabled(self) -> None:
        with patch.dict(os.environ, {"SYNDICATE_ODDS_EVENTS_COMPACT_BYTES": "0"}, clear=False):
            path = self._append(30_000)
        self.assertEqual(self._row_count(path), 30_000)

    def test_a_small_file_is_never_rewritten(self) -> None:
        with patch.object(odds_lifecycle, "_compact_odds_lifecycle_file") as spy:
            self._append(500)
        spy.assert_not_called()

    def test_rows_remain_valid_json_after_compaction(self) -> None:
        path = self._append(60_000)
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    self.assertIsInstance(json.loads(line), dict)

    def test_no_temp_files_are_left_behind(self) -> None:
        path = self._append(60_000)
        leftovers = list(path.parent.glob("*.tmp"))
        self.assertEqual(leftovers, [])



class StaleOddsEventBacklogTests(unittest.TestCase):
    """#76 backlog. The append path only ever touches the file being written,
    so every earlier day stayed at whatever size it had reached -- ~948MB in
    closed files on refresh-worker 2026-07-27, all still read every cycle by
    the 7-day lookback.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        odds_lifecycle._COMPACTION_NEXT_THRESHOLD.clear()
        odds_lifecycle._JSONL_ROWS_CACHE.clear()
        patcher = patch.dict(
            os.environ,
            {
                "SYNDICATE_DATA_ROOT": self._tmp.name,
                "SYNDICATE_ODDS_EVENTS_COMPACT_BYTES": str(512 * 1024),
            },
            clear=False,
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        self.root = Path(self._tmp.name) / "odds_events"
        self.root.mkdir(parents=True, exist_ok=True)

    def _write(self, name: str, rows: int) -> Path:
        path = self.root / name
        with path.open("w", encoding="utf-8") as handle:
            for seq in range(rows):
                handle.write(json.dumps(_event(seq)) + "\n")
        return path

    def _rows(self, path: Path) -> int:
        with path.open(encoding="utf-8") as handle:
            return sum(1 for line in handle if line.strip())

    def test_closed_oversized_logs_are_trimmed(self) -> None:
        from datetime import date

        stale = self._write("2026-07-25.jsonl", 40_000)
        before = stale.stat().st_size
        count = odds_lifecycle.compact_stale_odds_lifecycle_files(root=self.root, today=date(2026, 7, 26))
        self.assertEqual(count, 1)
        self.assertLess(stale.stat().st_size, before)
        self.assertLessEqual(self._rows(stale), odds_lifecycle._MAX_PERSISTED_ROWS_PER_FILE)

    def test_todays_log_is_left_to_the_append_path(self) -> None:
        # It has a writer; trimming it here would race the appender.
        from datetime import date

        today_log = self._write("2026-07-26.jsonl", 40_000)
        before = today_log.stat().st_size
        count = odds_lifecycle.compact_stale_odds_lifecycle_files(root=self.root, today=date(2026, 7, 26))
        self.assertEqual(count, 0)
        self.assertEqual(today_log.stat().st_size, before)

    def test_future_dated_and_unparseable_names_are_left_alone(self) -> None:
        from datetime import date

        future = self._write("2026-07-27.jsonl", 40_000)
        junk = self._write("not-a-date.jsonl", 40_000)
        sizes = (future.stat().st_size, junk.stat().st_size)
        odds_lifecycle.compact_stale_odds_lifecycle_files(root=self.root, today=date(2026, 7, 26))
        self.assertEqual((future.stat().st_size, junk.stat().st_size), sizes)

    def test_small_closed_logs_are_not_rewritten(self) -> None:
        from datetime import date

        small = self._write("2026-07-24.jsonl", 100)
        mtime = small.stat().st_mtime_ns
        count = odds_lifecycle.compact_stale_odds_lifecycle_files(root=self.root, today=date(2026, 7, 26))
        self.assertEqual(count, 0)
        self.assertEqual(small.stat().st_mtime_ns, mtime)

    def test_the_lookback_still_reads_the_newest_rows_of_a_trimmed_day(self) -> None:
        # The lookback reads closed days too, so trimming must preserve the
        # same tail those reads already select.
        from datetime import date

        stale = self._write("2026-07-25.jsonl", 40_000)
        odds_lifecycle.compact_stale_odds_lifecycle_files(root=self.root, today=date(2026, 7, 26))
        odds_lifecycle._JSONL_ROWS_CACHE.clear()
        rows = odds_lifecycle._load_jsonl_rows(stale)
        seqs = [row["seq"] for row in rows]
        self.assertEqual(seqs[-1], 39_999)
        self.assertEqual(seqs, list(range(40_000 - len(seqs), 40_000)))

    def test_scan_is_rate_limited_off_the_append_path(self) -> None:
        odds_lifecycle._last_stale_scan_epoch = 0.0
        with patch.object(odds_lifecycle, "compact_stale_odds_lifecycle_files") as spy:
            for _ in range(5):
                odds_lifecycle._maybe_compact_stale_odds_lifecycle_files()
        self.assertEqual(spy.call_count, 1)

    def test_a_failing_scan_never_breaks_the_write_path(self) -> None:
        odds_lifecycle._last_stale_scan_epoch = 0.0
        with patch.object(odds_lifecycle, "compact_stale_odds_lifecycle_files", side_effect=RuntimeError("boom")):
            odds_lifecycle._maybe_compact_stale_odds_lifecycle_files()  # must not raise
    def test_the_read_path_also_triggers_the_scan(self) -> None:
        # The service holding the backlog is not the one writing it:
        # refresh-worker carries 2.66GB of these logs and emitted zero append
        # traces across 19 minutes, because the odds refresh appends on
        # live-odds-worker while refresh-worker only READS them. An
        # append-only hook would never have run on the box that needed it.
        odds_lifecycle._last_stale_scan_epoch = 0.0
        with patch.object(odds_lifecycle, "compact_stale_odds_lifecycle_files") as spy:
            odds_lifecycle.load_recent_odds_events(days_back=1, end_date="2026-07-26")
        spy.assert_called_once()


if __name__ == "__main__":
    unittest.main()
