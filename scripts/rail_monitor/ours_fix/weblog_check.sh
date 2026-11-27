#!/bin/bash
# Read-only: count error lines in the fleet web log since the reload (04:39:59Z 11-27).
LOG=$(ls -t ~/syndicate-prod/logs/web*.log 2>/dev/null | head -1)
echo "log $LOG read_at $(date -u +%H:%M:%SZ)"
since="2026-11-27 04:39:5"
awk 'substr($0, 1, 19) >= "2026-11-27T04:39:59" && substr($0, 1, 4) == "2026"' "$LOG" > /tmp/ours_fix_weblog.txt 2>/dev/null
echo "lines since reload $(wc -l < /tmp/ours_fix_weblog.txt)"
for k in UNHANDLED_500 Traceback "WORKER TIMEOUT" TemplateSyntaxError "Internal Server Error"; do
  echo "$k $(grep -c "$k" /tmp/ours_fix_weblog.txt)"
done
echo "first line: $(head -1 /tmp/ours_fix_weblog.txt | cut -c1-160)"
echo "last line:  $(tail -1 /tmp/ours_fix_weblog.txt | cut -c1-160)"
