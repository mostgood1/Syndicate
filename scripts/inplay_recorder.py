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

Cost: OddsAPI charges markets x regions = 3 x 2 = 6 credits per call (regions
us,eu; the nightly passed us,eu,uk = 9 until 2026-10-24). Books are polled for a sport only while ESPN shows one of its games
in play (--books-when pre-or-in widens that), so a sport costs ~360 credits per
LIVE hour, 0.007%/h of the 5M monthly cap.

Stop: --until is a hard cap. --stop-after-final-minutes N also stops N minutes
after every ESPN game of the slate (ESPN `dates=<date>`) is final/postponed.
Finalized Kalshi tickers are polled once more for their result, then dropped.

Which Kalshi markets (lane inplay-recorder-discovery, 2026-11-17): every
--tickers-seconds, the union of (a) Kalshi's own public listing of tonight's
full-game markets (`FULL_GAME_SERIES`, `discover_tickers`) and (b) the fleet's
capture file `venue_odds/kalshi__<sport>__<date>.json`. A ticker stays polled
until its result is recorded, even if both sources stop listing it. The capture
file alone was capped at 8,000 markets (`venue_daily_odds.MAX_MARKETS_PER_FILE`),
and on NCAAF Saturday 2026-11-14 it sat at the cap, so markets dropped in and out
of the list for 10 to 80 minutes at a time.

How fast: every Kalshi request, poll or discovery, waits its turn at
--kalshi-rate (1.25/s), with --kalshi-batch (200) tickers per poll request. A 429
ends that cycle; the next cycle starts at the batch that failed. Until 2026-11-17
the loop fired each cycle's 50-ticker batches back to back (~5 req/s) and started
every cycle at the top of the sorted list. A 429 then cut most Saturday cycles
short, and the tail of the list went unpolled: on 11-14 that meant 90,485
gaps > 120 s, against 387 from the cap.

