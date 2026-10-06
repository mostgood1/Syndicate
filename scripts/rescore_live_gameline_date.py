#!/usr/bin/env python3
"""Re-score a past date's live-gameline ledger with the CURRENT scorer.

WHY THIS EXISTS. `history.jsonl` stores the board's RETAINED summary for a
date, and a re-capture of a past date re-serves that summary verbatim rather
than recomputing it. So a cut the scorer gained LATER can never appear for an
earlier date, no matter how many times the date is re-captured -- and because
`pool_live_gameline_trend.best_per_date` skips a date whose cut has no brier,
the date does not shrink the pool, it drops out of it silently.

Measured 2026-09-24: 2026-08-30 and 2026-08-31 were the only two dates whose
summaries were computed inside the ~47h window between `75cf9aec`
(2026-08-30 11:59 CDT, added `scored_markets`/`records_by_market`) and
`4d20ea00` (2026-09-01 11:07 CDT, added `fresh_quotes_only`). Their 09-23
re-capture carries `scored_markets` yet `fresh_quote_seconds: None`, which
`live_gameline_score.py` sets UNCONDITIONALLY to a constant -- proof the
scoring function never ran and a stored object was served. The per-record
ledgers, however, carry `quote_age_seconds` on 100% of records (5,904/5,904
and 8,161/8,161); `live_gameline_ledger.py` has stamped it since `7e1d0cac`
(2026-08-15). The data was never missing. Only the summary was too old.

WHAT MAKES A RE-SCORE TRUSTWORTHY, AND WHY THIS REFUSES WITHOUT IT. A
reconstruction is NOT automatically the same measurement as the board's. The
2026-09-08 precedent (`findings_2026-09-08_live_gameline_0904_per_game.md`)
rebuilt 09-04 from the same ledger and got +0.06352 against the board's
+0.07827, because its finals index resolved 15 games where the board had 13.
Direction matched; the number did not.

So this script does not ask to be believed. `--expect-*` names the retained
`all_records` briers and n, and an appended row is REFUSED unless the re-score
reproduces them EXACTLY. That is a strong check: it pins two briers to 5dp and
two row counts simultaneously, on a population the current scorer rebuilt from
raw records. When it passes, the `fresh_quotes_only` block this adds is the
same measurement as the `all_records`/`priceable_only` already in history, not
a lookalike computed on a different set of games.

THE BOARD'S POPULATION IS THE TARGET, NOT THE FULLEST ONE. A late game that
finished after the board's last build of its date is final on StatsAPI today
and was not final for the board then. `--exclude-game-pk` reproduces the
board's set. Measured for 08-31: a leave-one-out search over all 12 StatsAPI
finals found exactly ONE that reproduces the retained figures -- 824314
(BAL @ COL, first pitch 00:1xZ). Scoring the fuller 12-game set instead is
defensible data but it is NOT what every neighbouring date in the series is,
so pooling it would compare populations across dates.

Usage:
    python scripts/rescore_live_gameline_date.py --date 2026-08-30 \
        --expect-model 0.15138 --expect-market 0.18455 --expect-n 618/526

    ... --exclude-game-pk 824314 --append

Exit codes:
    0 ok
    2 ledger fetch/read failed
    3 no expectation given (refuses to append blind)
    4 verification FAILED -- the re-score is not the board's measurement
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import os
import re
import unicodedata
import subprocess
import sys
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from syndicate.features.mlb.live_gameline_segment_actuals import (  # noqa: E402
    MlbSegmentActuals,
    segment_score_blocks,
)
from syndicate.features.shared.live_gameline_accuracy import RETAINED_SCORE_KEYS  # noqa: E402
from syndicate.features.shared.live_gameline_score import (  # noqa: E402
    finals_from_scores,
    score_ledger_records,
)

HISTORY = REPO / "reports" / "live_gameline_accuracy" / "history.jsonl"
LEDGER_PATH = "{sport}_source/data/live_gameline_ledger/live_gameline_ledger_{date}.jsonl"
try:
    from scripts._base_url import admin_token as resolve_admin_token, default_base_url
except ImportError:  # run as `python scripts/<name>.py`
    from _base_url import admin_token as resolve_admin_token, default_base_url

DEFAULT_BASE = default_base_url()
STATSAPI = "https://statsapi.mlb.com/api/v1/schedule?sportId=1&date={date}"
# NCAAF has no StatsAPI equivalent and its ledger rows carry `game_pk: None`, so its
# finals are keyed by `event_id` instead -- which needs NO scorer change, because
# `score_ledger_records` tries a record's `game_pk` and THEN its `event_id`
# (`live_gameline_score.py:793`). `groups=80` is FBS; one page with `limit` far above
# a day's slate is the whole population.
ESPN_CFB = ("https://site.api.espn.com/apis/site/v2/sports/football/college-football/"
            "scoreboard?dates={compact}&groups=80&limit=400")
WIRED_SPORTS = ("mlb", "ncaaf", "soccer")


def _admin_token(base_url: str | None = None) -> str | None:
    """Via `_base_url.admin_token`: the fleet's own token for the fleet, else env / `.env`. Never printed."""
    token = resolve_admin_token(base_url or DEFAULT_BASE)
    return token or None


