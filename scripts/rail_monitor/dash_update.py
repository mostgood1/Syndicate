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


def classify_ours(rdir, rail, chips, split_resim=True):
    """I-17: college full-game total flags on live rail cards, and the card's OURS against the side the model favours.

    A flag (p > 0.5) whose OURS sits across the line from the flagged side has three outcomes:
    - skew_consistent (11-22 R27, Rice @ Lamar u167.5 p=0.69, ours 167.7): OURS is the flagged row's OWN live_total, so
      p and the mean come from one distribution and a skewed end game puts them on opposite sides of the line.
    - resim_tick (11-25 R20, the fleet-watcher's flag, Liberty @ Princeton o134.5 p=0.59, ours 134.3): OURS is the
      chip's live re-sim final total (an uncalibrated total's OURS is the card's PROJ box, intelligence.html
      liveRailSummary), the flagged row's own live_total is on the flagged side, and the two differ. They are two TICKS of
      one re-sim, not two models: on that game the row equalled the chip at R17 (144.495 / 144.5) and R19 (145.98 /
      146.0). At R20 the grid built at 22:22:25Z had joined the previous re-sim (137.74, so p 0.59), and the chip carried
      the re-sim stamped 22:22:28Z (134.3). A display mismatch on the card (LEAD 2, 11-20 R32), not a model fault.
    - contradiction: anything else, e.g. 11-18's real defect (OURS taken from ANOTHER row, 152-249 s older). Counted in
      ours_contradictions, as before. split_resim=False reproduces the pre-11-25 rule (tests only).
    """
    pts = {}
    resim_final = {}
    for c in chips.get("chips") or []:
        try:
            pts[str(c.get("game_key"))] = float(c["away"]["score"]) + float(c["home"]["score"])
        except Exception:
            pass
        iv = c.get("intervals") or {}
        try:
            if iv.get("source") == "live_resim" and (iv.get("final") or {}).get("total") is not None:
                resim_final[str(c.get("game_key"))] = (float(iv["final"]["total"]), str(iv.get("as_of") or ""))
        except (TypeError, ValueError):
            pass
    i17 = below = college_flags = 0
    i17_list = []
    own_total = {}
    _lr = os.path.join(rdir, "liverail_0.json")
    if os.path.exists(_lr):
        for r in (json.load(open(_lr, encoding="utf-8")).get("rows") or []):
            if (r.get("market") == "totals" and str(r.get("segment") or "full") == "full" and not r.get("player_name")
                    and r.get("live_total") is not None and r.get("line") is not None):
                try:
                    own_total[(r.get("sport"), r.get("matchup"), str(r.get("side"))[:1], float(r["line"]))] = (
                        float(r["live_total"]), str(r.get("price_grid_generated_at") or ""))
                except (TypeError, ValueError):
                    pass
    skew_consistent = 0
    skew_list = []
    resim_tick = 0
    resim_list = []
    for card in rail.get("cards") or []:
        if card.get("sport") not in COLLEGE or not card.get("live"):
            continue
        gk = str((card.get("chip") or {}).get("game_key"))
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
                o_u, line = mline.group(1), float(mline.group(2))
                across = (o_u == "o" and ours < line) or (o_u == "u" and ours > line)
                own_t = own_total.get((card.get("sport"), card.get("matchup"), o_u, line))
                own, grid_at = own_t if own_t else (None, "")
                rs = resim_final.get(gk)
                if across and own is not None and abs(own - ours) <= 0.051:
                    skew_consistent += 1
                    if len(skew_list) < 5:
                        skew_list.append(f"{card.get('sport')} {card.get('matchup')} {side} p={e.get('model')} ours {ours} "
                                         f"own {own}")
                elif (across and split_resim and own is not None and rs is not None and abs(rs[0] - ours) <= 0.051
                        and ((o_u == "o" and own > line) or (o_u == "u" and own < line))):
                    resim_tick += 1
                    if len(resim_list) < 5:
                        resim_list.append(f"{card.get('sport')} {card.get('matchup')} {side} p={e.get('model')} ours {ours} "
                                          f"(chip re-sim {rs[1][11:19]}Z) own {own} (grid {grid_at[11:19]}Z)")
                elif across:
                    i17 += 1
                    # Name it (11-20 8:50 PM: the fleet-watcher could not tell which game). A late tie, where an
                    # extra-period branch pulls the mean above an under the model favours, still lands here.
                    if len(i17_list) < 5:
                        i17_list.append(f"{card.get('sport')} {card.get('matchup')} {side} p={e.get('model')} ours {ours}")
            if ours is not None and gk in pts and ours < pts[gk]:
                below += 1
    return {"pts": pts, "i17": i17, "i17_list": i17_list, "skew_consistent": skew_consistent, "skew_list": skew_list,
            "resim_tick": resim_tick, "resim_list": resim_list, "below": below, "college_flags": college_flags}


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
    c17 = classify_ours(rdir, rail, chips)
    pts = c17["pts"]
    i17, i17_list, below, college_flags = c17["i17"], c17["i17_list"], c17["below"], c17["college_flags"]
    skew_consistent, skew_list = c17["skew_consistent"], c17["skew_list"]
    resim_tick, resim_list = c17["resim_tick"], c17["resim_list"]

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

    def counts_as_priced(sport, market):  # the same rule as p29_orient.counts_as_priced
        s, m = str(sport or "").lower(), str(market or "").strip().lower()
        if s == "nfl":
            return m in ("h2h", "moneyline")
        if s == "nhl" and "total" in m:
            return False
        return m in _PRICED
    by_game = {}
    if os.path.exists(lr_path):
        for r in (json.load(open(lr_path, encoding="utf-8")).get("rows") or []):
            if r.get("player_name") or str(r.get("segment") or "full") != "full":
                continue
            # 11-21 R27: NHL live TOTALS are refused at the join by design (no total distribution published;
            # findings_2026-11-13_nhl_live_total_calibration.md), 0 of 16-21 rows modelled every reading. Counting them
            # put Pittsburgh @ Nashville (3 totals) and Vegas @ Winnipeg (2) on this list while their h2h / puck-line
            # rows carried models. NHL counts its puck lines only.
            # 11-22 R9: NFL live totals AND spreads are withheld by design (nfl/live_resim.py:714: no totalRunsDist /
            # marginDist, nfl-live-distribution-grade graded live margins a FAIL; 0 modelled on every saved NFL reading
            # since 11-15). Counting them put all 6 re-simmed games here as resimmed_no_row_model while their
            # full-game moneylines carried the model (5 of 5 rows at R9). NFL counts its full-game moneyline only.
            if not counts_as_priced(r.get("sport"), r.get("market")):
                continue
            g = by_game.setdefault(f"{r.get('sport')} {r.get('matchup')}", [0, 0, 0])
            g[0] += 1
            if r.get("live_model_probability") is not None:
                g[1] += 1
            # 11-24 R19/R20 (the fleet-watcher's flag, Winthrop @ James Madison): `live_total` is set on a totals row
            # once the game's live lane joined, priced or not. Joined with no probability = the join's per-line gates
            # (quote-age ceiling, quote-older-than-state), not a name / orientation miss. Unjoined = no live_total.
            if r.get("live_total") is not None:
                g[2] += 1
    games_no_model = sorted(k for k, (n, m, _lt) in by_game.items() if n and not m)

    # 11-21 (the fleet-watcher's ask): WHY each no-model game has none, from p29_orient.py's per-game lines (the
    # sport's re-sim snapshot). Values: the snapshot's own refusal reason (key_player_out, game_final, no_margin_anchor,
    # in_intermission, ...); "orientation_reversed" (I-29: the snapshot has the teams the other way round);
    # "resimmed_no_row_model" (re-simmed, yet the priced rows carry no model and no live_total, and the helper's own
    # later read had none modelled either: a join defect, flag it); 11-24: "resimmed_model_by_helper_read" (the helper's
    # read had the model: timing between the two reads) and "resimmed_lane_joined_rows_withheld" (live_total on the
    # rows, no probability: the per-line gates);
    # "not_in_resim" (no snapshot entry matched, possibly this helper's name miss: check); 11-27: "snapshot_stale" (no
    # entry matched AND the sport's snapshot is over 900 s old: its writer stalled, not a name miss -- the soccer lens's
    # memory gate 20:02-21:47Z 11-27); "sport_absent_from_helper_read"
    # (the helper's own live-rail GET, made a few minutes after the probe's, held no game of this sport; NOT a missing
    # snapshot. Renamed 11-21 from "no_snapshot_for_sport", which read as an NHL snapshot miss at R26; the helper's
    # `{"rail": ...}` line says what its read held); "unknown" (the helper's output was missing this tick).
    reasons, details = {}, {}
    orient = {}
    stale_snapshots = {}
    if args.orient and os.path.exists(args.orient):
        for line in open(args.orient, encoding="utf-8", errors="replace"):
            if line.startswith("{"):
                try:
                    o = json.loads(line)
                except ValueError:
                    continue
                if o.get("matchup"):
                    orient[f"{o.get('sport')} {o.get('matchup')}"] = o
                elif o.get("sport") and isinstance(o.get("resim_age_s"), (int, float)) and o["resim_age_s"] > 900:
                    # 11-27: a sport with live rail games whose snapshot is stale. Its games still IN the snapshot
                    # carry a model that stopped moving (soccer has no lane-age ceiling in the live join), so this
                    # is reported even when no game is on the no-model list.
                    stale_snapshots[o["sport"]] = {"age_s": o["resim_age_s"], "generated": o.get("resim_generated"),
                                                  "games_in_snapshot": o.get("resim_games")}
    covered = {o.get("sport") for o in orient.values()}
    for k in games_no_model:
        o = orient.get(k)
        if o is None:
            reasons[k] = "unknown" if not orient else ("not_in_resim" if k.split(" ", 1)[0] in covered else "sport_absent_from_helper_read")
        elif o.get("resim") == "REVERSED":
            reasons[k] = "orientation_reversed"
        elif o.get("resim") in ("not_in_resim", "no_snapshot", "snapshot_stale"):
            reasons[k] = o["resim"]
        elif o.get("reason") == "resimmed":
            # 1-2 priced rows: the join's per-line withholds (stale quote, no distribution for that line, stoppage
            # time) explain it -- 11-21: Wake Forest @ GT, Lyon @ Lille, Philadelphia @ NE at 90'+6'. 3+: a join defect.
            n_priced, _m, n_lt = by_game.get(k, [0, 0, 0])
            if o.get("priced_with_model"):
                # 11-24 R19/R20: the helper's own live-rail GET (a minute after the probe's) already had the model on
                # these rows -- Winthrop @ JMU 1 of 3 and 4 of 7, Providence @ Arizona 5 of 5. Two reads, two moments.
                reasons[k] = "resimmed_model_by_helper_read"
                details[k] = (f"probe read: {n_priced} priced full-game rows, none with a model; the helper's later read: "
                              f"{o.get('priced_with_model')} of {o.get('priced')} modelled")
            elif n_lt:
                reasons[k] = "resimmed_lane_joined_rows_withheld"
                details[k] = (f"{n_priced} priced full-game rows, the lane joined (live_total on {n_lt}), none priced: "
                              f"the join's per-line gates (quote age / order)")
            else:
                reasons[k] = "resimmed_few_priced_rows" if n_priced <= 2 else "resimmed_no_row_model"
                details[k] = f"{n_priced} priced full-game rows, none with a model"
        else:
            reasons[k] = o.get("reason") or "unknown"
        if o and o.get("detail") and k not in details:
            details[k] = o["detail"]

    # 11-21 (the fleet-watcher's ask): WHY each dark row is dark. The probe calls a row dark when it would flag (gap
    # >= 3 pp, quote <= 120 s old at pricing) but its age now -- quote age at pricing + the price grid's age -- is over
    # 300 s, so the flag is (rightly) withheld. Split that age: grid_age_s >= 300 is "grid_stale" (the overlay has not
    # re-priced the row for 5+ min: a cadence fault worth a look); under 300 it is "cadence_edge" (a quote that was
    # already 1-2 min old when priced, plus a normal overlay interval, crossed the line). The probe keeps a sample of 6.
    # Measured 11-21 R14/R15: every dark row had NO price_grid_generated_at, so the probe aged it from the board build
    # (grid_age_s == query.board_built_age_s). Those rows -- h2h, quarter-ball soccer lines, some alt / half lines --
    # are not re-priced by the ~26 s book grid, so their freshness rides on the board cycle: "board_cadence".
    sport_of = {str(c.get("matchup")): c.get("sport") for c in rail.get("cards") or []}
    dark_detail = []
    rpath = os.path.join(rdir, "reading.json")
    board_age = None
    if os.path.exists(rpath):
        try:
            _rd = json.load(open(rpath, encoding="utf-8"))
            sample = (_rd.get("live") or {}).get("dark_sample") or []
            board_age = (_rd.get("query") or {}).get("board_built_age_s")
        except ValueError:
            sample = []
        for t in sample:
            pr, an = t.get("priced"), t.get("age_now")
            grid = round(float(an) - float(pr), 1) if isinstance(pr, (int, float)) and isinstance(an, (int, float)) else None
            dark_detail.append({
                "game": f"{sport_of.get(str(t.get('matchup')), '?')} {t.get('matchup')}",
                "row": f"{t.get('market')} {t.get('segment')} {t.get('side')} {t.get('line')}",
                "gap_pp": t.get("gap"), "quote_age_at_pricing_s": None if pr is None else round(float(pr), 1),
                "grid_age_s": grid, "age_now_s": an,
                "reason": "unknown" if grid is None else (
                    "board_cadence" if isinstance(board_age, (int, float)) and abs(grid - float(board_age)) <= 1.0
                    else ("grid_stale" if grid >= 300 else "cadence_edge"))})

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
        "dark_rows_detail": dark_detail,
        "college_total_flags": college_flags,
        "ours_contradictions": i17,
        "ours_contradictions_list": i17_list,
        "ours_skew_consistent": skew_consistent,
        "ours_skew_consistent_list": skew_list,
        "ours_resim_tick": resim_tick,
        "ours_resim_tick_list": resim_list,
        "ours_below_points": below,
        "floor_calibrated_rows": floor_rows,
        "floor_violations": floor_viol,
        "floor_examples": floor_examples,
        "pregame_college_total_flags": p6,
        "live_games_with_rows": len(by_game),
        "live_games_no_model": len(games_no_model),
        "live_games_no_model_list": games_no_model[:5],
        "live_games_no_model_reasons": reasons,
        "live_games_no_model_detail": details,
        "stale_snapshots": stale_snapshots,
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


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("row")
    a.add_argument("--n", type=int, required=True)
    a.add_argument("--probe", required=True)
    a.add_argument("--metrics", required=True)
    a.add_argument("--dir")
    a.add_argument("--note")
    a.add_argument("--orient", help="p29_orient.py output for this tick (per-game re-sim state and refusal reason)")
    a.add_argument("--day", help="slate date YYYY-MM-DD; selects rows_<day>.jsonl")
    b = sub.add_parser("build")
    b.add_argument("--day", help="slate date YYYY-MM-DD; selects rows_<day>.jsonl")
    args = ap.parse_args()
    (row if args.cmd == "row" else build)(args)
