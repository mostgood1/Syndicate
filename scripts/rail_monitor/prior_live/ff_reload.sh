#!/bin/bash
# Claimed web deploy (lane layer2-rail-monitor, preflight CLEAR 16:29:30Z): ff the fleet to EXACTLY 8455f25c0, then
# reload-web. Gate on "state": "done".
cd ~/Syndicate || exit 1
T=8455f25c01bd43d37ae3f9670af29f6eea54d8d7
echo "head_before $(git rev-parse --short HEAD)"
git merge-base --is-ancestor HEAD "$T" || { echo "NOT_ANCESTOR"; exit 2; }
echo "ff_at $(date -u +%Y-%m-%dT%H:%M:%SZ)"
git merge --ff-only "$T" || { echo "FF_FAILED"; exit 3; }
echo "head_after $(git rev-parse --short HEAD)"
echo "reload_at $(date -u +%Y-%m-%dT%H:%M:%SZ)"
~/.venvs/syndicate/bin/python scripts/local_production.py reload-web
echo "reload_rc=$? done_at $(date -u +%Y-%m-%dT%H:%M:%SZ)"
