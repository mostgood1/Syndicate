"""
Context: Syndicate Simulation System
See: docs/ai_context/architecture.md

Role:
- Flask entrypoint for running the Syndicate app.

Constraints:
- State-driven execution
- Avoid redundant computation
"""

from syndicate.app import app


if __name__ == "__main__":
    app.run(debug=True, use_reloader=False)