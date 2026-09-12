import json
from pathlib import Path
from tempfile import TemporaryDirectory
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
        class Owned:
            process = Exited()
            reconciled = False
            def refresh(self): raise AssertionError("exited child should not refresh")
            def stop(self): self.reconciled = True
        with TemporaryDirectory() as directory:
            directory = Path(directory)
            shutdown, status = directory / "stop", directory / "status.json"
            owned = Owned()
            windows_native.graceful_stop(owned, shutdown, status, seconds=0)
            self.assertTrue(owned.reconciled, 'Tracked orphans must be reconciled after wrapper exit')
            self.assertTrue(shutdown.exists())
            self.assertEqual(json.loads(status.read_text(encoding="utf-8"))["state"], "stopped")


if __name__ == "__main__":
    unittest.main()
