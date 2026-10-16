"""The SyndicateROI brand kit (user 2026-10-16): one JSON of constants that the play cards and the cheat-sheet page both
read -- "let the JSON enforce consistency". These tests are that enforcement: no colour of its own in either template,
the spec's section order on the card, and every renderer injecting the tokens."""
from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

import pytest

from syndicate.features.shared import brand_kit
from syndicate.features.shared import cheat_sheets as cs
from syndicate.features.shared import play_cards as pc

REPO = Path(__file__).resolve().parents[1]
CARD = REPO / "syndicate" / "templates" / "play_cards" / "card.html"
PAGE = REPO / "syndicate" / "templates" / "cheat_sheets.html"
# A colour literal: any hex, or an rgb()/rgba() that is not plain black or white (those are shade and highlight only).
LITERAL = re.compile(r"#[0-9a-fA-F]{6}\b|#[0-9a-fA-F]{3}\b|rgba?\((?!\s*0\s*,\s*0\s*,\s*0\s*[,)]|\s*255\s*,\s*255\s*,\s*255\s*[,)])[^)]*\)")


def _script(name):
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / f"{name}.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_the_brand_json_holds_the_spec():
    brand = brand_kit.load()
    assert brand["layout"] == ["header", "matchup", "banner", "hero", "bet", "dashboard", "analysis", "ticker", "footer"]
    c = brand["colors"]
    assert (c["green"], c["blue"], c["cyan"]) == ("#8CFF00", "#00AEEF", "#00E5FF")
    assert (c["bg0"], c["bg1"], c["bg2"]) == ("#050505", "#101010", "#151515")
    assert all(re.fullmatch(r"#[0-9A-F]{6}", v) for v in c.values())
    assert sum(brand["mix_pct"].values()) == 100 and brand["handle"] == "@SyndicateROI"
    assert brand["tagline"] == ["Data driven", "Discipline", "Long-term edge"]
    tokens = brand_kit.css_tokens()
    assert "--green: #8CFF00;" in tokens and "--chrome-hi: #FFFFFF;" in tokens and '--display: "Saira Condensed"' in tokens


@pytest.mark.parametrize("path", [CARD, PAGE], ids=["card", "page"])
def test_no_template_hard_codes_a_colour(path):
    # Every colour comes from the JSON (a token or a color-mix of one); a literal would drift from the brand silently.
    text = path.read_text(encoding="utf-8")
    assert LITERAL.findall(text) == []


def _fields(**extra):
    row = {"player": "Tory Horton", "event_id": "e1", "market": "Receiving Yards", "line": 3.5, "side": "under",
           "books_quoting": 3, "suggested": True, "fair_method": "consensus_no_vig", "team": "SEA", "team_name": "Seattle Seahawks",
           "pos": "WR", "headshot_url": "data:image/webp;base64,HEAD", "form_labels": ["vs LAC", "@WAS", "@WAS", "vs HOU", "@JAX"],
           "check": {"verdict": "value", "ev_market": 4.1, "price": 105, "book": "betmgm", "p_market": 0.51, "p_model": None,
                     "form10": {"games": 5, "hits": 2, "values": [6, 48, 48, 0, 0]}, "reasons": []}}
    row.update(extra)
    game = {"matchup": "Seattle Seahawks @ Denver Broncos", "commence_time": "2026-10-16T00:15:00Z"}
    return pc.card_fields(row, sport="nfl", date="2026-10-15", number=2, game=game)


def test_the_card_renders_the_spec_order_and_the_brand_copy():
    html = pc.render_card(_fields(), "data:,")
    body = html.split("</style>", 1)[1]
    order = ['class="top"', 'class="matchup', 'class="banner"', 'class="bet"', 'class="dash', 'class="analysis"',
             'class="ticker"', 'class="tagline"']
    at = [body.index(marker) for marker in order]
    assert at == sorted(at)                                                   # never rearranged
    assert "--green: #8CFF00;" in html and "$" not in html.replace("$$", "")  # tokens injected, nothing unfilled
    assert ">Why we like it<" in body and ">Case against<" in body and "@SyndicateROI" in body and "Long-term edge" in body
    ticker = body[body.index('class="ticker"'):body.index('class="tagline"')]
    assert "FREE PLAY" in ticker and "#" not in ticker and "TORY HORTON UNDER 3.5 RECEIVING YARDS" in ticker.upper() and "(+105)" in ticker
    assert 'class="head" src="data:image/webp;base64,HEAD"' in body           # the athlete is the hero


