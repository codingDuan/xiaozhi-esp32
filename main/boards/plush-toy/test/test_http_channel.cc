#include "test_http_channel.h"

#include <arpa/inet.h>
#include <cstdio>
#include <string>

namespace {
int failures = 0;
#define CHECK(condition, message)                        \
    do {                                                 \
        if (!(condition)) {                              \
            std::fprintf(stderr, "FAIL: %s\n", message); \
            ++failures;                                  \
        }                                                \
    } while (0)
}  // namespace

int main() {
    std::string scheduled_action;
    TestHttpChannel channel("172.20.10.14", [&](const std::string& action, const std::string&) {
        scheduled_action = action;
    });

    CHECK(channel.enabled(), "numeric IPv4 host must enable the channel");
    CHECK(channel.AuthorizePeer("172.20.10.14"), "configured host must be authorized");
    CHECK(!channel.AuthorizePeer("172.20.10.15"), "peer outside the configured host is rejected");
    in_addr allowed = {};
    inet_pton(AF_INET, "172.20.10.14", &allowed);
    CHECK(channel.AuthorizePeerAddress(allowed.s_addr), "raw IPv4 address must be authorized");
    channel.SetAllowedSubnetMask(htonl(0xfffffff0));
    in_addr gateway = {};
    inet_pton(AF_INET, "172.20.10.1", &gateway);
    CHECK(channel.AuthorizePeerAddress(gateway.s_addr),
          "a peer in the current Wi-Fi subnet must be authorized");
    CHECK(!channel.AuthorizePeer("172.20.11.2"), "peer outside the Wi-Fi subnet is rejected");
    CHECK(channel.Dispatch("wave", R"({"side":"left","times":1})"),
          "whitelisted wave must dispatch");
    CHECK(scheduled_action == "wave", "wave must reach the scheduler");
    CHECK(channel.Dispatch("emotion", R"({"emotion":"happy"})"),
          "whitelisted emotion must dispatch");
    CHECK(scheduled_action == "emotion", "emotion must reach the scheduler");
    CHECK(channel.Dispatch("touch_modes", R"({"modes":5})"),
          "whitelisted touch_modes must dispatch");
    CHECK(scheduled_action == "touch_modes", "touch_modes must reach the scheduler");
    CHECK(channel.Dispatch("simulate_touch", R"({"electrode":0,"pressed":true})"),
          "whitelisted simulate_touch must dispatch");
    CHECK(channel.StatusJson().find("\"simulate_touch\"") != std::string::npos,
          "status must list simulate_touch");
    CHECK(channel.Dispatch("motion_modes", R"({"modes":9})"),
          "whitelisted motion_modes must dispatch");
    CHECK(scheduled_action == "motion_modes", "motion_modes must reach the scheduler");
    CHECK(channel.Dispatch("simulate_motion", R"({"kind":"shake"})"),
          "whitelisted simulate_motion must dispatch");
    CHECK(channel.StatusJson().find("\"simulate_motion\"") != std::string::npos,
          "status must list simulate_motion");
    CHECK(channel.Dispatch("gesture_modes", R"({"modes":15})"),
          "whitelisted gesture_modes must dispatch");
    CHECK(scheduled_action == "gesture_modes", "gesture_modes must reach the scheduler");
    CHECK(channel.StatusJson().find("\"gesture_modes\"") != std::string::npos,
          "status must list gesture_modes");
    CHECK(!channel.Dispatch("self.reboot", "{}"), "non-test action must be rejected");
    CHECK(channel.StatusJson().find("\"wave\"") != std::string::npos, "status must list wave");
    CHECK(channel.StatusJson().find("\"emotion\"") != std::string::npos,
          "status must list emotion");
    CHECK(channel.StatusJson().find("self.reboot") == std::string::npos,
          "status must not expose reboot");

    // 控制台是哑的，原始计数只能从 status 拿。板级片段必须原样嵌入。
    TestHttpChannel probed("172.20.10.14", [](const std::string&, const std::string&) {},
                           []() { return std::string(R"("touch_bits":1)"); });
    CHECK(probed.StatusJson().find(R"("touch_bits":1)") != std::string::npos,
          "status must embed the board-provided fragment");
    CHECK(probed.StatusJson().find("\"ready\":true") != std::string::npos,
          "status must keep the ready flag");

    TestHttpChannel disabled("example.com", [](const std::string&, const std::string&) {});
    CHECK(!disabled.enabled(), "hostname must disable the channel");
    CHECK(!disabled.AuthorizePeer("172.20.10.14"), "disabled channel must reject every peer");

    if (failures)
        return 1;
    std::puts("all TestHttpChannel tests passed");
    return 0;
}
