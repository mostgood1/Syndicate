"""todo #784: the outcome gate for *_LIVE_MECHANISMS env changes, and deploy_preflight's OUTCOME_GATE verdict.

Why it exists: NCAAB RC46 passed a gate that scored the margin's MEAN while live prices read its DISTRIBUTION, went
live on 2026-11-10 with every lock passing, and was reverted on outcome scoring (learnings 2026-11-11). These pin:
one hash and one receipt predicate shared by the gate and preflight; the scoring flags a worse candidate and not an
equal one; and preflight's verdict REACHES OUTCOME_GATE for a changed key under --reinject-env and only then.
"""
from __future__ import annotations

import importlib.util
import io
import json
import sys
import tempfile
import time
import types
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


gate = _load("live_mechanism_outcome_gate_under_test", "scripts/live_mechanism_outcome_gate.py")
deploy_preflight = _load("deploy_preflight_outcome_gate_under_test", "scripts/deploy_preflight.py")

OLD = '{"endgame_foul_window_s": 120, "blowout_margin": 999, "solver_endgame_pts_per_team": 0.2}'
NEW = '{"endgame_foul_window_s": 120, "blowout_margin": 999, "solver_endgame_pts_per_team": 0.46, "score_effect_k": 0.005}'
KEY = "SYNDICATE_NCAAB_LIVE_MECHANISMS"


def _receipt(directory, *, candidate=NEW, current=OLD, games=240, worse=(), age_s=60.0, league="ncaab"):
    return gate.write_receipt(Path(directory), {
        "league": league, "candidate_hash": gate.value_hash(candidate), "current_hash": gate.value_hash(current),
        "games": games, "worse": list(worse), "better": [], "written_at": time.time() - age_s,
        "written_at_iso": "2026-11-11T18:00:00Z"})


class HashTests(unittest.TestCase):
    def test_one_value_one_hash_whatever_the_spelling(self) -> None:
        a = '{"b": 1, "a": [0.25, 0.5]}'
        b = '  {"a":[0.25,0.5],"b":1}\n'
        self.assertEqual(gate.value_hash(a), gate.value_hash(b))
        self.assertNotEqual(gate.value_hash(a), gate.value_hash('{"a": [0.25, 0.5], "b": 2}'))

    def test_unset_is_one_value(self) -> None:
        self.assertEqual(gate.value_hash(""), gate.value_hash(None))
        self.assertEqual(gate.value_hash("   "), gate.value_hash(""))
        self.assertNotEqual(gate.value_hash(""), gate.value_hash("{}"))

    def test_a_windows_worktree_resolves_to_the_primary_tree_from_wsl_and_from_windows(self) -> None:
        text = "gitdir: C:/Users/me/Coding/Syndicate/.git/worktrees/bell-1\n"
        self.assertEqual(gate.root_from_gitfile(text, Path("/x"), windows=False).as_posix(),
                         "/mnt/c/Users/me/Coding/Syndicate")
        self.assertEqual(gate.root_from_gitfile(text, Path("C:/x"), windows=True).name, "Syndicate")
        self.assertIsNone(gate.root_from_gitfile("not a gitfile", Path("/x"), windows=False))

    def test_league_of_key(self) -> None:
        self.assertEqual(gate.league_of_key(KEY), "ncaab")
        self.assertEqual(gate.league_of_key("SYNDICATE_NBA_LIVE_MECHANISMS"), "nba")
        self.assertIsNone(gate.league_of_key("SYNDICATE_NCAAB_HALF_SPLIT"))


