"""Read-only WNBA accuracy + profitability assessment (lane wnba-accuracy-assessment).

Builds ground truth from ESPN (scoreboard + summary boxscores) because every
production WNBA accuracy instrument reads zero, then grades the Syndicate
pregame sim, its game-market recommendations and its player-prop
recommendations against it.

Nothing here writes to production or to data/. Inputs are cached JSON under the
session scratchpad.
"""
from __future__ import annotations

import glob
import io
import json
import math
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# The provenance split is NOT optional here and is not re-implemented locally.
# Pooling the two artifact roots turns this sim's +16.53% Brier skill into
# -21.52%, and the first pass of this very assessment reported the pooled
# number. `wnba_card_provenance` is the single place that knows the rule.
from syndicate.features.shared import wnba_card_provenance as provenance  # noqa: E402

# READ LAZILY, NOT AT IMPORT `[fixed 2026-09-05]`. This was
# `os.environ["SC"]` at module level, so importing this module AT ALL raised
# `KeyError: 'SC'` unless the variable happened to be set -- it is a source-cache
# directory used by exactly two globs below, and nothing else here needs it.
# Found by `scripts/probability_differential.py`'s registry, which refuses to
# count an unimportable implementation as passing: "an unimportable one is
# untested, not passing". A module-level `os.environ[key]` turns a missing
# CONFIG value into an ImportError for every consumer, including tooling that
# only wants one pure function out of the file.
def _source_cache_root() -> str:
    root = str(os.environ.get("SC") or "").strip()
    if not root:
        raise SystemExit(
            "assess_wnba_accuracy needs the SC environment variable (the source-cache "
            "directory holding espn/ and cards/ JSON). Set it and re-run."
        )
    return root


# ---------------------------------------------------------------- ground truth
def _jload(path):
    """Every JSON file here is UTF-8; Windows would otherwise decode as cp1252."""
    with io.open(path, encoding="utf-8") as fh:
        return json.load(fh)


def load_espn_games():
    """{(utc_start_minute, away_tri, home_tri): {...}} plus a by-date index."""
    games = {}
    for p in sorted(glob.glob(_source_cache_root() + "/espn/*.json")):
        for ev in _jload(p).get("events") or []:
            comp = (ev.get("competitions") or [{}])[0]
            stat = ((ev.get("status") or {}).get("type")) or {}
            if not stat.get("completed"):
                continue
            home = away = None
            for c in comp.get("competitors") or []:
                side = c.get("homeAway")
                rec = {
                    "tri": (c.get("team") or {}).get("abbreviation"),
                    "score": int(c.get("score")) if c.get("score") is not None else None,
                }
                if side == "home":
                    home = rec
                else:
                    away = rec
            if not home or not away or home["score"] is None:
                continue
            if home["tri"] in NON_LEAGUE_TRI or away["tri"] in NON_LEAGUE_TRI:
                continue
            games[ev["id"]] = {
                "id": ev["id"],
                "utc": ev.get("date"),
                "away": away["tri"],
                "home": home["tri"],
                "away_score": away["score"],
                "home_score": home["score"],
                "total": away["score"] + home["score"],
                "home_margin": home["score"] - away["score"],
                "periods": len(comp.get("competitors", [{}])[0].get("linescores") or []),
            }
    return games


# ESPN abbreviation -> the tri-code the Syndicate cards use, where they differ.
TRI_ALIAS = {
    "LAS": "LA", "LA": "LAS",
    "LVA": "LV", "LV": "LVA",
    "NYL": "NY", "NY": "NYL",
    "GSV": "GS", "GS": "GSV",
}
# ESPN carries the All-Star exhibition teams on the same scoreboard; they are
# not WNBA games and must never enter a grading sample.
NON_LEAGUE_TRI = {"COOP", "NIGER", "SPO"}


def tri_variants(t):
    t = (t or "").upper()
    return {t, TRI_ALIAS.get(t, t)}


