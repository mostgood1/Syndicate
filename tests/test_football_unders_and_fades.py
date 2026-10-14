"""Football unders test (HU-NFL / HU-NCAAF) and the forward fade grader (F9 / F10a / F10b), on synthetic files."""
from __future__ import annotations

import csv
import importlib.util
import json
from collections import defaultdict
from pathlib import Path

import pytest


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).resolve().parents[1] / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


KICK = "2026-10-25T17:00:00Z"  # cutoff 16:50Z


def _q(seen, book, player, point, over, under, market="Rushing Yards", event="e1", commence=KICK, **extra):
    base = {"kind": "prop", "event_id": event, "commence_time": commence, "captured_at": seen, "bookmaker": book,
            "market": market, "player_name": player, "line": point, "home_team": "Troy Trojans",
            "away_team": "Army Black Knights", **extra}
    return [dict(base, selection="over", price=over), dict(base, selection="under", price=under)]


def test_close_lines_use_us_books_the_scheduled_kickoff_and_change_log_semantics() -> None:
    g = _load("grade_football_fade_leads")
    rows = []
    rows += _q("2026-10-25T12:00:00Z", "draftkings", "A B", 60.5, -110, -110)
    rows += _q("2026-10-25T15:00:00Z", "draftkings", "A B", 64.5, -110, -110)          # dk moved off 60.5
    rows += _q("2026-10-25T15:00:00Z", "fanduel", "A B", 64.5, -105, -115)
    rows += _q("2026-10-25T15:00:00Z", "betmgm", "A B", 60.5, -110, -110)
    rows += _q("2026-10-25T15:00:00Z", "polymarket", "A B", 60.5, -110, -105)          # not a US sportsbook
    rows += _q("2026-10-25T16:55:00Z", "fanduel", "A B", 70.5, -110, -110,             # in-play rewrite: after cutoff
               commence="2026-10-25T17:05:00Z")
    rows.append({"kind": "prop", "event_id": "e1", "commence_time": KICK, "captured_at": "2026-10-25T16:00:00Z",
                 "bookmaker": "draftkings", "market": "Rushing Yards", "player_name": "A B", "line": 64.5,
                 "selection": "under", "price": -125, "home_team": "Troy Trojans", "away_team": "Army Black Knights"})
    lines = g.close_main_lines(rows)
    assert len(lines) == 1
    line = lines[0]
    assert line["point"] == 64.5 and line["books"] == 2       # dk (over carried forward) + fd; dk's 60.5 dropped
    assert line["best_under"] == -115                          # dk -125, fd -115
    assert line["kickoff"].isoformat().startswith("2026-10-25T17:00")


def test_weeks_and_interim_vs_final_reads() -> None:
    g = _load("grade_football_fade_leads")
    assert g._weeks(None, (6, 18)) == list(range(6, 19)) and g._weeks("2-5", (6, 18)) == [2, 3, 4, 5]
    rows = [{"h": "F9", "game": f"g{i}", "y": 1.0, "p": 0.5, "pnl": 0.9, "week": 6} for i in range(10)]
    interim = g.report(rows, final=False, counts={})
    assert interim["hypotheses"]["F9"]["verdict"].startswith("INTERIM") and "holm" not in interim
    final = g.report(rows, final=True, counts={})
    assert final["holm"] == {"F9": True, "F10a": False, "F10b": False}
    assert final["hypotheses"]["F9"]["residual_under"]["p_one_sided"] == round(1 / 2001, 4)


def _box(root: Path, rows: list[dict]) -> None:
    path = root / "ncaaf_source" / "source_artifacts" / "data" / "processed" / "player_game_stats" / \
        "ncaaf_player_game_stats_snapshot.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    cols = ["season", "week", "game_id", "player_id", "player_name", "team", "opponent", "passing_attempts",
            "rushing_attempts", "receptions", "rushing_yards", "receiving_yards", "passing_yards", "passing_tds"]
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, 0) for c in cols})


def _ncaaf_season(root: Path, season: int, spike_week: int, opponent: bool = True) -> None:
    """Rb One: 5 carries a game (of 20) for weeks 1-5, then 15 (of 20) in weeks 6-8 -> a carry spike before
    `spike_week`; Troy plays Army in `spike_week`, where Rb One runs for 40 yards."""
    rows = []
    for wk in range(1, spike_week + 1):
        game = f"{season}g{wk}"
        mine = 5 if wk <= spike_week - 4 else 15
        yards = 40 if wk == spike_week else 50
        rows += [{"season": season, "week": wk, "game_id": game, "player_id": "1", "player_name": "Rb One", "team": "Troy",
                  "opponent": "Army", "rushing_attempts": mine, "rushing_yards": yards},
                 {"season": season, "week": wk, "game_id": game, "player_id": "2", "player_name": "Rb Two", "team": "Troy",
                  "opponent": "Army", "rushing_attempts": 20 - mine},
                 {"season": season, "week": wk, "game_id": game, "player_id": "3", "player_name": "Army Back",
                  "team": "Army", "opponent": "Troy", "rushing_attempts": 20}]
    if not opponent:  # the 2026 snapshot leaves `opponent` empty
        for r in rows:
            r["opponent"] = ""
    _box(root, rows)


