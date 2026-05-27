import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from syndicate.app import create_app
app=create_app(); c=app.test_client()
r=c.get('/api/home?date=2026-05-20'); p=r.get_json() or {}
html=p.get('html') or ''
print('status', r.status_code)
checks=['/mlb/cards?date=2026-05-20','/mlb/cards?date=','client=source&amp;embed=home-cards','/mlb/hr-targets?date=2026-05-20','/mlb/hr-targets?date=','/mlb/live-lens?date=2026-05-20','/mlb/live-lens?date=','data-home-preserve-key="home-cards"','href="/?date=2026-05-20"']
for chk in checks:
    print(chk, chk in html)
r2=c.get('/?date=2026-05-20'); b=r2.get_data(as_text=True)
print('home has /?date selected', 'href="/?date=2026-05-20"' in b)
print('home has Use Today href /', 'href="/">Use Today<' in b)
print('preserve key home-cards', 'data-home-preserve-key="home-cards"' in b)
