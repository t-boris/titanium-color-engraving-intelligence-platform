---
type: plan
feature: ux-photo-lettering-panels-p1
title: Short photo engraving and lettering forms
issues:
  - id: I-1
    title: Restructure photo controls by user intent
    summary: Expose engraving kind, size, recommended scale and basic image adjustments at the first level in both photo-work and vector photo-zone panels. Group Min/Max power, gamma, dot correction, measured points and scale details by purpose, with brief explanations. Preserve exact numeric entry alongside sliders, validation, error feedback and visible measured-range limitations.
    requirements: [REQ-001]
    decisions: []
  - id: I-2
    title: Compare photo results before and after the latest change
    summary: Allow comparison of the current photo result against the state immediately before the latest parameter change. Advance the baseline after each subsequent change and treat one continuous slider adjustment as one change. Preserve protection against stale responses so comparison displays the results associated with the intended settings.
    requirements: [REQ-001]
    decisions: [DEC-001]
  - id: I-3
    title: Restructure lettering controls into a short primary form
    summary: Limit the primary lettering form to text, font, height and color. Organize every remaining existing parameter into Placement, Text Shape and Inlay groups. Preserve dragging, rotation and scaling alongside exact coordinate entry, with all controls remaining available.
    requirements: [REQ-002]
    decisions: []
  - id: I-4
    title: Verify engraving, geometry, export and undo guarantees
    summary: "Verify and address regressions introduced by the form changes: photo prediction and LightBurn export must use the same settings without changing the physical model; scale changes must retain the source image; undo must restore size and settings. For lettering, verify straight, arc, circle and path modes, gap and backing preserve geometry, export and undo behavior. Include stale-response and validation failure scenarios in the regression coverage."
    requirements: [REQ-001, REQ-002]
    decisions: [DEC-001]
  - id: I-5
    title: Validate the revised forms across interfaces and accessibility modes
    summary: Validate the affected photo-work, vector photo-zone and lettering forms in the real browser and Electron interfaces. Check keyboard and screen-reader access, enlarged text, narrow windows and low windows, including grouped controls, exact numeric entry, error feedback and photo comparison. Resolve discovered usability and accessibility defects and record acceptance evidence.
    requirements: [REQ-001, REQ-002]
    decisions: [DEC-001]
updated: 2026-11-06
---

# Implementation plan — [P1] Короткие формы фотогравировки и надписей

## I-1: Restructure photo controls by user intent

Expose engraving kind, size, recommended scale and basic image adjustments at the first level in both photo-work and vector photo-zone panels. Group Min/Max power, gamma, dot correction, measured points and scale details by purpose, with brief explanations. Preserve exact numeric entry alongside sliders, validation, error feedback and visible measured-range limitations.

Requirements: REQ-001

## I-2: Compare photo results before and after the latest change

Allow comparison of the current photo result against the state immediately before the latest parameter change. Advance the baseline after each subsequent change and treat one continuous slider adjustment as one change. Preserve protection against stale responses so comparison displays the results associated with the intended settings.

Requirements: REQ-001
Decisions: DEC-001

## I-3: Restructure lettering controls into a short primary form

Limit the primary lettering form to text, font, height and color. Organize every remaining existing parameter into Placement, Text Shape and Inlay groups. Preserve dragging, rotation and scaling alongside exact coordinate entry, with all controls remaining available.

Requirements: REQ-002

## I-4: Verify engraving, geometry, export and undo guarantees

Verify and address regressions introduced by the form changes: photo prediction and LightBurn export must use the same settings without changing the physical model; scale changes must retain the source image; undo must restore size and settings. For lettering, verify straight, arc, circle and path modes, gap and backing preserve geometry, export and undo behavior. Include stale-response and validation failure scenarios in the regression coverage.

Requirements: REQ-001, REQ-002
Decisions: DEC-001

## I-5: Validate the revised forms across interfaces and accessibility modes

Validate the affected photo-work, vector photo-zone and lettering forms in the real browser and Electron interfaces. Check keyboard and screen-reader access, enlarged text, narrow windows and low windows, including grouped controls, exact numeric entry, error feedback and photo comparison. Resolve discovered usability and accessibility defects and record acceptance evidence.

Requirements: REQ-001, REQ-002
Decisions: DEC-001
