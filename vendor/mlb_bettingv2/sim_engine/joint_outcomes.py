"""The MLB sim's JOINT outcome distribution -- accumulated, ranked, published.

`#621` Phase 4, producer side. The consumer landed first (`1bbcc246`):
`correlation_engine.compute_correlation(..., measured_lookup=...)` takes a
resolver returning `float | None` whose value REPLACES the heuristic stack and
stamps `correlation_basis="measured_joint"`.

WHAT THIS REPLACES. Today `_sim_many` runs 1,000 game simulations and reduces
every one of them into MARGINAL counters -- per-player histograms, per-segment
totals. The joint is computed and thrown away on every run. What survives to the
artifact is 50 per-segment score `samples`. The correlation the platform prices
parlays with is instead a sum of categorical flags plus a static table holding
ONE constant for every player in every game -- `("mlb", ("home_runs",
"total_bases")): 1.35` at `syndicate/features/intelligence.py:617`, never
measured, and reaching real money through parlay pricing, board correlation
badges and `bankroll_manager.build_portfolio` bet SIZING.

--------------------------------------------------------------------------
SHAPE. MEASURED, because it is the whole risk.
--------------------------------------------------------------------------

The refresh-worker peaks at ~3.29 GB against a 4 GiB ceiling, so a per-sim
matrix is a real memory question and not a free one. One game, 1,000 sims,
D=292 tracked outcomes, RSS delta measured on py-3.11.9/win32 with `psutil`
(the first attempt used a hand-rolled ctypes `GetProcessMemoryInfo` that
returned 0 for every shape -- a reading indistinguishable from "free"):

    theoretical  n*D*2                            584,000 B
    array('h', [0]) * (n*D)      PROPOSED         647,168 B   1.11x theory
    array('h', bytes(2*n*D))                    1,273,856 B   2.18x  (temporary)
    numpy zeros int16, touched                    634,880 B   1.09x  (+23.9 MB import)
    list-of-lists                               2,572,288 B   4.40x
    list-of-dicts, sim-like small ints          6,746,112 B  11.55x
    list-of-dicts, DISTINCT ints               16,375,808 B  28.04x

`list-of-dicts` is the shape `samples` uses today, and lengthening it was the
obvious move and the wrong one -- 28x theory, because every scalar carries a
`PyObject` header and a dict slot. Note the spread WITHIN that row: interned
small ints read 11.55x and distinct ints 28.04x, so a synthetic benchmark using
`i % 7` would have understated the real thing by 2.4x.

`array('h', [0]) * n` is chosen over numpy for the ACCUMULATOR because
`_simw_chunk` runs in FOUR spawned worker processes and `import numpy` costs
23.9 MB of RSS in each (measured), against a 647 KB matrix. numpy is imported
lazily in the PARENT only, where the correlation is actually computed.
`scipy.stats` is not imported at all in production: 54.2 MB and **4.96 s** to
import (measured), for a `rankdata` this module implements in fifteen lines and
`tests/` checks against scipy directly.

RETENTION, NOT SHAPE, IS THE REAL CEILING QUESTION. The prompt's 373 MB figure
assumed all 17 games held at once. They are not: `_sim_many` is called per game
and the matrix is consumed and dropped before the next. One game live at a time
costs 647 KB -- **0.09% of the worker's ~708 MB headroom**. Holding the whole
slate would cost 3.2 MB even in this shape, so the discipline that matters is
"do not accumulate across games", which `JointAccumulator` enforces by owning no
module-level state.

--------------------------------------------------------------------------
WHY RANK (SPEARMAN) AND NOT PEARSON
--------------------------------------------------------------------------

These are small counts with hard floors -- a batter's home runs are 0 in ~92% of
sims. Pearson on such a variable measures the shape of its zero-inflation as
much as its dependence. Spearman is invariant to any monotone re-expression,
which is what a parlay actually needs: does leg B tend to land when leg A does.

A CONSTANT COLUMN HAS NO CORRELATION, AND MUST READ `null`, NEVER `0.0`. This is
`model_engine_standard` §4.2 exactly: `0.0` is a legitimate measurement meaning
"independent", so returning it for "undefined" makes a DEAD FIELD look like a
measured independence. It is not hypothetical -- lane `mlb-hitter-so-dead-field`
has `strikeouts` pinned at 0 for every hitter in every game right now, so the
first slate carrying `strikeouts` will emit an all-`null` row, and that row is
an independent witness for their bug over the whole slate.
"""
from __future__ import annotations

import array
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

