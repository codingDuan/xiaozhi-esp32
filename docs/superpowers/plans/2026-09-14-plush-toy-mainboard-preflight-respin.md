# Plush Toy Mainboard Preflight Respin Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Regenerate and reroute the plush-toy mainboard with protected USB power, tight buck/ESP32/XCLK geometry, safe connector markings, and directly uploadable JLCPCB manufacturing outputs.

**Architecture:** `scripts/board_spec.py` remains the electrical source of truth, while the schematic and PCB stay generated artifacts. Placement and critical copper are deterministic and tested before Freerouting handles non-critical nets; manufacturing files are generated in a temporary directory and atomically promoted only after electrical, geometric, DRC, parity, and BOM/CPL checks pass. This remains one plan because every circuit change invalidates the same generated schematic, placement, routing solution, and manufacturing package.

**Tech Stack:** Python 3 `unittest`, KiCad 10.0.6 CLI and `pcbnew`, OpenJDK 26, Freerouting 2.4.1, Bash, CSV/Gerber.

**Spec:** `docs/superpowers/specs/2026-09-14-plush-toy-mainboard-preflight-respin-design.md`

## Global Constraints

- Work on the current `feat/plush-toy-design` branch; do not create a worktree.
- Preserve `.idea/`, `sdkconfig.bak.breadwifi`, `sdkconfig.bak.s3cam`, and unrelated worktree changes.
- Do not modify `main/boards/plush-toy/config.h` or any GPIO assignment.
- Keep the board 90×60mm, four layers, and single-sided assembly.
- Keep VBUS and VMOT isolated; `R_STAR` remains the only PGND/GND connection.
- Keep In1 as continuous GND and In2 as the logic-power plane; never route signals on inner layers.
- Use `apply_patch` for source changes and regenerate `.kicad_sch`, `.kicad_pcb`, `fab/`, and `renders/` through project scripts.
- Run ordinary data tests with `python3`; run `pcbnew` tests and generators with `/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3` (`KP`).
- ESP-IDF activation is not needed: this plan changes PCB generation and documentation, not firmware.
- Do not claim hardware validation from ERC, DRC, rendering, or manufacturing export.

## File Map

- `hardware/plush-toy-mainboard/scripts/board_spec.py`: parts, fitted state, LCSC codes, pins, and nets.
- `hardware/plush-toy-mainboard/lib/plush.kicad_sym`: exact project symbol for TPS259531.
- `hardware/plush-toy-mainboard/scripts/gen_schematic.py`: generated schematic and explicit NC behavior.
- `hardware/plush-toy-mainboard/scripts/placement.py`: fixed positions, proximity constraints, and safety-silkscreen definitions.
- `hardware/plush-toy-mainboard/scripts/gen_pcb.py`: board creation, stackup, zones, footprints, and independent silkscreen text.
- `hardware/plush-toy-mainboard/scripts/fanout.py`: locked eFuse/buck/ESP32/XCLK critical copper and existing plane fanout.
- `hardware/plush-toy-mainboard/scripts/post_route.py`: non-critical completion and candidate-only DRC promotion.
- `hardware/plush-toy-mainboard/scripts/export_bom.py`: automated-versus-hand-installed assembly classification.
- `hardware/plush-toy-mainboard/scripts/fab_tools.py`: JLCPCB CPL conversion and package validation.
- `hardware/plush-toy-mainboard/scripts/export_fab.sh`: atomic manufacturing export and renders.
- `hardware/plush-toy-mainboard/scripts/test_*.py`: source, library, PCB geometry, routing, DRC, and manufacturing regressions.
- `hardware/plush-toy-mainboard/{README.md,TESTING.md}` and `docs/superpowers/specs/2026-09-14-plush-toy-pcb-4layer-design.md`: operator and fabrication guidance.
- `hardware/plush-toy-mainboard/{plush-toy-mainboard.kicad_sch,plush-toy-mainboard.kicad_pcb,fab/,renders/}`: regenerated deliverables.

---

### Task 1: Encode the protected power path and revised assembly population

**Files:**
- Modify: `hardware/plush-toy-mainboard/scripts/board_spec.py:44-138,212-250`
- Modify: `hardware/plush-toy-mainboard/scripts/gen_schematic.py:184-189`
- Modify: `hardware/plush-toy-mainboard/scripts/export_bom.py:16-28`
- Modify: `hardware/plush-toy-mainboard/scripts/test_board_spec.py:23-103`
- Modify: `hardware/plush-toy-mainboard/scripts/test_export_bom.py:16-60`
- Modify: `hardware/plush-toy-mainboard/README.md:5-15`

