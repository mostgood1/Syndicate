"""WNBA raw/injuries.csv keeps each date's snapshot (lane wnba-injury-snapshot-overwrite; the NBA copy is #730).

The file is a stack of DAILY snapshots, and every reader takes the latest snapshot on or before its date. The WNBA
writer deleted ``--date``'s rows on every fetch while ESPN dated its rows ``datetime.now()``. Measured on the fleet:
- a fetch for D run after midnight deleted D's snapshot: the file has no 10-12, and the last 10-12 fetch ran
  10-13 00:00:03 CDT;
- a prefetch for D+1 deleted nothing of D's and MERGED its scrape into D's rows, so a player who had left ESPN's
  page stayed listed in D until a same-day fetch. With the NBA's rows in the file (#731), these prefetches flipped
  the 10-21 snapshot back and forth and caused 13 WNBA sim rebuilds.

Every case goes through the real ``update_injuries`` and the real ESPN parser. Only the network
(``requests.Session.get``) and the clock are stubbed, so these tests also run against the old file: there, the
late-fetch (writer, readers, CLI), prefetch, midnight-straddle and UTC-process tests fail (6); the two guards
(same-day fetch, no byte churn between a prefetch and a same-day fetch) pass on both. Three mutants of the fix each
fail their own tests: a per-row stamp (straddle), the process clock (UTC), the old replace-by-date_str rule (4).
"""

from __future__ import annotations

import types
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pandas as pd
import pytest
import requests

import syndicate.features.wnba.source_cli.scrapers.injuries as inj
from syndicate.features.shared import basketball_props_availability as props_availability
from syndicate.features.shared import wnba_sim_availability as sim_availability

CT = ZoneInfo("America/Chicago")
ESPN_URL = "https://www.espn.com/wnba/injuries"


def _espn_html(rows: dict[str, list[tuple[str, str]]]) -> str:
    """ESPN's WNBA injuries page: one titled table per team, PLAYER | POS | DATE | INJURY | STATUS."""
    blocks = []
    for team, players in rows.items():
        body = "".join(f"<tr><td>{p}</td><td>G</td><td>Oct 20</td><td>Knee</td><td>{s}</td></tr>" for p, s in players)
        blocks.append(
            f'<div class="Table__Title">{team}</div><div class="ResponsiveTable"><table>'
            "<tr><th>PLAYER</th><th>POS</th><th>DATE</th><th>INJURY</th><th>STATUS</th></tr>"
            f"{body}</table></div>"
        )
    return "<html><body>" + "".join(blocks) + "</body></html>"


class _Resp:
    def __init__(self, text: str) -> None:
        self.status_code = 200
        self.ok = True
        self.text = text
        self.content = text.encode("utf-8")
        self.headers = {"content-type": "text/html"}

    def raise_for_status(self) -> None:
        return None


@pytest.fixture
def world(tmp_path, monkeypatch):
    """A WNBA source root with no roster (the fleet's case: the roster cleaners are no-ops), ESPN stubbed.

    ``world.espn`` is the page's rows; ``world.clock(...)`` pins the instants ``datetime.now`` returns, in order.
    """
    source_root = tmp_path / "wnba_source"
    data_root = source_root / "data"
    processed = data_root / "processed"
    processed.mkdir(parents=True)
    state = types.SimpleNamespace(
        source_root=source_root,
        processed=processed,
        target=data_root / "raw" / "injuries.csv",
        espn={},
        requested=[],
    )
    state.target.parent.mkdir(parents=True)

    def fake_get(self, url, **kwargs):
        state.requested.append(url)
        if url == ESPN_URL:
            return _Resp(_espn_html(state.espn))
        raise AssertionError(f"unexpected URL {url}")

    def clock(*instants: datetime, process_tz=CT) -> None:
        """Each now() call takes the next instant; the last one repeats. ``process_tz`` is the process clock's
        zone, which is what a bare now() reads (the fleet's is CDT)."""
        calls = {"n": 0}

        class _Clock(datetime):
            @classmethod
            def now(cls, tz=None):
                moment = instants[min(calls["n"], len(instants) - 1)]
                calls["n"] += 1
                local = moment.astimezone(tz or process_tz)
                return local if tz is not None else local.replace(tzinfo=None)

        monkeypatch.setattr(inj, "datetime", _Clock)

    monkeypatch.setattr(requests.Session, "get", fake_get)
    monkeypatch.setattr(inj, "paths", types.SimpleNamespace(data_processed=processed, data_root=data_root))
    state.clock = clock
    return state


