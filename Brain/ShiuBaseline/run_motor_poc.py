"""Run the v783 descending-neuron-to-motor-output PoC.

Example:
    python run_motor_poc.py --dataset v783 --n-run 3 --frequencies 100 200
"""

import argparse
import json
import logging
from pathlib import Path
from typing import Dict, Iterable, Mapping

import pandas as pd

from brain_adapter import (
    FiringRateResult,
    extract_firing_rates,
    run_brain_experiment,
)
from motor_decoder import MotorDecoder, MotorDecoderConfig
from poc_config import (
    DESCENDING_NEURON_IDS,
    REPO_ROOT,
    SUGAR_SENSORY_NEURON_IDS,
    get_dataset,
)


LOGGER = logging.getLogger("motor_poc")


def _read_dataset_ids(dataset) -> set[int]:
    completeness = pd.read_csv(dataset.completeness_path, index_col=0)
    return {int(value) for value in completeness.index}


def inspect_descending_neurons(dataset) -> list[dict]:
    """Validate target IDs and count input/output connectivity."""

    completeness_ids = _read_dataset_ids(dataset)
    connectivity_columns = [
        "Presynaptic_ID",
        "Postsynaptic_ID",
        "Connectivity",
        "Excitatory x Connectivity",
    ]
    connectivity = pd.read_parquet(dataset.connectivity_path, columns=connectivity_columns)
    has_root_ids = {"Presynaptic_ID", "Postsynaptic_ID"}.issubset(connectivity.columns)
    rows = []

    for name, root_id in DESCENDING_NEURON_IDS.items():
        incoming = connectivity[connectivity["Postsynaptic_ID"] == root_id] if has_root_ids else None
        outgoing = connectivity[connectivity["Presynaptic_ID"] == root_id] if has_root_ids else None
        rows.append(
            {
                "name": name,
                "root_id": root_id,
                "completeness": root_id in completeness_ids,
                "connectivity": bool(has_root_ids and (not incoming.empty or not outgoing.empty)),
                "input_edge_count": int(len(incoming)) if incoming is not None else None,
                "output_edge_count": int(len(outgoing)) if outgoing is not None else None,
                "input_connectivity_sum": int(incoming["Connectivity"].sum()) if incoming is not None else None,
                "output_connectivity_sum": int(outgoing["Connectivity"].sum()) if outgoing is not None else None,
                "neurotransmitter": None,
            }
        )
    return rows


def _available_sugar_ids(dataset) -> tuple[list[int], list[int]]:
    completeness_ids = _read_dataset_ids(dataset)
    available = [root_id for root_id in SUGAR_SENSORY_NEURON_IDS if root_id in completeness_ids]
    missing = [root_id for root_id in SUGAR_SENSORY_NEURON_IDS if root_id not in completeness_ids]
    return available, missing


def _write_motor_output(frequency_hz: int, decoded: Mapping, output_dir: Path) -> Path:
    output_path = output_dir / f"motor_output_{frequency_hz}Hz.json"
    payload = {
        "protocolVersion": 1,
        "stimulus": {"type": "sugar", "frequencyHz": frequency_hz},
        "motor": {
            "forward": float(decoded["forward"]),
            "turn": float(decoded["turn"]),
        },
        "raw": {name: float(value) for name, value in decoded["raw"].items()},
    }
    output_path.write_text(json.dumps(payload, indent=2) + "\n")
    return output_path


def _write_activity_table(
    results: Mapping[int, FiringRateResult], output_dir: Path, dataset_name: str
) -> Path:
    frequencies = sorted(results)
    rows = []
    for name, root_id in DESCENDING_NEURON_IDS.items():
        row = {"neuron": name, "root_id": root_id}
        for frequency in frequencies:
            activity = results[frequency]
            row[f"total_spikes_{frequency}Hz"] = activity.total_spikes[name]
            row[f"mean_rate_{frequency}Hz"] = activity.mean_rate_hz[name]
            row[f"std_rate_{frequency}Hz"] = activity.std_rate_hz[name]
            row[f"per_trial_rate_{frequency}Hz"] = json.dumps(activity.per_trial_rate_hz[name])
        if 100 in results and 200 in results:
            row["delta_200Hz_minus_100Hz"] = (
                results[200].mean_rate_hz[name] - results[100].mean_rate_hz[name]
            )
        rows.append(row)
    output_path = output_dir / f"descending_activity_{dataset_name}.csv"
    pd.DataFrame(rows).to_csv(output_path, index=False)
    return output_path


def run(args: argparse.Namespace) -> None:
    dataset = get_dataset(args.dataset)
    output_dir = REPO_ROOT / "results" / "codex_run"
    output_dir.mkdir(parents=True, exist_ok=True)

    validation = inspect_descending_neurons(dataset)
    LOGGER.info("descending validation: %s", json.dumps(validation, sort_keys=True))
    validation_path = output_dir / f"dataset_validation_{dataset.name}.json"
    validation_path.write_text(json.dumps(validation, indent=2) + "\n")
    LOGGER.info("dataset validation written: %s", validation_path)
    missing_targets = [row["name"] for row in validation if not row["completeness"]]
    if missing_targets:
        raise RuntimeError(f"Descending neuron IDs missing from {dataset.name}: {missing_targets}")

    sugar_ids, missing_sugar_ids = _available_sugar_ids(dataset)
    if missing_sugar_ids:
        LOGGER.warning(
            "Skipping %d Sugar ID(s) absent from %s without substitution: %s",
            len(missing_sugar_ids),
            dataset.name,
            missing_sugar_ids,
        )
    if not sugar_ids:
        raise RuntimeError(f"No Sugar sensory IDs are available in {dataset.name}")

    activities: Dict[int, FiringRateResult] = {}
    for frequency_hz in args.frequencies:
        experiment_name = f"sugar_{dataset.name}_{frequency_hz}Hz"
        result = run_brain_experiment(
            stimulated_neuron_ids=sugar_ids,
            stimulus_frequency_hz=frequency_hz,
            dataset=dataset,
            experiment_name=experiment_name,
            n_run=args.n_run,
            n_proc=args.n_proc,
            force_overwrite=args.force_overwrite,
        )
        activity = extract_firing_rates(result, DESCENDING_NEURON_IDS)
        activities[frequency_hz] = activity
        decoder = MotorDecoder(
            MotorDecoderConfig(
                forward_scale_hz=args.forward_scale_hz,
                turn_scale_hz=args.turn_scale_hz,
            )
        )
        decoded = decoder.decode(activity.mean_rate_hz)
        output_path = _write_motor_output(frequency_hz, decoded, output_dir)
        LOGGER.info("motor output written: %s", output_path)
        LOGGER.info("motor output %sHz: %s", frequency_hz, json.dumps(decoded, sort_keys=True))

    table_path = _write_activity_table(activities, output_dir, dataset.name)
    LOGGER.info("descending activity table written: %s", table_path)
    print(pd.read_csv(table_path).to_string(index=False))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", choices=("v630", "v783"), default="v783")
    parser.add_argument("--n-run", type=int, default=3)
    parser.add_argument("--n-proc", type=int, default=-1)
    parser.add_argument("--frequencies", type=int, nargs="+", default=[100, 200])
    parser.add_argument("--forward-scale-hz", type=float, default=40.0)
    parser.add_argument("--turn-scale-hz", type=float, default=40.0)
    parser.add_argument("--force-overwrite", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    run(parse_args())
