"""Run a bounded three-seed upstream-to-readout PoC with an edge-block control."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import resource

from malecns_brain import MaleCNSBrain


STIMULUS_ID = 13137
READOUT_ID = 10360
DIRECT_EDGE_SYNAPSE_COUNT = 717


def run_condition(graph: Path, seed: int, condition: str, duration_ms: float, rate_hz: float) -> dict:
    brain = MaleCNSBrain(graph, seed=seed).initialize()
    brain.set_readouts({"DNa02_R_candidate": READOUT_ID})
    if condition != "baseline":
        brain.set_stimulation([STIMULUS_ID], rate_hz)
    if condition == "direct_edge_blocked":
        brain.set_blocked_edges([(STIMULUS_ID, READOUT_ID)])
    result = brain.step(duration_ms)
    count = result["readoutSpikeCounts"]["DNa02_R_candidate"]
    result.update(
        {
            "seed": seed,
            "condition": condition,
            "stimulusBodyIds": [] if condition == "baseline" else [str(STIMULUS_ID)],
            "readoutBodyIds": [str(READOUT_ID)],
            "stimulusReadoutOverlap": False,
            "stimulusRateHz": 0.0 if condition == "baseline" else rate_hz,
            "readoutRateHz": count / (duration_ms / 1000.0),
            "directEdgeBlocked": condition == "direct_edge_blocked",
        }
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--graph", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--duration-ms", type=float, default=50.0)
    parser.add_argument("--rate-hz", type=float, default=100.0)
    args = parser.parse_args()
    trials = [
        run_condition(args.graph, seed, condition, args.duration_ms, args.rate_hz)
        for seed in (20260911, 20260912, 20260913)
        for condition in ("baseline", "stimulated", "direct_edge_blocked")
    ]
    payload = {
        "capturedAtUtc": datetime.now(timezone.utc).isoformat(),
        "datasetId": "male-cns:v1.0",
        "dynamicsModel": "Shiu-style LIF adaptation in persistent NumPy runtime",
        "physiologicallyValidated": False,
        "stimulus": {
            "bodyId": str(STIMULUS_ID),
            "type": "AN03A008",
            "instance": "AN03A008_R",
            "superclass": "ascending_neuron",
        },
        "readout": {
            "bodyId": str(READOUT_ID),
            "type": "DNa02",
            "instance": "DNa02_R",
            "superclass": "descending_neuron",
        },
        "directEdgeSynapseCount": DIRECT_EDGE_SYNAPSE_COUNT,
        "trials": trials,
        "peakProcessRssBytes": int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(trials)} trials to {args.output}")


if __name__ == "__main__":
    main()
