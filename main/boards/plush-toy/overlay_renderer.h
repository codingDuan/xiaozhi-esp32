#pragma once

#include <cstdint>
#include <vector>

class OverlayRenderer {
public:
    static constexpr int kSize = 240;

    // Render a determinate 0..100 percent progress ring into a full RGB565 frame.
    static void RenderProgress(uint16_t* out, int progress);

    // Render a QR module matrix as black modules on a white background.
    static bool RenderQr(uint16_t* out, const std::vector<uint8_t>& modules, int side);

    // Render the static companion shown in the other eye during provisioning.
    static void RenderWaitIcon(uint16_t* out);
};
