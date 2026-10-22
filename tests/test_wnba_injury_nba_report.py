"""The WNBA injury fetch must never take the NBA's injury report (lane wnba-injury-nba-report, todo #731).

The vendored WNBA ``update_injuries`` preferred ``official.nba.com/nba-injury-report-<season>``, which is the NBA's
report. Rotowire's /basketball/ page (also the NBA's) and ESPN's WNBA page were only a fallback for when it came
back empty. Measured on the fleet 10-20..10-21: on NBA game days the official path won and ESPN was skipped. The
NBA's rows were written under the WNBA tricodes of the shared cities (ATL, CHI, DAL, IND, MIN, PHX, POR, TOR,
WAS). The fleet has no WNBA ``rosters_*.csv``, so the roster filter kept them. With a roster, the filter drops
them, and the day is left with no rows at all.

Every case goes through the real ``update_injuries``. Only the network (``requests.Session.get``), pypdf and the
clock are stubbed, so these tests also run against the old code: on it, the NBA-report-day and no-NBA-request
tests fail, and the no-report-day test passes.
"""

from __future__ import annotations

import sys
import types
from datetime import datetime

import pandas as pd
import pytest
import requests

import syndicate.features.wnba.source_cli.scrapers.injuries as inj

DATE = "2026-10-21"

# ESPN's WNBA page on 10-21: the players the 10-21 WNBA sim readmitted to the ATL / GSV pools while the NBA's rows
# stood in for the day's report (SMART_SIM_REUSE_STALE_EXCLUSIONS drift, refresh log 2026-10-21).
ESPN_ROWS = {
    "Atlanta Dream": [("Matilde Villa", "Knee", "Out"), ("Aaliyah Nye", "Ankle", "Out")],
    "Golden State Valkyries": [("Iliana Rupert", "Foot", "Out"), ("Ndjakalenga Mwenentanda", "Knee", "Out")],
}
WNBA_EXPECTED = {
    ("ATL", "Matilde Villa"): "OUT",
    ("ATL", "Aaliyah Nye"): "OUT",
    ("GSV", "Iliana Rupert"): "OUT",
    ("GSV", "Ndjakalenga Mwenentanda"): "OUT",
}

# The real 10-21 5:00 PM ET NBA report, Atlanta Hawks block (pypdf gives one word per line). "ATL" and "Atlanta"
# resolve to the WNBA's Atlanta Dream, so the old code wrote these Hawks as WNBA ATL rows.
NBA_PDF_TOKENS = [
    "Injury", "Report:", "10/21/26", "05:00", "PM", "Game", "Date", "Game", "Time", "Matchup", "Team",
    "Player", "Name", "Current", "Status", "Reason", "10/21/2026", "07:30", "(ET)",
    "ATL@ORL", "Atlanta", "Hawks",
    "Dennis,", "RayJ", "Questionable", "G", "League", "-", "Two-", "Way",
    "Gilbert,", "Keshon", "Questionable", "G", "League", "-", "Two-", "Way",
    "Gueye,", "Mouhamed", "Out", "Injury/Illness", "-", "Left", "Foot", "Fracture",
    "Veesaar,", "Henri", "Out", "Injury/Illness", "-", "Right", "ACL", "Tear",
]
NBA_PDF_URL = f"https://ak-static.cms.nba.com/referee/injury/Injury-Report_{DATE}_05_00PM.pdf"
YESTERDAY_PDF_URL = "https://ak-static.cms.nba.com/referee/injury/Injury-Report_2026-10-20_11_30PM.pdf"


def _espn_html() -> str:
    blocks = []
    for team, rows in ESPN_ROWS.items():
        body = "".join(
            f"<tr><td>{p}</td><td>G</td><td>Oct 20</td><td>{injury}</td><td>{status}</td></tr>"
            for p, injury, status in rows
        )
        blocks.append(
            f'<div class="Table__Title">{team}</div><div class="ResponsiveTable"><table>'
            "<tr><th>PLAYER</th><th>POS</th><th>DATE</th><th>INJURY</th><th>STATUS</th></tr>"
            f"{body}</table></div>"
        )
    return "<html><body>" + "".join(blocks) + "</body></html>"


class _Resp:
    def __init__(self, *, text: str = "", content: bytes | None = None, ctype: str = "text/html") -> None:
        self.status_code = 200
        self.ok = True
        self.text = text
        self.content = content if content is not None else text.encode("utf-8")
        self.headers = {"content-type": ctype}

    def raise_for_status(self) -> None:
        return None


class _StubPage:
    def __init__(self, text: str) -> None:
        self._text = text

    def extract_text(self) -> str:
        return self._text


class _StubPdfReader:
    """Stands in for pypdf: the 'PDF bytes' are the token stream, one token per line."""

    def __init__(self, stream) -> None:
        self.pages = [_StubPage(stream.read().decode("utf-8"))]


class _FixedDatetime(datetime):
    """ESPN rows are stamped datetime.now(): pin it to the fetch date."""

    @classmethod
    def now(cls, tz=None):
        return cls(2026, 10, 21, 12, 0, 0)