def test_the_case_against_is_three_to_four_and_the_reasons_at_most_six():
    f = _fields()
    assert 3 <= len(f["risk"]) <= 4 and len(f["why"]) <= 6
    # form is context (already in the price, measured), never a solid tick; one that argues against the side is a risk
    assert all(tone in ("for", "ctx") for tone in f["why_tones"]) and f["why_tones"][0] == "for"
    form = [(tone, t) for tone, t in zip(f["why_tones"], f["why"]) if t.startswith("Last 5:")] + \
        [("against", r) for r in f["risk"] if r.startswith("Last 5:")]
    assert len(form) == 1 and form[0][0] in ("ctx", "against") and "under 3.5 in 2 of 5" in form[0][1]
    assert any("One big play is enough to beat an under" in r for r in f["risk"])
    rendered = pc.render_card(f, "data:,")
    assert rendered.count('<li class="for">') + rendered.count('<li class="ctx">') == len(f["why"])


def test_market_risks_know_their_bet():
    assert pc.market_risks({"kind": "game", "market": "spreads", "side": "home", "line": -15, "price": "+110"})[0].startswith("Big favourite")
    assert pc.market_risks({"kind": "game", "market": "h2h", "price": "+205"})[0].startswith("An underdog loses more often")
    assert pc.market_risks({"kind": "game", "market": "totals", "side": "under", "price": "-110"})[0].startswith("One late score")
    assert pc.market_risks({"kind": "prop", "side": "over", "price": "-114"})[-1].startswith("Lines move")


def test_hero_url_takes_the_largest_free_cutout():
    mlb = "https://img.mlbstatic.com/mlb-photos/image/upload/w_360,q_auto:best/v1/people/691406/headshot/67/current"
    assert brand_kit.hero_url("mlb", mlb).endswith("/v1/people/691406/headshot/silo/current") and "w_1000" in brand_kit.hero_url("mlb", mlb)
    nba = "https://cdn.nba.com/headshots/nba/latest/1040x760/203999.png"
    assert brand_kit.hero_url("nba", nba) == nba and brand_kit.hero_url("nfl", None) is None
    assert brand_kit.hero_url("nfl", "/cheatsheets/img/abc.webp") is None           # only a remote source is upgraded


def _sheet():
    def r(player, market, team="Texas State Bobcats", face=True, **kw):
        return {"player": player, "market": market, "team": team, "team_name": team, "line": 1.5, "side": "over",
                "headshot_url": f"https://a.espncdn.com/{player}.png" if face else None, "books_quoting": 1,
                "check": {"verdict": "neutral", "ev_market": 0.0}, **kw}
    rows = [r("QB One", "Passing Yards"), r("QB One", "Rush Yards"), r("QB One", "Passing TDs"),
            r("WR Two", "Receptions"), r("WR Two", "Receiving Yards"), r("No Face", "A", face=False), r("No Face", "B", face=False),
            r("No Face", "C", face=False), r("No Face", "D", face=False),
            r("Rival QB", "Passing Yards", team="Colorado State Rams"),
            r("Value Guy", "Receptions", check={"verdict": "value", "ev_market": 3.0}, books_quoting=5)]
    picks = [{"pick_id": "l2_1", "kind": "game", "market": "spreads", "side": "home", "home_team": "Texas State Bobcats",
              "away_team": "Colorado State Rams"},
             {"pick_id": "l2_2", "kind": "game", "market": "totals", "side": "over", "home_team": "Texas State Bobcats",
              "away_team": "Colorado State Rams"},
             {"pick_id": "l2_3", "kind": "prop", "headshot_url": "https://a.espncdn.com/prop.png"}]
    return {"sport": "nfl", "date": "2026-10-15", "rows": rows, "picks": picks}


