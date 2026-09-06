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
#
# MEASURED 2026-08-20: the pattern here was `^###`, but learnings.md entries are
# written at `##`. That matched 9 headings against 35 FORBIDDEN/EXONERATED rules
# at `##` -- so **35 of 44 standing rules reached no session at all**, including
# ones as load-bearing as "never point a worker publish URL at a public
# hostname". A rule nobody is shown is not a rule.
#
# Relaxing the pattern ALONE would have made it worse. 44 headings is ~4,800B
# against a 450B cap, and `head -c` takes them in FILE order, which is
# append-order, which is OLDEST-first -- so the digest would have shown ~7 of
# the most stale rules and silently dropped every lesson learned since. The
# selection matters as much as the match, so this takes the TAIL: the most
# recently written rules, which are the ones a session is most likely to be
# about to repeat.
#
# The count is printed because "showing 6" and "showing 6 of 44" are different
# claims, and only the second tells a session that reading learnings.md is
# still worth doing.
RULES=""
if [ -f .syndicate/learnings.md ]; then
  # Compacted, because 43 rules do not fit in 450B at full heading length and
  # `head -c` alone cuts the last one mid-word. Drop the `2026-` century prefix
  # and clip each to one line: measured, full headings fit 4 rules and clipped
  # ones fit ~7, all of them readable to the end.
  RULES_RAW=$(grep -E '^#{2,3}[[:space:]].*(FORBIDDEN|EXONERATED)' .syndicate/learnings.md 2>/dev/null \
    | sed -E 's/^#{2,3} //; s/^2026-//; s/[[:space:]]+—[[:space:]]+/ /' \
    | cut -c1-64)
  RULES_N=$(printf '%s\n' "$RULES_RAW" | grep -c . || true)
  # `tail -n 14 | head -c CAP` looked right and was WRONG: it keeps the FIRST 7
  # of the last 14, so it showed rules 30-36 of 43 -- neither the newest nor the
  # oldest, and the tail cut mid-word. Take exactly as many whole lines as the
  # cap holds: entries are clipped to 64 chars, so 6 lines is <=390B, under the
  # 450B cap with every line complete.
  RULES=$(printf '%s' "$RULES_RAW" | tail -n 6 | head -c "$RULE_CAP")
  RULES_SHOWN=$(printf '%s\n' "$RULES" | grep -c . || true)
  [ "${RULES_N:-0}" -gt "${RULES_SHOWN:-0}" ] && \
    NOTES="${NOTES}[STANDING RULES: showing ${RULES_SHOWN} most recent of ${RULES_N} — full list in learnings.md] "
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
# Which tree am I in? A session cannot answer this by looking at the files --
# a worktree is a normal-looking checkout -- and the answer decides whether
# `git add` is safe. `git rev-parse --git-dir` returns a path under
# `.git/worktrees/<name>` in a linked worktree and plain `.git` in the primary.
GITDIR=$(git rev-parse --git-dir 2>/dev/null || echo "")
case "$GITDIR" in
  *worktrees*) add "TREE: your own worktree — its index is yours; \`git add\` touches no other session." ;;
  *)           add "TREE: the PRIMARY, SHARED tree — \`git add\` here writes the index EVERY session shares. Move: scripts/session_worktree.py adopt --lane <slug>, then open." ;;
