"""The in-play overlay no longer starves refresh-worker's book-grid tick (lane `book-grid-overlay-starvation`,
todo #790; user 2026-11-13 "Yes, fix #790 here").

Two mechanisms, each held here with its off switch (off != on):
  1. `prop_evidence.basketball._box_games` reads the player's rows from an index built once per read cache,
     instead of walking every box row of every source on every call (577 ms of a 617 ms card, warm, fleet
     bench 11-13). The result must be IDENTICAL to the walk: same rows, order, one line per date, opponents.
  2. `book_grid_artifact.build_inplay_overlay` passes ONE context per build (one read cache, one evidence
     budget, the board's date) instead of the bare call, whose read cache and 60 s budget restarted every
     wall-clock minute.
"""
from __future__ import annotations

import csv
import os
from pathlib import Path

import pytest

from syndicate.features.shared import book_grid_artifact as bga
from syndicate.features.shared import layer2_row_context as rc
from syndicate.features.shared.prop_evidence import basketball as bb
from syndicate.features.shared.prop_evidence import common as C

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "prop_evidence" / "root"
BOX_FIELDS = ["date", "game_id", "TEAM_ABBREVIATION", "PLAYER_NAME", "MIN", "PTS", "REB", "AST", "FG3M", "STL", "BLK", "TOV"]


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in ("SYNDICATE_PROP_EVIDENCE_BOX_INDEX", "SYNDICATE_INPLAY_OVERLAY_BUILD_CONTEXT",
                 "SYNDICATE_INPLAY_OVERLAY_EVIDENCE_SECONDS", "SYNDICATE_INPLAY_OVERLAY"):
        monkeypatch.delenv(name, raising=False)


def _walk(sport, name, as_of, monkeypatch):
    """The walk, as before the index: the off switch, inside its own fresh read cache."""
    monkeypatch.setenv("SYNDICATE_PROP_EVIDENCE_BOX_INDEX", "off")
    try:
        with C.build_read_cache({}):
            return bb._box_games(sport, name, as_of)
    finally:
        monkeypatch.delenv("SYNDICATE_PROP_EVIDENCE_BOX_INDEX")


def _write_box(path: Path, rows: list[dict]):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=BOX_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in BOX_FIELDS})


def _box(date, game, team, name, minutes="30", pts="10"):
    return {"date": date, "game_id": game, "TEAM_ABBREVIATION": team, "PLAYER_NAME": name, "MIN": minutes,
            "PTS": pts, "REB": "4", "AST": "3", "FG3M": "1", "STL": "1", "BLK": "0", "TOV": "2"}


@pytest.fixture()
def nba_root(tmp_path, monkeypatch):
    """History + two dated files + a multi-season game log, with the cases the walk has rules for."""
    processed = tmp_path / "nba_source" / "data" / "processed"
    _write_box(processed / "boxscores_history.csv", [
        _box("2026-11-01", "g1", "NY", "Jalen Brunson", pts="30"),        # NY folds to NYK
        _box("2026-11-01", "g1", "BOS", "Jayson Tatum"),
        _box("2026-11-03", "g2", "NYK", "Jalen Brunson", minutes="0"),     # a DNP: dropped
        _box("2026-11-03", "g2", "MIA", "Tyler Herro"),
        _box("2026-11-05", "g3", "NYK", "D.J. Carton"),                    # "DJ Carton" on the board
        _box("2026-11-05", "g3", "PHI", "Joel Embiid"),
    ])
    _write_box(processed / "boxscores_2026-11-07.csv", [
        _box("2026-11-07", "g4", "NYK", "Jalen Brunson", pts="41"),
        _box("2026-11-07", "g4", "TOR", "Scottie Barnes"),
        _box("2026-11-01", "g1-espn", "NYK", "Jalen Brunson", pts="99"),   # same DATE, other numbering: first wins
    ])
    _write_box(processed / "boxscores_2026-11-09.csv", [
        _box("2026-11-09", "g5", "NYK", "Jalen Brunson Jr", pts="22"),      # suffix spelling
        _box("2026-11-09", "g5", "CHI", "Coby White"),
        _box("2026-11-09", "g5", "SAS", "Interloper Who"),                 # a third team in one game
    ])
    log = processed / "player_game_log_2025.csv"
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["date", "gameId", "teamTricode", "firstName", "familyName",
                                                    "MIN", "PTS", "REB", "AST", "FG3M", "STL", "BLK", "TOV"])
        writer.writeheader()
        writer.writerow({"date": "2025-04-01", "gameId": "4017", "teamTricode": "NYK", "firstName": "Jalen",
                         "familyName": "Brunson", "MIN": "35", "PTS": "25", "REB": "3", "AST": "8", "FG3M": "2",
                         "STL": "1", "BLK": "0", "TOV": "3"})
        writer.writerow({"date": "2025-04-01", "gameId": "4017", "teamTricode": "GS", "firstName": "Stephen",
                         "familyName": "Curry", "MIN": "34", "PTS": "31", "REB": "5", "AST": "6", "FG3M": "6",
                         "STL": "1", "BLK": "0", "TOV": "2"})
    monkeypatch.setenv("SYNDICATE_DATA_ROOT", str(tmp_path))
    return processed


