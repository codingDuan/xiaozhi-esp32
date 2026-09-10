#pragma once

#include <cstdint>
#include <functional>
#include <string>

class TestHttpChannel {
public:
    using ScheduleAction = std::function<void(const std::string&, const std::string&)>;
    // 板级注入的 status 片段来源。控制台是哑的，触摸原始计数与舵机诊断
    // 只能从 HTTP 拿，所以 status 必须能带出板子的即时状态。
    using StatusProvider = std::function<std::string()>;

    TestHttpChannel(std::string allowed_host, ScheduleAction schedule_action,
                    StatusProvider status_provider = nullptr);
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
    StatusProvider status_provider_;
};
