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
    SCHEMA  THIS ARTIFACT HAS TWO CONSUMERS AND BOTH ARE LOAD-BEARING.
            1. `ladders_common.pitcher_rows_from_summary` (top-props board)
               reads pitcherName, team, matchup, marketLine, mean, mode,
               overLineProb, simCount.
            2. `cards.py::_pregame_starter_ladder_badges_for_pitcher` (the
               compact board's pregame starter chips) additionally needs
               **gamePk, pitcherId and ladder[{total,hitProb}]** -- it joins on
               gamePk (`cards.py:1166`) and returns None on an empty ladder
               (`cards.py:1102`).
    SHAPE   groups.pitcher.strikeouts.rows[]  (`_extract_prop_group`)

**THE SCHEMA REGRESSION THIS FILE ALREADY CAUSED ONCE.** The list above named
only consumer 1 until 2026-08-20, and this module emitted only consumer 1's
fields. Consumer 2 was named in the paragraph above as an inherited reader and
then not served. Result: from the cutover until 2026-08-20, EVERY pregame
starter ladder chip on the MLB board was dead -- 3,978 rows with `ladder=0` and
`gamePk=0`, 0 of 18 starters carrying a chip -- and because the compact card
hides the starter's NAME along with its chips, 12 of 18 pregame sides rendered
no starter at all. Nothing failed: the join was perfect (`matchedPlayers 18,
oddsPlayers 18, unmatchedOdds 0`), `is_stale` said fresh, every test passed, and
no log line was emitted. The user reported it from the board.

**So: a reader added to the list above is a reader this module must be TESTED
against.** `test_the_real_native_reader_consumes_the_output` covers consumer 1
and passed throughout the outage; `test_the_CARDS_reader_consumes_the_output`
now covers consumer 2. Adding a third consumer means adding a third such test --
a name grep for the field will not catch this, because the field name is present
in the reader and simply absent from the data.

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
from syndicate.features.shared.probability_refusal import CERTAINTY_REFUSED

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
    # `None` HERE IS PERMANENT AND CORRECT, not an oversight. OddsAPI publishes
    # no pitches-thrown or batters-faced market for MLB: searched 2026-08-20
    # across scripts/, syndicate/ and pipeline/ and there is no such market key
    # anywhere in the platform -- every `pitches`/`batters_faced` hit is one of
    # our OWN sim fields (features/mlb/cards.py, shared/game_shape.py), never a
    # book market. These two ladders are sim-only by nature; a reader seeing 0
    # market lines here is seeing the truth, not a bug. Do not re-investigate.
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
    # `batter_strikeouts` IS fetched -- it is in `DEFAULT_HITTER_MARKETS` in
    # scripts/fetch_mlb_oddsapi_local.py and has a line preference there. The
    # `None` this replaces was my own placeholder, and it meant the builder
    # never looked for a market that was already being paid for. `#440`.
    "hitter_strikeouts": {"dist": "strikeouts_dist",      "mean": "so_mean",  "odds": "batter_strikeouts",      "label": "Strikeouts"},
    # WIRED BUT NOT YET FED, deliberately and visibly. These three are valid
    # OddsAPI keys and are already modelled elsewhere in the platform
    # (shared/mlb_prop_calibration.py, shared/prop_projections.py,
    # shared/live_projection_join.py) -- but they are NOT in
    # `DEFAULT_HITTER_MARKETS`, so nothing fetches them and these rows will read
    # 0 until that list changes. Mapping them here rather than leaving `None`
    # makes the remaining work exactly one line in the fetcher instead of a
    # rediscovery. Cost of that line, measured 2026-08-20: OddsAPI player props
    # bill per market per event, burn is ~87,635 credits/day and 3,391,356
    # remain against the 5M cap = 39 days, i.e. about the rest of the season
    # with no slack. Adding 3 markets to a 7-market hitter fetch is ~+43% on
    # that path. That is a spend decision, not a code decision.
    "doubles":           {"dist": "doubles_dist",         "mean": "2b_mean",  "odds": "batter_doubles",         "label": "Doubles"},
    "triples":           {"dist": "triples_dist",         "mean": "3b_mean",  "odds": "batter_triples",         "label": "Triples"},
    "stolen_bases":      {"dist": "stolen_bases_dist",    "mean": "sb_mean",  "odds": "batter_stolen_bases",    "label": "Stolen bases"},
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
    out: dict[str, Any] = {"mode": mode, "overLineProb": over, "simCount": total}

    # REFUSE AN EXACT CERTAINTY BESIDE A REAL MARKET LINE. `#646`(d).
    #
    # A finite simulation cannot establish impossibility: `overLineProb == 0.0`
    # says the OVER cannot happen, which makes the UNDER a 100%-confidence bet
    # against whatever the book pays. 0.0 is the dangerous end, not 1.0 -- see
    # `shared/probability_refusal.py`, whose `CERTAINTY_REFUSED` is imported
    # rather than re-spelled so there is ONE definition of what counts.
    #
    # Reached for real: the MLB hitter `strikeouts` dist was `{0: n_sims}` for
    # every hitter of every game until 2026-09-04, so this returned exactly 0.0
    # on every strikeouts row that had a line.
    #
    # LABELLED, NOT SILENTLY NULLED. `overLineProb` is ALREADY None for "no
    # market line" (see this function's docstring: a zero probability and an
    # absent market are different facts the card renders differently), so a bare
    # None here would collapse the two. The label mirrors
    # `refuse_published_certainty`'s `_refused` / `_refused_value` pair, and the
    # original value is KEPT -- this is a refusal to price on a certainty, not
    # the loss of one.
    #
    # SCOPED TO `overLineProb` ALONE, deliberately. `_dist_ladder` emits
    # `{total: 0, hitProb: 1.0}` and that 1.0 is P(X >= 0) -- trivially and
    # CORRECTLY certain. A blanket certainty refusal on this surface would blank
    # a true value, which is why this does not live in `_dist_ladder` too.
    #
    # `mode` and `simCount` survive: the sim genuinely produced them. What it
    # cannot state is P(over) from a sample that never crossed the line.
    if isinstance(over, float) and over in CERTAINTY_REFUSED:
        out["overLineProb"] = None
        out["overLineProbRefused"] = "exact_certainty"
        out["overLineProbRefusedValue"] = float(over)
    return out


def _dist_ladder(dist: Any) -> list[dict[str, Any]]:
    """The CUMULATIVE ladder `P(X >= total)` over an outcome histogram.

    **This exists because dropping it silently killed a whole board surface.**
    The compact card's pregame starter chips are built by
    `cards.py::_starter_ladder_badge_from_ladder_row`, which walks exactly this
    list and returns `None` the moment it is empty. When `#440` replaced the
    vendor writer, the output schema was pinned to the TOP-PROPS reader
    (`ladders_common.pitcher_rows_from_summary`), which does not read a ladder —
    so this field, `gamePk` and `pitcherId` all stopped being emitted, and every
    pregame ladder chip on the MLB board went dark with passing tests, no error
    and no log line. Measured on production 2026-08-20: 3,978 rows, `ladder=0`
    on every one of them; 0 of 18 starters carried a ladder-derived chip.

    `hitProb` is `P(X >= total)`, matching the vendor artifact this replaced
    (verified against `daily_ladders_2026_05_29.json`: `total=0 -> hitProb=1.0`,
    monotonically non-increasing) and matching what the reader's `min_hit_prob`
    floors are calibrated against. Getting this direction wrong would not throw
    — it would render confidently wrong chips.

    **Deliberately unfiltered.** The reader owns the thresholds (`> marketLine`,
    `min_hit_prob`, `max_rungs`), and duplicating them here is the coupling that
    caused this bug in the first place. The size control is the CALLER's — see
    `_rows_for_prop`, which puts this on pitcher rows only.
    """
    if not isinstance(dist, dict) or not dist:
        return []
    counts: dict[int, int] = {}
    for k, v in dist.items():
        try:
            counts[int(k)] = int(v)
        except Exception:
            continue
    total = sum(counts.values())
    if total <= 0:
        return []
    ladder: list[dict[str, Any]] = []
    at_or_above = total
    for outcome in sorted(counts):
        # Ascending `total`, because the reader takes the LAST surviving rung's
        # probability as the badge's `hitProb` and its `max_rungs` cap slices
        # from the front.
        ladder.append({"total": int(outcome), "hitProb": round(at_or_above / total, 4)})
        at_or_above -= counts[outcome]
    return ladder


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


def _rows_for_prop(entries, spec, market, name_key, *, with_ladder: bool = False):
    """entries: iterable of (player_id, sim_stats, meta{name,team,opponent,matchup,gamePk})

    `with_ladder` IS THE SIZE CONTROL, and it is a caller decision on purpose.
    `learnings.md` 2026-08-20: this artifact reached 13,678,982 bytes against
    the publish sweep's `_PUBLISH_MAX_BYTES` of 12,582,912, was refused
    SILENTLY, and web served a 28-hour-old copy while every other link in the
    chain read correct. Putting a per-outcome array back on all 3,978 rows is
    exactly the move that re-arms that. So the ladder goes on the 18 PITCHER
    rows, whose sole consumer is `cards.py:1102`, and not on the 234-row hitter
    groups, which have no consumer for it at all (`grep '"ladder"'` over
    `syndicate/`: one MLB hit, and it is the cards reader).
    """
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
        row = {
            name_key: name or f"id {pid}",
            "playerId": pid,
            # `gamePk` and `pitcherId` are what the CARDS reader joins on; the
            # flat fields above are what the TOP-PROPS reader reads. Two
            # consumers, one artifact -- serving only one of them is how this
            # regressed. `pitcherId` is int because `cards.py` compares it with
            # `int(pitcher_id)`; `playerId` stays a str for the existing reader.
            "gamePk": meta.get("gamePk"),
            "team": meta.get("team") or "",
            "opponent": meta.get("opponent") or "",
            "matchup": meta.get("matchup") or "",
            "marketLine": line,
            "mean": stats.get(spec["mean"]),
            "mode": stats_out["mode"],
            "overLineProb": stats_out["overLineProb"],
            "simCount": stats_out["simCount"],
        }
        if name_key == "pitcherName":
            try:
                row["pitcherId"] = int(pid)
            except (TypeError, ValueError):
                row["pitcherId"] = None
        if with_ladder:
            row["ladder"] = _dist_ladder(stats.get(spec["dist"]))
        rows.append(row)

    return _prop_group(
        rows, spec,
        matched=matched,
        odds_total=len(market) if odds_field is not None else 0,
        unmatched_odds=sorted(set(market) - seen) if odds_field is not None else [],
        unmatched_sim=sorted(set(unmatched_sim)),
    )


def _pitcher_entries(date_str, game_pks):
    """`gamePk` is threaded into meta, NOT discarded as `_pk`.

    `cards.py::_pregame_starter_ladder_badges_for_pitcher` joins on it FIRST
    (`cards.py:1166`: `if row_game_pk is None ... continue`), which means an
    absent `gamePk` also makes the `pitcherName` fallback below it unreachable —
    the row can never match no matter how good the name is. It was already in
    hand here and thrown away.
    """
    for game_pk, payload in _sim_games(date_str, game_pks):
        sim = payload.get("sim") if isinstance(payload.get("sim"), dict) else {}
        props = sim.get("pitcher_props") if isinstance(sim.get("pitcher_props"), dict) else {}
        starters = _starter_index(payload)
        for pid, stats in props.items():
            if isinstance(stats, dict):
                yield str(pid), stats, {**(starters.get(str(pid)) or {}), "gamePk": int(game_pk)}


def _hitter_entries(date_str, game_pks):
    """Hitters carry `name` and `team` on the entry itself, so no starter index."""
    for game_pk, payload in _sim_games(date_str, game_pks):
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
                "gamePk": int(game_pk),
            }


