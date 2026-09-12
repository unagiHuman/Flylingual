"""Foreground launcher helpers for the loopback-only video backend."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import plistlib
import re
import signal
import socket
import subprocess
import sys
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
import uuid

import psutil


ROOT = Path(__file__).resolve().parents[2]
HEALTH_PATH = "/api/video/health"
HEALTH_TIMEOUT_SECONDS = 1.0
STARTUP_TIMEOUT_SECONDS = 12.0
POLL_SECONDS = 0.2
METRICS_INTERVAL_SECONDS = 1.0
SHUTDOWN_SECONDS = 5.0
MAX_DURATION_SECONDS = 24 * 60 * 60
MAX_HEALTH_BYTES = 64 * 1024
_TARGET = re.compile(
    r"(?:[A-Za-z_][A-Za-z0-9_-]{0,31}@)?"
    r"(?:[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?|\[[0-9A-Fa-f:]+\])"
)


class LaunchError(ValueError):
    """A user-facing startup failure with no configuration or secret echo."""


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        return None


@dataclass
class Child:
    name: str
    process: subprocess.Popen


def absolute_path(value: str | Path) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = ROOT / path
    return path.resolve()


def _valid_token(value: str) -> bool:
    return 32 <= len(value) <= 256 and value.isascii() and value.isprintable()


def _file_token(config_path: Path, token_file: Any) -> str | None:
    if not isinstance(token_file, str) or not token_file:
        return None
    path = Path(token_file)
    if not path.is_absolute():
        path = config_path.parent / path
    try:
        token = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return token if _valid_token(token) else None


def load_publisher_config(path: Path, configured_streams: list[str]) -> tuple[int, str | None]:
    """Read only the non-secret endpoint used by the native publisher."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LaunchError("Publisher configuration could not be read") from exc
    if not isinstance(data, dict) or not isinstance(data.get("endpoint"), str):
        raise LaunchError("Publisher configuration requires a loopback endpoint")
    endpoint = urlsplit(data["endpoint"])
    try:
        port = endpoint.port
    except ValueError as exc:
        raise LaunchError("Publisher endpoint has an invalid port") from exc
    if (endpoint.scheme != "http" or endpoint.hostname not in ("127.0.0.1", "localhost", "::1")
            or endpoint.username or endpoint.password or endpoint.path not in ("", "/")
            or endpoint.query or endpoint.fragment or port is None):
        raise LaunchError("Publisher endpoint must be an explicit loopback HTTP endpoint")
    if data.get("enabled") is not True:
        raise LaunchError("Publisher configuration must be enabled for Player launch")
    stream = data.get("streamId")
    if not isinstance(stream, str) or stream not in configured_streams:
        raise LaunchError("Publisher stream is not configured by the video backend")
    return port, data.get("tokenFile")


def resolve_player(value: str) -> Path:
    player = absolute_path(value)
    if player.suffix.lower() == ".app":
        info = player / "Contents" / "Info.plist"
        try:
            with info.open("rb") as handle:
                executable = plistlib.load(handle).get("CFBundleExecutable")
        except (OSError, plistlib.InvalidFileException) as exc:
            raise LaunchError("The macOS Player bundle is invalid") from exc
        if (not isinstance(executable, str) or not executable or Path(executable).name != executable
                or executable in (".", "..")):
            raise LaunchError("The macOS Player bundle has an invalid executable")
        player = player / "Contents" / "MacOS" / executable
    if not player.is_file():
        raise LaunchError("Player executable was not found")
    if os.name != "nt" and not os.access(player, os.X_OK):
        raise LaunchError("Player executable is not executable")
    return player


def validate_ssh_target(value: str) -> str:
    if not _TARGET.fullmatch(value) or value.startswith("-"):
        raise LaunchError("SSH target must be an explicit user@host or host value")
    return value


