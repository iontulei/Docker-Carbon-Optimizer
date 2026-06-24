"""Data loading utilities for DCO rules."""

from __future__ import annotations

import json
from pathlib import Path

_DATA_DIR = Path(__file__).parent
_image_data: dict | None = None


def get_image_data() -> dict:
    """Load and cache image_sizes.json.

    Returns the full data dict with 'images' and 'minimal_images' keys.
    """
    global _image_data
    if _image_data is None:
        path = _DATA_DIR / "image_sizes.json"
        _image_data = json.loads(path.read_text(encoding="utf-8"))
    return _image_data
