#!/usr/bin/env python3
"""Record WebRTC video receive diagnostics without controlling Unity, Brain, or audio."""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import re
import secrets
import sys
import time
from typing import Any
from urllib.parse import urlsplit

import aiohttp
from aiortc import RTCConfiguration, RTCIceServer, RTCPeerConnection, RTCSessionDescription
import psutil


ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = (ROOT / "artifacts").resolve()
MAX_DURATION_SECONDS = 86_400
MAX_RESPONSE_BYTES = 192 * 1024
HTTP_TIMEOUT_SECONDS = 5.0
OFFER_TIMEOUT_SECONDS = 25.0
ICE_TIMEOUT_SECONDS = 12.0
FIRST_FRAME_TIMEOUT_SECONDS = 5.0
FRAME_TIMEOUT_SECONDS = 2.0
STATUS_INTERVAL_SECONDS = 1.0
PROBE_INTERVAL_SECONDS = 5.0
PROBE_TIMEOUT_SECONDS = 5.0
PROBE_EXPIRE_SECONDS = 10.0
MAX_LATENCY_SAMPLES = 18_000
STREAM_ID = re.compile(r"[a-z0-9-]{1,40}")
SESSION_ID = re.compile(r"[a-f0-9]{32}")
SAFE_ERROR = re.compile(r"[a-z0-9_]{1,80}")


