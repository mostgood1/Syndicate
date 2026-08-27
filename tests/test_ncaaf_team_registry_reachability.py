"""`#558` -- the resolver's INPUT has to be on the disk of the service that runs it.

Measured on live-odds-worker 2026-08-25T21:03:35Z, the first live OddsAPI call
this module ever made:

    [ncaaf_odds] EVENTS events=111 teams=184 resolved=0 unresolved=184

Not a naming gap. The alias map was EMPTY, because the CFBD team registry is
git-tracked (so a checkout and web both have it) and matched none of the 155
`HOT_ARTIFACT_PATTERNS` (so neither worker could ever be sent it).

These tests are about REACHABILITY and about the failure being AUDIBLE. A value
assertion over a fixture cannot catch either -- the fixture is the thing that
lied.
"""

from __future__ import annotations

import fnmatch
import importlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from syndicate.features.ncaaf import oddsapi_lines as lines
from syndicate.features.shared import artifact_publisher as publisher

fetcher = importlib.import_module("scripts.fetch_ncaaf_oddsapi_game_lines")


# --------------------------------------------------------------------------
# the allowlist -- checked against the real tuple, never by eye
# --------------------------------------------------------------------------

def test_the_registry_can_cross_to_a_worker_at_all():
    """`HOT_ARTIFACT_PATTERNS` is what PERMITS the transfer. Without a match,
    `pull_streamed_artifact` refuses before it makes a request, so no amount of
    calling it would have helped."""
    rel = fetcher.TEAM_REGISTRY_RELATIVE_PATH
    assert [p for p in publisher.HOT_ARTIFACT_PATTERNS if fnmatch.fnmatch(rel, p)]
    assert publisher.is_hot_artifact_relative_path(rel)


def test_the_constant_names_the_path_the_resolver_actually_reads():
    """Two spellings of one path is how this drifts back. Assert they agree
    rather than trusting the string."""
    from syndicate.features.ncaaf.sources import team_registry_snapshot_path

    assert str(team_registry_snapshot_path()).replace("\\", "/").endswith(
        fetcher.TEAM_REGISTRY_RELATIVE_PATH
    )


# --------------------------------------------------------------------------
# registry_status -- answerable without spending a credit
# --------------------------------------------------------------------------

def test_status_reports_ok_on_a_real_checkout():
    status = lines.registry_status()
    assert status["ok"] is True
    assert status["teams"] > 100, status


def test_status_reports_not_ok_for_an_absent_file(monkeypatch, tmp_path):
    monkeypatch.setattr(
        lines, "team_registry_snapshot_path", lambda: tmp_path / "nope.csv"
    )
    status = lines.registry_status()
    assert status == {
        "path": str(tmp_path / "nope.csv"),
        "exists": False,
        "rows": 0,
        "teams": 0,
        "ok": False,
    }


# --------------------------------------------------------------------------
# the guard that was disabled by the condition that breaks it
# --------------------------------------------------------------------------

def test_an_empty_registry_is_audible(monkeypatch, tmp_path, capsys):
    """`if known:` meant a POPULATED map was validated and an ABSENT one was
    waved through in silence. That is backwards."""
    monkeypatch.setattr(
        lines, "team_registry_snapshot_path", lambda: tmp_path / "nope.csv"
    )
    lines._alias_map.cache_clear()
    try:
        assert lines._alias_map() == {}
        assert "TEAM_REGISTRY_EMPTY" in capsys.readouterr().out
    finally:
        lines._alias_map.cache_clear()


def test_an_empty_registry_does_not_raise_because_web_builds_boards_with_this(
    monkeypatch, tmp_path
):
    """`cards.py` and `game_projections.py` call the resolver on the WEB service.
    Raising there turns a missing input into a dead page; degrading to "no
    lines" is correct for them. The FETCHER is the caller that must refuse."""
    monkeypatch.setattr(
        lines, "team_registry_snapshot_path", lambda: tmp_path / "nope.csv"
    )
    lines._alias_map.cache_clear()
    try:
        assert lines.resolve_team("Alabama Crimson Tide") is None  # must not raise
    finally:
        lines._alias_map.cache_clear()


# --------------------------------------------------------------------------
# the fetcher -- refuses BEFORE the credit, and says which failure it is
# --------------------------------------------------------------------------

def _no_registry(monkeypatch, tmp_path):
    monkeypatch.setattr(
        lines, "team_registry_snapshot_path", lambda: tmp_path / "nope.csv"
    )
    lines._alias_map.cache_clear()
    lines._mascot_tails.cache_clear()


def test_the_fetch_never_happens_without_a_registry(monkeypatch, tmp_path, capsys):
    """THE ORDER IS THE FIX. A credit spent against an empty map buys 184
    unresolved names and nothing else."""
    _no_registry(monkeypatch, tmp_path)
    called: list[str] = []
    monkeypatch.setattr(
        fetcher, "fetch_events", lambda *a, **k: called.append("fetched") or []
    )
    monkeypatch.setattr(
        "syndicate.features.shared.artifact_publisher.pull_streamed_artifact",
        lambda *a, **k: (False, 0),
    )
    monkeypatch.setenv("ODDS_API_KEY", "test-key")

    code = fetcher.main(["--report"])
    assert code == 3
    assert called == [], "a credit was spent against an empty registry"
    out = capsys.readouterr().out
    assert "TEAM_REGISTRY_ABSENT" in out
    assert str(tmp_path / "nope.csv") in out, "the resolved path must be in the output"


