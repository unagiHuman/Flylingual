"""Project a Shiu controller recording onto the existing server frame shape.

No neural rates, motor values, request IDs, or timings are calculated. Missing
measurements remain null. The original recording retains controller-only
provenance (stimulus IDs, decoder calibration, phases, spike counts, backend).
Only Python's standard library is required; the Brain server is never imported.
"""
import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "Contracts/fixtures/shiu_game_brain_controller_frames.jsonl"
OUTPUT = SOURCE.with_name("shiu_game_brain_controller_frames_wire_v1.jsonl")
BRAIN_FIELDS = ("DNp09_Hz", "DNa02_R_Hz", "DNa02_L_Hz", "DNa02Difference_Hz")


def section(frame, name):
    value = frame.get(name)
    if value is not None and not isinstance(value, dict):
        raise ValueError(f"{name} must be an object or null")
    return value or {}


def normalize_frame(frame):
    if not isinstance(frame, dict):
        raise ValueError("each line must contain an object")
    if frame.get("type", "brain_frame") != "brain_frame":
        raise ValueError("only brain_frame records are supported")
    motor = section(frame, "motor")
    brain = section(frame, "brain")
    performance = section(frame, "performance")
    diagnostics = section(frame, "diagnostics")
    # An explicitly present wire section takes precedence, including nulls.
    brain_source = brain if "brain" in frame else frame
    perf_source = performance if "performance" in frame else frame
    return {
        "type": "brain_frame",
        "sequence": frame.get("sequence"),
        "appliedRequestId": frame.get("appliedRequestId"),
        "appliedClientTimeMs": frame.get("appliedClientTimeMs"),
        "requestedAction": frame.get("requestedAction"),
        "brainTimeMs": frame.get("brainTimeMs") if "brainTimeMs" in frame
        else frame.get("brainSimulationTimeMs"),
        "motor": {key: motor.get(key) for key in ("forward", "turn")},
        "brain": {key: brain_source.get(key) for key in BRAIN_FIELDS},
        "performance": {key: perf_source.get(key) for key in ("windowMs", "stepWallTimeMs")},
        "diagnostics": {key: diagnostics.get(key) for key in
                        ("receivedCommandCount", "overwrittenCommandCount", "latestRequestId")},
    }


def reject_constant(value):
    raise ValueError(f"non-finite JSON number: {value}")


def normalize_file(source, destination):
    source, destination = Path(source), Path(destination)
    if source.resolve() == destination.resolve() or (
        destination.exists() and source.samefile(destination)
    ):
        raise ValueError("source recording must not be overwritten")
    raw = source.read_bytes()
    lines = []
    for number, line in enumerate(raw.decode("utf-8-sig").splitlines(), 1):
        if not line.strip():
            continue
        try:
            frame = json.loads(line, parse_constant=reject_constant)
            lines.append(json.dumps(normalize_frame(frame), separators=(",", ":"), allow_nan=False))
        except (ValueError, TypeError) as exc:
            raise ValueError(f"{source}:{number}: {exc}") from exc
    if not lines:
        raise ValueError("source recording contains no frames")
    # Validate the entire input before touching the destination.
    destination.parent.mkdir(parents=True, exist_ok=True)
    output = ("\n".join(lines) + "\n").encode("utf-8")
    destination.write_bytes(output)
    return {"frameCount": len(lines), "sourceSha256": hashlib.sha256(raw).hexdigest(),
            "outputSha256": hashlib.sha256(output).hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=SOURCE)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    print(json.dumps(normalize_file(args.input, args.output), indent=2))


if __name__ == "__main__":
    main()
