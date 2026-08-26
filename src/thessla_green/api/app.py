"""Small FastAPI surface for the first control slice.

The module remains import-safe without FastAPI installed so domain and protocol
tests can run before deployment dependencies are provisioned.
"""

import asyncio
import hmac
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from thessla_green.application.control import (
    USER_SELECTABLE_SPECIAL_MODES,
    AirPackMode,
    ComfortPreference,
    DeviceControlError,
)
from thessla_green.application.factory import build_gateway
from thessla_green.application.gateway import GatewayNotStarted, GatewayService
from thessla_green.config import Settings
from thessla_green.discovery.candidates import enumerate_serial_ports
from thessla_green.discovery.service import DiscoveryService


def create_app(
    service: GatewayService | None = None,
    *,
    api_token: str | None = None,
    cors_origins: Sequence[str] = (),
    poll_interval_seconds: float = 5.0,
) -> Any:
    try:
        from fastapi import (
            Depends,
            FastAPI,
            Header,
            HTTPException,
            Query,
            WebSocket,
            WebSocketDisconnect,
            WebSocketException,
        )
        from fastapi.responses import FileResponse
        from fastapi.staticfiles import StaticFiles
        from starlette.middleware.cors import CORSMiddleware
        from starlette.requests import HTTPConnection

        from thessla_green.api.schemas import CommandRequest, CommandResponse
    except ImportError as exc:  # pragma: no cover - depends on deployment environment
        raise RuntimeError(
            "install the 'api' optional dependencies before starting FastAPI"
        ) from exc

    normalized_cors_origins = tuple(
        origin.strip() for origin in cors_origins if origin.strip()
    )
    if "*" in normalized_cors_origins:
        raise ValueError("cors_origins must contain explicit origins, not '*'")

    @asynccontextmanager
    async def lifespan(_app: Any) -> AsyncIterator[None]:
        if service is not None:
            await service.start()
            service.start_polling(poll_interval_seconds)
        try:
            yield
        finally:
            if service is not None:
                await service.stop()

    async def authorize(connection: HTTPConnection) -> None:
        if not api_token:
            return
        scheme, _, supplied = connection.headers.get("authorization", "").partition(" ")
        if scheme.lower() != "bearer" or not hmac.compare_digest(supplied, api_token):
            if connection.scope["type"] == "websocket":
                raise WebSocketException(code=1008, reason="invalid or missing bearer token")
            raise HTTPException(status_code=401, detail="invalid or missing bearer token")

    app = FastAPI(
        title="Thessla Green Gateway",
        version="0.3.1",
        description="Local-first, read-confirmed control API for AirPack units.",
        lifespan=lifespan,
        dependencies=[Depends(authorize)] if api_token else None,
    )
    if normalized_cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(normalized_cors_origins),
            allow_credentials=False,
            allow_methods=["GET", "POST", "OPTIONS"],
            allow_headers=["Authorization", "Content-Type", "X-Thessla-Source"],
        )

    web_dir = Path(__file__).resolve().parent.parent / "web"
    if web_dir.is_dir():
        app.mount("/ui", StaticFiles(directory=str(web_dir), html=True), name="ui")

        @app.get("/", include_in_schema=False)
        async def dashboard() -> Any:
            return FileResponse(web_dir / "index.html")

    def configured_service() -> GatewayService:
        if service is None:
            raise HTTPException(status_code=503, detail="gateway is not configured")
        return service

    def normalize_source(value: str | None) -> str:
        allowed = {"api", "mobile", "home_assistant", "automation", "cli"}
        source = (value or "api").strip().lower()
        return source if source in allowed else "api"

    def selected_device(device_id: str) -> GatewayService:
        gateway = configured_service()
        identity = gateway.state.identity
        if identity is None or identity.stable_id != device_id:
            raise HTTPException(status_code=404, detail="device was not found")
        return gateway

    async def execute_command(
        gateway: GatewayService,
        payload: CommandRequest,
        *,
        source: str = "api",
    ) -> CommandResponse:
        try:
            response = await gateway.execute_command(
                payload.type,
                payload.parameters,
                source=source,
                request_id=payload.request_id,
                expected_revision=payload.expected_revision,
            )
        except KeyError as exc:
            raise HTTPException(
                status_code=422, detail=f"missing parameter: {exc.args[0]}"
            ) from exc
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except GatewayNotStarted as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except DeviceControlError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return CommandResponse.model_validate(response)

    @app.get("/health/live")
    async def live() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/ready")
    async def ready() -> dict[str, object]:
        if service is None:
            return {"status": "not_configured", "ready": False}
        state = service.state
        return {"status": "ready" if state.online else "device_offline", "ready": state.online}

    @app.get("/api/v1/state")
    async def state() -> dict[str, object]:
        return configured_service().state.to_dict()

    @app.get("/api/v1/capabilities")
    async def capabilities() -> dict[str, object]:
        return configured_service().state.capabilities.to_dict()

    @app.get("/api/v1/devices")
    async def devices() -> dict[str, object]:
        gateway = configured_service()
        identity = gateway.state.identity
        return {"devices": [identity.to_dict()] if identity is not None else []}

    @app.get("/api/v1/devices/{device_id}")
    async def device(device_id: str) -> dict[str, object]:
        gateway = selected_device(device_id)
        return {
            "identity": gateway.state.identity.to_dict() if gateway.state.identity else None,
            "state": gateway.state.to_dict(),
        }

    @app.get("/api/v1/devices/{device_id}/state")
    async def device_state(device_id: str) -> dict[str, object]:
        return selected_device(device_id).state.to_dict()

    @app.get("/api/v1/devices/{device_id}/capabilities")
    async def device_capabilities(device_id: str) -> dict[str, object]:
        return selected_device(device_id).state.capabilities.to_dict()

    @app.get("/api/v1/control/options")
    async def control_options() -> dict[str, object]:
        return {
            "fan_speed": {"minimum": 10, "maximum": 100, "unit": "%"},
            "temporary_fan_speed": {"minimum": 10, "maximum": 100, "unit": "%"},
            "temporary_mode": {
                "duration_source": "airpack_controller_settings",
                "duration_writable": False,
                "activation": "atomic_register_block_4400_4402",
            },
            "modes": {mode.name.lower(): int(mode) for mode in AirPackMode},
            "comfort_modes": {
                mode.name.lower(): int(mode) for mode in ComfortPreference
            },
            "special_modes": {
                name: int(mode) for mode, name in USER_SELECTABLE_SPECIAL_MODES.items()
            },
        }

    @app.get("/api/v1/audit")
    async def audit(limit: int = Query(default=50, ge=1, le=500)) -> dict[str, object]:
        events = await configured_service().stored_audit(limit=limit)
        return {"events": list(events)}

    @app.get("/api/v1/devices/{device_id}/telemetry")
    async def telemetry(
        device_id: str,
        limit: int = Query(default=100, ge=1, le=1000),
        from_timestamp: str | None = Query(default=None, alias="from"),
        until_timestamp: str | None = Query(default=None, alias="to"),
    ) -> dict[str, object]:
        gateway = selected_device(device_id)
        points = await gateway.telemetry(
            limit=limit,
            since=from_timestamp,
            until=until_timestamp,
        )
        return {"points": list(points)}

    @app.get("/api/v1/discovery/serial-ports")
    async def serial_ports() -> dict[str, object]:
        return {"ports": [port.to_dict() for port in enumerate_serial_ports()]}

    @app.post("/api/v1/discovery")
    async def discovery() -> dict[str, object]:
        if service is not None:
            raise HTTPException(
                status_code=409,
                detail="stop the selected gateway before running discovery on its bus",
            )
        results = await DiscoveryService(Settings.from_env()).discover()
        return {"results": [result.to_dict() for result in results]}

    @app.post("/api/v1/commands", response_model=CommandResponse)
    async def command(
        payload: CommandRequest,
        x_thessla_source: str | None = Header(default=None),
    ) -> Any:
        return await execute_command(
            configured_service(), payload, source=normalize_source(x_thessla_source)
        )

    @app.post("/api/v1/devices/{device_id}/commands", response_model=CommandResponse)
    async def device_command(
        device_id: str,
        payload: CommandRequest,
        x_thessla_source: str | None = Header(default=None),
    ) -> Any:
        return await execute_command(
            selected_device(device_id),
            payload,
            source=normalize_source(x_thessla_source),
        )

    @app.websocket("/api/v1/events")
    async def events(websocket: WebSocket) -> None:
        # Authenticate before accepting the upgrade.  This keeps an invalid
        # client from starting a state-stream loop even when app-level HTTP
        # dependencies are not applied by the ASGI server.
        await authorize(websocket)
        await websocket.accept()
        if service is None:
            await websocket.send_json({"type": "error", "detail": "gateway is not configured"})
            await websocket.close(code=1013)
            return
        last_revision = -1
        try:
            while True:
                state_snapshot = service.state
                if state_snapshot.revision != last_revision:
                    await websocket.send_json(
                        {
                            "type": "state",
                            "sequence": state_snapshot.revision,
                            "data": state_snapshot.to_dict(),
                        }
                    )
                    last_revision = state_snapshot.revision
                await asyncio.sleep(1)
        except WebSocketDisconnect:
            return

    return app


try:  # Allow importing the package in a minimal unit-test environment.
    _settings = Settings.from_env()
    app = create_app(
        build_gateway(_settings),
        api_token=_settings.api_token,
        cors_origins=_settings.api_cors_origins,
        poll_interval_seconds=_settings.poll_interval_seconds,
    )
except RuntimeError:
    app = None