def ensure_port_available(port: int) -> None:
    """Fail before spawning; never adopt or terminate another process's port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        # Unix permits a new listener to reuse a just-closed connection's local
        # address only with this option.  Do not enable it on Windows: there it
        # can weaken this probe's guarantee that an existing listener is found.
        if os.name != "nt":
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind(("127.0.0.1", port))
        except OSError as exc:
            raise LaunchError("The requested local video port is occupied; the existing process was preserved") from exc


def health_url(port: int) -> str:
    return f"http://127.0.0.1:{port}{HEALTH_PATH}"


def read_health(port: int) -> dict[str, Any]:
    """Read and validate the loopback health contract without credentials."""
    request = Request(health_url(port), method="GET", headers={"Accept": "application/json"})
    try:
        opener = build_opener(ProxyHandler({}), _NoRedirect())
        with opener.open(request, timeout=HEALTH_TIMEOUT_SECONDS) as response:
            if response.status != 200:
                raise LaunchError("Video health endpoint returned an unexpected status")
            length = response.headers.get("Content-Length")
            if length is not None and (not length.isdigit() or int(length) > MAX_HEALTH_BYTES):
                raise LaunchError("Video health endpoint response is too large")
            body = response.read(MAX_HEALTH_BYTES + 1)
            if len(body) > MAX_HEALTH_BYTES:
                raise LaunchError("Video health endpoint response is too large")
            payload = json.loads(body.decode("utf-8"))
    except LaunchError:
        raise
    except (OSError, HTTPError, URLError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LaunchError("Video backend health endpoint is unavailable") from exc
    required = {"service", "instanceId", "uptimeSeconds", "viewers", "streams"}
    streams = payload.get("streams") if isinstance(payload, dict) else None
    if (not isinstance(payload, dict) or set(payload) != required
            or payload["service"] != "flylingual-video"
            or not isinstance(payload["instanceId"], str) or not payload["instanceId"]
            or isinstance(payload["uptimeSeconds"], bool) or not isinstance(payload["uptimeSeconds"], (int, float))
            or not math.isfinite(payload["uptimeSeconds"]) or payload["uptimeSeconds"] < 0
            or type(payload["viewers"]) is not int or payload["viewers"] < 0
            or not isinstance(streams, list) or len(streams) > 8
            or any(not isinstance(stream, dict)
                   or not isinstance(stream.get("streamId"), str)
                   or stream.get("state") not in ("waiting", "live", "stale") for stream in streams)):
        raise LaunchError("Video backend health response is invalid")
    try:
        if str(uuid.UUID(payload["instanceId"])) != payload["instanceId"]:
            raise ValueError
    except ValueError as exc:
        raise LaunchError("Video backend health response is invalid") from exc
    return payload


def wait_for_health(port: int, children: list[Child], expected_instance_id: str | None) -> dict[str, Any]:
    deadline = time.monotonic() + STARTUP_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        stopped = next((child for child in children if child.process.poll() is not None), None)
        if stopped is not None:
            raise LaunchError(f"{stopped.name} stopped before video health became ready")
        try:
            health = read_health(port)
        except LaunchError:
            time.sleep(POLL_SECONDS)
            continue
        if expected_instance_id is not None and health["instanceId"] != expected_instance_id:
            raise LaunchError("Video health belongs to a different local process")
        return health
    raise LaunchError("Video backend health did not become ready before timeout")


def _is_sensitive_environment_name(name: str) -> bool:
    key = name.upper()
    if key == "FLY_VIDEO_PUBLISH_TOKEN":
        return False
    return ("APIKEY" in key or "API_KEY" in key or "SECRET" in key or "PASSWORD" in key
            or "CREDENTIAL" in key or "ACCESS_TOKEN" in key or "REFRESH_TOKEN" in key
            or "AUTH_TOKEN" in key or "TOKEN" in key
            or key.startswith(("OPENAI_", "ANTHROPIC_", "AWS_")))


def child_environment(prefer_file_token: bool) -> dict[str, str]:
    environment = {name: value for name, value in os.environ.items()
                   if not _is_sensitive_environment_name(name)}
    if prefer_file_token:
        environment.pop("FLY_VIDEO_PUBLISH_TOKEN", None)
    return environment


def _popen(command: list[str], environment: dict[str, str]) -> subprocess.Popen:
    kwargs: dict[str, Any] = {"env": environment, "cwd": str(ROOT)}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    return subprocess.Popen(command, **kwargs)


def start_backend(config_path: Path, environment: dict[str, str], instance_id: str) -> Child:
    environment = {**environment, "FLY_VIDEO_INSTANCE_ID": instance_id}
    return Child("backend", _popen([sys.executable, str(ROOT / "tools" / "video.py"), "serve",
                                           "--config", str(config_path)], environment))


def start_tunnel(target: str, local_port: int, remote_port: int, environment: dict[str, str]) -> Child:
    command = ["ssh", "-N", "-o", "BatchMode=yes", "-o", "ExitOnForwardFailure=yes",
               "-o", "ServerAliveInterval=15", "-o", "ServerAliveCountMax=3", "-L",
               f"127.0.0.1:{local_port}:127.0.0.1:{remote_port}", target]
    return Child("sshTunnel", _popen(command, environment))


def start_player(player: Path, publisher_config: Path, run_folder: Path,
                 environment: dict[str, str]) -> Child:
    run_folder.mkdir(parents=True, exist_ok=False)
    command = [str(player), "-flyVideoConfig", str(publisher_config),
               "-logFile", str(run_folder / "player.log")]
    return Child("unityPlayer", _popen(command, environment))


def _wait(process: subprocess.Popen, seconds: float) -> bool:
    try:
        process.wait(timeout=seconds)
        return True
    except subprocess.TimeoutExpired:
        return False


def _kill_group(process: subprocess.Popen, graceful_signal: int | None = None) -> None:
    if process.poll() is not None:
        return
    try:
        if os.name == "nt":
            if graceful_signal == signal.SIGINT:
                process.send_signal(signal.CTRL_BREAK_EVENT)
            else:
                process.terminate()
        elif graceful_signal is not None:
            os.killpg(process.pid, graceful_signal)
        else:
            os.killpg(process.pid, signal.SIGTERM)
    except (OSError, ProcessLookupError):
        return


def stop_children(children: list[Child]) -> None:
    """Stop only process groups created by this invocation, in reverse dependency order."""
    for child in reversed(children):
        if child.process.poll() is None:
            _kill_group(child.process, signal.SIGINT if child.name == "backend" else None)
    deadline = time.monotonic() + SHUTDOWN_SECONDS
    for child in reversed(children):
        remaining = max(0.0, deadline - time.monotonic())
        _wait(child.process, remaining)
    for child in reversed(children):
        if child.process.poll() is None:
            try:
                if os.name == "nt":
                    child.process.kill()
                else:
                    os.killpg(child.process.pid, signal.SIGKILL)
            except (OSError, ProcessLookupError):
                pass
            _wait(child.process, 1.0)


def make_run_folder() -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    return ROOT / "artifacts" / "video-runs" / stamp


class MetricsWriter:
    def __init__(self, output: Path | None):
        self.handle = None
        self.next_sample = 0.0
        self.processes: dict[int, psutil.Process] = {}
        if output is not None:
            output.parent.mkdir(parents=True, exist_ok=True)
            self.handle = output.open("a", encoding="utf-8")

    def register(self, child: Child) -> None:
        if self.handle is None:
            return
        try:
            process = psutil.Process(child.process.pid)
            process.cpu_percent(interval=None)  # Prime psutil's delta counter once per owned child.
            self.processes[child.process.pid] = process
        except psutil.Error:
            # A child which already exited is reported by the supervisor, never as fabricated metrics.
            pass

    def sample(self, port: int, children: list[Child]) -> None:
        if self.handle is None or time.monotonic() < self.next_sample:
            return
        self.next_sample = time.monotonic() + METRICS_INTERVAL_SECONDS
        try:
            health: dict[str, Any] | None = read_health(port)
            health_error = None
        except LaunchError:
            health, health_error = None, "unavailable"
        child_rows = []
        for child in children:
            process = self.processes.get(child.process.pid)
            try:
                memory = process.memory_info().rss if process is not None else None
                cpu = process.cpu_percent(interval=None) if process is not None else None
                created = process.create_time() if process is not None else None
            except psutil.Error:
                memory, cpu, created = None, None, None
            child_rows.append({"role": child.name, "pid": child.process.pid,
                               "createdAtUnix": created, "cpuPercent": cpu, "rssBytes": memory,
                               "returnCode": child.process.poll()})
        row = {"utc": datetime.now(timezone.utc).isoformat(), "health": health,
               "healthError": health_error, "children": child_rows}
        self.handle.write(json.dumps(row, separators=(",", ":")) + "\n")
        self.handle.flush()

    def close(self) -> None:
        if self.handle is not None:
            self.handle.close()


def supervise(*, config_path: Path, config: dict[str, Any], player_value: str | None,
              publisher_path: Path | None, ssh_target: str | None, duration: int | None,
              metrics_output: Path | None) -> int:
    """Run local children in the foreground and return a conventional process status."""
    if duration is not None and not 1 <= duration <= MAX_DURATION_SECONDS:
        raise LaunchError(f"Duration must be between 1 and {MAX_DURATION_SECONDS} seconds")
    publisher_token_file: str | None = None
    if publisher_path is not None:
        publisher_port, publisher_token_file = load_publisher_config(publisher_path, config["streams"])
    else:
        publisher_port = config["port"]
    if publisher_path is not None and publisher_port != config["port"]:
        raise LaunchError("Publisher endpoint port must match the backend configuration")
    target = validate_ssh_target(ssh_target) if ssh_target is not None else None
    if player_value is not None and publisher_path is None:
        candidate = config_path.parent / "publisher.json"
        if not candidate.is_file():
            raise LaunchError("Player launch requires a publisher configuration")
        publisher_path = candidate.resolve()
        publisher_port, publisher_token_file = load_publisher_config(publisher_path, config["streams"])
        if publisher_port != config["port"]:
            raise LaunchError("Publisher endpoint port must match the backend configuration")
    if player_value is not None and publisher_path is None:
        raise LaunchError("Player launch requires a publisher configuration")

    children: list[Child] = []
    metrics = MetricsWriter(metrics_output)
    clean_exit = False
    previous_term_handler = signal.getsignal(signal.SIGTERM)

    def interrupted(_signum, _frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, interrupted)
    try:
        # Preserve the existing explicit video-token override; remove unrelated credentials.
        environment = child_environment(prefer_file_token=False)
        backend_token = config["publishToken"]
        if player_value is not None:
            publisher_token = environment.get("FLY_VIDEO_PUBLISH_TOKEN") or _file_token(publisher_path, publisher_token_file)
            if publisher_token is None:
                raise LaunchError("Publisher token file is unavailable")
            import hmac
            if not hmac.compare_digest(publisher_token, backend_token):
                raise LaunchError("Publisher token does not match the video backend")
        if target is None:
            ensure_port_available(config["port"])
            instance_id = str(uuid.uuid4())
            children.append(start_backend(config_path, environment, instance_id))
            local_port = config["port"]
        else:
            ensure_port_available(publisher_port)
            children.append(start_tunnel(target, publisher_port, config["port"], environment))
            local_port = publisher_port
            instance_id = None
        metrics.register(children[-1])
        wait_for_health(local_port, children, instance_id)
        if player_value is not None:
            children.append(start_player(resolve_player(player_value), publisher_path, make_run_folder(), environment))
            metrics.register(children[-1])
        print(json.dumps({"mode": "ssh-tunnel" if target else "local-backend", "health": health_url(local_port),
                          "playerStarted": player_value is not None}, separators=(",", ":")), flush=True)
        started = time.monotonic()
        while True:
            metrics.sample(local_port, children)
            stopped = next((child for child in children if child.process.poll() is not None), None)
            if stopped is not None:
                raise LaunchError(f"{stopped.name} stopped unexpectedly")
            if duration is not None and time.monotonic() - started >= duration:
                clean_exit = True
                return 0
            time.sleep(POLL_SECONDS)
    except KeyboardInterrupt:
        clean_exit = True
        return 0
    finally:
        # A second termination request must not interrupt owned-child cleanup.
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        try:
            metrics.close()
            stop_children(children)
        finally:
            signal.signal(signal.SIGTERM, previous_term_handler)
        if not clean_exit:
            # The caller reports the sanitized failure and exits nonzero after owned-child cleanup.
            pass


def readonly_status(config: dict[str, Any]) -> dict[str, Any]:
    try:
        health = read_health(config["port"])
    except LaunchError:
        return {"mode": "readonly-health", "backendReachable": False,
                "unityPlayerValidated": False}
    return {"mode": "readonly-health", "backendReachable": True, "health": health,
            "unityPlayerValidated": False}
