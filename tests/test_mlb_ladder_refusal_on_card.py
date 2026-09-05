"""A REFUSED over-probability must read differently on the card from an ABSENT one.

`462d8d6c` made the DATA distinguish the two (`overLineProbRefused`), but every
consumer rendered both through `format_pct`, which returns `-` for each — so the
label was unread and the reader still could not tell "the book quotes no line"
from "the sim was certain and we refuse to publish it".

The CONTROLS matter as much as the new behaviour here: an absent line and a
healthy probability must render EXACTLY as they did before, or this change is a
UI regression wearing a fix's clothes.
"""

from __future__ import annotations

from syndicate.features.mlb.ladders_common import (
    hitter_rows_from_summary,
    pitcher_rows_from_summary,
)

REFUSED = {
    "hitterName": "Zero Batter", "pitcherName": "Zero Arm", "team": "AAA",
    "mean": 0.0, "mode": 0, "simCount": 1000, "marketLine": 0.5,
    "overLineProb": None,
    "overLineProbRefused": "exact_certainty",
    "overLineProbRefusedValue": 0.0,
}
ABSENT = {
    "hitterName": "No Line", "pitcherName": "No Line", "team": "BBB",
    "mean": 1.2, "mode": 1, "simCount": 1000, "marketLine": None,
    "overLineProb": None,
}
HEALTHY = {
    "hitterName": "Real Bat", "pitcherName": "Real Arm", "team": "CCC",
    "mean": 1.25, "mode": 1, "simCount": 1000, "marketLine": 0.5,
    "overLineProb": 0.736,
}


def _rows(builder, row):
    # The two builders read DIFFERENT keys: hitter -> groups.hitter.hits,
    # pitcher -> groups.pitcher.strikeouts. Getting this wrong makes the
    # builder return no rows, which fails every assertion including the
    # controls -- which is how this fixture bug was caught.
    group = {"prop": "hits", "propLabel": "Hits", "rows": [row]}
    summary = {
        "groups": {
            "hitter": {"hits": group},
            "pitcher": {"strikeouts": group},
        }
    }
    out, _label = builder(summary)
    return out


def _over_metric(card):
    return next(m["value"] for m in card["metrics"] if m["label"] == "Over")


def _over_item(card):
    return next((i for i in card["list_items"] if str(i).startswith("Over probability:")), None)


def _cards(row):
    """Both render sites. They are duplicated, so both must be asserted."""
    h = _rows(hitter_rows_from_summary, row)
    p = _rows(pitcher_rows_from_summary, row)
    assert h and p, "fixture produced no card"
    return {"hitter": h[0], "pitcher": p[0]}


def test_refused_over_probability_is_not_rendered_as_a_bare_dash():
    """REACHABILITY: fails on the unfixed code, which renders '-'."""
    for side, card in _cards(REFUSED).items():
        assert _over_metric(card) != "-", (
            f"{side} card rendered a refused certainty as a bare '-', "
            "indistinguishable from a missing market line"
        )


def test_refused_row_says_why_in_the_list_item():
    for side, card in _cards(REFUSED).items():
        item = _over_item(card)
        assert item is not None, f"{side} card lost its Over probability line"
        assert item != "Over probability: -", f"{side} still renders the bare dash"
        low = item.lower()
        assert "refus" in low or "certain" in low, (
            f"{side} list item does not say WHY it is blank: {item!r}"
        )


def test_refused_and_absent_render_differently():
    """The whole point. If these two match, the label is still unread."""
    refused, absent = _cards(REFUSED), _cards(ABSENT)
    for side in ("hitter", "pitcher"):
        assert _over_metric(refused[side]) != _over_metric(absent[side])
        assert _over_item(refused[side]) != _over_item(absent[side])


def test_absent_line_still_renders_exactly_as_before():
    """CONTROL: passes BEFORE and after. No line is not a refusal."""
    for side, card in _cards(ABSENT).items():
        assert _over_metric(card) == "-", f"{side} changed the absent-line rendering"
        assert _over_item(card) == "Over probability: -"


def test_healthy_probability_still_renders_exactly_as_before():
    """CONTROL: passes BEFORE and after. A real number must be untouched."""
    for side, card in _cards(HEALTHY).items():
        assert _over_metric(card) == "73.6%", f"{side} changed a healthy rendering"
        assert _over_item(card) == "Over probability: 73.6%"


def test_other_metrics_survive_on_a_refused_row():
    """Only the probability is refused; the sim really produced the rest."""
    for side, card in _cards(REFUSED).items():
        labels = {m["label"]: m["value"] for m in card["metrics"]}
        assert labels["Mean"] == "0.00" or labels["Mean"].startswith("0"), labels
        assert card["title"] in ("Zero Batter", "Zero Arm")