def _seed(target, snapshots: dict[str, list[tuple[str, str]]]) -> None:
    """Write earlier snapshots: {date: [(team, player), ...]}, every player OUT."""
    pd.DataFrame(
        [
            {"team": team, "player": player, "status": "OUT", "injury": "Knee", "date": date}
            for date, players in snapshots.items()
            for team, player in players
        ]
    ).to_csv(target, index=False)


def _day(target, date: str) -> set[tuple[str, str]]:
    written = pd.read_csv(target)
    day = written[written["date"].astype(str) == date]
    return {(r.team, r.player) for r in day.itertuples()}


def _dates(target) -> list[str]:
    return sorted(set(pd.read_csv(target)["date"].astype(str)))


def _fetch(world, date_str: str) -> None:
    inj.NBAInjuryDatabase(filepath=str(world.target)).update_injuries(date_str=date_str)


# --- a late fetch for D (after Central midnight) -----------------------------------------------------------------


def test_late_fetch_for_d_keeps_ds_snapshot(world):
    """The fleet's missing 10-12: the last 10-12 fetch ran 10-13 00:00:03 CDT. The old writer deleted 10-12's rows
    and wrote the scrape as 10-13's, so 10-12 was left with nothing."""
    _seed(world.target, {"2026-10-11": [("ATL", "Matilde Villa")], "2026-10-12": [("ATL", "Matilde Villa"), ("ATL", "Aaliyah Nye")]})
    world.espn = {"Atlanta Dream": [("Matilde Villa", "Out")]}  # Nye is back by midnight
    world.clock(datetime(2026, 10, 13, 0, 0, 3, tzinfo=CT))

    _fetch(world, "2026-10-12")

    assert _day(world.target, "2026-10-12") == {("ATL", "Matilde Villa"), ("ATL", "Aaliyah Nye")}
    assert _day(world.target, "2026-10-13") == {("ATL", "Matilde Villa")}
    assert _day(world.target, "2026-10-11") == {("ATL", "Matilde Villa")}


def test_late_fetch_for_d_leaves_the_readers_on_ds_snapshot(world):
    """What the deletion did downstream: a reader for D fell back a day, to D-1's snapshot."""
    _seed(world.target, {"2026-10-11": [("ATL", "Matilde Villa")], "2026-10-12": [("ATL", "Matilde Villa"), ("ATL", "Aaliyah Nye")]})
    world.espn = {"Atlanta Dream": [("Matilde Villa", "Out")]}
    world.clock(datetime(2026, 10, 13, 0, 0, 3, tzinfo=CT))

    _fetch(world, "2026-10-12")

    feed = props_availability.out_players_for_date(source_root=world.source_root, date_str="2026-10-12")
    assert feed["snapshot_date"] == "2026-10-12"
    assert set(feed["out"]) == {"MATILDE VILLA", "AALIYAH NYE"}
    snaps, reason = sim_availability._injury_snapshots(world.processed, props_availability.player_key)
    assert reason == "ok"
    assert sim_availability._snapshot_on_or_before(snaps, "2026-10-12") == "2026-10-12"


# --- a prefetch for D+1 on D -------------------------------------------------------------------------------------


def test_prefetch_for_the_next_day_replaces_todays_snapshot_and_writes_no_future_one(world):
    """10-21: the props refresh prefetched 10-22 / 10-23 hourly. The old writer deleted the (absent) future rows
    and merged the scrape into 10-21's, so a player who had left ESPN's page stayed listed for 10-21."""
    _seed(
        world.target,
        {
            "2026-10-20": [("ATL", "Matilde Villa"), ("GSV", "Iliana Rupert")],
            "2026-10-21": [("ATL", "Matilde Villa"), ("ATL", "Aaliyah Nye"), ("GSV", "Iliana Rupert")],
        },
    )
    world.espn = {"Atlanta Dream": [("Matilde Villa", "Out")], "Golden State Valkyries": [("Iliana Rupert", "Out")]}  # Nye back
    world.clock(datetime(2026, 10, 21, 6, 5, tzinfo=CT))

    _fetch(world, "2026-10-22")

    assert _day(world.target, "2026-10-21") == {("ATL", "Matilde Villa"), ("GSV", "Iliana Rupert")}
    assert _day(world.target, "2026-10-22") == set()
    assert _day(world.target, "2026-10-20") == {("ATL", "Matilde Villa"), ("GSV", "Iliana Rupert")}
    assert _dates(world.target) == ["2026-10-20", "2026-10-21"]
    feed = props_availability.out_players_for_date(source_root=world.source_root, date_str="2026-10-21")
    assert "AALIYAH NYE" not in feed["out"]


