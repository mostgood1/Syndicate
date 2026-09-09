"""NCAAF compact game cards must be able to find their scoreboard chip.

THE DEFECT THIS PINS, measured on the served payload 2026-09-03. Every sport's
Games-strip card rendered two `TRICODE score` rows except NCAAF, which rendered
"UMass Minutemen @ Rutgers Scarlet Knights" and "11 opportunities". The chip was
present and carried abbreviations; the CARD could not find it. `chipForGame`
(intelligence.html) has four indexes and NCAAF missed all four:

    chip  game_key "1_Massachusetts_Rutgers"  matchup "MAS @ RUT"
          away {abbr "MAS", name "Massachusetts", key None}
    row   event_id "fc7e0d9b..."              matchup "UMass Minutemen @ ..."
          away_key None

The canonical-key index is the one designed for exactly this -- two feeds
spelling one club differently -- and it was empty on BOTH sides because
`canonical_team("ncaaf", ...)` is None for everything.

WHY THE FIX WAS NOT "populate `_alias_map('ncaaf')`" -- AND WHAT CHANGED. That
was built, measured and reverted on 2026-08-29 (`.syndicate/handoff_2026-08-29_
ncaaf_umass_alias_gap.md`): it makes `teams_match` map-authoritative, and
`venue_quote_adapters.event_game_token` depends on NCAAF not canonicalising
(`#603`). On 2026-09-09 the map landed anyway, from a different source and
behind that revert's own two gates -- see `team_aliases._ncaaf_alias_to_name`
and `tests/test_ncaaf_team_aliases.py`. `#603` is held by `game_token` refusing
NCAAF explicitly rather than by the map being empty.
`test_the_2026_08_29_REVERTS_HAZARDS_STAY_REFUSED` is the control now.

`chip_join_key` is still not redundant: the map is FBS-only, while
`resolve_team` reads all four divisions, so an FCS visitor on a real slate
resolves here and nowhere else.

DATA-FREE ON PURPOSE. The session worktree excludes `data/`, and a test that
silently degraded to "registry absent -> nothing resolves -> None" would pass
identically with and without the fix. Every test here points the resolver at a
registry it writes itself, and `test_the_registry_stub_actually_resolves` is the
guard against the whole file passing vacuously.
"""

from __future__ import annotations

import pytest

from syndicate.features.ncaaf import oddsapi_lines
from syndicate.features.shared import team_aliases
from syndicate.features.shared.game_chip_scoreboard import build_game_chip


_REGISTRY_HEADER = (
    "team_id,canonical_team_name,abbreviation,conference,subdivision,aliases,"
    "display_name,conference_short_name,school_name,mascot_name,source_system,"
    "source_snapshot_date\n"
)

# Real rows copied from `ncaaf_team_registry_snapshot.csv`. They carry the two
# shapes that matter: a school whose registry name is NOT what the odds feed
# sends ("Massachusetts" vs "UMass Minutemen" -- reachable only through the
# resolver's hand-verified supplement), and schools where the feed simply
# appends the mascot ("Rutgers Scarlet Knights").
#
# `UMass Dartmouth` is here deliberately. The 2026-08-29 handoff's whole hazard
# was `MAS` resolving to it; the snapshot now abbreviates it `MDAR`, and
# `test_ncaaf_alias_map_stays_empty` asserts the miss stays a miss.
_REAL_ROWS: tuple[tuple[str, str, str, str, str], ...] = (
    # (team_id, canonical, abbr, mascot, subdivision)
    ("113", "Massachusetts", "MASS", "Minutemen", "FBS"),
    ("164", "Rutgers", "RUTG", "Scarlet Knights", "FBS"),
    ("379", "UMass Dartmouth", "MDAR", "Corsairs", "III"),
    ("142", "Missouri", "MIZ", "Tigers", "FBS"),
    ("2029", "Arkansas-Pine Bluff", "UAPB", "Golden Lions", "FCS"),
    ("70", "Idaho", "IDHO", "Vandals", "FBS"),
)


