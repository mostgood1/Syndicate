from __future__ import annotations

import importlib.util
from pathlib import Path

script_path = Path(r"C:\Users\tempadmin\OneDrive\Coding\Syndicate\scripts\refresh_nba_oddsapi_props.py")
module_spec = importlib.util.spec_from_file_location("refresh_nba", script_path)
module = importlib.util.module_from_spec(module_spec)
assert module_spec.loader is not None
module_spec.loader.exec_module(module)

source_root = Path(r"C:\Users\tempadmin\OneDrive\Coding\Syndicate\vendor\nba_betting_repo")
log_file = source_root / "tmp_bootstrap_check.log"
result = module._ensure_source_game_inputs(
    source_root=source_root,
    package_name="nba_betting",
    date_str="2026-05-30",
    log_file=log_file,
    heartbeat_cb=None,
)
pred_path = source_root / "data" / "processed" / "predictions_2026-05-30.csv"
repo_pred_path = source_root / "predictions_2026-05-30.csv"
print(result)
print("processed_exists", pred_path.exists())
print("processed_rows", module._count_csv_rows_quick(pred_path))
print("repo_exists", repo_pred_path.exists())
