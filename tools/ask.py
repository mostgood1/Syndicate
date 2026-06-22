import os

BASE = "docs/ai_context"

def load(file):
    path = os.path.join(BASE, file)
    return open(path).read() if os.path.exists(path) else ""

def build_prompt(task):
    return f"""
SYSTEM CONTEXT:
{load("architecture.md")}

DECISIONS:
{load("decisions.md")}

TASK:
{task}
"""

if __name__ == "__main__":
    import sys
    query = " ".join(sys.argv[1:])
    prompt = build_prompt(query)
    print(prompt)