def test_prefetch_then_same_day_fetch_write_the_same_bytes(world):
    """No flapping: the hourly prefetch and the live loop's same-day fetch read the same page, so the file's
    bytes (which the live loop hashes to force a re-sim) do not change between them."""
    _seed(world.target, {"2026-10-20": [("ATL", "Matilde Villa")]})
    world.espn = {"Atlanta Dream": [("Matilde Villa", "Out"), ("Aaliyah Nye", "Out")]}
    world.clock(datetime(2026, 10, 21, 6, 5, tzinfo=CT))

    _fetch(world, "2026-10-22")
    after_prefetch = world.target.read_bytes()
    _fetch(world, "2026-10-21")
    after_same_day = world.target.read_bytes()
    _fetch(world, "2026-10-23")

    assert after_prefetch == after_same_day == world.target.read_bytes()


# --- the scrape's date -------------------------------------------------------------------------------------------


def test_a_scrape_parsed_across_midnight_carries_one_date(world):
    """The old parser stamped each ROW with datetime.now(). Since a fetch replaces every date its rows carry, a
    scrape split across midnight would replace D with its first rows only."""
    _seed(world.target, {"2026-10-21": [("ATL", "Matilde Villa"), ("ATL", "Aaliyah Nye"), ("GSV", "Iliana Rupert")]})
    world.espn = {
        "Atlanta Dream": [("Matilde Villa", "Out"), ("Aaliyah Nye", "Out")],
        "Golden State Valkyries": [("Iliana Rupert", "Out")],
    }
    world.clock(datetime(2026, 10, 21, 23, 59, 59, 999000, tzinfo=CT), datetime(2026, 10, 22, 0, 0, 0, 1000, tzinfo=CT))

    _fetch(world, "2026-10-21")

    assert _day(world.target, "2026-10-21") == {("ATL", "Matilde Villa"), ("ATL", "Aaliyah Nye"), ("GSV", "Iliana Rupert")}
    assert _dates(world.target) == ["2026-10-21"]


def test_the_scrape_is_dated_on_the_central_calendar_whatever_the_process_clock(world):
    """The slate calendar is Central (the live loop asks with central_today_iso). The fleet's clock is CDT, but a
    UTC process dated every scrape after 7 PM CDT to tomorrow: a reader for today never saw the evening's report."""
    world.espn = {"Atlanta Dream": [("Matilde Villa", "Out")]}
    world.clock(datetime(2026, 10, 22, 1, 30, tzinfo=timezone.utc), process_tz=timezone.utc)  # 8:30 PM CDT 10-21

    _fetch(world, "2026-10-21")

    assert _dates(world.target) == ["2026-10-21"]


# --- guard: unchanged behaviour ----------------------------------------------------------------------------------


def test_same_day_fetch_replaces_the_days_snapshot(world):
    """Guard, green on both files: a same-day fetch makes the day's snapshot the new scrape (a returned player drops
    off) and touches no other date."""
    _seed(world.target, {"2026-10-20": [("ATL", "Matilde Villa")], "2026-10-21": [("ATL", "Matilde Villa"), ("ATL", "Aaliyah Nye")]})
    world.espn = {"Atlanta Dream": [("Matilde Villa", "Out")]}
    world.clock(datetime(2026, 10, 21, 12, 0, tzinfo=CT))

    _fetch(world, "2026-10-21")

    assert _day(world.target, "2026-10-21") == {("ATL", "Matilde Villa")}
    assert _day(world.target, "2026-10-20") == {("ATL", "Matilde Villa")}
    assert world.requested == [ESPN_URL]


def test_the_fleet_entrypoint_keeps_ds_snapshot_on_a_late_fetch(world):
    """`python -m syndicate.features.wnba.source_cli.cli fetch-injuries --date D` is what both fleet writers run."""
    from click.testing import CliRunner

    from syndicate.features.wnba.source_cli import cli as wnba_cli

    _seed(world.target, {"2026-10-12": [("ATL", "Matilde Villa"), ("ATL", "Aaliyah Nye")]})
    world.espn = {"Atlanta Dream": [("Matilde Villa", "Out")]}
    world.clock(datetime(2026, 10, 13, 0, 0, 3, tzinfo=CT))

    result = CliRunner().invoke(wnba_cli.cli, ["fetch-injuries", "--date", "2026-10-12"])

    assert result.exit_code == 0, result.output
    assert _day(world.target, "2026-10-12") == {("ATL", "Matilde Villa"), ("ATL", "Aaliyah Nye")}
    assert _day(world.target, "2026-10-13") == {("ATL", "Matilde Villa")}
