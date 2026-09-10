#pragma once

#include "test_http_channel.h"

#include <esp_http_server.h>
#include <cstddef>

#include <string>

class PlushToyTestServer {
public:
    PlushToyTestServer(const std::string& allowed_host,
                       TestHttpChannel::ScheduleAction schedule_action,
                       TestHttpChannel::StatusProvider status_provider = nullptr);
    ~PlushToyTestServer();
    bool Start();

private:
    static esp_err_t StatusHandler(httpd_req_t* request);
    static esp_err_t ActionHandler(httpd_req_t* request);
    bool IsAuthorized(httpd_req_t* request) const;
    void SendJson(httpd_req_t* request, const char* json, const char* status = "200 OK") const;

    TestHttpChannel channel_;
    httpd_handle_t server_ = nullptr;
};
