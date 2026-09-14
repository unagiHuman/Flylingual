"""Bridge-compatible transport for the validated persistent AnalogServer.

This module intentionally changes only transport ownership and provenance
observability.  The AnalogWorker and its controller continue to own all brain,
stimulus, and motor-decoder state.
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import math
from pathlib import Path
import uuid
from typing import Any

from analog_controller import ROOT
from brain_server_analog import AnalogServer, parse_args
from game_controller import Action
from visual_threat import validate_command


_GRAPH_FILES = ("body_ids.npy", "indptr.npy", "targets.npy", "weights.npy")
_SOURCE_FILES = (
    "brain_server_bridge.py",
    "brain_server_analog.py",
    "brain_server_malecns.py",
    "analog_controller.py",
    "neural_visualization.py",
    "visual_threat.py",
    "config/visual_threat_v1.json",
    "analog_motor_decoder.py",
    "game_controller.py",
    "shiu_compatible.py",
    "lif_kernels.py",
    "temporal_motor_decoder.py",
)


def _digest_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _aggregate_hash(paths: dict[str, Path]) -> str:
    """Hash a stable filename-to-content-digest manifest."""
    manifest = {name: _digest_file(path) for name, path in paths.items()}
    encoded = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_finite_number(value: Any) -> bool:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(float(value))
    except OverflowError:
        return False


class BridgeAnalogServer(AnalogServer):
    """AnalogServer with one controller session and explicit release evidence."""

    supports_visual_threat = True

    def __init__(self, args: Any):
        super().__init__(args)
        module_dir = Path(__file__).resolve().parent
        self.instance_id = str(uuid.uuid4())
        self._session_ids: dict[asyncio.StreamWriter, str] = {}
        self.graph_hash = _aggregate_hash({name: Path(args.graph) / name for name in _GRAPH_FILES})
        self.config_hash = _digest_file(Path(args.config))
        self.source_hash = _aggregate_hash({name: module_dir / name for name in _SOURCE_FILES})

    @staticmethod
    def _log(event: str, **fields: Any) -> None:
        print(json.dumps({"event": event, **fields}, sort_keys=True, separators=(",", ":")), flush=True)

    def status_payload(self, session_id: str | None = None) -> dict[str, Any]:
        payload = super().status_payload()
        payload.update(
            {
                "datasetId": "male-cns:v1.0",
                "configHash": self.config_hash,
                "graphHash": self.graph_hash,
                "sourceHash": self.source_hash,
                "instanceId": self.instance_id,
                "sessionId": session_id,
                "activeControllerCount": len(self.sessions),
            }
        )
        return payload

    def _validate_set_action(self, payload: dict[str, Any]) -> tuple[int, Action, float | None]:
        if payload.get("type") != "set_action":
            raise ValueError("expected_set_action")
        request_id = payload.get("requestId")
        if not _is_int(request_id):
            raise ValueError("invalid_request_id")
        action_value = payload.get("action")
        if not isinstance(action_value, str):
            raise ValueError("invalid_action")
        try:
            action = Action(action_value)
        except ValueError as exc:
            raise ValueError("invalid_action") from exc
        client_time = payload.get("clientTimeMs")
        if client_time is not None and not _is_finite_number(client_time):
            raise ValueError("invalid_client_time")
        return request_id, action, client_time

    @staticmethod
    def _validate_release(payload: dict[str, Any]) -> int:
        if payload.get("type") != "release_controller":
            raise ValueError("expected_release_controller")
        request_id = payload.get("requestId")
        if not _is_int(request_id):
            raise ValueError("invalid_request_id")
        return request_id

    async def _release_writer(
        self,
        writer: asyncio.StreamWriter,
        session_id: str,
        request_id: int | None,
        reason: str,
    ) -> None:
        """Submit STOP before making the single controller slot reusable."""
        if self.worker:
            self.worker.submit(request_id, Action.STOP, None)
        self.sessions.discard(writer)
        self._session_ids.pop(writer, None)
        self._log(
            "controller_release",
            activeControllerCount=len(self.sessions),
            instanceId=self.instance_id,
            reason=reason,
            sessionId=session_id,
        )

    async def handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        if self.sessions:
            self._log("controller_connect_rejected", instanceId=self.instance_id, reason="controller_already_connected")
            try:
                await self.send(writer, {"type": "error", "error": "controller_already_connected"})
            finally:
                writer.close()
                await writer.wait_closed()
            return

        session_id = str(uuid.uuid4())
        released = False
        last_visual_request_id = None
        self.sessions.add(writer)
        self._session_ids[writer] = session_id
        self._log(
            "controller_connect",
            activeControllerCount=len(self.sessions),
            instanceId=self.instance_id,
            sessionId=session_id,
        )
        try:
            # The try/finally intentionally includes this first send: a failed
            # status write must not strand the worker's controller slot.
            await self.send(writer, self.status_payload(session_id))
            while line := await reader.readline():
                try:
                    payload = json.loads(line.decode("utf-8"))
                    if not isinstance(payload, dict):
                        raise ValueError("expected_json_object")
                    message_type = payload.get("type")
                    if message_type == "release_controller":
                        request_id = self._validate_release(payload)
                        await self._release_writer(writer, session_id, request_id, "explicit_release")
                        released = True
                        await self.send(
                            writer,
                            {
                                "type": "controller_released",
                                "requestId": request_id,
                                "sessionId": session_id,
                                "instanceId": self.instance_id,
                                "activeControllerCount": 0,
                            },
                        )
                        return
                    if message_type == 'set_visual_threat':
                        request_id, active, valid_for_ms = validate_command(payload)
                        if last_visual_request_id is not None and (
                                request_id >= last_visual_request_id if last_visual_request_id < 0
                                else request_id <= last_visual_request_id):
                            raise ValueError('visual_threat_request_reused')
                        if not self.worker or getattr(self.worker.controller,'visual_threat',None) is None:
                            raise RuntimeError('visual_threat_unavailable')
                        self.worker.submit_visual_threat(request_id,active,valid_for_ms)
                        last_visual_request_id = request_id
                        await self.send(writer,{'type':'visual_threat_ack','requestId':request_id,
                                                'accepted':True,'active':active})
                        continue
                    request_id, action, client_time = self._validate_set_action(payload)
                    if not self.worker:
                        raise RuntimeError("worker_unavailable")
                    self.worker.submit(request_id, action, client_time)
                    await self.send(
                        writer,
                        {"type": "ack", "requestId": request_id, "action": action.value, "accepted": True},
                    )
                except UnicodeDecodeError:
                    await self.send(writer, {"type": "error", "error": "invalid_command", "message": "malformed_utf8"})
                except json.JSONDecodeError:
                    await self.send(writer, {"type": "error", "error": "invalid_command", "message": "malformed_json"})
                except (RuntimeError, TypeError, ValueError):
                    # Never reflect parser/exception text: malformed input can
                    # contain secrets or arbitrarily large untrusted payloads.
                    await self.send(writer, {"type": "error", "error": "invalid_command", "message": "invalid_command"})
        except (ConnectionError, BrokenPipeError, asyncio.TimeoutError) as exc:
            self._log("controller_send_or_connection_failed", instanceId=self.instance_id, sessionId=session_id, error=type(exc).__name__)
        finally:
            # An explicit release already submitted STOP and freed this exact
            # session.  Do not submit another STOP after a newer client arrives.
            if not released and writer in self.sessions:
                await self._release_writer(writer, session_id, None, "disconnect")
                self._log("controller_disconnect", instanceId=self.instance_id, sessionId=session_id)
            writer.close()
            try:
                await writer.wait_closed()
            except ConnectionError:
                pass

    async def publish(self) -> None:
        while True:
            frame = await self.queue.get()
            for writer in list(self.sessions):
                session_id = self._session_ids.get(writer)
                if session_id is None:
                    continue
                published = copy.deepcopy(frame)
                metadata = published.setdefault("metadata", {})
                metadata["instanceId"] = self.instance_id
                metadata["sessionId"] = session_id
                try:
                    await self.send(writer, published)
                except (ConnectionError, BrokenPipeError, asyncio.TimeoutError):
                    self._log("controller_send_failed", instanceId=self.instance_id, sessionId=session_id)
                    # handle_client owns cleanup; closing makes its read wake.
                    writer.close()


if __name__ == "__main__":
    try:
        asyncio.run(BridgeAnalogServer(parse_args()).run())
    except KeyboardInterrupt:
        pass
