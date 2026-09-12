"""Launcher-local API-key file handling for the Bridge.

The key is returned only to the launcher caller.  It is intentionally not a
configuration value and is never persisted or logged here.
"""

from __future__ import annotations

import os
from os import PathLike
from pathlib import Path
from typing import Mapping


MAX_KEY_FILE_BYTES = 8192


class CredentialError(ValueError):
    """A local credential source is missing or unsafe to use."""


def _validate_key(value: str) -> str:
    if (
        not value
        or not value.startswith("sk-")
        or any(ord(character) > 0x7F or character.isspace() for character in value)
    ):
        raise CredentialError("API key file does not contain one valid single-line API key")
    return value


def load_api_key_file(path_value: str | PathLike[str]) -> str:
    """Read one small, ASCII, single-line key without exposing its contents."""
    path = Path(path_value)
    try:
        with path.open("rb") as handle:
            data = handle.read(MAX_KEY_FILE_BYTES + 1)
    except OSError as exc:
        raise CredentialError("API key file cannot be read") from exc
    if len(data) > MAX_KEY_FILE_BYTES:
        raise CredentialError(f"API key file exceeds {MAX_KEY_FILE_BYTES} bytes")
    try:
        text = data.decode("ascii")
    except UnicodeDecodeError as exc:
        raise CredentialError("API key file must contain ASCII text") from exc
    lines = text.splitlines()
    if len(lines) != 1:
        raise CredentialError("API key file must contain exactly one line")
    return _validate_key(lines[0])


def load_requested_api_key(
    key_file: str | None, environ: Mapping[str, str] | None = None
) -> str | None:
    """Resolve explicit --key-file before the optional environment fallback."""
    environment = os.environ if environ is None else environ
    source = key_file if key_file is not None else environment.get("OPENAI_API_KEY_FILE")
    if not source:
        return None
    return load_api_key_file(source)
