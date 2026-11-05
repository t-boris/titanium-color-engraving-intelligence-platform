# UX P0: data guarantees, legacy documents and changed tests

Results of feature `ux-validation-p0`, REQ-003 (domain guarantees and compatibility of old documents) and the "tests aligned" part of
REQ-002. Protocol: `docs/validation/ux-p0-protocol.md`, sections 4 and 5. Date of every run below: 2026-11-05.

What was run against what: the working tree on top of commit `c89b339` (release 0.38.1) with the work of the nine `ux-*-p0` features
not yet committed. Tests ran in pytest with the real FastAPI application over a real workshop directory (`TestClient`); screens ran in
node over the fake DOM of `tests/ui_dom.js`. **That DOM is not a browser**: whatever needs a real layout, focus order, keyboard handling
by the browser, pointer geometry or a screen reader is listed in section 5 and is not claimed anywhere else.

No product code was changed to produce these results. The only edit of an existing test file made for this document is one fixture in
`tests/test_preview_feedback.py` (section 4, finding F-1).

## 0. Summary

| | |
|---|---|
| Guarantees checked | 9 (section 1); all hold |
| Guarantees found broken | none |
| New tests | 24: `tests/test_ux_guarantees.py` (13), `tests/test_ux_legacy_documents.py` (11) |
| Legacy document kinds | 4 (artwork, photo in stripes, photo-preview, photo work) plus the old route table; each is created, reopened and exported as before (a photo-preview keeps nothing, section 2) |
| Changed tests found weakened or deleted | none (section 4); one narrowed comparison (`test_findings.py`) is named and compensated by a new test |
| Finding F-1 | one existing test (`test_preview_feedback.py`) failed on a stale fixture, not on a broken guarantee; fixture fixed |
| Finding F-2 | the two halves of the palette guard of the photo-engraving screen were not told apart by any test; closed: each half now fails a test of its own (section 1, G3) |
| Last run of everything cited | 2026-11-05: **662 passed, 0 failed, 0 skipped** in 434 s (30 test files, `-n 4`, tree as of that run; 660 before the two tests of F-2 were added) |

Command (from the repository root; no test may be skipped, node must be installed):

```
.venv/bin/python -m pytest tests/test_ux_guarantees.py tests/test_ux_legacy_documents.py tests/test_scale_palette_context.py \
  tests/test_photo_works.py tests/test_photo_engraving_ui.py tests/test_save_feedback_ui.py tests/test_creation_ui.py \
  tests/test_pair_review.py tests/test_lifecycle.py tests/test_lifecycle_traced.py tests/test_lifecycle_ui.py \
  tests/test_lifecycle_screens.py tests/test_photo_review_ui.py tests/test_photo_results.py tests/test_picture_tone.py \
  tests/test_preview_feedback.py tests/test_remeasure.py tests/test_vector_rename.py tests/test_vector_work.py \
  tests/test_vector_editor_ui.py tests/test_vector_workspace_ui.py tests/test_work_review.py tests/test_discrete.py \
  tests/test_continuous.py tests/test_prediction_api.py tests/test_ui_foundation.py tests/test_work_catalog_ui.py \
  tests/test_vector_zone_dots_and_tone.py tests/test_grey_scales.py tests/test_findings.py -q -rs -n 4
```

The whole suite was not run for this document. Another run, a few minutes earlier on a tree that other agents were still changing, had one
failure that is not a finding about a guarantee: `test_vector_editor_ui.py` expected the first fold of the file tab to be «Важные области»
while a fold «Путь файла и прогноз» was being added above it; that test was updated by the feature's own work and passes in the run above.

## 1. Domain guarantees

"Bites" means: a deliberate defect was put into a throw-away copy of the source (never into the repository) and the named test failed.
A test is listed as "cited" when it was read and asserts the guarantee but no defect was tried against it.

