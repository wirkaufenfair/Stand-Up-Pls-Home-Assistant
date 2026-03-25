"""Device actions for Stand Up Pls Desk."""
from __future__ import annotations

from typing import Any

from homeassistant.core import Context, HomeAssistant
from homeassistant.helpers import device_registry as dr

from .const import DOMAIN

ACTION_TYPES = ["up", "down", "stop"]


def _is_standup_desk_device(device: dr.DeviceEntry) -> bool:
    return any(identifier[0] == DOMAIN for identifier in device.identifiers)


async def async_get_actions(
    hass: HomeAssistant, device_id: str
) -> list[dict[str, Any]]:
    """Return device actions for the desk."""
    device_registry = dr.async_get(hass)
    device = device_registry.async_get(device_id)
    if not device or not _is_standup_desk_device(device):
        return []

    return [
        {
            "domain": DOMAIN,
            "device_id": device_id,
            "type": action_type,
        }
        for action_type in ACTION_TYPES
    ]


async def async_call_action(
    hass: HomeAssistant,
    config: dict[str, Any],
    variables: dict[str, Any],
    context: Context | None,
) -> None:
    """Execute a device action."""
    action_type = config["type"]
    await hass.services.async_call(
        DOMAIN,
        "control",
        {
            "action": action_type,
            "device_id": [config["device_id"]],
        },
        blocking=True,
        context=context,
    )


async def async_get_action_capabilities(
    hass: HomeAssistant, config: dict[str, Any]
) -> dict[str, Any]:
    """Return action capabilities."""
    return {}
