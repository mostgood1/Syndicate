#!/bin/bash
# Daily suggested-set grade: Windows task `SyndicateSuggestedSet`, 7:15 AM local (lane layer2-suggested-grader,
# user "Yes, go ahead" 2026-11-18). The task runs a COPY of this file, C:\SyndicateProd\suggested_set\run_suggested_set.sh,
# so the variables below expand inside bash and not at the wsl.exe hop (inline `$(...)` / `$rc` came through empty).
# Read-only on the fleet except its own outputs under reports/suggested_set/; nice 19. Exit = the grader's exit code
# (2 no data root, 3 no recorder files, 5 write failure; see scripts/grade_suggested_set.py).
LOG="$HOME/syndicate-prod/logs/suggested_set.log"
mkdir -p "$HOME/syndicate-prod/logs" "$HOME/.cache/syndicate_suggested_set"
cd "$HOME/Syndicate" || { echo "=== $(date -u +%Y-%m-%dT%H:%M:%SZ) no ~/Syndicate rc=9" >> "$LOG"; exit 9; }
echo "=== start $(date -u +%Y-%m-%dT%H:%M:%SZ) head=$(git rev-parse --short HEAD)" >> "$LOG"
nice -n 19 "$HOME/.venvs/syndicate/bin/python" scripts/grade_suggested_set.py \
    --data-root "$HOME/syndicate-prod/data" --write --cache-dir "$HOME/.cache/syndicate_suggested_set" >> "$LOG" 2>&1
rc=$?
echo "=== end $(date -u +%Y-%m-%dT%H:%M:%SZ) rc=$rc" >> "$LOG"
exit $rc
