"""`population_outcomes_espn` -- NFL / NCAAF / WNBA props and segment lines settled from ESPN.

Every fixture under `tests/fixtures/population_outcomes/espn/` is TRIMMED FROM A REAL PAYLOAD,
and the two join sides come from independent sources: player and team names from the
recorder's own rows (OddsAPI spellings), stats and scores from ESPN / CFBD.

    nfl     recorder 2026-09-14__nfl__part000 rows for Denver Broncos @ Kansas City Chiefs
            (MNF, 2026-09-15T00:15Z); ESPN scoreboard 20260914 + summary 401872931.
    ncaaf   recorder rows for UTEP @ Michigan (2026-09-19, unplayed), RE-POINTED to the
            completed Oklahoma @ Michigan (2026-09-12, ESPN 401856679) -- no recorder row for a
            completed NCAAF game exists; `ncaaf_records.json` states the re-point. CFBD snapshot
            rows for that game and real registry rows for the six teams on the trimmed slate.
    wnba    recorder rows for Connecticut @ Atlanta (2026-09-17, first WNBA rows, unplayed),
            re-pointed to the completed Minnesota @ Atlanta (2026-08-30, ESPN 401857186);
            unmodified, they are the not-final case against the real 2026-09-17 scoreboard.

HAND-VERIFIED against ESPN's raw box before any assertion was written:
    Kenneth Walker III  rushing  ['23', '173', '7.5', '1', '60']  -> 173 yds, 1 TD
    Travis Kelce        receiving ['3', '71', '23.7', '0', '59', '5'] -> 3 rec, 71 yds, 0 TD
    first half          DEN [7, 0, ...]  KC [7, 7, ...] -> 7 - 14, total 21
    Jordan Marshall     rushing ['11', '32', '2.9', '1', '8'] (CFBD 11.0, 32.0, 1.0 TD)
    Jordin Canada       16 pts, 4 reb, 10 ast, 2-? threes; q1 ATL 26 - MIN 21
"""

from __future__ import annotations

import importlib.util
import inspect
import json
import pathlib
from datetime import datetime, timezone
from urllib.parse import urlsplit

import pytest

from syndicate.features.shared import population_outcomes_espn as poe
from syndicate.features.shared.population_outcomes_espn import (
    GRADER_VERSION,
    NCAAF_PLAYER_STATS_SNAPSHOT,
    EspnPopulationSettler,
)

_SRC = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "bucket_search.py"
_spec = importlib.util.spec_from_file_location("bucket_search", _SRC)
bs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bs)

FIX = pathlib.Path(__file__).resolve().parent / "fixtures" / "population_outcomes" / "espn"

_PAYLOADS = {
    "/apis/site/v2/sports/football/nfl/scoreboard?dates=20260914": "nfl_scoreboard_20260914.json",
    "/apis/site/v2/sports/football/nfl/summary?event=401872931": "nfl_summary_401872931.json",
    "/apis/site/v2/sports/football/nfl/scoreboard?dates=20260913": "nfl_scoreboard_20260913.json",
    "/apis/site/v2/sports/football/college-football/scoreboard?dates=20260912&groups=80&limit=200":
        "ncaaf_scoreboard_20260912.json",
    "/apis/site/v2/sports/football/college-football/summary?event=401856679": "ncaaf_summary_401856679.json",
    "/apis/site/v2/sports/basketball/wnba/scoreboard?dates=20260830": "wnba_scoreboard_20260830.json",
    "/apis/site/v2/sports/basketball/wnba/summary?event=401857186": "wnba_summary_401857186.json",
    "/apis/site/v2/sports/basketball/wnba/scoreboard?dates=20260917": "wnba_scoreboard_20260917.json",
}


class FakeEspn:
    """ESPN from the fixtures. Records every URL; an unknown one is a failed read (None)."""

    def __init__(self, refuse_host: str | None = None) -> None:
        self.urls: list[str] = []
        self.refuse_host = refuse_host

    def __call__(self, url: str):
        self.urls.append(url)
        parts = urlsplit(url)
        if self.refuse_host and parts.netloc == self.refuse_host:
            return None
        name = _PAYLOADS.get(f"{parts.path}?{parts.query}")
        return json.loads((FIX / name).read_text(encoding="utf-8")) if name else None


