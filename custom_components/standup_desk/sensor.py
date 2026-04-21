"""Sensor platform for Stand Up Pls Desk."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import (
    RestoreSensor,
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfLength
from homeassistant.core import HomeAssistant, callback
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
    """Set up desk sensor entities from a config entry."""
    connection: StandUpDeskConnection = hass.data[DOMAIN][entry.entry_id]
    mac = entry.data["mac"]
    name = entry.data.get("device_name", "Stand Up Desk")

    async_add_entities([
        StandUpDeskHeightSensor(connection, entry.entry_id, mac, name),
        StandUpDeskMovingSensor(connection, entry.entry_id, mac, name),
    ])


class StandUpDeskHeightSensor(RestoreSensor):
    """Current desk height in cm."""

    _attr_device_class = SensorDeviceClass.DISTANCE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfLength.CENTIMETERS
    _attr_has_entity_name = True
    _attr_icon = "mdi:tape-measure"

    def __init__(
        self,
        connection: StandUpDeskConnection,
        entry_id: str,
        mac: str,
        device_name: str,
    ) -> None:
        self._connection = connection
        self._attr_unique_id = f"{entry_id}_height"
        self._attr_name = "Height"
        self._attr_native_value = connection.current_status.get("height_cm")
        self._attr_extra_state_attributes = {
            "height_raw": connection.current_status.get("height_raw"),
            "direction": connection.current_status.get("direction"),
        }
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, mac)},
            name=device_name,
            manufacturer=MANUFACTURER,
            model=MODEL,
        )
        self._connection.register_callback(self._handle_status_update)

    async def async_added_to_hass(self) -> None:
        """Restore last known height if no fresh status is available yet."""
        await super().async_added_to_hass()

        if self._attr_native_value is not None:
            return

        last_state = await self.async_get_last_state()
        if last_state is None or last_state.state in (
            "unknown",
            "unavailable",
        ):
            return

        try:
            self._attr_native_value = float(last_state.state)
        except (ValueError, TypeError):
            _LOGGER.debug(
                "Cannot restore previous height state: %s",
                last_state.state,
            )

    async def async_will_remove_from_hass(self) -> None:
        self._connection.unregister_callback(self._handle_status_update)

    @callback
    async def _handle_status_update(self, status: dict[str, Any]) -> None:
        self._attr_native_value = status.get("height_cm")
        self._attr_extra_state_attributes = {
            "height_raw": status.get("height_raw"),
            "direction": status.get("direction"),
        }
        self.async_write_ha_state()


class StandUpDeskMovingSensor(SensorEntity):
    """Desk movement state sensor."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:motion-sensor"

    def __init__(
        self,
        connection: StandUpDeskConnection,
        entry_id: str,
        mac: str,
        device_name: str,
    ) -> None:
        self._connection = connection
        self._attr_unique_id = f"{entry_id}_moving"
        self._attr_name = "Movement"
        status = connection.current_status
        if status.get("is_moving"):
            self._attr_native_value = status.get("direction", "idle")
        else:
            self._attr_native_value = "idle"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, mac)},
            name=device_name,
            manufacturer=MANUFACTURER,
            model=MODEL,
        )
        self._connection.register_callback(self._handle_status_update)

    async def async_will_remove_from_hass(self) -> None:
        self._connection.unregister_callback(self._handle_status_update)

    @callback
    async def _handle_status_update(self, status: dict[str, Any]) -> None:
        is_moving = status.get("is_moving", False)
        direction = status.get("direction", "idle")
        if is_moving and direction == "up":
            self._attr_native_value = "up"
            self._attr_icon = "mdi:arrow-up-bold"
        elif is_moving and direction == "down":
            self._attr_native_value = "down"
            self._attr_icon = "mdi:arrow-down-bold"
        else:
            self._attr_native_value = "idle"
            self._attr_icon = "mdi:motion-sensor-off"
        self.async_write_ha_state()
