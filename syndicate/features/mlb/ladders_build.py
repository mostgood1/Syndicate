"""Build the MLB ladders artifact NATIVELY, retiring the vendor writer. `#440`.

**Why this exists.** The only thing that ever wrote `daily_ladders_<date>.json`
was `write_daily_ladders_artifact` inside the VENDOR Flask frontend
(`vendor/.../flask_frontend.py:4058`), fired on-request when it noticed the
artifact was stale. Syndicate inherited the reader (`cards.py:1273`,
`ladders_common.py:142`) and the presenter (`pitcher_ladders.py`) and never the
producer. Measured 2026-08-19: the ladder artifact was generated at
2026-08-18T18:20 and the odds it needs arrived at 2026-08-19T18:16 — **~19 hours
later** — so every served row carried a full sim side and an empty market side:

    Mean 4.66   Over "-"   Mode 4   Sim count 994
    "Market line: -"   "Over probability: -"

Sims were never the problem: 24 `daily_sim` runs that day, every 15-20 minutes.

**This is assembly, not invention.** Both inputs already have native readers and
the output schema is pinned by the existing native consumer:

    SIM     `daily_sim_artifact_path(date, game_pk)`
              -> sim.pitcher_props[<mlbam_id>].so_dist   (outcome histogram)
                                               .so_mean
    MARKET  `daily_snapshot_oddsapi_pitcher_props_path(date)`
              -> pitcher_props[<lowercase name>].strikeouts.line
    SCHEMA  `ladders_common.pitcher_rows_from_summary` reads pitcherName, team,
            matchup, marketLine, mean, mode, overLineProb, simCount
    SHAPE   groups.pitcher.strikeouts.rows[]  (`_extract_prop_group`)

`mode` is the argmax of the histogram and `overLineProb` is the mass above the
line — arithmetic on data that already exists, not a new model.

**THE JOIN IS THE DANGEROUS PART AND IT IS REPORTED, NOT HIDDEN.** The sim keys
on `mlbam_id` and the odds key on a lowercase display name. A name->id join
silently drops rows, and a thin card looks identical to a correct one. So the
artifact carries `matchedPitchers` / `unmatchedOdds` / `unmatchedNames` and the
builder REFUSES to overwrite a good artifact with an empty one.
"""

from __future__ import annotations

import json
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from syndicate.features.mlb.sources import daily_ladders_path
from syndicate.features.mlb.sources import daily_sim_artifact_path
from syndicate.features.mlb.sources import daily_snapshot_oddsapi_hitter_props_path
from syndicate.features.mlb.sources import daily_snapshot_oddsapi_pitcher_props_path

# Only strikeouts for now: it is what the compact card reads first, via
# `_extract_prop_group(summary, "pitcher", "strikeouts")`. The sim artifact
# carries outs/pitches/hits/earned_runs/walks/batters_faced on the same shape,
# so widening is adding rows to this table -- not new plumbing.
# prop_key -> sim histogram field, sim mean field, odds field, card label.
#
# `odds: None` is DELIBERATE and not a gap in this table: the feed carries no
# market for those props. They still get rows -- a projection with no line is
# useful and honest -- and they are excluded from the join accounting so an
# absent market never reads as a broken join.
PITCHER_PROPS: dict[str, dict[str, Any]] = {
    "strikeouts":    {"dist": "so_dist",            "mean": "so_mean",            "odds": "strikeouts",     "label": "Strikeouts"},
    "outs":          {"dist": "outs_dist",          "mean": "outs_mean",          "odds": "outs",           "label": "Outs"},
    "hits_allowed":  {"dist": "hits_dist",          "mean": "hits_mean",          "odds": "hits_allowed",   "label": "Hits allowed"},
    "earned_runs":   {"dist": "earned_runs_dist",   "mean": "er_mean",            "odds": "earned_runs",    "label": "Earned runs"},
    "walks_allowed": {"dist": "walks_dist",         "mean": "walks_mean",         "odds": "walks_allowed",  "label": "Walks allowed"},
    "pitches":       {"dist": "pitches_dist",       "mean": "pitches_mean",       "odds": None,             "label": "Pitches"},
    "batters_faced": {"dist": "batters_faced_dist", "mean": "batters_faced_mean", "odds": None,             "label": "Batters faced"},
}

