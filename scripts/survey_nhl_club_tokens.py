"""GATE (a): does a source carry every NHL token the join actually sees?

The 2026-08-29 FORBIDDEN entry bans populating an alias map without first
confirming the SOURCE carries the specific names the join fails on. This
enumerates the REAL token vocabulary from every NHL feed Syndicate reads --
NHL api-web, ESPN, TheOddsAPI, and the captured book_quotes shard -- and checks
each token against `local_nhl_odds.TEAM_NAME_TO_ABBR`, the in-repo table the
NHL pipeline already resolves names with.

Read-only. The OddsAPI events listing is free (x-requests-last is printed).
No token is invented here: anything this prints as UNCOVERED is a real string a
real feed emitted, and is the only thing a supplement may contain.

    py -3 scripts/survey_nhl_club_tokens.py
"""
from __future__ import annotations

import collections
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from syndicate.local_nhl_odds import TEAM_ABBRS, TEAM_NAME_TO_ABBR, _norm_team_name

UA = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
RENDER_SRV = "srv-d91dpertqb8s73co8lt0"  # live-odds-worker, for ODDS_API_KEY


def get_json(url, headers=UA, timeout=40):
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=timeout) as r:
        return json.loads(r.read().decode()), {k.lower(): v for k, v in dict(r.headers).items()}


PRIMARY_TREE = Path(r"C:\Users\tempadmin\OneDrive\Coding\Syndicate")


def odds_api_key():
    # `.env` is gitignored, so a session worktree does not carry one; fall back
    # to the primary tree's copy rather than failing in exactly the place this
    # script is meant to be run from.
    env = REPO / ".env"
    if not env.exists():
        env = PRIMARY_TREE / ".env"
    render_key = ""
    for line in env.read_text(encoding="utf-8").splitlines():
        if line.startswith("RENDER_API_KEY="):
            render_key = line.split("=", 1)[1].strip().strip('"').strip("'")
    body, _ = get_json(
        f"https://api.render.com/v1/services/{RENDER_SRV}/env-vars/ODDS_API_KEY",
        headers={"Authorization": f"Bearer {render_key}", "Accept": "application/json"},
    )
    key = (body.get("envVar") or body).get("value")
    assert key, "ODDS_API_KEY came back empty"
    return key


# JOIN-GRADE tokens are the ones a cross-source join actually keys on: a feed's
# abbreviation and its full/display name. COMPONENT tokens -- a bare place
# ("New York") or a bare nickname ("Rangers") -- are reported separately and
# are NOT supplement candidates: `_alias_map` is not where they belong
# (`_nickname_alias_map` derives nicknames from the map's own values), and a
# bare place is ambiguous in this league by construction.
tokens: dict[str, set[str]] = collections.defaultdict(set)
components: dict[str, set[str]] = collections.defaultdict(set)


def note(source, *values):
    for value in values:
        text = str(value or "").strip()
        if text:
            tokens[text].add(source)


def note_component(source, *values):
    for value in values:
        text = str(value or "").strip()
        if text:
            components[text].add(source)


# ---- 1. NHL api-web: full names, place/common split, and the tri-code
for anchor in ("2026-09-24", "2026-10-01"):
    payload, _ = get_json(f"https://api-web.nhle.com/v1/schedule/{anchor}")
    for week in payload.get("gameWeek", []):
        for game in week.get("games", []):
            for side in ("awayTeam", "homeTeam"):
                team = game.get(side) or {}
                place = (team.get("placeName") or {}).get("default", "")
                common = (team.get("commonName") or {}).get("default", "")
                note("nhl-api", team.get("abbrev"), f"{place} {common}".strip())
                note_component("nhl-api", place, common)

# ---- 2. ESPN: its own abbreviations and display names
for day in ("20260923", "20260924", "20260926", "20261003"):
    payload, _ = get_json(f"https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/scoreboard?dates={day}")
    for event in payload.get("events", []):
        for comp in event["competitions"][0]["competitors"]:
            team = comp["team"]
            note("espn", team.get("abbreviation"), team.get("displayName"))
            note_component("espn", team.get("shortDisplayName"), team.get("location"), team.get("name"))

# ---- 3. TheOddsAPI: the vendor's own spellings, both NHL sport keys
key = odds_api_key()
for sport_key in ("icehockey_nhl", "icehockey_nhl_preseason"):
    url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/events?" + urllib.parse.urlencode({"apiKey": key})
    events, headers = get_json(url, headers={"Accept": "application/json"})
    print(f"[oddsapi] {sport_key}: {len(events)} events, x-requests-last={headers.get('x-requests-last')}")
    for event in events:
        note("oddsapi", event.get("home_team"), event.get("away_team"))

# ---- 4. The captured shard: what actually landed on disk
shard = Path(r"C:\tmp\nhl_bq.jsonl")
if shard.exists():
    with shard.open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                row = json.loads(line)
                note("book_quotes", row.get("home_team"), row.get("away_team"))

abbrs = set(TEAM_ABBRS)


def resolve(token):
    normalized = _norm_team_name(token)
    return TEAM_NAME_TO_ABBR.get(normalized) or (
        token.strip().upper() if token.strip().upper() in abbrs else None
    )


print(f"\nJOIN-GRADE tokens (feed abbreviation + full/display name): {len(tokens)}")
covered = {t: resolve(t) for t in sorted(tokens) if resolve(t)}
uncovered = [t for t in sorted(tokens) if not resolve(t)]
print(f"  covered by local_nhl_odds.TEAM_NAME_TO_ABBR (+ tri-codes): {len(covered)}")
print(f"  UNCOVERED -- the only strings a supplement may contain: {len(uncovered)}")
for token in uncovered:
    print(f"     {token!r:24s} seen in {','.join(sorted(tokens[token]))}")

# Components are printed for the record, and to show WHY they are excluded:
# how many of them are claimed by more than one club.
by_club = collections.defaultdict(set)
for token, sources in components.items():
    for club in (resolve(token),):
        pass
print(f"\nCOMPONENT tokens (bare place / bare nickname), NOT supplement candidates: {len(components)}")
ambiguous = []
for token in sorted(components):
    owners = {resolve(full) for full in tokens if _norm_team_name(token) in _norm_team_name(full)}
    owners.discard(None)
    if len(owners) > 1:
        ambiguous.append((token, sorted(owners)))
print(f"  of which claimed by MORE THAN ONE club (would be a wrong answer, not a miss): {len(ambiguous)}")
for token, owners in ambiguous:
    print(f"     {token!r:24s} -> {owners}")
