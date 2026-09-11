"""Local TCP brain server using NDJSON and latest-action-wins semantics.

The asyncio event loop owns TCP connections. A single dedicated worker thread
owns BrainController initialization, action changes, and Brian2 step calls.
This keeps the CPU-bound brain step off the event loop and prevents concurrent
access to the Brian2 Network.
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
import json
from pathlib import Path
import threading
import time
from typing import Any

from brain_controller import Action, BrainController
from motor_decoder import MotorDecoder, MotorDecoderCalibration
from poc_config import REPO_ROOT


@dataclass(frozen=True)
class PendingCommand:
    request_id: Any
    action: Action
    client_time_ms: float | int | None


class BrainWorker:
    """Own one BrainController and publish decoded frames to an asyncio queue."""

    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        frame_queue: asyncio.Queue,
        dataset: str,
        backend: str,
        seed: int,
        stimulus_frequency_hz: float,
        window_ms: float,
        decoder: MotorDecoder,
    ) -> None:
        self.loop = loop
        self.frame_queue = frame_queue
        self.dataset = dataset
        self.backend = backend
        self.seed = seed
        self.stimulus_frequency_hz = stimulus_frequency_hz
        self.window_ms = window_ms
        self.decoder = decoder
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._ready_event = threading.Event()
        self._lock = threading.Lock()
        self._latest_command: PendingCommand | None = None
        self._state = "INITIALIZING"
        self._error: str | None = None
        self._controller: BrainController | None = None
        self._received_command_count = 0
        self._overwritten_command_count = 0
        self._latest_request_id: Any = None
        self._frames_published = 0
        self._state_history = ["INITIALIZING"]
        self._cold_start_seconds: float | None = None
        self._warmup_seconds: float | None = None

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._run,
            name="brain-controller-worker",
            daemon=True,
        )
        self._thread.start()

    async def wait_ready(self) -> None:
        await asyncio.to_thread(self._ready_event.wait)
        if self._error:
            raise RuntimeError(self._error)

    def submit_command(
        self,
        request_id: Any,
        action: Action,
        client_time_ms: float | int | None,
    ) -> None:
        with self._lock:
            self._received_command_count += 1
            if self._latest_command is not None:
                self._overwritten_command_count += 1
            self._latest_command = PendingCommand(request_id, action, client_time_ms)
            self._latest_request_id = request_id

    def force_stop(self) -> None:
        """Apply STOP on the next available step when no client is connected."""

        with self._lock:
            self._latest_command = PendingCommand(None, Action.STOP, None)
            self._latest_request_id = None

    def diagnostics(self) -> dict:
        with self._lock:
            return {
                "receivedCommandCount": self._received_command_count,
                "overwrittenCommandCount": self._overwritten_command_count,
                "latestRequestId": self._latest_request_id,
            }

    def status(self) -> dict:
        with self._lock:
            controller = self._controller
            return {
                "state": self._state,
                "backend": self.backend,
                "windowMs": self.window_ms,
                "dtMs": controller.dt_ms if controller else None,
                "networkRebuildCount": controller.network_rebuild_count if controller else 0,
                "stateResetCount": controller.state_reset_count if controller else 0,
                "coldStartSeconds": self._cold_start_seconds,
                "initializationSeconds": (
                    controller.initialization_seconds if controller else None
                ),
            }

    def run_summary(self) -> dict:
        with self._lock:
            controller = self._controller
            summary = {
                "state": self._state,
                "stateHistory": list(self._state_history),
                "backend": self.backend,
                "windowMs": self.window_ms,
                "dtMs": controller.dt_ms if controller else None,
                "networkRebuildCount": controller.network_rebuild_count if controller else 0,
                "stateResetCount": controller.state_reset_count if controller else 0,
                "coldStartSeconds": self._cold_start_seconds,
                "warmupSeconds": self._warmup_seconds,
                "initializationSeconds": (
                    controller.initialization_seconds if controller else None
                ),
                "framesPublished": self._frames_published,
                "error": self._error,
            }
            summary.update(
                {
                    "receivedCommandCount": self._received_command_count,
                    "overwrittenCommandCount": self._overwritten_command_count,
                    "latestRequestId": self._latest_request_id,
                }
            )
            return summary

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join()

    def _set_state(self, state: str) -> None:
        with self._lock:
            self._state = state
            if not self._state_history or self._state_history[-1] != state:
                self._state_history.append(state)

    def _take_latest(self) -> PendingCommand | None:
        with self._lock:
            command = self._latest_command
            self._latest_command = None
            return command

    def _publish_frame(self, payload: dict) -> None:
        self._frames_published += 1
        self.loop.call_soon_threadsafe(self.frame_queue.put_nowait, payload)

    def _run(self) -> None:
        started = time.perf_counter()
        controller: BrainController | None = None
        try:
            controller = BrainController(
                dataset=self.dataset,
                backend=self.backend,
                seed=self.seed,
                stimulus_frequency_hz=self.stimulus_frequency_hz,
                window_ms=self.window_ms,
            )
            controller.initialize()
            self._controller = controller

            # The first Cython step performs code generation. Warm it before
            # advertising READY so client latency measurements exclude cold
            # compilation while the cold-start duration remains recorded.
            warmup_started = time.perf_counter()
            controller.set_action(Action.STOP)
            controller.step()
            self._warmup_seconds = time.perf_counter() - warmup_started
            self._cold_start_seconds = time.perf_counter() - started
            self._set_state("READY")
            self._ready_event.set()
            self._set_state("RUNNING")

            current_action = Action.STOP
            while not self._stop_event.is_set():
                command = self._take_latest()
                applied_request_id = None
                applied_client_time_ms = None
                if command is not None:
                    controller.set_action(command.action)
                    current_action = command.action
                    applied_request_id = command.request_id
                    applied_client_time_ms = command.client_time_ms

                frame = controller.step()
                decoded = self.decoder.decode(frame.firing_rates())
                payload = {
                    "type": "brain_frame",
                    "sequence": frame.sequence,
                    "appliedRequestId": applied_request_id,
                    "appliedClientTimeMs": applied_client_time_ms,
                    "requestedAction": current_action.value,
                    "brainTimeMs": frame.brain_simulation_time_ms,
                    "motor": {
                        "forward": float(decoded["forward"]),
                        "turn": float(decoded["turn"]),
                    },
                    "brain": {
                        "DNp09_Hz": float(frame.d_np09_hz),
                        "DNa02_R_Hz": float(frame.d_na02_r_hz),
                        "DNa02_L_Hz": float(frame.d_na02_l_hz),
                        "DNa02Difference_Hz": float(frame.d_na02_difference_hz),
                    },
                    "performance": {
                        "windowMs": float(frame.window_ms),
                        "stepWallTimeMs": float(frame.step_wall_time_ms),
                    },
                    "diagnostics": self.diagnostics(),
                }
                self._publish_frame(payload)
        except Exception as exc:  # server must expose initialization/worker errors
            self._error = f"{type(exc).__name__}: {exc}"
            self._set_state("ERROR")
            self._ready_event.set()
        finally:
            if controller is not None:
                controller.close()
            if self._state != "ERROR":
                self._set_state("SHUTTING_DOWN")


@dataclass(eq=False)
class ClientSession:
    reader: asyncio.StreamReader
    writer: asyncio.StreamWriter
    send_lock: asyncio.Lock
    identifier: str

    async def send(self, payload: dict) -> None:
        data = (json.dumps(payload, separators=(",", ":")) + "\n").encode("utf-8")
        async with self.send_lock:
            self.writer.write(data)
            await self.writer.drain()


class BrainServer:
    """Async TCP server around one persistent BrainWorker."""

    def __init__(
        self,
        host: str,
        port: int,
        worker: BrainWorker,
        run_output: Path,
        calibration_path: Path,
    ) -> None:
        self.host = host
        self.port = port
        self.worker = worker
        self.run_output = run_output
        self.calibration_path = calibration_path
        self.sessions: set[ClientSession] = set()
        self.shutdown_event = asyncio.Event()
        self._server: asyncio.AbstractServer | None = None
        self._connection_count = 0
        self._state = "INITIALIZING"
        self._started_at = time.time()

    async def start(self) -> None:
        self.worker.start()
        await self.worker.wait_ready()
        self._state = "READY"
        self._server = await asyncio.start_server(
            self._handle_client,
            host=self.host,
            port=self.port,
        )
        self._state = "RUNNING"
        sockets = self._server.sockets or []
        bound = sockets[0].getsockname() if sockets else (self.host, self.port)
        print(f"brain server READY at {bound[0]}:{bound[1]}", flush=True)

    async def serve(self) -> None:
        if self._server is None:
            raise RuntimeError("server has not been started")
        publisher = asyncio.create_task(self._publish_frames())
        try:
            await self.shutdown_event.wait()
        finally:
            self._state = "SHUTTING_DOWN"
            self._server.close()
            await self._server.wait_closed()
            publisher.cancel()
            await asyncio.gather(publisher, return_exceptions=True)
            for session in list(self.sessions):
                session.writer.close()
                await session.writer.wait_closed()
            self.sessions.clear()
            await asyncio.to_thread(self.worker.stop)
            self._write_run_summary()

    async def stop(self) -> None:
        self.shutdown_event.set()

    async def _publish_frames(self) -> None:
        while True:
            payload = await self.worker.frame_queue.get()
            if not self.sessions:
                continue
            sessions = list(self.sessions)
            results = await asyncio.gather(
                *(self._send_or_remove(session, payload) for session in sessions),
                return_exceptions=True,
            )
            del results

    async def _send_or_remove(self, session: ClientSession, payload: dict) -> None:
        try:
            await session.send(payload)
        except (ConnectionError, BrokenPipeError, asyncio.CancelledError):
            await self._remove_session(session)

    async def _remove_session(self, session: ClientSession) -> None:
        if session in self.sessions:
            self.sessions.remove(session)
        if not self.sessions:
            self.worker.force_stop()
        try:
            session.writer.close()
            await session.writer.wait_closed()
        except (ConnectionError, BrokenPipeError):
            pass

    async def _handle_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        self._connection_count += 1
        session = ClientSession(
            reader=reader,
            writer=writer,
            send_lock=asyncio.Lock(),
            identifier=f"client-{self._connection_count}",
        )
        self.sessions.add(session)
        await session.send(
            {
                "type": "status",
                "state": "READY",
                "backend": self.worker.backend,
                "windowMs": self.worker.window_ms,
                "dtMs": self.worker.status()["dtMs"],
                "networkRebuildCount": self.worker.status()["networkRebuildCount"],
                "stateResetCount": self.worker.status()["stateResetCount"],
            }
        )
        try:
            while not reader.at_eof():
                line = await reader.readline()
                if not line:
                    break
                await self._handle_command_line(session, line)
        except (ConnectionError, BrokenPipeError, asyncio.IncompleteReadError):
            pass
        finally:
            await self._remove_session(session)

    async def _handle_command_line(self, session: ClientSession, line: bytes) -> None:
        try:
            payload = json.loads(line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            await session.send(
                {"type": "error", "error": "invalid_json", "message": str(exc)}
            )
            return
        if not isinstance(payload, dict) or payload.get("type") != "set_action":
            await session.send(
                {
                    "type": "error",
                    "error": "invalid_command",
                    "message": "expected type=set_action",
                }
            )
            return
        request_id = payload.get("requestId")
        if request_id is None:
            await session.send(
                {"type": "error", "error": "missing_request_id", "message": "requestId is required"}
            )
            return
        action_name = payload.get("action")
        try:
            action = Action(str(action_name))
        except (ValueError, TypeError):
            await session.send(
                {
                    "type": "error",
                    "requestId": request_id,
                    "error": "unknown_action",
                    "message": f"unknown action {action_name!r}",
                    "allowedActions": [item.value for item in Action],
                }
            )
            return
        client_time_ms = payload.get("clientTimeMs")
        self.worker.submit_command(request_id, action, client_time_ms)
        await session.send(
            {
                "type": "ack",
                "requestId": request_id,
                "action": action.value,
                "accepted": True,
            }
        )

    def _write_run_summary(self) -> None:
        summary = {
            "protocolVersion": 1,
            "host": self.host,
            "port": self.port,
            "calibrationPath": str(self.calibration_path),
            "connectionCount": self._connection_count,
            "serverState": self._state,
            "startedAtUnixSeconds": self._started_at,
            "stoppedAtUnixSeconds": time.time(),
            "worker": self.worker.run_summary(),
        }
        self.run_output.parent.mkdir(parents=True, exist_ok=True)
        self.run_output.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")


def load_decoder(calibration_path: Path) -> MotorDecoder:
    calibration = MotorDecoderCalibration.from_json(calibration_path)
    return MotorDecoder(calibration.decoder_config())


async def async_main(args: argparse.Namespace) -> None:
    loop = asyncio.get_running_loop()
    calibration_path = Path(args.calibration_source)
    decoder = load_decoder(calibration_path)
    frame_queue: asyncio.Queue = asyncio.Queue()
    worker = BrainWorker(
        loop=loop,
        frame_queue=frame_queue,
        dataset=args.dataset,
        backend=args.backend,
        seed=args.seed,
        stimulus_frequency_hz=args.stimulus_frequency_hz,
        window_ms=args.window_ms,
        decoder=decoder,
    )
    server = BrainServer(
        host=args.host,
        port=args.port,
        worker=worker,
        run_output=Path(args.run_output),
        calibration_path=calibration_path,
    )
    try:
        await server.start()
        await server.serve()
    except KeyboardInterrupt:
        await server.stop()
        await server.serve()
    except Exception:
        if worker.status()["state"] == "ERROR":
            server._write_run_summary()
        raise


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--dataset", choices=("v630", "v783"), default="v783")
    parser.add_argument("--backend", choices=("numpy", "cython"), default="cython")
    parser.add_argument("--seed", type=int, default=20260910)
    parser.add_argument("--stimulus-frequency-hz", type=float, default=100.0)
    parser.add_argument("--window-ms", type=float, default=50.0)
    parser.add_argument(
        "--calibration-source",
        default=str(REPO_ROOT / "results" / "codex_run" / "motor_decoder_calibration.json"),
    )
    parser.add_argument(
        "--run-output",
        default=str(REPO_ROOT / "results" / "codex_run" / "brain_server_run.json"),
    )
    return parser.parse_args()


if __name__ == "__main__":
    try:
        asyncio.run(async_main(parse_args()))
    except KeyboardInterrupt:
        pass
