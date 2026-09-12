"""Unity JPEG ingress -> VP8/H264 WebRTC. No Brain/control/API dependency."""
from __future__ import annotations

import asyncio
import base64
import binascii
import contextlib
import hmac
import json
import logging
import math
import os
import re
import time
import uuid

from aiohttp import web
from aiortc import RTCConfiguration, RTCIceServer, RTCPeerConnection, RTCSessionDescription

from .media import (IDENTITY_KEYS, PUBLISHER_METRIC_KEYS,
                    STALE_SECONDS, LatestVideoTrack, Stream, decode_jpeg)

LOG = logging.getLogger('flylingual.video')
MAX_METADATA_BYTES = 4096
MAX_METADATA_BASE64_BYTES = 4 * ((MAX_METADATA_BYTES + 2) // 3)
MAX_NUMBER_MS = 600_000.0
MAX_FRAME_AGE_MS = 86_400_000.0
MAX_FPS = 10_000.0
MAX_JPEG_BYTES = 2 * 1024 * 1024
IDENTITY_TEXT = re.compile(r'^[ -~]{1,128}$')


def failure(status: int, error: str):
    return web.json_response({'error': error}, status=status)


def _finite_number(value, maximum: float):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError('invalid number')
    if value < 0 or value > maximum:
        raise ValueError('out of range')
    value = float(value)
    if not math.isfinite(value) or value < 0 or value > maximum:
        raise ValueError('out of range')
    return value


def parse_frame_metadata(value: str | None) -> tuple[dict, dict | None]:
    """Decode only the small, explicitly versionless publisher telemetry schema."""
    publisher = {key: None for key in PUBLISHER_METRIC_KEYS}
    if value is None:
        return publisher, None
    if not value.isascii() or len(value) > MAX_METADATA_BASE64_BYTES:
        raise ValueError('invalid metadata encoding')
    try:
        decoded = base64.b64decode(value.encode('ascii'), validate=True)
        if len(decoded) > MAX_METADATA_BYTES:
            raise ValueError('metadata too large')
        payload = json.loads(decoded.decode('utf-8'))
    except (UnicodeDecodeError, binascii.Error, json.JSONDecodeError) as exc:
        raise ValueError('invalid metadata encoding') from exc
    if not isinstance(payload, dict) or set(payload) - set(PUBLISHER_METRIC_KEYS) - {'brainIdentity'}:
        raise ValueError('unknown metadata key')

    for key in ('captureMs', 'encodeMs', 'uploadMs'):
        if key in payload:
            publisher[key] = _finite_number(payload[key], MAX_NUMBER_MS)
    for key in ('gameFps', 'videoFps'):
        if key in payload:
            publisher[key] = _finite_number(payload[key], MAX_FPS)
    if 'jpegBytes' in payload:
        jpeg_bytes = _finite_number(payload['jpegBytes'], MAX_JPEG_BYTES)
        if not jpeg_bytes.is_integer():
            raise ValueError('jpegBytes must be integral')
        publisher['jpegBytes'] = int(jpeg_bytes)
    if 'diagnosticsOverlay' in payload:
        if not isinstance(payload['diagnosticsOverlay'], bool):
            raise ValueError('diagnosticsOverlay must be boolean')
        publisher['diagnosticsOverlay'] = payload['diagnosticsOverlay']

    identity = payload.get('brainIdentity')
    if identity is None:
        return publisher, None
    if not isinstance(identity, dict) or set(identity) != set(IDENTITY_KEYS):
        raise ValueError('invalid brain identity')
    for key in IDENTITY_KEYS:
        if key == 'frameAgeMs':
            identity[key] = _finite_number(identity[key], MAX_FRAME_AGE_MS)
        elif key == 'frameSequence':
            if (isinstance(identity[key], bool) or not isinstance(identity[key], int)
                    or not 0 <= identity[key] <= 0x7fffffff):
                raise ValueError('invalid brain identity')
        elif not isinstance(identity[key], str) or not IDENTITY_TEXT.fullmatch(identity[key]):
            raise ValueError('invalid brain identity')
    return publisher, dict(identity)


class VideoBackend:
    def __init__(self, config):
        self.config = config
        self.streams = {name: Stream(name) for name in config['streams']}
        self.peers = {}
        requested_instance_id = os.environ.get('FLY_VIDEO_INSTANCE_ID')
        if requested_instance_id is None:
            self.instance_id = str(uuid.uuid4())
        else:
            try:
                self.instance_id = str(uuid.UUID(requested_instance_id))
            except (AttributeError, ValueError) as exc:
                raise ValueError('Invalid video instance identifier') from exc
        self.started = time.monotonic()

    async def expire_stream(self, stream: Stream) -> bool:
        if not stream.expire_publisher():
            return False
        await asyncio.gather(*(self.close(key) for key, peer in list(self.peers.items())
                               if peer['stream'] is stream))
        LOG.info('VIDEO_PUBLISHER_EXPIRED stream=%s', stream.id)
        return True

    @web.middleware
    async def boundary(self, request, handler):
        hosts = {f'127.0.0.1:{self.config["port"]}', f'localhost:{self.config["port"]}'}
        origin = request.headers.get('Origin')
        if request.host not in hosts or request.remote not in ('127.0.0.1', '::1'):
            return failure(403, 'loopback_only')
        if origin is not None and origin not in self.config['allowedOrigins']:
            return failure(403, 'origin_not_allowed')
        if request.method == 'OPTIONS':
            response = web.Response(status=204)
        else:
            try:
                response = await handler(request)
            except web.HTTPException as exc:
                response = failure(exc.status, exc.reason)
            except Exception:
                # Do not log request bodies, tokens, SDP or local config.
                LOG.error('VIDEO_REQUEST_FAILED')
                response = failure(500, 'internal_error')
        response.headers.update({'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'})
        if origin is not None:
            response.headers.update({'Access-Control-Allow-Origin': origin, 'Vary': 'Origin',
                'Access-Control-Allow-Methods': 'GET, POST, DELETE, OPTIONS',
                'Access-Control-Allow-Headers': 'Content-Type', 'Access-Control-Max-Age': '300'})
        return response

    async def public_config(self, request):
        return web.json_response({'iceServers': self.config['iceServers'],
            'streams': list(self.streams), 'staleAfterMs': int(STALE_SECONDS * 1000)})

    async def health(self, request):
        for stream in self.streams.values():
            await self.expire_stream(stream)
        now = time.monotonic()
        return web.json_response({
            'service': 'flylingual-video',
            'instanceId': self.instance_id,
            'uptimeSeconds': round(max(0.0, now - self.started), 3),
            'viewers': len(self.peers),
            'streams': [stream.status(sum(peer['stream'] is stream for peer in self.peers.values()))
                        for stream in self.streams.values()],
        })

    async def status(self, request):
        stream = self.streams.get(request.match_info['stream'])
        if stream is None:
            return failure(404, 'unknown_stream')
        await self.expire_stream(stream)
        return web.json_response(stream.status(sum(p['stream'] is stream for p in self.peers.values())))

    async def ingest(self, request):
        if not hmac.compare_digest(request.headers.get('Authorization', ''),
                                   'Bearer ' + self.config['publishToken']):
            return failure(401, 'publisher_auth_required')
        # Browser clients must not publish; Unity supplies no Origin header.
        if request.headers.get('Origin') is not None:
            return failure(403, 'native_publisher_required')
        stream = self.streams.get(request.match_info['stream'])
        if stream is None:
            return failure(404, 'unknown_stream')
        await self.expire_stream(stream)
        publisher = request.headers.get('X-Publisher-Id', '')
        sequence = request.headers.get('X-Frame-Sequence', '')
        execution_os = request.headers.get('X-Execution-Os', '')
        label = request.headers.get('X-Source-Label', '')
        if (not re.fullmatch(r'[a-zA-Z0-9-]{8,64}', publisher)
                or not re.fullmatch(r'[0-9]{1,15}', sequence)
                or execution_os not in ('macOS', 'Windows', 'diagnostic')
                or len(label) > 80 or not label.isascii() or not label.isprintable()):
            return failure(400, 'invalid_frame_metadata')
        if request.content_type != 'image/jpeg':
            return failure(415, 'jpeg_required')
        if stream.busy:
            return failure(429, 'publisher_busy')
        if stream.publisher and stream.publisher != publisher:
            return failure(409, 'publisher_slot_in_use')
        if not stream.accepts_sequence(publisher, int(sequence)):
            return failure(409, 'old_frame_sequence')
        try:
            publisher_metrics, brain_identity = parse_frame_metadata(request.headers.get('X-Frame-Metadata'))
        except ValueError:
            return failure(400, 'invalid_frame_metadata')
        stream.busy = True
        try:
            try:
                ingress_started = time.monotonic()
                body = await asyncio.wait_for(request.read(), timeout=3)
                decode_started = time.monotonic()
                frame = await asyncio.to_thread(decode_jpeg, body)
                decode_ms = (time.monotonic() - decode_started) * 1000
            except web.HTTPRequestEntityTooLarge:
                return failure(413, 'frame_too_large')
            except (ValueError, OSError):
                return failure(400, 'invalid_jpeg')
            except asyncio.TimeoutError:
                return failure(408, 'frame_upload_timeout')
            source = {
                'kind': 'diagnostic' if execution_os == 'diagnostic' else 'unity-game',
                'label': label, 'executionOs': execution_os, 'brainIdentity': brain_identity,
            }
            if brain_identity is not None:
                brain_identity['frameAgeMs'] = min(
                    MAX_FRAME_AGE_MS,
                    brain_identity['frameAgeMs'] + max(0.0, (time.monotonic() - ingress_started) * 1000))
            previous_publisher = stream.publisher
            binding_changed = stream.publish(publisher, int(sequence), source, publisher_metrics,
                                             frame, len(body), decode_ms)
            # A new publisher or observed Brain binding must never reuse a peer whose
            # buffered image could have been labelled with the prior binding.
            if binding_changed:
                await asyncio.gather(*(self.close(key) for key, peer in list(self.peers.items())
                                       if peer['stream'] is stream))
            if previous_publisher != publisher:
                LOG.info('VIDEO_PUBLISHER stream=%s os=%s', stream.id, execution_os)
            elif binding_changed:
                LOG.info('VIDEO_SOURCE_BINDING_CHANGED stream=%s', stream.id)
            return web.json_response({'acceptedSequence': stream.sequence,
                                      'probeNonce': stream.take_probe()})
        finally:
            stream.busy = False

    async def offer(self, request):
        stream = self.streams.get(request.match_info['stream'])
        if stream is None:
            return failure(404, 'unknown_stream')
        await self.expire_stream(stream)
        if stream.status()['state'] != 'live':
            return failure(409, 'publisher_not_live')
        if len(self.peers) >= self.config['maxViewers']:
            return failure(429, 'viewer_limit')
        # Reserve capacity before reading a body or performing asynchronous SDP work.
        session = uuid.uuid4().hex
        pc = RTCPeerConnection(RTCConfiguration(iceServers=[RTCIceServer(**s) for s in self.config['iceServers']]))
        peer = {'pc': pc, 'stream': stream, 'generation': stream.generation,
                'created': time.monotonic(), 'track': None}
        self.peers[session] = peer

        @pc.on('connectionstatechange')
        async def state_changed():
            if pc.connectionState in ('failed', 'closed'):
                await self.close(session)

        try:
            body = await asyncio.wait_for(request.read(), timeout=3)
            if len(body) > 128 * 1024 or request.content_type != 'application/json':
                raise ValueError('invalid_offer')
            import json
            params = json.loads(body)
            if (not isinstance(params, dict) or set(params) != {'type', 'sdp'}
                    or params['type'] != 'offer' or not isinstance(params['sdp'], str)
                    or len(params['sdp']) > 120000):
                raise ValueError('invalid_offer')
            # This endpoint supports a single recvonly video m-line, with no data/control channel.
            media = [line for line in params['sdp'].splitlines() if line.startswith('m=')]
            if len(media) != 1 or not media[0].startswith('m=video '):
                raise ValueError('video_only_offer_required')
            directions = [line for line in params['sdp'].splitlines() if line in
                          ('a=recvonly', 'a=sendonly', 'a=sendrecv', 'a=inactive')]
            if directions != ['a=recvonly']:
                raise ValueError('recvonly_video_required')
            await asyncio.wait_for(pc.setRemoteDescription(RTCSessionDescription(**params)), timeout=3)
            transceivers = pc.getTransceivers()
            if len(transceivers) != 1 or transceivers[0].kind != 'video':
                raise ValueError('recvonly_video_required')
            track = LatestVideoTrack(stream)
            peer['track'] = track
            pc.addTrack(track)
            transceivers[0].direction = 'sendonly'
            answer = await pc.createAnswer()
            await asyncio.wait_for(pc.setLocalDescription(answer), timeout=15)
            if (session not in self.peers or stream.status()['state'] != 'live'
                    or stream.generation != peer['generation']):
                raise ValueError('publisher_not_live')
            LOG.info('VIDEO_VIEWER_OPEN stream=%s', stream.id)
            return web.json_response({'type': pc.localDescription.type, 'sdp': pc.localDescription.sdp,
                                      'sessionId': session, 'publisherId': stream.publisher,
                                      'source': stream._source_snapshot()})
        except asyncio.CancelledError:
            await self.close(session)
            raise
        except Exception:
            await self.close(session)
            return failure(400, 'invalid_offer_or_ice_timeout')

    async def close(self, session):
        peer = self.peers.pop(session, None)
        if peer is not None:
            if peer['track']:
                peer['track'].stop()
            await peer['pc'].close()
            LOG.info('VIDEO_VIEWER_CLOSED stream=%s', peer['stream'].id)

    async def delete(self, request):
        await self.close(request.match_info['session'])
        return web.Response(status=204)

    async def probe(self, request):
        stream = self.streams.get(request.match_info['stream'])
        if stream is None:
            return failure(404, 'unknown_stream')
        await self.expire_stream(stream)
        if not stream.is_live() or stream.publisher_metrics['diagnosticsOverlay'] is not True:
            return failure(409, 'diagnostics_overlay_required')
        try:
            body = await asyncio.wait_for(request.read(), timeout=3)
            if len(body) > 256 or request.content_type != 'application/json':
                raise ValueError('invalid probe')
            payload = json.loads(body)
            nonce = payload.get('nonce') if isinstance(payload, dict) and set(payload) == {'nonce'} else None
            if isinstance(nonce, bool) or not isinstance(nonce, int) or not 0 < nonce <= 0xffffffff:
                raise ValueError('invalid nonce')
        except (asyncio.TimeoutError, json.JSONDecodeError, ValueError):
            return failure(400, 'invalid_probe')
        stream.set_probe(nonce)
        LOG.info('VIDEO_PROBE_ACCEPTED stream=%s', stream.id)
        return web.json_response({'acceptedSequence': stream.sequence, 'probeNonce': nonce})

    async def sweep(self):
        while True:
            await asyncio.sleep(1)
            now = time.monotonic()
            for stream in self.streams.values():
                await self.expire_stream(stream)
            expired = [sid for sid, p in self.peers.items() if
                (p['pc'].connectionState != 'connected' and now - p['created'] > 25)
                or p['generation'] != p['stream'].generation
                or (p['stream'].received and now - p['stream'].received > 10)]
            await asyncio.gather(*(self.close(sid) for sid in expired))

    async def lifecycle(self, app):
        task = asyncio.create_task(self.sweep())
        yield
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        await asyncio.gather(*(self.close(sid) for sid in list(self.peers)))


def create_app(config):
    backend = VideoBackend(config)
    app = web.Application(client_max_size=2 * 1024 * 1024, middlewares=[backend.boundary])
    app.router.add_get('/api/video/config', backend.public_config)
    app.router.add_get('/api/video/health', backend.health)
    app.router.add_get('/api/video/streams/{stream}', backend.status)
    app.router.add_post('/api/video/streams/{stream}/frames', backend.ingest)
    app.router.add_post('/api/video/streams/{stream}/probe', backend.probe)
    app.router.add_post('/api/video/streams/{stream}/offer', backend.offer)
    app.router.add_delete('/api/video/sessions/{session}', backend.delete)
    app.router.add_route('OPTIONS', '/{path:.*}', lambda request: web.Response(status=204))
    app.cleanup_ctx.append(backend.lifecycle)
    return app
