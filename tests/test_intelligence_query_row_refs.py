"""`row_refs`: the board query sends each opportunity row ONCE (lane board-query-row-refs).

MEASURED on the fleet's served `/api/intelligence/query`, 2026-11-16 7:48 PM CST
(the page's own request: `slim_aliases` + `drop_row_diagnostics`): 80.3 MB raw /
14.4 MB gzipped, of which ranked_all 23.9, board_contract.cards 23.1,
top_opportunities 21.4 and top_live_opportunities 11.9 MB -- the same rows by
pick_id. With `row_refs`: 33.1 MB raw / 5.7 MB gzipped, and the page's own
`rehydrateAliases` rebuilds a payload JSON.stringify-identical to the flag-off one
(full measurement in `.syndicate/findings_2026-11-17_board_query_row_refs.md`).

ORDER, as `learnings.md` asks: reachability first (off != on through the body flag
and through `SYNDICATE_QUERY_ROW_REFS`), then the size saving, then equivalence on
a slice of that recorded response (`tests/fixtures/intelligence_query_row_refs_sample.json`)
-- in Python and with the template's real function under node -- then the edge
cases that must cost bytes rather than data.
"""

from __future__ import annotations

import copy
import json
import shutil
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from syndicate.features.shared import response_row_refs as rr

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "intelligence_query_row_refs_sample.json"
TEMPLATE = ROOT / "syndicate" / "templates" / "intelligence.html"
NODE = shutil.which("node")


def _recorded() -> dict:
    return json.loads(FIXTURE.read_text(encoding="ascii"))


def _wire(obj) -> str:
    """What Flask's provider sends: json_safe, sorted keys, compact, ASCII."""
    from syndicate.features.shared.json_safety import json_safe_value

    return json.dumps(json_safe_value(obj), sort_keys=True, ensure_ascii=True, separators=(",", ":"))


def _in_order(obj) -> str:
    """Serialise WITHOUT sorting, so a key-order difference is a difference."""
    return json.dumps(obj, ensure_ascii=True, separators=(",", ":"))


# --------------------------------------------------------------------------
# 1. Reachability: off != on, through the body flag and through the env.
# --------------------------------------------------------------------------


def test_the_flag_is_off_unless_asked(monkeypatch):
    monkeypatch.delenv(rr.ENV_SWITCH, raising=False)
    assert rr.row_refs_requested({}) is False
    assert rr.row_refs_requested(None) is False
    assert rr.row_refs_requested({"row_refs": False}) is False
    assert rr.row_refs_requested({"row_refs": "no"}) is False
    assert rr.row_refs_requested({"row_refs": True}) is True
    assert rr.row_refs_requested({"row_refs": "true"}) is True


def test_the_server_off_switch_refuses_an_asking_caller(monkeypatch):
    """ABSENT honours the request; `off` refuses it."""
    monkeypatch.delenv(rr.ENV_SWITCH, raising=False)
    assert rr.row_refs_requested({"row_refs": True}) is True
    for value in ("off", "OFF", "0", "false", "no"):
        monkeypatch.setenv(rr.ENV_SWITCH, value)
        assert rr.row_refs_requested({"row_refs": True}) is False, value
    monkeypatch.setenv(rr.ENV_SWITCH, "on")
    assert rr.row_refs_requested({"row_refs": True}) is True


class _Route:
    """The real `/api/intelligence/query` combined-board exit, fed the recorded board."""

    def __init__(self):
        from syndicate.app import create_app

        app = create_app()
        app.testing = True
        self.client = app.test_client()

    def post(self, **flags):
        board = copy.deepcopy(_recorded()["response"])
        body = {"question": "show me the board", "slim_aliases": True, "drop_row_diagnostics": True}
        body.update(flags)
        with patch("syndicate.blueprints.intelligence.combined_board_default_enabled", return_value=True), \
             patch("syndicate.blueprints.intelligence.read_combined_intelligence_response", return_value=board):
            res = self.client.post("/api/intelligence/query", json=body)
        assert res.status_code == 200
        return res.get_data(as_text=True)


@pytest.fixture(scope="module")
def route():
    return _Route()