@pytest.mark.parametrize("name", ["Jalen Brunson", "Jalen Brunson Jr.", "DJ Carton", "Tyler Herro", "Coby White",
                                  "Stephen Curry", "Nobody Here", "", None])
def test_the_index_returns_exactly_what_the_walk_returns(nba_root, monkeypatch, name):
    expected = _walk("nba", name, "2026-11-12", monkeypatch)
    with C.build_read_cache({}) as cache:
        got = bb._box_games("nba", name, "2026-11-12")
        assert any(key[0] == "box_index" for key in cache), "the index must be what answered"
    assert got == expected


def test_the_rules_the_walk_has_hold_on_the_index(nba_root):
    with C.build_read_cache({}):
        games, source = bb._box_games("nba", "Jalen Brunson", "2026-11-12")
    assert source.name == "boxscores_history.csv"
    assert [g["date"] for g in games] == ["2026-11-09", "2026-11-07", "2026-11-01", "2025-04-01"]  # DNP dropped
    assert games[2]["PTS"] == 30.0 and games[2]["game_id"] == "g1"  # first source wins the date
    assert games[2]["opponent"] == "BOS" and games[1]["opponent"] == "TOR"
    assert games[0]["opponent"] in {"CHI", "SAS"}  # a three-team game: either, as the walk does


def test_every_row_is_filed_under_every_key_of_its_name(nba_root):
    """`names_match` is a key INTERSECTION, so a row filed under one of its keys only misses a spelling
    that shares another ("Jalen Brunson Jr" -> "jalen brunson jr" and "jalen brunson")."""
    with C.build_read_cache({}):
        sources = bb._box_sources("nba", "2026-11-12")
        rows, by_key, _teams = bb._box_index("nba", sources)
    multi = 0
    for position, (name, *_rest) in enumerate(rows):
        keys = C.name_keys(name)
        multi += len(keys) > 1
        for key in keys:
            assert position in by_key[key], (name, key)
    assert multi >= 2  # "Jalen Brunson Jr", "D.J. Carton"


def test_the_first_source_wins_a_date_whatever_order_a_set_gives(tmp_path, monkeypatch):
    """The player's rows at positions 2 and 8: a set of those iterates 8 first (8 % 8 == 0), so the
    index must sort to keep the walk's first-source-wins."""
    processed = tmp_path / "nba_source" / "data" / "processed"
    _write_box(processed / "boxscores_history.csv", [
        _box("2026-11-01", "g0", "BOS", "Other One"), _box("2026-11-01", "g0", "MIA", "Other Two"),
        _box("2026-11-02", "g1", "NYK", "Mikal Bridges", pts="30"),
    ])
    _write_box(processed / "boxscores_2026-11-07.csv", [
        _box("2026-11-07", "g9", "TOR", f"Filler {i}") for i in range(5)
    ] + [_box("2026-11-02", "g1-espn", "NYK", "Mikal Bridges", pts="99")])
    monkeypatch.setenv("SYNDICATE_DATA_ROOT", str(tmp_path))
    expected = _walk("nba", "Mikal Bridges", "2026-11-12", monkeypatch)
    with C.build_read_cache({}):
        got = bb._box_games("nba", "Mikal Bridges", "2026-11-12")
    assert got == expected and [g["PTS"] for g in got[0]] == [30.0]


