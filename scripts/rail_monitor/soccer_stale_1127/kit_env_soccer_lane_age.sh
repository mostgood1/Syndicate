#!/bin/bash
# Load kit for the soccer live lane-age ceiling (lane soccer-live-lane-age-ceiling, rail monitor session d58574cb):
# ONE GLOBAL env line, SYNDICATE_LIVE_GAMELINE_SOCCER_LANE_AGE=<shadow|on> (code on main, ABSENT = OFF = today's
# behaviour). Global, because the soccer join runs wherever board_enrichment.attach_live_gamelines_for_sport runs
# (refresh-worker's book-grid tick and its Layer 2 board child); every other sport ignores this key.
#   shadow = the lens time is stamped and the 600 s ceiling judged, NOTHING refused (counts only; not a betting change)
#   on     = soccer lanes older than 600 s, or with no time, are not priced (A BETTING CHANGE)
# `on` loads only in a betting-change window (12-08 queued), or with the user's --outside-window reason. NOT applied by
# the building session -- the user decides, and the env is built only at a drained full down/up.
# usage: kit_env_soccer_lane_age.sh check | apply shadow|on | restore <backup_path>
# Prints NO env values except this key (a non-secret switch). apply backs the file up first (mode kept); an existing
# GLOBAL line is rewritten in place (shadow -> on promotes), a ROLE__-scoped line is refused (fix it by hand).
set -u
F=${KIT_ENV_FILE:-/home/amyn/syndicate-prod/local_production.env}  # override ONLY for the dummy-file self-test
K=SYNDICATE_LIVE_GAMELINE_SOCCER_LANE_AGE
ANY="^([A-Z_]+__)?$K="
GLOBAL="^$K="
case "${1:-check}" in
  check) ;;
  apply)
    V="${2:-}"
    case "$V" in shadow|on) ;; *) echo "usage: kit_env_soccer_lane_age.sh apply shadow|on"; exit 2 ;; esac
    if grep -qE "^[A-Z_]+__$K=" "$F"; then echo "ROLE_SCOPED_LINE_PRESENT (refusing; check the counts below)"; exit 3; fi
    if [ "$(grep -cE "$GLOBAL" "$F")" -gt 1 ]; then echo "DUPLICATE_GLOBAL_LINES (refusing)"; exit 3; fi
    BK="$F.bak-soccerlaneage-$(date -u +%Y%m%dT%H%M%S.%NZ)-$$"
    [ -e "$BK" ] && { echo "BACKUP_EXISTS $BK"; exit 3; }
    cp -p "$F" "$BK" && echo "backup=$BK" || { echo "BACKUP_FAILED"; exit 3; }
    if grep -qE "$GLOBAL" "$F"; then
      sed -i -E "s/^$K=.*/$K=$V/" "$F" && echo "rewritten_in_place=$V"
    else
      printf '\n# lane soccer-live-lane-age-ceiling: soccer live lanes older than 600 s are judged (shadow) / not priced (on)\n%s=%s\n' "$K" "$V" >> "$F" && echo "appended=$V"
    fi ;;
  restore)
    B="${2:?usage: kit_env_soccer_lane_age.sh restore <backup_path>}"
    [ -f "$B" ] || { echo "NO_BACKUP $B"; exit 3; }
    cp -p "$B" "$F" && echo "restored_from=$B" ;;
  *) echo "usage: kit_env_soccer_lane_age.sh check|apply shadow|on|restore <backup>"; exit 2 ;;
esac
stat -c 'env_file_mode=%a' "$F"
echo "lines_soccer_lane_age_on=$(grep -c "^$K=on$" "$F")"
echo "lines_soccer_lane_age_shadow=$(grep -c "^$K=shadow$" "$F")"
echo "lines_any_soccer_lane_age_key=$(grep -cE "$ANY" "$F")"
if [ -z "${KIT_ENV_FILE:-}" ]; then
  cd /home/amyn/Syndicate || exit 4
  for r in web refresh-worker live-odds-worker; do
    v=$(python3 scripts/local_production.py env --role "$r" 2>/dev/null | grep -E "^$K=" || true)
    echo "role_env[$r]: ${v:-ABSENT}"
  done
fi
