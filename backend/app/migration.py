"""Portable, owner-scoped legacy export and openGym plan conversion.

No historical result is interpreted as a completed set. Export files are private
data; callers choose a new output directory outside source control.
"""

import argparse
import hashlib
import json
import os
import sqlite3
from datetime import UTC
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, joinedload

from app.models import GymDay, LoggedSession, Routine, User


def _iso(value):
    return value.replace(tzinfo=value.tzinfo or UTC).astimezone(UTC).isoformat()


def export_legacy(db: Session, user: User) -> dict:
    routines = db.scalars(
        select(Routine).options(joinedload(Routine.gym_days).joinedload(GymDay.exercises))
        .where(Routine.user_id == user.id).order_by(Routine.id)
    ).unique().all()
    days = {d.id: d for r in routines for d in r.gym_days}
    sessions = db.scalars(
        select(LoggedSession).options(joinedload(LoggedSession.results))
        .where(LoggedSession.gym_day_id.in_(days)).order_by(LoggedSession.id)
    ).unique().all() if days else []
    return {
        "format": "gym-legacy-v1", "owner": {"id": user.id, "username": user.username},
        "unit": "lb", "timestamp_convention": "UTC",
        "history_semantics": "One summary per exercise; individual completed sets are unknown.",
        "routines": [{
            "id": r.id, "name": r.name, "is_active": r.is_active,
            "gym_days": [{
                "id": d.id, "name": d.name, "order_index": d.order_index,
                "exercises": [{
                    "id": e.id, "name": e.name, "muscle_group": e.muscle_group,
                    "sets": e.sets, "rep_range_low": e.rep_range_low,
                    "rep_range_high": e.rep_range_high,
                } for e in d.exercises],
            } for d in r.gym_days],
        } for r in routines],
        "sessions": [{
            "id": s.id, "gym_day_id": s.gym_day_id, "logged_at": _iso(s.logged_at),
            "results": [{"exercise_definition_id": e.exercise_definition_id,
                         "weight_lb": e.weight_lb, "reps_done": e.reps_done}
                        for e in sorted(s.results, key=lambda x: x.id)],
        } for s in sessions],
    }


def plan_from_export(snapshot: dict, mapping: dict | None = None) -> tuple[dict, dict]:
    if snapshot.get("format") != "gym-legacy-v1" or snapshot.get("unit") != "lb":
        raise ValueError("Expected a gym-legacy-v1 export in pounds")
    mapping = mapping or {}
    custom, routines, exercise_map, rotation = {}, [], [], []
    for routine in snapshot["routines"]:
        for day in sorted(routine["gym_days"], key=lambda d: d["order_index"]):
            rid = f"legacy-r{routine['id']}-d{day['id']}"
            exercises = []
            for e in day["exercises"]:
                key = str(e["id"])
                target = mapping.get(key)
                eid = target["id"] if target else f"legacy-exercise-{key}"
                if not target:
                    custom[eid] = {
                        "id": eid, "n": e["name"], "bp": "",
                        "desc": "Imported routine definition. Source muscle group: "
                        + e["muscle_group"] + ". Review equipment and muscle mapping.",
                    }
                exercises.append({"id": eid, "sets": e["sets"],
                                  "reps": e["rep_range_high"], "repsMin": e["rep_range_low"],
                                  "weight": 0, "prog": "off"})
                exercise_map.append({"source_id": e["id"], "name": e["name"],
                                     "target_id": eid, "reviewed": bool(target),
                                     "load_convention": target.get("load_convention")
                                     if target else None})
            routines.append({"id": rid, "name": routine["name"] + " / " + day["name"],
                             "prog": "off", "ex": exercises})
            if routine["is_active"]:
                rotation.append(rid)
    plan = {"opengym_plan": 1, "name": "Legacy gym routines", "unit": "lb",
            "week": {}, "routines": routines, "customEx": list(custom.values())}
    report = {
        "routines": len(snapshot["routines"]), "gym_days": len(routines),
        "exercise_definitions": len(exercise_map), "legacy_sessions": len(snapshot["sessions"]),
        "legacy_results_preserved": sum(len(s["results"]) for s in snapshot["sessions"]),
        "completed_sets_inferred": 0, "historical_workouts_imported": 0,
        "exercise_mapping": exercise_map, "rotation_source_ids": rotation,
        "warnings": [
            "Historical summaries remain in legacy.json; they are not completed sets.",
            "Set starting weights and review equipment/muscle mappings in openGym.",
            "Plan imports add routines. Import once into the intended empty profile.",
            "Set the rotation using the imported routine order; weekday assignments are unknown.",
        ],
    }
    return plan, report


def write_bundle(snapshot: dict, destination: Path, mapping: dict | None = None):
    plan, report = plan_from_export(snapshot, mapping)
    documents = {"legacy.json": snapshot, "opengym-plan.json": plan, "report.json": report}
    encoded = {k: (json.dumps(v, indent=2, ensure_ascii=False) + "\n").encode()
               for k, v in documents.items()}
    manifest = {"format": 1, "sha256": {k: hashlib.sha256(v).hexdigest()
                                        for k, v in encoded.items()}}
    encoded["manifest.json"] = (json.dumps(manifest, indent=2) + "\n").encode()
    if destination.exists():
        # Repeating an unchanged export is safe; different data never overwrite a prior export.
        if all((destination / k).is_file() and (destination / k).read_bytes() == v
               for k, v in encoded.items()):
            return report
        raise FileExistsError("Choose a new output directory for the changed export")
    destination.mkdir(mode=0o700, parents=True)
    for name, content in encoded.items():
        fd = os.open(destination / name, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--sqlite", type=Path, help="Read-only local database snapshot")
    source.add_argument("--export", type=Path, help="Owner-scoped portable JSON export")
    parser.add_argument("--username")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--mapping", type=Path, help="Reviewed exercise-ID mapping JSON")
    args = parser.parse_args()
    mapping = json.loads(args.mapping.read_text(encoding="utf-8")) if args.mapping else None
    if args.export:
        snapshot = json.loads(args.export.read_text(encoding="utf-8"))
    else:
        if not args.username or not args.sqlite.is_file():
            parser.error("--sqlite requires an existing snapshot and --username")
        uri = args.sqlite.resolve().as_uri() + "?mode=ro"
        engine = create_engine("sqlite://", creator=lambda: sqlite3.connect(uri, uri=True))
        try:
            with Session(engine) as db:
                user = db.scalar(select(User).where(User.username == args.username))
                if user is None:
                    parser.error("Requested user not found")
                snapshot = export_legacy(db, user)
        finally:
            engine.dispose()
    report = write_bundle(snapshot, args.out, mapping)
    print(json.dumps({k: v for k, v in report.items()
                      if k not in {"exercise_mapping", "rotation_source_ids"}}, indent=2))


if __name__ == "__main__":
    main()
