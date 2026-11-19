"""Tabulate LIVE_GAMELINE_BUILD for one sport since a UTC time (refresh-worker log).

  cd ~/syndicate-prod && python3 /mnt/c/tmp/railmon/lgb.py <sport> <since_utc>
"""
import re, subprocess, sys

sport, since = sys.argv[1], sys.argv[2]
out = subprocess.run(["grep", "-a", f"LIVE_GAMELINE_BUILD sport={sport} ", "logs/refresh-worker.log"],
                     capture_output=True, text=True, errors="replace").stdout
for l in out.splitlines():
    if "ALL_PROCESS_MEMORY" in l or l[:19] < since[:19]:
        continue

    def g(k):
        m = re.search(k + r"=(\S+)", l)
        return m.group(1) if m else None

    m = re.search(r"withheld_by_reason=(\{[^}]*\})", l)
    print(l[11:19], "considered", g("considered"), "proj", g("projected"), "priceable", g("priceable"),
          "withheld", g("withheld"), "full", g("full_games"), m.group(1) if m else "")
