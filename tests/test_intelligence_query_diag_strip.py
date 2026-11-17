"""`drop_row_diagnostics` also strips `top_live_opportunities` and drops `rationale` (lane board-query-diag-strip, todo #827).

MEASURED on the fleet's recorded `/api/intelligence/query`, 2026-11-16 7:48 PM CST (the page's own
request), with the change applied exactly as it lands
(`.syndicate/findings_2026-11-17_board_query_diag_strip.md`):

                     before         after
    row_refs on   33,144,917 ->  25,559,058 B raw    5,689,938 -> 4,575,384 B gzip-1
    row_refs off  80,281,791 ->  73,750,559 B raw   14,383,596 -> 13,628,477 B gzip-1

`top_live_opportunities` was never in `_DIAGNOSTIC_ROW_LISTS`, so its 2,176 rows kept `trace`,
`score_breakdown`, the unconsumed `quote` fields, the all-null `movement` fields and the rebuildable
aliases; `rationale` (4.2 MB over the two top lists) had no reader in any sender of the flag.

ORDER, as `learnings.md` asks: reachability first (off != on through the real route, for BOTH changes,
and against the old constants), then the saving, then that nothing else is lost (the page's real
`rehydrateAliases` under node brings every alias back and `row_refs` stays lossless), then the consumer
survey re-proved against every sender of the flag, so the next reader fails a test instead of a card.
"""

from __future__ import annotations

import copy
import json
import re
import shutil
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from syndicate.blueprints import intelligence as intel
from syndicate.features.shared import response_row_refs as rr

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "intelligence_query_row_refs_sample.json"
TEMPLATE = ROOT / "syndicate" / "templates" / "intelligence.html"
NODE = shutil.which("node")

#: The constants before this lane, to prove the change itself is what moves the payload.
OLD_LISTS = ("top_opportunities", "ranked_all", "recommendations")
OLD_FIELDS = ("trace", "score_breakdown")


def _recorded() -> dict:
    # A slice of the recorded fleet response (lane board-query-row-refs): its top_live rows were
    # never stripped, and its top rows carry `rationale`, exactly as the fleet served them.
    return json.loads(FIXTURE.read_text(encoding="ascii"))


class _Route:
    """The real `/api/intelligence/query` combined-board exit, fed the recorded board."""

    def __init__(self):
        from syndicate.app import create_app

        app = create_app()
        app.testing = True
        self.client = app.test_client()

    def post(self, **flags) -> str:
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


@pytest.fixture(autouse=True)
def _row_refs_env_absent(monkeypatch):
    monkeypatch.delenv(rr.ENV_SWITCH, raising=False)


# --------------------------------------------------------------------------
# 1. Reachability: off != on, for both changes, through the real route.
# --------------------------------------------------------------------------


def test_the_input_carries_what_the_change_drops():
    """A null needs a live population: the recorded slice must carry the fields, or every
    "absent after" below would pass with no change at all."""
    resp = _recorded()["response"]
    live = resp["top_live_opportunities"]
    assert live and all("trace" in r and "score_breakdown" in r and "rationale" in r for r in live)
    assert any(set(intel._UNCONSUMED_QUOTE_FIELDS) & set(r.get("quote") or {}) for r in live)
    assert any(r.get("game_pk") == r.get("event_id") and "game_pk" in r for r in live)
    assert all("rationale" in r for r in resp["top_opportunities"])


def test_off_and_on_differ_through_the_route(route):
    off = json.loads(route.post(drop_row_diagnostics=False))["response"]
    on = json.loads(route.post())["response"]

    assert all("rationale" in r for r in off["top_opportunities"])
    assert all("trace" in r and "rationale" in r for r in off["top_live_opportunities"])

    assert len(on["top_live_opportunities"]) == len(off["top_live_opportunities"])
    for key in ("top_opportunities", "top_live_opportunities", "ranked_all"):
        for row in on[key]:
            for name in intel._UNCONSUMED_ROW_DIAGNOSTICS:
                assert name not in row, (key, name)
    for row in on["top_live_opportunities"]:
        assert not set(intel._UNCONSUMED_QUOTE_FIELDS) & set(row.get("quote") or {})
        movement = row.get("movement") or {}
        assert not any(k in movement and movement[k] is None for k in intel._ALL_NULL_MOVEMENT_FIELDS)
    assert "rationale" in on["_dropped_row_fields"]


