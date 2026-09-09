"""The NCAAF player-game-stats snapshot refresh.

Every fixture here is shaped like the REAL CFBD ``/games/players`` response.
The shape was re-confirmed live on 2026-09-09 against
``https://api.collegefootballdata.com/games/players?year=2026&week=1&seasonType=regular``:
HTTP 200, **203 games, 6.01 MB**, which the refresh turned into **4,937 rows**
for ``season=2026 week=1``. The same call for ``week=2`` returned HTTP 200
with an **empty list** -- that is the real behaviour the no-op guard exists
for, not a hypothetical.
"""

from __future__ import annotations

import csv
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from syndicate.features.ncaaf import player_stats_refresh as refresh_module
from syndicate.features.ncaaf.player_stats_refresh import (
    AUTORUN_ENV_VAR,
    DEFAULT_INTERVAL_SECONDS,
    INTERVAL_ENV_VAR,
    MIN_INTERVAL_SECONDS,
    NcaafPlayerStatsHistoryLoss,
    player_stats_autorun_enabled,
    player_stats_refresh_interval_seconds,
    refresh_player_game_stats,
    refresh_week,
    snapshot_columns,
    weeks_to_refresh,
)


def _games_players_fixture(*, game_id: int = 401856667) -> list[dict]:
    """One game in CFBD's real ``/games/players`` shape: a flat list of games,
    each with ``id`` and ``teams``; each team with ``team``/``categories``;
    each category with ``name``/``types``; each type with ``name``/``athletes``
    (``{id, name, stat}``, ``stat`` ALWAYS a string, including the combined
    ``C/ATT`` form and ``"--"`` for an unavailable value)."""
    return [
        {
            "id": game_id,
            "teams": [
                {
                    "team": "Texas",
                    "conference": "SEC",
                    "homeAway": "away",
                    "points": 38,
                    "categories": [
                        {
                            "name": "passing",
                            "types": [
                                {"name": "C/ATT", "athletes": [{"id": "4432762", "name": "Arch Manning", "stat": "22/30"}]},
                                {"name": "YDS", "athletes": [{"id": "4432762", "name": "Arch Manning", "stat": "305"}]},
                                {"name": "TD", "athletes": [{"id": "4432762", "name": "Arch Manning", "stat": "3"}]},
                                {"name": "INT", "athletes": [{"id": "4432762", "name": "Arch Manning", "stat": "1"}]},
                                {"name": "QBR", "athletes": [{"id": "4432762", "name": "Arch Manning", "stat": "--"}]},
                            ],
                        },
                        {
                            "name": "rushing",
                            "types": [
                                {"name": "CAR", "athletes": [{"id": "4432762", "name": "Arch Manning", "stat": "5"}]},
                                {"name": "YDS", "athletes": [{"id": "4432762", "name": "Arch Manning", "stat": "6"}]},
                                {"name": "TD", "athletes": [{"id": "4432762", "name": "Arch Manning", "stat": "0"}]},
                            ],
                        },
                        {
                            "name": "receiving",
                            "types": [
                                {"name": "REC", "athletes": [{"id": "4685362", "name": "Ryan Wingo", "stat": "7"}]},
                                {"name": "YDS", "athletes": [{"id": "4685362", "name": "Ryan Wingo", "stat": "121"}]},
                                {"name": "TD", "athletes": [{"id": "4685362", "name": "Ryan Wingo", "stat": "1"}]},
                            ],
                        },
                    ],
                },
                {
                    "team": "Texas State",
                    "conference": "Pac-12",
                    "homeAway": "home",
                    "points": 7,
                    "categories": [
                        {
                            "name": "rushing",
                            "types": [
                                {"name": "CAR", "athletes": [{"id": "4916885", "name": "Jaylen Jenkins", "stat": "9"}]},
                                {"name": "YDS", "athletes": [{"id": "4916885", "name": "Jaylen Jenkins", "stat": "51"}]},
                                {"name": "TD", "athletes": [{"id": "4916885", "name": "Jaylen Jenkins", "stat": "1"}]},
                            ],
                        }
                    ],
                },
            ],
        }
    ]


