"""
Core 9-slice logic — pure functions, no GUI dependencies.

A 9-slice is defined by four margins (left, right, top, bottom) measured
inward from the edges of a source image.  The margins carve the image into
a 3×3 grid of regions:

    TL | TC | TR
    ---+----+---
    ML | MC | MR
    ---+----+---
    BL | BC | BR
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, asdict
from typing import Dict, List, Tuple

from PIL import Image


# Canonical names for the nine slices, row-major order.
SLICE_NAMES: List[str] = [
    "corner_tl", "edge_top",    "corner_tr",
    "edge_left", "center",      "edge_right",
    "corner_bl", "edge_bottom", "corner_br",
]


@dataclass
class Margins:
    """Pixel margins measured inward from each edge."""
    left: int
    right: int
    top: int
    bottom: int

    def validate(self, width: int, height: int) -> None:
        """Raise ValueError if margins don't fit inside *width* × *height*."""
        if self.left < 0 or self.right < 0 or self.top < 0 or self.bottom < 0:
            raise ValueError("Margins must be non-negative.")
        if self.left + self.right > width:
            raise ValueError(
                f"Horizontal margins ({self.left}+{self.right}) exceed image width ({width})."
            )
        if self.top + self.bottom > height:
            raise ValueError(
                f"Vertical margins ({self.top}+{self.bottom}) exceed image height ({height})."
            )


def compute_regions(
    width: int, height: int, margins: Margins
) -> Dict[str, Tuple[int, int, int, int]]:
    """Return a dict mapping each slice name to its (x0, y0, x1, y1) crop box.

    The box follows PIL convention: left edge inclusive, right edge exclusive.
    """
    margins.validate(width, height)
    l, r, t, b = margins.left, margins.right, margins.top, margins.bottom
    # Column boundaries
    cx = [0, l, width - r, width]
    # Row boundaries
    cy = [0, t, height - b, height]

    regions: Dict[str, Tuple[int, int, int, int]] = {}
    idx = 0
    for row in range(3):
        for col in range(3):
            regions[SLICE_NAMES[idx]] = (cx[col], cy[row], cx[col + 1], cy[row + 1])
            idx += 1
    return regions


def slice_image(img: Image.Image, margins: Margins) -> Dict[str, Image.Image]:
    """Crop *img* into 9 sub-images keyed by slice name."""
    regions = compute_regions(img.width, img.height, margins)
    return {name: img.crop(box) for name, box in regions.items()}


def export_json(
    width: int, height: int, margins: Margins, path: str
) -> None:
    """Write slice coordinates to a JSON file."""
    regions = compute_regions(width, height, margins)
    data = {
        "image_size": {"width": width, "height": height},
        "margins": asdict(margins),
        "slices": {name: {"x": b[0], "y": b[1], "w": b[2] - b[0], "h": b[3] - b[1]}
                   for name, b in regions.items()},
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def export_slices(img: Image.Image, margins: Margins, directory: str) -> List[str]:
    """Export each of the 9 slices as individual PNG files.

    Returns the list of written file paths.
    """
    os.makedirs(directory, exist_ok=True)
    slices = slice_image(img, margins)
    paths: List[str] = []
    for name, sub in slices.items():
        p = os.path.join(directory, f"{name}.png")
        sub.save(p)
        paths.append(p)
    return paths


def stitch_corners(img: Image.Image, margins: Margins) -> Image.Image:
    """Stitch the 4 corner slices into a single image.

    Layout:
        TL | TR
        ---+---
        BL | BR

    The result width = left + right, height = top + bottom.
    """
    slices = slice_image(img, margins)
    tl = slices["corner_tl"]
    tr = slices["corner_tr"]
    bl = slices["corner_bl"]
    br = slices["corner_br"]
    w = tl.width + tr.width
    h = tl.height + bl.height
    result = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    result.paste(tl, (0, 0))
    result.paste(tr, (tl.width, 0))
    result.paste(bl, (0, tl.height))
    result.paste(br, (tl.width, tl.height))
    return result


def export_corners(img: Image.Image, margins: Margins, path: str) -> None:
    """Export the 4 corners stitched into a single PNG."""
    result = stitch_corners(img, margins)
    result.save(path)


