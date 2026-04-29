"""Constants for the Stand Up Pls Desk integration."""

DOMAIN = "standup_desk"

# Nordic UART Service (NUS) UUIDs
SERVICE_UUID = "6e400001-b5a3-f393-e0a9-e50e24dcca9e"
TX_CHAR_UUID = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"  # desk → phone (notify)
RX_CHAR_UUID = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"  # phone → desk (write)

# TiMotion TWD1 BLE commands
# Source: github.com/2easy/go-Stand-Up-Pls
# Reverse-engineered from the "Stand Up Pls" app.
UP_COMMAND = bytes([0xD9, 0xFF, 0x01, 0x63, 0x3C])
DOWN_COMMAND = bytes([0xD9, 0xFF, 0x02, 0x60, 0x3A])
STOP_COMMAND = bytes([0x00, 0x00, 0x00, 0x00, 0x00])

# Config keys
CONF_SIT_HEIGHT = "sit_height"
CONF_STAND_HEIGHT = "stand_height"

# Defaults
DEFAULT_SIT_HEIGHT = 77
DEFAULT_STAND_HEIGHT = 124

# Height limits (cm)
HEIGHT_MIN = 65
HEIGHT_MAX = 130

# Movement parameters
TOLERANCE_CM = 3
MOVEMENT_INTERVAL = 0.2  # seconds between BLE commands
MAX_MOVEMENT_STEPS = 150  # 150 * 0.2s = 30s max
MAX_STALL_STEPS = 5  # abort early if the desk stays idle / stuck for too long
STARTUP_GRACE_STEPS = 15  # 15 × 0.2 s = 3 s window before stall/height-stuck checks activate
HEIGHT_PROGRESS_MIN_CM = 2.0  # minimum cm the desk must advance per 15-step (3 s) window

# Manufacturer info
MANUFACTURER = "TiMotion"
MODEL = "TWD1"
