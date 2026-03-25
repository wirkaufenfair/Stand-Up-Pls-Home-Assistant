"""Button platform for Stand Up Pls Desk — preset movement buttons."""
from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, MANUFACTURER, MODEL
from . import StandUpDeskConnection

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    connection: StandUpDeskConnection = hass.data[DOMAIN][entry.entry_id]
    mac = entry.data["mac"]
    name = entry.data.get("device_name", "Stand Up Desk")

    async_add_entities([
        StandUpDeskButton(connection, entry, mac, name, "sit", "Sit", "mdi:seat-recline-normal"),
        StandUpDeskButton(connection, entry, mac, name, "stand", "Stand", "mdi:human-male-height"),
        StandUpDeskButton(connection, entry, mac, name, "stop", "Stop", "mdi:stop"),
    ])


class StandUpDeskButton(ButtonEntity):
    """Button entity to trigger a desk action."""

    _attr_has_entity_name = True

    def __init__(
        self,
        connection: StandUpDeskConnection,
        entry: ConfigEntry,
        mac: str,
        device_name: str,
        action: str,
        entity_name: str,
        icon: str,
    ) -> None:
        self._connection = connection
        self._action = action
        self._attr_unique_id = f"{entry.entry_id}_{action}"
        self._attr_name = entity_name
        self._attr_icon = icon
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, mac)},
            name=device_name,
            manufacturer=MANUFACTURER,
            model=MODEL,
        )

    async def async_press(self) -> None:
        if self._action == "stop":
            await self._connection.stop()
        elif self._action == "stand":
            await self._connection.move_to_height(
                float(self._connection.stand_height), "up"
            )
        elif self._action == "sit":
            await self._connection.move_to_height(
                float(self._connection.sit_height), "down"
            )
