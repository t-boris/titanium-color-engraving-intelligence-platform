"""Layer masks for layers that consist of many touching shapes (how conversion plans store a layer)."""
import numpy as np
import pytest

from titanium_platform import photo as ph

PX_PER_MM = 4.0
IMG_TO_MM = np.linalg.inv(np.diag([PX_PER_MM, PX_PER_MM, 1.0]))
SHAPE = (200, 260)


def tiled(rows=6, cols=10, size=5.0):
    """A 50 x 30 mm area built from 60 touching 5 mm squares."""
    return [[(c * size, r * size), ((c + 1) * size, r * size), ((c + 1) * size, (r + 1) * size), (c * size, (r + 1) * size)]
            for r in range(rows) for c in range(cols)]


def test_eroding_every_tile_on_its_own_leaves_seams_between_tiles():
    """Documents why a per-shape mask is wrong for tiled layers: the seams between tiles are lost."""
    per_tile = np.zeros(SHAPE, bool)
    for poly in tiled():
        per_tile |= ph.region_mask(poly, IMG_TO_MM, SHAPE)
    whole_area_px = 50 * 30 * PX_PER_MM ** 2
    assert per_tile.sum() < 0.65 * whole_area_px


def test_layer_mask_erodes_the_outline_of_the_union_not_each_tile():
    mask = ph.layer_mask(tiled(), IMG_TO_MM, SHAPE)
    ys, xs = np.nonzero(mask)
    # the area is 200 x 120 px; 20% of its smaller side (120 px) = 24 px is removed on every side
    assert xs.min() >= 24 - 2 and xs.max() <= 200 - 24 + 2
    assert ys.min() >= 24 - 2 and ys.max() <= 120 - 24 + 2
    inner = (200 - 48) * (120 - 48)
    assert abs(int(mask.sum()) - inner) < 0.05 * inner
    assert mask[ys.min():ys.max() + 1, xs.min():xs.max() + 1].all()  # solid: no seams


def test_layer_mask_agrees_with_the_single_shape_mask_for_one_rectangle():
    poly = [(10, 10), (110, 10), (110, 60), (10, 60)]
    single = ph.region_mask(poly, np.eye(3), (100, 200))
    union = ph.layer_mask([poly], np.eye(3), (100, 200))
    assert abs(int(union.sum()) - int(single.sum())) < 0.1 * single.sum()


def test_each_separate_area_is_eroded_by_its_own_size():
    big = [(0, 0), (40, 0), (40, 40), (0, 40)]
    small = [(100, 0), (108, 0), (108, 8), (100, 8)]
    mask = ph.layer_mask([big, small], np.eye(3), (60, 140))
    assert mask[:, 100:109].sum() > 0  # the small area keeps a core: its edge is 20% of ITS size
    assert mask[:, :41].sum() > 20 * mask[:, 100:109].sum()


def test_layer_mask_of_nothing_is_empty():
    assert not ph.layer_mask([], np.eye(3), (50, 50)).any()


def test_an_area_touching_the_frame_still_loses_its_edge_there():
    """Regression: OpenCV erodes with an 'infinite' border by default, which kept the frame-side edge."""
    poly = [(0, 0), (50, 0), (50, 30), (0, 30)]
    for mask in (ph.layer_mask([poly], IMG_TO_MM, SHAPE), ph.region_mask(poly, IMG_TO_MM, SHAPE)):
        ys, xs = np.nonzero(mask)
        assert xs.min() >= 22 and ys.min() >= 22



def test_a_hole_of_a_shape_is_not_part_of_the_mask():
    outer = [(0, 0), (40, 0), (40, 30), (0, 30)]
    hole = [(15, 10), (25, 10), (25, 20), (15, 20)]
    full = ph.layer_mask([outer], IMG_TO_MM, SHAPE, edge_fraction=0)
    holed = ph.layer_mask([outer], IMG_TO_MM, SHAPE, edge_fraction=0, holes_mm=[[hole]])
    assert full.sum() - holed.sum() == pytest.approx(10 * 10 * PX_PER_MM ** 2, rel=0.06)   # the hole outline pixels go too
    assert not holed[int(15 * PX_PER_MM), int(20 * PX_PER_MM)]            # inside the hole
    assert holed[int(5 * PX_PER_MM), int(5 * PX_PER_MM)]                  # in the fill


def test_a_hole_does_not_remove_pixels_that_another_shape_of_the_layer_fills():
    outer = [(0, 0), (40, 0), (40, 30), (0, 30)]
    hole = [(15, 10), (25, 10), (25, 20), (15, 20)]
    plug = [(10, 5), (30, 5), (30, 25), (10, 25)]       # a second shape of the same layer covers the hole
    mask = ph.layer_mask([outer, plug], IMG_TO_MM, SHAPE, edge_fraction=0, holes_mm=[[hole], []])
    assert mask[int(15 * PX_PER_MM), int(20 * PX_PER_MM)]