#: Scale for the published integer correlations. 1000 keeps three decimals --
#: finer than any consumer can act on, and it keeps the artifact small: a dense
#: DxD float matrix of D=96 is ~4,560 pairs, and ints cost roughly a third of
#: the JSON that "a|b": 0.1234567 keys would.
CORR_SCALE = 1000

#: Sentinel for "this pair has no defined correlation" in the packed triangle.
#: Outside the achievable range of a scaled coefficient, so it can never be
#: confused with a real measurement, and it round-trips through JSON as an int.
CORR_UNDEFINED = -32768

#: int16 bounds. Every tracked MLB per-sim outcome is a small count (a batter's
#: total bases max out around 15, a segment's runs around 30), so the clamp
#: should never fire -- which is why it is COUNTED rather than silent. A
#: wrapped int16 would corrupt a correlation with no error and no log line.
_I16_MIN = -32767
_I16_MAX = 32767

#: The hitter markets a joint is worth keeping, and the key each reads out of
#: the per-sim `hitter_stat_values` dict built at BOTH accumulation sites in
#: `daily_update.py`. Keep this in step with `_HITTER_PROP_DIST_SPECS` there.
#:
#: `strikeouts`/`SO` was held back until its source key existed. Lane
#: `mlb-hitter-so-dead-field` landed `0b9a03e7` adding `"SO": so` at BOTH sites
#: (`:726` and `:4457`), so it is included from this commit -- the market was
#: added in the same change that made it measurable, never before, because a
#: market whose source key is missing publishes a constant column dressed as a
#: measurement.
HITTER_MARKET_ROW_KEYS: Tuple[Tuple[str, str], ...] = (
    ("hits", "H"),
    ("home_runs", "HR"),
    ("total_bases", "TB"),
    ("rbi", "RBI"),
    ("strikeouts", "SO"),
)

#: Per-segment team-score dimensions, named to match the artifact's `segments`.
SEGMENT_SCORE_LABELS: Tuple[str, ...] = (
    "team|full|away",
    "team|full|home",
    "team|first1|away",
    "team|first1|home",
    "team|first3|away",
    "team|first3|home",
    "team|first5|away",
    "team|first5|home",
)

#: Starter dimensions and the `pitcher_stats` row key each reads.
STARTER_MARKET_ROW_KEYS: Tuple[Tuple[str, str], ...] = (
    ("strikeouts", "SO"),
    ("outs", "OUTS"),
    ("earned_runs", "ER"),
    ("hits_allowed", "H"),
    ("walks", "BB"),
)


def hitter_label(player_id: int, market: str) -> str:
    """`batter|<mlbam_id>|<market>` -- the id, never the name.

    Names collide, get punctuated differently between feeds, and are not stable
    across a roster rebuild. The RESOLVER is where name-based candidate lookup
    is handled, against a `players` map this artifact publishes alongside.
    """
    return f"batter|{int(player_id)}|{market}"


def starter_label(player_id: int, market: str) -> str:
    return f"pitcher|{int(player_id)}|{market}"


def build_labels(
    batter_ids: Sequence[int],
    starter_ids: Sequence[int] = (),
) -> List[str]:
    """The dimension list, in a DETERMINISTIC order.

    Order matters more than it looks: `_simw_chunk` runs in separate processes
    and each builds its own accumulator, so a label list that depended on dict
    iteration or on which chunk ran first would produce matrices that cannot be
    concatenated. Sorting the ids makes the order a function of the inputs
    alone, and `JointAccumulator.extend` asserts the lists match rather than
    trusting it.
    """
    labels: List[str] = list(SEGMENT_SCORE_LABELS)
    for pid in sorted({int(p) for p in batter_ids}):
        for market, _row_key in HITTER_MARKET_ROW_KEYS:
            labels.append(hitter_label(pid, market))
    for pid in sorted({int(p) for p in starter_ids}):
        for market, _row_key in STARTER_MARKET_ROW_KEYS:
            labels.append(starter_label(pid, market))
    return labels


