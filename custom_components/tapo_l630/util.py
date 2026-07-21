"""Utility helpers for the Tapo L630 integration."""

from __future__ import annotations

import base64
import binascii
from typing import Any


def decode_nickname(value: Any) -> str | None:
    """Decode the base64 nickname used by recent Tapo firmware."""
    if not isinstance(value, str) or not value:
        return None
    try:
        decoded = base64.b64decode(value, validate=True).decode()
    except (binascii.Error, UnicodeDecodeError):
        return value
    return decoded or value
