#!/bin/bash
# Read-only, nice 19: the soccer live writer's lines (autorun launches/finishes, lens tick results) 19:55Z-22:05Z 11-27.
cd ~/syndicate-prod/logs || exit 0
tail -n 600000 live-odds-worker.log | grep -a -E 'SOCCER_LIVE_AUTORUN|soccer_live_state\]|TICK_COMPLETE|soccer.*(Traceback|ERROR|timeout|killed|refus)' \
  | awk '$1 >= "2026-11-27T19:55" && $1 <= "2026-11-27T22:05"' \
  | sed -E 's/results=\{[^}]*.soccer.: (True|False)[^}]*\}/soccer=\1/' | cut -c1-240 > /tmp/sw1127.txt
wc -l < /tmp/sw1127.txt
grep -c SOCCER_LIVE_AUTORUN_LAUNCHED /tmp/sw1127.txt
echo '@@ distinct event kinds @@'
grep -a -o -E '(SOCCER_LIVE_AUTORUN_[A-Z_]+|PLAYER_EXIT_TICK|TICK_COMPLETE soccer=(True|False))' /tmp/sw1127.txt | sort | uniq -c
echo '@@ autorun lines (not LAUNCHED) @@'
grep -a 'SOCCER_LIVE_AUTORUN' /tmp/sw1127.txt | grep -v LAUNCHED | head -30
echo '@@ LAUNCHED per 10 min @@'
grep -a LAUNCHED /tmp/sw1127.txt | cut -c1-15 | uniq -c
echo '@@ PLAYER_EXIT_TICK per 10 min @@'
grep -a PLAYER_EXIT_TICK /tmp/sw1127.txt | cut -c1-15 | uniq -c
echo '@@ launched in_play samples @@'
grep -a LAUNCHED /tmp/sw1127.txt | awk 'NR%6==1' | cut -c1-230
