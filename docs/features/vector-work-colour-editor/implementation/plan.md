---
type: plan
feature: vector-work-colour-editor
title: Vector work colour editor for photograph vector works
issues:
  - id: I-1
    title: Implement version-aware editor history and variant restoration
    summary: Extend editor history snapshots to include colouring, document version, ΔE tolerance and filters. Support undo and redo across colouring and geometry operations, clear redo after a new operation, and allocate version numbers above every previously allocated version even after branching. Preserve compatibility with older undo entries by assigning them to the work's current version. Bind variants to their document version and reject restoration on another version with a translated message. Resplitting clears history and variants. Verify mixed-operation undo/redo, settings restoration, version branching and legacy history.
    requirements: [REQ-049]
    decisions: [DEC-077]
  - id: I-2
    title: Assign all source colours automatically and remove acceptance gating
    summary: "Assign every source colour with areas a measured titanium colour after splitting, resplitting or automatic recolouring: the fastest within tolerance, otherwise the nearest. Remove acceptance operations and preserve previously accepted choices as manual choices. Restrict export blockers to unavailable measured choices, an empty palette, nothing left to engrave or recipes exceeding LightBurn's layer limit, with a specific explanation for each. Expose beyond-tolerance ΔE and area highlighting for the editor. Verify that a copy of live work 22 assigns all 28 colours at tolerance 0.05 and permits export."
    requirements: [REQ-043]
    decisions: [DEC-001]
  - id: I-3
    title: Build the large-picture editor, palette and inspection controls
    summary: Build the photograph editor around a large picture and a side panel containing tools, brush scope and similarity ΔE, active colour, measured palette, layers, source colours, totals and history controls. Provide wheel and button zoom, fit, drag pan, titanium/source/original views, and beyond-tolerance outlines. Order the palette by distance to the hovered area's source colour, display ΔE and seconds per cm², and mark measurements without a reference with dashed styling. Show layer area, area count and time, source assignments and ΔE, and live totals. Connect pipette and Alt+click, undo/redo buttons and keyboard shortcuts, and exact affected-area hover previews with source number, titanium colour, ΔE and recipe.
    requirements: [REQ-044, REQ-043, REQ-049]
    decisions: [DEC-075]
  - id: I-4
    title: Implement three brush scopes and automatic-choice restoration
    summary: Implement brush operations for one area, all areas of a source colour, and a connected fill using shared borders and source-colour ΔE relative to the clicked area. Source-colour painting clears its areas' individual choices; fill traversal never crosses excluded areas or excluded source colours, while painting an excluded area includes it again. Use the same affected-area calculation for preview and execution. Support painting with automatic to restore automatic choices, record each paint as one history operation, and retain whole-work automatic modes that preserve manual choices. Verify scope isolation, exclusions, fill connectivity and preview/execution agreement.
    requirements: [REQ-045, REQ-044, REQ-049]
    decisions: [DEC-075, DEC-077]
  - id: I-5
    title: Merge titanium colours through the layers list
    summary: Allow selection of two or more titanium colours in the layers list and replacement with a measured palette target throughout the work. Convert every affected source-colour and area assignment into a manual target choice so later automatic modes preserve the merge. Recompute layers and totals, reject insufficient selections or targets outside the palette with translated messages, and record the merge as one undoable operation. Verify assignments, resulting layer counts and persistence through automatic recolouring.
    requirements: [REQ-046, REQ-049]
    decisions: [DEC-076, DEC-077]
  - id: I-6
    title: Merge source colours into a versioned palette entry
    summary: Merge selected source colours into a new document version using their pixel-weighted mean Lab and the number of the member with most pixels, without renumbering other colours. Relabel member areas while preserving area ids and geometry; drop choices and exclusions of merged-away source colours while retaining area choices. Reject fewer than two colours or unknown colours with translated messages. Connect the operation to version-aware history and verify all brush scopes and automatic modes against the merged version, including undo and redo.
    requirements: [REQ-047, REQ-049]
    decisions: [DEC-076, DEC-077]
  - id: I-7
    title: Merge neighbouring areas while preserving topology and export
    summary: Add click and Shift+click area selection and merge a set of at least two areas connected through shared borders into a new document version. Reject corner-only connectivity with a translated message. Remove internal shared arcs, reconstruct boundaries from loop successor relations, order outer loops before holes by signed area and renumber arcs. Preserve the largest member's id, source colour and choices, and sum member pixels. Verify closed outlines, holes and pinch points, unchanged coverage without gaps or overlaps, LightBurn export read-back, and restoration of both geometry and colouring through undo and redo.
    requirements: [REQ-048, REQ-044, REQ-049]
    decisions: [DEC-076, DEC-077]
  - id: I-8
    title: Apply the operator's answers on merging colours, painting a source colour and merging areas
    summary: "Refuse a titanium-colour merge unless two or more distinct colours used by the colouring are selected (DEC-078), with one translated message. Make a source-colour paint with a titanium colour include again every area of that colour that was excluded one by one, so that the hover outline and the click agree (DEC-079). Enable the merge-areas button only for a connected selection and say why otherwise, using a new read-only GET /api/vector/{id}/neighbours that answers with the relation merging uses, asked once per split version; the server keeps refusing unconnected and corner-only sets (DEC-080). Verify by tests that cover REQ-049 for the titanium merge as well, and by a walkthrough on a full copy of the live data."
    requirements: [REQ-045, REQ-046, REQ-048, REQ-049]
    decisions: [DEC-078, DEC-079, DEC-080]
