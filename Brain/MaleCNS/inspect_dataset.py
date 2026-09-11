"""Stream-audit MaleCNS annotations, neurotransmitters, and structural edges."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import resource

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.feather as feather
import pyarrow.ipc as ipc


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def arrow_file(path: Path) -> ipc.RecordBatchFileReader:
    return ipc.open_file(pa.memory_map(str(path), "r"))


def peak_rss_bytes() -> int:
    return int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)


def selected_indices(values: np.ndarray, sorted_ids: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    positions = np.searchsorted(sorted_ids, values)
    valid = positions < len(sorted_ids)
    matched = np.zeros(len(values), dtype=bool)
    matched[valid] = sorted_ids[positions[valid]] == values[valid]
    return positions, matched


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    annotation_path = args.data / "body-annotations-male-cns-v1.0-minconf-0.5.feather"
    nt_path = args.data / "body-neurotransmitters-male-cns-v1.0.feather"
    weights_path = args.data / "connectome-weights-male-cns-v1.0-minconf-0.5.feather"

    annotations = feather.read_table(annotation_path)
    annotation_ids = annotations["bodyId"].to_numpy(zero_copy_only=False)
    selected_ids = np.unique(annotation_ids)
    if len(selected_ids) != len(annotation_ids):
        duplicate_annotation_rows = int(len(annotation_ids) - len(selected_ids))
    else:
        duplicate_annotation_rows = 0

    nt = feather.read_table(nt_path, columns=["body", "consensus_nt"])
    nt_ids = nt["body"].to_numpy(zero_copy_only=False)
    nt_categories = np.asarray(nt["consensus_nt"].to_pylist(), dtype=object)
    nt_order = np.argsort(nt_ids)
    nt_ids_sorted = nt_ids[nt_order]
    nt_categories_sorted = nt_categories[nt_order]
    selected_nt_pos, selected_has_nt = selected_indices(selected_ids, nt_ids_sorted)
    selected_category_counts: Counter[str] = Counter()
    for pos, present in zip(selected_nt_pos, selected_has_nt):
        selected_category_counts[str(nt_categories_sorted[pos]) if present else "missing"] += 1

    edge_rows_by_nt: Counter[str] = Counter()
    edge_weight_by_nt: Counter[str] = Counter()
    raw_rows = raw_weight = selected_rows = selected_weight = 0
    outside_rows = outside_weight = self_rows = self_weight = zero_rows = 0
    selected_pre_ids: set[int] = set()
    selected_post_ids: set[int] = set()

    reader = arrow_file(weights_path)
    for batch_index in range(reader.num_record_batches):
        batch = reader.get_batch(batch_index)
        pre = batch.column(batch.schema.get_field_index("body_pre")).to_numpy(zero_copy_only=False)
        post = batch.column(batch.schema.get_field_index("body_post")).to_numpy(zero_copy_only=False)
        weight = batch.column(batch.schema.get_field_index("weight")).to_numpy(zero_copy_only=False)
        raw_rows += len(pre)
        raw_weight += int(weight.sum(dtype=np.int64))
        zero_rows += int(np.count_nonzero(weight == 0))
        same = pre == post
        self_rows += int(np.count_nonzero(same))
        self_weight += int(weight[same].sum(dtype=np.int64))
        pre_pos, pre_ok = selected_indices(pre, selected_ids)
        _, post_ok = selected_indices(post, selected_ids)
        keep = pre_ok & post_ok
        selected_rows += int(np.count_nonzero(keep))
        selected_weight += int(weight[keep].sum(dtype=np.int64))
        outside = ~keep
        outside_rows += int(np.count_nonzero(outside))
        outside_weight += int(weight[outside].sum(dtype=np.int64))
        selected_pre_ids.update(map(int, pre[keep]))
        selected_post_ids.update(map(int, post[keep]))

        kept_pre = pre[keep]
        kept_weight = weight[keep]
        nt_pos, has_nt = selected_indices(kept_pre, nt_ids_sorted)
        categories = np.full(len(kept_pre), "missing", dtype=object)
        categories[has_nt] = nt_categories_sorted[nt_pos[has_nt]]
        for category in np.unique(categories):
            category_mask = categories == category
            key = str(category)
            edge_rows_by_nt[key] += int(np.count_nonzero(category_mask))
            edge_weight_by_nt[key] += int(kept_weight[category_mask].sum(dtype=np.int64))

    incident_ids = selected_pre_ids | selected_post_ids
    payload = {
        "capturedAtUtc": datetime.now(timezone.utc).isoformat(),
        "datasetId": "male-cns:v1.0",
        "inputs": {
            path.name: {"bytes": path.stat().st_size, "sha256": sha256(path)}
            for path in (annotation_path, nt_path, weights_path)
        },
        "annotations": {
            "rowCount": int(len(annotation_ids)),
            "nullIdCount": int(annotations["bodyId"].null_count),
            "duplicateIdRowCount": duplicate_annotation_rows,
            "selectedNeuronCount": int(len(selected_ids)),
            "minId": str(int(selected_ids.min())),
            "maxId": str(int(selected_ids.max())),
            "selectedNtCategoryCounts": dict(sorted(selected_category_counts.items())),
        },
        "neurotransmitters": {
            "rowCount": int(len(nt_ids)),
            "uniqueIdCount": int(len(np.unique(nt_ids))),
            "selectedMissingCount": int(np.count_nonzero(~selected_has_nt)),
        },
        "structuralGraph": {
            "rawRowCount": raw_rows,
            "rawSynapseCount": raw_weight,
            "selectedRowCountBeforePairAggregation": selected_rows,
            "selectedSynapseCount": selected_weight,
            "outsideSelectionRowCount": outside_rows,
            "outsideSelectionSynapseCount": outside_weight,
            "selfEdgeRowCount": self_rows,
            "selfEdgeSynapseCount": self_weight,
            "zeroWeightRowCount": zero_rows,
            "selectedPreNeuronCount": len(selected_pre_ids),
            "selectedPostNeuronCount": len(selected_post_ids),
            "selectedIncidentNeuronCount": len(incident_ids),
            "selectedIsolatedNeuronCount": int(len(selected_ids) - len(incident_ids)),
            "outputRowsByConsensusNt": dict(sorted(edge_rows_by_nt.items())),
            "outputSynapseCountByConsensusNt": dict(sorted(edge_weight_by_nt.items())),
            "duplicatePairCount": None,
            "selectedEdgeCountAfterPairAggregation": None,
            "aggregationStatus": "computed by build_sparse_graph.py",
        },
        "peakProcessRssBytes": peak_rss_bytes(),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
