"""Bounded GPT-Live WebRTC transport with the ConversationAdapter WS interface.

aiortc/av are optional until connect; no credential, SDP or provider error logging.
"""
import asyncio
import base64
import json
import importlib
from fractions import Fraction

import aiohttp


class LiveWebRTCError(RuntimeError):
    pass


class PCMBuffer:
    """One second maximum input backlog, consumed as paced 20ms frames."""
    def __init__(self):
        self.data = bytearray()
        self.consumed_samples = 0
        self.nonzero_samples = 0

    def append(self, encoded):
        try:
            if not isinstance(encoded, str) or len(encoded) > 64000:
                raise ValueError()
            raw = base64.b64decode(encoded, validate=True)
            if len(raw) % 2 or len(raw) + len(self.data) > 48000:
                raise ValueError()
        except (ValueError, TypeError):
            raise LiveWebRTCError('webrtc_input_audio_invalid_or_full') from None
        self.data.extend(raw)

    def take(self):
        raw = bytes(self.data[:960])
        del self.data[:960]
        self.consumed_samples += len(raw) // 2
        self.nonzero_samples += sum(raw[i:i + 2] != b'\0\0' for i in range(0, len(raw), 2))
        return raw.ljust(960, b'\0')


def _make_track(audio_track, audio_frame, buffer):
    class PCMTrack(audio_track):
        def __init__(self):
            super().__init__()
            self.pts = 0
            self.started_at = None

        async def recv(self):
            loop = asyncio.get_running_loop()
            now = loop.time()
            if self.started_at is None:
                self.started_at = now
            deadline = self.started_at + self.pts / 24000
            if now - deadline > .1:
                # Rebase after suspension rather than bursting missed frames.
                self.started_at = now - self.pts / 24000
                deadline = now
            await asyncio.sleep(max(0, deadline - now))
            frame = audio_frame(format='s16', layout='mono', samples=480)
            frame.planes[0].update(buffer.take())
            frame.sample_rate = 24000
            frame.time_base = Fraction(1, 24000)
            frame.pts = self.pts
            self.pts += 480
            return frame
    return PCMTrack()


