# Intelligence Architecture

Preferred architecture:

request -> router -> pipeline -> intelligence.py -> evidence builder -> structured output -> formatter -> endpoint response

## Design rules
- Prefer wrapping and orchestrating intelligence.py over embedding additional logic directly inside it
- Keep analysis separate from formatting
- Endpoint responses should be derived from structured output objects
``