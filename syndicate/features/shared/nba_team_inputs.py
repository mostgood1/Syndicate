"""NBA smart-sim team inputs that nothing fed: as-of team ratings and starter flags (lane `nba-sim-team-adj-473`, `#473`).

WHY. Measured 2026-10-09 (`scripts/basketball_engine_input_checklist.py`, 15 production NBA sims 10-05..08):
`home/away_team_adj` absent on 0/30 NBA team-sides (WNBA 24/24) and starter flags on 0/517 player rows. Every
production NBA sim carried `team_advanced_priors.reason = missing_team_advanced_stats` and
`pregame_expected_minutes.reason = missing_pregame_expected_minutes`.

  * Team ratings. `_team_adj_from_advanced_stats_local` keys an NBA season by its END year (2026-10-09 -> 2027) and the
    vendored builders it calls can only fill season 2027 from 2026-27 REGULAR-season games with `min_games=10`: empty
    from the preseason until ~3 weeks into the season. (The vendored boxscores builder also reads a
    `processed/boxscores/` directory that does not exist in Syndicate's layout.) WNBA keys by START year with
    `min_games=1`, which is why it was fed.
  * Starter flags. Their only feed is `pregame_expected_minutes_<date>.csv`; WNBA's refresh writes it with a vendored
    step that NBA's refresh deliberately omits, and nothing else writes it for NBA.

WHAT THIS BUILDS, and which POPULATION each number comes from (never mixed across phases):

  * `build_team_ratings_asof` -> `team_advanced_stats_<season>_asof_<YYYYMMDD>.csv`, the file the sim already reads.
    Ratings come ONLY from regular-season rows of `player_logs.csv` (`SEASON_ID` 2xxxx). Preseason games never enter a
    rating. A team's rating is the current season's regular-season games so far blended with the PRIOR regular
    season's final rating shrunk toward the league mean:
        rating = (n * current + K * (mean + BETA * (prior - mean))) / (n + K)
    BETA = 0.573: slope of next-season on this-season mean margin, 270 team-season pairs, regular seasons 2017-2026
    (`games_nba_api.csv`). K = 15 games: minimised rest-of-season margin MSE over n in {3,5,10,20} (flat 12..20). At
    n = 0 the shrunk prior cut rest-of-season margin MSE 25.47 -> 17.81 vs a neutral rating. BETA is measured on
    MARGIN and applied to every rating column's deviation; per-column persistence is not separately measured.
  * `build_starters` -> `pregame_expected_minutes_<date>.csv` with STARTER COLUMNS ONLY (no `exp_min_*`, so the
    sim's minutes inputs are untouched): starter_prob = share of the team's last 5 games (date < slate) in which ESPN's
    box score marked the player a starter (P2's `rotation_stints/player_checks_<date>.csv`). Population: the slate's
    own phase of the current season when the team has >= 3 such games; otherwise the current season's games of any
    phase; otherwise the prior season's regular-season games. The population is written per row in `exp_min_source`.

OFF SWITCH. `SYNDICATE_NBA_TEAM_INPUTS=0` restores the previous inputs exactly: the producers are not called AND files
these producers wrote are ignored on read (`is_ours`), so off == the pre-fix sim even on a disk that holds them.
"""
from __future__ import annotations

import os
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional

TEAM_RATINGS_SOURCE = "syndicate_nba_team_inputs_v1"
STARTERS_SOURCE_PREFIX = "nba_starters_v1"
YOY_BETA = 0.573
PRIOR_GAMES_K = 15.0
STARTER_WINDOW = 5
STARTER_MIN_SAME_PHASE = 3
STARTER_FLAG_MIN_PROB = 0.6  # started >= 3 of the last 5
STARTER_LOOKBACK_FILES = 120
RATING_COLS = ("pace", "off_rtg", "def_rtg", "efg_pct", "tov_pct", "orb_pct", "ft_rate", "fg3a_rate", "fg3_pct")
# nba_season_phase names -> the `season_type` values P2's stints producer writes
_PHASE_TO_SEASON_TYPE = {"preseason": "preseason", "regular": "regular", "postseason": "playoffs", "play_in": "play-in"}


