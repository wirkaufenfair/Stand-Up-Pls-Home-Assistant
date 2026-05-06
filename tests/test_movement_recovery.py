"""Regression tests for desk movement recovery behavior."""

import asyncio
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
        self.stop_notify_calls = 0
        self.disconnect_calls = 0

    async def write_gatt_char(self, _uuid, command, response=False):
        """Record outgoing GATT write commands."""
        _ = response
        self.commands.append(command)

    async def stop_notify(self, _uuid):
        """Record that notification subscription was stopped."""
        self.stop_notify_calls += 1

    async def disconnect(self):
        """Record that BLE disconnect was requested."""
        self.disconnect_calls += 1


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
            self.conn._moving_notification_count += 1
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
            self.conn._idle_notification_count += 1
            self.conn.current_status = {
                "height_cm": 80 + self._up_count * 0.1,
                "is_moving": False,
                "direction": "idle",
            }


class FrozenHeightMovingClient(FakeClient):
    """Fake client that simulates a desk reporting is_moving=True but with
    height frozen — the tug-of-war scenario where HA re-issues UP commands
    after a physical stop and the desk briefly restarts each time, generating
    fresh is_moving=True notifications that reset the stall counter."""

    def __init__(self, conn):
        """Initialize client with attached connection."""
        super().__init__()
        self.conn = conn

    async def write_gatt_char(self, _uuid, command, response=False):
        """Record command and inject a moving-but-frozen status on UP."""
        await super().write_gatt_char(_uuid, command, response=response)
        if command == standup_desk.UP_COMMAND:
            # Desk appears to be moving in target direction but height never
            # actually advances — this keeps resetting the stall counter.
            self.conn._notification_count += 1
            self.conn._moving_notification_count += 1
            self.conn.current_status = {
                "height_cm": 80,  # frozen
                "is_moving": True,
                "direction": "up",
            }


class TugOfWarClient(FakeClient):
    """Simulates physical STOP mid-automation: each BLE UP command
    makes the desk briefly start (is_moving=True notification) and
    then the panel STOP overrides it (is_moving=False notification)
    — both within the same 0.2 s step.  The idle notification is
    recorded in _idle_notification_count even when current_status is
    overwritten by a later packet before the loop reads it."""

    def __init__(self, conn):
        """Initialize client with attached connection."""
        super().__init__()
        self.conn = conn
        self._up_count = 0

    async def write_gatt_char(self, _uuid, command, response=False):
        """Inject a moving-then-idle notification pair per UP command."""
        await super().write_gatt_char(_uuid, command, response=response)
        if command == standup_desk.UP_COMMAND:
            self._up_count += 1
            height = 80.0 + self._up_count * 0.1
            # Desk starts in response to the BLE UP command.
            self.conn._notification_count += 1
            self.conn._moving_notification_count += 1
            self.conn.current_status = {
                "height_cm": height,
                "is_moving": True,
                "direction": "up",
            }
            # Physical STOP overrides the motor immediately after.
            # This notification may be overwritten in current_status
            # before the loop reads it, but _idle_notification_count
            # preserves the signal for the idle-interruption check.
            self.conn._notification_count += 1
            self.conn._idle_notification_count += 1
            self.conn.current_status = {
                "height_cm": height,
                "is_moving": False,
                "direction": "idle",
            }


class TugOfWarNoIdleClient(FakeClient):
    """Simulates the most common real-world physical-STOP scenario.

    Each HA UP command makes the desk start briefly (is_moving=True
    notification, height advances 0.1 cm) then the physical STOP kills
    the motor BEFORE the desk sends an is_moving=False notification.
    The desk simply goes silent.  This means:
      * _notification_count increments (is_moving=True arrived)
      * _idle_notification_count does NOT increment (no idle sent)
      * height advances only 0.1 cm per step
    Neither the idle-notification counter (v1.0.7) nor the height-
    progress window (v1.0.6) reliably detected this.  The stall counter
    fix in v1.0.8 — requiring ≥ 0.2 cm height advancement per step —
    catches it within MAX_STALL_STEPS iterations.
    """

    def __init__(self, conn):
        """Initialize client with attached connection."""
        super().__init__()
        self.conn = conn
        self._up_count = 0

    async def write_gatt_char(self, _uuid, command, response=False):
        """Inject a moving-but-barely-advancing status on each UP."""
        await super().write_gatt_char(_uuid, command, response=response)
        if command == standup_desk.UP_COMMAND:
            self._up_count += 1
            # Desk starts briefly, advances 0.1 cm, then physical STOP
            # silences the motor — no is_moving=False notification follows.
            self.conn._notification_count += 1
            self.conn._moving_notification_count += 1
            self.conn.current_status = {
                "height_cm": 80.0 + self._up_count * 0.1,
                "is_moving": True,
                "direction": "up",
            }


