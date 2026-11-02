"""Read-only, single-owner integration with pinned openGym and Endurain APIs.

Upstream response bodies and credentials never enter error responses. The two
stores own their sport: openGym cardio and Endurain strength are not counted.
"""

import math
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import httpx

from app.config import _setting, load_settings
from app.training_tokens import EndurainSession

RUN_TYPES = {1: "Run", 2: "Trail run", 3: "Virtual run", 34: "Track run", 40: "Treadmill"}
CARDIO_TYPES = RUN_TYPES | {4: "Ride", 5: "Gravel ride", 6: "MTB ride", 7: "Virtual ride",
                           8: "Lap swimming", 9: "Open water swimming", 11: "Walk", 12: "Hike",
                           27: "Commuting ride", 28: "Indoor ride", 29: "Mixed surface ride",
                           31: "Indoor walking", 35: "E-Bike ride", 36: "E-Mountain Bike ride"}


@dataclass(frozen=True)
class TrainingSettings:
    username: str
    timezone: str
    opengym_url: str
    opengym_public_url: str
    opengym_uid: str
    opengym_token: str = field(repr=False)
    endurain_url: str = ""
    endurain_public_url: str = ""
    endurain_user_id: str = ""
    endurain_token_file: str = field(default="", repr=False)

    @classmethod
    def load(cls):
        return cls(
            username=_setting("TRAINING_USERNAME", ""),
            timezone=_setting("TRAINING_TIMEZONE", "America/Chicago"),
            opengym_url=_setting("OPENGYM_URL", ""),
            opengym_public_url=_setting("OPENGYM_PUBLIC_URL", ""),
            opengym_uid=_setting("OPENGYM_UID", ""),
            opengym_token=_setting("OPENGYM_TOKEN", ""),
            endurain_url=_setting("ENDURAIN_URL", ""),
            endurain_public_url=_setting("ENDURAIN_PUBLIC_URL", ""),
            endurain_user_id=_setting("ENDURAIN_USER_ID", ""),
            endurain_token_file=_setting("ENDURAIN_TOKEN_FILE", ""),
        )


def safe_url(value: str, *, public: bool = False) -> str | None:
    if not value:
        return None
    p = urlsplit(value)
    if p.username or p.password or p.query or p.fragment or not p.hostname:
        raise ValueError("Invalid integration URL")
    local = p.hostname in {"localhost", "127.0.0.1", "::1", "opengym-api", "endurain"}
    if p.scheme != "https" and not (
        p.scheme == "http" and local and load_settings().app_env == "development"
    ):
        raise ValueError("Integration URLs require HTTPS outside local development")
    if public and p.hostname in {"opengym-api", "endurain"}:
        raise ValueError("Public URL must be reachable by the browser")
    return value.rstrip("/")


def _number(value):
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value) if math.isfinite(value) and value >= 0 else None


def _instant(value) -> datetime | None:
    try:
        if isinstance(value, int | float) and not isinstance(value, bool):
            return datetime.fromtimestamp(value / 1000, UTC)
        if isinstance(value, str):
            d = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return d.astimezone(UTC) if d.tzinfo else None
    except (ValueError, OverflowError, OSError):
        pass
    return None


def week_window(anchor: date, timezone: str):
    zone = ZoneInfo(timezone)
    monday = anchor - timedelta(days=anchor.weekday())
    return (
        datetime.combine(monday, time.min, zone),
        datetime.combine(monday + timedelta(days=7), time.min, zone),
    )


