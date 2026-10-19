---
type: plan
feature: vector-detail-and-colour-control
title: Vector Detail and Colour Control
issues:
  - id: I-1
    title: Build the unified Vector Work workspace and update navigation
    summary: Create a unified canvas-centred workspace for segmentation and colouring, with surrounding tools, contextual settings and accessible import/export actions. Keep primary actions available without whole-page scrolling; allow internal panel scrolling. Place Vector Work third after Experiments and Color Map, preserving existing URLs and editor tools.
    requirements: [REQ-042, REQ-044]
    decisions: [DEC-078]
  - id: I-2
    title: Add segmentation algorithm selection and independent density control
    summary: Evaluate and implement distinct photo-to-region segmentation algorithms, retaining the existing method and documenting image suitability for each supported option. Expose algorithm selection and global region density independently of source-colour count, with a previewed region count. Verify that a detailed reference image produces fewer regions at low density than at high density with other settings unchanged; do not label detail presets as separate algorithms.
    requirements: [REQ-042]
    decisions: [DEC-076]
  - id: I-3
    title: Add independent eye detail and boundary controls
    summary: Provide editable boundaries and independent detail overrides for each detected or manually marked eye, including manual addition when detection misses an eye. Apply changes through explicit rebuilding and verify that changing one eye's detail preserves geometry outside its boundary. Integrate these controls into the canvas workspace.
    requirements: [REQ-042]
    decisions: [DEC-076, DEC-078]
  - id: I-4
    title: Produce smooth shared contours while preserving topology
    summary: Improve shared-contour smoothing so curved boundaries have continuous tangents except at intentional corners and multi-region junctions. Preserve identical shared borders and holes, keeping rasterized uncovered and doubly covered areas each below 0.5%. Validate curved, corner and junction fixtures and confirm that exported geometry matches the preview.
    requirements: [REQ-042]
    decisions: []
  - id: I-5
    title: Integrate contextual measured-palette painting
    summary: Expose every eligible measured colour for the selected laser, lens and titanium when a region is selected. Support applying a palette colour while preserving existing brush scopes, exclusions and manual-choice semantics. Update the region's recipe, layer count and time estimate immediately, and retain existing layer limits.
    requirements: [REQ-042, REQ-044, REQ-045]
    decisions: [DEC-078, vector-work-colour-editor/DEC-075]
  - id: I-6
    title: Add Contrast and lightness-preserving Artistic recolouring
    summary: Add previewable, reproducible whole-work Contrast and Artistic variants using eligible recipes and existing filters while preserving manual choices. Verify that Contrast improves shared-border-length-weighted mean neighbour ΔE over Closest on a reference fixture. Artistic must vary seeded hue arrangements within the chosen measured palette subset while preserving source lightness order for automatic assignments; handle insufficient palette variety and manual-choice conflicts consistently with existing Tonality behaviour.
    requirements: [REQ-042, REQ-044]
    decisions: [DEC-079, vector-work-colour-editor/DEC-075]
  - id: I-7
    title: Automatically merge adjacent regions with identical engraving configurations
    summary: After colouring, automatically union each border-connected component of included regions with identical recipes and applicable settings, removing internal seams while preserving holes. Keep corner-touching, disconnected, excluded and differently configured regions separate. Preserve compatibility with existing painting and manual merge operations, retain source and assignment information needed by subsequent edits, and record colouring plus its automatic geometry merges as one undoable operation.
    requirements: [REQ-042, REQ-045, REQ-046, REQ-047, REQ-048, REQ-049]
    decisions: [vector-work-colour-editor/DEC-075]
  - id: I-8
    title: Integrate rebuild lifecycle, persistence, history and export
    summary: Persist algorithm, density, eye and smoothing settings alongside accepted geometry and colouring. Require explicit rebuilding for segmentation changes and warn that colouring and variants reset. Verify reload, undo/redo and LightBurn export across the integrated workflow, including restored boundaries after undo, retained holes, accepted preview geometry, complete recipes and existing layer limits. Requirement references reuse existing IDs; the feature overview's eight acceptance criteria have no separate requirement IDs.
    requirements: [REQ-042, REQ-044, REQ-049]
    decisions: [DEC-076, DEC-078, DEC-079]
