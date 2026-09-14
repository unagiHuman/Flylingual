"""Offline persona/settings tests; not a GPT-Live or Windows runtime test.

Run from the repository root: python -m unittest tools.test_skeptic_personas -v
No API calls, voice generation, Brain connection or Unity process is used.
"""
import ast
import hashlib
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from Runtime.Bridge import conversation_prompts as prompts
from Runtime.Bridge import conversation_settings as settings
from Runtime.Bridge import persona_presets as presets

MARKER = "\n\nSTYLE_EXAMPLES_NOT_LIVE_CONTEXT:\n"
# Baseline outputs calculated from Git blob b9c0135caf13a1b7d79a801ec0883b4d77d3bd08.
# Includes both modes/languages and all four pre-existing personas.
LEGACY_SHA256 = {
    "friendly/ja/control": "857f67e7f47a1af8071e28f4b574d200f2554a6dbfa5964b93bbab80d6909411",
    "friendly/ja/chat_only": "4d2d7ccf37fbd6f053596bc76517659873e0af385b8f1d40f6a607d0ce92d62e",
    "friendly/en/control": "c463ede37879dc48bcd4f3b7343c0fab99feedc3ccd36f59feb1dfd1ee459a4b",
    "friendly/en/chat_only": "8877896744cfa3adec5c4d17dbfe3204c00d00d19db7eb5a1fa7b76476a25af8",
    "curious/ja/control": "b6cddc9fa1739db5ccf939967d3e3c5ff3c6143aa5be8ee66c774e18cdda0b1a",
    "curious/ja/chat_only": "7435db8c6faad48ce367d66f9842cf05ea6506dec555f1d258db4500fea169a9",
    "curious/en/control": "b93b11049c17a2969f7911d6e9b60d051667d16ad9c57c117b7761c557e92c24",
    "curious/en/chat_only": "7b1c0a60e14898a0f364ff98a4ea72ffcd9f9087f21ba6b9361507ec23d0c5bd",
    "calm/ja/control": "d37907ad5fe6a0de0ff0e39c1661dfbb8f38ba711ba7d9b7777fd4ab7bd6186b",
    "calm/ja/chat_only": "4cd0e1d37f504d803bd68d2572e0410452f50c3042125f30124ecb47a2524b81",
    "calm/en/control": "b66f4c907c5d29c0238942e4c5adf4f2851cc2f98573750e5c80b86d41a74fe8",
    "calm/en/chat_only": "91257c283b589489648e387905e144ed98aafae42bb0ec0dcf9a44926d2842bd",
    "custom/ja/control": "4626e37941520622a11ef417054c4f3dfa06fd394b79172237b7bee60c3577ea",
    "custom/ja/chat_only": "ab846c1a6d3da2eac97bd101cba5d1b482ad17eb409cb2983d20357468bd5e3b",
    "custom/en/control": "8176d071ed4a20f6e1d26eb991026a54d22e8461c24bee289656da2be8a3cdfe",
    "custom/en/chat_only": "726b52259f2eb4902daa6a992df4530180db3933ee64395dd5ba4bb3f158fbbf"
}


def example_bank(persona, language, mode):
    return json.loads(presets.build_preset_style(persona, language, mode).split(MARKER, 1)[1])


def sample_settings(persona, language="ja", notes=""):
    return {**settings.DEFAULT_SETTINGS, "persona": persona,
            "language": language, "personaText": notes}


