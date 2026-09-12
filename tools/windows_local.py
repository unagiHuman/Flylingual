#!/usr/bin/env python3
"""Windows-only, foreground supervisor for the local Brain, Bridge, video, and Unity stack."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener

import psutil
import webbrowser

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from Runtime.Bridge.config import ConfigError, load_config
from Runtime.Video.config import load as load_video
from Runtime.Video.launcher import LaunchError, load_publisher_config, read_health

LOOPBACK = {"localhost", "127.0.0.1", "::1"}
STACK_KEYS = {"bridgePython", "bridgeLocalConfig", "keyFile", "unityPlayer", "videoBackendConfig", "videoPublisherConfig", "runRoot"}
MAX_DURATION = 86400
HTTP_TIMEOUT = 1.0


class StackError(ValueError):
    pass


def repo_path(value: str) -> Path:
    path = Path(value).expanduser()
    return (path if path.is_absolute() else ROOT / path).resolve()


def read_stack(path: str | Path) -> dict[str, Path]:
    path = repo_path(str(path))
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StackError("Windows stack configuration could not be read") from exc
    if not isinstance(data, dict) or set(data) - STACK_KEYS:
        raise StackError("Windows stack configuration has unknown keys")
    required = STACK_KEYS - {"keyFile", "runRoot"}
    if any(not isinstance(data.get(key), str) or not data[key] for key in required):
        raise StackError("Windows stack configuration is missing a required path")
    result = {key: repo_path(value) for key, value in data.items() if isinstance(value, str) and value}
    result.setdefault("runRoot", ROOT / "artifacts" / "windows-local-runs")
    return result


def ensure_file(path: Path, label: str) -> None:
    if not path.is_file():
        raise StackError(f"{label} was not found")


def _loopback_url(value: str, label: str) -> None:
    from urllib.parse import urlsplit
    parsed = urlsplit(value)
    if (parsed.scheme != "http" or parsed.hostname not in LOOPBACK or parsed.username or parsed.password
            or parsed.query or parsed.fragment):
        raise StackError(f"{label} must use a loopback HTTP URL")


def validate(stack: dict[str, Path], key_override: str | None) -> tuple[dict[str, Any], dict[str, Any], Path | None]:
    for key, label in (("bridgePython", "Bridge Python"), ("bridgeLocalConfig", "Bridge local configuration"),
                       ("unityPlayer", "Unity Player"), ("videoBackendConfig", "Video backend configuration"),
                       ("videoPublisherConfig", "Video publisher configuration")):
        ensure_file(stack[key], label)
    bridge = load_config(profile="windows-local", local=stack["bridgeLocalConfig"])
    video = load_video(stack["videoBackendConfig"])
    try:
        publisher_port, _ = load_publisher_config(stack["videoPublisherConfig"], video["streams"])
    except LaunchError as exc:
        raise StackError("Video publisher configuration is invalid") from exc
    publisher = json.loads(stack["videoPublisherConfig"].read_text(encoding="utf-8"))
    endpoint = publisher.get("endpoint")
    if not isinstance(endpoint, str):
        raise StackError("Video publisher endpoint is required")
    _loopback_url(endpoint, "Video publisher endpoint")
    if publisher_port != video["port"] or publisher.get("streamId") != "unity-windows":
        raise StackError("Video publisher must target this loopback backend as stream unity-windows")
    if bridge["bridge"]["host"].lower() not in LOOPBACK or bridge["brain"]["host"].lower() not in LOOPBACK:
        raise StackError("Brain and Bridge hosts must be loopback")
    if bridge["bridge"]["tcpPort"] == bridge["bridge"]["controlPort"]:
        raise StackError("Bridge TCP and HTTP ports must differ")
    if bridge["conversation"]["mode"] != "live":
        raise StackError("windows-local requires conversation.mode=live")
    ensure_file(Path(bridge["brain"]["python"]), "Brain Python")
    ensure_file(Path(bridge["brain"]["config"]), "Brain configuration")
    if not Path(bridge["brain"]["graph"]).is_dir():
        raise StackError("Brain graph was not found")
    origin = f"http://127.0.0.1:{bridge['bridge']['controlPort']}"
    if origin not in video["allowedOrigins"]:
        raise StackError("Video backend must allow the local Bridge player origin")
    key_file = repo_path(key_override) if key_override else stack.get("keyFile")
    if key_file is None or not key_file.is_file():
        raise StackError("conversation.mode=live requires an existing local key file")
    return bridge, video, key_file


def required_ports(bridge: dict[str, Any], video: dict[str, Any]) -> list[int]:
    ports = [bridge["brain"]["port"], bridge["bridge"]["tcpPort"], bridge["bridge"]["controlPort"], video["port"]]
    if len(set(ports)) != len(ports):
        raise StackError("Brain, Bridge TCP, Bridge HTTP, and video ports must all differ")
    return ports


def bridge_doctor(stack: dict[str, Path], key_file: Path) -> None:
    command = [str(stack["bridgePython"]), str(ROOT / "tools" / "dev.py"), "doctor", "--profile", "windows-local",
               "--local", str(stack["bridgeLocalConfig"]), "--key-file", str(key_file)]
    result = subprocess.run(command, cwd=ROOT, env=scrubbed_environment(), stdin=subprocess.DEVNULL,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    if result.returncode != 0:
        raise StackError("Bridge doctor did not validate the local Windows Brain configuration")


def assert_ports_free(ports: list[int]) -> None:
    occupied: set[int] = set()
    try:
        for item in psutil.net_connections(kind="tcp"):
            if item.status == psutil.CONN_LISTEN and item.laddr and item.laddr.port in ports:
                occupied.add(item.laddr.port)
    except psutil.Error as exc:
        raise StackError("Cannot inspect required local ports before launch") from exc
    if occupied:
        raise StackError("A required local port is occupied; its existing process was preserved")
    probes: list[socket.socket] = []
    try:
        for port in ports:
            probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            probe.bind(("127.0.0.1", port))
            probes.append(probe)
    except OSError as exc:
        raise StackError("A required local port is occupied; its existing process was preserved") from exc
    finally:
        for probe in probes:
            probe.close()


def scrubbed_environment() -> dict[str, str]:
    def sensitive(name: str) -> bool:
        upper = name.upper()
        return ("API_KEY" in upper or "APIKEY" in upper or "TOKEN" in upper or "SECRET" in upper
                or "PASSWORD" in upper or upper.startswith(("OPENAI_", "ANTHROPIC_", "AWS_")))
    return {key: value for key, value in os.environ.items() if not sensitive(key)}


class Owned:
    def __init__(self, name: str, process: subprocess.Popen[str]):
        self.name, self.process = name, process
        self.created = psutil.Process(process.pid).create_time()
        self.processes: dict[int, float] = {process.pid: self.created}

    def refresh(self) -> None:
        try:
            root = psutil.Process(self.process.pid)
            if abs(root.create_time() - self.created) > 0.01:
                return
            for item in root.children(recursive=True):
                self.processes.setdefault(item.pid, item.create_time())
        except psutil.Error:
            pass

    def alive(self) -> bool:
        self.refresh()
        return self.process.poll() is None

    def stop(self) -> None:
        self.refresh()
        targets = []
        for pid, created in self.processes.items():
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
        _, alive = psutil.wait_procs(targets, timeout=5)
        for process in alive:
            try:
                process.kill()
            except psutil.Error:
                pass


def start(name: str, command: list[str], env: dict[str, str], log: Path, visible: bool = False) -> Owned:
    flags = 0 if visible else subprocess.CREATE_NO_WINDOW
    with log.open("w", encoding="utf-8", newline="\n") as handle:
        process = subprocess.Popen(command, cwd=ROOT, env=env, stdin=subprocess.DEVNULL,
                                   stdout=handle, stderr=subprocess.STDOUT, text=True,
                                   creationflags=flags)
    return Owned(name, process)


def http_ready(port: int, path: str, children: list[Owned]) -> None:
    deadline = time.monotonic() + 30
    url = f"http://127.0.0.1:{port}{path}"
    opener = build_opener(ProxyHandler({}))
    while time.monotonic() < deadline:
        stopped = next((child.name for child in children if not child.alive()), None)
        if stopped:
            raise StackError(f"{stopped} stopped during startup")
        try:
            with opener.open(Request(url, method="GET"), timeout=HTTP_TIMEOUT) as response:
                if response.status == 200:
                    return
        except (OSError, HTTPError, URLError):
            time.sleep(0.2)
    raise StackError("A local HTTP readiness endpoint did not become ready")


def timestamped_run(root: Path) -> Path:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    run = root / stamp
    run.mkdir(parents=True, exist_ok=False)
    return run


def player_url(bridge: dict[str, Any], video: dict[str, Any]) -> str:
    return (f"http://127.0.0.1:{bridge['bridge']['controlPort']}/player/"
            f"?profile=windows-local&stream=unity-windows&videoPort={video['port']}")


def doctor(stack: dict[str, Path], bridge: dict[str, Any], video: dict[str, Any], key_file: Path | None) -> int:
    ports = required_ports(bridge, video)
    report = {"ok": True, "profile": bridge["profile"], "brain": f"127.0.0.1:{bridge['brain']['port']}",
              "bridgeTcp": f"127.0.0.1:{bridge['bridge']['tcpPort']}", "playerUrl": player_url(bridge, video),
              "video": f"http://127.0.0.1:{video['port']}/api/video/health", "stream": "unity-windows",
              "ports": ports, "keyFilePresent": key_file is not None and key_file.is_file()}
    try:
        assert_ports_free(ports)
        report["portsAvailable"] = True
    except StackError:
        report["portsAvailable"] = False
        report["ok"] = False
    print(json.dumps(report, indent=2))
    return 0 if report["ok"] else 1


def up(stack: dict[str, Path], bridge: dict[str, Any], video: dict[str, Any], key_file: Path | None, duration: int | None, no_browser: bool) -> int:
    if os.name != "nt":
        raise StackError("windows-local can run only on Windows")
    if duration is not None and not 1 <= duration <= MAX_DURATION:
        raise StackError("duration must be 1..86400 seconds")
    assert_ports_free(required_ports(bridge, video))
    run = timestamped_run(stack["runRoot"])
    children: list[Owned] = []
    try:
        bridge_command = [str(stack["bridgePython"]), str(ROOT / "tools" / "dev.py"), "up", "--profile", "windows-local",
                          "--local", str(stack["bridgeLocalConfig"]), "--launch-brain"]
        if key_file is not None:
            bridge_command += ["--key-file", str(key_file)]
        bridge_child = start("bridge", bridge_command, scrubbed_environment(), run / "bridge.log")
        children.append(bridge_child)
        http_ready(bridge["bridge"]["controlPort"], "/player/", children)

        video_child = start("video", [sys.executable, str(ROOT / "tools" / "video.py"), "serve", "--config", str(stack["videoBackendConfig"])],
                            scrubbed_environment(), run / "video.log")
        children.append(video_child)
        deadline = time.monotonic() + 30
        while True:
            if next((child for child in children if not child.alive()), None):
                raise StackError("A self-owned child stopped during video startup")
            try:
                health = read_health(video["port"])
                break
            except LaunchError:
                if time.monotonic() >= deadline:
                    raise StackError("Video health did not become ready")
                time.sleep(0.2)

        player_args = [str(stack["unityPlayer"]), "-demoLive", "-demoLiveConnectDelay", "3", "-brainHost", "127.0.0.1",
                       "-brainPort", str(bridge["bridge"]["tcpPort"]), "-flyVideoConfig", str(stack["videoPublisherConfig"]),
                       "-demoOutput", str(run / "unity"), "-logFile", str(run / "player.log"), "-screen-fullscreen", "0"]
        children.append(start("unityPlayer", player_args, scrubbed_environment(), run / "player-wrapper.log", visible=True))
        url = player_url(bridge, video)
        state = {"profile": "windows-local", "run": str(run), "playerUrl": url,
                 "videoInstanceId": health["instanceId"], "stream": "unity-windows", "pids": {child.name: child.process.pid for child in children}}
        (run / "runstate.json").write_text(json.dumps(state, indent=2), encoding="utf-8")
        print(json.dumps({"event": "windows_local_ready", "run": str(run), "stream": "unity-windows", "playerUrl": url}), flush=True)
        if not no_browser:
            webbrowser.open(url)
        started = time.monotonic()
        while True:
            if duration is not None and time.monotonic() - started >= duration:
                return 0
            exited = next((child for child in children if not child.alive()), None)
            if exited:
                raise StackError(f"Self-owned child exited: {exited.name}")
            time.sleep(0.25)
    finally:
        for child in reversed(children):
            child.stop()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("doctor", "up"))
    parser.add_argument("--config", default="Runtime/Config/windows-stack.local.json")
    parser.add_argument("--key-file")
    parser.add_argument("--duration", type=int)
    parser.add_argument("--no-browser", action="store_true", help="Do not open the local player page after startup")
    args = parser.parse_args()
    try:
        stack = read_stack(args.config)
        bridge, video, key_file = validate(stack, args.key_file)
        assert key_file is not None
        bridge_doctor(stack, key_file)
        return doctor(stack, bridge, video, key_file) if args.action == "doctor" else up(stack, bridge, video, key_file, args.duration, args.no_browser)
    except (StackError, ConfigError, OSError, ValueError) as exc:
        print(f"windows-local error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
