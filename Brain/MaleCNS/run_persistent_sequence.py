"""Run the bounded STOP/F/R/L/combined persistent MaleCNS sequence."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import resource
import statistics

from game_controller import Action, MaleCNSGameController


SEQUENCE = (
    Action.STOP, Action.FORWARD, Action.STOP, Action.TURN_R, Action.STOP,
    Action.TURN_L, Action.STOP, Action.FORWARD_R, Action.STOP,
    Action.FORWARD_L, Action.STOP,
)


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    position = int(round((len(ordered) - 1) * fraction))
    return ordered[position]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--graph", type=Path, required=True)
    parser.add_argument("--mapping", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=20260911)
    parser.add_argument("--window-ms", type=float, default=50.0)
    parser.add_argument("--recurrent-weight-scale", type=float, default=1.0)
    args = parser.parse_args()
    controller = MaleCNSGameController(
        args.graph, args.mapping, args.seed, args.window_ms, args.recurrent_weight_scale
    ).initialize()
    frames = []
    for action in SEQUENCE:
        controller.set_action(action)
        frames.append(controller.step())
    wall = [frame["performance"]["stepWallTimeMs"] for frame in frames]
    payload = {
        "capturedAtUtc": datetime.now(timezone.utc).isoformat(),
        "datasetId": "male-cns:v1.0",
        "seed": args.seed,
        "windowMs": args.window_ms,
        "recurrentWeightScale": args.recurrent_weight_scale,
        "networkRebuildCount": controller.network_rebuild_count,
        "stateResetCount": controller.state_reset_count,
        "frames": frames,
        "performance": {
            "sampleCount": len(wall),
            "meanMs": statistics.mean(wall),
            "medianMs": statistics.median(wall),
            "p95Ms": percentile(wall, 0.95),
            "maxMs": max(wall),
            "wallToSimRatioMean": statistics.mean(wall) / args.window_ms,
        },
        "peakProcessRssBytes": int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(frames)} persistent frames to {args.output}")


if __name__ == "__main__":
    main()
