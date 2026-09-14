"""Text-session lifecycle tests, without Brain or Unity simulation."""
import copy
import unittest
from unittest.mock import AsyncMock, patch

from Runtime.Bridge.config import _DEFAULT
from Runtime.Bridge.conversation import ConversationAdapter, ConversationError
from tools.test_native_continuous_control import NativeContinuousControlTests


class TextSessionTests(unittest.IsolatedAsyncioTestCase):
    async def test_no_api_key_required_and_audio_refused(self):
        events = []
        async def emit(event):
            events.append(event)
        cfg = {**copy.deepcopy(_DEFAULT['conversation']), 'mode': 'text',
               'intentProvider': 'vercel', 'cloudIntentUrl': 'https://example.invalid/api/fly/translate'}
        adapter = ConversationAdapter(cfg, emit, AsyncMock())
        with patch.dict('os.environ', {}, clear=True):
            try:
                await adapter.start()
                self.assertEqual(adapter.state, 'text')
                self.assertIsNone(adapter.ws)
                proposal = await adapter.interpret('前に進んで', {}, 4000, 8000)
                self.assertEqual(proposal['action'], 'FORWARD')
                with self.assertRaisesRegex(ConversationError, 'live_audio_not_connected'):
                    await adapter.input_audio('AAAA')
            finally:
                await adapter.stop()
        self.assertEqual(events[-1]['state'], 'off')
        self.assertIsNone(adapter.http)


class TextContinuousControlTests(NativeContinuousControlTests):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.bridge.conversation.state = 'text'
        self.bridge.conversation.mode = 'text'
