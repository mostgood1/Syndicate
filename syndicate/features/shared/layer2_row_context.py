"""What a Layer 2 card needs beyond its price: a face and a sentence.

Lane `layer2-row-parity`, 2026-09-15. On the served board that morning, 2,959
Layer 2 rows carried no headshot and no explainer, while 58 legacy rows from an
older pipeline carried both. Those 58 were not a better version of the same rows:
16 of the 39 MLB props were the SAME BET as a Layer 2 row with contradictory
numbers (Kyle Freeland over 11.5 outs: legacy "edge 43.3%", Layer 2 EV -5.1%). So
the answer is to give the Layer 2 rows the two things the legacy rows had, from
the Layer 2 row's OWN numbers, not to copy the legacy rows.

TWO HALVES, SPLIT THE SAME WAY AS THE OPENINGS:

  * `load_layer2_row_context` does the IO, ONCE per build, outside the card loop:
    the MLB locked-policy write-ups (a ~570 KB artifact the daily sim already
    writes) and the NFL roster's ESPN ids.
  * `row_identity` / `row_explainer` are PURE and run per card.

THE EXPLAINER'S NUMBERS ARE THE ROW'S. The locked-policy write-up opens with
"The model lands on the over side in X% of sims, while the market is pricing it
closer to Y%" -- numbers from the vendor pipeline's own snapshot, which can
disagree with the price this row is actually published at. That sentence is
DROPPED and replaced with one built from this row's model probability and no-vig
fair; only the baseball context after it (recent starts, pitch mix, lineup spot)
is kept.
"""
from __future__ import annotations

import csv
import json
import re
from datetime import date as _date
from pathlib import Path
from typing import Any, Mapping

from syndicate.features.shared.layer2_board import (
    _american_from_probability,
    _as_float,
    _is_lay_market,
    _model_prob_for_side,
    _pick_label,
    _segment_label,
)
from syndicate.features.shared.prop_projections import _norm_name

_NFL_HEADSHOT_URL = "https://a.espncdn.com/i/headshots/nfl/players/full/{espn_id}.png"

# Locked-policy GAME markets -> the Layer 2 market key. Props carry their own
# `prop` key, which already matches (`outs`, `strikeouts`, `batter_hits`, ...).
_NARRATIVE_GAME_MARKETS = {"ml": "h2h", "totals": "totals"}

# Words, not keys. Unmapped keys fall back to their own words (underscores and a
# `batter_`/`player_`/`pitcher_` prefix removed) rather than vanishing.
_MARKET_WORDS = {
    "strikeouts": "strikeouts",
    "outs": "outs",
    "earned_runs": "earned runs",
    "hits_allowed": "hits allowed",
    "walks_allowed": "walks allowed",
    "batter_hits": "hits",
    "batter_total_bases": "total bases",
    "batter_hits_runs_rbis": "hits + runs + RBIs",
    "batter_runs_scored": "runs",
    "batter_rbis": "RBIs",
    "batter_home_runs": "home runs",
    "batter_strikeouts": "strikeouts",
    "totals": "total",
    "totals_alt": "alternate total",
    "spreads": "spread",
    "spreads_alt": "alternate spread",
    "h2h": "moneyline",
    "h2h_3_way": "3-way moneyline",
    "btts": "both teams to score",
    "alternate_totals_corners": "total corners",
}

_LEAD_SENTENCE_RE = re.compile(
    r"^\s*(?:The model lands on the [\w ]+? side in [\d.]+% of sims, while the market is pricing it"
    r" closer to [\d.]+%\.|This snapshot only used .*?closer to [\d.]+%\.)\s*",
    re.IGNORECASE,
)


# --------------------------------------------------------------------------
# IO, once per build
# --------------------------------------------------------------------------


