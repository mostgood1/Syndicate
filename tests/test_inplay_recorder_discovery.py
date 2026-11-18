"""The in-play recorder's Kalshi poll list and poll cycle (lane inplay-recorder-discovery, 2026-11-17).

Two defects, measured on NCAAF Saturday 2026-11-14 (C:/tmp/inplay_2026-11-14, 5,014 markets):
  * the list came only from the fleet capture file, which sat at its 8,000-market cap, so markets
    dropped out of the list (387 gaps > 120 s, 320 of them > 20 min);
  * each cycle fired its batches back to back (~5 req/s) from the top of the sorted list, and a 429
    ended the cycle, so the tail (NCAAF totals, NHL) was starved (90,485 gaps > 120 s).
These tests pin the fix: discovery from Kalshi's public listing, a list that never shrinks before
settlement, even pacing, and a 429 that resumes where it stopped.
"""

import sys
from pathlib import Path
from urllib.error import HTTPError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import inplay_recorder as rec  # noqa: E402


def _http429():
    return HTTPError("https://x", 429, "Too Many Requests", {}, None)


def _market(ticker, event):
    return {"ticker": ticker, "event_ticker": event, "status": "active"}


def test_date_code_is_kalshis_event_date_segment():
    assert rec.date_code("2026-11-14") == "26NOV14"
    assert rec.date_code("2027-01-03") == "27JAN03"
    assert rec.on_date("KXNCAAFGAME-26NOV14VALPSTET", "26NOV14")
    assert not rec.on_date("KXNCAAFGAME-26NOV21VALPSTET", "26NOV14")
    assert not rec.on_date("KXNCAAFGAME", "26NOV14")
    assert not rec.on_date(None, "26NOV14")


def test_discover_keeps_tonights_markets_follows_the_cursor_and_asks_only_listed_series():
    pages = {
        ("KXNCAAFSPREAD", ""): ({"markets": [_market("KXNCAAFSPREAD-26NOV14ABCDEF-ABC7", "KXNCAAFSPREAD-26NOV14ABCDEF"),
                                             _market("KXNCAAFSPREAD-26NOV21GHIJKL-GHI3", "KXNCAAFSPREAD-26NOV21GHIJKL")],
                                 "cursor": "c/2+="}),
        ("KXNCAAFSPREAD", "c/2+="): ({"markets": [_market("KXNCAAFSPREAD-26NOV14ABCDEF-DEF3", "KXNCAAFSPREAD-26NOV14ABCDEF")],
                                     "cursor": ""}),
        ("KXNCAAFGAME", ""): ({"markets": [_market("KXNCAAFGAME-26NOV14ABCDEF-ABC", "KXNCAAFGAME-26NOV14ABCDEF")]}),
        ("KXNCAAFTOTAL", ""): ({"markets": []}),
        ("KXNHLGAME", ""): ({"markets": [_market("KXNHLGAME-26NOV14BOSTOR-BOS", "KXNHLGAME-26NOV14BOSTOR")]}),
        ("KXNHLSPREAD", ""): ({"markets": []}),
    }
    asked = []

    def get(url, timeout=15.0):
        from urllib.parse import parse_qs, urlparse
        q = parse_qs(urlparse(url).query)
        assert q["status"] == ["open"]
        key = (q["series_ticker"][0], q.get("cursor", [""])[0])
        asked.append(key)
        return pages[key], {}

    paced = []
    found, errors = rec.discover_tickers(["ncaaf", "nhl"], "2026-11-14", get=get, pace=lambda: paced.append(1))
    assert found == ["KXNCAAFGAME-26NOV14ABCDEF-ABC", "KXNCAAFSPREAD-26NOV14ABCDEF-ABC7",
                     "KXNCAAFSPREAD-26NOV14ABCDEF-DEF3", "KXNHLGAME-26NOV14BOSTOR-BOS"]
    assert errors == []
    assert ("KXNCAAFSPREAD", "c/2+=") in asked  # the cursor survives URL quoting
    assert {s for s, _ in asked} == {"KXNCAAFGAME", "KXNCAAFSPREAD", "KXNCAAFTOTAL", "KXNHLGAME", "KXNHLSPREAD"}
    assert "KXNHLTOTAL" not in rec.FULL_GAME_SERIES["nhl"]  # stage-2 scoreboard population unchanged
    assert len(paced) == len(asked)  # every discovery request waits its turn


def test_discover_one_failing_series_leaves_the_others():
    slept = []

    def get(url, timeout=15.0):
        if "KXNBASPREAD" in url:
            raise _http429()
        if "KXNBAGAME" in url:
            return {"markets": [_market("KXNBAGAME-26NOV14BKNMEM-BKN", "KXNBAGAME-26NOV14BKNMEM")]}, {}
        return {"markets": []}, {}

    found, errors = rec.discover_tickers(["nba"], "2026-11-14", get=get, sleep=slept.append)
    assert found == ["KXNBAGAME-26NOV14BKNMEM-BKN"]
    assert len(errors) == 1 and errors[0].startswith("KXNBASPREAD")
    assert slept == [5.0]


