"""The `/` embed must not serialise the same 685 rows six times.

MEASURED on the served page 2026-08-30 (12,437,156 bytes, TTFB 4.9-5.9s):

    <script> blocks            12,428,521 chars   99.9% of the page
    markup/text                     8,501 chars
    the board JSON blob        11,283,324 chars   98.4% of the page

    top_opportunities   685 rows  1,860,287  sha1 2e6b803dfe9b  \\
    recommendations     685 rows  1,860,287  sha1 2e6b803dfe9b   > byte-identical
    ranked_all          685 rows  1,860,287  sha1 2e6b803dfe9b  /
    boardContract                 1,860,034  == board_contract (same object)
    by_sport flattened  685 rows  1,860,325  == ranked_all grouped by sport

**82% of the payload is duplication.**

THE PROPERTY THAT MAKES THE FIX SAFE, and what these tests exist to pin: a key is
dropped ONLY when it is provably identical to its canonical form. The failure
mode is therefore "no saving", never "wrong data". A payload whose
`recommendations` genuinely differs from `ranked_all` must come through
untouched, and that is the first test below -- not the happy path.
"""
from __future__ import annotations

import json

from syndicate.blueprints.intelligence import _slim_embedded_board_payload


def _rows(n=3, sport="mlb"):
    return [{"sport": sport, "id": i, "ev_pct": float(i)} for i in range(n)]


def _rehydrate(payload):
    """The client's rebuild, mirrored. Kept deliberately literal so a divergence
    between this and `intelligence.html` shows up as a test failure rather than
    as a blank board in production.

    `_embed_dropped` and `_dropped_row_fields` are NOT rebuilt -- they are keys
    the page does not read, declared so a consumer can tell "dropped on purpose"
    from "the server had no value". The tests below compare against an original
    with those removed, never against the untouched one."""
    out = dict(payload)
    out.pop("_embed_dropped", None)
    out.pop("_dropped_row_fields", None)
    out.pop("_dropped_row_aliases", None)
    aliases = out.pop("_embed_aliases", None) or {}
    for key, source in aliases.items():
        if source == "__group_ranked_all_by_sport__":
            grouped: dict[str, list] = {}
            for row in out.get("ranked_all") or []:
                grouped.setdefault(str(row.get("sport") or ""), []).append(row)
            out[key] = grouped
        elif source in out:
            out[key] = out[source]
    return out


# --------------------------------------------------------------------------
# THE SAFETY PROPERTY FIRST. A saving that can corrupt is not a saving.
# --------------------------------------------------------------------------


def test_a_genuinely_different_list_is_never_dropped():
    """If `recommendations` is not identical to `ranked_all`, it must survive."""
    payload = {
        "ranked_all": _rows(3),
        "recommendations": _rows(2),          # DIFFERENT -- must be kept
        "top_opportunities": _rows(3),        # identical -- may be dropped
    }
    slim = _slim_embedded_board_payload(payload)
    assert "recommendations" in slim, "a differing list was dropped -- data loss"
    assert slim["recommendations"] == _rows(2)


def test_a_differing_board_contract_alias_is_never_dropped():
    payload = {"board_contract": {"cards": [1]}, "boardContract": {"cards": [2]}}
    slim = _slim_embedded_board_payload(payload)
    assert slim["boardContract"] == {"cards": [2]}


def test_by_sport_is_kept_when_it_is_not_a_pure_partition():
    """Grouping that does not reconstruct exactly must not be thrown away --
    e.g. a sport bucket the rows themselves do not account for."""
    payload = {
        "ranked_all": _rows(2, "mlb"),
        "by_sport": {"mlb": _rows(2, "mlb"), "nfl": [{"sport": "nfl", "id": 9}]},
    }
    slim = _slim_embedded_board_payload(payload)
    assert "by_sport" in slim, "a by_sport that does not reconstruct was dropped"


def test_a_payload_with_nothing_redundant_is_returned_unchanged():
    payload = {"ranked_all": _rows(2), "board_contract": {"cards": []}}
    assert _slim_embedded_board_payload(payload) == payload
    assert "_embed_aliases" not in _slim_embedded_board_payload(payload)


def test_a_non_dict_is_passed_through():
    assert _slim_embedded_board_payload(None) is None
    assert _slim_embedded_board_payload([1, 2]) == [1, 2]


