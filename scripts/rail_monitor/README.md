# Rail monitor scripts (copies)

Working copies run from `C:\tmp\railmon` (see RUNBOOK.md); these are the committed backups, so a C:\tmp cleanup cannot lose the always-on monitor. Restore with a copy back to C:\tmp\railmon (dash/ for the dashboard scripts).

`p844_grid_sample.py` and `p844.sh` (the #844 sampler, an owned reading since 11-19) restore to the root of the railmon folder, not dash/.

`make_p851.py` rebuilds `p851_loopstages.py` (the #851 reader, owned reading R-D) from the lane's reader, kept here as `p851_loopstages_src.py`; restore it to C:\tmp\w1124_851\loopstages.py first. `cs_split.py` (dash/) splits cs_raw.json into the two cheat-sheet datasets.

`p838_watch.py` (owned reading R-E) restores to the root of the railmon folder; `odds_lane_838/` holds the lane's readers, which restore to C:\tmp\odds_lane_838.
