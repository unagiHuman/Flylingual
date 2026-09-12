"""A bounded latest-frame mailbox, independent of Brain state and wall clocks."""
from __future__ import annotations

import asyncio
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
        self.sequence = -1
        self.frame = None
        self.received = 0.0
        self.generation = 0
        self.revision = 0
        self.event = asyncio.Event()
        self.busy = False

    def status(self, viewers: int = 0) -> dict:
        age = time.monotonic() - self.received if self.frame is not None else None
        return {'streamId': self.id, 'state': 'waiting' if age is None else
                ('live' if age < STALE_SECONDS else 'stale'),
                'sequence': self.sequence, 'frameAgeMs': round(age * 1000) if age is not None else None,
                'publisherId': self.publisher, 'source': self.source,
                'width': self.frame.width if self.frame else None,
                'height': self.frame.height if self.frame else None, 'viewers': viewers}

    def publish(self, publisher: str, sequence: int, source: dict, frame: av.VideoFrame):
        if publisher != self.publisher:
            self.generation += 1
        self.publisher, self.sequence, self.source = publisher, sequence, source
        self.frame, self.received = frame, time.monotonic()
        self.revision += 1
        self.event.set()
        self.event = asyncio.Event()


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