def _write_capture(root, sport, date, tickers):
    import json
    p = rec.fleet_file(root, "kalshi", sport, date)
    p.write_text(json.dumps({"markets": {t: {"market": "spreads"} for t in tickers}}), encoding="utf-8")


def test_refresh_reachability_discovery_on_differs_from_off_and_nothing_drops_before_settlement(tmp_path):
    date = "2026-11-14"
    on_kalshi = "KXNCAAFTOTAL-26NOV14ZZZYYY-61"  # the capped capture file does not list it

    def get(url, timeout=15.0):
        if "KXNCAAFTOTAL" in url:
            return {"markets": [_market(on_kalshi, "KXNCAAFTOTAL-26NOV14ZZZYYY")]}, {}
        return {"markets": []}, {}

    _write_capture(tmp_path, "ncaaf", date, ["KXNCAAFSPREAD-26NOV14AAABBB-AAA7"])
    off, info_off = rec.refresh_tickers(set(), tmp_path, ["ncaaf"], date, [], discover=False, get=get)
    known = set()
    on, info_on = rec.refresh_tickers(known, tmp_path, ["ncaaf"], date, ["KXHELD-1"], discover=True, get=get)
    assert on_kalshi not in off and on_kalshi in on  # off != on
    assert "KXHELD-1" in on  # --extra-tickers still join
    assert info_on["discovered_only"] == 1 and info_off["discovered"] == 0
    # The capture file drops its market (the cap at work) and Kalshi stops listing ours (closed):
    _write_capture(tmp_path, "ncaaf", date, [])
    again, _ = rec.refresh_tickers(known, tmp_path, ["ncaaf"], date, [], discover=True,
                                   get=lambda url, timeout=15.0: ({"markets": []}, {}))
    assert again == on  # nothing leaves the list before its result is recorded


def _cycle(polled, start_at, fail_on_request=None, batch=100):
    """Run one poll_cycle with a fake Kalshi; return (tickers returned, requests, next start)."""
    seen, reqs = [], []

    def get(url, timeout=15.0):
        reqs.append(url)
        if fail_on_request is not None and len(reqs) == fail_on_request:
            raise _http429()
        tickers = url.split("tickers=", 1)[1].split(",")
        return {"markets": [{"ticker": t} for t in tickers]}, {}

    nxt = rec.poll_cycle(polled, start_at, batch, get, lambda: None, lambda ts, m: seen.append(m["ticker"]),
                         lambda e: None, sleep=lambda s: None)
    return seen, reqs, nxt


def test_poll_cycle_batches_100_and_a_full_pass_restarts_at_the_top():
    polled = [f"T{i:04d}" for i in range(250)]
    seen, reqs, nxt = _cycle(polled, "")
    assert seen == polled and nxt == ""
    assert [len(u.split("tickers=")[1].split(",")) for u in reqs] == [100, 100, 50]
    assert all("limit=100&" in u for u in reqs)


def test_poll_cycle_resumes_at_the_batch_a_429_stopped():
    polled = [f"T{i:04d}" for i in range(250)]
    seen, _, nxt = _cycle(polled, "", fail_on_request=2)
    assert seen == polled[:100] and nxt == "T0100"
    seen, _, nxt = _cycle(polled, nxt)
    assert seen[:150] == polled[100:] and seen[150:] == polled[:100] and nxt == ""
    # The list changed between cycles (the resume ticker settled): start at the next one.
    seen, _, _ = _cycle(polled[:100] + polled[101:], "T0100")
    assert seen[0] == "T0101"


def test_429s_every_cycle_no_longer_starve_the_tail():
    """11-14's shape: a 429 lands mid-cycle on most cycles. The old loop restarted at the top
    every time, so tickers after the 429 point were never polled; resuming covers them all."""
    polled = [f"T{i:04d}" for i in range(1000)]  # 10 requests per full pass
    seen_new, start = set(), ""
    for _ in range(6):
        s, _, start = _cycle(polled, start, fail_on_request=4)
        seen_new |= set(s)
    assert seen_new == set(polled)
    seen_old = set()
    for _ in range(6):
        s, _, _ = _cycle(polled, "", fail_on_request=4)  # the pre-fix behaviour: always from the top
        seen_old |= set(s)
    assert len(seen_old) == 300  # the other 700 starve


def test_pacer_spaces_requests_evenly():
    clock = [100.0]
    slept = []

    def sleep(s):
        slept.append(round(s, 6))
        clock[0] += s

    p = rec.Pacer(2.5, clock=lambda: clock[0], sleep=sleep)
    stamps = []
    for _ in range(4):
        p.wait()
        stamps.append(round(clock[0], 6))
    assert stamps == [100.0, 100.4, 100.8, 101.2]
    clock[0] += 5.0  # idle time is not banked into a burst
    p.wait()
    p.wait()
    assert round(clock[0] - 106.2, 6) == 0.4