# --------------------------------------------------------------------------
# THEN the saving, and that it round-trips EXACTLY.
# --------------------------------------------------------------------------


def test_the_six_way_duplication_collapses_and_rebuilds_identically():
    """THE REGRESSION, in the shape production actually had it."""
    rows = _rows(4, "mlb") + _rows(3, "soccer")
    contract = {"cards": [{"c": 1}], "lane_counts": {"live": 2}}
    original = {
        "ranked_all": rows,
        "top_opportunities": list(rows),
        "recommendations": list(rows),
        "board_contract": contract,
        "boardContract": dict(contract),
        "by_sport": {"mlb": _rows(4, "mlb"), "soccer": _rows(3, "soccer")},
        "server_time": "2026-08-30T00:00:00Z",
    }
    slim = _slim_embedded_board_payload(original)

    for gone in ("top_opportunities", "recommendations", "boardContract", "by_sport"):
        assert gone not in slim, f"{gone} should have been dropped as redundant"
    assert "ranked_all" in slim and "board_contract" in slim

    # `board_contract.cards` is dropped as UNREAD (see the 2026-09-22 block
    # below), so the rebuild restores everything else.
    expected = dict(original)
    expected["board_contract"] = {k: v for k, v in contract.items() if k != "cards"}
    expected["boardContract"] = dict(expected["board_contract"])
    assert _rehydrate(slim) == expected


def test_the_saving_is_material_not_cosmetic():
    """A dedupe that saves nothing is not worth the moving parts."""
    rows = _rows(200)
    contract = {"cards": rows}
    original = {
        "ranked_all": rows,
        "top_opportunities": list(rows),
        "recommendations": list(rows),
        "board_contract": contract,
        "boardContract": dict(contract),
        "by_sport": {"mlb": list(rows)},
    }
    before = len(json.dumps(original, default=str))
    after = len(json.dumps(_slim_embedded_board_payload(original), default=str))
    assert after < before * 0.45, f"only {100 * (1 - after / before):.0f}% saved"
    expected = dict(original)
    expected["board_contract"] = {k: v for k, v in contract.items() if k != "cards"}
    expected["boardContract"] = dict(expected["board_contract"])
    assert _rehydrate(_slim_embedded_board_payload(original)) == expected


def test_rehydrate_tolerates_a_payload_with_no_aliases():
    """An older server, or one where nothing was redundant. Must not throw."""
    payload = {"ranked_all": _rows(2)}
    assert _rehydrate(payload) == payload


# --------------------------------------------------------------------------
# 2026-09-22: the same page, 3,244 rows later. MEASURED on the served `/`:
# 32,802,992 bytes (4,579,458 gzipped), TTFB 4.1-8.5 s against 0.46 s for
# `/nfl`, and the embed was 99.3% of it -- `ranked_all` 15.54 MB and
# `board_contract.cards` 15.53 MB. The two are NOT copies (642 of 3,244 cards
# carry a different `gate` / `live_projection` / `actual` / `is_live`), so no
# alias can rebuild one from the other. They are dropped as UNREAD instead,
# which is only safe while the page does not read them -- pinned below.
# --------------------------------------------------------------------------


def test_the_board_cards_list_is_dropped_from_the_embed_and_declared():
    rows = _rows(3)
    cards = [dict(row) for row in rows]
    cards[1]["gate"] = "blocked"          # production's shape: NOT a copy
    contract = {"cards": cards, "lane_counts": {"live": 2}, "recommendation_count": 3}
    original = {"ranked_all": rows, "board_contract": contract}

    slim = _slim_embedded_board_payload(original)

    assert "cards" not in slim["board_contract"]
    assert slim["_embed_dropped"] == ["board_contract.cards"]
    # Everything else the page DOES read survives.
    assert slim["board_contract"]["lane_counts"] == {"live": 2}
    assert slim["board_contract"]["recommendation_count"] == 3
    assert slim["ranked_all"] == rows
    # The API shares this object: slimming the embed must not mutate it.
    assert original["board_contract"]["cards"] == cards


