"""Paired LIVE simulation validation; no TCP/Unity, replay, or mock substitution.

Run only with an exclusive measurement slot. Numerical comparisons occur outside
the timed controller calls. Importing this module does not load the full graph.
For the compiled-window change, prefer validate_malecns_window_compiled.py: it
adds the pre-window baseline and LLVM inspection of all executed window kernels.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib
import importlib.metadata
import json
import platform
import re
import struct
import subprocess
import sys
import time
import traceback
import types
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
BASELINE_COMMIT = "add036414f262c8f35dd289d42bc150e7d699525"
SOURCE_FILES = ("Brain/MaleCNS/shiu_compatible.py", "Brain/MaleCNS/analog_controller.py")
SEGMENTS = ("STOP", "FORWARD", "TURN_R", "TURN_L", "FORWARD_R", "FORWARD_L", "STOP")


def git_source(path):
    return subprocess.check_output(
        ["git", "-c", "safe.directory=" + ROOT.as_posix(), "show", BASELINE_COMMIT + ":" + path],
        cwd=ROOT,
    )


def load_implementations():
    """Load unchanged pinned sources, never synthesize a historical algorithm."""
    sys.path.insert(0, str(ROOT / "Brain/MaleCNS"))
    candidate_lif = importlib.import_module("shiu_compatible")
    candidate_controller = importlib.import_module("analog_controller")
    sources = {path: git_source(path) for path in SOURCE_FILES}
    reference_lif = types.ModuleType("compiled_validation_reference_lif")
    reference_lif.__file__ = str(ROOT / SOURCE_FILES[0])
    exec(compile(sources[SOURCE_FILES[0]], "<pinned-lif-" + BASELINE_COMMIT + ">", "exec"),
         reference_lif.__dict__)
    reference_controller = types.ModuleType("compiled_validation_reference_controller")
    reference_controller.__file__ = str(ROOT / SOURCE_FILES[1])
    exec(compile(sources[SOURCE_FILES[1]], "<pinned-controller-" + BASELINE_COMMIT + ">", "exec"),
         reference_controller.__dict__)
    reference_controller.MaleCNSShiuCompatibleLIF = reference_lif.MaleCNSShiuCompatibleLIF
    return (reference_lif.MaleCNSShiuCompatibleLIF, candidate_lif.MaleCNSShiuCompatibleLIF,
            reference_controller.MaleCNSAnalogController, candidate_controller.MaleCNSAnalogController,
            sources)


def assert_exact(a, b, label="value"):
    """Compare finite IEEE bits, including signed zero, and ordered containers."""
    if isinstance(a, np.ndarray):
        if not isinstance(b, np.ndarray) or a.shape != b.shape or a.dtype != b.dtype:
            raise AssertionError(label + ": array shape/dtype mismatch")
        if np.issubdtype(a.dtype, np.floating):
            if not np.isfinite(a).all() or not np.isfinite(b).all():
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
        for index, (x, y) in enumerate(zip(a, b)):
            assert_exact(x, y, label + "[" + str(index) + "]")
    elif isinstance(a, (float, np.floating)):
        if not np.isfinite(a) or not np.isfinite(b):
            raise AssertionError(label + ": nonfinite scalar")
        if struct.pack("!d", float(a)) != struct.pack("!d", float(b)):
            raise AssertionError(label + ": float bit mismatch")
    elif a != b:
        raise AssertionError(label + ": value mismatch")


def compare_simulations(a, b):
    for name in ("v", "g", "last", "rfc", "tick", "pending", "dt"):
        assert_exact(getattr(a, name), getattr(b, name), "sim." + name)


def sha256_file(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def state_digest(controller):
    h = hashlib.sha256()
    for name in ("v", "g", "last", "rfc"):
        value = getattr(controller.sim, name)
        h.update(name.encode())
        h.update(value.dtype.str.encode())
        h.update(value.tobytes())
    h.update(json.dumps([controller.sim.tick, controller.sim.pending], separators=(",", ":")).encode())
    return h.hexdigest()


def attach_count_capture(controller):
    """Observe either API; wrapper frequency follows each controller's path."""
    for name in ("step", "step_window"):
        if not hasattr(controller.sim, name):
            continue
        def capture(*args, _original=getattr(controller.sim, name), **kwargs):
            result = _original(*args, **kwargs)
            controller.validation_counts = result[0]
            return result
        setattr(controller.sim, name, capture)