HITTER_PROPS: dict[str, dict[str, Any]] = {
    "hits":              {"dist": "hits_dist",            "mean": "h_mean",   "odds": "batter_hits",            "label": "Hits"},
    "hits_runs_rbis":    {"dist": "hits_runs_rbis_dist",  "mean": "hrr_mean", "odds": "batter_hits_runs_rbis",  "label": "H+R+RBI"},
    "home_runs":         {"dist": "home_runs_dist",       "mean": "hr_mean",  "odds": "batter_home_runs",       "label": "Home runs"},
    "total_bases":       {"dist": "total_bases_dist",     "mean": "tb_mean",  "odds": "batter_total_bases",     "label": "Total bases"},
    "runs":              {"dist": "runs_dist",            "mean": "r_mean",   "odds": "batter_runs_scored",     "label": "Runs"},
    "rbi":               {"dist": "rbi_dist",             "mean": "rbi_mean", "odds": "batter_rbis",            "label": "RBI"},
    "hitter_strikeouts": {"dist": "strikeouts_dist",      "mean": "so_mean",  "odds": None,                     "label": "Strikeouts"},
    "doubles":           {"dist": "doubles_dist",         "mean": "2b_mean",  "odds": None,                     "label": "Doubles"},
    "triples":           {"dist": "triples_dist",         "mean": "3b_mean",  "odds": None,                     "label": "Triples"},
    "stolen_bases":      {"dist": "stolen_bases_dist",    "mean": "sb_mean",  "odds": None,                     "label": "Stolen bases"},
}


def _norm_name(value: Any) -> str:
    """Fold a display name to a join key.

    Accents and punctuation are the whole reason this is not `.lower()`:
    the odds feed writes "jose ramirez" where the roster says "José Ramírez",
    and a bare lower() drops that pitcher silently.
    """
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(c for c in text if not unicodedata.combining(c))
    return " ".join(text.replace(".", " ").replace("-", " ").lower().split())


def _dist_stats(dist: Any, line: float | None) -> dict[str, Any]:
    """mean / mode / P(over line) from an outcome histogram.

    Returns `overLineProb=None` when there is no line, rather than 0.0 — a
    zero probability and an absent market are different facts and the card
    renders them differently.
    """
    if not isinstance(dist, dict) or not dist:
        return {"mode": None, "overLineProb": None, "simCount": 0}
    counts: dict[int, int] = {}
    for k, v in dist.items():
        try:
            counts[int(k)] = int(v)
        except Exception:
            continue
    total = sum(counts.values())
    if total <= 0:
        return {"mode": None, "overLineProb": None, "simCount": 0}
    mode = max(counts.items(), key=lambda kv: kv[1])[0]
    over = None
    if line is not None:
        # strictly greater than the line: a 5.5 line means 6+ is a win, and
        # a whole-number line pushes rather than wins, which this respects.
        over = sum(c for outcome, c in counts.items() if outcome > line) / total
    return {"mode": mode, "overLineProb": over, "simCount": total}


def _market_lines(date_str: str, side: str = "pitcher") -> dict[str, dict[str, Any]]:
    """{normalised player name -> {odds prop -> {line, over_odds}}}"""
    if side == "hitter":
        path = daily_snapshot_oddsapi_hitter_props_path(date_str)
        doc_key = "hitter_props"
    else:
        path = daily_snapshot_oddsapi_pitcher_props_path(date_str)
        doc_key = "pitcher_props"
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return {}
    props = doc.get(doc_key) if isinstance(doc.get(doc_key), dict) else {}
    out: dict[str, dict[str, Any]] = {}
    for name, per_prop in props.items():
        if isinstance(per_prop, dict):
            out[_norm_name(name)] = per_prop
    return out


def _sim_games(date_str: str, game_pks: list[int]) -> list[tuple[int, dict[str, Any]]]:
    games: list[tuple[int, dict[str, Any]]] = []
    for game_pk in game_pks:
        path = daily_sim_artifact_path(date_str, int(game_pk))
        if path is None:
            continue
        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(payload, dict):
            games.append((int(game_pk), payload))
    return games


