"""Resolve a MEASURED same-game correlation out of the MLB sim's joint artifact.

`#621` Phase 4, consumer side of the producer. This module builds the
`measured_lookup` that `correlation_engine.compute_correlation` already accepts
(landed `1bbcc246`): a callable `(candidate_a, candidate_b) -> float | None`
whose answer REPLACES the heuristic flag-sum and stamps
`correlation_basis="measured_joint"`.

It is a separate module on purpose. `correlation_engine.py` is claimed by
another lane, and more importantly the seam is better as an INJECTION than as an
import: the engine stays ignorant of MLB, of artifact paths, and of disk, and a
resolver that cannot find its artifact returns `None` and the board keeps
working on the heuristic exactly as before.

--------------------------------------------------------------------------
WHAT `None` MEANS, AND WHY IT IS NOT A FAILURE
--------------------------------------------------------------------------

`None` is the NORMAL answer and the safe one. It is returned for a cross-game
pair, a non-MLB pair, a market with no joint dimension, a player who was not in
the sim, a date with no artifact, and -- importantly -- a pair whose measured
correlation is UNDEFINED because one of its columns was constant across all
1,000 sims. Every one of those falls back to the heuristic.

What must NEVER happen is the inverse: returning `0.0` where the answer is
unknown. `0.0` is a legitimate measurement meaning "these legs are independent",
and it is a LARGE claim -- it would tell `bankroll_manager` to size two legs as
if they were unrelated. Mapping "unknown" onto it is the permissive-default
failure the ledger names directly. So every path that cannot measure returns
`None`, and `reasons()` records which path it took.

--------------------------------------------------------------------------
SUBSTRATE
--------------------------------------------------------------------------

This reads artifacts through `syndicate.features.mlb.sources`, the same
resolver the board uses, so it sees whatever root the process is pointed at --
Render's mounted disk on the worker, a mirror locally. `data/daily/sims/<date>/
sim_*.json` is ALREADY in `HOT_ARTIFACT_PATTERNS`
(`artifact_publisher.py:586,596`), so the joint rides along on a path that is
already published and already exportable, and no allowlist change and no web
deploy are needed for it to be readable.
"""
from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Optional, Tuple

from syndicate.features.shared.market_keys import canonical_market_key

#: Canonical market key -> the joint dimension suffix the producer emits.
#: Keyed on the CANONICAL form so this table never becomes a second, drifting
#: alias list -- `canonical_market_key` owns the aliases ("hr", "total bases",
#: "batter_total_bases", ...) and this owns only the final hop.
CANONICAL_MARKET_TO_JOINT: Dict[str, str] = {
    "batter_hits": "hits",
    "batter_home_runs": "home_runs",
    "batter_total_bases": "total_bases",
    "batter_rbis": "rbi",
}

_WORD = re.compile(r"[^a-z0-9]+")

#: Defaults matching the producer's. Every read prefers the value the ARTIFACT
#: carries (`scale`, `undefined`) and falls back to these only when it is
#: absent, so an older artifact still reads correctly and a future producer can
#: change the packing without stranding this reader.
_DEFAULT_SCALE = 1000
_DEFAULT_UNDEFINED = -32768


def _triangle_index(i: int, j: int) -> int:
    """Position of pair (i, j) in the producer's packed lower triangle.

    DELIBERATELY DUPLICATED from `sim_engine.joint_outcomes.triangle_index`, and
    the duplication is the lesser evil. `syndicate/` cannot import `sim_engine`:
    nothing under `syndicate/` does, only `scripts/` that bootstrap `sys.path`
    onto the vendor root first. An import here would raise `ImportError`, be
    swallowed by `compute_correlation`'s own try/except around `measured_lookup`,
    and silently serve the heuristic forever -- a fix that is present, tested,
    and unreachable, which is the exact failure `model_engine_standard` §4.3
    exists to prevent.

    The drift risk that duplication creates is closed by a TEST rather than by
    hope: `test_resolver_agrees_with_the_producers_own_reader` round-trips a
    real `JointAccumulator` payload through both readers and asserts every pair
    matches. That is a stronger guarantee than a shared import, because it
    exercises the published artifact CONTRACT, which is what actually crosses
    between the two processes.
    """
    if i == j:
        raise ValueError("a dimension has no off-diagonal entry with itself")
    if i < j:
        i, j = j, i
    return i * (i - 1) // 2 + j


def _lookup_pair(
    joint: Dict[str, Any],
    label_pos: Dict[str, int],
    label_a: str,
    label_b: str,
) -> Optional[float]:
    """One pair out of a published `sim["joint"]`. None when undefined."""
    i = label_pos.get(str(label_a))
    j = label_pos.get(str(label_b))
    if i is None or j is None or i == j:
        return None
    triangle = joint.get("corr_lower") or []
    pos = _triangle_index(i, j)
    if pos < 0 or pos >= len(triangle):
        return None
    raw = triangle[pos]
    if raw is None:
        return None
    undefined = joint.get("undefined", _DEFAULT_UNDEFINED)
    try:
        if int(raw) == int(undefined):
            return None
    except (TypeError, ValueError):
        return None
    scale = float(joint.get("scale") or _DEFAULT_SCALE)
    if scale == 0.0:
        return None
    return float(raw) / scale