**Interfaces:**
- Consumes: existing `Part`, `res()`, `cap()`, `nc()`, `PARTS`, `nets()`, and `is_assembly_item(part)`.
- Produces: `Part.assembly: bool`; `VBUS_FUSED`; `U_EFUSE`, `C_EFUSE_IN`, `C_EFUSE_DVDT`, `R_EFUSE_ILM`, and `J_TOUCH`; fitted `R_SIOC/R_SIOD`; V6 `D_LED`; a hand-installed set derived from `Part.assembly`.

- [ ] **Step 1: Add failing source-of-truth tests**

Add tests that assert the exact circuit rather than merely checking that references exist:

```python
def part(ref):
    return next(p for p in board_spec.PARTS if p.ref == ref)

def test_usb_efuse_is_between_fuse_and_every_vbus_load(self):
    self.assertEqual(part("F_USB").pins, {"1": "VBUS_IN", "2": "VBUS_FUSED"})
    self.assertEqual(part("U_EFUSE").pins, {
        "1": "EFUSE_DVDT", "2": "VBUS_FUSED", "3": "VBUS_FUSED",
        "4": "VBUS_FUSED", "5": "VBUS", "6": "NC_U_EFUSE_FLT",
        "7": "EFUSE_ILM", "8": "GND", "9": "GND",
    })
    self.assertEqual(part("C_EFUSE_IN").pins, {"1": "VBUS_FUSED", "2": "GND"})
    self.assertEqual(part("C_EFUSE_DVDT").pins, {"1": "EFUSE_DVDT", "2": "GND"})
    self.assertEqual(part("R_EFUSE_ILM").pins, {"1": "EFUSE_ILM", "2": "GND"})
    for load in ("U_BUCK", "R_BUCK_EN", "U_AMP", "R_AMP_SD", "C_AMP_BULK", "C_AMP"):
        self.assertNotIn("VBUS_FUSED", part(load).pins.values())
        self.assertIn("VBUS", part(load).pins.values())

def test_revised_camera_touch_and_led_parts(self):
    self.assertTrue(part("R_SIOC").fitted)
    self.assertTrue(part("R_SIOD").fitted)
    self.assertNotIn("TP_E0", {p.ref for p in board_spec.PARTS})
    self.assertEqual(part("J_TOUCH").pins, {"1": "TOUCH_E0", "2": "GND"})
    self.assertEqual(part("D_LED").value, "WS2812B-2020-V6")
    self.assertEqual(part("D_LED").lcsc, "C52917434")

def test_hand_installed_parts_are_owned_by_board_spec(self):
    expected = {"J_HEAT", "J_LCD_L", "J_LCD_R", "J_SERVO_L", "J_SERVO_R",
                "J_NTC", "J_SPK", "J_VMOT", "J_TOUCH"}
    actual = {p.ref for p in board_spec.PARTS
              if p.fitted and not p.assembly and p.ref.startswith("J_")}
    self.assertEqual(actual, expected)
```

Update BOM tests to derive `expected = {p.ref for p in board_spec.PARTS if export_bom.is_assembly_item(p)}` and compare the exported reference set with `expected`; assert `J_TOUCH` is hand-installed and both SCCB resistors are exported.

- [ ] **Step 2: Run the focused tests and capture the expected failures**

Run:

```sh
cd hardware/plush-toy-mainboard/scripts
python3 -m unittest test_board_spec test_export_bom -v
```

Expected: failures for absent `U_EFUSE`/`J_TOUCH`, old `F_USB` output, DNP SCCB resistors, old LED, and hard-coded assembly count.

- [ ] **Step 3: Implement the minimal parts and network changes**

Add `1.02k: C226838` and `3.3nF: C696855` to the LCSC lookup tables, define `U_EFUSE` with symbol `plush:TPS259531`, footprint `Package_SON:Texas_DSG0008A_WSON-8-1EP_2x2mm_P0.5mm_EP0.9x1.6mm_ThermalVias`, and LCSC `C2155674`. Change `F_USB.2` to `VBUS_FUSED`; add the three support parts; remove `TP_E0`; add the two-pin vertical JST-PH `J_TOUCH`; set SCCB pull-ups fitted; and change D_LED to V6 while retaining pins `1=NC_DOUT, 2=GND, 3=LED_RGB, 4=+3V3`.

