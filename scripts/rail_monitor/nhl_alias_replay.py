"""Replay the NHL live join's GAME MATCH, switch off vs on, on real fleet names. Read-only, local.

Index: a dumped `nhl_live_lens.json` (Redis copy; every game, any lane source, so a finished game still indexes).
Rows: the odds-feed (away, home) pairs of the live NHL rows in saved rail readings. For each pair it calls the real
`resolve_live_gameline` and reports hit / miss and the reason, with `SYNDICATE_LIVE_GAMELINE_NHL_TEAM_ALIASES`
absent and then "on". A pair whose answer differs between the two is printed.

  py -3 C:\\tmp\\railmon\\nhl_alias_replay.py <repo> <lens_dump.json> <reading_dir> [<reading_dir> ...]
"""
import json, os, sys

repo, lens_path, dirs = sys.argv[1], sys.argv[2], sys.argv[3:]
sys.path.insert(0, repo)
from syndicate.features.shared import live_gameline_join as lgj  # noqa: E402

snap = json.load(open(lens_path, encoding="utf-8"))
if isinstance(snap.get("payload"), dict):
    snap = snap["payload"]
# NAME MATCHING ONLY: a pregame lens indexes nothing (no accepted live lane), so each REAL lens game, its published
# names untouched, gets a stand-in live lane. What is replayed is the join's own key + alias resolution.
for _g in snap.get("games") or []:
    _g["gameLens"] = [{"key": "live", "source": "live_resim", "modelHomeWinProb": 0.5, "simsRun": 200,
                       "projection": {"homeMargin": 0.0, "total": 6.0}}]
# Accept every lane source so finished / intermission games index too: this replays NAME matching only.
sources = set()
for g in snap.get("games") or []:
    for lane in g.get("gameLens") or []:
        if isinstance(lane, dict) and lane.get("source"):
            sources.add(str(lane["source"]))
pairs = {}


def walk(o, depth=0):
    """Every NHL (away_team, home_team) pair anywhere in a saved reading file (board query, live rail, shortlist)."""
    if depth > 7:
        return
    if isinstance(o, dict):
        if o.get("sport") == "nhl" and o.get("away_team") and o.get("home_team"):
            pairs[(o["away_team"], o["home_team"])] = o.get("matchup")
        for v in o.values():
            walk(v, depth + 1)
    elif isinstance(o, list):
        for v in o[:20000]:
            walk(v, depth + 1)


for d in dirs:
    for name in ("query.json", "liverail_0.json", "shortlist.json"):
        path = os.path.join(d, name)
        if os.path.exists(path):
            walk(json.load(open(path, encoding="utf-8")))
print("lens", snap.get("generatedAt"), "games", len(snap.get("games") or []), "sources", sorted(sources))
print("odds pairs from the readings:", len(pairs))


def run(env_on):
    if env_on:
        os.environ[lgj.NHL_TEAM_ALIAS_JOIN_ENV] = "on"
    else:
        os.environ.pop(lgj.NHL_TEAM_ALIAS_JOIN_ENV, None)
    diag = {}
    index = lgj.build_live_gameline_index(snap, sources=tuple(sorted(sources)), sport="nhl", diagnostics=diag)
    out = {}
    for (away, home) in pairs:
        hit, why = lgj.resolve_live_gameline(index, (lgj._norm_team(away), lgj._norm_team(home)), sport="nhl",
                                             row_teams=(away, home))
        out[(away, home)] = ("HIT" if hit is not None else "miss", why, (hit or {}).get("game_pk"))
    return out, diag


off, diag_off = run(False)
on, diag_on = run(True)
print("index off:", {k: diag_off.get(k) for k in ("games_in_snapshot", "indexed", "alias_keys")},
      "| index on:", {k: diag_on.get(k) for k in ("games_in_snapshot", "indexed", "alias_keys")})
print("off: hits %d of %d | on: hits %d of %d" % (sum(v[0] == "HIT" for v in off.values()), len(off),
                                                   sum(v[0] == "HIT" for v in on.values()), len(on)))
changed = [(p, off[p], on[p]) for p in pairs if off[p] != on[p]]
print("pairs whose answer changed:", len(changed))
for p, a, b in changed:
    print("   %s @ %s: off %s -> on %s" % (p[0], p[1], a, b))
still = [p for p in pairs if on[p][0] != "HIT"]
print("pairs still missing with the switch on:", len(still))
for p in still:
    print("   %s @ %s: %s" % (p[0], p[1], on[p][1]))
