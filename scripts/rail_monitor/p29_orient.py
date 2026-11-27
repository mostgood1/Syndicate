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
import json, subprocess, sys, unicodedata, urllib.request
from datetime import datetime, timezone

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


def counts_as_priced(sport, market):
    """The full-game markets the live join prices FOR THIS SPORT (dash_update.counts_as_priced is the same rule).
    NHL: live totals are refused by design (no total distribution), so puck lines only. NFL (11-22 R9, the
    fleet-watcher's flag): the re-sim publishes NO totalRunsDist / marginDist on purpose (nfl/live_resim.py:714,
    nfl-live-distribution-grade graded live margins a FAIL), so every NFL live total and spread is withheld by design
    and the full-game moneyline is the one priced market. Counting totals/spreads put all 6 re-simmed games on the
    no-model list as "resimmed_no_row_model" while their moneylines carried the model (5 of 5 rows at R9)."""
    s, m = str(sport or "").lower(), str(market or "").strip().lower()
    if s == "nfl":
        return m in ("h2h", "moneyline")
    if s == "nhl" and "total" in m:
        return False
    return m in _PRICED


# Letters NFKD leaves whole. 11-24: the rail's "LASK @ Bodø/Glimt" missed the lens's "LASK Linz @ Bodo/Glimt" on the
# ø alone and read not_in_resim, though the lens held the match (ESPN 401915380).
_FOLD = str.maketrans({"ø": "o", "æ": "ae", "œ": "oe", "ß": "ss", "đ": "d", "ł": "l", "ı": "i", "þ": "th",
                       "’": "'", "‘": "'"})
# Native city names the soccer lens (ESPN) uses where the rail (the books) uses the English one, folded word by word on
# BOTH sides, so the map cannot split a pair that already matched. 11-26 R13/R14 (the fleet-watcher's flag): the rail's
# "FC Copenhagen @ Inter Club d'Escaldes" missed the lens's "F.C. København @ Inter D'Escaldes" (ESPN 401915738, uecl,
# momentum.reason competition_not_modelled) on Copenhagen / København alone and read not_in_resim. The home side already
# matched by the word-subset rule; the apostrophe was not the cause.
_EXONYM = {"kobenhavn": "copenhagen", "munchen": "munich", "koln": "cologne", "praha": "prague", "beograd": "belgrade",
           "bucuresti": "bucharest", "warszawa": "warsaw", "kiev": "kyiv", "athina": "athens", "wien": "vienna",
           "moskva": "moscow", "lisboa": "lisbon", "geneve": "geneva", "sevilla": "seville", "milano": "milan",
           "torino": "turin", "napoli": "naples", "roma": "rome", "firenze": "florence", "genova": "genoa"}


def norm(s):
    s = unicodedata.normalize("NFKD", str(s or "").lower().translate(_FOLD))
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return " ".join(_EXONYM.get(w, w) for w in s.replace(".", "").split())


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
    # 11-24 R7/R8 (the fleet-watcher's flag): a UEFA match in play is served on purpose with projection null and
    # momentum.reason "competition_not_modelled" (poll_soccer_live_state._scoreboard_only_game; the #699 NO-GO gate,
    # state_soccer.md). Read as no reason, it showed "unknown" (Aston Villa @ Galatasaray, R7). It is a deliberate refusal.
    mom = g.get("momentum") if isinstance(g.get("momentum"), dict) else {}
    if not lens and g.get("projection") is None and mom.get("reason") == "competition_not_modelled":
        return "competition_not_modelled", f"{g.get('league') or 'this competition'}: no in-play projection by design (#699 NO-GO gate)"
    return None, None


def find(index, away, home, sport=""):
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
    if len(hit) == 1:
        return hit[0]
    # 11-24 R4: the WNCAAB re-sim names a game missing from the board's odds file by ESPN ("Alcorn State Lady Braves @
    # UT Martin Skyhawks", nameSource espn_display) while the rail says "Alcorn St Braves @ Tenn-Martin Skyhawks". The
    # fleet's own alias fold (team_aliases.chip_join_key, what the margin anchor keys on) maps both to one pair.
    # Unique match only; any import or lookup failure leaves the answer None, as before.
    ka, kh = alias_key(sport, away), alias_key(sport, home)
    if ka and kh:
        hit = [g for pairs, g in index if any(alias_key(sport, pa) == ka and alias_key(sport, ph) == kh for pa, ph in pairs)]
        if len(hit) == 1:
            return hit[0]
    return None


