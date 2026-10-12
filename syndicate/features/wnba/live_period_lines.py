"""WNBA live OddsAPI lines for one matchup: period totals/spreads and live game lines (Syndicate-owned).

Lane wnba-live-period-lines-native (2026-10-12). Ported from vendor/wnba_betting_repo/app.py
(sha256 1d62ccb6c60543d6...): ``_live_oddsapi_period_totals_for_game`` and its team-code closure (``_canonical_team_tri``,
``_get_tricode``, ``_load_team_maps``, ``_espn_to_tri``) plus the capped TTL cache it used. The function body is the
vendored text. ``scripts/refresh_wnba_oddsapi_props.py`` used to import the whole 46,820-line vendored Flask app on
every live-snapshot export to reach it.

Two edits, both in ``_load_team_maps``:
  * the merge of nba_api's NBA team list is dropped. It only matters for an NBA FULL team name, which the
    basketball_wnba feed never returns;
  * the read of web/assets/teams_wnba.json is dropped. That file does not exist in the vendored checkout.
``LEAGUE`` is the vendored WNBA league config by value (``basketball_engine.orchestrator.league_config``).

PARITY: tests/test_wnba_live_period_lines.py runs the vendored function (AST-extracted from the vendored app, no
Flask import) and this one on the same mocked OddsAPI responses, every branch, and requires identical output.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from typing import Any, Optional

import numpy as np
import requests

from syndicate.features.basketball_engine.orchestrator.league_config import LEAGUE


def _env_int_clamped(name: str, default: int, lo: int, hi: int) -> int:
    try:
        raw = str(os.environ.get(name, str(default))).strip()
        v = int(float(raw))
        return int(max(lo, min(hi, v)))
    except Exception:
        return int(max(lo, min(hi, int(default))))


class _CappedDict(dict):
    """Insertion-ordered dict with a max size controlled by an env var.

    Why: CPython's allocator often doesn't return freed memory to the OS quickly.
    If we let caches grow unbounded (even with TTL checks), RSS can climb until
    Render kills the process on small instances.
    """

    def __init__(self, *, max_items_env: str, default_max: int, lo: int = 0, hi: int = 2000):
        super().__init__()
        self._max_items_env = str(max_items_env)
        self._default_max = int(default_max)
        self._lo = int(lo)
        self._hi = int(hi)

    def _max_items(self) -> int:
        return _env_int_clamped(self._max_items_env, self._default_max, self._lo, self._hi)

    def _prune(self) -> None:
        try:
            max_items = int(self._max_items())
            if max_items <= 0:
                super().clear()
                return
            while len(self) > max_items:
                try:
                    super().pop(next(iter(self)))
                except Exception:
                    break
        except Exception:
            pass

    def __setitem__(self, key: Any, value: Any) -> None:
        super().__setitem__(key, value)
        self._prune()

    def update(self, *args: Any, **kwargs: Any) -> None:  # type: ignore[override]
        super().update(*args, **kwargs)
        self._prune()


_live_oddsapi_period_cache: dict[str, tuple[float, dict[str, Any]]] = _CappedDict(
    max_items_env="LIVE_ODDSAPI_PERIOD_CACHE_MAX_ITEMS",
    default_max=16,
    lo=0,
    hi=500,
)

_team_name_to_abbr: Optional[dict[str, str]] = None
_team_abbr_to_id: Optional[dict[str, int]] = None


def _load_team_maps() -> dict[str, str]:
    global _team_name_to_abbr, _team_abbr_to_id
    if _team_name_to_abbr is not None:
        return _team_name_to_abbr
    mapping: dict[str, str] = {}
    abbr_to_id: dict[str, int] = {}
    # Syndicate port: the vendored function first merged nba_api's NBA team list here. It can only matter for an
    # NBA FULL team name (every abbreviation falls through to the same upper-cased value), which OddsAPI's
    # basketball_wnba feed never returns, so the dependency is dropped (tests/test_wnba_live_period_lines.py pins it).
    # Bug found live 2026-08-01: this WNBA full_name -> abbreviation list used
    # to live only inside the `except` branch above, so it silently never ran
    # whenever the nba_api import succeeded (the normal case) -- nba_api's
    # static teams list is NBA-only, so `mapping` ended up with zero WNBA
    # full-team-name entries beyond the 5 explicitly aliased in
    # _get_tricode() (Sparks/Aces/Valkyries/Tempo/Fire). Confirmed live:
    # _canonical_team_tri("Indiana Fever") fell through to the raw uppercased
    # string "INDIANA FEVER" instead of "IND", so _live_oddsapi_period_totals_
    # for_game's own event-matching against real OddsAPI events silently
    # failed for every established (non-renamed) WNBA team, even though the
    # correct event was right there in the response. The teams_wnba.json
    # fallback below can't rescue this either -- that file doesn't exist in
    # this vendored checkout. Always merge this list in (not gated on the
    # nba_api call's outcome) so every WNBA team resolves regardless.
    wnba_built_in = [
        ("Atlanta Dream", "ATL"),
        ("Chicago Sky", "CHI"),
        ("Connecticut Sun", "CON"),
        ("Dallas Wings", "DAL"),
        ("Golden State Valkyries", "GSV"),
        ("Indiana Fever", "IND"),
        ("Los Angeles Sparks", "LAS"),
        ("LA", "LAS"),
        ("LAS", "LAS"),
        ("Las Vegas Aces", "LVA"),
        ("LVA", "LVA"),
        ("Minnesota Lynx", "MIN"),
        ("New York Liberty", "NYL"),
        ("Phoenix Mercury", "PHX"),
        ("Portland Fire", "POR"),
        ("Seattle Storm", "SEA"),
        ("Toronto Tempo", "TOR"),
        ("Washington Mystics", "WSH"),
    ]
    for full, abbr in wnba_built_in:
        mapping.setdefault(str(full).strip().lower(), str(abbr).strip().upper())
        mapping.setdefault(str(abbr).strip().lower(), str(abbr).strip().upper())
    # Syndicate port: the vendored function then read vendor/wnba_betting_repo/web/assets/teams_wnba.json, which does
    # not exist in the vendored checkout (its own comment above says so). Dropped.
    _team_name_to_abbr = mapping
    _team_abbr_to_id = abbr_to_id
    return mapping


def _get_tricode(team: str | None) -> str | None:
    if not team:
        return None
    raw = str(team).strip()
    key = raw.lower()
    explicit_aliases = {
        "la": "LAS",
        "las": "LAS",
        "los angeles sparks": "LAS",
        "lva": "LVA",
        "las vegas aces": "LVA",
        "gsv": "GSV",
        "golden state valkyries": "GSV",
        "toronto tempo": "TOR",
        "portland fire": "POR",
    }
    if key in explicit_aliases:
        return explicit_aliases[key]
    m = _load_team_maps()
    abbr = m.get(key)
    return (abbr or raw.upper() or None)


def _canonical_team_tri(team: Any) -> str:
    tri = str(_get_tricode(str(team or "")) or team or "").strip().upper()
    return _espn_to_tri(tri) if tri else ""


def _espn_to_tri(abbr: str) -> str:
    s = str(abbr or '').upper().strip()
    is_wnba = "wnba" in str(getattr(LEAGUE, 'espn_sport_path', '') or '').lower()
    if is_wnba:
        fix = {
            'GS': 'GSV',
            'GSW': 'GSV',
            'LAS': 'LA',
            'LV': 'LVA',
            'NY': 'NYL',
            'NYK': 'NYL',
            'WAS': 'WSH',
        }
    else:
        fix = {
            'GS': 'GSW',
            'NO': 'NOP',
            'NY': 'NYK',
            'BRK': 'BKN',
            'BK': 'BKN',
            'PHO': 'PHX',
            # ESPN sometimes uses legacy or short abbreviations that don't match league tricodes
            'SA': 'SAS',
            'WSH': 'WAS',
            'UTAH': 'UTA',
        }
    return fix.get(s, s)


def _live_oddsapi_period_totals_for_game(date_str: str, home_tri: str, away_tri: str) -> dict[str, Any]:
        """Best-effort OddsAPI lines for a matchup (fast path).

        Returns:
            {
                source,
                event_id,
                swapped,
                period_totals: {h1, q1..q4},
                period_spreads: {h1, q1..q4},
                game_lines: {total, home_spread, away_spread, home_ml, away_ml},
                market_keys: {...}
            }
        """
        api_key = (os.environ.get("ODDS_API_KEY") or os.environ.get("THE_ODDS_API_KEY") or "").strip()
        if not api_key:
            return {}

        h = _canonical_team_tri(home_tri)
        a = _canonical_team_tri(away_tri)
        if not h or not a:
            return {}

        cache_key = f"{date_str}:{h}:{a}"
        now = time.time()
        ent = _live_oddsapi_period_cache.get(cache_key)
        if ent and (now - ent[0] < 20):
            return ent[1]

        # Fast direct HTTP calls with short timeouts (avoid blocking UI/pollers).
        base = "https://api.the-odds-api.com"
        sport = LEAGUE.odds_api_sport_key
        headers = {"Accept": "application/json", "User-Agent": getattr(LEAGUE, "user_agent_product", "wnba-betting/1.0")}
        timeout_s = 3

        # 1) List events and match by team tricodes.
        # Important: OddsAPI can return multiple events for the same teams over a season.
        # Choose the best match closest to now to avoid pulling a future/past instance.
        event_id = None
        swapped = False
        try:
            r = requests.get(f"{base}/v4/sports/{sport}/events", params={"apiKey": api_key}, headers=headers, timeout=timeout_s)
            evs = r.json() if r.ok else []
            events = evs if isinstance(evs, list) else []
        except Exception:
            events = []

        def _parse_commence_time_utc_naive(x: Any) -> datetime | None:
            try:
                s = str(x or "").strip()
                if not s:
                    return None
                # OddsAPI commonly returns ISO strings like '2026-02-21T03:10:00Z'
                dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
                if dt.tzinfo is not None:
                    dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
                return dt
            except Exception:
                return None

        best: tuple[float, Any, bool] | None = None  # (abs_seconds_from_now, event_id, swapped)
        now_utc = datetime.utcnow()
        for ev in events:
            try:
                if not isinstance(ev, dict):
                    continue
                eh = _canonical_team_tri(ev.get("home_team"))
                ea = _canonical_team_tri(ev.get("away_team"))
                if not ((eh == h and ea == a) or (eh == a and ea == h)):
                    continue

                dt = _parse_commence_time_utc_naive(ev.get("commence_time"))
                if dt is None:
                    # Still allow selection, but strongly de-prioritize unknown timestamps.
                    abs_s = 1e18
                else:
                    abs_s = float(abs((dt - now_utc).total_seconds()))

                sw = bool(eh == a and ea == h)
                if best is None or abs_s < best[0]:
                    best = (abs_s, ev.get("id"), sw)
            except Exception:
                continue

        if best is not None:
            event_id = best[1]
            swapped = best[2]

        if not event_id:
            # Diagnostic added 2026-08-01: this early return happens silently
            # (before PERIOD_MARKET_DISCOVERY_DIAG below), so a caller could
            # never tell "no live game right now" apart from "a real live
            # game whose OddsAPI event just isn't matching." Confirmed live:
            # this branch fired all night for a genuinely in-progress WNBA
            # game (IND@POR) while game-level lines (fetched through a
            # separate, already-working odds path) were fine -- so this
            # function's own /v4/sports/{sport}/events lookup+match is the
            # suspect, not a genuine absence of the game from OddsAPI.
            print(
                f"[wnba_live_lens] PERIOD_MARKET_EVENT_MATCH_FAILED matchup={h}@{a} "
                f"events_returned={len(events)} "
                f"sample_events={[(ev.get('home_team'), ev.get('away_team'), ev.get('commence_time')) for ev in events[:8] if isinstance(ev, dict)]}",
                flush=True,
            )
            out = {}
            _live_oddsapi_period_cache[cache_key] = (now, out)
            return out

        # 2) Discover market keys.
        keys: set[str] = set()
        discover_status = None
        discover_error = None
        try:
            r = requests.get(
                f"{base}/v4/sports/{sport}/events/{event_id}/markets",
                params={"apiKey": api_key, "regions": "us"},
                headers=headers,
                timeout=timeout_s,
            )
            discover_status = r.status_code
            jd = r.json() if r.ok else None
            if isinstance(jd, dict):
                # OddsAPI v4 shape: {id, ... , bookmakers:[{markets:[{key,...},...]}, ...]}
                bks = jd.get("bookmakers") or []
                if isinstance(bks, list):
                    for bk in bks:
                        if not isinstance(bk, dict):
                            continue
                        markets = bk.get("markets") or []
                        if not isinstance(markets, list):
                            continue
                        for m in markets:
                            if isinstance(m, dict) and m.get("key"):
                                keys.add(str(m.get("key")))
            elif isinstance(jd, list):
                # Some variants may return a flat list of market metadata
                for m in jd:
                    if isinstance(m, dict) and m.get("key"):
                        keys.add(str(m.get("key")))
        except Exception as exc:
            discover_error = f"{type(exc).__name__}: {exc}"
            keys = set()

        # #125 follow-up, 2026-07-28: user asked whether the live period
        # total/spread line "may be named different than expected" rather
        # than genuinely absent -- this settles it directly against a real
        # OddsAPI response instead of guessing. Bounded to once per (date,
        # matchup) per 20s cache window (this function's own cache_key/TTL
        # above), not a hot loop.
        print(
            f"[wnba_live_lens] PERIOD_MARKET_DISCOVERY_DIAG matchup={h}@{a} event_id={event_id} "
            f"discover_status={discover_status} discover_error={discover_error} discovered_keys={sorted(keys)}",
            flush=True,
        )

        # Candidate keys (OddsAPI period keys commonly use suffixes like _q1 and _h1)
        # Found live 2026-08-01: "h2" (second half) had no entry here at all,
        # even though books actively quote totals_h2/spreads_h2 once the
        # first half ends -- confirmed via a real discovered_keys list for a
        # live 4th-quarter game that included both. Every other period
        # (h1/q1-q4) had a slot; h2 was simply missing.
        want: dict[str, list[str]] = {
            "game_total": ["totals"],
            "game_spreads": ["spreads"],
            "game_h2h": ["h2h"],
            "h1": ["totals_h1", "totals_1h", "totals_1st_half", "totals_first_half"],
            "h1_spread": ["spreads_h1", "spreads_1h", "spreads_1st_half", "spreads_first_half"],
            "h2": ["totals_h2", "totals_2h", "totals_2nd_half", "totals_second_half"],
            "h2_spread": ["spreads_h2", "spreads_2h", "spreads_2nd_half", "spreads_second_half"],
            "q1": ["totals_q1", "totals_1q", "totals_1st_quarter", "totals_first_quarter"],
            "q1_spread": ["spreads_q1", "spreads_1q", "spreads_1st_quarter", "spreads_first_quarter"],
            "q2": ["totals_q2", "totals_2q", "totals_2nd_quarter", "totals_second_quarter"],
            "q2_spread": ["spreads_q2", "spreads_2q", "spreads_2nd_quarter", "spreads_second_quarter"],
            "q3": ["totals_q3", "totals_3q", "totals_3rd_quarter", "totals_third_quarter"],
            "q3_spread": ["spreads_q3", "spreads_3q", "spreads_3rd_quarter", "spreads_third_quarter"],
            "q4": ["totals_q4", "totals_4q", "totals_4th_quarter", "totals_fourth_quarter"],
            "q4_spread": ["spreads_q4", "spreads_4q", "spreads_4th_quarter", "spreads_fourth_quarter"],
        }

        picked: dict[str, str] = {}
        for label, cands in want.items():
            for k in cands:
                if k in keys:
                    picked[label] = k
                    break

        req_markets = sorted(set(picked.values()))
        if not req_markets:
            out = {
                "source": "oddsapi_fast",
                "event_id": str(event_id),
                "swapped": bool(swapped),
                "period_totals": {},
                "period_spreads": {},
                "game_lines": {},
                "market_keys": {},
            }
            _live_oddsapi_period_cache[cache_key] = (now, out)
            return out

        # 3) Fetch odds for the picked markets and extract the points.
        period_totals: dict[str, float] = {}
        period_spreads: dict[str, float] = {}
        game_lines: dict[str, float] = {}
        odds_fetch_status = None
        try:
            r = requests.get(
                f"{base}/v4/sports/{sport}/events/{event_id}/odds",
                params={
                    "apiKey": api_key,
                    "regions": "us",
                    "markets": ",".join(req_markets),
                    "oddsFormat": "american",
                },
                headers=headers,
                timeout=timeout_s,
            )
            odds_fetch_status = r.status_code
            obj = r.json() if r.ok else None
        except Exception:
            obj = None

        mk_to_label = {mkey: label for label, mkey in picked.items()}
        # Aggregate across bookmakers to avoid arbitrary "first book wins" volatility.
        period_pts: dict[str, list[float]] = {k: [] for k in ["h1", "h2", "q1", "q2", "q3", "q4"]}
        period_home_spreads: dict[str, list[float]] = {k: [] for k in ["h1", "h2", "q1", "q2", "q3", "q4"]}
        game_total_pts: list[float] = []
        home_spreads: list[float] = []
        away_spreads: list[float] = []
        home_mls: list[float] = []
        away_mls: list[float] = []

        if isinstance(obj, dict):
            bks = obj.get("bookmakers") or []
            if isinstance(bks, list):
                for bk in bks:
                    if not isinstance(bk, dict):
                        continue
                    markets = bk.get("markets") or []
                    if not isinstance(markets, list):
                        continue
                    for m in markets:
                        if not isinstance(m, dict):
                            continue
                        mkey = str(m.get("key") or "")
                        label = mk_to_label.get(mkey)
                        if not label:
                            continue
                        outs = m.get("outcomes") or []
                        if not isinstance(outs, list):
                            continue

                        if label in {"h1", "h2", "q1", "q2", "q3", "q4"}:
                            for oc in outs:
                                if not isinstance(oc, dict):
                                    continue
                                pt = oc.get("point")
                                try:
                                    v = float(pt)
                                    if np.isfinite(v):
                                        period_pts[label].append(float(v))
                                except Exception:
                                    continue

                        if label in {"h1_spread", "h2_spread", "q1_spread", "q2_spread", "q3_spread", "q4_spread"}:
                            period_label = str(label).replace("_spread", "")
                            for oc in outs:
                                if not isinstance(oc, dict):
                                    continue
                                nm = str(oc.get("name") or "")
                                tri = _canonical_team_tri(nm)
                                pt = oc.get("point")
                                try:
                                    v = float(pt)
                                    if not np.isfinite(v):
                                        continue
                                except Exception:
                                    continue
                                if tri == h and period_label in period_home_spreads:
                                    period_home_spreads[period_label].append(float(v))

                        # Full-game markets
                        if label == "game_total":
                            for oc in outs:
                                if not isinstance(oc, dict):
                                    continue
                                pt = oc.get("point")
                                try:
                                    v = float(pt)
                                    if np.isfinite(v):
                                        game_total_pts.append(float(v))
                                except Exception:
                                    continue

                        if label == "game_spreads":
                            for oc in outs:
                                if not isinstance(oc, dict):
                                    continue
                                nm = str(oc.get("name") or "")
                                tri = _canonical_team_tri(nm)
                                pt = oc.get("point")
                                try:
                                    v = float(pt)
                                    if not np.isfinite(v):
                                        continue
                                except Exception:
                                    continue
                                if tri == h:
                                    home_spreads.append(float(v))
                                if tri == a:
                                    away_spreads.append(float(v))

                        if label == "game_h2h":
                            for oc in outs:
                                if not isinstance(oc, dict):
                                    continue
                                nm = str(oc.get("name") or "")
                                tri = _canonical_team_tri(nm)
                                pr = oc.get("price")
                                try:
                                    v = float(pr)
                                    if not np.isfinite(v):
                                        continue
                                except Exception:
                                    continue
                                if tri == h:
                                    home_mls.append(float(v))
                                if tri == a:
                                    away_mls.append(float(v))

        # Reduce aggregated values to a single best-effort line.
        try:
            for label, pts in period_pts.items():
                if pts:
                    period_totals[label] = float(np.median(np.asarray(pts, dtype=float)))
        except Exception:
            pass
        try:
            for label, spreads in period_home_spreads.items():
                if spreads:
                    period_spreads[label] = float(np.median(np.asarray(spreads, dtype=float)))
        except Exception:
            pass
        try:
            if game_total_pts:
                game_lines["total"] = float(np.median(np.asarray(game_total_pts, dtype=float)))
        except Exception:
            pass
        try:
            if home_spreads:
                game_lines["home_spread"] = float(np.median(np.asarray(home_spreads, dtype=float)))
            if away_spreads:
                game_lines["away_spread"] = float(np.median(np.asarray(away_spreads, dtype=float)))
        except Exception:
            pass
        try:
            if home_mls:
                game_lines["home_ml"] = float(np.median(np.asarray(home_mls, dtype=float)))
            if away_mls:
                game_lines["away_ml"] = float(np.median(np.asarray(away_mls, dtype=float)))
        except Exception:
            pass

        if req_markets and not period_totals and not period_spreads:
            # Diagnostic added 2026-08-01: discovery can find real period
            # market keys (req_markets non-empty) yet the actual /odds fetch
            # still yield nothing -- this print distinguishes a fetch-level
            # failure (non-200/exception) from a response that came back
            # fine but had no bookmaker actually offering the requested
            # markets at fetch time (can legitimately happen if a book pulls
            # a market between the discovery call and this one).
            bookmaker_count = len(obj.get("bookmakers") or []) if isinstance(obj, dict) else None
            print(
                f"[wnba_live_lens] PERIOD_MARKET_ODDS_FETCH_EMPTY matchup={h}@{a} event_id={event_id} "
                f"odds_fetch_status={odds_fetch_status} req_markets={req_markets} bookmaker_count={bookmaker_count}",
                flush=True,
            )

        out = {
            "source": "oddsapi_fast",
            "event_id": str(event_id),
            "swapped": bool(swapped),
            "period_totals": period_totals,
            "period_spreads": period_spreads,
            "game_lines": game_lines,
            "market_keys": picked,
        }
        _live_oddsapi_period_cache[cache_key] = (now, out)
        return out


# Public name for Syndicate callers.
live_oddsapi_period_totals_for_game = _live_oddsapi_period_totals_for_game
