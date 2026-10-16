---
type: plan
feature: titanium-color-engraving-intelligence-platform
title: Titanium Color Engraving Intelligence Platform — Closed-loop implementation
issues:
  - id: I-1
    title: Local application, versioned profiles and observation context
    summary: Establish the single-process local browser application with local offline persistence, tablet access over the local network, and no login or roles. Implement titanium and versioned laser profiles with power, frequency and speed as variable axes, extensible axis definitions, and profile constants preserved in every observation. Provide optional context fields defaulting to unknown with previous-value shortcuts, prevent silent merging across profile versions, and specify the corresponding browser screens without selecting an implementation technology.
    requirements: [REQ-010, REQ-011, REQ-016]
    decisions: [DEC-001, DEC-004, DEC-005, DEC-014, DEC-017]
  - id: I-2
    title: EngravingPlan, calibration plates and LightBurn export
    summary: Define the internal EngravingPlan contract and implement calibration-grid generation and shared LightBurn export. Generate power × frequency grids with speed represented by a plate series, mandatory calibration registration markers and experiment identifiers, and optional production markers outside the image area. Export discrete colors and configurable continuous bands as layers preserving parameters and per-band prediction metadata, with a banding preview. Verify compatibility against the user's LightBurn version, including the required N=32 export and import without manual parameter reassignment; resolve unsupported capabilities before accepting the export implementation.
    requirements: [REQ-002, REQ-003, REQ-010, REQ-011, REQ-012, REQ-013]
    decisions: [DEC-005, DEC-008, DEC-010, DEC-015, DEC-017]
  - id: I-3
    title: Universal LightBurn ingestion and calibration mismatch resolution
    summary: Implement universal paired LightBurn-file and photograph ingestion for calibration plates, finished engravings and imported works. Parse .lbrn/.lbrn2 layer parameters and fill geometry, reconstruct plans and layer masks, flag unreadable parameters, and import unsupported axes with warnings and an explicit non-comparable status. Treat the paired file as authoritative for power, frequency and speed; retain plate definitions for identity and geometry, and block calibration observation acceptance on parameter mismatches until correction or explicit operator confirmation, preserving each discrepancy and confirmation.
    requirements: [REQ-001, REQ-003, REQ-005, REQ-006, REQ-010, REQ-015, REQ-016]
    decisions: [DEC-014, DEC-015, DEC-016, DEC-017]
  - id: I-4
    title: Photographic correction, alignment and region measurement
    summary: Implement RAW capture-setup records, reference-chart detection and chart-based correction before measuring regions. Recover calibration markers, identifiers and cell geometry without guessing failed mappings; align marked works automatically and unmarked works through four-corner placement. Display layer-mask overlays for verification, sample corrected region interiors with edges excluded, and store device-independent colors, parameters and alignment methods per region. Photographs without a detectable chart must be flagged and produce no observations or model updates; repeated photographs of the same artefact shall support rig repeatability measurement.
    requirements: [REQ-001, REQ-003, REQ-009, REQ-013, REQ-015, REQ-016]
    decisions: [DEC-003, DEC-010, DEC-015, DEC-016]
  - id: I-5
    title: Measured color model, prediction uncertainty and reproducibility
    summary: Build the color-space model and parameter-prediction service from eligible measured observations, keeping measurements distinct from predictions and preventing AI output from silently overwriting evidence. Pool comparable parameter sets across artefact sources while preserving profile-version boundaries. Require confidence, expected color error and stability on every prediction and expose them in the UI and plan output, explicitly identifying requests outside measured coverage. Analyze reproducibility and unstable regions, include rig repeatability, group evidence by known material and focus context, and expose unknown-context attribution limits.
    requirements: [REQ-001, REQ-002, REQ-009, REQ-010, REQ-015, REQ-016]
    decisions: [DEC-005, DEC-014, DEC-015, DEC-016]
  - id: I-6
    title: Evidence eligibility, knowledge maturation and production safeguards
    summary: Define shared observation-quality, repetition-independence and applicable threshold rules before implementing automatic validation, without inventing numerical defaults. Apply equal eligibility across sources and preserve eligibility when optional context is absent. Implement automatic maturation through measured, candidate, repeated and validated, explicit production approval, transition history and rollback without automatic production demotion. Flag degraded production entries as questioned with supporting evidence and record manual confirmation or demotion. Reconcile specification references by marking DEC-012 superseded and aligning DEC-011 with the accepted Tonal exception.
    requirements: [REQ-001, REQ-005, REQ-006, REQ-009, REQ-013, REQ-015, REQ-016]
    decisions: [DEC-006, DEC-011, DEC-015, DEC-016, DEC-018]
  - id: I-7
    title: Discrete artwork conversion and unreachable-color handling
    summary: Implement discrete artwork conversion using eligible validated or production colors and a visible, configurable ΔE threshold. Show each match with its titanium color, error, confidence and stability; block finalization until every unreachable color is substituted from the eligible palette or excluded, and automatically register unreachable colors as Experiment Designer targets. Exclude questioned production settings by default and allow explicit inclusion only for the current plan, leaving maturity stages and questioned flags unchanged. Produce a previewable EngravingPlan using the shared marker and export facilities.
    requirements: [REQ-002, REQ-004, REQ-005, REQ-006, REQ-012, REQ-013]
    decisions: [DEC-009, DEC-010, DEC-018]
  - id: I-8
    title: Continuous photo conversion with Tonal and Color-path strategies
    summary: Implement Continuous Photo Engraving through one calibrated transfer-function abstraction with Tonal and Color-path strategies. Map luminance to the specified monotonic parameter curve for Tonal and to a user-selected titanium color trajectory for Color-path, producing configurable bands with prediction metadata and a banding preview. Require plan-specific inclusion of questioned production settings for Color-path; allow their use in Tonal with visible warnings and access to supporting observations without separate confirmation. Preserve knowledge stages and questioned flags during plan generation.
    requirements: [REQ-001, REQ-002, REQ-004, REQ-005, REQ-012, REQ-013]
    decisions: [DEC-007, DEC-008, DEC-010, DEC-018]
  - id: I-9
    title: Post-engraving comparison and closed-loop feedback
    summary: Connect the shared ingestion, alignment and measurement pipeline to completed-engraving comparison against the original plan. Report color deviations for discrete work, brightness and contrast for Tonal, and ΔE along the selected trajectory for Color-path, retaining planned predictions alongside measured results. Estimate reproducibility and detect unstable regions, route eligible observations into model updates, maturation and Experiment Designer inputs, and surface production questioning through the evidence workflow. Verify the complete experiment-to-next-experiment loop across both engraving workflows.
    requirements: [REQ-001, REQ-004, REQ-005, REQ-009, REQ-013, REQ-015, REQ-016]
    decisions: [DEC-007, DEC-010, DEC-014, DEC-015, DEC-016, DEC-018]
  - id: I-10
    title: Offline Experiment Designer and optional explanatory adapter
    summary: Implement an offline acquisition algorithm that scores candidate parameter sets using coverage gaps, uncertainty, instability and target colors, then produces calibration-plate proposals with per-setting reasons and target references. Make proposals reproducible for a fixed database state and seed, incorporate eligible evidence from every artefact source, and pass proposals into calibration-plate generation. Provide an optional LLM explanation adapter that stores only explanatory text and hypotheses, cannot select parameters or modify observations, and leaves proposals identical and fully functional without an API key.
    requirements: [REQ-001, REQ-006, REQ-015, REQ-016]
    decisions: [DEC-009, DEC-013, DEC-015, DEC-016]
  - id: I-11
    title: Task-aware experiment records and outcome knowledge
    summary: Extend each plan, imported job and measured region with an explicit engraving intent and relevant image/geometry features. Keep raw parameter/photo/file evidence separate from derived recipes. Build task-conditioned mappings from the full LightBurn operation and hardware/material context to the measured outcome, so text, lines, filled vectors, tonal images and color images do not inherit one generic recommendation. Use only quality metrics supported by the captured image, calibration reference or independent measurement.
    requirements: [REQ-020]
    decisions: [DEC-042]
  - id: I-12
    title: Image-to-vector engraving workflow
    summary: Accept an image and requested engraving result, prepare an editable vector representation, classify regions and paths by the selected task, and map them to supported evidence-backed strategies. Preview geometry, assignments, confidence, out-of-coverage areas and unresolved choices before writing a standard LightBurn project. Preserve the source image, vector document, generated job and eventual result as one linked work record.
    requirements: [REQ-021]
    decisions: []
  - id: I-13
    title: Periodic findings and experiment acquisition loop
    summary: Reanalyze accepted evidence after new measurements and on a configurable periodic run. Surface reproducible improvements, anomalies, unstable settings and task/material coverage gaps with source links and sample counts. Rank follow-up experiments by the question they answer and expected information gain, save each hypothesis and proposed settings, and export accepted proposals as plates with the configured cleaning operation first.
    requirements: [REQ-022]
    decisions: [DEC-009, DEC-013]
