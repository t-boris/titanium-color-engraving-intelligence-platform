---
type: plan
feature: ux-work-catalog-p0
title: "Draft: Unified compact work catalog using App.list"
issues:
  - id: I-1
    title: Unify catalog metadata while preserving document identity
    summary: Provide a shared catalog data adapter for vector and photo works while preserving their existing owners and identifiers. Include thumbnail, name, type, dimensions, state, modification date and equipment references. Represent mixed works as one document; define handling of missing metadata and identifier collisions before implementation. Verify that catalog aggregation creates no additional work objects.
    requirements: [REQ-001, REQ-002]
    decisions: []
  - id: I-2
    title: Render the unified compact catalog through App.list
    summary: Build the shared Works entry on the existing App.list with compact rows containing all required metadata. Display at most 20 works initially and provide access to subsequent portions without omissions or duplicates. Include loading, empty and failure states, and verify collections spanning both work types and multiple portions.
    requirements: [REQ-001]
    decisions: []
  - id: I-3
    title: Compose catalog search, filters, counts and sorting
    summary: Combine text search, work type, laser, lens and material filters with modification-date sorting, visible counts and reset controls. Specify search fields, count semantics and treatment of missing equipment metadata before implementation. Verify combined controls across the complete catalog, including results beyond the initial portion, while preserving keyboard focus during typing.
    requirements: [REQ-001]
    decisions: []
  - id: I-4
    title: Add gallery switching and restore catalog context
    summary: Add a switchable gallery using the same catalog identity and query state. Preserve the selected view, search, filters, sorting and browsing position when opening a work and returning. Define a predictable fallback when the previous work disappears or no longer matches, and verify restoration beyond the first portion.
    requirements: [REQ-001]
    decisions: []
  - id: I-5
    title: Preserve editor routing and existing work links
    summary: Route each catalog item to its existing editor and keep mixed works in one document containing their zones and text. Preserve existing deep links and verify direct opening independently of the visible catalog portion. Cover vector, photo and mixed works, including unavailable targets, without creating duplicate documents.
    requirements: [REQ-002]
    decisions: []
  - id: I-6
    title: Provide accessible work actions and deletion confirmation
    summary: Expose rename, copy and delete through each item's action menu using existing work operations. Require explicit deletion confirmation and refresh the catalog consistently after success or failure. Reproduce the relevant BUG-014 behavior in the real interface and coordinate its shared-dialog fix so confirmation starts on Cancel, traps focus, supports Escape and restores focus to a valid target.
    requirements: [REQ-002]
    decisions: []
  - id: I-7
    title: Protect the boundary between works and experimental checks
    summary: Verify that photographing a work can expose its research check in Experiments while the original work retains sole ownership. Ensure deleting a check does not delete its work, and that removing the associated photo updates experiment visibility according to existing domain behavior. Extend regression coverage around these boundaries and preserve file and measurement history.
    requirements: [REQ-002]
    decisions: []
  - id: I-8
    title: Validate catalog workflows and domain regressions in the real interface
    summary: Validate the completed catalog in the browser and Electron with keyboard navigation, accessibility checks and end-to-end tasks for vector, photo and mixed works. Exercise search, combined filters, pagination, view restoration, actions and old links; verify applicable n58 editor guarantees after catalog navigation. Record baseline and resulting task success, search time, errors and first useful display time under n55–n57. Treat collection sizes and numerical performance thresholds as open proposals until explicitly established, and report observed results without claiming unmeasured improvement.
    requirements: [REQ-001, REQ-002]
    decisions: []
updated: 2026-11-05
---

# Implementation plan — [P0] Общий компактный каталог работ

## I-1: Unify catalog metadata while preserving document identity

Provide a shared catalog data adapter for vector and photo works while preserving their existing owners and identifiers. Include thumbnail, name, type, dimensions, state, modification date and equipment references. Represent mixed works as one document; define handling of missing metadata and identifier collisions before implementation. Verify that catalog aggregation creates no additional work objects.

Requirements: REQ-001, REQ-002

## I-2: Render the unified compact catalog through App.list

Build the shared Works entry on the existing App.list with compact rows containing all required metadata. Display at most 20 works initially and provide access to subsequent portions without omissions or duplicates. Include loading, empty and failure states, and verify collections spanning both work types and multiple portions.

Requirements: REQ-001

## I-3: Compose catalog search, filters, counts and sorting

Combine text search, work type, laser, lens and material filters with modification-date sorting, visible counts and reset controls. Specify search fields, count semantics and treatment of missing equipment metadata before implementation. Verify combined controls across the complete catalog, including results beyond the initial portion, while preserving keyboard focus during typing.

Requirements: REQ-001

## I-4: Add gallery switching and restore catalog context

Add a switchable gallery using the same catalog identity and query state. Preserve the selected view, search, filters, sorting and browsing position when opening a work and returning. Define a predictable fallback when the previous work disappears or no longer matches, and verify restoration beyond the first portion.

Requirements: REQ-001

## I-5: Preserve editor routing and existing work links

Route each catalog item to its existing editor and keep mixed works in one document containing their zones and text. Preserve existing deep links and verify direct opening independently of the visible catalog portion. Cover vector, photo and mixed works, including unavailable targets, without creating duplicate documents.

Requirements: REQ-002

## I-6: Provide accessible work actions and deletion confirmation

Expose rename, copy and delete through each item's action menu using existing work operations. Require explicit deletion confirmation and refresh the catalog consistently after success or failure. Reproduce the relevant BUG-014 behavior in the real interface and coordinate its shared-dialog fix so confirmation starts on Cancel, traps focus, supports Escape and restores focus to a valid target.

Requirements: REQ-002

## I-7: Protect the boundary between works and experimental checks

Verify that photographing a work can expose its research check in Experiments while the original work retains sole ownership. Ensure deleting a check does not delete its work, and that removing the associated photo updates experiment visibility according to existing domain behavior. Extend regression coverage around these boundaries and preserve file and measurement history.

Requirements: REQ-002

## I-8: Validate catalog workflows and domain regressions in the real interface

Validate the completed catalog in the browser and Electron with keyboard navigation, accessibility checks and end-to-end tasks for vector, photo and mixed works. Exercise search, combined filters, pagination, view restoration, actions and old links; verify applicable n58 editor guarantees after catalog navigation. Record baseline and resulting task success, search time, errors and first useful display time under n55–n57. Treat collection sizes and numerical performance thresholds as open proposals until explicitly established, and report observed results without claiming unmeasured improvement.

Requirements: REQ-001, REQ-002
