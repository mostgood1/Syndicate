#!/bin/bash
# Read-only, nice 19: what a failing soccer refresh run (20261127_200057) left behind.
d=~/syndicate-prod/data/reports/migration_runs/2026-11-27/odds_refresh_20261127_200057
ls -la "$d"
for f in "$d"/*.json; do echo "@@ $f"; head -c 1500 "$f"; echo; done
echo "@@ stderr: line kinds"
grep -a -o -E '^\[[a-z_]+\] [A-Z_]+|\[[a-z_]+\] [A-Z_]{4,}' "$d/odds_refresh.stderr.txt" | sort | uniq -c | sort -rn | head -20
echo "@@ stderr: lines that are not the memory/process debug family"
grep -a -v -E 'PROCESS_ENUM_DEBUG|PROCESS_TREE_MEMORY|CONTAINER_MEMORY|THREADS|CHILD_PROCESSES|ALL_PROCESS_MEMORY' "$d/odds_refresh.stderr.txt" | cut -c1-300 | head -40
echo "@@ stdout tail"
for f in "$d"/*stdout*; do echo "-- $f"; tail -c 3000 "$f"; done
