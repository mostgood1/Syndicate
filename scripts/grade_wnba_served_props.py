"""Grade one WNBA slate's SERVED props against the book and the outcome (pre-registered 2026-10-05, before the games).

Rows: player x market where the snapshot's OddsAPI capture has a two-sided line; the line is the modal line across
books, the book probability is the median over books of the proportionally de-vigged P(over) at that line (latest
snapshot per book). Served P(over) = the served sim ladder read with the board's own `_hit_prob_over`. Outcome from
production's boxscores_<D>.csv. Reports per market and pooled: n, Brier served / book, served - book, over-rate,
and the share of rows where the served side (P>0.5 -> over) matched the outcome. Also: players the availability rule
excluded for D who played. With one or two games this is a sanity check, not a skill verdict.

Usage (WSL, fleet venv): python grade_day.py <date> <snapshot_dir> <boxscores_csv>
"""
import csv
import json
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

F = Path.home() / "Syndicate"
sys.path.insert(0, str(F))
from syndicate.features.shared import wnba_sim_availability as A  # noqa: E402
from syndicate.features.shared.basketball_props_smart_sim import _norm_name_key  # noqa: E402
from syndicate.features.shared.wnba_projections import _hit_prob_over  # noqa: E402

MK = {"player_points": ("pts", ("PTS",)), "player_rebounds": ("reb", ("REB",)), "player_assists": ("ast", ("AST",)),
      "player_threes": ("threes", ("FG3M",)), "player_points_rebounds_assists": ("pra", ("PTS", "REB", "AST")),
      "player_points_rebounds": ("pr", ("PTS", "REB")), "player_points_assists": ("pa", ("PTS", "AST")),
      "player_rebounds_assists": ("ra", ("REB", "AST"))}


def implied(price):
    try:
        a = float(price)
    except (TypeError, ValueError):
        return None
    if a == 0:
        return None
    return 100.0 / (a + 100.0) if a > 0 else -a / (-a + 100.0)


def key(n):
    return _norm_name_key(n).upper()


def main(date, snap, box_csv):
    snap, box_csv = Path(snap), Path(box_csv)
    # book: latest snapshot per (book, player, market, line, side)
    latest = {}
    with (snap / f"oddsapi_player_props_{date}.csv").open(encoding="utf-8", errors="replace") as fh:
        for r in csv.DictReader(fh):
            if r["market"] not in MK:
                continue
            side = str(r["outcome_name"]).strip().lower()
            if side not in ("over", "under"):
                continue
            try:
                line = float(r["point"])
            except (TypeError, ValueError):
                continue
            k = (r["bookmaker"], key(r["player_name"]), r["market"], line, side)
            if k not in latest or r["snapshot_ts"] >= latest[k][0]:
                latest[k] = (r["snapshot_ts"], implied(r["price"]))
    lines = defaultdict(Counter)
    pair = defaultdict(dict)
    for (bk, pk, mk, line, side), (_ts, p) in latest.items():
        if p is not None:
            pair[(bk, pk, mk, line)][side] = p
    for (bk, pk, mk, line), sides in pair.items():
        if len(sides) == 2:
            lines[(pk, mk)][line] += 1
    book = {}
    for (pk, mk), c in lines.items():
        line = sorted(c.items(), key=lambda t: (-t[1], t[0]))[0][0]
        ps = [s["over"] / (s["over"] + s["under"]) for (bk, p2, m2, l2), s in pair.items()
              if p2 == pk and m2 == mk and l2 == line and len(s) == 2]
        if ps:
            book[(pk, mk)] = (line, statistics.median(ps), len(ps))
    # outcomes
    act = {}
    with box_csv.open(encoding="utf-8", errors="replace") as fh:
        for r in csv.DictReader(fh):
            try:
                if float(r.get("MIN") or 0) > 0:
                    act[key(r["PLAYER_NAME"])] = {c: float(r.get(c) or 0) for c in ("PTS", "REB", "AST", "FG3M", "MIN")}
            except ValueError:
                continue
    # served ladders
    rows = []
    pool = {}
    for f in sorted(snap.glob(f"smart_sim_{date}_*.json")):
        d = json.loads(f.read_text())
        for side in ("home", "away"):
            for p in d["players"][side]:
                pk = key(p["player_name"]); pool[pk] = (d[side], round(p.get("min_mean", 0), 1))
                for mk, (lk, cols) in MK.items():
                    b = book.get((pk, mk)); lad = (p.get("prop_ladders") or {}).get(lk)
                    if not b or not lad or pk not in act:
                        continue
                    line, pb, nb = b
                    y = sum(act[pk][c] for c in cols)
                    if y == line:
                        continue
                    ps = _hit_prob_over(lad["ladder"], line)
                    if ps is None:
                        continue
                    rows.append({"gid": f.name, "mk": mk, "ps": min(max(ps, 0.001), 0.999), "pb": pb, "o": int(y > line)})
    print(f"{date}: book lines {len(book)}, players played {len(act)}, served pool {len(pool)}, graded rows {len(rows)}")
    br = lambda p, o: (p - o) ** 2
    for mk in list(MK) + ["ALL"]:
        R = rows if mk == "ALL" else [r for r in rows if r["mk"] == mk]
        if not R:
            continue
        bs, bb = statistics.fmean(br(r["ps"], r["o"]) for r in R), statistics.fmean(br(r["pb"], r["o"]) for r in R)
        side = statistics.fmean(int((r["ps"] > 0.5) == bool(r["o"])) for r in R)
        print(f"  {mk:32s} n {len(R):3d}  Brier served {bs:.4f} book {bb:.4f}  served-book {bs - bb:+.4f}  "
              f"over-rate {statistics.fmean(r['o'] for r in R):.2f}  served side right {side:.2f}")
    # availability false exclusions
    rec = {}
    A.add_recency_exclusions(rec, processed_root=box_csv.parent, date_str=date, league_code="wnba", props_df=None,
                             name_key=_norm_name_key, env={A.FLAG: "1"})
    teams = {t for t, _m in pool.values()}
    false_ex = sorted((t, k, act[k]["MIN"]) for t in teams for k in rec.get(t, set()) if k in act)
    print(f"  availability: excluded on the slate's teams {sum(len(rec.get(t, ())) for t in teams)}; "
          f"excluded who PLAYED: {false_ex}")


if __name__ == "__main__":
    main(*sys.argv[1:4])
