# openGym + Endurain training hub

The existing app now provides an authenticated weekly overview across two independent services. openGym owns lifting routines and completed sets. Endurain owns imported running activities. Apple Workout remains the run recorder. The old tracker and its assistant summary remain available during migration.

## Start local staging

From this repository:

```powershell
python scripts/init_training.py
docker compose --env-file deployment/.env -f deployment/compose.training.yaml up -d --build
```

The initializer refuses to overwrite existing configuration. Three loopback-only entry points are available:

| App | URL |
|---|---|
| Training hub | http://localhost:18080 |
| openGym | http://localhost:18081 |
| Endurain | http://localhost:18082 |

This development stack is for the local computer. Phone pairing needs stable HTTPS hosting; localhost on a phone refers to the phone. Do not expose this development configuration to the internet. It uses development cookies, open initial signup, and a first-user openGym administrator. Create your own profiles before sharing an address. Endurain initially provisions its upstream admin account; change its default password during setup.

Create a hub account, an openGym profile, and an Endurain account. Profiles remain separate. Set `TRAINING_USERNAME` in the ignored `deployment/.env` to the exact hub username authorized to view the linked data. Other hub users cannot view that integration.

Images are pinned by digest and tracked in `deployment/upstream-lock.json`. The upstream code is kept separate; this repository integrates through HTTP and exports plan files rather than copying upstream training logic or exercise media.

## Connect lifting

