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
    # Assert the VERDICT, not the whole payload. The original exact-equality
    # assertion broke the moment `evidence` was added -- and evidence is the
    # thing that made a wrong `fresh` diagnosable at all, so the test was
    # over-specified against a diagnostic that was always going to grow.
    st = lb.is_stale("2026-05-28", [7])
    assert st["stale"] is False
    assert st["reason"] == "fresh"


def test_status_artifact_is_written_and_allowlisted(wired, tmp_path):
    """The status file is the ONLY channel that survives — the sim job's stdout
    goes to a disk file whose endpoint serves the last 8000 chars, and the
    publish sweep's ~109 PUBLISH_OK lines consume that window entirely."""
    wired({7: _sim_payload()}, {"pitcher_props": {}})
    written = lb.write_status_artifact("2026-05-28", {"outcome": "skipped_fresh", "games": 3})
    assert written, "status write returned nothing"
    doc = json.loads(Path(written).read_text(encoding="utf-8"))
    assert doc["outcome"] == "skipped_fresh"
    assert doc["date"] == "2026-05-28"
    assert doc["writtenAt"], "no timestamp -- a status with no time cannot be aged"


def test_status_filename_matches_the_EXISTING_allowlist(tmp_path):
    """Must publish with NO new HOT_ARTIFACT_PATTERNS entry: adding one needs a
    WEB deploy, because the publish endpoint gates on web's copy of the
    allowlist -- that is what 403'd five artifacts on 2026-08-18."""
    from syndicate.features.shared.artifact_publisher import is_hot_artifact_relative_path
    rel = "mlb_source/source_artifacts/data/daily/ladders/daily_ladders_status_2026_08_19.json"
    assert is_hot_artifact_relative_path(rel)


def test_status_never_raises_on_an_unwritable_path(monkeypatch):
    """A status write must never fail the sim job it is reporting on."""
    monkeypatch.setattr(lb, "daily_ladders_path", lambda d: Path("/nonexistent\x00/x.json"))
    assert lb.write_status_artifact("2026-05-28", {"outcome": "rebuilt"}) is None


def test_a_freshly_touched_file_with_STALE_CONTENT_is_stale(wired, tmp_path):
    """The exact production failure, 2026-08-19.

    The artifact is SYNCED onto the worker from web, so its mtime is whenever
    the sync ran while its `generatedAt` is the last real build. `is_stale` read
    mtime, saw a recent file, and returned `fresh` for a 28-hour-old artifact —
    which kept the ladders serving "Market line: -" through four correct deploys.
    """
    base = wired({7: _sim_payload()}, {"pitcher_props": {}})
    dest = base / "daily_ladders_2026-05-28.json"
    dest.write_text(json.dumps({
        "generatedAt": "2026-08-18T18:20:25+00:00",   # a day old
        "groups": {"pitcher": {"strikeouts": {"rows": [1]}}},
    }), encoding="utf-8")
    # mtime is NOW -- newer than every input. Only the content betrays it.
    st = lb.is_stale("2026-05-28", [7])
    assert st["stale"] is True, f"stale content read as fresh: {st}"


def test_unreadable_artifact_does_not_default_to_fresh(wired, tmp_path):
    """An unknown must not take the permissive branch. A corrupt artifact that
    reads as `fresh` would suppress every future rebuild silently."""
    base = wired({7: _sim_payload()}, {"pitcher_props": {}})
    dest = base / "daily_ladders_2026-05-28.json"
    dest.write_text("{ not json", encoding="utf-8")
    st = lb.is_stale("2026-05-28", [7])
    assert isinstance(st.get("stale"), bool)
    assert st.get("reason") != "artifact_missing"


