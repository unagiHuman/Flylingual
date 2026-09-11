"""Measure R/L/F controller states on one persistent FlyWire brain.

The fixed sequence is:
OFF, R, OFF, L, OFF, F, OFF, F+R, OFF, F+L, OFF.
Each phase is 500 ms. The network is built once per process and the input
rates are changed without resetting neuron, synapse, or refractory state.
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
    ms,
    prefs,
    second,
    start_scope,
)

from model import create_model, default_params
from poc_config import DESCENDING_NEURON_IDS, MOTOR_DN_STIMULUS_GROUPS, REPO_ROOT, get_dataset


TARGET_NAMES = ("DNa02_R", "DNa02_L", "DNp09")
GROUPS = {
    "R": "top5_DNa02_R",
    "L": "top5_DNa02_L",
    "F": "top5_DNp09",
}
PHASES = (
    ("OFF_0", ()),
    ("R", ("R",)),
    ("OFF_1", ()),
    ("L", ("L",)),
    ("OFF_2", ()),
    ("F", ("F",)),
    ("OFF_3", ()),
    ("F+R", ("F", "R")),
    ("OFF_4", ()),
    ("F+L", ("F", "L")),
    ("OFF_5", ()),
)


def _rss_mb(process: psutil.Process) -> float:
    return process.memory_info().rss / (1024 * 1024)


def _counts(monitor: SpikeMonitor, target_indices: dict[str, int]) -> tuple[dict[str, int], int]:
    all_counts = np.asarray(monitor.count[:], dtype=np.int64)
    return (
        {name: int(all_counts[index]) for name, index in target_indices.items()},
        int(all_counts.sum()),
    )


def _phase_steps(phase_ms: int, requested_step_ms: int) -> list[int]:
    full_steps, remainder = divmod(phase_ms, requested_step_ms)
    durations = [requested_step_ms] * full_steps
    if remainder:
        durations.append(remainder)
    return durations


def _rate(count: int, duration_ms: int) -> float:
    return float(count / (duration_ms / 1000.0))


def _group_ids(alias_names: tuple[str, ...]) -> list[int]:
    ids = set()
    for alias in alias_names:
        ids.update(MOTOR_DN_STIMULUS_GROUPS[GROUPS[alias]])
    return sorted(ids)


def run(args: argparse.Namespace) -> Path:
    if args.phase_ms <= 0 or args.step_ms <= 0:
        raise ValueError("phase-ms and step-ms must be positive")

    dataset = get_dataset(args.dataset)
    target_ids = {name: int(DESCENDING_NEURON_IDS[name]) for name in TARGET_NAMES}
    all_stimulus_ids = _group_ids(("R", "L", "F"))
    if set(all_stimulus_ids).intersection(target_ids.values()):
        raise RuntimeError("A stimulus group directly contains a target DN")

    completeness = pd.read_csv(dataset.completeness_path, index_col=0)
    flywire_ids = [int(value) for value in completeness.index]
    flywire_to_index = {root_id: index for index, root_id in enumerate(flywire_ids)}
    required_ids = all_stimulus_ids + list(target_ids.values())
    missing = [root_id for root_id in required_ids if root_id not in flywire_to_index]
    if missing:
        raise RuntimeError(f"IDs missing from {dataset.name} completeness: {missing}")

    output_dir = REPO_ROOT / "results" / "codex_run"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = (
        Path(args.output)
        if args.output
        else output_dir / f"brain_controller_sequence_{args.backend}_{args.step_ms}ms.json"
    )
    jsonl_path = output_path.with_suffix(".jsonl")
    process = psutil.Process()
    rss_before_init = _rss_mb(process)
    init_started = time.perf_counter()

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

    source_indices = [flywire_to_index[root_id] for root_id in all_stimulus_ids]
    source_index_by_root_id = {
        root_id: index for index, root_id in enumerate(all_stimulus_ids)
    }
    target_indices = {
        name: flywire_to_index[root_id] for name, root_id in target_ids.items()
    }
    for index in source_indices:
        neu[index].rfc = 0 * ms

    stimulus_source = PoissonGroup(
        len(source_indices),
        rates=np.zeros(len(source_indices)) * Hz,
        name="controller_stimulus_source",
    )
    stimulus_synapses = Synapses(
        stimulus_source,
        neu,
        model="w_ext : volt (constant)",
        on_pre="v_post += w_ext",
        name="controller_stimulus_synapses",
    )
    stimulus_synapses.connect(
        i=np.arange(len(source_indices), dtype=int),
        j=np.asarray(source_indices, dtype=int),
    )
    stimulus_synapses.w_ext = params["w_syn"] * params["f_poi"]
    count_monitor = SpikeMonitor(neu, record=False, name="controller_count_monitor")
    network = Network(neu, syn, stimulus_source, stimulus_synapses, count_monitor)
    init_seconds = time.perf_counter() - init_started
    rss_after_init = _rss_mb(process)

    previous_target_counts, previous_whole_count = _counts(count_monitor, target_indices)
    step_records = []
    phase_records = []
    compute_times = []
    read_save_times = []
    rss_peak = rss_after_init
    global_sequence = 0

    with jsonl_path.open("w", encoding="utf-8") as jsonl:
        for phase_index, (phase_name, active_aliases) in enumerate(PHASES):
            active_root_ids = _group_ids(active_aliases)
            rate_vector = np.zeros(len(source_indices), dtype=float)
            for root_id in active_root_ids:
                rate_vector[source_index_by_root_id[root_id]] = args.stimulus_frequency_hz
            stimulus_source.rates = rate_vector * Hz
            phase_step_records = []

            for duration_ms in _phase_steps(args.phase_ms, args.step_ms):
                brain_start_s = float(network.t / second)
                compute_started = time.perf_counter()
                network.run(duration_ms * ms)
                compute_seconds = time.perf_counter() - compute_started
                brain_end_s = float(network.t / second)
                compute_times.append(compute_seconds)

                read_save_started = time.perf_counter()
                current_target_counts, current_whole_count = _counts(count_monitor, target_indices)
                target_deltas = {
                    name: current_target_counts[name] - previous_target_counts[name]
                    for name in TARGET_NAMES
                }
                whole_delta = current_whole_count - previous_whole_count
                record = {
                    "sequence": global_sequence,
                    "phase_index": phase_index,
                    "phase": phase_name,
                    "active_stimulus_groups": list(active_aliases),
                    "active_stimulus_ids": [str(root_id) for root_id in active_root_ids],
                    "brain_interval_start_s": brain_start_s,
                    "brain_interval_end_s": brain_end_s,
                    "brain_interval_ms": duration_ms,
                    "DNa02_R": {
                        "root_id": str(target_ids["DNa02_R"]),
                        "spike_count": target_deltas["DNa02_R"],
                        "firing_rate_hz": _rate(target_deltas["DNa02_R"], duration_ms),
                    },
                    "DNa02_L": {
                        "root_id": str(target_ids["DNa02_L"]),
                        "spike_count": target_deltas["DNa02_L"],
                        "firing_rate_hz": _rate(target_deltas["DNa02_L"], duration_ms),
                    },
                    "DNp09": {
                        "root_id": str(target_ids["DNp09"]),
                        "spike_count": target_deltas["DNp09"],
                        "firing_rate_hz": _rate(target_deltas["DNp09"], duration_ms),
                    },
                    "whole_brain_spike_count": whole_delta,
                    "step_compute_seconds": compute_seconds,
                }
                phase_step_records.append(record)
                step_records.append(record)
                jsonl.write(json.dumps(record) + "\n")
                jsonl.flush()
                record["read_save_seconds"] = time.perf_counter() - read_save_started
                read_save_times.append(record["read_save_seconds"])
                rss_peak = max(rss_peak, _rss_mb(process))
                previous_target_counts = current_target_counts
                previous_whole_count = current_whole_count
                global_sequence += 1

            phase_record = {
                "phase_index": phase_index,
                "phase": phase_name,
                "active_stimulus_groups": list(active_aliases),
                "active_stimulus_ids": [str(root_id) for root_id in active_root_ids],
                "brain_interval_start_s": phase_step_records[0]["brain_interval_start_s"],
                "brain_interval_end_s": phase_step_records[-1]["brain_interval_end_s"],
                "brain_interval_ms": sum(item["brain_interval_ms"] for item in phase_step_records),
                "DNa02_R_spike_count": sum(item["DNa02_R"]["spike_count"] for item in phase_step_records),
                "DNa02_L_spike_count": sum(item["DNa02_L"]["spike_count"] for item in phase_step_records),
                "DNp09_spike_count": sum(item["DNp09"]["spike_count"] for item in phase_step_records),
                "whole_brain_spike_count": sum(item["whole_brain_spike_count"] for item in phase_step_records),
            }
            phase_record["DNa02_R_rate_hz"] = _rate(
                phase_record["DNa02_R_spike_count"], phase_record["brain_interval_ms"]
            )
            phase_record["DNa02_L_rate_hz"] = _rate(
                phase_record["DNa02_L_spike_count"], phase_record["brain_interval_ms"]
            )
            phase_record["DNp09_rate_hz"] = _rate(
                phase_record["DNp09_spike_count"], phase_record["brain_interval_ms"]
            )
            phase_records.append(phase_record)

    compute_after_first = compute_times[1:]
    simulated_seconds = sum(item["brain_interval_ms"] for item in step_records) / 1000.0
    result = {
        "protocolVersion": 1,
        "dataset": dataset.name,
        "backend": args.backend,
        "random_seed": args.seed,
        "dt_ms": float(defaultclock.dt / ms),
        "network_rebuild_count": 1,
        "state_reset_count": 0,
        "spike_history_recorded": False,
        "refractory_behavior": (
            "All fixed upstream candidates use rfc=0 ms for the whole session, "
            "matching model.poi. Input OFF changes rates only; no state reset."
        ),
        "sequence_definition": [
            {"phase": name, "active_stimulus_groups": list(active)}
            for name, active in PHASES
        ],
        "stimulus_frequency_hz": args.stimulus_frequency_hz,
        "phase_ms": args.phase_ms,
        "requested_step_ms": args.step_ms,
        "partial_step_count": sum(
            1 for duration in _phase_steps(args.phase_ms, args.step_ms) if duration != args.step_ms
        ) * len(PHASES),
        "performance": {
            "initialization_seconds": init_seconds,
            "first_step_compute_seconds": compute_times[0],
            "subsequent_step_compute_seconds_mean": float(np.mean(compute_after_first)),
            "subsequent_step_compute_seconds_median": float(np.median(compute_after_first)),
            "subsequent_step_compute_seconds_p95": float(np.percentile(compute_after_first, 95)),
            "subsequent_step_compute_seconds_max": float(np.max(compute_after_first)),
            "mean_read_save_seconds": float(np.mean(read_save_times)),
            "simulated_seconds": simulated_seconds,
            "compute_seconds_total": float(np.sum(compute_times)),
            "compute_to_brain_time_ratio": float(np.sum(compute_times) / simulated_seconds),
            "total_steps": len(step_records),
        },
        "memory": {
            "rss_before_init_mb": rss_before_init,
            "rss_after_init_mb": rss_after_init,
            "rss_peak_mb": rss_peak,
            "rss_peak_delta_after_init_mb": rss_peak - rss_after_init,
        },
        "stimulus_groups": {
            alias: {
                "config_key": config_key,
                "target_ids": [str(root_id) for root_id in MOTOR_DN_STIMULUS_GROUPS[config_key]],
            }
            for alias, config_key in GROUPS.items()
        },
        "artifacts": {"step_jsonl": str(jsonl_path), "result_json": str(output_path)},
        "phases": phase_records,
        "steps": step_records,
    }
    output_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result["performance"], indent=2))
    print(f"result written: {output_path}")
    return output_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", choices=("v630", "v783"), default="v783")
    parser.add_argument("--backend", choices=("numpy", "cython"), default="cython")
    parser.add_argument("--seed", type=int, default=20260910)
    parser.add_argument("--stimulus-frequency-hz", type=int, default=100)
    parser.add_argument("--phase-ms", type=int, default=500)
    parser.add_argument("--step-ms", type=int, choices=(25, 50, 100, 200), default=100)
    parser.add_argument("--output")
    return parser.parse_args()


if __name__ == "__main__":
    run(parse_args())
