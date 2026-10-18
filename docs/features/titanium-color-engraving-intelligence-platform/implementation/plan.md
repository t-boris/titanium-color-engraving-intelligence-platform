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
    decisions: [DEC-065]
  - id: I-13
    title: Periodic findings and experiment acquisition loop
    summary: Reanalyze accepted evidence after new measurements and on a configurable periodic run. Surface reproducible improvements, anomalies, unstable settings and task/material coverage gaps with source links and sample counts. Rank follow-up experiments by the question they answer and expected information gain, save each hypothesis and proposed settings, and export accepted proposals as plates with the configured cleaning operation first.
    requirements: [REQ-022]
    decisions: [DEC-009, DEC-013, DEC-064]
  - id: I-14
    title: Laser and lens replace laser profiles in every table
    summary: Carry out DEC-042 by the full schema migration of DEC-063. Plates, plans, pairs, observations, knowledge, target colours and proposals carry the physical laser and the historical lens instead of a profile; the old profile id stays only as provenance. Comparable knowledge, rules, targets and proposals are partitioned by laser and lens, with job settings in the recipe key. No screen asks for a profile; imports never assert the installed lens; 200 ns is only a device-supported prefill; a lens may be incomplete.
    requirements: [REQ-010, REQ-015, REQ-016, REQ-017, REQ-018, REQ-019]
    decisions: [DEC-042, DEC-043, DEC-063]
  - id: I-15
    title: Closed-loop and translation defects found by the 2026-10-18 audit
    summary: Make generated plan files ingestible and auto-aligned, export the complete recipe settings, keep the repetition of an alignment revision, rebuild knowledge after a deletion without lowering stages, keep marker and label layers out of the model, translate every server message the screen shows, and close the remaining UI and ingestion gaps (band limits and banding picture, colour-path inclusion, capture setup on upload, rig repeatability, restored plans for imports, target-colour check, lens snapshots, one experiment list, honest colour-map search).
    requirements: [REQ-001, REQ-003, REQ-004, REQ-005, REQ-006, REQ-009, REQ-012, REQ-013, REQ-019, REQ-028, REQ-029]
    decisions: [DEC-021, DEC-025, DEC-027, DEC-028, DEC-034, DEC-047, DEC-066]
  - id: I-16
    title: Predicted look of a photo engraving
    summary: Render a grayscale-mode image layer as it will look on titanium from the measured power-to-colour curve of its mode, with the provenance of every curve point, hatched areas outside the measured span, assumed picture adjustments and Min/Max re-rendering.
    requirements: [REQ-030]
    decisions: [DEC-057, DEC-062]
  - id: I-17
    title: Devices, lenses, registration, photo engravings, experiments, colour map, matrix and oxide model
    summary: The work carried from the unmerged branch feat/laser-device-profiles and the session of 2026-10-18 - laser devices with passports and characterization, replaceable lenses, exact LightBurn geometry, element-anchor registration started from the whole drawing, image layers and photo engravings, experiments as single objects, one colour map, the 16-bit linear colour decode, the oxide film model and the parameter matrix read from a photograph - verified and merged.
    requirements: [REQ-017, REQ-018, REQ-019, REQ-023, REQ-024, REQ-025, REQ-026, REQ-027, REQ-028, REQ-029, REQ-031]
    decisions: [DEC-035, DEC-036, DEC-037, DEC-038, DEC-039, DEC-040, DEC-041, DEC-048, DEC-049, DEC-050, DEC-051, DEC-052, DEC-053, DEC-054, DEC-055, DEC-056, DEC-057, DEC-058, DEC-059, DEC-060, DEC-061]
updated: 2026-10-18
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

## I-14: Laser and lens replace laser profiles in every table

Carry out DEC-042 by the full schema migration of DEC-063: device and historical lens on every record, the profile id kept only as provenance, knowledge partitioned by laser and lens with job settings in the recipe key, no profile anywhere in the screens.

Requirements: REQ-010, REQ-015, REQ-016, REQ-017, REQ-018, REQ-019
Decisions: DEC-042, DEC-043, DEC-063

## I-15: Closed-loop and translation defects found by the 2026-10-18 audit

Close the defects that broke the loop or the specification: generated plan files at ingest, complete recipe export, repetition of revisions, rebuild after deletion, marker layers out of the model, translations, and the UI and ingestion gaps listed in the summary.

