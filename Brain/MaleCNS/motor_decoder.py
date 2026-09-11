"""Action-independent decoder for calibrated MaleCNS candidate readouts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping


class MotorDecoder:
    def __init__(self, calibration_path: Path):
        payload = json.loads(Path(calibration_path).read_text(encoding="utf-8"))
        config = payload["decoderConfig"]
        self.forward_reference_hz = float(config["forwardReferenceHz"])
        self.turn_reference_hz = float(config["turnReferenceHz"])
        self.turn_deadzone_hz = float(config["turnDeadzoneHz"])
        if self.forward_reference_hz <= 0 or self.turn_reference_hz <= self.turn_deadzone_hz:
            raise ValueError("invalid motor calibration")

    @staticmethod
    def clip(value: float, low: float, high: float) -> float:
        return max(low, min(high, float(value)))

    def decode(self, raw: Mapping[str, float]) -> dict[str, float]:
        forward_hz = float(raw["DNp09_Hz"])
        turn_delta_hz = float(raw["DNa02_R_Hz"]) - float(raw["DNa02_L_Hz"])
        forward = self.clip(forward_hz / self.forward_reference_hz, 0.0, 1.0)
        if abs(turn_delta_hz) <= self.turn_deadzone_hz:
            turn = 0.0
        else:
            direction = 1.0 if turn_delta_hz > 0 else -1.0
            turn = self.clip(
                direction * (abs(turn_delta_hz) - self.turn_deadzone_hz)
                / (self.turn_reference_hz - self.turn_deadzone_hz),
                -1.0,
                1.0,
            )
        return {"forward": forward, "turn": turn}