def test_ncaaf_fade_carry_spike_end_to_end(tmp_path, monkeypatch) -> None:
    g = _load("grade_football_fade_leads")
    from syndicate.features.shared import team_aliases

    alias = {"Troy Trojans": "troy", "Troy": "troy", "Army Black Knights": "army", "Army": "army"}
    monkeypatch.setattr(team_aliases, "canonical_team", lambda sport, name: alias.get(str(name)))
    _ncaaf_season(tmp_path, 2026, 9, opponent=False)
    quotes = tmp_path / "ncaaf_source" / "tracking" / "book_quotes" / "2026_wk9.jsonl"
    quotes.parent.mkdir(parents=True, exist_ok=True)
    rows = _q("2026-10-25T12:00:00Z", "draftkings", "Rb One", 55.5, -110, -110) + \
        _q("2026-10-25T12:00:00Z", "fanduel", "Rb One", 55.5, -110, -105)
    quotes.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    counts: dict = defaultdict(int)
    recs = g.ncaaf_records(tmp_path, [9], False, counts)
    assert len(recs) == 1 and recs[0]["h"] == "F10b" and recs[0]["y"] == 1.0 and recs[0]["price"] == -105
    # a game that kicked off before the registration is never graded
    rows_pre = _q("2026-10-13T12:00:00Z", "draftkings", "Rb One", 55.5, -110, -110, commence="2026-10-13T23:00:00Z")
    quotes.write_text("\n".join(json.dumps(r) for r in rows_pre) + "\n", encoding="utf-8")
    assert g.ncaaf_records(tmp_path, [9], False, counts) == [] and counts["pre_registration_kickoff"] >= 1


def test_football_unders_ncaaf_grades_main_lines_from_the_box(tmp_path) -> None:
    u = _load("football_unders_test")
    _ncaaf_season(tmp_path, 2025, 9)
    qdir = tmp_path / "quotes"
    qdir.mkdir()
    rows = []
    for book in ("draftkings", "fanduel"):
        for side, price in (("over", -110), ("under", -110)):
            rows.append({"kind": "prop", "event_id": "e9", "cfbd_game_id": "2025g9", "market": "Rushing Yards",
                         "selection": side, "player_name": "Rb One", "line": 45.5, "price": price, "bookmaker": book,
                         "home_team": "Troy Trojans", "away_team": "Army Black Knights"})
    (qdir / "quotes_2025_wk09.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    primary, sens, counts = u.grade_lines("ncaaf", tmp_path, qdir, None)
    assert counts["graded"] == 1 and len(primary) == 1 and sens == primary
    assert primary[0]["window"] == "confirm" and primary[0]["y"] == 1.0 and abs(primary[0]["p"] - 0.5) < 1e-9
    assert primary[0]["under_dec_best"] == pytest.approx(1 + 100 / 110)


def test_injury_listing_counts_any_status_and_summary_bar(tmp_path) -> None:
    u = _load("football_unders_test")
    inj = tmp_path / "injuries_2025.csv"
    inj.write_text("season,game_type,week,team,gsis_id,report_status\n2025,REG,3,KC,00-1,Questionable\n"
                   "2025,REG,3,KC,00-2,\n2025,WC,19,KC,00-3,Out\n", encoding="utf-8")
    listed = u.injury_listed(inj, 2025)
    assert listed[(3, "KC")] == {"00-1"} and (19, "KC") not in listed
    rows = [{"window": w, "game": f"{w}{i}", "y": 1.0 if i % 5 else 0.0, "p": 0.5, "under_dec_best": 1.9,
             "under_dec_median": 1.9, "stat": "receptions"} for w in ("discover", "confirm") for i in range(30)]
    s = u.summarize(rows)
    assert s["verdict"] == "SUPPORTED" and s["confirm"]["residual"]["n"] == 30


def test_quote_log_is_read_plain_or_gzipped(tmp_path) -> None:
    import gzip as gz

    g = _load("grade_football_fade_leads")
    lf = _load("signal_lift_football")
    d = tmp_path / "nfl_source" / "tracking" / "book_quotes"
    d.mkdir(parents=True)
    assert g.quotes_path(tmp_path, "nfl", 7) is None
    with gz.open(d / "2026_wk7.jsonl.gz", "wt", encoding="utf-8") as fh:
        fh.write(json.dumps({"kind": "prop", "x": 1}) + "\n")
    path = g.quotes_path(tmp_path, "nfl", 7)
    assert path.name == "2026_wk7.jsonl.gz" and lf._read_jsonl(path) == [{"kind": "prop", "x": 1}]
    (d / "2026_wk7.jsonl").write_text(json.dumps({"kind": "prop", "x": 2}) + "\n", encoding="utf-8")
    assert g.quotes_path(tmp_path, "nfl", 7).name == "2026_wk7.jsonl"
