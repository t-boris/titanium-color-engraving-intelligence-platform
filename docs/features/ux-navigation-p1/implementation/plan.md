---
type: plan
feature: ux-navigation-p1
title: Validate and implement operator navigation and orientation
issues:
  - id: I-1
    title: Inventory navigation and define route compatibility coverage
    summary: Inventory every existing navigation entry, settings tab, route and linked workflow. Produce a traceable mapping to the proposed five sections, explicitly marking placements as hypotheses. Record representative object identifiers, route arguments and query parameters for compatibility checks, including distinct vector and photo editors, AI session history and laboratory-source selection within work creation.
    requirements: [REQ-001]
    decisions: [DEC-001]
  - id: I-2
    title: Validate proposed groupings with operators
    summary: Build a reviewable navigation prototype and compare it with the current interface on identical representative operator tasks covering all five proposed sections, especially capture settings, repeatability assessment, materials and photo markers. Record unaided completion, navigation time, backtracking and errors separately from assumptions; establish numerical targets after the baseline. Document supported labels and placements, revise and retest unsupported groupings, and produce an explicit adoption record before production regrouping begins.
    requirements: [REQ-001]
    decisions: [DEC-001]
  - id: I-3
    title: Implement validated navigation while preserving existing routes
    summary: After operator validation, implement only the supported primary sections and discoverable paths from the inventory. Apply validated placements for planning, findings and AI research; vector and photo engraving; network, laboratories and settings. Preserve every existing function, workflow and address, distinct editors and object ownership. Verify that direct links retain identifiers, arguments and query parameters, browser back/forward restores the correct content, and active-section indication matches the adopted grouping.
    requirements: [REQ-001]
    decisions: [DEC-001]
  - id: I-4
    title: Add persistent section labels and editor orientation
    summary: Provide a pinnable navigation menu with visible section labels on wide windows while retaining a user-selectable compact mode. Show the current section, work title and a persistent return to the appropriate catalog in each affected editor, using the currently adopted section structure. Remove the static role badge while preserving useful statuses and the application version. Verify orientation and catalog return for both vector and photo work.
    requirements: [REQ-002]
    decisions: []
  - id: I-5
    title: Group equipment details with progressive disclosure
    summary: Organize the equipment card into overview, lenses, measurements and technical data. Place graphs, pulse information, protocol and documents within technical data while preserving document search and links. Identify frequent actions from operator observations and keep them accessible without expanding technical groups; verify access to every existing equipment capability after regrouping.
    requirements: [REQ-003]
    decisions: []
  - id: I-6
    title: Verify navigation accessibility and domain regressions
    summary: Verify the affected navigation, editor orientation and equipment groups in the real browser and Electron interface using keyboard, screen reader, enlarged text, narrow and low windows. Exercise relevant workflows from research nodes n55–n58, including back navigation, delayed responses and applicable failure recovery. Confirm preview/export consistency, separate color and photo quality assessments, file and measurement history, and applicable palette, cancellation and stale-response protections. Record observed results and unresolved failures; do not treat prototype selection or structural tests as runtime acceptance.
    requirements: [REQ-001, REQ-002, REQ-003]
    decisions: [DEC-001]
updated: 2026-11-06
---

# Implementation plan — [P1] Пять разделов и понятные ориентиры

## I-1: Inventory navigation and define route compatibility coverage

Inventory every existing navigation entry, settings tab, route and linked workflow. Produce a traceable mapping to the proposed five sections, explicitly marking placements as hypotheses. Record representative object identifiers, route arguments and query parameters for compatibility checks, including distinct vector and photo editors, AI session history and laboratory-source selection within work creation.

Requirements: REQ-001
Decisions: DEC-001

## I-2: Validate proposed groupings with operators

Build a reviewable navigation prototype and compare it with the current interface on identical representative operator tasks covering all five proposed sections, especially capture settings, repeatability assessment, materials and photo markers. Record unaided completion, navigation time, backtracking and errors separately from assumptions; establish numerical targets after the baseline. Document supported labels and placements, revise and retest unsupported groupings, and produce an explicit adoption record before production regrouping begins.

Requirements: REQ-001
Decisions: DEC-001

## I-3: Implement validated navigation while preserving existing routes

After operator validation, implement only the supported primary sections and discoverable paths from the inventory. Apply validated placements for planning, findings and AI research; vector and photo engraving; network, laboratories and settings. Preserve every existing function, workflow and address, distinct editors and object ownership. Verify that direct links retain identifiers, arguments and query parameters, browser back/forward restores the correct content, and active-section indication matches the adopted grouping.

Requirements: REQ-001
Decisions: DEC-001

## I-4: Add persistent section labels and editor orientation

Provide a pinnable navigation menu with visible section labels on wide windows while retaining a user-selectable compact mode. Show the current section, work title and a persistent return to the appropriate catalog in each affected editor, using the currently adopted section structure. Remove the static role badge while preserving useful statuses and the application version. Verify orientation and catalog return for both vector and photo work.

Requirements: REQ-002

## I-5: Group equipment details with progressive disclosure

Organize the equipment card into overview, lenses, measurements and technical data. Place graphs, pulse information, protocol and documents within technical data while preserving document search and links. Identify frequent actions from operator observations and keep them accessible without expanding technical groups; verify access to every existing equipment capability after regrouping.

Requirements: REQ-003

## I-6: Verify navigation accessibility and domain regressions

Verify the affected navigation, editor orientation and equipment groups in the real browser and Electron interface using keyboard, screen reader, enlarged text, narrow and low windows. Exercise relevant workflows from research nodes n55–n58, including back navigation, delayed responses and applicable failure recovery. Confirm preview/export consistency, separate color and photo quality assessments, file and measurement history, and applicable palette, cancellation and stale-response protections. Record observed results and unresolved failures; do not treat prototype selection or structural tests as runtime acceptance.

Requirements: REQ-001, REQ-002, REQ-003
Decisions: DEC-001