def _fetch_ledger(date: str, sport: str, base: str, dest: Path) -> bytes:
    token = _admin_token(base)
    if not token:
        raise RuntimeError("no ADMIN_TOKEN in env or .env")
    url = f"{base}/api/ops/artifacts/stream?path=" + LEDGER_PATH.format(sport=sport, date=date)
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=300) as resp:
        raw = resp.read()
    dest.write_bytes(raw)
    return raw


def _final_scores(date: str) -> dict[str, tuple[float, float]]:
    """`game_pk` -> `(away, home)` for games FINAL on StatsAPI.

    Scores here are ints; the LEDGER's own `home_score`/`away_score` are
    strings (`'4'`), which is why the finals index is built from StatsAPI and
    not from the records -- and why an `isinstance(x, int)` split over the
    ledger silently returns n=0. Noted in the 09-08 findings; kept here so the
    next reader does not rediscover it.
    """
    with urllib.request.urlopen(STATSAPI.format(date=date), timeout=60) as resp:
        sched = json.load(resp)
    scores: dict[str, tuple[float, float]] = {}
    for day in sched.get("dates", []):
        for game in day.get("games", []):
            if (game.get("status") or {}).get("abstractGameState") != "Final":
                continue
            teams = game.get("teams") or {}
            away = (teams.get("away") or {}).get("score")
            home = (teams.get("home") or {}).get("score")
            if away is None or home is None:
                continue
            scores[str(game["gamePk"])] = (float(away), float(home))
    return scores


def _norm_team(name):
    """Fold diacritics, DROP apostrophes, then strip remaining punctuation to spaces.

    Nothing fuzzier ON PURPOSE: an alias table or edit-distance match would hide a real
    miss, and a miss has to be NAMED. The two steps here are pure canonicalisation --
    the SAME name written two ways -- which is a different thing from guessing that two
    different names mean one team. Measured 2026-10-06 against ESPN:

        San José State  -> san jose state   (NFKD fold)
        Hawai'i         -> hawaii           (apostrophe DROPPED, not spaced: spacing it
                                             gives 'hawai i', which matches nothing)

    Deliberately NOT handled, and reported as unmatched instead: `McNeese State` vs
    `McNeese`, `UMass` vs `Massachusetts`. Those are different strings for one team and
    resolving them needs a decision, not a regex.
    """
    folded = unicodedata.normalize("NFKD", name or "")
    folded = "".join(ch for ch in folded if not unicodedata.combining(ch))
    folded = folded.replace("'", "").replace("\u2019", "")
    s = re.sub(r"[^a-z0-9 ]", " ", folded.lower())
    return re.sub(r"\s+", " ", s).strip()


