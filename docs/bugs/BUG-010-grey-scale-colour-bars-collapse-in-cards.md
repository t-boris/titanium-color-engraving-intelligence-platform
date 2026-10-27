---
type: bug
id: BUG-010
title: Grey-scale colour strips collapse to two pixels in scale cards
status: fixed
severity: medium
reporter: Boris Tsekinovsky
created: 2026-10-27
updated: 2026-10-27
provenance: Operator screenshot of the photo-zone scale selector
---

# Grey-scale colour strips collapse to two pixels in scale cards

The photo-zone sidebar shows a thin vertical line where each card should show the measured colours. The gradient is present and
valid. Electron's default button alignment is `flex-start`: the empty `.ge-bar` span has no intrinsic width and collapses to its
two one-pixel borders. The two power labels also sit together instead of at opposite ends of the card.

Fixed in 0.37.2 by explicitly stretching the children of the shared column-layout `.ge-scale` button. This applies to the photo-zone
selector and other full scale cards. Compact list strips retain their explicit 44 × 14 pixel dimensions.

Validation uses the actual `App.h`, `PhotoPanels.scaleCard` and stylesheet in a hidden Electron 33 window with an isolated temporary
profile. Before the change, the strip measured 2 × 22 pixels at card widths 226, 320 and 600. Afterwards it measures 204, 298 and
578 × 22 pixels respectively; Min/Max span the same width, the computed gradient is retained, and compact strips remain 44 × 14.
Screenshots were captured for visual verification. The operator's running window and workshop are not restarted by this check.

Full local suite: 2348 passed, none skipped. The installed stylesheet also passes the same hidden Electron geometry checks and
the application's Developer ID signature verifies after installation.

The complete signed 0.37.2 desktop release was then installed locally at the operator's request. The frozen core, packaged app and
installed app pass their hidden smoke checks on temporary workshops. The installed backend reports 0.37.2 and its stylesheet matches
the source. No operator workshop is used by these checks.