def load_layer2_row_context(selected_date: Any) -> dict[str, Any]:
    """The per-build context the card builder reads. Never raises."""
    date_text = str(selected_date or "").strip()
    context: dict[str, Any] = {"narratives": {}, "nfl_espn_ids": {}, "errors": {}, "selected_date": date_text}
    if not date_text:
        return context
    try:
        context["narratives"] = _mlb_narratives(date_text)
    except Exception as exc:  # noqa: BLE001 -- enrichment must never break the build
        context["errors"]["mlb_narratives"] = f"{type(exc).__name__}: {exc}"
    try:
        context["nfl_espn_ids"] = _nfl_espn_ids(date_text)
    except Exception as exc:  # noqa: BLE001
        context["errors"]["nfl_espn_ids"] = f"{type(exc).__name__}: {exc}"
    print(
        "[layer2_row_context] ROW_CONTEXT date=%s mlb_narratives=%d nfl_espn_ids=%d errors=%s"
        % (date_text, len(context["narratives"]), len(context["nfl_espn_ids"]), sorted(context["errors"]) or "none"),
        flush=True,
    )
    return context


def _first_reason(record: Mapping[str, Any]) -> str:
    reasons = record.get("reasons")
    if isinstance(reasons, list):
        for item in reasons:
            if isinstance(item, str) and item.strip():
                return item.strip()
    return str(record.get("reason_summary") or "").strip()


def _mlb_narratives(date_text: str) -> dict[tuple, dict[str, Any]]:
    from syndicate.features.mlb.sources import daily_artifact_path

    path = Path(daily_artifact_path(date_text, suffix="_locked_policy"))
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    index: dict[tuple, dict[str, Any]] = {}
    if not isinstance(payload, Mapping):
        return index
    for top in ("markets", "shadow_markets"):
        groups = payload.get(top)
        if not isinstance(groups, Mapping):
            continue
        for block in groups.values():
            if not isinstance(block, Mapping):
                continue
            for list_name in ("recommendations", "other_playable_candidates"):
                for record in block.get(list_name) or ():
                    if not isinstance(record, Mapping):
                        continue
                    player = record.get("pitcher_name") or record.get("player_name")
                    if player:
                        market = record.get("prop")
                        player_id = record.get("pitcher_id") if record.get("pitcher_name") else record.get("batter_id")
                    else:
                        market = _NARRATIVE_GAME_MARKETS.get(str(record.get("market") or "").strip().lower())
                        player_id = None
                    key = narrative_key(
                        event_id=record.get("event_id"),
                        player_name=player,
                        market=market,
                        side=record.get("selection"),
                        line=record.get("market_line"),
                    )
                    if not key or key in index:
                        continue
                    index[key] = {
                        "text": clean_narrative(_first_reason(record)),
                        "player_id": str(player_id) if str(player_id or "").strip().isdigit() else None,
                    }
    return index


def _nfl_season(date_text: str) -> int:
    day = _date.fromisoformat(date_text[:10])
    return day.year if day.month >= 3 else day.year - 1


def _nfl_espn_ids(date_text: str) -> dict[str, str]:
    from syndicate.features.nfl.fantasy_players import roster_path

    path = Path(roster_path(_nfl_season(date_text)))
    if not path.is_file():
        return {}
    found: dict[str, str] = {}
    ambiguous: set[str] = set()
    with path.open(encoding="utf-8", newline="") as handle:
        for record in csv.DictReader(handle):
            espn_id = str(record.get("espn_id") or "").strip()
            if espn_id.endswith(".0"):
                espn_id = espn_id[:-2]
            if not espn_id.isdigit():
                continue
            name = _norm_name(record.get("full_name") or record.get("football_name") or record.get("player_name"))
            if not name:
                continue
            if name in found and found[name] != espn_id:
                ambiguous.add(name)
            found.setdefault(name, espn_id)
    # TWO PLAYERS, ONE NAME: no face at all rather than the wrong one.
    for name in ambiguous:
        found.pop(name, None)
    return found


# --------------------------------------------------------------------------
# Pure, per card
# --------------------------------------------------------------------------


def narrative_key(
    *, event_id: Any = None, player_name: Any = None, market: Any = None, side: Any = None, line: Any = None
) -> tuple | None:
    market_text = str(market or "").strip().lower()
    side_text = str(side or "").strip().lower()
    if not market_text or not side_text:
        return None
    line_value = None if market_text == "h2h" else _as_float(line)
    line_key = None if line_value is None else round(line_value, 1)
    name = _norm_name(player_name)
    if name:
        return ("prop", name, market_text, side_text, line_key)
    event = str(event_id or "").strip()
    return ("game", event, market_text, side_text, line_key) if event else None


def clean_narrative(text: Any) -> str | None:
    body = _LEAD_SENTENCE_RE.sub("", str(text or "").strip(), count=1).strip()
    return body or None


