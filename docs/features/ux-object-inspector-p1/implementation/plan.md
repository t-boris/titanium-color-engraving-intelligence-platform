---
type: plan
feature: ux-object-inspector-p1
title: Canvas selection and unified object inspector
issues:
  - id: I-1
    title: "[P0] Make brush mode and action scope visible"
    summary: Deliver the P0 improvement in the current editor before the P1 inspector restructuring. Show the active brush mode and whether it affects one region, every region sharing the source colour, or similar neighbours. Make any mode change on entering Photo visible before the next action, and ensure the displayed scope matches the operation.
    requirements: [REQ-002]
    decisions: []
  - id: I-2
    title: Expose selection action eligibility and button equivalents
    summary: Enable merge for connected selections, re-splitting for a single region, and photo-zone creation for eligible selections. Explain unavailable actions beside their controls. Provide ordinary buttons for keyboard-triggered actions and preserve existing undo guarantees.
    requirements: [REQ-002]
    decisions: []
  - id: I-3
    title: Connect canvas selection to one object inspector
    summary: Introduce one inspector driven by the selected region, photo zone or inscription, keeping the canvas primary. Display the corresponding properties when selection changes without resetting the canvas view, and define clear inspector states for no selection and unsupported or multiple selections.
    requirements: [REQ-001]
    decisions: []
  - id: I-4
    title: Integrate basic photo-zone properties and detailed editing
    summary: Expose basic photo-zone properties in the inspector using the grouping defined by ux-photo-lettering-panels-p1/REQ-001. Add an explicit action opening the selected zone in the existing detailed editor, preserve every detailed control, and support returning to the canvas with the selected zone and view context retained. Keep inspector and detailed-editor changes in the vector work's shared undo/redo history.
    requirements: [REQ-001]
    decisions: [DEC-001]
  - id: I-5
    title: Distinguish document colouring from selection colour
    summary: Separate document-wide colouring from selection colour through explicit labels, placement and action scope. Remove the two indistinguishable Colours tabs and verify that colour changes target the scope communicated by the interface.
    requirements: [REQ-001]
    decisions: []
  - id: I-6
    title: Preserve document modes and history across navigation
    summary: Keep splitting, variants, results and export accessible as document modes alongside object inspection. Preserve the vector work's history when switching modes and verify that subsequent undo/redo retains the existing editing guarantees.
    requirements: [REQ-001]
    decisions: []
  - id: I-7
    title: Verify integrated editor accessibility and domain guarantees
    summary: "Validate the completed workflows in browser and Electron: object selection, inspector edits, photo-zone detailed-editor round trips, document modes, action eligibility and undo/redo. Check keyboard and screen-reader access, enlarged text, and narrow or low windows. Record runtime evidence against applicable n55–n58 criteria, including n58 domain guarantees, and resolve acceptance-blocking failures."
    requirements: [REQ-001, REQ-002]
    decisions: [DEC-001]
updated: 2026-11-06
---

# Implementation plan — [P1] Холст, выделение и единая панель свойств

## I-1: [P0] Make brush mode and action scope visible

Deliver the P0 improvement in the current editor before the P1 inspector restructuring. Show the active brush mode and whether it affects one region, every region sharing the source colour, or similar neighbours. Make any mode change on entering Photo visible before the next action, and ensure the displayed scope matches the operation.

Requirements: REQ-002

## I-2: Expose selection action eligibility and button equivalents

Enable merge for connected selections, re-splitting for a single region, and photo-zone creation for eligible selections. Explain unavailable actions beside their controls. Provide ordinary buttons for keyboard-triggered actions and preserve existing undo guarantees.

Requirements: REQ-002

## I-3: Connect canvas selection to one object inspector

Introduce one inspector driven by the selected region, photo zone or inscription, keeping the canvas primary. Display the corresponding properties when selection changes without resetting the canvas view, and define clear inspector states for no selection and unsupported or multiple selections.

Requirements: REQ-001

## I-4: Integrate basic photo-zone properties and detailed editing

Expose basic photo-zone properties in the inspector using the grouping defined by ux-photo-lettering-panels-p1/REQ-001. Add an explicit action opening the selected zone in the existing detailed editor, preserve every detailed control, and support returning to the canvas with the selected zone and view context retained. Keep inspector and detailed-editor changes in the vector work's shared undo/redo history.

Requirements: REQ-001
Decisions: DEC-001

## I-5: Distinguish document colouring from selection colour

Separate document-wide colouring from selection colour through explicit labels, placement and action scope. Remove the two indistinguishable Colours tabs and verify that colour changes target the scope communicated by the interface.

Requirements: REQ-001

## I-6: Preserve document modes and history across navigation

Keep splitting, variants, results and export accessible as document modes alongside object inspection. Preserve the vector work's history when switching modes and verify that subsequent undo/redo retains the existing editing guarantees.

Requirements: REQ-001

## I-7: Verify integrated editor accessibility and domain guarantees

Validate the completed workflows in browser and Electron: object selection, inspector edits, photo-zone detailed-editor round trips, document modes, action eligibility and undo/redo. Check keyboard and screen-reader access, enlarged text, and narrow or low windows. Record runtime evidence against applicable n55–n58 criteria, including n58 domain guarantees, and resolve acceptance-blocking failures.

Requirements: REQ-001, REQ-002
Decisions: DEC-001
