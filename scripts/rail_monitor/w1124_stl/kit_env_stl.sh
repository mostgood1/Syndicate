#!/bin/bash
# Load kit for the NHL St. Louis live-join fix (lane nhl-live-join-stl-alias, rail monitor session d58574cb): ONE
# GLOBAL env line, SYNDICATE_LIVE_GAMELINE_NHL_TEAM_ALIASES=on (code on main, absent = OFF). Global, because the NHL
# join runs wherever board_enrichment.attach_live_gamelines_for_sport runs (refresh-worker's book-grid tick and its
# Layer 2 board child); every other sport ignores this key (NCAAF keeps its own absent = ON switch).
# A BETTING CHANGE: load only in a betting-change window, or with the user's --outside-window reason. NOT applied by
# the building session -- the user decides (queue for the 11-24 window).
# usage: kit_env_stl.sh check | apply | restore <backup_path>
# Prints NO env values except this key (a non-secret switch). apply is idempotent and backs the file up first (mode kept).
set -u
F=${KIT_ENV_FILE:-/home/amyn/syndicate-prod/local_production.env}  # override ONLY for the dummy-file self-test
K=SYNDICATE_LIVE_GAMELINE_NHL_TEAM_ALIASES
ANY="^([A-Z_]+__)?$K="
case "${1:-check}" in
  check) ;;
  apply)
    BK="$F.bak-nhlstl-$(date -u +%Y%m%dT%H%M%S.%NZ)-$$"
    [ -e "$BK" ] && { echo "BACKUP_EXISTS $BK"; exit 3; }
    cp -p "$F" "$BK" && echo "backup=$BK" || { echo "BACKUP_FAILED"; exit 3; }
    if grep -qE "$ANY" "$F"; then echo "already_present (not appending; check the lines below)"; else
      printf '\n# lane nhl-live-join-stl-alias: NHL live rows join through the team-alias fallback (St Louis / St. Louis Blues)\n%s=on\n' "$K" >> "$F" && echo "appended"
    fi ;;
  restore)
    B="${2:?usage: kit_env_stl.sh restore <backup_path>}"
    [ -f "$B" ] || { echo "NO_BACKUP $B"; exit 3; }
    cp -p "$B" "$F" && echo "restored_from=$B" ;;
  *) echo "usage: kit_env_stl.sh check|apply|restore <backup>"; exit 2 ;;
esac
stat -c 'env_file_mode=%a' "$F"
echo "lines_nhlstl_on=$(grep -c "^$K=on$" "$F")"
echo "lines_any_nhlstl_key=$(grep -cE "$ANY" "$F")"
cd /home/amyn/Syndicate || exit 4
for r in web refresh-worker live-odds-worker; do
  v=$(python3 scripts/local_production.py env --role "$r" 2>/dev/null | grep -E "^$K=" || true)
  echo "role_env[$r]: ${v:-ABSENT}"
done
