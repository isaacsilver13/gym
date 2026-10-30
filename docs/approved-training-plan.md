**Training project enhancement plan: openGym + Endurain**

Prepared October 27, 2026. This is an implementation plan based on repository inspection; production data, deployments, and credentials have not been inspected or changed.

**Recommendation**

Build the next version of your gym project on openGym for lifting and Endurain for running. Retain each application's native interface and storage, and connect both through a small integration layer for your dashboard and assistant. Keep your existing project available during migration.

The goal is a personal training hub with complete set logging, lifting progression, running history and analysis, a combined weekly view, phone access, and ownership of your data. You currently record runs with Apple Watch / Apple Fitness; preserve that workflow. Start with upstream behavior and introduce customization only where it solves a specific need.

Endurain is included in the agreed scope. Its initial implementation milestone is a three-run import pilot; that pilot validates the integration and data quality before production use. Its documented capabilities include maps, activity statistics, goals, and file/provider imports. Adaptive coaching is a separate project feature to build and validate, rather than an assumed Endurain capability. Its current feature freeze favors planning around existing functionality.

| Approach | Benefit | Cost | Assessment |
|---|---|---|---|
| Configure openGym and maintain a small fork when needed | Most capabilities arrive together; upstream improvements remain accessible | Migrate history and integrations; adapt hosting | Recommended |
| Rebuild selected features inside the existing app | Retains FastAPI, Postgres, and current authentication | Reimplement workout UX, per-set storage, progression, offline behavior, and sync | Fallback if retaining the existing architecture is essential |
| Replace openGym's backend with your FastAPI backend | Familiar infrastructure | Significant compatibility work across state, authentication, and sync | Defer unless a concrete requirement justifies it |

**What the code establishes**

Your current app uses FastAPI, SQLAlchemy, React/TypeScript, and a single Fly.io deployment. Its model represents a routine as ordered gym days, each containing exercise definitions. A logged exercise result contains one weight in pounds and one reps value for a session. The UI also accepts only that one result; it does not record the individual sets behind it. Your assistant endpoint returns the next gym day and latest/best recent exercise results.

openGym provides a complete workout application. Its Node API stores profile state as JSON in a data directory; its React frontend and nginx proxy share an origin with that API. This storage and sync model differs materially from your current Postgres model. Establish openGym as the authoritative store for new lifting workouts after cutover. Endurain becomes the application's running history and analysis store, with original Apple Watch exports retained for reproducible imports.

Endurain uses FastAPI and PostgreSQL with activity-file storage. Operate it independently of openGym; do not merge their databases or make either application's internal tables part of the other's contract. The integration layer reads supported interfaces and produces a normalized training summary.

Baseline the work on v1.4.3, the latest published release verified during this review, released October 26, 2026. Pin the source commit and image digests during implementation. Recheck the chosen release's behavior instead of assuming development-branch documentation always describes it exactly.

**Repository and application boundaries**

- Keep the existing gym repository and its history. Put the migration exporter, mapping reports, and migration instructions there initially.
- Use an upstream-tracking openGym fork or checkout as the new application source. Preserve upstream history, notices, and version information. Do not replace your old repository's root with an upstream source dump.
- Deploy a pinned Endurain release with configuration maintained alongside the project's integration/deployment files. Begin with an unmodified upstream image; introduce a fork only if a verified integration requirement needs a code change.
- Keep an explicit mapping between your openGym profile, Endurain user, and integration identity. Separate deployments do not imply shared accounts or single sign-on.
- Keep deployment configuration and integration code in clearly identified project-owned paths. Minimize edits to upstream frontend and training helpers.
- After successful cutover, the existing application becomes the legacy history viewer and migration reference. Retire its write path before retiring its infrastructure.
- Retain old database backups and any unconverted historical records independently of the new deployment.
- Treat the training hub as a read model initially: openGym owns lifting edits, Endurain owns imported running records, and Apple Workout remains the run recorder. Give each workout a source and stable identifier so one workout is not counted twice across services.

**Phase 0 — Establish the migration baseline**

Work:

