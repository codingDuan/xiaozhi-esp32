# Plush Toy Eye Themes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Provide 20 original animated eye themes that can cycle when the user says “换眼睛”, can be selected by name, and survive a reboot.

**Architecture:** Add a board-local `EyeTheme` catalog that describes colors and shape flags without image assets. `EyeDisplay` owns the selected ID and combines the active theme with live emotion/gaze state before asking `EyeRenderer` to draw. A new MCP tool changes the display selection and NVS stores only its stable numeric ID.

**Tech Stack:** C++17, ESP-IDF Settings/NVS, ESP LCD, RGB565 procedural renderer, board host-test Makefile, device-side MCP.

---

### Task 1: Define the immutable 20-theme catalog and lookup API

**Files:**
- Create: `main/boards/plush-toy/eye_theme.h`
- Create: `main/boards/plush-toy/eye_theme.cc`
- Modify: `main/boards/plush-toy/test/Makefile`
- Create: `main/boards/plush-toy/test/test_eye_theme.cc`

- [ ] **Step 1: Write catalog tests first**

Create `test_eye_theme.cc` with checks for exact catalog size, IDs, cycling, and name resolution:

```cpp
CHECK(EyeThemeCatalog::Count() == 20, "catalog must contain exactly 20 themes");
CHECK(EyeThemeCatalog::Get(0).name == std::string_view("ocean"), "theme 0 is ocean");
CHECK(EyeThemeCatalog::Next(19) == 0, "last theme wraps to first");
CHECK(EyeThemeCatalog::Find("dragon-amber") == 14, "named dragon theme resolves");
CHECK(EyeThemeCatalog::Find("not-a-theme") == -1, "unknown theme is rejected");
```

Include this binary in the existing `test` and `clean` targets.

- [ ] **Step 2: Run the new test and verify it fails**

Run: `make -C main/boards/plush-toy/test test_eye_theme`

Expected: compilation failure because `eye_theme.h` does not exist.

- [ ] **Step 3: Add the catalog API and all 20 entries**

Define these rendering properties in `eye_theme.h`:

```cpp
enum class ScleraStyle : uint8_t { kLight, kDark, kNone };
enum class PupilShape : uint8_t { kRound, kVerticalSlit, kHorizontalSlit };
struct EyeTheme {
    uint8_t id;
    std::string_view name;
    uint16_t iris_inner;
    uint16_t iris_outer;
    ScleraStyle sclera;
    PupilShape pupil;
};
class EyeThemeCatalog {
public:
    static constexpr size_t Count() { return 20; }
    static const EyeTheme& Get(uint8_t id);
    static uint8_t Next(uint8_t id);
    static int Find(std::string_view name);
};
```

In `eye_theme.cc`, define IDs 0–19 in this exact order: `ocean`, `emerald`, `violet`, `amber`, `rose`, `ice`, `copper`, `jade`, `midnight`, `pearl`, `void-blue`, `void-purple`, `void-rose`, `dragon-amber`, `dragon-emerald`, `dragon-violet`, `cat-gold`, `cat-jade`, `cat-ice`, `cat-rose`. Use original RGB565 constants. `Get()` must return `ocean` for an invalid ID; `Next()` must normalize an invalid ID to `ocean` and wrap `19` to `0`; `Find()` must do an exact ASCII name match.

- [ ] **Step 4: Run the catalog test**

Run: `make -C main/boards/plush-toy/test test_eye_theme && main/boards/plush-toy/test/test_eye_theme`

Expected: `all EyeTheme tests passed`.

- [ ] **Step 5: Commit the self-contained catalog**

```bash
git add main/boards/plush-toy/eye_theme.{h,cc} main/boards/plush-toy/test/{Makefile,test_eye_theme.cc}
git commit -m "feat(plush-toy): add eye theme catalog"
```

### Task 2: Make the renderer apply theme visuals while preserving animation

**Files:**
- Modify: `main/boards/plush-toy/eye_renderer.h`
- Modify: `main/boards/plush-toy/eye_renderer.cc`
- Modify: `main/boards/plush-toy/test/test_eye_renderer.cc`

- [ ] **Step 1: Add failing visual-difference tests**

