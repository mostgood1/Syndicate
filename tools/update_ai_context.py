import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
CONTEXT_DIR = BASE_DIR / "docs" / "ai_context"

EXCLUDE = {"__pycache__", ".git", "node_modules", "docs", "tools"}

def get_files():
    files = []
    for root, dirs, filenames in os.walk(BASE_DIR):
        dirs[:] = [d for d in dirs if d not in EXCLUDE]

        for f in filenames:
            if f.endswith(".py"):
                path = Path(root) / f
                files.append(path.relative_to(BASE_DIR))
    return files


def classify_file(path):
    name = str(path).lower()

    if "sim" in name or "engine" in name:
        return "simulation"
    if "state" in name:
        return "state"
    if "eval" in name or "metric" in name:
        return "evaluation"
    if "run" in name or "controller" in name:
        return "execution"
    return "other"


def update_system_map(files):
    categories = {}

    for f in files:
        cat = classify_file(f)
        categories.setdefault(cat, []).append(str(f))

    lines = ["# System Map\n\n{"]
    for k, v in categories.items():
        lines.append(f'  "{k}": [')
        for file in v:
            lines.append(f'    "{file}",')
        lines.append("  ],")
    lines.append("}")

    (CONTEXT_DIR / "system_map.md").write_text("\n".join(lines))


def update_architecture(files):
    summary = f"""# Syndicate System Overview

## Overview
Auto-generated overview of project structure.

## File Count
Total Python files: {len(files)}

## Core Areas
"""

    counts = {}
    for f in files:
        cat = classify_file(f)
        counts[cat] = counts.get(cat, 0) + 1

    for k, v in counts.items():
        summary += f"- {k}: {v} files\n"

    summary += """
## Key Design Principles
- State-driven execution
- Avoid redundant computation
- Modular components
"""

    (CONTEXT_DIR / "architecture.md").write_text(summary)


def main():
    print("🔍 Scanning project...")

    files = get_files()

    print(f"✅ Found {len(files)} Python files:")
    for f in files[:10]:  # show first 10
        print(" -", f)

    print("\n🧠 Updating system_map.md...")
    update_system_map(files)

    print("🧠 Updating architecture.md...")
    update_architecture(files)

    print("\n✅ DONE — AI context updated.")
    print(f"📁 Output folder: {CONTEXT_DIR}")


if __name__ == "__main__":
    main()