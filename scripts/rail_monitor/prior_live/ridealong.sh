#!/bin/bash
# Read-only: the fleet's head and what an ff to the after-midnight rail fix carries along.
cd ~/Syndicate || exit 1
echo "read_at $(date -u +%H:%M:%SZ)"
echo "fleet_head $(git rev-parse --short HEAD)"
git merge-base --is-ancestor HEAD 8455f25c0 && echo "ancestor_ok" || echo "NOT_ANCESTOR"
echo "--- commits fleet_head..8455f25c0 touching runtime code (not .syndicate/docs/reports/tests/scripts/rail_monitor)"
git log --format='%h %ad %s' --date=format:%m-%dT%H:%M HEAD..8455f25c0 -- . ':(exclude).syndicate' ':(exclude)docs' ':(exclude)reports' ':(exclude)tests' ':(exclude)scripts/rail_monitor' | cut -c1-230
echo "--- board_build_process.py diff head"
git diff HEAD 8455f25c0 -- pipeline/board_build_process.py | grep -E '^\+.*(environ|def |ENV|_enabled|default)' | head -30
