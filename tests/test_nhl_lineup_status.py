"""NHL lineups stop dressing players the news collector holds OUT (lane `nhl-lineup-status`, 2026-10-16).

The REACHABILITY test comes first (model engine standard §4.3: `off != on` on a fixture where a dressed player is
OUT), then the state / as-of / matching rules `syndicate.features.nhl.lineup_availability` is built on.
"""
from __future__ import annotations

import csv
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from syndicate.features.nhl import lineup_availability as la
from syndicate.features.nhl.sim_engine.hockeysim.ingestion.collect import collect_slate_inputs
from syndicate.features.nhl.sim_engine.hockeysim.ingestion.nhl_web import NhlWebIngestClient
from syndicate.local_nhl_odds import _alias_team_abbr, _team_abbr

UTC = timezone.utc
DATE = "2026-10-16"
START = datetime(2026, 10, 17, 2, 0, tzinfo=UTC)          # ANA vs COL, 9 PM CT
NOW = datetime(2026, 10, 16, 20, 0, tzinfo=UTC)           # 3 PM CT: the production path (game still ahead)
GAME_IDS = ["2026020001", "2026020002"]

# ANA: 14 forwards -- 100 = Granlund, the top-minutes forward; 112 = Poehling, a book-listed depth forward who
# played game 1 but NOT the last game; 113 = a depth forward who played only the last game -- 7 D, 2 G.
# COL mirrors it with no one out.
ANA_F = {100: "Mikael Granlund", 101: "Troy Terry", 102: "Leo Carlsson", 103: "Mason McTavish", 104: "Cutter Gauthier",
         105: "Frank Vatrano", 106: "Alex Killorn", 107: "Ryan Strome", 108: "Isac Lundestrom", 109: "Ross Johnston",
         110: "Sam Colangelo", 111: "Brett Leason", 112: "Ryan Poehling", 113: "Nikita Nesterenko"}
ANA_D = {200 + i: f"Ana Defense{i}" for i in range(7)}
ANA_G = {300: "Lukas Dostal", 301: "Ville Husso"}
COL_F = {500 + i: f"Col Forward{i}" for i in range(14)}
COL_D = {600 + i: f"Col Defense{i}" for i in range(7)}
COL_G = {700: "Mackenzie Blackwood", 701: "Scott Wedgewood"}


def _skater(pid: int, name: str, pos: str, toi_min: float) -> dict:
    return {"playerId": pid, "name": {"default": name}, "position": pos,
            "toi": f"{int(toi_min):02d}:{int(round((toi_min % 1) * 60)):02d}" if toi_min > 0 else "00:00"}


def _forward_toi(i: int, game: int) -> float:
    if i < 12:
        return 21.0 - i                      # every-night regulars
    if i == 12:
        return 8.0 if game == 0 else 0.0     # played game 1, missed the last game
    return 0.0 if game == 0 else 7.0         # called up for the last game only


def _side(f: dict, d: dict, g: dict, *, game: int) -> dict:
    forwards = []
    for i, (pid, name) in enumerate(f.items()):
        toi = _forward_toi(i, game)
        if toi > 0:
            forwards.append(_skater(pid, name, "C", toi))
    defense = [_skater(pid, name, "D", 24.0 - i) for i, (pid, name) in enumerate(d.items()) if i < 6 or game == 0]
    goalies = [_skater(pid, name, "G", 60.0 if i == 0 else 0.0) for i, (pid, name) in enumerate(g.items())]
    return {"forwards": forwards, "defense": defense, "goalies": goalies}


class FixtureClient(NhlWebIngestClient):
    def __init__(self, cache_dir: Path) -> None:
        super().__init__(cache_dir=cache_dir, offline=True)

    def roster_full_names(self, team_abbr, season):  # noqa: D401 - offline fixture
        if team_abbr == "ANA":
            return {**ANA_F, **ANA_D, **ANA_G}
        return {**COL_F, **COL_D, **COL_G}

    def recent_finished_game_ids(self, team_abbr, season, *, before_date, n=8):
        return list(GAME_IDS)