def test_the_team_star_fronts_a_side_and_both_stars_front_a_total():
    # Spec: "SPREADS / TOTALS: use team athlete hero image". The star is the player the books list the most markets on.
    sheet = _sheet()
    assert brand_kit.team_star(sheet["rows"], "Texas State Bobcats")["player"] == "QB One"        # 3 markets, with a face
    assert brand_kit.team_star(sheet["rows"], "Nobody") is None
    named = pc.attach_heroes(sheet)
    side, total, prop = sheet["picks"]
    assert side["hero_url"] == "https://a.espncdn.com/QB One.png" and side["hero_name"] == "QB One"
    assert total["hero_home_url"].endswith("QB One.png") and total["hero_away_url"].endswith("Rival QB.png")
    assert prop["hero_url"] == "https://a.espncdn.com/prop.png"
    heroes = [r["player"] for r in sheet["rows"] if r.get("hero_url")]
    assert heroes == ["Value Guy"] and named == 5        # only a row a card can be made of fetches a hero


def test_a_total_card_shows_both_teams_equally():
    f = {"kind": "game", "market": "totals", "hero_away": "data:a", "hero_home": "data:h", "away_logo": "data:al",
         "home_logo": "data:hl", "sport": "NCAAF", "player": "x"}
    st = pc.stage(f)
    assert st["stage_class"] == "duo" and 'class="head away"' in st["hero"] and 'class="head home"' in st["hero"] and ">VS<" in st["hero"]
    assert pc.stage(dict(f, hero_home=None))["hero"].count("crest-duo") == 2        # one face missing: both crests instead
    assert pc.stage({"kind": "prop", "hero": "data:x", "sport": "MLB"})["stage_class"] == "tight"   # square cutouts


def test_team_colour_reads_the_branding_snapshot(tmp_path, monkeypatch):
    from syndicate.features.shared import team_logos

    csv = tmp_path / "nfl_team_branding.csv"
    csv.write_text("team_id,abbreviation,location,display_name,primary_color,secondary_color,logo_url,source_snapshot_date\n"
                   "26,SEA,Seattle,Seattle Seahawks,002a5c,69be28,https://x/sea.png,2026-07-20\n", encoding="utf-8")
    monkeypatch.setattr(team_logos, "_branding_files", lambda sport: [csv])
    brand_kit._colors.cache_clear()
    try:
        assert brand_kit.team_color("nfl", "Seattle Seahawks") == "#002A5C" == brand_kit.team_color("nfl", "SEA")
        assert brand_kit.team_color("nfl", "Nowhere") is None
    finally:
        brand_kit._colors.cache_clear()


def test_every_page_renderer_injects_the_brand_tokens(tmp_path):
    # Reachability: the static renderer once did its own substitutions and shipped the page with no colours at all.
    template = PAGE.read_text(encoding="utf-8")
    for html in (cs.render_page(template, [], logo_src="x.webp"),
                 cs.render_record_page(template, None, logo_src="x.webp", meta={"page": "record"})):
        assert "__BRAND_TOKENS__" not in html and "--green: #8CFF00;" in html
    sheet_dir = tmp_path / "cheatsheets" / "nfl"
    sheet_dir.mkdir(parents=True)
    (sheet_dir / "2026-10-15.json").write_text(json.dumps({"sport": "nfl", "date": "2026-10-15", "rows": [], "games": [],
                                                           "sections": {}, "picks": []}), encoding="utf-8")
    out = tmp_path / "page.html"
    _script("render_cheat_sheets").main(["--data-root", str(tmp_path), "--date", "2026-10-15", "--sports", "nfl", "--out", str(out)])
    page = out.read_text(encoding="utf-8")
    assert "__BRAND_TOKENS__" not in page and "--green: #8CFF00;" in page


@pytest.mark.parametrize("path", [CARD, PAGE], ids=["card", "page"])
def test_nothing_a_viewer_reads_names_the_internal_board(path):
    # User 2026-10-16: "the public doesnt know what the layer 2 board is - so we shouldnt reference it". Code comments
    # may name it; no string the page or the card shows may.
    shown = [ln for ln in path.read_text(encoding="utf-8").split("\n") if not ln.lstrip().startswith(("//", "/*", "*"))]
    assert [ln.strip()[:100] for ln in shown if re.search(r"(?i)layer ?2|the board|on board|board's", ln)] == []


