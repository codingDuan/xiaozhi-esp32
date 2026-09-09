# Plush Toy Text Test Tool Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Provide a loopback-only text CLI that sends real MCP actions to the currently online plush-toy device.

**Architecture:** `WebSocketServer` keeps the currently live `ConnectionHandler` objects keyed by device ID.  An aiohttp handler receives a narrow, loopback-only device-MCP request and delegates to the existing `call_mcp_tool()` function.  A dependency-free CLI in the firmware repository maps ergonomic plush-toy commands to that handler, including a deterministic regression sequence.

**Tech Stack:** Python 3.10+, aiohttp, asyncio, unittest/pytest, existing device MCP protocol.

---

### Task 1: Track active device MCP connections

**Files:**
- Modify: `/Users/lianjia/Workspace/xiaozhi-esp32-server/main/xiaozhi-server/core/websocket_server.py`
- Create: `/Users/lianjia/Workspace/xiaozhi-esp32-server/main/xiaozhi-server/tests/core/test_websocket_server.py`

- [ ] **Step 1: Write failing registry tests**

```python
from core.websocket_server import WebSocketServer


def make_server():
    server = WebSocketServer.__new__(WebSocketServer)
    server.active_connections = {}
    return server


def test_register_and_lookup_active_connection():
    server = make_server()
    handler = object()
    server.register_connection("device-1", handler)
    assert server.get_connection("device-1") is handler
    assert server.list_connections() == {"device-1": handler}


def test_unregister_only_removes_the_matching_connection():
    server = make_server()
    first, second = object(), object()
    server.register_connection("device-1", first)
    server.register_connection("device-1", second)
    server.unregister_connection("device-1", first)
    assert server.get_connection("device-1") is second
    server.unregister_connection("device-1", second)
    assert server.get_connection("device-1") is None
```

- [ ] **Step 2: Run the test to verify red state**

Run: `cd /Users/lianjia/Workspace/xiaozhi-esp32-server/main/xiaozhi-server && pytest tests/core/test_websocket_server.py -q`

Expected: FAIL because `register_connection` does not exist.

- [ ] **Step 3: Implement the minimal registry and lifecycle hooks**

```python
# WebSocketServer.__init__
self.active_connections: dict[str, ConnectionHandler] = {}

def register_connection(self, device_id: str, handler: ConnectionHandler) -> None:
    self.active_connections[device_id] = handler

def unregister_connection(self, device_id: str, handler: ConnectionHandler) -> None:
    if self.active_connections.get(device_id) is handler:
        self.active_connections.pop(device_id, None)

def get_connection(self, device_id: str) -> ConnectionHandler | None:
    return self.active_connections.get(device_id)

def list_connections(self) -> dict[str, ConnectionHandler]:
    return dict(self.active_connections)
```

In `_handle_connection`, read the authenticated `device-id` header after creating the handler; register it before `await handler.handle_connection(websocket)` and unregister the same handler in `finally`.

- [ ] **Step 4: Run the registry test**

Run: `cd /Users/lianjia/Workspace/xiaozhi-esp32-server/main/xiaozhi-server && pytest tests/core/test_websocket_server.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the server registry**

```bash
git -C /Users/lianjia/Workspace/xiaozhi-esp32-server add main/xiaozhi-server/core/websocket_server.py main/xiaozhi-server/tests/core/test_websocket_server.py
git -C /Users/lianjia/Workspace/xiaozhi-esp32-server commit -m "feat: track active device MCP connections"
```

### Task 2: Add a loopback-only device MCP debug bridge

**Files:**
- Create: `/Users/lianjia/Workspace/xiaozhi-esp32-server/main/xiaozhi-server/core/api/device_mcp_debug_handler.py`
- Modify: `/Users/lianjia/Workspace/xiaozhi-esp32-server/main/xiaozhi-server/core/http_server.py`
- Create: `/Users/lianjia/Workspace/xiaozhi-esp32-server/main/xiaozhi-server/tests/core/api/test_device_mcp_debug_handler.py`

- [ ] **Step 1: Write failing handler tests**

```python
import pytest
from core.api.device_mcp_debug_handler import DeviceMcpDebugHandler


