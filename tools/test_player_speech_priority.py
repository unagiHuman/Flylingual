"""Player-first presentation contracts; no real Brain or external service."""
import asyncio
import copy
import unittest
from array import array
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from Runtime.Bridge.config import _DEFAULT
from Runtime.Bridge.server import Bridge
from Runtime.Bridge.conversation_prompts import build_voice_instructions


class PlayerSpeechPriorityTests(unittest.IsolatedAsyncioTestCase):
    def bridge(self):
        b = Bridge(copy.deepcopy(_DEFAULT))
        b.conversation_accepting = True
        b.conversation.state = 'live'
        b.conversation.mode = 'live'
        b.conversation.last_voice_end_at = -1e15
        b.emit = Mock()
        b.log = Mock()
        b.conversation.append = AsyncMock()
        return b

    async def test_envelope_onset_discards_once_before_any_transcript(self):
        b = self.bridge()
        b.conversation._send_event = AsyncMock()
        pcm = array('h', [1000] * 2400).tobytes()
        b.conversation.audio_queue.put_nowait(pcm)
        b.conversation.audio_queue.put_nowait(pcm)
        task = asyncio.create_task(b.conversation._send_audio())
        try:
            await asyncio.sleep(.35)
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        discards = [c.args[0] for c in b.emit.call_args_list if c.args[0].get('type') == 'discard_audio']
        self.assertEqual(len(discards), 1)
        self.assertTrue(b.player_has_priority())
        b.conversation.append.assert_not_awaited()

    async def test_envelope_discard_precedes_blocked_network_send(self):
        b = self.bridge()
        entered, release = asyncio.Event(), asyncio.Event()
        async def blocked_send(event):
            entered.set()
            await release.wait()
        b.conversation._send_event = blocked_send
        b.conversation.audio_queue.put_nowait(array('h', [1000] * 2400).tobytes())
        task = asyncio.create_task(b.conversation._send_audio())
        try:
            await asyncio.wait_for(entered.wait(), 1)
            self.assertEqual(sum(c.args[0].get('type') == 'discard_audio'
                                 for c in b.emit.call_args_list), 1)
            self.assertFalse(release.is_set())
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def test_voiced_input_drops_output_then_allows_new_audio_after_tail(self):
        b = self.bridge()
        b.player_priority_until = 16.
        b.conversation.last_voice_end_at = 10.
        clock = [10.1]
        with patch('Runtime.Bridge.server.time', SimpleNamespace(monotonic=lambda: clock[0])):
            await b.conversation_event({'type': 'audio', 'audio': 'fixture', 'audible': True})
            b.emit.assert_not_called()
            self.assertEqual(b.neural_output_at, -1e15)
            clock[0] = 10.151
            await b.conversation_event({'type': 'audio', 'audio': 'new-fixture', 'audible': True})
            audio = [c.args[0] for c in b.emit.call_args_list if c.args[0].get('type') == 'audio']
            self.assertEqual(len(audio), 1)
            self.assertEqual(audio[0]['audio'], 'new-fixture')
            self.assertNotIn('audible', audio[0])
            self.assertAlmostEqual(b.neural_output_at, 10151.)

    async def test_silent_output_never_extends_priority(self):
        b = self.bridge()
        b.player_priority_until = 6.
        b.neural_output_at = 0.
        with patch('Runtime.Bridge.server.time', SimpleNamespace(monotonic=lambda: 10.)):
            await b.conversation_event({'type': 'audio', 'audio': 'silent-fixture', 'audible': False})
            self.assertEqual(b.neural_output_at, 0.)
            self.assertFalse(b.player_has_priority())
            audio = [c.args[0] for c in b.emit.call_args_list if c.args[0].get('type') == 'audio']
            self.assertEqual(len(audio), 1)
            self.assertNotIn('audible', audio[0])

    async def test_asr_burst_does_not_repeatedly_erase_response(self):
        b = self.bridge()
        clock = [10.]
        with patch('Runtime.Bridge.server.time', SimpleNamespace(monotonic=lambda: clock[0])):
            for text in ('今', 'どういう', '状態'):
                await b.conversation_event({'type': 'conversation_text', 'role': 'user', 'text': text, 'append': True})
                clock[0] += .2
            discards = [c for c in b.emit.call_args_list if c.args[0].get('type') == 'discard_audio']
            self.assertEqual(len(discards), 1)
            self.assertEqual(b.conversation.append.await_count, 1)
            self.assertEqual(b.conversation.append.await_args.args[0], 'instructions')
            clock[0] += 2
            await b.conversation_event({'type': 'conversation_text', 'role': 'user', 'text': '次の質問', 'append': True})
            self.assertEqual(b.conversation.append.await_count, 2)

    async def test_not_accepting_has_no_interrupt_or_asr_side_effect(self):
        b = self.bridge()
        b.conversation_accepting = False
        prior = (b.player_priority_until, b.player_transcript_at)
        await b.conversation_event({'type': 'player_speech_started'})
        await b.conversation_event({'type': 'conversation_text', 'role': 'user', 'text': 'hello'})
        self.assertEqual(prior, (b.player_priority_until, b.player_transcript_at))
        b.emit.assert_not_called()
        b.conversation.append.assert_not_awaited()

    async def test_cues_and_measured_cues_yield_then_recover_after_deadline(self):
        b = self.bridge()
        b.control_ws = object()
        b.require_fresh = Mock()
        b.blind_script.accept = Mock(return_value=('Observed warning.', True))
        clock = [100.]
        e = dict(cue='swatter_escaped', controlEpoch=b.arbiter.epoch,
                 conversationGeneration=b.conversation_generation, sequence=1)
        with patch('Runtime.Bridge.server.time', SimpleNamespace(monotonic=lambda: clock[0])):
            b.player_speech_started()
            for measured in (None, ('Earlier measured right 120 Hz.', {'brainSequence': 12})):
                b.visual_threat_cue_context = Mock(return_value=measured)
                await b.blind_run_cue(e)
                self.assertEqual(b.conversation.append.await_args.args[0], 'thinking')
                if measured:
                    self.assertEqual(b.conversation.append.await_args.kwargs['trace'], measured[1])
            clock[0] = 107.
            self.assertFalse(b.player_has_priority())
            await b.blind_run_cue(e)
            self.assertEqual(b.conversation.append.await_args.args[0], 'commentary')

    async def test_priority_waits_for_intent_and_recent_output(self):
        b = self.bridge()
        b.player_priority_until = 1.
        with patch('Runtime.Bridge.server.time', SimpleNamespace(monotonic=lambda: 10.)):
            b.intent_tasks.add('pending')
            self.assertTrue(b.player_has_priority())
            b.intent_tasks.clear()
            b.neural_output_at = 9000
            self.assertTrue(b.player_has_priority())
            b.neural_output_at = 8000
            self.assertFalse(b.player_has_priority())

    async def test_bilingual_control_and_chat_only_prompts_prioritize_player(self):
        b = self.bridge()
        for language in ('ja', 'en'):
            settings = {**b.conversation.settings, 'language': language}
            for interaction in ('control', 'chat_only'):
                prompt = build_voice_instructions(settings, interaction, neural_feedback=True)
                self.assertIn('即座に中断' if language == 'ja' else 'immediately stop the script', prompt)
                self.assertIn('勝手に再開しません' if language == 'ja' else 'Do not automatically resume', prompt)
                self.assertIn('安全規則' if language == 'ja' else 'safety rules', prompt)


if __name__ == '__main__': unittest.main()
