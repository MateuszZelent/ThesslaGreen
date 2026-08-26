from __future__ import annotations

import pytest

from thessla_green.config import Settings


def test_cors_origins_are_explicit_and_trimmed() -> None:
    settings = Settings.from_env(
        {
            "THESSLA_API_CORS_ORIGINS": " https://phone.example,https://dashboard.example ,,",
        }
    )

    assert settings.api_cors_origins == (
        "https://phone.example",
        "https://dashboard.example",
    )


def test_cors_is_disabled_by_default() -> None:
    assert Settings.from_env({}).api_cors_origins == ()


def test_cors_rejects_wildcard_origin() -> None:
    with pytest.raises(ValueError, match="explicit origins"):
        Settings.from_env({"THESSLA_API_CORS_ORIGINS": "*"})


def test_airflow_observation_window_is_configurable() -> None:
    settings = Settings.from_env(
        {
            "THESSLA_AIRFLOW_OBSERVATION_SECONDS": "5",
            "THESSLA_AIRFLOW_OBSERVATION_INTERVAL_SECONDS": "0.5",
        }
    )

    assert settings.airflow_observation_seconds == 5
    assert settings.airflow_observation_interval_seconds == 0.5


def test_airflow_observation_window_rejects_invalid_values() -> None:
    with pytest.raises(ValueError, match="cannot be negative"):
        Settings(airflow_observation_seconds=-1)
    with pytest.raises(ValueError, match="must be positive"):
        Settings(airflow_observation_interval_seconds=0)
