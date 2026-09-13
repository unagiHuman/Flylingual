#!/usr/bin/env python3
"""Mac supervisor launched by the Unity conversation Player or Editor.

The supervisor owns only the Bridge process it starts and the Brain child that
``dev.py --launch-brain`` starts.  It refuses occupied ports and watches the
Unity owner's PID and heartbeat so an unrelated local stack is never stopped.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import socket
import signal
import subprocess
import sys
import time
from typing import Any

try:
    import psutil
except ModuleNotFoundError:
    psutil = None


ROOT = Path(__file__).resolve().parents[1]
LOOPBACK = {"localhost", "127.0.0.1", "::1"}
STACK_KEYS = {
    "bridgePython", "brainPython", "bridgeLocalConfig", "keyFile", "conversationMode",
    "runRoot", "startupSeconds", "heartbeatSeconds",
}
shutdown_requested = False


class NativeError(ValueError):
    pass


def repo_path(value: str | Path) -> Path:
    path = Path(value).expanduser()
    # Keep executable symlinks such as .venv-bridge/bin/python intact. Python
    # uses the symlink path to select the venv site-packages directory.
    return (path if path.is_absolute() else ROOT / path).absolute()


def read_stack(path: str | Path) -> dict[str, Any]:
    try:
        data = json.loads(repo_path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise NativeError("Mac native configuration could not be read") from exc
    if not isinstance(data, dict) or set(data) - STACK_KEYS:
        raise NativeError("Mac native configuration has unknown keys")
    for key in ("bridgePython", "brainPython"):
        if not isinstance(data.get(key), str) or not data[key]:
            raise NativeError(f"Mac native configuration is missing {key}")

    result: dict[str, Any] = dict(data)
    for key in ("bridgePython", "brainPython", "bridgeLocalConfig", "keyFile"):
        if isinstance(result.get(key), str) and result[key]:
            result[key] = repo_path(result[key])
    result.setdefault("conversationMode", "mock")
    result.setdefault("runRoot", ROOT / "artifacts" / "mac-native-runs")
    result.setdefault("startupSeconds", 90)
    result.setdefault("heartbeatSeconds", 10)
    result["runRoot"] = repo_path(result["runRoot"])
    if result["conversationMode"] not in {"off", "mock", "live"}:
        raise NativeError("conversationMode must be off, mock, or live")
    if not isinstance(result["startupSeconds"], int) or not 1 <= result["startupSeconds"] <= 180:
        raise NativeError("startupSeconds must be 1..180")
    if not isinstance(result["heartbeatSeconds"], int) or not 2 <= result["heartbeatSeconds"] <= 60:
        raise NativeError("heartbeatSeconds must be 2..60")
    return result


def scrubbed_environment() -> dict[str, str]:
    def sensitive(name: str) -> bool:
        upper = name.upper()
        return ("API_KEY" in upper or "APIKEY" in upper or "TOKEN" in upper or "SECRET" in upper
                or "PASSWORD" in upper or upper.startswith(("OPENAI_", "ANTHROPIC_", "AWS_")))

    return {name: value for name, value in os.environ.items() if not sensitive(name)}


def bridge_settings(stack: dict[str, Any]) -> dict[str, Any]:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from Runtime.Bridge.config import ConfigError, load_config

    try:
        config = load_config(
            profile="mac-local",
            local=stack.get("bridgeLocalConfig"),
            overrides={"conversation": {"mode": stack["conversationMode"]}},
        )
    except (ConfigError, OSError, ValueError) as exc:
        raise NativeError("Mac Bridge configuration is invalid") from exc
    bridge, brain = config["bridge"], config["brain"]
    if bridge["host"].lower() not in LOOPBACK or brain["host"].lower() not in LOOPBACK:
        raise NativeError("Brain and Bridge hosts must be loopback")
    if config["conversation"]["mode"] != stack["conversationMode"]:
        raise NativeError("conversationMode does not match the resolved Bridge configuration")
    return config


def assert_ports_free(ports: list[int]) -> None:
    if len(ports) != len(set(ports)):
        raise NativeError("Brain and Bridge ports must differ")
    if psutil is None:
        raise NativeError("psutil is required for Mac native process ownership")
    try:
        occupied = {
            item.laddr.port for item in psutil.net_connections(kind="tcp")
            if item.status == psutil.CONN_LISTEN and item.laddr and item.laddr.port in ports
        }
    except psutil.AccessDenied:
        # macOS may deny process-wide connection enumeration to an ordinary
        # user. The bind probes below still detect listeners on the required
        # loopback ports without requiring elevated access.
        occupied = set()
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
    if psutil is None:
        raise NativeError("psutil is required for Mac native process ownership")
    try:
        return psutil.Process(pid).create_time()
    except psutil.Error as exc:
        raise NativeError("Unity owner process could not be inspected") from exc


def owner_alive(pid: int, created: float) -> bool:
    if psutil is None:
        return False
    try:
        process = psutil.Process(pid)
        if not process.is_running() or process.status() == psutil.STATUS_ZOMBIE:
            return False
        return abs(process.create_time() - created) <= 0.01
    except psutil.Error:
        return False


def request_shutdown(_signum: int, _frame: Any) -> None:
    """Let the supervisor finish ownership cleanup after a terminal signal."""
    global shutdown_requested
    shutdown_requested = True


class Owned:
    def __init__(self, process: subprocess.Popen[str]):
        self.process = process
        self.identity: dict[int, float] = {process.pid: process_identity(process.pid)}

    def refresh(self) -> None:
        if psutil is None:
            return
        try:
            root = psutil.Process(self.process.pid)
            if abs(root.create_time() - self.identity[self.process.pid]) > 0.01:
                return
            for child in root.children(recursive=True):
                self.identity.setdefault(child.pid, child.create_time())
        except psutil.Error:
            pass

    def stop(self) -> None:
        if psutil is None:
            return
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


def graceful_stop(owned: Owned, shutdown: Path, status: Path, seconds: float = 25.0) -> None:
    shutdown.touch()
    deadline = time.monotonic() + seconds
    while owned.process.poll() is None and time.monotonic() < deadline:
        owned.refresh()
        time.sleep(0.1)
    owned.stop()
    write_status(status, "stopped")


def bridge_command(stack: dict[str, Any], shutdown: Path) -> list[str]:
    command = [
        str(stack["bridgePython"]), str(ROOT / "tools" / "dev.py"), "up",
        "--profile", "mac-local", "--conversation", stack["conversationMode"],
        "--launch-brain", "--brain-python", str(stack["brainPython"]),
        "--shutdown-file", str(shutdown),
    ]
    if stack.get("bridgeLocalConfig") is not None:
        command.extend(("--local", str(stack["bridgeLocalConfig"])))
    if stack.get("keyFile") is not None:
        command.extend(("--key-file", str(stack["keyFile"])))
    return command


def launch(stack: dict[str, Any], status: Path, stop: Path, heartbeat: Path,
           owner_pid: int, owner_created: float) -> int:
    if not owner_alive(owner_pid, owner_created):
        raise NativeError("Unity owner process identity no longer matches")
    for label in ("bridgePython", "brainPython"):
        if not stack[label].is_file():
            raise NativeError(f"{label} was not found")
    if stack.get("bridgeLocalConfig") is not None and not stack["bridgeLocalConfig"].is_file():
        raise NativeError("bridgeLocalConfig was not found")
    if stack.get("keyFile") is not None and not stack["keyFile"].is_file():
        raise NativeError("keyFile was not found")
    if stack["conversationMode"] == "live" and stack.get("keyFile") is None:
        raise NativeError("conversationMode=live requires an existing keyFile")

    config = bridge_settings(stack)
    ports = [config["brain"]["port"], config["bridge"]["tcpPort"], config["bridge"]["controlPort"]]
    assert_ports_free(ports)
    status.parent.mkdir(parents=True, exist_ok=True)
    stop.unlink(missing_ok=True)
    heartbeat.touch()
    endpoint = f"ws://127.0.0.1:{config['bridge']['controlPort']}/ws"
    write_status(status, "starting", endpoint=endpoint, profile="mac-local", ownerPid=owner_pid)
    command = bridge_command(stack, stop)
    log = status.parent / "bridge.log"
    with log.open("w", encoding="utf-8", newline="\n") as output:
        process = subprocess.Popen(
            command, cwd=ROOT, env=scrubbed_environment(), stdin=subprocess.DEVNULL,
            stdout=output, stderr=subprocess.STDOUT, text=True, start_new_session=True,
        )
    owned = Owned(process)
    try:
        deadline = time.monotonic() + stack["startupSeconds"]
        while time.monotonic() < deadline:
            owned.refresh()
            if shutdown_requested or stop.exists():
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
                write_status(status, "ready", endpoint=endpoint, profile="mac-local", ownerPid=owner_pid,
                             helperPid=os.getpid(), bridgePid=process.pid)
                break
            time.sleep(0.2)
        else:
            raise NativeError(f"Bridge did not listen within {stack['startupSeconds']} seconds; see {log}")

        while True:
            owned.refresh()
            if shutdown_requested or stop.exists():
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
        graceful_stop(owned, stop, status)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="Runtime/Config/mac-native.local.json")
    parser.add_argument("--status", required=True)
    parser.add_argument("--stop", required=True)
    parser.add_argument("--heartbeat", required=True)
    parser.add_argument("--owner-pid", required=True, type=int)
    parser.add_argument("--owner-created", required=True, type=float)
    args = parser.parse_args()
    for signal_number in (signal.SIGINT, signal.SIGTERM, getattr(signal, "SIGHUP", None)):
        if signal_number is not None:
            signal.signal(signal_number, request_shutdown)
    status = repo_path(args.status)
    if psutil is None:
        message = "psutil is required for Mac native process ownership; install tools/requirements-mac-native.txt"
        try:
            write_status(status, "failed", message=message)
        except OSError:
            pass
        print(f"mac-native error: {message}", file=sys.stderr)
        return 2
    try:
        return launch(read_stack(args.config), status, repo_path(args.stop), repo_path(args.heartbeat),
                      args.owner_pid, args.owner_created)
    except (NativeError, OSError, ValueError) as exc:
        write_status(status, "failed", message=str(exc))
        print(f"mac-native error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
