"""Private, pinned llama.cpp child for the Windows native supervisor.

This module only supports the checked-in Windows local llama_cpp contract.  It
does not discover runtimes, download models, or adopt a process already using
the endpoint.
"""
from __future__ import annotations

import os
import json
from pathlib import Path
import socket
import subprocess
import time
from typing import Any, Callable
from urllib.error import URLError
from urllib.request import ProxyHandler, Request, build_opener
from urllib.parse import urlsplit

try:
    import psutil
except ModuleNotFoundError:
    psutil = None

ROOT = Path(__file__).resolve().parents[1]
INSTALL = ROOT / "artifacts" / "local-llm" / "ollama-v0.34.0" / "lib" / "ollama"
SERVER = INSTALL / "llama-server.exe"
MODEL = ROOT / "artifacts" / "local-llm" / "models" / "blobs" / "sha256-81fb60c7daa80fc1123380b98970b320ae233409f0f71a72ed7b9b0d62f40490"
CUDA = INSTALL / "cuda_v13"
STANDARD_MODEL = "qwen3.5:4b"
STANDARD_PORT = 11436


class LocalIntentError(ValueError):
    pass


class LocalIntentAborted(RuntimeError):
    pass


def specification(config: dict[str, Any]) -> "LocalIntent | None":
    conversation = config["conversation"]
    if conversation.get("intentProvider") != "llama_cpp":
        return None
    endpoint = urlsplit(conversation.get("localIntentUrl", ""))
    if (endpoint.scheme != "http" or endpoint.hostname not in {"127.0.0.1", "localhost"}
            or endpoint.username or endpoint.password or endpoint.port != STANDARD_PORT
            or endpoint.path not in ("", "/") or endpoint.query or endpoint.fragment):
        raise LocalIntentError("llama_cpp local intent endpoint is not the supported 127.0.0.1:11436 endpoint")
    if conversation.get("localIntentModel") != STANDARD_MODEL:
        raise LocalIntentError("llama_cpp local intent model is not the supported pinned model")
    if conversation.get("localIntentFormat") not in {"compact", "label"}:
        raise LocalIntentError("llama_cpp local intent format is not supported")
    return LocalIntent(STANDARD_PORT, conversation["localIntentFormat"])


def _port_is_free(port: int) -> bool:
    if psutil is None:
        raise LocalIntentError("psutil is required to inspect the local intent port")
    try:
        for item in psutil.net_connections(kind="tcp"):
            if item.status == psutil.CONN_LISTEN and item.laddr and item.laddr.port == port:
                return False
    except psutil.Error as exc:
        raise LocalIntentError("Cannot inspect local intent port before launch") from exc
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.bind(("127.0.0.1", port))
    except OSError:
        return False
    finally:
        probe.close()
    return True


class LocalIntent:
    def __init__(self, port: int, local_format: str = "label"):
        self.port = port
        self.local_format = local_format
        self.process: subprocess.Popen[str] | None = None

    def assert_startable(self) -> None:
        if not SERVER.is_file() or not MODEL.is_file():
            raise LocalIntentError("Pinned local llama runtime or model is missing")
        if not _port_is_free(self.port):
            raise LocalIntentError("Local intent port 11436 is occupied; existing process was preserved")

    @property
    def health_url(self) -> str:
        return f"http://127.0.0.1:{self.port}/health"

    def start(self, bridge_python: Path, log: Path, timeout: float, continue_running: Callable[[], bool],
              base_environment: dict[str, str]) -> None:
        self.assert_startable()
        log.parent.mkdir(parents=True, exist_ok=True)
        environment = dict(base_environment)
        environment["GGML_BACKEND_PATH"] = str(CUDA / "ggml-cuda.dll")
        environment["PATH"] = str(CUDA) + os.pathsep + environment.get("PATH", "")
        command = [str(SERVER), "-m", str(MODEL), "-ngl", "all", "--device", "CUDA0", "-c", "8192", "-np", "1",
                   "-b", "1024", "-ub", "1024", "--host", "127.0.0.1", "--port", str(self.port), "--reasoning", "off",
                   "--ctx-checkpoints", "32", "--checkpoint-min-step", "0", "--cache-ram", "512", "--no-webui", "--offline",
                   "--cors-origins", self.health_url, "--no-cors-credentials"]
        with log.open("w", encoding="utf-8", newline="\n") as output:
            self.process = subprocess.Popen(command, cwd=INSTALL, env=environment, stdin=subprocess.DEVNULL, stdout=output,
                                            stderr=subprocess.STDOUT, text=True, creationflags=subprocess.CREATE_NO_WINDOW,
                                            close_fds=True)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not continue_running():
                raise LocalIntentAborted("Local intent startup was stopped by its owner")
            if self.process.poll() is not None:
                raise LocalIntentError(f"Local intent exited during startup (exit {self.process.returncode}); see {log}")
            if self.health():
                break
            time.sleep(.2)
        else:
            raise LocalIntentError(f"Local intent did not become healthy within {timeout:g} seconds; see {log}")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise LocalIntentError(f"Local intent warmup did not start within {timeout:g} seconds; see {log}")
        with log.open("a", encoding="utf-8", newline="\n") as output:
            warm = subprocess.Popen([str(bridge_python), "-B", str(ROOT / "tools" / "prepare_local_intent.py"),
                                     "--provider", "llama_cpp", "--model", STANDARD_MODEL, "--local-format", self.local_format],
                                    cwd=ROOT, env=base_environment, stdin=subprocess.DEVNULL, stdout=output,
                                    stderr=subprocess.STDOUT, text=True, creationflags=subprocess.CREATE_NO_WINDOW, close_fds=True)
            while warm.poll() is None and time.monotonic() < deadline:
                if not continue_running():
                    warm.terminate()
                    raise LocalIntentAborted("Local intent warmup was stopped by its owner")
                time.sleep(.2)
        if warm.poll() is None:
            warm.kill()
            warm.wait(timeout=5)
            raise LocalIntentError(f"Local intent warmup timed out within {timeout:g} seconds; see {log}")
        if warm.returncode != 0:
            raise LocalIntentError(f"Local intent warmup failed (exit {warm.returncode}); see {log}")

    def health(self) -> bool:
        opener = build_opener(ProxyHandler({}))
        try:
            with opener.open(Request(self.health_url, method="GET"), timeout=1) as response:
                return response.status == 200 and json.load(response).get("status") == "ok"
        except (OSError, URLError, ValueError, json.JSONDecodeError):
            return False

    def stop(self) -> None:
        """Terminate only the direct child this object created."""
        if self.process is None or self.process.poll() is not None:
            return
        self.process.terminate()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=5)
