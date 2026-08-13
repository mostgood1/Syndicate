"""`#412` -- the live prop join keyed on a display grouping and matched nothing.

REPORTED FROM THE BOARD: "im not seeing proj/edge data on the live lines so make
sure we are carrying live projection, sim projection, and actual so far."

The join was not partially broken, it was totally broken, and its own
instrumentation said so on production 2026-08-13:

    rows_live_considered: 1385      live_games_in_snapshot: 7
    rows_live_projected:  0         snapshot_rows_indexed: 90
    miss_no_player:       0         miss_no_market_alias: 1385   <- all of them

`build_live_prop_index` keyed each snapshot row on `market`. But `market` is a
DISPLAY GROUPING, not a market -- measured the same day:

    market                prop                    rows
    hitter_props          hits                      39
    hitter_props          total_bases               29
    hitter_props          runs_scored                1
    hitter_total_bases    batter_total_bases        20
    hitter_rbis           batter_rbis               15

So `hitter_props` (a) collapsed four unrelated markets onto one key, colliding 70
rows against each other, and (b) matched no board market, because the board
speaks OddsAPI (`batter_hits`). The correct key was sitting in the next field the
whole time: `prop` is already the board's vocabulary.

THE CONTROL, run against one production snapshot and one production board:

    old keying -> rows_live_projected = 0
    new keying -> rows_live_projected = 41

Same snapshot, same rows, same index. Nothing else changed.
"""

from __future__ import annotations

from syndicate.features.shared.live_edge_policy import live_edge_unavailable_reason
from syndicate.features.shared.live_projection_join import (
    attach_live_projections,
    build_live_prop_index,
)


def _snapshot(*props):
    return {
        "games": [
            {
                "status": {"abstract": "Live", "detailed": "In Progress"},
                "liveProps": list(props),
            }
        ]
    }


def _prop(player, market, prop_key, line, projection=0.8, actual=1.0):
    return {
        "playerName": player,
        "market": market,
        "prop": prop_key,
        "line": line,
        "liveProjection": projection,
        "modelProbOver": 0.42,
        "actualSoFar": actual,
        "selection": "Over",
    }


def _row(player, market, line, projection=None):
    return {
        "kind": "prop",
        "game": {"state": "live"},
        "player_name": player,
        "market": market,
        "line": line,
        "projection": dict(projection or {}),
    }


def test_the_grouping_field_does_not_decide_the_market():
    """The reported case. `hitter_props` must not be the key."""
    index = build_live_prop_index(
        _snapshot(_prop("Brandon Lowe", "hitter_props", "total_bases", 1.5))
    )
    grid = [_row("Brandon Lowe", "batter_total_bases", 1.5)]
    coverage = attach_live_projections(grid, index)
    assert coverage["rows_live_projected"] == 1, coverage


def test_one_grouping_covering_four_markets_does_not_collide():
    """`hitter_props` covered hits, total_bases, runs_scored and rbis at once.

    Keyed on the grouping, these four overwrite each other in the index and at
    most one survives -- so this asserts all four land, not merely that some do.
    """
    index = build_live_prop_index(
        _snapshot(
            _prop("Aaron Judge", "hitter_props", "hits", 0.5, projection=1.1),
            _prop("Aaron Judge", "hitter_props", "total_bases", 0.5, projection=2.2),
            _prop("Aaron Judge", "hitter_props", "runs_scored", 0.5, projection=3.3),
            _prop("Aaron Judge", "hitter_props", "rbis", 0.5, projection=4.4),
        )
    )
    grid = [
        _row("Aaron Judge", "batter_hits", 0.5),
        _row("Aaron Judge", "batter_total_bases", 0.5),
        _row("Aaron Judge", "batter_runs_scored", 0.5),
        _row("Aaron Judge", "batter_rbis", 0.5),
    ]
    coverage = attach_live_projections(grid, index)
    assert coverage["rows_live_projected"] == 4, coverage
    assert [r["projection"]["projected"] for r in grid] == [1.1, 2.2, 3.3, 4.4], (
        "the four markets crossed wires -- the grouping is still the key somewhere"
    )