Why 200 x 1.25/s and not 100 x 2.5/s (dry A/B, 2026-11-18, 4,663 markets): the
same tickers per second in half the requests drew 3-6 Kalshi 429s per 15 min
against 6-16, and a gap's worst case is two 429s in a row (35-40 s idle). Do not
retry sooner after a 429: tested, it drew about 3x the 429s.
(.syndicate/findings_2026-11-17_inplay_recorder_discovery.md section 3.)
"""

from __future__ import annotations

import argparse
import bisect
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
# Kalshi's full-game series per sport, listed by `discover_tickers`. These are exactly
# the families the capture file has fed this recorder on every night checked (11-07,
# 11-13..11-16). KXNHLTOTAL is left out: it has never come through the capture file,
# and adding it would put an NHL totals population into lane in-game-trading's stage-2
# scoreboard (inplay_fair_score scores any *TOTAL family). That is the lane's call.
FULL_GAME_SERIES = {
    "nba": ("KXNBAGAME", "KXNBASPREAD", "KXNBATOTAL"),
    "nhl": ("KXNHLGAME", "KXNHLSPREAD"),
    "nfl": ("KXNFLGAME", "KXNFLSPREAD", "KXNFLTOTAL"),
    "ncaaf": ("KXNCAAFGAME", "KXNCAAFSPREAD", "KXNCAAFTOTAL"),
}
MONTHS = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")[:-4] + "Z"


def get_json(url: str, timeout: float = 15.0):
    req = urllib.request.Request(url, headers={"User-Agent": "syndicate-inplay-recorder/1"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8")), dict(r.headers)


# The primary dev checkout's .env; the checkout moves out of OneDrive (docs/ai_context/repo_out_of_onedrive_plan.md,
# F6). The first that exists wins, so the default works on either side of the move; SYNDICATE_ENV_FILE overrides.
ENV_CANDIDATES = (r"C:\Users\tempadmin\Coding\Syndicate\.env", r"C:\Users\tempadmin\OneDrive\Coding\Syndicate\.env")


def default_env_file() -> str:
    override = os.environ.get("SYNDICATE_ENV_FILE", "").strip()
    if override:
        return override
    for cand in ENV_CANDIDATES:
        if Path(cand).is_file():
            return cand
    return ENV_CANDIDATES[0]


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


def date_code(date: str) -> str:
    """'2026-11-14' -> '26NOV14', the date segment of a Kalshi event ticker
    (KXNCAAFGAME-26NOV14VALPSTET). Not strftime('%b'): that is locale-dependent."""
    y, m, d = (int(x) for x in date.split("-"))
    return f"{y % 100:02d}{MONTHS[m - 1]}{d:02d}"


def on_date(event_ticker, code: str) -> bool:
    parts = str(event_ticker or "").split("-", 2)
    return len(parts) > 1 and parts[1].startswith(code)


class Pacer:
    """At most `rate` Kalshi requests per second, evenly spaced (no bursts)."""

    def __init__(self, rate: float, clock=time.monotonic, sleep=time.sleep):
        self.interval = 1.0 / rate if rate > 0 else 0.0
        self.clock, self.sleep, self.next_at = clock, sleep, 0.0

    def wait(self) -> None:
        t = self.clock()
        if t < self.next_at:
            self.sleep(self.next_at - t)
            t = self.next_at
        self.next_at = t + self.interval


def discover_tickers(sports, date: str, get=None, pace=None, sleep=time.sleep, max_pages: int = 20):
    """Tonight's full-game Kalshi tickers from the PUBLIC listing: (sorted tickers, errors).

    `status=open` lists every date's open markets in a series (measured 2026-11-17: 15
    requests, ~11 MB, for all twelve series); the event ticker's date code keeps
    tonight's. A market drops out of this listing once it closes, which is why the
    caller keeps every ticker it has seen until the result is recorded. One series
    failing leaves the others; a 429 also waits 5 s, as the poll loop does."""
    get = get or get_json
    code = date_code(date)
    found: set[str] = set()
    errors: list[str] = []
    for s in sports:
        for series in FULL_GAME_SERIES.get(s, ()):
            cursor = ""
            for _ in range(max_pages):
                if pace:
                    pace()
                q = f"?series_ticker={series}&status=open&limit=1000"
                if cursor:
                    q += "&cursor=" + urllib.parse.quote(cursor, safe="")
                try:
                    d, _ = get(KALSHI + q, timeout=30.0)
                except Exception as e:  # noqa: BLE001
                    errors.append(f"{series}: {e!r}"[:200])
                    if "429" in repr(e):
                        sleep(5.0)
                    break
                ms = d.get("markets") or []
                found.update(str(m["ticker"]) for m in ms if m.get("ticker") and on_date(m.get("event_ticker"), code))
                cursor = d.get("cursor") or ""
                if not cursor or not ms:
                    break
    return sorted(found), errors


def refresh_tickers(known: set, root: Path, sports, date: str, extra, discover: bool, pace=None, get=None):
    """Grow `known` with this refresh's tickers; return (sorted list, log fields).

    Both sources are unioned and NOTHING is dropped here: a ticker leaves the poll
    list only once its result is recorded (the caller's `settled`)."""
    cap = kalshi_tickers(root, sports, date)
    found, errors = discover_tickers(sports, date, get=get, pace=pace) if discover else ([], [])
    known |= set(cap) | set(found) | set(extra)
    cs, fs = set(cap), set(found)
    return sorted(known), {"capture": len(cs), "discovered": len(fs), "discovered_only": len(fs - cs),
                           "capture_only": len(cs - fs), "discover_errors": errors[:5]}


def poll_cycle(polled, start_at: str, batch: int, get, pace, on_market, on_error, sleep=time.sleep) -> str:
    """One pass over the sorted `polled` list, `batch` tickers per request, starting at
    the first ticker >= `start_at` and wrapping round. Returns where the next cycle
    starts: "" after a full pass, or the first ticker of the batch a 429 stopped. So a
    429 delays that batch by one cycle instead of starving every ticker after it."""
    if not polled:
        return ""
    i0 = bisect.bisect_left(polled, start_at) % len(polled) if start_at else 0
    order = polled[i0:] + polled[:i0]
    for i in range(0, len(order), batch):
        chunk = order[i:i + batch]
        pace()
        try:
            d, _ = get(KALSHI + f"?limit={max(100, batch)}&tickers=" + ",".join(chunk))
            ts = now()
            for m in d.get("markets", []):
                on_market(ts, m)
        except Exception as e:  # noqa: BLE001
            on_error(e)
            if "429" in repr(e):
                sleep(5.0)
                return chunk[0]
    return ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True)
    ap.add_argument("--sports", default="nba,nhl")
    ap.add_argument("--out", required=True)
    ap.add_argument("--fleet-root", default=r"\\wsl.localhost\Ubuntu-24.04\home\amyn\syndicate-prod\data\reports\intelligence\venue_odds")
    ap.add_argument("--env", default=default_env_file())
    ap.add_argument("--kalshi-seconds", type=float, default=10.0)
    ap.add_argument("--kalshi-rate", type=float, default=1.25,
                    help="ceiling on Kalshi requests per second, polls and discovery alike, evenly spaced")
    ap.add_argument("--kalshi-batch", type=int, default=200,
                    help="tickers per Kalshi poll request (Kalshi returned all of them at 50-200; 200 drew the fewest 429s)")
    ap.add_argument("--tickers-seconds", type=float, default=600.0, help="how often the Kalshi ticker list is refreshed")
    ap.add_argument("--no-discover", action="store_true",
                    help="take Kalshi tickers from the fleet capture file only (the pre-2026-11-17 source)")
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

    tickers, tick_at, last_k, last_f, last_b = [], -1e9, 0.0, 0.0, 0.0
    known: set[str] = set()  # every Kalshi ticker listed tonight by either source; never shrinks
    resume_at = ""  # where the next Kalshi cycle starts ("" = the top); set by a 429
    pacer = Pacer(a.kalshi_rate)
    poly_seen: dict[str, str] = {}
    settled: set[str] = set()  # tickers whose result has been recorded: not polled again
    espn_states: dict[str, dict[str, str]] = {}  # sport -> {event id: "pre"|"in"|"done"}
    last_open_t = time.time()  # last time any slate game was not done
    ymd = a.date.replace("-", "")

    def on_market(ts, m):
        if m.get("result") and m.get("status") in ("finalized", "settled", "determined"):
            settled.add(m.get("ticker"))
        emit("kalshi", {"ts": ts, "t": m.get("ticker"), "ev": m.get("event_ticker"),
                        "st": m.get("status"), "ya": m.get("yes_ask_dollars"), "yb": m.get("yes_bid_dollars"),
                        "na": m.get("no_ask_dollars"), "nb": m.get("no_bid_dollars"),
                        "yas": m.get("yes_ask_size_fp"), "ybs": m.get("yes_bid_size_fp"),
                        "lp": m.get("last_price_dollars"), "vol": m.get("volume_fp"),
                        "sub": m.get("yes_sub_title"), "fs": m.get("floor_strike"), "res": m.get("result")})

    def on_error(e):
        emit("log", {"ts": now(), "event": "kalshi_error", "err": repr(e)[:300]})

    while datetime.now(timezone.utc) < until:
        t = time.time()
        # Refresh: on schedule, or (when the list is still empty) once a minute -- not every
        # 1 s loop, now that a refresh asks Kalshi ~15 requests.
        if t - tick_at >= a.tickers_seconds or (not tickers and t - tick_at >= 60):
            extra = [x.strip() for x in a.extra_tickers.split(",") if x.strip()]
            tickers, info = refresh_tickers(known, root, sports, a.date, extra, not a.no_discover, pace=pacer.wait)
            tick_at = t
            emit("log", {"ts": now(), "event": "tickers", "n": len(tickers), "settled": len(settled & set(tickers)), **info})
        polled = [x for x in tickers if x not in settled]
        # The pacer holds every request to --kalshi-rate, so a cycle of n requests takes
        # n / rate seconds; a short list still waits --kalshi-seconds between cycles.
        n_req = (len(polled) + a.kalshi_batch - 1) // a.kalshi_batch
        if t - last_k >= max(a.kalshi_seconds, n_req / max(a.kalshi_rate, 1e-9)):
            last_k = t
            resume_at = poll_cycle(polled, resume_at, a.kalshi_batch, get_json, pacer.wait, on_market, on_error)
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
