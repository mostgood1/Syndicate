"""WNBA SEGMENT game lines grade off the quarter linescore, not the final.

Before this, `bet_status_wnba` refused every non-`full` segment with
`final_box_is_full_game_not_<seg>` -- correct, and permanent, because the only
artifact settlement read was the whole-game player box. The quarter linescore
is in the SAME ESPN summary that box is built from; `build_wnba_boxscores` now
writes it beside the CSV as `linescores_<date>.json`, and the resolver grades
`q1..q4` / `h1` / `h2` totals, spreads and moneylines off it.

The refusal is kept as the FALLBACK and these tests pin both directions: a
segment order with the sidecar present grades, and the very same order with
the sidecar absent refuses with the recorded wording. A full-game order never
touches the segment path at all.

Scores below are GS @ CON 2026-08-26, GS 89 / CON 64 -- the game already
verified against ESPN in `bet_status_wnba` -- split into quarters that sum to
those totals. The quarter split is a fixture, not a reading.
"""

from __future__ import annotations

import json

import pytest

from syndicate.features.shared import bet_status_wnba as mod
from syndicate.features.shared.bet_status import resolve_bet_status
from syndicate.features.shared.segment_actuals import REASON_SEGMENT_ACTUAL_PREFIX

DATE = "2026-08-26"
CON_Q = [15, 17, 14, 18]   # 64, home
GS_Q = [22, 20, 29, 18]    # 89, away


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNDICATE_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("SYNDICATE_REFRESH_STATE_BACKEND", "file")
    yield tmp_path


def _write_linescores(tmp_path, games, date=DATE):
    path = tmp_path / mod.linescores_relative_path(date)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"date": date, "source": "espn", "games": games}), encoding="utf-8")
    return path


def _gs_con_linescore(home=CON_Q, away=GS_Q, *, home_tri="CON", away_tri="GS"):
    return {
        "game_id": "401857176", "home_tri": home_tri, "away_tri": away_tri,
        "home": list(home), "away": list(away),
        "home_score": sum(v for v in home if v is not None),
        "away_score": sum(v for v in away if v is not None),
    }


def _write_final_box(tmp_path, date=DATE):
    """`boxscores_<date>.csv` as the producer writes it -- the FULL-GAME source."""
    import csv as _csv

    from scripts.build_wnba_boxscores import COLUMNS

    rows = []
    for i, pts in enumerate([25, 20, 16, 12, 8, 8]):
        rows.append({"game_id": "401857176", "gameId": "401857176",
                     "TEAM_ABBREVIATION": "GS", "PLAYER_NAME": f"GS Player {i}", "PTS": pts})
    for i, pts in enumerate([18, 14, 12, 10, 6, 4]):
        rows.append({"game_id": "401857176", "gameId": "401857176",
                     "TEAM_ABBREVIATION": "CON", "PLAYER_NAME": f"CON Player {i}", "PTS": pts})
    path = tmp_path / "wnba_source" / "data" / "processed" / f"boxscores_{date}.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = _csv.DictWriter(handle, fieldnames=list(COLUMNS), lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in COLUMNS})


def _order(**kw):
    order = {
        "sport": "wnba",
        "event_id": "a-board-hash-that-is-not-an-espn-id",
        "market": "totals",
        "side": "over",
        "line": 151.5,
        "away_team": "Golden State Valkyries",
        "home_team": "Connecticut Sun",
        "status": "filled",
        "fill_price": 0.49,
        "fill_stake_dollars": 1.95,
    }
    order.update(kw)
    return order


def _status(out, order):
    """The grader's verdict for one resolved order -- what `paper_settlement`
    computes, restated side/line and all."""
    assert out.get("unavailable_reason") is None, out
    return resolve_bet_status(
        market=order["market"],
        side=out.get("side", order.get("side")),
        line=out.get("line", order.get("line")),
        current_value=out["current_value"],
        is_final=out["is_final"],
        started=out.get("started", True),
    )


