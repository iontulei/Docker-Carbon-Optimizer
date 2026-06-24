"""Shared utilities for DCO rule implementations."""

from __future__ import annotations


def parse_from_value(value: str) -> tuple[str, str]:
    """Extract image name and tag from a FROM instruction value.

    Handles formats like::

        'python:3.12'
        'python:3.12 AS builder'
        'library/python:3.12'
        'python'  (no tag)

    Returns:
        (image_name, tag) - tag is empty string when absent.
    """
    # Strip AS alias
    parts = value.split()
    image_ref = parts[0]

    # Strip library/ prefix
    if image_ref.startswith("library/"):
        image_ref = image_ref[len("library/"):]

    # Split image:tag
    if ":" in image_ref:
        image, tag = image_ref.split(":", 1)
    else:
        image, tag = image_ref, ""

    return image, tag
