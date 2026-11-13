"""Women's college basketball rows get team crests (lane wncaab-team-crests, #798).

Measured on the fleet's served board 2026-11-13 17:46Z: 39 of 39 WNCAAB rows (6 games) had no crest, and NCAAB 3 of 205
(Lindenwood 2, West Florida 1). `team_logos._SPORTS` left `wncaab` out and no WNCAAB branding snapshot existed. Now
ESPN's women's list is a committed snapshot, and a college school its own league's snapshot lacks takes the other
league's crest. ESPN files both teams under one id; the own league still goes first, because Tennessee's women's crest is
a different image.

Each behaviour has an OFF arm that must differ (off != on).
"""

from __future__ import annotations

import csv
import importlib.util
import sys
from pathlib import Path

import pytest

from syndicate.features.shared import team_logos

REPO_ROOT = Path(__file__).resolve().parents[1]
HEADER = "team_id,abbreviation,location,display_name,primary_color,secondary_color,logo_url,source_snapshot_date\n"
CDN = "https://a.espncdn.com/i/teamlogos/ncaa/500"

# The fleet's men's snapshot (2026-07-20): no Lindenwood, West Florida with no URL.
MEN = (
    f"2633,TENN,Tennessee,Tennessee Volunteers,,,{CDN}/2633.png,2026-07-20\n"
    f"119,TOW,Towson,Towson Tigers,,,{CDN}/119.png,2026-07-20\n"
    f"2697,UWF,West Florida,West Florida Argonauts,,,,2026-07-20\n"
    f"2678,VMI,VMI,VMI Keydets,,,{CDN}/2678.png,2026-07-20\n"  # men's only: no women's D-I team
)
# ESPN's women's list (2026-11-13): the Lady Vols crest, Lindenwood, West Florida with a URL.
WOMEN = (
    f"2633,TENN,Tennessee,Tennessee Lady Volunteers,,,{CDN}/2633_ncw.png,2026-11-13\n"
    f"119,TOW,Towson,Towson Tigers,,,{CDN}/119.png,2026-11-13\n"
    f"2352,L-MD,Loyola Maryland,Loyola Maryland Greyhounds,,,{CDN}/2352.png,2026-11-13\n"
    f"2815,LIN,Lindenwood,Lindenwood Lions,,,{CDN}/2815.png,2026-11-13\n"
    f"2697,UWF,West Florida,West Florida Argonauts,,,{CDN}/2697.png,2026-11-13\n"
)


@pytest.fixture
def branding(tmp_path, monkeypatch):
    files = {}
    for sport, body in (("ncaab", MEN), ("wncaab", WOMEN)):
        path = Path(tmp_path) / f"{sport}_team_branding.csv"
        path.write_text(HEADER + body, encoding="utf-8")
        files[sport] = [path]
    monkeypatch.setattr(team_logos, "_branding_files", lambda sport: files.get(sport, []))
    caches = (team_logos._index, team_logos._by_team_id)  # an OFF arm may swap one out until monkeypatch undoes it
    for cache in caches:
        cache.cache_clear()
    yield files
    for cache in caches:
        cache.cache_clear()


def no_wncaab(monkeypatch) -> None:
    """The pre-fix lookup: `wncaab` is not one of the sports."""
    monkeypatch.setattr(team_logos, "_SPORTS", tuple(s for s in team_logos._SPORTS if s != "wncaab"))


def no_sibling(monkeypatch) -> None:
    monkeypatch.setattr(team_logos, "_COLLEGE_SIBLING", {})


# ------------------------------------------------------------------------------------------------------ the gap

def test_a_wncaab_row_gets_its_crest(branding, monkeypatch):
    assert team_logos.logo_url("wncaab", "Loyola (MD) Greyhounds", "loyola maryland") == f"{CDN}/2352.png"
    no_wncaab(monkeypatch)
    assert team_logos.logo_url("wncaab", "Loyola (MD) Greyhounds", "loyola maryland") is None  # off: the 11-13 board


def test_the_row_stamp_fills_both_wncaab_crests(branding, monkeypatch):
    def rows():
        return [{"sport_slug": "wncaab", "away_team": "Towson Tigers", "away_key": "towson",
                 "home_team": "Loyola (MD) Greyhounds", "home_key": "loyola maryland"}]

    on = rows()
    assert team_logos.stamp_row_logos(on) == 1
    assert (on[0].get("away_logo"), on[0].get("home_logo")) == (f"{CDN}/119.png", f"{CDN}/2352.png")
    no_wncaab(monkeypatch)
    off = rows()
    assert team_logos.stamp_row_logos(off) == 0
    assert (off[0].get("away_logo"), off[0].get("home_logo")) == (None, None)


