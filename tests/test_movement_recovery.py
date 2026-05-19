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


class TransientIdlePulseClient(FakeClient):
    """Simulates one long idle glitch during otherwise normal UP movement."""

    def __init__(self, conn):
        """Initialize client with attached connection."""
        super().__init__()
        self.conn = conn
        self._up_count = 0
        self._glitch_emitted = False

    async def write_gatt_char(self, _uuid, command, response=False):
        """Inject one idle packet and resume moving well after 500 ms."""
        await super().write_gatt_char(_uuid, command, response=response)
        if command != standup_desk.UP_COMMAND:
            return

        self._up_count += 1
        if self._up_count == 4 and not self._glitch_emitted:
            self._glitch_emitted = True
            self.conn._notification_count += 1
            self.conn._idle_notification_count += 1
            self.conn.current_status = {
                "height_cm": 90.0,
                "is_moving": False,
                "direction": "idle",
            }
            panel_idle_event = getattr(self.conn, "_panel_idle_event", None)
            if panel_idle_event is not None:
                panel_idle_event.set()

            async def _resume_up_motion() -> None:
                # Simulate an 800 ms glitch (longer than the 500 ms
                # confirmation window) to ensure a *single* idle pulse still
                # does not trigger abort.
                await asyncio.sleep(0.8)
                self.conn._notification_count += 1
                self.conn._moving_notification_count += 1
                self.conn.current_status = {
                    "height_cm": 92.5,
                    "is_moving": True,
                    "direction": "up",
                }

            asyncio.create_task(_resume_up_motion())
            return

        self.conn._notification_count += 1
        self.conn._moving_notification_count += 1
        self.conn.current_status = {
            "height_cm": 80.0 + self._up_count * 2.5,
            "is_moving": True,
            "direction": "up",
        }


class SingleConfirmedIdleEpisodeThenResumeClient(FakeClient):
    """Simulates one confirmed idle episode followed by normal UP movement.

    The desk emits two idle notifications (enough for one confirmed
    idle-episode) and then resumes moving up. Movement must continue and
    reach target; a single confirmed idle episode must not trigger abort.
    """

    def __init__(self, conn):
        """Initialize client with attached connection."""
        super().__init__()
        self.conn = conn
        self._up_count = 0
        self._episode_emitted = False

    async def write_gatt_char(self, _uuid, command, response=False):
        """Emit one two-idle episode, then resume normal up movement."""
        await super().write_gatt_char(_uuid, command, response=response)
        if command != standup_desk.UP_COMMAND:
            return

        self._up_count += 1

        if self._up_count <= 2:
            self.conn._notification_count += 1
            self.conn._moving_notification_count += 1
            self.conn.current_status = {
                "height_cm": 80.0 + self._up_count * 2.5,
                "is_moving": True,
                "direction": "up",
            }
            return

        if not self._episode_emitted:
            self._episode_emitted = True
            # First idle packet.
            self.conn._notification_count += 1
            self.conn._idle_notification_count += 1
            self.conn.current_status = {
                "height_cm": 85.0,
                "is_moving": False,
                "direction": "idle",
            }
            panel_idle_event = getattr(self.conn, "_panel_idle_event", None)
            if panel_idle_event is not None:
                panel_idle_event.set()

            async def _second_idle_then_resume() -> None:
                # Emit second idle shortly after the first so one confirmed
                # idle episode is formed, then resume UP movement.
                await asyncio.sleep(0.05)
                self.conn._notification_count += 1
                self.conn._idle_notification_count += 1
                self.conn.current_status = {
                    "height_cm": 85.0,
                    "is_moving": False,
                    "direction": "idle",
                }
                panel_idle_event2 = getattr(
                    self.conn,
                    "_panel_idle_event",
                    None,
                )
                if panel_idle_event2 is not None:
                    panel_idle_event2.set()

                await asyncio.sleep(0.1)
                self.conn._notification_count += 1
                self.conn._moving_notification_count += 1
                self.conn.current_status = {
                    "height_cm": 87.5,
                    "is_moving": True,
                    "direction": "up",
                }

            asyncio.create_task(_second_idle_then_resume())
            return

        self.conn._notification_count += 1
        self.conn._moving_notification_count += 1
        self.conn.current_status = {
            "height_cm": 87.5 + (self._up_count - 3) * 2.5,
            "is_moving": True,
            "direction": "up",
        }


