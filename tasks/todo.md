# Implement the whole specification (goal set 2026-10-18)

Branch `feat/titanium-color-engraving-intelligence-platform`, created from `origin/main` (5d31a9d) and fast-forwarded by the 20
unmerged commits of `feat/laser-device-profiles` (REQ-017..REQ-029). Baseline on the carried working tree: 561 passed, 0 skipped
(5 min 27 s). Spec read in full: 29 requirements, 61 decisions, 24 questions, 3 findings, discussion.md.

## Gap analysis (five read-only audits of every acceptance criterion, 2026-10-18)

Binding and not (fully) implemented:
- DEC-042 / Q-022 (B): laser profiles are still a NOT NULL foreign key on plate, plan, pair, observation, knowledge, target_color,
  proposal; the operator must create one before ingest, artwork, photo engraving, designer, calculator; "Профили" is in the menu.
  Imports take the profile's lens (REQ-016 AC3), servers default 200 ns (REQ-010 AC7), lens focal length NOT NULL (REQ-019 AC1).
- REQ-013 loop broken: a LightBurn file exported from a discrete / tonal / colour-path plan is refused at ingest ("experiment
  identifier TCE-A-/TCE-P- not known"), so no generated plan can be measured; marked works never align automatically.
- REQ-012: export writes recipe settings (layer type, bidirectional, cross-hatch, angle, ...) as defaults; the recipe key holds them.
- DEC-021: an alignment revision is stored as a re-photograph; accepting it leaves the engraving with 0 independent repetitions.
- DEC-047: knowledge is not rebuilt after a pair is deleted; a plan with active pairs can be cascade-deleted; plates never marked Deleted.
- DEC-027/028: capability-plate marker/label layers can become model-eligible observations on a charted photograph.
- DEC-034: "not comparable to this hardware/search setup: ..." (operator's printout 2026-10-18), every "... not found" (KeyError),
  api/ messages, matrix titles and layer names reach the screen in English; the coverage test cannot see them.
- REQ-004: colour-path has no per-plan inclusion of questioned sets in the UI; tonal warning links only the first entry.
- REQ-012: photo form defaults to 32 bands and says "1–255" (limit 28/29); the banding preview is a table, not a picture.
- REQ-009: no capture setup is recorded (a dummy "Photo capture (no rig)"); rig repeatability is never shown; DEC-025 chart
  reference values hard-coded instead of a capture-setup setting.
- REQ-005/006: imported files never become an EngravingPlan (MODE_RESTORED unused); a plate made for a target colour is never
  checked against it after measurement.
- REQ-019 AC6: artwork/photo plans take no lens snapshot; snapshots carry no spot basis.
- REQ-020 (I-11): no task kind on plans, plates, pairs or observations; no task filter; recommendations without counts/confidence;
  metrics without method/basis; provisional (checked, not accepted) pairs missing from the general colour map (DEC-045).
- REQ-029/DEC-021: colour-map search counts re-photographs as repeats, mixes chart and camera-relative points, merges batches.
- REQ-028: cancelled/superseded plates listed as "waiting for a photo"; the device tab keeps a second list of photographs.
- REQ-022 (I-13): no run-on-demand or scheduled analysis, no aggregated findings (improvement / anomaly / unstable / gap), findings
  history overwritten (AC6), proposals without question/hypothesis/context, no accepted state, plate -> pair -> result not linked.
- REQ-021 (I-12): no vectorisation (pixel runs -> rectangles at 160 px), only three strategies, no editing, no weak-evidence preview.
- REQ-030 (draft): nothing implemented; blocked by Q-025 (open).
- Designer (DEC-033 + DEC-042): one GP over six axes mixes job-setting groups; rules/targets keyed by raw profile id.
- Oxide (DEC-060, proposed): ignores model_eligible, mixes devices/lenses; /colors/settings gives computed settings without the
  three values of REQ-002.
- Small bugs: delete_device uninstalls the lens before refusing; device.js reads a pulse_width profiles never carry.

Spec contradicts itself (need the operator): chart/rig in every frame (REQ-001/003/009/013/015/024) vs accepted DEC-045/053;
REQ-003 "no plate without markers" vs unmarked small-patch plates (README); DEC-047 "rebuild" vs DEC-029 "never lower a stage";
DEC-013 "LLM never chooses parameters" vs the AI researcher that creates plates; DEC-048 vs proposed DEC-058; REQ-016 "material
optional" vs REQ-020 "titanium stock on every record"; DEC-028 "skip < 25 px" vs DEC-050 narrow-stroke fallback; DEC-008 free N vs
DEC-044 cap; DEC-029/033/041/056 still speak of profile versions after DEC-042.

## Plan (work packages; each ends with tests green and the spec updated)

- [x] WP-0 Branch from origin/main, baseline, CI installs tesseract (matrix OCR tests must not skip in CI).
- [x] WP-1 Spec reconciliation: answers and resolutions recorded as decisions in MarkView; plan.md status table; GitHub issues
      for I-11..I-13 and the new work items.
      Done 2026-10-18: DEC-058..061 accepted, REQ-030/031 approved, Q-025 answered (DEC-062), DEC-063 (full schema
      migration), DEC-064 (AI researcher exception), DEC-065 (contour vectoriser), DEC-066 (9 reconciliations); issues #13-#19
      (I-11..I-17), draft PR #20; plan.md items I-14..I-17 and statuses.
- [x] WP-2 Translations (DEC-034) and a coverage test that collects KeyError, api/ and wrapped messages.
- [x] WP-3 Closed-loop bugs: generated plans ingestible and auto-aligned (REQ-013), full settings on export (REQ-012), revision
      keeps its repetition (DEC-021), deletion rebuild and plan protection (DEC-047), marker/label never model-eligible
      (DEC-027/028), device delete, unreadable QR (REQ-003).
- [x] WP-4 DEC-042: no operator-managed profiles (approach per the operator's answer), device + lens + job settings everywhere,
      lens may be incomplete, imports do not assert the installed lens, 200 ns only as a device-supported prefill.
      Done 6bf303b: full schema migration (DEC-063), review found 0 critical / 5 major (all fixed); live-database copy: 662
      observations byte-identical; 580 passed. Startup refusal names the exact SQL fix (0.3.1 cannot re-link a profile with
      records). Next: three parallel streams in worktrees — S1 loop + ingestion (WP-3, WP-6), S2 export + conversion UI +
      vector job (WP-5, WP-10), S3 experiments + colour map + prediction (WP-7, WP-11); then WP-8, WP-9, WP-2, WP-12, WP-13.
- [x] WP-5 Conversion UI: band limits and banding picture, colour-path inclusion, tonal warning with all observations, lens
      snapshot with spot basis on every plan.
- [x] WP-6 Ingestion completeness: capture setup on upload, chart reference in the setup, rig repeatability shown, restored
      EngravingPlan for imports, target-colour check after measurement.
- [x] WP-7 Experiments and colour map: cancelled plates, one list, provisional pairs, honest search grouping.
      Streams merged 2026-10-18: S1 576e3c8..93d37a2, S2 f520c39..96a8ef5, S3 c177161..445df58; integration fix; 746 passed.
      Proposed decisions for the operator: DEC-067 (S2), DEC-068 (S3), DEC-069 (S1). The live app on 8765 was found serving
      the new UI against the old in-memory backend (it ran from the working tree); restarted from the installed wheel of
      59c4704 after a backup (lessons.md).
- [x] WP-8 REQ-020 task kinds end to end.
- [x] WP-9 REQ-022 findings and proposals loop.
- [x] WP-10 REQ-021 image -> vector LightBurn job (approach per the operator's answer).
- [x] WP-11 REQ-030 predicted look of a photo engraving (after Q-025).
- [x] WP-12 Designer and oxide model per comparable partition; REQ-002 values on computed settings.
- [x] WP-13 Tests for every criterion that has code but no test.
      Final: 909 passed (0 skipped); QR 0/1000 failures; pre-deploy check on an isolated full copy (database + files):
      16/16 experiments accepted as in the running app, every photo and overlay served, 565/565 colour-map points.
- [ ] WP-14 Version 0.4.0, PR, CI, merge, tag, deploy (DEC-024), browser walkthrough, manual checklist.

# New experiment kind: a parameter matrix (LightBurn Material Test) read from its photograph — goal set 2026-10-18

Operator: photographs of colour matrices; every square is engraved with its own settings, the settings are engraved as text, two
parameters vary along the two axes. Samples: IMG_3300 (power x speed, 250 kHz 9 ns), IMG_3301 (power x speed, 330 kHz 4 ns), IMG_3302
(power x speed, 60 kHz 300 ns), IMG_3304 (power x interval, 1950 kHz 2 ns), IMG_3305 (1-D: Q-pulse 1..10 ns and passes 1..5 at 40 %),
IMG_3306 (1-D: interval 0.001..0.005 at 40 %). All carry a ColorChecker and a ruler; all are 1.5–3.8 stops under-exposed.

Design: the matrix becomes an ordinary pair whose LightBurn file is generated from the recognised grid and the confirmed settings (one
Scan layer per cell), so the check, the masks, acceptance, observations, the colour map and the oxide model work unchanged.

- [x] 1. `photo.correct`: detect the chart on an exposure-normalised rendering of the linear decode (prototype: found on 6/6, residual
      2.8–3.6 dE; on the 8-bit decode 1/6).
- [x] 2. `matrix.py`: square cells -> lattice (lattice -> px) -> grid extent (cell vs gap contrast, uniform interior, connected to the
      detected squares) -> rectified grid -> labels (row numbers left, column numbers below rotated, header above, axis titles) read with
      tesseract when it is installed (an optional system program, no new Python dependency) -> interpretation: fixed settings from the
      header, the two varying parameters from the axis titles / what the header lacks, axis values as an evenly spaced sequence fitted
      robustly to the labels that were read (misreads repaired, at least 3 consistent labels) -> rows/cols trimmed or extended by labels.
      Several matrices in one photograph: every complete one is a candidate.
- [x] 3. Generated LightBurn file (cell pitch 5 mm by default; settings tags as the parser reads them) and the alignment of a matrix pair
      straight from the lattice (method "material test grid").
- [x] 4. Ingest: create a matrix pair from a photograph (+ laser profile, titanium), edit the spec (axis parameter, min, max, count, fixed
      values) which regenerates the file and re-checks, confirm the spec; acceptance refuses an unconfirmed or incomplete spec.
- [x] 5. API + UI: upload mode "Матрица параметров" (photo only), the matrix card on the review screen (what was read, editable spec,
      confirm), other matrices of the same photo offered as their own experiments; experiment list names the kind.
- [x] 6. Tests: synthetic material-test photograph (grid, labels, chart, under-exposed) -> detection, interpretation, repair of misreads,
      generated file round trip, whole path to observations; OCR tests skip without tesseract.
- [x] 7. The six real photographs through the application; numbers here; DEC + REQ in MarkView; full suite.

## Film order along a matrix, kinetics per pulse regime (PROPOSAL, awaits the operator's approval)

Finding (2026-10-18, operator's paste of the "settings for a colour" card): the kinetics gives no settings although the
matrices are exactly the dose ramps its note asked for. Measured on the live store:

| regime | cells with dose | thickness determined | Spearman thickness~dose | power law r2 |
|---|---|---|---|---|
| 1950 kHz 2 ns (IMG_3304, 3306) | 112 | 48 | 0.02 | 0.003 |
| 330 kHz 4 ns (IMG_3301) | 107 | 50 | 0.50 | 0.035 |
| 250 kHz 9 ns (IMG_3300) | 106 | 11 | 0.72 | 0.31 |
| 60 kHz 300 ns (IMG_3302) | 0 | — | — | — |

- Cause 1: the thickness is fitted to each colour on its own. In IMG_3301 the palest cells (almost bare titanium) get 96 nm,
  neighbours jump 96 / 226 / 126 / 274 / 400 nm, while the colours run smoothly pale -> gold -> purple -> blue -> teal with dose.
- Cause 2: IMG_3302 has no dose: 300 ns is not a pulse step of the JPT M7 passport (… 250, 350, 500). Question to the operator:
  which pulse did the laser actually fire for "Q-Pulse 300 ns"?
Approved by the operator 2026-10-18 ("Да, делай"); the IMG_3302 pulse: "Не знаю" (the manufacturer's note in the device
template: a width that is not a step is ignored and the laser keeps the last valid one, so the fired pulse is unknown; the plate
stays on the colour map and out of the kinetics).
- [x] 1. Ramp-wide film order (`oxide.assign_ramps`, dynamic programming over the dose order, lightness weighted 0.35). Works on
      model-generated ramps (tests). FAILS on the real matrices, so it is OFF (`ORDER_BY_RAMPS = False`):
      | variant | IMG_3301 palest cells | path | median coloured residual |
      |---|---|---|---|
      | per cell (current) | 96 nm | jumps 96/226/126/400 | 4.87 |
      | ramp, plain dE | 96 nm | 96 -> 126 -> 228 -> 398 | 6.84 |
      | ramp, lightness 0.35 | 14 nm | 14 -> 126 -> 226, skips gold/purple/blue | 7.65 |
      | ramp, gain up to 2.2 | 20 nm | purple/blue cells 60-90 % dark oxide | 3.62 |
      | ramp, gain 1.6 + flare 0.1 | 10 nm | 10 -> 14 -> 210, purple/blue undetermined | 3.07 global, 4.23 after |
      Cause: the model's first-order colours are much darker and more saturated than the measured ones (model purple 36 nm
      L 27 b -22, blue 44 nm b -47; measured purple L 40 b -13, blue L 44 b -19); the paler second order wins. The "usable"
      laws the ramps produced (r2 0.6-0.85, exponents 2-5.6) are artefacts of the monotone constraint.
- [x] 2. Kinetics per pulse regime (`regime_laws`): in place; on the per-cell thicknesses no regime is usable (r2 0.31 / 0.04 / 0.003).
- [x] 3. Settings for a colour per usable regime (`_by_regime`: dose from the law, the nearest measured cell, the power that
      reaches the dose): in place, shows nothing until a law is usable. The colour card shows it.
- [x] 4. Tests: monotone path, ramp placement, per-regime laws, power search; 6 new / updated in tests/test_oxide.py.
- [ ] NEXT (needs the operator's approval): make the film model reproduce a measured ramp before ordering by it: thickness
      non-uniformity within a cell (spectra averaged over d +- sigma, which washes out the higher orders and the saturation),
      a specular gain above 1 and a flat flare, fitted on the matrices. Acceptance: on IMG_3301 the cells run pale -> gold ->
      purple -> blue in the first order (10-70 nm) in dose order, median coloured residual <= 5 dE, exponents of the laws
      0.2-1.5; only then ORDER_BY_RAMPS on.
- Alternative without physics (needs approval: the photo engraving deliberately does not interpolate): settings for a colour
  from the matrices directly, the nearest cell and interpolation between neighbouring cells of one matrix.
- Today already: for a colour the matrices produced, the colour map gives the measured settings (e.g. a blue L 55 b -25:
  a matrix cell at dE 1.7, obtained in 3 experiments).

## Fixes from the same paste (done 2026-10-18)
- [x] "null" above the film card: the DOM's replaceChildren prints a null child; `App.fill` skips them like `h()`. Same flaw
      fixed on the experiment page (the new matrix block) and the photo-engraving form. Static test guards every screen.
- [x] The kinetics and colour notes reached the screen in English: the translation coverage test now also collects
      `{"note": ...}` literals and conditional messages; translations added. The kinetics note no longer asks for ramp plates.
- [x] Verified in the browser: colour search without "null", Russian note; matrix table on the experiment page.

## Results (2026-10-18)

| photo | matrix | read | missing / wrong |
|---|---|---|---|
| IMG_3300 | 10 x 10 power 20->60 % x speed 1500->500 mm/s, 250 kHz 9 ns 0.002 mm 1 pass | complete | — |
| IMG_3301 | 10 x 10 power 25->50 x speed 1500->300, 330 kHz 4 ns 0.003 mm 1 | complete | — |
| IMG_3302 | 10 x 10 power 5->30 x speed 150->50, 60 kHz 300 ns 0.0169 mm 1 | complete | — |
| IMG_3304 | 10 x 10 power 10->100 x interval 0.010->0.001, 1800 mm/s 1950 kHz 2 ns 1 | complete | — |
| IMG_3305 | 1 x 10 Q-pulse 10->1 ns at 1800 mm/s 1950 kHz 1 pass; + a 1 x 5 passes column | rows, speed, frequency, passes | power (label cut by the plate edge), interval (overprinted); the second column's labels |
| IMG_3306 | 1 x 5 interval 0.005->0.001 at 40 % 1800 mm/s 1950 kHz 2 ns | all | passes read 4 instead of 1 |

- Through the running application (POST /matrix-pairs + check): pairs 52–57 created with laser profile 1 and Big Plate 150 Grade 5,
  100 / 100 / 100 / 100 / 0 / 5 cells measured, chart residual 2.8–3.6 dE.
- On the colour map (operator's remark "add the results to the colour map"): every read setting was compared with the engraving on
  the chart-corrected overlay; 3306 passes corrected 4 -> 1 (the header reads "Passes: 1"). Accepted: 52 (by the operator), 53, 54, 55,
  57 (the operator replaced 57 by its re-check 58 with the same settings). 405 calibrated points of matrices on the map (555 in all).
- IMG_3305: the first pair (56) was deleted by the operator. Re-created as pair 59 (unconfirmed, 10 / 10 cells measured):
  interval 0.0030 mm read by eye under an overprinted faint label column; power 40 % proposed, NOT read: the column label is cut by
  the plate edge, only its last "0" is visible. Cross-check of its 2 ns cell against the same settings elsewhere (CIE76):
  IMG_3304 interval 0.003 at 30 % 8.8, at 40 % 8.2; IMG_3306 at 40 % 12.5; the same setting on 3304 vs 3306 differs by 5.7,
  so 30 % and 40 % cannot be told apart by colour. Verified afterwards from IMG_3306: the same Q-pulse plate lies there turned by
  90 deg at the right edge with "1.00", "2.00" and the complete power label "40.0" (a seam between two plates runs through the
  label, which is why IMG_3305 shows only its last "0"); its 1 ns and 2 ns cells match the IMG_3305 cells within dE 1.4 and 1.9,
  the crossed pairs differ by more than 10. The operator confirmed and accepted pair 59 at 40 % (17:58). The pair's stored note
  still says "proposed, not read"; the application has no way to edit a pair note and no screen shows it.
  The second matrix of the photo (1 x 5 passes at 40 %) has its interval and Q-pulse outside the photograph; not created.
- All six examples accepted: 415 matrix colours on the map, 565 in all.
- Oxide model refitted on 448 calibrated observations: median coloured residual 4.89 dE (goal < 5). Kinetics: still no single law
  (r2 0.01 on 111 points); the matrices are ramps at a fixed pulse regime, so a law per regime is the next step (needs approval).
- Chart on an exposure-normalised rendering: found on 6 / 6 sample photographs (before: 1 / 6).
- Tests: `tests/test_matrix.py` (15: geometry, dark chart, cut matrix, label fits, header, interpretation, OCR on a synthetic matrix,
  generated file, image->mm, edit, whole path to observations, refusals). DEC-061 and REQ-031 in MarkView (proposed / draft).

# Oxide thickness model, kinetics, settings for a colour, colour map — approved 2026-10-18 ("выполняй все по порядку")

- [x] 1. `oxide.py`: thin-film model (air / TiO2 film / titanium, Fresnel at the capture angle, D65, CIE 1931 2 deg -> Lab) with two
      mechanisms: an interference film of thickness d and a share f of absorbing dark oxide; global parameters (film index scale, film
      absorption, gloss, angle) fitted on every calibrated observation; per observation: thickness, dark share, residual dE, and whether
      another interference order fits almost as well. Success: median dE < 5 on the coloured regimes. API `GET /oxide/model`, tests.
- [x] 2. Kinetics: dose features from the layer settings and the device (average power, pulse energy, pulses per spot, line overlap);
      thickness and dark share against dose on the calibrated points; a monotone law fitted and its residual reported; `GET /oxide/kinetics`.
- [x] 3. Settings for a colour: `POST /colors/settings` with a target Lab -> nearest measured observations (as now) + model candidates
      (thicknesses of every order within tolerance -> dose -> power for every measured mode), each marked measured / computed with its
      expected error; shown in the colour map's search panel.
- [x] 4. Colour map: a lightness band control (L* range) and the three Lab projections; a settings card for the picked point with its
      neighbours in settings; the model's thickness spiral drawn under the points.
- [x] 5. Full suite (540 passed), the map and the three endpoints checked on the live data, DEC-060 in MarkView.

## Results (2026-10-18)

- Model (`oxide.py`, DEC-060 proposed): fitted on 43 chart-corrected observations: index scale 1.0, film absorption 0.05, gloss 1.0,
  angle 0. Coloured regimes (32): median residual 3.6 dE (goal 5), p90 9.5; dark regimes (11): median 1.1 dE through the dark-oxide share;
  70 % of all points within 5 dE; 25 points admit a second interference order within 3 dE; 15 thicknesses determined outright.
  Readings: golds 100–130 nm (first order) or 224–232 nm (second), blues 58–88 nm, purples ~272–282 nm, "black" = dark oxide 70–90 %.
- Kinetics: areal energy of the settings against thickness on this set: r2 0.07 -> no usable law (finished works mix 4 ns / 9 ns / 200 ns
  regimes and frequencies). The settings card therefore offers measured films only. Needed: plates with a monotone dose ramp at one
  pulse width and frequency, photographed with the chart.
- Settings for a colour: `GET /colors/settings`: thickness candidates in every fitting order, the measured settings that produced films
  within 15 nm (e.g. gold L* 72 b +34 -> 226 nm -> Kalinin C08/C12 40 % 1800 mm/s, Chicago C08 45 % 1600 mm/s, C05 24 % 1500 mm/s),
  reachability (within 8 dE of the spiral), the kinetics note.
- Colour map: planes a*b*, a*L*, b*L*; lightness band; the film spiral with thickness marks under the points; film reading of a picked
  point; film card under the search results.
- Tests: `tests/test_oxide.py` (8). Full suite running.

# Predicted look of a photo engraving from its picture and settings — plan awaiting approval (2026-10-18)

Operator: "for colour photo engraving the grey level sets the power; I want you to compute how the picture will look for the
parameters we set".

## What exists

- DEC-057: power = Min + (Max - Min) x (1 - grey) for a grayscale-mode image layer; `lightburn.py` reads the picture (PNG), the layer's
  Min/Max, speed, frequency, pulse width, line interval / dpi, passes and the picture adjustments (gamma, contrast, brightness, enhance).
- `ingest._tonal_profile`: for an accepted photo engraving, grey -> power -> measured Lab in 16 bins (pair 22, Inna: 13 bins, grey 0.16..0.91,
  power 6.0..14.4 % at 300 ns, 60 kHz, 128 mm/s, 1503 dpi). Each bin is a colour on the map with the settings of that power.
- 76 flat-fill observations (Scan layers) with full settings; `model.predict_for_lab` works the other way (colour -> settings).
- The screen "Непрерывная фотогравировка / Тональный" builds bands from validated plate colours; it does not take a LightBurn picture.

Prototype (scratchpad `inna_preview_proto.jpg`): the Inna picture rendered through its own measured profile. The mechanics work; the
result is nearly black because that photograph was dark and camera-relative (L* 1.4..7.2). The prediction can only be as good as the
measured evidence: today one dark photo engraving and no plate at these settings.

## Steps

- [ ] 1. `prediction.py` (new): `tone_curve(store, settings, profile)` — for a mode (speed, frequency, pulse width, line interval, passes,
      material, setup) collect every referenced measurement at that mode as (power, Lab, source): tonal-profile bins of accepted photo
      engravings and flat-fill observations; sort by power; the curve is linear in Lab between neighbouring measured powers; outside the
      measured span nothing is predicted (REQ-003). Camera-relative evidence is used only when nothing referenced exists, and is flagged.
- [ ] 2. `prediction.render(picture, settings, curve)` — grey of the stored picture -> LightBurn's adjustments (gamma, contrast, brightness:
      standard formulas, marked "assumed"; enhance / denoise not modelled) -> power (DEC-057) -> Lab from the curve -> sRGB. Returns the
      image, a coverage mask (predicted / outside the measured span / no evidence), the share of pixels outside, the curve used with the
      provenance of every point, and whether the colours are referenced or camera-relative. Dithered modes (Stucki, Jarvis, threshold) are
      refused with a reason; only grayscale mode is predicted.
- [ ] 3. API: `POST /predictions/photo` takes a LightBurn file (the picture and the settings are inside) and optional overrides
      (min_power, max_power, speed, frequency, pulse width, line interval) -> JSON (curve, coverage, flags) + `/predictions/photo/{id}.png`
      (preview, side by side with the picture, hatched where not predicted). Nothing is stored except a short-lived cache of the upload.
- [ ] 4. UI: screen "Предпросмотр фотогравировки": upload the LightBurn file, per image layer the picture next to the predicted look; sliders
      for Min/Max power that re-render; the curve table (grey -> power -> colour, source of each point); a plain statement of what the
      prediction rests on (which plates / pairs, referenced or camera-relative) and what it does not know (powers outside the span).
      A link from an accepted photo engraving's experiment page ("как будет выглядеть при других Min/Max").
- [ ] 5. Tests: curve from synthetic observations (interpolation, span limits, flags), render of a synthetic picture, refusal of dithered
      modes, API round trip, i18n coverage.
- [ ] 6. Real check: the Inna file through the screen; the prediction against its own photograph (self-consistency) and the picture's
      5.5 % of pixels outside the span reported.
- [ ] 7. MarkView: REQ "predicted look of a photo engraving" (draft, waiting for approval), decision on the evidence rule.

## Decisions needed from the operator

1. Evidence: is a prediction from camera-relative photographs (no ColorChecker, as all pairs so far) acceptable when flagged, or should the
   screen refuse until a referenced measurement at that mode exists?
2. Picture adjustments: predict with standard gamma / contrast / brightness formulas and say "assumed", or refuse files whose picture
   adjustments are not at LightBurn's defaults?
3. Scope of v1: grayscale mode only (dithered modes refused), LightBurn file as the only input (no bare picture + typed settings).

# Automatic alignment refused on the operator's new pairs (2026-10-18) — approved: rewrite the start without the frame (operator, 2026-10-18: "перепиши все")

Operator: "match does not work" (CowBoy, lion, limitless). Reproduced on the real files, outside the application.

## What fails and why (measured)

| pair | automatic result | cause |
|---|---|---|
| CowBoy (pair 24, deleted) | "no frame window was found" → manual corners | black parts of the work touch the frame at the top and right; `find_window` requires half of the scan lines of a side to end on one line (top 25/60, right 23/54) |
| limitless (pair 25) | "no frame window was found" | window is found at 1100 px but refused at the working scale (2194 px): the line tolerance is 3 px regardless of the scale, and glossy black frame edges end the dark run early on 10–25 % of the lines |
| lion (pair 23, **accepted**) | anchoring refused "orientation ambiguous" (0.056 vs 0.058 mm); the old geometry fallback accepted 3 shapes with residual 0 and a mirror | the drawing is dense (30 % of the window pixels are edges), so the trimmed-50 % cost is ≈ 0 for every orientation; the plain capped mean separates the true orientation 3× (0.067 vs 0.186 mm). **The fallback overlay is wrong (checked visually): the 19 observations of pair 23 were measured off the drawing.** |

Prototype (scratchpad, no repository change): with a dominant-line rule in `find_window` (tolerance 0.3 % of the long side, at least 25 % of the lines, outermost of near-equal lines) and the plain capped mean as orientation cost:
CowBoy → element anchors, 31 anchors, residual 0.06 / 0.12 mm (median / p90), spread 0.54, orientation margin 0.62, 5 s;
unbreakable (pilot) still → 64 anchors, 0.07 / 0.12 mm, margin 0.39.
lion and limitless need the final line rule (a hard "no points outside the line" filter rejected their glossy frames); to be verified in step 1.

A start without any frame (whole drawing searched over 8 orientations × scale × shift on the current coarse grid) fails on all four pairs: the grid is built for a start near the truth. A frame-less start needs a coarse-to-fine (pyramid) search — a separate step, see 5.

## Steps (approved)

The start of the registration no longer needs a frame. The whole drawing is searched in the photograph; the frame window is derived
afterwards from the known plate size and the lightness step at its edge, and is used only to say what is hidden.

- [x] 1. `anchoring.prepare`: edge map with the gradient direction of every edge pixel (4 direction bins, each bin also accepts the two
      neighbouring directions), so that a dense drawing of parallel strokes cannot match itself turned by 90 degrees.
- [x] 2. `anchoring.global_search`: at a coarse resolution (long side 480 px) the drawing's outline samples, with their tangent
      directions, are rendered as a 4-channel template for every pose (mirror x 4 right angles x small rotation offsets x plate
      scale 0.3..1.1 of the photograph) and correlated with the proximity map (FFT); best shift per pose; the best pose per
      orientation is kept. Score = mean proximity over all outline points, so a cropped photograph lowers every orientation alike.
- [x] 3. Every orientation's best pose is polished at 1100 px by coordinate descent on the plain capped mean distance (no trimmed
      share); ranking by the polished cost; the two best go to the element matching at the working scale (10 px/mm) exactly as
      before (`_refine`, RANSAC fit, anchors-of-the-second-orientation gate, inlier / residual / spread gates).
- [x] 4. `anchoring.window_from_frame`: with the final transform, each side of the plate rectangle is scanned for the inner edge of
      a dark frame within 3 % outside .. 12 % inside; the dominant line per side (>= 25 % of the lines, tolerance 0.1 mm,
      outermost of near-equal lines); a side without a frame edge is the plate edge itself. No frame = nothing hidden.
- [x] 5. `ingest._align`: the geometry fallback result must be supported by the photograph's edges (`anchoring.outline_support`)
      or it is not used; a wrong three-shape fit (lion) yields "place the four corners" instead of a mirrored overlay.
- [x] 6. Tests: synthetic work without a frame is registered and nothing is hidden; a black silhouette touching the frame; a
      drawing of parallel strokes; the geometry guard; i18n coverage; existing suites green.
- [x] 7. Real pairs through `anchoring.register` and through the application: unbreakable, lion, CowBoy, limitless, Inna (picture
      route untouched); numbers recorded below.
- [x] 8. MarkView: decision "the frame is derived from the plate, not required" (supersedes the frame-window part of DEC-049);
      pair 23 (lion): re-check and, with the operator's consent, delete its 19 observations.

## Results (2026-10-18, real pairs through `anchoring.register` and through `check_pair` on a temporary store)

| pair | method | anchors | residual median / p90 mm | orientation margin (cost best/second) | frame hidden per corner mm | time of the check |
|---|---|---|---|---|---|---|
| unbreakable (pilot) | element anchors | 72 | 0.066 / 0.131 | 0.77, second orientation 6 anchors vs 72 | 3.3 · 0.4 · -1.4 · 1.4 | 20 s |
| lion | element anchors | 26 | 0.077 / 0.158 | 0.56, second 0 anchors | 2.7 · 2.8 · 2.0 · 1.7 (bottom side = plate edge) | 18 s |
| CowBoy | element anchors | 27 | 0.072 / 0.136 | 0.78, second 0 anchors | 3.8 · 4.3 · 3.7 · 0.6 | 17 s |
| limitless | element anchors | 41 | 0.123 / 0.176 | 0.52, second 17 anchors vs 41 | 3.9 · 7.2 · 0.6 · 1.1 | 34 s |
| Inna (picture route) | picture | — | — | untouched | 3.8 / 5.3 mm left / right | 9 s |

`anchoring.register` alone: 8–9 s per pair (global search 240 px, 8 direction bins; the polishing pyramid; element anchors at 10 px/mm).
A negative hidden margin means the frame edge lies outside the file's rectangle (the physical plate is larger than the C00 rectangle).

Lion, corrected: the whole-shape fit of pair 23 was not mirrored but off by 0.4 mm (median) and up to 2 mm at the edges against the
anchored result; `anchoring.confirm` from that fit converges to 23 anchors, residual 0.063 mm. Two anchored results of the lion (from the
global search and from the whole-shape start) differ by 0.43 mm median, 0.78 mm max: that is the real accuracy on a drawing of dense
parallel strokes, wider than the anchor residual says. The plate-corner uncertainty reported to the operator (0.24–0.37 mm) is of that order.

Synthetic: a work without a frame is registered and hides nothing; a black silhouette on two plate edges leaves the frame edges where
they are (hidden 1.5–3.6 mm on every side, accuracy < 0.4 mm); a drawing of parallel strokes is registered mirrored as photographed;
a start from another route is confirmed when right and refused when mirrored.

The application server was restarted on the new code on 2026-10-18 (port 8765, log in ~/.titanium-platform/server.log). Full suite: 530 passed.

## Re-measurement of every chart pair and the first thin-film result (2026-10-18)

- Operator: re-check every experiment; works without a chart will be re-photographed with it. Done through the running application for
  every accepted chart pair (alignment revision -> fresh automatic check -> masks reviewed -> accepted; the superseded pair is retired by
  `accept_pair`): Motorcycle 1, Van Gogh (CowBoy), Sergey Kalinin, ChicagoGirlShow, Soccer Players, Girl on a bike -> pairs 46–51, chart
  residual 3.6–4.2 dE, grey ramp within 1–3 L*, 44 observations. Still camera-relative, waiting for a photograph with the chart:
  unbreakable (IMG_3281), Inna (IMG_3283), lion (IMG_Lion), limitless (IMG_Limitless).
- Thin-film prototype (`scratchpad/thinfilm.py`): air / TiO2 film (Cauchy n ~2.3–2.5) / titanium (n,k from the literature), Fresnel at the
  given angle, D65, CIE 1931 2 deg -> Lab; free parameters: index scale, film absorption, gloss (overall reflectance factor), angle. Fit of
  the 43 calibrated observations: best gloss 0.7, angle 30 deg, median 8.9 dE, 30 % within 8 dE. The coloured regimes (gold 19–130 nm, blue
  58–88 nm, purple ~280 nm) sit on the curve within 3–9 dE; the dark neutral "black" regimes (L* 35–38, chroma < 4) are 21–23 dE off: a
  pure interference film cannot be dark and neutral, that is an absorbing, rough oxide, a second mechanism. Thicknesses above ~200 nm are
  ambiguous (the curve loops). Next: proper n,k tables, a two-mechanism model (interference + absorbing fraction), fixed capture angle on
  the stand, and plates with a monotone dose ramp to order the points along the spiral.

## "Again no black" (2026-10-18): the black is C01 at L* 34–38; the witness of a fully engraved plate was a fallback artefact

- On the ChicagoGirlShow photograph the darkest pixels of the plate are L* 32–35 (99 % of them in layer C01); the chart's black patch in the
  same frame is L* 22 (3.6 % reflectance), its dark grey patch L* 36.5 (9.3 %). The engraved "black" reflects 8–9 %: it is the chart's dark
  grey, not its black. The table is right; there is nothing darker on the plate.
- Defect found on the way: the first layer C00 (68 %, 1000 mm/s, the whole plate) is engraved over entirely, so its clean-witness mask was
  empty; the measurement then fell into the narrow-stroke fallback and reported L* 50 over 8.9 M pixels as "clean titanium". Operator's
  rule (2026-10-18): clean titanium shows only where no fill covers it, and every layer counts. Now: an entirely covered witness is not
  measured and says so; the witness is sampled wherever no later layer engraved, with a 1 mm guard around every later outline and the
  plate edge instead of shrinking the plate rectangle by 20 % of its side (which had hidden the clean ring at the edge); a first layer
  that measures dark or coloured (L* < 50 or chroma > 15) is a background fill, measured as a colour, and the photograph has no clean
  reference. Soccer: clean titanium between the players L* 80.4 over 4.5 M px; Sergey Kalinin: first layer covered entirely.

## "Why no black" (2026-10-18): colour measured from a 16-bit linear decode (DEC-059, proposed)

- The black layer of ChicagoGirlShow (C01) measured L* 28: its mask is clean (5th percentile 23, ruler 1 % of pixels), the darkest point of
  the plate is L* 22. The black oxide is a dark grey of about 5 % reflectance, like the chart's black patch (3 %, L* 21.7).
- But the chart correction distorted the dark tones: grey ramp after the matrix 99.9 · 82.4 · 65.1 · 46.5 · 28.3 · 13.4 against the reference
  95.8 · 80.6 · 65.9 · 51.2 · 36.1 · 21.7. Cause: the RAW developed to 8 bits with a tone curve was read as sRGB; the darks were up to 3x too dark.
- Change: `photo.decode_linear` (16-bit, gamma 1, camera WB), chart patches read from the linear image (`chart_patches_linear`), matrix fitted
  in linear light (`fit_correction_linear`), corrected and camera-relative colours and the clean-titanium ratio from the linear image; the
  check reports the grey ramp (`chart.grey_ramp`), the review screen shows it. The 8-bit decode stays for detection, alignment, previews.
- Six chart pairs re-checked on a temporary store: residual 6.0–6.5 -> 3.6–4.2 dE; grey ramp within 1–3 L*; black layers L* 25–28 -> 35–38,
  mid tones +4–8, light tones +2–5, chroma almost unchanged. Pairs 30–37 (and all camera-relative ones) carry the old bias: re-measure as new
  pairs. Tests: photo, ingest, framed, picturing green.

## Motorcycle 1 (IMG_3294, photo engraving with the chart): the picture route starts from the global search too

- Cause: the picture route's start was a small grid of sizes (0.8–1.1 of the short side) and positions (±12 %) built for close-ups; a plate
  photographed with a chart and a ruler beside it is smaller in the frame and off-centre, so no start was near and the ECC refinement
  ended at a correlation of 0.13 (0.25 required). Widening the grid alone broke the Inna close-up: the 128-px edge correlation does not
  rank starts reliably across scales.
- Rule: the picture's edges (Canny on the stored grey, with their tangent directions) are searched exactly as the vector outlines are
  (`anchoring.global_search`, scale 0.3–1.5 of the photograph, every shift, mirror and right angles); the best pose of each of the four
  best orientations is refined with ECC and the refined correlation decides. Motorcycle 0.55 (second 0.12), girl on a bike 0.53,
  Inna 0.33 with the same hidden margins as before. Picture route ~10–12 s.
- Open: a light grey frame (motorcycle) gives no step of lightness at its inner edge, so the window is not found and 6 % (9 mm) per side is
  assumed hidden; the measured surface loses that band. The frame edge of a light frame needs a texture or edge criterion, not a step.

## Photographs with a ColorChecker and a ruler (2026-10-18): IMG_3293..3297, checked outside the application

- Chart found on all five (OpenCV mcc, 24 patches, 0.3 s each), correction residual 6.1–6.5 dE (limit 12); white patch as shot 98–133 of 255,
  so the shots are ~1.3 stops under at the chart, acceptable. The ruler is not used by anything and does not interfere.
- Full check on a temporary store: Soccer (IMG_3293, unframed plate on the textured background) → chart-corrected, element anchors, 32
  anchors, residual 0.057 / 0.134 mm, clean titanium L* 78.8, gold half-shirt L* 68 b +38; CowBoy (IMG_3295) → 51 anchors, 0.093 / 0.142 mm,
  gold L* 69 b +54. IMG_3294 (motorcycle), 3296 (girl on a motorcycle), 3297 (man's portrait) are new works without a pair yet.
- Two refinements the bright Soccer photograph forced: (1) every orientation whose polished cost comes within the 0.9 margin of the best
  goes on to the anchor stage (at least two, at most three) instead of a refusal there; (2) when the mirror twin keeps half the anchors
  and the outline support is within 0.05, the elements that only one orientation explains (>= 70 % of their outline vs < 50 %) decide:
  the best needs at least 3 and three times the twin's. Soccer bright: 9 vs 1; dark: 20 vs 0; the other pairs 154–378 vs 0. A drawing
  that anchors nowhere while every orientation looks alike is refused as ambiguous (nested squares).

## "Light colours are not found" (2026-10-18): camera-relative colours against the clean titanium of the same photograph

- Cause: a photograph without a chart is measured as the camera exposed it (RAW decoded with no brightness change). The operator's
  photographs are 2.5–5 stops under nominal (sensor median 1–3 % of white; Soccer: clean titanium at L* 9.4), so every colour came out
  nearly black and the light ones could not be told.
- Rule (DEC-056 carried from the colour map into the check): where the work's cleaning layer shows clean titanium in the same photograph,
  every measured colour is also given as it would look next to nominal clean titanium: the ratio to the clean surface per channel in
  linear light, which does not depend on the exposure. Derived on every read (`ingest.express_against_clean`), never stored; the
  camera-relative value stays as the evidence. Experiment, analysis and layer dialogs show the derived colour first, "как снято" beside.
- Soccer (pair 29): gold half-shirt C08 as shot L* 6.7 b 6.7 → L* 58.5 b 28.7; blue C10 L* 5.1 b -7.0 → L* 53.1 b -31.8; exposure
  5.2 stops under. Nominal clean titanium is the default L* 68 until a photograph with a chart measures it.
- Not covered: works without a cleaning layer (Inna's photo engraving) stay as shot; the photographs should be exposed for the metal.

## Soccer Players (2026-10-18, after the rewrite): two rules added

- Four identical shirts: the mirrored orientation also collects anchors (29 against 22), so the anchor count cannot decide. Rule: when the
  second orientation keeps >= 50 % of the anchors, the orientations are compared by the share of the *whole* outline the photograph
  confirms (edges of the right direction within 0.15 mm); the best must lead by 0.05 or the work is refused. Soccer: 0.857 vs 0.721, checked
  on the stripes of the second player's shorts at full resolution. Lion 0.91 vs 0.24, unbreakable 0.73 vs 0.24, CowBoy 0.78 vs 0, limitless
  0.78 vs 0.12.
- The strictest refinement pass kept 8 anchors of 162 elements (the engraved edges are doubled by a dark rim, which fails the
  distinctiveness test at a 0.4 mm radius) while the first passes had 38–57. Rule: after the passes, every element with a close,
  distinctive match within 0.5 mm of its prediction under the final transform is an anchor. Soccer: 22 anchors, residual 0.042 / 0.119 mm,
  spread 0.42. The other pairs gained anchors (unbreakable 106, lion 34, CowBoy 51, limitless 83) at residuals 0.09–0.10 / 0.15–0.18 mm.
- Soccer's plate is engraved dark to its edge, so no frame edge is found: nothing is reported hidden, which is right for that photograph.

# Element-anchored registration of unmarked works (framed artwork)

Branch: `feat/laser-device-profiles`. Goal (user, 2026-10-16): the photograph of a finished work is aligned to its
LightBurn file by finding a few reliable elements, trusting them, and computing every other element from the file
distances. Parts hidden under a frame are inferred, never measured.

Pilot pair: `unbreakable.lbrn2` (19 layers, 235 closed vectors) + `IMG_3281.DNG` (framed, no reference chart).
Prototype with measured results: session scratchpad `proto/` (coarse 8-orientation search, per-element anchors,
robust homography, hold-out test).

## Scope

- [x] 0. Record the decisions in MarkView first (DEC element anchors, DEC frame window, REQ registration, REQ exact geometry).
- [x] 1. `lightburn.py`: exact vector geometry (Bezier edges, sub-paths, holes, closed flag per loop).
- [x] 2. `photo.layer_mask`: honour holes of a shape.
- [x] 3. New module `anchoring.py`: edge map, frame window, orientation search, element anchors, robust fit, classification, uncertainty.
- [x] 4. `ingest._align`: use anchoring before `register_geometry` for unmarked works; manual four corners stay the fallback (REQ-013).
- [x] 5. Measurement: the frame window limits the visible surface; partly hidden elements are measured on their visible part only.
- [x] 6. Overlay + review report: statuses (anchor / confirmed / computed / hidden), hidden margins, orientation margin.
- [x] 7. UI strings (ru/en), `test_i18n_coverage` stays green.
- [x] 8. Tests: geometry, mask holes, synthetic framed work (perspective + frame), ingest end to end, fallbacks.
- [x] 9. Run the real pilot pair through the real code path and compare with the prototype numbers.
- [x] 10. Full test suite; review section below.

## Rules kept

- Measured beats computed; a hidden element is never measured, only reported as inferred.
- No silent guessing (REQ-003): too few anchors or an ambiguous orientation raises `PhotoError`, the operator places four corners.
- Reference chart is still mandatory (REQ-009); alignment does not change that gate.
- Do not touch unrelated uncommitted work in the tree; no commit unless asked.

## Added after the goal hook (REQ-025, DEC-050, DEC-051)

- [x] 11. Complete capture: nested `SubLayer` settings, `Group` transforms (child XForm first, then the groups above), unsupported shapes counted per layer and noted, image object settings in the layer's settings.
- [x] 12. A layer is not sampled where a later layer engraves over it (burn order = priority, then index).
- [x] 13. Run order (`priority`) is not stored in the recipe of new observations; keys of existing data unchanged (tested against the previous algorithm).
- [x] 14. Whole path of a framed pair checked, reviewed and accepted into observations (synthetic pair with chart).

## Decisions of the operator (2026-10-16) and what was done

- Commit: one commit with the whole tree, no push.
- MarkView: DEC-048..051 accepted, REQ-023..025 approved.
- Old measurement history: removed on request (244 observations, 19 pairs with their stored file copies, 18 capability findings). A verified
  copy of the database and of the files is in `~/.titanium-platform/backup-20261016-142236-before-reset-of-observations`; to restore, stop the
  application and copy `titanium.sqlite` and `files/` back. Device, passport documents, lens, profile, titanium stock, plans, plates and
  research notes were kept. The change is recorded in the audit log.

## Checked against the operator's own files (170 LightBurn files in `Dropbox/Sirius Art`, read only)

- All 170 parse without errors in 26 s. They contain 2370 groups nested up to 7 deep, 86 image layers (grayscale, 3dslice, stucki, jarvis,
  sketch, threshold), 99 image objects, 95 texts (all carry a converted outline) and 45 ellipses; nothing is left unread.
- Group transforms: LightBurn's own thumbnail in the file matches the new reading (circle, letter D and plants of DACUSAN-1; both cards of
  the vCard), while ignoring group transforms shrinks or scatters the drawing.
- `BackupPath` carries the same XForm as its text object (found on real data; the first guess applied it twice and was fixed).
- Image layers: mode, kind (tonal / depth), dpi, dot width and correction, cleanup pass, passes, sub-layer, picture processing; the picture
  is PNG in `Data`, shared by the objects of one file (DEC-052, REQ-026). The tonal profile is validated on synthetic photographs only.

## Pilot pair accepted by the operator (2026-10-16)

Pair 21 (`unbreakable.lbrn2` + `IMG_3281.DNG`, profile JPT MOPA M7 60W) was created in the running application, reviewed and accepted by the
operator: 19 observations, alignment `element anchors`, camera-relative (none model-eligible), run order not in the recipe.

## Photo engraving checked on the operator's own pair (2026-10-16): `Inna - 2.lbrn2` + `IMG_3283.DNG`

- One grayscale image layer: power 5..16.1 %, 300 ns, 60 kHz, 128 mm/s, 1503 dpi. The grey level of the picture sets the power and the power sets
  the oxide colour (the operator's method, confirmed by LightBurn's documentation: Min power for the lightest, Max for the darkest).
- `picturing.py`: the picture's silhouettes (edge maps of the three Lab channels) are matched to the photograph over 8 orientations, refined by
  ECC. Orientation: vertical mirror, margin 2.1 times; hidden by the frame 2.9 / 7.3 / 3.8 / 3.2 mm (left, right, top, bottom); 5.7 s for the check.
- Tonal profile on the real photograph: smooth and monotone, near black and neutral at about 14 % power, brown and most coloured at about 7 %
  (rank correlation with grey: L* 0.64..0.80, a* -0.64, b* 0.50..0.72). DEC-052, DEC-054, REQ-026 and REQ-027 accepted on this evidence.
- The frame of that photograph is brushed metal; the old dark-frame detector does not find it, the step at the inner edge does.

## Answers of the operator (2026-10-16) and what is still open

- **Grey to power: settled (Q-024 answered, DEC-057).** Power = Min + (Max - Min) x (1 - grey) with the layer's own Min and Max; checked against the portrait
  (Min 5, Max 16.1, grayscale). The unverified-sRGB caveat is gone; no wedge plate.
- **Portrait steps: shown on the map by default** (pale, dotted outline, "без привязки к чистому титану"); a checkbox hides them; they stay out of the search until
  "Искать и среди них" (their distances to referenced colours mean nothing).
- **Photographs of plates: the operator sends them one by one** after engraving; nothing to do until then (11 plates show "plate ready").
- **ColorChecker: the operator is thinking about where to get one.** Until a photograph with a chart exists every colour is camera-relative (dashed outline).
- Brightness, contrast and gamma of LightBurn are recorded and listed in the profile, not modelled (they do not reorder grey levels); the dithering of other modes
  is not modelled.

## Experiments as single objects and one general colour map (operator, 2026-10-16): done

Operator decisions: camera-relative colours are expressed against the clean titanium of their own photograph; all laser and lens versions on one map
with a filter; the working-task panel stays, compact, on top. The photograph with its overlay is always shown in an experiment.

- [x] A1-A2. `experiments.py`, `GET /experiments` and `/experiments/{key}`: derived from plates and checks (DEC-055, REQ-028), no schema change.
- [x] A3-A4. One list screen (thumbnail, state, laser, lens, titanium, search, state filter, conclusions beside it); one experiment screen with the
  photograph and its overlay first, then the checks, the measured layers, the plate, the file and the conclusions.
- [x] A5. Old routes keep working and link back; new plates open as experiments.
- [x] B1-B2. `colormap.py`, `GET /colors` and `/colors/search` (DEC-056, REQ-029).
- [x] B3. One map screen: filters, a*b* plane, a palette or Lab input, nearest recipes with settings and where they came from; the model page stays
  reachable (`/colors?profile=`).
- [x] B4. Cleaning layer of a finished work recognised (also for works accepted earlier, from the stored file); linear-light ratio to the clean surface.
- [x] A6/B5. Tests (524 pass); checked in the running application on the operator's pairs.

## Review

### Result (2026-10-16)

- DEC-048, DEC-049, REQ-023, REQ-024 recorded in MarkView (statuses left to the operator).
- `lightburn.py`: exact outlines. Pilot file: 233 of 239 sub-paths closed (the old reader saw 43 of 235 paths); layer areas agree with
  an independent reader to 0.1 %.
- `anchoring.py` (new): window of the frame, 8 orientations with trimmed chamfer cost, pose polishing, per-element anchors, robust
  homography, statuses, bootstrap and a ring hold-out estimate. Pilot pair: 71 anchors, 120 confirmed, 29 partly hidden, median
  outline residual 0.09 mm, orientation margin 0.58 and 0 anchors for the second orientation; 15 s for the whole pair check.
- `ingest.py`: new route before `register_geometry`; frame window limits the measured surface; overlay draws the hidden part in
  magenta; per-layer notes; `_line_metrics` farthest pair via convex hull (was O(N^2): 66 s -> 14 s on the pilot pair).
- UI: method pill, anchor statistics, hidden margins marked approximate, refusal reason; Russian translations added.
- Tests: 486 pass (44 new: geometry, mask holes, anchoring on synthetic framed work, whole pair check and acceptance, farthest pair,
  sub-layers, groups, unsupported shapes, run order, overlap exclusion, key stability).

### Limits to remember

- Only one real pair was available. The reference chart is still missing from `IMG_3281.DNG`, so no observation can be created from it.
- Hidden margins of the plate vary by about 1 mm between runs of different settings; the UI says so. Visible elements are
  registered to about 0.1 mm (median); on synthetic works the worst grid point was 0.14-0.74 mm.
- The frame window is found only for a dark frame with a clear histogram valley; otherwise the old routes and the manual four corners remain.
- Heavily overlapping outlines (painted over) may be refused ("orientation ambiguous"); refusal is the safe outcome.
- See "Still open, and why" above.

## Stream S3: one experiment list, provisional colours, honest search, predicted photo engraving (I-15 part, I-16; 2026-10-18)

- [x] REQ-028: cancelled, superseded and deleted plates (also `plate.status = 'Deleted'` when that column exists) are not experiments;
  the laser page shows the one experiment list filtered by that laser; a finished work offers its LightBurn file on its experiment.
- [x] REQ-020 AC7 / DEC-045: checked, aligned, measured pairs awaiting acceptance are on the colour map as provisional, linked to their
  review; out of the search unless asked for, out of every prediction.
- [x] REQ-029 / DEC-021: one search entry per recipe = settings + laser id + lens id + titanium stock id + kind of measurement
  (chart / against clean titanium / as photographed) + provisional; it counts independent engravings and photographs apart.
- [x] REQ-030: `prediction_store.py` (curve of a mode from tonal profiles and flat fills), `api/routes_prediction.py` (upload, re-render
  at other Min/Max from an in-memory cache, no database), screen "Предпросмотр фотогравировки".

Real check on the accepted Inna pair (pair 22, scratch copy of the live database migrated by the new Store, file copied read-only):
its own LightBurn file through `POST /api/predictions/photo` gives a camera-relative curve "as photographed" (no clean titanium in that
photograph) of 13 points, 6.04..14.37 % power, all from pair 22; 5.49 % of the 1024 x 1024 picture needs a power outside that span
(the 800 px preview alone would say 3.88 %, so the share is counted on the whole picture). The predicted picture binned by grey as the
tonal profile bins the photograph gives back every measured bin within dE 0.01..0.17 (worst at grey 0.906, the lightest bin, whose
lighter half is outside the span). At Min 4 / Max 18 the share outside rises to 32.4 %.

