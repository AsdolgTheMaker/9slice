"""Unit tests for slicer.py — run with: python -m pytest test_slicer.py"""

import json
import os
import tempfile

import pytest
from PIL import Image

import slicer
from slicer import (Margins, compute_regions, slice_image, export_json,
                    export_slices, export_atlas, stitch_corners, export_corners)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _make_img(w: int = 100, h: int = 80) -> Image.Image:
    """Return a solid-colour RGBA test image."""
    return Image.new("RGBA", (w, h), (255, 0, 0, 255))


# ---------------------------------------------------------------------------
# Margins validation
# ---------------------------------------------------------------------------
class TestMargins:
    def test_valid(self):
        Margins(10, 10, 10, 10).validate(100, 80)

    def test_negative(self):
        with pytest.raises(ValueError, match="non-negative"):
            Margins(-1, 0, 0, 0).validate(100, 80)

    def test_exceeds_width(self):
        with pytest.raises(ValueError, match="width"):
            Margins(60, 60, 0, 0).validate(100, 80)

    def test_exceeds_height(self):
        with pytest.raises(ValueError, match="height"):
            Margins(0, 0, 50, 50).validate(100, 80)

    def test_zero_margins(self):
        Margins(0, 0, 0, 0).validate(100, 80)

    def test_exact_fit(self):
        Margins(50, 50, 40, 40).validate(100, 80)


# ---------------------------------------------------------------------------
# Region computation
# ---------------------------------------------------------------------------
class TestComputeRegions:
    def test_basic(self):
        m = Margins(10, 20, 15, 25)
        regions = compute_regions(100, 80, m)
        assert len(regions) == 9
        assert set(regions.keys()) == set(slicer.SLICE_NAMES)

    def test_corners(self):
        m = Margins(10, 20, 15, 25)
        r = compute_regions(100, 80, m)
        assert r["corner_tl"] == (0, 0, 10, 15)
        assert r["corner_tr"] == (80, 0, 100, 15)
        assert r["corner_bl"] == (0, 55, 10, 80)
        assert r["corner_br"] == (80, 55, 100, 80)

    def test_center(self):
        m = Margins(10, 20, 15, 25)
        r = compute_regions(100, 80, m)
        assert r["center"] == (10, 15, 80, 55)

    def test_edges(self):
        m = Margins(10, 20, 15, 25)
        r = compute_regions(100, 80, m)
        assert r["edge_top"] == (10, 0, 80, 15)
        assert r["edge_bottom"] == (10, 55, 80, 80)
        assert r["edge_left"] == (0, 15, 10, 55)
        assert r["edge_right"] == (80, 15, 100, 55)

    def test_zero_margins_gives_degenerate_corners(self):
        r = compute_regions(100, 80, Margins(0, 0, 0, 0))
        # corners have zero width/height
        assert r["corner_tl"] == (0, 0, 0, 0)
        assert r["center"] == (0, 0, 100, 80)


# ---------------------------------------------------------------------------
# Slicing
# ---------------------------------------------------------------------------
class TestSliceImage:
    def test_slice_count(self):
        img = _make_img()
        slices = slice_image(img, Margins(10, 20, 15, 25))
        assert len(slices) == 9

    def test_slice_sizes(self):
        img = _make_img(100, 80)
        m = Margins(10, 20, 15, 25)
        slices = slice_image(img, m)
        assert slices["corner_tl"].size == (10, 15)
        assert slices["center"].size == (70, 40)
        assert slices["corner_br"].size == (20, 25)


# ---------------------------------------------------------------------------
# Export JSON
# ---------------------------------------------------------------------------
class TestExportJson:
    def test_writes_valid_json(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            export_json(100, 80, Margins(10, 20, 15, 25), path)
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            assert data["image_size"] == {"width": 100, "height": 80}
            assert data["margins"] == {"left": 10, "right": 20, "top": 15, "bottom": 25}
            assert "center" in data["slices"]
            assert data["slices"]["center"] == {"x": 10, "y": 15, "w": 70, "h": 40}
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# Export slices
# ---------------------------------------------------------------------------
class TestExportSlices:
    def test_creates_9_files(self):
        img = _make_img()
        with tempfile.TemporaryDirectory() as d:
            paths = export_slices(img, Margins(10, 10, 10, 10), d)
            assert len(paths) == 9
            for p in paths:
                assert os.path.isfile(p)
                assert p.endswith(".png")


# ---------------------------------------------------------------------------
# Export atlas
# ---------------------------------------------------------------------------
class TestExportAtlas:
    def test_creates_file(self):
        img = _make_img()
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "atlas.png")
            export_atlas(img, Margins(10, 10, 10, 10), path, padding=1)
            atlas = Image.open(path)
            # Atlas should be slightly bigger than original due to padding
            assert atlas.width == img.width + 2   # 2 gaps × 1px
            assert atlas.height == img.height + 2
            atlas.close()

    def test_padding_zero(self):
        img = _make_img()
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "atlas.png")
            export_atlas(img, Margins(10, 10, 10, 10), path, padding=0)
            atlas = Image.open(path)
            assert atlas.size == img.size
            atlas.close()


# ---------------------------------------------------------------------------
# Stitch corners
# ---------------------------------------------------------------------------
class TestStitchCorners:
    def test_dimensions(self):
        img = _make_img(100, 80)
        m = Margins(10, 20, 15, 25)
        result = stitch_corners(img, m)
        assert result.width == 10 + 20   # left + right
        assert result.height == 15 + 25  # top + bottom

    def test_square_margins(self):
        img = _make_img(100, 100)
        m = Margins(25, 25, 25, 25)
        result = stitch_corners(img, m)
        assert result.size == (50, 50)

    def test_zero_margins(self):
        img = _make_img(100, 80)
        result = stitch_corners(img, Margins(0, 0, 0, 0))
        assert result.size == (0, 0)

    def test_export_corners_file(self):
        img = _make_img(100, 80)
        m = Margins(10, 20, 15, 25)
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "corners.png")
            export_corners(img, m, path)
            saved = Image.open(path)
            assert saved.size == (30, 40)
            saved.close()