Append `assembly: bool = True` after `pins` in the `Part` dataclass so existing positional helper calls retain their meaning. Mark all nine hand-installed connectors, test points, and mounting holes `assembly=False`. Derive `HAND_INSTALLED_REFS` from fitted connector parts with `assembly=False`; make `is_assembly_item()` return `part.fitted and part.assembly`; and pass `part.assembly` to `gen_schematic.place(..., in_bom=...)`. Replace all numeric assembly-count expectations with a set generated by `is_assembly_item()`.

Set the README schematic/layout/routing/manufacturing rows to `改版中`; do not retain the previous “静态检查完成” status while the old manufacturing package is invalidated by these source changes.

- [ ] **Step 4: Run the data tests**

Run:

```sh
python3 -m unittest test_config_pins test_board_spec test_export_bom -v
```

Expected: all tests pass; GPIO mapping remains unchanged; BOM expected-set comparison includes SCCB pull-ups and excludes nine hand-installed connectors.

- [ ] **Step 5: Commit the electrical source-of-truth change**

```sh
git add hardware/plush-toy-mainboard/scripts/board_spec.py \
        hardware/plush-toy-mainboard/scripts/gen_schematic.py \
        hardware/plush-toy-mainboard/scripts/export_bom.py \
        hardware/plush-toy-mainboard/scripts/test_board_spec.py \
        hardware/plush-toy-mainboard/scripts/test_export_bom.py \
        hardware/plush-toy-mainboard/README.md
git commit -m "feat(pcb): protect plush toy USB power input"
```

### Task 2: Add and verify the exact eFuse library symbol

**Files:**
- Modify: `hardware/plush-toy-mainboard/lib/plush.kicad_sym`
- Modify: `hardware/plush-toy-mainboard/scripts/test_project_lib.py:1-62`
- Modify: `hardware/plush-toy-mainboard/scripts/test_part_pins.py:50-69`

**Interfaces:**
- Consumes: `board_spec.U_EFUSE` pin map and KiCad official DSG0008A footprint.
- Produces: loadable `plush:TPS259531` with pins 1–8 plus exposed pad 9, and verified symbol/footprint parity.

- [ ] **Step 1: Add failing symbol and package tests**

Add a `Tps259531LibraryTest` that calls `test_part_pins.symbol_pins("plush:TPS259531")` and `footprint_pads(...)`, asserting both equal `{str(n) for n in range(1, 10)}`. Assert pin 9 exists so the exposed pad cannot silently remain ungrounded. Also assert D_LED's official footprint exposes pads 1–4 and its board-spec pins remain `1=DO, 2=GND, 3=DI, 4=VDD`, matching the V6 data sheet.

- [ ] **Step 2: Verify the test fails because the symbol is absent**

Run:

```sh
cd hardware/plush-toy-mainboard/scripts
python3 -m unittest test_part_pins -v
KP=/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3
$KP -m unittest test_project_lib -v
```

Expected: `KeyError: plush:TPS259531` or an equivalent missing-symbol failure.

- [ ] **Step 3: Add the exact project symbol**

Append a KiCad symbol named `TPS259531` to `lib/plush.kicad_sym`, using the TI pin names and electrical types: `1 dVdt input`, `2 EN/UVLO input`, `3 IN power_in`, `4 IN power_in`, `5 OUT power_out`, `6 FLT open_collector`, `7 ILM input`, `8 GND power_in`, `9 EP power_in`. Keep all nine pin numbers visible in the library definition.

- [ ] **Step 4: Run library, pin, netlist, and ERC tests**

Run:

```sh
python3 -m unittest test_part_pins test_netlist_roundtrip -v
KP=/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3
$KP -m unittest test_project_lib -v
```

Expected: symbol and footprint pads agree; generated schematic netlist matches `board_spec`; ERC has zero errors and FLT is explicitly NC.

- [ ] **Step 5: Commit the exact symbol**

```sh
git add hardware/plush-toy-mainboard/lib/plush.kicad_sym \
        hardware/plush-toy-mainboard/scripts/test_project_lib.py \
        hardware/plush-toy-mainboard/scripts/test_part_pins.py
git commit -m "feat(pcb): add exact TPS259531 symbol"
```

### Task 3: Lock placement, safety silkscreen, and the fabrication stackup

**Files:**
- Modify: `hardware/plush-toy-mainboard/scripts/placement.py:19-103`
- Modify: `hardware/plush-toy-mainboard/scripts/gen_pcb.py:99-345`
- Modify: `hardware/plush-toy-mainboard/scripts/test_pcb.py:18-315`