class FakeMcpClient:
    def has_tool(self, name): return name == "self.limbs.hug"


class FakeConnection:
    mcp_client = FakeMcpClient()


class FakeServer:
    def __init__(self): self.connection = FakeConnection()
    def list_connections(self): return {"toy-1": self.connection}
    def get_connection(self, device_id): return self.connection if device_id == "toy-1" else None


@pytest.mark.asyncio
async def test_rejects_non_loopback_request(make_mocked_request):
    handler = DeviceMcpDebugHandler(FakeServer())
    request = make_mocked_request("GET", "/debug/device-mcp/devices", remote="10.0.0.2")
    response = await handler.handle_devices(request)
    assert response.status == 403


@pytest.mark.asyncio
async def test_lists_online_device_tools(make_mocked_request):
    handler = DeviceMcpDebugHandler(FakeServer())
    request = make_mocked_request("GET", "/debug/device-mcp/devices", remote="127.0.0.1")
    response = await handler.handle_devices(request)
    assert response.status == 200
    assert "toy-1" in response.text
```

- [ ] **Step 2: Run the tests to verify red state**

Run: `cd /Users/lianjia/Workspace/xiaozhi-esp32-server/main/xiaozhi-server && pytest tests/core/api/test_device_mcp_debug_handler.py -q`

Expected: FAIL because the handler module does not exist.

- [ ] **Step 3: Implement validation, listing, and delegation**

`DeviceMcpDebugHandler` accepts a `WebSocketServer`.  `_is_loopback(request)` returns true only when `request.remote` is `127.0.0.1` or `::1`; every other caller receives JSON `{"error": "debug endpoint is loopback-only"}` and HTTP 403.  `handle_devices` emits each registered ID and `connection.mcp_client.get_available_tools()` names.

`handle_call` requires a JSON object with non-empty string `device_id`, non-empty string `tool`, and object `arguments`.  It returns 400 for malformed JSON or invalid fields, 404 for no active device, 400 when the device has not advertised the requested tool, 504 on `TimeoutError`, and 502 for other `call_mcp_tool()` exceptions.  A successful response is `{"device_id": ..., "tool": ..., "result": ...}` with HTTP 200.

```python
result = await call_mcp_tool(connection, connection.mcp_client, tool, arguments)
return web.json_response({"device_id": device_id, "tool": tool, "result": result})
```

Pass the existing `ws_server` into `SimpleHttpServer(config, ws_server)` from `app.py`, create the handler in `SimpleHttpServer.__init__`, and register:

```python
web.get("/debug/device-mcp/devices", self.device_mcp_debug_handler.handle_devices),
web.post("/debug/device-mcp/call", self.device_mcp_debug_handler.handle_call),
```

- [ ] **Step 4: Run handler tests**

Run: `cd /Users/lianjia/Workspace/xiaozhi-esp32-server/main/xiaozhi-server && pytest tests/core/api/test_device_mcp_debug_handler.py -q`

Expected: PASS, including loopback rejection, validation, unavailable device/tool, successful call, timeout, and delegated error cases.

- [ ] **Step 5: Commit the debug bridge**

```bash
git -C /Users/lianjia/Workspace/xiaozhi-esp32-server add main/xiaozhi-server/app.py main/xiaozhi-server/core/http_server.py main/xiaozhi-server/core/api/device_mcp_debug_handler.py main/xiaozhi-server/tests/core/api/test_device_mcp_debug_handler.py
git -C /Users/lianjia/Workspace/xiaozhi-esp32-server commit -m "feat: add loopback device MCP debug bridge"
```

### Task 3: Add the firmware-repository CLI and unit tests

**Files:**
- Create: `tools/plush_toy_test.py`
- Create: `scripts/tests/test_plush_toy_test.py`
- Modify: `main/boards/plush-toy/README.md`

- [ ] **Step 1: Write failing CLI mapping tests**

```python
from tools import plush_toy_test


def test_wave_maps_to_device_tool():
    assert plush_toy_test.command_to_call(["wave", "--side", "left", "--times", "2"]) == (
        "self.limbs.wave_hand", {"side": "left", "times": 2}
    )


