#!/bin/bash
# Self-test of kit_env_stl.sh against a DUMMY env file (no real values). The real file is only checked, never written.
set -u
D=$(mktemp /tmp/sstl_dummy_env.XXXXXX)
printf 'FOO=1\nREFRESH_WORKER__BAR=2\n' > "$D"; chmod 600 "$D"
K=/mnt/c/tmp/w1124_stl/kit_env_stl.sh
echo "== apply 1"; out=$(KIT_ENV_FILE="$D" bash "$K" apply); echo "$out" | grep -E 'backup=|appended|already|lines_'
B=$(echo "$out" | sed -n 's/^backup=//p')
echo "== apply 2 (idempotent)"; KIT_ENV_FILE="$D" bash "$K" apply | grep -E 'already|appended|lines_'
echo "== dummy file now"; cat "$D"
echo "== restore"; KIT_ENV_FILE="$D" bash "$K" restore "$B" | grep -E 'restored|lines_'
echo "== dummy file after restore"; cat "$D"
rm -f "$D" "$D".bak-nhlstl-*
echo "== real file untouched (check only)"; before=$(stat -c '%Y %s' /home/amyn/syndicate-prod/local_production.env)
bash "$K" check
after=$(stat -c '%Y %s' /home/amyn/syndicate-prod/local_production.env)
[ "$before" = "$after" ] && echo "real_file_unchanged=yes" || echo "real_file_unchanged=NO"