class JointAccumulator:
    """One game's `n_sims x D` per-sim outcome matrix, in one flat `array('h')`.

    Row-major: sim `i`, dimension `j` lives at `i * D + j`. Preallocated once by
    sequence-repeat (`array('h', [0]) * (n*D)`), which is the cheapest of the
    six shapes measured in this module's docstring and the only one that avoids
    building a same-sized temporary on the way.

    NOT thread-safe and deliberately not shared: one instance per game per
    process, dropped when the game's artifact is written.
    """

    __slots__ = ("labels", "_index", "n_sims", "n_dims", "buf", "_rows", "clamped")

    def __init__(self, labels: Sequence[str], n_sims: int) -> None:
        self.labels: List[str] = [str(x) for x in labels]
        self.n_dims = len(self.labels)
        self.n_sims = int(max(0, n_sims))
        self._index: Dict[str, int] = {label: i for i, label in enumerate(self.labels)}
        if len(self._index) != self.n_dims:
            raise ValueError("joint labels must be unique")
        self.buf = array.array("h", [0]) * (self.n_sims * self.n_dims) if self.n_dims and self.n_sims else array.array("h")
        self._rows = 0
        #: Count of values that hit the int16 clamp. Published, so an overflow
        #: is a visible number rather than a silently wrapped correlation.
        self.clamped = 0

    def record(self, sim_index: int, values: Dict[str, int]) -> None:
        """Write one simulation's outcomes. Unknown labels are ignored."""
        i = int(sim_index)
        if i < 0 or i >= self.n_sims:
            return
        base = i * self.n_dims
        buf = self.buf
        index = self._index
        for label, value in values.items():
            j = index.get(label)
            if j is None:
                continue
            try:
                v = int(value)
            except (TypeError, ValueError):
                continue
            if v > _I16_MAX:
                v = _I16_MAX
                self.clamped += 1
            elif v < _I16_MIN:
                v = _I16_MIN
                self.clamped += 1
            buf[base + j] = v
        if i + 1 > self._rows:
            self._rows = i + 1

    @property
    def rows_written(self) -> int:
        return self._rows

    # --- crossing the process boundary --------------------------------------

    def to_transport(self) -> Dict[str, Any]:
        """A picklable dict for a `_simw_chunk` return value.

        `array('h')` pickles as a raw buffer, so the 1,000x292 matrix crosses
        the boundary as ~584 KB of bytes rather than 292,000 `PyObject`s.
        `_merge_seg` merges only counts today, which is why nothing joint
        survives the multiprocessing path at all -- this is the missing half.
        """
        return {
            "labels": list(self.labels),
            "n_sims": int(self._rows),
            "clamped": int(self.clamped),
            "buf": self.buf[: self._rows * self.n_dims],
        }

    def extend(self, transport: Dict[str, Any]) -> None:
        """Append another chunk's rows. Row ORDER is irrelevant to a correlation.

        Chunks cover disjoint sim ranges and a rank correlation is invariant to
        row permutation, so plain concatenation is correct and no reindexing is
        needed. The label lists MUST match: concatenating two matrices whose
        columns mean different things would produce a plausible, wrong number
        with no error -- so this raises instead.
        """
        other_labels = [str(x) for x in (transport.get("labels") or [])]
        if other_labels != self.labels:
            raise ValueError(
                "joint label mismatch across sim chunks: "
                f"{len(other_labels)} vs {len(self.labels)} dims"
            )
        buf = transport.get("buf")
        if buf is None:
            return
        incoming = buf if isinstance(buf, array.array) else array.array("h", buf)
        if self.n_dims and len(incoming) % self.n_dims:
            raise ValueError("joint chunk buffer is not a whole number of rows")
        self.buf.extend(incoming)
        self._rows += (len(incoming) // self.n_dims) if self.n_dims else 0
        self.n_sims = self._rows
        self.clamped += int(transport.get("clamped") or 0)

    @classmethod
    def from_transport(cls, transport: Dict[str, Any]) -> "JointAccumulator":
        acc = cls(list(transport.get("labels") or []), 0)
        acc.extend(transport)
        return acc

    # --- the published payload ----------------------------------------------

    def to_payload(self, *, players: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """`sim["joint"]` -- labels, n, a packed lower triangle, and provenance.

        The triangle is DENSE: near-zero pairs are kept. Pruning them would make
        a MEASURED independence indistinguishable from an unmeasured pair, which
        is the same class of error as `.get(key, 1.0)` -- see the module
        docstring. Undefined pairs are `CORR_UNDEFINED`, never 0.
        """
        corr = spearman_lower_triangle(self.buf, self._rows, self.n_dims)
        payload: Dict[str, Any] = {
            "version": 1,
            "method": "spearman_rank",
            "labels": list(self.labels),
            "n": int(self._rows),
            "scale": CORR_SCALE,
            "undefined": CORR_UNDEFINED,
            "corr_lower": corr,
            "clamped": int(self.clamped),
        }
        if players:
            payload["players"] = players
        return payload


# --- rank correlation --------------------------------------------------------


def rankdata_average(values: Sequence[float]) -> List[float]:
    """Average ranks, ties shared -- `scipy.stats.rankdata`'s default method.

    Reimplemented rather than imported because `import scipy.stats` costs 54.2
    MB of RSS and 4.96 s (measured), for this. `tests/` asserts equivalence
    against scipy on random and heavily-tied inputs, so the reference is checked
    rather than merely believed.
    """
    n = len(values)
    order = sorted(range(n), key=lambda i: values[i])
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and values[order[j + 1]] == values[order[i]]:
            j += 1
        shared = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = shared
        i = j + 1
    return ranks


def _column(buf: Sequence[int], n_rows: int, n_dims: int, j: int) -> List[int]:
    return [buf[i * n_dims + j] for i in range(n_rows)]


def spearman_lower_triangle(
    buf: Sequence[int],
    n_rows: int,
    n_dims: int,
) -> List[int]:
    """Packed lower triangle (j < i), row-major, scaled by `CORR_SCALE`.

    Element order is (1,0), (2,0), (2,1), (3,0)... so index(i, j) =
    i*(i-1)//2 + j. `triangle_index` is the one place that arithmetic is
    written; the resolver imports it rather than re-deriving it.

    numpy is used when available and a pure-Python path covers its absence,
    because this runs inside a vendored sim whose worker processes should not
    be made to depend on it. Both paths are checked against each other in
    `tests/`.
    """
    if n_rows < 2 or n_dims < 2:
        return [CORR_UNDEFINED] * (n_dims * (n_dims - 1) // 2)

    ranked: List[List[float]] = []
    constant: List[bool] = []
    for j in range(n_dims):
        col = _column(buf, n_rows, n_dims, j)
        first = col[0]
        is_const = all(v == first for v in col)
        constant.append(is_const)
        ranked.append([0.0] * n_rows if is_const else rankdata_average(col))

    try:
        import numpy as np  # noqa: WPS433 - lazy on purpose; see module docstring

        mat = np.asarray(ranked, dtype=np.float64)
        centred = mat - mat.mean(axis=1, keepdims=True)
        norms = np.sqrt((centred * centred).sum(axis=1))
        out: List[int] = []
        for i in range(n_dims):
            for j in range(i):
                if constant[i] or constant[j] or norms[i] == 0.0 or norms[j] == 0.0:
                    out.append(CORR_UNDEFINED)
                    continue
                rho = float((centred[i] * centred[j]).sum() / (norms[i] * norms[j]))
                out.append(_pack(rho))
        return out
    except ImportError:
        pass

    means = [sum(col) / float(n_rows) for col in ranked]
    centred = [[v - means[k] for v in ranked[k]] for k in range(n_dims)]
    norms = [sum(v * v for v in centred[k]) ** 0.5 for k in range(n_dims)]
    out = []
    for i in range(n_dims):
        for j in range(i):
            if constant[i] or constant[j] or norms[i] == 0.0 or norms[j] == 0.0:
                out.append(CORR_UNDEFINED)
                continue
            dot = sum(a * b for a, b in zip(centred[i], centred[j]))
            out.append(_pack(dot / (norms[i] * norms[j])))
    return out


def _pack(rho: float) -> int:
    if rho != rho:  # NaN is not a measurement
        return CORR_UNDEFINED
    return int(round(max(-1.0, min(1.0, rho)) * CORR_SCALE))


def triangle_index(i: int, j: int) -> int:
    """Position of pair (i, j) in a packed lower triangle. `i != j` required."""
    if i == j:
        raise ValueError("a dimension has no off-diagonal entry with itself")
    if i < j:
        i, j = j, i
    return i * (i - 1) // 2 + j


def unpack(value: int) -> Optional[float]:
    """Scaled int -> coefficient, or None for an UNDEFINED pair."""
    if value is None or int(value) == CORR_UNDEFINED:
        return None
    return float(value) / float(CORR_SCALE)


def lookup(payload: Dict[str, Any], label_a: str, label_b: str) -> Optional[float]:
    """Read one pair out of a published `sim["joint"]`. None when undefined."""
    if not isinstance(payload, dict):
        return None
    labels: Iterable[str] = payload.get("labels") or ()
    try:
        index = {str(x): k for k, x in enumerate(labels)}
    except TypeError:
        return None
    i = index.get(str(label_a))
    j = index.get(str(label_b))
    if i is None or j is None or i == j:
        return None
    tri = payload.get("corr_lower") or []
    pos = triangle_index(i, j)
    if pos >= len(tri):
        return None
    scale = float(payload.get("scale") or CORR_SCALE)
    raw = tri[pos]
    if raw is None or int(raw) == int(payload.get("undefined", CORR_UNDEFINED)):
        return None
    return float(raw) / scale
