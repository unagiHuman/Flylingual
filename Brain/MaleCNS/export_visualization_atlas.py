#!/usr/bin/env python3
"""Export a compact, real-soma MaleCNS visualization atlas; never simulates."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import sys

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
DATASET_ID = "male-cns:v1.0"
MAX_NEURONS = 65_536
DEFAULT_MAX_NEURONS = 24_000


def _from_root(path: Path) -> Path:
    return (path if path.is_absolute() else ROOT / path).resolve()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical_id(payload: dict) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _worst_case_visualization_payload_bytes(body_ids: list[int]) -> int:
    """Measure a 50 ms count payload without simulating any neuron."""
    payload = {
        "schemaVersion": 1,
        "atlasId": "0" * 64,
        "metric": "window_spike_count",
        "windowMs": 50.0,
        "bodyIds": [str(body_id) for body_id in body_ids],
        "spikeCounts": [500] * len(body_ids),
    }
    return len(json.dumps(payload, separators=(",", ":")).encode("utf-8"))


def _required_ids(config: dict) -> set[int]:
    required = {int(value) for values in config["inputs"].values() for value in values}
    required.update(int(value) for value in config["readouts"].values())
    for axis in config["populations"].values():
        for side in axis.values():
            for values in side.values():
                required.update(int(value) for value in values)
    return required


def _sample_ids(valid_ids: list[int], forced_ids: set[int], maximum: int) -> list[int]:
    forced = sorted(forced_ids.intersection(valid_ids))
    if len(forced) > maximum:
        raise ValueError("valid required IDs exceed --max-neurons")
    remainder = [body_id for body_id in valid_ids if body_id not in forced_ids]
    wanted = maximum - len(forced)
    if wanted >= len(remainder):
        return sorted(forced + remainder)
    # Evenly sample the sorted IDs.  This is reproducible across platforms and
    # avoids deriving any display location that is not present in the source.
    selected = [remainder[index * len(remainder) // wanted] for index in range(wanted)]
    return sorted(forced + selected)


def _load_coordinates(annotation: Path, graph_ids: np.ndarray) -> tuple[dict[int, tuple[float, float, float]], int]:
    try:
        import pyarrow.feather as feather
    except ImportError as exc:
        raise RuntimeError("pyarrow is required to read the MaleCNS Feather annotations") from exc
    table = feather.read_table(annotation, columns=["bodyId", "somaLocation"])
    graph_set = {int(value) for value in graph_ids}
    coordinates: dict[int, tuple[float, float, float]] = {}
    seen_body_ids: set[int] = set()
    for row in table.to_pylist():
        body_id = int(row["bodyId"])
        if body_id in seen_body_ids:
            raise ValueError(f"annotation contains duplicate bodyId {body_id}")
        seen_body_ids.add(body_id)
        location = row["somaLocation"]
        if body_id not in graph_set or not isinstance(location, list) or len(location) != 3:
            continue
        try:
            values = tuple(float(value) for value in location)
        except (TypeError, ValueError, OverflowError):
            continue
        if all(math.isfinite(value) for value in values):
            coordinates[body_id] = values
    return coordinates, int(len(graph_ids) - len(coordinates))


def _unity_neurons(selected_ids: list[int], coordinates: dict[int, tuple[float, float, float]]) -> tuple[list[dict], str]:
    source = np.asarray([coordinates[body_id] for body_id in selected_ids], dtype=np.float64)
    # This is a display orientation only: source z is vertical in Unity, with
    # its sign flipped so the static preview has brain above VNC.
    source_center = (source.min(axis=0) + source.max(axis=0)) / 2.0
    source_span = source.max(axis=0) - source.min(axis=0)
    vertical_span = float(source_span[2])
    scale = 2.0 / (vertical_span if vertical_span > 0.0 else max(float(source_span.max()), 1.0))
    transformed = (source - source_center) * scale
    neurons = [
        {"id": str(body_id), "x": float(point[0]), "y": float(-point[2]), "z": float(point[1])}
        for body_id, point in zip(selected_ids, transformed)
    ]
    coordinate_space = (
        "Unity display orientation; source somaLocation [x,y,z] mapped to Unity [x,y,z]="
        f"[(sourceX-{source_center[0]:.9g})*{scale:.9g},"
        f"-(sourceZ-{source_center[2]:.9g})*{scale:.9g},"
        f"(sourceY-{source_center[1]:.9g})*{scale:.9g}]; uniform scale, source z span targets 2 units"
    )
    return neurons, coordinate_space


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metadata", type=Path, required=True, help="analog handoff metadata JSON")
    parser.add_argument("--graph", type=Path, required=True, help="graph directory containing body_ids.npy")
    parser.add_argument("--config", type=Path, required=True, help="analog temporal config JSON")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--annotations", type=Path,
                        help="optional annotation Feather path; relative paths resolve from the Flylingual root")
    parser.add_argument("--max-neurons", type=int, default=DEFAULT_MAX_NEURONS)
    args = parser.parse_args()
    if not 1 <= args.max_neurons <= MAX_NEURONS:
        parser.error(f"--max-neurons must be between 1 and {MAX_NEURONS}")

    metadata_path = _from_root(args.metadata)
    graph_dir = _from_root(args.graph)
    config_path = _from_root(args.config)
    output_path = _from_root(args.output)
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    annotation_info = metadata["datasetManifest"]["files"]["annotations"]
    if metadata["datasetManifest"].get("dataset") != DATASET_ID:
        raise ValueError("metadata dataset is not male-cns:v1.0")
    annotation = _from_root(args.annotations) if args.annotations else ROOT.parent / "Data" / "malecns" / "v1.0" / annotation_info["filename"]
    source_hash = _sha256(annotation)
    if source_hash != annotation_info["sha256"]:
        raise ValueError("annotation sourceSha256 does not match metadata")
    graph_path = graph_dir / "body_ids.npy"
    graph_ids = np.load(graph_path, mmap_mode="r")
    if graph_ids.ndim != 1 or graph_ids.dtype.kind not in "iu" or len(graph_ids) == 0 or np.any(graph_ids[1:] <= graph_ids[:-1]):
        raise ValueError("graph/body_ids.npy must contain unique ascending integer IDs")
    config = json.loads(config_path.read_text(encoding="utf-8"))
    coordinates, omitted = _load_coordinates(annotation, graph_ids)
    valid_ids = sorted(coordinates)
    required_ids = _required_ids(config)
    missing_required_ids = sorted(required_ids.difference(coordinates))
    selected_ids = _sample_ids(valid_ids, required_ids, args.max_neurons)
    if not selected_ids:
        raise ValueError("no graph neurons have finite soma coordinates")
    max_visualization_payload_bytes = _worst_case_visualization_payload_bytes(selected_ids)
    neurons, coordinate_space = _unity_neurons(selected_ids, coordinates)
    payload = {
        "schemaVersion": 1,
        "datasetId": DATASET_ID,
        "coordinateSpace": coordinate_space,
        "sourceSha256": source_hash,
        "graphIdsSha256": _sha256(graph_path),
        "neurons": neurons,
        "totalGraphNeurons": int(len(graph_ids)),
        "omittedCoordinateCount": omitted,
        "eligibleCoordinateCount": len(valid_ids),
        "selectedNeuronCount": len(neurons),
        "missingRequiredCoordinateCount": len(missing_required_ids),
        "missingRequiredCoordinateIds": [str(body_id) for body_id in missing_required_ids],
        "maxVisualizationPayloadBytes": max_visualization_payload_bytes,
    }
    payload["atlasId"] = _canonical_id(payload)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, separators=(",", ":"), allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"atlasId": payload["atlasId"], "graphNeuronCount":len(graph_ids),
                      "eligibleCoordinateCount":len(valid_ids),"selectedNeuronCount":len(neurons),
                      "omittedCoordinateCount":omitted,"missingRequiredCoordinateCount":len(missing_required_ids),
                      "maxVisualizationPayloadBytes":max_visualization_payload_bytes}, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, KeyError, TypeError, ValueError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
