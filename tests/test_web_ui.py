from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from starlette.websockets import WebSocketDisconnect

from thessla_green.api.app import create_app
from thessla_green.api.schemas import CommandRequest
from thessla_green.application.gateway import GatewayService
from thessla_green.protocol.simulator import SimulatedAirPackTransport


def test_local_dashboard_assets_are_packaged() -> None:
    web_dir = Path(__file__).parents[1] / "src" / "thessla_green" / "web"
    for name in ("index.html", "app.js", "styles.css", "favicon.svg"):
        assert (web_dir / name).is_file()
    assert "/api/v1/state" in (web_dir / "app.js").read_text(encoding="utf-8")
    assert "set_fan_speed" in (web_dir / "app.js").read_text(encoding="utf-8")
    assert "activate_temporary_mode" in (web_dir / "app.js").read_text(encoding="utf-8")
    assert "refreshAfterConflict" in (web_dir / "app.js").read_text(encoding="utf-8")
    assert "refreshSnapshotForCommand" in (web_dir / "app.js").read_text(encoding="utf-8")
    assert "mode-description" in (web_dir / "index.html").read_text(encoding="utf-8")
    assert "Chwilowy" in (web_dir / "index.html").read_text(encoding="utf-8")
    assert "/ui/app.js?v=0.2.1" in (web_dir / "index.html").read_text(encoding="utf-8")
    assert "airflow_observation" in (web_dir / "app.js").read_text(encoding="utf-8")
    assert "run-discovery" in (web_dir / "index.html").read_text(encoding="utf-8")
    assert "/api/v1/discovery" in (web_dir / "app.js").read_text(encoding="utf-8")


def test_fastapi_mounts_the_local_dashboard() -> None:
    app = create_app()
    paths = {route.path for route in app.routes}

    assert "/" in paths
    assert "/ui" in paths
    assert "/api/v1/state" in paths
    assert "/api/v1/commands" in paths
    assert "/api/v1/devices/{device_id}/telemetry" in paths


def test_websocket_contract_includes_monotonic_sequence() -> None:
    source = Path(__file__).parents[1] / "src" / "thessla_green" / "api" / "app.py"
    text = source.read_text(encoding="utf-8")
    assert '"sequence": state_snapshot.revision' in text


def test_websocket_state_event_contains_sequence_and_snapshot() -> None:
    transport = SimulatedAirPackTransport()
    service = GatewayService(transport, endpoint=transport.endpoint, unit_id=transport.unit_id)
    app = create_app(service)
    websocket_route = next(route for route in app.routes if route.path == "/api/v1/events")

    class FakeWebSocket:
        scope: dict[str, object] = {"type": "websocket"}
        headers: dict[str, str] = {}

        def __init__(self) -> None:
            self.messages: list[dict[str, object]] = []

        async def accept(self) -> None:
            return None

        async def send_json(self, payload: dict[str, object]) -> None:
            self.messages.append(payload)
            raise WebSocketDisconnect(code=1000)

    websocket = FakeWebSocket()
    asyncio.run(websocket_route.endpoint(websocket))

    assert websocket.messages
    assert websocket.messages[0]["type"] == "state"
    assert websocket.messages[0]["sequence"] == service.state.revision
    assert isinstance(websocket.messages[0]["data"], dict)


def test_cors_is_opt_in_and_restricted_to_configured_origins() -> None:
    assert create_app().user_middleware == []

    app = create_app(cors_origins=("https://phone.example", "http://localhost:8080"))
    cors = next(
        middleware
        for middleware in app.user_middleware
        if middleware.cls.__name__ == "CORSMiddleware"
    )

    assert cors.kwargs["allow_origins"] == [
        "https://phone.example",
        "http://localhost:8080",
    ]
    assert cors.kwargs["allow_credentials"] is False
    assert cors.kwargs["allow_methods"] == ["GET", "POST", "OPTIONS"]


def test_fastapi_rejects_wildcard_cors_origin() -> None:
    with pytest.raises(ValueError, match="explicit origins"):
        create_app(cors_origins=("*",))


def test_command_contract_is_present_in_openapi() -> None:
    schema = create_app().openapi()
    command = schema["paths"]["/api/v1/commands"]["post"]
    request_schema = command["requestBody"]["content"]["application/json"]["schema"]
    response_schema = command["responses"]["200"]["content"]["application/json"]["schema"]

    assert request_schema["$ref"].endswith("/CommandRequest")
    assert response_schema["$ref"].endswith("/CommandResponse")
    properties = schema["components"]["schemas"]["CommandRequest"]["properties"]
    assert {"type", "parameters", "request_id", "expected_revision"} <= properties.keys()


def test_versioned_openapi_artifact_tracks_runtime_routes() -> None:
    artifact_path = Path(__file__).parents[1] / "docs" / "openapi-v1.json"
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    runtime = create_app().openapi()

    assert artifact["info"]["version"] == runtime["info"]["version"] == "0.2.1"
    assert set(artifact["paths"]) == set(runtime["paths"])
    assert artifact["components"]["schemas"]["CommandRequest"] == runtime["components"][
        "schemas"
    ]["CommandRequest"]


def test_command_request_rejects_unknown_fields_and_boolean_revision() -> None:
    with pytest.raises(ValueError):
        CommandRequest.model_validate(
            {"type": "set_fan_speed", "parameters": {}, "unexpected": True}
        )
    with pytest.raises(ValueError):
        CommandRequest(type="set_fan_speed", parameters={}, expected_revision=True)


def test_fastapi_lifecycle_confirms_a_simulated_command() -> None:
    transport = SimulatedAirPackTransport()
    service = GatewayService(transport, endpoint=transport.endpoint, unit_id=transport.unit_id)
    app = create_app(service, poll_interval_seconds=60)

    async def run() -> None:
        async with app.router.lifespan_context(app):
            status, _, state_payload = await _asgi_request(app, "GET", "/api/v1/state")
            assert status == 200
            state = json.loads(state_payload)
            device_id = state["identity"]["stable_id"]

            status, _, command_payload = await _asgi_request(
                app,
                "POST",
                f"/api/v1/devices/{device_id}/commands",
                {
                    "type": "set_mode",
                    "parameters": {"mode": "manual"},
                    "request_id": "contract-test-mode",
                    "expected_revision": state["revision"],
                },
            )
            assert status == 200
            body = json.loads(command_payload)
            assert body["status"] == "confirmed"
            assert body["result"]["confirmed"] is True
            assert body["state"]["values"]["mode"] == 1

    asyncio.run(run())


async def _asgi_request(
    app: Any,
    method: str,
    path: str,
    payload: dict[str, object] | None = None,
) -> tuple[int, list[tuple[bytes, bytes]], str]:
    body = json.dumps(payload).encode() if payload is not None else b""
    messages = [
        {"type": "http.request", "body": body, "more_body": False},
    ]
    sent: list[dict[str, Any]] = []

    async def receive() -> dict[str, object]:
        if messages:
            return messages.pop(0)
        return {"type": "http.disconnect"}

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    headers = [(b"host", b"testserver")]
    if payload is not None:
        headers.append((b"content-type", b"application/json"))
    await app(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": method,
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "headers": headers,
            "client": ("testclient", 50000),
            "server": ("testserver", 80),
        },
        receive,
        send,
    )
    start = next(message for message in sent if message["type"] == "http.response.start")
    body_bytes = b"".join(
        message.get("body", b"")
        for message in sent
        if message["type"] == "http.response.body"
    )
    return int(start["status"]), list(start.get("headers", [])), body_bytes.decode()
