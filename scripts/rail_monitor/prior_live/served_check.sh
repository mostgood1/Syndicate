#!/bin/bash
# Read-only, nice 19: the fleet's loaded commit, the web workers, and whether the SERVED page and endpoint carry the
# after-midnight rail fix (8455f25c0). Usage: bash served_check.sh <label>
L="${1:-check}"
OUT=/mnt/c/tmp/railmon/prior_live
echo "read_at $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "fleet_commit $(git -C ~/Syndicate rev-parse --short HEAD)"
echo "web_workers $(pgrep -f 'gunicorn' -a | grep -v pgrep | awk '{print $1}' | tr '\n' ' ')"
code=$(nice -n 19 curl -s -o "$OUT/served_$L.html" -w '%{http_code} %{size_download}' http://127.0.0.1:10000/intelligence)
echo "intelligence_http $code"
echo "served_page_has_carry_param $(grep -c 'carry_prior_live=1&sports=' "$OUT/served_$L.html")"
echo "served_page_has_railKeepsChip $(grep -c 'const railKeepsChip = (chip)' "$OUT/served_$L.html")"
code=$(nice -n 19 curl -s -o "$OUT/chips_$L.json" -w '%{http_code} %{size_download}' 'http://127.0.0.1:10000/api/board/game-chips?carry_prior_live=1&sports=mlb,nba,wnba,nhl,nfl,ncaaf,ncaab,wncaab,soccer')
echo "chips_http $code"
python3 - "$OUT/chips_$L.json" <<'PY'
import json, sys
try:
    body = json.load(open(sys.argv[1], encoding="utf-8"))
except Exception as exc:
    print("chips_parse_error", type(exc).__name__)
    raise SystemExit(0)
pdl = body.get("prior_date_live", "ABSENT")
print("endpoint_has_prior_date_live", 0 if pdl == "ABSENT" else 1)
print("prior_date_live", json.dumps(pdl) if pdl != "ABSENT" else "ABSENT")
chips = body.get("chips") or []
print("chips", len(chips), "carried", sum(1 for c in chips if isinstance(c, dict) and c.get("carried_onto")), "source", body.get("source"))
PY
