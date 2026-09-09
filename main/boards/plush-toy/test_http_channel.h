#pragma once

#include <cstdint>
#include <functional>
#include <string>

class TestHttpChannel {
public:
    using ScheduleAction = std::function<void(const std::string&, const std::string&)>;

    TestHttpChannel(std::string allowed_host, ScheduleAction schedule_action);
    bool enabled() const;
    void SetAllowedSubnetMask(uint32_t netmask);
    bool AuthorizePeerAddress(uint32_t peer_address) const;
    bool AuthorizePeer(const std::string& peer) const;
    bool Dispatch(const std::string& action, const std::string& arguments_json) const;
    std::string StatusJson() const;

private:
    std::string allowed_host_;
    uint32_t allowed_subnet_mask_ = 0;
    ScheduleAction schedule_action_;
};
