"""Serves the daily cheat sheets `scripts/build_cheat_sheets.py` writes (lane `cheat-sheets`, user 2026-10-14).

Read-only, like `model_scorecard.py`: every route returns what the generator already wrote to
`<data root>/cheatsheets/<sport>/<date>.json`. The evidence behind a sheet costs 1-12 s per player on the
fleet, so it is never built on a request (the web/worker split in CLAUDE.md); a missing sheet is a 404 that
names what is missing, or an empty page, never an on-request rebuild. Images are the generator's cached copies.

    /cheatsheets                          TODAY's sheets (US Central); ?date= opens a past day's record,
                                          ?sport= / ?game= open one sport / one game's own sheet
    /cheatsheets/card/<sport>/<date>/<id> one pick's branded graphic (only rows whose price check passes)
    /cheatsheets/img/<key>.webp           a cached headshot / logo
    /api/cheatsheets                      which sports and dates exist
    /api/cheatsheets/<sport>/<date>       one sheet as written
    POST /api/cheatsheets/cards           a pick graphic was exported: append it to the graded play-card ledger
    POST /api/cheatsheets/posted          a section graphic was exported: record its rows as posted (they stay featured)

A day's sheet is a record: games that started keep the rows the last build gave them (the generator merges).
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from flask import Blueprint, Response, jsonify, render_template_string, request, send_file

from syndicate.features.shared import cheat_sheet_images as images
from syndicate.features.shared import cheat_sheets as cs
from syndicate.features.shared import play_cards as pc

cheat_sheets_bp = Blueprint("cheat_sheets", __name__)

_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_SPORT = re.compile(r"^[a-z]{2,8}$")
_CARD = re.compile(r"^(?:[0-9a-f]{12}|l2_[0-9a-f]{8,40})$")   # a row's card id, or a Syndicate pick's board pick_id
_ROW_ID = re.compile(r"^[0-9a-f]{12}$")
_SGP_ID = re.compile(r"^sgp_[0-9a-f]{12}$")
_SECTION = re.compile(r"^[a-z_]{1,24}$")
# Sections whose items are already a record (the Syndicate picks) or are not bets (the slate, scripts, news, ladder).
_NOT_POSTED = frozenset({"picks", "ladder", "slate", "script", "news", "record", "record_chart", "record_days",
                         "record_totals"})
TEMPLATE = Path(__file__).resolve().parents[1] / "templates" / "cheat_sheets.html"
LOGO_SRC = "/static/brand/syndicate_roi_badge.webp"


def _data_root() -> Path:
    from syndicate.features.shared.refresh_state_store import data_root

    return Path(data_root())


def _sheet_dir() -> Path:
    return _data_root() / "cheatsheets"


def _today() -> str:
    return pc.central(datetime.now(timezone.utc)).date().isoformat()


def _tomorrow(today: str) -> str:
    from datetime import date, timedelta

    return (date.fromisoformat(today) + timedelta(days=1)).isoformat()


def _dates(sport: str) -> list[str]:
    folder = _sheet_dir() / sport
    if not folder.is_dir():
        return []
    return sorted(p.stem for p in folder.glob("*.json") if _DAY.match(p.stem))


def _read(sport: str, day: str) -> dict[str, Any] | None:
    try:
        doc = json.loads((_sheet_dir() / sport / f"{day}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not (isinstance(doc, dict) and doc.get("sport") == sport):
        return None
    # The results, when `scripts/reconcile_cheat_sheets.py` has graded the day: `cs.page_payload` attaches them.
    try:
        rec = json.loads((_sheet_dir() / sport / f"{day}.reconciled.json").read_text(encoding="utf-8"))
        if isinstance(rec, dict) and rec.get("sport") == sport and rec.get("date") == day:
            doc["reconciled"] = rec
    except (OSError, ValueError):
        pass
    posted = cs.load_posted(_sheet_dir(), sport, day)    # exported graphics: `cs.page_payload` pins their rows
    if posted:
        doc["posted"] = posted
    cross = _cross(sport, day)
    if cross:
        doc["cross"] = cross
    return doc


def _cross(sport: str, day: str) -> dict[str, Any] | None:
    """The day's cross-game parlays that have a leg in `sport` (`scripts/build_cheat_sheets.attach_cross_game`), each
    with its result once the reconcile has graded it (`<day>.graded.json`). They live beside `cheatsheets/`, in
    `cheatsheets_cross/`, because every directory inside it is read as a sport."""
    root = _sheet_dir().parent / "cheatsheets_cross"
    try:
        doc = json.loads((root / f"{day}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    try:
        graded = json.loads((root / f"{day}.graded.json").read_text(encoding="utf-8")).get("tickets") or {}
    except (OSError, ValueError, AttributeError):
        graded = {}
    def with_result(t: dict[str, Any]) -> dict[str, Any]:
        return dict(t, **({"result": graded[t["xg_id"]]} if t.get("xg_id") in graded else {}))

    kinds = {}
    for kind, tickets in ((doc or {}).get("kinds") or {}).items():
        mine = [with_result(t) for t in tickets or [] if any(leg.get("sport") == sport for leg in t.get("legs") or [])]
        if mine:
            kinds[kind] = mine
    # This sport alone, across its games (2026-10-20: "we also need single sport, cross slate plays").
    single = {kind: [with_result(t) for t in tickets or []]
              for kind, tickets in (((doc or {}).get("by_sport") or {}).get(sport) or {}).items() if tickets}
    if not kinds and not single:
        return None
    return {"generated_at": doc.get("generated_at"), "kinds": kinds, "single": single}


def _sports() -> list[str]:
    root = _sheet_dir()
    if not root.is_dir():
        return []
    return [p.name for p in sorted(root.iterdir()) if p.is_dir() and _SPORT.match(p.name)]


@cheat_sheets_bp.get("/api/cheatsheets")
def cheat_sheets_index():
    return jsonify({"ok": True, "today": _today(), "sports": {s: _dates(s)[-14:] for s in _sports()}}), 200


@cheat_sheets_bp.get("/api/cheatsheets/<sport>/<day>")
def cheat_sheet_one(sport: str, day: str):
    if not _SPORT.match(sport) or not _DAY.match(day):
        return jsonify({"ok": False, "error": "sport must be a slug and day YYYY-MM-DD"}), 400
    doc = _read(sport, day)
    if doc is None:
        return jsonify({"ok": False, "error": "not_published", "path": f"cheatsheets/{sport}/{day}.json"}), 404
    return jsonify(doc), 200


@cheat_sheets_bp.get("/cheatsheets/img/<key>.webp")
def cheat_sheet_image(key: str):
    if not images.KEY_RE.match(key):
        return jsonify({"ok": False, "error": "bad key"}), 400
    path = images.cache_dir(_data_root()) / f"{key}.bin"
    if not path.is_file() or not path.stat().st_size:
        return jsonify({"ok": False, "error": "not cached"}), 404
    head = path.read_bytes()[:4]
    mime = "image/webp" if head == b"RIFF" else "image/png" if head == b"\x89PNG" else "image/jpeg"
    response = send_file(path, mimetype=mime, max_age=7 * 86400)
    return response


@cheat_sheets_bp.get("/cheatsheets")
def cheat_sheets_page():
    today = _today()
    day = str(request.args.get("date") or "").strip() or today
    if not _DAY.match(day):
        return jsonify({"ok": False, "error": "date must be YYYY-MM-DD"}), 400
    sheets, dates = [], set()
    for sport in _sports():
        have = _dates(sport)
        dates.update(have)
        doc = _read(sport, day) if day in have else None
        if doc and (doc.get("rows") or doc.get("game_lines") or doc.get("picks")):
            sheets.append(doc)
    try:
        template = TEMPLATE.read_text(encoding="utf-8")
    except OSError:
        return jsonify({"ok": False, "error": "template missing"}), 500
    meta = {"mode": "app", "date": day, "today": today, "beta": day < pc.OFFICIAL_START,
            "dates": sorted({d for d in dates if d <= _tomorrow(today)} | {today}, reverse=True)[:14],
            "logos": {sport: f"/static/brand/{pc.badge_name(sport)}" for sport in cs.SPORT_ORDER}}
    page = cs.render_page(template, sheets, logo_src=LOGO_SRC, meta=meta)
    # The site menu, the same header every standalone page includes. The page template itself stays plain HTML so
    # `scripts/render_cheat_sheets.py` can render the identical page without Flask (the published artifact).
    page = page.replace("<!--__SITE_HEAD__-->", render_template_string(_SITE_HEAD), 1)
    page = page.replace("<!--__SITE_HEADER__-->", render_template_string(_SITE_HEADER, active_sport_slug="cheatsheets"), 1)
    return Response(page, mimetype="text/html")


def _record() -> dict[str, Any] | None:
    try:
        doc = json.loads((_sheet_dir() / "record.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) else None


@cheat_sheets_bp.get("/api/cheatsheets/record")
def cheat_sheets_record_api():
    doc = _record()
    if doc is None:
        return jsonify({"ok": False, "error": "not_published", "path": "cheatsheets/record.json"}), 404
    return jsonify(doc), 200


@cheat_sheets_bp.get("/cheatsheets/record")
def cheat_sheets_record_page():
    """The running season record (user 2026-10-15). `scripts/reconcile_cheat_sheets.py` writes `record.json` after
    every grading run; this only reads it."""
    try:
        template = TEMPLATE.read_text(encoding="utf-8")
    except OSError:
        return jsonify({"ok": False, "error": "template missing"}), 500
    meta = {"mode": "app", "page": "record", "today": _today()}
    page = cs.render_record_page(template, _record(), logo_src=LOGO_SRC, meta=meta)
    page = page.replace("<!--__SITE_HEAD__-->", render_template_string(_SITE_HEAD), 1)
    page = page.replace("<!--__SITE_HEADER__-->", render_template_string(_SITE_HEADER, active_sport_slug="cheatsheets"), 1)
    return Response(page, mimetype="text/html")


def _card_row(sport: str, day: str, card: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None, str]:
    """(row, game, reason) -- the sheet row (or Syndicate pick) whose card id this is, re-derived from the sheet (never
    the client). A pick is returned with `pick_id` set; its game is None and the sheet rides along as `_sheet`."""
    if not _SPORT.match(sport) or not _DAY.match(day) or not _CARD.match(card):
        return None, None, "bad request"
    doc = _read(sport, day)
    if doc is None:
        return None, None, "no sheet for that sport and day"
    for p in doc.get("picks") or []:
        if p.get("pick_id") == card:
            return dict(p, _sheet=doc), None, ""
    for r in doc.get("rows") or []:
        if pc.card_id(sport, day, r) == card:
            if not pc.eligible(r):
                return None, None, "this pick's price does not clear the fair, so it gets no pick graphic"
            game = next((g for g in doc.get("games") or [] if g.get("event_id") == r.get("event_id")), None)
            return r, game, ""
    return None, None, "no such pick on that sheet"


def _local_images(row: dict[str, Any], game: dict[str, Any] | None) -> tuple[dict[str, Any], dict[str, Any]]:
    """The card draws the generator's cached copies (same origin, so the PNG export can read them)."""
    row = dict(row, headshot_url=row.get("headshot_card_src") or row.get("headshot_src") or row.get("headshot_url"),
               team_logo=row.get("team_logo_card_src") or row.get("team_logo_src") or row.get("team_logo"))
    if game:
        game = dict(game, home_logo=game.get("home_logo_card_src") or game.get("home_logo_src") or game.get("home_logo"),
                    away_logo=game.get("away_logo_card_src") or game.get("away_logo_src") or game.get("away_logo"))
    return row, game