def _snapshot_export(requested: list[str] | None = None):
    def fetch(relative: str):
        if requested is not None:
            requested.append(relative)
        if relative != NCAAF_PLAYER_STATS_SNAPSHOT:
            return None
        return (FIX / "ncaaf_player_game_stats_401856679.csv").read_text(encoding="utf-8")

    return fetch


def _records(name: str, *, repoint: bool) -> list[dict]:
    if name.endswith(".jsonl"):
        return bs.parse_records_text((FIX / name).read_text(encoding="utf-8"))
    payload = json.loads((FIX / name).read_text(encoding="utf-8"))
    records = [dict(record) for record in payload["records"]]
    if repoint:
        for record in records:
            record["ct"] = payload["repoint"]["commence_time"]
            if record.get("at"):
                record["at"] = payload["repoint"]["away_team"]
    return records


def _shaped(records: list[dict]) -> dict[str, dict]:
    """key -> the record as `grade_population` shapes it: earliest sighting, names lent across."""
    chosen: dict[str, dict] = {}
    named: dict = {}
    for record in records:
        if record.get("ht") and record.get("at"):
            identity = bs.parse_population_key(record["k"])
            named.setdefault((record["sport"], identity["event_id"]), (record["ht"], record["at"]))
        held = chosen.get(record["k"])
        if held is None or record["t"] < held["t"]:
            chosen[record["k"]] = record
    out = {}
    for key, record in chosen.items():
        shaped, why = bs.scorecard_record(record, named)
        assert shaped is not None, why
        out[key.split("|", 1)[1]] = shaped
    return out


def _derived(shaped: dict, **changes) -> dict:
    return {**shaped, **changes}


@pytest.fixture
def ncaaf_registry(monkeypatch):
    """The registry resolver over REAL registry rows, without reading `data/`."""
    from syndicate.features.shared import ncaaf_team_registry as registry

    monkeypatch.setattr(registry, "registry_path", lambda: FIX / "ncaaf_team_registry.csv")
    monkeypatch.setattr(registry, "_odds_name_supplement", lambda: [])
    registry.unambiguous_team_index.cache_clear()
    yield
    registry.unambiguous_team_index.cache_clear()


@pytest.fixture
def nfl():
    return _shaped(_records("nfl_records_2026-09-14.jsonl", repoint=False))


# ---------------------------------------------------------------------------
# NFL
# ---------------------------------------------------------------------------


def test_grader_version():
    assert GRADER_VERSION == "espn/1"


def test_nfl_yardage_over_under_and_push(nfl):
    settler = EspnPopulationSettler(fetch_json=FakeEspn())
    assert settler(nfl["rushing yards|kenneth walker iii|full|over|170.5"]) == ("win", "espn_box")
    assert settler(nfl["rushing yards|kenneth walker iii|full|over|173.5"]) == ("loss", "espn_box")
    assert settler(nfl["rushing yards|kenneth walker iii|full|under|173.5"]) == ("win", "espn_box")
    assert settler(nfl["receiving yards|travis kelce|full|over|65.5"]) == ("win", "espn_box")
    assert settler(nfl["receptions|travis kelce|full|over|2.5"]) == ("win", "espn_box")
    # DERIVED, and only the line: no priced row sat on 173 exactly, so the real over-173.5 row is
    # re-lined to the real total to exercise the push. Name and box stay independent.
    at_the_number = _derived(nfl["rushing yards|kenneth walker iii|full|over|173.5"], line=173.0)
    assert settler(at_the_number) == ("push", "espn_box")


def test_nfl_anytime_td_yes_wins_and_loses(nfl):
    settler = EspnPopulationSettler(fetch_json=FakeEspn())
    assert settler(nfl["anytime td|kenneth walker iii|full|yes|"]) == ("win", "espn_box")
    assert settler(nfl["anytime td|travis kelce|full|yes|"]) == ("loss", "espn_box")


