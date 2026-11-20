"""Service handlers for the eQ-3 MAX! Cube integration.

Currently one service:

``maxcube_local.export_schedule``
    Returns the weekly programme of a thermostat in the shape a Home Assistant
    ``schedule`` helper expects, plus the YAML needed to create that helper.
    Read-only: it never writes to the Cube.

The reverse direction (writing an edited schedule back to the Cube) is
deliberately not implemented yet.
"""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
import yaml

from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN
from .coordinator import MaxCubeConfigEntry, MaxCubeCoordinator
from .schedule_conv import (
    ScheduleConversionError,
    programme_to_schedule,
)

_LOGGER = logging.getLogger(__name__)

ATTR_DEVICE = "device_id"
ATTR_SHOW_YAML = "show_yaml"

SERVICE_EXPORT_SCHEDULE = "export_schedule"

EXPORT_SCHEDULE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_DEVICE): cv.entity_id,
        vol.Optional(ATTR_SHOW_YAML, default=True): cv.boolean,
    }
)


def _resolve_coordinator(
    hass: HomeAssistant, entity_id: str
) -> tuple[MaxCubeCoordinator, Any]:
    """Return the coordinator and device for a climate entity.

    Raises ServiceValidationError when the entity is not a MAX! climate entity,
    which is the case the user can actually fix (wrong entity picked).
    """
    registry = er.async_get(hass)
    entry = registry.async_get(entity_id)

    if entry is None or entry.platform != DOMAIN:
        raise ServiceValidationError(
            f"{entity_id} is not an entity of the MAX! Cube integration"
        )

    config_entry = hass.config_entries.async_get_entry(entry.config_entry_id)
    if config_entry is None:
        raise ServiceValidationError(
            f"No config entry found for {entity_id}"
        )

    coordinator: MaxCubeCoordinator = config_entry.runtime_data
    device = coordinator.cube.device_by_rf(
        # The unique id of a climate entity is the device RF address.
        entry.unique_id
    )
    if device is None:
        raise ServiceValidationError(
            f"Could not find a MAX! device for {entity_id}"
        )

    return coordinator, device


def _schedule_yaml(name: str, schedule: dict) -> str:
    """Render the schedule as a YAML snippet ready to paste into configuration."""
    payload = {"schedule": [{"platform": "schedule", "name": name}]}
    payload["schedule"][0].update(schedule)
    return yaml.safe_dump(payload, sort_keys=False, allow_unicode=True).rstrip()


@callback
def async_register_services(hass: HomeAssistant) -> None:
    """Register the integration's services."""

    async def async_export_schedule(call: ServiceCall) -> ServiceResponse:
        """Return a thermostat's weekly programme in HA schedule format."""
        entity_id: str = call.data[ATTR_DEVICE]
        show_yaml: bool = call.data[ATTR_SHOW_YAML]

        coordinator, device = _resolve_coordinator(hass, entity_id)

        programme = getattr(device, "programme", None)
        if not programme:
            raise ServiceValidationError(
                f"{device.name or entity_id} has no weekly programme"
            )

        try:
            schedule = programme_to_schedule(programme)
        except ScheduleConversionError as err:
            raise ServiceValidationError(
                f"Could not convert the programme of {device.name}: {err}"
            ) from err

        result: dict[str, Any] = {
            "device_id": entity_id,
            "name": device.name or entity_id,
            "schedule": schedule,
        }
        if show_yaml:
            result["yaml"] = _schedule_yaml(device.name or entity_id, schedule)

        return result

    hass.services.async_register(
        DOMAIN,
        SERVICE_EXPORT_SCHEDULE,
        async_export_schedule,
        schema=EXPORT_SCHEDULE_SCHEMA,
        supports_response="only",
    )


@callback
def async_unregister_services(hass: HomeAssistant) -> None:
    """Remove the integration's services."""
    hass.services.async_remove(DOMAIN, SERVICE_EXPORT_SCHEDULE)