@pytest.fixture
def world(tmp_path, monkeypatch):
    """The network, pypdf and clock, stubbed. ``world.nba_report_day`` says whether the NBA's season page lists
    a report for DATE; ``world.requested`` records every URL fetched."""
    state = types.SimpleNamespace(nba_report_day=True, requested=[], tmp=tmp_path)

    def fake_get(self, url, **kwargs):
        state.requested.append(url)
        if "official.nba.com/nba-injury-report-" in url:
            pdf = NBA_PDF_URL if state.nba_report_day else YESTERDAY_PDF_URL
            return _Resp(text=f'<html><body><a href="{pdf}">report</a></body></html>')
        if url.endswith(".pdf"):
            return _Resp(content="\n".join(NBA_PDF_TOKENS).encode("utf-8"), ctype="application/pdf")
        if "rotowire.com" in url:
            return _Resp(text="<html><body></body></html>")  # JS-rendered: the static page parses 0 rows
        if url == "https://www.espn.com/wnba/injuries":
            return _Resp(text=_espn_html())
        raise AssertionError(f"unexpected URL {url}")

    monkeypatch.setattr(requests.Session, "get", fake_get)
    monkeypatch.setattr(inj, "PdfReader", _StubPdfReader, raising=False)
    monkeypatch.setattr(inj, "datetime", _FixedDatetime)
    monkeypatch.setitem(sys.modules, "selenium", None)  # no headless Rotowire, as on the fleet
    processed = tmp_path / "processed"
    processed.mkdir()
    monkeypatch.setattr(inj, "paths", types.SimpleNamespace(data_processed=processed, data_root=tmp_path))
    state.processed = processed
    state.target = tmp_path / "raw" / "injuries.csv"
    state.target.parent.mkdir()
    # Yesterday's snapshot and an earlier fetch of today's, both from ESPN.
    pd.DataFrame([
        {"team": "ATL", "player": "Matilde Villa", "status": "OUT", "injury": "Out", "date": "2026-10-20"},
        {"team": "ATL", "player": "Matilde Villa", "status": "OUT", "injury": "Out", "date": DATE},
    ]).to_csv(state.target, index=False)
    return state


def _write_wnba_roster(processed) -> None:
    rows = [{"PLAYER": p, "TEAM_ABBREVIATION": t} for (t, p) in WNBA_EXPECTED]
    rows += [{"PLAYER": "Allisha Gray", "TEAM_ABBREVIATION": "ATL"}, {"PLAYER": "Kayla Thornton", "TEAM_ABBREVIATION": "GSV"}]
    pd.DataFrame(rows).to_csv(processed / "rosters_2026.csv", index=False)


def _day(target, date: str) -> dict[tuple[str, str], str]:
    written = pd.read_csv(target)
    day = written[written["date"].astype(str) == date]
    return {(r.team, r.player): r.status for r in day.itertuples()}


@pytest.mark.parametrize("roster", ["absent", "present"], ids=["no-roster-as-on-the-fleet", "with-wnba-roster"])
def test_nba_report_day_writes_the_wnba_report_not_the_nbas(world, roster):
    """Old code: no roster -> the Hawks written as WNBA ATL rows; roster -> the day emptied. Both read ESPN now."""
    if roster == "present":
        _write_wnba_roster(world.processed)

    inj.NBAInjuryDatabase(filepath=str(world.target)).update_injuries(date_str=DATE)

    assert _day(world.target, DATE) == WNBA_EXPECTED
    assert _day(world.target, "2026-10-20") == {("ATL", "Matilde Villa"): "OUT"}  # other snapshots untouched


def test_no_nba_report_day_is_unchanged(world):
    """Guard: with no NBA report for the date, the old code already fell back to ESPN. The output is the same."""
    world.nba_report_day = False

    inj.NBAInjuryDatabase(filepath=str(world.target)).update_injuries(date_str=DATE)

    assert _day(world.target, DATE) == WNBA_EXPECTED


@pytest.mark.parametrize("nba_report_day", [True, False], ids=["nba-report-day", "no-nba-report"])
def test_the_fetch_never_requests_an_nba_source(world, nba_report_day):
    world.nba_report_day = nba_report_day

    inj.NBAInjuryDatabase(filepath=str(world.target)).update_injuries(date_str=DATE)

    assert world.requested == ["https://www.espn.com/wnba/injuries"]


def test_the_fleet_entrypoint_writes_the_wnba_report(world):
    """`python -m syndicate.features.wnba.source_cli.cli fetch-injuries --date D` is what both fleet writers run
    (the WNBA props refresh and live_refresh_loop._fetch_injuries)."""
    from click.testing import CliRunner

    from syndicate.features.wnba.source_cli import cli as wnba_cli

    result = CliRunner().invoke(wnba_cli.cli, ["fetch-injuries", "--date", DATE])

    assert result.exit_code == 0, result.output
    assert _day(world.target, DATE) == WNBA_EXPECTED
    assert world.requested == ["https://www.espn.com/wnba/injuries"]