def _write_csv(path: Path, rows: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def _state_record(aid: str, name: str, team: str, status: str, updated: str = "2026-10-16T17:00Z", **extra) -> dict:
    return {"athlete_id": aid, "athlete": name, "team": team, "status": status, "type": status[:2].upper(),
            "detail_type": "Upper Body", "return_date": None, "comment": f"{name} {status.lower()}",
            "source_updated_at": updated, **extra}


def _write_state(news: Path, records: list, *, written_at: datetime = NOW - timedelta(minutes=10)) -> Path:
    path = news / "_state" / "nhl_injuries.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({r["athlete_id"]: r for r in records}), encoding="utf-8")
    os.utime(path, (written_at.timestamp(), written_at.timestamp()))
    return path


def _write_events(news: Path, events: list) -> None:
    by_day: dict = {}
    for ev in events:
        by_day.setdefault(ev["captured_at"][:10], []).append(ev)
    for day, evs in by_day.items():
        path = news / "nhl" / "injuries" / f"{day}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(e) + "\n" for e in evs), encoding="utf-8")


def _fixture(tmp_path: Path, *, book_lists_poehling: bool = True):
    root = tmp_path / "nhl_source"
    _write_csv(root / "data" / "odds" / "games" / f"date={DATE}" / "scoreboard.csv",
               [{"gamePk": "2026020120", "gameDate": "2026-10-17T02:00:00Z",
                 "home": "Anaheim Ducks", "away": "Colorado Avalanche"}])
    if book_lists_poehling:
        _write_csv(root / "data" / "props" / "player_props_lines" / f"date={DATE}" / "oddsapi.csv",
                   [{"player_name": n, "home_team": "Anaheim Ducks", "away_team": "Colorado Avalanche",
                     "market": "SOG", "line": "1.5", "over_price": "-110", "under_price": "-110", "book": "fanduel",
                     "is_current": "True"} for n in ("Ryan Poehling", "Mikael Granlund")])
    cache = tmp_path / "cache"
    cache.mkdir()
    for g, gid in enumerate(GAME_IDS):
        box = {"gameDate": f"2026-10-1{2 + 2 * g}", "homeTeam": {"abbrev": "ANA"}, "awayTeam": {"abbrev": "COL"},
               "playerByGameStats": {"homeTeam": _side(ANA_F, ANA_D, ANA_G, game=g),
                                     "awayTeam": _side(COL_F, COL_D, COL_G, game=g)}}
        (cache / f"boxscore_{gid}.json").write_text(json.dumps(box), encoding="utf-8")
    news = tmp_path / "news"
    _write_state(news, [
        _state_record("1001", "Mikael Granlund", "Anaheim Ducks", "Out"),
        _state_record("1002", "Ryan Poehling", "Anaheim Ducks", "Injured Reserve"),
        _state_record("1003", "Troy Terry", "Anaheim Ducks", "Day-To-Day"),
    ])
    return root, news, FixtureClient(cache)


def _collect(root, news, client, **kw):
    return collect_slate_inputs(DATE, root=root, client=client, write=False, availability_now=kw.pop("now", NOW),
                                news_root=news, **kw)


def _dressed(summary: dict, team: str = "Anaheim Ducks") -> dict:
    return {r["full_name"]: r["line_slot"] for r in summary["_lineups"] if r["team"] == team and r.get("line_slot")}


# ----------------------------------------------------------------------------- reachability (FIRST)


def test_reachability_off_and_on_build_different_lineups(tmp_path, monkeypatch):
    root, news, client = _fixture(tmp_path)
    monkeypatch.setenv(la.SWITCH_ENV, "off")
    off = _collect(root, news, client)
    monkeypatch.setenv(la.SWITCH_ENV, "on")
    on = _collect(root, news, client)

    assert _dressed(off) != _dressed(on)
    assert _dressed(off)["Mikael Granlund"] == "L1"           # the defect: OUT, dressed on the top line
    names_on = {r["full_name"] for r in on["_lineups"]}
    assert "Mikael Granlund" not in names_on                   # removed, not merely unslotted (no ~0 projection)
    assert "Ryan Poehling" not in names_on
    assert "Troy Terry" in _dressed(on)                        # Day-To-Day stays dressed
    assert len([s for s in _dressed(on).values() if s.startswith("L")]) == 12   # the slot re-sort refills the 12
    assert off["lineup_status"] == {"enabled": False, "applied": False}
    assert on["lineup_status"]["excluded"] == 2
    assert {e["full_name"] for e in on["_exclusions"]} == {"Mikael Granlund", "Ryan Poehling"}


def test_absent_env_means_on(tmp_path, monkeypatch):
    root, news, client = _fixture(tmp_path)
    monkeypatch.delenv(la.SWITCH_ENV, raising=False)
    assert "Mikael Granlund" not in _dressed(_collect(root, news, client))


def test_a_book_listing_cannot_force_an_out_player_back_in(tmp_path, monkeypatch):
    # Poehling missed the last game and is the 13th forward: only the book listing dresses him when status is off.
    root, news, client = _fixture(tmp_path)
    monkeypatch.setenv(la.SWITCH_ENV, "off")
    assert "Ryan Poehling" in _dressed(_collect(root, news, client))
    monkeypatch.setenv(la.SWITCH_ENV, "on")
    assert "Ryan Poehling" not in _dressed(_collect(root, news, client))


def test_exclusions_are_printed_and_written_beside_the_lineups(tmp_path, monkeypatch, capsys):
    root, news, client = _fixture(tmp_path)
    monkeypatch.setenv(la.SWITCH_ENV, "on")
    out_dir = tmp_path / "processed"
    summary = collect_slate_inputs(DATE, root=root, client=client, out_dir=out_dir, availability_now=NOW, news_root=news)
    printed = capsys.readouterr().out
    assert "[nhl_lineup_status] date=2026-10-16 team=ANA" in printed and "Mikael Granlund(OUT:Out)" in printed
    assert "NHL_LINEUP_STATUS date=2026-10-16 teams=2 excluded=2" in printed
    payload = json.loads(Path(summary["exclusions_path"]).read_text(encoding="utf-8"))
    assert Path(summary["exclusions_path"]).parent == Path(summary["lineups_path"]).parent
    assert {e["full_name"]: e["status"] for e in payload["excluded"]} == {"Mikael Granlund": "OUT", "Ryan Poehling": "OUT"}
    assert payload["feeds"]["ANA"]["feed_status"] == "ok" and payload["feeds"]["ANA"]["source"] == "state_file"
    with Path(summary["lineups_path"]).open(encoding="utf-8") as fh:
        assert "Mikael Granlund" not in {r["full_name"] for r in csv.DictReader(fh)}


# ----------------------------------------------------------------------------- a missing or dead feed is LOUD


def test_absent_state_removes_nobody_and_says_not_applied(tmp_path, monkeypatch, capsys):
    root, _news, client = _fixture(tmp_path)
    monkeypatch.setenv(la.SWITCH_ENV, "on")
    summary = _collect(root, tmp_path / "no_news_here", client)
    assert "Mikael Granlund" in _dressed(summary)
    assert summary["lineup_status"]["feeds"] == {"state_file:absent": 2}
    assert "NOT APPLIED for 2 team(s): feed=absent" in capsys.readouterr().out


def test_stale_state_removes_nobody(tmp_path, monkeypatch, capsys):
    root, news, client = _fixture(tmp_path)
    _write_state(news, [_state_record("1001", "Mikael Granlund", "Anaheim Ducks", "Out")],
                 written_at=NOW - timedelta(hours=30))
    monkeypatch.setenv(la.SWITCH_ENV, "on")
    summary = _collect(root, news, client)
    assert "Mikael Granlund" in _dressed(summary)
    assert "feed=stale" in capsys.readouterr().out


def test_an_availability_error_keeps_the_lineup(tmp_path, monkeypatch, capsys):
    root, news, client = _fixture(tmp_path)
    monkeypatch.setenv(la.SWITCH_ENV, "on")

    def boom(*a, **k):
        raise ValueError("bad state")

    monkeypatch.setattr(la.CollectorState, "injuries_at", boom)
    summary = _collect(root, news, client)
    assert "Mikael Granlund" in _dressed(summary)
    assert "NOT APPLIED" in capsys.readouterr().out


# ----------------------------------------------------------------------------- state, never events


def test_a_rekeyed_same_run_pair_nets_to_one_record():
    # 2026-10-16 00:51:17Z on the fleet: Jason Dickinson's ESPN id changed in one run.
    events = [
        {"event": "new", "athlete_id": "596013", "athlete": "Jason Dickinson", "team": "Edmonton Oilers",
         "status": "Day-To-Day", "captured_at": "2026-10-15T17:41:17Z", "source_updated_at": "2026-10-15T17:36Z"},
        {"event": "new", "athlete_id": "596043", "athlete": "Jason Dickinson", "team": "Edmonton Oilers",
         "status": "Out", "captured_at": "2026-10-16T00:51:17Z", "source_updated_at": "2026-10-16T00:38Z"},
        {"event": "cleared", "athlete_id": "596013", "athlete": "Jason Dickinson", "team": "Edmonton Oilers",
         "previous_status": "Day-To-Day", "captured_at": "2026-10-16T00:51:17Z"},
    ]
    state = la.dedupe_state(la.replay_injury_events(events, datetime(2026, 10, 16, 1, 0, tzinfo=UTC)))
    assert list(state) == [("EDM", "jason dickinson")]
    assert state[("EDM", "jason dickinson")]["status"] == "Out"
    before = la.dedupe_state(la.replay_injury_events(events, datetime(2026, 10, 16, 0, 0, tzinfo=UTC)))
    assert before[("EDM", "jason dickinson")]["status"] == "Day-To-Day"


def test_two_ids_for_one_player_keep_the_latest_update():
    state = {"a": _state_record("a", "Jason Dickinson", "Edmonton Oilers", "Day-To-Day", updated="2026-10-15T17:36Z"),
             "b": _state_record("b", "Jason Dickinson", "Edmonton Oilers", "Out", updated="2026-10-16T00:38Z")}
    deduped = la.dedupe_state(state)
    assert len(deduped) == 1 and deduped[("EDM", "jason dickinson")]["status"] == "Out"


@pytest.mark.parametrize("status,removed", [
    ("Out", True), ("Injured Reserve", True), ("Suspension", True), ("Long Term Injured Reserve", True),
    ("Day-To-Day", False), ("Questionable", False), ("Active", False), ("", False),
])
def test_removal_rule(status, removed):
    assert (la.removal_status(status) in la.REMOVE_STATUSES) is removed


# ----------------------------------------------------------------------------- as of


def test_state_file_newer_than_as_of_is_replayed_not_read(tmp_path):
    """A post-game rebuild: a player hurt IN the game must not be removed from that game's lineup."""
    news = tmp_path / "news"
    _write_events(news, [
        {"event": "new", "athlete_id": "1", "athlete": "Pre Game", "team": "Anaheim Ducks", "status": "Out",
         "captured_at": "2026-10-17T00:00:00Z", "source_updated_at": "2026-10-16T23:50Z"},
        {"event": "new", "athlete_id": "2", "athlete": "In Game", "team": "Anaheim Ducks", "status": "Out",
         "captured_at": "2026-10-17T04:00:00Z", "source_updated_at": "2026-10-17T03:55Z"},
    ])
    _write_state(news, [_state_record("1", "Pre Game", "Anaheim Ducks", "Out"),
                        _state_record("2", "In Game", "Anaheim Ducks", "Out")],
                 written_at=datetime(2026, 10, 17, 4, 30, tzinfo=UTC))
    collector = la.CollectorState(news, now=datetime(2026, 10, 17, 5, 0, tzinfo=UTC))
    at_start, meta = collector.injuries_at(START)
    assert meta["source"] == "event_replay" and meta["feed_status"] == "ok"
    assert set(at_start) == {("ANA", "pre game")}
    now_state, now_meta = collector.injuries_at(None)
    assert now_meta["source"] == "state_file" and set(now_state) == {("ANA", "pre game"), ("ANA", "in game")}


def test_before_collection_is_reported_not_silent(tmp_path):
    news = tmp_path / "news"
    _write_events(news, [{"event": "new", "athlete_id": "1", "athlete": "A B", "team": "Anaheim Ducks",
                          "status": "Out", "captured_at": "2026-10-13T19:29:58Z"}])
    _write_state(news, [_state_record("1", "A B", "Anaheim Ducks", "Out")],
                 written_at=datetime(2026, 10, 16, 0, 0, tzinfo=UTC))
    records, meta = la.CollectorState(news, now=NOW).injuries_at(datetime(2026, 1, 10, tzinfo=UTC))
    assert records == {} and meta["feed_status"] == "before_collection"


def test_game_started_uses_puck_drop_as_of(tmp_path, monkeypatch):
    root, news, client = _fixture(tmp_path)
    monkeypatch.setenv(la.SWITCH_ENV, "on")
    avail = la.SlateAvailability.load(DATE, root=root, now=START + timedelta(hours=3), news_root=news)
    assert avail.as_of_for("ANA") == START
    assert la.SlateAvailability.load(DATE, root=root, now=NOW, news_root=news).as_of_for("ANA") == NOW


# ----------------------------------------------------------------------------- scratches


def _gameinfo(news: Path, captured: str, home_scratches: list) -> None:
    path = news / "nhl" / "gameinfo" / f"{captured[:10]}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    rec = {"event": "new", "game_id": "2026020120", "home": "ANA", "away": "COL", "start_utc": "2026-10-17T02:00:00Z",
           "captured_at": captured, "home_scratches": home_scratches, "away_scratches": [], "referees": [], "linesmen": []}
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec) + "\n")


