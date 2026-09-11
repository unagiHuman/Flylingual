"""Data-calibrated decoder from descending-neuron activity to motor output."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Mapping
import json

import numpy as np


@dataclass(frozen=True)
class MotorDecoderConfig:
    """Visible normalization and dead-zone parameters.

    ``forward_scale_hz`` and ``turn_scale_hz`` are retained as compatibility
    aliases for the earlier standalone sugar PoC. New controller code uses
    the explicitly named reference fields.
    """

    forward_reference_hz: float | None = None
    turn_reference_hz: float | None = None
    turn_deadzone_hz: float = 0.0
    forward_scale_hz: float | None = None
    turn_scale_hz: float | None = None

    def __post_init__(self) -> None:
        forward = self.forward_reference_hz
        turn = self.turn_reference_hz
        if forward is None:
            forward = self.forward_scale_hz if self.forward_scale_hz is not None else 40.0
            object.__setattr__(self, "forward_reference_hz", float(forward))
        if turn is None:
            turn = self.turn_scale_hz if self.turn_scale_hz is not None else 40.0
            object.__setattr__(self, "turn_reference_hz", float(turn))
        if self.forward_scale_hz is None:
            object.__setattr__(self, "forward_scale_hz", float(forward))
        if self.turn_scale_hz is None:
            object.__setattr__(self, "turn_scale_hz", float(turn))
        if float(forward) <= 0 or float(turn) <= 0:
            raise ValueError("decoder references must be positive")
        if self.turn_deadzone_hz < 0:
            raise ValueError("turn_deadzone_hz must not be negative")
        if self.turn_deadzone_hz >= float(turn):
            raise ValueError("turn_deadzone_hz must be below turn_reference_hz")

    def to_dict(self) -> dict:
        """Return protocol-friendly calibration names."""

        return {
            "forwardReferenceHz": float(self.forward_reference_hz),
            "turnReferenceHz": float(self.turn_reference_hz),
            "turnDeadzoneHz": float(self.turn_deadzone_hz),
        }


@dataclass(frozen=True)
class MotorDecoderCalibration:
    """Calibration derived from an observed persistent-controller sequence."""

    source_result: str
    source_step_ms: float
    forward_reference_hz: float
    turn_reference_hz: float
    turn_deadzone_hz: float
    percentile: float
    safety_margin_hz: float
    forward_sample_count: int
    turn_sample_count: int
    forward_deadzone_sample_count: int
    forward_reference_method: str
    turn_reference_method: str
    deadzone_method: str

    @classmethod
    def from_sequence_payload(
        cls,
        payload: Mapping,
        source_result: str,
        percentile: float = 95.0,
    ) -> "MotorDecoderCalibration":
        """Derive references from the sequence's raw per-window measurements."""

        steps = payload.get("steps", [])
        if not steps:
            raise ValueError("calibration source contains no step records")

        step_ms = float(payload.get("requested_step_ms", 0.0))
        if step_ms <= 0:
            raise ValueError("calibration source has no positive requested_step_ms")

        forward_actions = {"F", "F+R", "F+L"}
        steering_actions = {"R", "L", "F+R", "F+L"}
        straight_steps = [step for step in steps if step.get("phase") == "F"]
        forward_steps = [step for step in steps if step.get("phase") in forward_actions]
        steering_steps = [step for step in steps if step.get("phase") in steering_actions]
        if not forward_steps or not steering_steps or not straight_steps:
            raise ValueError("calibration source lacks F, steering, or combined samples")

        def rate(step: Mapping, key: str) -> float:
            return float(step[key]["firing_rate_hz"])

        forward_values = np.asarray([rate(step, "DNp09") for step in forward_steps], dtype=float)
        turn_values = np.asarray(
            [rate(step, "DNa02_R") - rate(step, "DNa02_L") for step in steering_steps],
            dtype=float,
        )
        straight_abs_delta = np.asarray(
            [abs(rate(step, "DNa02_R") - rate(step, "DNa02_L")) for step in straight_steps],
            dtype=float,
        )

        forward_reference = float(np.percentile(forward_values, percentile))
        turn_reference = float(np.percentile(np.abs(turn_values), percentile))
        # One spike in a 50 ms window is 20 Hz. A quarter of that resolution
        # is used as a small, explicit safety margin for the straight state.
        safety_margin = 0.25 * (1000.0 / step_ms)
        deadzone = float(np.percentile(straight_abs_delta, percentile) + safety_margin)
        if deadzone >= turn_reference:
            raise ValueError(
                f"calibrated dead zone {deadzone} is not below turn reference {turn_reference}"
            )

        return cls(
            source_result=str(source_result),
            source_step_ms=step_ms,
            forward_reference_hz=forward_reference,
            turn_reference_hz=turn_reference,
            turn_deadzone_hz=deadzone,
            percentile=float(percentile),
            safety_margin_hz=safety_margin,
            forward_sample_count=int(len(forward_values)),
            turn_sample_count=int(len(turn_values)),
            forward_deadzone_sample_count=int(len(straight_abs_delta)),
            forward_reference_method=(
                "95th percentile of DNp09 firing rates in F, F+R, and F+L windows"
            ),
            turn_reference_method=(
                "95th percentile of abs(DNa02_R - DNa02_L) in R, L, F+R, and F+L windows"
            ),
            deadzone_method=(
                "95th percentile of abs(DNa02_R - DNa02_L) in F windows "
                "+ one-quarter of one-spike rate resolution"
            ),
        )

    @classmethod
    def from_json(cls, path: str | Path) -> "MotorDecoderCalibration":
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        fields = payload["calibration"] if "calibration" in payload else payload
        return cls(
            **{
                field.name: fields[field.name]
                for field in cls.__dataclass_fields__.values()
                if field.name in fields
            }
        )

    def to_dict(self) -> dict:
        data = asdict(self)
        data.update(
            {
                "forwardReferenceHz": float(self.forward_reference_hz),
                "turnReferenceHz": float(self.turn_reference_hz),
                "turnDeadzoneHz": float(self.turn_deadzone_hz),
            }
        )
        return data

    def decoder_config(self) -> MotorDecoderConfig:
        return MotorDecoderConfig(
            forward_reference_hz=self.forward_reference_hz,
            turn_reference_hz=self.turn_reference_hz,
            turn_deadzone_hz=self.turn_deadzone_hz,
        )


