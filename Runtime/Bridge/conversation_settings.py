"""Validated, non-secret conversation presentation settings."""

from __future__ import annotations

import unicodedata
from typing import Any, Mapping

from .persona_presets import PRESET_PERSONAS


MAX_PERSONA_TEXT_LENGTH = 800
DEFAULT_SETTINGS = {
    "language": "ja",
    "voice": "marin",
    "persona": "friendly",
    "personaText": "",
}
LANGUAGES = ("ja", "en")
VOICES = (
    "marin", "quartz", "ripple", "vesper", "willow", "stone", "gleam",
    "meridian", "bossa", "tempo", "beacon", "delta", "cinder",
)
PERSONAS = ("friendly", "curious", "calm", "custom", *PRESET_PERSONAS)


class SettingsError(ValueError):
    """Stable validation code; never includes user-supplied persona text."""


def _error(code: str) -> None:
    raise SettingsError(code)


def _validated_choice(value: Any, allowed: tuple[str, ...], code: str) -> str:
    if not isinstance(value, str) or value not in allowed:
        _error(code)
    return value


def _validated_persona_text(value: Any) -> str:
    if not isinstance(value, str):
        _error("invalid_persona_text")
    text = value.strip()
    if len(text) > MAX_PERSONA_TEXT_LENGTH:
        _error("persona_text_too_long")
    if any(unicodedata.category(character) == "Cc" and character not in "\n\t" for character in text):
        _error("persona_text_has_control_character")
    return text


def validate_settings(value: Any) -> dict[str, str]:
    """Validate exactly the public presentation fields and return a fresh dict."""
    if not isinstance(value, dict) or set(value) != set(DEFAULT_SETTINGS):
        _error("invalid_conversation_settings")
    result = {
        "language": _validated_choice(value["language"], LANGUAGES, "invalid_language"),
        "voice": _validated_choice(value["voice"], VOICES, "invalid_voice"),
        "persona": _validated_choice(value["persona"], PERSONAS, "invalid_persona"),
        "personaText": _validated_persona_text(value["personaText"]),
    }
    if result["persona"] == "custom" and not result["personaText"]:
        _error("custom_persona_text_required")
    return result


def settings_from_config(config: Any) -> dict[str, str]:
    """Extract only presentation fields from a complete Bridge configuration."""
    if not isinstance(config, Mapping):
        _error("invalid_conversation_settings")
    conversation = config.get("conversation")
    if not isinstance(conversation, Mapping):
        _error("invalid_conversation_settings")
    settings = dict(DEFAULT_SETTINGS)
    for key in DEFAULT_SETTINGS:
        if key in conversation:
            settings[key] = conversation[key]
    return validate_settings(settings)


def options_message() -> dict[str, object]:
    """Return serializable choices without any configured custom persona text."""
    return {
        "type": "conversation_options",
        "languages": list(LANGUAGES),
        "voices": list(VOICES),
        "personas": list(PERSONAS),
        "maxPersonaTextLength": MAX_PERSONA_TEXT_LENGTH,
    }
