"""OddsAPI game lines for the NCAAF board, read back out of the shared quote log.

WHY THIS EXISTS. `syndicate/features/ncaaf/cards.py` read its market lines from
exactly one path, `data/ncaaf_source/data/cfbd_lines_{season}_wk{week}.json`.
Measured 2026-08-25: that file is written only by `scripts/fetch_ncaaf_market_lines.py`
and `scripts/fetch_cfbd_lines.py`, **both of which have zero callers** on any
service, and no such file exists in git at any SHA. So `markets` was null on
0-of-51 games, which is why candidate generation produced 0 rows and every
priced surface downstream was empty.

WHY THE QUOTE LOG RATHER THAN A NEW FILE. `HOT_ARTIFACT_PATTERNS` is written in
sport-agnostic globs, and two of them already match NCAAF:

    *_source/tracking/book_quotes/*.jsonl        <- what this module reads
    *_source/data/book_grid/book_grid_*.json     <- what Layer 1 reads

so lines routed through the quote log cross worker->web on transport that is
already allowlisted and demonstrably running, and the SAME capture feeds both
Layer 1's grid and these cards. A bespoke `ncaaf_*_lines.json` would have needed
a new allowlist entry and would have given the board a second line source that
could disagree with Layer 1's.

WHAT THIS MODULE DOES NOT DO. It does not fetch. `scripts/fetch_ncaaf_oddsapi_game_lines.py`
captures; this reads. Keeping the read pure is what lets the board stay on the
"web reads precomputed artifacts" side of the runtime split.
"""

from __future__ import annotations

import gzip
import json
import os
import statistics
import threading
import unicodedata
import re
from collections import Counter, OrderedDict
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, BinaryIO, Callable, Iterable, Mapping

from syndicate.features.ncaaf.sources import team_registry_snapshot_path

# The canonical full-game market names the shared vocabulary tags quotes with
# (`syndicate/features/shared/market_segments.py::_MARKET_BASES`). Named here so
# a change there fails this module's tests rather than silently emptying the
# board -- an unrecognised market name produces no line, which is
# indistinguishable from "no book quoted it".
MARKET_H2H = "h2h"
MARKET_SPREADS = "spreads"
MARKET_TOTALS = "totals"

# Only full-game lines belong on a game card. A first-quarter total shown as the
# game total is `learnings.md` 2026-08-21's failure exactly: a number that is
# right and labelled wrong.
SEGMENT_FULL = "full"


def fold(value: Any) -> str:
    """Aggressive fold for TEAM-NAME MATCHING only -- never for board keys.

    Transliterates diacritics before stripping punctuation, which is the whole
    point: the board's own `_normalize_text` deletes non-ASCII outright, so CFBD's
    "San Jose State" (with an acute e) folds to `san jos state` there while
    OddsAPI's unaccented spelling folds to `san jose state`. Matching on that
    would silently drop every accented school. Here the accent is normalised
    AWAY to its base letter so both spellings meet.

    Deliberately NOT used to key the returned index -- see `build_line_index`.
    """
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower().replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _csv_rows(path: Path) -> list[dict[str, str]]:
    import csv

    if not path.is_file():
        return []
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            return list(csv.DictReader(handle))
    except Exception:
        return []