# --------------------------------------------------------------------------
# The full game is untouched.
# --------------------------------------------------------------------------


@pytest.mark.parametrize("segment_kw", [{}, {"segment": "full"}, {"segment": ""}])
def test_a_full_game_order_still_grades_off_the_final_box(_isolated, segment_kw):
    """REGRESSION. Absent, blank and `full` all mean the whole game, and the
    whole game is still read from the summed player box -- the sidecar is not
    consulted, so a slate without one grades exactly as before."""
    _write_final_box(_isolated)
    resolve = mod.wnba_status_resolver(DATE)

    out = resolve(_order(**segment_kw))
    assert out["matched_by"] == "final_boxscore_team_totals"
    assert out["current_value"] == 89 + 64
    assert "settled_segment" not in out


# --------------------------------------------------------------------------
# Segment totals.
# --------------------------------------------------------------------------


def test_a_q1_total_grades_over_under_and_push(_isolated):
    """Q1 is CON 15 / GS 22 = 37. Three lines, three verdicts, and the push is
    its own outcome -- a tie folded into the losses would understate P&L."""
    _write_linescores(_isolated, [_gs_con_linescore()])
    resolve = mod.wnba_status_resolver(DATE)

    over = _order(segment="q1", side="over", line=36.5)
    out = resolve(over)
    assert out["matched_by"] == "final_linescore_segment"
    assert out["settled_segment"] == "q1"
    assert out["current_value"] == 37
    assert out["home_score"] == 15 and out["away_score"] == 22
    assert out["is_final"] is True
    assert _status(out, over)["status"] == "won"

    under = _order(segment="q1", side="under", line=36.5)
    assert _status(resolve(under), under)["status"] == "lost"

    level = _order(segment="q1", side="over", line=37)
    tied = _status(resolve(level), level)
    assert tied["status"] == "live_tied" and tied["decided"] is True


def test_h2_includes_overtime_and_q4_does_not(_isolated):
    """The book convention this module states: a second-half market is the
    rest of the game, a fourth-quarter market is the fourth quarter."""
    home = CON_Q + [10]
    away = GS_Q + [8]
    _write_linescores(_isolated, [_gs_con_linescore(home, away)])
    resolve = mod.wnba_status_resolver(DATE)

    h2 = resolve(_order(segment="h2", side="over", line=90.5))
    assert h2["current_value"] == (14 + 18 + 10) + (29 + 18 + 8)
    q4 = resolve(_order(segment="q4", side="over", line=35.5))
    assert q4["current_value"] == 18 + 18


def test_overtime_on_one_side_only_refuses_h2_by_name(_isolated):
    """One side with five periods and the other with four is not a linescore
    this can read; refusing beats summing a smaller number that looks real."""
    _write_linescores(_isolated, [_gs_con_linescore(CON_Q + [10], GS_Q)])
    resolve = mod.wnba_status_resolver(DATE)

    out = resolve(_order(segment="h2", side="over", line=90.5))
    assert out["unavailable_reason"] == f"{REASON_SEGMENT_ACTUAL_PREFIX}h2"
    # Regulation quarters are still readable on the same game.
    assert resolve(_order(segment="q1", side="over", line=36.5))["current_value"] == 37


# --------------------------------------------------------------------------
# Segment spreads and moneylines, through `game_line_view`.
# --------------------------------------------------------------------------


def test_an_h1_spread_grades_on_the_half_margin_with_a_push(_isolated):
    """H1 is CON 32 / GS 42 -- GS (away) by 10. `-7.5` on the away side wins,
    `+7.5` on the home side loses, and `-10` on the away side pushes."""
    _write_linescores(_isolated, [_gs_con_linescore()])
    resolve = mod.wnba_status_resolver(DATE)

    for side, line, expected in (("away", -7.5, "won"), ("home", 7.5, "lost"), ("away", -10, "live_tied")):
        order = _order(market="spreads", segment="h1", side=side, line=line)
        out = resolve(order)
        assert out["settled_segment"] == "h1"
        assert out["home_score"] == 32 and out["away_score"] == 42
        status = _status(out, order)
        assert status["status"] == expected, (side, line, status)
        assert status["decided"] is True


