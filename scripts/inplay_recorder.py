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

Cost: OddsAPI charges markets x regions = 3 x 3 = 9 credits per call (regions
us,eu,uk). Books are polled for a sport only while ESPN shows one of its games
in play (--books-when pre-or-in widens that), so a sport costs ~540 credits per
LIVE hour, 0.011%/h of the 5M monthly cap.

Stop: --until is a hard cap. --stop-after-final-minutes N also stops N minutes
after every ESPN game of the slate (ESPN `dates=<date>`) is final/postponed.
Finalized Kalshi tickers are polled once more for their result, then dropped.
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
    "nfl": {"odds": "americanfootball_nfl", "espn": "football/nfl"},
    # groups=80 = all FBS games, not ESPN's default featured/top-25 list.
    "ncaaf": {"odds": "americanfootball_ncaaf", "espn": "football/college-football", "espn_q": "&groups=80&limit=400"},
}
DONE_STATUS = {"STATUS_POSTPONED", "STATUS_CANCELED", "STATUS_FORFEIT"}
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
    ap.add_argument("--regions", default="us,eu", help="OddsAPI regions; each adds 3 credits per call")
    ap.add_argument("--until", required=True, help="UTC stop time, ISO")
    ap.add_argument("--extra-tickers", default="", help="comma list of Kalshi tickers to poll as well (held positions)")
    ap.add_argument("--books-when", choices=("in", "pre-or-in", "always"), default="in",
                    help="poll OddsAPI for a sport only while ESPN shows a game of it in play (default), also pregame, or always")
    ap.add_argument("--stop-after-final-minutes", type=float, default=0.0,
                    help="stop this many minutes after every ESPN game of the slate is final (0 = only --until)")
    a = ap.parse_args()
    if os.name == "nt":  # Idle priority: the fleet shares this host.
        k32 = ctypes.windll.kernel32
        # HANDLE is 64-bit: without these the pseudo-handle is truncated to a
        # 32-bit int and the call fails SILENTLY (measured 2026-10-21: every
        # recorder ran at Normal).
        k32.GetCurrentProcess.restype = ctypes.c_void_p
        k32.SetPriorityClass.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        if not k32.SetPriorityClass(k32.GetCurrentProcess(), 0x40):
            raise SystemExit("could not set Idle priority")
    elif hasattr(os, "nice"):
        os.nice(19)
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
    settled: set[str] = set()  # tickers whose result has been recorded: not polled again
    espn_states: dict[str, dict[str, str]] = {}  # sport -> {event id: "pre"|"in"|"done"}
    last_open_t = time.time()  # last time any slate game was not done
    ymd = a.date.replace("-", "")
    while datetime.now(timezone.utc) < until:
        t = time.time()
        if t - tick_at > 600 or not tickers:
            extra = [x.strip() for x in a.extra_tickers.split(",") if x.strip()]
            tickers, tick_at = sorted(set(kalshi_tickers(root, sports, a.date)) | set(extra)), t
            emit("log", {"ts": now(), "event": "tickers", "n": len(tickers), "settled": len(settled & set(tickers))})
        polled = [x for x in tickers if x not in settled]
        # A full NCAAF Saturday is ~3,400 tickers = 68 requests: stretch the
        # cycle so the public endpoint is not asked for more than ~2.5 req/s.
        if t - last_k >= max(a.kalshi_seconds, 0.4 * ((len(polled) + 49) // 50)):
            last_k = t
            for i in range(0, len(polled), 50):
                batch = polled[i:i + 50]
                try:
                    d, _ = get_json(KALSHI + "?limit=100&tickers=" + ",".join(batch))
                    ts = now()
                    for m in d.get("markets", []):
                        if m.get("result") and m.get("status") in ("finalized", "settled", "determined"):
                            settled.add(m.get("ticker"))
                        emit("kalshi", {"ts": ts, "t": m.get("ticker"), "ev": m.get("event_ticker"),
                                        "st": m.get("status"), "ya": m.get("yes_ask_dollars"), "yb": m.get("yes_bid_dollars"),
                                        "na": m.get("no_ask_dollars"), "nb": m.get("no_bid_dollars"),
                                        "yas": m.get("yes_ask_size_fp"), "ybs": m.get("yes_bid_size_fp"),
                                        "lp": m.get("last_price_dollars"), "vol": m.get("volume_fp"),
                                        "sub": m.get("yes_sub_title"), "fs": m.get("floor_strike"), "res": m.get("result")})
                except Exception as e:  # noqa: BLE001
                    emit("log", {"ts": now(), "event": "kalshi_error", "err": repr(e)[:300]})
                    if "429" in repr(e):
                        time.sleep(5.0)
                        break
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
                # ESPN first: its state decides whether this sport's books are polled.
                try:
                    d, _ = get_json(ESPN.format(path=cfg["espn"]) + f"?dates={ymd}" + cfg.get("espn_q", ""))
                    ts = now()
                    states = {}
                    for ev in d.get("events", []):
                        c = (ev.get("competitions") or [{}])[0]
                        stt = c.get("status") or ev.get("status") or {}
                        typ = stt.get("type") or {}
                        state = typ.get("state")
                        states[str(ev.get("id"))] = "done" if (state == "post" or typ.get("name") in DONE_STATUS) else (state or "pre")
                        emit("espn", {"ts": ts, "sport": s, "id": ev.get("id"), "name": ev.get("shortName"),
                                      "state": state, "status": typ.get("name"), "start": ev.get("date"),
                                      "detail": typ.get("shortDetail"),
                                      "period": stt.get("period"), "clock": stt.get("displayClock"),
                                      "teams": [{"abbr": (x.get("team") or {}).get("abbreviation"), "ha": x.get("homeAway"),
                                                 "name": (x.get("team") or {}).get("displayName"),
                                                 "score": x.get("score")} for x in c.get("competitors", [])]})
                    espn_states[s] = states
                except Exception as e:  # noqa: BLE001
                    emit("log", {"ts": now(), "event": "espn_error", "sport": s, "err": repr(e)[:300]})
                st = set((espn_states.get(s) or {}).values())
                want = (a.books_when == "always" or "in" in st or (a.books_when == "pre-or-in" and "pre" in st)
                        or s not in espn_states)  # ESPN never read: do not go blind on the books
                if not want:
                    continue
                try:
                    q = urllib.parse.urlencode({"apiKey": key, "regions": a.regions, "markets": "h2h,spreads,totals",
                                                "oddsFormat": "decimal", "dateFormat": "iso"})
                    d, h = get_json(ODDSAPI.format(key=cfg["odds"]) + "?" + q)
                    ts = now()
                    live = [e for e in d if e.get("commence_time", "") <= ts]
                    emit("books", {"ts": ts, "sport": s, "events": live, "n_all": len(d),
                                   "used": h.get("x-requests-used") or h.get("X-Requests-Used"),
                                   "last": h.get("x-requests-last") or h.get("X-Requests-Last")})
                except Exception as e:  # noqa: BLE001
                    emit("log", {"ts": now(), "event": "books_error", "sport": s, "err": repr(e)[:300].replace(key, "<key>")})
            if a.stop_after_final_minutes > 0 and set(espn_states) >= set(sports):
                allst = [v for st_ in espn_states.values() for v in st_.values()]
                if not allst or any(v != "done" for v in allst):
                    last_open_t = t
                elif t - last_open_t >= a.stop_after_final_minutes * 60:
                    emit("log", {"ts": now(), "event": "slate_final", "games": len(allst)})
                    break
        time.sleep(1.0)
    emit("log", {"ts": now(), "event": "stopped"})
    return 0


if __name__ == "__main__":
    sys.exit(main())
