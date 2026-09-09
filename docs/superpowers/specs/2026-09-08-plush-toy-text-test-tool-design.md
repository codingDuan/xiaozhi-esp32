# Plush Toy Text Test Tool Design

## Goal

Allow a developer at the workstation to send real MCP actions to an online plush-toy board from text commands, without wake-word, speech recognition, or an LLM.

## Scope

The companion `xiaozhi-esp32-server` process will retain its active device connections by device ID.  Its existing HTTP server will expose a debugging bridge restricted to loopback clients.  A command-line client in the firmware repository will invoke that bridge.

The bridge exposes:

- `GET /debug/device-mcp/devices` to list online devices and their advertised tools.
- `POST /debug/device-mcp/call` with `device_id`, `tool`, and `arguments` to call one advertised device MCP tool and return its result.

The HTTP handler rejects every peer other than `127.0.0.1` or `::1`.  It never accepts arbitrary WebSocket payloads: requests are validated as a named tool plus a JSON object, and the existing `call_mcp_tool()` implementation continues to issue the protocol call and enforce its timeout.

The CLI supports direct commands for the plush-toy actions:

```sh
python3 tools/plush_toy_test.py devices
python3 tools/plush_toy_test.py wave --side left --times 2
python3 tools/plush_toy_test.py hug
python3 tools/plush_toy_test.py cheer --times 3
python3 tools/plush_toy_test.py eyes dragon-amber
python3 tools/plush_toy_test.py diagnostics
python3 tools/plush_toy_test.py run-regression
```

`run-regression` calls the actual online device in a fixed order: eye theme selection, left/right/both wave, hug, cheer, and diagnostics.  It prints each tool result and exits non-zero on an RPC, device, or validation failure.  It does not claim that a servo physically moved; that remains the concise human observation step.

## Data flow

```text
CLI -> loopback HTTP debug bridge -> active ConnectionHandler -> MCP tools/call -> board
CLI <- result/error             <- MCP tool result       <- board
```

When no requested device is online, the bridge returns a clear 404.  When multiple devices are online, the CLI requires `--device-id`; when one is online, it selects it automatically.  A tool not advertised by that device is rejected before sending a request.

## Testing

Server tests will cover loopback enforcement, device lookup, input validation, unavailable tools, successful delegation, and error mapping with a fake active connection.  CLI tests will cover command-to-tool mappings, payload construction, selection behavior, and regression ordering.  After deployment, the CLI regression will be run against the connected board; its MCP responses will be recorded separately from physical acceptance.
