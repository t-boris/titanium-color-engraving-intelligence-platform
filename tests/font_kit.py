"""Small fonts made for the tests (feature inscriptions-in-works), so that the inscriptions are tested the same on any computer: the
tests never read the fonts installed on it (``conftest`` points the catalogue's system folders at the fonts made here).

Every font has a cap height of 700 units in 1000. Its letters are rectangles whose areas are known exactly:

* ``H``: two stems 100 x 700 and a bar between them 300 x 100, as three overlapping contours (the stems and a bar 500 wide): 170 000 units²;
* ``O``: a ring, 600 x 700 outside and 400 x 500 inside: 220 000 units²;
* ``П`` (Cyrillic): two stems 100 x 600 under a roof 600 x 100: 180 000 units²;
* ``א`` (Hebrew alef) a block 500 x 700 (350 000) and ``ב`` (bet) a block 200 x 700 (140 000): the order of a right-to-left run is seen in
  where the larger one lies;
* every other letter of the script samples (so that Latin, Cyrillic and Hebrew count as covered) a block 400 x 500 (200 000);
* a space 300 wide, nothing drawn.
"""
from __future__ import annotations

from pathlib import Path

from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen

UPEM, CAP = 1000, 700
AREA = {"H": 170_000, "O": 220_000, "П": 180_000, "א": 350_000, "ב": 140_000, "box": 200_000}
ADVANCE = {".notdef": 500, "space": 300, "H": 600, "O": 700, "Pe": 700, "alef": 600, "bet": 300, "box": 500}     # by glyph
SAMPLES = "AaZzАаЯяЖжשת"                      # the rest of fonts.SCRIPTS' samples of Latin, Cyrillic and Hebrew


def _rect(pen, x0, y0, x1, y1, clockwise=True):
    points = [(x0, y0), (x0, y1), (x1, y1), (x1, y0)] if clockwise else [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    pen.moveTo(points[0])
    for p in points[1:]:
        pen.lineTo(p)
    pen.closePath()


def _glyph(*rects):
    pen = TTGlyphPen(None)
    for r in rects:
        _rect(pen, *r)
    return pen.glyph()


def make_font(path: Path, family: str = "Test Sans", style: str = "Regular", weight: int = 400, cap: int = CAP) -> Path:
    """Write a TrueType font of the letters above to ``path`` (``cap``: the cap height it states, -1 as some fonts do for «not set»)."""
    glyphs = {
        ".notdef": _glyph((50, 0, 450, 700), (100, 50, 400, 650, False)),
        "space": TTGlyphPen(None).glyph(),
        "H": _glyph((50, 0, 150, 700), (450, 0, 550, 700), (50, 300, 550, 400)),
        "O": _glyph((50, 0, 650, 700), (150, 100, 550, 600, False)),
        "Pe": _glyph((50, 0, 150, 600), (550, 0, 650, 600), (50, 600, 650, 700)),
        "alef": _glyph((50, 0, 550, 700)),
        "bet": _glyph((50, 0, 250, 700)),
        "box": _glyph((50, 0, 450, 500)),
    }
    order = list(glyphs)
    cmap = {ord(" "): "space", ord("H"): "H", ord("O"): "O", ord("П"): "Pe", ord("א"): "alef", ord("ב"): "bet"}
    cmap.update({ord(c): "box" for c in SAMPLES})
    fb = FontBuilder(UPEM, isTTF=True)
    fb.setupGlyphOrder(order)
    fb.setupCharacterMap(cmap)
    fb.setupGlyf(glyphs)
    fb.setupHorizontalMetrics({name: (ADVANCE[name], getattr(glyphs[name], "xMin", 0)) for name in order})
    fb.setupHorizontalHeader(ascent=800, descent=-200)
    fb.setupNameTable({"familyName": family, "styleName": style})
    fb.setupOS2(sTypoAscender=800, sTypoDescender=-200, sTypoLineGap=0, usWinAscent=800, usWinDescent=200, sCapHeight=cap, sxHeight=500,
                usWeightClass=weight, version=4, fsSelection=0x40)
    fb.setupPost()
    path.parent.mkdir(parents=True, exist_ok=True)
    fb.save(str(path))
    return path