# OddsAPI spellings the CFBD registry does not carry, folded key -> CFBD
# canonical name. SMALL AND VALIDATED ON PURPOSE.
#
# Every entry is checked against the registry when the map is built, and an
# entry naming a team that does not exist RAISES rather than being skipped --
# a silently-dropped alias is a team that quietly loses its line, which is the
# failure this whole module exists to remove.
#
# This is NOT `scripts/refresh_ncaaf_oddsapi.py`'s ALIASES table and must not be
# merged with it: that one targets a different vocabulary (it maps "ole miss" ->
# "mississippi", where CFBD's canonical name IS "Ole Miss"), so importing it
# here would mis-map rather than help.
#
# The list is short because it can only be verified against real OddsAPI
# responses, and this session had no egress to them. `--report` on the fetcher
# prints every unresolved name so the first live run says exactly what to add.
_ODDSAPI_NAME_SUPPLEMENT: Mapping[str, str] = {
    "umass": "Massachusetts",
    "umass minutemen": "Massachusetts",
    "southern california": "USC",
    "southern california trojans": "USC",
    "louisiana monroe": "UL Monroe",
    "louisiana monroe warhawks": "UL Monroe",
    "ulm": "UL Monroe",
    "miami ohio": "Miami (OH)",
    "miami oh": "Miami (OH)",
    "miami florida": "Miami",
    "miami fl": "Miami",

    # --------------------------------------------------------------------
    # `#558`, measured. The first live OddsAPI read that had a registry to
    # resolve against (live-odds-worker 2026-08-25T21:41:08Z) returned
    # `resolved=176 unresolved=8` over the real 111-event slate. These are
    # those 8, each looked up in the registry rather than guessed.
    #
    # Both spellings are listed for every school. `resolve_team` strips a
    # trailing MASCOT, but the mascots here are real registry mascots
    # ("Mountaineers" belongs to West Virginia too), so stripping only ever
    # yields the school form -- which is itself not a registry key in any of
    # these cases. Covering both is what makes the suffix path irrelevant.
    #
    # THE REGISTRY USES THE SHORT FORM, the feed uses the long one. Three of
    # these are FBS -- main-board games that would otherwise show an empty
    # market block, which on the board reads identically to "no book quoted
    # it".
    "appalachian state": "App State",                    # FBS
    "appalachian state mountaineers": "App State",
    "southern mississippi": "Southern Miss",             # FBS
    "southern mississippi golden eagles": "Southern Miss",
    "southeastern louisiana": "SE Louisiana",
    "southeastern louisiana lions": "SE Louisiana",
    "citadel": "The Citadel",
    "citadel bulldogs": "The Citadel",
    "nicholls state": "Nicholls",
    "nicholls state colonels": "Nicholls",
    # Read off 24 paper orders on LSU v McNeese State (2026-10-03), whose
    # `away_team` is OddsAPI's "McNeese State Cowboys"; the registry's school
    # is "McNeese" (FCS, Southland). Lane paper-evicted-grading, #744.
    "mcneese state": "McNeese",
    "mcneese state cowboys": "McNeese",

    # THE SCHOOL WAS RENAMED and the feed still carries the old name. The
    # registry is current; OddsAPI is not.
    "houston baptist": "Houston Christian",              # renamed 2022
    "houston baptist huskies": "Houston Christian",
    "sam houston state": "Sam Houston",                  # FBS, renamed 2021
    "sam houston state bearkats": "Sam Houston",

    # A JUDGEMENT CALL, STATED AS ONE. The registry carries TWO Albanys --
    # `UAlbany` (FCS, Great Danes) and `Albany State GA` (Division II) -- and
    # the feed sends the bare word. A Division II school does not appear on a
    # book's slate, so this is UAlbany; but that is an inference from the
    # feed's composition, not something the name itself says. Written here as
    # a hand-verified entry rather than left to the alias generator, which
    # would have had no basis to choose and correctly refuses ambiguity.
    "albany": "UAlbany",
}


@lru_cache(maxsize=1)
def fbs_canonical_names() -> frozenset[str]:
    """The canonical names of the FBS teams only, from the same snapshot.

    The registry carries all four divisions (fbs 138, fcs 128, ii 171, iii 247
    on the 2026-08-26 snapshot) and the non-FBS rows are what make a bare code
    dangerous: `MAS` is UMass Dartmouth's REAL abbreviation and collides with
    the synthetic three-letter abbr a board chip builds for Massachusetts.

    Exposed so a consumer can restrict itself to the subdivision the board
    actually cards, without re-reading or re-parsing the CSV.
    """
    return frozenset(
        str(row.get("canonical_team_name") or "").strip()
        for row in _csv_rows(team_registry_snapshot_path())
        if (row.get("subdivision") or "").strip().lower() == "fbs"
        and str(row.get("canonical_team_name") or "").strip()
    )