def test_a_q1_moneyline_wins_and_loses_on_the_quarter_winner(_isolated):
    """CON 15 / GS 22 in the first quarter: away won it, home lost it -- whatever
    the full game says."""
    _write_linescores(_isolated, [_gs_con_linescore()])
    resolve = mod.wnba_status_resolver(DATE)

    for side, expected in (("away", "won"), ("home", "lost")):
        order = _order(market="h2h", segment="q1", side=side, line=None)
        assert _status(resolve(order), order)["status"] == expected, side


def test_a_tied_quarter_PUSHES_the_two_way_moneyline(_isolated):
    """Q4 is 18-18. Basketball cannot tie a GAME, but a quarter can, and the
    two-way market returns the stake. Run through `paper_settlement`'s own
    verdict so the outcome is the ledger's word for it, not the grader's."""
    from syndicate.features.shared.paper_settlement import _our_verdict

    _write_linescores(_isolated, [_gs_con_linescore()])
    resolve = mod.wnba_status_resolver(DATE)

    verdict, resolved, refusal = _our_verdict(_order(market="h2h", segment="q4", side="home", line=None), resolve)
    assert refusal == "" or refusal is None, refusal
    assert verdict["outcome"] == "push"
    assert resolved["settled_segment"] == "q4"


def test_a_tied_quarter_LOSES_the_three_way_moneyline_and_pays_the_draw(_isolated):
    """`h2h_3_way` is three-way by name: level is a loss on either club and a
    win on the draw. The same 18-18 quarter, the other market."""
    _write_linescores(_isolated, [_gs_con_linescore()])
    resolve = mod.wnba_status_resolver(DATE)

    home = _order(market="h2h_3_way", segment="q4", side="home", line=None)
    assert _status(resolve(home), home)["status"] == "lost"
    draw = _order(market="h2h_3_way", segment="q4", side="draw", line=None)
    assert _status(resolve(draw), draw)["status"] == "won"


# --------------------------------------------------------------------------
# Every unreadable segment is named, and the old refusal is the fallback.
# --------------------------------------------------------------------------


def test_no_sidecar_falls_back_to_the_recorded_refusal(_isolated):
    """A slate whose box was built before the capture existed -- or whose game
    is not final yet -- still refuses with the wording `state_basketball.md`
    quotes, and never grades the quarter off the whole game."""
    _write_final_box(_isolated)
    resolve = mod.wnba_status_resolver(DATE)

    out = resolve(_order(segment="q1", side="over", line=36.5))
    assert out["unavailable_reason"] == "final_box_is_full_game_not_q1"
    assert out.get("current_value") is None


def test_a_game_absent_from_the_sidecar_falls_back_rather_than_matching_another(_isolated):
    _write_linescores(_isolated, [_gs_con_linescore(home_tri="LVA", away_tri="PHX")])
    resolve = mod.wnba_status_resolver(DATE)

    out = resolve(_order(segment="q1", side="over", line=36.5))
    assert out["unavailable_reason"] == "final_box_is_full_game_not_q1"


def test_a_game_in_the_sidecar_with_the_period_missing_is_named(_isolated):
    """The game IS there and the answer still is not: two quarters captured,
    a fourth-quarter line asked. Named with the segment so the work list says
    which reading is missing, while the first half still grades."""
    _write_linescores(_isolated, [_gs_con_linescore(CON_Q[:2], GS_Q[:2])])
    resolve = mod.wnba_status_resolver(DATE)

    out = resolve(_order(segment="q4", side="over", line=35.5))
    assert out["unavailable_reason"] == f"{REASON_SEGMENT_ACTUAL_PREFIX}q4"
    assert resolve(_order(segment="h1", side="over", line=73.5))["current_value"] == 32 + 42


