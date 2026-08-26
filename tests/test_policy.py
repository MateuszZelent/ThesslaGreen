from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from thessla_green.control import (
    ControlIntent,
    IntentPriority,
    PolicyArbiter,
)

BASE_TIME = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)


def intent(
    source: str,
    priority: IntentPriority,
    *,
    created_offset: int = 0,
    expires_offset: int | None = 60,
    command_type: str = "set_fan_speed",
) -> ControlIntent:
    return ControlIntent(
        command_type=command_type,
        parameters={"percentage": 40},
        priority=priority,
        source=source,
        reason=f"test:{source}",
        created_at=BASE_TIME + timedelta(seconds=created_offset),
        expires_at=(
            BASE_TIME + timedelta(seconds=expires_offset)
            if expires_offset is not None
            else None
        ),
    )


def test_safety_intent_wins_over_manual_and_automation() -> None:
    arbiter = PolicyArbiter()
    decision = arbiter.decide(
        [
            intent("schedule", IntentPriority.SCHEDULE),
            intent("mobile", IntentPriority.MANUAL),
            intent("safety", IntentPriority.SAFETY),
        ],
        at=BASE_TIME,
    )

    assert decision.selected is not None
    assert decision.selected.source == "safety"
    assert decision.reason == "highest_priority"
    assert len(decision.rejected) == 2


def test_manual_override_suppresses_lower_priority_intents_but_not_safety() -> None:
    arbiter = PolicyArbiter()
    arbiter.set_manual_override(BASE_TIME + timedelta(seconds=30))

    decision = arbiter.decide(
        [
            intent("temperature", IntentPriority.TEMPERATURE),
            intent("air-quality", IntentPriority.AIR_QUALITY),
        ],
        at=BASE_TIME,
    )
    assert decision.selected is None
    assert decision.reason == "manual_override_active"

    safety_decision = arbiter.decide(
        [intent("safety", IntentPriority.SAFETY)],
        at=BASE_TIME,
    )
    assert safety_decision.selected is not None
    assert safety_decision.selected.source == "safety"


def test_manual_override_expires_and_ties_are_deterministic() -> None:
    arbiter = PolicyArbiter()
    arbiter.set_manual_override(BASE_TIME + timedelta(seconds=10))
    older = intent("a", IntentPriority.TEMPERATURE, created_offset=0)
    newer = intent("b", IntentPriority.TEMPERATURE, created_offset=1)

    decision = arbiter.decide([older, newer], at=BASE_TIME + timedelta(seconds=11))
    assert decision.selected is newer
    assert arbiter.manual_override_until is None


def test_expired_intent_and_raw_register_intent_are_rejected() -> None:
    arbiter = PolicyArbiter()
    expired = intent("old", IntentPriority.MANUAL, expires_offset=1)
    decision = arbiter.decide([expired], at=BASE_TIME + timedelta(seconds=1))
    assert not decision.has_command
    assert decision.reason == "no_active_intent"

    with pytest.raises(ValueError, match="typed commands"):
        intent("unsafe", IntentPriority.MANUAL, command_type="raw_modbus")


def test_intent_requires_timezone_aware_timestamps() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        ControlIntent(
            command_type="set_mode",
            parameters={"mode": "manual"},
            priority=IntentPriority.MANUAL,
            source="test",
            reason="test",
            created_at=datetime(2026, 1, 1),
        )
