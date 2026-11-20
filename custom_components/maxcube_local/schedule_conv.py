"""Conversion between the Cube's weekly programme and Home Assistant schedules.

Two formats are involved:

Cube (``maxcube-api``)::

    {"monday": [{"temp": 12, "until": "12:00"},
                {"temp": 20, "until": "23:00"},
                {"temp": 12, "until": "24:00"}], ...}

Home Assistant ``schedule`` helper::

    {"monday": [{"from": "00:00", "to": "12:00", "data": {"temp": 12}},
                {"from": "12:00", "to": "23:00", "data": {"temp": 20}},
                {"from": "23:00", "to": "24:00", "data": {"temp": 12}}], ...}

The mapping is mechanical: each Cube point's ``until`` becomes a HA ``to``, and
its start is the previous point's ``until`` (or ``"00:00"`` for the first).  The
Cube temperature travels in ``data: {temp: ...}``, which the HA schedule schema
accepts as free-form per-range data.

Note the different day ordering: the Cube library keys the dict
Saturday-first (``DAYS`` in ``maxcube.cube``), while HA and the ISO week are
Monday-first.  ``DAY_ORDER`` below is authoritative for both directions.
"""

from __future__ import annotations

from typing import Any

# ISO order, which is what HA templates and humans expect.
DAY_ORDER: tuple[str, ...] = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)

# The Cube's final point always ends at midnight; HA spell it "24:00" too, and
# its own schedule schema maps that to time.max internally.
END_OF_DAY = "24:00"
START_OF_DAY = "00:00"

# The library asserts temp <= 32, in 0.5 steps, and times in 5-minute steps.
MAX_TEMP = 32.0
MIN_TEMP = 0.0
TEMP_STEP = 0.5
TIME_STEP_MINUTES = 5


class ScheduleConversionError(ValueError):
    """Raised when a programme cannot be converted to/from the HA format."""


def _minutes_of_day(hhmm: str) -> int:
    """Return minutes since midnight for an ``HH:MM`` string.

    ``"24:00"`` is accepted as end-of-day (1440).  Anything else must be a real
    24-hour time, because ``datetime.strptime`` rejects hour 24.
    """
    if hhmm == END_OF_DAY:
        return 24 * 60
    parts = hhmm.split(":")
    if len(parts) < 2:
        raise ScheduleConversionError(f"Invalid time {hhmm!r}, expected HH:MM")
    try:
        hour = int(parts[0])
        minute = int(parts[1])
    except ValueError as err:
        raise ScheduleConversionError(
            f"Invalid time {hhmm!r}, expected HH:MM"
        ) from err
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        raise ScheduleConversionError(f"Invalid time {hhmm!r}, expected HH:MM")
    return hour * 60 + minute


def _normalise_hhmm(hhmm: str) -> str:
    """Return ``HH:MM`` with zero padding, keeping ``24:00`` intact."""
    if hhmm == END_OF_DAY:
        return END_OF_DAY
    total = _minutes_of_day(hhmm)
    return f"{total // 60:02d}:{total % 60:02d}"


def programme_to_schedule(programme: dict[str, list[dict[str, Any]]]) -> dict:
    """Convert a Cube programme dict into the HA ``schedule`` day format.

    Returns a dict keyed by weekday with a list of
    ``{from, to, data: {temp}}`` ranges per day.  Days missing from the input
    are emitted as empty lists, because the HA schedule schema expects every
    weekday key to be present.
    """
    schedule: dict[str, list[dict[str, Any]]] = {}

    for day in DAY_ORDER:
        points = programme.get(day) or []
        if not points:
            schedule[day] = []
            continue

        ranges: list[dict[str, Any]] = []
        cursor = START_OF_DAY
        for point in points:
            try:
                until = point["until"]
                temp = point["temp"]
            except (TypeError, KeyError) as err:
                raise ScheduleConversionError(
                    f"Malformed programme entry for {day}: {point!r}"
                ) from err

            end = _normalise_hhmm(str(until))
            if _minutes_of_day(end) < _minutes_of_day(cursor):
                raise ScheduleConversionError(
                    f"Schedule for {day} is not ascending: {cursor} -> {end}"
                )

            ranges.append({CONF_FROM: cursor, CONF_TO: end, CONF_DATA: {CONF_TEMP: temp}})
            cursor = end

        # The day must cover the full 24 h, otherwise the thermostat falls back
        # to its comfort temperature for the remainder.
        if cursor != END_OF_DAY:
            raise ScheduleConversionError(
                f"Schedule for {day} ends at {cursor}, expected {END_OF_DAY}"
            )

        schedule[day] = ranges

    return schedule


# Field names, kept as constants so the service schema and this module agree.
CONF_FROM = "from"
CONF_TO = "to"
CONF_DATA = "data"
CONF_TEMP = "temp"


