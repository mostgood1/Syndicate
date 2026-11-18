#!/bin/bash
# Copy every Kalshi maker-pilot log line ([kalshi_maker_pilot] MAKER_PILOT ...) from the live-odds-worker logs into
# the fleet research store, deduplicated, before log rotation deletes them.
#
# Why (profit learning program, study S3, `.syndicate/findings_2026-11-18_s3_maker_entry.md`): the maker pilot's
# pre-registered re-judge (`findings_2026-10-31_maker_pilot_review.md`) is judged on edge at FILL. The ledger row has
# no fill time (`venue_filled_at` is absent), so fill times exist only in `MAKER_PILOT FILL` log lines, and the
# live-odds-worker log rotates in about 3.5 days (5 x 210 MB). The fill times for 11-02..11-09 were lost that way.
# User 2026-11-18: "Yes, set it up". The durable fix is `venue_filled_at` on the row; this bridges until then.
#
# Installed copy: C:\SyndicateProd\maker_pilot_preserve\preserve_maker_pilot_lines.sh, run daily by the Windows task
# "SyndicateMakerPilotLines" (7:30 AM local, Interactive logon, wsl.exe -d Ubuntu-24.04), appending to
# ~/syndicate-prod/logs/maker_pilot_preserve.log. Re-install after editing (strip CRs; core.autocrlf is true here):
#     sed 's/\r$//' scripts/preserve_maker_pilot_lines.sh > /c/SyndicateProd/maker_pilot_preserve/preserve_maker_pilot_lines.sh
#
# Rules:
#   - COPY only: reads the logs, never changes them. The output only grows (old lines are kept, new ones merged,
#     sorted, deduplicated) and is replaced atomically.
#   - Excludes ALL_PROCESS_MEMORY lines: that snapshot quotes every process's command line, including this
#     script's own grep, so it would otherwise match.
#   - Exit 0 = copied, nothing wrong.
#   - Exit 3 = a FILL line says filled_as=TAKER. That is the pilot's stop rule (state_kalshi.md
#     [kalshi-maker-pilot]): report it, and this script changes nothing.
#   - Exit 4 = a possible GAP: the oldest log line still on disk is newer than the newest line already saved, so
#     lines in between may have rotated away unsaved. (A pilot that logs nothing for longer than the log window,
#     about 3.5 days, also trips this; its FAIR_PASS lines normally run about 190 a day.)
#   - Exit 1 = the copy itself failed.
#
# Env overrides (for tests): PILOT_LOG_DIR (default ~/syndicate-prod/logs), PILOT_OUT (default
# ~/syndicate-prod/data/research/maker_pilot/maker_pilot_log_lines.txt).
set -u
set -o pipefail

log_dir="${PILOT_LOG_DIR:-$HOME/syndicate-prod/logs}"
out="${PILOT_OUT:-$HOME/syndicate-prod/data/research/maker_pilot/maker_pilot_log_lines.txt}"

say() { echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) [maker_pilot_preserve] $*"; }

mkdir -p "$(dirname "$out")" || { say "FATAL cannot create $(dirname "$out")"; exit 1; }
touch "$out" || { say "FATAL cannot write $out"; exit 1; }

shopt -s nullglob
logs=("$log_dir"/live-odds-worker.log*)
if [ "${#logs[@]}" -eq 0 ]; then say "FATAL no live-odds-worker logs in $log_dir"; exit 1; fi

before=$(wc -l < "$out")
newest_saved=$(tail -n 1 "$out" | cut -c1-24)
oldest_on_disk=""
for l in "${logs[@]}"; do
  first=$(head -c 24 "$l")
  case "$first" in 20[0-9][0-9]-*) ;; *) continue ;; esac
  if [ -z "$oldest_on_disk" ] || [[ "$first" < "$oldest_on_disk" ]]; then oldest_on_disk="$first"; fi
done

if ! { cat "$out"; for l in "${logs[@]}"; do nice -n 19 grep -a -h -F "MAKER_PILOT" "$l" || true; done; } \
    | grep -a -v "ALL_PROCESS_MEMORY" | sort -u > "$out.tmp"; then
  rm -f "$out.tmp"; say "FAILED to build the merged copy"; exit 1
fi
mv -f "$out.tmp" "$out" || { say "FAILED to replace $out"; exit 1; }

after=$(wc -l < "$out")
fills=$(grep -a "MAKER_PILOT FILL" "$out" | grep -a -o "key=[0-9a-f]*" | sort -u | wc -l)
takers=$(grep -a "MAKER_PILOT FILL" "$out" | grep -a -c "filled_as=TAKER" || true)
say "done lines $before -> $after (+$((after - before))), distinct filled orders $fills, TAKER fills $takers, oldest on disk ${oldest_on_disk:-?}, newest saved before ${newest_saved:-none}"

rc=0
if [ -n "$newest_saved" ] && [ -n "$oldest_on_disk" ] && [[ "$oldest_on_disk" > "$newest_saved" ]]; then
  say "GAP: the oldest log line on disk ($oldest_on_disk) is newer than the newest saved line ($newest_saved); lines between may be lost"
  rc=4
fi
if [ "${takers:-0}" -gt 0 ]; then
  say "STOP RULE: $takers FILL line(s) with filled_as=TAKER -- the maker pilot's stop rule; report it"
  rc=3
fi
exit "$rc"
