import json, re

rows = [json.loads(l) for l in open(r"C:\tmp\railmon\dash\rows.jsonl", encoding="utf-8")]
rows.sort(key=lambda r: r["n"])
data = []
for r in rows:
    t = re.sub(r"^R\d+\s*\S?\s*", "", r["label"]).strip()
    data.append({"t": t, "flags": r.get("flags_shown") or 0, "dark": r.get("dark_rows") or 0,
                 "rows": r.get("live_rows") or 0, "le": r.get("priced_le_120") or 0})

src = open(r"C:\tmp\railmon\rail_watch_1117.html", encoding="utf-8").read()
style = src[src.index("<style>"):src.index("</style>") + 8].replace(
    "Same system as the 11-15 and 11-16 pages.", "Same system as the 11-15 to 11-17 pages.")
script = src[src.index("<script>"):]
script = re.sub(r"var data = \[.*?\];", lambda m: "var data = " + json.dumps(data) + ";", script, flags=re.S)
script = script.replace("var maxF = 80", "var maxF = 120").replace("[0, 20, 40, 60, 80]", "[0, 30, 60, 90, 120]")

head = """<title>Rail Watch, Wed Nov 18</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Archivo:wght@500;700;800&family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@400;600&display=swap">
"""
body = open(r"C:\tmp\railmon\page_1118_body.html", encoding="utf-8").read()
html = head + style + body + script
open(r"C:\tmp\railmon\rail_watch_1118.html", "w", encoding="utf-8").write(html)
print(len(html), len(data))
