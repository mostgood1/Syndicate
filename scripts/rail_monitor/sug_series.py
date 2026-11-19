"""Read-only: the suggested-set grader's per-sport 28-day rows (reports/suggested_set/suggested_set_latest.json),
one row per day and sport (regular season preferred, else the phase with the most bets), in board_results' shape."""
import json, os, sys
j = json.load(open(os.path.expanduser('~/syndicate-prod/data/reports/suggested_set/suggested_set_latest.json')))
best = {}
for r in j['rows']:
    if r.get('scope') != 'sport' or r.get('window') != '28d':
        continue
    k = (r['day'], r.get('sport_key') or r.get('sport'))
    cur = best.get(k)
    rank = (r.get('season_phase') == 'regular', r.get('bets') or 0)
    if cur is None or rank > cur[0]:
        best[k] = (rank, r)
out = []
for (day, sk), (_, r) in sorted(best.items()):
    out.append({'day': day, 'sport': sk, 'set': 'Suggested by the board', 'bets': r.get('bets'), 'games': r.get('games'),
                'roi_pct': r.get('roi_pct'), 'predicted_ev_pct': r.get('predicted_ev_pct'), 'market_ev_pct': r.get('market_ev_pct'),
                'roi_ci95_lo_pct': r.get('roi_ci95_lo_pct'), 'roi_ci95_hi_pct': r.get('roi_ci95_hi_pct'), 'season_phase': r.get('season_phase')})
json.dump({'generated_at': j.get('generated_at'), 'rows': out}, sys.stdout)
