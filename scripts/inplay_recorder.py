"""Read-only in-play quote recorder (lane in-game-trading, 2026-10-20).

Records, for tonight's games of the given sports, side by side:
  * Kalshi full-game h2h/spreads/totals quotes, polled directly from the PUBLIC
    market endpoint (no credentials) every --kalshi-seconds;
  * the fleet's own Polymarket quote store (venue_odds/polymarket__<sport>__<date>.json),
    newest point per full-game market, every --fleet-seconds -- this measures the
    FLEET's Polymarket cadence, not the venue's;
  * OddsAPI in-play sportsbook odds (regions us,eu so Pinnacle is present) every
    --books-seconds;
  * ESPN scoreboard state (period, clock, score) every --books-seconds.

It sends no order, reads no credential except ODDS_API_KEY, and writes only to
--out. Every row carries its own UTC receive time. Analysis lives in
scripts/inplay_edge_report.py.

Cost: OddsAPI charges markets x regions = 3 x 2 = 6 credits per call that returns
events; 2 sports x 60 calls/h = 720 credits/h (0.014%/h of the 5M monthly cap).
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

KALSHI = "https://external-api.kalshi.com/trade-api/v2/markets"
ODDSAPI = "https://api.the-odds-api.com/v4/sports/{key}/odds"
ESPN = "https://site.api.espn.com/apis/site/v2/sports/{path}/scoreboard"
SPORTS = {
    "nba": {"odds": "basketball_nba", "espn": "basketball/nba"},
    "nhl": {"odds": "icehockey_nhl", "espn": "hockey/nhl"},
}
FULL_GAME = {"h2h", "spreads", "totals"}


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")[:-4] + "Z"


def get_json(url: str, timeout: float = 15.0):
    req = urllib.request.Request(url, headers={"User-Agent": "syndicate-inplay-recorder/1"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8")), dict(r.headers)


def odds_key(env_path: Path) -> str:
    for line in env_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("ODDS_API_KEY="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("ODDS_API_KEY not in env file")


def fleet_file(root: Path, venue: str, sport: str, date: str) -> Path:
    return root / f"{venue}__{sport}__{date.replace('-', '_')}.json"


def kalshi_tickers(root: Path, sports, date: str) -> list[str]:
    out = []
    for s in sports:
        try:
            d = json.loads(fleet_file(root, "kalshi", s, date).read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            print(f"TICKERS_READ_FAILED sport={s} err={e!r}", flush=True)
            continue
        out += [t for t, v in d.get("markets", {}).items() if v.get("market") in FULL_GAME]
    return sorted(set(out))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True)
    ap.add_argument("--sports", default="nba,nhl")
    ap.add_argument("--out", required=True)
    ap.add_argument("--fleet-root", default=r"\\wsl.localhost\Ubuntu-24.04\home\amyn\syndicate-prod\data\reports\intelligence\venue_odds")
    ap.add_argument("--env", default=r"C:\Users\tempadmin\OneDrive\Coding\Syndicate\.env")
    ap.add_argument("--kalshi-seconds", type=float, default=10.0)
    ap.add_argument("--fleet-seconds", type=float, default=60.0)
    ap.add_argument("--books-seconds", type=float, default=60.0)
    ap.add_argument("--until", required=True, help="UTC stop time, ISO")
    ap.add_argument("--extra-tickers", default="", help="comma list of Kalshi tickers to poll as well (held positions)")
    a = ap.parse_args()
    if os.name == "nt":  # Idle priority: the fleet shares this host.
        ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), 0x40)
    sports = [s.strip() for s in a.sports.split(",") if s.strip() and s.strip() != "none"]
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    root = Path(a.fleet_root)
    key = odds_key(Path(a.env))
    until = datetime.fromisoformat(a.until.replace("Z", "+00:00"))
    files = {n: open(out / f"{n}.jsonl", "a", encoding="utf-8") for n in ("kalshi", "polymarket_fleet", "books", "espn", "log")}

    def emit(name, row):
        files[name].write(json.dumps(row, separators=(",", ":")) + "\n")
        files[name].flush()

    tickers, tick_at, last_k, last_f, last_b = [], 0.0, 0.0, 0.0, 0.0
    poly_seen: dict[str, str] = {}
    while datetime.now(timezone.utc) < until:
        t = time.time()
        if t - tick_at > 600 or not tickers:
            extra = [x.strip() for x in a.extra_tickers.split(",") if x.strip()]
            tickers, tick_at = sorted(set(kalshi_tickers(root, sports, a.date)) | set(extra)), t
            emit("log", {"ts": now(), "event": "tickers", "n": len(tickers)})
        if t - last_k >= a.kalshi_seconds:
            last_k = t
            for i in range(0, len(tickers), 50):
                batch = tickers[i:i + 50]
                try:
                    d, _ = get_json(KALSHI + "?limit=100&tickers=" + ",".join(batch))
                    ts = now()
                    for m in d.get("markets", []):
                        emit("kalshi", {"ts": ts, "t": m.get("ticker"), "ev": m.get("event_ticker"),
                                        "st": m.get("status"), "ya": m.get("yes_ask_dollars"), "yb": m.get("yes_bid_dollars"),
                                        "na": m.get("no_ask_dollars"), "nb": m.get("no_bid_dollars"),
                                        "yas": m.get("yes_ask_size_fp"), "ybs": m.get("yes_bid_size_fp"),
                                        "lp": m.get("last_price_dollars"), "vol": m.get("volume_fp"),
                                        "sub": m.get("yes_sub_title"), "fs": m.get("floor_strike"), "res": m.get("result")})
                except Exception as e:  # noqa: BLE001
                    emit("log", {"ts": now(), "event": "kalshi_error", "err": repr(e)[:300]})
        if t - last_f >= a.fleet_seconds:
            last_f = t
            for s in sports:
                try:
                    d = json.loads(fleet_file(root, "polymarket", s, a.date).read_text(encoding="utf-8"))
                except Exception as e:  # noqa: BLE001
                    emit("log", {"ts": now(), "event": "poly_read_error", "sport": s, "err": repr(e)[:200]})
                    continue
                ts = now()
                for mk, v in d.get("markets", {}).items():
                    if v.get("market") not in FULL_GAME or not v.get("points"):
                        continue
                    p = v["points"][-1]
                    if poly_seen.get(mk) == p.get("ts"):
                        continue
                    poly_seen[mk] = p.get("ts")
                    emit("polymarket_fleet", {"ts": ts, "sport": s, "k": mk, "ev": v.get("event"), "m": v.get("market"),
                                              "line": v.get("line"), "side": v.get("side"), "player": v.get("player"),
                                              "pt": p, "file_updated": d.get("updated_at")})
        if t - last_b >= a.books_seconds:
            last_b = t
            for s in sports:
                cfg = SPORTS[s]
                try:
                    q = urllib.parse.urlencode({"apiKey": key, "regions": "us,eu", "markets": "h2h,spreads,totals",
                                                "oddsFormat": "decimal", "dateFormat": "iso"})
                    d, h = get_json(ODDSAPI.format(key=cfg["odds"]) + "?" + q)
                    ts = now()
                    live = [e for e in d if e.get("commence_time", "") <= ts]
                    emit("books", {"ts": ts, "sport": s, "events": live, "n_all": len(d),
                                   "used": h.get("x-requests-used") or h.get("X-Requests-Used"),
                                   "last": h.get("x-requests-last") or h.get("X-Requests-Last")})
                except Exception as e:  # noqa: BLE001
                    emit("log", {"ts": now(), "event": "books_error", "sport": s, "err": repr(e)[:300].replace(key, "<key>")})
                try:
                    d, _ = get_json(ESPN.format(path=cfg["espn"]))
                    ts = now()
                    for ev in d.get("events", []):
                        c = (ev.get("competitions") or [{}])[0]
                        stt = c.get("status") or ev.get("status") or {}
                        emit("espn", {"ts": ts, "sport": s, "id": ev.get("id"), "name": ev.get("shortName"),
                                      "state": (stt.get("type") or {}).get("state"), "detail": (stt.get("type") or {}).get("shortDetail"),
                                      "period": stt.get("period"), "clock": stt.get("displayClock"),
                                      "teams": [{"abbr": (x.get("team") or {}).get("abbreviation"), "ha": x.get("homeAway"),
                                                 "score": x.get("score")} for x in c.get("competitors", [])]})
                except Exception as e:  # noqa: BLE001
                    emit("log", {"ts": now(), "event": "espn_error", "sport": s, "err": repr(e)[:300]})
        time.sleep(1.0)
    emit("log", {"ts": now(), "event": "stopped"})
    return 0


if __name__ == "__main__":
    sys.exit(main())
