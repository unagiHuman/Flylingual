"""Summarize actual Player CSV samples; never fill missed physical observations."""
import argparse
import csv
import json
import math
from pathlib import Path


def summarize(folder):
    root = Path(__file__).resolve().parents[1]
    recording = [json.loads(line) for line in (root / "Contracts/fixtures/shiu_game_brain_controller_frames_wire_v1.jsonl").read_text().splitlines()]
    expected = {str(frame["sequence"]): frame for frame in recording}
    results = []
    for path in sorted(Path(folder).rglob("replay_samples_*.csv")):
        rows = list(csv.DictReader(path.open(newline="", encoding="utf-8-sig")))
        mismatches = []
        actions = {}
        for row in rows:
            frame = expected.get(row["sequence"])
            if frame is None or frame["requestedAction"] != row["action"]:
                mismatches.append({"sequence": row["sequence"], "reason": "unknown sequence/action"})
                continue
            for key in ("forward", "turn"):
                if abs(float(row[key]) - frame["motor"][key]) > 0.00051:
                    mismatches.append({"sequence": row["sequence"], "field": key})
            for key, wire in (("DNp09", "DNp09_Hz"), ("DNa02_R", "DNa02_R_Hz"), ("DNa02_L", "DNa02_L_Hz")):
                value = frame["brain"][wire]
                if value is None:
                    if row[key] != "N/A": mismatches.append({"sequence": row["sequence"], "field": key})
                elif row[key] == "N/A" or abs(float(row[key]) - value) > 0.00051:
                    mismatches.append({"sequence": row["sequence"], "field": key})
            actions.setdefault(row["action"], []).append(row)
        groups = {}
        for action, samples in actions.items():
            first, last = samples[0], samples[-1]
            groups[action] = {
                "observedSamples": len(samples),
                "displacementBetweenFirstAndLastObservedFrame": {key: float(last[key]) - float(first[key]) for key in ("dx", "dy", "dz")},
                "yawDeltaDegrees": math.remainder(float(last["yaw"]) - float(first["yaw"]), 360),
            }
        results.append({"csv": str(path), "sampleCount": len(rows), "uniqueRecordedSequences": len({row['sequence'] for row in rows}), "recordingValueMismatches": mismatches, "actions": groups})
    return {"runs": results, "note": "Displacements are measured across observed frames, not independent trials. STOP appears in multiple intervals. Replay timings are recording playback, not Windows Brain performance."}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = summarize(args.folder)
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)
