"""Compare real full-graph controllers with/without the inactive sensory extension."""
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "Brain/MaleCNS"))
from analog_controller import MaleCNSAnalogController


def main():
    output = ROOT / "artifacts/neural-feedback/visual-threat-inactive.json"
    if output.exists():
        raise SystemExit("Refusing to overwrite evidence")
    started = time.perf_counter()
    config = ROOT / "Brain/MaleCNS/config/analog_temporal_v1.json"
    # Use the production action vocabulary from the controller.
    from analog_controller import ACTIONS
    schedule = ["STOP"] + [action for action in ACTIONS if action != "STOP"] + ["STOP"]
    records = []
    for enabled in (False, True):
        controller = MaleCNSAnalogController(
            ROOT / "artifacts/neuron_checkpoint", config, seed=20270101, window_ms=50,
            visual_threat_config=ROOT / "Brain/MaleCNS/config/visual_threat_v1.json" if enabled else None,
        ).initialize()
        frames = []
        for action in schedule:
            controller.set_action(action)
            for _ in range(3):
                frame = controller.step()
                frame.pop("performance")
                frame["raw"].pop("visualThreat", None)
                frames.append(frame)
        encoded = json.dumps(frames, sort_keys=True, separators=(",", ":")).encode()
        records.append({"enabled": enabled, "frameCount": len(frames),
                        "numericFrameSha256": hashlib.sha256(encoded).hexdigest()})
        del controller
    result = {"passed": records[0]["numericFrameSha256"] == records[1]["numericFrameSha256"],
              "backend": "MALECNS_EXPERIMENTAL", "mode": "LIVE", "ready": False,
              "scope": "real full-graph controller numerical comparison; no Unity/TCP claim",
              "seed": 20270101, "windowMs": 50, "schedule": schedule, "windowsPerAction": 3,
              "records": records, "wallSeconds": time.perf_counter() - started}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result))
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