Requirements: REQ-001, REQ-003, REQ-004, REQ-005, REQ-006, REQ-009, REQ-012, REQ-013, REQ-019, REQ-028, REQ-029
Decisions: DEC-021, DEC-025, DEC-027, DEC-028, DEC-034, DEC-047, DEC-066

## I-16: Predicted look of a photo engraving

Render the predicted look of a grayscale image layer from the measured power-to-colour curve of its mode, flagged camera-relative when nothing referenced exists.

Requirements: REQ-030
Decisions: DEC-057, DEC-062

## I-17: Devices, lenses, registration, photo engravings, experiments, colour map, matrix and oxide model

Verify and merge the work carried from the unmerged branch feat/laser-device-profiles and the session of 2026-10-18.

Requirements: REQ-017, REQ-018, REQ-019, REQ-023, REQ-024, REQ-025, REQ-026, REQ-027, REQ-028, REQ-029, REQ-031

## Implementation status

I-1..I-10: branch `feature/titanium-color-engraving-platform-implementation`, version 0.1.0, merged in #11; GitHub issue #n tracks plan item I-n. I-11..I-17: branch `feat/titanium-color-engraving-intelligence-platform`, pull request #20; issue #(n+2) tracks I-n (I-11 #13 ... I-17 #19); issues close only when the work is merged. "Implemented" means code and automated tests exist; "not verified" names what no test can show.

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
| I-11 | Implemented on the branch, not merged (#13) | `tasks.py`, task_kind on observations, task filters and choosers (b505a75, bc628fd, 33d8ace) | Every REQ-020 criterion has a test; keys of 108 accepted live observations unchanged. Choices recorded as proposed DEC-071. |
| I-12 | Implemented on the branch, not merged (#14) | `vectorize.py`, `vector_job.py`, `api/routes_vector.py`, `ui/screens/vector.js` (f520c39, cbe984d, 96a8ef5) | Opening an exported job in LightBurn is a manual check; a photograph of an exported vector job through ingest is not yet tested end to end; task-conditioned recipes wait for I-11. Choices recorded as proposed DEC-067. |
| I-13 | Implemented on the branch, not merged (#15) | `findings.py`, `api/routes_findings.py`, `designer.py`, `ui/screens/findings.js` (da56ea1, 68820ed, 3d62518) | Analysis after every acceptance, on demand and on a schedule (off by default); findings with history; proposals with question, reasons, status and results; optional AI explanation. Choices recorded as proposed DEC-070. |
| I-14 | Implemented on the branch, not merged (#16) | `db.py` migration, `setup.py`, every module and screen (6bf303b) | Verified on a copy of the live database (662 observations byte-identical); the live database is migrated only by the deploy, after a backup. |
| I-15 | Implemented on the branch, not merged (#17) | S1 576e3c8..93d37a2; S2 cbe984d, 96a8ef5; S3 cd6a130; S6 d2cdd8d..7a78a28 | All audit gaps closed with tests, including operator-supplied missing settings, spot per lens, steps listed, unknown field labelled, margins per side, exactly 6 % when no frame edge, REQ-002 values on computed settings. Final integration: QR read with every identifier (0 of 1000 fail, 32cc1b2), designer models only fill recipes (28be36f), every server message translated (b758973). Manual: LightBurn opening of exported files, tablet access. Choices recorded as proposed DEC-067, DEC-069, DEC-072. |
| I-16 | Implemented on the branch, not merged (#18) | `prediction.py`, `prediction_store.py`, `api/routes_prediction.py`, `ui/screens/photo-preview.js` (c177161, 7f8a597) | Real check on the accepted Inna pair: 13 bins reproduced within 0.17 dE, 5.49 % of the picture outside the measured span, camera-relative. Choices recorded as proposed DEC-068. |
| I-17 | Implemented on the branch, not merged (#19) | `devices.py`, `lenses.py`, `characterization.py`, `anchoring.py`, `picturing.py`, `experiments.py`, `colormap.py`, `oxide.py`, `matrix.py` | CI green on Linux and macOS; oxide kinetics has no usable law on the matrices yet (ORDER_BY_RAMPS off). |

Browser UI: Russian (DEC-034), visual system of prototype v10 (DEC-019). Walked through in a browser with synthetic files: profile, rig, marker layer, plate preview and creation, pair upload, check, mask overlay, accept, analysis, color map, knowledge, discrete conversion with an unreachable color excluded, plan export. Four defects found that way were fixed with regression tests.

