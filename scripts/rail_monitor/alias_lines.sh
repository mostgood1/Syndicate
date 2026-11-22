#!/bin/bash
# Which fleet role logs carry the live join's alias counters (rows_joined_by_team_alias / alias_keys). Read-only.
cd /home/amyn/syndicate-prod/logs || exit 1
for f in refresh-worker.log live-odds-worker.log web.log; do
  n=$(nice -n 19 grep -a -c 'rows_joined_by_team_alias' "$f")
  echo "== $f rows_joined_by_team_alias lines=$n"
  nice -n 19 grep -a 'rows_joined_by_team_alias' "$f" | grep -E '^20[0-9]{2}-' | grep -v ALL_PROCESS_MEMORY | tail -2 | cut -c1-320
done
