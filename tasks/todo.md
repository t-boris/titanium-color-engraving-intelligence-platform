# Element-anchored registration of unmarked works (framed artwork)

Branch: `feat/laser-device-profiles`. Goal (user, 2026-10-16): the photograph of a finished work is aligned to its
LightBurn file by finding a few reliable elements, trusting them, and computing every other element from the file
distances. Parts hidden under a frame are inferred, never measured.

Pilot pair: `unbreakable.lbrn2` (19 layers, 235 closed vectors) + `IMG_3281.DNG` (framed, no reference chart).
Prototype with measured results: session scratchpad `proto/` (coarse 8-orientation search, per-element anchors,
robust homography, hold-out test).

## Scope

- [x] 0. Record the decisions in MarkView first (DEC element anchors, DEC frame window, REQ registration, REQ exact geometry).
- [x] 1. `lightburn.py`: exact vector geometry (Bezier edges, sub-paths, holes, closed flag per loop).
- [x] 2. `photo.layer_mask`: honour holes of a shape.
- [x] 3. New module `anchoring.py`: edge map, frame window, orientation search, element anchors, robust fit, classification, uncertainty.
- [x] 4. `ingest._align`: use anchoring before `register_geometry` for unmarked works; manual four corners stay the fallback (REQ-013).
- [x] 5. Measurement: the frame window limits the visible surface; partly hidden elements are measured on their visible part only.
- [x] 6. Overlay + review report: statuses (anchor / confirmed / computed / hidden), hidden margins, orientation margin.
- [x] 7. UI strings (ru/en), `test_i18n_coverage` stays green.
- [x] 8. Tests: geometry, mask holes, synthetic framed work (perspective + frame), ingest end to end, fallbacks.
- [x] 9. Run the real pilot pair through the real code path and compare with the prototype numbers.
- [x] 10. Full test suite; review section below.

## Rules kept

- Measured beats computed; a hidden element is never measured, only reported as inferred.
- No silent guessing (REQ-003): too few anchors or an ambiguous orientation raises `PhotoError`, the operator places four corners.
- Reference chart is still mandatory (REQ-009); alignment does not change that gate.
- Do not touch unrelated uncommitted work in the tree; no commit unless asked.

## Added after the goal hook (REQ-025, DEC-050, DEC-051)

- [x] 11. Complete capture: nested `SubLayer` settings, `Group` transforms (child XForm first, then the groups above), unsupported shapes counted per layer and noted, image object settings in the layer's settings.
- [x] 12. A layer is not sampled where a later layer engraves over it (burn order = priority, then index).
- [x] 13. Run order (`priority`) is not stored in the recipe of new observations; keys of existing data unchanged (tested against the previous algorithm).
- [x] 14. Whole path of a framed pair checked, reviewed and accepted into observations (synthetic pair with chart).

## Decisions of the operator (2026-10-16) and what was done

- Commit: one commit with the whole tree, no push.
- MarkView: DEC-048..051 accepted, REQ-023..025 approved.
- Old measurement history: removed on request (244 observations, 19 pairs with their stored file copies, 18 capability findings). A verified
  copy of the database and of the files is in `~/.titanium-platform/backup-20261016-142236-before-reset-of-observations`; to restore, stop the
  application and copy `titanium.sqlite` and `files/` back. Device, passport documents, lens, profile, titanium stock, plans, plates and
  research notes were kept. The change is recorded in the audit log.

## Checked against the operator's own files (170 LightBurn files in `Dropbox/Sirius Art`, read only)

- All 170 parse without errors in 26 s. They contain 2370 groups nested up to 7 deep, 86 image layers (grayscale, 3dslice, stucki, jarvis,
  sketch, threshold), 99 image objects, 95 texts (all carry a converted outline) and 45 ellipses; nothing is left unread.
- Group transforms: LightBurn's own thumbnail in the file matches the new reading (circle, letter D and plants of DACUSAN-1; both cards of
  the vCard), while ignoring group transforms shrinks or scatters the drawing.
- `BackupPath` carries the same XForm as its text object (found on real data; the first guess applied it twice and was fixed).
- Image layers: mode, kind (tonal / depth), dpi, dot width and correction, cleanup pass, passes, sub-layer, picture processing; the picture
  is PNG in `Data`, shared by the objects of one file (DEC-052, REQ-026). The tonal profile is validated on synthetic photographs only.

## Pilot pair accepted by the operator (2026-10-16)

Pair 21 (`unbreakable.lbrn2` + `IMG_3281.DNG`, profile JPT MOPA M7 60W) was created in the running application, reviewed and accepted by the
operator: 19 observations, alignment `element anchors`, camera-relative (none model-eligible), run order not in the recipe.

## Photo engraving checked on the operator's own pair (2026-10-16): `Inna - 2.lbrn2` + `IMG_3283.DNG`

