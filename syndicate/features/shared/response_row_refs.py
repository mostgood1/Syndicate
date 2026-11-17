"""Send each board-query row ONCE (`/api/intelligence/query`, body flag `row_refs`).

MEASURED on the fleet's served response, 2026-11-16 7:48 PM CST (lane
`board-query-row-refs`, layer2-rail-monitor backlog I-2). The page's own request
(`slim_aliases` + `drop_row_diagnostics`) came back at 80.3 MB uncompressed,
14.4 MB on the wire, in 78 s:

    ranked_all              6,295 rows   23.9 MB
    board_contract.cards    6,295 rows   23.1 MB   the same rows by pick_id
    top_opportunities       4,500 rows   21.4 MB   a subset of ranked_all
    top_live_opportunities  2,176 rows   11.9 MB   a subset of ranked_all

**NO ROW IS AN EXACT COPY, so plain references would lose data.** Every
`top_opportunities` row is its `ranked_all` row PLUS ~10 keys (`rationale`,
`pick`, `american_odds`, ...). Every card LACKS the two logo keys, and 498 cards
carry a different `gate`. `top_live_opportunities` never went through
`drop_row_diagnostics`, so its `quote` / `movement` / `trace` differed on every
row. The embed's exact-match row references (`_slim_embedded_board_payload`)
would therefore have referenced nothing here.

**Since lane `board-query-diag-strip` (2026-11-17, todo `#827`)** the flag strips
`top_live_opportunities` too and drops `rationale` from every list. On the same
recorded response that takes this encoding's output from 33,144,917 to
25,559,058 B raw (5,689,938 -> 4,575,384 B gzip-1): the `top_live_opportunities`
patch falls from 5.2 MB to 0.49 MB and the `top_opportunities` patch from 3.9 to
1.0 MB. The rows still differ from `ranked_all` (the ~9 keys the top lists add,
the cards' `gate`), so the encoding is unchanged and still lossless.

THE ENCODING, per list, is lossless by construction:

    {"from": "ranked_all",
     "index": [i, ...],          # the ranked_all row each row starts from, or null
     "order": [key, ...],        # every key any row of the list has, in WIRE order
     "patch": [{...} | null],    # keys that are new or whose value differs
     "drop":  {"n": [key, ...]}} # keys of the base row that row n does not have

Row n is rebuilt by walking `order`: a key in its patch takes the patch's value,
else a key on the base row that row n does not drop takes the base row's value.
A base key outside `order` (the cards' logos) is never emitted. So every key the
row had comes back with its own value, no key it lacked appears, and the keys
come back in the order the flag-off response would have put them on the wire.

An encoded list stays on the payload as `null`, so the rebuild fills the key
where it already sits and the container's key order is unchanged too.

ENCODE ONLY WHAT IS SERIALISED. `_response_candidate_count` is
`len(top_opportunities)`, so anything that reads the payload server-side (the
debug fields, the stage log) must read it BEFORE this runs; the route hands only
the copy it serialises to `encode_row_refs`.

`order` IS THE WIRE ORDER, NOT PYTHON'S. Flask's JSON provider sorts keys
(`DefaultJSONProvider.sort_keys = True`), so the flag-off page sees every row's
keys sorted; the rebuild must produce the same. When the provider does not sort,
`order` is one key order consistent with every row's own order, and a list whose
rows disagree on order is sent in full.

THE FAILURE MODE IS "NO SAVING", NEVER "WRONG DATA". A value is omitted from a
patch only when `_same_on_wire` proves it serialises identically to the base
row's (type-strict, key order included, NaN and -0.0 always patched). A list
that cannot be encoded is left exactly as it was. A row with no unique
`pick_id` in `ranked_all` travels whole inside its patch.

OPT-IN, and the server can refuse: the caller sends `row_refs: true`, and
`SYNDICATE_QUERY_ROW_REFS=off` makes the server ignore it. ABSENT MEANS THE
REQUEST IS HONOURED. Only the page sends the flag, and its `rehydrateAliases`
rebuilds the lists before any other reader runs. A caller that does not send
the flag gets exactly what it got before.
"""

from __future__ import annotations

import math
import os
from typing import Any

#: The lists encoded against `ranked_all`, by path. Named rather than walked, so
#: a new list elsewhere in the payload is never encoded by accident -- the same
#: reason `_DIAGNOSTIC_ROW_LISTS` names its lists.
ROW_REF_LISTS = ("top_opportunities", "top_live_opportunities", "board_contract.cards")
ROW_REF_SOURCE = "ranked_all"
ROW_REF_KEY = "pick_id"
#: Where the payload declares the encoding. The page deletes it after rebuilding.
RESPONSE_KEY = "_response_row_refs"
ENV_SWITCH = "SYNDICATE_QUERY_ROW_REFS"