class MotorDecoder:
    """Decode DNp09 forward drive and DNa02 left/right asymmetry."""

    def __init__(self, config: MotorDecoderConfig | None = None) -> None:
        self.config = config or MotorDecoderConfig()

    @staticmethod
    def _clip(value: float, lower: float, upper: float) -> float:
        return max(lower, min(upper, float(value)))

    def decode(self, firing_rates: Mapping[str, float]) -> dict:
        raw = {
            "DNp09": float(firing_rates.get("DNp09", 0.0)),
            "DNa02_R": float(firing_rates.get("DNa02_R", 0.0)),
            "DNa02_L": float(firing_rates.get("DNa02_L", 0.0)),
            "DNa01_R": float(firing_rates.get("DNa01_R", 0.0)),
            "DNa01_L": float(firing_rates.get("DNa01_L", 0.0)),
        }
        forward = self._clip(
            raw["DNp09"] / float(self.config.forward_reference_hz), 0.0, 1.0
        )
        turn_delta_hz = raw["DNa02_R"] - raw["DNa02_L"]
        if abs(turn_delta_hz) <= self.config.turn_deadzone_hz:
            turn = 0.0
        else:
            sign = 1.0 if turn_delta_hz > 0 else -1.0
            usable_delta = abs(turn_delta_hz) - self.config.turn_deadzone_hz
            usable_reference = float(self.config.turn_reference_hz) - self.config.turn_deadzone_hz
            turn = self._clip(sign * usable_delta / usable_reference, -1.0, 1.0)
        return {
            "forward": forward,
            "turn": turn,
            "raw": raw,
            "DNa02Difference_Hz": turn_delta_hz,
        }
