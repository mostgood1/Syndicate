"""A/B on the REAL ASA pull (lane mls-ratings-season-rollover): the MLS ratings the old branch builds
(`compute_team_ratings(fetch_asa_mls_team_history(today.year), as_of, allow_undated=True)`) against the new
`_load_team_ratings("mls", ...)`, for 2026 build dates. Read-only: public ASA GETs; nothing on the fleet is touched.
  <fleet venv> mls_rollover_ab.py <path to build_soccer_artifacts.py> [as_of ...]
Then the same for a 2027 pre-opener date, to show what changes there (old: 0 teams; new: last season's teams)."""
import importlib.util
import json
import sys
from pathlib import Path

script = Path(sys.argv[1])
dates = sys.argv[2:] or ["2026-11-28", "2026-11-29", "2026-12-05"]
spec = importlib.util.spec_from_file_location("bsa_ab", script)
bsa = importlib.util.module_from_spec(spec)
sys.path.insert(0, str(script.resolve().parents[1]))
spec.loader.exec_module(bsa)
same = 0
for as_of in dates:
    old_rows = bsa.fetch_asa_mls_team_history(int(as_of[:4]))  # today.year == as_of's year for every 2026 date
    old = bsa.compute_team_ratings(old_rows, as_of=as_of, allow_undated=True)
    new = bsa._load_team_ratings("mls", Path("/nonexistent"), as_of)
    eq = json.dumps(old, sort_keys=True) == json.dumps(new, sort_keys=True)
    same += eq
    print(f"{as_of}: old teams {len(old)} new teams {len(new)} -> {'IDENTICAL' if eq else 'DIFFERS'}; "
          f"games min {min(r['games'] for r in old_rows):g} max {max(r['games'] for r in old_rows):g}")
print(f"{same} of {len(dates)} 2026 dates identical")
pre = "2027-02-27"
old_rows = bsa.fetch_asa_mls_team_history(2027)
old = bsa.compute_team_ratings(old_rows, as_of=pre, allow_undated=True)
new = bsa._load_team_ratings("mls", Path("/nonexistent"), pre)
print(f"{pre} (2027 pre-opener): old code would rate {len(old)} teams (every fixture team then gets the same promoted "
      f"prior); new rates {len(new)} teams, {len({round(v['attack_rating'], 6) for v in new.values()})} distinct attack ratings")
sys.exit(0 if same == len(dates) else 1)