updated: 2026-10-19
---

# Implementation plan — Vector work colour editor

## I-1: Implement version-aware editor history and variant restoration

Extend editor history snapshots to include colouring, document version, ΔE tolerance and filters. Support undo and redo across colouring and geometry operations, clear redo after a new operation, and allocate version numbers above every previously allocated version even after branching. Preserve compatibility with older undo entries by assigning them to the work's current version. Bind variants to their document version and reject restoration on another version with a translated message. Resplitting clears history and variants. Verify mixed-operation undo/redo, settings restoration, version branching and legacy history.

Requirements: REQ-049
Decisions: DEC-077

## I-2: Assign all source colours automatically and remove acceptance gating

Assign every source colour with areas a measured titanium colour after splitting, resplitting or automatic recolouring: the fastest within tolerance, otherwise the nearest. Remove acceptance operations and preserve previously accepted choices as manual choices. Restrict export blockers to unavailable measured choices, an empty palette, nothing left to engrave or recipes exceeding LightBurn's layer limit, with a specific explanation for each. Expose beyond-tolerance ΔE and area highlighting for the editor. Verify that a copy of live work 22 assigns all 28 colours at tolerance 0.05 and permits export.

Requirements: REQ-043
Decisions: DEC-001

## I-3: Build the large-picture editor, palette and inspection controls

Build the photograph editor around a large picture and a side panel containing tools, brush scope and similarity ΔE, active colour, measured palette, layers, source colours, totals and history controls. Provide wheel and button zoom, fit, drag pan, titanium/source/original views, and beyond-tolerance outlines. Order the palette by distance to the hovered area's source colour, display ΔE and seconds per cm², and mark measurements without a reference with dashed styling. Show layer area, area count and time, source assignments and ΔE, and live totals. Connect pipette and Alt+click, undo/redo buttons and keyboard shortcuts, and exact affected-area hover previews with source number, titanium colour, ΔE and recipe.

Requirements: REQ-044, REQ-043, REQ-049
Decisions: DEC-075

## I-4: Implement three brush scopes and automatic-choice restoration

Implement brush operations for one area, all areas of a source colour, and a connected fill using shared borders and source-colour ΔE relative to the clicked area. Source-colour painting clears its areas' individual choices; fill traversal never crosses excluded areas or excluded source colours, while painting an excluded area includes it again. Use the same affected-area calculation for preview and execution. Support painting with automatic to restore automatic choices, record each paint as one history operation, and retain whole-work automatic modes that preserve manual choices. Verify scope isolation, exclusions, fill connectivity and preview/execution agreement.

Requirements: REQ-045, REQ-044, REQ-049
Decisions: DEC-075, DEC-077

## I-5: Merge titanium colours through the layers list

Allow selection of two or more titanium colours in the layers list and replacement with a measured palette target throughout the work. Convert every affected source-colour and area assignment into a manual target choice so later automatic modes preserve the merge. Recompute layers and totals, reject insufficient selections or targets outside the palette with translated messages, and record the merge as one undoable operation. Verify assignments, resulting layer counts and persistence through automatic recolouring.

Requirements: REQ-046, REQ-049
Decisions: DEC-076, DEC-077

## I-6: Merge source colours into a versioned palette entry

Merge selected source colours into a new document version using their pixel-weighted mean Lab and the number of the member with most pixels, without renumbering other colours. Relabel member areas while preserving area ids and geometry; drop choices and exclusions of merged-away source colours while retaining area choices. Reject fewer than two colours or unknown colours with translated messages. Connect the operation to version-aware history and verify all brush scopes and automatic modes against the merged version, including undo and redo.

Requirements: REQ-047, REQ-049
Decisions: DEC-076, DEC-077

## I-7: Merge neighbouring areas while preserving topology and export

Add click and Shift+click area selection and merge a set of at least two areas connected through shared borders into a new document version. Reject corner-only connectivity with a translated message. Remove internal shared arcs, reconstruct boundaries from loop successor relations, order outer loops before holes by signed area and renumber arcs. Preserve the largest member's id, source colour and choices, and sum member pixels. Verify closed outlines, holes and pinch points, unchanged coverage without gaps or overlaps, LightBurn export read-back, and restoration of both geometry and colouring through undo and redo.

Requirements: REQ-048, REQ-044, REQ-049
Decisions: DEC-076, DEC-077

## I-8: Apply the operator's answers on merging colours, painting a source colour and merging areas

Refuse a titanium-colour merge unless two or more distinct colours used by the colouring are selected (DEC-078), with one translated message. Make a source-colour paint with a titanium colour include again every area of that colour that was excluded one by one, so that the hover outline and the click agree (DEC-079). Enable the merge-areas button only for a connected selection and say why otherwise, using a new read-only GET /api/vector/{id}/neighbours that answers with the relation merging uses, asked once per split version; the server keeps refusing unconnected and corner-only sets (DEC-080). Verify by tests that cover REQ-049 for the titanium merge as well, and by a walkthrough on a full copy of the live data.

Requirements: REQ-045, REQ-046, REQ-048, REQ-049
Decisions: DEC-078, DEC-079, DEC-080
