"""Run the six-state game brain controller on one persistent network."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Mapping

import pandas as pd

from brain_controller import Action, BrainController
from motor_decoder import MotorDecoder, MotorDecoderCalibration
from poc_config import REPO_ROOT, get_dataset


PHASES = (
    (Action.STOP, "STOP_0"),
    (Action.FORWARD, "FORWARD"),
    (Action.STOP, "STOP_1"),
    (Action.TURN_R, "TURN_R"),
    (Action.STOP, "STOP_2"),
    (Action.TURN_L, "TURN_L"),
    (Action.STOP, "STOP_3"),
    (Action.FORWARD_R, "FORWARD_R"),
    (Action.STOP, "STOP_4"),
    (Action.FORWARD_L, "FORWARD_L"),
    (Action.STOP, "STOP_5"),
)


def _phase_steps(phase_ms: int, window_ms: int) -> list[int]:
    full_steps, remainder = divmod(phase_ms, window_ms)
    durations = [window_ms] * full_steps
    if remainder:
        durations.append(remainder)
    if any(duration != window_ms for duration in durations):
        raise ValueError("the controller API currently requires phase_ms divisible by window_ms")
    return durations


def _response_matches(action: Action, motor: Mapping[str, float]) -> bool:
    """Define a measurable first response without changing the raw output."""

    forward = float(motor["forward"])
    turn = float(motor["turn"])
    threshold = 0.1
    if action is Action.STOP:
        return forward <= 0.05 and abs(turn) <= 0.05
    if action is Action.FORWARD:
        return forward >= threshold
    if action is Action.TURN_R:
        return turn >= threshold
    if action is Action.TURN_L:
        return turn <= -threshold
    if action is Action.FORWARD_R:
        return forward >= threshold and turn >= threshold
    if action is Action.FORWARD_L:
        return forward >= threshold and turn <= -threshold
    raise AssertionError(f"unhandled action: {action}")


def _mean(rows: list[dict], key: str) -> float:
    return float(sum(float(row[key]) for row in rows) / len(rows))


def run(args: argparse.Namespace) -> dict:
    dataset = get_dataset(args.dataset)
    output_dir = REPO_ROOT / "results" / "codex_run"
    output_dir.mkdir(parents=True, exist_ok=True)
    frames_path = Path(args.frames_output)
    summary_path = Path(args.summary_output)
    calibration_path = Path(args.calibration_output)
    calibration_source = Path(args.calibration_source)
    if not calibration_source.is_file():
        raise FileNotFoundError(f"calibration source not found: {calibration_source}")

    source_payload = json.loads(calibration_source.read_text(encoding="utf-8"))
    calibration = MotorDecoderCalibration.from_sequence_payload(
        source_payload,
        source_result=str(calibration_source),
    )
    decoder = MotorDecoder(calibration.decoder_config())
    calibration_path.write_text(
        json.dumps(
            {
                "protocolVersion": 1,
                "calibration": calibration.to_dict(),
                "decoderConfig": calibration.decoder_config().to_dict(),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    window_steps = _phase_steps(args.phase_ms, args.window_ms)
    controller = BrainController(
        dataset=args.dataset,
        backend=args.backend,
        seed=args.seed,
        stimulus_frequency_hz=args.stimulus_frequency_hz,
        window_ms=args.window_ms,
    )
    controller.initialize()
    phase_rows: list[dict] = []
    current_phase_rows: list[dict] = []
    all_rows: list[dict] = []
    try:
        with frames_path.open("w", encoding="utf-8") as frames_file:
            for phase_index, (action, phase_name) in enumerate(PHASES):
                controller.set_action(action)
                phase_start_sequence = controller.sequence
                current_phase_rows = []
                for _duration_ms in window_steps:
                    frame = controller.step()
                    motor = decoder.decode(frame.firing_rates())
                    row = frame.to_dict()
                    row.update(
                        {
                            "phaseIndex": phase_index,
                            "phase": phase_name,
                            "motor": {
                                "forward": float(motor["forward"]),
                                "turn": float(motor["turn"]),
                            },
                            "decoder": {
                                "forwardReferenceHz": calibration.forward_reference_hz,
                                "turnReferenceHz": calibration.turn_reference_hz,
                                "turnDeadzoneHz": calibration.turn_deadzone_hz,
                            },
                        }
                    )
                    frames_file.write(json.dumps(row) + "\n")
                    frames_file.flush()
                    current_phase_rows.append(row)
                    all_rows.append(row)

                matching = [
                    index
                    for index, row in enumerate(current_phase_rows)
                    if _response_matches(action, row["motor"])
                ]
                phase_rows.append(
                    {
                        "phaseIndex": phase_index,
                        "phase": phase_name,
                        "requestedAction": action.value,
                        "startSequence": phase_start_sequence,
                        "stepCount": len(current_phase_rows),
                        "meanDNa02_R_Hz": _mean(current_phase_rows, "DNa02_R_Hz"),
                        "meanDNa02_L_Hz": _mean(current_phase_rows, "DNa02_L_Hz"),
                        "meanDNp09_Hz": _mean(current_phase_rows, "DNp09_Hz"),
                        "meanDNa02Difference_Hz": _mean(
                            current_phase_rows, "DNa02Difference_Hz"
                        ),
                        "meanForward": _mean(
                            [row["motor"] for row in current_phase_rows], "forward"
                        ),
                        "meanTurn": _mean(
                            [row["motor"] for row in current_phase_rows], "turn"
                        ),
                        "firstResponseLatencyMs": (
                            float(matching[0] * args.window_ms) if matching else None
                        ),
                    }
                )
    finally:
        controller.close()

    pd.DataFrame(phase_rows).to_csv(summary_path, index=False)
    run_summary = {
        "protocolVersion": 1,
        "dataset": dataset.name,
        "backend": args.backend,
        "seed": args.seed,
        "stimulusFrequencyHz": args.stimulus_frequency_hz,
        "phaseMs": args.phase_ms,
        "windowMs": args.window_ms,
        "phaseDefinition": [
            {"phase": phase_name, "requestedAction": action.value}
            for action, phase_name in PHASES
        ],
        "responseLatencyDefinition": (
            "first window after action change whose decoded output has the expected "
            "axis above 0.1; STOP requires forward <= 0.05 and abs(turn) <= 0.05"
        ),
        "calibration": calibration.to_dict(),
        "network": {
            "networkRebuildCount": controller.network_rebuild_count,
            "stateResetCount": controller.state_reset_count,
            "dtMs": controller.dt_ms,
            "initializationSeconds": controller.initialization_seconds,
        },
        "outputs": {
            "framesJsonl": str(frames_path),
            "summaryCsv": str(summary_path),
            "calibrationJson": str(calibration_path),
        },
        "phases": phase_rows,
        "totalFrames": len(all_rows),
    }
    summary_json_path = output_dir / "game_brain_controller_run.json"
    summary_json_path.write_text(json.dumps(run_summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(run_summary["network"], indent=2))
    print(f"frames written: {frames_path}")
    print(f"summary written: {summary_path}")
    print(f"calibration written: {calibration_path}")
    return run_summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", choices=("v630", "v783"), default="v783")
    parser.add_argument("--backend", choices=("numpy", "cython"), default="cython")
    parser.add_argument("--seed", type=int, default=20260910)
    parser.add_argument("--stimulus-frequency-hz", type=float, default=100.0)
    parser.add_argument("--phase-ms", type=int, default=500)
    parser.add_argument("--window-ms", type=int, choices=(25, 50, 100, 200), default=50)
    parser.add_argument(
        "--calibration-source",
        default=str(REPO_ROOT / "results" / "codex_run" / "brain_controller_sequence_cython_50ms.json"),
    )
    parser.add_argument(
        "--frames-output",
        default=str(REPO_ROOT / "results" / "codex_run" / "game_brain_controller_frames.jsonl"),
    )
    parser.add_argument(
        "--summary-output",
        default=str(REPO_ROOT / "results" / "codex_run" / "game_brain_controller_summary.csv"),
    )
    parser.add_argument(
        "--calibration-output",
        default=str(REPO_ROOT / "results" / "codex_run" / "motor_decoder_calibration.json"),
    )
    return parser.parse_args()


if __name__ == "__main__":
    run(parse_args())
