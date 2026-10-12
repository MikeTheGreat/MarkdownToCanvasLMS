"""A short, stable hash of parsed TOML values.

Used by `update` to tell which course-settings sections changed, and by
`generate-due-dates` / `update` / `publish` for the ``last_generated_hash``
fingerprint of ``[relative_due_dates]``. Values are serialized as canonical
JSON (sorted keys, no whitespace; TOML dates and times through ``str``), so
comments, layout and key order in the file do not affect the result.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_hash(value: Any) -> str:
    """The first 16 hex digits of the SHA-256 of ``value`` as canonical JSON."""
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