def test_every_player_in_the_production_sliced_fixture_matches_the_walk(monkeypatch):
    """The real 2026-09-17 WNBA box files: every name in them, the index against the walk."""
    monkeypatch.setenv("SYNDICATE_DATA_ROOT", str(FIXTURE_ROOT))
    names = set()
    for path in (FIXTURE_ROOT / "wnba_source").rglob("boxscores*.csv"):
        with path.open(encoding="utf-8", newline="") as handle:
            names.update(str(row.get("PLAYER_NAME") or "").strip() for row in csv.DictReader(handle))
    names.discard("")
    assert len(names) >= 25  # 30 players in the 2026-09-17 slice
    expected = {name: _walk("wnba", name, "2026-09-17", monkeypatch) for name in sorted(names)}
    with C.build_read_cache({}) as cache:
        got = {name: bb._box_games("wnba", name, "2026-09-17") for name in sorted(names)}
        assert sum(1 for key in cache if key[0] == "box_index") == 1  # built once, read for every name
    assert got == expected
    assert sum(1 for games, _ in got.values() if games) >= 25


def test_the_index_is_built_once_per_read_cache_and_the_walk_reads_every_call(nba_root, monkeypatch):
    reads = []
    real = C.iter_csv

    def counting(path):
        reads.append(Path(path).name)
        return real(path)

    monkeypatch.setattr(C, "iter_csv", counting)
    with C.build_read_cache({}):
        for name in ("Jalen Brunson", "Tyler Herro", "Coby White"):
            bb._box_games("nba", name, "2026-11-12")
    on = len(reads)
    reads.clear()
    monkeypatch.setenv("SYNDICATE_PROP_EVIDENCE_BOX_INDEX", "off")
    with C.build_read_cache({}):
        for name in ("Jalen Brunson", "Tyler Herro", "Coby White"):
            bb._box_games("nba", name, "2026-11-12")
    off = len(reads)
    assert on == 4 and off == 12  # 4 sources: once each, vs once each per call


def test_no_read_cache_means_no_index_kept(nba_root):
    """An Ask click (no build) keeps nothing across calls, as before."""
    games, _ = bb._box_games("nba", "Jalen Brunson", "2026-11-12")
    assert C._READ_CACHE.get() is None and [g["date"] for g in games][:1] == ["2026-11-09"]


def test_a_rewritten_source_is_read_again(nba_root):
    with C.build_read_cache({}) as cache:
        before, _ = bb._box_games("nba", "Coby White", "2026-11-12")
        _write_box(nba_root / "boxscores_2026-11-09.csv", [
            _box("2026-11-09", "g5", "CHI", "Coby White", pts="17"),
            _box("2026-11-09", "g5", "NYK", "Jalen Brunson Jr", pts="22"),
            _box("2026-11-10", "g6", "CHI", "Coby White", pts="28"),
        ])
        stamp = os.stat(nba_root / "boxscores_2026-11-09.csv")
        os.utime(nba_root / "boxscores_2026-11-09.csv", ns=(stamp.st_atime_ns, stamp.st_mtime_ns + 10_000_000))
        after, _ = bb._box_games("nba", "Coby White", "2026-11-12")
        assert sum(1 for key in cache if key[0] == "box_index") == 2
    assert [g["date"] for g in before] == ["2026-11-09"]
    assert [(g["date"], g["PTS"]) for g in after] == [("2026-11-10", 28.0), ("2026-11-09", 17.0)]


# --- the overlay's build context ------------------------------------------------------------------------


@pytest.fixture()
def fake_chain(monkeypatch):
    from syndicate.features.shared import layer2_board

    seen = {}

    def build(rows):
        return {"opportunities": [{"event_id": r["event_id"], "market": "player_points", "kind": "prop"} for r in rows]}

    def select(opps):
        return {"rows": list(opps)}

    def cards(rows, openings=None, price_trail=None, row_context=None, openings_by_line=None):
        seen.setdefault("contexts", []).append(row_context)
        if row_context is not None:
            row_context["recent_matchup"]["spent"]["nba"] = 7.5
        return [{"sport": "nba", "event_id": r["event_id"], "source": "layer2_shortlist"} for r in rows]

    monkeypatch.setattr(layer2_board, "build_layer2_rows", build)
    monkeypatch.setattr(layer2_board, "select_shortlist", select)
    monkeypatch.setattr(layer2_board, "layer2_rows_to_board_cards", cards)
    return seen