class PresetButtonInterruptClient(FakeClient):
    """Simulates pressing a preset button (e.g. '1') while HA is moving up.

    The desk executes 3 normal UP steps, then the panel preset triggers.
    TiMotion firmware sends the idle and the following moving-DOWN packet
    close enough together that both arrive within the same 0.2 s step:
    - idle notification (desk stops current motion)
    - moving/down notification (preset move starts)

    This causes the opposite-direction guard to fire on the *next* loop
    iteration, before the idle-abort check can trigger.  HA must NOT send
    a STOP command, because the desk is already executing the preset move.
    A spurious BLE STOP would cancel the preset mid-way and leave the
    TiMotion firmware confused, making the panel unresponsive.
    """

    def __init__(self, conn):
        """Initialize client with attached connection."""
        super().__init__()
        self.conn = conn
        self._up_count = 0

    async def write_gatt_char(self, _uuid, command, response=False):
        """Record command; simulate panel preset after 3 normal UP steps."""
        await super().write_gatt_char(_uuid, command, response=response)
        if command == standup_desk.UP_COMMAND:
            self._up_count += 1
            if self._up_count <= 3:
                # Normal desk movement upward.
                self.conn._notification_count += 1
                self.conn._moving_notification_count += 1
                self.conn.current_status = {
                    "height_cm": 80.0 + self._up_count * 2.5,
                    "is_moving": True,
                    "direction": "up",
                }
            else:
                # Panel preset: desk goes idle then immediately starts DOWN.
                # Both packets arrive within the same 0.2 s MOVEMENT_INTERVAL
                # so the loop reads the final current_status (moving/down)
                # on the next iteration and hits the opposite-direction guard
                # before the idle-abort threshold can fire.
                self.conn._notification_count += 1
                self.conn._idle_notification_count += 1
                self.conn._notification_count += 1
                self.conn._moving_notification_count += 1
                self.conn.current_status = {
                    "height_cm": 87.5 - (self._up_count - 4) * 2.5,
                    "is_moving": True,
                    "direction": "down",
                }


class PanelButtonStopClient(FakeClient):
    """Simulates pressing a panel button that simply stops desk movement.

    The desk executes 3 normal UP steps, then the panel button press
    causes it to go idle and stay idle (no preset move follows).

    Regression: idle-abort must never send a final STOP (to avoid preset
    cancellation), but it should release BLE promptly so panel control is
    restored immediately.
    """

    def __init__(self, conn):
        """Initialize client with attached connection."""
        super().__init__()
        self.conn = conn
        self._up_count = 0

    async def write_gatt_char(self, _uuid, command, response=False):
        """Record command; simulate clean stop after 3 normal UP steps."""
        await super().write_gatt_char(_uuid, command, response=response)
        if command == standup_desk.UP_COMMAND:
            self._up_count += 1
            if self._up_count <= 3:
                # Normal desk movement upward.
                self.conn._notification_count += 1
                self.conn._moving_notification_count += 1
                self.conn.current_status = {
                    "height_cm": 80.0 + self._up_count * 2.5,
                    "is_moving": True,
                    "direction": "up",
                }
            else:
                # Panel button pressed: desk goes idle and stays idle.
                self.conn._notification_count += 1
                self.conn._idle_notification_count += 1
                self.conn.current_status = {
                    "height_cm": 87.5,
                    "is_moving": False,
                    "direction": "idle",
                }


