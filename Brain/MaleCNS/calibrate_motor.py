"""Create a calibration from training-seed persistent sequences and score holdout."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

import numpy as np

from motor_decoder import MotorDecoder


FORWARD_ACTIONS = {"FORWARD", "FORWARD_R", "FORWARD_L"}
TURN_ACTIONS = {"TURN_R", "TURN_L", "FORWARD_R", "FORWARD_L"}


def load_frames(paths: list[Path]) -> list[dict]:
    return [frame for path in paths for frame in json.loads(path.read_text(encoding="utf-8"))["frames"]]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--train", type=Path, nargs="+", required=True)
    parser.add_argument("--holdout", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    train = load_frames(args.train)
    forward = [f["brain"]["DNp09_Hz"] for f in train if f["requestedAction"] in FORWARD_ACTIONS]
    turn = [abs(f["brain"]["DNa02Difference_Hz"]) for f in train if f["requestedAction"] in TURN_ACTIONS]
    straight_delta = [abs(f["brain"]["DNa02Difference_Hz"]) for f in train if f["requestedAction"] == "FORWARD"]
    window_ms = float(train[0]["windowMs"])
    one_spike_hz = 1000.0 / window_ms
    forward_reference = float(np.percentile(forward, 95))
    turn_reference = float(np.percentile(turn, 95))
    deadzone = float(np.percentile(straight_delta, 95) + one_spike_hz / 4.0)
    payload = {
        "capturedAtUtc": datetime.now(timezone.utc).isoformat(),
        "datasetId": "male-cns:v1.0",
        "mappingId": "exploratory-direct-inputs-v1",
        "recurrentWeightScale": 0.1,
        "trainingSeeds": [json.loads(path.read_text())["seed"] for path in args.train],
        "holdoutSeed": json.loads(args.holdout.read_text())["seed"],
        "calibration": {
            "forwardReferenceHz": forward_reference,
            "turnReferenceHz": turn_reference,
            "turnDeadzoneHz": deadzone,
            "forwardSampleCount": len(forward),
            "turnSampleCount": len(turn),
            "straightSampleCount": len(straight_delta),
            "method": "95th percentiles; deadzone is straight 95th percentile plus quarter-window spike resolution",
        },
        "decoderConfig": {
            "forwardReferenceHz": forward_reference,
            "turnReferenceHz": turn_reference,
            "turnDeadzoneHz": deadzone,
        },
        "holdout": [],
        "limitations": "Three single-sequence seeds are PoC evidence, not biological validation or robust production calibration.",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    decoder = MotorDecoder(args.output)
    holdout = json.loads(args.holdout.read_text(encoding="utf-8"))["frames"]
    payload["holdout"] = [
        {
            "sequence": frame["sequence"],
            "requestedAction": frame["requestedAction"],
            "raw": frame["brain"],
            "motor": decoder.decode(frame["brain"]),
        }
        for frame in holdout
    ]
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote calibration and {len(holdout)} holdout frames to {args.output}")


if __name__ == "__main__":
    main()