def test_the_overlay_passes_one_build_context_with_its_own_budget(fake_chain):
    overlay = bga.build_inplay_overlay("nba", "2026-11-11", [{"event_id": "e1"}, {"event_id": "e2"}])
    [context] = fake_chain["contexts"]
    assert context["selected_date"] == "2026-11-11"
    assert context["recent_matchup_budget_seconds"] == 20.0
    assert context["recent_matchup"]["read_cache"] == {} or isinstance(context["recent_matchup"]["read_cache"], dict)
    assert len(overlay["cards"]) == 2 and overlay["cards"][0]["source"] == "layer2_inplay_overlay"
    assert overlay["timings"]["evidence_s"] == 7.5 and overlay["timings"]["evidence_budget_s"] == 20.0
    assert {"rows_ms", "shortlist_ms", "cards_ms"} <= set(overlay["timings"])


def test_each_build_gets_a_fresh_context(fake_chain):
    bga.build_inplay_overlay("nba", "2026-11-11", [{"event_id": "e1"}])
    bga.build_inplay_overlay("nba", "2026-11-11", [{"event_id": "e1"}])
    first, second = fake_chain["contexts"]
    assert first is not second and first["recent_matchup"]["read_cache"] is not second["recent_matchup"]["read_cache"]


def test_the_budget_is_tunable(fake_chain, monkeypatch):
    monkeypatch.setenv("SYNDICATE_INPLAY_OVERLAY_EVIDENCE_SECONDS", "45")
    bga.build_inplay_overlay("nba", "2026-11-11", [{"event_id": "e1"}])
    assert fake_chain["contexts"][0]["recent_matchup_budget_seconds"] == 45.0


def test_off_restores_the_bare_call(fake_chain, monkeypatch):
    monkeypatch.setenv("SYNDICATE_INPLAY_OVERLAY_BUILD_CONTEXT", "off")
    overlay = bga.build_inplay_overlay("nba", "2026-11-11", [{"event_id": "e1"}])
    assert fake_chain["contexts"] == [None]
    assert overlay["timings"]["evidence_s"] is None


def test_the_overlay_log_line_carries_the_phases(fake_chain, capsys, monkeypatch, tmp_path):
    monkeypatch.setenv("SYNDICATE_DATA_ROOT", str(tmp_path))
    monkeypatch.setattr(bga, "_publish_inplay_overlay", lambda path: True)
    row = {"event_id": "e1", "game": {"state": "live"}, "seen_age_seconds": 10}
    bga._write_inplay_overlay_best_effort("nba", "2026-11-11", {"generated_at": "G", "rows": [row]})
    line = [l for l in capsys.readouterr().out.splitlines() if "INPLAY_OVERLAY sport=nba" in l][0]
    assert "cards=1" in line and "evidence_s=7.5" in line and "cards_ms=" in line and "rows_ms=" in line


# --- the per-build budget in row_recent_matchup_text ----------------------------------------------------


@pytest.fixture()
def counted_text(monkeypatch):
    import syndicate.features.intelligence_recent_matchup as irm

    calls = []

    def text(row, *, selected_date, memo=None):
        calls.append(selected_date)
        return "Recent form: x"

    monkeypatch.setattr(irm, "prop_recent_matchup_text", text)
    rc._RECENT_MATCHUP_TEXT.clear()
    return calls


PROP = {"sport": "nba", "kind": "prop", "player_name": "Jalen Brunson", "market": "player_points", "line": 26.5,
        "side": "over", "home_team": "New York Knicks", "away_team": "Boston Celtics",
        "commence_time": "2026-11-12T00:30:00Z"}


