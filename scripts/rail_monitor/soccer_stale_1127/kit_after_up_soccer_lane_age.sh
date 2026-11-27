#!/bin/bash
# After a load of SYNDICATE_LIVE_GAMELINE_SOCCER_LANE_AGE (shadow or on): read-only, nice 19, refresh-worker log.
# usage: kit_after_up_soccer_lane_age.sh <since_utc e.g. 2026-12-08T09:00>
# Per soccer LIVE_GAMELINE_JOIN line with a match in play (index > 0): lane_age_max (None = the stamp is NOT on),
# priceable, the shadow would-refuse counts, and the two lane reasons in `why` (on refuses by those names).
# PASS shape: every line with index > 0 has a numeric lane_age_max; under shadow, would_refuse appears only on lines
# whose lane_age_max > 600; under on, live_lane_older_than_pricing_ceiling appears only there, and
# live_lane_carries_no_state_time never appears (it would mean an untimed lens).
set -u
S="${1:?usage: kit_after_up_soccer_lane_age.sh <since_utc>}"
cd ~/syndicate-prod/logs || exit 0
tail -n 1500000 refresh-worker.log | grep -a 'LIVE_GAMELINE_JOIN sport=soccer' | awk -v s="$S" '$1 >= s' > /tmp/kasla.txt
echo "soccer join lines since $S: $(wc -l < /tmp/kasla.txt)"
python3 - <<'PY'
import re
n = timed = untimed = over = 0
for l in open("/tmp/kasla.txt", errors="replace"):
    m = re.search(r" index=(\d+) .*?priceable=(\S+) .*?lane_age_max=(\S+) lane_age_would_refuse=(\{[^}]*\}) lane_age_would_refuse_priced=(\{[^}]*\})", l)
    if not m or int(m.group(1)) == 0:
        continue
    n += 1
    age = m.group(3)
    stale = "live_lane_older_than_pricing_ceiling" in l
    absent = "live_lane_carries_no_state_time" in l
    if age == "None":
        untimed += 1
    else:
        timed += 1
        over += float(age) > 600
    if n <= 40 or stale or absent:
        print(l[:24], "games", m.group(1), "priceable", m.group(2), "lane_age_max", age, "would", m.group(4),
              "would_priced", m.group(5), "| stale_reason" if stale else "", "| NO_TIME_REASON" if absent else "")
print(f"lines with a match in play {n}: lane_age_max numeric {timed}, None {untimed}; over 600 s {over}")
PY
