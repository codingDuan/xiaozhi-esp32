#include "test_http_channel.h"

#ifdef ESP_PLATFORM
#include <lwip/sockets.h>
#else
#include <arpa/inet.h>
#endif

namespace {
bool IsAllowedAction(const std::string& action) {
    return action == "wave" || action == "hug" || action == "cheer" || action == "eyes" ||
           action == "emotion" || action == "diagnostics";
}
}  // namespace

TestHttpChannel::TestHttpChannel(std::string allowed_host, ScheduleAction schedule_action)
    : allowed_host_(std::move(allowed_host)), schedule_action_(std::move(schedule_action)) {}

bool TestHttpChannel::enabled() const {
    in_addr allowed = {};
    return inet_pton(AF_INET, allowed_host_.c_str(), &allowed) == 1;
}

void TestHttpChannel::SetAllowedSubnetMask(uint32_t netmask) { allowed_subnet_mask_ = netmask; }

bool TestHttpChannel::AuthorizePeer(const std::string& peer) const {
    in_addr candidate = {};
    return inet_pton(AF_INET, peer.c_str(), &candidate) == 1 &&
           AuthorizePeerAddress(candidate.s_addr);
}

bool TestHttpChannel::AuthorizePeerAddress(uint32_t peer_address) const {
    in_addr allowed = {};
    if (inet_pton(AF_INET, allowed_host_.c_str(), &allowed) != 1)
        return false;
    return allowed.s_addr == peer_address ||
           (allowed_subnet_mask_ != 0 &&
            (allowed.s_addr & allowed_subnet_mask_) == (peer_address & allowed_subnet_mask_));
}

bool TestHttpChannel::Dispatch(const std::string& action, const std::string& arguments_json) const {
    if (!IsAllowedAction(action) || arguments_json.size() > 1024 || !schedule_action_)
        return false;
    schedule_action_(action, arguments_json);
    return true;
}

std::string TestHttpChannel::StatusJson() const {
    return R"({"ready":true,"actions":["wave","hug","cheer","eyes","emotion","diagnostics"]})";
}