def test_an_unreadable_period_cell_refuses_rather_than_reading_zero(_isolated):
    _write_linescores(_isolated, [_gs_con_linescore([15, None, 14, 18], GS_Q)])
    resolve = mod.wnba_status_resolver(DATE)

    assert resolve(_order(segment="h1", side="over", line=1.5))["unavailable_reason"] == f"{REASON_SEGMENT_ACTUAL_PREFIX}h1"
    assert resolve(_order(segment="q1", side="over", line=36.5))["current_value"] == 37


def test_swapped_home_and_away_between_order_and_espn_refuses(_isolated):
    """`_matchup_key` is a frozenset and matches either way round; the roles
    are checked after, because a segment spread on the wrong side is a
    confident wrong verdict."""
    _write_linescores(_isolated, [_gs_con_linescore(home_tri="GS", away_tri="CON")])
    resolve = mod.wnba_status_resolver(DATE)

    out = resolve(_order(market="spreads", segment="h1", side="away", line=-7.5))
    assert out["unavailable_reason"] == "home_away_disagree_between_sources"


def test_a_segment_PLAYER_prop_still_refuses(_isolated):
    """The linescore carries no player stats. A first-half points line is
    exactly the order the guard was moved to the resolver entry for, and the
    sidecar being present must not reopen that path."""
    _write_linescores(_isolated, [_gs_con_linescore()])
    _write_final_box(_isolated)
    resolve = mod.wnba_status_resolver(DATE)

    out = resolve(_order(market="player_points", segment="h1", player_name="GS Player 0", side="over", line=9.5))
    assert out["unavailable_reason"] == "final_box_is_full_game_not_h1"


def test_a_segment_this_sport_does_not_play_falls_back(_isolated):
    _write_linescores(_isolated, [_gs_con_linescore()])
    resolve = mod.wnba_status_resolver(DATE)

    out = resolve(_order(segment="first5", side="over", line=36.5))
    assert out["unavailable_reason"] == "final_box_is_full_game_not_first5"


def test_the_sidecar_is_read_once_per_resolver(_isolated, monkeypatch):
    _write_linescores(_isolated, [_gs_con_linescore()])
    calls = []
    real = mod._load_linescores

    def counted(date):
        calls.append(date)
        return real(date)

    monkeypatch.setattr(mod, "_load_linescores", counted)
    resolve = mod.wnba_status_resolver(DATE)
    for segment in ("q1", "h1", "q4"):
        resolve(_order(segment=segment, side="over", line=1.5))
    assert calls == [DATE]


# --------------------------------------------------------------------------
# The producer: the sidecar rides the fetch that already exists.
# --------------------------------------------------------------------------


def _summary_with_header(home_periods, away_periods, *, home_tri="CON", away_tri="GS"):
    """The two parts of an ESPN summary settlement reads: the header (quarters)
    and the boxscore (players). `displayValue` is the spelling
    `build_wnba_recon._linescore_totals` reads from this same endpoint."""
    def competitor(tri, periods, side):
        return {
            "homeAway": side,
            "team": {"abbreviation": tri},
            "score": str(sum(periods)),
            "linescores": [{"displayValue": str(p)} for p in periods],
        }

    return {
        "header": {"competitions": [{"competitors": [
            competitor(home_tri, home_periods, "home"),
            competitor(away_tri, away_periods, "away"),
        ]}]},
        "boxscore": {"players": [{
            "team": {"abbreviation": away_tri},
            "statistics": [{
                "keys": ["minutes", "points"],
                "athletes": [{"athlete": {"id": "1", "displayName": "GS Player 0"},
                              "starter": True, "position": {"abbreviation": "G"},
                              "stats": ["30", "25"]}],
            }],
        }]},
    }


