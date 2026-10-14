"""Build dated, as-of NFL matchup-signal tables (lane `signal-engine-football`).

For every (season, week W) and every player with an appearance earlier that season: target / air-yards / carry /
pass-attempt shares (season, last 3, base, trend), the team's season-to-date pass rate over expected, and the "fresh
vacated" target and carry share -- the season-to-date shares of teammates listed OUT for week W who appeared in the
team's previous game. Everything reads weeks < W only. One table per week:
`<data root>/nfl_source/signals/<season>/wkNN.jsonl`.

SOURCES  nflverse play-by-play `nfl_source/tracking/nflverse/pbp/pbp_<season>.csv` (REG rows), nflverse injury
         reports `injuries_<season>.csv` (final game status; known before kickoff).

    python3 scripts/build_nfl_signals.py --data-root ~/syndicate-prod/data --seasons 2023,2024,2025 \\
        --injuries-dir ~/syndicate-prod/data/backfill/nfl_injuries_2009_25
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.shared.matchup_signals import write_signal_table  # noqa: E402
from syndicate.features.shared.matchup_signals_football import share_features, week_key  # noqa: E402

COUNTS = ("targets", "air_yards", "carries", "pass_att")


def _f(v: Any) -> float | None:
    try:
        return None if v in (None, "", "NA") else float(v)
    except (TypeError, ValueError):
        return None


def game_counts(plays: Iterable[Mapping[str, Any]]) -> tuple[dict, dict]:
    """(player_games, team_games) from REG play-by-play rows.

    player_games[(game_id, player_id)] = {week, team, targets, air_yards, carries, pass_att}
    team_games[(game_id, team)]        = {week, targets, air_yards, carries, pass_att, proe_sum, proe_n}
    Target = an official pass attempt (no sack, no two-point try) with a receiver. Carry = a rush attempt that is not
    a two-point try or a kneel. pass_oe is nflverse's per-play pass-over-expected (0-100 scale)."""
    players: dict[tuple[str, str], dict[str, Any]] = {}
    teams: dict[tuple[str, str], dict[str, Any]] = {}
    for p in plays:
        if p.get("season_type") not in (None, "", "REG"):
            continue
        game, team = p.get("game_id") or "", p.get("posteam") or ""
        try:
            week = int(p.get("week") or 0)
        except (TypeError, ValueError):
            continue
        if not game or not team or not week:
            continue
        t = teams.setdefault((game, team), {"week": week, **{c: 0.0 for c in COUNTS}, "proe_sum": 0.0, "proe_n": 0})
        two_pt, sack = p.get("two_point_attempt") == "1", p.get("sack") == "1"
        proe = _f(p.get("pass_oe"))
        if proe is not None and not two_pt:
            t["proe_sum"] += proe
            t["proe_n"] += 1

        def bump(pid: str, key: str, amount: float = 1.0) -> None:
            row = players.setdefault((game, pid), {"week": week, "team": team, **{c: 0.0 for c in COUNTS}})
            row[key] += amount

        if p.get("pass_attempt") == "1" and not sack and not two_pt:
            passer = p.get("passer_player_id") or ""
            if passer:
                t["pass_att"] += 1
                bump(passer, "pass_att")
            receiver = p.get("receiver_player_id") or ""
            if receiver:
                air = _f(p.get("air_yards")) or 0.0
                t["targets"] += 1
                t["air_yards"] += air
                bump(receiver, "targets")
                bump(receiver, "air_yards", air)
        if p.get("rush_attempt") == "1" and not two_pt and p.get("play_type") != "qb_kneel":
            rusher = p.get("rusher_player_id") or ""
            if rusher:
                t["carries"] += 1
                bump(rusher, "carries")
    return players, teams


def load_out(path: Path | None, season: int) -> dict[tuple[int, str], set[str]]:
    """(week, team) -> gsis ids with final report_status OUT for that REG week."""
    out: dict[tuple[int, str], set[str]] = defaultdict(set)
    if path is None or not path.is_file():
        return out
    with path.open(encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh):
            if str(r.get("season")) != str(season) or (r.get("game_type") or "REG") != "REG":
                continue
            if (r.get("report_status") or "").strip().lower() != "out" or not r.get("gsis_id"):
                continue
            try:
                out[(int(r["week"]), r.get("team") or "")].add(r["gsis_id"])
            except (TypeError, ValueError, KeyError):
                continue
    return out


