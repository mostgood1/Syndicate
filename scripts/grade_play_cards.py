"""Grade the Syndicate ROI play-card ledger (lane `play-cards`): EV at the closing line, then the result.

For every card in `<data root>/playcards/ledger.jsonl` whose game started > 4 h ago and is not yet graded:

  close   from the fleet quote logs (`<sport>_source/tracking/book_quotes/`): each book's LAST quote at or before
          kickoff on the card's exact line, both sides -> per-book Shin fair -> median. Reported: the closing fair
          probability of the card's side, EV of the CARD's price at that fair, and CLV = closing fair minus the
          fair when the card was made. EV at the close is the honest skill number: it does not wait for luck.
  result  through production's own grader (`score_ranking_backtest.py pull --source recorder`, the path the
          nightly scorecard uses), matched on sport + date + market + player + side + line; units at the CARD's
          price (1 unit staked; push 0).

Rewrites the ledger atomically and renders `<data root>/playcards/record.html` (branded): the running record, units,
mean EV at the close, every card. Then, for every settled card (lane `result-cards`, user 2026-10-16), a RESULT card
beside its pregame card (`<date>/<nn>_<sport>_<id>_result.png`: the result, the final, line vs sim vs actual, the
close, what happened and the verdict) and `<data root>/playcards/postmortem.jsonl`, one engine-ledger record per graded
card, rewritten whole each run. Read-only otherwise; no OddsAPI.

    py -3 scripts/grade_play_cards.py --data-root //wsl.localhost/Ubuntu-24.04/home/amyn/syndicate-prod/data
"""
from __future__ import annotations

import argparse
import base64
import gzip
import html
import importlib.util
import json
import os
import statistics
import sys
import tempfile
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.shared.basketball_props_availability import player_key  # noqa: E402
from syndicate.features.shared.opportunity_signals import devig  # noqa: E402
from syndicate.features.shared.play_cards import fmt_american  # noqa: E402

LOGO = REPO_ROOT / "syndicate" / "static" / "brand" / "syndicate_roi_badge.webp"
SETTLE_AFTER = timedelta(hours=4)


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def decimal(american: float) -> float:
    a = float(american)
    return 1 + (a / 100 if a > 0 else 100 / -a)


_NPF = None


def _npf():
    global _NPF
    if _NPF is None:
        _NPF = _load("news_price_follow")
    return _NPF


def central_date(ts: datetime) -> str:
    from syndicate.features.shared.play_cards import central

    return central(ts).date().isoformat()


def closing_fair(quotes: list[dict[str, Any]], card: dict[str, Any]) -> dict[str, Any] | None:
    """Median per-book Shin fair of the card's side from each book's last two-sided quote at or before kickoff."""
    npf = _npf()
    commence = npf.parse_ts(card.get("commence_time"))
    if commence is None:
        return None
    pkey, line, market = player_key(card.get("player")), card.get("line"), card.get("market")
    latest: dict[tuple[str, str], dict[str, Any]] = {}
    for q in quotes:
        if str(q.get("event_id")) != str(card.get("event_id")) or q.get("market") != market:
            continue
        if player_key(q.get("player_name")) != pkey or q.get("line") != line:
            continue
        ts = npf.parse_ts(q.get("captured_at"))
        if ts is None or ts > commence:
            continue
        k = (q.get("bookmaker"), str(q.get("selection") or "").lower())
        if k not in latest or ts >= npf.parse_ts(latest[k].get("captured_at")):
            latest[k] = q
    by_book: dict[str, dict[str, float]] = defaultdict(dict)
    for (book, sel), q in latest.items():
        by_book[book][sel] = float(q["price"])
    side = str(card.get("side") or "").lower()
    fairs, best = [], None
    for book, sides in by_book.items():
        if len(sides) != 2 or side not in sides:
            continue
        names = sorted(sides)
        probs = devig([sides[n] for n in names], method="shin")
        if probs:
            fairs.append(dict(zip(names, probs))[side])
            best = sides[side] if best is None or decimal(sides[side]) > decimal(best) else best
    if not fairs:
        return None
    p = statistics.median(fairs)
    return {"p_close": round(p, 4), "books": len(fairs), "best_close_price": best,
            "ev_close_pct": round(100 * (p * decimal(card["price"]) - 1), 2),
            "clv_pp": None if card.get("p_market") is None else round(100 * (p - float(card["p_market"])), 2)}


