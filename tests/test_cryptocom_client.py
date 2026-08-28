"""Crypto.com Predictions -- a real sports venue with no SANCTIONED,
server-readable market-data surface.

These tests replaced a set written on 2026-08-24 that asserted
`FINDING["status"] == "no_public_api_yet"` and that the documented endpoint was
"rejected" as third-party. Both were falsified by live measurement on
2026-08-28 (see the module header and
`.syndicate/findings_2026-08-28_cryptocom_venue_evaluation.md`), so the tests
that pinned them had to go rather than be worked around -- a test that pins a
wrong fact is what makes the wrong fact survive.

The load-bearing test here is `test_probe_unblocks_only_on_a_non_crypto_instrument`
against `test_probe_reports_blocked_when_the_catalogue_is_all_crypto`: the pair
proves the gate is REACHABLE in both directions. A guard that has only ever been
observed in its refusing state is indistinguishable from one that always
refuses.
"""

from __future__ import annotations

import json
import urllib.error

import pytest

from syndicate.features.shared import cryptocom_client


# --------------------------------------------------------------------------
# fake transport
# --------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, status: int, body: bytes) -> None:
        self.status = status
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _install(monkeypatch, by_url):
    """Route each URL to a body, an exception, or raise on an unexpected host.

    An unrouted URL is a test-authoring error and must fail loudly -- silently
    serving a default is how a probe test ends up asserting against a request
    that was never made.
    """

    def fake_urlopen(request, timeout=None):  # noqa: ANN001
        url = request.full_url
        for prefix, outcome in by_url.items():
            if url.startswith(prefix):
                if isinstance(outcome, Exception):
                    raise outcome
                return _FakeResponse(*outcome)
        raise AssertionError(f"probe() requested an unrouted URL: {url}")

    monkeypatch.setattr(
        "syndicate.features.shared.cryptocom_client.urllib.request.urlopen",
        fake_urlopen,
    )


_EXCHANGE = "https://api.crypto.com/exchange/v1/public/get-instruments"
_PROXY = "https://web.crypto.com/api/proxy/"

_CLOUDFLARE_HTML = (
    b"<!DOCTYPE html><html><head><title>Attention Required! | Cloudflare</title>"
    b"</head><body>Sorry, you have been blocked</body></html>"
)


def _instruments(rows):
    return (200, json.dumps({"id": -1, "method": "public/get-instruments", "code": 0,
                            "result": {"data": rows}}).encode())


_ALL_CRYPTO = _instruments(
    [
        {"symbol": "BTC_USD", "inst_type": "CCY_PAIR"},
        {"symbol": "BTCUSD-PERP", "inst_type": "PERPETUAL_SWAP"},
        {"symbol": "BTCUSD-260925", "inst_type": "FUTURE"},
    ]
)


# --------------------------------------------------------------------------
# FINDING -- what the record now says
# --------------------------------------------------------------------------


def test_finding_status_names_the_access_gap_not_a_missing_api():
    """The venue's data EXISTS and was read. What is absent is a sanctioned,
    server-readable path to it -- and the distinction is the whole finding,
    because the two send a future session to completely different places."""
    assert cryptocom_client.FINDING["status"] == "no_sanctioned_server_readable_api"
    assert cryptocom_client.FINDING["product"] == (
        "cryptocom_predictions_sports_event_contracts"
    )


def test_finding_does_not_repeat_the_falsified_no_api_claim():
    """Regression guard on the exact 2026-08-24 wording. A JSON endpoint
    serving sports events exists; anything asserting otherwise is a lie the
    next session would act on."""
    blob = json.dumps(cryptocom_client.FINDING).lower()
    assert "no public rest" not in blob
    assert "no_public_api_yet" not in blob


def test_finding_records_cloudflare_as_the_blocker_and_kalshi_units_as_the_prize():
    """Both halves matter. Without the first, someone rebuilds the client and
    gets HTML. Without the second, the venue looks not worth a contact form."""
    blob = json.dumps(cryptocom_client.FINDING).lower()
    assert "cloudflare" in blob
    assert "403" in blob
    assert "kalshi" in blob


def test_corrected_source_supersedes_the_rejection_and_still_names_the_endpoint():
    """The endpoint must stay NAMED. Dropping it would read as never
    considered rather than considered and found dead -- and the correction
    (it is Crypto.com's own sample, not a stranger's invention) is the part a
    future session needs in order not to re-reject it for a false reason."""
    corrected = cryptocom_client.FINDING["corrected_source"]
    assert "predictions/events" in corrected
    assert "exchange-pro" in corrected
    # The superseded key must be gone, not left beside its own correction.
    assert "rejected_source" not in cryptocom_client.FINDING


def test_finding_keeps_the_coverage_caveat_and_the_brand_ambiguity_open():
    """Two things measurement did NOT settle. Both are recorded as open rather
    than rounded off, because `polymarket_us_markets`'s header is what an
    unresolved venue identity costs."""
    assert "moneyline" in cryptocom_client.FINDING["coverage_caveat"].lower()
    assert "og.com" in cryptocom_client.FINDING["open_question"].lower()


# --------------------------------------------------------------------------
# probe() -- the gate, in both directions
# --------------------------------------------------------------------------