def _fields(row: dict[str, Any], game: dict[str, Any] | None, *, sport: str, day: str, number: int) -> dict[str, Any]:
    """The card for a sheet row, or for a Syndicate pick (the board's suggested opp, 2026-10-15)."""
    if row.get("pick_id"):
        sheet = row.pop("_sheet", {}) or {}
        pick = dict(row, headshot_url=row.get("headshot_card_src") or row.get("headshot_src") or row.get("headshot_url"),
                    team_logo=row.get("team_logo_card_src") or row.get("team_logo_src") or row.get("team_logo"),
                    home_logo=row.get("home_logo_card_src") or row.get("home_logo_src") or row.get("home_logo"),
                    away_logo=row.get("away_logo_card_src") or row.get("away_logo_src") or row.get("away_logo"))
        values, labels = pc.pick_form(sheet, pick) if pick.get("kind") == "prop" else ([], [])
        return pc.pick_card_fields(pick, sport=sport, date=day, number=number, form_values=values, form_labels=labels)
    row, game = _local_images(row, game)
    return pc.card_fields(row, sport=sport, date=day, number=number, game=game)


@cheat_sheets_bp.get("/cheatsheets/card/<sport>/<day>/<card>")
def cheat_sheet_card(sport: str, day: str, card: str):
    row, game, reason = _card_row(sport, day, card)
    if row is None:
        return jsonify({"ok": False, "error": reason}), 404
    number = pc.card_number(pc.read_ledger(pc.ledger_path(_data_root())), day, card)
    fields = _fields(row, game, sport=sport, day=day, number=number)
    html = pc.render_card(fields, f"/static/brand/{pc.badge_name(sport)}")
    back = f"/cheatsheets?{'date=' + day + '&' if day != _today() else ''}sport={sport}"
    toolbar = _CARD_TOOLBAR.replace("__SPORT__", sport).replace("__DAY__", day).replace("__CARD__", card) \
        .replace("__BACK__", back).replace("__FILE__", f"syndicate-{sport}-{day}-pick-{number}.png")
    return Response(html.replace("</body>", toolbar + "</body>", 1), mimetype="text/html")


