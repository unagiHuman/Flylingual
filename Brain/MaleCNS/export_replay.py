"""Export a persistent sequence as current nested BrainFrame NDJSON with motor."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from motor_decoder import MotorDecoder


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sequence", type=Path, required=True)
    parser.add_argument("--calibration", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload = json.loads(args.sequence.read_text(encoding="utf-8"))
    decoder = MotorDecoder(args.calibration)
    lines = []
    for frame in payload["frames"]:
        lines.append(
            json.dumps(
                {
                    "type": "brain_frame",
                    "sequence": frame["sequence"],
                    "appliedRequestId": frame["sequence"],
                    "appliedClientTimeMs": 0.0,
                    "requestedAction": frame["requestedAction"],
                    "brainTimeMs": frame["brainSimulationTimeMs"],
                    "motor": decoder.decode(frame["brain"]),
                    "brain": frame["brain"],
                    "performance": frame["performance"],
                    "metadata": {
                        "backendId": "malecns_lif_poc",
                        "datasetId": "male-cns:v1.0",
                        "dynamicsModel": "Shiu-style LIF adaptation in persistent NumPy runtime",
                        "mode": "REPLAY",
                        "liveBackendReady": False,
                    },
                },
                separators=(",", ":"),
            )
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {len(lines)} replay frames to {args.output}")


if __name__ == "__main__":
    main()
