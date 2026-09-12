#!/usr/bin/env python3
"""Non-destructive Bridge configuration diagnosis and foreground launcher."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from Runtime.Bridge.config import ConfigError, ROOT, load_config
from Runtime.Bridge.credentials import CredentialError, load_requested_api_key


LOCAL_PROFILES = {"mac-local", "windows-local"}
REMOTE_PROFILES = {"windows-to-mac", "mac-to-windows"}
GRAPH_FILES = ("body_ids.npy", "indptr.npy", "targets.npy", "weights.npy")
SOURCE_FILES = (
    "brain_server_bridge.py",
    "brain_server_analog.py",
    "brain_server_malecns.py",
    "analog_controller.py",
    "neural_visualization.py",
    "analog_motor_decoder.py",
    "game_controller.py",
    "shiu_compatible.py",
    "lif_kernels.py",
    "temporal_motor_decoder.py",
)
READY_PREFIX = "MaleCNS brain server READY at "


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _aggregate_hash(paths: dict[str, Path]) -> str:
    """Match brain_server_bridge.py's canonical filename-to-digest hash."""
    manifest = {name: _sha256(path) for name, path in paths.items()}
    encoded = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _resolved_local_path(value: str | None) -> str | None:
    path = Path(value) if value is not None else ROOT / "Runtime/Config/local.json"
    if not path.is_absolute():
        path = ROOT / path
    return str(path.resolve()) if path.exists() else None


def _cli_overrides(args: argparse.Namespace) -> dict[str, Any]:
    result: dict[str, Any] = {}
    brain: dict[str, Any] = {}
    if args.brain_host is not None:
        brain["host"] = args.brain_host
    if args.brain_port is not None:
        brain["port"] = args.brain_port
    if args.graph is not None:
        brain["graph"] = args.graph
    if args.brain_python is not None:
        brain["python"] = args.brain_python
    if brain:
        result["brain"] = brain
    conversation: dict[str, str] = {}
    if args.conversation is not None:
        conversation["mode"] = args.conversation
    for argument, key in (
        (args.language, "language"),
        (args.voice, "voice"),
        (args.persona, "persona"),
        (args.persona_text, "personaText"),
    ):
        if argument is not None:
            conversation[key] = argument
    if conversation:
        result["conversation"] = conversation
    return result


def _is_local_profile(config: dict[str, Any]) -> bool:
    return config["profile"] in LOCAL_PROFILES


