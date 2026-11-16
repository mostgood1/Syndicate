"""The in-play overlay checks each file once per BUILD (todo #790, lane nba-overlay-card-cost, user "Check once per
build", 2026-11-16).

Measured offline on the 11-16 NBA grid: a warm 2,000-card overlay build made 47,565 stat and 2,376 scandir calls,
almost all per-card re-checks of things that do not change inside a build -- the data root's `resolve()` behind
the calibration profile path, the NBA odds root's `resolve()`, the calibration profile's stat signature, the
closing-line files' stat, the team-results glob and stat. On refresh-worker each one is a GIL hand-off to the busy
board loop; beside one busy thread the build took 139.9 s against 3.6 s alone, and 6.1 s with each path answered
once per build, with the same cards.

These tests pin, for each of those sites: inside a scope it answers exactly what it answers outside one, and
computes once per build instead of once per call; outside a scope nothing changed. Then the reachability test
(off != on): `build_inplay_overlay` opens the scope, its cards are identical either way, and its timings say
which branch ran.
"""
from __future__ import annotations

import csv
import os
import threading

import pytest

from syndicate.features.shared import book_grid_artifact as bga
from syndicate.features.shared import build_lookup_scope as bls
from syndicate.features.shared import closing_line_history as clh
from syndicate.features.shared import odds_control_plane as ocp
from syndicate.features.shared import probability_calibration as pc
from syndicate.features.shared import refresh_state_store as rss
from syndicate.features.shared import team_recent_results as trr


@pytest.fixture(autouse=True)
def _env(monkeypatch, tmp_path):
    monkeypatch.delenv(bls.FLAG, raising=False)
    monkeypatch.setenv("SYNDICATE_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("SYNDICATE_NBA_SOURCE_ROOT", str(tmp_path / "nba_source"))
    clh._CACHE.clear()
    trr._CACHE.clear()
    pc.clear_profile_cache()
    yield
    clh._CACHE.clear()
    trr._CACHE.clear()
    pc.clear_profile_cache()


def _counter(monkeypatch, module, name):
    count = {"n": 0}
    real = getattr(module, name)

    def counting(*args, **kwargs):
        count["n"] += 1
        return real(*args, **kwargs)

    monkeypatch.setattr(module, name, counting)
    return count


# --------------------------------------------------------------------------------------------------------------
# The scope's own counters and stat
# --------------------------------------------------------------------------------------------------------------


def test_scope_counts_computes_and_reuses_and_is_none_outside():
    assert bls.scope_counts() is None
    with bls.lookup_scope():
        assert bls.scope_counts() == (0, 0)
        for key in ["a", "b", "a", "a"]:
            bls.scoped_lookup("ns", key, lambda key=key: key.upper())
        assert bls.scope_counts() == (2, 2)
    assert bls.scope_counts() is None


def test_scope_counts_is_none_when_switched_off(monkeypatch):
    monkeypatch.setenv(bls.FLAG, "off")
    with bls.lookup_scope():
        assert bls.scope_counts() is None


def test_stat_signature_once_per_build_and_fresh_after(monkeypatch, tmp_path):
    path = tmp_path / "f.json"
    path.write_text("{}", encoding="utf-8")
    real = bls._stat_signature_now(os.fspath(path))
    calls = _counter(monkeypatch, bls, "_stat_signature_now")
    with bls.lookup_scope():
        answers = [bls.scoped_stat_signature(path) for _ in range(5)]
        path.write_text('{"rewritten": true}', encoding="utf-8")  # mid-build: this build keeps its first answer
        answers.append(bls.scoped_stat_signature(str(path)))  # str and Path are the same key
    assert answers == [real] * 6 and calls["n"] == 1
    fresh = bls.scoped_stat_signature(path)  # the next ask outside a scope sees the rewrite
    assert fresh == (os.stat(path).st_mtime_ns, os.stat(path).st_size) and fresh[1] == len('{"rewritten": true}')
    bls.scoped_stat_signature(path)
    assert calls["n"] == 3  # outside a scope: every call stats


def test_an_absent_file_is_none_inside_and_outside(monkeypatch, tmp_path):
    missing = tmp_path / "nope.json"
    calls = _counter(monkeypatch, bls, "_stat_signature_now")
    with bls.lookup_scope():
        assert [bls.scoped_stat_signature(missing) for _ in range(3)] == [None, None, None]
    assert calls["n"] == 1
    assert bls.scoped_stat_signature(missing) is None


# --------------------------------------------------------------------------------------------------------------
# Each site: the same answer, once per build
# --------------------------------------------------------------------------------------------------------------


def test_data_root_same_answer_resolved_once_per_build(tmp_path):
    outside = [rss.data_root() for _ in range(3)]
    assert outside[0] == tmp_path.resolve()
    assert outside[0] is not outside[1]  # outside a scope: resolved on every call, as before
    with bls.lookup_scope():
        inside = [rss.data_root() for _ in range(3)]
    assert inside[0] == outside[0] and inside[0] is inside[1] is inside[2]


def test_data_root_follows_the_env_inside_a_scope(monkeypatch, tmp_path):
    other = tmp_path / "other"
    other.mkdir()
    with bls.lookup_scope():
        first = rss.data_root()
        monkeypatch.setenv("SYNDICATE_DATA_ROOT", str(other))
        assert rss.data_root() == other.resolve() != first


def test_the_scope_is_private_to_the_build_thread():
    seen = []
    with bls.lookup_scope():
        main = rss.data_root()

        def board_loop():
            seen.append((bls.lookup_scope_active(), rss.data_root(), rss.data_root()))

        t = threading.Thread(target=board_loop)
        t.start()
        t.join()
        assert rss.data_root() is main
    [(active, a, b)] = seen
    assert active is False and a == main and a is not b  # the other thread resolves every call, as before


def test_odds_root_same_answer_resolved_once_per_build():
    outside = [ocp.current_odds_root_for_sport("nba") for _ in range(2)]
    assert outside[0] is not outside[1]
    with bls.lookup_scope():
        inside = [ocp.current_odds_root_for_sport(" NBA ") for _ in range(3)]
        nhl = ocp.current_odds_root_for_sport("nhl")
    assert inside[0] == outside[0] and inside[0] is inside[1] is inside[2]
    assert nhl == ocp.current_odds_root_for_sport("nhl") != inside[0]


def test_an_unsupported_sport_still_raises_inside_a_scope():
    with bls.lookup_scope():
        for _ in range(2):
            with pytest.raises(ValueError):
                ocp.current_odds_root_for_sport("cricket")


def test_calibration_profile_stat_once_per_build(monkeypatch, tmp_path):
    path = pc.profile_path("nba")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"version": "x", "profile": {}}', encoding="utf-8")
    outside = pc.cached_profile("nba")
    calls = _counter(monkeypatch, bls, "_stat_signature_now")
    with bls.lookup_scope():
        inside = [pc.cached_profile("nba") for _ in range(4)]
    assert calls["n"] == 1
    assert all(i[0] is outside[0] for i in inside)  # same cached profile object: nothing re-parsed
    pc.cached_profile("nba")
    pc.cached_profile("nba")
    assert calls["n"] == 3


