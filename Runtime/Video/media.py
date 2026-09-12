"""A bounded latest-frame mailbox, independent of Brain state and wall clocks."""
from __future__ import annotations

import asyncio
from collections import OrderedDict, deque
from fractions import Fraction
import io
import time

import av
from aiortc import VideoStreamTrack
from aiortc.mediastreams import MediaStreamError
from PIL import Image

STALE_SECONDS = 2.0
LEASE_SECONDS = 5.0
MAX_PIXELS = 1920 * 1080
RATE_WINDOW_SECONDS = 5.0
RATE_WINDOW_SAMPLES = 60
MAX_COUNTER = (1 << 63) - 1
MAX_FRAME_AGE_MS = 86_400_000
IDENTITY_KEYS = ('instanceId', 'sessionId', 'backendId', 'datasetId',
                 'configHash', 'graphHash', 'sourceHash', 'frameAgeMs',
                 'frameSequence')
PUBLISHER_METRIC_KEYS = ('captureMs', 'encodeMs', 'uploadMs', 'gameFps',
                         'videoFps', 'jpegBytes', 'diagnosticsOverlay')


def decode_jpeg(body: bytes) -> av.VideoFrame:
    with Image.open(io.BytesIO(body)) as image:
        if image.format != 'JPEG' or not (16 <= image.width <= 1920 and 16 <= image.height <= 1080):
            raise ValueError('JPEG dimensions must be 16..1920 by 16..1080')
        if image.width * image.height > MAX_PIXELS:
            raise ValueError('Frame too large')
        return av.VideoFrame.from_image(image.convert('RGB'))


