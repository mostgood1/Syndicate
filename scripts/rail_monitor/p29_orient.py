"""Per live game on the rail: the rail rows' (away @ home) against the sport's live re-sim snapshot, and why the re-sim
did or did not price it. One JSON line per game, then one summary line per sport.

  WSL: ~/.venvs/syndicate/bin/python /mnt/c/tmp/railmon/p29_orient.py
Read-only: redis GET of the re-sim snapshots, one GET of /api/board/live-rail.

Game line fields: sport, matchup, rows, with_model (non-player rail rows, and those carrying a live model),
  resim = direct | REVERSED (I-29: the snapshot has the teams the other way round) | not_in_resim | no_snapshot.
    not_in_resim can be this helper's own name miss (11-21: "UL Monroe Warhawks" matched no snapshot spelling while
    21 of its 28 rows carried a model), so it is "unknown", not a fleet defect, until checked.
  event_id, reason (the snapshot's refusal reason, "resimmed" when it re-simmed the game, else null), detail.
11-21: extended from NCAAB/WNCAAB to every sport with a per-game snapshot, and the reason added, so the dashboard
row can say why a game has no model (the fleet-watcher's ask: skip deliberate fail-closed refusals).
"""
import json, subprocess, urllib.request

PFX = "syndicate:refresh-state:/home/amyn/syndicate-prod/data/live/"
SNAP = {  # sport -> keyvalue file. NCAAF and NHL keep their per-game refusals in the live lens, not a _live_resim file.
    "ncaab": "ncaab_live_resim.json",
    "wncaab": "wncaab_live_resim.json",
    "nba": "nba_live_resim.json",
    "ncaaf": "ncaaf_live_lens.json",
    "nhl": "nhl_live_lens.json",
    "nfl": "nfl_live_resim.json",
    "soccer": "soccer_live_lens.json",  # no refusals: a live game in it carries a projection ("resimmed"), else absent
}
# The markets the live join prices (dash_update's _PRICED, live_gameline_join._DIST_MARKETS). priced / priced_with_model
# count only these full-game rows, so the page's dark list uses the same rule as the row's live_games_no_model.
_PRICED = {"totals", "total", "totals_alt", "alternate_totals", "spreads", "run_line", "ats", "spreads_alt",
           "alternate_spreads"}


def norm(s):
    return " ".join(str(s or "").lower().replace(".", "").split())


def names(g):
    """Every (away, home) spelling a snapshot game carries: full names, short names, the nested matchup."""
    mu = g.get("matchup") if isinstance(g.get("matchup"), dict) else {}
    pairs = [(g.get("away"), g.get("home")), (g.get("away_name"), g.get("home_name")), (g.get("away_team"), g.get("home_team")),
             ((mu.get("away") or {}).get("name"), (mu.get("home") or {}).get("name"))]
    return {(norm(a), norm(h)) for a, h in pairs if isinstance(a, str) and isinstance(h, str) and a and h}


def lens_reason(g):
    lens = g.get("gameLens")
    lens = lens if isinstance(lens, list) else [lens] if isinstance(lens, dict) else []
    for x in lens:
        if not isinstance(x, dict):
            continue
        ref = x.get("refusal") if isinstance(x.get("refusal"), dict) else {}
        reason = x.get("liveResimRefusal") or ref.get("reason")
        if reason:
            return reason, x.get("liveResimRefusalDetail") or ref.get("detail")
        if x.get("source") == "live_resim":
            return "resimmed", None
    if not lens and g.get("projection"):  # soccer live lens
        return "resimmed", None
    return None, None


def find(index, away, home):
    a, h = norm(away), norm(home)
    hit = [g for pairs, g in index if (a, h) in pairs]
    if hit:
        return hit[0]
    # short-name snapshots ("Wisconsin" for "Wisconsin Badgers"): accept a unique prefix match only
    hit = [g for pairs, g in index if any(pa and ph and a.startswith(pa + " ") and h.startswith(ph + " ") for pa, ph in pairs)]
    if len(hit) == 1:
        return hit[0]
    # soccer lens spellings ("AJ Auxerre" / "Auxerre", "Lens" / "RC Lens"): one name's words a subset of the other's,
    # both sides, unique match only
    ta, th = set(a.split()), set(h.split())
    sub = lambda x, y: bool(x) and bool(y) and (x <= y or y <= x)
    hit = [g for pairs, g in index if any(sub(ta, set(pa.split())) and sub(th, set(ph.split())) for pa, ph in pairs)]
    return hit[0] if len(hit) == 1 else None