**Interfaces:**
- Consumes: all fitted parts from Task 1 and the TPS259531 package from Task 2.
- Produces: `SAFETY_SILK: tuple[tuple[str, float, float], ...]`, fixed critical-component coordinates, and the JLC04161H-7628 stackup in the generated board.

- [ ] **Step 1: Add failing placement, silk, and stackup tests**

Add PCB tests for the exact requirements:

```python
def distance(self, a, pa, b, pb):
    p = self.fps[a].FindPadByNumber(pa).GetPosition()
    q = self.fps[b].FindPadByNumber(pb).GetPosition()
    return ((mm(p.x - q.x) ** 2) + (mm(p.y - q.y) ** 2)) ** 0.5

def test_buck_and_esp32_local_parts_are_close(self):
    self.assertLessEqual(self.distance("U_BUCK", "4", "C_BUCK_IN", "1"), 2.5)
    self.assertLessEqual(self.distance("U_BUCK", "2", "C_BUCK_IN", "2"), 2.5)
    for ref in ("C_U1", "C_U1_BULK"):
        self.assertLessEqual(self.distance("U1", "2", ref, "1"), 4.0)
    for ref in ("R_EN", "C_EN"):
        self.assertLessEqual(self.distance("U1", "3", ref, "2" if ref == "R_EN" else "1"), 5.0)

def test_required_safety_silkscreen_is_present(self):
    texts = {t.GetText() for t in self.board.GetDrawings()
             if isinstance(t, pcbnew.PCB_TEXT) and t.GetLayer() == pcbnew.F_SilkS}
    self.assertTrue({"电机/加热专用 5V", "+", "-", "CH0 左", "CH1 右",
                     "必须串 KSD9700 65度 常闭", "VMOT 仅限 5V",
                     "头部触摸 E0 / GND"} <= texts)

def test_stackup_matches_jlc04161h_7628(self):
    text = PCB.read_text(encoding="utf-8")
    for needle in ('(thickness 0.035)', '(thickness 0.2104)',
                   '(thickness 0.0152)', '(thickness 1.065)'):
        self.assertIn(needle, text)
```

Retain the existing silk-size and pad-clearance tests so every new safety label must be at least 1.0mm/0.15mm and 0.25mm from pads.

- [ ] **Step 2: Generate the old PCB and verify the new tests fail**

Run:

```sh
cd hardware/plush-toy-mainboard/scripts
KP=/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3
$KP gen_pcb.py
$KP -m unittest test_pcb -v
```

Expected: missing new-part placement first; after all new parts have placement entries, failures identify the old buck/ESP32 distances, missing labels, and absent real stackup.

- [ ] **Step 3: Define deterministic critical placement and silk data**

Place `U_EFUSE` and its three support parts between F_USB and the buck/amp VBUS consumers. Convert U_BUCK, L_BUCK, C_BUCK_IN, feedback parts, C_U1/C_U1_BULK, and R_EN/C_EN from loose `NEAR` placement to fixed `ANCHORS` that satisfy the pad-distance assertions. Place `J_TOUCH` near U_TOUCH at the lower board edge with its cable direction unobstructed.

Replace `HEATER_SILK` with a deterministic function anchored to the actual footprint and pad positions:

```python
def safety_silk(fps) -> tuple[tuple[str, float, float], ...]:
    def at_ref(ref, dx, dy):
        p = fps[ref].GetPosition()
        return p.x * 1e-6 + dx, p.y * 1e-6 + dy

    def at_pad(ref, number, dx, dy):
        p = fps[ref].FindPadByNumber(number).GetPosition()
        return p.x * 1e-6 + dx, p.y * 1e-6 + dy

    return (
        ("必须串 KSD9700 65度 常闭", 70.0, 39.6),
        ("电机/加热专用 5V", *at_ref("J_VMOT", -7.5, -5.0)),
        ("+", *at_pad("J_VMOT", "1", -2.0, 0.0)),
        ("-", *at_pad("J_VMOT", "2", -2.0, 0.0)),
        ("CH0 左", *at_ref("J_SERVO_L", -5.0, 0.0)),
        ("CH1 右", *at_ref("J_SERVO_R", -5.0, 0.0)),
        ("VMOT 仅限 5V", *at_ref("C_VMOT_BULK", 0.0, -6.5)),
        ("头部触摸 E0 / GND", *at_ref("J_TOUCH", 0.0, -3.0)),
    )
```

If any initial fixed offset fails the existing text/pad clearance tests, move the owning fixed component in `ANCHORS` and update the corresponding numeric offset together; do not shrink the text.

- [ ] **Step 4: Generate all independent silk texts and inject the exact stackup**

