"""Backtest: do NCAAF game lines and player props beat a naive baseline AND the book?

Lane `ncaaf-lines-props-backtest` (2026-10-02). The NHL template
(`nhl-player-props-projection`, deploys.md 2026-10-02 21:38Z) applied to NCAAF:
run THE PRODUCTION CODE PATH, unmodified, over completed games whose inputs are
rebuilt AS-OF kickoff, score every market against (a) the actual result, (b) a
naive baseline, (c) the de-vigged book, and let the result GATE the board. A
market earns a probability/edge only if it beats the baseline AND the book.

--------------------------------------------------------------------------
ARMS (each says where its inputs come from and how many games it rests on)
--------------------------------------------------------------------------

  L25  GAME LINES, 2025 regular season, FBS vs FBS, weeks 3-15 (the in-season
       blend production runs from week 3). Ratings are rebuilt per week with
       the SHIPPED `inseason_blend_index` (prior = 2024 FINAL SP+, current =
       CFBD `/ppa/games` rows for weeks < N, games completed in weeks < N),
       turned into a game by the SHIPPED `build_projection` (300 seeds, the
       promoted calibration profile) with a `FootballSegmentAccumulator`, so
       the segment numbers are the ones `segment_projections` would price.
       Book = CFBD `/lines` close (DraftKings when quoted, else the median of
       the providers); moneylines de-vigged per provider. Spread/total carry
       NO prices in CFBD, so the book's probability at its OWN line is 0.5.
  L26  GAME LINES, 2026 weeks 3-4: PRODUCTION's own pregame CSVs (the
       sha-checked snapshots `ncaaf-blend-forward-grade` saved; Render is
       suspended and the fleet's wk4 CSV was rewritten after the games) for
       full-game markets; segments by rebuilding each game from the
       snapshotted blend entry (that rebuild reproduced 113/115 production
       rows exactly on 2026-09-28; re-checked here per game). Books: the DK
       close (CFBD) and, for week 4, the Render-era OddsAPI captures (two-sided
       prices, real de-vig; captured <= 2026-09-23 -- early-week, NOT a close).
  L26C GAME LINES on the fleet's first completed slate with CLOSING segment
       quotes (kickoffs 2026-10-02T00-02Z), rebuilt from the week-5 blend entry
       (inputs weeks < 5, i.e. pregame). Tiny by construction; reported so the
       segment-vs-book cells are not left blank without a reason.
  P25  PROPS, 2025 weeks 2-16: the SHIPPED `payload_from_players` per week over
       the fleet's player-game-stats snapshot, scored on the player's actual
       week-N line. Baseline = the player's own as-of season mean (the
       entry's `season_mean`). Anytime TD: the `prop_model` rate, AS-OF (the
       shipped `anytime_td_probability` reads the whole season -- lookahead --
       so it cannot be graded as-is; the as-of form is its own backtest's).
  P26  PROPS, 2026 week 4 (+ the 10-02 slate): production code over a
       snapshot holding 2025 + 2026 weeks < N, against real book prices
       (Render-era captures for week 4; fleet captures for week 5's first
       slate), de-vigged two-way per book at the same line.

NOT AS-OF (frozen, stated): the calibration profile (fit on 2023-2025 drives,
so in-sample for L25), the prop constants (chosen a priori), the 2024 FINAL SP+
prior (end of 2024 -- legitimately before 2025). The blend's points scale is
the 2024 fit (44.66, the original held-out grade's), not production's 44.497
which was fit on 2025 and would leak into L25.

HONESTY RULES BUILT IN: coverage per family and the INTERSECTION are printed
first; every statistic carries n; every claimed difference carries a
game-clustered bootstrap CI; nothing is SUPPLIED that production lacked (no
actual lineup, no post-kickoff row, no week-N stat in a week-N projection);
one-sided quotes (Anytime TD "yes") are excluded and COUNTED, never de-vigged.

Usage:
  py -3 scripts/backtest_ncaaf_lines_props.py fetch --work C:/tmp/ncaaf_lpb
  py -3 scripts/backtest_ncaaf_lines_props.py sim   --work C:/tmp/ncaaf_lpb --arm L26 --workers 6
  py -3 scripts/backtest_ncaaf_lines_props.py sim   --work C:/tmp/ncaaf_lpb --arm L25 --workers 6
  py -3 scripts/backtest_ncaaf_lines_props.py score --work C:/tmp/ncaaf_lpb
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import math
import os
import random
import statistics
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

SEEDS = 300  # production's SEEDS_PER_GAME; asserted against the generator at sim time
BLEND_BETA_ASOF_2025 = 44.66  # the 2024 fit (see the docstring); production's 44.497 is fit on 2025
L25_WEEKS = range(3, 16)
SEGMENTS = ("q1", "q2", "q3", "q4", "h1", "h2")
PROP_MARKETS = {  # board label -> (snapshot column, prop_projections market key or None)
    "Passing Yards": ("passing_yards", "passing_yards"),
    "Passing TDs": ("passing_tds", "passing_tds"),
    "Rushing Yards": ("rushing_yards", "rushing_yards"),
    "Receiving Yards": ("receiving_yards", "receiving_yards"),
    "Receptions": ("receptions", "receptions"),
    "Anytime TD": ("anytime_td", None),
}
BOOT_REPS = 2000
PROB_CLIP = 0.005  # log-loss guard only; Brier is computed on the unclipped value


# ---------------------------------------------------------------------------
# small utils
# ---------------------------------------------------------------------------


def _read_json(path: Path) -> Any:
    if str(path).endswith(".gz"):
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            return json.load(handle)
    return json.loads(path.read_text(encoding="utf-8"))


def _f(value: Any) -> float | None:
    try:
        text = str(value).strip()
        if text == "" or text.lower() in {"none", "nan"}:
            return None
        out = float(text)
        return out if out == out else None
    except (TypeError, ValueError):
        return None


def _ts(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        out = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return out if out.tzinfo else out.replace(tzinfo=timezone.utc)


def american_to_prob(price: Any) -> float | None:
    p = _f(price)
    if p is None or p == 0 or -100 < p < 100:
        return None
    return 100.0 / (p + 100.0) if p > 0 else -p / (-p + 100.0)


def devig_two_way(price_a: Any, price_b: Any) -> float | None:
    """Proportional de-vig: fair P(side a)."""
    pa, pb = american_to_prob(price_a), american_to_prob(price_b)
    if pa is None or pb is None or pa + pb <= 0:
        return None
    return pa / (pa + pb)


def brier(p: float, y: int) -> float:
    return (p - y) ** 2


def logloss(p: float, y: int) -> float:
    p = min(1.0 - PROB_CLIP, max(PROB_CLIP, p))
    return -math.log(p if y else 1.0 - p)


def cluster_boot(rows: list[tuple[str, float]], *, reps: int = BOOT_REPS, seed: int = 20261002) -> dict[str, Any]:
    """Mean of per-row values with a CLUSTER (game) bootstrap 95% CI.

    `rows` = [(cluster_id, value)]. Rows of one game move together, because a
    game's player props share the game script and are not independent draws.
    """
    if not rows:
        return {"n": 0, "games": 0, "mean": None, "lo": None, "hi": None}
    by: dict[str, list[float]] = defaultdict(list)
    for cid, value in rows:
        by[cid].append(value)
    keys = list(by)
    sums = [sum(by[k]) for k in keys]
    counts = [len(by[k]) for k in keys]
    mean = sum(sums) / sum(counts)
    rng = random.Random(seed)
    draws = []
    m = len(keys)
    for _ in range(reps):
        s = c = 0.0
        for _ in range(m):
            i = rng.randrange(m)
            s += sums[i]
            c += counts[i]
        draws.append(s / c)
    draws.sort()
    return {"n": len(rows), "games": m, "mean": mean,
            "lo": draws[int(0.025 * reps)], "hi": draws[int(0.975 * reps) - 1]}


#: No verdict below this many GAMES (clusters): two games can exclude 0 and mean nothing.
MIN_GAMES_FOR_VERDICT = 20


def verdict(ci: dict[str, Any]) -> str:
    """Negative = the model is better (errors/losses are model minus comparator)."""
    if not ci or ci.get("n", 0) == 0 or ci.get("lo") is None:
        return "no data"
    if ci.get("games", MIN_GAMES_FOR_VERDICT) < MIN_GAMES_FOR_VERDICT:
        return f"insufficient (<{MIN_GAMES_FOR_VERDICT} games)"
    if ci["hi"] < 0:
        return "MODEL BETTER"
    if ci["lo"] > 0:
        return "MODEL WORSE"
    return "unresolved"


# ---------------------------------------------------------------------------
# environment: point every production module at the scratch data root
# ---------------------------------------------------------------------------


def configure_env(work: Path) -> None:
    os.environ["SYNDICATE_CALIBRATION_PROFILE_DIR"] = str(work / "calib")
    os.environ["SYNDICATE_DATA_ROOT"] = str(work / "dataroot")
    os.environ["SYNDICATE_NCAAF_SOURCE_ROOT"] = str(work / "dataroot" / "ncaaf_source")
    # The generator's drive priors default OFF and are off on the fleet (absent);
    # stated rather than relied on.
    os.environ.pop("SYNDICATE_NCAAF_DRIVE_PRIORS", None)
    for var in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
        os.environ.setdefault(var, "1")


def _gen():
    import scripts.generate_smartsim2_ncaaf_projections as module

    return module


def _src(work: Path) -> Path:
    return work / "dataroot" / "ncaaf_source"


def _snapshot_path(work: Path) -> Path:
    return _src(work) / "source_artifacts" / "data" / "processed" / "player_game_stats" / "ncaaf_player_game_stats_snapshot.csv"


def _load_dotenv() -> None:
    """CFBD_API_KEY from the primary checkout's .env; the value is never printed."""
    if os.environ.get("CFBD_API_KEY"):
        return
    for cand in (REPO / ".env", Path(r"C:\Users\tempadmin\OneDrive\Coding\Syndicate\.env")):
        if cand.exists():
            for line in cand.read_text(encoding="utf-8", errors="replace").splitlines():
                if line.startswith("CFBD_API_KEY="):
                    os.environ["CFBD_API_KEY"] = line.split("=", 1)[1].strip().strip('"').strip("'")
                    return


