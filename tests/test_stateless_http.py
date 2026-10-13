"""Exercise the configured transport with real JSON-RPC HTTP requests."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager

import pytest
from starlette.testclient import TestClient

from fxhoudinimcp import _sdk

# SDK 1 serves HTTP with sessions: run_server keeps it stateful.
pytestmark = pytest.mark.skipif(not _sdk._SDK_V2, reason="stateless HTTP is SDK 2 only")

LIFESPANS = []


@pytest.fixture
def http_client(monkeypatch):
    LIFESPANS.clear()

    @asynccontextmanager
    async def lifespan(_server):
        LIFESPANS.append(1)
        yield {}

    server = _sdk.build_server(
        name="HTTP regression", instructions="", lifespan=lifespan, version="1.0"
    )

    @server.tool()
    async def echo(value: str, ctx: _sdk.Context) -> str:
        await _sdk.report_progress(ctx, 1, 2, "working")
        return value

    apps = []

    def run(*, transport, **options):
        assert transport == "streamable-http"
        apps.append(server.streamable_http_app(**options))

    monkeypatch.setattr(server, "run", run)
    _sdk.run_server(server, transport="streamable-http")
    with TestClient(apps[0], base_url="http://127.0.0.1:8000") as client:
        yield client


def rpc_response(client, method, params, *, version="2025-06-18", request_id=1):
    headers = {
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": version,
        "Mcp-Method": method,
    }
    if "name" in params:
        headers["Mcp-Name"] = params["name"]
    response = client.post(
        "/mcp",
        headers=headers,
        json={"jsonrpc": "2.0", "id": request_id, "method": method, "params": params},
    )
    assert response.status_code == 200, response.text
    assert "mcp-session-id" not in response.headers
    return response


def rpc(client, method, params, **options):
    response = rpc_response(client, method, params, **options)
    if response.headers["content-type"].startswith("application/json"):
        return response.json()
    messages = [
        json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")
    ]
    return next(
        message for message in messages if message.get("id") == options.get("request_id", 1)
    )


def test_legacy_clients_need_no_session_id(http_client):
    for name in ("first client", "second client"):
        initialized = rpc(
            http_client,
            "initialize",
            {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": name, "version": "1.0"},
            },
        )
        assert initialized["result"]["protocolVersion"] == "2025-06-18"
        tools = rpc(http_client, "tools/list", {})
        assert [tool["name"] for tool in tools["result"]["tools"]] == ["echo"]
        called = rpc(http_client, "tools/call", {"name": "echo", "arguments": {"value": name}})
        assert called["result"]["content"] == [{"type": "text", "text": name}]


def test_the_lifespan_is_entered_once_not_per_request(http_client):
    """It holds the Houdini bridge: once per request, connect_houdini would not last."""
    for request_id in (1, 2, 3):
        rpc(
            http_client,
            "initialize",
            {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "client", "version": "1.0"},
            },
            request_id=request_id,
        )
    assert len(LIFESPANS) == 1


def test_modern_client_discovers_and_calls_without_initialize(http_client):
    meta = {
        "io.modelcontextprotocol/protocolVersion": "2026-07-28",
        "io.modelcontextprotocol/clientCapabilities": {},
    }
    discovery = rpc(http_client, "server/discover", {"_meta": meta}, version="2026-07-28")
    assert "2026-07-28" in discovery["result"]["supportedVersions"]
    for value in ("first request", "independent request"):
        called = rpc(
            http_client,
            "tools/call",
            {"_meta": meta, "name": "echo", "arguments": {"value": value}},
            version="2026-07-28",
        )
        assert called["result"]["content"] == [{"type": "text", "text": value}]


def test_request_scoped_sse_preserves_progress(http_client):
    response = rpc_response(
        http_client,
        "tools/call",
        {"_meta": {"progressToken": "cook-42"}, "name": "echo", "arguments": {"value": "done"}},
    )
    assert response.headers["content-type"].startswith("text/event-stream")
    messages = [
        json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")
    ]
    progress = next(
        message for message in messages if message.get("method") == "notifications/progress"
    )
    assert progress["params"] == {
        "progressToken": "cook-42",
        "progress": 1.0,
        "total": 2.0,
        "message": "working",
    }
    final = next(message for message in messages if message.get("id") == 1)
    assert final["result"]["content"] == [{"type": "text", "text": "done"}]