def test_a_school_the_mens_snapshot_lacks_takes_the_womens_crest(branding, monkeypatch):
    """NCAAB Lindenwood (2 rows on 11-13) and West Florida (no URL in the men's snapshot)."""
    assert team_logos.logo_url("ncaab", "Lindenwood Lions", "lindenwood") == f"{CDN}/2815.png"
    assert team_logos.logo_url("ncaab", "West Florida Argonauts", "west florida") == f"{CDN}/2697.png"
    no_sibling(monkeypatch)
    assert team_logos.logo_url("ncaab", "Lindenwood Lions", "lindenwood") is None
    assert team_logos.logo_url("ncaab", "West Florida Argonauts", "west florida") is None


# ------------------------------------------------------------------------------------------- what must not change

def test_the_own_league_crest_wins(branding):
    """Tennessee: the Lady Vols crest on a women's row, the men's on a men's row, whatever name the feed sends."""
    for name in ("Tennessee Volunteers", "Tennessee Lady Volunteers", "Tennessee", "TENN"):
        assert team_logos.logo_url("wncaab", name) == f"{CDN}/2633_ncw.png", name
        assert team_logos.logo_url("ncaab", name) == f"{CDN}/2633.png", name
    assert team_logos.logo_url("ncaab", "VMI Keydets", "vmi") == f"{CDN}/2678.png"  # the sibling has no VMI


def test_a_school_the_own_league_holds_keeps_its_own_crest_through_the_sibling(branding, monkeypatch):
    """A name only the sibling knows, for a school the own league holds: the own league's crest, never the sibling's."""
    assert team_logos.logo_url("ncaab", "Tennessee Lady Volunteers") == f"{CDN}/2633.png"
    monkeypatch.setattr(team_logos, "_by_team_id", lambda sport: ({}, {}))
    assert team_logos.logo_url("ncaab", "Tennessee Lady Volunteers") == f"{CDN}/2633_ncw.png"  # off: the sibling's


def test_a_crest_the_row_already_has_is_kept(branding):
    row = {"sport_slug": "ncaab", "home_team": "Lindenwood Lions", "home_logo": "https://example.test/kept.png"}
    team_logos.stamp_row_logos([row])
    assert row["home_logo"] == "https://example.test/kept.png"


def test_no_other_sport_borrows_a_college_crest(branding):
    assert team_logos.logo_url("nba", "Towson Tigers") is None
    assert team_logos.logo_url("ncaaf", "Lindenwood Lions") is None


def test_a_school_neither_league_holds_is_none(branding):
    assert team_logos.logo_url("wncaab", "Nowhere State Nomads") is None
    assert team_logos.logo_url("ncaab", "Nowhere State Nomads") is None


# ----------------------------------------------------------------------------------- where the snapshot comes from

def _load_builder():
    spec = importlib.util.spec_from_file_location("test_team_logos_wncaab_builder",
                                                  REPO_ROOT / "scripts" / "build_team_branding_snapshot.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_the_builder_writes_where_team_logos_reads(tmp_path, monkeypatch):
    """Reachability: `--sport wncaab` writes ESPN's women's list to the file `_branding_files("wncaab")` returns."""
    builder = _load_builder()
    assert builder.SPORT_CONFIG["wncaab"][0] == "basketball/womens-college-basketball"
    monkeypatch.setenv("SYNDICATE_WNCAAB_SOURCE_ROOT", str(tmp_path / "wncaab_source"))
    target = builder.branding_snapshot_path("wncaab")
    target.parent.mkdir(parents=True)
    target.write_text(HEADER + WOMEN, encoding="utf-8")
    assert list(team_logos._branding_files("wncaab")) == [target]


def test_the_committed_womens_snapshot_is_whole():
    """A deleted or truncated snapshot would silently take every WNCAAB crest away again."""
    data = REPO_ROOT / "data"
    if not data.is_dir():
        pytest.skip("no data/ in this checkout (a session worktree without --with-data)")
    path = data / "wncaab_source" / "source_artifacts" / "data" / "processed" / "team_branding" / "wncaab_team_branding.csv"
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    assert len(rows) >= 355
    assert all(row["logo_url"].startswith("https://a.espncdn.com/") for row in rows)
    by_id = {row["team_id"]: row for row in rows}
    for team_id in ("2352", "119", "2815", "2385"):  # Loyola Maryland, Towson, Lindenwood, Mercyhurst
        assert team_id in by_id, team_id
