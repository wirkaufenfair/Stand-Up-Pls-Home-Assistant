# Stand Up Pls Desk

[![HACS Validation](https://github.com/wirkaufenfair/Stand-Up-Pls-Home-Assistant/actions/workflows/validate.yml/badge.svg)](https://github.com/wirkaufenfair/Stand-Up-Pls-Home-Assistant/actions/workflows/validate.yml)
[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)

A [Home Assistant](https://www.home-assistant.io/) custom integration to control **TiMotion TWD1** Bluetooth sit-stand desks via BLE.

The BLE protocol was reverse-engineered from the "Stand Up Pls" iOS/Android app (based on [2easy/go-Stand-Up-Pls](https://github.com/2easy/go-Stand-Up-Pls)).

## Features

- Automatic Bluetooth discovery of your desk
- Real-time height and movement status sensors
- One-button sit/stand/stop controls
- Configurable sit and stand height presets
- Services for automations (`standup_desk.control`, `standup_desk.move_to`)
- Device automations support

## Requirements

- Home Assistant 2024.1.0 or newer
- A Bluetooth adapter accessible by Home Assistant
- A TiMotion TWD1 compatible sit-stand desk (advertises Nordic UART Service)

## Installation

### HACS (recommended)

1. Open HACS in your Home Assistant instance
2. Click the three dots in the top right corner and select **Custom repositories**
3. Add `https://github.com/wirkaufenfair/Stand-Up-Pls-Home-Assistant` with category **Integration**
4. Search for "Stand Up Pls Desk" and install it
5. Restart Home Assistant

### Manual

1. Download the latest release from [GitHub Releases](https://github.com/wirkaufenfair/Stand-Up-Pls-Home-Assistant/releases)
2. Copy the `custom_components/standup_desk` folder to your Home Assistant `config/custom_components/` directory
3. Restart Home Assistant

## Configuration

### Automatic (Bluetooth discovery)

If your desk is powered on and within Bluetooth range, Home Assistant will automatically discover it. You will see a notification to set it up.

### Manual setup

1. Go to **Settings** > **Devices & Services** > **Add Integration**
2. Search for "Stand Up Pls Desk"
3. Enter your device name (default: `stand UP-`)
4. The integration will search for a matching Bluetooth device and set it up

### Options

After setup, you can configure the sit and stand height presets:

1. Go to **Settings** > **Devices & Services**
2. Click **Configure** on your Stand Up Pls Desk integration
3. Set your preferred **Sit height** and **Stand height** (65-130 cm)

## Entities

Each desk device creates the following entities:

| Entity | Type | Description |
|--------|------|-------------|
| Height | Sensor | Current desk height in cm |
| Movement | Sensor | Movement state: `up`, `down`, or `idle` |
| Sit height | Number | Configurable sit height preset (65-130 cm) |
| Stand height | Number | Configurable stand height preset (65-130 cm) |
| Sit | Button | Move desk down to sit height |
| Stand | Button | Move desk up to stand height |
| Stop | Button | Stop desk movement |

## Services

### `standup_desk.control`

Move the desk up, down, or stop.

| Parameter | Required | Description |
|-----------|----------|-------------|
| `action` | Yes | `up`, `down`, or `stop` |
| `target_height` | No | Target height in cm (overrides preset) |

### `standup_desk.move_to`

Move the desk to a specific height.

| Parameter | Required | Description |
|-----------|----------|-------------|
| `height` | Yes | Target height in cm (65-130) |

### Automation example

```yaml
automation:
  - alias: "Stand up reminder"
    trigger:
      - platform: time
        at: "10:00:00"
    action:
      - service: standup_desk.control
        data:
          action: up
```

## Troubleshooting

- **Desk not discovered:** Make sure the desk is powered on and within Bluetooth range. Check that your Bluetooth adapter is working in Home Assistant under **Settings** > **Devices & Services** > **Bluetooth**.
- **Connection fails:** The desk can only maintain one BLE connection at a time. Close the "Stand Up Pls" app on your phone before connecting via Home Assistant.
- **Height readings inaccurate:** The desk reports height relative to its internal calibration. Small offsets are normal.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
