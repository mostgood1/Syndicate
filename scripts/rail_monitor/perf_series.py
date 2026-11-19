"""Read-only: per-day, per-sport 28-day rolling results of the board (pooled), the shortlist-published
recommendations, and the portfolio's staked paper bets, from the fleet's daily model scorecards."""
import json, os, sys
R = os.path.expanduser('~/syndicate-prod/data/reports/model_scorecard')
rows = []
for f in sorted(os.listdir(R)):
    if not (f.startswith('model_scorecard_2026') and f.endswith('.json')):
        continue
    try:
        d = json.load(open(os.path.join(R, f)))
    except Exception:
        continue
    day = d.get('today_central') or f[16:24]
    opt = d.get('optimizer') or {}
    bs = opt.get('by_sport') or {}
    win = opt.get('window') or {}
    for sport, s in bs.items():
        for kind in ('pooled', 'recommended', 'staked'):
            b = s.get(kind) or {}
            if not b.get('bets'):
                continue
            rows.append({
                'day': day, 'sport': sport, 'set': {'pooled': 'Whole board', 'recommended': 'Published to the shortlist', 'staked': 'Staked by the portfolio (paper)'}[kind],
                'bets': b.get('bets'), 'roi_pct': round(100 * b['roi'], 2) if b.get('roi') is not None else None,
                'predicted_ev_pct': round(100 * b['predicted_ev'], 2) if b.get('predicted_ev') is not None else None,
                'market_ev_pct': round(100 * b['market_ev'], 2) if b.get('market_ev') is not None else None,
                'window_days': win.get('days'), 'games': s.get('games'),
            })
json.dump(rows, sys.stdout)