Factor `add_silk_text(board, text, x, y)` in `gen_pcb.py`, add every entry in `SAFETY_SILK`, pass every resulting bounding box to `tidy_silkscreen`, and add `apply_stackup(path: Path)` that inserts KiCad's `(stackup ...)` block inside `(setup ...)` with copper/dielectric sequence `0.035/0.2104/0.0152/1.065/0.0152/0.2104/0.035mm`. Call it after every `board.Save()` that creates the base board, before `project_rules.apply()`.

- [ ] **Step 5: Regenerate and run PCB placement tests**

Run:

```sh
$KP gen_pcb.py
$KP -m unittest \
  test_pcb.PcbTest.test_outline_is_90_by_60 \
  test_pcb.PcbTest.test_four_copper_layers \
  test_pcb.PcbTest.test_every_fitted_part_placed_inside_outline \
  test_pcb.PcbTest.test_pad_nets_match_spec \
  test_pcb.PcbTest.test_no_courtyard_overlap_on_same_side \
  test_pcb.PcbTest.test_buck_and_esp32_local_parts_are_close \
  test_pcb.PcbTest.test_required_safety_silkscreen_is_present \
  test_pcb.PcbTest.test_silkscreen_texts_do_not_overlap \
  test_pcb.PcbTest.test_silkscreen_texts_clear_of_pads \
  test_pcb.PcbTest.test_silkscreen_text_size_meets_jlcpcb \
  test_pcb.PcbTest.test_stackup_matches_jlc04161h_7628 \
  test_pcb.PcbTest.test_single_sided_assembly -v
```

Expected: all selected placement, overlap, safety-silk, stackup, and single-sided-assembly tests pass. Routing-dependent tests are intentionally deferred until Task 4.

- [ ] **Step 6: Render placement and visually inspect labels and polarity**

Run:

```sh
/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli pcb render --side top --width 1600 --height 1100 \
  -o ../renders/place_top.png ../plush-toy-mainboard.kicad_pcb
```

Expected: all eight safety texts are readable, `+/-` align with J_VMOT pins 1/2, CH0/CH1 align with left/right servo headers, and J_TOUCH insertion is unobstructed.

- [ ] **Step 7: Commit placement, stackup, and silkscreen generation**

```sh
git add hardware/plush-toy-mainboard/scripts/placement.py \
        hardware/plush-toy-mainboard/scripts/gen_pcb.py \
        hardware/plush-toy-mainboard/scripts/test_pcb.py \
        hardware/plush-toy-mainboard/renders/place_top.png
git commit -m "feat(pcb): lock safe plush toy component placement"
```

### Task 4: Generate and protect critical power, reset, and XCLK copper

**Files:**
- Modify: `hardware/plush-toy-mainboard/scripts/fanout.py:29-323`
- Modify: `hardware/plush-toy-mainboard/scripts/post_route.py:25-619`
- Modify: `hardware/plush-toy-mainboard/scripts/test_pcb.py:166-315`
- Modify: `hardware/plush-toy-mainboard/scripts/test_post_route.py:12-40`

**Interfaces:**
- Consumes: the fixed pad positions from Task 3.
- Produces: `route_usb_efuse()`, `route_buck_hot_loop()`, `route_u1_power_and_en()`, and `route_camera_xclk_guards()` in `Fanout`; `CRITICAL_NETS = {"BUCK_SW", "CAM_XCLK"}` protected from post-route replacement.

- [ ] **Step 1: Add failing critical-copper geometry tests**

Add helpers that collect tracks/vias by net and endpoint, then assert:

```python
def test_buck_sw_is_short_top_only_and_vialess(self):
    copper = [t for t in self.board.GetTracks() if t.GetNetname() == "BUCK_SW"]
    tracks = [t for t in copper if t.GetClass() == "PCB_TRACK"]
    vias = [t for t in copper if t.GetClass() == "PCB_VIA"]
    self.assertEqual(vias, [])
    self.assertTrue(tracks)
    self.assertEqual({t.GetLayer() for t in tracks}, {pcbnew.F_Cu})
    self.assertLessEqual(sum(mm(t.GetLength()) for t in tracks), 3.0)

def test_camera_xclk_is_top_only_vialess_and_guarded(self):
    xclk = [t for t in self.board.GetTracks() if t.GetNetname() == "CAM_XCLK"]
    self.assertTrue(xclk)
    self.assertEqual([t for t in xclk if t.GetClass() == "PCB_VIA"], [])
    self.assertEqual({t.GetLayer() for t in xclk}, {pcbnew.F_Cu})
    guards = [t for t in self.board.GetTracks()
              if t.GetNetname() == "GND" and t.GetClass() == "PCB_TRACK"
              and t.GetLayer() == pcbnew.F_Cu]
    self.assertGreaterEqual(len(guards), 2)
```