- One grayscale image layer: power 5..16.1 %, 300 ns, 60 kHz, 128 mm/s, 1503 dpi. The grey level of the picture sets the power and the power sets
  the oxide colour (the operator's method, confirmed by LightBurn's documentation: Min power for the lightest, Max for the darkest).
- `picturing.py`: the picture's silhouettes (edge maps of the three Lab channels) are matched to the photograph over 8 orientations, refined by
  ECC. Orientation: vertical mirror, margin 2.1 times; hidden by the frame 2.9 / 7.3 / 3.8 / 3.2 mm (left, right, top, bottom); 5.7 s for the check.
- Tonal profile on the real photograph: smooth and monotone, near black and neutral at about 14 % power, brown and most coloured at about 7 %
  (rank correlation with grey: L* 0.64..0.80, a* -0.64, b* 0.50..0.72). DEC-052, DEC-054, REQ-026 and REQ-027 accepted on this evidence.
- The frame of that photograph is brushed metal; the old dark-frame detector does not find it, the step at the inner edge does.

## Still open, and why

- Brightness, contrast and gamma of LightBurn are recorded and listed in the profile, not modelled (they do not reorder grey levels); the
  dithering of other modes is not modelled; the grey-to-power rule is the documented linear one, a forum reply says it follows the sRGB curve.
- The operator asked for two changes of the application that are not done yet and need a plan first: (1) experiments as single objects
  (plate, engraving and photo inside the experiment, no separate lists of plates, engravings and photos; the conclusions per material stay),
  (2) one general full colour map: where a wanted colour occurred, without going through experiments. See the plan below.

## Experiments as single objects and one general colour map (operator, 2026-10-16): done

Operator decisions: camera-relative colours are expressed against the clean titanium of their own photograph; all laser and lens versions on one map
with a filter; the working-task panel stays, compact, on top. The photograph with its overlay is always shown in an experiment.

- [x] A1-A2. `experiments.py`, `GET /experiments` and `/experiments/{key}`: derived from plates and checks (DEC-055, REQ-028), no schema change.
- [x] A3-A4. One list screen (thumbnail, state, laser, lens, titanium, search, state filter, conclusions beside it); one experiment screen with the
  photograph and its overlay first, then the checks, the measured layers, the plate, the file and the conclusions.
- [x] A5. Old routes keep working and link back; new plates open as experiments.
- [x] B1-B2. `colormap.py`, `GET /colors` and `/colors/search` (DEC-056, REQ-029).
- [x] B3. One map screen: filters, a*b* plane, a palette or Lab input, nearest recipes with settings and where they came from; the model page stays
  reachable (`/colors?profile=`).
- [x] B4. Cleaning layer of a finished work recognised (also for works accepted earlier, from the stored file); linear-light ratio to the clean surface.
- [x] A6/B5. Tests (524 pass); checked in the running application on the operator's pairs.

## Review

### Result (2026-10-16)

- DEC-048, DEC-049, REQ-023, REQ-024 recorded in MarkView (statuses left to the operator).
- `lightburn.py`: exact outlines. Pilot file: 233 of 239 sub-paths closed (the old reader saw 43 of 235 paths); layer areas agree with
  an independent reader to 0.1 %.
- `anchoring.py` (new): window of the frame, 8 orientations with trimmed chamfer cost, pose polishing, per-element anchors, robust
  homography, statuses, bootstrap and a ring hold-out estimate. Pilot pair: 71 anchors, 120 confirmed, 29 partly hidden, median
  outline residual 0.09 mm, orientation margin 0.58 and 0 anchors for the second orientation; 15 s for the whole pair check.
- `ingest.py`: new route before `register_geometry`; frame window limits the measured surface; overlay draws the hidden part in
  magenta; per-layer notes; `_line_metrics` farthest pair via convex hull (was O(N^2): 66 s -> 14 s on the pilot pair).
- UI: method pill, anchor statistics, hidden margins marked approximate, refusal reason; Russian translations added.
- Tests: 486 pass (44 new: geometry, mask holes, anchoring on synthetic framed work, whole pair check and acceptance, farthest pair,
  sub-layers, groups, unsupported shapes, run order, overlap exclusion, key stability).

### Limits to remember

- Only one real pair was available. The reference chart is still missing from `IMG_3281.DNG`, so no observation can be created from it.
- Hidden margins of the plate vary by about 1 mm between runs of different settings; the UI says so. Visible elements are
  registered to about 0.1 mm (median); on synthetic works the worst grid point was 0.14-0.74 mm.
- The frame window is found only for a dark frame with a clear histogram valley; otherwise the old routes and the manual four corners remain.
- Heavily overlapping outlines (painted over) may be refused ("orientation ambiguous"); refusal is the safe outcome.
- See "Still open, and why" above.