updated: 2026-10-14
---

# Implementation plan — Titanium Color Engraving Intelligence Platform

## I-1: Local application, versioned profiles and observation context

Establish the single-process local browser application with local offline persistence, tablet access over the local network, and no login or roles. Implement titanium and versioned laser profiles with power, frequency and speed as variable axes, extensible axis definitions, and profile constants preserved in every observation. Provide optional context fields defaulting to unknown with previous-value shortcuts, prevent silent merging across profile versions, and specify the corresponding browser screens without selecting an implementation technology.

Requirements: REQ-010, REQ-011, REQ-016
Decisions: DEC-001, DEC-004, DEC-005, DEC-014, DEC-017

## I-2: EngravingPlan, calibration plates and LightBurn export

Define the internal EngravingPlan contract and implement calibration-grid generation and shared LightBurn export. Generate power × frequency grids with speed represented by a plate series, mandatory calibration registration markers and experiment identifiers, and optional production markers outside the image area. Export discrete colors and configurable continuous bands as layers preserving parameters and per-band prediction metadata, with a banding preview. Verify compatibility against the user's LightBurn version, including the required N=32 export and import without manual parameter reassignment; resolve unsupported capabilities before accepting the export implementation.

Requirements: REQ-002, REQ-003, REQ-010, REQ-011, REQ-012, REQ-013
Decisions: DEC-005, DEC-008, DEC-010, DEC-015, DEC-017

