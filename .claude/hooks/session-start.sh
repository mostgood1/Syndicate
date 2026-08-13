#!/usr/bin/env bash
# SessionStart hook — no session begins blind.
# Emits current state + open lanes so the protocol is loaded, not remembered.
# Fails open: any error exits 0 silently rather than obstructing the session.
set -uo pipefail

cd "${CLAUDE_PROJECT_DIR:-$(pwd)}" 2>/dev/null || exit 0
[ -d .syndicate ] || exit 0

echo "=== SYNDICATE LEDGER (auto-loaded) ==="
echo

if [ -f .syndicate/state.md ]; then
  echo "--- VERIFIED STATE ---"
  cat .syndicate/state.md
  echo
fi

if [ -f .syndicate/lanes.md ]; then
  echo "--- OPEN LANES ---"
  awk '/^### .* — OPEN/{p=1} /^### .* — (CLOSED|BLOCKED)/{p=0} /^## CLOSED/{p=0} p' .syndicate/lanes.md
  echo
fi

if [ -f .syndicate/learnings.md ]; then
  echo "--- STANDING RULES (FORBIDDEN / EXONERATED) ---"
  grep -E '^### .*(FORBIDDEN|EXONERATED)' .syndicate/learnings.md || echo "(none)"
  echo
fi

if [ -f .syndicate/deploys.md ]; then
  PENDING=$(grep -c '<pending>' .syndicate/deploys.md 2>/dev/null || echo 0)
  if [ "$PENDING" -gt 0 ]; then
    echo "--- OPEN OBLIGATIONS ---"
    echo "$PENDING deploy(s) in deploys.md have no measurement recorded."
    echo "An unmeasured deploy is not evidence of a fix. Chase these before new work."
    echo
  fi
fi

echo "Protocol: /lane before editing, /preflight before deploying, /checkpoint before ending."
echo "======================================"
exit 0
