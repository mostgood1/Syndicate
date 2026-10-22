"""The NBA official injury-report PDF parser (lane nba-injury-pdf-parser, todo #723 follow-up).

Two defects measured on the 10-21 slate (findings_2026-10-22_nba_sim_minutes_allocation.md §2 Q1a):

1. A reason's last word became part of the next player's name. The parser accepts "<word> Last," as a
   two-token surname (for "Lively II,"), so "... ACL Tear Wilson, Jalen" gave "Jalen Tear Wilson",
   which no sim pool matches: an OUT player was simulated.
2. "Available" was not a status, so "Curry, Stephen Available - Moody, Moses Out" parsed as ONE row,
   OUT, that the cleaner mapped to Stephen Curry. Moody's row was lost.

The token streams below are copied from the real 10-21 reports (pypdf gives one word per line).
They go through the real ``_parse_pdf_rows`` with only ``PdfReader`` stubbed.
"""

from __future__ import annotations

import types

import pandas as pd
import pytest

import syndicate.features.nba.source_cli.scrapers.injuries as inj

DATE = "2026-10-21"

ROSTER = {
    "ATL": ["RayJ Dennis", "Keshon Gilbert", "Mouhamed Gueye", "Henri Veesaar", "Jalen Wilson"],
    "GSW": ["Jimmy Butler III", "Stephen Curry", "Moses Moody"],
    "ORL": ["Anthony Black"],
    "DAL": ["Dereck Lively II", "David Jones Garcia"],
    "CLE": ["Khalifa Diop", "Jarrett Allen"],
}

HEADER = ["Injury", "Report:", "10/21/26", "05:00", "PM", "Game", "Date", "Game", "Time", "Matchup", "Team",
          "Player", "Name", "Current", "Status", "Reason", "10/21/2026", "07:30", "(ET)"]

ATL_STREAM = [
    "ATL@ORL", "Atlanta", "Hawks",
    "Dennis,", "RayJ", "Questionable", "G", "League", "-", "Two-", "Way",
    "Gilbert,", "Keshon", "Questionable", "G", "League", "-", "Two-", "Way",
    "Gueye,", "Mouhamed", "Out", "Injury/Illness", "-", "Left", "Foot", "Fracture",
    "Veesaar,", "Henri", "Out", "Injury/Illness", "-", "Right", "ACL", "Tear",
    "Wilson,", "Jalen", "Questionable", "G", "League", "-", "Two-", "Way",
    "Orlando", "Magic",
    "Black,", "Anthony", "Out", "Injury/Illness", "-", "Right", "Ankle", "Sprain",
]

GSW_STREAM = [
    "LAC@GSW", "Golden", "State", "Warriors",
    "Butler", "III,", "Jimmy", "Out", "Injury/Illness", "-", "Right", "ACL", "Repair", "/", "Surgery",
    "Curry,", "Stephen", "Available", "-",
    "Moody,", "Moses", "Out", "Injury/Illness", "-", "Left", "Patellar", "Tendon", "Repair",
]


class _StubPage:
    def __init__(self, text: str) -> None:
        self._text = text

    def extract_text(self) -> str:
        return self._text


class _StubPdfReader:
    """Stands in for pypdf: the 'PDF bytes' are the token stream, one token per line."""

    def __init__(self, stream) -> None:
        self.pages = [_StubPage(stream.read().decode("utf-8"))]


def _pdf(tokens: list[str]) -> bytes:
    return "\n".join(HEADER + tokens).encode("utf-8")


@pytest.fixture
def roster_dir(tmp_path, monkeypatch):
    rows = [{"PLAYER": p, "TEAM_ABBREVIATION": t} for t, players in ROSTER.items() for p in players]
    pd.DataFrame(rows).to_csv(tmp_path / "rosters_2026-27.csv", index=False)
    monkeypatch.setattr(inj, "paths", types.SimpleNamespace(data_processed=tmp_path, data_root=tmp_path))
    monkeypatch.setattr(inj, "PdfReader", _StubPdfReader)
    return tmp_path


def _parse(tokens: list[str]) -> pd.DataFrame:
    return inj.NBAOfficialInjuryReportScraper()._parse_pdf_rows(_pdf(tokens), date_str=DATE)


def _rows(df: pd.DataFrame) -> dict[str, tuple[str, str, str]]:
    return {r.player: (r.team, r.status, r.injury) for r in df.itertuples()}


def test_available_ends_its_row_and_the_next_player_keeps_his_own_status(roster_dir):
    rows = _rows(_parse(GSW_STREAM))

    assert set(rows) == {"Jimmy Butler III", "Moses Moody"}
    assert rows["Moses Moody"][:2] == ("GSW", "OUT")
    assert rows["Moses Moody"][2].startswith("Injury/Illness - Left Patellar")
    # Available is not an injury: parsed to end the row, never written.
    assert "Stephen Curry" not in rows