Add exact endpoint/length tests for U1.3→R_EN/C_EN local EN copper (≤10mm, F.Cu, no via), nearest GND via distance (≤1.0mm) for U_BUCK.2, C_BUCK_IN.2, C_U1.2, and C_U1_BULK.2, XCLK guard gap (0.5–0.8mm), guard-via pitch (≤3.0mm), and absence of >3mm parallel overlap within 0.7mm between XCLK and every non-GND signal.

- [ ] **Step 2: Run the routing geometry tests against the unrouted board**

Run:

```sh
cd hardware/plush-toy-mainboard/scripts
$KP -m unittest test_pcb test_post_route -v
```

Expected: new critical-copper tests fail because the deterministic methods do not exist or the nets are unrouted.

- [ ] **Step 3: Add deterministic critical routing methods**

In `Fanout`, add the four named methods and call them before `escape_camera_fpc()` in `run()`. Use `add_track()` for top copper and `add_via()` for local plane connections. Route BUCK_SW directly U_BUCK.3→L_BUCK.1 with no via; connect U_BUCK.4→C_BUCK_IN.1 and place ground vias within 1mm of both ground pads; route U1 decoupling and local EN before the long switch branch; route CAM_XCLK U1.8→J_CAM.13 on F.Cu and add two GND guard tracks with stitched vias at both endpoints and ≤3mm intervals.

- [ ] **Step 4: Prevent general routing from replacing critical copper**

In `post_route.py`, add `CRITICAL_NETS` and exclude those nets from `reroute_long_power_tracks()` and `open_pairs()` repair. Add a regression test that constructs a narrow BUCK_SW track longer than 2mm and proves `reroute_long_power_tracks()` leaves it untouched; the geometry test remains responsible for rejecting an invalid critical route.

- [ ] **Step 5: Run fanout and focused geometry tests**

Run:

```sh
$KP gen_pcb.py
$KP fanout.py
$KP -m unittest test_pcb test_post_route -v
```

Expected: critical-copper and placement tests pass; only tests requiring all remaining nets to be routed may fail.

- [ ] **Step 6: Commit deterministic critical routing**

```sh
git add hardware/plush-toy-mainboard/scripts/fanout.py \
        hardware/plush-toy-mainboard/scripts/post_route.py \
        hardware/plush-toy-mainboard/scripts/test_pcb.py \
        hardware/plush-toy-mainboard/scripts/test_post_route.py
git commit -m "feat(pcb): lock critical plush toy routing"
```

### Task 5: Emit direct JLCPCB CPL and validate the real assembly set and stackup

**Files:**
- Modify: `hardware/plush-toy-mainboard/scripts/fab_tools.py:1-68`
- Modify: `hardware/plush-toy-mainboard/scripts/export_fab.sh:18-45`
- Modify: `hardware/plush-toy-mainboard/scripts/test_export_bom.py:16-60`

**Interfaces:**
- Consumes: KiCad raw CSV fields `Ref,Val,Package,PosX,PosY,Rot,Side` and `export_bom.is_assembly_item()`.
- Produces: `filter_positions(source: Path, destination: Path)` with exact JLCPCB columns and `expected_assembly_refs() -> set[str]` used by `validate(fab)`.

- [ ] **Step 1: Add failing CPL and package-validation tests**

Replace the current filter assertion with:

```python
fab_tools.filter_positions(source, destination)
with destination.open(newline="") as stream:
    reader = csv.DictReader(stream)
    self.assertEqual(reader.fieldnames,
                     ["Designator", "Mid X", "Mid Y", "Layer", "Rotation"])
    self.assertEqual(list(reader), [{
        "Designator": "C_ADC", "Mid X": "3", "Mid Y": "4",
        "Layer": "Top", "Rotation": "0",
    }])
```

Add cases for `bottom→Bottom`, negative/≥360 rotations normalized into `[0, 360)`, missing raw columns raising `ValueError`, BOM/CPL set mismatch, duplicate CPL references, and a Gerber job fixture whose dielectric thickness differs from the required stackup.

- [ ] **Step 2: Run manufacturing unit tests and verify failure**

Run:

```sh
cd hardware/plush-toy-mainboard/scripts
python3 -m unittest test_export_bom -v
```

