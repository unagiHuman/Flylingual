"""Persistent-controller fixed-point equivalence validator for MaleCNS.

This is an offline direct-simulation acceptance tool.  It loads the pinned
pre-fixed-point implementation from ``git show`` in isolated module names and
compares it with the working-tree candidate after every paired 50 ms window.
It intentionally does not start Brain, TCP, Unity, or external services.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib
import importlib.metadata
import importlib.util
import json
import os
import platform
import struct
import subprocess
import sys
import time
import traceback
import types
from datetime import datetime, timezone
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASELINE_REF = "eb6d3143131c5783dbed1657fcffb856166f03f3"
SOURCE_FILES = (
    "Brain/MaleCNS/lif_kernels.py",
    "Brain/MaleCNS/shiu_compatible.py",
    "Brain/MaleCNS/analog_controller.py",
)
ACTION_SEQUENCE = ("STOP", "FORWARD", "TURN_R", "TURN_L", "FORWARD_R", "FORWARD_L")
EXPECTED_TINY = 2.2250738585072014e-308


def sha256_bytes(value):
    return hashlib.sha256(value).hexdigest()


def sha256_file(path):
    return sha256_bytes(Path(path).read_bytes())


def git_source(ref, path):
    return subprocess.check_output(
        ["git", "-c", "safe.directory=" + ROOT.as_posix(), "show", ref + ":" + path], cwd=ROOT)


def save_report(path, report):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
    temporary.replace(path)


def assert_exact(a, b, label):
    """Require type, container order, IEEE bits, and signed zeros to match."""
    if isinstance(a, np.ndarray):
        if not isinstance(b, np.ndarray) or a.shape != b.shape or a.dtype != b.dtype:
            raise AssertionError(label + ": array shape/dtype mismatch")
        if np.issubdtype(a.dtype, np.floating) and (not np.isfinite(a).all() or not np.isfinite(b).all()):
            raise AssertionError(label + ": nonfinite value")
        if a.tobytes() != b.tobytes():
            raise AssertionError(label + ": array bit mismatch")
    elif isinstance(a, dict):
        if not isinstance(b, dict) or a.keys() != b.keys():
            raise AssertionError(label + ": dictionary keys mismatch")
        for key in a:
            assert_exact(a[key], b[key], label + "." + str(key))
    elif isinstance(a, (list, tuple)):
        if type(a) is not type(b) or len(a) != len(b):
            raise AssertionError(label + ": sequence type/length mismatch")
        for index, (left, right) in enumerate(zip(a, b)):
            assert_exact(left, right, label + "[" + str(index) + "]")
    elif isinstance(a, (float, np.floating)):
        if not np.isfinite(a) or not np.isfinite(b):
            raise AssertionError(label + ": nonfinite scalar")
        if struct.pack("!d", float(a)) != struct.pack("!d", float(b)):
            raise AssertionError(label + ": float bit mismatch")
    elif a != b:
        raise AssertionError(label + ": value mismatch")


def state_digest(controller):
    simulation = controller.sim
    digest = hashlib.sha256()
    for name in ("v", "g", "last", "rfc"):
        value = getattr(simulation, name)
        digest.update(name.encode("ascii"))
        digest.update(value.dtype.str.encode("ascii"))
        digest.update(value.tobytes())
    digest.update(json.dumps([simulation.tick, simulation.pending], separators=(",", ":")).encode("utf-8"))
    return digest.hexdigest()


def pending_digest(simulation):
    return sha256_bytes(json.dumps(simulation.pending, separators=(",", ":")).encode("utf-8"))


def rng_digest(controller):
    return sha256_bytes(json.dumps(controller.rng.bit_generator.state, sort_keys=True,
                                  separators=(",", ":")).encode("utf-8"))


def subnormal_count(values):
    absolute = np.abs(values)
    return int(np.count_nonzero((absolute != 0.0) & (absolute < np.finfo(np.float64).tiny)))


def stable_conductance_statistics(simulation):
    """Count tiny bit-pattern conductances without changing the state arrays."""
    bits = simulation.g.view(np.uint64) & np.uint64(0x7FFFFFFFFFFFFFFF)
    stable = bits <= np.uint64(25)
    nonzero_stable_at_reset = stable & (simulation.g != 0.0) & (simulation.v == -52.0)
    return {"gStableBitMagnitudeLe25Count": int(np.count_nonzero(stable)),
            "gStableNonzeroAtResetVCount": int(np.count_nonzero(nonzero_stable_at_reset))}


def compare_simulations(left, right):
    for name in ("v", "g", "last", "rfc", "tick", "pending", "dt"):
        assert_exact(getattr(left, name), getattr(right, name), "sim." + name)


def timed_call(call, process):
    rss_before = process.memory_info().rss
    cpu_start = time.process_time_ns()
    wall_start = time.perf_counter_ns()
    result = call()
    wall_end = time.perf_counter_ns()
    cpu_end = time.process_time_ns()
    return result, {"wallMs": (wall_end - wall_start) / 1_000_000.0,
                    "processCpuMs": (cpu_end - cpu_start) / 1_000_000.0,
                    "rssBeforeBytes": rss_before, "rssAfterBytes": process.memory_info().rss}


def load_baseline(ref, directory):
    """Load three unchanged git blobs without replacing candidate sys.modules.

    Numba cache-enabled functions need a stable real source path.  The immutable
    materialization is checked byte-for-byte and is never replaced in place.
    """
    module_directory = str(ROOT / "Brain/MaleCNS")
    if module_directory not in sys.path:
        sys.path.insert(0, module_directory)
    sources = {path: git_source(ref, path) for path in SOURCE_FILES}
    directory.mkdir(parents=True, exist_ok=True)
    materialized = {}
    for path, source in sources.items():
        target = directory / Path(path).name
        if target.exists():
            if target.read_bytes() != source:
                raise AssertionError("existing baseline materialization differs: " + str(target))
        else:
            target.write_bytes(source)
        materialized[path] = target
    kernel_name = "fixed_point_baseline_kernels_" + sha256_bytes(ref.encode("ascii"))[:12]
    spec = importlib.util.spec_from_file_location(kernel_name, materialized[SOURCE_FILES[0]])
    kernels = importlib.util.module_from_spec(spec)
    sys.modules[kernel_name] = kernels
    # The runtime cache-compatibility header inserts its own source directory.
    # A snapshot must not become the normal candidate import search path.
    previous_path = sys.path[:]
    try:
        spec.loader.exec_module(kernels)
    finally:
        sys.path[:] = previous_path

    lif = types.ModuleType("fixed_point_baseline_lif")
    lif.__file__ = str(materialized[SOURCE_FILES[1]])
    exec(compile(sources[SOURCE_FILES[1]], lif.__file__, "exec"), lif.__dict__)
    # The snapshot's direct import resolved the candidate module during exec;
    # bind every kernel it uses to the isolated baseline implementation instead.
    for name, value in vars(kernels).items():
        if callable(value):
            lif.__dict__[name] = value

    controller = types.ModuleType("fixed_point_baseline_controller")
    controller.__file__ = str(materialized[SOURCE_FILES[2]])
    exec(compile(sources[SOURCE_FILES[2]], controller.__file__, "exec"), controller.__dict__)
    controller.MaleCNSShiuCompatibleLIF = lif.MaleCNSShiuCompatibleLIF
    return lif, controller, kernels, sources, materialized


def load_candidate():
    module_directory = str(ROOT / "Brain/MaleCNS")
    if module_directory not in sys.path:
        sys.path.insert(0, module_directory)
    kernels = importlib.import_module("lif_kernels")
    lif = importlib.import_module("shiu_compatible")
    controller = importlib.import_module("analog_controller")
    return lif, controller, kernels


def install_kernel_timer(lif_module, kernel_module):
    """Observe the actual run_window call without altering its arguments/result."""
    original = lif_module.run_window
    sample = {}

    def measured(*args, **kwargs):
        wall_start = time.perf_counter_ns()
        cpu_start = time.thread_time_ns()
        try:
            return original(*args, **kwargs)
        finally:
            sample.clear()
            sample.update({"kernelWallMs": (time.perf_counter_ns() - wall_start) / 1_000_000.0,
                           "kernelThreadCpuMs": (time.thread_time_ns() - cpu_start) / 1_000_000.0})

    lif_module.run_window = measured
    if getattr(kernel_module, "run_window", None) is original:
        kernel_module.run_window = measured
    return sample


def add_count_capture(controller):
    original = controller.sim.step_window

    def capture(*args, **kwargs):
        result = original(*args, **kwargs)
        controller.validation_counts = result[0]
        return result

    controller.sim.step_window = capture


def numerical_frame(frame):
    result = copy.deepcopy(frame)
    result.pop("performance", None)
    return result


def summary(rows, label):
    wall = np.asarray([row["timing"][label]["wallMs"] for row in rows], dtype=np.float64)
    cpu = np.asarray([row["timing"][label]["processCpuMs"] for row in rows], dtype=np.float64)
    kernel_wall = np.asarray([row["kernel"][label].get("kernelWallMs", 0.0) for row in rows], dtype=np.float64)
    kernel_cpu = np.asarray([row["kernel"][label].get("kernelThreadCpuMs", 0.0) for row in rows], dtype=np.float64)
    return {"n": int(wall.size), "wallMeanMs": float(wall.mean()), "wallP95Ms": float(np.percentile(wall, 95)),
            "wallMaxMs": float(wall.max()), "processCpuMeanMs": float(cpu.mean()),
            "kernelWallMeanMs": float(kernel_wall.mean()), "kernelWallP95Ms": float(np.percentile(kernel_wall, 95)),
            "kernelThreadCpuMeanMs": float(kernel_cpu.mean())}


def make_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path,
                        default=ROOT / "artifacts/windows-malecns/fixed-point/equivalence.json")
    parser.add_argument("--baseline-ref", default=DEFAULT_BASELINE_REF)
    parser.add_argument("--graph", type=Path, default=ROOT / "artifacts/neuron_checkpoint")
    parser.add_argument("--config", type=Path, default=ROOT / "Brain/MaleCNS/config/analog_temporal_v1.json")
    parser.add_argument("--seeds", type=int, nargs="+", default=[20270101, 20270102, 20270103])
    parser.add_argument("--initial-stop-windows", type=int, default=4)
    parser.add_argument("--forward-windows", type=int, default=8)
    parser.add_argument("--subnormal-stop-windows", type=int, default=100)
    parser.add_argument("--action-windows", type=int, default=4)
    return parser


def main(argv=None):
    args = make_parser().parse_args(argv)
    counts = (args.initial_stop_windows, args.forward_windows, args.subnormal_stop_windows, args.action_windows)
    if len(set(args.seeds)) != len(args.seeds) or not args.seeds or any(value <= 0 for value in counts):
        raise SystemExit("seeds must be unique/nonempty and every window count must be positive")
    if struct.pack("!d", np.finfo(np.float64).tiny) != struct.pack("!d", EXPECTED_TINY):
        raise RuntimeError("float64 tiny guard failed")
    import psutil
    process = psutil.Process()
    segments = [("initial_stop", "STOP", args.initial_stop_windows),
                ("forward", "FORWARD", args.forward_windows),
                ("subnormal_stop", "STOP", args.subnormal_stop_windows)]
    segments.extend(("restimulate_" + action.lower(), action, args.action_windows) for action in ACTION_SEQUENCE)
    total = len(args.seeds) * sum(item[2] for item in segments)
    report = {"complete": False, "numericGate": "running", "mode": "LIVE direct persistent controllers",
              "tcpUnityGate": "not measured", "baselineRef": args.baseline_ref, "measurementHead": None,
              "createdUtc": datetime.now(timezone.utc).isoformat(), "command": sys.argv,
              "seeds": args.seeds, "segments": [{"name": name, "action": action, "windows": windows}
                                                   for name, action, windows in segments],
              "pairedWindowsExpected": total, "dtMs": 0.1, "windowMs": 50.0,
              "float64Tiny": EXPECTED_TINY, "rows": [], "initialization": [], "sourceHashes": {},
              "notes": ["AB/BA alternates every paired window; initialization order alternates by seed.",
                        "All numerical controller/simulator comparisons occur after both timed steps.",
                        "BrainFrame performance is captured but excluded from exact frame equality.",
                        "Kernel timers wrap run_window only; controller timings include normal Python setup/readout.",
                        "No Brain server, TCP, Unity, external API, cache deletion, or source rewrite occurs."],
              "nonNumericalFrameExclusions": ["performance"]}
    save_report(args.output, report)
    try:
        report["measurementHead"] = subprocess.check_output(
            ["git", "-c", "safe.directory=" + ROOT.as_posix(), "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
        report["platform"] = platform.platform()
        report["python"] = sys.version
        report["dependencies"] = {name: importlib.metadata.version(name)
                                  for name in ("numpy", "numba", "llvmlite", "psutil")}
        report["environment"] = {name: os.environ.get(name) for name in ("NUMBA_CACHE_DIR", "NUMBA_DISABLE_JIT",
                                                                            "NUMBA_CPU_NAME", "NUMBA_THREADING_LAYER")}
        baseline_directory = args.output.parent / ("baseline-" + args.baseline_ref[:12])
        candidate_lif, candidate_controller_module, candidate_kernels = load_candidate()
        baseline_lif, baseline_controller_module, baseline_kernels, baseline_sources, materialized = load_baseline(
            args.baseline_ref, baseline_directory)
        for name, module in [('lif_kernels.py', candidate_kernels), ('shiu_compatible.py', candidate_lif),
                             ('analog_controller.py', candidate_controller_module)]:
            if Path(module.__file__).resolve() != (ROOT / 'Brain/MaleCNS' / name).resolve():
                raise AssertionError('Candidate module imported from wrong path: ' + str(module.__file__))
        report['loadedKernels'] = {}
        for name in ('run_window', 'update_state_and_extract_fired'):
            current, previous = getattr(candidate_kernels, name), getattr(baseline_kernels, name)
            if current is previous or getattr(candidate_lif, name) is not current or getattr(baseline_lif, name) is not previous:
                raise AssertionError('Candidate/baseline kernel binding is not isolated: ' + name)
            if Path(current.py_func.__code__.co_filename).resolve() != (ROOT / SOURCE_FILES[0]).resolve():
                raise AssertionError('Candidate code object is not the working-tree source')
            if Path(previous.py_func.__code__.co_filename).resolve() != materialized[SOURCE_FILES[0]].resolve():
                raise AssertionError('Baseline code object is not the pinned snapshot')
            report['loadedKernels'][name] = dict(candidate=current.py_func.__code__.co_filename,
                baseline=previous.py_func.__code__.co_filename, distinct=True)
        report["sourceHashes"] = {"baseline": {path: sha256_bytes(value) for path, value in baseline_sources.items()},
                                  "candidate": {path: sha256_file(ROOT / path) for path in SOURCE_FILES},
                                  "validator": sha256_file(Path(__file__))}
        report["baselineMaterialization"] = {path: str(target.resolve()) for path, target in materialized.items()}
        report["config"] = {"path": str(args.config.resolve()), "sha256": sha256_file(args.config)}
        report["graph"] = {"path": str(args.graph.resolve()), "sha256": {
            name: sha256_file(args.graph / name) for name in ("body_ids.npy", "indptr.npy", "targets.npy", "weights.npy")}}
        baseline_kernel_sample = install_kernel_timer(baseline_lif, baseline_kernels)
        candidate_kernel_sample = install_kernel_timer(candidate_lif, candidate_kernels)
        pair_index = 0
        for seed_index, seed in enumerate(args.seeds):
            arms = {"baseline": baseline_controller_module.MaleCNSAnalogController,
                    "candidate": candidate_controller_module.MaleCNSAnalogController}
            initialization_order = ("baseline", "candidate") if seed_index % 2 == 0 else ("candidate", "baseline")
            controllers = {}
            for label in initialization_order:
                controller, timing = timed_call(lambda cls=arms[label]: cls(args.graph, args.config, seed, 50.0).initialize(), process)
                add_count_capture(controller)
                controllers[label] = controller
                report["initialization"].append({"seed": seed, "arm": label, **timing,
                                                 "controllerInitializationMs": controller.initialization_ms})
            baseline, candidate = controllers["baseline"], controllers["candidate"]
            for name in ("ids", "inputs", "dns", "observed", "groups", "baseline"):
                assert_exact(getattr(baseline, name), getattr(candidate, name), "initialized." + name)
            compare_simulations(baseline.sim, candidate.sim)
            report["N"], report["E"], report["observedCount"] = len(baseline.ids), len(baseline.sim.post), len(baseline.observed)
            for segment_index, (segment_name, action, windows) in enumerate(segments):
                baseline.set_action(action)
                candidate.set_action(action)
                for window_index in range(windows):
                    order = ("baseline", "candidate") if pair_index % 2 == 0 else ("candidate", "baseline")
                    frames, timings, kernel = {}, {}, {}
                    for label in order:
                        controller = controllers[label]
                        frames[label], timings[label] = timed_call(controller.step, process)
                        kernel[label] = dict(baseline_kernel_sample if label == "baseline" else candidate_kernel_sample)
                    compare_simulations(baseline.sim, candidate.sim)
                    assert_exact(baseline.validation_counts, candidate.validation_counts, "count")
                    assert_exact(baseline.rng.bit_generator.state, candidate.rng.bit_generator.state, "RNG")
                    assert_exact(vars(baseline.decoder) if baseline.decoder else None,
                                 vars(candidate.decoder) if candidate.decoder else None, "decoder")
                    assert_exact(numerical_frame(frames["baseline"]), numerical_frame(frames["candidate"]), "BrainFrame")
                    state_hash = state_digest(baseline)
                    count_hash = sha256_bytes(baseline.validation_counts.tobytes())
                    row = {"seed": seed, "segment": segment_name, "segmentIndex": segment_index, "action": action,
                           "windowIndex": window_index, "pairIndex": pair_index, "order": list(order), "exact": True,
                           "tick": baseline.sim.tick, "stateSha256": state_hash, "pendingSha256": pending_digest(baseline.sim),
                           "countSha256": count_hash, "rngSha256": rng_digest(baseline),
                           "subnormalGCount": subnormal_count(baseline.sim.g),
                           "gNonzeroCount": int(np.count_nonzero(baseline.sim.g)),
                           "totalSpikeCount": int(baseline.validation_counts.sum()), "timing": timings, "kernel": kernel,
                           "baselineFramePerformance": frames["baseline"]["performance"],
                           "candidateFramePerformance": frames["candidate"]["performance"]}
                    row.update(stable_conductance_statistics(baseline.sim))
                    report["rows"].append(row)
                    pair_index += 1
                    save_report(args.output, report)
                print(f"seed={seed} segment={segment_name} windows={windows} exact", flush=True)
            del controllers
        report["performanceSummary"] = {label: summary(report["rows"], label) for label in ("baseline", "candidate")}
        report["complete"], report["numericGate"] = True, "pass"
        save_report(args.output, report)
        print(str(args.output.resolve()), flush=True)
        return 0
    except Exception as error:
        report["numericGate"] = "failed or incomplete"
        report["failure"] = {"type": type(error).__name__, "message": str(error), "traceback": traceback.format_exc()}
        save_report(args.output, report)
        raise


if __name__ == "__main__":
    raise SystemExit(main())
