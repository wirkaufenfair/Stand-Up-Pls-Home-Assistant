"""Regression tests for desk movement recovery behavior."""

import enum
import importlib
import sys
import types
import unittest
from pathlib import Path
from typing import Any, cast


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


# Minimal stubs so the integration can be imported without Home Assistant.
bleak = types.ModuleType("bleak")
bleak_exc = types.ModuleType("bleak.exc")


class BleakError(Exception):  # pragma: no cover - import stub
    """Stub Bleak exception used by the integration import."""


class BleakClient:  # pragma: no cover - import stub
    """Stub Bleak client used by the integration import."""


setattr(bleak, "BleakClient", BleakClient)
setattr(bleak_exc, "BleakError", BleakError)
sys.modules.setdefault("bleak", bleak)
sys.modules.setdefault("bleak.exc", bleak_exc)

bleak_retry = types.ModuleType("bleak_retry_connector")


async def establish_connection(
    *_args,
    **_kwargs,
):  # pragma: no cover - import stub
    """Stub BLE connection helper returning no client."""
    return None


class BleakClientWithServiceCache:  # pragma: no cover - import stub
    """Stub cached Bleak client class for connection setup."""


setattr(bleak_retry, "establish_connection", establish_connection)
setattr(
    bleak_retry,
    "BleakClientWithServiceCache",
    BleakClientWithServiceCache,
)
sys.modules.setdefault("bleak_retry_connector", bleak_retry)

homeassistant = types.ModuleType("homeassistant")
sys.modules.setdefault("homeassistant", homeassistant)

components = types.ModuleType("homeassistant.components")
sys.modules.setdefault("homeassistant.components", components)
bluetooth = types.ModuleType("homeassistant.components.bluetooth")


def _async_ble_device_from_address(*_args, **_kwargs):
    """Stub Bluetooth discovery helper returning no device."""
    return None


setattr(
    bluetooth,
    "async_ble_device_from_address",
    _async_ble_device_from_address,
)
sys.modules.setdefault("homeassistant.components.bluetooth", bluetooth)

config_entries = types.ModuleType("homeassistant.config_entries")


class ConfigEntry:  # pragma: no cover - import stub
    """Stub Home Assistant config entry type."""


setattr(config_entries, "ConfigEntry", ConfigEntry)
sys.modules.setdefault("homeassistant.config_entries", config_entries)

const = types.ModuleType("homeassistant.const")


class Platform(enum.Enum):
    """Stub Home Assistant platform enum."""

    SENSOR = "sensor"
    NUMBER = "number"
    BUTTON = "button"


setattr(const, "Platform", Platform)
sys.modules.setdefault("homeassistant.const", const)

core = types.ModuleType("homeassistant.core")


class HomeAssistant:  # pragma: no cover - import stub
    """Stub Home Assistant core object."""

    def async_create_task(self, coro):
        """Return the coroutine without scheduling for test simplicity."""
        return coro


class ServiceCall(dict):
    """Stub service call payload type."""


setattr(core, "HomeAssistant", HomeAssistant)
setattr(core, "ServiceCall", ServiceCall)
sys.modules.setdefault("homeassistant.core", core)

helpers = types.ModuleType("homeassistant.helpers")
sys.modules.setdefault("homeassistant.helpers", helpers)
device_registry = types.ModuleType(
    "homeassistant.helpers.device_registry"
)
sys.modules.setdefault(
    "homeassistant.helpers.device_registry",
    device_registry,
)
setattr(helpers, "device_registry", device_registry)

vol = types.ModuleType("voluptuous")
setattr(vol, "Schema", lambda *args, **kwargs: None)
setattr(vol, "Required", lambda value: value)
setattr(vol, "Optional", lambda value: value)
setattr(vol, "In", lambda value: value)
setattr(vol, "Coerce", lambda value: value)
setattr(vol, "All", lambda *args, **kwargs: None)
setattr(vol, "Range", lambda *args, **kwargs: None)
setattr(vol, "ALLOW_EXTRA", object())
sys.modules.setdefault("voluptuous", vol)

standup_desk = importlib.import_module("custom_components.standup_desk")
StandUpDeskConnection = standup_desk.StandUpDeskConnection


class FakeClient:
    """Simple fake BLE client that records outgoing commands."""

    def __init__(self):
        """Initialize the fake client command log."""
        self.commands = []

    async def write_gatt_char(self, _uuid, command, response=False):
        """Record outgoing GATT write commands."""
        _ = response
        self.commands.append(command)


class OppositeDirectionClient(FakeClient):
    """Fake client that simulates opposite movement from panel override."""

    def __init__(self, conn):
        """Initialize client with attached connection."""
        super().__init__()
        self.conn = conn

    async def write_gatt_char(self, _uuid, command, response=False):
        """Record command and inject opposite movement status on UP."""
        await super().write_gatt_char(_uuid, command, response=response)
        if command == standup_desk.UP_COMMAND:
            self.conn._notification_count += 1
            self.conn.current_status = {
                "height_cm": 79,
                "is_moving": True,
                "direction": "down",
            }


