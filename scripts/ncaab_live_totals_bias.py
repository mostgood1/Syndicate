"""NCAAB live re-sim: why the projected full-game total runs LOW against the final (lane ncaab-live-totals-bias, 2026-11-08).

READ-ONLY. Work dir = the CURRENT directory, holding:
  ledgers/<sport>/live_gameline_ledger_<date>.jsonl   fleet copies (<data>/<sport>_source/data/live_gameline_ledger/)
  pregame/<sport>/pregame_sim_<date>.json             fleet copies (<data>/<sport>_source/data/pregame_sim/)
  espn/<sport>/...                                     ESPN scoreboard + summary cache (shared with the quote-order script)

Two populations, both graded against ESPN finals (completed games only):
  P1 "priced totals rows": priceable full-game totals records -- the population the 2026-11-08 quote-order findings
     measured (model_total_mean - final -3.41 / -2.57 / -1.43 within / older / newer than 30 s). Line - final beside it.
  P2 "lane states": one row per DISTINCT re-sim state (game, live_state_as_of), from every full-game record that
     carries model_total_mean (priceable or not), so a game is not weighted by how often its line moved.

Each lane state is placed on the game clock by the ESPN play it was resumed from: the last play at or before
live_state_as_of whose score equals the record's score (the earliest such play if ESPN's wallclock runs ahead).
Error = model_total_mean - final = model remaining points - actual remaining points (both share the score so far).
It is split into
  live_update = model remaining - PRIOR remaining, where PRIOR remaining is the engine's own pregame targets spread
                over the time left: pregameTotal x H1_SHARE (0.4743) per first half, x 0.5257 per second half, pro rata
                by clock (`ncaab/live_resim.half_targets`); and
  prior_error = PRIOR remaining - actual remaining.
A live_update near 0 means the resume projects the remaining time at the prior's rate; a negative one means the
resumed engine takes points away from what its own prior expects for that time.

Engine epochs by live_state_as_of (deploys.md): E0 < 11-03 19:41:57Z (before the college prior calibration),
E1 to 22:47:05Z (calibrated, no efficiency bounds), E2 to 11-05 22:37:41Z (bounds; OVERTIME POINTS MISSING from the
full-game total, `b9999dc1d`), E3 after (overtime counted). After 2026-11-07 16:29:14Z the quote-order gate refuses
rows whose quote is > 30 s older than the state; refused rows leave the ledger, so later states are a SELECTED
subset (`censored` in every table).

Usage: cd <work dir>; py -3 -I <repo>/scripts/ncaab_live_totals_bias.py ncaab [2026-11-02,...] [--penalty=<json>]
  --penalty: the blowout rule's cost by margin from `ncaab_blowout_resume_probe.py` ({"half": {...}, "h1mid": {...}});
  adds COUNTERFACTUAL rows = each state's projection plus the points the rule took from it (men's only).
SEs are game-clustered (equal weight per record within a game). Findings:
.syndicate/findings_2026-11-08_ncaab_live_totals_bias.md
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import college_quote_order_by_score_change as qo  # noqa: E402  (ts, scoreboard, match, fetch_json, clustered)

HERE = Path.cwd()
H1_SHARE = 0.4743  # ncaab/live_resim.H1_SHARE (the half split production runs, SYNDICATE_NCAAB_HALF_SPLIT on)
# League geometry: (regulation periods, period seconds, each period's share of the prior total). The men's engine runs
# the half split (H1_SHARE); the women's runs NO men-fitted adjustment (`build_engine_inputs`), so an even split.
GEOMETRY = {"ncaab": (2, 1200, (H1_SHARE, 1.0 - H1_SHARE)), "wncaab": (4, 600, (0.25, 0.25, 0.25, 0.25))}
PERIODS, PERIOD_S, SHARES = GEOMETRY["ncaab"]
HALF_S = 1200
GATE_LOADED = qo.GATE_LOADED
EPOCHS = (
    ("E0_precal", datetime(2026, 11, 3, 19, 41, 57, tzinfo=timezone.utc)),
    ("E1_cal", datetime(2026, 11, 3, 22, 47, 5, tzinfo=timezone.utc)),
    ("E2_bounds_noOT", datetime(2026, 11, 5, 22, 37, 41, tzinfo=timezone.utc)),
    ("E3_OTcounted", datetime(2100, 1, 1, tzinfo=timezone.utc)),
)
BLOWOUT_Q4_MARGIN = 15  # basketball_engine.engine.EventSimConfig.blowout_q4_margin; NCAAB N_PERIODS=2 -> all of h2


def epoch(t: datetime) -> str:
    for name, end in EPOCHS:
        if t < end:
            return name
    return EPOCHS[-1][0]


def clock_seconds(v) -> float | None:
    s = str(v or "").strip()
    if not s:
        return None
    try:
        if ":" in s:
            m, sec = s.split(":", 1)
            return int(m) * 60 + float(sec)
        return float(s)
    except ValueError:
        return None


def timeline(sport: str, event_id: str):
    """plays [(wall, period, clock_s, home, away)], per-period finals, completed -- from the cached ESPN summary."""
    url = f"https://site.api.espn.com/apis/site/v2/sports/{qo.ESPN[sport]}/summary?event={event_id}"
    data = qo.fetch_json(url, HERE / "espn" / sport / f"summary_{event_id}.json")
    if not data:
        return None
    comp = ((data.get("header") or {}).get("competitions") or [{}])[0]
    if not ((comp.get("status") or {}).get("type") or {}).get("completed"):
        return None
    side = {c.get("homeAway"): c for c in comp.get("competitors") or []}
    try:
        fh, fa = int(side["home"]["score"]), int(side["away"]["score"])
        lh = [int(x.get("displayValue")) for x in side["home"].get("linescores") or []]
        la = [int(x.get("displayValue")) for x in side["away"].get("linescores") or []]
    except Exception:
        return None
    plays = []
    for p in data.get("plays") or []:
        try:
            h, a = int(p.get("homeScore")), int(p.get("awayScore"))
            per = int((p.get("period") or {}).get("number"))
        except Exception:
            continue
        cs = clock_seconds((p.get("clock") or {}).get("displayValue"))
        w = qo.ts(p.get("wallclock"))
        if cs is None or w is None:
            continue
        plays.append((w, per, cs, h, a))
    if not plays or len(lh) < PERIODS or len(la) < PERIODS:
        return None
    return {"final_home": fh, "final_away": fa, "lines_home": lh, "lines_away": la, "plays": plays,
            "neutral": bool(comp.get("neutralSite"))}


def place(plays, as_of: datetime, h: int, a: int):
    """The play the state was resumed from: (period, clock_s, lag_s), or None when no play has that score."""
    same = [p for p in plays if p[3] == h and p[4] == a]
    if not same:
        return None
    before = [p for p in same if p[0] <= as_of]
    p = before[-1] if before else same[0]
    return p[1], p[2], (as_of - p[0]).total_seconds()


def regulation_left(period: int, clock: float) -> float:
    if period > PERIODS:
        return 0.0
    return (PERIODS - period) * PERIOD_S + clock


def prior_remaining(prior_total: float, period: int, clock: float) -> float:
    """The engine's pregame targets over the time left (regulation only; overtime is never in a prior rate)."""
    if period > PERIODS:
        return 0.0
    rem = prior_total * SHARES[period - 1] * clock / PERIOD_S
    return rem + sum(prior_total * SHARES[p] for p in range(period, PERIODS))


