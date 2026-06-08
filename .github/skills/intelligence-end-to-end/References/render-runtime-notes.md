# Render Runtime Notes

Render runs deployed application code from this repository's Flask application and deployment configuration.

Agent skills do not run at request time.
Skills are only development-time guidance for Copilot.

Therefore:
- all runtime behavior must be implemented in application code
- endpoint correctness must come from the Flask route / pipeline / models
- changing SKILL.md alone does not change runtime behavior