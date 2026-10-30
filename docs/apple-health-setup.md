# Apple Watch → private training server

Record runs in Apple's Workout app as usual. Health Auto Export on the iPhone
reads Apple Health with your permission and sends JSON to this computer over
Tailscale. The hub stores a durable import job, converts it to FIT, and submits it
to your separate Endurain profile. Endurain completion appears in the hub's
**Apple Watch sync** card. HTTP 202 means stored for processing, not yet imported.

## iPhone setup

1. Install Tailscale on your iPhone, sign into the same tailnet as this computer,
   and connect it. This computer, Docker Desktop, and Tailscale must stay running
   and the computer must be awake for uploads to arrive.
2. Install [Health Auto Export](https://www.healthyapps.dev/). Automatic REST
   exports require its paid automation feature; no purchase is made by this code.
   Grant read access to Workouts, workout routes if desired, running distance,
   workout heart rate and active energy. Apple ID credentials are never needed.
3. In Health Auto Export: **Automations → New Automation → REST API**. Name it
   `My training server`.
4. Get the URL and `Authorization` header value from the private local file
   `runtime/apple-health-phone.json`. Add that header in the automation's HTTP
   Headers section. The bearer value is an upload credential: keep it private,
   put it only in the header, and do not paste it into a URL or chat.
5. Set **Data Type: Workouts**, **Format: JSON**, **Export Version: 2**.
   Enable **Include Workout Metrics**. Enable **Include Route Data** if you want
   maps in Endurain. Start with minute grouping; second grouping can produce very
   large exports. Select running if the app offers a workout-type filter; the
   receiver also skips non-running sports.
6. Use **Default** date range (previous day through now) for normal repeated sync,
   about hourly cadence, and **Batch Requests ON**. Overlap is safe. Limit initial
   historical imports to small date ranges; at most 100 workouts / 16 MiB per
   request are accepted. Shorten the range if a request is rejected as too large.
7. Run one **Manual Export** from that automation. In the hub on this computer,
   sign in to your personal local profile, click Refresh, and verify that the run
   progresses from pending to imported. Compare distance, active duration, start
   time and heart rate against Apple Fitness before enabling ongoing sync.
8. Enable the automation and Background App Refresh. iOS controls background
   delivery; sync may wait until the iPhone is unlocked. A widget/manual run can
   trigger it when needed. This is periodic syncing, not guaranteed real time.

The app's [REST setup guide](https://help.healthyapps.dev/en/health-auto-export/automations/rest-api/)
and [background limitations](https://help.healthyapps.dev/en/health-auto-export/automations/)
describe the current controls. No real Apple workout has been verified until the
first phone-side export is compared with Apple Fitness.

## Server enrollment and private HTTPS

The receiver is disabled unless `APPLE_HEALTH_CONFIG_FILE` points to a private
connection file. The file's owner, Endurain account ID and URL must exactly match
the hub's `TRAINING_USERNAME`, `ENDURAIN_USER_ID` and `ENDURAIN_URL`.
`APPLE_HEALTH_QUEUE` must be on persistent storage, `/data/apple-health.sqlite`
in the provided stack. Run one hub process. Local development may use only the
known loopback/Compose HTTP upstream hosts; other connections require HTTPS.

For a new account, connect its mobile session with the existing
`app.training_tokens` helper, set Endurain's default activity visibility to
**private**, then run `python -m app.apple_health_setup --help`.
That interactive helper verifies the session's account ID/privacy and creates
an `activities:upload` key after password/MFA verification. It saves two new
files without overwriting existing credentials: a server connection containing
only a hash of the inbound bearer, and phone settings containing the raw bearer
but no Endurain credential. Protect both with your account's ACLs.

The local personal profile is separate from the demo. Its illustrative local
email is not an address configured for mail/recovery. Replace it in Endurain
before enabling any email-dependent features. Production has not been changed.

After inspecting `tailscale serve status --json` to avoid replacing another
service, expose only the upload route within the tailnet:

```powershell
tailscale serve --bg --https=8443 --set-path=/api/v1/integrations/apple-health/workouts http://127.0.0.1:18080/api/v1/integrations/apple-health/workouts
```

Use the HTTPS hostname Tailscale reports, with port 8443 and that path. This is
**Serve**, which is private to the tailnet; do not enable Funnel. Tailscale's
tailnet access rules must allow the iPhone to this computer on port 8443.
The upload endpoint additionally requires its dedicated bearer credential.
Verify unauthenticated uploads return 401 and unrelated paths are unavailable.

Remove only this route if needed:

```powershell
tailscale serve --https=8443 --set-path=/api/v1/integrations/apple-health/workouts off
```

## Fidelity and recovery

- Supported: running, including indoor/trail labels. Other sports are skipped to
  keep lifting in openGym. Localized workout type names require a reviewed mapping;
  set the exporter to English if runs are skipped unexpectedly.
- Required: version 2 UUID, offset-aware start/end, active duration and recorded
  distance with m/km/mi units. A missing distance is rejected rather than becoming
  a misleading zero in Endurain. Optional GPS and heart rate may be absent.
- FIT preserves recorded distance and active versus elapsed duration, summary
  heart rate when supplied, optional measured samples/route/elevation, and the
  source UTC offset for GPS-less runs. It does not invent distance samples,
  splits or pause locations. Endurain may resolve GPS timezone from location and
  recompute heart-rate summaries from the supplied grouped samples, so averages
  can differ from Apple Fitness. Raw FIT records are pruned from the outbox after
  completion; Endurain owns the resulting activity file and streams.
- Repeated UUIDs do not create a second import. If supported data for the same
  UUID changes, the existing import is kept and the hub reports a review flag.
  Source edits/deletions do not automatically edit/delete Endurain activities.
  Do not send the same runs through Strava/manual files as well without reconciling
  duplicates across those routes.
- A stored ingestion-job ID resumes polling after restart. A crash after upload
  but before saving its ID repeats the same Endurain idempotency key. The outbox
  is bound to owner/server/account; reusing it after remapping fails closed.
- Transient network/server failures retry with backoff. Credential rejection and
  ingestion failure remain visible as failed. After repairing/replacing an
  upload key for the same account, run `python -m app.apple_health` to count
  credential failures, then repeat with `--apply` to retry only those failures.
  Parser failures and changed exports need manual review; re-exporting does not
  silently overwrite completed data.
- The outbox is inside the existing hub `/data` backup. Connection files and
  phone credentials are deliberately separate: protect/back them up privately
  or recreate them after recovery. Preserve the outbox when rotating credentials.
- Set `APPLE_HEALTH_CONFIG_FILE` empty and recreate the hub to disable the
  receiver/worker. To revoke the phone alone, create a new pairing credential and
  replace the configured server file with the new hash. Never remove the outbox
  simply to fix a connection; that discards duplicate/retry history.

Status: `GET /api/v1/training/apple-health` requires the mapped owner's cookie and
contains only job IDs/state/timestamps and static error codes. No GPS, heart-rate
streams or credentials are returned. Upload body validation errors omit submitted
values. This endpoint does not grant upload access through the browser cookie.