@cheat_sheets_bp.post("/api/cheatsheets/posted")
def cheat_sheet_posted():
    """A section graphic was exported (user 2026-10-17: "Trying to promote these on twitter and the changes dont help
    for reconciling"): its rows and game lines are recorded as POSTED in `<sport>/<date>.posted.json`, re-derived from
    the sheet by card id (never the client), with the price and book the sheet showed. From then on every build keeps
    them, they lead their section, and the record grades them at that price."""
    body = request.get_json(silent=True) or {}
    sport, day, section = str(body.get("sport") or ""), str(body.get("date") or ""), str(body.get("section") or "")
    if not _SPORT.match(sport) or not _DAY.match(day) or not _SECTION.match(section) or section in _NOT_POSTED:
        return jsonify({"ok": False, "error": "bad request"}), 400
    doc = _read(sport, day)
    if doc is None:
        return jsonify({"ok": False, "error": "no sheet for that sport and day"}), 404
    wanted = {"rows": [str(x) for x in body.get("card_ids") or [] if _ROW_ID.match(str(x))][:60],
              "lines": [str(x) for x in body.get("line_ids") or [] if _ROW_ID.match(str(x))][:60],
              "sgps": [str(x) for x in body.get("sgp_ids") or [] if _SGP_ID.match(str(x))][:30]}
    post: dict[str, Any] = {"section": section, "game": str(body.get("game") or "") or None,
                            "posted_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                            "sheet_generated_at": doc.get("generated_at"), "rows": [], "lines": [], "sgps": []}
    tickets = {str(t.get("sgp_id")): t for t in cs.with_posted_sgps(doc.get("sgp") or [], doc.get("posted"))}
    for sid in dict.fromkeys(wanted["sgps"]):
        if sid in tickets:
            post["sgps"].append({"sgp_id": sid, "item": {k: v for k, v in tickets[sid].items() if k != "posted"}})
    for kind, field in (("rows", "rows"), ("lines", "game_lines")):
        by_id: dict[str, dict[str, Any]] = {}
        for item in doc.get(field) or []:
            by_id.setdefault(pc.card_id(sport, day, item), item)
        for cid in dict.fromkeys(wanted[kind]):
            item = by_id.get(cid)
            if item is None:
                continue
            check = item.get("check") or {}
            post[kind].append({"card_id": cid, "price": check.get("price"), "book": check.get("book"),
                               "item": {k: v for k, v in item.items() if k not in ("book_prices", "evidence_error")}})
    missing = sum(len(set(wanted[k])) - len(post[k]) for k in ("rows", "lines", "sgps"))
    if not post["rows"] and not post["lines"] and not post["sgps"]:
        return jsonify({"ok": False, "error": "none of those rows are on the sheet now -- reload and export again",
                        "missing": missing}), 404
    path = _sheet_dir() / sport / f"{day}{cs.POSTED_SUFFIX}"
    current = cs.load_posted(_sheet_dir(), sport, day) or {"sport": sport, "date": day, "posts": []}
    current["posts"] = list(current.get("posts") or []) + [post]
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(current, fh, ensure_ascii=False)
    os.replace(tmp, path)
    return jsonify({"ok": True, "rows": len(post["rows"]), "lines": len(post["lines"]), "sgps": len(post["sgps"]),
                    "missing": missing, "posted_at": post["posted_at"]}), 200


@cheat_sheets_bp.post("/api/cheatsheets/cards")
def cheat_sheet_card_logged():
    body = request.get_json(silent=True) or {}
    sport, day, card = str(body.get("sport") or ""), str(body.get("date") or ""), str(body.get("card_id") or "")
    row, game, reason = _card_row(sport, day, card)
    if row is None:
        return jsonify({"ok": False, "error": reason}), 404
    path = pc.ledger_path(_data_root())
    number = pc.card_number(pc.read_ledger(path), day, card)
    fields = _fields(row, game, sport=sport, day=day, number=number)
    record = pc.ledger_record(fields, row, sport=sport, generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                              source="exported")
    added = pc.append_ledger(path, [record])
    return jsonify({"ok": True, "card_id": card, "logged": bool(added), "number": number}), 200


_SITE_HEAD = """<link rel="icon" href="{{ url_for('static', filename='shared/favicon-32.png') }}" sizes="32x32" type="image/png">
<link rel="stylesheet" href="{{ url_for('static', filename='shared/standalone_shell.css') }}">"""
_SITE_HEADER = "{% include 'shared/_standalone_app_header.html' %}"

# The export toolbar for a pick graphic: outside the captured area, so the PNG is exactly the 1080 x 1350 card.
_CARD_TOOLBAR = r"""<div id="pc-toolbar" style="position:fixed;top:14px;right:14px;z-index:50;display:flex;gap:8px;font:700 15px Barlow,Arial,sans-serif">
  <button id="pc-dl" style="background:#8cff2e;color:#04110a;border:0;border-radius:8px;padding:10px 16px;font:inherit;cursor:pointer">Download PNG</button>
  <a href="__BACK__" style="background:#0a1520;color:#eef3f7;border:1px solid #1d3a55;border-radius:8px;padding:10px 16px;text-decoration:none">Back to the sheet</a>
  <span id="pc-msg" style="align-self:center;color:#9db0bf"></span>
</div>
<script src="https://cdn.jsdelivr.net/npm/html-to-image@1.11.11/dist/html-to-image.js"></script>
<script>
// Embed the latin font subsets ourselves: html-to-image cannot read the cross-origin Google Fonts sheet.
async function fontEmbedCSS() {
  var link = Array.prototype.find.call(document.querySelectorAll('link[rel="stylesheet"]'), function (l) { return l.href.indexOf("fonts.googleapis.com") >= 0; });
  if (!link) return "";
  var css = (await (await fetch(link.href)).text()).split("/* ").filter(function (b) { return b.indexOf("latin */") === 0; })
    .map(function (b) { return b.slice(8); }).join("\n");
  var urls = Array.from(new Set((css.match(/url\((https:[^)]+)\)/g) || []).map(function (x) { return x.slice(4, -1); })));
  for (var i = 0; i < urls.length; i++) {
    var blob = await (await fetch(urls[i])).blob();
    var data = await new Promise(function (r) { var fr = new FileReader(); fr.onload = function () { r(fr.result); }; fr.readAsDataURL(blob); });
    css = css.split(urls[i]).join(data);
  }
  return css;
}
document.getElementById("pc-dl").addEventListener("click", async function () {
  var msg = document.getElementById("pc-msg");
  msg.textContent = "Rendering...";
  try {
    if (document.fonts && document.fonts.ready) await document.fonts.ready;
    var url = await window.htmlToImage.toPng(document.body, {width: 1080, height: 1350, pixelRatio: 1, backgroundColor: "#04070c",
      fontEmbedCSS: await fontEmbedCSS(), filter: function (node) { return node.id !== "pc-toolbar"; }});
    var a = document.createElement("a"); a.href = url; a.download = "__FILE__"; document.body.appendChild(a); a.click(); a.remove();
    window.__lastCard = url;
    var r = await fetch("/api/cheatsheets/cards", {method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({sport: "__SPORT__", date: "__DAY__", card_id: "__CARD__"})});
    var j = await r.json();
    msg.textContent = j.logged ? "Saved, and added to the graded record." : "Saved (already on the graded record).";
  } catch (e) { msg.textContent = "Export failed: " + e.message; }
});
</script>
"""
