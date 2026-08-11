"""`#350` — the projection-age vars must be DECLARED, not just referenced.

I shipped a template that USED `projAge`/`projStale` at the Proj cell and never
declared them: `ReferenceError: projAge is not defined` on first paint, which
would have broken the entire Layer 1 board render for every sport.

Every other test in `test_projection_age.py` passed on that template, because
substring assertions confirm a token EXISTS and say nothing about whether it is
BOUND. Same class as the NFL segment fetch that used `requests`,
`get_base_url` and `record_oddsapi_quota` while importing none of them, and as
the auto-refresh regression where structural tests could not see a missing
behaviour. Third instance this session; the rule is assert on binding and
ordering, not on text.

Deliberately NOT a general "no variable used before declaration" sweep. Tried
that first: `edgeWhy` and `priced` both appear in comments and parameter lists
before their `var`, which a text scan cannot tell from a real use. A check that
cries wolf gets muted, so this asserts only what it can actually establish.
"""

from __future__ import annotations

import pathlib

_TEMPLATE = pathlib.Path(__file__).resolve().parents[1] / "syndicate" / "templates" / "shared" / "layer1_board.html"


def _occurrences(haystack: str, needle: str) -> list[int]:
    out: list[int] = []
    start = 0
    while True:
        idx = haystack.find(needle, start)
        if idx == -1:
            return out
        out.append(idx)
        start = idx + 1


def test_projection_age_vars_are_declared_before_they_are_used():
    html = _TEMPLATE.read_text(encoding="utf-8")
    for name in ("projAge", "projStale"):
        decl = html.find("var " + name)
        assert decl != -1, f"{name} is never declared -- this is the ReferenceError"
        uses = [i for i in _occurrences(html, name) if html[max(0, i - 4):i] != "var "]
        assert uses, f"{name} is declared but never used -- a field nothing renders is invisible"
        assert decl < min(uses), (
            f"{name} used at char {min(uses)} before its declaration at char {decl}"
        )


def test_the_board_actually_reads_the_age_field():
    # The payload half is worthless if the view ignores it: a 22-day-old sim and
    # a fresh one looked identical precisely because nothing rendered the age.
    html = _TEMPLATE.read_text(encoding="utf-8")
    assert "p.age_hours" in html
    assert "projAge >= 24" in html, "the staleness threshold is not applied"
    assert 'projStale ? " *"' in html, "staleness is not visible in the cell text"