def test_off_and_on_differ_through_the_route(route, monkeypatch):
    monkeypatch.delenv(rr.ENV_SWITCH, raising=False)
    off = json.loads(route.post())
    on = json.loads(route.post(row_refs=True))

    assert rr.RESPONSE_KEY not in off["response"]
    assert isinstance(off["response"]["top_opportunities"], list) and off["response"]["top_opportunities"]

    refs = on["response"][rr.RESPONSE_KEY]
    assert set(refs) == {"top_opportunities", "top_live_opportunities", "board_contract.cards"}
    assert on["response"]["top_opportunities"] is None
    assert on["response"]["top_live_opportunities"] is None
    assert on["response"]["board_contract"]["cards"] is None
    assert len(on["response"]["ranked_all"]) == len(off["response"]["ranked_all"])


def test_the_env_switch_turns_it_off_through_the_route(route, monkeypatch):
    monkeypatch.setenv(rr.ENV_SWITCH, "off")
    off = route.post()
    refused = route.post(row_refs=True)
    assert rr.RESPONSE_KEY not in json.loads(refused)["response"]
    assert json.loads(refused)["response"] == json.loads(off)["response"]


def test_the_debug_fields_still_read_the_unencoded_payload(route, monkeypatch):
    """`candidate_count` is `len(top_opportunities)`. Read after encoding it is 0,
    and the page shows it -- the route must hand the encoder only the copy it
    serialises."""
    monkeypatch.delenv(rr.ENV_SWITCH, raising=False)
    off = json.loads(route.post())
    on = json.loads(route.post(row_refs=True))
    assert off["candidate_count"] > 0
    for key in ("candidate_count", "state_last_updated", "snapshot_generated_at", "dates_covered",
                "line_moves_tracked", "debug_source"):
        assert on.get(key) == off.get(key), key


def test_the_route_rebuild_is_the_flag_off_response(route, monkeypatch):
    """End to end through hydrate -> slim -> drop -> encode -> provider."""
    monkeypatch.delenv(rr.ENV_SWITCH, raising=False)
    off = json.loads(route.post())["response"]
    on = json.loads(route.post(row_refs=True))["response"]
    assert _in_order(rr.decode_row_refs(on)) == _in_order(off)


# --------------------------------------------------------------------------
# 2. The saving is real.
# --------------------------------------------------------------------------


def test_the_recorded_slice_shrinks_by_more_than_half():
    doc = _recorded()
    off = _wire(doc)
    on_doc = dict(doc)
    on_doc["response"] = rr.encode_row_refs(doc["response"], sort_keys=True)
    on = _wire(on_doc)
    # Full recorded response: 41.3% (80,281,791 -> 33,144,917). The slice keeps
    # fewer top rows per ranked row, so it is held to a looser bound.
    assert len(on) < 0.55 * len(off), (len(on), len(off))


def test_the_route_serves_fewer_bytes_with_the_flag(route, monkeypatch):
    monkeypatch.delenv(rr.ENV_SWITCH, raising=False)
    assert len(route.post(row_refs=True)) < 0.55 * len(route.post())


# --------------------------------------------------------------------------
# 3. Equivalence on the recorded slice: Python reference, then the page's JS.
# --------------------------------------------------------------------------


def test_python_rebuild_of_the_recorded_slice_is_byte_identical():
    doc = _recorded()
    off = json.loads(_wire(doc))
    on_doc = dict(doc)
    on_doc["response"] = rr.encode_row_refs(doc["response"], sort_keys=True)
    on = json.loads(_wire(on_doc))
    rr.decode_row_refs(on["response"])
    assert _in_order(on) == _in_order(off)


def test_the_recorded_slice_exercises_every_encoding_case():
    """The fixture must keep covering what the full response had, or the
    equivalence above proves less than it says."""
    refs = rr.encode_row_refs(_recorded()["response"], sort_keys=True)[rr.RESPONSE_KEY]
    top, live, cards = refs["top_opportunities"], refs["top_live_opportunities"], refs["board_contract.cards"]
    assert all(top["patch"]), "every top row adds keys (rationale, pick, ...)"
    assert "rationale" in top["patch"][0]
    assert any(p and "quote" in p for p in live["patch"]), "top_live keeps its unstripped quote"
    assert cards.get("drop"), "some cards lack a key their ranked row has (actual)"
    assert any(p is None for p in cards["patch"]) and any(p for p in cards["patch"])
    assert "home_logo" not in cards["order"], "a base-only key is never emitted"
    assert all(i is not None for i in top["index"] + live["index"] + cards["index"])


