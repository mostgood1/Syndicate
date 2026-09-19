"""NHL cards date lookahead: only an EMPTY requested slate may jump ahead.

2026-09-19: web's disk held predictions for 09-19 (7 games) AND 09-20, and
`/nhl/api/cards?date=2026-09-19` served 09-20's slate (`lookahead_applied=true`)
because the lookahead never checked the requested date's own rows.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from syndicate.features.nhl import cards

_HEADER = "home,away,date,p_home_ml,p_away_ml,model_total\n"


def _write_predictions(root: Path, date_str: str, rows: list[tuple[str, str]]) -> None:
    body = _HEADER + "".join(f"{home},{away},{date_str},0.55,0.45,6.1\n" for home, away in rows)
    (root / f"predictions_{date_str}.csv").write_text(body, encoding="utf-8")


def _patched(root: Path, dates: list[str]):
    return (
        patch.object(cards, "processed_path", side_effect=lambda *parts: root.joinpath(*parts)),
        patch.object(cards, "scoreboard_snapshot_path", side_effect=lambda d: root / "scoreboard" / f"{d}.csv"),
        patch.object(cards, "source_available_dates", return_value=list(dates)),
    )


def _resolve(root: Path, dates: list[str], requested: str):
    p1, p2, p3 = _patched(root, dates)
    with p1, p2, p3:
        return cards._resolve_cards_date(requested)


def test_requested_date_with_rows_is_served_even_when_a_later_date_exists(tmp_path: Path) -> None:
    _write_predictions(tmp_path, "2026-09-19", [("St. Louis Blues", "Dallas Stars")])
    _write_predictions(tmp_path, "2026-09-20", [("New Jersey Devils", "New York Islanders")])

    assert _resolve(tmp_path, ["2026-09-19", "2026-09-20"], "2026-09-19") == ("2026-09-19", "2026-09-19", False)


def test_empty_requested_date_still_looks_ahead_to_next_date_with_rows(tmp_path: Path) -> None:
    _write_predictions(tmp_path, "2026-09-20", [("New Jersey Devils", "New York Islanders")])

    assert _resolve(tmp_path, ["2026-09-20"], "2026-09-19") == ("2026-09-19", "2026-09-20", True)


def test_no_later_date_means_no_lookahead(tmp_path: Path) -> None:
    _write_predictions(tmp_path, "2026-09-18", [("Boston Bruins", "Washington Capitals")])

    assert _resolve(tmp_path, ["2026-09-18"], "2026-09-19") == ("2026-09-19", "2026-09-19", False)


def test_payload_serves_requested_slate_games(tmp_path: Path) -> None:
    _write_predictions(tmp_path, "2026-09-19", [("St. Louis Blues", "Dallas Stars"), ("Seattle Kraken", "Vancouver Canucks")])
    _write_predictions(tmp_path, "2026-09-20", [("New Jersey Devils", "New York Islanders")])

    p1, p2, p3 = _patched(tmp_path, ["2026-09-19", "2026-09-20"])
    with p1, p2, p3:
        payload = cards.build_source_bundle_payload("2026-09-19")

    assert payload["date"] == "2026-09-19"
    assert payload["lookahead_applied"] is False
    assert payload["empty_state"] is None