def _team_abbr(payload, side):
    """`away`/`home` are OBJECTS ({team_id, name, abbreviation}), not strings.
    Stringifying them put a whole dict into `team` and `matchup`, which the card
    rendered verbatim -- caught by running the real reader, not by types."""
    node = payload.get(side)
    if isinstance(node, dict):
        return str(node.get("abbreviation") or node.get("name") or "").strip()
    return str(node or "").strip()


def _starter_index(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """{mlbam_id -> {name, team, opponent, matchup}} for this game's starters."""
    away = _team_abbr(payload, "away")
    home = _team_abbr(payload, "home")
    out: dict[str, dict[str, Any]] = {}
    starters = payload.get("starters") if isinstance(payload.get("starters"), dict) else {}
    names = payload.get("starter_names") if isinstance(payload.get("starter_names"), dict) else {}
    for side in ("away", "home"):
        pid = starters.get(side)
        if pid in (None, ""):
            continue
        team = away if side == "away" else home
        opp = home if side == "away" else away
        out[str(pid)] = {
            "name": str(names.get(side) or "").strip(),
            "team": team,
            "opponent": opp,
            "matchup": f"{away} @ {home}".strip(" @"),
        }
    return out


def _prop_group(rows, spec, *, matched, odds_total, unmatched_odds, unmatched_sim):
    rows.sort(key=lambda r: (r.get("mean") is None, -(r.get("mean") or 0)))
    group = {
        "found": bool(rows),
        "propLabel": spec["label"],
        "rows": rows,
        # THE JOIN, PUBLISHED. A thin card and a broken join look identical
        # without these numbers.
        "matchedPlayers": matched,
        "oddsPlayers": odds_total,
        "unmatchedOdds": unmatched_odds,
        "unmatchedSimNames": unmatched_sim,
    }
    if spec.get("odds") is None:
        # No market EXISTS for this prop, so zero matches is not a failed join.
        # Saying so is the difference between "no market" and "join broken".
        group["marketAvailable"] = False
    return group


def _rows_for_prop(entries, spec, market, name_key):
    """entries: iterable of (player_id, sim_stats, meta{name,team,opponent,matchup})"""
    rows = []
    matched = 0
    unmatched_sim = []
    seen = set()
    odds_field = spec.get("odds")

    for pid, stats, meta in entries:
        name = str(meta.get("name") or "").strip()
        key = _norm_name(name)
        per_prop = market.get(key) if key else None
        if odds_field is not None:
            if per_prop is not None:
                seen.add(key)
                matched += 1
            elif name:
                unmatched_sim.append(name)

        line = None
        if odds_field is not None and isinstance(per_prop, dict):
            entry = per_prop.get(odds_field)
            if isinstance(entry, dict):
                try:
                    line = float(entry.get("line"))
                except Exception:
                    line = None
        stats_out = _dist_stats(stats.get(spec["dist"]), line)
        rows.append({
            name_key: name or f"id {pid}",
            "playerId": pid,
            "team": meta.get("team") or "",
            "opponent": meta.get("opponent") or "",
            "matchup": meta.get("matchup") or "",
            "marketLine": line,
            "mean": stats.get(spec["mean"]),
            "mode": stats_out["mode"],
            "overLineProb": stats_out["overLineProb"],
            "simCount": stats_out["simCount"],
        })

    return _prop_group(
        rows, spec,
        matched=matched,
        odds_total=len(market) if odds_field is not None else 0,
        unmatched_odds=sorted(set(market) - seen) if odds_field is not None else [],
        unmatched_sim=sorted(set(unmatched_sim)),
    )


def _pitcher_entries(date_str, game_pks):
    for _pk, payload in _sim_games(date_str, game_pks):
        sim = payload.get("sim") if isinstance(payload.get("sim"), dict) else {}
        props = sim.get("pitcher_props") if isinstance(sim.get("pitcher_props"), dict) else {}
        starters = _starter_index(payload)
        for pid, stats in props.items():
            if isinstance(stats, dict):
                yield str(pid), stats, (starters.get(str(pid)) or {})


def _hitter_entries(date_str, game_pks):
    """Hitters carry `name` and `team` on the entry itself, so no starter index."""
    for _pk, payload in _sim_games(date_str, game_pks):
        sim = payload.get("sim") if isinstance(payload.get("sim"), dict) else {}
        props = sim.get("hitter_props") if isinstance(sim.get("hitter_props"), dict) else {}
        away = _team_abbr(payload, "away")
        home = _team_abbr(payload, "home")
        for pid, stats in props.items():
            if not isinstance(stats, dict):
                continue
            team = str(stats.get("team") or "").strip()
            opp = home if team == away else away
            yield str(pid), stats, {
                "name": str(stats.get("name") or "").strip(),
                "team": team,
                "opponent": opp,
                "matchup": f"{away} @ {home}".strip(" @"),
            }


def build_pitcher_strikeout_rows(date_str, game_pks):
    """Named entry point kept: this is the group the compact card reads first."""
    entries = list(_pitcher_entries(date_str, game_pks))
    return _rows_for_prop(entries, PITCHER_PROPS["strikeouts"],
                          _market_lines(date_str, "pitcher"), "pitcherName")


def discover_game_pks(date_str: str) -> list[int]:
    """Game pks from whatever sims exist on disk for this date.

    NOT from `--only-game-pks`: that argument is present on a scoped resim and
    absent on a full run, so a trigger relying on it would rebuild only part of
    the board on full runs and look correct on scoped ones.
    """
    pks: set[int] = set()
    probe = daily_sim_artifact_path(date_str, 1)
    roots: list[Path] = []
    if probe is not None:
        roots.append(Path(probe).parent)
    else:
        from syndicate.features.mlb.sources import _artifact_roots, _source_roots  # type: ignore
        for root in [*_artifact_roots(), *_source_roots()]:
            roots.append(Path(root) / "data" / "daily" / "sims" / date_str)
            roots.append(Path(root) / "source_artifacts" / "data" / "daily" / "sims" / date_str)
    for d in roots:
        try:
            if not d.is_dir():
                continue
        except Exception:
            continue
        for f in d.glob("sim_*_pk*_*.json"):
            m = re.search(r"pk(\d+)", f.name)
            if m:
                pks.add(int(m.group(1)))
    return sorted(pks)


def is_stale(date_str: str, game_pks: list[int] | None = None) -> dict[str, Any]:
    """Should the ladder artifact be rebuilt?

    **The freshness test is the whole fix.** Measured 2026-08-19: the ladder was
    generated at 18:20 the previous evening and the odds landed at 18:16 the next
    day, so every row served a full sim side against an empty market. Nothing
    compared the two mtimes because nothing rebuilt the artifact at all.

    Stale when the artifact is missing, older than the odds, or older than any
    sim for the date. The sim clause is what re-derives ladders on GAME STATE,
    since sims re-run every 15-20 minutes.
    """
    dest = Path(daily_ladders_path(date_str))
    try:
        dest_mtime = dest.stat().st_mtime
    except Exception:
        return {"stale": True, "reason": "artifact_missing"}

    for side in ("pitcher", "hitter"):
        odds_path = (daily_snapshot_oddsapi_hitter_props_path(date_str) if side == "hitter"
                     else daily_snapshot_oddsapi_pitcher_props_path(date_str))
        try:
            if Path(odds_path).stat().st_mtime > dest_mtime:
                return {"stale": True, "reason": "odds_newer", "side": side}
        except Exception:
            continue

    for pk in (game_pks if game_pks is not None else discover_game_pks(date_str)):
        sim_path = daily_sim_artifact_path(date_str, int(pk))
        if sim_path is None:
            continue
        try:
            if Path(sim_path).stat().st_mtime > dest_mtime:
                return {"stale": True, "reason": "sim_newer", "gamePk": int(pk)}
        except Exception:
            continue
    return {"stale": False, "reason": "fresh"}


def build_ladders_artifact(date_str: str, game_pks: list[int]) -> dict[str, Any]:
    # Read each side's sims and market ONCE, then fan out across props. The
    # artifact covers 17 prop groups; re-reading per prop would multiply the
    # disk work seventeen-fold on a worker near its memory cap.
    pitcher_entries = list(_pitcher_entries(date_str, game_pks))
    hitter_entries = list(_hitter_entries(date_str, game_pks))
    pitcher_market = _market_lines(date_str, "pitcher")
    hitter_market = _market_lines(date_str, "hitter")
    return {
        "date": date_str,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "generatedBy": "syndicate.features.mlb.ladders_build",
        "groups": {
            "pitcher": {
                key: _rows_for_prop(pitcher_entries, spec, pitcher_market, "pitcherName")
                for key, spec in PITCHER_PROPS.items()
            },
            "hitter": {
                key: _rows_for_prop(hitter_entries, spec, hitter_market, "hitterName")
                for key, spec in HITTER_PROPS.items()
            },
        },
    }


def write_ladders_artifact(date_str: str, game_pks: list[int]) -> dict[str, Any]:
    """Build and write. **Refuses to replace a good artifact with an empty one.**

    An empty rebuild is indistinguishable from a correct one on the card -- both
    render nothing -- so overwriting on zero rows would destroy working output
    and look like a successful refresh.
    """
    artifact = build_ladders_artifact(date_str, game_pks)
    group = artifact["groups"]["pitcher"]["strikeouts"]
    destination = Path(daily_ladders_path(date_str))
    if not group.get("rows"):
        return {
            "ok": False,
            "reason": "no_rows_refusing_to_overwrite",
            "path": str(destination),
            "oddsPitchers": group.get("oddsPitchers"),
        }
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(artifact, indent=1), encoding="utf-8")
    return {
        "ok": True,
        "path": str(destination),
        "rows": len(group["rows"]),
        "matchedPitchers": group.get("matchedPitchers"),
        "oddsPitchers": group.get("oddsPitchers"),
        "unmatchedOdds": len(group.get("unmatchedOdds") or []),
    }


