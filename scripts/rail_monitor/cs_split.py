"""Split cs_raw.json (cs_series.py output) into the two dashboard datasets.

  py -3 cs_split.py   -> cheat_sections.json (latest review's sections), cheat_history.json (one row per day x section)
"""
import json, os

HERE = os.path.dirname(os.path.abspath(__file__))
raw = json.load(open(os.path.join(HERE, "cs_raw.json"), encoding="utf-8"))
sections = raw.get("sections") or []
history = raw.get("history") or []
assert sections and history, "cs_raw.json is empty: rerun cs_series.py"
json.dump(sections, open(os.path.join(HERE, "cheat_sections.json"), "w", encoding="utf-8"), indent=0)
json.dump(history, open(os.path.join(HERE, "cheat_history.json"), "w", encoding="utf-8"), indent=0)
print("sections", len(sections), "day", sections[0].get("day"), "| history", len(history), "| review days", raw.get("review_days"), raw.get("first"), "..", raw.get("last"))
