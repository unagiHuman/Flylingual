import unittest
from unittest.mock import patch

from tools import native_local_intent


def config(**conversation):
    return {"conversation": {"intentProvider": "llama_cpp", "localIntentUrl": "http://127.0.0.1:11436",
                              "localIntentModel": "qwen3.5:4b", "localIntentFormat": "label", **conversation}}


class NativeLocalIntentTests(unittest.TestCase):
    def test_non_llama_provider_does_not_launch_a_local_child(self):
        self.assertIsNone(native_local_intent.specification({"conversation": {"intentProvider": "responses"}}))

    def test_only_pinned_endpoint_and_model_are_accepted(self):
        with self.assertRaisesRegex(native_local_intent.LocalIntentError, "supported"):
            native_local_intent.specification(config(localIntentModel="other"))
        with self.assertRaisesRegex(native_local_intent.LocalIntentError, "endpoint"):
            native_local_intent.specification(config(localIntentUrl="http://127.0.0.1:9999"))

    def test_occupied_port_is_preserved(self):
        listener = type("Listener", (), {"status": native_local_intent.psutil.CONN_LISTEN,
                                            "laddr": type("Address", (), {"port": 11436})()})()
        with patch.object(native_local_intent.psutil, "net_connections", return_value=[listener]):
            with self.assertRaisesRegex(native_local_intent.LocalIntentError, "preserved"):
                native_local_intent.LocalIntent(11436).assert_startable()

    def test_stop_only_terminates_the_direct_child(self):
        class Child:
            def __init__(self): self.terminated = self.killed = False
            def poll(self): return None
            def terminate(self): self.terminated = True
            def wait(self, timeout): return 0
            def kill(self): self.killed = True
        child = Child()
        service = native_local_intent.LocalIntent(11436)
        service.process = child
        service.stop()
        self.assertTrue(child.terminated)
        self.assertFalse(child.killed)


if __name__ == "__main__":
    unittest.main()