def phase_bin(period: int, clock: float) -> str:
    """Minutes left IN THE PERIOD, by period; overtime apart."""
    if period > PERIODS:
        return "9 OT"
    m = clock / 60.0
    if PERIODS == 4:  # women's quarters
        return f"q{period} " + (">5m left" if m > 5 else "2-5m left" if m > 2 else "<=2m left")
    if period == 1:
        return ("0 h1 >18m left" if m > 18 else "1 h1 12-18m left" if m > 12 else
                "2 h1 6-12m left" if m > 6 else "3 h1 <=6m left")
    return ("4 h2 14-20m left" if m > 14 else "5 h2 8-14m left" if m > 8 else "6 h2 4-8m left" if m > 4 else
            "7 h2 2-4m left" if m > 2 else "8 h2 <=2m left")


def blowout_flag(period: int, margin: int) -> bool:
    """`engine.simulate_pbp_game_boxscore`: q >= N_PERIODS and |m| >= 15, or q >= second-half-first-period and |m| >= 18."""
    m = abs(int(margin))
    return (period >= PERIODS and m >= BLOWOUT_Q4_MARGIN) or (period >= PERIODS // 2 + 1 and m >= 18)


def margin_bin(m: int) -> str:
    m = abs(m)
    return "0-5" if m <= 5 else ("6-10" if m <= 10 else ("11-14" if m <= 14 else ("15-19" if m <= 19 else "20+")))


def load_pregame(sport: str) -> dict[str, dict]:
    out = {}
    for f in sorted((HERE / "pregame" / sport).glob("pregame_sim_*.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        for eid, g in (d.get("games") or {}).items():
            prov = g.get("provenance") or {}
            segs = ((g.get("dist") or {}).get("segments") or {})
            means = {}
            for s in ("h1", "h2", "full"):
                tot = (segs.get(s) or {}).get("total") or {}
                n = sum(tot.values())
                if n:
                    means[s] = sum(int(k) * v for k, v in tot.items()) / n
            out[str(eid)] = {"target": prov.get("pregameTotal"), "raw": prov.get("rawPregameTotal"),
                             "sim_total": g.get("total_mean"), "computed_at": g.get("computed_at"),
                             "seg_means": means, "fallback": prov.get("priorSeasonFallback"),
                             "home_margin": g.get("home_margin_mean"), "date": d.get("date")}
    return out


def _interp(table: dict, m: float) -> float:
    pts = sorted((float(k), float(v)) for k, v in table.items())
    if m <= pts[0][0]:
        return pts[0][1]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if m <= x1:
            return y0 + (y1 - y0) * (m - x0) / (x1 - x0)
    return pts[-1][1]


def blowout_penalty(table: dict, period: int, clock: float, margin: int) -> float:
    """Points the blowout rule takes from this state's projected remaining total, from the probe
    (`ncaab_blowout_resume_probe.py`: no_blowout - prod). `table` = {"half": {margin: pts}, "h1mid": {margin: pts}}:
    an h2 state with the flag on loses the halftime penalty pro rata to the h2 time left; an h1 state loses the
    mid-first-half penalty at its margin (its simulated h2 may be flagged). Men's geometry only."""
    m = abs(int(margin))
    if period == 2:
        if not blowout_flag(period, margin):
            return 0.0
        return _interp({k: v for k, v in table["half"].items() if float(k) >= 15}, max(m, 16)) * clock / HALF_S
    if period == 1:
        return _interp(table["h1mid"], m)
    return 0.0


def pregame_vs_finals(sport: str, pre: dict[str, dict]) -> None:
    """EVERY pregame entry (not only games with a live lane) against ESPN's final, from the scoreboard: the prior target
    (calibrated to the books' close, `prior_calibration` target "close"), the raw prior and the pregame sim total."""
    finals = {}
    for d in sorted({str(g.get("date")) for g in pre.values() if g.get("date")}):
        compact = d.replace("-", "")
        url = (f"https://site.api.espn.com/apis/site/v2/sports/{qo.ESPN[sport]}/scoreboard"
               f"?dates={compact}&groups=50&limit=500")
        data = qo.fetch_json(url, HERE / "espn" / sport / f"scoreboard_{compact}.json") or {}
        for ev in data.get("events") or []:
            comp = (ev.get("competitions") or [{}])[0]
            if not (((comp.get("status") or {}).get("type") or {}).get("completed")):
                continue
            try:
                finals[str(ev.get("id"))] = sum(int(c.get("score")) for c in comp.get("competitors") or [])
            except (TypeError, ValueError):
                continue
    acc = defaultdict(list)
    for eid, g in pre.items():
        fin = finals.get(str(eid))
        if fin is None or not isinstance(g.get("target"), (int, float)):
            continue
        acc["target - final"].append((eid, float(g["target"]) - fin))
        acc[f"target - final | {g.get('date')}"].append((eid, float(g["target"]) - fin))
        if isinstance(g.get("raw"), (int, float)):
            acc["raw prior - final"].append((eid, float(g["raw"]) - fin))
        if isinstance(g.get("sim_total"), (int, float)):
            acc["pregame sim total - final"].append((eid, float(g["sim_total"]) - fin))
    for k in sorted(acc):
        vals = [v for _, v in acc[k]]
        n = len(vals)
        if n < 2:
            continue
        mu = sum(vals) / n
        se = (sum((x - mu) ** 2 for x in vals) / (n - 1) / n) ** 0.5
        under = sum(1 for x in vals if x > 0)
        print(f"  P0-all {sport} {k:34s} games={n:4d}  mean={mu:+7.2f}  se={se:.2f}  final below it in {under}/{n}")


def main():
    global PERIODS, PERIOD_S, SHARES
    sport = sys.argv[1] if len(sys.argv) > 1 else "ncaab"
    PERIODS, PERIOD_S, SHARES = GEOMETRY[sport]
    dates = set(sys.argv[2].split(",")) if len(sys.argv) > 2 and sys.argv[2] and not sys.argv[2].startswith("--") else set()
    penalty = None
    for a in sys.argv[1:]:
        if a.startswith("--penalty="):
            penalty = json.loads(Path(a.split("=", 1)[1]).read_text(encoding="utf-8"))
    recs = []
    for f in sorted((HERE / "ledgers" / sport).glob("live_gameline_ledger_*.jsonl")):
        with f.open(encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if '"model_total_mean"' not in line:
                    continue
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                if str(r.get("segment") or "").lower() not in qo.FULL:
                    continue
                if not isinstance(r.get("model_total_mean"), (int, float)):
                    continue
                if dates and str(r.get("date")) not in dates:
                    continue
                recs.append(r)
    games = {d: qo.scoreboard(sport, d) for d in sorted({r["date"] for r in recs})}
    keyed, unmatched = defaultdict(list), set()
    for r in recs:
        eid = qo.match(games.get(r["date"], {}), r.get("home_team"), r.get("away_team"))
        if eid is None:
            unmatched.add((r["date"], r.get("home_team"), r.get("away_team")))
            continue
        keyed[eid].append(r)
    pre = load_pregame(sport)
    pregame_vs_finals(sport, pre)
    print(f"=== {sport}: {len(recs)} full-game records with model_total_mean, {len(keyed)} ESPN games matched, "
          f"{len(unmatched)} game keys unmatched; pregame entries {len(pre)}", flush=True)
    tl = {eid: timeline(sport, eid) for eid in sorted(keyed)}
    acc = defaultdict(list)
    skipped = defaultdict(int)
    dates_used, states_used = defaultdict(set), 0
    pregame_rows = {}
    placed: dict = {}
    per_game_lines = defaultdict(list)  # (censored, game) -> [(recorded_at, line - final, model - final)]
    for eid, rs in keyed.items():
        g = tl.get(eid)
        if not g:
            skipped["no_final_or_summary"] += len(rs)
            continue
        fin = g["final_home"] + g["final_away"]
        reg_final = sum(g["lines_home"][:PERIODS]) + sum(g["lines_away"][:PERIODS])
        ot_pts = fin - reg_final
        pg = pre.get(str(eid))
        if pg and isinstance(pg.get("target"), (int, float)):
            pregame_rows[eid] = (pg, g)
        seen = set()
        for r in rs:
            a = qo.ts(r.get("live_state_as_of"))
            try:
                h, w = int(r.get("home_score")), int(r.get("away_score"))
            except (TypeError, ValueError):
                skipped["no_score"] += 1
                continue
            if a is None:
                skipped["no_as_of"] += 1
                continue
            censored = "censored" if a >= GATE_LOADED else "pregate"
            err = float(r["model_total_mean"]) - fin
            pk = (r.get("live_state_as_of"), h, w)
            if pk not in placed:
                placed[pk] = place(g["plays"], a, h, w)
            pl = placed[pk]
            # P1: priced totals rows (the quote-order findings' population)
            if r.get("market") == "totals" and r.get("priceable") is True and isinstance(r.get("line"), (int, float)):
                q = qo.ts(r.get("quote_updated_at"))
                if q is not None:
                    d = (q - a).total_seconds()
                    b1 = "older30" if d < -30 else ("within30" if d <= 30 else "newer30")
                    line_err = float(r["line"]) - fin
                    gap = float(r["model_total_mean"]) - float(r["line"])
                    p1tags = [f"{censored}|{b1}", f"{censored}|all"]
                    if pl is not None:
                        per = pl[0]
                        if PERIODS // 2 < per <= PERIODS:
                            p1tags.append(f"{censored}|h2 " + ("blowout flag ON" if blowout_flag(per, h - w) else "blowout flag off"))
                        elif per <= PERIODS // 2:
                            p1tags.append(f"{censored}|h1 margin " + ("<15" if abs(h - w) < 15 else ">=15"))
                    pen = blowout_penalty(penalty, pl[0], pl[1], h - w) if (penalty and pl is not None and sport == "ncaab") else None
                    for t in p1tags:
                        acc[("P1 priced totals model-final", t)].append((eid, err))
                        acc[("P1 priced totals line-final", t)].append((eid, line_err))
                        acc[("P1 priced totals model-line", t)].append((eid, gap))
                        if pen is not None:  # the same rows, as they are and with the rule off
                            acc[("P1 SAME ROWS today model-final", t)].append((eid, err))
                            acc[("P1 SAME ROWS today model-line", t)].append((eid, gap))
                            acc[("P1 COUNTERFACTUAL rule off model-final", t)].append((eid, err + pen))
                            acc[("P1 COUNTERFACTUAL rule off model-line", t)].append((eid, gap + pen))
                    rec_at = str(r.get("recorded_at") or "")
                    per_game_lines[(censored, eid)].append((rec_at, line_err, err))
            key = (r.get("live_state_as_of"), round(float(r["model_total_mean"]), 2))
            if key in seen:
                continue
            seen.add(key)
            if pl is None:
                skipped["state_score_not_in_pbp"] += 1
                continue
            period, clock, lag = pl
            states_used += 1
            ep = epoch(a)
            dates_used[censored].add(r["date"])
            ph = phase_bin(period, clock)
            mb = margin_bin(h - w)
            tags = [f"{censored}|all", f"{censored}|{ep}", f"{censored}|phase {ph}", f"{censored}|{ep}|phase {ph}",
                    f"{censored}|margin {mb}", f"{censored}|date {r['date']}"]
            second_half = PERIODS // 2 < period <= PERIODS
            if second_half:
                bf = "blowout flag ON" if blowout_flag(period, h - w) else "blowout flag off"
                tags.append(f"{censored}|h2 margin {mb}")
                tags.append(f"{censored}|h2 {bf}")
                tags.append(f"{censored}|{ep}|h2 {bf}")
                tags.append(f"{censored}|h2 {bf}|phase {ph}")
                if period == PERIODS and clock <= 240:
                    tags.append(f"{censored}|h2 last4m margin {mb}")
                # the threshold itself: |margin| 11..19 in the last period with > 8 min to play (the flag's step at 15)
                if period == PERIODS and clock > 480 and 11 <= abs(h - w) <= 19:
                    tags.append(f"{censored}|threshold |m|={abs(h - w):02d}")
                    tags.append(f"{censored}|threshold " + ("|m| 11-14" if abs(h - w) < BLOWOUT_Q4_MARGIN else "|m| 15-19"))
            if period <= PERIODS // 2:
                tags.append(f"{censored}|h1 margin {mb}")
            if pg and isinstance(pg.get("target"), (int, float)) and period <= PERIODS:
                prior_rem = prior_remaining(float(pg["target"]), period, clock)
                model_rem = float(r["model_total_mean"]) - (h + w)
                actual_rem = fin - (h + w)
                elapsed = PERIODS * PERIOD_S - regulation_left(period, clock)
                for t in tags:
                    acc[("P2 live_update (model rem - prior rem)", t)].append((eid, model_rem - prior_rem))
                    acc[("P2 prior_error (prior rem - actual rem)", t)].append((eid, prior_rem - actual_rem))
                    acc[("P2 ot_points_in_actual", t)].append((eid, float(ot_pts)))
                if elapsed >= 300:
                    pace = ((h + w) / (elapsed / 60.0)) / (float(pg["target"]) / (PERIODS * PERIOD_S / 60.0))
                    pb = "pace<0.85" if pace < 0.85 else ("0.85-0.95" if pace < 0.95 else ("0.95-1.05" if pace < 1.05 else ("1.05-1.15" if pace < 1.15 else "pace>=1.15")))
                    tags.append(f"{censored}|pace {pb}")
                    acc[("P2 live_update (model rem - prior rem)", f"{censored}|pace {pb}")].append((eid, model_rem - prior_rem))
                    acc[("P2 prior_error (prior rem - actual rem)", f"{censored}|pace {pb}")].append((eid, prior_rem - actual_rem))
                fb = "priorSeasonFallback" if pg.get("fallback") else "currentSeason"
                tags.append(f"{censored}|{fb}")
                acc[("P2 live_update (model rem - prior rem)", f"{censored}|{fb}")].append((eid, model_rem - prior_rem))
                acc[("P2 prior_error (prior rem - actual rem)", f"{censored}|{fb}")].append((eid, prior_rem - actual_rem))
            pen2 = blowout_penalty(penalty, period, clock, h - w) if (penalty and sport == "ncaab") else None
            for t in tags:
                acc[("P2 model-final", t)].append((eid, err))
                if pen2 is not None:
                    acc[("P2 COUNTERFACTUAL rule off model-final", t)].append((eid, err + pen2))
                acc[("P2 per remaining minute", t)].append(
                    (eid, err / max(1.0, (regulation_left(period, clock) + (300 if period > PERIODS else 0)) / 60.0)))
    # pregame: the engine's prior and the pregame sim against the final, one row per game
    reg_xy: list[tuple[float, float]] = []
    for eid, (pg, g) in pregame_rows.items():
        fin = g["final_home"] + g["final_away"]
        half = PERIODS // 2
        h1a = sum(g["lines_home"][:half]) + sum(g["lines_away"][:half])
        h2a = fin - h1a
        tag = "pregame|" + ("OT-counted sim" if str(pg.get("computed_at") or "") >= "2026-11-05T22:36" else "pre-OT-fix sim")
        acc[("P0 pregame target - final", "pregame|all")].append((eid, float(pg["target"]) - fin))
        acc[("P0 pregame target - final", f"pregame|date {pg.get('date')}")].append((eid, float(pg["target"]) - fin))
        reg_xy.append((float(pg["target"]), float(fin)))
        acc[("P0 pregame target - final", tag)].append((eid, float(pg["target"]) - fin))
        if isinstance(pg.get("raw"), (int, float)):
            acc[("P0 raw prior - final", "pregame|all")].append((eid, float(pg["raw"]) - fin))
        if isinstance(pg.get("sim_total"), (int, float)):
            acc[("P0 pregame sim total - final", tag)].append((eid, float(pg["sim_total"]) - fin))
        sm = pg.get("seg_means") or {}
        if "h1" in sm:
            acc[("P0 pregame sim h1 - actual h1", tag)].append((eid, sm["h1"] - h1a))
        if "h2" in sm:
            acc[("P0 pregame sim h2 - actual h2(+OT)", tag)].append((eid, sm["h2"] - h2a))
        acc[("P0 target x H1_SHARE - actual h1", "pregame|all")].append((eid, float(pg["target"]) * H1_SHARE - h1a))
        acc[("P0 target x (1-H1_SHARE) - actual h2(+OT)", "pregame|all")].append((eid, float(pg["target"]) * (1 - H1_SHARE) - h2a))
        acc[("P0 actual h1 share", "pregame|all")].append((eid, h1a / fin))
    print(f"  lane states placed: {states_used}; dates: { {k: sorted(v) for k, v in dates_used.items()} }; skipped {dict(skipped)}")
    # final regressed on the prior target (the target ON the model, `learnings 2026-11-03`): slope and intercept
    if len(reg_xy) > 3:
        n = len(reg_xy)
        mx, my = sum(x for x, _ in reg_xy) / n, sum(y for _, y in reg_xy) / n
        sxx = sum((x - mx) ** 2 for x, _ in reg_xy)
        sxy = sum((x - mx) * (y - my) for x, y in reg_xy)
        b = sxy / sxx
        a0 = my - b * mx
        resid = [y - (a0 + b * x) for x, y in reg_xy]
        s2 = sum(e * e for e in resid) / (n - 2)
        print(f"  P0 OLS final = a + b * pregame target over {n} games: b = {b:.3f} +- {(s2 / sxx) ** 0.5:.3f}, "
              f"a = {a0:+.1f}; mean target {mx:.1f}, mean final {my:.1f}")
    # one row per game: the FIRST priced totals record (closest to the tip) and the game's mean, line and model vs final
    for cen in ("pregate", "censored"):
        firsts = [sorted(v)[0] for (c, _), v in per_game_lines.items() if c == cen]
        means = [(sum(x[1] for x in v) / len(v), sum(x[2] for x in v) / len(v)) for (c, _), v in per_game_lines.items() if c == cen]
        if len(firsts) < 2:
            continue
        def ms(vals):
            mu = sum(vals) / len(vals)
            sd = (sum((x - mu) ** 2 for x in vals) / (len(vals) - 1)) ** 0.5
            return mu, sd / len(vals) ** 0.5
        fl, fm = ms([f[1] for f in firsts]), ms([f[2] for f in firsts])
        gl, gm = ms([m[0] for m in means]), ms([m[1] for m in means])
        under = sum(1 for f in firsts if f[1] > 0)
        print(f"  P1 per game [{cen}] {len(firsts)} games: FIRST priced row line-final {fl[0]:+.2f}+-{fl[1]:.2f} "
              f"model-final {fm[0]:+.2f}+-{fm[1]:.2f}, final under that line in {under}/{len(firsts)}; "
              f"GAME MEAN line-final {gl[0]:+.2f}+-{gl[1]:.2f} model-final {gm[0]:+.2f}+-{gm[1]:.2f}")
    for fam in sorted({k[0] for k in acc}):
        for k in sorted(k for k in acc if k[0] == fam):
            res = qo.clustered(acc[k])
            if res is None:
                continue
            mean, se, n, ng = res
            print(f"  {fam:44s} {k[1]:46s} n={n:6d} games={ng:4d}  mean={mean:+8.3f}  se={se:.3f}")
    if unmatched:
        print("  unmatched sample:", sorted(unmatched)[:6])


if __name__ == "__main__":
    main()
