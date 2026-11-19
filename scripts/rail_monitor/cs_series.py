"""Read-only: cheat sheet section records from the fleet's daily reviews (cheatsheets/reviews/<date>.json).
Writes JSON {sections: [...latest...], history: [...per review day...]} to stdout."""
import json, os, sys
R = os.path.expanduser('~/syndicate-prod/data/cheatsheets/reviews')
days = sorted(f[:-5] for f in os.listdir(R) if f.endswith('.json') and f[:4] == '2026')
hist = []
latest = None
for day in days:
    try:
        j = json.load(open(os.path.join(R, day + '.json')))
    except Exception:
        continue
    latest = (day, j)
    for key, t in (j.get('trends') or {}).items():
        s, w = t.get('season') or {}, t.get('last_7_days') or {}
        hist.append({'id': f'{day}|{key}', 'day': day, 'section_key': key, 'section': t.get('label') or key,
                     'scope': j.get('scope'), 'season_n': s.get('n'), 'season_roi_pct': s.get('roi_pct'),
                     'season_win_pct': s.get('win_pct'), 'last7_n': w.get('n'), 'last7_roi_pct': w.get('roi_pct')})
sections = []
if latest:
    day, j = latest
    ap = j.get('against_price') or {}
    for key, t in (j.get('trends') or {}).items():
        s, w = t.get('season') or {}, t.get('last_7_days') or {}
        ex = (ap.get(key) or {}).get('excess') or {}
        lf = (ap.get(key) or {}).get('lift') or {}
        sections.append({
            'id': key, 'day': day, 'section': t.get('label') or key,
            'season_record': f"{s.get('w', 0)}-{s.get('l', 0)}", 'season_n': s.get('n'), 'season_win_pct': s.get('win_pct'),
            'season_units': s.get('units'), 'season_roi_pct': s.get('roi_pct'), 'season_verdict': s.get('verdict'),
            'last7_record': f"{w.get('w', 0)}-{w.get('l', 0)}", 'last7_roi_pct': w.get('roi_pct'), 'last7_verdict': w.get('verdict'),
            'vs_fair_pts': ex.get('pts'), 'vs_fair_lo': (ex.get('ci') or [None, None])[0], 'vs_fair_hi': (ex.get('ci') or [None, None])[1],
            'vs_others_pts': lf.get('pts'), 'vs_others_lo': (lf.get('ci') or [None, None])[0], 'vs_others_hi': (lf.get('ci') or [None, None])[1],
        })
    sections.sort(key=lambda r: -(r['season_n'] or 0))
json.dump({'sections': sections, 'history': hist, 'review_days': len(days), 'first': days[0] if days else None,
           'last': days[-1] if days else None, 'scope': latest[1].get('scope') if latest else None}, sys.stdout)
