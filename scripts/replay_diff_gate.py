"""Replay a mirrored production day through the REAL worker code, offline, and
diff what it produces against production's own answer. `todo.md #625` item (5).

    py -3 scripts/replay_diff_gate.py --date 2026-08-29
    py -3 scripts/replay_diff_gate.py --date 2026-08-29 --json
    py -3 scripts/replay_diff_gate.py --date 2026-08-29 --perturb   # prove it can FAIL

EXIT CODES -- and the middle one is the whole point
---------------------------------------------------
    0  PASS            every declared output reproduced within tolerance
    1  FAIL            an output differs, or the target ran and wrote nothing
    3  NO_FIXTURE      no mirror, no manifest, or the day is not comparable

`3` is NOT a pass. `migration_gate.py` reports it as UNKNOWN and never folds it
into `ok`. A guard that maps "I could not tell" onto its permissive branch is
the failure this repo has written down more times than any other, and a replay
gate with no fixture is exactly that case.

WHY THIS EXISTS -- four defects from ONE day, 2026-09-02
--------------------------------------------------------
All four were PRESENT IN PRODUCTION AND NOT WORKING, and every one cost
production time and most cost a deploy:

  1. `#626`(h)'s evaluation autorun: shipped, tested, and had NEVER RUN -- the
     env flag was absent and the job defaults OFF.
  2. The `odds_history` merge size cap: sized against a 39 MB soccer shard while
     MLB's pair is 109 MB, so the merge was INERT on the largest files.
  3. That autorun's decline path returned False silently, so "disabled", "gate
     refused" and "never reached" were one indistinguishable silence for 100
     minutes.
  4. Once armed, it OOM-killed refresh-worker (anon 1,833 -> 3,868 MB against a
     4,096 MB ceiling).

Every one is observable from a mirrored day plus a local run. None needed a
deploy to find. That is the case for this file.

THE THREE LAWS, AS ENFORCED HERE RATHER THAN ASSERTED
------------------------------------------------------
**(1) One-way flows.** The replay runs `_run_book_grid_artifact_tick`, and that
tick calls `publish_hot_artifact` (`run_refresh_worker.py:4753`) -- an HTTP POST
that writes the artifact onto production web's disk. Running the real worker
entrypoint on a laptop with a live `ADMIN_TOKEN` would therefore push a
LOCALLY-BUILT board onto production. That is precisely the bidirectional flow
law (1) forbids, and it is not hypothetical: it is what the real code does. So
the child process runs behind a **deny-all socket guard** and with every
credential stripped from its environment. Two independent mechanisms, because
one of them silently failing is how this class of accident happens.

The tick also PULLS (`pull_streamed_artifact`, `4693`/`4708`) to reconcile its
shard against web. Denying that is not a limitation of the harness -- it is what
makes the run a replay of the mirrored bytes rather than a fresh pull. The tick
already treats both as non-fatal (`artifact_publisher`'s contract is "must never
raise"), so denial produces a clean local-only build rather than a crash.

**(2) Parity or it isn't evidence.** The fixture must carry a
`mirror_manifest.py` manifest, and this gate re-verifies every input hash before
running. The manifest id is printed with the result and belongs in any claim
made from it.

**(3) Replay-first.** `book_quotes` IS a tick tape. The replayed target's whole
job is to pivot it. No fetch mode is implicit: the guard records every outbound
attempt with host and port, and a single attempt is reported.

THE COMPARABILITY PRECONDITION, and why it is checked rather than assumed
-------------------------------------------------------------------------
Production built its artifact at some instant T from the shard AS IT WAS AT T.
The mirror holds the shard as it is NOW. If the shard grew after T, the replay
reads more quotes than production did and the diff measures the passage of time,
not the code.

So the fixture is only comparable when **every input is older than the output**.
That is checkable, and it is checked: `_check_comparability` compares mtimes
from the manifest and returns NO_FIXTURE rather than a diff it cannot interpret.

This holds far more often than it sounds, because the tick rebuilds YESTERDAY
once per day after its shard stops growing (`run_refresh_worker.py:4617-4625`).
Measured 2026-09-02 over ten consecutive MLB dates: the output was newer than
every input on **10 of 10**.

TOLERANCE
---------
Default is EXACT: `atol=0, rtol=0`. Every relaxation and every excluded field is
declared in the target with a REASON, because a tolerance is an admission that
something is not deterministic and the admission should be legible. A field
whose difference is explained by the clock is excluded by name; a field that
merely happens to be close is not.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Floating-point slack on every tolerance comparison. A tolerance of exactly
# 0.1 rejected `3.5 - 3.6` because that subtraction is -0.10000000000000142 in
# binary floating point -- the values differ by precisely the declared step and
# the check failed anyway. Without this, a tolerance sized in the units the data
# is rounded to can never actually hold.
TOLERANCE_EPSILON = 1e-9

EXIT_PASS = 0
EXIT_FAIL = 1
EXIT_NO_FIXTURE = 3

# Environment variables that let a run escape `SYNDICATE_DATA_ROOT`. Enumerated
# rather than trusted: `data_root()` is honoured per call
# (`refresh_state_store.py:445`), but three separate mechanisms sit in front of
# it and each would silently read the developer's own checkout instead of the
# fixture.
DATA_ROOT_ESCAPES: tuple[str, ...] = tuple(
    # `source_roots.py:117-120`: when set, the per-sport root wins and
    # SYNDICATE_DATA_ROOT is never consulted at all.
    [f"SYNDICATE_{sport}_SOURCE_ROOT" for sport in ("MLB", "NBA", "WNBA", "NHL", "NFL", "NCAAF", "NCAAB", "SOCCER")]
    # Read at IMPORT time (`vendor/mlb_bettingv2/tools/web/flask_frontend.py:120-135`),
    # so a value here is baked in before any test could patch it.
    + [f"{sport}_LIVE_LENS_DIR" for sport in ("MLB", "NBA", "NHL", "WNBA")]
)

# Stripped from the child. The socket guard already denies every connection;
# this is the second, independent mechanism. A credential that is not in the
# environment cannot be spent by a code path the guard somehow misses.
CREDENTIAL_ENV: tuple[str, ...] = (
    "ADMIN_TOKEN",
    "SYNDICATE_ADMIN_TOKEN",
    "RENDER_API_KEY",
    "CFBD_API_KEY",
    "ODDS_API_KEY",
    "THE_ODDS_API_KEY",
    "ODDSAPI_KEY",
    "KALSHI_API_KEY",
    "KALSHI_PRIVATE_KEY",
    "POLYMARKET_API_KEY",
    "POLYMARKET_PRIVATE_KEY",
    "ANTHROPIC_API_KEY",
    "REDIS_URL",
    "SYNDICATE_KEYVALUE_URL",
)


def _match_reason(rules: tuple[tuple[str, str], ...], path: str) -> str | None:
    """Match a glob against the raw path AND its index-collapsed form.

    `rows[*].game` does NOT work: in fnmatch `[...]` is a CHARACTER CLASS, so
    `rows[*]` means "rows followed by one literal `*`" and silently matches
    nothing. Every per-row exclusion written that way is inert while looking
    correct -- which is the defect class this whole gate exists to catch, and it
    was in the gate's own tolerance table first. Patterns are written against
    the collapsed form, `rows[].game*`.
    """
    collapsed = _collapse_indices(path)
    for pattern, reason in rules:
        if fnmatch.fnmatch(path, pattern) or fnmatch.fnmatch(collapsed, pattern):
            return reason
    return None


@dataclass(frozen=True)
class Tolerance:
    """Exact by default. Each relaxation carries the reason it was needed."""

    atol: float = 0.0
    rtol: float = 0.0
    # fnmatch globs over the dotted JSON path, each paired with WHY it is
    # excluded. A bare exclusion list decays into a place to hide failures.
    volatile: tuple[tuple[str, str], ...] = ()
    # Fields derived from ONE shared clock reading taken inside the run. They
    # are checked ANCHOR-RELATIVE rather than excluded: a single offset is
    # estimated across all of them and every field must then agree with it.
    #
    # WHY THIS IS NOT FITTING THE ANSWER. The artifact's only recorded clock is
    # `generated_at`, stamped AFTER the pivot; the ages were computed before it.
    # Measured on 2026-09-01: the gap is a CONSTANT 3.6s on 3,151 of 3,207 rows
    # and 3.5s on the other 56 -- one unknown, 58,336 constraints. Estimating it
    # and then requiring every field to satisfy it leaves 58,335 degrees of
    # freedom, so a real change to any age still fails.
    clock_relative: tuple[tuple[str, str], ...] = ()
    clock_relative_atol: float = 0.1
    clock_offset_max_sec: float = 60.0

    # Per-field absolute tolerance: (glob, atol, reason). Distinct from
    # `clock_relative` because these fields carry NO shared offset -- a
    # difference of two clock-derived values cancels it -- so folding them into
    # the offset estimate both biases the estimate and then fails them by it.
    field_atol: tuple[tuple[str, float, str], ...] = ()

    def is_clock_relative(self, path: str) -> str | None:
        return _match_reason(self.clock_relative, path)

    def field_atol_for(self, path: str) -> tuple[float, str] | None:
        collapsed = _collapse_indices(path)
        for pattern, atol, reason in self.field_atol:
            if fnmatch.fnmatch(path, pattern) or fnmatch.fnmatch(collapsed, pattern):
                return atol, reason
        return None

    def is_volatile(self, path: str) -> str | None:
        return _match_reason(self.volatile, path)

    def numbers_agree(self, left: float, right: float) -> bool:
        if left == right:
            return True
        if math.isnan(left) and math.isnan(right):
            return True
        return abs(left - right) <= self.atol + self.rtol * abs(right) + TOLERANCE_EPSILON


@dataclass(frozen=True)
class ReplayTarget:
    name: str
    entrypoint: str
    """`module:function` of the REAL worker code invoked. Recorded in the report
    so a pass names what actually ran -- `presence is not reachability`."""
    description: str
    input_families: tuple[str, ...]
    output_families: tuple[str, ...]
    outputs: tuple[str, ...]
    """Relative paths the target MUST produce, with `{date}`/`{slug}`."""
    clock_field: str
    """Top-level field in the FIRST output carrying the instant production built
    it. The replay's clock is frozen to this, so age fields are checked rather
    than excluded."""
    tolerance: Tolerance


# The cell-level `reason` string, per SIDE and per CELL KIND.
#
# Sides are enumerated rather than wildcarded because in fnmatch `*` spans dots:
# `rows[].cells.*.reason` also swallows
# `rows[].cells.<book>.<side>.market_basis.reason`, a different field that is
# checked for real. A rule written for one field silently excluding its
# neighbour is the same class of quiet over-reach this gate exists to catch.
QUOTE_REASON_EXCLUSIONS: tuple[tuple[str, str], ...] = tuple(
    (
        f"rows[].{holder}.{side}.reason",
        "a human RENDERING of lag_behind_freshest_seconds, quantised to MINUTES "
        "(`'1h 6m behind the freshest quote on this market'`), so the +/-0.1s rounding "
        "declared under field_atol flips the text whenever the lag sits on a minute "
        "boundary. Measured on 2026-09-01: exactly 2 cells out of 301,694 leaves, both on "
        "row 689, `1h 6m` against `1h 7m`. The NUMBERS this string renders "
        "(`lag_behind_freshest_seconds`, `age_seconds`, `stale`, `price`) all stay checked, "
        "so a real change to the refusal logic still fails the gate; only the prose is out.",
    )
    for holder in ("cells.*", "best")
    for side in ("over", "under", "home", "away", "draw")
)

BOOK_GRID_TOLERANCE = Tolerance(
    atol=0.0,
    rtol=0.0,
    volatile=(
        # NOTE what is NOT here: `generated_at`. With the clock frozen it MATCHES
        # production to the microsecond, and leaving it checked makes it the
        # assertion that the freeze took effect. Excluding it would have hidden
        # a silently-unfrozen run behind 58,000 downstream mismatches.
        (
            "projections.summary_artifact",
            "an ABSOLUTE filesystem path. Production records "
            "`/opt/render/project/data/...`; any replay records its own scratch root. "
            "Environment-dependent by construction, on every machine that is not Render.",
        ),
        # ---- UNREPLAYABLE: the input's historical value does not exist ----
        #
        # Every one of these traces to ONE file: `data_root()/live/<sport>_live_lens.json`
        # (`board_enrichment.py:485`). It is NOT dated -- one mutable file holding
        # the CURRENT snapshot -- so there is no historical value to mirror, and
        # staging today's copy would apply today's live games to a past date,
        # which is worse than absent. It is allowlisted
        # (`artifact_publisher.py:885`) yet web's disk holds ZERO files matching
        # `live/*` (measured twice, 45 minutes apart, 2026-09-02).
        #
        # CONFIRMED as the single cause, not assumed: production recorded
        # `live_game_state.transitions = {"live->pregame": 229}` for 2026-09-01,
        # and on all 167 rows whose `projection.edge_unavailable_reason` differs
        # the replay says `game.state = live` where production says `pregame` --
        # 167 of 167, no exceptions. `projections.rows_with_edge` 187 -> 53 and
        # `margin_model.modelled_edge_rows_priced` 67 -> 44 are the same rows
        # counted again downstream.
        (
            "live_game_state*",
            "UNREPLAYABLE: needs live/mlb_live_lens.json, a non-dated mutable snapshot with no "
            "historical value. DATING IT WAS MEASURED AND REJECTED 2026-09-03 -- it is a single "
            "4,194,400-byte KEYVALUE key, so one write per 60s tick is ~5.76 GB/day for MLB alone "
            "against a 256 MB store already 86.8% full. The block now carries a `lens_fingerprint` "
            "instead: a divergence here is ATTRIBUTABLE even though it is not reproducible.",
        ),
        ("live_gamelines*", "UNREPLAYABLE: same live-lens snapshot."),
        ("live_projections*", "UNREPLAYABLE: same live-lens snapshot."),
        ("live_gameline_score*", "UNREPLAYABLE: scores the game states the live-lens snapshot corrects."),
        ("live_gameline_accuracy*", "UNREPLAYABLE: same chain as live_gameline_score."),
        ("rows[].game*", "UNREPLAYABLE: per-row game state, corrected by the live-lens snapshot."),
        (
            "rows[].projection*",
            "UNREPLAYABLE: live_edge_policy reads game.state, so an uncorrected state withholds the edge.",
        ),
        ("projections.rows_with_edge", "UNREPLAYABLE: counts the rows above."),
        ("projections.pct_with_edge", "UNREPLAYABLE: counts the rows above."),
        ("margin_model.modelled_edge*", "UNREPLAYABLE: refuses on the same uncorrected game states."),
        (
            "game_state.chips",
            "UNREPLAYABLE: attach_game_state resolves chips for the dates the ROWS span "
            "(board_enrichment.py:70-97), so it needs D+1's slate -- and D's grid is rebuilt "
            "DURING D+1, so D+1's snapshot directory is still being written when production "
            "answers. Measured: `D+1 settled before D's output` was FALSE on 9 of 9 dates.",
        ),
        *QUOTE_REASON_EXCLUSIONS,
    ),
    clock_relative=(
        (
            "*age_seconds",
            "time since a quote moved / was last seen: `now - stamp`, one shared `now` "
            "(book_grid.py:362). Checked against the estimated shared offset, not excluded.",
        ),
    ),
    field_atol=(
        (
            "*lag_behind_freshest_seconds",
            0.1,
            "a DIFFERENCE of two clock-derived ages (book_grid.py:426), so the shared offset "
            "CANCELS and only the 0.1s rounding step on each term survives. Measured on "
            "2026-09-01: all 553 differing values were exactly +/-0.1, none larger. It is "
            "deliberately NOT in clock_relative -- an offset of zero folded into that estimate "
            "would both bias it and then fail every one of these by the bias.",
        ),
    ),
    clock_relative_atol=0.1,
    clock_offset_max_sec=60.0,
)

TARGETS: dict[str, ReplayTarget] = {
    "mlb_book_grid": ReplayTarget(
        name="mlb_book_grid",
        entrypoint="scripts.run_refresh_worker:_run_book_grid_artifact_tick",
        description=(
            "The Layer 1 book-grid pivot. The one tick that is central, cheap and "
            "confirmed network-free end to end: it reads the book_quotes tick tape "
            "already on disk and writes the bounded grid web serves. Its own module "
            "docstring states the property a replay-diff exists to check -- 'the "
            "pivot's output depends on row ORDER, anything that touches it must be "
            "compared grid-to-grid, not by totals' (book_grid_artifact.py:216-221) -- "
            "after two earlier reductions permuted 2,006 of 5,547 rows at IDENTICAL "
            "total byte length, invisible to every count and size check."
        ),
        input_families=("mlb_book_grid_replay", "mlb_book_grid_enrichment"),
        output_families=("mlb_book_grid_output",),
        outputs=("mlb_source/data/book_grid/book_grid_{date}.json",),
        clock_field="generated_at",
        tolerance=BOOK_GRID_TOLERANCE,
    ),
}


# --------------------------------------------------------------------------
# CHILD: runs inside a scrubbed subprocess. Everything below `_child_main` runs
# with no network and no credentials.
# --------------------------------------------------------------------------


def _install_socket_guard(record: list[dict[str, Any]]) -> None:
    """Deny every outbound connection and RECORD what was attempted.

    Recording matters as much as denying. "Did this code path try to reach the
    network?" is otherwise answered by reading it, and reading it is how a
    conditional fetch behind a cache check gets missed.
    """
    import socket

    class ReplayNetworkDenied(OSError):
        pass

    def _deny(where: str, address: Any) -> None:
        host, port = (address + (None, None))[:2] if isinstance(address, tuple) else (str(address), None)
        record.append({"via": where, "host": host, "port": port})
        raise ReplayNetworkDenied(
            f"replay is offline: {where} to {host}:{port} denied. "
            "One-way flows (#625 law 1): a replay must not read from or write to production."
        )

    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex

    def guarded_connect(self, address):  # type: ignore[no-untyped-def]
        _deny("socket.connect", address)
        return original_connect(self, address)

    def guarded_connect_ex(self, address):  # type: ignore[no-untyped-def]
        _deny("socket.connect_ex", address)
        return original_connect_ex(self, address)

    def guarded_create_connection(address, *args, **kwargs):  # type: ignore[no-untyped-def]
        _deny("socket.create_connection", address)

    socket.socket.connect = guarded_connect  # type: ignore[method-assign]
    socket.socket.connect_ex = guarded_connect_ex  # type: ignore[method-assign]
    socket.create_connection = guarded_create_connection  # type: ignore[assignment]


def _freeze_clock(epoch: float) -> None:
    """Replay the CLOCK as the input it is.

    `build_book_grid` takes `now` as a parameter and defaults it to
    `datetime.now(timezone.utc)` (`book_grid.py:362`); production calls it with
    `now=None`, so the argument is identical either way and only the clock
    moves. Every `age_seconds` in the artifact is `now - quote_time`, so an
    unfrozen replay differs from production on ~58,000 leaves for no reason
    except elapsed time, and threshold-derived flags (`stale`, a cell's
    `reason`) FLIP at the margin -- which makes the gate flaky as well as noisy.

    Frozen to production's own `generated_at`, those become checked fields
    instead of excluded ones. `generated_at` itself is then the assertion that
    the freeze took effect: if this silently failed, it is the first mismatch.

    Patched GLOBALLY and BEFORE the target is imported, because a module that
    did `from datetime import datetime` at import time keeps whatever the name
    pointed at then. `time.monotonic` is deliberately untouched -- it backs
    cache TTLs, not artifact values, and freezing it would wedge them.
    """
    import datetime as _datetime_module
    import time as _time_module

    real_time = _time_module.time
    frozen_utc = _datetime_module.datetime.fromtimestamp(epoch, _datetime_module.timezone.utc)

    class _FrozenDateTime(_datetime_module.datetime):
        # A SUBCLASS, so `isinstance(x, datetime)` keeps working everywhere.
        @classmethod
        def now(cls, tz=None):  # type: ignore[override]
            return frozen_utc.astimezone(tz) if tz is not None else frozen_utc.replace(tzinfo=None)

        @classmethod
        def utcnow(cls):  # type: ignore[override]
            return frozen_utc.replace(tzinfo=None)

        @classmethod
        def today(cls):  # type: ignore[override]
            return frozen_utc.replace(tzinfo=None)

    _datetime_module.datetime = _FrozenDateTime  # type: ignore[misc]
    _time_module.time = lambda: epoch  # type: ignore[assignment]
    _time_module._replay_real_time = real_time  # type: ignore[attr-defined]


def _child_main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--_child", action="store_true")
    parser.add_argument("--target", required=True)
    parser.add_argument("--date", required=True)
    parser.add_argument("--receipt", required=True)
    parser.add_argument("--freeze-epoch", type=float, default=None)
    args = parser.parse_args(argv)

    network_attempts: list[dict[str, Any]] = []
    _install_socket_guard(network_attempts)

    receipt: dict[str, Any] = {
        "target": args.target,
        "date": args.date,
        "network_attempts": network_attempts,
        "data_root": os.environ.get("SYNDICATE_DATA_ROOT"),
        "reports_root": os.environ.get("SYNDICATE_REPORTS_ROOT"),
        "frozen_epoch": args.freeze_epoch,
    }
    target = TARGETS[args.target]
    module_name, _, function_name = target.entrypoint.partition(":")

    real_time = time.time
    if args.freeze_epoch is not None:
        _freeze_clock(args.freeze_epoch)
    started = real_time()
    try:
        import importlib

        module = importlib.import_module(module_name)
        # Patch the CLOCK, not the logic. "What day is it" is an input to this
        # tick like any other; every date it derives (previous day, the forward
        # window, the per-sport coverage check) comes from this one call, so
        # moving it moves the whole run coherently. Patching the tick's
        # behaviour instead would replay something production never ran.
        module.central_today_iso = lambda: args.date  # type: ignore[attr-defined]
        receipt["clock_patched_to"] = args.date
        receipt["module_file"] = getattr(module, "__file__", None)
        function = getattr(module, function_name)
        result = function()
        receipt["ok"] = True
        receipt["result"] = result if isinstance(result, (dict, list, str, int, float, type(None))) else repr(result)
    except BaseException as exc:  # noqa: BLE001 -- a crash is a RESULT here
        receipt["ok"] = False
        receipt["error"] = f"{type(exc).__name__}: {exc}"
        import traceback

        receipt["traceback"] = traceback.format_exc()[-4000:]
    receipt["elapsed_sec"] = round(real_time() - started, 2)

    # What actually landed on disk. `files_written` is the reachability check:
    # a target that runs cleanly and writes nothing is INERT, which is the
    # defect class this gate exists for, and it must not read as a pass.
    root = Path(os.environ["SYNDICATE_DATA_ROOT"])
    slug = args.date.replace("-", "_")
    written: list[dict[str, Any]] = []
    for template in target.outputs:
        relative = template.format(date=args.date, slug=slug)
        path = root / relative
        if path.is_file():
            written.append({"path": relative, "bytes": path.stat().st_size})
        else:
            written.append({"path": relative, "bytes": None, "absent": True})
    receipt["outputs"] = written

    Path(args.receipt).write_text(json.dumps(receipt, indent=2, default=str), encoding="utf-8")
    return 0 if receipt.get("ok") else 1


# --------------------------------------------------------------------------
# DIFF
# --------------------------------------------------------------------------


@dataclass
class DiffResult:
    compared: int = 0
    excluded: int = 0
    mismatch_count: int = 0
    # UNCAPPED histogram, keyed by the path with list indices collapsed
    # (`rows[]​.game.state`). The recorded sample is capped and the sample is
    # what a reader sees first, so the shape of a 69,000-mismatch result has to
    # survive truncation or the report understates the problem it just found.
    mismatch_by_key: dict[str, int] = field(default_factory=dict)
    mismatches: list[dict[str, Any]] = field(default_factory=list)
    excluded_paths: dict[str, str] = field(default_factory=dict)
    unreplayable: dict[str, str] = field(default_factory=dict)
    clock_pairs: list[tuple[str, float, float]] = field(default_factory=list)
    clock_offset_sec: float | None = None
    clock_checked: int = 0

    def record(self, mismatch: dict[str, Any], *, cap: int) -> None:
        """Count every mismatch; keep only the first `cap` in full.

        Counting and recording are separated on purpose. `mismatch_count` is
        the number that decides PASS/FAIL and it is never capped; the list is
        the readable sample. Conflating them is how a truncated report becomes
        a smaller-looking problem.
        """
        self.mismatch_count += 1
        key = _collapse_indices(str(mismatch.get("path") or "<root>"))
        self.mismatch_by_key[key] = self.mismatch_by_key.get(key, 0) + 1
        if len(self.mismatches) < cap:
            self.mismatches.append(mismatch)

    @property
    def ok(self) -> bool:
        return self.mismatch_count == 0


def diff_json(
    produced: Any,
    expected: Any,
    tolerance: Tolerance,
    *,
    path: str = "",
    result: DiffResult | None = None,
    max_mismatches: int = 40,
) -> DiffResult:
    """Structural, order-sensitive, tolerance-aware.

    ORDER-SENSITIVE on purpose. `build_book_grid` anchors on the first row
    carrying a given canonical line, so a permutation is a real behaviour change
    that leaves every count and total identical. Comparing lists as sets would
    make this gate blind to the exact defect its target's own docstring records.
    """
    result = result if result is not None else DiffResult()
    # The cap bounds what is RECORDED, never what is traversed. An earlier
    # version returned here once 40 mismatches had accumulated, and the effect
    # was that `rows` -- the 12 MB the artifact is actually for -- was never
    # compared at all while the report said `leaves compared 34`. A gate that
    # stops looking after the first page of failures reports a clean bill on
    # everything it did not reach.

    if path:
        reason = tolerance.is_volatile(path)
        if reason is not None:
            result.excluded += 1
            result.excluded_paths[_collapse_indices(path)] = reason
            return result
        scaled = tolerance.field_atol_for(path)
        if (
            scaled is not None
            and isinstance(expected, (int, float))
            and isinstance(produced, (int, float))
            and not isinstance(expected, bool)
            and not isinstance(produced, bool)
        ):
            result.compared += 1
            if abs(float(produced) - float(expected)) > scaled[0] + TOLERANCE_EPSILON:
                result.record(
                    {
                        "path": path,
                        "kind": "field_atol",
                        "expected": expected,
                        "produced": produced,
                        "atol": scaled[0],
                    },
                    cap=max_mismatches,
                )
            return result
        reason = tolerance.is_clock_relative(path)
        if reason is not None and isinstance(expected, (int, float)) and isinstance(produced, (int, float)):
            # DEFERRED, not skipped. Judged after the traversal, once the shared
            # offset can be estimated across every such field at once.
            if not isinstance(expected, bool) and not isinstance(produced, bool):
                result.clock_pairs.append((path, float(produced), float(expected)))
                return result

    if isinstance(expected, dict) and isinstance(produced, dict):
        for key in sorted(set(expected) | set(produced)):
            child = f"{path}.{key}" if path else key
            if key not in produced:
                if tolerance.is_volatile(child):
                    result.excluded += 1
                    continue
                result.record({"path": child, "kind": "missing_in_replay", "expected": _brief(expected[key])}, cap=max_mismatches)
            elif key not in expected:
                if tolerance.is_volatile(child):
                    result.excluded += 1
                    continue
                result.record({"path": child, "kind": "extra_in_replay", "produced": _brief(produced[key])}, cap=max_mismatches)
            else:
                diff_json(produced[key], expected[key], tolerance, path=child, result=result, max_mismatches=max_mismatches)
        return result

    if isinstance(expected, list) and isinstance(produced, list):
        if len(expected) != len(produced):
            result.record(
                {"path": path or "<root>", "kind": "length", "expected": len(expected), "produced": len(produced)},
                cap=max_mismatches,
            )
            return result
        for index, (left, right) in enumerate(zip(produced, expected)):
            diff_json(left, right, tolerance, path=f"{path}[{index}]", result=result, max_mismatches=max_mismatches)
        return result

    result.compared += 1
    if isinstance(expected, bool) or isinstance(produced, bool):
        # bool before number: `True == 1` in Python, and a flag flipping to an
        # int is a real change that numeric tolerance would swallow.
        if expected is not produced:
            result.record(
                {"path": path or "<root>", "kind": "value", "expected": expected, "produced": produced},
                cap=max_mismatches,
            )
        return result
    if isinstance(expected, (int, float)) and isinstance(produced, (int, float)):
        if not tolerance.numbers_agree(float(produced), float(expected)):
            result.record(
                {
                    "path": path or "<root>",
                    "kind": "number",
                    "expected": expected,
                    "produced": produced,
                    "delta": float(produced) - float(expected),
                },
                cap=max_mismatches,
            )
        return result
    if expected != produced:
        result.record(
            {"path": path or "<root>", "kind": "value", "expected": _brief(expected), "produced": _brief(produced)},
            cap=max_mismatches,
        )
    return result


def finalize_clock_relative(result: DiffResult, tolerance: Tolerance, *, cap: int = 40) -> None:
    """Estimate the one shared clock offset, then hold every deferred field to it."""
    if not result.clock_pairs:
        return
    deltas = sorted(produced - expected for _, produced, expected in result.clock_pairs)
    offset = deltas[len(deltas) // 2]
    result.clock_offset_sec = round(offset, 3)
    result.clock_checked = len(result.clock_pairs)
    if abs(offset) > tolerance.clock_offset_max_sec:
        # A large offset is not an anchoring artefact any more -- it means the
        # clock freeze did not take, or the replay read a different instant.
        # Reporting it as one failure beats emitting 58,000 that all say the
        # same thing.
        result.record(
            {
                "path": "<clock offset>",
                "kind": "clock_offset_out_of_bounds",
                "expected": f"|offset| <= {tolerance.clock_offset_max_sec}s",
                "produced": f"{offset:.3f}s across {len(result.clock_pairs)} fields",
            },
            cap=cap,
        )
        return
    for path, produced, expected in result.clock_pairs:
        if abs((produced - expected) - offset) > tolerance.clock_relative_atol + TOLERANCE_EPSILON:
            result.record(
                {
                    "path": path,
                    "kind": "clock_relative",
                    "expected": expected,
                    "produced": produced,
                    "delta_vs_offset": round((produced - expected) - offset, 3),
                },
                cap=cap,
            )


def _collapse_indices(path: str) -> str:
    """`rows[17].game.state` -> `rows[].game.state`, so 3,000 row-level
    mismatches aggregate into one line instead of 3,000."""
    return re.sub(r"\[\d+\]", "[]", path)


def _brief(value: Any, limit: int = 120) -> Any:
    if isinstance(value, (dict, list)):
        text = json.dumps(value, default=str)
        return text[:limit] + ("..." if len(text) > limit else "")
    if isinstance(value, str) and len(value) > limit:
        return value[:limit] + "..."
    return value


# --------------------------------------------------------------------------
# PARENT
# --------------------------------------------------------------------------


def _load_manifest(root: Path, date_str: str) -> dict[str, Any] | None:
    path = root / "_manifests" / f"{date_str}.json"
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _check_comparability(manifest: dict[str, Any], target: ReplayTarget) -> dict[str, Any]:
    """Every input must be older than every output, or the diff is meaningless.

    See the module docstring. This is the difference between "the code changed"
    and "the day carried on after production answered".
    """
    files = manifest.get("files") or {}
    families = manifest.get("families") or {}
    input_paths = [p for p in files if _in_families(p, families, target.input_families)]
    output_paths = [p for p in files if _in_families(p, families, target.output_families)]
    if not input_paths:
        return {"ok": False, "reason": "no input files in the manifest for this target"}
    if not output_paths:
        return {"ok": False, "reason": "no production output in the manifest -- nothing to diff against"}
    newest_input = max((files[p].get("remote_mtime") or 0) for p in input_paths)
    oldest_output = min((files[p].get("remote_mtime") or 0) for p in output_paths)
    # NAME the offenders. "an input is newer" is unactionable; the fix is always
    # to narrow one specific pattern, and that needs the file.
    offenders = sorted(
        (
            {"path": p, "newer_by_sec": round((files[p].get("remote_mtime") or 0) - oldest_output, 1)}
            for p in input_paths
            if (files[p].get("remote_mtime") or 0) >= oldest_output
        ),
        key=lambda row: -row["newer_by_sec"],
    )
    return {
        "ok": not offenders,
        "newest_input_mtime": newest_input,
        "oldest_output_mtime": oldest_output,
        "margin_sec": round(oldest_output - newest_input, 1),
        "input_files": len(input_paths),
        "output_files": len(output_paths),
        "inputs_newer_than_output": offenders[:10],
        "reason": (
            ""
            if not offenders
            else f"{len(offenders)} input(s) are NEWER than production's output. Production answered "
            "from a smaller input than the mirror holds, so a diff would measure elapsed time, not "
            "code. Narrow the pattern, or pass --allow-newer-inputs and carry the caveat."
        ),
    }


def _in_families(relative_path: str, families: dict[str, Any], names: Iterable[str]) -> bool:
    for name in names:
        spec = families.get(name) or {}
        for pattern in spec.get("patterns") or ():
            if fnmatch.fnmatch(relative_path, pattern):
                return True
    return False


def _stage_inputs(mirror: Path, manifest: dict[str, Any], target: ReplayTarget, scratch: Path) -> dict[str, Any]:
    """Copy INPUT families into the scratch root. Outputs are deliberately NOT
    copied: if production's own answer were present, the target could read it,
    or a reader could mistake it for something the replay produced."""
    files = manifest.get("files") or {}
    families = manifest.get("families") or {}
    staged = 0
    total = 0
    for relative_path in sorted(files):
        if not _in_families(relative_path, families, target.input_families):
            continue
        source = mirror / relative_path
        if not source.is_file():
            return {"ok": False, "reason": f"manifest names {relative_path} but it is not on disk"}
        destination = scratch / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        staged += 1
        total += source.stat().st_size
    return {"ok": staged > 0, "files": staged, "bytes": total, "reason": "" if staged else "no input files staged"}


def _child_env(scratch: Path) -> dict[str, str]:
    env = dict(os.environ)
    for name in DATA_ROOT_ESCAPES:
        env.pop(name, None)
    for name in CREDENTIAL_ENV:
        env.pop(name, None)
    # `RENDER=1` makes `data_root()` raise instead of falling back, which is
    # right on Render and wrong here -- the fixture root is set explicitly.
    env.pop("RENDER", None)
    env.pop("SYNDICATE_REQUIRE_HOSTED_STORAGE", None)
    env["SYNDICATE_DATA_ROOT"] = str(scratch)
    # `reports_root()` is NOT under SYNDICATE_DATA_ROOT (refresh_state_store.py:367).
    # Without this the replay reads and writes the developer's own `reports/`.
    env["SYNDICATE_REPORTS_ROOT"] = str(scratch / "reports")
    # The keyvalue backend is a network hop; the guard would deny it anyway, but
    # a file backend inside the fixture is what a replay actually wants.
    env["SYNDICATE_REFRESH_STATE_BACKEND"] = "file"
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def run_replay(
    *,
    target: ReplayTarget,
    date_str: str,
    mirror: Path,
    keep: bool,
    perturb: bool,
    allow_newer_inputs: bool = False,
    freeze_clock: bool = True,
) -> dict[str, Any]:
    report: dict[str, Any] = {
        "target": target.name,
        "entrypoint": target.entrypoint,
        "date": date_str,
        "mirror": str(mirror),
        "status": "NO_FIXTURE",
    }

    manifest = _load_manifest(mirror, date_str)
    if manifest is None:
        report["reason"] = (
            f"no manifest at {mirror / '_manifests' / (date_str + '.json')}. "
            "A local day with no manifest is not a fixture (#625 law 2). "
            f"Run: py -3 scripts/mirror_manifest.py sync --date {date_str}"
        )
        return report
    report["manifest_id"] = manifest.get("manifest_id")
    report["manifest_files"] = len(manifest.get("files") or {})

    comparability = _check_comparability(manifest, target)
    report["comparability"] = comparability
    if not comparability["ok"]:
        if not allow_newer_inputs:
            report["reason"] = comparability["reason"]
            return report
        # Explicit, recorded escape hatch -- the same idiom as the deploy
        # protocol's `--allow-off-main`. The run proceeds and the caveat travels
        # with the result rather than being lost at the command line.
        report["caveat"] = (
            "RAN WITH --allow-newer-inputs: "
            + ", ".join(row["path"] for row in comparability.get("inputs_newer_than_output") or [])
            + " postdate production's output, so any mismatch below may be elapsed time rather than code."
        )

    scratch_parent = Path(tempfile.mkdtemp(prefix=f"replay_{target.name}_{date_str}_"))
    scratch = scratch_parent / "data"
    scratch.mkdir(parents=True, exist_ok=True)
    try:
        staged = _stage_inputs(mirror, manifest, target, scratch)
        report["staged"] = staged
        if not staged["ok"]:
            report["reason"] = staged["reason"]
            return report

        if perturb:
            # NEGATIVE CONTROL. A gate that has never been observed to fail is
            # not known to be a gate. This drops the LAST line of the tick tape,
            # the smallest change to an input that the pivot could notice.
            slug = date_str.replace("-", "_")
            tape = scratch / f"mlb_source/tracking/book_quotes/{date_str}.jsonl"
            if not tape.is_file():
                report["reason"] = f"--perturb needs {tape} and it is not staged"
                return report
            raw = tape.read_bytes()
            cut = raw.rstrip(b"\n").rfind(b"\n")
            tape.write_bytes(raw[: cut + 1] if cut > 0 else b"")
            report["perturbed"] = {
                "path": tape.name,
                "bytes_before": len(raw),
                "bytes_after": tape.stat().st_size,
                "note": "dropped the final quote row from the tick tape",
            }

        # THE FREEZE EPOCH COMES FROM PRODUCTION'S OWN OUTPUT.
        #
        # Reading one scalar -- the instant production stamped into its artifact
        # -- to set the replay's clock is replaying an INPUT, not peeking at the
        # answer. The output file is never staged into the scratch root, so the
        # target cannot read it; only this harness does, and only for this field.
        freeze_epoch: float | None = None
        freeze_source = "off"
        if freeze_clock:
            for template in target.outputs:
                expected_path = mirror / template.format(date=date_str, slug=date_str.replace("-", "_"))
                if not expected_path.is_file():
                    continue
                try:
                    stamp = json.loads(expected_path.read_text(encoding="utf-8")).get(target.clock_field)
                    if stamp:
                        from datetime import datetime as _dt

                        freeze_epoch = _dt.fromisoformat(str(stamp).replace("Z", "+00:00")).timestamp()
                        freeze_source = f"{expected_path.name}:{target.clock_field}={stamp}"
                except Exception as exc:  # noqa: BLE001
                    freeze_source = f"unreadable ({type(exc).__name__})"
                break
        report["clock"] = {"frozen": freeze_epoch is not None, "epoch": freeze_epoch, "source": freeze_source}
        if freeze_clock and freeze_epoch is None:
            # Do not silently fall back to the real clock: an unfrozen run
            # differs on ~58,000 clock-derived leaves and would read as a
            # catastrophic FAIL rather than as "the freeze did not happen".
            report["status"] = "NO_FIXTURE"
            report["reason"] = (
                f"could not read `{target.clock_field}` from production's output ({freeze_source}); "
                "refusing to replay against the real clock, which would differ on every age field."
            )
            return report

        receipt_path = scratch_parent / "receipt.json"
        command = [
            sys.executable,
            str(Path(__file__).resolve()),
            "--_child",
            "--target",
            target.name,
            "--date",
            date_str,
            "--receipt",
            str(receipt_path),
        ]
        if freeze_epoch is not None:
            command.extend(["--freeze-epoch", repr(freeze_epoch)])
        started = time.time()
        completed = subprocess.run(
            command,
            cwd=str(REPO_ROOT),
            env=_child_env(scratch),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=3600,
        )
        report["child"] = {
            "returncode": completed.returncode,
            "elapsed_sec": round(time.time() - started, 1),
            "stdout_tail": (completed.stdout or "")[-3000:],
            "stderr_tail": (completed.stderr or "")[-3000:],
        }
        if not receipt_path.is_file():
            report["status"] = "FAIL"
            report["reason"] = "the replay child produced no receipt -- it did not reach the end of its run"
            return report
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        report["receipt"] = receipt
        report["network_attempts"] = receipt.get("network_attempts") or []

        if not receipt.get("ok"):
            report["status"] = "FAIL"
            report["reason"] = f"the target raised: {receipt.get('error')}"
            return report

        # REACHABILITY BEFORE CORRECTNESS. A target that ran cleanly and wrote
        # nothing is the deployed-inert case; it must never read as a pass.
        absent = [row["path"] for row in receipt.get("outputs") or [] if row.get("absent")]
        if absent:
            report["status"] = "FAIL"
            report["reason"] = (
                "the target completed and wrote NOTHING for: " + ", ".join(absent) + ". "
                "That is the inert case, not a pass."
            )
            return report

        # DIFF
        diffs: list[dict[str, Any]] = []
        slug = date_str.replace("-", "_")
        all_ok = True
        for template in target.outputs:
            relative = template.format(date=date_str, slug=slug)
            produced_path = scratch / relative
            expected_path = mirror / relative
            if not expected_path.is_file():
                diffs.append({"path": relative, "ok": False, "reason": "production's output is not in the mirror"})
                all_ok = False
                continue
            produced = json.loads(produced_path.read_text(encoding="utf-8"))
            expected = json.loads(expected_path.read_text(encoding="utf-8"))
            result = diff_json(produced, expected, target.tolerance)
            finalize_clock_relative(result, target.tolerance)
            entry = {
                "path": relative,
                "ok": result.ok,
                "produced_bytes": produced_path.stat().st_size,
                "expected_bytes": expected_path.stat().st_size,
                "leaves_compared": result.compared,
                "leaves_excluded": result.excluded,
                "clock_relative_checked": result.clock_checked,
                "clock_offset_sec": result.clock_offset_sec,
                "excluded_paths": result.excluded_paths,
                "mismatch_count": result.mismatch_count,
                # NOT capped in the JSON. The TEXT report shows the top 25 for
                # readability; the machine-readable report carries every distinct
                # field path, because classifying a 69,000-mismatch result means
                # partitioning that whole list, not its head.
                "mismatch_by_key": dict(sorted(result.mismatch_by_key.items(), key=lambda kv: -kv[1])),
                "mismatch_key_total": len(result.mismatch_by_key),
                "mismatches": result.mismatches[:40],
            }
            diffs.append(entry)
            all_ok = all_ok and result.ok
        report["diffs"] = diffs
        report["status"] = "PASS" if all_ok else "FAIL"
        report["tolerance"] = {
            "atol": target.tolerance.atol,
            "rtol": target.tolerance.rtol,
            "volatile": [{"pattern": p, "reason": r} for p, r in target.tolerance.volatile],
        }
        if perturb:
            # Inverted: with a perturbed input, PASS is the failure.
            report["negative_control"] = {
                "expected": "FAIL",
                "observed": report["status"],
                "ok": report["status"] == "FAIL",
            }
        return report
    finally:
        if keep:
            report["scratch_kept"] = str(scratch_parent)
        else:
            shutil.rmtree(scratch_parent, ignore_errors=True)


def render_report(report: dict[str, Any]) -> str:
    lines: list[str] = []
    status = report.get("status", "?")
    lines.append(f"REPLAY-DIFF  target={report.get('target')}  date={report.get('date')}  ->  {status}")
    lines.append(f"  entrypoint      {report.get('entrypoint')}   (the REAL worker function, not a stand-in)")
    lines.append(f"  mirror          {report.get('mirror')}")
    if report.get("manifest_id"):
        lines.append(f"  manifest_id     {report['manifest_id']}   ({report.get('manifest_files')} files) -- cite this")
    comparability = report.get("comparability") or {}
    if comparability:
        lines.append(
            f"  comparability   {'OK' if comparability.get('ok') else 'NO'}  "
            f"output is {comparability.get('margin_sec')}s newer than the newest input "
            f"({comparability.get('input_files')} in / {comparability.get('output_files')} out)"
        )
    staged = report.get("staged") or {}
    if staged:
        lines.append(f"  staged          {staged.get('files')} input files, {staged.get('bytes', 0):,} bytes")
    if report.get("perturbed"):
        p = report["perturbed"]
        lines.append(f"  PERTURBED       {p['note']}  ({p['bytes_before']:,} -> {p['bytes_after']:,} bytes)")
    clock = report.get("clock") or {}
    if clock:
        lines.append(
            f"  clock           {'FROZEN to production' if clock.get('frozen') else 'REAL (age fields will differ)'}"
            + (f"  <- {clock.get('source')}" if clock.get("frozen") else "")
        )
    child = report.get("child") or {}
    if child:
        lines.append(f"  child           rc={child.get('returncode')}  {child.get('elapsed_sec')}s")
    attempts = report.get("network_attempts") or []
    lines.append(f"  network         {len(attempts)} outbound attempt(s), all DENIED")
    for attempt in attempts[:6]:
        lines.append(f"                    {attempt.get('via')} -> {attempt.get('host')}:{attempt.get('port')}")
    if len(attempts) > 6:
        lines.append(f"                    ... {len(attempts) - 6} more")
    for entry in report.get("diffs") or []:
        lines.append("")
        lines.append(f"  [{'PASS' if entry.get('ok') else 'FAIL'}] {entry['path']}")
        if entry.get("reason"):
            lines.append(f"        {entry['reason']}")
            continue
        lines.append(
            f"        replay {entry['produced_bytes']:,}B vs production {entry['expected_bytes']:,}B   "
            f"leaves compared {entry['leaves_compared']:,}, excluded {entry['leaves_excluded']}"
        )
        if entry.get("clock_relative_checked"):
            lines.append(
                f"        clock-relative {entry['clock_relative_checked']:,} field(s) checked against a shared "
                f"offset of {entry.get('clock_offset_sec')}s (production stamps its clock after the pivot)"
            )
        # Grouped by REASON, not by path. One `rows[].cells.*.reason` rule
        # matches 44 books x 2 sides, and printing its paragraph 88 times buries
        # the mismatches underneath it.
        by_reason: dict[str, list[str]] = {}
        for path, reason in (entry.get("excluded_paths") or {}).items():
            by_reason.setdefault(reason, []).append(path)
        for reason, paths in by_reason.items():
            shown = ", ".join(sorted(paths)[:3]) + (f" (+{len(paths) - 3} more)" if len(paths) > 3 else "")
            lines.append(f"        excluded  {shown}")
            lines.append(f"                  -- {reason}")
        by_key = entry.get("mismatch_by_key") or {}
        if by_key:
            lines.append(f"        mismatches by field ({entry.get('mismatch_key_total')} distinct field paths):")
            for key, count in list(by_key.items())[:25]:
                lines.append(f"          {count:>8,}  {key}")
            if len(by_key) > 25:
                lines.append(f"          ... {entry.get('mismatch_key_total', 0) - 25} more field paths")
            lines.append("        sample:")
        for mismatch in entry.get("mismatches") or []:
            lines.append(
                f"        DIFF  {mismatch.get('path')}  [{mismatch.get('kind')}]  "
                f"expected={_brief(mismatch.get('expected'), 60)}  produced={_brief(mismatch.get('produced'), 60)}"
            )
        if entry.get("mismatch_count", 0) > len(entry.get("mismatches") or []):
            lines.append(f"        ... {entry['mismatch_count'] - len(entry['mismatches'])} more mismatches")
    control = report.get("negative_control")
    if control:
        lines.append("")
        lines.append(
            f"  NEGATIVE CONTROL  expected {control['expected']}, observed {control['observed']}  "
            f"-> {'the gate can fail' if control['ok'] else 'THE GATE DID NOT NOTICE -- it is not a gate'}"
        )
    for row in (report.get("comparability") or {}).get("inputs_newer_than_output") or []:
        lines.append(f"                    NEWER THAN OUTPUT by {row['newer_by_sec']}s: {row['path']}")
    if report.get("caveat"):
        lines.append("")
        lines.append(f"  CAVEAT          {report['caveat']}")
    if report.get("reason"):
        lines.append("")
        lines.append(f"  reason          {report['reason']}")
    if status == "NO_FIXTURE":
        lines.append("")
        lines.append("  NO_FIXTURE IS NOT A PASS. This run proves nothing about worker behaviour.")
    return "\n".join(lines)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--_child", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--target", default="mlb_book_grid", choices=sorted(TARGETS))
    parser.add_argument("--date", help="ISO date of the mirrored day")
    parser.add_argument("--mirror", help="mirror root (else SYNDICATE_MIRROR_ROOT)")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--write", help="write the JSON report to this path")
    parser.add_argument("--keep-scratch", action="store_true")
    parser.add_argument(
        "--perturb",
        action="store_true",
        help="NEGATIVE CONTROL: corrupt one input, then require the gate to FAIL",
    )
    parser.add_argument(
        "--allow-newer-inputs",
        action="store_true",
        help="proceed even when an input postdates production's output; the caveat is recorded in the report",
    )
    parser.add_argument(
        "--real-clock",
        action="store_true",
        help="do NOT freeze the clock to production's build instant (every age field will then differ)",
    )
    parser.add_argument("--receipt", help=argparse.SUPPRESS)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    raw = list(argv if argv is not None else sys.argv[1:])
    if "--_child" in raw:
        return _child_main(raw)

    args = parse_args(raw)
    if not args.date:
        print("--date is required")
        return 2

    from scripts.mirror_manifest import mirror_root

    mirror = mirror_root(args.mirror)
    target = TARGETS[args.target]
    report = run_replay(
        target=target,
        date_str=args.date,
        mirror=mirror,
        keep=args.keep_scratch,
        perturb=args.perturb,
        allow_newer_inputs=args.allow_newer_inputs,
        freeze_clock=not args.real_clock,
    )

    if args.write:
        Path(args.write).parent.mkdir(parents=True, exist_ok=True)
        Path(args.write).write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print(render_report(report))

    if args.perturb:
        control = report.get("negative_control") or {}
        return EXIT_PASS if control.get("ok") else EXIT_FAIL
    return {"PASS": EXIT_PASS, "FAIL": EXIT_FAIL}.get(str(report.get("status")), EXIT_NO_FIXTURE)


if __name__ == "__main__":
    raise SystemExit(main())
