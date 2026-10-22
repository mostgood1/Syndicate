"""NBA raw/injuries.csv keeps each date's OFFICIAL snapshot (lane nba-injury-snapshot-overwrite, todo #725 lead 5).

Measured on the fleet 2026-10-22: every past date's rows had been replaced by Rotowire/ESPN. The season page
lists only TODAY's reports, so the live loop's fetch for its (Central) date after midnight ET found no PDF and
fell back; 10-21's official rows (74 OUT at 8:35 PM CT) were 65 fallback rows by 11:04 PM CT. Separately, the
SmartSim's partial-snapshot guard compared a day's official report (only the teams playing) with the previous
day's all-team fallback, and on the 3-game 10-20 and 2-game 10-22 slates every game-day build used the
previous day's rows instead.

Writer tests go through ``NBAInjuryDatabase.update_injuries`` with the network stubbed at the scraper edge
(page lookup, PDF download, Rotowire, ESPN) and the roster cleaners neutralized. Guard tests go through the
real ``_smart_sim_injuries_excluded_map_for_date_local``.
"""

from __future__ import annotations

import csv
import datetime as dt
from pathlib import Path

import pandas as pd
import pytest

import syndicate.features.nba.source_cli.scrapers.injuries as inj
from syndicate.features.shared import basketball_props_smart_sim as sim

D = "2026-10-21"
NEXT = "2026-10-22"


def _rows(date: str, source: str, players: list[tuple[str, str, str]]) -> pd.DataFrame:
    return pd.DataFrame(
        [{"team": t, "player": p, "status": s, "injury": s.title(), "date": date, "source": source} for t, p, s in players]
    )


