"""Rail Watch dashboard rows: one per monitor reading.

  py -3 dash_update.py row --n 3 --probe d4r3_probe.txt --metrics d4r3_metrics.json [--note "..."]
  py -3 dash_update.py build      -> writes readings.json from rows.jsonl (newest last)

Reads only local files the probe and the metrics script wrote. Counts and timings only.
"""
import argparse, datetime as dt, json, os, re, sys
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
ROWS_ALL = os.path.join(HERE, "rows.jsonl")  # 11-18 (day 4) rows; from 11-19 one file per day


def rows_path(day):
    return ROWS_ALL if day in (None, "2026-11-18") else os.path.join(HERE, f"rows_{day}.jsonl")
CT = ZoneInfo("America/Chicago")
COLLEGE = ("ncaab", "wncaab")


def load_s(s):
    m = re.match(r"([0-9.]+)s", s or "")
    return float(m.group(1)) if m else None


def newest_dir(probe):
    base = os.path.join(os.path.dirname(HERE), "readings")
    stamp = dt.datetime.fromisoformat(probe["read_at_ct"].replace(" CT", "").replace(" PM", "PM").replace(" AM", "AM"))
    return base, stamp


def row(args):
    p = json.load(open(args.probe, encoding="utf-8"))
    m = json.load(open(args.metrics, encoding="utf-8"))
    rdir = args.dir
    if not rdir:
        base = os.path.join(os.path.dirname(HERE), "readings")
        rdir = os.path.join(base, sorted(d for d in os.listdir(base) if d.startswith("20"))[-1])
    at = dt.datetime.strptime(os.path.basename(rdir), "%Y%m%dT%H%M%SZ").replace(tzinfo=dt.timezone.utc)
    ct = at.astimezone(CT)
    load = p.get("load") or {}
    flags = p.get("flags") or {}
    lr = p.get("live_rows") or {}
    teams = p.get("teams") or {}
    board = p.get("board") or {}

    # I-17 contradictions and #824 from the rail cards + chips
    rail = json.load(open(os.path.join(rdir, "rail.json"), encoding="utf-8"))
    chips = json.load(open(os.path.join(rdir, "chips.json"), encoding="utf-8"))
    pts = {}
    for c in chips.get("chips") or []:
        try:
            pts[str(c.get("game_key"))] = float(c["away"]["score"]) + float(c["home"]["score"])
        except Exception:
            pass
    i17 = below = college_flags = 0
    i17_list = []
    for card in rail.get("cards") or []:
        if card.get("sport") not in COLLEGE or not card.get("live"):
            continue
        for mk in card.get("markets") or []:
            e = mk.get("edge")
            if mk.get("key") != "totals" or mk.get("segment") != "full" or not isinstance(e, dict):
                continue
            college_flags += 1
            side = str(e.get("side") or "")
            mline = re.match(r"([ou])([0-9.]+)", side)
            try:
                ours = float(str(e.get("ours") or mk.get("ours")))
            except ValueError:
                ours = None
            if mline and ours is not None and (e.get("model") or 0) > 0.5:
                line = float(mline.group(2))
                if (mline.group(1) == "o" and ours < line) or (mline.group(1) == "u" and ours > line):
                    i17 += 1
                    # Name it (11-20 8:50 PM: the fleet-watcher could not tell which game). Two known non-defects
                    # trip this: the chip's re-sim lagging the flagged row by one build (OURS is the chip's final),
                    # and a late tie, where an extra-period branch pulls the mean above an under the model favours.
                    if len(i17_list) < 5:
                        i17_list.append(f"{card.get('sport')} {card.get('matchup')} {side} p={e.get('model')} ours {ours}")
            gk = str((card.get("chip") or {}).get("game_key"))
            if ours is not None and gk in pts and ours < pts[gk]:
                below += 1

    # I-17 score floor (d78a448c4, handed over 11-19): calibrated college full-game total rows on the live rail
    # whose live_total is below the points already scored on the chip. Expected 0 once the parent has it.
    card_chip = {}
    for card in rail.get("cards") or []:
        k = str(card.get("key") or "")
        if "|" in k:
            card_chip[k.split("|", 1)[1]] = str((card.get("chip") or {}).get("game_key"))
    floor_rows = floor_viol = 0
    floor_examples = []
    lr_path = os.path.join(rdir, "liverail_0.json")
    if os.path.exists(lr_path):
        for r in (json.load(open(lr_path, encoding="utf-8")).get("rows") or []):
            if r.get("sport") not in COLLEGE or r.get("player_name") or str(r.get("segment") or "full") != "full":
                continue
            if not str(r.get("market") or "").startswith("totals") or r.get("live_total_basis") != "calibrated":
                continue
            gk = card_chip.get(str(r.get("event_id")))
            try:
                lt = float(r.get("live_total"))
            except (TypeError, ValueError):
                continue
            floor_rows += 1
            if gk in pts and lt < pts[gk]:
                floor_viol += 1
                if len(floor_examples) < 3:
                    floor_examples.append(f"{r.get('matchup')} {r.get('side')} {r.get('line')}: total {lt} < {pts[gk]:.0f} scored, age {r.get('book_age_seconds')}")

    # I-29 (11-19): live games whose full-game (non-player) rail rows carry NO live model at all. The probe's dark/missed
    # counts need a model on the row, so a game that loses its model join is invisible to them.
    # Only the markets the live join prices (live_gameline_join._DIST_MARKETS: totals/spreads and their alts). 11-20
    # 3:50 PM: soccer games flickered onto this list whenever only their corners / BTTS / h2h rows made the rail's
    # ~100-row cut -- markets that never carry a live model (0 of 97 soccer rows that day), so "no model" there was the
    # row mix, not a refusal. h2h is out for every sport: layer2_board leaves some h2h rows blank by design.
    _PRICED = {"totals", "total", "totals_alt", "alternate_totals", "spreads", "run_line", "ats", "spreads_alt",
               "alternate_spreads"}
    by_game = {}
    if os.path.exists(lr_path):
        for r in (json.load(open(lr_path, encoding="utf-8")).get("rows") or []):
            if r.get("player_name") or str(r.get("segment") or "full") != "full":
                continue
            if str(r.get("market") or "").strip().lower() not in _PRICED:
                continue
            g = by_game.setdefault(f"{r.get('sport')} {r.get('matchup')}", [0, 0])
            g[0] += 1
            if r.get("live_model_probability") is not None:
                g[1] += 1
    games_no_model = sorted(k for k, (n, m) in by_game.items() if n and not m)

    # BC-048: pregame college totals flags on the shortlist (model edge > 0 on a non-live row)
    sl = json.load(open(os.path.join(rdir, "shortlist.json"), encoding="utf-8"))
    p6 = 0
    for r in sl.get("rows") or []:
        if r.get("sport") in COLLEGE and str(r.get("market", "")).startswith("total") and not r.get("is_live"):
            e = r.get("model_edge_pct")
            if isinstance(e, (int, float)) and e > 0:
                p6 += 1

    out = {
        "n": args.n,
        "at": at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "label": f"R{args.n} · {ct.strftime('%-I:%M %p') if os.name != 'nt' else ct.strftime('%#I:%M %p')}",
        "chips_today": teams.get("chips_today"),
        "live_games": teams.get("live_chips"),
        "flags_shown": flags.get("shown"),
        "flags_false": flags.get("false"),
        "flags_missed": flags.get("missed"),
        "dark_rows": flags.get("dark_rows"),
        "college_total_flags": college_flags,
        "ours_contradictions": i17,
        "ours_contradictions_list": i17_list,
        "ours_below_points": below,
        "floor_calibrated_rows": floor_rows,
        "floor_violations": floor_viol,
        "floor_examples": floor_examples,
        "pregame_college_total_flags": p6,
        "live_games_with_rows": len(by_game),
        "live_games_no_model": len(games_no_model),
        "live_games_no_model_list": games_no_model[:5],
        "live_rows": lr.get("n"),
        "priced_le_120": lr.get("priced_le_120"),
        "priced_age_p50_s": (lr.get("priced_age") or {}).get("p50"),
        "overlay_gap_max_s": m.get("overlay_gap_max_s"),
        "overlay_gaps_over_360": m.get("overlay_gaps_over_360"),
        "web_merges": m.get("web_merges"),
        "web_merges_stale": m.get("web_merges_stale"),
        "tick_gap_max_s": m.get("tick_gap_max_s"),
        "board_builds": m.get("board_builds"),
        "board_wall_median_s": m.get("board_wall_median_s"),
        "board_wall_max_s": m.get("board_wall_max_s"),
        "board_over_300": m.get("board_over_300"),
        "shortlist_span_max_s": m.get("shortlist_span_max_s"),
        "board_pub_gap_max_s": m.get("board_pub_gap_max_s"),
        "board_pub_gap_median_s": m.get("board_pub_gap_median_s"),
        "today_cadence_step_max_s": m.get("today_cadence_step_max_s"),
        "sweeps_launched": m.get("sweeps_launched"),
        "sweeps_refused": m.get("sweeps_refused"),
        "sweeps_refused_pct": m.get("sweeps_refused_pct"),
        "live_run_max_s": m.get("live_run_max_s"),
        "nhl_child_max_age_s": m.get("nhl_child_max_age_s"),
        "lookahead_max_s": m.get("lookahead_max_s"),
        "lookahead_soccer_max_s": m.get("lookahead_soccer_max_s"),
        "query_s": load_s(load.get("/api/intelligence/query")),
        "shortlist_s": load_s(load.get("/api/board/layer2-shortlist")),
        "chips_s": load_s(load.get("/api/board/game-chips")),
        "page_s": load_s(load.get("/intelligence")),
        "today_board_age_s": board.get("query_today_age_s"),
        "team_defects": sum(int(teams.get(k) or 0) for k in ("flipped", "det1", "det2", "det3")) + len(teams.get("chipless") or []),
        "host_load": m.get("host_load1"),
        "fleet_head": m.get("fleet_head"),
        "note": args.note or "",
    }
    with open(rows_path(args.day), "a", encoding="utf-8") as f:
        f.write(json.dumps(out) + "\n")
    print(json.dumps(out, indent=1))


def build(_args):
    rows = [json.loads(l) for l in open(rows_path(_args.day), encoding="utf-8") if l.strip()]
    rows.sort(key=lambda r: r["at"])
    seen, uniq = set(), []
    for r in rows:
        if r["n"] in seen:
            uniq = [u for u in uniq if u["n"] != r["n"]]
        seen.add(r["n"])
        uniq.append(r)
    json.dump(uniq, open(os.path.join(HERE, "readings.json"), "w", encoding="utf-8"), indent=0)
    print("readings.json rows", len(uniq))


ap = argparse.ArgumentParser()
sub = ap.add_subparsers(dest="cmd", required=True)
a = sub.add_parser("row")
a.add_argument("--n", type=int, required=True)
a.add_argument("--probe", required=True)
a.add_argument("--metrics", required=True)
a.add_argument("--dir")
a.add_argument("--note")
a.add_argument("--day", help="slate date YYYY-MM-DD; selects rows_<day>.jsonl")
b = sub.add_parser("build")
b.add_argument("--day", help="slate date YYYY-MM-DD; selects rows_<day>.jsonl")
args = ap.parse_args()
(row if args.cmd == "row" else build)(args)