def test_the_alias_map_joins_in_both_directions():
    """`_MARKET_ALIASES` was a one-way expansion and the snapshot speaks both.

    The same market arrived as `hits` on 39 rows and `batter_hits` on 6. A
    one-way map matches whichever side happens to hold the canonical name.
    """
    for snapshot_name in ("hits", "batter_hits"):
        index = build_live_prop_index(
            _snapshot(_prop("Mookie Betts", "hitter_props", snapshot_name, 1.5))
        )
        grid = [_row("Mookie Betts", "batter_hits", 1.5)]
        coverage = attach_live_projections(grid, index)
        assert coverage["rows_live_projected"] == 1, f"{snapshot_name}: {coverage}"


def test_a_batters_strikeouts_never_joins_a_pitchers():
    # The families must stay separate. Merging them would price a hitter's
    # strikeout prop off the pitcher's distribution, which joins and is wrong --
    # strictly worse than not joining.
    index = build_live_prop_index(
        _snapshot(_prop("Framber Valdez", "pitcher_props", "strikeouts", 5.5))
    )
    grid = [_row("Framber Valdez", "batter_strikeouts", 5.5)]
    coverage = attach_live_projections(grid, index)
    assert coverage["rows_live_projected"] == 0


def test_a_row_with_no_live_projection_is_not_marked_live_aware():
    """`modelProbOver` alone is NOT evidence the model saw the score.

    Measured 2026-08-13: 63 of 144 snapshot rows carried `modelProbOver` while
    `liveProjection`, `modelMean` and `actualSoFar` were all null -- a pregame
    probability sitting in a live-lens row. Indexing those marks them
    `live_aware`, which hands `live_edge_policy` exactly the pregame-vs-live
    edge it exists to suppress (`#340`: a +23-point "edge" on a coin flip).
    """
    prop = _prop("Max Muncy", "hitter_runs", "batter_runs_scored", 0.5)
    prop["liveProjection"] = None
    prop["actualSoFar"] = None
    index = build_live_prop_index(_snapshot(prop))
    assert index["rows_indexed"] == 0
    assert index["skipped_no_live_projection"] == 1

    grid = [_row("Max Muncy", "batter_runs_scored", 0.5)]
    attach_live_projections(grid, index)
    assert live_edge_unavailable_reason(grid[0]), "a pregame row gained a live edge"


def test_the_live_number_does_not_erase_the_sim_number():
    """All THREE numbers, which is what was actually asked for.

    The overlay used to write `projected` over the pregame value, so the board
    could never show the move from "we projected 2.27" to "now 1.8, with 1
    already in the book".
    """
    index = build_live_prop_index(
        _snapshot(_prop("Brandon Lowe", "hitter_props", "total_bases", 1.5,
                        projection=1.8, actual=1.0))
    )
    grid = [_row("Brandon Lowe", "batter_total_bases", 1.5,
                 projection={"projected": 2.274, "basis": "total_bases_2plus"})]
    attach_live_projections(grid, index)
    p = grid[0]["projection"]
    assert p["live_projected"] == 1.8
    assert p["sim_projected"] == 2.274, "the pregame projection was overwritten"
    assert p["actual_so_far"] == 1.0
    assert p["sim_basis"] == "total_bases_2plus"


def test_a_second_pass_does_not_record_the_live_number_as_the_sim_number():
    # The artifact is rebuilt every cycle over rows that may already carry an
    # overlay. Re-stamping would ratchet `sim_projected` toward the live value
    # and quietly erase the pregame baseline over the course of a game.
    index = build_live_prop_index(
        _snapshot(_prop("Brandon Lowe", "hitter_props", "total_bases", 1.5, projection=1.8))
    )
    grid = [_row("Brandon Lowe", "batter_total_bases", 1.5,
                 projection={"projected": 2.274, "basis": "total_bases_2plus"})]
    attach_live_projections(grid, index)
    attach_live_projections(grid, index)
    assert grid[0]["projection"]["sim_projected"] == 2.274