class ScoringTests(unittest.TestCase):
    @staticmethod
    def _features(brier, in80_margin, crps=5.0):
        return {"margin_crps": crps, "margin_in80": in80_margin, "total_crps": 7.0, "total_in80": 1.0,
                "win_brier": brier, "win_logloss": brier * 3, "margin_sd": 10.0, "margin_err": 0.0}

    def test_a_candidate_worse_on_every_game_is_flagged_and_an_equal_one_is_not(self) -> None:
        paired = {f"g{i}": {"20m": {"current": self._features(0.10, 1.0),
                                    "candidate": self._features(0.12 + 0.001 * (i % 5), 1.0)}}
                  for i in range(60)}
        worse, better = gate.flag_cells(gate.score_cells(paired, ["20m"]))
        self.assertIn("20m:win_brier", worse)
        self.assertIn("20m:win_logloss", worse)
        same = {g: {"20m": {"current": v["20m"]["current"], "candidate": dict(v["20m"]["current"])}}
                for g, v in paired.items()}
        self.assertEqual(gate.flag_cells(gate.score_cells(same, ["20m"])), ([], []))

    def test_coverage_is_scored_as_distance_from_nominal_not_as_higher(self) -> None:
        # current covers 100% (over-wide), candidate 80% (nominal): the candidate is BETTER although it covers less.
        paired = {f"g{i}": {"30m": {"current": self._features(0.1, 1.0),
                                    "candidate": self._features(0.1, 1.0 if i % 5 else 0.0)}}
                  for i in range(200)}
        cells = gate.score_cells(paired, ["30m"])
        self.assertAlmostEqual(cells["30m"]["margin_cov80_dev"]["candidate_coverage"], 0.8)
        worse, better = gate.flag_cells(cells)
        self.assertIn("30m:margin_cov80_dev", better)
        self.assertNotIn("30m:margin_cov80_dev", worse)

    def test_the_mean_shifts_are_reported_when_the_features_carry_means(self) -> None:
        def feats(total_mean):
            return {**self._features(0.1, 1.0), "total_mean": total_mean, "margin_mean": 3.0}
        paired = {f"g{i}": {"0m": {"current": feats(140.0), "candidate": feats(140.5)}} for i in range(30)}
        info = gate.score_cells(paired, ["0m"])["0m"]["_info"]
        self.assertAlmostEqual(info["total_mean_shift"], 0.5)
        self.assertAlmostEqual(info["margin_mean_shift"], 0.0)
        # features without means (older callers) still score, with no shift reported
        self.assertNotIn("total_mean_shift", gate.score_cells(
            {"g": {"0m": {"current": self._features(0.1, 1.0), "candidate": self._features(0.1, 1.0)}}}, ["0m"])["0m"]["_info"])

    def test_game_features_reads_state_window_and_overtime(self) -> None:
        cp = {"rows": [[10, 5, 0, 0], [12, 6, 5, 3]], "h0": 60, "a0": 50, "home_win_prob": 0.9}
        f = gate.game_features(cp, 72, 56)
        self.assertEqual(f["win_brier"], (0.9 - 1.0) ** 2)
        # margins: 60-50+10-5 = 15 and 60-50+12-6+5-3 = 18; the final is 16, inside the central 80%
        self.assertEqual(f["margin_in80"], 1.0)


class ReceiptTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.cand, self.cur = gate.value_hash(NEW), gate.value_hash(OLD)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _check(self, accept=""):
        return gate.check_receipt(self.dir, "ncaab", self.cand, self.cur, time.time(), accept)

    def test_round_trip_names_the_exact_transition(self) -> None:
        path = _receipt(self.dir)
        self.assertEqual(path.name, gate.receipt_name("ncaab", self.cand, self.cur))
        problem, detail = self._check()
        self.assertIsNone(problem, problem)
        self.assertEqual(detail["games"], 240)
        # the reverse transition is a different receipt
        problem, _ = gate.check_receipt(self.dir, "ncaab", self.cur, self.cand, time.time())
        self.assertIn("no outcome-gate receipt", problem)

    def test_missing_stale_thin_renamed_and_unsupported_all_refuse(self) -> None:
        self.assertIn("no outcome-gate receipt", self._check()[0])
        _receipt(self.dir, age_s=8 * 86400)
        self.assertIn("days old", self._check()[0])
        _receipt(self.dir, games=54)
        self.assertIn("floor", self._check()[0])
        path = _receipt(self.dir)
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["current_hash"] = "0" * 64
        path.write_text(json.dumps(payload), encoding="utf-8")
        self.assertIn("different transition", self._check()[0])
        self.assertIn("no outcome replay exists", gate.check_receipt(self.dir, "nba", self.cand, self.cur, time.time())[0])

    def test_worse_cells_refuse_unless_accepted_and_the_acceptance_is_recorded(self) -> None:
        _receipt(self.dir, worse=["20m:win_brier", "36m:win_brier"])
        problem, _ = self._check()
        self.assertIn("20m:win_brier", problem)
        problem, detail = self._check(accept="user accepted the 20 m cost for the late gain")
        self.assertIsNone(problem)
        self.assertEqual(detail["accepted_regression"], "user accepted the 20 m cost for the late gain")


