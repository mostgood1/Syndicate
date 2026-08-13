#!/usr/bin/env bash
# Stop hook — refuses to let real work evaporate silently.
# Warns (does not block) when tracked files changed but no checkpoint was written.
set -uo pipefail

cd "${CLAUDE_PROJECT_DIR:-$(pwd)}" 2>/dev/null || exit 0
[ -d .syndicate ] || exit 0
command -v git >/dev/null 2>&1 || exit 0

DIRTY=$(git status --porcelain 2>/dev/null | wc -l | tr -d ' ')
[ "$DIRTY" -eq 0 ] && exit 0

TODAY_LOG=".syndicate/log/$(date +%F).md"
MARKER=".syndicate/.last-checkpoint"

# Checkpointed if today's log exists and is newer than the newest tracked change.
if [ -f "$TODAY_LOG" ] && [ -f "$MARKER" ]; then
  NEWEST=$(git status --porcelain 2>/dev/null | awk '{print $NF}' \
    | while read -r f; do [ -f "$f" ] && stat -c %Y "$f" 2>/dev/null || stat -f %m "$f" 2>/dev/null; done \
    | sort -rn | head -1)
  MARK=$(stat -c %Y "$MARKER" 2>/dev/null || stat -f %m "$MARKER" 2>/dev/null || echo 0)
  if [ -n "${NEWEST:-}" ] && [ "$MARK" -ge "$NEWEST" ]; then exit 0; fi
fi

echo "UNCHECKPOINTED WORK: $DIRTY modified file(s), no /checkpoint since the last edit." >&2
echo "Run /checkpoint before ending, or this session's findings do not survive it." >&2
exit 1