def test_the_snapshot_ceiling_is_reported():
    """A low count must be attributable without a second investigation.

    The lens indexes far fewer rows than the board carries (68 indexable against
    1336 live board rows). "The join is broken" and "the lens only covers this
    much" render identically as a small number and have opposite fixes.
    """
    prop = _prop("Max Muncy", "hitter_runs", "batter_runs_scored", 0.5)
    prop["liveProjection"] = None
    index = build_live_prop_index(
        _snapshot(prop, _prop("Brandon Lowe", "hitter_props", "total_bases", 1.5))
    )
    coverage = attach_live_projections([], index)
    assert coverage["snapshot_rows_seen"] == 2
    assert coverage["snapshot_rows_indexed"] == 1
    assert coverage["snapshot_skipped_no_live_projection"] == 1


def test_a_row_the_resim_could_not_price_carries_no_edge():
    """No live probability -> no edge. There is deliberately NO fallback.

    Falling back to `modelProbOver` is what produced the original defect: it was
    bit-identical to the pregame probability on 24 of 28 rows, and three props
    whose over was ALREADY WON still read 0.659/0.655/0.745, giving
    +36.5%/+32.3%/+15.8% -- more than twice the honest numbers, on a board that
    sorts by edge. A row the live model cannot reach must stay blank.
    """
    # UNDECIDED on purpose, so this isolates the missing-probability case rather
    # than tripping the already-decided guard below it.
    index = build_live_prop_index(
        _snapshot(_prop("Angel Genao", "hitter_props", "hits", 0.5, projection=0.7, actual=0.0))
    )
    grid = [_row("Angel Genao", "batter_hits", 0.5,
                 projection={"model_prob_over": 0.659, "market_fair_prob_over": 0.294})]
    coverage = attach_live_projections(grid, index)
    p = grid[0]["projection"]
    assert p["edge_vs_market_pct"] is None, (
        "the pregame probability was priced against a live market -- the #340 defect"
    )
    assert coverage["rows_live_edge_withheld"] == 1
    assert "no probability" in p["edge_unavailable_reason"]


def test_a_live_probability_produces_a_live_edge():
    """`#414`: the re-sim now emits P(over) from its own rest-of-game sims."""
    prop = _prop("Brandon Lowe", "hitter_props", "total_bases", 1.5, projection=1.8, actual=1.0)
    prop["liveModelProbOver"] = 0.62
    index = build_live_prop_index(_snapshot(prop))
    grid = [_row("Brandon Lowe", "batter_total_bases", 1.5,
                 projection={"model_prob_over": 0.281, "market_fair_prob_over": 0.50})]
    coverage = attach_live_projections(grid, index)
    p = grid[0]["projection"]
    assert coverage["rows_live_edged"] == 1
    assert p["edge_vs_market_pct"] == 12.0, "(0.62 - 0.50) * 100"
    assert p["live_prob_over"] == 0.62
    assert "edge_unavailable_reason" not in p


def test_the_live_probability_is_never_taken_from_the_pregame_field():
    """The two must not share a keyspace, at either end of the join.

    `modelProbOver` IS the pregame number. If it ever reaches the edge -- by
    fallback, by rename, or by a normaliser folding the two together -- every
    measurement in this file's docstring comes straight back.
    """
    prop = _prop("Mookie Betts", "hitter_props", "hits", 0.5)
    prop["modelProbOver"] = 0.90          # pregame, and wildly favourable
    prop.pop("liveModelProbOver", None)   # the re-sim priced nothing
    index = build_live_prop_index(_snapshot(prop))
    grid = [_row("Mookie Betts", "batter_hits", 0.5,
                 projection={"market_fair_prob_over": 0.30})]
    attach_live_projections(grid, index)
    assert grid[0]["projection"]["edge_vs_market_pct"] is None, (
        "a +60-point edge was manufactured from the pregame probability"
    )


def test_a_missing_market_fair_is_named_separately():
    # "the re-sim had no opinion" and "there is no market price to beat" are
    # different facts with different fixes, and both render as a blank cell.
    prop = _prop("Brandon Lowe", "hitter_props", "total_bases", 1.5)
    prop["liveModelProbOver"] = 0.62
    index = build_live_prop_index(_snapshot(prop))
    grid = [_row("Brandon Lowe", "batter_total_bases", 1.5, projection={})]
    attach_live_projections(grid, index)
    assert "no market fair value" in grid[0]["projection"]["edge_unavailable_reason"]