Render the same neutral `EyeState` with `ocean`, `void-blue`, `dragon-amber`, and `cat-gold`. Assert that each theme differs at a relevant pixel and that round, vertical-slit, and horizontal-slit pupil masks differ. Retain all existing mirror and dirty-rectangle tests.

```cpp
CHECK(Pixel(ocean, 120, 120) != Pixel(dragon, 120, 120), "dragon has slit pupil");
CHECK(Pixel(ocean, 20, 120) != Pixel(void_eye, 20, 120), "void theme removes light sclera");
CHECK(ocean != cat, "horizontal pupil theme changes the frame");
```

- [ ] **Step 2: Run the renderer test and verify it fails**

Run: `make -C main/boards/plush-toy/test test_eye_renderer && main/boards/plush-toy/test/test_eye_renderer`

Expected: compilation failure until `Render` accepts a theme.

- [ ] **Step 3: Extend rendering without adding frame buffers**

Change the signature to:

```cpp
static void Render(uint16_t* out, const EyeState& state, const EyeTheme& theme,
                   int side, DirtyRect rect);
```

Use `theme.iris_inner` and `theme.iris_outer` for radial interpolation. Draw `kLight` sclera with the current gradient, `kDark` with a dark blue-gray gradient, and `kNone` as the iris field within the eye aperture. Replace the round-pupil condition with a helper that tests a circle, a capped vertical ellipse/slit, or a capped horizontal ellipse/slit according to `theme.pupil`. Keep highlights, eyelid geometry, RGB/BGR swap, and all coordinate maths unchanged.

Keep `EyeState::iris_color` temporarily so existing emotion presets compile, but do not use it for an active themed frame. Update `ComputeDirty()` only if a renderer-state field changes; changing the theme will explicitly request `FullRect()` in Task 3.

- [ ] **Step 4: Update all renderer call sites and run tests**

Pass `EyeThemeCatalog::Get(0)` to test helpers and `EyeDisplay` call sites. Run:

```bash
make -C main/boards/plush-toy/test test_eye_renderer
main/boards/plush-toy/test/test_eye_renderer
```

Expected: existing tests and the new theme-shape checks pass.

- [ ] **Step 5: Commit renderer support**

```bash
git add main/boards/plush-toy/eye_renderer.{h,cc} main/boards/plush-toy/test/test_eye_renderer.cc
git commit -m "feat(plush-toy): render procedural eye themes"
```

### Task 3: Select and persist a theme in `EyeDisplay`

**Files:**
- Modify: `main/boards/plush-toy/eye_display.h`
- Modify: `main/boards/plush-toy/eye_display.cc`
- Modify: `main/boards/plush-toy/test/test_eye_theme.cc`

- [ ] **Step 1: Add a failing selection contract test**

Test `EyeThemeCatalog::Next()` for IDs 0, 18, 19, and 200. The display layer itself requires ESP-IDF Settings and is verified through device build/hardware in Task 5; do not mock NVS into the pure renderer test.

- [ ] **Step 2: Add the display API**

Add to `EyeDisplay`:

```cpp
bool ChangeTheme(const char* requested_name, std::string& selected_name);
uint8_t theme_id() const { return theme_id_; }
```

Store `uint8_t theme_id_ = 0;`. In the constructor, read `Settings("plush_eye", false).GetInt("theme_id", 0)`, accept only IDs below `EyeThemeCatalog::Count()`, and otherwise use 0. `Flush()` must pass `EyeThemeCatalog::Get(theme_id_)` to both renderer calls.

`ChangeTheme(nullptr, selected_name)` and `ChangeTheme("", selected_name)` must select `Next(theme_id_)`. A nonempty name must use `Find`; return `false` without writes/redraw for an unknown name. For a valid selection, update `theme_id_`, write `Settings("plush_eye", true).SetInt("theme_id", theme_id_)`, return the selected canonical name, and call `Flush(EyeRenderer::FullRect())`. This works during overlay mode because `Flush` is suppressed but `theme_id_` remains updated; `ShowEyes()` already requests a full redraw.

- [ ] **Step 3: Run catalog and renderer tests**

Run: `make -C main/boards/plush-toy/test clean test`

Expected: all board host tests pass.

- [ ] **Step 4: Commit persistence-capable selection**