def test_a_context_budget_overrides_the_table(counted_text):
    context = {"selected_date": "2026-11-11", "recent_matchup": {"read_cache": {}, "spent": {"nba": 25.0}, "logged": set()},
               "recent_matchup_budget_seconds": 20.0}
    assert rc.row_recent_matchup_text(PROP, context) is None and counted_text == []  # 25 >= 20: spent
    context["recent_matchup_budget_seconds"] = None  # absent: the table's 60 s
    assert rc.row_recent_matchup_text(PROP, context) == "Recent form: x" and counted_text == ["2026-11-11"]


@pytest.mark.parametrize("bad", [0, -5, True, "20"])
def test_a_bad_budget_is_ignored(counted_text, bad):
    context = {"selected_date": "2026-11-11", "recent_matchup": {"read_cache": {}, "spent": {"nba": 25.0}, "logged": set()},
               "recent_matchup_budget_seconds": bad}
    assert rc.row_recent_matchup_text(PROP, context) == "Recent form: x"  # the table's 60 s, 25 spent


def test_with_a_context_the_budget_does_not_restart_with_the_minute(counted_text, monkeypatch):
    """The bare call's state is keyed on the wall-clock minute; a build context's is not."""
    import time as _time

    context = {"selected_date": "2026-11-11", "recent_matchup": {"read_cache": {}, "spent": {"nba": 20.0}, "logged": set()},
               "recent_matchup_budget_seconds": 20.0}
    clock = [1_000_000.0]
    monkeypatch.setattr(_time, "time", lambda: clock[0])
    assert rc.row_recent_matchup_text(PROP, context) is None
    clock[0] += 120
    assert rc.row_recent_matchup_text(PROP, context) is None and counted_text == []


# --- option (c): a slow sport's slower schedule in the book-grid tick (user 2026-11-13 "Slower NBA schedule") --

import importlib.util as _ilu
from datetime import datetime as _dt, timezone as _tz
from unittest.mock import patch as _patch

_SPEC = _ilu.spec_from_file_location(
    "run_refresh_worker_slow_sport", Path(__file__).resolve().parent.parent / "scripts" / "run_refresh_worker.py"
)
worker = _ilu.module_from_spec(_SPEC)
_SPEC.loader.exec_module(worker)

TODAY = "2026-11-11"
T0 = _dt(2026, 11, 12, 0, 10, tzinfo=_tz.utc).timestamp()
LIVE = {"rows": [{"game": {"state": "live"}, "commence_time": "2026-11-12T00:00:00Z"}], "rows_total": 1}
SLOW_ENV = ("SYNDICATE_BOOK_GRID_SLOW_SPORT_SCHEDULE", "SYNDICATE_BOOK_GRID_SLOW_SPORT_SECONDS",
            "SYNDICATE_BOOK_GRID_PRICE_ON_PULL", "SYNDICATE_BOOK_GRID_SKIP_NONLIVE_SPORTS",
            "SYNDICATE_BOOK_GRID_REFRESH_INTERVAL_SECONDS")


@pytest.fixture()
def tick(tmp_path, monkeypatch):
    """Drive the REAL `_run_book_grid_artifact_tick` (the price-on-pull tests' harness) with a build clock
    that advances by each sport's build time: NBA 90 s (the 11-11 overlay: 94-234 s), NCAAB 3 s."""
    worker._BOOK_GRID_LAST_RUN.clear()
    worker._BOOK_GRID_SPORT_STATE.clear()
    for name in SLOW_ENV:
        monkeypatch.delenv(name, raising=False)
    shard = tmp_path / f"{TODAY}.jsonl"
    shard.write_text("{}\n", encoding="utf-8")
    clock = [1000.0]
    durations = {"nba": 90.0, "ncaab": 3.0}
    monkeypatch.setattr(worker, "_book_grid_build_clock", lambda: clock[0])
    history = []

    def run(k: int, payloads=None):
        built = []
        payloads = payloads or {"nba": LIVE, "ncaab": LIVE}

        def build(sport, day):
            if day != TODAY or sport not in payloads:
                return None
            built.append(sport)
            clock[0] += durations.get(sport, 1.0)
            return payloads[sport]

        with _patch.object(worker.time, "time", return_value=T0 + 130 * k), \
             _patch.object(worker, "central_today_iso", return_value=TODAY), \
             _patch.object(worker, "_book_grid_forward_days", return_value=0), \
             _patch.object(worker, "_book_grid_refresh_interval_seconds", return_value=120), \
             _patch("syndicate.features.shared.book_grid_artifact.build_book_grid_artifact", side_effect=build), \
             _patch("syndicate.features.shared.book_grid_artifact.write_book_grid_artifact", return_value=shard), \
             _patch("syndicate.features.shared.artifact_publisher.publish_hot_artifact", return_value=None), \
             _patch("syndicate.features.shared.artifact_publisher.pull_streamed_artifact", return_value=None), \
             _patch("syndicate.features.shared.odds_book_quotes.book_quotes_path", return_value=shard), \
             _patch("syndicate.features.shared.refresh_state_store.data_root", return_value=tmp_path):
            meta = worker._run_book_grid_artifact_tick()
        history.append((built, meta))
        return built, meta

    run.durations = durations
    return run


