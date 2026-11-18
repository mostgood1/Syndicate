"""The cheat sheets' board pull asks for `row_refs` and rebuilds the cards (lane cheat-sheet-picks-row-refs, 2026-11-17).

`SyndicateCheatSheetPicks` pulls the board query every 15 minutes, and the full build pulls it too. Measured on the
fleet 2026-11-18, through `fetch_board_cards`: 12,848,512 -> 4,521,512 B per call on the wire (gzip, from the opener
`import syndicate` installs), and 69,000,099 -> 24,516,064 B for web to serialise (one board state).

The picks must not move -- every line is its own decision -- so these tests hold the rebuilt cards, and the picks
built from them, to the flag-off read with key order included. The data is the recorded fleet slice
(`tests/fixtures/intelligence_query_row_refs_sample.json`, lane board-query-row-refs).
"""
from __future__ import annotations

import importlib.util
import io
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from syndicate.features.shared import response_row_refs as rr
from syndicate.features.shared.json_safety import json_safe_value

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "intelligence_query_row_refs_sample.json"
SPORTS = ("nfl", "ncaaf", "nhl", "soccer", "nba", "ncaab", "wnba", "mlb")
DAYS = ("2026-11-16", "2026-11-17", "2026-11-22")  # the slice's card dates, plus the day after
BASE = "http://board.test"


def _script():
    spec = importlib.util.spec_from_file_location("build_cheat_sheets", ROOT / "scripts" / "build_cheat_sheets.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _recorded() -> dict:
    return json.loads(FIXTURE.read_text(encoding="ascii"))


def _wire(obj) -> bytes:
    """What Flask's provider sends: json_safe, sorted keys, compact, ASCII."""
    return json.dumps(json_safe_value(obj), sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode("ascii")


def _in_order(obj) -> str:
    """Serialise WITHOUT sorting, so a key-order difference is a difference."""
    return json.dumps(obj, ensure_ascii=True, separators=(",", ":"))


class _Server:
    """`/api/intelligence/query` as this client sees it: the flag honoured or not, the body served."""

    def __init__(self, doc, *, honour=True, encode=None):
        self.doc, self.honour = doc, honour
        self.encode = encode or (lambda response: rr.encode_row_refs(response, sort_keys=True))
        self.requests, self.served = [], []

    def __call__(self, req, timeout=None):
        body = json.loads(req.data.decode("utf-8"))
        self.requests.append((req.full_url, body, timeout))
        doc = dict(self.doc)
        if self.honour and rr.row_refs_requested(body):
            doc["response"] = self.encode(self.doc["response"])
        raw = _wire(doc)
        self.served.append(len(raw))
        return io.BytesIO(raw)


def _flag_off_cards(doc) -> list:
    """What `fetch_board_cards` returned before the flag: the full response's cards, as parsed off the wire."""
    full = json.loads(_wire(doc))
    return [c for c in full["response"]["board_contract"]["cards"] if isinstance(c, dict)]


@pytest.fixture
def builder(monkeypatch):
    monkeypatch.delenv(rr.ENV_SWITCH, raising=False)
    return _script()


def _serve(monkeypatch, module, server):
    monkeypatch.setattr(module.urllib.request, "urlopen", server)
    return server


def test_the_pull_asks_for_row_refs_and_nothing_else_in_the_request_changes(builder, monkeypatch):
    server = _serve(monkeypatch, builder, _Server(_recorded()))
    builder.fetch_board_cards(BASE)
    (url, body, timeout), = server.requests
    assert url == f"{BASE}/api/intelligence/query" and timeout == 300
    assert body == {"question": "top edges today", "mode": "recommendation", "timing": "all", "background": False,
                    "force_refresh": False, "slim_aliases": False, "drop_row_diagnostics": True, "row_refs": True}


def test_the_rebuilt_cards_are_identical_to_the_flag_off_read(builder, monkeypatch):
    doc = _recorded()
    server = _serve(monkeypatch, builder, _Server(doc))
    cards = builder.fetch_board_cards(BASE)
    # Reachability: the cards really travelled as references, and the body was smaller (off != on).
    encoded = json.loads(_wire(dict(doc, response=rr.encode_row_refs(doc["response"], sort_keys=True))))
    assert encoded["response"]["board_contract"]["cards"] is None
    assert "board_contract.cards" in encoded["response"][rr.RESPONSE_KEY]
    assert server.served[0] < 0.55 * len(_wire(doc)), (server.served[0], len(_wire(doc)))
    off = _flag_off_cards(doc)
    assert len(cards) == len(off) == 17
    assert _in_order(cards) == _in_order(off)


@pytest.mark.parametrize("refusal", ["route ignores the flag", "server switch off"])
def test_a_server_that_does_not_honour_the_flag_gives_the_same_cards(builder, monkeypatch, refusal):
    doc = _recorded()
    if refusal == "server switch off":
        monkeypatch.setenv(rr.ENV_SWITCH, "off")
    server = _serve(monkeypatch, builder, _Server(doc, honour=refusal != "route ignores the flag"))
    cards = builder.fetch_board_cards(BASE)
    assert server.served == [len(_wire(doc))]  # the full body: nothing was encoded
    assert _in_order(cards) == _in_order(_flag_off_cards(doc))


def test_the_picks_built_from_the_rebuilt_cards_are_identical(builder, monkeypatch):
    doc = _recorded()
    _serve(monkeypatch, builder, _Server(doc))
    cards, off = builder.fetch_board_cards(BASE), _flag_off_cards(doc)
    now = datetime(2026, 11, 17, 2, 45, tzinfo=timezone.utc)
    built = 0
    for sport in SPORTS:
        for day in DAYS:
            before = builder.build_picks(off, {"rows": []}, sport=sport, day=day, now=now)
            after = builder.build_picks(cards, {"rows": []}, sport=sport, day=day, now=now)
            assert _in_order(after) == _in_order(before), (sport, day)
            built += len(before)
    # Positive control: the slice yields picks, so the equality above is not over empty lists.
    assert built > 0


def test_encoded_cards_that_do_not_rebuild_raise_instead_of_reading_as_an_empty_board(builder, monkeypatch):
    """An empty card list would make `merge_picks` mark every pick off the board on every picks run. A raise takes
    the path a failed read already takes."""

    def broken(response):
        out = rr.encode_row_refs(response, sort_keys=True)
        out[rr.RESPONSE_KEY]["board_contract.cards"]["from"] = "no_such_list"
        return out

    _serve(monkeypatch, builder, _Server(_recorded(), encode=broken))
    with pytest.raises(ValueError, match="did not rebuild"):
        builder.fetch_board_cards(BASE)
