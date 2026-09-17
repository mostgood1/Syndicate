# -*- coding: utf-8 -*-
"""Forward grades over the pre-kickoff freeze: H27 (corners estimator vs market) and watch-list W1r / W2 / W3.

Lane `soccer-forward-graders`, 2026-09-17. The rules are the registrations, not this file:

  W1 / W2 / W3   `.syndicate/log/2026-09-16.md` ~20:50 CT  (W1 ended when the corners model changed)
  H27            `.syndicate/log/2026-09-16.md` ~22:45 CT
  W1r            `.syndicate/log/2026-09-17.md` ~07:20 CT
  details        `.syndicate/log/2026-09-17.md` ~11:40 CT (ESPN kickoff, service merge, dispersion per
                 grade, CI level, and the REPORTED-ONLY book_quotes price sensitivity)

The registrations name the audit's own code, so this module imports it instead of restating it:
`audit_games.load_game_markets` / `corners_market` / `last_season_corners` / `settle`,
`audit_props.bind_players` / `appeared`, `namejoin_diag.score`, `common.nb_sf` / `poisson_sf` /
`find_fixture` / `load_recs`, `corners_estimators.load_history`, and `outcomes.extract`.

Two steps, so the grade itself never touches the network:

    py -3 scripts/soccer_season_audit/forward_grade.py pull  --cache <dir> [--with-book-quotes]
    py -3 scripts/soccer_season_audit/forward_grade.py grade --cache <dir> --history-root <checkout WITH data/>

`pull` reads production through `/api/ops/artifacts/export` (and `/stream` for book_quotes, which is
over the export's per-file cap) plus ESPN match summaries. `grade` writes `<cache>/forward_grade.json`
and prints each cell's funnel (frozen -> finished -> in window -> priced -> bets) before its verdict,
so a zero is visible at the stage where it happened.

NOTHING HERE IS STAKED. A verdict changes nothing without a separate user decision.
"""
from __future__ import annotations

import argparse
import collections
import csv
import datetime as dt
import glob
import io
import json
import math
import os
import random
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
CHECKOUT = HERE.parents[1]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
os.environ.setdefault("SYNDICATE_REPO_ROOT", str(CHECKOUT))

import audit_games  # noqa: E402
from audit_games import corners_market, settle  # noqa: E402
from audit_props import appeared, bind_players  # noqa: E402
from common import LEAGUES, dec_from_american, find_fixture, fold, load_recs, nb_sf, poisson_sf, ts  # noqa: E402
from namejoin_diag import score as name_score  # noqa: E402

CORNERS_BASIS = "team_rates_pressure_v1"
W1R_SINCE = dt.datetime(2026, 9, 17, 12, 12, 50, tzinfo=dt.timezone.utc)   # W1r registration commit
# Window ENDS. None = still open. A model change is recorded in the ledger first, then set here.
WINDOW_END: dict[str, dt.datetime | None] = {"W1r": None, "W2": None, "W3": None, "H27": None}
GRADE_DATE = dt.date(2026, 11, 15)
CLOSE_DATE = dt.date(2026, 12, 15)
CI_LEVEL = 0.983            # three cells, Bonferroni, two-sided
BOOT_REPS, BOOT_SEED = 2000, 11
W1R_EDGE, PROP_EDGE = 0.08, 0.15
WATCH_BETS, H27_MATCHES, H27_LEAGUE_N, H27_BIAS_BAR = 100, 150, 20, 0.5
FIXTURE_WINDOW_SECONDS = 3 * 3600
H27_DISPERSION_FROM = dt.datetime(2025, 7, 1)
PREKICKOFF_PATTERN = "soccer_source/*/api/recommendations/recommendations_prekickoff_*.json"
PROP_MARKETS = {"player_shots_on_target": "W2", "player_goal_scorer_anytime": "W3"}
PROP_SELECTION = {"player_shots_on_target": "over", "player_goal_scorer_anytime": "yes"}
_FREEZE_NAME = re.compile(r"recommendations_prekickoff_(\d{4}-\d{2}-\d{2})\.(.+)\.json$")


# ============================================================================ freeze + outcomes