def iter_team_alias_offers() -> Iterable[tuple[str, str, bool]]:
    """Every `(raw alias, canonical team, is_supplement)` this module's
    vocabulary is built from -- BEFORE folding and BEFORE the collision pass.

    ONE ENUMERATION, MORE THAN ONE NORMALISER. `_alias_map` below folds these
    with `fold()` (punctuation deleted, `&` -> ` and `);
    `team_aliases._ncaaf_alias_to_name` needs the SAME vocabulary keyed with
    `team_aliases.normalize`, which keeps `&` and parentheses. Those two
    disagree on "Texas A&M" and "Miami (OH)", so a consumer cannot re-key this
    module's folded output -- it needs the raw strings.

    Yielding them rather than letting the second consumer re-enumerate the CSV
    columns is the point: `team_aliases`' own header says a second
    hand-maintained list is "the drift this module exists to prevent", and two
    resolvers that disagree about one club is a silent mismatch nobody sees
    (`#218`). A school added to the registry, or an entry added to
    `_ODDSAPI_NAME_SUPPLEMENT`, reaches both consumers or neither.

    `is_supplement` is carried because the two classes are treated differently
    and must stay distinguishable: registry offers are subject to the collision
    pass, supplement entries are hand-verified answers to names the registry
    genuinely does not carry and OVERRIDE it.
    """
    for row in _csv_rows(team_registry_snapshot_path()):
        canonical = str(row.get("canonical_team_name") or "").strip()
        if not canonical:
            continue
        school = str(row.get("school_name") or "").strip()
        mascot = str(row.get("mascot_name") or "").strip()

        # The high-confidence key first: OddsAPI's own "<School> <Mascot>".
        if school and mascot:
            yield (f"{school} {mascot}", canonical, False)
        yield (canonical, canonical, False)
        yield (school, canonical, False)

        # "Boise St." as well as "Boise State". Measured 2026-08-25 across all
        # 138 FBS teams: the full spellings resolve 138/138, but if the feed
        # abbreviates, **30 of 138 silently lose their line** -- and a team with
        # no line is indistinguishable on the board from a team no book quoted.
        # Cheap to cover, and covering it costs nothing if the feed never
        # abbreviates.
        #
        # ADDS AN ALIAS, never rewrites the lookup string, and that distinction
        # is load-bearing: the registry holds 11 schools whose name genuinely
        # STARTS with "St."/"Saint" (St. Anselm, Saint John's (MN), ...). A
        # transform mapping the token "st" -> "state" on input would mangle
        # every one of them. Generating "Boise St." as an extra key for a team
        # already named "Boise State" cannot touch them, and any key two
        # canonical teams both claim is dropped by the collision pass.
        if " State" in school:
            abbreviated = school.replace(" State", " St.")
            yield (abbreviated, canonical, False)
            if mascot:
                yield (f"{abbreviated} {mascot}", canonical, False)
        yield (str(row.get("display_name") or ""), canonical, False)
        # `aliases` is pipe-separated and INCLUDES the bare mascot, which is why
        # every alias goes through the collision check rather than being trusted.
        for alias in str(row.get("aliases") or "").split("|"):
            yield (alias, canonical, False)
        # Abbreviations collide hard across divisions (many "ACU"s); the
        # collision pass is what makes offering them safe.
        yield (str(row.get("abbreviation") or ""), canonical, False)

    for alias, canonical in _ODDSAPI_NAME_SUPPLEMENT.items():
        yield (alias, canonical, True)