def test_nfl_player_absent_from_final_box_is_a_dnp_void(nfl):
    settler = EspnPopulationSettler(fetch_json=FakeEspn())
    assert settler(nfl["anytime td|brashard smith|full|yes|"]) == (None, "dnp_void")


def test_no_scorer_is_refused_by_name_before_any_read(nfl):
    fake = FakeEspn()
    settler = EspnPopulationSettler(fetch_json=fake)
    assert settler(nfl["anytime td|no scorer|full|yes|"]) == (None, "non_player_prop_unsupported")
    assert fake.urls == []


def test_nfl_first_half_lines_from_linescores(nfl):
    settler = EspnPopulationSettler(fetch_json=FakeEspn())
    assert settler(nfl["totals||h1|over|20.5"]) == ("win", "espn_linescore")
    assert settler(nfl["totals||h1|under|20.5"]) == ("loss", "espn_linescore")
    assert settler(nfl["totals||h1|over|21.5"]) == ("loss", "espn_linescore")
    assert settler(nfl["spreads||h1|home|-6.5"]) == ("win", "espn_linescore")
    assert settler(nfl["spreads||h1|away|6.5"]) == ("loss", "espn_linescore")
    assert settler(nfl["h2h||h1|away|"]) == ("loss", "espn_linescore")
    # DERIVED line: h1 finished 21 exactly.
    assert settler(_derived(nfl["totals||h1|over|21.5"], line=21.0)) == ("push", "espn_linescore")


def test_overtime_second_half_includes_it_fourth_quarter_and_three_way_do_not():
    """New Orleans 30 @ Detroit 31 in OT (2026-09-13): NO [0, 0, 14, 10, 6], DET [7, 0, 14, 3, 7].

    The two rows are real published openings; the h2 / q4 / three-way rows are DERIVED from the
    moneyline row (market, segment, side, line changed) because none was priced on this game.
    """
    rows = _shaped(_records("nfl_openings_2026-09-13_no_det.jsonl", repoint=False))
    settler = EspnPopulationSettler(fetch_json=FakeEspn())
    moneyline = rows["h2h||full|away|"]
    assert settler(moneyline) is None
    assert settler(rows["totals||h1|under|24.5"]) == ("win", "espn_linescore")  # 0 + 7
    # h2: 30 + 24 = 54 with overtime; 41 without it.
    assert settler(_derived(moneyline, segment="h2", market="totals", side="over", line=53.5)) == ("win", "espn_linescore")
    # q4: 10 + 3 = 13; overtime is not the fourth quarter.
    assert settler(_derived(moneyline, segment="q4", market="totals", side="over", line=13.5)) == ("loss", "espn_linescore")
    # Three-way full game settles on regulation: 24 - 24 is the draw.
    assert settler(_derived(moneyline, market="h2h_3_way", side="draw")) == ("win", "espn_final")
    assert settler(_derived(moneyline, market="h2h_3_way", side="home")) == ("loss", "espn_final")


def test_full_game_h2h_spreads_totals_pass_through(nfl):
    fake = FakeEspn()
    settler = EspnPopulationSettler(fetch_json=fake)
    game = nfl["h2h||full|home|"]
    assert not settler.handles(game)
    assert settler(game) is None
    for market, side, line in (("spreads", "home", -3.5), ("totals", "over", 44.5)):
        assert settler(_derived(game, market=market, side=side, line=line)) is None
    assert fake.urls == []


def test_reachability_a_real_prop_row_grades_only_through_the_settler(nfl):
    """off != on. Without the settler `grade_population` counts the row `player_prop`."""
    records = _records("nfl_records_2026-09-14.jsonl", repoint=False)
    row = next(r for r in records if r["k"].endswith("|rushing yards|kenneth walker iii|full|over|170.5"))
    named_source = next(r for r in records if r["k"].endswith("|rushing yards|kenneth walker iii|full|over|61.5"))
    assert named_source.get("ht")
    graded, ungraded = bs.grade_population([row, named_source], {}, today="2026-09-15")
    assert ungraded.get("player_prop") == 2 and not graded

    settler = EspnPopulationSettler(fetch_json=FakeEspn())
    shaped, _ = bs.scorecard_record(row, {("nfl", bs.parse_population_key(row["k"])["event_id"]): (named_source["ht"], named_source["at"])})
    assert settler(shaped, bs.mbs.view_from_record(row)) == ("win", "espn_box")

    if "extra_settler" not in inspect.signature(bs.grade_population).parameters:
        pytest.skip("grade_population has no extra_settler hook in this checkout yet")
    graded, ungraded = bs.grade_population([row, named_source], {}, today="2026-09-15", extra_settler=settler)
    assert "player_prop" not in ungraded
    assert len(graded) == 2 and {g["y"] for g in graded} == {1.0}