class FakeHass:
    """Minimal Home Assistant stub for async task scheduling."""

    def async_create_task(self, coro):
        """Return the coroutine without scheduling for test simplicity."""
        return coro


class IdleThenPresetTransitionClient(FakeClient):
    """Simulates idle-abort followed by delayed panel preset transition.

    Sequence after a few normal UP steps:
      1) desk emits idle (idle-abort condition)
      2) shortly after, desk starts moving down from panel preset

    HA must not send a final STOP in this transition window.
    """

    def __init__(self, conn):
        """Initialize client with attached connection."""
        super().__init__()
        self.conn = conn
        self._up_count = 0
        self._transition_scheduled = False

    async def write_gatt_char(self, _uuid, command, response=False):
        """Record command; schedule delayed preset motion after idle."""
        await super().write_gatt_char(_uuid, command, response=response)
        if command == standup_desk.UP_COMMAND:
            self._up_count += 1
            if self._up_count <= 3:
                self.conn._notification_count += 1
                self.conn._moving_notification_count += 1
                self.conn.current_status = {
                    "height_cm": 80.0 + self._up_count * 2.5,
                    "is_moving": True,
                    "direction": "up",
                }
            elif not self._transition_scheduled:
                self._transition_scheduled = True
                self.conn._notification_count += 1
                self.conn._idle_notification_count += 1
                self.conn.current_status = {
                    "height_cm": 87.5,
                    "is_moving": False,
                    "direction": "idle",
                }

                async def _delayed_panel_preset_start() -> None:
                    await asyncio.sleep(0.3)
                    self.conn._notification_count += 1
                    self.conn._moving_notification_count += 1
                    self.conn.current_status = {
                        "height_cm": 87.0,
                        "is_moving": True,
                        "direction": "down",
                    }

                asyncio.create_task(_delayed_panel_preset_start())


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
        """Ensure movement stops after the startup grace + stall budget.

        A completely silent desk (no BLE notifications at all) is suppressed
        from stall counting for STARTUP_GRACE_STEPS iterations to give the
        motor time to spin up.  Once grace expires, MAX_STALL_STEPS more
        silent steps trigger the abort, keeping the total well under the
        30-second MAX_MOVEMENT_STEPS ceiling.
        """
        setattr(standup_desk, "MOVEMENT_INTERVAL", 0)
        setattr(standup_desk, "MAX_MOVEMENT_STEPS", 50)

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
            standup_desk.STARTUP_GRACE_STEPS + standup_desk.MAX_STALL_STEPS,
            (
                "Movement should stop within the startup grace window plus "
                "the stall budget when the desk never sends any BLE "
                "notifications (stuck or error state)."
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

    async def test_move_aborts_when_height_frozen_despite_moving_notifications(
        self,
    ):
        """Ensure abort when is_moving=True arrives but height never advances.

        Simulates the tug-of-war: physical panel stop followed by HA
        re-commanding the desk.  The desk briefly restarts each time
        (is_moving=True notification, _notification_count increments) but the
        height stays frozen, so the stall counter is perpetually reset by
        v1.0.5 logic.  The height-progress guard introduced in v1.0.6 must
        abort the loop within ~15 steps.
        """
        setattr(standup_desk, "MOVEMENT_INTERVAL", 0)
        setattr(standup_desk, "MAX_MOVEMENT_STEPS", 50)

        conn = StandUpDeskConnection("AA:BB", cast(Any, FakeHass()))
        fake_client = FrozenHeightMovingClient(conn)
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
            16,  # height-progress check fires after 15 steps
            (
                "Movement must abort within ~15 commands when is_moving=True "
                "notifications keep arriving but height is completely frozen "
                "(physical stop + HA tug-of-war scenario)."
            ),
        )

    async def test_move_aborts_when_physical_stop_causes_idle_notifications(
        self,
    ):
        """Ensure panel STOP is detected via idle BLE notification count.

        Simulates the realistic tug-of-war: each HA UP command makes the
        desk briefly start (is_moving=True notification), then the physical
        STOP kicks in (is_moving=False notification) within the same 0.2 s
        step.  The idle notification can be overwritten in current_status
        before the loop reads it, so the height-progress check from v1.0.6
        would not catch this when the desk makes any forward progress.
        The idle-notification counter introduced in v1.0.7 must abort the
        loop after 1 idle event (threshold lowered from 2 to 1 in v1.0.16
        to prevent the extra UP command that was confusing the firmware).
        """
        setattr(standup_desk, "MOVEMENT_INTERVAL", 0)
        setattr(standup_desk, "MAX_MOVEMENT_STEPS", 50)

        conn = StandUpDeskConnection("AA:BB", cast(Any, FakeHass()))
        fake_client = TugOfWarClient(conn)
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
                "Movement must abort within 2 UP commands when the physical "
                "panel STOP repeatedly interrupts HA UP commands — the "
                "threshold-1 idle check fires after the first idle event so "
                "HA does not send any more UP commands that could interfere "
                "with a panel-preset move the desk may be transitioning to."
            ),
        )

    async def test_move_aborts_when_panel_stop_sends_no_idle_notification(
        self,
    ):
        """Ensure abort when physical STOP leaves desk barely advancing.

        Scenario: each HA UP command makes the desk start briefly
        (is_moving=True notification, 0.1 cm height advance), but the
        physical STOP kills the
        motor before an is_moving=False (idle) notification is sent.

        Detection path (v1.0.10): the stall counter is only active when the
        desk is *completely* silent (no BLE packets at all), so it does not
        fire here.  Instead the height-progress window catches the pattern:
        0.1 cm/step × 15 steps = 1.5 cm which is below HEIGHT_PROGRESS_MIN_CM
        (2.0 cm), so abort happens within ~15 UP commands (~3 s).
        """
        setattr(standup_desk, "MOVEMENT_INTERVAL", 0)
        setattr(standup_desk, "MAX_MOVEMENT_STEPS", 50)

        conn = StandUpDeskConnection("AA:BB", cast(Any, FakeHass()))
        fake_client = TugOfWarNoIdleClient(conn)
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
            16,  # height-progress check fires after at most 15 active steps
            (
                "Movement must abort within ~15 UP commands when the physical "
                "panel STOP repeatedly silences the desk motor with no "
                "is_moving=False notification, leaving the desk barely "
                "advancing (0.1 cm per HA step) — caught by the "
                "HEIGHT_PROGRESS_MIN_CM window (2.0 cm / 3 s)."
            ),
        )

    async def test_panel_preset_interrupt_sends_no_stop(self):
        """No STOP command after preset-button abort (opposite-direction path).

        Regression: pressing a physical preset button (e.g. '1') while HA
        moves up causes the desk to start a panel-controlled DOWN move.
        HA must abort quickly (opposite-direction guard) and must NOT issue
        a final BLE STOP, because that STOP would cancel the panel's preset
        move mid-way and leave the TiMotion firmware confused with a locked
        panel.
        """
        setattr(standup_desk, "MOVEMENT_INTERVAL", 0)
        setattr(standup_desk, "MAX_MOVEMENT_STEPS", 20)

        conn = StandUpDeskConnection("AA:BB", cast(Any, FakeHass()))
        fake_client = PresetButtonInterruptClient(conn)
        conn.client = cast(Any, fake_client)
        conn.is_connected = True
        conn.current_status = {
            "height_cm": 80,
            "is_moving": False,
            "direction": "idle",
        }

        await conn.move_to_height(120, "up")

        stop_commands_after_first = [
            cmd
            for cmd in fake_client.commands[1:]  # skip the init-ping STOP
            if cmd == standup_desk.STOP_COMMAND
        ]
        self.assertEqual(
            len(stop_commands_after_first),
            0,
            "No STOP command must be sent after a panel preset-button abort: "
            "the desk is executing the panel's preset move and a spurious "
            "BLE STOP would cancel it, leaving the panel unresponsive.",
        )

        move_commands = [
            cmd
            for cmd in fake_client.commands
            if cmd == standup_desk.UP_COMMAND
        ]
        self.assertLessEqual(
            len(move_commands),
            6,
            "Movement loop must abort within a few steps when the desk "
            "reports opposite direction after a panel preset press.",
        )
        self.assertGreaterEqual(
            fake_client.disconnect_calls,
            1,
            "BLE connection must be released after opposite-direction "
            "panel interrupt so the panel can take over reliably.",
        )

    async def test_panel_button_stop_no_final_stop_for_safety(
        self,
    ):
        """Idle-abort must skip STOP and disconnect without stop_notify.

        Regression: when a panel button stops movement (idle), we cannot
        reliably distinguish between a simple stop vs. a preset that is about
        to start. To avoid cancelling a delayed preset, idle-abort never sends
        final STOP. At the same time, keeping BLE connected for too long can
        leave panel control blocked; we must release BLE promptly.

        Critical detail: release must be a direct disconnect without a prior
        stop_notify call, because stop_notify during panel transitions can
        lock TiMotion firmware.
        """
        setattr(standup_desk, "MOVEMENT_INTERVAL", 0)
        setattr(standup_desk, "MAX_MOVEMENT_STEPS", 20)

        conn = StandUpDeskConnection("AA:BB", cast(Any, FakeHass()))
        fake_client = PanelButtonStopClient(conn)
        conn.client = cast(Any, fake_client)
        conn.is_connected = True
        conn.current_status = {
            "height_cm": 80,
            "is_moving": False,
            "direction": "idle",
        }

        await conn.move_to_height(120, "up")

        # The init-ping STOP is expected before movement starts. After
        # idle-abort, no additional STOP must be sent (to avoid preset
        # cancellation risk).
        first_up_idx = next(
            i
            for i, cmd in enumerate(fake_client.commands)
            if cmd == standup_desk.UP_COMMAND
        )
        stop_commands_after_movement = [
            cmd
            for cmd in fake_client.commands[first_up_idx:]
            if cmd == standup_desk.STOP_COMMAND
        ]
        self.assertEqual(
            len(stop_commands_after_movement),
            0,
            "No final STOP must be sent after idle-abort to avoid "
            "cancelling potential panel presets.",
        )
        self.assertGreaterEqual(
            fake_client.disconnect_calls,
            1,
            "BLE should be disconnected on idle-abort so panel control can "
            "recover immediately.",
        )
        self.assertEqual(
            fake_client.stop_notify_calls,
            0,
            "Idle-abort release must not call stop_notify because that can "
            "lock TiMotion firmware during panel transitions.",
        )

    async def test_idle_abort_with_delayed_preset_transition_sends_no_stop(
        self,
    ):
        """No STOP and disconnect-without-stop_notify after idle-abort.

        stop_notify during an active panel preset transition can lock the
        TiMotion firmware. We therefore allow BLE release only via direct
        disconnect.
        """
        setattr(standup_desk, "MOVEMENT_INTERVAL", 0)
        setattr(standup_desk, "MAX_MOVEMENT_STEPS", 20)

        conn = StandUpDeskConnection("AA:BB", cast(Any, FakeHass()))
        fake_client = IdleThenPresetTransitionClient(conn)
        conn.client = cast(Any, fake_client)
        conn.is_connected = True
        conn.current_status = {
            "height_cm": 80,
            "is_moving": False,
            "direction": "idle",
        }

        await conn.move_to_height(120, "up")

        first_up_idx = next(
            i
            for i, cmd in enumerate(fake_client.commands)
            if cmd == standup_desk.UP_COMMAND
        )
        stop_commands_after_movement = [
            cmd
            for cmd in fake_client.commands[first_up_idx:]
            if cmd == standup_desk.STOP_COMMAND
        ]
        self.assertEqual(
            len(stop_commands_after_movement),
            0,
            "No final STOP must be sent when idle-abort transitions into "
            "panel-controlled preset motion.",
        )
        self.assertGreaterEqual(
            fake_client.disconnect_calls,
            1,
            "Idle-abort should release BLE control via direct disconnect.",
        )
        self.assertEqual(
            fake_client.stop_notify_calls,
            0,
            "Idle-abort release must not call stop_notify because that can "
            "lock TiMotion firmware during panel transitions.",
        )


if __name__ == "__main__":
    unittest.main()
