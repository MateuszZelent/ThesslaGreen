"""Gateway lifecycle and normalized state service."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections.abc import Awaitable, Callable, Mapping
from contextlib import suppress
from datetime import UTC, datetime

from custom_components.thessla_green._core.application.control import (
    DEFAULT_CONTROL_CAPABILITIES,
    USER_SELECTABLE_SPECIAL_MODES,
    AirPackController,
    AirPackMode,
    ComfortPreference,
    CommandConflict,
    ControlResult,
    SpecialMode,
)
from custom_components.thessla_green._core.application.lease import EndpointLease, EndpointLeaseBusy
from custom_components.thessla_green._core.control import ControlIntent, ControlPolicyDecision
from custom_components.thessla_green._core.discovery.probe import AirPackProbe
from custom_components.thessla_green._core.domain.models import (
    AuditEvent,
    Capabilities,
    DeviceIdentity,
    DeviceState,
    TransportEndpoint,
)
from custom_components.thessla_green._core.protocol.codec import (
    decode_airflow,
    decode_airpack_temperature,
    decode_firmware_version,
    decode_serial_number,
)
from custom_components.thessla_green._core.protocol.profile import AIRPACK4_PROFILE
from custom_components.thessla_green._core.protocol.transport import (
    ModbusTransport,
    ReadResponseError,
)
from custom_components.thessla_green._core.storage import EventStore

_LOGGER = logging.getLogger(__name__)

DEFAULT_CAPABILITIES = Capabilities(
    features=DEFAULT_CONTROL_CAPABILITIES.features
    | frozenset({"temperatures", "airflow", "season", "comfort_mode", "bypass_off"}),
    min_fan_percentage=DEFAULT_CONTROL_CAPABILITIES.min_fan_percentage,
    max_fan_percentage=DEFAULT_CONTROL_CAPABILITIES.max_fan_percentage,
)


class GatewayNotStarted(RuntimeError):
    """Raised when a caller requests hardware access before startup."""


class GatewayService:
    """Single owner of one selected Modbus endpoint and AirPack unit."""

    def __init__(
        self,
        transport: ModbusTransport,
        *,
        endpoint: TransportEndpoint,
        unit_id: int,
        identity: DeviceIdentity | None = None,
        capabilities: Capabilities | None = None,
        store: EventStore | None = None,
        command_cache_limit: int = 256,
        command_cache_ttl_seconds: float = 86400.0,
        airflow_observation_seconds: float = 0.0,
        airflow_observation_interval_seconds: float = 1.0,
    ) -> None:
        if command_cache_limit < 1:
            raise ValueError("command cache limit must be positive")
        if command_cache_ttl_seconds <= 0:
            raise ValueError("command cache TTL must be positive")
        if airflow_observation_seconds < 0:
            raise ValueError("airflow observation window cannot be negative")
        if airflow_observation_interval_seconds <= 0:
            raise ValueError("airflow observation interval must be positive")
        self.transport = transport
        self.endpoint = endpoint
        self.unit_id = unit_id
        self.identity = identity
        self.capabilities = capabilities or DEFAULT_CAPABILITIES
        self.store = store
        self.controller = AirPackController(
            transport,
            endpoint=endpoint,
            unit_id=unit_id,
            identity=identity,
            capabilities=self.capabilities,
        )
        self._started = False
        self._poll_task: asyncio.Task[None] | None = None
        self._command_lock = asyncio.Lock()
        self._command_cache_limit = command_cache_limit
        self._command_cache_ttl_seconds = command_cache_ttl_seconds
        self._airflow_observation_seconds = airflow_observation_seconds
        self._airflow_observation_interval_seconds = airflow_observation_interval_seconds
        self._command_cache: dict[str, tuple[str, dict[str, object], datetime]] = {}
        self._persisted_audit_count = 0
        self._endpoint_lease = EndpointLease(endpoint)
        self._state = DeviceState(
            revision=0,
            online=False,
            identity=identity,
            capabilities=self.capabilities,
        )

    @property
    def state(self) -> DeviceState:
        return self._state

    @property
    def audit_events(self) -> tuple[AuditEvent, ...]:
        """Write evidence collected by the single controller owner."""

        return self.controller.audit_events

    async def start(self) -> DeviceState:
        if self._started:
            return self._state
        if self.store is not None:
            await self.store.initialize()
        try:
            self._endpoint_lease.acquire()
        except EndpointLeaseBusy as exc:
            raise GatewayNotStarted(str(exc)) from exc
        try:
            await self.transport.connect()
            probe = await AirPackProbe().run(self.transport, self.endpoint, self.unit_id)
            if not probe.is_selectable or probe.identity is None:
                raise GatewayNotStarted(
                    "selected endpoint is not a confirmed AirPack device: "
                    f"{probe.error or probe.status}"
                )
            self.identity = probe.identity
            self.capabilities = AirPackProbe.capabilities(probe)
            self.controller.identity = self.identity
            self.controller.capabilities = self.capabilities
            self._started = True
            return await self.refresh()
        except BaseException:
            self._started = False
            with suppress(Exception):
                await self.transport.close()
            self._endpoint_lease.release()
            raise

    async def stop(self) -> None:
        self._started = False
        if self._poll_task is not None:
            self._poll_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._poll_task
            self._poll_task = None
        try:
            await self.transport.close()
        finally:
            self._endpoint_lease.release()

    def start_polling(self, interval_seconds: float = 5.0) -> None:
        """Start one background snapshot loop owned by this gateway."""

        if interval_seconds <= 0:
            raise ValueError("poll interval must be positive")
        if not self._started:
            raise GatewayNotStarted("gateway must be started before polling")
        if self._poll_task is None:
            self._poll_task = asyncio.create_task(self._poll_loop(interval_seconds))

    async def _poll_loop(self, interval_seconds: float) -> None:
        try:
            while self._started:
                await asyncio.sleep(interval_seconds)
                if self._started:
                    await self.refresh()
        except asyncio.CancelledError:
            raise

    async def refresh(self) -> DeviceState:
        if not self._started:
            raise GatewayNotStarted("gateway must be started before refresh")
        try:
            firmware_block = await self.transport.read_input_registers(0, 5, self.unit_id)
            temperatures = await self.transport.read_input_registers(16, 7, self.unit_id)
            serial_block = await self.transport.read_input_registers(24, 6, self.unit_id)
            airflow = await self.transport.read_input_registers(256, 2, self.unit_id)
            ventilation = await self.transport.read_input_registers(271, 5, self.unit_id)
            fpx_system = await self._read_optional_holding_register(4192)
            fpx_stage = await self._read_optional_holding_register(4198)
            mode_block = await self.transport.read_holding_registers(4208, 4, self.unit_id)
            special_mode = await self.transport.read_holding_registers(4224, 1, self.unit_id)
            comfort = await self.transport.read_holding_registers(4304, 2, self.unit_id)
            bypass_off = await self.transport.read_holding_registers(4320, 1, self.unit_id)
            bypass_mode = await self.transport.read_holding_registers(4330, 1, self.unit_id)
            bypass_actuator_open = await self._read_optional_coil(9)
            power = await self.transport.read_holding_registers(4387, 1, self.unit_id)
            erv_post_heater = await self._read_optional_holding_register(4704)
            erv_post_heater_mode = await self._read_optional_holding_register(4711)

            firmware = decode_firmware_version(
                (firmware_block[0], firmware_block[1], firmware_block[4])
            )
            serial_number = decode_serial_number(serial_block)
            if int(ventilation[0]) not in (0, 1):
                raise ValueError("constant flow status must be 0 or 1")
            if any(not 0 <= int(value) <= 150 for value in ventilation[1:3]):
                raise ValueError("active fan percentages must be in the documented range 0..150")
            if any(not 0 <= int(value) <= 4095 for value in ventilation[3:5]):
                raise ValueError("target airflow must be in the documented range 0..4095")
            if self.identity is None:
                self.identity = DeviceIdentity(
                    model=AIRPACK4_PROFILE.model_name,
                    unit_id=self.unit_id,
                    firmware=firmware,
                    serial_number=serial_number or None,
                    endpoint=self.endpoint,
                )
                self.controller.identity = self.identity
            values: dict[str, object] = {
                "firmware": ".".join(str(part) for part in firmware),
                "serial_number": serial_number or None,
                "outdoor_temperature": decode_airpack_temperature(temperatures[0]),
                "supply_temperature": decode_airpack_temperature(temperatures[1]),
                "extract_temperature": decode_airpack_temperature(temperatures[2]),
                "fpx_temperature": decode_airpack_temperature(temperatures[3]),
                "duct_supply_temperature": decode_airpack_temperature(temperatures[4]),
                "gwc_temperature": decode_airpack_temperature(temperatures[5]),
                "ambient_temperature": decode_airpack_temperature(temperatures[6]),
                "supply_airflow": decode_airflow(airflow[0]),
                "extract_airflow": decode_airflow(airflow[1]),
                "constant_flow_available": airflow[0] != 0xFFFF and airflow[1] != 0xFFFF,
                "constant_flow_active": bool(ventilation[0]),
                "supply_percentage": ventilation[1],
                "extract_percentage": ventilation[2],
                "supply_flowrate": ventilation[3],
                "extract_flowrate": ventilation[4],
                "fpx_system_active": bool(fpx_system) if fpx_system in (0, 1) else None,
                "fpx_stage": fpx_stage if fpx_stage in (0, 1, 2) else None,
                "mode": mode_block[0],
                "season": mode_block[1],
                "manual_fan_speed": mode_block[2],
                "temporary_fan_speed": mode_block[3],
                "special_mode": special_mode[0],
                "comfort_mode_panel": comfort[0],
                "comfort_mode": comfort[1],
                "bypass_off": bypass_off[0],
                "bypass_mode": bypass_mode[0],
                "bypass_actuator_open": bypass_actuator_open,
                "power": power[0],
                "erv_post_heater_active": (
                    bool(erv_post_heater) if erv_post_heater in (0, 1) else None
                ),
                "erv_post_heater_mode": (
                    erv_post_heater_mode if erv_post_heater_mode in (0, 1, 2) else None
                ),
            }
        except (ReadResponseError, OSError, TimeoutError, ValueError, IndexError) as exc:
            self._state = DeviceState(
                revision=self._state.revision + 1,
                captured_at=datetime.now(UTC),
                online=False,
                identity=self.identity,
                capabilities=self.capabilities,
                values=self._state.values,
                quality="error",
                error=str(exc),
            )
            await self._persist_state()
            return self._state

        self._state = DeviceState(
            revision=self._state.revision + 1,
            captured_at=datetime.now(UTC),
            online=True,
            identity=self.identity,
            capabilities=self.capabilities,
            values=values,
            quality="complete",
        )
        await self._persist_state()
        return self._state

    async def _read_optional_holding_register(self, address: int) -> int | None:
        """Read a firmware-dependent diagnostic without taking the gateway offline."""

        try:
            values = await self.transport.read_holding_registers(address, 1, self.unit_id)
        except ReadResponseError:
            return None
        if len(values) != 1:
            return None
        return int(values[0])

    async def _read_optional_coil(self, address: int) -> bool | None:
        """Read a physical actuator state without making it a gateway requirement."""

        try:
            values = await self.transport.read_coils(address, 1, self.unit_id)
        except ReadResponseError:
            return None
        if len(values) != 1:
            return None
        return bool(values[0])

    async def _persist_state(self) -> None:
        if self.store is None:
            return
        try:
            await self.store.record_state(self._state)
        except Exception as exc:  # pragma: no cover - filesystem/SQLite dependent
            _LOGGER.warning("unable to persist gateway state: %s", exc)

    async def _persist_audit_events(self) -> None:
        if self.store is None:
            return
        events = self.controller.audit_events
        while self._persisted_audit_count < len(events):
            event = events[self._persisted_audit_count]
            try:
                await self.store.record_audit(event)
            except Exception as exc:  # pragma: no cover - filesystem/SQLite dependent
                _LOGGER.warning("unable to persist gateway audit event: %s", exc)
                return
            self._persisted_audit_count += 1

    async def _execute_control(
        self, operation: Callable[[], Awaitable[ControlResult]]
    ) -> ControlResult:
        try:
            result = await operation()
        except BaseException:
            await self._persist_audit_events()
            raise
        await self._persist_audit_events()
        await self.refresh()
        return result

    async def set_fan_speed(self, percentage: int, *, source: str = "gateway") -> ControlResult:
        return await self._execute_control(
            lambda: self.controller.set_fan_speed(percentage, source=source)
        )

    async def set_temporary_fan_speed(
        self, percentage: int, *, source: str = "gateway"
    ) -> ControlResult:
        return await self._execute_control(
            lambda: self.controller.set_temporary_fan_speed(percentage, source=source)
        )

    async def activate_temporary_mode(
        self, percentage: int, *, source: str = "gateway"
    ) -> ControlResult:
        return await self._execute_control(
            lambda: self.controller.activate_temporary_mode(percentage, source=source)
        )

    async def set_mode(self, mode: AirPackMode | int, *, source: str = "gateway") -> ControlResult:
        return await self._execute_control(lambda: self.controller.set_mode(mode, source=source))

    async def set_special_mode(
        self, mode: SpecialMode | int, *, source: str = "gateway"
    ) -> ControlResult:
        selected = SpecialMode(mode)
        if selected not in USER_SELECTABLE_SPECIAL_MODES:
            raise ValueError("special mode is observable but not safe for manual activation")
        return await self._execute_control(
            lambda: self.controller.set_special_mode(selected, source=source)
        )

    async def set_comfort_mode(
        self, mode: ComfortPreference | int, *, source: str = "gateway"
    ) -> ControlResult:
        return await self._execute_control(
            lambda: self.controller.set_comfort_mode(mode, source=source)
        )

    async def set_power(self, enabled: bool, *, source: str = "gateway") -> ControlResult:
        return await self._execute_control(
            lambda: self.controller.set_power(enabled, source=source)
        )

    async def telemetry(
        self, *, limit: int = 100, since: str | None = None, until: str | None = None
    ) -> tuple[dict[str, object], ...]:
        if self.store is None:
            return ()
        return await self.store.list_states(limit=limit, since=since, until=until)

    async def stored_audit(self, *, limit: int = 100) -> tuple[dict[str, object], ...]:
        if self.store is None:
            return tuple(event.to_dict() for event in self.audit_events[-limit:])
        return await self.store.list_audit(limit=limit)

    @staticmethod
    def _command_fingerprint(command_type: str, parameters: Mapping[str, object]) -> str:
        try:
            encoded = json.dumps(
                {"type": command_type, "parameters": dict(parameters)},
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                default=str,
            ).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise ValueError("command parameters must be JSON-compatible") from exc
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _parse_bool(value: object) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"on", "true", "1"}:
                return True
            if normalized in {"off", "false", "0"}:
                return False
        raise ValueError("enabled must be a boolean or one of on/off")

    @staticmethod
    def _parse_int(value: object, name: str) -> int:
        if isinstance(value, bool):
            raise TypeError(f"{name} must be an integer")
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            try:
                return int(value)
            except ValueError as exc:
                raise ValueError(f"{name} must be an integer") from exc
        if isinstance(value, float) and value.is_integer():
            return int(value)
        raise ValueError(f"{name} must be an integer")

    @staticmethod
    def _airflow_observation(
        command_type: str,
        before: DeviceState,
        after: DeviceState,
    ) -> dict[str, object] | None:
        """Describe the post-write airflow sample without claiming RPM feedback."""

        if command_type not in {
            "set_fan_speed",
            "set_temporary_fan_speed",
            "activate_temporary_mode",
            "set_mode",
            "set_special_mode",
            "set_power",
        }:
            return None

        before_supply = before.values.get("supply_airflow")
        before_extract = before.values.get("extract_airflow")
        after_supply = after.values.get("supply_airflow")
        after_extract = after.values.get("extract_airflow")

        def numeric(value: object) -> bool:
            return isinstance(value, (int, float)) and not isinstance(value, bool)

        supply_pair = numeric(before_supply) and numeric(after_supply)
        extract_pair = numeric(before_extract) and numeric(after_extract)
        observation: dict[str, object] = {
            "available": numeric(after_supply) and numeric(after_extract),
            "sampled_after_readback": True,
            "physical_signal": "airflow_m3h_not_rpm",
            "after_supply_airflow_m3h": after_supply,
            "after_extract_airflow_m3h": after_extract,
        }
        if supply_pair:
            observation["before_supply_airflow_m3h"] = before_supply
            observation["supply_changed"] = before_supply != after_supply
        if extract_pair:
            observation["before_extract_airflow_m3h"] = before_extract
            observation["extract_changed"] = before_extract != after_extract
        return observation

    @staticmethod
    def _airflow_changed(before: DeviceState, after: DeviceState) -> bool:
        """Return whether either measured airflow changed between snapshots."""

        for key in ("supply_airflow", "extract_airflow"):
            previous = before.values.get(key)
            current = after.values.get(key)
            if (
                isinstance(previous, (int, float))
                and not isinstance(previous, bool)
                and isinstance(current, (int, float))
                and not isinstance(current, bool)
                and previous != current
            ):
                return True
        return False

    @staticmethod
    def _airflow_sample(state: DeviceState) -> dict[str, object]:
        """Serialize the small physical-response sample kept in a command result."""

        return {
            "captured_at": state.captured_at.isoformat(),
            "revision": state.revision,
            "online": state.online,
            "supply_airflow_m3h": state.values.get("supply_airflow"),
            "extract_airflow_m3h": state.values.get("extract_airflow"),
        }

    async def _observe_airflow_after_command(
        self,
        command_type: str,
        before: DeviceState,
    ) -> dict[str, object] | None:
        """Optionally sample delayed fan response after a confirmed register write.

        Register read-back proves that the controller accepted the setpoint.  A
        separate airflow window is deliberately optional because some units
        react immediately while others need several seconds, and the vendor
        protocol exposes airflow rather than RPM.
        """

        observation = self._airflow_observation(command_type, before, self.state)
        if observation is None or self._airflow_observation_seconds <= 0:
            return observation

        loop = asyncio.get_running_loop()
        started = loop.time()
        samples = [self._airflow_sample(self.state)]
        changed = self._airflow_changed(before, self.state)
        while not changed:
            elapsed = loop.time() - started
            remaining = self._airflow_observation_seconds - elapsed
            if remaining <= 0 or not self._started:
                break
            await asyncio.sleep(min(self._airflow_observation_interval_seconds, remaining))
            if not self._started:
                break
            current = await self.refresh()
            samples.append(self._airflow_sample(current))
            changed = self._airflow_changed(before, current)

        final_observation = self._airflow_observation(command_type, before, self.state)
        if final_observation is None:
            return None
        final_observation["observation_window_seconds"] = round(loop.time() - started, 3)
        final_observation["changed_within_window"] = changed
        final_observation["samples"] = samples
        return final_observation

    async def execute_intent(
        self,
        intent: ControlIntent,
        *,
        request_id: str | None = None,
        expected_revision: int | None = None,
    ) -> dict[str, object]:
        """Execute a selected policy intent through the normal command path."""

        return await self.execute_command(
            intent.command_type,
            intent.parameters,
            source=intent.source,
            request_id=request_id,
            expected_revision=expected_revision,
        )

    async def execute_policy_decision(
        self,
        decision: ControlPolicyDecision,
        *,
        request_id: str | None = None,
        expected_revision: int | None = None,
    ) -> dict[str, object]:
        """Execute only the arbiter's selected intent, never a rejected one."""

        if decision.selected is None:
            raise ValueError(f"policy decision has no command: {decision.reason}")
        return await self.execute_intent(
            decision.selected,
            request_id=request_id,
            expected_revision=expected_revision,
        )

    def _cache_is_fresh(self, captured_at: datetime) -> bool:
        age = (datetime.now(UTC) - captured_at).total_seconds()
        return age >= 0 and age <= self._command_cache_ttl_seconds

    async def _load_cached_command(
        self, request_id: str
    ) -> tuple[str, dict[str, object], datetime] | None:
        cached = self._command_cache.get(request_id)
        if cached is not None:
            if self._cache_is_fresh(cached[2]):
                return cached
            self._command_cache.pop(request_id, None)

        if self.store is None:
            return None
        loader = getattr(self.store, "get_command", None)
        if not callable(loader):
            return None
        try:
            stored = await loader(request_id)
        except Exception as exc:  # pragma: no cover - storage failure dependent
            _LOGGER.warning("unable to load persisted command cache: %s", exc)
            return None
        if not isinstance(stored, Mapping):
            return None
        fingerprint = stored.get("fingerprint")
        captured_raw = stored.get("captured_at")
        response_raw = stored.get("response")
        if not isinstance(fingerprint, str) or not isinstance(captured_raw, str):
            return None
        if not isinstance(response_raw, Mapping):
            return None
        try:
            captured_at = datetime.fromisoformat(captured_raw.replace("Z", "+00:00"))
        except ValueError:
            return None
        if captured_at.tzinfo is None:
            captured_at = captured_at.replace(tzinfo=UTC)
        response = {str(key): value for key, value in response_raw.items()}
        if not self._cache_is_fresh(captured_at):
            return None
        entry = (fingerprint, response, captured_at)
        self._command_cache[request_id] = entry
        return entry

    async def _persist_cached_command(
        self,
        request_id: str,
        fingerprint: str,
        response: Mapping[str, object],
        captured_at: datetime,
    ) -> None:
        if self.store is None:
            return
        recorder = getattr(self.store, "record_command", None)
        if not callable(recorder):
            return
        try:
            await recorder(
                request_id,
                fingerprint,
                response,
                captured_at=captured_at.isoformat(),
            )
        except Exception as exc:  # pragma: no cover - storage failure dependent
            _LOGGER.warning("unable to persist command cache: %s", exc)

    async def execute_command(
        self,
        command_type: str,
        parameters: Mapping[str, object],
        *,
        source: str = "gateway",
        request_id: str | None = None,
        expected_revision: int | None = None,
    ) -> dict[str, object]:
        """Execute one typed command with serialization and optional idempotency."""

        if not self._started:
            raise GatewayNotStarted("gateway must be started before sending commands")
        if not isinstance(command_type, str) or not command_type.strip():
            raise ValueError("command type cannot be empty")
        if request_id is not None:
            if not isinstance(request_id, str) or not request_id.strip():
                raise ValueError("request_id must be a non-empty string")
            if len(request_id) > 128:
                raise ValueError("request_id cannot exceed 128 characters")
        if expected_revision is not None and (
            isinstance(expected_revision, bool) or not isinstance(expected_revision, int)
        ):
            raise TypeError("expected_revision must be an integer")

        fingerprint = self._command_fingerprint(command_type, parameters)
        async with self._command_lock:
            if request_id is not None:
                cached = await self._load_cached_command(request_id)
                if cached is not None:
                    cached_fingerprint, cached_response, _captured_at = cached
                    if cached_fingerprint != fingerprint:
                        raise CommandConflict("request_id was already used for a different command")
                    replay = dict(cached_response)
                    replay["replayed"] = True
                    return replay

            if expected_revision is not None and self.state.revision != expected_revision:
                raise CommandConflict(
                    f"expected state revision {expected_revision}, current is {self.state.revision}"
                )

            before_state = self.state

            if command_type == "set_fan_speed":
                result = await self.set_fan_speed(
                    self._parse_int(parameters["percentage"], "percentage"), source=source
                )
            elif command_type == "set_temporary_fan_speed":
                result = await self.set_temporary_fan_speed(
                    self._parse_int(parameters["percentage"], "percentage"), source=source
                )
            elif command_type == "activate_temporary_mode":
                result = await self.activate_temporary_mode(
                    self._parse_int(parameters["percentage"], "percentage"), source=source
                )
            elif command_type == "set_mode":
                raw_mode = parameters["mode"]
                parsed_mode = (
                    AirPackMode[raw_mode.upper()]
                    if isinstance(raw_mode, str) and not raw_mode.isdecimal()
                    else AirPackMode(self._parse_int(raw_mode, "mode"))
                )
                if parsed_mode is AirPackMode.TEMPORARY:
                    current_percentage = self._parse_int(
                        self.state.values["temporary_fan_speed"],
                        "temporary_fan_speed",
                    )
                    result = await self.activate_temporary_mode(
                        current_percentage,
                        source=source,
                    )
                else:
                    result = await self.set_mode(parsed_mode, source=source)
            elif command_type == "set_special_mode":
                raw_mode = parameters["mode"]
                selectable_names = {
                    name: mode for mode, name in USER_SELECTABLE_SPECIAL_MODES.items()
                }
                if isinstance(raw_mode, str) and not raw_mode.isdecimal():
                    parsed_special_mode = selectable_names.get(raw_mode.lower())
                    if parsed_special_mode is None:
                        raise ValueError(
                            "special mode is observable but not safe for manual activation"
                        )
                else:
                    parsed_special_mode = SpecialMode(self._parse_int(raw_mode, "mode"))
                result = await self.set_special_mode(parsed_special_mode, source=source)
            elif command_type == "set_comfort_mode":
                raw_mode = parameters["mode"]
                parsed_comfort_mode = (
                    ComfortPreference[raw_mode.upper()]
                    if isinstance(raw_mode, str) and not raw_mode.isdecimal()
                    else ComfortPreference(self._parse_int(raw_mode, "mode"))
                )
                result = await self.set_comfort_mode(parsed_comfort_mode, source=source)
            elif command_type == "set_power":
                result = await self.set_power(
                    self._parse_bool(parameters["enabled"]), source=source
                )
            else:
                raise ValueError(f"unsupported typed command: {command_type}")

            result_payload = result.to_dict()
            airflow_observation = await self._observe_airflow_after_command(
                command_type,
                before_state,
            )
            if airflow_observation is not None:
                result_payload["airflow_observation"] = airflow_observation
            response: dict[str, object] = {
                "status": "confirmed",
                "request_id": request_id,
                "replayed": False,
                "result": result_payload,
                "state": self.state.to_dict(),
            }
            if request_id is not None:
                captured_at = datetime.now(UTC)
                self._command_cache[request_id] = (fingerprint, response, captured_at)
                await self._persist_cached_command(request_id, fingerprint, response, captured_at)
                if len(self._command_cache) > self._command_cache_limit:
                    self._command_cache.pop(next(iter(self._command_cache)))
            return response
