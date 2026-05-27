import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from syndicate.app import create_app
app = create_app()
client = app.test_client()
for path in [
    "/nhl/live-lens?date=2026-05-16",
    "/wnba/api/live-lens?date=2026-05-16",
    "/nba/api/season/2025/live-lens",
]:
    resp = client.get(path)
    print(path, resp.status_code, resp.headers.get("Location"))
    if "/api/" in path:
        payload = resp.get_json() or {}
        print("route_path", payload.get("route_path"))
        print("module_links_count", len(payload.get("module_links") or []))
        first = (payload.get("module_links") or [{}])[0]
        print("first_href", first.get("href"))