- Confirm the canonical repository location and production deployment configuration; the GitHub content service currently resolves the old gym_tracker path to gym.
- Inventory users, routines, gym days, exercise definitions, sessions, and results using authorized production access during implementation. Record counts and export timestamps.
- Capture the deployed source revision, existing configuration names, dashboard consumers, assistant consumers, and current URL.
- Inventory the available Apple Watch running history, confirm how a single run can be exported, and identify which permissions the chosen export path requires. No paid bridge app, account connection, or upload is assumed to have been configured.
- Produce an application-consistent database backup and a portable data export. Keep password hashes, session secrets, and other authentication material out of migration reports.
- Confirm what your old reps value means in practice: a representative set, last set, total reps, or another convention. Preserve the original value regardless.
- Select a stable production hostname before enrolling production passkeys. Staging gets separate profiles and enrollment.
- Review upstream code and media terms for the intended personal fork. Preserve AGPL notices and upstream attribution; media have separate terms. A standalone app assembled from copied animations is outside the plan.

Done when: source versions, integrations, export counts, backup/restore procedure, and the treatment of historical results are documented.

**Phase 1 — Prove the new app in staging**

Work:

- Run the pinned upstream release with its standard web/API topology and a disposable profile.
- Configure pounds, your preferred workout layout, and an ordered rotation matching your current gym-day sequence. Retain any weekday-specific scheduling only where you actually use it.
- Recreate one real routine, including exercise order, planned sets, and rep ranges. Review ambiguous exercise matches and weight conventions: barbell total load, dumbbell load per hand, assistance, and added bodyweight load.
- Exercise the complete flow on your phone: sign in, start, record different results per set, use a timer, interrupt/reopen, finish, and view history.
- Test offline logging followed by reconnect and sync, plus concurrent edits on two devices.
- Keep automatic progression off while establishing imported plans and historical baselines. Enable the chosen rule once its inputs are trustworthy.

Hosting proposal: retain Fly.io if a small deployment adapter can preserve upstream behavior. First prove web/API routing, process startup and shutdown, internal DNS, health checks, durable storage, and restart/deploy recovery. Fly does not consume the upstream Compose file as a deployment specification, so this requires explicit packaging/configuration work. Compare one app containing managed web/API processes with separate web and API apps before choosing the smaller maintenance burden.

The API requires persistent storage for its data directory, including profile state, authentication state, and uploads. Use a single active API writer initially and a mounted persistent volume; do not add independent API replicas writing separate JSON stores. Establish off-machine backups and test restoration. Fly's ephemeral root filesystem and automatic volume snapshots are insufficient as the sole persistence/backup strategy.

Done when: a workout survives offline/reconnect, process restart, and a staging deployment, and a clean restoration reproduces the profile. If Fly packaging becomes extensive, use the supported Compose topology on a suitable Docker host and retain dashboard integration.

**Phase 2 — Move routines and preserve history honestly**

Migration outputs:

- A portable source export with original identifiers, UTC timestamps, raw weight/reps values, and a checksum manifest.
- A reviewed exercise mapping table, including source exercise ID, equipment/load convention, target catalogue/custom ID, and unresolved matches.
- An openGym-compatible plan import and, where justified, a historical-workout import.
- A reconciliation report with accepted, rejected, unmatched, and intentionally unconverted records.

| Existing data | Proposed destination | Rule |
|---|---|---|
| Routine containing multiple gym days | Group of openGym session routines | Preserve original parent names and day order |
| Planned exercise sets and rep range | Routine exercise prescription | Preserve planned values; they are not evidence of completed work |
| Free-text exercise name | Reviewed catalogue match or custom exercise | Never silently choose the wrong machine or variant |
| Pounds | Explicitly declared source units and target conversion | Verify round trips; avoid double conversion |
| Session timestamp | Original timestamp plus intended local workout date | Test midnight and daylight-saving boundaries |
| Single historical weight/reps result | Preserved legacy record | Never expand into the planned number of completed sets |
| Existing account | Newly enrolled openGym profile | Map ownership; do not assume password hashes or sessions transfer |

Default historical policy: retain old results in a clearly labeled legacy history view/export, outside the calculations for new per-set workouts. If you confirm that an old row represents a real single set, offer a reviewed import of that observed set only. If it is a session summary or total, preserve it as such. Do not silently interpret a summary as one completed set either.

Use the supported plan importer for routines and a tested history import path for eligible records. Workout CSV imports do not create routines. The generic CSV path may group or skip records by date, and plan imports add new routines; neither behavior is sufficient proof of migration idempotency. Use source-ID mapping and a migration manifest, rehearse repeated runs, and explicitly test two sessions on the same day. If standard imports cannot preserve identity and metadata, implement a narrow migration adapter against the pinned schema.

