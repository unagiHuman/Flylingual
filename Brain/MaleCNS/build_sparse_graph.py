"""Build a disk-backed, pair-aggregated structural MaleCNS graph without dense arrays."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import resource
import shutil

import numpy as np
import pyarrow as pa
import pyarrow.feather as feather
import pyarrow.ipc as ipc


PARTITIONS = 256
RECORD_DTYPE = np.dtype([("key", "<u8"), ("weight", "<i8")])


def selected_positions(values: np.ndarray, sorted_ids: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    positions = np.searchsorted(sorted_ids, values)
    valid = positions < len(sorted_ids)
    matched = np.zeros(len(values), dtype=bool)
    matched[valid] = sorted_ids[positions[valid]] == values[valid]
    return positions, matched


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--work", type=Path, required=True)
    args = parser.parse_args()

    annotations = feather.read_table(
        args.data / "body-annotations-male-cns-v1.0-minconf-0.5.feather", columns=["bodyId"]
    )
    selected_ids = np.unique(annotations["bodyId"].to_numpy(zero_copy_only=False))
    if len(selected_ids) > np.iinfo(np.int32).max:
        raise RuntimeError("selected neuron count does not fit int32 indices")

    args.work.mkdir(parents=True, exist_ok=False)
    paths = [args.work / f"part-{index:03d}.bin" for index in range(PARTITIONS)]
    handles = [path.open("wb") for path in paths]
    selected_rows = 0
    try:
        reader = ipc.open_file(pa.memory_map(str(args.data / "connectome-weights-male-cns-v1.0-minconf-0.5.feather"), "r"))
        for batch_index in range(reader.num_record_batches):
            batch = reader.get_batch(batch_index)
            pre = batch.column(0).to_numpy(zero_copy_only=False)
            post = batch.column(1).to_numpy(zero_copy_only=False)
            weight = batch.column(2).to_numpy(zero_copy_only=False)
            pre_idx, pre_ok = selected_positions(pre, selected_ids)
            post_idx, post_ok = selected_positions(post, selected_ids)
            keep = pre_ok & post_ok
            pre_idx = pre_idx[keep].astype(np.uint32, copy=False)
            post_idx = post_idx[keep].astype(np.uint32, copy=False)
            weight = weight[keep].astype(np.int64, copy=False)
            selected_rows += len(weight)
            partitions = pre_idx & (PARTITIONS - 1)
            for partition in np.unique(partitions):
                mask = partitions == partition
                records = np.empty(int(np.count_nonzero(mask)), dtype=RECORD_DTYPE)
                records["key"] = (pre_idx[mask].astype(np.uint64) << np.uint64(32)) | post_idx[mask].astype(np.uint64)
                records["weight"] = weight[mask]
                records.tofile(handles[int(partition)])
    finally:
        for handle in handles:
            handle.close()

    unique_counts: list[int] = []
    duplicate_rows = 0
    for path in paths:
        records = np.fromfile(path, dtype=RECORD_DTYPE)
        if len(records) == 0:
            unique_counts.append(0)
            continue
        order = np.argsort(records["key"], kind="stable")
        records = records[order]
        starts = np.r_[0, np.flatnonzero(records["key"][1:] != records["key"][:-1]) + 1]
        unique_counts.append(len(starts))
        duplicate_rows += len(records) - len(starts)
    edge_count = int(sum(unique_counts))

    args.output.mkdir(parents=True, exist_ok=True)
    np.save(args.output / "body_ids.npy", selected_ids.astype(np.int64, copy=False))
    pre_out = np.lib.format.open_memmap(args.output / "pre_index.npy", mode="w+", dtype=np.int32, shape=(edge_count,))
    post_out = np.lib.format.open_memmap(args.output / "post_index.npy", mode="w+", dtype=np.int32, shape=(edge_count,))
    weight_out = np.lib.format.open_memmap(args.output / "synapse_count.npy", mode="w+", dtype=np.int64, shape=(edge_count,))
    cursor = 0
    for path in paths:
        records = np.fromfile(path, dtype=RECORD_DTYPE)
        if len(records) == 0:
            continue
        order = np.argsort(records["key"], kind="stable")
        records = records[order]
        starts = np.r_[0, np.flatnonzero(records["key"][1:] != records["key"][:-1]) + 1]
        keys = records["key"][starts]
        sums = np.add.reduceat(records["weight"], starts)
        count = len(starts)
        pre_out[cursor:cursor + count] = (keys >> np.uint64(32)).astype(np.int32)
        post_out[cursor:cursor + count] = (keys & np.uint64(0xFFFFFFFF)).astype(np.int32)
        weight_out[cursor:cursor + count] = sums
        cursor += count
    pre_out.flush(); post_out.flush(); weight_out.flush()

    manifest = {
        "capturedAtUtc": datetime.now(timezone.utc).isoformat(),
        "datasetId": "male-cns:v1.0",
        "representation": "pair-aggregated structural graph; unsigned synapse counts",
        "neuronCount": int(len(selected_ids)),
        "selectedRowCountBeforePairAggregation": selected_rows,
        "duplicatePairRowCount": int(duplicate_rows),
        "edgeCountAfterPairAggregation": edge_count,
        "indexDtype": "int32",
        "bodyIdDtype": "int64",
        "synapseCountDtype": "int64",
        "signedDynamicsReady": False,
        "signedDynamicsBlocker": "nt_policy.json intentionally leaves transmitter signs unresolved",
        "peakProcessRssBytes": int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss),
    }
    (args.output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    shutil.rmtree(args.work)
    print(f"Wrote {edge_count} aggregated edges to {args.output}")


if __name__ == "__main__":
    main()