@lru_cache(maxsize=1)
def _alias_map() -> dict[str, str]:
    """folded alias -> CFBD canonical team name.

    AMBIGUOUS ALIASES ARE DROPPED, NOT RESOLVED. The registry carries 684 teams
    across all divisions and `state.md` records the specific hazard: roughly 680
    schools share mascots, so "Wildcats" or "Bulldogs" identifies nobody. Any
    folded string that two different canonical teams both claim is removed from
    the map entirely, so a collision yields "unresolved" (a visible gap) rather
    than a confident wrong join (an invisible one).

    A BARE MASCOT IS NEVER A KEY. Mascots enter only as the tail of
    "<school> <mascot>", which is the shape OddsAPI actually sends
    ("TCU Horned Frogs"), and as a suffix `resolve_team` may strip.
    """
    mapping: dict[str, str] = {}
    collisions: set[str] = set()

    def offer(alias: Any, canonical: str) -> None:
        key = fold(alias)
        if not key or key.isdigit():
            return
        existing = mapping.get(key)
        if existing is None:
            mapping[key] = canonical
        elif existing != canonical:
            collisions.add(key)

    # The vocabulary itself lives in `iter_team_alias_offers` so that
    # `team_aliases` can key the SAME offers with its own normaliser rather
    # than maintain a second list. The supplement is skipped here and applied
    # below, after the collision pass, exactly as it always was.
    for alias, canonical, is_supplement in iter_team_alias_offers():
        if not is_supplement:
            offer(alias, canonical)

    for key in collisions:
        mapping.pop(key, None)

    # The supplement is applied AFTER the collision pass and overrides it: these
    # are hand-verified answers to names the registry genuinely does not carry,
    # so they must survive a mascot collision rather than be dropped by it.
    known = {row for row in mapping.values()}
    if not known:
        # `#558`. THE GUARD BELOW USED TO BE SKIPPED BY EXACTLY THE CONDITION
        # THAT BREAKS IT. `if known:` meant a POPULATED registry was validated
        # and an ABSENT one was waved through, returning {} -- which resolves
        # nothing while looking identical to "the feed sent names we don't
        # carry". Measured on live-odds-worker 2026-08-25T21:03:35Z:
        # `resolved=0 unresolved=184`, every team, reported at exit 0.
        #
        # Audible, not fatal: `cards.py` and `game_projections.py` call this on
        # the WEB service to build the board, and raising there would turn a
        # missing input into a dead page. Degrading to "no lines" is right for
        # them. The FETCHER refuses outright instead -- see
        # `registry_status()` and `fetch_ncaaf_oddsapi_game_lines.py`, which is
        # the caller that would otherwise spend a credit and write nothing.
        print(
            "[ncaaf_odds] TEAM_REGISTRY_EMPTY path="
            f"{team_registry_snapshot_path()} -- every team name will fail to "
            "resolve. This file is git-tracked and reaches web via "
            "bootstrap_data_root; a WORKER needs it pulled (it is allowlisted "
            "in HOT_ARTIFACT_PATTERNS).",
            flush=True,
        )
    if known:
        for alias, canonical in _ODDSAPI_NAME_SUPPLEMENT.items():
            if canonical not in known:
                raise ValueError(
                    "_ODDSAPI_NAME_SUPPLEMENT maps "
                    f"{alias!r} -> {canonical!r}, which is not a canonical team in "
                    f"{team_registry_snapshot_path()}. Fix the entry rather than "
                    "removing this check: a silently-skipped alias is a team that "
                    "quietly loses its market line."
                )
            mapping[fold(alias)] = canonical
    return mapping


def registry_status() -> dict[str, Any]:
    """Is the team registry actually on THIS process's disk?

    `#558`. Exists because the answer differs per SERVICE and nothing said so:
    the CSV is git-tracked, so `bootstrap_data_root` puts it on web's disk,
    while live-odds-worker never runs that bootstrap and had never been sent
    the file. `_csv_rows()` returns [] for a missing path, so the resolver
    reported 184 unresolved names at exit 0 rather than one absent input.

    Callable WITHOUT spending an API credit, which is the point -- the fetcher
    checks this before it fetches.
    """
    path = team_registry_snapshot_path()
    rows = _csv_rows(path)
    teams = {
        str(row.get("canonical_team_name") or "").strip()
        for row in rows
        if str(row.get("canonical_team_name") or "").strip()
    }
    return {
        "path": str(path),
        "exists": path.is_file(),
        "rows": len(rows),
        "teams": len(teams),
        "ok": bool(teams),
    }


@lru_cache(maxsize=1)
def _mascot_tails() -> tuple[str, ...]:
    """Folded mascot strings, longest first, for suffix stripping only."""
    seen: set[str] = set()
    for row in _csv_rows(team_registry_snapshot_path()):
        mascot = fold(row.get("mascot_name"))
        if mascot:
            seen.add(mascot)
    return tuple(sorted(seen, key=lambda item: (-len(item.split()), item)))


def resolve_team(name: Any) -> str | None:
    """An OddsAPI team name -> the CFBD canonical name the board joins on.

    Returns None rather than a guess. An unresolved team costs that game its
    line; a wrong one puts another game's price on this card.
    """
    key = fold(name)
    if not key:
        return None
    mapping = _alias_map()
    hit = mapping.get(key)
    if hit:
        return hit
    # "<school> <mascot>" where the pair was never registered together: strip a
    # known mascot tail and retry on the school alone. Longest tail first so
    # "Rainbow Warriors" is tried before "Warriors".
    for tail in _mascot_tails():
        suffix = " " + tail
        if key.endswith(suffix):
            stem = key[: -len(suffix)].strip()
            if stem:
                hit = mapping.get(stem)
                if hit:
                    return hit
    return None