# ---------------------------------------------------------------------------
# FETCH (CFBD; every response cached, so `score` never calls out)
# ---------------------------------------------------------------------------


def cmd_fetch(args) -> None:
    work = args.work
    configure_env(work)
    _load_dotenv()
    cache = work / "cache"
    cache.mkdir(parents=True, exist_ok=True)
    gen = _gen()
    calls = 0
    for week in range(1, 16):
        path = cache / f"ppa_games_2025_wk{week:02d}.json"
        if not path.exists():
            rows = gen._load_ppa_games_week_uncached(2025, week)
            path.write_text(json.dumps(rows), encoding="utf-8")
            calls += 1
            print(f"ppa 2025 wk{week}: {len(rows)} rows", flush=True)
    path = cache / "games_2026_wk5.json"
    if not path.exists():
        rows = gen._cfbd_get("/games", {"year": 2026, "week": 5, "seasonType": "regular"})
        path.write_text(json.dumps(rows), encoding="utf-8")
        calls += 1
        print(f"games 2026 wk5: {len(rows)}", flush=True)
    # 2026 weeks 1-2 player logs: production held them on 2026-09-18 (8,115
    # rows) and the fleet's snapshot no longer does. Weeks 3-4 are the fleet's.
    from syndicate.features.ncaaf.cfbd import CfbdClient
    from syndicate.features.ncaaf.player_stats_refresh import refresh_week

    marker = cache / "player_stats_fetched.json"
    done = json.loads(marker.read_text()) if marker.exists() else {}
    client = None
    for week in (1, 2, 5):
        if str(week) in done:
            continue
        client = client or CfbdClient.from_env()
        result = refresh_week(client=client, season=2026, week=week, output_path=_snapshot_path(work))
        calls += 1
        done[str(week)] = {"rows_written": result.rows_written, "games": result.games_fetched,
                           "skipped": result.skipped, "reason": result.skip_reason}
        print(f"player stats 2026 wk{week}: {done[str(week)]}", flush=True)
        marker.write_text(json.dumps(done, indent=1))
    print(f"CFBD calls this run: {calls}")


# ---------------------------------------------------------------------------
# GAMES, RATINGS, NAIVE BASELINE
# ---------------------------------------------------------------------------


def load_games(work: Path, season: int) -> list[dict]:
    rows = _read_json(_src(work) / "historical_truth" / f"games_{season}.json.gz")
    if season == 2026 and (work / "cache" / "games_2026_wk5.json").exists():
        by_id = {int(r["id"]): r for r in rows}
        for r in _read_json(work / "cache" / "games_2026_wk5.json"):
            by_id[int(r["id"])] = r  # the fresher copy of week 5 (its Thursday finals)
        rows = list(by_id.values())
    return [r for r in rows if str(r.get("seasonType") or "regular") == "regular"]


def is_final(g: dict) -> bool:
    return g.get("homePoints") is not None and g.get("awayPoints") is not None and bool(g.get("completed", True))


def line_scores(g: dict) -> dict[str, tuple[float, float]] | None:
    """Per-segment (home, away) actual points; h2 is REGULATION only (Q3+Q4),
    matching `segment_actuals` and the accumulator's `h2_regulation_only`."""
    h, a = g.get("homeLineScores") or [], g.get("awayLineScores") or []
    if len(h) < 4 or len(a) < 4:
        return None
    try:
        h = [float(x) for x in h[:4]]
        a = [float(x) for x in a[:4]]
    except (TypeError, ValueError):
        return None
    return {"q1": (h[0], a[0]), "q2": (h[1], a[1]), "q3": (h[2], a[2]), "q4": (h[3], a[3]),
            "h1": (h[0] + h[1], a[0] + a[1]), "h2": (h[2] + h[3], a[2] + a[3])}


