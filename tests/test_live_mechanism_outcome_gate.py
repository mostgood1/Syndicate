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


class SeedSaltTests(unittest.TestCase):
    """todo #765 STEP 3j: `--seed-salt` re-seeds the candidate arm only (an A/A noise check), salt 0 is inert, and a
    salted receipt can never clear preflight."""

    def test_salt_zero_is_the_gates_own_seed_and_each_salt_is_a_different_one(self) -> None:
        self.assertEqual(gate.salted_seed(123456, 0), 123456)
        s1, s2 = gate.salted_seed(123456, 1), gate.salted_seed(123456, 2)
        self.assertNotIn(s1, (123456, s2))
        self.assertEqual(s1, gate.salted_seed(123456, 1))
        self.assertTrue(0 <= s1 < 2 ** 31 and 0 <= s2 < 2 ** 31)

    def test_every_arm_carries_its_own_salt(self) -> None:
        arms = [("current@0", OLD, 0), ("current@1001", OLD, 1001), ("candidate", NEW, 2)]
        jobs = gate.build_jobs([{"game_id": "a"}, {"game_id": "b"}], arms, {"0m": 0.0}, 5)
        self.assertEqual(len(jobs), 6)
        self.assertEqual({(j[1], j[2], j[5]) for j in jobs},
                         {("current@0", OLD, 0), ("current@1001", OLD, 1001), ("candidate", NEW, 2)})
        self.assertEqual(gate.current_salt_list(4), [0, 1001, 1002, 1003])
        self.assertEqual(gate.current_salt_list(1), [0])

    def test_the_replay_seeds_the_engine_with_the_salted_seed(self) -> None:
        sys.path.insert(0, str(ROOT))
        from syndicate.features.ncaab import live_resim as lr

        seen: list[int] = []

        def fake_resim(inputs, state, *, sims, base_seed, simulate, league):
            seen.append(base_seed)
            return {"home_win_prob": 0.5}

        mech = lr.live_mechanisms_from_env({KEY: OLD})
        inputs = {**{k: None for k in lr._ENGINE_KWARGS}, "cfg": types.SimpleNamespace(**mech),
                  "home_players": {"athlete_id": [], "player_name": []},
                  "away_players": {"athlete_id": [], "player_name": []}}
        task = {"game_id": "401999", "date": "2026-11-05", "team_ids": {"home": 1, "away": 2}, "neutral": False,
                "codes": {"home": "AAA", "away": "BBB"}, "final": {"home": 70, "away": 60}}
        with mock.patch.object(lr, "build_engine_inputs", return_value=inputs), \
             mock.patch.object(lr, "ncaab_engine"), \
             mock.patch.object(lr, "resim_live_game", side_effect=fake_resim), \
             mock.patch.object(gate, "_harness"), \
             mock.patch.dict("os.environ"):
            for salt in (0, 1):
                out = gate._replay_ncaab(task, "candidate", OLD, {"0m": 0.0}, 3, salt)
                self.assertIn("0m", out["cps"], out)
        base = lr.stable_seed("401999", 0, "ncaab")
        self.assertEqual(seen, [base, gate.salted_seed(base, 1)])
        self.assertNotEqual(seen[0], seen[1])

    def test_a_salted_receipt_has_its_own_name_and_never_clears(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            path = gate.write_receipt(d, {"league": "ncaab", "candidate_hash": gate.value_hash(OLD),
                                          "current_hash": gate.value_hash(OLD), "games": 360, "worse": [],
                                          "better": [], "written_at": time.time(), "seed_salt": 1})
            self.assertTrue(path.name.endswith("__salt1.json"), path.name)
            problem, _ = gate.check_receipt(d, "ncaab", gate.value_hash(OLD), gate.value_hash(OLD), time.time())
            self.assertIn("no outcome-gate receipt", problem)
            path.rename(d / gate.receipt_name("ncaab", gate.value_hash(OLD), gate.value_hash(OLD)))
            problem, _ = gate.check_receipt(d, "ncaab", gate.value_hash(OLD), gate.value_hash(OLD), time.time())
            self.assertIn("noise check", problem)

    def test_main_refuses_an_a_to_a_without_a_salt_and_runs_one_with_a_salt(self) -> None:
        calls: list[list[tuple]] = []

        def fake_run(league, arms, dates, data_root, sims, procs, log=print):
            calls.append([(a, s) for a, _v, s in arms])
            return {a: {} for a, _v, _s in arms}, {}

        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(gate, "run_arms", side_effect=fake_run), \
                mock.patch.dict("os.environ"):
            common =["--league", "ncaab", "--current", OLD, "--dates", "2026-11-05", "--data-root", tmp,
                      "--receipt-dir", tmp]
            base = common + ["--candidate", OLD]
            refused = [base, base + ["--current-salts", "4", "--seed-salt", "1001"],
                       common + ["--current-salts", "4", "--aa-salts", "1002"],
                       common + ["--aa-salts", "0"], common + ["--aa-salts", "3,3"]]
            for argv in refused:
                buf = io.StringIO()
                with redirect_stdout(buf):
                    rc = gate.main(argv)
                self.assertEqual(rc, 2, argv)
                self.assertTrue("no transition to score" in buf.getvalue() or "--aa-salts must" in buf.getvalue(),
                                (argv, buf.getvalue()))
            self.assertEqual(calls, [])
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = gate.main(base + ["--seed-salt", "1"])
            self.assertEqual(calls, [[("current@0", 0), ("candidate", 1)]])  # default: one current draw
            self.assertIn("NOISE CHECK", buf.getvalue())
            self.assertEqual(rc, 2)  # no games -> no receipt
            self.assertIn("NO RECEIPT", buf.getvalue())


CPS5 = ["0m", "10m", "20m", "30m", "36m"]
LINEAR = ("margin_crps", "total_crps", "win_brier", "win_logloss")


def _base(n_games: int, seed: int = 5) -> dict:
    import numpy as np

    rng = np.random.default_rng(seed)
    return {cp: {**{m: rng.normal(1.0, 0.5, n_games) for m in LINEAR},
                 "in80": (rng.random(n_games) < 0.85).astype(float)} for cp in CPS5}


def _arm(base: dict, noise_seed: int, n_games: int, shift: dict | None = None, scale: float = 0.1) -> dict:
    """features[game][cp]: the shared per-game base + this draw's MEAN-ZERO noise + an exact shift per (cp, metric),
    so a cell's paired diff is exactly the shift and its SD is the noise's."""
    import numpy as np

    rng = np.random.default_rng(noise_seed)
    out: dict = {}
    for cp in CPS5:
        for metric in LINEAR:
            e = rng.normal(0.0, scale, n_games)
            e -= e.mean()
            delta = (shift or {}).get((cp, metric), 0.0)
            for g in range(n_games):
                out.setdefault(f"g{g}", {}).setdefault(cp, {})[metric] = float(base[cp][metric][g] + e[g] + delta)
        for g in range(n_games):
            out[f"g{g}"][cp].update(margin_in80=float(base[cp]["in80"][g]), total_in80=float(base[cp]["in80"][g]),
                                    margin_sd=10.0, margin_err=0.0, total_mean=140.0, margin_mean=0.0)
    return out


class NullBaselineTests(unittest.TestCase):
    """lane outcome-gate-null-baseline: the current arm is the mean of K draws and WORSE is family-wise (max-T), because
    two A/A runs flagged 4 and 2 cells against one fixed current draw (findings STEP 3j)."""

    def test_average_arms_is_the_draw_at_k1_and_needs_every_draw(self) -> None:
        a = {"g1": {"0m": {"x": 0.1, "y": 2.0}}, "g2": {"0m": {"x": 0.3}}}
        b = {"g1": {"0m": {"x": 0.3, "y": 4.0}}}
        self.assertEqual(gate.average_arms([a]), a)
        avg = gate.average_arms([a, b])
        self.assertEqual(set(avg), {"g1"})  # g2 is missing from draw b: dropped, not averaged over one draw
        self.assertAlmostEqual(avg["g1"]["0m"]["x"], 0.2)
        self.assertAlmostEqual(avg["g1"]["0m"]["y"], 3.0)

    def test_family_rule_flags_a_strong_effect_but_not_a_z_2_4_cell_the_per_cell_rule_flags(self) -> None:
        n = 300
        base = _base(n)
        paired = gate.pair(_arm(base, 1, n), _arm(base, 2, n, shift={("20m", "win_brier"): 0.0196,
                                                                    ("36m", "win_logloss"): 0.065}))
        per_cell_worse, _ = gate.flag_cells(gate.score_cells(paired, CPS5))
        self.assertEqual(per_cell_worse, ["20m:win_brier", "36m:win_logloss"])
        fam = gate.family_flags(paired, CPS5)
        self.assertGreater(fam["z"]["20m:win_brier"], 1.96)
        self.assertLess(fam["z"]["20m:win_brier"], fam["critical_worse"])
        self.assertEqual(fam["worse"], ["36m:win_logloss"])
        self.assertEqual(fam["better"], [])
        self.assertTrue(2.4 < fam["critical_worse"] < 3.3, fam["critical_worse"])
        self.assertEqual(fam["n_cells"], 30)

    def test_the_critical_value_rises_with_the_number_of_cells(self) -> None:
        n = 300
        base = _base(n)
        paired = gate.pair(_arm(base, 1, n), _arm(base, 2, n))
        one, five = gate.family_flags(paired, ["0m"]), gate.family_flags(paired, CPS5)
        self.assertTrue(1.7 < one["critical_worse"] < 2.7, one["critical_worse"])
        self.assertGreater(five["critical_worse"], one["critical_worse"] + 0.3)
        self.assertEqual((one["worse"], five["worse"], five["better"]), ([], [], []))

    def test_identical_arms_never_flag(self) -> None:
        n = 200
        arm = _arm(_base(n), 1, n)
        fam = gate.family_flags(gate.pair(arm, arm), CPS5)
        self.assertEqual((fam["worse"], fam["better"]), ([], []))
        self.assertTrue(all(z == 0.0 for z in fam["z"].values()))

    def test_opt_in_k_draws_and_family_rule_through_main_vs_the_one_draw_per_cell_default(self) -> None:
        """off != on through main(): an A/A whose current draw 0 is LUCKY on 20 m win Brier (STEP 3j's shape). The
        DEFAULT (one draw, per-cell; restored 2026-11-13 after the family rule failed to refuse RC46) refuses it;
        the opt-in --current-salts 4 --flag-rule family writes no WORSE cell; every receipt's legacy block refuses."""
        n = 200
        base = _base(n)
        table = {"current@0": _arm(base, 11, n, shift={("20m", "win_brier"): -0.06}),
                 "current@1001": _arm(base, 12, n), "current@1002": _arm(base, 13, n),
                 "current@1003": _arm(base, 14, n),
                 # + a z ~2.5 cell against the 4-draw mean: the per-cell rule would refuse it, the family rule must not
                 "aa1": _arm(base, 15, n, shift={("30m", "win_brier"): 0.02})}
        seen: list[list[str]] = []

        def fake_run(league, arms, dates, data_root, sims, procs, log=print):
            seen.append([a for a, _v, _s in arms])
            return {a: table[a] for a, _v, _s in arms}, {}

        h = gate.value_hash(OLD)
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(gate, "run_arms", side_effect=fake_run), \
                mock.patch.dict("os.environ"):
            common = ["--league", "ncaab", "--current", OLD, "--aa-salts", "1", "--dates", "2026-11-05",
                      "--data-root", tmp, "--receipt-dir", tmp]
            receipt = Path(tmp) / gate.receipt_name("ncaab", h, h, 1)
            opt_in = Path(tmp) / gate.receipt_name("ncaab", h, h, 1, gate.rule_id("family", 4))
            self.assertNotEqual(receipt, opt_in)
            with redirect_stdout(io.StringIO()):
                rc_on = gate.main(common + ["--current-salts", "4", "--flag-rule", "family"])
            self.assertFalse(receipt.exists())  # the opt-in run never writes the default's file name
            on = json.loads(opt_in.read_text(encoding="utf-8"))
            with redirect_stdout(io.StringIO()):
                rc_off = gate.main(common)
            off = json.loads(receipt.read_text(encoding="utf-8"))
        self.assertEqual(seen[0], ["current@0", "current@1001", "current@1002", "current@1003", "aa1"])
        self.assertEqual(seen[1], ["current@0", "aa1"])
        self.assertEqual((rc_on, on["worse"], on["flag_rule"], on["current_salts"]), (0, [], "family", [0, 1001, 1002, 1003]))
        self.assertIn("30m:win_brier", gate.flag_cells(on["cells"])[0])  # main() applied the family rule, not 1.96
        self.assertTrue(1.96 < on["family"]["z"]["30m:win_brier"] < on["family"]["critical_worse"])
        self.assertIn("20m:win_brier", on["legacy"]["worse"])
        self.assertEqual((rc_off, off["flag_rule"], off["current_salts"]), (1, "per-cell", [0]))
        self.assertIn("20m:win_brier", off["worse"])
        self.assertEqual(off["worse"], off["legacy"]["worse"])
        self.assertEqual(off["legacy"]["cells"], off["cells"])  # K = 1 + per-cell IS the legacy computation
        self.assertEqual(on["seed_salt"], 1)
        self.assertLess(on["cells"]["20m"]["win_brier"]["diff"], off["cells"]["20m"]["win_brier"]["diff"])


def _with_coverage(arm: dict, cp: str, value: float) -> dict:
    """A copy of `arm` whose margin_in80 at `cp` is `value` for every game: a coverage-only change."""
    out = json.loads(json.dumps(arm))
    for by_cp in out.values():
        by_cp[cp]["margin_in80"] = value
    return out


class SmoothFamilyTests(unittest.TestCase):
    """lane gate-smooth-family: the family rule over the 20 smooth cells (coverage reported, never flagged), and a
    receipt scored by any rule but the default getting its own name and never clearing preflight (the STEP 3k
    validation overwrote the live receipts with family-rule verdicts on 2026-11-13 22:58Z)."""

    def test_smooth_family_reports_coverage_with_its_z_but_never_flags_it(self) -> None:
        n = 300
        base = _base(n)
        cand = _with_coverage(_arm(base, 2, n), "0m", 1.0)  # coverage 0.85 -> 1.00: |dev| 0.05 -> 0.20
        paired = gate.pair(_arm(base, 1, n), cand)
        every = gate.family_flags(paired, CPS5)
        smooth = gate.family_flags(paired, CPS5, metrics=gate.FAMILY_CELLS["smooth"])
        self.assertIn("0m:margin_cov80_dev", every["worse"])
        self.assertGreater(smooth["z"]["0m:margin_cov80_dev"], smooth["critical_worse"])  # reported, and large
        self.assertNotIn("0m:margin_cov80_dev", smooth["worse"])
        self.assertIn("0m:margin_cov80_dev", smooth["report_only"])
        self.assertEqual((every["n_cells"], smooth["n_cells"], len(smooth["report_only"])), (30, 20, 10))
        self.assertEqual(len(smooth["z"]), 30)

    def test_the_smooth_family_is_the_post_hoc_construction_and_a_cells_z_does_not_depend_on_the_family(self) -> None:
        """STEP 3k's post hoc numbers came from scoring with METRICS cut to the smooth four; the option must reproduce
        them exactly, so the confirmation tests the rule that was chosen and not a cousin of it."""
        import numpy as np

        n = 250
        base = _base(n)
        cand = _arm(base, 2, n, shift={("20m", "win_brier"): 0.03})
        rng = np.random.default_rng(9)  # the candidate's OWN per-game coverage, so the coverage cells' t is not 0
        for by_cp in cand.values():
            for feats in by_cp.values():
                feats["margin_in80"], feats["total_in80"] = float(rng.random() < 0.82), float(rng.random() < 0.82)
        paired = gate.pair(_arm(base, 1, n), cand)
        smooth = gate.family_flags(paired, CPS5, metrics=gate.FAMILY_CELLS["smooth"])
        every = gate.family_flags(paired, CPS5)
        with mock.patch.object(gate, "METRICS", gate.FAMILY_CELLS["smooth"]):
            post_hoc = gate.family_flags(paired, CPS5)
        self.assertEqual((smooth["critical_worse"], smooth["critical_better"], smooth["worse"], smooth["better"]),
                         (post_hoc["critical_worse"], post_hoc["critical_better"], post_hoc["worse"], post_hoc["better"]))
        self.assertEqual({c: smooth["z"][c] for c in post_hoc["z"]}, post_hoc["z"])
        self.assertEqual({c: every["z"][c] for c in post_hoc["z"]}, post_hoc["z"])
        # a max over a superset is >= the max over the subset in every draw, so its quantile is too; strictly here,
        # because the coverage cells vary (which is what lets this test see a family that is ignored)
        self.assertLess(smooth["critical_worse"], every["critical_worse"])
        with self.assertRaises(ValueError):
            gate.family_flags(paired, CPS5, metrics=("win_brier", "spread_cover"))

    def test_rule_ids_and_receipt_names(self) -> None:
        self.assertEqual(gate.DEFAULT_RULE_ID, "percell-k1")
        self.assertEqual(gate.rule_id("family", 4, "smooth"), "family-smooth-k4-a0.05")
        self.assertEqual(gate.rule_id("per-cell", 4, "smooth", 0.2), "percell-k4")  # cells / alpha unused per-cell
        h1, h2 = gate.value_hash(NEW), gate.value_hash(OLD)
        default = gate.receipt_name("ncaab", h1, h2)
        self.assertEqual(gate.receipt_name("ncaab", h1, h2, 0, gate.DEFAULT_RULE_ID), default)
        self.assertTrue(gate.receipt_name("ncaab", h1, h2, 0, "family-smooth-k4-a0.05").endswith(
            "__rule-family-smooth-k4-a0.05.json"))
        self.assertTrue(gate.receipt_name("ncaab", h1, h2, 2, "percell-k4").endswith("__salt2__rule-percell-k4.json"))
        # derived from the receipt's fields: a pre-opt-in receipt (no fields) is per-cell K = 1; STEP 3k's are not
        self.assertEqual(gate.receipt_rule_id({}), "percell-k1")
        self.assertEqual(gate.receipt_rule_id({"flag_rule": "family", "current_salts": [0, 1001, 1002, 1003],
                                               "family": {"alpha": 0.05}}), "family-all-k4-a0.05")
        self.assertEqual(gate.receipt_rule_id({"flag_rule": "per-cell", "current_salts": [0, 1001]}), "percell-k2")

    def test_an_opt_in_receipt_never_clears_even_renamed_and_a_pre_opt_in_one_still_does(self) -> None:
        h1, h2 = gate.value_hash(NEW), gate.value_hash(OLD)
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            path = gate.write_receipt(d, {"league": "ncaab", "candidate_hash": h1, "current_hash": h2, "games": 360,
                                          "worse": [], "better": [], "written_at": time.time(), "flag_rule": "family",
                                          "family_cells": "smooth", "current_salts": [0, 1001, 1002, 1003],
                                          "family": {"alpha": 0.05}})
            self.assertTrue(path.name.endswith("__rule-family-smooth-k4-a0.05.json"), path.name)
            self.assertIn("no outcome-gate receipt", gate.check_receipt(d, "ncaab", h1, h2, time.time())[0])
            path.rename(d / gate.receipt_name("ncaab", h1, h2))
            problem, detail = gate.check_receipt(d, "ncaab", h1, h2, time.time())
            self.assertIn("opt-in rule family-smooth-k4-a0.05", problem)
            self.assertEqual(detail["rule"], "family-smooth-k4-a0.05")
            _receipt(d)  # the pre-opt-in shape (no rule fields) at the default name
            problem, detail = gate.check_receipt(d, "ncaab", h1, h2, time.time())
            self.assertIsNone(problem, problem)
            self.assertEqual(detail["rule"], "percell-k1")

    def test_smooth_cells_through_main_off_vs_on_and_only_the_default_receipt_is_read(self) -> None:
        """off != on through main(): a candidate whose ONLY change is 0 m margin coverage (0.85 -> 1.00). The default
        (per-cell) and the 30-cell family rule refuse it; --family-cells smooth writes no WORSE cell but keeps the
        coverage z on the receipt. Each rule writes its own file, and check_receipt reads only the default's."""
        n = 200
        base = _base(n)
        table = {"current@0": _arm(base, 11, n), "current@1001": _arm(base, 12, n), "current@1002": _arm(base, 13, n),
                 "current@1003": _arm(base, 14, n), "candidate": _with_coverage(_arm(base, 15, n), "0m", 1.0)}

        def fake_run(league, arms, dates, data_root, sims, procs, log=print):
            return {a: table[a] for a, _v, _s in arms}, {}

        h1, h2 = gate.value_hash(NEW), gate.value_hash(OLD)
        k4 = ["--current-salts", "4", "--flag-rule", "family"]
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(gate, "run_arms", side_effect=fake_run), \
                mock.patch.dict("os.environ"):
            d = Path(tmp)
            common = ["--league", "ncaab", "--current", OLD, "--candidate", NEW, "--dates", "2026-11-05",
                      "--data-root", tmp, "--receipt-dir", tmp]
            rcs, out = {}, {}
            for name, extra in (("all", k4), ("smooth", k4 + ["--family-cells", "smooth"]), ("default", [])):
                buf = io.StringIO()
                with redirect_stdout(buf):
                    rcs[name] = gate.main(common + extra)
                out[name] = buf.getvalue()
            files = sorted(p.name for p in d.glob("*.json"))
            smooth = json.loads((d / gate.receipt_name("ncaab", h1, h2, 0, "family-smooth-k4-a0.05")).read_text(
                encoding="utf-8"))
            every = json.loads((d / gate.receipt_name("ncaab", h1, h2, 0, "family-all-k4-a0.05")).read_text(
                encoding="utf-8"))
            problem, detail = gate.check_receipt(d, "ncaab", h1, h2, time.time())
        self.assertEqual(len(files), 3, files)
        self.assertEqual((rcs["all"], rcs["smooth"], rcs["default"]), (1, 0, 1))
        self.assertIn("0m:margin_cov80_dev", every["worse"])
        self.assertEqual(smooth["worse"], [])
        self.assertIn("0m:margin_cov80_dev", smooth["family"]["report_only"])
        self.assertGreater(smooth["family"]["z"]["0m:margin_cov80_dev"], smooth["family"]["critical_worse"])
        self.assertEqual((smooth["rule_id"], smooth["family_cells"], smooth["family"]["n_cells"]),
                         ("family-smooth-k4-a0.05", "smooth", 20))
        self.assertIn("0m:margin_cov80_dev", smooth["legacy"]["worse"])  # the legacy block still sees it
        self.assertIn("(reported, not flagged)", out["smooth"])
        self.assertIn("OPT-IN", out["smooth"])
        self.assertEqual(detail["rule"], "percell-k1")  # preflight read the DEFAULT run's receipt ...
        self.assertIn("0m:margin_cov80_dev", problem)  # ... and refuses on its coverage cell


if __name__ == "__main__":
    unittest.main()
