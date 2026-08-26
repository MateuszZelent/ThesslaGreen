"""Constants for the Thessla Green Home Assistant adapter."""

from __future__ import annotations

from datetime import timedelta

DOMAIN = "thessla_green"
CONF_CONNECTION_TYPE = "connection_type"
CONF_SERIAL_PORT = "serial_port"
CONF_UNIT_ID = "unit_id"
CONF_BAUDRATE = "baudrate"
CONF_TIMEOUT = "timeout"
CONF_URL = "url"
CONF_TOKEN = "token"
CONNECTION_DIRECT = "direct"
CONNECTION_GATEWAY = "gateway"
DEFAULT_CONNECTION_TYPE = CONNECTION_DIRECT
DEFAULT_UNIT_ID = 10
DEFAULT_BAUDRATE = 9600
DEFAULT_TIMEOUT = 1.5
DEFAULT_URL = "http://127.0.0.1:8000"
DEFAULT_SCAN_INTERVAL = timedelta(seconds=5)

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
MODE_LABELS = {
    "automatic": "Automatyczny",
    "manual": "Ręczny",
    "temporary": "Chwilowy",
}
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

SPECIAL_MODE_LABELS = {
    "none": "Brak",
    "hood": "Okap",
    "fireplace": "Kominek",
    "airing_manual": "Wietrzenie",
    "open_windows": "Otwarte okna",
    "empty_house": "Pusty dom",
}