_ALIAS = {}


def alias_key(sport, name):
    """team_aliases.chip_join_key from the fleet checkout, cached; None when it cannot resolve."""
    k = (sport, name)
    if k not in _ALIAS:
        try:
            if "/home/amyn/Syndicate" not in sys.path:
                sys.path.insert(0, "/home/amyn/Syndicate")
            from syndicate.features.shared.team_aliases import chip_join_key
            _ALIAS[k] = chip_join_key(str(sport), str(name or "")) or None
        except Exception:
            _ALIAS[k] = None
    return _ALIAS[k]


# 11-27 R15-R18 (the fleet-watcher's flag): "Real Racing Club de Santander @ Levante" read not_in_resim in two
# straight readings. Not a name miss (find() matches "Racing Santander" / "Racing de Santander" / "Real Racing Club"):
# the soccer live lens was not rewritten from 20:01:59Z to 21:47Z, because its memory gate (300 MB headroom on the
# 3,072 MB live-odds-worker) skipped every tick (LIVE_LENS_TICK_DIAG sport=soccer reason=low_headroom, 63 in 20-21Z),
# so no 20:00Z kickoff was in it. A game missing from a snapshot older than this is "snapshot_stale": the writer, not
# the helper. Every writer here rewrites each tick (1-4 min) while its sport has a live game; 900 s is a stall.
STALE_SNAPSHOT_S = 900


def snapshot_age_s(snap):
    """Seconds since the snapshot's generatedAt / generated_at; None when absent, unparseable or naive."""
    raw = (snap or {}).get("generatedAt") or (snap or {}).get("generated_at") if isinstance(snap, dict) else None
    try:
        t = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if t.tzinfo is None:
        return None
    return max(0.0, (datetime.now(timezone.utc) - t).total_seconds())


rail = json.load(urllib.request.urlopen("http://127.0.0.1:10000/api/board/live-rail", timeout=30))
rows = rail.get("rows") or []
matchups = {}
for r in rows:
    if r.get("player_name"):
        continue
    m = matchups.setdefault((r.get("sport"), r.get("matchup")), {"rows": 0, "with_model": 0, "priced": 0, "priced_with_model": 0})
    m["rows"] += 1
    m["with_model"] += 1 if r.get("live_model_probability") is not None else 0
    if str(r.get("segment") or "full") == "full" and counts_as_priced(r.get("sport"), r.get("market")):
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
    age = snapshot_age_s(snap)
    for (s, mu), c in sorted(matchups.items(), key=lambda kv: str(kv[0])):
        if s != sport:
            continue
        away, _, home = str(mu).partition(" @ ")
        if snap is None:
            state, g = "no_snapshot", None
        else:
            g = find(index, away, home, sport)
            state = "direct"
            if g is None:
                g = find(index, home, away, sport)
                state = "REVERSED" if g is not None else "not_in_resim"
        reason, detail = lens_reason(g) if g else (None, None)
        if state == "not_in_resim":  # say how old the snapshot is: a game that kicked off after it is not a defect
            gen = (snap or {}).get('generatedAt') or (snap or {}).get('generated_at')
            detail = f"snapshot generated {gen}"
            if age is not None and age > STALE_SNAPSHOT_S:
                state = "snapshot_stale"
                detail = (f"snapshot generated {gen}, {age / 60:.0f} min old: its writer has not rewritten it, "
                          f"so a game that started since is absent (not a name miss)")
        out.append(dict(sport=sport, matchup=mu, rows=c["rows"], with_model=c["with_model"], priced=c["priced"],
                        priced_with_model=c["priced_with_model"], resim=state,
                        event_id=(g or {}).get("event_id"), reason=reason, detail=detail))
    if snap is not None:
        summaries.append(dict(sport=sport, resim_generated=snap.get("generatedAt") or snap.get("generated_at"),
                              resim_age_s=None if age is None else round(age),
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