class LiveWebRTCTransport:
    def __init__(self):
        self.closed = False
        self.pc = self.track = self.channel = None
        self.input = PCMBuffer()
        self.events = asyncio.Queue(maxsize=256)
        self.tasks = set()
        self.opened = asyncio.Event()
        self.session_id = None

    @property
    def diagnostics(self):
        """Local media consumption only, not remote ASR acceptance or RTP delivery."""
        return {'consumedSamples': self.input.consumed_samples,
                'nonzeroSamples': self.input.nonzero_samples,
                'queuedBytes': len(self.input.data)}

    def _spawn(self, coroutine):
        task = asyncio.create_task(coroutine)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    def _event(self, data):
        if self.closed:
            return
        try:
            if not isinstance(data, str) or len(data) > 262144:
                raise ValueError()
            event = json.loads(data)
            if not isinstance(event, dict):
                raise ValueError()
            self.events.put_nowait(aiohttp.WSMessage(aiohttp.WSMsgType.TEXT, data, ''))
        except (ValueError, asyncio.QueueFull):
            self._spawn(self.close())

    @classmethod
    async def connect(cls, http, endpoint, session, access_pass):
        self = cls()
        try:
            # Loading codec/crypto DLLs can take seconds on a cold machine.
            # Keep Brain reads and safety STOP traffic running throughout.
            rtc, media = await asyncio.to_thread(lambda: (importlib.import_module('aiortc'), importlib.import_module('av')))
            RTCPeerConnection, RTCSessionDescription, AudioStreamTrack = rtc.RTCPeerConnection, rtc.RTCSessionDescription, rtc.AudioStreamTrack
            AudioFrame, AudioResampler = media.AudioFrame, media.AudioResampler
            self.pc = RTCPeerConnection()
            self.track = _make_track(AudioStreamTrack, AudioFrame, self.input)
            self.pc.addTrack(self.track)
            self.channel = self.pc.createDataChannel('oai-events')
            self.channel.on('open', self.opened.set)
            self.channel.on('message', self._event)
            self.channel.on('close', lambda: self._spawn(self.close()))

            @self.pc.on('connectionstatechange')
            async def state_changed():
                if self.pc.connectionState in ('failed', 'closed', 'disconnected'):
                    await self.close()

            @self.pc.on('track')
            def got_track(track):
                if track.kind == 'audio':
                    self._spawn(self._receive_audio(track, AudioResampler))

            async def negotiate():
                await self.pc.setLocalDescription(await self.pc.createOffer())
                async with http.post(endpoint, json={'sdp': self.pc.localDescription.sdp, 'session': session},
                                     headers={'X-Flylingual-Voice-Pass': access_pass},
                                     allow_redirects=False,
                                     timeout=aiohttp.ClientTimeout(total=20)) as response:
                    if response.status not in (200, 201):
                        raise LiveWebRTCError('webrtc_session_rejected')
                    raw = bytearray()
                    async for chunk in response.content.iter_chunked(16384):
                        raw.extend(chunk)
                        if len(raw) > 262144:
                            raise ValueError()
                    if len(raw) > 262144:
                        raise ValueError()
                    answer = json.loads(raw)
                transport = answer['transport']
                if transport['type'] != 'webrtc' or not isinstance(transport['sdp'], str):
                    raise ValueError()
                self.session_id = answer['session']['id']
                if not isinstance(self.session_id, str) or not self.session_id:
                    raise ValueError()
                await self.pc.setRemoteDescription(RTCSessionDescription(sdp=transport['sdp'], type='answer'))
                await self.opened.wait()
            await asyncio.wait_for(negotiate(), 35)
            if self.closed:
                raise LiveWebRTCError('webrtc_connection_closed')
            return self
        except asyncio.CancelledError:
            await self.close()
            raise
        except Exception:
            await self.close()
            raise LiveWebRTCError('webrtc_connection_failed') from None

    async def _receive_audio(self, track, resampler_class):
        resampler = resampler_class(format='s16', layout='mono', rate=24000)
        try:
            while not self.closed:
                frame = await track.recv()
                for converted in resampler.resample(frame):
                    raw = bytes(converted.planes[0])[:converted.samples * 2]
                    self._event(json.dumps({'type': 'session.output_audio.delta',
                                            'delta': base64.b64encode(raw).decode('ascii')}))
        except asyncio.CancelledError:
            raise
        except Exception:
            await self.close()

    async def send_json(self, event):
        if self.closed:
            raise LiveWebRTCError('webrtc_closed')
        kind = event.get('type')
        if kind == 'session.start':
            return  # HTTP already created the session.
        if kind == 'session.input_audio.append':
            self.input.append(event.get('audio'))
            return
        try:
            data = json.dumps(event, ensure_ascii=False, allow_nan=False)
            if len(data) > 262144 or self.channel.readyState != 'open':
                raise ValueError()
            until = asyncio.get_running_loop().time() + 1
            while self.channel.bufferedAmount > 262144:
                if self.closed or asyncio.get_running_loop().time() >= until:
                    raise ValueError()
                await asyncio.sleep(.01)
            self.channel.send(data)
        except Exception:
            raise LiveWebRTCError('webrtc_send_failed') from None

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self.closed and self.events.empty():
            raise StopAsyncIteration
        event = await self.events.get()
        if event is None:
            raise StopAsyncIteration
        return event

    async def close(self):
        if self.closed:
            return
        self.closed = True
        self.opened.set()
        self.input.data.clear()
        while not self.events.empty():
            self.events.get_nowait()
        self.events.put_nowait(None)
        current = asyncio.current_task()
        pending = [task for task in self.tasks if task is not current]
        for task in pending:
            task.cancel()
        if self.track is not None:
            self.track.stop()
        if self.pc is not None:
            try:
                await asyncio.wait_for(self.pc.close(), 3)
            except Exception:
                pass
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
