# Plush Toy Independent HTTP Test Channel Design

## Goal

Provide a text-driven test channel that is reachable while the plush-toy is idle, without creating or modifying the voice WebSocket, audio pipeline, server-side MCP connection, or LLM flow.

## Architecture

The `plush-toy` board starts a board-local HTTP server on TCP port `8181` after Wi-Fi has connected.  This server is independent of the XiaoZhi server and accepts only a fixed set of test actions.  Each request schedules the existing board action on the application task; the HTTP task never changes device state directly or blocks on arm animation.

```text
tools/plush_toy_test.py --device-url http://<board-ip>:8181
                         |
                         v
       plush-toy HTTP test channel -> existing limb/eye action entry points

voice WebSocket -> existing Application / Protocol / audio paths (unchanged)
```

## API and security

The server has one readiness endpoint and one action endpoint:

- `GET /test/v1/status` returns the board IP, readiness, and supported action names.
- `POST /test/v1/actions` accepts JSON `{ "action": string, "arguments": object }` and responds with a JSON result or a client error.

The actions are `wave`, `hug`, `cheer`, `eyes`, and `diagnostics`.  No generic MCP payload, shell command, filesystem access, camera capture, volume control, or reboot operation is exposed.

Requests are accepted only if the source IPv4 address is the current host in the board's persisted WebSocket URL.  This keeps the port usable from the development Mac already configured by OTA while rejecting other LAN peers.  If the configured WebSocket URL is not a numeric IPv4 address, the test channel remains disabled and reports that fact through its status endpoint; it must not broaden access silently.

The service-side loopback debug bridge introduced for the earlier design is removed.  The normal XiaoZhi HTTP/OTA and WebSocket services retain their previous behavior.

## Device behavior

The server starts only for the `plush-toy` board.  It does not open a WebSocket, wake the audio pipeline, alter `Application::SetDeviceState()`, or make any network request after startup.  It uses bounded request payloads and returns immediately after scheduling an action.  Existing motion serialization remains owned by `LimbController`; eye changes retain their existing NVS persistence.

## CLI behavior

The CLI moves from `--server` to required `--device-url`, for example:

```sh
export PLUSH_TOY_DEVICE_URL=http://<板子IP>:8181   # 或每条都带 --device-url
python3 tools/plush_toy_test.py status
python3 tools/plush_toy_test.py wave --side left
python3 tools/plush_toy_test.py eyes dragon-amber
python3 tools/plush_toy_test.py run-regression
```

`--device-url` 没有默认值，缺了会直接报错退出。板子 IP 随 DHCP 变，写死的默认值只会让人对着失效地址反复超时。取 IP 的方法与前提见 `main/boards/plush-toy/README.md`。

`run-regression` sends the fixed sequence to the board-local endpoint.  A success result establishes direct command delivery and firmware scheduling; visual servo/display observation remains the final physical acceptance criterion.

## Testing

Host tests validate source-address parsing and allow-list decisions, request validation, action mapping, response serialization, and that action callbacks schedule rather than run on the HTTP task.  CLI tests validate direct-HTTP request construction and regression ordering.  The affected `plush-toy` firmware builds and host tests run before flashing.  After the board reconnects to Wi-Fi, the CLI status request and direct regression run against the board without starting a voice session.
