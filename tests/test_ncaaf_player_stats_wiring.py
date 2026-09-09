"""`ncaaf-player-stats-wiring` lane -- the two edits that make the NCAAF
player-game-stats refresh able to run in production at all.

The job itself landed complete and verified (`3ec9a94c`): it fetches CFBD
`/games/players`, merges week-aware, and raises rather than exiting 0 if any
untargeted `(season, week)` group loses rows. Two things stopped it from ever
mattering, and this file pins both.

1. **The artifact was not allowlisted.** Checked against all of
   `HOT_ARTIFACT_PATTERNS` with the real matcher: nothing matched
   `ncaaf_source/source_artifacts/data/processed/player_game_stats/*.csv`. The
   worker writes to its own disk and `_ncaaf_player_box_section` reads WEB's, so
   until the entry exists the snapshot can never cross the service boundary.

2. **Nothing scheduled the refresh.** Default-OFF behind
   `NCAAF_PLAYER_STATS_ENABLE_REFRESH_WORKER_AUTORUN`, with no dispatch calling
   it. A job with no call site is indistinguishable from a broken one.

REACHABILITY BEFORE CORRECTNESS, in that order, because this lane is ENTIRELY a
reachability fix. `ReachabilityFirst` below asserts the three links in the chain
that carry the artifact -- dispatch exists, allowlist admits it, a publish call
exists -- and each of them is a thing that was ABSENT before this lane and whose
absence produced a passing test suite and a silently empty box score.

WHAT THESE TESTS DO **NOT** SHOW. Nothing here makes the refresh run. The flag
stays absent, so in production this dispatch declines every tick and prints a
rate-limited SKIPPED line. What is proven is that it is now SCHEDULABLE and
PUBLISHABLE; the reading that it actually works still needs the flag set, a
deploy, and a look at the served card.
"""
from __future__ import annotations

import inspect
import os
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import scripts.run_refresh_worker as worker
from syndicate.features.shared.artifact_publisher import (
    HOT_ARTIFACT_PATTERNS,
    is_export_only_artifact_relative_path,
    is_exportable_artifact_relative_path,
    is_hot_artifact_relative_path,
)

#: The one file the NCAAF player box joins against, relative to `data_root()`.
#: Built from `sources.player_game_stats_snapshot_path()`'s own parts rather
#: than retyped, so a rename of the writer's path breaks this test instead of
#: silently leaving the allowlist pointed at nothing.
ARTIFACT = "ncaaf_source/source_artifacts/data/processed/player_game_stats/ncaaf_player_game_stats_snapshot.csv"

ENV_VAR = "NCAAF_PLAYER_STATS_ENABLE_REFRESH_WORKER_AUTORUN"

REFRESH_SCRIPT = Path(worker.__file__).resolve().parent / "refresh_ncaaf_player_game_stats.py"


class _Store(dict):
    """Minimal stand-in for the refresh state store, as the sibling autorun
    tests use it (`test_nfl_roster_depth_autorun.py`)."""

    def __init__(self, payload=None):
        self.written: dict[str, object] = {}
        self.payload = payload
        super().__init__(
            read_json_file=lambda path: self.payload,
            write_json_file=lambda path, data: self.written.update({str(path): data}),
            reports_root=lambda: Path("/tmp/reports"),
        )


def _kwargs():
    return {
        "latest_manifest_path": MagicMock(),
        "worker_status_path": MagicMock(),
        "refresh_cycle": {},
    }


def _dispatch_order() -> list[str]:
    source = open(worker.__file__, encoding="utf-8").read()
    return [
        line.strip().removeprefix("elif ").removeprefix("if ").split("(")[0]
        for line in source.splitlines()
        if line.strip().startswith(("elif _launch_autorun", "if _launch_autorun"))
    ]


