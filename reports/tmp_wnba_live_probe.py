import sys, json, os
from pathlib import Path
from tempfile import TemporaryDirectory
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from syndicate.features.wnba.live_prop_audit import build_live_prop_audit_payload
from syndicate.features.wnba.live_game_accuracy import build_live_game_accuracy_payload
from syndicate.features.wnba.live_prop_accuracy import build_live_prop_accuracy_payload
with TemporaryDirectory() as d:
    p=Path(d)/'data'/'processed'; p.mkdir(parents=True, exist_ok=True)
    (p/'live_lens_projections_2026-05-18.jsonl').write_text(json.dumps({'market':'player_prop','game_id':'1234567890','player':'A\'ja Wilson','stat':'pts','proj':25.5,'line':24.5})+'\n', encoding='utf-8')
    (p/'live_lens_signals_2026-05-18.jsonl').write_text(json.dumps({'market':'player_prop','klass':'BET','game_id':'1234567890','player':'A\'ja Wilson','stat':'pts','side':'OVER','line':24.5})+'\n', encoding='utf-8')
    (p/'recon_props_2026-05-18.csv').write_text('game_id,player_name,pts,reb,ast\n1234567890,A\'ja Wilson,28,8,3\n', encoding='utf-8')
    (p/'recon_games_2026-05-18.csv').write_text('game_id,home_tri,away_tri,home_pts,visitor_pts,total_actual\n1234567890,LVA,SEA,95,88,183\n', encoding='utf-8')
    os.environ['SYNDICATE_WNBA_SOURCE_ROOT']=d
    a=build_live_prop_audit_payload('date=2026-05-18&include_rows=1')
    g=build_live_game_accuracy_payload('since=2026-05-18&until=2026-05-18&include_rows=1')
    pr=build_live_prop_accuracy_payload('since=2026-05-18&until=2026-05-18&include_rows=1')
    print('audit source', ((a or {}).get('meta') or {}).get('source'), 'n', ((a or {}).get('overall') or {}).get('n'))
    print('game source', ((g or {}).get('meta') or {}).get('source'), 'n_settled', (((g or {}).get('overall') or {}).get('ats') or {}).get('n_settled'))
    print('prop source', ((pr or {}).get('meta') or {}).get('source'), 'n_settled', (((pr or {}).get('overall') or {}).get('props') or {}).get('n_settled'))
