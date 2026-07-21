"""Constants for the Tapo L630 integration."""

from datetime import timedelta

DOMAIN = "tapo_l630"
PLATFORMS = ["light"]
SCAN_INTERVAL = timedelta(seconds=15)

MIN_COLOR_TEMP_KELVIN = 2500
MAX_COLOR_TEMP_KELVIN = 6500