def test_probe_reports_blocked_when_the_catalogue_is_all_crypto(monkeypatch):
    """The 2026-08-28 production reading: 957 instruments, none an event
    contract, and the app proxy 403ing a plain client."""
    _install(monkeypatch, {_EXCHANGE: _ALL_CRYPTO, _PROXY: (403, _CLOUDFLARE_HTML)})
    result = cryptocom_client.probe()

    assert result["status"] == "ok"
    assert result["unblocked"] is False
    assert result["blocked_reason"] == "exchange_rest_lists_no_event_contracts"
    instruments = result["checks"]["exchange_rest"]["instruments"]
    assert instruments["instrument_count"] == 3
    assert instruments["non_crypto_count"] == 0
    assert instruments["by_inst_type"]["CCY_PAIR"] == 1


def test_probe_unblocks_only_on_a_non_crypto_instrument(monkeypatch):
    """OFF != ON. The same code path that refuses above must be shown to
    accept, or 'blocked' is indistinguishable from 'always blocks'."""
    _install(
        monkeypatch,
        {
            _EXCHANGE: _instruments(
                [
                    {"symbol": "BTC_USD", "inst_type": "CCY_PAIR"},
                    {"symbol": "MLB-NYY-260828", "inst_type": "EVENT_CONTRACT"},
                ]
            ),
            _PROXY: (403, _CLOUDFLARE_HTML),
        },
    )
    result = cryptocom_client.probe()

    assert result["unblocked"] is True
    assert result["blocked_reason"] is None
    non_crypto = result["checks"]["exchange_rest"]["instruments"]["non_crypto"]
    assert non_crypto == [{"inst_type": "EVENT_CONTRACT", "symbol": "MLB-NYY-260828"}]


def test_app_proxy_json_alone_can_never_unblock(monkeypatch):
    """Even if a plain client somehow got JSON out of the app proxy, an
    undocumented private BFF is not an integration surface. It is surfaced
    loudly for a human and it does not move the gate."""
    _install(
        monkeypatch,
        {
            _EXCHANGE: _ALL_CRYPTO,
            _PROXY: (200, json.dumps({"code": 0, "data": {"data": [{"id": "x"}]}}).encode()),
        },
    )
    result = cryptocom_client.probe()

    assert result["unblocked"] is False
    assert result["blocked_reason"] == "exchange_rest_lists_no_event_contracts"
    assert (
        result["checks"]["app_proxy"]["interpretation"]
        == "unexpected_server_side_json_investigate"
    )


def test_probe_names_a_bot_challenge_instead_of_reading_it_as_empty(monkeypatch):
    """HTML where JSON was expected is `kalshi_client`'s founding failure mode:
    parsed, it is indistinguishable from a venue that lists nothing."""
    _install(monkeypatch, {_EXCHANGE: _ALL_CRYPTO, _PROXY: (200, _CLOUDFLARE_HTML)})
    proxy = cryptocom_client.probe()["checks"]["app_proxy"]

    assert proxy["decoded_json"] is False
    assert proxy["looks_like_html"] is True
    assert proxy["looks_like_bot_challenge"] is True
    assert proxy["interpretation"] == "bot_challenge_html_not_json"


def test_unreadable_catalogue_shape_blocks_rather_than_reading_as_zero(monkeypatch):
    """`unknown must not default permissive` -- and its mirror: an unrecognised
    payload must not read as an empty catalogue either. Both would be silent."""
    _install(
        monkeypatch,
        {
            _EXCHANGE: (200, json.dumps({"code": 0, "result": {}}).encode()),
            _PROXY: (403, _CLOUDFLARE_HTML),
        },
    )
    result = cryptocom_client.probe()

    assert result["unblocked"] is False
    assert result["blocked_reason"] == "exchange_rest_unreadable:no_result_data_list"


@pytest.mark.parametrize(
    "boom, expected_error",
    [
        (urllib.error.URLError("connect_rejected"), "connect_rejected"),
        (urllib.error.HTTPError("url", 403, "forbidden", {}, None), "http_403"),
    ],
)
def test_probe_reports_a_named_error_when_nothing_reaches_the_venue(
    monkeypatch, boom, expected_error
):
    """A probe run from a network that cannot reach the venue at all must be
    distinguishable from one where the venue answered 'no'."""
    _install(monkeypatch, {_EXCHANGE: boom, _PROXY: boom})
    result = cryptocom_client.probe()

    assert result["status"] == "error"
    assert result["unblocked"] is False
    assert result["blocked_reason"] == "no_check_reached_the_venue"
    assert expected_error in result["error"]
    assert result["finding"] is cryptocom_client.FINDING


def test_one_reachable_check_is_not_reported_as_a_total_failure(monkeypatch):
    """The venue answering while the proxy refuses is the NORMAL reading, and
    it must not be flattened into `status=error` -- that would make the real
    finding look like a network fault."""
    _install(
        monkeypatch,
        {_EXCHANGE: _ALL_CRYPTO, _PROXY: urllib.error.URLError("connect_rejected")},
    )
    result = cryptocom_client.probe()

    assert result["status"] == "ok"
    assert "error" not in result
    assert result["checks"]["app_proxy"]["interpretation"].startswith(
        "unreadable_server_side:"
    )
