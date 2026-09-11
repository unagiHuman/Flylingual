"""MaleCNS PoC TCP/NDJSON server using one persistent brain worker."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import threading
import time
from typing import Any

from game_controller import Action, MaleCNSGameController
from motor_decoder import MotorDecoder


class Worker:
    def __init__(self, loop: asyncio.AbstractEventLoop, queue: asyncio.Queue, args: argparse.Namespace):
        self.loop = loop
        self.queue = queue
        self.args = args
        self.thread: threading.Thread | None = None
        self.stop_event = threading.Event()
        self.ready_event = threading.Event()
        self.lock = threading.Lock()
        self.latest_command: tuple[Any, Action, float | None] | None = None
        self.error: str | None = None
        self.controller: MaleCNSGameController | None = None
        self.received = 0
        self.superseded = 0

    def start(self) -> None:
        self.thread = threading.Thread(target=self.run, name="malecns-brain-worker", daemon=True)
        self.thread.start()

    def submit(self, request_id: Any, action: Action, client_time_ms: float | None) -> None:
        with self.lock:
            self.received += 1
            if self.latest_command is not None:
                self.superseded += 1
            self.latest_command = (request_id, action, client_time_ms)

    def run(self) -> None:
        try:
            controller = MaleCNSGameController(
                self.args.graph,
                self.args.mapping,
                self.args.seed,
                self.args.window_ms,
                self.args.recurrent_weight_scale,
            ).initialize()
            decoder = MotorDecoder(self.args.calibration)
            self.controller = controller
            self.ready_event.set()
            while not self.stop_event.is_set():
                request_id = None
                client_time_ms = None
                with self.lock:
                    command = self.latest_command
                    self.latest_command = None
                if command is not None:
                    request_id, action, client_time_ms = command
                    controller.set_action(action)
                frame = controller.step()
                frame.update(
                    {
                        "type": "brain_frame",
                        "appliedRequestId": request_id,
                        "appliedClientTimeMs": client_time_ms,
                        "motor": decoder.decode(frame["brain"]),
                        "diagnostics": {
                            "receivedCommandCount": self.received,
                            "supersededCommandCount": self.superseded,
                            "networkRebuildCount": controller.network_rebuild_count,
                            "stateResetCount": controller.state_reset_count,
                        },
                    }
                )
                frame["metadata"]["ready"] = False
                frame["metadata"]["experimentalRuntimeAvailable"] = True
                frame["metadata"]["productionReady"] = False
                frame["metadata"]["performanceTargetMet"] = False
                self.loop.call_soon_threadsafe(self.queue.put_nowait, frame)
        except Exception as exc:
            self.error = f"{type(exc).__name__}: {exc}"
            self.ready_event.set()

    def stop(self) -> None:
        self.stop_event.set()
        if self.thread:
            self.thread.join()


class Server:
    worker_class = Worker
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.sessions: set[asyncio.StreamWriter] = set()
        self.queue: asyncio.Queue = asyncio.Queue()
        self.worker: Worker | None = None

    async def run(self) -> None:
        loop = asyncio.get_running_loop()
        self.worker = self.worker_class(loop, self.queue, self.args)
        self.worker.start()
        await asyncio.to_thread(self.worker.ready_event.wait)
        if self.worker.error:
            raise RuntimeError(self.worker.error)
        server = await asyncio.start_server(self.handle_client, self.args.host, self.args.port)
        publisher = asyncio.create_task(self.publish())
        print(f"MaleCNS brain server READY at {self.args.host}:{self.args.port}", flush=True)
        try:
            async with server:
                await server.serve_forever()
        finally:
            publisher.cancel()
            await asyncio.gather(publisher, return_exceptions=True)
            await asyncio.to_thread(self.worker.stop)

    async def send(self, writer: asyncio.StreamWriter, payload: dict) -> None:
        writer.write((json.dumps(payload, separators=(",", ":")) + "\n").encode("utf-8"))
        await writer.drain()

    async def publish(self) -> None:
        while True:
            frame = await self.queue.get()
            for writer in list(self.sessions):
                try:
                    await self.send(writer, frame)
                except (ConnectionError, BrokenPipeError):
                    self.sessions.discard(writer)

    async def handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        if self.sessions:
            await self.send(writer, {"type": "error", "error": "controller_already_connected"})
            writer.close(); await writer.wait_closed(); return
        self.sessions.add(writer)
        await self.send(
            writer,
            self.status_payload(),
        )
        try:
            while line := await reader.readline():
                try:
                    payload = json.loads(line.decode("utf-8"))
                    if not isinstance(payload, dict):
                        raise ValueError("expected JSON object")
                    if payload.get("type") != "set_action" or payload.get("requestId") is None:
                        raise ValueError("expected type=set_action and requestId")
                    action = Action(str(payload.get("action")))
                    self.worker.submit(payload["requestId"], action, payload.get("clientTimeMs"))
                    await self.send(writer, {"type": "ack", "requestId": payload["requestId"], "action": action.value, "accepted": True})
                except (ValueError, TypeError, json.JSONDecodeError) as exc:
                    await self.send(writer, {"type": "error", "error": "invalid_command", "message": str(exc)})
        finally:
            self.sessions.discard(writer)
            if self.worker:
                self.worker.submit(None, Action.STOP, None)
            writer.close(); await writer.wait_closed()

    def status_payload(self):
        return {
                "type": "status",
                "state": "READY",
                "backendId": "malecns_lif_poc",
                "datasetId": "male-cns:v1.0",
                "dynamicsModel": "Shiu-style LIF adaptation in persistent NumPy runtime",
                "validationCandidate": "Shiu-compatible LIF dynamics applied to the MaleCNS connectome",
                "validationCandidateIntegrated": False,
                "mode": "MALECNS",
                "windowMs": self.args.window_ms,
                "ready": False,
                "experimentalRuntimeAvailable": True,
                "productionReady": False,
                "performanceTargetMet": False,
            }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--graph", type=Path, required=True)
    parser.add_argument("--mapping", type=Path, required=True)
    parser.add_argument("--calibration", type=Path, required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--seed", type=int, default=20260913)
    parser.add_argument("--window-ms", type=float, default=50.0)
    parser.add_argument("--recurrent-weight-scale", type=float, default=0.1)
    return parser.parse_args()


if __name__ == "__main__":
    try:
        asyncio.run(Server(parse_args()).run())
    except KeyboardInterrupt:
        pass
