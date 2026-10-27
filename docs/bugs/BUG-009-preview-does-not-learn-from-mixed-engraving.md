---
type: bug
id: BUG-009
title: Mixed-work preview fails to learn its measured colours and photo tones
status: fixed
severity: high
reporter: Boris Tsekinovsky
created: 2026-10-27
updated: 2026-10-27
provenance: Operator reported Inna & Emmy 2, then clarified that the preview must resemble the engraving as closely as possible
---

# Mixed-work preview fails to learn its measured colours and photo tones

Photo 153 (`IMG_3443.DNG`), work 46, accepted 2026-10-27. Its ColorChecker residual is 3.546 ΔE and the element-anchor alignment is
valid (median residual 0.08 mm). Eight of twelve vector layers differ visibly from their exported promise, area-weighted error
20.24 ΔE. C05 promised olive green, Lab [58.88, -6.28, 29.74], and measured brown, [53.20, 12.30, 26.13], error 19.76 ΔE.

The preview's colour came from a 5.1 mm calibration fill. The engraving's individual-shape scan rows measure 33.2 mm. The preview
incorrectly summed separate shapes' rows as 69.2 mm. New evidence did not reach the chosen recipe: calibration fills and colour-image
fills had different task keys, and a LightBurn 2.2 re-save added `fgPathAlgorithm=CutGantry`. A first measurement on the work's own
plate could also change an entry id previously taken from another plate.

The photographed image matches export 2 (250 ns, Min 1 %, Max 30 %), while the review selected export 3 on a vector-only tie
(350 ns, Min 2.9 %, Max 28.2 %). The photo layer was omitted from the comparison pictures. Its pre-existing curve was measured at
38.4 mm and applied to a 121.2 mm image; against the photographed grey bins its median error is 17.99 ΔE, maximum 60.87 ΔE.
The new profile (rho 0.422) was labelled weak and discarded, so its lost tones never improved the prediction. Correlation alone
cannot establish the reliability of a titanium colour scale: even a correctly aligned picture can engrave with non-monotone tones.

Fixed in 0.37.1:

- Palette evidence shares measurements of physically identical area fills across their area-task labels and the explicit/omitted
  default path algorithm. Every other execution control and unknown setting stays distinct; text and line evidence stay excluded.
  The stored task records and palette ids remain available. Automatic choices count an equivalent recipe once. Chart measurements
  supersede older measurement bases in work previews; the colour map retains the older evidence and its superseded status.
- Existing work ids from another plate resolve to the current recipe evidence without rewriting colouring, variants or history.
- Preview and colour selection use individual-shape fill order and the same joining of touching regions as the exported file.
  The work-list thumbnail and inscriptions also read current evidence instead of saved layer colours.
- An unchanged bitmap's grey and alpha pixels are fingerprinted against the work's stored exports. This proves its storage
  orientation independently of tone correlation. A valid, accepted low-correlation profile with that proof contributes to its own
  settings and size; an edited/missing bitmap, wrong flip or invalid alignment does not. Immutable observations stay unchanged.
- Export matching includes image mode, Min/Max, pulse width and other recorded scan controls. Reviews show photo errors against
  the measurements known at export, differences from the latest file, and both comparison pictures include the actual embedded
  bitmap rendered with the prior or measured tone curve, in its measured transform and opacity.
  The comparison also reopens the split, dimensions and smoothing saved with that export, so a later re-split or resize of the work
  cannot redraw the old engraving on the new regions.
- The editor states which vector layers and photo zones estimate a size that has not been measured. On startup versioned derived
  reviews and work-list attention counts are rebuilt for existing results.

Validation: regression tests in `tests/test_preview_feedback.py`, the existing palette, size, photo, review, laboratory-parity,
golden-evidence and UI suites. On a database copy, replaying export 2 with the now-available evidence reproduces all twelve vector
layers' photographed median colours to floating-point precision and includes all fifteen photo bins. This is a check that the
accepted result reaches its preview, not independent evidence of the next engraving's accuracy. The actual bitmap comparison
shows the washed-out face and dog in the measured panel. A future engraving remains the independent repeat.

Installation verification caught the operator's newer split (versions 4 and 5, made while the investigation ran). With a fresh copy of
that state, both comparison PNGs are byte-for-byte identical to the archived version-1 comparison; the current split and colouring
remain untouched. A regression test re-splits, resizes and changes smoothing after engraving, then checks both old comparison PNGs.
