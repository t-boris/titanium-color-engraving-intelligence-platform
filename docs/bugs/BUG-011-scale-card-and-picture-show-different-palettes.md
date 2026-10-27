---
type: bug
id: BUG-011
title: Selected scale card and picture preview show palettes from different engraving sizes
status: fixed
severity: high
reporter: Boris Tsekinovsky
created: 2026-10-27
updated: 2026-10-27
provenance: Operator screenshot after the scale-strip visibility repair
---

# Selected scale card and picture preview show different palettes

Work 46, photo zone 1: 150 mm/s, 60 kHz, 250 ns, interval 0.0212 mm; Min 2.5%, Max 30.2%, width about 121.4 mm.
The default scale summary selects the 38.4 mm grey ramp, span 1–30%, with violet and blue. The actual picture and detail select the
121.2 mm measurement, span 3.726–29.101%, with pale straw and grey. At 15% the former is Lab [62.1,-4.7,-14.2], the latter
[79.8,-0.4,11.0]. Both are valid measurements; showing one as the choice for a picture predicted with the other is misleading.

Fixed in 0.37.3:

- `/api/grey-scales` accepts `row_mm`; its summaries use the same size selection as the detailed scale and picture.
- Work and photo-zone selectors request the picture's width; embedded photo-zone caches include the width.
- The selected card and compact list row use the detailed response's current Min/Max and grey levels. The card and picture strip
  share the same 64 levels, colours and unmeasured hatching. Cards state the displayed width and any nearest-size fallback.
- Resizing reloads the choices. Obsolete size responses cannot replace a later width or undo. The standalone scale page also
  synchronizes the selected card when its width or power controls change.

Regression coverage includes actual short/long measurements with different colours, the list/detail API contract, selected card
versus preview colours and unknowns, Min/Max changes, resize and a deliberately delayed response after undo. The measured evidence
and the colour prediction model are unchanged by this display fix.

Validation: 2353 local tests passed with none skipped (175.46 s). A hidden Electron window using the actual work-46 API data compares
all 64 displayed segments: card and picture strip have identical colours, unknown hatching and power tooltips (six unknown segments
for the current 2.5–30.2% range). The displayed width is 121.4 mm and the source measurement is 121.2 mm. The signed 0.37.3 app is
installed locally; core, packaged and installed hidden smoke checks pass on temporary workshops. Installed UI assets match source,
the backend reports 0.37.3, and deep strict code-signature verification passes. The operator must restart the existing app to load
the updated backend and selector together.
