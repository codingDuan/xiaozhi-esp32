// 把几种情绪渲染成裸 RGB 文件，供 to_png.py 转成图片肉眼检查。
//   make preview && ./preview && python3 to_png.py
// 不带参数时渲染默认主题 ocean；带参数则每个参数是一个主题名，
// 输出文件名带上主题，便于把写实和日系两种画法并排比对。
#include "eye_renderer.h"
#include "eye_theme.h"
#include <cstdio>
#include <cstring>
#include <vector>
struct Preset { const char* name; EyeState s; };
int main(int argc, char** argv) {
    std::vector<Preset> ps = {
        {"neutral",  {0.94f, 0,0, 1.0f,   0,    0,    0x363E}},
        {"happy",    {0.62f, 0,0.05f,1.0f,0,    0.85f,0x363E}},
        {"sad",      {0.58f, 0,0.34f,1.0f,19,  -0.4f, 0x363E}},
        {"angry",    {0.68f, 0,-0.1f,0.82f,-27,-0.25f,0x363E}},
        {"surprised",{1.0f,  0,0,   1.45f, 0,    0,    0x363E}},
        {"sleepy",   {0.18f, 0,0.25f,1.0f, 6,  -0.15f,0x363E}},
        {"blink",    {0.08f, 0,0,   1.0f,  0,    0,    0x363E}},
    };
    std::vector<const char*> themes;
    for (int i = 1; i < argc; ++i) themes.push_back(argv[i]);
    if (themes.empty()) themes.push_back("ocean");

    const int N = EyeRenderer::kSize;
    for (const char* tn : themes) {
        const int id = EyeThemeCatalog::Find(tn);
        if (id < 0) { std::printf("未知主题: %s\n", tn); return 1; }
        const EyeTheme& theme = EyeThemeCatalog::Get((uint8_t)id);
        // 每种情绪出一张「左眼|右眼」并排图，便于检查镜像是否对称
        for (auto& p : ps) {
            std::vector<uint16_t> l(N*N), r(N*N);
            EyeRenderer::Render(l.data(), p.s, theme, +1, EyeRenderer::FullRect());
            EyeRenderer::Render(r.data(), p.s, theme, -1, EyeRenderer::FullRect());
            char fn[160];
            std::snprintf(fn, sizeof(fn), "eye_%s_%s.rgb", tn, p.name);
            FILE* f = std::fopen(fn, "wb");
            for (int y = 0; y < N; y++) {
                for (int pass = 0; pass < 2; pass++) {
                    const std::vector<uint16_t>& b = pass ? r : l;
                    for (int x = 0; x < N; x++) {
                        uint16_t c = b[y*N+x];
                        unsigned char px[3] = {
                            (unsigned char)(((c>>11)&0x1F)*255/31),
                            (unsigned char)(((c>>5)&0x3F)*255/63),
                            (unsigned char)((c&0x1F)*255/31)};
                        std::fwrite(px,1,3,f);
                    }
                }
            }
            std::fclose(f);
            std::printf("%s\n", fn);
        }
    }
    return 0;
}
