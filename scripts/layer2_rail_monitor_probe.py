"""Read-only: one reading of the Layer 2 board's Games Rail as the fleet serves it (lane layer2-rail-monitor).

One run = one reading. It never writes to production; every request is a plain GET or the page's own
read-only board query (`background: true`, `force_refresh: false`, the page's exact payload).

What it measures, each as a rate with its denominator:
  * LOAD: time and size of the board page, the board query, /api/board/layer2-shortlist,
    /api/board/game-chips and /api/board/live-rail (three reads ~10 s apart: a producer counter is not
    the served count).
  * LIVE RECOMMENDATIONS: the served page's OWN rail code (`layer2_rail_monitor_run.mjs` slices
    deriveGameCards / liveRailSummary / liveRowFreshEdge out of the served HTML) decides which live cards
    and which MODEL != LINE flags the default rail (today, Central) shows. This script then re-derives
    every live row's qualification INDEPENDENTLY from its fields -- gap >= 3 pp (live sim probability vs
    the no-vig fair, else the live join's model_edge_pct on a live_aware row), quote <= 120 s at pricing,
    age now <= 300 s -- and counts false flags (shown, not qualifying), missed flags (qualifying, not
    shown) and flags gone dark (gap and fresh pricing, but the price is now > 300 s old). Every shown flag
    is appended to <out>/flags.jsonl for grading against finals later.
  * REFRESH: the live-rail's newest overlay age; board `written_at` age; fleet role logs over the last
    --log-minutes: INPLAY_OVERLAY gaps and elapsed per sport, BOOK_GRID_TICK build seconds and
    deferred_slow, web INPLAY_OVERLAY_MERGED stale counts, latest LAYER2_BOARD_HEALTH per sport.
  * MISMATCHED TEAMS: chip-less cards, the three duplicate detectors of game_rail_production_replay.mjs
    (detector 3 is the one that sees the 2026-09-16 shape), flipped home/away, abbreviations that look
    minted from a truncated name, and live chips with no live rail card.

Usage:  py -3 scripts/layer2_rail_monitor_probe.py [--out-dir C:\\tmp\\railmon\\readings] [--log-minutes 30]
Run at Idle priority on the fleet host (it shares the CPU with production).
"""
from __future__ import annotations

import argparse
import datetime as dt
import gzip
import json
import os
import statistics
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
# PRODUCTION IS THE FLEET, ONLY (user 2026-11-15: "we shouldnt be using render for anything anymore").
# Pinned here rather than taken from scripts/_base_url.py, whose precedence lets an exported
# SYNDICATE_BASE_URL (or a Render host) pick the target. A non-loopback --base-url is refused.
FLEET_BASE_URL = "http://127.0.0.1:10000"

CT = ZoneInfo("America/Chicago")
CHIP_SPORTS = "mlb,nba,wnba,nhl,nfl,ncaaf,ncaab,wncaab,soccer"
QUERY_BODY = {"question": "top edges today", "mode": "recommendation", "timing": "all", "background": True,
              "force_refresh": False, "slim_aliases": True, "drop_row_diagnostics": True}
MIN_PP, FRESH_S, STALE_S = 3.0, 120.0, 300.0


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def iso(t: dt.datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_ts(v):
    if not v:
        return None
    try:
        return dt.datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None


def fetch(base, path, out_file, body=None, timeout=300):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method="POST" if body is not None else "GET",
                                 headers={"Content-Type": "application/json", "Accept-Encoding": "gzip"})
    t0 = time.monotonic()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        first = time.monotonic()
        raw = r.read()
        code = r.status
        enc = r.headers.get("Content-Encoding")
    t1 = time.monotonic()
    payload = gzip.decompress(raw) if enc == "gzip" else raw
    Path(out_file).write_bytes(payload)
    return {"path": path, "code": code, "seconds": round(t1 - t0, 3), "ttfb": round(first - t0, 3),
            "wire_bytes": len(raw), "bytes": len(payload)}


def pct(values, q):
    v = sorted(x for x in values if x is not None)
    if not v:
        return None
    k = max(0, min(len(v) - 1, int(round(q * (len(v) - 1)))))
    return round(v[k], 1)


