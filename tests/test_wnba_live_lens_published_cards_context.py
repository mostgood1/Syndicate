"""The live-lens tick consumes a PUBLISHED context, not another process's dict.

`44008605` turned the WNBA live-lens tick into a consumer of
`build_cards_page_context_if_cached` and named the /wnba endpoints as the
builders. The reasoning was right and the mechanism could not work: that cache
is a module-level dict, so it is warm only inside the interpreter that filled
it. The tick runs on refresh-worker (moved there by `397088a3`); the /wnba
routes run on web. Two containers, two dicts, and a read that could never hit.

MEASURED on refresh-worker 2026-08-08 18:00-21:45Z, before the fix:

    live_lens_tick_before_wnba          7
    live_lens_tick_after_build_wnba     7
    CARDS_CONTEXT_COLD                  6      <- 6 of 7 ticks degraded
    reason=low_headroom                 0      <- the gate was NOT the cause

and on the surface that consumes the output, with a real 3-game slate whose
/wnba/api/cards showed IND @ CHI live with 1:49 left in the 4th:

    GET /wnba/api/live-lens?date=2026-08-08  ->  games: 0, rank_cards: 0

Two further reasons the same read could never hit, each sufficient alone: the
cache key carries `allow_stored_date_fallback` and the /wnba routes build with
`True` while the tick asks for `False`; and the TTL is 12s against an observed
tick spacing of ~22 minutes.
"""

from __future__ import annotations

import time
from unittest.mock import patch

from syndicate.features.wnba import cards as wnba_cards
from syndicate.features.wnba import live_lens as wnba_live_lens


CONTEXT = {
    "date": "2026-08-08",
    "requested_date": "2026-08-08",
    "source_path": "wnba_cards.json",
    "games": [
        {
            "event_id": "evt-live",
            "away": {"abbr": "IND", "score": 71},
            "home": {"abbr": "CHI", "score": 68},
            "status": "Live",
            "detail": "1:49 - 4th",
            "summary": "Live pace is tracking over.",
            "panels": [],
            "shared_prop_rows": [],
            "shared_top_play_rows": [],
        }
    ],
}


def _publish(payload):
    """Stand in for the shared keyvalue store one writer/one reader apart."""
    store: dict[str, object] = {}

    def _write(path, value):
        store[str(path)] = value

    def _read(path):
        return store.get(str(path))

    if payload is not None:
        store[str(wnba_cards.wnba_cards_context_artifact_path("2026-08-08"))] = payload
    return _write, _read


def test_a_cold_process_cache_no_longer_means_an_empty_lens():
    """The regression, and the fix, in one assertion. The in-process cache is
    cold -- as it always is on a worker -- and the published artifact carries
    the slate through anyway."""
    published = dict(CONTEXT, published_at=time.time())
    _write, _read = _publish(published)

    with patch.object(wnba_cards, "_keyvalue_read_json_file", _read), patch.object(
        wnba_cards, "_keyvalue_write_json_file", _write
    ), patch.object(
        wnba_live_lens, "build_cards_page_context_if_cached", return_value=None
    ), patch.object(
        wnba_live_lens, "build_live_lines_payload", return_value={"games": []}
    ), patch.object(
        wnba_live_lens, "_run_wnba_live_lens_tick", return_value=None
    ):
        snapshot = wnba_live_lens.build_live_lens_snapshot("2026-08-08")

    assert len(snapshot["games"]) == 1
    assert snapshot["rank_cards"], "a published context must produce rank cards"
    assert snapshot["cards_context_source"] == "published_artifact"


def test_the_tick_never_rebuilds_the_cards_page():
    """The ~1GB rebuild `44008605` removed must not come back through the
    artifact path. If the published context is missing, the tick degrades."""
    _write, _read = _publish(None)

    def _explode(*args, **kwargs):
        raise AssertionError("the tick rebuilt the cards page")

    with patch.object(wnba_cards, "_keyvalue_read_json_file", _read), patch.object(
        wnba_live_lens, "build_cards_page_context_if_cached", return_value=None
    ), patch.object(wnba_live_lens, "build_cards_page_context", _explode), patch.object(
        wnba_live_lens, "_run_wnba_live_lens_tick", return_value=None
    ):
        snapshot = wnba_live_lens.build_live_lens_snapshot("2026-08-08")

    assert snapshot["games"] == []
    assert snapshot["cards_context_source"] == "cold"


