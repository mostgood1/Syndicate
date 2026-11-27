#!/bin/bash
# Read-only, nice 19. Fix (a) design check: after the 11-27 roll (06:00Z), did the prior-date carryover keep the
# 11-26 board and 11-26 chips fresh while Baylor @ Gonzaga / Texas Tech @ Oregon were live?
LOG=~/syndicate-prod/logs/refresh-worker.log
echo "read_at $(date -u +%H:%M:%SZ)"
echo "--- LAYER2_CARRYOVER 05:50Z..07:59Z 11-27"
nice -n 19 grep -E '^2026-11-27T0[5-7]:[0-9:.]+Z .*LAYER2_CARRYOVER' "$LOG" | cut -c1-260 | head -40
echo "--- LAYER2_FAST_REFRESH date=2026-11-26 after 05:55Z"
nice -n 19 grep -E '^2026-11-27T0[5-7]:[0-9:.]+Z .*LAYER2_FAST_REFRESH.*date=2026-11-26' "$LOG" | grep -oE '^[^ ]+|date=[^ ]+|live_rows=[^ ]+|chips_live[a-z_]*=[^ ]+|elapsed_s=[^ ]+|rows=[^ ]+' | paste -sd' ' | sed 's/ 2026-11-27T/\n2026-11-27T/g' | head -30
echo "--- GAME_CHIPS_PUBLISHED by date, 05:30Z..07:59Z"
nice -n 19 grep -E '^2026-11-27T0[5-7]:[0-9:.]+Z .*GAME_CHIPS_PUBLISHED' "$LOG" | grep -oE '^[^ ]+|date=[^ ]+|chips=[^ ]+|live=[^ ]+' | paste -sd' ' | sed 's/ 2026-11-27T/\n2026-11-27T/g' | head -40
