"""Stand Up Pls Desk integration for Home Assistant.

Controls TiMotion TWD1 Bluetooth sit-stand desks via BLE (Nordic UART Service).
Protocol reverse-engineered from the "Stand Up Pls" iOS/Android app.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from bleak import BleakClient
from bleak.exc import BleakError
from bleak_retry_connector import (
    BleakClientWithServiceCache,
    establish_connection,
)
from homeassistant.components.bluetooth import async_ble_device_from_address
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import device_registry as dr
import voluptuous as vol

from .const import (
    CONF_SIT_HEIGHT,
    CONF_STAND_HEIGHT,
    DEFAULT_SIT_HEIGHT,
    DEFAULT_STAND_HEIGHT,
    DOMAIN,
    DOWN_COMMAND,
    MANUFACTURER,
    MAX_MOVEMENT_STEPS,
    MAX_STALL_STEPS,
    MODEL,
    MOVEMENT_INTERVAL,
    RX_CHAR_UUID,
    STOP_COMMAND,
    TOLERANCE_CM,
    TX_CHAR_UUID,
    UP_COMMAND,
)

_LOGGER = logging.getLogger(__name__)

BLE_EXCEPTIONS = (BleakError, asyncio.TimeoutError, OSError)

PLATFORMS = [Platform.SENSOR, Platform.NUMBER, Platform.BUTTON]


def decode_desk_status(data: bytes) -> dict[str, Any] | None:
    """Decode a 5-byte status packet from the desk.

    Format: [0x99, direction, height_hi, height_lo, checksum]
    """
    if len(data) < 5:
        return None

    direction_byte = data[1]
    raw_height = (data[2] << 8) | data[3]
    height_cm = round(raw_height - 256, 1)

    expected_cs = (0x99 + data[1] + data[2] + data[3]) & 0xFF
    if data[4] != expected_cs:
        _LOGGER.debug(
            "Checksum mismatch: expected 0x%02X, got 0x%02X (data: %s)",
            expected_cs, data[4], data.hex(),
        )

    if direction_byte == 0x42:
        direction = "up"
        is_moving = True
    elif direction_byte == 0x41:
        direction = "down"
        is_moving = True
    else:
        direction = "idle"
        is_moving = False

    return {
        "height_cm": height_cm,
        "height_raw": raw_height,
        "is_moving": is_moving,
        "direction": direction,
    }


class StandUpDeskConnection:
    """Manages BLE connection to a TiMotion TWD1 desk."""

    def __init__(self, mac_address: str, hass: HomeAssistant) -> None:
        self.mac_address = mac_address
        self.hass = hass
        self.client: BleakClient | None = None
        self.is_connected = False
        self.current_status: dict[str, Any] = {}
        self.sit_height: int = DEFAULT_SIT_HEIGHT
        self.stand_height: int = DEFAULT_STAND_HEIGHT
        self._callbacks: list = []
        self._stop_requested = False
        self._move_lock = asyncio.Lock()
        self._notification_count: int = 0

    async def connect(self) -> bool:
        """Open the BLE connection and subscribe to desk updates."""
        try:
            _LOGGER.info("Connecting to desk: %s", self.mac_address)
            ble_device = async_ble_device_from_address(
                self.hass,
                self.mac_address,
                connectable=True,
            )
            if ble_device is None:
                _LOGGER.error("BLE device not found: %s", self.mac_address)
                self.is_connected = False
                return False

            self.client = await establish_connection(
                BleakClientWithServiceCache,
                ble_device,
                self.mac_address,
                self._on_disconnected,
            )
            await self.client.start_notify(
                TX_CHAR_UUID,
                self._notification_handler,
            )

            # Ask desk for a fresh status packet right after subscribing.
            try:
                await self.request_status()
            except BLE_EXCEPTIONS as error:
                _LOGGER.debug("Initial status request failed: %s", error)

            self.is_connected = True
            _LOGGER.info("Connected to desk")
            return True
        except BLE_EXCEPTIONS as error:
            _LOGGER.error("Connection error: %s", error)
            self.is_connected = False
            return False

    async def disconnect(self) -> None:
        """Close the BLE connection and stop desk notifications."""
        if self.client and self.is_connected:
            try:
                await self.client.stop_notify(TX_CHAR_UUID)
                await self.client.disconnect()
            except BLE_EXCEPTIONS as error:
                _LOGGER.debug("Disconnect error: %s", error)
            finally:
                self.is_connected = False

    async def ensure_connected(self) -> bool:
        """Return whether the desk is connected, reconnecting if needed."""
        if self.is_connected:
            return True
        return await self.connect()

    def _on_disconnected(self, _client: BleakClient) -> None:
        """Handle an unexpected BLE disconnect callback."""
        _LOGGER.warning("BLE disconnected: %s", self.mac_address)
        self.is_connected = False

    def _notification_handler(
        self,
        _characteristic: Any,
        data: bytearray,
    ) -> None:
        """Process incoming BLE notifications from the desk."""
        status = decode_desk_status(data)
        if status:
            self._notification_count += 1
            self.current_status = status
            for callback in self._callbacks:
                self.hass.async_create_task(callback(status))

    def register_callback(self, callback) -> None:
        """Register a coroutine callback for status updates."""
        self._callbacks.append(callback)

    def unregister_callback(self, callback) -> None:
        """Remove a previously registered status callback."""
        if callback in self._callbacks:
            self._callbacks.remove(callback)

    async def request_status(self) -> None:
        """Request a fresh status packet from desk.

        The desk typically responds to a STOP frame with a notification
        containing current height/direction, which lets sensors avoid an
        initial 'unknown'.
        """
        if not self.client:
            return
        await self.client.write_gatt_char(
            RX_CHAR_UUID,
            STOP_COMMAND,
            response=False,
        )

    async def move_to_height(self, target_cm: float, direction: str) -> None:
        """Move desk to target height. Direction must be 'up' or 'down'."""
        async with self._move_lock:
            if direction not in {"up", "down"}:
                _LOGGER.error("Cannot move: invalid direction %s", direction)
                return

            if not await self.ensure_connected() or not self.client:
                _LOGGER.error("Cannot move: not connected")
                return

            current_cm = self.current_status.get("height_cm", 0)
            if direction == "up" and current_cm >= target_cm - TOLERANCE_CM:
                _LOGGER.info(
                    "Desk already at or above target: %.0f cm",
                    current_cm,
                )
                return
            if direction == "down" and current_cm <= target_cm + TOLERANCE_CM:
                _LOGGER.info(
                    "Desk already at or below target: %.0f cm",
                    current_cm,
                )
                return

            cmd = UP_COMMAND if direction == "up" else DOWN_COMMAND

            # Init ping
            await self.client.write_gatt_char(
                RX_CHAR_UUID,
                STOP_COMMAND,
                response=False,
            )
            await asyncio.sleep(0.3)

            self._stop_requested = False
            start_cm = self.current_status.get("height_cm", 0)
            last_cm = start_cm
            stalled_steps = 0
            opposite_direction_steps = 0
            last_notif_count = self._notification_count
            # Height-progress checkpoint: abort if the desk hasn't moved
            # meaningfully towards the target in the last 3 s (15 steps).
            # This catches the tug-of-war where HA keeps re-issuing move
            # commands after a physical panel stop and the desk briefly
            # restarts, generating is_moving=True notifications that
            # prevent the notification-count stall counter from latching.
            height_checkpoint = start_cm
            height_check_step = 0
            _LOGGER.info(
                "Moving %s: %.0f cm -> %.0f cm",
                direction,
                start_cm,
                target_cm,
            )

            target_reached = False
            for _step in range(MAX_MOVEMENT_STEPS):
                if self._stop_requested:
                    _LOGGER.info(
                        "Stop requested at %.0f cm",
                        self.current_status.get("height_cm", 0),
                    )
                    break

                current_cm = self.current_status.get("height_cm", last_cm)
                current_direction = self.current_status.get(
                    "direction",
                    "idle",
                )
                is_moving = self.current_status.get("is_moving", False)

                if (
                    is_moving
                    and current_direction in {"up", "down"}
                    and current_direction != direction
                ):
                    opposite_direction_steps += 1
                    if opposite_direction_steps >= 2:
                        _LOGGER.warning(
                            "Movement override detected: desk reports %s "
                            "while target direction is %s; stopping loop",
                            current_direction,
                            direction,
                        )
                        break
                else:
                    opposite_direction_steps = 0

                if (
                    direction == "up"
                    and current_cm >= target_cm - TOLERANCE_CM
                ):
                    target_reached = True
                    break
                if (
                    direction == "down"
                    and current_cm <= target_cm + TOLERANCE_CM
                ):
                    target_reached = True
                    break

                received_update = self._notification_count != last_notif_count
                last_notif_count = self._notification_count
                if (
                    received_update
                    and is_moving
                    and current_direction == direction
                ):
                    stalled_steps = 0
                else:
                    stalled_steps += 1
                    if stalled_steps >= MAX_STALL_STEPS:
                        _LOGGER.warning(
                            "Movement aborted after %d stalled updates at "
                            "%.0f cm (target: %.0f cm)",
                            stalled_steps,
                            current_cm,
                            target_cm,
                        )
                        break

                # Height-progress check (every 15 steps ≈ 3 s).
                height_check_step += 1
                if height_check_step >= 15:
                    progress = (
                        current_cm - height_checkpoint
                        if direction == "up"
                        else height_checkpoint - current_cm
                    )
                    if progress < 1.0:
                        _LOGGER.warning(
                            "Height stuck (%.1f cm progress towards target "
                            "in 3 s); aborting at %.0f cm (target: %.0f cm)",
                            progress,
                            current_cm,
                            target_cm,
                        )
                        break
                    height_checkpoint = current_cm
                    height_check_step = 0

                await self.client.write_gatt_char(
                    RX_CHAR_UUID,
                    cmd,
                    response=False,
                )
                await asyncio.sleep(MOVEMENT_INTERVAL)
                last_cm = current_cm

            # Send stop and refresh status so the desk panel is released again.
            await self.client.write_gatt_char(
                RX_CHAR_UUID,
                STOP_COMMAND,
                response=False,
            )
            await asyncio.sleep(0.1)
            final_cm = self.current_status.get("height_cm", last_cm)
            if target_reached:
                _LOGGER.info("Target reached at %.0f cm", final_cm)
            else:
                _LOGGER.warning(
                    "Movement stopped at %.0f cm (target: %.0f cm)",
                    final_cm,
                    target_cm,
                )

    async def stop(self) -> None:
        """Stop desk movement."""
        self._stop_requested = True
        if await self.ensure_connected() and self.client:
            await self.client.write_gatt_char(
                RX_CHAR_UUID,
                STOP_COMMAND,
                response=False,
            )
            _LOGGER.info("Stop command sent")


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Stand Up Pls Desk from a config entry."""
    mac_address = entry.data["mac"]
    device_name = entry.data.get("device_name", "stand UP- 3131")

    connection = StandUpDeskConnection(mac_address, hass)
    connection.sit_height = entry.options.get(
        CONF_SIT_HEIGHT,
        DEFAULT_SIT_HEIGHT,
    )
    connection.stand_height = entry.options.get(
        CONF_STAND_HEIGHT,
        DEFAULT_STAND_HEIGHT,
    )

    if not await connection.connect():
        _LOGGER.warning("Initial connection failed, will retry")

    device_registry = dr.async_get(hass)
    device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, mac_address)},
        manufacturer=MANUFACTURER,
        model=MODEL,
        name=device_name,
    )

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = connection

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))

    # Register services (once)
    if not hass.data[DOMAIN].get("_services_registered"):
        _register_services(hass)
        hass.data[DOMAIN]["_services_registered"] = True

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    connection: StandUpDeskConnection = hass.data[DOMAIN][entry.entry_id]
    await connection.disconnect()
    unload_ok = await hass.config_entries.async_unload_platforms(
        entry,
        PLATFORMS,
    )
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok


