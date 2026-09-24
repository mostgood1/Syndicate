#!/usr/bin/env python3
"""`#688` -- derive the live-tier coverage matrix from the CODE and fail on an
inconsistent row.

WHY THIS EXISTS. The matrix of "which sport has a live tier, and how far does it
reach" was maintained BY HAND, in chat and in ad-hoc audits. Measured
2026-09-24: a hand-built matrix was wrong or stale in THREE of its eight rows
within two hours of being written --

  * `mlb` game lines read "root cause found, not fixed" after the fix had
    deployed and measured (stale 100% -> 64.9% over four builds);
  * `nhl` read "built, not deployed" after the tick was live and verified, and
    "needs October" while eleven preseason games sat on the slate that night;
  * `wnba` read "producer not wired", which was a misread of a GENERIC runtime
    refusal (`board_enrichment.py:1840`, `carries no liveProps`) fired by an
    out-of-season slate. `wnba/live_lens.py:413` populates `liveProps`.

The cost was not cosmetic. On that matrix I recommended allowlisting
`live/nfl_live_lens.json` as cheap work; had it been taken, it would have wired
a PREGAME probability onto a live board (`#340`). Four registries and one
allowlist live in four files, and NOTHING reconciled them.

WHAT THIS CHECKS, and what it deliberately does not.

The four registries are read by IMPORTING the real objects, never by grepping --
the same discipline `sim_input_checklist.py` applies with `dataclasses.fields()`,
and for the same reason: a name grep answers a question about text, not about
what the process will do.

But no static check can tell whether a published number is a GENUINELY LIVE
probability or a pregame one carried forward. That is the `#340` defect, it is
the most expensive mistake available on this surface, and it is invisible to
every registry. So each sport must DECLARE its provenance below, with evidence.
A sport that appears in any registry and is not declared FAILS -- which is the
real gate here: a sport cannot be board-wired without someone stating, on the
record, what its probability actually is.

THE ALLOWLIST COLUMN IS INFORMATIONAL AND IS NOT A CROSSING SIGNAL.
Resolved 2026-09-24 and verified on all three production services:
`live/*_live_lens.json` crosses through KEYVALUE (Redis), never through
`HOT_ARTIFACT_PATTERNS`. `SYNDICATE_REFRESH_STATE_BACKEND` is `keyvalue` on web,
refresh-worker and live-odds-worker; `live/` matches no entry in
`_KEYVALUE_EXCLUDED_PATH_MARKERS`; so `write_json_file` returns after the Redis
SET and `read_json_file` after the GET, and neither touches disk. A 403 from
`/api/ops/artifacts/stream` means "not on disk", never "cannot cross". This
module prints the column so the belief stays visible and refutable, and refuses
to score it, because scoring it is how the wrong recommendation got made.

Exit codes: 0 all rows consistent, 1 at least one FAIL, 2 the check itself could
not run (an import broke).
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Every sport the platform claims, not just those with a live tier. A sport with
# no live tier anywhere is a legitimate row (`ncaab`); a sport MISSING from this
# tuple that turns up in a registry is caught by R1.
ALL_SPORTS: tuple[str, ...] = (
    "mlb", "nba", "wnba", "nhl", "nfl", "ncaaf", "ncaab", "soccer",
)

# Provenance of the GAME-LINE probability a sport publishes.
LIVE_RESIM = "live_resim"          # restarted from the live score/clock
LIVE_PROJECTION = "live_projection"  # re-projected off the live score, may be unpriced
PREGAME_CARRIED = "pregame_carried"  # a pregame number with live score/clock overlaid
NONE = "none"                        # publishes no game-line probability

# Provenance of the PROP projections.
PROPS_WIRED = "wired"
PROPS_ABSENT = "absent"
PROPS_NONE = "none"


@dataclass(frozen=True)
class Declaration:
    """What a sport's live tier ACTUALLY publishes. Evidence is mandatory.

    `alternate_producer` names the module for a sport whose live tier does not
    run on `live_lens_loop`'s tick. Two sports are legitimately in that shape
    (`soccer` writes per-league live-state artifacts; `ncaaf` re-sims on
    refresh-worker's own loop), and without this field R3 would flag both.
    """

    gameline: str
    props: str
    evidence: str
    alternate_producer: str | None = None
    note: str = ""


# One row per sport. ADDING A SPORT TO ANY REGISTRY WITHOUT ADDING IT HERE IS
# THE FAILURE THIS FILE EXISTS TO CAUSE.
DECLARATIONS: dict[str, Declaration] = {
    "mlb": Declaration(
        gameline=LIVE_RESIM,
        props=PROPS_WIRED,
        evidence="mlb/live_lens.py -- in-game Monte Carlo re-sim; lens source `live_mc`",
    ),
    "nba": Declaration(
        gameline=NONE,
        props=PROPS_NONE,
        evidence="in live-lens `skippedSports`; its live tier is a logistic blend "
                 "whose `sim_mu` equals the pregame number, so it publishes no "
                 "independent live game-line probability",
        note="Ticks and is allowlisted; deliberately NOT in the game-line gate. "
             "Wiring it would be `#340` until the blend is replaced by a re-sim.",
    ),
    "wnba": Declaration(
        gameline=LIVE_PROJECTION,
        props=PROPS_WIRED,
        evidence="wnba/live_lens.py:413 populates `liveProps`; board_enrichment's "
                 "`attach_live_gamelines_for_sport` docstring records a measured "
                 "live re-projection (total 151.17 vs pregame 173.96 at 60-53)",
        note="Publishes no `simsRun`, so `price_moneyline` withholds by "
             "REASON_UNUSABLE_SIMS -- a live projection with an explicitly "
             "unpriced edge. That is deliberate, not a gap.",
    ),
    "nhl": Declaration(
        gameline=LIVE_RESIM,
        props=PROPS_NONE,
        evidence="nhl/live_resim.py restarts hockeysim from the current period, "
                 "clock and score; refusals publish a `pregame_only` lane carrying "
                 "NO probability, and the join rejects that stamp",
        note="Moneyline only. Margin/total distributions are withheld on purpose.",
    ),
    "nfl": Declaration(
        gameline=LIVE_RESIM,
        props=PROPS_NONE,
        evidence="nfl/live_resim.py restarts smartsim2 from the live quarter, clock "
                 "and score (`resim_live_game`, MAX_RESUMABLE_PERIOD=4) and ticks on "
                 "refresh-worker (`run_refresh_worker._run_nfl_live_resim_tick`)",
        alternate_producer="syndicate/features/nfl/live_resim.py "
                           "(refresh-worker's own loop, behind SYNDICATE_NFL_LIVE_RESIM, "
                           "code default OFF -- absent on all three services 2026-09-24)",
        note="I FIRST DECLARED THIS `pregame_carried` FROM THE WRONG MODULE. "
             "`nfl/live_lens.py` is pregame-carried and says so, but it is the LENS "
             "page builder, not the sport's live tier -- `nfl/live_resim.py` (600 "
             "lines) is. The wrong declaration made R6 and R8 silent on the one sport "
             "they were built for, which is the documented soft spot of this file: "
             "the registries are derived, the provenance is asserted.",
    ),
    "ncaaf": Declaration(
        gameline=LIVE_RESIM,
        props=PROPS_NONE,
        evidence="ncaaf/live_resim.py restarts smartsim2 from the current quarter, "
                 "clock and score; refusals publish a `pregame` lane the join rejects",
        alternate_producer="syndicate/features/ncaaf/live_resim.py "
                           "(refresh-worker's own loop, not live_lens_loop's tick)",
    ),
    "ncaab": Declaration(
        gameline=NONE,
        props=PROPS_NONE,
        evidence="no live tier of any kind; source-app-mirror only",
    ),
    "soccer": Declaration(
        gameline=LIVE_RESIM,
        props=PROPS_WIRED,
        evidence="poll_soccer_live_state.py writes per-league live state; the board "
                 "join reads it via `soccer_live_gameline_source`",
        alternate_producer="syndicate/features/shared/soccer_live_gameline_source.py "
                           "(NOT the lens path -- `live/soccer_live_lens.json` is the "
                           "tick-status snapshot and carries no `gameLens`)",
    ),
}


# KNOWN-OPEN findings, mirroring `migration_gate.ALLOWED_AUDIT_FINDINGS`. A
# waived finding is printed as [KNOWN] and does NOT fail the gate; anything else
# does. THE WAIVER CANNOT ROT: a waived finding that stops firing is itself a
# FAIL (`R0_STALE_WAIVER`), because a fix nobody removed the waiver for is
# indistinguishable from a rule that quietly stopped working -- the same
# `missing_allowed_findings` guard the migration gate already applies.
#
# Every entry names the lane that owns it. An entry with no owner is a defect
# nobody is fixing wearing the costume of one somebody is.
KNOWN_OPEN: dict[tuple[str, str], str] = {
    ("R6_LIVE_PRODUCER_WITHOUT_GATE", "nfl"):
        "lane `nfl-live-resim-activation` (2026-09-24): the re-sim ticks on "
        "refresh-worker behind SYNDICATE_NFL_LIVE_RESIM (default OFF) and the "
        "board never reads it. Enabling it publishes live money edges on an "
        "engine documented to lose to the close -- a user decision, not wiring.",
    ("R8_SNAPSHOT_PATH_COLLISION", "nfl"):
        "lane `nfl-live-resim-activation` (2026-09-24): the lens loop and the "
        "re-sim share one key. Latent while the flag is OFF; must be resolved "
        "BEFORE it is ever turned on, or the pregame writer races the live one.",
}

@dataclass
class Finding:
    rule: str
    sport: str
    level: str  # FAIL | INFO
    message: str


@dataclass
class Registries:
    lens: frozenset[str]
    builders: frozenset[str]
    validators: frozenset[str]
    snapshot_paths: frozenset[str]
    props: frozenset[str]
    gameline: frozenset[str]
    sources: frozenset[str]
    allowlisted: frozenset[str]


def load_registries() -> Registries:
    """Import the real objects. A grep would answer a question about text."""
    from syndicate.features.shared.artifact_publisher import HOT_ARTIFACT_PATTERNS
    from syndicate.features.shared.board_enrichment import (
        _LIVE_GAMELINE_SPORTS,
        _LIVE_PROP_SPORTS,
    )
    from syndicate.features.shared.live_gameline_join import LIVE_LENS_SOURCES_BY_SPORT
    from syndicate.features.shared.live_lens_loop import (
        _LIVE_LENS_BUILDERS,
        _LIVE_LENS_SNAPSHOT_PATHS,
        _LIVE_LENS_SPORTS,
        _LIVE_LENS_VALIDATORS,
    )

    allowlisted = {
        pattern[len("live/"):-len("_live_lens.json")]
        for pattern in HOT_ARTIFACT_PATTERNS
        if pattern.startswith("live/") and pattern.endswith("_live_lens.json")
    }
    return Registries(
        lens=frozenset(_LIVE_LENS_SPORTS),
        builders=frozenset(_LIVE_LENS_BUILDERS),
        validators=frozenset(_LIVE_LENS_VALIDATORS),
        snapshot_paths=frozenset(_LIVE_LENS_SNAPSHOT_PATHS),
        props=frozenset(_LIVE_PROP_SPORTS),
        gameline=frozenset(_LIVE_GAMELINE_SPORTS),
        sources=frozenset(LIVE_LENS_SOURCES_BY_SPORT),
        allowlisted=frozenset(allowlisted),
    )


def resim_snapshot_path(sport: str) -> str | None:
    """Where a sport's `live_resim` module publishes, if it has one.

    Signatures differ on purpose and both are real: `nhl` takes no argument
    (the lens-loop registry calls it directly), `ncaaf`/`nfl` take a data root.
    Probing both is what lets this be a DERIVED check rather than another
    assertion -- and an assertion is exactly what failed for nfl.
    """
    import importlib

    try:
        module = importlib.import_module(f"syndicate.features.{sport}.live_resim")
    except Exception:
        return None
    resolver = getattr(module, "live_lens_snapshot_path", None)
    if resolver is None:
        return None
    from syndicate.features.shared.refresh_state_store import data_root

    for args in ((), (data_root(),)):
        try:
            return str(resolver(*args))
        except TypeError:
            continue
        except Exception:
            return None
    return None


def loop_snapshot_path(sport: str) -> str | None:
    """Where `live_lens_loop`'s tick publishes for this sport, if registered."""
    try:
        from syndicate.features.shared.live_lens_loop import _LIVE_LENS_SNAPSHOT_PATHS
    except Exception:
        return None
    resolver = _LIVE_LENS_SNAPSHOT_PATHS.get(sport)
    if resolver is None:
        return None
    try:
        return str(resolver())
    except Exception:
        return None


def _loop_resolver_is_the_resim(sport: str) -> bool:
    """True when the lens loop registered the RESIM's own path resolver.

    That is one producer wearing two names, not two producers sharing a key.
    """
    import importlib

    try:
        from syndicate.features.shared.live_lens_loop import _LIVE_LENS_SNAPSHOT_PATHS
        module = importlib.import_module(f"syndicate.features.{sport}.live_resim")
    except Exception:
        return False
    return _LIVE_LENS_SNAPSHOT_PATHS.get(sport) is getattr(
        module, "live_lens_snapshot_path", None
    )


def evaluate(reg: Registries, declarations: dict[str, Declaration]) -> list[Finding]:
    findings: list[Finding] = []

    in_any_registry = (
        reg.lens | reg.builders | reg.validators | reg.snapshot_paths
        | reg.props | reg.gameline | reg.sources | reg.allowlisted
    )

    # R1 -- the gate that makes every other rule enforceable. An undeclared sport
    # in a registry means somebody wired a surface without stating what it
    # publishes, which is exactly how a pregame number reaches a live board.
    for sport in sorted(in_any_registry):
        if sport not in declarations:
            findings.append(Finding(
                "R1_UNDECLARED", sport, "FAIL",
                "appears in a live registry with no entry in DECLARATIONS -- "
                "state its game-line provenance and evidence before wiring it",
            ))

    # R7 -- the three lens registries must name the same sports. A builder with
    # no validator publishes an unvalidated snapshot; a path with no builder is
    # a read of something nothing writes.
    if not (reg.builders == reg.validators == reg.snapshot_paths):
        skew = sorted(
            (reg.builders | reg.validators | reg.snapshot_paths)
            - (reg.builders & reg.validators & reg.snapshot_paths)
        )
        findings.append(Finding(
            "R7_LENS_REGISTRY_SKEW", ",".join(skew) or "-", "FAIL",
            "builders / validators / snapshot paths do not name the same sports",
        ))

    for sport in sorted(declarations):
        decl = declarations[sport]
        has_producer = sport in reg.lens or decl.alternate_producer is not None

        # R2 -- `#340`. The most expensive mistake on this surface: a pregame
        # probability published under a live label.
        if sport in reg.gameline and decl.gameline in (PREGAME_CARRIED, NONE):
            findings.append(Finding(
                "R2_PREGAME_UNDER_LIVE_LABEL", sport, "FAIL",
                f"in the game-line gate while declaring `{decl.gameline}` -- this "
                f"publishes a pregame number on a live board (#340). Evidence: "
                f"{decl.evidence}",
            ))

        # R3 -- the board asks and nothing answers.
        if sport in reg.gameline and not has_producer:
            findings.append(Finding(
                "R3_GATE_WITHOUT_PRODUCER", sport, "FAIL",
                "in the game-line gate but absent from the lens tick and declaring "
                "no `alternate_producer`",
            ))

        # R4 -- same shape, prop side.
        if sport in reg.props and decl.props == PROPS_ABSENT:
            findings.append(Finding(
                "R4_PROP_GATE_WITHOUT_PRODUCER", sport, "FAIL",
                "in the prop gate while declaring its prop producer absent",
            ))

        # R5 -- lens-source config for a sport the board never joins.
        if sport in reg.sources and sport not in reg.gameline:
            findings.append(Finding(
                "R5_SOURCES_WITHOUT_GATE", sport, "FAIL",
                "has LIVE_LENS_SOURCES_BY_SPORT config but is not in the game-line "
                "gate -- the config is dead",
            ))

        # R6 -- built and inert. This was NHL's state for most of 2026-09-24:
        # a working re-sim publishing to a board that never read it.
        if decl.gameline in (LIVE_RESIM, LIVE_PROJECTION) and has_producer \
                and sport not in reg.gameline:
            findings.append(Finding(
                "R6_LIVE_PRODUCER_WITHOUT_GATE", sport, "FAIL",
                f"declares `{decl.gameline}` and has a producer, but is not in the "
                "game-line gate -- the re-sim runs and nothing consumes it",
            ))

        # R8 -- TWO PRODUCERS, ONE KEY. Found on nfl 2026-09-24: the lens loop
        # (live-odds-worker, pregame-carried) and the live re-sim
        # (refresh-worker) resolve the SAME `live/nfl_live_lens.json`, which on
        # Render is one Redis key. Last writer wins, on a ~60s cadence, from two
        # services -- and the pregame one overwriting the live one is `#340`
        # arriving by race rather than by wiring. Latent only because the resim
        # flag defaults OFF.
        # SAME PATH IS NOT ENOUGH -- it must be TWO PRODUCERS. `nhl` registers
        # its resim's OWN resolver in the loop (`live_lens_loop.py` imports
        # `nhl.live_resim.live_lens_snapshot_path` as `_nhl_snapshot_path`), so
        # one producer owns the path and there is nothing to race. Comparing
        # only the strings flagged nhl on the first run of this rule -- a row
        # that is correct as-is, which this lane's own falsification test
        # forbids. Function IDENTITY separates the two cases exactly.
        loop_path = loop_snapshot_path(sport)
        resim_path = resim_snapshot_path(sport)
        if loop_path and resim_path and loop_path == resim_path                 and not _loop_resolver_is_the_resim(sport):
            findings.append(Finding(
                "R8_SNAPSHOT_PATH_COLLISION", sport, "FAIL",
                f"the lens-loop builder and {sport}/live_resim.py both publish "
                f"{loop_path} -- one key, two writers on two services, last write "
                "wins. One producer must own the path (the `ncaaf` precedent: it is "
                "absent from the lens loop and its re-sim owns the file)",
            ))

        # I1 -- informational ONLY, see the module docstring.
        if sport in reg.allowlisted and sport not in reg.builders:
            findings.append(Finding(
                "I1_ALLOWLIST_WITHOUT_BUILDER", sport, "INFO",
                "allowlisted with no lens builder. Harmless: the entry names a "
                "path nothing writes, and on Render the allowlist is not the "
                "crossing channel anyway",
            ))

    return findings


def render_matrix(reg: Registries, declarations: dict[str, Declaration]) -> str:
    header = (
        f"{'sport':8s} {'lens':5s} {'prop':5s} {'GL':4s} {'src':4s} "
        f"{'allow*':7s} {'gameline provenance':20s} props"
    )
    lines = [header, "-" * len(header)]
    for sport in ALL_SPORTS:
        decl = declarations.get(sport)
        mark = lambda flag: " yes " if flag else "  -  "  # noqa: E731
        lines.append(
            f"{sport:8s} {mark(sport in reg.lens):5s} {mark(sport in reg.props):5s} "
            f"{mark(sport in reg.gameline)[:4]:4s} {mark(sport in reg.sources)[:4]:4s} "
            f"{mark(sport in reg.allowlisted)[:7]:7s} "
            f"{(decl.gameline if decl else 'UNDECLARED'):20s} "
            f"{(decl.props if decl else 'UNDECLARED')}"
        )
    lines.append("")
    lines.append(
        "* `allow` is INFORMATIONAL and is NOT a crossing signal. Verified "
        "2026-09-24 on all three\n"
        "  services: live/*_live_lens.json crosses via KEYVALUE (Redis), never via "
        "HOT_ARTIFACT_PATTERNS.\n"
        "  A 403 from /api/ops/artifacts/stream means 'not on disk', never 'cannot "
        "cross'."
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--quiet", action="store_true",
                        help="print findings only, not the matrix")
    args = parser.parse_args(argv)

    try:
        reg = load_registries()
    except Exception as exc:  # the check itself could not run
        print(f"LIVE_TIER_COVERAGE could not load registries: {exc!r}")
        return 2

    findings = evaluate(reg, DECLARATIONS)

    if not args.quiet:
        print(render_matrix(reg, DECLARATIONS))
        print()

    raw_fails = [f for f in findings if f.level == "FAIL"]
    infos = [f for f in findings if f.level == "INFO"]

    fails = [f for f in raw_fails if (f.rule, f.sport) not in KNOWN_OPEN]
    known = [f for f in raw_fails if (f.rule, f.sport) in KNOWN_OPEN]

    fired = {(f.rule, f.sport) for f in raw_fails}
    stale = [key for key in KNOWN_OPEN if key not in fired]

    for finding in fails + infos:
        print(f"[{finding.level}] {finding.rule} {finding.sport}: {finding.message}")
    for finding in known:
        print(f"[KNOWN] {finding.rule} {finding.sport}: "
              f"{KNOWN_OPEN[(finding.rule, finding.sport)]}")
    for rule, sport in sorted(stale):
        print(f"[FAIL] R0_STALE_WAIVER {sport}: {rule} is waived in KNOWN_OPEN but no "
              "longer fires -- if it is fixed, DELETE the waiver; if the rule broke, "
              "that is the bug")

    print()
    print(f"LIVE_TIER_COVERAGE sports={len(ALL_SPORTS)} declared={len(DECLARATIONS)} "
          f"fail={len(fails)} known_open={len(known)} stale_waiver={len(stale)} "
          f"info={len(infos)}")
    return 1 if (fails or stale) else 0


if __name__ == "__main__":
    raise SystemExit(main())