def dist(values):
    v = [x for x in values if x is not None]
    return {"n": len(v), "p50": pct(v, 0.5), "p90": pct(v, 0.9), "max": round(max(v), 1) if v else None}


def wsl(cmd: str, timeout=120) -> str:
    try:
        r = subprocess.run(["wsl", "--", "bash", "-c", cmd], capture_output=True, timeout=timeout)
        return r.stdout.decode("utf-8", "replace")
    except Exception as exc:  # the log half is optional; the HTTP half stands alone
        return f"__ERR__ {exc}"


LOG_SH = r"""#!/bin/bash
# $1 = cutoff ISO. Lines start with an ISO timestamp; tail bounds the cost.
cd ~/syndicate-prod/logs || exit 0
tail -n 120000 refresh-worker.log | grep -a -E 'INPLAY_OVERLAY sport=|BOOK_GRID_TICK |LAYER2_BOARD_HEALTH|LIVE_GAMELINE_JOIN' | awk -v c="$1" '$1 >= c'
echo '@@WEB@@'
tail -n 60000 web.log | grep -a 'INPLAY_OVERLAY_MERGED' | awk -v c="$1" '$1 >= c'
"""


def to_wsl_path(p: Path) -> str:
    s = str(p.resolve()).replace("\\", "/")
    return f"/mnt/{s[0].lower()}{s[2:]}" if len(s) > 2 and s[1] == ":" else s


def fleet_logs(minutes: int, now: dt.datetime, work_dir: Path) -> dict:
    cutoff = iso(now - dt.timedelta(minutes=minutes))
    sh = work_dir / "fleet_logs.sh"
    sh.write_bytes(LOG_SH.encode())  # LF only: bash rejects CRLF
    try:
        r = subprocess.run(["wsl", "--", "nice", "-n", "19", "bash", to_wsl_path(sh), cutoff], capture_output=True, timeout=180)
        text = r.stdout.decode("utf-8", "replace")
    except Exception as exc:  # the log half is optional; the HTTP half stands alone
        text = f"__ERR__ {exc}"
    rw, _, web = text.partition("@@WEB@@")
    overlay, ticks, health, joins = {}, [], {}, {}
    for line in rw.splitlines():
        ts = line.split(" ", 1)[0]
        if "INPLAY_OVERLAY sport=" in line:
            kv = dict(p.split("=", 1) for p in line.split() if "=" in p)
            try:  # a non-numeric value means the line is someone's echoed command text, not a build
                rec = (ts, float(kv.get("elapsed_ms", "nan")) / 1000.0, int(kv.get("rows_inplay", 0) or 0), int(kv.get("cards", -1)))
            except ValueError:
                continue
            if not ts[:4].isdigit():
                continue
            overlay.setdefault(kv.get("sport"), []).append(rec)
        elif "BOOK_GRID_TICK " in line:
            try:
                ticks.append((ts, json.loads(line.split("BOOK_GRID_TICK ", 1)[1])))
            except ValueError:
                pass
        elif "LAYER2_BOARD_HEALTH" in line:
            kv = dict(p.split("=", 1) for p in line.split() if "=" in p)
            health[kv.get("sport")] = {"ts": ts, **{k: kv.get(k) for k in ("rows", "live_rows", "live_proj", "pregame_proj", "no_proj", "age_p50s", "age_p90s")}}
        elif "LIVE_GAMELINE_JOIN" in line:
            kv = dict(p.split("=", 1) for p in line.split() if "=" in p)
            joins[kv.get("sport")] = {"ts": ts, **{k: v for k, v in kv.items() if k != "sport"}}
    over = {}
    for sport, xs in overlay.items():
        times = [parse_ts(t) for t, _, _, _ in xs]
        gaps = [(b - a).total_seconds() for a, b in zip(times, times[1:]) if a and b]
        last = times[-1]
        over[sport] = {"builds": len(xs), "gap": dist(gaps), "gaps_over_360": sum(1 for g in gaps if g > 360),
                       "elapsed": dist([e for _, e, _, _ in xs]), "rows_inplay_last": xs[-1][2],
                       # A build that kept in-play rows but published 0 cards: those games' live lines leave the rail.
                       "zero_card_builds_with_rows": sum(1 for _, _, r, c in xs if r > 0 and c == 0),
                       "since_last_s": round((now - last).total_seconds(), 1) if last else None}
    build = {}
    deferred = {}
    for _, t in ticks:
        for s, sec in (t.get("build_seconds") or {}).items():
            build.setdefault(s, []).append(sec)
        for s in t.get("deferred_slow") or []:
            deferred[s] = deferred.get(s, 0) + 1
    tick_times = [parse_ts(ts) for ts, _ in ticks]
    tick_gaps = [(b - a).total_seconds() for a, b in zip(tick_times, tick_times[1:]) if a and b]
    merged = {"lines": 0, "stale": {}, "fresh": {}}
    for line in web.splitlines():
        if "sports={" not in line:
            continue
        merged["lines"] += 1
        try:
            sports = eval(line.split("sports=", 1)[1].strip(), {"__builtins__": {}})  # a logged python dict literal
        except Exception:
            continue
        for s, v in sports.items():
            bucket = "stale" if isinstance(v, str) and v.startswith("stale") else "fresh"
            merged[bucket][s] = merged[bucket].get(s, 0) + 1
    return {"window_min": minutes, "overlay": over, "ticks": len(ticks), "tick_gap": dist(tick_gaps),
            "build_seconds": {s: dist(v) for s, v in build.items()}, "deferred_slow": deferred,
            "web_merge": merged, "health": health, "joins": joins,
            "log_error": text[:200] if text.startswith("__ERR__") else None}


