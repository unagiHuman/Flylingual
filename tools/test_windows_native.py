import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
import unittest
from unittest.mock import patch

import psutil

from tools import windows_native


class WindowsNativeTests(unittest.TestCase):
    def test_read_stack_accepts_native_subset_and_resolves_root_relative_paths(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "native.json"
            path.write_text(json.dumps({"bridgePython": ".venv-bridge/Scripts/python.exe",
                                        "bridgeLocalConfig": "Runtime/Config/local.json"}), encoding="utf-8")
            stack = windows_native.read_stack(path)
        self.assertEqual(stack["bridgePython"], windows_native.ROOT / ".venv-bridge/Scripts/python.exe")
        self.assertEqual(stack["heartbeatSeconds"], 10)

    def test_read_stack_accepts_legacy_video_keys_without_requiring_them(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "native.json"
            path.write_text(json.dumps({"bridgePython": "python", "bridgeLocalConfig": "local.json", "unityPlayer": "old.exe"}), encoding="utf-8")
            stack = windows_native.read_stack(path)
        self.assertEqual(stack["unityPlayer"], windows_native.ROOT / "old.exe")

    def test_ports_preserve_existing_listener(self):
        listener = type("Listener", (), {"status": psutil.CONN_LISTEN,
                                           "laddr": type("Address", (), {"port": 18770})()})()
        with patch.object(windows_native.psutil, "net_connections", return_value=[listener]):
            with self.assertRaisesRegex(windows_native.NativeError, "preserved"):
                windows_native.assert_ports_free([18770])

    def test_owner_identity_requires_matching_creation_time(self):
        process = type("Process", (), {"create_time": lambda self: 20.0})()
        with patch.object(windows_native.psutil, "Process", return_value=process):
            self.assertTrue(windows_native.owner_alive(10, 20.0))
            self.assertFalse(windows_native.owner_alive(10, 19.0))

    def test_status_never_serializes_credentials(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "status.json"
            windows_native.write_status(path, "ready", endpoint="ws://127.0.0.1:18771/ws")
            payload = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(payload["endpoint"], "ws://127.0.0.1:18771/ws")
        self.assertNotIn("key", " ".join(payload).lower())

    def test_scrubbed_environment_removes_conversation_secrets(self):
        with patch.dict(windows_native.os.environ, {"OPENAI_API_KEY": "secret", "KEEP_ME": "yes"}, clear=True):
            environment = windows_native.scrubbed_environment()
        self.assertNotIn("OPENAI_API_KEY", environment)
        self.assertEqual(environment["KEEP_ME"], "yes")

    def test_bridge_command_passes_shutdown_file_and_key_file_path(self):
        command = windows_native.bridge_command({"bridgePython": Path("bridge-python"),
                                                  "bridgeLocalConfig": Path("local.json"),
                                                  "keyFile": Path("secret-file.txt")}, Path("stop"))
        self.assertIn("--shutdown-file", command)
        self.assertEqual(command[command.index("--shutdown-file") + 1], "stop")
        self.assertEqual(command[command.index("--key-file") + 1], "secret-file.txt")

    def test_graceful_stop_marks_stopped_when_child_already_exited(self):
        class Exited:
            def poll(self): return 0
        with TemporaryDirectory() as directory:
            directory = Path(directory)
            shutdown, status = directory / "stop", directory / "status.json"
            windows_native.graceful_stop(Exited(), shutdown, status, seconds=0)
            self.assertTrue(shutdown.exists())
            self.assertEqual(json.loads(status.read_text(encoding="utf-8"))["state"], "stopped")

    @unittest.skipUnless(os.name == "nt", "Windows Job Object test")
    def test_kill_on_close_job_ends_only_probe_sleep_child(self):
        with TemporaryDirectory() as directory:
            pid_path = Path(directory) / "child.pid"
            probe = subprocess.run([sys.executable, "-m", "tools.windows_native_job", "--owner-probe", str(pid_path)],
                                   cwd=windows_native.ROOT, capture_output=True, text=True, timeout=15)
            self.assertEqual(probe.returncode, 0, probe.stderr)
            child_pid = int(pid_path.read_text(encoding="ascii"))
            deadline = time.monotonic() + 5
            while psutil.pid_exists(child_pid) and time.monotonic() < deadline:
                time.sleep(.05)
            self.assertFalse(psutil.pid_exists(child_pid), "job-owned sleep child survived its owner")

    @unittest.skipUnless(os.name == "nt", "Windows Job Object test")
    def test_kill_on_close_job_forced_owner_exit_ends_descendants_but_not_sibling(self):
        def wait_for_file(path: Path) -> int:
            deadline = time.monotonic() + 5
            while not path.exists() and time.monotonic() < deadline:
                time.sleep(.05)
            self.assertTrue(path.exists(), f"missing probe output: {path}")
            return int(path.read_text(encoding="ascii"))

        def wait_for_exit(pid: int) -> None:
            deadline = time.monotonic() + 5
            while psutil.pid_exists(pid) and time.monotonic() < deadline:
                time.sleep(.05)
            self.assertFalse(psutil.pid_exists(pid), f"job descendant {pid} survived forced owner exit")

        with TemporaryDirectory() as directory:
            directory = Path(directory)
            child_path, grandchild_path = directory / "child.pid", directory / "grandchild.pid"
            sibling = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], close_fds=True)
            probe = subprocess.Popen([sys.executable, "-m", "tools.windows_native_job", "--owner-probe", str(child_path),
                                      "--grandchild-pid", str(grandchild_path), "--hold"], cwd=windows_native.ROOT,
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, text=True)
            try:
                child_pid = wait_for_file(child_path)
                grandchild_pid = wait_for_file(grandchild_path)
                probe.terminate()
                self.assertIsNotNone(probe.wait(timeout=10))
                wait_for_exit(child_pid)
                wait_for_exit(grandchild_pid)
                self.assertTrue(psutil.pid_exists(sibling.pid), "unrelated sibling was captured by the job")
            finally:
                if probe.poll() is None: probe.kill(); probe.wait(timeout=5)
                if sibling.poll() is None: sibling.terminate(); sibling.wait(timeout=5)


if __name__ == "__main__":
    unittest.main()
