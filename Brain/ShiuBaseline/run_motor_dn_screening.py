"""Find and screen upstream candidates for motor-related descending neurons.

The workflow is deliberately coarse-to-fine:

1. Aggregate direct presynaptic connectivity into a ranked CSV.
2. Select a small top-five group for each target.
3. Run one-trial 100 Hz whole-brain simulations, including no-stimulation
   baseline, and write target rates plus whole-brain spike counts.

The target DNs themselves are excluded from every stimulus group.
"""

import argparse
import json
from pathlib import Path

import pandas as pd

from brain_adapter import extract_firing_rates, run_brain_experiment
from poc_config import DESCENDING_NEURON_IDS, REPO_ROOT, get_dataset


SCREEN_TARGETS = {
    name: DESCENDING_NEURON_IDS[name]
    for name in ("DNa02_R", "DNa02_L", "DNp09")
}


def _completeness_ids(dataset) -> set[int]:
    completeness = pd.read_csv(dataset.completeness_path, index_col=0)
    return {int(value) for value in completeness.index}


def build_candidate_table(dataset) -> pd.DataFrame:
    """Aggregate direct presynaptic edges for the three screen targets."""

    target_ids = set(SCREEN_TARGETS.values())
    columns = [
        "Presynaptic_ID",
        "Postsynaptic_ID",
        "Connectivity",
        "Excitatory x Connectivity",
    ]
    connectivity = pd.read_parquet(dataset.connectivity_path, columns=columns)
    connectivity = connectivity[connectivity["Postsynaptic_ID"].isin(target_ids)]
    completeness_ids = _completeness_ids(dataset)

    rows = []
    target_by_id = {root_id: name for name, root_id in SCREEN_TARGETS.items()}
    for (presynaptic_id, postsynaptic_id), edges in connectivity.groupby(
        ["Presynaptic_ID", "Postsynaptic_ID"], sort=False
    ):
        if int(presynaptic_id) in target_ids:
            continue
        rows.append(
            {
                "target_name": target_by_id[int(postsynaptic_id)],
                "target_root_id": int(postsynaptic_id),
                "presynaptic_root_id": int(presynaptic_id),
                "edge_count": int(len(edges)),
                "synapse_count": int(edges["Connectivity"].sum()),
                "effective_weight": float(edges["Excitatory x Connectivity"].sum()),
                "presynaptic_in_completeness": int(presynaptic_id) in completeness_ids,
                "presynaptic_name": None,
            }
        )

    table = pd.DataFrame(rows)
    return table.sort_values(
        ["target_name", "effective_weight", "synapse_count", "edge_count"],
        ascending=[True, False, False, False],
    ).reset_index(drop=True)


def select_candidate_groups(table: pd.DataFrame, group_size: int) -> dict[str, list[int]]:
    """Select small positive-weight groups, falling back to synapse rank."""

    groups = {}
    for target_name in SCREEN_TARGETS:
        target_rows = table[table["target_name"] == target_name]
        positive = target_rows[target_rows["effective_weight"] > 0]
        ranked = positive if len(positive) >= group_size else target_rows
        selected = ranked.head(group_size)
        if len(selected) < group_size:
            raise RuntimeError(f"Not enough candidates for {target_name}")
        groups[f"top{group_size}_{target_name}"] = [
            int(value) for value in selected["presynaptic_root_id"]
        ]
    return groups


def build_path_table(table: pd.DataFrame, groups: dict[str, list[int]]) -> pd.DataFrame:
    """Document the direct one-hop path used by every screened candidate."""

    rows = []
    for group_name, candidate_ids in groups.items():
        target_name = group_name.split("_", 1)[1]
        selected = table[
            (table["target_name"] == target_name)
            & table["presynaptic_root_id"].isin(candidate_ids)
        ]
        for _, row in selected.iterrows():
            rows.append(
                {
                    "stimulus_group": group_name,
                    "target_name": target_name,
                    "target_root_id": int(row["target_root_id"]),
                    "presynaptic_root_id": int(row["presynaptic_root_id"]),
                    "hop_count": 1,
                    "direct_connection": True,
                    "edge_count": int(row["edge_count"]),
                    "synapse_count": int(row["synapse_count"]),
                    "effective_weight": float(row["effective_weight"]),
                }
            )
    return pd.DataFrame(rows).sort_values(
        ["stimulus_group", "effective_weight"], ascending=[True, False]
    )