def independent_gap(r):
    lmp, fair = r.get("live_model_probability"), r.get("fair")
    try:
        if lmp is not None and fair is not None and 0 < float(lmp) < 1 and 0 < float(fair) < 1:
            return (float(lmp) - float(fair)) * 100.0
    except (TypeError, ValueError):
        pass
    if r.get("live_aware") is True and r.get("model_edge_pct") is not None:
        try:
            return float(r["model_edge_pct"])
        except (TypeError, ValueError):
            return None
    return None


def independent_age_now(r, now, board_built):
    priced = r.get("book_age_seconds")
    if priced is None:
        return None
    built = parse_ts(r.get("price_grid_generated_at")) or board_built
    if built is None:
        return None
    return float(priced) + max(0.0, (now - built).total_seconds())


def looks_truncated(abbr: str) -> bool:
    a = str(abbr or "")
    return bool(a) and (len(a) > 5 or (a[:1].isupper() and a[1:].islower() and len(a) >= 4))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default=FLEET_BASE_URL)
    ap.add_argument("--out-dir", default=r"C:\tmp\railmon\readings")
    ap.add_argument("--log-minutes", type=int, default=30)
    ap.add_argument("--rail-date", default=None, help="default: today, Central (the page's default day)")
    ap.add_argument("--no-page", action="store_true", help="skip the 19 MB page fetch; reuse the last served.html")
    args = ap.parse_args()
    base = args.base_url.rstrip("/")
    host = urllib.parse.urlsplit(base).hostname or ""
    if host not in ("127.0.0.1", "localhost", "::1"):
        sys.exit(f"refusing {base!r}: this probe reads the local fleet only (production is the fleet, not Render)")
    start = utcnow()
    rail_date = args.rail_date or start.astimezone(CT).date().isoformat()
    out_dir = Path(args.out_dir)
    stamp = start.strftime("%Y%m%dT%H%M%SZ")
    rdir = out_dir / stamp
    rdir.mkdir(parents=True, exist_ok=True)
    reading = {"read_at": iso(start), "read_at_ct": start.astimezone(CT).strftime("%Y-%m-%d %I:%M:%S %p CT"),
               "rail_date": rail_date, "base": base, "load": []}
    # ---- LOAD
    page = out_dir / "served.html"
    if not args.no_page or not page.exists():
        reading["load"].append(fetch(base, "/intelligence", page))
    reading["load"].append(fetch(base, "/api/board/layer2-shortlist", rdir / "shortlist.json"))
    reading["load"].append(fetch(base, f"/api/board/game-chips?sports={CHIP_SPORTS}", rdir / "chips.json"))
    reading["load"].append(fetch(base, "/api/intelligence/query", rdir / "query.json", body=QUERY_BODY))
    lr_reads = []
    for i in range(3):
        if i:
            time.sleep(10)
        f = rdir / f"liverail_{i}.json"
        meta = fetch(base, "/api/board/live-rail", f)
        reading["load"].append(meta)
        doc = json.loads(f.read_bytes())
        read_at = parse_ts(doc.get("read_at"))
        newest = parse_ts(doc.get("newest_written_at"))
        lr_reads.append({"rows": len(doc.get("rows") or []), "sports": doc.get("sports"), "enabled": doc.get("enabled"),
                         "newest_written_at": doc.get("newest_written_at"),
                         "newest_age_s": round((read_at - newest).total_seconds(), 1) if read_at and newest else None})
    reading["live_rail"] = lr_reads
    now = utcnow()
    # ---- board state
    sl = json.loads((rdir / "shortlist.json").read_bytes())
    wa = parse_ts(sl.get("written_at"))
    reading["shortlist"] = {k: sl.get(k) for k in ("written_at", "build_age_seconds", "returned", "total_rows",
                                                   "rows_live_state_stale", "rows_player_out_on_feed", "shard_index_stale")}
    reading["shortlist"]["written_age_s"] = round((now - wa).total_seconds(), 1) if wa else None
    q = json.loads((rdir / "query.json").read_bytes())
    reading["query"] = {k: q.get(k) for k in ("snapshot_generated_at", "state_last_updated", "selected_date")}
    snap = parse_ts(q.get("snapshot_generated_at"))
    reading["query"]["snapshot_age_s"] = round((now - snap).total_seconds(), 1) if snap else None
    # ---- the served page's own rail code
    runner = HERE / "layer2_rail_monitor_run.mjs"
    out_json = rdir / "rail.json"
    proc = subprocess.run(["node", str(runner), str(page), str(rdir / "query.json"), str(rdir / "chips.json"),
                           str(rdir / "liverail_2.json"), iso(now), str(out_json), rail_date],
                          capture_output=True, timeout=600)
    reading["runner"] = (proc.stdout.decode() + proc.stderr.decode()).strip()[-600:]
    rail = json.loads(out_json.read_bytes())
    cards = rail["cards"]
    live = [c for c in cards if c["live"]]
    by_sport = {}
    for c in cards:
        by_sport.setdefault(c["sport"], {"cards": 0, "live": 0, "flags": 0, "chipless": 0})
        by_sport[c["sport"]]["cards"] += 1
        if c["live"]:
            by_sport[c["sport"]]["live"] += 1
            by_sport[c["sport"]]["flags"] += sum(1 for m in c.get("markets") or [] if m.get("edge"))
    for c in rail.get("chipless") or []:
        by_sport.setdefault(c["sport"], {"cards": 0, "live": 0, "flags": 0, "chipless": 0})["chipless"] += 1
    # ---- flags: page verdict vs independent re-derivation
    # The page's own boardBuildEpochMs: state_meta.read_at - newest_age_seconds, else state_last_updated.
    meta = (q.get("response") or {}).get("state_meta") or {}
    board_built = None
    if meta.get("newest_age_seconds") is not None and parse_ts(meta.get("read_at")):
        board_built = parse_ts(meta.get("read_at")) - dt.timedelta(seconds=float(meta["newest_age_seconds"]))
    board_built = board_built or parse_ts(q.get("state_last_updated"))
    reading["query"]["board_built_at"] = iso(board_built) if board_built else None
    reading["query"]["board_built_age_s"] = round((now - board_built).total_seconds(), 1) if board_built else None
    flags, false_flags, missed, dark_rows, dark_markets = [], [], [], [], set()
    priced_ages, ages_now, seen_ages, no_fair, markets_total, markets_no_ours = [], [], [], [], 0, 0
    for c in live:
        for m in c.get("markets") or []:
            markets_total += 1
            if m.get("ours") in (None, ""):
                markets_no_ours += 1
            if m.get("edge"):
                e = m["edge"]
                flags.append({"read_at": iso(now), "sport": c["sport"], "matchup": c["matchup"],
                              "chip": (c.get("chip") or {}).get("game_key"), "market": m["key"], "segment": m["segment"],
                              "side": e.get("side"), "gap_pp": round(e.get("edge"), 2), "model": e.get("model"),
                              "fair": e.get("fair"), "ours": e.get("ours"), "priced_age_s": e.get("priced"),
                              "age_now_s": round(e.get("ageNow"), 1) if e.get("ageNow") is not None else None})
        for r in c.get("rows") or []:
            gap = independent_gap(r)
            age_now = independent_age_now(r, now, board_built)
            priced = r.get("book_age_seconds")
            priced_ages.append(priced)
            seen_ages.append(r.get("seen_age_seconds"))
            ages_now.append(age_now)
            if r.get("fair") is None:
                no_fair.append({"matchup": c["matchup"], "market": r["market"], "segment": r["segment"], "line": r["line"]})
            qualifies = (gap is not None and gap >= MIN_PP and priced is not None and float(priced) <= FRESH_S
                         and age_now is not None and age_now <= STALE_S)
            shown = r.get("fresh") is not None
            tag = {"matchup": c["matchup"], "market": r["market"], "segment": r["segment"], "side": r["side"],
                   "line": r["line"], "gap": None if gap is None else round(gap, 2), "priced": priced,
                   "age_now": None if age_now is None else round(age_now, 1)}
            if shown and not qualifies:
                false_flags.append(tag)
            if qualifies and not shown:
                missed.append(tag)
            if (gap is not None and gap >= MIN_PP and priced is not None and float(priced) <= FRESH_S
                    and age_now is not None and age_now > STALE_S):
                dark_rows.append(tag)
                dark_markets.add((c["matchup"], r["market"], r["segment"]))
    reading["live"] = {
        "cards_on_rail": len(cards), "live_cards": len(live), "by_sport": by_sport,
        "live_cards_with_flag": sum(1 for c in live if c.get("hasFreshEdge")),
        "flags": len(flags), "false_flags": false_flags, "missed_flags": missed,
        "dark_rows": len(dark_rows), "dark_markets": len(dark_markets), "dark_sample": dark_rows[:6],
        "live_markets": markets_total, "live_markets_no_ours": markets_no_ours,
        "live_rows": sum(len(c.get("rows") or []) for c in live), "live_rows_no_fair": len(no_fair),
        "no_fair_sample": no_fair[:6],
        "priced_age": dist(priced_ages), "age_now": dist(ages_now),
        # Our own lag: when WE last looked at the quote, at pricing (the book's unchanged clock is priced_age).
        "seen_age_at_pricing": dist(seen_ages),
        "priced_le_120": sum(1 for a in priced_ages if a is not None and float(a) <= FRESH_S),
        "age_now_gt_300": sum(1 for a in ages_now if a is not None and a > STALE_S),
        "flag_list": flags,
    }
    if flags:
        with open(out_dir / "flags.jsonl", "a", encoding="utf-8") as fh:
            for f in flags:
                fh.write(json.dumps(f) + "\n")
    # ---- teams
    chips = json.loads((rdir / "chips.json").read_bytes()).get("chips") or []
    today_chips = [ch for ch in chips if (parse_ts(ch.get("start_time_utc")) or now).astimezone(CT).date().isoformat() == rail_date]
    live_chips = [ch for ch in today_chips if ch.get("state") == "live"]
    live_card_chips = {(c.get("chip") or {}).get("game_key") for c in live}
    truncated = [{"sport": ch.get("sport"), "matchup": ch.get("matchup"), "abbr": (ch.get(s) or {}).get("abbr"), "name": (ch.get(s) or {}).get("name")}
                 for ch in today_chips for s in ("away", "home") if looks_truncated((ch.get(s) or {}).get("abbr"))]
    reading["teams"] = {
        "chips_today": len(today_chips), "live_chips": len(live_chips),
        # Game clock per live chip (HALF / intermission / Q3 7:24), to join 0-card overlay builds to game state.
        "live_chip_status": {f"{ch.get('sport')} {ch.get('matchup')}": ch.get("status_token") for ch in live_chips},
        "live_chips_without_live_card": [f"{ch.get('sport')} {ch.get('matchup')}" for ch in live_chips if ch.get("game_key") not in live_card_chips],
        "chipless": rail.get("chipless"), "det1": rail.get("det1"), "det2": rail.get("det2"), "det3": rail.get("det3"),
        "flipped": rail.get("flipped"), "truncated_abbr": truncated,
    }
    reading["logs"] = fleet_logs(args.log_minutes, now, out_dir)
    reading["finished_at"] = iso(utcnow())
    (rdir / "reading.json").write_text(json.dumps(reading, indent=1, default=str), encoding="utf-8")
    with open(out_dir / "readings.jsonl", "a", encoding="utf-8") as fh:
        slim = {k: v for k, v in reading.items() if k != "live"}
        slim["live"] = {k: v for k, v in reading["live"].items() if k not in ("flag_list",)}
        fh.write(json.dumps(slim, default=str) + "\n")
    print(json.dumps(summary(reading), indent=1, default=str))
    return 0