def _registry_csv() -> str:
    """A registry stub carrying every school the resolver's supplement names.

    `_alias_map` RAISES on a supplement entry whose target is not a canonical
    team in the registry -- deliberately, so a silently-skipped alias cannot
    happen. A stub holding only the six schools this test cares about would
    therefore blow up rather than resolve, so the supplement's own targets are
    generated in. Reading them from the module rather than typing them out is
    what keeps this test from breaking every time an alias is added.
    """
    rows = list(_REAL_ROWS)
    known = {canonical for _, canonical, _, _, _ in rows}
    for index, canonical in enumerate(sorted(set(oddsapi_lines._ODDSAPI_NAME_SUPPLEMENT.values()))):
        if canonical in known:
            continue
        rows.append((f"90{index:03d}", canonical, f"Z{index:03d}", f"Mascot{index:03d}", "FBS"))

    lines = [_REGISTRY_HEADER]
    for team_id, canonical, abbr, mascot, subdivision in rows:
        aliases = "|".join(sorted({canonical.lower(), abbr.lower(), mascot.lower()}))
        lines.append(
            f'{team_id},"{canonical}",{abbr},TestConf,{subdivision},"{aliases}",'
            f'"{canonical}",,"{canonical}","{mascot}",cfbd,2026-07-21\n'
        )
    return "".join(lines)


def _clear_ncaaf_registry_caches() -> None:
    """EVERY cache downstream of the registry path, in one place.

    THIS LIST WAS INCOMPLETE AND THE GAP WAS INVISIBLE. It cleared only
    `oddsapi_lines`' two caches, so `team_aliases._ncaaf_alias_to_name` (added
    2026-09-09, `lru_cache(maxsize=1)`) and `oddsapi_lines.fbs_canonical_names`
    kept this file's SIX-SCHOOL STUB for the rest of the pytest process. Every
    NCAAF test that ran after this file then asked a stub registry and got
    `canonical_team("ncaaf", "South Florida Bulls") -> None` -- which reads
    exactly like "the map does not cover it".

    It could not be seen before, because `_alias_map("ncaaf")` returned `{}`
    with or without the stub. Adding a real map is what turned a dormant leak
    into a wrong answer, so the clear list is now derived from the caches that
    exist rather than from the ones someone remembered.
    """
    for module, names in (
        (oddsapi_lines, ("_alias_map", "_mascot_tails", "fbs_canonical_names")),
        (team_aliases, ("_ncaaf_alias_to_name", "_nickname_alias_map", "unambiguous_club_tokens")),
    ):
        for name in names:
            cached = getattr(module, name, None)
            clear = getattr(cached, "cache_clear", None)
            if clear is not None:
                clear()


@pytest.fixture(autouse=True)
def _ncaaf_registry_caches_are_never_left_dirty():
    """AUTOUSE, so a test in this file that forgets the fixture cannot leak
    either. The stub is process-global state once cached; nothing about the
    fixture's own scope contains it."""
    _clear_ncaaf_registry_caches()
    try:
        yield
    finally:
        _clear_ncaaf_registry_caches()


@pytest.fixture
def ncaaf_registry(tmp_path, monkeypatch):
    """Point the NCAAF resolver at a registry this test wrote."""
    path = tmp_path / "ncaaf_team_registry_snapshot.csv"
    path.write_text(_registry_csv(), encoding="utf-8")
    monkeypatch.setattr(oddsapi_lines, "team_registry_snapshot_path", lambda: path)
    _clear_ncaaf_registry_caches()
    try:
        yield path
    finally:
        _clear_ncaaf_registry_caches()


def test_the_registry_stub_actually_resolves(ncaaf_registry):
    """Guards every other test in this file against passing vacuously."""
    assert oddsapi_lines.resolve_team("UMass Minutemen") == "Massachusetts"
    assert oddsapi_lines.resolve_team("Rutgers Scarlet Knights") == "Rutgers"


def test_chip_and_board_row_resolve_to_one_key(ncaaf_registry):
    """The two halves of the join, in the exact vocabularies production sends.

    The CHIP carries the CFBD short name ("Massachusetts"); the board ROW
    carries the odds feed's "<School> <Mascot>" ("UMass Minutemen"). Neither
    spelling reaches the other by any string rule -- that is the whole finding.
    """
    chip_side = team_aliases.chip_join_key("ncaaf", "Massachusetts")
    row_side = team_aliases.chip_join_key("ncaaf", "UMass Minutemen")
    assert chip_side is not None
    assert chip_side == row_side

    # The other sides of the two games in the reported screenshot.
    for chip_name, row_name in (
        ("Rutgers", "Rutgers Scarlet Knights"),
        ("Missouri", "Missouri Tigers"),
        ("Arkansas-Pine Bluff", "Arkansas Pine Bluff Golden Lions"),
    ):
        resolved = team_aliases.chip_join_key("ncaaf", chip_name)
        assert resolved is not None, chip_name
        assert resolved == team_aliases.chip_join_key("ncaaf", row_name), row_name


