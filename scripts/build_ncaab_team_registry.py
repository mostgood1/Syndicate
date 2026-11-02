"""Fetch the ESPN Division I men's basketball team list into a git-tracked registry.

WHY A COMMITTED CSV, AND WHY NOT UNDER `data/`
----------------------------------------------
NCAAF's equivalent snapshot lives at
`data/ncaaf_source/source_artifacts/data/processed/team_registry/`, and that
placement has bitten twice. `_soccer_alias_to_name` is DERIVED from artifacts
under `data/`, and in a checkout without them it builds an **empty map** in
silence -- `canonical_team("soccer", ...)` returned None for every club and the
failure looked like a join bug rather than a missing file. A session worktree
excludes `data/` by default (34,690 of 37,745 tracked files), so a map derived
from there is empty in exactly the tree where the tests run.

This registry is 362 rows of a slow-moving, closed set. It travels with the
code instead, beside `syndicate/features/shared/measured_bucket_skill.json`,
which is the existing precedent for a data file inside the package. An empty
map then means the file was deleted, not that the mirror was thin.

    py -3 scripts/build_ncaab_team_registry.py            # refresh in place
    py -3 scripts/build_ncaab_team_registry.py --check    # CI: is it stale?
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import sys
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from syndicate.features.college_basketball.league import league_for  # noqa: E402

# `--league wncaab` (lane wncaab-module, 2026-11-02) writes the women's registry from ESPN's women's
# list; the default stays the men's, byte for byte.
DEST = league_for("ncaab").registry_csv
SOURCE_URL = league_for("ncaab").teams_url
FIELDS = ("espn_id", "school", "display_name", "short_display_name", "abbreviation", "mascot", "slug")


def fetch_rows(source_url: str = SOURCE_URL) -> list[dict[str, str]]:
    request = urllib.request.Request(source_url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=60) as response:
        payload = json.loads(response.read().decode())
    entries = payload["sports"][0]["leagues"][0]["teams"]
    rows = []
    for entry in entries:
        team = entry.get("team") or {}
        school = str(team.get("location") or "").strip()
        if not school:
            # No school name means no canonical to key on; such a row cannot
            # contribute an alias and is dropped rather than guessed at.
            continue
        rows.append({
            "espn_id": str(team.get("id") or "").strip(),
            "school": school,
            "display_name": str(team.get("displayName") or "").strip(),
            "short_display_name": str(team.get("shortDisplayName") or "").strip(),
            "abbreviation": str(team.get("abbreviation") or "").strip(),
            "mascot": str(team.get("name") or "").strip(),
            "slug": str(team.get("slug") or "").strip(),
        })
    rows.sort(key=lambda r: (r["school"].lower(), r["espn_id"]))
    return rows


def render(rows: list[dict[str, str]]) -> str:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=FIELDS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="exit 1 if the committed file differs from the source")
    parser.add_argument("--league", default="ncaab", choices=("ncaab", "wncaab"))
    args = parser.parse_args()

    league = league_for(args.league)
    dest = league.registry_csv
    rows = fetch_rows(league.teams_url)
    rendered = render(rows)
    current = dest.read_text(encoding="utf-8") if dest.exists() else ""

    if args.check:
        if rendered == current:
            print(f"up to date: {len(rows)} teams")
            return 0
        print(f"STALE: source has {len(rows)} teams; committed file differs", file=sys.stderr)
        return 1

    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(rendered, encoding="utf-8")
    print(f"wrote {dest.relative_to(REPO)}  ({len(rows)} teams, {len(rendered)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
