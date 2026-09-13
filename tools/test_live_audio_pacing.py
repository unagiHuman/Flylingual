"""Network-free pacing checks for Live PCM transport."""
import asyncio
import copy
import unittest
from unittest.mock import AsyncMock, patch

from Runtime.Bridge.config import _DEFAULT
from Runtime.Bridge.conversation import ConversationAdapter, ConversationError


class FakeLoop:
    def __init__(self): self.now = 0.0
    def time(self): return self.now


class LiveAudioPacingTests(unittest.IsolatedAsyncioTestCase):
    async def run_sender(self, latency, oversleep=0.0, player_audio=True, sends_to=3):
        adapter = ConversationAdapter(copy.deepcopy(_DEFAULT['conversation']), AsyncMock(), AsyncMock())
        adapter.state = 'live'
        if player_audio: adapter.audio_queue.put_nowait(bytes(4800))
        clock, starts, sends = FakeLoop(), [], 0

        extras = iter(oversleep) if isinstance(oversleep, (list, tuple)) else None
        async def sleep(delay):
            extra = next(extras, 0.0) if extras is not None else oversleep
            clock.now += delay + extra

        async def send_event(_event):
            nonlocal sends
            starts.append(clock.now)
            sends += 1
            clock.now += latency
            if sends == sends_to: raise ConversationError('test_stop')

        adapter._send_event = send_event
        with patch('Runtime.Bridge.conversation.asyncio.get_running_loop', return_value=clock), \
             patch('Runtime.Bridge.conversation.asyncio.sleep', side_effect=sleep):
            await adapter._send_audio()
        return adapter, starts

    async def test_send_cost_is_inside_the_100ms_period_and_counters_survive(self):
        adapter, starts = await self.run_sender(latency=.02)
        self.assertEqual([round(value, 3) for value in starts], [.1, .2, .3])
        diagnostics = adapter.diagnostics()
        self.assertEqual(diagnostics['sentInputChunks'], 1)
        self.assertEqual(diagnostics['sentInputBytes'], 4800)
        # The third fake write stops before production increments its counter.
        self.assertEqual(diagnostics['clockSilenceChunks'], 1)

    async def test_slow_send_uses_its_actual_start_without_a_past_deadline(self):
        _adapter, starts = await self.run_sender(latency=.25)
        self.assertEqual([round(value, 3) for value in starts], [.1, .35, .6])
        self.assertEqual(starts, sorted(starts))

    async def test_event_loop_oversleep_keeps_bounded_intervals(self):
        _adapter, starts = await self.run_sender(latency=.02, oversleep=[.4], player_audio=False)
        self.assertEqual([round(value, 3) for value in starts], [.5, .59, .68])
        self.assertTrue(all(later - earlier >= .09 - 1e-9 for earlier, later in zip(starts, starts[1:])))

    async def test_repeated_small_sleep_jitter_returns_to_the_planned_clock(self):
        _adapter, starts = await self.run_sender(latency=.02, oversleep=.003, player_audio=False)
        self.assertEqual([round(value, 3) for value in starts], [.103, .203, .303])

    async def test_periodic_jitter_does_not_accumulate_queue_drift(self):
        oversleeps = [.02 if (index + 1) % 7 == 0 else 0.0 for index in range(200)]
        _adapter, starts = await self.run_sender(latency=.02, oversleep=oversleeps,
                                                 player_audio=False, sends_to=200)
        self.assertLessEqual(starts[-1] - 20.0, .011)

    async def test_long_stall_returns_to_100ms_period_after_bounded_recovery(self):
        _adapter, starts = await self.run_sender(latency=.02, oversleep=[.4],
                                                 player_audio=False, sends_to=45)
        self.assertTrue(all(later - earlier >= .09 - 1e-9 for earlier, later in zip(starts, starts[1:])))
        self.assertAlmostEqual(starts[-1] - starts[-2], .1, places=6)


if __name__ == '__main__':
    unittest.main()