| # | Guarantee | Tests (`file::name`) | Result 2026-11-05 | How it was shown to hold, and notes |
|---|---|---|---|---|
| G1 | The picture is kept when the scale changes (BUG-002) | **new** `test_ux_guarantees.py::test_a_scale_a_width_and_an_undo_keep_the_stored_picture_unchanged`; cited `test_photo_works.py::test_another_scale_keeps_the_picture_and_takes_its_measured_span_and_every_change_is_saved`, `test_photo_works.py::test_undo_brings_back_another_scale_with_its_min_and_max`, `test_photo_engraving_ui.py::test_another_scale_is_saved_in_the_work_the_picture_stays_and_min_and_max_become_the_new_scales_span` | pass | The old tests check the derived preview and the size, not the stored file. The new test compares the bytes of the work's picture, its stored path, name and size through another scale, another width, going back, three undos and a copy. Bites: a scale change that forgets the picture's name fails the new test only (all 76 tests of `test_photo_works`, `test_photo_engraving_ui` and `test_picture_tone` still pass with that defect); a scale change that overwrites the stored file fails the new test and, by accident, one old test. The UI test shows the screen sends only the scale and shows the stored preview. |
| G2 | The card and the prediction use the one palette of the current width (BUG-002, BUG-011) | **new** `test_ux_guarantees.py::test_the_list_the_detail_and_the_prediction_of_a_work_read_the_palette_of_its_current_width_also_after_an_undo`; cited `test_scale_palette_context.py::test_the_scale_list_uses_the_requested_size_instead_of_the_default_short_colourful_probe`, `::test_the_api_lists_scale_colours_at_the_same_width_as_the_picture_detail`, `::test_a_zone_selected_card_matches_the_preview_colours_unknowns_and_updated_power_range`, `::test_a_photo_work_reloads_choices_on_resize_and_uses_the_detail_for_its_selected_card` | pass | The new test checks, at 60, 120 and 90 mm and after two undos, that the list, the detail and the work's own prediction name the same selection of measured sizes (not only the same number) and that the card draws the colours of the detail. Bites: a list that ignores the width fails it, and so does a work whose own prediction reads the sizes of a fixed width. |
| G3 | A late or stale answer does not cancel a resize or an undo (BUG-002, BUG-011) | cited `test_scale_palette_context.py::test_a_late_palette_response_for_a_resized_work_cannot_overwrite_its_undo`, `test_save_feedback_ui.py::test_a_late_answer_never_marks_a_newer_change_saved_or_replaces_it`, `::test_overlapping_width_changes_on_a_work_show_saving_until_the_last_answer`, `test_photo_engraving_ui.py::test_changes_are_sent_one_after_another_in_their_order_and_the_last_one_is_shown`, `test_creation_ui.py::test_cancelling_the_change_dialog_saves_nothing_and_a_late_answer_for_an_earlier_choice_is_dropped`; **new** `test_ux_guarantees.py::test_a_late_palette_answer_for_an_older_width_cannot_replace_the_palette_of_its_current_width`, `::test_a_late_answer_of_an_older_request_for_the_same_width_cannot_replace_the_answer_of_the_newer_one`, `::test_an_answer_for_a_width_the_work_has_left_while_its_changes_were_still_on_their_way_is_dropped` | pass | The save-state tests prove the queue and the "saved" mark. They do not prove the palette guard of the photo-engraving screen (`photo-engraving.js`: `if (scalesRequest !== request \|\| view.width_mm !== width) return;`): with that line removed, all 119 tests of `test_scale_palette_context`, `test_photo_engraving_ui`, `test_save_feedback_ui` and `test_creation_ui` still pass. The line holds two conditions, the identity of the request (`scalesRequest !== request`) and the width of the work (`view.width_mm !== width`), and each has a test of its own. (a) The list for 120 mm is asked and held, the work goes to 90 mm and back to 120 mm (a second list for 120 mm is asked and answered), then the first answer arrives: the width is the same, so only the identity of the request tells it is the older answer, and the card must keep the answer of the newer one. (b) The list for 120 mm is held while two changes of the width (80 mm, 90 mm) are sent one after another; the answer for 120 mm arrives when the first of them is answered, the work is 80 mm, but the screen is drawn again only after the last answer, so the request is still the newest and only the width tells the answer is for a width the work has left: it must be dropped and no list may be asked for 80 mm. The first of the three new tests (an older width after a resize) fails only when both halves are removed. Mutations in a throw-away copy: both halves removed, fails the older-width test and (a) and (b); only the width half kept (`if (view.width_mm !== width) return;`), fails (a) only; only the request half kept (`if (scalesRequest !== request) return;`), fails (b) only; the unchanged line, all three pass. With either half removed alone, the 119 earlier tests and the older-width test still pass. node over the fake DOM only: the real timing of two answers needs a real browser. |
| G4 | Cancelling or undoing puts back the size and the settings | **new** `test_ux_guarantees.py::test_undoing_a_resize_puts_back_the_size_of_the_exported_file_and_its_picture`; cited `test_photo_works.py::test_every_change_of_what_the_work_engraves_is_undone_and_redone_one_step_at_a_time`, `::test_a_new_change_after_an_undo_drops_what_could_be_redone_and_a_change_to_nothing_is_no_step`, `test_vector_work.py::test_undo_and_redo_bring_the_size_and_the_markers_back_with_the_split_version`, `test_photo_engraving_ui.py::test_undo_and_redo_in_the_head_bring_the_work_back_with_its_min_and_max_and_follow_ctrl_z`, `test_save_feedback_ui.py::test_an_undo_that_fails_is_not_offered_again_and_the_work_can_be_read_from_the_server`, `test_creation_ui.py::test_cancelling_the_change_dialog_saves_nothing_and_a_late_answer_for_an_earlier_choice_is_dropped` | pass | The setting alone is not the guarantee. The new test writes the LightBurn file, resizes, undoes and writes it again: the size and the bitmap are equal to the first file byte for byte, and redo gives the larger one again. Bites: an undo that does not put back `width_mm` fails it. The old step test also fails on that defect, so the new test's addition is the check at the level of the file written. |
| G5 | The preview agrees with the LightBurn export | cited `test_photo_works.py::test_the_file_is_the_picture_the_preview_shows_at_the_layers_resolution`, `test_picture_tone.py::test_the_tone_lightens_or_darkens_the_dots_in_the_look_and_in_the_file_alike`, `::test_grayscale_adjusts_its_own_and_colour_matched_greys_in_the_preview_and_export`, `test_vector_work.py::test_the_file_cleans_first_has_one_layer_per_recipe_with_its_full_settings_and_gapless_closed_regions`, `test_preview_feedback.py::test_vector_preview_uses_the_recipe_fill_order_and_matches_the_export` | pass | Photo work: the test decodes the bitmap in the file, draws the preview's picture through the same grey table and requires the two to agree (median error under 2, 90th percentile under 8 in L\*a\*b\*). Bites: a file made at a narrower power range than the preview fails it. Vector work: each layer of the file has the name, power, speed, line interval, frequency and region count of the layer the screen shows. No new test was needed. The preview is not the laser's burn: nothing here claims the colour on titanium, only that the file is what the screen promised. |
| G6 | The assessments of colour and of photo engraving are independent | **new** `test_ux_guarantees.py::test_the_colour_verdict_and_the_photo_verdict_of_a_layer_are_two_marks_and_neither_overwrites_or_stands_in_for_the_other`; cited `test_photo_results.py::test_colour_success_does_not_turn_a_failed_photo_layer_into_a_success`, `test_photo_engraving_ui.py::test_a_lightburn_marker_has_independent_colour_and_photo_assessments`, `test_lifecycle_ui.py::test_the_colour_and_the_photo_assessments_are_separate_sections_and_neither_stands_in_for_the_other` | pass | The old tests mark the photo first and the colour second. The new one uses the other order and re-marks each aspect: a bad colour does not make a good photo engraving bad or take it off the recommended ones, a withdrawn colour verdict leaves the photo's, and each aspect is its own stored row. Bites: a colour mark stored as the photo's fails it. |
| G7 | Files, measurements and their history are kept, also after the lifecycle and photo-review changes | **new** `test_ux_guarantees.py::test_every_file_a_work_handed_out_stays_as_it_was_after_an_edit_a_repeat_export_and_a_restart`, `::test_attaching_another_lightburn_file_to_a_pair_keeps_the_file_it_replaced`, `::test_the_derived_review_of_a_pair_is_never_stored_with_its_measurements`, `::test_the_advice_on_a_finding_is_worked_out_when_it_is_read_and_never_stored_with_its_run`, `::test_the_acceptance_gate_refuses_in_every_state_the_gate_of_0_38_1_refused_with_the_same_words`; cited `test_lifecycle.py::test_reopening_the_application_keeps_the_chain`, `::test_an_edit_after_a_verified_file_starts_again_from_prepared_and_the_files_keep_their_stages`, `::test_new_measurements_move_the_current_prediction_and_never_rewrite_what_an_exported_file_promised`, `::test_a_review_made_before_the_basis_was_named_gets_it_from_its_own_fields_and_is_not_rewritten`, `::test_measuring_the_engraving_again_after_a_later_export_keeps_the_file_it_was_compared_with`, `test_remeasure.py::test_the_same_engraving_keeps_one_accepted_photograph_and_the_old_rows_stay_in_the_history`, `::test_a_measurement_that_does_not_come_out_whole_leaves_the_old_one_untouched`, `::test_a_check_that_finds_problems_keeps_the_old_measurement_and_names_them`, `test_pair_review.py::test_acceptance_after_going_back_keeps_the_provenance_the_measurement_rules_and_the_engraved_version`, `::test_rejecting_an_accepted_pair_keeps_its_observations_in_the_audit_history`, `::test_the_refusals_of_accept_pair_read_as_they_always_did`, `test_preview_feedback.py::test_comparison_of_an_old_engraving_keeps_its_exported_split_size_and_smoothing_after_edits`, `test_vector_rename.py::test_a_file_exported_before_keeps_its_name_and_the_next_one_gets_the_new_name`, `test_findings.py::test_a_later_run_recalculates_while_earlier_findings_stay_readable_with_their_run_and_inputs` | pass | The new file tests compare the bytes of every file handed out (three exports with edits between, again after a new application process is started over the same data directory) and of the photograph pair's replaced LightBurn file. The review of a pair and the advice on a finding are derived on every read; the tests check neither is written into the stored data. The gate test replays 576 combinations of pair states against a copy of the gate of 0.38.1 and requires the same refusal in the same words; its one deliberate difference is that a confirmation given for other differences than the current ones no longer counts (`pair_review.FILE_DIFFERS`). Bites: a repeat export that removes or rewrites an earlier file, a list that loses a record, a replaced file that is deleted, a stored review, a stored advice, a gate that forgets the mask review or a problem of the check: each fails. |
| G8 | Undo and redo step through every change of a work one step at a time | cited `test_photo_works.py::test_every_change_of_what_the_work_engraves_is_undone_and_redone_one_step_at_a_time`, `test_vector_work.py::test_undo_and_redo_step_through_paints_and_merges_with_their_split_versions`, `::test_undo_and_redo_cover_the_titanium_merge_among_the_four_kinds_of_operation_the_requirement_names`, `::test_undo_brings_back_the_tolerance_and_the_filters_with_the_colouring`, `test_vector_editor_ui.py::test_undo_and_redo_answer_ctrl_z_and_ctrl_shift_z_only_while_the_editor_is_on_screen_and_no_field_has_the_focus`, `test_lifecycle.py::test_a_replacement_of_a_current_colour_is_undone_by_one_undo_and_neither_touches_the_files_already_made` | pass | Read, not mutated. The first test goes through four changes of a photo work (Max power, width with the colour choice, a rule of a part, the AI's answer) and back, then forward again, and refuses a step beyond either end with a message. The real keys are not pressed: the node test calls the handlers (section 5). |
| G9 | A full re-segmentation needs its own confirmation | **new** `test_ux_guarantees.py::test_splitting_again_changes_nothing_until_it_is_confirmed_and_cancelling_changes_nothing`; cited `test_vector_work.py::test_an_area_dragged_on_the_picture_is_sent_in_picture_pixels_when_split_again`, `test_vector_workspace_ui.py::test_the_split_colours_the_colour_settings_and_the_ai_description_are_checked_before_anything_is_asked_or_sent` | pass | The new test presses «Разбить заново» and finds the question «Разбить картинку заново?» with the focus on «Отмена»; «Отмена», the cross and Escape each leave zero requests to `/split`; confirming sends exactly one. Bites: removing the question fails the new test and also the cited drag test (it counts the POSTs before the confirmation). The focus is the fake DOM's `activeElement`; a real focus ring needs a real browser. |

The 9 rows hold. Nothing in them states a physical limit, a power or a speed of the laser: the sizes and settings are the ones the tests
chose.

## 2. Legacy documents (protocol section 5, research n50)

"Old" is defined by evidence. `tests/fixtures/legacy_0_38_1/` holds what release 0.38.1 (commit `c89b339`, run from `git archive` in a
separate directory) stored and wrote: `stored_plans.json` is the key set of every stored plan; `photo_work.lbrn2` and `picture.lbrn2` are
files it wrote. The files that write an artwork, a stripes plan and a photo work (`conversion.py`, `plans.py`, `photo_work.py`) are
unchanged since that release, so a document made today is stored exactly as one made then. The one difference is the list of files
handed out (`exports`), which 0.38.1 did not keep: a plan only became "Exported". The tests therefore make an old exported plan with the same
endpoints and take that record out, which is what 0.38.1 left in the database; the first test below proves the two key sets are equal.

| Document | UI route | Create (through the HTTP API) | Reopen | Export | Result 2026-11-05 |
|---|---|---|---|---|---|
| Artwork, a picture engraved in colours | `#/artwork` | `test_ux_legacy_documents.py::test_artwork_with_colours_the_laser_cannot_reach_is_blocked_until_each_is_replaced_or_excluded_then_exports_and_reopens` creates it with an unreachable colour: it stays a draft, cannot be finalised and has no file, and the refusals change nothing stored | `::test_an_artwork_plan_exported_by_0_38_1_reopens_with_one_unnumbered_file_and_exports_again_as_file_1`: status "Exported", one unnumbered file with unknown date, palette, source image and banding picture still served | same test: the same layers, settings and areas as before; from then on it is file 1; an edit takes it back to a draft and it is finalised and exported like a new one | pass |
| Unreachable colours block the plan until replaced or excluded | `#/artwork` | `::test_artwork_with_colours_the_laser_cannot_reach_...` | the same test reopens the exported plan | an excluded colour is not in the file; a replacement colour is; an unknown replacement is refused | pass |
| Photo in stripes, tonal | `#/photo` | `::test_a_stripes_photo_is_made_with_its_band_count_tiles_the_picture_exports_a_layer_per_band_and_reopens` (also `::test_the_stripes_band_count_is_limited_by_the_layers_lightburn_has_and_the_limit_is_told`) | same test | a layer per band; the file carries `band_count` bands | pass |
| Photo in stripes, along a colour path | `#/photo` | `::test_a_stripes_photo_along_a_colour_path_keeps_the_operators_order_and_a_revision_leaves_the_plan_it_revises_alone` | same test | same test | pass |
| Photo in stripes exported by 0.38.1 | `#/photo` | made by the previous test's endpoints | `::test_a_stripes_photo_exported_by_0_38_1_reopens_with_its_band_count_and_exports_again` | exports again | pass |
| Photo-preview, forecast of a LightBurn file made elsewhere | `#/photo-preview` | `::test_files_made_by_0_38_1_are_forecast_drawn_again_at_other_min_and_max_and_keep_nothing`: the two files of 0.38.1 are uploaded; `::test_the_file_0_38_1_made_for_a_photo_work_is_forecast_as_the_file_made_today_is` | the kept upload is drawn again at other Min and Max without a new upload | the picture it draws; **a forecast keeps nothing**, so there is no stored document to export or reopen, and the test checks that no record appears | pass |
| Photo work | `#/photo-engraving` | `::test_a_photo_work_is_stored_as_0_38_1_stored_it_reopens_and_exports_through_its_own_routes` | same test | its own routes (`/api/photo-works/...`) | pass |
| Premise: stored form | | `::test_a_plan_made_today_is_stored_with_the_keys_0_38_1_stored_and_an_export_only_adds_the_record_of_the_file` | | | pass |
| Old addresses | all of the above | | `::test_every_old_address_of_a_screen_is_still_drawn_by_the_screen_it_always_belonged_to`: the real `index.html` scripts in node, each screen replaced by a recorder; 24 addresses, among them `#/artwork?plan=12`, `#/photo`, `#/photo-preview?pair=3`, `#/photo-engraving?work=7`, `#/vector?new=1&classic=1`, `#/plans/9`, `#/knowledge`, an unknown one; the screen, its argument and the menu section marked current are checked | | pass |

Defects tried against these tests, each caught: a plan that ignores unreachable colours, a draft that exports, no placeholder file for an
old exported plan, an export that is not recorded, a `band_count` that is not saved, the photo-preview address no longer routed or losing its menu section,
a new key in a stored plan, a revision that rewrites the plan it revises, a forecast that stores a record, a forecast that changes the power range of the old
file, an exclusion that is ignored when the colours are matched. (The first attempt at a forecast defect, a changed format version, was ignored by the parser and
proved nothing; it was replaced by the last two.)

**Cross-release check (once, not part of the suite).** On 2026-11-05 a workshop directory was made by release 0.38.1 itself (three plans:
an artwork, a tonal stripes photo and a colour-path photo, all "Exported", none with an `exports` list) and opened by the current code. All
three opened; exporting each again gave file 1. It was done with a throw-away script outside the repository; the fixture and the tests above
are what stay.

What is not covered by an automated legacy test: a photo work already exported by 0.38.1 in a real old workshop (it is covered by the
stored-form test, not by an old directory), and documents of releases before 0.38.1.

## 3. Reading the guarantees: what the tests cannot see

* A test that passes is not proof of a guarantee; a defect has to fail it. For G1 (the picture's name forgotten) and G3 (the palette guard
  removed, whole or either half) the existing tests passed with the guarantee broken, which is why the new tests for G1 and G3 were written; for G4 and G5 the
  existing tests already failed on the defects tried, and the new G4 test only adds the check at the level of the file. The "how it was
  shown" column says which defect each test catches. Defects not tried are not claimed.
* The advice on a finding and the review of a pair are derived on read. `test_findings.py` compares an earlier run with itself ignoring
  `remedies` and `recommendation` (section 4); that is sound only while the stored rows hold neither, which the new G7 tests check.

## 4. Tests changed by the nine features (REQ-002, criterion 3)

Changed tracked files: **28**, +1009 / -154 lines (`git diff --stat -- tests/` shows 29 files, +1010 / -154; the extra file and line are the one-line fixture
of F-1 below). The other agents were still editing the tree while this was written; the numbers are from 2026-11-05.

Class (a): updated to a named new requirement. Class (b): harness only (script lists, selectors, helper stubs). Class (c): a domain
assertion weakened or deleted. **No file has a change of class (c).**

| File | What changed and why | Class |
|---|---|---|
| `tests/ui_dom.js` | The fake DOM learns focus loss on removal, `contains`, `blur`, `getElementById`, and loads `forms.js` and `terms.js` after `app.js` as `index.html` does | b |
| `test_analysis.py` | Loads `lifecycle.js`; one added assertion: the report explains «пара» and «основание» | b, a (save-feedback REQ-003) |
| `test_app_version_header.py` | The version label is now followed by the task panel's entry before the user chip; the regular expression still fixes the order | a (save-feedback REQ-002) |
| `test_color_map_one_screen.py` | Plane buttons ◀ ▶ added to the expected list; the sources fold is found by its class because a second fold exists | a (accessible-layout REQ-001), b |
| `test_colour_model_ui.py` | Signals first and the figures in a closed fold; the facts «Цвет» and «Параметры» swap; the history is a list of one line per event, newest first (the old row count of 3 included the table header, now 2 events); the evidence "480, 481, 482" became "Номера наблюдений: 3" plus three links to the photographs, which the new assertion checks by text and address; two new tests | a (evidence-summaries REQ-001, growing-collections REQ-002 and REQ-003) |
| `test_conversion_ui.py` | Source-text assertions on the export button and the file fetch moved from `vector.js` to `lifecycle.js` (`disabled: !r.ready`, `I18N.tr(r.reason)`, one place that fetches a file). The behaviour is covered by `test_lifecycle_ui.py` | a (lifecycle REQ-001, REQ-002) |
| `test_experiment_screen_ui.py` | The link «Скачать .lbrn2» is now the button «Скачать LightBurn» with the readiness; the old address assertions are replaced by six tests that check the request path (`/api/plans/22/export.lbrn2`, `/api/photo-works/28/export.lbrn2`), the saved name and the reload | a (lifecycle REQ-001, REQ-002) |
| `test_experiments.py` | Source labels renamed to the one wording «Скачать LightBurn» and the chain | a (lifecycle REQ-001) |
| `test_experiments_screen_ui.py` | The material is the stock selector, no longer a drop-down; `PlateDialog.open(devices, null, reload)`; one new test for a long list of supporting observations | a (growing-collections REQ-001, REQ-002), b |
| `test_findings.py` | The "earlier run is not rewritten" comparison now ignores `recommendation` as well as `remedies`. **Narrowed comparison, compensated:** the new `test_ux_guarantees.py` test proves the advice is never stored with the run | a (evidence-summaries REQ-002) |
| `test_findings_screen_ui.py` | The screen is built as decisions: one recommended step first, the other remedies in a fold (the three old remedy lines are still asserted, now two in the fold and the third as the step); the photo queue comes from `/api/analysis/photo-queue` instead of `/api/photo-knowledge/everywhere`; the opened card gains «Открыть основания»; a new test for the schedule interval | a (evidence-summaries REQ-002, save-feedback REQ-003) |
| `test_i18n_coverage.py` | The history code moved to `knowledge-history.js` | a (growing-collections REQ-002) |
| `test_lettering_ui.py` | The blocked-inscription reason appears three times instead of two (tab, beside the export, in the words of the check); the stub gains `lifecycle` | a (lifecycle REQ-001); stricter |
| `test_photo_engraving_ui.py` | A refused width keeps the typed `0`, shows the stored preview (`?v=3`), and the error stays beside the work with what was typed and what is stored; an empty AI wish is told as «Заполните это поле» beside the box (the AI is still not asked); one new test for the download | a (save-feedback REQ-001, REQ-003; lifecycle REQ-001) |
| `test_photo_preview_ui.py` | The titanium is the stock selector | a (growing-collections REQ-001), b |
| `test_plan_screen_ui.py` | «Экспортировать в LightBurn» is now «Скачать LightBurn» with the readiness; three new tests; the stub gains `lifecycle` | a (lifecycle REQ-001) |
| `test_ui_cloud.py` | Boxes are found by their visible label; one new test for the withdrawal form | b, a (save-feedback REQ-003) |
| `test_ui_files.py` | Script load order for the new files; the menu has «/works» fifth | a (work-catalog REQ-001), b |
| `test_ui_gaps.py` | The lens form sends `v.spot` of the form helper; the layer field is named by its visible label «Проходы, слой «C00»: нет в файле»; the review stub gains `review` | b, a (save-feedback REQ-003, photo-review REQ-001) |
| `test_ui_labs.py` | The own titanium is the stock selector; the classic form of a new vector work is opened with `classic=1`; the name is required | a (growing-collections REQ-001, work-creation, save-feedback REQ-003), b |
| `test_ui_network.py` | Loads `forms.js`; one new test for the port and the cloud address | b, a (save-feedback REQ-003) |
| `test_ui_workshop.py` | Fields found by their label; `confirm: v.word` | b |
| `test_vector_editor_ui.py` | A fold «Путь файла и прогноз» under the head is now the first fold, so the existing fold assertions apply from the second (none dropped); the file tab folds the recipe and the files made before; a button «Выбрать области» is new on every colour line; `export_blocked` is read through `lifecycle.readiness`; one new test (Min above Max) and one added assertion (a power outside 0..100) | a (accessible-layout REQ-001, lifecycle REQ-001, save-feedback REQ-003) |
| `test_vector_form_ui.py` | The classic form is reached with `classic=1`; the name is required; the work is remembered as the next choice; the tolerance is told beside the box; one new test for each box | a (work-creation, save-feedback REQ-003) |
| `test_vector_work.py` | «Создать файл LightBurn» is «Скачать LightBurn»; the disabled state follows `lifecycle.readiness.ready`, which must equal `export_blocked is None`; the failure stays beside the button with «Повторить»; the form reads the algorithm once | a (lifecycle REQ-001, save-feedback REQ-003) |
| `test_vector_workspace_ui.py` | A blank or refused name is told beside the field, not in a toast, with the typed text kept; the size dialog names its boxes by their label; three new tests | a (save-feedback REQ-003) |
| `test_vector_zone_ui.py` | Loads `evidence-summary.js` | b |
| `test_work_review_ui.py` | «обещанных» became «ожидаемых», «Обещано» became «Ожидали» (one wording for the comparison); the stock selector in the upload form | a (lifecycle REQ-003), b |

Narrowed or reworded assertions that were looked at because they could hide a loss, and why they do not: the findings comparison (above);
the three source-text assertions of `test_conversion_ui.py`, which point at the new file and are backed by behavioural tests in
`test_lifecycle_ui.py`; the empty-wish message of `test_photo_engraving_ui.py`, whose "the AI is not asked" count is unchanged; the evidence
numbers of `test_colour_model_ui.py`, which are now asserted as links. A source-text assertion that a button is disabled by a name
(`"disabled: !r.ready"`) does not prove the behaviour; the behaviour is proved by the lifecycle tests.

Untracked new test files, by count only: **29 files, 457 test functions** written by the nine features (`git status --short tests/`),
plus 2 helper modules (`growing_ui.py`, `lifecycle_stub.py`). This validation adds 2 test files, 24 tests and one fixture directory.

### Findings

* **F-1.** `tests/test_preview_feedback.py::test_photo_review_explains_the_wrong_export_and_the_actual_tones_in_the_ui` failed with
  `TypeError: Cannot read properties of undefined (reading 'kind')`. The review stub written by hand in the test has no `basis`; the screen
  (`vector-review.js`, `resultBlock`) now reads `r.basis.kind`, and the work's view always names the basis, also for reviews saved before it was
  named (`vector_job.py`: `reviews=[{**r, "basis": lifecycle.basis_of(plan, r)} ...]`). The test fixture was stale, not the guarantee. One line was
  added to the stub; the test passes and still asserts the same texts. The file was not among those changed by the nine features.
* **F-2 (closed).** The palette guard of the photo-engraving screen holds two conditions, and removing either one alone passed every test. Two
  tests were added (section 1, G3), one for each half; with a half removed in a throw-away copy, the test of that half fails and the other passes.
  The product code was not changed.

## 5. What only a real browser or Electron can prove

None of the following is claimed by any result above.

| Not proved | Why node over the fake DOM cannot |
|---|---|
| Layout, wrapping and overflow at a narrow or low window, the sticky head and the scroll of a column | the fake DOM has no layout; `getBoundingClientRect` returns a constant |
| Tab order, the visible focus ring, focus returning after a dialog closes, a focus trap | `activeElement` is a field of the fake DOM; the browser decides what takes the focus |
| A screen reader announcing `aria-live`, `role="alert"`, labels and descriptions | no accessibility tree |
| Real Escape, Enter, Ctrl+Z and Space reaching the handler once a field or a dialog has the focus | the tests call the handlers; key repeat, IME and the browser's own shortcuts are not exercised |
| Pointer drag, a lasso, a pointer capture, wheel and pinch, touch | events are synthesised without geometry |
| The back button, reload on a route, a bookmarked address, the order of two real network answers | there is no history stack or real latency; the late-answer tests order the answers by hand |
| The Electron window: the shell, its log and window self-check (0.38.1), the file picker, the download dialog | no Electron; `Blob` and `a.click()` are stubs |
| How a titanium colour looks on the screen and on the metal | not a software property |

Nothing in sections 1 to 4 would change if these were checked; a failure there would be a new finding.
