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
  # Status is the field between the 1st and 2nd em-dash, and it is FREE TEXT.
  # v3 required a literal " — OPEN", which rejected the live lane
  # "— DEPLOYED, MEASUREMENT OPEN —" and under-reported open lanes 2 -> 1.
  # v2's bare /OPEN/ had the opposite failure, counting "NO LANE WAS EVER
  # OPENED" as open. Match the WORD within the status field only: the
  # (^|[^A-Za-z])OPEN([^A-Za-z]|$) form is a portable word boundary, since
  # \b/\y are not consistent across awk implementations.
  LANES_RAW=$(awk '
    /^###[[:space:]]/ {
      st = $0
      if (sub(/^###[^—]*—[[:space:]]*/, "", st)) {
        sub(/—.*$/, "", st)
        open = (st ~ /(^|[^A-Za-z])OPEN([^A-Za-z]|$)/) ? 1 : 0
      } else {
        open = 0
      }
    }
    open && /^###[[:space:]]/ { print; next }
    open && /^-[[:space:]]*Goal:/ { print "   " $0 }
  ' .syndicate/lanes.md 2>/dev/null)

  # A "### " header with no em-dash has no parseable status and is NOT counted
  # as open. That is the permissive direction, so it has to be visible: this
  # exact class of silence is what hid the DEPLOYED-lane hole for 20 minutes.
  H=$(grep -c '^###[[:space:]]' .syndicate/lanes.md 2>/dev/null || echo 0)
  P=$(grep -cE '^###[[:space:]][^—]*—' .syndicate/lanes.md 2>/dev/null || echo 0)
  UNPARSED=$(( ${H:-0} - ${P:-0} ))
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
add "/lane before editing (EM-DASH headers only). /checkpoint before ending."
add "Do NOT state system facts from memory — read .syndicate/state.md first."
# DEPLOYS, 2026-08-18: the coordinator ROLE is retired. It was a session, and a
# session can be archived -- which happened, with two requests queued into it and
# none ever granted, leaving a guard whose allow-branch was unreachable. Deploys
# are now self-serve behind two locks that cannot be archived. Printed
# unconditionally: there is no register left to gate on.
add "DEPLOYS: yours, behind two locks. deploy_claim.py acquire + deploy_preflight.py (CLEAR, <15min), then deploy."
add ""

if [ -f .syndicate/lanes.md ]; then
  add "--- OPEN LANES ---"
  add "${LANES:-(none)}"
  [ "${UNPARSED:-0}" -gt 0 ] && add "(${UNPARSED} lane header(s) have no parseable status and are NOT guarded)"
  add ""
fi

if [ -f .syndicate/learnings.md ]; then
  add "--- STANDING RULES (headings only; read learnings.md for evidence) ---"
  add "${RULES:-(none)}"
  add ""
fi

# --- Open obligations: a count, not the rows ---
#
# 2026-08-17: the raw marker count COULD ONLY EVER GO UP. deploys.md is
# append-only by its own convention ("Appended, not edited into the row above"),
# so a `Measured:` pending marker is never cleared -- the MEASUREMENT row that
# closes it is appended BELOW it. Measured that day: the hook reported 14 while
# 12 were already discharged, including seven closed by rows carrying the words
# "closes the ... row" a few hundred lines further down. A number that cannot
# fall is not an obligation count, it is a high-water mark, and it was being
# read at every session start as if a fix were owed.
#
# Each discharged marker is now declared by exactly one `- RECONCILED:` line
# (see "OBLIGATION RECONCILIATION" in deploys.md), so subtract those. The
# reconciliation section deliberately never writes the literal marker string --
# describing the markers used to inflate the count of them.
if [ -f .syndicate/deploys.md ]; then
  PENDING=$(grep -c '<pending>' .syndicate/deploys.md 2>/dev/null); PENDING=${PENDING:-0}
  RECONCILED=$(grep -c '^- RECONCILED:' .syndicate/deploys.md 2>/dev/null); RECONCILED=${RECONCILED:-0}
  OWED=$(( PENDING - RECONCILED ))
  [ "$OWED" -lt 0 ] && OWED=0
  if [ "$OWED" -gt 0 ]; then
    add "OPEN OBLIGATIONS: $OWED deploy(s) with no measurement ($RECONCILED of $PENDING markers reconciled). Not evidence of a fix."
  elif [ "$PENDING" -gt 0 ]; then
    add "OPEN OBLIGATIONS: none owed ($RECONCILED of $PENDING markers reconciled). A discharged obligation is not a healthy service."
  fi
fi

# --- Ledger health ---
# A warning that always fires is ignored, so these thresholds are set where the
# file actually stops being readable in one pass, not at "bigger than tiny".
# 2026-08-15: state.md was 120KB/51 sections stacking contradictions (#387 in
# six of them) and lanes.md was 79% closed lanes. Both are read at every session
# start, so their size is a tax on every session, not just on the writer.
BLOAT=""
for f in state.md:60000 lanes.md:120000 learnings.md:120000; do
  n=${f%%:*}; cap=${f##*:}
  if [ -f ".syndicate/$n" ]; then
    SZ=$(wc -c < ".syndicate/$n" 2>/dev/null | tr -d ' ')
    [ "${SZ:-0}" -gt "$cap" ] && BLOAT="${BLOAT}${n} $((SZ/1024))KB>$((cap/1024))KB, "
  fi
done
[ -n "$BLOAT" ] && add "LEDGER OVER BUDGET: ${BLOAT%, } — these are read every session."

# The actionable half: closed lanes retained in lanes.md. Archiving them is
# mechanical and lossless (.syndicate/lanes_closed.md), unlike trimming prose.
if [ -f .syndicate/lanes.md ]; then
  # `grep -c` PRINTS 0 and EXITS 1 when nothing matches, so `|| echo 0` emitted
  # a second 0, so the next test saw two zeroes on two lines -- an integer
  # error on every clean session.
  # session. `|| true` swallows the exit status and keeps grep's own count.
  CLOSED=$(grep -c '^### .*—[^—]*\(CLOSED\|ORPHANED\|VOID\)' .syndicate/lanes.md 2>/dev/null || true)
  CLOSED=${CLOSED:-0}
  [ "${CLOSED:-0}" -gt 12 ] && add "LANE ARCHIVE OWED: $CLOSED closed/orphaned lanes still in lanes.md. Move to lanes_closed.md, leave a one-line pointer each (keep the file/line maps and any ORPHANED 'to resume' notes reachable)."
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
