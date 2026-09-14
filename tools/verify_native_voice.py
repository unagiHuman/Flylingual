#!/usr/bin/env python3
"""Run the Unity synthetic-voice fixture probe with owned-process cleanup.

This wrapper never opens a Brain or Bridge client itself.  Unity owns the
existing control connection; the fixture input is selected by command line.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import re
from pathlib import Path
import platform
import subprocess
import sys
import time

import psutil

from windows_native import (ROOT, Owned, assert_ports_free, bridge_settings,
                            owner_alive, read_stack, scrubbed_environment)


def sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def collect_hashes(manifest: Path, config: dict | None = None, exe: Path | None = None) -> dict[str, dict[str, str | None]]:
    groups: dict[str, list[str]] = {
        "source": ["Brain/MaleCNS/brain_server_analog.py", "Brain/MaleCNS/shiu_compatible.py",
                   "Brain/MaleCNS/analog_controller.py", "Brain/MaleCNS/lif_kernels.py",
                   "Runtime/Bridge/server.py", "Runtime/Bridge/conversation.py",
                   "Runtime/Bridge/action_plans.py", "Runtime/Bridge/control.py",
                   "Runtime/Bridge/conversation_prompts.py", "Runtime/Bridge/fast_intents.py",
                   "Runtime/Bridge/intent_contract.py", "Runtime/Bridge/intent_interpreter.py",
                   "tools/verify_native_voice.py", "tools/windows_native.py"],
        "config": ["Runtime/Config/local.json", "Runtime/Config/windows-stack.local.json",
                   "Runtime/Config/profiles/windows-local.json", "Brain/MaleCNS/requirements-runtime.txt"],
        "data": [],
        "artifact": ["artifacts/windows-native-conversation/unity/FlylingualConversation.exe",
                      "artifacts/windows-native-conversation/unity/FlylingualConversation_Data/Managed/Assembly-CSharp.dll",
                      "UnityProject/Assets/RuntimeIntegration/Conversation/Client/ConversationSessionController.cs",
                      "UnityProject/Assets/RuntimeIntegration/Conversation/NativeVoiceFixtureProbe.cs",
                      "UnityProject/Assets/RuntimeIntegration/Conversation/Audio/VoiceFixtureClip.cs",
                      "UnityProject/Assets/RuntimeIntegration/Conversation/Audio/PcmStreamConverter.cs"],
    }
    if exe is not None:
        groups["artifact"][:2] = [str(exe), str(exe.parent / (exe.stem + "_Data") / "Managed/Assembly-CSharp.dll")]
    if config:
        brain = config.get("brain", {})
        for key, group in (("config", "config"), ("graph", "data"), ("visualizationAtlas", "artifact")):
            value = brain.get(key)
            if isinstance(value, str):
                p = (ROOT / value).resolve()
                if p.is_file(): groups[group].append(str(p))
                elif p.is_dir(): groups[group].extend(str(x) for x in sorted(p.iterdir()) if x.is_file())
    groups["fixtures"] = [str(manifest)]
    result = {}
    for group, paths in groups.items():
        result[group] = {}
        for item in paths:
            path = Path(item)
            result[group][item] = sha256(path if path.is_absolute() else ROOT / path)
    try:
        entries = json.loads(manifest.read_text(encoding="utf-8-sig")).get("fixtures", [])
        result["fixtureWavs"] = {str(manifest.parent / str(e.get("file"))): sha256(manifest.parent / str(e.get("file")))
                                  for e in entries if isinstance(e, dict) and isinstance(e.get("file"), str)}
    except (OSError, json.JSONDecodeError, AttributeError):
        result["fixtureWavs"] = {}
    return result


def runtime_versions(config: dict) -> dict:
    packages = {}
    for name in ("aiohttp", "psutil"):
        try: packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError: packages[name] = None
    result = {"python": sys.version, "packages": packages, "platform": platform.platform()}
    script = "import sys,json,importlib.metadata as m; print(json.dumps({'python':sys.version,'packages':{n:m.version(n) for n in ('numpy','numba','llvmlite')}}))"
    try:
        response = subprocess.run([config["brain"]["python"], "-c", script], cwd=ROOT,
                                  env=scrubbed_environment(), capture_output=True, text=True,
                                  timeout=15, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), check=True)
        result["brainPython"] = json.loads(response.stdout)
    except Exception as exc:
        result["brainVersionError"] = type(exc).__name__
    return result


def read_report(output: Path) -> dict:
    # NativeVoiceFixtureProbe may choose any of these explicit report names.
    for name in ("summary.json", "voice-report.json", "report.json"):
        path = output / name
        if path.is_file():
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(value, dict):
                    return value
            except (OSError, json.JSONDecodeError):
                return {"status": "incomplete", "reportError": f"invalid_{name}"}
    return {"status": "blocked", "reportError": "fixture_probe_report_missing"}


def evaluate_status(report, *, timeout, remaining, ports_free, exit_code, exceptions, runner_error):
    if runner_error:
        return "fail"
    status = str(report.get("status", "incomplete")).lower()
    if status in ("pass", "passed", "ok"):
        return "pass" if (report.get("pass") is True and report.get("stopped") is True
                          and not timeout and not remaining and ports_free
                          and exit_code == 0 and exceptions == 0) else "incomplete"
    return status if status in ("blocked", "incomplete", "fail", "failed") else "incomplete"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--fixtures", required=True, type=Path, help="manifest.json")
    ap.add_argument("--suite", choices=("smoke", "full", "duration", "plans", "soak", "persistent", "handoff", "script_interrupt"), default="smoke")
    ap.add_argument("--capture-test-transcript", action="store_true",
                    help="opt-in recognized text for synthetic fixtures only; never enables the microphone")
    ap.add_argument("--seconds", type=int, default=None)
    ap.add_argument("--output", required=True, type=Path)
    ap.add_argument("--exe", type=Path,
                    default=ROOT / "artifacts/windows-native-conversation/unity/FlylingualConversation.exe")
    ap.add_argument("--stack", type=Path, default=ROOT / "Runtime/Config/windows-stack.local.json",
                    help="must be the Player's default windows-stack.local.json")
    args = ap.parse_args()
    manifest = (ROOT / args.fixtures if not args.fixtures.is_absolute() else args.fixtures).resolve()
    output = (ROOT / args.output if not args.output.is_absolute() else args.output).resolve()
    exe = (ROOT / args.exe if not args.exe.is_absolute() else args.exe).resolve()
    stack_path = (ROOT / args.stack if not args.stack.is_absolute() else args.stack).resolve()
    default_stack = (ROOT / "Runtime/Config/windows-stack.local.json").resolve()
    if stack_path != default_stack:
        ap.error("--stack must be the Player default Runtime/Config/windows-stack.local.json")
    if not manifest.is_file(): ap.error(f"fixture manifest not found: {manifest}")
    if not exe.is_file(): ap.error(f"Unity Player not found: {exe}")
    if args.seconds is not None and not 1 <= args.seconds <= 3600: ap.error("--seconds must be between 1 and 3600")
    if output.exists(): ap.error(f"output already exists; choose a new directory: {output}")
    output.mkdir(parents=True)
    event_log = output / "runner-events.jsonl"
    player_log = output / "player.log"
    metadata = output / "runner-metadata.json"
    with event_log.open("w", encoding="utf-8", newline="\n") as events:
        def event(kind: str, **details: object) -> None:
            events.write(json.dumps({"tsUnixMs": int(time.time() * 1000), "event": kind, **details}, ensure_ascii=False) + "\n")
            events.flush()
        try:
            stack = read_stack(stack_path)
            config = bridge_settings(stack)
            ports = [config["brain"]["port"], config["bridge"]["tcpPort"], config["bridge"]["controlPort"]]
            assert_ports_free(ports)
            run_hashes = collect_hashes(manifest, config, exe)
            versions = runtime_versions(config)
        except Exception as exc:
            payload = {"status": "blocked", "reason": "preflight_failed", "errorType": type(exc).__name__}
            metadata.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            event("blocked", **payload)
            return 2
        command = [str(exe), "-flyRepoRoot", str(ROOT), "-flyVoiceFixtures", str(manifest),
                   "-flyVoiceFixtureOutput", str(output), "-flyVoiceFixtureSuite", args.suite,
                   "-flyVoiceFixtureQuit", "-logFile", str(player_log),
                   "-screen-fullscreen", "0", "-screen-width", "1280", "-screen-height", "800"]
        if args.seconds is not None:
            command.extend(("-flyVoiceFixtureSeconds", str(args.seconds)))
        if args.capture_test_transcript:
            command.append("-flyVoiceFixtureTextDiagnostics")
        event("launch", suite=args.suite)
        started = time.monotonic()
        stdout_path = output / "player-stdout.log"
        deadline_seconds = args.seconds if args.seconds is not None else {"smoke": 240, "full": 900, "duration": 180, "plans": 240, "soak": 300, "persistent": 180, "handoff": 120, "script_interrupt": 120}[args.suite]
        timeout = False; process = None; owned = None; peak_rss = 0; runner_exception = None
        try:
            with stdout_path.open("w", encoding="utf-8", newline="\n") as player_output:
                process = subprocess.Popen(command, cwd=ROOT, env=scrubbed_environment(), stdin=subprocess.DEVNULL,
                                           stdout=player_output, stderr=subprocess.STDOUT, text=True,
                                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                owned = Owned(process)
                deadline = time.monotonic() + max(60, deadline_seconds + 45)
                while process.poll() is None and time.monotonic() < deadline:
                    owned.refresh()
                    rss = 0
                    for pid, created in owned.identity.items():
                        if owner_alive(pid, created):
                            try: rss += psutil.Process(pid).memory_info().rss
                            except psutil.Error: pass
                    peak_rss = max(peak_rss, rss)
                    time.sleep(.25)
                timeout = process.poll() is None
                if timeout:
                    event("timeout", seconds=deadline_seconds)
        except Exception as exc:
            runner_exception = type(exc).__name__
            event("runner_exception", errorType=runner_exception)
        finally:
            if owned is not None:
                owned.refresh()
                owned.stop()
                time.sleep(.25)
                owned.refresh()
        remaining = [] if owned is None else [pid for pid, created in owned.identity.items() if owner_alive(pid, created)]
        ports_free_after_cleanup = False
        cleanup_port_error = None
        try:
            assert_ports_free(ports)
            ports_free_after_cleanup = True
        except Exception as exc:
            cleanup_port_error = type(exc).__name__
        report = read_report(output)
        exception_count = -1
        if player_log.is_file():
            exception_count = len(re.findall(r"^[\w.]*Exception:", player_log.read_text(encoding="utf-8", errors="replace"), re.MULTILINE))
        process_code = None if process is None else process.returncode
        status = evaluate_status(report, timeout=timeout, remaining=remaining, ports_free=ports_free_after_cleanup,
                                 exit_code=process_code, exceptions=exception_count, runner_error=runner_exception)
        result = {"status": status, "suite": args.suite, "fixtureManifest": str(manifest),
                  "exitCode": process_code, "timeout": timeout, "remainingOwnedPids": remaining,
                  "portsFreeAfterCleanup": ports_free_after_cleanup, "cleanupPortError": cleanup_port_error,
                  "wallSeconds": round(time.monotonic() - started, 3), "peakTreeRssBytes": peak_rss,
                  "playerExceptionCount": exception_count,
                  "runnerExceptionType": runner_exception,
                  "hashes": run_hashes,
                  "environment": versions,
                  "probe": report}
        metadata.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        event("complete", status=status, exitCode=process_code, remainingOwnedPids=remaining)
        print(json.dumps({"status": status, "report": str(metadata), "exitCode": process_code,
                          "remainingOwnedPids": remaining, "portsFreeAfterCleanup": ports_free_after_cleanup}, ensure_ascii=False))
        return 0 if status == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