def _norm_name(value: Any) -> str:
    """Fold a player name for matching: accents, punctuation, suffixes, case."""
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = _WORD.sub(" ", text.lower()).strip()
    parts = [p for p in text.split() if p not in {"jr", "sr", "ii", "iii", "iv"}]
    return " ".join(parts)


class JointCorrelationIndex:
    """Every game's joint for one date, indexed for candidate lookup.

    Built ONCE per board build and reused across every pair. `compute_correlation`
    is called O(n^2) over the candidate pool -- `attach_board_correlation_flags`
    walks every pair -- so a resolver that touched disk per call would turn a
    board build into thousands of file reads. Nothing here reads disk after
    construction.
    """

    def __init__(self) -> None:
        self._joint_by_pk: Dict[int, Dict[str, Any]] = {}
        self._label_pos: Dict[int, Dict[str, int]] = {}
        #: (game_pk, normalized name) and (game_pk, player_id) -> player_id
        self._player_by_name: Dict[Tuple[int, str], int] = {}
        self._ambiguous_names: set[Tuple[int, str]] = set()
        self._pk_by_player: Dict[int, int] = {}
        self._pk_by_name: Dict[str, int] = {}
        self._ambiguous_global_names: set[str] = set()
        self.reasons: Dict[str, int] = {}
        self.date: str = ""

    # --- construction -------------------------------------------------------

    def add_game(self, game_pk: int, joint: Dict[str, Any]) -> None:
        if not isinstance(joint, dict) or not joint.get("labels"):
            self._bump("joint_absent_or_empty")
            return
        pk = int(game_pk)
        self._joint_by_pk[pk] = joint
        self._label_pos[pk] = {str(label): i for i, label in enumerate(joint.get("labels") or [])}
        for pid_raw, row in (joint.get("players") or {}).items():
            try:
                pid = int(pid_raw)
            except (TypeError, ValueError):
                continue
            self._pk_by_player[pid] = pk
            name = _norm_name((row or {}).get("name"))
            if not name:
                continue
            key = (pk, name)
            if key in self._player_by_name and self._player_by_name[key] != pid:
                # Two players with the same folded name in ONE game. Refusing
                # is the only safe move: guessing would attach one player's
                # measured correlation to another's bet.
                self._ambiguous_names.add(key)
            else:
                self._player_by_name[key] = pid
            if name in self._pk_by_name and self._pk_by_name[name] != pk:
                self._ambiguous_global_names.add(name)
            else:
                self._pk_by_name[name] = pk

    @classmethod
    def for_date(cls, date_str: str, *, game_pks: Optional[Iterable[int]] = None) -> "JointCorrelationIndex":
        """Load every sim artifact for a date and index its `sim.joint`."""
        index = cls()
        index.date = str(date_str or "")
        try:
            from syndicate.features.mlb.ladders_build import discover_game_pks
            from syndicate.features.mlb.sources import daily_sim_artifact_path
        except Exception:
            index._bump("mlb_sources_unavailable")
            return index

        pks = list(game_pks) if game_pks is not None else discover_game_pks(index.date)
        if not pks:
            index._bump("no_sims_for_date")
            return index
        for pk in pks:
            path = daily_sim_artifact_path(index.date, int(pk))
            if not path:
                index._bump("sim_artifact_missing")
                continue
            try:
                record = json.loads(Path(path).read_text(encoding="utf-8"))
            except Exception:
                index._bump("sim_artifact_unreadable")
                continue
            joint = ((record or {}).get("sim") or {}).get("joint")
            if not joint:
                # The expected state until the producer ships, and after it
                # ships for any game simmed by an older build. Counted, so
                # "the resolver is inert" is a NUMBER rather than a silence.
                index._bump("joint_field_absent")
                continue
            index.add_game(int(pk), joint)
        return index

    # --- lookup -------------------------------------------------------------

    def _bump(self, reason: str) -> None:
        self.reasons[reason] = self.reasons.get(reason, 0) + 1

    @property
    def games_with_joint(self) -> int:
        return len(self._joint_by_pk)

    def _resolve_candidate(self, candidate: Dict[str, Any]) -> Optional[Tuple[int, str]]:
        """Candidate -> (game_pk, joint label), or None."""
        market = canonical_market_key(
            "mlb",
            candidate.get("market_key"),
            candidate.get("market"),
            candidate.get("stat"),
            candidate.get("metric"),
            candidate.get("prop"),
        )
        joint_market = CANONICAL_MARKET_TO_JOINT.get(str(market or ""))
        if not joint_market:
            self._bump("market_has_no_joint_dimension")
            return None

        pid = None
        for field in ("player_id", "subject_id", "mlbam_id", "playerId"):
            raw = candidate.get(field)
            try:
                if raw is not None and int(raw) > 0:
                    pid = int(raw)
                    break
            except (TypeError, ValueError):
                continue

        pk = None
        for field in ("game_pk", "gamePk", "game_id", "event_id"):
            raw = candidate.get(field)
            try:
                if raw is not None and int(raw) > 0 and int(raw) in self._joint_by_pk:
                    pk = int(raw)
                    break
            except (TypeError, ValueError):
                continue

        if pid is not None and pk is None:
            pk = self._pk_by_player.get(pid)

        name = _norm_name(
            candidate.get("subject_key")
            or candidate.get("player")
            or candidate.get("player_name")
            or _subject_from_display_name(candidate.get("name"))
        )
        if pid is None and name:
            if pk is not None:
                if (pk, name) in self._ambiguous_names:
                    self._bump("ambiguous_name_in_game")
                    return None
                pid = self._player_by_name.get((pk, name))
            else:
                if name in self._ambiguous_global_names:
                    self._bump("ambiguous_name_across_slate")
                    return None
                pk = self._pk_by_name.get(name)
                if pk is not None:
                    pid = self._player_by_name.get((pk, name))

        if pk is None or pid is None:
            self._bump("player_not_in_any_sim")
            return None

        label = f"batter|{int(pid)}|{joint_market}"
        if label not in self._label_pos.get(pk, {}):
            self._bump("label_absent_from_joint")
            return None
        return pk, label

    def measured(self, candidate_a: Dict[str, Any], candidate_b: Dict[str, Any]) -> Optional[float]:
        """The `measured_lookup` contract: a coefficient, or None.

        NEVER returns 0.0 for "unknown" -- see the module docstring. A pair whose
        measured correlation is genuinely 0.000 does return 0.0, and that is a
        measurement worth having: it says the heuristic's `same_game` 0.25 plus
        `same_team` 0.14 was inventing a dependence that the sim does not show.
        """
        if not self._joint_by_pk:
            return None
        left = self._resolve_candidate(candidate_a or {})
        if left is None:
            return None
        right = self._resolve_candidate(candidate_b or {})
        if right is None:
            return None
        pk_a, label_a = left
        pk_b, label_b = right
        if pk_a != pk_b:
            # Cross-game is not measurable from a per-game joint. It is also
            # the pair the heuristic is least wrong about.
            self._bump("cross_game")
            return None
        if label_a == label_b:
            self._bump("same_dimension")
            return None

        value = _lookup_pair(self._joint_by_pk[pk_a], self._label_pos[pk_a], label_a, label_b)
        if value is None:
            self._bump("undefined_pair")
            return None
        # UNIT CONVERSION, and it is the difference between beating the guess
        # and losing to independence. `value` is a SPEARMAN RANK CORRELATION OF
        # COUNTS; the consumer prices a THRESHOLDED bet (`hits > 0.5`), and
        # thresholding attenuates dependence to 54-68% of the rank figure.
        # Measured 2026-09-05 over 6,396 realised leg pairs: passing the raw
        # value through made the joint LOSE to plain independence
        # (+0.101 log-loss same-player), monotonically worse the more the
        # estimator was allowed to move. See `threshold_correlation`.
        p_a = candidate_probability(candidate_a)
        p_b = candidate_probability(candidate_b)
        converted = threshold_correlation(float(value), p_a, p_b)
        self._bump("measured" if (p_a is not None and p_b is not None)
                   else "measured_fallback_attenuation")
        return converted

    def _lookup_for_test(self, game_pk: int, label_a: str, label_b: str) -> Optional[float]:
        """Raw pair read, bypassing candidate keying.

        Exists so `test_resolver_agrees_with_the_producers_own_reader` can compare
        THIS reader against the producer's over every pair of a real payload --
        the guard against the deliberate `triangle_index` duplication drifting.
        """
        pk = int(game_pk)
        return _lookup_pair(self._joint_by_pk[pk], self._label_pos[pk], label_a, label_b)

    def as_lookup(self) -> Callable[[Dict[str, Any], Dict[str, Any]], Optional[float]]:
        """The callable to hand to `compute_correlation(measured_lookup=...)`."""
        return self.measured


from syndicate.features.mlb.threshold_correlation import (
    candidate_probability,
    threshold_correlation,
)


def _subject_from_display_name(value: Any) -> str:
    """`"Aaron Judge Over 1.5 Total Bases"` -> `"Aaron Judge"`.

    Mirrors `correlation_engine._candidate_subject_key`'s own handling of the
    `name` field, so a candidate carrying only a display string resolves the
    same way in both places.
    """
    text = str(value or "")
    for marker in (" Over ", " Under ", " over ", " under "):
        if marker in text:
            return text.split(marker, 1)[0].strip()
    return text


def build_measured_lookup(
    date_str: str,
    *,
    game_pks: Optional[Iterable[int]] = None,
) -> Tuple[Callable[[Dict[str, Any], Dict[str, Any]], Optional[float]], JointCorrelationIndex]:
    """Convenience: index a date and return `(lookup, index)`.

    The index comes back so a caller can report `index.reasons` and
    `index.games_with_joint`. A resolver that silently answers `None` for every
    pair is indistinguishable from one that is not wired up at all, and those
    counters are the difference.
    """
    index = JointCorrelationIndex.for_date(date_str, game_pks=game_pks)
    return index.as_lookup(), index
