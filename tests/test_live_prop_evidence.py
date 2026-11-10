"""Phase 1B M1, live stat progress: the live props evidence log (lane `live-props-evidence`, 2026-11-10).

The round trip runs on rows from NBA's own producer (`nba/live_resim.build_live_props`), with neighbour lines, a pulled
line, a certainty refusal and the double-double / triple-double rows, so the test covers the shapes the fleet
publishes rather than a hand-written imitation of them."""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone

import pytest

from syndicate.features.nba import live_resim as lr
from syndicate.features.shared import live_evidence_log as lel
from syndicate.features.shared import live_prop_evidence as lpe

NOW = datetime(2026, 11, 11, 2, 0, 30, tzinfo=timezone.utc)


def _canon_multiset(rows):
    return Counter(json.dumps(r, sort_keys=True) for r in rows)


def _nba_live_props():
    name = "LeBron James"
    nk = lr.normalize_name(name)
    other = "Austin Reaves"
    ok = lr.normalize_name(other)
    result = {
        "sims_run": 400,
        "player_remainders": {
            "home": {
                name: {"pts": {"0": 40, "4": 160, "8": 140, "14": 60}, "reb": {"0": 100, "3": 200, "6": 100},
                       "ast": {"1": 200, "4": 200}, "pr": {"3": 200, "10": 200},
                       lr.DOUBLES_JOINT_KEY: {"0,0,0,0,0": 150, "4,3,1,0,0": 150, "10,6,4,1,0": 100}},
            },
            "away": {
                other: {"pts": {"0": 100, "6": 300}, "threes": {"0": 250, "1": 150}},
            },
        },
    }
    actuals = {nk: {"pts": 21, "reb": 6, "ast": 7, "threes": 2, "stl": 1, "blk": 0, "tov": 3},
               ok: {"pts": 9, "reb": 2, "ast": 1, "threes": 1, "stl": 0, "blk": 0, "tov": 1}}
    lines = lr.with_neighbour_lines({(nk, "pts"): (25.5, 26.5), (nk, "reb"): 8.5, (nk, "pr"): 31.5,
                                     (nk, "dd"): 1.5, (ok, "pts"): 13.5, (ok, "threes"): 1.5})
    pulled = {(nk, "ast"): (11.5,)}
    rows, counts = lr.build_live_props(result, actuals, lines, pulled=pulled)
    assert counts["pulled_rows"] >= 1 and counts["certainty_refused"] >= 1 and counts["doubles_rows"] >= 0
    return rows, counts


def _snapshot(t: str, live_props, *, event: str = "401810001", coverage=None, refusal=None, score: int = 61,
              props_keys: bool = True) -> dict:
    game = {
        "event_id": event, "home": "LAL", "away": "SAS", "home_name": "Los Angeles Lakers",
        "away_name": "San Antonio Spurs", "status": "in_progress",
        "gameLens": [{"key": "live", "source": "live_resim", "liveStateAsOf": t, "simsRun": 400,
                      "projection": {"period": 3, "clockSeconds": 300.0, "homeScore": score, "awayScore": 58,
                                     "total": 226.5, "homeMargin": 3.1}}],
    }
    if props_keys:
        game["liveProps"] = live_props
        game["livePropsCoverage"] = coverage if coverage is not None else {"rows": len(live_props or [])}
        if refusal:
            game["livePropsRefusal"] = refusal
    return {"date": "2026-11-10", "generatedAt": t, "games": [game]}


class _Store:
    def __init__(self):
        self.snaps: dict[str, dict] = {}

    def read(self, name):
        return self.snaps.get(name)


def _collector(tmp_path, store, props=True):
    return lel.Collector(root=tmp_path, read=store.read, sports={"nba": "n.json"}, props=props)


# ---------------------------------------------------------------- switch


def test_switch_absent_is_on_and_off_turns_it_off(monkeypatch, tmp_path):
    assert lpe.enabled({}) is True
    assert lpe.enabled({lpe.PROPS_ENV: "off"}) is False
    monkeypatch.setenv(lpe.PROPS_ENV, "off")
    assert lel.Collector(root=tmp_path, read=lambda _n: None).props_on is False
    monkeypatch.delenv(lpe.PROPS_ENV)
    assert lel.Collector(root=tmp_path, read=lambda _n: None).props_on is True


# ---------------------------------------------------------------- compaction


def test_round_trip_is_lossless_on_the_nba_producers_rows():
    rows, _counts = _nba_live_props()
    entries = lpe.compact_props(rows)
    back = lpe.expand_props(json.loads(json.dumps(entries)))
    assert _canon_multiset(back) == _canon_multiset(rows)
    assert len(back) == len(rows)
    # one entry per (player, prop); the line-invariant fields are stored once
    assert len(entries) == len({(r["playerName"], r["prop"]) for r in rows})
    pts = next(e for e in entries if e["f"].get("prop") == "player_points" and e["f"]["playerName"] == "LeBron James")
    assert {"liveProjection", "actualSoFar", "simsRun", "side"} <= set(pts["f"])
    assert pts["c"][0] == "line"
    # the compact form is materially smaller than the published rows
    assert len(json.dumps(entries)) < 0.6 * len(json.dumps(rows))


