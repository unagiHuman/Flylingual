"""Three-arm LIVE numerical/performance comparison for compiled LIF windows.

Historical NumPy, pinned pre-window compiled snapshot, and current production
each own their original controller and simulator classes. No TCP/Unity gate.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import importlib.metadata
import importlib.util
import json
import platform
import re
import subprocess
import sys
import traceback
import types
from pathlib import Path

import numpy as np

from validate_malecns_compiled import (ROOT, BASELINE_COMMIT, SEGMENTS, assert_exact,
    attach_count_capture, compare_simulations, load_implementations, save_report, sha256_file, state_digest, timed_call)

DEFAULT_SNAPSHOT = ROOT / "artifacts/windows-malecns/window-compiled/baseline"
WINDOW_BASELINE_COMMIT = "88d117d02dc72710de893590811669bb9fccc2d0"
WINDOW_BASELINE_HASHES = {
    "shiu_compatible.py": "323b968fe5bfd692d0deee80031d1a728367163760446a1b0763fccd9a3758c0",
    "lif_kernels.py": "0cec8979a0147743a478403260211d83400cd6ba7f90e0e475e6288de441b7d8",
    "analog_controller.py": "f3362d6b66c14c64415b9e021f4ef57839df7de9852f86c4cd73ecd8e4752745",
}


def load_snapshot(directory=None):
    """Verify bytes first; bind all three snapshot modules without global swaps."""
    if directory is None:
        # Materialize unchanged git blobs so Numba has a genuine cache locator.
        # The original working-tree snapshot and its manifest are never replaced.
        directory = ROOT / "artifacts/windows-malecns/window-compiled" / ("reference-" + WINDOW_BASELINE_COMMIT[:7])
        directory.mkdir(parents=True, exist_ok=True)
        for filename, expected in WINDOW_BASELINE_HASHES.items():
            source = subprocess.check_output(["git", "-c", "safe.directory=" + ROOT.as_posix(), "show",
                WINDOW_BASELINE_COMMIT + ":Brain/MaleCNS/" + filename], cwd=ROOT)
            if hashlib.sha256(source).hexdigest() != expected:
                raise AssertionError("Pinned pre-window source hash mismatch: " + filename)
            target = directory / filename
            if not target.exists():
                target.write_bytes(source)
        manifest = {"source": "pinned commit matching original working-tree snapshot bytes",
                    "head": WINDOW_BASELINE_COMMIT, "snapshotHead": "4f703017902fc1ac2ca90e1d637c20f2735f78c1",
                    "sha256": WINDOW_BASELINE_HASHES}
    else:
        directory = Path(directory)
        manifest = json.loads((directory / "snapshot.json").read_text(encoding="utf-8-sig"))
        if manifest["sha256"] != WINDOW_BASELINE_HASHES:
            raise AssertionError("Snapshot must match pinned pre-window baseline hashes")
    manifest = {**manifest, "path": str(directory.resolve())}
    for filename, expected in manifest["sha256"].items():
        if sha256_file(directory / filename) != expected:
            raise AssertionError("Snapshot source changed: " + filename)
    sys.path.insert(0, str(ROOT / "Brain/MaleCNS"))
    name = "window_validation_snapshot_kernels"
    spec = importlib.util.spec_from_file_location(name, directory / "lif_kernels.py")
    kernels = importlib.util.module_from_spec(spec)
    sys.modules[name] = kernels
    spec.loader.exec_module(kernels)
    lif = types.ModuleType("window_validation_snapshot_lif")
    lif.__file__ = str(ROOT / "Brain/MaleCNS/shiu_compatible.py")
    exec(compile((directory / "shiu_compatible.py").read_bytes(), str(directory / "shiu_compatible.py"), "exec"), lif.__dict__)
    lif.update_state_and_extract_fired = kernels.update_state_and_extract_fired
    controller = types.ModuleType("window_validation_snapshot_controller")
    controller.__file__ = str(ROOT / "Brain/MaleCNS/analog_controller.py")
    exec(compile((directory / "analog_controller.py").read_bytes(), str(directory / "analog_controller.py"), "exec"), controller.__dict__)
    controller.MaleCNSShiuCompatibleLIF = lif.MaleCNSShiuCompatibleLIF
    return lif.MaleCNSShiuCompatibleLIF, controller.MaleCNSAnalogController, kernels, manifest


def pack_events(start_tick, ticks, events):
    offsets, indices = [0], []
    for tick in range(start_tick, start_tick + ticks):
        indices.extend(events.get(tick, ()))
        offsets.append(len(indices))
    return np.asarray(offsets, dtype=np.int64), np.asarray(indices, dtype=np.int64)


def attach_window_count_capture(controller):
    # One wrapper per simulation entry point; old controllers enter 500 times,
    # new controllers once. Record this instrumentation difference explicitly.
    attach_count_capture(controller)


def inspect_kernels(module, output_directory):
    """Inspect actual production dispatchers after all graph signatures exist."""
    findings = {}
    for name, kernel in vars(module).items():
        if not hasattr(kernel, "nopython_signatures") or not kernel.signatures:
            continue
        kernel.recompile()  # cached dispatchers otherwise do not expose LLVM
        entry = {"nopythonSignatures": [str(x) for x in kernel.nopython_signatures],
                 "targetOptions": kernel.targetoptions, "variants": []}
        for index, signature in enumerate(kernel.signatures):
            llvm, assembly = kernel.inspect_llvm(signature), kernel.inspect_asm(signature)
            floating = [line.strip() for line in llvm.splitlines()
                        if re.search(r"\b(?:fadd|fsub|fmul|fdiv|fcmp)\b.*\b(?:fast|reassoc|contract)\b", line)]
            fma_llvm = [line.strip() for line in llvm.splitlines() if "llvm.fma" in line or "llvm.fmuladd" in line]
            fma_asm = [line.strip() for line in assembly.splitlines()
                       if re.search(r"\b(?:v?f(?:madd|msub|nmadd|nmsub)\w*|fmadd|fmsub)\b", line)]
            prefix = output_directory / (name + "-" + str(index))
            prefix.with_suffix(".ll").write_text(llvm, encoding="utf-8")
            prefix.with_suffix(".asm").write_text(assembly, encoding="utf-8")
            entry["variants"].append({"signature": str(signature), "unsafeFloatingFlags": floating,
                "fmaIntrinsics": fma_llvm, "fmaInstructions": fma_asm,
                "llvmSha256": hashlib.sha256(llvm.encode()).hexdigest(),
                "assemblySha256": hashlib.sha256(assembly.encode()).hexdigest()})
            if floating or fma_llvm or fma_asm:
                raise AssertionError("Relaxed floating instructions in " + name)
        if not entry["nopythonSignatures"]:
            raise AssertionError("No nopython signature for " + name)
        findings[name] = entry
    return findings


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/windows-malecns/window-compiled/equivalence.json")
    parser.add_argument("--snapshot-dir", type=Path,
                        help="Optional original snapshot directory; default loads fixed commit " + WINDOW_BASELINE_COMMIT)
    parser.add_argument("--graph", type=Path, default=ROOT / "artifacts/neuron_checkpoint")
    parser.add_argument("--config", type=Path, default=ROOT / "Brain/MaleCNS/config/analog_temporal_v1.json")
    parser.add_argument("--seeds", type=int, nargs="+", default=[20270101, 20270102, 20270103])
    parser.add_argument("--stop-max-windows", type=int, default=64)
    args = parser.parse_args(argv)
    if len(set(args.seeds)) != len(args.seeds) or args.stop_max_windows < 8:
        parser.error("unique seeds and --stop-max-windows >= 8 required")
    import psutil
    process = psutil.Process()
    report = {"complete": False, "numericGate": "running", "mode": "LIVE direct simulation",
        "tcpUnityGate": "not measured", "command": sys.argv, "pid": process.pid,
        "historicalCommit": BASELINE_COMMIT, "seeds": args.seeds, "dtMs": .1, "windowMs": 50.,
        "segments": list(SEGMENTS), "windowsPerSegment": 8,
        "requiredBaseTriples": len(args.seeds) * 56, "rows": [], "initialization": [], "stopRecovery": [],
        "python": sys.version, "platform": platform.platform(),
        "versions": {name: importlib.metadata.version(name) for name in ("numpy", "numba", "llvmlite", "psutil")},
        "notes": ["ABC/CBA alternation reverses both baseline/candidate pair orders each window.",
            "Historical and snapshot controllers retain their original simulation entry path.",
            "Timed call includes count-reference wrapper: 500 old step calls versus one new step_window call.",
            "Source/data/config hashing, numerical comparisons, report serialization and LLVM inspection are untimed.",
            "RSS samples are whole process with three resident arms, not per-arm or peak RSS.",
            "First process call may load Numba disk cache. Graph initialization includes any new-signature compilation.",
            "STOP near-zero: abs(forward),abs(turn)<=.02 for 3 windows; exact zero recorded separately.",
            "No inference of general bit equivalence or guaranteed latency from these finite samples."],
        "nonNumericalFrameExclusions": ["performance"]}
    save_report(args.output, report)
    try:
        old_lif, new_lif, old_controller, new_controller, historical_sources = load_implementations()
        snapshot_lif, snapshot_controller, _, snapshot_manifest = load_snapshot(args.snapshot_dir)
        report["snapshot"] = snapshot_manifest
        report["measurementHead"] = subprocess.check_output(["git", "-c", "safe.directory=" + ROOT.as_posix(),
            "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
        paths = ["Brain/MaleCNS/" + name for name in ("shiu_compatible.py", "lif_kernels.py", "analog_controller.py",
            "analog_motor_decoder.py", "temporal_motor_decoder.py", "neural_visualization.py")]
        paths += ["tools/" + name for name in ("test_malecns_compiled.py", "validate_malecns_compiled.py",
            "test_malecns_window_compiled.py", "validate_malecns_window_compiled.py")]
        report["sourceHashes"] = {"candidate": {path: sha256_file(ROOT / path) for path in paths},
            "historical": {path: hashlib.sha256(source).hexdigest() for path, source in historical_sources.items()}}
        report["config"] = {"path": str(args.config.resolve()), "sha256": sha256_file(args.config)}
        report["graph"] = {"path": str(args.graph.resolve()), "sha256": {name: sha256_file(args.graph / name)
            for name in ("body_ids.npy", "indptr.npy", "targets.npy", "weights.npy")}}
        report["firstProcessCall"] = {}
        for label, cls in (("historical", old_lif), ("snapshot", snapshot_lif), ("candidate", new_lif)):
            def first():
                sim = cls(2, np.zeros(3, dtype=np.int64), np.empty(0, dtype=np.int64), np.empty(0, dtype=np.float64))
                sim.step(1)
                if hasattr(sim, "step_window"):
                    sim.step_window(1, np.array([0, 0], dtype=np.int64), np.empty(0, dtype=np.int64), np.array([0], dtype=np.int64))
                return sim
            _, timing = timed_call(first, process)
            report["firstProcessCall"][label] = timing
        arms = {"historical": old_controller, "snapshot": snapshot_controller, "candidate": new_controller}
        triple = 0
        for seed_index, seed in enumerate(args.seeds):
            controllers = {}
            labels = list(arms) if seed_index % 2 == 0 else list(reversed(arms))
            for label in labels:
                controller, timing = timed_call(lambda: arms[label](args.graph, args.config, seed, 50.).initialize(), process)
                controllers[label] = controller
                attach_window_count_capture(controller)
                report["initialization"].append({"arm": label, "seed": seed, **timing,
                    "controllerInitializationMs": controller.initialization_ms})
            reference = controllers["historical"]
            report["N"], report["E"] = len(reference.ids), len(reference.sim.post)
            report["observedCount"] = len(reference.observed)
            for label in ("snapshot", "candidate"):
                compare_simulations(reference.sim, controllers[label].sim)
                for name in ("ids", "inputs", "dns", "observed", "groups", "baseline"):
                    assert_exact(getattr(reference, name), getattr(controllers[label], name), label + ".initialized." + name)
            for segment, action in enumerate(SEGMENTS):
                for controller in controllers.values():
                    controller.set_action(action)
                index, near_streak = 0, 0
                final_stop = segment == len(SEGMENTS) - 1
                while index < 8 or (final_stop and near_streak < 3 and index < args.stop_max_windows):
                    order = list(arms) if triple % 2 == 0 else list(reversed(arms))
                    report["activeWindow"] = {"seed": seed, "segment": segment, "action": action, "index": index}
                    frames, timing = {}, {}
                    for label in order:
                        frames[label], timing[label] = timed_call(controllers[label].step, process)
                    performance = {label: frame.pop("performance") for label, frame in frames.items()}
                    for label in ("snapshot", "candidate"):
                        other = controllers[label]
                        compare_simulations(reference.sim, other.sim)
                        assert_exact(reference.validation_counts, other.validation_counts, label + ".count")
                        assert_exact(reference.rng.bit_generator.state, other.rng.bit_generator.state, label + ".RNG")
                        assert_exact(vars(reference.decoder) if reference.decoder else None,
                                     vars(other.decoder) if other.decoder else None, label + ".decoder")
                        assert_exact(frames["historical"], frames[label], label + ".BrainFrame")
                    motor = frames["candidate"]["motor"]
                    near = all(abs(value) <= .02 for value in motor.values())
                    near_streak = near_streak + 1 if near else 0
                    report["rows"].append({"seed": seed, "segment": segment, "action": action, "index": index,
                        "triple": triple, "order": order, "extension": index >= 8, "exact": True,
                        "tick": reference.sim.tick, "timing": timing, "framePerformance": performance,
                        "motor": motor, "nearZeroMotor": near, "exactZeroMotor": all(x == 0 for x in motor.values()),
                        "totalSpikeCount": int(reference.validation_counts.sum()),
                        "stateSha256": state_digest(reference),
                        "countSha256": hashlib.sha256(reference.validation_counts.tobytes()).hexdigest()})
                    triple += 1
                    index += 1
                    save_report(args.output, report)
                if action == "STOP":
                    report["stopRecovery"].append({"seed": seed, "segment": segment, "windows": index,
                        "nearZeroConverged": near_streak >= 3, "nearZeroConsecutiveWindows": near_streak})
                print(f"seed={seed} action={action} windows={index} exact across three arms", flush=True)
            for controller in controllers.values():
                for name in ("step", "step_window"):
                    if name in vars(controller.sim):
                        delattr(controller.sim, name)
            del controllers, reference, other, controller
        report["performanceSummary"] = {}
        for label in arms:
            samples = np.array([row["timing"][label]["wallMs"] for row in report["rows"]])
            cpu = np.array([row["timing"][label]["processCpuMs"] for row in report["rows"]])
            report["performanceSummary"][label] = {"n": len(samples), "meanMs": float(samples.mean()),
                "medianMs": float(np.median(samples)), "p95Ms": float(np.percentile(samples, 95)),
                "observedMaxMs": float(samples.max()), "meanProcessCpuMs": float(cpu.mean())}
        compiler_directory = args.output.parent / "compiler-evidence"
        compiler_directory.mkdir(parents=True, exist_ok=True)
        report["compiledKernels"], report["compilerInspectionTiming"] = timed_call(
            lambda: inspect_kernels(importlib.import_module("lif_kernels"), compiler_directory), process)
        report["complete"], report["numericGate"] = True, "pass"
        report["stopRecoveryGate"] = "pass" if all(item["nearZeroConverged"] for item in report["stopRecovery"]) else "not converged"
        report.pop("activeWindow", None)
        save_report(args.output, report)
        print(json.dumps(report["performanceSummary"], indent=2), flush=True)
        return 0
    except Exception as error:
        report["numericGate"] = "failed or incomplete"
        report["error"] = {"type": type(error).__name__, "message": str(error), "traceback": traceback.format_exc()}
        save_report(args.output, report)
        raise


if __name__ == "__main__":
    raise SystemExit(main())
