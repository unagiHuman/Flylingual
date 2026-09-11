"""Prove that changing sensory input changes downstream brain activity.

This is independent of Unity and the motor decoder. It runs the upstream
Brian2 model twice with the same frequency and trial count: once with all
available Sugar IDs and once with a smaller Sugar subset.
"""

import argparse
import json
from pathlib import Path

import pandas as pd

from brain_adapter import run_brain_experiment
from poc_config import REPO_ROOT, SUGAR_SENSORY_NEURON_IDS, get_dataset


def _available_sugar_ids(dataset) -> list[int]:
    completeness = pd.read_csv(dataset.completeness_path, index_col=0)
    available_ids = {int(value) for value in completeness.index}
    return [root_id for root_id in SUGAR_SENSORY_NEURON_IDS if root_id in available_ids]


def _mean_rates(parquet_path: Path) -> tuple[pd.Series, dict]:
    spikes = pd.read_parquet(parquet_path)
    counts = spikes.groupby(["flywire_id", "trial"]).size().unstack(fill_value=0)
    rates = counts.mean(axis=1)
    summary = {
        "parquet": str(parquet_path.resolve()),
        "rows": int(len(spikes)),
        "trials": int(spikes["trial"].nunique()),
        "neurons": int(spikes["flywire_id"].nunique()),
        "total_spikes": int(len(spikes)),
        "trial_spikes": [
            int((spikes["trial"] == trial).sum())
            for trial in sorted(spikes["trial"].unique())
        ],
    }
    return rates, summary


def run(args: argparse.Namespace) -> Path:
    dataset = get_dataset(args.dataset)
    output_dir = REPO_ROOT / "results" / "codex_run"
    output_dir.mkdir(parents=True, exist_ok=True)

    sugar_ids = _available_sugar_ids(dataset)
    if len(sugar_ids) < 2:
        raise RuntimeError("At least two Sugar IDs are required for the input comparison")
    split_at = min(max(args.split_at, 1), len(sugar_ids) - 1)
    conditions = {
        "all_sugar": sugar_ids,
        "partial_sugar": sugar_ids[:split_at],
    }

    rates = {}
    condition_summaries = {}
    for name, input_ids in conditions.items():
        result = run_brain_experiment(
            stimulated_neuron_ids=input_ids,
            stimulus_frequency_hz=args.frequency_hz,
            dataset=dataset,
            experiment_name=(
                f"sugar_{dataset.name}_{args.frequency_hz}Hz"
                if name == "all_sugar"
                else f"sugar_{dataset.name}_half_{args.frequency_hz}Hz"
            ),
            n_run=args.n_run,
            n_proc=args.n_proc,
            force_overwrite=args.force_overwrite,
        )
        rates[name], condition_summaries[name] = _mean_rates(result.parquet_path)
        condition_summaries[name]["stimulated_neuron_count"] = len(input_ids)
        condition_summaries[name]["stimulated_neuron_ids"] = input_ids

    common_ids = rates["all_sugar"].index.intersection(rates["partial_sugar"].index)
    comparison = pd.DataFrame(
        {
            "all_sugar_rate_hz": rates["all_sugar"].reindex(common_ids),
            "partial_sugar_rate_hz": rates["partial_sugar"].reindex(common_ids),
        }
    )
    comparison["delta_partial_minus_all_hz"] = (
        comparison["partial_sugar_rate_hz"] - comparison["all_sugar_rate_hz"]
    )
    changed = comparison[comparison["delta_partial_minus_all_hz"].abs() > 1e-12]
    ranked = changed.reindex(
        changed["delta_partial_minus_all_hz"].abs().sort_values(ascending=False).index
    )

    evidence = {
        "protocolVersion": 1,
        "dataset": dataset.name,
        "stimulusFrequencyHz": args.frequency_hz,
        "nRun": args.n_run,
        "conditions": condition_summaries,
        "comparison": {
            "common_neurons": int(len(common_ids)),
            "changed_neurons": int(len(changed)),
            "mean_abs_delta_hz": float(comparison["delta_partial_minus_all_hz"].abs().mean()),
            "max_abs_delta_hz": float(comparison["delta_partial_minus_all_hz"].abs().max()),
            "top_changed": [
                {
                    "flywire_id": int(neuron_id),
                    "all_sugar_rate_hz": float(row["all_sugar_rate_hz"]),
                    "partial_sugar_rate_hz": float(row["partial_sugar_rate_hz"]),
                    "delta_partial_minus_all_hz": float(row["delta_partial_minus_all_hz"]),
                }
                for neuron_id, row in ranked.head(args.top).iterrows()
            ],
        },
    }
    output_path = (
        Path(args.output)
        if args.output
        else output_dir / "mac_brain_input_change_evidence.json"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(evidence, indent=2) + "\n")
    print(json.dumps(evidence, indent=2))
    print(f"evidence written: {output_path}")
    return output_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", choices=("v630", "v783"), default="v783")
    parser.add_argument("--n-run", type=int, default=10)
    parser.add_argument("--n-proc", type=int, default=-1)
    parser.add_argument("--frequency-hz", type=int, default=100)
    parser.add_argument("--split-at", type=int, default=10)
    parser.add_argument("--top", type=int, default=10)
    parser.add_argument("--output")
    parser.add_argument("--force-overwrite", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    run(parse_args())
