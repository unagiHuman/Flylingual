import asyncio
import base64
import json
import unittest
import time
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import aiohttp
from Runtime.Bridge.live_webrtc import LiveWebRTCTransport, LiveWebRTCError, PCMBuffer, _make_track


class TransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_events_and_start_not_sent(self):
        transport = LiveWebRTCTransport()
        sent = []
        transport.channel = SimpleNamespace(readyState='open', bufferedAmount=0, send=sent.append)
        await transport.send_json({'type': 'session.start'})
        await transport.send_json({'type': 'session.thinking.append', 'text': 'hello'})
        self.assertEqual(len(sent), 1)
        transport._event('{"type":"session.started","session":{"id":"test"}}')
        msg = await anext(transport)
        self.assertEqual(msg.type, aiohttp.WSMsgType.TEXT)
        self.assertEqual(json.loads(msg.data)['type'], 'session.started')
        await transport.close()

    async def test_pcm_boundaries_padding_and_overload(self):
        transport = LiveWebRTCTransport()
        await transport.send_json({'type': 'session.input_audio.append', 'audio': base64.b64encode(b'\x01\x02'*600).decode()})
        self.assertEqual(transport.input.take(), b'\x01\x02'*480)
        self.assertEqual(transport.input.take(), b'\x01\x02'*120 + b'\0'*720)
        for value in ('?', base64.b64encode(b'x').decode(), 'A'*64004):
            with self.assertRaises(LiveWebRTCError):
                transport.input.append(value)
        transport.input.append(base64.b64encode(b'\0'*48000).decode())
        with self.assertRaises(LiveWebRTCError):
            transport.input.append('AAA=')
        await transport.close()
        self.assertFalse(transport.input.data)

    async def test_close_wakes_reader_cancels_track(self):
        transport = LiveWebRTCTransport()
        transport.pc = SimpleNamespace(close=AsyncMock())
        stopped = []
        transport.track = SimpleNamespace(stop=lambda: stopped.append(True))
        waiting = asyncio.create_task(anext(transport))
        await asyncio.sleep(0)
        await transport.close()
        with self.assertRaises(StopAsyncIteration):
            await waiting
        self.assertEqual(stopped, [True])
        transport.pc.close.assert_awaited_once()
        with self.assertRaises(LiveWebRTCError):
            await transport.send_json({'type': 'anything'})

    async def test_output_resampling_omits_plane_padding(self):
        transport = LiveWebRTCTransport()
        track = SimpleNamespace(recv=AsyncMock(return_value=object()))
        class Resampler:
            def __init__(self, **kwargs):
                self.kwargs = kwargs
            def resample(self, frame):
                track.recv.side_effect = asyncio.CancelledError
                return [SimpleNamespace(planes=[b'\x01\x02\x03\x04padding'], samples=2)]
        task = asyncio.create_task(transport._receive_audio(track, Resampler))
        with self.assertRaises(asyncio.CancelledError):
            await task
        event = json.loads((await anext(transport)).data)
        self.assertEqual(base64.b64decode(event['delta']), b'\x01\x02\x03\x04')
        await transport.close()

    async def test_queue_overload_closes_without_unbounded_growth(self):
        transport = LiveWebRTCTransport()
        for _ in range(257):
            transport._event('{"type":"test"}')
        await asyncio.sleep(0)
        self.assertTrue(transport.closed)
        self.assertLessEqual(transport.events.qsize(), 1)

    async def test_slow_optional_import_does_not_block_event_loop(self):
        importing = threading.Event()
        finished = threading.Event()
        ticks_during_import = []

        def slow_import(name):
            importing.set()
            time.sleep(.15)
            finished.set()
            raise ImportError('simulated optional dependency failure')

        async def ticker():
            while not finished.is_set():
                if importing.is_set():
                    ticks_during_import.append(True)
                await asyncio.sleep(.01)

        ticker_task = asyncio.create_task(ticker())
        try:
            with patch('Runtime.Bridge.live_webrtc.importlib.import_module', side_effect=slow_import):
                with self.assertRaisesRegex(LiveWebRTCError, '^webrtc_connection_failed$'):
                    await LiveWebRTCTransport.connect(None, 'unused', {}, 'unused')
            await ticker_task
        finally:
            ticker_task.cancel()
            await asyncio.gather(ticker_task, return_exceptions=True)
        self.assertTrue(ticks_during_import, 'The loop must tick while optional imports are blocked')

    async def test_negotiation_failure_redacts_and_closes(self):
        pc = SimpleNamespace(close=AsyncMock())
        pc.addTrack = lambda track: None
        def fail(label):
            raise RuntimeError('secret-pass-and-provider-body')
        pc.createDataChannel = fail
        fake_aiortc = SimpleNamespace(RTCPeerConnection=lambda: pc,
                                     RTCSessionDescription=object, AudioStreamTrack=type('Track', (), {'stop': lambda self: None}))
        fake_av = SimpleNamespace(AudioFrame=object, AudioResampler=object)
        with patch.dict('sys.modules', {'aiortc': fake_aiortc, 'av': fake_av}):
            with self.assertRaises(LiveWebRTCError) as error:
                await LiveWebRTCTransport.connect(None, 'unused', {}, 'secret-pass')
        self.assertEqual(str(error.exception), 'webrtc_connection_failed')
        pc.close.assert_awaited_once()

    async def test_absolute_clock_drift_and_long_pause_rebase(self):
        class Frame:
            def __init__(self, **kwargs):
                self.planes = [SimpleNamespace(update=lambda data: None)]
        track = _make_track(object, Frame, PCMBuffer())
        clock = SimpleNamespace(time=lambda: now[0])
        now = [10.0]
        waits = []
        async def sleep(delay):
            waits.append(delay)
            now[0] += delay
        with patch('Runtime.Bridge.live_webrtc.asyncio.get_running_loop', return_value=clock), \
             patch('Runtime.Bridge.live_webrtc.asyncio.sleep', side_effect=sleep):
            await track.recv()
            now[0] += .003  # encoder cost must not accumulate into the next deadline
            await track.recv()
            self.assertAlmostEqual(waits[-1], .017)
            now[0] += .004
            await track.recv()
            self.assertAlmostEqual(waits[-1], .016)
            now[0] += 2  # resume without catching up two seconds of frames
            await track.recv()
            self.assertEqual(waits[-1], 0)
            await track.recv()
            self.assertAlmostEqual(waits[-1], .02)
        self.assertEqual(track.pts, 5 * 480)

    async def test_safe_consumption_diagnostics(self):
        transport = LiveWebRTCTransport()
        transport.input.append(base64.b64encode(b'\0\0\x01\0\0\x01').decode())
        self.assertEqual(transport.diagnostics['queuedBytes'], 6)
        transport.input.take()
        self.assertEqual(transport.diagnostics,
                         {'consumedSamples': 3, 'nonzeroSamples': 2, 'queuedBytes': 0})
        transport.input.take()  # locally generated padding is not player consumption
        self.assertEqual(transport.diagnostics['consumedSamples'], 3)
        await transport.close()

    async def test_track_clock_and_samples(self):
        class Track:
            pass
        class Frame:
            def __init__(self, **kwargs):
                self.planes = [SimpleNamespace(update=lambda data: setattr(self, 'data', data))]
        track = _make_track(Track, Frame, PCMBuffer())
        first = await track.recv()
        second = await track.recv()
        self.assertEqual((first.pts, second.pts, second.sample_rate), (0, 480, 24000))
        self.assertEqual(len(second.data), 960)


if __name__ == '__main__':
    unittest.main()