rail = json.load(urllib.request.urlopen("http://127.0.0.1:10000/api/board/live-rail", timeout=30))
rows = rail.get("rows") or []
matchups = {}
for r in rows:
    if r.get("player_name"):
        continue
    m = matchups.setdefault((r.get("sport"), r.get("matchup")), {"rows": 0, "with_model": 0, "priced": 0, "priced_with_model": 0})
    m["rows"] += 1
    m["with_model"] += 1 if r.get("live_model_probability") is not None else 0
    if (str(r.get("segment") or "full") == "full" and str(r.get("market") or "").strip().lower() in _PRICED
            # NHL live totals are refused at the join by design (no total distribution); dash_update skips them too
            and not (str(r.get("sport") or "").lower() == "nhl" and "total" in str(r.get("market") or "").lower())):
        m["priced"] += 1
        m["priced_with_model"] += 1 if r.get("live_model_probability") is not None else 0

out, summaries = [], []
for sport in sorted({s for s, _ in matchups if s in SNAP}):  # soccer etc.: no per-game snapshot, and their corners /
    snap, index = None, []                                     # BTTS rows never carry a model, so they would only add noise
    if sport in SNAP:
        raw = subprocess.run(["redis-cli", "--raw", "GET", PFX + SNAP[sport]], capture_output=True, text=True,
                             errors="replace").stdout
        try:
            snap = json.loads(raw) if raw.strip() else None
        except Exception:
            snap = None
        if isinstance(snap, dict) and isinstance(snap.get("payload"), dict):
            snap = snap["payload"]
        games = (snap or {}).get("games") if isinstance(snap, dict) else None
        index = [(names(g), g) for g in (games or []) if isinstance(g, dict)]
    for (s, mu), c in sorted(matchups.items(), key=lambda kv: str(kv[0])):
        if s != sport:
            continue
        away, _, home = str(mu).partition(" @ ")
        if snap is None:
            state, g = "no_snapshot", None
        else:
            g = find(index, away, home)
            state = "direct"
            if g is None:
                g = find(index, home, away)
                state = "REVERSED" if g is not None else "not_in_resim"
        reason, detail = lens_reason(g) if g else (None, None)
        if state == "not_in_resim":  # say how old the snapshot is: a game that kicked off after it is not a defect
            detail = f"snapshot generated {(snap or {}).get('generatedAt') or (snap or {}).get('generated_at')}"
        out.append(dict(sport=sport, matchup=mu, rows=c["rows"], with_model=c["with_model"], priced=c["priced"],
                        priced_with_model=c["priced_with_model"], resim=state,
                        event_id=(g or {}).get("event_id"), reason=reason, detail=detail))
    if snap is not None:
        summaries.append(dict(sport=sport, resim_generated=snap.get("generatedAt") or snap.get("generated_at"),
                              resim_games=len(index), counts=snap.get("counts") or snap.get("coverage")))
# 11-21: what this helper's OWN live-rail GET held, per sport. dash_update labels a no-model game of a sport this read
# lacks entirely "sport_absent_from_helper_read"; this line is how to tell that apart from a snapshot miss next time
# (R26 6:26 PM: no NHL in this read while the fleet's merge 4 s later held 91 NHL cards). No "matchup" key, so
# dash_update and the page skip it.
by_sport = {}
for (s, _mu) in matchups:
    by_sport[s] = by_sport.get(s, 0) + 1
summaries.append({"rail": {"read_at": rail.get("read_at"), "newest_written_at": rail.get("newest_written_at"),
                           "rows": len(rows), "games_by_sport": by_sport, "sports": rail.get("sports")}})
for o in out + summaries:
    print(json.dumps(o, default=str))