async def _async_options_updated(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> None:
    """Handle options update — sync heights to connection."""
    connection: StandUpDeskConnection = hass.data[DOMAIN].get(entry.entry_id)
    if connection:
        connection.sit_height = entry.options.get(
            CONF_SIT_HEIGHT,
            DEFAULT_SIT_HEIGHT,
        )
        connection.stand_height = entry.options.get(
            CONF_STAND_HEIGHT,
            DEFAULT_STAND_HEIGHT,
        )


def _get_connections(hass: HomeAssistant) -> list[StandUpDeskConnection]:
    """Get all active desk connections."""
    return [
        v for v in hass.data.get(DOMAIN, {}).values()
        if isinstance(v, StandUpDeskConnection)
    ]


def _register_services(hass: HomeAssistant) -> None:
    """Register standup_desk services."""

    async def handle_control(call: ServiceCall) -> None:
        action = call.data["action"]
        target_height = call.data.get("target_height")

        for conn in _get_connections(hass):
            if action == "stop":
                await conn.stop()
            elif action == "up":
                height = target_height or conn.stand_height
                await conn.move_to_height(float(height), "up")
            elif action == "down":
                height = target_height or conn.sit_height
                await conn.move_to_height(float(height), "down")

    async def handle_move_to(call: ServiceCall) -> None:
        height = call.data["height"]
        for conn in _get_connections(hass):
            current = conn.current_status.get("height_cm", 0)
            direction = "up" if height > current else "down"
            await conn.move_to_height(float(height), direction)

    hass.services.async_register(
        DOMAIN, "control",
        handle_control,
        schema=vol.Schema({
            vol.Required("action"): vol.In(["up", "down", "stop"]),
            vol.Optional("target_height"): vol.Coerce(float),
        }, extra=vol.ALLOW_EXTRA),
    )

    hass.services.async_register(
        DOMAIN, "move_to",
        handle_move_to,
        schema=vol.Schema({
            vol.Required("height"): vol.All(
                vol.Coerce(float),
                vol.Range(min=55, max=135),
            ),
        }, extra=vol.ALLOW_EXTRA),
    )