def test_flags_only_some_rows_carry_survive():
    rows, _ = _nba_live_props()
    back = lpe.expand_props(lpe.compact_props(rows))
    pulled = [r for r in back if r.get("quotePulled")]
    assert pulled and all(r["liveModelProbOver"] is None and r["unpricedReason"] == "quote_pulled" for r in pulled)
    refused = [r for r in back if r.get("unpricedReason") == "certainty_refused"]
    assert refused and all(r["liveModelProbOver"] is None for r in refused)
    priced = [r for r in back if "unpricedReason" not in r]
    assert priced and all(r["liveModelProbOver"] is not None for r in priced)


def test_a_single_row_group_and_non_mapping_rows():
    entries = lpe.compact_props([{"playerName": "A", "prop": "player_points", "line": 9.5}, "junk", None])
    assert entries == [{"f": {"line": 9.5, "playerName": "A", "prop": "player_points"}, "c": [], "r": [[]]}]
    assert lpe.expand_props(entries) == [{"playerName": "A", "prop": "player_points", "line": 9.5}]


# ---------------------------------------------------------------- collector


def test_collector_writes_props_beside_the_lane_rows_and_returns_lane_counts_only(tmp_path):
    rows, _ = _nba_live_props()
    store = _Store()
    store.snaps["n.json"] = _snapshot("2026-11-10T20:00:00-06:00", rows)
    c = _collector(tmp_path, store)
    assert c.collect_once(now=NOW) == {"nba": 1}
    assert c.last_props["nba"][0] == 1 and c.last_props["nba"][1] > 0
    (prow,) = list(lpe.iter_prop_rows("nba", "2026-11-10", root=tmp_path))
    assert prow["kind"] == "props" and prow["t"] == "2026-11-10T20:00:00-06:00" and prow["event_id"] == "401810001"
    assert prow["n"] == len(rows) and prow["coverage"] == {"rows": len(rows)} and prow["refusal"] is None
    assert _canon_multiset(lpe.expand_props(prow["props"])) == _canon_multiset(rows)
    # the lane file holds lane rows only
    lane_rows = list(lel.iter_rows("nba", "2026-11-10", root=tmp_path))
    assert len(lane_rows) == 1 and "props" not in lane_rows[0]
    assert c.props_on and lpe.props_path("nba", "2026-11-10", root=tmp_path).name == "2026-11-10.props.jsonl"


def test_off_writes_no_props_and_leaves_the_lane_file_byte_identical(tmp_path):
    rows, _ = _nba_live_props()
    on_root, off_root = tmp_path / "on", tmp_path / "off"
    for root, props in ((on_root, True), (off_root, False)):
        store = _Store()
        store.snaps["n.json"] = _snapshot("2026-11-10T20:00:00-06:00", rows)
        assert lel.Collector(root=root, read=store.read, sports={"nba": "n.json"}, props=props).collect_once(now=NOW) == {"nba": 1}
    assert lpe.props_path("nba", "2026-11-10", root=on_root).exists()
    assert not lpe.props_path("nba", "2026-11-10", root=off_root).exists()
    assert (lel.log_path("nba", "2026-11-10", root=on_root).read_bytes()
            == lel.log_path("nba", "2026-11-10", root=off_root).read_bytes())


def test_unchanged_props_on_a_new_tick_are_not_rewritten(tmp_path):
    rows, _ = _nba_live_props()
    store = _Store()
    c = _collector(tmp_path, store)
    store.snaps["n.json"] = _snapshot("2026-11-10T20:00:00-06:00", rows)
    c.collect_once()
    store.snaps["n.json"] = _snapshot("2026-11-10T20:02:30-06:00", rows, score=63)  # lane moved, props did not
    assert c.collect_once() == {"nba": 1}
    assert c.last_props == {}
    changed = [dict(r, liveProjection=r["liveProjection"] + 1.0) for r in rows]
    store.snaps["n.json"] = _snapshot("2026-11-10T20:05:00-06:00", changed, score=65)
    c.collect_once()
    got = list(lpe.iter_prop_rows("nba", "2026-11-10", root=tmp_path))
    assert [r["t"] for r in got] == ["2026-11-10T20:00:00-06:00", "2026-11-10T20:05:00-06:00"]


