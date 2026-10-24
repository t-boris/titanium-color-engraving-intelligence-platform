---
type: plan
feature: electron
title: Electron Desktop Workshop and Laboratory Exchange
issues:
  - id: I-1
    title: Define the portable laboratory contract and compatibility fixtures
    summary: Define the versioned .tcelab JSON Schema, canonical hashing, stable laboratory and observation identities, release identity allocation, provenance, capabilities and compatibility policy. Provide golden and negative fixtures and a benchmark-backed resource envelope for large libraries. Distinguish file-export identity from server-assigned publication identity and establish the shared numerical EvidenceSource contract.
    requirements: [REQ-083, REQ-087]
    decisions: [DEC-024, DEC-026, DEC-032, DEC-034, DEC-035]
  - id: I-2
    title: Export privacy-preserving numerical laboratory releases
    summary: Implement incremental export of selected own measurements and tonal profiles using an explicit field allowlist, with a review of contents, excluded fields and author-selected usage terms. Recalculate summaries exclusively from selected independent engravings and preserve measurement bases and quality states. Prevent export of connected external data and verify privacy using unique markers in private fields and image payloads. Finalize the approved usage-term options before accepting this issue.
    requirements: [REQ-083]
    decisions: [DEC-023, DEC-024, DEC-032, DEC-037]
  - id: I-3
    title: Import and manage connected laboratory releases safely
    summary: Implement staged, cancellable import with compatibility, integrity, identity, reference and resource validation followed by atomic activation. Store external releases separately as persistent read-only sources, identify unverified file authorship and make repeated imports idempotent. Add manual or configured update checks, release comparisons, withdrawal handling and safe disconnection while retaining snapshots referenced by saved work. Verify interruption, malformed input and large-library behavior without changing existing observations.
    requirements: [REQ-083, REQ-084]
    decisions: [DEC-024, DEC-025, DEC-026, DEC-029, DEC-038, DEC-041]
  - id: I-4
    title: Use external evidence in reproducible local workflows
    summary: Adapt palette, color-map and supported photo-prediction workflows to an explicitly selected EvidenceSource without requiring the author's files. Preserve setup compatibility, eligibility, extrapolation and LightBurn constraints. Pin saved work to exact releases, recipes and algorithm versions; explicit source updates create a new work version with a route back. Support separate own transfer experiments with equipment-limit checks, provenance and Lab/ΔE comparison, and verify that recipient images and work usage remain local.
    requirements: [REQ-085, REQ-084]
    decisions: [DEC-023, DEC-025, DEC-026, DEC-032]
  - id: I-5
    title: Build the desktop shell and bundled core lifecycle
    summary: Package the existing interface and Python core for macOS Apple Silicon and Windows x64, validating native dependencies and bundled resources on clean machines. Implement workshop creation and selection, discovery of existing ~/.titanium-platform data, remembered workshop selection, readiness and compatibility checks, process supervision, workshop locking and safe shutdown. Verify the complete supported offline workflow without an account or installed developer tools, and use D0 evidence to establish minimum OS versions.
    requirements: [REQ-080]
    decisions: [DEC-021, DEC-022, DEC-030, DEC-034, DEC-036]
  - id: I-6
    title: Implement recoverable workshop backup and schema migration
    summary: Provide complete, consistent workshop backups and restoration into a different folder, including committed WAL data and files required by saved work. Gate migrations on compatibility, space and successful recovery backup creation; prevent concurrent migration and activation of partially migrated data. Preserve the previous successful backup on failure, require explicit overwrite choices and verify coordinated database/file recovery and compatible rollback.
    requirements: [REQ-081, REQ-080]
    decisions: [DEC-021, DEC-031]
  - id: I-7
    title: Secure desktop sessions and persistent tablet access
    summary: Isolate the renderer with sandboxing, context isolation and a minimal privileged API, and authenticate the loopback service with session, origin and request-forgery protection. Add explicitly enabled LAN access with protected transport, persistent device pairing, device inspection and immediate revocation without exposing the desktop secret. Specify and validate the pairing and transport design, verify tablet photo upload and firewall behavior on both platforms, and ensure untrusted content cannot execute.
    requirements: [REQ-082, REQ-080]
    decisions: [DEC-029, DEC-033]
  - id: I-8
    title: Deliver cloud identity, invitations and laboratory discovery
    summary: Integrate managed authentication with system-browser sign-in, secure desktop return and recovery of the same account and laboratory ownership. Implement owner-managed public and invitation-only laboratories, invitations and server-side reader authorization across metadata, manifests and content downloads. Provide anonymous public discovery and release cards with usage terms, deny unauthorized private access and exclude participant contributions. Reconcile the superseded public-only wording in DEC-027, DEC-028 and the cloud API description before acceptance.
    requirements: [REQ-086, REQ-084]
    decisions: [DEC-021, DEC-027, DEC-028, DEC-037, DEC-038, DEC-040, DEC-041]
  - id: I-9
    title: Publish immutable releases with atomic finalization and safe retries
    summary: Implement owner-authorized incremental uploads, bounded upload lifetime, resumable retries and idempotent finalization through the server API. Validate the complete numerical projection, schema, resource limits and hash before atomically exposing immutable content and catalogue indexes to the authorized audience. Enforce expected-previous-release concurrency checks, preserve withdrawal events separately from release content and verify complete retrieval while the author's computer is offline using deployed-service limits and the validated large-library envelope.
    requirements: [REQ-087, REQ-083, REQ-084]
    decisions: [DEC-024, DEC-026, DEC-028, DEC-035, DEC-038, DEC-041]
  - id: I-10
    title: Deliver signed updates, network controls and release diagnostics
    summary: Distribute signed installers and verified updates through project-owner-controlled resources, keeping signing keys outside the repository and applying updates only at safe operation boundaries. Add configurable application and laboratory checks, localized network-failure recovery, local logs and explicitly requested sanitized diagnostic export. Verify that disabled automatic checks cause no publication or catalogue traffic during ordinary local work, telemetry is absent by default, verification failures block installation and clean-machine release checks cover the supported platform matrix.
    requirements: [REQ-080]
    decisions: [DEC-021, DEC-030, DEC-031, DEC-036, DEC-039]
