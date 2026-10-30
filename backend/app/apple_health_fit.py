"""Health Auto Export v2 running workouts -> FIT, without inferred samples."""

import math
from datetime import UTC, datetime
from uuid import UUID

from garmin_fit_sdk import Encoder
from garmin_fit_sdk.profile import Profile

RUN_NAMES = {"Running", "Outdoor Running", "Indoor Running", "Trail Running", "Treadmill Running",
             "Outdoor Run", "Indoor Run"}  # the "... Run" names are what Health Auto Export sends
HR_UNITS = {"count/min": 1, "bpm": 1}  # Health Auto Export v2 sends "count/min"
MAX_SAMPLES = 100_000


class InvalidWorkout(ValueError):
    """Only static field names / reasons may be returned to a client."""


def number(value, field, low=0, high=1e9):
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise InvalidWorkout(f"Invalid {field}")
    if not math.isfinite(value) or not low <= value <= high:
        raise InvalidWorkout(f"Invalid {field}")
    return float(value)


def timestamp(value):
    if not isinstance(value, str) or len(value) > 50:
        raise InvalidWorkout("Invalid timestamp")
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            raise ValueError
        parsed = parsed.astimezone(UTC)
        if not 1990 <= parsed.year <= 2100:
            raise ValueError
        return parsed.timestamp()
    except ValueError:
        raise InvalidWorkout("Timestamps must include a timezone") from None


def quantity(value, field, factors, high=1e9):
    if not isinstance(value, dict) or value.get("units") not in factors:
        raise InvalidWorkout(f"Unsupported units for {field}")
    return number(value.get("qty"), field, high=high) * factors[value["units"]]


def array(workout, key):
    value = workout.get(key, [])
    if not isinstance(value, list) or len(value) > MAX_SAMPLES:
        raise InvalidWorkout(f"Invalid or oversized {key}")
    if any(not isinstance(item, dict) for item in value):
        raise InvalidWorkout(f"Invalid {key} sample")
    return value


def normalize(workout):
    """Validate only supported fields and retain canonical, bounded SI values."""
    if not isinstance(workout, dict):
        raise InvalidWorkout("Invalid workout")
    if workout.get("name") not in RUN_NAMES:
        return None
    try:
        source_id = str(UUID(workout["id"]))
    except (KeyError, ValueError, TypeError, AttributeError):
        raise InvalidWorkout("Running workouts require a version 2 UUID") from None
    start, end = timestamp(workout.get("start")), timestamp(workout.get("end"))
    elapsed = end - start
    duration = number(workout.get("duration"), "duration", low=0.001, high=604800)
    if elapsed <= 0 or elapsed > 604800 or duration > elapsed + 1:
        raise InvalidWorkout("Invalid workout time range")
    result = {"id": source_id, "start": start, "end": end, "duration": min(duration, elapsed),
              "utc_offset": datetime.fromisoformat(workout["end"]).utcoffset().total_seconds(),
              "indoor": workout.get("isIndoor") is True or workout.get("location") == "Indoor"
              or workout["name"] in {"Indoor Running", "Treadmill Running", "Indoor Run"},
              "records": []}
    if "distance" not in workout:
        raise InvalidWorkout("Running export requires recorded distance")
    result["distance"] = quantity(workout["distance"], "distance",
                                  {"m": 1, "km": 1000, "mi": 1609.344})
    if result["distance"] > 1_000_000:
        raise InvalidWorkout("Invalid distance")
    for source, target in [("avgHeartRate", "avg_hr"), ("maxHeartRate", "max_hr")]:
        value = workout.get(source, workout.get("heartRate", {}).get(
            "avg" if target == "avg_hr" else "max")) if isinstance(
                workout.get("heartRate", {}), dict) else workout.get(source)
        if value is not None:
            result[target] = quantity(value, "heart rate", HR_UNITS, high=254)
    for source, target in [("activeEnergyBurned", "calories"),
                           ("elevationUp", "ascent"), ("elevationDown", "descent")]:
        if source in workout:
            factors = {"kcal": 1, "kJ": 1 / 4.184} if target == "calories" else {
                "m": 1, "ft": 0.3048}
            value = quantity(workout[source], source, factors)
            if value >= 65535:
                raise InvalidWorkout(f"Invalid {source}")
            result[target] = value
    records = {}

    def point(when, slack=0):
        seconds = timestamp(when)
        if not start - slack <= seconds <= end + slack:
            raise InvalidWorkout("Sample outside workout time range")
        seconds = min(max(seconds, start), end)  # snap bucket edges into the workout
        return records.setdefault(seconds, {"time": seconds})

    for sample in array(workout, "heartRateData"):
        record = point(sample.get("date"), slack=60)  # minute-grouped buckets straddle edges
        if sample.get("units") not in HR_UNITS:
            raise InvalidWorkout("Unsupported heart rate units")
        record["heart_rate"] = round(number(sample.get("Avg"), "heart rate", low=1, high=254))
    for sample in array(workout, "route"):
        record = point(sample.get("timestamp"))
        record["lat"] = number(sample.get("latitude"), "latitude", -90, 90)
        record["lon"] = number(sample.get("longitude"), "longitude", -180, 180)
        if record["lon"] == 180:
            record["lon"] = -180  # Same meridian; +180 exceeds FIT's signed semicircle range.
        if "altitude" in sample:
            record["altitude"] = number(sample["altitude"], "altitude", -500, 10000)
        if "speed" in sample and sample["speed"] >= 0:
            record["speed"] = number(sample["speed"], "speed", high=100)
    if len(records) > MAX_SAMPLES:
        raise InvalidWorkout("Too many combined samples")
    result["records"] = sorted(records.values(), key=lambda item: item["time"])
    return result