def timed_call(call, process):
    before_rss = process.memory_info().rss
    cpu, wall = time.process_time(), time.perf_counter()
    result = call()
    wall_ms = (time.perf_counter() - wall) * 1000
    cpu_ms = (time.process_time() - cpu) * 1000
    return result, {"wallMs": wall_ms, "processCpuMs": cpu_ms,
                    "rssBeforeBytes": before_rss, "rssAfterBytes": process.memory_info().rss}


def save_report(path, report):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
    temporary.replace(path)


def make_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/windows-malecns/compiled/equivalence.json")
    parser.add_argument("--graph", type=Path, default=ROOT / "artifacts/neuron_checkpoint")
    parser.add_argument("--config", type=Path, default=ROOT / "Brain/MaleCNS/config/analog_temporal_v1.json")
    parser.add_argument("--seeds", type=int, nargs="+", default=[20270101, 20270102, 20270103])
    parser.add_argument("--stop-max-windows", type=int, default=64,
                        help="Maximum final STOP windows, including its initial eight (default 64)")
    return parser


def main(argv=None):
    args = make_parser().parse_args(argv)
    if len(set(args.seeds)) != len(args.seeds):
        raise SystemExit("Seeds must be independent (no duplicates)")
    if args.stop_max_windows < 8:
        raise SystemExit("--stop-max-windows must be at least eight")
    import psutil
    process = psutil.Process()
    report = {"complete": False, "numericGate": "running", "baselineCommit": BASELINE_COMMIT,
              "mode": "LIVE direct simulation", "tcpUnityGate": "not measured",
              "seeds": args.seeds, "segments": list(SEGMENTS), "windowsPerSegment": 8,
              "requiredBasePairs": len(args.seeds) * len(SEGMENTS) * 8,
              "dtMs": 0.1, "windowMs": 50, "command": sys.argv,
              "python": sys.version, "platform": platform.platform(), "versions": {},
              "rows": [], "initialization": [], "stopRecovery": [],
              "measurementNotes": ["AB/BA alternates globally across paired windows.",
                  "Count-reference wrapper frequency follows the controller: 500 old step entries or one new step_window entry.",
                  "Array/decoder/RNG/frame comparisons, hashes and JSON saves are outside timed calls.",
                  "RSS is process RSS with both controllers resident; samples are not peak RSS.",
                  "Cold first constructor/JIT is measured separately from warm full-graph initialization.",
                  "Numba disk cache may be populated; first call is cold in this process, not guaranteed cache-cold.",
                  "This legacy validator inspects only the neuron-update kernel; use validate_malecns_window_compiled.py for all window kernels and pre-window baseline.",
                  "All BrainFrame fields except performance must match unless explicitly classified below.",
                  "Final STOP convergence: abs(forward), abs(turn) <= .02 for three consecutive windows.",
                  "Exact-zero motor and whole-network silence are recorded separately, not acceptance requirements."],
              "nonNumericalFrameExclusions": ["performance"]}
    save_report(args.output, report)
    try:
        for package in ("numpy", "numba", "llvmlite", "psutil"):
            report["versions"][package] = importlib.metadata.version(package)
        old_lif, new_lif, old_controller, new_controller, sources = load_implementations()
        report["measurementHead"] = subprocess.check_output(
            ["git", "-c", "safe.directory=" + ROOT.as_posix(), "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
        report["baselineNote"] = "Pinned optimization baseline retained; measurement HEAD includes independent optional visualization support. Full graph uses visualization_atlas=None."
        report["sourceHashes"] = {"baseline": {path: hashlib.sha256(source).hexdigest()
                                                   for path, source in sources.items()},
                                  "candidate": {path: sha256_file(ROOT / path) for path in SOURCE_FILES}}
        for path in ("Brain/MaleCNS/lif_kernels.py", "Brain/MaleCNS/analog_motor_decoder.py",
                     "Brain/MaleCNS/temporal_motor_decoder.py", "Brain/MaleCNS/neural_visualization.py",
                     "tools/test_malecns_compiled.py", "tools/validate_malecns_compiled.py"):
            report["sourceHashes"]["candidate"][path] = sha256_file(ROOT / path)
        report["config"] = {"path": str(args.config.resolve()), "sha256": sha256_file(args.config)}
        report["graph"] = {"path": str(args.graph.resolve()), "files": {
            name: sha256_file(args.graph / name)
            for name in ("body_ids.npy", "indptr.npy", "targets.npy", "weights.npy")}}
        for label, cls in (("baseline", old_lif), ("candidate", new_lif)):
            # Same dtypes/signature as production; no full-graph step in this phase.
            def cold():
                sim = cls(2, np.zeros(3, dtype=np.int64), np.empty(0, dtype=np.int64),
                          np.empty(0, dtype=np.float64))
                sim.step(1)
                return sim
            _, timing = timed_call(cold, process)
            report.setdefault("firstProcessLifCall", {})[label] = timing
        # Recompile the actual dispatcher once to expose LLVM even when the first
        # call loaded a disk cache. This diagnostic compile is outside warm timing.
        kernel = importlib.import_module("lif_kernels").update_state_and_extract_fired
        _, report["diagnosticRecompile"] = timed_call(kernel.recompile, process)
        report["compiledKernel"] = {"nopythonSignatures": [str(x) for x in kernel.nopython_signatures],
                                    "targetOptions": kernel.targetoptions, "variants": []}
        for signature in kernel.signatures:
            llvm, assembly = kernel.inspect_llvm(signature), kernel.inspect_asm(signature)
            flags = [line.strip() for line in llvm.splitlines()
                     if re.search(r"\b(?:fadd|fsub|fmul|fdiv|fcmp)\s+(?:(?:nnan|ninf|nsz|arcp|afn)\s+)*(?:fast|reassoc|contract)\b", line)]
            fma = [line.strip() for line in assembly.splitlines()
                   if re.search(r"\b(?:v?f(?:madd|msub|nmadd|nmsub)\w*|fmadd|fmsub)\b", line)]
            intrinsics = [line.strip() for line in llvm.splitlines() if "llvm.fma" in line or "llvm.fmuladd" in line]
            report["compiledKernel"]["variants"].append({"signature": str(signature),
                "llvmSha256": hashlib.sha256(llvm.encode()).hexdigest(),
                "assemblySha256": hashlib.sha256(assembly.encode()).hexdigest(),
                "unsafeFloatingFlags": flags, "fmaInstructions": fma, "fmaIntrinsics": intrinsics})
            if flags or fma or intrinsics:
                raise AssertionError("compiled kernel contains relaxed floating instructions")
        if not kernel.nopython_signatures:
            raise AssertionError("kernel did not compile in nopython mode")
        save_report(args.output, report)
        pair_index = 0
        for seed in args.seeds:
            controllers = {}
            init_order = (("baseline", old_controller), ("candidate", new_controller))
            if args.seeds.index(seed) % 2:
                init_order = tuple(reversed(init_order))
            for label, cls in init_order:
                c, timing = timed_call(lambda: cls(args.graph, args.config, seed, 50).initialize(), process)
                controllers[label] = c
                attach_count_capture(c)
                report["initialization"].append({"seed": seed, "arm": label, **timing,
                                                 "controllerInitializationMs": c.initialization_ms})
            a, b = controllers["baseline"], controllers["candidate"]
            compare_simulations(a.sim, b.sim)
            for name in ("ids", "inputs", "dns", "observed", "groups", "baseline"):
                assert_exact(getattr(a, name), getattr(b, name), "initialized." + name)
            report["N"], report["E"] = len(a.ids), len(a.sim.post)
            report["observedCount"] = len(a.observed)
            for segment, action in enumerate(SEGMENTS):
                a.set_action(action)
                b.set_action(action)
                near_streak = 0
                index = 0
                final_stop = segment == len(SEGMENTS) - 1
                while index < 8 or (final_stop and near_streak < 3 and index < args.stop_max_windows):
                    order = ("baseline", "candidate") if pair_index % 2 == 0 else ("candidate", "baseline")
                    frames, timings = {}, {}
                    for label in order:
                        frames[label], timings[label] = timed_call(controllers[label].step, process)
                    compare_simulations(a.sim, b.sim)
                    assert_exact(a.validation_counts, b.validation_counts, "count")
                    assert_exact(a.rng.bit_generator.state, b.rng.bit_generator.state, "rng")
                    assert_exact(vars(a.decoder) if a.decoder else None,
                                 vars(b.decoder) if b.decoder else None, "decoder")
                    numerical_frames = copy.deepcopy(frames)
                    for frame in numerical_frames.values():
                        frame.pop("performance")
                    assert_exact(numerical_frames["baseline"], numerical_frames["candidate"], "BrainFrame")
                    motor = frames["baseline"]["motor"]
                    near_zero = all(abs(value) <= .02 for value in motor.values())
                    exact_zero = all(value == 0 for value in motor.values())
                    near_streak = near_streak + 1 if near_zero else 0
                    report["rows"].append({"seed": seed, "segment": segment, "action": action,
                        "index": index, "pairIndex": pair_index, "order": list(order),
                        "extension": index >= 8, "exact": True, "tick": a.sim.tick,
                        "motor": motor, "nearZeroMotor": near_zero, "exactZeroMotor": exact_zero,
                        "allNetworkCountZero": not bool(np.any(a.validation_counts)),
                        "totalSpikeCount": int(a.validation_counts.sum()),
                        "stateSha256": state_digest(a), "countSha256": hashlib.sha256(a.validation_counts.tobytes()).hexdigest(),
                        "baseline": timings["baseline"], "candidate": timings["candidate"],
                        "baselineFramePerformance": frames["baseline"]["performance"],
                        "candidateFramePerformance": frames["candidate"]["performance"]})
                    index += 1
                    pair_index += 1
                    save_report(args.output, report)
                if action == "STOP":
                    report["stopRecovery"].append({"seed": seed, "segment": segment,
                        "windows": index, "nearZeroConverged": near_streak >= 3,
                        "nearZeroConsecutiveWindows": near_streak, "lastMotorExactlyZero": exact_zero,
                        "maximumWindows": args.stop_max_windows if final_stop else 8})
                print(f"seed={seed} segment={segment} action={action} windows={index} exact", flush=True)
            # Drop closures as well as controller references before the next seed.
            for controller in controllers.values():
                for name in ("step", "step_window"):
                    if name in vars(controller.sim):
                        delattr(controller.sim, name)
            del controllers, a, b, c, controller
        report["complete"] = True
        report["numericGate"] = "pass"
        report["stopRecoveryGate"] = "pass" if all(x["nearZeroConverged"] for x in report["stopRecovery"]) else "not converged"
        report["performanceSummary"] = {}
        for label in ("baseline", "candidate"):
            samples = np.array([row[label]["wallMs"] for row in report["rows"]])
            report["performanceSummary"][label] = {"n": len(samples), "meanMs": float(samples.mean()),
                "p50Ms": float(np.percentile(samples, 50)), "p95Ms": float(np.percentile(samples, 95)),
                "observedMaxMs": float(samples.max())}
        report["performanceGate"] = "not evaluated; separate from numerical equality and TCP/Unity gate"
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