def load_freeze_files(freeze_dir: Path) -> list[dict]:
    """Every cached freeze file as {league, date, service, matches}."""
    out = []
    for path in sorted(Path(freeze_dir).glob("*.json")):
        try:
            body = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        m = _FREEZE_NAME.search(path.name)
        if not isinstance(body, dict) or not isinstance(body.get("matches"), dict):
            continue
        out.append({"league": body.get("league"), "date": body.get("date") or (m.group(1) if m else None),
                    "service": body.get("service") or (m.group(2) if m else None), "matches": body["matches"]})
    return out


def espn_kickoff(summary: dict) -> dt.datetime | None:
    comp = ((summary.get("header") or {}).get("competitions") or [{}])[0]
    return ts(comp.get("date"))


def outcome_from_summary(summary: dict) -> dict:
    """`outcomes.extract` (the audit's box-score reader) plus the ESPN kickoff."""
    from outcomes import extract  # noqa: E402 -- imported late: outcomes.py reads %TEMP% at import
    rec = extract(summary)
    rec["kickoff"] = espn_kickoff(summary)
    return rec


def merge_frozen(files: list[dict], kickoffs: dict) -> dict:
    """(league, match_id) -> {entry, service, league, date}: the latest `frozen_at` strictly before the ESPN
    kickoff, across services. A match with no ESPN kickoff is not merged: it cannot be shown pre-kickoff."""
    merged: dict = {}
    for f in files:
        for mid, entry in f["matches"].items():
            key = (f["league"], str(mid))
            ko = kickoffs.get(key)
            frozen_at = ts(entry.get("frozen_at"))
            if ko is None or frozen_at is None or frozen_at >= ko:
                continue
            held = merged.get(key)
            if held is None or frozen_at > ts(held["entry"]["frozen_at"]):
                merged[key] = {"entry": entry, "service": f["service"], "league": f["league"], "date": f["date"]}
    return merged


def recs_from_merged(merged: dict, work_dir: Path) -> dict:
    """The audit's `load_recs` over the merged entries, one synthetic recommendations file per match, so
    every model field is read exactly as the audit read it (generated_at = frozen_at)."""
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    for old in work_dir.glob("*.json"):
        old.unlink()
    for (lg, mid), x in merged.items():
        body = {"league": lg, "date": x["date"], "generated_at": x["entry"]["frozen_at"],
                "matches": [x["entry"]["match"]], "player_props": x["entry"].get("player_props") or []}
        (work_dir / f"{lg}__{re.sub(r'[^A-Za-z0-9_-]', '_', mid)}.json").write_text(json.dumps(body), encoding="utf-8")
    return load_recs(str(work_dir))


def in_window(ko: dt.datetime, cell: str, since: dt.datetime | None = None) -> bool:
    end = WINDOW_END.get(cell)
    return (since is None or ko > since) and (end is None or ko < end)


# ============================================================================ statistics + verdicts

def boot_ci_level(units: list, stat, level: float = CI_LEVEL, reps: int = BOOT_REPS, seed: int = BOOT_SEED):
    """`common.boot_ci`'s resampling (same RNG draws), at a chosen two-sided level."""
    rng = random.Random(seed)
    k = len(units)
    if k < 5:
        return (float("nan"), float("nan"))
    vals = sorted(stat([units[rng.randrange(k)] for _ in range(k)]) for _ in range(reps))
    alpha = (1.0 - level) / 2.0
    return vals[int(alpha * reps)], vals[int((1.0 - alpha) * reps) - 1]


def roi_ci(bets: list[dict], field: str, level: float = CI_LEVEL):
    by = collections.defaultdict(list)
    for b in bets:
        by[b["key"]].append(b[field])
    units = list(by.values())
    if not units:
        return float("nan"), (float("nan"), float("nan")), 0
    stat = lambda s: sum(sum(u) for u in s) / max(sum(len(u) for u in s), 1)  # noqa: E731
    return stat(units), boot_ci_level(units, stat, level), len(units)


