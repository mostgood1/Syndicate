"""The cheat sheets' daily review (user 2026-10-15: "monitoring/optimizations ... via a daily skill run based on
section trends"): pipeline health first, then section trends -- flagged only beyond noise, as proposals."""
from __future__ import annotations

import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path

from syndicate.features.shared import cheat_sheets as cs

DAY = "2026-10-15"


def _script():
    spec = importlib.util.spec_from_file_location(
        "review_cheat_sheets", Path(__file__).resolve().parents[1] / "scripts" / "review_cheat_sheets.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_a_trend_is_flagged_only_beyond_noise():
    m = _script()
    assert m.verdict({"w": 2, "l": 8, "n": 10, "units": -6.2}).startswith("reading only")      # 10 bets: never a flag
    assert m.verdict({"w": 10, "l": 30, "n": 40, "units": -21.0}).startswith("FLAG: losing")   # 40 bets, -52% ROI
    assert m.verdict({"w": 21, "l": 19, "n": 40, "units": 0.1}).startswith("within noise")
    assert "do not size up" in m.verdict({"w": 32, "l": 8, "n": 40, "units": 21.0})
    assert m.price_band(-250) == "big favourite (-200 or shorter)" and m.price_band(150) == "dog (+101..+199)"
    assert m.ev_band(3.1) == "EV 2-5%" and m.ev_band(None) == "no fair line"


def _write(root: Path, sport: str, day: str, rows, results, *, counts=None, void=None):
    folder = root / "cheatsheets" / sport
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{day}.json").write_text(json.dumps({"sport": sport, "date": day, "rows": rows}), encoding="utf-8")
    rec = {"sport": sport, "date": day, "props": {cs.prop_result_key(r): {"y": y} for r, y in zip(rows, results) if y is not None},
           "lines": {}, "void": void or {}, "counts": counts or {"props": len(rows), "props_graded": len(rows), "props_valued": len(rows)}}
    (folder / f"{day}.reconciled.json").write_text(json.dumps(rec), encoding="utf-8")


def _value_row(player, price=-110, ev=3.0):
    return {"event_id": "e1", "player": player, "market": "Receptions", "line": 2.5, "side": "over", "books_quoting": 4,
            "headshot_url": "x", "check": {"verdict": "value", "ev_market": ev, "price": price, "p_market": 0.55}}


def test_the_review_reports_health_and_trends_and_writes_its_mirror(tmp_path, monkeypatch):
    m = _script()
    monkeypatch.setattr(m, "central_today", lambda: DAY)
    rows = [_value_row(f"P{i}") for i in range(4)]
    _write(tmp_path, "nfl", "2026-10-14", rows, [1.0, 0.0, 0.0, None],
           counts={"props": 4, "props_graded": 3, "props_valued": 1},
           void={cs.prop_result_key(rows[3]): "player_not_in_box"})
    (tmp_path / "cheatsheets" / "nhl").mkdir()
    (tmp_path / "cheatsheets" / "nhl" / "2026-10-14.json").write_text(json.dumps({"sport": "nhl", "date": "2026-10-14", "rows": [{"player": "x"}]}), encoding="utf-8")
    log = tmp_path / "reconcile.log"
    log.write_text("RECONCILE_RUN start old\nvalue hooks MISSING ['x']\nRECONCILE_RUN start new\nRECONCILE ok\n", encoding="utf-8")
    mirror = tmp_path / "mirror"
    assert m.main(["--data-root", str(tmp_path), "--log", str(log), "--mirror", str(mirror)]) == 0
    review = json.loads((mirror / "latest.json").read_text(encoding="utf-8"))
    checks = {c["check"]: c for c in review["health"]}
    assert checks["season record"]["level"] == "fail"                                   # no record.json yet
    assert checks["nhl 2026-10-14 reconcile"]["level"] == "fail"                        # published, never reconciled
    assert checks["nfl 2026-10-14 graded"]["level"] == "warn"                           # 3 of 4 = 75%
    assert checks["nfl 2026-10-14 actual stats"]["level"] == "warn"                     # values on 1 of 3
    assert "actual-stat tap" not in checks                                              # the OLD run's MISSING is not read
    value = review["trends"]["value"]
    assert review["scope"] == "beta" and value["season"]["n"] == 3 and value["season"]["verdict"].startswith("reading only")
    assert set(value["slices"]) == {"price", "ev", "sport"} and review["flags"] == []
    assert (tmp_path / "cheatsheets" / "reviews" / f"{DAY}.md").read_text(encoding="utf-8").startswith("# Cheat-sheet review 2026-10-15")
    assert (mirror / "latest.md").read_text(encoding="utf-8") == (tmp_path / "cheatsheets" / "reviews" / "latest.md").read_text(encoding="utf-8")


def test_a_large_losing_slice_is_flagged_as_a_proposal(tmp_path, monkeypatch):
    m = _script()
    monkeypatch.setattr(m, "central_today", lambda: DAY)
    rows = [_value_row(f"P{i}", price=-110) for i in range(20)]           # a section shows 25 a sheet: two days of 20
    _write(tmp_path, "nfl", DAY, rows, [1.0] * 4 + [0.0] * 16)
    _write(tmp_path, "nfl", "2026-10-16", rows, [1.0] * 4 + [0.0] * 16)
    (tmp_path / "cheatsheets" / "record.json").write_text(json.dumps({"generated_at": datetime.now(timezone.utc).isoformat()}), encoding="utf-8")
    m.main(["--data-root", str(tmp_path), "--log", str(tmp_path / "none.log")])
    review = json.loads((tmp_path / "cheatsheets" / "reviews" / "latest.json").read_text(encoding="utf-8"))
    assert review["scope"] == "official" and review["trends"]["value"]["season"]["verdict"].startswith("FLAG: losing")
    assert any(f.startswith("Value at the best price: season FLAG") for f in review["flags"])
    assert "Never remove a sport, a market or a market family" in (tmp_path / "cheatsheets" / "reviews" / "latest.md").read_text(encoding="utf-8")
