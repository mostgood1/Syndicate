"""Find the nightly close cron's stored prompt in this session's transcript and print the parts about owed readings."""
import json
import re

P = (r"C:\Users\tempadmin\.claude\projects\C--Users-tempadmin-Coding-Syndicate--claude-worktrees-brave-swanson-6e6c6a"
     r"\d58574cb-c55a-4f1f-aa9a-ab530a5f63e0.jsonl")
best = None
for line in open(P, encoding="utf-8"):
    if "RAIL MONITOR NIGHTLY CLOSE (lean" not in line or "close_prompt_check" in line or "Check whether the close" in line:
        continue
    try:
        rec = json.loads(line)
    except ValueError:
        continue
    if rec.get("type") != "user":
        continue
    msg = rec.get("message", {})
    content = msg.get("content")
    text = content if isinstance(content, str) else " ".join(
        c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text")
    if "RAIL MONITOR NIGHTLY CLOSE" in text:
        best = text
if not best:
    print("not found")
else:
    i = best.find("RAIL MONITOR NIGHTLY CLOSE")
    body = best[i:]
    print("prompt chars", len(body))
    for m in re.finditer(r"(?i)runbook|\bR-[A-Z]\b|owed reading|carry-over", body):
        print("...", body[max(0, m.start() - 160): m.start() + 220].replace("\n", " "))