HARNESS = r"""
import fs from 'fs';
const html = fs.readFileSync(process.argv[2], 'utf8').split('\r\n').join('\n');
const start = html.indexOf('  function rehydrateAliases(payload) {');
const end = html.indexOf('  rehydrateAliases(initialIntelligenceResponse);', start);
if (start < 0 || end < 0) throw new Error('rehydrateAliases not found in the template');
const rehydrateAliases = new Function(html.slice(start, end) + '\nreturn rehydrateAliases;')();
function rebuilt(p) {
  const doc = JSON.parse(fs.readFileSync(p, 'utf8'));
  rehydrateAliases(doc.response);
  return JSON.stringify(doc);
}
const off = rebuilt(process.argv[3]), on = rebuilt(process.argv[4]);
let i = 0; while (i < off.length && off[i] === on[i]) i++;
console.log(JSON.stringify({ identical: off === on, length: off.length, firstDiff: off === on ? null : i,
  off: off.slice(Math.max(0, i - 80), i + 80), on: on.slice(Math.max(0, i - 80), i + 80) }));
"""


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_the_pages_own_rehydrate_makes_the_flag_on_payload_identical(tmp_path):
    """The real `rehydrateAliases`, sliced from the template, run on both wire
    payloads: JSON.stringify must match byte for byte (key order included), with
    the per-row aliases, the top-level aliases and the by_sport rebuild all live."""
    doc = _recorded()
    on_doc = dict(doc)
    on_doc["response"] = rr.encode_row_refs(doc["response"], sort_keys=True)
    off_path, on_path = tmp_path / "off.json", tmp_path / "on.json"
    off_path.write_text(_wire(doc), encoding="ascii")
    on_path.write_text(_wire(on_doc), encoding="ascii")
    script = tmp_path / "harness.mjs"
    script.write_text(HARNESS, encoding="utf-8")
    proc = subprocess.run([NODE, str(script), str(TEMPLATE), str(off_path), str(on_path)],
                          capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr
    result = json.loads(proc.stdout)
    assert result["identical"], result


def test_the_page_asks_for_row_refs_and_rebuilds_before_the_row_aliases():
    """The rebuild must run before `_dropped_row_aliases` restores `game_pk` /
    `market_key` / `selection`, or the rebuilt lists miss them."""
    html = TEMPLATE.read_text(encoding="utf-8")
    payload_fn = html[html.index("function intelligenceQueryPayload"):]
    assert "row_refs: true," in payload_fn[:payload_fn.index("return payload;")]
    body = html[html.index("function rehydrateAliases(payload) {"):]
    assert body.index("payload._response_row_refs") < body.index("payload._dropped_row_aliases")


# --------------------------------------------------------------------------
# 4. Edge cases: each must cost bytes, never data.
# --------------------------------------------------------------------------


def _rows():
    ranked = [
        {"pick_id": "a", "sport": "nba", "edge": 1.5, "quote": {"price": -110, "book": "x"}, "n": 1},
        {"pick_id": "b", "sport": "nfl", "edge": 0.0, "quote": {"price": 120, "book": "y"}, "n": 2},
        {"pick_id": "c", "sport": "nhl", "edge": 2.0, "quote": {"price": 100, "book": "z"}, "n": 3},
    ]
    return ranked


def _roundtrip(resp, *, sort_keys=True):
    """Encode, send, parse, rebuild -- and the flag-off parse to compare with."""
    from syndicate.features.shared.json_safety import json_safe_value

    def dump(obj):
        return json.dumps(json_safe_value(obj), sort_keys=sort_keys, separators=(",", ":"))

    enc = rr.encode_row_refs(resp, sort_keys=sort_keys)
    off = json.loads(dump(resp))
    on = json.loads(dump(enc))
    return enc, off, rr.decode_row_refs(on)


def test_a_row_without_a_base_travels_whole():
    ranked = _rows()
    resp = {"ranked_all": ranked, "top_opportunities": [dict(ranked[0]), {"sport": "mlb", "n": 9}]}
    enc, off, rebuilt = _roundtrip(resp)
    spec = enc[rr.RESPONSE_KEY]["top_opportunities"]
    assert spec["index"] == [0, None]
    assert spec["patch"][1] == {"sport": "mlb", "n": 9}
    assert _in_order(rebuilt) == _in_order(off)


def test_a_duplicated_pick_id_references_nothing():
    ranked = _rows() + [dict(_rows()[0], n=99)]
    resp = {"ranked_all": ranked, "top_opportunities": [dict(ranked[0])]}
    enc, off, rebuilt = _roundtrip(resp)
    assert enc[rr.RESPONSE_KEY]["top_opportunities"]["index"] == [None]
    assert _in_order(rebuilt) == _in_order(off)


@pytest.mark.parametrize("base_value,row_value", [
    (1, 1.0),            # int vs float: == but serialise differently
    (1, True),           # int vs bool
    (0.0, -0.0),         # == but "-0.0"
    (float("nan"), float("nan")),
    ({"a": 1, "b": 2}, {"b": 2, "a": 1}),   # same items, other order
    ([1, 2], (1, 2)),
])
def test_values_python_calls_equal_are_still_patched(base_value, row_value):
    assert rr._same_on_wire(base_value, row_value) is False
    ranked = [{"pick_id": "a", "v": base_value}]
    enc = rr.encode_row_refs({"ranked_all": ranked, "top_opportunities": [{"pick_id": "a", "v": row_value}]})
    patch = enc[rr.RESPONSE_KEY]["top_opportunities"]["patch"][0]
    assert list(patch) == ["v"] and patch["v"] is row_value


def test_identical_values_are_not_patched_and_drops_are_recorded():
    ranked = _rows()
    card = {k: v for k, v in ranked[1].items() if k != "n"}
    card["gate"] = "open"
    resp = {"ranked_all": ranked, "board_contract": {"cards": [dict(ranked[0]), card], "schema": "v1"}}
    enc, off, rebuilt = _roundtrip(resp)
    spec = enc[rr.RESPONSE_KEY]["board_contract.cards"]
    assert spec["patch"] == [None, {"gate": "open"}]
    assert spec["drop"] == {"1": ["n"]}
    assert enc["board_contract"]["cards"] is None and enc["board_contract"]["schema"] == "v1"
    assert _in_order(rebuilt) == _in_order(off)


def test_unsorted_provider_keeps_each_rows_own_order():
    ranked = [{"pick_id": "a", "z": 1, "y": 2}, {"pick_id": "b", "z": 3, "y": 4}]
    top = [{"pick_id": "a", "z": 1, "extra": 5, "y": 2}, {"pick_id": "b", "z": 3, "y": 4}]
    enc, off, rebuilt = _roundtrip({"ranked_all": ranked, "top_opportunities": top}, sort_keys=False)
    assert enc[rr.RESPONSE_KEY]["top_opportunities"]["order"] == ["pick_id", "z", "extra", "y"]
    assert _in_order(rebuilt) == _in_order(off)


def test_rows_that_disagree_on_key_order_are_sent_in_full_when_order_matters():
    ranked = [{"pick_id": "a", "x": 1, "y": 2}, {"pick_id": "b", "x": 1, "y": 2}]
    top = [{"pick_id": "a", "x": 1, "y": 2}, {"pick_id": "b", "y": 2, "x": 1}]
    resp = {"ranked_all": ranked, "top_opportunities": top}
    assert rr.encode_row_refs(resp, sort_keys=False) is resp
    assert rr.RESPONSE_KEY in rr.encode_row_refs(resp, sort_keys=True)


@pytest.mark.parametrize("resp", [
    {"top_opportunities": [{"pick_id": "a"}]},                                  # no ranked_all
    {"ranked_all": [], "top_opportunities": [{"pick_id": "a"}]},                # empty source
    {"ranked_all": [{"pick_id": "a"}, "x"], "top_opportunities": [{"pick_id": "a"}]},  # non-dict source row
    {"ranked_all": [{"pick_id": "a"}], "top_opportunities": [{"pick_id": "a"}, 3]},    # non-dict list row
    {"ranked_all": [{"pick_id": "a"}], "top_opportunities": []},
])
def test_what_cannot_be_encoded_is_returned_unchanged(resp):
    assert rr.encode_row_refs(resp) is resp


def test_the_input_is_not_mutated():
    doc = _recorded()["response"]
    before = _in_order(doc)
    rr.encode_row_refs(doc, sort_keys=True)
    assert _in_order(doc) == before