Import into an empty staging profile first. Use supported import/sync flows; do not mutate live server JSON files behind the running API. Reconcile all source records, including those intentionally left in the legacy archive. Missing duration, effort, or individual-set details remain unknown.

Done when: every source record is accounted for; all routine structure and unit conventions match; rerunning migration creates no duplicate records; new progression and volume statistics are not contaminated by inferred history.

**Running workstream — Endurain and Apple Watch**

Begin after the baseline and staging setup, alongside the lifting migration. Include this workstream in the initial release scope, with its own acceptance gate so a running-import issue does not corrupt lifting data.

Data flow:

Apple Workout on Apple Watch → Apple Health on iPhone → reviewed FIT export → Endurain → authenticated integration adapter → training dashboard and weekly report.

HealthFit is the proposed export bridge because it supports Apple Health workout data and FIT exports. First validate a manual export of one activity; installing or purchasing it is a later setup choice. An Apple Workout → Strava → Endurain sync route is an alternative if you prefer that account connection. Pick one primary ingestion route before automating it, and test duplicates when any route changes. Automatic HealthFit-to-Endurain delivery is not assumed to exist.

Work:

- Select and pin a supported Endurain release/image at implementation time, checking release notes, import behavior, API authentication, and deployment requirements.
- Deploy isolated staging with PostgreSQL and durable activity-file storage. Back up and restore the database and files together; verify that restored activity details and maps open correctly.
- Export and import three representative real runs: an outdoor steady run, an interval run if available, and a treadmill run if available. Where these are unavailable, use distinct existing runs and document untested cases.
- Compare each activity with Apple Fitness: original start time, local date, elapsed/moving time, distance, pace, route, heart rate, cadence, elevation, and intervals/laps where the source provides them. Record which fields survive rather than assuming every Apple metric is supported.
- Handle miles/kilometers and min/mile versus min/km explicitly. Preserve unknown fields as unknown; a treadmill run without GPS must remain usable without a route.
- Retain original FIT files, checksums, and an import manifest. Reimport one run to test duplicate handling and test a second run on the same day.
- Map imported activity ownership to your Endurain user and prove profile isolation. Keep GPS routes out of assistant payloads unless a requested analysis needs them.
- After the small pilot passes, import the historical running archive in batches and reconcile accepted, duplicate, and failed activities. Do not introduce bulk history and automated ingestion simultaneously.
- Add authenticated API reads to the integration adapter for running summaries. Confirm supported scopes and response fields on the pinned version; avoid binding the hub to internal database tables.
- Assess incremental automation only after the manual route works. A later scheduled uploader or provider sync needs retry behavior, deduplication, visible last-success time, and an error queue; this document does not create a scheduled job.

Done when: three real runs reconcile with documented tolerances, field losses are understood, reimports are safe, database/files restore together, and the hub can read an authorized running summary. The next milestone is a historical import and a reproducible ongoing ingestion route.

**Phase 3 — Restore your project integrations**

Dashboard:

- Inventory its actual registry contract and replace the old application's health/URL entry only after staging verification.
- Connect an appropriate health endpoint and include persistence/backup checks in the runbook. Distinguish a running web proxy from a working API.
- Link to the enhanced app and document deployment, restoration, and upstream upgrades.
- Add separate lifting and running entry points, service-health indicators, and last-import times. The initial hub can link to native application screens; a unified replacement UI is unnecessary for the first release.

Assistant:

- Preserve the useful response contract of your existing /api/v1/assistant/summary endpoint through a small authenticated compatibility adapter or an explicit consumer migration.
- Return routine/next session, recent logged results, and selected progress summaries with stable exercise identifiers and units.
- Keep legacy summaries labeled separately from new individual sets. Distinguish heaviest weight, best estimated 1RM, and best rep performance instead of presenting them as the same record.
- Restrict access to the intended profile and verify authentication failures and cross-profile isolation. The current assistant token is not an openGym login and must not become a public proxy to a full profile.
- Prefer API-based reads for a remotely hosted app. openGym's bundled MCP read tools currently expect filesystem access to its data directory; they cannot be assumed to read the Fly deployment from your desktop. Evaluate a narrow authenticated remote adapter later if conversational analysis is useful.
- Add a new combined training-summary contract while preserving the existing lifting-only endpoint for current consumers. Include activity source, source ID, timestamp, timezone, units, data freshness, and any missing metrics.
- Return weekly lifting sessions, selected lift trends, running frequency/distance/time, longest run, and pace/heart-rate comparisons where comparable source data exists. Count the same Apple Watch workout once even if it appears in more than one service.
- Calculate numerical summaries deterministically. Any assistant explanation should cite the source sessions and distinguish observed changes from hypotheses. Compare like-for-like runs; do not treat pace differences across hills, intervals, and treadmill sessions as a simple fitness trend.
- Keep running load and lifting volume as separate metrics unless a documented, validated model supports combining them. openGym's muscle-fatigue map is not a validated readiness score for running.

