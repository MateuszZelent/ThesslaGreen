"""Pydantic request/response contracts for the versioned HTTP API."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator


class CommandRequest(BaseModel):
    """One typed, idempotent command submitted by an adapter."""

    model_config = ConfigDict(extra="forbid")

    type: str = Field(min_length=1, max_length=64)
    parameters: dict[str, Any] = Field(default_factory=dict)
    request_id: str | None = Field(default=None, min_length=1, max_length=128)
    expected_revision: StrictInt | None = Field(default=None, ge=0)

    @field_validator("type")
    @classmethod
    def normalize_type(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("command type cannot be empty")
        return normalized


class CommandResponse(BaseModel):
    """Confirmed state returned after a command or its idempotent replay."""

    status: Literal["confirmed"]
    request_id: str | None = None
    replayed: bool = False
    result: dict[str, Any]
    state: dict[str, Any]