_OFF_VALUES = {"off", "0", "false", "no", "n", "f"}
_ON_VALUES = {"1", "true", "t", "yes", "y", "on"}
_MAX_DEPTH = 16
_MISSING = object()


def row_refs_enabled() -> bool:
    """The server's off switch. ABSENT means ON (the caller's request is honoured)."""
    return str(os.environ.get(ENV_SWITCH) or "").strip().lower() not in _OFF_VALUES


def row_refs_requested(payload: Any) -> bool:
    """True only when the caller sent `row_refs` truthy AND the server has not switched it off."""
    if not isinstance(payload, dict):
        return False
    value = payload.get("row_refs")
    asked = value if isinstance(value, bool) else str(value or "").strip().lower() in _ON_VALUES
    return bool(asked) and row_refs_enabled()


def _same_on_wire(left: Any, right: Any, depth: int = 0) -> bool:
    """True only if `left` and `right` PROVABLY serialise to the same JSON.

    Stricter than `blueprints/intelligence.py::_provably_same` in two places,
    because a value omitted here is rebuilt from the OTHER object: dict key ORDER
    must match (a provider that does not sort keys sends it), and a float must
    match in sign as well (`-0.0 == 0.0`, but they serialise differently). NaN is
    never equal to itself, so it is always patched; `json_safe_value` then turns
    both copies into the same `null`.
    """
    if left is right:
        return True
    kind = type(left)
    if kind is not type(right):
        return False
    if kind is str or kind is int or kind is bool:
        return left == right
    if kind is float:
        return _same_float(left, right)
    if depth > _MAX_DEPTH:
        return False
    # Scalars are compared INLINE in the two loops below: on the recorded 11-16
    # response 2.4M calls, mostly on scalars, cost ~2 s; recursing only into
    # containers is what keeps this cheaper than the serialisation it saves.
    if kind is dict:
        if len(left) != len(right):
            return False
        for (lk, lv), (rk, rv) in zip(left.items(), right.items()):
            if lk != rk:
                return False
            if lv is rv:
                continue
            t = type(lv)
            if t is not type(rv):
                return False
            if t is str or t is int or t is bool:
                if lv != rv:
                    return False
            elif t is float:
                if lv != rv or (lv == 0.0 and math.copysign(1.0, lv) != math.copysign(1.0, rv)):
                    return False
            elif not _same_on_wire(lv, rv, depth + 1):
                return False
        return True
    if kind is list or kind is tuple:
        if len(left) != len(right):
            return False
        for lv, rv in zip(left, right):
            if lv is rv:
                continue
            t = type(lv)
            if t is not type(rv):
                return False
            if t is str or t is int or t is bool:
                if lv != rv:
                    return False
            elif t is float:
                if lv != rv or (lv == 0.0 and math.copysign(1.0, lv) != math.copysign(1.0, rv)):
                    return False
            elif not _same_on_wire(lv, rv, depth + 1):
                return False
        return True
    return False


def _same_float(left: float, right: float) -> bool:
    if left != right:
        return False
    return left != 0.0 or math.copysign(1.0, left) == math.copysign(1.0, right)


def _same_value(lv: Any, rv: Any, depth: int) -> bool:
    """One element of a container: scalars here, containers recurse."""
    if lv is rv:
        return True
    t = type(lv)
    if t is not type(rv):
        return False
    if t is str or t is int or t is bool:
        return lv == rv
    if t is float:
        return _same_float(lv, rv)
    return _same_on_wire(lv, rv, depth + 1)


def _key_order(rows: list[dict], *, sort_keys: bool) -> list[str] | None:
    """The key order the flag-off response puts every row of `rows` in, or None.

    Sorted when the provider sorts. Otherwise one order consistent with every
    row's own order (a precedence merge, ties broken by first appearance), or
    None when two rows disagree -- that list is then sent in full.
    """
    seen: dict[Any, None] = {}
    for row in rows:
        for key in row:
            seen.setdefault(key, None)
    if any(not isinstance(key, str) for key in seen):
        return None
    if sort_keys:
        return sorted(seen)
    successors: dict[str, set[str]] = {key: set() for key in seen}
    indegree: dict[str, int] = {key: 0 for key in seen}
    for row in rows:
        keys = list(row)
        for a, b in zip(keys, keys[1:]):
            if b not in successors[a]:
                successors[a].add(b)
                indegree[b] += 1
    rank = {key: n for n, key in enumerate(seen)}
    ready = sorted((k for k, d in indegree.items() if d == 0), key=rank.__getitem__)
    order: list[str] = []
    while ready:
        key = ready.pop(0)
        order.append(key)
        released = [m for m in successors[key] if indegree[m] == 1]
        for m in successors[key]:
            indegree[m] -= 1
        if released:
            ready = sorted(ready + released, key=rank.__getitem__)
    if len(order) != len(seen):
        return None
    for row in rows:
        if [k for k in order if k in row] != list(row):
            return None
    return order


