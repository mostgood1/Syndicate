from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import date as _date
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
DATA = ROOT / "data"
PROC = DATA / "processed"
CACHE = DATA / "processed" / "_reconcile_cache"


def _configure_nba_api_headers() -> None:
    """Best-effort: configure nba_api headers to avoid stats.nba.com blocking.

    Mirrors the approach used in app.py.
    """
    try:
        from nba_api.library import http as _nba_http  # type: ignore

        _nba_http.STATS_HEADERS.update(
            {
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "en-US,en;q=0.9",
                "Origin": "https://www.nba.com",
                "Referer": "https://www.nba.com/stats/",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
                "Connection": "keep-alive",
            }
        )
    except Exception:
        return


def _parse_date(s: str) -> _date:
    return datetime.strptime(str(s), "%Y-%m-%d").date()


def _daterange(start: _date, end: _date):
    d = start
    while d <= end:
        yield d
        d = d + timedelta(days=1)


def _norm_tri(x: Any) -> str:
    return str(x or "").strip().upper()


def _espn_to_tri(abbr: str) -> str:
    s = str(abbr or "").strip().upper()
    fix = {"GS": "GSW", "NO": "NOP", "NY": "NYK", "UTAH": "UTA"}
    return fix.get(s, s)


def _tri_to_espn(tri: str) -> str:
    s = str(tri or "").strip().upper()
    fix = {"GSW": "GS", "NOP": "NO", "NYK": "NY", "UTA": "UTAH"}
    return fix.get(s, s)


def _safe_int(x: Any, default: int = 0) -> int:
    try:
        v = int(pd.to_numeric(x, errors="coerce"))
        return v
    except Exception:
        return default


def _safe_float(x: Any, default: float = 0.0) -> float:
    try:
        v = float(pd.to_numeric(x, errors="coerce"))
        if not np.isfinite(v):
            return default
        return v
    except Exception:
        return default


def _norm_player_key(s: str) -> str:
    if s is None:
        return ""
    t = str(s)
    if "(" in t:
        t = t.split("(", 1)[0]
    t = t.replace("-", " ").replace(".", "").replace("'", "").replace(",", " ")
    t = t.strip()
    for suf in (" JR", " SR", " II", " III", " IV"):
        if t.upper().endswith(suf):
            t = t[: -len(suf)]
    try:
        t = t.encode("ascii", "ignore").decode("ascii")
    except Exception:
        pass
    return t.upper().strip()


def _load_player_logs() -> pd.DataFrame:
    fp = PROC / "player_logs.csv"
    if not fp.exists():
        raise SystemExit(f"Missing {fp}")
    df = pd.read_csv(fp)
    if df is None or df.empty:
        raise SystemExit("player_logs.csv empty")
    return df


def _load_predictions(d: _date) -> Optional[pd.DataFrame]:
    fp = PROC / f"predictions_{d.isoformat()}.csv"
    if not fp.exists():
        return None
    try:
        df = pd.read_csv(fp)
        return df if isinstance(df, pd.DataFrame) else None
    except Exception:
        return None


def _load_props_predictions(d: _date) -> Optional[pd.DataFrame]:
    fp = PROC / f"props_predictions_{d.isoformat()}.csv"
    if not fp.exists():
        return None
    try:
        df = pd.read_csv(fp)
        return df if isinstance(df, pd.DataFrame) else None
    except Exception:
        return None


def _games_from_logs_for_date(logs: pd.DataFrame, d: _date) -> pd.DataFrame:
    g = logs.copy()
    g["GAME_DATE"] = pd.to_datetime(g.get("GAME_DATE"), errors="coerce").dt.date
    g = g[g["GAME_DATE"] == d]
    if g.empty:
        return pd.DataFrame(columns=["game_id", "home_tri", "away_tri"])

    # Determine home/away from MATCHUP string when possible.
    out_rows: list[dict[str, str]] = []
    for gid, gg in g.groupby(g.get("GAME_ID").astype(str), dropna=False):
        if not gid or gid == "nan":
            continue
        gg = gg.copy()
        gg["TEAM_ABBREVIATION"] = gg.get("TEAM_ABBREVIATION").astype(str).str.upper().str.strip()
        gg["MATCHUP"] = gg.get("MATCHUP").astype(str)

        home_tri: Optional[str] = None
        away_tri: Optional[str] = None
        # Home team row usually contains "vs."; away contains "@".
        try:
            home_row = gg[gg["MATCHUP"].str.contains("vs", case=False, na=False)]
            if not home_row.empty:
                home_tri = _norm_tri(home_row.iloc[0].get("TEAM_ABBREVIATION"))
        except Exception:
            home_tri = None
        try:
            away_row = gg[gg["MATCHUP"].str.contains("@", case=False, na=False)]
            if not away_row.empty:
                away_tri = _norm_tri(away_row.iloc[0].get("TEAM_ABBREVIATION"))
        except Exception:
            away_tri = None

        # Fallback if MATCHUP parsing failed: infer from unique teams.
        teams = [t for t in gg["TEAM_ABBREVIATION"].dropna().astype(str).str.upper().str.strip().unique().tolist() if t]
        if (not home_tri) or (not away_tri):
            if len(teams) == 2:
                # unknown home/away, but keep stable order
                home_tri = home_tri or teams[0]
                away_tri = away_tri or teams[1]

        if home_tri and away_tri and home_tri != away_tri:
            out_rows.append({"game_id": str(gid), "home_tri": home_tri, "away_tri": away_tri})

    return pd.DataFrame(out_rows)


@dataclass
class ActualGameContext:
    home_tri: str
    away_tri: str
    home_pts: int
    away_pts: int
    quarters: list[dict[str, int]]
    starters_home: list[str]
    starters_away: list[str]
    first_sub_in_home: Optional[str]
    first_sub_in_away: Optional[str]
    first_sub_time_home: Optional[str]
    first_sub_time_away: Optional[str]