class PreflightPieceTests(unittest.TestCase):
    def test_parse_reads_both_sections_and_refuses_a_half_read(self) -> None:
        text = ("@@DERIVED\n" + f"{KEY}={NEW}\n" + "@@ENVRC=0\n@@RUNNING\n" + f"{KEY}={OLD}\n" + "@@PROC=ok\n")
        running, derived = deploy_preflight.parse_mechanism_sections(text)
        self.assertEqual(derived[KEY], NEW)
        self.assertEqual(running[KEY], OLD)
        with self.assertRaises(RuntimeError):
            deploy_preflight.parse_mechanism_sections(text.replace("@@ENVRC=0", "@@ENVRC=1"))
        with self.assertRaises(RuntimeError):
            deploy_preflight.parse_mechanism_sections(text.replace("@@PROC=ok", "@@PROC=unreadable"))

    def test_changes_are_by_value_not_by_spelling(self) -> None:
        self.assertEqual(deploy_preflight.mechanism_changes({KEY: OLD}, {KEY: json.dumps(json.loads(OLD))}), [])
        changes = deploy_preflight.mechanism_changes({KEY: OLD}, {KEY: NEW})
        self.assertEqual([c["key"] for c in changes], [KEY])
        self.assertEqual(changes[0]["candidate_hash"], gate.value_hash(NEW))
        added = deploy_preflight.mechanism_changes({}, {KEY: NEW})
        self.assertFalse(added[0]["current_set"])

    def test_problem_only_when_required_and_unknown_is_not_clear(self) -> None:
        changes = deploy_preflight.mechanism_changes({KEY: OLD}, {KEY: NEW})
        with tempfile.TemporaryDirectory() as tmp:
            on, _ = deploy_preflight.outcome_gate_problem(changes, "", True, tmp, time.time())
            off, _ = deploy_preflight.outcome_gate_problem(changes, "", False, tmp, time.time())
            self.assertIsNotNone(on)
            self.assertIsNone(off)
            unread, _ = deploy_preflight.outcome_gate_problem([], "wsl rc=1", True, tmp, time.time())
            self.assertIn("unknown", unread)
            waived, detail = deploy_preflight.outcome_gate_problem(changes, "", True, tmp, time.time(), "urgent revert")
            self.assertIsNone(waived)
            self.assertEqual(detail["waived"], "urgent revert")


STATUS_TEXT = """HEAD=b2cdb6ed6aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
supervisor pid=523171 since 2026-10-25T15:15:35+00:00 state=redis
  web               pid=523186 up  rss=942 MB (cap 2048 MB)  restarts=0  code=b2cdb6ed
  refresh-worker    pid=1467610 up  rss=4246 MB (cap 6144 MB)  restarts=10  code=b2cdb6ed
  live-odds-worker  pid=1822371 up  rss=1200 MB (cap 2048 MB)  restarts=0  code=b2cdb6ed
"""