def status_artifact_path(date_str: str) -> Path:
    """Sibling of the ladders artifact, and NOT an accident of naming.

    `daily_ladders_status_<date>.json` matches the ALREADY-ALLOWLISTED glob
    `*/daily/ladders/daily_ladders_*.json`, so it publishes to production with
    no change to `HOT_ARTIFACT_PATTERNS` — and therefore **no web deploy**.
    Adding a new pattern would need one: the publish endpoint gates on the WEB
    service's copy of the allowlist, which is what returned 403 on five
    artifacts on 2026-08-18.

    The reader builds an exact filename (`sources.daily_ladders_path`), so this
    file can never be mistaken for the ladders artifact itself.
    """
    return Path(daily_ladders_path(date_str)).with_name(
        f"daily_ladders_status_{date_str.replace('-', '_')}.json")


def write_status_artifact(date_str: str, payload: dict[str, Any]) -> str | None:
    """Record what the refresh DID, on every path including the skips.

    **This exists because the log cannot be read.** The sim job's stdout goes to
    a file on the worker's disk, and the endpoint that surfaces it serves only
    `log_text[-8000:]` (`ops.py:1757`) — a window the publish sweep's ~109
    `PUBLISH_OK` lines consume entirely. Measured twice on 2026-08-19: both the
    checklist hook's line and this module's own refresh line were absent from
    the tail, and a pre-existing marker printed from the same place was absent
    too, proving truncation rather than absence.

    So the outcome is written where it can be READ instead of printed where it
    cannot. Never raises: a status write must not fail a sim job.
    """
    try:
        out = status_artifact_path(date_str)
        out.parent.mkdir(parents=True, exist_ok=True)
        body = dict(payload)
        body["date"] = date_str
        body["writtenAt"] = datetime.now(timezone.utc).isoformat()
        out.write_text(json.dumps(body, indent=1), encoding="utf-8")
        return str(out)
    except Exception:
        return None


__all__ = ["write_status_artifact", "status_artifact_path", "build_ladders_artifact", "write_ladders_artifact", "build_pitcher_strikeout_rows"]
