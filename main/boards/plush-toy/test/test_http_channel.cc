#include "test_http_channel.h"

#include <cstdio>
#include <string>

namespace {
int failures = 0;
#define CHECK(condition, message) \
    do {                          \
        if (!(condition)) {       \
            std::fprintf(stderr, "FAIL: %s\n", message); \
            ++failures;           \
        }                         \
    } while (0)
}  // namespace

int main() {
    std::string scheduled_action;
    TestHttpChannel channel("172.20.10.14", [&](const std::string& action, const std::string&) {
        scheduled_action = action;
    });

    CHECK(channel.AuthorizePeer("172.20.10.14"), "configured host must be authorized");
    CHECK(!channel.AuthorizePeer("172.20.10.15"), "other LAN peer must be rejected");
    CHECK(channel.Dispatch("wave", R"({"side":"left","times":1})"),
          "whitelisted wave must dispatch");
    CHECK(scheduled_action == "wave", "wave must reach the scheduler");
    CHECK(!channel.Dispatch("self.reboot", "{}"), "non-test action must be rejected");
    CHECK(channel.StatusJson().find("\"wave\"") != std::string::npos,
          "status must list wave");
    CHECK(channel.StatusJson().find("self.reboot") == std::string::npos,
          "status must not expose reboot");

    if (failures) return 1;
    std::puts("all TestHttpChannel tests passed");
    return 0;
}
