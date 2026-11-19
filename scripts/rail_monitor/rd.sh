#!/usr/bin/env bash
# One rail-monitor reading (11-19 onward). Git Bash, from anywhere.
#   bash /c/tmp/railmon/rd.sh <D YYYY-MM-DD> <N> <prevZ e.g. 2026-11-19T22:50:19Z> [page]
# Writes: d<DD>r<N>_probe.txt, dash/m_<DD>_<N>.json, d<DD>r<N>_mem.txt, d<DD>r<N>_extra.txt (watchers), then prints a summary.
D="$1"; N="$2"; PREV="$3"; PAGE="$4"
DD=$(echo "$D" | sed 's/^[0-9]*-\([0-9]*\)-\([0-9]*\)$/\1\2/')
WT=/c/Users/tempadmin/Coding/Syndicate/.claude/worktrees/brave-swanson-6e6c6a
R=/c/tmp/railmon
PREVNZ="${PREV%Z}"
NOPAGE="--no-page"; [ "$PAGE" = "page" ] && NOPAGE=""
date -u +%TZ
( cd "$WT" && py -3 scripts/layer2_rail_monitor_probe.py $NOPAGE --log-minutes 40 > "$R/d${DD}r${N}_probe.txt" 2> "$R/d${DD}r${N}_probe.err"; echo "probe rc=$?" ) &
( MSYS_NO_PATHCONV=1 wsl -- nice -n 19 python3 /mnt/c/tmp/railmon/dash/d4metrics.py "$PREV" "$D" > "$R/dash/m_${DD}_${N}.json" 2> "$R/dash/m_${DD}_${N}.err"; echo "metrics rc=$?" ) &
( MSYS_NO_PATHCONV=1 wsl -- nice -n 19 bash /mnt/c/tmp/railmon/d4mem.sh "$PREV" > "$R/d${DD}r${N}_mem.txt" 2>&1; echo "mem rc=$?" ) &
( MSYS_NO_PATHCONV=1 wsl -- bash -c "cd ~/syndicate-prod && nice -n 19 python3 /mnt/c/tmp/railmon/p838_watch.py $PREV; nice -n 19 python3 /mnt/c/tmp/railmon/qstage.py $PREVNZ ${D}T23:59:59; [ \"$D\" = \"\$(date -u +%Y-%m-%d)\" ] || nice -n 19 python3 /mnt/c/tmp/railmon/qstage.py $PREVNZ \$(date -u +%Y-%m-%d)T23:59:59; nice -n 19 ~/.venvs/syndicate/bin/python /mnt/c/tmp/railmon/p29_orient.py" > "$R/d${DD}r${N}_extra.txt" 2>&1
  MSYS_NO_PATHCONV=1 wsl -- nice -n 19 bash /mnt/c/tmp/railmon/p844.sh "$D" >> "$R/d${DD}r${N}_extra.txt" 2>&1 ) &
wait
echo "--- extra"; cut -c1-260 "$R/d${DD}r${N}_extra.txt"
echo "--- metrics"; cat "$R/dash/m_${DD}_${N}.json"; echo
echo "--- mem"; grep -v " 19 .*python3\|grep" "$R/d${DD}r${N}_mem.txt" | cut -c1-220 | tail -12
echo "--- probe"
py -3 - "$R/d${DD}r${N}_probe.txt" <<'PYEOF'
import json, sys
p = json.load(open(sys.argv[1], encoding="utf-8"))
print(p["read_at_ct"])
for k in ("load", "flags", "live_rows", "board"):
    print(k, json.dumps(p.get(k))[:420])
t = p["teams"]
print("teams", {k: t.get(k) for k in ("chips_today", "live_chips", "chipless", "det1", "det2", "det3", "flipped", "live_chips_without_live_card")})
print("live", t.get("live_chip_status"))
PYEOF
ls -d "$R"/readings/20* | tail -1
