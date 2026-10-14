# Titanium Color Engraving Intelligence Platform

An experimental, data-driven platform that learns the relationship between laser parameters and the colors they produce on titanium from physical calibration experiments, and uses that learned model to generate engraving plans for artwork (discrete colors) and photographs (continuous luminance-driven parameters). It runs as a closed loop — experiment → engraving → photograph → measurement → comparison → model update → next experiment — with physical measurements as the source of truth, every prediction carrying confidence/error/stability, knowledge promoted to production only after repeated observations, and an AI Experiment Designer proposing the next calibration plates.

## Problem

Laser color marking on titanium is poorly reproducible: the same nominal parameters can yield different colors depending on material batch, laser, focus and environment, and colors are discovered by trial and error. Today there is no tool that systematically captures calibration results, aligns photographs of plates to the parameter grid without manual error, quantifies uncertainty and stability of each color, and turns that knowledge into engraving plans for real artwork and photos — nor one that tells the operator which experiment to run next.

## Scope

IN (first version, as stated by the user): material and laser profiles; calibration plate generation with registration markers and experiment identifier; photographing plates and CV-based alignment of cell ↔ parameter set; color measurement and experiment database; color-space model with confidence, expected color error and stability; parameter prediction; stability & reproducibility analysis; knowledge maturation pipeline (measured → candidate → repeated → validated → production); AI Experiment Designer; discrete-color artwork conversion; continuous photo engraving via calibrated transfer function; internal EngravingPlan format; LightBurn integration; post-engraving analysis and continuous learning. Deliverable of the first step is a full Product + System Specification in Markdown, not code.

OUT (not stated / assumed out until decided): direct laser control or firmware; automatic application of model updates to production profiles after a single observation; exact color reproduction guarantees; non-titanium materials; multi-tenant cloud service; hardware (camera, colorimeter) procurement.

## Specification

The confirmed brief, decisions and requirements are in [`docs/features/titanium-color-engraving-intelligence-platform/`](docs/features/titanium-color-engraving-intelligence-platform/overview.md). Open this folder in MarkView to continue them.

### Requirements

- REQ-001 Closed learning loop with measurements as source of truth
- REQ-002 Predictions carry confidence, expected color error and stability
- REQ-003 Calibration plates with registration markers and experiment identifier
- REQ-004 Two independent engraving workflows
- REQ-005 Knowledge maturation before production use
- REQ-006 AI Experiment Designer
- REQ-009 Controlled photographic measurement setup with reference chart
- REQ-010 Single laser profile with fixed variable axes
- REQ-011 Single-user locally run web application with LightBurn export
- REQ-012 EngravingPlan export to LightBurn as quantized parameter layers
- REQ-013 Post-engraving analysis of production engravings with optional markers