# ---------------------------------------------------------------------------
# NCAAF
# ---------------------------------------------------------------------------


def test_ncaaf_props_settle_from_the_cfbd_snapshot(ncaaf_registry):
    rows = _shaped(_records("ncaaf_records.json", repoint=True))
    requested: list[str] = []
    settler = EspnPopulationSettler(fetch_json=FakeEspn(), fetch_export=_snapshot_export(requested))
    assert settler(rows["rushing yards|jordan marshall|full|under|103.5"]) == ("win", "cfbd_snapshot")
    assert settler(rows["rushing yards|jordan marshall|full|over|103.5"]) == ("loss", "cfbd_snapshot")
    assert settler(rows["anytime td|jordan marshall|full|yes|"]) == ("win", "cfbd_snapshot")
    assert settler(rows["anytime td|jj buchanan|full|yes|"]) == ("loss", "cfbd_snapshot")
    assert settler(rows["receptions|jj buchanan|full|over|4.5"]) == ("loss", "cfbd_snapshot")
    assert settler(rows["passing yards|bryce underwood|full|under|194.5"]) == ("win", "cfbd_snapshot")
    assert requested == [NCAAF_PLAYER_STATS_SNAPSHOT]


def test_ncaaf_player_absent_from_the_snapshot_game_is_unverifiable(ncaaf_registry):
    rows = _shaped(_records("ncaaf_records.json", repoint=True))
    settler = EspnPopulationSettler(fetch_json=FakeEspn(), fetch_export=_snapshot_export())
    assert settler(rows["anytime td|channing goodwin|full|yes|"]) == (None, "player_absent_unverifiable")
    assert settler(rows["anytime td|michigan wolverines d/st|full|yes|"]) == (None, "non_player_prop_unsupported")


def test_ncaaf_falls_back_to_the_espn_box_when_the_snapshot_lacks_the_game(ncaaf_registry):
    rows = _shaped(_records("ncaaf_records.json", repoint=True))
    settler = EspnPopulationSettler(fetch_json=FakeEspn(), fetch_export=None)
    assert settler(rows["rushing yards|jordan marshall|full|under|103.5"]) == ("win", "espn_box")
    assert settler(rows["anytime td|jordan marshall|full|yes|"]) == ("win", "espn_box")
    assert settler(rows["anytime td|channing goodwin|full|yes|"]) == (None, "dnp_void")


def test_ncaaf_join_goes_through_the_registry_not_a_prefix(ncaaf_registry):
    """Michigan State and Oklahoma State play the same Saturday; neither may stand in."""
    rows = _shaped(_records("ncaaf_records.json", repoint=True))
    settler = EspnPopulationSettler(fetch_json=FakeEspn(), fetch_export=_snapshot_export())
    event, why = settler._locate("ncaaf", rows["anytime td|jordan marshall|full|yes|"])
    assert why == "" and event["event_id"] == "401856679"
    spartans = _derived(rows["anytime td|jordan marshall|full|yes|"], home_team="Michigan State Spartans",
                        away_team="Eastern Michigan Eagles")
    event, _ = settler._locate("ncaaf", spartans)
    assert event["event_id"] == "401858440"


# ---------------------------------------------------------------------------
# WNBA
# ---------------------------------------------------------------------------