def test_props_that_go_away_get_one_clearing_row(tmp_path):
    rows, _ = _nba_live_props()
    store = _Store()
    c = _collector(tmp_path, store)
    store.snaps["n.json"] = _snapshot("2026-11-10T20:00:00-06:00", rows)
    c.collect_once()
    store.snaps["n.json"] = _snapshot("2026-11-10T20:02:30-06:00", None, props_keys=False)
    c.collect_once()
    store.snaps["n.json"] = _snapshot("2026-11-10T20:05:00-06:00", None, props_keys=False, score=70)
    c.collect_once()
    got = list(lpe.iter_prop_rows("nba", "2026-11-10", root=tmp_path))
    assert [(r["t"], r["n"]) for r in got] == [("2026-11-10T20:00:00-06:00", len(rows)), ("2026-11-10T20:02:30-06:00", 0)]
    assert got[1]["props"] == []


def test_a_game_that_never_had_props_writes_nothing(tmp_path):
    store = _Store()
    c = _collector(tmp_path, store)
    store.snaps["n.json"] = _snapshot("2026-11-10T20:00:00-06:00", None, props_keys=False)
    assert c.collect_once() == {"nba": 1}
    assert not lpe.props_path("nba", "2026-11-10", root=tmp_path).exists()


def test_a_size_refusal_is_kept(tmp_path):
    store = _Store()
    c = _collector(tmp_path, store)
    store.snaps["n.json"] = _snapshot("2026-11-10T20:00:00-06:00", [], refusal="props_over_size_budget",
                                      coverage={"rows": 0})
    c.collect_once()
    (row,) = list(lpe.iter_prop_rows("nba", "2026-11-10", root=tmp_path))
    assert row["n"] == 0 and row["refusal"] == "props_over_size_budget"


def test_a_failed_write_is_retried_on_the_next_tick_and_never_stops_the_lane_rows(tmp_path, monkeypatch, capsys):
    rows, _ = _nba_live_props()
    store = _Store()
    c = _collector(tmp_path, store)
    real = lpe.append_rows
    calls = {"n": 0}

    def flaky(*a, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("disk full")
        return real(*a, **kw)

    monkeypatch.setattr(lpe, "append_rows", flaky)
    store.snaps["n.json"] = _snapshot("2026-11-10T20:00:00-06:00", rows)
    assert c.collect_once() == {"nba": 1}
    assert "PROPS_FAILED sport=nba OSError" in capsys.readouterr().out
    assert not lpe.props_path("nba", "2026-11-10", root=tmp_path).exists()
    store.snaps["n.json"] = _snapshot("2026-11-10T20:02:30-06:00", rows, score=63)
    assert c.collect_once() == {"nba": 1}
    got = list(lpe.iter_prop_rows("nba", "2026-11-10", root=tmp_path))
    assert [r["t"] for r in got] == ["2026-11-10T20:02:30-06:00"]
    assert len(list(lel.iter_rows("nba", "2026-11-10", root=tmp_path))) == 2


def test_an_oversize_row_drops_its_props_and_says_so(tmp_path, monkeypatch):
    rows, _ = _nba_live_props()
    monkeypatch.setattr(lpe, "ROW_MAX_BYTES", 500)
    row = lpe.game_prop_row("nba", "2026-11-10", "2026-11-10T20:00:00-06:00", "x", _snapshot("t", rows)["games"][0])
    assert row["props"] == [] and row["dropped"] == ["props"] and row["n"] == len(rows)


def test_a_non_list_live_props_is_named_not_guessed():
    game = _snapshot("t", {"weird": 1})["games"][0]
    row = lpe.game_prop_row("nba", "2026-11-10", "t", "x", game)
    assert row["n"] == 0 and row["props"] == [] and row["props_type"] == "dict"


# ---------------------------------------------------------------- reading back


def test_props_at_uses_the_producer_time_and_skips_a_torn_line(tmp_path):
    rows, _ = _nba_live_props()
    store = _Store()
    c = _collector(tmp_path, store)
    store.snaps["n.json"] = _snapshot("2026-11-10T20:00:00-06:00", rows)
    c.collect_once(now=datetime(2026, 11, 11, 2, 9, 0, tzinfo=timezone.utc))  # observed 9 min late
    store.snaps["n.json"] = _snapshot("2026-11-10T20:05:00-06:00", rows[:3], score=65)
    c.collect_once()
    path = lpe.props_path("nba", "2026-11-10", root=tmp_path)
    with path.open("a", encoding="utf-8") as fh:
        fh.write('{"v":1,"kind":"props","t":"2026-11-10T20:0')  # a torn last line
    got = list(lpe.iter_prop_rows("nba", "2026-11-10", root=tmp_path))
    assert len(got) == 2
    at_0003 = lpe.props_at(got, "2026-11-10T20:03:00-06:00")
    assert at_0003["401810001"]["n"] == len(rows)  # published at 20:00 although observed at 20:09
    assert lpe.props_at(got, "2026-11-10T20:06:00-06:00")["401810001"]["n"] == 3
    assert lpe.props_at(got, "2026-11-10T19:59:00-06:00") == {}
    with pytest.raises(ValueError):
        lpe.props_at(got, "not a time")
