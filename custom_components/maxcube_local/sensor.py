"""Sensor platform for eQ-3 MAX! Cube (valve position, temperature, schedule)."""

from __future__ import annotations

from typing import Any

from maxcube.device import MaxDevice

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .coordinator import MaxCubeConfigEntry, MaxCubeCoordinator
from .entity import MaxCubeEntity
from .schedule_conv import ScheduleConversionError, programme_to_schedule


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MaxCubeConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up valve-position, temperature and schedule sensors."""
    coordinator = entry.runtime_data
    cube = coordinator.cube
    entities: list[SensorEntity] = []
    for device in cube.devices:
        if device.is_thermostat():
            entities.append(MaxCubeValve(coordinator, device))
        if device.is_thermostat() or device.is_wallthermostat():
            entities.append(MaxCubeTemperature(coordinator, device))
            entities.append(MaxCubeWeeklySchedule(coordinator, device))
    async_add_entities(entities)


class MaxCubeValve(MaxCubeEntity, SensorEntity):
    """Valve opening percentage of a radiator thermostat."""

    _attr_translation_key = "valve_position"
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:radiator"

    def __init__(self, coordinator: MaxCubeCoordinator, device: MaxDevice) -> None:
        """Initialize the valve-position sensor."""
        super().__init__(coordinator, device)
        self._attr_unique_id = f"{device.rf_address}_valve"

    @property
    def native_value(self) -> int | None:
        """Return the valve opening in percent."""
        return getattr(self._device, "valve_position", None)


class MaxCubeTemperature(MaxCubeEntity, SensorEntity):
    """Measured room temperature reported by a thermostat."""

    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 1

    def __init__(self, coordinator: MaxCubeCoordinator, device: MaxDevice) -> None:
        """Initialize the temperature sensor."""
        super().__init__(coordinator, device)
        self._attr_unique_id = f"{device.rf_address}_temperature"

    @property
    def native_value(self) -> float | None:
        """Return the measured temperature, if the device reports one."""
        temp = getattr(self._device, "actual_temperature", None)
        # Radiator thermostats only report a temperature in auto/manual mode.
        return temp if temp else None


# ISO weekday order, matching ``schedule_conv.DAY_ORDER`` and ``datetime``.
WEEKDAYS: tuple[str, ...] = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)


def _to_minutes(hhmm: str) -> int:
    """Return minutes since midnight for an ``HH:MM`` string."""
    if hhmm == "24:00":
        return 1440
    hour, minute = hhmm.split(":")
    return int(hour) * 60 + int(minute)


def _active_temp(schedule: dict[str, list[dict[str, Any]]]) -> float | None:
    """Return the temperature the programme prescribes for right now."""
    now = dt_util.now()
    ranges = schedule.get(WEEKDAYS[now.weekday()]) or []
    minute = now.hour * 60 + now.minute
    for entry in ranges:
        start = _to_minutes(str(entry["from"]))
        end = _to_minutes(str(entry["to"]))
        if start <= minute < end:
            return entry.get("data", {}).get("temp")
    return None


class MaxCubeWeeklySchedule(MaxCubeEntity, SensorEntity):
    """A thermostat's weekly programme, exposed as a structured attribute.

    The sensor state is the temperature the programme prescribes for the
    current moment, so the entity is a real sensor rather than a bare data
    holder.  The full week lives in ``extra_state_attributes["schedule"]`` in
    the same ``{from, to, data: {temp}}`` shape Home Assistant's ``schedule``
    helper uses, which is what the bundled Lovelace card renders.
    """

    _attr_translation_key = "weekly_schedule"
    _attr_icon = "mdi:calendar-clock"

    def __init__(self, coordinator: MaxCubeCoordinator, device: MaxDevice) -> None:
        """Initialize the weekly-schedule sensor."""
        super().__init__(coordinator, device)
        self._attr_unique_id = f"{device.rf_address}_weekly_schedule"

    @property
    def _schedule(self) -> dict[str, list[dict[str, Any]]] | None:
        """Return the converted programme, or ``None`` if unavailable/invalid."""
        programme = getattr(self._device, "programme", None)
        if not programme:
            return None
        try:
            return programme_to_schedule(programme)
        except ScheduleConversionError:
            # A malformed programme must not take the entity down.
            return None

    @property
    def native_value(self) -> float | None:
        """Return the temperature the programme prescribes right now."""
        schedule = self._schedule
        return _active_temp(schedule) if schedule else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose the whole week plus the identifiers the card needs."""
        attrs: dict[str, Any] = {
            "rf_address": self._rf_address,
            "device_name": self._device.name,
        }
        schedule = self._schedule
        if schedule is not None:
            attrs["schedule"] = schedule
        return attrs