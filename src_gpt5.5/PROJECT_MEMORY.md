# Project Memory

This file records long-lived maintenance rules for the Truth Social post analysis system.

## Maintenance Rules

- If a change touches deployment, startup/shutdown scripts, runtime operations, configuration, scheduled tasks, logs, database paths, or user-facing operational behavior, update `README.md` in the same change set.
- Keep Windows and Linux launch/stop/status scripts aligned with the current recommended entry points.
- If a config option changes meaning or defaults, document it in `README.md`.
- If a change affects how to operate the service day to day, document the new behavior in `README.md`.

## Current Script Entry Points

- Windows:
  - `start.ps1`
  - `stop.ps1`
  - `status.ps1`
- Linux:
  - `start.sh`
  - `stop.sh`
  - `status.sh`

## Notes

- Treat this file as the long-term maintenance contract for the project.
- Prefer updating this file alongside any future operational convention changes.
