#!/bin/bash
# Read-only, nice 19: soccer live pricing while the lens was frozen at 20:01:59Z (20:02Z-21:47Z 11-27), against the hour before.
cd ~/syndicate-prod/logs || exit 0
tail -n 900000 refresh-worker.log | grep -a -E 'LIVE_GAMELINE_JOIN sport=soccer|LIVE_PROJECTION_JOIN sport=soccer' \
  | awk '$1 >= "2026-11-27T19:00" && $1 <= "2026-11-27T22:10"' > /tmp/ssp1127.txt
echo "lines $(wc -l < /tmp/ssp1127.txt)"
echo '@@ LIVE_GAMELINE_JOIN soccer: time, index, projected, priceable, withheld, display, why (first 200 chars) @@'
grep -a 'LIVE_GAMELINE_JOIN' /tmp/ssp1127.txt | awk 'NR%2==1' | sed -E 's/^([^ ]+).*index=([0-9]+).*projected=([0-9]+) priceable=([0-9]+) withheld=([0-9]+) display=([0-9]+).*why=(.{0,200}).*/\1 idx=\2 proj=\3 priceable=\4 withheld=\5 display=\6 why=\7/' | cut -c1-330
echo '@@ LIVE_PROJECTION_JOIN soccer (props): time edged edged_modelled lens_live_games @@'
grep -a 'LIVE_PROJECTION_JOIN' /tmp/ssp1127.txt | sed -E 's/^([^ ]+).* edged=([0-9]+) edged_modelled=([0-9]+).*lens_live_games=([0-9]+).*/\1 edged=\2 edged_modelled=\3 lens_live_games=\4/' | cut -c1-120
