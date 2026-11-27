#!/bin/bash
# Self-test of kit_env_soccer_lane_age.sh against a DUMMY env file (no real values). The real file is only checked.
set -u
D=$(mktemp /tmp/ssla_dummy_env.XXXXXX)
printf 'FOO=1\nREFRESH_WORKER__BAR=2\n' > "$D"; chmod 600 "$D"
K=/mnt/c/tmp/w1208_soccer_lane_age/kit_env_soccer_lane_age.sh
fail=0
expect() { echo "$2" | grep -qE "$1" && echo "  ok: $1" || { echo "  FAIL: expected /$1/"; fail=1; }; }
echo "== apply garbage (refused)"; out=$(KIT_ENV_FILE="$D" bash "$K" apply onn); echo "$out" | head -1; expect '^usage' "$out"
echo "== apply shadow"; out=$(KIT_ENV_FILE="$D" bash "$K" apply shadow); B1=$(echo "$out" | sed -n 's/^backup=//p')
expect 'appended=shadow' "$out"; expect 'lines_soccer_lane_age_shadow=1' "$out"; expect 'env_file_mode=600' "$out"
echo "== apply on (promotes in place)"; out=$(KIT_ENV_FILE="$D" bash "$K" apply on)
expect 'rewritten_in_place=on' "$out"; expect 'lines_soccer_lane_age_on=1' "$out"; expect 'lines_any_soccer_lane_age_key=1' "$out"
echo "== apply on again (idempotent: one line)"; out=$(KIT_ENV_FILE="$D" bash "$K" apply on)
expect 'lines_any_soccer_lane_age_key=1' "$out"
echo "== other lines kept"; expect '^FOO=1$' "$(cat "$D")"; expect '^REFRESH_WORKER__BAR=2$' "$(cat "$D")"
echo "== restore to before shadow"; out=$(KIT_ENV_FILE="$D" bash "$K" restore "$B1")
expect 'lines_any_soccer_lane_age_key=0' "$out"
echo "== a ROLE__ line is refused"; printf 'REFRESH_WORKER__SYNDICATE_LIVE_GAMELINE_SOCCER_LANE_AGE=on\n' >> "$D"
out=$(KIT_ENV_FILE="$D" bash "$K" apply on); expect 'ROLE_SCOPED_LINE_PRESENT' "$out"
rm -f "$D" "$D".bak-soccerlaneage-*
echo "== real file untouched (check only)"; before=$(stat -c '%Y %s' /home/amyn/syndicate-prod/local_production.env)
out=$(bash "$K" check); echo "$out" | grep -E 'lines_|role_env'
after=$(stat -c '%Y %s' /home/amyn/syndicate-prod/local_production.env)
[ "$before" = "$after" ] && echo "real_file_unchanged=yes" || { echo "real_file_unchanged=NO"; fail=1; }
[ $fail -eq 0 ] && echo "SELFTEST PASS" || echo "SELFTEST FAIL"
exit $fail