def test_eye_theme_maps_to_device_tool():
    assert plush_toy_test.command_to_call(["eyes", "dragon-amber"]) == (
        "self.eyes.change_theme", {"theme": "dragon-amber"}
    )


def test_regression_order_is_safe_and_deterministic():
    assert [tool for tool, _ in plush_toy_test.REGRESSION_CASES] == [
        "self.eyes.change_theme", "self.limbs.wave_hand", "self.limbs.wave_hand",
        "self.limbs.wave_hand", "self.limbs.hug", "self.limbs.cheer",
        "self.limbs.get_diagnostics",
    ]
```

- [ ] **Step 2: Run CLI tests to verify red state**

Run: `python3 -m unittest scripts.tests.test_plush_toy_test -v`

Expected: FAIL because `tools/plush_toy_test.py` does not exist.

- [ ] **Step 3: Implement the standard-library CLI**

Use `argparse`, `urllib.request`, and `json`; do not add dependencies.  Provide `devices`, `wave`, `hug`, `cheer`, `eyes`, `diagnostics`, and `run-regression` subcommands.  `--server` defaults to `http://127.0.0.1:8003`; `--device-id` is optional only for exactly one online device.  `call_device_tool()` posts the explicit tool/arguments JSON and prints a compact JSON response.  It exits 1 for HTTP, JSON, validation, or MCP errors.

Define the exact regression cases:

```python
REGRESSION_CASES = [
    ("self.eyes.change_theme", {"theme": "dragon-amber"}),
    ("self.limbs.wave_hand", {"side": "left", "times": 1}),
    ("self.limbs.wave_hand", {"side": "right", "times": 1}),
    ("self.limbs.wave_hand", {"side": "both", "times": 1}),
    ("self.limbs.hug", {}),
    ("self.limbs.cheer", {"times": 1}),
    ("self.limbs.get_diagnostics", {}),
]
```

Document the commands and explicitly state that successful MCP output proves protocol/firmware handling, while observed servo movement remains physical acceptance.

- [ ] **Step 4: Run the CLI tests**

Run: `python3 -m unittest scripts.tests.test_plush_toy_test -v`

Expected: PASS.

- [ ] **Step 5: Commit the CLI**

```bash
git add tools/plush_toy_test.py scripts/tests/test_plush_toy_test.py main/boards/plush-toy/README.md
git commit -m "feat: add plush toy text test CLI"
```

### Task 4: Verify against the live board

**Files:**
- Modify: `docs/superpowers/plans/2026-09-08-plush-toy-text-test-tool.md` (check off executed verification only)

- [ ] **Step 1: Run both repositories’ focused test suites**

Run:

```bash
cd /Users/lianjia/Workspace/xiaozhi-esp32-server/main/xiaozhi-server && pytest tests/core/test_websocket_server.py tests/core/api/test_device_mcp_debug_handler.py -q
cd /Users/lianjia/Workspace/xiaozhi-esp32 && python3 -m unittest scripts.tests.test_plush_toy_test -v
```

Expected: all tests PASS.

- [ ] **Step 2: Restart the local service and confirm one board is online**

Run: `python3 tools/plush_toy_test.py devices`

Expected: exactly one entry with the `plush-toy` MCP tool list, including `self.eyes.change_theme`, `self.limbs.wave_hand`, `self.limbs.hug`, `self.limbs.cheer`, and `self.limbs.get_diagnostics`.

- [ ] **Step 3: Run the actual MCP regression**

Run: `python3 tools/plush_toy_test.py run-regression`

Expected: seven successful JSON results, in the documented order; command exits 0.

- [ ] **Step 4: Run existing firmware checks**

Run:

```bash
make -C main/boards/plush-toy/test clean test
python3 -m unittest discover -s scripts/tests -v
```

Expected: all tests PASS.

- [ ] **Step 5: Commit verification record only if it contains no generated output**

```bash
git add docs/superpowers/plans/2026-09-08-plush-toy-text-test-tool.md
git commit -m "docs: record plush toy text test verification"
```
