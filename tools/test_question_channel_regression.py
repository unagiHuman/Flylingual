"""Real Bridge/ConversationAdapter question path; only outbound WebSocket is fake."""
import copy
import unittest
from Runtime.Bridge.config import _DEFAULT
from Runtime.Bridge.server import Bridge
from Runtime.Bridge.conversation import ConversationAdapter


class OutboundSocket:
    closed = False
    def __init__(self): self.events = []
    async def send_json(self, event): self.events.append(copy.deepcopy(event))


class QuestionChannelRegressionTests(unittest.IsolatedAsyncioTestCase):
    def bridge(self, language):
        config = copy.deepcopy(_DEFAULT)
        config['neuralFeedback']['enabled'] = True
        b = Bridge(config)
        b.conversation.mode = 'live'
        b.conversation.state = 'live'
        b.conversation.settings['language'] = language
        b.conversation.ws = OutboundSocket()
        return b

    async def test_real_question_path_preserves_thinking_then_instructions(self):
        for language, context in [('ja', '現在の原因は未確認です。'), ('en', 'The current cause is unverified.')]:
            b = self.bridge(language)
            self.assertIsInstance(b.conversation, ConversationAdapter)
            self.assertIsNone(b.adapter)  # No Brain instance, transport or fabricated frame.
            await b.speak_non_action(context, 'question-1')
            events = b.conversation.ws.events
            self.assertEqual([e['type'] for e in events], ['session.thinking.append', 'session.instructions.append'])
            self.assertEqual(events[0]['content'], context)
            self.assertEqual(events[0]['delegation_id'], 'question-1')
            self.assertIn('質問' if language == 'ja' else 'question', events[1]['content'])
            self.assertEqual(b.neural_context_appends, 1)
            self.assertNotEqual(events[0]['event_id'], events[1]['event_id'])

    async def test_existing_target_changed_instructions_and_trace_use_same_transport(self):
        b = self.bridge('en')
        rid = await b.conversation.append('instructions', b.text('target_changed'),
                                          trace={'language': 'en', 'controlEpoch': b.arbiter.epoch})
        self.assertEqual(b.conversation.ws.events[0]['type'], 'session.instructions.append')
        self.assertEqual(b.conversation.ws.events[0]['event_id'], rid)
        await b.conversation._context_appended({'type': 'session.instructions.appended',
                                               'client_event_id': rid, 'event_id': 'server-event'})
        self.assertNotIn(rid, b.conversation.context_receipts)


if __name__ == '__main__': unittest.main()