def naive_baseline(games: list[dict], week: int) -> dict[str, Any]:
    """Each team's OWN as-of scoring (the game-line analogue of 'the player's
    own average'): points for/against per game over completed regular-season
    games of weeks < N, plus the as-of league home edge and segment shares."""
    gen = _gen()
    pf: dict[str, list[float]] = defaultdict(list)
    pa: dict[str, list[float]] = defaultdict(list)
    home_edge: list[float] = []
    seg_share: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for g in games:
        if int(g.get("week") or 0) >= week or not is_final(g):
            continue
        hn, an = gen.norm(g["homeTeam"]), gen.norm(g["awayTeam"])
        hp, ap = float(g["homePoints"]), float(g["awayPoints"])
        pf[hn].append(hp); pa[hn].append(ap); pf[an].append(ap); pa[an].append(hp)
        if not g.get("neutralSite"):
            home_edge.append(hp - ap)
        ls = line_scores(g)
        if ls and hp + ap > 0:
            for seg, (sh, sa) in ls.items():
                seg_share[seg].append((sh / hp if hp else 0.0, sa / ap if ap else 0.0))
    edge = statistics.fmean(home_edge) if home_edge else 0.0
    shares = {seg: (statistics.fmean(x for x, _ in v), statistics.fmean(y for _, y in v)) for seg, v in seg_share.items()}
    return {"pf": pf, "pa": pa, "home_edge": edge, "shares": shares}


def naive_game(base: dict[str, Any], home: str, away: str, neutral: bool) -> dict[str, Any] | None:
    pf, pa = base["pf"], base["pa"]
    if len(pf.get(home, ())) < 2 or len(pf.get(away, ())) < 2:
        return None  # fewer than two games is not an average
    h = (statistics.fmean(pf[home]) + statistics.fmean(pa[away])) / 2.0
    a = (statistics.fmean(pf[away]) + statistics.fmean(pa[home])) / 2.0
    edge = 0.0 if neutral else base["home_edge"]
    h, a = h + edge / 2.0, a - edge / 2.0
    out = {"margin": h - a, "total": h + a, "home": h, "away": a, "segments": {}}
    for seg, (sh, sa) in base["shares"].items():
        out["segments"][seg] = {"margin": h * sh - a * sa, "total": h * sh + a * sa}
    return out


# ---------------------------------------------------------------------------
# BOOKS
# ---------------------------------------------------------------------------


def cfbd_book(row: dict) -> dict[str, Any] | None:
    """Close from one CFBD `/lines` game row. Home frame: market margin = -spread."""
    lines = [l for l in (row.get("lines") or []) if isinstance(l, dict)]
    if not lines:
        return None
    dk = [l for l in lines if str(l.get("provider") or "").replace(" ", "").lower() == "draftkings"]
    pick = dk[0] if dk else None
    spreads = [_f(l.get("spread")) for l in lines if _f(l.get("spread")) is not None]
    totals = [_f(l.get("overUnder")) for l in lines if _f(l.get("overUnder")) is not None]
    spread = _f(pick.get("spread")) if pick and _f(pick.get("spread")) is not None else (statistics.median(spreads) if spreads else None)
    total = _f(pick.get("overUnder")) if pick and _f(pick.get("overUnder")) is not None else (statistics.median(totals) if totals else None)
    fairs = [devig_two_way(l.get("homeMoneyline"), l.get("awayMoneyline")) for l in lines]
    fairs = [p for p in fairs if p is not None]
    dk_fair = devig_two_way(pick.get("homeMoneyline"), pick.get("awayMoneyline")) if pick else None
    return {"spread": spread, "total": total,
            "ml_home_fair": dk_fair if dk_fair is not None else (statistics.fmean(fairs) if fairs else None),
            "provider": "DraftKings" if pick else f"median_of_{len(lines)}"}


def load_cfbd_lines_2025() -> dict[int, dict]:
    """The primary checkout's cached 2025 `/lines` weeks (git-tracked CFBD history)."""
    base = Path(r"C:\Users\tempadmin\OneDrive\Coding\Syndicate\data\ncaaf_source\data")
    out: dict[int, dict] = {}
    for path in sorted(base.glob("cfbd_lines_wk*.json")):
        for row in _read_json(path):
            if isinstance(row, dict) and int(row.get("season") or 0) == 2025:
                book = cfbd_book(row)
                if book:
                    out[int(row["id"])] = book
    return out


def load_quotes(paths: Iterable[Path], kinds: tuple[str, ...]) -> list[dict]:
    """Book quotes captured BEFORE their own kickoff -- never one after."""
    out = []
    for path in paths:
        if not path.exists():
            continue
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if r.get("kind") not in kinds:
                    continue
                cap, ko = _ts(r.get("captured_at")), _ts(r.get("commence_time"))
                if cap is None or ko is None or cap >= ko:
                    continue
                out.append(r)
    return out


def consensus_fair(quotes: list[dict], *, side_a: str, side_b: str, line_key) -> dict[str, Any] | None:
    """Each book's LATEST pregame pair at one line -> proportional de-vig; the
    line quoted by the most books wins; fair = mean over those books."""
    latest: dict[tuple, dict] = {}
    for q in quotes:
        key = (q.get("bookmaker"), q.get("selection"), line_key(q))
        if key[2] is None and q.get("market") != "h2h":
            continue
        if key not in latest or q["captured_at"] > latest[key]["captured_at"]:
            latest[key] = q
    by_line: dict[Any, list[float]] = defaultdict(list)
    books = {k[0] for k in latest}
    for book in books:
        lines = {k[2] for k in latest if k[0] == book}
        for ln in lines:
            a, b = latest.get((book, side_a, ln)), latest.get((book, side_b, ln))
            if a and b:
                fair = devig_two_way(a.get("price"), b.get("price"))
                if fair is not None:
                    by_line[ln].append(fair)
    if not by_line:
        return None
    line = max(by_line, key=lambda ln: (len(by_line[ln]), -abs(ln or 0)))
    return {"line": line, "fair_a": statistics.fmean(by_line[line]), "books": len(by_line[line])}


def oddsapi_game_books(quotes: list[dict]) -> dict[tuple[str, str, str], dict[str, Any]]:
    """{(event_id, market, segment): consensus} for h2h / spreads / totals.

    Spreads are keyed on the HOME line h (home covers when margin + h > 0, i.e.
    margin > -h = the board's away-frame line)."""
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for q in quotes:
        if q.get("market") in ("h2h", "spreads", "totals"):
            groups[(q["event_id"], q["market"], q.get("segment") or "full")].append(q)
    out = {}
    for key, qs in groups.items():
        market = key[1]
        if market == "totals":
            res = consensus_fair(qs, side_a="over", side_b="under", line_key=lambda q: _f(q.get("line")))
        elif market == "spreads":
            # pair home line h with away line -h
            norm_qs = [dict(q, _pair=(_f(q.get("line")) if q.get("selection") == "home" else
                                      (-_f(q.get("line")) if _f(q.get("line")) is not None else None))) for q in qs]
            res = consensus_fair(norm_qs, side_a="home", side_b="away", line_key=lambda q: q.get("_pair"))
        else:
            res = consensus_fair(qs, side_a="home", side_b="away", line_key=lambda q: None)
        if res:
            first = qs[0]
            res.update({"home_team": first.get("home_team"), "away_team": first.get("away_team"),
                        "commence_time": first.get("commence_time")})
            out[key] = res
    return out


