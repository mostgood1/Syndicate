#!/usr/bin/env bash
# SessionStart hook — v3.
#
# Design (unchanged from v2): this hook does NOT deliver the ledger. Hook stdout
# is capped (~2KB) by the harness, and v1 spent the entire budget cat-ing
# state.md, so the operational sections never reached context at all.
#
# The job is to deliver the OBLIGATION to read the ledger, plus the few facts
# too costly to miss. Reading files is cheap for the session; forgetting that
# it must is what the hook prevents. Everything here is bounded.
#
# v3 fixes three defects measured in v2 (2026-08-13):
#   1. The lane test was the substring /OPEN/, so
#      "### render-yaml-web-block-hygiene — DONE — **NO LANE WAS EVER OPENED**"
#      was reported as an open lane. It now requires " — OPEN" not followed by
#      another letter, which excludes OPENED/REOPENED.
#   2. Every cap truncated in silence. Silent truncation is the exact failure
#      this file exists to prevent, so each cap now announces itself, and the
#      overflow marker prints FIRST — the tail is what gets cut, so a warning
#      at the bottom is a warning that cannot be read.
#   3. BUDGET was 1500 against a body that had legitimately grown to ~1590B.
#      Raised to 1800, which still leaves ~200B of margin under the harness
#      cap. Raising it is only defensible because (2) now makes the real
#      ceiling visible instead of quietly eating content.
#
# Fails open: any error exits 0 silently.
set -uo pipefail

BUDGET=1800          # hard cap on body bytes; harness cap is ~2000
LANE_CAP=600
RULE_CAP=450

cd "${CLAUDE_PROJECT_DIR:-$(pwd)}" 2>/dev/null || exit 0
[ -d .syndicate ] || exit 0

NOTES=""

# PRINTS a note if the text would be cut, otherwise nothing. It must print
# rather than assign to NOTES: every caller runs it inside $(...), which is a
# subshell, so an assignment made in here would be discarded and the guard
# would be permanently silent. (It was, on the first attempt at this fix.)
#
# Byte counts come from wc -c, not ${#var}: the ledger is full of em-dashes and
# ${#} counts characters, which would under-count by 2 bytes each and cap late.
over_note() {  # $1=label  $2=cap  $3=text
  local n
  n=$(printf '%s' "$3" | wc -c | tr -d ' ')
  [ "${n:-0}" -gt "$2" ] && printf '[%s truncated: %sB > %sB cap] ' "$1" "$n" "$2"
  return 0
}

# --- Open lanes: slug and goal only, hard-capped ---
LANES=""
if [ -f .syndicate/lanes.md ]; then
  LANES_RAW=$(awk '
    /^###[[:space:]]/ { open = ($0 ~ / — OPEN([^A-Za-z]|$)/) ? 1 : 0 }
    open && /^###[[:space:]]/ { print; next }
    open && /^-[[:space:]]*Goal:/ { print "   " $0 }
  ' .syndicate/lanes.md 2>/dev/null)
  NOTES="${NOTES}$(over_note "OPEN LANES" "$LANE_CAP" "$LANES_RAW")"
  LANES=$(printf '%s' "$LANES_RAW" | head -c "$LANE_CAP")
fi

# --- Standing rules: headings only, never bodies ---
RULES=""
if [ -f .syndicate/learnings.md ]; then
  RULES_RAW=$(grep -E '^###.*(FORBIDDEN|EXONERATED)' .syndicate/learnings.md 2>/dev/null \
    | sed 's/^### //')
  NOTES="${NOTES}$(over_note "STANDING RULES" "$RULE_CAP" "$RULES_RAW")"
  RULES=$(printf '%s' "$RULES_RAW" | head -c "$RULE_CAP")
fi

BODY=""
add() { BODY="${BODY}$1
"; }

add "=== SYNDICATE PROTOCOL (auto-loaded, bounded digest) ==="
add "/lane before editing. /preflight before deploying. /checkpoint before ending."
add "Do NOT state system facts from memory — read .syndicate/state.md first."
add ""

if [ -f .syndicate/lanes.md ]; then
  add "--- OPEN LANES ---"
  add "${LANES:-(none)}"
  add ""
fi

if [ -f .syndicate/learnings.md ]; then
  add "--- STANDING RULES (headings only; read learnings.md for evidence) ---"
  add "${RULES:-(none)}"
  add ""
fi

# --- Open obligations: a count, not the rows ---
if [ -f .syndicate/deploys.md ]; then
  PENDING=$(grep -c '<pending>' .syndicate/deploys.md 2>/dev/null || echo 0)
  [ "$PENDING" -gt 0 ] && add "OPEN OBLIGATIONS: $PENDING deploy(s) with no measurement. Not evidence of a fix."
fi

# --- Ledger health: surface bloat instead of silently truncating it ---
BLOAT=""
for f in state.md lanes.md; do
  if [ -f ".syndicate/$f" ]; then
    SZ=$(wc -c < ".syndicate/$f" 2>/dev/null | tr -d ' ')
    [ "${SZ:-0}" -gt 6000 ] && BLOAT="${BLOAT}${f} ${SZ}B, "
  fi
done
if [ -n "$BLOAT" ]; then
  add "LEDGER BLOAT: ${BLOAT%, }. Working state, not history — promote durable"
  add "rules to learnings.md and cut back before these stop being read."
fi

# --- Emit. Overflow is announced BEFORE the body, because the tail is the
#     part that gets cut and a truncation warning that gets truncated is worse
#     than none: it reads as a clean run. ---
LEN=$(printf '%s' "$BODY" | wc -c | tr -d ' ')
if [ "${LEN:-0}" -gt "$BUDGET" ]; then
  echo "DIGEST OVERFLOW: ${LEN}B body > ${BUDGET}B budget — tail cut. Trim .syndicate/ or raise BUDGET."
fi
[ -n "$NOTES" ] && echo "DIGEST NOTES: ${NOTES}"

printf '%s' "$BODY" | head -c "$BUDGET"
echo
echo "=== end digest — full ledger in .syndicate/ ==="
exit 0