```bash
git add main/boards/plush-toy/eye_display.{h,cc} main/boards/plush-toy/test/test_eye_theme.cc
git commit -m "feat(plush-toy): persist selected eye theme"
```

### Task 4: Expose the voice-control MCP contract

**Files:**
- Modify: `main/boards/plush-toy/plush_toy_board.cc`
- Modify: `scripts/tests/test_build.py`

- [ ] **Step 1: Add a failing source-level contract test**

In `scripts/tests/test_build.py`, add a test that reads `plush_toy_board.cc` and asserts it exposes `self.eyes.change_theme`, has an optional string `theme` property, and says “换眼睛” in its tool description.

- [ ] **Step 2: Run it and verify failure**

Run: `python3 -m unittest scripts.tests.test_build.VersionTests.test_plush_toy_eye_theme_tool -v`

Expected: FAIL because the new MCP tool does not yet exist.

- [ ] **Step 3: Register one bounded tool**

Within the existing `if (display_ != nullptr)` block in `InitializeTools()`, register:

```cpp
mcp.AddTool("self.eyes.change_theme",
    "Change the eye theme. Use when the user says 换眼睛 without a named style to cycle "
    "to the next theme. Use theme for a requested style such as ocean, dragon-amber, or cat-gold.",
    PropertyList({Property("theme", kPropertyTypeString, std::string(""))}),
    [eyes](const PropertyList& properties) -> ReturnValue {
        std::string selected;
        const auto requested = properties["theme"].value<std::string>();
        if (!eyes->ChangeTheme(requested.c_str(), selected))
            return std::string("unknown eye theme");
        return selected;
    });
```

Do not overload `self.eyes.swap_colors`: it remains strictly panel RGB/BGR calibration.

- [ ] **Step 4: Run the targeted test**

Run: `python3 -m unittest scripts.tests.test_build.VersionTests.test_plush_toy_eye_theme_tool -v`

Expected: PASS.

- [ ] **Step 5: Commit the MCP contract**

```bash
git add main/boards/plush-toy/plush_toy_board.cc scripts/tests/test_build.py
git commit -m "feat(plush-toy): expose eye theme switching"
```

### Task 5: Verify the integrated firmware and hardware behavior

**Files:**
- Modify if necessary: `main/boards/plush-toy/README.md`

- [ ] **Step 1: Run all local regression tests**

```bash
make -C main/boards/plush-toy/test clean test
python3 -m unittest discover -s scripts/tests -v
clang-format --dry-run -Werror main/boards/plush-toy/eye_theme.cc main/boards/plush-toy/eye_theme.h main/boards/plush-toy/eye_renderer.cc main/boards/plush-toy/eye_renderer.h main/boards/plush-toy/eye_display.cc main/boards/plush-toy/eye_display.h main/boards/plush-toy/plush_toy_board.cc
git diff --check
```

Expected: all host tests, all Python tests, formatting, and whitespace checks pass.

- [ ] **Step 2: Build and flash the selected board**

```bash
source /Users/lianjia/.espressif/v6.1/esp-idf/export.sh
python3 scripts/build.py plush-toy --name plush-toy
idf.py -p /dev/cu.usbmodem5C834268091 flash
```

Expected: ESP32-S3 build completes and flash exits successfully. If the ESP-IDF virtual environment is unavailable, record that exact environmental blocker; do not claim a fresh build passed.

- [ ] **Step 3: Perform physical acceptance**

Verify on the powered board: issue “换眼睛” 20 times and confirm 20 visibly distinct frames before wraparound; say “换成 dragon-amber” and “换成 cat-gold”; confirm blink and gaze remain animated; power-cycle and confirm the last selection returns; enter provisioning and confirm QR overlay covers both eyes, then exit and confirm the chosen theme returns.

- [ ] **Step 4: Document user-facing names**

Add the 20 canonical theme names and the two voice interaction forms to `main/boards/plush-toy/README.md`, including that names such as “龙眼” should map server-side to the canonical `dragon-*` values, while bare “换眼睛” uses no name and cycles locally.

- [ ] **Step 5: Commit verification documentation**

```bash
git add main/boards/plush-toy/README.md
git commit -m "docs(plush-toy): document eye theme controls"
```