def test_row_diagnostics_are_dropped_from_the_embed_and_declared():
    """The page asks the API for exactly this (`drop_row_diagnostics: true`);
    the embed never applied it. 1.67 MB of the 2026-09-22 payload."""
    rows = [{"sport": "mlb", "id": 1, "trace": {"steps": [1, 2, 3]}, "score_breakdown": {"a": 1}}]
    slim = _slim_embedded_board_payload({"ranked_all": rows, "board_contract": {"cards": list(rows)}})

    row = slim["ranked_all"][0]
    assert "trace" not in row and "score_breakdown" not in row
    assert row["sport"] == "mlb" and row["id"] == 1
    assert set(slim["_dropped_row_fields"]) >= {"trace", "score_breakdown"}


def test_the_page_still_does_not_read_the_embedded_board_cards():
    """THE GUARD for the drop above. `intelligence.html` is the embed's only
    consumer; it mentions `board_contract.cards` twice, both harmless: the
    row-alias repair loop (which tolerates the key's absence) and a comment.
    A new READ here means the embed must stop dropping the list."""
    import pathlib

    template = (pathlib.Path(__file__).resolve().parents[1]
                / "syndicate" / "templates" / "intelligence.html").read_text(encoding="utf-8")
    reads = [line.strip() for line in template.splitlines()
             if "board_contract.cards" in line or "boardContract.cards" in line]
    code_reads = [line for line in reads if not line.startswith("//")]
    assert code_reads == [
        "const boardCards = payload.board_contract && Array.isArray(payload.board_contract.cards)",
        "? [payload.board_contract.cards]",
    ], (
        "intelligence.html now reads board_contract.cards somewhere new: "
        f"{code_reads}. The embed drops that list (_slim_embedded_board_payload); "
        "either stop dropping it or make the new reader tolerate its absence."
    )


# --------------------------------------------------------------------------
# 2026-10-09: HYDRATION MUST STAMP `by_sport` LIKE EVERY OTHER ROW LIST.
#
# Logo stamping (10-08) covered ranked_all / top_opportunities /
# recommendations and not `by_sport`, so the exact-match dedupe above failed on
# EVERY request and the served `/` carried the board twice: 25.4 MB of a
# 49.8 MB page for a key the page never reads (lane home-embed-by-sport-dedupe).
# The unit tests above all fed the slimmer by hand and so could not see it.
# This one runs the real hydrate -> slim chain the route runs.
# --------------------------------------------------------------------------


def test_hydration_keeps_by_sport_droppable_from_the_embed(tmp_path, monkeypatch):
    from syndicate.blueprints import intelligence as bp
    from syndicate.features.shared import team_logos

    branding = tmp_path / "nhl_team_branding.csv"
    branding.write_text(
        "team_id,abbreviation,location,display_name,primary_color,secondary_color,logo_url,source_snapshot_date\n"
        "1,TOR,Toronto,Toronto Maple Leafs,,,https://x/tor.png,2026-10-01\n"
        "2,BOS,Boston,Boston Bruins,,,https://x/bos.png,2026-10-01\n",
        encoding="utf-8",
    )
    team_logos._index.cache_clear()
    monkeypatch.setattr(team_logos, "_branding_files", lambda *a, **k: [branding])
    try:
        rows = [
            {"sport": "nhl", "pick_id": f"p{i}", "home_team": "Toronto Maple Leafs", "away_team": "Boston Bruins", "ev_pct": float(i)}
            for i in range(3)
        ]
        # by_sport as its own row objects, as the producer sends it -- a shared
        # object would be stamped once and hide the bug.
        payload = {"ok": True, "ranked_all": rows, "by_sport": {"nhl": [dict(r) for r in rows]}}
        hydrated = bp._hydrate_board_response_payload(payload)
        assert all(r.get("home_logo") == "https://x/tor.png" for r in hydrated["by_sport"]["nhl"])

        slim = bp._slim_embedded_board_payload(hydrated)
        assert "by_sport" not in slim, "by_sport diverged from ranked_all and was shipped a second time"
        assert slim["_embed_aliases"]["by_sport"] == "__group_ranked_all_by_sport__"
        # Strict parse of the text the route actually serves, by the browser's
        # rules: no NaN/Infinity (learnings 2026-10-08).
        slim["ranked_all"][0]["line"] = float("nan")

        def _refuse(token):
            raise ValueError(token)

        json.loads(bp._embed_json_text(slim), parse_constant=_refuse)
    finally:
        team_logos._index.cache_clear()