def match_event(games: list[dict], home: str, away: str, commence: str) -> tuple[dict | None, bool]:
    """OddsAPI event -> CFBD game via the board's own resolver; (game, flipped)."""
    from syndicate.features.ncaaf.oddsapi_lines import resolve_team

    gen = _gen()
    h, a = resolve_team(home), resolve_team(away)
    if not h or not a:
        return None, False
    h, a = gen.norm(h), gen.norm(a)
    ko = _ts(commence)
    for g in games:
        gh, ga = gen.norm(g["homeTeam"]), gen.norm(g["awayTeam"])
        start = _ts(g.get("startDate"))
        if ko and start and abs((start - ko).total_seconds()) > 36 * 3600:
            continue
        if (gh, ga) == (h, a):
            return g, False
        if (gh, ga) == (a, h):
            return g, True
    return None, False


# ---------------------------------------------------------------------------
# SIM (the production generator, unmodified)
# ---------------------------------------------------------------------------


def _sim_task(task: dict) -> dict:
    _lower_priority()
    gen = _gen()
    from syndicate.features.shared.football_segment_distributions import FootballSegmentAccumulator

    acc = FootballSegmentAccumulator()
    t0 = time.time()
    p = gen.build_projection(
        season=task["season"], week=task["week"], home_team=task["home"], away_team=task["away"],
        game_id=str(task["game_id"]), ppa_index={}, rating_source=task["rating_source"], seeds=SEEDS,
        sp_index=task["index"], sp_means=tuple(task["means"]), segment_accumulator=acc,
    )
    payload = acc.payload() or {}
    segs = {}
    for seg, block in (payload.get("segments") or {}).items():
        segs[seg] = {k: block.get(k) for k in ("home_points_mean", "away_points_mean", "total_points_dist",
                                               "margin_dist", "h2_regulation_only")}
    return {"arm": task["arm"], "game_id": task["game_id"], "season": task["season"], "week": task["week"],
            "margin_mean": p.margin_mean, "total_mean": p.total_mean, "margin_stdev": p.margin_stdev,
            "total_stdev": p.total_stdev, "home_win_rate": p.home_win_rate, "segments": segs,
            "segment_payload_meta": {k: payload.get(k) for k in ("distribution_version", "sims", "skipped_sims", "overtime_sims")},
            "seconds": round(time.time() - t0, 1)}


def _lower_priority() -> None:
    """The production fleet shares this machine: run at IDLE priority so it
    always preempts the backtest."""
    try:
        import psutil

        proc = psutil.Process()
        if os.name == "nt":
            proc.nice(psutil.IDLE_PRIORITY_CLASS)
        else:
            proc.nice(19)
    except Exception:  # noqa: BLE001
        pass


def _blend_2025_by_week(work: Path, games: list[dict]) -> dict[int, dict[str, tuple[float, float]]]:
    gen = _gen()
    prior = dict(gen._read_sp_cache(_src(work) / "historical_truth" / "sp_ratings_2024.json"))
    out = {}
    for week in L25_WEEKS:
        games_by_id = {int(g["id"]): g for g in games if int(g.get("week") or 0) < week and is_final(g)}
        rows = []
        for wk in range(1, week):
            rows.extend(_read_json(work / "cache" / f"ppa_games_2025_wk{wk:02d}.json"))
        index, _counts = gen.inseason_blend_index(prior, rows, games_by_id, beta=BLEND_BETA_ASOF_2025)
        out[week] = index
    return out


def _snapshot_blend_index(path: Path, week: int) -> dict[str, tuple[float, float]]:
    doc = _read_json(path)
    entry = (doc.get("weeks") or {}).get(str(week)) or {}
    return {team: (float(v[0]), float(v[1])) for team, v in (entry.get("teams") or {}).items()}


def l26_csv_rows(week: int) -> list[dict]:
    path = Path(fr"C:\tmp\ncaaf_677_snapshots\wk{week}\ncaaf_source__data__smartsim2_projections_2026_wk{week}.csv")
    with path.open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def build_tasks(work: Path, arm: str) -> list[dict]:
    gen = _gen()
    assert gen.SEEDS_PER_GAME == SEEDS, f"production seeds {gen.SEEDS_PER_GAME} != {SEEDS}"
    tasks = []
    if arm == "L25":
        games = load_games(work, 2025)
        prior = dict(gen._read_sp_cache(_src(work) / "historical_truth" / "sp_ratings_2024.json"))
        by_week = _blend_2025_by_week(work, games)
        for g in games:
            wk = int(g.get("week") or 0)
            if wk not in L25_WEEKS or not is_final(g):
                continue
            if g.get("homeClassification") != "fbs" or g.get("awayClassification") != "fbs":
                continue
            h, a = gen.norm(g["homeTeam"]), gen.norm(g["awayTeam"])
            if h not in prior or a not in prior:
                continue  # production would borrow current SP+ here; no as-of copy exists
            index = by_week[wk]
            means = gen.sp_league_means(index)
            tasks.append({"arm": arm, "season": 2025, "week": wk, "game_id": int(g["id"]),
                          "home": g["homeTeam"], "away": g["awayTeam"], "means": list(means),
                          "index": {h: index[h], a: index[a]},
                          "rating_source": f"asof_blend_ppa_2025_wk{wk}"})
    elif arm in ("L26", "L26C"):
        weeks = (3, 4) if arm == "L26" else (5,)
        for week in weeks:
            if arm == "L26":
                blend = _snapshot_blend_index(Path(fr"C:\tmp\ncaaf_677_snapshots\wk{week}\ncaaf_source__historical_truth__sp_ratings_inseason_blend_2026.json"), week)
                pairs = [(int(r["game_id"]), r["home_team"], r["away_team"]) for r in l26_csv_rows(week)]
            else:
                blend = _snapshot_blend_index(_src(work) / "historical_truth" / "sp_ratings_inseason_blend_2026.json", week)
                pairs = []
                for g in load_games(work, 2026):
                    ko = _ts(g.get("startDate"))
                    if int(g.get("week") or 0) == 5 and ko and ko < datetime(2026, 10, 2, 6, tzinfo=timezone.utc):
                        pairs.append((int(g["id"]), g["homeTeam"], g["awayTeam"]))
            means = gen.sp_league_means(blend)
            for gid, home, away in pairs:
                h, a = gen.norm(home), gen.norm(away)
                if h not in blend or a not in blend:
                    continue
                tasks.append({"arm": arm, "season": 2026, "week": week, "game_id": gid, "home": home, "away": away,
                              "means": list(means), "index": {h: blend[h], a: blend[a]},
                              "rating_source": f"snapshot_blend_2026_wk{week}"})
    return tasks


def cmd_sim(args) -> None:
    work = args.work
    configure_env(work)
    out_path = work / f"sim_{args.arm}.jsonl"
    done = set()
    if out_path.exists():
        for line in out_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                done.add(json.loads(line)["game_id"])
    tasks = [t for t in build_tasks(work, args.arm) if t["game_id"] not in done]
    if args.limit:
        tasks = tasks[: args.limit]
    print(f"{args.arm}: {len(tasks)} games to simulate ({len(done)} cached), {args.workers} workers, idle priority", flush=True)
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=args.workers, initializer=configure_env, initargs=(work,)) as pool, \
            out_path.open("a", encoding="utf-8") as handle:
        futures = [pool.submit(_sim_task, t) for t in tasks]
        for i, fut in enumerate(as_completed(futures), 1):
            handle.write(json.dumps(fut.result()) + "\n")
            handle.flush()
            if i % 10 == 0 or i == len(futures):
                print(f"  {i}/{len(futures)}  {time.time() - t0:.0f}s", flush=True)


