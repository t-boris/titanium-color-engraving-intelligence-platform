# Lessons

Rules written after the operator's remarks, to prevent a repeat.

## Screens follow the operator's questions, not the data model
- Remark: experiments were shown as plates, engravings and photographs in three columns; the colour map was reached through profile versions and experiments.
- Rule: before building a screen, write the one question the operator asks of it ("what happened in this experiment", "where did this colour occur") and make that the
  structure. Derive the object from existing data (experiments are derived, nothing new is stored) instead of exposing tables.

## What the operator must see is shown, not offered
- Remark: the photograph with its overlay must be shown in an experiment every time, not hidden behind a button.
- Rule: evidence for a result (photograph, overlay, contours) is the first block of the page and is on by default. Buttons may switch it off, never on.

## Do not ask for what was already given
- Remark: "I gave you the card / the pair, why can you not use it?" (the ColorChecker was part of the LightBurn file; the pair was already supplied).
- Rule: before asking for an input, list what the conversation and the stored data already contain and look inside it. Ask only for what is provably missing.

## A "did not hit" screenshot is a geometry bug until proven otherwise
- Remark: the overlay of the photo engraving missed, and the green lines were missing.
- Rule: check registration on the real photograph in the real application after every change, not only on synthetic data; the overlay must draw every layer of evidence
  (silhouettes, window, hidden parts). Constrain refinements physically (perspective limit) so a good score cannot hide a skew.

## Synthetic tests are not validation
- Rule: every algorithm that reads real photographs is also run on the operator's real pairs before it is called done; record the numbers (anchors, residual mm, rank
  correlation) in tasks/todo.md.

## Do not end a turn by asking what else to fix
- Rule: finish the listed scope, verify it, report; list open items as facts, not as a question to the operator.

## An optional physical feature is never a required input of an algorithm
- Remark: "why does the algorithm use the frame at all? find every section of the file on its own and grow from there" (2026-10-18), after three
  new pairs were refused for "no frame window".
- Rule: the input of a registration is the file geometry and the photograph, nothing else. A frame, a chart, a marker may *help* when present
  and must be *derived* (the frame from the known plate size) when they matter, but a missing one must not stop the work. Before writing a
  detector of X, ask what happens to the operator's pair when X is absent or looks different (glossy, dark work touching it).

## Judge an overlay by numbers, not by eye
- Remark: I told the operator the lion's fallback overlay was "mirrored and shifted"; measured against the anchored result it was off by 0.4 mm
  median and up to 2 mm at the edges, not mirrored.
- Rule: before calling a registration wrong, compute the displacement against a trusted transform on a grid in mm and quote that; a 1000-px
  preview cannot tell 2 mm from a mirror.

## A relative measurement is shown against a reference in the same photograph, never as the camera exposed it
- Remark: "it does not find light colours" (2026-10-18): every colour of a chartless pair was near black because the photographs are
  2.5–5 stops under and the RAW was decoded without any brightness change.
- Rule: a value that depends on exposure or illuminant is evidence, not a colour. Before showing or comparing it, anchor it to a reference
  inside the same photograph (clean titanium from the cleaning layer, a chart when present) and say which reference was used. If no
  reference exists, say so on the screen instead of showing dark numbers as if they were colours.

## A calibration is checked on its own reference before its result is believed
- Remark: "why no black" (2026-10-18). The chart correction had been reporting a mean residual of 6 dE for months; nobody looked at *where*
  the residual sat. The grey ramp showed the dark tones threefold too dark.
- Rule: every calibration step reports its result on its own reference in a form a person can read (the grey ramp beside the reference), and
  a mean residual is never accepted without that breakdown. When a measurement looks physically odd, check the calibration's reference first.

## A fallback never widens what is measured
- Remark: "clean titanium is visible only where there is no fill; every layer must be taken into account" (2026-10-18), after a fully
  engraved-over first layer was reported as clean titanium at L* 50 over the whole plate.
- Rule: when a mask comes out empty, the answer is "nothing visible", stated on the screen; a fallback for thin strokes applies to thin
  strokes only. Coverage by later layers is computed over every layer in burn order before anything is sampled.

## Recognition that reads text is tuned on every real sample at once, never one at a time
- Situation (2026-10-18): reading the engraved labels of six Material Test photographs; every fix that made one photograph read better
  broke another (a global threshold, a geometric crop, a strip read), because the photographs differ six-fold in label contrast.
- Rule: keep one runner over all real samples and judge every change by the whole table; prefer local, self-calibrating measures (a
  threshold per label from its own strokes) over global constants; let structure repair reading (an evenly spaced sequence fixes a
  misread digit) instead of chasing a perfect reader; and leave the last word to the operator's confirmation.

