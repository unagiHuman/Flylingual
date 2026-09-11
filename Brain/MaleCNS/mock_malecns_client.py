"""Sequential localhost E2E probe for the MaleCNS NDJSON server."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import statistics
import time


ACTIONS = ("STOP", "FORWARD", "TURN_R", "TURN_L", "FORWARD_R", "FORWARD_L")


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    reader, writer = await asyncio.open_connection(args.host, args.port)
    status = json.loads((await reader.readline()).decode("utf-8"))
    samples = []
    for request_id, action in enumerate(ACTIONS, 1):
        started = time.perf_counter()
        command = {"type": "set_action", "requestId": request_id, "action": action, "clientTimeMs": started * 1000.0}
        writer.write((json.dumps(command) + "\n").encode("utf-8")); await writer.drain()
        while True:
            message = json.loads((await reader.readline()).decode("utf-8"))
            if message.get("type") == "brain_frame" and message.get("appliedRequestId") == request_id:
                break
        samples.append(
            {
                "requestId": request_id,
                "action": action,
                "e2eMs": (time.perf_counter() - started) * 1000.0,
                "frame": message,
            }
        )
    writer.close(); await writer.wait_closed()
    latencies = [sample["e2eMs"] for sample in samples]
    payload = {
        "status": status,
        "samples": samples,
        "performance": {
            "sampleCount": len(samples),
            "medianE2eMs": statistics.median(latencies),
            "p95E2eMs": sorted(latencies)[-1],
            "maxE2eMs": max(latencies),
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload["performance"]))


if __name__ == "__main__":
    asyncio.run(main())