def test_reason_words_are_not_spliced_into_the_next_name(roster_dir):
    rows = _rows(_parse(ATL_STREAM))

    assert set(rows) == {"RayJ Dennis", "Keshon Gilbert", "Mouhamed Gueye", "Henri Veesaar", "Jalen Wilson",
                         "Anthony Black"}
    assert rows["Jalen Wilson"][:2] == ("ATL", "QUESTIONABLE")
    assert rows["Mouhamed Gueye"][:2] == ("ATL", "OUT")
    # The dropped word goes back to the reason it was cut from.
    assert rows["RayJ Dennis"][2] == "G League - Two- Way"
    assert rows["Keshon Gilbert"][2] == "G League - Two- Way"
    assert rows["Henri Veesaar"][2] == "Injury/Illness - Right ACL Tear"


def test_a_normal_row(roster_dir):
    rows = _rows(_parse(["ATL@ORL", "Orlando", "Magic", "Black,", "Anthony", "Out", "Injury/Illness", "-",
                         "Right", "Ankle", "Sprain"]))

    assert rows == {"Anthony Black": ("ORL", "OUT", "Injury/Illness - Right Ankle Sprain")}


def test_real_two_word_surnames_are_kept(roster_dir):
    rows = _rows(_parse(["DAL@SAS", "Dallas", "Mavericks",
                         "Jones", "Garcia,", "David", "Out", "Injury/Illness", "-", "Left", "Knee", "Soreness",
                         "Lively", "II,", "Dereck", "Out", "Injury/Illness", "-", "Right", "Foot", "Surgery"]))

    assert rows["David Jones Garcia"][:2] == ("DAL", "OUT")
    assert rows["Dereck Lively II"][:2] == ("DAL", "OUT")
    assert rows["David Jones Garcia"][2] == "Injury/Illness - Left Knee Soreness"


def test_a_name_off_the_roster_is_never_guessed(roster_dir):
    # "Jalen Wilson" exists, but on ATL: the repair is scoped to the row's team, so it does not fire.
    rows = _rows(_parse(["DAL@SAS", "Dallas", "Mavericks",
                         "Lively", "II,", "Dereck", "Out", "Injury/Illness", "-", "Right", "ACL", "Tear",
                         "Wilson,", "Jalen", "Out", "Injury/Illness", "-", "Left", "Knee"]))

    assert "Jalen Wilson" not in rows
    assert rows["Jalen Tear Wilson"][:2] == ("DAL", "OUT")


def test_without_a_roster_rows_still_never_merge(tmp_path, monkeypatch):
    monkeypatch.setattr(inj, "paths", types.SimpleNamespace(data_processed=tmp_path, data_root=tmp_path))
    monkeypatch.setattr(inj, "PdfReader", _StubPdfReader)

    rows = _rows(_parse(GSW_STREAM))

    assert set(rows) == {"Jimmy Butler III", "Moses Moody"}
    assert rows["Moses Moody"][1] == "OUT"


def test_an_unknown_status_word_cannot_carry_a_row_into_the_next(roster_dir):
    rows = _rows(_parse(["LAC@GSW", "Golden", "State", "Warriors",
                         "Curry,", "Stephen", "Unlisted", "-",
                         "Moody,", "Moses", "Out", "Injury/Illness", "-", "Left", "Patellar"]))

    assert set(rows) == {"Moses Moody"}


def test_the_cleaner_repairs_by_roster_and_refuses_merged_rows(roster_dir):
    df = pd.DataFrame([
        {"team": "CLE", "player": "Khalifa Tendinopathy Diop", "status": "OUT", "injury": "", "date": "2026-10-22"},
        {"team": "GSW", "player": "Stephen Available - Moody, Moses Curry", "status": "OUT", "injury": "",
         "date": DATE},
        {"team": "CLE", "player": "Jarrett Allen", "status": "QUESTIONABLE", "injury": "", "date": "2026-10-22"},
    ])

    out = inj._clean_injury_player_names(df, date_str="2026-10-22")

    assert out["player"].tolist() == ["Khalifa Diop", "Jarrett Allen"]


def test_update_injuries_writes_the_repaired_rows(roster_dir, monkeypatch):
    """The real write path: fetch -> _parse_pdf_rows -> cleaner -> raw/injuries.csv."""
    stream = GSW_STREAM + ATL_STREAM
    monkeypatch.setattr(inj.NBAOfficialInjuryReportScraper, "_latest_pdf_url_for_date",
                        lambda self, d: f"https://example.invalid/Injury-Report_{d}_05_00PM.pdf")
    monkeypatch.setattr(inj.NBAOfficialInjuryReportScraper, "_download_pdf", lambda self, url: _pdf(stream))
    target = roster_dir / "raw" / "injuries.csv"

    inj.NBAInjuryDatabase(filepath=str(target)).update_injuries(date_str=DATE)

    written = pd.read_csv(target)
    got = {(r.team, r.player): r.status for r in written.itertuples()}
    assert got == {
        ("GSW", "Jimmy Butler III"): "OUT",
        ("GSW", "Moses Moody"): "OUT",
        ("ATL", "RayJ Dennis"): "QUESTIONABLE",
        ("ATL", "Keshon Gilbert"): "QUESTIONABLE",
        ("ATL", "Mouhamed Gueye"): "OUT",
        ("ATL", "Henri Veesaar"): "OUT",
        ("ATL", "Jalen Wilson"): "QUESTIONABLE",
        ("ORL", "Anthony Black"): "OUT",
    }