def closing_fairs(root: Path, sport: str, day: str, cards: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """card_id -> the closing fair (as `closing_fair`) for MANY cards in one streaming pass over the day's and the next
    day's quote files, parsing only lines for the cards' own events -- a nightly sheet of hundreds of rows must not
    load eleven days of quotes the way one card can."""
    events = {str(c.get("event_id")) for c in cards if c.get("event_id")}
    if not events:
        return {}
    directory = root / f"{sport}_source" / "tracking" / "book_quotes"
    nxt = (datetime.fromisoformat(day) + timedelta(days=1)).date().isoformat()
    quotes: list[dict[str, Any]] = []
    for name in (day, nxt):
        # A day's log is gzipped the next evening (NBA ~9:09 PM CT). Reading only `.jsonl` made every LATER reconcile
        # find no close and rewrite each graded verdict as `no_close` (10-20 58 of 58, 10-21 60 -> 0, measured 10-23).
        path = directory / f"{name}.jsonl"
        packed = directory / f"{name}.jsonl.gz"
        if path.is_file():
            opener = lambda p=path: p.open(encoding="utf-8")                      # noqa: E731
        elif packed.is_file():
            opener = lambda p=packed: gzip.open(p, "rt", encoding="utf-8")       # noqa: E731
        else:
            continue
        with opener() as fh:
            for line in fh:
                if not any(e in line for e in events):
                    continue
                try:
                    q = json.loads(line)
                except ValueError:
                    continue
                if q.get("price") is not None and str(q.get("event_id")) in events:
                    quotes.append(q)
    by_event: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for q in quotes:
        by_event[str(q.get("event_id"))].append(q)
    out = {}
    for c in cards:
        fair = closing_fair(by_event.get(str(c.get("event_id")), []), c) if c.get("price") is not None else None
        if fair:
            out[str(c["card_id"])] = fair
    return out


def match_key(sport: Any, market: Any, player: Any, side: Any, line: Any) -> tuple:
    """The population key's own normalisation: market and side lower-cased, line a float or None."""
    return (str(sport or "").lower(), str(market or "").strip().lower(), player_key(player), str(side or "").lower(),
            None if line in (None, "") else float(line))


def _pick_key(player: Any, market: Any, side: Any, line: Any, segment: Any, event_id: Any) -> str:
    from syndicate.features.shared.cheat_sheets import pick_result_key

    return pick_result_key({"player_name": player, "market": market, "side": side, "line": line,
                            "segment": segment or "full", "event_id": event_id})


def results_for(cards: list[dict[str, Any]], *, work: Path) -> dict[str, dict[str, Any]]:
    """card_id -> {y, units} through production's grader, one pull per date."""
    srb = _load("score_ranking_backtest")
    out: dict[str, dict[str, Any]] = {}
    # The recorder files a side under the board date it was SEEN on, so pull the card's date and the game's own date.
    by_date: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for c in cards:
        dates = {c["date"]}
        commence = _npf().parse_ts(c.get("commence_time"))
        if commence is not None:
            dates.add(central_date(commence))
        for d in dates:
            by_date[d].append(c)
    for date, group in sorted(by_date.items()):
        sports = ",".join(sorted({c["sport"] for c in group}))
        graded_path = work / f"graded_{date}.jsonl"
        srb.main(["pull", "--start", date, "--end", date, "--sports", sports, "--source", "recorder", "--out", str(graded_path)])
        index: dict[tuple, dict[str, Any]] = {}
        by_pick: dict[str, dict[str, Any]] = {}
        for line in graded_path.read_text(encoding="utf-8").splitlines() if graded_path.is_file() else []:
            g = json.loads(line)
            if g.get("y") is None:
                continue
            # A Syndicate pick (2026-10-15) can be a game line or a segment: it grades on ITS key, segment included.
            by_pick.setdefault(_pick_key(g.get("player"), g.get("market"), g.get("side"), g.get("line"), g.get("segment"),
                                         str(g.get("game") or "").split("|", 1)[-1]), g)
            if str(g.get("segment") or "full") == "full":
                index[match_key(g.get("sport"), g.get("market"), g.get("player"), g.get("side"), g.get("line"))] = g
        for c in group:
            if c.get("pick_id"):
                g = by_pick.get(_pick_key(c.get("player"), c.get("market"), c.get("side"), c.get("line"), c.get("segment"),
                                          c.get("event_id")))
            else:
                g = index.get(match_key(c["sport"], c["market"], c["player"], c["side"], c["line"]))
            if g is None or c["card_id"] in out:
                continue
            y = float(g["y"])
            units = round(decimal(c["price"]) - 1, 3) if y == 1 else (-1.0 if y == 0 else 0.0)
            out[c["card_id"]] = {"y": y, "units": units, "graded_game": g.get("game")}
    return out


def render_record(cards: list[dict[str, Any]], path: Path) -> None:
    from syndicate.features.shared.play_cards import OFFICIAL_START

    cards = [c for c in cards if str(c.get("date") or "") >= OFFICIAL_START]     # beta cards are never in the record
    done = [c for c in cards if c.get("result")]
    w = sum(1 for c in done if c["result"]["y"] == 1)
    l = sum(1 for c in done if c["result"]["y"] == 0)
    units = round(sum(c["result"]["units"] for c in done), 2)
    evs = [c["close"]["ev_close_pct"] for c in cards if c.get("close")]
    logo = "data:image/webp;base64," + base64.b64encode(LOGO.read_bytes()).decode()
    e = lambda s: html.escape(str(s if s is not None else ""))
    rows = "".join(
        f"<tr><td>{e(c['date'])}</td><td>{e(c['sport']).upper()}</td><td>{e(c['player'])}</td><td>{e(c['side']).upper()} {e(c['line'])} {e(c['market'])}</td>"
        f"<td>{e(fmt_american(c['price']))} {e(c['book'])}</td><td>{e(c.get('ev_market'))}%</td>"
        f"<td>{e((c.get('close') or {}).get('ev_close_pct', '-'))}</td>"
        f"<td class='{ {1.0: 'w', 0.0: 'l'}.get((c.get('result') or {}).get('y'), 'p') }'>"
        f"{ {1.0: 'WIN', 0.0: 'LOSS'}.get((c.get('result') or {}).get('y'), 'PENDING' if not c.get('result') else 'PUSH') }</td>"
        f"<td>{e((c.get('result') or {}).get('units', ''))}</td></tr>" for c in sorted(cards, key=lambda c: c['generated_at'], reverse=True))
    path.write_text(f"""<!doctype html><meta charset="utf-8"><title>Syndicate ROI Record</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Saira+Condensed:wght@800;900&family=Barlow:wght@500;600&display=swap">
<style>body{{background:#04070c;color:#eef3f7;font-family:Barlow,Arial,sans-serif;margin:0;padding:24px}}
h1{{font:900 48px Saira Condensed,Impact,sans-serif;margin:0;transform:skewX(-8deg)}} .g{{color:#8cff2e}}
.top{{display:flex;gap:16px;align-items:center}} img{{width:80px;border-radius:10px;box-shadow:0 0 0 2px #8cff2e}}
.band{{display:flex;gap:14px;flex-wrap:wrap;margin:18px 0}} .s{{border:2px solid #1d3a55;border-radius:10px;padding:10px 16px;background:#0a1520}}
.s b{{display:block;font:900 34px Saira Condensed,sans-serif;color:#8cff2e}} table{{border-collapse:collapse;width:100%;font-size:14px}}
th,td{{text-align:left;padding:8px;border-top:1px solid #183044}} th{{color:#1fa8ff;font:800 14px Saira Condensed,sans-serif;letter-spacing:.06em}}
td.w{{color:#8cff2e;font-weight:600}} td.l{{color:#ff5a4a;font-weight:600}} td.p{{color:#9db0bf}} .wrap{{overflow-x:auto}}</style>
<div class="top"><img src="{logo}" alt="Syndicate ROI"><h1>SYNDICATE ROI <span class="g">RECORD</span></h1></div>
<p>Every card the generator made, graded at the closing line and on the result. We post the wins. We post the losses.</p>
<div class="band"><div class="s"><b>{w}-{l}</b>record</div><div class="s"><b>{units:+.2f}u</b>units at the card price</div>
<div class="s"><b>{(statistics.mean(evs) if evs else 0):+.2f}%</b>mean EV at the close ({len(evs)} cards)</div><div class="s"><b>{len(cards)}</b>cards generated</div></div>
<div class="wrap"><table><thead><tr><th>Date</th><th>Sport</th><th>Player</th><th>Bet</th><th>Price</th><th>Edge at card</th><th>EV at close</th><th>Result</th><th>Units</th></tr></thead><tbody>{rows}</tbody></table></div>""",
                    encoding="utf-8")


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def render_results(cards: list[dict[str, Any]], root: Path, *, out_dir: Path | None = None, png: bool = True,
                   usage: Any = None, cache: Path | None = None) -> dict[str, int]:
    """A RESULT card for every settled card (rendered once: an existing PNG is kept) and the engine ledger. `usage` is
    an optional callable (card, item) -> box-score usage dict (opportunity vs efficiency)."""
    from syndicate.features.shared import play_card_results as pcr
    from syndicate.features.shared import play_cards as pc

    bpc = _load("build_play_cards")
    out_dir = out_dir or (root / "playcards")
    cache = cache or (root / "cheatsheets" / ".img_cache")
    sheets: dict[tuple[str, str], Any] = {}
    pairs, post, missing = [], [], 0
    for c in pcr.iter_due(cards):
        key = (c["sport"], c["date"])
        if key not in sheets:
            base = root / "cheatsheets" / c["sport"]
            sheets[key] = (_read_json(base / f"{c['date']}.json"), _read_json(base / f"{c['date']}.reconciled.json"))
        sheet, rec = sheets[key]
        item = pcr.find_item(sheet or {}, c)
        if item is None:
            missing += 1
            continue
        number = pc.card_number(cards, c["date"], c["card_id"])
        if c.get("pick_id"):
            fields = pc.pick_card_fields(dict(item), sport=c["sport"], date=c["date"], number=number)
        else:
            games = {g.get("event_id"): g for g in (sheet or {}).get("games") or []}
            fields = pc.card_fields(dict(item), sport=c["sport"], date=c["date"], number=number, game=games.get(item.get("event_id")))
        if not fields.get("hero") and fields.get("headshot"):          # a sheet built before hero caching (10-16)
            from syndicate.features.shared import brand_kit

            fields["hero"] = brand_kit.hero_url(c["sport"], fields["headshot"])
        score = ((rec or {}).get("scores") or {}).get(str(c.get("event_id")))
        found = usage(c, item) if callable(usage) else None
        overrides, classification = pcr.result_overrides(fields, item, c, entry=pcr.reconciled_entry(rec, item), score=score,
                                                         usage=found)
        post.append(pcr.postmortem(dict(c, label=c.get("label") or fields.get("label")), item, classification))
        html_path = out_dir / c["date"] / f"{number:02d}_{c['sport']}_{c['card_id']}_result.html"
        if html_path.with_suffix(".png").exists():
            continue
        html_path.parent.mkdir(parents=True, exist_ok=True)
        badge = pc.BRAND_DIR / pc.badge_name(c["sport"])
        logo = "data:image/webp;base64," + base64.b64encode(badge.read_bytes()).decode()
        html_path.write_text(pc.render_card(bpc.embed_card_images(fields, cache), logo, overrides=overrides), encoding="utf-8")
        pairs.append((html_path, html_path.with_suffix(".png")))
    pngs = bpc.to_png(pairs) if png and pairs else 0
    ledger = out_dir / "postmortem.jsonl"
    ledger.parent.mkdir(parents=True, exist_ok=True)
    tmp = ledger.with_name(ledger.name + ".tmp")
    tmp.write_text("".join(json.dumps(r, default=str) + "\n" for r in post), encoding="utf-8")
    os.replace(tmp, ledger)
    return {"settled": len(post) + missing, "rendered": len(pairs), "png": pngs, "postmortem": len(post), "no_sheet_item": missing}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--data-root", default=os.environ.get("SYNDICATE_DATA_ROOT") or "")
    ap.add_argument("--no-results", action="store_true", help="closing-line EV only (no production pull)")
    ap.add_argument("--now", default=None, help="ISO instant to settle as of (default: now)")
    ap.add_argument("--no-result-cards", action="store_true", help="grade only: no result cards, no postmortem ledger")
    args = ap.parse_args(argv)
    if not args.data_root:
        print("REFUSING: no --data-root", flush=True)
        return 2
    root = Path(os.path.expanduser(args.data_root))
    ledger = root / "playcards" / "ledger.jsonl"
    if not ledger.is_file():
        print("PLAY_CARDS_GRADE no ledger yet", flush=True)
        return 0
    cards = [json.loads(x) for x in ledger.read_text(encoding="utf-8").splitlines() if x.strip()]
    npf = _npf()
    now = npf.parse_ts(args.now) if args.now else datetime.now(timezone.utc)
    due = [c for c in cards if c.get("result") is None and (npf.parse_ts(c.get("commence_time")) or now) <= now - SETTLE_AFTER]
    for sport in sorted({c["sport"] for c in due if c.get("close") is None}):
        group = [c for c in due if c["sport"] == sport and c.get("close") is None]
        quotes = npf.load_quotes(root, sport, min(c["date"] for c in group), max(c["date"] for c in group))
        for c in group:
            c["close"] = closing_fair(quotes, c)
    if due and not args.no_results:
        with tempfile.TemporaryDirectory() as work:
            for card_id, res in results_for(due, work=Path(work)).items():
                for c in cards:
                    if c["card_id"] == card_id:
                        c["result"] = res
    tmp = ledger.with_name(ledger.name + ".tmp")
    tmp.write_text("".join(json.dumps(c, default=str) + "\n" for c in cards), encoding="utf-8")
    os.replace(tmp, ledger)
    render_record(cards, root / "playcards" / "record.html")
    if not args.no_result_cards:
        from syndicate.features.shared import box_usage

        usage = lambda card, item: box_usage.usage_for(card, item, cache=root / "playcards" / ".usage_cache", data_root=root)
        print(f"PLAY_CARDS_RESULTS {json.dumps(render_results(cards, root, usage=usage))}", flush=True)
    graded = [c for c in cards if c.get("result")]
    print(f"PLAY_CARDS_GRADE cards={len(cards)} due={len(due)} closed={sum(1 for c in cards if c.get('close'))} "
          f"graded={len(graded)} units={round(sum(c['result']['units'] for c in graded), 2)}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
