#include "overlay_qr.h"

extern "C" {
#include "qrcodegen.h"
}

bool OverlayQr::Encode(const char* text, std::vector<uint8_t>& modules, int& side) {
    modules.clear();
    side = 0;
    if (text == nullptr || text[0] == '\0')
        return false;

    uint8_t qr[qrcodegen_BUFFER_LEN_FOR_VERSION(6)];
    uint8_t temp[qrcodegen_BUFFER_LEN_FOR_VERSION(6)];
    const bool encoded = qrcodegen_encodeText(text, temp, qr, qrcodegen_Ecc_LOW,
                                              qrcodegen_VERSION_MIN, 6, qrcodegen_Mask_AUTO, true);
    if (!encoded)
        return false;

    side = qrcodegen_getSize(qr);
    modules.resize(static_cast<size_t>(side) * side);
    for (int y = 0; y < side; ++y) {
        for (int x = 0; x < side; ++x) {
            modules[static_cast<size_t>(y) * side + x] = qrcodegen_getModule(qr, x, y) ? 1 : 0;
        }
    }
    return true;
}