def _cache_path(kind: str, game_id: str) -> Path:
    CACHE.mkdir(parents=True, exist_ok=True)
    return CACHE / f"{kind}_{game_id}.json"


def _fetch_nba_api_cached(kind: str, game_id: str, fetcher) -> dict[str, Any]:
    fp = _cache_path(kind, game_id)
    if fp.exists():
        try:
            return json.loads(fp.read_text(encoding="utf-8"))
        except Exception:
            pass
    try:
        data = fetcher()
    except Exception:
        return {}
    # Only cache non-empty dicts
    try:
        if isinstance(data, dict) and data:
            fp.write_text(json.dumps(data), encoding="utf-8")
    except Exception:
        pass
    return data if isinstance(data, dict) else {}


def _http_get_json(url: str, timeout: int = 12) -> dict[str, Any]:
    try:
        import requests

        r = requests.get(
            url,
            headers={"Accept": "application/json", "User-Agent": "nba-betting/1.0"},
            timeout=int(timeout),
        )
        if not r.ok:
            return {}
        j = r.json()
        return j if isinstance(j, dict) else {}
    except Exception:
        return {}


def _espn_scoreboard(date_str: str) -> dict[str, Any]:
    ymd = str(date_str).replace("-", "")
    url = f"https://site.web.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates={ymd}"
    return _fetch_nba_api_cached("espn_scoreboard", date_str, lambda: _http_get_json(url, timeout=12))


def _espn_summary(event_id: str) -> dict[str, Any]:
    url = f"https://site.web.api.espn.com/apis/site/v2/sports/basketball/nba/summary?event={event_id}"
    return _fetch_nba_api_cached("espn_summary", str(event_id), lambda: _http_get_json(url, timeout=12))


def _espn_event_id_for_matchup(date_str: str, home_tri: str, away_tri: str) -> Optional[str]:
    sb = _espn_scoreboard(date_str)
    events = sb.get("events") if isinstance(sb, dict) else None
    if not isinstance(events, list):
        return None
    h = _tri_to_espn(home_tri)
    a = _tri_to_espn(away_tri)
    for e in events:
        try:
            comps = (e or {}).get("competitions") or []
            if not comps:
                continue
            c0 = comps[0] or {}
            teams = c0.get("competitors") or []
            if len(teams) < 2:
                continue
            home = next((t for t in teams if str((t or {}).get("homeAway")) == "home"), None)
            away = next((t for t in teams if str((t or {}).get("homeAway")) == "away"), None)
            if not home or not away:
                continue
            hab = str(((home.get("team") or {}).get("abbreviation")) or "").strip().upper()
            aab = str(((away.get("team") or {}).get("abbreviation")) or "").strip().upper()
            if hab == h and aab == a:
                return str((e or {}).get("id") or "").strip() or None
        except Exception:
            continue
    return None


def _actual_quarters_from_espn_competitors(comp_home: dict[str, Any], comp_away: dict[str, Any]) -> tuple[list[dict[str, int]], int, int]:
    def _score(c: dict[str, Any]) -> int:
        try:
            return int(float(c.get("score") or 0))
        except Exception:
            return 0

    hpts = _score(comp_home)
    apts = _score(comp_away)
    hl = comp_home.get("linescores") if isinstance(comp_home, dict) else None
    al = comp_away.get("linescores") if isinstance(comp_away, dict) else None
    if not isinstance(hl, list) or not isinstance(al, list):
        return [], hpts, apts

    out: list[dict[str, int]] = []
    hcum = 0
    acum = 0
    for i in range(1, 5):
        hli = (hl[i - 1] or {})
        ali = (al[i - 1] or {})
        try:
            hp = int(float(hli.get("value") or hli.get("displayValue") or 0))
        except Exception:
            hp = 0
        try:
            ap = int(float(ali.get("value") or ali.get("displayValue") or 0))
        except Exception:
            ap = 0
        hcum += hp
        acum += ap
        out.append({"q": i, "home": hp, "away": ap, "home_cum": hcum, "away_cum": acum})
    return out, hpts, apts


def _extract_starters_from_espn_boxscore(summary: dict[str, Any], team_abbr: str) -> list[str]:
    try:
        box = (summary or {}).get("boxscore") or {}
        players = box.get("players") or []
        if not isinstance(players, list):
            return []
        tabbr = str(team_abbr or "").strip().upper()
        for tp in players:
            team = (tp or {}).get("team") or {}
            ab = str(team.get("abbreviation") or "").strip().upper()
            if ab != tabbr:
                continue
            stats_groups = (tp or {}).get("statistics") or []
            if not isinstance(stats_groups, list):
                continue
            starters: list[str] = []
            for g in stats_groups:
                ath = (g or {}).get("athletes") or []
                if not isinstance(ath, list):
                    continue
                for a in ath:
                    if not isinstance(a, dict):
                        continue
                    if bool(a.get("starter")):
                        nm = str(((a.get("athlete") or {}).get("displayName")) or "").strip()
                        if nm:
                            starters.append(nm)
                if starters:
                    break
            return starters[:5]
        return []
    except Exception:
        return []


