"""The native MLB ladders builder. `#440`.

These tests exist because the failure this module fixes was INVISIBLE: the card
rendered twelve rows with a full sim side and an empty market side, and looked
like a working feature. So the assertions are about the join and the refusal,
not just "does it produce rows".

The output schema is pinned by `ladders_common.pitcher_rows_from_summary`, which
is the real consumer, so one test drives that reader rather than re-asserting the
keys by hand — a hand-written copy of the schema would pass while the card broke.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from syndicate.features.mlb import ladders_build as lb  # noqa: E402
from syndicate.features.mlb.ladders_common import pitcher_rows_from_summary  # noqa: E402


def _sim_payload(pid: str = "111", name: str = "Colin Rea", *, dist=None) -> dict:
    return {
        "away": {"team_id": 1, "name": "Chicago Cubs", "abbreviation": "CHC"},
        "home": {"team_id": 2, "name": "Pittsburgh Pirates", "abbreviation": "PIT"},
        "starters": {"away": int(pid), "home": 222},
        "starter_names": {"away": name, "home": "Other Guy"},
        "sim": {
            "pitcher_props": {
                pid: {"so_dist": dist or {"4": 200, "5": 500, "6": 300}, "so_mean": 5.1},
            }
        },
    }


@pytest.fixture()
def wired(monkeypatch, tmp_path):
    """Point both native readers at fixtures under tmp_path."""
    def _install(sim_payloads: dict[int, dict], odds: dict | None):
        sim_dir = tmp_path / "sims"
        sim_dir.mkdir(exist_ok=True)
        paths = {}
        for pk, payload in sim_payloads.items():
            p = sim_dir / f"sim_pk{pk}.json"
            p.write_text(json.dumps(payload), encoding="utf-8")
            paths[pk] = p
        odds_path = tmp_path / "odds.json"
        if odds is not None:
            odds_path.write_text(json.dumps(odds), encoding="utf-8")
        monkeypatch.setattr(lb, "daily_sim_artifact_path", lambda d, pk: paths.get(int(pk)))
        monkeypatch.setattr(lb, "daily_snapshot_oddsapi_pitcher_props_path", lambda d: odds_path)
        # is_stale() checks BOTH odds files. Leaving the hitter path pointing at
        # real repo data let its mtime leak in and made two staleness tests fail
        # for a reason unrelated to what they assert.
        monkeypatch.setattr(lb, "daily_snapshot_oddsapi_hitter_props_path", lambda d: odds_path)
        monkeypatch.setattr(lb, "daily_ladders_path", lambda d: tmp_path / f"daily_ladders_{d}.json")
        return tmp_path
    return _install


def test_join_matches_and_carries_the_market_line(wired):
    wired({7: _sim_payload()}, {"pitcher_props": {"colin rea": {"strikeouts": {"line": 4.5}}}})
    grp = lb.build_pitcher_strikeout_rows("2026-05-28", [7])
    row = [r for r in grp["rows"] if r["pitcherName"] == "Colin Rea"][0]
    assert row["marketLine"] == 4.5
    assert grp["matchedPlayers"] == 1
    assert grp["unmatchedOdds"] == []


def test_over_probability_is_mass_strictly_above_the_line(wired):
    # dist 4:200, 5:500, 6:300 against a 4.5 line -> 5 and 6 win = 800/1000
    wired({7: _sim_payload()}, {"pitcher_props": {"colin rea": {"strikeouts": {"line": 4.5}}}})
    row = [r for r in lb.build_pitcher_strikeout_rows("2026-05-28", [7])["rows"]
           if r["pitcherName"] == "Colin Rea"][0]
    assert row["overLineProb"] == pytest.approx(0.8)
    assert row["mode"] == 5
    assert row["simCount"] == 1000


def test_whole_number_line_treats_a_push_as_not_over(wired):
    """A 5.0 line must NOT count the 5s as wins. Off-by-one here silently
    inflates every over probability, which is the kind of error that looks
    like model edge."""
    wired({7: _sim_payload()}, {"pitcher_props": {"colin rea": {"strikeouts": {"line": 5.0}}}})
    row = [r for r in lb.build_pitcher_strikeout_rows("2026-05-28", [7])["rows"]
           if r["pitcherName"] == "Colin Rea"][0]
    assert row["overLineProb"] == pytest.approx(0.3)


def test_absent_market_gives_None_not_zero(wired):
    """`None` and `0.0` mean different things: no market vs a market we beat
    never. The card renders them differently and conflating them invents a
    confident zero."""
    wired({7: _sim_payload()}, {"pitcher_props": {}})
    row = lb.build_pitcher_strikeout_rows("2026-05-28", [7])["rows"][0]
    assert row["marketLine"] is None
    assert row["overLineProb"] is None
    assert row["mean"] is not None, "the sim side must survive an absent market"


def test_accented_name_still_joins(wired):
    """The odds feed writes unaccented ASCII. A bare .lower() drops this
    pitcher and the row silently loses its market line."""
    wired({7: _sim_payload(name="José Ramírez")},
          {"pitcher_props": {"jose ramirez": {"strikeouts": {"line": 6.5}}}})
    row = [r for r in lb.build_pitcher_strikeout_rows("2026-05-28", [7])["rows"]
           if r["pitcherName"] == "José Ramírez"][0]
    assert row["marketLine"] == 6.5


def test_unmatched_odds_are_REPORTED_not_swallowed(wired):
    """The whole point of the accounting: a thin card and a broken join look
    identical without these numbers."""
    wired({7: _sim_payload()},
          {"pitcher_props": {"colin rea": {"strikeouts": {"line": 4.5}},
                             "someone else": {"strikeouts": {"line": 3.5}}}})
    grp = lb.build_pitcher_strikeout_rows("2026-05-28", [7])
    assert grp["oddsPlayers"] == 2
    assert grp["matchedPlayers"] == 1
    assert "someone else" in grp["unmatchedOdds"]


def test_team_fields_are_strings_not_dicts(wired):
    """`away`/`home` are objects. Stringifying them put a whole dict into the
    rendered card; only running the real reader caught it."""
    wired({7: _sim_payload()}, {"pitcher_props": {}})
    row = lb.build_pitcher_strikeout_rows("2026-05-28", [7])["rows"][0]
    assert row["team"] == "CHC"
    assert row["matchup"] == "CHC @ PIT"


def test_the_real_native_reader_consumes_the_output(wired):
    """Drive the ACTUAL consumer. A hand-rolled schema assertion would pass
    while the card broke."""
    wired({7: _sim_payload()}, {"pitcher_props": {"colin rea": {"strikeouts": {"line": 4.5}}}})
    grp = lb.build_pitcher_strikeout_rows("2026-05-28", [7])
    cards, label = pitcher_rows_from_summary({"groups": {"pitcher": {"strikeouts": grp}}})
    assert label == "Strikeouts"
    card = [c for c in cards if c["title"] == "Colin Rea"][0]
    assert card["eyebrow"] == "CHC"
    assert card["meta"] == "CHC @ PIT"
    assert "4.5" in card["badge"]
    assert any(m["label"] == "Over" and m["value"] != "-" for m in card["metrics"])


def test_refuses_to_overwrite_a_good_artifact_with_an_empty_one(wired, tmp_path):
    """An empty rebuild renders identically to a correct one, so overwriting on
    zero rows destroys working output and looks like a successful refresh."""
    base = wired({}, {"pitcher_props": {}})
    dest = base / "daily_ladders_2026-05-28.json"
    dest.write_text(json.dumps({"groups": {"pitcher": {"strikeouts": {"rows": [1, 2, 3]}}}}),
                    encoding="utf-8")
    result = lb.write_ladders_artifact("2026-05-28", [])
    assert result["ok"] is False
    assert result["reason"] == "no_rows_refusing_to_overwrite"
    assert json.loads(dest.read_text(encoding="utf-8"))["groups"]["pitcher"]["strikeouts"]["rows"] == [1, 2, 3]


def test_writes_when_there_are_rows(wired, tmp_path):
    base = wired({7: _sim_payload()}, {"pitcher_props": {"colin rea": {"strikeouts": {"line": 4.5}}}})
    result = lb.write_ladders_artifact("2026-05-28", [7])
    assert result["ok"] is True
    doc = json.loads((base / "daily_ladders_2026-05-28.json").read_text(encoding="utf-8"))
    assert doc["generatedBy"] == "syndicate.features.mlb.ladders_build"
    assert doc["groups"]["pitcher"]["strikeouts"]["rows"]


# ------------------------------------------------------------ freshness trigger

def _touch(p: Path, when: float) -> None:
    import os
    p.write_text(p.read_text(encoding="utf-8") if p.exists() else "{}", encoding="utf-8")
    os.utime(p, (when, when))


def test_stale_when_the_artifact_is_missing(wired, tmp_path):
    wired({7: _sim_payload()}, {"pitcher_props": {}})
    assert lb.is_stale("2026-05-28", [7])["reason"] == "artifact_missing"


def test_stale_when_the_ODDS_are_newer(wired, tmp_path):
    """The exact production failure: ladder built 2026-08-18T18:20, odds
    arrived 2026-08-19T18:16, nothing compared the two."""
    base = wired({7: _sim_payload()}, {"pitcher_props": {}})
    dest = base / "daily_ladders_2026-05-28.json"
    dest.write_text("{}", encoding="utf-8")
    _touch(dest, 1_000_000)
    _touch(base / "odds.json", 2_000_000)
    for f in (base / "sims").glob("*.json"):
        _touch(f, 500_000)
    out = lb.is_stale("2026-05-28", [7])
    assert out["stale"] is True and out["reason"] == "odds_newer"


def test_stale_when_a_SIM_is_newer(wired, tmp_path):
    """This clause is what re-derives ladders on game state: sims re-run every
    15-20 minutes, so a ladder older than the latest sim is stale even when the
    market has not moved."""
    base = wired({7: _sim_payload()}, {"pitcher_props": {}})
    dest = base / "daily_ladders_2026-05-28.json"
    dest.write_text("{}", encoding="utf-8")
    _touch(dest, 1_000_000)
    _touch(base / "odds.json", 500_000)
    for f in (base / "sims").glob("*.json"):
        _touch(f, 2_000_000)
    out = lb.is_stale("2026-05-28", [7])
    assert out["stale"] is True and out["reason"] == "sim_newer"


def test_fresh_when_the_artifact_is_newest(wired, tmp_path):
    """Must NOT rebuild every tick: this runs after every sim on a worker at
    ~88% of its memory cap."""
    base = wired({7: _sim_payload()}, {"pitcher_props": {}})
    dest = base / "daily_ladders_2026-05-28.json"
    dest.write_text("{}", encoding="utf-8")
    _touch(base / "odds.json", 500_000)
    for f in (base / "sims").glob("*.json"):
        _touch(f, 600_000)
    _touch(dest, 2_000_000)
    assert lb.is_stale("2026-05-28", [7]) == {"stale": False, "reason": "fresh"}
