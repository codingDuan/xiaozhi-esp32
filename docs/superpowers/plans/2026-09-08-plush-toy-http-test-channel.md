# Plush Toy Independent HTTP Test Channel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the workstation issue direct text actions to an idle plush-toy board without opening its voice WebSocket.

**Architecture:** The board-local `PlushToyTestServer` owns TCP 8181 and delegates validated actions to existing board callbacks through `Application::Schedule()`. The Python CLI calls this endpoint directly. The earlier local-server MCP bridge is reverted so the normal audio architecture is unchanged.

**Tech Stack:** ESP-IDF `esp_http_server`, C++17, cJSON, Python standard library, unittest.

---

### Task 1: Add a testable board-local action router

**Files:**
- Create: `main/boards/plush-toy/test_http_channel.h`
- Create: `main/boards/plush-toy/test_http_channel.cc`
- Create: `main/boards/plush-toy/test/test_http_channel.cc`
- Modify: `main/boards/plush-toy/test/Makefile`

- [ ] **Step 1: Write the failing authorization and action tests**

```cpp
TEST(AuthorizePeerAcceptsConfiguredHost) {
  TestHttpChannel channel("172.20.10.14", callback);
  CHECK(channel.AuthorizePeer("172.20.10.14"));
  CHECK(!channel.AuthorizePeer("172.20.10.15"));
}

TEST(DispatchSchedulesWhitelistedWave) {
  CHECK(channel.Dispatch("wave", R"({"side":"left","times":1})"));
  CHECK(scheduled_action == "wave");
  CHECK(!channel.Dispatch("self.reboot", "{}"));
}
```

- [ ] **Step 2: Verify red state**

Run: `make -C main/boards/plush-toy/test test_http_channel`

Expected: FAIL because `TestHttpChannel` does not exist.

- [ ] **Step 3: Implement the pure router**

`TestHttpChannel` accepts one numeric IPv4 host and a `std::function<void(const std::string&, const std::string&)>` scheduler. `AuthorizePeer()` uses `inet_pton(AF_INET, ...)` on both addresses. `Dispatch()` allows exactly `wave`, `hug`, `cheer`, `eyes`, and `diagnostics`, enforces a 1024-byte JSON body, and calls the scheduler once; it rejects all other names.

- [ ] **Step 4: Verify green state**

Run: `make -C main/boards/plush-toy/test test_http_channel`

Expected: PASS.

- [ ] **Step 5: Commit router**

```sh
git add main/boards/plush-toy/test_http_channel.* main/boards/plush-toy/test/test_http_channel.cc main/boards/plush-toy/test/Makefile
git commit -m "feat: add plush toy HTTP test action router"
```

### Task 2: Bind the router to an ESP-IDF HTTP server

**Files:**
- Create: `main/boards/plush-toy/plush_toy_test_server.h`
- Create: `main/boards/plush-toy/plush_toy_test_server.cc`
- Modify: `main/boards/plush-toy/plush_toy_board.cc`
- Modify: `main/boards/plush-toy/CMakeLists.txt` if board-local source selection requires it

- [ ] **Step 1: Write failing route-contract tests in `test_http_channel.cc`**

```cpp
TEST(StatusListsOnlyTestActions) {
  CHECK(channel.StatusJson().find("\"wave\"") != std::string::npos);
  CHECK(channel.StatusJson().find("self.reboot") == std::string::npos);
}
```

- [ ] **Step 2: Verify red state**

Run: `make -C main/boards/plush-toy/test test_http_channel`

Expected: FAIL because `StatusJson()` does not exist.

- [ ] **Step 3: Implement HTTP handlers and board callbacks**

`PlushToyTestServer::Start()` configures `HTTPD_DEFAULT_CONFIG()` with port `8181`, registers `GET /test/v1/status` and `POST /test/v1/actions`, and delegates peer checking and action validation to `TestHttpChannel`. The POST handler reads at most 1024 bytes, requires `{ "action": string, "arguments": object }`, and returns JSON 400/403/404/413 errors as applicable.