updated: 2026-10-21
---

# Implementation plan — Локальное приложение Electron и обмен лабораториями

## I-1: Define the portable laboratory contract and compatibility fixtures

Define the versioned .tcelab JSON Schema, canonical hashing, stable laboratory and observation identities, release identity allocation, provenance, capabilities and compatibility policy. Provide golden and negative fixtures and a benchmark-backed resource envelope for large libraries. Distinguish file-export identity from server-assigned publication identity and establish the shared numerical EvidenceSource contract.

Requirements: REQ-083, REQ-087
Decisions: DEC-024, DEC-026, DEC-032, DEC-034, DEC-035

## I-2: Export privacy-preserving numerical laboratory releases

Implement incremental export of selected own measurements and tonal profiles using an explicit field allowlist, with a review of contents, excluded fields and author-selected usage terms. Recalculate summaries exclusively from selected independent engravings and preserve measurement bases and quality states. Prevent export of connected external data and verify privacy using unique markers in private fields and image payloads. Finalize the approved usage-term options before accepting this issue.

Requirements: REQ-083
Decisions: DEC-023, DEC-024, DEC-032, DEC-037

## I-3: Import and manage connected laboratory releases safely

Implement staged, cancellable import with compatibility, integrity, identity, reference and resource validation followed by atomic activation. Store external releases separately as persistent read-only sources, identify unverified file authorship and make repeated imports idempotent. Add manual or configured update checks, release comparisons, withdrawal handling and safe disconnection while retaining snapshots referenced by saved work. Verify interruption, malformed input and large-library behavior without changing existing observations.

Requirements: REQ-083, REQ-084
Decisions: DEC-024, DEC-025, DEC-026, DEC-029, DEC-038, DEC-041

## I-4: Use external evidence in reproducible local workflows

