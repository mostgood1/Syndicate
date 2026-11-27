#!/bin/bash
# Read-only, nice 19: soccer live-lens memory-gate skips on live-odds-worker, 11-27 (and the days before, for a rate).
cd ~/syndicate-prod/logs || exit 0
tail -n 900000 live-odds-worker.log | grep -a 'LIVE_LENS_TICK_DIAG' > /tmp/lltd1127.txt
echo "all DIAG lines in tail: $(wc -l < /tmp/lltd1127.txt)"
echo '@@ soccer low_headroom per UTC hour (11-25..11-27) @@'
grep -a 'sport=soccer ok=False reason=low_headroom' /tmp/lltd1127.txt | cut -c1-13 | sort | uniq -c | awk '$2 >= "2026-11-25"'
echo '@@ other sports low_headroom per day @@'
grep -a 'reason=low_headroom' /tmp/lltd1127.txt | grep -a -v 'sport=soccer' | sed -E 's/^(.{10}).*sport=([a-z]+).*/\1 \2/' | sort | uniq -c | tail -12
echo '@@ first / last soccer skip 11-27 + one headroom sample @@'
grep -a 'sport=soccer ok=False reason=low_headroom' /tmp/lltd1127.txt | awk '$1 >= "2026-11-27"' | sed -n '1p;$p' | cut -c1-420
echo '@@ soccer lens tick True at (11-27 19:00-22:10Z) @@'
tail -n 900000 live-odds-worker.log | grep -a 'TICK_COMPLETE' | awk '$1 >= "2026-11-27T19:00" && $1 <= "2026-11-27T22:10"' | grep -a -o -E "^[^ ]+|'soccer': (True|False)" | paste - - | grep True
echo '@@ container memory pct, 10-min max 19:30-22:10Z @@'
tail -n 900000 live-odds-worker.log | grep -a 'ALL_PROCESS_MEMORY' | awk '$1 >= "2026-11-27T19:30" && $1 <= "2026-11-27T22:10"' \
  | sed -E 's/^(.{15}).*"container_memory_pct_of_max": ([0-9.]+).*/\1 \2/' | awk '{if($2>m[$1])m[$1]=$2; if(!($1 in mn)||$2<mn[$1])mn[$1]=$2} END{for(k in m)print k, "min", mn[k], "max", m[k]}' | sort