class ConfirmedIdleStretchThenResumeClient(FakeClient):
    """Simulates one sustained idle stretch that later resumes upward.

    Regression: one continuous pause can emit several idle notifications.
    That must count as a single idle episode, not as multiple episodes that
    falsely trigger the panel-stop abort while the desk is merely pausing
    under load before resuming upward movement.
    """

    def __init__(self, conn):
        """Initialize client with attached connection."""
        super().__init__()
        self.conn = conn
        self._up_count = 0
        self._stretch_emitted = False

    async def write_gatt_char(self, _uuid, command, response=False):
        """Emit one long idle stretch with repeated idle notifications."""
        await super().write_gatt_char(_uuid, command, response=response)
        if command != standup_desk.UP_COMMAND:
            return

        self._up_count += 1

        if self._up_count <= 2:
            self.conn._notification_count += 1
            self.conn._moving_notification_count += 1
            self.conn.current_status = {
                "height_cm": 80.0 + self._up_count * 2.5,
                "is_moving": True,
                "direction": "up",
            }
            return

        if not self._stretch_emitted:
            self._stretch_emitted = True
            self.conn._notification_count += 1
            self.conn._idle_notification_count += 1
            self.conn.current_status = {
                "height_cm": 85.0,
                "is_moving": False,
                "direction": "idle",
            }
            panel_idle_event = getattr(self.conn, "_panel_idle_event", None)
            if panel_idle_event is not None:
                panel_idle_event.set()

            async def _emit_idle_stretch_then_resume() -> None:
                for _ in range(3):
                    await asyncio.sleep(0.1)
                    self.conn._notification_count += 1
                    self.conn._idle_notification_count += 1
                    self.conn.current_status = {
                        "height_cm": 85.0,
                        "is_moving": False,
                        "direction": "idle",
                    }
                    panel_idle_event2 = getattr(
                        self.conn,
                        "_panel_idle_event",
                        None,
                    )
                    if panel_idle_event2 is not None:
                        panel_idle_event2.set()

                # Resume only after the 500 ms idle-confirmation window has
                # already elapsed so this exercises the post-confirmation
                # resume grace rather than the transient-idle path.
                await asyncio.sleep(0.35)
                self.conn._notification_count += 1
                self.conn._moving_notification_count += 1
                self.conn.current_status = {
                    "height_cm": 87.5,
                    "is_moving": True,
                    "direction": "up",
                }

            asyncio.create_task(_emit_idle_stretch_then_resume())
            return

        self.conn._notification_count += 1
        self.conn._moving_notification_count += 1
        self.conn.current_status = {
            "height_cm": 87.5 + (self._up_count - 3) * 2.5,
            "is_moving": True,
            "direction": "up",
        }


class SlowUpStartupThenRecoverClient(FakeClient):
    """Simulates slow but real upward movement before normal speed resumes."""

    def __init__(self, conn):
        """Initialize client with attached connection."""
        super().__init__()
        self.conn = conn
        self._movement_started = False
        self._task = None

    async def write_gatt_char(self, _uuid, command, response=False):
        """Start background UP notifications on the first UP command."""
        await super().write_gatt_char(_uuid, command, response=response)
        if command != standup_desk.UP_COMMAND or self._movement_started:
            return

        self._movement_started = True

        async def _emit_progress() -> None:
            height = 78.0
            for _ in range(30):
                # First two 15-step windows: 1.0 cm progress each.
                height += 1.0 / 15.0
                self.conn._notification_count += 1
                self.conn._moving_notification_count += 1
                self.conn.current_status = {
                    "height_cm": round(height, 1),
                    "is_moving": True,
                    "direction": "up",
                }
                await asyncio.sleep(0.01)

            while height < 123.0:
                # Then resume normal upward speed.
                height += 0.8
                self.conn._notification_count += 1
                self.conn._moving_notification_count += 1
                self.conn.current_status = {
                    "height_cm": round(height, 1),
                    "is_moving": True,
                    "direction": "up",
                }
                await asyncio.sleep(0.01)

        self._task = asyncio.create_task(_emit_progress())