def enabled() -> bool:
    return (os.environ.get("SYNDICATE_NBA_TEAM_INPUTS") or "1").strip().lower() not in {"0", "false", "no", "off"}


def is_ours(source: Any) -> bool:
    text = str(source or "")
    return text.startswith(TEAM_RATINGS_SOURCE) or text.startswith(STARTERS_SOURCE_PREFIX)


def _iso(date_str: str) -> str:
    text = str(date_str or "").strip()
    if re.fullmatch(r"\d{8}", text):
        return f"{text[:4]}-{text[4:6]}-{text[6:]}"
    return text[:10]


def season_end_year(date_str: str) -> int:
    d = datetime.strptime(_iso(date_str), "%Y-%m-%d").date()
    return d.year + 1 if d.month >= 7 else d.year


def _season_label(season_end: int) -> str:
    return f"{int(season_end) - 1}-{str(int(season_end))[-2:]}"


def _atomic_write_csv(df, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    df.to_csv(tmp, index=False)
    os.replace(tmp, path)


# ------------------------------------------------------------------------------------------------ team ratings

def _load_regular_player_logs(processed_root: Path):
    import pandas as pd

    path = Path(processed_root) / "player_logs.csv"
    if not path.is_file() or path.stat().st_size <= 0:
        return pd.DataFrame()
    df = pd.read_csv(path, dtype={"SEASON_ID": str, "GAME_ID": str})
    need = {"SEASON_ID", "SEASON", "GAME_ID", "GAME_DATE", "TEAM_ABBREVIATION", "PTS", "FGM", "FGA", "FG3M", "FTA", "OREB", "DREB", "TOV"}
    if df.empty or not need.issubset(df.columns):
        return pd.DataFrame()
    df = df[df["SEASON_ID"].astype(str).str.strip().str.startswith("2")].copy()  # regular season only
    df["GAME_DATE"] = pd.to_datetime(df["GAME_DATE"], errors="coerce")
    df["SEASON"] = df["SEASON"].astype(str).str.strip()
    return df.dropna(subset=["GAME_DATE"])


def team_season_ratings(logs, *, season_label: str, as_of: Optional[date] = None):
    """Per-team regular-season ratings from player rows (same definitions as the vendored player-logs builder, so a
    WNBA-style table and this one mean the same thing to the sim). `as_of` is inclusive."""
    import numpy as np
    import pandas as pd

    if logs is None or logs.empty:
        return pd.DataFrame()
    df = logs[logs["SEASON"] == season_label]
    if as_of is not None:
        df = df[df["GAME_DATE"].dt.date <= as_of]
    if df.empty:
        return pd.DataFrame()
    cols = ["PTS", "FGM", "FGA", "FG3M", "FG3A", "FTA", "OREB", "DREB", "TOV"]
    tmp = df[["GAME_ID", "TEAM_ABBREVIATION"] + [c for c in cols if c in df.columns]].copy()
    for c in cols:
        tmp[c] = pd.to_numeric(tmp[c], errors="coerce").fillna(0.0) if c in tmp.columns else np.nan
    tmp["TEAM_ABBREVIATION"] = tmp["TEAM_ABBREVIATION"].astype(str).str.upper().str.strip()
    g = tmp.groupby(["GAME_ID", "TEAM_ABBREVIATION"], as_index=False)[cols].sum(min_count=1)
    opp = g.rename(columns={"TEAM_ABBREVIATION": "OPP", **{c: f"O_{c}" for c in cols}})
    m = g.merge(opp, on="GAME_ID")
    m = m[m["TEAM_ABBREVIATION"] != m["OPP"]].drop_duplicates(subset=["GAME_ID", "TEAM_ABBREVIATION"])
    if m.empty:
        return pd.DataFrame()
    m["poss"] = m["FGA"] + 0.44 * m["FTA"] - m["OREB"] + m["TOV"]
    m["o_poss"] = m["O_FGA"] + 0.44 * m["O_FTA"] - m["O_OREB"] + m["O_TOV"]
    m["pace_game"] = 0.5 * (m["poss"] + m["o_poss"])
    a = m.groupby("TEAM_ABBREVIATION").agg(
        games=("GAME_ID", "size"), pts=("PTS", "sum"), opp_pts=("O_PTS", "sum"), fgm=("FGM", "sum"), fga=("FGA", "sum"),
        tpm=("FG3M", "sum"), tpa=("FG3A", "sum"), fta=("FTA", "sum"), oreb=("OREB", "sum"), opp_dreb=("O_DREB", "sum"),
        tov=("TOV", "sum"), poss=("poss", "sum"), o_poss=("o_poss", "sum"), pace=("pace_game", "mean"),
    ).reset_index().rename(columns={"TEAM_ABBREVIATION": "team"})
    eps = 1e-9
    a["off_rtg"] = 100.0 * a["pts"] / (a["poss"] + eps)
    a["def_rtg"] = 100.0 * a["opp_pts"] / (a["o_poss"] + eps)
    a["efg_pct"] = (a["fgm"] + 0.5 * a["tpm"]) / (a["fga"] + eps)
    a["tov_pct"] = a["tov"] / (a["fga"] + 0.44 * a["fta"] + a["tov"] + eps)
    a["orb_pct"] = a["oreb"] / (a["oreb"] + a["opp_dreb"] + eps)
    a["ft_rate"] = a["fta"] / (a["fga"] + eps)
    a["fg3a_rate"] = a["tpa"] / (a["fga"] + eps)
    a["fg3_pct"] = a["tpm"] / (a["tpa"] + eps)
    return a[["team", "games", *RATING_COLS]].copy()


def build_team_ratings_asof(*, processed_root: Path, season: int, as_of: str):
    """The blended as-of table for NBA `season` (END year), or an empty frame when neither the current nor the prior
    regular season has a single game. Pure: reads player_logs.csv, writes nothing."""
    import numpy as np
    import pandas as pd

    as_of_d = datetime.strptime(_iso(as_of), "%Y-%m-%d").date()
    logs = _load_regular_player_logs(Path(processed_root))
    cur_label, prior_label = _season_label(season), _season_label(int(season) - 1)
    cur = team_season_ratings(logs, season_label=cur_label, as_of=as_of_d)
    prior = team_season_ratings(logs, season_label=prior_label)
    if cur.empty and prior.empty:
        return pd.DataFrame()
    prior_mean = {c: float(prior[c].mean()) for c in RATING_COLS} if not prior.empty else {}
    cur_mean = {c: float(cur[c].mean()) for c in RATING_COLS} if not cur.empty else {}
    teams = sorted((set(cur["team"]) if not cur.empty else set()) | (set(prior["team"]) if not prior.empty else set()))
    cur_i = cur.set_index("team") if not cur.empty else None
    prior_i = prior.set_index("team") if not prior.empty else None
    rows = []
    for team in teams:
        n = float(cur_i.at[team, "games"]) if (cur_i is not None and team in cur_i.index) else 0.0
        has_prior = prior_i is not None and team in prior_i.index
        row: Dict[str, Any] = {"team": team, "games": int(n), "prior_games": int(prior_i.at[team, "games"]) if has_prior else 0}
        for c in RATING_COLS:
            if has_prior:
                anchor = prior_mean[c] + YOY_BETA * (float(prior_i.at[team, c]) - prior_mean[c])
            else:  # no prior rating (expansion/relabel): shrink toward the league mean with the same weight
                anchor = cur_mean.get(c, prior_mean.get(c, float("nan")))
            cur_v = float(cur_i.at[team, c]) if n > 0 else 0.0
            row[c] = (n * cur_v + PRIOR_GAMES_K * anchor) / (n + PRIOR_GAMES_K)
        row["population"] = ("prior_regular_shrunk" if n == 0 else "current_regular_blend") if has_prior else "current_regular_shrunk_to_mean"
        rows.append(row)
    out = pd.DataFrame(rows).replace([np.inf, -np.inf], np.nan)
    out["source"] = (f"{TEAM_RATINGS_SOURCE}:prior={prior_label}_regular(beta={YOY_BETA}),"
                     f"current={cur_label}_regular_through_{as_of_d.isoformat()}(k={PRIOR_GAMES_K:g})")
    return out


def ensure_team_ratings_asof(*, processed_root: Path, season: int, as_of: str) -> Optional[Path]:
    """Write the as-of table under the name the sim reads; None when there is nothing to write."""
    stats = build_team_ratings_asof(processed_root=processed_root, season=season, as_of=as_of)
    if stats is None or stats.empty:
        return None
    out = Path(processed_root) / f"team_advanced_stats_{int(season)}_asof_{_iso(as_of).replace('-', '')}.csv"
    _atomic_write_csv(stats, out)
    return out


# ------------------------------------------------------------------------------------------------ starter flags

def _norm_name(value: Any) -> str:
    import unicodedata

    text = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode("ascii").lower()
    text = re.sub(r"[^a-z0-9 ]", " ", text)
    text = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b", " ", text)
    return " ".join(text.split())


def _load_player_checks(processed_root: Path, before: str):
    import pandas as pd

    stints = Path(processed_root) / "rotation_stints"
    files = sorted(p for p in stints.glob("player_checks_*.csv") if p.stem[len("player_checks_"):] < before)
    frames = []
    for p in files[-STARTER_LOOKBACK_FILES:]:
        try:
            frames.append(pd.read_csv(p, usecols=["season", "season_type", "date", "event_id", "team", "player_name", "starter"]))
        except Exception:  # noqa: BLE001 -- a malformed day must not lose the rest
            continue
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True)
    df["team"] = df["team"].astype(str).str.upper().str.strip()
    df["starter"] = pd.to_numeric(df["starter"], errors="coerce").fillna(0).astype(int)
    return df[df["date"].astype(str) < before]