def watch_verdict(n_bets: int, roi: float, ci_low: float, today: dt.date) -> str:
    """W1r/W2/W3 (registration, ~20:50 CT): graded at 100 bets or 2026-11-15, whichever is first."""
    if n_bets >= WATCH_BETS:
        if ci_low == ci_low and ci_low > 0:
            return "SUPPORTED"
        if roi <= 0:
            return "FALSIFIED"
        return "INCONCLUSIVE" if today < CLOSE_DATE else "NOT SHOWN"
    if today < GRADE_DATE:
        return "WATCHING"
    return "INSUFFICIENT" if today < CLOSE_DATE else "NOT SHOWN"


def h27_verdict(n_with_k: int, mae_m: float, mae_k: float, league_bias: dict, today: dt.date) -> str:
    """H27 (registration, ~22:45 CT): graded at >= 150 matches with a K, or on 2026-11-15."""
    if n_with_k < H27_MATCHES:
        return "WATCHING" if today < GRADE_DATE else "INSUFFICIENT"
    biased = [lg for lg, b in league_bias.items() if b["n"] >= H27_LEAGUE_N and abs(b["bias"]) > H27_BIAS_BAR]
    return "MET" if (mae_m <= mae_k and not biased) else "FALSIFIED"


def _r(xs, ys):
    n = len(xs)
    if n < 3:
        return float("nan")
    mx, my = sum(xs) / n, sum(ys) / n
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    sy = math.sqrt(sum((y - my) ** 2 for y in ys))
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (sx * sy) if sx and sy else float("nan")


def _mean(xs):
    xs = list(xs)
    return sum(xs) / len(xs) if xs else float("nan")


# ============================================================================ prices

def game_market_events(cache: Path) -> dict:
    """The audit's `load_game_markets` over `<cache>/prod/game_markets/*.json`: each event's last pre-kickoff
    FILE VERSION (the code the registrations name; see the ~11:40 CT log note on its wording)."""
    audit_games.S = str(cache)
    return audit_games.load_game_markets()


def book_quote_events(cache: Path, markets: tuple[str, ...]) -> dict:
    """REPORTED-ONLY sensitivity: per (league, event), each book's last `book_quotes` row with captured_at <
    kickoff, reshaped into `game_markets` rows (corners) or prop offers."""
    last: dict = {}
    meta: dict = {}
    for path in sorted(Path(cache, "book_quotes").glob("*.jsonl")):
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                if r.get("market") not in markets:
                    continue
                ko, ca = ts(r.get("commence_time")), ts(r.get("captured_at"))
                if ko is None or ca is None or ca >= ko:
                    continue
                ev = (r.get("league"), r.get("event_id"))
                meta[ev] = {"league": r.get("league"), "home": r.get("home_team"), "away": r.get("away_team"), "game_time": ko}
                k = (ev, r.get("market"), r.get("bookmaker"), r.get("player_name"), r.get("line"), str(r.get("selection")).lower())
                if k not in last or ca > last[k][0]:
                    last[k] = (ca, r.get("price"))
    events = {ev: {**m, "rows": []} for ev, m in meta.items()}
    for (ev, market, book, player, line, sel), (_, price) in last.items():
        events[ev]["rows"].append({"market_key": market, "book": book, "player": player, "line": line, "side": sel, "price": price})
    return events


def prop_offers_registered(cache: Path) -> list[dict]:
    """`audit_props`' market rule over `<cache>/prod/props/*.csv`: files dated on/before the game date, the
    latest file date winning per (event, player, market, line, book). One row per book."""
    latest: dict = {}
    for path in glob.glob(os.path.join(cache, "prod", "props", "*.csv")):
        m = re.search(r"(\d{4}-\d{2}-\d{2})\.csv$", os.path.basename(path))
        if not m or os.path.getsize(path) < 50:
            continue
        fdate = m.group(1)
        with io.open(path, encoding="utf-8") as handle:
            for r in csv.DictReader(handle):
                if r.get("market_key") not in PROP_MARKETS:
                    continue
                gt = ts(r.get("game_time"))
                if gt is None or fdate > gt.date().isoformat():
                    continue
                try:
                    price = float(r["over_price"])
                except (TypeError, ValueError, KeyError):
                    continue
                line = _line(r.get("line"))
                k = (r.get("event_id"), r.get("player"), r["market_key"], line, r.get("book"))
                if k not in latest or fdate >= latest[k]["_fdate"]:
                    latest[k] = {"_fdate": fdate, "league": r.get("league"), "event_id": r.get("event_id"), "home": r.get("home_team"),
                                 "away": r.get("away_team"), "game_time": gt, "player": r.get("player"), "market": r["market_key"],
                                 "line": line, "book": r.get("book"), "price": price}
    return list(latest.values())


