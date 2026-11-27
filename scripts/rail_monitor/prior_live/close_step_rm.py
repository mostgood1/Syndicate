"""Add one line to the runbook's NIGHTLY CLOSE section: do every R-item not marked DONE (R-M first). .tmp + os.replace."""
import os

W = r"C:\Users\tempadmin\Coding\Syndicate\.claude\worktrees\brave-swanson-6e6c6a"
LINE = ("**Owed readings at every close:** do each `R-` item above that is not marked DONE (from 11-27: R-M, the after-"
        "midnight carry, and the OURS fix's `ours_resim_tick` count), and write each result in the lane and the day's findings.")
for p in (r"C:\tmp\railmon\MONITOR_RUNBOOK.md", os.path.join(W, "scripts", "rail_monitor", "RUNBOOK.md")):
    s = open(p, encoding="utf-8", newline="").read()
    nl = "\r\n" if "\r\n" in s else "\n"
    if LINE in s:
        print("already", p)
        continue
    head = "## NIGHTLY CLOSE"
    assert s.count(nl + head) == 1, p
    k = s.index(nl + head) + len(nl + head)
    e = s.index(nl, k)
    s = s[:e] + nl + nl + LINE + s[e:]
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        f.write(s)
    os.replace(tmp, p)
    print("added", p)
