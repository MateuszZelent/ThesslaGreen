"""Deterministic arbitration for future automation rules.

This module decides *which typed intent should win*. It deliberately does not
know Modbus addresses, FastAPI, Home Assistant, or sensor-specific registers.
The application gateway remains the only component allowed to translate the
winning intent into a validated, read-confirmed command.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import IntEnum


class IntentPriority(IntEnum):
    """Policy order from a safety fallback to a background schedule."""

    SAFETY = 100
    MANUAL = 80
    SPECIAL = 60
    AIR_QUALITY = 40
    TEMPERATURE = 30
    SCHEDULE = 10


@dataclass(frozen=True, slots=True)
class ControlIntent:
    """A proposed typed gateway command with an explainable lifetime."""

    command_type: str
    parameters: Mapping[str, object]
    priority: IntentPriority
    source: str
    reason: str
    created_at: datetime
    expires_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.command_type.strip():
            raise ValueError("control intent command_type cannot be empty")
        if self.command_type in {"write_register", "raw_modbus", "write_raw_register"}:
            raise ValueError("control intents must use typed commands")
        if not isinstance(self.priority, IntentPriority):
            raise TypeError("control intent priority must be an IntentPriority")
        if not self.source.strip():
            raise ValueError("control intent source cannot be empty")
        if not self.reason.strip():
            raise ValueError("control intent reason cannot be empty")
        self._require_aware(self.created_at, "created_at")
        if self.expires_at is not None:
            self._require_aware(self.expires_at, "expires_at")
            if self.expires_at <= self.created_at:
                raise ValueError("control intent expires_at must be after created_at")

    @staticmethod
    def _require_aware(value: datetime, name: str) -> None:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"control intent {name} must be timezone-aware")

    def is_active(self, at: datetime) -> bool:
        """Return whether this intent is eligible at a given instant."""

        self._require_aware(at, "evaluation time")
        if at < self.created_at:
            return False
        return self.expires_at is None or at < self.expires_at

    def to_dict(self) -> dict[str, object]:
        return {
            "command_type": self.command_type,
            "parameters": dict(self.parameters),
            "priority": self.priority.name.lower(),
            "priority_value": int(self.priority),
            "source": self.source,
            "reason": self.reason,
            "created_at": self.created_at.isoformat(),
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
        }


@dataclass(frozen=True, slots=True)
class ControlPolicyDecision:
    """Winner plus rejected candidates and a human-readable explanation."""

    selected: ControlIntent | None
    rejected: tuple[ControlIntent, ...]
    reason: str
    evaluated_at: datetime

    def __post_init__(self) -> None:
        if self.evaluated_at.tzinfo is None or self.evaluated_at.utcoffset() is None:
            raise ValueError("policy decision evaluated_at must be timezone-aware")
        if not self.reason.strip():
            raise ValueError("policy decision reason cannot be empty")

    @property
    def has_command(self) -> bool:
        return self.selected is not None

    def to_dict(self) -> dict[str, object]:
        return {
            "selected": self.selected.to_dict() if self.selected else None,
            "rejected": [intent.to_dict() for intent in self.rejected],
            "reason": self.reason,
            "evaluated_at": self.evaluated_at.isoformat(),
        }


class PolicyArbiter:
    """Choose one intent while respecting safety and manual override rules.

    A manual override suppresses lower-priority automation until its expiry,
    but never suppresses a safety intent. Ties are deterministic: priority,
    creation time, source and command name are used in that order.
    """

    def __init__(self) -> None:
        self._manual_override_until: datetime | None = None

    @property
    def manual_override_until(self) -> datetime | None:
        return self._manual_override_until

    def set_manual_override(self, until: datetime) -> None:
        self._require_aware(until, "manual override expiry")
        self._manual_override_until = until

    def clear_manual_override(self) -> None:
        self._manual_override_until = None

    def decide(
        self,
        intents: Iterable[ControlIntent],
        *,
        at: datetime | None = None,
    ) -> ControlPolicyDecision:
        evaluated_at = at or datetime.now(UTC)
        self._require_aware(evaluated_at, "evaluation time")
        if self._manual_override_until is not None and evaluated_at >= self._manual_override_until:
            self._manual_override_until = None

        active = [intent for intent in intents if intent.is_active(evaluated_at)]
        eligible = active
        if self._manual_override_until is not None:
            eligible = [
                intent
                for intent in active
                if intent.priority >= IntentPriority.MANUAL
                or intent.priority is IntentPriority.SAFETY
            ]

        if not eligible:
            reason = (
                "manual_override_active"
                if self._manual_override_until is not None and active
                else "no_active_intent"
            )
            return ControlPolicyDecision(
                selected=None,
                rejected=tuple(active),
                reason=reason,
                evaluated_at=evaluated_at,
            )

        selected = max(
            eligible,
            key=lambda intent: (
                int(intent.priority),
                intent.created_at,
                intent.source,
                intent.command_type,
            ),
        )
        rejected = tuple(intent for intent in active if intent is not selected)
        reason = (
            "manual_override" if self._manual_override_until is not None else "highest_priority"
        )
        return ControlPolicyDecision(
            selected=selected,
            rejected=rejected,
            reason=reason,
            evaluated_at=evaluated_at,
        )

    @staticmethod
    def _require_aware(value: datetime, name: str) -> None:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{name} must be timezone-aware")
