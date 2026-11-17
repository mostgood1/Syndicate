"""Read-only: one reading of Ask the Syndicate as the fleet serves it, beside the web health it depends on (lane
ask-engine-monitor).

One run = one reading. It never writes to production: a page GET, one GET of the Layer 2 shortlist (to pick real
rows), and a handful of `POST /api/syndicate/query` asks, which only read the snapshot. Asks run one at a time.

What it measures, each with its denominator:
  * THE PAGE: `GET /syndicate` status, time, and the example questions it offers (`data-example`).
  * FREE-TEXT ASKS: each example question exactly as the page sends it (`{question, context: {}}`).
  * BOARD-ROW ASKS: rows picked from `/api/board/layer2-shortlist` (one game line, one player prop, one live row
    when any is live), asked exactly as the Layer 2 Ask button sends them (`ask_bar.js` `contextFromCard` keys).
  * Per ask: HTTP status, seconds, `ok`, error, `schema_type`, `answer_source`, `routed_sport`, the answer's
    `as_of` age, its size, whether it named a board bet, and whether it crossed the pages' 45 s cut-off
    (`syndicate.html` `timeoutMs`, `ask_bar.js` `REQUEST_TIMEOUT_MS`): the user saw "Timed out".
  * WEB HEALTH over --log-minutes of `web.log`: gunicorn WORKER TIMEOUT kills, memory recycles (anon MB against the
    limit), combined-board overlay warms (`build_s`), requests over 20 s and 45 s by route, and every Ask in the
    window from any client.
  * THE HOST: load average, cores, MemAvailable, and the top CPU processes with their nice.

Usage (on the fleet host, at nice 19; it shares the CPU with production):
    nice -n 19 python3 scripts/ask_monitor_probe.py [--out-dir DIR] [--log-minutes 30] [--no-rows]
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping

BASE_URL = "http://127.0.0.1:10000"
CLIENT_CUTOFF_S = 45.0          # syndicate.html timeoutMs / ask_bar.js REQUEST_TIMEOUT_MS
SLOW_S = 20.0
ASK_TIMEOUT_S = 120.0
LOG_TAIL_BYTES = 40 * 1024 * 1024
GAME_MARKETS = ("h2h", "spreads", "totals")

_TS = re.compile(r"^(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?Z) ")
_ACCESS = re.compile(r'"(?P<method>[A-Z]+) (?P<path>\S+) HTTP/[\d.]+" (?P<status>\d{3}) (?P<size>\S+) "[^"]*" '
                     r'"(?P<agent>[^"]*)" (?P<ms>\d+)ms\s*$')
_WARM = re.compile(r"COMBINED_BOARD_OVERLAY_WARMED .*?build_s=(?P<build>[\d.]+).*?rebuilt=(?P<rebuilt>\w+)")
_EXAMPLE = re.compile(r'data-example="([^"]+)"')


def _parse_ts(text: str) -> dt.datetime | None:
    """An ISO stamp; one with no zone (some answers' `as_of`) is read as UTC."""
    try:
        ts = dt.datetime.fromisoformat(str(text).strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return ts if ts.tzinfo is not None else ts.replace(tzinfo=dt.timezone.utc)


# ----------------------------------------------------------------------------- the web log


def parse_log(lines: Iterable[str], since: dt.datetime) -> dict[str, Any]:
    """Web health from web.log lines at or after `since` (each line starts with an ISO Z stamp)."""
    kills: list[str] = []
    recycles: list[dict[str, Any]] = []
    warms: list[float] = []
    slow: Counter = Counter()
    over_cutoff: Counter = Counter()
    asks: list[dict[str, Any]] = []
    requests = 0
    for line in lines:
        m = _TS.match(line)
        if not m:
            continue
        ts = _parse_ts(m.group(1))
        if ts is None or ts < since:
            continue
        stamp = m.group(1)
        if "WORKER TIMEOUT" in line:
            kills.append(stamp)
            continue
        if "WEB_WORKER_MEMORY_RECYCLE" in line:
            try:
                rec = json.loads(line.split("WEB_WORKER_MEMORY_RECYCLE", 1)[1].strip())
            except ValueError:
                rec = {}
            recycles.append({"at": stamp, "anon_mb": rec.get("anon_mb"), "limit_mb": rec.get("limit_mb"),
                             "hard": rec.get("hard"), "age_s": rec.get("age_s")})
            continue
        w = _WARM.search(line)
        if w:
            warms.append(float(w.group("build")))
            continue
        a = _ACCESS.search(line)
        if not a:
            continue
        requests += 1
        path = a.group("path").split("?", 1)[0]
        route = f"{a.group('method')} {path}"
        seconds = int(a.group("ms")) / 1000.0
        if seconds > SLOW_S:
            slow[route] += 1
        if seconds > CLIENT_CUTOFF_S:
            over_cutoff[route] += 1
        if path == "/api/syndicate/query" and a.group("method") == "POST":
            asks.append({"at": stamp, "status": int(a.group("status")), "s": round(seconds, 2),
                         "agent": a.group("agent")[:40]})
    warms_sorted = sorted(warms)
    return {
        "since": since.isoformat(), "requests": requests,
        "worker_timeouts": kills,
        "recycles": {"n": len(recycles), "hard": sum(1 for r in recycles if r.get("hard")),
                     "max_anon_mb": max((r["anon_mb"] for r in recycles if r.get("anon_mb") is not None),
                                        default=None),
                     "limit_mb": max((r["limit_mb"] for r in recycles if r.get("limit_mb") is not None),
                                     default=None)},
        "overlay_warms": {"n": len(warms), "over_20s": sum(1 for w in warms if w > SLOW_S),
                          "over_45s": sum(1 for w in warms if w > CLIENT_CUTOFF_S),
                          "over_60s": sum(1 for w in warms if w > 60.0),
                          "max_s": warms_sorted[-1] if warms_sorted else None,
                          "median_s": warms_sorted[len(warms_sorted) // 2] if warms_sorted else None},
        "slow_over_20s": dict(slow.most_common()),
        "over_45s": dict(over_cutoff.most_common()),
        "asks_any_client": {"n": len(asks), "over_45s": sum(1 for a in asks if a["s"] > CLIENT_CUTOFF_S),
                            "non_200": sum(1 for a in asks if a["status"] != 200), "rows": asks[-20:]},
    }


def read_log_tail(path: Path, tail_bytes: int = LOG_TAIL_BYTES) -> list[str]:
    if not path.exists():
        return []
    size = path.stat().st_size
    with path.open("rb") as fh:
        fh.seek(max(0, size - tail_bytes))
        data = fh.read()
    return data.decode("utf-8", "replace").replace("\x00", "").splitlines()


# ----------------------------------------------------------------------------- the asks


def row_context(row: Mapping[str, Any]) -> dict[str, str]:
    """The context `ask_bar.js` `contextFromCard` sends for a Layer 2 row, from a shortlist row's fields."""
    market = str(row.get("market") or "")
    side = str(row.get("side") or "")
    player = str(row.get("player_name") or "").strip()
    home, away = str(row.get("home_team") or ""), str(row.get("away_team") or "")
    if player:
        name = player
    elif side == "home":
        name = home
    elif side == "away":
        name = away
    else:
        name = side.capitalize()
    ctx = {"sport": str(row.get("sport") or "").lower(), "market": market, "selection": name,
           "matchup": f"{away} @ {home}" if home and away else "", "name": name,
           "event_id": str(row.get("event_id") or ""), "side": side,
           "line": "" if row.get("line") is None else str(row.get("line")), "segment": str(row.get("segment") or "")}
    if player:
        ctx["player_name"] = player
    quote = row.get("quote")
    if isinstance(quote, Mapping) and quote.get("price") is not None:
        ctx["odds"] = str(quote.get("price"))
    return {k: v for k, v in ctx.items() if v}


def row_question(ctx: Mapping[str, str]) -> str:
    """The question the ask bar shows for a row (`askSubjectFromContext`, simplified)."""
    name = ctx.get("name", "")
    if name.lower() in ("over", "under"):
        bet = " ".join(x for x in (name, ctx.get("line", "")) if x)
        subject = f"{bet} in {ctx['matchup']}" if ctx.get("matchup") else bet
    elif ctx.get("player_name"):
        subject = " ".join(x for x in (name, ctx.get("side", "").capitalize(), ctx.get("line", "")) if x)
    else:
        subject = name
    return f"What's the case for and against {subject}?"


def pick_rows(rows: Iterable[Mapping[str, Any]]) -> list[tuple[str, Mapping[str, Any]]]:
    """One pregame game line, one pregame player prop, one live row (any market) when any is live."""
    picked: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        if not row.get("event_id"):
            continue
        live = bool(row.get("is_live"))
        prop = bool(row.get("player_name"))
        if live:
            picked.setdefault("live_row", row)
        elif prop:
            picked.setdefault("pregame_prop", row)
        elif str(row.get("market") or "") in GAME_MARKETS:
            picked.setdefault("pregame_game_line", row)
    return [(k, picked[k]) for k in ("pregame_game_line", "pregame_prop", "live_row") if k in picked]


def _http(method: str, url: str, body: Mapping[str, Any] | None = None, timeout: float = ASK_TIMEOUT_S
          ) -> tuple[int | None, float, bytes, str | None]:
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            return resp.status, time.monotonic() - t0, raw, None
    except urllib.error.HTTPError as exc:
        return exc.code, time.monotonic() - t0, exc.read() or b"", f"HTTP {exc.code}"
    except Exception as exc:  # noqa: BLE001 -- a reading records the failure, it never raises
        return None, time.monotonic() - t0, b"", f"{type(exc).__name__}: {exc}"[:200]


def summarise_answer(raw: bytes, now: dt.datetime) -> dict[str, Any]:
    try:
        d = json.loads(raw)
    except ValueError:
        return {"json": False}
    if not isinstance(d, dict):
        return {"json": False}
    vis = d.get("visuals") if isinstance(d.get("visuals"), dict) else {}
    as_of = vis.get("as_of") or d.get("as_of")
    # A date-only `as_of` (an evidence slate's date, or a fixture's) has no age; only a timestamp does.
    date_only = bool(as_of) and re.fullmatch(r"\d{4}-\d\d-\d\d", str(as_of).strip()) is not None
    ts = _parse_ts(str(as_of)) if as_of and not date_only else None
    named = d.get("board_row") or (d.get("schema") or {}).get("recommendation") if isinstance(d.get("schema"), dict) \
        else d.get("board_row")
    return {"json": True, "ok": d.get("ok"), "error": d.get("error"), "schema_type": d.get("schema_type"),
            "answer_source": d.get("answer_source"), "routed_sport": d.get("routed_sport"),
            "as_of": as_of, "as_of_age_s": None if ts is None else round((now - ts).total_seconds()),
            "as_of_kind": None if not as_of else ("date" if date_only else ("timestamp" if ts else "unparsed")),
            "as_of_in_future": bool((ts is not None and ts > now) or
                                    (date_only and str(as_of).strip() > now.date().isoformat())),
            "tables": len(vis.get("tables") or []) if isinstance(vis.get("tables"), list) else None,
            "charts": len(vis.get("charts") or []) if isinstance(vis.get("charts"), list) else None,
            "named_bet": bool(named)}


def ask(base: str, question: str, context: Mapping[str, Any]) -> dict[str, Any]:
    status, seconds, raw, err = _http("POST", f"{base}/api/syndicate/query", {"question": question,
                                                                             "context": dict(context)})
    out = {"question": question, "status": status, "s": round(seconds, 2), "bytes": len(raw),
           "user_saw_timeout": seconds > CLIENT_CUTOFF_S, "transport_error": err}
    out.update(summarise_answer(raw, dt.datetime.now(dt.timezone.utc)) if raw else {"json": False})
    out["answered"] = bool(status == 200 and out.get("ok") is True and not out["user_saw_timeout"])
    return out


# ----------------------------------------------------------------------------- the host


def host() -> dict[str, Any]:
    out: dict[str, Any] = {"cores": os.cpu_count()}
    try:
        out["loadavg"] = [round(x, 2) for x in os.getloadavg()]
    except OSError:
        out["loadavg"] = None
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemAvailable:"):
                out["mem_available_mb"] = int(line.split()[1]) // 1024
    except OSError:
        pass
    try:
        ps = subprocess.run(["ps", "-eo", "pid,ni,pcpu,rss,etimes,args", "--sort=-pcpu"], capture_output=True,
                            text=True, timeout=20).stdout.splitlines()[1:9]
        out["top"] = [{"pid": int(p[0]), "ni": p[1], "cpu": float(p[2]), "rss_mb": int(p[3]) // 1024,
                       "etimes": int(p[4]), "cmd": " ".join(p[5:])[:110]}
                      for p in (line.split() for line in ps) if len(p) >= 6]
    except (OSError, subprocess.SubprocessError, ValueError):
        out["top"] = None
    return out


# ----------------------------------------------------------------------------- one reading


def reading(base: str, log_path: Path, log_minutes: int, with_rows: bool) -> dict[str, Any]:
    started = dt.datetime.now(dt.timezone.utc)
    out: dict[str, Any] = {"started": started.isoformat(), "base": base, "cutoff_s": CLIENT_CUTOFF_S}
    status, seconds, raw, err = _http("GET", f"{base}/syndicate", timeout=60)
    examples = [html.unescape(x) for x in _EXAMPLE.findall(raw.decode("utf-8", "replace"))] if raw else []
    out["page"] = {"status": status, "s": round(seconds, 2), "error": err, "examples": examples}
    out["free_text"] = [ask(base, q, {}) for q in examples]
    out["rows"] = []
    if with_rows:
        status, seconds, raw, err = _http("GET", f"{base}/api/board/layer2-shortlist", timeout=120)
        out["shortlist"] = {"status": status, "s": round(seconds, 2), "bytes": len(raw), "error": err}
        try:
            rows = json.loads(raw).get("rows") or [] if raw else []
        except ValueError:
            rows = []
        out["shortlist"]["rows"] = len(rows)
        for kind, row in pick_rows(rows):
            ctx = row_context(row)
            out["rows"].append({"kind": kind, "context": ctx, **ask(base, row_question(ctx), ctx)})
    asks = out["free_text"] + out["rows"]
    out["asks"] = {"n": len(asks), "answered": sum(1 for a in asks if a["answered"]),
                   "user_saw_timeout": sum(1 for a in asks if a["user_saw_timeout"]),
                   "max_s": max((a["s"] for a in asks), default=None),
                   "median_s": sorted(a["s"] for a in asks)[len(asks) // 2] if asks else None}
    since = started - dt.timedelta(minutes=log_minutes)
    out["web"] = parse_log(read_log_tail(log_path), since)
    out["host"] = host()
    out["finished"] = dt.datetime.now(dt.timezone.utc).isoformat()
    return out


def summary_line(r: Mapping[str, Any]) -> str:
    a, w, h = r["asks"], r["web"], r["host"]
    return (f"ASK_READING asks={a['answered']}/{a['n']} answered, timeouts_seen={a['user_saw_timeout']} "
            f"median_s={a['median_s']} max_s={a['max_s']} | page={r['page']['status']} {r['page']['s']}s "
            f"| web {w['since'][11:16]}Z+: kills={len(w['worker_timeouts'])} recycles={w['recycles']['n']} "
            f"warms={w['overlay_warms']['n']} (>45s {w['overlay_warms']['over_45s']}, max {w['overlay_warms']['max_s']}) "
            f"slow>20s={sum(w['slow_over_20s'].values())} >45s={sum(w['over_45s'].values())} "
            f"asks_any={w['asks_any_client']['n']} | load={h.get('loadavg')} mem_avail={h.get('mem_available_mb')}MB")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base-url", default=BASE_URL)
    ap.add_argument("--log", default=str(Path.home() / "syndicate-prod" / "logs" / "web.log"))
    ap.add_argument("--log-minutes", type=int, default=30)
    ap.add_argument("--out-dir", default=None)
    ap.add_argument("--no-rows", action="store_true", help="free-text asks only (skip the shortlist read)")
    args = ap.parse_args(argv)
    r = reading(args.base_url.rstrip("/"), Path(args.log), args.log_minutes, not args.no_rows)
    line = summary_line(r)
    print(line, flush=True)
    for a in r["free_text"] + r["rows"]:
        print(f"ASK {a.get('kind', 'free_text'):17s} s={a['s']:6.2f} status={a['status']} ok={a.get('ok')} "
              f"seen_timeout={a['user_saw_timeout']} schema={a.get('schema_type')} as_of_age_s={a.get('as_of_age_s')} "
              f"tables={a.get('tables')} err={a.get('error') or a.get('transport_error')} q={a['question'][:70]!r}",
              flush=True)
    if args.out_dir:
        out = Path(args.out_dir)
        out.mkdir(parents=True, exist_ok=True)
        stamp = r["started"][:19].replace(":", "").replace("-", "")
        (out / f"ask_reading_{stamp}Z.json").write_text(json.dumps(r, indent=1, default=str), encoding="utf-8")
        with (out / "ask_readings.log").open("a", encoding="utf-8") as fh:
            fh.write(f"{r['started']} {line}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