def build_pitcher_strikeout_rows(date_str, game_pks):
    """Named entry point kept: this is the group the compact card reads first."""
    entries = list(_pitcher_entries(date_str, game_pks))
    return _rows_for_prop(entries, PITCHER_PROPS["strikeouts"],
                          _market_lines(date_str, "pitcher"), "pitcherName",
                          with_ladder=True)


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
    # EVERY return carries the values it compared. Measured 2026-08-20: the
    # status artifact said `{"stale": false, "reason": "fresh"}` for an artifact
    # whose served copy was 28 hours old, and the verdict alone could not
    # distinguish "the worker's copy really is fresher than web's" from "the
    # timestamp parse failed and fell back to mtime". A diagnostic that reports
    # a verdict without its evidence is half an instrument.
    _evidence: dict[str, Any] = {"path": str(daily_ladders_path(date_str))}
    dest = Path(daily_ladders_path(date_str))
    try:
        dest_mtime = dest.stat().st_mtime
        _evidence["fileMtime"] = dest_mtime
    except Exception:
        return {"stale": True, "reason": "artifact_missing", "evidence": _evidence}

    # *** COMPARE THE CONTENT CLOCK, NOT THE FILE CLOCK. ***
    #
    # Measured 2026-08-19 by the status artifact this module writes: the trigger
    # fired, called `is_stale`, and got `{"stale": false, "reason": "fresh"}` for
    # an artifact whose own `generatedAt` was 2026-08-18T18:20 — 28 hours old.
    #
    # `st_mtime` is the wrong clock. The artifact is SYNCED onto the worker's
    # disk from web, so its mtime is whenever the sync last touched it, while its
    # CONTENT is whatever the last real build produced. A file can therefore look
    # newly-written and be a day stale inside, which is exactly what kept the
    # ladders serving "Market line: -" through four correct deploys.
    #
    # `generatedAt` is written by `build_ladders_artifact` on every real build,
    # so the honest timestamp was in the file the whole time. Fall back to mtime
    # only when the content carries no timestamp — an artifact from before this
    # field existed should not be treated as infinitely fresh.
    effective = dest_mtime
    try:
        doc = json.loads(dest.read_text(encoding="utf-8"))
        raw = str((doc or {}).get("generatedAt") or "").strip()
        if raw:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            content_ts = parsed.timestamp()
            # Take the OLDER of the two. A synced file cannot make stale content
            # look fresh, and a rewritten file cannot make fresh content look old.
            effective = min(dest_mtime, content_ts)
            _evidence["artifactGeneratedAt"] = raw
            _evidence["contentTs"] = content_ts
    except Exception as _exc:
        _evidence["parseError"] = f"{type(_exc).__name__}: {_exc}"
        # Unreadable or unparseable -> fall through on mtime. Deliberately NOT
        # "assume fresh": an unknown must not default to the permissive branch.
        effective = dest_mtime
    dest_mtime = effective

    for side in ("pitcher", "hitter"):
        odds_path = (daily_snapshot_oddsapi_hitter_props_path(date_str) if side == "hitter"
                     else daily_snapshot_oddsapi_pitcher_props_path(date_str))
        try:
            _om = Path(odds_path).stat().st_mtime
            _evidence[f"oddsMtime_{side}"] = _om
            if _om > dest_mtime:
                return {"stale": True, "reason": "odds_newer", "side": side,
                        "evidence": _evidence}
        except Exception:
            continue

    for pk in (game_pks if game_pks is not None else discover_game_pks(date_str)):
        sim_path = daily_sim_artifact_path(date_str, int(pk))
        if sim_path is None:
            continue
        try:
            _sm = Path(sim_path).stat().st_mtime
            _evidence["newestSimMtime"] = max(_evidence.get("newestSimMtime", 0.0), _sm)
            if _sm > dest_mtime:
                return {"stale": True, "reason": "sim_newer", "gamePk": int(pk),
                        "evidence": _evidence}
        except Exception:
            continue
    # The fresh verdict is the one that most needs its evidence: it is the
    # branch that suppresses a rebuild, so a wrong `fresh` is silent forever.
    _evidence["effectiveTs"] = dest_mtime
    return {"stale": False, "reason": "fresh", "evidence": _evidence}


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
                key: _rows_for_prop(pitcher_entries, spec, pitcher_market, "pitcherName",
                                    with_ladder=True)
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