# ---------------------------------------------------------------------------
# SCORE: GAME LINES
# ---------------------------------------------------------------------------


def _read_sims(work: Path, arm: str) -> dict[int, dict]:
    path = work / f"sim_{arm}.jsonl"
    if not path.exists():
        return {}
    return {json.loads(l)["game_id"]: json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()}


def _seg_prob(block: dict, market: str, seg: str, line: float | None, home_name: str) -> float | None:
    from syndicate.features.ncaaf.segment_projections import segment_projection

    proj = segment_projection({"line": line, "home_team": home_name}, market=market, segment=seg,
                              block={"segments": {seg: block}})
    return None if proj is None else proj.get("model_prob_over")


def score_lines(work: Path, report: dict) -> None:
    from syndicate.features.ncaaf.game_projections import _normal_prob_above

    gen = _gen()
    cells: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))

    def add_point(arm: str, market: str, gid: Any, model: float, naive: float | None, book: float | None, actual: float):
        c = cells[f"{arm}|{market}"]
        c["model_err"].append((str(gid), abs(model - actual)))
        c["model_bias"].append((str(gid), model - actual))
        if naive is not None:
            c["d_naive"].append((str(gid), abs(model - actual) - abs(naive - actual)))
            c["naive_err"].append((str(gid), abs(naive - actual)))
        if book is not None:
            c["d_book"].append((str(gid), abs(model - actual) - abs(book - actual)))
            c["book_err"].append((str(gid), abs(book - actual)))

    def add_prob(arm: str, market: str, gid: Any, p_model: float | None, p_book: float | None, y: int | None):
        if p_model is None or p_book is None or y is None:
            cells[f"{arm}|{market}"]["prob_skipped"].append((str(gid), 1.0))
            return
        c = cells[f"{arm}|{market}"]
        c["brier_model"].append((str(gid), brier(p_model, y)))
        c["brier_book"].append((str(gid), brier(p_book, y)))
        c["d_brier"].append((str(gid), brier(p_model, y) - brier(p_book, y)))
        c["d_logloss"].append((str(gid), logloss(p_model, y) - logloss(p_book, y)))

    coverage: dict[str, Any] = {}

    # ---- L25 ---------------------------------------------------------------
    games25 = load_games(work, 2025)
    sims25 = _read_sims(work, "L25")
    lines25 = load_cfbd_lines_2025()
    naive_by_week = {wk: naive_baseline(games25, wk) for wk in L25_WEEKS}
    cand = [g for g in games25 if int(g.get("week") or 0) in L25_WEEKS and is_final(g)
            and g.get("homeClassification") == "fbs" and g.get("awayClassification") == "fbs"]
    drops = Counter()
    used = 0
    for g in cand:
        gid = int(g["id"])
        sim = sims25.get(gid)
        if sim is None:
            drops["no_sim(unrated_or_not_run)"] += 1
            continue
        used += 1
        _score_game(g, sim, naive_by_week[int(g["week"])], lines25.get(gid), None, "L25", add_point, add_prob,
                    _normal_prob_above, gen, drops)
    coverage["L25"] = {"fbs_vs_fbs_wk3_15_final": len(cand), "simulated": len(sims25), "scored": used,
                       "with_cfbd_close": sum(1 for g in cand if int(g["id"]) in lines25 and int(g["id"]) in sims25),
                       "dropped": dict(drops)}

    # ---- L26 (production CSVs) + L26C --------------------------------------
    games26 = load_games(work, 2026)
    g26 = {int(g["id"]): g for g in games26}
    sims26 = _read_sims(work, "L26")
    sims26c = _read_sims(work, "L26C")
    dk26: dict[int, dict] = {}
    for wk in (3, 4):
        for row in _read_json(Path(fr"C:\tmp\ncaaf_677_snapshots\grade\cfbd_lines_wk{wk}.json")):
            b = cfbd_book(row)
            if b:
                dk26[int(row["id"])] = b
        for row in _read_json(Path(fr"C:\tmp\ncaaf_677_snapshots\grade\cfbd_games_wk{wk}.json")):
            g26.setdefault(int(row["id"]), row)
    quotes = load_quotes([Path(r"C:\tmp\bq_ncaaf_2026-09-24.jsonl"), Path(r"C:\tmp\bq_ncaaf_2026-09-26.jsonl")], ("game",))
    oa_wk4 = oddsapi_game_books(quotes)
    quotes_c = load_quotes([_src(work) / "tracking" / "book_quotes" / "2026-10-01.jsonl"], ("game",))
    oa_c = oddsapi_game_books(quotes_c)
    oa_by_game: dict[int, dict[tuple[str, str], tuple[dict, bool]]] = defaultdict(dict)
    unmatched = Counter()
    for source_name, books in (("wk4_render", oa_wk4), ("fleet_1001", oa_c)):
        for (eid, market, seg), res in books.items():
            g, flipped = match_event(list(g26.values()), res["home_team"], res["away_team"], res["commence_time"])
            if g is None:
                unmatched[source_name] += 1
                continue
            oa_by_game[int(g["id"])][(market, seg)] = (res, flipped)
    drops = Counter()
    used = 0
    for wk in (3, 4):
        for r in l26_csv_rows(wk):
            gid = int(r["game_id"])
            g = g26.get(gid)
            if g is None or not is_final(g):
                drops["no_final"] += 1
                continue
            ko, gen_at = _ts(g.get("startDate")), _ts(r.get("generated_at"))
            if ko and gen_at and gen_at >= ko:
                drops["row_generated_after_kickoff"] += 1
                continue
            sim = {"margin_mean": _f(r["margin_mean"]), "total_mean": _f(r["total_mean"]),
                   "margin_stdev": _f(r["margin_stdev"]), "total_stdev": _f(r["total_stdev"]),
                   "home_win_rate": _f(r["home_win_rate"]), "segments": (sims26.get(gid) or {}).get("segments") or {}}
            # the rebuild must BE production for its segments to stand for production's
            rb = sims26.get(gid)
            if rb is not None:
                same = abs(rb["margin_mean"] - sim["margin_mean"]) < 0.05 and abs(rb["total_mean"] - sim["total_mean"]) < 0.05
                drops["rebuild_matches_csv" if same else "rebuild_DIFFERS_from_csv(segments dropped)"] += 1
                if not same:
                    sim["segments"] = {}
            used += 1
            _score_game(g, sim, naive_baseline(games26, wk), dk26.get(gid), oa_by_game.get(gid), "L26", add_point,
                        add_prob, _normal_prob_above, gen, drops)
    coverage["L26"] = {"csv_rows": sum(len(l26_csv_rows(w)) for w in (3, 4)), "scored": used, "dropped": dict(drops),
                       "oddsapi_events_unmatched": dict(unmatched),
                       "games_with_oddsapi_quotes": len(oa_by_game)}
    drops = Counter()
    used = 0
    for gid, sim in sims26c.items():
        g = g26.get(gid)
        if g is None or not is_final(g):
            drops["no_final"] += 1
            continue
        used += 1
        _score_game(g, sim, naive_baseline(games26, 5), None, oa_by_game.get(gid), "L26C", add_point, add_prob,
                    _normal_prob_above, gen, drops)
    coverage["L26C"] = {"simulated": len(sims26c), "scored": used, "dropped": dict(drops)}

    report["lines_coverage"] = coverage
    report["lines"] = _summarise(cells)


