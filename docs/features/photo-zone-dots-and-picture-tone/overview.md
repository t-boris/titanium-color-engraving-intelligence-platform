---
type: feature
id: photo-zone-dots-and-picture-tone
title: Photo zone dots and picture tone
status: implemented
owner: Boris Tsekinovsky
created: 2026-10-24
provenance: Created by an AI agent through MarkView from Operator request 2026-10-24 (work 41, photo zone 2)
understanding:
  Problem: known
  Target Users: known
  Primary Workflow: known
  Permissions: n/a
  Failure Scenarios: known
  Data Model: known
  Notifications: n/a
  Security: n/a
  Analytics: n/a
  Dependencies: known
  Acceptance Criteria: known
---

# Photo zone dots and picture tone

## Idea

On a photo zone of a vector work in a dot kind (work 41 «Яня портрет - 1», zone 2, Jarvis) the operator could neither choose the dots' colour (the zone's scale 128 mm/s · 60 kHz · 300 ns is measured at 6.1..14.3 %, every power nearly black, and photo zones had no «Цвет с карты») nor make the picture lighter or darker. Scope: the dots of a photo zone take any measured colour of the colour map, as a photo work's dots do since 0.25.0; the picture of a photo work and of a photo zone gets brightness, contrast and gamma, applied to its greys before they become power or dots, so the look and the LightBurn file carry the same greys. Released in 0.27.0.

## Problem

## Scope
