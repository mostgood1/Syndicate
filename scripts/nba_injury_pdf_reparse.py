"""Re-parse official NBA injury-report PDFs with an old and the current parser, and count what changed.

Lane nba-injury-pdf-parser. Each PDF goes through the write path's two steps, ``_parse_pdf_rows`` and
``_clean_injury_player_names``, once with the parser at ``--old-rev`` and once with the working tree's.
Both use the same roster file. Reported per report and in total:

- rows written;
- rows whose name is on no roster (exact name key, any team): the sim can never match them;
- status changes per (team, player): a player gaining or losing an EXCLUDING status (the SmartSim's set),
  a row only one side writes, and other status changes.

The PDFs are data: fetch them yourself into an empty directory (``--fetch`` does it), never run from there.

    py -3 scripts/nba_injury_pdf_reparse.py --pdf-dir <dir> --processed-dir <dir with rosters_<season>.csv>
        [--old-rev origin/main] [--fetch 2026-10-21 ...] [--json out.json]
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import subprocess
import sys
import tempfile
import time
import types
from collections import Counter
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import syndicate.features.nba.source_cli.scrapers.injuries as current_mod  # noqa: E402

MODULE_PATH = "syndicate/features/nba/source_cli/scrapers/injuries.py"
EXCLUDING = {"OUT", "DOUBTFUL", "SUSPENDED", "INACTIVE", "REST"}  # basketball_props_smart_sim's exclusion set
PDF_HOST = "https://ak-static.cms.nba.com/referee/injury/"
NAME_RE = re.compile(r"Injury-Report_(\d{4}-\d{2}-\d{2})_(\d{2})_(\d{2})(AM|PM)\.pdf$")


def _load_rev(rev: str):
    src = subprocess.run(["git", "-C", str(ROOT), "show", f"{rev}:{MODULE_PATH}"], check=True,
                         capture_output=True).stdout
    path = Path(tempfile.mkdtemp()) / "injuries_rev.py"
    path.write_bytes(src)
    spec = importlib.util.spec_from_file_location("syndicate.features.nba.source_cli.scrapers._injuries_rev", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fetch(pdf_dir: Path, dates: list[str]) -> None:
    import requests

    session = requests.Session()
    session.trust_env = False
    session.headers.update({"User-Agent": "Mozilla/5.0"})
    for date_str in dates:
        for hour in range(24):
            for minute in (0, 30):
                name = f"Injury-Report_{date_str}_{hour % 12 or 12:02d}_{minute:02d}{'AM' if hour < 12 else 'PM'}.pdf"
                if (pdf_dir / name).exists():
                    continue
                resp = session.get(PDF_HOST + name, timeout=30)
                if resp.status_code == 200 and resp.content[:4] == b"%PDF":
                    (pdf_dir / name).write_bytes(resp.content)
                time.sleep(0.2)


def _report_key(path: Path) -> tuple[str, int]:
    m = NAME_RE.search(path.name)
    hour = int(m.group(2)) % 12 + (12 if m.group(4) == "PM" else 0)
    return m.group(1), hour * 60 + int(m.group(3))


def _written(module, pdf: bytes, date_str: str) -> pd.DataFrame:
    df = module.NBAOfficialInjuryReportScraper()._parse_pdf_rows(pdf, date_str=date_str)
    if df is None or df.empty:
        return pd.DataFrame(columns=["team", "player", "status", "injury", "date"])
    return module._clean_injury_player_names(df, date_str=date_str)


def _status_map(df: pd.DataFrame, norm) -> dict[tuple[str, str], tuple[str, str]]:
    return {(r.team, norm(r.player)): (r.player, r.status) for r in df.itertuples()}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pdf-dir", required=True, type=Path)
    ap.add_argument("--processed-dir", required=True, type=Path, help="holds rosters_<season>.csv")
    ap.add_argument("--old-rev", default="origin/main")
    ap.add_argument("--fetch", nargs="*", default=[], help="dates to download first (YYYY-MM-DD)")
    ap.add_argument("--json", type=Path)
    args = ap.parse_args()

    args.pdf_dir.mkdir(parents=True, exist_ok=True)
    if args.fetch:
        _fetch(args.pdf_dir, args.fetch)

    old_mod = _load_rev(args.old_rev)
    fake_paths = types.SimpleNamespace(data_processed=args.processed_dir, data_root=args.processed_dir.parent)
    for module in (old_mod, current_mod):
        module.paths = fake_paths
    norm = current_mod._norm_player_name_key
    roster_file = current_mod.pick_rosters_file(args.processed_dir, season=None)
    roster_keys = {norm(p) for p in pd.read_csv(roster_file)["PLAYER"].dropna()}

    pdfs = sorted(args.pdf_dir.glob("Injury-Report_*.pdf"), key=_report_key)
    totals: Counter = Counter()
    per_report = []
    players: dict[str, Counter] = {"gained_exclusion": Counter(), "lost_exclusion": Counter(),
                                   "off_roster_old": Counter(), "off_roster_new": Counter(),
                                   "only_old": Counter(), "only_new": Counter()}
    for path in pdfs:
        date_str, _ = _report_key(path)
        pdf = path.read_bytes()
        old_df, new_df = _written(old_mod, pdf, date_str), _written(current_mod, pdf, date_str)
        old_map, new_map = _status_map(old_df, norm), _status_map(new_df, norm)
        row = {"report": path.name, "rows_old": len(old_df), "rows_new": len(new_df)}
        for side, df in (("old", old_df), ("new", new_df)):
            off = [p for p in df["player"] if norm(p) not in roster_keys]
            row[f"off_roster_{side}"] = len(off)
            players[f"off_roster_{side}"].update(off)
        # Only a rostered name can exclude anyone from a sim pool; an off-roster key never matches.
        gained = lost = only_old = only_new = other = 0
        for key in {k for k in set(old_map) | set(new_map) if k[1] in roster_keys}:
            o, n = old_map.get(key), new_map.get(key)
            o_ex = bool(o and o[1] in EXCLUDING)
            n_ex = bool(n and n[1] in EXCLUDING)
            label = f"{key[0]} {(n or o)[0]}: {o[1] if o else '-'} -> {n[1] if n else '-'}"
            if n_ex and not o_ex:
                gained += 1
                players["gained_exclusion"][label] += 1
            elif o_ex and not n_ex:
                lost += 1
                players["lost_exclusion"][label] += 1
            elif o is None:
                only_new += 1
                players["only_new"][label] += 1
            elif n is None:
                only_old += 1
                players["only_old"][label] += 1
            elif o[1] != n[1]:
                other += 1
        row.update(gained_exclusion=gained, lost_exclusion=lost, only_old=only_old, only_new=only_new,
                   other_status_change=other)
        per_report.append(row)
        totals.update({k: v for k, v in row.items() if k != "report"})

    print(f"reports: {len(pdfs)}  ({pdfs[0].name if pdfs else '-'} .. {pdfs[-1].name if pdfs else '-'})")
    print(f"roster: {roster_file}  ({len(roster_keys)} name keys)")
    for key in ("rows_old", "rows_new", "off_roster_old", "off_roster_new", "gained_exclusion", "lost_exclusion",
                "only_old", "only_new", "other_status_change"):
        print(f"  {key:22s} {totals[key]:6d}")
    for key, counter in players.items():
        print(f"{key}: {len(counter)} players")
        for label, count in counter.most_common():
            print(f"    {count:4d}  {label}")
    if args.json:
        args.json.write_text(json.dumps({"totals": dict(totals), "per_report": per_report,
                                         "players": {k: dict(v) for k, v in players.items()}}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