def test_linescore_from_summary_reads_the_header_quarters():
    from scripts import build_wnba_boxscores as producer

    out = producer.linescore_from_summary(_summary_with_header(CON_Q, GS_Q), "401857176")
    assert out == {
        "game_id": "401857176", "home_tri": "CON", "away_tri": "GS",
        "home": CON_Q, "away": GS_Q, "home_score": 64, "away_score": 89,
    }


def test_a_summary_without_a_header_yields_no_linescore_and_still_yields_rows():
    """The existing fixtures carry no header. They must keep producing rows,
    and produce NO sidecar entry rather than an empty one."""
    from scripts import build_wnba_boxscores as producer

    summary = _summary_with_header(CON_Q, GS_Q)
    del summary["header"]
    assert producer.linescore_from_summary(summary, "x") is None
    assert len(producer.rows_from_summary(summary, "x", DATE)) == 1


def test_build_date_writes_the_sidecar_beside_the_csv(monkeypatch, _isolated):
    from scripts import build_wnba_boxscores as producer

    monkeypatch.setattr(producer, "completed_event_ids", lambda d: ["401857176"])
    monkeypatch.setattr(producer, "_get", lambda url, timeout=30: _summary_with_header(CON_Q, GS_Q))

    result = producer.build_date(DATE)
    assert result["status"] == "ok" and result["rows"] == 1 and result["linescores"] == 1
    assert (_isolated / "wnba_source" / "data" / "processed" / f"boxscores_{DATE}.csv").exists()
    sidecar = json.loads((_isolated / producer.linescores_relative_path(DATE)).read_text(encoding="utf-8"))
    assert sidecar["games"][0]["home"] == CON_Q and sidecar["games"][0]["away_tri"] == "GS"

    # AND THE RESOLVER READS WHAT THE PRODUCER WROTE -- the round trip, not two
    # halves that each look right.
    resolve = mod.wnba_status_resolver(DATE)
    assert resolve(_order(segment="q1", side="over", line=36.5))["current_value"] == 37


def test_build_date_via_web_takes_the_web_linescores(monkeypatch, _isolated):
    """Render's route: ESPN 403s the worker, so web returns `linescores` in the
    same payload as the rows and the producer persists them verbatim."""
    from scripts import build_wnba_boxscores as producer

    row = {c: "" for c in producer.COLUMNS} | {"PLAYER_NAME": "GS Player 0", "game_id": "401857176"}
    monkeypatch.setattr(producer, "fetch_via_web", lambda base, d, count_only=False: {
        "ok": True, "games": 1, "rows": [row], "linescores": [_gs_con_linescore()],
    })
    monkeypatch.setattr(producer, "completed_event_ids",
                        lambda d: (_ for _ in ()).throw(AssertionError("must not hit ESPN")))

    result = producer.build_date(DATE, base_url="https://web")
    assert result["status"] == "ok" and result["linescores"] == 1
    assert (_isolated / producer.linescores_relative_path(DATE)).exists()


def test_a_slate_with_no_linescores_writes_the_csv_and_no_sidecar(monkeypatch, _isolated):
    from scripts import build_wnba_boxscores as producer

    summary = _summary_with_header(CON_Q, GS_Q)
    del summary["header"]
    monkeypatch.setattr(producer, "completed_event_ids", lambda d: ["401857176"])
    monkeypatch.setattr(producer, "_get", lambda url, timeout=30: summary)

    result = producer.build_date(DATE)
    assert result["status"] == "ok" and result["linescores"] == 0
    assert not (_isolated / producer.linescores_relative_path(DATE)).exists()


def test_the_producer_and_the_reader_agree_on_the_path():
    from scripts import build_wnba_boxscores as producer

    assert producer.linescores_relative_path(DATE) == mod.linescores_relative_path(DATE)
    assert mod.linescores_relative_path(DATE) == f"wnba_source/data/processed/linescores_{DATE}.json"