def _split_path(path: str) -> tuple[str, str | None]:
    parent, _, child = path.partition(".")
    return parent, (child or None)


def encode_row_refs(response: Any, *, sort_keys: bool = True) -> Any:
    """Replace each list in `ROW_REF_LISTS` with references into `ranked_all`.

    Returns a NEW top-level dict (and a new `board_contract` when its cards are
    encoded), with each encoded list set to `None` in place; nothing the caller
    holds is mutated. Returns `response` itself when
    nothing could be encoded. `sort_keys` must be the serialising provider's own
    setting -- see the module docstring.
    """
    if not isinstance(response, dict):
        return response
    source = response.get(ROW_REF_SOURCE)
    if not isinstance(source, list) or not source:
        return response
    index_of: dict[str, int | None] = {}
    for i, row in enumerate(source):
        if not isinstance(row, dict):
            return response
        pid = row.get(ROW_REF_KEY)
        if isinstance(pid, str) and pid:
            # A duplicated id references nothing: such rows travel whole.
            index_of[pid] = None if pid in index_of else i

    out = dict(response)
    refs: dict[str, dict[str, Any]] = {}
    for path in ROW_REF_LISTS:
        parent, child = _split_path(path)
        container = out if child is None else out.get(parent)
        leaf = parent if child is None else child
        if not isinstance(container, dict):
            continue
        rows = container.get(leaf)
        if not isinstance(rows, list) or not rows or not all(isinstance(r, dict) for r in rows):
            continue
        order = _key_order(rows, sort_keys=sort_keys)
        if order is None:
            continue
        in_order = set(order)
        index: list[int | None] = []
        patches: list[dict | None] = []
        drops: dict[str, list[str]] = {}
        for n, row in enumerate(rows):
            pid = row.get(ROW_REF_KEY)
            i = index_of.get(pid) if isinstance(pid, str) else None
            if i is None:
                index.append(None)
                patches.append(dict(row))
                continue
            base = source[i]
            patch = {}
            for k, v in row.items():
                bv = base.get(k, _MISSING)
                if bv is _MISSING or not _same_value(v, bv, 0):
                    patch[k] = v
            gone = [k for k in base if k in in_order and k not in row]
            index.append(i)
            patches.append(patch or None)
            if gone:
                drops[str(n)] = gone
        spec: dict[str, Any] = {"from": ROW_REF_SOURCE, "index": index, "order": order, "patch": patches}
        if drops:
            spec["drop"] = drops
        refs[path] = spec
        # A `null` PLACEHOLDER, not a removed key: the rebuild assigns into the
        # existing key, which keeps its position. Removing it put `cards` back at
        # the END of `board_contract` on the recorded response (every row matched
        # byte for byte; only the container's key order differed).
        if child is None:
            out[leaf] = None
        else:
            container = dict(container)
            container[leaf] = None
            out[parent] = container
    if not refs:
        return response
    out[RESPONSE_KEY] = refs
    return out


def decode_row_refs(payload: Any) -> Any:
    """The page's rebuild (`rehydrateAliases`), in Python.

    The reference the tests hold the template's JS to, and what the measurement
    uses. Mutates and returns `payload`, as the page does, and removes
    `RESPONSE_KEY` so the rebuilt payload has exactly the flag-off keys.
    """
    if not isinstance(payload, dict):
        return payload
    refs = payload.pop(RESPONSE_KEY, None)
    if not isinstance(refs, dict):
        return payload
    for path, spec in refs.items():
        if not isinstance(spec, dict):
            continue
        source = payload.get(spec.get("from"))
        index, order = spec.get("index"), spec.get("order")
        if not isinstance(source, list) or not isinstance(index, list) or not isinstance(order, list):
            continue
        patches = spec.get("patch") if isinstance(spec.get("patch"), list) else []
        drops = spec.get("drop") if isinstance(spec.get("drop"), dict) else {}
        rows = []
        for n, i in enumerate(index):
            base = source[i] if isinstance(i, int) and 0 <= i < len(source) else {}
            patch = patches[n] if n < len(patches) and isinstance(patches[n], dict) else None
            dropped = drops.get(str(n)) or ()
            row = {}
            for key in order:
                if patch is not None and key in patch:
                    row[key] = patch[key]
                elif key in base and key not in dropped:
                    row[key] = base[key]
            rows.append(row)
        parent, child = _split_path(path)
        if child is None:
            payload[parent] = rows
        elif isinstance(payload.get(parent), dict):
            payload[parent][child] = rows
    return payload
