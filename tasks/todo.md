# Vector work: photograph -> gapless colour regions -> titanium colours -> LightBurn (operator, 2026-10-19)

Requirements REQ-033 (split), REQ-034 (colouring, recolouring, file), REQ-035 (engraving time); decisions DEC-073 (all measured
colours, up to 29 with cleaning first), DEC-074 (recolouring modes, YuNet faces + manual areas), DEC-075 (time, filter, fastest
within tolerance), DEC-076 (proposed: superpixels + planar map of shared borders). Branch feat/vector-work-colours from origin/main.

- [x] V1 Segmentation core (worktree): smoothing + SLIC superpixels finer in important areas, Lab clustering to N <= 29,
      small-region merge, planar map of shared arcs smoothed once, holes, Path export from arcs; YuNet model shipped as
      package data with its licence; manual important areas; determinism; gapless test by rasterising (< 0.5 % gap/overlap).
- [x] V2 Time and colouring (worktree): time per cm2 / per cm from settings (DEC-075); colour map shows time and filters;
      search orders equal colours by time; palette = every measured colour of laser+lens+titanium; assignment modes
      nearest / tonality / random (seeded, restorable) / fewer layers; fastest within tolerance; per-group and per-region change.
- [x] V3 Vector work flow (main tree, after V1+V2): steps split -> preview -> colour -> preview -> file; important-area
      marking on the picture; variants kept; export cleaning first, <= 29 recipe layers, Paths from shared borders; job time.