def test_deriving_a_probability_from_the_live_mean_is_not_attempted():
    # WNBA already refuses this: "inventing P(over) from a mean would put a
    # fabricated number into EV". The edge must be priced from the re-sim's own
    # probability field and never reconstructed from `live_projection`.
    import pathlib

    src = (pathlib.Path(__file__).resolve().parents[1]
           / "syndicate" / "features" / "shared" / "live_projection_join.py").read_text(encoding="utf-8")
    src_body = src[src.index("def attach_live_projections("):]
    # Scoped to the EDGE block. `model_prob_over` is legitimately carried onto
    # the projection for display; what must never happen is it reaching the edge.
    start = src_body.index('        live_prob = hit.get(')
    edge_block = src_body[start:src_body.index("edged += 1", start)]
    assert 'live_prob = hit.get("live_prob_over")' in edge_block
    assert "model_prob_over" not in edge_block, "the pregame probability is reachable from the edge"
    assert "live_projection" not in edge_block, "the edge is being derived from the mean"


def test_an_already_decided_prop_is_not_an_edge():
    """`#414` guard: a settled market has no price to beat.

    With 1 hit banked against a 0.5 line the live probability is exactly 1.0 --
    correct -- and against a fair value of 0.30 that computes a **+70% edge**.
    There is no bet: the book has settled or pulled the market, and a price still
    reading 0.30 is a stale quote. Left in, these are the LARGEST numbers on the
    board and sort straight to the top -- the same visible failure the pregame
    probability produced, reached by a different route.

    Same rule `live_edge_policy` applies to a final game, scoped to one player.
    """
    prop = _prop("Angel Genao", "hitter_props", "hits", 0.5, projection=1.0, actual=1.0)
    prop["liveModelProbOver"] = 1.0
    index = build_live_prop_index(_snapshot(prop))
    grid = [_row("Angel Genao", "batter_hits", 0.5,
                 projection={"market_fair_prob_over": 0.30})]
    coverage = attach_live_projections(grid, index)
    p = grid[0]["projection"]
    assert p["edge_vs_market_pct"] is None, "a +70% edge on a settled market"
    assert "already decided" in p["edge_unavailable_reason"]
    assert coverage["rows_live_edge_withheld"] == 1


def test_an_undecided_prop_at_the_same_line_still_prices():
    # The guard must key on the BANKED value, not on the line or the market.
    # Withholding every 0.5-line prop would delete most of the live board.
    prop = _prop("Angel Genao", "hitter_props", "hits", 0.5, projection=0.7, actual=0.0)
    prop["liveModelProbOver"] = 0.48
    index = build_live_prop_index(_snapshot(prop))
    grid = [_row("Angel Genao", "batter_hits", 0.5,
                 projection={"market_fair_prob_over": 0.30})]
    coverage = attach_live_projections(grid, index)
    assert coverage["rows_live_edged"] == 1
    assert grid[0]["projection"]["edge_vs_market_pct"] == 18.0


def test_every_layer_between_the_resim_and_the_board_carries_the_field():
    """`#416` shipped INERT the first time, and this is the guard for that.

    The re-sim computed `live_model_prob_over` correctly and
    `_normalize_live_lens_live_prop_row` -- a WHITELIST that rebuilds each row
    from an explicit key list -- dropped it one layer before the snapshot.
    Deployed on both workers, `LIVE_PROB` read 0 on every tick while
    `liveProjection` populated normally: present, running, and unreachable.

    The chain is four hops and a whitelist at any of them is silent:

        _current_live_prop_rows        computes  live_model_prob_over
        _normalize_live_lens_live_prop_row  ->   liveModelProbOver   <- dropped here
        mlb/live_lens._normalize_live_prop_row   passthrough
        live_projection_join.build_live_prop_index consumes it
    """
    import pathlib

    repo = pathlib.Path(__file__).resolve().parents[1]
    vendor = (repo / "vendor" / "mlb_bettingv2" / "tools" / "web"
              / "flask_frontend.py").read_text(encoding="utf-8", errors="replace")
    lens = (repo / "syndicate" / "features" / "mlb" / "live_lens.py").read_text(encoding="utf-8")
    join = (repo / "syndicate" / "features" / "shared"
            / "live_projection_join.py").read_text(encoding="utf-8")

    # 1. computed, and written onto the row in BOTH loops (hitter and pitcher)
    assert vendor.count('"live_model_prob_over": live_model_prob_over,') == 2

    # 2. survives the whitelist normaliser -- the hop that actually failed
    norm = vendor[vendor.index("def _normalize_live_lens_live_prop_row"):]
    norm = norm[:norm.index("\ndef ")]
    assert '"liveModelProbOver": _safe_float(row.get("live_model_prob_over")),' in norm

    # 3. survives Syndicate's own normaliser
    assert '"liveModelProbOver": row.get("liveModelProbOver")' in lens

    # 4. is read by the join, from its OWN key and never from the pregame one
    assert '"live_prob_over": prop.get("liveModelProbOver"),' in join