Done when: dashboard checks work, existing assistant consumers receive expected information, and expired/missing credentials or another profile cannot expose training data.

**Phase 4 — Pilot, reconcile, and cut over**

- Use staging for 3–5 real workouts across your usual gym days. Evaluate logging speed, exercise naming, timers, interrupted sessions, and confidence in next-session targets.
- Complete the three-run Endurain pilot and review one combined weekly report before the running workstream goes live. Keep recording runs in Apple Workout throughout the transition.
- Keep a simple pilot log describing where each workout was recorded. Avoid two competing writable histories.
- Resolve migration discrepancies and decide which progression rules to enable per exercise, including available load increments and machine stacks.
- Take a final legacy backup/export, pause its write path, and import any records created since the rehearsal snapshot.
- Verify the production hostname, account enrollment, phone pairing, migration totals, integrations, and a new save/read cycle before redirecting your normal entry point.
- Retain the old app as read-only while confirming the new version works through normal use. Remove its production infrastructure only after legacy access and backups have an agreed long-term home.

Rollback: before accepting new production workouts, the old application and database remain the recovery path. Once the new application accepts workouts, export those additions before any rollback and reconcile them explicitly; restoring an old database alone would discard newer training. Keep the failed new deployment's data intact for recovery.

For Endurain rollback, retain original activity exports and a consistent database/file backup. Preserve activities added since the backup before restoring it. A running-service rollback must not roll back openGym's lifting data.

Done when: your lifting and running workflows work, records reconcile, both services restore correctly, the combined report counts activities correctly, and each rollback procedure handles post-cutover additions.

**Phase 5 — Add optional enhancements from real use**

Prioritize these after the core tracker is stable:

1. Expand the initial combined weekly report with comparisons over longer periods, selected lift trends, body-weight trend, and training distribution.
2. Assistant questions over both reliable histories, initially read-only. Examples: what changed in running consistency, whether comparable easy runs show a pace/heart-rate change, and how runs and lower-body lifting are distributed through the week.
3. Optional AI coach, using the application's review/apply workflow and a separately configured provider. Set data-sharing preferences and spending limits when enabling it.
4. Conversational workout entry, only after preview, exercise matching, duplicate handling, and write authorization are verified.
5. Goal-aware running suggestions based on your stated goal, recent training, available days, and perceived effort. Present proposed changes for review with their supporting data. Race predictions, injury-risk scores, automatic plan changes, and workouts pushed to the watch require separate design and validation; they are not initial-release promises.
6. Wearable/health integrations that fit your actual devices. Keep Apple Workout as the running recorder and test the official openGym app paired with your server before considering custom native builds.

Avoid early changes to upstream sync, authentication, progression formulas, or the exercise catalogue. Avoid a custom App Store release and a Postgres rewrite unless a later requirement makes their ongoing maintenance worthwhile.

**Implementation work packages**

| Package | Deliverable | Depends on |
|---|---|---|
| 1. Baseline and preservation | Inventory, source export, backup/restore rehearsal, migration policy | Authorized source-data access |
| 2. Upstream baseline | Pinned source, isolated staging, real routine trial | Package 1 |
| 3. Production hosting | Fly packaging decision, durable state, HTTPS, health checks, backup restoration | Package 2 |
| 4. Data migration | Exercise map, plan conversion, eligible-history import, reconciliation tests | Packages 1–2 |
| 5. Endurain baseline | Pinned staging service, PostgreSQL/file storage, backup restoration | Package 1 |
| 6. Apple Watch import | Three-run FIT pilot, field/duplicate checks, import manifest, historical-import procedure | Package 5 |
| 7. Project integration | Dashboard entries, lifting compatibility adapter, running API adapter, combined weekly report | Packages 2–3 and 5–6 |
| 8. Pilot and launch | Trial reports, final migrations, independent cutover and rollback runbooks | Packages 3–7 |
| 9. Ongoing run ingestion | Validated incremental import/sync route and failure visibility | Packages 6–8 |
| 10. Optional enhancements | Goal-aware feedback and improvements based on actual use | Package 8 |