_COLS = ["closing_line", "closing_price", "line", "market", "player_name", "segment", "selection", "sport"]


def _closing(root, day, rows):
    folder = root / "settlement_inputs"
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / f"closing_lines_{day}.csv").open("w", encoding="utf-8", newline="") as handle:
        w = csv.DictWriter(handle, fieldnames=_COLS)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def test_closing_lines_stat_once_per_day_per_build(monkeypatch, tmp_path):
    for day, line in (("2026-11-10", "24.5"), ("2026-11-12", "26.5")):
        _closing(tmp_path, day, [{"sport": "nba", "player_name": "Coby White", "market": "player_points",
                                  "closing_line": line, "line": line, "closing_price": "-110", "selection": "over",
                                  "segment": "full"}])
    dates = ["2026-11-10", "2026-11-11", "2026-11-12"]
    outside = clh.past_main_lines("nba", "Coby White", "player_points", dates)
    assert outside == [24.5, None, 26.5]
    calls = _counter(monkeypatch, bls, "_stat_signature_now")
    with bls.lookup_scope():
        inside = [clh.past_main_lines("nba", player, "player_points", dates)
                  for player in ["Coby White", "Jalen Brunson", "Coby White", "Coby White"]]
    assert inside[0] == inside[2] == inside[3] == outside and inside[1] == [None, None, None]
    assert calls["n"] == 3  # one per day's file (the absent one included), not one per card per day