- [x] V4 Tests green, real photograph through the flow (gaps measured on the export), PR, CI, merge, 0.5.0, deploy, walkthrough.
      1051 passed; CI green; v0.5.0 (#23) deployed after a backup; walkthrough on the Inna picture (work 21): face, eyes, lips
      found, 12 colours = 500 regions, export cleaning + 9 layers, 0 % gaps/overlaps, 3 h 54 min estimated. The walkthrough
      found the area overlay hiding the picture (chart style of svg[role=img]): fixed in v0.5.1 (#24), deployed, verified.

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
- [x] WP-14 Version 0.4.0, PR, CI, merge, tag, deploy (DEC-024), browser walkthrough, manual checklist.

## Review (2026-10-19)

- PR #20 merged (5c5208f), CI green on Linux 3.11/3.12 and macOS 3.12; tag v0.4.0; issues #13-#19 closed by the merge.
- Tests: 909 passed, 0 skipped. QR identifier read for 1000 of 1000 synthetic codes (classic detector alone: 991).
- Deploy (DEC-024): backup titanium-before-deploy-0.4.0-20261019T001137Z.sqlite, wheel from the tag installed in
  ~/.titanium-platform-app, port 8765 answers 0.4.0; the migration made titanium-before-0.4.0-20261019T001151Z.sqlite.
  Live data after the migration: 662 observations byte-identical to the backup, 16 experiments accepted, every photo
  and overlay served, 565 colour-map points, all 39 pairs on laser 1 with lens 2.
- Walkthrough in the operator's tab: a tab opened before the upgrade showed the old page ("Не найдено") until reloaded.
- Open for the operator: proposed DEC-067..DEC-072; LightBurn opening of exported files; tablet access; a .lbrn sample.

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


## Vector work colour editor and slow screens (operator, 2026-10-19)

Plan approved 2026-10-19 (`~/.claude/plans/scalable-bubbling-dove.md`). Feature `vector-work-colour-editor` (REQ-043..REQ-049,
DEC-001, DEC-075..DEC-077, issue #28); bug BUG-001 (issue #27). The platform feature was closed before (DEC-079, #26).

- [x] BUG-001 (0.5.2, PR #29, deployed; on 8765: knowledge 6.8 s → 0.12 s, 16 list thumbnails 0.36 s, experiment picture 4 ms): knowledge list once per list (6.8 s on 343 entries); on-disk render cache for photographs and overlays (0.6-3.3 s
  per picture, RAW decoded on every request); 480 px list thumbnails; ETag/304; `warm-cache` command. Release 0.5.2.
- [x] REQ-043 / DEC-001: every source colour coloured from the start, outside-tolerance flagged, never blocking.
- [x] REQ-044: editor with a large picture, zoom/pan, brush / pipette / select, palette, layers, source colours, totals.
- [x] REQ-045: paint scopes area / source colour / fill of similar neighbours, hover preview equal to the result.
- [x] REQ-046..REQ-048: merge titanium colours, source colours, neighbouring areas into one contour (gapless).
- [x] REQ-049: undo / redo over colouring and document versions.
- [x] Full-copy check (work 22: 28 colours coloured, export allowed; 17/17 experiments, 565/565 map points), release 0.6.0
  (PR #30, tag v0.6.0), backup `titanium-before-0.6.0-20261019-085107.sqlite`, deploy (662 observations), view-only walkthrough of
  work 22 in a MarkView tab (demo work 21 no longer exists): 986 areas, no accept button, export enabled, hover of a source colour
  outlines its 49 areas with the tooltip; nothing sent (undo count unchanged), no console errors.

Integration review (2026-10-19). Backend (`segment.neighbours`, `merge_colours`, `merge_regions`; `vector_job` paint scopes, merges,
undo/redo with versions; `GET /reach`) and UI (`vector-editor.js`) merged on `feat/vector-colour-editor`; `set_region` dropped
in favour of `paint` with the area scope. Full suite 1096 passed. Real data (copy of work 22, 986 regions): 30 chained region
merges + 3 colour merges, coverage 0.0/0.0 after every step, LightBurn round trip 902/902 shapes and 55/55 holes; 38 undos back to
version 1, 38 redos identical. Walkthrough in headless Chrome on a full copy (port 8794, never the operator's browser): 28/28
colours coloured, export enabled, no accept button; hover outlines 1 area / 10 areas of a colour / 63 areas of a fill equal to
`/reach`; paint, Ctrl+Z / Ctrl+Shift+Z, Alt+click pipette, Shift+click selection, merge 986 → 985 areas, layers 9 → 8, colours
28 → 27, wheel zoom, drag pan without painting, original view; 6 undos back to the start; at 820 px the panel goes below the
picture, no page scroll; no console errors.

## BUG-001 slow screens (issue #27, branch fix/BUG-001-slow-screens; 2026-10-19)

- [x] Knowledge list O(N): `knowledge.get()` takes the setup's summaries and the entry's events; `list_for_setup` reads them once.
  Test: the list equals `get()` of each entry; `model.knowledge_summaries` runs once per list.
- [x] `render_cache.py`: `<data dir>/cache/renders/<pair id>/<sha256>.png`, atomic write, damaged or missing file redrawn, LRU limit
  500 MB, removed with the pair. Key = canonical JSON of photo and LightBurn file stamps (path, size, mtime_ns), the stored check, the
  plan's JSON digest, the chart reference (corrected only), `allow_non_raw_photos`, every view parameter and `RENDER_VERSION = 1`.
- [x] `size` (64..5000, longest side) on `photo.png` and `overlay.png`; the experiment list asks `size=480`.
- [x] ETag = key, `Cache-Control: private, max-age=0, must-revalidate`; matching `If-None-Match` -> 304 without drawing.
- [x] `titanium-platform warm-cache --data-dir DIR`: the list thumbnail and the experiment page picture of every check in active use.
- [x] Tests: `tests/test_render_cache.py` (7), `tests/test_knowledge.py` (+1).

### Review (copy of the live data, sqlite backup API + copied files, server on port 8793, GET only)

| Request | 0.5.1 | after |
|---|---|---|
| `GET /api/knowledge?device_id=1&lens_id=2` (343 entries) | 6.53 s | 0.07 s (output byte-identical) |
| experiment list, 16 thumbnails one after another, cold | 11.6 s, 35.9 MB (0.65 s median) | 11.3 s, 4.7 MB (0.62 s median) |
| same, 6 at a time as a browser, cold | ~2.7 s, 35.9 MB | 2.4 s, 4.7 MB |
| same, cached / after `warm-cache` | 11.6 s (no cache) | 0.02 s (1-2 ms each); revalidation 304 in 1 ms |
| experiment page `overlay.png?corrected=true&visibility=lifted` | 3.3-3.4 s every time | 3.3 s once, then 3-4 ms; 304 in 1-2 ms |
| `warm-cache` on the copy | - | 32 pictures (16 checks) in 67 s, 39 MB |

Pictures at the default sizes are byte-identical to 0.5.1. The cache key costs 0.1 ms (photo) and up to 9.6 ms (overlay of the pair with
the largest stored check, 529 kB) per request.

Cold time (cProfile, pair 59): the list thumbnail is 0.55 s, of which the RAW decode is 0.52 s (94 %); `size=480` only removes PNG
encode (33 -> 4 ms) and 87 % of the bytes. A corrected picture is 3.2-3.4 s: 8-bit RAW decode 0.51 s, linear RAW decode 0.52 s, chart
correction 2.0-2.2 s (exposure-normalised render 0.65 s, chart detection 0.18-0.27 s, applying the matrix 0.6 s), PNG encode 0.03 s.
Decode and correction were not changed. So the first opening of a picture stays RAW-bound; `warm-cache` after a deploy (and the cache
itself after the first view) is what makes the screens fast.

Not cached: nothing that is served. The vector overlay is cached too (`transparent=true`); `size` was not added to it.


## Vector work colour editor: verification against the rewritten REQ-049 and the operator's answers (goal 2026-10-19)

Branch `feat/vector-colour-editor-req049`, created from `origin/main` (3aa4e45); local `main` was level with it. Spec read in full:
REQ-043..REQ-049, DEC-001 and DEC-075..DEC-077, plan I-1..I-7, discussion.md; the feature has no questions or findings. I-1..I-7 were built
in 0.6.0 (PR #30, issue #28); REQ-049 was rewritten afterwards with unticked criteria, so this goal audits the code against all of it.

Audit (code read, then the tests that cover each criterion):
- REQ-049 holds in the code: `_here` snapshots colouring, split version, tolerance and filters; `_snapshot` clears redo; `_new_version` numbers
  after every version in the history, redo included; variants carry `version` and `restore` refuses another one with a translated message;
  `resplit` clears undo, redo and variants; `_pin_legacy` reads old undo entries and variants as belonging to the current version.
- Gaps found: (a) no test undoes and redoes a titanium-colour merge, (b) the settings test checks only the settings after redo, not the
  colouring, (c) three places where the wording of a criterion and the code differ. The operator answered (c) on 2026-10-19 (DEC-078..DEC-080).

Plan (I-8, steps in the order they were committed):
- [x] Baseline on the branch before any code change: 1104 passed, 1 failed in 11 min 38 s. The failure, `test_plans.py::test_exported_markers_are_
      detected_and_identifier_decoded_from_the_raster`, is a flake: it passes alone (30 of 30) and fails for about 0.75 % of random experiment
      identifiers (3 of 400; `TCE-AFA45888` every time). Cause: OpenCV's classic `QRCodeDetector` misses those codes; the codes are valid
      (`QRCodeDetectorAruco` reads all of them at 10-30 px/mm) and `photo.read_identifier` falls back to it. The test now uses the product's
      reader, and four missed identifiers are pinned (commit 3367022).
- [x] Spec: DEC-078 (a titanium merge needs two or more selected colours), DEC-079 (painting a source colour includes every area of it again),
      DEC-080 (the merge-areas button only for a connected selection); REQ-045/046/048 criteria refined; plan I-8; discussion.md.
- [x] DEC-078: `_merge_titanium` refuses fewer than two distinct selected colours that the colouring uses; one translated message; tests.
- [x] DEC-079: `_paint` with the scope "source colour" and a colour includes every excluded area of that colour; test; the hover agreed already.
- [x] DEC-080: `GET /api/vector/{id}/neighbours` (segment.neighbours, per split version), the screen disables "Слить в один контур" unless the
      selection is connected and says why; the server still refuses; tests (API, screen in node, fallback when the request fails).
- [x] REQ-049 coverage: undo/redo of a titanium merge in a sequence with the other three kinds; redo after a settings change restores the colouring.
- [x] Criteria of REQ-045/046/048/049 ticked with the test seen (175 passed in the files they touch) and the walkthrough below.
- [x] Walkthrough in a MarkView tab on a full copy of the live data (ports 8794 and 8795, never the operator's 8765): see "Walkthrough".
- [x] Full suite on the finished code: 1114 passed, none skipped (10 min 42 s; 1105 tests of the baseline plus 9 new); wheel 0.6.1 built and
      served by an installed copy (CI's check, run locally); version 0.6.1 (DEC-023, SemVer; pyproject.toml; README note).
- [x] Where the commits go: the operator ruled on 2026-10-19, mid-goal, that commits go straight to `main` with no pull request and no new
      branch until he says otherwise (CLAUDE.md). `main` was fast-forwarded to this branch (7 commits), the local branch deleted, and
      `main` pushed (3aa4e45..dd0aceb). He then said not to wait for CI and to switch it off for now: `gh workflow disable CI` (the run
      of dd0aceb, 39309256823, was still in progress and is left to finish); recorded in CLAUDE.md. Not done, as the goal excludes it:
      build and deploy of 0.6.1 to the operator's app on 8765 (backup of the database, install of the wheel, restart).
- [ ] Issue #28 closed with a comment now that the work is in `main`; a note on #32 that its specification landed and nothing of it is built.

### Walkthrough (2026-10-19; MarkView tabs on a full copy of the live data, branch app on ports 8794 and 8795, the operator's app on 8765 only read)

Copy: `sqlite3 -readonly ... .dump` of `titanium.sqlite` with the absolute file paths rewritten to the copy (0 left pointing at the live
directory), `files/` copied (662 observations as in the live deploy). Work 22 "Imma + Boris": photograph, 28 colours, 986 areas, split
version 2, tolerance 0.05, 10 undo steps.
- Opens with all 28 colours coloured, all beyond the tolerance and flagged "вне допуска" ("Дальше допуска ΔE 0.05: цветов 28, областей 986
  (100.0 % площади). Файл они не блокируют."), no accept button, `export_blocked` null; totals "Слоёв 7 из 29 · время слоёв цвета 3 ч 18 мин ·
  средний ΔE 18.55 · цветов в допуске 0 из 28" (REQ-043, REQ-044).
- DEC-080: `GET /neighbours` answers 200, 42 kB, 26 ms, 986 areas, symmetric. With `r7` selected the merge button is disabled ("...соседние по
  границе"); with `r7` and the distant `r1` it is disabled and says "Слить нельзя: выбранные области не связаны общими границами (касания
  углом недостаточно)"; adding the neighbour `r30` keeps it disabled while `r1` stays; without `r1` it is enabled. A real click merged them:
  version 2 → 3, areas 986 → 985, undo steps 10 → 11, and `/neighbours` for version 3 lists 985 areas without `r30`. The "Отменить" button
  brought version 2 and 986 areas back; Ctrl+Shift+Z redid version 3 (REQ-048, REQ-049).
- REQ-049 numbering (second copy): merge → version 3, merge → version 4, two undos → version 2 with 2 redo steps, a new merge → version 5,
  redo 0 and the redo button disabled.
- DEC-079: source colour № 1 has 21 areas; `r32` and `r50` excluded one by one (grey); with the brush on "Весь исходный цвет" the hover outlined
  all 21 areas; the click left `excluded_regions` empty and painted both with the active colour; one undo brought both exclusions back.
- DEC-078: one ticked layer shows no merge control, two show the target list; the merge took layers 7 → 6 ("Слоёв 6 из 29"); the server
  refused `entries=[A], into=B` and `entries=[A, A]` with 422 "choose two or more titanium colours of the colouring to merge", which the
  screen translates ("Выберите два цвета титана из раскраски или больше, чтобы слить их в один"); the refusals changed nothing.
- No console messages on the scripted tab.

Limits: shift-click and Ctrl+Shift+Z were sent as DOM events with the right flags, because the browser tool's key press sends the literal
key "Control+Shift+Z" with every modifier flag false. During the run someone else operated the first tab (a merge of `r232` and `r165` at
19:04:48, a coarse re-split at 19:05:26, two paints, an automatic recolouring), so the rest ran on a second copy at 8795.


## Splitting algorithms, one section for colours and split, Vector Work third (operator, 2026-10-19; feature vector-detail-and-colour-control)

Asked for twice by the operator ("не вижу ... на третье место, и не вижу, где можно выбрать алгоритмы по разбивке"), then "соедини первое и
второе в одну секцию". REQ-051, DEC-080 (the algorithms), DEC-081 (one section) of that feature; criterion 1 of its overview (menu) ticked.
- [x] Menu: `/vector` third (router.js NAV and ICONS together); test for the new start of the menu and for the unchanged addresses.
- [x] Seam: `segment._slic` was the only place superpixels are made. `ALGORITHMS = ("slic", "seeds")`, `_seeds` beside it (OpenCV SEEDS reads an
      8-bit picture; a crop smaller than two superpixels is one), `segment(..., algorithm=)`, recorded in the document; `vector_job` validates
      it (`the splitting algorithm must be slic or seeds`, translated), keeps it in `split`, writes it into the history, reads a work made
      before as slic; `POST /api/vector` takes `algorithm`, `POST .../split` takes it in the body.
- [x] Screen: the split block (algorithm first, with what each is for, number of colours, detail, smoothing, faces, "Разбить заново", counts;
      the picture for marking important areas folded) is a slot of the colours card "1. Цвета и разбиение"; the file card is "2.". The start
      form has the same select.
- [x] Candidates tried through the real pipeline (job's own settings: 12 colours, medium detail), `scratchpad/algo_eval.py`:

  | picture | algorithm | regions | seconds | mean ΔE | p95 ΔE | gap / overlap |
  |---|---|---|---|---|---|---|
  | portrait (work 22) | SLIC | 323 | 2.42 | 7.35 | 17.4 | 0 / 0 |
  | | SLICO | 344 | 3.19 | 7.48 | 18.2 | 0 / 0 |
  | | MSLIC | 342 | 3.60 | 7.48 | 17.5 | 0 / 0 |
  | | LSC | 280 | 3.21 | 7.64 | 19.5 | 0 / 0 (faces smeared) |
  | | SEEDS | 316 | 1.80 | 7.47 | 17.9 | 0 / 0 |
  | sheet photograph | SLIC / SLICO / MSLIC / LSC / SEEDS | 120 / 105 / 136 / 116 / 104 | 0.93 / 1.17 / 1.40 / 1.17 / 0.77 | 3.93 / 3.96 / 4.01 / 3.76 / 3.79 | 11.4 / 10.3 / 11.8 / 10.2 / 9.8 | 0 / 0 |
  | flat shapes | SLIC / SLICO / MSLIC / LSC / SEEDS | 6 / 6 / 6 / **1** / 6 | | 0.81 / 2.30 / 0.83 / 46.2 / 0.82 | | 0 / 0 |

  Offered: SLIC (default) and SEEDS. Rejected with reasons in DEC-080: LSC (faces smeared, one region on a small picture), SLICO (ragged
  borders on flat shapes, no gain), MSLIC (never better than SLIC). A first reading of thin strokes (absolute darkness threshold, 4 colours)
  said SLIC kept 91 % and SEEDS 48 %; it was an artefact of the threshold. Measured as ink against its own surroundings at 6 colours, over six
  noise and shading settings, SEEDS keeps 87-93 % against SLIC's 83-88 % with a third of the regions: that is what the test and the hint say.
- [x] Real flow, on a copy (port 8796, stopped afterwards): SEEDS chosen in the browser on work 22: split version 5 → 6, 985 → 879 areas, 28
      colours, export unblocked, undo and redo reset, the select and the summary line show SEEDS.
- [x] Full suite on the finished code: 1125 passed, none skipped (10 min 43 s; 1114 before plus 11 new). Release 0.7.0 (SemVer: a new capability):
      wheel built and served by an installed copy (menu order and the merged section in its files), pushed to `main` (9d50df7..7ed6215),
      tag v0.7.0 (v0.6.1 on dd0aceb was tagged earlier).
- [x] Deployed to the operator's app on 8765, as 0.6.1 had been: `titanium-before-0.6.1-20261019T192055Z.sqlite` and
      `titanium-before-0.7.0-20261019T195208Z.sqlite` (integrity ok, 662 observations each), app stopped, wheel installed into
      `~/.titanium-platform-app`, started again detached; GET checks on work 22: `/`, the new scripts, the view (1.6 s on the first request after a
      restart, 0.10 s after), `/neighbours`, `/palette` all 200. Between the two deploys the operator worked in the real app (a medium split
      at 19:27 and a coarse one at 19:30 UTC with faces off, paints, random recolourings): work 22 is now version 4, 335 areas, 12 undo steps,
      and the second backup holds exactly that state.
- [x] View-only look at the real app on 0.7.0 (reloaded tab, nothing sent, server state compared before and after): Vector Work third in the
      menu; "1. Цвета и разбиение" with the algorithm select (SLIC selected, SEEDS), its description, the summary line "Алгоритм SLIC · цветов: 28
      · областей: 335", the folded important areas, then colours, variants and "2. Файл LightBurn".
- Left open on purpose: REQ-050 (AI colouring in a chosen style) is a draft with three questions (Q-005 what the AI receives, Q-006 lightness
  order, Q-007 styles); the rest of vector-detail-and-colour-control (density, eyes, smoothing, Contrast and Artistic, automatic merging of
  same-recipe regions) is not built. CI stays switched off (CLAUDE.md); the run of dd0aceb finished on GitHub on its own.

## 0.8.0 plan: a straight layout, methods that differ, smooth contours, colouring by AI (approved 2026-10-19; steps 1-2 done)
Evidence (portrait of work 22, 28 colours, coarse detail, scratchpad `look*.py` and `look*.png`):
- Layout: toolbar labels at y = 748/723/705/748 (flex-end alignment, hints under some fields only); `h4` margin 20 + stack gap 18.
- Methods: SLIC 290 regions vs SEEDS 267 regions, same patches. Different in kind: tonal grid (275 regions, follows the shading:
  brows, lips, nose highlight; 8 s, to be sped up) and graph/Felzenszwalb (173 regions at scale 150: flat planes and ribbons along
  features, 1.6 s). Felzenszwalb at 500+ collapses a face into one region, so the scale is bounded.
- Smoothing: low-pass sigma 0.15 mm today. Prototype on the same arcs, ends pinned: sigma 0.4 and 0.8 mm give visibly smooth contours with
  uncovered 0.00 % and overlap 0.00 %. The format already carries curves: `lightburn.py` reads `B` primitives and the operator's own
  files use them; `vectorize.py` writes `L` only.
- AI: `research.openai_client()` and `.env.local` exist; the real app runs from the repository directory and finds the key. No new library.
Steps (each ends with tests, a commit to main, and a look at the real screen):
- [x] 1. Layout: fields in a grid aligned at the top, hints in the same row height, checkbox and button on one baseline, no empty bands (cf83634; all inputs at y = 695 on screen).
- [x] 2. Smoothing as a live slider (operator's amendment: "он перерисовывает все заново"): `contour.py` low-passes each shared arc
  (ends pinned, corners kept) and fits cubic Béziers; base arcs stay as traced, curves are derived at read time for `plan["smoothing_mm"]`
  (new works 0.5, older 0, max 2), so the slider resets nothing and is not in undo; preview `C`, LightBurn file `B`; export entry records
  the strength. Tests: `tests/test_contour.py` (30), route/export/slider tests in `tests/test_vector_work.py`.
- [x] 3. Methods (tonal sped up 8.6 s to 3.3 s by merging superpixel colours on at most 20 000 points; planes scale fixed at 150; tests: four different maps, no collapse of a shaded face, cap of the clustering input): "Мозаика" (SLIC, default), "По тонам", "Крупные плоскости" and SEEDS kept (the operator's answer: "те же три и SEEDS"; DEC-082); old works keep their key; a test that the four maps differ.
- [x] 4. AI colouring (REQ-050): `ai_colouring.py`, operation `ai_colour`, permission route; styles + own text + free lightness + photo permission; answer checked (measured, complete, layers, lightness), one retry with the reason; a variant that is never asked again. One real call on the test copy: 32 s, 16 recipes. Tests: `tests/test_ai_colouring.py` (fake client).
- [x] 5. Spec: DEC amendments (DEC-082 result, DEC-083 live slider, DEC-084 result), REQ-050..052 ticked, version 0.8.0 (tag v0.8.0, commit 4b43135).

### Review of 0.8.0 (2026-10-19)
- [x] Full suite once, before the release commit: 1215 passed, none skipped (10 min 43 s). Targeted files only during the steps (operator's
      remark about test time).
- [x] Backup `titanium-before-0.8.0-20261019T210411Z.sqlite` (integrity ok, 662 observations), real app stopped, wheel 0.8.0 installed into
      `~/.titanium-platform-app`, started again from the repository directory (key found); GET checks of work 22 (view 1.5 s on the first
      request, palette, neighbours, split.svg, scripts) all 200.
- [x] View-only look at the real app: four algorithms (SEEDS selected on work 22), all fields of the split on one line, the slider reads "как
      найдены" (work 22 was made before the slider), the "Раскраска с помощью AI" panel is there and its button is enabled (a key is set).
      Nothing was sent to the AI from the real app; the one real call was made on a copy of the data (numbers only).
- Test copy on port 8796 stopped. Old test tabs (8794, 8795, 8796) in the MarkView window are dead and can be closed.
- Known and left as it is: `git add -A` put specification changes into the layout commit cf83634; the history was not rewritten.
- Not built (still in vector-detail-and-colour-control): density and eyes controls, Contrast and Artistic modes, automatic merging of
  same-recipe regions.


## 0.9.0: saved works, copy, one-screen workspace (operator, 2026-10-19, after 0.8.0 went live)

Operator's words: "Векторная работа должна где-то как-то сохраняться. То есть, что мы выбрали, как она выглядит. ... И возможность
переделать. И, пожалуйста, переделай UI намного-намного более удобным, чтобы не надо было вообще скроллить."

Findings: a work is stored (plan row + document file + source image), but the screen has only a creation form, no list, so a work can only be
reached by its address `#/vector?plan=22`; the work page is several screens tall. Work 22 was deleted from the UI at 21:37Z (audit 190).

Answers (AskUserQuestion): restore 22 (yes); list with thumbnails + "Сделать копию" (new work from the same state, the old one stays);
layout "one screen, three columns" (tabs of settings left, big picture centre, layers and variants right); the 500-for-missing-library
message and the README dependency step go into the same release. SemVer: a new capability, so 0.9.0 (not 0.8.1).

- [x] 1. Work 22 restored from `titanium-before-0.8.0-20261019T210411Z.sqlite` (one plan row; fresh backup
      `titanium-before-restore-of-work-22-20261019T221230Z.sqlite` first; audit row `plan_restored`; GET /api/vector/22 -> 200, version 7).
- [x] 2. Backend (done by a fork, tests `tests/test_vector_list.py`, 26): `GET /api/vector` (list with facts), `GET /api/vector/{id}/thumb.png`, `POST /api/vector/{id}/copy`; a missing AI library is
      a message, not a 500, and `ai.missing` tells the screen why the button is off. Tests: `tests/test_vector_list.py`.
- [x] 3. UI (`vector-workspace.js`, `App.tabs` in `dialogs.js`, router workspace mode, CSS; tests `tests/test_vector_workspace_ui.py`): "Мои работы" (cards: thumbnail, name, date, algorithm, colours, layers, AI style; Open, Copy, Delete with confirmation); the work
      screen as one viewport (header with undo/redo and file, tabs Разбиение/Цвета/AI/Файл on the left, picture in the middle, layers and
      variants on the right, only long lists scroll inside their panel). Check on screen at 1421x951 and a smaller window.
- [x] 4. Spec (DEC-085, REQ-053, REQ-054), README (0.9.0 section, dependency step of the deploy recipe), version 0.9.0, tag.
- [ ] 5. Full suite once, backup, wheel, install, import every declared dependency from the app environment, one AI call from it on a copy,
      deploy, look at the real app.

### Measured on screen (copy of the data on 8796, window 1421 x 951, work 22: 28 colours, 16 layers)
- The page does not scroll (document height = window height) on any tab; the tabs Разбиение, Цвета, AI, Варианты, Файл and the editor tabs
  Кисть and Слои need no inner scroll. Only the editor tab "Цвета" (28 source colours, 1661 px in a 746 px panel) scrolls inside its panel.
- List: thumbnail 360 px, one card; "Сделать копию" made work 23 "Imma + Boris (копия)" and opened it, both thumbnails loaded.
- The side menu folds away on the work screen and "Меню" opens it.
- Not changed: works made by the fill, text and line strategies keep their long page (`jobView`); the thumbnails share the geometry memo
  (6 entries) with the editor, so a long list can evict the geometry of the work being edited (recomputed in about 0.5 s).

### Release 0.9.0 (2026-10-19)
- Full suite once: 1246 passed, none skipped (666 s). Commit `fdaa132`, tag `v0.9.0`, pushed to main.
- Backup `titanium-before-0.9.0-20261019T224230Z.sqlite` (integrity ok, plans 6 and 22) taken before the real app was stopped.
- Wheel 0.9.0 installed into `~/.titanium-platform-app` (`--force-reinstall --no-deps`, then `pip install <wheel>`); every declared dependency
  imports from that environment; the real app runs 0.9.0 on 8765 (data `~/.titanium-platform`).
- First feature check from the app environment on the data copy (port 8796, stopped after use): list, copy (201) and an AI colouring call
  ("cubism", 41 s, 18 recipes).
- Real app, view only, 1421 x 951: the list shows work 22 with its thumbnail; the work screen has no page scroll (951 = 951); only the editor
  tab "Цвета" scrolls inside its panel.
- Found while looking: work 22 as restored (from the 21:04Z backup) is the older state: document version 7, SEEDS, 308 regions, 6 layers,
  colouring "Ближе к оригиналу", 1 variant. At deletion it was one step further (document version 8, file `vector-075cbfd7c547.json`, written
  21:35:15Z): re-split "По тонам" (medium, 538 regions, the 4 manual edits kept), photo permission on and off, settings tolerance 0.05 with
  "include as shot", colouring "Случайно" then "Сохранить тональность". The deleted row is still readable in the snapshot
  `titanium-before-restore-of-work-22-20261019T221230Z.sqlite` (freed pages). Nothing was written to the real data for this; the operator decides:
  redo the split and the colouring by hand (two clicks), or have the missing step applied (needs approval).
- Not done: `mcp` library is still missing in the app environment (only `titanium-research-mcp` needs it); the old `tolerance_mm` split field is
  still an API parameter; commit `cf83634` mixes spec changes with the layout (history not rewritten).

# 0.10.0 - rename a work, one screen without scrolling for "Эксперименты" and "Карта цветов" (operator, 2026-10-19)

Requests (verbatim): "Сделай возможность переименовать работу"; "Поменяй UI на 1 screen without scroll for карта цветов и для экспериментов".
Answers to my questions: scope = "Пункты меню и вложенные страницы"; experiments = list on the left, working task and findings on the right;
colour map = filters on the left, the map in the centre, the colour search on the right. Measured before (1421 x 951, copy of the data):
experiments list 3725 px, experiment page 4403 px (plate-only experiment 1295 px), colour map 1473 px, model of one laser and lens 30396 px.

Shared frame (done by me first): `.os`, `.os-head`, `.os-body`, `.os-col`, `.os-col-head`, `.os-scroll` in styles.css (section 15), router leaves the
footer out of an `.os` page; `.workspace` next to it also folds the side menu away; `App.tabs` for tabs; below 1100 px the page stacks and scrolls.

- [x] A. Rename a vector work: `POST /api/vector/{id}/rename` (name only, no history entry, no document version, audit `vector_work_renamed`), pencil
      next to the name on the list card, in the work header and on the long page of other strategies, dialog with the field, tests, REQ-055, DEC-086.
- [x] B. "Эксперименты": list (search + two filters, scrolls inside) | working task over findings; keeps the side menu; `ExperimentCards.list` stays usable on the laser page.
- [x] C. "Карта цветов" (general map): filters | big map with projection switch and lightness range | colour search with its results; `.workspace` (menu folds).
- [x] D. Experiment page (`experiment.js`): one screen, tabs/columns by its content, the overlay photo large.
- [x] E. Model of one laser and lens (`colors.js`) and the knowledge page (`knowledge.js`): one screen, a list of sets, the selected set's plot and tables in panels.
- [ ] F. Integration (me): targeted tests of every touched file, REQ-044 / DEC-080 in the spec (done), README 0.10.0 section, version 0.10.0, full suite once, backup, deploy
      (wheel + dependency imports from the app environment + first check from it on a data copy), look at the real app, report with measured page heights.

### Review 0.10.0 (five parallel forks on disjoint files, then integration)
Measured at 1421 x 951 on a copy of the data (`document.documentElement.scrollHeight == innerHeight` everywhere below; GET only):
- "Эксперименты": 3725 -> 951 px; with `?device=`, with a filter that empties the list: 951. The list scrolls inside its panel (2451 px in 587).
- "Карта цветов": 1473 -> 951 px; default, after a search (12 results), after a click on a point (the chart shrinks 684 -> 458 px, the detail strip
  fits), with 76 or 0 colours: 951. Inside: the results list and the unfolded "Как это считается".
- Experiment page: matrix test 4402 -> 951, finished work 1401 -> 951, a second finished work 951, plate-only 1295 -> 951 (measured on its "Плата" tab
  only before the copy lost those plans). Inside: the "Результат" tab with many layers (1951 px in 750 for 10 layers).
- Colour model of one laser and lens: about 30 396 -> 951 for all five sets and every tab, the unknown lens too; knowledge 1, 120, 343: 951.
  Inside: the model list (343 rows, about 23 900 px in 750) and the long "Варианты" / "Все слои" tabs.

Where the old parts went (experiment page): title, status, tasks, add photo, delete -> header; photo, contour and brightness buttons, legend (now a
fold-out "Что означают линии"), caption -> left column; checks -> tab "Проверки (n)"; alerts, margins, measured layers (cards instead of the 5-column
table, same data), tonal tables and images -> tab "Результат"; parameter matrix -> tab "Матрица" (only if the check has one); plate and links -> tab
"Плата"; LightBurn file and photo-preview link -> tab "Работа"; conclusions -> tab "Выводы (n)".
Colour model: calibrated observations -> first item of the list "Наборы"; their map -> centre; table "Модель цветовых параметров" (343 rows, all 8
values and the links to the knowledge pages) -> right column; each RAW pair -> a list item and the centre; "Что видно", "Цветовые варианты", "Все
измеренные слои" -> tabs; warnings, the note about relative Lab and "принять пару" -> under the map; "Нестабильные наборы" -> under the header.
Knowledge: details and the decision buttons on the left; history and evidence on the right.

Shared edits outside the pages: `App.tabs` skips hidden tabs on the arrow keys (dialogs.js); the router leaves the footer out of `.os` pages;
`mapPlot` got an optional `{fit}`. Old `.exp-*` layout rules of the experiment page were removed (nothing else used them).
Caveats: below 1100 px the pages scroll as before (checked by CSS and tests, not in a narrow browser); the copy of the data has no findings for the
material, so the findings panel was checked on injected markup; the knowledge states "под вопросом", "утверждено", "производство" are covered by
mock tests only. During this work three plans of the shared test copy (22, 23, 24) were deleted from it (not by me, a fork used the shared server
beyond GET; see the correction below); the operator's real data was checked afterwards: plans 6 and 22 intact.
Real work 22 meanwhile: the operator re-split it (SLIC, document version 10) and coloured it with the AI at 22:48 and 22:52 (variants 8), so the
AI colouring works in production and the older state of 21:35 in the snapshot is no longer needed.

### Changes during the integration (operator's messages while the full suite was about to run)
1. Menu (DEC-081): "Когда открываю карту цветов - меню исчезает" -> "Пусть вообще оно будет висеть слева и открывается в попапе" -> "короче пусть везде
   будет так". The folded menu is gone everywhere (also from the vector work screen of 0.9.0): a fixed 56 px rail of icons, the button at its top
   (and "Меню" in the header) opens the names as a popup; a click outside, Esc and a choice close it; below 1000 px only "Меню". The five pages of
   0.10.0 lost the `workspace` class (it only removes the width limit now). Measured at 1421 x 951 after the change: experiments, colour map,
   experiment page, vector list, work 22, devices: scrollHeight = innerHeight = 951, no horizontal overflow; settings 1843 (long, as before).
2. Lost work (DEC-082): "Я удалил эксперимент и удалилась моя работа... Почему?" Cause: the experiments list showed vector works and "Удалить
   эксперимент" deletes the plan, which for an unphotographed work is the work. It happened on the test copy (port 8796, audit 192 `plan_deleted` 22
   at 23:18:33Z); the real data was intact (work 22, version 10, audit up to 191). The explanation I had for the earlier missing plans 22-24 on the
   first copy ("a fork") was wrong: it was the same click path. Fix (operator's choice): a vector work without a photograph is not an
   experiment (list and key), and the plan page of a vector work has no "Удалить тест" button nor, before a photograph, "К эксперименту".
   Tests: `tests/test_vector_work_is_not_an_experiment.py` (5; three fail without the change). Still open: a vector work WITH photographs is an
   experiment, and deleting that experiment deletes its checks and archives the plan (the work leaves the work list; rows and files stay).
   Until 0.10.0 is deployed the real app (0.9.0) still lists work 22 as an experiment: do not use "Удалить эксперимент" on it.

### Release 0.10.0 (done 2026-10-19, commit 771ef04, tag v0.10.0)
- Full suite once at the end: 1312 passed, 0 skipped (11 min 50 s). Targeted runs before it: UI files 80, experiments 21.
- Backup before the deploy: `~/.titanium-platform/backups/titanium-before-0.10.0-20261019T235536Z.sqlite` (integrity ok; plans 6 and 22; audit 191).
- Wheel built with the app environment's pip, installed with `--force-reinstall --no-deps` and then with its dependencies; all ten declared
  dependencies import from `~/.titanium-platform-app` (`scikit-learn` under the name `sklearn`; `mcp` 1.30.0 is installed now).
- First feature check from the app environment on a data copy (port 8798, stopped after): list, rename (version stays 10), blank name 422, the
  experiments list without work 22 (16 entries), `/api/experiments/plan-22` 404, the rail in router.js and styles.css.
- Real app restarted on 8765 from the repo directory: 0.10.0, work 22 (Imma + Boris, v10, 12 layers) intact, audit still 191, integrity ok.
  Viewed read-only at 1421 x 951: vector list, experiments, colour map, an experiment page, work 22: scrollHeight = innerHeight = 951,
  rail 56 px, no horizontal overflow; the plan page of work 22 has no "Удалить тест" and no "К эксперименту".
- Open: the test copy on 8796 (`scratchpad/live-copy-4`) holds the operator's own edits (renamed "Inna + Boris", split 23, SEEDS) and is NOT the real
  app; moving them to the real app needs the operator's word. A vector work WITH photographs is still an experiment (see DEC-082).

## 0.11.0: palette from all plates of the material, and as many layers as colours are set (operator, 2026-10-19/20)
Spec ids: DEC-087/REQ-056 (the fifth mode) are SUPERSEDED by DEC-089/REQ-058; DEC-088/REQ-057 (palette) live in the feature `vector-detail-and-colour-control`.
(Ids are per feature: DEC-080..082 and REQ-044 of the 0.10.0 notes above are in the main feature `titanium-color-engraving-intelligence-platform`.)
Operator, 2026-10-20: "Какая кнопка как можно больше цветов? Не нужна такая кнопка. цветов всегда как можно больше и ограничено количеством в
установках" -> asked what to do with the other modes -> "Разные цвета везде, «Меньше слоёв» убрать". Also: "не нужно запускать все тесты пока я не
попрошу - все локально запускай как можно скорее - я проверю" (full suite NOT run for this release; targeted files only).
- [x] DEC-089/REQ-058: `palette._closest` = one-to-one assignment (scipy `linear_sum_assignment`, tolerance-clipped cost, then time; n > m: every entry
  used once, the rest nearest), `_tonality` = strict rising entries (`_monotone(strict=True)`, `_spread` DP without kept choices), `_random` uses every
  entry when the palette is small; `_pool` keeps the operator's kept entries from the others; `fewer_layers` and `most_colours` removed (API error text,
  buttons, translation); `vector_job._automatic` maps a stored old mode to closest; the old name stays in `MODE`/`MODE_NAME` for saved variants.
- [x] DEC-088/REQ-057: `palette._same_material` (family + grade, case/spacing ignored, no grade = itself) and `palette._across_plates` (a recipe on several
  plates is one entry; group/id of the work's own plate when measured there). Record 1 "Test Plate 1mm": "Garde 2" -> "Grade 5" (PUT
  /api/materials/1 after `.backup` titanium-before-grade5-20261020T001540Z.sqlite).
- [x] Measured on a data copy (port 8797, stopped): work 22 palette 18 -> 505; closest 29 of 29 layers (dE 6.97; before 20 layers / 6.16 with the 505 palette,
  7 / 18.5 with 18), tonality 29 (7.84), random 29; old variant 1 restores (7 layers).
- [x] Tests (targeted, 255 passed): test_palette (51: brute-force optimum for closest and tonality, own entry in every mode, every entry used, kept entries,
  merged plates, grade/family/no grade), test_vector_work (5 layers on the fixture, the other-plate test), test_vector_list, UI label tests.
- [ ] Deploy: backup, wheel, install, first check on a copy, real app (no button; palette count; 29 layers on the work when the mode is pressed). No full suite,
  no push/tag until the operator has looked.
Not done and not asked: widening the palette with colours predicted by the laser model (unmeasured; needs its own decision); AI colouring unchanged.

## 0.12.0: confidence in the colour of a setting (operator goal, 2026-10-20; REQ-045, DEC-083)
Operator: new experiments and pictures give "new colours"; a setting needs a confidence in its value and the more confident colours are preferred: the
same colour repeating under the same settings is more confident, a colour that changes is not and "cannot be taken", a yellow that is redone as dark brown
is replaced by the dark brown; more repeats, more confidence; more differences, less.
Measured on the operator's data first (copy, GET only): 539 recipes on the colour map, 23 repeated, 11 of those disagree by dE 7 to 22.8; palette of work 22 =
505 recipes, 496 engraved once, 9 with a confidence; 14 settings are in the palette twice or thrice because chart / against-clean / as-shot are separate recipes.
- [x] A. `agreement.py` (pure): agreeing group within dE 5, newest wins a tie, confidence k^2/((k+2)n), contradicted; unit tests incl. the yellow -> dark brown case.
- [x] B. Palette (what a vector work chooses from): colour = agreed colour, `agreement`, `caution` (contradicted / superseded by a better basis), `automatic()`
      refuses cautioned entries, `_closest` prefers confident before fast inside the tolerance; error text when nothing is left; tests.
- [x] C. Knowledge model `model.summarize` (agreed colour + agreement-aware confidence, stability still over all) and colour map `search` (distance to the
      agreed colour, confidence, agreement); tests.
- [x] D. Screens (+ the operator's addition of 2026-10-20: the diameter of a circle on the colour map follows the confidence): palette table and picker (confidence, "k of n agree", contradicted / replaced), colour map result, knowledge page; i18n coverage tests.
- [x] E. Real data: before / after counts on the copy (changed colours, contradicted, superseded), a work's colouring before / after.
- [ ] F. Release 0.12.0: targeted tests only (operator: no full suite unless asked), README, version, backup, wheel, install + dependency imports, first check from the
      app environment on a data copy, real app view-only. Commit on main, NOT pushed until the operator has looked (feedback of 2026-10-20).
Not in this step: pooling the three measurement bases of one setting into one estimate (REQ-029 keeps them apart); a screen to set the dE 5 limit.

### Review 0.12.0 (before the deploy)
- New code: `agreement.py` (consensus within dE 5, newest wins a tie, confidence k^2/((k+2)n), contradicted = no strict majority), `colormap.agreed / annotate`,
  `palette._entry / _supersede / automatic / _closest`, `model.summarize / predict_for_lab`, `colormap.search / fastest_first`, `/api/colors` points carry `trust`,
  screens: vector colours (table, picker), colour map (circle radius 3 + 12 * trust, title, legend), knowledge page.
- Tests: `tests/test_agreement.py` (11, pure), `tests/test_setting_confidence.py` (16: palette, supersession, assign, knowledge, search, API points), the DOM test
  of the circle diameter in `tests/test_color_map_one_screen.py`. Old tests that pinned "the mean of all engravings" were changed to agreeing data or to the agreed
  colour (test_palette plate merge, test_model rephotographs, test_findings x3, test_vector_work other plate); the anomaly finding now measures from the agreed colour
  (its statement and Russian translation changed).
- Measured on a copy of the real data (GET only, own port 8799, stopped after): colour map 565 points, 517 engraved once (trust 0.33), 22 with two agreeing (0.5),
  3 with three (0.6), 20 + 3 contradicted; palette of work 22: 505 entries, 3 contradicted, 16 superseded (11 of them as-shot, which automatic modes never took), 9 with a
  confidence; palette 0.10 s, colour map 0.08 s, annotate 8 ms (no slower than before). Recolouring work 22 (closest): 29 layers, no cautioned entry used; without the
  rules the old choice would have used one superseded colour (dE 22.7 from its source), mean dE 14.5 -> 16.3 when it is refused (the price of not taking it).
- Headless Chrome on the copy: circles of the map have r = 7 (517), 9 (23), 5 (20), 10.2 (3), 4.3 (3): the map is dominated by colours engraved once.
- Open / not done: pooling the three measurement bases of one setting into one estimate (the better basis only replaces the worse); no screen sets the dE 5 limit;
  `conversion.eligible` (knowledge-based plans) takes the agreed colour through `summarize` but does not refuse contradicted entries (its stage gate stays).

### 0.12.3: zoom and pan of the colour map (operator, 2026-10-20; REQ-046)
- [x] Wheel (about the cursor), sideways wheel / shift + wheel, drag, double click, buttons + / - / whole map, keys, two-finger pinch; circles keep their screen size;
      the view of a plane survives picking a colour. Pure `zoomView / panView / clampView` tested in node; the DOM test covers wheel, drag, buttons, keys, pick.
- [x] Real headless Chrome on a copy of the data (port 8801, stopped): wheel x2.5, drag, drag that starts on a circle does not pick it, plain click picks it, reset.
- Not checked: a real pinch on a touch screen (REQ-046 criterion 4 stays unticked). Released locally and deployed to 8765; NOT pushed, NOT tagged.

## 0.13.0 plan: the measured colour is the colour on the picture; every LightBurn parameter read and shown; re-measure (operator, 2026-10-20) - NOT APPROVED YET
Operator: the colours listed for check 60 (pair 60, IMG_3327.DNG, work "Inna + Boris 2", plan 22) do not match the photo, "especially the dark ones"; the ColorChecker
must make the shown colour the colour on the picture. Also: Q-pulse "not in file" is a bug, all parameters (passes, fill, angle, TC on/off) matter and their defaults
must be known; experiments must be re-runnable after the colour fix.

### Evidence (own analysis of pair 60, copy of the data, read only; scripts in the scratchpad)
1. The chart fit has no offset (3x3 on linear RGB). The photo is ~3 stops under (gains 8-10), so any additive error (flare, black level) is multiplied by ~10 and lifts the darks:
   black patch L 30.4 (reference 21.7), neutral 3.5: 40.4 (36.1), saturated patches desaturated (orange b 45.8 vs 56.1). Affine fit minimising dE in Lab:
   black L 21.0, leave-one-out mean dE 4.0 (now 6.4), max 8.1 (now 12.9). Layer colours move by 0.7-8.1 dE (C07 8.1, C10 5.0, C05 4.3, C16 3.4, the rest < 3).
2. The plate is specular and brighter than the matte white patch: median corrected linear > 1.0 for C05, C07, C10; 87% of C07's pixels are clipped at 1.0, so L is pushed to
   ~99 and the hue moves (stored L 98.8 a -8.9 b 27.5, unclipped L 107 a -0.5 b 39.7). A matte chart cannot certify L* above its own white.
3. One median per layer is not "the colour of the layer" when its elements differ. C16 (the darkest listed, L 55.2 / a 3.3 / b 5.8) has 20 measurable elements:
   brown 47 / 7 / 12 (31.9 k px, the big rectangle at the top), grey-brown 55-58 (16.5 k, 9.9 k px), grey-blue 69 / -3 / -1 (17.8 k px). The listed colour matches none of them.
   Only 25-91% of a layer's pixels are within dE 10 of its median (C15: 25%).
4. The list has no dark colours: after correction only 2.3% of the plate is below L 45; the darkest listed layers are L 55 (C16), 60 (C14), 63 (C12). C16 is also excluded
   from the model (`model_eligible=0`: no QPulseWidth in its layer), so the darkest measured colour never reaches the colour map or the palette.
5. Sixteen layers represent a picture that has hundreds of distinct areas; the picture's own darks are not among the experiments' settings at all.
6. PIPETTE vs CHART (operator, 2026-10-20: "why not take the colour from the photo like an eyedropper?"). The median of a layer's pixels IS an eyedropper; the question is
   which picture it is taken from. On the camera's own preview (the DNG's embedded JPEG, what Photos / Preview show) the chart reads: white patch L 71.9 (reference 95.8),
   grey ramp 71.9 / 59.2 / 44.3 / 30.3 / 18.6 / 9.5 (reference 95.8 / 80.6 / 65.9 / 51.2 / 36.1 / 21.7), mean chart dE 23.9. So the picture is ~20 L* darker than the chart's
   white says. Layer colours, mean L*: pipette on the preview 61.3, exposure only (one gain x7.3 so that the white patch is white, no matrix) 81.0, current 3x3 79.8,
   affine in Lab 80.7. C16: 36 / 56 / 55 / 53; C01: 66 / 82 / 81 / 83. The "lightening" is the exposure normalisation to the chart's white, NOT the matrix; the matrix only
   changes chroma (mean 9.9 -> 14.1 to fit the chart). Clipped layers differ in hue: C07 pipette a -2 b 30, current a -9 b 28 (L 77 vs 99).
   The open physical question (only the operator can judge it with the plate in hand): does the plate look like the camera picture (darker; then the matte chart overstates
   the lightness of a mirror-like plate) or like the chart-corrected photo (then chart-relative colours are right)?

### Part A: measurement (the operator's main complaint)
- [ ] A1. Chart correction: 3x3 + offset fitted to minimise dE in Lab (fallback to the old fit when fewer than 18 patches are found); store `correction.model` and the
      fit residual with every check so old and new measurements are told apart. Tests: synthetic chart with a known offset recovers it; leave-one-out bound.
- [ ] A2. No per-pixel clipping before a layer's colour is taken; the median is taken in linear light and clamped only for display. A layer where > 20% of the pixels
      exceed the chart white gets `lightness_bound = true` (its L is a lower bound); shown on the card; the model keeps it but does not use L as exact.
- [ ] A3. DECIDE AFTER A1-A2 WITH NUMBERS: layer spread. Options: (a) keep the median and show the spread and the dominant cluster on the card; (b) the dominant
      cluster is the layer colour; (c) every element is its own observation of the same recipe (the agreement rule of DEC-083 then judges repeats; it needs the re-measure of C).
- [ ] A4. Proof on the screen: chart table (reference vs measured per patch, dE), grey ramp, and the layer fills drawn next to the corrected photo, so the operator can judge.

### Part B: parameters and defaults (Q-pulse, TC on/off, passes, fill, angle)
- [ ] B1. One module with the LightBurn defaults (bidirectional, cross-hatch, angle, passes, fill mode, interval ...). "Tag absent" is kept apart from "device default";
      Q-pulse and the four TC timings have NO documented default, so they come from the operator. Found on this Mac (`~/Library/Preferences/LightBurn/prefs.ini`): the
      default layer template holds QPulseWidth 2, LaserOn_TC 1, LaserOff_TC 1, End_TC 1, Polygon_TC 10, JumpSpeed 4000, OverrideGalvoTimings true, bidir false; the device
      "JCZFiber" holds Laser_QPulseWidthEnabled true and no timing values. Needs the operator to read the two layers (cleaning, C16) in LightBurn.
- [ ] B2. Every parameter on the layer card, recipe and colour-map details: direction, angle, cross-hatch, passes, global passes, fill, interval, TC timings + override,
      Q-pulse with its source (file / default / supplied). Replace "Q-Pulse нет в файле".
- [ ] B3. A layer without Q-pulse can be completed by the operator (existing `supplied_settings`), after which C16 becomes model-eligible.

### Part C: re-measure an experiment (after A)
- [ ] C1. Observations are immutable (DB trigger). A re-measure inserts new observations that SUPERSEDE the old ones (link to the replaced row); old rows stay as history;
      every derived view takes the newest per (pair, layer). One button per check, and "re-measure all" with progress and a before / after report (changed colours, dE).

### Not in this plan
Pooling the three measurement bases of one setting; a screen for the dE 5 agreement limit; any change to the cameras or the chart itself.

### Decisions needed from the operator
0. NEW, first: which basis for the colour of a layer: chart-relative (now; comparable between photos) or as the camera picture shows it (pipette), or both numbers on the
   card and the operator picks what the palette and the map use? Decided by what the real plate looks like (see evidence 6).
1. A1 + A2 as written (affine fit in Lab, no clipping, a lightness-bound flag)?
2. A3 option, after the numbers of A1-A2 (recommendation: (a) now, (c) later).
3. B1: the Q-pulse and TC values LightBurn shows for the cleaning layer and C16 of "Inna + Boris 2" (or the device settings).
4. C1: supersede-by-link (recommended), or something else.
5. Order: A, then C, then B (recommended; B does not change existing observations).

### 0.13.x plan after the operator's decisions of 2026-10-20 (DEC-085 pipette; "Q-Pulse default is 200, set it in the parameters")
Decided by the operator: the colour of a layer is taken like an eyedropper from the picture (DEC-085); the default Q-pulse is 200 ns and is set in the parameters.
Evidence added: the camera's own exposure is not steady - the chart white reads L 72..91 over 14 photographs (median 82.5), so one recipe photographed twice can differ by
several L*; the same-recipe agreement (dE 5) will count some repeats as differing. Recorded in DEC-085; the operator is told, not asked.
- [-] 0.13.0 P1-P5 (eyedropper on the camera's embedded preview, `measurement_basis`, `is_standard`): DROPPED 2026-10-20 after the measurement: the preview reads the
      chart 20 L* darker than the real chart and changes with the exposure (DEC-085 rejected). Replaced by DEC-087 (look-up among the 24 squares), below.
- [x] 0.13.0 (released, deployed to 8765, not pushed) Default Q-pulse width as a parameter of the laser (passport `default_pulse_width_ns`, 200 for the JPT M7 template and for the operator's laser): a layer whose
      file has no QPulseWidth takes it with the provenance "laser default"; shown as such; DEC about the rule "nothing is filled in automatically" (REQ-015/016).
- [ ] 0.13.2 Re-measure an experiment (`create_alignment_revision` + check + accept; one button, and all experiments with a before / after report on a COPY first).

### 0.13.1: the colour is found among the 24 squares; the screens show the picture the numbers come from (operator, 2026-10-20; DEC-087, proposed)
Operator: "work in the other direction: you know the 24 squares; take the colour with an eyedropper and find it among the squares; why lighten or darken at all?"
- [x] Measured on 15 charted photographs (leave one square out): global matrix 4.5 dE (dark squares 5.0, worst 12.9); matrix + offset 3.8; radial basis 4.5-4.7;
      look-up of the 4 nearest squares on an affine base 3.6 (dark 3.1, worst 8.8). Check 60: grey ramp 95.8/80.6/66.1/51.3/36.5/21.7 against 95.8/80.6/65.9/51.2/36.1/21.7.
- [x] `photo.fit_lookup` (affine base in Lab + nearest-squares local correction, honest leave-one-out residual), picture map through a 41-node LUT in threads, `CALIBRATION`
      switch ("lookup" default, "matrix" kept); `tests/test_lookup_correction.py` (8 tests).
- [x] Screens: the check screen opens on the corrected picture when the chart is usable and does not lift it; the experiment screen lifts only the uncorrected RAW unless the
      operator chooses; the cache pre-warm follows the same rule.
- Finding: the layer colours of check 60 change little (mean dE 2.6, mean L 79.8 -> 80.1): the "lightening" was the exposure of the white square and, on screen, the gamma lift
  of 0.58 on top of the corrected picture / the dark uncorrected default view. Specular layers C05, C07, C10 still saturate (L 98-99).
- [ ] Open: layers brighter than the white square (flag "above the chart's white"); pixels of a layer covered by an earlier engraving (the pink / green areas missing from the list);
      IMG_Lion chart read wrongly (grey ramp not monotonic, residual 38) - must be refused with a clear message; all LightBurn parameters shown with defaults (TC timings unknown);
      0.13.2 re-measure (rehearse on a copy, before / after report, ask before applying to the real data).

### 0.13.2: re-measure (operator, 2026-10-20: "redo all experiments with the new calculations"; DEC-088, proposed)
- [x] `ingest.remeasure_pair` (revision -> check -> review -> accept; kept untouched unless the colour basis is the same, no problems and no layer less),
      `POST /api/pairs/{id}/remeasure`, buttons on the experiment and analysis screens, `tests/test_remeasure.py` (6).
- [x] Rehearsal on a COPY of the real data (paths rewritten to the copy: the real DB holds absolute file paths and accepting a revision unlinks the old pair's files).
- [x] Applied to the real data in 0.13.3 (after the pulse-width rule was settled, so each pair was measured once more only): see 0.13.3.
- Trap found: the database stores absolute file paths, so a plain copy of the DB would make `delete_pair` unlink the REAL files. Rewrite the paths in any copy first.

### 0.13.3: any Q-Pulse in the laser's range (operator, 2026-10-20: "who said 300 is not supported? I entered it and it works"; DEC-089, accepted)
- [x] Asked: any width 1-500 ns with an interpolated cut-off (chosen) / add the values to the table / any width without power loss.
- [x] `devices.pulse_range`, `cutoff_for` (log-log interpolation; CW neighbour -> the other neighbour), `require_selectable` = range, operating point says "interpolated"; default pulse width in range.
- [x] Tests moved from off-step values (7, 5, 210) to out-of-range ones (600); `tests/test_pulse_width_range.py`.
- [x] Deployed 0.13.3 (backup titanium-before-0.13.3-*.sqlite) and re-measured ALL 17 accepted pairs on the real data through the app (new pairs 61-77; old ones Deleted, rows kept):
      539 layers, mean dE 1.98 (chart pairs 1.4; the 4 camera-relative pairs 6.7: they were measured by an older pipeline); model-eligible 353 -> 474 of 540 (the rest: 65 camera-relative layers
      by design, 1 cleaning witness); no active observation without a pulse width; colour map 0.14 s warm.

### 0.14.0: "work on the errors" - close the loop promise -> engraved result -> conclusion -> correction (operator, 2026-10-20; DEC-090 proposed, REQ-047 draft)
Operator's goal: what the screen promises must equal what is engraved. After each LightBurn file the operator reports the result (photo); the system compares, concludes about
the work and the existing works, and may swap colours / change parameters / find the problems. Decisions of the operator: the conclusion lives inside the work plus a mark in the
list of works; the system proposes replacements, the operator applies them.

Found in code and real data: the palette is re-read on every view (a new measurement already changes the preview); a vector work kept the preview colour (`lab`) but `prediction` was None, so
its pair report compared nothing; an export kept only its number of layers; the engraved file need not be the exported one (pair 77 matches 0 of 16 layers of work 22 by settings).

- [x] A. An export keeps what every layer promised (`exports[n].promised`: settings, colour, basis, area, regions); older exports are reconstructed while the colouring is unchanged ("approximate").
- [x] B. Engraved layers matched to the promise by settings (0.5 %), greedy by closeness, each layer once; unmatched layers listed on both sides.
- [x] C. Review per layer (promised / got, dE, dL, dC, dh, beyond, causes from the measurements, systematic shift, poor chart), stored in the work (`reviews`, one per engraving), Result tab with
      two pictures (promised / measured colours), mark in the list, block in the pair report, message on acceptance.
- [x] D. Drift of every work of the laser and lens against the last file's promise (recipes no longer used are settled; never-exported works are not marked), counts kept for the list
      (`attention`), replacement proposals (closest measured colour, >= 1 dE nearer), applied by the operator as ordinary edits.
- [~] E. Causes: only what the measurements show (highlight above the chart white, different basis, no chart, poor chart, one shift of most layers). Not done: recipe measured once / unstable,
      below the cut-off, covered by another layer (order).
- [ ] F. Parameter changes (power/speed) from measured neighbours, or send the colour to the Experiment Designer as a target. Not done.
- Assumptions to confirm: visible difference 5 dE (the chart's own error is about 3.6), replacement gain 1 dE, poor chart 7 dE, systematic shift 3 L* on 75 % of layers.
- Tests: tests/test_work_review.py (23), tests/test_work_review_ui.py (4); the vector UI tests list the new tab and script.

### 0.14.1: "Загрузить фото для этой работы" (operator, 2026-10-20; REQ-048 draft)
Operator asked for the link after learning that a photograph links to a work only through the TCE1 identifier in the file's notes (pair 78 "Inna + Boris 2" carries the identifier of work 22 but its layers were edited, so 0 of 16 matched).
- [x] Link on the Result tab (empty and filled state) -> `/ingest?plan=<id>&material=<id>`; the form takes laser, lens, titanium from the work, names it, links back.
- [x] Pair page names the linked work (`plan_name` on the pair).
- [x] Check warns when the file's identifier names another work than the chosen one (the file's identifier wins; a file without one falls back to the chosen work).
- [ ] Not done: the chosen work forcing the link when the file names another one (would hide a wrong file); a link on the "Файл" tab next to the saved files.
- Tests: test_work_review_ui.py (3 new), test_plan_ingest.py (1 new); targeted run in pytest_0141.log. Full suite not run.

### 0.15.0: the colour map says how far a colour is trusted and where it comes from (operator, 2026-10-20: "filter < 1 diameter", "show the confidence when I pick colours", "show where we know this colour from"; REQ-049 draft, DEC-091 proposed)
Operator's words, all on the colour map screen. "Diameter" is the circle of a colour (REQ-045, DEC-084): radius 4 for an engraving never repeated, x1.5 for each repeat that gave the same colour,
/1.5 for each that gave another, 2..14. Agreed with the operator: "1 diameter" is the circle of one unrepeated engraving; a colour whose circle is smaller than that (more engravings differ than
agree: `agreeing - 1 - differing < 0`) is "doubtful" and can be filtered out.
- [x] A. Server: `agreement.doubtful(found)`; `colormap.annotate` marks each point `doubtful`; `/colors` and `/colors/search` take `hide_doubtful` and report `counts.doubtful`.
- [x] B. Server: `sources` of a recipe = its independent engravings (experiment, pairs, photographs, date, colour, dE from the agreed colour, whether it agrees, measurement basis);
      on every search match, and on `/colors` as `recipes[group]` for recipes engraved more than once.
- [x] C. UI: filter "hide colours we doubt" (remembered with the other filters, counted in the head); the picked colour shows its confidence (the circle as on the map, the number, "N of M agree")
      and "Where we know this colour from" (every engraving, who agrees, links to the experiment and the analysis); the search results show the same.
- [x] D. Tests: tests/test_colormap.py (annotate / filter / sources / API), tests/test_color_map_one_screen.py (UI in node). Targeted only; the full suite is not run.
- [x] E. REQ-049 (draft) and DEC-091 (proposed) through the markview tools, README 0.15.0, version 0.15.0; deployed to 8765 after the commit (backup, wheel, restart); nothing pushed or tagged.
- [x] F. Done as 0.15.1 (below).
- Not touched by me: pair 101 (the operator deleted it and uploaded the photograph again as pair 102 with the material "Small Plate"; 102 is "Ready to accept", not accepted).

### 0.15.1: the check does not measure layers the photograph cannot show where the file puts them (operator, 2026-10-20: "Не находит", screenshot; agreed "Согласен - вперед"; REQ-050 draft, DEC-092 proposed)
The file engraved from work 22 had the picture resized to 100 x 100 mm and moved; layers C18 and C28 are hidden in LightBurn, so its tools skipped them and they stayed at the export's 150 x 143 mm
places (outlines on the ruler and the chart; 16 of 29 uncertain elements; rows C18 dE 23.7 and C28 46.0 meaningless). C28 also has its output switched off.
- [x] A. `lightburn.Layer.hidden` and `.output_off` (from the `hide` and `doOutput` settings of the file).
- [x] B. `left_behind.py` (pure): per-axis scale, offset and mirror shared by the layers of the engraved and exported files; a layer is left behind when it sits at the export's place and not at the moved place.
- [x] C. `ingest._leave_out_layers` called by `check_pair`: flags `left_out`, adds a note and a warning, drops the shapes of those layers so alignment, coverage and measurement skip them; the overlay skips them.
- [x] D. Russian translations of the warnings and notes (`i18n-rest.js`); `test_i18n_coverage` green.
- [x] E. tests/test_left_behind.py (11 tests; a mutation of the detector fails 4 of them); targeted run of 459 tests green (`pytest_0150b.log`). Full suite not run.
- [x] F. Checked on a COPY of the real data: pair 102 -> C18 left behind, C28 output off, 28 of 30 layers measured, alignment valid (256 of 269 elements found, 2.6 px), the other layers move by at most 0.8 dE.
- [x] G. REQ-050 (draft) and DEC-092 (proposed) through the markview tools, README 0.15.1, version 0.15.1; deployed to 8765 (backup, wheel, restart); nothing pushed or tagged.
- Not decided: pair 102 (accept or not): 27 layers beyond tolerance in the earlier review of the same photograph; the operator chooses.

### 0.16.0: replace a colour of a work with a chosen one, and see where every colour comes from (operator, 2026-10-20: "I cannot change colours simply", "I want to see where the colour comes from: tests or an existing work", "replace it with a more stable colour", "I do not understand exclude"; plan agreed with "да делай"; REQ-051 draft, DEC-093 proposed)
Today the editor's "Цвета" tab (source colours of the picture, each with the titanium colour it will be engraved in) offers only a merge checkbox and "Исключить"; the picker with "Изменить" exists only in the table on the work page. "Исключить" removes
every area of that colour from the file (they are not engraved), which reads like a missing colour. The picker shows the basis, the number of engravings and photographs, dE and the confidence, but not which test or work the colour was measured in.
- [x] A. Server: every point of the colour map says what its engraving was (`origin`: test = calibration plate, capability test or parameter matrix; work = everything else; `work_id` of a vector work);
      `colormap.sources_of` carries it; palette entries carry `sources` and `doubtful` (so the picker, the editor and the work's own colours show where a colour comes from).
- [x] B. UI shared: `App.sourcesBlock` (the "where we know this colour from" block of the colour map moved to app.js, now with the kind of each source and a work link) and `App.originText`; the colour map uses it.
- [x] C. UI picker (vector-colours.js `pick`): "Откуда этот цвет" for the chosen colour, stability line (confirmed by repetition / one engraving / doubtful), sorting (closest | most stable | fastest), filter "only repeated colours",
      and "Стабильнее и похоже на этот цвет": colours more stable than the current one, nearest to the current one first.
- [x] D. UI editor "Цвета" tab: a row has "Заменить" (the same picker, `set_colour`), "Автоматически" when set by hand, where the colour comes from in one line; "Исключить" becomes "Не гравировать" with a hint of what happens, an excluded row says "не гравируется"; a short explanation of the tab.
      The table on the work page uses the same words. The brush's "active colour" shows where the colour comes from.
- [x] E. Tests (targeted), README 0.16.0, version 0.16.0, REQ-051 and DEC-093 through the markview tools, deploy to 8765 after the commit; nothing pushed or tagged; full suite not run.

Review (0.16.0, 2026-10-20): the colours tab replaces a colour from the editor and says where each colour comes from and how stable it is (REQ-051, DEC-093); the LightBurn file of a vector work
carries MirrorY and writes both handles of every Bezier edge (REQ-052, DEC-094). Targeted run of 695 tests passed (editor and colour-map UI, palette, colormap, vector work, vectorize, ingest,
left behind, i18n, UI files, and neighbours); the full suite was not run. Deployed to 8765 before the run finished, at the operator's request (backup titanium-before-0.16.0-20261020T104412Z).
Warm timings: /api/colors 0.16 s, /api/vector/22 0.17-0.21 s, palette 0.19 s. Not pushed or tagged. The effect of MirrorY in the operator's LightBurn is confirmed only by a new export.

### 0.17.0 plan: photo engraving understood, and works that mix vector layers with photo engraving (operator goal, 2026-10-21) - written before the build
Operator's words: some works are "a mix: part vector, part photo engraving, one layer is the photo engraving"; (1) understand photo engraving: the kinds, their parameters, their
results, and a prediction of how an engraving will look at given settings ("a big piece"); (2) understand in experiments that part of a picture is photo engraving and part is fill.

#### Evidence (own analysis, read only, scripts in the scratchpad; the real app on 8765 only read, new pairs only on a COPY of the data)
- The operator's art folder (/Volumes/Storage0/Art/Laser, 27 files with a LightBurn project) holds 8 mixed works and 3 image-only ones. Image modes in use: grayscale (1500 dpi, Min 1-3 / Max 27-30 %,
  100-150 mm/s, 60 kHz, 300 ns; one at 2048 dpi 0-15 %), jarvis (2540 dpi, dot width 0.01 mm with dot correction, 25 %, 150 mm/s; 1100 dpi in Downloads/deploma.lbrn2), sketch (1100 dpi). The earlier
  survey (DEC-052) also names 3dslice, stucki and threshold. A mixed work = a cleaning rectangle + 7..20 colour fills (Scan) + ONE Image layer burned last (priority highest).
- The Image layer's bitmap covers a rectangle (Joker 152 x 152 mm) but only 70 % of its pixels are opaque: the transparent part is where the vector fills are. In deploma.lbrn2 three small
  sketch/jarvis bitmaps (60-85 % white) lie over the fills; in Sleeping Girl the 16 fills have output OFF and only the photo burns.
- DEFECT, measured on the operator's real works (check on a COPY, finished-work photographs without a chart): `_covered_by_later_layers` treats the whole bitmap rectangle as "engraved again by a later
  layer", so ALL 7 fills of the Joker and ALL 6 fills of "girl art deco" come out "100 % engraved again ... not measured"; only the photo layer gets one median colour. Geometry (first reading, superseded by the check in the Review below) said the fills lie
  under 0-3 % opaque pixels of the picture; that holds for the Joker, not for girl art deco, whose picture is a jarvis halftone over all the fills.
- Real photo-engraving pairs (93 Girl on a bike, 88 Motorcycle, 85 Inna-2; all grayscale) are aligned by the picture and give a tonal profile; the existing prediction (grayscale only) reproduces its own
  pair. Leave-one-pair-out on the two pairs that share one mode (same plate stock, speed 150, 60 kHz, 300 ns, 0.0169): power >= 16 % (dark tones) 1.2-2.9 dE; power < 15 % (light tones) 10-16 dE
  (L* 65-67 in one photograph, 75-82 in the other). It is NOT optical blur (sigma 0-0.8 mm tried), NOT a smooth illumination field (polynomial up to degree 3), NOT heat from the neighbourhood (mean grey
  over 0.5-16 mm): the cross-picture error stays 7-8 L* rms whatever is added. So two engravings at the same settings differ in light tones, and a prediction must show that spread instead of one line.
- The colours of a photo engraving are iridescent (gold, orange, violet, blue by power), not only a lightness ramp: the prediction already carries Lab per power; the descriptor "tonal" is a colour path.
- Nothing classifies photo against fill from the photograph; nothing writes `CutSetting_Img`; no plate engraves a grey ramp per mode (explore report, 2026-10-21).

#### Order (what the operator named first, and what blocks what)
- [x] A. Kinds of photo engraving, one catalogue (`photo_modes.py`, pure): per mode (grayscale, threshold, ordered, atkinson, dither, stucki, jarvis, newsprint, halftone, sketch, passthrough, 3dslice)
      its family, what the grey level controls (power / dot density / depth), the settings that matter, whether a pixel fires (transparent and, in binary modes, white never fire), what the platform can
      predict. `image_summary` carries it; the labels on the screens come from it (today `ordered` and `passthrough` are missing from the label maps).
- [x] B. Mixed works in experiments (blocks every real mixed work):
  - [x] B1. The area an Image layer really engraves (`fired` mask in mm: opaque pixels, mode rule) replaces the bitmap rectangle in `_covered_by_later_layers`; the vector fills under the transparent part
        are measured again. Fills under a pixel that fires stay "engraved again". Tested on synthetic files AND on Joker / girl art deco (before: 0 of 7 / 0 of 6 fills measured).
  - [x] B2. The composition of a file, pure and shown with every check: per layer its kind (cleaning, fill, line, photo tonal, photo depth), area, the share that shows in the end (not covered), the share
        of the picture area that is photo, fill, both-with-holes, nothing; the Image layer's own opaque share. On the review screen and the experiment screen.
  - [x] B3. Tonal profile on the visible opaque part only (transparent pixels excluded; regression on Girl on a bike: identical bins, rho 0.898). NOT built: one profile per bitmap object - every real Image layer
        has exactly one picture object (every real Image layer examined in this work), so there is nothing to split. Dithered modes give grey -> colour bins too: that is C2.
  - [x] B4. (decided against, with the numbers) What the photograph says about the kind: the spread (robust, L*) of each layer's visible area is reported next to the median; a fill that varies like a picture or a photo layer that is flat is named,
        with a threshold taken from the real works' numbers, not invented.
        Result: the spread is reported as information only. On the Joker a flat fill (fill 6, L-spread 6.4) varies MORE than the photo layer (5.5), so no threshold separates flat from tonal; a verdict
        would have been invented. The kind comes from the file (layer type and mode), which is exact; the photograph only says how stable a colour is.
- [x] C. Prediction of a photo engraving (C3 stays open)
  - [x] C1. A curve point keeps how far independent engravings disagree at that power (the 10-16 dE of the evidence above); the preview names the share of the picture in uncertain powers.
  - [x] C2. Dithered modes: the colour of a grey level is read from tonal profiles measured in the same mode and settings (no dither model needed); refused with the reason only when nothing was measured.
  - [ ] C3. Open until C1-C2 are measured on real data: a dot simulation for a mode never photographed (assumed, flagged); a photo-mode test plate (a grey ramp per mode) needs the Image-layer writer, so
        it needs the operator's yes (the file must open in LightBurn; the three real files are the reference for the structure).
- Not decided, needs the operator: (1) pure white in grayscale mode - does Min power fire on it? (the real photographs show no step at pure white; settled by a ramp plate, C3); (2) path shapes
  that sit on an Image layer (Lana Portrait: 12 outlines on C17) - does LightBurn engrave them? They are kept as they are and named in the composition.
- Tests while building: only the files touched; the full suite once before the release; deploy after a backup; "reload the page (Cmd+R)" in the report.

#### Review of 0.17.0
- Built: `photo_modes.py` (catalogue, strike rule), `composition.py` (the file by layers, shares fill / photo / both), the strike mask replacing the bitmap rectangle in the "engraved again" test, the
  tonal profile without transparent pixels, `photo.sample_spread`, the spread between independent engravings on every curve point and in the preview, transparent pixels blank in the preview,
  prediction of the dot modes from the tonal profiles of the same mode, the Russian table `ui/photo-modes.js` with a test that compares it with the catalogue, the composition card and the layer notes.
- On the operator's real works (copy of the data, read only): Joker 0 of 7 fills measured -> 7 of 7 (Lab in the report); the Image layer's colour L 48 -> 84 once the figure left its sample; girl art deco
  stays unmeasured and now says why (jarvis picture over all fills, dot density 48 %). Girl on a bike, re-checked as a new pair: identical tonal bins.
- Needs the operator's decision (not changed): (1) in one curve, flat-fill points and photo tonal points of the same mode disagree up to 39 dE (the Power x Speed plate against Girl and Motorcycle) - should
  flat fills stay in a photo-mode curve at all? (2) the assumptions: a plain shape on an Image layer strikes nothing; threshold cuts at mid grey; white is struck at Min in grayscale (documentation and
  forums, not measured); (3) a photo-mode test plate (a grey ramp per mode) needs an Image-layer LightBurn writer (C3).
- No real photograph pair in a dot mode exists in the database: that prediction is tested on synthetic works only and says so.
- Tests: full suite, 1494 passed, none skipped, serial 14 min 15 s (`.venv/bin/python -m pytest -q -rs`). `pytest-xdist` 3.8.0 was installed into `.venv` with the operator's approval (2026-10-21) and
  declared in the `dev` extra of `pyproject.toml`; the same 1494 pass on 12 workers in 2 min 32 s (`-n 12`). It is a development tool only: the app environment on 8765 does not get it.
- New tests: `test_photo_modes.py` (12: catalogue, strike rule, orientation, UI table equals catalogue), `test_mixed_work.py` (8), `test_dot_modes.py` (14: spread, transparency, dot-mode prediction,
  `sample_spread`). Changed on purpose: the dither-refusal tests (REQ-030 refused every dot mode, DEC-096 predicts seven of them), the mode record in the API test, the node harness of the experiment screen
  (it must load `photo-modes.js` and `composition.js`).

## 0.17.1: the work is found by any picture of the file and the ruler (REQ-055, DEC-097)

Operator, 2026-10-21 (voice-typed): pair 105 (`deploma.lbrn2` + `IMG_3307.DNG`): "Не смог найти картинку"; "исправь, чтобы находила диплом"; "достаточно найти один из слоев, все остальные ты можешь рассчитать ...
Важно, какой слой ты найдешь. НЕ важно"; "ты можешь ориентироваться на линейку ... масштабы, один из углов, плюс ... направление по линейке"; "он может определять тебе, в какой области искать любой из секторов
заливок"; "Это не просто линейка, а уголок".

- [x] A. Root cause, on the real files (copy of the pair through GET, scratch Store, nothing mutated): the check dropped every output-off layer before the alignment; the only active layer is a 25 x 23 mm seal
      (symmetric, ambiguous alone, picture route refuses), the outline route has no outlines, so the operator's four corners were fitted to the seal's bounding box (anisotropic 0.0104 / 0.0080 mm/px).
      Not a regression of 0.17.0 (REQ-050 / 0.15.1).
- [x] B. Evidence before design: the other layers ARE on the plate (template match of their pictures at 19.6 px/mm: eagle 0.49, seal 0.57, signatures 0.69 in one orientation, vertical flip), and the photograph shows
      a measuring angle (two rulers) with the plate in its inner corner.
- [x] C. `ruler.py`: scale from the 1 mm tick spectrum with its 5 and 10 mm ticks (chains of windows along a narrow strip, leakage and half-period handling), the inner corner and side of an angle.
- [x] D. `picturing.locate`: every picture of every layer (output-off included, `Layer.placed`), eight orientations, scale +-5 %, agreement of the pictures on the file's origin, ECC twice, one homography; the
      side of the angle first, the whole photograph if nothing is found there.
- [x] E. `ingest._locate_by_ruler` after the outline and largest-picture routes; the scale as read, doubled, halved; warnings; UI label; Russian translations.
- [ ] F. Not built, flagged: the ruler's direction as a rotation prior (strip edges were not stable on the real photograph; the search tolerates about 1.5 degrees instead); fill layers as templates (Q-029);
      the manual corners fitted to all layers (Q-028).
- [x] G. Tests, docs, release.

#### Review of 0.17.1
- Pair 105 in a scratch Store, full `check_pair`: method "picture at ruler scale", C05 measured Lab [60.3, 0.2, 6.5] at the seal (before: [72.6, 1.7, 13.8] at the wrong place); the overlay frame sits on the seal;
  the plate's lower-left corner of the cleaning rectangle falls within about 1.5 mm of the angle's inner corner (independent check). Ruler 19.64 px/mm against 19.67 fitted from the pictures; the three pictures
  agree within 0.13 mm; correlation after refinement 0.68 / 0.84 / 0.88.
- Real data, GET only (19 other pairs): the ruler is found on 15, absent (none reported) on 4. Where an accepted alignment gives the scale it agrees within 0.2-3.2 % (pairs 88, 90-93, 102); pairs 103 / 104 read
  half (the doubled scale is tried), pair 89 has the plate in a frame above the ruler's plane (1.5 times: not searched). Pairs 88 and 93 (colour portraits, aligned by the older route): `locate` refuses (correlation
  at the true pose 0.09 or below), so it cannot override them. No pair other than 105 has a picture the older routes miss; `locate` is validated on one real work and on synthetic ones, and says so.
- Needs the operator: (1) check pair 105 again with the automatic alignment (its stored check keeps the wrong frame); (2) Q-028 and Q-029.
- Cost: about 2 s for the ruler and 7-11 s for the search, only when every other automatic route has failed.
- Tests: full suite, 1518 passed, none skipped, 2 min 42 s on 12 workers (`-n 12`). New: `test_ruler.py` (7), `test_locate.py` (12), `test_ruler_alignment.py` (5, through `check_pair`), two assertions in `test_left_behind.py`;
  `tests/synth.py` gained a work of three pictures beside a measuring angle (`pictures_work`, `draw_angle`).

## 0.17.2: every layer the alignment placed is drawn; the version is in the header (REQ-055, REQ-056)

Operator, 2026-10-21, after 0.17.1 on the real pair 105 (re-checked, method "picture at ruler scale"): "В новой версии нашел только 1 картинку" (screenshot: one magenta frame on the seal; the eagle, the signatures
and every fill have none). Earlier: "Мне непонятно почему я не вижу версию апликации в header?" - answered (the version is only at `GET /api/version`, DEC-023), operator: "с версией согласен".

- [x] A. Root cause (confirmed on the stored check, GET only): the check found three pictures (C04 0.68, C05 0.84, C06 0.88) but `_draw_overlay` skips every layer flagged `left_out` (REQ-050), and the layers whose output is
      off carry that flag. Only C05, the one layer that is on, is drawn.
- [x] B. The overlay draws the layers of an alignment that was found by their pictures (`alignment.located`): output-off layers are drawn where the same transform puts them, in a colour of their own, not measured.
      Layers left behind stay undrawn (REQ-050). Without `located` nothing changes.
- [x] C. The note of a layer whose picture was found says so ("its picture is on the plate"), not "was not engraved": the photograph shows it was.
- [x] D. Judge the overlay on the real pair 105 by numbers and by looking: the outlines of the fills (text, cleaning rectangle) must lie on the engraved text.
- [x] E. The header shows `v<version>` next to the name (from `GET /api/version`, one request; nothing shown if it fails); Russian tooltip; UI test.
- [x] F. Tests, MarkView (REQ-056 for B-C and the version, DEC-098), README 0.17.2, lessons, version bump, release, deploy; tell the operator to reload (Cmd+R) and that the stored check needs no re-run (the overlay is redrawn from it).

#### Review of 0.17.2
- Real pair 105 (the stored check fetched with GET, the cached files, the working-tree code): the overlay now outlines all six layers. Edge strength under the outlines against the outlines shifted by -6..+6 px:
  C00 (97,649 outline px) peaks at dx -1, dy +1 px; C02 (25,975 px) at dx +2, dy -2 px; one pixel is 0.05 mm at 19.7 px/mm. The picture layers (C04-C06) have a bounding frame with no edge under it, so this
  measure says nothing about them; their position rests on the correlation after refinement (0.68 / 0.84 / 0.88) and the look of the overlay.
- New tests: `test_app_version_header.py` (4, node), seven in `test_ruler_alignment.py` (notes and warnings, overlay with and without `located`, left behind never drawn). `tests/ui_dom.js` got `classList.toggle`.
- The wording "this layer was not engraved" stays for a check that was not found by pictures (REQ-050); it is replaced only when pictures found the work.

### 0.17.3: the picture cache version (REQ-056)
- [x] After deploying 0.17.2, `GET /api/pairs/105/overlay.png?size=1400` answered in 0.01 s and the downloaded picture had 0 light-blue pixels (the working-tree drawing: 40,502): the render cache served the picture drawn by
      0.17.1, because `RENDER_VERSION` was not bumped when the drawing changed. Bumped to 2; a test keeps the version in the key; full suite and a fresh GET of the overlay on the deployed server are the proof.


## 0.18.0 plan: photo engraving is the fourth section; grayscale scales "grey -> colour" from the operator's data, confirmed by a grey-ramp plate; time of every work (operator goal, 2026-10-21)

Operator's words (voice-typed): "четвёртым пунктом была фотогравировка ... цветная гравировка мне вообще не нужна, потому что это и есть векторная работа"; "по моим данным, выбирая сеттинги фотогравировки,
видеть, как она будет выглядеть. И мои эксперименты должны это подтверждать"; grayscale: "все статичные, кроме мощности ... если эти основные сеттинги не вокруг чёрного цвета, а вокруг какого-то другого, то изменение
мощности меняет цвет ... научился понимать, какой серый создает какой цвет"; "считал ... скорость выполнения каждой работы ... 3 часа она делается или 15 минут"; "обрати внимание, какое должно быть расстояние между
точками ... такое же расстояние, как и для цвета ... grayscale вообще не получится ... я нашел 0.0169, но может быть есть более удобный вариант"; "да, делай писатель слоя Image и пластину".

#### Evidence (read only: the live DB opened read-only, GET on 8765; scripts in the scratchpad)
- One laser (JPT M7 60 W), one lens (F-Theta 174, field 170), three Grade 5 titanium records. Grayscale works: pairs 88 Motorcycle and 93 Girl on a bike (Big Plate, Min 1 / Max 30, 150 mm/s, 60 kHz, 300 ns,
  0.0169 mm = 1500 dpi, chart-corrected) form one mode ("Mode A", 31 tonal points, P 1.9-29.1); pair 85 Inna-2 (Test Plate, 5-16.1 %, 128 mm/s, camera-relative, 13 points).
- Mode A changes colour with power, not only lightness: pale gold (P 2-9, L 76-82 b 14-21) -> gold (P 12.8: 72/4/26) -> violet-neutral (P 18.2: 53/2.5/-1) -> dark brown-grey (P >= 23.7: 43/-1/5). Ends dE 25-33.
- Repeatability of Mode A (88 vs 93): dark half dE 1.2-2.9, light half 8-16.
- The fill row of the Power x Speed plate (pair 95) has EXACTLY the settings of Mode A. Grayscale pixel vs fill at the same power: dark (P 24-29) dE 1.4-6.2; middle (P 16-22) 15-21; light and gold (P 5-15) 6-36.
  A power factor does not explain it (best x1.1: still 12-17). So a grayscale scale is measured with grayscale engravings; fills are not a predictor (answers Q-026 with numbers; the operator's remark on
  the line interval says why).
- Nothing writes `CutSetting_Img`; no grey-ramp plate exists; no photo job or plate shows its total time; no real job duration is stored anywhere (estimates only, DEC-075, never timed).
- The operator's own Image layers (reference for the writer): `CutSetting_Img type="Image"` with minPower, maxPower, speed, frequency (Hz), QPulseWidth, interval, ditherMode, dpi (= 25.4 / interval, rounded);
  `Shape Type="Bitmap"` with W/H = mm of the PNG at its own pHYs dpi, XForm scale + centre, Gamma/Contrast/Brightness/Enhance*, File, SourceHash, Data = base64 PNG (L or RGBA).

#### Order (the operator's ask first; each step tested on its own files while building, the full suite once at the end)
- [x] A. Navigation: 1 Эксперименты, 2 Карта цветов, 3 Векторная работа, 4 Фотогравировка (new section), then the rest. "Цветная гравировка" leaves the menu; its address stays (plan pages link to it).
      The banded tonal / colour-path form and the old preview stay reachable from the section; their addresses keep working.
- [x] B. Grayscale scales (the core): a scale = one grayscale mode (laser, lens, titanium, speed, frequency, pulse, interval, passes) with its measured "power -> colour" points from grayscale engravings only.
      Per scale: the colour bar over its measured power span, the grey -> colour bar for the chosen Min/Max with grey numbers (0-255) and power, the table "which grey makes which colour", where each point
      was measured, and the confirmation by experiments: each engraving against the curve of the OTHER engravings (dE per power band). Fills of the same settings are shown beside as reference, not used.
- [x] C. Preview of a picture on a scale: a plain picture (PNG/JPG) or a LightBurn file; Min/Max sliders inside the measured span; side by side with the prediction; the engraving time for the chosen size;
      download a LightBurn file with the picture on an Image layer with exactly these settings (needs D).
- [x] D. The Image-layer writer: `CutSetting_Img` + `Shape Type="Bitmap"` (PNG with pHYs at the layer dpi), read back by our parser AND compared tag by tag with the operator's real Image files.
- [x] E. The grey-ramp plate ("Шкалы серого"): a plate type with markers and cleaning first; each tile one Image layer in grayscale mode with a horizontal 16-step ramp (steps at the measurement's bin centres,
      white on the left), its own settings; two axes chosen from speed, line interval, frequency, pulse width, passes (default rows = interval 0.0127 / 0.0169 / 0.0212 / 0.0254 mm = 2000 / 1500 / 1200 /
      1000 dpi, columns = speed around 150 mm/s); Min/Max power shared. Engraved -> photographed -> the existing check measures each tile as a tonal profile -> each tile becomes a scale. Proven end to end on a
      synthetic photograph of the plate (check, accept, the scale appears with the right colours).
- [x] F. "Which grey for this colour": a colour picture -> the grey picture whose grayscale engraving on the chosen scale comes nearest (each pixel to the nearest colour the scale reaches); preview and download.
- [x] G. Time of every work: the photo preview and the downloaded file, every plan and plate page (`engraving_time.estimate`), with what the estimate leaves out.
- [x] H. Docs (MarkView feature through the tools), README 0.18.0, version, lessons, full suite (-n 12), backup + deploy to 8765, check on the real app (GET only), report with "reload (Cmd+R)".
      Done 2026-10-21: REQ-059, REQ-060, DEC-100..102 through MarkView; README 0.18.0; lessons; 1545 passed (-n 12, none skipped) on the final tree; backup
      `backups/titanium-before-0.18.0-20261021T192658Z.sqlite` (integrity ok); wheel installed with its dependencies; 8765 answers 0.18.0. GET only: 2 scales, Inna + Boris 1.65 h,
      vector screen 3.11 h, overlay of pair 104 redrawn (4.1 s, then 0.008 s from the cache) with every shape outlined.
- Ids: requirement numbers are global across features in MarkView (REQ-058 is vector-detail's), so this release is REQ-059 (photo engraving) and REQ-060 (time);
  decisions DEC-100 (scales from grayscale engravings only), DEC-101 (time per piece of scan line, 1 ms), DEC-102 (shared VertList / PrimList).

#### Review (2026-10-21)
- Built: A-G as listed; tests `tests/test_grey_scales.py` (11), `tests/test_engraving_time.py` (+4), `tests/test_lightburn.py` (+1), UI and i18n tests; the framed-ingest acceptance became a module
  fixture (the witness test depended on another test's side effect and failed when pytest-xdist put them on different workers).
- Found while timing works: the reader did not follow LightBurn's shared lists (`VertID` / `PrimID`): 222 of 574 paths of Inna + Boris 9_backup were open lines with no area, 8 stored files affected
  (DEC-102). Fixed in `lightburn._shared_lists`; overlays redrawn (`RENDER_VERSION` 3).
- Time model timed against the operator's jobs (DEC-101): Inna + Boris about 3 h at 150 mm and 1.5-2 h at 100 mm. Counting pieces of scan line from the shapes (edge extent / 2 x interval) at 1 ms:
  150 mm 3.11 h on the vector screen, 2.9-3.3 h by the files; 100 mm 1.5-1.65 h. The old 0.3 ms with 10 mm lines gave 1.2-1.4 h for the 100 mm file.
- Real data (Mode A): confirmation median dE 10.2, not confirmed: dark half 1-3 dE, light half 10-16; 10 fills of the same settings differ by up to 33.8 dE (reference only).
- Full suite: 1545 passed, none skipped, 2 min 38 s on 12 workers.
- Open for the operator (answered with a default, not blocking): pure white at Min power (the plate's first step is white: the photograph decides); a convenient interval (the plate's rows decide: the one
  with the widest colour range and distinct steps); the pulse width 300 ns is not one of the laser's steps (250 / 350): the laser keeps the last valid one, so what these works really used is uncertain.
