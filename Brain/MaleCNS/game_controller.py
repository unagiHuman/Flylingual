"""Game-facing persistent controller over the exploratory MaleCNS LIF runtime."""

from __future__ import annotations

from enum import Enum
import json
from pathlib import Path

from malecns_brain import LifConfig, MaleCNSBrain


class Action(str, Enum):
    STOP = "STOP"
    FORWARD = "FORWARD"
    TURN_R = "TURN_R"
    TURN_L = "TURN_L"
    FORWARD_R = "FORWARD_R"
    FORWARD_L = "FORWARD_L"


ACTION_GROUPS = {
    Action.STOP: (),
    Action.FORWARD: ("F",),
    Action.TURN_R: ("R",),
    Action.TURN_L: ("L",),
    Action.FORWARD_R: ("F", "R"),
    Action.FORWARD_L: ("F", "L"),
}


class MaleCNSGameController:
    def __init__(self, graph_path: Path, mapping_path: Path, seed: int = 20260911, window_ms: float = 50.0, recurrent_weight_scale: float = 1.0):
        self.graph_path = Path(graph_path)
        self.mapping_path = Path(mapping_path)
        self.seed = int(seed)
        self.window_ms = float(window_ms)
        self.mapping = json.loads(self.mapping_path.read_text(encoding="utf-8"))
        self.recurrent_weight_scale = float(recurrent_weight_scale)
        self.brain = MaleCNSBrain(
            self.graph_path,
            config=LifConfig(recurrent_weight_scale=self.recurrent_weight_scale),
            seed=self.seed,
        )
        self.action = Action.STOP
        self.sequence = 0
        self.network_rebuild_count = 0
        self.state_reset_count = 0

    def initialize(self) -> "MaleCNSGameController":
        self.brain.initialize()
        self.brain.set_readouts(
            {name: int(body_id) for name, body_id in self.mapping["readouts"].items()}
        )
        self.network_rebuild_count = 1
        self.set_action(Action.STOP)
        return self

    def set_action(self, action: Action | str) -> None:
        self.action = action if isinstance(action, Action) else Action(action)
        groups = ACTION_GROUPS[self.action]
        body_ids = [int(body_id) for group in groups for body_id in self.mapping["groups"][group]]
        self.brain.set_stimulation(body_ids, float(self.mapping["stimulusRateHz"]))

    def step(self) -> dict:
        result = self.brain.step(self.window_ms)
        counts = result["readoutSpikeCounts"]
        scale = 1000.0 / self.window_ms
        rates = {name: count * scale for name, count in counts.items()}
        dnp09_hz = 0.5 * (rates["DNp09_L"] + rates["DNp09_R"])
        frame = {
            "sequence": self.sequence,
            "brainSimulationTimeMs": result["totalSimulatedMs"],
            "windowMs": self.window_ms,
            "requestedAction": self.action.value,
            "activeStimulusGroups": list(ACTION_GROUPS[self.action]),
            "activeStimulusIds": [
                body_id
                for group in ACTION_GROUPS[self.action]
                for body_id in self.mapping["groups"][group]
            ],
            "brain": {
                "DNp09_Hz": dnp09_hz,
                "DNp09_L_Hz": rates["DNp09_L"],
                "DNp09_R_Hz": rates["DNp09_R"],
                "DNa02_R_Hz": rates["DNa02_R"],
                "DNa02_L_Hz": rates["DNa02_L"],
                "DNa02Difference_Hz": rates["DNa02_R"] - rates["DNa02_L"],
            },
            "wholeBrainSpikeCount": result["wholeNetworkSpikeCount"],
            "performance": {"windowMs": self.window_ms, "stepWallTimeMs": result["wallMs"]},
            "metadata": {
                "backendId": "malecns_lif_poc",
                "datasetId": "male-cns:v1.0",
                "dynamicsModel": "Shiu-style LIF adaptation in persistent NumPy runtime",
                "recurrentWeightScale": self.recurrent_weight_scale,
                "mode": "MALECNS",
                "ready": False,
            },
        }
        self.sequence += 1
        return frame