def _score_game(g, sim, naive_base, cfbd, oddsapi, arm, add_point, add_prob, normal_above, gen, drops) -> None:
    gid = int(g["id"])
    hp, ap = float(g["homePoints"]), float(g["awayPoints"])
    margin, total = hp - ap, hp + ap
    nv = naive_game(naive_base, gen.norm(g["homeTeam"]), gen.norm(g["awayTeam"]), bool(g.get("neutralSite")))
    if nv is None:
        drops["naive_unavailable(<2 games)"] += 1
    book_margin = -cfbd["spread"] if cfbd and cfbd.get("spread") is not None else None
    book_total = cfbd.get("total") if cfbd else None
    add_point(arm, "margin", gid, sim["margin_mean"], nv and nv["margin"], book_margin, margin)
    add_point(arm, "total", gid, sim["total_mean"], nv and nv["total"], book_total, total)
    # probabilities vs the CFBD close (no prices -> 0.5 at its own line)
    if cfbd and cfbd.get("spread") is not None:
        line = -cfbd["spread"]
        y = None if margin == line else int(margin > line)
        add_prob(arm, "spread_cover@close(book=0.5)", gid, normal_above(line, sim["margin_mean"], sim["margin_stdev"]),
                 0.5 if y is not None else None, y)
    if book_total is not None:
        y = None if total == book_total else int(total > book_total)
        add_prob(arm, "total_over@close(book=0.5)", gid, normal_above(book_total, sim["total_mean"], sim["total_stdev"]),
                 0.5 if y is not None else None, y)
    if cfbd and cfbd.get("ml_home_fair") is not None and margin != 0:
        add_prob(arm, "h2h(cfbd_devig)", gid, sim["home_win_rate"], cfbd["ml_home_fair"], int(margin > 0))
    # OddsAPI two-sided quotes: real de-vig, full game and segments
    ls = line_scores(g)
    for (market, seg), (res, flipped) in (oddsapi or {}).items():
        if seg == "full":
            seg_margin, seg_total = margin, total
            mm, ms, tm, ts_ = sim["margin_mean"], sim["margin_stdev"], sim["total_mean"], sim["total_stdev"]
        else:
            if not ls or seg not in ls:
                drops[f"no_line_scores_{seg}"] += 1
                continue
            seg_margin, seg_total = ls[seg][0] - ls[seg][1], ls[seg][0] + ls[seg][1]
        fair_a = res["fair_a"]
        if market == "totals":
            ln = res["line"]
            if seg == "full":
                p = normal_above(ln, tm, ts_)
            else:
                blk = (sim.get("segments") or {}).get(seg)
                p = _seg_prob(blk, "totals", seg, ln, g["homeTeam"]) if blk else None
            y = None if seg_total == ln else int(seg_total > ln)
            add_prob(arm, f"total_over/{seg}(oddsapi)", gid, p, fair_a, y)
        elif market == "spreads":
            h_line = res["line"]  # OddsAPI home's line
            if flipped:  # the quote's home is CFBD's away
                h_line, fair_a = -h_line, 1.0 - fair_a
            board_line = -h_line  # home covers when margin > -h
            if seg == "full":
                p = normal_above(board_line, mm, ms)
            else:
                blk = (sim.get("segments") or {}).get(seg)
                p = _seg_prob(blk, "spreads", seg, board_line, g["homeTeam"]) if blk else None
            y = None if seg_margin == board_line else int(seg_margin > board_line)
            add_prob(arm, f"spread_cover/{seg}(oddsapi)", gid, p, fair_a, y)
        else:
            if flipped:
                fair_a = 1.0 - fair_a
            if seg == "full":
                p = sim["home_win_rate"]
            else:
                blk = (sim.get("segments") or {}).get(seg)
                p = _seg_prob(blk, "h2h", seg, None, g["homeTeam"]) if blk else None
            y = None if seg_margin == 0 else int(seg_margin > 0)
            add_prob(arm, f"h2h/{seg}(oddsapi)", gid, p, fair_a, y)
    # segment POINT accuracy vs the naive share baseline (no book in L25/L26)
    if ls:
        for seg in SEGMENTS:
            blk = (sim.get("segments") or {}).get(seg)
            if not blk or blk.get("home_points_mean") is None:
                continue
            m_h, m_a = float(blk["home_points_mean"]), float(blk["away_points_mean"])
            nseg = (nv or {}).get("segments", {}).get(seg) if nv else None
            add_point(arm, f"seg_margin/{seg}", gid, m_h - m_a, nseg and nseg["margin"], None, ls[seg][0] - ls[seg][1])
            add_point(arm, f"seg_total/{seg}", gid, m_h + m_a, nseg and nseg["total"], None, ls[seg][0] + ls[seg][1])


def _summarise(cells: dict) -> dict:
    out = {}
    for key, c in sorted(cells.items()):
        row: dict[str, Any] = {}
        if c.get("model_err"):
            row["n"] = len(c["model_err"])
            row["mae_model"] = statistics.fmean(v for _, v in c["model_err"])
            row["bias_model"] = statistics.fmean(v for _, v in c["model_bias"])
            if c.get("naive_err"):
                row["mae_naive"] = statistics.fmean(v for _, v in c["naive_err"])
                row["dmae_vs_naive"] = cluster_boot(c["d_naive"])
                row["verdict_vs_naive"] = verdict(row["dmae_vs_naive"])
            if c.get("book_err"):
                row["mae_book"] = statistics.fmean(v for _, v in c["book_err"])
                row["dmae_vs_book"] = cluster_boot(c["d_book"])
                row["verdict_vs_book"] = verdict(row["dmae_vs_book"])
        if c.get("brier_model"):
            row["n_prob"] = len(c["brier_model"])
            row["brier_model"] = statistics.fmean(v for _, v in c["brier_model"])
            row["brier_book"] = statistics.fmean(v for _, v in c["brier_book"])
            row["dbrier_vs_book"] = cluster_boot(c["d_brier"])
            row["dlogloss_vs_book"] = cluster_boot(c["d_logloss"])
            row["verdict_vs_book"] = verdict(row["dbrier_vs_book"])
        if c.get("prob_skipped"):
            row["prob_skipped"] = len(c["prob_skipped"])
        out[key] = row
    return out


# ---------------------------------------------------------------------------
# SCORE: PROPS
# ---------------------------------------------------------------------------


def _actual_rows(snapshot: Path) -> dict[tuple[int, int, str], list[dict]]:
    out: dict[tuple[int, int, str], list[dict]] = defaultdict(list)
    with snapshot.open(encoding="utf-8-sig", newline="") as handle:
        for r in csv.DictReader(handle):
            try:
                out[(int(r["season"]), int(r["week"]), str(r["player_id"]))].append(r)
            except (KeyError, ValueError):
                continue
    return out