def _player_team_map_from_espn_boxscore(summary: dict[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    try:
        box = (summary or {}).get("boxscore") or {}
        players = box.get("players") or []
        if not isinstance(players, list):
            return {}
        for tp in players:
            team = (tp or {}).get("team") or {}
            ab = str(team.get("abbreviation") or "").strip().upper()
            stats_groups = (tp or {}).get("statistics") or []
            if not isinstance(stats_groups, list):
                continue
            for g in stats_groups:
                ath = (g or {}).get("athletes") or []
                if not isinstance(ath, list):
                    continue
                for a in ath:
                    nm = str(((a or {}).get("athlete") or {}).get("displayName") or "").strip()
                    if nm:
                        out[_norm_player_key(nm)] = ab
    except Exception:
        return out
    return out


def _first_sub_from_espn_pbp(summary: dict[str, Any], team_abbr: str) -> tuple[Optional[str], Optional[str]]:
    try:
        plays = (summary or {}).get("plays") or []
        if not isinstance(plays, list) or not plays:
            return None, None
        tabbr = str(team_abbr or "").strip().upper()

        p2team = _player_team_map_from_espn_boxscore(summary)

        def _clock_str(clk: Any) -> str:
            if isinstance(clk, dict):
                return str(clk.get("displayValue") or "").strip()
            return str(clk or "").strip()

        def _key(p: dict[str, Any]) -> tuple[int, int]:
            per = int((p.get("period") or {}).get("number") or 99)
            clk = _clock_str(p.get("clock"))
            try:
                if ":" in clk:
                    mm, ss = clk.split(":", 1)
                    rem = int(mm) * 60 + int(ss)
                    plen = 12 * 60 if per <= 4 else 5 * 60
                    el = plen - rem
                else:
                    el = 10**9
            except Exception:
                el = 10**9
            return per, el

        subs: list[dict[str, Any]] = []
        for p in plays:
            if not isinstance(p, dict):
                continue
            txt = str(p.get("text") or "")
            ttxt = str(((p.get("type") or {}).get("text")) or "")
            is_sub = ("substitution" in ttxt.lower()) or ("enters the game" in txt.lower())
            if not is_sub:
                continue
            ab = str(((p.get("team") or {}).get("abbreviation")) or "").strip().upper()
            if not ab:
                # For substitutions, ESPN often omits team; infer from player name.
                if " enters the game" in txt:
                    nm_in = txt.split(" enters the game", 1)[0].strip()
                    ab = p2team.get(_norm_player_key(nm_in), "")
            if ab != tabbr:
                continue
            subs.append(p)
        if not subs:
            return None, None
        subs.sort(key=_key)
        p0 = subs[0]
        txt = str(p0.get("text") or "")
        clk = _clock_str(p0.get("clock")) or None
        name_in = None
        if " enters the game" in txt:
            name_in = txt.split(" enters the game", 1)[0].strip()
        return name_in, clk
    except Exception:
        return None, None


def _player_points_by_quarter_from_espn_pbp(summary: dict[str, Any]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    plays = (summary or {}).get("plays") or []
    if not isinstance(plays, list) or not plays:
        return pd.DataFrame(columns=["team", "player_name", "q", "pts"])
    for p in plays:
        if not isinstance(p, dict):
            continue
        if not bool(p.get("scoringPlay")):
            continue
        pts = _safe_int(p.get("scoreValue"), 0)
        if pts <= 0:
            continue
        per = _safe_int((p.get("period") or {}).get("number"), 0)
        if per <= 0:
            continue
        team = (p.get("team") or {})
        ab = str(team.get("abbreviation") or "").strip().upper()
        parts = p.get("participants") or []
        shooter = None
        if isinstance(parts, list) and parts:
            for part in parts:
                if isinstance(part, dict) and (part.get("athlete") or {}).get("displayName"):
                    shooter = str(((part.get("athlete") or {}).get("displayName")) or "").strip()
                    break
        if not shooter:
            txt = str(p.get("text") or "")
            if txt and "(" in txt:
                shooter = txt.split("(", 1)[0].strip()
        if not shooter:
            continue
        rows.append({"team": ab, "player_name": shooter, "q": int(per), "pts": int(pts)})
    if not rows:
        return pd.DataFrame(columns=["team", "player_name", "q", "pts"])
    df = pd.DataFrame(rows)
    return df.groupby(["team", "player_name", "q"], as_index=False)["pts"].sum()


def _fetch_actual_game_context_espn(date_str: str, home_tri: str, away_tri: str) -> tuple[ActualGameContext, pd.DataFrame]:
    event_id = _espn_event_id_for_matchup(date_str, home_tri, away_tri)
    if not event_id:
        return (
            ActualGameContext(
                home_tri=home_tri,
                away_tri=away_tri,
                home_pts=0,
                away_pts=0,
                quarters=[],
                starters_home=[],
                starters_away=[],
                first_sub_in_home=None,
                first_sub_in_away=None,
                first_sub_time_home=None,
                first_sub_time_away=None,
            ),
            pd.DataFrame(columns=["team", "player_name", "q", "pts"]),
        )

    summ = _espn_summary(event_id)
    hdr = (summ or {}).get("header") or {}
    comps = (hdr.get("competitions") or []) if isinstance(hdr, dict) else []
    c0 = comps[0] if comps else {}
    teams = (c0.get("competitors") or []) if isinstance(c0, dict) else []
    home = next((t for t in teams if str((t or {}).get("homeAway")) == "home"), {})
    away = next((t for t in teams if str((t or {}).get("homeAway")) == "away"), {})
    quarters, hpts, apts = _actual_quarters_from_espn_competitors(home, away)

    h_ab = _tri_to_espn(home_tri)
    a_ab = _tri_to_espn(away_tri)

    starters_home = _extract_starters_from_espn_boxscore(summ, h_ab)
    starters_away = _extract_starters_from_espn_boxscore(summ, a_ab)

    first_home, time_home = _first_sub_from_espn_pbp(summ, h_ab)
    first_away, time_away = _first_sub_from_espn_pbp(summ, a_ab)

    pts_q = _player_points_by_quarter_from_espn_pbp(summ)

    ctx = ActualGameContext(
        home_tri=home_tri,
        away_tri=away_tri,
        home_pts=int(hpts),
        away_pts=int(apts),
        quarters=quarters,
        starters_home=starters_home,
        starters_away=starters_away,
        first_sub_in_home=first_home,
        first_sub_in_away=first_away,
        first_sub_time_home=time_home,
        first_sub_time_away=time_away,
    )
    return ctx, pts_q


def _actual_quarters_from_linescore(linescore: pd.DataFrame, home_tri: str, away_tri: str) -> tuple[list[dict[str, int]], int, int]:
    if linescore is None or linescore.empty:
        return [], 0, 0

    cols = {c.upper(): c for c in linescore.columns}
    team_col = cols.get("TEAM_ABBREVIATION") or cols.get("TEAM_TRICODE") or cols.get("TEAM")
    if not team_col:
        return [], 0, 0

    def _row_for(tri: str) -> pd.Series:
        m = linescore[team_col].astype(str).str.upper().str.strip() == str(tri).upper().strip()
        if bool(m.any()):
            return linescore[m].iloc[0]
        return linescore.iloc[0]

    hrow = _row_for(home_tri)
    arow = _row_for(away_tri)

    qcols = []
    for k in ("PTS_QTR1", "PTS_QTR2", "PTS_QTR3", "PTS_QTR4"):
        if k in cols:
            qcols.append(cols[k])
    if not qcols:
        # Alternate naming
        for i in (1, 2, 3, 4):
            key = f"PTS_QTR{i}"
            if key in cols:
                qcols.append(cols[key])

    out: list[dict[str, int]] = []
    hcum = 0
    acum = 0
    for i, qc in enumerate(qcols[:4], start=1):
        hp = _safe_int(hrow.get(qc), 0)
        ap = _safe_int(arow.get(qc), 0)
        hcum += hp
        acum += ap
        out.append({"q": i, "home": hp, "away": ap, "home_cum": hcum, "away_cum": acum})

    # Final points
    pts_col = cols.get("PTS")
    if pts_col:
        hpts = _safe_int(hrow.get(pts_col), hcum)
        apts = _safe_int(arow.get(pts_col), acum)
    else:
        hpts = hcum
        apts = acum

    return out, hpts, apts


def _extract_starters(trad_players: pd.DataFrame, team_tri: str) -> list[str]:
    if trad_players is None or trad_players.empty:
        return []
    cols = {c.upper(): c for c in trad_players.columns}
    tcol = cols.get("TEAM_ABBREVIATION")
    ncol = cols.get("PLAYER_NAME") or cols.get("PLAYER")
    scol = cols.get("START_POSITION")
    if not tcol or not ncol:
        return []
    tmp = trad_players.copy()
    tmp[tcol] = tmp[tcol].astype(str).str.upper().str.strip()
    tmp = tmp[tmp[tcol] == str(team_tri).upper().strip()]
    if tmp.empty:
        return []
    if scol and scol in tmp.columns:
        starters = tmp[tmp[scol].astype(str).str.strip().ne("")].copy()
        if not starters.empty:
            return [str(x).strip() for x in starters[ncol].dropna().astype(str).tolist()][:5]
    # Fallback: top minutes
    min_col = cols.get("MIN")
    if min_col:
        tmp["_m"] = pd.to_numeric(tmp[min_col], errors="coerce").fillna(0.0)
        tmp = tmp.sort_values("_m", ascending=False)
    return [str(x).strip() for x in tmp[ncol].dropna().astype(str).tolist()][:5]


def _parse_clock_to_elapsed_seconds(pctimestring: str, period: int) -> Optional[int]:
    try:
        # NBA clock shows time remaining in period
        s = str(pctimestring or "").strip()
        if ":" not in s:
            return None
        mm, ss = s.split(":", 1)
        rem = int(mm) * 60 + int(ss)
        period_len = 12 * 60 if int(period) <= 4 else 5 * 60
        elapsed_in_period = period_len - rem
        return int((int(period) - 1) * period_len + elapsed_in_period)
    except Exception:
        return None


def _first_sub_in(pbp: pd.DataFrame, team_id: int) -> tuple[Optional[str], Optional[str]]:
    if pbp is None or pbp.empty:
        return None, None
    cols = {c.upper(): c for c in pbp.columns}
    msg_col = cols.get("EVENTMSGTYPE")
    period_col = cols.get("PERIOD")
    time_col = cols.get("PCTIMESTRING")
    p2_col = cols.get("PLAYER2_NAME")
    t1_col = cols.get("PLAYER1_TEAM_ID")
    t2_col = cols.get("PLAYER2_TEAM_ID")

    if not msg_col or not period_col or not time_col or not p2_col:
        return None, None

    sub = pbp[pd.to_numeric(pbp[msg_col], errors="coerce") == 8].copy()
    if sub.empty:
        return None, None

    # Filter substitution-in team id. Depending on endpoint, team id may be in PLAYER1_TEAM_ID or PLAYER2_TEAM_ID.
    if t2_col and t2_col in sub.columns:
        m = pd.to_numeric(sub[t2_col], errors="coerce") == int(team_id)
        if bool(m.any()):
            sub = sub[m].copy()
    elif t1_col and t1_col in sub.columns:
        m = pd.to_numeric(sub[t1_col], errors="coerce") == int(team_id)
        if bool(m.any()):
            sub = sub[m].copy()

    if sub.empty:
        return None, None

    sub["_period"] = pd.to_numeric(sub[period_col], errors="coerce").fillna(99).astype(int)
    sub["_elapsed"] = sub.apply(lambda r: _parse_clock_to_elapsed_seconds(r.get(time_col), int(r.get("_period") or 1)) or 10**9, axis=1)
    sub = sub.sort_values(["_period", "_elapsed"], ascending=[True, True])
    r0 = sub.iloc[0]
    return str(r0.get(p2_col) or "").strip() or None, str(r0.get(time_col) or "").strip() or None


def _fetch_actual_game_context(game_id: str, home_tri: str, away_tri: str) -> ActualGameContext:
    # nba_api imports inside to avoid slow import if not used
    from nba_api.stats.endpoints import boxscoresummaryv2, boxscoretraditionalv2, playbyplayv2  # type: ignore

    _configure_nba_api_headers()

    def _retry(fetch_fn, tries: int = 3) -> dict[str, Any]:
        last: Exception | None = None
        for _ in range(max(1, int(tries))):
            try:
                return fetch_fn()
            except Exception as e:
                last = e
                continue
        if last is not None:
            raise last
        return {}

    def _fetch_summary() -> dict[str, Any]:
        bs = boxscoresummaryv2.BoxScoreSummaryV2(game_id=game_id, timeout=30)
        return bs.get_normalized_dict() or {}

    def _fetch_trad() -> dict[str, Any]:
        bs = boxscoretraditionalv2.BoxScoreTraditionalV2(game_id=game_id, timeout=30)
        return bs.get_normalized_dict() or {}

    def _fetch_pbp() -> dict[str, Any]:
        pbp = playbyplayv2.PlayByPlayV2(game_id=game_id, timeout=30)
        return pbp.get_normalized_dict() or {}

    nd_sum = _fetch_nba_api_cached("boxscoresummaryv2", game_id, lambda: _retry(_fetch_summary, tries=3))
    nd_trad = _fetch_nba_api_cached("boxscoretraditionalv2", game_id, lambda: _retry(_fetch_trad, tries=3))
    nd_pbp = _fetch_nba_api_cached("playbyplayv2", game_id, lambda: _retry(_fetch_pbp, tries=3))

    linescore = pd.DataFrame((nd_sum or {}).get("LineScore", []))
    quarters, hpts, apts = _actual_quarters_from_linescore(linescore, home_tri, away_tri)

    trad_players = pd.DataFrame((nd_trad or {}).get("PlayerStats", []))

    starters_home = _extract_starters(trad_players, home_tri)
    starters_away = _extract_starters(trad_players, away_tri)

    # Determine team ids for first-sub filtering
    team_df = pd.DataFrame((nd_sum or {}).get("GameSummary", []))
    home_tid = None
    away_tid = None
    try:
        if not team_df.empty:
            cols = {c.upper(): c for c in team_df.columns}
            ht = cols.get("HOME_TEAM_ID")
            at = cols.get("VISITOR_TEAM_ID") or cols.get("AWAY_TEAM_ID")
            if ht:
                home_tid = int(pd.to_numeric(team_df.iloc[0].get(ht), errors="coerce"))
            if at:
                away_tid = int(pd.to_numeric(team_df.iloc[0].get(at), errors="coerce"))
    except Exception:
        home_tid = None
        away_tid = None

    pbp_df = pd.DataFrame((nd_pbp or {}).get("PlayByPlay", []))

    first_home, time_home = (None, None)
    first_away, time_away = (None, None)
    if home_tid is not None:
        first_home, time_home = _first_sub_in(pbp_df, int(home_tid))
    if away_tid is not None:
        first_away, time_away = _first_sub_in(pbp_df, int(away_tid))

    return ActualGameContext(
        home_tri=home_tri,
        away_tri=away_tri,
        home_pts=int(hpts),
        away_pts=int(apts),
        quarters=quarters,
        starters_home=starters_home,
        starters_away=starters_away,
        first_sub_in_home=first_home,
        first_sub_in_away=first_away,
        first_sub_time_home=time_home,
        first_sub_time_away=time_away,
    )


def _row_winner(home_pts: int, away_pts: int, home_tri: str, away_tri: str) -> str:
    if home_pts > away_pts:
        return str(home_tri)
    if away_pts > home_pts:
        return str(away_tri)
    return "TIE"


def main() -> int:
    ap = argparse.ArgumentParser(description="Reconcile connected sim vs actual (last N days): scores, quarters, starters, first bench")
    ap.add_argument("--end", type=str, default=None, help="End date (YYYY-MM-DD), default=max date in player_logs")
    ap.add_argument("--days", type=int, default=7, help="Days ending at --end")
    ap.add_argument("--n-quarter-samples", type=int, default=800)
    ap.add_argument("--n-connected-samples", type=int, default=80)
    ap.add_argument("--minutes-lookback-days", type=int, default=45)
    ap.add_argument("--top-k", type=int, default=10)
    ap.add_argument("--skip-ot", action="store_true")
    ap.add_argument("--max-games", type=int, default=0, help="Optional cap for debugging (0=all)")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--out-games-csv", type=str, default=None)
    ap.add_argument("--out-players-csv", type=str, default=None)
    ap.add_argument("--out-player-q-pts-csv", type=str, default=None, help="Optional: ESPN play-by-play derived points per player per quarter")
    ap.add_argument("--out-json", type=str, default=None)
    args = ap.parse_args()

    logs = _load_player_logs()

    if args.end:
        end_d = _parse_date(args.end)
    else:
        logs_dt = pd.to_datetime(logs.get("GAME_DATE"), errors="coerce")
        end_ts = logs_dt.max()
        if pd.isna(end_ts):
            raise SystemExit("Could not infer end date from player_logs")
        end_d = end_ts.date()

    start_d = end_d - timedelta(days=int(args.days) - 1)

    out_games = Path(args.out_games_csv) if args.out_games_csv else (PROC / f"connected_reconcile_games_{start_d.isoformat()}_{end_d.isoformat()}.csv")
    out_players = Path(args.out_players_csv) if args.out_players_csv else (PROC / f"connected_reconcile_players_{start_d.isoformat()}_{end_d.isoformat()}.csv")
    out_player_q = Path(args.out_player_q_pts_csv) if args.out_player_q_pts_csv else (PROC / f"connected_reconcile_player_quarter_points_{start_d.isoformat()}_{end_d.isoformat()}.csv")
    out_json = Path(args.out_json) if args.out_json else (PROC / f"connected_reconcile_summary_{start_d.isoformat()}_{end_d.isoformat()}.json")

    # Lazy imports (project code)
    import sys

    if str(SRC) not in sys.path:
        sys.path.insert(0, str(SRC))

    from nba_betting.sim.quarters import GameInputs, TeamContext, simulate_quarters  # type: ignore
    from nba_betting.sim.connected_game import simulate_connected_game  # type: ignore
    from nba_betting.player_priors import PlayerPriorsConfig, compute_player_priors  # type: ignore
    from nba_betting.teams import to_tricode  # type: ignore

    game_rows: list[dict[str, Any]] = []
    player_rows: list[dict[str, Any]] = []
    player_q_rows: list[dict[str, Any]] = []

    games_done = 0

    for d in _daterange(start_d, end_d):
        preds = _load_predictions(d)
        props = _load_props_predictions(d)
        if preds is None or props is None or preds.empty:
            continue

        preds = preds.copy()
        if "home_team" in preds.columns:
            preds["home_tri"] = preds["home_team"].astype(str).map(lambda x: _norm_tri(to_tricode(str(x)) or str(x)))
        if "visitor_team" in preds.columns:
            preds["away_tri"] = preds["visitor_team"].astype(str).map(lambda x: _norm_tri(to_tricode(str(x)) or str(x)))

        games = _games_from_logs_for_date(logs, d)
        if games.empty:
            continue

        # minutes priors from logs (simple avg minutes over lookback)
        lookback_start = d - timedelta(days=int(args.minutes_lookback_days) - 1)
        logs_dt = pd.to_datetime(logs.get("GAME_DATE"), errors="coerce").dt.date
        mask = (logs_dt >= lookback_start) & (logs_dt <= d)
        lb = logs[mask].copy()
        lb["TEAM_ABBREVIATION"] = lb.get("TEAM_ABBREVIATION").astype(str).str.upper().str.strip()
        lb["PLAYER_NAME"] = lb.get("PLAYER_NAME").astype(str)

        def _to_min(v: Any) -> float:
            try:
                if isinstance(v, str) and ":" in v:
                    mm, ss = v.split(":", 1)
                    return float(mm) + float(ss) / 60.0
                return float(pd.to_numeric(v, errors="coerce") or 0.0)
            except Exception:
                return 0.0

        lb["MIN_F"] = lb.get("MIN").map(_to_min)
        grp = lb.groupby(["TEAM_ABBREVIATION", "PLAYER_NAME"], dropna=False)["MIN_F"].mean().reset_index()
        minutes_priors: dict[tuple[str, str], float] = {}
        for _, r in grp.iterrows():
            tri = _norm_tri(r.get("TEAM_ABBREVIATION"))
            nm = str(r.get("PLAYER_NAME") or "").strip()
            key = _norm_player_key(nm)
            m = _safe_float(r.get("MIN_F"), 0.0)
            if tri and key and m > 0:
                minutes_priors[(tri, key)] = float(m)

        try:
            pri = compute_player_priors(
                d.isoformat(),
                cfg=PlayerPriorsConfig(days_back=int(args.minutes_lookback_days), min_games=3, min_minutes_avg=4.0),
            )
            player_priors = pri.rates
        except Exception:
            player_priors = {}

        for _, g in games.iterrows():
            gid = str(g.get("game_id"))
            htri = _norm_tri(g.get("home_tri"))
            atri = _norm_tri(g.get("away_tri"))
            if not gid or not htri or not atri:
                continue

            pr = preds[(preds.get("home_tri") == htri) & (preds.get("away_tri") == atri)]
            flipped = False
            if pr.empty:
                pr = preds[(preds.get("home_tri") == atri) & (preds.get("away_tri") == htri)]
                flipped = not pr.empty
            if pr.empty:
                continue

            r = pr.iloc[0].copy()
            if flipped:
                r["home_team"], r["visitor_team"] = r.get("visitor_team"), r.get("home_team")
                r["home_tri"], r["away_tri"] = htri, atri
                if "spread_margin" in r.index:
                    r["spread_margin"] = -_safe_float(r.get("spread_margin"), 0.0)
                if "home_spread" in r.index:
                    r["home_spread"] = -_safe_float(r.get("home_spread"), 0.0)

            # Actual rosters for this game from logs
            gdf = logs[logs.get("GAME_ID").astype(str) == gid].copy()
            gdf["TEAM_ABBREVIATION"] = gdf.get("TEAM_ABBREVIATION").astype(str).str.upper().str.strip()
            gdf["MIN_F"] = gdf.get("MIN").map(_to_min)
            gdf = gdf[gdf["MIN_F"] > 0]

            def _top_names(tri: str) -> list[str]:
                gg = gdf[gdf["TEAM_ABBREVIATION"] == tri]
                if gg.empty:
                    return []
                gg = gg.sort_values(["MIN_F", "PTS"], ascending=[False, False])
                return [str(x).strip() for x in gg.get("PLAYER_NAME").dropna().astype(str).tolist() if str(x).strip()]

            home_roster = _top_names(htri)
            away_roster = _top_names(atri)
            if not home_roster or not away_roster:
                continue

            # Skip OT when requested.
            if args.skip_ot:
                hm = float(gdf[gdf["TEAM_ABBREVIATION"] == htri]["MIN_F"].sum())
                am = float(gdf[gdf["TEAM_ABBREVIATION"] == atri]["MIN_F"].sum())
                if hm > 245.0 or am > 245.0:
                    continue

            # Build contexts from predictions row (best-effort)
            pred_total = _safe_float(r.get("pred_total"), np.nan)
            if not np.isfinite(pred_total):
                pred_total = _safe_float(r.get("totals"), np.nan)
            pred_margin = _safe_float(r.get("pred_margin"), np.nan)
            if not np.isfinite(pred_margin):
                pred_margin = _safe_float(r.get("spread_margin"), np.nan)

            home_mu_implied = (0.5 * (pred_total + pred_margin)) if np.isfinite(pred_total) and np.isfinite(pred_margin) else None
            away_mu_implied = (0.5 * (pred_total - pred_margin)) if np.isfinite(pred_total) and np.isfinite(pred_margin) else None

            home_pace = _safe_float(r.get("home_pace"), 98.0)
            away_pace = _safe_float(r.get("away_pace"), 98.0)

            def _rating_from_mu(mu: Optional[float], pace: float) -> float:
                if mu is None:
                    return 112.0
                try:
                    return float((float(mu) / max(1e-6, float(pace))) * 100.0)
                except Exception:
                    return 112.0

            home_off = _safe_float(r.get("home_off_rating"), _rating_from_mu(home_mu_implied, home_pace))
            away_off = _safe_float(r.get("away_off_rating"), _rating_from_mu(away_mu_implied, away_pace))
            home_def = _safe_float(r.get("home_def_rating"), 112.0)
            away_def = _safe_float(r.get("away_def_rating"), 112.0)

            home_ctx = TeamContext(team=str(r.get("home_team") or htri), pace=float(home_pace), off_rating=float(home_off), def_rating=float(home_def), injuries_out=0)
            away_ctx = TeamContext(team=str(r.get("visitor_team") or atri), pace=float(away_pace), off_rating=float(away_off), def_rating=float(away_def), injuries_out=0)

            market_total = _safe_float(r.get("total"), np.nan)
            market_home_spread = _safe_float(r.get("home_spread"), np.nan)
            market_total = None if not np.isfinite(market_total) else float(market_total)
            market_home_spread = None if not np.isfinite(market_home_spread) else float(market_home_spread)

            inp = GameInputs(date=d.isoformat(), home=home_ctx, away=away_ctx, market_total=market_total, market_home_spread=market_home_spread)
            qsum = simulate_quarters(inp, n_samples=int(args.n_quarter_samples))
            sim = simulate_connected_game(
                qsum.quarters,
                home_tri=htri,
                away_tri=atri,
                props_df=props,
                home_roster=home_roster,
                away_roster=away_roster,
                minutes_priors=minutes_priors,
                player_priors=player_priors,
                minutes_lookback_days=int(args.minutes_lookback_days),
                n_samples=int(args.n_connected_samples),
                seed=int(args.seed) + int(gid[-4:]) if gid[-4:].isdigit() else int(args.seed),
            )
            if not isinstance(sim, dict) or sim.get("error"):
                continue

            rep = sim.get("rep") or {}

            # Actual: finals + quarters + starters + first sub
            act, pts_q_df = _fetch_actual_game_context_espn(d.isoformat(), htri, atri)
            if isinstance(pts_q_df, pd.DataFrame) and not pts_q_df.empty:
                for _, prr in pts_q_df.iterrows():
                    team_tri = _espn_to_tri(str(prr.get("team") or "").strip())
                    player_q_rows.append(
                        {
                            "date": d.isoformat(),
                            "game_id": gid,
                            "team": team_tri,
                            "player_name": str(prr.get("player_name") or "").strip(),
                            "q": int(_safe_int(prr.get("q"), 0)),
                            "pts": int(_safe_int(prr.get("pts"), 0)),
                        }
                    )

            sim_h = _safe_int(rep.get("home_score"), 0)
            sim_a = _safe_int(rep.get("away_score"), 0)
            act_h = int(act.home_pts)
            act_a = int(act.away_pts)

            # Quarters
            sim_q = rep.get("quarters") or []
            act_q = act.quarters or []

            def _qget(rows: list[dict[str, Any]], q: int, side: str) -> int:
                for rr in rows:
                    if int(rr.get("q") or 0) == int(q):
                        return _safe_int(rr.get(side), 0)
                return 0

            # Per-player totals: actual from logs, sim from rep box
            def _act_team_box(tri: str) -> pd.DataFrame:
                gg = gdf[gdf["TEAM_ABBREVIATION"] == tri].copy()
                if gg.empty:
                    return pd.DataFrame(columns=["player_key", "player_name", "min", "pts"]) 
                out = pd.DataFrame(
                    {
                        "player_name": gg.get("PLAYER_NAME").astype(str),
                        "min": gg.get("MIN_F").astype(float),
                        "pts": pd.to_numeric(gg.get("PTS"), errors="coerce").fillna(0.0),
                        "reb": pd.to_numeric(gg.get("REB"), errors="coerce").fillna(0.0),
                        "ast": pd.to_numeric(gg.get("AST"), errors="coerce").fillna(0.0),
                        "threes": pd.to_numeric(gg.get("FG3M"), errors="coerce").fillna(0.0),
                        "tov": pd.to_numeric(gg.get("TOV"), errors="coerce").fillna(0.0),
                    }
                )
                out["player_key"] = out["player_name"].map(_norm_player_key)
                out = out[out["player_key"].ne("")].copy()
                return out.groupby("player_key", as_index=False).agg({"player_name": "first", "min": "sum", "pts": "sum", "reb": "sum", "ast": "sum", "threes": "sum", "tov": "sum"})

            def _sim_team_box(key: str) -> pd.DataFrame:
                box = (rep or {}).get(key) or {}
                players = box.get("players") or []
                df = pd.DataFrame(players)
                if df.empty:
                    return pd.DataFrame(columns=["player_key", "player_name", "min", "pts"]) 
                df = df.copy()
                df["player_name"] = df.get("player_name").astype(str)
                df["player_key"] = df["player_name"].map(_norm_player_key)
                for c in ("min", "pts", "reb", "ast", "threes", "tov"):
                    if c in df.columns:
                        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)
                    else:
                        df[c] = 0.0
                df = df[df["player_key"].ne("")].copy()
                return df.groupby("player_key", as_index=False).agg({"player_name": "first", "min": "sum", "pts": "sum", "reb": "sum", "ast": "sum", "threes": "sum", "tov": "sum"})

            act_home_box = _act_team_box(htri)
            act_away_box = _act_team_box(atri)
            sim_home_box = _sim_team_box("home_box")
            sim_away_box = _sim_team_box("away_box")

            for team, act_box, sim_box, starters in (
                (htri, act_home_box, sim_home_box, act.starters_home),
                (atri, act_away_box, sim_away_box, act.starters_away),
            ):
                m = act_box.merge(sim_box, on="player_key", how="outer", suffixes=("_act", "_sim"))
                m["player_name"] = m.get("player_name_act").fillna(m.get("player_name_sim")).fillna("")
                m["is_starter"] = m["player_name"].map(lambda nm: _norm_player_key(nm) in set(_norm_player_key(x) for x in starters))
                # Rank by actual minutes (top-k)
                m["min_act"] = pd.to_numeric(m.get("min_act"), errors="coerce").fillna(0.0)
                m = m.sort_values("min_act", ascending=False).head(int(args.top_k)).copy()
                for _, rr in m.iterrows():
                    player_rows.append(
                        {
                            "date": d.isoformat(),
                            "game_id": gid,
                            "team": team,
                            "player_name": str(rr.get("player_name") or "").strip(),
                            "is_starter": bool(rr.get("is_starter")),
                            "min_act": float(rr.get("min_act") or 0.0),
                            "min_sim": float(rr.get("min_sim") or 0.0),
                            "pts_act": float(rr.get("pts_act") or 0.0),
                            "pts_sim": float(rr.get("pts_sim") or 0.0),
                            "reb_act": float(rr.get("reb_act") or 0.0),
                            "reb_sim": float(rr.get("reb_sim") or 0.0),
                            "ast_act": float(rr.get("ast_act") or 0.0),
                            "ast_sim": float(rr.get("ast_sim") or 0.0),
                            "threes_act": float(rr.get("threes_act") or 0.0),
                            "threes_sim": float(rr.get("threes_sim") or 0.0),
                            "tov_act": float(rr.get("tov_act") or 0.0),
                            "tov_sim": float(rr.get("tov_sim") or 0.0),
                        }
                    )

            game_rows.append(
                {
                    "date": d.isoformat(),
                    "game_id": gid,
                    "home_tri": htri,
                    "away_tri": atri,
                    "act_home_pts": act_h,
                    "act_away_pts": act_a,
                    "act_winner": _row_winner(act_h, act_a, htri, atri),
                    "sim_home_pts": sim_h,
                    "sim_away_pts": sim_a,
                    "sim_winner": _row_winner(sim_h, sim_a, htri, atri),
                    "abs_err_home": abs(sim_h - act_h) if (act_h or act_a) else None,
                    "abs_err_away": abs(sim_a - act_a) if (act_h or act_a) else None,
                    "act_q1_home": _qget(act_q, 1, "home"),
                    "act_q1_away": _qget(act_q, 1, "away"),
                    "act_q2_home": _qget(act_q, 2, "home"),
                    "act_q2_away": _qget(act_q, 2, "away"),
                    "act_q3_home": _qget(act_q, 3, "home"),
                    "act_q3_away": _qget(act_q, 3, "away"),
                    "act_q4_home": _qget(act_q, 4, "home"),
                    "act_q4_away": _qget(act_q, 4, "away"),
                    "sim_q1_home": _qget(sim_q, 1, "home"),
                    "sim_q1_away": _qget(sim_q, 1, "away"),
                    "sim_q2_home": _qget(sim_q, 2, "home"),
                    "sim_q2_away": _qget(sim_q, 2, "away"),
                    "sim_q3_home": _qget(sim_q, 3, "home"),
                    "sim_q3_away": _qget(sim_q, 3, "away"),
                    "sim_q4_home": _qget(sim_q, 4, "home"),
                    "sim_q4_away": _qget(sim_q, 4, "away"),
                    "starters_home": ";".join(act.starters_home or []),
                    "starters_away": ";".join(act.starters_away or []),
                    "first_sub_in_home": act.first_sub_in_home,
                    "first_sub_time_home": act.first_sub_time_home,
                    "first_sub_in_away": act.first_sub_in_away,
                    "first_sub_time_away": act.first_sub_time_away,
                    "sim_used_target_rep": bool((sim.get("diagnostics") or {}).get("used_target_rep")),
                    "sim_warnings": ";".join(((sim.get("diagnostics") or {}).get("warnings") or [])),
                }
            )

            games_done += 1
            if games_done % 5 == 0:
                print(f"Processed {games_done} games...")

            if int(args.max_games) > 0 and games_done >= int(args.max_games):
                break

        if int(args.max_games) > 0 and games_done >= int(args.max_games):
            break

    games_df = pd.DataFrame(game_rows)
    players_df = pd.DataFrame(player_rows)
    player_q_df = pd.DataFrame(player_q_rows)

    games_df.to_csv(out_games, index=False)
    players_df.to_csv(out_players, index=False)
    if not player_q_df.empty:
        player_q_df.to_csv(out_player_q, index=False)

    summary: dict[str, Any] = {
        "start": start_d.isoformat(),
        "end": end_d.isoformat(),
        "days": int(args.days),
        "games": int(len(games_df)),
        "players_rows": int(len(players_df)),
        "winner_match_rate": None,
        "mean_abs_err_total": None,
    }

    try:
        if not games_df.empty:
            m = games_df[games_df["act_winner"].notna() & games_df["sim_winner"].notna()].copy()
            if not m.empty:
                summary["winner_match_rate"] = float((m["act_winner"] == m["sim_winner"]).mean())
            if "abs_err_home" in games_df.columns and "abs_err_away" in games_df.columns:
                ae = pd.to_numeric(games_df["abs_err_home"], errors="coerce").fillna(0) + pd.to_numeric(games_df["abs_err_away"], errors="coerce").fillna(0)
                summary["mean_abs_err_total"] = float(ae.mean())
    except Exception:
        pass

    out_json.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"Wrote: {out_games}")
    print(f"Wrote: {out_players}")
    if not player_q_df.empty:
        print(f"Wrote: {out_player_q}")
    print(f"Wrote: {out_json}")
    print(json.dumps(summary, indent=2))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
