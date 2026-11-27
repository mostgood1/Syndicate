#!/bin/bash
# Read-only, nice 19. R-M at a nightly close: did the after-midnight carry (8455f25c0) give every game still live
# after the roll a card on Today? Usage: bash read_carry.sh <D> <D+1>   e.g. 2026-11-27 2026-11-28
# The roll is 06:00Z on D+1 (midnight CST). Prints the prior-date carryover's builds and D's chip publications
# after the roll; the probe readings' carried chips come from read_carry.py on the Windows side.
D="$1"; N="$2"
LOG=~/syndicate-prod/logs/refresh-worker.log
echo "read_at $(date -u +%H:%M:%SZ) D=$D next=$N"
echo "--- LAYER2_CARRYOVER date=$D on $N 06..11Z"
nice -n 19 grep -E "^${N}T(0[6-9]|1[01]):[0-9:.]+Z .*LAYER2_CARRYOVER date=${D}" "$LOG" | grep -oE '^[^ ]+|decision=[^ ]+|reason=[^ ]+|chips_live_now=[^ ]+|live_rows_now=[^ ]+' | paste -sd' ' | sed "s/ ${N}T/\n${N}T/g" | head -40
echo "--- GAME_CHIPS_PUBLISHED date=$D on $N 05:50..11Z"
nice -n 19 grep -E "^${N}T(0[5-9]|1[01]):[0-9:.]+Z .*GAME_CHIPS_PUBLISHED.*date=${D}" "$LOG" | grep -oE '^[^ ]+' | head -40