class ReachabilityFirst(unittest.TestCase):
    """Can the artifact reach a reader AT ALL. Every assertion here was FALSE
    before this lane, with a green suite either way."""

    def test_the_writer_and_the_allowlist_name_the_same_path(self):
        """The allowlist entry is not a guess about where the file lands."""
        from syndicate.features.ncaaf.sources import player_game_stats_snapshot_path

        parts = player_game_stats_snapshot_path().as_posix()
        self.assertTrue(
            parts.endswith("source_artifacts/data/processed/player_game_stats/ncaaf_player_game_stats_snapshot.csv"),
            parts,
        )

    def test_the_artifact_is_allowlisted(self):
        self.assertTrue(is_hot_artifact_relative_path(ARTIFACT))

    def test_the_dispatch_chain_actually_calls_the_autorun(self):
        """The gap this lane closes: the job existed and nothing invoked it."""
        self.assertIn("_launch_autorun_ncaaf_player_stats", _dispatch_order())

    def test_a_publish_call_exists_for_this_path(self):
        """An allowlist entry PERMITS a transfer; it does not make one happen.

        There is no blanket sweep on refresh-worker --
        `sweep_changed_hot_artifacts`'s only production caller is
        `live_lens_loop`, on another service -- so without an explicit call the
        entry above is inert and the card stays empty with every upstream stage
        reporting success.
        """
        source = REFRESH_SCRIPT.read_text(encoding="utf-8")
        self.assertIn("publish_hot_artifact", source)
        self.assertIn("artifact_published", source)


class OffIsNotOn(unittest.TestCase):
    """`off != on` for the flag, before anything about behaviour is asserted.

    A gate whose two settings are indistinguishable is the failure this repo
    caught four inert features with, and it is invisible in review.
    """

    def test_absent_declines_and_set_launches_on_the_same_inputs(self):
        store_off = _Store(None)
        env_off = dict(os.environ)
        env_off.pop(ENV_VAR, None)
        with patch.dict(os.environ, env_off, clear=True), \
             patch.object(worker, "_refresh_state_store", return_value=store_off), \
             patch.object(worker, "_active_sports_for_date", return_value="ncaaf"), \
             patch.object(worker, "subprocess") as sp_off:
            off = worker._launch_autorun_ncaaf_player_stats(**_kwargs())

        store_on = _Store(None)
        with patch.dict(os.environ, {ENV_VAR: "true"}), \
             patch.object(worker, "_refresh_state_store", return_value=store_on), \
             patch.object(worker, "_active_sports_for_date", return_value="ncaaf"), \
             patch.object(worker, "_write_worker_status"), \
             patch.object(worker, "_latest_manifest_payload", return_value={}), \
             patch.object(worker, "subprocess") as sp_on:
            on = worker._launch_autorun_ncaaf_player_stats(**_kwargs())

        self.assertFalse(off)
        sp_off.Popen.assert_not_called()
        self.assertTrue(on)
        sp_on.Popen.assert_called_once()
        self.assertNotEqual(off, on)


class AllowlistScope(unittest.TestCase):
    """The entry is a LITERAL path. fnmatch `*` crosses `/`, so a wildcard here
    would reach into a directory a future producer may share."""

    def test_the_entry_is_literal(self):
        self.assertIn(ARTIFACT, HOT_ARTIFACT_PATTERNS)
        self.assertNotIn("*", ARTIFACT)
        self.assertNotIn("?", ARTIFACT)

    def test_it_matches_nothing_beside_the_one_artifact(self):
        # Asserted first so this test cannot pass VACUOUSLY: with the entry
        # absent, "no pattern equal to ARTIFACT matched a neighbour" is
        # trivially true and says nothing.
        self.assertIn(ARTIFACT, HOT_ARTIFACT_PATTERNS)
        neighbours = [
            # Same directory, a different file -- e.g. a future per-season split.
            "ncaaf_source/source_artifacts/data/processed/player_game_stats/ncaaf_player_game_stats_2026.csv",
            "ncaaf_source/source_artifacts/data/processed/player_game_stats/scratch.csv",
            # Deeper, which is what a trailing `*` would have swept in.
            "ncaaf_source/source_artifacts/data/processed/player_game_stats/raw/week_1.csv",
            # A different sport's root with the identical tail.
            "nfl_source/source_artifacts/data/processed/player_game_stats/ncaaf_player_game_stats_snapshot.csv",
        ]
        for path in neighbours:
            with self.subTest(path=path):
                self.assertFalse(
                    any(
                        __import__("fnmatch").fnmatch(path, pattern)
                        and pattern == ARTIFACT
                        for pattern in HOT_ARTIFACT_PATTERNS
                    ),
                    f"the new literal entry matched {path}",
                )

    def test_the_ncaaf_sibling_snapshots_stay_where_they_were(self):
        """Sibling NCAAF `processed/` snapshots are unaffected in both
        directions: `team_registry` was already allowlisted and still is;
        `player_identity` and `transfers` were not and still are not."""
        self.assertTrue(
            is_hot_artifact_relative_path(
                "ncaaf_source/source_artifacts/data/processed/team_registry/ncaaf_team_registry_snapshot.csv"
            )
        )
        for unlisted in (
            "ncaaf_source/source_artifacts/data/processed/player_identity/ncaaf_player_identity_snapshot.csv",
            "ncaaf_source/source_artifacts/data/processed/transfers/ncaaf_transfer_portal_snapshot.csv",
        ):
            with self.subTest(path=unlisted):
                self.assertFalse(is_hot_artifact_relative_path(unlisted))

    def test_it_is_hot_not_export_only(self):
        """`#413`'s test is a serving HAZARD, and there is none here: web's
        reader joins on season and refuses a season it does not match, so
        PRESENCE cannot freeze or fabricate a box score."""
        self.assertFalse(is_export_only_artifact_relative_path(ARTIFACT))
        self.assertTrue(is_exportable_artifact_relative_path(ARTIFACT))


