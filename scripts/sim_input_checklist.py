"""SIM ENGINE INPUT CHECKLIST — is every input the sim reads actually fed?

`#440`. This exists because FOUR separate features were found in one session that
were fully built, tested, consumed by the simulation, and **populated with
nothing** — each behaving as a silent no-op:

  * pitch-type effectiveness (`pitch_type_whiff_mult`) -> every pitch identical
  * batted-ball types (`bb_gb_rate`) -> every hitter identical
  * `statcast_quality_mult`, `vs_pitch_type`, and more

None raised an error. None failed a test. The sim ran, produced numbers, and
those numbers were identical to a build where the feature did not exist.

THE TWO RULES THIS ENCODES, both learned the hard way:

  1. **Never reason about a model's presence from a NAME SEARCH.** A grep for
     `ground_ball|fly_ball|launch_angle` produced the published claim "no
     batted-ball model". The fields are prefixed `bb_`. Enumerate
     `dataclasses.fields()` instead — vocabulary is not evidence.
  2. **A `.get(key, NEUTRAL)` default makes an unfed field invisible.** A
     multiplier defaulting to 1.0 is indistinguishable from a working feature at
     every level except the data.

So this cross-references TWO things per field:

    is it CONSUMED by the simulation?   (search the engine source for the name)
    is it POPULATED in real rosters?    (measure against artifacts)

**CONSUMED + UNPOPULATED is the alarm.** That combination is a feature which
cannot work, and it is invisible to every other check in this repo.

Exits 1 when any consumed field is unpopulated, so it can gate.

Usage:
  py -3 scripts/sim_input_checklist.py
  py -3 scripts/sim_input_checklist.py --games 60 --json reports/phase7/input_checklist.json
"""

from __future__ import annotations