def to_fit(workout):
    """FIT session totals preserve Apple timer time even when pauses lack timestamps."""
    encoder = Encoder()

    def write(kind, **fields):
        encoder.write_mesg({"mesg_num": Profile["mesg_num"][kind.upper()], **fields})

    def dt(seconds):
        return datetime.fromtimestamp(seconds, UTC)

    start, end = dt(workout["start"]), dt(workout["end"])
    write("file_id", type="activity", manufacturer="development", product=0,
          serial_number=int(UUID(workout["id"])) & 0xFFFFFFFF, time_created=start)
    write("workout", sport="running", wkt_name="Apple Workout run")
    # No fabricated GPS, distance progression, splits, or timer pause events.
    for sample in workout["records"]:
        fields = {"timestamp": dt(sample["time"])}
        if "lat" in sample:
            fields.update(position_lat=round(sample["lat"] * 2**31 / 180),
                          position_long=round(sample["lon"] * 2**31 / 180))
        for source, target in [("altitude", "enhanced_altitude"),
                               ("speed", "enhanced_speed"), ("heart_rate", "heart_rate")]:
            if source in sample:
                fields[target] = sample[source]
        write("record", **fields)
    fields = {"timestamp": end, "start_time": start, "sport": "running",
              "sub_sport": "treadmill" if workout["indoor"] else "generic",
              "total_elapsed_time": workout["end"] - workout["start"],
              "total_timer_time": workout["duration"], "first_lap_index": 0, "num_laps": 1,
              "event": "lap", "event_type": "stop"}
    for source, target in [("distance", "total_distance"), ("avg_hr", "avg_heart_rate"),
                           ("max_hr", "max_heart_rate"), ("calories", "total_calories"),
                           ("ascent", "total_ascent"), ("descent", "total_descent")]:
        if source in workout:
            fields[target] = round(workout[source]) if source != "distance" else workout[source]
    if "distance" in workout:
        fields["enhanced_avg_speed"] = workout["distance"] / workout["duration"]
    write("lap", message_index=0, **fields)
    fields.update(event="session", num_laps=1)
    write("session", message_index=0, **fields)
    write("activity", timestamp=end, local_timestamp=dt(workout["end"] + workout["utc_offset"]),
          total_timer_time=workout["duration"],
          num_sessions=1, type="manual", event="activity", event_type="stop")
    return bytes(encoder.close())