The board constructs it after `InitializeTools()`. Its scheduler calls `Application::GetInstance().Schedule()` and invokes existing `limbs_` actions or `SetEyeTheme`; it never calls them from the HTTP handler task. The allowed source address is parsed from persisted `websocket.url`; non-numeric hosts leave the test server disabled and log the reason. No changes are made to `WebsocketProtocol`, `Application`, `McpServer`, or audio files.

- [ ] **Step 4: Verify router tests and affected build**

Run:

```sh
make -C main/boards/plush-toy/test clean test
source /Users/lianjia/.espressif/tools/activate_idf_v6.1.sh && export PATH="$IDF_PATH/tools:$PATH" && python3 scripts/build.py plush-toy --name plush-toy
```

Expected: all host tests and the ESP32-S3 build PASS.

- [ ] **Step 5: Commit HTTP server**

```sh
git add main/boards/plush-toy/plush_toy_test_server.* main/boards/plush-toy/plush_toy_board.cc main/boards/plush-toy/CMakeLists.txt
git commit -m "feat: add board-local plush toy test HTTP server"
```

### Task 3: Switch the CLI and retire the server bridge

**Files:**
- Modify: `tools/plush_toy_test.py`
- Modify: `scripts/tests/test_plush_toy_test.py`
- Modify: `main/boards/plush-toy/README.md`
- Revert in `/Users/lianjia/Workspace/xiaozhi-esp32-server`: commits `b5117039` and `e84ff405`

- [ ] **Step 1: Write the failing direct-endpoint CLI test**

```python
def test_wave_posts_to_device_endpoint():
    request = build_action_request("http://172.20.10.2:8181", "wave", {"side": "left", "times": 1})
    assert request.full_url == "http://172.20.10.2:8181/test/v1/actions"
    assert json.loads(request.data) == {"action": "wave", "arguments": {"side": "left", "times": 1}}
```

- [ ] **Step 2: Verify red state**

Run: `python3 -m unittest scripts.tests.test_plush_toy_test -v`

Expected: FAIL because `build_action_request` does not exist.

- [ ] **Step 3: Implement direct CLI calls**

Require `--device-url`; replace `devices` with `status`, post mapped action names to `/test/v1/actions`, retain `wave`, `hug`, `cheer`, `eyes`, `diagnostics`, and `run-regression`, and bypass proxies as before. Document `--device-url http://172.20.10.2:8181`.

Revert the two server commits so no unused debug listener or connection registry remains.

- [ ] **Step 4: Verify tests**

Run:

```sh
python3 -m unittest scripts.tests.test_plush_toy_test -v
cd /Users/lianjia/Workspace/xiaozhi-esp32-server/main/xiaozhi-server && /Users/lianjia/miniconda3/envs/xiaozhi-esp32-server/bin/python -m unittest discover -s tests -v
```

Expected: all tests PASS.

- [ ] **Step 5: Commit CLI change and bridge removal**

```sh
git add tools/plush_toy_test.py scripts/tests/test_plush_toy_test.py main/boards/plush-toy/README.md
git commit -m "feat: send plush toy tests directly over HTTP"
git -C /Users/lianjia/Workspace/xiaozhi-esp32-server revert --no-edit e84ff405 b5117039
```

### Task 4: Flash and run direct regression

**Files:**
- Modify: `docs/superpowers/plans/2026-09-08-plush-toy-http-test-channel.md` (check executed verification only)

- [ ] **Step 1: Flash the verified image**

Run: `idf.py -p /dev/cu.usbmodem5C834268091 flash`

Expected: `Hash of data verified` and hardware reset.

- [ ] **Step 2: Run direct status and real actions**

Run:

```sh
python3 tools/plush_toy_test.py --device-url http://172.20.10.2:8181 status
python3 tools/plush_toy_test.py --device-url http://172.20.10.2:8181 run-regression
```

Expected: status succeeds while no voice session is active; seven action responses succeed.