def test_a_slow_sport_is_built_every_other_tick_and_the_others_every_tick(tick):
    built = [tick(k)[0] for k in range(1, 6)]
    assert [("nba" in b, "ncaab" in b) for b in built] == [
        (True, True), (False, True), (True, True), (False, True), (True, True)]
    _, meta = tick(6)
    assert meta["deferred_slow"] == ["nba"] and meta["build_seconds"] == {"ncaab": 3.0}


def test_the_tick_reports_build_seconds_and_the_skip(tick):
    _, first = tick(1)
    assert first["build_seconds"] == {"nba": 90.0, "ncaab": 3.0} and first["deferred_slow"] == []
    assert worker._BOOK_GRID_SPORT_STATE["nba"]["build_seconds"] == 90.0
    _, second = tick(2)
    assert second["deferred_slow"] == ["nba"]


def test_off_restores_every_due_sport_every_tick(tick, monkeypatch):
    monkeypatch.setenv("SYNDICATE_BOOK_GRID_SLOW_SPORT_SCHEDULE", "off")
    assert all("nba" in tick(k)[0] for k in range(1, 5))


def test_a_fast_sport_is_never_skipped(tick):
    tick.durations["nba"] = 20.0  # the overlay after 019b5d15d
    assert all("nba" in tick(k)[0] for k in range(1, 5))


def test_the_threshold_is_tunable(tick, monkeypatch):
    monkeypatch.setenv("SYNDICATE_BOOK_GRID_SLOW_SPORT_SECONDS", "120")
    assert all("nba" in tick(k)[0] for k in range(1, 5))
    monkeypatch.setenv("SYNDICATE_BOOK_GRID_SLOW_SPORT_SECONDS", "60")
    assert "nba" not in tick(5)[0]


def test_a_skipped_live_sport_keeps_the_live_cadence(tick):
    """NBA alone live and skipped: the next tick must stay on the live cadence."""
    tick(1, {"nba": LIVE})
    for sport in ("mlb", "wnba", "nhl", "nfl", "ncaaf", "ncaab", "wncaab", "soccer"):
        # Built recently with nothing live: not due on the live cadence, so the skip is all this tick does.
        worker._BOOK_GRID_SPORT_STATE[sport] = {"date": TODAY, "built_at": T0 + 250, "live": False, "next_start": None}
    _, meta = tick(2, {"nba": LIVE})
    assert meta is not None, "a tick whose only act is the skip must still report it"
    assert meta["deferred_slow"] == ["nba"] and meta["written"] == [] and meta["skipped_no_shard"] == []
    assert worker._BOOK_GRID_LAST_RUN["any_live"] is True


def test_a_slow_sport_never_takes_price_on_pull(tick, tmp_path):
    tick(1)
    later = tmp_path / f"{TODAY}.jsonl"
    stamp = T0 + 130 + 60
    os.utime(later, (stamp, stamp))
    with _patch("syndicate.features.shared.odds_book_quotes.book_quotes_path", return_value=later):
        assert worker._book_grid_sports_with_new_live_quotes(TODAY, stamp + 30) == ["ncaab"]
        worker._BOOK_GRID_SPORT_STATE["nba"]["build_seconds"] = 20.0
        assert worker._book_grid_sports_with_new_live_quotes(TODAY, stamp + 30) == ["nba", "ncaab"]
