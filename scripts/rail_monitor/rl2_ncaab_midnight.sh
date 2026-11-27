#!/bin/bash
# Read-only, nice 19. R-L (2) at the 11-26 close: NCAAB live gameline builds across the midnight CT roll
# (05:30Z..07:30Z 11-27), by date shard, per 10 min: builds, index (games in snapshot), considered, written.
LOG=~/syndicate-prod/logs/refresh-worker.log
nice -n 19 grep -E '^2026-11-27T0[5-7]:[0-9:.]+Z \[book_grid\] LIVE_GAMELINE_BUILD sport=ncaab ' "$LOG" \
 | awk '{
   ts=substr($1,1,15); d=""; idx=""; con=""; wr="";
   for(i=1;i<=NF;i++){ if($i ~ /^date=/) d=substr($i,6); if($i ~ /^index=/) idx=substr($i,7);
     if($i ~ /^considered=/) con=substr($i,12); if($i ~ /^written=/) wr=substr($i,9) }
   k=ts"0 "d; n[k]++; ix[k]=ix[k]" "idx; c[k]+=con; w[k]+=wr
 } END { for(k in n) printf "%s builds=%d index=[%s] considered_sum=%d written_sum=%d\n", k, n[k], ix[k], c[k], w[k] }' | sort
echo "--- last ncaab build per date shard"
for d in 2026-11-26 2026-11-27; do
  nice -n 19 grep -E "LIVE_GAMELINE_BUILD sport=ncaab date=$d " "$LOG" | tail -1 | cut -c1-230
done
echo "--- live bets placed on the two late games? (LIVE_BET lines naming them, 05:00Z..08:00Z)"
nice -n 19 grep -E '^2026-11-27T0[5-7]' ~/syndicate-prod/logs/live-odds-worker.log | grep -ciE 'gonzaga|oregon ducks'