class PanelStopClient(FakeClient):
    """Fake client simulating a physical STOP press: desk stays idle but
    drifts 0.1 cm per HA command, which previously reset the stall counter."""

    def __init__(self, conn):
        """Initialize client with attached connection."""
        super().__init__()
        self.conn = conn
        self._up_count = 0

    async def write_gatt_char(self, _uuid, command, response=False):
        """Record command and nudge height slightly while keeping desk idle."""
        await super().write_gatt_char(_uuid, command, response=response)
        if command == standup_desk.UP_COMMAND:
            self._up_count += 1
            self.conn._notification_count += 1
            self.conn.current_status = {
                "height_cm": 80 + self._up_count * 0.1,
                "is_moving": False,
                "direction": "idle",
            }


class FakeHass:
    """Minimal Home Assistant stub for async task scheduling."""

    def async_create_task(self, coro):
        """Return the coroutine without scheduling for test simplicity."""
        return coro


class MovementRecoveryTests(unittest.IsolatedAsyncioTestCase):
    """Regression tests for stalled desk movement handling."""

    def setUp(self):
        """Store mutable module constants before each test."""
        self._original_movement_interval = standup_desk.MOVEMENT_INTERVAL
        self._original_max_movement_steps = standup_desk.MAX_MOVEMENT_STEPS

    def tearDown(self):
        """Restore mutable module constants after each test."""
        setattr(
            standup_desk,
            "MOVEMENT_INTERVAL",
            self._original_movement_interval,
        )
        setattr(
            standup_desk,
            "MAX_MOVEMENT_STEPS",
            self._original_max_movement_steps,
        )

    async def test_move_aborts_early_when_height_never_changes(self):
        """Ensure movement stops quickly when the desk reports no progress."""
        setattr(standup_desk, "MOVEMENT_INTERVAL", 0)
        setattr(standup_desk, "MAX_MOVEMENT_STEPS", 20)

        conn = StandUpDeskConnection("AA:BB", cast(Any, FakeHass()))
        fake_client = FakeClient()
        conn.client = cast(Any, fake_client)
        conn.is_connected = True
        conn.current_status = {
            "height_cm": 80,
            "is_moving": False,
            "direction": "idle",
        }

        await conn.move_to_height(120, "up")

        move_commands = [
            cmd
            for cmd in fake_client.commands
            if cmd == standup_desk.UP_COMMAND
        ]
        self.assertLessEqual(
            len(move_commands),
            5,
            (
                "Movement should stop quickly when the desk is stuck "
                "or in an error state."
            ),
        )

    async def test_move_aborts_when_opposite_direction_is_reported(self):
        """Ensure panel override in opposite direction stops movement loop."""
        setattr(standup_desk, "MOVEMENT_INTERVAL", 0)
        setattr(standup_desk, "MAX_MOVEMENT_STEPS", 20)

        conn = StandUpDeskConnection("AA:BB", cast(Any, FakeHass()))
        fake_client = OppositeDirectionClient(conn)
        conn.client = cast(Any, fake_client)
        conn.is_connected = True
        conn.current_status = {
            "height_cm": 80,
            "is_moving": False,
            "direction": "idle",
        }

        await conn.move_to_height(120, "up")

        move_commands = [
            cmd
            for cmd in fake_client.commands
            if cmd == standup_desk.UP_COMMAND
        ]
        self.assertLessEqual(
            len(move_commands),
            2,
            (
                "Movement should stop quickly when opposite direction "
                "is detected from panel input."
            ),
        )

    async def test_move_aborts_when_panel_stop_causes_idle_with_tiny_drift(
        self,
    ):
        """Ensure panel STOP aborts loop even when height drifts 0.1 cm/step.

        Previously the stall counter reset on any height change, allowing the
        loop to run for the full 30-second window while holding _move_lock.
        """
        setattr(standup_desk, "MOVEMENT_INTERVAL", 0)
        setattr(standup_desk, "MAX_MOVEMENT_STEPS", 50)

        conn = StandUpDeskConnection("AA:BB", cast(Any, FakeHass()))
        fake_client = PanelStopClient(conn)
        conn.client = cast(Any, fake_client)
        conn.is_connected = True
        conn.current_status = {
            "height_cm": 80,
            "is_moving": False,
            "direction": "idle",
        }

        await conn.move_to_height(120, "up")

        move_commands = [
            cmd
            for cmd in fake_client.commands
            if cmd == standup_desk.UP_COMMAND
        ]
        self.assertLessEqual(
            len(move_commands),
            standup_desk.MAX_STALL_STEPS + 1,
            (
                "Movement must abort within MAX_STALL_STEPS commands when "
                "the desk stays idle after a physical panel stop, even if "
                "height drifts slightly with each HA command."
            ),
        )


if __name__ == "__main__":
    unittest.main()
