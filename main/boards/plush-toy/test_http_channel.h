#pragma once

#include <functional>
#include <string>

class TestHttpChannel {
public:
    using ScheduleAction = std::function<void(const std::string&, const std::string&)>;

    TestHttpChannel(std::string allowed_host, ScheduleAction schedule_action);
    bool AuthorizePeer(const std::string& peer) const;
    bool Dispatch(const std::string& action, const std::string& arguments_json) const;
    std::string StatusJson() const;

private:
    std::string allowed_host_;
    ScheduleAction schedule_action_;
};
