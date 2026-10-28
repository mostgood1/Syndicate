"""Historical NBA injury feed for research resims (lane basketball-player-distribution step 1d, pre-registered
4c68f36e in .syndicate/findings_2026-10-26_basketball_player_distribution.md).

The resim deletes raw/injuries.csv (there was no NBA injury history), so injured / inactive players kept their
minutes in every historical sim. This rebuilds the feed from the official NBA injury-report PDFs, as of each game:

- each regular-season game in the ESPN summary cache gets the LATEST report stamped at or before tip - 30 min (ET);
  a report published later is never read;
- only that game's two teams' rows are kept, stamped with the game's US date (header UTC - 6 h, as the read script);
- rows go through the production parser unchanged (_parse_pdf_rows + _clean_injury_player_names); teams are the
  report's own, with no roster team correction.

Filenames are hourly (`_05PM`) through about 2025-12-21 and every 15 minutes (`_05_00PM`) after; both are tried.
The PDFs are data: they go into --pdf-dir, and the script never runs from there.

    py -3 scripts/nba_injury_history_build.py --cache DIR --pdf-dir DIR --processed-dir DIR --out CSV
        [--start 2025-11-01 --end 2026-03-01] [--json SUMMARY]
"""
from __future__ import annotations

import argparse
import gzip
import json
import sys
import time
import types
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Tuple
from zoneinfo import ZoneInfo

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PDF_HOST = "https://ak-static.cms.nba.com/referee/injury/"
ET = ZoneInfo("America/New_York")
LEAD = timedelta(minutes=30)
MAX_BACK = timedelta(hours=24)
NBA = {"ATL", "BOS", "BKN", "CHA", "CHI", "CLE", "DAL", "DEN", "DET", "GSW", "HOU", "IND", "LAC", "LAL", "MEM", "MIA",
       "MIL", "MIN", "NOP", "NYK", "OKC", "ORL", "PHI", "PHX", "POR", "SAC", "SAS", "TOR", "UTA", "WAS"}
TRI = {"GS": "GSW", "UTAH": "UTA", "SA": "SAS", "WSH": "WAS", "NO": "NOP", "NY": "NYK"}
COLUMNS = ["date", "team", "player", "status", "injury", "source", "report"]


def games(cache: Path, start: str = "", end: str = "9999") -> List[Dict[str, object]]:
    """Regular-season NBA games in the ESPN summary cache: date (US day), home, away, tip (UTC)."""
    out = []
    for f in sorted(cache.glob("summary_*.json.gz")):
        hdr = json.load(gzip.open(f)).get("header") or {}
        if int((hdr.get("season") or {}).get("type") or 0) != 2:
            continue
        comp = (hdr.get("competitions") or [{}])[0]
        try:
            tip = datetime.strptime(str(comp.get("date") or "")[:16], "%Y-%m-%dT%H:%M").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        sides = {c.get("homeAway"): TRI.get(c["team"].get("abbreviation"), c["team"].get("abbreviation"))
                 for c in comp.get("competitors") or []}
        if not {sides.get("home"), sides.get("away")} <= NBA:
            continue  # ESPN files the All-Star game as season type 2
        day = (tip - timedelta(hours=6)).strftime("%Y-%m-%d")
        if start <= day <= end:
            out.append({"date": day, "home": sides["home"], "away": sides["away"], "tip": tip})
    return out


def report_names(t_et: datetime) -> List[str]:
    """Filenames a report stamped at t_et (ET) can have: the 15-minute form, and the hourly form on the hour."""
    d, h12, ap = t_et.strftime("%Y-%m-%d"), t_et.hour % 12 or 12, "AM" if t_et.hour < 12 else "PM"
    names = [f"Injury-Report_{d}_{h12:02d}_{t_et.minute:02d}{ap}.pdf"]
    if t_et.minute == 0:
        names.append(f"Injury-Report_{d}_{h12:02d}{ap}.pdf")
    return names


def pick_report(tip: datetime, have: Callable[[str], bool]) -> Optional[Tuple[str, datetime]]:
    """The latest report stamped at or before tip - LEAD, walking back in 15-minute steps up to MAX_BACK."""
    t = (tip - LEAD).astimezone(ET).replace(tzinfo=None)
    t = t.replace(minute=t.minute - t.minute % 15, second=0, microsecond=0)
    stop = t - MAX_BACK
    while t > stop:
        for name in report_names(t):
            if have(name):
                return name, t
        t -= timedelta(minutes=15)
    return None


class PdfStore:
    """Reports on disk in pdf_dir, fetched on a miss; misses are remembered in pdf_dir/_missing.json."""

    def __init__(self, pdf_dir: Path, fetch: Optional[Callable[[str], Optional[bytes]]] = None):
        self.dir = pdf_dir
        self.dir.mkdir(parents=True, exist_ok=True)
        self.missing_path = pdf_dir / "_missing.json"
        self.missing = set(json.loads(self.missing_path.read_text())) if self.missing_path.exists() else set()
        self.fetch = fetch
        self.fetched = 0

    def have(self, name: str) -> bool:
        if (self.dir / name).exists():
            return True
        if name in self.missing or self.fetch is None:
            return False
        data = self.fetch(name)
        self.fetched += 1
        if data and data[:4] == b"%PDF":
            (self.dir / name).write_bytes(data)
            return True
        self.missing.add(name)
        return False

    def save(self) -> None:
        self.missing_path.write_text(json.dumps(sorted(self.missing)))


def http_fetch() -> Callable[[str], Optional[bytes]]:
    import requests

    session = requests.Session()
    session.trust_env = False
    session.headers.update({"User-Agent": "Mozilla/5.0"})

    def fetch(name: str) -> Optional[bytes]:
        time.sleep(0.15)
        resp = session.get(PDF_HOST + name, timeout=30)
        return resp.content if resp.status_code == 200 else None

    return fetch