def _anytime_td_asof(rows: dict, season: int, week: int) -> dict[str, float]:
    """`prop_model`'s rate, as-of: shrunk Poisson P(>=1) over weeks < N."""
    from syndicate.features.ncaaf.prop_model import MIN_PRIOR_GAMES, SHRINK_GAMES

    games: Counter = Counter()
    tds: Counter = Counter()
    for (s, w, pid), rs in rows.items():
        if s == season and w < week:
            games[pid] += len(rs)
            tds[pid] += sum(_f(r.get("anytime_td")) or 0.0 for r in rs)
    league = sum(tds.values()) / max(1, sum(games.values()))
    out = {}
    for pid, g in games.items():
        if g >= MIN_PRIOR_GAMES:
            shrunk = (tds[pid] + SHRINK_GAMES * league) / (g + SHRINK_GAMES)
            out[pid] = 1.0 - math.exp(-max(0.0, shrunk))
    return out


def score_props(work: Path, report: dict) -> None:
    from syndicate.features.ncaaf.prop_projections import (
        find_player, index_from_payload, payload_from_players, prob_over, read_snapshot_players,
    )

    snapshot = _snapshot_path(work)
    players = read_snapshot_players(snapshot, (2024, 2025, 2026))
    actual = _actual_rows(snapshot)
    cells: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    coverage: dict[str, Any] = {"snapshot_rows_by_season_week": {}}
    sw = Counter((s, w) for (s, w, _), rs in actual.items() for _ in rs)
    coverage["snapshot_rows_by_season_week"] = {f"{s}_wk{w}": n for (s, w), n in sorted(sw.items())}

    # ---- P25: point accuracy vs the player's own as-of mean -----------------
    refused = Counter()
    td_by_player_2025: dict[str, list[tuple[int, float]]] = defaultdict(list)
    for (s, w, pid), rs in actual.items():
        if s == 2025:
            td_by_player_2025[pid].extend((w, _f(r.get("anytime_td")) or 0.0) for r in rs)
    for week in range(2, 17):
        payload = payload_from_players(season=2025, week=week, current=players.get(2025, {}),
                                       previous=players.get(2024, {}), snapshot_name=snapshot.name)
        for k, v in payload["refusals"].items():
            refused[k] += v
        for p in payload["players"]:
            rows = actual.get((2025, week, str(p["player_id"])))
            if not rows:
                refused["no_week_n_line(did_not_play_or_no_stat)"] += 1
                continue
            if len(rows) > 1:
                refused["two_games_in_week"] += 1
                continue
            row = rows[0]
            gid = str(row.get("game_id"))
            for label, (col, key) in PROP_MARKETS.items():
                entry = (p.get("markets") or {}).get(key) if key else None
                if entry is None:
                    continue
                y = _f(row.get(col)) or 0.0
                mean, base = float(entry["mean"]), float(entry["season_mean"])
                c = cells[f"P25|{label}"]
                c["model_err"].append((gid, abs(mean - y)))
                c["model_bias"].append((gid, mean - y))
                c["naive_err"].append((gid, abs(base - y)))
                c["d_naive"].append((gid, abs(mean - y) - abs(base - y)))
                # calibration at a proxy line (floor of the baseline + 0.5), model vs the
                # SAME distribution re-centred on the baseline: no book exists for 2025
                line = math.floor(base) + 0.5
                pm = prob_over(entry, line)
                pb = prob_over(dict(entry, mean=base), line)
                if pm is not None and pb is not None:
                    yy = int(y > line)
                    c["brier_model"].append((gid, brier(pm, yy)))
                    c["brier_book"].append((gid, brier(pb, yy)))  # "book" column = the baseline here
                    c["d_brier"].append((gid, brier(pm, yy) - brier(pb, yy)))
                    c["d_logloss"].append((gid, logloss(pm, yy) - logloss(pb, yy)))
        # Anytime TD, as-of
        rates = _anytime_td_asof(actual, 2025, week)
        td_hist = td_by_player_2025
        for (s, w, pid), rows in actual.items():
            if s != 2025 or w != week or pid not in rates or len(rows) != 1:
                continue
            y = int((_f(rows[0].get("anytime_td")) or 0.0) > 0)
            c = cells["P25|Anytime TD"]
            gid = str(rows[0].get("game_id"))
            c["brier_model"].append((gid, brier(rates[pid], y)))
            # baseline: the player's own raw as-of TD frequency (P(>=1) from his raw rate)
            prior_tds = [td for w2, td in td_hist.get(pid, ()) if w2 < week]
            raw = sum(prior_tds) / max(1, len(prior_tds))
            pb = min(0.99, max(0.01, 1.0 - math.exp(-raw)))
            c["brier_book"].append((gid, brier(pb, y)))
            c["d_brier"].append((gid, brier(rates[pid], y) - brier(pb, y)))
            c["d_logloss"].append((gid, logloss(rates[pid], y) - logloss(pb, y)))
    coverage["P25_refusals"] = dict(refused)

    # ---- P26: vs the de-vigged book -----------------------------------------
    games26 = load_games(work, 2026)
    quote_sets = {
        4: [Path(r"C:\tmp\bq_ncaaf_2026-09-24.jsonl"), Path(r"C:\tmp\bq_ncaaf_2026-09-26.jsonl")],
        5: [_src(work) / "tracking" / "book_quotes" / "2026-10-01.jsonl"],
    }
    p26 = Counter()
    for week, paths in quote_sets.items():
        payload = payload_from_players(season=2026, week=week, current=players.get(2026, {}),
                                       previous=players.get(2025, {}), snapshot_name=snapshot.name)
        index = index_from_payload(payload)
        weeks_used = payload["input"]["weeks_used"]
        coverage[f"P26_wk{week}_model_input_weeks"] = weeks_used
        quotes = load_quotes(paths, ("prop",))
        p26[f"wk{week}_prop_quotes_pregame"] += len(quotes)
        groups: dict[tuple, list[dict]] = defaultdict(list)
        for q in quotes:
            groups[(q["event_id"], q.get("market"), q.get("player_name"))].append(q)
        for (eid, label, name), qs in groups.items():
            if label not in PROP_MARKETS:
                p26["unsupported_market"] += 1
                continue
            if label == "Anytime TD" or not any(q.get("selection") == "under" for q in qs):
                p26[f"one_sided_excluded/{label}"] += 1
                continue
            res = consensus_fair(qs, side_a="over", side_b="under", line_key=lambda q: _f(q.get("line")))
            if res is None:
                p26["no_two_sided_pair"] += 1
                continue
            g, _flipped = match_event(games26, qs[0]["home_team"], qs[0]["away_team"], qs[0]["commence_time"])
            if g is None:
                p26["event_unmatched"] += 1
                continue
            if not is_final(g):
                p26["game_not_final"] += 1
                continue
            player, reason = find_player(index, name, (g["homeTeam"], g["awayTeam"]))
            if player is None:
                p26[f"player:{reason}"] += 1
                continue
            col, key = PROP_MARKETS[label]
            entry = (player.get("markets") or {}).get(key)
            if entry is None:
                p26["no_market_projection"] += 1
                continue
            rows = [r for r in actual.get((2026, week, str(player["player_id"])), []) if str(r.get("game_id")) == str(g["id"])]
            if not rows:
                p26["no_actual_line(did_not_play_or_no_stat)"] += 1
                continue
            y_val = _f(rows[0].get(col)) or 0.0
            line = res["line"]
            if y_val == line:
                p26["push"] += 1
                continue
            y = int(y_val > line)
            pm = prob_over(entry, line)
            if pm is None:
                p26["no_model_probability"] += 1
                continue
            gid = str(g["id"])
            arm = f"P26|{label}"
            c = cells[arm]
            c["brier_model"].append((gid, brier(pm, y)))
            c["brier_book"].append((gid, brier(res["fair_a"], y)))
            c["d_brier"].append((gid, brier(pm, y) - brier(res["fair_a"], y)))
            c["d_logloss"].append((gid, logloss(pm, y) - logloss(res["fair_a"], y)))
            mean, base = float(entry["mean"]), float(entry["season_mean"])
            c["model_err"].append((gid, abs(mean - y_val)))
            c["model_bias"].append((gid, mean - y_val))
            c["naive_err"].append((gid, abs(base - y_val)))
            c["d_naive"].append((gid, abs(mean - y_val) - abs(base - y_val)))
            c["book_err"].append((gid, abs(line - y_val)))  # the book's LINE as its point estimate
            c["d_book"].append((gid, abs(mean - y_val) - abs(line - y_val)))
            p26["scored"] += 1
    coverage["P26"] = dict(p26)
    report["props_coverage"] = coverage
    report["props"] = _summarise(cells)