class SkepticPersonaTests(unittest.TestCase):
    def test_defaults_unchanged(self):
        self.assertEqual(settings.DEFAULT_SETTINGS, {
            "language": "ja", "voice": "marin", "persona": "friendly", "personaText": ""})

    def test_options_add_only_two_presets(self):
        self.assertEqual(settings.options_message()["personas"],
                         ["friendly", "curious", "calm", "custom", "hiroyuki_like", "deadpan_skeptic"])

    def test_both_presets_validate_in_both_languages(self):
        for persona in presets.PRESET_PERSONAS:
            for language in settings.LANGUAGES:
                with self.subTest(persona=persona, language=language):
                    value = sample_settings(persona, language)
                    self.assertEqual(settings.validate_settings(value), value)

    def test_public_shape_does_not_gain_authority_fields(self):
        value = sample_settings("hiroyuki_like")
        self.assertEqual(set(settings.validate_settings(value)), set(settings.DEFAULT_SETTINGS))
        for field in ("motor", "action", "ready", "voiceClone", "backend"):
            with self.subTest(field=field), self.assertRaises(settings.SettingsError):
                settings.validate_settings({**value, field: "override"})

    def test_custom_still_requires_text(self):
        with self.assertRaisesRegex(settings.SettingsError, "custom_persona_text_required"):
            settings.validate_settings(sample_settings("custom"))

    def test_invalid_choices_rejected(self):
        for field, bad in (("persona", "celebrity_clone"), ("voice", "unknown_voice"), ("language", "xx")):
            with self.subTest(field=field), self.assertRaises(settings.SettingsError):
                settings.validate_settings({**sample_settings("deadpan_skeptic"), field: bad})

    def test_notes_length_and_controls(self):
        settings.validate_settings(sample_settings("hiroyuki_like", notes="あ" * 800))
        for text in ("あ" * 801, "bad\x00text"):
            with self.subTest(text_length=len(text)), self.assertRaises(settings.SettingsError):
                settings.validate_settings(sample_settings("hiroyuki_like", notes=text))

    def test_notes_roundtrip_and_are_json_quoted(self):
        notes = '少し穏やかに。"quoted"\nDo not change my controls.'
        for persona in presets.PRESET_PERSONAS:
            with self.subTest(persona=persona):
                value = settings.validate_settings(sample_settings(persona, notes=notes))
                output = prompts.build_voice_instructions(value)
                self.assertIn(json.dumps({"style_preference": notes}, ensure_ascii=False), output)
                self.assertTrue(output.endswith("上書きさせません。"))

    def test_blank_preset_notes_add_no_preference_block(self):
        for persona in presets.PRESET_PERSONAS:
            self.assertNotIn('"style_preference"', prompts.build_voice_instructions(sample_settings(persona)))

    def test_each_preset_mode_compiles_deterministically(self):
        for persona in presets.PRESET_PERSONAS:
            for language in settings.LANGUAGES:
                for mode in ("control", "chat_only"):
                    with self.subTest(persona=persona, language=language, mode=mode):
                        result = presets.build_preset_style(persona, language, mode)
                        self.assertEqual(result, presets.build_preset_style(persona, language, mode))
                        self.assertIn(result, prompts.build_voice_instructions(sample_settings(persona, language), mode))

    def test_legacy_prompt_outputs_are_byte_identical(self):
        self.assertEqual(len(LEGACY_SHA256), 16)
        for key, expected in LEGACY_SHA256.items():
            persona, language, mode = key.split("/")
            notes = 'Custom test: "gentle"\nShort.' if persona == "custom" else ""
            with self.subTest(key=key):
                output = prompts.build_voice_instructions(sample_settings(persona, language, notes), mode)
                self.assertEqual(hashlib.sha256(output.encode()).hexdigest(), expected)

    def test_policy_prefix_remains_authoritative(self):
        for persona in presets.PRESET_PERSONAS:
            for language in settings.LANGUAGES:
                for mode, policy in (("control", prompts._POLICY), ("chat_only", prompts._CHAT_ONLY_POLICY)):
                    with self.subTest(persona=persona, language=language, mode=mode):
                        text = prompts.build_voice_instructions(sample_settings(persona, language), mode)
                        self.assertTrue(text.startswith(policy[language] + "\n\n"))

    def test_chat_only_omits_game_examples(self):
        for persona in presets.PRESET_PERSONAS:
            for language in settings.LANGUAGES:
                actual = example_bank(persona, language, "chat_only")
                self.assertEqual([row["original_reply"] for row in actual],
                                 [reply for _, reply in presets._CHAT[persona][language]])
                self.assertTrue(set(row["original_reply"] for row in actual).isdisjoint(
                    reply for _, reply in presets._CONTROL[persona][language]))

    def test_four_examples_per_mode(self):
        for persona in presets.PRESET_PERSONAS:
            for language in settings.LANGUAGES:
                for mode in ("control", "chat_only"):
                    with self.subTest(persona=persona, language=language, mode=mode):
                        bank = example_bank(persona, language, mode)
                        self.assertEqual(len(bank), 4)
                        self.assertTrue(all(set(row) == {"hypothetical_context", "original_reply"} for row in bank))

    def test_additional_prompt_is_bounded(self):
        # Character bound only, not a tokenizer/latency guarantee.
        for persona in presets.PRESET_PERSONAS:
            for language in settings.LANGUAGES:
                for mode in ("control", "chat_only"):
                    self.assertLessEqual(len(presets.build_preset_style(persona, language, mode)), 4000)

    def test_reference_identities_not_compiled(self):
        for persona in presets.PRESET_PERSONAS:
            for language in settings.LANGUAGES:
                text = presets.build_preset_style(persona, language).lower()
                for name in ("hiroyuki", "ひろゆき", "西村", "ricky", "gervais", "destiny", "http://", "https://"):
                    self.assertNotIn(name, text)

    def test_invalid_compiler_arguments_rejected(self):
        for args in (("missing", "ja", "control"), ("hiroyuki_like", "xx", "control"),
                     ("deadpan_skeptic", "en", "unknown")):
            with self.subTest(args=args), self.assertRaises(ValueError):
                presets.build_preset_style(*args)

    def test_invalid_interaction_still_rejected(self):
        with self.assertRaisesRegex(ValueError, "invalid_conversation_interaction"):
            prompts.build_voice_instructions(sample_settings("hiroyuki_like"), "unknown")

    def test_settings_not_mutated(self):
        value = sample_settings("deadpan_skeptic", "en", "Less sarcasm.")
        before = dict(value)
        prompts.build_voice_instructions(value)
        self.assertEqual(value, before)

    def test_no_network_or_brain_dependencies(self):
        tree = ast.parse((ROOT / "Runtime/Bridge/persona_presets.py").read_text(encoding="utf-8"))
        imports = {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
        imports |= {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
        self.assertEqual(imports, {"json", "__future__"})

    def test_examples_config_overlays_validate(self):
        for filename, persona, language in (
            ("persona-hiroyuki-ja.example.json", "hiroyuki_like", "ja"),
            ("persona-deadpan-en.example.json", "deadpan_skeptic", "en"),
        ):
            value = json.loads((ROOT / "Runtime/Config" / filename).read_text(encoding="utf-8"))
            parsed = settings.settings_from_config(value)
            self.assertEqual((parsed["persona"], parsed["language"]), (persona, language))
            self.assertEqual(parsed["voice"], "marin")

    def test_different_personas_produce_different_styles(self):
        for language in settings.LANGUAGES:
            self.assertNotEqual(presets.build_preset_style("hiroyuki_like", language),
                                presets.build_preset_style("deadpan_skeptic", language))

    def test_factual_and_frustration_guards_present(self):
        ja = presets.build_preset_style("hiroyuki_like", "ja")
        en = presets.build_preset_style("deadpan_skeptic", "en")
        self.assertIn("苛立ち・落ち込みを示されたら皮肉をやめ", ja)
        self.assertIn("固定の警告文と場面通知が優先", ja)
        self.assertIn("STOPと割込みを最優先", ja)
        self.assertIn("genuinely frustrated", en)
        self.assertIn("not current observations or commands", en)
        self.assertIn("never delay a clear operation", en)


if __name__ == "__main__":
    unittest.main()