Expected: old KiCad column names, lowercase layer values, and hard-coded count behavior fail.

- [ ] **Step 3: Implement exact conversion and dynamic validation**

Set `CPL_FIELDS = ("Designator", "Mid X", "Mid Y", "Layer", "Rotation")`; map `Ref→Designator`, `PosX→Mid X`, `PosY→Mid Y`, `top→Top`, `bottom→Bottom`, and `float(Rot) % 360` formatted without unnecessary trailing zeros. Change `_position_refs()` to read `Designator`. Implement:

```python
def expected_assembly_refs() -> set[str]:
    return {part.ref for part in board_spec.PARTS if export_bom.is_assembly_item(part)}
```

Require both BOM and CPL sets to equal this function, with no hard-coded quantity. Parse `plush-toy-mainboard-job.gbrjob` and compare the ordered copper/dielectric thicknesses with `(0.035, 0.2104, 0.0152, 1.065, 0.0152, 0.2104, 0.035)` within 0.0001mm.

- [ ] **Step 4: Run manufacturing tests**

Run:

```sh
python3 -m unittest test_export_bom -v
```

Expected: all tests pass and expected assembly count is derived from `board_spec`.

- [ ] **Step 5: Commit the manufacturing contract**

```sh
git add hardware/plush-toy-mainboard/scripts/fab_tools.py \
        hardware/plush-toy-mainboard/scripts/export_fab.sh \
        hardware/plush-toy-mainboard/scripts/test_export_bom.py
git commit -m "feat(pcb): export JLCPCB-ready placement data"
```

### Task 6: Regenerate, autoroute, and converge the complete board

**Files:**
- Regenerate: `hardware/plush-toy-mainboard/plush-toy-mainboard.kicad_sch`
- Regenerate: `hardware/plush-toy-mainboard/plush-toy-mainboard.kicad_pcb`
- Regenerate: `hardware/plush-toy-mainboard/renders/schematic.pdf`
- Modify if a reproducible failure requires it: the narrowest owning generator or regression test from Tasks 1–5.

**Interfaces:**
- Consumes: all generator and validation interfaces from Tasks 1–5.
- Produces: routed PCB with zero unconnected items, zero parity findings, zero DRC errors, and only the two exact reviewed U1 silk-edge warnings.

- [ ] **Step 1: Run the complete pre-route suite**

Run:

```sh
cd hardware/plush-toy-mainboard/scripts
python3 -m unittest test_kicad_env test_config_pins test_board_spec test_part_pins \
  test_netlist_roundtrip test_export_bom -v
$KP -m unittest test_project_lib -v
/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli sch export pdf \
  -o ../renders/schematic.pdf ../plush-toy-mainboard.kicad_sch
```

Expected: all tests pass; this regenerates the schematic and proves ERC/netlist equivalence.

- [ ] **Step 2: Generate the board and deterministic copper**

Run:

```sh
$KP gen_pcb.py
$KP fanout.py
$KP -m unittest test_pcb -v
```

Expected: all non-full-routing tests pass and every critical geometry assertion passes before autorouting.

- [ ] **Step 3: Autoroute non-critical nets**

Run:

```sh
JAVA_TOOL_OPTIONS=-Djava.awt.headless=true $KP route.py 30
```

Expected: Freerouting exits zero and writes `build/board.ses`; it does not route on In1/In2 or alter pre-routed BUCK_SW/XCLK copper.

- [ ] **Step 4: Apply candidate-only deterministic completion**

Run:

```sh
$KP post_route.py --apply
```

Expected: the script promotes the candidate only when `violations` matches the exact two U1 silk-edge warnings and both `unconnected_items` and `schematic_parity` are empty.

- [ ] **Step 5: Diagnose any non-convergence before changing code**

For each failure, save the DRC JSON and identify the owning generator. Add one regression assertion reproducing that exact geometric or net failure, run it to confirm failure, make the smallest deterministic generator change, then repeat Steps 2–4. Do not whitelist new DRC findings and do not delete critical-route assertions.

- [ ] **Step 6: Run the complete routed-board suite**

Run:

```sh
python3 -m unittest test_kicad_env test_config_pins test_board_spec test_part_pins \
  test_netlist_roundtrip test_export_bom -v
$KP -m unittest test_project_lib test_pcb test_drc test_post_route -v
```

Expected: every test passes; DRC reports exactly two reviewed U1 silk-edge warnings, zero unconnected items, and zero schematic-parity findings.

- [ ] **Step 7: Commit generated electrical and routed board outputs**

