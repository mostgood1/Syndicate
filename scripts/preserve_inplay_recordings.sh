#!/bin/bash
# Copy completed in-play recorder nights from the Windows host's C:\tmp into the fleet's research store, gzipped.
#
# Why (profit learning program, item I1, `.syndicate/plan_2026-11-18_profit_learning_program.md`): the recorder
# (Windows task "Syndicate inplay nightly", scripts/inplay_nightly.py) writes to C:\tmp\inplay_<date>\ only. That
# is the only deep Kalshi/Polymarket in-play quote history Syndicate has, and C:\tmp is neither backed up nor
# safe from cleanups. The fleet data root is backed up. Backfill of 10-20..11-17 done 2026-11-18 (319 files,
# 14.1 GB -> 1.4 GB); this keeps new nights flowing. User 2026-11-18: "Yes, set it up".
#
# Installed copy: C:\SyndicateProd\inplay_preserve\preserve_inplay_recordings.sh, run daily by the Windows task
# "SyndicateInplayPreserve" (7:15 AM local, Interactive logon, wsl.exe -d Ubuntu-24.04), appending to
# ~/syndicate-prod/logs/inplay_preserve.log. Re-install after editing this file (strip CRs: core.autocrlf is true
# on this host, so a Windows checkout of this file can have CRLF endings, which bash will not run):
#     sed 's/\r$//' scripts/preserve_inplay_recordings.sh > /c/SyndicateProd/inplay_preserve/preserve_inplay_recordings.sh
#
# Rules:
#   - COPY only. Never deletes or changes a source file, and never replaces a good .gz with a failed one.
#   - Skips tonight (the night dated today, Central time) and any night with a file modified in the last
#     INPLAY_QUIET_MIN minutes (the recorder may still be writing it); the next run picks it up.
#   - A .gz newer than its source is done. A source changed after its copy is copied again.
#   - Reads through dd in 4 MB blocks with up to 3 tries: on 2026-11-18, 9 of 319 plain gzip reads of
#     /mnt/c failed with ENOMEM while WSL had ~300 MB free, and all 9 succeeded on retry.
#   - Every copy is checked with gzip -t before it is renamed into place. Idle priority throughout.
#   - Exit 0 when every completed night is fully copied; 1 when any file is still missing.
#
# Env overrides (for tests): INPLAY_SRC_ROOT (default /mnt/c/tmp), INPLAY_DEST
# (default ~/syndicate-prod/data/research/inplay_recorder), INPLAY_QUIET_MIN (default 90),
# INPLAY_RETRY_SLEEP (default 30), INPLAY_TODAY (default today in America/Chicago).
set -u
set -o pipefail

src_root="${INPLAY_SRC_ROOT:-/mnt/c/tmp}"
dest="${INPLAY_DEST:-$HOME/syndicate-prod/data/research/inplay_recorder}"
quiet_min="${INPLAY_QUIET_MIN:-90}"
retry_sleep="${INPLAY_RETRY_SLEEP:-30}"
today_ct="${INPLAY_TODAY:-$(TZ=America/Chicago date +%F)}"

log() { echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) [inplay_preserve] $*"; }

mkdir -p "$dest" || { log "FATAL cannot create $dest"; exit 1; }
log "start src=$src_root dest=$dest today_ct=$today_ct quiet_min=$quiet_min"

nights=0 copied=0 done_before=0 failed=0 deferred=0
for src in "$src_root"/inplay_20[0-9][0-9]-[0-1][0-9]-[0-3][0-9]; do
  [ -d "$src" ] || continue
  night="${src##*/inplay_}"
  [ "$night" \< "$today_ct" ] || continue
  if [ -n "$(find "$src" -maxdepth 1 -type f -mmin "-$quiet_min" -print -quit)" ]; then
    log "defer $night: a file changed in the last $quiet_min min"
    deferred=$((deferred + 1))
    continue
  fi
  nights=$((nights + 1))
  out="$dest/$night"
  mkdir -p "$out"
  for f in "$src"/*; do
    [ -f "$f" ] || continue
    g="$out/${f##*/}.gz"
    if [ -s "$g" ] && [ "$g" -nt "$f" ]; then
      done_before=$((done_before + 1))
      continue
    fi
    ok=0
    for try in 1 2 3; do
      if nice -n 19 ionice -c3 dd if="$f" bs=4M status=none | nice -n 19 gzip -c > "$g.tmp" \
          && gzip -t "$g.tmp" && mv -f "$g.tmp" "$g"; then
        ok=1
        log "copied $night/${f##*/} ($(stat -c %s "$f") -> $(stat -c %s "$g") bytes, try $try)"
        break
      fi
      rm -f "$g.tmp"
      log "retry $night/${f##*/}: try $try failed"
      [ "$try" -lt 3 ] && sleep "$retry_sleep"
    done
    if [ "$ok" = 1 ]; then copied=$((copied + 1)); else failed=$((failed + 1)); log "FAILED $night/${f##*/}"; fi
  done
done

log "done nights=$nights copied=$copied already=$done_before deferred_nights=$deferred failed=$failed total=$(du -sh "$dest" | cut -f1)"
[ "$failed" = 0 ]