def test_the_png_builder_inlines_a_cached_hero(tmp_path):
    from syndicate.features.shared import cheat_sheet_images as img

    key = "a" * 40
    (tmp_path / f"{key}.bin").write_bytes(b"RIFF....WEBPVP8 ")
    out = _script("build_play_cards").embed_card_images({"hero": f"/cheatsheets/img/{key}.webp", "headshot": None}, tmp_path)
    assert out["hero"].startswith("data:image/webp;base64,") and img.HERO_SIZE == brand_kit.load()["hero_image_px"]


def test_college_athletes_are_shown_by_their_team_logo(monkeypatch):
    # User 2026-10-16: "use team logos for college athletes". No college player's face on a card, on the sheet page, or
    # fetched by the generator; the team's logo is the hero. Pro sports keep their faces (the control).
    assert brand_kit.faces_allowed("NCAAF") is False and brand_kit.faces_allowed("ncaab") is False
    assert brand_kit.faces_allowed("nfl") is True
    row = {"player": "Destyn Hill", "event_id": "e9", "market": "Receptions", "line": 4.5, "side": "over", "books_quoting": 5,
           "suggested": True, "fair_method": "consensus_no_vig", "team": "Tulane", "team_name": "Tulane Green Wave",
           "headshot_url": "https://a.espncdn.com/college.png", "hero_url": "https://a.espncdn.com/college.png",
           "team_logo": "data:image/webp;base64,TULANE",
           "check": {"verdict": "value", "ev_market": 3.0, "price": 110, "book": "fanduel", "p_market": 0.5, "reasons": []}}
    college = pc.card_fields(row, sport="ncaaf", date="2026-10-17", number=1, game=None)
    pro = pc.card_fields(row, sport="nfl", date="2026-10-17", number=1, game=None)
    assert college["headshot"] is None and college["hero"] is None and pro["hero"] == "https://a.espncdn.com/college.png"
    shown = pc.render_card(college, "data:,").split("</style>", 1)[1]
    assert 'class="head"' not in shown and 'class="crest-big" src="data:image/webp;base64,TULANE"' in shown
    pick = dict(row, pick_id="l2_9", kind="prop", display_name="Destyn Hill", bet="Over 4.5 Receptions", price=110,
                fair_price=100, p_market=0.5, ev_pct=3.0, books=5, points=[])
    assert pc.pick_card_fields(pick, sport="ncaab", date="2026-10-17", number=1)["headshot"] is None
    bare = {k: v for k, v in row.items() if k != "hero_url"}
    sheet = {"sport": "ncaaf", "date": "2026-10-17", "rows": [dict(bare)], "picks": [dict(pick, hero_url=None)], "games": []}
    assert pc.attach_heroes(sheet) == 0 and "hero_url" not in sheet["rows"][0] and sheet["picks"][0]["hero_url"] is None
    assert pc.attach_heroes(dict(sheet, sport="nfl", rows=[dict(bare)], picks=[dict(pick, hero_url=None)])) == 2   # control
    page = cs.page_payload([sheet, dict(sheet, sport="nfl")])
    assert not set(brand_kit.FACE_FIELDS) & set(page["ncaaf"]["rows"][0]) and not set(brand_kit.FACE_FIELDS) & set(page["ncaaf"]["picks"][0])
    assert page["ncaaf"]["rows"][0]["team_logo"] == "data:image/webp;base64,TULANE"
    assert page["nfl"]["rows"][0]["headshot_url"] == "https://a.espncdn.com/college.png"          # control
    from syndicate.features.shared import cheat_sheet_images as img

    fetched = []
    monkeypatch.setattr(img, "cache_image", lambda url, cache, size=96, **kw: fetched.append((url, size)) or None)
    _script("build_cheat_sheets").attach_images({"sport": "ncaaf", "rows": [dict(row)], "picks": [], "games": []}, Path("."))
    assert sorted(fetched) == [("data:image/webp;base64,TULANE", 96), ("data:image/webp;base64,TULANE", 500)]  # logo only, never the face