In openGym, record your Account ID as `OPENGYM_UID`. Use Settings → Account → Pair the mobile app and the upstream [pairing script](https://github.com/DuarteSantos8/openGym/blob/v1.4.3/mcp/scripts/pair.mjs) to obtain a paired token; store it as `OPENGYM_TOKEN` in the ignored deployment environment file. A paired token is a full sign-in credential. The hub uses it only for `/api/me` and `/api/data` and verifies the returned profile ID before reading workout state. It is never returned to the browser or dashboard.

Recreate the hub after configuration changes:

```powershell
docker compose --env-file deployment/.env -f deployment/compose.training.yaml up -d --no-deps hub
```

The optional AI coach is disabled in this staging stack. Its activation and provider setup are separate later steps.

## Connect running

Endurain v0.20.2 API keys authorize uploads, not activity reads. The summary adapter uses its supported mobile JWT session with `X-Client-Type: mobile`, refreshes once on a 401, and atomically saves the rotated token pair. A revoked session remains unavailable until reconnected. Run one hub process with the credential-file implementation.

For a local-password account, run this interactive command inside the hub container. It supports MFA and never prints passwords or tokens:

```powershell
docker compose --env-file deployment/.env -f deployment/compose.training.yaml exec hub python -m app.training_tokens --url http://endurain:8080 --out /connections/endurain.json
```

Set `ENDURAIN_USER_ID` in `deployment/.env` to your Endurain account ID and recreate the hub. The adapter verifies ownership of every returned activity. Protect `runtime/connections` as full account access; restrict its host permissions. Connection files are separate from portable workout exports and are not included in the data backup; reconnect sessions after disaster recovery. SSO-only account connection is not implemented by this password-login helper.

Keep recording runs with Apple Workout. The selected ongoing route is Apple Health → Health Auto Export on iPhone → private Tailscale HTTPS receiver on this computer → Endurain. See [phone setup, server enrollment, fidelity and recovery](apple-health-setup.md). The phone-side automation is a paid app feature and has not been purchased or enabled by this implementation. First export representative runs and compare their recorded fields with Apple Fitness. Manual FIT/GPX/TCX uploads remain available for historical files; reconcile duplicates before using multiple ingestion routes.

For explicit resumable uploads, create an upload-only Endurain API key and set it securely as `ENDURAIN_UPLOAD_KEY` in the process environment. With the package installed or `PYTHONPATH=backend`:

```powershell
python -m app.run_import --url http://localhost:18082 --manifest runtime/run-import.json runtime/run-1.fit runtime/run-2.fit runtime/run-3.fit
# Review the dry run, then repeat with --apply.
```

The uploader uses content-derived idempotency keys, persists accepted job IDs before polling, and reports pending/failed jobs instead of treating HTTP 202 as a completed import. Each manifest is bound to its server and upload-credential fingerprint; use a new manifest when changing accounts or keys. Reuse the same manifest when resuming. Retain original files. Switching ingestion routes needs duplicate reconciliation; no schedule or provider connection is activated automatically.

## Migrate the old tracker

The Training overview includes **Export legacy history**, backed by authenticated `GET /api/v1/training/legacy-export`. It includes only the signed-in user's routine definitions and session summaries; password hashes and other users' records are excluded.

Convert the downloaded JSON:

```powershell
python -m app.migration --export runtime/gym-legacy-export.json --out runtime/migration-01
```

Alternatively, use a consistent local SQLite snapshot with `--sqlite runtime/legacy-snapshot.db --username YOUR_USERNAME`. SQLite is opened read-only. This tool does not connect to production or back up authentication state; obtain a full production backup separately before cutover.

Outputs include a checksummed `legacy.json`, `opengym-plan.json`, and reconciliation report. Repeating an unchanged export is safe; different contents require a new destination. Each gym day becomes a routine. Unknown exercises become editable custom exercises, pending review. An optional `--mapping` JSON maps source exercise IDs to reviewed upstream IDs, for example `{"12":{"id":"0025","load_convention":"barbell total lb"}}`.

Import the plan once through openGym's Plan import into the intended profile. Upstream plan imports add fresh routines; rerunning that UI import duplicates routines. Set rotation order using the report, review catalogue/equipment mappings and starting weights, then enable progression per exercise as desired. The converter deliberately does not invent individual completed sets from old summaries, so old history remains in the legacy tracker/export and stays out of new volume/progression calculations.

## API and dashboard contract

- `GET /api/v1/training/summary?anchor=YYYY-MM-DD`: cookie-authenticated, mapped owner only.
- `GET /api/v1/assistant/training`: existing assistant token authentication plus the same owner check.
- `GET /api/v1/assistant/summary`: unchanged legacy response for existing consumers.

The new response includes a version, Chicago calendar-week boundaries, source status, fetch time, canonical units, source-qualified activity IDs, totals and evidence-linked observations. Missing/failed sources yield null totals, not false zeroes. Source fetch time does not assert that all watch runs have been imported. Running time uses active timer time; elapsed time is preserved separately. Source ownership is enforced, hidden activities are excluded, and GPS locations are excluded from the summary. Endurain strength and openGym cardio are excluded so the two stores do not count the same sport twice. Identical provider IDs are deduplicated; unrelated activities are never merged merely because they share a start time.

Working rep-set counts include completed unilateral sides separately, matching the pinned upstream convention, and omit warm-ups. These are set-completion counts, not a replacement for upstream volume, timed-work or strength statistics. Running load and lifting sets remain separate. Weekly observations are deterministic summaries, not adaptive coaching or injury predictions.

The dashboard companion change adds local registry entries and an optional private Assistant card. Set `TRAINING_HUB_URL` and `TRAINING_HUB_TOKEN` on the dashboard and the matching `ASSISTANT_READ_TOKEN` on the hub. The dashboard receives only allowlisted numeric totals and source states; it holds no openGym or Endurain session tokens. Existing production registry targets remain intact pending deployment.

## Back up and rehearse restoration

```powershell
python scripts/training_backup.py backup runtime/backups/backup-01
python scripts/training_backup.py restore runtime/backups/backup-01 --project aisaac-training-restore-test01
```

Backup briefly stops staging writers, captures PostgreSQL and both file stores plus the hub database, copies the required encryption configuration, and resumes the previously running writers. Files are checksummed. Restoration refuses an existing volume set and writes only to a new project beginning `aisaac-training-restore-`; it never overwrites staging or production volumes. The restored PostgreSQL service is stopped afterward, with recovery volumes retained for inspection. Backup files include sensitive application/encryption secrets; restrict access and encrypt them before off-machine storage. Backup and migration directories use mode 0700 and files use 0600 on POSIX. Windows inherits host-directory ACLs; use a folder restricted to your Windows account. Session connection files need re-pairing after recovery.

## Production gate and remaining pilot

Local verification can use clearly labeled synthetic data. It does not complete the real Apple Watch pilot or reconcile your production history. Before release, complete the actual three-run field comparison, 3–5 real lifting sessions, source ownership mapping, reviewed exercise mappings, off-machine backup/restore, stable HTTPS hostname selection, and production resource/cost approval. Enable invite-only access after initial enrollment. No production app is replaced by starting local staging.

The first release exposes weekly summaries and links to the native apps. Advanced suggestions, comparison over comparable runs, race-goal planning, custom native app builds, watch workout delivery, automatic schedules, and provider-billed AI remain follow-up work rather than silently activated features.
