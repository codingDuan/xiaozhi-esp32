#include "eye_theme.h"

#include <cstdio>

static int g_failures = 0;

#define CHECK(condition, message)                                          \
    do {                                                                   \
        if (!(condition)) {                                                \
            std::printf("FAIL: %s (%s:%d)\n", message, __FILE__, __LINE__); \
            ++g_failures;                                                  \
        }                                                                  \
    } while (0)

int main() {
    CHECK(EyeThemeCatalog::Count() == 20, "catalog must contain 20 themes");
    CHECK(EyeThemeCatalog::Get(0).name == "ocean", "theme zero is ocean");
    CHECK(EyeThemeCatalog::Get(19).name == "cat-rose", "theme nineteen is cat-rose");
    CHECK(EyeThemeCatalog::Next(0) == 1, "next advances one theme");
    CHECK(EyeThemeCatalog::Next(19) == 0, "last theme wraps to first");
    CHECK(EyeThemeCatalog::Next(200) == 0, "invalid theme cycles from first");
    CHECK(EyeThemeCatalog::Find("dragon-amber") == 13, "named dragon theme resolves");
    CHECK(EyeThemeCatalog::Find("cat-gold") == 16, "named cat theme resolves");
    CHECK(EyeThemeCatalog::Find("not-a-theme") == -1, "unknown theme is rejected");

    if (g_failures == 0) {
        std::printf("all EyeTheme tests passed\n");
        return 0;
    }
    std::printf("%d EyeTheme test(s) failed\n", g_failures);
    return 1;
}