def test_posted_scratch_removes_by_nhl_id_until_puck_drop_only(tmp_path, monkeypatch):
    root, news, client = _fixture(tmp_path)
    _write_state(news, [])
    _gameinfo(news, "2026-10-17T01:31:17Z", [{"id": 105, "name": "Frank Vatrano"}])
    _gameinfo(news, "2026-10-17T02:11:17Z", [{"id": 106, "name": "Alex Killorn"}])   # after puck drop
    monkeypatch.setenv(la.SWITCH_ENV, "on")
    summary = _collect(root, news, client, now=START + timedelta(hours=4))
    dressed = _dressed(summary)
    assert "Frank Vatrano" not in dressed and "Alex Killorn" in dressed
    assert [(e["full_name"], e["status"], e["source"]) for e in summary["_exclusions"]] == \
        [("Frank Vatrano", "INACTIVE", "nhl_gameinfo")]


# ----------------------------------------------------------------------------- matching


def test_initial_surname_fallback_is_unique_within_the_team():
    rows = [{"player_id": 1, "full_name": "Mitchell Marner"}, {"player_id": 2, "full_name": "Jack Hughes"},
            {"player_id": 3, "full_name": "Luke Hughes"}]
    recs = {("TOR", "mitch marner"): {"athlete": "Mitch Marner", "status": "Out"},
            ("TOR", "j hughes"): {"athlete": "J Hughes", "status": "Out"},
            ("BOS", "luke hughes"): {"athlete": "Luke Hughes", "status": "Out"}}
    matched = la.match_records(rows, "TOR", recs)
    assert matched[1][1] == "initial_surname"
    assert 2 in matched and 3 not in matched          # "j hughes" -> only Jack; the BOS Luke Hughes never crosses