def prop_offers_book_quotes(cache: Path) -> list[dict]:
    out = []
    for ev in book_quote_events(cache, tuple(PROP_MARKETS)).values():
        for r in ev["rows"]:
            if r["side"] != PROP_SELECTION.get(r["market_key"]) or r["price"] is None:
                continue
            out.append({"league": ev["league"], "event_id": None, "home": ev["home"], "away": ev["away"], "game_time": ev["game_time"],
                        "player": r["player"], "market": r["market_key"], "line": _line(r["line"]), "book": r["book"], "price": float(r["price"])})
    return out


def _line(value):
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(v) else v


# ============================================================================ cells

def _fixture(recs_by_league: dict, lg: str, home, away, when: dt.datetime):
    return find_fixture(home, away, [(x["home"], x["away"], x) for x in recs_by_league.get(lg, [])
                                     if x["kickoff"] and abs((x["kickoff"] - when).total_seconds()) <= FIXTURE_WINDOW_SECONDS])


def corners_items(recs: dict, outcomes: dict, events: dict, cell: str, since=None, basis=None, merged=None) -> tuple[list, collections.Counter]:
    """One item per frozen finished match in the cell's population, with its corners outcome and (if any) market."""
    funnel = collections.Counter()
    by_lg = collections.defaultdict(list)
    for e in events.values():
        by_lg[e["league"]].append(e)
    items = []
    for (lg, mid), m in recs.items():
        o = outcomes.get((lg, mid))
        funnel["frozen"] += 1
        if not o or not o.get("completed") or o.get("kickoff") is None:
            continue
        funnel["finished"] += 1
        if not in_window(o["kickoff"], cell, since):
            continue
        if basis is not None:
            vp = ((merged or {}).get((lg, mid), {}).get("entry", {}).get("match") or {}).get("volume_projection") or {}
            if vp.get("corners_basis") != basis:
                continue
        funnel["in_window"] += 1
        ch = (o["teams"].get("home") or {}).get("wonCorners")
        ca = (o["teams"].get("away") or {}).get("wonCorners")
        if ch is None or ca is None or m["corners_h"] is None or m["corners_a"] is None:
            continue
        funnel["with_outcome"] += 1
        ev = None
        if m["kickoff"]:
            ev = find_fixture(m["home"], m["away"], [(e["home"], e["away"], e) for e in by_lg.get(lg, [])
                                                     if abs((e["game_time"] - m["kickoff"]).total_seconds()) <= FIXTURE_WINDOW_SECONDS])
        mk = corners_market(ev["rows"]) if ev else None
        funnel["priced"] += bool(mk)
        items.append({"lg": lg, "key": f"{lg}|{mid}", "date": m["date"], "mh": float(m["corners_h"]), "ma": float(m["corners_a"]),
                      "ch": float(ch), "ca": float(ca), "mk": mk})
    return items, funnel


def w1r_bets(items: list, dispersion: dict, pooled: float) -> list[dict]:
    """`audit_games.main`'s corners legs, at the one registered threshold."""
    bets = []
    for i in items:
        if not i["mk"]:
            continue
        k = int(math.floor(i["mk"]["line"])) + 1
        pm = nb_sf(k, i["mh"] + i["ma"], dispersion.get(i["lg"], pooled))
        pk, y = i["mk"]["fair"], (i["ch"] + i["ca"] >= k)
        legs = ({"side": "over", "edge": pm - pk, "dec_typ": i["mk"]["med"][0], "dec_best": i["mk"]["best"][0], "won": y},
                {"side": "under", "edge": pk - pm, "dec_typ": i["mk"]["med"][1], "dec_best": i["mk"]["best"][1], "won": not y})
        for leg in legs:
            if leg["edge"] >= W1R_EDGE:
                bets.append({"key": i["key"], "lg": i["lg"], "line": i["mk"]["line"], **leg,
                             "p_typ": settle(leg["dec_typ"], leg["won"]), "p_best": settle(leg["dec_best"], leg["won"])})
    return bets


