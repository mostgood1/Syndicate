from __future__ import annotations

import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class NcaabRefreshRunnerTests(unittest.TestCase):
    def _load_module(self):
        repo_root = Path(__file__).resolve().parents[1]
        script_path = repo_root / "scripts" / "refresh_ncaab_odds_history.py"
        spec = importlib.util.spec_from_file_location("test_refresh_ncaab_odds_history", script_path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_main_writes_source_compatible_odds_filename(self) -> None:
        module = self._load_module()

        class _FakeRow:
            def model_dump(self):
                return {"event_id": "evt-1", "market": "h2h", "book": "DraftKings"}

        class _FakeAdapter:
            def __init__(self, region: str = "us") -> None:
                self.region = region

            def iter_current_odds_expanded(self, *, markets: str, date_iso: str, bookmakers: str | None = None):
                return [_FakeRow()]

        with tempfile.TemporaryDirectory() as tmp_dir:
            out_dir = Path(tmp_dir) / "odds_history"
            argv = [
                "refresh_ncaab_odds_history.py",
                "--date",
                "2026-05-22",
                "--out-dir",
                str(out_dir),
            ]
            # `--out-dir` covers the odds CSV but NOT the quote log: `main()` also
            # calls `_append_ncaab_book_quotes` -> `append_book_quotes`, which
            # resolves `data/ncaab_source/tracking/book_quotes/<date>.jsonl` from
            # `data_root()` and ignores `--out-dir` entirely. That is the same
            # artifact family as the `book_quotes/.jsonl` write this guard was
            # built for, one sport over.
            with patch.dict(
                os.environ, {"SYNDICATE_DATA_ROOT": str(Path(tmp_dir) / "data_root")}
            ), patch.object(module, "_load_source_adapter", return_value=_FakeAdapter), patch("sys.argv", argv):
                rc = module.main()

            self.assertEqual(rc, 0)
            self.assertTrue((out_dir / "odds_2026-05-22.csv").exists())
            self.assertFalse((out_dir / "odds_history_2026-05-22.csv").exists())

    def test_main_accepts_legacy_source_root_flag(self) -> None:
        module = self._load_module()

        class _FakeRow:
            def model_dump(self):
                return {"event_id": "evt-1", "market": "h2h", "book": "DraftKings"}

        class _FakeAdapter:
            def __init__(self, region: str = "us") -> None:
                self.region = region

            def iter_current_odds_expanded(self, *, markets: str, date_iso: str, bookmakers: str | None = None):
                return [_FakeRow()]

        with tempfile.TemporaryDirectory() as tmp_dir:
            out_dir = Path(tmp_dir) / "odds_history"
            argv = [
                "refresh_ncaab_odds_history.py",
                "--date",
                "2026-05-22",
                "--source-root",
                tmp_dir,
                "--out-dir",
                str(out_dir),
            ]
            # `--out-dir` covers the odds CSV but NOT the quote log: `main()` also
            # calls `_append_ncaab_book_quotes` -> `append_book_quotes`, which
            # resolves `data/ncaab_source/tracking/book_quotes/<date>.jsonl` from
            # `data_root()` and ignores `--out-dir` entirely. That is the same
            # artifact family as the `book_quotes/.jsonl` write this guard was
            # built for, one sport over.
            with patch.dict(
                os.environ, {"SYNDICATE_DATA_ROOT": str(Path(tmp_dir) / "data_root")}
            ), patch.object(module, "_load_source_adapter", return_value=_FakeAdapter), patch("sys.argv", argv):
                rc = module.main()

            self.assertEqual(rc, 0)
            self.assertTrue((out_dir / "odds_2026-05-22.csv").exists())

    # The two tests above patch `_load_source_adapter` with a fake, so neither
    # ever built the REAL client -- and the real client's constructor is where
    # every fleet NCAAB fetch died (2026-11-01: 65 of 65 runs, "TheOddsAPI key
    # not set"), because the fleet sets only the shared `ODDS_API_KEY`.
    _KEY_NAMES = ("NCAAB_THEODDS_API_KEY", "THEODDSAPI_KEY", "THEODDS_API_KEY", "ODDS_API_KEY")

    def _env_with(self, **keys: str) -> dict[str, str]:
        env = {name: value for name, value in os.environ.items() if name not in self._KEY_NAMES}
        env.update(keys)
        return env

    def test_real_client_builds_from_the_shared_key_alone(self) -> None:
        module = self._load_module()
        with patch.dict(os.environ, self._env_with(ODDS_API_KEY="shared-key"), clear=True):
            client = module._load_source_adapter(None)(region="us")
        self.assertEqual(client.api_key, "shared-key")
        self.assertEqual(client.sport_key, "basketball_ncaab")

    def test_ncaab_specific_key_still_wins_over_the_shared_key(self) -> None:
        module = self._load_module()
        env = self._env_with(NCAAB_THEODDS_API_KEY="ncaab-key", ODDS_API_KEY="shared-key")
        with patch.dict(os.environ, env, clear=True):
            self.assertEqual(module._load_api_key(), "ncaab-key")

    def test_no_key_at_all_still_refuses(self) -> None:
        module = self._load_module()
        with patch.dict(os.environ, self._env_with(), clear=True):
            with self.assertRaises(ValueError):
                module._load_api_key()

    # 2026-11-02 opener: the slate-date path captured 16 of ~130 priced games and
    # wrote every half line as a full-game line.
    def test_oddsapi_half_suffixes_are_labelled_as_halves(self) -> None:
        infer = self._load_module().TheOddsApiClient._infer_period_from_key
        self.assertEqual(infer("spreads_h1"), "1h")
        self.assertEqual(infer("totals_h2"), "2h")
        self.assertEqual(infer("spreads"), "full_game")
        self.assertEqual(infer("h2h"), "full_game")

    def test_bulk_full_game_for_every_game_and_halves_only_in_the_live_window(self) -> None:
        import datetime as dt

        module = self._load_module()
        now = dt.datetime(2026, 11, 3, 1, 0, tzinfo=dt.timezone.utc)
        commence = {
            "soon": now + dt.timedelta(minutes=10),       # tips in 10 min: both halves
            "live": now - dt.timedelta(minutes=90),       # first half over: second half only
            "later": now + dt.timedelta(hours=5),         # outside the window: bulk only
        }
        calls: list[tuple] = []

        class _Adapter:
            def iter_current_odds_expanded(self, *, markets, date_iso, bookmakers=None):
                calls.append(("bulk", markets))
                return [{"event_id": eid, "commence_time": ct, "period": "full_game", "market": "spreads"} for eid, ct in commence.items()]

            def iter_event_odds(self, event_id, *, markets, bookmakers=None, fallback_full_game=True):
                calls.append(("event", event_id, markets, fallback_full_game))
                return [{"event_id": event_id, "period": "2h", "market": "totals"}]

        rows = module._fetch_current_rows(
            adapter=_Adapter(), date_iso="2026-11-02",
            markets="h2h,spreads,totals,spreads_h1,totals_h1,spreads_h2,totals_h2", bookmakers=None, now=now,
        )
        self.assertEqual(calls[0], ("bulk", "h2h,spreads,totals"))
        per_event = {c[1]: c for c in calls if c[0] == "event"}
        self.assertEqual(set(per_event), {"soon", "live"})
        self.assertEqual(per_event["soon"][2], "spreads_h1,totals_h1,spreads_h2,totals_h2")
        self.assertEqual(per_event["live"][2], "spreads_h2,totals_h2")
        # A half-only request must never fall back to a paid full-game request.
        self.assertTrue(all(c[3] is False for c in per_event.values()))
        self.assertEqual(len(rows), 3 + 2)

    def test_full_game_only_markets_make_exactly_one_bulk_call(self) -> None:
        module = self._load_module()
        calls: list[str] = []

        class _Adapter:
            def iter_current_odds_expanded(self, *, markets, date_iso, bookmakers=None):
                calls.append(markets)
                return []

            def iter_event_odds(self, *a, **k):  # pragma: no cover - must not be reached
                raise AssertionError("per-event call without half markets")

        module._fetch_current_rows(adapter=_Adapter(), date_iso="2026-11-02", markets="h2h,spreads,totals", bookmakers=None)
        self.assertEqual(calls, ["h2h,spreads,totals"])

    def test_quote_log_uses_the_shared_segment_names(self) -> None:
        module = self._load_module()
        captured: list[dict] = []
        rows = [
            {"event_id": "e", "book": "BetMGM", "period": period, "market": "totals", "total": line, "over_price": -110, "under_price": -110}
            for period, line in (("full_game", 153.5), ("1h", 75.5), ("2h", 78.5))
        ]
        with patch("syndicate.features.shared.odds_book_quotes.append_book_quotes", lambda **kw: captured.extend(kw["rows"])):
            module._append_ncaab_book_quotes(rows, date_iso="2026-11-02")
        by_segment = {(q["segment"], q["line"]) for q in captured}
        self.assertEqual(by_segment, {("full", 153.5), ("h1", 75.5), ("h2", 78.5)})