def _latest_key(row: Mapping[str, Any]) -> tuple[str, str, str, str, str] | None:
    """(home, away, market, selection, book) for a full-game line row, else None."""
    if str(row.get("kind") or "game") != "game":
        return None
    if str(row.get("segment") or SEGMENT_FULL) != SEGMENT_FULL:
        return None
    return (
        str(row.get("home_team") or ""),
        str(row.get("away_team") or ""),
        str(row.get("market") or ""),
        str(row.get("selection") or ""),
        str(row.get("bookmaker") or ""),
    )


def _latest_per_key(rows: Iterable[Mapping[str, Any]]) -> dict[tuple, tuple[Any, Any]]:
    """Collapse the append log to one (line, price) per (game, market, selection, book).

    The log is append-only and ordered, so the LAST occurrence is current. That
    is also why a line that stopped being quoted keeps its last value here --
    freshness is the caller's problem, and `line_index_freshness` reports it
    rather than this function silently dropping stale rows.

    Only `line` and `price` are kept: they are the only fields
    `_line_index_from_latest` reads off a row, and a whole row per key is more
    than the per-shard cache below can afford to hold.
    """
    latest: dict[tuple, tuple[Any, Any]] = {}
    for row in rows:
        key = _latest_key(row)
        if key is not None:
            latest[key] = (row.get("line"), row.get("price"))
    return latest


# ---------------------------------------------------------------------------
# READING THE SHARDS: STREAMED, AND ONLY THE APPENDED BYTES ONCE A SHARD IS SEEN
# ---------------------------------------------------------------------------
#
# [2026-11-27, lane ncaaf-cards-build-cost] Measured on the fleet (week 13; the
# 11-27 and 11-28 shards, 174 MB and 382,883 lines): the reader this replaced put
# every row of the week into ONE list and collapsed it afterwards. That cost
# +940-984 MB of peak RSS and 2.5-2.9 s on EVERY board build, cold or warm -- most
# of a warm `/ncaaf/api/cards`, and enough to push a web worker past the memory
# recycler (~625-647 MB anon) on nearly every NCAAF cards, picks or market-board
# read.
#
# Two changes, and the index they produce is the same:
#   1. Rows are collapsed AS THEY ARE READ, so a shard never exists as a list.
#   2. A plain shard is append-only (`append_book_quotes` opens it "a"; the
#      sanitize pass rewrites it through `os.replace`, which is a new inode). So
#      the collapse of the bytes already read is kept per process, and a later
#      read parses only what was appended. Anything that says the file is not the
#      one read before -- another inode, a shorter size, different bytes at the
#      head or just before the read offset -- re-reads it whole.
#
# WHAT "THE SAME" COVERS, case by case against the old text-mode reader
# (`open(path, "rt", encoding="utf-8")`, one `json.loads` per stripped line):
#   - universal newlines: "\r\n" and a lone "\r" end a line, as text mode does;
#   - strict UTF-8: an undecodable byte anywhere drops the WHOLE date, as the old
#     `except Exception: return []` did. Nothing is cached on that path, so the
#     date stays dropped for as long as the bytes are there;
#   - a last line with no newline is parsed, as before, but never cached: the next
#     read parses it again, whether or not it has been completed since;
#   - append order, the LAST quote per key winning, the key keeping the position
#     of its FIRST occurrence -- what plain `dict` assignment did before, across
#     dates as well as within one.

#: Bytes compared at the head of a shard and just before the cached offset.
_SHARD_ANCHOR_BYTES = 65536

#: Shards held per process. A week's slate spans at most ~10 dates (2026 week 1).
_SHARD_CACHE_LIMIT = 16


@dataclass(frozen=True)
class _ShardCollapse:
    """What one process has collapsed of one shard. Never mutated once stored."""

    #: (st_dev, st_ino) for a plain shard; for a `.gz`, also (st_size, st_mtime_ns).
    identity: tuple[int, ...]
    #: Bytes collapsed into `latest`. Plain: always just past a b"\n" (or 0).
    offset: int
    #: The first min(offset, _SHARD_ANCHOR_BYTES) bytes of the file (plain only).
    head: bytes
    #: The bytes ending at `offset`, at most _SHARD_ANCHOR_BYTES (plain only).
    tail: bytes
    #: The collapse of bytes [0, offset). Shared by readers: never written to.
    latest: dict


_SHARD_COLLAPSES: "OrderedDict[str, _ShardCollapse]" = OrderedDict()
_SHARD_COLLAPSES_LOCK = threading.Lock()


