#include "test_http_channel.h"

#ifdef ESP_PLATFORM
#include <lwip/sockets.h>
#else
#include <arpa/inet.h>
#endif

namespace {
bool IsAllowedAction(const std::string& action) {
    return action == "wave" || action == "hug" || action == "cheer" || action == "eyes" ||
           action == "diagnostics";
}
}  // namespace

TestHttpChannel::TestHttpChannel(std::string allowed_host, ScheduleAction schedule_action)
    : allowed_host_(std::move(allowed_host)), schedule_action_(std::move(schedule_action)) {}

bool TestHttpChannel::enabled() const {
    in_addr allowed = {};
    return inet_pton(AF_INET, allowed_host_.c_str(), &allowed) == 1;
}

bool TestHttpChannel::AuthorizePeer(const std::string& peer) const {
    in_addr allowed = {};
    in_addr candidate = {};
    return inet_pton(AF_INET, allowed_host_.c_str(), &allowed) == 1 &&
           inet_pton(AF_INET, peer.c_str(), &candidate) == 1 && allowed.s_addr == candidate.s_addr;
}

bool TestHttpChannel::Dispatch(const std::string& action, const std::string& arguments_json) const {
    if (!IsAllowedAction(action) || arguments_json.size() > 1024 || !schedule_action_)
        return false;
    schedule_action_(action, arguments_json);
    return true;
}

std::string TestHttpChannel::StatusJson() const {
    return R"({"ready":true,"actions":["wave","hug","cheer","eyes","diagnostics"]})";
}
