"""Number platform for Stand Up Pls Desk — configurable sit/stand heights."""
from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_SIT_HEIGHT,
    CONF_STAND_HEIGHT,
    DEFAULT_SIT_HEIGHT,
    DEFAULT_STAND_HEIGHT,
    DOMAIN,
    HEIGHT_MAX,
    HEIGHT_MIN,
    MANUFACTURER,
    MODEL,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    mac = entry.data["mac"]
    name = entry.data.get("device_name", "Stand Up Desk")

    async_add_entities([
        StandUpDeskHeightNumber(
            entry, mac, name,
            key=CONF_SIT_HEIGHT,
            entity_name="Sit height",
            icon="mdi:seat-recline-normal",
            default=DEFAULT_SIT_HEIGHT,
        ),
        StandUpDeskHeightNumber(
            entry, mac, name,
            key=CONF_STAND_HEIGHT,
            entity_name="Stand height",
            icon="mdi:human-male-height",
            default=DEFAULT_STAND_HEIGHT,
        ),
    ])


class StandUpDeskHeightNumber(NumberEntity):
    """Number entity for a configurable desk height preset."""

    _attr_has_entity_name = True
    _attr_native_unit_of_measurement = "cm"
    _attr_native_min_value = HEIGHT_MIN
    _attr_native_max_value = HEIGHT_MAX
    _attr_native_step = 1
    _attr_mode = NumberMode.BOX

    def __init__(
        self,
        entry: ConfigEntry,
        mac: str,
        device_name: str,
        key: str,
        entity_name: str,
        icon: str,
        default: int,
    ) -> None:
        self._entry = entry
        self._key = key
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_name = entity_name
        self._attr_icon = icon
        self._attr_native_value = entry.options.get(key, default)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, mac)},
            name=device_name,
            manufacturer=MANUFACTURER,
            model=MODEL,
        )

    async def async_set_native_value(self, value: float) -> None:
        self._attr_native_value = int(value)
        # Persist to config entry options
        options = {**self._entry.options, self._key: int(value)}
        self.hass.config_entries.async_update_entry(self._entry, options=options)
        self.async_write_ha_state()
