---
type: plan
feature: ux-photo-review-p0
title: "[P0] Exception-first photo review with permanently visible manual tools"
issues:
  - id: I-1
    title: Introduce review stages and preserve state across navigation
    summary: Define and implement the Files → Alignment → Review → Acceptance workflow, showing completion, blocking problems, and one primary action at each stage. Preserve entered data when returning to Files or Alignment and prevent navigation from accepting an unchecked result. Document which upstream changes invalidate review before implementing the transitions. This issue describes future work; implementation authorization remains pending.
    requirements: [REQ-001]
    decisions: []
  - id: I-2
    title: Build the review overview with persistent manual tool access
    summary: Make the photo with contours and a suitability summary the default review view. Prioritize problems requiring attention while keeping valid layers and metrics collapsed. Keep entry points for manual corners, workpiece alignment, matrix, all layers, and engraving tasks continuously visible and operable, including when automation reports no warnings.
    requirements: [REQ-001, REQ-002]
    decisions: [DEC-001]
  - id: I-3
    title: Connect warnings and blockers to contextual correction actions
    summary: Connect each warning to its relevant correction tool and give every blocking condition an explanation and a direct resolution link. Establish the warning-to-tool mapping and distinguish blocking conditions from advisory warnings using existing measurement rules. Ensure contextual actions coexist with the persistent manual entry points and that corrected problems are reflected in the review summary.
    requirements: [REQ-001, REQ-002]
    decisions: [DEC-001]
  - id: I-4
    title: Preserve measurement and provenance guarantees at acceptance
    summary: Integrate acceptance and rejection with the staged workflow while preserving existing measurement eligibility rules, provenance, and linkage to the specific engraved version. Verify that returning to earlier stages or changing review inputs cannot accept an unchecked result or retain an obsolete acceptance state. Identify the existing domain guarantees and their evidence before changing the acceptance path.
    requirements: [REQ-001, REQ-002]
    decisions: [DEC-001]
  - id: I-5
    title: Verify runtime behavior, accessibility, and domain guarantees
    summary: Validate the completed workflow in the real interface against both requirements and the research guarantees n55–n58. Cover navigation with retained input, stage completion and blockers, collapsed valid details, every manual tool without warnings, correction of alignment considered valid by automation, warning shortcuts, and acceptance/rejection integrity. Verify keyboard access, focus behavior, accessible names, and visibility of tool entry points; record runtime evidence and unresolved failures before marking acceptance criteria complete.
    requirements: [REQ-001, REQ-002]
    decisions: [DEC-001]
updated: 2026-11-05
---

# Implementation plan — [P0] Проверка фотографии по исключениям

## I-1: Introduce review stages and preserve state across navigation

Define and implement the Files → Alignment → Review → Acceptance workflow, showing completion, blocking problems, and one primary action at each stage. Preserve entered data when returning to Files or Alignment and prevent navigation from accepting an unchecked result. Document which upstream changes invalidate review before implementing the transitions. This issue describes future work; implementation authorization remains pending.

Requirements: REQ-001

## I-2: Build the review overview with persistent manual tool access

Make the photo with contours and a suitability summary the default review view. Prioritize problems requiring attention while keeping valid layers and metrics collapsed. Keep entry points for manual corners, workpiece alignment, matrix, all layers, and engraving tasks continuously visible and operable, including when automation reports no warnings.

Requirements: REQ-001, REQ-002
Decisions: DEC-001

## I-3: Connect warnings and blockers to contextual correction actions

Connect each warning to its relevant correction tool and give every blocking condition an explanation and a direct resolution link. Establish the warning-to-tool mapping and distinguish blocking conditions from advisory warnings using existing measurement rules. Ensure contextual actions coexist with the persistent manual entry points and that corrected problems are reflected in the review summary.

Requirements: REQ-001, REQ-002
Decisions: DEC-001

## I-4: Preserve measurement and provenance guarantees at acceptance

Integrate acceptance and rejection with the staged workflow while preserving existing measurement eligibility rules, provenance, and linkage to the specific engraved version. Verify that returning to earlier stages or changing review inputs cannot accept an unchecked result or retain an obsolete acceptance state. Identify the existing domain guarantees and their evidence before changing the acceptance path.

Requirements: REQ-001, REQ-002
Decisions: DEC-001

## I-5: Verify runtime behavior, accessibility, and domain guarantees

Validate the completed workflow in the real interface against both requirements and the research guarantees n55–n58. Cover navigation with retained input, stage completion and blockers, collapsed valid details, every manual tool without warnings, correction of alignment considered valid by automation, warning shortcuts, and acceptance/rejection integrity. Verify keyboard access, focus behavior, accessible names, and visibility of tool entry points; record runtime evidence and unresolved failures before marking acceptance criteria complete.

Requirements: REQ-001, REQ-002
Decisions: DEC-001
