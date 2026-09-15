"""Sortable, filename-safe identifiers.

Format: <prefix>_<base32 time><base32 random>. Lexicographic order matches
creation order, which keeps directory listings and library queries cheap
without an index.
"""
from __future__ import annotations

import os
import re
import time

_ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyz"
ID_PATTERN = re.compile(r"^[a-z]{3,8}_[0-9a-z]{10,32}$")


def _encode(value: int, width: int) -> str:
    digits = []
    for _ in range(width):
        value, rest = divmod(value, len(_ALPHABET))
        digits.append(_ALPHABET[rest])
    return "".join(reversed(digits))


def new_id(prefix: str) -> str:
    milliseconds = int(time.time() * 1000)
    return f"{prefix}_{_encode(milliseconds, 9)}{_encode(int.from_bytes(os.urandom(5), 'big'), 8)}"


def is_valid_id(value: str) -> bool:
    """Reject anything that could escape the data directory when joined."""
    return bool(ID_PATTERN.fullmatch(value)) and "/" not in value and ".." not in value