The original lifting-only estimate was 8–15 focused development days. Allow approximately 4–8 additional days for Endurain staging, a working Apple Watch file-import route, and the initial combined report: roughly 12–23 focused development days overall, plus the real-workout pilot. Automatic ongoing ingestion and advanced coaching should be estimated after the three-run pilot. These are initial effort estimates, not calendar commitments. The main uncertainties are production access, exercise mapping, history size, Fly packaging, preservation of Apple Watch fields, and the integration APIs. Re-estimate after the staging migrations. Two services, PostgreSQL, durable files, and backups expand the hosting footprint; price the chosen topology before production deployment. Optional AI/provider and bridge-app costs require explicit setup choices.

**Maintenance and release acceptance**

Keep upstream changes separate from local integrations; record every local patch and why it exists. Trial upstream releases in staging with a restored copy or fixtures before upgrading production. For each upgrade, check the import format, API/sync contract, authentication, one complete workout, and assistant output. Back up before upgrading and document data compatibility before downgrading.

Migration and integration tests should cover unit conversion, ambiguous exercise names, legacy-summary exclusion, duplicate imports, multiple same-day sessions, timezone boundaries, account isolation, sync conflicts, and backup restoration. Run the relevant upstream checks for touched code. Verify phone behavior manually where a unit test cannot prove it.

For Endurain and the combined report, additionally verify FIT field preservation, missing GPS/heart-rate data, moving versus elapsed time, interval/lap support, pace-unit conversion, cross-source duplicate detection, stale ingestion, independent service failure, and consistent database/file restoration. Compare a report against known fixtures covering both sports.

The first reviewable implementation milestone is an openGym staging profile containing one of your routines, an Endurain staging user containing three Apple Watch runs, and a migration/import reconciliation report. Follow it with one combined weekly report before production cutover.

**Sources inspected**

- [Your gym app README](https://github.com/isaacsilver13/gym/blob/be0c2710b371f17be9b9eed1d52077e89ea01f55/README.md)
- [Your data model](https://github.com/isaacsilver13/gym/blob/be0c2710b371f17be9b9eed1d52077e89ea01f55/backend/app/models.py)
- [Your logging screen](https://github.com/isaacsilver13/gym/blob/be0c2710b371f17be9b9eed1d52077e89ea01f55/frontend/src/pages/RoutineDetail.tsx)
- [Your assistant endpoint](https://github.com/isaacsilver13/gym/blob/be0c2710b371f17be9b9eed1d52077e89ea01f55/backend/app/api/assistant.py)
- [Your Fly configuration](https://github.com/isaacsilver13/gym/blob/be0c2710b371f17be9b9eed1d52077e89ea01f55/fly.toml)
- [openGym release v1.4.3](https://github.com/DuarteSantos8/openGym/releases/tag/v1.4.3)
- [openGym overview](https://github.com/DuarteSantos8/openGym)
- [Import and export documentation](https://github.com/DuarteSantos8/openGym/blob/main/docs/DATA_IMPORTS.md)
- [Plan importer](https://github.com/DuarteSantos8/openGym/blob/main/frontend/src/lib/plan-share.js)
- [CSV importer](https://github.com/DuarteSantos8/openGym/blob/main/frontend/src/lib/import-csv.js)
- [Self-hosting guide](https://github.com/DuarteSantos8/openGym/blob/main/docs/SELF_HOSTING.md)
- [Deployment topology](https://github.com/DuarteSantos8/openGym/blob/main/docker-compose.yml)
- [API specification](https://github.com/DuarteSantos8/openGym/blob/main/api/openapi.yaml)
- [MCP capabilities and limitations](https://github.com/DuarteSantos8/openGym/blob/main/mcp/README.md)
- [Code and media notices](https://github.com/DuarteSantos8/openGym/blob/main/NOTICE.md)
- [Fly persistent-volume documentation](https://docs.fly.io/volumes/overview)
- [Endurain repository](https://github.com/endurain-project/endurain)
- [Endurain features and project status](https://endurain.com/)
- [Endurain imports and duplicate detection](https://docs.endurain.com/features/importing/)
- [HealthFit: Apple Health analysis and FIT export](https://apps.apple.com/us/app/healthfit/id1202650514)
- [Apple Workout and Strava synchronization](https://support.strava.com/en-us/articles/15402024-apple-health-and-strava)