def clear_shard_cache() -> None:
    """Forget every collapsed shard (tests; and a way to force full re-reads)."""
    with _SHARD_COLLAPSES_LOCK:
        _SHARD_COLLAPSES.clear()


def _cached_collapse(key: str) -> _ShardCollapse | None:
    with _SHARD_COLLAPSES_LOCK:
        state = _SHARD_COLLAPSES.get(key)
        if state is not None:
            _SHARD_COLLAPSES.move_to_end(key)
        return state


def _store_collapse(key: str, state: _ShardCollapse) -> None:
    with _SHARD_COLLAPSES_LOCK:
        _SHARD_COLLAPSES[key] = state
        _SHARD_COLLAPSES.move_to_end(key)
        while len(_SHARD_COLLAPSES) > _SHARD_CACHE_LIMIT:
            _SHARD_COLLAPSES.popitem(last=False)


def _collapse_piece(raw: bytes, latest: dict) -> None:
    """Collapse one b"\\n"-terminated piece of a shard (or its unterminated tail).

    Split the way text mode splits it -- "\\r\\n" and a lone "\\r" both end a line --
    then decoded strictly. A decode error is RAISED: the caller drops the date.
    """
    if b"\r" in raw:
        pieces = raw.replace(b"\r\n", b"\n").replace(b"\r", b"\n").split(b"\n")
    else:
        pieces = (raw,)
    for piece in pieces:
        line = piece.decode("utf-8").strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except Exception:
            continue
        if isinstance(row, dict):
            key = _latest_key(row)
            if key is not None:
                latest[key] = (row.get("line"), row.get("price"))


def _collapse_stream(handle: BinaryIO, latest: dict) -> tuple[int, bytes]:
    """Collapse every b"\\n"-terminated line left in `handle` into `latest`.

    Returns (bytes collapsed, the unterminated tail -- b"" when the stream ends on
    a newline). The tail is NOT collapsed: the caller decides where it goes.
    """
    consumed = 0
    for raw in handle:
        if not raw.endswith(b"\n"):
            return consumed, raw
        consumed += len(raw)
        _collapse_piece(raw, latest)
    return consumed, b""


def _anchors_hold(handle: BinaryIO, state: _ShardCollapse) -> bool:
    handle.seek(0)
    if handle.read(len(state.head)) != state.head:
        return False
    handle.seek(state.offset - len(state.tail))
    return handle.read(len(state.tail)) == state.tail


def _collapse_plain_shard(path: Path, stats: dict[str, int]) -> dict:
    """The collapse of a plain shard, parsing only what was appended since the last read."""
    key = str(path)
    prior = _cached_collapse(key)
    with open(path, "rb") as handle:
        info = os.fstat(handle.fileno())
        identity = (int(info.st_dev), int(info.st_ino))
        start = 0
        latest: dict = {}
        if (
            prior is not None
            and prior.identity == identity
            and prior.offset <= int(info.st_size)
            and _anchors_hold(handle, prior)
        ):
            start = prior.offset
            latest = dict(prior.latest)
        else:
            stats["full_reads"] += 1
        handle.seek(start)
        consumed, tail = _collapse_stream(handle, latest)
        offset = start + consumed
        handle.seek(0)
        head = handle.read(min(offset, _SHARD_ANCHOR_BYTES))
        anchor_start = max(0, offset - _SHARD_ANCHOR_BYTES)
        handle.seek(anchor_start)
        anchor = handle.read(offset - anchor_start)
    stats["reused_bytes"] += start
    stats["parsed_bytes"] += consumed + len(tail)
    _store_collapse(key, _ShardCollapse(identity, offset, head, anchor, latest))
    if not tail:
        return latest
    view = dict(latest)
    _collapse_piece(tail, view)
    return view


def _collapse_gz_shard(path: Path, stats: dict[str, int]) -> dict:
    """The collapse of a compacted shard, kept while its (inode, size, mtime) hold.

    A `.gz` is written whole and swapped in by `os.replace`, so it never grows:
    either the same file is read again or it is read from scratch.
    """
    key = str(path)
    info = path.stat()
    identity = (int(info.st_dev), int(info.st_ino), int(info.st_size), int(info.st_mtime_ns))
    prior = _cached_collapse(key)
    if prior is not None and prior.identity == identity:
        stats["reused_bytes"] += prior.offset
        return prior.latest
    stats["full_reads"] += 1
    latest: dict = {}
    with gzip.open(path, "rb") as handle:
        _consumed, tail = _collapse_stream(handle, latest)
        if tail:
            _collapse_piece(tail, latest)
    stats["parsed_bytes"] += int(info.st_size)
    _store_collapse(key, _ShardCollapse(identity, int(info.st_size), b"", b"", latest))
    return latest


