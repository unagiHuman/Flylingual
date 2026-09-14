"""Async, fail-closed client for the Bridge-compatible Brain NDJSON transport."""

from __future__ import annotations

import asyncio
import inspect
import json
import math
import time
from typing import Any, Awaitable, Callable


_LIMIT = 2 * 1024 * 1024
_ACTIONS = frozenset({"STOP", "FORWARD", "TURN_R", "TURN_L", "FORWARD_R", "FORWARD_L"})
_STATUS_KEYS = (
    "backendId",
    "datasetId",
    "configHash",
    "graphHash",
    "sourceHash",
    "sessionId",
    "instanceId",
)


class BrainAdapterError(RuntimeError):
    """A safe protocol/transport error code suitable for callers and logs."""


class ReleaseUnknownError(BrainAdapterError):
    """The controller release could not be directly observed."""


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_finite_number(value: Any) -> bool:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(float(value))
    except OverflowError:
        return False


class BrainAdapter:
    """Own one controller connection; never silently fall back to another Brain."""

    def __init__(
        self,
        on_message: Callable[[dict[str, Any]], Awaitable[None]],
        timeout: float = 10,
    ) -> None:
        if not callable(on_message):
            raise TypeError("on_message must be async callable")
        if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout must be a positive finite number")
        self._on_message = on_message
        self.timeout = float(timeout)
        self.status: dict[str, Any] = {}
        self.latest_frame: dict[str, Any] | None = None
        self.latest_received_at: float = time.monotonic()
        self.session_id: str | None = None
        self.instance_id: str | None = None
        self.connected = False
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._reader_task: asyncio.Task[None] | None = None
        self._status_future: asyncio.Future[dict[str, Any]] | None = None
        self._release_future: asyncio.Future[dict[str, Any]] | None = None
        self._write_lock = asyncio.Lock()
        self._closed = False
        self._ever_connected = False
        self._last_sequence: int | None = None
        self._next_internal_request_id = -1
        self._release_request_id: int | None = None
        self._failure_code: str | None = None
        self._sensory_generation = 0
        self.visual_threat_requests = {}

    @staticmethod
    def _safe_expected_target(target: dict[str, Any]) -> tuple[str, int]:
        if not isinstance(target, dict):
            raise BrainAdapterError("invalid_target")
        host = target.get("host")
        port = target.get("port")
        if not isinstance(host, str) or not host:
            raise BrainAdapterError("invalid_target_host")
        if not _is_int(port) or not 1 <= port <= 65535:
            raise BrainAdapterError("invalid_target_port")
        for key in ("expectedBackend", "expectedDataset", "expectedConfigHash", "expectedGraphHash", "expectedSourceHash"):
            value = target.get(key)
            if value is not None and not isinstance(value, str):
                raise BrainAdapterError("invalid_expected_identity")
        return host, port

    async def connect(self, target: dict[str, Any]) -> dict[str, Any]:
        if self._closed:
            raise BrainAdapterError("adapter_closed")
        if self._ever_connected:
            raise BrainAdapterError("adapter_already_connected")
        host, port = self._safe_expected_target(target)
        self._ever_connected = True
        loop = asyncio.get_running_loop()
        self._status_future = loop.create_future()
        try:
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(host, port, limit=_LIMIT), timeout=self.timeout
            )
            self._reader_task = asyncio.create_task(self._reader_loop(target), name="brain-adapter-reader")
            return await asyncio.wait_for(asyncio.shield(self._status_future), timeout=self.timeout)
        except Exception:
            await self.close()
            raise

    async def send_action(self, action: str, request_id: int) -> None:
        if action not in _ACTIONS:
            raise BrainAdapterError("invalid_action")
        if not _is_int(request_id):
            raise BrainAdapterError("invalid_request_id")
        if not self.connected:
            raise BrainAdapterError("not_connected")
        if action == "STOP":
            self.invalidate_visual_threat()
        await self._send({"type": "set_action", "action": action, "requestId": request_id})

    def invalidate_visual_threat(self):
        """Invalidate sensory writes already waiting behind the transport lock."""
        self._sensory_generation += 1

    async def send_visual_threat(self, active, valid_for_ms, *, source, valid=None):
        if (type(active) is not bool or type(valid_for_ms) is not int
                or (active and not 1 <= valid_for_ms <= 750) or (not active and valid_for_ms != 0)):
            raise BrainAdapterError("invalid_visual_threat")
        if (not self.connected or not isinstance(self.status.get('capabilities'), list)
                or 'visual_threat_v1' not in self.status['capabilities']):
            return None
        if valid is not None and not valid():
            return None
        if not active:
            self.invalidate_visual_threat()
        generation = self._sensory_generation
        started = time.monotonic()
        request_id = self._next_internal_request_id
        self._next_internal_request_id -= 1
        payload = dict(type='set_visual_threat', requestId=request_id, active=active, validForMs=valid_for_ms)
        def prepare():
            if generation != self._sensory_generation or not self.connected or (valid and not valid()):
                return False
            if active:
                remaining = valid_for_ms - int(math.ceil(max(0, time.monotonic()-started)*1000))
                if remaining <= 0:
                    return False
                payload['validForMs'] = remaining
            self.visual_threat_requests[request_id] = dict(source=source, active=active, validForMs=payload['validForMs'])
            while len(self.visual_threat_requests) > 128:
                del self.visual_threat_requests[next(iter(self.visual_threat_requests))]
            return True
        sent = await self._send(payload, prepare=prepare)
        return request_id if sent else None

    async def release(self) -> dict[str, Any]:
        self.invalidate_visual_threat()
        if not self.connected:
            raise ReleaseUnknownError("release_unknown")
        if self._release_future is not None:
            raise ReleaseUnknownError("release_in_progress")
        # A callback is executed by the reader task.  Waiting for the release
        # event from that same task would deadlock, so callers must schedule
        # release from their manager instead of issuing it inline.
        if asyncio.current_task() is self._reader_task:
            raise ReleaseUnknownError("release_unknown")
        loop = asyncio.get_running_loop()
        self._release_future = loop.create_future()
        request_id = self._next_internal_request_id
        self._next_internal_request_id -= 1
        self._release_request_id = request_id
        try:
            await self._send({"type": "release_controller", "requestId": request_id})
            evidence = await asyncio.wait_for(asyncio.shield(self._release_future), timeout=self.timeout)
            task = self._reader_task
            if task is not None and task is not asyncio.current_task():
                await asyncio.wait_for(asyncio.shield(task), timeout=self.timeout)
            await self.close()
            return evidence
        except Exception as exc:
            await self.close()
            if isinstance(exc, ReleaseUnknownError):
                raise
            raise ReleaseUnknownError("release_unknown") from exc

    async def close(self) -> None:
        """Close transport permanently; this adapter instance cannot reconnect."""
        self.invalidate_visual_threat()
        self._closed = True
        self.connected = False
        self._reject_pending("adapter_closed")
        writer, self._writer = self._writer, None
        if writer is not None:
            writer.close()
        task = self._reader_task
        if task is not None and task is not asyncio.current_task() and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        if writer is not None:
            try:
                await asyncio.wait_for(writer.wait_closed(), timeout=self.timeout)
            except (ConnectionError, asyncio.TimeoutError):
                pass

    async def _send(self, payload: dict[str, Any], *, prepare=None):
        writer = self._writer
        if writer is None or writer.is_closing():
            raise BrainAdapterError("not_connected")

        async def write_and_drain() -> None:
            # The timeout wraps both lock acquisition and drain.  A stale
            # queued action must never hold a safety STOP or target release.
            async with self._write_lock:
                if prepare is not None and not prepare():
                    return False
                writer.write(json.dumps(payload, separators=(",", ":"), allow_nan=False).encode("utf-8") + b"\n")
                await writer.drain()
                return True

        try:
            return await asyncio.wait_for(write_and_drain(), timeout=self.timeout)
        except asyncio.TimeoutError as exc:
            await self._fail("send_timeout")
            raise BrainAdapterError("send_timeout") from exc
        except (ConnectionError, OSError) as exc:
            await self._fail("send_failed")
            raise BrainAdapterError("send_failed") from exc

    async def _reader_loop(self, target: dict[str, Any]) -> None:
        error: str | None = None
        try:
            assert self._reader is not None
            while True:
                line = await self._reader.readline()
                if not line:
                    break
                if len(line) > _LIMIT:
                    raise BrainAdapterError("message_too_large")
                try:
                    message = json.loads(line.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise BrainAdapterError("malformed_message") from exc
                if not isinstance(message, dict):
                    raise BrainAdapterError("malformed_message")
                await self._handle_message(message, target)
        except asyncio.CancelledError:
            raise
        except (ValueError, asyncio.LimitOverrunError):
            # StreamReader uses ValueError for an over-limit readline too.
            error = "message_too_large"
        except BrainAdapterError as exc:
            error = str(exc)
        except (ConnectionError, OSError):
            error = "connection_failed"
        finally:
            # close() is an intentional local lifecycle transition, not a
            # transport fault that should recursively re-enter its callback.
            if error is None and self._closed:
                self.connected = False
            elif error is None and not self._release_acknowledged():
                error = "connection_closed"
            if error is not None:
                await self._fail(error)
            elif not self._closed:
                self.connected = False
                self._reject_status_if_pending("connection_closed")

    async def _handle_message(self, message: dict[str, Any], target: dict[str, Any]) -> None:
        message_type = message.get("type")
        if message_type == "status":
            self._accept_status(message, target)
            await self._notify(message)
            return
        if message_type == "brain_frame":
            self._accept_frame(message)
            await self._notify(message)
            return
        if message_type == 'visual_threat_ack':
            rid = message.get('requestId')
            pending = self.visual_threat_requests.get(rid) if _is_int(rid) else None
            if (pending and message.get('accepted') is True and type(message.get('active')) is bool
                    and message['active'] == pending['active']):
                await self._notify({**message, 'source': pending['source']})
            return  # Sensory acks never enter Action application tracking.
        if message_type == "ack":
            if not _is_int(message.get("requestId")) or message.get("action") not in _ACTIONS or not isinstance(message.get("accepted"), bool):
                raise BrainAdapterError("malformed_ack")
            await self._notify(message)
            return
        if message_type == "error":
            if _is_int(message.get("requestId")) and message["requestId"] in self.visual_threat_requests:
                return  # Optional sensory rejection is not an Action failure.
            if not isinstance(message.get("error"), str) or not message["error"]:
                raise BrainAdapterError("malformed_error")
            await self._notify(message)
            return
        if message_type == "controller_released":
            self._accept_release(message)
            return
        raise BrainAdapterError("unknown_message_type")

    def _accept_status(self, message: dict[str, Any], target: dict[str, Any]) -> None:
        if any(not isinstance(message.get(key), str) or not message[key] for key in _STATUS_KEYS):
            raise BrainAdapterError("malformed_status")
        expected = {
            "backendId": target.get("expectedBackend"),
            "datasetId": target.get("expectedDataset"),
            "configHash": target.get("expectedConfigHash"),
            "graphHash": target.get("expectedGraphHash"),
            "sourceHash": target.get("expectedSourceHash"),
        }
        if any(expected[key] is not None and message[key] != expected[key] for key in expected):
            raise BrainAdapterError("identity_mismatch")
        if self.session_id is not None and (
            message["sessionId"] != self.session_id or message["instanceId"] != self.instance_id
        ):
            raise BrainAdapterError("identity_mismatch")
        self.status = dict(message)
        self.session_id = message["sessionId"]
        self.instance_id = message["instanceId"]
        self.connected = True
        if self._status_future is not None and not self._status_future.done():
            self._status_future.set_result(dict(message))

    def _accept_frame(self, message: dict[str, Any]) -> None:
        sequence = message.get("sequence")
        metadata = message.get("metadata")
        motor = message.get("motor")
        applied = message.get('appliedRequestId')
        if applied is not None and not _is_int(applied):
            raise BrainAdapterError('invalid_applied_request_id')
        if not _is_int(sequence) or not isinstance(metadata, dict) or not isinstance(motor, dict):
            raise BrainAdapterError("malformed_brain_frame")
        forward, turn = motor.get("forward"), motor.get("turn")
        if not _is_finite_number(forward) or not 0 <= forward <= 1:
            raise BrainAdapterError("invalid_motor_range")
        if not _is_finite_number(turn) or not -1 <= turn <= 1:
            raise BrainAdapterError("invalid_motor_range")
        if metadata.get("sessionId") != self.session_id or metadata.get("instanceId") != self.instance_id:
            raise BrainAdapterError("identity_mismatch")
        if self._last_sequence is not None and sequence <= self._last_sequence:
            raise BrainAdapterError("sequence_not_increasing")
        self._last_sequence = sequence
        self.latest_frame = message
        self.latest_received_at = time.monotonic()

    def _accept_release(self, message: dict[str, Any]) -> None:
        future = self._release_future
        if future is None or future.done():
            raise BrainAdapterError("unexpected_release")
        if (
            not _is_int(message.get("requestId"))
            or message["requestId"] != self._release_request_id
            or message.get("sessionId") != self.session_id
            or message.get("instanceId") != self.instance_id
            or message.get("activeControllerCount") != 0
        ):
            raise BrainAdapterError("invalid_release_evidence")
        future.set_result(dict(message))

    async def _notify(self, message: dict[str, Any]) -> None:
        try:
            result = self._on_message(message)
            if inspect.isawaitable(result):
                await result
            else:
                raise TypeError("on_message must return awaitable")
        except Exception:
            # Never keep reporting fresh transport after the consumer failed to
            # process a frame. _reader_loop converts this to a single failure.
            if message.get('type') != 'adapter_error':
                raise BrainAdapterError('consumer_failed') from None

    async def _fail(self, code: str) -> None:
        if self._failure_code is not None:
            return
        self._failure_code = code
        self.connected = False
        self._reject_pending(code)
        await self._notify({"type": "adapter_error", "error": code})
        writer = self._writer
        if writer is not None and not writer.is_closing():
            writer.close()

    def _release_acknowledged(self) -> bool:
        return (
            self._release_future is not None
            and self._release_future.done()
            and not self._release_future.cancelled()
            and self._release_future.exception() is None
        )

    def _reject_status_if_pending(self, code: str) -> None:
        if self._status_future is not None and not self._status_future.done():
            self._status_future.set_exception(BrainAdapterError(code))

    def _reject_pending(self, code: str) -> None:
        self._reject_status_if_pending(code)
        if self._release_future is not None and not self._release_future.done():
            self._release_future.set_exception(ReleaseUnknownError("release_unknown" if code else code))