def test_a_stale_context_is_served_and_flagged_rather_than_refused():
    """Refusing a 40-minute-old context puts the lens back to the blank page
    this whole change exists to remove. A visible slate with a stated age beats
    a blank one -- so it is served, marked stale, and its age travels with it.
    Serving it as if it were LIVE would be the `e8deadb7` defect (snapshots
    frozen at pregame), which is what the flag exists to prevent."""
    published = dict(CONTEXT, published_at=time.time() - 2400)
    _write, _read = _publish(published)

    with patch.object(wnba_cards, "_keyvalue_read_json_file", _read):
        context, age, is_stale = wnba_cards.load_published_cards_page_context("2026-08-08")

    assert context is not None, "a stale slate is still better than an empty page"
    assert is_stale is True
    assert age is not None and age > 2000


def test_past_the_hard_ceiling_it_is_refused_and_the_age_still_reported():
    """A context built this morning does not describe a night slate. Past the
    hard ceiling it stops being stale data and starts being the wrong data --
    and the miss still says HOW stale, because a miss without an age cannot be
    told from "nobody published one"."""
    published = dict(CONTEXT, published_at=time.time() - 30000)
    _write, _read = _publish(published)

    with patch.object(wnba_cards, "_keyvalue_read_json_file", _read):
        context, age, is_stale = wnba_cards.load_published_cards_page_context("2026-08-08")

    assert context is None
    assert age is not None and age > 20000
    assert is_stale is True


def test_the_fresh_bound_being_unmeetable_cannot_empty_the_lens():
    """The bound the publisher's real cadence has to clear is a GUESS (900s),
    and a guessed threshold that silently disables the stage it guards is the
    defect this repo keeps re-learning. Squeeze FRESH to zero and the lens must
    still carry the slate."""
    published = dict(CONTEXT, published_at=time.time() - 60)
    _write, _read = _publish(published)

    with patch.dict(
        "os.environ", {"SYNDICATE_WNBA_CARDS_CONTEXT_MAX_AGE_SECONDS": "1"}, clear=False
    ), patch.object(wnba_cards, "_keyvalue_read_json_file", _read), patch.object(
        wnba_live_lens, "build_cards_page_context_if_cached", return_value=None
    ), patch.object(
        wnba_live_lens, "build_live_lines_payload", return_value={"games": []}
    ), patch.object(wnba_live_lens, "_run_wnba_live_lens_tick", return_value=None):
        snapshot = wnba_live_lens.build_live_lens_snapshot("2026-08-08")

    assert len(snapshot["games"]) == 1
    assert snapshot["cards_context_source"] == "published_artifact_stale"


def test_provenance_travels_with_the_snapshot():
    """A live lens built from a 10-minute-old context is not wrong the way an
    empty one is, but it is not live either. Whoever reads the snapshot must be
    able to tell which source fed it and how old that source was."""
    published = dict(CONTEXT, published_at=time.time() - 120)
    _write, _read = _publish(published)

    with patch.object(wnba_cards, "_keyvalue_read_json_file", _read), patch.object(
        wnba_live_lens, "build_cards_page_context_if_cached", return_value=None
    ), patch.object(
        wnba_live_lens, "build_live_lines_payload", return_value={"games": []}
    ), patch.object(wnba_live_lens, "_run_wnba_live_lens_tick", return_value=None):
        snapshot = wnba_live_lens.build_live_lens_snapshot("2026-08-08")

    assert snapshot["cards_context_source"] == "published_artifact"
    assert 100 <= snapshot["cards_context_age_seconds"] <= 200