def _latest_for_date(sport: str, date_str: str, stats: dict[str, int]) -> dict:
    """One date's shard collapsed to (line, price) per key. Never raises.

    {} when the date has no shard, or when reading it failed anywhere -- the old
    reader's "a partial read is no read" rule, kept.
    """
    try:
        from syndicate.features.shared.odds_book_quotes import resolve_book_quotes_path

        path = resolve_book_quotes_path(sport, date_str)
    except Exception:
        return {}
    if not path or not Path(path).is_file():
        return {}
    stats["shards"] += 1
    try:
        if str(path).endswith(".gz"):
            return _collapse_gz_shard(Path(path), stats)
        return _collapse_plain_shard(Path(path), stats)
    except Exception:
        stats["failed"] += 1
        return {}


def _as_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _selection_side(selection: Any, *, home_raw: str, away_raw: str) -> str | None:
    """Which side of the market a quote row is for: home / away / over / under.

    `quote_rows_from_oddsapi_events` ALREADY resolves OddsAPI's outcome names to
    these side tokens, so the canonical form is checked first. Measured while
    building this: assuming the row still carried the raw team name silently
    dropped every spread and moneyline while totals -- whose outcome name IS
    literally "Over" -- kept working, which looked like a books-coverage gap
    rather than a bug.

    The team-name branch stays as a fallback because the log is shared and a
    future writer may not go through that helper.
    """
    text = fold(selection)
    if not text:
        return None
    if text in ("home", "away", "over", "under"):
        return text
    if text == fold(home_raw):
        return "home"
    if text == fold(away_raw):
        return "away"
    if text.startswith("over"):
        return "over"
    if text.startswith("under"):
        return "under"
    return None


def build_line_index(
    rows: Iterable[Mapping[str, Any]],
    *,
    key_fn: Callable[[Any], str],
) -> dict[tuple[str, str], dict[str, Any]]:
    """Quote rows -> the index shape `_smartsim2_standalone_rows` already joins on.

    `key_fn` IS PASSED IN, not imported. It must be the board's own
    `_normalize_text`, because the projection index is keyed with that exact
    function and a second copy here would be free to drift. Passing it also
    breaks what would otherwise be an import cycle.

    Aggregation deliberately MIRRORS the CFBD reader this supplements, so the
    two sources cannot produce differently-shaped numbers for the same game:
    mean spread across books (negated -- see below), mean total, and the first
    book quoting BOTH moneylines rather than an average, since American odds do
    not average meaningfully.

    THE NEGATION IS THE EASY THING TO GET BACKWARDS. `market_margin` is a HOME
    MARGIN (positive = home favoured); a book's home spread is negative when the
    home side is favoured. `state.md` records the identical trap costing a whole
    analysis in NFL: using nflverse's `spread_line` negated inverted every
    conclusion while producing entirely plausible numbers.
    """
    return _line_index_from_latest(_latest_per_key(rows), key_fn=key_fn)