def row_narrative(row: Mapping[str, Any], context: Mapping[str, Any] | None) -> dict[str, Any] | None:
    narratives = (context or {}).get("narratives")
    if not isinstance(narratives, Mapping) or not narratives:
        return None
    if str(row.get("sport") or "").strip().lower() != "mlb":
        return None
    # The write-ups are FULL-GAME. A first-five total at the same number is a
    # different bet and must not borrow a nine-inning explanation.
    if str(row.get("segment") or "full").strip().lower() not in {"", "full", "full_game", "game"}:
        return None
    key = narrative_key(
        event_id=row.get("event_id"),
        player_name=row.get("player_name"),
        market=row.get("market"),
        side=row.get("side"),
        line=row.get("line"),
    )
    found = narratives.get(key) if key else None
    return found if isinstance(found, Mapping) else None


def _mlb_headshot(player_id: str) -> str | None:
    if not player_id.isdigit():
        return None
    try:
        from syndicate.features.mlb.cards import _mlb_headshot_url
    except Exception:  # noqa: BLE001
        return None
    return _mlb_headshot_url(int(player_id))


def row_identity(row: Mapping[str, Any], context: Mapping[str, Any] | None) -> dict[str, Any]:
    """`headshot_url` (and, for MLB, `player_id`) where an id source exists. Else {}."""
    player = str(row.get("player_name") or "").strip()
    if not player:
        return {}
    sport = str(row.get("sport") or "").strip().lower()
    if sport == "mlb":
        projection = row.get("projection") if isinstance(row.get("projection"), Mapping) else {}
        player_id = str(projection.get("player_id") or "").strip()
        if not player_id:
            player_id = str((row_narrative(row, context) or {}).get("player_id") or "").strip()
        url = _mlb_headshot(player_id) if player_id else None
        return {"player_id": player_id, "headshot_url": url} if url else {}
    if sport == "nfl":
        espn_id = ((context or {}).get("nfl_espn_ids") or {}).get(_norm_name(player))
        # `player_id` is NOT set here: consumers read it as an MLBAM-style id,
        # and an ESPN id in that field would be a wrong id, not a missing one.
        return {"headshot_url": _NFL_HEADSHOT_URL.format(espn_id=espn_id)} if espn_id else {}
    # NHL / NBA / WNBA / NCAAF / soccer (lane layer2-board-ui-redesign,
    # 2026-10-08): cached name -> CDN id maps, ambiguous names dropped.
    from syndicate.features.shared.player_headshots import headshot_url

    url = headshot_url(row)
    return {"headshot_url": url} if url else {}


def _market_words(market: str) -> str:
    key = market.strip().lower()
    if key in _MARKET_WORDS:
        return _MARKET_WORDS[key]
    text = re.sub(r"^(batter|player|pitcher)_", "", key)
    return text.replace("_", " ").strip() or "this market"


def _fmt_line(value: float) -> str:
    return f"{value:.1f}" if float(value).is_integer() else f"{value:g}"


def _fmt_signed(value: float) -> str:
    text = _fmt_line(abs(value))
    return f"+{text}" if value > 0 else (f"-{text}" if value < 0 else text)


def _fmt_american(value: Any) -> str | None:
    number = _as_float(value)
    if number is None:
        return None
    rounded = int(round(number))
    return f"+{rounded}" if rounded > 0 else str(rounded)


def _subject(row: Mapping[str, Any]) -> str | None:
    side = str(row.get("side") or "").strip().lower()
    market = str(row.get("market") or "").strip().lower()
    line = _as_float(row.get("line"))
    player = str(row.get("player_name") or "").strip()
    segment = _segment_label(row.get("segment"), row.get("sport"))
    tail = f" ({segment})" if segment else ""
    words = _market_words(market)
    if player:
        if side in {"over", "under"} and line is not None:
            return f"{player} {side} {_fmt_line(line)} {words}"
        if side in {"yes", "no"}:
            return f"{player} {words}: {side}"
        return f"{player} {words}"
    if side in {"over", "under"} and line is not None:
        if market in {"totals", "total"}:
            return f"the {side} {_fmt_line(line)}{tail}"
        return f"{words} {side} {_fmt_line(line)}{tail}"
    if side in {"home", "away"}:
        team = _pick_label(row)
        if market.startswith("spreads") and line is not None:
            return f"{team} {_fmt_signed(line)}{tail}"
        if _is_lay_market(market):
            return f"{team}{tail}"
        return f"{team} to win{tail}"
    if side == "draw":
        return f"the draw{tail}"
    if side in {"yes", "no"}:
        return f"{words}: {side}{tail}"
    return None