esac
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
#
# state.md 60000 -> 180000, 2026-08-18 [USER DECISION]. The old figure was set
# when state.md carried far fewer subjects, and by its own principle above it had
# stopped being a threshold: it fired continuously through two full collapses
# (2026-08-15 and 2026-08-18, both archived verbatim) and was back to 2.77x the
# same evening. A warning that cannot be satisfied is one people learn to scroll
# past, which costs more than the warning was ever worth.
#
# 180000 IS SUBJECT-COUNT-DRIVEN, NOT REVERSE-ENGINEERED FROM TODAY'S SIZE:
# 40 keyed subjects x ~4,500 B. `state_key_check.py` enforces one-subject-one-
# section, so the subject count is what actually drives this file's size, and a
# cap that tracks it says something. A cap set to whatever the file measures
# today would be a rubber stamp -- it would pass on the day it is written and
# never fail again.
#
# THE RIGHT RESPONSE TO EXCEEDING THIS IS NOT ANOTHER RAISE. It is collapse by
# the SUBJECT'S OWNER: measured 2026-08-18, only 923 B of state.md's 163,412 was
# self-declared archival, and the rest is live current-truth at 8-19% dated
# measurement lines -- so there is nothing mechanical to reclaim, and a
# non-owner compressing it is deciding which of someone else's measured numbers
# stop mattering. lanes.md and learnings.md were both brought under cap the same
# evening by MOVING blocks, which is verifiable; state.md has no such operation.
#
# SIZE WAS ALWAYS A PROXY HERE. The failure it stood in for -- stacked
# contradictory sections -- is caught directly and better by
# `state_key_check.py` in the coherence loop below, which is why loosening this
# number does not loosen the thing that matters.
BLOAT=""
# RAISED 2026-09-01, after the reduction below made the old numbers unreachable
# rather than aspirational. learnings.md went 416,515 -> 232,351 chars in one
# evening (compaction through 09-01, pre-08-20 entries archived, and the
# evidence file deduped) and STILL sat at 1.94x of 120,000. A cap that cannot
# be met by any non-destructive operation is not a budget, it is a permanent red
# light -- and a warning that is always on is one nobody reads.
#
# The new numbers are current size + ~15% headroom, so this stays a GROWTH
# ALARM: it goes off when a file starts running away again, which is the only
# question it was ever able to answer. Sizes when set: state 638,208,
# lanes 201,022, learnings 240,442.
#
# state.md gets MORE headroom than the others, not less: it is the fastest
# grower (617 KB -> 638 KB in roughly two hours on 2026-08-31 with three
# sessions appending) and it is the one file here with NO trim tool at all --
# `state_key_check.py` is a checker. 10% headroom would have fired again the
# same night.
#
# lanes.md HAD no lever when this was written -- `trim_lane_blocks.py` reported
# "nothing to move -- every block is claim-bearing or reads OPEN", so its size
# was lanes not being CLOSED. THAT IS NO LONGER TRUE, and the reason is worth
# keeping: the lever was not broken, it was WAITING ON LANES TO CLOSE. By
# 2026-09-03 nineteen had, and one --apply moved 235,998 -> 150,869 B (86,823 B
# off the working file), 48 blocks -> 29, claims unchanged at 17, every moved
# block verified present in lanes_history.md and absent from lanes.md.
#
# So do not read "no lever" here as permanent. Re-run the dry run before
# concluding this file cannot be trimmed -- its trimmability is a function of
# how many lanes are closed today, not of the tool.
#
# learnings.md RAISED AGAIN 2026-09-02, 280,000 -> 400,000, and the reason is
# that "current size + 15% headroom" IS THE WRONG SIZING RULE FOR THIS FILE.
# That headroom was set on 2026-09-01 at 240,442 bytes and was CONSUMED IN
# UNDER A DAY -- 278,051 by 21:09 the same evening, +37,609. Measured growth
# over ten hours of that day, from the file's own commit sizes: 243,973 ->
# 274,066, about 3 KB/hour with several sessions appending.
#
# The structural reason, and it is not "the file grows fast": THE LEVER LAGS BY
# A DAY BY DESIGN. `compact_learnings.py --keep-from <date>` compacts entries
# strictly BEFORE that date, so today's rules are never compactable and
# yesterday's only become so tomorrow. Measured today: cutoffs through
# 2026-09-01 reclaimed 0 bytes (everything older was already compacted) while
# `--keep-from 2026-09-02` reclaimed 27,669. So the file always carries an
# UNCOMPACTABLE WORKING SET of one to two days on top of its compacted floor,
# and a cap pinned to a percentage of the compacted floor fires on normal work
# every single day.
#
# 400,000 is that floor (~249 KB after compacting through 09-01) plus roughly
# three days of net growth -- enough that the alarm survives a weekend nobody
# compacts, and still goes off if the file genuinely runs away. This is NOT the
# lanes.md case: learnings.md has a WORKING tool with real bytes to reclaim, so
# raising the cap here buys time for a lever that exists rather than silencing
# one that does not.
# state.md RAISED 2026-09-03, 750,000 -> 920,000, AND THIS IS AN EXPLICIT
# OVERRIDE OF THE PARAGRAPH ABOVE THAT SAYS "THE RIGHT RESPONSE TO EXCEEDING
# THIS IS NOT ANOTHER RAISE." User ordered the raise after the archival pass
# below came up short. Logged here rather than applied silently, because the
# standing position it overrides is still the correct default.
#
# What was tried first, and what it actually yielded. A hand archival pass on
# 2026-09-03 moved two dead regions out of the MLB gameline cell -- a completed
# landing narrative and the retracted n=98 / +0.06104 reading -- into
# state_archive_2026-09-03.md. That cell was 11,108 chars, NINE TIMES the next
# largest line in the file, so it was the best single target available. It
# reclaimed 3,086 B. At the measured growth rate that is ONE HOUR AND TWENTY
# MINUTES of headroom. Hand archival is real but it does not scale to the rate.
#
# This CONFIRMS the 2026-08-18 measurement above ("only 923 B of 163,412 was
# self-declared archival, nothing mechanical to reclaim") at 5x the file size,
# and an earlier draft of this comment guessed the opposite. scripts/
# compact_state.py was written, and every superseded marker in the file was
# then audited BY HAND: 9 candidates, of which ONE was archivable (1,460 B,
# moved) and EIGHT were not. Six had no dead body -- the superseded claim was
# deleted when its correction was written and survives only as a quotation
# inside that correction, so the flagged paragraph IS the record. Two keep
# their old block deliberately and say so ("kept because the diagnosis chain in
# them is still the right one"), and both carry post-correction content.
#
# So: 0.2% of state.md was reclaimable superseded prose, and it is now gone.
# THE FILE IS NOT BLOATED, IT IS BIG -- it is live current truth, and it grows
# because the system does. Raise the cap or split the file; do not send anyone
# looking for fat that has already been measured and is not there.
#
# Where 920,000 comes from -- MEASURED, not chosen. Over 133 first-parent
# commits touching state.md since 08-28: +292,472 B in 143.5 h = 2,038 B/h.
# Last 24 h alone: 683,018 -> 736,532, i.e. 2,253 B/h across 40 commits.
# Busiest window: +62,250 B in 4.7 h = 13,244 B/h. Those are git blob (LF)
# bytes; the check below reads the CRLF working file, ~1.55% larger, so call
# it 2,290 B/h sustained. 920,000 - 747,959 = 172,041 B = ~3.1 days sustained,
# or one full day of burst. Three days is the same survives-a-weekend rule
# used for learnings.md above.
#
# WHAT THIS DOES NOT FIX, stated plainly so the next raise is not a surprise:
# state.md has NO trim tool and only grows, so any cap is consumed on a
# schedule. 920,000 buys ~3 days. It is a RUNAWAY DETECTOR and nothing more --
# it can tell you the file doubled overnight, it can never tell you the file
# is healthy. The thing that catches the failure size was always a proxy for
# is state_key_check.py in the coherence loop below, which this raise does not
# touch. The real fix is a compact_state.py that does for cells what
# compact_learnings.py does for entries: rule stays, superseded reading moves.
# SPLIT 2026-09-03. state.md is now an INDEX plus cross-cutting subjects
# (61,985 B); the bodies live in nine `state_<domain>.md` parts. So the single
# 920,000 cap above no longer describes anything -- state.md would sit at 7% of
# it forever while a part grew without limit, which is a cap that cannot fire.
#
# Three alarms now, each answering a different question:
#   state.md:120000   the index must stay CHEAP -- it is what every session
#                     reads first, and it grows one row per new subject.
#   part:250000       one domain running away. Largest today is venues at
#                     154,682, so this is ~1.6x the current worst.
#   total:1100000     aggregate growth, the question the old 920,000 asked.
#                     Today's total is 774,933 across ten files -- the split
#                     ADDED ~28 KB in part headers and the index, which is the
#                     price of the structure and is counted here honestly.
STATE_TOTAL=0
for sf in .syndicate/state.md .syndicate/state_*.md; do
  case "$sf" in *state_archive*) continue;; esac
  [ -f "$sf" ] || continue
  SZ=$(wc -c < "$sf" 2>/dev/null | tr -d ' ')
  STATE_TOTAL=$((STATE_TOTAL + ${SZ:-0}))
  case "$sf" in
    .syndicate/state.md) [ "${SZ:-0}" -gt 120000 ] && BLOAT="${BLOAT}state.md index $((SZ/1024))KB>117KB, ";;
    *) [ "${SZ:-0}" -gt 250000 ] && BLOAT="${BLOAT}$(basename "$sf") $((SZ/1024))KB>244KB, ";;
  esac
