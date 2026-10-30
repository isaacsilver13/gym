# Direct Apple Health ingestion — 2026-10-28

Approved route: Apple Workout → Apple Health → Health Auto Export (iPhone) →
private Tailscale HTTPS receiver on this computer → Endurain → training hub.

1. Accept documented JSON version 2 running workouts with a dedicated bearer
   credential. Bound request size, batch size, numeric ranges and sample counts;
   never echo submitted health data or secrets in errors.
2. Preserve source UUID, recorded distance, timer versus elapsed time, heart-rate
   samples and optional GPS in FIT using Garmin's encoder. Never invent a route,
   distance samples, split times or pause locations. Ignore other sports so
   lifting stays in openGym.
3. Persist a private SQLite outbox before acknowledging uploads. Bind the outbox
   to the configured hub owner and Endurain account/server. Deduplicate UUIDs,
   flag changed re-exports for review, retry transient failures, persist accepted
   Endurain job IDs and poll to completion. No account credential on the phone.
4. Add owner-only import status in the hub and private pairing/config helpers.
   Keep credentials outside Git and request URLs. Run the worker with the hub;
   back up the outbox with its existing /data volume.
5. Verify unit/integration regressions plus actual local Endurain FIT ingestion,
   repeat uploads, restart recovery and private HTTPS rejection of unauthenticated
   requests. Have an independent second agent review changes, fix findings,
   apply source to the real gym repo without overwriting unrelated edits.
6. Enable only the workout receiver through Tailscale Serve, preserving existing
   Serve configuration. No Funnel, new cloud deployment or paid purchase.
   Phone-side app installation and Health access must be completed on the iPhone.

Sources: [HAE JSON](https://help.healthyapps.dev/en/health-auto-export/export-format/),
[workouts v2](https://help.healthyapps.dev/en/health-auto-export/export-format/workouts/),
[REST automation](https://help.healthyapps.dev/en/health-auto-export/automations/rest-api/),
[Garmin encoder](https://github.com/garmin/fit-python-sdk), pinned Endurain v0.20.2 source.

Limits: this version imports running only. Export corrections/deletions are
reviewed manually; changing ingestion routes requires duplicate reconciliation.
Background delivery depends on iOS and this computer staying awake/connected.
