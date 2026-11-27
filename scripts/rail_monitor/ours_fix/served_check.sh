#!/bin/bash
# Read-only, nice 19: the fleet's loaded commit, the web workers, and whether the SERVED /intelligence page carries the
# rail card OURS fix (fe46fb249). Usage: bash served_check.sh <label>
L="${1:-check}"
OUT=/mnt/c/tmp/railmon/ours_fix
echo "read_at $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "fleet_commit $(git -C ~/Syndicate rev-parse --short HEAD)"
echo "web_workers $(pgrep -f 'gunicorn' -a | grep -v pgrep | awk '{print $1}' | tr '\n' ' ')"
code=$(nice -n 19 curl -s -o "$OUT/served_$L.html" -w '%{http_code} %{size_download}' http://127.0.0.1:10000/intelligence)
echo "intelligence_http $code"
echo "served_page_has_flaggedOwn $(grep -c 'const flaggedOwn = segment === \"full\"' "$OUT/served_$L.html")"
echo "served_page_has_tooltip $(grep -c 'from another re-sim tick' "$OUT/served_$L.html")"
