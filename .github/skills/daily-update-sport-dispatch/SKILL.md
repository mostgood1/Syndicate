---
name: daily-update-sport-dispatch
description: Use when manually triggering or troubleshooting Syndicate daily updates for a specific subset of sports, especially WNBA-only or other sport-filtered workflow_dispatch runs.
---

# Daily Update Sport Dispatch Skill

Use this skill when the user wants to run the daily update for one or more specific sports instead of the full in-season set.

## Objective
Keep the daily update workflow sport-selective, explicit, and debuggable.

## Core principles
- Use the workflow_dispatch `active_sports` input for sport-filtered manual runs.
- Prefer direct `scripts/daily_update.ps1` routing for sport-specific manual dispatches when wrapper layering causes argument binding problems.
- Build PowerShell arguments with ordered hashtable splatting so named parameters stay bound even when sports are filtered.
- Preserve the existing in-season wrapper for broader scheduled runs when no sport filter is provided.
- Validate the exact emitted command line before dispatching a new workflow run.

## Required analysis sequence
1. Identify the requested sport set and date.
2. Check whether the workflow already exposes a manual sport selector.
3. Confirm the dispatch path and wrapper choice for the requested sport set.
4. Build the run arguments as an ordered hashtable.
5. Validate the emitted command line locally.
6. Dispatch the workflow and monitor the resulting run for the daily pipeline step.
7. Watch for downstream artifact generation or publish-path failures.

## Expected outputs
- workflow_dispatch input mapping
- sport-filtered command-line shape
- wrapper routing decision
- validation probe for the emitted args
- follow-up checks for artifact generation or publish parity