def test_the_live_probability_is_not_folded_into_the_pregame_fallback_chain():
    """`modelProbOver`'s chain reaches `estimatedWinProb` -- the PREGAME number.

    Folding the live field into that chain would make an absent live probability
    silently resolve to the pregame one, which is the original defect restored
    at the normaliser instead of at the join.
    """
    import pathlib

    lens = (pathlib.Path(__file__).resolve().parents[1] / "syndicate" / "features" / "mlb"
            / "live_lens.py").read_text(encoding="utf-8")
    line = next(l for l in lens.splitlines() if '"liveModelProbOver"' in l)
    assert "estimatedWinProb" not in line
    assert "estimated_win_prob" not in line


def test_the_reader_counter_separates_a_missing_field_from_a_dropped_one():
    """`#416` reader-side counter. The two cases have OPPOSITE fixes.

    The re-sim demonstrably priced props on live-odds-worker
    (`LIVE_MC_PRICED outcomes={'priced': 71}`) while the board served
    `rows_live_edged: 0`. Exactly one hop between those was unobserved: whether
    the PUBLISHED snapshot carries the field. It cannot be read from web, which
    404s on that path (it lives in the keyvalue store) and whose own recompute is
    blind (`simContextAvailable: False` on every game).

        seen == 0                     -> the writer's value never reached the artifact
        seen > 0 and indexed == 0     -> it arrived and the join dropped it

    Before this, both rendered as one blank edge column.
    """
    without = _prop("Aaron Judge", "hitter_props", "hits", 0.5)
    without.pop("liveModelProbOver", None)
    cov = attach_live_projections([], build_live_prop_index(_snapshot(without)))
    assert cov["snapshot_live_prob_seen"] == 0
    assert cov["snapshot_live_prob_indexed"] == 0

    with_prob = _prop("Aaron Judge", "hitter_props", "hits", 0.5)
    with_prob["liveModelProbOver"] = 0.44
    cov = attach_live_projections([], build_live_prop_index(_snapshot(with_prob)))
    assert cov["snapshot_live_prob_seen"] == 1
    assert cov["snapshot_live_prob_indexed"] == 1


def test_a_row_carrying_the_field_but_failing_to_index_is_counted_as_seen():
    # The discriminating case: the snapshot HAS the probability and this
    # function drops the row anyway (here, no `liveProjection`). Counting it
    # only at index time would report `seen: 0` and blame the writer.
    prop = _prop("Aaron Judge", "hitter_props", "hits", 0.5)
    prop["liveModelProbOver"] = 0.44
    prop["liveProjection"] = None
    cov = attach_live_projections([], build_live_prop_index(_snapshot(prop)))
    assert cov["snapshot_live_prob_seen"] == 1, "the field was present and went uncounted"
    assert cov["snapshot_live_prob_indexed"] == 0


def test_the_snapshot_keyspace_is_reported_when_the_field_is_absent():
    """An absent field is just another null unless you can see what IS there.

    `#412`'s root cause was a correct value under an unexpected key, found only
    by reading the row's actual keys. This carries the names -- bounded, and
    names only, never values.
    """
    prop = _prop("Aaron Judge", "hitter_props", "hits", 0.5)
    cov = attach_live_projections([], build_live_prop_index(_snapshot(prop)))
    keys = cov["snapshot_prop_keys"]
    assert "liveProjection" in keys and "modelProbOver" in keys
    assert len(keys) <= 40
    assert all(isinstance(k, str) for k in keys), "keys only -- this must not leak values"