def _is_count_market(row: Mapping[str, Any]) -> bool:
    if str(row.get("player_name") or "").strip():
        return True
    return str(row.get("market") or "").strip().lower().startswith("totals")


def _projection_sentence(row: Mapping[str, Any], model: float, projected: float, line: float) -> str:
    """The projection, said so it cannot read as a contradiction of the line above it.

    `projected` is the sim's MEAN. On a skewed count the mean and the likely
    result can sit on opposite sides of a low line: Michael Van Buren Jr. Under
    0.5 passing TDs read "Our sim has him under 0.5 at 52.3% ... It projects 0.7
    against the 0.5 line" (user 2026-10-08, item 9) -- both true, and read
    together as the sim contradicting itself. When the mean is on the far side
    from the side the sim prices above 50%, say why both hold.
    """
    side = str(row.get("side") or "").strip().lower()
    line_text = _fmt_line(line)
    mean_over = projected > line
    mean_under = projected < line
    if side in {"over", "under"} and model >= 0.5 and ((side == "under" and mean_over) or (side == "over" and mean_under)):
        pull = "up by its big games" if side == "under" else "down by its quiet ones"
        return (
            f"Its average is {projected:.1f}, on the other side of the {line_text} line, "
            f"but {model:.1%} of its simulations finish {side} it: the average is pulled {pull}."
        )
    return f"It projects an average of {projected:.1f} against the {line_text} line."


def row_explainer(
    row: Mapping[str, Any], quote: Mapping[str, Any], context: Mapping[str, Any] | None = None
) -> str | None:
    """One plain paragraph on why this row is on the board, from its own numbers."""
    subject = _subject(row)
    if not subject:
        return None
    fair = _as_float(quote.get("fair_probability"))
    if fair is not None and not 0.0 < fair < 1.0:
        fair = None
    model = _model_prob_for_side(row)
    projection = row.get("projection") if isinstance(row.get("projection"), Mapping) else {}
    live = str(projection.get("basis") or "").strip().lower() == "live_resim" or projection.get("live_prob_over") is not None
    books = int(_as_float(quote.get("books_quoting")) or 0)
    across = f" across {books} books" if books > 1 else ""
    parts: list[str] = []
    if model is not None and fair is not None:
        who = "The live re-sim" if live else "Our sim"
        parts.append(f"{who} has {subject} at {model:.1%}; the no-vig market{across} says {fair:.1%}.")
    else:
        price = _fmt_american(quote.get("price"))
        book = str(quote.get("bookmaker") or "").strip().upper()
        fair_price = _fmt_american(_american_from_probability(fair)) if fair is not None else None
        if price and book and fair_price:
            parts.append(
                f"No sim view on {subject}; it is ranked on price: {book} {price} against a no-vig fair of {fair_price}{across}."
            )
        else:
            parts.append(f"No sim view on {subject}; it is ranked on price alone.")
    projected = _as_float(projection.get("projected"))
    line = _as_float(row.get("line"))
    if model is not None and projected is not None and line is not None and _is_count_market(row):
        parts.append(_projection_sentence(row, model, projected, line))
    narrative = row_narrative(row, context)
    if narrative and narrative.get("text"):
        parts.append(str(narrative["text"]))
    # RECENCY + MATCHUP LEAD the evidence (user 2026-10-08): right after the
    # price/sim sentence, before projection detail and season context.
    recent = row_recent_matchup_text(row, context)
    if recent:
        parts.insert(1 if parts else 0, recent)
    season = row_season_text(row, context)
    if season:
        parts.append(season)
    return " ".join(parts)


