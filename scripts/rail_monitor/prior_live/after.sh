#!/bin/bash
# Read-only: ff instant from the reflog, the served check, and web-log errors since the reload (16:29:54Z 11-27).
cd ~/Syndicate || exit 1
echo "reflog_ff $(git reflog -1 --date=format-local:%Y-%m-%dT%H:%M:%S --format='%gd %gs' 2>/dev/null)"
TZ=UTC git reflog -1 --date=iso-strict-local --format='reflog_time %gd'
bash /mnt/c/tmp/railmon/prior_live/served_check.sh after
LOG=$(ls -t ~/syndicate-prod/logs/web*.log 2>/dev/null | head -1)
awk 'substr($0, 1, 19) >= "2026-11-27T16:29:54" && substr($0, 1, 4) == "2026"' "$LOG" > /tmp/prior_live_weblog.txt
echo "web_log $LOG lines_since_reload $(wc -l < /tmp/prior_live_weblog.txt)"
for k in UNHANDLED_500 Traceback "WORKER TIMEOUT" TemplateSyntaxError "Internal Server Error" BOARD_GAME_CHIPS_PRIOR_DATE_READ_FAILURE; do
  echo "$k $(grep -c "$k" /tmp/prior_live_weblog.txt)"
done