def test_the_old_constants_left_top_live_and_rationale_alone(route, monkeypatch):
    """The change, not something else in the route, is what strips them."""
    monkeypatch.setattr(intel, "_DIAGNOSTIC_ROW_LISTS", OLD_LISTS)
    monkeypatch.setattr(intel, "_UNCONSUMED_ROW_DIAGNOSTICS", OLD_FIELDS)
    old = json.loads(route.post())["response"]
    assert all("trace" in r and "rationale" in r for r in old["top_live_opportunities"])
    assert all("rationale" in r for r in old["top_opportunities"])


def test_top_live_aliases_are_dropped_and_declared(route):
    on = json.loads(route.post())["response"]
    raw = _recorded()["response"]["top_live_opportunities"]
    declared = on["_dropped_row_aliases"]
    dropped = 0
    for before, after in zip(raw, on["top_live_opportunities"]):
        for alias, canonical in declared.items():
            if alias in before and canonical in before and before[alias] == before[canonical]:
                assert alias not in after, alias
                dropped += 1
    assert dropped > 0


# --------------------------------------------------------------------------
# 2. The saving is real.
# --------------------------------------------------------------------------


@pytest.mark.parametrize("row_refs", [False, True])
def test_the_route_serves_fewer_bytes_than_with_the_old_constants(route, monkeypatch, row_refs):
    new = len(route.post(row_refs=row_refs))
    monkeypatch.setattr(intel, "_DIAGNOSTIC_ROW_LISTS", OLD_LISTS)
    monkeypatch.setattr(intel, "_UNCONSUMED_ROW_DIAGNOSTICS", OLD_FIELDS)
    old = len(route.post(row_refs=row_refs))
    # Full recorded response: 0.919 without row_refs and 0.771 with it. The slice keeps more
    # top_live rows per ranked row than the full response, so the bounds are its own.
    bound = 0.80 if row_refs else 0.92
    assert new < bound * old, (new, old, round(new / old, 3))


# --------------------------------------------------------------------------
# 3. Nothing else is lost: the page's own rebuild, and row_refs stays lossless.
# --------------------------------------------------------------------------


def test_the_page_restores_aliases_on_every_list_the_server_strips():
    """The server strips `_DIAGNOSTIC_ROW_LISTS` and the page restores aliases on its own list:
    the two must name the same lists, or an alias drop on one list comes back on none."""
    html = TEMPLATE.read_text(encoding="utf-8").replace("\r\n", "\n")
    start = html.index("  function rehydrateAliases(payload) {")
    body = html[start:html.index("  rehydrateAliases(initialIntelligenceResponse);", start)]
    m = re.search(r"const lists = \[([^\]]*)\];", body)
    assert m, "the row-alias list in rehydrateAliases moved"
    page_lists = set(re.findall(r'"([a-z_]+)"', m.group(1)))
    assert page_lists == set(intel._DIAGNOSTIC_ROW_LISTS)