class _FakeClient:
    """Records every fetch so a test can assert a call was NOT made -- the
    only way to tell "gated" apart from "ran and found nothing"."""

    def __init__(self, payload_by_week: dict[int, list[dict]] | None = None):
        self.payload_by_week = payload_by_week or {}
        self.calls: list[tuple[int, int, str]] = []

    def fetch_player_game_stats(self, *, season: int, week: int, season_type: str = "regular"):
        self.calls.append((season, week, season_type))
        return list(self.payload_by_week.get(week, []))


def _seed_prior_season_csv(path: Path, *, rows: int = 25, season: int = 2025) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = snapshot_columns()
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for index in range(rows):
            week = (index % 16) + 1
            payload = {column: "" for column in columns}
            payload.update(
                {
                    "season": str(season),
                    "week": str(week),
                    "game_id": f"400000{index:03d}",
                    "player_id": f"90000{index:03d}",
                    "player_name": f"Prior Season Player {index}",
                    "team": "Abilene Christian",
                    "source_system": "cfbd",
                    "source_snapshot_date": "2026-08-26",
                }
            )
            writer.writerow(payload)


def _read_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


class TestAutorunFlag(unittest.TestCase):
    def test_absent_means_off(self) -> None:
        self.assertFalse(player_stats_autorun_enabled({}))

    def test_affirmative_values_are_on(self) -> None:
        for value in ("1", "true", "TRUE", "yes", "on", " On "):
            with self.subTest(value=value):
                self.assertTrue(player_stats_autorun_enabled({AUTORUN_ENV_VAR: value}))

    def test_unknown_value_defaults_off_not_permissive(self) -> None:
        """A typo must not arm a scheduled production job."""
        for value in ("", "maybe", "0", "false", "no", "off", "enabled"):
            with self.subTest(value=value):
                self.assertFalse(player_stats_autorun_enabled({AUTORUN_ENV_VAR: value}))


class TestInterval(unittest.TestCase):
    def test_default_is_daily(self) -> None:
        self.assertEqual(player_stats_refresh_interval_seconds({}), DEFAULT_INTERVAL_SECONDS)

    def test_floor_is_enforced(self) -> None:
        self.assertEqual(player_stats_refresh_interval_seconds({INTERVAL_ENV_VAR: "5"}), MIN_INTERVAL_SECONDS)

    def test_unparseable_falls_back_to_default(self) -> None:
        self.assertEqual(player_stats_refresh_interval_seconds({INTERVAL_ENV_VAR: "soon"}), DEFAULT_INTERVAL_SECONDS)

    def test_explicit_value_is_honoured(self) -> None:
        self.assertEqual(player_stats_refresh_interval_seconds({INTERVAL_ENV_VAR: "43200"}), 43200)


class TestWeekWindow(unittest.TestCase):
    def test_trailing_window_includes_the_previous_week(self) -> None:
        self.assertEqual(weeks_to_refresh(3), (2, 3))

    def test_lookback_of_one_is_the_target_week_only(self) -> None:
        self.assertEqual(weeks_to_refresh(3, lookback_weeks=1), (3,))

    def test_window_never_runs_below_week_one(self) -> None:
        self.assertEqual(weeks_to_refresh(1), (1,))

    def test_unresolved_target_week_yields_no_window(self) -> None:
        """None means "season not loaded / all games complete". Guessing a
        week would spend a CFBD call to learn nothing."""
        self.assertEqual(weeks_to_refresh(None), ())


