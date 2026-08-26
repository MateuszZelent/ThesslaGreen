"""Constants for the Thessla Green Home Assistant adapter."""

from __future__ import annotations

from datetime import timedelta

DOMAIN = "thessla_green"
CONF_URL = "url"
CONF_TOKEN = "token"
DEFAULT_URL = "http://127.0.0.1:8000"
DEFAULT_SCAN_INTERVAL = timedelta(seconds=5)

PLATFORMS = ("binary_sensor", "fan", "sensor", "select", "button")

MODE_OPTIONS = {
    "automatic": 0,
    "manual": 1,
    "temporary": 2,
}

SPECIAL_MODE_OPTIONS = {
    "none": 0,
    "hood": 1,
    "fireplace": 2,
    "airing_manual": 7,
    "open_windows": 10,
    "empty_house": 11,
}

MODE_NAMES = {value: key for key, value in MODE_OPTIONS.items()}
SPECIAL_MODE_NAMES = {
    0: "none",
    1: "hood",
    2: "fireplace",
    3: "airing_button",
    4: "airing_switch",
    5: "airing_humidity",
    6: "airing_air_quality",
    7: "airing_manual",
    8: "airing_automatic",
    9: "airing_schedule",
    10: "open_windows",
    11: "empty_house",
}
