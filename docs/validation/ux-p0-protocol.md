# UX P0 validation protocol (release 0.39.0)

Feature `ux-validation-p0` (REQ-001..003, plan I-1..I-6). It says how the nine P0 UX features are checked, with what, and what has
**not** been checked. Results are recorded in [ux-p0-results.md](ux-p0-results.md); this file is the protocol and does not change when a
check is run.

Rules of the record (research n55–n58):
- An **observation** is something a check produced on a named build on a named date. A **hypothesis** is what the redesign is expected to
  do. The two are never mixed in one sentence. No number in this record is an improvement claim.
- A check has one of four states: `passed` (with where: node test name, browser, Electron), `failed`, `not executed` (with why),
  `not applicable`. Static reading of code is not a state of a check.
- Loads of 20 / 200 / 2000 records are **synthetic test workloads**. Nothing here says how large the operator's database is.
- Numeric targets (seconds, number of steps) are chosen **after** the baseline below has been taken. None is set in this protocol.

## 1. Before / after protocol (REQ-001, plan I-1)

Same tasks, same operator-visible starting state, on two builds: **before** = 0.38.1 (the installed desktop app, or the wheel of tag
`v0.38.1` on a throw-away workshop), **after** = 0.39.0. Use a rehearsal copy of the workshop (never the live one):
`sqlite3 .backup` of `titanium.sqlite` (read-only), `cp -Rc` of `files/` and `fonts/` (not `ai/`), a free port, its own browser tab.

| id | task (research n56) | start state | success without a hint means |
|---|---|---|---|
| T1 | continue a saved work | catalog/menu, a work exists | the work is open in its editor with its own saved context |
| T2 | create a work from an image | an image file, a size in mm | a saved work with the chosen result, without entering equipment twice |
| T3 | pick a better colour | an open work | the colour is changed, undo returns it |
| T4 | add a lettering and a photo zone | an open work | both present and exportable |
| T5 | download the LightBurn file and accept the result | a prepared work, a photograph of the engraving | file downloaded, photo accepted, back at the work with the summary |
| T6 | find the cause of a discrepancy | a finding in the queue | the person says which photograph/measurement is the cause |
| T7 | first launch / no measurements | empty workshop | a starter test is offered and its meaning is clear |
| T8 | laboratory import | a laboratory file | import finished or its failure understood |
| T9 | interrupted cloud sign-in | sign-in started, window closed | the person can start again, nothing half-saved |
| T10 | restore a copy | a backup | the workshop is restored and checked |

Recorded per run (a row of the record): build, date, operator, task, **success without a hint (y/n)**, **time to find the record**,
**time to the downloaded file**, **returns to an earlier step**, **mistaken actions**, **context entered again**, **changes lost**,
**keyboard-only possible (y/n)**, time of first useful display. Collections for T1/T2/T6 are run on a small set and on synthetic
20 / 200 / 2000 records (`tools/seed_ux_workloads.py` builds them in a throw-away workshop).

The operator's own timings cannot be produced by the agent: the baseline sheet is prepared and **left unfilled** until the operator runs
the tasks.

## 2. Runtime interaction and failure scenarios (REQ-002, plan I-2; research n55)

Node tests on the fake DOM prove structure and order of events; they do not prove a layout engine, real focus, a screen reader or
Electron. Each scenario therefore has two columns.