done
[ "$STATE_TOTAL" -gt 1100000 ] && BLOAT="${BLOAT}state total $((STATE_TOTAL/1024))KB>1074KB, "

# learnings.md 400000 -> 460000, 2026-09-05 [USER DECISION], AFTER compacting.
# The raise is second, not first, and that ORDER is the whole justification:
# `compact_learnings.py --keep-from 2026-09-05` was run first and reclaimed
# 64,557 B (462,498 -> 397,941), moving 40 entries' bodies to the evidence file
# while their headings and rule lines stayed here. Conservation verified
# independently of the tool: 896 headings before across learnings+evidence, 897
# after (the +1 is a peer appending mid-run), ZERO lost, and learnings.md itself
# still carries all 483 of its own headings.
#
# 460,000 = post-compaction 397,941 + 15.6%, which is the `current size + ~15%
# headroom` rule the 2026-09-01 block above states. Deliberately NOT based on
# the size right now (405,388): that number already includes ~7 KB peers
# appended DURING the compaction, and sizing a cap to a moment of load is the
# same error a peer made tonight reading an auto-managed pagefile mid-run and
# calling it a precondition.
#
# WHY A RAISE WAS STILL RIGHT WHEN COMPACTION ALONE CLEARED THE CAP. It cleared
# it by 2,059 B -- 0.5%. Measured this session, the file grew ~6 KB/hour across
# an active multi-session evening and ~7 KB during the compaction window alone,
# so a 0.5% margin is a red light again within the hour. That is the exact
# failure the 2026-09-01 block names: `a cap that cannot be met by any
# non-destructive operation is not a budget, it is a permanent red light -- and
# a warning that is always on is one nobody reads.` 460,000 leaves ~55 KB, i.e.
# 8-9 hours of fleet work, so it still FIRES on a runaway.
#
# WHAT THIS ALARM IS ACTUALLY MEASURING, because it is not sloppy writing:
# ~40 new FORBIDDEN-class rules were appended in 36 hours by parallel sessions.
# The number tracks the fleet's mistake-to-rule conversion rate. Read it that
# way before compacting again -- and note compaction is now nearly spent, since
# 369 of 432 dated entries are ALREADY stubs and re-moving them reclaims zero.
# The next lever is not a raise and not a compaction; it is fewer, better rules.
for f in lanes.md:240000 learnings.md:460000; do
  n=${f%%:*}; cap=${f##*:}
  if [ -f ".syndicate/$n" ]; then
    SZ=$(wc -c < ".syndicate/$n" 2>/dev/null | tr -d ' ')
    [ "${SZ:-0}" -gt "$cap" ] && BLOAT="${BLOAT}${n} $((SZ/1024))KB>$((cap/1024))KB, "
  fi
done
[ -n "$BLOAT" ] && add "LEDGER OVER BUDGET: ${BLOAT%, } — these are read every session."

# --- Ledger COHERENCE (size is not health) ---
# Over-budget measures how BIG the ledgers are. It says nothing about whether
# they still mean anything, and 2026-08-18 showed the difference: todo.md was
# within nobody's definition of broken while #447 sat in NEITHER it nor the
# archive, and lanes.md had 7 slugs with two OPEN blocks each -- two sessions
# could each read themselves as the holder of the same files.
#
# Each checker is a one-liner here BECAUSE the detail belongs in the tool. The
# digest says only "something is wrong and here is what to run": a session-start
# banner that prints twelve findings is one people learn to scroll past.
#
# --no-history on the todo check: its default pass is `git log -p` over 738
# commits (~10s) to recover ids that were only ever legacy table rows. That is
# right for an audit and wrong for something on the session-start path.
#
# FAILS OPEN, like every other guard here: no python, a missing script, or a
# crashing checker leaves the line off entirely rather than blocking a session.
INCOHERENT=""
if command -v python >/dev/null 2>&1; then
  # check_lane_invariants.py was MISSING from this list until 2026-08-18, and
  # its absence is why `#466` ran unnoticed. lane_identity_check answers "does
  # one slug have two OPEN blocks"; it says nothing about WHERE a block sits or
  # whether two lanes claim one file. Both of those failed for days with a green
  # session-start banner over them: 7 OPEN lanes filed inside `## Archived
  # lanes` (whose claims a future archive pass drops silently, since lane-guard
  # reads lanes.md and nothing else) and 1 contested file.
  #
  # The lesson is the cheap half of the pair. `/lane` was also fixed to insert
  # under `## OPEN` instead of appending at EOF -- but that is PROSE in a slash
  # command, and prose is what failed here in the first place. A checker in this
  # loop is what makes the regression surface next session instead of next week.
  # check_lane_claims.py added 2026-09-03. The other three all ask whether the
  # ledger's STRUCTURE is intact -- one block per slug, blocks under the right
  # heading, one holder per claim. None of them asks whether a claim NAMES A
  # FILE, and a claim that names nothing satisfies every one of them while
  # guarding nothing. `learnings.md` 2026-08-31 prescribed this exact check
  # ("reject claims whose path is absent from git ls-files") and it was never
  # built; 8 of 44 live claims were in that state when it finally was.
  for c in "lane_identity_check.py:lanes.md" \
           "check_lane_invariants.py:lanes.md" \
           "check_lane_claims.py:lanes.md (claims name no file)" \
           "state_key_check.py:state.md" \
           "todo_id_reconcile.py --no-history:todo.md"; do
    script=${c%%:*}; label=${c##*:}
    [ -f "scripts/${script%% *}" ] || continue
    if ! python scripts/$script >/dev/null 2>&1; then
      INCOHERENT="${INCOHERENT}${label} (scripts/${script%% *}), "
    fi
  done
fi
# NOT via `add`. The body is hard-capped (`head -c "$BUDGET"`) and this section
# sits at the tail, so the first version of this line was emitted as
# "LEDGER INCOHERENT: state.md (scripts/state_key_" -- cut mid-word. This file
# already states the principle for exactly that failure: "a truncation warning
# that gets truncated is worse than none: it reads as a clean run." A coherence
# warning has the same property, so it is emitted OUTSIDE the budget, next to
# DIGEST OVERFLOW.

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
[ -n "$INCOHERENT" ] && echo "LEDGER INCOHERENT: ${INCOHERENT%, } — the file's own rules are being broken; run it before trusting what the file says."

printf '%s' "$BODY" | head -c "$BUDGET"
echo
echo "=== end digest — full ledger in .syndicate/ ==="
exit 0