class SustainedSlowContinuousUpClient(FakeClient):
    """Simulates sustained slow but steady upward movement.

    The desk keeps sending frequent moving/up notifications while only
    advancing 1.0 cm per 3 s window (15 steps), i.e. below
    HEIGHT_PROGRESS_MIN_CM (2.0 cm). This is a real slow-load scenario and
    should not be treated as stuck.
    """

    def __init__(self, conn):
        """Initialize client with attached connection."""
        super().__init__()
        self.conn = conn
        self._movement_started = False
        self._task = None

    async def write_gatt_char(self, _uuid, command, response=False):
        """Start sustained slow UP notifications on the first UP command."""
        await super().write_gatt_char(_uuid, command, response=response)
        if command != standup_desk.UP_COMMAND or self._movement_started:
            return

        self._movement_started = True

        async def _emit_progress() -> None:
            height = 80.0
            # 1.0 cm progress every 15 updates => slow but steady.
            while height < 85.0:
                height += 1.0 / 15.0
                self.conn._notification_count += 1
                self.conn._moving_notification_count += 1
                self.conn.current_status = {
                    "height_cm": round(height, 1),
                    "is_moving": True,
                    "direction": "up",
                }
                await asyncio.sleep(0.01)

        self._task = asyncio.create_task(_emit_progress())


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
        loop after persistent idleness. To avoid false positives from single
        transient idle packets, the threshold is now 2 idle events.
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
            6,
            (
                "Movement must still abort within a few UP commands when "
                "the physical panel STOP repeatedly interrupts HA UP "
                "commands. One confirmed idle episode plus a short resume "
                "grace is tolerated to avoid false positives from a single "
                "long pause, but HA should still back off quickly enough to "
                "avoid interfering with panel input."
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

        Detection path: the stall counter is only active when the desk is
        *completely* silent (no BLE packets at all), so it does not fire
        here.  Instead the height-progress window catches the pattern:
        0.1 cm/step × 15 steps = 1.5 cm which is below HEIGHT_PROGRESS_MIN_CM
        (2.0 cm). To reduce false positives, abort now requires two
        consecutive low-progress windows, so it should happen within ~30 UP
        commands (~6 s).
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
            31,  # two low-progress windows: at most ~30 active steps
            (
                "Movement must abort within ~30 UP commands when the physical "
                "panel STOP repeatedly silences the desk motor with no "
                "is_moving=False notification, leaving the desk barely "
                "advancing (0.1 cm per HA step) — caught by the "
                "HEIGHT_PROGRESS_MIN_CM window (2.0 cm / 3 s) across two "
                "consecutive windows."
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
        self.assertEqual(
            fake_client.disconnect_calls,
            0,
            "No immediate disconnect should be attempted during panel "
            "preset handoff; immediate GATT teardown can lock the desk.",
        )
        self.assertIsNone(
            conn.client,
            "Connection should be quarantined locally after panel preset "
            "handoff so HA stops using the live BLE link immediately.",
        )

    async def test_panel_button_stop_no_final_stop_for_safety(
        self,
    ):
        """Idle-abort must skip STOP and avoid immediate BLE teardown.

        Regression: when a panel button stops movement (idle), we cannot
        reliably distinguish between a simple stop vs. a preset that is about
        to start. To avoid cancelling a delayed preset, idle-abort never sends
        final STOP. Immediate disconnect is also unsafe on some desks, so the
        connection must be quarantined locally first and only released later.

        Critical detail: no immediate stop_notify/disconnect call is allowed,
        because panel-transition firmware can lock hard in that window.
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
        self.assertEqual(
            fake_client.disconnect_calls,
            0,
            "Idle-abort must not attempt immediate disconnect during the "
            "panel-handoff window.",
        )
        self.assertEqual(
            fake_client.stop_notify_calls,
            0,
            "Idle-abort release must not call stop_notify because that can "
            "lock TiMotion firmware during panel transitions.",
        )
        self.assertIsNone(
            conn.client,
            "Idle-abort should quarantine the client locally so HA does not "
            "keep driving the live BLE link after panel input.",
        )
        move_commands = [
            cmd
            for cmd in fake_client.commands
            if cmd == standup_desk.UP_COMMAND
        ]
        self.assertLessEqual(
            len(move_commands),
            5,
            "After a confirmed idle episode from a panel stop, HA must stop "
            "sending further UP commands quickly so BLE control is released "
            "instead of fighting the panel.",
        )

    async def test_idle_abort_with_delayed_preset_transition_sends_no_stop(
        self,
    ):
        """No STOP and no immediate disconnect during idle-abort handoff.

        stop_notify during an active panel preset transition can lock the
        TiMotion firmware. We therefore quarantine the connection locally and
        delay any teardown/reconnect attempts until after a cooldown.
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
        self.assertEqual(
            fake_client.disconnect_calls,
            0,
            "Idle-abort must not attempt an immediate disconnect during a "
            "potential preset transition window.",
        )
        self.assertEqual(
            fake_client.stop_notify_calls,
            0,
            "Idle-abort release must not call stop_notify because that can "
            "lock TiMotion firmware during panel transitions.",
        )
        self.assertIsNone(
            conn.client,
            "Idle-abort should quarantine the client locally so HA stops "
            "touching the live BLE link during preset handoff.",
        )
        self.assertFalse(
            await conn.ensure_connected(),
            "Reconnect attempts should be blocked briefly after panel "
            "handoff to avoid another immediate STOP-based handshake.",
        )

    async def test_transient_idle_pulse_does_not_abort_normal_up_movement(
        self,
    ):
        """A short idle glitch must not trigger panel-stop abort."""
        setattr(standup_desk, "MOVEMENT_INTERVAL", 0.05)
        setattr(standup_desk, "MAX_MOVEMENT_STEPS", 50)

        conn = StandUpDeskConnection("AA:BB", cast(Any, FakeHass()))
        fake_client = TransientIdlePulseClient(conn)
        conn.client = cast(Any, fake_client)
        conn.is_connected = True
        conn.current_status = {
            "height_cm": 80,
            "is_moving": False,
            "direction": "idle",
        }

        await conn.move_to_height(120, "up")

        self.assertGreaterEqual(
            conn.current_status.get("height_cm", 0),
            117,
            "Desk should still reach target despite one transient idle pulse.",
        )
        self.assertEqual(
            fake_client.disconnect_calls,
            0,
            "Transient idle pulse must not trigger panel-interrupt "
            "BLE release.",
        )

    async def test_single_confirmed_idle_episode_allows_up_recovery(self):
        """One confirmed idle episode must not abort normal UP movement."""
        setattr(standup_desk, "MOVEMENT_INTERVAL", 0.05)
        setattr(standup_desk, "MAX_MOVEMENT_STEPS", 60)

        conn = StandUpDeskConnection("AA:BB", cast(Any, FakeHass()))
        fake_client = SingleConfirmedIdleEpisodeThenResumeClient(conn)
        conn.client = cast(Any, fake_client)
        conn.is_connected = True
        conn.current_status = {
            "height_cm": 80,
            "is_moving": False,
            "direction": "idle",
        }

        await conn.move_to_height(120, "up")

        self.assertGreaterEqual(
            conn.current_status.get("height_cm", 0),
            117,
            "Desk should still reach target after one confirmed idle "
            "episode followed by resumed upward movement.",
        )
        self.assertEqual(
            fake_client.disconnect_calls,
            0,
            "Single confirmed idle episode must not trigger panel-interrupt "
            "BLE release.",
        )

    async def test_long_idle_stretch_counts_as_single_episode_then_recovers(
        self,
    ):
        """One long idle stretch must not be double-counted as two episodes."""
        setattr(standup_desk, "MOVEMENT_INTERVAL", 0.05)
        setattr(standup_desk, "MAX_MOVEMENT_STEPS", 60)

        conn = StandUpDeskConnection("AA:BB", cast(Any, FakeHass()))
        fake_client = ConfirmedIdleStretchThenResumeClient(conn)
        conn.client = cast(Any, fake_client)
        conn.is_connected = True
        conn.current_status = {
            "height_cm": 80,
            "is_moving": False,
            "direction": "idle",
        }

        await conn.move_to_height(120, "up")

        self.assertGreaterEqual(
            conn.current_status.get("height_cm", 0),
            117,
            "Desk should recover after one sustained idle stretch that "
            "later resumes upward movement.",
        )
        self.assertEqual(
            fake_client.disconnect_calls,
            0,
            "One sustained idle stretch must not trigger panel-interrupt "
            "BLE release.",
        )

    async def test_slow_upward_startup_does_not_trigger_height_stuck(self):
        """Slow but real upward progress must get one grace window."""
        setattr(standup_desk, "MOVEMENT_INTERVAL", 0.01)
        setattr(standup_desk, "MAX_MOVEMENT_STEPS", 120)

        conn = StandUpDeskConnection("AA:BB", cast(Any, FakeHass()))
        fake_client = SlowUpStartupThenRecoverClient(conn)
        conn.client = cast(Any, fake_client)
        conn.is_connected = True
        conn.current_status = {
            "height_cm": 78.0,
            "is_moving": False,
            "direction": "idle",
        }

        await conn.move_to_height(125, "up")

        self.assertGreaterEqual(
            conn.current_status.get("height_cm", 0),
            122,
            "Desk should continue upward after one slow startup window "
            "instead of tripping the height-stuck abort.",
        )
        self.assertEqual(
            fake_client.disconnect_calls,
            0,
            "Slow upward startup must not trigger a panel-interrupt BLE "
            "release.",
        )

    async def test_sustained_slow_upward_progress_does_not_false_abort(
        self,
    ):
        """Continuous slow UP movement must not trip height-stuck abort."""
        setattr(standup_desk, "MOVEMENT_INTERVAL", 0.01)
        setattr(standup_desk, "MAX_MOVEMENT_STEPS", 160)

        conn = StandUpDeskConnection("AA:BB", cast(Any, FakeHass()))
        fake_client = SustainedSlowContinuousUpClient(conn)
        conn.client = cast(Any, fake_client)
        conn.is_connected = True
        conn.current_status = {
            "height_cm": 80.0,
            "is_moving": False,
            "direction": "idle",
        }

        await conn.move_to_height(85, "up")

        self.assertGreaterEqual(
            conn.current_status.get("height_cm", 0),
            82,
            "Desk should keep moving upward during sustained slow but "
            "continuous motion instead of aborting as height-stuck.",
        )
        self.assertEqual(
            fake_client.disconnect_calls,
            0,
            "Sustained slow upward motion must not trigger panel-interrupt "
            "BLE release.",
        )


if __name__ == "__main__":
    unittest.main()