def lifting_activities(state: dict, start: datetime, end: datetime) -> list[dict]:
    """Summarize actual rep sets; leave upstream strength/progression math upstream."""
    activities = []
    seen = set()
    for w in state.get("workouts", []):
        wid = str(w.get("id", ""))
        if not wid or wid in seen or w.get("legacy_summary"):
            continue
        stamp = _instant(w.get("start"))
        if stamp is None:
            try:
                stamp = datetime.combine(date.fromisoformat(w["d"]), time(12), start.tzinfo)
            except (KeyError, ValueError, TypeError):
                continue
        if not start <= stamp < end:
            continue
        sets = 0
        exercise_ids = set()
        for entry in w.get("entries", []):
            if entry.get("mode") in {"cardio", "time"}:
                continue
            for row in entry.get("sets", []):
                phase = row.get("phase")
                warm = (str(phase).lower() in {"warmup", "warm-up", "warm_up"}) if phase else (
                    row.get("warmup") is True
                )
                sides = row.get("sides")
                work_rows = [sides.get(side, {}) for side in ("L", "R")] if sides else [row]
                completed = sum(1 for work in work_rows if work.get("done") is True
                                and (_number(work.get("r")) or 0) > 0)
                if not warm and completed:
                    sets += completed
                    exercise_ids.add(str(entry.get("id", "")))
        if not sets and not w.get("summary_only"):
            continue
        finish = _instant(w.get("end"))
        duration = (finish - stamp).total_seconds() if finish and finish >= stamp else None
        activities.append({
            "id": "opengym:" + wid, "source": "opengym", "sport": "lifting",
            "name": str(w.get("name") or "Lifting"),
            "started_at": stamp.isoformat(),
            "local_date": stamp.astimezone(start.tzinfo).date().isoformat(),
            "duration_seconds": duration, "working_sets": sets,
            "summary_only": bool(w.get("summary_only")),
            "exercise_count": len(exercise_ids),
        })
        seen.add(wid)
    return activities


def running_activities(rows: list[dict], user_id: str, start: datetime, end: datetime):
    activities = []
    seen = set()
    provider_ids = set()
    for row in rows:
        if str(row.get("user_id")) != user_id:
            raise ValueError("Profile mismatch")
        if row.get("is_hidden") or row.get("activity_type") not in CARDIO_TYPES:
            continue
        rid = str(row.get("id", ""))
        stamp = _instant(row.get("start_time"))
        providers = {(k, str(row[k])) for k in (
            "strava_activity_id", "garminconnect_activity_id"
        ) if row.get(k) is not None}
        if not rid or rid in seen or providers & provider_ids:
            continue
        if stamp is None or not start <= stamp < end:
            continue
        distance = _number(row.get("distance"))
        timer = _number(row.get("total_timer_time"))
        elapsed = _number(row.get("total_elapsed_time"))
        # Unknown active time stays unknown: elapsed time includes pauses.
        pace = timer / (distance / 1000) if distance and timer is not None else None
        activities.append({
            "id": "endurain:" + rid, "source": "endurain",
            "sport": "running" if row["activity_type"] in RUN_TYPES else "cardio",
            "name": str(row.get("name") or CARDIO_TYPES[row["activity_type"]]),
            "run_type": CARDIO_TYPES[row["activity_type"]], "started_at": stamp.isoformat(),
            "local_date": stamp.astimezone(start.tzinfo).date().isoformat(),
            "distance_meters": distance, "duration_seconds": timer,
            "elapsed_seconds": elapsed, "pace_seconds_per_km": pace,
            "average_heart_rate": _number(row.get("average_hr")),
        })
        seen.add(rid)
        provider_ids.update(providers)
    return activities


def _json(client, url, headers, params=None):
    response = client.get(url, headers=headers, params=params)
    response.raise_for_status()
    return response.json()


def _open_data(client, cfg):
    base = safe_url(cfg.opengym_url)
    headers = {"Authorization": "Bearer " + cfg.opengym_token}
    me = _json(client, base + "/api/me", headers)
    if str(me.get("user", {}).get("id")) != cfg.opengym_uid:
        raise ValueError("Profile mismatch")
    payload = _json(client, base + "/api/data", headers)
    data = payload["state"]
    if data is not None and not isinstance(data, dict):
        raise ValueError("Invalid upstream state")
    return data or {}


def _run_data(client, cfg, start, end):
    base = safe_url(cfg.endurain_url)
    session = EndurainSession(cfg.endurain_token_file, base, client)
    rows = []
    for page in range(1, 26):
        payload = session.get("/api/v1/activities", {
            "page_number": page, "num_records": 100,
            "start_date": (start.date() - timedelta(days=1)).isoformat(),
            "end_date": end.date().isoformat(),
        })
        items, total = payload["items"], payload["total"]
        if not isinstance(items, list) or not isinstance(total, int):
            raise ValueError("Invalid activities response")
        rows.extend(items)
        if len(rows) >= total:
            return rows
        if not items:
            raise ValueError("Incomplete activities response")
    raise ValueError("Activities exceed bounded read; refine the query")