## A new kind of experiment is finished only when its results are on the colour map
- Situation (2026-10-18): the matrix experiment was built and its six photographs uploaded, but every pair stopped at "settings wait
  for confirmation"; the operator had to remind: "do not forget to add the results to the colour map".
- Rule: the end of a data path is where the data is used (the colour map, the model), not the review screen. Take real samples all the
  way: verify each proposed reading against the photograph, correct what is visibly wrong, accept, and check the map counts. What
  cannot be verified (an unreadable value) is named to the operator with exactly what is missing.

## A model's note that asks for data is re-read when that data arrives
- Situation (2026-10-18): the kinetics note said "plates with a monotone dose ramp at one pulse regime are needed". The matrices
  brought exactly those plates, the results went onto the map, and nobody looked at the kinetics again; the operator found it
  still asking for ramps, in English, under a stray "null".
- Rule: when new data feeds a model, run the model and read its output on the screen the operator uses, including notes. A note
  that promises "with X it will work" is a hypothesis to test the moment X exists.

## UI text: what h() forgives, the DOM does not
- `el.replaceChildren(cond ? x : null)` prints "null"; `h()` skips null. Use `App.fill(el, ...)` (static test in test_ui_files).
- Server text reaches the screen not only through raised errors: dict literals ({"note": ...}) and conditional messages count.
  The translation coverage test collects them; a new kind of message site must be added to the collector, not translated ad hoc.

## A constraint that forces order manufactures correlation: check the physics before trusting r2
- Situation (2026-10-18): forcing the film thickness to grow with dose along each matrix gave "usable" kinetics laws
  (r2 0.6-0.85), but the exponents were 2-5.6 and the palest, almost bare cells sat at 96 nm or the path skipped the whole first
  order. Any monotone assignment correlates with dose; the r2 said nothing.
- Rule: before reading a fit statistic on data shaped by a constraint, check the assignment against what is physically known
  (pale cells are thin, the first order comes first). When the approved plan's premise fails on real data, switch the new
  behaviour off, keep it tested, say why with numbers, and bring a revised plan instead of tuning until a number looks good.

## The operator's application never runs from the development tree
- Remark (2026-10-18): "не работает" / "Sttus не поменялся". Port 8765 ran from the repository's editable `.venv`: its Python
  code stayed in memory while the UI files were served from disk, so the new screens called routes the old backend lacked.
- Rule: the operator's server always runs from the installed wheel in `~/.titanium-platform-app` (DEC-024), never from the
  working tree; check `ps` for the 8765 process before changing files. A new version reaches it only through the deploy step,
  after a backup of the database.

## Statuses move with the code, not at the end
- Remark (2026-10-18): the plan's status table and the requirements' acceptance criteria stayed "in progress"/unchecked while
  work landed on the branch.
- Rule: every commit that implements or verifies something updates, in the same push, the plan.md status row, the ticked
  acceptance criteria (code + test seen) and the issue comment/label.

## Test servers never appear in the operator's browser
- Remark (2026-10-18): "не удали мои эксперименты … фотографий нет, выводов нет". A worker had opened its test server
  (port 8791, a database copy without the photo files) in the operator's MarkView window; the operator took it for the real app.
- Rule: workers never use the MarkView browser tools; UI is checked by static tests and API calls. The lead checks a new version
  on a full copy (database and files) before the deploy, and says in every message which port is the operator's (8765).

## A confirmation that adds no information is a defect
- Remark (2026-10-19): "Мне нужно каждый принять, принять. Очень неудобно … все должно быть принято в самом начале." Every colour
  outside a ΔE tolerance of 0.05 waited for its own "accept" click (28 on one work); the nearest colour and its ΔE were already shown.
- Rule: before adding an approval step, name what the operator learns at that step that the screen does not already show. If
  nothing, apply the choice and show the warning (a ΔE badge, an outline) instead. A tolerance chooses between candidates; it does
  not stop the work.

## A local screen that takes seconds is a bug: measure every screen on the real data
- Remark (2026-10-19): "Почему тэбы грузятся долго? Это ведь локальный вызов." Knowledge took 6.8 s (summaries recomputed per
  entry, O(N²)); every photograph was decoded from RAW on every request (0.6-3.3 s, 2 MB PNG per thumbnail).
- Rule: after a release, time every screen's requests on the live data (curl, GET only) and treat anything over 0.5 s as a
  defect. Derived pictures are cached by a key of all their inputs; a list computes shared data once, never per item.

## A framework default is not a contract
- Situation (2026-10-19): CI failed on all three jobs between two runs of the same tests: FastAPI 0.148 began reading a
  missing `bool` form field as false (an unticked HTML checkbox), and the route relied on `Form(True)`.
- Rule: a form flag whose absence must mean "yes" is read as text and parsed by the application (`form_flag`). When CI
  breaks without a code change, compare the installed versions of the last green run with the failing one first.