updated: 2026-10-19
---

# Implementation plan — Vector Detail and Colour Control

## I-1: Build the unified Vector Work workspace and update navigation

Create a unified canvas-centred workspace for segmentation and colouring, with surrounding tools, contextual settings and accessible import/export actions. Keep primary actions available without whole-page scrolling; allow internal panel scrolling. Place Vector Work third after Experiments and Color Map, preserving existing URLs and editor tools.

Requirements: REQ-042, REQ-044
Decisions: DEC-078

## I-2: Add segmentation algorithm selection and independent density control

Evaluate and implement distinct photo-to-region segmentation algorithms, retaining the existing method and documenting image suitability for each supported option. Expose algorithm selection and global region density independently of source-colour count, with a previewed region count. Verify that a detailed reference image produces fewer regions at low density than at high density with other settings unchanged; do not label detail presets as separate algorithms.

Requirements: REQ-042
Decisions: DEC-076

## I-3: Add independent eye detail and boundary controls

Provide editable boundaries and independent detail overrides for each detected or manually marked eye, including manual addition when detection misses an eye. Apply changes through explicit rebuilding and verify that changing one eye's detail preserves geometry outside its boundary. Integrate these controls into the canvas workspace.

Requirements: REQ-042
Decisions: DEC-076, DEC-078

## I-4: Produce smooth shared contours while preserving topology

Improve shared-contour smoothing so curved boundaries have continuous tangents except at intentional corners and multi-region junctions. Preserve identical shared borders and holes, keeping rasterized uncovered and doubly covered areas each below 0.5%. Validate curved, corner and junction fixtures and confirm that exported geometry matches the preview.

Requirements: REQ-042

## I-5: Integrate contextual measured-palette painting

Expose every eligible measured colour for the selected laser, lens and titanium when a region is selected. Support applying a palette colour while preserving existing brush scopes, exclusions and manual-choice semantics. Update the region's recipe, layer count and time estimate immediately, and retain existing layer limits.

Requirements: REQ-042, REQ-044, REQ-045
Decisions: DEC-078, vector-work-colour-editor/DEC-075

## I-6: Add Contrast and lightness-preserving Artistic recolouring

Add previewable, reproducible whole-work Contrast and Artistic variants using eligible recipes and existing filters while preserving manual choices. Verify that Contrast improves shared-border-length-weighted mean neighbour ΔE over Closest on a reference fixture. Artistic must vary seeded hue arrangements within the chosen measured palette subset while preserving source lightness order for automatic assignments; handle insufficient palette variety and manual-choice conflicts consistently with existing Tonality behaviour.

Requirements: REQ-042, REQ-044
Decisions: DEC-079, vector-work-colour-editor/DEC-075

## I-7: Automatically merge adjacent regions with identical engraving configurations

After colouring, automatically union each border-connected component of included regions with identical recipes and applicable settings, removing internal seams while preserving holes. Keep corner-touching, disconnected, excluded and differently configured regions separate. Preserve compatibility with existing painting and manual merge operations, retain source and assignment information needed by subsequent edits, and record colouring plus its automatic geometry merges as one undoable operation.

Requirements: REQ-042, REQ-045, REQ-046, REQ-047, REQ-048, REQ-049
Decisions: vector-work-colour-editor/DEC-075

## I-8: Integrate rebuild lifecycle, persistence, history and export

Persist algorithm, density, eye and smoothing settings alongside accepted geometry and colouring. Require explicit rebuilding for segmentation changes and warn that colouring and variants reset. Verify reload, undo/redo and LightBurn export across the integrated workflow, including restored boundaries after undo, retained holes, accepted preview geometry, complete recipes and existing layer limits. Requirement references reuse existing IDs; the feature overview's eight acceptance criteria have no separate requirement IDs.

Requirements: REQ-042, REQ-044, REQ-049
Decisions: DEC-076, DEC-078, DEC-079
