#include "plush_toy_test_server.h"

#include <esp_log.h>
#include <cJSON.h>
#include <lwip/sockets.h>

#include <vector>

namespace {
constexpr int kPort = 8181;
constexpr size_t kMaxBodyBytes = 1024;
constexpr char kTag[] = "PlushTestHttp";
}  // namespace

PlushToyTestServer::PlushToyTestServer(const std::string& allowed_host,
                                       TestHttpChannel::ScheduleAction schedule_action)
    : channel_(allowed_host, std::move(schedule_action)) {}

PlushToyTestServer::~PlushToyTestServer() {
    if (server_ != nullptr)
        httpd_stop(server_);
}

bool PlushToyTestServer::Start() {
    if (!channel_.enabled()) {
        ESP_LOGW(kTag, "test channel disabled: websocket.url host is not a numeric IPv4 address");
        return false;
    }
    httpd_config_t config = HTTPD_DEFAULT_CONFIG();
    config.server_port = kPort;
    config.ctrl_port = kPort + 1;
    if (httpd_start(&server_, &config) != ESP_OK)
        return false;
    const httpd_uri_t status = {
        .uri = "/test/v1/status", .method = HTTP_GET, .handler = StatusHandler, .user_ctx = this};
    const httpd_uri_t action = {
        .uri = "/test/v1/actions", .method = HTTP_POST, .handler = ActionHandler, .user_ctx = this};
    if (httpd_register_uri_handler(server_, &status) != ESP_OK ||
        httpd_register_uri_handler(server_, &action) != ESP_OK) {
        httpd_stop(server_);
        server_ = nullptr;
        return false;
    }
    ESP_LOGI(kTag, "test channel listening on port %d", kPort);
    return true;
}

bool PlushToyTestServer::IsAuthorized(httpd_req_t* request) const {
    sockaddr_in peer = {};
    socklen_t length = sizeof(peer);
    if (getpeername(httpd_req_to_sockfd(request), reinterpret_cast<sockaddr*>(&peer), &length) != 0)
        return false;
    char address[INET_ADDRSTRLEN] = {};
    return inet_ntop(AF_INET, &peer.sin_addr, address, sizeof(address)) != nullptr &&
           channel_.AuthorizePeer(address);
}

void PlushToyTestServer::SendJson(httpd_req_t* request, const char* json,
                                  const char* status) const {
    httpd_resp_set_status(request, status);
    httpd_resp_set_type(request, "application/json");
    httpd_resp_sendstr(request, json);
}

esp_err_t PlushToyTestServer::StatusHandler(httpd_req_t* request) {
    auto* self = static_cast<PlushToyTestServer*>(request->user_ctx);
    if (!self->IsAuthorized(request)) {
        self->SendJson(request, R"({"error":"forbidden"})", "403 Forbidden");
        return ESP_OK;
    }
    self->SendJson(request, self->channel_.StatusJson().c_str());
    return ESP_OK;
}

esp_err_t PlushToyTestServer::ActionHandler(httpd_req_t* request) {
    auto* self = static_cast<PlushToyTestServer*>(request->user_ctx);
    if (!self->IsAuthorized(request)) {
        self->SendJson(request, R"({"error":"forbidden"})", "403 Forbidden");
        return ESP_OK;
    }
    if (request->content_len > kMaxBodyBytes) {
        self->SendJson(request, R"({"error":"payload too large"})", "413 Payload Too Large");
        return ESP_OK;
    }
    std::vector<char> body(request->content_len + 1, '\0');
    size_t received = 0;
    while (received < request->content_len) {
        const int result =
            httpd_req_recv(request, body.data() + received, request->content_len - received);
        if (result <= 0)
            break;
        received += result;
    }
    if (received != request->content_len) {
        self->SendJson(request, R"({"error":"invalid request body"})", "400 Bad Request");
        return ESP_OK;
    }
    cJSON* root = cJSON_Parse(body.data());
    cJSON* action = root ? cJSON_GetObjectItem(root, "action") : nullptr;
    cJSON* arguments = root ? cJSON_GetObjectItem(root, "arguments") : nullptr;
    if (!cJSON_IsString(action) || !cJSON_IsObject(arguments)) {
        if (root)
            cJSON_Delete(root);
        self->SendJson(request, R"({"error":"action and arguments are required"})",
                       "400 Bad Request");
        return ESP_OK;
    }
    char* arguments_json = cJSON_PrintUnformatted(arguments);
    const bool accepted =
        self->channel_.Dispatch(action->valuestring, arguments_json ? arguments_json : "");
    if (arguments_json)
        cJSON_free(arguments_json);
    cJSON_Delete(root);
    if (!accepted) {
        self->SendJson(request, R"({"error":"unsupported action"})", "404 Not Found");
        return ESP_OK;
    }
    self->SendJson(request, R"({"accepted":true})", "202 Accepted");
    return ESP_OK;
}