## I-3: Universal LightBurn ingestion and calibration mismatch resolution

Implement universal paired LightBurn-file and photograph ingestion for calibration plates, finished engravings and imported works. Parse .lbrn/.lbrn2 layer parameters and fill geometry, reconstruct plans and layer masks, flag unreadable parameters, and import unsupported axes with warnings and an explicit non-comparable status. Treat the paired file as authoritative for power, frequency and speed; retain plate definitions for identity and geometry, and block calibration observation acceptance on parameter mismatches until correction or explicit operator confirmation, preserving each discrepancy and confirmation.

Requirements: REQ-001, REQ-003, REQ-005, REQ-006, REQ-010, REQ-015, REQ-016
Decisions: DEC-014, DEC-015, DEC-016, DEC-017

## I-4: Photographic correction, alignment and region measurement

Implement RAW capture-setup records, reference-chart detection and chart-based correction before measuring regions. Recover calibration markers, identifiers and cell geometry without guessing failed mappings; align marked works automatically and unmarked works through four-corner placement. Display layer-mask overlays for verification, sample corrected region interiors with edges excluded, and store device-independent colors, parameters and alignment methods per region. Photographs without a detectable chart must be flagged and produce no observations or model updates; repeated photographs of the same artefact shall support rig repeatability measurement.

Requirements: REQ-001, REQ-003, REQ-009, REQ-013, REQ-015, REQ-016
Decisions: DEC-003, DEC-010, DEC-015, DEC-016

## I-5: Measured color model, prediction uncertainty and reproducibility

