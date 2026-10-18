"""Exercise the real HTTP session stack with all device startup isolated."""

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from unittest.mock import AsyncMock, Mock

import pytest
from fastmcp.server import http
from httpx import ASGITransport, AsyncClient

import mcp_venus_os.server as server
from mcp_venus_os.config import ServerConfig

HEADERS = {"Accept": "application/json, text/event-stream"}
INITIALIZE = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-03-26",
        "capabilities": {},
        "clientInfo": {"name": "session-regression", "version": "1"},
    },
}


@pytest.fixture
def http_client(
    monkeypatch: pytest.MonkeyPatch,
) -> Callable[[float], AbstractAsyncContextManager[AsyncClient]]:
    """Keep production routing/session handling; deny device access and shorten limits."""
    config = ServerConfig(transport_backend="dbus")
    monkeypatch.setattr(server, "get_config", lambda: config)
    monkeypatch.setattr(server, "_dbus_client", None)
    monkeypatch.setattr(server, "_mqtt_client", None)
    monkeypatch.setattr(server, "close_ssh_client", AsyncMock())
    monkeypatch.setattr(server.mcp, "auth", None)
    for name in ("get_dbus_client", "get_mqtt_client", "get_ssh_client"):
        monkeypatch.setattr(
            server, name, Mock(side_effect=AssertionError("Device access forbidden"))
        )

    original_init: Callable[..., None] = http.FastMCPStreamableHTTPSessionManager.__init__

    @asynccontextmanager
    async def client(idle_timeout: float = 30) -> AsyncIterator[AsyncClient]:
        def initialize(
            self: http.FastMCPStreamableHTTPSessionManager, *args: object, **kwargs: object
        ) -> None:
            original_init(self, *args, **kwargs)
            # Verify the actual inherited defaults before reducing them for fast tests.
            assert self.max_sessions == 10_000
            assert self.session_idle_timeout == 1_800
            assert self.stateless is False
            self.max_sessions = 1
            self.session_idle_timeout = idle_timeout

        monkeypatch.setattr(http.FastMCPStreamableHTTPSessionManager, "__init__", initialize)
        app = server.mcp.http_app(json_response=True)
        async with (
            app.router.lifespan_context(app),
            AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://127.0.0.1:8000",
                headers=HEADERS,
            ) as connection,
        ):
            yield connection

    return client


@pytest.mark.asyncio
async def test_full_pool_recovers_after_delete(
    http_client: Callable[[float], AbstractAsyncContextManager[AsyncClient]],
) -> None:
    async with http_client(30) as client:
        first = await client.post("/mcp", json=INITIALIZE)
        assert first.status_code == 200
        session = first.headers["mcp-session-id"]
        assert (await client.post("/mcp", json=INITIALIZE)).status_code == 503
        assert (await client.delete("/mcp", headers={"mcp-session-id": session})).status_code == 200
        replacement = await client.post("/mcp", json=INITIALIZE)
        assert replacement.status_code == 200
        assert replacement.headers["mcp-session-id"] != session


@pytest.mark.asyncio
async def test_expiry_invalidates_session_and_releases_capacity(
    http_client: Callable[[float], AbstractAsyncContextManager[AsyncClient]],
) -> None:
    async with http_client(0.05) as client:
        first = await client.post("/mcp", json=INITIALIZE)
        assert first.status_code == 200
        session = first.headers["mcp-session-id"]
        await asyncio.sleep(0.2)
        expired = await client.post(
            "/mcp",
            headers={"mcp-session-id": session},
            json={"jsonrpc": "2.0", "id": 2, "method": "ping"},
        )
        assert expired.status_code == 404
        assert (await client.post("/mcp", json=INITIALIZE)).status_code == 200


@pytest.mark.asyncio
async def test_rejected_opening_request_releases_capacity(
    http_client: Callable[[float], AbstractAsyncContextManager[AsyncClient]],
) -> None:
    async with http_client(30) as client:
        rejected = await client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "ping"})
        assert rejected.status_code == 400
        assert (await client.post("/mcp", json=INITIALIZE)).status_code == 200