class MeasureError(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass
class Connection:
    generation: int
    pc: RTCPeerConnection
    track: Any
    session_id: str
    publisher_id: str | None
    binding: tuple[Any, ...] | None
    connected_at: float
    mailbox: "FrameMailbox"
    consumer: asyncio.Task
    observed_frames: int = 0
    observed_revision: int = 0


@dataclass
class Probe:
    nonce: int
    started: float
    task: asyncio.Task
    accepted: bool = False


@dataclass
class FrameMailbox:
    """A one-frame mailbox: the drain task never lets a decoded-frame queue grow."""
    latest: Any | None = None
    revision: int = 0
    received_frames: int = 0
    first_received_at: float | None = None
    last_received_at: float | None = None
    max_gap_ms: float | None = None
    error: str | None = None


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalized_endpoint(value: str) -> str:
    endpoint = urlsplit(value)
    try:
        port = endpoint.port
    except ValueError as exc:
        raise MeasureError("endpoint_invalid") from exc
    if (endpoint.scheme != "http" or endpoint.hostname not in ("127.0.0.1", "localhost", "::1")
            or endpoint.username or endpoint.password or endpoint.path not in ("", "/")
            or endpoint.query or endpoint.fragment or port is None):
        raise MeasureError("endpoint_loopback_required")
    host = "[::1]" if endpoint.hostname == "::1" else endpoint.hostname
    return f"http://{host}:{port}"


def output_path(value: str | None) -> Path:
    if value is None:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        candidate = ARTIFACTS / "video-measure" / f"{stamp}.jsonl"
    else:
        candidate = Path(value).expanduser()
        if not candidate.is_absolute():
            candidate = ROOT / candidate
        candidate = candidate.resolve()
    try:
        candidate.relative_to(ARTIFACTS)
    except ValueError as exc:
        raise MeasureError("output_must_be_under_ignored_artifacts") from exc
    if candidate.suffix != ".jsonl":
        raise MeasureError("output_must_end_in_jsonl")
    return candidate


def summary_path(path: Path) -> Path:
    return path.with_suffix(".summary.json")


def valid_duration(value: str) -> int:
    try:
        seconds = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if not 1 <= seconds <= MAX_DURATION_SECONDS:
        raise argparse.ArgumentTypeError("must be 1..86400")
    return seconds


def valid_reconnect(value: str) -> int:
    seconds = valid_duration(value)
    if seconds < 10:
        raise argparse.ArgumentTypeError("must be at least 10 seconds")
    return seconds


def source_binding(source: Any) -> tuple[Any, ...] | None:
    if not isinstance(source, dict):
        return None
    identity = source.get("brainIdentity")
    if not isinstance(identity, dict):
        return None
    keys = ("instanceId", "sessionId", "backendId", "datasetId", "configHash", "graphHash", "sourceHash")
    values = tuple(identity.get(key) for key in keys)
    return values if all(isinstance(value, str) and value for value in values) else None


def status_identity(status: dict[str, Any]) -> tuple[str | None, tuple[Any, ...] | None]:
    publisher = status.get("publisherId")
    return (publisher if isinstance(publisher, str) and publisher else None,
            source_binding(status.get("source")))


def safe_http_error(status: int, payload: Any) -> str:
    error = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(error, str) and SAFE_ERROR.fullmatch(error):
        return f"http_{status}_{error}"
    return f"http_{status}"


async def request_json(session: aiohttp.ClientSession, method: str, url: str,
                       body: dict[str, Any] | None = None, timeout: float = HTTP_TIMEOUT_SECONDS) -> dict[str, Any]:
    try:
        async with session.request(method, url, json=body, allow_redirects=False,
                                   timeout=aiohttp.ClientTimeout(total=timeout)) as response:
            if response.content_length is not None and response.content_length > MAX_RESPONSE_BYTES:
                raise MeasureError("http_response_too_large")
            chunks: list[bytes] = []
            size = 0
            async for chunk in response.content.iter_chunked(8192):
                size += len(chunk)
                if size > MAX_RESPONSE_BYTES:
                    raise MeasureError("http_response_too_large")
                chunks.append(chunk)
            raw = b"".join(chunks)
            try:
                payload = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise MeasureError("http_invalid_json") from exc
            if response.status < 200 or response.status >= 300:
                raise MeasureError(safe_http_error(response.status, payload))
            if not isinstance(payload, dict):
                raise MeasureError("http_invalid_schema")
            return payload
    except MeasureError:
        raise
    except asyncio.TimeoutError as exc:
        raise MeasureError("http_timeout") from exc
    except aiohttp.ClientConnectionError as exc:
        raise MeasureError("http_connect") from exc
    except aiohttp.ClientError as exc:
        raise MeasureError("http_client") from exc


def configuration(payload: dict[str, Any], stream: str) -> list[RTCIceServer]:
    streams, ice_servers = payload.get("streams"), payload.get("iceServers")
    if (not isinstance(streams, list) or stream not in streams or not isinstance(ice_servers, list)
            or not all(isinstance(item, str) and STREAM_ID.fullmatch(item) for item in streams)
            or not all(isinstance(item, dict) for item in ice_servers)):
        raise MeasureError("config_invalid")
    try:
        return [RTCIceServer(**item) for item in ice_servers if isinstance(item, dict)]
    except (TypeError, ValueError) as exc:
        raise MeasureError("config_invalid") from exc


async def wait_ice_complete(pc: RTCPeerConnection) -> None:
    deadline = time.monotonic() + ICE_TIMEOUT_SECONDS
    while pc.iceGatheringState != "complete":
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise MeasureError("ice_gather_timeout")
        await asyncio.sleep(min(0.05, remaining))


async def delete_session(session: aiohttp.ClientSession, endpoint: str, session_id: str | None) -> None:
    if session_id is None or not SESSION_ID.fullmatch(session_id):
        return
    try:
        async with session.delete(f"{endpoint}/api/video/sessions/{session_id}", allow_redirects=False,
                                  timeout=aiohttp.ClientTimeout(total=HTTP_TIMEOUT_SECONDS)) as response:
            # DELETE returns 204. Consume at most a small error body without requiring JSON.
            await response.content.read(1024)
    except (asyncio.TimeoutError, aiohttp.ClientError):
        # This is best-effort cleanup of a session created only by this process.
        return


async def close_connection(session: aiohttp.ClientSession, endpoint: str,
                           connection: Connection | None) -> None:
    if connection is None:
        return
    try:
        if not connection.consumer.done():
            connection.consumer.cancel()
        try:
            await connection.consumer
        except (asyncio.CancelledError, Exception):
            pass
        await connection.pc.close()
    finally:
        await delete_session(session, endpoint, connection.session_id)


async def cancel_probe(probe: Probe | None) -> None:
    if probe is None:
        return
    if not probe.task.done():
        probe.task.cancel()
    try:
        await probe.task
    except (asyncio.CancelledError, MeasureError, Exception):
        pass


async def drain_track(track: Any, mailbox: FrameMailbox) -> None:
    try:
        while True:
            frame = await track.recv()
            received_at = time.monotonic()
            if mailbox.last_received_at is not None:
                gap_ms = (received_at - mailbox.last_received_at) * 1000
                mailbox.max_gap_ms = gap_ms if mailbox.max_gap_ms is None else max(mailbox.max_gap_ms, gap_ms)
            if mailbox.first_received_at is None:
                mailbox.first_received_at = received_at
            mailbox.last_received_at = received_at
            mailbox.latest = frame
            mailbox.revision += 1
            mailbox.received_frames += 1
    except asyncio.CancelledError:
        raise
    except Exception:
        mailbox.error = "track_receive"


async def open_connection(session: aiohttp.ClientSession, endpoint: str, stream: str,
                          generation: int) -> Connection:
    config = configuration(await request_json(session, "GET", f"{endpoint}/api/video/config"), stream)
    pc = RTCPeerConnection(RTCConfiguration(iceServers=config))
    track_ready = asyncio.Event()
    state_ready = asyncio.Event()
    track_holder: dict[str, Any] = {}

    @pc.on("track")
    def on_track(track):
        if track.kind == "video":
            track_holder["track"] = track
            track_ready.set()

    @pc.on("connectionstatechange")
    async def on_connection_state_change():
        if pc.connectionState == "connected":
            state_ready.set()

    session_id: str | None = None
    try:
        pc.addTransceiver("video", direction="recvonly")
        offer = await pc.createOffer()
        await pc.setLocalDescription(offer)
        await wait_ice_complete(pc)
        local = pc.localDescription
        if local is None or local.type != "offer" or not isinstance(local.sdp, str) or len(local.sdp) > 120_000:
            raise MeasureError("offer_invalid")
        answer = await request_json(session, "POST", f"{endpoint}/api/video/streams/{stream}/offer",
                                    {"type": "offer", "sdp": local.sdp}, OFFER_TIMEOUT_SECONDS)
        session_id = answer.get("sessionId")
        if (answer.get("type") != "answer" or not isinstance(answer.get("sdp"), str)
                or not SESSION_ID.fullmatch(session_id or "")):
            raise MeasureError("answer_invalid")
        await asyncio.wait_for(pc.setRemoteDescription(RTCSessionDescription(type="answer", sdp=answer["sdp"])),
                               timeout=ICE_TIMEOUT_SECONDS)
        await asyncio.wait_for(track_ready.wait(), timeout=ICE_TIMEOUT_SECONDS)
        await asyncio.wait_for(state_ready.wait(), timeout=ICE_TIMEOUT_SECONDS)
        track = track_holder.get("track")
        if track is None:
            raise MeasureError("track_missing")
        mailbox = FrameMailbox()
        consumer = asyncio.create_task(drain_track(track, mailbox))
        publisher = answer.get("publisherId")
        return Connection(generation, pc, track, session_id,
                          publisher if isinstance(publisher, str) and publisher else None,
                          source_binding(answer.get("source")), time.monotonic(), mailbox, consumer)
    except asyncio.TimeoutError as exc:
        await pc.close()
        await delete_session(session, endpoint, session_id)
        raise MeasureError("webrtc_timeout") from exc
    except asyncio.CancelledError:
        await pc.close()
        await delete_session(session, endpoint, session_id)
        raise
    except MeasureError:
        await pc.close()
        await delete_session(session, endpoint, session_id)
        raise
    except Exception as exc:
        await pc.close()
        await delete_session(session, endpoint, session_id)
        raise MeasureError("webrtc_setup") from exc


async def get_inbound_stats(pc: RTCPeerConnection) -> dict[str, Any] | None:
    try:
        reports = await pc.getStats()
    except Exception:
        return None
    for report in reports.values():
        if report.type == "inbound-rtp" and getattr(report, "kind", getattr(report, "mediaType", None)) == "video":
            def number(name: str):
                value = getattr(report, name, None)
                return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None
            jitter = number("jitter")
            return {"receivedPackets": number("packetsReceived"), "packetsLost": number("packetsLost"),
                    "jitterRtpTimestampUnits": jitter,
                    "jitterMs": jitter / 90.0 if jitter is not None else None,
                    "framesDecoded": number("framesDecoded"), "bytesReceived": number("bytesReceived")}
    return None


def decode_marker(frame: Any) -> int | None:
    if frame.width < 256 or frame.height < 8:
        return None
    try:
        image = frame.to_image().convert("RGB")
        for top in (0, image.height - 8):
            crop = image.crop((0, top, 256, top + 8))
            pixels = crop.load()
            bits: list[int] = []
            for block in range(64):
                total = 0
                for x in range(block * 4 + 1, block * 4 + 3):
                    for y in range(2, 6):
                        red, green, blue = pixels[x, y]
                        total += red + green + blue
                bits.append(1 if total / 24 >= 128 else 0)
            value = 0
            for bit in bits:
                value = (value << 1) | bit
            magic, nonce, checksum = value >> 48, (value >> 16) & 0xffffffff, value & 0xffff
            if magic == 0xD3A5 and nonce and checksum == (((nonce >> 16) ^ (nonce & 0xffff) ^ 0x6B4D) & 0xffff):
                return nonce
    except Exception:
        return None
    return None


def percentile(values: list[float], percent: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * percent / 100.0
    lower, upper = math.floor(position), math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def source_hashes() -> dict[str, str]:
    result = {}
    for path in (Path(__file__), ROOT / "Runtime/Video/server.py", ROOT / "Runtime/Video/media.py"):
        try:
            result[str(path.relative_to(ROOT))] = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            result[str(path)] = "unavailable"
    return result


class Recorder:
    def __init__(self, output: Path, duration: int, endpoint: str, stream: str):
        self.output = output
        self.summary = summary_path(output)
        self.duration = duration
        self.endpoint = endpoint
        self.stream = stream
        self.handle = None
        self.started = time.monotonic()
        self.started_utc = utc_now()
        self.source_hashes_start = source_hashes()
        self.sample_count = 0
        self.received_frames = 0
        self.max_frame_gap_ms: float | None = None
        self.last_frame_at: float | None = None
        self.last_sample_at = self.started
        self.frames_at_sample = 0
        self.failures: Counter[str] = Counter()
        self.reconnects = 0
        self.downtime_started: float | None = self.started
        self.downtime_seconds = 0.0
        self.latencies: list[float] = []
        self.total_latency_count = 0
        self.last_latency_ms: float | None = None
        self.process = psutil.Process()
        self.process.cpu_percent(interval=None)

    def open(self) -> None:
        self.output.parent.mkdir(parents=True, exist_ok=True)
        if self.summary.exists() or self.output.exists():
            raise MeasureError("output_already_exists")
        self.handle = self.output.open("x", encoding="utf-8")

    def failure(self, code: str, media: bool = True) -> None:
        self.failures[code] += 1
        if media and self.downtime_started is None:
            self.downtime_started = time.monotonic()

    def frames(self, count: int, first_at: float | None, last_at: float | None,
               max_gap_ms: float | None) -> None:
        if count <= 0 or last_at is None:
            return
        self.received_frames += count
        if max_gap_ms is not None:
            self.max_frame_gap_ms = max_gap_ms if self.max_frame_gap_ms is None else max(self.max_frame_gap_ms, max_gap_ms)
        self.last_frame_at = last_at
        if self.downtime_started is not None:
            self.downtime_seconds += (first_at or last_at) - self.downtime_started
            self.downtime_started = None

    def latency(self, value_ms: float) -> None:
        self.total_latency_count += 1
        self.last_latency_ms = value_ms
        if len(self.latencies) == MAX_LATENCY_SAMPLES:
            self.latencies.pop(0)
        self.latencies.append(value_ms)

    def sample(self, now: float, connection: Connection | None, status: dict[str, Any] | None,
               stats: dict[str, Any] | None, last_error: str | None) -> None:
        elapsed = now - self.started
        interval = max(0.001, now - self.last_sample_at)
        delta_fps = (self.received_frames - self.frames_at_sample) / interval
        self.last_sample_at, self.frames_at_sample = now, self.received_frames
        try:
            cpu, rss = self.process.cpu_percent(interval=None), self.process.memory_info().rss
        except psutil.Error:
            cpu, rss = None, None
        row = {"utc": utc_now(), "elapsedSeconds": round(elapsed, 3),
               "generation": connection.generation if connection else None,
               "sessionId": connection.session_id if connection else None,
               "status": status, "receivedFrames": self.received_frames,
               "deltaFps": round(delta_fps, 3), "maxFrameGapMs": self.max_frame_gap_ms,
               "process": {"cpuPercent": cpu, "rssBytes": rss}, "webrtc": stats,
               "visualRoundTripToDecodeMs": self.last_latency_ms, "lastError": last_error}
        self.handle.write(json.dumps(row, separators=(",", ":"), ensure_ascii=True) + "\n")
        self.handle.flush()
        self.sample_count += 1

    def close(self, completed: bool) -> Path:
        ended = time.monotonic()
        if self.downtime_started is not None:
            self.downtime_seconds += ended - self.downtime_started
            self.downtime_started = None
        if self.handle is not None:
            self.handle.close()
        versions = {}
        for name in ("aiohttp", "aiortc", "av", "Pillow", "psutil"):
            try:
                versions[name] = importlib.metadata.version(name)
            except importlib.metadata.PackageNotFoundError:
                versions[name] = "unavailable"
        latency = {"timing": "visualRoundTripToDecodeMs", "notOneWayE2E": True,
                   "count": self.total_latency_count, "retainedSamples": len(self.latencies),
                   "partial": self.total_latency_count > len(self.latencies),
                   "median": percentile(self.latencies, 50), "p95": percentile(self.latencies, 95),
                   "p99": percentile(self.latencies, 99), "max": max(self.latencies) if self.latencies else None}
        hashes_end = source_hashes()
        payload = {"startedUtc": self.started_utc, "requestedDurationSeconds": self.duration,
                   "completed": completed and ended - self.started >= self.duration,
                   "elapsedSeconds": round(ended - self.started, 3),
                   "sampleCount": self.sample_count, "totalFrames": self.received_frames,
                   "maxFrameGapMs": self.max_frame_gap_ms, "reconnectCount": self.reconnects,
                   "failures": dict(self.failures), "downtimeSeconds": round(self.downtime_seconds, 3),
                   "latency": latency, "headlessMetric": "decoded WebRTC frame, not browser display",
                   "versions": versions, "sourceHashesAtStart": self.source_hashes_start,
                   "sourceHashesAtEnd": hashes_end,
                   "sourceChangedDuringRun": self.source_hashes_start != hashes_end}
        self.summary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return self.summary


async def run(args: argparse.Namespace) -> tuple[Path, Path]:
    endpoint = normalized_endpoint(args.endpoint)
    if not STREAM_ID.fullmatch(args.stream):
        raise MeasureError("stream_invalid")
    output = output_path(args.output)
    recorder = Recorder(output, args.duration, endpoint, args.stream)
    recorder.open()
    connection: Connection | None = None
    probe: Probe | None = None
    status: dict[str, Any] | None = None
    last_error: str | None = None
    next_status, next_probe = recorder.started, recorder.started
    next_sample = recorder.started
    reconnect_after = recorder.started
    deadline = recorder.started + args.duration
    next_forced_reconnect = None
    generation = 0
    retry_attempt = 0
    completed = False
    status_task: asyncio.Task | None = None
    connector = aiohttp.TCPConnector(limit=2, force_close=True)
    async with aiohttp.ClientSession(connector=connector, trust_env=False) as session:
        try:
            while True:
                now = time.monotonic()
                if now >= deadline:
                    completed = True
                    break
                if probe is not None and probe.task.done():
                    try:
                        response = probe.task.result()
                        if response.get("probeNonce") == probe.nonce:
                            probe.accepted = True
                        else:
                            recorder.failure("probe_invalid_response", media=False)
                            await cancel_probe(probe)
                            probe = None
                    except MeasureError as exc:
                        last_error = exc.code
                        recorder.failure(exc.code, media=False)
                        await cancel_probe(probe)
                        probe = None
                if probe is not None and now - probe.started >= PROBE_EXPIRE_SECONDS:
                    await cancel_probe(probe)
                    probe = None

                if status_task is None and now >= next_status:
                    next_status = now + STATUS_INTERVAL_SECONDS
                    status_task = asyncio.create_task(request_json(
                        session, "GET", f"{endpoint}/api/video/streams/{args.stream}",
                        timeout=max(0.01, min(HTTP_TIMEOUT_SECONDS, deadline - now))))
                if status_task is not None and status_task.done():
                    task = status_task
                    status_task = None
                    try:
                        status = task.result()
                        if status.get("streamId") != args.stream or status.get("state") not in ("waiting", "live", "stale"):
                            raise MeasureError("status_invalid")
                        publisher, binding = status_identity(status)
                        if connection is not None and (status["state"] != "live"
                                or publisher != connection.publisher_id or binding != connection.binding):
                            last_error = "source_changed" if status["state"] == "live" else f"stream_{status['state']}"
                            recorder.failure(last_error)
                            await cancel_probe(probe)
                            await close_connection(session, endpoint, connection)
                            connection, probe = None, None
                            retry_attempt = min(5, retry_attempt + 1)
                            reconnect_after = time.monotonic() + min(8.0, 0.5 * (2 ** (retry_attempt - 1)))
                    except MeasureError as exc:
                        last_error = exc.code
                        recorder.failure(exc.code)
                        if connection is not None:
                            await cancel_probe(probe)
                            await close_connection(session, endpoint, connection)
                            connection, probe = None, None
                            retry_attempt = min(5, retry_attempt + 1)
                            reconnect_after = time.monotonic() + min(8.0, 0.5 * (2 ** (retry_attempt - 1)))

                if connection is None and now >= reconnect_after:
                    generation += 1
                    try:
                        connection = await asyncio.wait_for(
                            open_connection(session, endpoint, args.stream, generation),
                            timeout=max(0.01, min(OFFER_TIMEOUT_SECONDS, deadline - time.monotonic())))
                        if generation > 1:
                            recorder.reconnects += 1
                        next_forced_reconnect = (time.monotonic() + args.reconnect_every
                                                 if args.reconnect_every else None)
                        last_error = None
                    except asyncio.TimeoutError:
                        if time.monotonic() >= deadline:
                            completed = True
                            break
                        last_error = "webrtc_timeout"
                        recorder.failure(last_error)
                        retry_attempt = min(5, retry_attempt + 1)
                        reconnect_after = time.monotonic() + min(8.0, 0.5 * (2 ** (retry_attempt - 1)))
                    except MeasureError as exc:
                        last_error = exc.code
                        recorder.failure(exc.code)
                        retry_attempt = min(5, retry_attempt + 1)
                        reconnect_after = time.monotonic() + min(8.0, 0.5 * (2 ** (retry_attempt - 1)))

                now = time.monotonic()
                if connection is not None and next_forced_reconnect is not None and now >= next_forced_reconnect:
                    recorder.failure("scheduled_reconnect", media=False)
                    if recorder.downtime_started is None:
                        recorder.downtime_started = now
                    await cancel_probe(probe)
                    await close_connection(session, endpoint, connection)
                    connection, probe, reconnect_after = None, None, now
                    continue

                if connection is not None and probe is None and now >= next_probe:
                    metrics = status.get("metrics") if isinstance(status, dict) else None
                    publisher_metrics = metrics.get("publisher") if isinstance(metrics, dict) else None
                    if isinstance(publisher_metrics, dict) and publisher_metrics.get("diagnosticsOverlay") is True:
                        nonce = secrets.randbits(32) or 1
                        probe = Probe(nonce, time.monotonic(), asyncio.create_task(
                            request_json(session, "POST", f"{endpoint}/api/video/streams/{args.stream}/probe",
                                         {"nonce": nonce}, PROBE_TIMEOUT_SECONDS)))
                    next_probe = now + PROBE_INTERVAL_SECONDS

                if connection is not None:
                    mailbox = connection.mailbox
                    delta = mailbox.received_frames - connection.observed_frames
                    if delta > 0:
                        recorder.frames(delta,
                                        mailbox.first_received_at if connection.observed_frames == 0 else mailbox.last_received_at,
                                        mailbox.last_received_at, mailbox.max_gap_ms)
                        connection.observed_frames = mailbox.received_frames
                        retry_attempt = 0
                    if probe is not None and probe.accepted and mailbox.revision > connection.observed_revision:
                        connection.observed_revision = mailbox.revision
                        if decode_marker(mailbox.latest) == probe.nonce:
                            recorder.latency((time.monotonic() - probe.started) * 1000)
                            await cancel_probe(probe)
                            probe = None
                    if mailbox.error is not None:
                        last_error = mailbox.error
                        recorder.failure(last_error)
                        await cancel_probe(probe)
                        await close_connection(session, endpoint, connection)
                        connection, probe = None, None
                        retry_attempt = min(5, retry_attempt + 1)
                        reconnect_after = time.monotonic() + min(8.0, 0.5 * (2 ** (retry_attempt - 1)))
                        continue
                    frame_deadline = (connection.connected_at + FIRST_FRAME_TIMEOUT_SECONDS
                                      if mailbox.last_received_at is None else mailbox.last_received_at + FRAME_TIMEOUT_SECONDS)
                    if now >= frame_deadline:
                        if now >= deadline:
                            completed = True
                            break
                        last_error = "first_frame_timeout" if mailbox.last_received_at is None else "frame_timeout"
                        recorder.failure(last_error)
                        await cancel_probe(probe)
                        await close_connection(session, endpoint, connection)
                        connection, probe = None, None
                        retry_attempt = min(5, retry_attempt + 1)
                        reconnect_after = time.monotonic() + min(8.0, 0.5 * (2 ** (retry_attempt - 1)))
                        continue

                if now >= next_sample:
                    next_sample = now + STATUS_INTERVAL_SECONDS
                    stats = await get_inbound_stats(connection.pc) if connection is not None else None
                    recorder.sample(now, connection, status, stats, last_error)

                if connection is None:
                    await asyncio.sleep(min(0.2, max(0.01, reconnect_after - time.monotonic())))
                    continue
                await asyncio.sleep(min(0.05, max(0.01, deadline - time.monotonic())))
        finally:
            if status_task is not None and not status_task.done():
                status_task.cancel()
                try:
                    await status_task
                except (asyncio.CancelledError, Exception):
                    pass
            await cancel_probe(probe)
            await close_connection(session, endpoint, connection)
            summary = recorder.close(completed)
    return output, summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", default="http://127.0.0.1:8880", help="Loopback video backend endpoint")
    parser.add_argument("--stream", default="unity-mac", help="Configured video stream ID")
    parser.add_argument("--duration", type=valid_duration, default=1800, help="Measurement seconds (1..86400)")
    parser.add_argument("--output", help="Ignored artifacts/*.jsonl output path")
    parser.add_argument("--reconnect-every", type=valid_reconnect,
                        help="Optionally force a fresh receive session every N seconds (>=10)")
    args = parser.parse_args()
    try:
        output, summary = asyncio.run(run(args))
    except KeyboardInterrupt:
        raise SystemExit(130)
    except MeasureError as exc:
        print(f"Video measurement failed ({exc.code}).", file=sys.stderr)
        raise SystemExit(2) from None
    print(json.dumps({"output": str(output), "summary": str(summary)}, separators=(",", ":")))


if __name__ == "__main__":
    main()