def test_the_stored_date_fallback_variant_is_never_published():
    """`allow_stored_date_fallback=True` may substitute a DIFFERENT date's
    stored slate. That is exactly the wrong thing to hand a live lens, and it is
    what the /wnba routes build with -- so the publish must be keyed off the
    live-truthful variant only."""
    writes: list[str] = []

    with patch.object(wnba_cards, "_build_cards_page_context_uncached", return_value=dict(CONTEXT)), patch.object(
        wnba_cards, "_keyvalue_write_json_file", lambda path, value: writes.append(str(path))
    ):
        wnba_cards._clear_build_cards_page_context_cache()
        wnba_cards.build_cards_page_context("2026-08-08", allow_stored_date_fallback=True)
        assert writes == []

        wnba_cards._clear_build_cards_page_context_cache()
        wnba_cards.build_cards_page_context("2026-08-08", allow_stored_date_fallback=False)
        assert len(writes) == 1


def test_a_broken_shared_store_never_breaks_a_page_render():
    """The publish rides inside the request path on web. A keyvalue outage must
    degrade the live lens, not 500 the cards page."""

    def _explode(*args, **kwargs):
        raise RuntimeError("keyvalue down")

    with patch.object(wnba_cards, "_build_cards_page_context_uncached", return_value=dict(CONTEXT)), patch.object(
        wnba_cards, "_keyvalue_write_json_file", _explode
    ):
        wnba_cards._clear_build_cards_page_context_cache()
        context = wnba_cards.build_cards_page_context("2026-08-08", allow_stored_date_fallback=False)

    assert len(context["games"]) == 1


def test_the_card_eyebrow_reads_the_status_dict_not_its_repr():
    """`game["status"]` is a dict under the board contract. The eyebrow ran it
    through `_safe_text`, so a card carrying a real slate rendered
    `{'clock': '', 'detail': 'Final', ...}` to the user. Only reachable once the
    lens has rows at all, which is why the empty-snapshot regression hid it."""
    card = wnba_live_lens._rank_card(
        {
            "event_id": "evt-live",
            "away": {"abbr": "IND", "score": 71},
            "home": {"abbr": "CHI", "score": 68},
            "status": {"status": "Live", "detail": "1:49 - 4th", "in_progress": True},
            "detail": "1:49 - 4th",
        },
        "2026-08-08",
        live_line=None,
    )

    assert card["eyebrow"] == "Live"
    assert "{" not in card["eyebrow"]


def test_the_web_route_actually_passes_allow_rebuild():
    """`44008605` added `allow_rebuild` and documented it as the route's escape
    hatch, then never passed it from any caller -- so the one path where a
    rebuild IS the job being asked for degraded exactly like the background
    tick."""
    import inspect

    source = inspect.getsource(wnba_live_lens.build_live_lens_page_context)
    assert "allow_rebuild=True" in source


def test_provenance_survives_the_api_boundary():
    """`build_rank_api_payload` copies an EXPLICIT key list, so a top-level
    scalar added upstream is silently dropped crossing it -- todo.md's first
    operational rule. Measured on the served production payload 2026-08-08
    22:29Z: `cards_context_source` and `cards_context_age_seconds` both read
    `None`, which is worse than absent because it reads as "the tick had no
    provenance" rather than "this endpoint forgot to forward it".

    Nested payloads survive that boundary; scalars do not. These are scalars.
    """
    published = dict(CONTEXT, published_at=time.time() - 120)
    _write, _read = _publish(published)

    with patch.object(wnba_cards, "_keyvalue_read_json_file", _read), patch.object(
        wnba_live_lens, "build_cards_page_context_if_cached", return_value=None
    ), patch.object(
        wnba_live_lens, "build_live_lines_payload", return_value={"games": []}
    ), patch.object(wnba_live_lens, "_run_wnba_live_lens_tick", return_value=None), patch.object(
        wnba_live_lens, "_load_live_lens_snapshot", return_value=None
    ):
        payload = wnba_live_lens.build_live_lens_api_payload("2026-08-08")

    assert payload["cards_context_source"] == "published_artifact"
    assert 100 <= payload["cards_context_age_seconds"] <= 200
