---
type: bug
id: BUG-004
title: The check of a photograph measures hidden layers left behind in a file LightBurn re-saved with its mirror switch changed
status: open
severity: high
reporter: Boris Tsekinovsky
created: 2026-10-23
provenance: Created by an AI agent through MarkView
---

# The check of a photograph measures hidden layers left behind in a file LightBurn re-saved with its mirror switch changed

## Summary

Pair 115 (work 39 «Inna Portait Mix 1», IMG_3403, Inna_Portait_Mix_1_7.lbrn2). The work was exported 60 x 60 mm with MirrorY on and layers C11 and C18 hidden (their recipes were measured on hidden layers, and the export writes the recipe's LightBurn tags). LightBurn 2.2 saved the file with MirrorY off, reflecting every shape about the design (the hidden ones too); its tools then enlarged and moved only the shown layers onto the plate (100 mm, 35 mm from the field's corner). The check knows layers left behind (REQ-050) but compared the files after turning the engraved one back about its moved cleaning rectangle, which put the hidden layers neither where the export had them nor where the move puts them. So C11 and C18 were measured on the ruler and the table beside the plate (L* 71), their outlines were drawn there, and the measured window took the whole file (132 mm on a 100 mm plate). Fixed in 0.25.1: the files are compared as LightBurn saved them, before the engraved one is turned to the plan's axes, with each export turned as LightBurn turns it. Not fixed yet: the export still hides the layers of recipes measured on hidden layers (12 recipes, 58 observations); that needs the operator's decision because the Show switch is part of a recipe's key.

## Steps to reproduce

1. Export a vector work whose colours include a recipe measured on a hidden LightBurn layer (for example P30 F330 V1200 I0.003)
2. Open the file in LightBurn 2.2, select all, enlarge it and move it onto the plate, save
3. Engrave, photograph and check the pair in «Эксперименты»

## Expected

The hidden layers left behind are named in a warning, left out of the measurement and not drawn; the measured window is the plate.

## Actual

The hidden layers are measured beside the plate (ruler, table), their outlines are drawn below the plate, the window is the whole file, and the pair is «Ready to accept».

## Environment

0.25.0 on the operator's data, LightBurn 2.2.00, JCZFiber
