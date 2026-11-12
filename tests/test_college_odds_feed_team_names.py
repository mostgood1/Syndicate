"""College odds-feed team spellings resolve to their ESPN school (lane `college-odds-feed-team-names`, 2026-11-12).

User: "still have college teams not matching" -- CSU Bakersfield's men's @ Western Illinois and women's @ Washington
drew chip-less cards on the Games rail. The fleet audit (`scripts/college_team_name_audit.py`) over every ncaab/wncaab
quote shard found 3 unresolved names in 5 of 723 events; these pin the two derivation rules that resolve all of them,
and the audit's own contract.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import college_team_name_audit as audit_mod
from syndicate.features.shared.ncaab_team_registry import registry_rows
from syndicate.features.shared.team_aliases import chip_join_key


@pytest.mark.parametrize("league", ["ncaab", "wncaab"])
@pytest.mark.parametrize(
    "feed, espn",
    [
        ("CSU Bakersfield Roadrunners", "Cal State Bakersfield Roadrunners"),
        ("CSU Fullerton Titans", "Cal State Fullerton Titans"),  # 11-03's one-off, now derived
        ("CSU Northridge Matadors", "Cal State Northridge Matadors"),
    ],
)
def test_the_feeds_csu_spelling_joins_espns_cal_state_school(league, feed, espn):
    assert chip_join_key(league, espn) is not None
    assert chip_join_key(league, feed) == chip_join_key(league, espn)


@pytest.mark.parametrize(
    "feed, espn",
    [
        ("Montana Grizzlies", "Montana Lady Griz"),
        ("Western Kentucky Hilltoppers", "Western Kentucky Lady Toppers"),
        ("Penn State Nittany Lions", "Penn State Lady Lions"),  # 11-03's one-off, now derived
        ("Texas Tech Red Raiders", "Texas Tech Lady Raiders"),
    ],
)
def test_a_womens_team_priced_under_the_mens_mascot_joins_its_school(feed, espn):
    assert chip_join_key("wncaab", espn) is not None
    assert chip_join_key("wncaab", feed) == chip_join_key("wncaab", espn)


@pytest.mark.parametrize("bare", ["Hilltoppers", "Grizzlies", "Red Raiders", "Nittany Lions"])
def test_the_mens_mascot_is_offered_to_womens_teams_only_in_composites(bare):
    """Like the "Lady" stem: a bare mascot from the OTHER registry must not become a women's key."""
    assert chip_join_key("wncaab", bare) is None


def test_every_mens_mascot_composite_names_its_own_school_or_nothing():
    """The collision pass may drop a composite, but it must never point at a different school."""
    mens = {row["espn_id"]: row["mascot"] for row in registry_rows("ncaab")}
    checked = 0
    for row in registry_rows("wncaab"):
        men = mens.get(row["espn_id"])
        if not men or men == row["mascot"]:
            continue
        own = chip_join_key("wncaab", row["school"])
        got = chip_join_key("wncaab", f"{row['school']} {men}")
        assert got in (own, None), (row["school"], men, got)
        checked += 1
    assert checked >= 25  # 29 women's schools carry a different mascot from the men's row (2026-11-12)


def _write_league(root: Path, league: str, shard_rows: list[dict], scoreboard_games: list[dict], day: str = "2026-11-12"):
    quotes = root / f"{league}_source" / "tracking" / "book_quotes"
    quotes.mkdir(parents=True)
    (quotes / f"{day}.jsonl").write_text("".join(json.dumps(r) + "\n" for r in shard_rows), encoding="utf-8")
    (quotes / f".{day}.jsonl.lock").write_text("", encoding="utf-8")
    board = root / f"{league}_source" / "data" / "scoreboard"
    board.mkdir(parents=True)
    (board / f"scoreboard_{day}.json").write_text(json.dumps({"games": scoreboard_games}), encoding="utf-8")


def _quote(away, home, event_id="e1", market="h2h"):
    return {"kind": "game", "date": "2026-11-12", "event_id": event_id, "away_team": away, "home_team": home,
            "market": market, "selection": "home", "price": -110}


def test_the_audit_names_an_unresolved_team_with_its_espn_spelling(tmp_path):
    _write_league(
        tmp_path, "wncaab",
        [_quote("Nowhere Tech Robots", "Duke Blue Devils"), _quote("Nowhere Tech Robots", "Duke Blue Devils", market="spreads")],
        [{"away": {"name": "Somewhere Tech Robots"}, "home": {"name": "Duke Blue Devils"}}],
    )
    report = audit_mod.audit(tmp_path, ["wncaab"])
    league = report["leagues"]["wncaab"]
    assert league["events"] == 1 and league["events_with_an_unresolved_team"] == 1
    assert league["unresolved"] == {
        "Nowhere Tech Robots": {"events": 1, "dates": ["2026-11-12"], "espn_spelling": {"Somewhere Tech Robots": 1}}
    }
    assert audit_mod.exit_code(report) == 1


def test_the_audit_is_clean_on_the_names_this_lane_fixed(tmp_path):
    _write_league(
        tmp_path, "wncaab",
        [_quote("CSU Bakersfield Roadrunners", "Washington Huskies"), _quote("Montana Grizzlies", "Western Kentucky Hilltoppers", "e2")],
        [],
    )
    report = audit_mod.audit(tmp_path, ["wncaab"])
    assert report["leagues"]["wncaab"]["unresolved"] == {}
    assert audit_mod.exit_code(report) == 0


def test_the_audit_reads_no_shards_as_unknown_not_clean(tmp_path):
    report = audit_mod.audit(tmp_path, ["ncaab", "wncaab"])
    assert audit_mod.exit_code(report) == 2