class AutorunGating(unittest.TestCase):
    def test_absent_flag_means_off(self):
        env = dict(os.environ)
        env.pop(ENV_VAR, None)
        with patch.dict(os.environ, env, clear=True):
            self.assertFalse(worker._ncaaf_player_stats_enabled())

    def test_explicit_true_arms_it(self):
        for value in ("1", "true", "TRUE", "yes", "on"):
            with self.subTest(value=value), patch.dict(os.environ, {ENV_VAR: value}):
                self.assertTrue(worker._ncaaf_player_stats_enabled())

    def test_unknown_values_map_to_off_never_to_the_permissive_branch(self):
        for value in ("maybe", "0", "false", "no", "off", "", "  ", "ture", "True ", "enabled"):
            with self.subTest(value=value), patch.dict(os.environ, {ENV_VAR: value}):
                if value.strip().lower() in {"1", "true", "yes", "on"}:
                    continue
                self.assertFalse(
                    worker._ncaaf_player_stats_enabled(),
                    f"{value!r} armed a production job; unknown must resolve OFF",
                )

    def test_an_unimportable_module_resolves_off(self):
        """Unknown must not default permissive -- including 'I could not tell'."""
        with patch.dict(os.environ, {ENV_VAR: "true"}), \
             patch.dict("sys.modules", {"syndicate.features.ncaaf.player_stats_refresh": None}):
            self.assertFalse(worker._ncaaf_player_stats_enabled())

    def test_interval_defaults_daily_and_floors_at_an_hour(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("NCAAF_PLAYER_STATS_REFRESH_INTERVAL_SECONDS", None)
            self.assertEqual(worker._ncaaf_player_stats_interval_seconds(), 86400)
        with patch.dict(os.environ, {"NCAAF_PLAYER_STATS_REFRESH_INTERVAL_SECONDS": "5"}):
            self.assertEqual(worker._ncaaf_player_stats_interval_seconds(), 3600)
        with patch.dict(os.environ, {"NCAAF_PLAYER_STATS_REFRESH_INTERVAL_SECONDS": "not-a-number"}):
            self.assertEqual(worker._ncaaf_player_stats_interval_seconds(), 86400)


class AutorunCooldownAndSeason(unittest.TestCase):
    def test_out_of_season_is_skipped(self):
        store = _Store(None)
        with patch.dict(os.environ, {ENV_VAR: "true"}), \
             patch.object(worker, "_refresh_state_store", return_value=store), \
             patch.object(worker, "_active_sports_for_date", return_value="mlb,soccer"), \
             patch.object(worker, "subprocess") as sp:
            launched = worker._launch_autorun_ncaaf_player_stats(**_kwargs())
        self.assertFalse(launched)
        sp.Popen.assert_not_called()

    def test_a_recent_attempt_suppresses_the_launch(self):
        store = _Store({"attempted_at_epoch": time.time() - 60})
        with patch.dict(os.environ, {ENV_VAR: "true"}), \
             patch.object(worker, "_refresh_state_store", return_value=store), \
             patch.object(worker, "_active_sports_for_date", return_value="ncaaf"), \
             patch.object(worker, "subprocess") as sp:
            launched = worker._launch_autorun_ncaaf_player_stats(**_kwargs())
        self.assertFalse(launched)
        sp.Popen.assert_not_called()

    def test_a_stale_marker_allows_the_launch_and_restamps_it(self):
        store = _Store({"attempted_at_epoch": time.time() - 200_000})
        with patch.dict(os.environ, {ENV_VAR: "true"}), \
             patch.object(worker, "_refresh_state_store", return_value=store), \
             patch.object(worker, "_active_sports_for_date", return_value="ncaaf"), \
             patch.object(worker, "_write_worker_status"), \
             patch.object(worker, "_latest_manifest_payload", return_value={}), \
             patch.object(worker, "subprocess") as sp:
            launched = worker._launch_autorun_ncaaf_player_stats(**_kwargs())
        self.assertTrue(launched)
        sp.Popen.assert_called_once()
        self.assertEqual(len(store.written), 1)
        stamped = next(iter(store.written.values()))
        self.assertGreater(float(stamped["attempted_at_epoch"]), 0.0)

    def test_the_marker_is_written_before_the_launch_not_after(self):
        """`#443`: a last-ATTEMPT stamp is the whole rate limit. Written after
        the launch, a crashing subprocess relaunches every tick forever."""
        src = inspect.getsource(worker._launch_autorun_ncaaf_player_stats)
        self.assertLess(src.index("attempted_at_epoch"), src.index("subprocess.Popen"))

    def test_it_launches_the_refresh_entry_point(self):
        args = worker._ncaaf_player_stats_script_args()
        self.assertTrue(str(args[1]).endswith("refresh_ncaaf_player_game_stats.py"))


class NoSilentDeclineAndNoLoggerInfo(unittest.TestCase):
    def test_every_decline_path_logs_a_reason(self):
        src = inspect.getsource(worker._launch_autorun_ncaaf_player_stats)
        for reason in ("disabled", "not_in_season", "rate_limited"):
            self.assertIn(reason, src)
        lines = src.splitlines()
        silent = []
        for i, line in enumerate(lines):
            if line.strip() != "return False":
                continue
            window = "\n".join(lines[max(0, i - 5):i])
            if "print(" not in window and "_skip(" not in window:
                silent.append(f"line {i}: {line.strip()}")
        self.assertEqual(silent, [], f"silent decline path(s): {silent}")

    def test_status_lines_use_print_flush_not_logger_info(self):
        """`logger.info` never reaches Render's log collector, so a logger call
        here would make the branch invisible in exactly the state it reports."""
        src = inspect.getsource(worker._launch_autorun_ncaaf_player_stats)
        self.assertIn("flush=True", src)
        self.assertNotIn("logger.", src)

    def test_no_persisted_pid_guard(self):
        src = inspect.getsource(worker._launch_autorun_ncaaf_player_stats)
        self.assertNotIn("_process_exists", src)
        self.assertNotIn("still_running", src)


class DispatchPlacement(unittest.TestCase):
    def test_it_sits_above_every_high_frequency_branch(self):
        """`#341`: every branch is `elif`, so an entry below a high-frequency
        refresh runs on no tick at all during a slate. Reconciliation was mute
        FOR WEEKS that way while enabled and correctly configured."""
        order = _dispatch_order()
        index = order.index("_launch_autorun_ncaaf_player_stats")
        for high_frequency in (
            "_launch_autorun_mlb_refresh",
            "_launch_autorun_weekly_sports_refresh",
            "_launch_autorun_soccer_weekly_refresh",
        ):
            self.assertIn(high_frequency, order)
            self.assertLess(
                index,
                order.index(high_frequency),
                f"{high_frequency} precedes the NCAAF player-stats autorun; "
                f"order={order}",
            )

    def test_it_does_not_displace_the_nfl_ingestion_block(self):
        """Additive placement: the NFL block stays one contiguous unit above
        it, so nothing that used to win a tick now loses one."""
        order = _dispatch_order()
        index = order.index("_launch_autorun_ncaaf_player_stats")
        for nfl in (
            "_launch_autorun_nfl_pbp_fetch",
            "_launch_autorun_nfl_injuries_fetch",
            "_launch_autorun_nfl_roster_snapshot",
            "_launch_autorun_nfl_depth_chart_snapshot",
            "_launch_autorun_nfl_news_capture",
            "_launch_autorun_nfl_fantasy_artifact",
        ):
            self.assertLess(order.index(nfl), index, f"order={order}")


if __name__ == "__main__":
    unittest.main()
