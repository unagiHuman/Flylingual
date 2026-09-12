import json
from pathlib import Path
import socket
import tempfile
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import windows_local


class WindowsLocalTests(unittest.TestCase):
    def stack_file(self, folder: Path, **extra):
        data = {
            "bridgePython": "python.exe",
            "bridgeLocalConfig": "bridge-local.json",
            "unityPlayer": "Fly.exe",
            "videoBackendConfig": "backend.json",
            "videoPublisherConfig": "publisher.json",
        }
        data.update(extra)
        path = folder / "stack.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def test_stack_rejects_unknown_keys(self):
        with tempfile.TemporaryDirectory() as raw:
            path = self.stack_file(Path(raw), unexpected=True)
            with self.assertRaises(windows_local.StackError):
                windows_local.read_stack(path)

    def test_occupied_port_is_preserved(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            with self.assertRaises(windows_local.StackError):
                windows_local.assert_ports_free([listener.getsockname()[1]])

    def test_video_endpoint_requires_loopback_windows_stream(self):
        with tempfile.TemporaryDirectory() as raw:
            folder = Path(raw)
            for name in ("python.exe", "bridge-local.json", "Fly.exe", "backend.json", "publisher.json"):
                (folder / name).write_text("{}", encoding="utf-8")
            (folder / "publisher.json").write_text(json.dumps({"endpoint": "http://192.168.1.2:8880", "streamId": "unity-windows"}), encoding="utf-8")
            stack = windows_local.read_stack(self.stack_file(folder,
                bridgePython=str(folder / 'python.exe'), bridgeLocalConfig=str(folder / 'bridge-local.json'),
                unityPlayer=str(folder / 'Fly.exe'), videoBackendConfig=str(folder / 'backend.json'),
                videoPublisherConfig=str(folder / 'publisher.json')))
            bridge = {"profile": "windows-local", "bridge": {"host": "127.0.0.1", "tcpPort": 18770, "controlPort": 18771},
                      "brain": {"host": "127.0.0.1", "port": 18766}, "conversation": {"mode": "off"}}
            with patch.object(windows_local, "load_config", return_value=bridge), patch.object(windows_local, "load_video", return_value={"port": 8880, "streams": ["unity-windows"], "allowedOrigins": ["http://127.0.0.1:18771"]}), patch.object(windows_local, "load_publisher_config", return_value=(8880, "publish-token.txt")):
                with self.assertRaisesRegex(windows_local.StackError, 'loopback HTTP URL'):
                    windows_local.validate(stack, None)

    def test_owned_cleanup_stops_tracked_orphan_after_root_exit(self):
        class FakeProcess:
            def __init__(self, pid, created): self.pid, self.created, self.terminated = pid, created, False
            def create_time(self): return self.created
            def children(self, recursive): raise psutil.NoSuchProcess(self.pid)
            def terminate(self): self.terminated = True
            def kill(self): pass
        import psutil
        root, orphan = FakeProcess(10, 1.0), FakeProcess(11, 2.0)
        with patch.object(windows_local.psutil, "Process", side_effect=[root, psutil.NoSuchProcess(10), psutil.NoSuchProcess(10), orphan]), patch.object(windows_local.psutil, "wait_procs", return_value=([], [])):
            owned = windows_local.Owned("test", SimpleNamespace(pid=10, poll=lambda: None))
            owned.processes[11] = 2.0
            owned.stop()
        self.assertTrue(orphan.terminated)

    def test_owned_cleanup_does_not_touch_reused_root_pid(self):
        class FakeProcess:
            def __init__(self, pid, created): self.pid, self.created, self.terminated = pid, created, False
            def create_time(self): return self.created
            def children(self, recursive): return []
            def terminate(self): self.terminated = True
        original, reused = FakeProcess(10, 1.0), FakeProcess(10, 99.0)
        with patch.object(windows_local.psutil, "Process", side_effect=[original, reused, reused]), patch.object(windows_local.psutil, "wait_procs", return_value=([], [])):
            owned = windows_local.Owned("test", SimpleNamespace(pid=10, poll=lambda: None))
            owned.stop()
        self.assertFalse(reused.terminated)


if __name__ == "__main__":
    unittest.main()