```sh
git add hardware/plush-toy-mainboard/plush-toy-mainboard.kicad_sch \
        hardware/plush-toy-mainboard/plush-toy-mainboard.kicad_pcb \
        hardware/plush-toy-mainboard/renders/schematic.pdf
git commit -m "feat(pcb): reroute protected plush toy mainboard"
```

Before committing, inspect `git diff --cached --name-only`; remove unrelated files from the index and confirm the previously dirty schematic is now present only as intentional generated content from the new `board_spec`. If Step 5 required a generator fix, commit that focused source/test pair immediately after its regression passes, before staging these two generated outputs.

### Task 7: Export fabrication deliverables and synchronize operator documentation

**Files:**
- Modify: `hardware/plush-toy-mainboard/README.md:1-89`
- Modify: `hardware/plush-toy-mainboard/TESTING.md:1-53`
- Modify: `docs/superpowers/specs/2026-09-14-plush-toy-pcb-4layer-design.md`
- Regenerate: `hardware/plush-toy-mainboard/fab/bom.csv`
- Regenerate: `hardware/plush-toy-mainboard/fab/positions.csv`
- Regenerate: `hardware/plush-toy-mainboard/fab/gerber/**`
- Regenerate: `hardware/plush-toy-mainboard/fab/gerber.zip`
- Regenerate: `hardware/plush-toy-mainboard/renders/final_top.png`
- Regenerate: `hardware/plush-toy-mainboard/renders/final_bottom.png`

**Interfaces:**
- Consumes: the fully verified board from Task 6 and `export_fab.sh` atomic export.
- Produces: orderable JLCPCB package, current status documentation, and physical validation checklist.

- [ ] **Step 1: Update design and operator documentation before final export**

Document the eFuse block and thresholds, SCCB fitted state, X7R C_NTC, V6 LED, J_TOUCH pinout, exact JLC04161H-7628 stack, nine hand-installed connectors, dynamic automated assembly count, and direct JLCPCB CPL format. Add explicit order notes: rails only on top/bottom; no left-side material/copper; preserve about 15mm antenna clearance; `VMOT` accepts only 5V.

Extend `TESTING.md` with oscilloscope checks for USB hot-plug clamp and rise time, 3V3 ripple at Wi-Fi load, XCLK waveform/image artifacts, J_TOUCH cable strain and baseline, V6 LED color, and antenna range in the installed enclosure.

- [ ] **Step 2: Export all manufacturing files atomically**

Run:

```sh
cd hardware/plush-toy-mainboard
./scripts/export_fab.sh
```

Expected: DRC gate passes first; `fab/positions.csv` has exact JLCPCB headers; BOM/CPL sets equal the dynamically derived fitted assembly set; Gerber files are non-empty; job stackup matches JLC04161H-7628; final top/bottom renders are replaced only after validation.

- [ ] **Step 3: Inspect final outputs**

Check `renders/final_top.png`, `renders/final_bottom.png`, the Gerber job, BOM, and CPL. Confirm connector polarity/channel labels, eFuse/buck orientation, LED pin 1, IC pin 1, diode polarity, capacitor polarity, XCLK guards, antenna keepout, drill layers, and all hand-installed connectors.

- [ ] **Step 4: Run the final static verification from a clean command sequence**

Run:

```sh
cd hardware/plush-toy-mainboard/scripts
python3 -m unittest test_kicad_env test_config_pins test_board_spec test_part_pins \
  test_netlist_roundtrip test_export_bom -v
$KP -m unittest test_project_lib test_pcb test_drc test_post_route -v
python3 fab_tools.py validate ../fab
git diff --check
```

Expected: all tests pass; manufacturing validation passes; no whitespace errors; only the two exact U1 warnings remain in KiCad DRC.

- [ ] **Step 5: Commit documentation and manufacturing outputs**

```sh
git add docs/superpowers/specs/2026-09-14-plush-toy-pcb-4layer-design.md \
        hardware/plush-toy-mainboard/README.md \
        hardware/plush-toy-mainboard/TESTING.md \
        hardware/plush-toy-mainboard/fab \
        hardware/plush-toy-mainboard/renders
git commit -m "docs(pcb): publish plush toy respin outputs"
```

- [ ] **Step 6: Verify commits and push the current branch**

Run:

```sh
git status --short
git log --oneline --decorate -8
git push fork feat/plush-toy-design
```

Expected: only preserved unrelated `.idea/` and `sdkconfig.bak.*` files remain untracked; the push updates `fork/feat/plush-toy-design`. Report static verification results separately from the physical checks that still require fabricated hardware.
