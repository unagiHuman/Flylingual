"""Re-run promising motor-DN input groups with multiple trials."""

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


def _activity_and_spikes(result):
    activity = extract_firing_rates(result, SCREEN_TARGETS)
    spikes = pd.read_parquet(result.parquet_path)
    whole_brain_by_trial = (
        spikes.groupby("trial").size().reindex(range(result.n_run), fill_value=0)
    )
    return activity, [int(value) for value in whole_brain_by_trial.tolist()]


def run(args: argparse.Namespace) -> None:
    dataset = get_dataset(args.dataset)
    output_dir = REPO_ROOT / "results" / "codex_run"
    groups_path = output_dir / "motor_dn_candidate_groups.json"
    groups = json.loads(groups_path.read_text())
    target_ids = set(SCREEN_TARGETS.values())
    for name, input_ids in groups.items():
        if target_ids.intersection(input_ids):
            raise RuntimeError(f"Candidate group {name} directly stimulates a target DN")

    baseline_result = run_brain_experiment(
        stimulated_neuron_ids=[],
        stimulus_frequency_hz=args.frequency_hz,
        dataset=dataset,
        experiment_name=f"motor_dn_baseline_{dataset.name}_{args.frequency_hz}Hz_n{args.n_run}",
        n_run=args.n_run,
        n_proc=args.n_proc,
        force_overwrite=args.force_overwrite,
        allow_zero_spikes=True,
    )
    baseline_activity, baseline_whole_brain = _activity_and_spikes(baseline_result)

    trial_rows = []
    summary_rows = []
    lateral_rows = []
    for group_name, input_ids in groups.items():
        result = run_brain_experiment(
            stimulated_neuron_ids=input_ids,
            stimulus_frequency_hz=args.frequency_hz,
            dataset=dataset,
            experiment_name=f"motor_dn_{dataset.name}_{group_name}_{args.frequency_hz}Hz_n{args.n_run}",
            n_run=args.n_run,
            n_proc=args.n_proc,
            force_overwrite=args.force_overwrite,
        )
        activity, whole_brain = _activity_and_spikes(result)
        for trial in range(args.n_run):
            for target in SCREEN_TARGETS:
                rate = activity.per_trial_rate_hz[target][trial]
                baseline_rate = baseline_activity.per_trial_rate_hz[target][trial]
                trial_rows.append(
                    {
                        "stimulus_group": group_name,
                        "trial": trial,
                        "target": target,
                        "target_rate_hz": rate,
                        "baseline_rate_hz": baseline_rate,
                        "delta_rate_hz": rate - baseline_rate,
                        "whole_brain_spikes": whole_brain[trial],
                        "baseline_whole_brain_spikes": baseline_whole_brain[trial],
                    }
                )
            right = activity.per_trial_rate_hz["DNa02_R"][trial]
            left = activity.per_trial_rate_hz["DNa02_L"][trial]
            lateral_rows.append(
                {
                    "stimulus_group": group_name,
                    "trial": trial,
                    "DNa02_L_Hz": left,
                    "DNa02_R_Hz": right,
                    "R_minus_L_Hz": right - left,
                    "L_minus_R_Hz": left - right,
                }
            )

        for target in SCREEN_TARGETS:
            values = activity.per_trial_rate_hz[target]
            mean_rate = activity.mean_rate_hz[target]
            summary_rows.append(
                {
                    "stimulus_group": group_name,
                    "target": target,
                    "mean_rate_hz": mean_rate,
                    "std_rate_hz": activity.std_rate_hz[target],
                    "min_rate_hz": min(values),
                    "max_rate_hz": max(values),
                    "baseline_mean_rate_hz": baseline_activity.mean_rate_hz[target],
                    "delta_mean_rate_hz": mean_rate - baseline_activity.mean_rate_hz[target],
                    "whole_brain_spikes_mean": sum(whole_brain) / len(whole_brain),
                }
            )

    trials_path = output_dir / "motor_dn_revalidation_trials.csv"
    summary_path = output_dir / "motor_dn_revalidation_summary.csv"
    lateral_path = output_dir / "motor_dn_lateral_revalidation.csv"
    pd.DataFrame(trial_rows).to_csv(trials_path, index=False)
    pd.DataFrame(summary_rows).to_csv(summary_path, index=False)
    pd.DataFrame(lateral_rows).to_csv(lateral_path, index=False)
    summary_frame = pd.DataFrame(summary_rows)
    lateral_frame = pd.DataFrame(lateral_rows)
    primary_group = "top5_DNa02_R"
    primary = summary_frame[summary_frame["stimulus_group"] == primary_group]
    primary_lateral = lateral_frame[lateral_frame["stimulus_group"] == primary_group]
    primary_brain = {
        row["target"]: float(row["mean_rate_hz"])
        for _, row in primary.iterrows()
    }
    primary_baseline = {
        row["target"]: float(row["baseline_mean_rate_hz"])
        for _, row in primary.iterrows()
    }
    motor_poc = {
        "protocolVersion": 1,
        "dataset": dataset.name,
        "stimulus": {
            "group": primary_group,
            "targetIds": groups[primary_group],
            "frequencyHz": args.frequency_hz,
            "nRun": args.n_run,
        },
        "brain": {
            "DNa02_L_Hz": primary_brain["DNa02_L"],
            "DNa02_R_Hz": primary_brain["DNa02_R"],
            "DNp09_Hz": primary_brain["DNp09"],
        },
        "baseline": {
            "DNa02_L_Hz": primary_baseline["DNa02_L"],
            "DNa02_R_Hz": primary_baseline["DNa02_R"],
            "DNp09_Hz": primary_baseline["DNp09"],
        },
        "DNa02_lateral": {
            "R_minus_L_Hz_mean": float(primary_lateral["R_minus_L_Hz"].mean()),
            "L_minus_R_Hz_mean": float(primary_lateral["L_minus_R_Hz"].mean()),
        },
        "alternativeConditions": [
            {
                "group": group_name,
                "targetIds": groups[group_name],
                "brain": {
                    "DNa02_L_Hz": float(
                        summary_frame[
                            (summary_frame["stimulus_group"] == group_name)
                            & (summary_frame["target"] == "DNa02_L")
                        ]["mean_rate_hz"].iloc[0]
                    ),
                    "DNa02_R_Hz": float(
                        summary_frame[
                            (summary_frame["stimulus_group"] == group_name)
                            & (summary_frame["target"] == "DNa02_R")
                        ]["mean_rate_hz"].iloc[0]
                    ),
                    "DNp09_Hz": float(
                        summary_frame[
                            (summary_frame["stimulus_group"] == group_name)
                            & (summary_frame["target"] == "DNp09")
                        ]["mean_rate_hz"].iloc[0]
                    ),
                },
            }
            for group_name in groups
            if group_name != primary_group
        ],
    }
    motor_poc_path = output_dir / "brain_motor_poc.json"
    motor_poc_path.write_text(json.dumps(motor_poc, indent=2) + "\n")
    print(f"trials: {trials_path}")
    print(f"summary: {summary_path}")
    print(f"lateral: {lateral_path}")
    print(f"motor PoC: {motor_poc_path}")
    print(summary_frame.to_string(index=False))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", choices=("v630", "v783"), default="v783")
    parser.add_argument("--frequency-hz", type=int, default=100)
    parser.add_argument("--n-run", type=int, choices=(5, 10), default=5)
    parser.add_argument("--n-proc", type=int, default=-1)
    parser.add_argument("--force-overwrite", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    run(parse_args())
