"""Small adapter around the upstream whole-brain simulation.

This module deliberately calls the existing ``model.run_exp`` and
``utils.get_rate`` functions instead of changing the official implementation.
It is the seam that can later be replaced by a persistent brain process.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Mapping

import pandas as pd
from brian2 import Hz, second

import utils as utl
from model import default_params, run_exp
from poc_config import DatasetConfig


@dataclass(frozen=True)
class BrainExperimentResult:
    """Metadata for one completed simulation output."""

    dataset_name: str
    experiment_name: str
    frequency_hz: float
    n_run: int
    duration_s: float
    parquet_path: Path


@dataclass(frozen=True)
class FiringRateResult:
    """Target-neuron activity extracted from one experiment."""

    experiment: BrainExperimentResult
    total_spikes: Mapping[str, int]
    mean_rate_hz: Mapping[str, float]
    std_rate_hz: Mapping[str, float]
    per_trial_rate_hz: Mapping[str, List[float]]


def run_brain_experiment(
    stimulated_neuron_ids: Iterable[int],
    stimulus_frequency_hz: float,
    dataset: DatasetConfig,
    experiment_name: str,
    n_run: int = 3,
    n_proc: int = -1,
    force_overwrite: bool = False,
    allow_zero_spikes: bool = False,
) -> BrainExperimentResult:
    """Run the upstream model with an explicit dataset and stimulus.

    The output directory is created here because the upstream ``run_exp``
    expects its parent directory to already exist.
    """

    if n_run < 1:
        raise ValueError("n_run must be at least 1")
    if stimulus_frequency_hz <= 0:
        raise ValueError("stimulus_frequency_hz must be positive")

    dataset.result_root.mkdir(parents=True, exist_ok=True)
    params = dict(default_params)
    params["n_run"] = int(n_run)
    params["r_poi"] = float(stimulus_frequency_hz) * Hz

    run_exp(
        exp_name=experiment_name,
        neu_exc=[int(neuron_id) for neuron_id in stimulated_neuron_ids],
        path_res=dataset.result_root,
        path_comp=dataset.completeness_path,
        path_con=dataset.connectivity_path,
        params=params,
        n_proc=n_proc,
        force_overwrite=force_overwrite,
    )

    parquet_path = dataset.result_root / f"{experiment_name}.parquet"
    if not parquet_path.is_file():
        raise RuntimeError(f"Simulation completed without parquet output: {parquet_path}")
    if not allow_zero_spikes and pd.read_parquet(parquet_path, columns=["t"]).empty:
        raise RuntimeError(f"Simulation produced zero spikes: {parquet_path}")

    return BrainExperimentResult(
        dataset_name=dataset.name,
        experiment_name=experiment_name,
        frequency_hz=float(stimulus_frequency_hz),
        n_run=int(n_run),
        duration_s=float(default_params["t_run"] / second),
        parquet_path=parquet_path,
    )


def extract_firing_rates(
    result: BrainExperimentResult,
    target_neuron_ids: Mapping[str, int],
) -> FiringRateResult:
    """Extract total, mean, standard-deviation, and per-trial rates.

    Targets with no spikes are retained with zero values, which is important
    for a decoder: absence of a spike must not be confused with missing data.
    """

    df_spike = utl.load_exps([str(result.parquet_path)])
    target_names = list(target_neuron_ids)
    target_ids = [int(target_neuron_ids[name]) for name in target_names]

    if df_spike.empty:
        zeros = {name: 0.0 for name in target_names}
        return FiringRateResult(
            experiment=result,
            total_spikes={name: 0 for name in target_names},
            mean_rate_hz=zeros,
            std_rate_hz=zeros,
            per_trial_rate_hz={name: [0.0] * result.n_run for name in target_names},
        )

    df_rate, df_rate_std = utl.get_rate(
        df_spike,
        t_run=result.duration_s,
        n_run=result.n_run,
    )
    rate_column = result.experiment_name
    mean_series = df_rate[rate_column] if rate_column in df_rate else pd.Series(dtype=float)
    std_series = df_rate_std[rate_column] if rate_column in df_rate_std else pd.Series(dtype=float)

    mean_by_id = mean_series.reindex(target_ids).fillna(0.0)
    std_by_id = std_series.reindex(target_ids).fillna(0.0)

    target_spikes = df_spike[df_spike["flywire_id"].isin(target_ids)]
    total_by_id = target_spikes.groupby("flywire_id").size().reindex(target_ids, fill_value=0)

    if target_spikes.empty:
        per_trial = pd.DataFrame(0.0, index=target_ids, columns=range(result.n_run))
    else:
        counts = target_spikes.groupby(["flywire_id", "trial"]).size().unstack(fill_value=0)
        per_trial = counts.reindex(index=target_ids, columns=range(result.n_run), fill_value=0)
        per_trial = per_trial.astype(float) / result.duration_s

    return FiringRateResult(
        experiment=result,
        total_spikes={name: int(total_by_id.loc[root_id]) for name, root_id in target_neuron_ids.items()},
        mean_rate_hz={name: float(mean_by_id.loc[root_id]) for name, root_id in target_neuron_ids.items()},
        std_rate_hz={name: float(std_by_id.loc[root_id]) for name, root_id in target_neuron_ids.items()},
        per_trial_rate_hz={
            name: [float(value) for value in per_trial.loc[root_id].tolist()]
            for name, root_id in target_neuron_ids.items()
        },
    )
