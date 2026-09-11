"""Verify Brian2's Cython runtime backend and measure cache reuse."""

import argparse
import importlib.metadata as metadata
import json
import os
import platform
import subprocess
import time
import traceback
from pathlib import Path

from brian2 import Network, NeuronGroup, ms, prefs, run, start_scope

from poc_config import REPO_ROOT


def _version(name: str) -> str | None:
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return None


def _command_version(command: list[str]) -> str | None:
    try:
        return subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def run_test(output_path: Path, cache_dir: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cache_dir.mkdir(parents=True, exist_ok=True)
    result = {
        "protocolVersion": 1,
        "backend": "cython",
        "environment": {
            "platform": platform.platform(),
            "machine": platform.machine(),
            "python": platform.python_version(),
            "brian2": _version("brian2"),
            "cython": _version("Cython"),
            "numpy": _version("numpy"),
            "setuptools": _version("setuptools"),
            "cc": os.environ.get("CC"),
            "cxx": os.environ.get("CXX"),
            "macosx_deployment_target": os.environ.get("MACOSX_DEPLOYMENT_TARGET"),
            "clang": _command_version(["/usr/bin/clang", "--version"]),
            "clangxx": _command_version(["/usr/bin/clang++", "--version"]),
        },
        "cache_dir": str(cache_dir.resolve()),
    }
    started = time.perf_counter()
    try:
        prefs.codegen.target = "cython"
        prefs.codegen.runtime.cython.cache_dir = str(cache_dir.resolve())
        start_scope()
        group = NeuronGroup(
            1,
            "dv/dt = -v/(10*ms) : 1",
            method="euler",
        )
        network = Network(group)
        first_started = time.perf_counter()
        network.run(1 * ms)
        first_seconds = time.perf_counter() - first_started
        second_started = time.perf_counter()
        network.run(1 * ms)
        second_seconds = time.perf_counter() - second_started
        result.update(
            {
                "success": True,
                "first_run_seconds": first_seconds,
                "second_run_seconds": second_seconds,
                "total_process_seconds": time.perf_counter() - started,
            }
        )
        print("Cython OK")
    except Exception as exc:
        result.update(
            {
                "success": False,
                "error_type": type(exc).__name__,
                "error": str(exc),
                "traceback": traceback.format_exc(),
                "total_process_seconds": time.perf_counter() - started,
            }
        )
        output_path.write_text(json.dumps(result, indent=2) + "\n")
        raise
    output_path.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    print(f"result written: {output_path}")
    return output_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        default=str(REPO_ROOT / "results" / "codex_run" / "cython_smoke_test.json"),
    )
    parser.add_argument(
        "--cache-dir",
        default=str(REPO_ROOT / "results" / "codex_run" / "cython_cache"),
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    run_test(Path(args.output), Path(args.cache_dir))