def test_ambiguous_initial_surname_is_refused():
    rows = [{"player_id": 1, "full_name": "Jack Hughes"}, {"player_id": 2, "full_name": "Jake Hughes"}]
    assert la.match_records(rows, "NJD", {("NJD", "j hughes"): {"athlete": "J. Hughes", "status": "Out"}}) == {}


ESPN_TEAM_NAMES = [
    "Anaheim Ducks", "Boston Bruins", "Buffalo Sabres", "Calgary Flames", "Carolina Hurricanes", "Chicago Blackhawks",
    "Colorado Avalanche", "Columbus Blue Jackets", "Dallas Stars", "Detroit Red Wings", "Edmonton Oilers",
    "Florida Panthers", "Los Angeles Kings", "Minnesota Wild", "Montreal Canadiens", "Montréal Canadiens",
    "Nashville Predators", "New Jersey Devils", "New York Islanders", "New York Rangers", "Ottawa Senators",
    "Philadelphia Flyers", "Pittsburgh Penguins", "San Jose Sharks", "Seattle Kraken", "St. Louis Blues",
    "Tampa Bay Lightning", "Toronto Maple Leafs", "Utah Mammoth", "Vancouver Canucks", "Vegas Golden Knights",
    "Washington Capitals", "Winnipeg Jets",
]


@pytest.mark.parametrize("name", ESPN_TEAM_NAMES)
def test_every_espn_team_name_maps_to_the_lineup_team_key(name):
    code = la.team_code(name)
    assert code and len(code) == 3
    assert code == _alias_team_abbr(_team_abbr(name))   # exactly the key collect.py builds the lineup under


def test_all_32_teams_have_distinct_codes():
    assert len({la.team_code(n) for n in ESPN_TEAM_NAMES}) == 32