def build_week(players: Mapping, teams: Mapping, out: Mapping[tuple[int, str], set[str]], week: int) -> list[dict[str, Any]]:
    """Rows for week `week` from games with week < `week` only."""
    by_player: dict[str, list[tuple[int, str, dict]]] = defaultdict(list)
    for (game, pid), row in players.items():
        if row["week"] < week:
            by_player[pid].append((row["week"], game, row))
    team_games: dict[str, list[tuple[int, str, dict]]] = defaultdict(list)
    for (game, team), row in teams.items():
        if row["week"] < week:
            team_games[team].append((row["week"], game, row))
    last_game = {team: max(g)[1] for team, g in team_games.items() if g}
    proe = {team: (round(sum(r["proe_sum"] for _, _, r in g) / sum(r["proe_n"] for _, _, r in g), 3)
                   if sum(r["proe_n"] for _, _, r in g) else None) for team, g in team_games.items()}
    rows: dict[str, dict[str, Any]] = {}
    for pid, games in by_player.items():
        games.sort(key=lambda x: (x[0], x[1]))
        team = games[-1][2]["team"]
        feats: dict[str, Any] = {"player_id": pid, "team": team, "week": week, "games_prior": len(games),
                                 "team_proe": proe.get(team), "team_games_prior": len(team_games.get(team, []))}
        for prefix, key in (("tgt", "targets"), ("air", "air_yards"), ("carry", "carries"), ("pass", "pass_att")):
            feats.update(share_features([(g[2][key], teams[(g[1], g[2]["team"])][key]) for g in games], prefix))
        feats["pass_share_season"] = feats.pop("pass_season")
        for k in ("pass_l3", "pass_base", "pass_trend"):
            feats.pop(k, None)
        feats["last_game"] = games[-1][1]
        feats["out_this_week"] = pid in out.get((week, team), set())
        rows[pid] = feats
    for team in team_games:
        listed_out = out.get((week, team), set())
        fresh = [rows[pid] for pid in listed_out if pid in rows and rows[pid]["last_game"] == last_game.get(team)]
        vac_tgt = round(sum(r.get("tgt_season") or 0.0 for r in fresh), 4)
        vac_carry = round(sum(r.get("carry_season") or 0.0 for r in fresh), 4)
        for r in rows.values():
            if r["team"] == team:
                r["vac_tgt_fresh"], r["vac_carry_fresh"] = vac_tgt, vac_carry
                r["vac_players"] = sorted(x["player_id"] for x in fresh)
    for r in rows.values():
        r["tgt_share_season"], r["carry_share_season"] = r.get("tgt_season"), r.get("carry_season")
        r.setdefault("vac_tgt_fresh", None)
        r.setdefault("vac_carry_fresh", None)
    return list(rows.values())


def _read_pbp(path: Path) -> Iterable[dict[str, Any]]:
    with path.open(encoding="utf-8", newline="") as fh:
        yield from csv.DictReader(fh)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--data-root", default=os.environ.get("SYNDICATE_DATA_ROOT") or "")
    ap.add_argument("--seasons", required=True, help="comma list, e.g. 2023,2024,2025")
    ap.add_argument("--injuries-dir", default=None, help="dir with injuries_<season>.csv (nflverse)")
    ap.add_argument("--max-week", type=int, default=18)
    args = ap.parse_args(argv)
    if not args.data_root:
        print("REFUSING: no --data-root", flush=True)
        return 2
    root = Path(os.path.expanduser(args.data_root))
    for season in [int(s) for s in args.seasons.split(",") if s.strip()]:
        pbp = root / "nfl_source" / "tracking" / "nflverse" / "pbp" / f"pbp_{season}.csv"
        if not pbp.is_file():
            print(f"NFL_SIGNALS season={season} SKIP no pbp at {pbp}", flush=True)
            continue
        players, teams = game_counts(_read_pbp(pbp))
        inj = Path(os.path.expanduser(args.injuries_dir)) / f"injuries_{season}.csv" if args.injuries_dir else None
        out = load_out(inj, season)
        weeks = sorted({r["week"] for r in teams.values()})
        written = fired_vac = 0
        for week in range(2, min(args.max_week, max(weeks) + 1) + 1):
            rows = build_week(players, teams, out, week)
            write_signal_table(root, "nfl", str(season), week_key(week), rows)
            written += len(rows)
            fired_vac += sum(1 for r in rows if (r.get("vac_tgt_fresh") or 0) > 0)
        print(f"NFL_SIGNALS season={season} player_games={len(players)} team_games={len(teams)} weeks={len(weeks)} "
              f"rows={written} out_listings={sum(len(v) for v in out.values())} rows_with_vacated_targets={fired_vac}",
              flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