def _target_activity(result):
    activity = extract_firing_rates(result, SCREEN_TARGETS)
    whole_brain_spikes = int(pd.read_parquet(result.parquet_path, columns=["t"]).shape[0])
    return activity, whole_brain_spikes


def run(args: argparse.Namespace) -> None:
    dataset = get_dataset(args.dataset)
    output_dir = REPO_ROOT / "results" / "codex_run"
    output_dir.mkdir(parents=True, exist_ok=True)

    candidates = build_candidate_table(dataset)
    candidates_path = output_dir / "motor_dn_presynaptic_candidates.csv"
    candidates.to_csv(candidates_path, index=False)

    groups = select_candidate_groups(candidates, args.group_size)
    groups_path = output_dir / "motor_dn_candidate_groups.json"
    groups_path.write_text(json.dumps(groups, indent=2) + "\n")
    paths_path = output_dir / "motor_dn_connectivity_paths.csv"
    build_path_table(candidates, groups).to_csv(paths_path, index=False)

    baseline_result = run_brain_experiment(
        stimulated_neuron_ids=[],
        stimulus_frequency_hz=args.frequency_hz,
        dataset=dataset,
        experiment_name=f"motor_dn_baseline_{dataset.name}_{args.frequency_hz}Hz",
        n_run=args.n_run,
        n_proc=args.n_proc,
        force_overwrite=args.force_overwrite,
        allow_zero_spikes=True,
    )
    baseline_activity, baseline_whole_brain_spikes = _target_activity(baseline_result)

    rows = []
    for group_name, input_ids in groups.items():
        result = run_brain_experiment(
            stimulated_neuron_ids=input_ids,
            stimulus_frequency_hz=args.frequency_hz,
            dataset=dataset,
            experiment_name=f"motor_dn_{dataset.name}_{group_name}_{args.frequency_hz}Hz",
            n_run=args.n_run,
            n_proc=args.n_proc,
            force_overwrite=args.force_overwrite,
        )
        activity, whole_brain_spikes = _target_activity(result)
        for target_name in SCREEN_TARGETS:
            rows.append(
                {
                    "stimulus_group": group_name,
                    "stimulus_ids": json.dumps(input_ids),
                    "target": target_name,
                    "target_rate_hz": activity.mean_rate_hz[target_name],
                    "target_std_hz": activity.std_rate_hz[target_name],
                    "baseline_rate_hz": baseline_activity.mean_rate_hz[target_name],
                    "delta_rate_hz": (
                        activity.mean_rate_hz[target_name]
                        - baseline_activity.mean_rate_hz[target_name]
                    ),
                    "whole_brain_spikes": whole_brain_spikes,
                    "baseline_whole_brain_spikes": baseline_whole_brain_spikes,
                }
            )

    screening = pd.DataFrame(rows)
    screening_path = output_dir / "motor_dn_screening.csv"
    screening.to_csv(screening_path, index=False)

    print(f"candidates: {candidates_path}")
    print(f"groups: {groups_path}")
    print(f"paths: {paths_path}")
    print(f"screening: {screening_path}")
    print(screening.to_string(index=False))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", choices=("v630", "v783"), default="v783")
    parser.add_argument("--frequency-hz", type=int, default=100)
    parser.add_argument("--n-run", type=int, default=1)
    parser.add_argument("--n-proc", type=int, default=-1)
    parser.add_argument("--group-size", type=int, choices=(5, 10), default=5)
    parser.add_argument("--force-overwrite", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    run(parse_args())
