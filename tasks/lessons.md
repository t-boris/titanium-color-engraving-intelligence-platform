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