class TestWeekFetchMapsToSchema(unittest.TestCase):
    def test_fetched_week_maps_onto_the_csv_schema(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "snapshot.csv"
            client = _FakeClient({1: _games_players_fixture()})
            result = refresh_week(client=client, season=2026, week=1, output_path=path, source_snapshot_date="2026-09-09")

            self.assertFalse(result.skipped)
            self.assertEqual(result.games_fetched, 1)
            self.assertEqual(result.validation_issues, ())

            rows = _read_rows(path)
            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                header = tuple(next(csv.reader(handle)))
            self.assertEqual(header, snapshot_columns())
            self.assertEqual(len(rows), result.rows_written)

            by_name = {row["player_name"]: row for row in rows}
            manning = by_name["Arch Manning"]
            self.assertEqual(manning["season"], "2026")
            self.assertEqual(manning["week"], "1")
            self.assertEqual(manning["game_id"], "401856667")
            self.assertEqual(manning["team"], "Texas")
            self.assertEqual(manning["source_system"], "cfbd")
            self.assertEqual(manning["source_snapshot_date"], "2026-09-09")
            # "22/30" is CFBD's combined C/ATT string, the one stat in the
            # real response shape that needs splitting rather than a parse.
            self.assertEqual(float(manning["passing_completions"]), 22.0)
            self.assertEqual(float(manning["passing_attempts"]), 30.0)
            self.assertEqual(float(manning["passing_yards"]), 305.0)
            self.assertEqual(float(manning["passing_tds"]), 3.0)
            self.assertEqual(float(manning["interceptions"]), 1.0)
            # A dual-threat QB appears in BOTH passing and rushing and must
            # merge into ONE row, not two.
            self.assertEqual(float(manning["rushing_yards"]), 6.0)
            self.assertEqual(len([row for row in rows if row["player_name"] == "Arch Manning"]), 1)

            wingo = by_name["Ryan Wingo"]
            self.assertEqual(float(wingo["receptions"]), 7.0)
            self.assertEqual(float(wingo["receiving_yards"]), 121.0)
            self.assertEqual(float(wingo["anytime_td"]), 1.0)

            # Both teams in the game are represented, not just the winner.
            self.assertEqual({row["team"] for row in rows}, {"Texas", "Texas State"})


class TestHistoryIsPreserved(unittest.TestCase):
    def test_prior_season_rows_survive_a_current_season_refresh(self) -> None:
        """The whole point: 35,829 rows of 2025 must not be spent to gain one
        week of 2026."""
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "snapshot.csv"
            _seed_prior_season_csv(path, rows=25)
            before = _read_rows(path)
            self.assertEqual(len(before), 25)

            client = _FakeClient({1: _games_players_fixture()})
            result = refresh_week(client=client, season=2026, week=1, output_path=path)

            after = _read_rows(path)
            prior = [row for row in after if row["season"] == "2025"]
            current = [row for row in after if row["season"] == "2026"]
            self.assertEqual(len(prior), 25, "a 2026 refresh deleted 2025 rows")
            self.assertEqual([row["player_name"] for row in prior], [row["player_name"] for row in before])
            self.assertEqual(len(current), result.rows_written)
            self.assertGreater(len(current), 0)
            self.assertEqual(len(after), 25 + result.rows_written)

    def test_refreshing_the_same_week_twice_replaces_rather_than_duplicates(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "snapshot.csv"
            _seed_prior_season_csv(path, rows=10)
            client = _FakeClient({1: _games_players_fixture()})
            first = refresh_week(client=client, season=2026, week=1, output_path=path)
            second = refresh_week(client=client, season=2026, week=1, output_path=path)

            after = _read_rows(path)
            self.assertEqual(first.rows_written, second.rows_written)
            self.assertEqual(len([row for row in after if row["season"] == "2026"]), second.rows_written)
            self.assertEqual(len([row for row in after if row["season"] == "2025"]), 10)

    def test_a_second_week_extends_rather_than_replaces_the_first(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "snapshot.csv"
            client = _FakeClient(
                {
                    1: _games_players_fixture(game_id=401856667),
                    2: _games_players_fixture(game_id=401856999),
                }
            )
            refresh_week(client=client, season=2026, week=1, output_path=path)
            refresh_week(client=client, season=2026, week=2, output_path=path)
            after = _read_rows(path)
            self.assertGreater(len([row for row in after if row["week"] == "1"]), 0)
            self.assertGreater(len([row for row in after if row["week"] == "2"]), 0)

    def test_a_write_that_drops_untargeted_rows_raises(self) -> None:
        """Guards the guard: if the merge ever stops being (season, week)
        aware, this fails loudly instead of reporting a successful refresh."""
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "snapshot.csv"
            _seed_prior_season_csv(path, rows=12)

            def _clobbering_write(**kwargs):
                target = kwargs["output_path"]
                with target.open("w", encoding="utf-8", newline="") as handle:
                    writer = csv.DictWriter(handle, fieldnames=snapshot_columns(), extrasaction="ignore")
                    writer.writeheader()
                raise AssertionError("unreachable -- replaced below")

            class _Result:
                rows = ()
                validation_issues = ()

            def _drop_history(**kwargs):
                target = kwargs["output_path"]
                with target.open("w", encoding="utf-8", newline="") as handle:
                    writer = csv.DictWriter(handle, fieldnames=snapshot_columns(), extrasaction="ignore")
                    writer.writeheader()
                return _Result()

            client = _FakeClient({1: _games_players_fixture()})
            with patch.object(refresh_module, "write_ncaaf_player_game_stats_snapshot_csv", _drop_history):
                with self.assertRaises(NcaafPlayerStatsHistoryLoss) as ctx:
                    refresh_week(client=client, season=2026, week=1, output_path=path)
            self.assertIn("2025", str(ctx.exception))


class TestEmptyWeekIsANoOp(unittest.TestCase):
    def test_a_week_with_no_completed_games_does_not_touch_the_file(self) -> None:
        """CFBD answers an unplayed week with HTTP 200 and ``[]`` -- measured
        live for 2026 week 2 on 2026-09-09. Writing that response is how a
        scheduled job destroys the artifact it maintains."""
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "snapshot.csv"
            _seed_prior_season_csv(path, rows=30)
            original_bytes = path.read_bytes()
            original_mtime = path.stat().st_mtime_ns

            client = _FakeClient({2: []})
            result = refresh_week(client=client, season=2026, week=2, output_path=path)

            self.assertTrue(result.skipped)
            self.assertEqual(result.skip_reason, "no_completed_games")
            self.assertEqual(result.rows_written, 0)
            self.assertEqual(path.read_bytes(), original_bytes, "an empty week rewrote the snapshot")
            self.assertEqual(path.stat().st_mtime_ns, original_mtime, "an empty week reopened the snapshot")

    def test_a_payload_with_no_player_rows_is_also_a_no_op(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "snapshot.csv"
            _seed_prior_season_csv(path, rows=8)
            original_bytes = path.read_bytes()
            client = _FakeClient({3: [{"id": 401800001, "teams": []}]})
            result = refresh_week(client=client, season=2026, week=3, output_path=path)
            self.assertTrue(result.skipped)
            self.assertEqual(result.skip_reason, "no_player_rows")
            self.assertEqual(path.read_bytes(), original_bytes)

    def test_an_empty_week_does_not_create_a_missing_file(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "nested" / "snapshot.csv"
            client = _FakeClient({1: []})
            result = refresh_week(client=client, season=2026, week=1, output_path=path)
            self.assertTrue(result.skipped)
            self.assertFalse(path.exists())


class TestMultiWeekRun(unittest.TestCase):
    def test_a_window_mixes_written_and_skipped_weeks(self) -> None:
        """The real 2026-09-09 state: week 1 played, week 2 not yet."""
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "snapshot.csv"
            _seed_prior_season_csv(path, rows=20)
            client = _FakeClient({1: _games_players_fixture(), 2: []})
            report = refresh_player_game_stats(client=client, season=2026, weeks=(1, 2), output_path=path)

            self.assertTrue(report.ok)
            self.assertEqual(report.weeks_refreshed, (1,))
            self.assertEqual(report.weeks_skipped, (2,))
            self.assertEqual(report.total_rows_before, 20)
            self.assertEqual(report.total_rows_after, 20 + report.rows_written)
            self.assertEqual([call[1] for call in client.calls], [1, 2])

    def test_report_serialises(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "snapshot.csv"
            client = _FakeClient({1: _games_players_fixture()})
            report = refresh_player_game_stats(client=client, season=2026, weeks=(1,), output_path=path)
            payload = report.as_dict()
            self.assertEqual(payload["season"], 2026)
            self.assertEqual(payload["weeks_refreshed"], [1])
            self.assertTrue(payload["ok"])


class TestScriptGating(unittest.TestCase):
    """The flag absent means the job does not run -- and, crucially, does not
    reach CFBD. `off != on` is asserted in both directions."""

    def _main(self):
        import importlib.util

        script = Path(__file__).resolve().parents[1] / "scripts" / "refresh_ncaaf_player_game_stats.py"
        spec = importlib.util.spec_from_file_location("_refresh_ncaaf_player_game_stats_under_test", script)
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return module

    def test_flag_absent_means_the_job_does_not_run(self) -> None:
        module = self._main()
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "snapshot.csv"
            _seed_prior_season_csv(path, rows=5)
            with patch.dict("os.environ", {}, clear=False) as _env:
                import os

                os.environ.pop(AUTORUN_ENV_VAR, None)
                with patch.object(module, "CfbdClient") as fake_client_cls:
                    code = module.main(["--season", "2026", "--weeks", "1", "--output-path", str(path), "--json"])
            self.assertEqual(code, 0)
            fake_client_cls.from_env.assert_not_called()
            self.assertEqual(len(_read_rows(path)), 5)

    def test_flag_true_lets_the_job_run(self) -> None:
        module = self._main()
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "snapshot.csv"
            _seed_prior_season_csv(path, rows=5)
            client = _FakeClient({1: _games_players_fixture()})
            with patch.dict("os.environ", {AUTORUN_ENV_VAR: "true"}):
                with patch.object(module, "CfbdClient") as fake_client_cls:
                    fake_client_cls.from_env.return_value = client
                    code = module.main(["--season", "2026", "--weeks", "1", "--output-path", str(path), "--json"])
            self.assertEqual(code, 0)
            fake_client_cls.from_env.assert_called_once()
            rows = _read_rows(path)
            self.assertEqual(len([row for row in rows if row["season"] == "2025"]), 5)
            self.assertGreater(len([row for row in rows if row["season"] == "2026"]), 0)

    def test_force_overrides_an_absent_flag(self) -> None:
        module = self._main()
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "snapshot.csv"
            client = _FakeClient({1: _games_players_fixture()})
            import os

            with patch.dict("os.environ", {}, clear=False):
                os.environ.pop(AUTORUN_ENV_VAR, None)
                with patch.object(module, "CfbdClient") as fake_client_cls:
                    fake_client_cls.from_env.return_value = client
                    code = module.main(
                        ["--force", "--season", "2026", "--weeks", "1", "--output-path", str(path), "--json"]
                    )
            self.assertEqual(code, 0)
            self.assertGreater(len(_read_rows(path)), 0)

    def test_no_resolvable_week_window_is_a_benign_no_op(self) -> None:
        module = self._main()
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "snapshot.csv"
            with patch.dict("os.environ", {AUTORUN_ENV_VAR: "true"}):
                with patch.object(module, "CfbdClient") as fake_client_cls:
                    with patch.object(module, "_resolve_weeks", return_value=()):
                        code = module.main(["--season", "2026", "--output-path", str(path), "--json"])
            self.assertEqual(code, 0)
            fake_client_cls.from_env.assert_not_called()
            self.assertFalse(path.exists())

    def test_a_missing_cfbd_key_exits_two_and_says_so(self) -> None:
        module = self._main()
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "snapshot.csv"
            with patch.dict("os.environ", {AUTORUN_ENV_VAR: "true"}):
                with patch.object(module, "CfbdClient") as fake_client_cls:
                    fake_client_cls.from_env.side_effect = RuntimeError("Missing CFBD API key.")
                    code = module.main(["--season", "2026", "--weeks", "1", "--output-path", str(path), "--json"])
            self.assertEqual(code, 2)


class TestCardJoinFindsCurrentSeasonRows(unittest.TestCase):
    """The user-visible half. The refusal to render last season's numbers is
    CORRECT and stays; what changes is that a current season with real rows
    now populates instead of falling into the same empty state."""

    def _clear_caches(self) -> None:
        from syndicate.features.ncaaf import cards as ncaaf_cards
        from syndicate.features.ncaaf import player_stats

        player_stats.load_player_game_rows.cache_clear()
        player_stats.player_name_index.cache_clear()
        ncaaf_cards._ncaaf_player_rows_for_week.cache_clear()

    def _section(self, path: Path, *, season: int, week: int):
        from syndicate.features.ncaaf import cards as ncaaf_cards
        from syndicate.features.ncaaf import player_stats

        self._clear_caches()
        game = {
            "away": {"name": "Texas", "abbr": "TEX"},
            "home": {"name": "Texas State", "abbr": "TXST"},
        }
        try:
            with patch.object(player_stats, "player_game_stats_snapshot_path", return_value=path):
                return ncaaf_cards._ncaaf_player_box_section(game, season=season, week=week)
        finally:
            self._clear_caches()

    def test_empty_state_before_the_refresh_and_real_rows_after(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "snapshot.csv"
            _seed_prior_season_csv(path, rows=40)

            before = self._section(path, season=2026, week=1)
            self.assertEqual(before["chip"], "Not published")
            self.assertEqual(before["rows"], [])
            self.assertIn("2026", before["body"])

            client = _FakeClient({1: _games_players_fixture()})
            refresh_week(client=client, season=2026, week=1, output_path=path)

            after = self._section(path, season=2026, week=1)
            self.assertEqual(after["chip"], "Final")
            self.assertTrue(after["table_rows"], "the player box stayed empty after a successful refresh")
            self.assertEqual(after["columns"], ["Player", "Tm", "Pass yds", "Rush yds", "Rec yds", "TD"])

            names = [row[0] for row in after["table_rows"]]
            self.assertIn("Arch Manning", names)
            manning = next(row for row in after["table_rows"] if row[0] == "Arch Manning")
            self.assertEqual(manning[1], "TEX")
            self.assertEqual(manning[2], "305")
            # Both sides of the game reach the box, mapped to their own abbr.
            self.assertIn("TXST", {row[1] for row in after["table_rows"]})

    def test_a_season_with_no_rows_still_refuses_after_the_refresh_exists(self) -> None:
        """The standing rule, re-asserted: gaining a refresh path must not
        turn the empty state into last season's numbers under this game."""
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "snapshot.csv"
            _seed_prior_season_csv(path, rows=40)
            client = _FakeClient({1: _games_players_fixture()})
            refresh_week(client=client, season=2026, week=1, output_path=path)

            other = self._section(path, season=2027, week=1)
            self.assertEqual(other["chip"], "Not published")
            self.assertEqual(other["rows"], [])

    def test_the_wrong_week_of_the_right_season_also_refuses(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "snapshot.csv"
            client = _FakeClient({1: _games_players_fixture()})
            refresh_week(client=client, season=2026, week=1, output_path=path)
            other = self._section(path, season=2026, week=5)
            self.assertEqual(other["chip"], "Not published")


if __name__ == "__main__":
    unittest.main()
