---
type: feature
id: ready-engraving-settings-for-business-cards
title: Ready engraving settings for business cards
status: exploring
owner: Boris Tsekinovsky
created: 2026-11-07
provenance: Created by an AI agent through MarkView from Operator's request of 2026-11-07 after the release of 0.41.0 (feature-2); code research of the same day
understanding:
  Problem: known
  Target Users: known
  Primary Workflow: partial
  Permissions: n/a
  Failure Scenarios: partial
  Data Model: partial
  Notifications: n/a
  Security: n/a
  Analytics: n/a
  Dependencies: known
  Acceptance Criteria: unknown
related: feature-2
issues: [44]
---

# Ready engraving settings for business cards

## Idea

In the business-card editor (feature-2) the operator chooses "Engraving settings" for an element or a group, and every settings set starts EMPTY: a form of blank number boxes (power, speed, frequency, line interval, passes, pulse width) with "—" and a pill "needs power, speed, …". It is not clear what to enter, which values the workshop already knows, or where a value would come from, and the set carries fewer fields than the engravings the workshop already did (a photo engraving has a mode, minimum power, global passes and more).

The operator wants the opposite: settings are never left empty. For anything on a card the editor either PROPOSES known settings to choose from, or says plainly that the settings are UNKNOWN for this device, lens and material. Choosing comes first; typing numbers ("Custom") is the last resort, for when the operator found nothing suitable among the choices. Examples given by the operator: to get a colour, pick the colour and take the settings of the measured colour recipe; to engrave like a photo engraving, pick the settings of that photo engraving.

Who: the workshop operator composing a titanium card. Known sources in the app today (found by reading the code on 2026-11-07, nothing built yet): best settings per photo kind (`/api/photo-knowledge`), grey scales with a measured power span (`/api/grey-scales`), measured colours and their recipes (`/api/colors/search`, `/api/vector-palette`), validated findings of the device (`/api/devices/{id}/findings`), device passport defaults (pulse width only), and a model prediction that is labelled "not a measurement" (`/api/colors/settings`). There is no generic settings library or preset store.

Scope: choosing settings for the sets of a business card; saying "unknown" honestly; keeping the origin of every chosen set; carrying the fields the source setting has into the card's LightBurn layer. Out of scope until decided: a general settings library for all works, changing how photo or vector works pick their settings, inventing values where nothing was measured (the project never does).

## Problem

## Scope