def build(game_list: Iterable[Dict[str, object]], store: PdfStore, parse: Callable[[bytes, str], pd.DataFrame],
          roster_keys: set, norm: Callable[[str], str]) -> Tuple[pd.DataFrame, Dict[str, object]]:
    parsed: Dict[str, pd.DataFrame] = {}
    rows, ages, fmt = [], [], Counter()
    n_games = no_report = team_games = listed = 0
    for g in game_list:
        n_games += 1
        hit = pick_report(g["tip"], store.have)
        if hit is None:
            no_report += 1
            continue
        name, t_et = hit
        fmt["15min" if name.count("_") == 3 else "hourly"] += 1
        ages.append((g["tip"].astimezone(ET).replace(tzinfo=None) - t_et).total_seconds() / 60)
        if name not in parsed:
            # the report's own date: the game-day stamp of a pre-midnight report is the filename's date
            parsed[name] = parse((store.dir / name).read_bytes(), name.split("_")[1])
        df = parsed[name]
        for team in (g["home"], g["away"]):
            team_games += 1
            sub = df[df["team"] == team] if not df.empty else df
            listed += int(not sub.empty)
            for r in sub.itertuples():
                rows.append({"date": g["date"], "team": team, "player": r.player, "status": r.status,
                             "injury": getattr(r, "injury", ""), "source": "nba_official", "report": name})
    out = pd.DataFrame(rows, columns=COLUMNS).drop_duplicates(["date", "team", "player"], keep="last")
    off = int(sum(norm(p) not in roster_keys for p in out["player"])) if len(out) else 0
    s = pd.Series(ages, dtype=float)
    summary = {
        "games": n_games, "games_no_report": no_report, "team_games": team_games, "team_games_listed": listed,
        "rows": len(out), "rows_off_roster": off, "reports_used": len(parsed), "format": dict(fmt),
        "report_age_min": {q: float(s.quantile(q)) for q in (0.05, 0.5, 0.95)} if len(s) else {},
        "status": dict(Counter(out["status"])),
        "gates": {
            "B1_every_game_has_report": no_report == 0,
            "B2_listed_ge_95pct": team_games > 0 and listed >= 0.95 * team_games,
            "B3_off_roster_le_5pct": len(out) > 0 and off <= 0.05 * len(out),
        },
    }
    return out, summary


def production_parser(processed_dir: Path, work_dir: Path):
    """The production parser, repairing names against the roster AS OF each report's date. Its name repair accepts a
    word-dropped name only when it is exactly one roster player on the report's team, so an end-of-season roster
    left every traded player's garbled name unrepaired (measured: 'Anthony Way Davis', 'Collin Way Sexton')."""
    import syndicate.features.nba.source_cli.scrapers.injuries as m
    from scripts.basketball_scenario_rates import asof_roster

    roster_file = m.pick_rosters_file(processed_dir, season=None)
    roster = pd.read_csv(roster_file)
    logs = pd.read_csv(processed_dir / "player_logs.csv",
                       usecols=["PLAYER_ID", "PLAYER_NAME", "TEAM_ABBREVIATION", "GAME_DATE"])
    logs["GAME_DATE"] = logs["GAME_DATE"].astype(str).str[:10]

    def parse(pdf: bytes, date_str: str) -> pd.DataFrame:
        day_dir = work_dir / date_str
        if not (day_dir / roster_file.name).exists():
            day_dir.mkdir(parents=True, exist_ok=True)
            roster.to_csv(day_dir / roster_file.name, index=False)
            logs[logs["GAME_DATE"] < date_str].to_csv(day_dir / "player_logs.csv", index=False)
            asof_roster(day_dir, date_str)
        m.paths = types.SimpleNamespace(data_processed=day_dir, data_root=day_dir.parent)
        df = m.NBAOfficialInjuryReportScraper()._parse_pdf_rows(pdf, date_str=date_str)
        if df is None or df.empty:
            return pd.DataFrame(columns=["team", "player", "status", "injury"])
        df = m._clean_injury_player_names(df, date_str=date_str)
        df["team"] = df["team"].astype(str).str.upper().map(lambda t: TRI.get(t, t))
        return df

    return parse, set(roster["PLAYER"].dropna()) | set(logs["PLAYER_NAME"].dropna())


def main(argv: Optional[Iterable[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cache", required=True, type=Path, help="ESPN summary cache (summary_<eid>.json.gz)")
    ap.add_argument("--pdf-dir", required=True, type=Path)
    ap.add_argument("--processed-dir", required=True, type=Path, help="holds rosters_<season>.csv (name cleaning)")
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--start", default="")
    ap.add_argument("--end", default="9999")
    ap.add_argument("--json", type=Path)
    args = ap.parse_args(list(argv) if argv is not None else None)

    from syndicate.features.shared.basketball_props_smart_sim import _norm_name_key as norm

    # B3 counts names the SIM cannot match: its own key (which reads 'Gilgeous- Alexander' as the roster name) over
    # every name an as-of pool can hold -- the season roster file plus everyone in player_logs.
    parse, names = production_parser(args.processed_dir, args.out.parent / "injury_asof_rosters")
    roster_keys = {norm(x) for x in names}
    store = PdfStore(args.pdf_dir, http_fetch())
    try:
        out, summary = build(games(args.cache, args.start, args.end), store, parse, roster_keys, norm)
    finally:
        store.save()
    summary["fetched"] = store.fetched
    out.to_csv(args.out, index=False)
    text = json.dumps(summary, indent=1)
    if args.json:
        args.json.write_text(text)
    print(text)
    return 0 if all(summary["gates"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