def _doctor(config: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Inspect only local metadata/files; deliberately performs no TCP or API request."""
    errors: list[str] = []
    report: dict[str, Any] = {
        "profile": config["profile"],
        "brainTarget": f"{config['brain']['host']}:{config['brain']['port']}",
        "conversationMode": config["conversation"]["mode"],
        "conversationLanguage": config["conversation"]["language"],
        "conversationVoice": config["conversation"]["voice"],
        "conversationPersona": config["conversation"]["persona"],
        "conversationCustomTextPresent": bool(config["conversation"]["personaText"]),
        "aiohttpAvailable": importlib.util.find_spec("aiohttp") is not None,
        "openAiKeyPresent": bool(os.environ.get("OPENAI_API_KEY")),
        "selectedSource": str(ROOT / "Brain/MaleCNS/brain_server_bridge.py"),
        "networkChecked": False,
    }
    if not report["aiohttpAvailable"]:
        errors.append("aiohttp is not installed")
    if config["conversation"]["mode"] == "live" and not report["openAiKeyPresent"]:
        errors.append("conversation.mode=live requires OPENAI_API_KEY in this process environment")

    source = Path(report["selectedSource"])
    report["sourceExists"] = source.is_file()
    if not source.is_file():
        errors.append(f"Brain launcher source is missing: {source}")

    if not _is_local_profile(config):
        report["graphCheck"] = "skipped: remote profile requires a pre-existing SSH tunnel; it does not manage remote graph data"
        report["tunnelRequired"] = True
        return report, errors

    graph = Path(config["brain"]["graph"])
    report["graphPath"] = str(graph)
    file_report: dict[str, Any] = {}
    for name in GRAPH_FILES:
        path = graph / name
        item: dict[str, Any] = {"exists": path.is_file()}
        if path.is_file():
            item["sha256"] = _sha256(path)
        else:
            errors.append(f"graph file is missing: {path}")
        file_report[name] = item
    report["graphFiles"] = file_report

    manifest_path = ROOT / "Brain/MaleCNS/config/analog_handoff_manifest.json"
    report["graphManifest"] = str(manifest_path)
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            expected_files = manifest.get("graphFiles", {})
            manifest_result: dict[str, Any] = {}
            for name in GRAPH_FILES:
                expected = expected_files.get(name, {}).get("sha256")
                actual = file_report[name].get("sha256")
                matches = isinstance(expected, str) and actual == expected
                manifest_result[name] = {"expectedPresent": isinstance(expected, str), "matches": matches}
                if actual is not None and not matches:
                    errors.append(f"graph checksum does not match manifest: {name}")
            report["manifestChecks"] = manifest_result
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"cannot read graph manifest: {exc}")
    else:
        errors.append(f"graph manifest is missing: {manifest_path}")

    hash_targets = {
        "expectedConfigHash": Path(config["brain"]["config"]),
    }
    expected_checks: dict[str, Any] = {}
    for key, path in hash_targets.items():
        expected = config["brain"][key]
        if expected is None:
            expected_checks[key] = "not configured"
        elif not path.is_file():
            expected_checks[key] = "target missing"
            errors.append(f"{key} target is missing: {path}")
        else:
            matches = _sha256(path).lower() == expected.lower()
            expected_checks[key] = {"matches": matches}
            if not matches:
                errors.append(f"{key} does not match {path}")
    for key, paths in (
        ("expectedGraphHash", {name: graph / name for name in GRAPH_FILES}),
        ("expectedSourceHash", {name: source.parent / name for name in SOURCE_FILES}),
    ):
        expected = config["brain"][key]
        missing = [str(path) for path in paths.values() if not path.is_file()]
        if expected is None:
            expected_checks[key] = "not configured"
        elif missing:
            expected_checks[key] = "target missing"
            errors.append(f"{key} target is missing: {', '.join(missing)}")
        else:
            matches = _aggregate_hash(paths).lower() == expected.lower()
            expected_checks[key] = {"matches": matches}
            if not matches:
                errors.append(f"{key} does not match the Brain aggregate hash")
    report["expectedHashChecks"] = expected_checks
    return report, errors


async def _wait_ready(process: subprocess.Popen[str], host: str, port: int, seconds: float = 30.0) -> None:
    assert process.stdout is not None
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"Brain launcher exited before READY (exit {process.returncode})")
        try:
            line = await asyncio.wait_for(
                asyncio.to_thread(process.stdout.readline), timeout=max(0.05, deadline - time.monotonic())
            )
        except asyncio.TimeoutError:
            break
        if not line:
            continue
        if line.strip() == f"{READY_PREFIX}{host}:{port}":
            return
    raise RuntimeError("Brain launcher did not emit READY within 30 seconds")


def _terminate_owned(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


async def _up(config: dict[str, Any], launch_brain: bool) -> None:
    if config["conversation"]["mode"] == "live" and not os.environ.get("OPENAI_API_KEY"):
        raise ConfigError("conversation.mode=live requires OPENAI_API_KEY; its value is never accepted in config or logs")
    process: subprocess.Popen[str] | None = None
    output_task = None
    try:
        if launch_brain:
            if not _is_local_profile(config):
                raise ConfigError("--launch-brain is only allowed for mac-local or windows-local; remote profiles use a pre-existing SSH tunnel")
            source = ROOT / "Brain/MaleCNS/brain_server_bridge.py"
            graph = Path(config["brain"]["graph"])
            brain_config = Path(config["brain"]["config"])
            missing = [str(path) for path in (source, graph, brain_config) if not path.exists()]
            if missing:
                raise ConfigError("--launch-brain prerequisites are missing: " + ", ".join(missing))
            command = [
                config["brain"]["python"], str(source), "--graph", str(graph), "--config", str(brain_config),
                "--host", "127.0.0.1", "--port", str(config["brain"]["port"]), "--window-ms", "50",
            ]
            launched_at = time.monotonic()
            process = subprocess.Popen(
                command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace",
                # The Brain does not use conversation credentials.  Do not
                # propagate either the key or its local-file locator to it.
                env={
                    name: value for name, value in os.environ.items()
                    if name not in {"OPENAI_API_KEY", "OPENAI_API_KEY_FILE"}
                },
            )
            await _wait_ready(process, "127.0.0.1", config["brain"]["port"])
            print(json.dumps({'event': 'brain_launch_ready', 'pid': process.pid,
                              'startupWallMs': (time.monotonic()-launched_at)*1000}), flush=True)
            async def drain_output():
                # Keep the owned child's pipe drained after READY. Otherwise
                # lifecycle logging eventually blocks the Brain server itself.
                while True:
                    line = await asyncio.to_thread(process.stdout.readline)
                    if not line:
                        return
                    print(line.rstrip(), flush=True)
            output_task = asyncio.create_task(drain_output())
        from Runtime.Bridge.server import run
        await run(config)
    finally:
        if process is not None:
            _terminate_owned(process)
        if output_task is not None:
            await asyncio.gather(output_task, return_exceptions=True)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Flylingual Bridge doctor and foreground launcher")
    subcommands = parser.add_subparsers(dest="command", required=True)
    for command in ("doctor", "up"):
        child = subcommands.add_parser(command)
        child.add_argument("--profile", default="mac-local")
        child.add_argument("--local", help="local JSON override; defaults to Runtime/Config/local.json if present")
        child.add_argument("--conversation", choices=("off", "mock", "live"))
        child.add_argument("--language", choices=("ja", "en"))
        child.add_argument("--voice")
        child.add_argument("--persona", choices=("friendly", "curious", "calm", "custom"))
        child.add_argument("--persona-text")
        child.add_argument("--brain-host")
        child.add_argument("--brain-port", type=int)
        child.add_argument("--graph")
        child.add_argument("--brain-python")
        child.add_argument(
            "--key-file",
            help="local single-line API-key file; overrides OPENAI_API_KEY_FILE and is never stored",
        )
        if command == "up":
            child.add_argument("--launch-brain", action="store_true")
            child.add_argument("--shutdown-file", help="Private launcher stop signal; never an HTTP endpoint")
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        # This is launcher-only process state, deliberately outside the JSON
        # config schema.  Without a requested file, retain any inherited key.
        api_key = load_requested_api_key(args.key_file)
        if api_key is not None:
            os.environ["OPENAI_API_KEY"] = api_key
        config = load_config(profile=args.profile, local=args.local, overrides=_cli_overrides(args))
        if args.command == "doctor":
            report, errors = _doctor(config)
            report["ok"] = not errors
            report["errors"] = errors
            print(json.dumps(report, indent=2, sort_keys=True))
            return 0 if not errors else 1
        # This is launcher-only runtime context, deliberately outside the JSON config schema.
        config["_localPath"] = _resolved_local_path(args.local)
        if args.shutdown_file:
            config["_shutdownFile"] = str(Path(args.shutdown_file).resolve())
        asyncio.run(_up(config, args.launch_brain))
        return 0
    except (ConfigError, CredentialError, RuntimeError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