def build_summary(cfg: TrainingSettings, anchor: date | None = None, client=None) -> dict:
    now = datetime.now(UTC)
    zone = ZoneInfo(cfg.timezone)
    start, end = week_window(anchor or now.astimezone(zone).date(), cfg.timezone)
    owned_client = client is None
    client = client or httpx.Client(timeout=8, follow_redirects=False, trust_env=False)
    sources, activities = {}, []
    try:
        for name, configured, reader in (
            ("opengym", cfg.opengym_url and cfg.opengym_token and cfg.opengym_uid,
             lambda: lifting_activities(_open_data(client, cfg), start, end)),
            ("endurain", cfg.endurain_url and cfg.endurain_token_file and cfg.endurain_user_id,
             lambda: running_activities(_run_data(client, cfg, start, end),
                                       cfg.endurain_user_id, start, end)),
        ):
            source = {"state": "not_connected", "fetched_at": None,
                      "latest_activity_at": None}
            if configured:
                try:
                    found = reader()
                    activities.extend(found)
                    source.update(state="ok", fetched_at=now.isoformat(),
                                  latest_activity_at=max(
                                      (a["started_at"] for a in found), default=None))
                except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError, OSError):
                    source["state"] = "unavailable"
            sources[name] = source
    finally:
        if owned_client:
            client.close()
    activities.sort(key=lambda a: a["started_at"], reverse=True)
    lifts = [a for a in activities if a["sport"] == "lifting"]
    runs = [a for a in activities if a["sport"] == "running"]
    distance_values = [a["distance_meters"] for a in runs if a["distance_meters"] is not None]
    duration_values = [a["duration_seconds"] for a in runs if a["duration_seconds"] is not None]
    links = {}
    for key, value in (("opengym", cfg.opengym_public_url),
                       ("endurain", cfg.endurain_public_url)):
        try:
            links[key] = safe_url(value, public=True)
        except ValueError:
            links[key] = None
    # A missing or failed source must never read as a week of zero training.
    totals = {
        "lifting_sessions": len(lifts) if sources["opengym"]["state"] == "ok" else None,
        "working_sets": sum(a["working_sets"] for a in lifts)
        if sources["opengym"]["state"] == "ok" else None,
        "runs": len(runs) if sources["endurain"]["state"] == "ok" else None,
        "cardio_sessions": sum(a["sport"] == "cardio" for a in activities)
        if sources["endurain"]["state"] == "ok" else None,
        "running_distance_meters": sum(distance_values)
        if sources["endurain"]["state"] == "ok" and len(distance_values) == len(runs) else None,
        "running_timer_seconds": sum(duration_values)
        if sources["endurain"]["state"] == "ok" and len(duration_values) == len(runs) else None,
        "longest_run_meters": max(distance_values, default=None),
    }
    observations = []
    if totals["runs"] is not None:
        run_label = "run" if len(runs) == 1 else "runs"
        observations.append({"text": f"{len(runs)} {run_label} recorded this week.",
                             "evidence": [a["id"] for a in runs]})
    if totals["lifting_sessions"] is not None:
        lift_label = "session" if len(lifts) == 1 else "sessions"
        observations.append({"text": f"{len(lifts)} lifting {lift_label} recorded this week.",
                             "evidence": [a["id"] for a in lifts]})
    return {
        "schema_version": 1, "generated_at": now.isoformat(), "timezone": cfg.timezone,
        "week_start": start.date().isoformat(), "week_end_exclusive": end.date().isoformat(),
        "sources": sources, "links": links, "totals": totals, "activities": activities,
        "observations": observations,
        "notes": ["Legacy summary entries are excluded from individual-set statistics.",
                  "Fetched time confirms API access, not that every watch run has been imported.",
                  "Running effort and lifting sets are reported separately."],
    }