# ---------------------------------------------------------------------------
# COVERAGE (families, dates, intersection)
# ---------------------------------------------------------------------------


def family_coverage(work: Path) -> dict[str, Any]:
    out: dict[str, Any] = {}
    g25, g26 = load_games(work, 2025), load_games(work, 2026)
    out["final_scores"] = {
        "2025_weeks": sorted({int(g["week"]) for g in g25 if is_final(g)}),
        "2026_weeks": sorted({int(g["week"]) for g in g26 if is_final(g)}),
        "2026_final_games": sum(1 for g in g26 if is_final(g)),
        "source": "fleet historical_truth/games_<S>.json.gz (+ CFBD /games 2026 wk5 fetched)",
    }
    lines25 = load_cfbd_lines_2025()
    out["cfbd_close_2025"] = {"games": len(lines25),
                              "weeks": sorted({int(g["week"]) for g in g25 if int(g["id"]) in lines25}),
                              "source": "checkout data/ncaaf_source/data/cfbd_lines_wk*.json (CFBD history)"}
    out["ppa_games_2025_cache_weeks"] = sorted(int(p.stem[-2:]) for p in (work / "cache").glob("ppa_games_2025_wk*.json"))
    out["projections_2026_pregame"] = {f"wk{w}": len(l26_csv_rows(w)) for w in (3, 4)}
    out["projections_2026_pregame"]["source"] = "C:/tmp/ncaaf_677_snapshots (production CSVs, sha256-checked 2026-09-28)"
    for name in ("L25", "L26", "L26C"):
        out[f"sims_{name}"] = len(_read_sims(work, name))
    rows = _actual_rows(_snapshot_path(work))
    out["player_game_stats_weeks"] = sorted({f"{s}_wk{w}" for (s, w, _) in rows})
    for name, paths in (("odds_render_wk4", [Path(r"C:\tmp\bq_ncaaf_2026-09-24.jsonl"), Path(r"C:\tmp\bq_ncaaf_2026-09-26.jsonl")]),
                        ("odds_fleet_1001", [_src(work) / "tracking" / "book_quotes" / "2026-10-01.jsonl"])):
        qs = load_quotes(paths, ("game", "prop"))
        out[name] = {"pregame_quotes": len(qs),
                     "kickoff_dates": sorted({str(q.get("commence_time"))[:10] for q in qs}),
                     "captured_range": [min((q["captured_at"] for q in qs), default=None), max((q["captured_at"] for q in qs), default=None)],
                     "markets": dict(Counter(f"{q.get('kind')}/{q.get('market')}/{q.get('segment')}" for q in qs).most_common(16)) if qs else {}}
    return out


def cmd_score(args) -> None:
    work = args.work
    configure_env(work)
    report: dict[str, Any] = {"generated_at": datetime.now(timezone.utc).isoformat(), "seeds": SEEDS,
                              "blend_beta_2025": BLEND_BETA_ASOF_2025, "bootstrap_reps": BOOT_REPS}
    report["family_coverage"] = family_coverage(work)
    if not args.props_only:
        score_lines(work, report)
    if not args.lines_only:
        score_props(work, report)
    out = work / "report.json"
    out.write_text(json.dumps(report, indent=1, default=str), encoding="utf-8")
    print_report(report)
    print(f"\nwritten {out}")


def _ci(ci: dict | None) -> str:
    if not ci or ci.get("mean") is None:
        return "-"
    return f"{ci['mean']:+.4f} [{ci['lo']:+.4f}, {ci['hi']:+.4f}] g={ci['games']}"


def print_report(report: dict) -> None:
    print(json.dumps({"family_coverage": report.get("family_coverage"),
                      "lines_coverage": report.get("lines_coverage"),
                      "props_coverage": report.get("props_coverage")}, indent=1, default=str))
    for section in ("lines", "props"):
        print(f"\n=== {section.upper()} ===")
        for key, row in (report.get(section) or {}).items():
            parts = [f"{key:42s}"]
            if "n" in row:
                parts.append(f"n={row['n']:>5} MAE m={row['mae_model']:.3f}")
                if "mae_naive" in row:
                    parts.append(f"naive={row['mae_naive']:.3f} dN={_ci(row['dmae_vs_naive'])} {row['verdict_vs_naive']}")
                if "mae_book" in row:
                    parts.append(f"book={row['mae_book']:.3f} dB={_ci(row.get('dmae_vs_book'))}")
                parts.append(f"bias={row['bias_model']:+.3f}")
            if "n_prob" in row:
                parts.append(f"| prob n={row['n_prob']} Brier m={row['brier_model']:.4f} b={row['brier_book']:.4f} "
                             f"dBrier={_ci(row['dbrier_vs_book'])} dLL={_ci(row['dlogloss_vs_book'])} {row['verdict_vs_book']}")
            print("  ".join(parts))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("fetch", "sim", "score"):
        p = sub.add_parser(name)
        p.add_argument("--work", type=Path, required=True)
        if name == "sim":
            p.add_argument("--arm", choices=("L25", "L26", "L26C"), required=True)
            p.add_argument("--workers", type=int, default=4)
            p.add_argument("--limit", type=int, default=0)
        if name == "score":
            p.add_argument("--lines-only", action="store_true")
            p.add_argument("--props-only", action="store_true")
    args = parser.parse_args()
    {"fetch": cmd_fetch, "sim": cmd_sim, "score": cmd_score}[args.cmd](args)


if __name__ == "__main__":
    main()