HARNESS = r"""
import fs from 'fs';
const [tpl, rawP, offP, onP] = process.argv.slice(2);
const html = fs.readFileSync(tpl, 'utf8').split('\r\n').join('\n');
const start = html.indexOf('  function rehydrateAliases(payload) {');
const end = html.indexOf('  rehydrateAliases(initialIntelligenceResponse);', start);
if (start < 0 || end < 0) throw new Error('rehydrateAliases not found in the template');
const rehydrateAliases = new Function(html.slice(start, end) + '\nreturn rehydrateAliases;')();
const load = (p) => { const d = JSON.parse(fs.readFileSync(p, 'utf8')); rehydrateAliases(d.response); return d.response; };
const raw = load(rawP), off = load(offP), on = load(onP);
const stable = (v) => JSON.stringify(v, (k, x) => (x && typeof x === 'object' && !Array.isArray(x))
  ? Object.keys(x).sort().reduce((o, kk) => { o[kk] = x[kk]; return o; }, {}) : x);
const dRow = new Set(off._dropped_row_fields || []), dQuote = new Set(off._dropped_quote_fields || []);
const dMove = new Set(off._dropped_movement_fields || []);
const out = { refsIdentical: JSON.stringify(off) === JSON.stringify(on), lists: {} };
const get = { ranked_all: (r) => r.ranked_all, top_opportunities: (r) => r.top_opportunities,
  top_live_opportunities: (r) => r.top_live_opportunities, cards: (r) => (r.board_contract || {}).cards };
for (const [name, g] of Object.entries(get)) {
  const b = g(raw) || [], a = g(off) || [];
  const s = { rows: [b.length, a.length], lost: [], changed: [], added: [], dropped: 0 };
  b.forEach((br, i) => {
    const ar = a[i] || {};
    for (const k of Object.keys(br)) {
      if (dRow.has(k)) { s.dropped++; continue; }
      if (!(k in ar)) { s.lost.push(k); continue; }
      let bv = br[k];
      if ((k === 'quote' || k === 'movement') && bv && typeof bv === 'object') {
        bv = Object.fromEntries(Object.entries(bv).filter(([kk, vv]) =>
          !(k === 'quote' ? dQuote.has(kk) : (dMove.has(kk) && vv === null))));
      }
      if (stable(bv) !== stable(ar[k])) s.changed.push(k);
    }
    for (const k of Object.keys(ar)) if (!(k in br)) s.added.push(k);
  });
  out.lists[name] = s;
}
console.log(JSON.stringify(out));
"""


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_the_pages_own_rehydrate_loses_only_the_declared_fields(route, tmp_path):
    """The real `rehydrateAliases`, sliced from the template, on three route responses: the flag
    off, on, and on with `row_refs`. On vs off: every row of every list differs ONLY by the declared
    drops -- each top_live alias comes back with its value -- and `row_refs` rebuilds the flag-on
    payload byte for byte."""
    paths = {}
    for name, flags in (("raw", {"drop_row_diagnostics": False}), ("off", {}), ("on", {"row_refs": True})):
        paths[name] = tmp_path / f"{name}.json"
        paths[name].write_text(route.post(**flags), encoding="utf-8")
    script = tmp_path / "harness.mjs"
    script.write_text(HARNESS, encoding="utf-8")
    proc = subprocess.run([NODE, str(script), str(TEMPLATE), str(paths["raw"]), str(paths["off"]), str(paths["on"])],
                          capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr
    result = json.loads(proc.stdout)
    assert result["refsIdentical"], result
    for name, s in result["lists"].items():
        assert s["rows"][0] == s["rows"][1] and s["rows"][0] > 0, (name, s["rows"])
        assert not s["lost"] and not s["changed"] and not s["added"], (name, s)
    assert result["lists"]["top_live_opportunities"]["dropped"] > 0
    assert result["lists"]["top_opportunities"]["dropped"] > 0


# --------------------------------------------------------------------------
# 4. The survey, re-proved against every sender of the flag on every run.
# --------------------------------------------------------------------------

#: Every file that SENDS `drop_row_diagnostics: true`, and the files its rows flow into. A new sender
#: fails `test_every_sender_of_the_flag_is_surveyed` until it is surveyed and added here.
SENDERS = {
    "syndicate/templates/intelligence.html": (),  # + the scripts it loads, found from the template
    "scripts/build_cheat_sheets.py": (
        "syndicate/features/shared/cheat_sheets.py",
        "syndicate/features/shared/cheat_sheet_record.py",
    ),
    "scripts/layer2_rail_monitor_probe.py": (
        "scripts/layer2_rail_monitor_run.mjs",
        "scripts/layer2_rail_flag_grade.py",
    ),
    "scripts/verify_layer2_row_parity.py": (),
}
_SENDS = re.compile(r"""["']?drop_row_diagnostics["']?\s*:\s*(?:True|true)\b""")


def _read_forms(name: str) -> re.Pattern:
    """A READ of a field, in every form these files use: `.name`, `["name"]` / `.get("name")` /
    `"name" in row` (any quoted literal)."""
    n = re.escape(name)
    return re.compile(rf"""\.{n}\b|["']{n}["']""")


def _page_scripts() -> list[str]:
    html = TEMPLATE.read_text(encoding="utf-8")
    files = []
    m = re.search(r"""\{%\s*extends\s+["']([^"']+)["']""", html)
    sources = [html] + ([(ROOT / "syndicate" / "templates" / m.group(1)).read_text(encoding="utf-8")] if m else [])
    for text in sources:
        for js in re.findall(r"""filename=['"]([^'"]+\.js)['"]""", text):
            files.append(f"syndicate/static/{js}")
    return files


def _consumers() -> dict[str, list[str]]:
    out = {s: [s, *rest] for s, rest in SENDERS.items()}
    out["syndicate/templates/intelligence.html"] += _page_scripts()
    return out


def test_every_sender_of_the_flag_is_surveyed():
    found = set()
    for top in ("syndicate", "scripts"):
        for path in (ROOT / top).rglob("*"):
            if path.suffix not in (".py", ".html", ".js", ".mjs") or not path.is_file():
                continue
            rel = path.relative_to(ROOT).as_posix()
            if rel == "syndicate/blueprints/intelligence.py":  # the server, which documents the flag
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            if "drop_row_diagnostics" in text and _SENDS.search(text):
                found.add(rel)
    assert found == set(SENDERS), (
        "a sender of drop_row_diagnostics was added or removed; survey what it reads for every name "
        "in _UNCONSUMED_ROW_DIAGNOSTICS and every list in _DIAGNOSTIC_ROW_LISTS, then update SENDERS: "
        f"{sorted(found ^ set(SENDERS))}"
    )


def test_the_survey_can_see_a_read():
    """Positive control: the same patterns find reads that are known to exist, so a 0 below means
    the name is absent, not that the pattern is blind."""
    page = _consumers()["syndicate/templates/intelligence.html"]
    assert len(page) > 3, page  # the template, its base's scripts and its own
    page_text = (ROOT / page[0]).read_text(encoding="utf-8")
    assert _read_forms("board_score_components").search(page_text)
    cheat = (ROOT / "syndicate/features/shared/cheat_sheets.py").read_text(encoding="utf-8")
    assert _read_forms("fair_probability").search(cheat)
    probe = (ROOT / "scripts/layer2_rail_monitor_run.mjs").read_text(encoding="utf-8")
    assert _read_forms("top_opportunities").search(probe)


def test_no_sender_reads_a_dropped_row_field():
    """`rationale` joined `trace` / `score_breakdown` on a survey of four senders. A proof of
    "unreferenced" expires when a consumer changes (`quote_seen_age_seconds`, 2026-10-02)."""
    hits = []
    for sender, files in _consumers().items():
        for rel in files:
            text = (ROOT / rel).read_text(encoding="utf-8", errors="replace")
            for name in intel._UNCONSUMED_ROW_DIAGNOSTICS:
                for m in _read_forms(name).finditer(text):
                    hits.append(f"{rel}:{text.count(chr(10), 0, m.start()) + 1} reads {name} (sender {sender})")
    assert not hits, hits


def test_no_reader_of_top_live_reads_a_dropped_quote_field():
    """`top_live_opportunities` is stripped like the other lists now. Today no sender reads the list
    at all; one that starts to must not read what the strip removes from its `quote`."""
    hits = []
    for sender, files in _consumers().items():
        texts = {rel: (ROOT / rel).read_text(encoding="utf-8", errors="replace") for rel in files}
        if not any(_read_forms("top_live_opportunities").search(t) for t in texts.values()):
            continue
        for rel, text in texts.items():
            for name in intel._UNCONSUMED_QUOTE_FIELDS:
                if _read_forms(name).search(text):
                    hits.append(f"{rel} reads quote.{name} and {sender} reads top_live_opportunities")
    assert not hits, hits