import argparse
import glob
import json
import re
import sys
import os
from collections import Counter
from dataclasses import fields
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
VENDOR = REPO / "vendor" / "mlb_bettingv2"
for _p in (str(REPO), str(VENDOR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

ENGINE = VENDOR / "sim_engine"


def _data_root() -> Path:
    """The root the WORKER actually writes to.

    **This was hardcoded to `REPO / "data"` and it made the checklist useless in
    the one place it matters.** Locally that IS the data root, so the script ran
    perfectly on a dev box; in production `SYNDICATE_DATA_ROOT` points at the
    mounted disk and `REPO/data` is the EPHEMERAL CHECKOUT, which holds no
    `roster_objs/`. So on the worker the glob matched nothing, the script exited
    1 with REFUSED, and no report was ever written -- while the `--publish` path
    twenty lines below resolved the SAME root correctly. **The file read from one
    root and wrote to another.**
    """
    root = str(os.environ.get("SYNDICATE_DATA_ROOT") or "").strip()
    return Path(root).expanduser().resolve() if root else (REPO / "data")


def _season_artifact_probe(season: int = 2026) -> dict:
    """Is each season-scoped sim input actually PRESENT AND LOADABLE here?

    WHY THIS EXISTS. `pitch_type_whiff_mult` read 0.0% in production on
    2026-08-20 while the arsenal artifact was published, schema-valid on web
    (466/466 pitchers carrying the multipliers), the consumer was provably
    REACHED (the calls on both sides of it populated at 76.87%), and the real
    `apply_arsenal_to_pitcher` populated 5/5 pitchers when run against the real
    file locally. Four hypotheses died against that evidence. The one link
    nobody could read was the simplest: **does the file exist on the WORKER at
    build time?**

    `pull_season_artifacts()` runs before the build and its own docstring warns
    that "a return of 0 is not proof of success" -- and its `SEASON_PULL`
    diagnostics are INVISIBLE, because the sim job's stdout is redirected to a
    disk file that Render's log API cannot serve (confirmed by control:
    `[artifact_publisher]` lines reach the collector, `[mlb_sim_job]` lines
    return zero hits).

    Cheap on purpose: stat + parse + count. No network, no per-pitcher work.
    This is the probe `--simulate-rebuild` cannot safely be on a worker near its
    memory cap, since that path calls the per-pitcher BVP fetch.
    """
    root = _data_root()
    specs = (
        ("arsenal", f"mlb_source/source_artifacts/data/arsenal/arsenal_{season}.json",
         ("pitchers", "batters")),
        ("conditional_mix", f"mlb_source/source_artifacts/data/conditional_mix/conditional_mix_{season}.json",
         ("pitchers",)),
        ("batted_ball", f"mlb_source/source_artifacts/data/batted_ball/batted_ball_{season}.json",
         ("pitchers", "batters")),
        ("quality", f"mlb_source/source_artifacts/data/quality/quality_{season}.json",
         ("pitchers", "batters")),
        ("pitch_splits", f"mlb_source/source_artifacts/data/pitch_splits/pitch_splits_{season}.json",
         ("pitchers",)),
    )
    out = {"data_root": str(root), "season": int(season), "files": []}
    for name, rel, keys in specs:
        p = root / rel
        row = {"name": name, "path": str(p), "exists": False}
        try:
            row["exists"] = p.is_file()
            if row["exists"]:
                row["bytes"] = int(p.stat().st_size)
                row["mtime"] = float(p.stat().st_mtime)
                doc = json.loads(p.read_text(encoding="utf-8"))
                row["loadable"] = True
                for k in keys:
                    row[f"n_{k}"] = len(doc.get(k) or {})
        except Exception as exc:
            row["loadable"] = False
            row["error"] = f"{type(exc).__name__}: {exc}"[:160]
        out["files"].append(row)
    return out


SNAPSHOTS = _data_root() / "mlb_source/source_artifacts/data/daily_pitcher_props/snapshots"

# Fields that are legitimately sparse. Documented so a low number here is not
# mistaken for a defect -- anything NOT listed, and consumed, must be populated.
EXPECTED_SPARSE = {
    "availability_mult": "set only for pitchers with a known workload flag",
    "leverage_skill": "relievers with enough high-leverage sample",
    "sb_attempt_rate": "many hitters genuinely never attempt a steal",
    "sb_success_rate": "same population as sb_attempt_rate",
    "batted_ball_source": "provenance stamp, only when the blend is enabled",
    "batted_ball_bbe": "same",
    "batted_ball_weight": "same",
    # BVP is SPARSE BY NATURE, not by defect. A batter only has history against
    # starters he has actually faced, so ~14% coverage is the correct answer and
    # 100% would be impossible.
    #
    # **THE "13.9%" THIS COMMENT USED TO CITE WAS NOT A PRODUCTION NUMBER**
    # `[corrected 2026-08-20]`. It was measured under `--simulate-rebuild`,
    # and that path calls `apply_starter_bvp_hr_multipliers` UNCONDITIONALLY,
    # while production reaches it only through `if bvp_hr_on:`. In production
    # these fields read 0.0%, because BVP is switched OFF by config -- see
    # `_disabled_by_config`. Quoting a simulate-mode number beside fields that
    # are zero in production is the true-but-misleading shape that sends the
    # next reader hunting a regression that never happened.
    # Listing these matters: a checklist that flags correct behaviour as FAILURE
    # gets ignored, and then it misses the real ones.
    "vs_pitcher_hr_mult": "batter has history only vs starters actually faced",
    "vs_pitcher_k_mult": "same",
    "vs_pitcher_bb_mult": "same",
    "vs_pitcher_inplay_mult": "same",
    "vs_pitcher_history": "same",
}
SPARSE_FLOOR = 0.20
POPULATED_FLOOR = 0.50


def _disabled_by_config(date_str=None):
    """Fields unfed BY DELIBERATE CONFIGURATION, not by defect. `#440`.

    WHY THIS IS A SEPARATE CATEGORY. `FAIL` must mean "something is wrong".
    Five of the fifteen failures reported on 2026-08-20 were the `vs_pitcher_*`
    BVP fields, zero because `FORWARD_BVP_MATCHUP_MODE = "off"` -- a modelling
    decision with a stated re-entry condition ("until the matchup path proves
    net value on a cleaner holdout"), not a breakage. Reporting them
    identically to the four genuine defects found that same day is how a gating
    check loses its meaning, and it is what pulled a session into tracing a
    non-bug for half an hour.

    READ FROM THE REAL CONFIG, never hardcoded: flipping the switch back on
    returns these fields to ordinary FAIL/ok accounting automatically. A
    hardcoded exemption list would keep excusing them long after they should
    work -- which is the same failure mode as the neutral default this whole
    checklist exists to catch.
    """
    out = {}
    try:
        from sim_engine.forward_tuning import (FORWARD_BVP_MATCHUP_MODE,
                                               should_use_forward_tuning)
    except Exception:
        return out
    try:
        forward = should_use_forward_tuning(date_str) if date_str else True
    except Exception:
        forward = True
    if forward and str(FORWARD_BVP_MATCHUP_MODE).strip().lower() != "on":
        why = ("bvp_hr=off via FORWARD_BVP_MATCHUP_MODE=%r -- daily_update gates "
               "the whole BVP block on `if bvp_hr_on:`" % (FORWARD_BVP_MATCHUP_MODE,))
        for f in ("vs_pitcher_hr_mult", "vs_pitcher_k_mult", "vs_pitcher_bb_mult",
                  "vs_pitcher_inplay_mult", "vs_pitcher_history"):
            out[f] = why
    return out



def engine_source() -> str:
    parts = []
    for path in ENGINE.rglob("*.py"):
        try:
            parts.append(path.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            continue
    return "\n".join(parts)


def consumed(name: str, src: str) -> bool:
    """Does the engine READ this field anywhere?

    Matches attribute access (`.name`) and string reference (getattr / dict key).
    Deliberately broad: a false 'consumed' costs one harmless row, a false
    'unconsumed' hides the exact defect this script exists to find.
    """
    esc = re.escape(name)
    return bool(re.search(r"\." + esc + r"\b", src) or re.search(r"['\"]" + esc + r"['\"]", src))


def populated(value, default) -> bool:
    if value is None:
        return False
    if isinstance(value, (dict, list, tuple, set)):
        return len(value) > 0
    if isinstance(value, str):
        return value.strip() != ""
    if isinstance(value, bool):
        return value != default
    if isinstance(value, (int, float)):
        return value != default
    return True


# --------------------------------------------------------------------------
# OUTPUT-SIDE INVARIANT  `#621`
#
# Everything else in this file audits INPUT dataclass fields: is a field the
# engine READS actually POPULATED. That framing is structurally blind to the
# defect that motivated this block, which sits on the OUTPUT side --
# `_HITTER_PROP_DIST_SPECS` names a row_key ("SO") that the per-sim
# `hitter_stat_values` dict never sets, and the read is
# `.get(row_key, 0)`. A neutral default (standard 4.2) turns that into
# `strikeouts_dist == {0: n_sims}` and `so_mean == 0.0` for every hitter in
# every game, with passing tests and no log line.
#
# It is a ONE-LINE invariant -- `set(spec row_keys) <= set(dict keys)` -- and
# it is checked here rather than only in the test suite because this script is
# what `scripts/run_mlb_daily_sim_job.py` runs, so a regression fails the
# actual daily job.
#
# It runs BEFORE the roster glob on purpose. It needs no artifacts, so it must
# still report on a box where the checklist would otherwise exit "REFUSED: no
# roster artifacts" -- the state in which a fresh checkout sits.
#
# THE PITCHER SPEC IS DELIBERATELY NOT CHECKED HERE. `_PITCHER_PROP_DIST_SPECS`
# is read straight off the boxscore row (`row.get(str(row_key))`), not out of a
# curated dict, so there is no key set to compare against and no equivalent way
# to silently drop one. Audited empirically 2026-09-04: all 7 pitcher dists
# multi-bin. If a curated pitcher dict is ever introduced, add it here.
# --------------------------------------------------------------------------
DAILY_UPDATE_PY = REPO / "vendor" / "mlb_bettingv2" / "tools" / "daily_update.py"


def output_spec_problems() -> list:
    """Return human-readable problems with the hitter prop OUTPUT specs.

    Parsed with `ast`, never a regex: the fix's own comment contains a literal
    `{0: n_sims}` whose brace truncates a non-greedy match, which made the dict
    look SHORTER than it is -- a false PASS shaped like the bug being tested.
    """
    import ast

    problems: list = []
    try:
        tree = ast.parse(DAILY_UPDATE_PY.read_text(encoding="utf-8"))
    except Exception as exc:
        return [f"could not parse {DAILY_UPDATE_PY}: {exc}"]

    sites: list = []
    specs: list = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        names = [t.id for t in node.targets if isinstance(t, ast.Name)]
        if isinstance(node.value, ast.Dict) and "hitter_stat_values" in names:
            sites.append([k.value for k in node.value.keys if isinstance(k, ast.Constant)])
    for node in ast.walk(tree):
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)                 and node.target.id == "_HITTER_PROP_DIST_SPECS" and node.value is not None:
            for elt in getattr(node.value, "elts", []):
                parts = [e.value for e in getattr(elt, "elts", []) if isinstance(e, ast.Constant)]
                if len(parts) == 3:
                    specs.append(parts)

    if not specs:
        return ["could not read _HITTER_PROP_DIST_SPECS -- the invariant did NOT run"]
    if len(sites) != 2:
        problems.append(
            f"expected 2 hitter_stat_values sites (_simw_chunk + _sim_many), found {len(sites)}"
        )
    if not sites:
        return problems + ["could not read hitter_stat_values -- the invariant did NOT run"]

    required = {row_key for _d, row_key, _m in specs}
    for i, keys in enumerate(sites, start=1):
        missing = sorted(required - set(keys))
        if missing:
            problems.append(
                f"hitter_stat_values site #{i} never sets {missing}, which "
                f"_HITTER_PROP_DIST_SPECS reads via .get(row_key, 0) -- "
                f"those dists are {{0: n_sims}} and their means 0.0 on EVERY row"
            )
    if len(sites) == 2 and sites[0] != sites[1]:
        problems.append(
            f"the two hitter_stat_values dicts have DRIFTED: {sites[0]} vs {sites[1]} "
            f"(this is the `#334` failure mode -- fixing one copy and not the other)"
        )
    return problems


def joint_site_problems() -> list:
    """Two-site identity for the `#621` Phase 4 JOINT accumulation.

    WHY THIS IS SEPARATE FROM `output_spec_problems`. That gate proves every
    `_HITTER_PROP_DIST_SPECS` row key is SET in `hitter_stat_values`. It says
    nothing about a second structure written at the same two sites, and the
    joint is exactly that -- so assuming coverage would leave the new code with
    the protection the old code has and none of its own.

    WHY A REACHABILITY TEST IS NOT ENOUGH HERE, MEASURED. With `_simw_chunk`
    (site 1) broken and `_sim_many` (site 2) intact, BOTH `off != on`
    reachability tests still PASS, because `workers=1` never enters
    `_simw_chunk` -- and `--workers` DEFAULTS TO 4, so the path the tests take is
    the one production does not. `model_engine_standard` §4.3 is necessary and
    not sufficient for a duplicated site; only a structural invariant sees it.

    WHY `ast` AND NEVER A REGEX. Measured on this very file: the `#621` fix's
    own comment contains a literal `{0: n_sims}`, and that brace truncates a
    non-greedy `hitter_stat_values = \\{(.*?)\\}` match. The regex reports **6
    keys where the dict has 10**, silently dropping `"SO"` -- a false reading
    shaped precisely like the bug being guarded against.

    THE HISTORY THAT EARNS THIS. `#334` fixed one site and zeroed `hrr_mean`;
    `#429` added loud warning comments at BOTH sites; the third instance
    happened anyway, WITH those comments in place. A comment asking a human to
    remember is not a control.
    """
    import ast
    import copy

    problems: list = []
    try:
        tree = ast.parse(DAILY_UPDATE_PY.read_text(encoding="utf-8"))
    except Exception as exc:
        return [f"could not parse {DAILY_UPDATE_PY}: {exc}"]

    # The ENCLOSING STATEMENT of every joint_row write, grouped by function --
    # not the bare assignment.
    #
    # THIS DISTINCTION WAS MEASURED, NOT REASONED. The first version compared
    # only the `Assign` nodes and MISSED a real single-site break: deleting
    # `("first5", f5)` from one site's segment tuple left every assignment
    # byte-identical, because the tuple lives in the `for` header. The gate
    # read CLEAN while the two sites accumulated different dimensions -- which
    # `JointAccumulator.extend` would then reject at runtime, on the worker,
    # mid-slate. Dumping the enclosing `for`/`if` captures what is iterated.
    class _Normalize(ast.NodeTransformer):
        """Erase the two LEGITIMATE differences between the sites.

        The accumulator is named `joint_acc` in the chunk and `joint_total` in
        the parent, and the chunk offsets its row index by `start_i` because it
        owns rows [0, n) of its own matrix. Both are correct; neither is drift.
        Without normalising them the check would cry wolf on every run, and a
        gate that always fails is a gate nobody reads.
        """

        def visit_Name(self, node):  # noqa: N802 - ast API
            if node.id in {"joint_acc", "joint_total"}:
                return ast.copy_location(ast.Name(id="JOINT", ctx=node.ctx), node)
            return node

        def visit_Expr(self, node):  # noqa: N802 - ast API
            call = node.value
            if (
                isinstance(call, ast.Call)
                and isinstance(call.func, ast.Attribute)
                and call.func.attr == "record"
            ):
                # Checked separately, by presence -- its ARGS legitimately differ.
                return None
            return self.generic_visit(node)

    def _writes_joint_row(node) -> bool:
        for sub in ast.walk(node):
            if not isinstance(sub, ast.Assign):
                continue
            for target in sub.targets:
                if (
                    isinstance(target, ast.Subscript)
                    and isinstance(target.value, ast.Name)
                    and target.value.id == "joint_row"
                ):
                    return True
        return False

    def _joint_statements(func) -> list:
        found = []

        def _walk_body(body) -> None:
            for stmt in body:
                if not _writes_joint_row(stmt):
                    continue
                if isinstance(stmt, ast.Assign):
                    found.append(stmt)
                    continue
                # A `for` or `if` that CONTAINS writes: dump it whole, so the
                # iterated tuple and the guard are part of the comparison.
                if isinstance(stmt, (ast.For, ast.If, ast.While, ast.With)):
                    inner = [s for s in stmt.body if _writes_joint_row(s)]
                    if inner and all(isinstance(s, ast.Assign) for s in inner):
                        found.append(stmt)
                        continue
                for field in ("body", "orelse", "finalbody"):
                    _walk_body(getattr(stmt, field, []) or [])

        _walk_body(func.body)
        out = []
        for stmt in found:
            clone = _Normalize().visit(copy.deepcopy(stmt))
            ast.fix_missing_locations(clone)
            out.append(ast.dump(clone))
        return sorted(out)

    writes: dict = {}
    functions = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
    for func in functions:
        found = _joint_statements(func)
        if found:
            writes[func.name] = found

    if not writes:
        return [
            "no joint_row writes found at all -- the `#621` Phase 4 producer is "
            "ABSENT, or this invariant has stopped matching it and is now inert"
        ]
    if set(writes) != {"_simw_chunk", "_sim_many"}:
        problems.append(
            f"joint_row is written in {sorted(writes)}, expected exactly "
            "['_simw_chunk', '_sim_many'] -- the multiprocessing site and the serial one"
        )
    if len(writes) == 2:
        first, second = (writes[k] for k in sorted(writes))
        if first != second:
            only_a = [w for w in first if w not in second]
            only_b = [w for w in second if w not in first]
            problems.append(
                "the two joint_row accumulation sites have DRIFTED -- this is the "
                f"`#334`/`#429` failure mode. Only in one: {only_a[:2]}; "
                f"only in the other: {only_b[:2]}"
            )

    # Every joint market's row key must exist in BOTH hitter_stat_values dicts.
    # The joint reads that dict, so a key absent there yields a CONSTANT column,
    # whose rank correlation is undefined for every pair it appears in.
    try:
        from sim_engine.joint_outcomes import HITTER_MARKET_ROW_KEYS
    except Exception as exc:
        return problems + [f"could not import joint_outcomes -- invariant did NOT run: {exc}"]

    sites = [
        [k.value for k in node.value.keys if isinstance(k, ast.Constant)]
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and isinstance(node.value, ast.Dict)
        and any(isinstance(t, ast.Name) and t.id == "hitter_stat_values" for t in node.targets)
    ]
    if len(sites) != 2:
        problems.append(f"expected 2 hitter_stat_values sites, found {len(sites)}")
    for i, keys in enumerate(sites, start=1):
        missing = sorted({row_key for _m, row_key in HITTER_MARKET_ROW_KEYS} - set(keys))
        if missing:
            problems.append(
                f"hitter_stat_values site #{i} never sets {missing}, which "
                "HITTER_MARKET_ROW_KEYS publishes as joint dimensions -- those "
                "columns are CONSTANT and every correlation touching them is undefined"
            )

    # The record() call is what makes a write reach the matrix. A site that
    # populates joint_row and never records it is a no-op that this invariant
    # would otherwise call identical and healthy.
    for name in ("_simw_chunk", "_sim_many"):
        func = next((f for f in functions if f.name == name), None)
        if func is None:
            problems.append(f"{name} not found -- invariant did NOT run for it")
            continue
        recorded = any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "record"
            and any(isinstance(a, ast.Name) and a.id == "joint_row" for a in node.args)
            for node in ast.walk(func)
        )
        if not recorded:
            problems.append(
                f"{name} populates joint_row but never calls .record(..., joint_row) -- "
                "the values are built and dropped"
            )
    return problems


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--games", type=int, default=40)
    ap.add_argument("--json", type=Path, default=None)
    ap.add_argument("--warn-only", action="store_true",
                    help="report without failing, for exploratory runs")
    ap.add_argument("--simulate-rebuild", action="store_true",
                    help="apply the BUILD-TIME appliers before auditing. Without this the "
                         "checklist can only see what was SERIALISED -- i.e. history. Archived "
                         "rosters were written before any current wiring existed, so a plain run "
                         "reports the pre-wiring state forever and cannot validate a fix.")
    ap.add_argument("--publish", action="store_true",
                    help="write the report into the artifact tree so PRODUCTION can be audited. Roster objects are not allowlisted (hundreds of large files per date); the worker runs this and publishes the bounded result instead -- the book_grid pattern.")
    args = ap.parse_args()

    # OUTPUT-SIDE INVARIANT first: it needs no rosters, so it must still speak
    # on a box where the roster glob below exits REFUSED. `#621`.
    spec_problems = output_spec_problems()
    if spec_problems:
        print("=" * 88)
        print("FAIL: hitter prop OUTPUT spec/dict mismatch -- silently zeroed distributions")
        for problem in spec_problems:
            print(f"    {problem}")
        print("=" * 88)
        print("")
    else:
        print("ok: every _HITTER_PROP_DIST_SPECS row_key is set at both "
              "hitter_stat_values sites, and the two sites match")

    # `#621` Phase 4. Same class of invariant, different structure. Also needs
    # no rosters, so it speaks on a box where the roster glob exits REFUSED.
    joint_problems = joint_site_problems()
    if joint_problems:
        print("=" * 88)
        print("FAIL: JOINT accumulation sites disagree -- a correlation built from half a slate")
        for problem in joint_problems:
            print(f"    {problem}")
        print("=" * 88)
        print("")
    else:
        print("ok: joint_row is written identically at both accumulation sites, "
              "recorded at both, and every joint market's row_key exists in both dicts")
    spec_problems = list(spec_problems) + list(joint_problems)

    from sim_engine.data.roster_artifact import read_game_roster_artifact
    from sim_engine.models import BatterProfile, PitcherProfile

    paths = sorted(glob.glob(str(SNAPSHOTS / "*/roster_objs/roster_obj_*.json")))[:args.games]
    if not paths:
        # Distinguish "wrong root" from "right root, no rosters yet". A bare
        # REFUSED sent me chasing the sim job for hours when the path was wrong.
        _root = _data_root()
        print(f"REFUSED: no roster artifacts under {SNAPSHOTS}")
        print(f"  data root      : {_root}  (exists={_root.exists()})")
        print(f"  SYNDICATE_DATA_ROOT env: {os.environ.get('SYNDICATE_DATA_ROOT') or '(unset -- falling back to REPO/data)'}")
        print(f"  snapshots dir  : exists={SNAPSHOTS.exists()}")
        if SNAPSHOTS.exists():
            _dates = sorted(d.name for d in SNAPSHOTS.iterdir() if d.is_dir())[-3:]
            print(f"  dates present  : {_dates or '(none)'} -- rosters may not be built yet")
        return 1

    src = engine_source()
    hits = {"batter": Counter(), "pitcher": Counter()}
    n = {"batter": 0, "pitcher": 0}
    bdef = {f.name: f.default for f in fields(BatterProfile)}
    pdef = {f.name: f.default for f in fields(PitcherProfile)}

    if args.simulate_rebuild:
        # Everything the real build applies, in the same order. BVP is applied by
        # `daily_update.py:7564` -- NOT by build_roster -- which is why it needs
        # its own call here; see the provenance table in
        # docs/ai_context/mlb_sim_engine_reference.md.
        from datetime import date as _date
        from sim_engine.data.arsenal import (apply_arsenal_to_batter,
                                             apply_arsenal_to_pitcher)
        from sim_engine.data.batted_ball import (apply_batted_ball_to_batter,
                                                 apply_batted_ball_to_pitcher)
        from sim_engine.data.build_roster import _apply_cached_statcast_pitch_splits
        from sim_engine.data.quality import apply_quality
        from sim_engine.data.statcast_bvp import (apply_starter_bvp_hr_multipliers,
                                                  default_bvp_cache)
        from sim_engine.data.statcast_pitch_splits import default_statcast_cache
        _sc, _bc = default_statcast_cache(), default_bvp_cache()

    for path in paths:
        try:
            roster = read_game_roster_artifact(Path(path))
        except Exception:
            continue
        if args.simulate_rebuild:
            for _bat, _pit in (("away", "home"), ("home", "away")):
                try:
                    apply_starter_bvp_hr_multipliers(
                        batting_roster=roster[_bat],
                        pitcher_id=int(roster[_pit].lineup.pitcher.player.mlbam_id),
                        season=2026, start_date=_date(2026, 3, 1),
                        end_date=_date(2026, 7, 30), cache=_bc)
                except Exception:
                    pass
            for _side in ("away", "home"):
                _lu = roster[_side].lineup
                for _b in list(_lu.batters) + list(_lu.bench or []):
                    try:
                        apply_batted_ball_to_batter(_b, season=2026, weight=0.35)
                        apply_arsenal_to_batter(_b, season=2026)
                        apply_quality(_b, season=2026, side="batters")
                    except Exception:
                        pass
                for _p in [_lu.pitcher] + list(_lu.bullpen or []):
                    try:
                        _apply_cached_statcast_pitch_splits(
                            _p, season=2026, statcast_cache=_sc, statcast_ttl_seconds=None)
                        apply_batted_ball_to_pitcher(_p, season=2026)
                        apply_arsenal_to_pitcher(_p, season=2026)
                        apply_quality(_p, season=2026, side="pitchers")
                    except Exception:
                        pass
        for side in ("away", "home"):
            lineup = roster[side].lineup
            for b in list(lineup.batters) + list(lineup.bench or []):
                n["batter"] += 1
                for f in fields(BatterProfile):
                    if f.name != "player" and populated(getattr(b, f.name, None), bdef.get(f.name)):
                        hits["batter"][f.name] += 1
            for p in [lineup.pitcher] + list(lineup.bullpen or []):
                n["pitcher"] += 1
                for f in fields(PitcherProfile):
                    if f.name != "player" and populated(getattr(p, f.name, None), pdef.get(f.name)):
                        hits["pitcher"][f.name] += 1

    print("=" * 88)
    print("SIM ENGINE INPUT CHECKLIST")
    print("=" * 88)
    print(f"\n  rosters {len(paths)}   batters {n['batter']}   pitchers {n['pitcher']}")
    print("  a field FAILS when the engine READS it and nothing FEEDS it\n")

    failures, warnings, rows = [], [], []
    disabled = []
    disabled_cfg = _disabled_by_config(getattr(args, 'date', None))
    for kind, model in (("batter", BatterProfile), ("pitcher", PitcherProfile)):
        print(f"\n--- {kind.upper()} " + "-" * (70 - len(kind)))
        entries = []
        for f in fields(model):
            if f.name == "player":
                continue
            pct = hits[kind].get(f.name, 0) / max(1, n[kind])
            entries.append((pct, f.name, consumed(f.name, src)))
        for pct, name, is_consumed in sorted(entries):
            sparse = name in EXPECTED_SPARSE
            bucket = None
            if is_consumed and pct == 0.0 and name in disabled_cfg:
                # DISABLED != BROKEN. Checked BEFORE the zero-is-failure rule,
                # which is otherwise correct and would swallow the distinction.
                status = "disabled  unfed BY CONFIG, not a defect"
                disabled.append((kind, name, disabled_cfg[name]))
            elif is_consumed and pct == 0.0:
                # zero is a failure even for an expected-sparse field: "sometimes
                # absent" and "never present" are different claims.
                status, bucket = "FAIL  consumed but NEVER populated", failures
            elif is_consumed and pct < SPARSE_FLOOR and not sparse:
                status, bucket = "FAIL  consumed, almost never populated", failures
            elif is_consumed and pct < POPULATED_FLOOR and not sparse:
                status, bucket = "warn  consumed, thinly populated", warnings
            elif not is_consumed and pct == 0.0:
                status = "note  unread and unfed (dead field)"
            else:
                status = "ok"
            if bucket is not None:
                bucket.append((kind, name, pct))
            rows.append({"kind": kind, "field": name, "pct": round(pct, 4),
                         "consumed": is_consumed, "status": status.split()[0]})
            if status != "ok":
                mark = "*" if sparse else " "
                print(f"  {pct:6.1%} {mark} {name:32s} {status}")

    print("\n" + "=" * 88)
    if failures:
        print(f"FAILURES: {len(failures)} field(s) the engine READS and nothing FEEDS\n")
        for kind, name, pct in failures:
            print(f"    {kind:8s} {name:32s} {pct:.1%}")
        print("\n  Each is a silent no-op: the sim runs, produces numbers, and those")
        print("  numbers are identical to a build where the feature does not exist.")
    else:
        print("PASS: every field the engine reads is populated above its floor.")
    if disabled:
        print("\n  %d field(s) unfed BY CONFIG -- not defects, not counted as failures:" % len(disabled))
        for kind, name, why in disabled:
            print("    %-8s %-32s %s" % (kind, name, why))
    if warnings:
        print(f"\n  {len(warnings)} thin field(s) — not failing, worth a look:")
        for kind, name, pct in warnings:
            print(f"    {kind:8s} {name:32s} {pct:.1%}")
    print("  (* = documented as expected-sparse in EXPECTED_SPARSE)")

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(
            {"rosters": len(paths), "counts": n, "failures": len(failures),
             "warnings": len(warnings), "rows": rows}, indent=2), encoding="utf-8")
        print(f"\nwrote {args.json}")

    if args.publish:
        # `os` is imported at MODULE scope (see `_data_root`). A local `import os`
        # here made `os` a local name for the WHOLE function, so the diagnostic
        # REFUSED block above raised UnboundLocalError instead of printing --
        # turning a helpful message into a crash on exactly the failing path.
        from datetime import datetime, timezone
        base = _data_root()   # same root the SNAPSHOTS glob reads from
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        out = (base / "mlb_source/source_artifacts/data/sim_input_report"
               / f"sim_input_report_{stamp}.json")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({
            "schema_version": 1,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            # "worker" iff the mounted-disk root is configured; `_data_root()`
                # falls back to REPO/data on a dev box and that is "local".
                "host": "worker" if str(os.environ.get("SYNDICATE_DATA_ROOT") or "").strip() else "local",
            "rosters": len(paths), "counts": n,
            # the link that four hypotheses could not read remotely
            "season_artifacts": _season_artifact_probe(),
            "failures": [{"kind": k, "field": f, "pct": round(v, 4)} for k, f, v in failures],
            # unfed BY CONFIG -- deliberately OUTSIDE `failures`, so nfail
            # means "things that are wrong"
            "disabled": [{"kind": k, "field": f, "reason": w} for k, f, w in disabled],
            "warnings": [{"kind": k, "field": f, "pct": round(v, 4)} for k, f, v in warnings],
            "rows": rows,
        }, indent=2), encoding="utf-8")
        print("")
        print(f"published {out}")
        print("  This is the ONLY way the production population is readable: the")
        print("  artifacts endpoint gates on HOT_ARTIFACT_PATTERNS and roster_objs")
        print("  is deliberately not on it.")

    # `spec_problems` is NOT gated on --warn-only: it is a source-level
    # contradiction, not a population rate that a thin day can excuse.
    if spec_problems:
        return 1
    return 1 if (failures and not args.warn_only) else 0


if __name__ == "__main__":
    raise SystemExit(main())