def implied_mean(line: float, fair_over: float, disp: float) -> float:
    """`corners_estimators.market_benchmark`'s inversion of `nb_sf`."""
    k, lo, hi = int(math.floor(line)) + 1, 1.0, 25.0
    for _ in range(50):
        mid = (lo + hi) / 2.0
        if nb_sf(k, mid, disp) < fair_over:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def h27_report(items: list, dispersion: dict, pooled: float, today: dt.date) -> dict:
    with_k = [i for i in items if i["mk"]]
    act = [i["ch"] + i["ca"] for i in with_k]
    m_ = [i["mh"] + i["ma"] for i in with_k]
    k_ = [implied_mean(i["mk"]["line"], i["mk"]["fair"], dispersion.get(i["lg"], pooled)) for i in with_k]
    mae_m = _mean(abs(a - p) for a, p in zip(act, m_))
    mae_k = _mean(abs(a - p) for a, p in zip(act, k_))
    league_bias = {}
    for lg in LEAGUES:
        sub = [i for i in with_k if i["lg"] == lg]
        if sub:
            league_bias[lg] = {"n": len(sub), "bias": _mean(i["ch"] + i["ca"] - i["mh"] - i["ma"] for i in sub)}
    all_bias = {lg: {"n": len(s), "bias": _mean(i["ch"] + i["ca"] - i["mh"] - i["ma"] for i in s)}
                for lg in LEAGUES for s in [[i for i in items if i["lg"] == lg]] if s}
    team_a = [x for i in with_k for x in (i["ch"], i["ca"])]
    team_m = [x for i in with_k for x in (i["mh"], i["ma"])]
    return {"n_population": len(items), "n_with_k": len(with_k), "mae_m": mae_m, "mae_k": mae_k,
            "r_m": _r(m_, act), "r_k": _r(k_, act), "team_mae_m": _mean(abs(a - p) for a, p in zip(team_a, team_m)),
            "league_bias_with_k": league_bias, "league_bias_all": all_bias,
            "verdict": h27_verdict(len(with_k), mae_m, mae_k, league_bias, today)}