Adapt palette, color-map and supported photo-prediction workflows to an explicitly selected EvidenceSource without requiring the author's files. Preserve setup compatibility, eligibility, extrapolation and LightBurn constraints. Pin saved work to exact releases, recipes and algorithm versions; explicit source updates create a new work version with a route back. Support separate own transfer experiments with equipment-limit checks, provenance and Lab/ΔE comparison, and verify that recipient images and work usage remain local.

Requirements: REQ-085, REQ-084
Decisions: DEC-023, DEC-025, DEC-026, DEC-032

## I-5: Build the desktop shell and bundled core lifecycle

Package the existing interface and Python core for macOS Apple Silicon and Windows x64, validating native dependencies and bundled resources on clean machines. Implement workshop creation and selection, discovery of existing ~/.titanium-platform data, remembered workshop selection, readiness and compatibility checks, process supervision, workshop locking and safe shutdown. Verify the complete supported offline workflow without an account or installed developer tools, and use D0 evidence to establish minimum OS versions.

Requirements: REQ-080
Decisions: DEC-021, DEC-022, DEC-030, DEC-034, DEC-036

## I-6: Implement recoverable workshop backup and schema migration

Provide complete, consistent workshop backups and restoration into a different folder, including committed WAL data and files required by saved work. Gate migrations on compatibility, space and successful recovery backup creation; prevent concurrent migration and activation of partially migrated data. Preserve the previous successful backup on failure, require explicit overwrite choices and verify coordinated database/file recovery and compatible rollback.

Requirements: REQ-081, REQ-080
Decisions: DEC-021, DEC-031

## I-7: Secure desktop sessions and persistent tablet access

Isolate the renderer with sandboxing, context isolation and a minimal privileged API, and authenticate the loopback service with session, origin and request-forgery protection. Add explicitly enabled LAN access with protected transport, persistent device pairing, device inspection and immediate revocation without exposing the desktop secret. Specify and validate the pairing and transport design, verify tablet photo upload and firewall behavior on both platforms, and ensure untrusted content cannot execute.

Requirements: REQ-082, REQ-080
Decisions: DEC-029, DEC-033

## I-8: Deliver cloud identity, invitations and laboratory discovery

Integrate managed authentication with system-browser sign-in, secure desktop return and recovery of the same account and laboratory ownership. Implement owner-managed public and invitation-only laboratories, invitations and server-side reader authorization across metadata, manifests and content downloads. Provide anonymous public discovery and release cards with usage terms, deny unauthorized private access and exclude participant contributions. Reconcile the superseded public-only wording in DEC-027, DEC-028 and the cloud API description before acceptance.

Requirements: REQ-086, REQ-084
Decisions: DEC-021, DEC-027, DEC-028, DEC-037, DEC-038, DEC-040, DEC-041

## I-9: Publish immutable releases with atomic finalization and safe retries

Implement owner-authorized incremental uploads, bounded upload lifetime, resumable retries and idempotent finalization through the server API. Validate the complete numerical projection, schema, resource limits and hash before atomically exposing immutable content and catalogue indexes to the authorized audience. Enforce expected-previous-release concurrency checks, preserve withdrawal events separately from release content and verify complete retrieval while the author's computer is offline using deployed-service limits and the validated large-library envelope.

Requirements: REQ-087, REQ-083, REQ-084
Decisions: DEC-024, DEC-026, DEC-028, DEC-035, DEC-038, DEC-041

## I-10: Deliver signed updates, network controls and release diagnostics

Distribute signed installers and verified updates through project-owner-controlled resources, keeping signing keys outside the repository and applying updates only at safe operation boundaries. Add configurable application and laboratory checks, localized network-failure recovery, local logs and explicitly requested sanitized diagnostic export. Verify that disabled automatic checks cause no publication or catalogue traffic during ordinary local work, telemetry is absent by default, verification failures block installation and clean-machine release checks cover the supported platform matrix.

Requirements: REQ-080
Decisions: DEC-021, DEC-030, DEC-031, DEC-036, DEC-039
