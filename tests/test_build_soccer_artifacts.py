from __future__ import annotations

import importlib.util
import io
import unittest
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch


def _load_module(repo_root: Path):
    script_path = repo_root / "scripts" / "build_soccer_artifacts.py"
    spec = importlib.util.spec_from_file_location("test_build_soccer_artifacts", script_path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


class LoadPlayerRowsTests(unittest.TestCase):
    # #170. Root-caused live 2026-07-31: MLS's board had a fully populated
    # match-level sim (real win probability, projected score, "Simulations:
    # 400") but zero player props for its one match of the day, while every
    # other tracked league had real player-prop counts on the same board at
    # the same time. Traced to `_load_player_rows` having no error path for
    # a missing/empty roster CSV (the same "no error path" shape #146/#148
    # already found and fixed one step downstream of this exact function) --
    # an empty or absent `players/` directory silently returns `[]`, so
    # `adapter.simulate_props()` runs "successfully" every cycle with zero
    # player_outputs and nothing anywhere flags it. These tests lock in the
    # new SOCCER_PLAYER_ROWS_MISSING diagnostic for both failure shapes
    # (directory absent; files present but empty) without changing the
    # return value in either case, and confirm the real-data path is silent
    # and unaffected.

    def test_missing_players_directory_logs_and_returns_empty(self) -> None:
        module = _load_module(Path(__file__).resolve().parents[1])
        with TemporaryDirectory() as tmp_dir:
            source_root = Path(tmp_dir)
            with patch("sys.stdout", new_callable=StringIO) as captured_stdout:
                rows = module._load_player_rows("mls", source_root)

        self.assertEqual(rows, [])
        log_output = captured_stdout.getvalue()
        self.assertIn("SOCCER_PLAYER_ROWS_MISSING", log_output)
        self.assertIn("league=mls", log_output)

    def test_empty_players_csv_logs_and_returns_empty(self) -> None:
        module = _load_module(Path(__file__).resolve().parents[1])
        with TemporaryDirectory() as tmp_dir:
            source_root = Path(tmp_dir)
            players_dir = source_root / "mls" / "players"
            players_dir.mkdir(parents=True)
            (players_dir / "players_2026.csv").write_text(
                "league,season,player_id,player_name,team,position,minutes,games,"
                "shots_per90,xg_per90,xa_per90,goals_per90,assists_per90,"
                "key_passes_per90,expected_minutes_share,is_goalkeeper,source\n",
                encoding="utf-8",
            )
            with patch("sys.stdout", new_callable=StringIO) as captured_stdout:
                rows = module._load_player_rows("mls", source_root)

        self.assertEqual(rows, [])
        log_output = captured_stdout.getvalue()
        self.assertIn("SOCCER_PLAYER_ROWS_MISSING", log_output)
        self.assertIn("league=mls", log_output)

    def test_real_roster_data_loads_silently(self) -> None:
        module = _load_module(Path(__file__).resolve().parents[1])
        repo_root = Path(__file__).resolve().parents[1]
        source_root = repo_root / "data" / "soccer_source"

        with patch("sys.stdout", new_callable=StringIO) as captured_stdout:
            rows = module._load_player_rows("mls", source_root)

        self.assertGreater(len(rows), 0)
        self.assertNotIn("SOCCER_PLAYER_ROWS_MISSING", captured_stdout.getvalue())
        teams = {str(row.get("team") or "") for row in rows}
        self.assertIn("New York City FC", teams)
        self.assertIn("Toronto FC", teams)


_PLAYER_HEADER = (
    "league,season,player_id,player_name,team,position,minutes,games,"
    "shots_per90,xg_per90,xa_per90,goals_per90,assists_per90,"
    "key_passes_per90,expected_minutes_share,is_goalkeeper,source\n"
)


def _player_row(season: int, pid: str, name: str, team: str = "Arsenal") -> str:
    return (
        f"epl,{season},{pid},{name},{team},F,900,10,"
        "2.0,0.4,0.2,0.3,0.1,1.0,0.8,False,understat\n"
    )


def _write_players(source_root, season: int, rows: str) -> None:
    players_dir = source_root / "epl" / "players"
    players_dir.mkdir(parents=True, exist_ok=True)
    (players_dir / f"players_{season}.csv").write_text(_PLAYER_HEADER + rows, encoding="utf-8")


def _patch_roster(module, names: list[str]):
    """Control what the ESPN roster says, at the READ.

    `_current_roster_names` goes through `sources.roster_rows`, which resolves
    across `_source_roots()` -- the runtime disk AND the git-shipped repo
    fallback. A roster CSV written into a TemporaryDirectory is therefore
    never read, and a test that wrote one would pass by accident whenever the
    name it invented happens to exist in the real repo roster (both "Nwaneri"
    and "Viktor Gyokeres" do). Patching the read is the only way these assert
    on their own fixture.
    """
    return patch.object(
        module,
        "roster_rows",
        return_value=tuple({"player_name": name} for name in names),
    )


class DepartedPlayerTests(unittest.TestCase):
    """`_load_player_rows` concatenated every season's file and deduped by
    `player_id` keeping the newest row. That asks "what is this player's
    latest row" and never "is this player still here", so anyone who ever
    played in the league survived forever under their last-known club.

    Measured on production 2026-08-20 (Arsenal v Coventry): the sim published
    a 28-man Arsenal squad including Thomas Partey, Kieran Tierney, Jorginho,
    Raheem Sterling and Jakub Kiwior -- all departed, none in
    `players_2025.csv`, all carried by a 2024 row. The five two-season
    leagues held 160-215 stale-only players each, and by this function's own
    reasoning about duplicates, every extra squad member dilutes each real
    teammate's shot and prop share.
    """

    def _module(self):
        return _load_module(Path(__file__).resolve().parents[1])

    def test_a_player_absent_from_the_latest_season_is_dropped(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            source_root = Path(tmp_dir)
            _write_players(source_root, 2024, _player_row(2024, "u1", "Stays") + _player_row(2024, "u2", "Departed"))
            _write_players(source_root, 2025, _player_row(2025, "u1", "Stays"))
            with patch("sys.stdout", new_callable=StringIO) as out:
                rows = self._module()._load_player_rows("epl", source_root)
        names = {r["player_name"] for r in rows}
        self.assertIn("Stays", names)
        self.assertNotIn("Departed", names)
        self.assertIn("SOCCER_DEPARTED_PLAYERS_DROPPED", out.getvalue())

    def test_the_roster_RESCUES_a_current_player_with_no_latest_season_row(self) -> None:
        """The load-bearing half, and the reason this is a union and not a
        latest-season filter. Filtering on the season alone would have
        dropped Ethan Nwaneri and Reiss Nelson -- both genuinely at Arsenal,
        both carrying a real bookmaker price, neither with a 2025 stats row.
        Across the ten leagues the roster rescues 121 such players."""
        with TemporaryDirectory() as tmp_dir:
            source_root = Path(tmp_dir)
            _write_players(source_root, 2024, _player_row(2024, "u1", "Stays") + _player_row(2024, "u2", "Nwaneri"))
            _write_players(source_root, 2025, _player_row(2025, "u1", "Stays"))
            module = self._module()
            with _patch_roster(module, ["Stays", "Nwaneri"]):
                rows = module._load_player_rows("epl", source_root)
        self.assertEqual({r["player_name"] for r in rows}, {"Stays", "Nwaneri"})

    def test_the_roster_never_deletes_a_player_it_omits(self) -> None:
        """DIRECTION IS THE DESIGN. Measured 2026-08-20: used as a FILTER the
        roster would have wrongly dropped 1,970 current-season players --
        several roster files are badly incomplete (bundesliga 142 rows vs 567
        players with stats) and the name join is lossy. A player in the
        latest season must survive a roster that has never heard of them."""
        with TemporaryDirectory() as tmp_dir:
            source_root = Path(tmp_dir)
            _write_players(source_root, 2024, _player_row(2024, "u1", "Current"))
            _write_players(source_root, 2025, _player_row(2025, "u1", "Current"))
            module = self._module()
            with _patch_roster(module, ["SomebodyElse"]):
                rows = module._load_player_rows("epl", source_root)
        self.assertEqual({r["player_name"] for r in rows}, {"Current"})

    def test_roster_match_ignores_diacritics(self) -> None:
        """The roster spells them "Viktor Gyokeres" and "Gabriel Magalhaes"
        where the stats feed does not. Shares `_norm_player_name` with
        `features/lineups.py` so the identity that keeps a player here is the
        one `attach_confirmed_starters` uses to match a confirmed XI."""
        with TemporaryDirectory() as tmp_dir:
            source_root = Path(tmp_dir)
            _write_players(source_root, 2024, _player_row(2024, "u1", "A") + _player_row(2024, "u2", "Viktor Gyokeres"))
            _write_players(source_root, 2025, _player_row(2025, "u1", "A"))
            module = self._module()
            with _patch_roster(module, ["Viktor Gy\u00f6keres"]):
                rows = module._load_player_rows("epl", source_root)
        self.assertIn("Viktor Gyokeres", {r["player_name"] for r in rows})

    def test_a_single_season_league_is_untouched(self) -> None:
        """No earlier file means no stale population is possible. Five of the
        ten leagues are in this state and must be unaffected."""
        with TemporaryDirectory() as tmp_dir:
            source_root = Path(tmp_dir)
            _write_players(source_root, 2026, _player_row(2026, "u1", "A") + _player_row(2026, "u2", "B"))
            with patch("sys.stdout", new_callable=StringIO) as out:
                rows = self._module()._load_player_rows("epl", source_root)
        self.assertEqual(len(rows), 2)
        self.assertNotIn("SOCCER_DEPARTED_PLAYERS_DROPPED", out.getvalue())

    def test_a_thin_new_season_file_disables_filtering_and_says_so(self) -> None:
        """A new season's file starts empty and fills up. Filtering against a
        half-written file would delete most of the league on the first build
        of a season -- and the failure would look exactly like this fix
        working, which is why it degrades loudly instead of silently."""
        with TemporaryDirectory() as tmp_dir:
            source_root = Path(tmp_dir)
            _write_players(
                source_root, 2025,
                "".join(_player_row(2025, f"u{i}", f"P{i}") for i in range(10)),
            )
            _write_players(source_root, 2026, _player_row(2026, "u0", "P0"))
            with patch("sys.stdout", new_callable=StringIO) as out:
                rows = self._module()._load_player_rows("epl", source_root)
        self.assertEqual(len(rows), 10)
        self.assertIn("SOCCER_LATEST_SEASON_FILE_THIN", out.getvalue())

    def test_an_absent_roster_still_filters_rather_than_skipping(self) -> None:
        """An absent roster means no rescues, not no filtering. Treating it
        as a reason to skip would make the fix silently inert on exactly the
        leagues whose roster feed is weakest."""
        with TemporaryDirectory() as tmp_dir:
            source_root = Path(tmp_dir)
            _write_players(source_root, 2024, _player_row(2024, "u1", "Stays") + _player_row(2024, "u2", "Departed"))
            _write_players(source_root, 2025, _player_row(2025, "u1", "Stays"))
            module = self._module()
            with _patch_roster(module, []), patch("sys.stdout", new_callable=StringIO) as out:
                rows = module._load_player_rows("epl", source_root)
        self.assertEqual({r["player_name"] for r in rows}, {"Stays"})
        self.assertIn("SOCCER_ROSTER_EMPTY", out.getvalue())

    def test_against_the_real_mirror_the_known_departures_go_and_the_known_squad_stays(self) -> None:
        """The production case that started this, end to end on real data."""
        module = self._module()
        source_root = Path(__file__).resolve().parents[1] / "data" / "soccer_source"
        if not (source_root / "epl" / "players").exists():
            self.skipTest("epl mirror not present in this checkout")
        rows = module._load_player_rows("epl", source_root)
        arsenal = {str(r.get("player_name")) for r in rows if "Arsenal" in str(r.get("team"))}
        for departed in ("Thomas Partey", "Jorginho", "Kieran Tierney", "Raheem Sterling", "Jakub Kiwior"):
            self.assertNotIn(departed, arsenal)
        # Rescued by the roster: no 2025 stats row, but really at the club and
        # really priced by the book.
        for current in ("Ethan Nwaneri", "Reiss Nelson"):
            self.assertIn(current, arsenal)

class RosterReadReachabilityTests(unittest.TestCase):
    """The rescue shipped INERT and this is the test that would have caught it.

    The first version globbed `source_root / league / "api" / "rosters"` -- a
    SINGLE root. Measured in production 2026-08-20 23:17:45Z on the first
    artifact rebuilt by the deployed code: Arsenal 28 -> 21 with
    `rescued_by_roster` effectively zero, dropping Ethan Nwaneri and Reiss
    Nelson, both really at the club and both really priced. Locally the same
    code returned 23, because locally that one root happens to hold the file.

    `sources._api_read_path` iterates `_source_roots()` -- runtime disk AND
    the git-shipped repo fallback -- and `rosters_*.csv` is absent from
    `HOT_ARTIFACT_PATTERNS`, so on a worker the fallback is the ONLY route to
    it. Asserting the READ PATH, not the outcome: an outcome test passes on a
    dev box either way, which is exactly how this reached production.
    """

    def test_the_roster_is_read_through_sources_not_a_single_root_glob(self) -> None:
        """Asserts the CALL, not the source text.

        The first version of this test grepped the file for the old glob
        expression -- and failed, because that string still appears in the
        COMMENT explaining why the glob was wrong. A test that a comment can
        break is testing prose. Patching `roster_rows` and asserting it is
        actually invoked tests the mechanism: if anyone reverts to a direct
        glob, this goes red regardless of what the comments say.
        """
        module = _load_module(Path(__file__).resolve().parents[1])
        with patch.object(module, "roster_rows", return_value=({"player_name": "X"},)) as mocked:
            names = module._current_roster_names("epl")
        mocked.assert_called_once()
        self.assertEqual(names, {"x"})

    def test_every_league_roster_is_git_tracked_so_the_fallback_can_find_it(self) -> None:
        """The fallback only works on files the checkout actually ships. If a
        league's roster ever stops being tracked, its rescues go silently to
        zero on every worker -- the same failure, one file at a time."""
        import subprocess

        out = subprocess.run(
            ["git", "ls-files", "data/soccer_source/*/api/rosters/rosters_*.csv"],
            capture_output=True, text=True, cwd=Path(__file__).resolve().parents[1],
        ).stdout
        tracked = [line for line in out.splitlines() if line.strip()]
        self.assertGreaterEqual(len(tracked), 10, f"only {len(tracked)} roster files tracked")

if __name__ == "__main__":
    unittest.main()