def test_built_ncaaf_chip_carries_a_join_key(ncaaf_registry):
    """END OF THE PIPE, not the helper.

    `_side_key` is the only thing that puts `key` on a chip, and the browser's
    canonical index is built from `chip.away.key`/`chip.home.key`. A helper that
    resolves while the chip still ships `key: null` is the inert-fix shape this
    repo keeps catching, so the assertion is on the CHIP.
    """
    chip = build_game_chip(
        "ncaaf",
        {
            "game_id": "1_Massachusetts_Rutgers",
            "away": {"abbr": "MAS", "name": "Massachusetts"},
            "home": {"abbr": "RUT", "name": "Rutgers"},
            "startTime": "2026-09-03T22:00:00Z",
        },
    )
    assert chip["away"]["key"] and chip["home"]["key"]
    assert chip["away"]["key"] == team_aliases.chip_join_key("ncaaf", "UMass Minutemen")
    assert chip["home"]["key"] == team_aliases.chip_join_key(
        "ncaaf", "Rutgers Scarlet Knights"
    )
    # The abbreviations were never the missing half -- pinned so a future
    # "fix" that invents tri-codes client-side is visibly unnecessary.
    assert chip["away"]["abbr"] == "MAS"
    assert chip["home"]["abbr"] == "RUT"


def test_the_2026_08_29_REVERTS_HAZARDS_STAY_REFUSED(ncaaf_registry):
    """THE CONTROL FOR THE 2026-08-29 REVERT -- REWRITTEN, NOT DELETED.

    This asserted `_alias_map("ncaaf") == {}`. NCAAF gained a map on
    2026-09-09 (`team_aliases._ncaaf_alias_to_name`), so the emptiness is gone
    and the two things it was PROTECTING are what get asserted instead. Both
    were the revert's actual arguments:

      1. a miss must not become a confident wrong club (`MAS`);
      2. `#603`'s `evt:` token shape must survive -- `game_token` refuses NCAAF
         explicitly so the board and venue halves keep agreeing.
    """
    from syndicate.features.shared.venue_quote_adapters import event_game_token, game_token

    # The map exists, and the name the 08-29 attempt could NOT reach now does.
    assert team_aliases._alias_map("ncaaf")
    assert team_aliases.canonical_team("ncaaf", "UMass Minutemen") == "massachusetts"
    # ...and a miss is still a miss, not a confident wrong club.
    assert team_aliases.canonical_team("ncaaf", "MAS") is None
    assert team_aliases.teams_match("ncaaf", "MAS", "Idaho Vandals") is False
    # `#603` is untouched: no club-pair token for ncaaf, so both halves of the
    # quote join still key on the event identity.
    assert game_token("ncaaf", "Massachusetts", "Rutgers") is None
    assert event_game_token("evt-mas-rut") == "evt:evt-mas-rut"
    # The token guard is a REFUSAL of shared words, not of the sport. Asserted
    # against THIS STUB's vocabulary, not the real registry's -- `state` is
    # unambiguous among six schools and shared among 26 real ones, so the
    # production behaviour belongs in `test_ncaaf_team_aliases.py` and only
    # the mechanism belongs here.
    tokens = team_aliases.unambiguous_club_tokens("ncaaf")
    assert "massachusetts" in tokens
    assert "umass" not in tokens  # names Massachusetts AND UMass Dartmouth


def test_chip_join_key_is_additive_for_every_other_sport(ncaaf_registry):
    """Sports with a map answer exactly as before; sports without still refuse."""
    # NFL's map is a static dict with no data dependency, so this is a
    # non-vacuous positive even in a worktree with no `data/`.
    assert team_aliases.chip_join_key("nfl", "Carolina Panthers") == "carolina panthers"
    assert team_aliases.chip_join_key("nfl", "GB") == "green bay packers"
    # nhl and ncaab also resolve `_alias_map` to {} and are deliberately NOT
    # given a resolver here -- this change is scoped to the sport whose cards
    # were reported wrong.
    assert team_aliases.chip_join_key("nhl", "Boston Bruins") is None
    assert team_aliases.chip_join_key("ncaab", "Duke Blue Devils") is None
    assert team_aliases.chip_join_key("ncaaf", "") is None
    assert team_aliases.chip_join_key("ncaaf", "Not A Real School Aardvarks") is None