def build_starters(*, processed_root: Path, date_str: str, slate_phase: Optional[str] = None):
    """Rows (date, team_tri, player_name, starter_prob, is_starter, exp_min_source) for every team with history."""
    import pandas as pd

    ds = _iso(date_str)
    checks = _load_player_checks(Path(processed_root), ds)
    if checks.empty:
        return pd.DataFrame()
    season = season_end_year(ds)
    want_type = _PHASE_TO_SEASON_TYPE.get(str(slate_phase or ""))
    rows = []
    for team, grp in checks.groupby("team"):
        games = grp.drop_duplicates("event_id")[["event_id", "date", "season", "season_type"]].sort_values("date", ascending=False)
        cur = games[games["season"] == season]
        same = cur[cur["season_type"] == want_type] if want_type else cur.iloc[0:0]
        if len(same) >= STARTER_MIN_SAME_PHASE:
            pick, pop = same, f"{season}_{want_type}"
        elif len(cur):
            pick, pop = cur, f"{season}_any_phase"
        else:
            prior = games[(games["season"] == season - 1) & (games["season_type"] == "regular")]
            if prior.empty:
                continue
            pick, pop = prior, f"{season - 1}_regular"
        ids = list(pick["event_id"].head(STARTER_WINDOW))
        window = grp[grp["event_id"].isin(ids)].groupby(["event_id", "player_name"], as_index=False)["starter"].max()
        share = window.groupby("player_name")["starter"].sum() / float(len(ids))
        for name, prob in share.items():
            if not str(name).strip():
                continue
            rows.append({
                "date": ds, "team_tri": team, "player_name": str(name).strip(), "starter_prob": round(float(prob), 4),
                "is_starter": bool(prob >= STARTER_FLAG_MIN_PROB),
                "exp_min_source": f"{STARTERS_SOURCE_PREFIX}:{pop}:last{len(ids)}",
            })
    return pd.DataFrame(rows)



def ensure_starters(*, processed_root: Path, date_str: str) -> Optional[Path]:
    """Write `pregame_expected_minutes_<date>.csv` (starter columns only) unless one already exists."""
    ds = _iso(date_str)
    out = Path(processed_root) / f"pregame_expected_minutes_{ds}.csv"
    if out.exists() or out.with_suffix(".parquet").exists():
        return out
    phase = None
    try:
        from syndicate.features.shared.nba_season_phase import phase_for_date

        phase = phase_for_date(ds, processed_root=Path(processed_root), allow_fetch=False)
    except Exception:  # noqa: BLE001 -- unknown phase -> current season, any phase
        phase = None
    df = build_starters(processed_root=Path(processed_root), date_str=ds, slate_phase=phase)
    if df is None or df.empty:
        return None
    _atomic_write_csv(df, out)
    return out