def test_wnba_points_combos_and_double_double():
    rows = _shaped(_records("wnba_records.json", repoint=True))
    settler = EspnPopulationSettler(fetch_json=FakeEspn())
    assert settler(rows["player_points|jordin canada|full|over|10.5"]) == ("win", "espn_box")
    assert settler(rows["player_points|jordin canada|full|under|10.5"]) == ("loss", "espn_box")
    assert settler(rows["player_points|angel reese|full|over|15.5"]) == ("loss", "espn_box")
    assert settler(rows["player_points_rebounds_assists|jordin canada|full|over|20.5"]) == ("win", "espn_box")
    assert settler(rows["player_threes|allisha gray|full|over|1.5"]) == ("win", "espn_box")
    assert settler(rows["player_double_double|jordin canada|full|yes|"]) == ("win", "espn_box")
    assert settler(rows["player_double_double|rhyne howard|full|yes|"]) == ("loss", "espn_box")


def test_wnba_first_quarter_spread_total_and_three_way_draw():
    rows = _shaped(_records("wnba_records.json", repoint=True))
    settler = EspnPopulationSettler(fetch_json=FakeEspn())
    assert settler(rows["spreads||q1|home|-4.5"]) == ("win", "espn_linescore")
    assert settler(rows["spreads||q1|away|4.5"]) == ("loss", "espn_linescore")
    assert settler(rows["totals||q1|over|41.5"]) == ("win", "espn_linescore")
    assert settler(rows["h2h_3_way||q1|draw|"]) == ("loss", "espn_linescore")
    assert settler(rows["h2h||full|home|"]) is None


def test_not_final_refuses(monkeypatch):
    """The real 2026-09-17 slate, every game `pre` on ESPN."""
    rows = _shaped(_records("wnba_records.json", repoint=False))
    monkeypatch.setattr(poe, "_utcnow", lambda: datetime(2026, 9, 18, 0, 0, tzinfo=timezone.utc))
    fake = FakeEspn()
    settler = EspnPopulationSettler(fetch_json=fake)
    assert settler(rows["player_points|jordin canada|full|over|10.5"]) == (None, "not_started")
    assert settler(rows["spreads||q1|home|-4.5"]) == (None, "not_started")
    assert any("dates=20260917" in url for url in fake.urls)

    monkeypatch.setattr(poe, "_utcnow", lambda: datetime(2026, 9, 17, 12, 0, tzinfo=timezone.utc))
    before_kickoff = EspnPopulationSettler(fetch_json=FakeEspn())
    assert before_kickoff(rows["totals||q1|over|41.5"]) == (None, "not_started")


# ---------------------------------------------------------------------------
# reads
# ---------------------------------------------------------------------------


def test_second_host_is_tried_when_the_first_refuses(nfl):
    fake = FakeEspn(refuse_host="site.api.espn.com")
    settler = EspnPopulationSettler(fetch_json=fake)
    assert settler(nfl["anytime td|kenneth walker iii|full|yes|"]) == ("win", "espn_box")
    assert {urlsplit(url).netloc for url in fake.urls} == {"site.api.espn.com", "site.web.api.espn.com"}


def test_disk_cache_keeps_immutable_payloads_only(tmp_path, nfl, monkeypatch):
    settler = EspnPopulationSettler(fetch_json=FakeEspn(), cache_dir=tmp_path)
    assert settler(nfl["anytime td|kenneth walker iii|full|yes|"]) == ("win", "espn_box")
    assert len(list((tmp_path / "espn").glob("*.json"))) == 2  # final scoreboard + completed summary

    offline = EspnPopulationSettler(fetch_json=lambda url: None, cache_dir=tmp_path)
    assert offline(nfl["anytime td|travis kelce|full|yes|"]) == ("loss", "espn_box")
    assert offline.counters["espn_requests"] == 0

    wnba = _shaped(_records("wnba_records.json", repoint=False))
    monkeypatch.setattr(poe, "_utcnow", lambda: datetime(2026, 9, 18, 0, 0, tzinfo=timezone.utc))
    EspnPopulationSettler(fetch_json=FakeEspn(), cache_dir=tmp_path)(wnba["spreads||q1|home|-4.5"])
    assert len(list((tmp_path / "espn").glob("*.json"))) == 2  # the pregame scoreboard is not kept