class Stream:
    def __init__(self, stream_id: str):
        self.id = stream_id
        self.publisher = None
        self.source = None
        self.identity_signature = None
        self.sequence = -1
        self.frame = None
        self.received = 0.0
        self.generation = 0
        self.revision = 0
        self.event = asyncio.Event()
        self.busy = False
        self.received_frames = 0
        self.received_bytes = 0
        self.decode_ms = None
        self.rate_samples = deque(maxlen=RATE_WINDOW_SAMPLES)
        self.publisher_metrics = {key: None for key in PUBLISHER_METRIC_KEYS}
        self.probe_nonce = 0
        # Retain only a small high-water set so an expired publisher cannot replay
        self.probe_expires = 0.0
        # an older in-flight frame into a later stream generation.
        self.publisher_high_water = OrderedDict()

    @staticmethod
    def _identity_signature(source: dict):
        identity = source.get('brainIdentity')
        if identity is None:
            return None
        return tuple(identity[key] for key in IDENTITY_KEYS
                     if key not in ('frameAgeMs', 'frameSequence'))

    def is_live(self, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        return self.frame is not None and now - self.received < STALE_SECONDS

    def lease_expired(self, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        return self.publisher is not None and now - self.received >= LEASE_SECONDS

    def expire_publisher(self, now: float | None = None) -> bool:
        if not self.lease_expired(now):
            return False
        self.publisher = None
        self.source = None
        self.identity_signature = None
        self.sequence = -1
        self.frame = None
        self.received = 0.0
        self.probe_nonce = 0
        self.publisher_metrics = {key: None for key in PUBLISHER_METRIC_KEYS}
        self.generation += 1
        self.revision += 1
        self.event.set()
        self.event = asyncio.Event()
        return True

    def accepts_sequence(self, publisher: str, sequence: int) -> bool:
        previous = self.publisher_high_water.get(publisher)
        return previous is None or sequence > previous

    def _record_sequence(self, publisher: str, sequence: int):
        self.publisher_high_water[publisher] = sequence
        self.publisher_high_water.move_to_end(publisher)
        while len(self.publisher_high_water) > 16:
            self.publisher_high_water.popitem(last=False)

    def _source_snapshot(self, age: float | None = None):
        if self.source is None:
            return None
        result = dict(self.source)
        identity = self.source.get('brainIdentity')
        if identity is not None:
            result['brainIdentity'] = dict(identity)
            elapsed_ms = round((time.monotonic() - self.received if age is None else age) * 1000)
            result['brainIdentity']['frameAgeMs'] = min(
                MAX_FRAME_AGE_MS, identity['frameAgeMs'] + max(0, elapsed_ms))
        return result

    def _metrics(self, now: float) -> dict:
        while len(self.rate_samples) > 1 and now - self.rate_samples[0][0] > RATE_WINDOW_SECONDS:
            self.rate_samples.popleft()
        ingress_fps = None
        ingress_kbps = None
        if len(self.rate_samples) > 1:
            first_time = self.rate_samples[0][0]
            elapsed = self.rate_samples[-1][0] - first_time
            if elapsed > 0:
                ingress_fps = round((len(self.rate_samples) - 1) / elapsed, 3)
                ingress_kbps = round(sum(sample[1] for sample in list(self.rate_samples)[1:]) * 8 / elapsed / 1000, 3)
        return {
            'receivedFrames': self.received_frames,
            'receivedBytes': self.received_bytes,
            'decodeMs': self.decode_ms,
            'ingressFps': ingress_fps,
            'ingressKbps': ingress_kbps,
            'publisher': dict(self.publisher_metrics),
        }

    def status(self, viewers: int = 0) -> dict:
        now = time.monotonic()
        age = now - self.received if self.frame is not None else None
        return {'streamId': self.id, 'state': 'waiting' if age is None else
                ('live' if age < STALE_SECONDS else 'stale'),
                'sequence': self.sequence, 'frameAgeMs': round(age * 1000) if age is not None else None,
                'publisherId': self.publisher, 'source': self._source_snapshot(age),
                'width': self.frame.width if self.frame else None,
                'height': self.frame.height if self.frame else None, 'viewers': viewers,
                'metrics': self._metrics(now)}

    def publish(self, publisher: str, sequence: int, source: dict, publisher_metrics: dict,
                frame: av.VideoFrame, frame_bytes: int, decode_ms: float) -> bool:
        binding_changed = publisher != self.publisher or self._identity_signature(source) != self.identity_signature
        if binding_changed:
            self.generation += 1
        self._record_sequence(publisher, sequence)
        self.publisher, self.sequence, self.source = publisher, sequence, source
        self.identity_signature = self._identity_signature(source)
        self.frame, self.received = frame, time.monotonic()
        self.received_frames = min(MAX_COUNTER, self.received_frames + 1)
        self.received_bytes = min(MAX_COUNTER, self.received_bytes + frame_bytes)
        self.decode_ms = round(max(0.0, decode_ms), 3)
        self.rate_samples.append((self.received, frame_bytes))
        self.publisher_metrics = dict(publisher_metrics)
        if binding_changed or self.publisher_metrics['diagnosticsOverlay'] is not True:
            self.probe_nonce = 0
        self.revision += 1
        self.event.set()
        self.event = asyncio.Event()
        return binding_changed

    def set_probe(self, nonce: int):
        self.probe_nonce = nonce
        self.probe_expires = time.monotonic() + 10.0

    def take_probe(self) -> int:
        if (not self.is_live() or self.publisher_metrics['diagnosticsOverlay'] is not True
                or time.monotonic() >= self.probe_expires):
            return 0
        return self.probe_nonce


class LatestVideoTrack(VideoStreamTrack):
    def __init__(self, stream: Stream):
        super().__init__()
        self.stream = stream
        self.generation = stream.generation
        self.revision = -1
        self.started = time.monotonic()
        self.sent = 0.0
        self.pts = -1

    async def recv(self):
        # Never queue history or synthesize fresh timestamps for a stopped source.
        while self.readyState == 'live':
            if self.generation != self.stream.generation:
                self.stop()
                raise MediaStreamError
            if (self.stream.revision != self.revision and self.stream.frame is not None
                    and time.monotonic() - self.stream.received < STALE_SECONDS):
                await asyncio.sleep(max(0, self.sent + 1 / 30 - time.monotonic()))
                if self.generation != self.stream.generation:
                    continue
                self.revision = self.stream.revision
                # Separate frame object per viewer: encoder PTS mutation cannot race.
                frame = self.stream.frame.reformat(format='yuv420p')
                self.sent = time.monotonic()
                self.pts = max(self.pts + 1, round((self.sent - self.started) * 90000))
                frame.pts, frame.time_base = self.pts, Fraction(1, 90000)
                return frame
            try:
                await asyncio.wait_for(self.stream.event.wait(), timeout=0.5)
            except asyncio.TimeoutError:
                pass
        raise MediaStreamError
