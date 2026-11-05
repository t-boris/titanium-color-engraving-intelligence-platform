---
type: plan
feature: ux-growing-collections-p0
title: "[P0] Growing collections: materials, sources, and history"
issues:
  - id: I-1
    title: Complete shared list reset, empty states, and recovery
    summary: Extend the existing shared list behavior with distinct empty-collection and no-results states, a reset action for all active search and filter conditions, and inline loading errors with retry. Reset must return to the first page and update counts consistently while preserving sort order and current selection. Retry must preserve input values, focus, and previously loaded rows. Reuse the existing App.list implementation and check overlap with BUG-012/013 before making changes.
    requirements: [REQ-004]
    decisions: []
  - id: I-2
    title: Build a searchable material catalog and selector
    summary: Replace the material form stack with compact rows showing name, alloy, batch, and thickness, with separate creation and selected-record editing forms. Add search, sorting, and pagination using existing list patterns. Provide searchable material selection with recent records while retaining the distinction between a material grade and a specific batch or sheet. Verify the workflow with 20, 200, and 2,000 test records.
    requirements: [REQ-001]
    decisions: []
  - id: I-3
    title: Add search and pagination to RAW datasets and documents
    summary: Apply search and pagination to RAW dataset and document collections so that neither collection renders all records by default. Preserve access to every matching record and its provenance across searches and page changes. Verify navigation, counts, empty states, and recovery through the shared list behavior.
    requirements: [REQ-002]
    decisions: []
  - id: I-4
    title: Paginate knowledge history and collapse source references
    summary: Limit knowledge history to an initial page with an explicit way to retrieve subsequent entries. Replace long photo and observation identifier lists with counts and expandable linked lists. Ensure that collapsed and paginated views retain provenance and access to every original record; verify count accuracy, link targets, and keyboard operation.
    requirements: [REQ-002]
    decisions: []
  - id: I-5
    title: Preserve selected-object visibility across search and pagination
    summary: Keep the current recipe, scale, or document identifiable when its row is outside the visible page or excluded by search or filters, using a pinned selected row or an explicit navigation action. Explain when active conditions exclude the selection and provide an explicit selection-reset action. Replace silent null outcomes from programmatic row opening with visible feedback and a way to locate the object, including an explicit unavailable state when it cannot be retrieved. Verify selection beyond the twentieth record, page changes, and excluding filters.
    requirements: [REQ-003]
    decisions: []
updated: 2026-11-05
---

# Implementation plan — [P0] Материалы, источники и длинная история

## I-1: Complete shared list reset, empty states, and recovery

Extend the existing shared list behavior with distinct empty-collection and no-results states, a reset action for all active search and filter conditions, and inline loading errors with retry. Reset must return to the first page and update counts consistently while preserving sort order and current selection. Retry must preserve input values, focus, and previously loaded rows. Reuse the existing App.list implementation and check overlap with BUG-012/013 before making changes.

Requirements: REQ-004

## I-2: Build a searchable material catalog and selector

Replace the material form stack with compact rows showing name, alloy, batch, and thickness, with separate creation and selected-record editing forms. Add search, sorting, and pagination using existing list patterns. Provide searchable material selection with recent records while retaining the distinction between a material grade and a specific batch or sheet. Verify the workflow with 20, 200, and 2,000 test records.

Requirements: REQ-001

## I-3: Add search and pagination to RAW datasets and documents

Apply search and pagination to RAW dataset and document collections so that neither collection renders all records by default. Preserve access to every matching record and its provenance across searches and page changes. Verify navigation, counts, empty states, and recovery through the shared list behavior.

Requirements: REQ-002

## I-4: Paginate knowledge history and collapse source references

Limit knowledge history to an initial page with an explicit way to retrieve subsequent entries. Replace long photo and observation identifier lists with counts and expandable linked lists. Ensure that collapsed and paginated views retain provenance and access to every original record; verify count accuracy, link targets, and keyboard operation.

Requirements: REQ-002

## I-5: Preserve selected-object visibility across search and pagination

Keep the current recipe, scale, or document identifiable when its row is outside the visible page or excluded by search or filters, using a pinned selected row or an explicit navigation action. Explain when active conditions exclude the selection and provide an explicit selection-reset action. Replace silent null outcomes from programmatic row opening with visible feedback and a way to locate the object, including an explicit unavailable state when it cannot be retrieved. Verify selection beyond the twentieth record, page changes, and excluding filters.

Requirements: REQ-003
