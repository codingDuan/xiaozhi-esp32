#pragma once

#include <cstdint>
#include <vector>

class OverlayQr {
public:
    // Encode text as a row-major side*side array of 0/1 QR modules.
    static bool Encode(const char* text, std::vector<uint8_t>& modules, int& side);
};
