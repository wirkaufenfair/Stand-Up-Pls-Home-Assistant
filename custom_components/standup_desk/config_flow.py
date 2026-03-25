"""Config flow for Stand Up Pls Desk integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
from homeassistant.data_entry_flow import FlowResult

from .const import (
    CONF_SIT_HEIGHT,
    CONF_STAND_HEIGHT,
    DEFAULT_SIT_HEIGHT,
    DEFAULT_STAND_HEIGHT,
    DOMAIN,
    HEIGHT_MAX,
    HEIGHT_MIN,
)

_LOGGER = logging.getLogger(__name__)


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Stand Up Pls Desk."""

    VERSION = 1

    def __init__(self) -> None:
        self._discovery_info: BluetoothServiceInfoBleak | None = None

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> FlowResult:
        """Handle Bluetooth discovery."""
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()
        self._discovery_info = discovery_info
        return await self.async_step_bluetooth_confirm()

    async def async_step_bluetooth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Confirm Bluetooth discovery."""
        if user_input is not None:
            return self.async_create_entry(
                title=self._discovery_info.name or "Stand Up Desk",
                data={
                    "mac": self._discovery_info.address,
                    "device_name": self._discovery_info.name or "stand UP- 3131",
                },
            )

        self._set_confirm_only()
        return self.async_show_form(
            step_id="bluetooth_confirm",
            description_placeholders={"name": self._discovery_info.name},
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle manual setup."""
        errors: dict[str, str] = {}

        if user_input is not None:
            device_name = user_input.get("device_name", "stand UP- 3131")

            # Search for the device via HA Bluetooth
            from homeassistant.components.bluetooth import async_discovered_service_info

            for info in async_discovered_service_info(self.hass, connectable=True):
                if info.name and device_name.lower() in info.name.lower():
                    await self.async_set_unique_id(info.address)
                    self._abort_if_unique_id_configured()
                    return self.async_create_entry(
                        title=info.name,
                        data={
                            "mac": info.address,
                            "device_name": info.name,
                        },
                    )

            errors["base"] = "not_found"

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Optional("device_name", default="stand UP-"): str,
            }),
            errors=errors,
        )

    @staticmethod
    def async_get_options_flow(config_entry: config_entries.ConfigEntry):
        return OptionsFlow(config_entry)


class OptionsFlow(config_entries.OptionsFlow):
    """Handle options for Stand Up Pls Desk."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Optional(
                    CONF_SIT_HEIGHT,
                    default=self._entry.options.get(CONF_SIT_HEIGHT, DEFAULT_SIT_HEIGHT),
                ): vol.All(int, vol.Range(min=HEIGHT_MIN, max=HEIGHT_MAX)),
                vol.Optional(
                    CONF_STAND_HEIGHT,
                    default=self._entry.options.get(CONF_STAND_HEIGHT, DEFAULT_STAND_HEIGHT),
                ): vol.All(int, vol.Range(min=HEIGHT_MIN, max=HEIGHT_MAX)),
            }),
        )