def test_it_tries_a_pull_before_giving_up(monkeypatch, tmp_path, capsys):
    """A worker's disk is fillable. Refusing without trying would make this a
    permanent failure on exactly the service that needs it."""
    _no_registry(monkeypatch, tmp_path)
    pulls: list[str] = []
    monkeypatch.setattr(
        "syndicate.features.shared.artifact_publisher.pull_streamed_artifact",
        lambda rel, **k: pulls.append(rel) or (False, 0),
    )
    monkeypatch.setattr(fetcher, "fetch_events", lambda *a, **k: [])
    monkeypatch.setenv("ODDS_API_KEY", "test-key")

    fetcher.main(["--report"])
    assert pulls == [fetcher.TEAM_REGISTRY_RELATIVE_PATH]


def test_a_successful_pull_lets_the_run_proceed(monkeypatch, capsys):
    """The re-check reads DISK, not the pull's return value: a 304 writes
    nothing and is the normal steady state."""
    seen: list[str] = []
    monkeypatch.setattr(
        fetcher, "fetch_events", lambda *a, **k: seen.append("fetched") or []
    )
    monkeypatch.setenv("ODDS_API_KEY", "test-key")

    code = fetcher.main(["--report"])
    assert code == 0
    assert seen == ["fetched"]
    assert "TEAM_REGISTRY rows=" in capsys.readouterr().out


def test_a_failing_pull_cannot_take_the_run_down(monkeypatch, tmp_path, capsys):
    _no_registry(monkeypatch, tmp_path)

    def boom(*a, **k):
        raise RuntimeError("no admin token")

    monkeypatch.setattr(
        "syndicate.features.shared.artifact_publisher.pull_streamed_artifact", boom
    )
    monkeypatch.setenv("ODDS_API_KEY", "test-key")

    assert fetcher.main(["--report"]) == 3  # refused, not crashed
    assert "TEAM_REGISTRY_PULL_FAILED" in capsys.readouterr().out


# --------------------------------------------------------------------------
# `#558` -- the 8 the first successful live read could not place
# --------------------------------------------------------------------------

# OddsAPI spelling -> registry canonical, from live-odds-worker
# 2026-08-25T21:41:08Z (`resolved=176 unresolved=8` over the real 111-event
# slate). Every one was looked up in the registry, not guessed.
MEASURED_UNRESOLVED = {
    "Appalachian State Mountaineers": "App State",
    "Southern Mississippi Golden Eagles": "Southern Miss",
    "Sam Houston State Bearkats": "Sam Houston",
    "Citadel Bulldogs": "The Citadel",
    "Houston Baptist Huskies": "Houston Christian",
    "Nicholls State Colonels": "Nicholls",
    "Southeastern Louisiana Lions": "SE Louisiana",
    "Albany": "UAlbany",
}


@pytest.mark.parametrize("sent,canonical", sorted(MEASURED_UNRESOLVED.items()))
def test_the_names_the_live_feed_actually_sent_now_resolve(sent, canonical):
    assert lines.resolve_team(sent) == canonical


@pytest.mark.parametrize(
    "sent", ["Appalachian State", "Southern Mississippi", "Sam Houston State",
             "Houston Baptist", "Nicholls State", "Southeastern Louisiana"]
)
def test_the_school_form_resolves_too_not_only_the_mascot_form(sent):
    """`resolve_team` strips a trailing mascot, but these mascots are REAL
    registry mascots owned by other schools, so stripping only ever yields the
    school form -- which is not itself a registry key for any of these. Both
    spellings are covered so the suffix path is irrelevant."""
    assert lines.resolve_team(sent) is not None, sent


def test_adding_app_state_did_not_steal_west_virginia():
    """"Mountaineers" belongs to West Virginia, App State, Schreiner and
    Western Colorado. A supplement entry keyed on the bare mascot would have
    taken all four; these are keyed on "<school> <mascot>" and the school form
    only."""
    assert lines.resolve_team("West Virginia Mountaineers") == "West Virginia"
    assert lines.resolve_team("Appalachian State Mountaineers") == "App State"


def test_bare_mascots_still_refuse():
    """The registry carries ~680 schools sharing mascots. A confident wrong
    join is invisible; an unresolved name is a gap you can see."""
    for mascot in ("Mountaineers", "Bulldogs", "Wildcats", "Lions", "Huskies"):
        assert lines.resolve_team(mascot) is None, mascot


def test_albany_is_a_stated_judgement_not_an_inferred_one():
    """The registry carries BOTH `UAlbany` and `Albany State GA`. The feed
    sends the bare word; a Division II school is not on a book's slate, so the
    answer is UAlbany -- an inference from the slate's composition, recorded as
    a hand-verified entry rather than left to the alias generator, which
    correctly refuses ambiguity and would have resolved nothing."""
    assert lines.resolve_team("Albany") == "UAlbany"
    assert lines.resolve_team("Albany State GA") == "Albany State GA"


def test_every_supplement_entry_names_a_real_canonical_team():
    """`_alias_map()` raises on a supplement entry whose target is not in the
    registry. Building the map IS the assertion -- this makes it explicit so a
    typo fails here rather than at boot on a worker."""
    mapping = lines._alias_map()
    known = set(mapping.values())
    for alias, canonical in lines._ODDSAPI_NAME_SUPPLEMENT.items():
        assert canonical in known, f"{alias!r} -> {canonical!r}"