# --------------------------------------------------------------------------
# Season metrics -- ONE explanation layer for the ONE list
# --------------------------------------------------------------------------
#
# User 2026-10-07: "we shouldnt have seperate lists being generated" -- the Layer
# 2 board IS the pick list, so the season-metric evidence that
# `intelligence_season_evidence` reads (lane intelligence-evidence-coverage,
# `ced2618f`) belongs on Layer 2 rows. Before this it reached only the legacy
# intelligence pool (77 recommendations) and 0 of 4,500 served board rows.
#
# Display only: appended to `detail`; no field the score, the shortlist floors,
# `portfolio_commit` or execution read is touched.
#
# Memoised in the per-build `context` dict: thousands of rows share a few
# hundred games, and the signal for a game side does not depend on the book or
# the line. A caller with no context (None) still gets the sentence, unmemoised.

# Sports whose prop recency/matchup evidence is cheap enough per card for a
# board build -- warm, cached, measured on the fleet 2026-10-08 after the read
# cache, the name memo and the NCAAF/soccer index fixes: wnba 30 ms, nfl 7 ms,
# ncaaf 71 ms, soccer 69 ms, nhl 103 ms per card (identical facts cached vs
# uncached). MLB is served by its batter-vs-pitcher path, not this one.
_RECENT_MATCHUP_SPORTS = frozenset({"mlb", "nba", "wnba", "nfl", "nhl", "ncaaf", "soccer"})
# Per-build, PER-SPORT budget: cards are built in board order, so each sport's
# top rows are served first, and one slow sport can neither starve the others
# (measured 2026-10-08: a single shared 120 s budget ran out before NHL got any)
# nor stretch a build by more than this per sport.
_RECENT_MATCHUP_BUDGET_SECONDS_PER_SPORT = 30.0
# Sentences persist ACROSS builds for this long: form and matchup data change
# daily, so a later build only computes picks it has not seen. Only the short
# strings persist -- parsed logs live in the per-build read cache and are freed.
_RECENT_MATCHUP_TTL_SECONDS = 1800.0
_RECENT_MATCHUP_TEXT: dict[tuple, tuple[float, str | None]] = {}
_RECENT_MATCHUP_TEXT_MAX = 20000
_RECENT_MATCHUP_MODULE: dict[int, dict] = {}


