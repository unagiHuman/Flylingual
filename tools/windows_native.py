#!/usr/bin/env python3
"""Private Windows supervisor launched by a Unity conversation Player.

The helper owns only its Bridge process, its Brain child created by
``dev.py --launch-brain``, and when configured, its pinned local llama.cpp child.
It deliberately refuses occupied ports so it never attaches to, or kills, a
pre-existing local stack.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from typing import Any

try:
    # ``windows_native.py`` is normally invoked as a script by Unity, while
    # tests import it as ``tools.windows_native``.
    from tools.windows_native_job import JobError, KillOnCloseJob
except ModuleNotFoundError:
    from windows_native_job import JobError, KillOnCloseJob

try:
    from tools.native_local_intent import LocalIntentAborted, LocalIntentError, specification as local_intent_specification
except ModuleNotFoundError:
    from native_local_intent import LocalIntentAborted, LocalIntentError, specification as local_intent_specification

try:
    import psutil
except ModuleNotFoundError:
    psutil = None

ROOT = Path(__file__).resolve().parents[1]
LOOPBACK = {"localhost", "127.0.0.1", "::1"}
# The existing windows-stack.local.json is intentionally a superset: native
# conversation ignores the old Player/video fields instead of forcing users to
# duplicate their machine-local paths.
STACK_KEYS = {"bridgePython", "bridgeLocalConfig", "keyFile", "runRoot", "startupSeconds", "heartbeatSeconds",
              "unityPlayer", "videoBackendConfig", "videoPublisherConfig"}


class NativeError(ValueError):
    pass


def repo_path(value: str | Path) -> Path:
    path = Path(value).expanduser()
    return (path if path.is_absolute() else ROOT / path).resolve()


def read_stack(path: str | Path) -> dict[str, Any]:
    try:
        data = json.loads(repo_path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise NativeError("Windows native configuration could not be read") from exc
    if not isinstance(data, dict) or set(data) - STACK_KEYS:
        raise NativeError("Windows native configuration has unknown keys")
    for key in ("bridgePython", "bridgeLocalConfig"):
        if not isinstance(data.get(key), str) or not data[key]:
            raise NativeError(f"Windows native configuration is missing {key}")
    result: dict[str, Any] = dict(data)
    for key in ("bridgePython", "bridgeLocalConfig", "keyFile", "runRoot", "unityPlayer", "videoBackendConfig", "videoPublisherConfig"):
        if isinstance(result.get(key), str) and result[key]:
            result[key] = repo_path(result[key])
    result.setdefault("runRoot", ROOT / "artifacts" / "windows-native-runs")
    result.setdefault("startupSeconds", 45)
    result.setdefault("heartbeatSeconds", 10)
    if not isinstance(result["startupSeconds"], int) or not 1 <= result["startupSeconds"] <= 120:
        raise NativeError("startupSeconds must be 1..120")
    if not isinstance(result["heartbeatSeconds"], int) or not 2 <= result["heartbeatSeconds"] <= 60:
        raise NativeError("heartbeatSeconds must be 2..60")
    return result


def scrubbed_environment() -> dict[str, str]:
    def sensitive(name: str) -> bool:
        name = name.upper()
        return ("API_KEY" in name or "APIKEY" in name or "TOKEN" in name or "SECRET" in name
                or "PASSWORD" in name or name.startswith(("OPENAI_", "ANTHROPIC_", "AWS_")))
    return {name: value for name, value in os.environ.items() if not sensitive(name)}


def apply_build_selection(stack: dict[str, Any], selection_path: Path, status: Path) -> dict[str, Any]:
    """Create a private config; build provider does not depend on debug flags."""
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from Runtime.Bridge.cloud_intent import cloud_endpoint
    from Runtime.Bridge.config import _check_known
    try:
        selection = json.loads(selection_path.read_text(encoding='utf-8'))
        if (type(selection) is not dict or set(selection) != {'channel', 'provider', 'backendUrl'}
                or selection['channel'] not in ('Dev', 'Demo', 'Judge')
                or selection['provider'] not in ('Local', 'Cloud')):
            raise ValueError('invalid build selection')
        source = json.loads(Path(stack['bridgeLocalConfig']).read_text(encoding='utf-8'))
        if type(source) is not dict:
            raise ValueError('invalid bridge configuration')
        # Reject unknown fields (including any credential field) before writing.
        _check_known(source, 'build source')
        conversation = source.setdefault('conversation', {})
        if selection['provider'] == 'Cloud':
            conversation.update(mode='live' if conversation.get('voiceSessionUrl') else 'text', intentProvider='vercel',
                                cloudIntentUrl=cloud_endpoint(selection['backendUrl']),
                                intentTimeoutMs=5000, localIntentResponsesFallback=False)
        else:
            conversation['intentProvider'] = 'llama_cpp'
        result = dict(stack)
        if conversation.get('mode') == 'text' or conversation.get('voiceSessionUrl'):
            result.pop('keyFile', None)
        destination = status.parent / 'runtime-bridge.json'
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(source, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        result['bridgeLocalConfig'] = destination
        return result
    except (OSError, ValueError, TypeError) as exc:
        raise NativeError('Build selection or source configuration is invalid') from exc


def bridge_settings(stack: dict[str, Any]) -> dict[str, Any]:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from Runtime.Bridge.config import ConfigError, load_config
    try:
        config = load_config(profile="windows-local", local=stack["bridgeLocalConfig"])
    except (ConfigError, OSError, ValueError) as exc:
        raise NativeError("Bridge local configuration is invalid") from exc
    bridge, brain = config["bridge"], config["brain"]
    if bridge["host"].lower() not in LOOPBACK or brain["host"].lower() not in LOOPBACK:
        raise NativeError("Brain and Bridge hosts must be loopback")
    return config


def assert_ports_free(ports: list[int]) -> None:
    if len(ports) != len(set(ports)):
        raise NativeError("Brain and Bridge ports must differ")
    try:
        occupied = {item.laddr.port for item in psutil.net_connections(kind="tcp")
                    if item.status == psutil.CONN_LISTEN and item.laddr and item.laddr.port in ports}
    except psutil.Error as exc:
        raise NativeError("Cannot inspect required local ports before launch") from exc
    if occupied:
        raise NativeError("A required local port is occupied; its existing process was preserved")
    probes: list[socket.socket] = []
    try:
        for port in ports:
            probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            probe.bind(("127.0.0.1", port))
            probes.append(probe)
    except OSError as exc:
        raise NativeError("A required local port is occupied; its existing process was preserved") from exc
    finally:
        for probe in probes:
            probe.close()


def process_identity(pid: int) -> float:
    try:
        return psutil.Process(pid).create_time()
    except psutil.Error as exc:
        raise NativeError("Unity owner process could not be inspected") from exc


def owner_alive(pid: int, created: float) -> bool:
    try:
        return abs(psutil.Process(pid).create_time() - created) <= 0.01
    except psutil.Error:
        return False


class Owned:
    """Legacy verification helper; launch() deliberately uses Job Object ownership."""
    def __init__(self, process: subprocess.Popen[str]):
        self.process = process
        self.identity: dict[int, float] = {process.pid: process_identity(process.pid)}

    def refresh(self) -> None:
        try:
            root = psutil.Process(self.process.pid)
            if abs(root.create_time() - self.identity[self.process.pid]) > 0.01:
                return
            for child in root.children(recursive=True):
                self.identity.setdefault(child.pid, child.create_time())
        except psutil.Error:
            pass

    def stop(self) -> None:
        self.refresh()
        targets = []
        for pid, created in self.identity.items():
            try:
                process = psutil.Process(pid)
                if abs(process.create_time() - created) <= 0.01:
                    targets.append(process)
            except psutil.Error:
                pass
        for process in reversed(targets):
            try:
                process.terminate()
            except psutil.Error:
                pass
        _, remaining = psutil.wait_procs(targets, timeout=5)
        for process in remaining:
            try:
                process.kill()
            except psutil.Error:
                pass


def write_status(path: Path, state: str, **details: Any) -> None:
    # This is Unity's read-only handoff. Never add environment data or credentials.
    payload = {"state": state, "updatedUnixMs": int(time.time() * 1000), **details}
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


def bridge_listening(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.25):
            return True
    except OSError:
        return False


def graceful_stop(process: subprocess.Popen[str], shutdown: Path, status: Path, seconds: float = 5.0) -> None:
    """Request Bridge shutdown, then let the closing owner job kill survivors."""
    shutdown.touch()
    deadline = time.monotonic() + seconds
    while process.poll() is None and time.monotonic() < deadline:
        time.sleep(0.1)
    write_status(status, "stopped")


def bridge_command(stack: dict[str, Any], shutdown: Path) -> list[str]:
    command = [str(stack["bridgePython"]), str(ROOT / "tools" / "dev.py"), "up", "--profile", "windows-local",
               "--local", str(stack["bridgeLocalConfig"]), "--launch-brain", "--shutdown-file", str(shutdown)]
    if stack.get("keyFile") is not None:
        command.extend(("--key-file", str(stack["keyFile"])))
    return command


def launch(stack: dict[str, Any], status: Path, stop: Path, heartbeat: Path, owner_pid: int, owner_created: float) -> int:
    if os.name != "nt":
        raise NativeError("windows-native can run only on Windows")
    if not owner_alive(owner_pid, owner_created):
        raise NativeError("Unity owner process identity no longer matches")
    for label in ("bridgePython", "bridgeLocalConfig"):
        if not stack[label].is_file():
            raise NativeError(f"{label} was not found")
    if stack.get("keyFile") is not None and not stack["keyFile"].is_file():
        raise NativeError("keyFile was not found")
    config = bridge_settings(stack)
    if config["conversation"]["mode"] == "live" and not config['conversation'].get('voiceSessionUrl') and stack.get("keyFile") is None:
        raise NativeError("conversation.mode=live requires an existing keyFile")
    ports = [config["brain"]["port"], config["bridge"]["tcpPort"], config["bridge"]["controlPort"]]
    assert_ports_free(ports)
    try:
        local_intent = local_intent_specification(config)
        if local_intent is not None:
            local_intent.assert_startable()
    except LocalIntentError as exc:
        raise NativeError(str(exc)) from exc
    status.parent.mkdir(parents=True, exist_ok=True)
    stop.unlink(missing_ok=True)
    heartbeat.touch()
    endpoint = f"ws://127.0.0.1:{config['bridge']['controlPort']}/ws"
    write_status(status, "starting", endpoint=endpoint, profile="windows-local", ownerPid=owner_pid)
    command = bridge_command(stack, stop)
    log = status.parent / "bridge.log"
    # Assign the helper before spawning.  The non-inheritable KILL_ON_CLOSE job
    # then automatically contains only this Bridge and its Brain descendants.
    job = KillOnCloseJob()
    job.assign_current_process()
    process: subprocess.Popen[str] | None = None
    def launch_still_owned() -> bool:
        if stop.exists() or not owner_alive(owner_pid, owner_created):
            return False
        try:
            return time.time() - heartbeat.stat().st_mtime <= stack["heartbeatSeconds"]
        except OSError:
            return False
    try:
        if local_intent is not None:
            try:
                local_intent.start(stack["bridgePython"], status.parent / "local-intent.log", stack["startupSeconds"],
                                   launch_still_owned, scrubbed_environment())
            except LocalIntentAborted:
                return 0
            except LocalIntentError as exc:
                raise NativeError(str(exc)) from exc
        with log.open("w", encoding="utf-8", newline="\n") as output:
            process = subprocess.Popen(command, cwd=ROOT, env=scrubbed_environment(), stdin=subprocess.DEVNULL,
                                       stdout=output, stderr=subprocess.STDOUT, text=True,
                                       creationflags=subprocess.CREATE_NO_WINDOW, close_fds=True)
        deadline = time.monotonic() + stack["startupSeconds"]
        while time.monotonic() < deadline:
            if stop.exists():
                return 0
            if process.poll() is not None:
                raise NativeError(f"Bridge exited during startup (exit {process.returncode}); see {log}")
            if not owner_alive(owner_pid, owner_created):
                return 0
            try:
                if time.time() - heartbeat.stat().st_mtime > stack["heartbeatSeconds"]:
                    return 0
            except OSError:
                return 0
            if bridge_listening(config["bridge"]["controlPort"]):
                write_status(status, "ready", endpoint=endpoint, profile="windows-local", ownerPid=owner_pid,
                             helperPid=os.getpid(), bridgePid=process.pid)
                break
            time.sleep(0.2)
        else:
            raise NativeError(f"Bridge did not listen within {stack['startupSeconds']} seconds; see {log}")
        while True:
            if stop.exists():
                return 0
            if process.poll() is not None:
                raise NativeError(f"Bridge exited (exit {process.returncode}); see {log}")
            if not owner_alive(owner_pid, owner_created):
                return 0
            try:
                age = time.time() - heartbeat.stat().st_mtime
            except OSError:
                age = float("inf")
            if age > stack["heartbeatSeconds"]:
                return 0
            time.sleep(0.25)
    finally:
        if process is not None:
            graceful_stop(process, stop, status)
        if local_intent is not None:
            local_intent.stop()
        # Do not close ``job`` here.  This process belongs to KILL_ON_CLOSE; its
        # final handle closes on interpreter exit after the status handoff, which
        # forcibly removes any Bridge/Brain survivor without touching other jobs.
        _ = job


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="Runtime/Config/windows-stack.local.json")
    parser.add_argument("--status", required=True)
    parser.add_argument("--stop", required=True)
    parser.add_argument("--heartbeat", required=True)
    parser.add_argument("--owner-pid", required=True, type=int)
    parser.add_argument("--owner-created", required=True, type=float)
    parser.add_argument("--build-selection", help="Non-secret Player build-channel configuration")
    args = parser.parse_args()
    status = repo_path(args.status)
    if psutil is None:
        message = "psutil is required for owned process cleanup; install it in bridgePython's environment"
        try:
            write_status(status, "failed", message=message)
        except OSError:
            pass
        print(f"windows-native error: {message}", file=sys.stderr)
        return 2
    try:
        stack = read_stack(args.config)
        if args.build_selection:
            stack = apply_build_selection(stack, repo_path(args.build_selection), status)
        return launch(stack, status, repo_path(args.stop), repo_path(args.heartbeat),
                      args.owner_pid, args.owner_created)
    except (NativeError, JobError, OSError, ValueError) as exc:
        write_status(status, "failed", message=str(exc))
        print(f"windows-native error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