def _final_scores_ncaaf(date, records):
    """`event_id` -> `(away, home)` for NCAAF games FINAL on ESPN's FBS scoreboard,
    plus a join report.

    THE JOIN IS BY TEAM NAME BECAUSE THERE IS NO SHARED ID. The ledger's `event_id`
    is an odds-feed hash and its `game_pk` is None for this sport, so the only field
    both sides carry is the team display name. Both orientations are tried -- a feed
    listing the sides the other way round would otherwise read as a miss -- and EVERY
    unmatched game is returned for the caller to print. A silent drop would shrink the
    scored population, which is the one thing this tool exists to pin down.
    """
    compact = date.replace("-", "")
    with urllib.request.urlopen(ESPN_CFB.format(compact=compact), timeout=60) as resp:
        board = json.load(resp)
    by_pair = {}
    finals_seen = 0
    for event in board.get("events") or []:
        comp = (event.get("competitions") or [{}])[0]
        if (((comp.get("status") or {}).get("type") or {}).get("state")) != "post":
            continue
        sides = comp.get("competitors") or []
        home = next((c for c in sides if c.get("homeAway") == "home"), None)
        away = next((c for c in sides if c.get("homeAway") == "away"), None)
        if not home or not away:
            continue
        try:
            hs, as_ = float(home.get("score")), float(away.get("score"))
        except (TypeError, ValueError):
            continue
        finals_seen += 1
        hk = _norm_team((home.get("team") or {}).get("displayName"))
        ak = _norm_team((away.get("team") or {}).get("displayName"))
        by_pair[(hk, ak)] = (as_, hs)

    games = {}
    scoreable = set()
    for rec in records:
        ev = str(rec.get("event_id") or "").strip()
        if not ev:
            continue
        if ev not in games and rec.get("home_team") and rec.get("away_team"):
            games[ev] = (rec["home_team"], rec["away_team"])
        # Only a game with a scoreable FULL-GAME h2h row can move the h2h measurement,
        # so only such a game going unmatched shrinks the scored population. Measured
        # 2026-10-03: 3 of 54 games went unmatched and NONE was scoreable, which is why
        # the --expect-* gate still reproduced the retained figures exactly.
        if (rec.get("market") == "h2h" and rec.get("segment") == "full"
                and rec.get("model_home_win_prob") is not None
                and rec.get("market_fair_prob") is not None):
            scoreable.add(ev)

    scores = {}
    flipped = []
    unmatched = []
    unmatched_scoreable = []
    for ev, (ht, at) in games.items():
        h, a = _norm_team(ht), _norm_team(at)
        if (h, a) in by_pair:
            scores[ev] = by_pair[(h, a)]
        elif (a, h) in by_pair:
            feed_away, feed_home = by_pair[(a, h)]
            # the feed had OUR home side as its away side, so swap back into
            # (away, home) as THIS ledger row orients it
            scores[ev] = (feed_home, feed_away)
            flipped.append(at + " @ " + ht)
        else:
            tag = " [SCOREABLE -- shrinks the measurement]" if ev in scoreable else " [no scoreable h2h row]"
            unmatched.append(at + " @ " + ht + tag)
            if ev in scoreable:
                unmatched_scoreable.append(at + " @ " + ht)
    used = set()
    for ev in scores:
        ht, at = games[ev]
        h, a = _norm_team(ht), _norm_team(at)
        used.add((h, a) if (h, a) in by_pair else (a, h))
    espn_unused = [f"{a} @ {h}" for (h, a) in by_pair if (h, a) not in used]
    return scores, {"espn_finals": finals_seen, "ledger_games": len(games),
                    "matched": len(scores), "orientation_flipped": flipped,
                    "unmatched": unmatched, "unmatched_scoreable": unmatched_scoreable,
                    "scoreable_games": len(scoreable), "espn_unused": espn_unused}


def _final_scores_soccer(date, records):
    """`game_pk` -> `(away, home)` for soccer games FINAL on ESPN, plus a join report.

    AN ID JOIN, NOT A NAME JOIN, and that is the whole point. The ledger's soccer
    `game_pk` is ESPN's event id, so this keys on the scorer's first lookup field and
    never compares a club name. Verified 2026-09-30: ledger `game_pk` 761833 is ESPN
    `usa.1` event 761833. A name join would have failed on both recoverable dates --
    ESPN says "St. Louis CITY SC" / "Red Bull New York" where the ledger says
    "St. Louis City SC" / "New York Red Bulls" -- which is the documented soccer
    name-join hazard (`tests/test_soccer_live_gameline_name_join.py`).

    DRAWS ARE KEPT. `soccer` is in `DRAW_IS_A_REAL_OUTCOME` and `finals_from_scores`
    maps a level final to False ("the home side did not win"), which is the unbiased
    treatment; excluding draws is what once removed a third of soccer's population
    while both probabilities were formed unconditionally.

    Everything else is borrowed rather than re-derived: the league slugs, the window
    retry, and the postponed/canceled rule all come from `espn_lineups`.
    """
    from syndicate.features.soccer.ingestion.espn_lineups import (  # noqa: PLC0415
        LEAGUE_ESPN_SLUGS, fetch_events, record_is_unplayed)
    compact = date.replace("-", "")
    window = f"{compact}-{compact}"
    try:
        from syndicate.features.soccer.sources import active_leagues_for_date  # noqa: PLC0415
        leagues = [lg for lg in active_leagues_for_date(date) if lg in LEAGUE_ESPN_SLUGS]
        league_source = "active_leagues_for_date"
    except Exception:  # noqa: BLE001
        # Falling back to EVERY tracked league is more fetches, never fewer finals,
        # and the report says which happened so a thin join is not misread as a
        # league being out of season.
        leagues = sorted(LEAGUE_ESPN_SLUGS)
        league_source = "ALL tracked leagues (active_leagues_for_date unavailable)"
    if not leagues:
        leagues = sorted(LEAGUE_ESPN_SLUGS)
        league_source = "ALL tracked leagues (none reported active for this date)"

    scores = {}
    finals_seen = 0
    unplayed = 0
    draws = 0
    for league in leagues:
        try:
            events = fetch_events(league, date_windows=[window], statuses={"post"})
        except Exception as exc:  # noqa: BLE001
            print(f"    league {league}: fetch FAILED ({type(exc).__name__}), no finals from it")
            continue
        for ev in events:
            if record_is_unplayed(ev):
                unplayed += 1
                continue
            try:
                home_pts, away_pts = float(ev.get("home_score")), float(ev.get("away_score"))
            except (TypeError, ValueError):
                continue
            finals_seen += 1
            if home_pts == away_pts:
                draws += 1          # KEPT, see the docstring
            scores[str(ev.get("event_id"))] = (away_pts, home_pts)

    ledger_games = {}
    scoreable = set()
    for rec in records:
        pk = str(rec.get("game_pk") or "").strip()
        if not pk:
            continue
        ledger_games.setdefault(pk, (rec.get("home_team"), rec.get("away_team")))
        if (rec.get("market") == "h2h" and rec.get("segment") == "full"
                and rec.get("model_home_win_prob") is not None
                and rec.get("market_fair_prob") is not None):
            scoreable.add(pk)
    matched = sorted(set(ledger_games) & set(scores))
    unmatched = []
    unmatched_scoreable = []
    for pk in sorted(set(ledger_games) - set(scores)):
        home, away = ledger_games[pk]
        tag = " [SCOREABLE -- shrinks the measurement]" if pk in scoreable else " [no scoreable h2h row]"
        unmatched.append(f"{away} @ {home} (game_pk {pk}){tag}")
        if pk in scoreable:
            unmatched_scoreable.append(f"{away} @ {home} (game_pk {pk})")
    # Only the ledger's own games are kept: an ESPN final for a match this board never
    # priced is not part of the population and must not enter the index.
    kept = {pk: scores[pk] for pk in matched}
    return kept, {"leagues": leagues, "league_source": league_source,
                  "espn_finals": finals_seen, "espn_unplayed_skipped": unplayed,
                  "draws_kept": draws, "ledger_games": len(ledger_games),
                  "matched": len(kept), "unmatched": unmatched,
                  "unmatched_scoreable": unmatched_scoreable,
                  "scoreable_games": len(scoreable)}


