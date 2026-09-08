# Plush Toy Eye Themes Design

## Goal

When a person says “换眼睛”, the plush toy changes to another eye theme.
The first release provides 20 original, built-in themes and keeps the selected
theme after restart.

## Scope and source material

The Adafruit Uncanny Eyes guide is visual reference only. Its included designs
(`defaultEye`, `noSclera`, `dragonEye`, and `goatEye`) are not copied as image
or table assets: the upstream repository does not declare a reuse license, its
graphics target 128x128 displays, and the plush toy renders 240x240 eyes.

The firmware will instead add original, procedural themes inspired only by the
high-level categories: natural eye, no-sclera eye, dragon-style eye, and
horizontal-pupil eye.

## Theme model

`EyeTheme` is an immutable board-local description containing:

- stable numeric ID and MCP-facing name;
- iris base color and optional inner/outer accent colors;
- sclera treatment (light, dark, or omitted);
- pupil shape (round, vertical slit, horizontal slit);
- eyelid profile and whether eye motion is constrained.

The initial catalog contains 20 themes. It includes blue, green, purple, gold,
amber, and rose natural eyes; several dark/no-sclera variants; several
vertical-slit dragon-style variants; and horizontal-pupil variants. Theme IDs
are stable persistent values; visual names are human-readable aliases and are
not NVS keys.

The existing `EyeState` continues to carry live gaze, blink, pupil-scale, and
emotion values. The renderer combines the chosen immutable theme with that
live state each frame. Thus idle animation and emotion changes are retained
rather than replaced by static bitmaps.

## Control flow

1. Board initialization reads the selected theme ID from a new board-scoped
   NVS setting; an absent or invalid value selects the first theme.
2. The board registers `self.eyes.change_theme`.
3. A call with no `theme` argument advances to the next catalog entry,
   wrapping after the twentieth.
4. A call with a known theme name selects it directly. An unknown name returns
   a clear MCP error and leaves the current theme unchanged.
5. The board persists the stable ID only after the display accepts the change,
   then requests a full redraw.

The tool description explicitly maps “换眼睛” to advancing a theme and maps
requests such as “换成龙眼” or “换成绿色眼睛” to named selection. It does not
alter the independent RGB/BGR panel calibration setting.

## Rendering and safety

All theme changes are scheduled through the display's existing synchronization
path. The change performs one whole-eye redraw, while ordinary gaze and blink
updates retain dirty-rectangle rendering. Overlay mode (provisioning QR or
upgrade progress) remains authoritative: a theme selection made while an
overlay is visible is stored and appears when `ShowEyes()` resumes eye mode.

No image files, runtime downloads, new network dependencies, or large frame
buffers are added. The design remains compatible with both existing round
screens and their shared SPI bus.

## Tests and physical acceptance

Host tests will verify the full 20-entry catalog, next-theme wraparound,
name-to-ID resolution, rendering distinctions for pupil/sclera variants, and
dirty-rectangle escalation to a full redraw on a theme change. A board-level
test will verify the MCP schema exposes an optional theme name.

On hardware, acceptance requires: saying “换眼睛” repeatedly visibly cycles
through distinct themes; asking for a named theme selects the expected look;
blinking and gaze continue to animate; a reboot retains the choice; and a QR
overlay still covers both eyes and returns to the chosen theme.