def _write_feed(path: Path, frames: list[pd.DataFrame]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.concat(frames, ignore_index=True).to_csv(path, index=False)


def _day(path: Path, date: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    return df[df["date"].astype(str) == date].reset_index(drop=True)


@pytest.fixture
def db(tmp_path, monkeypatch):
    # The cleaners re-key names/teams against the current roster file; with no roster they pass rows through.
    monkeypatch.setattr(inj, "_roster_player_indexes", lambda date_str: ({}, {}, {}))
    monkeypatch.setattr(inj, "_roster_name_to_team_map", lambda date_str: {})
    database = inj.NBAInjuryDatabase.__new__(inj.NBAInjuryDatabase)
    database.filepath = tmp_path / "data" / "raw" / "injuries.csv"
    database.scraper = type("_ESPN", (), {"get_all_injuries": lambda self: pd.DataFrame()})()
    return database


def _stub_sources(monkeypatch, *, official=None, rotowire=None):
    calls = {"rotowire": 0}

    def _official(self, date_str):
        return official if official is not None else pd.DataFrame()

    def _rotowire(self):
        calls["rotowire"] += 1
        return rotowire if rotowire is not None else pd.DataFrame()

    monkeypatch.setattr(inj.NBAOfficialInjuryReportScraper, "get_injuries_for_date", _official)
    monkeypatch.setattr(inj.RotowireInjuryScraper, "get_all_injuries", _rotowire)
    return calls


# --- writer: official snapshots are never replaced by fallback rows -------------------------------------------


def test_fallback_never_replaces_an_official_snapshot(db, monkeypatch):
    official = _rows(D, inj.OFFICIAL_INJURY_SOURCE, [("GSW", "Moses Moody", "OUT"), ("GSW", "Al Horford", "QUESTIONABLE")])
    _write_feed(db.filepath, [official])
    # After midnight ET the page has no 10-21 PDF; Rotowire describes "now", stamped with the scrape day.
    _stub_sources(monkeypatch, rotowire=_rows(D, "", [("GSW", "Moses Moody", "OUT"), ("LAL", "Luka Doncic", "OUT")]).drop(columns="source"))
    monkeypatch.setattr(inj, "_et_today", lambda: dt.date(2026, 10, 21))

    out = db.update_injuries(date_str=D)

    assert out.empty
    kept = _day(db.filepath, D)
    assert sorted(kept["player"]) == ["Al Horford", "Moses Moody"]
    assert set(kept["source"]) == {inj.OFFICIAL_INJURY_SOURCE}


def test_fallback_still_replaces_a_fallback_snapshot(db, monkeypatch):
    _write_feed(db.filepath, [_rows(D, "rotowire", [("GSW", "Moses Moody", "OUT"), ("LAL", "Luka Doncic", "OUT")])])
    # Doncic is back: he drops off the new scrape, and the day's snapshot is the new scrape.
    _stub_sources(monkeypatch, rotowire=_rows(D, "", [("GSW", "Moses Moody", "OUT")]).drop(columns="source"))
    monkeypatch.setattr(inj, "_et_today", lambda: dt.date(2026, 10, 21))

    db.update_injuries(date_str=D)

    day = _day(db.filepath, D)
    assert list(day["player"]) == ["Moses Moody"]
    assert list(day["source"]) == ["rotowire"]


def test_official_replaces_a_fallback_snapshot_and_carries_provenance(db, monkeypatch):
    _write_feed(db.filepath, [_rows(D, "rotowire", [("GSW", "Moses Moody", "OUT"), ("LAL", "Luka Doncic", "OUT")])])
    official = _rows(D, inj.OFFICIAL_INJURY_SOURCE, [("GSW", "Moses Moody", "OUT")])
    calls = _stub_sources(monkeypatch, official=official)

    db.update_injuries(date_str=D)

    day = _day(db.filepath, D)
    assert list(day["player"]) == ["Moses Moody"]
    assert list(day["source"]) == [inj.OFFICIAL_INJURY_SOURCE]
    assert calls["rotowire"] == 0


def test_lookahead_fallback_touches_only_the_day_it_describes(db, monkeypatch):
    # A props refresh fetches --date D+2 two days ahead: no official report exists yet, and Rotowire/ESPN
    # stamp their rows with the scrape day (10-21). The old writer deleted the D+2 rows and MERGED the scrape
    # into 10-21's official snapshot (dedupe keep-last), mixing two sources in one day.
    official = _rows(D, inj.OFFICIAL_INJURY_SOURCE, [("GSW", "Moses Moody", "OUT"), ("GSW", "Al Horford", "QUESTIONABLE")])
    earlier = _rows("2026-10-20", "rotowire", [("DET", "Taurean Prince", "OUT")])
    _write_feed(db.filepath, [earlier, official])
    _stub_sources(monkeypatch, rotowire=_rows(D, "", [("GSW", "Moses Moody", "DAY-TO-DAY"), ("LAL", "Luka Doncic", "OUT")]).drop(columns="source"))
    monkeypatch.setattr(inj, "_et_today", lambda: dt.date(2026, 10, 21))

    db.update_injuries(date_str="2026-10-23")

    day = _day(db.filepath, D)
    assert sorted(zip(day["player"], day["status"])) == [("Al Horford", "QUESTIONABLE"), ("Moses Moody", "OUT")]
    assert list(_day(db.filepath, "2026-10-20")["player"]) == ["Taurean Prince"]


def test_fallback_for_another_day_does_not_delete_the_requested_days_rows(db, monkeypatch):
    # A fetch for a past date whose rows are fallback, made after the Central date rolled: the scrape is
    # stamped TODAY, so it replaces today's snapshot and leaves the requested day's rows alone (the old writer
    # deleted them and wrote nothing in their place).
    _write_feed(db.filepath, [_rows(D, "rotowire", [("GSW", "Moses Moody", "OUT")])])
    _stub_sources(monkeypatch, rotowire=_rows(NEXT, "", [("OKC", "Nikola Topic", "OUT")]).drop(columns="source"))
    monkeypatch.setattr(inj, "_et_today", lambda: dt.date(2026, 10, 22))
    monkeypatch.setattr(inj.NBAOfficialInjuryReportScraper, "_direct_pdf_for_past_date", lambda self, d: None)

    db.update_injuries(date_str=D)

    assert list(_day(db.filepath, D)["player"]) == ["Moses Moody"]
    assert list(_day(db.filepath, NEXT)["player"]) == ["Nikola Topic"]


# --- writer: a past date's last report by direct URL -------------------------------------------------------------


@pytest.fixture
def pdf_host(monkeypatch):
    """The real get_injuries_for_date, with the season page and the PDF host stubbed. Every report parses to
    the same two rows, as consecutive real reports do when no status changed."""
    state = {"page": None, "available": set(), "downloads": []}

    def _page(self, date_str):
        return state["page"]

    def _download(self, url):
        state["downloads"].append(url)
        return b"%PDF-1.7 stub" if url.rsplit("/", 1)[-1] in state["available"] else None

    def _parse(self, pdf, *, date_str):
        return _rows(date_str, "", [("GSW", "Moses Moody", "OUT"), ("LAL", "Luka Doncic", "OUT")]).drop(columns="source")

    monkeypatch.setattr(inj.NBAOfficialInjuryReportScraper, "_latest_pdf_url_for_date", _page)
    monkeypatch.setattr(inj.NBAOfficialInjuryReportScraper, "_download_pdf", _download)
    monkeypatch.setattr(inj.NBAOfficialInjuryReportScraper, "_parse_pdf_rows", _parse)
    return state


def test_past_date_fetches_its_last_report_by_url(db, monkeypatch, pdf_host, capsys):
    # 11:05 PM CT on 10-21 = 12:05 AM ET 10-22: the page lists only 10-22, the live loop still asks for 10-21.
    monkeypatch.setattr(inj, "_et_today", lambda: dt.date(2026, 10, 22))
    pdf_host["available"] = {"Injury-Report_2026-10-21_11_30PM.pdf"}
    _write_feed(db.filepath, [_rows(D, inj.OFFICIAL_INJURY_SOURCE, [("GSW", "Stephen Curry", "OUT")])])
    rotowire_calls = []
    monkeypatch.setattr(inj.RotowireInjuryScraper, "get_all_injuries", lambda self: rotowire_calls.append(1) or pd.DataFrame())

    db.update_injuries(date_str=D)

    day = _day(db.filepath, D)
    assert sorted(day["player"]) == ["Luka Doncic", "Moses Moody"]
    assert set(day["source"]) == {inj.OFFICIAL_INJURY_SOURCE}
    assert pdf_host["downloads"] == ["https://ak-static.cms.nba.com/referee/injury/Injury-Report_2026-10-21_11_30PM.pdf"]
    assert "INJURY_REPORT date=2026-10-21 report=Injury-Report_2026-10-21_11_30PM.pdf via=url rows=2" in capsys.readouterr().out
    assert rotowire_calls == []


def test_direct_url_steps_back_and_is_bounded(monkeypatch, pdf_host, capsys):
    monkeypatch.setattr(inj, "_et_today", lambda: dt.date(2026, 10, 22))
    scraper = inj.NBAOfficialInjuryReportScraper()

    pdf_host["available"] = {"Injury-Report_2026-10-21_11_00PM.pdf"}
    assert len(scraper.get_injuries_for_date(D)) == 2
    assert [u.rsplit("/", 1)[-1] for u in pdf_host["downloads"]] == [
        "Injury-Report_2026-10-21_11_30PM.pdf", "Injury-Report_2026-10-21_11_00PM.pdf"]
    assert "report=Injury-Report_2026-10-21_11_00PM.pdf via=url" in capsys.readouterr().out

    # A date with no reports (10-10..10-18 returned 403): a fixed number of requests, then the fallback.
    pdf_host["downloads"].clear()
    pdf_host["available"] = set()
    assert scraper.get_injuries_for_date("2026-10-15").empty
    assert len(pdf_host["downloads"]) == len(inj.NBAOfficialInjuryReportScraper.PAST_DATE_REPORT_TIMES)


def test_today_and_future_dates_are_not_probed_by_url(monkeypatch, pdf_host):
    monkeypatch.setattr(inj, "_et_today", lambda: dt.date(2026, 10, 22))
    pdf_host["available"] = {"Injury-Report_2026-10-22_11_30PM.pdf", "Injury-Report_2026-10-23_11_30PM.pdf"}
    scraper = inj.NBAOfficialInjuryReportScraper()
    assert scraper.get_injuries_for_date(NEXT).empty
    assert scraper.get_injuries_for_date("2026-10-23").empty
    assert pdf_host["downloads"] == []


def test_page_listed_report_wins_and_is_stamped(monkeypatch, pdf_host, capsys):
    monkeypatch.setattr(inj, "_et_today", lambda: dt.date(2026, 10, 21))
    pdf_host["page"] = "https://ak-static.cms.nba.com/referee/injury/Injury-Report_2026-10-21_05_00PM.pdf"
    pdf_host["available"] = {"Injury-Report_2026-10-21_05_00PM.pdf"}
    df = inj.NBAOfficialInjuryReportScraper().get_injuries_for_date(D)
    assert set(df["source"]) == {inj.OFFICIAL_INJURY_SOURCE}
    assert pdf_host["downloads"] == [pdf_host["page"]]
    assert "report=Injury-Report_2026-10-21_05_00PM.pdf via=page" in capsys.readouterr().out


def test_a_new_report_with_the_same_statuses_leaves_the_file_bytes_unchanged(db, monkeypatch, pdf_host):
    # The live loop forces a re-sim whenever injuries.csv's bytes change (_basketball_lineup_injury_fingerprint),
    # and a new report is posted every half hour: nothing that names the report may land in the file.
    monkeypatch.setattr(inj, "_et_today", lambda: dt.date(2026, 10, 21))
    pdf_host["page"] = "https://ak-static.cms.nba.com/referee/injury/Injury-Report_2026-10-21_05_00PM.pdf"
    pdf_host["available"] = {"Injury-Report_2026-10-21_05_00PM.pdf", "Injury-Report_2026-10-21_05_30PM.pdf"}
    db.update_injuries(date_str=D)
    first = db.filepath.read_bytes()
    pdf_host["page"] = "https://ak-static.cms.nba.com/referee/injury/Injury-Report_2026-10-21_05_30PM.pdf"
    db.update_injuries(date_str=D)
    assert db.filepath.read_bytes() == first


# --- reader: the SmartSim's partial-snapshot guard ---------------------------------------------------------------


def _feed_csv(root: Path, rows: list[tuple[str, str, str, str, str]]) -> None:
    path = root / "data" / "raw" / "injuries.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["team", "player", "status", "injury", "date", "source"])
        for team, player, status, date, source in rows:
            writer.writerow([team, player, status, status.title(), date, source])


def _excluded(root: Path, date: str) -> set[str]:
    (root / "data" / "processed").mkdir(parents=True, exist_ok=True)
    props = pd.DataFrame([{"team": "DET", "player_name": "Taurean Prince"}, {"team": "BOS", "player_name": "Devin Carter"}])
    out = sim._smart_sim_injuries_excluded_map_for_date_local(
        processed_root=root / "data" / "processed", raw_root=root / "data" / "raw", date_str=date, props_df=props,
    )
    return {name for names in out.values() for name in names}


def _previous_day_fallback(date: str) -> list[tuple[str, str, str, str, str]]:
    # All 30 teams' worth of Rotowire rows the night before (10 here), with nothing on DET.
    teams = ["ATL", "BKN", "CHA", "CHI", "HOU", "MIA", "MIL", "ORL", "TOR", "WAS"]
    return [(t, f"Player {t}", "OUT", date, "rotowire") for t in teams] + [("BOS", "Devin Carter", "OUT", date, "rotowire")]


def test_game_dates_official_report_is_trusted_on_a_light_slate(tmp_path):
    # 10-20: 3 games. The day's own report (DET's OUT players) is far smaller than last night's all-team
    # fallback; it must still be the one read.
    _feed_csv(tmp_path, _previous_day_fallback("2026-10-19") + [
        ("DET", "Taurean Prince", "OUT", "2026-10-20", "nba_official"),
        ("BOS", "Devin Carter", "QUESTIONABLE", "2026-10-20", "nba_official"),
    ])
    excluded = _excluded(tmp_path, "2026-10-20")
    assert sim._norm_name_key("Taurean Prince") in excluded
    assert sim._norm_name_key("Devin Carter") not in excluded


def test_small_fallback_snapshot_still_falls_back(tmp_path):
    # The guard's own case is unchanged: a small NON-official latest snapshot is a partial fetch.
    _feed_csv(tmp_path, _previous_day_fallback("2026-10-19") + [("DET", "Taurean Prince", "OUT", "2026-10-20", "rotowire")])
    excluded = _excluded(tmp_path, "2026-10-20")
    assert sim._norm_name_key("Taurean Prince") not in excluded
    assert sim._norm_name_key("Devin Carter") in excluded


def test_official_report_of_an_earlier_day_keeps_the_guard(tmp_path):
    # A lookahead sim for 10-21 run on 10-20: the latest snapshot is 10-20's report, which speaks only for
    # 10-20's teams. It is not the game date's own report, so the guard decides as before.
    _feed_csv(tmp_path, _previous_day_fallback("2026-10-19") + [("DET", "Taurean Prince", "OUT", "2026-10-20", "nba_official")])
    excluded = _excluded(tmp_path, "2026-10-21")
    assert sim._norm_name_key("Taurean Prince") not in excluded
    assert sim._norm_name_key("Devin Carter") in excluded


def test_rows_without_provenance_keep_the_guard(tmp_path):
    # Rows written before the column existed carry no source: unknown is not official.
    _feed_csv(tmp_path, _previous_day_fallback("2026-10-19") + [("DET", "Taurean Prince", "OUT", "2026-10-20", "")])
    assert sim._norm_name_key("Taurean Prince") not in _excluded(tmp_path, "2026-10-20")