class PreflightReachabilityTests(unittest.TestCase):
    """off != on through main(): the same fleet, the same change; only --reinject-env and the receipt differ."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _run(self, *extra, mech=(lambda role, pid: ({KEY: OLD}, {KEY: NEW}))):
        status = deploy_preflight.parse_fleet_status(STATUS_TEXT)

        def fake_processes(role, now):
            started = (now - timedelta(seconds=7200)).isoformat().replace("+00:00", "Z")
            return [], {"worker_pid": 1, "worker_age_seconds": 7200}, {"id": "fleet pid 1", "status": "live",
                                                                      "createdAt": started}

        captured = {}

        def fake_receipt(args, report, verdict, reason, live_commit):
            captured.update(report=report, verdict=verdict, reason=reason)

        def no_render(*_a, **_k):
            raise AssertionError("the fleet path must not call Render")

        stamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        mech_mock = mock.Mock(side_effect=mech)
        with mock.patch.object(deploy_preflight, "_api_key", side_effect=no_render), \
             mock.patch.object(deploy_preflight, "_get", side_effect=no_render), \
             mock.patch.object(deploy_preflight, "fleet_status", return_value=("b2cdb6ed6" + "a" * 31, status)), \
             mock.patch.object(deploy_preflight, "fleet_role_processes", side_effect=fake_processes), \
             mock.patch.object(deploy_preflight, "read_board_build_state", return_value=(False, {})), \
             mock.patch.object(deploy_preflight, "is_ancestor", return_value=True), \
             mock.patch.object(deploy_preflight, "_write_receipt", side_effect=fake_receipt), \
             mock.patch.object(deploy_preflight, "fleet_mechanism_values", mech_mock), \
             mock.patch.object(deploy_preflight, "_main_worktree_root", return_value=self.root), \
             mock.patch.object(deploy_preflight.sys, "argv",
                               ["deploy_preflight.py", "--target", "fleet", "--service", "live-odds-worker",
                                "--holder", "me", "--expect", "x=1", "--baseline", "x=0",
                                "--baseline-read-at", stamp, *extra]), \
             mock.patch.dict(sys.modules, {"deploy_claim": types.SimpleNamespace(active_claim=lambda _s: None)}), \
             redirect_stdout(io.StringIO()):
            code = deploy_preflight.main()
        return code, captured, mech_mock

    def test_a_changed_key_without_a_receipt_is_OUTCOME_GATE(self) -> None:
        code, got, mech = self._run("--reinject-env")
        self.assertEqual(got["verdict"], "OUTCOME_GATE", got["reason"])
        self.assertEqual(code, deploy_preflight.EXIT_OUTCOME_GATE)
        mech.assert_called_once_with("live-odds-worker", "1822371")
        self.assertIn(KEY, got["reason"])

    def test_the_same_change_with_a_fresh_receipt_is_CLEAR_and_names_it(self) -> None:
        _receipt(gate.receipt_dir(self.root))
        code, got, _ = self._run("--reinject-env")
        self.assertEqual(got["verdict"], "CLEAR", got["reason"])
        self.assertIn("outcome gate: ncaab__", got["reason"])

    def test_without_reinject_env_the_fleet_env_is_not_read(self) -> None:
        code, got, mech = self._run()
        self.assertEqual(got["verdict"], "CLEAR", got["reason"])
        mech.assert_not_called()
        self.assertIsNone(got["report"]["outcome_gate"])

    def test_an_unreadable_env_is_OUTCOME_GATE_not_CLEAR(self) -> None:
        def boom(role, pid):
            raise RuntimeError("fleet shell rc=1")
        code, got, _ = self._run("--reinject-env", mech=boom)
        self.assertEqual(got["verdict"], "OUTCOME_GATE")
        self.assertIn("fleet shell rc=1", got["reason"])

    def test_the_waiver_clears_and_is_on_the_report(self) -> None:
        code, got, _ = self._run("--reinject-env", "--no-outcome-gate", "urgent revert of RC46")
        self.assertEqual(got["verdict"], "CLEAR", got["reason"])
        self.assertEqual(got["report"]["outcome_gate"]["waived"], "urgent revert of RC46")
        self.assertIn("OUTCOME GATE WAIVED", got["reason"])

    def test_no_change_is_CLEAR(self) -> None:
        code, got, _ = self._run("--reinject-env", mech=lambda role, pid: ({KEY: OLD}, {KEY: OLD}))
        self.assertEqual(got["verdict"], "CLEAR", got["reason"])
        self.assertIn("no *_LIVE_MECHANISMS change", got["reason"])


if __name__ == "__main__":
    unittest.main()
