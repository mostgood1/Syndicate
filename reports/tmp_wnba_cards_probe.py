import sys
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from syndicate.features.wnba.cards import build_cards_page_context
with patch('syndicate.features.wnba.cards._games_from_artifacts', return_value=([], 'missing_cards.csv', 'missing_recommendations.json')):
    ctx = build_cards_page_context('1900-01-01')
print('date', ctx.get('date'))
print('games', len(ctx.get('games') or []))
print('scoreboard_items', len(ctx.get('scoreboard_items') or []))
print('using_sample_data', ctx.get('using_sample_data'))
print('source_title', ctx.get('source_title'))
print('empty_title', (ctx.get('empty_state') or {}).get('title'))
