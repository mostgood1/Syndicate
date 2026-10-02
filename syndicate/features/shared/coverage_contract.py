"""ONE uniform coverage contract across sports, so "end to end working" is checkable.

WHY THIS EXISTS `[2026-09-29, lane e2e-coverage-contract, user: "I need ALL sports
that are active FULLY end to end working"]`.

The per-sport diagnostics in the Layer 2 shortlist do NOT share a schema. MLB, NHL
and soccer report combined `rows_considered` / `rows_with_projection`; NFL, NCAAF
and WNBA split into `game_rows_*` / `prop_rows_*`. Nothing declares which shape a
sport uses.

That is not cosmetic. Building the first cross-sport matrix, I read MLB's
`game_rows_with_projection` -- a key MLB does not emit -- got None, and was about
to report MLB's healthy **773/882 = 87.6%** as **0%**. A reader that assumes one
schema silently misreports every sport that uses the other, and it misreports them
as BROKEN, which is the direction that wastes the most time.

THE TWO RULES THAT MAKE THIS SAFE, both learned the hard way in this repo:

1. **AN ABSENT KEY IS `not_reported`, NEVER ZERO.** A missing metric and a measured
   zero are completely different facts, and mapping absence onto the zero branch is
   how a failed join turns into a confident "no coverage". `learnings.md` carries
   this as a standing rule ("Unknown must not default permissive"; "Absence in a
   window isn't absence").

2. **A ZERO MUST CARRY A STATED REASON.** `no live re-sim wired for nhl` (a code
   gap) and `no soccer match in play` (an empty population) are the same number and
   opposite problems. A zero with no reason is `unattributed_zero` -- the one state
   this contract treats as a defect in the INSTRUMENT, because it is unactionable.

PROVENANCE IS PART OF THE ANSWER. Every cell records the key path it resolved
from, so a sport that changes its diagnostic shape shows up as `not_reported` or a
changed `source_key` rather than as a silent number. That is the property that
makes a regression gate trustworthy: the gate can tell "the coverage fell" from
"the reader stopped understanding this sport".

This module READS diagnostics. It computes no coverage of its own and reaches no
network or disk, so it is safe to call from a request path or a test.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

#: Cell statuses, ordered from healthy to broken-instrument.
OK = "ok"
DEGRADED = "degraded"                 #: a real number, but below full coverage
ATTRIBUTED_ZERO = "attributed_zero"   #: zero WITH a stated reason -- actionable
UNATTRIBUTED_ZERO = "unattributed_zero"  #: zero with NO reason -- instrument defect
NOT_REPORTED = "not_reported"         #: the sport emits no such metric -- schema drift

#: The four cells of the matrix.
PREGAME_GAMES = "pregame_games"
PREGAME_PROPS = "pregame_props"
LIVE_GAMES = "live_games"
LIVE_PROPS = "live_props"
CELLS = (PREGAME_GAMES, PREGAME_PROPS, LIVE_GAMES, LIVE_PROPS)

#: Candidate key paths per cell, tried IN ORDER against the sport's enrichment
#: block. The split (`game_rows_*`) forms come FIRST so a sport emitting both a
#: split and a combined count is read at the finer grain rather than being
#: credited with prop rows under a games cell.
_CANDIDATES: dict[str, tuple[tuple[tuple[str, ...], tuple[str, ...]], ...]] = {
    PREGAME_GAMES: (
        (("projections", "game_rows_with_projection"), ("projections", "game_rows_considered")),
        (("projections", "game_coverage", "rows_with_projection"),
         ("projections", "game_coverage", "rows_considered")),
        # Combined form (MLB / NHL / soccer): these sports do not separate the two
        # families in their diagnostics, so the combined count is reported here and
        # the props cell reads `not_reported` rather than inventing a split.
        (("projections", "rows_with_projection"), ("projections", "rows_considered")),
    ),
    PREGAME_PROPS: (
        (("projections", "prop_rows_with_projection"), ("projections", "prop_rows_considered")),
        (("projections", "prop_coverage", "rows_with_projection"),
         ("projections", "prop_coverage", "rows_considered")),
    ),
    LIVE_GAMES: (
        (("live_gamelines", "rows_live_gameline_projected"),
         ("live_gamelines", "rows_live_gameline_considered")),
    ),
    LIVE_PROPS: (
        (("live_projections", "rows_live_projected"),
         ("live_projections", "rows_live_considered")),
    ),
}

#: DERIVED cells: (considered_path, shortfall_path) -> projected = considered - shortfall.
#:
#: MLB -- the REFERENCE module other sports converge toward -- emits no
#: `*_rows_with_projection` split at all, but it does emit the pieces:
#: `game_rows_considered` with `game_no_projection`, and `player_rows_considered`
#: with `player_no_projection`. Without this, MLB's games cell falls through to the
#: COMBINED `rows_with_projection` (763/871, games and props mixed) and its props
#: cell reads `not_reported` -- so the one sport everything is modelled on would be
#: the least legible row in the matrix.
#:
#: These are tried BEFORE the combined fallback, and only when BOTH parts are
#: present -- a shortfall with no denominator derives nothing rather than guessing.
_DERIVED: dict[str, tuple[tuple[tuple[str, ...], tuple[str, ...]], ...]] = {
    PREGAME_GAMES: (
        (("projections", "game_rows_considered"), ("projections", "game_no_projection")),
    ),
    PREGAME_PROPS: (
        (("projections", "player_rows_considered"), ("projections", "player_no_projection")),
    ),
}

#: Where a cell's refusal reason lives, tried in order.
_REASON_PATHS: dict[str, tuple[tuple[str, ...], ...]] = {
    PREGAME_GAMES: (("projections", "game_coverage", "reason"), ("projections", "reason")),
    PREGAME_PROPS: (("projections", "prop_coverage", "reason"), ("projections", "reason")),
    LIVE_GAMES: (("live_gamelines", "reason"),),
    LIVE_PROPS: (("live_projections", "reason"),),
}

_SUPPORTED_PATHS: dict[str, tuple[tuple[str, ...], ...]] = {
    PREGAME_GAMES: (("projections", "game_coverage", "supported"), ("projections", "supported")),
    PREGAME_PROPS: (("projections", "prop_coverage", "supported"), ("projections", "supported")),
    LIVE_GAMES: (("live_gamelines", "supported"),),
    LIVE_PROPS: (("live_projections", "supported"),),
}


def _dig(block: Any, path: tuple[str, ...]) -> Any:
    node = block
    for key in path:
        if not isinstance(node, dict) or key not in node:
            return None
        node = node[key]
    return node


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class Cell:
    """One cell of the matrix, with the provenance of how it was resolved.

    `projected is None` means NOT REPORTED. It never means zero -- that
    distinction is the whole point of this module.
    """

    name: str
    projected: int | None = None
    considered: int | None = None
    reason: str | None = None
    supported: bool | None = None
    source_key: str | None = None

    @property
    def rate(self) -> float | None:
        """Coverage as a rate, or None when there is no denominator.

        A bare count cannot distinguish a thin slate from a broken join, so
        callers are pushed toward the rate -- but a rate is NOT invented when the
        denominator is missing or zero.
        """
        if self.projected is None or not self.considered:
            return None
        return self.projected / self.considered

    @property
    def status(self) -> str:
        if self.projected is None:
            return NOT_REPORTED
        if self.projected > 0:
            if self.considered and self.projected < self.considered:
                return DEGRADED
            return OK
        return ATTRIBUTED_ZERO if (self.reason or "").strip() else UNATTRIBUTED_ZERO

    def describe(self) -> str:
        if self.status == NOT_REPORTED:
            return "not reported by this sport"
        rate = self.rate
        head = (f"{self.projected}/{self.considered}"
                if self.considered is not None else str(self.projected))
        if rate is not None:
            head += f" ({100.0 * rate:.1f}%)"
        if self.reason:
            head += f" -- {self.reason}"
        return head


@dataclass(frozen=True)
class SportCoverage:
    sport: str
    candidates: int | None = None
    cells: dict[str, Cell] = field(default_factory=dict)
    #: True when `active_sports` lists this sport, False when it lists others and
    #: not this one, None when the payload carries no `active_sports` at all.
    #: The three-way distinction is the point -- see `defects`.
    active: bool | None = None

    def cell(self, name: str) -> Cell:
        return self.cells.get(name) or Cell(name=name)

    @property
    def defects(self) -> list[str]:
        """Cells whose state makes end-to-end status UNVERIFIABLE.

        Deliberately NOT a list of coverage gaps. A zero with a stated reason is a
        known, actionable gap and is not a defect of the instrument; an
        unattributed zero or a metric this sport stopped reporting is.

        AN OUT-OF-SEASON SPORT CONTRIBUTES NOTHING `[2026-10-02, lane
        coverage-gate-inactive-sports]`. `read_shortlist` unions `per_sport_ingest`
        with `active_sports` so an ACTIVE sport can never vanish from the matrix --
        but that guard was one-directional, so an INACTIVE sport carrying a
        zero-activity ingest block got judged and produced four `not_reported`
        defects. Measured on the live fleet 2026-10-02: **8 of the gate's 9 defects
        were mlb and nba out of season**, i.e. 89% noise, which is how a gate earns
        being switched off. The row is still SHOWN -- hiding it would lose the fact
        that the sport is reported-but-idle.

        `active is None` STILL GETS JUDGED. A payload with no `active_sports` does
        not prove a sport is out of season, and mapping that unknown onto the
        permissive branch is the exact failure this contract exists to refuse.
        """
        if self.active is False:
            return []
        out = []
        for name in CELLS:
            c = self.cell(name)
            if c.status in (UNATTRIBUTED_ZERO, NOT_REPORTED):
                out.append(f"{self.sport}.{name}: {c.status}")
        return out


def read_sport(sport: str, ingest_block: Any, *, active: bool | None = None) -> SportCoverage:
    """Normalise one sport's `per_sport_ingest` entry into the contract.

    `active` is three-way on purpose: True (listed in `active_sports`), False
    (the payload lists sports and not this one), None (no `active_sports` to
    read). Only an explicit False exempts a sport from `defects`.
    """
    block = ingest_block if isinstance(ingest_block, dict) else {}
    enrichment = block.get("enrichment") if isinstance(block.get("enrichment"), dict) else {}
    cells: dict[str, Cell] = {}
    for name in CELLS:
        projected = considered = None
        source = None
        # Direct split keys first: they are the finest grain and need no arithmetic.
        for proj_path, cons_path in _CANDIDATES[name][:2]:
            value = _as_int(_dig(enrichment, proj_path))
            if value is None:
                continue
            projected = value
            considered = _as_int(_dig(enrichment, cons_path))
            source = ".".join(proj_path)
            break
        # Then a derivation from (considered - shortfall), which keeps MLB legible.
        if projected is None:
            for cons_path, short_path in _DERIVED.get(name, ()):
                cons = _as_int(_dig(enrichment, cons_path))
                short = _as_int(_dig(enrichment, short_path))
                if cons is None or short is None:
                    continue
                considered = cons
                projected = max(0, cons - short)
                source = f"{'.'.join(cons_path)} - {'.'.join(short_path)}"
                break
        # Only then the COMBINED count, which mixes games and props and is
        # therefore the least informative resolution -- used rather than losing
        # the cell entirely, and its `source_key` says so.
        if projected is None:
            for proj_path, cons_path in _CANDIDATES[name][2:]:
                value = _as_int(_dig(enrichment, proj_path))
                if value is None:
                    continue
                projected = value
                considered = _as_int(_dig(enrichment, cons_path))
                source = ".".join(proj_path) + " (COMBINED games+props)"
                break
        reason = None
        for path in _REASON_PATHS[name]:
            got = _dig(enrichment, path)
            if isinstance(got, str) and got.strip():
                reason = got.strip()
                break
        supported = None
        for path in _SUPPORTED_PATHS[name]:
            got = _dig(enrichment, path)
            if isinstance(got, bool):
                supported = got
                break
        cells[name] = Cell(name=name, projected=projected, considered=considered,
                           reason=reason, supported=supported, source_key=source)
    return SportCoverage(sport=sport, candidates=_as_int(block.get("candidates")),
                         cells=cells, active=active)


def read_shortlist(payload: Any) -> dict[str, SportCoverage]:
    """Every sport in a `/api/board/layer2-shortlist` payload, in one shape.

    Reads `active_sports` when present so a sport that is active but emits NO
    ingest block still appears -- as a row of `not_reported`, which is a finding.
    An active sport missing entirely from the matrix is the failure this avoids.
    """
    doc = payload if isinstance(payload, dict) else {}
    ingest = doc.get("per_sport_ingest") if isinstance(doc.get("per_sport_ingest"), dict) else {}
    active = doc.get("active_sports")
    names = set(ingest)
    active_set: set[str] | None = None
    if isinstance(active, list):
        active_set = {str(s) for s in active if s}
        names |= active_set
    # `active_set is None` means the payload carried no `active_sports`, so
    # nothing is known about any sport's season -- every row then passes
    # `active=None` and stays judged. Only an explicit listing makes a sport
    # provably inactive.
    return {
        s: read_sport(s, ingest.get(s),
                      active=(s in active_set) if active_set is not None else None)
        for s in sorted(names)
    }


def all_defects(matrix: dict[str, SportCoverage]) -> list[str]:
    out: list[str] = []
    for sport in sorted(matrix):
        out.extend(matrix[sport].defects)
    return out