Build the color-space model and parameter-prediction service from eligible measured observations, keeping measurements distinct from predictions and preventing AI output from silently overwriting evidence. Pool comparable parameter sets across artefact sources while preserving profile-version boundaries. Require confidence, expected color error and stability on every prediction and expose them in the UI and plan output, explicitly identifying requests outside measured coverage. Analyze reproducibility and unstable regions, include rig repeatability, group evidence by known material and focus context, and expose unknown-context attribution limits.

Requirements: REQ-001, REQ-002, REQ-009, REQ-010, REQ-015, REQ-016
Decisions: DEC-005, DEC-014, DEC-015, DEC-016

## I-6: Evidence eligibility, knowledge maturation and production safeguards

Define shared observation-quality, repetition-independence and applicable threshold rules before implementing automatic validation, without inventing numerical defaults. Apply equal eligibility across sources and preserve eligibility when optional context is absent. Implement automatic maturation through measured, candidate, repeated and validated, explicit production approval, transition history and rollback without automatic production demotion. Flag degraded production entries as questioned with supporting evidence and record manual confirmation or demotion. Reconcile specification references by marking DEC-012 superseded and aligning DEC-011 with the accepted Tonal exception.

Requirements: REQ-001, REQ-005, REQ-006, REQ-009, REQ-013, REQ-015, REQ-016
Decisions: DEC-006, DEC-011, DEC-015, DEC-016, DEC-018

## I-7: Discrete artwork conversion and unreachable-color handling

Implement discrete artwork conversion using eligible validated or production colors and a visible, configurable ΔE threshold. Show each match with its titanium color, error, confidence and stability; block finalization until every unreachable color is substituted from the eligible palette or excluded, and automatically register unreachable colors as Experiment Designer targets. Exclude questioned production settings by default and allow explicit inclusion only for the current plan, leaving maturity stages and questioned flags unchanged. Produce a previewable EngravingPlan using the shared marker and export facilities.

Requirements: REQ-002, REQ-004, REQ-005, REQ-006, REQ-012, REQ-013
Decisions: DEC-009, DEC-010, DEC-018

## I-8: Continuous photo conversion with Tonal and Color-path strategies

Implement Continuous Photo Engraving through one calibrated transfer-function abstraction with Tonal and Color-path strategies. Map luminance to the specified monotonic parameter curve for Tonal and to a user-selected titanium color trajectory for Color-path, producing configurable bands with prediction metadata and a banding preview. Require plan-specific inclusion of questioned production settings for Color-path; allow their use in Tonal with visible warnings and access to supporting observations without separate confirmation. Preserve knowledge stages and questioned flags during plan generation.

Requirements: REQ-001, REQ-002, REQ-004, REQ-005, REQ-012, REQ-013
Decisions: DEC-007, DEC-008, DEC-010, DEC-018

## I-9: Post-engraving comparison and closed-loop feedback

Connect the shared ingestion, alignment and measurement pipeline to completed-engraving comparison against the original plan. Report color deviations for discrete work, brightness and contrast for Tonal, and ΔE along the selected trajectory for Color-path, retaining planned predictions alongside measured results. Estimate reproducibility and detect unstable regions, route eligible observations into model updates, maturation and Experiment Designer inputs, and surface production questioning through the evidence workflow. Verify the complete experiment-to-next-experiment loop across both engraving workflows.

Requirements: REQ-001, REQ-004, REQ-005, REQ-009, REQ-013, REQ-015, REQ-016
Decisions: DEC-007, DEC-010, DEC-014, DEC-015, DEC-016, DEC-018

## I-10: Offline Experiment Designer and optional explanatory adapter

Implement an offline acquisition algorithm that scores candidate parameter sets using coverage gaps, uncertainty, instability and target colors, then produces calibration-plate proposals with per-setting reasons and target references. Make proposals reproducible for a fixed database state and seed, incorporate eligible evidence from every artefact source, and pass proposals into calibration-plate generation. Provide an optional LLM explanation adapter that stores only explanatory text and hypotheses, cannot select parameters or modify observations, and leaves proposals identical and fully functional without an API key.

Requirements: REQ-001, REQ-006, REQ-015, REQ-016
Decisions: DEC-009, DEC-013, DEC-015, DEC-016

