"""Hold in-play ENTRIES on a game a key player has left (lane live-player-exit-gate, user loan 2026-11-15).

The in-play entry loops (`inplay_entries_paper` / `inplay_entries_live`) price from BOOK CONSENSUS, not
from our model, so the live re-sim's `key_player_out` refusal never reached them: on 2026-11-15 they
could still enter NE @ DET after Drake Maye left it. This reads the SAME published snapshot the live
moneyline join reads (`live/<sport>_live_resim.json`, the keyvalue store), so an entry and a gameline
refuse on one source and cannot disagree about who is out.

Only a sport whose live producer PUBLISHES `playersOut` is checked (`PUBLISHING_SPORTS`); every other
sport answers `off`, which is exactly the behaviour before this module. A game the snapshot cannot speak
for (snapshot unreadable, game not in it, `playersOut` absent because the summary was unreadable)
answers `unknown` and is NOT refused: that is the pre-gate behaviour, recorded so it is countable.

Lag: the hold is as fresh as the producer's tick (NFL re-sim: 300 s) plus CACHE_S here.
"""

from __future__ import annotations

import time
from typing import Any, Callable, Mapping

from syndicate.features.shared.live_player_status import REASON_KEY_PLAYER_OUT, gate_enabled

# sport -> the live snapshot (under data_root()/live) whose games carry `playersOut`. Must equal
# `board_enrichment._LIVE_GAMELINE_SNAPSHOT_PATHS[sport]` (tested): a copy here keeps the fast exit
# thread from importing board_enrichment.
PUBLISHING_SPORTS: dict[str, str] = {"nfl": "nfl_live_resim.json", "ncaaf": "ncaaf_live_lens.json",
                                     "nba": "nba_live_resim.json", "wnba": "wnba_live_lens.json",
                                     "ncaab": "ncaab_live_resim.json", "wncaab": "wncaab_live_resim.json"}
CACHE_S = 30.0


def _read_snapshot(sport: str) -> Any:
    from syndicate.features.shared.refresh_state_store import data_root, read_json_file

    return read_json_file(data_root() / "live" / PUBLISHING_SPORTS[sport])


def _canon(sport: str, name: Any) -> str:
    from syndicate.features.shared.team_aliases import canonical_team

    text = str(name or "").strip()
    return (canonical_team(sport, text) or text).strip().lower() if text else ""


def _team_score(sport: str, entry_name: Any, snap_name: Any) -> int:
    """How well a book name (the entry's) names a snapshot team. 0 = not this team.

    NFL: the canonical names agree. College: the snapshot carries the SCHOOL ("Miami (OH)", "Ohio") and the
    book adds the mascot ("Miami (OH) RedHawks"), and `canonical_team` has no college vocabulary, so the
    book name must START with the school; the score is the school's length, so "Ohio State Buckeyes"
    prefers "Ohio State" over "Ohio" when both are live."""
    from syndicate.features.shared.live_player_status import normalize_name

    a, b = _canon(sport, entry_name), _canon(sport, snap_name)
    if not a or not b:
        return 0
    if a == b:
        return 1000
    na, nb = normalize_name(a), normalize_name(b)
    if na and nb and (na == nb or na.startswith(nb + " ")):
        return len(nb)
    return 0


class ExitHold:
    """`check(sport, home_team, away_team)` -> {"verdict": off|pass|fail|unknown, ...}. Never raises."""

    def __init__(self, *, read_fn: Callable[[str], Any] | None = None,
                 clock: Callable[[], float] = time.monotonic, cache_s: float = CACHE_S,
                 env: Mapping[str, str] | None = None) -> None:
        self.read_fn = read_fn or _read_snapshot
        self.clock = clock
        self.cache_s = cache_s
        self.env = env
        self._cache: dict[str, tuple[float, Any]] = {}

    def _snapshot(self, sport: str) -> Any:
        now = self.clock()
        hit = self._cache.get(sport)
        if hit is None or now - hit[0] >= self.cache_s:
            try:
                snap = self.read_fn(sport)
            except Exception as exc:  # noqa: BLE001 -- a read failure is `unknown`, never a crash in the exit thread
                snap = {"_read_error": f"{type(exc).__name__}: {exc}"[:160]}
            hit = (now, snap)
            self._cache[sport] = hit
        return hit[1]

    def check(self, sport: Any, home_team: Any, away_team: Any) -> dict[str, Any]:
        sport = str(sport or "").lower()
        if not gate_enabled(self.env) or sport not in PUBLISHING_SPORTS:
            return {"verdict": "off"}
        snap = self._snapshot(sport)
        if not isinstance(snap, Mapping) or not isinstance(snap.get("games"), list):
            return {"verdict": "unknown", "why": "snapshot_unreadable"}
        if not _canon(sport, home_team) or not _canon(sport, away_team):
            return {"verdict": "unknown", "why": "entry_has_no_teams"}
        best, best_score = None, 0
        for game in snap["games"]:
            if not isinstance(game, Mapping):
                continue
            g_home = game.get("home_name") or game.get("home_code")
            g_away = game.get("away_name") or game.get("away_code")
            # BOTH teams must name this game, in either order; the weaker side decides the score.
            score = max(min(_team_score(sport, home_team, g_home), _team_score(sport, away_team, g_away)),
                        min(_team_score(sport, home_team, g_away), _team_score(sport, away_team, g_home)))
            if score > best_score:
                best, best_score = game, score
        if best is not None:
            game = best
            out = game.get("playersOut")
            if not isinstance(out, list):
                return {"verdict": "unknown", "why": "game_exits_not_read", "snapshot_at": (snap.get("generated_at") or snap.get("generatedAt"))}
            key = [f"{p.get('team')}:{p.get('player')}:{p.get('reason')}" for p in out
                   if isinstance(p, Mapping) and p.get("key") and not p.get("modelled")]
            if key:
                return {"verdict": "fail", "reason": REASON_KEY_PLAYER_OUT, "players": key,
                        "snapshot_at": (snap.get("generated_at") or snap.get("generatedAt"))}
            return {"verdict": "pass", "snapshot_at": (snap.get("generated_at") or snap.get("generatedAt"))}
        return {"verdict": "unknown", "why": "game_not_in_snapshot", "snapshot_at": (snap.get("generated_at") or snap.get("generatedAt"))}
