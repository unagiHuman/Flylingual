"""Validated, opt-in mapping from a MaleCNS atlas to graph spike counters."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path

import numpy as np


SCHEMA_VERSION = 1
DATASET_ID = "male-cns:v1.0"
MAX_VISUALIZATION_NEURONS = 65_536
MAX_ATLAS_BYTES = 16 * 1024 * 1024
# The bridge limits a full NDJSON line to 2 MiB.  Reserve space for the
# existing brain_frame fields and constrain this optional nested object.
MAX_VISUALIZATION_JSON_BYTES = 1_800_000


@dataclass(frozen=True)
class VisualizationSelection:
    atlas_id: str
    body_ids: list[str]
    graph_indices: np.ndarray


def _canonical_atlas_id(payload: dict) -> str:
    canonical = dict(payload)
    canonical.pop("atlasId", None)
    encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _graph_ids_hash(graph: Path) -> str:
    return hashlib.sha256((graph / "body_ids.npy").read_bytes()).hexdigest()


def _worst_case_payload_bytes(body_ids: list[str]) -> int:
    payload = {
        "schemaVersion": SCHEMA_VERSION,
        "atlasId": "0" * 64,
        "metric": "window_spike_count",
        "windowMs": 50.0,
        "bodyIds": body_ids,
        # A 50 ms window contains 500 simulation ticks, so no neuron can
        # contribute more than 500 count-buffer increments in one frame.
        "spikeCounts": [500] * len(body_ids),
    }
    return len(json.dumps(payload, separators=(",", ":")).encode("utf-8"))


def load_visualization_atlas(path: str | Path, graph: Path, graph_ids: np.ndarray) -> VisualizationSelection:
    """Load an exported atlas and verify it identifies this exact graph.

    The atlas is intentionally independent of simulation state.  It only maps
    atlas-ordered real body IDs to pre-existing whole-network count slots.
    """
    atlas_path = Path(path)
    try:
        if atlas_path.stat().st_size > MAX_ATLAS_BYTES:
            raise ValueError(f"visualization atlas exceeds {MAX_ATLAS_BYTES} bytes")
    except OSError as exc:
        raise ValueError(f"cannot read visualization atlas {atlas_path}: {exc}") from exc
    try:
        atlas = json.loads(atlas_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read visualization atlas {atlas_path}: {exc}") from exc
    if not isinstance(atlas, dict):
        raise ValueError("visualization atlas must be a JSON object")
    if atlas.get("schemaVersion") != SCHEMA_VERSION or atlas.get("datasetId") != DATASET_ID:
        raise ValueError("visualization atlas schemaVersion or datasetId is unsupported")
    if not isinstance(atlas.get("coordinateSpace"), str) or not atlas["coordinateSpace"]:
        raise ValueError("visualization atlas coordinateSpace is invalid")
    source_hash = atlas.get("sourceSha256")
    if not isinstance(source_hash, str) or len(source_hash) != 64 or any(char not in "0123456789abcdef" for char in source_hash):
        raise ValueError("visualization atlas sourceSha256 is invalid")
    if atlas.get("graphIdsSha256") != _graph_ids_hash(graph):
        raise ValueError("visualization atlas graphIdsSha256 does not match graph/body_ids.npy")
    atlas_id = atlas.get("atlasId")
    if not isinstance(atlas_id, str) or atlas_id != _canonical_atlas_id(atlas):
        raise ValueError("visualization atlas atlasId is invalid")
    neurons = atlas.get("neurons")
    if not isinstance(neurons, list) or not neurons or len(neurons) > MAX_VISUALIZATION_NEURONS:
        raise ValueError(f"visualization atlas must contain 1..{MAX_VISUALIZATION_NEURONS} neurons")
    if atlas.get("totalGraphNeurons") != int(len(graph_ids)):
        raise ValueError("visualization atlas totalGraphNeurons does not match graph")
    if not isinstance(atlas.get("omittedCoordinateCount"), int) or atlas["omittedCoordinateCount"] < 0:
        raise ValueError("visualization atlas omittedCoordinateCount is invalid")

    body_ids: list[str] = []
    numeric_ids: list[int] = []
    for neuron in neurons:
        if not isinstance(neuron, dict):
            raise ValueError("visualization atlas neuron must be an object")
        body_id = neuron.get("id")
        if not isinstance(body_id, str) or not body_id.isdecimal() or str(int(body_id)) != body_id:
            raise ValueError("visualization atlas neuron id must be a canonical decimal string")
        coordinates = [neuron.get(axis) for axis in ("x", "y", "z")]
        if not all(isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value)) for value in coordinates):
            raise ValueError("visualization atlas neuron coordinates must be finite numbers")
        body_ids.append(body_id)
        numeric_ids.append(int(body_id))
    if len(set(body_ids)) != len(body_ids):
        raise ValueError("visualization atlas neuron IDs must be unique")
    if _worst_case_payload_bytes(body_ids) > MAX_VISUALIZATION_JSON_BYTES:
        raise ValueError("visualization atlas can exceed the BrainFrame 2 MiB line budget")

    requested = np.asarray(numeric_ids, dtype=np.int64)
    positions = np.searchsorted(graph_ids, requested)
    if np.any(positions >= len(graph_ids)) or not np.array_equal(graph_ids[positions], requested):
        raise ValueError("visualization atlas contains IDs absent from graph")
    return VisualizationSelection(atlas_id=atlas_id, body_ids=body_ids, graph_indices=positions)