def join_cards_to_espn(espn):
    """Match Syndicate cards to completed ESPN games on (start minute, teams)."""
    by_min = defaultdict(list)
    for g in espn.values():
        by_min[g["utc"][:16]].append(g)
    by_teams_day = defaultdict(list)
    for g in espn.values():
        by_teams_day[(g["utc"][:10], g["away"], g["home"])].append(g)

    joined, unmatched = [], []
    for p in sorted(glob.glob(_source_cache_root() + "/cards/*.json")):
        card_date = os.path.basename(p)[:-5]
        payload = _jload(p)
        for card in payload.get("games") or []:
            st = (card.get("startTime") or "")[:16]
            a, h = card.get("away_tri"), card.get("home_tri")
            hit = None
            for cand in by_min.get(st, []):
                if cand["away"] in tri_variants(a) and cand["home"] in tri_variants(h):
                    hit = cand
                    break
            if hit is None:  # fall back to same UTC day + teams
                for day in {st[:10]}:
                    for av in tri_variants(a):
                        for hv in tri_variants(h):
                            for cand in by_teams_day.get((day, av, hv), []):
                                hit = hit or cand
            if hit is None:
                unmatched.append((card_date, a, h, st))
            else:
                joined.append((card_date, card, hit))

    # One ESPN game can be carried by cards on two adjacent dates (UTC vs CT).
    # Keep the card whose own date matches the game's Central date.
    best = {}
    for card_date, card, g in joined:
        prev = best.get(g["id"])
        if prev is None or _date_distance(card_date, g) < _date_distance(prev[0], g):
            best[g["id"]] = (card_date, card, g)
    return list(best.values()), unmatched


def _date_distance(card_date, g):
    """|card date - the game's US-Central calendar date|, in days."""
    from datetime import datetime, timedelta
    utc = datetime.strptime(g["utc"][:16], "%Y-%m-%dT%H:%M")
    central = (utc - timedelta(hours=5)).date().isoformat()
    return abs((datetime.strptime(card_date, "%Y-%m-%d").date()
                - datetime.strptime(central, "%Y-%m-%d").date()).days)


# ------------------------------------------------------------------- utilities
def american_to_prob(odds):
    if odds is None:
        return None
    try:
        o = float(odds)
    except (TypeError, ValueError):
        return None
    if -100 < o < 100:  # impossible American price -- reject, do not coerce
        return None
    return (-o) / (-o + 100.0) if o < 0 else 100.0 / (o + 100.0)


def american_profit(odds, won):
    o = float(odds)
    if won is None:
        return 0.0
    if not won:
        return -1.0
    return (100.0 / -o) if o < 0 else (o / 100.0)


def brier(ps, ys):
    return sum((p - y) ** 2 for p, y in zip(ps, ys)) / len(ps)


def logloss(ps, ys, eps=1e-9):
    return -sum(
        y * math.log(min(max(p, eps), 1 - eps)) + (1 - y) * math.log(1 - min(max(p, eps), 1 - eps))
        for p, y in zip(ps, ys)
    ) / len(ps)


def auc(ps, ys):
    pairs = sorted(zip(ps, ys))
    pos = sum(ys)
    neg = len(ys) - pos
    if pos == 0 or neg == 0:
        return None
    rank, i, total = {}, 0, 0.0
    while i < len(pairs):
        j = i
        while j + 1 < len(pairs) and pairs[j + 1][0] == pairs[i][0]:
            j += 1
        avg = (i + j) / 2.0 + 1
        for k in range(i, j + 1):
            if pairs[k][1] == 1:
                total += avg
        i = j + 1
    return (total - pos * (pos + 1) / 2.0) / (pos * neg)


def corr(xs, ys):
    n = len(xs)
    if n < 3:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    sy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if sx == 0 or sy == 0:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (sx * sy)


def wilson_se(p, n):
    return math.sqrt(max(p * (1 - p), 1e-12) / n)


def root_of_payload(payload: dict) -> str:
    """Provenance of a whole `/wnba/api/cards` payload."""
    return provenance.root_of((payload or {}).get("source_path"))


def clean_root_only(joined):
    """`(rows, coverage_note)` -- Syndicate root only, and it SAYS what it dropped.

    Never returns a filtered sample without the note: a silently filtered sample
    reads as a complete one, which is how a 43%-contaminated archive produced a
    confident wrong verdict.
    """
    tagged = [{"source_path": row.get("source_path"), "row": row} for row in joined]
    buckets = provenance.split_by_root(tagged)
    kept = [item["row"] for item in buckets[provenance.SYNDICATE]]
    return kept, provenance.coverage_note(buckets)
