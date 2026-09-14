"""No-network transcript/Bridge ordering tests, not ASR or Brain motion acceptance."""
import asyncio
import copy
import json
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from Runtime.Bridge.config import _DEFAULT
from Runtime.Bridge.conversation import ConversationAdapter, ConversationError
from Runtime.Bridge.server import Bridge
from tools.test_live_session_clock import EventSocket, delegation, transcript
from tools.test_persistent_execution import action, update


def non_action(kind):
    value = action(duration=4000)
    value.update(kind=kind, action=None)
    return value


class TranscriptSemanticControlTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        config = copy.deepcopy(_DEFAULT)
        config['conversation']['mode'] = 'live'
        self.b = Bridge(config)
        b = self.b
        b.emit = Mock()
        b.log = Mock()
        b.summary = Mock(return_value={'stale': False, 'interpretation': 'unknown'})
        b.control_ws = object()
        b.adapter = SimpleNamespace(connected=True, status={}, send_action=AsyncMock())
        b.arbiter.owner = 'gpt'
        b.arbiter.resume()
        b.conversation_accepting = True
        b.native_voice_control = True
        b.voice_control_epoch = b.arbiter.epoch
        self.a = b.conversation
        self.a.state = 'live'
        self.a.closing = False
        self.a.interaction = 'control'
        self.a.transcript_batch_delay = .01
        self.a.append = AsyncMock()
        self.a.interpret = AsyncMock(return_value=action('STOP', duration=4000))
        self.socket = EventSocket()
        self.a.ws = self.socket
        self.a.reader = asyncio.create_task(self.a._read())

    async def asyncTearDown(self):
        await self.a.stop(graceful=False)
        tasks = tuple(self.b.intent_tasks | self.b.tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def finish_semantic(self):
        worker = self.a.transcript_worker
        if worker is not None:
            await asyncio.wait_for(asyncio.shield(worker), 2)
        # start_intent retains the production task runner; wait for its prepared proposal.
        for _ in range(3):
            tasks = tuple(self.b.intent_tasks)
            if not tasks:
                break
            await asyncio.wait_for(asyncio.gather(*tasks), 2)
        await asyncio.sleep(0)

    async def blocked_classifier(self, first, second=None):
        entered, release = asyncio.Event(), asyncio.Event()
        count = 0

        async def interpret(*_):
            nonlocal count
            count += 1
            if count == 1:
                entered.set()
                await release.wait()
                return first
            return second if second is not None else non_action('clarify')

        self.a.interpret.side_effect = interpret
        return entered, release

    async def test_undelegated_semantic_stop_submits_once_without_second_model_call(self):
        await self.socket.feed(transcript(0, 500, 'とどまって'))
        await self.finish_semantic()
        self.a.interpret.assert_awaited_once()
        self.assertEqual(self.a.interpret.await_args.args[0], 'とどまって')
        self.b.adapter.send_action.assert_awaited_once_with('STOP', 1)
        self.assertIsNone(self.b.requests[1]['delegationId'])
        dispatches = [c.kwargs for c in self.b.log.call_args_list if c.args[0] == 'voice_intent_dispatch']
        self.assertEqual(len(dispatches), 1)
        self.assertTrue(dispatches[0]['inputId'].startswith('utterance-'))
        self.assertIsNone(dispatches[0].get('delegationId'))

    async def test_question_and_clarify_preserve_existing_pending_task_and_execution(self):
        self.b.activate_execution('already-running', 'FORWARD', 'until_next_command', None)
        execution = self.b.active_execution
        pending = self.b.task(asyncio.Event().wait(), intent=True)
        try:
            for index, kind in enumerate(('question', 'clarify')):
                self.a.interpret.return_value = non_action(kind)
                before = self.b.intent_revision
                await self.socket.feed(transcript(index * 500, (index + 1) * 500, '右は危ない？'))
                worker = self.a.transcript_worker
                if worker is not None:
                    await asyncio.wait_for(asyncio.shield(worker), 2)
                self.assertEqual(self.a.interpret.await_count, index + 1)
                self.assertEqual(self.b.intent_revision, before)
                self.assertIs(self.b.active_execution, execution)
                self.assertFalse(pending.done())
                self.assertFalse(pending.cancelled())
            self.b.adapter.send_action.assert_not_awaited()
        finally:
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)

    async def test_nonfinal_question_waits_without_consuming_caption(self):
        self.a.interpret.return_value = non_action('question')
        with patch.object(self.a, 'claim_transcript', wraps=self.a.claim_transcript) as claim:
            await self.socket.feed(transcript(0, 500, '今どういう状態？'))
            await self.finish_semantic()
            claim.assert_not_called()
        # Initial ASR redirects presentation, but does not answer or claim
        # the still-incomplete utterance as a semantic question.
        self.a.append.assert_awaited_once()
        self.assertEqual(self.a.append.await_args.args[0], 'instructions')
        self.b.adapter.send_action.assert_not_awaited()

    def test_large_context_is_complete_and_stale_facts_are_omitted(self):
        # This is the legacy structured-context branch. Neural-enabled
        # questions intentionally use compact_summary instead of JSON.
        self.b.neural.enabled = False
        self.b.intent_context = Mock(return_value={
            'activeCommand': {'action': 'FORWARD', 'brainApplied': True},
            'localSafety': {'fresh': False, 'facts': {'groundPresent': True}},
            'stale': False, 'interpretation': '長い神経報告' * 200})
        self.b.blind_script.current_fact = Mock(return_value='長い場面観測' * 200)
        message = self.b.non_action_reply_context('状態は？', 'question')
        self.assertLessEqual(len(message), 380)
        payload = json.loads(message[message.index('{'):])
        self.assertEqual(payload['active'], 'FORWARD')
        self.assertTrue(payload['brainApplied'])
        self.assertFalse(payload['localFresh'])
        self.assertEqual(payload['facts'], {})
        self.assertNotIn('scene', payload)
        self.assertNotIn('neural', payload)

    async def test_unclassified_caption_does_not_cancel_pending_intent(self):
        pending = self.b.task(asyncio.Event().wait(), intent=True)
        entered, release = await self.blocked_classifier(non_action('clarify'))
        try:
            await self.socket.feed(transcript(0, 200, '指示の途中'))
            await asyncio.wait_for(entered.wait(), 1)
            self.assertFalse(pending.done())
            self.assertFalse(pending.cancelled())
            self.assertEqual(self.b.intent_revision, 0)
            self.b.adapter.send_action.assert_not_awaited()
        finally:
            release.set()
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
        await self.finish_semantic()

    async def test_split_negation_discards_prior_stop_result(self):
        entered, release = await self.blocked_classifier(action('STOP', duration=4000), non_action('clarify'))
        await self.socket.feed(transcript(0, 200, '止まって'))
        await asyncio.wait_for(entered.wait(), 1)
        await self.socket.feed(transcript(200, 400, 'はいけない'))
        release.set()
        await self.finish_semantic()
        self.b.adapter.send_action.assert_not_awaited()
        self.assertEqual(self.b.intent_revision, 0)
        self.assertEqual(self.a.interpret.await_args_list[1].args[0], '止まってはいけない')
        self.assertEqual(self.a.interpret.await_count, 2)

    async def test_direction_correction_discards_old_result_and_submits_only_corrected_action(self):
        entered, release = await self.blocked_classifier(action('TURN_R', duration=4000), action('TURN_L', duration=4000))
        await self.socket.feed(transcript(0, 200, '右へ'))
        await asyncio.wait_for(entered.wait(), 1)
        await self.socket.feed(transcript(200, 400, '、いや左へ'))
        release.set()
        await self.finish_semantic()
        self.b.adapter.send_action.assert_awaited_once_with('TURN_L', 1)
        self.assertEqual(self.a.interpret.await_count, 2)
        self.assertEqual(self.a.interpret.await_args_list[1].args[0], '右へ、いや左へ')

    async def test_live_delegation_joins_pending_classification_without_restarting_it(self):
        entered, release = await self.blocked_classifier(action('FORWARD', duration=4000), action('STOP', duration=4000))
        await self.socket.feed(transcript(0, 500, '前へ'))
        await asyncio.wait_for(entered.wait(), 1)
        await self.socket.feed(delegation(500, 'actual-live-delegation'))
        release.set()
        await self.finish_semantic()
        self.b.adapter.send_action.assert_awaited_once_with('FORWARD', 1)
        self.assertEqual(self.b.requests[1]['delegationId'], 'actual-live-delegation')
        self.assertEqual(self.a.interpret.await_count, 1)

    async def test_quiet_completed_short_request_skips_model_and_late_delegation(self):
        self.a.interpret = ConversationAdapter.interpret.__get__(self.a)
        self.a.http = object()
        self.a.last_voice_end_ms = 500
        self.a.sent_audio_samples = 19200  # 800 ms; the last 300 ms are quiet.
        with patch('Runtime.Bridge.conversation.interpret_intent', new=AsyncMock()) as model:
            await self.socket.feed(transcript(0, 500, '前に進んで'))
            await self.finish_semantic()
            await self.socket.feed(delegation(500, 'late'))
            await self.finish_semantic()
            model.assert_not_awaited()
        self.a.http = None
        self.b.adapter.send_action.assert_awaited_once_with('FORWARD', 1)
        self.assertEqual(self.a.last_interpret_route, 'rules')

    async def test_speech_still_in_progress_does_not_execute_a_short_prefix(self):
        self.a.last_voice_end_ms = 500
        self.a.sent_audio_samples = 12000
        await self.socket.feed(transcript(0, 500, '止まって'))
        await asyncio.sleep(.035)
        self.a.interpret.assert_not_awaited()
        await self.socket.feed(transcript(500, 700, 'はいけない'))
        self.a.interpret.return_value = non_action('clarify')
        self.a.last_voice_end_ms = 700
        self.a.sent_audio_samples = 24000
        await self.finish_semantic()
        self.assertEqual(self.a.interpret.await_args.args[0], '止まってはいけない')
        self.b.adapter.send_action.assert_not_awaited()

    async def test_duplicate_transcript_event_id_and_two_delegations_share_one_receipt(self):
        event = dict(transcript(0, 500, '止まって'), event_id='same-transcript')
        await self.socket.feed(event, event, delegation(400, 'a'), delegation(500, 'b'))
        await self.finish_semantic()
        self.a.interpret.assert_awaited_once()
        self.assertEqual(self.a.interpret.await_args.args[0], '止まって')
        self.b.adapter.send_action.assert_awaited_once_with('STOP', 1)

    async def test_continuous_background_sound_falls_back_to_semantics_instead_of_locking_input(self):
        self.a.last_voice_end_ms = 500
        self.a.sent_audio_samples = 12000
        await self.socket.feed(transcript(0, 500, '止まって'), delegation(500, 'noisy'))
        self.a.transcript_changed_at = asyncio.get_running_loop().time() - 1.01
        await self.finish_semantic()
        self.a.interpret.assert_awaited_once()
        self.assertFalse(self.a.interpret.await_args.args[1]['utteranceFinalized'])
        self.b.adapter.send_action.assert_awaited_once_with('STOP', 1)

    async def test_stop_epoch_change_discards_old_semantic_result(self):
        entered, release = await self.blocked_classifier(action('FORWARD', duration=4000))
        await self.socket.feed(transcript(0, 500, '進んで'))
        await asyncio.wait_for(entered.wait(), 1)
        self.b.arbiter.inhibit('explicit-stop')
        await self.b.submit('STOP', 'safety', 'new-stop')
        release.set()
        await self.finish_semantic()
        self.b.adapter.send_action.assert_awaited_once_with('STOP', 1)
        self.assertIsNone(self.b.active_execution)

    async def test_new_intent_revision_discards_old_semantic_result(self):
        entered, release = await self.blocked_classifier(action('FORWARD', duration=4000))
        await self.socket.feed(transcript(0, 500, '進んで'))
        await asyncio.wait_for(entered.wait(), 1)
        self.b.intent_revision += 1
        release.set()
        await self.finish_semantic()
        self.b.adapter.send_action.assert_not_awaited()
        self.assertEqual(self.b.intent_revision, 1)

    async def test_late_same_offset_live_delegation_cannot_reconsume_claimed_text(self):
        await self.socket.feed(transcript(0, 500, 'とどまって'))
        await self.finish_semantic()
        self.assertEqual(self.a.last_offset, 500)
        self.assertFalse(self.a.fragments)
        await self.socket.feed(delegation(500, 'late-live-delegation'))
        await self.finish_semantic()
        self.a.interpret.assert_awaited_once()
        self.b.adapter.send_action.assert_awaited_once_with('STOP', 1)
        self.assertEqual(self.a.diagnostics()['delegationWithoutTranscript'], 1)

    async def test_chat_only_neither_schedules_nor_classifies_transcript(self):
        self.a.interaction = self.b.conversation_interaction = 'chat_only'
        await self.socket.feed(transcript(0, 500, '止まって'))
        self.assertIsNone(self.a.transcript_worker)
        candidate = {'inputId': 'probe', 'generation': self.a.context_generation,
                     'revision': self.a.transcript_revision, 'fragments': tuple(self.a.fragments)}
        await self.b.transcript_utterance('止まって', candidate)
        self.a.interpret.assert_not_awaited()
        self.b.adapter.send_action.assert_not_awaited()

    async def test_failed_candidate_is_not_automatically_retried(self):
        self.a.interpret.side_effect = ConversationError('intent_translation_failed')
        await self.socket.feed(transcript(0, 500, 'とどまって'))
        await self.finish_semantic()
        await asyncio.sleep(.04)
        self.assertIsNone(self.a.transcript_worker)
        self.a.interpret.assert_awaited_once()
        self.b.adapter.send_action.assert_not_awaited()
        self.assertEqual(self.b.intent_revision, 0)

    async def test_semantic_update_reuses_original_context_without_brain_resubmission(self):
        self.b.activate_execution('already-running', 'FORWARD', 'until_next_command', None)
        self.a.interpret.return_value = update(target='already-running')
        await self.socket.feed(transcript(0, 500, 'そのまま'))
        await self.finish_semantic()
        self.a.interpret.assert_awaited_once()
        self.b.adapter.send_action.assert_not_awaited()
        self.assertEqual(self.b.current_execution()['executionId'], 'already-running')
        self.assertTrue(any(c.args[0] == 'execution_updated' for c in self.b.log.call_args_list))

    async def test_semantic_plan_reuses_one_model_result_in_existing_plan_entrypoint(self):
        proposal = action(duration=4000)
        proposal.update(kind='plan', action=None, plan='right_then_forward')
        self.a.interpret.return_value = proposal
        self.b.plans.begin = AsyncMock()
        await self.socket.feed(transcript(0, 500, '右側に進んで'))
        await self.finish_semantic()
        self.a.interpret.assert_awaited_once()
        self.b.plans.begin.assert_awaited_once()
        call = self.b.plans.begin.await_args
        self.assertEqual(call.args[0], 'right_then_forward')
        self.assertEqual(call.args[2:5], (self.b.arbiter.epoch, self.b.conversation_generation, 4000))
        self.assertEqual(call.kwargs['execution_mode'], 'timed')
        self.assertNotIn('delegation_id', call.kwargs)

    async def test_new_context_generation_rejects_old_candidate(self):
        entered, release = await self.blocked_classifier(action('FORWARD', duration=4000))
        await self.socket.feed(transcript(0, 500, '進んで'))
        await asyncio.wait_for(entered.wait(), 1)
        self.a.context_generation += 1
        release.set()
        await self.finish_semantic()
        self.b.adapter.send_action.assert_not_awaited()

    def assert_rejected(self, reason):
        self.assertTrue(any(c.args[0].get('stage') == 'rejected'
                            and c.args[0].get('reason') == reason for c in self.b.emit.call_args_list), reason)

    async def test_delta_after_claim_before_prepared_player_starts_is_rejected(self):
        entered, release = asyncio.Event(), asyncio.Event()
        original = self.b.player_intent

        async def pause_before_player(*args, **kwargs):
            entered.set()
            await release.wait()
            await original(*args, **kwargs)

        self.b.player_intent = pause_before_player
        self.a.interpret.return_value = action('FORWARD', duration=4000)
        await self.socket.feed(transcript(0, 500, '進んで'))
        await asyncio.wait_for(entered.wait(), 1)
        self.assertEqual(self.a.last_offset, 500)
        # Receive the revision through the production reader without launching
        # another classifier that could mask the admission guard by cancelling it.
        self.a.on_transcript = None
        await self.socket.feed(transcript(500, 700, 'はいけない'))
        release.set()
        await self.finish_semantic()
        self.assert_rejected('stale_transcript')
        self.b.adapter.send_action.assert_not_awaited()

    async def check_cancel_wait_revision(self, kind):
        entered, release = asyncio.Event(), asyncio.Event()

        async def paused_cancel():
            entered.set()
            await release.wait()

        self.b.plans.cancel_and_wait = paused_cancel
        proposal = action('FORWARD', duration=4000)
        if kind == 'plan':
            proposal.update(kind='plan', action=None, plan='right_then_forward')
            self.b.local_observation.accept({
                'type': 'local_safety_observation', 'controlEpoch': self.b.arbiter.epoch,
                'conversationGeneration': self.b.conversation_generation, 'sequence': 1,
                'ageMs': 0, 'groundPresent': True, 'leftEdge': 'safe', 'rightEdge': 'safe',
                'forwardBlocked': False, 'bodyUnsafe': False})
        self.a.interpret.return_value = proposal
        await self.socket.feed(transcript(0, 500, '右側へ進んで'))
        await asyncio.wait_for(entered.wait(), 1)
        self.a.on_transcript = None
        await self.socket.feed(transcript(500, 700, 'はいけない'))
        release.set()
        await self.finish_semantic()
        self.assert_rejected('stale_transcript')
        self.b.adapter.send_action.assert_not_awaited()
        self.assertIsNone(self.b.plans.active)

    async def test_action_cancel_wait_rechecks_prepared_transcript(self):
        await self.check_cancel_wait_revision('action')

    async def test_plan_cancel_wait_rechecks_prepared_transcript(self):
        await self.check_cancel_wait_revision('plan')

    async def test_finalized_non_action_claims_once_and_replies(self):
        for kind in ('question', 'clarify'):
            self.a.interpret.return_value = non_action(kind)
            candidate = {'inputId': 'final-' + kind, 'finalized': True}
            with patch.object(self.a, 'transcript_is_current', return_value=True), \
                    patch.object(self.a, 'claim_transcript', return_value=True) as claim:
                await self.b.transcript_utterance('こんにちは', candidate)
                claim.assert_called_once_with(candidate)
        self.assertEqual([call.args[0] for call in self.a.append.await_args_list],
                         ['thinking', 'instructions', 'thinking', 'instructions'])
        self.assertTrue(all(len(call.args[1]) <= 380 for call in self.a.append.await_args_list))
        self.assertEqual(self.b.intent_revision, 0)
        self.b.adapter.send_action.assert_not_awaited()

    async def test_single_oversized_delta_never_executes_its_truncated_text(self):
        await self.socket.feed(transcript(0, 500, 'あ' * 2001))
        await self.finish_semantic()
        self.assertTrue(self.a.transcript_overflow)
        self.a.interpret.assert_not_awaited()
        self.b.adapter.send_action.assert_not_awaited()
        await self.socket.feed(delegation(500, 'overflow-delegation'))
        self.a.interpret.assert_not_awaited()
        self.b.adapter.send_action.assert_not_awaited()

    async def test_accumulated_character_overflow_never_executes_suffix_and_gap_recovers(self):
        await self.socket.feed(transcript(0, 200, 'あ' * 1000), transcript(200, 500, 'い' * 1001),
                               transcript(500, 600, '止まって'))
        await self.finish_semantic()
        self.assertTrue(self.a.transcript_overflow)
        self.a.interpret.assert_not_awaited()
        await self.socket.feed(transcript(2101, 2400, '止まって'))
        await self.finish_semantic()
        self.assertFalse(self.a.transcript_overflow)
        self.a.interpret.assert_awaited_once()
        self.assertEqual(self.a.interpret.await_args.args[0], '止まって')
        self.b.adapter.send_action.assert_awaited_once_with('STOP', 1)

    async def test_fragment_count_overflow_never_executes_evicted_suffix_and_gap_recovers(self):
        fragments = [transcript(i * 2, i * 2 + 1, 'あ') for i in range(160)]
        fragments.append(transcript(320, 321, '止まって'))
        await self.socket.feed(*fragments)
        await self.finish_semantic()
        self.assertTrue(self.a.transcript_overflow)
        self.assertEqual(len(self.a.fragments), 160)
        self.a.interpret.assert_not_awaited()
        await self.socket.feed(transcript(1822, 2000, '止まって'))
        await self.finish_semantic()
        self.assertFalse(self.a.transcript_overflow)
        self.a.interpret.assert_awaited_once()
        self.assertEqual(self.a.interpret.await_args.args[0], '止まって')
        self.b.adapter.send_action.assert_awaited_once_with('STOP', 1)

    async def test_1500ms_gap_boundary_retains_pending_text_and_larger_gap_retires_it(self):
        self.a.interpret.return_value = non_action('clarify')
        await self.socket.feed(transcript(0, 500, '未完の'))
        await self.finish_semantic()
        await self.socket.feed(transcript(2000, 2100, '言葉'))
        await self.finish_semantic()
        self.assertEqual(self.a.interpret.await_args.args[0], '未完の言葉')
        await self.socket.feed(transcript(3601, 3800, '新しい言葉'))
        await self.finish_semantic()
        self.assertEqual(self.a.interpret.await_args.args[0], '新しい言葉')
        self.b.adapter.send_action.assert_not_awaited()

    async def test_clear_context_releases_worker_slot_before_its_cancel_finishes(self):
        entered, _ = await self.blocked_classifier(action('FORWARD', duration=4000), action('STOP', duration=4000))
        await self.socket.feed(transcript(0, 500, '前へ'))
        await asyncio.wait_for(entered.wait(), 1)
        old = self.a.transcript_worker
        self.a.clear_context()
        self.assertIsNone(self.a.transcript_worker)
        await self.socket.feed(transcript(500, 800, '止まって'))
        await self.finish_semantic()
        await asyncio.gather(old, return_exceptions=True)
        self.a.interpret.assert_awaited()
        self.assertEqual(self.a.interpret.await_count, 2)
        self.b.adapter.send_action.assert_awaited_once_with('STOP', 1)

    async def test_speculative_timeout_cancels_model_and_does_not_retry_or_touch_current_intent(self):
        self.b.config['control']['maxIntentAgeMs'] = 30
        cancelled = asyncio.Event()

        async def stalled(*_):
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        self.a.interpret.side_effect = stalled
        await self.socket.feed(transcript(0, 500, '進んで'))
        await self.finish_semantic()
        self.assertTrue(cancelled.is_set())
        self.a.interpret.assert_awaited_once()
        self.assertEqual(self.b.intent_revision, 0)
        self.b.adapter.send_action.assert_not_awaited()
        self.assertTrue(any(c.args[0] == 'transcript_candidate_result'
                            and c.kwargs.get('reason') == 'classification_timeout'
                            for c in self.b.log.call_args_list))

    async def test_new_delta_cancels_only_speculative_model_and_starts_current_candidate(self):
        entered, cancelled = asyncio.Event(), asyncio.Event()
        pending = self.b.task(asyncio.Event().wait(), intent=True)
        calls = 0

        async def interpret(*_):
            nonlocal calls
            calls += 1
            if calls == 1:
                entered.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    cancelled.set()
            return non_action('clarify')

        self.a.interpret.side_effect = interpret
        try:
            await self.socket.feed(transcript(0, 500, 'その'))
            await asyncio.wait_for(entered.wait(), 1)
            old = self.a.transcript_worker
            await self.socket.feed(transcript(500, 800, '指示'))
            worker = self.a.transcript_worker
            if worker is not None:
                await asyncio.wait_for(asyncio.shield(worker), 2)
            await asyncio.gather(old, return_exceptions=True)
            self.assertTrue(cancelled.is_set())
            self.assertEqual(calls, 2)
            self.assertFalse(pending.done())
            self.assertEqual(self.b.intent_revision, 0)
        finally:
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)

    async def test_late_claimed_delegation_does_not_emit_incomplete_transcript_reply(self):
        await self.socket.feed(transcript(0, 500, 'とどまって'))
        await self.finish_semantic()
        self.a.append.reset_mock()
        await self.socket.feed(delegation(500, 'late-live'))
        await self.finish_semantic()
        self.a.append.assert_not_awaited()
        self.b.adapter.send_action.assert_awaited_once_with('STOP', 1)


if __name__ == '__main__':
    unittest.main()
