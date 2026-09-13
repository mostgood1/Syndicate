"""A quote-state publish refused at merge capacity is retried in-call.

Lane `quote-state-publish-retry`. Web answers HTTP 503 to a
`book_quotes/*.state.json` publish while another merge child is running. The
publisher used to leave that for next-sweep repair, so last-seen stamps reached
web minutes late. On 2026-09-13 that took live NFL props on the Layer 2 board
from 278 to 0 and back to 216 across three builds, because the in-play gate
kills a row whose last-seen age passes 300 s.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError

from syndicate.features.shared import artifact_publisher as ap

QUOTE_STATE = "nfl_source/tracking/book_quotes/2026-09-13.state.json"
NOT_QUOTE_STATE = "nfl_source/oddsapi_player_props_2026_wk1.csv"
PUBLISH_URL = "https://syndicate.onrender.com"


def _ok_response() -> MagicMock:
    response = MagicMock()
    response.__enter__.return_value = response
    response.read.return_value = b"{}"
    return response


def _http_error(code: int) -> HTTPError:
    return HTTPError(f"{PUBLISH_URL}/api/ops/artifacts/publish", code, "refused", hdrs=None, fp=None)


def _run(relative_path: str, side_effect, *, content: str = '{"k": [null, -110, "2026-09-13T22:40:19+00:00"]}'):
    with TemporaryDirectory() as tmp_dir:
        data_root = Path(tmp_dir)
        target = data_root / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        ap._LAST_PUBLISHED_CHECKSUM.clear()
        ap._LAST_PUBLISH_FAILURE_STATUS.clear()
        env = {
            "SYNDICATE_DATA_ROOT": str(data_root),
            "ADMIN_TOKEN": "secret-token",
            "SYNDICATE_WEB_PUBLISH_URL": PUBLISH_URL,
        }
        with patch.dict(os.environ, env, clear=False), \
                patch.object(ap, "_publish_refused_no_producer_input", return_value=""), \
                patch.object(ap, "_publish_refused_as_empty", return_value=False), \
                patch.object(ap, "_publish_budget_blocks", return_value=False), \
                patch.object(ap, "_retry_sleep") as sleep, \
                patch("urllib.request.urlopen", side_effect=side_effect) as urlopen:
            result = ap.publish_hot_artifact(target)
        return result, urlopen, sleep


def test_quote_state_refused_at_capacity_then_accepted_is_published_in_call():
    result, urlopen, sleep = _run(QUOTE_STATE, [_http_error(503), _ok_response()])
    assert result is True
    assert urlopen.call_count == 2
    sleep.assert_called_once_with(ap._QUOTE_STATE_RETRY_DELAYS_SECONDS[0])
    body = json.loads(urlopen.call_args.args[0].data.decode("utf-8"))
    assert body["relative_path"] == QUOTE_STATE
    assert QUOTE_STATE not in ap._FAILED_DIRECT_PUBLISH


def test_quote_state_refused_every_attempt_gives_up_and_stays_marked_for_repair():
    attempts = 1 + len(ap._QUOTE_STATE_RETRY_DELAYS_SECONDS)
    result, urlopen, sleep = _run(QUOTE_STATE, [_http_error(503)] * attempts)
    assert result is False
    assert urlopen.call_count == attempts
    assert sleep.call_count == len(ap._QUOTE_STATE_RETRY_DELAYS_SECONDS)
    assert QUOTE_STATE in ap._FAILED_DIRECT_PUBLISH


def test_a_non_quote_state_path_is_not_retried():
    result, urlopen, sleep = _run(NOT_QUOTE_STATE, [_http_error(503), _ok_response()], content="a,b\n1,2\n")
    assert result is False
    assert urlopen.call_count == 1
    sleep.assert_not_called()


def test_a_quote_state_failure_that_is_not_503_is_not_retried():
    result, urlopen, sleep = _run(QUOTE_STATE, [_http_error(500), _ok_response()])
    assert result is False
    assert urlopen.call_count == 1
    sleep.assert_not_called()


def test_the_streamed_form_is_retried_too():
    # MLB's state sidecar is large enough to take the streamed form.
    with patch.object(ap, "_should_stream_publish", return_value=True), \
            patch.object(ap, "_gzip_publish_enabled", return_value=False):
        result, urlopen, sleep = _run(QUOTE_STATE, [_http_error(503), _ok_response()])
    assert result is True
    assert urlopen.call_count == 2
    assert urlopen.call_args.args[0].get_header("X-artifact-path") == QUOTE_STATE
    sleep.assert_called_once()