def _event_to_game_from_ledger(records: list[dict]) -> dict[str, str]:
    """odds `event_id` -> gamePk, from the ledger's own FULL-GAME rows.

    A first5 row carries `game_pk=None` and the event only; a full-game row
    of the same event carries both (09-27: 14 of 14 first5 observation events
    mapped, none to two games). The board build maps through the grid instead
    (`event_to_game_pk_from_grid`); a re-score has no grid, and the ledger is
    the one record of what the board joined at the time.
    """
    out: dict[str, str] = {}
    for rec in records:
        pk, ev = str(rec.get("game_pk") or "").strip(), str(rec.get("event_id") or "").strip()
        if pk.isdigit() and ev:
            out.setdefault(ev, pk)
    return out


def _retained_expectation(history: Path, date: str, sport: str = "mlb") -> dict | None:
    """The BOARD's retained `all_records` for `date` -- the fullest ordinary
    capture (never a re-score, which would make the gate check itself)."""
    best = None
    if not history.exists():
        return None
    for line in history.open(encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        if row.get("date") != date or row.get("sport", "mlb") != sport or row.get("rescored_from_ledger"):
            continue
        allr = row.get("all_records") or {}
        model, market = allr.get("model") or {}, allr.get("market") or {}
        if model.get("brier") is None or market.get("brier") is None:
            continue
        if best is None or (row.get("games_with_outcome") or 0) > (best["games"] or 0):
            best = {"games": row.get("games_with_outcome"), "model": model["brier"],
                    "market": market["brier"], "n": f"{model.get('n')}/{market.get('n')}",
                    "captured_at": row.get("captured_at")}
    return best


def _scorer_provenance() -> dict[str, str | None]:
    """The exact scorer that produced these numbers, so the row is re-derivable."""
    rel = "syndicate/features/shared/live_gameline_score.py"
    try:
        sha = subprocess.run(
            ["git", "log", "-1", "--format=%H", "--", rel],
            cwd=REPO, capture_output=True, text=True, timeout=30,
        ).stdout.strip() or None
    except Exception:
        sha = None
    digest = hashlib.sha256((REPO / rel).read_bytes()).hexdigest()[:16]
    return {"scorer_file": rel, "scorer_commit": sha, "scorer_sha256_16": digest}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--date", required=True, help="slate date, zero-padded YYYY-MM-DD")
    ap.add_argument("--sport", default="mlb",
                    help="mlb (StatsAPI finals, keyed by game_pk), ncaaf (ESPN FBS "
                         "scoreboard, keyed by event_id via a team-name join) or soccer "
                         "(ESPN per-league scoreboards, keyed by game_pk, which IS the "
                         "ESPN event id -- an id join, and draws are kept as not-a-home-win)")
    ap.add_argument("--ledger", help="local ledger .jsonl; fetched from production if absent")
    ap.add_argument("--base-url", default=DEFAULT_BASE)
    ap.add_argument("--exclude-game-pk", action="append", default=[],
                    help="a finals KEY the board did NOT have a final for; repeatable. "
                         "For mlb that is a game_pk, for ncaaf an event_id -- whatever "
                         "this sport's finals index is keyed by.")
    ap.add_argument("--expect-model", type=float, help="retained all_records model brier")
    ap.add_argument("--expect-market", type=float, help="retained all_records market brier")
    ap.add_argument("--expect-n", help="retained all_records n, as MODEL/MARKET")
    ap.add_argument("--expect-records-considered", type=int,
                    help="WEAKER ANCHOR, for a date whose retained figures came from the "
                         "PRE-FIX scorer and so cannot be reproduced by design. Proves the "
                         "same ledger reached the scorer; it does NOT prove the same finals "
                         "population, so it requires --finals-population statsapi.")
    ap.add_argument("--finals-population", choices=("board", "statsapi", "espn"), default="board",
                    help="Which population this row is scored on. 'board' means the retained "
                         "figures were reproduced exactly, so the row is comparable with a "
                         "board capture. 'statsapi' means they could not be and the row is "
                         "scored on the sport's own record -- a DIFFERENT population, which "
                         "must never be pooled with 'board' rows unmarked.")
    ap.add_argument("--expect-from-history", action="store_true",
                    help="take --expect-model/--expect-market/--expect-n from the fullest BOARD "
                         "capture of this date already in the history (never a re-score)")
    ap.add_argument("--search-exclusions", action="store_true",
                    help="if the StatsAPI finals do not reproduce the retained figures, try "
                         "leaving out each final in turn; accept ONLY a unique exact match "
                         "(the 08-31 precedent: one late game the board never saw)")
    ap.add_argument("--history", default=str(HISTORY),
                    help="history.jsonl to read expectations from and append to")
    ap.add_argument("--append", action="store_true", help="append the verified row to history.jsonl")
    ap.add_argument("--json-out", help="also write the full score object here")
    args = ap.parse_args(argv)

    date = args.date
    sport = (args.sport or "").strip().lower()
    if sport not in WIRED_SPORTS:
        # An unwired sport would otherwise fetch a ledger that does not exist and
        # report an empty one, which reads as 'no data' rather than 'not supported'.
        print(f"sport {sport!r} is not wired for re-scoring; wired: "
              f"{', '.join(WIRED_SPORTS)}", file=sys.stderr)
        return 2
    history = Path(args.history)
    if args.expect_from_history:
        exp = _retained_expectation(history, date, sport)
        if exp is None:
            print(f"NO RETAINED BOARD CAPTURE of {date} with all_records in {history}",
                  file=sys.stderr)
            return 3
        args.expect_model, args.expect_market, args.expect_n = exp["model"], exp["market"], exp["n"]
        print(f"  expectation from history: board capture {exp['captured_at']} games={exp['games']}"
              f" model={exp['model']} market={exp['market']} n={exp['n']}")
    scratch = Path(os.environ.get("TEMP", ".")) / "live_gameline_rescore"
    scratch.mkdir(parents=True, exist_ok=True)

    # --- records -------------------------------------------------------
    # SPORT-SCOPED, and not cosmetically: with a bare `ledger_{date}.jsonl` an
    # earlier --sport ncaaf run left its 44 MB ledger where a later --sport mlb run
    # read it, scoring 0 games off the wrong sport entirely (measured 2026-10-06).
    path = Path(args.ledger) if args.ledger else scratch / f"ledger_{sport}_{date}.jsonl"
    try:
        if args.ledger or path.exists():
            raw = path.read_bytes()
        else:
            raw = _fetch_ledger(date, sport, args.base_url, path)
    except Exception as exc:  # noqa: BLE001
        print(f"FAILED to obtain ledger for {date}: {exc}", file=sys.stderr)
        return 2
    records = [json.loads(line) for line in raw.decode("utf-8").splitlines() if line.strip()]
    if not records:
        print(f"ledger for {date} is EMPTY ({len(raw)} bytes)", file=sys.stderr)
        return 2

    # --- finals, restricted to the board's population ------------------
    join = None
    if sport == "soccer":
        scores, join = _final_scores_soccer(date, records)
        print(f"  soccer finals join: leagues={len(join['leagues'])} ({join['league_source']})"
              f" espn_finals={join['espn_finals']} draws_kept={join['draws_kept']}"
              f" unplayed_skipped={join['espn_unplayed_skipped']}"
              f" ledger_games={join['ledger_games']} matched={join['matched']}")
        for game in join["unmatched"]:
            print(f"    UNMATCHED -- this game is NOT scored: {game}")
        if join["unmatched_scoreable"]:
            print(f"  WARNING: {len(join['unmatched_scoreable'])} unmatched game(s) DO carry a"
                  " scoreable h2h row, so the scored population is SMALLER than the"
                  " ledger's. Do not read the result as a reproduction unless the"
                  " --expect-* gate passes anyway.")
    elif sport == "ncaaf":
        scores, join = _final_scores_ncaaf(date, records)
        print(f"  ncaaf finals join: espn_finals={join['espn_finals']}"
              f" ledger_games={join['ledger_games']} matched={join['matched']}")
        for game in join["orientation_flipped"]:
            print(f"    ORIENTATION FLIPPED (feed listed the sides the other way): {game}")
        for game in join["unmatched"]:
            print(f"    UNMATCHED -- this game is NOT scored: {game}")
        if join["unmatched_scoreable"]:
            print(f"  WARNING: {len(join['unmatched_scoreable'])} unmatched game(s) DO carry a"
                  " scoreable h2h row, so the scored population is SMALLER than the"
                  " ledger's. Do not read the result as a reproduction unless the"
                  " --expect-* gate passes anyway.")
        elif join["unmatched"]:
            print(f"  {len(join['unmatched'])} unmatched game(s), NONE of them scoreable, so the"
                  f" h2h measurement is unaffected ({join['scoreable_games']} scoreable games"
                  " in the ledger).")
        for game in join.get("espn_unused") or []:
            print(f"    ESPN final no ledger game matched: {game}")
    else:
        scores = _final_scores(date)
    excluded = [str(g) for g in args.exclude_game_pk]
    kept = {k: v for k, v in scores.items() if k not in excluded}
    missing = [g for g in excluded if g not in scores]

    score = score_ledger_records(records, finals_from_scores(kept), final_scores=kept)

    def _reproduces(candidate: dict) -> bool:
        if args.expect_model is None or args.expect_market is None or not args.expect_n:
            return False
        got = candidate["all_records"]
        want_model_n, _, want_market_n = args.expect_n.partition("/")
        return (got["model"]["brier"] is not None and got["market"]["brier"] is not None
                and abs(got["model"]["brier"] - args.expect_model) <= 1e-5
                and abs(got["market"]["brier"] - args.expect_market) <= 1e-5
                and got["model"]["n"] == int(want_model_n)
                and got["market"]["n"] == int(want_market_n))

    if args.search_exclusions and not excluded and not _reproduces(score):
        # THE BOARD'S POPULATION, FOUND RATHER THAN GUESSED. Only a UNIQUE
        # exact match is accepted: two candidates that both reproduce would
        # mean the gate cannot tell them apart, and picking one is a guess.
        hits = []
        for pk in sorted(scores):
            trial = {k: v for k, v in scores.items() if k != pk}
            if _reproduces(score_ledger_records(records, finals_from_scores(trial),
                                                final_scores=trial)):
                hits.append(pk)
        print(f"  exclusion search over {len(scores)} finals: {len(hits)} exact match(es) {hits}")
        if len(hits) == 1:
            excluded = hits
            kept = {k: v for k, v in scores.items() if k not in excluded}
            score = score_ledger_records(records, finals_from_scores(kept), final_scores=kept)

    print(f"=== {date} re-scored by the CURRENT scorer ===")
    # The dict means different things per sport: for mlb it is every StatsAPI final
    # for the date, for ncaaf only the ones that JOINED, so label it accordingly
    # rather than printing one number under two meanings.
    finals_label = ("espn_finals_matched" if sport in ("ncaaf", "soccer")
                    else "statsapi_finals")
    print(f"  ledger bytes={len(raw)} records={len(records)} {finals_label}={len(scores)}"
          f" excluded={excluded or 'none'} scored_games={score['games_with_outcome']}")
    if missing:
        print(f"  WARNING: --exclude-game-pk {missing} not among StatsAPI finals (no effect)")
    for name in ("all_records", "priceable_only", "fresh_quotes_only"):
        block = score.get(name) or {}
        model, market = block.get("model") or {}, block.get("market") or {}
        paired = block.get("model_paired") or {}
        if model.get("brier") is None:
            print(f"  {name:18s} NO DATA")
            continue
        diff = (round(paired["brier"] - market["brier"], 5)
                if paired.get("brier") is not None and market.get("brier") is not None else None)
        print(f"  {name:18s} model={model['brier']} paired={paired.get('brier')}"
              f" market={market.get('brier')} n={model['n']}/{market.get('n')} paired_diff={diff}")
    print(f"  quote_age_absent={score.get('quote_age_absent')}"
          f" fresh_quote_seconds={score.get('fresh_quote_seconds')}")

    # --- verification gate ---------------------------------------------
    if args.expect_records_considered is not None:
        # THE PRE-FIX WINDOW, AND WHY THE STRONG GATE CANNOT SERVE IT.
        # `75cf9aec` fixed a scorer that compared totals `P(over)` and spreads
        # `P(home covers)` against "did the home team win", so for any date
        # summarised before it the retained `all_records` MEASURES THAT BUG.
        # The current scorer cannot reproduce it, by design, and a gate
        # demanding it would refuse every such date forever.
        #
        # Reproducing the PRE-FIX number with the PRE-FIX code was tried and
        # does not close the gap either: that scorer keys finals on `game_pk`
        # OR `event_id` off the board grid, and `findings_2026-09-08` measured
        # that the served grid no longer rebuilds that index (0 entries against
        # the server's own `finals_seen: 2598`). Measured here on 08-29 against
        # `ad4bc5c6`: the replay matches `records_considered` 5554/5554 exactly
        # and still yields 15 games / n=5380 against the retained 16 / 4917.
        #
        # So the board's population is UNRECONSTRUCTABLE for these dates. It is
        # also known to be LOSSY: `score_live_gameline_offline.py` measured the
        # board's index at 143 games over 08-20..08-31 where StatsAPI gives
        # 157, and the shortfall lands on whichever games upstream score
        # nulling touched, so it is not random.
        #
        # This anchor therefore proves only that the SAME LEDGER was scored.
        # The row records that in `finals_population`, so a pool can split on
        # it instead of averaging two populations into one number.
        if args.finals_population != "statsapi":
            print("--expect-records-considered proves only the LEDGER, never the board's"
                  " finals population, so it requires --finals-population statsapi.",
                  file=sys.stderr)
            return 3
        got_rc = score.get("records_considered")
        ok_rc = got_rc == args.expect_records_considered
        print("")
        print(f"  ANCHOR records_considered: got={got_rc}"
              f" expected={args.expect_records_considered}"
              f" {'OK' if ok_rc else 'MISMATCH'}")
        if not ok_rc:
            print("ANCHOR FAILED: this is not the ledger the board scored.", file=sys.stderr)
            return 4
        print("    => the same ledger, scored on the StatsAPI population.")
        checks = {"records_considered": (got_rc, args.expect_records_considered)}

    elif args.expect_model is None or args.expect_market is None or not args.expect_n:
        print("\nNO EXPECTATION: pass --expect-model/--expect-market/--expect-n (the retained\n"
              "all_records figures) so the re-score can be proved to be the board's own\n"
              "measurement, or --expect-records-considered for a pre-fix date whose retained\n"
              "figures the current scorer cannot reproduce. Refusing to append a row nothing\n"
              "checked.", file=sys.stderr)
        return 3

    else:
        want_model_n, _, want_market_n = args.expect_n.partition("/")
        got = score["all_records"]
        checks = {
            "model_brier": (got["model"]["brier"], args.expect_model),
            "market_brier": (got["market"]["brier"], args.expect_market),
            "model_n": (got["model"]["n"], int(want_model_n)),
            "market_n": (got["market"]["n"], int(want_market_n)),
        }
        def _differs(got, want):
            # A None `got` means the re-score produced NO measurement for that field.
            # That is a FAILURE to report, not a crash: `abs(None - 0.1)` used to raise
            # TypeError here and hide the one line the operator needed (measured
            # 2026-10-06, a run that scored 0 games against an expectation of 4).
            if got is None:
                return True
            if isinstance(want, float):
                return abs(got - want) > 1e-5
            return got != want

        failed = {k: v for k, v in checks.items() if _differs(v[0], v[1])}
        print("\n  VERIFICATION against the retained summary (all_records):")
        for key, (got_v, want_v) in checks.items():
            print(f"    {key:13s} got={got_v} retained={want_v}"
                  f" {'OK' if key not in failed else 'MISMATCH'}")
        if failed:
            print(f"\nVERIFICATION FAILED on {sorted(failed)} -- this re-score is NOT the board's\n"
                  "measurement, so its fresh_quotes_only is not poolable with the rest of the\n"
                  "series. Find the finals the board actually had (a leave-one-out search over\n"
                  "StatsAPI finals identifies a late game the board never saw) before appending.",
                  file=sys.stderr)
            return 4
        print("    => EXACT: the current scorer reproduces the retained measurement.")

    # --- the SEGMENT blocks, scored exactly as the board build now does ---
    # (`segment_score_blocks`), against StatsAPI linescores of the SAME kept
    # finals the gate just verified -- so a segment row can only be graded on a
    # game the board also had as final.
    event_to_game = _event_to_game_from_ledger(records)
    seg_lookup = MlbSegmentActuals(event_to_game=event_to_game, final_game_pks=set(kept))
    segments = segment_score_blocks(records, finals_from_scores(kept), kept,
                                    sport=args.sport, segment_actuals=seg_lookup)
    if segments:
        for seg, block in sorted((segments.get("by_segment") or {}).items()):
            allr = block.get("all_records") or {}
            print(f"  segment {seg:7s} h2h games={block.get('games_with_outcome')}"
                  f" paired={((allr.get('model_paired') or {}).get('brier'))}"
                  f" market={((allr.get('market') or {}).get('brier'))}"
                  f" diff={allr.get('model_minus_market_brier')}"
                  f" n={((allr.get('market') or {}).get('n'))}")
        print(f"  segment lookup: {segments.get('lookup')}")

    # --- the row --------------------------------------------------------
    row = {
        "sport": args.sport,
        "date": date,
        "captured_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "games_with_outcome": score["games_with_outcome"],
        "records_considered": score.get("records_considered"),
        "scored_markets": score.get("scored_markets"),
        "records_by_market": score.get("records_by_market"),
        "all_records": score.get("all_records"),
        "last_per_game": score.get("last_per_game"),
        "priceable_only": score.get("priceable_only"),
        "fresh_quotes_only": score.get("fresh_quotes_only"),
        "fresh_quote_seconds": score.get("fresh_quote_seconds"),
        "by_quote_age": score.get("by_quote_age"),
        "quote_age_absent": score.get("quote_age_absent"),
        "unscored": score.get("unscored"),
        "segments": segments,
        # --- PROVENANCE. THIS ROW IS NOT A BOARD CAPTURE. ---------------
        # `backfill` already means "re-captured a past date FROM THE BOARD".
        # This row never touched the board's scorer output, so it needs its
        # own word: a reader (or a future pooling rule) must be able to tell
        # a reconstruction from an observation without inferring it from a
        # timestamp. `rescored_from_ledger` is that word, and the verified
        # block below is what earns it.
        "backfill": True,
        "rescored_from_ledger": True,
        # WHICH POPULATION THIS ROW'S GAMES CAME FROM. A pool that averages
        # `board` and `statsapi` rows is comparing two selections of games, and
        # the difference is NOT random -- the board's index drops whichever
        # games upstream score nulling touched. Recorded at top level, not
        # buried in `rescore`, because it decides whether a row may be pooled.
        "finals_population": args.finals_population,
        "rescore": {
            "reason": ("recover cuts/blocks the retained summary lacks: fresh_quotes_only "
                       "(4d20ea00), point_forecast (contract 3), segments (2026-09-28)"),
            "finals_population": args.finals_population,
            "anchor": ("records_considered" if args.expect_records_considered is not None
                       else "retained_all_records_exact"),
            "ledger_path": LEDGER_PATH.format(sport=sport, date=date),
            "ledger_bytes": len(raw),
            "ledger_sha256_16": hashlib.sha256(raw).hexdigest()[:16],
            "finals_source": "statsapi.mlb.com/api/v1/schedule",
            "statsapi_finals": len(scores),
            "excluded_game_pks": excluded,
            "verified_against_retained": {k: {"got": v[0], "retained": v[1]}
                                          for k, v in checks.items()},
            **_scorer_provenance(),
        },
    }

    # Every other scoring field the board's own captures keep, from the ONE
    # shared list -- `point_forecast` and `scorer_contract` above all. This row
    # used to drop both, so a re-score could never carry totals/spreads.
    for key in RETAINED_SCORE_KEYS:
        row.setdefault(key, score.get(key))

    if args.json_out:
        Path(args.json_out).write_text(json.dumps(score, indent=2), encoding="utf-8")

    if not args.append:
        print("\n  (--append not given; nothing written)")
        return 0

    # history.jsonl is SHARED and append-only -- other sessions and the
    # snapshot cron write it too. Open in append mode and never rewrite it.
    before = sum(1 for _ in history.open(encoding="utf-8")) if history.exists() else 0
    with history.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row) + "\n")
    after = sum(1 for _ in history.open(encoding="utf-8"))
    print(f"\n  appended -> {history}  ({before} -> {after} rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
