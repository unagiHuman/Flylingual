"""Run the minimal persistent-brain stimulus-switching smoke test.

One v783 whole-brain Brian2 network is built once, then advanced for 15
steps: 500 ms off, 500 ms on for the fixed top5_DNa02_R upstream group, and
500 ms off again. The Poisson source rate is changed between steps without
resetting neuron or synapse state.
"""

import argparse
import json
import random
import time
from pathlib import Path

import numpy as np
import pandas as pd
import psutil
from brian2 import (
    Hz,
    Network,
    PoissonGroup,
    SpikeMonitor,
    Synapses,
    defaultclock,
    mV,
    ms,
    prefs,
    second,
    start_scope,
)

from model import create_model, default_params
from poc_config import (
    DESCENDING_NEURON_IDS,
    MOTOR_DN_STIMULUS_GROUPS,
    REPO_ROOT,
    get_dataset,
)


TARGET_NAMES = ("DNa02_R", "DNa02_L", "DNp09")
STIMULUS_GROUP_NAME = "top5_DNa02_R"


def _rss_mb(process: psutil.Process) -> float:
    return process.memory_info().rss / (1024 * 1024)


def _phase_for_step(step: int, steps_per_phase: int) -> tuple[str, bool]:
    if step < steps_per_phase:
        return "baseline_before", False
    if step < steps_per_phase * 2:
        return "stimulus_on", True
    return "baseline_after", False


def _counts(monitor: SpikeMonitor, target_indices: dict[str, int]) -> tuple[dict[str, int], int]:
    all_counts = np.asarray(monitor.count[:], dtype=np.int64)
    target_counts = {
        name: int(all_counts[index]) for name, index in target_indices.items()
    }
    return target_counts, int(all_counts.sum())


def _rate(count: int, duration_s: float) -> float:
    return float(count / duration_s)


