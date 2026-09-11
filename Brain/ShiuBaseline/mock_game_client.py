"""Mock game client for the local brain TCP server.

Modes:
  interactive - send W/A/D-style commands from a terminal
  latency     - send at least 30 sequential action changes and write latency CSV
  burst       - send four commands at 20 ms intervals and verify latest wins
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
from pathlib import Path
import statistics
import time
from typing import Any

from poc_config import REPO_ROOT


ACTION_NAMES = {"STOP", "FORWARD", "TURN_R", "TURN_L", "FORWARD_R", "FORWARD_L"}
KEY_TO_ACTION = {
    "": "STOP",
    "S": "STOP",
    "STOP": "STOP",
    "W": "FORWARD",
    "A": "TURN_L",
    "D": "TURN_R",
    "WA": "FORWARD_L",
    "AW": "FORWARD_L",
    "WD": "FORWARD_R",
    "DW": "FORWARD_R",
    "FORWARD": "FORWARD",
    "TURN_L": "TURN_L",
    "TURN_R": "TURN_R",
    "FORWARD_L": "FORWARD_L",
    "FORWARD_R": "FORWARD_R",
}


class MockClient:
    def __init__(self, host: str, port: int) -> None:
        self.host = host
        self.port = port
        self.reader: asyncio.StreamReader | None = None
        self.writer: asyncio.StreamWriter | None = None
        self.messages: asyncio.Queue = asyncio.Queue()
        self.reader_task: asyncio.Task | None = None
        self.next_request_id = 1

    async def connect(self) -> dict:
        self.reader, self.writer = await asyncio.open_connection(self.host, self.port)
        self.reader_task = asyncio.create_task(self._read_messages())
        while True:
            message = await self.messages.get()
            if message.get("type") == "status":
                if message.get("state") != "READY":
                    raise RuntimeError(f"server is not READY: {message}")
                return message

    async def close(self) -> None:
        if self.reader_task:
            self.reader_task.cancel()
            await asyncio.gather(self.reader_task, return_exceptions=True)
        if self.writer:
            self.writer.close()
            await self.writer.wait_closed()

    async def _read_messages(self) -> None:
        assert self.reader is not None
        try:
            while True:
                line = await self.reader.readline()
                if not line:
                    break
                try:
                    message = json.loads(line.decode("utf-8"))
                except json.JSONDecodeError:
                    continue
                await self.messages.put(message)
        except (asyncio.CancelledError, ConnectionError):
            pass

    async def send_action(self, action: str, request_id: Any | None = None) -> tuple[Any, float]:
        if action not in ACTION_NAMES:
            raise ValueError(f"unknown action: {action}")
        if request_id is None:
            request_id = self.next_request_id
            self.next_request_id += 1
        send_time = time.perf_counter()
        payload = {
            "type": "set_action",
            "requestId": request_id,
            "action": action,
            "clientTimeMs": time.time() * 1000.0,
        }
        assert self.writer is not None
        self.writer.write((json.dumps(payload, separators=(",", ":")) + "\n").encode())
        await self.writer.drain()
        return request_id, send_time

    async def wait_for_applied(self, request_id: Any, timeout: float = 10.0) -> dict:
        deadline = time.perf_counter() + timeout
        while True:
            remaining = deadline - time.perf_counter()
            if remaining <= 0:
                raise TimeoutError(f"timed out waiting for appliedRequestId={request_id}")
            message = await asyncio.wait_for(self.messages.get(), remaining)
            if message.get("type") == "error":
                raise RuntimeError(message)
            if (
                message.get("type") == "brain_frame"
                and message.get("appliedRequestId") == request_id
            ):
                return message


async def run_interactive(client: MockClient) -> None:
    print("Commands: W, A, D, W+A, W+D, S/empty=STOP, Q=quit")
    while True:
        text = await asyncio.to_thread(input, "game> ")
        normalized = text.strip().upper().replace(" ", "")
        if normalized == "Q":
            return
        action = KEY_TO_ACTION.get(normalized)
        if action is None:
            print(f"unknown command: {text}")
            continue
        request_id, _ = await client.send_action(action)
        print(f"sent requestId={request_id} action={action}")
        try:
            frame = await client.wait_for_applied(request_id)
            print(json.dumps(frame, ensure_ascii=False, indent=2))
        except TimeoutError as exc:
            print(str(exc))


async def run_latency(client: MockClient, count: int, output: Path) -> dict:
    actions = ["STOP", "FORWARD", "TURN_R", "TURN_L", "FORWARD_R", "FORWARD_L"]
    rows = []
    for index in range(count):
        action = actions[index % len(actions)]
        request_id, send_perf = await client.send_action(action)
        frame = await client.wait_for_applied(request_id)
        receive_perf = time.perf_counter()
        rows.append(
            {
                "requestId": request_id,
                "action": action,
                "sendTimePerfSeconds": send_perf,
                "applyFrameSequence": frame["sequence"],
                "receiveTimePerfSeconds": receive_perf,
                "endToEndLatencyMs": (receive_perf - send_perf) * 1000.0,
                "brainStepWallTimeMs": frame["performance"]["stepWallTimeMs"],
            }
        )

    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    latencies = [row["endToEndLatencyMs"] for row in rows]
    summary = {
        "count": len(rows),
        "minMs": min(latencies),
        "meanMs": statistics.mean(latencies),
        "medianMs": statistics.median(latencies),
        "p95Ms": _percentile(latencies, 95),
        "maxMs": max(latencies),
        "output": str(output),
    }
    print(json.dumps(summary, indent=2))
    return summary


async def run_burst(client: MockClient, output: Path) -> dict:
    # Wait for one current frame so the four sends happen during a known
    # running brain step in normal operation.
    baseline_frame = await _wait_for_any_frame(client)
    first_diag = baseline_frame.get("diagnostics", {})
    burst_ids = []
    applied_ids = []
    burst_commands = ["FORWARD", "FORWARD_R", "FORWARD_L", "STOP"]
    send_records = []
    for action in burst_commands:
        request_id, send_perf = await client.send_action(action)
        burst_ids.append(request_id)
        send_records.append(
            {"requestId": request_id, "action": action, "sendTimePerfSeconds": send_perf}
        )
        if action == burst_commands[0]:
            await asyncio.sleep(0.02)
        else:
            await asyncio.sleep(0.02)

    final_frame = None
    collected = []
    deadline = time.perf_counter() + 10.0
    while time.perf_counter() < deadline:
        message = await asyncio.wait_for(
            client.messages.get(), max(0.01, deadline - time.perf_counter())
        )
        if message.get("type") != "brain_frame":
            continue
        collected.append(message)
        request_id = message.get("appliedRequestId")
        if request_id in burst_ids:
            applied_ids.append(request_id)
        if first_diag is None:
            first_diag = message.get("diagnostics", {})
        if request_id == burst_ids[-1]:
            final_frame = message
            break
    if final_frame is None:
        raise TimeoutError("burst test did not observe final STOP application")
    # Give the worker one additional opportunity to publish a queued stale
    # action; middle requests must not appear after the final STOP.
    await asyncio.sleep(0.25)
    while not client.messages.empty():
        message = client.messages.get_nowait()
        if message.get("type") == "brain_frame":
            collected.append(message)
            if message.get("appliedRequestId") in burst_ids:
                applied_ids.append(message.get("appliedRequestId"))

    first_overwritten = int((first_diag or {}).get("overwrittenCommandCount", 0))
    final_overwritten = int(
        final_frame.get("diagnostics", {}).get("overwrittenCommandCount", first_overwritten)
    )
    middle_ids = set(burst_ids[1:-1])
    success = (
        burst_ids[-1] in applied_ids
        and not (middle_ids & set(applied_ids))
    )
    result = {
        "protocolVersion": 1,
        "commands": send_records,
        "appliedRequestIds": applied_ids,
        "finalAppliedRequestId": final_frame.get("appliedRequestId"),
        "overwrittenCommandCountDelta": final_overwritten - first_overwritten,
        "success": success,
        "rule": "latest action wins; middle burst commands must not be replayed",
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return result


async def run_disconnect(client: MockClient, output: Path) -> dict:
    request_id, _ = await client.send_action("FORWARD")
    await asyncio.sleep(0.02)
    await client.close()

    reconnected = MockClient(client.host, client.port)
    status = await reconnected.connect()
    stop_frame = None
    deadline = time.perf_counter() + 5.0
    try:
        while time.perf_counter() < deadline:
            message = await asyncio.wait_for(
                reconnected.messages.get(), max(0.01, deadline - time.perf_counter())
            )
            if (
                message.get("type") == "brain_frame"
                and message.get("requestedAction") == "STOP"
            ):
                stop_frame = message
                break
    finally:
        await reconnected.close()
    result = {
        "protocolVersion": 1,
        "disconnectedRequestId": request_id,
        "reconnectedStatus": status,
        "stopObservedAfterReconnect": stop_frame is not None,
        "networkRebuildCount": status.get("networkRebuildCount"),
        "stateResetCount": status.get("stateResetCount"),
        "disconnectPolicy": "when no client is connected, STOP is submitted for the next step",
        "success": (
            stop_frame is not None
            and status.get("networkRebuildCount") == 1
            and status.get("stateResetCount") == 0
        ),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return result


async def _wait_for_any_frame(client: MockClient) -> dict:
    while True:
        message = await client.messages.get()
        if message.get("type") == "brain_frame":
            return message


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    position = (len(ordered) - 1) * percentile / 100.0
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return float(ordered[lower] + (ordered[upper] - ordered[lower]) * fraction)


async def async_main(args: argparse.Namespace) -> None:
    client = MockClient(args.host, args.port)
    status = await client.connect()
    print(json.dumps(status, indent=2))
    try:
        if args.mode == "interactive":
            await run_interactive(client)
        elif args.mode == "latency":
            await run_latency(client, args.count, Path(args.latency_output))
        elif args.mode == "burst":
            result = await run_burst(client, Path(args.burst_output))
            if not result["success"]:
                raise RuntimeError("latest-action-wins burst test failed")
        elif args.mode == "disconnect":
            result = await run_disconnect(client, Path(args.disconnect_output))
            if not result["success"]:
                raise RuntimeError("disconnect/reconnect test failed")
    finally:
        await client.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument(
        "--mode",
        choices=("interactive", "latency", "burst", "disconnect"),
        default="interactive",
    )
    parser.add_argument("--count", type=int, default=30)
    parser.add_argument(
        "--latency-output",
        default=str(REPO_ROOT / "results" / "codex_run" / "brain_server_latency.csv"),
    )
    parser.add_argument(
        "--burst-output",
        default=str(REPO_ROOT / "results" / "codex_run" / "brain_server_burst_test.json"),
    )
    parser.add_argument(
        "--disconnect-output",
        default=str(
            REPO_ROOT / "results" / "codex_run" / "brain_server_disconnect_test.json"
        ),
    )
    return parser.parse_args()


if __name__ == "__main__":
    asyncio.run(async_main(parse_args()))