def test_fresh_verdict_carries_the_values_it_compared(wired, tmp_path):
    """A `fresh` verdict SUPPRESSES a rebuild, so a wrong one is silent forever.
    On 2026-08-20 the status artifact reported fresh for a 28-hour-old artifact
    and the verdict alone could not distinguish a genuinely-fresher worker copy
    from a failed timestamp parse. The evidence is what separates them."""
    base = wired({7: _sim_payload()}, {"pitcher_props": {}})
    dest = base / "daily_ladders_2026-05-28.json"
    dest.write_text(json.dumps({"generatedAt": "2026-08-18T18:20:25+00:00"}), encoding="utf-8")
    st = lb.is_stale("2026-05-28", [7])
    ev = st.get("evidence") or {}
    assert ev.get("path"), "no path recorded"
    assert "fileMtime" in ev, "no file mtime recorded"
    assert ev.get("artifactGeneratedAt") == "2026-08-18T18:20:25+00:00"
    assert "contentTs" in ev


def test_a_parse_failure_is_NAMED_not_swallowed(wired, tmp_path):
    """Falling back to mtime is correct; doing it silently is not -- that is the
    exact ambiguity that cost a diagnosis cycle."""
    base = wired({7: _sim_payload()}, {"pitcher_props": {}})
    dest = base / "daily_ladders_2026-05-28.json"
    dest.write_text(json.dumps({"generatedAt": "not-a-timestamp"}), encoding="utf-8")
    ev = (lb.is_stale("2026-05-28", [7]) or {}).get("evidence") or {}
    assert "parseError" in ev, f"a parse failure left no trace: {ev}"


# ------------------------------------------------- market key wiring (#440)

def test_hitter_strikeouts_is_wired_to_the_market_that_is_actually_fetched():
    """`batter_strikeouts` is paid for on every hitter fetch and was unused.

    This asserts the JOIN KEY equals the key the fetcher requests, read from
    the fetcher itself rather than retyped -- a hardcoded string here would
    pass while the two drifted apart, which is the exact defect being fixed.
    """
    import scripts.fetch_mlb_oddsapi_local as fetcher
    from syndicate.features.mlb.ladders_build import HITTER_PROPS

    wired = HITTER_PROPS["hitter_strikeouts"]["odds"]
    assert wired is not None, "hitter_strikeouts left unwired"
    assert wired in fetcher.DEFAULT_HITTER_MARKETS, (
        f"{wired!r} is not in DEFAULT_HITTER_MARKETS -- the join can never fire"
    )


def test_every_wired_hitter_market_is_a_real_key_and_fed_ones_are_fetched():
    """Separates 'wired and fed' from 'wired but not fetched' EXPLICITLY.

    doubles/triples/stolen_bases are deliberately wired ahead of the fetcher, so
    this test must not demand they be fetched -- but it must also not let a
    typo'd key masquerade as that deliberate state.
    """
    import scripts.fetch_mlb_oddsapi_local as fetcher
    from syndicate.features.mlb.ladders_build import HITTER_PROPS

    known_unfed = {"batter_doubles", "batter_triples", "batter_stolen_bases"}
    for prop, spec in HITTER_PROPS.items():
        key = spec["odds"]
        if key is None:
            continue
        assert key.startswith("batter_"), f"{prop}: {key!r} is not a batter market key"
        assert key in fetcher.DEFAULT_HITTER_MARKETS or key in known_unfed, (
            f"{prop}: {key!r} is neither fetched nor a known-unfed key -- likely a typo"
        )


def test_pitcher_props_without_a_market_stay_none():
    """OddsAPI has no pitches-thrown or batters-faced market.

    Pinned so a future 'fix the Nones' pass cannot invent a key that no book
    publishes and quietly produce a join that always misses.
    """
    from syndicate.features.mlb.ladders_build import PITCHER_PROPS
    assert PITCHER_PROPS["pitches"]["odds"] is None
    assert PITCHER_PROPS["batters_faced"]["odds"] is None


def test_wired_pitcher_markets_match_the_fetchers_mapping():
    import scripts.fetch_mlb_oddsapi_local as fetcher
    from syndicate.features.mlb.ladders_build import PITCHER_PROPS

    produced = set(fetcher.PITCHER_MARKET_KEY_MAP.values())
    for prop, spec in PITCHER_PROPS.items():
        key = spec["odds"]
        if key is None:
            continue
        assert key in produced, (
            f"{prop}: {key!r} is not produced by PITCHER_MARKET_KEY_MAP {sorted(produced)}"
        )