def _line_index_from_latest(
    latest: Mapping[tuple, tuple[Any, Any]],
    *,
    key_fn: Callable[[Any], str],
) -> dict[tuple[str, str], dict[str, Any]]:
    """`build_line_index` from an already-collapsed (line, price) per key.

    `resolve_team` and `_selection_side` are pure for one call (the alias map is
    `lru_cache`d), and a slate repeats the same few hundred names across ~10k
    keys, so each distinct name is resolved once (measured 11-27: 21,748
    `resolve_team` calls for one week's index).
    """
    resolved: dict[Any, str | None] = {}
    sides: dict[tuple[Any, str, str], str | None] = {}

    def _resolve(name: str) -> str | None:
        if name not in resolved:
            resolved[name] = resolve_team(name)
        return resolved[name]

    per_game: dict[tuple[str, str], dict[str, Any]] = {}
    for (home_raw, away_raw, market, selection, book), (raw_line, price) in latest.items():
        home = _resolve(home_raw)
        away = _resolve(away_raw)
        if not home or not away:
            continue
        key = (key_fn(home), key_fn(away))
        bucket = per_game.setdefault(
            key,
            {"spreads": {}, "totals": [], "h2h": {}, "home_name": home, "away_name": away},
        )
        line = _as_float(raw_line)
        side_key = (selection, home_raw, away_raw)
        if side_key not in sides:
            sides[side_key] = _selection_side(selection, home_raw=home_raw, away_raw=away_raw)
        side = sides[side_key]

        if market == MARKET_SPREADS and line is not None:
            # Only the HOME side's line; the away side is its mirror and
            # averaging the pair would cancel to zero.
            if side == "home":
                bucket["spreads"][book] = line
        elif market == MARKET_TOTALS and line is not None:
            # Over only, for the same reason -- over and under quote the SAME
            # number, so counting both would just double the sample.
            if side == "over":
                bucket["totals"].append(line)
        elif market == MARKET_H2H and price is not None:
            if side in ("home", "away"):
                bucket["h2h"].setdefault(book, {})[side] = price

    index: dict[tuple[str, str], dict[str, Any]] = {}
    for key, bucket in per_game.items():
        spreads = list(bucket["spreads"].values())
        totals = list(bucket["totals"])
        home_ml = away_ml = None
        for _book, prices in bucket["h2h"].items():
            if prices.get("home") is not None and prices.get("away") is not None:
                home_ml = prices.get("home")
                away_ml = prices.get("away")
                break
        index[key] = {
            "market_margin": (-statistics.mean(spreads)) if spreads else None,
            "market_total": statistics.mean(totals) if totals else None,
            "home_moneyline": home_ml,
            "away_moneyline": away_ml,
            "book_count": len(set(bucket["spreads"]) | set(bucket["h2h"])),
            "source": "oddsapi_book_quotes",
        }
    return index


def load_week_line_index(
    season: int,
    week: int,
    *,
    key_fn: Callable[[Any], str],
    kickoff_dates: Iterable[str],
) -> dict[tuple[str, str], dict[str, Any]]:
    """The week's line index, read from the quote shards its games kick off on.

    `kickoff_dates` is supplied by the caller rather than derived here because
    the board already holds the schedule -- and because NCAAF "week 1" spans ten
    calendar days (2026: 08-29 to 09-07), so guessing a date window from the week
    number would silently drop most of the slate.

    Each date's shard is collapsed on its own and merged in date order, which is
    the same as collapsing the dates' rows end to end: a key keeps the position it
    first appeared at and takes the last quote. See "READING THE SHARDS" above.
    """
    stats = {"shards": 0, "full_reads": 0, "parsed_bytes": 0, "reused_bytes": 0, "failed": 0}
    latest: dict[tuple, tuple[Any, Any]] = {}
    dates = list(dict.fromkeys(str(d).strip() for d in kickoff_dates if d))
    for date_str in dates:
        for key, value in _latest_for_date("ncaaf", date_str, stats).items():
            latest[key] = value
    if stats["shards"]:
        # Reads back which path ran: `full_reads=0` with `reused_bytes` > 0 is the
        # append-only path; `failed` counts dates dropped whole. print/flush --
        # `logger.info` never reached a role log.
        print(
            f"[ncaaf_odds] LINE_INDEX_READ season={season} week={week} dates={len(dates)} "
            f"shards={stats['shards']} full_reads={stats['full_reads']} failed={stats['failed']} "
            f"parsed_bytes={stats['parsed_bytes']} reused_bytes={stats['reused_bytes']} keys={len(latest)}",
            flush=True,
        )
    if not latest:
        return {}
    return _line_index_from_latest(latest, key_fn=key_fn)


def resolution_report(names: Iterable[Any]) -> dict[str, Any]:
    """How many OddsAPI names resolved, and which did not.

    Exists so the join is verified as a COUNT over the real slate rather than
    spot-checked. `scripts/fetch_ncaaf_oddsapi_game_lines.py --report` prints
    this, and an unresolved name is the signal that the registry needs an alias,
    not that the fetch failed.
    """
    seen = Counter(str(n) for n in names if str(n or "").strip())
    resolved: dict[str, str] = {}
    unresolved: list[str] = []
    for name in seen:
        hit = resolve_team(name)
        if hit:
            resolved[name] = hit
        else:
            unresolved.append(name)
    return {
        "total": len(seen),
        "resolved": len(resolved),
        "unresolved": sorted(unresolved),
        "mapping": resolved,
    }
