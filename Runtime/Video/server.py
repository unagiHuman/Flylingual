"""Unity JPEG ingress -> VP8/H264 WebRTC. No Brain/control/API dependency."""
from __future__ import annotations

import asyncio
import contextlib
import hmac
import logging
import re
import time
import uuid

from aiohttp import web
from aiortc import RTCConfiguration, RTCIceServer, RTCPeerConnection, RTCSessionDescription

from .media import LEASE_SECONDS, STALE_SECONDS, LatestVideoTrack, Stream, decode_jpeg

LOG = logging.getLogger('flylingual.video')


def failure(status: int, error: str):
    return web.json_response({'error': error}, status=status)


class VideoBackend:
    def __init__(self, config):
        self.config = config
        self.streams = {name: Stream(name) for name in config['streams']}
        self.peers = {}

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

    async def status(self, request):
        stream = self.streams.get(request.match_info['stream'])
        if stream is None:
            return failure(404, 'unknown_stream')
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
        if stream.publisher and stream.publisher != publisher and time.monotonic() - stream.received < LEASE_SECONDS:
            return failure(409, 'publisher_slot_in_use')
        if stream.publisher == publisher and int(sequence) <= stream.sequence:
            return failure(409, 'old_frame_sequence')
        stream.busy = True
        try:
            try:
                body = await asyncio.wait_for(request.read(), timeout=3)
                frame = await asyncio.to_thread(decode_jpeg, body)
            except web.HTTPRequestEntityTooLarge:
                return failure(413, 'frame_too_large')
            except (ValueError, OSError):
                return failure(400, 'invalid_jpeg')
            except asyncio.TimeoutError:
                return failure(408, 'frame_upload_timeout')
            # Close viewers when ownership changes; old video never becomes a new source.
            changed = stream.publisher is not None and stream.publisher != publisher
            if changed:
                await asyncio.gather(*(self.close(key) for key, p in list(self.peers.items()) if p['stream'] is stream))
            stream.publish(publisher, int(sequence), {
                'kind': 'diagnostic' if execution_os == 'diagnostic' else 'unity-game',
                'label': label, 'executionOs': execution_os}, frame)
            if stream.sequence == 0 or changed:
                LOG.info('VIDEO_PUBLISHER stream=%s os=%s', stream.id, execution_os)
            return web.json_response({'acceptedSequence': stream.sequence})
        finally:
            stream.busy = False

    async def offer(self, request):
        stream = self.streams.get(request.match_info['stream'])
        if stream is None:
            return failure(404, 'unknown_stream')
        if stream.status()['state'] != 'live':
            return failure(409, 'publisher_not_live')
        if len(self.peers) >= self.config['maxViewers']:
            return failure(429, 'viewer_limit')
        # Reserve capacity before reading a body or performing asynchronous SDP work.
        session = uuid.uuid4().hex
        pc = RTCPeerConnection(RTCConfiguration(iceServers=[RTCIceServer(**s) for s in self.config['iceServers']]))
        peer = {'pc': pc, 'stream': stream, 'created': time.monotonic(), 'track': None}
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
            if session not in self.peers or stream.status()['state'] != 'live':
                raise ValueError('publisher_not_live')
            LOG.info('VIDEO_VIEWER_OPEN stream=%s', stream.id)
            return web.json_response({'type': pc.localDescription.type, 'sdp': pc.localDescription.sdp,
                                      'sessionId': session})
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

    async def sweep(self):
        while True:
            await asyncio.sleep(1)
            now = time.monotonic()
            expired = [sid for sid, p in self.peers.items() if
                (p['pc'].connectionState != 'connected' and now - p['created'] > 25)
                or now - p['stream'].received > 10]
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
    app.router.add_get('/api/video/streams/{stream}', backend.status)
    app.router.add_post('/api/video/streams/{stream}/frames', backend.ingest)
    app.router.add_post('/api/video/streams/{stream}/offer', backend.offer)
    app.router.add_delete('/api/video/sessions/{session}', backend.delete)
    app.router.add_route('OPTIONS', '/{path:.*}', lambda request: web.Response(status=204))
    app.cleanup_ctx.append(backend.lifecycle)
    return app