def _game_log(root, rows):
    folder = root / "nba_source" / "data" / "processed"
    folder.mkdir(parents=True, exist_ok=True)
    cols = ["game_id", "TEAM_ABBREVIATION", "season_type", "PTS", "date"]
    with (folder / "player_game_log_2026.csv").open("w", encoding="utf-8", newline="") as handle:
        w = csv.DictWriter(handle, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow(dict(zip(cols, r)))


def test_team_results_listing_and_stat_once_per_build(monkeypatch, tmp_path):
    _game_log(tmp_path, [("g1", "CHI", "regular", "60", "2026-11-08"), ("g1", "NYK", "regular", "50", "2026-11-08"),
                         ("g1", "CHI", "regular", "45", "2026-11-08"), ("g1", "NYK", "regular", "52", "2026-11-08"),
                         ("g2", "CHI", "regular", "99", "2026-11-10"), ("g2", "BOS", "regular", "101", "2026-11-10")])
    outside = trr.team_recent_results("nba", "CHI", "2026-11-12")
    assert outside == [["2026-11-10", 99.0, 101.0], ["2026-11-08", 105.0, 102.0]]
    listings = _counter(monkeypatch, trr, "_sources")
    stats = _counter(monkeypatch, bls, "_stat_signature_now")
    with bls.lookup_scope():
        inside = [trr.team_recent_results("nba", team, "2026-11-12") for team in ["CHI", "NYK", "CHI", "BOS"]]
    assert inside[0] == inside[2] == outside
    assert inside[1] == [["2026-11-08", 102.0, 105.0]] and inside[3] == [["2026-11-10", 101.0, 99.0]]
    assert listings["n"] == 1 and stats["n"] == 1
    trr.team_recent_results("nba", "CHI", "2026-11-12")
    trr.team_recent_results("nba", "CHI", "2026-11-12")
    assert listings["n"] == 3 and stats["n"] == 3  # outside a scope: every call lists and stats, as before


# --------------------------------------------------------------------------------------------------------------
# Reachability: the overlay build opens the scope (off != on), with identical cards
# --------------------------------------------------------------------------------------------------------------


@pytest.fixture()
def checking_chain(monkeypatch, tmp_path):
    """A card builder that makes the real per-card checks the overlay's cards make, three per card."""
    from syndicate.features.shared import layer2_board

    path = pc.profile_path("nba")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"version": "x", "profile": {}}', encoding="utf-8")
    seen = {"active": []}

    def build(rows):
        return {"opportunities": [{"event_id": r["event_id"], "market": "player_points", "kind": "prop"} for r in rows]}

    def select(opps):
        return {"rows": list(opps)}

    def cards(rows, openings=None, price_trail=None, row_context=None, openings_by_line=None):
        out = []
        for r in rows:
            seen["active"].append(bls.lookup_scope_active())
            root = rss.data_root()
            odds = ocp.current_odds_root_for_sport("nba")
            profile, _ = pc.cached_profile("nba")
            out.append({"sport": "nba", "event_id": r["event_id"], "root": str(root), "odds": str(odds),
                        "profile": profile.version})
        return out

    monkeypatch.setattr(layer2_board, "build_layer2_rows", build)
    monkeypatch.setattr(layer2_board, "select_shortlist", select)
    monkeypatch.setattr(layer2_board, "layer2_rows_to_board_cards", cards)
    return seen


ROWS = [{"event_id": f"e{i}"} for i in range(40)]


def test_the_overlay_build_checks_once_per_build_off_differs_from_on(checking_chain, monkeypatch):
    stats = _counter(monkeypatch, bls, "_stat_signature_now")
    on = bga.build_inplay_overlay("nba", "2026-11-16", ROWS)
    on_stats = stats["n"]
    assert set(checking_chain["active"]) == {True}
    assert on["timings"]["lookups_resolved"] == 3  # data root, odds root, profile stat: once each
    # each card asks the data root twice (its own ask and the profile path's), the odds root and the stat; the
    # first card's profile load (a cache miss) asks for the profile path once more
    assert on["timings"]["lookups_reused"] == 4 * len(ROWS) - 3 + 1
    assert "lookup_scope" not in on["timings"]
    assert on_stats == 1

    checking_chain["active"].clear()
    monkeypatch.setenv(bls.FLAG, "off")
    off = bga.build_inplay_overlay("nba", "2026-11-16", ROWS)
    assert set(checking_chain["active"]) == {False}
    assert off["timings"]["lookup_scope"] == "off"
    assert "lookups_resolved" not in off["timings"] and "lookups_reused" not in off["timings"]
    assert stats["n"] - on_stats == len(ROWS)  # off: one stat per card, as before

    strip = lambda o: [{k: v for k, v in c.items() if k != "price_grid_generated_at"} for c in o["cards"]]  # noqa: E731
    assert strip(on) == strip(off) and len(on["cards"]) == len(ROWS)


def test_each_overlay_build_gets_its_own_scope(checking_chain, monkeypatch, tmp_path):
    stats = _counter(monkeypatch, bls, "_stat_signature_now")
    bga.build_inplay_overlay("nba", "2026-11-16", ROWS[:5])
    pc.profile_path("nba").write_text('{"version": "y", "profile": {}, "pad": "changes the size"}', encoding="utf-8")
    second = bga.build_inplay_overlay("nba", "2026-11-16", ROWS[:5])
    assert stats["n"] == 2  # the next build looks again
    assert second["timings"]["lookups_resolved"] == 3 and bls.lookup_scope_active() is False


def test_the_overlay_line_prints_which_branch_ran(checking_chain, monkeypatch, capsys):
    monkeypatch.setattr(bga, "write_book_grid_inplay_overlay", lambda sport, day, overlay: bga.Path("x"))
    monkeypatch.setattr(bga, "_publish_inplay_overlay", lambda path: True)
    monkeypatch.setattr(bga, "inplay_overlay_enabled", lambda: True)
    monkeypatch.setattr(bga, "select_inplay_rows", lambda rows: list(rows or []))
    bga._write_inplay_overlay_best_effort("nba", "2026-11-16", {"rows": ROWS[:4], "generated_at": "t"})
    monkeypatch.setenv(bls.FLAG, "off")
    bga._write_inplay_overlay_best_effort("nba", "2026-11-16", {"rows": ROWS[:4], "generated_at": "t"})
    on_line, off_line = [ln for ln in capsys.readouterr().out.splitlines() if "INPLAY_OVERLAY sport=nba" in ln]
    assert "lookups_resolved=3 lookups_reused=14" in on_line and "lookup_scope" not in on_line
    assert "lookup_scope=off" in off_line and "lookups_" not in off_line