def prop_bets(offers: list, recs: dict, outcomes: dict, cell: str) -> tuple[list[dict], collections.Counter]:
    """`audit_props.main`'s market section, raw model probability, for one cell's market."""
    market = next(k for k, v in PROP_MARKETS.items() if v == cell)
    funnel = collections.Counter()
    by_lg = collections.defaultdict(list)
    for x in recs.values():
        if x["kickoff"]:
            by_lg[x["league"]].append(x)
    grouped: dict = collections.defaultdict(list)
    event_match: dict = {}
    for off in offers:
        if off["market"] != market:
            continue
        ev = (off["league"], off["home"], off["away"], off["game_time"])
        if ev not in event_match:
            event_match[ev] = _fixture(by_lg, off["league"], off["home"], off["away"], off["game_time"])
        m = event_match[ev]
        if m is None:
            continue
        grouped[(off["league"], m["match_id"], fold(off["player"]), off["line"])].append(off)
    bind_cache: dict = {}
    bets = []
    for (lg, mid, pname, line), offs in grouped.items():
        m, o = recs.get((lg, mid)), outcomes.get((lg, mid))
        funnel["priced_lines"] += 1
        if not o or not o.get("completed") or o.get("kickoff") is None or not in_window(o["kickoff"], cell):
            continue
        funnel["finished_in_window"] += 1
        scored = sorted(((name_score(pname, p.get("player_name")), k) for k, p in enumerate(m["players"])), reverse=True)
        if not scored or scored[0][0] < 0.84 or (len(scored) > 1 and scored[1][0] >= scored[0][0]):
            funnel["no_model_player"] += 1
            continue
        pm = m["players"][scored[0][1]]
        if (lg, mid) not in bind_cache:
            bind_cache[(lg, mid)] = bind_players(m["players"], o["players"])
        hit = bind_cache[(lg, mid)].get(id(pm))
        if hit is None or not appeared(hit):
            funnel["void_or_unmatched"] += 1
            continue
        if cell == "W3":
            p = pm.get("anytime_scorer_probability_if_playing")
            won = (hit["goals"] or 0) >= 1
        else:
            mu = pm.get("expected_shots_on_target_if_playing")
            if line is None or mu is None:
                continue
            k = int(math.floor(line)) + 1
            p = poisson_sf(k, mu)
            won = (hit["sot"] or 0) >= k
        if p is None:
            continue
        funnel["graded_lines"] += 1
        decs = sorted(dec_from_american(x["price"]) for x in offs)
        best, med = decs[-1], decs[len(decs) // 2]
        if p - 1.0 / best >= PROP_EDGE:
            bets.append({"key": f"{lg}|{mid}", "lg": lg, "player": pname, "line": line, "p": p, "edge": p - 1.0 / best,
                         "best": best, "med": med, "won": won, "p_best": settle(best, won), "p_typ": settle(med, won)})
    funnel["bets"] = len(bets)
    return bets, funnel


def cell_summary(bets: list[dict], verdict_field: str, today: dt.date) -> dict:
    roi_v, ci_v, n_matches = roi_ci(bets, verdict_field)
    other = "p_typ" if verdict_field == "p_best" else "p_best"
    roi_o, ci_o, _ = roi_ci(bets, other)
    return {"bets": len(bets), "matches": n_matches, "hit": _mean(1.0 if b["won"] else 0.0 for b in bets),
            "mean_odds": _mean((b.get("dec_typ") or b.get("med")) if verdict_field == "p_typ" else (b.get("dec_best") or b.get("best")) for b in bets),
            "roi": roi_v, "ci": ci_v, "roi_other_price": roi_o, "ci_other_price": ci_o, "verdict_price": verdict_field,
            "verdict": watch_verdict(len(bets), roi_v, ci_v[0], today)}


# ============================================================================ dispersion

def w1r_dispersion(history_root: Path) -> tuple[dict, float]:
    audit_games.PRIMARY = str(history_root)
    lsc = audit_games.last_season_corners()
    return {lg: v["disp"] for lg, v in lsc.items()}, _mean(v["disp"] for v in lsc.values())


def h27_dispersion(history_root: Path) -> tuple[dict, float]:
    from corners_estimators import load_history  # noqa: E402
    hist = load_history(os.path.join(str(history_root), "data", "soccer_source"))
    disp = {}
    if not hist.empty:
        for lg, g in hist[hist.date >= H27_DISPERSION_FROM].groupby("lg"):
            tot = g.hc + g.ac
            disp[lg] = max(1.0, float(tot.var() / tot.mean()))
    return disp, (_mean(disp.values()) if disp else 1.0)


# ============================================================================ grade

def today_ct() -> dt.date:
    try:
        from zoneinfo import ZoneInfo
        return dt.datetime.now(ZoneInfo("America/Chicago")).date()
    except Exception:  # noqa: BLE001 -- no tz database on this machine: CST, the later of the two offsets
        return dt.datetime.now(dt.timezone(dt.timedelta(hours=-6))).date()


def grade(cache: Path, history_root: Path, today: dt.date | None = None) -> dict:
    cache = Path(cache)
    today = today or today_ct()
    outcomes = {}
    for path in Path(cache, "espn").glob("*.json"):
        lg, _, mid = path.stem.partition("__")
        try:
            outcomes[(lg, mid)] = outcome_from_summary(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            continue
    kickoffs = {k: v["kickoff"] for k, v in outcomes.items() if v.get("kickoff")}
    files = load_freeze_files(cache / "freeze")
    merged = merge_frozen(files, kickoffs)
    recs = recs_from_merged(merged, cache / "_recs")
    report: dict = {"today": today.isoformat(), "freeze_files": len(files),
                    "freeze_entries": sum(len(f["matches"]) for f in files), "merged_prekickoff": len(merged),
                    "services": dict(collections.Counter(x["service"] for x in merged.values())), "registered": {}, "sensitivity_book_quotes": {}}
    d1, p1 = w1r_dispersion(history_root)
    d27, p27 = h27_dispersion(history_root)
    report["dispersion"] = {"w1r": d1, "w1r_pooled": p1, "h27": d27, "h27_pooled": p27}

    price_sets = [("registered", game_market_events(cache), prop_offers_registered(cache))]
    if list(Path(cache, "book_quotes").glob("*.jsonl")):
        price_sets.append(("sensitivity_book_quotes", book_quote_events(cache, ("alternate_totals_corners",)), prop_offers_book_quotes(cache)))
    for label, events, offers in price_sets:
        out = report[label]
        items, funnel = corners_items(recs, outcomes, events, "W1r", since=W1R_SINCE, basis=CORNERS_BASIS, merged=merged)
        bets = w1r_bets(items, d1, p1)
        out["W1r"] = {"funnel": {**funnel, "bets": len(bets)}, **cell_summary(bets, "p_typ", today)}
        items27, funnel27 = corners_items(recs, outcomes, events, "H27", basis=CORNERS_BASIS, merged=merged)
        out["H27"] = {"funnel": dict(funnel27), **h27_report(items27, d27, p27, today)}
        for cell in ("W2", "W3"):
            pb, pf = prop_bets(offers, recs, outcomes, cell)
            out[cell] = {"funnel": dict(pf), **cell_summary(pb, "p_best", today)}
    return report


def print_report(report: dict) -> None:
    print(f"forward grade {report['today']}: freeze files {report['freeze_files']}, entries {report['freeze_entries']}, "
          f"merged pre-kickoff with an ESPN kickoff {report['merged_prekickoff']} {report['services']}")
    for label in ("registered", "sensitivity_book_quotes"):
        block = report.get(label) or {}
        if not block:
            continue
        print(f"\n== {label}{'  (REPORTED ONLY, never a verdict)' if label != 'registered' else ''} ==")
        h = block["H27"]
        print(f"  H27 funnel {h['funnel']}")
        print(f"      n with K {h['n_with_k']}  MAE M {h['mae_m']:.3f}  MAE K {h['mae_k']:.3f}  r M {h['r_m']:+.3f}  r K {h['r_k']:+.3f}  "
              f"team MAE M {h['team_mae_m']:.3f}  -> {h['verdict'] if label == 'registered' else '-'}")
        print("      league bias (with K): " + " | ".join(f"{lg} n{b['n']} {b['bias']:+.2f}" for lg, b in h["league_bias_with_k"].items()))
        for cell in ("W1r", "W2", "W3"):
            c = block[cell]
            print(f"  {cell} funnel {c['funnel']}")
            print(f"      bets {c['bets']} matches {c['matches']} hit {c['hit']:.3f} odds {c['mean_odds']:.2f}  ROI ({c['verdict_price']}) "
                  f"{100 * c['roi']:+.1f}% [{100 * c['ci'][0]:+.1f},{100 * c['ci'][1]:+.1f}]  other price {100 * c['roi_other_price']:+.1f}%  "
                  f"-> {c['verdict'] if label == 'registered' else '-'}")


# ============================================================================ pull (network)

def _prod():
    sys.path.insert(0, str(CHECKOUT / "scripts"))
    from fetch_prod_artifacts_paced import DEFAULT_BASE, admin_token, export  # noqa: E402
    return DEFAULT_BASE, admin_token(), export


def _stream(base: str, token: str, rel_path: str, dest: Path) -> int:
    import urllib.parse
    import urllib.request
    url = f"{base}/api/ops/artifacts/stream?" + urllib.parse.urlencode({"path": rel_path})
    req = urllib.request.Request(url, headers={"X-Admin-Token": token})
    tmp = dest.with_name(dest.name + ".part")
    with urllib.request.urlopen(req, timeout=900) as handle, open(tmp, "wb") as out:
        while True:
            chunk = handle.read(1 << 20)
            if not chunk:
                break
            out.write(chunk)
    os.replace(tmp, dest)
    return dest.stat().st_size


def pull(cache: Path, with_book_quotes: bool = False, pause: float = 2.0) -> dict:
    from syndicate.features.soccer.ingestion.espn_lineups import fetch_match_summary  # noqa: E402
    cache = Path(cache)
    for sub in ("freeze", "espn", "prod/game_markets", "prod/props", "book_quotes"):
        (cache / sub).mkdir(parents=True, exist_ok=True)
    base, token, export = _prod()
    now = dt.datetime.now(dt.timezone.utc)
    tally = collections.Counter()

    res = export(base, token, {"pattern": PREKICKOFF_PATTERN}, 900)
    for name in [o["path"] for o in res.get("oversize") or []]:
        _stream(base, token, name, cache / "freeze" / f"{name.split('/')[1]}__{os.path.basename(name)}")
        tally["freeze_streamed"] += 1
    for name, body in (res.get("artifacts") or {}).items():
        text = json.dumps(body) if isinstance(body, (dict, list)) else body
        (cache / "freeze" / f"{name.split('/')[1]}__{os.path.basename(name)}").write_text(text, encoding="utf-8")
        tally["freeze_files"] += 1
    if res.get("truncated"):
        raise SystemExit("freeze export truncated: re-run with a narrower pattern before grading")

    started = []
    for f in load_freeze_files(cache / "freeze"):
        for mid, entry in f["matches"].items():
            ko = ts(entry.get("kickoff"))
            if ko and ko < now - dt.timedelta(hours=2):
                started.append((f["league"], str(mid), ko))
    for lg, mid, _ in sorted(set(started)):
        dest = cache / "espn" / f"{lg}__{mid}.json"
        if dest.exists():
            try:
                if outcome_from_summary(json.loads(dest.read_text(encoding="utf-8"))).get("completed"):
                    tally["espn_cached"] += 1
                    continue
            except Exception:
                pass
        try:
            summary = fetch_match_summary(lg, mid)
        except Exception as exc:  # noqa: BLE001 -- counted, never silent
            tally[f"espn_fail_{type(exc).__name__}"] += 1
            continue
        dest.write_text(json.dumps(summary), encoding="utf-8")
        tally["espn_fetched"] += 1
        time.sleep(0.35)

    days = sorted({ko.date() for _, _, ko in started})
    wanted = sorted({d - dt.timedelta(days=back) for d in days for back in range(4)})
    for d in wanted:
        iso = d.isoformat()
        fresh = d >= now.date() - dt.timedelta(days=2)
        for pattern, sub, ext in ((f"soccer_source/*/props/game_markets_{iso}.json", "prod/game_markets", "json"),
                                  (f"soccer_source/*/props/{iso}.csv", "prod/props", "csv")):
            if not fresh and list((cache / sub).glob(f"*_{iso}.{ext}")):
                continue
            r = export(base, token, {"pattern": pattern}, 900)
            for name, body in (r.get("artifacts") or {}).items():
                text = json.dumps(body) if isinstance(body, (dict, list)) else body
                (cache / sub / f"{name.split('/')[1]}_{iso}.{ext}").write_text(text, encoding="utf-8")
                tally[f"{sub}_files"] += 1
            tally[f"{sub}_oversize_skipped"] += int(r.get("oversize_skipped") or 0)
            time.sleep(pause)
        if with_book_quotes and d in days:
            dest = cache / "book_quotes" / f"{iso}.jsonl"
            if fresh or not dest.exists():
                _stream(base, token, f"soccer_source/tracking/book_quotes/{iso}.jsonl", dest)
                tally["book_quotes_days"] += 1
                time.sleep(pause)
    return dict(tally)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("pull")
    p.add_argument("--cache", required=True)
    p.add_argument("--with-book-quotes", action="store_true")
    g = sub.add_parser("grade")
    g.add_argument("--cache", required=True)
    g.add_argument("--history-root", required=True, help="a checkout WITH data/soccer_source/*/history")
    g.add_argument("--today", help="YYYY-MM-DD (CT); default today")
    args = ap.parse_args(argv)
    if args.cmd == "pull":
        print(json.dumps(pull(Path(args.cache), args.with_book_quotes), indent=1))
        return 0
    today = dt.date.fromisoformat(args.today) if args.today else None
    report = grade(Path(args.cache), Path(args.history_root), today)
    Path(args.cache, "forward_grade.json").write_text(json.dumps(report, indent=1, default=str), encoding="utf-8")
    print_report(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