## I-11: Task-aware experiment records and outcome knowledge

Extend plans and observations with the requested engraving intent and only the source features needed to explain the result. Keep measurements and original files immutable; store inferred findings and recommended recipes separately with evidence links. Condition mappings on task, laser, historical lens, titanium/stock and the complete LightBurn operation. Do not treat a single Lab measurement as proof of line quality, text legibility or image similarity.

Requirements: REQ-020
Decisions: DEC-042

## I-12: Image-to-vector engraving workflow

Build the complete path from an uploaded source image to an editable vector engraving plan and standard LightBurn file. Let the operator choose the intended result, prepare/vectorize geometry, assign supported strategies to regions and paths, preview the result, and show where evidence is weak or absent. Link source image, intermediate vector, exported job and photographed outcome so actual work expands the same task-specific knowledge base.

Requirements: REQ-021

## I-13: Periodic findings and experiment acquisition loop

Recompute evidence-backed findings after accepted measurements and on a configurable schedule. Explain what improved, what is unstable and which task/material combinations remain unknown. Propose experiments with a named question, candidate settings and the reason the result would be useful; save the proposal and connect its generated plate and result back to that question. Every calibration/test plate puts its configured surface-cleaning pass before test marks.

Requirements: REQ-022

## Implementation status

Branch `feature/titanium-color-engraving-platform-implementation`, version 0.1.0. GitHub issue #n tracks plan item I-n; issues close only when the work is merged. "Implemented" means code and automated tests exist; "not verified" names what no test can show.

| Item | Status | Code | Not verified / open |
|---|---|---|---|
| I-1 | Implemented | `db.py`, `profiles.py`, `api/`, `cli.py`, `ui/` | Tablet access tested only on this Mac (`--host 0.0.0.0`). |
| I-2 | Implemented | `plans.py` | Exported `.lbrn2` (incl. N=32) not yet opened in LightBurn 2.1.04; checked by re-reading with `lightburn.py`. Marker format and marker-layer settings are proposed (DEC-027). |
| I-3 | Implemented | `lightburn.py`, `ingest.py` | Parser checked against one real `.lbrn2` file; curved paths are approximated by their vertices. |
| I-4 | Implemented | `photo.py`, `ingest.py` | Chart detection and correction verified on OpenCV test images and synthetic renders only, not on a real RAW rig photo (DEC-025). Edge exclusion is proposed (DEC-028). |
| I-5 | Implemented | `model.py` | Estimate formulas are proposed (DEC-026, DEC-029). |
| I-6 | Implemented | `knowledge.py` | Independence per DEC-021; thresholds have no defaults and must be agreed by the operator. Lower-stage rules are proposed (DEC-029). |
| I-7 | Implemented | `conversion.py` (discrete) | Threshold semantics proposed (DEC-030). |
| I-8 | Implemented | `conversion.py` (continuous) | Mapping without parameter interpolation proposed (DEC-032). |
| I-9 | Implemented | `analysis.py` | Uses the shared ingestion path; real engraved results not yet measured. |
| I-10 | Implemented | `designer.py` | Model and acquisition defaults proposed (DEC-033). No LLM adapter is wired; only the text-attachment interface exists. |
| I-11 | Specified | REQ-020 | Current observations measure outcomes but do not yet carry a task-intent taxonomy or task-conditioned recipes. |
| I-12 | Specified | REQ-021 | Current image conversion has plans for artwork/photo modes; end-to-end editable vectorization and evidence-aware LightBurn generation remain to be verified and completed. |
| I-13 | Specified | REQ-022 | Current designer proposes calibration settings; periodic evidence reports and question-linked follow-up experiments are not yet complete. |

Browser UI: Russian (DEC-034), visual system of prototype v10 (DEC-019). Walked through in a browser with synthetic files: profile, rig, marker layer, plate preview and creation, pair upload, check, mask overlay, accept, analysis, color map, knowledge, discrete conversion with an unreachable color excluded, plan export. Four defects found that way were fixed with regression tests.