def schedule_to_programme(
    schedule: dict[str, list[dict[str, Any]]],
) -> dict[str, list[dict[str, Any]]]:
    """Convert an HA ``schedule`` day mapping back into the Cube format.

    This is the inverse of :func:`programme_to_schedule` and is what a future
    "write back to the Cube" service would use.  Times are validated and
    normalised; overlapping or non-ascending ranges are rejected.
    """
    programme: dict[str, list[dict[str, Any]]] = {}

    for day in DAY_ORDER:
        ranges = schedule.get(day) or []
        if not ranges:
            programme[day] = []
            continue

        points: list[dict[str, Any]] = []
        previous_end = START_OF_DAY
        for entry in ranges:
            try:
                start = entry[CONF_FROM]
                end = entry[CONF_TO]
                temp = entry.get(CONF_DATA, {}).get(CONF_TEMP)
            except (TypeError, KeyError) as err:
                raise ScheduleConversionError(
                    f"Malformed schedule entry for {day}: {entry!r}"
                ) from err

            if temp is None:
                raise ScheduleConversionError(
                    f"Schedule entry for {day} has no {CONF_DATA!r}.{CONF_TEMP!r}"
                )

            start_min = _minutes_of_day(str(start))
            end_min = _minutes_of_day(str(end))
            if start_min != _minutes_of_day(previous_end):
                raise ScheduleConversionError(
                    f"Schedule for {day} has a gap or overlap at {start} "
                    f"(previous range ended at {previous_end})"
                )
            if end_min <= start_min:
                raise ScheduleConversionError(
                    f"Schedule for {day} has an empty range {start} -> {end}"
                )

            points.append({CONF_TEMP: temp, "until": _normalise_hhmm(str(end))})
            previous_end = _normalise_hhmm(str(end))

        if previous_end != END_OF_DAY:
            raise ScheduleConversionError(
                f"Schedule for {day} ends at {previous_end}, expected {END_OF_DAY}"
            )

        programme[day] = points

    return programme


def validate_temperature(temp: Any) -> float:
    """Validate a temperature against the Cube's limits.

    The library asserts these, but an ``AssertionError`` from a service handler
    surfaces as an unhandled traceback.  Checking here turns it into a proper
    user-facing error.
    """
    try:
        value = float(temp)
    except (TypeError, ValueError) as err:
        raise ScheduleConversionError(f"Temperature {temp!r} is not a number") from err

    if not MIN_TEMP <= value <= MAX_TEMP:
        raise ScheduleConversionError(
            f"Temperature {value} °C is outside {MIN_TEMP}–{MAX_TEMP} °C"
        )
    if (value * 2) % 1 != 0:
        raise ScheduleConversionError(
            f"Temperature {value} °C must be in {TEMP_STEP} °C steps"
        )
    return value


def validate_schedule(schedule: Any) -> dict:
    """Validate a schedule mapping from a service call.

    Ensures every weekday key is known, every day covers 00:00–24:00 without
    gaps, and every temperature is within the Cube's limits.
    """
    if not isinstance(schedule, dict):
        raise ScheduleConversionError("schedule must be a mapping of weekday to ranges")

    unknown = set(schedule) - set(DAY_ORDER)
    if unknown:
        raise ScheduleConversionError(
            f"Unknown weekday(s): {', '.join(sorted(unknown))}. "
            f"Expected {', '.join(DAY_ORDER)}"
        )

    # Validate first, so a bad entry aborts before anything is converted.
    cleaned: dict[str, list[dict[str, Any]]] = {}
    for day in DAY_ORDER:
        ranges = schedule.get(day) or []
        if not isinstance(ranges, list):
            raise ScheduleConversionError(f"{day} must be a list of ranges")

        cleaned[day] = []
        cursor = START_OF_DAY
        for entry in ranges:
            if not isinstance(entry, dict):
                raise ScheduleConversionError(
                    f"Malformed schedule entry for {day}: {entry!r}"
                )
            start = str(entry.get(CONF_FROM, ""))
            end = str(entry.get(CONF_TO, ""))
            temp = entry.get(CONF_DATA, {}).get(CONF_TEMP)

            if start != cursor:
                raise ScheduleConversionError(
                    f"{day}: range starts at {start!r}, expected {cursor!r}"
                )
            if _minutes_of_day(end) <= _minutes_of_day(start):
                raise ScheduleConversionError(
                    f"{day}: range {start} -> {end} is empty or reversed"
                )

            validate_temperature(temp)
            cleaned[day].append(
                {CONF_FROM: _normalise_hhmm(start),
                 CONF_TO: _normalise_hhmm(end),
                 CONF_DATA: {CONF_TEMP: float(temp)}}
            )
            cursor = _normalise_hhmm(end)

        if cursor != END_OF_DAY:
            raise ScheduleConversionError(
                f"{day}: schedule ends at {cursor}, expected {END_OF_DAY}"
            )

    return cleaned