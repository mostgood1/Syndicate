"""Recency + matchup sentences for board rows -- what the explanation LEADS with.

User 2026-10-08: "we need to get the advanced data metrics to primarily focus
on recency and matchups (hitter vs pitcher, hitter vs team, etc)". The evidence
already exists: `prop_evidence` (Ask's providers) computes each player's recent
form against the row's own line and his record against this opponent, plus the
opponent's profile. This module turns those FACTS into two short sentences:

    Recent form: over 12.5 in 4 of the last 10 (avg 10.6).
    Matchup: over in 4 of 4 vs ATL this season; ATL defensive rating 95.5.

Season-long metrics (`intelligence_season_evidence`) follow as context.

Costs are bounded the way `prop_evidence.common.build_read_cache` documents:
inside a board build every file is parsed once, and a row's sentence is memoised
per (sport, player, market, line, side, opponent) -- books quoting the same bet
share it. Never raises: a provider failure yields no sentence, not a broken card.
"""

from __future__ import annotations

from typing import Any, Mapping

_MAX_VALUES = 10


def _num(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return None if out != out else out


def _fmt(value: float | None, digits: int = 1) -> str:
    if value is None:
        return "-"
    return f"{value:.{digits}f}" if abs(value - round(value)) > 1e-9 else f"{value:.0f}"


def _rate_phrase(rate: Mapping[str, Any] | None, *, last: bool = False) -> str | None:
    """'over 12.5 in 4 of the last 10' (last=True) or 'over 12.5 in 4 of 4' from a hit_rate dict."""
    if not isinstance(rate, Mapping):
        return None
    games = int(_num(rate.get("games")) or 0)
    if games <= 0:
        return None
    hits = int(_num(rate.get("hits")) or 0)
    side = str(rate.get("side") or "").strip().lower()
    line = _num(rate.get("line"))
    of = f"the last {games}" if last else f"{games}"
    if side in {"over", "under"} and line is not None:
        return f"{side} {_fmt(line)} in {hits} of {of}"
    return f"{hits} of {of}"


def recent_form_text(facts: Mapping[str, Any] | None) -> str | None:
    if not isinstance(facts, Mapping) or not facts:
        return None
    phrase = _rate_phrase(facts.get("hit_rate"), last=True)
    values = [v for v in (_num(x) for x in (facts.get("values") or [])[:_MAX_VALUES]) if v is not None]
    avg = f" (avg {_fmt(sum(values) / len(values))})" if values else ""
    if phrase:
        text = f"Recent form: {phrase}{avg}"
    elif values:
        text = f"Recent form: avg {_fmt(sum(values) / len(values))} over the last {len(values)}"
    else:
        return None
    stale = _num(facts.get("stale_days"))
    if stale is not None and stale > 14:
        text += f" (newest game {int(stale)} days ago)"
    return text + "."


def _opponent_detail(facts: Mapping[str, Any]) -> str | None:
    opponent = str(facts.get("opponent") or "").strip()
    if not opponent:
        return None
    # basketball: opponent_advanced {def_rtg, pace, ...} (+ optional *_rank)
    adv = facts.get("opponent_advanced")
    if isinstance(adv, Mapping) and _num(adv.get("def_rtg")) is not None:
        rank = adv.get("def_rtg_rank")
        rank_text = f" ({rank})" if rank else ""
        pace = _num(adv.get("pace"))
        pace_text = f", pace {_fmt(pace)}" if pace is not None else ""
        return f"{opponent} defensive rating {_fmt(_num(adv.get('def_rtg')))}{rank_text}{pace_text}"
    # hockey: opponent_profile {xg {xga60, xgf60}, ...}
    prof = facts.get("opponent_profile")
    if isinstance(prof, Mapping):
        xg = prof.get("xg") if isinstance(prof.get("xg"), Mapping) else {}
        xga = _num(xg.get("xga60"))
        if xga is not None:
            return f"{opponent} allows {_fmt(xga, 2)} xG/60"
    # NCAAF: allowed_per_game + allowed_rank
    allowed = _num(facts.get("allowed_per_game"))
    if allowed is not None:
        rank = facts.get("allowed_rank")
        return f"{opponent} allows {_fmt(allowed)} per game" + (f", rank {rank}" if rank else "")
    # NFL: opponent_points_allowed [week, ...]
    pts = [v for v in (_num(x) for x in (facts.get("opponent_points_allowed") or [])) if v is not None]
    if pts:
        return f"{opponent} has allowed {_fmt(sum(pts) / len(pts))} points a game ({len(pts)} games)"
    # soccer: opponent_rating {xg_against_per_match, ...}
    rating = facts.get("opponent_rating")
    if isinstance(rating, Mapping) and _num(rating.get("xg_against_per_match")) is not None:
        return f"{opponent} concedes {_fmt(_num(rating.get('xg_against_per_match')), 2)} xG a match"
    return None


def matchup_text(facts: Mapping[str, Any] | None) -> str | None:
    if not isinstance(facts, Mapping) or not facts:
        return None
    parts: list[str] = []
    vs = facts.get("vs_opponent")
    opponent = str(facts.get("opponent") or "").strip()
    if isinstance(vs, Mapping):
        phrase = _rate_phrase(vs.get("hit_rate"))
        if phrase and opponent:
            parts.append(f"{phrase} vs {opponent}")
    detail = _opponent_detail(facts)
    if detail:
        parts.append(detail)
    return ("Matchup: " + "; ".join(parts) + ".") if parts else None


def _memo_key(row: Mapping[str, Any]) -> tuple:
    return (
        str(row.get("sport") or "").lower(),
        str(row.get("player_name") or "").lower(),
        str(row.get("market") or ""),
        str(row.get("line")),
        str(row.get("side") or "").lower(),
        str(row.get("home_team") or ""),
        str(row.get("away_team") or ""),
    )


def prop_recent_matchup_text(row: Mapping[str, Any], *, selected_date: str, memo: dict | None = None) -> str | None:
    """Recency + matchup sentences for one prop row, or None. Never raises."""
    if str(row.get("kind") or "").lower() != "prop" or not row.get("player_name"):
        return None
    key = _memo_key(row)
    if memo is not None and key in memo:
        return memo[key]
    text = None
    try:
        from syndicate.features.shared.prop_evidence import build_prop_evidence
        from syndicate.features.shared.prop_evidence.contract import Layer

        evidence = build_prop_evidence(dict(row), selected_date=selected_date)
        if evidence is not None:
            recent = evidence.layers.get(Layer.RECENT_FORM)
            match = evidence.layers.get(Layer.MATCHUP)
            pieces = [
                recent_form_text(recent.facts if recent is not None else None),
                matchup_text(match.facts if match is not None else None),
            ]
            text = " ".join(piece for piece in pieces if piece) or None
    except Exception as exc:  # noqa: BLE001 -- an explanation must never break a card
        print(f"[recent_matchup] FAILED sport={key[0]} error={type(exc).__name__}: {exc}", flush=True)
        text = None
    if memo is not None:
        memo[key] = text
    return text
