#!/bin/bash
# Read-only: is surface_consistency_check.py a fleet scheduled job; the refresh-worker parent's boot head.
cd ~/Syndicate || exit 1
echo "read_at $(date -u +%H:%M:%SZ)"
echo "scheduled_jobs naming surface_consistency: $(grep -c 'surface_consistency' scripts/local_production.py)"
echo "--- last PARENT_RECYCLE lines in refresh-worker.log"
nice -n 19 grep -E 'PARENT_RECYCLE' ~/syndicate-prod/logs/refresh-worker.log | tail -4 | cut -c1-260
