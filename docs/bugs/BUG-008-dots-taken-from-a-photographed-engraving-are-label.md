---
type: bug
id: BUG-008
title: Dots taken from a photographed engraving are labelled «с карты цветов» on the photo work and photo zone screens
status: fixed
severity: low
reporter: Boris Tsekinovsky
created: 2026-10-25
updated: 2026-10-25
provenance: Created by an AI agent through MarkView
---

# Dots taken from a photographed engraving are labelled «с карты цветов» on the photo work and photo zone screens

## Summary

Since 0.33.0 a dot kind chosen on a photo work or zone takes the dots of a photographed engraving (dot_recipe with source "photo"), but the shared picture panel (ui/screens/photo-panels.js) words every dot recipe as a colour picked on the colour map. 0.35.2 labels it right in the vector editor's «Фото» tab only («точки 25 % по фото № 149 (Джарвис)»).

## Steps to reproduce

1. Open a photo zone (or photo work) whose kind was chosen after a photograph of its kind (or, from 0.35.2, a kind that failed and takes another kind's dots)
2. Look at the dots line, the scale title, the bar under the ramp and the foot of the picture

## Expected

The source named as it is: «по фото № 149 (Джарвис)», and the estimate explained as dots of a photographed engraving, not a colour of the map.

## Actual

«Точки … с карты цветов: 25 % …», «точки — на настройках цвета с карты цветов», «точки — с карты цветов», «оценка по карте цветов: этот вид на этих настройках ещё не гравировался».

## Environment

0.35.2 rehearsal on a copy of the live workshop, work 41 zone 2, Atkinson

## Resolution

Fixed in 0.35.3. One helper, `PhotoQuality.recipeFrom` (ui/photo-quality.js), names where a recipe's dots come from: «с карты цветов» for
a fill of the colour map, «по фото № N (вид)» for a photographed engraving, «оценка по фото № N (вид)» for dots estimated at settings
not photographed. The photo work and zone screens (ui/screens/photo-panels.js, vector-zone.js), the photo work list
(photo-engraving.js) and the vector editor's «Фото» tab (vector-photo.js) use it. Photo dots are no longer worded as the scale's
(«со шкалы», «оценка по шкале») either. Test: `tests/test_photo_engraving_ui.py::test_dots_taken_from_a_photographed_engraving_name_its_photograph_not_the_colour_map`.
Verified on a copy of the live workshop, on work 41 zone 2 (Atkinson on Jarvis photo 149): «с карты цветов» appears nowhere on the zone
screen, and there are no console errors.