def row_recent_matchup_text(row: Mapping[str, Any], context: Mapping[str, Any] | None = None) -> str | None:
    """'Recent form: ... Matchup: ...' for a prop row, or None. Never raises."""
    import time as _time

    try:
        sport = str(row.get("sport") or "").strip().lower()
        if sport not in _RECENT_MATCHUP_SPORTS or str(row.get("kind") or "").lower() != "prop":
            return None
        from syndicate.features.intelligence_recent_matchup import _memo_key, prop_recent_matchup_text
        from syndicate.features.shared.prop_evidence.common import build_read_cache, eastern_date

        commence = str(row.get("commence_time") or "").strip()
        # The BUILD's date when there is one (Ask passes the board date too): keyed
        # per game date, soccer re-loaded its projection index for every kickoff
        # date in the window (70 s on the fleet, 2026-10-08).
        board_date = str((context or {}).get("selected_date") or "").strip() if isinstance(context, Mapping) else ""
        selected = board_date or (eastern_date(commence) if commence else None) or _date.today().isoformat()
        key = (selected,) + _memo_key(row)
        now = _time.monotonic()
        hit = _RECENT_MATCHUP_TEXT.get(key)
        if hit is not None and now - hit[0] < _RECENT_MATCHUP_TTL_SECONDS:
            return hit[1]
        if isinstance(context, dict):
            state = context.setdefault("recent_matchup", {"read_cache": {}, "spent": {}, "logged": set()})
        else:
            bucket = int(_time.time() // 60)
            for stale in [k for k in _RECENT_MATCHUP_MODULE if k != bucket]:
                _RECENT_MATCHUP_MODULE.pop(stale, None)
            state = _RECENT_MATCHUP_MODULE.setdefault(bucket, {"read_cache": {}, "spent": {}, "logged": set()})
        spent = state["spent"].get(sport, 0.0)
        if spent >= _RECENT_MATCHUP_BUDGET_SECONDS_PER_SPORT:
            if sport not in state["logged"]:
                state["logged"].add(sport)
                print(f"[layer2_row_context] RECENT_MATCHUP_BUDGET_SPENT sport={sport} seconds={spent:.1f}", flush=True)
            return None
        started = _time.perf_counter()
        with build_read_cache(state["read_cache"]):
            text = prop_recent_matchup_text(row, selected_date=selected)
        state["spent"][sport] = spent + (_time.perf_counter() - started)
        if len(_RECENT_MATCHUP_TEXT) >= _RECENT_MATCHUP_TEXT_MAX:
            _RECENT_MATCHUP_TEXT.clear()
        _RECENT_MATCHUP_TEXT[key] = (now, text)
        return text
    except Exception as exc:  # noqa: BLE001 -- enrichment must never break the build
        print(f"[layer2_row_context] RECENT_MATCHUP_FAILED error={type(exc).__name__}: {exc}", flush=True)
        return None


_PITCHER_MARKET_PREFIX = ("pitcher_",)
_SEASON_TEXT_MEMO: dict[int, dict] = {}
_SEASON_TEXT_MEMO_MAX = 4


def _season_candidate(row: Mapping[str, Any]) -> dict[str, Any] | None:
    sport = str(row.get("sport") or "").strip().lower()
    if not sport:
        return None
    home = str(row.get("home_team") or "").strip()
    away = str(row.get("away_team") or "").strip()
    side = str(row.get("side") or "").strip().lower()
    market = str(row.get("market") or "").strip()
    player = str(row.get("player_name") or "").strip()
    candidate: dict[str, Any] = {
        "sport_slug": sport,
        "matchup": f"{away} @ {home}" if home and away else "",
        "team": home if side == "home" else (away if side == "away" else ""),
        "event_id": row.get("event_id"),
        "market": market,
        "player_name": player,
        "league": row.get("league"),
    }
    if sport == "mlb" and player:
        projection = row.get("projection") if isinstance(row.get("projection"), Mapping) else {}
        player_id = str(projection.get("player_id") or "").strip()
        if player_id:
            candidate["player_id"] = player_id
    return candidate


def _season_memo_key(candidate: Mapping[str, Any]) -> tuple:
    sport = candidate.get("sport_slug")
    if sport == "mlb":
        role = "p" if str(candidate.get("market") or "").startswith(_PITCHER_MARKET_PREFIX) else "b"
        return (sport, "player", candidate.get("player_id"), role)
    if sport == "soccer":
        return (sport, "player", str(candidate.get("player_name") or "").lower(), candidate.get("league"))
    return (sport, "game", candidate.get("matchup"), candidate.get("team"), candidate.get("event_id"))


def row_season_text(row: Mapping[str, Any], context: Mapping[str, Any] | None = None) -> str | None:
    """The season-metric sentence for a Layer 2 row, or None. Never raises."""
    try:
        candidate = _season_candidate(row)
        if candidate is None:
            return None
        if candidate["sport_slug"] == "mlb" and not candidate.get("player_id"):
            return None  # MLB has player-level tables only; no id, nothing to read
        if candidate["sport_slug"] == "soccer" and not candidate.get("player_name"):
            return None  # soccer has player-level tables only
        memo: dict | None = None
        if isinstance(context, dict):
            memo = context.setdefault("season_text_memo", {})
        else:
            # No per-build context (the in-play overlay calls the card builder
            # bare, every tick): a small module memo, cleared when full and
            # keyed on the minute so a rebuilt table is read within ~60 s.
            import time as _time

            if len(_SEASON_TEXT_MEMO) > _SEASON_TEXT_MEMO_MAX:
                _SEASON_TEXT_MEMO.clear()
            memo = _SEASON_TEXT_MEMO.setdefault(int(_time.time() // 60), {})
            for stale in [k for k in _SEASON_TEXT_MEMO if k != int(_time.time() // 60)]:
                _SEASON_TEXT_MEMO.pop(stale, None)
        key = _season_memo_key(candidate)
        if memo is not None and key in memo:
            return memo[key]
        from syndicate.features import intelligence_season_evidence as season

        from syndicate.features.shared.prop_evidence.common import eastern_date

        commence = str(row.get("commence_time") or "").strip()
        try:
            today = _date.fromisoformat(eastern_date(commence) or "") if commence else _date.today()
        except ValueError:
            today = _date.today()
        text = season.season_evidence_text(season.candidate_season_signals(candidate, today)) or None
        if memo is not None:
            memo[key] = text
        return text
    except Exception as exc:  # noqa: BLE001 -- enrichment must never break the build
        print(f"[layer2_row_context] SEASON_TEXT_FAILED error={type(exc).__name__}: {exc}", flush=True)
        return None