| id | scenario | setup / action | expected | node test | real browser / Electron |
|---|---|---|---|---|---|
| R1 | multi-character search | type 5 characters in a list search, then edit in the middle | same input node, focus and caret kept, rows not jumping | `test_ui_foundation.py::test_typing_in_the_search_keeps_the_same_field_and_its_focus` | see results |
| R2 | double click | click «Показать ещё» twice quickly | one request, no duplicated rows | `…::test_a_second_click_on_show_more_while_one_is_on_its_way_asks_once` | see results |
| R3 | stale answer | change the search while a page is in flight | the old page never joins the new list | `…::test_a_late_page_of_an_old_search_does_not_join_the_new_list` | see results |
| R4 | load / save failure | server fails once | error beside the object, input kept, retry works | `…::test_a_failed_page_keeps_the_rows_the_search_and_offers_a_retry` and the save-state tests | see results |
| R5 | back navigation | open a work from the catalog, go back | view, search, filters, position restored | catalog tests | see results |
| R6 | dialogs | open a confirmation, Tab / Shift+Tab / Esc | focus trapped, starts on «Отмена», returns to the opener | `…::test_a_confirmation_starts_on_cancel_keeps_tab_inside_and_gives_the_focus_back` | see results |
| R7 | skip link | activate «Перейти к содержимому» on a deep route | route, argument, query unchanged; focus in `main` | `…::test_the_skip_link_moves_the_focus_to_the_content_and_leaves_the_address_alone` | see results |

## 3. Accessibility and responsive profiles (REQ-002, plan I-3; DEC-001 of ux-accessible-layout-p0)

Mandatory profile: **800 × 600 CSS px** content viewport, **text 200 %**, each alone and both together; **320 CSS px** width kept.

| id | check | how | state needed |
|---|---|---|---|
| A1 | keyboard path menu → search → dialog → colour → editor → export → return | real browser, no pointer, visible focus at each step | real browser |
| A2 | screen reader announces stage changes and final outcomes, not a timer | VoiceOver on macOS | **needs a person with a screen reader — not executable by the agent** |
| A3 | 320 px: forms and primary actions reachable | resize, scroll | real browser |
| A4 | 800×600 at 100 %, 200 %, and 800×600 at 200 % | zoom the window | real browser |
| A5 | reduced motion, system contrast modes | OS setting | real browser (structure of the CSS can be asserted in node) |
| A6 | target size and spacing of the actual controls | measured in the browser | real browser |
| A7 | Electron: the same A1, A3, A4 | packaged app | Electron |

Tests that assert exact CSS or a column count (`tests/test_one_screen_frame.py`, the `*_ui.py` tests that read `styles.css`) were
reviewed with the layout requirements: a test that pinned an old value is **changed with a stated reason** in the results, not deleted.

## 4. Domain guarantees (REQ-003, plan I-4/I-5; research n58)

| guarantee | evidence (existing tests unless marked new) |
|---|---|
| the picture stays when the scale changes | `tests/test_photo_engraving_ui.py::test_another_scale_is_saved_in_the_work_the_picture_stays_and_min_and_max_become_the_new_scales_span` |
| card and prediction use one palette of the current width (BUG-011) | `tests/test_scale_palette_context.py` |
| a late answer does not cancel a resize or an undo (BUG-002/011) | save-state tests of `ux-save-feedback-p0` (new) |
| cancelling restores size and settings | `test_photo_engraving_ui.py` undo/redo tests and the save-state tests |
| preview agrees with the LightBurn export | the export tests of `tests/test_lightburn*.py` / `test_vector_work.py` |
| colour and photo-engraving assessments are independent | `ux-engraving-lifecycle-p0` comparison tests (new) |
| files, measurements and their history are kept | lifecycle and photo-review acceptance tests (new) |
| full re-segmentation needs its own confirmation | `tests/test_vector_*_ui.py` split tests |

## 5. Legacy documents (REQ-003 c3, plan I-6; research n50)

Before any of the separate artwork / photo / photo-preview screens could be removed, the following must be created, reopened and
exported. **No screen is removed in 0.39.0**; the catalog and the creation flow route to them.

| document | create | reopen | export | note |
|---|---|---|---|---|
| artwork (colour engraving) | | | | unreachable colours must still block the plan until replaced or excluded |
| photo (continuous, stripes) | | | | stripe processing |
| photo-preview (forecast from an external LightBurn file) | | | | |

The matrix is filled in the results file with the test that did each step.
