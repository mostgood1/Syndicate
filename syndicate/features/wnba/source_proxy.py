from __future__ import annotations

from functools import lru_cache
from pathlib import Path


def _vendored_web_asset(filename: str) -> Path:
    return Path(__file__).resolve().parents[2] / "static" / "wnba" / filename


def source_web_text(filename: str) -> str | None:
    path = _vendored_web_asset(filename)
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def rewrite_source_cards_script(content: str) -> str:
    rewritten = str(content)
    replacements = {
        '"/api/cards/sim-detail': '"/wnba/api/source/cards/sim-detail',
        "'/api/cards/sim-detail": "'/wnba/api/source/cards/sim-detail",
        '`/api/cards/sim-detail': '`/wnba/api/source/cards/sim-detail',
        '"/api/cards/props-strip': '"/wnba/api/source/cards/props-strip',
        "'/api/cards/props-strip": "'/wnba/api/source/cards/props-strip",
        '`/api/cards/props-strip': '`/wnba/api/source/cards/props-strip',
        '"/api/cards?': '"/wnba/api/source/cards?',
        "'/api/cards?": "'/wnba/api/source/cards?",
        '`/api/cards?': '`/wnba/api/source/cards?',
        '"/api/': '"/wnba/api/',
        "'/api/": "'/wnba/api/",
        '`/api/': '`/wnba/api/',
        '"/season/': '"/wnba/season/',
        "'/season/": "'/wnba/season/",
        '`/season/': '`/wnba/season/',
        '"/web/assets/logos-wnba/': '"/wnba/web/assets/logos-wnba/',
        "'/web/assets/logos-wnba/": "'/wnba/web/assets/logos-wnba/",
        '`/web/assets/logos-wnba/': '`/wnba/web/assets/logos-wnba/',
    }
    for old, new in replacements.items():
        rewritten = rewritten.replace(old, new)
    return rewritten


def rewrite_source_cards_styles(content: str) -> str:
    return str(content).replace("/web/assets/logos-wnba/", "/wnba/web/assets/logos-wnba/")


def rewrite_source_live_page_html(content: str) -> str:
    rewritten = str(content)
    replacements = {
        'href="/betting-card"': 'href="/wnba/cards"',
        "href='/betting-card'": "href='/wnba/cards'",
        'href="/accuracy-market"': 'href="/wnba/market-accuracy"',
        "href='/accuracy-market'": "href='/wnba/market-accuracy'",
        'href="/live-lens-accuracy"': 'href="/wnba/live-lens-accuracy"',
        "href='/live-lens-accuracy'": "href='/wnba/live-lens-accuracy'",
        'href="/live-game-lens-accuracy"': 'href="/wnba/live-game-lens-accuracy"',
        "href='/live-game-lens-accuracy'": "href='/wnba/live-game-lens-accuracy'",
        'href="/live-player-props-lens-accuracy"': 'href="/wnba/live-player-props-lens-accuracy"',
        "href='/live-player-props-lens-accuracy'": "href='/wnba/live-player-props-lens-accuracy'",
        'href="/live-player-props-audit"': 'href="/wnba/live-player-props-audit"',
        "href='/live-player-props-audit'": "href='/wnba/live-player-props-audit'",
        '"/api/': '"/wnba/api/',
        "'/api/": "'/wnba/api/",
        "`/api/": "`/wnba/api/",
        '"/accuracy-market': '"/wnba/market-accuracy',
        "'/accuracy-market": "'/wnba/market-accuracy",
        "`/accuracy-market": "`/wnba/market-accuracy",
        '"/live-lens-accuracy': '"/wnba/live-lens-accuracy',
        "'/live-lens-accuracy": "'/wnba/live-lens-accuracy",
        "`/live-lens-accuracy": "`/wnba/live-lens-accuracy",
        '"/live-game-lens-accuracy': '"/wnba/live-game-lens-accuracy',
        "'/live-game-lens-accuracy": "'/wnba/live-game-lens-accuracy",
        "`/live-game-lens-accuracy": "`/wnba/live-game-lens-accuracy",
        '"/live-player-props-lens-accuracy': '"/wnba/live-player-props-lens-accuracy',
        "'/live-player-props-lens-accuracy": "'/wnba/live-player-props-lens-accuracy",
        "`/live-player-props-lens-accuracy": "`/wnba/live-player-props-lens-accuracy",
        '"/live-player-props-audit': '"/wnba/live-player-props-audit',
        "'/live-player-props-audit": "'/wnba/live-player-props-audit",
        "`/live-player-props-audit": "`/wnba/live-player-props-audit",
    }
    for old, new in replacements.items():
        rewritten = rewritten.replace(old, new)
    return rewritten


@lru_cache(maxsize=8)
def build_source_cards_script() -> str | None:
    content = source_web_text("cards-parity.js")
    if content is None:
        return None
    return rewrite_source_cards_script(content)


@lru_cache(maxsize=8)
def build_source_cards_styles() -> str | None:
    content = source_web_text("cards-parity.css")
    if content is None:
        return None
    return rewrite_source_cards_styles(content)


@lru_cache(maxsize=8)
def build_source_base_styles() -> str | None:
    return source_web_text("styles.css")