def summary(r):
    lv, tm, lg = r["live"], r["teams"], r["logs"]
    load = {x["path"].split("?")[0]: f'{x["seconds"]}s/{x["wire_bytes"]/1e6:.2f}MBwire/{x["bytes"]/1e6:.2f}MB' for x in r["load"]}
    return {
        "read_at_ct": r["read_at_ct"], "rail_date": r["rail_date"], "load": load,
        "live_rail": [(x["rows"], x["newest_age_s"]) for x in r["live_rail"]],
        "board": {"shortlist_written_age_s": r["shortlist"]["written_age_s"], "build_age_s": r["shortlist"]["build_age_seconds"],
                  "rows_live_state_stale": r["shortlist"]["rows_live_state_stale"], "query_snapshot_age_s": r["query"]["snapshot_age_s"], "board_built_age_s": r["query"].get("board_built_age_s")},
        "rail": {"cards": lv["cards_on_rail"], "live_cards": lv["live_cards"], "by_sport": lv["by_sport"]},
        "flags": {"shown": lv["flags"], "cards_flagged": lv["live_cards_with_flag"], "false": len(lv["false_flags"]),
                  "missed": len(lv["missed_flags"]), "dark_rows": lv["dark_rows"], "dark_markets": lv["dark_markets"]},
        "live_rows": {"n": lv["live_rows"], "no_fair": lv["live_rows_no_fair"], "priced_age": lv["priced_age"],
                      "age_now": lv["age_now"], "seen_age_at_pricing": lv.get("seen_age_at_pricing"), "priced_le_120": lv["priced_le_120"], "age_now_gt_300": lv["age_now_gt_300"],
                      "markets": lv["live_markets"], "markets_no_ours": lv["live_markets_no_ours"]},
        "teams": {"chips_today": tm["chips_today"], "live_chips": tm["live_chips"], "live_chip_status": tm.get("live_chip_status"),
                  "live_chips_without_live_card": tm["live_chips_without_live_card"],
                  "chipless": [(c["sport"], c["matchup"], c["count"]) for c in tm["chipless"] or []],
                  "det1": len(tm["det1"] or []), "det2": len(tm["det2"] or []), "det3": len(tm["det3"] or []),
                  "flipped": len(tm["flipped"] or []), "truncated_abbr": tm["truncated_abbr"][:6]},
        "logs": {"overlay": lg["overlay"], "ticks": lg["ticks"], "tick_gap": lg["tick_gap"], "build_seconds": lg["build_seconds"],
                 "deferred_slow": lg["deferred_slow"], "web_merge": lg["web_merge"], "log_error": lg["log_error"]},
    }


if __name__ == "__main__":
    sys.exit(main())
