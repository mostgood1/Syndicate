from pathlib import Path

from syndicate.app import create_app

app = create_app()
client = app.test_client()
payload = client.post('/api/intelligence/query', json={'question':'What is Brandon Young strikeouts projection today?','date':'2026-06-05'}).get_json() or {}
response = payload.get('response') or {}
lines = [repr((response.get('parsed_request') or {}).get('requested_subjects'))]
for item in (response.get('recommendations') or [])[:3]:
    lines.append(repr({k: item.get(k) for k in ('name','projected','line','odds','subject_key','market')}))
Path('c:/Users/tempadmin/OneDrive/Coding/Syndicate/tmp_verify_brandon_out.txt').write_text('\n'.join(lines), encoding='utf-8')
