"""Fix R-M step 1 in both runbooks: check the primary tree's probe by content, not by a commit id. .tmp + os.replace."""
import os

W = r"C:\Users\tempadmin\Coding\Syndicate\.claude\worktrees\brave-swanson-6e6c6a"
old = ("1. Check the primary tree holds the probe change (`git -C C:\\Users\\tempadmin\\Coding\\Syndicate merge-base "
       "--is-ancestor <the probe commit> HEAD`); readings before it hold `carried None`.")
new = ("1. Check the primary tree holds the probe change: `C:\\Users\\tempadmin\\Coding\\Syndicate\\scripts\\"
       "layer2_rail_monitor_probe.py` contains `carry_prior_live=1` (it lands with the auto-ff). Readings taken before it "
       "hold `carried None`.")
for p in (r"C:\tmp\railmon\MONITOR_RUNBOOK.md", os.path.join(W, "scripts", "rail_monitor", "RUNBOOK.md")):
    s = open(p, encoding="utf-8", newline="").read()
    if new in s:
        print("already", p)
        continue
    assert s.count(old) == 1, p
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        f.write(s.replace(old, new))
    os.replace(tmp, p)
    print("fixed", p)