def run(args: argparse.Namespace) -> Path:
    if args.phase_ms <= 0 or args.step_ms <= 0:
        raise ValueError("phase and step durations must be positive")
    if args.phase_ms % args.step_ms != 0:
        raise ValueError("phase_ms must be divisible by step_ms")

    dataset = get_dataset(args.dataset)
    stimulus_ids = list(MOTOR_DN_STIMULUS_GROUPS[STIMULUS_GROUP_NAME])
    target_ids = {name: int(DESCENDING_NEURON_IDS[name]) for name in TARGET_NAMES}
    if set(stimulus_ids).intersection(target_ids.values()):
        raise RuntimeError("The persistent stimulus group directly stimulates a target DN")

    completeness = pd.read_csv(dataset.completeness_path, index_col=0)
    flywire_ids = [int(value) for value in completeness.index]
    flywire_to_index = {root_id: index for index, root_id in enumerate(flywire_ids)}
    missing = [root_id for root_id in stimulus_ids + list(target_ids.values()) if root_id not in flywire_to_index]
    if missing:
        raise RuntimeError(f"IDs missing from {dataset.name} completeness: {missing}")

    output_dir = dataset.result_root.parent
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = (
        Path(args.output)
        if args.output
        else output_dir / f"persistent_brain_smoke_{args.backend}.json"
    )
    jsonl_path = output_path.with_suffix(".jsonl")
    process = psutil.Process()
    rss_before_init = _rss_mb(process)
    init_started = time.perf_counter()

    # Keep the official model equations and weights, while explicitly using
    # the same NumPy backend as the existing successful experiments.
    prefs.codegen.target = args.backend
    if args.backend == "cython":
        prefs.codegen.runtime.cython.cache_dir = str(
            REPO_ROOT / "results" / "codex_run" / "cython_cache"
        )
    start_scope()
    np.random.seed(args.seed)
    random.seed(args.seed)
    params = dict(default_params)
    params["r_poi"] = float(args.stimulus_frequency_hz) * Hz
    params["n_run"] = 1
    neu, syn, unused_monitor = create_model(
        dataset.completeness_path,
        dataset.connectivity_path,
        params,
    )
    del unused_monitor

    stimulus_indices = [flywire_to_index[root_id] for root_id in stimulus_ids]
    target_indices = {
        name: flywire_to_index[root_id] for name, root_id in target_ids.items()
    }

    # model.poi sets rfc=0 for externally stimulated neurons. Keep that
    # behavior for the whole persistent run; OFF changes only input rate.
    for index in stimulus_indices:
        neu[index].rfc = 0 * ms

    stimulus_source = PoissonGroup(
        len(stimulus_indices),
        rates=0 * Hz,
        name="persistent_stimulus_source",
    )
    stimulus_synapses = Synapses(
        stimulus_source,
        neu,
        model="w_ext : volt (constant)",
        on_pre="v_post += w_ext",
        name="persistent_stimulus_synapses",
    )
    stimulus_synapses.connect(
        i=np.arange(len(stimulus_indices), dtype=int),
        j=np.asarray(stimulus_indices, dtype=int),
    )
    stimulus_synapses.w_ext = params["w_syn"] * params["f_poi"]

    # record=False keeps only cumulative counts, not the full whole-brain
    # spike history. Counts are differenced at every 100 ms boundary.
    count_monitor = SpikeMonitor(neu, record=False, name="persistent_count_monitor")
    network = Network(neu, syn, stimulus_source, stimulus_synapses, count_monitor)
    init_seconds = time.perf_counter() - init_started
    rss_after_init = _rss_mb(process)

    steps_per_phase = int(args.phase_ms // args.step_ms)
    total_steps = steps_per_phase * 3
    step_duration_s = args.step_ms / 1000.0
    previous_target_counts, previous_whole_count = _counts(count_monitor, target_indices)
    step_records = []
    compute_times = []
    read_save_times = []
    rss_peak = rss_after_init

    with jsonl_path.open("w", encoding="utf-8") as jsonl:
        for step in range(total_steps):
            phase, stimulus_on = _phase_for_step(step, steps_per_phase)
            switch_started = time.perf_counter()
            stimulus_source.rates = (
                float(args.stimulus_frequency_hz) * Hz if stimulus_on else 0 * Hz
            )
            switch_seconds = time.perf_counter() - switch_started

            brain_start_s = float(network.t / second)
            compute_started = time.perf_counter()
            network.run(args.step_ms * ms)
            compute_seconds = time.perf_counter() - compute_started
            brain_end_s = float(network.t / second)
            compute_times.append(compute_seconds)

            read_save_started = time.perf_counter()
            current_target_counts, current_whole_count = _counts(count_monitor, target_indices)
            target_deltas = {
                name: current_target_counts[name] - previous_target_counts[name]
                for name in TARGET_NAMES
            }
            whole_brain_delta = current_whole_count - previous_whole_count
            record = {
                "sequence": step,
                "phase": phase,
                "brain_interval_start_s": brain_start_s,
                "brain_interval_end_s": brain_end_s,
                "active_stimulus_group": STIMULUS_GROUP_NAME if stimulus_on else None,
                "active_stimulus_ids": [str(root_id) for root_id in stimulus_ids]
                if stimulus_on
                else [],
                "DNa02_R": {
                    "root_id": str(target_ids["DNa02_R"]),
                    "spike_count": target_deltas["DNa02_R"],
                    "firing_rate_hz": _rate(target_deltas["DNa02_R"], step_duration_s),
                },
                "DNa02_L": {
                    "root_id": str(target_ids["DNa02_L"]),
                    "spike_count": target_deltas["DNa02_L"],
                    "firing_rate_hz": _rate(target_deltas["DNa02_L"], step_duration_s),
                },
                "DNp09": {
                    "root_id": str(target_ids["DNp09"]),
                    "spike_count": target_deltas["DNp09"],
                    "firing_rate_hz": _rate(target_deltas["DNp09"], step_duration_s),
                },
                "whole_brain_spike_count": whole_brain_delta,
                "step_compute_seconds": compute_seconds,
                "input_switch_seconds": switch_seconds,
            }
            step_records.append(record)
            jsonl.write(json.dumps(record) + "\n")
            jsonl.flush()
            read_save_seconds = time.perf_counter() - read_save_started
            record["read_save_seconds"] = read_save_seconds
            read_save_times.append(read_save_seconds)
            rss_peak = max(rss_peak, _rss_mb(process))
            previous_target_counts = current_target_counts
            previous_whole_count = current_whole_count

    # The JSONL has the durable per-step fields; the final JSON includes the
    # same records plus summary metadata. Keep root IDs as strings in JSON.
    compute_after_first = compute_times[1:]
    final = {
        "protocolVersion": 1,
        "dataset": dataset.name,
        "backend": args.backend,
        "random_seed": args.seed,
        "dt_ms": float(defaultclock.dt / ms),
        "network_rebuild_count": 1,
        "state_reset_count": 0,
        "spike_history_recorded": False,
        "refractory_behavior": (
            "Stimulus candidates use rfc=0 ms for the entire run, matching "
            "model.poi. OFF sets Poisson rate to 0 only; membrane, synapse, "
            "and refractory state are not reset."
        ),
        "stimulus": {
            "group": STIMULUS_GROUP_NAME,
            "targetIds": [str(root_id) for root_id in stimulus_ids],
            "frequencyHz": args.stimulus_frequency_hz,
            "phaseMs": args.phase_ms,
            "stepMs": args.step_ms,
            "totalSteps": total_steps,
        },
        "performance": {
            "initialization_seconds": init_seconds,
            "first_step_compute_seconds": compute_times[0],
            "subsequent_step_compute_seconds_mean": float(np.mean(compute_after_first)),
            "subsequent_step_compute_seconds_median": float(np.median(compute_after_first)),
            "subsequent_step_compute_seconds_p95": float(np.percentile(compute_after_first, 95)),
            "subsequent_step_compute_seconds_min": float(np.min(compute_after_first)),
            "subsequent_step_compute_seconds_max": float(np.max(compute_after_first)),
            "mean_read_save_seconds": float(np.mean(read_save_times)),
            "brain_time_seconds": args.phase_ms * 3 / 1000.0,
            "compute_seconds_total": float(np.sum(compute_times)),
            "compute_to_brain_time_ratio": float(np.sum(compute_times) / (args.phase_ms * 3 / 1000.0)),
        },
        "memory": {
            "rss_before_init_mb": rss_before_init,
            "rss_after_init_mb": rss_after_init,
            "rss_peak_mb": rss_peak,
            "rss_peak_delta_after_init_mb": rss_peak - rss_after_init,
        },
        "artifacts": {
            "step_jsonl": str(jsonl_path),
            "result_json": str(output_path),
        },
        "steps": step_records,
    }
    output_path.write_text(json.dumps(final, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(final["performance"], indent=2))
    print(json.dumps(final["memory"], indent=2))
    print(f"steps={total_steps} result={output_path} jsonl={jsonl_path}")
    return output_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", choices=("v630", "v783"), default="v783")
    parser.add_argument("--stimulus-frequency-hz", type=int, default=100)
    parser.add_argument("--phase-ms", type=int, default=500)
    parser.add_argument("--step-ms", type=int, default=100)
    parser.add_argument("--backend", choices=("numpy", "cython"), default="numpy")
    parser.add_argument("--seed", type=int, default=20260910)
    parser.add_argument("--output")
    return parser.parse_args()


if __name__ == "__main__":
    run(parse_args())
